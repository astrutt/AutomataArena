# handlers/grid.py - Navigation & Exploration Handlers
import random
import logging
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
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(msg, C_GREEN), tags=['SIGACT', nick])}")
        
        if machine_mode:
            # Public narrative confirmation
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nick} moved {direction}.', C_CYAN), tags=['SIGACT', nick])}")
        
        await handle_grid_view(node, nick, private_target)
        new_loc = await node.db.get_location(nick, node.net_name)
        if new_loc and new_loc.get('node_type') == 'wilderness':
            threat = new_loc.get('threat_level', 0)
            if threat > 0:
                spawn_chance = 0.60 if threat >= 3 else 0.35
                if random.random() < spawn_chance:
                    await handle_mob_encounter(node, nick, node_name, threat, prev_node, private_target)
    else:
        if msg == "System offline.":
            await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nick} - not a registered player - msg ignored")
        else:
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(msg, C_RED), tags=['SIGACT', nick])}")
        await handle_grid_view(node, nick, private_target)

async def handle_grid_view(node, nickname: str, reply_target: str):
    loc = await node.db.get_location(nickname, node.net_name)
    
    private_target, _, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if not loc:
        await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nickname} - not a registered player - msg ignored")
        return
    if machine_mode:
        exits = ",".join(loc['exits']) if loc['exits'] else "none"
        line = f"NODE:{loc['name']} TYPE:{loc['type']} OWNER:{loc.get('owner','none')} LVL:{loc['level']} EXITS:{exits} POWER:{loc['power_stored']}/{loc['upgrade_level']*100} DUR:{loc.get('durability',100):.0f}"
        await node.send(f"{reply_method} {private_target} :[GRID] {line}")
        return
    node_icon = {'safezone': '🛡️', 'arena': '⚔️', 'wilderness': '🌿', 'merchant': '💰'}.get(loc['type'], '📡')
    exits_str = " | ".join(loc['exits']) if loc['exits'] else "none"
    header = f"{node_icon} " + format_text(f"[ {loc['name']} ]", C_CYAN, bold=True)
    await node.send(f"{reply_method} {private_target} :{tag_msg(header, tags=['GEOINT'], location=loc['name'], is_machine=machine_mode)}")
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(loc['description'], C_YELLOW), tags=['GEOINT'], location=loc['name'], is_machine=machine_mode)}")
    node_stats = f"Type: {loc['type'].upper()} | Level: {loc['level']} | Credits: {loc['credits']}c"
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(node_stats, C_GREEN), tags=['GEOINT'], location=loc['name'], is_machine=machine_mode)}")
    
    # Phase 3: Metadata display
    meta_str = f"Integrity: {loc.get('visibility_mode', 'OPEN')}"
    if loc.get('visibility_mode') == 'OPEN' and loc.get('net_affinity'):
        meta_str += f" | Network: {loc['net_affinity'].upper()}"
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(meta_str, C_CYAN), tags=['GEOINT'], is_machine=machine_mode)}")
    
    # Local Topology Mini-Map (Radius 1)
    async with node.db.async_session() as session:
        char = await node.db.get_character_by_nick(nickname, node.net_name, session)
        if char:
            map_text = await generate_ascii_map(session, char, machine_mode=machine_mode, limit_radius=1, show_legend=False)
            for line in map_text.split("\n"):
                await node.send(f"{reply_method} {private_target} :{tag_msg(line, tags=['GEOINT'], is_machine=machine_mode)}")

    action_prompt = format_text(f"{nickname} @ {loc['name']} | Use '{node.prefix} move <dir>' to travel.", C_YELLOW)
    if loc['type'] == 'arena': action_prompt += format_text(f" | Use '{node.prefix} queue' to enter the Arena.", C_GREEN)
    await node.send(f"{reply_method} {private_target} :{tag_msg(action_prompt, tags=['GEOINT'], is_machine=machine_mode)}")

