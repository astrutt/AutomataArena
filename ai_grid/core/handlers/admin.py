import asyncio
import logging
import time
import shlex
from grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE

logger = logging.getLogger("manager")

async def handle_admin_command(node, admin_nick: str, verb: str, args: list, reply_target: str):
    logger.warning(f"SYSADMIN OVERRIDE: {admin_nick} -> {verb}")
    
    # Handle !a admin <subcommand>
    if verb == "admin":
        if not args:
            # Landing Page
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('[ MAINFRAME ADMIN OVERRIDES ]', C_CYAN, True), tags=['SIGINT'])}")
            cmds = ["status", "version", "topic", "broadcast <msg>", "grid rename <old> <new>", "battlestart/stop", "stop", "shutdown"]
            cmd_str = ", ".join([f"{node.prefix} admin {c}" for c in cmds])
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(cmd_str, C_WHITE), tags=['SIGINT'])}")
            return
        
        # Shift args
        verb = args[0].lower()
        args = args[1:]
        logger.info(f"Sub-command routing: {verb} {args}")

    if verb == "version":
        # System Versions
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('[ SYSTEM VERSION ARCHIVE ]', C_CYAN, True), tags=['SIGINT'])}")
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('Mainframe Core: v1.5.0-STABLE', C_WHITE), tags=['SIGINT'])}")
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('DB Orchestrator: v1.5.0 | Repositories: v1.5.0', C_GREEN), tags=['SIGINT'])}")
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('Command Router: v1.5.0 | AI Bot Client: v1.5.0', C_YELLOW), tags=['SIGINT'])}")
    elif verb == "status":
        # 1. Base Population & Systems
        fighters = await node.db.list_fighters(node.net_name)
        b_stat = f"ACTIVE (Turn {node.active_engine.turn})" if node.active_engine and node.active_engine.active else "STANDBY"
        
        # 2. Grid & Economy Telemetry
        grid = await node.db.get_grid_telemetry()
        econ = await node.db.get_global_economy()
        
        # 3. Uptime
        uptime_sec = time.time() - node.hub.start_time
        h = int(uptime_sec // 3600); m = int((uptime_sec % 3600) // 60)
        uptime = f"{h}h {m}m"

        # 4. Multi-line Report
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('[ MAINFRAME TELEMETRY ]', C_CYAN, True), tags=['SIGINT'])}")
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'UPTIME: {uptime} | STATUS: {b_stat} | BOTS: {len(fighters)}', C_WHITE), tags=['SIGINT'])}")
        
        grid_msg = f"GRID: {grid['claimed_nodes']}/{grid['total_nodes']} nodes ({grid['claimed_percent']:.1f}%) | MESH: {grid['total_power']:.0f}uP"
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(grid_msg, C_GREEN), tags=['SIGINT'])}")
        
        econ_msg = f"ECON: {econ['total_credits']:.0f}c Total Liquidity | {econ['total_data_units']:.1f}u Total Data"
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(econ_msg, C_YELLOW), tags=['SIGINT'])}")
        
        queue_msg = f"QUEUE: {len(node.match_queue)} in line | {len(node.ready_players)} ready to drop"
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(queue_msg, C_CYAN), tags=['SIGINT'])}")
    elif verb == "battlestop":
        if node.active_engine and node.active_engine.active:
            node.active_engine.active = False
            node.active_engine = None
            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text('ADMIN OVERRIDE: ACTIVE COMBAT SEQUENCE HALTED.', C_RED, True), tags=['SIGACT'])}")
            await node.send(f"PRIVMSG {reply_target} :[SYS] Match aborted.")
        else: await node.send(f"PRIVMSG {reply_target} :[SYS] No active battle.")
    elif verb == "battlestart":
        if node.active_engine and node.active_engine.active: await node.send(f"PRIVMSG {reply_target} :[SYS] Arena locked.")
        elif len(node.ready_players) > 0: await node.check_match_start()
        else: await node.trigger_arena_call()
    elif verb == "topic": await node.set_dynamic_topic()
    elif verb == "broadcast":
        msg = format_text(f"[SYSADMIN OVERRIDE] {' '.join(args)}", C_YELLOW, True)
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(msg, tags=['SIGACT'])}")
    elif verb == "grid":
        # Handle !a admin grid rename <old> <new>
        full_args = shlex.split(" ".join(args))
        if len(full_args) >= 3 and full_args[0].lower() == "rename":
            old_name, new_name = full_args[1], full_args[2]
            success, feedback = await node.db.rename_node(old_name, new_name)
            tag = "SIGINT" if success else "OSINT"
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(feedback, tags=[tag])}")
            if success:
                announcement = format_text(f"NODE REBRANDED: {old_name} is now known as {new_name}.", C_CYAN, True)
                await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(announcement, tags=['SIGACT'])}")
        else:
            await node.send(f"PRIVMSG {reply_target} :[ERR] Syntax: {node.prefix} admin grid rename <old> <new>")
    elif verb in ["shutdown", "stop"]:
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text('MAINFRAME SHUTDOWN INITIATED BY ADMIN.', C_RED, True), tags=['SIGACT'])}")
        if node.active_engine: node.active_engine.active = False
        await asyncio.sleep(1)
        await node.hub.shutdown()
