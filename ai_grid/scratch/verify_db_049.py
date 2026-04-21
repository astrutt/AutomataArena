import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def check():
    engine = create_async_engine("sqlite+aiosqlite:///automata_grid.db")
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT node_type, COUNT(*) FROM grid_nodes GROUP BY node_type"))
        rows = res.fetchall()
        print("\n--- NODE TYPE DISTRIBUTION ---")
        for type_name, count in rows:
            print(f"{type_name}: {count}")
        
        # Check if threat_level column exists
        try:
            await conn.execute(text("SELECT threat_level FROM grid_nodes LIMIT 1"))
            print("\nWARNING: 'threat_level' column still exists.")
        except Exception:
            print("\nCONFIRMED: 'threat_level' column is ABSENT.")

if __name__ == "__main__":
    asyncio.run(check())
