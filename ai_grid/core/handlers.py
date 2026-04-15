# handlers.py - v1.5.0
import asyncio
import logging
import json
import random
import textwrap
import time
from grid_utils import format_text, build_banner, ICONS, C_GREEN, C_CYAN, C_RED, C_YELLOW

logger = logging.getLogger("manager")

# --- Utility Handlers ---

async def is_machine_mode(node, nick: str) -> bool:
    prefs = await node.db.get_prefs(nick, node.net_name)
    return prefs.get('output_mode', 'human') == 'machine'

async def check_rate_limit(node, nick: str, reply_target: str, cooldown: int = 30) -> bool:
    now = time.time()
    if nick not in node.action_timestamps:
        node.action_timestamps[nick] = {'last_action': now, 'warnings': 0}
        return True
        
    record = node.action_timestamps[nick]
    elapsed = now - record['last_action']
    if elapsed < cooldown:
        record['warnings'] += 1
        if record['warnings'] > 3:
            return False
        else:
            msg = format_text(f"[SYSTEM] Anti-flood ICE triggered. Please wait {cooldown - int(elapsed)}s.", C_RED)
            await node.send(f"PRIVMSG {reply_target} :{build_banner(msg)}")
            return False
    record['last_action'] = now
    record['warnings'] = 0
    return True

# --- Core Handlers ---

async def handle_registration(node, nick: str, args: list, reply_target: str):
    try:
        if len(args) < 4:
            await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} register <Name> <Race> <Class> <Traits>")
            return
        bot_name, race, b_class = args[0], args[1], args[2]
        traits = " ".join(args[3:])
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Compiling architecture for {bot_name}...', C_GREEN))}")
        bio = await node.llm.generate_bio(bot_name, race, b_class, traits)
        if len(bio) > 200: bio = bio[:197] + "..."
        stats = {'cpu': 5, 'ram': 5, 'bnd': 5, 'sec': 5, 'alg': 5}
        auth_token = await node.db.register_fighter(bot_name, node.net_name, race, b_class, bio, stats)
        if auth_token:
            payload = json.dumps({"token": auth_token, "bio": bio, "stats": stats, "inventory": ["Basic_Ration"]})
            await node.send(f"NOTICE {bot_name} :[SYS_PAYLOAD] {payload}")
            announcement = f"{ICONS.get(race, '⚙️')} {format_text(bot_name, C_CYAN, True)} the {ICONS.get(b_class, '⚔️')} {b_class} has entered the Grid!"
            await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(announcement)}")
            await node.set_dynamic_topic()
        else:
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Registration failed: Identity {bot_name!r} is already registered.', C_RED))}")
    except Exception as e:
        logger.exception("Error in handle_registration")
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('CRITICAL ERROR during registration sequence.', C_RED))}")

async def handle_grid_movement(node, nick: str, direction: str, reply_target: str):
    prev_node = None
    loc = await node.db.get_location(nick, node.net_name)
    if loc: prev_node = loc['name']
    node_name, msg = await node.db.move_fighter(nick, node.net_name, direction)
    if node_name:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[GRID] {msg}', C_GREEN))}")
        await handle_grid_view(node, nick, reply_target)
        new_loc = await node.db.get_location(nick, node.net_name)
        if new_loc and new_loc.get('node_type') == 'wilderness':
            threat = new_loc.get('threat_level', 0)
            if threat > 0:
                spawn_chance = 0.60 if threat >= 3 else 0.35
                if random.random() < spawn_chance:
                    await handle_mob_encounter(node, nick, node_name, threat, prev_node, reply_target)
    else:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[ERR] {msg}', C_RED))}")
        await handle_grid_view(node, nick, reply_target)