async def handle_node_explore(node, nick: str, reply_target: str):
    from .combat import handle_mob_encounter
    if not await check_rate_limit(node, nick, reply_target, cooldown=45): return
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    result = await node.db.explore_node(nick, node.net_name)
    
    if "error" in result:
        if result["error"] == "System offline.":
            await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nick} - not a registered player - msg ignored")
        else:
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(result['error'], C_RED), tags=['ERR', nick])}")
        return

    banner = format_text(result.get('msg', 'Scanning nodal architecture...'), C_GREEN if result.get('status') == 'success' else C_YELLOW)
    loc = await node.db.get_location(nick, node.net_name)
    loc_name = loc['name'] if loc else None
    await node.send(f"{reply_method} {private_target} :{tag_msg(banner, tags=['GEOINT', nick], location=loc_name)}")
    
    if machine_mode:
        # Public narrative
        await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nick} explored the local sector.', C_CYAN), tags=['SIGACT', nick])}")
    
    # Award XP: 5 for success, 2 for attempt
    xp_reward = 5 if result.get('status') == 'success' else 2
    await node.add_xp(nick, xp_reward, reply_target)
    
    if result.get("danger") == "GRID_BUG_SPAWN":
        # Manually trigger a mob encounter with a Level 0 Grid Bug
        loc = await node.db.get_location(nick, node.net_name)
        await handle_mob_encounter(node, nick, loc['name'], 0, None, reply_target)
    
    if result['status'] == 'success':
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(f'Grid Discovery: {nick} uncovered architectural secrets!', C_CYAN), tags=['SIGACT', 'GEOINT'], location=loc_name)}")

async def handle_grid_map(node, nick: str, reply_target: str):
    """Render the ASCII grid map."""
    async with node.db.async_session() as session:
        # Get character for stats
        char = await node.db.get_character_by_nick(nick, node.net_name, session)
        if not char:
            await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nick} - not a registered player - msg ignored")
            return
        
        machine_mode, reply_method = await is_machine_mode(node, nick), (await node.db.get_prefs(nick, node.net_name)).get('msg_type', 'privmsg').upper()
        map_text = await generate_ascii_map(session, char, machine_mode=machine_mode)
        
        await node.send(f"{reply_method} {reply_target} :{tag_msg(format_text('[ TERMINAL NODAL TOPOLOGY ]', C_CYAN, True), tags=['GEOINT'], is_machine=machine_mode)}")
        for line in map_text.split("\n"):
            await node.send(f"{reply_method} {reply_target} :{tag_msg(line, tags=['GEOINT'], is_machine=machine_mode)}")

async def handle_node_probe(node, nick: str, reply_target: str):
    """SigInt report on current nodal architecture."""
    if not await check_rate_limit(node, nick, reply_target, cooldown=15): return
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    result = await node.db.probe_node(nick, node.net_name)
    if not result.get("success") or "error" in result:
        err_msg = result.get('error') or result.get('msg') or 'PROBE_FAILED'
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(err_msg, C_RED), tags=['SIGINT', nick])}")
        return

    if machine_mode:
        addons = ",".join(result['addons']) if result['addons'] else "none"
        occupants = ",".join(result['occupants']) if result['occupants'] else "none"
        line = f"PROBE:{result['name']} LVL:{result['level']} DUR:{result['durability']:.1f}% THREAT:{result['threat']} ADDONS:[{addons}] OCCUPANTS:[{occupants}]"
        await node.send(f"{reply_method} {private_target} :[SIGINT] {line}")
        
        # Public narrative
        await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nick} performed a deep architectural probe.', C_CYAN), tags=['SIGACT', nick])}")
        return

    # User Output
    node_name = result.get('name', 'UNKNOWN_NODE')
    header = format_text(f"[ SIGINT SCAN: {node_name} ]", C_CYAN, True)
    await node.send(f"{reply_method} {private_target} :{tag_msg(header, tags=['SIGINT'], location=result['name'])}")
    
    stats = f"Level: {result['level']} | Stability: {result['durability']:.1f}% | Integrity: {result['visibility']} | Threat: {result['threat']}"
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(stats, C_GREEN), tags=['SIGINT'])}")
    
    # Reveal Hack DC and Bonus
    if result.get('hack_dc'):
        intel = f"INTELLIGENCE: Security DC {result['hack_dc']} detected. Alg Bonus +{result['bonus_granted']} applied to local buffer."
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(intel, C_CYAN), tags=['SIGINT'])}")

    if result['addons']:
        addon_str = " | ".join([f"[{a}]" for a in result['addons']])
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'Hardware detected: {addon_str}', C_YELLOW), tags=['SIGINT'])}")
    
    if result['occupants']:
        occ_str = " | ".join(result['occupants'])
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(f'Active Occupants: {occ_str}', C_RED), tags=['SIGINT'])}")
    else:
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('Sector appears deserted.', C_WHITE), tags=['SIGINT'])}")

