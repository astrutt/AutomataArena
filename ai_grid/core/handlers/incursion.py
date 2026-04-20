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
        loc = await node.db.get_location(source_nick, node.net_name)
        if not loc:
            await node.send(f"{reply_method} {private_target} :{tag_msg('Cannot locate grid presence.', action='ERR', nick=source_nick, is_machine=machine_mode)}")
            return
        node_name = loc['name']
    else:
        node_name = args[0]
        
    success, msg, victors = await node.db.incursion.register_defense(source_nick, node.net_name, node_name)
    
    if success:
        if victors:
            # Resolved successfully
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(msg, action='SIGACT', result='SUCCESS')}")
            v_msg = f"Defenders deployed: {', '.join(victors)}"
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(v_msg, action='SIGINT')}")
        else:
            # Successfully logged defense, still waiting for players
            await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='OK', nick=source_nick, is_machine=machine_mode)}")
            chan_alert = f"{source_nick} deployed defense protocols at {node_name}!"
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(chan_alert, action='SIGACT', result='ALERT')}")
    else:
        await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='FAIL', nick=source_nick, is_machine=machine_mode)}")
