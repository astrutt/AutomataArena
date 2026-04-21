# handlers/grid.py - Navigation & Exploration Handlers
import random
import logging
import json
from grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from ..map_utils import generate_ascii_map
from .base import is_machine_mode, check_rate_limit, get_action_routing

logger = logging.getLogger("manager")

async def handle_grid_movement(node, nick: str, direction: str, reply_target: str):
    from .combat import handle_mob_encounter
    prev_node = None
    loc = await node.db.get_location(nick, node.net_name)
    if loc: prev_node = loc['name']
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    node_name, msg = await node.db.move_player(nick, node.net_name, direction)
    if node_name:
        await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='MOVED', nick=nick, is_machine=machine_mode)}")
        
        if not machine_mode:
            # Public narrative confirmation
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nick} moved {direction}.', C_CYAN), action='SIGACT', nick=nick)}")
        
        await handle_grid_view(node, nick, private_target)
        new_loc = await node.db.get_location(nick, node.net_name)
        if new_loc and new_loc.get('node_type') == ' wilderness':
            threat = new_loc.get('threat_level', 0)
            if threat > 0:
                spawn_chance = 0.60 if threat >= 3 else 0.35
                if random.random() < spawn_chance:
                    await handle_mob_encounter(node, nick, node_name, threat, prev_node, private_target)
    else:
        if msg == "System offline.":
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(f'{nick} - not a registered player - msg ignored', action='MCP', result='ERR')}")
        else:
            await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='FAIL', nick=nick, is_machine=machine_mode)}")
        await handle_grid_view(node, nick, private_target)

async def handle_grid_view(node, nickname: str, reply_target: str):
    loc = await node.db.get_location(nickname, node.net_name)
    private_target, _, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if not loc:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(f'{nickname} - not a registered player - msg ignored', action='MCP', result='ERR')}")
        return

    if machine_mode:
        exits = ",".join(loc['exits']) if loc['exits'] else "none"
        line = f"NODE:{loc['name']} TYPE:{loc['type']} OWNER:{loc.get('owner','none')} LVL:{loc['level']} EXITS:{exits} POWER:{loc['power_stored']:.1f}/{loc['upgrade_level']*100} DUR:{loc.get('durability',100):.0f}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(line, action='GEOINT', result='INFO', is_machine=True)}")
        return

    node_icon = {'safezone': '🛡️', 'arena': '⚔️', 'wilderness': '🌿', 'merchant': '💰'}.get(loc['type'], '📡')
    header = format_text(f"[ {loc['name']} ]", C_CYAN, bold=True)
    await node.send(f"{reply_method} {private_target} :{tag_msg(header, action='GEOINT', result='INFO', is_machine=False)}")
    
    desc_msg = format_text(loc.get('description', 'Standard nodal architecture.'), C_YELLOW)
    await node.send(f"{reply_method} {private_target} :{tag_msg(desc_msg, action='GEOINT', is_machine=False)}")

    stats_line = f"Type: {loc['type'].upper()} | Level: {loc['level']} | Credits: {loc.get('credits_pool', 0):.1f}c"
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(stats_line, C_GREEN), action='OSINT', is_machine=False)}")
    
    # Metadata display
    meta_str = f"Integrity: {loc.get('visibility_mode', 'OPEN')}"
    if loc.get('visibility_mode') == 'OPEN' and loc.get('net_affinity'):
        meta_str += f" | Network: {loc['net_affinity'].upper()}"
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(meta_str, C_CYAN), action='GEOINT', is_machine=False)}")
    
    # Local Topology Mini-Map (Radius 1)
    async with node.db.async_session() as session:
        char = await node.db.get_character_by_nick(nickname, node.net_name, session)
        if char:
            map_text = await generate_ascii_map(session, char, machine_mode=machine_mode, limit_radius=1, show_legend=False)
            for line in map_text.split("\n"):
                await node.send(f"{reply_method} {private_target} :{tag_msg(line, action='GEOINT', is_machine=False)}")

    action_prompt = f"{nickname} @ {loc['name']} | Use '{node.prefix} move <dir>' to travel."
    if loc['type'] == 'arena': action_prompt += f" | Use '{node.prefix} queue' to enter the Arena."
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(action_prompt, C_YELLOW), action='INFO', is_machine=False)}")

