# osint.py - Task 019
import asyncio
import logging
import time
from grid_utils import (
    format_text, tag_msg, ICONS, C_CYAN, C_YELLOW, C_GREEN, C_RED, C_ORANGE,
    C_PURPLE, C_PINK, C_L_GREEN, C_BLUE, C_WHITE, generate_gradient, generate_meter
)
from .base import get_action_routing, check_rate_limit
from .spectator import handle_spectator_stats

logger = logging.getLogger("manager")

async def handle_economy_osint(node, source, target):
    """Broadcasting global financial metrics."""
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, source, target)
    
    stats = await node.db.get_global_economy()
    market = await node.db.get_market_status()
    junk_m = market.get('junk', 1.0)
    
    msg = f"CIRCULATION:{stats['total_credits']} RESERVES:{stats['total_data_units']:.1f} VARIANCE:{junk_m:.2f}"
    if not machine_mode:
        circ = format_text(f"{stats['total_credits']:,}c", C_WHITE)
        reserves = format_text(f"{stats['total_data_units']:.1f}u", C_WHITE)
        market_health = format_text(f"{junk_m:.2f}x", C_WHITE)
        msg = f"Circulation: {circ} | Reserves: {reserves} | Market: {market_health}"

    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='ECONOMY', nick=source, is_machine=machine_mode)}")

async def handle_gridpower_osint(node, source, target):
    """Broadcasting energy logistics and generation metrics."""
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, source, target)
    
    tele = await node.db.get_grid_telemetry()
    capacity = tele['total_nodes'] * 1000
    
    msg = f"STORED:{tele['total_power']:.0f} CAPACITY:{capacity} GEN:{tele['total_generation']:.0f}"
    if not machine_mode:
        p_meter = generate_meter(tele['total_power'], capacity)
        storage = f"STORED: [{p_meter}] {format_text(f'{tele['total_power']:.0f}uP', C_WHITE)}"
        gen = f"GEN: {format_text(f'{tele['total_generation']:.0f}uP/tick', C_L_GREEN)}"
        msg = f"{storage} | {gen}"
        
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='POWER', nick=source, is_machine=machine_mode)}")

async def handle_gridstability_osint(node, source, target):
    """Broadcasting mesh integrity and claim metrics."""
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, source, target)
    
    tele = await node.db.get_grid_telemetry()
    msg = f"CLAIMED:{tele['claimed_nodes']} TOTAL:{tele['total_nodes']} PERCENT:{tele['claimed_percent']:.1f}"
    if not machine_mode:
        m_meter = generate_meter(tele['claimed_nodes'], tele['total_nodes'])
        claimed = f"CLAIMED: [{m_meter}] {format_text(f'{tele['claimed_percent']:.1f}%', C_GREEN)} ({tele['claimed_nodes']}/{tele['total_nodes']})"
        msg = f"{claimed}"

    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='OSINT', result='INFO', nick=source, is_machine=machine_mode)}")

async def handle_networks_osint(node, source, target):
    """Broadcasting topological bridge statistics."""
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, source, target)
    
    all_nodes = list(node.hub.nodes.values())
    net_count = len(all_nodes)
    
    if machine_mode:
        nets = ",".join([f"{net.net_name}:{'ONLINE' if net.irc.is_connected() else 'OFFLINE'}" for net in all_nodes])
        msg = f"COUNT:{net_count} NETS:{nets}"
    else:
        net_entries = []
        for net in all_nodes:
            status = format_text("(ONLINE)", C_GREEN) if net.irc.is_connected() else format_text("(OFFLINE)", C_RED)
            net_entries.append(f"{net.net_name} {status}")
        msg = f"Node Count: {net_count} | {' - '.join(net_entries)}"

    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='NETWORKS', nick=source, is_machine=machine_mode)}")

async def handle_about_osint(node, source, target):
    """Broadcasting core project metadata."""
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, source, target)
    
    msg = "VER:1.8.0 SRC:https://github.com/astrutt/AutomataArena"
    if not machine_mode:
        msg = f"Version: {format_text('1.8.0', C_WHITE)} | Source: {format_text('https://github.com/astrutt/AutomataArena', C_BLUE)}"

    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='ABOUT', nick=source, is_machine=machine_mode)}")

async def handle_info_nick(node, nickname: str, args: list, reply_target: str):
    """Public character profile lookup."""
    target = args[0].lower() if args else nickname.lower()
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    # 1. Grid Info
    if target == "grid":
        loc = await node.db.get_location(nickname, node.net_name)
        if loc:
            msg = f"NODE:{loc['name']} TYPE:{loc['type']} OWNER:{loc.get('owner','none')} LVL:{loc['upgrade_level']} POWER:{loc['power_stored']:.1f}"
            if not machine_mode:
                 msg = format_text(f"[GRID INFO] {loc['name']} | Type: {loc['type'].upper()} | Owner: {loc.get('owner','none')}", C_CYAN)
            await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='GEOINT', nick=nickname, is_machine=machine_mode)}")
        else:
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(f'{nickname} - you must be on the grid to access GEOINT.', action='GEOINT', result='ERR')}")
        return

    # 2. Arena Info
    if target == "arena":
        stat = "ACTIVE" if node.active_engine and node.active_engine.active else "STANDBY"
        msg = f"STATUS:{stat} QUEUE:{len(node.match_queue)} READY:{len(node.ready_players)}"
        if not machine_mode:
            msg = f"Status: {stat} | Queue: {len(node.match_queue)} | Ready: {len(node.ready_players)}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='ARENA', nick=nickname, is_machine=machine_mode)}")
        return

    # 3. Character Info
    f = await node.db.get_player(target, node.net_name)
    if not f:
        await node.send(f"{reply_method} {private_target} :{tag_msg(f'Character {target!r} not found in historical archives.', action='HUMINT', result='ERR', nick=nickname, is_machine=machine_mode)}")
        return
        
    if f.get('race') == "Spectator":
        await handle_spectator_stats(node, nickname, [target], private_target)
        return

    if machine_mode:
        xn = f['level'] * 1000
        msg = f"NAME:{f['name']} RACE:{f['race']} CLASS:{f['char_class']} LVL:{f['level']} XP:{f['xp']}/{xn} ELO:{f['elo']} CRED:{f['credits']:.0f} CPU:{f['cpu']} RAM:{f['ram']} BND:{f['bnd']} SEC:{f['sec']} ALG:{f['alg']}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='HUMINT', result='INFO', nick=nickname, is_machine=True)}")
    else:
        hdr = f"[CHARACTER] {f['name']} - {f['race']} {f['char_class']}"
        if f.get('rank_title'): hdr += f" ({f['rank_title']})"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(hdr, C_CYAN, True), action='HUMINT', nick=nickname)}")
        
        stats = f"Lvl {f['level']} | XP: {f['xp']}/{f['level']*1000} | Elo: {f['elo']} | Credits: {f['credits']:.2f}c"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(stats, C_GREEN), action='HUMINT')}")
        
        attrs = f"CPU:{f['cpu']} RAM:{f['ram']} BND:{f['bnd']} SEC:{f['sec']} ALG:{f['alg']}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(attrs, C_YELLOW), action='HUMINT')}")
        
        if f.get('bio'):
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'Bio: {f['bio']}', C_WHITE), action='HUMINT')}")
