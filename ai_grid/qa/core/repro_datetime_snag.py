import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy import update
from sqlalchemy.orm import selectinload

# Add root and ai_grid dirs to path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "ai_grid"))

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, RaidTarget, DiscoveryRecord, BreachRecord

async def test_datetime_snag():
    db = ArenaDB()
    nick = "TestRunner"
    network = "rizon"
    
    print("[*] Setting up datetime regression test...")
    async with db.async_session() as session:
        # Ensure test character exists
        char = await db.identity.get_character_by_nick(nick, network, session)
        if not char:
            await db.identity.register_player(nick, network, "Human", "Hacker", "Bio", {"cpu": 5, "ram": 5, "bnd": 5, "sec": 5, "alg": 5})
            char = await db.identity.get_character_by_nick(nick, network, session)
        
        # Ensure we are on a node with a raid target
        node_stmt = select(GridNode).where(GridNode.node_type == "void").options(selectinload(GridNode.active_target))
        node = (await session.execute(node_stmt)).scalars().first()
        char.node_id = node.id
        
        # Ensure raid target exists
        if not node.active_target_id:
            new_target = RaidTarget(node_id=node.id, name="[SMB-DATE-TEST]", target_type="SMB", credits_pool=1000, data_pool=200)
            session.add(new_target)
            await session.flush()
            node.active_target_id = new_target.id
        
        raid_target = node.active_target
        # FORCE naive datetime (simulating existing DB state or SQLAlchemy reload)
        # We manually set it to something naive and old
        raid_target.last_raided_at = datetime.utcnow() - timedelta(hours=2)
        
        # Ensure Discovery and Breach are valid (to bypass checks)
        disc_stmt = select(DiscoveryRecord).where(DiscoveryRecord.character_id == char.id, DiscoveryRecord.node_id == node.id)
        disc = (await session.execute(disc_stmt)).scalars().first()
        if not disc:
            session.add(DiscoveryRecord(character_id=char.id, node_id=node.id, intel_level='PROBE', discovered_at=datetime.utcnow()))
        else:
            disc.intel_level = 'PROBE'
            disc.discovered_at = datetime.utcnow()
            
        breach_stmt = select(BreachRecord).where(BreachRecord.character_id == char.id, BreachRecord.node_id == node.id)
        breach = (await session.execute(breach_stmt)).scalars().first()
        if not breach:
            session.add(BreachRecord(character_id=char.id, node_id=node.id, breached_at=datetime.utcnow()))
        else:
            breach.breached_at = datetime.utcnow()

        await session.commit()
    
    print(f"[*] Testing RAID with naive last_raided_at: {raid_target.last_raided_at}")
    try:
        raid_res = await db.infiltration.raid_node(nick, network, target_name="SMB")
        print(f"[+] RAID Result Status: {raid_res['success']}")
        print(f"[+] RAID Message: {raid_res['msg']}")
        if raid_res['success']:
            print("[✅] Datetime comparison succeeded!")
        else:
            print("[❌] RAID failed but check if it was a TypeError or just logic.")
    except TypeError as e:
        print(f"[❌] Regression Detected! TypeError: {e}")
    except Exception as e:
        print(f"[❓] Unexpected Error: {e}")
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(test_datetime_snag())
