import asyncio
import logging
import time
import shlex
from grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import get_action_routing

logger = logging.getLogger("manager")

async def handle_admin_command(node, admin_nick: str, verb: str, args: list, reply_target: str):
    # Logging Redaction Utility
    def mask_args(v, a):
        if v in ["nickregister", "nickidentify"] and len(a) > 0:
            return ["********"] + a[1:]
        if v == "nickconfirm" and len(a) > 0:
            return ["****"] + a[1:]
        return a

    # Redacted log for INFO, full for DEBUG
    logger.info(f"SYSADMIN OVERRIDE: {admin_nick} -> {verb} {mask_args(verb, args)}")
    logger.debug(f"SYSADMIN TRACE: {admin_nick} -> {verb} {args}")
    
    tactical_target, broadcast_chan, machine, tactical_cmd = await get_action_routing(node, admin_nick, reply_target)
    
    # Handle !a admin <subcommand>
    if verb == "admin":
        if not args:
            # Landing Page
            await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text('[ MAINFRAME ADMIN OVERRIDES ]', C_CYAN, True), tags=['SIGINT'], nick=admin_nick)}")
            cmds = ["status", "version", "topic", "broadcast <msg>", "nickregister", "nickconfirm", "nickidentify", "grid <rename|chgdesc|seed|spawn>", "battlestart/stop", "restart", "stop", "shutdown"]
            cmd_str = ", ".join([f"{node.prefix} admin {c}" for c in cmds])
            await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(cmd_str, C_WHITE), tags=['SIGINT'], nick=admin_nick)}")
            return
        
        # Shift args
        verb = args[0].lower()
        args = args[1:]
        logger.info(f"Sub-command routing: {verb} {args}")

    if verb == "version":
        # System Versions
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text('[ SYSTEM VERSION ARCHIVE ]', C_CYAN, True), tags=['SIGINT'], nick=admin_nick)}")
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text('Mainframe Core: v1.5.0-STABLE', C_WHITE), tags=['SIGINT'], nick=admin_nick)}")
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text('DB Orchestrator: v1.5.0 | Repositories: v1.5.0', C_GREEN), tags=['SIGINT'], nick=admin_nick)}")
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text('Command Router: v1.5.0 | AI Bot Client: v1.5.0', C_YELLOW), tags=['SIGINT'], nick=admin_nick)}")
    elif verb == "status":
        # 1. Base Population & Systems
        players = await node.db.list_players(node.net_name)
        b_stat = f"ACTIVE (Turn {node.active_engine.turn})" if node.active_engine and node.active_engine.active else "STANDBY"
        
        # 2. Grid & Economy Telemetry
        grid = await node.db.get_grid_telemetry()
        econ = await node.db.get_global_economy()
        
        # 3. Uptime
        uptime_sec = time.time() - node.hub.start_time
        h = int(uptime_sec // 3600); m = int((uptime_sec % 3600) // 60)
        uptime = f"{h}h {m}m"

        # 4. Multi-line Report
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text('[ MAINFRAME TELEMETRY ]', C_CYAN, True), tags=['SIGINT'], nick=admin_nick)}")
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(f'UPTIME: {uptime} | STATUS: {b_stat} | BOTS: {len(players)}', C_WHITE), tags=['SIGINT'], nick=admin_nick)}")
        
        grid_msg = f"GRID: {grid['claimed_nodes']}/{grid['total_nodes']} nodes ({grid['claimed_percent']:.1f}%) | MESH: {grid['total_power']:.0f}uP"
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(grid_msg, C_GREEN), tags=['SIGINT'], nick=admin_nick)}")
        
        econ_msg = f"ECON: {econ['total_credits']:.0f}c Total Liquidity | {econ['total_data_units']:.1f}u Total Data"
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(econ_msg, C_YELLOW), tags=['SIGINT'], nick=admin_nick)}")
        
        queue_msg = f"QUEUE: {len(node.match_queue)} in line | {len(node.ready_players)} ready to drop"
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(queue_msg, C_CYAN), tags=['SIGINT'], nick=admin_nick)}")
    elif verb == "battlestop":
        if node.active_engine and node.active_engine.active:
            node.active_engine.active = False
            node.active_engine = None
            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text('ADMIN OVERRIDE: ACTIVE COMBAT SEQUENCE HALTED.', C_RED, True), tags=['SIGACT'], nick=admin_nick)}")
            await node.send(f"{tactical_cmd} {reply_target} :[SYS] Match aborted.")
        else: await node.send(f"{tactical_cmd} {reply_target} :[SYS] No active battle.")
    elif verb == "battlestart":
        if node.active_engine and node.active_engine.active: await node.send(f"{tactical_cmd} {reply_target} :[SYS] Arena locked.")
        elif len(node.ready_players) > 0: await node.check_match_start()
        else: await node.trigger_arena_call()
    elif verb == "topic": await node.set_dynamic_topic()
    elif verb == "broadcast":
        msg = format_text(f"[SYSADMIN OVERRIDE] {' '.join(args)}", C_YELLOW, True)
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(msg, tags=['SIGACT'], nick=admin_nick)}")
    elif verb == "grid":
        # Handle !a admin grid rename <old> <new>
        full_args = shlex.split(" ".join(args))
        if len(full_args) >= 3 and full_args[0].lower() == "rename":
            old_name, new_name = full_args[1], full_args[2]
            success, feedback = await node.db.rename_node(old_name, new_name)
            tag = "SIGINT" if success else "OSINT"
            await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(feedback, tags=[tag], nick=admin_nick)}")
            if success:
                announcement = format_text(f"NODE REBRANDED: {old_name} is now known as {new_name}.", C_CYAN, True)
                await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(announcement, tags=['SIGACT'], nick=admin_nick)}")
        elif len(full_args) >= 2 and full_args[0].lower() == "seed":
            try: count = int(full_args[1])
            except: count = 1
            if count > 5: count = 5 # Limit per operation
            await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(f'Initiating procedural grid expansion ({count} nodes)...', C_YELLOW), tags=['SIGINT'], nick=admin_nick)}")
            
            new_nodes = await node.llm.generate_grid_nodes(count)
            added_count = 0
            for n_data in new_nodes:
                # Add individual nodes to DB
                stmt = select(node.db.models.GridNode).where(node.db.models.GridNode.name == n_data['name'])
                async with node.db.async_session() as session:
                    exists = (await session.execute(stmt)).scalars().first()
                    if not exists:
                        node_obj = node.db.models.GridNode(
                            name=n_data['name'], 
                            description=n_data['desc'], 
                            node_type=n_data.get('type', 'wilderness'),
                            threat_level=n_data.get('threat', 1)
                        )
                        session.add(node_obj)
                        await session.commit()
                        added_count += 1
            
            feedback = f"Expansion complete. Synced {added_count} new sectors to the mesh."
            await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(feedback, C_GREEN), tags=['SIGINT'], nick=admin_nick)}")
        elif len(full_args) >= 3 and full_args[0].lower() == "chgdesc":
            target_node, new_desc = full_args[1], " ".join(full_args[2:])
            success, feedback = await node.db.grid.update_node_description(target_node, new_desc)
            tag = "SIGINT" if success else "OSINT"
            await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(feedback, tags=[tag], nick=admin_nick)}")
            if success:
                announcement = format_text(f"NODE ARCHITECTURE REDEFINED: {target_node} sensors updated.", C_CYAN, True)
                await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(announcement, tags=['SIGACT'], nick=admin_nick)}")
        elif full_args[0].lower() == "spawn":
            if len(full_args) >= 2:
                target_node = full_args[1]
                success, feedback = await node.db.grid.set_spawn_node(target_node)
                tag = "SIGINT" if success else "OSINT"
                await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(feedback, tags=[tag], nick=admin_nick)}")
            else:
                current_spawn = await node.db.grid.get_spawn_node_name()
                await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(f'Current Grid Nexus: {current_spawn}', C_CYAN), tags=['SIGINT'], nick=admin_nick)}")
        else:
            await node.send(f"{tactical_cmd} {tactical_target} :[ERR] Syntax: {node.prefix} admin grid <rename|seed|spawn> [args]")
    elif verb in ["nickregister", "nickconfirm", "nickidentify"]:
        # SECURITY GATE: Force PM for auth commands
        if reply_target.lower() == node.config['channel'].lower():
            await node.send(f"PRIVMSG {admin_nick} :{tag_msg(format_text('[SITREP] SENSITIVE AUTH: Authentication commands must be executed via Private Message.', C_RED, True), tags=['ALARM'])}")
            return

        if verb == "nickregister":
            # Report current +r status
            is_r = admin_nick.lower() in node.nickserv_verified if admin_nick.lower() == node.config['nickname'].lower() else (node.config['nickname'].lower() in node.nickserv_verified)
            # Actually we want the BOT's status
            bot_nick = node.config['nickname'].lower()
            bot_verified = bot_nick in node.nickserv_verified
            status_str = format_text("ALREADY +r (REGISTERED)", C_GREEN) if bot_verified else format_text("NOT REGISTERED", C_RED)
            await node.send(f"PRIVMSG {admin_nick} :{tag_msg(f'Current Identity Status: {status_str}', tags=['SIGINT'])}")
            
            if len(args) >= 2:
                password, email = args[0], args[1]
                await node.send(f"PRIVMSG NickServ :REGISTER {password} {email}", immediate=True)
                await node.send(f"PRIVMSG {admin_nick} :{tag_msg('Registration command emitted to NickServ.', tags=['SIGINT'])}")
            else:
                await node.send(f"PRIVMSG {admin_nick} :{tag_msg(f'[ERR] Syntax: {node.prefix} admin nickregister <password> <email>', tags=['OSINT'])}")
        
        elif verb == "nickconfirm":
            if args:
                code = args[0]
                await node.send(f"PRIVMSG NickServ :CONFIRM {code}", immediate=True)
                await node.send(f"PRIVMSG {admin_nick} :{tag_msg('Confirmation code emitted to NickServ.', tags=['SIGINT'])}")
            else:
                await node.send(f"PRIVMSG {admin_nick} :{tag_msg(f'[ERR] Syntax: {node.prefix} admin nickconfirm <code>', tags=['OSINT'])}")
        
        elif verb == "nickidentify":
            if args:
                password = args[0]
                await node.send(f"PRIVMSG NickServ :IDENTIFY {password}", immediate=True)
                await node.send(f"PRIVMSG {admin_nick} :{tag_msg('Manual identification emitted to NickServ. Verification WHOIS pending...', tags=['SIGINT'])}")
                # Trigger a verification WHOIS after a short delay
                async def delayed_check():
                    await asyncio.sleep(5)
                    from core.security import request_nickserv_check
                    await request_nickserv_check(node, node.config['nickname'])
                asyncio.create_task(delayed_check())
            else:
                await node.send(f"PRIVMSG {admin_nick} :{tag_msg(f'[ERR] Syntax: {node.prefix} admin nickidentify <password>', tags=['OSINT'])}")
                
    elif verb == "restart":
        msg = tag_msg(format_text('MAINFRAME RESTART INITIATED BY ADMIN.', C_YELLOW, True), tags=['SIGACT'], nick=admin_nick)
        await node.send(f"PRIVMSG {node.config['channel']} :{msg}", immediate=True)
        if node.active_engine: node.active_engine.active = False
        await asyncio.sleep(1)
        await node.hub.restart()
    elif verb in ["shutdown", "stop"]:
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text('MAINFRAME SHUTDOWN INITIATED BY ADMIN.', C_RED, True), tags=['SIGACT'], nick=admin_nick)}")
        if node.active_engine: node.active_engine.active = False
        await asyncio.sleep(1)
        await node.hub.shutdown()
