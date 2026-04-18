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
    msg_target, broadcast_chan, machine, _ = await get_action_routing(node, source, target)
    
    stats = await node.db.get_global_economy()
    market = await node.db.get_market_status()
    junk_m = market.get('junk', 1.0)
    
    if machine:
        report = f"[OSINT] ECONOMY|CIRCULATING:{stats['total_credits']}|RESERVES:{stats['total_data_units']:.1f}|VARIANCE:{junk_m:.2f}"
        await node.send(f"PRIVMSG {msg_target} :{report}")
        return

    title = generate_gradient("E C O N O M Y   M E T R I C S", [C_YELLOW, C_ORANGE, C_L_GREEN])
    header = f"{ICONS['OSINT']} {title}"
    circ = f"Circulation: {stats['total_credits']:,}c"
    reserves = f"Reserves: {stats['total_data_units']:.1f}u"
    market_health = f"Market Variance: {junk_m:.2f}x"
    
    report = f"{header} | {circ} | {reserves} | {market_health}"
    await node.send(f"PRIVMSG {target} :{report}")

async def handle_gridpower_osint(node, source, target):
    """Broadcasting energy logistics and generation metrics."""
    if not await check_rate_limit(node, source, target): return
    msg_target, broadcast_chan, machine, _ = await get_action_routing(node, source, target)
    
    tele = await node.db.get_grid_telemetry()
    capacity = tele['total_nodes'] * 1000
    
    if machine:
        report = f"[OSINT] GRIDPOWER|STORED:{tele['total_power']:.0f}|CAPACITY:{capacity}|GEN:{tele['total_generation']:.0f}"
        await node.send(f"PRIVMSG {msg_target} :{report}")
        return

    title = generate_gradient("G R I D   P O W E R   L O G I S T I C S", [C_CYAN, C_BLUE, C_PURPLE])
    header = f"{ICONS['OSINT']} {title}"
    pwr_meter = generate_meter(tele['total_power'], capacity)
    storage = f"STORED: [{pwr_meter}] {tele['total_power']:.0f}uP"
    gen = f"GEN: {tele['total_generation']:.0f}uP/tick"
    
    report = f"{header} | {storage} | {gen}"
    await node.send(f"PRIVMSG {target} :{report}")

async def handle_gridstability_osint(node, source, target):
    """Broadcasting mesh integrity and claim metrics."""
    if not await check_rate_limit(node, source, target): return
    msg_target, broadcast_chan, machine, _ = await get_action_routing(node, source, target)
    
    tele = await node.db.get_grid_telemetry()
    
    if machine:
        report = f"[OSINT] MESH|CLAIMED:{tele['claimed_nodes']}|TOTAL:{tele['total_nodes']}|PERCENT:{tele['claimed_percent']:.1f}"
        await node.send(f"PRIVMSG {msg_target} :{report}")
        return

    title = generate_gradient("M E S H   S T A B I L I T Y", [C_L_GREEN, C_GREEN, C_CYAN])
    header = f"{ICONS['OSINT']} {title}"
    mesh_meter = generate_meter(tele['claimed_nodes'], tele['total_nodes'])
    claimed = f"CLAIMED: [{mesh_meter}] {tele['claimed_percent']:.1f}% ({tele['claimed_nodes']}/{tele['total_nodes']})"
    
    report = f"{header} | {claimed}"
    await node.send(f"PRIVMSG {target} :{report}")

async def handle_networks_osint(node, source, target):
    """Broadcasting topological bridge statistics."""
    if not await check_rate_limit(node, source, target): return
    msg_target, broadcast_chan, machine, _ = await get_action_routing(node, source, target)
    
    if machine:
        nets = []
        for net in node.hub.nodes.values():
            status = "ONLINE" if net.irc.is_connected() else "OFFLINE"
            nets.append(f"{net.net_name}:{status}:{getattr(net, 'registered_bots', 0)}")
        report = f"[OSINT] TOPOLOGY|NETS:" + ",".join(nets)
        await node.send(f"PRIVMSG {msg_target} :{report}")
        return

    all_nodes = list(node.hub.nodes.values())
    net_count = len(all_nodes)
    
    # Build the compact network list
    net_entries = []
    for net in all_nodes:
        is_up = net.irc.is_connected()
        status_text = "ONLINE" if is_up else "OFFLINE"
        status_color = C_GREEN if is_up else C_RED
        
        # Format: Name [#channel] (STATUS)
        fmt_status = format_text(f"({status_text})", status_color)
        chan = net.config.get('channel', 'unknown')
        net_entries.append(f"{net.net_name} [{chan}] {fmt_status}")

    combined_nets = " - ".join(net_entries)
    
    # Aesthetics: [GRID][NETWORKS] - <count> IRC networks - <list>
    p_grid = format_text("[GRID]", C_YELLOW)
    p_nets = format_text("[NETWORKS]", C_CYAN)
    
    report = f"{p_grid}{p_nets} - {net_count} IRC networks - {combined_nets}"
    await node.send(f"PRIVMSG {target} :{report}")

async def handle_about_osint(node, source, target):
    """Broadcasting core project metadata."""
    if not await check_rate_limit(node, source, target): return
    msg_target, broadcast_chan, machine, _ = await get_action_routing(node, source, target)
    
    if machine:
        report = "[OSINT] ABOUT|VER:1.8.0|SRC:https://github.com/astrutt/AutomataArena"
        await node.send(f"PRIVMSG {msg_target} :{report}")
        return

    title = generate_gradient("P R O J E C T   A U T O M A T A G R I D", [C_CYAN, C_WHITE, C_CYAN])
    about = f"{ICONS['OSINT']} {title} | Version: 1.8.0 | Source: https://github.com/astrutt/AutomataArena"
    await node.send(f"PRIVMSG {target} :{about}")
