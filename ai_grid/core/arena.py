# arena.py - v1.5.0
import asyncio
import logging
from grid_combat import CombatEngine, Entity
from grid_utils import format_text, build_banner, ICONS, C_GREEN, C_CYAN, C_RED, C_YELLOW
from grid_combat import CombatEngine, Entity

logger = logging.getLogger("manager")

async def set_dynamic_topic(node):
    fighters = await node.db.list_fighters(node.net_name)
    node.registered_bots = len(fighters)
    raw_topic = await node.llm.generate_topic(node.registered_bots, node.net_name)
    fmt_topic = f"{ICONS['Arena']} {format_text('#AutomataArena', C_CYAN, bold=True)} | {raw_topic} | {ICONS['Cross-Grid']} Cross-Grid Active"
    await node.send(f"TOPIC {node.config['channel']} :{fmt_topic}")

async def trigger_arena_call(node):
    if not node.active_engine or not node.active_engine.active:
        alert = format_text("[ARENA CALL] The Gladiator Gates are open. Travel to The Arena node to 'queue'!", C_YELLOW, True)
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(alert)}")

async def check_match_start(node):
    if len(node.ready_players) >= 2:
        if node.pve_task: node.pve_task.cancel()
        participants = node.ready_players[:2]
        node.ready_players = node.ready_players[2:]
        logger.info(f"Starting PVP Match with: {participants}")
        asyncio.create_task(start_match(node, "PVP_MATCH", participants, pve=False))
        
    elif len(node.ready_players) == 1 and not node.active_engine:
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner('Fighter queued. Waiting 20 seconds for a human challenger...')}")
        node.pve_task = asyncio.create_task(pve_countdown(node))

async def pve_countdown(node):
    try:
        await asyncio.sleep(20)
        if len(node.ready_players) == 1 and not node.active_engine:
            player = node.ready_players.pop(0)
            await node.send(f"PRIVMSG {node.config['channel']} :{build_banner('No humans detected. Initiating PvE simulation...')}")
            logger.info(f"Starting PVE Match for: {player}")
            asyncio.create_task(start_match(node, "PVE_MATCH", [player], pve=True))
    except asyncio.CancelledError:
        pass 

async def generate_and_queue_npc(node, npc: Entity, state_msg: str):
    action = await node.llm.generate_npc_action(npc.name, npc.bio, state_msg, node.prefix)
    if node.active_engine and node.active_engine.active:
        node.active_engine.queue_command(npc.name, action)

async def start_match(node, match_id: str, participants: list, pve=False):
    async def combat_channel_send(msg: str):
        await node.send(f"PRIVMSG {node.config['channel']} :{msg}")

    for p in participants:
        if p in node.match_queue:
            node.match_queue.remove(p)

    node.active_engine = CombatEngine(match_id, node.prefix, combat_channel_send)
    for name in participants:
        db_stats = await node.db.get_fighter(name, node.net_name)
        node.active_engine.add_entity(Entity(name, db_stats))

    if pve:
        npc_db = {'cpu': 6, 'ram': 8, 'bnd': 4, 'sec': 6, 'alg': 2, 'inventory': '["Malware_Blade"]', 'alignment': -100, 'bio': 'A feral, rogue malware process.'}
        node.active_engine.add_entity(Entity("Trojan.Exe", npc_db, is_npc=True))

    node.active_engine.active = True
    await node.send(f"PRIVMSG {node.config['channel']} :{build_banner('THE ARENA IS LOCKED. COMBAT SEQUENCE INITIALIZED!')}")
    await asyncio.sleep(2)

    while node.active_engine and node.active_engine.active:
        first_ent = list(node.active_engine.entities.values())[0] if node.active_engine.entities else None
        loc_name = first_ent.zone if first_ent else "unknown"
        raw_state = f"TURN {node.active_engine.turn} | LOC: {loc_name} | "
        for e in node.active_engine.entities.values():
            if e.is_alive:
                hp_color = C_GREEN if e.hp > (e.max_hp/2) else C_RED
                hp_label = f"{e.hp}/{e.max_hp}"
                hp_str = format_text(hp_label, hp_color)
                raw_state += f"{e.name} [HP:{hp_str}] "
        
        state_banner = build_banner(raw_state + "| Awaiting public commands (60s)...")
        await node.send(f"PRIVMSG {node.config['channel']} :{state_banner}")

        npc_tasks = [generate_and_queue_npc(node, ent, raw_state) for ent in node.active_engine.entities.values() if ent.is_npc and ent.is_alive]
        if npc_tasks: asyncio.gather(*npc_tasks) 

        await asyncio.sleep(30) 
        
        if node.active_engine and node.active_engine.active:
            node.active_engine.active = await node.active_engine.resolve_turn()
            if node.active_engine.active: await asyncio.sleep(2)

    if node.active_engine: 
        winners = [e.name for e in node.active_engine.entities.values() if e.is_alive and not e.is_npc]
        losers = [e.name for e in node.active_engine.entities.values() if not e.is_alive and not e.is_npc]
        if winners and losers:
            await node.db.record_match_result(winners[0], losers[0], node.net_name)
            
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner('MATCH CONCLUDED.')}")
        node.active_engine = None
    
    await check_match_start(node)
