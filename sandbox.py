#!/usr/bin/env python3
"""
sandbox.py — Standalone Interactive Local Sandbox & REPL for Automata Grid.

Boots Mock IRC, Mock LLM, temporary/persistent SQLite DB, Grid engine,
and an interactive non-blocking REPL with colored ANSI output,
meta-commands (/help, /nick, /role, /spawn, /bots, /kill, /db, /player, /nodes, /raw, /flood, /clear, /quit),
and game command injection.
"""

import argparse
import asyncio
import os
import signal
import sys
import shutil
import tempfile
import time
from typing import Dict, List, Optional, Set

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
except ImportError:
    class _Color:
        CYAN = "\033[36m"
        GREEN = "\033[32m"
        YELLOW = "\033[33m"
        RED = "\033[31m"
        MAGENTA = "\033[35m"
        WHITE = "\033[37m"
        BLUE = "\033[34m"
        RESET = "\033[0m"

    class _Style:
        BRIGHT = "\033[1m"
        DIM = "\033[2m"
        RESET_ALL = "\033[0m"

    Fore = _Color()
    Style = _Style()

from sqlalchemy import text, select

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode as DBGridNode, Player, NetworkAlias, InventoryItem
from ai_grid.manager import GridNode as EngineGridNode
from ai_grid.grid_llm import ArenaLLM
from tests.e2e.fixtures import MockIRCServer, MockLLMServer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automata Grid - Standalone Interactive Local Sandbox",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Network & Server Options
    parser.add_argument("--irc-port", type=int, default=6667, help="Mock IRC port (0 for auto-assign)")
    parser.add_argument("--llm-port", type=int, default=11434, help="Mock LLM port (0 for auto-assign)")
    parser.add_argument("--channel", type=str, default="#AutomataArena", help="Primary game channel")
    parser.add_argument("--prefix", type=str, default="x", help="Grid command prefix")
    parser.add_argument("--manager-nick", type=str, default="xArenaManager", help="Grid manager bot nick")

    # Player & Persona Options
    parser.add_argument("--nick", "-n", type=str, default="Operator", help="Interactive terminal player nick")
    parser.add_argument("--role", choices=["player", "admin", "spectator"], default="player", help="Initial role persona")
    parser.add_argument("--admin-token", type=str, default="sandbox_admin_token_2026", help="Admin authorization token")
    parser.add_argument("--spawn-bot", action="store_true", help="Automatically spawn an autonomous AI fighter bot")
    parser.add_argument("--bot-nick", type=str, default="Unit01", help="Spawned AI fighter nickname")

    # Persistence & Storage Options
    parser.add_argument("--db-path", type=str, default=None, help="Explicit SQLite DB path (default: ephemeral tempdir)")
    parser.add_argument("--keep-db", "--persist", action="store_true", help="Preserve temporary database on exit")

    # Scripted & Debug Options
    parser.add_argument("--exec", type=str, default=None, help="Semicolon-separated commands to execute before REPL/exit")
    parser.add_argument("--no-repl", action="store_true", help="Run headless without interactive terminal prompt")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="System log level")
    parser.add_argument("--log-file", type=str, default="sandbox.log", help="File for background engine logs")
    parser.add_argument("--verbose-irc", action="store_true", help="Print raw IRC protocol lines to terminal")

    return parser.parse_args()


class SandboxBotClient:
    """Lightweight autonomous AI client connecting to Mock IRC for testing."""

    def __init__(self, nick: str, host: str, port: int, channel: str, prefix: str):
        self.nick = nick
        self.host = host
        self.port = port
        self.channel = channel
        self.prefix = prefix
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.running = False
        self.task: Optional[asyncio.Task] = None

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        self.writer.write(f"NICK {self.nick}\r\nUSER {self.nick} 0 * :{self.nick}\r\n".encode())
        await self.writer.drain()

        # Await MOTD
        while True:
            line = (await self.reader.readline()).decode("utf-8", errors="ignore")
            if "376" in line or "422" in line or not line:
                break

        self.writer.write(f"JOIN {self.channel}\r\n".encode())
        await self.writer.drain()
        self.running = True
        self.task = asyncio.create_task(self._bot_loop())

    async def _bot_loop(self):
        while self.running:
            try:
                line_bytes = await self.reader.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="ignore").strip()
                # Bot responds to turn notices or periodic actions
                if "[GRID]" in line and "Awaiting public commands" in line:
                    await asyncio.sleep(0.5)
                    self.writer.write(f"PRIVMSG {self.channel} :{self.prefix} explore\r\n".encode())
                    await self.writer.drain()
            except (asyncio.CancelledError, Exception):
                break

    async def disconnect(self):
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
        if self.writer and not self.writer.is_closing():
            try:
                self.writer.write(b"QUIT :Bot leaving\r\n")
                await self.writer.drain()
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass


