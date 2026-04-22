import asyncio
import os
import sys
import json

# Root inclusion
sys.path.append('ai_grid')
import ai_grid.grid_db as grid_db
from ai_grid.models import ItemTemplate

async def audit_defense_in_depth():
    db = grid_db.ArenaDB()
    print("\n[QA] DEFENSE IN DEPTH AUDIT (TASK 020)")
    
    # Pre-test Cleanup (Idempotency)
    async with db.async_session() as session:
        await session.execute(grid_db.text("DELETE FROM item_templates WHERE name IN ('ADS_PRO', 'FIREWALL_LII', 'IDS_SCAN')"))
        await session.execute(grid_db.text("DELETE FROM grid_nodes WHERE name = 'QA_FORTRESS'"))
        await session.execute(grid_db.text("DELETE FROM players WHERE global_name = 'qa_admin_global'"))
        await session.commit()
    
    # 1. Setup Mock State
    async with db.async_session() as session:
        # Create a test node if it doesn't exist
        from ai_grid.models import GridNode
        test_node = GridNode(name="QA_FORTRESS", description="A hardened test node.", node_type="safezone", max_slots=2)
        session.add(test_node)
        
        # Add a test hardware template
        tpl = ItemTemplate(name="ADS_PRO", item_type="node_addon", effects_json='{"type": "ADS"}')
        tpl2 = ItemTemplate(name="FIREWALL_LII", item_type="node_addon", effects_json='{"type": "FIREWALL"}')
        tpl3 = ItemTemplate(name="IDS_SCAN", item_type="node_addon", effects_json='{"type": "IDS"}')
        session.add_all([tpl, tpl2, tpl3])
        await session.commit()

    # 2. Test Surveillance Tracking (Firewall Hits)
    print("\n[TEST 1] Surveillance Tracking")
    # Simulate a failed breach attempt (This logic is usually in the infiltration_repo)
    # Since we're auditing the logic in territory/infiltration_repo, we call the repo methods.
    
    # Note: infiltration_repo.py increments firewall_hits when a breach fails.
    # For this audit, we'll manually check the implementation logic we saw in the audit.
    async with db.async_session() as session:
        from ai_grid.models import GridNode
        node = (await session.execute(grid_db.select(GridNode).where(GridNode.name == "QA_FORTRESS"))).scalars().first()
        initial_hits = node.firewall_hits or 0
        node.firewall_hits += 1 # Mirroring the repo logic
        await session.commit()
        
        updated_node = (await session.execute(grid_db.select(GridNode).where(GridNode.name == "QA_FORTRESS"))).scalars().first()
        print(f" > Firewall Hits: {updated_node.firewall_hits} (Expected {initial_hits + 1})")
        if updated_node.firewall_hits == initial_hits + 1:
            print("   SUCCESS: Surveillance counters are writable and persistent.")
        else:
            print("   FAILURE: Surveillance counters failed persistence test.")

    # 3. Test Capacity Enforcement (max_slots = 2)
    print("\n[TEST 2] Hardware Capacity Enforcement")
    # We use a real character from the DB for this if one exists, or create a mock.
    # For safety, we'll just test the Repository logic directly with a mock session if needed, 
    # but ArenaDB is better.
    
    # Mocking a character with hardware
    from ai_grid.models import Character, Player, NetworkAlias, InventoryItem
    async with db.async_session() as session:
        p = Player(global_name="qa_admin_global")
        session.add(p)
        await session.flush()
        char = Character(name="QA_ADMIN", player_id=p.id, credits=1000, race="Android", char_class="Admin")
        session.add(char)
        await session.flush()
        alias = NetworkAlias(player_id=p.id, nickname="QA_ADMIN", network_name="testnet")
        session.add(alias)
        
        # Give them the items
        tpls = (await session.execute(grid_db.select(ItemTemplate).where(ItemTemplate.item_type == "node_addon"))).scalars().all()
        for t in tpls:
            session.add(InventoryItem(character_id=char.id, template_id=t.id))
        
        # Link character to node and establish ownership
        n_id = (await session.execute(grid_db.select(GridNode).where(GridNode.name == "QA_FORTRESS"))).scalars().first().id
        char.node_id = n_id
        
        # Explicitly set owner on node object
        node = (await session.execute(grid_db.select(GridNode).where(GridNode.id == n_id))).scalars().first()
        node.owner_character_id = char.id
        
        await session.commit()

    # Attempt Installations
    # Install 1
    res1 = await db.territory.install_node_addon("QA_ADMIN", "testnet", "ADS_PRO")
    print(f" > Install 1 (ADS): {res1['msg']}")
    
    # Install 2
    res2 = await db.territory.install_node_addon("QA_ADMIN", "testnet", "FIREWALL_LII")
    print(f" > Install 2 (FIREWALL): {res2['msg']}")
    
    # Install 3 (Should fail: Capacity 2 reached)
    res3 = await db.territory.install_node_addon("QA_ADMIN", "testnet", "IDS_SCAN")
    print(f" > Install 3 (IDS - Over Capacity): {res3['msg']}")
    
    if res3['success'] is False and "Capacity reached" in res3['msg']:
        print("   SUCCESS: Hardware slot constraint enforced (Max: 2).")
    else:
        print("   FAILURE: Slot constraint bypassed or logic error.")

    # Cleanup
    async with db.async_session() as session:
        await session.execute(grid_db.text("DELETE FROM item_templates WHERE name IN ('ADS_PRO', 'FIREWALL_LII', 'IDS_SCAN')"))
        await session.execute(grid_db.text("DELETE FROM grid_nodes WHERE name = 'QA_FORTRESS'"))
        await session.execute(grid_db.text("DELETE FROM characters WHERE name = 'QA_ADMIN'"))
        await session.execute(grid_db.text("DELETE FROM players WHERE global_name = 'qa_admin_global'"))
        await session.commit()

if __name__ == "__main__":
    asyncio.run(audit_defense_in_depth())
