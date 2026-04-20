import asyncio
import sys
import os

sys.path.append(os.path.join(os.getcwd(), 'ai_grid'))

async def verify_incursions():
    from ai_grid.grid_db import ArenaDB
    db = ArenaDB()
    print("[1] ArenaDB initialized.")
    
    try:
        # Run schema update to create tables
        print("[2] Running schema update...")
        await db.update_schema()
        
        print("[3] Testing Incursion Facade...")
        if not hasattr(db, 'incursion'):
            print("ERROR: Incursion facade missing!")
            return
            
        print("[4] Spawning test incursion...")
        # Assume 'Rizon' or 'TestNet'
        network = "TestNet"
        
        inc = await db.incursion.spawn_incursion(network, "HacktopusAI", tier=1, reward=100.0, duration_mins=2)
        if not inc:
            print("WARN: Could not spawn incursion, likely no non-safezone nodes exist. This is expected in empty DBs.")
        else:
            print(f"Spawned successfully: {inc}")
            
    except Exception as e:
        print(f"Verification Failed: {e}")
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(verify_incursions())
