import asyncio
import os
import sys
import json

# Root inclusion for models import
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'ai_grid'))

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, Memo, BreachRecord, DiscoveryRecord, ItemTemplate, InventoryItem

TEST_DB = "stability_audit.db"

async def setup_test_db():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    db = ArenaDB(db_path=TEST_DB)
    await db.init_schema()
    return db

async def audit_integration_flow(db):
    print("\n[STABILITY AUDIT] End-to-End Modular Flow")
    async with db.async_session() as session:
        # 1. Registration (PlayerRepo)
        await db.register_player("Auditor", "net", "Daemon", "QA", "Audit Bio", {"cpu":10,"ram":10,"bnd":10,"sec":10,"alg":10})
        await db.seed_items_only()
        
        # 2. Navigation & Territory (Claiming)
        await db.move_player_to_node("Auditor", "net", "The_CPU_Socket")
        await db.territory.claim_node("Auditor", "net")
        
        node = (await session.execute(GridNode.__table__.select().where(GridNode.name == "The_CPU_Socket"))).first()
        print(f"  > Node '{node.name}' claimed by character ID {node.owner_character_id}.")
        
        # 3. Economy (Merchant Transaction)
        # Move to Black_Market_Port (Merchant)
        await db.move_player_to_node("Auditor", "net", "Black_Market_Port")
        # Manually open it for the test
        await session.execute(GridNode.__table__.update().where(GridNode.name == "Black_Market_Port").values(availability_mode='OPEN'))
        await session.commit()
        
        # Add credits first
        await db.economy.award_credits("Auditor", "net", 5000)
        
        # Seed an AMP module template if missing (or use existing)
        amp_tpl = (await session.execute(ItemTemplate.__table__.select().where(ItemTemplate.name == "AMP_Module"))).first()
        if not amp_tpl:
            await session.execute(ItemTemplate.__table__.insert().values(name="AMP_Module", item_type="node_addon", base_value=1200, effects_json='{"type": "AMP"}'))
            await session.commit()
        
        print("  > Attempting purchase: AMP_Module")
        success, res = await db.economy.process_transaction("Auditor", "net", "buy", "AMP_Module")
        print(f"  > Purchase Result: {res}")
        
        # 4. Territory (Installation)
        await db.move_player_to_node("Auditor", "net", "The_CPU_Socket")
        install_res = await db.territory.install_node_addon("Auditor", "net", "AMP_Module")
        print(f"  > Installation Result: {install_res['msg']}")
        
        # 5. Maintenance (Yield Boost)
        # Verify durability first
        initial_node = (await session.execute(GridNode.__table__.select().where(GridNode.name == "The_CPU_Socket"))).first()
        print(f"  > Initial Power Stored: {initial_node.power_stored}")
        
        await db.maintenance.tick_grid_power()
        
        boosted_node = (await session.execute(GridNode.__table__.select().where(GridNode.name == "The_CPU_Socket"))).first()
        print(f"  > Power Stored after tick (with AMP): {boosted_node.power_stored}")
        
        # Yield check: claimed nodes get +1.0 * mult (passive) or +5.0 * mult (occupancy)
        # Auditor is present. Yield should be += 10.0
        if boosted_node.power_stored >= 110.0:
            print("SUCCESS: End-to-End Audit (Registration -> Claim -> Economy -> Territory -> Maintenance) PASSED.")
            return True
        else:
            print(f"FAILURE: Expected >= 110.0 uP, got {boosted_node.power_stored}")
            return False

async def run_audit():
    db = await setup_test_db()
    
    try:
        success = await audit_integration_flow(db)
        
        print("\n" + "="*40)
        print(f"STABILITY AUDIT: {'PASSED' if success else 'FAILED'}")
        print("="*40)
    finally:
        await db.close()
        if os.path.exists(TEST_DB): os.remove(TEST_DB)

if __name__ == "__main__":
    asyncio.run(run_audit())
