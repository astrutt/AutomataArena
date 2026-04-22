# handlers/machine.py - Production & The Gibson Handlers
import logging
from ai_grid.grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode, check_rate_limit, get_action_routing

logger = logging.getLogger("manager")

async def handle_powergen(node, nick: str, reply_target: str):
    if not await check_rate_limit(node, nick, reply_target, cooldown=60, consume=False): return
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    success, msg = await node.db.active_powergen(nick, node.net_name)
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='MAINT', result='SUCCESS' if success else 'FAIL', nick=nick, is_machine=machine_mode)}")
    
    if success:
        if not machine_mode:
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nick} initiated an active power generation cycle.', C_CYAN), action='SIGACT', nick=nick)}")
        await node.add_xp(nick, 3, private_target)

async def handle_training(node, nick: str, reply_target: str):
    if not await check_rate_limit(node, nick, reply_target, cooldown=60, consume=False): return
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    success, msg = await node.db.active_training(nick, node.net_name)
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='MAINT', result='SUCCESS' if success else 'FAIL', nick=nick, is_machine=machine_mode)}")
    
    if success:
        if not machine_mode:
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nick} completed a structural maintenance drill.', C_CYAN), action='SIGACT', nick=nick)}")
        await node.add_xp(nick, 3, private_target)

async def handle_gibson_status(node, nick: str, reply_target: str):
    """View status of Gibson mainframe tasks."""
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    data = await node.db.get_gibson_status(nick, node.net_name)
    
    if 'error' in data:
        await node.send(f"{reply_method} {private_target} :{tag_msg(data['error'], action='SIGINT', result='ERR', nick=nick, is_machine=machine_mode)}")
        return
    
    if machine_mode:
        tasks = ",".join([f"{t['type']}:{t['remaining_sec']}s" for t in data['active_tasks']]) or "none"
        msg = f"DATA:{data['data']:.1f} VULNS:{data['vulns']} ZD:{data['zero_days']} HARVEST:{data['harvest_rate']:.1f} TASKS:{tasks}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGINT', result='INFO', nick=nick, is_machine=True)}")
        return

    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('[ MAINFRAME UI: THE GIBSON ]', C_CYAN, True), action='SIGINT')}")
    storage = f"Raw Data: {data['data']:.1f} | Vulns: {data['vulns']} | Zero-Days: {data['zero_days']}"
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(storage, C_GREEN), action='SIGINT')}")
    
    perf = f"Global Harvest Rate: {data['harvest_rate']:.1f} uP/tick | Character Power: {data['character_power']:.1f}"
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(perf, C_YELLOW), action='SIGINT')}")
    
    if data['active_tasks']:
        for t in data['active_tasks']:
            m, s = divmod(t['remaining_sec'], 60)
            line = f"[{t['type']}] Yielding {t['amount']} units | ETA: {m}m {s}s"
            await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(line, C_GREEN), action='SIGINT', is_machine=False)}")
    else:
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text('Mainframe Idle. Ready for compilation.', C_CYAN), action='SIGINT', is_machine=False)}")

async def handle_gibson_compile(node, nick: str, args: list, reply_target: str):
    try: amount = int(args[0]) if args else 100
    except: amount = 100
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    result = await node.db.start_compilation(nick, node.net_name, amount)
    msg = result.get('error') or result.get('msg', 'COMPILE_START')
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='SUCCESS' if 'msg' in result else 'FAIL', nick=nick, is_machine=machine_mode)}")
    
    if 'msg' in result and not machine_mode:
        usage = f"Power Consumed: {result['node_used']:.1f} (Node) | {result['char_used']:.1f} (Char)"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(usage, C_YELLOW), action='SIGACT')}")

async def handle_gibson_assemble(node, nick: str, reply_target: str):
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    result = await node.db.start_assembly(nick, node.net_name)
    msg = result.get('error') or result.get('msg', 'ASSEMBLE_START')
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='SUCCESS' if 'msg' in result else 'FAIL', nick=nick, is_machine=machine_mode)}")
    
    if 'msg' in result and not machine_mode:
        usage = f"Power Consumed: {result['node_used']:.1f} (Node) | {result['char_used']:.1f} (Char)"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(usage, C_YELLOW), action='SIGACT')}")

async def handle_item_use(node, nick: str, args: list, reply_target: str):
    if not args: return
    item_name = " ".join(args)
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    result, msg = await node.db.use_item(nick, node.net_name, item_name)
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='SUCCESS' if result else 'FAIL', nick=nick, is_machine=machine_mode)}")
    
    if result and not machine_mode:
        await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nick} used {item_name}.', C_CYAN), action='SIGACT', nick=nick)}")
