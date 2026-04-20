import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update

# Ensure we can import from parent directories
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'core')))

from grid_db import ArenaDB
from models import Character, GridNode, DiscoveryRecord, BreachRecord
from grid_utils import tag_msg, C_CYAN, C_GREEN, C_WHITE

TEST_DB = "task_028_qa.db"

async def setup_test_db():
    if os.path.exists(TEST_DB): os.remove(TEST_DB)
    db = ArenaDB(db_path=TEST_DB)
    await db.init_schema()
    await db.seed_grid_expansion()
    # Create test player
    await db.register_player("QA_Bot", "testnet", "Daemon", "QA", "Verification Bot", {"cpu":10, "ram":10, "bnd":10, "sec":10, "alg":10})
    return db

async def test_sequence_enforcement(db):
    print("\n[TEST 1] Sequence Enforcement")
    async with db.async_session() as session:
        # Guarantee success for tests
        await session.execute(update(Character).where(Character.name == "QA_Bot").values(alg=100))
        await session.commit()

        # 1. Try PROBE without EXPLORE
        result = await db.probe_node("QA_Bot", "testnet")
        if not result.get("success") and "EXPLORED" in result.get("error", ""):
            print("  ✅ Pass: PROBE blocked without EXPLORE.")
        else:
            print(f"  ❌ Fail: PROBE not blocked. Result: {result}")

        # 2. EXPLORE and then PROBE
        await db.explore_node("QA_Bot", "testnet")
        result = await db.probe_node("QA_Bot", "testnet")
        if result.get("success"):
            print("  ✅ Pass: PROBE successful after EXPLORE.")
        else:
            print(f"  ❌ Fail: PROBE failed after EXPLORE. Result: {result}")

        # 3. Try HACK without PROBE (Move to a node with owner to test hack)
        # We need an owned node. Neural_Nexus level 1 unclaimed.
        await db.move_player("QA_Bot", "testnet", "north")
        # Set an owner for Neural_Nexus to allow HACK
        stmt = update(GridNode).where(GridNode.name == "Neural_Nexus").values(owner_character_id=999, availability_mode='CLOSED')
        await session.execute(stmt)
        await session.commit()
        
        # Explore it
        await db.explore_node("QA_Bot", "testnet")
        
        # Try HACK without PROBE
        success, msg, _ = await db.infiltration.hack_node("QA_Bot", "testnet")
        if not success and "Valid PROBE required" in msg:
            print("  ✅ Pass: HACK blocked without PROBE.")
        else:
            print(f"  ❌ Fail: HACK not blocked. Msg: {msg}")

async def test_ttl_expiry(db):
    print("\n[TEST 2] TTL Expiry")
    async with db.async_session() as session:
        # Guarantee success for tests
        await session.execute(update(Character).where(Character.name == "QA_Bot").values(alg=100))
        await session.commit()

        # 1. Successful PROBE
        await db.probe_node("QA_Bot", "testnet")
        
        # 2. Simulate Expiry (Subtract 6 minutes)
        from sqlalchemy.orm import selectinload
        stmt = select(Character).where(Character.name == "QA_Bot").options(selectinload(Character.current_node))
        char = (await session.execute(stmt)).scalars().first()
        node = char.current_node
        expiry_time = datetime.now(timezone.utc) - timedelta(minutes=6)
        
        stmt = update(DiscoveryRecord).where(
            DiscoveryRecord.character_id == char.id,
            DiscoveryRecord.node_id == node.id,
            DiscoveryRecord.intel_level == 'PROBE'
        ).values(discovered_at=expiry_time)
        await session.execute(stmt)
        await session.commit()
        
        # 3. Try HACK -> Should fail due to expired PROBE
        success, msg, _ = await db.infiltration.hack_node("QA_Bot", "testnet")
        if not success and "Valid PROBE required" in msg:
            print("  ✅ Pass: HACK blocked due to expired PROBE.")
        else:
            print(f"  ❌ Fail: HACK not blocked by TTL. Msg: {msg}")

async def test_ttl_refresh(db):
    print("\n[TEST 3] TTL Refresh")
    async with db.async_session() as session:
        # Guarantee success for tests
        await session.execute(update(Character).where(Character.name == "QA_Bot").values(alg=100))
        await session.commit()

        # 1. Perform PROBE
        await db.probe_node("QA_Bot", "testnet")
        
        from sqlalchemy.orm import selectinload
        stmt = select(Character).where(Character.name == "QA_Bot").options(selectinload(Character.current_node))
        char = (await session.execute(stmt)).scalars().first()
        
        char_id = char.id
        node_id = char.node_id

        disc = (await session.execute(select(DiscoveryRecord).where(
            DiscoveryRecord.character_id == char_id,
            DiscoveryRecord.node_id == node_id,
            DiscoveryRecord.intel_level == 'PROBE'
        ))).scalars().first()
        
        disc_id = disc.id
        ts1 = disc.discovered_at
        
        # 2. Re-probe after a slight delay (or manual offset)
        stmt = update(DiscoveryRecord).where(DiscoveryRecord.id == disc_id).values(discovered_at=ts1 - timedelta(seconds=10))
        await session.execute(stmt)
        await session.commit()
        
        await db.probe_node("QA_Bot", "testnet")
        
        # Fresh query for the record
        session.expire_all()
        disc_refreshed = (await session.execute(select(DiscoveryRecord).where(DiscoveryRecord.id == disc_id))).scalars().first()
        ts2 = disc_refreshed.discovered_at
        
        if ts2 > ts1 - timedelta(seconds=5): # Should be close to 'now'
            print("  ✅ Pass: PROBE refreshed the discovery timestamp.")
        else:
            print(f"  ❌ Fail: PROBE did not refresh timestamp. TS1: {ts1}, TS2: {ts2}")

async def test_protocol_format():
    print("\n[TEST 4] Protocol Format Audit")
    
    # [GRID]<ico>[ACTION][RESULT][NICK] TEXT
    # Manual mode (Human)
    msg_human = tag_msg("Test message", action="SIGINT", result="SUCCESS", nick="QA_Bot", is_machine=False)
    # Expected: Contains color codes, icon, and brackets in order.
    # We'll check for order of brackets.
    brackets = ["[GRID]", "[SIGINT]", "[SUCCESS]", "[QA_Bot]"]
    ordered = True
    pos = 0
    for b in brackets:
        new_pos = msg_human.find(b)
        if new_pos < pos: 
            ordered = False
            break
        pos = new_pos
    
    if ordered and "📡" in msg_human:
        print("  ✅ Pass: Human protocol format correct (ordered brackets + icon).")
    else:
        print(f"  ❌ Fail: Human protocol format mismatch. Result: {msg_human}")

    # Machine mode
    msg_machine = tag_msg("Test message", action="SIGINT", result="SUCCESS", nick="QA_Bot", is_machine=True)
    if "[GRID][SIGINT][SUCCESS][QA_Bot] Test message" in msg_machine and "📡" not in msg_machine:
        print("  ✅ Pass: Machine protocol format correct (plain text, no icon).")
    else:
        print(f"  ❌ Fail: Machine protocol format mismatch. Result: {msg_machine}")

async def run_all():
    db = await setup_test_db()
    try:
        await test_sequence_enforcement(db)
        await test_ttl_expiry(db)
        await test_ttl_refresh(db)
        await test_protocol_format()
    finally:
        await db.close()
        if os.path.exists(TEST_DB): os.remove(TEST_DB)

if __name__ == "__main__":
    asyncio.run(run_all())