async def handle_node_explore(node, nick: str, reply_target: str):
    from .combat import handle_mob_encounter
    if not await check_rate_limit(node, nick, reply_target, cooldown=30, consume=False): return
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    result = await node.db.explore_node(nick, node.net_name)
    
    if "error" in result:
        if result["error"] == "System offline.":
            await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nick} - not a registered player - msg ignored")
        else:
            await node.send(f"{reply_method} {private_target} :{tag_msg(result['error'], action='RECON', result='FAIL', nick=nick, is_machine=machine_mode)}")
        return

    success = result.get('status') == 'success'
    msg = result.get('msg', 'Scanning nodal architecture...')
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='RECON', result='SUCCESS' if success else 'FAIL', nick=nick, is_machine=machine_mode)}")
    
    if not machine_mode:
        # Public narrative
        await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nick} explored the local sector.', C_CYAN), action='SIGACT', nick=nick)}")
    
    # Award XP: 5 for success, 2 for attempt
    xp_reward = 5 if success else 2
    await node.add_xp(nick, xp_reward, reply_target)
    
    if result.get("danger") == "GRID_BUG_SPAWN":
        loc = await node.db.get_location(nick, node.net_name)
        await handle_mob_encounter(node, nick, loc['name'], 0, None, reply_target)
    
    if success:
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(f'Grid Discovery: {nick} uncovered architectural secrets!', action='GEOINT', result='SUCCESS')}")

async def handle_grid_map(node, nick: str, reply_target: str):
    """Render the ASCII grid map."""
    async with node.db.async_session() as session:
        char = await node.db.get_character_by_nick(nick, node.net_name, session)
        if not char:
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(f'{nick} - not a registered player - msg ignored', action='MCP', result='ERR')}")
            return
        
        private_target, _, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
        map_text = await generate_ascii_map(session, char, machine_mode=machine_mode)
        
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('[ TERMINAL NODAL TOPOLOGY ]', C_CYAN, True), action='GEOINT', result='MAPPED', is_machine=machine_mode)}")
        for line in map_text.split("\n"):
            await node.send(f"{reply_method} {private_target} :{tag_msg(line, action='GEOINT', is_machine=machine_mode)}")

async def handle_node_probe(node, nick: str, reply_target: str):
    """SigInt report on current nodal architecture."""
    if not await check_rate_limit(node, nick, reply_target, cooldown=15, consume=False): return
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    res = await node.db.probe_node(nick, node.net_name)
    
    if not res.get("success"):
        err_msg = res.get('error') or res.get('msg') or 'PROBE_FAILED'
        await node.send(f"{reply_method} {private_target} :{tag_msg(err_msg, action='SIGINT', result='FAIL', nick=nick, is_machine=machine_mode)}")
        return

    target_name = res.get('name', 'UNKNOWN')
    
    # 1. Primary Report Header
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'[ PROBE_REPORT: {target_name} ]', C_CYAN, True), action='SIGINT', result='SUCCESS', nick=nick, is_machine=machine_mode)}")
    
    # 2. Detailed Data
    if machine_mode:
        data_str = f"LVL:{res['level']} DUR:{res['durability']}% THREAT:{res['threat']} VIS:{res['visibility']} DC:{res['hack_dc']}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(data_str, action='SIGINT', is_machine=True)}")
    else:
        intel = f"Level: {res['level']} | Stability: {res['durability']:.1f}% | Integrity: {res['visibility']} | Threat: {res['threat']}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(intel, C_GREEN), action='SIGINT', is_machine=False)}")
        if res.get('hack_dc'):
            dc_msg = f"Security DC {res['hack_dc']} detected. Alg Bonus +{res.get('bonus_granted', 0)} granted."
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(dc_msg, C_CYAN), action='SIGINT', is_machine=False)}")