async def handle_grid_command(node, nickname: str, reply_target: str, action: str, args: list = None):
    args = args or []
    alert_data = None
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if action == "claim": success, msg = await node.db.claim_node(nickname, node.net_name)
    elif action == "upgrade": success, msg = await node.db.upgrade_node(nickname, node.net_name)
    elif action == "repair": success, msg = await node.db.grid_repair(nickname, node.net_name)
    elif action == "recharge": success, msg = await node.db.grid_recharge(nickname, node.net_name)
    elif action == "probe": 
        await handle_node_probe(node, nickname, reply_target)
        return
    elif action == "siphon":
        percent = 100.0
        if len(args) > 0:
            try: percent = float(args[0])
            except: pass
        res = await node.db.siphon_node(nickname, node.net_name, percent)
        success, msg = res[0], res[1]
        if len(res) > 2: alert_data = res[2]
    elif action == "install":
        if not args:
            await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} grid install <hardware_name>")
            return
        result = await node.db.install_node_addon(nickname, node.net_name, args[0])
        success, msg = result['success'], result['msg']
    elif action == "bolster":
        if not args:
            await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} grid bolster <power_amount>")
            return
        try: amount = float(args[0])
        except: 
            await node.send(f"PRIVMSG {reply_target} :[ERR] Invalid amount.")
            return
        result = await node.db.bolster_node(nickname, node.net_name, amount)
        success, msg = result['success'], result['msg']
    elif action in ["link", "net"]:
        if not args:
            await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} grid net <local_network_name>")
            return
        result = await node.db.link_network(nickname, node.net_name, args[0])
        success, msg = result['success'], result['msg']
    elif action == "hack":
        res = await node.db.hack_node(nickname, node.net_name)
        success, msg = res[0], res[1]
        if len(res) > 2: alert_data = res[2]
        if not success and msg == "PVE_GUARDIAN_SPAWN":
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('[WARNING] Primary MCP activated. PvE Guardian routine detected.', C_RED), tags=['SIGACT', nickname])}")
            return
    else:
        return # Unknown activity

    if not success and msg == "System offline.":
        await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nickname} - not a registered player - msg ignored")
        return
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(msg, C_GREEN if success else C_RED), tags=['SIGACT', nickname])}")
    
    if success and action in ["claim", "upgrade", "hack", "repair", "install", "net"]:
        if machine_mode:
            # Public narrative
            narratives = {
                "claim": "established authority over local node.",
                "upgrade": "fortified nodal hardware.",
                "hack": "sabotaged rival architecture.",
                "repair": "performed architectural maintenance.",
                "install": "deployed hardware enhancements.",
                "net": "bridged nodal networks."
            }
            narrative = narratives.get(action, f"executed a territorial {action}!")
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nickname} {narrative}', C_CYAN), tags=['SIGACT', nickname])}")
        
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(f'Grid Alert: {nickname} executed a territorial {action}!', C_YELLOW), tags=['SIGACT'])}")
        
        # Award XP for successful Grid actions
        xp_map = {"claim": 25, "upgrade": 15, "hack": 10, "repair": 5, "install": 10, "link": 10, "net": 10, "siphon": 5}
        if action in xp_map:
            await node.add_xp(nickname, xp_map[action], reply_target)

    # Tactical Alert Delegation for Siphon & Hack
    if action in ["siphon", "hack"] and alert_data:
        prefs = await node.db.get_prefs_by_id(alert_data['recipient_id'])
        if prefs.get("briefings_enabled", True):
            if prefs.get("memo_target") == "irc":
                await node.hub.send_memo(node.net_name, alert_data['recipient_id'], alert_data['message'])
            else:
                target_nick = await node.db.get_nickname_by_id(alert_data['recipient_id'])
                if target_nick and target_nick.lower() in node.channel_users:
                    await node.send(f"PRIVMSG {target_nick} :[ALERT] {alert_data['message']}")

