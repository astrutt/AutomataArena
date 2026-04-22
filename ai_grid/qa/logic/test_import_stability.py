import asyncio
import sys
import os

# Add root to path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, DiscoveryRecord

async def test_import_stability():
    print("[*] Starting Import Stability Audit (Task 058)...")
    
    try:
        # 1. Initialize ArenaDB
        print("[1] Initializing ArenaDB...")
        db = ArenaDB()
        print("[+] ArenaDB successfully initialized.")
        
        # 2. Verify Repository Attachment
        print("[2] Verifying repository attachment...")
        repos = [
            'identity', 'character', 'navigation', 'territory', 
            'discovery', 'infiltration', 'maintenance', 'comm'
        ]
        for repo in repos:
            if hasattr(db, repo):
                print(f" | {repo:<12}: OK")
            else:
                raise AttributeError(f"Repository '{repo}' not found on ArenaDB.")
        
        # 3. Perform basic query to verify model visibility
        print("[3] Verifying model/repository interaction...")
        async with db.async_session() as session:
            # Check for a character
            char = await db.character.get_player("Antigravity", "TestNet")
            if char:
                print(f"[+] Data found: {char['name']} @ {char['network']}")
            else:
                print("[!] No player found (expected if DB is empty), but query succeeded.")
        
        print("\n[✅] Import Stability Audit COMPLETE: No circular dependencies detected.")
        await db.close()
        
    except Exception as e:
        print(f"\n[❌] AUDIT FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_import_stability())