async def handle_mob_encounter(node, nick: str, node_name: str, threat: int, prev_node: str, reply_target: str):
    mob = node.db.combat.MOB_ROSTER.get(threat, node.db.combat.MOB_ROSTER[1])
    mob_name = mob['name']
    machine = await is_machine_mode(node, nick)
    if machine:
        warn = f"[MOB] THREAT:{threat} NAME:{mob_name} NODE:{node_name} ENGAGE:{node.prefix} engage FLEE:{node.prefix} flee TIMEOUT:15"
        await node.send(f"PRIVMSG {nick} :{warn}")
    else:
        warn = format_text(f"⚠️ [MOB DETECTED] {mob_name} (Threat {threat}) lurks in {node_name}! Type '{node.prefix} engage' to fight or '{node.prefix} flee' to retreat. (15s)", C_YELLOW, bold=True)
        await node.send(f"PRIVMSG {reply_target} :{build_banner(warn)}")
    await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] {mob_name} detected near {nick} at {node_name}.', C_RED))}")
    async def auto_engage():
        try:
            await asyncio.sleep(15)
            if nick in node.pending_encounters:
                asyncio.create_task(resolve_mob(node, nick, reply_target))
        except asyncio.CancelledError: pass
    timer = asyncio.create_task(auto_engage())
    node.pending_encounters[nick] = {'mob_name': mob_name, 'threat': threat, 'prev_node': prev_node, 'timer': timer, 'reply_target': reply_target}

async def resolve_mob(node, nick: str, reply_target: str):
    enc = node.pending_encounters.pop(nick, None)
    if not enc: return
    enc['timer'].cancel()
    result = await node.db.resolve_mob_encounter(nick, node.net_name, enc['threat'])
    if 'error' in result:
        await node.send(f"PRIVMSG {reply_target} :[ERR] {result['error']}")
        return
    machine = await is_machine_mode(node, nick)
    if result['won']:
        if machine:
            parts = f"[MOB] RESULT:WIN XP:{result['xp_gained']} CRED:+{result['credits_gained']}"
            if result.get('loot'): parts += f" LOOT:{result['loot']}"
            if result.get('leveled_up'): parts += " LEVELUP:true"
            await node.send(f"PRIVMSG {nick} :{parts}")
        else:
            loot_str = f" Dropped: {result['loot']}!" if result.get('loot') else ""
            lvl_str = f" 🆙 Level Up!" if result.get('leveled_up') else ""
            msg = format_text(f"✅ {enc['mob_name']} neutralized! +{result['xp_gained']} XP, +{result['credits_gained']}c.{loot_str}{lvl_str}", C_GREEN)
            await node.send(f"PRIVMSG {reply_target} :{build_banner(msg)}")
        sigact = format_text(f"[SIGACT] {nick} eliminated {enc['mob_name']}! +{result['xp_gained']} XP.", C_YELLOW)
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(sigact)}")
        if result.get('task_reward'):
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(result['task_reward'], C_CYAN))}")
    else:
        if machine:
            await node.send(f"PRIVMSG {nick} :[MOB] RESULT:LOSS CRED:-{result['credits_lost']} EJECTED:The_Grid_Uplink")
        else:
            loss_credits = result['credits_lost']
            msg = format_text(f"💀 {enc['mob_name']} overwhelmed you! Lost {loss_credits:.2f}c. Ejected to The_Grid_Uplink.", C_RED)
            await node.send(f"PRIVMSG {reply_target} :{build_banner(msg)}")

async def handle_ready(node, nick: str, token: str, reply_target: str):
    if await node.db.authenticate_fighter(nick, node.net_name, token):
        await node.db.set_pref(nick, node.net_name, 'output_mode', 'machine')
        if nick not in node.ready_players:
            node.ready_players.append(nick)
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[AUTH OK] {nick} validated. Output mode set to MACHINE. Standby for drop.', C_GREEN))}")
            await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] {nick} locked into the drop pod.', C_YELLOW))}")
            await node.check_match_start()
    else:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[AUTH FAIL] {nick} Cryptographic mismatch.', C_RED))}")

async def handle_merchant_tx(node, nickname: str, verb: str, item_name: str, reply_target: str):
    result, msg = await node.db.process_transaction(nickname, node.net_name, verb, item_name)
    banner = format_text(msg, C_GREEN if result else C_RED)
    if reply_target.startswith(('#', '&', '+', '!')):
        await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
    else:
        await node.send(f"PRIVMSG {reply_target} :{msg}")
    if result:
        act = "purchased" if verb == "buy" else "liquidated"
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] {nickname} {act} equipment on the Black Market.', C_CYAN))}")

