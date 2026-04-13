# manager.py - v1.2.0
# SysAdmin Toolkit: Status Telemetry and Manual Match Controls

import asyncio
import ssl
import json
import sys
import logging
from arena_utils import format_text, build_banner, ICONS, C_GREEN, C_CYAN, C_RED, C_YELLOW
from arena_llm import ArenaLLM
from arena_db import ArenaDB
from arena_combat import CombatEngine, Entity

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
        self.reader = None
        self.writer = None
        
        self.active_engine = None
        self.match_queue = [] 
        self.ready_players = [] 
        self.pve_task = None 
        self.hype_task = None
        self.registered_bots = 0
        
        raw_admins = CONFIG.get('admins', [])
        if isinstance(raw_admins, str):
            raw_admins = [x.strip() for x in raw_admins.split(',')]
        self.admins = [a.lower() for a in raw_admins]

    async def send(self, message: str):
        logger.debug(f"[{self.net_name}] > {message}")
        self.writer.write(f"{message}\r\n".encode('utf-8'))
        await self.writer.drain()
        await asyncio.sleep(0.3)

    async def connect(self):
        logger.info(f"Booting Node: {self.net_name} ({self.config['server']})...")
        ssl_ctx = ssl.create_default_context() if self.config['ssl'] else None
        self.reader, self.writer = await asyncio.open_connection(self.config['server'], self.config['port'], ssl=ssl_ctx)

        await self.send(f"NICK {self.config['nickname']}")
        await self.send(f"USER {self.config['nickname']} 0 * :AutomataArena Master Node")
        
        self.hype_task = asyncio.create_task(self.hype_loop())
        await self.listen_loop()

    async def set_dynamic_topic(self):
        self.registered_bots = len(self.db.list_fighters(self.net_name))
        raw_topic = await self.llm.generate_topic(self.registered_bots, self.net_name)
        fmt_topic = f"{ICONS['Arena']} {format_text('#AutomataArena', C_CYAN, bold=True)} | {raw_topic} | {ICONS['Cross-Grid']} Cross-Grid Active"
        await self.send(f"TOPIC {self.config['channel']} :{fmt_topic}")

    async def hype_loop(self):
        await asyncio.sleep(60) 
        while True:
            try:
                await asyncio.sleep(2700) 
                await self.set_dynamic_topic()
                if not self.active_engine:
                    hype_msg = await self.llm.generate_hype()
                    if not hype_msg.startswith("ERROR"):
                        alert = format_text(f"[ARENA BROADCAST] {hype_msg}", C_YELLOW, True)
                        await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(alert)}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Hype loop error: {e}")

    async def handle_ready(self, nick: str, token: str, reply_target: str):
        if self.db.authenticate_fighter(nick, self.net_name, token):
            if nick not in self.ready_players:
                self.ready_players.append(nick)
                await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[AUTH OK] {nick} validated. Standby for drop.', C_GREEN))}")
                await self.check_match_start()
        else:
            await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[AUTH FAIL] {nick} Cryptographic mismatch.', C_RED))}")

    async def check_match_start(self):
        if len(self.ready_players) >= 2:
            if self.pve_task: self.pve_task.cancel()
            participants = self.ready_players[:2]
            self.ready_players = self.ready_players[2:]
            logger.info(f"Starting PVP Match with: {participants}")
            asyncio.create_task(self.start_match("PVP_MATCH", participants, pve=False))
            
        elif len(self.ready_players) == 1 and not self.active_engine:
            await self.send(f"PRIVMSG {self.config['channel']} :{build_banner('Fighter queued. Waiting 20 seconds for a human challenger...')}")
            self.pve_task = asyncio.create_task(self.pve_countdown())

    async def pve_countdown(self):
        try:
            await asyncio.sleep(20)
            if len(self.ready_players) == 1 and not self.active_engine:
                player = self.ready_players.pop(0)
                await self.send(f"PRIVMSG {self.config['channel']} :{build_banner('No humans detected. Initiating PvE simulation...')}")
                logger.info(f"Starting PVE Match for: {player}")
                asyncio.create_task(self.start_match("PVE_MATCH", [player], pve=True))
        except asyncio.CancelledError:
            pass 

    async def generate_and_queue_npc(self, npc: Entity, state_msg: str):
        action = await self.llm.generate_npc_action(npc.name, npc.bio, state_msg, self.prefix)
        if self.active_engine and self.active_engine.active:
            self.active_engine.queue_command(npc.name, action)

    async def start_match(self, match_id: str, participants: list, pve=False):
        async def combat_channel_send(msg: str):
            await self.send(f"PRIVMSG {self.config['channel']} :{msg}")

        for p in participants:
            if p in self.match_queue:
                self.match_queue.remove(p)

        self.active_engine = CombatEngine(match_id, self.prefix, combat_channel_send)
        for name in participants:
            db_stats = self.db.get_fighter(name, self.net_name)
            self.active_engine.add_entity(Entity(name, db_stats))

        if pve:
            npc_db = {'cpu': 6, 'ram': 8, 'bnd': 4, 'sec': 6, 'alg': 2, 'inventory': '["Malware_Blade"]', 'alignment': -100, 'bio': 'A feral, rogue malware process.'}
            self.active_engine.add_entity(Entity("Trojan.Exe", npc_db, is_npc=True))

        self.active_engine.active = True
        await self.send(f"PRIVMSG {self.config['channel']} :{build_banner('THE ARENA IS LOCKED. COMBAT SEQUENCE INITIALIZED!')}")
        await asyncio.sleep(2)

        while self.active_engine and self.active_engine.active:
            raw_state = f"TURN {self.active_engine.turn} | LOC: {list(self.active_engine.entities.values())[0].zone} | "
            for e in self.active_engine.entities.values():
                if e.is_alive:
                    hp_color = C_GREEN if e.hp > (e.max_hp/2) else C_RED
                    hp_str = format_text(f"{e.hp}/{e.max_hp}", hp_color)
                    raw_state += f"{e.name} [HP:{hp_str}] "
            
            await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(raw_state + '| Awaiting public commands (60s)...')}")

            npc_tasks = [self.generate_and_queue_npc(ent, raw_state) for ent in self.active_engine.entities.values() if ent.is_npc and ent.is_alive]
            if npc_tasks: asyncio.gather(*npc_tasks) 

            await asyncio.sleep(60) 
            
            # The active_engine might have been killed mid-sleep by the battlestop command
            if self.active_engine and self.active_engine.active:
                self.active_engine.active = await self.active_engine.resolve_turn()
                if self.active_engine.active: await asyncio.sleep(2)

        if self.active_engine: # Only print concluded if it finished naturally, not via battlestop
            await self.send(f"PRIVMSG {self.config['channel']} :{build_banner('MATCH CONCLUDED.')}")
            self.active_engine = None
            logger.info(f"Match {match_id} concluded naturally.")
        
        await self.check_match_start()

    async def handle_registration(self, nick: str, args: list, reply_target: str):
        try:
            if len(args) < 4:
                await self.send(f"PRIVMSG {reply_target} :Syntax: {self.prefix} register <Name> <Race> <Class> <Traits>")
                return
                
            bot_name, race, b_class = args[0], args[1], args[2]
            traits = " ".join(args[3:])
            
            ack = format_text(f"Compiling architecture for {bot_name}...", C_GREEN)
            await self.send(f"PRIVMSG {reply_target} :{build_banner(ack)}")

            logger.info(f"Processing registration for {bot_name} ({race}/{b_class})")
            bio = await self.llm.generate_bio(bot_name, race, b_class, traits)
            if len(bio) > 200: bio = bio[:197] + "..."
                
            stats = {'cpu': 5, 'ram': 5, 'bnd': 5, 'sec': 5, 'alg': 5}
            auth_token = self.db.register_fighter(bot_name, self.net_name, race, b_class, bio, stats)
            
            if auth_token:
                payload = json.dumps({"token": auth_token, "bio": bio, "stats": stats, "inventory": ["Basic_Ration"]})
                await self.send(f"NOTICE {bot_name} :[SYS_PAYLOAD] {payload}")
                
                announcement = f"{ICONS.get(race, '⚙️')} {format_text(bot_name, C_CYAN, True)} the {ICONS.get(b_class, '⚔️')} {b_class} has entered the Grid!"
                await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(announcement)}")
                await self.set_dynamic_topic()
            else:
                err = format_text(f"Registration failed: Identity '{bot_name}' is already registered or corrupted.", C_RED)
                await self.send(f"PRIVMSG {reply_target} :{build_banner(err)}")

        except Exception as e:
            logger.exception("Critical Error in handle_registration")
            await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text('CRITICAL ERROR during registration sequence.', C_RED))}")

    # --- ADVANCED SYSADMIN CONTROLS ---
    async def handle_admin_command(self, admin_nick: str, verb: str, args: list, reply_target: str):
        logger.warning(f"SYSADMIN OVERRIDE: {admin_nick} executed '{verb}'")
        
        if verb == "status":
            bot_count = len(self.db.list_fighters(self.net_name))
            q_len = len(self.match_queue)
            r_len = len(self.ready_players)
            b_stat = f"ACTIVE (Turn {self.active_engine.turn})" if self.active_engine and self.active_engine.active else "STANDBY"
            
            msg = f"[SYS_TELEMETRY] Arena: {b_stat} | Bots: {bot_count} | Queue: {q_len} | Ready: {r_len}"
            await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text(msg, C_CYAN))}")

        elif verb == "battlestop":
            if self.active_engine and self.active_engine.active:
                self.active_engine.active = False
                self.active_engine = None
                alert = format_text("ADMIN OVERRIDE: ACTIVE COMBAT SEQUENCE HALTED.", C_RED, True)
                await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(alert)}")
                await self.send(f"PRIVMSG {reply_target} :[SYS] Match aborted successfully.")
            else:
                await self.send(f"PRIVMSG {reply_target} :[SYS] No active battle to stop.")

        elif verb == "battlestart":
            if self.active_engine and self.active_engine.active:
                await self.send(f"PRIVMSG {reply_target} :[SYS] Cannot start: Arena is currently locked in combat.")
            elif len(self.ready_players) > 0:
                await self.send(f"PRIVMSG {reply_target} :[SYS] Forcing match drop sequence...")
                await self.check_match_start()
            else:
                await self.send(f"PRIVMSG {reply_target} :[SYS] Cannot start: 0 players have authenticated their Ready tokens.")

        elif verb == "topic":
            await self.set_dynamic_topic()
            await self.send(f"PRIVMSG {reply_target} :[SYS] Topic regenerated.")

        elif verb == "broadcast":
            msg = " ".join(args)
            alert = format_text(f"[SYSADMIN OVERRIDE] {msg}", C_YELLOW, True)
            if reply_target != self.config['channel']:
                await self.send(f"PRIVMSG {reply_target} :[SYS] Broadcast deployed.")
            await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(alert)}")

        elif verb in ["shutdown", "stop"]:
            alert = format_text("MAINFRAME SHUTDOWN INITIATED BY ADMIN.", C_RED, True)
            await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(alert)}")
            if self.active_engine:
                self.active_engine.active = False
            await asyncio.sleep(1)
            self.hub.shutdown()

    async def listen_loop(self):
        while True:
            try:
                line = await self.reader.readline()
                if not line: break
                line = line.decode('utf-8', errors='ignore').strip()
                
                msg_idx = line.find(' :')
                if msg_idx != -1:
                    header = line[:msg_idx].split()
                    msg = line[msg_idx + 2:].strip()
                else:
                    header = line.split()
                    msg = ""

                if not header: continue

                if header[0].startswith(':'):
                    source_full = header[0][1:]
                    command = header[1] if len(header) > 1 else ""
                    target = header[2] if len(header) > 2 else ""
                else:
                    source_full = ""
                    command = header[0]
                    target = header[1] if len(header) > 1 else ""
                    
                source_nick = source_full.split('!')[0] if source_full else ""
                
                if command == "PING":
                    pong_target = msg if msg else target
                    await self.send(f"PONG :{pong_target}")
                    continue

                if command not in ["PONG", "PING"]:
                    logger.debug(f"[{self.net_name}] < {line}")

                if command in ["376", "422"]:
                    await self.send(f"JOIN {self.config['channel']}")
                    await self.set_dynamic_topic()
                    continue

                if command == "JOIN":
                    target_chan = msg if msg else target
                    if target_chan.lower() == self.config['channel'].lower() and source_nick != self.config['nickname']:
                        welcome = format_text(f"Welcome to the Grid, {source_nick}. Type {self.prefix} help to begin.", C_CYAN)
                        await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(welcome)}")
                    continue

                if command == "PRIVMSG":
                    cmd_parts = msg.split()
                    if not cmd_parts: continue
                    first_word = cmd_parts[0].lower() 

                    is_channel_msg = target.startswith(('#', '&', '+', '!'))
                    reply_target = target if is_channel_msg else source_nick
                    is_admin = source_nick.lower() in self.admins

                    if first_word == self.prefix and len(cmd_parts) >= 2:
                        verb = cmd_parts[1].lower()
                        args = cmd_parts[2:]
                        
                        logger.info(f"Command Rcvd | User: {source_nick} | Verb: {verb} | Target: {reply_target}")

                        if verb == "help":
                            player_help = (
                                f"PLAYER CMDS: {self.prefix} register <Name> <Race> <Class> <Traits> | "
                                f"{self.prefix} queue | "
                                f"DM: '{self.prefix} ready <token>' to auth. | "
                                f"COMBAT: {self.prefix} <attack/shoot/evade/heal/speak/use> <target>"
                            )
                            await self.send(f"PRIVMSG {source_nick} :{player_help}")
                            
                            if is_admin:
                                admin_help = (
                                    f"ADMIN CMDS: {self.prefix} status | {self.prefix} battlestart | {self.prefix} battlestop | "
                                    f"{self.prefix} topic | {self.prefix} broadcast <msg> | {self.prefix} stop\n"
                                    f"Use terminal 'python arena_db.py' for DB management."
                                )
                                await self.send(f"PRIVMSG {source_nick} :{admin_help}")
                            continue

                        elif verb == "register":
                            asyncio.create_task(self.handle_registration(source_nick, args, reply_target))
                            continue

                        elif verb == "queue":
                            if source_nick not in self.match_queue: 
                                self.match_queue.append(source_nick)
                            await self.send(f"PRIVMSG {reply_target} :{build_banner(f'{source_nick} is in the queue. DM me: {self.prefix} ready <token>')}")
                            continue

                        elif verb == "ready":
                            if len(args) >= 1:
                                asyncio.create_task(self.handle_ready(source_nick, args[0], reply_target))
                            continue

                        # --- NEW ADMIN COMMAND ROUTER ---
                        elif verb in ["topic", "broadcast", "shutdown", "stop", "status", "battlestop", "battlestart"]:
                            if is_admin:
                                asyncio.create_task(self.handle_admin_command(source_nick, verb, args, reply_target))
                            else:
                                await self.send(f"PRIVMSG {reply_target} :[ERR] Access Denied. Mainframe clearance required.")
                            continue

                        if self.active_engine and self.active_engine.active:
                            self.active_engine.queue_command(source_nick, msg)

            except Exception as e:
                logger.exception(f"Core Loop Exception caught: {e}. Recovering state...")
                
class MasterHub:
    def __init__(self):
        self.llm = ArenaLLM(CONFIG)
        self.db = ArenaDB()
        self.nodes = {}

    async def start(self):
        tasks = []
        for net_name, net_config in CONFIG['networks'].items():
            if net_config.get('enabled', True):
                node = GridNode(net_name, net_config, self.llm, self.db, self)
                self.nodes[net_name] = node
                tasks.append(node.connect())
        
        logger.info(f"Hub initialized. Bridging {len(tasks)} networks...")
        if not tasks: return

        self.loop_task = asyncio.gather(*tasks)
        try: await self.loop_task
        except asyncio.CancelledError: pass

    def shutdown(self):
        logger.warning("Initiating graceful shutdown...")
        self.db.close()
        for node in self.nodes.values():
            if node.hype_task: node.hype_task.cancel() 
            if node.writer: node.writer.write(b"QUIT :SysAdmin closed the grid.\r\n")
        if hasattr(self, 'loop_task'):
            self.loop_task.cancel()

if __name__ == "__main__":
    hub = MasterHub()
    try: asyncio.run(hub.start())
    except KeyboardInterrupt: hub.shutdown()
