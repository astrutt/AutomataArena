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
        self.router = CommandRouter(self)
        
        raw_admins = CONFIG.get('admins', [])
        if isinstance(raw_admins, str):
            raw_admins = [x.strip() for x in raw_admins.split(',')]
        self.admins = [a.lower() for a in raw_admins]
        self.pending_encounters = {} 

    async def send(self, message: str):
        await self.irc.send(message)

    async def connect(self):
        await self.irc.connect()
        asyncio.create_task(loops.hype_loop(self))
        asyncio.create_task(loops.ambient_event_loop(self))
        asyncio.create_task(loops.arena_call_loop(self))
        asyncio.create_task(loops.idle_payout_loop(self))
        asyncio.create_task(loops.power_tick_loop(self))
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
                    await self.send(f"PONG :{msg if msg else target}")
                elif command == "PONG":
                    ts_str = msg.strip() if msg else target.strip()
                    if ts_str in self.pending_pings:
                        import time
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
                    await self.send(f"JOIN {self.config['channel']}")
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
                    is_channel_msg = target.startswith(('#', '&', '+', '!'))
                    reply_target = target if is_channel_msg else source_nick
                    if is_channel_msg:
                        import time
                        nick_lower = source_nick.lower()
                        if nick_lower not in self.channel_users:
                            self.channel_users[nick_lower] = {'join_time': time.time(), 'chat_lines': 1}
                            security.start_registration_timer(self, nick_lower)
                        else:
                            self.channel_users[nick_lower]['chat_lines'] += 1
                    
                    is_admin = source_nick.lower() in self.admins
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
        self.llm = ArenaLLM(CONFIG); self.db = ArenaDB(); self.nodes = {}
    async def start(self):
        for net_name, net_config in CONFIG['networks'].items():
            if net_config.get('enabled', True):
                node = GridNode(net_name, net_config, self.llm, self.db, self)
                self.nodes[net_name] = node
                asyncio.create_task(node.connect())
        logger.info(f"Hub initialized. Bridging {len(self.nodes)} networks...")
        while True: await asyncio.sleep(3600)
    def shutdown(self):
        logger.warning("Shutting down...")
        asyncio.create_task(self.db.close())
        for node in self.nodes.values():
            if node.irc.writer: node.irc.writer.write(b"QUIT :Mainframe shutdown.\r\n")

if __name__ == "__main__":
    hub = MasterHub()
    try: asyncio.run(hub.start())
    except KeyboardInterrupt: hub.shutdown()
