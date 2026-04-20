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
        await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nickname} - absence in grid uplink - msg ignored")
        return

    data = node.channel_users[nick_lower]
    join_time = data.get('join_time', time.time())
    chat_lines = data.get('chat_lines', 0)
    idle_secs = time.time() - join_time
    idle_mins = idle_secs / 60.0
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if machine_mode:
        await node.send(f"{reply_method} {private_target} :[SPECTATOR] SESSION_IDLE_MINS:{idle_mins:.1f} SESSION_MSGS:{chat_lines} RATIO:{chat_lines/(max(1, idle_mins/60)):.2f}")
    else:
        hdr = f"=== [SPECTATOR SESSION: {nickname}] ==="
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(hdr, C_CYAN, bold=True), tags=['HUMINT', nickname])}")
        
        status = "IDLING" if chat_lines == 0 else "PARTICIPATING"
        ratio = chat_lines / max(1, idle_mins / 60.0)
        
        msg = f"Status: {status} | Ratio: {ratio:.2f} msg/hr | Uplink Time: {idle_mins:.1f}m"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(msg, C_GREEN), tags=['HUMINT', nickname])}")
        msg2 = f"Accumulated session data: {chat_lines} messages processed."
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(msg2, C_YELLOW), tags=['HUMINT', nickname])}")

async def handle_spectator_stats(node, nickname: str, args: list, reply_target: str):
    """Shows persistent historical stats, rank, and credits."""
    target = args[0] if args else nickname
    stats = await node.db.get_spectator_stats(target, node.net_name, node.config)
    
    if not stats:
        await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nickname} - no record found for '{target}' - msg ignored")
        return
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    if machine_mode:
        await node.send(f"{reply_method} {private_target} :[SPECTATOR] STATS=IDLE:{stats['idle_hours']} MSGS:{stats['chat_total']} RANK:{stats['rank_level']} XP:{stats['xp']}/{stats['xp_threshold']} CREDITS:{stats['credits']}")
    else:
        hdr = f"[SPECTATOR ARCHIVE] {stats['name']} - {stats['rank_title']}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(hdr, C_CYAN, bold=True), tags=['OSINT', stats['name']])}")
        
        main_stats = f"Credits: {stats['credits']:.2f}c | Rank: {stats['rank_level']} ({stats['xp']}/{stats['xp_threshold']} XP)"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(main_stats, C_GREEN), tags=['OSINT', stats['name']])}")
        
        activity = f"Total Idle Time: {stats['idle_hours']}h | Activity Ratio: {stats['ratio']} msg/hr"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(activity, C_YELLOW), tags=['OSINT', stats['name']])}")
        
        footer = f"Last Presence Detected: {stats['last_seen']}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(footer, C_WHITE), tags=['OSINT', stats['name']])}")

async def handle_spectator_help(node, nickname: str, reply_target: str):
    """Documentation for spectator mechanics."""
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if machine_mode:
        cmds = {
            "spectator": "View current activity.",
            "spectator stats": "View persistent stats and Rank.",
            "spectator drop": "Drop item in Arena (Public or Targeted).",
            "spectator drop": "Drop item in Arena (Public or Targeted)."
        }
        for cmd, desc in cmds.items():
            await node.send(f"{reply_method} {private_target} :{tag_msg(f'HELP:SUB=SPECTATOR|CMD={cmd}|DESC={desc}', tags=['OSINT'], is_machine=True)}")
    else:
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('=== [SPECTATOR COMMANDS] ===', C_CYAN, bold=True), tags=['OSINT'])}")
        help_lines = [
            f"{node.prefix} spectator         - View current session activity.",
            f"{node.prefix} spectator stats   - View persistent global stats and Rank.",
            f"{node.prefix} spectator drop    - Drop a support item to 'anyone' in Arena (2500c).",
            f"{node.prefix} spectator drop <nick> - Drop support item to specific player (2500c).",
            f"{node.prefix} spectator drop <nick> - Drop support item to specific player (2500c).",
            "Rewards: Earn credits and rank progress in real-time. Active chatting provides large bonuses."
        ]
        for line in help_lines:
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(line, C_YELLOW), tags=['OSINT'])}")

async def handle_spectator_drop(node, nickname: str, args: list, reply_target: str):
    """Bridge for spectator orbital drops."""
    target = args[0] if args else None
    
    success, msg = await node.db.spectator_drop(nickname, node.net_name, target)
    color = C_GREEN if success else C_RED
    
    # Drops are flashy and broadcast to channel
    await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(msg, color, bold=success), tags=['SIGACT', 'ORBITAL', nickname])}")


async def handle_spectator_inventory(node, nickname: str, reply_target: str):
    """Simplified inventory view for spectators."""
    char = await node.db.get_player(nickname, node.net_name)
    if not char: return

    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    import json
    inv = json.loads(char['inventory'])
    if not inv:
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('Your orbital storage is empty.', C_WHITE), tags=['OSINT', nickname])}")
    else:
        items = ", ".join(inv)
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'Orbital Storage: {items}', C_CYAN), tags=['OSINT', nickname])}")
