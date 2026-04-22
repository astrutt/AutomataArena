# ai_grid/core/handlers/hardware.py
import json
import logging
from ai_grid.grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode, get_action_routing

logger = logging.getLogger("manager")

async def handle_grid_hardware(node, nick: str, reply_target: str, action: str = None, args: list = None):
    """
    Manages Grid Node hardware modules.
    Syntax: !a grid hardware [install|uninstall] <item>
    """
    args = args or []
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    # OSINT Status View (Default if no action specified)
    if not action:
        loc = await node.db.get_location(nick, node.net_name)
        if not loc:
            await node.send(f"PRIVMSG {reply_target} :[ERR] {nick} - not a registered player")
            return
            
        async with node.db.async_session() as session:
            char_node = await node.db.get_character_by_nick(nick, node.net_name, session)
            if not char_node or not char_node.current_node:
                await node.send(f"PRIVMSG {reply_target} :[ERR] {nick} - topology failure")
                return
            
            gn = char_node.current_node
            addons = json.loads(gn.addons_json or "{}")
            
            if machine_mode:
                addon_list = ",".join(addons.keys()) if addons else "NONE"
                msg = f"NODE:{gn.name} SLOTS:{len(addons)}/{gn.max_slots} MODULES:[{addon_list}] IDS:{gn.ids_alerts} FW:{gn.firewall_hits}"
                await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='GEOINT', result='INFO', nick=nick, is_machine=True)}")
                return

            header = format_text(f"[ HARDWARE MANIFEST: {gn.name} ]", C_CYAN, bold=True)
            await node.send(f"{reply_method} {private_target} :{tag_msg(header, action='GEOINT', result='INFO', nick=nick)}")
            
            slots = []
            for mod in ["AMP", "IDS", "FIREWALL", "NET"]:
                st = format_text(f"[{mod}]", C_GREEN) if addons.get(mod) else format_text("[OPEN]", C_WHITE)
                slots.append(st)
            slots_str = ' | '.join(slots)
            await node.send(f"{reply_method} {private_target} :{tag_msg(f'Chassis Slots: {slots_str}', action='GEOINT')}")
            
            meters = []
            if addons.get("IDS") or gn.ids_alerts > 0: meters.append(f"IDS: {gn.ids_alerts}")
            if addons.get("FIREWALL") or gn.firewall_hits > 0: meters.append(f"FW: {gn.firewall_hits}")
            if meters: await node.send(f"{reply_method} {private_target} :{tag_msg(' | '.join(meters), action='GEOINT')}")
        return

    # Action Handlers
    res_status = 'FAIL'
    if action == "install":
        if not args: return
        module_name = args[0]
        result = await node.db.grid.install_node_addon(nick, node.net_name, module_name)
        success = result['success']
        res_status = 'SUCCESS' if success else 'FAIL'
        await node.send(f"{reply_method} {private_target} :{tag_msg(result['msg'], action='SIGACT', result=res_status, nick=nick, is_machine=machine_mode)}")
        if success:
            if not machine_mode:
                await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(f'Hardware Augmented: {nick} installed {module_name.upper()}.', action='SIGACT')}")
            await node.add_xp(nick, 10, reply_target)

    elif action in ["uninstall", "remove", "decommission"]:
        if not args: return
        module_name = args[0]
        result = await node.db.grid.uninstall_node_addon(nick, node.net_name, module_name)
        res_status = 'SUCCESS' if result['success'] else 'FAIL'
        await node.send(f"{reply_method} {private_target} :{tag_msg(result['msg'], action='SIGACT', result=res_status, nick=nick, is_machine=machine_mode)}")
