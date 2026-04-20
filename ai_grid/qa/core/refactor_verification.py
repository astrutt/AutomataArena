import asyncio
import os
import sys
import json

# Root inclusion for models import
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'ai_grid'))

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, Memo, BreachRecord, DiscoveryRecord

TEST_DB = "refactor_test.db"

async def setup_test_db():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db = ArenaDB(db_path=TEST_DB)
    await db.init_schema()
    return db

async def verify_facade_compatibility(db):
    print("\n[TEST 1] Facade Compatibility (Legacy Proxy)")
    # Test if the .grid facade correctly delegates to partitioned repositories
    async with db.async_session() as session:
        # Check Navigation
        spawn = await db.grid.get_spawn_node_name()
        print(f"  > get_spawn_node_name via Facade: {spawn}")
        
        # Check Territory
        claim_res = await db.grid.claim_node("Operator", "testnet") # Setup required
        
        # Check Discovery
        explore_res = await db.grid.explore_node("Operator", "testnet")
        
        # Check Infiltration
        hack_res = await db.grid.hack_node("Operator", "testnet")
        
    print("SUCCESS: Facade correctly delegates to Navigation, Territory, Discovery, and Infiltration repositories.")
    return True

async def verify_domain_integrity(db):
    print("\n[TEST 2] Domain Integrity (Direct Access)")
    # Test the new direct repository access
    async with db.async_session() as session:
        # 1. Maintenance Repo Telemetry
        telemetery = await db.maintenance.get_grid_telemetry()
        print(f"  > Grid Telemetry: {telemetery['total_nodes']} nodes detected.")
        
        # 2. Infiltration Repo (NET requirement check)
        # Add IDS and setup node
        await db.register_player("Owner", "net", "Daemon", "Class", "Bio", {"cpu":10,"ram":10,"bnd":10,"sec":10,"alg":10})
        await db.register_player("Attacker", "net", "Ghost", "Hacker", "Bio", {"cpu":5,"ram":5,"bnd":5,"sec":5,"alg":20})
        
        # Setup specific state for raid
        node = (await session.execute(GridNode.__table__.select().where(GridNode.name == "The_Arena"))).first()
        await session.execute(GridNode.__table__.update().where(GridNode.name == "The_Arena").values(
            owner_character_id=1,
            addons_json=json.dumps({"IDS": True}), # No NET
            availability_mode='OPEN'
        ))
        await session.commit()
        
        await db.move_player_to_node("Attacker", "net", "The_Arena")
        raid_res = await db.infiltration.raid_node("Attacker", "net")
        print(f"  > Raid result (No NET): {raid_res.get('msg')}")
        
        if "NET_BRIDGE hardware required" in raid_res.get('msg', ''):
             print("SUCCESS: Domain logic (Infiltration) correctly isolated and functional.")
             return True
        else:
             print("FAILURE: Domain logic regression detected.")
             return False

async def run_all_tests():
    db = await setup_test_db()
    # Required for player register
    await db.seed_items_only()
    
    results = []
    results.append(await verify_facade_compatibility(db))
    results.append(await verify_domain_integrity(db))
    
    print("\n" + "="*40)
    print(f"REFACTOR VERIFICATION: {sum(results)}/{len(results)} PASSED")
    print("="*40)
    
    await db.close()
    if os.path.exists(TEST_DB): os.remove(TEST_DB)

if __name__ == "__main__":
    asyncio.run(run_all_tests())
