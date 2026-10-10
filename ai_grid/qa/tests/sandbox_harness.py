"""
tests/sandbox_harness.py — Programmatic Sandbox Harness for Automata Grid.

Provides an isolated, in-memory/ephemeral async harness for end-to-end
testing of the Automata Grid engine, command router, AI player bots,
and database persistence without connecting to external networks.
"""

import asyncio
import os
import shutil
import sys
import time
import tempfile
from typing import Dict, List, Optional, Any

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode as DBGridNode, Player, InventoryItem
from ai_grid.manager import GridNode as EngineGridNode
from ai_grid.grid_llm import ArenaLLM
from ai_grid.qa.tests.e2e.fixtures import MockIRCServer, MockLLMServer, TestEnvironment


class SandboxHarness:
    """
    Programmatic test harness managing the full offline lifecycle of
    Automata Grid (Mock IRC, Mock LLM, SQLite DB, Engine GridNode, and Mock Client).
    """

    def __init__(
        self,
        channel: str = "#automatagrid",
        prefix: str = "x",
        player_nick: str = "TestPlayer",
        admin_nick: str = "TestAdmin",
        manager_nick: str = "ArenaMaster",
        network_name: str = "mocknet",
        enable_pacing: bool = False,
    ):
        self.channel = channel
        self.prefix = prefix.strip().lower()
        self.player_nick = player_nick
        self.admin_nick = admin_nick
        self.manager_nick = manager_nick
        self.network_name = network_name
        self.enable_pacing = enable_pacing

        # Managed fixtures
        self.env: Optional[TestEnvironment] = None
        self.irc_server: Optional[MockIRCServer] = None
        self.llm_server: Optional[MockLLMServer] = None
        self.db: Optional[ArenaDB] = None
        self.engine_node: Optional[EngineGridNode] = None

        # Background tasks and client streams
        self._background_tasks: List[asyncio.Task] = []
        self._client_reader: Optional[asyncio.StreamReader] = None
        self._client_writer: Optional[asyncio.StreamWriter] = None
        self._client_drain_task: Optional[asyncio.Task] = None
        self._is_started: bool = False

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        """Boot all mock servers, temporary database, and the engine node."""
        if self._is_started:
            return

        # 1. Start Mock IRC & LLM Servers
        self.irc_server = MockIRCServer()
        await self.irc_server.start()

        self.llm_server = MockLLMServer()
        self.llm_server.start()

        # 2. Setup Test Environment & Ephemeral DB
        self.env = TestEnvironment(prefix="sandbox_harness_")
        await self.env.setup()
        self.db = self.env.db

        # Seed procedural grid
        await self.db.seed_grid_expansion()

        # Write config.json for the engine
        self.env.write_config_json(
            irc_server="127.0.0.1",
            irc_port=self.irc_server.port,
            channel=self.channel,
            nickname=self.manager_nick,
            prefix=self.prefix,
            llm_endpoint=self.llm_server.get_endpoint(),
        )

        # Write config.ini for bot client
        self.env.write_config_ini(
            irc_server="127.0.0.1",
            irc_port=self.irc_server.port,
            channel=self.channel,
            manager_nick=self.manager_nick,
            prefix=self.prefix,
            llm_endpoint=self.llm_server.get_endpoint(),
        )

        # 3. Seed Default Player & Admin Characters
        await self.env.create_test_player(
            nickname=self.player_nick,
            network=self.network_name,
            credits=2000.0,
        )
        if self.admin_nick.lower() != self.player_nick.lower():
            await self.env.create_test_player(
                nickname=self.admin_nick,
                network=self.network_name,
                credits=50000.0,
            )

        # 4. Patch manager and database configs
        sandbox_config = {
            "networks": {
                self.network_name: {
                    "server": "127.0.0.1",
                    "port": self.irc_server.port,
                    "ssl": False,
                    "nickname": self.manager_nick,
                    "channel": self.channel,
                    "cmd_prefix": self.prefix,
                    "enabled": True,
                }
            },
            "database": {"file": self.env.db_path},
            "logging": {"level": "INFO"},
            "llm": {
                "endpoint": self.llm_server.get_endpoint(),
                "model": "mock-model",
                "temperature": 0.7,
            },
            "admins": [self.admin_nick.lower(), "admin", "testadmin"],
            "flood_messages": {
                "rate_limit": "Slow down! Rate limit exceeded.",
                "lockout": "Excess flood detected. Temporarily muted.",
            },
        }

        import ai_grid.manager as mgr
        import ai_grid.database.core as db_core
        mgr.CONFIG = sandbox_config
        db_core.CONFIG = sandbox_config
        db_core.DB_FILE = self.env.db_path

        # 5. Initialize and Connect Grid Engine Node
        net_config = sandbox_config["networks"][self.network_name]

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

        self.engine_node = EngineGridNode(
            net_name=self.network_name,
            net_config=net_config,
            llm=mock_hub.llm,
            db=self.db,
            hub=mock_hub,
        )
        mock_hub.nodes[self.network_name] = self.engine_node
        self.engine_node.admins = [self.admin_nick.lower(), "admin", "testadmin"]

        # Configure outbound pacing (accelerated for test harness)
        if not self.enable_pacing:
            self.engine_node.flood_config['max_tokens'] = 50.0
            self.engine_node.flood_config['refill_rate'] = 50.0
            async def _fast_outbound_worker():
                while True:
                    try:
                        msg = await self.engine_node.out_queue.get()
                        await self.engine_node.irc.send(msg)
                        self.engine_node.out_queue.task_done()
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        await asyncio.sleep(0.01)
            self.engine_node._outbound_worker = _fast_outbound_worker

        # Launch engine node connection in background task
        engine_task = asyncio.create_task(self.engine_node.connect())
        self._background_tasks.append(engine_task)

        # 6. Wait for Engine Node to Join Game Channel
        chan_key = self.channel.lower()
        mgr_nick = self.manager_nick.lower()
        for _ in range(50):
            if chan_key in self.irc_server.channels and mgr_nick in self.irc_server.channels[chan_key]:
                break
            await asyncio.sleep(0.1)

        # 7. Connect Harness Player Client to Mock IRC
        reader, writer = await asyncio.open_connection("127.0.0.1", self.irc_server.port)
        self._client_reader = reader
        self._client_writer = writer

        # Register client
        writer.write(f"NICK {self.player_nick}\r\nUSER {self.player_nick} 0 * :Harness User\r\n".encode())
        await writer.drain()

        # Wait for MOTD end (376 or 422)
        while True:
            line = (await reader.readline()).decode("utf-8", errors="ignore")
            if "376" in line or "422" in line or not line:
                break

        # Join game channel
        writer.write(f"JOIN {self.channel}\r\n".encode())
        await writer.drain()

        # Drain client reader in background so socket buffers don't overflow
        async def _drain_client():
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        break
            except (asyncio.CancelledError, Exception):
                pass

        self._client_drain_task = asyncio.create_task(_drain_client())
        self._background_tasks.append(self._client_drain_task)

        # Flush initial greetings and channel join announcements
        for _ in range(20):
            if self.engine_node.out_queue.empty():
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)
        self._is_started = True

    async def stop(self):
        """Cleanly tear down all tasks, sockets, servers, and temporary files."""
        if not self._is_started:
            return

        self._is_started = False

        # Close client connection
        if self._client_writer and not self._client_writer.is_closing():
            try:
                self._client_writer.close()
                transport = self._client_writer.transport
                if transport and not transport.is_closing():
                    transport.abort()
                await asyncio.wait_for(self._client_writer.wait_closed(), timeout=0.5)
            except Exception:
                pass

        # Close engine node IRC client
        if self.engine_node and self.engine_node.irc and self.engine_node.irc.writer:
            try:
                self.engine_node.irc.writer.close()
                transport = self.engine_node.irc.writer.transport
                if transport and not transport.is_closing():
                    transport.abort()
                await asyncio.wait_for(self.engine_node.irc.writer.wait_closed(), timeout=0.5)
            except Exception:
                pass

        # Cancel all background tasks
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

        # Stop servers
        if self.irc_server:
            await self.irc_server.stop()
            self.irc_server = None

        if self.llm_server:
            self.llm_server.stop()
            self.llm_server = None

        # Teardown database & temp files
        if self.env:
            await self.env.teardown()
            self.env = None

    async def send_command(
        self,
        command: str,
        nick: Optional[str] = None,
        target: Optional[str] = None,
        wait_reply: bool = True,
        timeout: float = 5.0,
    ) -> Optional[dict]:
        """Inject a player command and optionally await the manager's response."""
        active_nick = nick or self.player_nick
        dest = target or self.channel

        # Format command with prefix if omitted
        cmd_text = command.strip()
        if not cmd_text.startswith(self.prefix + " ") and cmd_text != self.prefix:
            cmd_text = f"{self.prefix} {cmd_text}"

        msg_start_idx = len(self.irc_server.received_messages)
        self.irc_server._message_event.clear()

        # Send command
        if active_nick == self.player_nick and self._client_writer:
            self._client_writer.write(f"PRIVMSG {dest} :{cmd_text}\r\n".encode())
            await self._client_writer.drain()
        else:
            await self.irc_server.send_privmsg(active_nick, dest, cmd_text)

        if not wait_reply:
            return None

        return await self.wait_for_reply(from_nick=self.manager_nick, timeout=timeout, min_index=msg_start_idx)

    async def wait_for_reply(
        self,
        from_nick: Optional[str] = None,
        contains: Optional[str] = None,
        timeout: float = 5.0,
        min_index: int = 0,
    ) -> Optional[dict]:
        """Wait for the manager to reply to channel or client."""
        expected_nick = (from_nick or self.manager_nick).lower()
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            for msg in self.irc_server.received_messages[min_index:]:
                if msg["from"].lower() == expected_nick and msg.get("command", "").upper() in ["PRIVMSG", "NOTICE"]:
                    if "Grid systems nominal" in msg["text"] or "Welcome to the Grid" in msg["text"]:
                        continue
                    if contains is None or contains in msg["text"]:
                        return msg

            try:
                remaining = timeout - (asyncio.get_event_loop().time() - start)
                if remaining > 0:
                    await asyncio.wait_for(self.irc_server._message_event.wait(), timeout=min(0.1, remaining))
                    self.irc_server._message_event.clear()
            except asyncio.TimeoutError:
                pass

        return None

    async def send_raw_irc(self, raw_line: str):
        """Send a raw IRC line into the server."""
        if self._client_writer:
            line = raw_line.rstrip("\r\n") + "\r\n"
            self._client_writer.write(line.encode())
            await self._client_writer.drain()
            await asyncio.sleep(0.05)
        else:
            await self.irc_server.broadcast(raw_line)

    async def get_player_character(self, nick: Optional[str] = None) -> Optional[Character]:
        """Query DB character record for state assertion."""
        target_nick = nick or self.player_nick
        async with self.db.async_session() as session:
            from sqlalchemy import select
            stmt = select(Character).filter_by(name=target_nick)
            res = await session.execute(stmt)
            return res.scalars().first()

    async def get_grid_node(self, name: str) -> Optional[DBGridNode]:
        """Query DB grid node record for state assertion."""
        async with self.db.async_session() as session:
            from sqlalchemy import select
            stmt = select(DBGridNode).filter_by(name=name)
            res = await session.execute(stmt)
            return res.scalars().first()