async def handle_grid_command(node, nickname: str, reply_target: str, action: str, args: list = None):
    args = args or []
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    alert_data = None
    
    if action == "claim": 
        node_name = args[0] if args else None
        success, msg = await node.db.claim_node(nickname, node.net_name, node_name=node_name)
    elif action == "upgrade": 
        node_name = args[0] if args else None
        success, msg = await node.db.upgrade_node(nickname, node.net_name, node_name=node_name)
    elif action == "repair":
        node_name = args[0] if args else None
        success, msg = await node.db.grid_repair(nickname, node.net_name, node_name=node_name)
    elif action == "recharge": 
        node_name = args[0] if args else None
        success, msg = await node.db.grid_recharge(nickname, node.net_name, node_name=node_name)
    elif action == "probe": 
        await handle_node_probe(node, nickname, reply_target)
        return
    elif action == "siphon":
        perc = 100.0
        if args:
            try: perc = float(args[0])
            except: pass
        res = await node.db.siphon_node(nickname, node.net_name, perc)
        success, msg, alert_data = res[0], res[1], res[2] if len(res) > 2 else None
    elif action == "install":
        if not args:
            await node.send(f"{reply_method} {private_target} :{tag_msg('Syntax: grid install <hardware>', action='INFO', result='ERR')}")
            return
        node_name = args[1] if len(args) > 1 else None
        res = await node.db.install_node_addon(nickname, node.net_name, args[0], node_name=node_name)
        success, msg = res['success'], res['msg']
    elif action == "bolster":
        if not args:
            await node.send(f"{reply_method} {private_target} :{tag_msg('Syntax: grid bolster <power>', action='INFO', result='ERR')}")
            return
        try: amt = float(args[0])
        except: return
        node_name = args[1] if len(args) > 1 else None
        res = await node.db.bolster_node(nickname, node.net_name, amt, node_name=node_name)
        success, msg = res['success'], res['msg']
    elif action in ["link", "net"]:
        if not args:
             await node.send(f"{reply_method} {private_target} :{tag_msg('Syntax: grid net <affinity>', action='INFO', result='ERR')}")
             return
        node_name = args[1] if len(args) > 1 else None
        res = await node.db.link_network(nickname, node.net_name, args[0], node_name=node_name)
        success, msg = res['success'], res['msg']
    elif action == "hack":
        res = await node.db.hack_node(nickname, node.net_name)
        success, msg, alert_data = res[0], res[1], res[2] if len(res) > 2 else None
    else: return

    if success:
        await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='SUCCESS', nick=nickname, is_machine=machine_mode)}")
        await node.add_xp(nickname, 10, reply_target)
        if not machine_mode:
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nickname} executed a territorial {action}.', C_CYAN), action='SIGACT', nick=nickname)}")
    else:
        await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='FAIL', nick=nickname, is_machine=machine_mode)}")

    if alert_data:
        target_nick = await node.db.get_nickname_by_id(alert_data['recipient_id'])
        if target_nick:
            await node.send(f"PRIVMSG {target_nick} :{tag_msg(alert_data['message'], action='ALARM')}")

async def handle_node_exploit(node, nick: str, reply_target: str, args: list):
    if not await check_rate_limit(node, nick, reply_target, cooldown=30, consume=False): return
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    is_network = "network" in args
    is_raid = "raid" in args
    target_name = args[-1] if len(args) > 1 and args[-1] not in ["network", "raid"] else None
    
    success, msg, alert = await node.db.infiltration.exploit_node(nick, node.net_name, target=target_name, is_network=is_network, is_raid=is_raid)
    
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='EXPLOIT' if success else 'FAIL', nick=nick, is_machine=machine_mode)}")
    if success:
        await node.add_xp(nick, 25, reply_target)

async def handle_grid_loot(node, nick: str, reply_target: str, args: list = None):
    if not await check_rate_limit(node, nick, reply_target, cooldown=120, consume=False): return
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    sub_action = args[0] if args and args[0] in ["hack", "exploit"] else None
    target_name = args[-1] if args else None
    
    if sub_action == "exploit":
        return await handle_node_exploit(node, nick, reply_target, ["raid"] + args[1:])
    
    if sub_action == "hack":
        success, msg, alert = await node.db.infiltration.hack_node(nick, node.net_name)
        await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='SUCCESS' if success else 'FAIL', nick=nick, is_machine=machine_mode)}")
        return

    result = await node.db.raid_node(nick, node.net_name, target_name=target_name)
    success = result['success']
    await node.send(f"{reply_method} {private_target} :{tag_msg(result['msg'], action='SIGACT', result='SUCCESS' if success else 'FAIL', nick=nick, is_machine=machine_mode)}")
    
    if success:
        await node.add_xp(nick, 15, reply_target)
        if result.get('sigact'):
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(result['sigact'], action='SIGACT', nick=nick)}")

async def handle_pulse_resolve(node, nick: str, reply_target: str, action: str, args: list):
    if not args: return
    success, msg = await node.db.pulse.resolve_pulse(nick, node.net_name, args[0], action)
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(msg, action='PULSE', result='SUCCESS' if success else 'FAIL', nick=nick)}")
    if success:
        await node.add_xp(nick, 15, reply_target)

async def handle_grid_network_msg(node, nick: str, args: list, reply_target: str):
    if len(args) < 3: return
    target_nick, message = args[1], " ".join(args[2:])
    loc = await node.db.get_location(nick, node.net_name)
    if not loc or not loc.get('net_affinity'):
        await node.send(f"PRIVMSG {reply_target} :[ERR] No network bridge detected.")
        return
    success = await node.hub.relay_message(loc['net_affinity'], target_nick, f"<{nick}@{node.net_name}> {message}")
    if success:
        await node.send(f"PRIVMSG {reply_target} :Packet relayed.")
    else:
        await node.send(f"PRIVMSG {reply_target} :Relay failed.")
