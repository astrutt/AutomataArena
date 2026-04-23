import asyncio
import sys
import os
from sqlalchemy import select
from datetime import datetime, timezone

# Add root to path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, Player, NetworkAlias, GridNode, RaidTarget, DiscoveryRecord

async def test_target_intel_isolation():
    print("[*] Starting Target Intelligence Isolation Audit (Task 065)...")
    db = ArenaDB()
    
    async with db.async_session() as session:
        # 1. Setup Test Data
        char = await db.character.get_player("Antigravity", "2600net")
        if not char:
            print("[!] Character not found, skipping deep repo test.")
            return

        # Ensure node is explored
        await db.discovery.explore_node("Antigravity", "2600net")
        
        # Create a raid target
        node_id = char['current_node_id']
        target = RaidTarget(node_id=node_id, name="[QA_TARGET]", target_type="SMB", difficulty=15)
        session.add(target)
        await session.commit()
        await session.refresh(target)
        
        print(f"[1] Target created: {target.name} (ID: {target.id})")

        # 2. Probe the target
        print("[2] Probing target...")
        res = await db.discovery.probe_node("Antigravity", "2600net", target_name="[QA_TARGET]")
        if res['success']:
            print(f" | Probe Success: {res['name']}")
        else:
            print(f" | Probe Fail: {res['error']}")
            return

        # 3. Verify DiscoveryRecord
        print("[3] Verifying DiscoveryRecords...")
        stmt = select(DiscoveryRecord).where(DiscoveryRecord.character_id == char['id'], DiscoveryRecord.node_id == node_id)
        records = (await session.execute(stmt)).scalars().all()
        
        target_records = [r for r in records if r.raid_target_id == target.id]
        node_records = [r for r in records if r.raid_target_id == None]
        
        print(f" | Target Records: {len(target_records)} (Level: {target_records[0].intel_level if target_records else 'N/A'})")
        print(f" | Node Records: {len(node_records)} (Level: {node_records[0].intel_level if node_records else 'N/A'})")
        
        if len(target_records) == 1 and target_records[0].intel_level == 'PROBE':
            print(" | Result: [✅] Target Intel Isolated: PASS")
        else:
            print(" | Result: [❌] Target Intel Missing or Conflict: FAIL")

    await db.close()

if __name__ == "__main__":
    asyncio.run(test_target_intel_isolation())
