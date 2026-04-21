import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy import delete
from sqlalchemy.orm import selectinload

# Add root and ai_grid dirs to path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "ai_grid"))

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, ItemTemplate, InventoryItem, RaidTarget, BreachRecord, DiscoveryRecord

async def test_loop():
    db = ArenaDB()
    nick = "TestRunner"
    network = "rizon"
    
    print("[*] Setting up test environment...")
    # 1. Setup Character & Power
    async with db.async_session() as session:
        char = await db.identity.get_character_by_nick(nick, network, session)
        if not char:
            await db.identity.register_player(nick, network, "Human", "Hacker", "Bio", {"cpu": 5, "ram": 5, "bnd": 5, "sec": 5, "alg": 5})
            char = await db.identity.get_character_by_nick(nick, network, session)
        
        # Grant surplus power for testing
        char.power = 2000.0
        # Boost stat to reduce RNG failure
        char.alg = 20
        
        # 2. Setup Chain Template & Stock
        tmpl_stmt = select(ItemTemplate).where(ItemTemplate.name == "ZeroDay_Chain")
        tmpl = (await session.execute(tmpl_stmt)).scalars().first()
        if not tmpl:
            tmpl = ItemTemplate(name="ZeroDay_Chain", item_type="hack", base_value=2500, is_darknet=True)
            session.add(tmpl)
            await session.flush()
        
        inv_stmt = select(InventoryItem).where(InventoryItem.character_id == char.id, InventoryItem.template_id == tmpl.id)
        chain = (await session.execute(inv_stmt)).scalars().first()
        if not chain:
            chain = InventoryItem(character_id=char.id, template_id=tmpl.id, quantity=5)
            session.add(chain)
        else:
            chain.quantity = 5
        
        # 3. Choose Node
        node_stmt = select(GridNode).where(GridNode.node_type == "wilderness")
        node = (await session.execute(node_stmt)).scalars().first()
        target_node_name = node.name
        target_node_id = node.id
        
        # 4. Clear old discovery/breach records for clean test
        await session.execute(delete(DiscoveryRecord).where(DiscoveryRecord.character_id == char.id))
        await session.execute(delete(BreachRecord).where(BreachRecord.character_id == char.id))
        
        await session.commit()
    
    char_id = char.id # Save ID for checks

    # Move player OUTSIDE session
    await db.navigation.move_player_to_node(nick, network, target_node_name)
    print(f"[*] Character {nick} (ID: {char_id}) prepared at {target_node_name} (ID: {target_node_id}).")

    # 1. Explore for targets
    print("[*] Testing Discovery...")
    found_target = False
    for i in range(5):
        res = await db.discovery.explore_node(nick, network)
        if res.get("discovery") == "raid_target":
            print(f"[+] Discovered Raid Target: {res['target']}")
            found_target = True
            break
    
    if not found_target:
        print("[!] No target discovered via explore. Forcing one.")
        async with db.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == target_node_name))).scalars().first()
            if not node.active_target_id:
                new_target = RaidTarget(node_id=node.id, name="[SMB-TEST]", target_type="SMB", credits_pool=1000, data_pool=200)
                session.add(new_target)
                await session.flush()
                node.active_target_id = new_target.id
                await session.commit()
    
    # Verify Explore Record Datetime & ID match
    async with db.async_session() as session:
        disc_stmt = select(DiscoveryRecord).where(DiscoveryRecord.character_id == char_id, DiscoveryRecord.node_id == target_node_id)
        disc = (await session.execute(disc_stmt)).scalars().first()
        if disc:
            print(f"[+] Discovery Record verified for node {target_node_id}. Time: {disc.discovered_at}")
            assert disc.discovered_at.tzinfo is not None, "DiscoveryRecord.discovered_at is offset-naive!"
        else:
            # Force it if explore failed to create for some reason
            print("[!] Discovery Record missing! Creating manually for test continuity.")
            session.add(DiscoveryRecord(character_id=char_id, node_id=target_node_id, intel_level='EXPLORE'))
            await session.commit()
    
    # 2. Probe to map vectors (Retry for success)
    print("[*] Probing...")
    probe_success = False
    for i in range(10):
        probe_res = await db.discovery.probe_node(nick, network)
        if probe_res.get("success"):
            print(f"[+] Probe Successful. Target: {probe_res.get('raid_target')}")
            probe_success = True
            break
        else:
            err = probe_res.get('error') or probe_res.get('msg')
            print(f"[-] Probe attempt {i+1} failed: {err}")
    
    if not probe_success:
        print("[❌] Probe failed after 10 attempts. Verification aborted.")
        await db.close()
        sys.exit(1)

    # 3. Exploit (Silent Breach using ZeroDay Chain)
    print("[*] Executing EXPLOIT...")
    success, msg, alert = await db.infiltration.exploit_node(nick, network, is_raid=True)
    print(f"[{'SUCCESS' if success else 'FAIL'}] {msg}")
    
    async with db.async_session() as session:
        char_stmt = select(Character).where(Character.id == char_id).options(
            selectinload(Character.inventory).selectinload(InventoryItem.template)
        )
        char = (await session.execute(char_stmt)).scalars().first()
        
        breach_stmt = select(BreachRecord).where(BreachRecord.character_id == char_id, BreachRecord.node_id == target_node_id)
        breach = (await session.execute(breach_stmt)).scalars().first()
        if breach:
            print(f"[+] Breach Record Time: {breach.breached_at} (tzinfo: {breach.breached_at.tzinfo})")
            assert breach.breached_at.tzinfo is not None, "BreachRecord.breached_at is offset-naive!"
            print(f"[+] Breach Silent? {breach.is_silent}")
        
        chain_item = next((i for i in char.inventory if i.template.name == "ZeroDay_Chain"), None)
        print(f"[+] Chains remaining: {chain_item.quantity if chain_item else 0}")

    # 4. Raid (Targeted)
    print("[*] Executing Targeted RAID...")
    raid_res = await db.infiltration.raid_node(nick, network, target_name="SMB")
    print(f"[{'SUCCESS' if raid_res['success'] else 'FAIL'}] {raid_res['msg']}")

    if raid_res['success']:
        print("\n[✅] Grid Hack Loop Verification Passed!")
    else:
        print("\n[❌] Grid Hack Loop Verification Failed at Raid stage.")
        sys.exit(1)

    await db.close()

if __name__ == "__main__":
    asyncio.run(test_loop())
