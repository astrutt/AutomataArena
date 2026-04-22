import asyncio
import sys
import os
import unittest
from sqlalchemy.future import select
from sqlalchemy import func

# Add root and ai_grid to path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "ai_grid"))

from ai_grid.grid_db import ArenaDB
from ai_grid.models import GridNode, RaidTarget

async def repro_grid_stats_crash():
    print("[*] Repro: Checking for get_grid_stats crash...")
    db = ArenaDB()
    try:
        # This call is expected to fail if GridNode.credits_pool is missing
        stats = await db.navigation.get_grid_stats()
        print(f"[!] Stats: {stats}")
    except Exception as e:
        print(f"[❌] CRASH DETECTED: {e}")
    finally:
        await db.close()

async def verify_map_overrides():
    print("\n[*] Verify: Coordinate Overrides & Raid Icons...")
    # This would require a full node setup, but we can audit the logic
    # via the existing handlers if we mock the node.
    pass

if __name__ == "__main__":
    asyncio.run(repro_grid_stats_crash())
