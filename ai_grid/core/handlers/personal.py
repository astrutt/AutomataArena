# handlers/personal.py - Character & Identity Handlers
import json
import logging
import textwrap
from grid_utils import format_text, tag_msg, ICONS, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode, get_action_routing

logger = logging.getLogger("manager")

async def handle_registration(node, nick: str, args: list, reply_target: str):
    try:
        if len(args) < 4:
            await node.send(f"PRIVMSG {reply_target} :Syntax: register <Name> <Race> <Class> <Traits>")
            return
        bot_name, race, b_class = args[0], args[1], args[2]
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(f'Compiling architecture for {bot_name}...', action='SIGACT', nick=nick)}")
        bio = await node.llm.generate_bio(bot_name, race, b_class, " ".join(args[3:]))
        if len(bio) > 200: bio = bio[:197] + "..."
        stats = {'cpu': 5, 'ram': 5, 'bnd': 5, 'sec': 5, 'alg': 5}
        auth_token = await node.db.register_player(bot_name, node.net_name, race, b_class, bio, stats)
        if auth_token:
            payload = json.dumps({"token": auth_token, "bio": bio, "stats": stats, "inventory": ["Basic_Ration"]})
            await node.send(f"NOTICE {bot_name} :[SYS_PAYLOAD] {payload}")
            announcement = f"{bot_name} the {b_class} has entered the Grid!"
            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(announcement, action='OSINT', result='INFO')}")
            await node.set_dynamic_topic()
        else:
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(f'Registration failed: Identity {bot_name!r} already exists.', action='SIGACT', result='FAIL', nick=nick)}")
    except Exception:
        logger.exception("Error in registration")
        await node.send(f"PRIVMSG {reply_target} :{tag_msg('CRITICAL ERROR in registration sequence.', action='SIGACT', result='ERR')}")

async def handle_tasks_view(node, nickname: str, reply_target: str):
    tasks_json = await node.db.get_daily_tasks(nickname, node.net_name)
    tasks = json.loads(tasks_json)
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if machine_mode:
        parts = " ".join(f"{k}:{v}" for k, v in tasks.items() if k not in ["date", "completed"])
        await node.send(f"{reply_method} {private_target} :{tag_msg(parts, action='TASKS', result='INFO', nick=nickname, is_machine=True)}")
        return

    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('=== [DAILY TASKS] ===', C_CYAN), action='OSINT', nick=nickname)}")
    for k, v in tasks.items():
        if k in ["date", "completed"]: continue
        await node.send(f"{reply_method} {private_target} :{'[x]' if v >= 1 else '[ ]'} {k}")

async def handle_options(node, nickname: str, args: list, reply_target: str):
    VALID = {
        "output": ("output_mode", {"human": "human", "machine": "machine"}),
        "msgtype": ("msg_type", {"privmsg": "privmsg", "notice": "notice"}),
        "memo": ("memo_target", {"irc": "irc", "grid": "grid"}),
        "briefings": ("briefings_enabled", {"on": True, "off": False}),
        "autosell": ("auto_sell", {"on": True, "off": False})
    }
    prefs = await node.db.get_prefs(nickname, node.net_name)
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if not args:
        if machine_mode:
            parts = " ".join(f"{k}:{v}" for k, v in prefs.items())
            await node.send(f"{reply_method} {private_target} :{tag_msg(parts, action='OPTIONS', result='INFO', nick=nickname, is_machine=True)}")
        else:
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('=== [ACCOUNT OPTIONS] ===', C_CYAN, True), action='OSINT')}")
            for k, v in prefs.items():
                await node.send(f"{reply_method} {private_target} :{k}: {format_text(str(v), C_GREEN if v else C_RED)}")
        return

    if len(args) < 2: return
    s, v = args[0].lower(), args[1].lower()
    if s not in VALID: return
    key, val_map = VALID[s]
    if v not in val_map: return
    
    await node.db.set_pref(nickname, node.net_name, key, val_map[v])
    await node.send(f"{reply_method} {private_target} :{tag_msg(f'Option {s} set to {v}.', action='SIGACT', result='SUCCESS', nick=nickname, is_machine=machine_mode)}")

async def handle_stats(node, nickname: str, args: list, reply_target: str):
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    char = await node.db.get_player(nickname, node.net_name)
    if not char: return

    if not args:
        if machine_mode:
            msg = f"CPU:{char['cpu']} RAM:{char['ram']} BND:{char['bnd']} SEC:{char['sec']} ALG:{char['alg']} POINTS:{char['pending_stat_points']}"
            await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='STATS', result='INFO', nick=nickname, is_machine=True)}")
        else:
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'[ {nickname.upper()} - ATTRIBUTES ]', C_CYAN, True), action='OSINT')}")
            stats = [("CPU", char['cpu']), ("RAM", char['ram']), ("BND", char['bnd']), ("SEC", char['sec']), ("ALG", char['alg'])]
            for n, v in stats:
                await node.send(f"{reply_method} {private_target} :{n}: {format_text(str(v), C_YELLOW)}")
            if char['pending_stat_points'] > 0:
                await node.send(f"{reply_method} {private_target} :{tag_msg(f'PENDING POINTS: {char['pending_stat_points']}', action='OSINT', result='INFO')}")
        return
    
    if args[0].lower() == "allocate" and len(args) > 1:
        stat = args[1].lower()
        success = await node.db.player.rank_up_stat(nickname, node.net_name, stat)
        res_tag = 'SUCCESS' if success else 'FAIL'
        await node.send(f"{reply_method} {private_target} :{tag_msg(f'Stat {stat.upper()} update: {res_tag}', action='SIGACT', result=res_tag, nick=nickname, is_machine=machine_mode)}")

async def handle_news_view(node, nickname: str, reply_target: str):
    private_target, _, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    news_text = await node.llm.generate_news(node.net_name)
    await node.send(f"{reply_method} {private_target} :{tag_msg('--- BREAKING NEWS ---', action='OSINT', is_machine=machine_mode)}")
    for line in textwrap.wrap(news_text, width=200):
        await node.send(f"{reply_method} {private_target} :{tag_msg(line, action='OSINT', is_machine=machine_mode)}")

async def handle_memos(node, nick: str, args: list, reply_target: str):
    private_target, _, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    if args and args[0].lower() == "clear":
        count = await node.db.player.mark_memos_read(nick, node.net_name)
        await node.send(f"{reply_method} {private_target} :{tag_msg(f'Memos cleared: {count}', action='SIGINT', result='OK', nick=nick, is_machine=machine_mode)}")
        return

    memos = await node.db.player.get_memos(nick, node.net_name, only_unread=True)
    msg = f"MEMO_COUNT:{len(memos)}"
    if not machine_mode:
         msg = f"Active Memos: {len(memos)}"
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGINT', result='INFO', nick=nick, is_machine=machine_mode)}")
    
    for m in memos[:5]:
        line = f"FROM:{m['sender']} [{m['node']}] | {m['message']}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(line, action='SIGINT', is_machine=machine_mode)}")