async def handle_grid_loot(node, nick: str, reply_target: str):
    if not await check_rate_limit(node, nick, reply_target, cooldown=60): return
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    result = await node.db.raid_node(nick, node.net_name)
    
    if not result['success'] and result['msg'] == "System offline.":
        await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nick} - not a registered player - msg ignored")
        return
    banner = format_text(result['msg'], C_GREEN if result['success'] else C_RED)
    await node.send(f"{reply_method} {private_target} :{tag_msg(banner, tags=['SIGACT', nick])}")
    
    if result['success']:
        if machine_mode:
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nick} initiated a rapid resource raid.', C_CYAN), tags=['SIGACT', nick])}")
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(result['sigact'], C_YELLOW, True), tags=['SIGACT'])}")
        await node.add_xp(nick, 10, reply_target)
        
        # Tactical Alert Delegation
        if result.get("alert"):
            alert = result['alert']
            prefs = await node.db.get_prefs_by_id(alert['recipient_id'])
            if prefs.get("briefings_enabled", True): # Only notify if briefings are ON
                if prefs.get("memo_target") == "irc":
                    await node.hub.send_memo(node.net_name, alert['recipient_id'], alert['message'])
                else:
                    # In-grid alerts are already in the DB as Memo objects
                    # We might want to send a live NOTICE to the victim if they are online
                    target_nick = await node.db.get_nickname_by_id(alert['recipient_id'])
                    if target_nick and target_nick.lower() in node.channel_users:
                        await node.send(f"PRIVMSG {target_nick} :[ALERT] {alert['message']}")

async def handle_pulse_resolve(node, nick: str, reply_target: str, action: str, args: list):
    """Handle the resolution of interactive Pulsar events (!a collect/patch)."""
    if not args:
        await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} {action} <node_name>")
        return
        
    node_name = args[0]
    success, msg = await node.db.pulse.resolve_pulse(nick, node.net_name, node_name, action)
    
    color = C_GREEN if success else C_RED
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(msg, color), tags=['PULSE', nick])}")
    
    if success:
        await node.add_xp(nick, 15, reply_target) # Bonus XP for interactive events
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(f'{nick} successfully resolved a localized pulse at {node_name}!', C_CYAN), tags=['SIGACT'])}")

async def handle_grid_network_msg(node, nick: str, args: list, reply_target: str):
    if len(args) < 3:
        await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} grid network msg <nick> <msg>")
        return
        
    target_nick = args[1]
    message = " ".join(args[2:])
    
    loc = await node.db.get_location(nick, node.net_name)
    if not loc or not loc.get('net_affinity'):
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('System Error: This node lacks a synchronized IRC bridge.', C_RED), tags=['SIGINT', nick])}")
        return
        
    target_net = loc['net_affinity']
    # Format the message to include the sender's origin
    formatted_msg = format_text(f"[CROSS-GRID] <{nick}@{node.net_name}> {message}", C_CYAN)
    
    success = await node.hub.relay_message(target_net, target_nick, formatted_msg)
    if success:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'Packet successfully relayed to {target_net} node.', C_GREEN), tags=['SIGINT', nick])}")
    else:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'Packet transmission failed: Network {target_net} is currently unreachable.', C_RED), tags=['SIGINT', nick])}")

async def handle_grid_claimed(node, nickname: str, args: list, reply_target: str):
    target = args[1] if len(args) > 1 else nickname
    count = await node.db.grid.get_claimed_nodes(target, node.net_name)
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    if machine_mode:
        await node.send(f"{reply_method} {private_target} :[GRID] CLAIMED_NODES:{count} TARGET:{target}")
    else:
        msg = f"Territorial Audit: {target} currently controls {count} Grid Nodes."
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(msg, C_CYAN), tags=['GEOINT'], location=target, is_machine=machine_mode)}")
