# handlers/personal.py - Character & Identity Handlers
import json
import logging
import textwrap
from grid_utils import format_text, tag_msg, ICONS, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode
from .spectator import handle_spectator_stats

logger = logging.getLogger("manager")

async def handle_registration(node, nick: str, args: list, reply_target: str):
    try:
        if len(args) < 4:
            await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} register <Name> <Race> <Class> <Traits>")
            return
        bot_name, race, b_class = args[0], args[1], args[2]
        traits = " ".join(args[3:])
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'Compiling architecture for {bot_name}...', C_GREEN), tags=['SIGACT'])}")
        bio = await node.llm.generate_bio(bot_name, race, b_class, traits)
        if len(bio) > 200: bio = bio[:197] + "..."
        stats = {'cpu': 5, 'ram': 5, 'bnd': 5, 'sec': 5, 'alg': 5}
        auth_token = await node.db.register_fighter(bot_name, node.net_name, race, b_class, bio, stats)
        if auth_token:
            payload = json.dumps({"token": auth_token, "bio": bio, "stats": stats, "inventory": ["Basic_Ration"]})
            await node.send(f"NOTICE {bot_name} :[SYS_PAYLOAD] {payload}")
            announcement = f"{ICONS.get(race, '⚙️')} {format_text(bot_name, C_CYAN, True)} the {ICONS.get(b_class, '⚔️')} {b_class} has entered the Grid!"
            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(announcement, tags=['OSINT', 'HUMINT'])}")
            await node.set_dynamic_topic()
        else:
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'Registration failed: Identity {bot_name!r} is already registered.', C_RED), tags=['SIGACT'])}")
    except Exception as e:
        logger.exception("Error in handle_registration")
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('CRITICAL ERROR during registration sequence.', C_RED), tags=['SIGACT'])}")

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
                await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(msg, C_CYAN, bold=True), tags=['GEOINT'], location=loc['name'], is_machine=machine)}")
                node_meta = f"Type: {loc['type'].upper()} | Owner: {loc['owner']} | Security Lvl: {loc['upgrade_level']}"
                await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(node_meta, C_YELLOW), tags=['GEOINT'], is_machine=machine)}")
                power_meta = f"Power Generated: {loc['power_generated']} | Consumed: {loc['power_consumed']} | Stored: {loc['power_stored']}"
                await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(power_meta, C_GREEN), tags=['GEOINT'], is_machine=machine)}")
        else: await node.send(f"PRIVMSG {reply_target} :[ERR] You must be on the grid.")
    elif target == "arena":
        q_len, r_len = len(node.match_queue), len(node.ready_players)
        b_stat = f"ACTIVE (Turn {node.active_engine.turn})" if node.active_engine and node.active_engine.active else "STANDBY"
        if machine: await node.send(f"PRIVMSG {nickname} :[INFO] ARENA_STATUS:{b_stat} QUEUE:{q_len} READY:{r_len}")
        else:
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('[ARENA INFO]', C_CYAN, bold=True), tags=['ARENA'], is_machine=machine)}")
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'Status: {b_stat} | Fighters in Queue: {q_len} | Drop Pods Ready: {r_len}', C_YELLOW), tags=['ARENA'], is_machine=machine)}")
    else:
        f = await node.db.get_fighter(target, node.net_name)
        if not f:
            await node.send(f"PRIVMSG {reply_target} :[ERR] Character '{target}' not found.")
            return
            
        if f.get('race') == "Spectator":
            await handle_spectator_stats(node, nickname, [target], reply_target)
            return

        if machine:
            xn = f['level'] * 1000
            await node.send(f"PRIVMSG {nickname} :[INFO] NAME:{f['name']} RACE:{f['race']} CLASS:{f['char_class']} LVL:{f['level']} XP:{f['xp']}/{xn} ELO:{f['elo']} HP:{f.get('current_hp','?')} CRED:{f['credits']:.0f}c CPU:{f['cpu']} RAM:{f['ram']} BND:{f['bnd']} SEC:{f['sec']} ALG:{f['alg']} W:{f['wins']} L:{f['losses']}")
        else:
            # Determine target's intel tag based on their output preference
            target_prefs = await node.db.get_prefs(target, node.net_name)
            intel_tag = "AI-INT" if target_prefs.get('output_mode') == 'machine' else "HUMINT"
            
            xn = f['level'] * 1000
            hdr = f"[CHARACTER FILE] {f['name']} - {f['race']} {f['char_class']}"
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(hdr, C_CYAN, bold=True), tags=[intel_tag, f['name']], is_machine=machine)}")
            cred_val = f['credits']
            stats_msg = f"Lvl {f['level']} | XP: {f['xp']}/{xn} | Elo: {f['elo']} | {ICONS['CREDITS']} {cred_val:.2f}c"
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(stats_msg, C_GREEN), tags=[intel_tag], is_machine=machine)}")
            
            # Territory & Mesh Power
            mesh_msg = f"{ICONS['TERRITORY']} Territory: {f['territory_count']} | {ICONS['POWER']} Mesh Power: {f['mesh_power']:.0f} uP"
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(mesh_msg, C_CYAN), tags=[intel_tag], is_machine=machine)}")
            
            attrs_msg = f"{ICONS['CPU']}CPU:{f['cpu']} {ICONS['RAM']}RAM:{f['ram']} {ICONS['BND']}BND:{f['bnd']} {ICONS['SEC']}SEC:{f['sec']} {ICONS['ALG']}ALG:{f['alg']}"
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(attrs_msg, C_YELLOW), tags=[intel_tag], is_machine=machine)}")
            
            wl_msg = f"Wins: {f['wins']} / Losses: {f['losses']}"
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(wl_msg, C_YELLOW), tags=[intel_tag], is_machine=machine)}")

