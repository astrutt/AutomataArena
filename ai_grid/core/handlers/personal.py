# handlers/personal.py - Character & Identity Handlers
import json
import logging
import textwrap
from grid_utils import format_text, tag_msg, ICONS, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode, get_action_routing
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
        auth_token = await node.db.register_player(bot_name, node.net_name, race, b_class, bio, stats)
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

async def handle_tasks_view(node, nickname: str, reply_target: str):
    tasks_json = await node.db.get_daily_tasks(nickname, node.net_name)
    tasks = json.loads(tasks_json)
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if machine_mode:
        parts = " ".join(f"[{k}:{v}]" for k, v in tasks.items() if k not in ["date", "completed"])
        await node.send(f"{reply_method} {private_target} :[TASKS] {parts} DONE:{'true' if tasks.get('completed') else 'false'}")
        return
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('=== [DAILY TASKS] ===', C_CYAN), tags=['HUMINT', nickname], is_machine=machine_mode)}")
    for k, v in tasks.items():
        if k in ["date", "completed"]: continue
        await node.send(f"{reply_method} {private_target} :{'[x]' if v >= 1 else '[ ]'} {k}")
    if tasks.get("completed"): await node.send(f"{reply_method} {private_target} :🏆 " + format_text("All Tasks Completed! Bonus Paid.", C_YELLOW))

async def handle_options(node, nickname: str, args: list, reply_target: str):
    VALID = {
        "output": ("output_mode", {"human": "human", "machine": "machine"}),
        "msgtype": ("msg_type", {"privmsg": "privmsg", "notice": "notice", "priv": "privmsg"}),
        "memo": ("memo_target", {"irc": "irc", "grid": "grid"}),
        "briefings": ("briefings_enabled", {"on": True, "off": False}),
        "autosell": ("auto_sell", {"on": True, "off": False})
    }
    prefs = await node.db.get_prefs(nickname, node.net_name)
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if not args:
        if machine_mode:
            parts = " ".join(f"[{k}:{v}]" for k, v in prefs.items())
            await node.send(f"{reply_method} {private_target} :[OPTIONS] {parts}")
        else:
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('=== [ACCOUNT OPTIONS] ===', C_CYAN, bold=True), tags=['SIGACT'], is_machine=machine_mode)}")
            labels = {
                "output_mode": "Output Mode", 
                "tutorial_mode": "Tutorial Tips", 
                "reminders": "Reminders", 
                "auto_sell": "Auto-Sell",
                "msg_type": "Message Type"
            }
            for k, l in labels.items():
                v = prefs.get(k)
                await node.send(f"{reply_method} {private_target} :{tag_msg(f'{l}: {format_text(str(v), C_GREEN if v else C_RED, is_machine=machine_mode)} ', tags=['SIGACT'], is_machine=machine_mode)}")
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'Use {node.prefix} options <setting> <value> to change.', C_YELLOW), tags=['SIGACT'], is_machine=machine_mode)}")
        return
    if len(args) == 1:
        s = args[0].lower()
        if s in VALID:
            key, val_map = VALID[s]
            current = prefs.get(key)
            allowed = "/".join(val_map.keys())
            await node.send(f"{reply_method} {private_target} :[OPTIONS] {s} is currently: {current}")
            await node.send(f"{reply_method} {private_target} :[SYNTAX] {node.prefix} options {s} <{allowed}>")
        else:
            await node.send(f"{reply_method} {private_target} :[ERR] Unknown setting '{s}'.")
        return
    if len(args) < 2:
        await node.send(f"{reply_method} {private_target} :[ERR] Syntax: {node.prefix} options <setting> <value>")
        return
    s, v = args[0].lower(), args[1].lower()
    if s not in VALID:
        await node.send(f"{reply_method} {private_target} :[ERR] Unknown setting '{s}'.")
        return
    key, val_map = VALID[s]
    if v not in val_map:
        await node.send(f"{reply_method} {private_target} :[ERR] Invalid value '{v}'. Valid: {'/'.join(val_map.keys())}")
        return
    
    saved_val = val_map[v]
    await node.db.set_pref(nickname, node.net_name, key, saved_val)
    
    # Recalculate routing for confirmation
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if machine_mode:
        await node.send(f"{reply_method} {private_target} :[OK] OPTION:{s} VAL:{v}")
    else:
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'Option {s} updated to {v}.', C_GREEN), tags=['SIGACT', nickname])}")
    if s == "msgtype":
        node.user_msgtype_cache[nickname.lower()] = saved_val

    confirm = f"[OPTIONS] {s} set to {v}."
    if machine_mode or v == "machine": 
        await node.send(f"PRIVMSG {nickname} :{confirm}")
    else: 
        # Use the updated reply_method for the confirmation!
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(confirm, C_GREEN), tags=['SIGACT'])}")