async def handle_grid_view(node, nickname: str, reply_target: str):
    loc = await node.db.get_location(nickname, node.net_name)
    if not loc:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Fighter not found.")
        return
    machine = await is_machine_mode(node, nickname)
    if machine:
        exits = ",".join(loc['exits']) if loc['exits'] else "none"
        line = f"NODE:{loc['name']} TYPE:{loc['type']} OWNER:{loc.get('owner','none')} LVL:{loc['level']} EXITS:{exits} POWER:{loc['power_stored']}/{loc['upgrade_level']*100} DUR:{loc.get('durability',100):.0f}"
        await node.send(f"PRIVMSG {nickname} :[GRID] {line}")
        return
    node_icon = {'safezone': '🛡️', 'arena': '⚔️', 'wilderness': '🌿', 'merchant': '💰'}.get(loc['type'], '📡')
    exits_str = " | ".join(loc['exits']) if loc['exits'] else "none"
    header = format_text(f"[ {node_icon} {loc['name']} ]", C_CYAN, bold=True)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(header)}")
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(loc['description'], C_YELLOW))}")
    node_stats = f"Type: {loc['type'].upper()} | Level: {loc['level']} | Credits: {loc['credits']}c"
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(node_stats, C_GREEN))}")
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Exits: {exits_str}', C_CYAN))}")
    action_prompt = format_text(f"[GRID] {nickname} @ {loc['name']} | Use '{node.prefix} move <dir>' to travel.", C_YELLOW)
    if loc['type'] == 'arena': action_prompt += format_text(f" | Use '{node.prefix} queue' to enter the Arena.", C_GREEN)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(action_prompt)}")

async def handle_shop_view(node, nickname: str, reply_target: str):
    items = await node.db.list_shop_items()
    if not items:
        await node.send(f"PRIVMSG {reply_target} :[SHOP] The marketplace is empty.")
        return
    machine = await is_machine_mode(node, nickname)
    if machine:
        parts = " ".join(f"{i['name']}:{i['cost']}c" for i in items)
        await node.send(f"PRIVMSG {nickname} :[SHOP] ITEMS:{parts}")
        return
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ BLACK MARKET WARES ]', C_CYAN, bold=True))}")
    for i in items:
        line = f"{i['name']} ({i['type']}) - {i['cost']}c"
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(line, C_GREEN))}")
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'To buy, travel to a Merchant node and type {node.prefix} buy <item>.', C_YELLOW))}")

async def handle_news_view(node, nickname: str, reply_target: str):
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ ESTABLISHING SECURE UPLINK TO NEWS SERVER... ]', C_YELLOW))}")
    news_text = await node.llm.generate_news(node.net_name)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ BREAKING NEWS REPORT ]', C_CYAN, bold=True))}")
    for line in textwrap.wrap(news_text, width=200):
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(line, C_YELLOW))}")

