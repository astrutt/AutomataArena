import asyncio
import sys
import os

# --- Path Injection (Allows running from within the package directory) ---
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from ai_grid.models import GridNode

async def test_find_uplink():
    engine = create_async_engine("sqlite+aiosqlite:///ai_grid/automata_grid.db")
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    async with async_session() as session:
        stmt = select(GridNode).where(GridNode.name == "UpLink")
        res = await session.execute(stmt)
        uplink = res.scalars().first()
        if uplink:
            print(f"FOUND: ID={uplink.id}, Name='{uplink.name}'")
        else:
            print("NOT FOUND: Node 'UpLink' missing in SQLAlchemy context.")
            # Check all nodes
            all_res = await session.execute(select(GridNode))
            nodes = all_res.scalars().all()
            print(f"Contained Nodes: {[n.name for n in nodes]}")

if __name__ == "__main__":
    asyncio.run(test_find_uplink())
