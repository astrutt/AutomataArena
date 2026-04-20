# handlers/spectator.py - Spectator "IdleRPG" & Activity Monitoring
import time
import logging
import datetime
from grid_utils import format_text, tag_msg, ICONS, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode, get_action_routing

logger = logging.getLogger("manager")

async def handle_spectator_view(node, nickname: str, args: list, reply_target: str):
    """Shows current session activity ratio and status."""
    nick_lower = nickname.lower()
    if nick_lower not in node.channel_users:
        await node.send(f"PRIVMSG {reply_target} :[ERR] absence in grid uplink.")
        return

    data = node.channel_users[nick_lower]
    idle_mins = (time.time() - data.get('join_time', time.time())) / 60.0
    chat_lines = data.get('chat_lines', 0)
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if machine_mode:
        msg = f"IDLE_MINS:{idle_mins:.1f} MSGS:{chat_lines} RATIO:{chat_lines/(max(1, idle_mins/60)):.2f}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SPECTATOR', result='INFO', nick=nickname, is_machine=True)}")
    else:
        hdr = f"=== [SESSION: {nickname}] ==="
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(hdr, C_CYAN, True), action='HUMINT', nick=nickname)}")
        msg = f"Ratio: {chat_lines/max(1, idle_mins/60.0):.2f} msg/hr | Uplink: {idle_mins:.1f}m"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(msg, C_GREEN), action='HUMINT')}")

async def handle_spectator_stats(node, nickname: str, args: list, reply_target: str):
    """Shows persistent historical stats, rank, and credits."""
    target = args[0] if args else nickname
    stats = await node.db.get_spectator_stats(target, node.net_name, node.config)
    if not stats:
        await node.send(f"PRIVMSG {reply_target} :[ERR] No record for '{target}'.")
        return
    
    private_target, _, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    if machine_mode:
        msg = f"IDLE_H:{stats['idle_hours']} MSGS:{stats['chat_total']} RANK:{stats['rank_level']} XP:{stats['xp']}/{stats['xp_threshold']} CRED:{stats['credits']:.1f}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SPECTATOR', result='STATS', nick=nickname, is_machine=True)}")
    else:
        hdr = f"[SPECTATOR ARCHIVE] {stats['name']} - {stats['rank_title']}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(hdr, C_CYAN, True), action='OSINT', nick=nickname)}")
        main = f"Credits: {stats['credits']:.2f}c | Rank: {stats['rank_level']} ({stats['xp']}/{stats['xp_threshold']} XP)"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(main, C_GREEN), action='OSINT')}")

async def handle_spectator_help(node, nickname: str, reply_target: str):
    private_target, _, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    if machine_mode:
        await node.send(f"{reply_method} {private_target} :{tag_msg('SUB=SPECTATOR CMD=stats,view,drop,inventory', action='HELP', is_machine=True)}")
    else:
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('=== [SPECTATOR COMMANDS] ===', C_CYAN, True), action='OSINT')}")
        for line in ["spectator view", "spectator stats", "spectator drop <nick>", "spectator inventory"]:
            await node.send(f"{reply_method} {private_target} :{tag_msg(line, action='OSINT')}")

async def handle_spectator_drop(node, nickname: str, args: list, reply_target: str):
    target = args[0] if args else None
    success, msg = await node.db.spectator_drop(nickname, node.net_name, target)
    color = C_GREEN if success else C_RED
    # Orbital drops are always broadcast with SIGACT
    await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(msg, color, success), action='SIGACT', result='ORBITAL', nick=nickname)}")

async def handle_spectator_inventory(node, nickname: str, reply_target: str):
    char = await node.db.get_player(nickname, node.net_name)
    if not char: return
    private_target, _, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    import json
    inv = json.loads(char['inventory'])
    msg = f"ORBITAL_INV:{','.join(inv) if inv else 'EMPTY'}"
    if not machine_mode:
        msg = f"Orbital Storage: {', '.join(inv) if inv else 'Empty'}"
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='OSINT', result='INFO', nick=nickname, is_machine=machine_mode)}")
