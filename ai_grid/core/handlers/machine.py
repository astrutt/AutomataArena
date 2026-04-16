# handlers/machine.py - Production & The Gibson Handlers
import logging
from grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode, check_rate_limit

logger = logging.getLogger("manager")

async def handle_powergen(node, nick: str, reply_target: str):
    if not await check_rate_limit(node, nick, reply_target, cooldown=60): return
    success, msg = await node.db.active_powergen(nick, node.net_name)
    banner = format_text(msg, C_GREEN if success else C_RED)
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(banner, tags=['MAINT', nick])}")
    if success:
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(f'[SIGACT] {nick} initiated an active power generation cycle.', C_CYAN), tags=['SIGACT'])}")
        await node.add_xp(nick, 3, reply_target)

async def handle_training(node, nick: str, reply_target: str):
    if not await check_rate_limit(node, nick, reply_target, cooldown=60): return
    success, msg = await node.db.active_training(nick, node.net_name)
    banner = format_text(msg, C_GREEN if success else C_RED)
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(banner, tags=['MAINT', nick])}")
    if success:
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(f'[SIGACT] {nick} completed a structural maintenance drill.', C_CYAN), tags=['SIGACT'])}")
        await node.add_xp(nick, 3, reply_target)

async def handle_gibson_status(node, nick: str, reply_target: str):
    """View status of Gibson mainframe tasks."""
    data = await node.db.get_gibson_status(nick, node.net_name)
    if "error" in data:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(data['error'], C_RED), tags=['SIGINT', nick])}")
        return
    
    machine = await is_machine_mode(node, nick)
    if machine:
        tasks = ",".join([f"{t['type']}:{t['remaining_sec']}s" for t in data['active_tasks']]) or "none"
        await node.send(f"PRIVMSG {nick} :[GIBSON] DATA:{data['data']:.1f} VULNS:{data['vulns']} ZD:{data['zero_days']} HARVEST:{data['harvest_rate']:.1f} TASKS:{tasks}")
        return

    await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('[ MAINFRAME UI: THE GIBSON ]', C_CYAN, True), tags=['SIGINT'], is_machine=machine)}")
    storage = f"Raw Data: {data['data']:.1f} | Vulns: {data['vulns']} | Zero-Days: {data['zero_days']}"
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(storage, C_GREEN), tags=['SIGINT'], is_machine=machine)}")
    
    perf = f"Global Harvest Rate: {data['harvest_rate']:.1f} uP/tick | Character Power: {data['character_power']:.1f}"
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(perf, C_YELLOW), tags=['SIGINT'], is_machine=machine)}")
    
    if data['active_tasks']:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('--- ACTIVE TASKS ---', C_CYAN), tags=['SIGINT'], is_machine=machine)}")
        for t in data['active_tasks']:
            m, s = divmod(t['remaining_sec'], 60)
            line = f"[{t['type']}] Yielding {t['amount']} units | ETA: {m}m {s}s"
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(line, C_GREEN), tags=['SIGINT'], is_machine=machine)}")
    else:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('Mainframe Idle. Ready for compilation.', C_CYAN), tags=['SIGINT'], is_machine=machine)}")

async def handle_gibson_compile(node, nick: str, args: list, reply_target: str):
    """Start compilation task."""
    try: amount = int(args[0]) if args else 100
    except: amount = 100
    
    result = await node.db.start_compilation(nick, node.net_name, amount)
    if "error" in result:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(result['error'], C_RED), tags=['SIGACT', nick])}")
    else:
        banner = format_text(result['msg'], C_GREEN)
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(banner, tags=['SIGACT', nick])}")
        usage = f"Power Consumed: {result['node_used']:.1f} (Node) | {result['char_used']:.1f} (Char)"
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(usage, C_YELLOW), tags=['SIGACT'], is_machine=False)}")

async def handle_gibson_assemble(node, nick: str, reply_target: str):
    """Start assembly task."""
    result = await node.db.start_assembly(nick, node.net_name)
    if "error" in result:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(result['error'], C_RED), tags=['SIGACT', nick])}")
    else:
        banner = format_text(result['msg'], C_GREEN)
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(banner, tags=['SIGACT', nick])}")
        usage = f"Power Consumed: {result['node_used']:.1f} (Node) | {result['char_used']:.1f} (Char)"
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(usage, C_YELLOW), tags=['SIGACT'], is_machine=False)}")

async def handle_item_use(node, nick: str, args: list, reply_target: str):
    """Consume an item for a boost."""
    if not args:
        await node.send(f"PRIVMSG {reply_target} :Usage: {node.prefix} use <item_name>")
        return
    
    item_name = " ".join(args)
    result, msg = await node.db.use_item(nick, node.net_name, item_name)
    banner = format_text(msg, C_GREEN if result else C_RED)
    await node.send(f"PRIVMSG {reply_target} :{tag_msg(banner, tags=['SIGACT', nick])}")
