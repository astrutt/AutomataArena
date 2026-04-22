import asyncio
import sys
from datetime import datetime, timedelta, timezone

# Root inclusion
sys.path.append('ai_grid')
import ai_grid.grid_db as grid_db
from ai_grid.models import PulseEvent, GridNode, Character, Player, NetworkAlias

async def audit_pulse_functional():
    db = grid_db.ArenaDB()
    print("\n[QA] PULSE FUNCTIONAL AUDIT (TASK 022)")
    
    # Pre-test Cleanup
    async with db.async_session() as session:
        await session.execute(grid_db.text("DELETE FROM pulse_events"))
        await session.execute(grid_db.text("DELETE FROM players WHERE global_name = 'qa_pulse_admin'"))
        await session.commit()

    async with db.async_session() as session:
        # 1. Setup Environment
        # Use an expansion node that has 'localnet' affinity
        node_stmt = grid_db.select(GridNode).where(GridNode.net_affinity == "localnet").limit(1)
        node = (await session.execute(node_stmt)).scalars().first()
        if not node:
            # Fallback/Seed for test
            node = (await session.execute(grid_db.select(GridNode).where(GridNode.name == "UpLink"))).scalars().first()
            node.net_affinity = "localnet"
            await session.commit()

        p = Player(global_name="qa_pulse_admin")
        session.add(p)
        await session.flush()
        
        char = Character(name="QA_PULSE_BOT", player_id=p.id, power=100.0, credits=0.0, node_id=node.id, race="Ghost", char_class="Admin")
        session.add(char)
        alias = NetworkAlias(player_id=p.id, nickname="QA_PULSE_BOT", network_name="localnet")
        session.add(alias)
        
        # 2. Manifest Pulse (PACKET)
        expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
        pulse = PulseEvent(node_id=node.id, network_name="localnet", event_type="PACKET", reward_val=250.0, expires_at=expiry, status='ACTIVE')
        session.add(pulse)
        await session.commit()
    
    # 3. Test Resolution
    print(" > Attempting 'collect' at UpLink (Target: PACKET)...")
    success1, msg1 = await db.pulse.resolve_pulse("QA_PULSE_BOT", "localnet", "UpLink", "collect")
    if success1:
        print(f"   SUCCESS: {msg1}")
    else:
        print(f"   FAILURE: {msg1}")
        
    # 4. Verification Check
    async with db.async_session() as session:
        char_v = (await session.execute(grid_db.select(Character).where(Character.name == "QA_PULSE_BOT"))).scalars().first()
        pulse_v = (await session.execute(grid_db.select(PulseEvent))).scalars().first()
        
        if char_v.credits == 250.0 and pulse_v.status == 'RESOLVED':
            print(" > Verification: Credits awarded and Status updated. PASS.")
        else:
            print(f" > Verification: FAILED. Credits={char_v.credits}, Status={pulse_v.status}")

    print("\n[TEST 2] Invalid Action Gating")
    # Manifest GLITCH
    async with db.async_session() as session:
        pulse_v.status = 'ACTIVE'
        pulse_v.event_type = 'GLITCH'
        await session.commit()
        
    print(" > Attempting 'collect' at UpLink (Target: GLITCH)...")
    success2, msg2 = await db.pulse.resolve_pulse("QA_PULSE_BOT", "localnet", "UpLink", "collect")
    if not success2:
        print(f"   SUCCESS: Gating confirmed. {msg2}")
    else:
        print(f"   FAILURE: collect allowed on GLITCH!")

if __name__ == "__main__":
    asyncio.run(audit_pulse_functional())