class SandboxEnvironment:
    """Manages full offline engine lifecycle (Mock IRC, Mock LLM, DB, GridNode, Bots)."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.temp_dir: Optional[str] = None
        self.db_path: str = ""
        self.db: Optional[ArenaDB] = None
        self.irc_server: Optional[MockIRCServer] = None
        self.llm_server: Optional[MockLLMServer] = None
        self.grid_node: Optional[EngineGridNode] = None
        self.node_task: Optional[asyncio.Task] = None
        self.bots: Dict[str, SandboxBotClient] = {}
        self.shutdown_event = asyncio.Event()

    async def boot(self):
        # 1. Setup isolated database directory
        if self.args.db_path:
            self.db_path = os.path.abspath(self.args.db_path)
            self.temp_dir = os.path.dirname(self.db_path)
        else:
            self.temp_dir = tempfile.mkdtemp(prefix="ag_sandbox_")
            self.db_path = os.path.join(self.temp_dir, "sandbox.db")

        # 2. Boot Mock IRC Server
        self.irc_server = MockIRCServer(host="127.0.0.1", port=self.args.irc_port)
        await self.irc_server.start()
        actual_irc_port = self.irc_server.port

        # 3. Boot Mock LLM Server
        self.llm_server = MockLLMServer(host="127.0.0.1", port=self.args.llm_port)
        self.llm_server.start()

        # 4. Initialize Database Schema & Seed Data
        self.db = ArenaDB(self.db_path)
        await self.db.init_schema()
        await self.db.seed_grid_expansion()

        # 5. Seed Initial Character Persona
        await self._seed_persona(self.args.nick, self.args.role)

        # 6. Configure and Boot Grid Node
        sandbox_config = {
            "networks": {
                "sandboxnet": {
                    "server": "127.0.0.1",
                    "port": actual_irc_port,
                    "ssl": False,
                    "nickname": self.args.manager_nick,
                    "channel": self.args.channel,
                    "cmd_prefix": self.args.prefix,
                    "enabled": True,
                }
            },
            "database": {"file": self.db_path},
            "logging": {"level": self.args.log_level},
            "llm": {
                "endpoint": self.llm_server.get_endpoint(),
                "model": "mock-model",
                "temperature": 0.7,
            },
            "admins": [self.args.nick.lower(), "admin", "sandboxadmin", "operator"],
            "flood_messages": {
                "rate_limit": "Slow down! Rate limit exceeded.",
                "lockout": "Excess flood detected. Temporarily muted.",
            },
        }

        import ai_grid.manager as mgr
        import ai_grid.database.core as db_core
        mgr.CONFIG = sandbox_config
        db_core.CONFIG = sandbox_config
        db_core.DB_FILE = self.db_path

        net_cfg = sandbox_config["networks"]["sandboxnet"]
        mock_hub = type("MockHub", (), {
            "start_time": time.time(),
            "nodes": {},
            "llm": ArenaLLM(sandbox_config),
            "db": self.db,
            "relay_message": lambda *args, **kwargs: asyncio.sleep(0),
            "send_memo": lambda *args, **kwargs: asyncio.sleep(0),
            "restart": lambda *args, **kwargs: asyncio.sleep(0),
            "shutdown": lambda *args, **kwargs: asyncio.sleep(0),
        })()

        self.grid_node = EngineGridNode("sandboxnet", net_cfg, mock_hub.llm, self.db, mock_hub)
        mock_hub.nodes["sandboxnet"] = self.grid_node
        self.grid_node.admins = [self.args.nick.lower(), "admin", "sandboxadmin", "operator"]

        # Fast outbound pacing for interactive responsiveness
        async def _fast_outbound_worker():
            while True:
                try:
                    msg = await self.grid_node.out_queue.get()
                    await self.grid_node.irc.send(msg)
                    self.grid_node.out_queue.task_done()
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(0.01)

        self.grid_node._outbound_worker = _fast_outbound_worker
        self.node_task = asyncio.create_task(self.grid_node.connect())

        # 7. Await Grid Node Channel Join
        await self._wait_for_grid_ready()

        # 8. Optionally Spawn Autonomous Bot
        if self.args.spawn_bot:
            await self.spawn_bot(self.args.bot_nick)

    async def _wait_for_grid_ready(self, timeout: float = 6.0) -> bool:
        start = asyncio.get_event_loop().time()
        chan_key = self.args.channel.lower()
        mgr_nick = self.args.manager_nick.lower()
        while asyncio.get_event_loop().time() - start < timeout:
            if chan_key in self.irc_server.channels and mgr_nick in self.irc_server.channels[chan_key]:
                return True
            await asyncio.sleep(0.05)
        return False

    async def _seed_persona(self, nick: str, role: str):
        async with self.db.async_session() as session:
            stmt = select(Character).filter_by(name=nick)
            existing = (await session.execute(stmt)).scalars().first()
            if not existing:
                p = Player(global_name=nick)
                session.add(p)
                await session.flush()
                alias = NetworkAlias(player_id=p.id, network_name="sandboxnet", nickname=nick)
                session.add(alias)

                spawn_name = await self.db.get_spawn_node_name()
                node_res = await session.execute(select(DBGridNode).filter_by(name=spawn_name))
                node_obj = node_res.scalars().first()
                node_id = node_obj.id if node_obj else None

                credits = 50000.0 if role in ["admin", "spectator"] else 2000.0
                level = 10 if role == "admin" else 1
                char = Character(
                    player_id=p.id,
                    node_id=node_id,
                    name=nick,
                    race="Wetware",
                    char_class="Zero_Day_Rogue" if role != "spectator" else "Spectator",
                    bio=f"Sandbox persona: {role}",
                    level=level,
                    credits=credits,
                    power=100.0,
                    stability=100.0,
                    auth_token=f"auth_token_{nick.lower()}",
                    status="Active",
                    current_hp=100,
                )
                session.add(char)
                await session.commit()

    async def spawn_bot(self, nick: str) -> SandboxBotClient:
        await self._seed_persona(nick, "player")
        bot = SandboxBotClient(
            nick=nick,
            host="127.0.0.1",
            port=self.irc_server.port,
            channel=self.args.channel,
            prefix=self.args.prefix,
        )
        await bot.connect()
        self.bots[nick] = bot
        return bot

    async def kill_bot(self, nick: str) -> bool:
        if nick in self.bots:
            bot = self.bots.pop(nick)
            await bot.disconnect()
            return True
        return False

    async def shutdown(self):
        self.shutdown_event.set()

        # Cancel node task first to prevent background loops from sending to closing socket
        if self.node_task and not self.node_task.done():
            self.node_task.cancel()

        # Disconnect all bots
        for nick, bot in list(self.bots.items()):
            try:
                await bot.disconnect()
            except Exception:
                pass
        self.bots.clear()

        # Stop Grid Node IRC client
        if self.grid_node and self.grid_node.irc:
            writer = self.grid_node.irc.writer
            self.grid_node.irc.writer = None
            self.grid_node.irc.reader = None
            if writer:
                try:
                    writer.close()
                    transport = writer.transport
                    if transport and not transport.is_closing():
                        transport.abort()
                    await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
                except Exception:
                    pass

        # Close DB
        if self.db:
            try:
                await self.db.close()
            except Exception:
                pass

        # Stop mock servers
        if self.irc_server:
            await self.irc_server.stop()
            self.irc_server = None

        if self.llm_server:
            self.llm_server.stop()
            self.llm_server = None

        # Clean temporary DB directory if requested
        if not self.args.keep_db and self.temp_dir and os.path.exists(self.temp_dir) and not self.args.db_path:
            shutil.rmtree(self.temp_dir, ignore_errors=True)


class SandboxREPL:
    """Asynchronous interactive terminal REPL with prompt protection and colored ANSI output."""

    def __init__(self, env: SandboxEnvironment):
        self.env = env
        self.args = env.args
        self.nick = env.args.nick
        self.role = env.args.role
        self.channel = env.args.channel
        self.prefix = env.args.prefix
        self.manager_nick = env.args.manager_nick
        self.admin_token = env.args.admin_token
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.listen_task: Optional[asyncio.Task] = None
        self.is_interactive = not env.args.no_repl

    def _get_prompt(self) -> str:
        role_color = Fore.YELLOW if self.role == "admin" else (Fore.MAGENTA if self.role == "spectator" else Fore.GREEN)
        return f"{role_color}{self.nick}{Style.RESET_ALL}@{Fore.CYAN}{self.channel}{Style.RESET_ALL} ({role_color}{self.role}{Style.RESET_ALL}) > "

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", self.env.irc_server.port)
        self.writer.write(f"NICK {self.nick}\r\nUSER {self.nick} 0 * :{self.nick}\r\n".encode())
        await self.writer.drain()

        # Wait for MOTD
        while True:
            line = (await self.reader.readline()).decode("utf-8", errors="ignore")
            if "376" in line or "422" in line or not line:
                break

        # Join game channel
        self.writer.write(f"JOIN {self.channel}\r\n".encode())
        await self.writer.drain()

        # Role-based identification
        if self.role == "admin":
            self.env.irc_server.mark_identified(self.nick)
            self.writer.write(f"PRIVMSG NickServ :IDENTIFY {self.admin_token}\r\n".encode())
            self.writer.write(f"PRIVMSG {self.manager_nick} :{self.prefix} admin auth {self.admin_token}\r\n".encode())
            await self.writer.drain()

        # Start listener loop
        self.listen_task = asyncio.create_task(self._listen_loop())

    def _format_message(self, line: str) -> str:
        # Highlight tags
        color_line = line
        color_line = color_line.replace("[SIGACT]", f"{Fore.CYAN}[SIGACT]{Style.RESET_ALL}")
        color_line = color_line.replace("[SIGINT]", f"{Fore.GREEN}[SIGINT]{Style.RESET_ALL}")
        color_line = color_line.replace("[COMBAT]", f"{Fore.RED}[COMBAT]{Style.RESET_ALL}")
        color_line = color_line.replace("[PULSE]", f"{Fore.YELLOW}[PULSE]{Style.RESET_ALL}")
        color_line = color_line.replace("[ERR]", f"{Fore.RED}{Style.BRIGHT}[ERR]{Style.RESET_ALL}")
        color_line = color_line.replace("[SYSTEM]", f"{Fore.BLUE}[SYSTEM]{Style.RESET_ALL}")
        color_line = color_line.replace("[CRITICAL]", f"{Fore.RED}{Style.BRIGHT}[CRITICAL]{Style.RESET_ALL}")
        return color_line

    async def _listen_loop(self):
        while not self.env.shutdown_event.is_set():
            try:
                line_bytes = await self.reader.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="ignore").rstrip("\r\n")
                if not line:
                    continue

                if self.args.verbose_irc:
                    sys.stdout.write(f"\r\033[K{Fore.WHITE}{Style.DIM}[IRC_RAW] {line}{Style.RESET_ALL}\n")
                    if self.is_interactive:
                        sys.stdout.write(self._get_prompt())
                    sys.stdout.flush()

                # Parse IRC message
                if " PRIVMSG " in line:
                    parts = line.split(" PRIVMSG ", 1)
                    src = parts[0].split("!")[0].lstrip(":")
                    dest_and_msg = parts[1].split(" :", 1)
                    dest = dest_and_msg[0]
                    content = dest_and_msg[1] if len(dest_and_msg) > 1 else ""

                    if src.lower() != self.nick.lower():
                        formatted = self._format_message(content)
                        if dest.startswith("#"):
                            out = f"{Fore.CYAN}[{dest}]{Style.RESET_ALL} <{Fore.YELLOW}{src}{Style.RESET_ALL}> {formatted}"
                        else:
                            out = f"{Fore.MAGENTA}[PM from {src}]{Style.RESET_ALL} {formatted}"
                        sys.stdout.write(f"\r\033[K{out}\n")
                        if self.is_interactive:
                            sys.stdout.write(self._get_prompt())
                        sys.stdout.flush()

                elif " NOTICE " in line:
                    parts = line.split(" NOTICE ", 1)
                    src = parts[0].split("!")[0].lstrip(":")
                    dest_and_msg = parts[1].split(" :", 1)
                    content = dest_and_msg[1] if len(dest_and_msg) > 1 else ""
                    if src.lower() != self.nick.lower():
                        formatted = self._format_message(content)
                        out = f"{Fore.YELLOW}[NOTICE from {src}]{Style.RESET_ALL} {formatted}"
                        sys.stdout.write(f"\r\033[K{out}\n")
                        if self.is_interactive:
                            sys.stdout.write(self._get_prompt())
                        sys.stdout.flush()

            except (asyncio.CancelledError, Exception):
                break

    async def handle_input(self, line: str):
        line = line.strip()
        if not line:
            return

        # Meta-commands
        if line.startswith("/"):
            parts = line.split()
            cmd = parts[0].lower()
            args = parts[1:]

            if cmd in ["/help", "/?"]:
                self._print_help()

            elif cmd == "/nick":
                if args:
                    new_nick = args[0]
                    self.nick = new_nick
                    self.writer.write(f"NICK {new_nick}\r\n".encode())
                    await self.writer.drain()
                    print(f"{Fore.GREEN}Nickname changed to: {new_nick}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}Usage: /nick <name>{Style.RESET_ALL}")

            elif cmd == "/role":
                if args and args[0].lower() in ["player", "admin", "spectator"]:
                    self.role = args[0].lower()
                    await self.env._seed_persona(self.nick, self.role)
                    if self.role == "admin":
                        self.env.irc_server.mark_identified(self.nick)
                        self.writer.write(f"PRIVMSG NickServ :IDENTIFY {self.admin_token}\r\n".encode())
                        self.writer.write(f"PRIVMSG {self.manager_nick} :{self.prefix} admin auth {self.admin_token}\r\n".encode())
                        await self.writer.drain()
                    print(f"{Fore.GREEN}Role persona switched to: {self.role}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}Usage: /role <player|admin|spectator>{Style.RESET_ALL}")

            elif cmd == "/spawn":
                bot_nick = args[0] if args else f"Bot_{len(self.env.bots) + 1}"
                print(f"{Fore.CYAN}Spawning bot: {bot_nick}...{Style.RESET_ALL}")
                await self.env.spawn_bot(bot_nick)
                print(f"{Fore.GREEN}Bot {bot_nick} joined {self.channel}.{Style.RESET_ALL}")

            elif cmd == "/bots":
                if self.env.bots:
                    print(f"{Fore.CYAN}Active Bots ({len(self.env.bots)}):{Style.RESET_ALL}")
                    for b_nick in self.env.bots:
                        print(f"  - {b_nick}")
                else:
                    print(f"{Fore.YELLOW}No active bots spawned.{Style.RESET_ALL}")

            elif cmd == "/kill":
                if args:
                    killed = await self.env.kill_bot(args[0])
                    if killed:
                        print(f"{Fore.GREEN}Bot {args[0]} terminated.{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.RED}Bot {args[0]} not found.{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}Usage: /kill <nick>{Style.RESET_ALL}")

            elif cmd == "/db":
                sql = " ".join(args)
                if sql:
                    try:
                        async with self.env.db.async_session() as session:
                            res = await session.execute(text(sql))
                            rows = res.fetchall()
                            print(f"{Fore.CYAN}Query Result ({len(rows)} rows):{Style.RESET_ALL}")
                            for r in rows[:20]:
                                print(f"  {r}")
                            if len(rows) > 20:
                                print(f"  ... [{len(rows) - 20} more rows]")
                    except Exception as e:
                        print(f"{Fore.RED}SQL Error: {e}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}Usage: /db <sql query>{Style.RESET_ALL}")

            elif cmd == "/player":
                target = args[0] if args else self.nick
                async with self.env.db.async_session() as session:
                    char_res = await session.execute(select(Character).filter_by(name=target))
                    c = char_res.scalars().first()
                    if c:
                        loc_name = "Unknown"
                        if c.node_id:
                            n_res = await session.execute(select(DBGridNode).filter_by(id=c.node_id))
                            n_obj = n_res.scalars().first()
                            if n_obj:
                                loc_name = n_obj.name
                        print(f"{Fore.CYAN}=== Character Telemetry: {c.name} ==={Style.RESET_ALL}")
                        print(f"  Class: {c.char_class} ({c.race}) | Level: {c.level}")
                        print(f"  HP: {c.current_hp} | Credits: {c.credits:.1f}c | Power: {c.power:.1f}")
                        print(f"  Location Node: {loc_name} (ID: {c.node_id})")
                        print(f"  Status: {c.status}")
                    else:
                        print(f"{Fore.RED}Character '{target}' not found in database.{Style.RESET_ALL}")

            elif cmd == "/nodes":
                async with self.env.db.async_session() as session:
                    nodes_res = await session.execute(select(DBGridNode).limit(15))
                    nodes = nodes_res.scalars().all()
                    count_res = await session.execute(text("SELECT count(*) FROM grid_nodes"))
                    total_count = count_res.scalar()
                    print(f"{Fore.CYAN}Grid Nodes (Total: {total_count}, displaying first {len(nodes)}):{Style.RESET_ALL}")
                    for n in nodes:
                        print(f"  - [{n.name}] ({n.x},{n.y}) Type: {n.node_type} Lvl: {n.upgrade_level} Mode: {n.availability_mode}")

            elif cmd == "/raw":
                raw_text = " ".join(args)
                if raw_text:
                    self.writer.write(f"{raw_text}\r\n".encode())
                    await self.writer.drain()
                    print(f"{Fore.WHITE}{Style.DIM}-> {raw_text}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.YELLOW}Usage: /raw <raw irc line>{Style.RESET_ALL}")

            elif cmd == "/flood":
                count = int(args[0]) if args and args[0].isdigit() else 6
                print(f"{Fore.YELLOW}Injecting {count} rapid messages to test flood lockout...{Style.RESET_ALL}")
                for i in range(count):
                    self.writer.write(f"PRIVMSG {self.channel} :{self.prefix} status\r\n".encode())
                await self.writer.drain()

            elif cmd == "/clear":
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.flush()

            elif cmd in ["/quit", "/exit"]:
                print(f"{Fore.YELLOW}Shutting down sandbox...{Style.RESET_ALL}")
                self.env.shutdown_event.set()

            else:
                print(f"{Fore.RED}Unknown meta-command: {cmd}. Type /help for assistance.{Style.RESET_ALL}")

        else:
            # Game command
            # Auto-prepend prefix if omitted and not already prefixed with x or !a
            if line.startswith(f"{self.prefix} ") or line == self.prefix or line.startswith("!a "):
                cmd_text = line
            else:
                cmd_text = f"{self.prefix} {line}"

            self.writer.write(f"PRIVMSG {self.channel} :{cmd_text}\r\n".encode())
            await self.writer.drain()

    def _print_help(self):
        print(f"\n{Fore.CYAN}{Style.BRIGHT}==================== AUTOMATA GRID SANDBOX HELP ===================={Style.RESET_ALL}")
        print(f"{Fore.WHITE}{Style.BRIGHT}Meta-Commands:{Style.RESET_ALL}")
        print(f"  {Fore.YELLOW}/help, /?{Style.RESET_ALL}                     Show this command manual")
        print(f"  {Fore.YELLOW}/nick <name>{Style.RESET_ALL}              Change current interactive nickname")
        print(f"  {Fore.YELLOW}/role <player|admin|spec>{Style.RESET_ALL} Switch active persona role")
        print(f"  {Fore.YELLOW}/spawn [nick]{Style.RESET_ALL}             Spawn an autonomous AI bot")
        print(f"  {Fore.YELLOW}/bots{Style.RESET_ALL}                     List active autonomous bots")
        print(f"  {Fore.YELLOW}/kill <nick>{Style.RESET_ALL}              Terminate a spawned bot")
        print(f"  {Fore.YELLOW}/db <sql query>{Style.RESET_ALL}           Execute SQL query on sandbox database")
        print(f"  {Fore.YELLOW}/player [nick]{Style.RESET_ALL}            Inspect player status & stats from DB")
        print(f"  {Fore.YELLOW}/nodes{Style.RESET_ALL}                    List active grid nodes from DB")
        print(f"  {Fore.YELLOW}/raw <irc line>{Style.RESET_ALL}           Inject raw unescaped IRC protocol line")
        print(f"  {Fore.YELLOW}/flood [count]{Style.RESET_ALL}            Send burst of messages to test flood lockout")
        print(f"  {Fore.YELLOW}/clear{Style.RESET_ALL}                    Clear terminal screen")
        print(f"  {Fore.YELLOW}/quit, /exit{Style.RESET_ALL}              Initiate graceful sandbox shutdown")
        print(f"\n{Fore.WHITE}{Style.BRIGHT}Game Commands (Prefix '{self.prefix}' auto-prepended if omitted):{Style.RESET_ALL}")
        print(f"  {Fore.GREEN}explore{Style.RESET_ALL}                   Explore current node sector")
        print(f"  {Fore.GREEN}probe <dir>{Style.RESET_ALL}               Probe adjacent node (north/south/east/west)")
        print(f"  {Fore.GREEN}status, stats{Style.RESET_ALL}             Show current player telemetry")
        print(f"  {Fore.GREEN}inventory{Style.RESET_ALL}                 List inventory items")
        print(f"  {Fore.GREEN}map{Style.RESET_ALL}                       Display grid sector map")
        print(f"  {Fore.GREEN}hack <node>{Style.RESET_ALL}               Infiltrate target node")
        print(f"  {Fore.GREEN}help{Style.RESET_ALL}                      Request engine game help")
        print(f"{Fore.CYAN}{Style.BRIGHT}===================================================================={Style.RESET_ALL}\n")

    async def run(self):
        # 1. Connect REPL socket
        await self.connect()

        # 2. Print Welcome Banner
        print(f"\n{Fore.CYAN}{Style.BRIGHT}====================================================================")
        print("          AUTOMATA GRID LOCAL SANDBOX ENVIRONMENT (v2.0)")
        print("====================================================================" + Style.RESET_ALL)
        print(f"  Manager: {Fore.YELLOW}{self.manager_nick}{Style.RESET_ALL} | Channel: {Fore.CYAN}{self.channel}{Style.RESET_ALL} | Prefix: {Fore.GREEN}{self.prefix}{Style.RESET_ALL}")
        print(f"  Player:  {Fore.GREEN}{self.nick}{Style.RESET_ALL} ({self.role}) | DB: {Fore.WHITE}{self.env.db_path}{Style.RESET_ALL}")
        print(f"  Mock IRC Port: {self.env.irc_server.port} | Mock LLM Port: {self.env.llm_server.port}")
        print(f"  Type {Fore.YELLOW}/help{Style.RESET_ALL} for available meta-commands or game commands.\n")

        # 3. Handle scripted --exec commands
        if self.args.exec:
            commands = [c.strip() for c in self.args.exec.split(";") if c.strip()]
            for cmd in commands:
                print(f"{Fore.WHITE}{Style.DIM}[EXEC] {cmd}{Style.RESET_ALL}")
                await self.handle_input(cmd)
                await asyncio.sleep(0.3)

        # 4. If headless (--no-repl), exit immediately
        if not self.is_interactive:
            return

        # 5. Interactive REPL loop
        while not self.env.shutdown_event.is_set():
            try:
                sys.stdout.write(self._get_prompt())
                sys.stdout.flush()
                line = await asyncio.to_thread(sys.stdin.readline)
                if not line:  # EOF / Ctrl+D
                    self.env.shutdown_event.set()
                    break
                await self.handle_input(line)
            except (asyncio.CancelledError, KeyboardInterrupt):
                self.env.shutdown_event.set()
                break


async def main_async():
    args = parse_args()
    env = SandboxEnvironment(args)

    # Setup signal handlers
    loop = asyncio.get_running_loop()

    def _sig_handler():
        print(f"\n{Fore.YELLOW}Received interrupt signal. Shutting down...{Style.RESET_ALL}")
        env.shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig_handler)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        # Boot mock infrastructure and grid node
        await env.boot()

        # Run REPL
        repl = SandboxREPL(env)
        await repl.run()

    finally:
        print(f"{Fore.CYAN}Tearing down sandbox resources...{Style.RESET_ALL}")
        await env.shutdown()
        print(f"{Fore.GREEN}Sandbox shutdown complete.{Style.RESET_ALL}")


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