async def handle_tasks_view(node, nickname: str, reply_target: str):
    tasks_json = await node.db.get_daily_tasks(nickname, node.net_name)
    try: tasks = json.loads(tasks_json)
    except: tasks = {}
    machine = await is_machine_mode(node, nickname)
    if machine:
        parts = " ".join(f"[{k}:{v}]" for k, v in tasks.items() if k not in ["date", "completed"])
        await node.send(f"PRIVMSG {nickname} :[TASKS] {parts} DONE:{'true' if tasks.get('completed') else 'false'}")
        return
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('=== [DAILY TASKS] ===', C_CYAN), tags=['HUMINT', nickname], is_machine=machine)}")
    for k, v in tasks.items():
        if k in ["date", "completed"]: continue
        await node.send(f"PRIVMSG {reply_target} :{'[x]' if v >= 1 else '[ ]'} {k}")
    if tasks.get("completed"): await node.send(f"PRIVMSG {reply_target} :🏆 " + format_text("All Tasks Completed! Bonus Paid.", C_YELLOW))

async def handle_options(node, nickname: str, args: list, reply_target: str):
    VALID = { 
        "output": ("output_mode", {"human": "human", "machine": "machine"}), 
        "tutorial": ("tutorial_mode", {"on": True, "off": False}), 
        "reminders": ("reminders", {"on": True, "off": False}), 
        "autosell": ("auto_sell_trash", {"on": True, "off": False}),
        "msgtype": ("msgtype", {"notice": "NOTICE", "privmsg": "PRIVMSG"})
    }
    prefs = await node.db.get_prefs(nickname, node.net_name)
    
    # Sync cache on every view to ensure GridNode knows the current preference
    if 'msgtype' in prefs:
        node.user_msgtype_cache[nickname.lower()] = prefs['msgtype']

    machine = prefs.get('output_mode', 'human') == 'machine'
    if not args:
        if machine: await node.send(f"PRIVMSG {nickname} :[PREFS] {' '.join(f'{k}:{v}' for k,v in prefs.items())}")
        else:
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('=== [ACCOUNT OPTIONS] ===', C_CYAN, bold=True), tags=['SIGACT'], is_machine=machine)}")
            labels = {
                "output_mode": "Output Mode", 
                "tutorial_mode": "Tutorial Tips", 
                "reminders": "Reminders", 
                "auto_sell_trash": "Auto-Sell Trash",
                "msgtype": "Message Type"
            }
            for k, l in labels.items():
                v = prefs.get(k)
                await node.send(f"PRIVMSG {reply_target} :{tag_msg(f'{l}: {format_text(str(v), C_GREEN if v else C_RED, is_machine=machine)} ', tags=['SIGACT'], is_machine=machine)}")
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'Use {node.prefix} options <setting> <value> to change.', C_YELLOW), tags=['SIGACT'], is_machine=machine)}")
        return
    if len(args) == 1:
        s = args[0].lower()
        if s in VALID:
            key, val_map = VALID[s]
            current = prefs.get(key)
            allowed = "/".join(val_map.keys())
            await node.send(f"PRIVMSG {reply_target} :[OPTIONS] {s} is currently: {current}")
            await node.send(f"PRIVMSG {reply_target} :[SYNTAX] {node.prefix} options {s} <{allowed}>")
        else:
            await node.send(f"PRIVMSG {reply_target} :[ERR] Unknown setting '{s}'.")
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
    
    saved_val = val_map[v]
    saved = await node.db.set_pref(nickname, node.net_name, key, saved_val)
    if not saved:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Could not save setting.")
        return
    
    # Update cache immediately on change
    if s == "msgtype":
        node.user_msgtype_cache[nickname.lower()] = saved_val

    confirm = f"[OPTIONS] {s} set to {v}."
    if machine or v == "machine": await node.send(f"PRIVMSG {nickname} :{confirm}")
    else: await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(confirm, C_GREEN), tags=['SIGACT'])}")

