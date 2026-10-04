# handlers/spectator.py - Spectator "IdleRPG" & Activity Monitoring
import time
import logging
import datetime
from ai_grid.grid_utils import format_text, tag_msg, ICONS, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode, get_action_routing

logger = logging.getLogger("manager")

async def handle_spectator_view(node, nickname: str, args: list, reply_target: str):
    """Shows current session activity ratio and status."""
    nick_lower = nickname.lower()
    if nick_lower not in node.channel_users:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg('Absence in grid uplink detected.', action='ERR', result='FAIL')}")
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
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(f'No record found for historical probe: {target}', action='OSINT', result='FAIL')}")
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
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('=== [SPECTATOR COMMANDS] ===', C_CYAN, True), action='OSINT', is_machine=False)}")
        for line in ["spectator view", "spectator stats", "spectator drop <nick>", "spectator inventory"]:
            await node.send(f"{reply_method} {private_target} :{tag_msg(line, action='OSINT', is_machine=False)}")

DROP_ITEM_ALIASES = {
    "nano_patch": "Nano_Patch",
    "nanopatch": "Nano_Patch",
    "patch": "Nano_Patch",
    "heal": "Nano_Patch",
    "hp": "Nano_Patch",
    "nano": "Nano_Patch",
    "battery": "Battery",
    "batt": "Battery",
    "power": "Battery",
    "cell": "Battery",
    "up": "Battery",
    "energy": "Battery",
    "zeroday_chain": "ZeroDay_Chain",
    "zeroday": "ZeroDay_Chain",
    "0day": "ZeroDay_Chain",
    "chain": "ZeroDay_Chain",
    "exploit": "ZeroDay_Chain",
    "zerodaychain": "ZeroDay_Chain",
}

def resolve_item_alias(token: str):
    if not token:
        return None
    norm = token.lower().replace("-", "_").replace(" ", "_")
    return DROP_ITEM_ALIASES.get(norm)

def parse_drop_args(args: list):
    """Disambiguates <target> <item> and <item> <target> syntax."""
    if not args:
        return None, "Nano_Patch"
    if len(args) == 1:
        item = resolve_item_alias(args[0])
        if item:
            return None, item
        else:
            return args[0], "Nano_Patch"
    
    item0 = resolve_item_alias(args[0])
    item1 = resolve_item_alias(args[1])
    if item0 and not item1:
        return args[1], item0
    elif item1 and not item0:
        return args[0], item1
    elif item0 and item1:
        return args[1], item0
    else:
        return args[0], "Nano_Patch"

async def handle_spectator_drop(node, nickname: str, args: list, reply_target: str):
    target, item_name = parse_drop_args(args)
    success, msg = await node.db.spectator_drop(nickname, node.net_name, target=target, item_name=item_name)
    color = C_GREEN if success else C_RED
    chan = node.config.get('channel', reply_target) if hasattr(node, 'config') and isinstance(node.config, dict) else reply_target

    if success and target and getattr(node, 'active_engine', None) and getattr(node.active_engine, 'active', False):
        engine = node.active_engine
        if target in engine.entities:
            ent = engine.entities[target]
            if getattr(ent, 'is_alive', getattr(ent, 'alive', False)):
                effect_desc = ""
                if item_name == "Nano_Patch":
                    ent.hp = min(ent.max_hp, ent.hp + 50)
                    effect_desc = f"+50 HP ({ent.hp}/{ent.max_hp})"
                elif item_name == "Battery":
                    ent.up = min(ent.max_up, ent.up + 50)
                    effect_desc = f"+50 uP ({ent.up}/{ent.max_up})"
                elif item_name == "ZeroDay_Chain":
                    ent.inventory.append("Zero-Day")
                    effect_desc = "Zero-Day Exploit loaded"

                if hasattr(engine, 'turn_events') and isinstance(engine.turn_events, list):
                    engine.turn_events.append({
                        "type": "spectator_drop",
                        "donor": nickname,
                        "target": target,
                        "item": item_name,
                        "effect": effect_desc
                    })
                alert = format_text(f"⚡ [ORBITAL INJECTION] {nickname} dropped {item_name} to {target}! {effect_desc}", C_YELLOW, True)
                await node.send(f"PRIVMSG {chan} :{tag_msg(alert, action='SIGACT', result='INJECT', nick=nickname)}")

    # Orbital drops are always broadcast with SIGACT
    await node.send(f"PRIVMSG {chan} :{tag_msg(format_text(msg, color, success), action='SIGACT', result='ORBITAL', nick=nickname)}")

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
