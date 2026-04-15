# manager.py - v1.5.0
# Arena Manager — Multi-Network IRC MUD with Auth-Gated Coordination
import asyncio
import json
import sys
import logging
from grid_utils import format_text, build_banner, C_GREEN, C_CYAN, C_RED, C_YELLOW
from grid_llm import ArenaLLM
from grid_db import ArenaDB
from core.irc_client import IRCClient
from core.command_router import CommandRouter
import core.loops as loops
import core.handlers as handlers
import core.arena as arena
import core.security as security

# --- Config Load ---
try:
    with open('config.json', 'r') as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    print("[!] config.json not found. Aborting.")
    sys.exit(1)

# --- Logging Setup ---
log_level_str = CONFIG.get('logging', {}).get('level', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logger = logging.getLogger("manager")
logger.setLevel(log_level)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

fh = logging.FileHandler('manager.log')
fh.setFormatter(formatter)
logger.addHandler(fh)
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

class GridNode:
    def __init__(self, net_name, net_config, llm, db, hub):
        self.net_name = net_name
        self.config = net_config
        self.llm = llm
        self.db = db
        self.hub = hub
        self.prefix = self.config.get('cmd_prefix', 'x').strip().lower() 
        self.irc = IRCClient(net_name, self.config)
        
        self.active_engine = None
        self.match_queue = [] 
        self.ready_players = [] 
        self.pve_task = None 
        self.hype_task = None
        self.registered_bots = 0
        self.pending_pings = {}
        self.channel_users = {}
        self.action_timestamps = {}
        self.pending_registrations = {} 
        self.nickserv_verified = set()  
        self.hype_counter = 0
        self.router = CommandRouter(self)
        
        # Outbound Pacing (Per Network)
        self.out_queue = asyncio.Queue()
        self.last_send_ts = 0
        
        raw_admins = CONFIG.get('admins', [])
        if isinstance(raw_admins, str):
            raw_admins = [x.strip() for x in raw_admins.split(',')]
        self.admins = [a.lower() for a in raw_admins]
        self.pending_encounters = {} 

    async def send(self, message: str, immediate: bool = False):
        """Dispatches a message either immediately or via the paced queue."""
        if immediate:
            await self.irc.send(message)
        else:
            self.out_queue.put_nowait(message)

    async def _outbound_worker(self):
        """Paces outgoing IRC messages at 1 message every 2 seconds."""
        import time
        while True:
            try:
                msg = await self.out_queue.get()
                now = time.time()
                elapsed = now - self.last_send_ts
                
                # Pace at 2 seconds
                wait = max(0, 2.0 - elapsed)
                if wait > 0:
                    await asyncio.sleep(wait)
                
                await self.irc.send(msg)
                self.last_send_ts = time.time()
                self.out_queue.task_done()
            except Exception as e:
                logger.error(f"Outbound Worker Error [{self.net_name}]: {e}")
                await asyncio.sleep(1)

    async def connect(self):
        await self.irc.connect()
        # Start maintenance and pacing tasks
        asyncio.create_task(self._outbound_worker())
        asyncio.create_task(loops.hype_loop(self))
        asyncio.create_task(loops.ambient_event_loop(self))
        asyncio.create_task(loops.arena_call_loop(self))
        asyncio.create_task(loops.idle_payout_loop(self))
        asyncio.create_task(loops.power_tick_loop(self))
        asyncio.create_task(loops.mainframe_loop(self))
        asyncio.create_task(loops.auction_loop(self))
        asyncio.create_task(loops.economic_ticker_loop(self))
        asyncio.create_task(loops.hype_drop_loop(self))
        await self.db.seed_grid_expansion()
        await self.listen_loop()

    # --- Delegated Methods (Core Logic) ---
    async def set_dynamic_topic(self):
        await arena.set_dynamic_topic(self)

    async def trigger_arena_call(self):
        await arena.trigger_arena_call(self)

    async def check_match_start(self):
        await arena.check_match_start(self)

    async def listen_loop(self):
        while True:
            try:
                line = await self.irc.readline()
                if not line: break
                
                msg_idx = line.find(' :')
                header = line[:msg_idx].split() if msg_idx != -1 else line.split()
                msg = line[msg_idx + 2:].strip() if msg_idx != -1 else ""

                if not header: continue
                source_full = header[0][1:] if header[0].startswith(':') else ""
                command = header[1] if header[0].startswith(':') else header[0]
                target = header[2] if header[0].startswith(':') and len(header) > 2 else (header[1] if len(header) > 1 else "")
                source_nick = source_full.split('!')[0] if source_full else ""
                
                if command == "PING":
                    await self.send(f"PONG :{msg if msg else target}", immediate=True)
                elif command == "PONG":
                    ts_str = msg.strip() if msg else target.strip()
                    if ts_str in self.pending_pings:
                        self.pending_pings[ts_str]['server_latency'] = (time.time() - self.pending_pings[ts_str]['start']) * 1000
                        await self._check_ping_complete(ts_str)
                elif command == "354":
                    who_parts = line.split()
                    if len(who_parts) >= 5:
                        who_nick = who_parts[4].lower()
                        who_acct = who_parts[5] if len(who_parts) > 5 else "0"
                        if who_nick and who_acct not in ["0", ""]:
                            self.nickserv_verified.add(who_nick)
                elif command == "353":
                    nicks = msg.replace('@', '').replace('+', '').split()
                    import time
                    now = time.time()
                    for n in nicks:
                        clean_nick = n.split('!')[0].lower()
                        if clean_nick != self.config['nickname'].lower() and clean_nick not in self.channel_users:
                            self.channel_users[clean_nick] = {'join_time': now, 'chat_lines': 0}
                            security.start_registration_timer(self, clean_nick)
                elif command in ["376", "422"]:
                    await self.send(f"JOIN {self.config['channel']}", immediate=True)
                    await self.set_dynamic_topic()
                    online_msg = format_text(f"[MAINFRAME ONLINE] Grid systems nominal. Type '{self.prefix} help' to begin.", C_GREEN, bold=True)
                    await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(online_msg)}")
                elif command == "JOIN":
                    target_chan = msg if msg else target
                    if target_chan.lower() == self.config['channel'].lower() and source_nick.lower() != self.config['nickname'].lower():
                        import time
                        nick_lower = source_nick.lower()
                        if nick_lower not in self.channel_users:
                            self.channel_users[nick_lower] = {'join_time': time.time(), 'chat_lines': 0}
                            security.start_registration_timer(self, nick_lower)
                        welcome = format_text(f"Welcome to the Grid, {source_nick}.", C_CYAN)
                        await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(welcome)}")
                elif command in ["PART", "QUIT"]:
                    self.channel_users.pop(source_nick.lower(), None)
                elif command == "PRIVMSG":
                    if target.lower() == self.config['channel'].lower():
                        self.hype_counter += 1
                        nick_lower = source_nick.lower()
                        if nick_lower in self.channel_users:
                            self.channel_users[nick_lower]['chat_lines'] += 1
                            asyncio.create_task(self.db.update_last_seen(source_nick, self.net_name))
                    
                    if msg.startswith(self.prefix):
                        is_admin = source_nick.lower() in self.admins
                        asyncio.create_task(self.db.update_last_seen(source_nick, self.net_name))
                        asyncio.create_task(self.router.dispatch(source_nick, command, target, msg, is_admin))

            except Exception as e:
                logger.exception(f"Core Loop Error: {e}")

    async def _check_ping_complete(self, ts_str: str):
        data = self.pending_pings.get(ts_str)
        if data and data['client_latency'] is not None and data['server_latency'] is not None:
            c_lat, s_lat = data['client_latency'], data['server_latency']
            msg = format_text(f"PING | Client: {c_lat:.0f}ms | Server: {s_lat:.0f}ms | Total: {c_lat+s_lat:.0f}ms", C_GREEN)
            await self.send(f"PRIVMSG {data['reply_target']} :{build_banner(msg)}")
            self.pending_pings.pop(ts_str, None)

