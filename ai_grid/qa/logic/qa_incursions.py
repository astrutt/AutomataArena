import asyncio
import sys
import os

sys.path.append(os.path.join(os.getcwd(), 'ai_grid'))

async def test_incursions():
    from ai_grid.grid_db import ArenaDB
    from ai_grid.models import GridNode, Character, Player, NetworkAlias, IncursionEvent
    from sqlalchemy.future import select
    from sqlalchemy import update, func
    
    db = ArenaDB()
    print("[+] DB Init")
    
    try:
        await db.init_schema()  # Ensure empty fresh DB or base stuff
        await db.update_schema()
        
        async with db.async_session() as session:
            # 1. Setup Test Network and Nodes
            n1 = GridNode(name="TestNode1", node_type="void", net_affinity="TestNet")
            n2 = GridNode(name="TestNode2", node_type="merchant", net_affinity="TestNet")
            
            session.add_all([n1, n2])
            await session.commit()
            print("[+] Seeded test nodes.")
            
        await db.register_player("TestChar1", "TestNet", "Synth", "Hacker", "Bio", {"str": 1, "cpu": 1, "ram": 1, "bnd": 1, "sec": 1, "alg": 1})
        await db.register_player("TestChar2", "TestNet", "Cyborg", "Tank", "Bio", {"str": 1, "cpu": 1, "ram": 1, "bnd": 1, "sec": 1, "alg": 1})
        print("[+] Seeded characters.")

            
        print("[+] Test 1: Spawn Incursion")
        inc = await db.incursion.spawn_incursion("TestNet", "HacktopusAI", tier=2, reward=500.0, duration_mins=5)
        if not inc:
            print("[-] FAILED: spawn_incursion returned None")
            return
        
        node_name = inc["node_name"]
        print(f"[+] Spawned incursion at {node_name}")
        
        print("[+] Test 2: Defend against wrong node")
        success, msg, victors = await db.incursion.register_defense("TestChar1", "TestNet", "WrongNode")
        if success or "not found" not in msg:
            print(f"[-] FAILED: Wrong node test. Msg: {msg}")
            return
        print(f"[+] Passed wrong node test")

        print("[+] Test 3: Defend correctly (1/2)")
        success, msg, victors = await db.incursion.register_defense("TestChar1", "TestNet", node_name)
        if not success or "Waiting for 1" not in msg:
            print(f"[-] FAILED: First defense. Msg: {msg}")
            return
        print("[+] Passed first defense")

        print("[+] Test 4: Defend duplicate")
        success, msg, victors = await db.incursion.register_defense("TestChar1", "TestNet", node_name)
        if success or "already deployed" not in msg:
            print(f"[-] FAILED: Duplicate defense. Msg: {msg}")
            return
        print("[+] Passed duplicate defense")

        print("[+] Test 5: Defend resolution (2/2)")
        success, msg, victors = await db.incursion.register_defense("TestChar2", "TestNet", node_name)
        if not success or "SUCCESS" not in msg:
            print(f"[-] FAILED: Final defense. Msg: {msg}")
            return
        print(f"[+] Resolution msg: {msg}")
        print(f"[+] Victors: {victors}")
        if "TestChar1" not in victors or "TestChar2" not in victors:
            print("[-] FAILED: Victors list missing characters.")
            return
        
        print("[+] Test 6: Verify Credits")
        async with db.async_session() as session:
            stmt = select(Character).where(Character.name.in_(["TestChar1", "TestChar2"]))
            chars = (await session.execute(stmt)).scalars().all()
            for c in chars:
                if c.credits != 1000.0:
                    print(f"[-] FAILED: {c.name} has {c.credits} instead of 1000.0")
                    return
        print("[+] Passed credits check")

        print("[+] Test 7: Expiration")
        # Let's spawn another incursion
        inc2 = await db.incursion.spawn_incursion("TestNet", "Gridbugs", tier=1, duration_mins=5)
        # artificially expire it
        async with db.async_session() as session:
            stmt = update(IncursionEvent).where(IncursionEvent.network_name == 'TestNet', IncursionEvent.status == 'ACTIVE').values(expires_at=func.datetime('now', '-1 day'))
            await session.execute(stmt)
            await session.commit()
            
        nots = await db.incursion.expire_incursions("TestNet")
        if not nots:
            print("[-] FAILED: Expiration did not return notifications.")
            return
        print(f"[+] Passed expiration: {nots[0]}")
        
    except Exception as e:
        print(f"[-] ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(test_incursions())
