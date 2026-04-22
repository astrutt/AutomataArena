import asyncio
import sys
from datetime import datetime, timedelta, timezone

# Root inclusion
sys.path.append('ai_grid')
import ai_grid.grid_db as grid_db
from ai_grid.models import PulseEvent, GridNode

async def audit_pulse_model():
    db = grid_db.ArenaDB()
    print("\n[QA] PULSE MODEL STRUCTURAL AUDIT (TASK 022)")
    
    async with db.async_session() as session:
        # 1. Setup Mock Node
        node = (await session.execute(grid_db.select(GridNode).limit(1))).scalars().first()
        if not node:
            print("FAILURE: No nodes found in database. Seed required.")
            return
            
        print(f" > Targeting Node: {node.name}")
        
        # 2. Test Insertion
        new_event = PulseEvent(
            node_id=node.id,
            network_name="localnet",
            event_type="PACKET",
            reward_val=50.0,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        session.add(new_event)
        await session.commit()
        
        print(f" > Event created: ID {new_event.id}")
        
        # 3. Test Retrieval & Relationship
        event = (await session.execute(grid_db.select(PulseEvent).where(PulseEvent.node_id == node.id))).scalars().first()
        if event and event.node.name == node.name:
            print(f"   SUCCESS: Model mapped to Node {event.node.name} successfully.")
        else:
            print("   FAILURE: Model mapping or relationship resolution failed.")

        # Cleanup
        await session.delete(event)
        await session.commit()
        print(" > Cleanup complete.")

if __name__ == "__main__":
    asyncio.run(audit_pulse_model())
