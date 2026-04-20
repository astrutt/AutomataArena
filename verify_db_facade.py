import asyncio
import sys
import os

# Set up paths
sys.path.append(os.path.join(os.getcwd(), 'ai_grid'))

async def verify_connectivity():
    from ai_grid.grid_db import ArenaDB
    db = ArenaDB()
    print("ArenaDB initialized.")
    
    try:
        print(f"Checking for 'player' attribute: {hasattr(db, 'player')}")
        if not hasattr(db, 'player'):
            print("ERROR: ArenaDB is missing the 'player' attribute facade!")
            
        print(f"Checking for 'character' attribute: {hasattr(db, 'character')}")
        print(f"Checking for 'progression' attribute: {hasattr(db, 'progression')}")
        
    except Exception as e:
        print(f"Connectivity Test Failed: {e}")
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(verify_connectivity())
