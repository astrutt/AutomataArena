import asyncio
import os
import sys

# Ensure we can import from parent directories
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'core')))

from grid_db import ArenaDB
from models import Character, GridNode, DiscoveryRecord
from core.map_utils import generate_ascii_map
from grid_utils import C_GREY, C_RED, format_text

TEST_DB = "discovery_test.db"

async def setup_test_db():
    db_path = "discovery_test.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    db = ArenaDB(db_path=db_path)
    await db.init_schema()
    await db.seed_grid_expansion()
    return db

async def verify_fog_of_war_init(db):
    print("\n[TEST 1] Fog of War Initialization")
    # 1. Create a fresh player
    await db.register_player("Alpha", "testnet", "Daemon", "Infiltrator", "Test Bio", {"cpu":5, "ram":5, "bnd":5, "sec":5, "alg":5})
    async with db.async_session() as session:
        char = await db.get_character_by_nick("Alpha", "testnet", session)
        # UpLink neighbors should be [?]
        map_text = await generate_ascii_map(session, char, machine_mode=True, limit_radius=1)
        print("Initial Map (Radius 1):")
        print(map_text)
        
        # neighbors of UpLink (0,0) are:
        # Neural_Nexus (N), Shadow_Sector (W), Memory_Socket (E), Black_Market (D)
        # Note: direction 'down' isn't handled by BFS yet in x,y logic but north/west/east are.
        
        if "[?]" in map_text:
            print("SUCCESS: Neighbors are hidden behind [?]")
            return True
        else:
            print("FAILURE: Neighbors are visible without exploration.")
            return False

async def verify_exploration_persistence(db):
    print("\n[TEST 2] Exploration Persistence")
    # 1. Move North to Neural_Nexus
    await db.move_player("Alpha", "testnet", "north")
    async with db.async_session() as session:
        char = await db.get_character_by_nick("Alpha", "testnet", session)
        # Node we are on should auto-discover
        map_text = await generate_ascii_map(session, char, machine_mode=True, limit_radius=1)
        print("Moved North to Neural_Nexus:")
        print(map_text)
        
        if "[S]" in map_text or "[@]" in map_text: # safezone symbol or current node
            print("SUCCESS: Current node auto-discovered.")
        else:
            print("FAILURE: Current node remains unknown.")
            return False
            
        # 2. Check persistence - Move back to UpLink and check if Neural_Nexus is still visible
        await db.move_player("Alpha", "testnet", "south")
        char = await db.get_character_by_nick("Alpha", "testnet", session)
        map_text = await generate_ascii_map(session, char, machine_mode=True, limit_radius=1)
        print("Moved back to UpLink:")
        print(map_text)
        if "[S]" in map_text:
            print("SUCCESS: Previously visited node remains visible.")
            return True
        else:
            print("FAILURE: Discovery record lost after movement.")
            return False

async def verify_tiered_indicators(db):
    print("\n[TEST 3] Tiered Intelligence Indicators")
    # We'll use a CLOSED node for this: Black_Market_Port
    # We need to ensure it's in the character's discovery horizon
    async with db.async_session() as session:
        # Force discover Black_Market_Port (from UpLink it's "down", so BFS won't find it in x,y unless we force it)
        from sqlalchemy import select
        node = (await session.execute(select(GridNode).where(GridNode.name == "Neural_Nexus"))).scalars().first()
        node.availability_mode = 'CLOSED'
        await session.commit()
        
        # Subtest 1: Level 1 (SEC+ALG = 10)
        char = await db.get_character_by_nick("Alpha", "testnet", session)
        char.sec = 5; char.alg = 5
        map_text = await generate_ascii_map(session, char, machine_mode=True, limit_radius=1)
        print("Tier 1 (SEC+ALG=10) Map:")
        print(map_text)
        if "[X]" in map_text:
            print("SUCCESS: Tier 1 shows [X]")
        else:
            print("FAILURE: Tier 1 indicator mismatch.")
            return False
            
        # Subtest 2: Tier 2 (SEC+ALG = 25)
        char.sec = 15; char.alg = 10
        map_text = await generate_ascii_map(session, char, machine_mode=True, limit_radius=1)
        print("Tier 2 (SEC+ALG=25) Map:")
        print(map_text)
        if "[S]" in map_text:
            print("SUCCESS: Tier 2 shows [Cat] ([S])")
        else:
            print("FAILURE: Tier 2 indicator mismatch.")
            return False
            
        # Subtest 4: Tier 4 (SEC+ALG = 65)
        char.sec = 35; char.alg = 30
        map_text = await generate_ascii_map(session, char, machine_mode=True, limit_radius=1)
        print("Tier 4 (SEC+ALG=65) Map:")
        print(map_text)
        if "[Neura]" in map_text: # Truncated name
            print("SUCCESS: Tier 4 shows [Name]")
            return True
        else:
            print("FAILURE: Tier 4 indicator mismatch.")
            return False

async def verify_tiered_opening(db):
    print("\n[TEST 4] Tiered Opening Logic")
    # Logic: Explore opens Level 1/Unclaimed Nodes
    async with db.async_session() as session:
        # Set Neural_Nexus back to CLOSED and unclaimed
        await session.execute(GridNode.__table__.update().where(GridNode.name == "Neural_Nexus").values(availability_mode='CLOSED', owner_character_id=None, upgrade_level=1, power_stored=50))
        await session.commit()
        
        # 1. Explore should open it
        char = await db.get_character_by_nick("Alpha", "testnet", session)
        char.alg = 100 # Guarantee success
        await session.commit()
        
        await db.move_player("Alpha", "testnet", "north")
        result = await db.explore_node("Alpha", "testnet")
        print("Explore Result:", result.get('msg'))
        
        from sqlalchemy import select
        node = (await session.execute(select(GridNode).where(GridNode.name == "Neural_Nexus"))).scalars().first()
        if node.availability_mode == 'OPEN':
            print("SUCCESS: Explore auto-opened simple sector.")
        else:
            print("FAILURE: Explore failed to open simple sector.")
            return False
            
        # Logic: Probe opens Level 2/Unclaimed
        char = await db.get_character_by_nick("Alpha", "testnet", session)
        char.alg = 100 # Guarantee success
        await session.commit()
        
        await session.execute(GridNode.__table__.update().where(GridNode.name == "Neural_Nexus").values(availability_mode='CLOSED', owner_character_id=None, upgrade_level=2, power_stored=200))
        await session.commit()
        
        result = await db.probe_node("Alpha", "testnet")
        print("Probe Result:", result.get('msg') or "Success dict returned")
        
        from sqlalchemy import select
        node = (await session.execute(select(GridNode).where(GridNode.name == "Neural_Nexus"))).scalars().first()
        if node.availability_mode == 'OPEN':
            print("SUCCESS: Probe auto-opened moderate sector.")
            return True
        else:
            print("FAILURE: Probe failed to open moderate sector.")
            return False

async def run_all_tests():
    db = await setup_test_db()
    results = []
    
    results.append(await verify_fog_of_war_init(db))
    results.append(await verify_exploration_persistence(db))
    results.append(await verify_tiered_indicators(db))
    results.append(await verify_tiered_opening(db))
    
    print("\n" + "="*30)
    print(f"VERIFICATION COMPLETE: {sum(results)}/{len(results)} PASSED")
    print("="*30)
    
    await db.close()
    if os.path.exists(TEST_DB): os.remove(TEST_DB)

if __name__ == "__main__":
    asyncio.run(run_all_tests())