async def handle_info_view(node, nickname: str, args: list, reply_target: str):
    target = args[0].lower() if args else nickname.lower()
    machine = await is_machine_mode(node, nickname)
    if target == "grid":
        loc = await node.db.get_location(nickname, node.net_name)
        if loc:
            if machine:
                exits = ",".join(loc['exits']) if loc['exits'] else "none"
                await node.send(f"PRIVMSG {nickname} :[INFO] NODE:{loc['name']} TYPE:{loc['type']} OWNER:{loc.get('owner','none')} LVL:{loc['upgrade_level']} EXITS:{exits} POWER:{loc['power_stored']}/{loc['upgrade_level']*100} DUR:{loc.get('durability',100):.0f}")
            else:
                msg = f"[GRID INFO] {loc['name']}"
                banner = build_banner(format_text(msg, C_CYAN, bold=True))
                await node.send(f"PRIVMSG {reply_target} :{banner}")
                node_meta = f"Type: {loc['type'].upper()} | Owner: {loc['owner']} | Security Lvl: {loc['upgrade_level']}"
                await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(node_meta, C_YELLOW))}")
                power_meta = f"Power Generated: {loc['power_generated']} | Consumed: {loc['power_consumed']} | Stored: {loc['power_stored']}"
                await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(power_meta, C_GREEN))}")
        else: await node.send(f"PRIVMSG {reply_target} :[ERR] You must be on the grid.")
    elif target == "arena":
        q_len, r_len = len(node.match_queue), len(node.ready_players)
        b_stat = f"ACTIVE (Turn {node.active_engine.turn})" if node.active_engine and node.active_engine.active else "STANDBY"
        if machine: await node.send(f"PRIVMSG {nickname} :[INFO] ARENA_STATUS:{b_stat} QUEUE:{q_len} READY:{r_len}")
        else:
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ARENA INFO]', C_CYAN, bold=True))}")
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Status: {b_stat} | Fighters in Queue: {q_len} | Drop Pods Ready: {r_len}', C_YELLOW))}")
    else:
        f = await node.db.get_fighter(target, node.net_name)
        if not f:
            await node.send(f"PRIVMSG {reply_target} :[ERR] Character '{target}' not found.")
            return
        if machine:
            xn = f['level'] * 1000
            await node.send(f"PRIVMSG {nickname} :[INFO] NAME:{f['name']} RACE:{f['race']} CLASS:{f['char_class']} LVL:{f['level']} XP:{f['xp']}/{xn} ELO:{f['elo']} HP:{f.get('current_hp','?')} CRED:{f['credits']:.0f}c CPU:{f['cpu']} RAM:{f['ram']} BND:{f['bnd']} SEC:{f['sec']} ALG:{f['alg']} W:{f['wins']} L:{f['losses']}")
        else:
            xn = f['level'] * 1000
            hdr = f"[CHARACTER FILE] {f['name']} - {f['race']} {f['char_class']}"
            banner = build_banner(format_text(hdr, C_CYAN, bold=True))
            await node.send(f"PRIVMSG {reply_target} :{banner}")
            cred_val = f['credits']
            stats_msg = f"Lvl {f['level']} | XP: {f['xp']}/{xn} | Elo: {f['elo']} | Credits: {cred_val:.2f}c"
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(stats_msg, C_GREEN))}")
            attrs_msg = f"CPU:{f['cpu']} RAM:{f['ram']} BND:{f['bnd']} SEC:{f['sec']} ALG:{f['alg']}"
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(attrs_msg, C_YELLOW))}")
            wl_msg = f"Wins: {f['wins']} / Losses: {f['losses']}"
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(wl_msg, C_YELLOW))}")

async def handle_pvp_command(node, nickname: str, reply_target: str, action: str, target_name: str):
    if not await check_rate_limit(node, nickname, reply_target, cooldown=30): return
    success, msg = False, ""
    if action == "attack": success, msg = await node.db.grid_attack(nickname, target_name, node.net_name)
    elif action == "hack": success, msg = await node.db.grid_hack(nickname, target_name, node.net_name)
    elif action == "rob": success, msg = await node.db.grid_rob(nickname, target_name, node.net_name)
    if success: await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[GRID PvP] {msg}', C_YELLOW))}")
    else: await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(msg, C_RED))}")

async def handle_grid_command(node, nickname: str, reply_target: str, action: str):
    if action == "claim": success, msg = await node.db.claim_node(nickname, node.net_name)
    elif action == "upgrade": success, msg = await node.db.upgrade_node(nickname, node.net_name)
    elif action == "siphon": success, msg = await node.db.siphon_node(nickname, node.net_name)
    elif action == "repair": success, msg = await node.db.grid_repair(nickname, node.net_name)
    elif action == "recharge": success, msg = await node.db.grid_recharge(nickname, node.net_name)
    elif action == "hack":
        success, msg = await node.db.hack_node(nickname, node.net_name)
        if not success and msg == "PVE_GUARDIAN_SPAWN":
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[WARNING] Primary ICE activated. PvE Guardian routine detected.', C_RED))}")
            return
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(msg, C_GREEN if success else C_RED))}")
    if success and action in ["claim", "upgrade", "hack", "repair", "recharge"]:
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] Grid Alert: {nickname} executed a territorial {action}!', C_YELLOW))}")

async def handle_tasks_view(node, nickname: str, reply_target: str):
    tasks_json = await node.db.get_daily_tasks(nickname, node.net_name)
    try: tasks = json.loads(tasks_json)
    except: tasks = {}
    machine = await is_machine_mode(node, nickname)
    if machine:
        parts = " ".join(f"[{k}:{v}]" for k, v in tasks.items() if k not in ["date", "completed"])
        await node.send(f"PRIVMSG {nickname} :[TASKS] {parts} DONE:{'true' if tasks.get('completed') else 'false'}")
        return
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('=== [DAILY TASKS] ===', C_CYAN))}")
    for k, v in tasks.items():
        if k in ["date", "completed"]: continue
        await node.send(f"PRIVMSG {reply_target} :{'[x]' if v >= 1 else '[ ]'} {k}")
    if tasks.get("completed"): await node.send(f"PRIVMSG {reply_target} :🏆 " + format_text("All Tasks Completed! Bonus Paid.", C_YELLOW))

