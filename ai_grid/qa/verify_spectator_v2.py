import asyncio
import datetime
import os
import sys
sys.path.append(os.path.join(os.getcwd(), 'ai_grid'))

from ai_grid.grid_db import ArenaDB
import core.handlers as handlers
from unittest.mock import MagicMock

async def verify_refinements():
    db = ArenaDB()
    await db.init_schema()

    node = MagicMock()
    node.db = db
    # Setup Async Mock for node.send
    async def mock_send(msg): 
        print(f"SEND: {msg}")
    node.send = MagicMock(side_effect=mock_send)
    node.prefix = "!a"
    node.net_name = "test_net"
    node.match_queue = []
    node.ready_players = []
    node.active_engine = None

    # Add Alice (Player)
    stats = {'cpu': 5, 'ram': 5, 'bnd': 5, 'sec': 5, 'alg': 5}
    await db.register_player("Alice", "test_net", "Human", "Hacker", "Test Bio", stats)
    
    # Manually seed a Spectator for dividend/stat testing
    from ai_grid.models import Character, Player, NetworkAlias
    from sqlalchemy.future import select
    async with db.async_session() as session:
        # Create Player
        p = Player(global_name="Spectator_Test")
        session.add(p)
        await session.flush()
        # Create Character
        c = Character(player_id=p.id, name="Spectator_Test", race="Spectator", char_class="Observer", bio="Watching...", credits=100.0, xp=0, level=1, rank_title="Silent Watcher")
        session.add(c)
        await session.flush()
        # Create NetworkAlias
        n = NetworkAlias(player_id=p.id, network_name="test_net", nickname="Spectator_Test")
        session.add(n)
        await session.commit()
    print("Seeding complete.")

    # Test Player Info
    print("\nTracing Player Profile:")
    await handlers.handle_info_nick(node, "Alice", ["Alice"], "Alice")
    
    # Test Spectator Info
    print("\nTracing Spectator Profile:")
    await handlers.handle_info_nick(node, "Bob", ["Spectator_Test"], "Bob")

    print("\n--- [2. AUTOMATED DIVIDEND: award_daily_dividend] ---")
    # Simulate a spectator who hasn't received a bonus today
    success, log = await db.award_daily_dividend("Spectator_Test", "test_net")
    print(f"Dividend Awarded: {success} | Log: {log}")

    print("\n--- [3. COMMAND ROUTER INTEGRITY] ---")
    from ai_grid.core.command_router import CommandRouter
    router = CommandRouter(node)
    
    # Test !a info <nick>
    print("\nTesting !a info <nick> routing...")
    await router.dispatch("Alice", "!a", "TestBot", "!a info Alice", False)

    # Test !a spectator bonus (should fail/nothing happens)
    print("\nTesting !a spectator bonus (Expect: No output or help fallback)...")
    await router.dispatch("Alice", "!a", "TestBot", "!a spectator bonus", False)

    print("\n--- [4. SPECTATOR STORAGE] ---")
    await handlers.handle_spectator_inventory(node, "Spectator_Test", "Bob")

    print("\nVerification Complete.")

if __name__ == "__main__":
    asyncio.run(verify_refinements())
