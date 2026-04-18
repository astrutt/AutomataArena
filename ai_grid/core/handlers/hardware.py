# ai_grid/core/handlers/hardware.py
import json
import logging
from grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode, get_action_routing

logger = logging.getLogger("manager")

async def handle_grid_hardware(node, nick: str, reply_target: str, action: str = None, args: list = None):
    """
    Manages Grid Node hardware modules.
    Syntax: !a grid hardware [install|uninstall] <item>
    """
    args = args or []
    msg_target, broadcast_chan, machine, action_cmd = await get_action_routing(node, nick, reply_target)
    
    # OSINT Status View (Default if no action specified)
    if not action:
        loc = await node.db.get_location(nick, node.net_name)
        if not loc:
            await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nick} - not a registered player")
            return
            
        async with node.db.async_session() as session:
            char_node = await node.db.get_character_by_nick(nick, node.net_name, session)
            if not char_node or not char_node.current_node:
                await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nick} - topology failure")
                return
            
            gn = char_node.current_node
            addons = json.loads(gn.addons_json or "{}")
            
            if machine:
                addon_list = ",".join(addons.keys()) if addons else "NONE"
                line = f"HARDWARE:{gn.name} SLOTS:{len(addons)}/{gn.max_slots} MODULES:[{addon_list}] IDS_ALERTS:{gn.ids_alerts} FIREWALL_HITS:{gn.firewall_hits}"
                await node.send(f"{action_cmd} {msg_target} :[GRID] {line}")
                return

            # High-Aesthetic Human View
            header = format_text(f"⚔️ [ HARDWARE MANIFEST: {gn.name} ]", C_CYAN, bold=True)
            await node.send(f"{action_cmd} {msg_target} :{tag_msg(header, tags=['GEOINT'], location=gn.name)}")
            
            # Slot Display
            slots = []
            standard_modules = ["AMP", "IDS", "FIREWALL", "NET"]
            for mod in standard_modules:
                if addons.get(mod):
                    slots.append(format_text(f"[{mod}]", C_GREEN))
                else:
                    slots.append(format_text("[OPEN]", C_WHITE))
            
            # Handle non-standard modules if any exist
            for mod in addons:
                if mod not in standard_modules:
                    slots.append(format_text(f"[{mod}*]", C_YELLOW))
            
            slot_info = " | ".join(slots)
            await node.send(f"{action_cmd} {msg_target} :{tag_msg(f'Chassis Slots: {slot_info}', tags=['GEOINT'])}")
            
            # Security Counters
            meters = []
            if addons.get("IDS") or gn.ids_alerts > 0:
                meters.append(f"{format_text('📜 IDS_ALERTS:', C_YELLOW)} {gn.ids_alerts}")
            if addons.get("FIREWALL") or gn.firewall_hits > 0:
                meters.append(f"{format_text('🛡️ FIREWALL_HITS:', C_RED)} {gn.firewall_hits}")
            
            if meters:
                await node.send(f"{action_cmd} {msg_target} :{tag_msg(' | '.join(meters), tags=['GEOINT'])}")
            
            footer = format_text(f"Use '{node.prefix} grid hardware install <item>' to augment architecture.", C_YELLOW)
            await node.send(f"{action_cmd} {msg_target} :{tag_msg(footer, tags=['GEOINT'])}")
        return

    # Action Handlers
    if action == "install":
        if not args:
            await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} grid hardware install <module>")
            return
        
        module_name = args[0]
        result = await node.db.grid.install_node_addon(nick, node.net_name, module_name)
        
        if result['success']:
            await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text(result['msg'], C_GREEN), tags=['SIGACT', nick])}")
            # Public narrative
            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(f'Hardware Augmented: {nick} installed {module_name.upper()} on local node.', C_YELLOW), tags=['SIGACT'])}")
            await node.add_xp(nick, 10, reply_target)
        else:
            await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text(result['msg'], C_RED), tags=['SIGACT', nick])}")

    elif action == "uninstall" or action == "remove" or action == "decommission":
        if not args:
            await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} grid hardware uninstall <module>")
            return
            
        module_name = args[0]
        result = await node.db.grid.uninstall_node_addon(nick, node.net_name, module_name)
        
        if result['success']:
            await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text(result['msg'], C_CYAN), tags=['SIGACT', nick])}")
        else:
            await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text(result['msg'], C_RED), tags=['SIGACT', nick])}")
    
    else:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Hardware sub-command '{action}' unrecognized. Use: install, uninstall.")
