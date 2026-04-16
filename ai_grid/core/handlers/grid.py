# handlers/grid.py - Navigation & Exploration Handlers
import random
import logging
from grid_utils import format_text, build_banner, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from ..map_utils import generate_ascii_map
from .base import is_machine_mode, check_rate_limit

logger = logging.getLogger("manager")

async def handle_grid_movement(node, nick: str, direction: str, reply_target: str):
    from .combat import handle_mob_encounter
    prev_node = None
    loc = await node.db.get_location(nick, node.net_name)
    if loc: prev_node = loc['name']
    node_name, msg = await node.db.move_fighter(nick, node.net_name, direction)
    if node_name:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[GRID] {msg}', C_GREEN))}")
        await handle_grid_view(node, nick, reply_target)
        new_loc = await node.db.get_location(nick, node.net_name)
        if new_loc and new_loc.get('node_type') == 'wilderness':
            threat = new_loc.get('threat_level', 0)
            if threat > 0:
                spawn_chance = 0.60 if threat >= 3 else 0.35
                if random.random() < spawn_chance:
                    await handle_mob_encounter(node, nick, node_name, threat, prev_node, reply_target)
    else:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[ERR] {msg}', C_RED))}")
        await handle_grid_view(node, nick, reply_target)

async def handle_grid_view(node, nickname: str, reply_target: str):
    loc = await node.db.get_location(nickname, node.net_name)
    if not loc:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Fighter not found.")
        return
    machine = await is_machine_mode(node, nickname)
    if machine:
        exits = ",".join(loc['exits']) if loc['exits'] else "none"
        line = f"NODE:{loc['name']} TYPE:{loc['type']} OWNER:{loc.get('owner','none')} LVL:{loc['level']} EXITS:{exits} POWER:{loc['power_stored']}/{loc['upgrade_level']*100} DUR:{loc.get('durability',100):.0f}"
        await node.send(f"PRIVMSG {nickname} :[GRID] {line}")
        return
    node_icon = {'safezone': '🛡️', 'arena': '⚔️', 'wilderness': '🌿', 'merchant': '💰'}.get(loc['type'], '📡')
    exits_str = " | ".join(loc['exits']) if loc['exits'] else "none"
    header = format_text(f"[ {node_icon} {loc['name']} ]", C_CYAN, bold=True)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(header)}")
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(loc['description'], C_YELLOW))}")
    node_stats = f"Type: {loc['type'].upper()} | Level: {loc['level']} | Credits: {loc['credits']}c"
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(node_stats, C_GREEN))}")
    
    # Phase 3: Metadata display
    meta_str = f"Integrity: {loc.get('visibility_mode', 'OPEN')}"
    if loc.get('visibility_mode') == 'OPEN' and loc.get('irc_affinity'):
        meta_str += f" | Network: {loc['irc_affinity'].upper()}"
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(meta_str, C_CYAN))}")

    # Local Topology Mini-Map (Radius 1)
    async with node.db.async_session() as session:
        char = await node.db.get_character_by_nick(nickname, node.net_name, session)
        if char:
            map_text = await generate_ascii_map(session, char, machine_mode=machine, limit_radius=1, show_legend=False)
            for line in map_text.split("\n"):
                await node.send(f"PRIVMSG {reply_target} :{build_banner(line)}")

    action_prompt = format_text(f"[GRID] {nickname} @ {loc['name']} | Use '{node.prefix} move <dir>' to travel.", C_YELLOW)
    if loc['type'] == 'arena': action_prompt += format_text(f" | Use '{node.prefix} queue' to enter the Arena.", C_GREEN)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(action_prompt)}")

