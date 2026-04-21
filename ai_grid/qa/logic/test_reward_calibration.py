import asyncio
import os
import sys
from sqlalchemy import delete, func
from sqlalchemy.future import select

# Add root and ai_grid dirs to path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "ai_grid"))

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, Player, NetworkAlias

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("manager")

async def test_reward_calibration():
    db = ArenaDB()
    network = "2600net"
    l1_nick = "CALIB_L1"
    l50_nick = "CALIB_L50"
    
    print("[*] Initializing Reward Calibration Audit (v1.8.3)...")

    async with db.async_session() as session:
        # 1. Setup L1 Character
        # Full wipe to avoid "already exists" errors
        for nick in [l1_nick, l50_nick]:
            char = await db.identity.get_character_by_nick(nick, network, session)
            if char:
                # Character delete cascades to Inventory, but we should clear aliases/player if needed
                # Actually register_player handles Player creation.
                player_id = char.player_id
                await session.delete(char)
                from models import NetworkAlias, Player
                await session.execute(delete(NetworkAlias).where(NetworkAlias.player_id == player_id))
                await session.execute(delete(Player).where(Player.id == player_id))
        await session.commit()

    async with db.async_session() as session:
        await db.identity.register_player(l1_nick, network, "Bot", "Hacker", "Digital", {"cpu": 1, "ram": 1, "bnd": 1, "sec": 1, "alg": 1})
        l1 = await db.identity.get_character_by_nick(l1_nick, network, session)
        l1.level = 1
        l1.xp = 0
        l1.credits = 0.0
        l1.data_units = 0.0
        
        # 2. Setup L50 Character
        await db.identity.register_player(l50_nick, network, "Bot", "Hacker", "Digital", {"cpu": 1, "ram": 1, "bnd": 1, "sec": 1, "alg": 1})
        l50 = await db.identity.get_character_by_nick(l50_nick, network, session)
        l50.level = 50
        l50.xp = 0
        l50.credits = 0.0
        l50.data_units = 0.0
        
        # 3. Setup Test Node
        node = (await session.execute(select(GridNode).where(GridNode.name == 'CALIB_NODE'))).scalars().first()
        if not node:
            node = GridNode(name='CALIB_NODE', node_type='wilderness', upgrade_level=1, durability=50.0, net_affinity=network)
            session.add(node)
        node.durability = 50.0 # reset for repair test
        
        # Ensure characters are NOT at the node for Task 045 test
        l1.node_id = 0
        l50.node_id = 0
        
        await session.commit()

    print(f"[+] Profiles Ready. L1: {l1_nick}, L50: {l50_nick}. Target: CALIB_NODE")

    # --- PHASE 1: L1 Scaling Audit ---
    print("\n[*] Auditing Level 1 Scaling (Spec: 4 actions to level)...")
    for i in range(1, 5):
        success, msg = await db.territory.grid_repair(l1_nick, network, node_name="CALIB_NODE")
        print(f"  > Action {i}: {msg}")
        assert success, f"Action {i} failed!"

    async with db.async_session() as session:
        l1 = await db.identity.get_character_by_nick(l1_nick, network, session)
        print(f"  [RESULT] L1 FINAL: Level {l1.level}, XP {l1.xp}, Credits {l1.credits}c, Data {l1.data_units}")
        assert l1.level == 2, f"Level 1 failed to level up in 4 actions. Current Level: {l1.level}"
        # XP per action should be 25. Threshold was 100. 25 * 4 = 100. XP should be 0 (or carry over).
        assert l1.credits == 200.0, "Credits scaling incorrect at L1. Expected 50 * 1 * 4 = 200."
        assert l1.data_units > 0, "Data rewards missing at L1."

    # --- PHASE 2: L50 Scaling Audit ---
    async with db.async_session() as session:
        l50_pre = await db.identity.get_character_by_nick(l50_nick, network, session)
        print(f"\n[*] Pre-Audit Level Check: {l50_nick} is Level {l50_pre.level}")
        assert l50_pre.level == 50, "Failed to initialize L50 correctly."

    print("\n[*] Auditing Level 50 Scaling (Spec: 100 actions to level)...")
    # We'll just do 1 action and check progress
    success, msg = await db.territory.grid_repair(l50_nick, network, node_name="CALIB_NODE")
    print(f"  > Action 1: {msg}")
    assert success, "L50 action failed!"

    async with db.async_session() as session:
        l50 = await db.identity.get_character_by_nick(l50_nick, network, session)
        # Threshold for L50 is 100 * (1.25^49) = 7,006,492
        # Divisor is 100.0
        # Expected XP = 7,006,492 / 100 = 70,064
        expected_xp = 70064
        print(f"  [RESULT] L50 Action 1: XP {l50.xp}")
        # Allow small rounding margin if necessary, but integer math should be close
        assert 70000 < l50.xp < 71000, f"L50 XP gain ({l50.xp}) does not meet 1/100 threshold spec (~{expected_xp})."
        
        # Exponential Data check: base_data=10 * (1.25^49) = 10 * 70064 = 700,649
        print(f"  [RESULT] L50 Data: {l50.data_units}")
        assert l50.data_units > 100000, "Exponential Data scaling failed or remained linear."

    # --- PHASE 3: Presence Audit (Task 045) ---
    print("\n[*] Auditing Remote Interaction (Task 045)...")
    # Already verified by success in Phase 1/2 (chars were at node_id 0)
    print("  [RESULT] SUCCESS: Repair protocol executed from remote coordinate.")

    print("\n[✅] Reward Calibration Audit Passed!")
    await db.close()

if __name__ == "__main__":
    asyncio.run(test_reward_calibration())
