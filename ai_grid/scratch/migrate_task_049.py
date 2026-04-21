
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import os

DB_FILE = "/Users/astrutt/Documents/AutomataGrid/ai_grid/automata_grid.db"
DB_URL = f"sqlite+aiosqlite:///{DB_FILE}"

async def migrate():
    print(f"[*] Starting migration on {DB_FILE}...")
    engine = create_async_engine(DB_URL, echo=True)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    async with engine.begin() as conn:
        # 1. Rename wilderness to void
        print("[*] Renaming 'wilderness' nodes to 'void'...")
        await conn.execute(text("UPDATE grid_nodes SET node_type = 'void' WHERE node_type = 'wilderness'"))
        
        # 2. Update default node_type to safezone (for existing NULLs if any, though usually not possible)
        # But we'll ensure safezone is the new default for any 'wilderness' that should have been safezone? 
        # Actually just rename is enough for now.
        
        # 3. Assign merchant types to known nodes
        print("[*] Assigning 'merchant' type to known trade hubs...")
        merchants = ["Black_Market_Port", "Dark_Web_Exchange"]
        for m in merchants:
            await conn.execute(text(f"UPDATE grid_nodes SET node_type = 'merchant' WHERE name = '{m}'"))
            
        # 4. Drop threat_level column
        print("[*] Dropping 'threat_level' column...")
        try:
            await conn.execute(text("ALTER TABLE grid_nodes DROP COLUMN threat_level"))
            print("[+] Successfully dropped 'threat_level' column.")
        except Exception as e:
            print(f"[!] Failed to drop 'threat_level' column: {e}")
            print("[!] This might be because the column doesn't exist or SQLite version issues.")

    await engine.dispose()
    print("[*] Migration complete.")

if __name__ == "__main__":
    asyncio.run(migrate())
