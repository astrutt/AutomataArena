# verify_v2_grid.py
import asyncio
import os
import sys

# Ensure ai_grid is in path
sys.path.append(os.path.join(os.getcwd(), 'ai_grid'))

from ai_grid.grid_db import ArenaDB

async def verify():
    db = ArenaDB()
    try:
        print("[*] Starting v2.0 Grid Verification...")
        
        # 1. Register Test Subject
        nick = "TestFighter"
        net = "rizon"
        await db.register_player(nick, net, "Android", "Recon", "Test Bio", {"cpu": 5, "ram": 5, "bnd": 5, "sec": 5, "alg": 5})
        print(f"[*] Registered {nick} on {net}.")
        
        # 2. Get Initial Location
        loc = await db.get_location(nick, net)
        print(f"[*] Initial Location: {loc['name']} at ({loc['x']}, {loc['y']})")
        if loc['x'] != 25 or loc['y'] != 25:
             print(f"[!] ERROR: Spawn mismatch. Expected (25, 25), got ({loc['x']}, {loc['y']})")
        
        # 3. Traversal (East)
        # Move east: X increment
        print("[*] Moving EAST...")
        target_name, msg = await db.move_player(nick, net, "east")
        print(f"[*] Move Result: {msg}")
        
        new_loc = await db.get_location(nick, net)
        print(f"[*] New Location: {new_loc['name']} at ({new_loc['x']}, {new_loc['y']})")
        if new_loc['x'] != 26 or new_loc['y'] != 25:
            print(f"[!] ERROR: Movement math fail. Expected (26, 25), got ({new_loc['x']}, {new_loc['y']})")

        # 4. Map Rendering Verification
        print("[*] Generating Local Geoint Map...")
        from core.map_utils import generate_ascii_map
        async with db.async_session() as session:
            # Need to fetch the character object
            from ai_grid.models import Character
            from sqlalchemy.future import select
            from sqlalchemy.orm import selectinload
            stmt = select(Character).where(Character.name == nick).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            
            ascii_map = await generate_ascii_map(session, char)
            print("\n" + "="*20 + " GEOINT REPORT " + "="*20)
            print(ascii_map)
            print("="*55 + "\n")
            
            if "@" not in ascii_map:
                print("[!] ERROR: Player symbol [@] not found in map.")
            if f"({new_loc['x']}, {new_loc['y']})" not in ascii_map:
                print("[!] ERROR: Legend mismatch. Expected player coordinates in legend.")

        print("[*] Verification Complete.")
        
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(verify())