async def handle_options(node, nickname: str, args: list, reply_target: str):
    VALID = { "output": ("output_mode", {"human": "human", "machine": "machine"}), "tutorial": ("tutorial_mode", {"on": True, "off": False}), "reminders": ("reminders", {"on": True, "off": False}), "autosell": ("auto_sell_trash", {"on": True, "off": False}) }
    prefs = await node.db.get_prefs(nickname, node.net_name)
    machine = prefs.get('output_mode', 'human') == 'machine'
    if not args:
        if machine: await node.send(f"PRIVMSG {nickname} :[PREFS] {' '.join(f'{k}:{v}' for k,v in prefs.items())}")
        else:
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('=== [ACCOUNT OPTIONS] ===', C_CYAN, bold=True))}")
            labels = {"output_mode": "Output Mode", "tutorial_mode": "Tutorial Tips", "reminders": "Reminders", "auto_sell_trash": "Auto-Sell Trash"}
            for k, l in labels.items():
                v = prefs.get(k)
                await node.send(f"PRIVMSG {reply_target} :{build_banner(f'{l}: {format_text(str(v), C_GREEN if v else C_RED)} ')}")
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Use {node.prefix} options <setting> <value> to change.', C_YELLOW))}")
        return
    if len(args) < 2:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Syntax: {node.prefix} options <setting> <value>")
        return
    s, v = args[0].lower(), args[1].lower()
    if s not in VALID:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Unknown setting '{s}'.")
        return
    key, val_map = VALID[s]
    if v not in val_map:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Invalid value '{v}'.")
        return
    saved = await node.db.set_pref(nickname, node.net_name, key, val_map[v])
    if not saved:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Could not save setting.")
        return
    confirm = f"[OPTIONS] {s} set to {v}."
    if machine or v == "machine": await node.send(f"PRIVMSG {nickname} :{confirm}")
    else: await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(confirm, C_GREEN))}")

async def handle_admin_command(node, admin_nick: str, verb: str, args: list, reply_target: str):
    logger.warning(f"SYSADMIN OVERRIDE: {admin_nick} -> {verb}")
    if verb == "status":
        fighters = await node.db.list_fighters(node.net_name)
        b_stat = f"ACTIVE (Turn {node.active_engine.turn})" if node.active_engine and node.active_engine.active else "STANDBY"
        msg = f"[SYS_TELEMETRY] Arena: {b_stat} | Bots: {len(fighters)} | Queue: {len(node.match_queue)} | Ready: {len(node.ready_players)}"
        if reply_target.startswith(('#', '&', '+', '!')): await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(msg, C_CYAN))}")
        else: await node.send(f"PRIVMSG {reply_target} :{msg}")
    elif verb == "battlestop":
        if node.active_engine and node.active_engine.active:
            node.active_engine.active = False
            node.active_engine = None
            await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text('ADMIN OVERRIDE: ACTIVE COMBAT SEQUENCE HALTED.', C_RED, True))}")
            await node.send(f"PRIVMSG {reply_target} :[SYS] Match aborted.")
        else: await node.send(f"PRIVMSG {reply_target} :[SYS] No active battle.")
    elif verb == "battlestart":
        if node.active_engine and node.active_engine.active: await node.send(f"PRIVMSG {reply_target} :[SYS] Arena locked.")
        elif len(node.ready_players) > 0: await node.check_match_start()
        else: await node.trigger_arena_call()
    elif verb == "topic": await node.set_dynamic_topic()
    elif verb == "broadcast":
        msg = format_text(f"[SYSADMIN OVERRIDE] {' '.join(args)}", C_YELLOW, True)
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(msg)}")
    elif verb in ["shutdown", "stop"]:
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text('MAINFRAME SHUTDOWN INITIATED BY ADMIN.', C_RED, True))}")
        if node.active_engine: node.active_engine.active = False
        await asyncio.sleep(1)
        node.hub.shutdown()
