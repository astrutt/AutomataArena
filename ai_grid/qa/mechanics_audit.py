
import asyncio
import sys
import os

# Inject path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, ItemTemplate
from sqlalchemy.future import select

async def audit_mechanics():
    db = ArenaDB()
    async with db.async_session() as session:
        # 1. Check Starting Stats & HP
        stmt = select(Character).limit(1)
        res = await session.execute(stmt)
        char = res.scalars().first()
        if char:
            print(f"--- Character Audit ---")
            print(f"Name: {char.name}")
            print(f"Level: {char.level}")
            print(f"Stats: CPU:{char.cpu} RAM:{char.ram} BND:{char.bnd} SEC:{char.sec} ALG:{char.alg}")
            total_stats = char.cpu + char.ram + char.bnd + char.sec + char.alg
            print(f"Total Stats: {total_stats}")
            print(f"Current HP: {char.current_hp}")
            print(f"Expected HP (6x+20): {total_stats * 6 + 20}")
            print(f"Expected HP (4x+10): {total_stats * 4 + 10}")

        # 2. Check Node Addons
        stmt = select(GridNode).where(GridNode.owner_character_id != None).limit(1)
        res = await session.execute(stmt)
        node = res.scalars().first()
        if node:
             print(f"\n--- Node Audit ---")
             print(f"Node: {node.name}")
             print(f"Type: {node.node_type}")
             print(f"Upgrade Level: {node.upgrade_level}")
             print(f"Addons: {node.addons_json}")

        # 3. Check Item Templates
        stmt = select(ItemTemplate).limit(5)
        res = await session.execute(stmt)
        items = res.scalars().all()
        print(f"\n--- Item Templates ---")
        for i in items:
            print(f"Item: {i.name} | Type: {i.item_type} | Value: {i.base_value}")

if __name__ == "__main__":
    asyncio.run(audit_mechanics())
