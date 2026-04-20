import asyncio
import datetime
import os
import sys
sys.path.append(os.path.join(os.getcwd(), 'ai_grid'))

from ai_grid.grid_db import ArenaDB
from models import Character, Player, NetworkAlias, GridNode
from sqlalchemy.future import select

async def verify_combat():
    db = ArenaDB()
    await db.init_schema()
    net = "test_net"
    
    # Mark spawn node as NOT safezone for testing attacks
    async with db.async_session() as session:
        stmt = select(GridNode).where(GridNode.is_spawn_node == True)
        node = (await session.execute(stmt)).scalars().first()
        if node:
            node.node_type = "sector"
            await session.commit()

    print("\n--- [1. HP FORMULA VERIFICATION] ---")
    # stats: all 5. Sum=25. HP = 25*4 + 10 = 110.
    stats = {'cpu': 5, 'ram': 5, 'bnd': 5, 'sec': 5, 'alg': 5}
    token = await db.register_player("CombatTest_Alice", net, "Human", "Hacker", "Ready.", stats)
    
    # Manually give Alice a stat point for testing since rank_up_stat requires points
    async with db.async_session() as session:
        stmt = select(Character).where(Character.name == "CombatTest_Alice")
        char_obj = (await session.execute(stmt)).scalars().first()
        char_obj.pending_stat_points = 5
        await session.commit()
    
    char = await db.player.get_player("CombatTest_Alice", net)
    print(f"Alice Initial HP: {char['current_hp']} (Expected: 110)")
    
    print("\nRanking up CPU...")
    await db.player.rank_up_stat("CombatTest_Alice", net, "cpu")
    char2 = await db.player.get_player("CombatTest_Alice", net)
    # CPU=6. Sum=26. HP = 26*4 + 10 = 114.
    print(f"Alice New HP: {char2['current_hp']} (Expected: 114)")

    print("\n--- [2. LEVEL-UP CURVE VERIFICATION] ---")
    # Lvl 1 -> 2: 100 * 1.25^0 = 100 XP
    # Lvl 2 -> 3: 100 * 1.25^1 = 125 XP
    res = await db.player.add_experience("CombatTest_Alice", net, 225)
    print(f"Alice Levels Gained: {res['levels_gained']} (Expected: 2)")
    print(f"Alice Current Level: {res['new_level']} (Expected: 3)")

    print("\n--- [3. UNIT POWER PERSISTENCE VERIFICATION] ---")
    # Seed Bob
    await db.register_player("CombatTest_Bob", net, "Human", "Warrior", "Ready.", stats)
    bob_before = await db.player.get_player("CombatTest_Bob", net)
    print(f"Bob Starting Power: {bob_before['power']}")
    
    # Record Match Result with final uP
    print("Recording match result: Alice wins, Bob surrenders. Alice uP: 85, Bob uP: 45.")
    await db.record_match_result("CombatTest_Alice", "CombatTest_Bob", net, was_surrender=True, winner_up=85.5, loser_up=45.0)
    
    alice_after = await db.player.get_player("CombatTest_Alice", net)
    bob_after = await db.player.get_player("CombatTest_Bob", net)
    
    print(f"Alice Final Power: {alice_after['power']} (Expected: 85.5)")
    print(f"Bob Final Power: {bob_after['power']} (Expected: 45.0)")
    
    print("\n--- [4. KINETIC DAMAGE FORMULA VERIFICATION] ---")
    # Alice CPU=6, RAM=5. Damage = 6*5 + 5 = 35. 
    # Bob SEC=5. Final = 35 - 5 = 30.
    success, msg, _ = await db.grid_attack("CombatTest_Alice", "CombatTest_Bob", net)
    print(f"Attack Log: {msg}")
    if "30 DMG" in msg: print("Kinetic Formula: VALID")
    else: print("Kinetic Formula: INVALID")

    print("\nVerification Complete.")

if __name__ == "__main__":
    asyncio.run(verify_combat())
