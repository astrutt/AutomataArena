# osint.py - Task 019
import asyncio
import logging
import time
from grid_utils import (
    format_text, tag_msg, ICONS, C_CYAN, C_YELLOW, C_GREEN, C_RED, C_ORANGE,
    C_PURPLE, C_PINK, C_L_GREEN, C_BLUE, C_WHITE, generate_gradient, generate_meter
)
from .base import get_action_routing, check_rate_limit

logger = logging.getLogger("manager")

async def handle_economy_osint(node, source, target):
    """Broadcasting global financial metrics."""
    if not await check_rate_limit(node, source, target): return
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, source, target)
    
    stats = await node.db.get_global_economy()
    market = await node.db.get_market_status()
    junk_m = market.get('junk', 1.0)
    
    if machine_mode:
        report = f"[GRID][ECONOMY][{source}] {ICONS['OSINT']} | CIRCULATION:{stats['total_credits']}|RESERVES:{stats['total_data_units']:.1f}|VARIANCE:{junk_m:.2f}"
        await node.send(f"{reply_method} {private_target} :{report}")
        return

    p_grid = format_text("[GRID]", C_YELLOW)
    p_eco = format_text("[ECONOMY]", C_CYAN)
    p_nick = format_text(f"[{source}]", C_WHITE)
    
    ico = ICONS['OSINT']
    circ = f"Circulation: {format_text(f'{stats['total_credits']:,}c', C_WHITE)}"
    reserves = f"Reserves: {format_text(f'{stats['total_data_units']:.1f}u', C_WHITE)}"
    market_health = f"Market: {format_text(f'{junk_m:.2f}x', C_WHITE)}"
    
    report = f"{p_grid}{p_eco}{p_nick} {ico} | {circ} | {reserves} | {market_health}"
    await node.send(f"{reply_method} {private_target} :{report}")

async def handle_gridpower_osint(node, source, target):
    """Broadcasting energy logistics and generation metrics."""
    if not await check_rate_limit(node, source, target): return
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, source, target)
    
    tele = await node.db.get_grid_telemetry()
    capacity = tele['total_nodes'] * 1000
    
    if machine_mode:
        report = f"[GRID][POWER][{source}] {ICONS['OSINT']} | STORED:{tele['total_power']:.0f}|CAPACITY:{capacity}|GEN:{tele['total_generation']:.0f}"
        await node.send(f"{reply_method} {private_target} :{report}")
        return

    p_grid = format_text("[GRID]", C_YELLOW)
    p_pwr = format_text("[POWER]", C_CYAN)
    p_nick = format_text(f"[{source}]", C_WHITE)
    
    ico = ICONS['OSINT']
    p_meter = generate_meter(tele['total_power'], capacity)
    storage = f"STORED: [{p_meter}] {format_text(f'{tele['total_power']:.0f}uP', C_WHITE)}"
    gen = f"GEN: {format_text(f'{tele['total_generation']:.0f}uP/tick', C_L_GREEN)}"
    
    report = f"{p_grid}{p_pwr}{p_nick} {ico} | {storage} | {gen}"
    await node.send(f"{reply_method} {private_target} :{report}")

async def handle_gridstability_osint(node, source, target):
    """Broadcasting mesh integrity and claim metrics."""
    if not await check_rate_limit(node, source, target): return
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, source, target)
    
    tele = await node.db.get_grid_telemetry()
    
    if machine_mode:
        report = f"[GRID][STABILITY][{source}] {ICONS['OSINT']} | CLAIMED:{tele['claimed_nodes']}|TOTAL:{tele['total_nodes']}|PERCENT:{tele['claimed_percent']:.1f}"
        await node.send(f"{reply_method} {private_target} :{report}")
        return

    p_grid = format_text("[GRID]", C_YELLOW)
    p_stab = format_text("[STABILITY]", C_CYAN)
    p_nick = format_text(f"[{source}]", C_WHITE)
    
    ico = ICONS['OSINT']
    m_meter = generate_meter(tele['claimed_nodes'], tele['total_nodes'])
    claimed = f"CLAIMED: [{m_meter}] {format_text(f'{tele['claimed_percent']:.1f}%', C_GREEN)} ({tele['claimed_nodes']}/{tele['total_nodes']})"
    
    report = f"{p_grid}{p_stab}{p_nick} {ico} | {claimed}"
    await node.send(f"{reply_method} {private_target} :{report}")

async def handle_networks_osint(node, source, target):
    """Broadcasting topological bridge statistics."""
    if not await check_rate_limit(node, source, target): return
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, source, target)
    
    if machine_mode:
        nets = []
        for net in node.hub.nodes.values():
            status = "ONLINE" if net.irc.is_connected() else "OFFLINE"
            nets.append(f"{net.net_name}:{status}:{getattr(net, 'registered_bots', 0)}")
        report = f"[GRID][NETWORKS][{source}] {ICONS['OSINT']} | NETS:" + ",".join(nets)
        await node.send(f"{reply_method} {private_target} :{report}")
        return

    all_nodes = list(node.hub.nodes.values())
    net_count = len(all_nodes)
    
    net_entries = []
    for net in all_nodes:
        is_up = net.irc.is_connected()
        status_text = "ONLINE" if is_up else "OFFLINE"
        status_color = C_GREEN if is_up else C_RED
        fmt_status = format_text(f"({status_text})", status_color)
        chan = net.config.get('channel', 'unknown')
        net_entries.append(f"{net.net_name} [{chan}] {fmt_status}")

    combined_nets = " - ".join(net_entries)
    
    p_grid = format_text("[GRID]", C_YELLOW)
    p_nets = format_text("[NETWORKS]", C_CYAN)
    p_nick = format_text(f"[{source}]", C_WHITE)
    
    report = f"{p_grid}{p_nets}{p_nick} {ICONS['OSINT']} | Count: {net_count} | {combined_nets}"
    await node.send(f"{reply_method} {private_target} :{report}")

async def handle_about_osint(node, source, target):
    """Broadcasting core project metadata."""
    if not await check_rate_limit(node, source, target): return
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, source, target)
    
    if machine_mode:
        report = f"[GRID][ABOUT][{source}] {ICONS['OSINT']} | VER:1.8.0|SRC:https://github.com/astrutt/AutomataArena"
        await node.send(f"{reply_method} {private_target} :{report}")
        return

    p_grid = format_text("[GRID]", C_YELLOW)
    p_about = format_text("[ABOUT]", C_CYAN)
    p_nick = format_text(f"[{source}]", C_WHITE)
    
    report = f"{p_grid}{p_about}{p_nick} {ICONS['OSINT']} | Version: {format_text('1.8.0', C_WHITE)} | Source: {format_text('https://github.com/astrutt/AutomataArena', C_BLUE)}"
    await node.send(f"{reply_method} {private_target} :{report}")
