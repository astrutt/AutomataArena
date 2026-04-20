import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

# Add root dir to path
# __file__ is ai_grid/scratch/test_remote_coordination.py
# parent is ai_grid/scratch
# parent of parent is ai_grid
# parent of parent of parent is the root
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "ai_grid"))

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, PulseEvent, IncursionEvent

async def verify_task_045():
    db = ArenaDB()
    nick = "PresenceTester"
    network = "rizon"
    
    print("[*] Initializing Remote Coordination Test...")
    
    async with db.async_session() as session:
        # 1. Setup Environment
        # Find two nodes
        stmt = select(GridNode).limit(2)
        nodes = (await session.execute(stmt)).scalars().all()
        if len(nodes) < 2:
            print("[!] Not enough nodes for test. Skipping.")
            return
            
        hub_node = nodes[0]
        remote_node = nodes[1]
        
        # Ensure they are on the same network for event testing
        remote_node.net_affinity = network
        hub_node.net_affinity = network
        
        # Ensure character exists
        char = await db.identity.get_character_by_nick(nick, network, session)
        if not char:
            await db.identity.register_player(nick, network, "Human", "Tester", "Bio", {"cpu": 5, "ram": 5, "bnd": 5, "sec": 5, "alg": 5})
            char = await db.identity.get_character_by_nick(nick, network, session)
            
        # Place player at Hub Node
        char.node_id = hub_node.id
        # Give enough resources
        char.credits = 5000.0
        char.power = 1000.0
        
        # Damage Remote Node
        remote_node.durability = 50.0
        remote_node.owner_character_id = char.id # Own it for repair test
        hub_node.owner_character_id = None # Hub is unclaimed
        
        # Clear existing pulses/incursions on Remote Node for clean test
        from sqlalchemy import delete
        await session.execute(delete(PulseEvent).where(PulseEvent.node_id == remote_node.id))
        await session.execute(delete(IncursionEvent).where(IncursionEvent.node_id == remote_node.id))
        
        await session.commit()
        
        print(f"[*] Player: {nick} @ {hub_node.name}")
        print(f"[*] Target: {remote_node.name} (Remote)")

    # 2. Test Remote Repair
    print(f"\n[1] Testing Remote Repair on {remote_node.name}...")
    success, msg = await db.grid.grid_repair(nick, network, node_name=remote_node.name)
    print(f"    Result: {'SUCCESS' if success else 'FAIL'} | Msg: {msg}")
    
    # 3. Test Presence Enforcement (Claim)
    print(f"\n[2] Testing Presence Enforcement (Local Claim)...")
    success, msg = await db.grid.claim_node(nick, network)
    print(f"    Claim Local Hub Result: {'SUCCESS' if success else 'FAIL'} | Msg: {msg}")
    
    # Remote Claim (Physical presence required)
    print(f"\n[2b] Testing Presence Enforcement (Remote Claim)...")
    success, msg = await db.grid.claim_node(nick, network, node_name=remote_node.name)
    print(f"    Claim Remote Result: {'SUCCESS' if success else 'FAIL'} | Msg: {msg}")
    
    # Now let's try to upgrade hub_node (physical presence required, player is THERE)
    print(f"\n[3] Testing Presence Enforcement for Upgrade (Local)...")
    success, msg = await db.grid.upgrade_node(nick, network)
    print(f"    Upgrade Local Hub Result: {'SUCCESS' if success else 'FAIL'} | Msg: {msg}")

    # 4. Test Remote Pulse (Patch)
    print(f"\n[4] Testing Remote Patching...")
    async with db.async_session() as session:
        # Spawn a Glitch pulse at the remote node
        expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
        pulse = PulseEvent(node_id=remote_node.id, network_name=network, event_type='GLITCH', reward_val=100, expires_at=expiry, status='ACTIVE')
        session.add(pulse)
        await session.commit()
        
    success, msg = await db.pulse.resolve_pulse(nick, network, remote_node.name, "patch")
    print(f"    Remote Patch Result: {'SUCCESS' if success else 'FAIL'} | Msg: {msg}")

    # 5. Test Remote Incursion (Defend)
    print(f"\n[5] Testing Remote Defense...")
    async with db.async_session() as session:
        # Spawn an Incursion at the remote node
        expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
        inc = IncursionEvent(node_id=remote_node.id, network_name=network, incursion_type='RAID', tier=1, reward_val=100, expires_at=expiry, status='ACTIVE')
        session.add(inc)
        await session.commit()
        
    success, msg, victors = await db.incursion.register_defense(nick, network, remote_node.name)
    print(f"    Remote Defend Result: {'SUCCESS' if success else 'FAIL'} | Msg: {msg}")

    await db.close()
    print("\n[*] Remote Coordination Verification Complete.")

if __name__ == "__main__":
    asyncio.run(verify_task_045())