async def handle_node_explore(node, nick: str, reply_target: str):
    from .combat import handle_mob_encounter
    if not await check_rate_limit(node, nick, reply_target, cooldown=45): return
    result = await node.db.explore_node(nick, node.net_name)
    
    if "error" in result:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(result['error'], C_RED))}")
        return
    
    banner = format_text(result['msg'], C_GREEN if result['status'] == 'success' else C_YELLOW)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
    
    # Award XP: 5 for success, 2 for attempt
    xp_reward = 5 if result['status'] == 'success' else 2
    await node.add_xp(nick, xp_reward, reply_target)
    
    if result.get("danger") == "GRID_BUG_SPAWN":
        # Manually trigger a mob encounter with a Level 0 Grid Bug
        loc = await node.db.get_location(nick, node.net_name)
        await handle_mob_encounter(node, nick, loc['name'], 0, None, reply_target)
    
    if result['status'] == 'success':
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] Grid Discovery: {nick} uncovered architectural secrets at their current position!', C_CYAN))}")

async def handle_grid_map(node, nick: str, reply_target: str):
    """Render the ASCII grid map."""
    async with node.db.async_session() as session:
        # Get character for stats
        char = await node.db.get_character_by_nick(nick, node.net_name, session)
        if not char:
            await node.send(f"PRIVMSG {reply_target} :[ERR] Persona offline.")
            return
        
        machine = await is_machine_mode(node, nick)
        map_text = await generate_ascii_map(session, char, machine_mode=machine)
        
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ TERMINAL NODAL TOPOLOGY ]', C_CYAN, True))}")
        for line in map_text.split("\n"):
            await node.send(f"PRIVMSG {reply_target} :{build_banner(line)}")

async def handle_grid_command(node, nickname: str, reply_target: str, action: str):
    if action == "claim": success, msg = await node.db.claim_node(nickname, node.net_name)
    elif action == "upgrade": success, msg = await node.db.upgrade_node(nickname, node.net_name)
    elif action == "siphon": success, msg = await node.db.siphon_node(nickname, node.net_name)
    elif action == "repair": success, msg = await node.db.grid_repair(nickname, node.net_name)
    elif action == "recharge": success, msg = await node.db.grid_recharge(nickname, node.net_name)
    elif action == "hack":
        success, msg = await node.db.hack_node(nickname, node.net_name)
        if not success and msg == "PVE_GUARDIAN_SPAWN":
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[WARNING] Primary ICE activated. PvE Guardian routine detected.', C_RED))}")
            return
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(msg, C_GREEN if success else C_RED))}")
    if success and action in ["claim", "upgrade", "hack", "repair", "recharge"]:
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] Grid Alert: {nickname} executed a territorial {action}!', C_YELLOW))}")
        
        # Award XP for successful Grid actions
        xp_map = {"claim": 25, "upgrade": 15, "hack": 10, "repair": 5, "recharge": 2}
        if action in xp_map:
            await node.add_xp(nickname, xp_map[action], reply_target)

async def handle_grid_loot(node, nick: str, reply_target: str):
    if not await check_rate_limit(node, nick, reply_target, cooldown=60): return
    result = await node.db.raid_node(nick, node.net_name)
    
    banner = format_text(result['msg'], C_GREEN if result['success'] else C_RED)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
    
    if result['success']:
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(result['sigact'], C_YELLOW, True))}")
        await node.add_xp(nick, 10, reply_target)

async def handle_grid_network_msg(node, nick: str, args: list, reply_target: str):
    if len(args) < 3:
        await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} grid network msg <nick> <msg>")
        return
        
    target_nick = args[1]
    message = " ".join(args[2:])
    
    loc = await node.db.get_location(nick, node.net_name)
    if not loc or not loc.get('irc_affinity'):
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('System Error: This node lacks a synchronized IRC bridge.', C_RED))}")
        return
        
    target_net = loc['irc_affinity']
    # Format the message to include the sender's origin
    formatted_msg = format_text(f"[CROSS-GRID] <{nick}@{node.net_name}> {message}", C_CYAN)
    
    success = await node.hub.relay_message(target_net, target_nick, formatted_msg)
    if success:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Packet successfully relayed to {target_net} node.', C_GREEN))}")
    else:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Packet transmission failed: Network {target_net} is currently unreachable.', C_RED))}")