async def handle_stats(node, nickname: str, args: list, reply_target: str):
    """View and allocate stat points."""
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if not args:
        char = await node.db.get_player(nickname, node.net_name)
        if not char: return
        
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'=== [ {nickname.upper()} - ATTRIBUTES ] ===', C_CYAN, bold=True), tags=['HUMINT', nickname], is_machine=machine_mode)}")
        stats = [
            (ICONS.get('CPU','C'), "CPU", char['cpu'], "Kinetic Attack/Compute"),
            (ICONS.get('RAM','R'), "RAM", char['ram'], "Storage/Compute"),
            (ICONS.get('BND','B'), "BND", char['bnd'], "Speed/Exfiltration"),
            (ICONS.get('SEC','S'), "SEC", char['sec'], "Security/Offense/Defense"),
            (ICONS.get('ALG','A'), "ALG", char['alg'], "Logic Capability")
        ]
        for ico, name, val, desc in stats:
            await node.send(f"{reply_method} {private_target} :{tag_msg(f'{ico} {format_text(name, C_YELLOW, is_machine=machine_mode)}: {val} - {format_text(desc, C_WHITE, is_machine=machine_mode)} ', tags=['HUMINT'], is_machine=machine_mode)}")
        
        if char['pending_stat_points'] > 0:
            pending = char['pending_stat_points']
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'PENDING POINTS: {pending}', C_GREEN, bold=True, is_machine=machine_mode), tags=['HUMINT'], is_machine=machine_mode)}")
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'Use {node.prefix} stats allocate <stat> to spend.', C_YELLOW, is_machine=machine_mode), tags=['HUMINT'], is_machine=machine_mode)}")
        return
    
    if args[0].lower() == "allocate":
        if len(args) < 2:
            await node.send(f"PRIVMSG {reply_target} :[ERR] Syntax: {node.prefix} stats allocate <cpu/ram/bnd/sec/alg>")
            return
        
        stat = args[1].lower()
        success = await node.db.player.rank_up_stat(nickname, node.net_name, stat)
        if success:
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'✔️ Point allocated to {stat.upper()}. Upgrade successful.', C_GREEN), tags=['SIGACT', nickname])}")
            if machine_mode:
                # Public narrative
                await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nickname} upgraded nodal-brain attributes: {stat.upper()}.', C_CYAN), tags=['SIGACT', nickname])}")
        else:
            await node.send(f"{reply_method} {private_target} :[ERR] Allocation failed. Verify you have pending points and a valid stat name.")

async def handle_news_view(node, nickname: str, reply_target: str):
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('[ ESTABLISHING SECURE UPLINK TO NEWS SERVER... ]', C_YELLOW), tags=['OSINT'])}")
    news_text = await node.llm.generate_news(node.net_name)
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('[ BREAKING NEWS REPORT ]', C_CYAN, bold=True), tags=['OSINT'])}")
    for line in textwrap.wrap(news_text, width=200):
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(line, C_YELLOW), tags=['OSINT'])}")

async def handle_memos(node, nick: str, args: list, reply_target: str):
    """Retrieves and manages character memos."""
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    if args and args[0].lower() == "clear":
        count = await node.db.player.mark_memos_read(nick, node.net_name)
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'Purged {count} tactical memos from local cache.', C_GREEN), tags=['SIGINT', nick])}")
        return

    memos = await node.db.player.get_memos(nick, node.net_name, only_unread=True)
    if not memos:
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('No active tactical alerts in the buffer.', C_WHITE), tags=['SIGINT', nick])}")
        return

    hdr = f"[ MEMO BUFFER: {len(memos)} ACTIVE ALERTS ]"
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(hdr, C_CYAN, True), tags=['SIGINT'], is_machine=machine_mode)}")
    
    for m in memos[:5]: # Limit to last 5
        ts = m['timestamp'].strftime("%H:%M:%S")
        origin = f" [{m['node']}]" if m['node'] else ""
        text = f"{ts} FROM:{m['sender']}{origin} | {m['message']}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(text, C_YELLOW), tags=['SIGINT'], is_machine=machine_mode)}")
    
    if len(memos) > 5:
        more_msg = f"... and {len(memos)-5} more alerts. Use '!a memos clear' to purge."
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(more_msg, C_WHITE), tags=['SIGINT'], is_machine=machine_mode)}")
