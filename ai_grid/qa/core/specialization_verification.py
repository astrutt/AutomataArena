import asyncio
import os
import sys
import json
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

# Fix PYTHONPATH locally to ensure we can import the project structure
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
AI_GRID_DIR = os.path.join(ROOT_DIR, 'ai_grid')
sys.path.append(ROOT_DIR)
sys.path.append(AI_GRID_DIR)

# Note: We need to set PYTHONPATH in the environment or ensure imports resolve.
# Since the developer hasn't fixed the 'from models' imports to relative 'from ..models',
# we must ensure 'ai_grid' is in the path so 'import models' works.

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, DiscoveryRecord, BreachRecord, Memo
from ai_grid.core.map_utils import generate_ascii_map

TEST_DB = "specialization_test.db"

async def setup_test_db():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db = ArenaDB(db_path=TEST_DB)
    await db.init_schema()
    await db.seed_grid_expansion()
    # Manual Seed for consistent testing
    async with db.async_session() as session:
        # Create Owner
        await db.register_player("Operator", "testnet", "Daemon", "Infiltrator", "Owner Bio", {"cpu":10,"ram":10,"bnd":10,"sec":10,"alg":10})
        # Create Attacker (High ALG)
        await db.register_player("Attacker", "testnet", "Ghost", "Hacker", "Attacker Bio", {"cpu":5,"ram":5,"bnd":5,"sec":5,"alg":20})
        await session.commit()
    return db

async def verify_amp_logic(db):
    print("\n[TEST 1] AMP Power Scaling")
    async with db.async_session() as session:
        # 1. Setup a node with AMP
        node = (await session.execute(GridNode.__table__.select().where(GridNode.name == "Neural_Nexus"))).first()
        owner = await db.get_character_by_nick("Operator", "testnet", session)
        
        # Claim and add AMP
        await session.execute(GridNode.__table__.update().where(GridNode.name == "Neural_Nexus").values(
            owner_character_id=owner.id,
            addons_json=json.dumps({"AMP": True}),
            power_stored=100.0
        ))
        await session.commit()
        
        # 2. Tick power
        await db.tick_grid_power()
        
        # 3. Check yields
        # Baseline = 5.0 (occupancy) or 1.0 (passive)
        # With AMP = 10.0 or 2.0
        
        # Move owner there to test occupancy boost
        await db.move_player_to_node("Operator", "testnet", "Neural_Nexus")
        await db.tick_grid_power()
        
        updated_node = (await session.execute(GridNode.__table__.select().where(GridNode.name == "Neural_Nexus"))).first()
        gen = updated_node.power_generated
        print(f"Power Generated with AMP: {gen}")
        
        if gen >= 10.0:
            print("SUCCESS: AMP multiplier (2.0x) applied correctly.")
            return True
        else:
            print("FAILURE: AMP multiplier not detected.")
            return False

async def verify_firewall_and_alerts(db):
    print("\n[TEST 2] FIREWALL DC & IDS Alerts")
    async with db.async_session() as session:
        # 1. Setup node with FIREWALL and IDS
        await session.execute(GridNode.__table__.update().where(GridNode.name == "Kernel_Deep").values(
            owner_character_id=1, # Operator
            addons_json=json.dumps({"FIREWALL": True, "IDS": True}),
            availability_mode='CLOSED',
            upgrade_level=2
        ))
        await session.commit()
        
        # 2. Move Attacker to Kernel_Deep
        await db.move_player_to_node("Attacker", "testnet", "Kernel_Deep")
        
        # 3. Test Hack DC scaling (Manual check via logic or running command)
        # We can't easily assert the internal DC without a return but we can check the alert
        print("Executing Hack attempt on IDS/FIREWALL node...")
        success, msg, alert_data = await db.hack_node("Attacker", "testnet")
        print(f"Hack Result: {msg}")
        
        # 4. Check for Alert Memo
        memos = (await session.execute(select(Memo).where(Memo.recipient_id == 1))).scalars().all()
        print(f"Memos found for Owner: {len(memos)}")
        for m in memos: print(f"  > {m.message}")
        
        if any("[GRID][ALARM]" in m.message for m in memos):
            print("SUCCESS: IDS/FIREWALL alert triggered and logged.")
            return True
        else:
            print("FAILURE: No alert record found.")
            return False

async def verify_net_requirement(db):
    print("\n[TEST 3] NET Raid Prerequisite")
    async with db.async_session() as session:
        # 1. Setup node WITHOUT NET
        await session.execute(GridNode.__table__.update().where(GridNode.name == "Memory_Heap").values(
            owner_character_id=1,
            addons_json=json.dumps({"IDS": True}), # Only IDS
            availability_mode='OPEN'
        ))
        await session.commit()
        
        await db.move_player_to_node("Attacker", "testnet", "Memory_Heap")
        
        # 2. Attempt RAID
        # raid_node is called via command but we can call it directly in DB
        result = await db.raid_node("Attacker", "testnet")
        print(f"Raid Result: {result.get('msg')}")
        
        if "NET" in result.get('msg', ''):
            print("SUCCESS: RAID correctly blocked without NET addon.")
            return True
        else:
            print("FAILURE: RAID allowed without NET hardware.")
            return False

async def run_all_tests():
    db = await setup_test_db()
    results = []
    
    results.append(await verify_amp_logic(db))
    results.append(await verify_firewall_and_alerts(db))
    results.append(await verify_net_requirement(db))
    
    print("\n" + "="*40)
    print(f"VERIFICATION COMPLETE: {sum(results)}/{len(results)} PASSED")
    print("="*40)
    
    await db.close()
    if os.path.exists(TEST_DB): os.remove(TEST_DB)

if __name__ == "__main__":
    asyncio.run(run_all_tests())
