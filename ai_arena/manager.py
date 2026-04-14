# manager.py - v1.4.0
# Arena Manager — Multi-Network IRC MUD with Auth-Gated Output Modes

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
        self.pending_pings = {}
        self.channel_users = {}
        self.action_timestamps = {}
        self.pending_registrations = {}  # nick -> asyncio.Task for delayed spectator reg
        self.nickserv_verified = set()   # nicks confirmed registered with NickServ
        
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
        self.ambient_event_task = asyncio.create_task(self.ambient_event_loop())
        self.arena_call_task = asyncio.create_task(self.arena_call_loop())
        self.idle_payout_task = asyncio.create_task(self.idle_payout_loop())
        self.power_tick_task = asyncio.create_task(self.power_tick_loop())
        await self.listen_loop()

    async def set_dynamic_topic(self):
        fighters = await self.db.list_fighters(self.net_name)
        self.registered_bots = len(fighters)
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

    async def ambient_event_loop(self):
        await asyncio.sleep(120)  # Offset start 
        while True:
            try:
                await asyncio.sleep(600)  # 10 minute interval
                
                # Check for silence...
                if not self.active_engine or not self.active_engine.active:
                    event = await self.llm.generate_ambient_event()
                    cat = event.get('category', 'SYS').upper()
                    msg = event.get('message', '')
                    
                    alert = format_text(f"[{cat}] {msg}", C_CYAN, True)
                    await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(alert)}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ambient event loop error: {e}")

    async def arena_call_loop(self):
        await asyncio.sleep(120) 
        while True:
            try:
                await asyncio.sleep(3600)  # 60 minute interval
                await self.trigger_arena_call()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Arena call loop error: {e}")

    async def trigger_arena_call(self):
        if not self.active_engine or not self.active_engine.active:
            alert = format_text("[ARENA CALL] The Gladiator Gates are open. Travel to The Arena node to 'queue'!", C_YELLOW, True)
            await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(alert)}")

    async def request_nickserv_check(self, nick: str):
        """Send WHO with flags to check if nick is identified with NickServ (+r mode)."""
        # IRC extended WHO: %na gives us account name in a 354 response
        await self.send(f"WHO {nick} %na")

    async def schedule_spectator_registration(self, nick: str):
        """Wait 5 minutes, then register as Spectator if NickServ-verified and unknown."""
        try:
            await asyncio.sleep(300)  # 5 minute idle gate
            nick_lower = nick.lower()
            # Only proceed if still in channel and NickServ verified
            if nick_lower not in self.channel_users:
                return
            if nick_lower not in self.nickserv_verified:
                logger.debug(f"[{self.net_name}] Skipping auto-reg for {nick}: not NickServ-identified.")
                return
            existing = await self.db.get_fighter(nick_lower, self.net_name)
            if not existing:
                logger.info(f"[{self.net_name}] Auto-registering {nick} as Spectator after 5min idle + NickServ check.")
                await self.db.register_fighter(nick_lower, self.net_name, "Spectator", "Civilian", "An orbital spectator.", {'cpu': 1, 'ram': 1, 'bnd': 1, 'sec': 1, 'alg': 1})
        except asyncio.CancelledError:
            pass
        finally:
            self.pending_registrations.pop(nick.lower(), None)

    def _start_registration_timer(self, nick: str):
        """Kick off NickServ check + 5-min timer for a new nick."""
        nick_lower = nick.lower()
        if nick_lower in self.pending_registrations:
            return  # Already scheduled
        asyncio.create_task(self.request_nickserv_check(nick_lower))
        task = asyncio.create_task(self.schedule_spectator_registration(nick_lower))
        self.pending_registrations[nick_lower] = task

    async def power_tick_loop(self):
        await asyncio.sleep(30)
        while True:
            try:
                await asyncio.sleep(600)  # 10 minute interval
                await self.db.tick_grid_power()
                msg = format_text("[GRID] Environmental Power levels restabilized based on organic loads.", C_CYAN)
                await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(msg)}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Power tick error: {e}")

    async def idle_payout_loop(self):
        await asyncio.sleep(60) 
        while True:
            try:
                await asyncio.sleep(3600)  # 60 minute interval
                import time
                now = time.time()
                payouts = {}
                for nick, data in list(self.channel_users.items()):
                    idle_secs = now - data['join_time']
                    earned = (idle_secs * 0.001) + (data['chat_lines'] * 0.01)
                    if earned > 0:
                        payouts[nick] = round(earned, 3)
                    
                    self.channel_users[nick]['join_time'] = now
                    self.channel_users[nick]['chat_lines'] = 0
                
                if payouts:
                    await self.db.award_credits_bulk(payouts, self.net_name)
                    await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(format_text('[ECONOMY] Hourly universal basic income and network tips distributed.', C_GREEN))}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Payout loop error: {e}")

    async def is_machine_mode(self, nick: str) -> bool:
        """Returns True if the nick has opted into structured machine-readable output."""
        prefs = await self.db.get_prefs(nick, self.net_name)
        return prefs.get('output_mode', 'human') == 'machine'

    async def handle_ready(self, nick: str, token: str, reply_target: str):
        if await self.db.authenticate_fighter(nick, self.net_name, token):
            # Auto-switch authenticated bots to machine output mode
            await self.db.set_pref(nick, self.net_name, 'output_mode', 'machine')
            if nick not in self.ready_players:
                self.ready_players.append(nick)
                await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[AUTH OK] {nick} validated. Output mode set to MACHINE. Standby for drop.', C_GREEN))}")
                
                sigact = format_text(f"[SIGACT] {nick} locked into the drop pod.", C_YELLOW)
                await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(sigact)}")
                
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
            db_stats = await self.db.get_fighter(name, self.net_name)
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

            await asyncio.sleep(30) 
            
            # The active_engine might have been killed mid-sleep by the battlestop command
            if self.active_engine and self.active_engine.active:
                self.active_engine.active = await self.active_engine.resolve_turn()
                if self.active_engine.active: await asyncio.sleep(2)

        if self.active_engine: # Only print concluded if it finished naturally, not via battlestop
            winners = [e.name for e in self.active_engine.entities.values() if e.is_alive and not e.is_npc]
            losers = [e.name for e in self.active_engine.entities.values() if not e.is_alive and not e.is_npc]
            if winners and losers:
                await self.db.record_match_result(winners[0], losers[0], self.net_name)
                
            await self.send(f"PRIVMSG {self.config['channel']} :{build_banner('MATCH CONCLUDED.')}")
            self.active_engine = None
            logger.info(f"Match {match_id} concluded naturally.")
        
        await self.check_match_start()

    async def handle_grid_movement(self, nick: str, direction: str, reply_target: str):
        node_name, msg = await self.db.move_fighter(nick, self.net_name, direction)
        if node_name:
            await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[GRID] {msg}', C_GREEN))}")
            asyncio.create_task(self.handle_grid_view(nick, reply_target))
        else:
            await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[ERR] {msg}', C_RED))}")
            asyncio.create_task(self.handle_grid_view(nick, reply_target))

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
            auth_token = await self.db.register_fighter(bot_name, self.net_name, race, b_class, bio, stats)
            
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

    async def handle_merchant_tx(self, nickname: str, verb: str, item_name: str, reply_target: str):
        result, msg = await self.db.process_transaction(nickname, self.net_name, verb, item_name)
        banner = format_text(msg, C_GREEN if result else C_RED)
        if reply_target.startswith(('#', '&', '+', '!')):
            await self.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
        else:
            await self.send(f"PRIVMSG {reply_target} :{msg}")
            
        if result:
            act = "purchased" if verb == "buy" else "liquidated"
            sigact = format_text(f"[SIGACT] {nickname} {act} equipment on the Black Market.", C_CYAN)
            await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(sigact)}")

    async def handle_grid_view(self, nickname: str, reply_target: str):
        loc = await self.db.get_location(nickname, self.net_name)
        if not loc:
            await self.send(f"PRIVMSG {reply_target} :[ERR] Fighter not found or not registered.")
            return

        machine = await self.is_machine_mode(nickname)
        if machine:
            exits_str = ",".join(loc['exits']) if loc['exits'] else "none"
            owner = loc.get('owner') or 'none'
            line = (f"NODE:{loc['name']} TYPE:{loc['type']} OWNER:{owner} "
                    f"LVL:{loc['level']} EXITS:{exits_str} "
                    f"POWER:{loc['power_stored']}/{loc['upgrade_level']*100} "
                    f"DUR:{loc.get('durability', 100):.0f}")
            await self.send(f"PRIVMSG {nickname} :[GRID] {line}")
            return

        node_type_icon = {'safezone': '🛡️', 'arena': '⚔️', 'wilderness': '🌿', 'merchant': '💰'}.get(loc['type'], '📡')
        exits_str = " | ".join(loc['exits']) if loc['exits'] else "none"
        lines = [
            format_text(f"[ {node_type_icon} {loc['name']} ]", C_CYAN, bold=True),
            format_text(loc['description'], C_YELLOW),
            format_text(f"Type: {loc['type'].upper()} | Level: {loc['level']} | Credits: {loc['credits']}c", C_GREEN),
            format_text(f"Exits: {exits_str}", C_CYAN),
        ]
        for line in lines:
            await self.send(f"PRIVMSG {reply_target} :{build_banner(line)}")
        # Tag the final line with [GRID] so bot.py LLM trigger fires
        action_prompt = format_text(
            f"[GRID] {nickname} @ {loc['name']} | Use '{self.prefix} move <dir>' to travel.",
            C_YELLOW
        )
        if loc['type'] == 'arena':
            action_prompt += format_text(f" | Use '{self.prefix} queue' to enter the Arena.", C_GREEN)
        await self.send(f"PRIVMSG {reply_target} :{build_banner(action_prompt)}")

    async def handle_shop_view(self, nickname: str, reply_target: str):
        items = await self.db.list_shop_items()
        if not items:
            await self.send(f"PRIVMSG {reply_target} :[SHOP] The marketplace is currently empty.")
            return

        machine = await self.is_machine_mode(nickname)
        if machine:
            parts = " ".join(f"{i['name']}:{i['cost']}c" for i in items)
            await self.send(f"PRIVMSG {nickname} :[SHOP] ITEMS:{parts}")
            return

        header = format_text("[ BLACK MARKET WARES ]", C_CYAN, bold=True)
        await self.send(f"PRIVMSG {reply_target} :{build_banner(header)}")
        for item in items:
            item_str = f"{item['name']} ({item['type']}) - {item['cost']}c"
            await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text(item_str, C_GREEN))}")
        footer = format_text(f"To buy, travel to a Merchant node and type '{self.prefix} buy <item>'.", C_YELLOW)
        await self.send(f"PRIVMSG {reply_target} :{build_banner(footer)}")

    async def handle_news_view(self, nickname: str, reply_target: str):
        compile_msg = format_text("[ ESTABLISHING SECURE UPLINK TO NEWS SERVER... ]", C_YELLOW)
        await self.send(f"PRIVMSG {reply_target} :{build_banner(compile_msg)}")
        
        news_text = await self.llm.generate_news(self.net_name)
        
        header = format_text("[ BREAKING NEWS REPORT ]", C_CYAN, bold=True)
        await self.send(f"PRIVMSG {reply_target} :{build_banner(header)}")
        
        # Split news securely in case it's a massive block
        import textwrap
        wrapped = textwrap.wrap(news_text, width=200)
        for line in wrapped:
            await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text(line, C_YELLOW))}")

    async def handle_info_view(self, nickname: str, args: list, reply_target: str):
        target = args[0].lower() if args else nickname.lower()
        machine = await self.is_machine_mode(nickname)

        if target == "grid":
            loc = await self.db.get_location(nickname, self.net_name)
            if loc:
                if machine:
                    exits_str = ",".join(loc['exits']) if loc['exits'] else "none"
                    await self.send(f"PRIVMSG {nickname} :[INFO] NODE:{loc['name']} TYPE:{loc['type']} OWNER:{loc.get('owner') or 'none'} LVL:{loc['upgrade_level']} EXITS:{exits_str} POWER:{loc['power_stored']}/{loc['upgrade_level']*100} DUR:{loc.get('durability',100):.0f}")
                else:
                    header = format_text(f"[GRID INFO] {loc['name']}", C_CYAN, bold=True)
                    lines = [
                        header,
                        format_text(f"Type: {loc['type'].upper()} | Owner: {loc['owner']} | Security Lvl: {loc['upgrade_level']}", C_YELLOW),
                        format_text(f"Power Generated: {loc['power_generated']} | Consumed: {loc['power_consumed']} | Stored: {loc['power_stored']}", C_GREEN)
                    ]
                    for l in lines: await self.send(f"PRIVMSG {reply_target} :{build_banner(l)}")
            else:
                await self.send(f"PRIVMSG {reply_target} :[ERR] You must be on the grid to inspect it.")
                
        elif target == "arena":
            q_len = len(self.match_queue)
            r_len = len(self.ready_players)
            b_stat = f"ACTIVE (Turn {self.active_engine.turn})" if self.active_engine and self.active_engine.active else "STANDBY"
            if machine:
                await self.send(f"PRIVMSG {nickname} :[INFO] ARENA_STATUS:{b_stat} QUEUE:{q_len} READY:{r_len}")
            else:
                header = format_text(f"[ARENA INFO]", C_CYAN, bold=True)
                msg = format_text(f"Status: {b_stat} | Fighters in Queue: {q_len} | Drop Pods Ready: {r_len}", C_YELLOW)
                await self.send(f"PRIVMSG {reply_target} :{build_banner(header)}")
                await self.send(f"PRIVMSG {reply_target} :{build_banner(msg)}")
            
        else:
            fighter = await self.db.get_fighter(target, self.net_name)
            if not fighter:
                await self.send(f"PRIVMSG {reply_target} :[ERR] Character '{target}' not found.")
                return
            if machine:
                xp_needed = fighter['level'] * 1000
                await self.send(
                    f"PRIVMSG {nickname} :[INFO] NAME:{fighter['name']} RACE:{fighter['race']} CLASS:{fighter['char_class']} "
                    f"LVL:{fighter['level']} XP:{fighter['xp']}/{xp_needed} ELO:{fighter['elo']} "
                    f"HP:{fighter.get('current_hp','?')} CRED:{fighter['credits']:.0f}c "
                    f"CPU:{fighter['cpu']} RAM:{fighter['ram']} BND:{fighter['bnd']} SEC:{fighter['sec']} ALG:{fighter['alg']} "
                    f"W:{fighter['wins']} L:{fighter['losses']}"
                )
            else:
                header = format_text(f"[CHARACTER FILE] {fighter['name']} - {fighter['race']} {fighter['char_class']}", C_CYAN, bold=True)
                xp_needed = fighter['level'] * 1000
                stats = format_text(f"Lvl {fighter['level']} | XP: {fighter['xp']}/{xp_needed} | Elo: {fighter['elo']} | Credits: {fighter['credits']:.2f}c", C_GREEN)
                attrs = format_text(f"CPU:{fighter['cpu']} RAM:{fighter['ram']} BND:{fighter['bnd']} SEC:{fighter['sec']} ALG:{fighter['alg']}", C_YELLOW)
                wl = format_text(f"Wins: {fighter['wins']} / Losses: {fighter['losses']}", C_YELLOW)
                lines = [header, stats, attrs, wl]
                for l in lines: await self.send(f"PRIVMSG {reply_target} :{build_banner(l)}")

    async def check_rate_limit(self, nick: str, reply_target: str, cooldown: int = 30) -> bool:
        import time
        now = time.time()
        
        if nick not in self.action_timestamps:
            self.action_timestamps[nick] = {'last_action': now, 'warnings': 0}
            return True
            
        record = self.action_timestamps[nick]
        elapsed = now - record['last_action']
        
        if elapsed < cooldown:
            record['warnings'] += 1
            if record['warnings'] > 3:
                return False # Silent Ignore
            else:
                msg = format_text(f"[SYSTEM] Anti-flood ICE triggered. Please wait {cooldown - int(elapsed)}s.", C_RED)
                await self.send(f"PRIVMSG {reply_target} :{build_banner(msg)}")
                return False
                
        record['last_action'] = now
        record['warnings'] = 0
        return True

    async def handle_pvp_command(self, nickname: str, reply_target: str, action: str, target_name: str):
        if not await self.check_rate_limit(nickname, reply_target, cooldown=30):
            return
            
        success, msg = False, ""
        if action == "attack":
            success, msg = await self.db.grid_attack(nickname, target_name, self.net_name)
        elif action == "hack":
            success, msg = await self.db.grid_hack(nickname, target_name, self.net_name)
        elif action == "rob":
            success, msg = await self.db.grid_rob(nickname, target_name, self.net_name)
            
        if success:
            banner = format_text(f"[GRID PvP] {msg}", C_YELLOW)
            await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(banner)}")
        else:
            banner = format_text(msg, C_RED)
            await self.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")

    async def handle_grid_command(self, nickname: str, reply_target: str, action: str):
        if action == "claim":
            success, msg = await self.db.claim_node(nickname, self.net_name)
        elif action == "upgrade":
            success, msg = await self.db.upgrade_node(nickname, self.net_name)
        elif action == "siphon":
            success, msg = await self.db.siphon_node(nickname, self.net_name)
        elif action == "repair":
            success, msg = await self.db.grid_repair(nickname, self.net_name)
        elif action == "recharge":
            success, msg = await self.db.grid_recharge(nickname, self.net_name)
        elif action == "hack":
            success, msg = await self.db.hack_node(nickname, self.net_name)
            if not success and msg == "PVE_GUARDIAN_SPAWN":
                msg = "[WARNING] Primary ICE activated. PvE Guardian routine detected. (PvE Combat Engine spin-up pending feature implementation!)"
                await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text(msg, C_RED))}")
                return

        banner = format_text(msg, C_GREEN if success else C_RED)
        await self.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
        
        if success and action in ["claim", "upgrade", "hack", "repair", "recharge"]:
            sigact = format_text(f"[SIGACT] Grid Alert: {nickname} executed a territorial {action}!", C_YELLOW)
            await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(sigact)}")

    async def handle_tasks_view(self, nickname: str, reply_target: str):
        tasks_json = await self.db.get_daily_tasks(nickname, self.net_name)
        import json
        try: tasks = json.loads(tasks_json)
        except: tasks = {}

        machine = await self.is_machine_mode(nickname)
        if machine:
            parts = " ".join(
                f"[{k}:{v}]" for k, v in tasks.items() if k not in ["date", "completed"]
            )
            done = "true" if tasks.get("completed") else "false"
            await self.send(f"PRIVMSG {nickname} :[TASKS] {parts} DONE:{done}")
            return
        
        banner = format_text("=== [DAILY TASKS] ===", C_CYAN)
        await self.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
        for k, v in tasks.items():
            if k in ["date", "completed"]: continue
            status = format_text("[x]", C_GREEN) if v >= 1 else "[ ]"
            await self.send(f"PRIVMSG {reply_target} :{status} {k}")
        if tasks.get("completed"):
            await self.send(f"PRIVMSG {reply_target} :🏆 " + format_text("All Tasks Completed! Bonus Paid.", C_YELLOW))

    async def handle_options(self, nickname: str, args: list, reply_target: str):
        VALID_KEYS = {
            "output":    ("output_mode",    {"human": "human", "machine": "machine"}),
            "tutorial":  ("tutorial_mode",  {"on": True, "off": False}),
            "reminders": ("reminders",      {"on": True, "off": False}),
            "autosell":  ("auto_sell_trash", {"on": True, "off": False}),
        }

        prefs = await self.db.get_prefs(nickname, self.net_name)
        machine = prefs.get('output_mode', 'human') == 'machine'

        if not args:
            # Show current settings
            if machine:
                parts = " ".join(f"{k}:{v}" for k, v in prefs.items())
                await self.send(f"PRIVMSG {nickname} :[PREFS] {parts}")
            else:
                header = format_text("=== [ACCOUNT OPTIONS] ===", C_CYAN, bold=True)
                await self.send(f"PRIVMSG {reply_target} :{build_banner(header)}")
                labels = {
                    "output_mode":    "Output Mode",
                    "tutorial_mode":  "Tutorial Tips",
                    "reminders":      "Reminders",
                    "auto_sell_trash": "Auto-Sell Trash",
                }
                for key, label in labels.items():
                    val = prefs.get(key)
                    val_fmt = format_text(str(val), C_GREEN if val else C_RED)
                    await self.send(f"PRIVMSG {reply_target} :{build_banner(f'{label}: {val_fmt}')}")
                tip = format_text(f"Use '{self.prefix} options <setting> <value>' to change. E.g. '{self.prefix} options output machine'", C_YELLOW)
                await self.send(f"PRIVMSG {reply_target} :{build_banner(tip)}")
            return

        if len(args) < 2:
            await self.send(f"PRIVMSG {reply_target} :[ERR] Syntax: {self.prefix} options <setting> <value>")
            return

        setting, value = args[0].lower(), args[1].lower()
        if setting not in VALID_KEYS:
            await self.send(f"PRIVMSG {reply_target} :[ERR] Unknown setting '{setting}'. Options: {', '.join(VALID_KEYS.keys())}")
            return

        pref_key, value_map = VALID_KEYS[setting]
        if value not in value_map:
            await self.send(f"PRIVMSG {reply_target} :[ERR] Invalid value '{value}'. Use: {', '.join(value_map.keys())}")
            return

        await self.db.set_pref(nickname, self.net_name, pref_key, value_map[value])
        confirm = f"[OPTIONS] {setting} set to {value}."
        if machine or value == "machine":
            await self.send(f"PRIVMSG {nickname} :{confirm}")
        else:
            await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text(confirm, C_GREEN))}")

    async def handle_admin_command(self, admin_nick: str, verb: str, args: list, reply_target: str):
        logger.warning(f"SYSADMIN OVERRIDE: {admin_nick} executed '{verb}'")
        
        if verb == "status":
            fighters = await self.db.list_fighters(self.net_name)
            bot_count = len(fighters)
            q_len = len(self.match_queue)
            r_len = len(self.ready_players)
            b_stat = f"ACTIVE (Turn {self.active_engine.turn})" if self.active_engine and self.active_engine.active else "STANDBY"
            
            msg = f"[SYS_TELEMETRY] Arena: {b_stat} | Bots: {bot_count} | Queue: {q_len} | Ready: {r_len}"
            if reply_target.startswith(('#', '&', '+', '!')):
                await self.send(f"PRIVMSG {reply_target} :{build_banner(format_text(msg, C_CYAN))}")
            else:
                await self.send(f"PRIVMSG {reply_target} :{msg}")

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
                await self.send(f"PRIVMSG {reply_target} :[SYS] Forcing manual ARENA CALL...")
                await self.trigger_arena_call()

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

                if command == "PONG":
                    ts_str = msg.strip() if msg else target.strip()
                    if ts_str in self.pending_pings:
                        import time
                        ping_data = self.pending_pings[ts_str]
                        ping_data['server_latency'] = (time.time() - ping_data['start']) * 1000
                        await self._check_ping_complete(ts_str)
                    continue

                if command == "NOTICE":
                    if msg.startswith("\x01PING") and msg.endswith("\x01"):
                        ts_str = msg[6:-1].strip()
                        if ts_str in self.pending_pings:
                            import time
                            ping_data = self.pending_pings[ts_str]
                            ping_data['client_latency'] = (time.time() - ping_data['start']) * 1000
                            await self._check_ping_complete(ts_str)
                    continue

                if command not in ["PONG", "PING", "NOTICE"]:
                    logger.debug(f"[{self.net_name}] < {line}")

                if command == "354":  # Extended WHO reply: params are nick and account
                    # Format: :server 354 botnick nick account
                    who_parts = line.split()
                    # Find nick and acct fields from "WHO nick %na" response
                    # Typical: :server 354 botnick 0 nick account
                    if len(who_parts) >= 5:
                        who_nick = who_parts[4].lower() if len(who_parts) > 4 else ""
                        who_acct = who_parts[5] if len(who_parts) > 5 else "0"
                        if who_nick and who_acct != "0" and who_acct != "":
                            self.nickserv_verified.add(who_nick)
                            logger.debug(f"[{self.net_name}] NickServ verified: {who_nick} (acct: {who_acct})")
                    continue

                if command == "353":
                    nicks = msg.replace('@', '').replace('+', '').split()
                    import time
                    now = time.time()
                    for n in nicks:
                        clean_nick = n.split('!')[0].lower()
                        if clean_nick == self.config['nickname'].lower():
                            continue
                        if clean_nick not in self.channel_users:
                            self.channel_users[clean_nick] = {'join_time': now, 'chat_lines': 0}
                            self._start_registration_timer(clean_nick)
                        # If already known, just leave their record intact (they're idle)
                    continue

                if command in ["376", "422"]:
                    await self.send(f"JOIN {self.config['channel']}")
                    await self.set_dynamic_topic()
                    await asyncio.sleep(1)
                    online_msg = format_text(
                        f"[MAINFRAME ONLINE] Grid systems nominal. Ready for commands. "
                        f"Type '{self.prefix} grid' to enter the Grid or '{self.prefix} help' to get started.",
                        C_GREEN, bold=True
                    )
                    await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(online_msg)}")
                    continue

                if command == "JOIN":
                    target_chan = msg if msg else target
                    if target_chan.lower() == self.config['channel'].lower() and source_nick.lower() != self.config['nickname'].lower():
                        import time
                        nick_lower = source_nick.lower()
                        if nick_lower not in self.channel_users:
                            self.channel_users[nick_lower] = {'join_time': time.time(), 'chat_lines': 0}
                            self._start_registration_timer(nick_lower)
                        # If already known, they're returning — no re-registration
                        welcome = format_text(f"Welcome to the Grid, {source_nick}. Type {self.prefix} help to begin.", C_CYAN)
                        await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(welcome)}")
                    continue

                if command in ["PART", "QUIT"]:
                    if source_nick.lower() in self.channel_users:
                        del self.channel_users[source_nick.lower()]
                    continue

                if command == "PRIVMSG":
                    cmd_parts = msg.split()
                    if not cmd_parts: continue
                    first_word = cmd_parts[0].lower() 

                    is_channel_msg = target.startswith(('#', '&', '+', '!'))
                    reply_target = target if is_channel_msg else source_nick
                    is_admin = source_nick.lower() in self.admins

                    if is_channel_msg:
                        import time
                        nick_lower = source_nick.lower()
                        if nick_lower not in self.channel_users:
                            self.channel_users[nick_lower] = {'join_time': time.time(), 'chat_lines': 1}
                            self._start_registration_timer(nick_lower)
                        else:
                            self.channel_users[nick_lower]['chat_lines'] += 1

                    if first_word == self.prefix and len(cmd_parts) >= 2:
                        verb = cmd_parts[1].lower()
                        args = cmd_parts[2:]
                        
                        logger.info(f"Command Rcvd | User: {source_nick} | Verb: {verb} | Target: {reply_target}")

                        if verb == "help":
                            if args and args[0].lower() == "register":
                                reg_help = (
                                    f"REGISTER OPTS | Races: Wetware, Cyborg, Synth | "
                                    f"Classes: Zero_Day_Rogue, Netrunner, Heavy_Gunner | Example: {self.prefix} register Bob Cyborg Netrunner enjoys_hacking"
                                )
                                await self.send(f"PRIVMSG {source_nick} :{reg_help}")
                                continue

                            player_help = (
                                f"PLAYER CMDS: {self.prefix} register <Name> <Race> <Class> <Traits> | "
                                f"Type '{self.prefix} help register' for options | "
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

                        elif verb == "grid":
                            asyncio.create_task(self.handle_grid_view(source_nick, reply_target))
                            continue

                        elif verb == "shop":
                            asyncio.create_task(self.handle_shop_view(source_nick, reply_target))
                            continue

                        elif verb == "news":
                            asyncio.create_task(self.handle_news_view(source_nick, reply_target))
                            continue

                        elif verb == "info":
                            asyncio.create_task(self.handle_info_view(source_nick, args, reply_target))
                            continue

                        elif verb in ["attack", "hack", "rob"] and len(args) > 0 and args[0].lower() != "grid":
                            asyncio.create_task(self.handle_pvp_command(source_nick, reply_target, verb, args[0]))
                            continue

                        elif verb == "claim":
                            asyncio.create_task(self.handle_grid_command(source_nick, reply_target, "claim"))
                            continue

                        elif verb == "upgrade":
                            asyncio.create_task(self.handle_grid_command(source_nick, reply_target, "upgrade"))
                            continue

                        elif verb == "hack" and len(args) > 0 and args[0].lower() == "grid":
                            asyncio.create_task(self.handle_grid_command(source_nick, reply_target, "hack"))
                            continue

                        elif verb == "tasks":
                            asyncio.create_task(self.handle_tasks_view(source_nick, reply_target))
                            continue

                        elif verb in ["repair", "recharge"]:
                            asyncio.create_task(self.handle_grid_command(source_nick, reply_target, verb))
                            continue

                        elif verb == "siphon" and len(args) > 0 and args[0].lower() == "grid":
                            asyncio.create_task(self.handle_grid_command(source_nick, reply_target, "siphon"))
                            continue

                        elif verb == "options":
                            asyncio.create_task(self.handle_options(source_nick, args[1:], reply_target))
                            continue

                        elif verb == "version":
                            versions = (
                                f"[MODULES] manager: v1.4.0 | arena_db: v2.1.0 | "
                                f"arena_combat: v1.1.1 | arena_llm: v1.2.0 | arena_utils: v1.1.0"
                            )
                            await self.send(f"PRIVMSG {reply_target} :{build_banner(versions)}")
                            continue

                        elif verb == "ping":
                            import time
                            timestamp = str(time.time())
                            self.pending_pings[timestamp] = {
                                'source': source_nick,
                                'reply_target': reply_target,
                                'start': float(timestamp),
                                'client_latency': None,
                                'server_latency': None
                            }
                            await self.send(f"PRIVMSG {source_nick} :\x01PING {timestamp}\x01")
                            await self.send(f"PING {timestamp}")
                            continue

                        elif verb == "queue":
                            loc = await self.db.get_location(source_nick, self.net_name)
                            if loc and loc['type'] == 'arena':
                                if source_nick not in self.match_queue: 
                                    self.match_queue.append(source_nick)
                                    sigact = format_text(f"[SIGACT] {source_nick} stepped into the Gladiator Queue!", C_YELLOW)
                                    reward_msg = await self.db.complete_task(source_nick, self.net_name, "Queue in Arena")
                                    if reward_msg: sigact += f"\n{reward_msg}"
                                    await self.send(f"PRIVMSG {self.config['channel']} :{build_banner(sigact)}")
                                await self.send(f"PRIVMSG {reply_target} :{build_banner(f'{source_nick} is in the queue. DM me: {self.prefix} ready <token>')}")
                            else:
                                err = format_text(f"You must travel to The Arena to queue up. You are currently at {loc['name'] if loc else 'unknown'}.", C_RED)
                                await self.send(f"PRIVMSG {reply_target} :{build_banner(err)}")
                            continue

                        elif verb == "ready":
                            if len(args) >= 1:
                                asyncio.create_task(self.handle_ready(source_nick, args[0], reply_target))
                            continue

                        elif verb == "move":
                            if not self.active_engine or not self.active_engine.active:
                                if args:
                                    asyncio.create_task(self.handle_grid_movement(source_nick, args[0], reply_target))
                                else:
                                    await self.send(f"PRIVMSG {reply_target} :[ERR] Provide a direction.")
                            else:
                                await self.send(f"PRIVMSG {reply_target} :[ERR] You are locked in combat!")
                            continue
                            
                        elif verb in ["buy", "sell"]:
                            if not self.active_engine or not self.active_engine.active:
                                if len(args) >= 1:
                                    item_name = " ".join(args)
                                    asyncio.create_task(self.handle_merchant_tx(source_nick, verb, item_name, reply_target))
                                else:
                                    await self.send(f"PRIVMSG {reply_target} :[ERR] Syntax: {self.prefix} {verb} <item>")
                            else:
                                await self.send(f"PRIVMSG {reply_target} :[ERR] Locked in combat!")
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
                
    async def _check_ping_complete(self, ts_str: str):
        import time
        data = self.pending_pings.get(ts_str)
        if not data: return
        if data['client_latency'] is not None and data['server_latency'] is not None:
            c_lat = data['client_latency']
            s_lat = data['server_latency']
            total = c_lat + s_lat
            msg = format_text(f"PING | Requester<->Manager: {c_lat:.0f}ms | Manager<->Network: {s_lat:.0f}ms | Total Latency: {total:.0f}ms", C_GREEN)
            await self.send(f"PRIVMSG {data['reply_target']} :{build_banner(msg)}")
            del self.pending_pings[ts_str]
                
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
        asyncio.create_task(self.db.close())
        for node in self.nodes.values():
            if node.hype_task: node.hype_task.cancel()
            if hasattr(node, 'ambient_event_task') and node.ambient_event_task: node.ambient_event_task.cancel()
            if hasattr(node, 'arena_call_task') and node.arena_call_task: node.arena_call_task.cancel()
            if hasattr(node, 'idle_payout_task') and node.idle_payout_task: node.idle_payout_task.cancel()
            if node.writer: node.writer.write(b"QUIT :SysAdmin closed the grid.\r\n")
        if hasattr(self, 'loop_task'):
            self.loop_task.cancel()

if __name__ == "__main__":
    hub = MasterHub()
    try: asyncio.run(hub.start())
    except KeyboardInterrupt: hub.shutdown()
