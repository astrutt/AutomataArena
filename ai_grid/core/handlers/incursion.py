# handlers/incursion.py - v1.0.0
import asyncio
import logging
from grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW
from .base import get_action_routing

logger = logging.getLogger("manager")

async def handle_incursion_defend(node, source_nick: str, args: list, current_target: str):
    """Processes an Incursion Defense attempt."""
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, source_nick, current_target)

    if not args:
        # Default to player's current node if omitted
        loc = await node.db.get_location(source_nick, node.net_name)
        if not loc:
            alert = format_text("Cannot locate your physical grid presence.", C_RED)
            await node.send(f"{reply_method} {private_target} :{tag_msg(alert, tags=['ERR', source_nick])}")
            return
        node_name = loc['name']
    else:
        node_name = args[0]
        
    success, msg, victors = await node.db.incursion.register_defense(source_nick, node.net_name, node_name)
    
    if success:
        if victors:
            # Resolved successfully
            alert = format_text(msg, C_GREEN, bold=True)
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(alert, tags=['SIGACT', 'INCURSION'])}")
            
            victors_str = ", ".join(victors)
            v_msg = format_text(f"Defenders deployed: {victors_str}", C_CYAN)
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(v_msg, tags=['SIGINT'])}")
        else:
            # Successfully logged defense, still waiting for players
            alert = format_text(msg, C_YELLOW)
            await node.send(f"{reply_method} {private_target} :{tag_msg(alert, tags=['SIGACT', source_nick])}")
            # Also notify the channel that someone deployed
            chan_alert = format_text(f"{source_nick} has deployed defense protocols at {node_name}!", C_YELLOW)
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(chan_alert, tags=['SIGACT', 'DEFENSE'])}")
    else:
        # Failed (not found, already defended, etc.)
        alert = format_text(msg, C_RED)
        await node.send(f"{reply_method} {private_target} :{tag_msg(alert, tags=['ERR', source_nick])}")