class MasterHub:
    def __init__(self):
        import time
        self.start_time = time.time()
        self.stop_signal = asyncio.Event()
        self.llm = ArenaLLM(CONFIG); self.db = ArenaDB(); self.nodes = {}
    async def start(self):
        # Startup Integrity Audit
        await self.db.verify_integrity()
        
        for net_name, net_config in CONFIG['networks'].items():
            if net_config.get('enabled', True):
                node = GridNode(net_name, net_config, self.llm, self.db, self)
                self.nodes[net_name] = node
                asyncio.create_task(node.connect())
        logger.info(f"Hub initialized. Bridging {len(self.nodes)} networks...")
        await self.stop_signal.wait()

    async def relay_message(self, target_net: str, target_nick: str, message: str) -> bool:
        """Relays a message to a specific target on a different network."""
        node = self.nodes.get(target_net.lower())
        if node:
            await node.send(f"PRIVMSG {target_nick} :{message}")
            return True
        return False

    async def send_memo(self, target_net: str, target_nick: str, message: str) -> bool:
        """Sends a memo via MemoServ to the target network."""
        node = self.nodes.get(target_net.lower())
        if node:
            # Traditional IRC service command
            await node.send(f"PRIVMSG MemoServ :SEND {target_nick} {message}")
            return True
        return False

    async def shutdown(self):
        logger.warning("Shutting down...")
        await self.db.close()
        for node in self.nodes.values():
            if node.irc.writer: 
                node.irc.writer.write(b"QUIT :Mainframe shutdown.\r\n")
                await node.irc.writer.drain()
        self.stop_signal.set()

if __name__ == "__main__":
    hub = MasterHub()
    try: asyncio.run(hub.start())
    except KeyboardInterrupt: asyncio.run(hub.shutdown())