async def handle_stats(node, nickname: str, args: list, reply_target: str):
    """View and allocate stat points."""
    if not args:
        char = await node.db.get_fighter(nickname, node.net_name)
        if not char: return
        
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'=== [ {nickname.upper()} - ATTRIBUTES ] ===', C_CYAN, bold=True), tags=['HUMINT', nickname], is_machine=machine)}")
        stats = [
            ("CPU", char['cpu'], "Kinetic Attack/Compute"),
            ("RAM", char['ram'], "Storage/Compute"),
            ("BND", char['bnd'], "Speed/Exfiltration"),
            ("SEC", char['sec'], "Security/Offense/Defense"),
            ("ALG", char['alg'], "Logic Capability")
        ]
        for name, val, desc in stats:
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(f'{format_text(name, C_YELLOW, is_machine=machine)}: {val} - {format_text(desc, C_WHITE, is_machine=machine)} ', tags=['HUMINT'], is_machine=machine)}")
        
        if char['pending_stat_points'] > 0:
            pending = char['pending_stat_points']
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'PENDING POINTS: {pending}', C_GREEN, bold=True, is_machine=machine), tags=['HUMINT'], is_machine=machine)}")
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'Use {node.prefix} stats allocate <stat> to spend.', C_YELLOW, is_machine=machine), tags=['HUMINT'], is_machine=machine)}")
        return
    
    if args[0].lower() == "allocate":
        if len(args) < 2:
            await node.send(f"PRIVMSG {reply_target} :[ERR] Syntax: {node.prefix} stats allocate <cpu/ram/bnd/sec/alg>")
            return
        
        stat = args[1].lower()
        success = await node.db.player.rank_up_stat(nickname, node.net_name, stat)
        if success:
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'✔️ Point allocated to {stat.upper()}. Upgrade successful.', C_GREEN), tags=['SIGACT', nickname])}")
        else:
            await node.send(f"PRIVMSG {reply_target} :[ERR] Allocation failed. Verify you have pending points and a valid stat name.")

async def handle_news_view(node, nickname: str, reply_target: str):
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('[ ESTABLISHING SECURE UPLINK TO NEWS SERVER... ]', C_YELLOW), tags=['OSINT'])}")
    news_text = await node.llm.generate_news(node.net_name)
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('[ BREAKING NEWS REPORT ]', C_CYAN, bold=True), tags=['OSINT'])}")
    for line in textwrap.wrap(news_text, width=200):
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(line, C_YELLOW), tags=['OSINT'])}")
