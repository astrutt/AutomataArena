import asyncio
import sys
import os
import re

# Add root and ai_grid dirs to path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "ai_grid"))

from ai_grid.grid_db import ArenaDB

class MockNode:
    def __init__(self, db, net_name="rizon"):
        self.db = db
        self.net_name = net_name
        self.prefix = "!a"
        self.config = {"channel": "#automata", "nickname": "GridNode"}
        self.action_timestamps = {}
        self.sent_messages = []

    async def send(self, msg, immediate=False):
        self.sent_messages.append(msg)

async def audit_machine_protocol():
    db = ArenaDB()
    node = MockNode(db)
    nick = "AuditBot"
    network = "rizon"
    
    print("[*] Initiating Nomenclature Protocol Audit (Machine Mode)...")
    
    # 1. Setup Audit Character in Machine Mode
    async with db.async_session() as session:
        char = await db.identity.get_character_by_nick(nick, network, session)
        if not char:
            await db.identity.register_player(nick, network, "Human", "Hacker", "Bio", {})
            char = await db.identity.get_character_by_nick(nick, network, session)
        
        # Set preference to machine mode
        await db.set_pref(nick, network, 'output_mode', 'machine')
        await session.commit()

    # Import handlers
    from core.handlers.grid import handle_grid_view
    from core.handlers.combat import handle_leaderboard
    from core.handlers.economy import handle_shop_view
    from core.handlers.personal import handle_stats
    
    test_cases = [
        ("GRID VIEW", handle_grid_view, [node, nick, "#automata"]),
        ("LEADERBOARD", handle_leaderboard, [node, nick, ["DICE"], "#automata"]),
        ("SHOP VIEW", handle_shop_view, [node, nick, "#automata"]),
        ("STATS VIEW", handle_stats, [node, nick, [], "#automata"])
    ]
    
    all_passed = True
    for name, func, args in test_cases:
        print(f"\n[*] Testing {name}...")
        node.sent_messages = []
        await func(*args)
        
        if not node.sent_messages:
            print(f"[❌] {name} failed: No messages sent.")
            all_passed = False
            continue
            
        # For machine mode, we expect [GRID][ACTION:...] and NO Unicode/IRC codes
        for msg in node.sent_messages:
            # Strip IRC formatting for check
            # (In reality, tag_msg should have already stripped them)
            # Check for [GRID] prefix
            if "[GRID]" not in msg:
                print(f"[❌] {name} leak detected: {msg}")
                all_passed = False
            
            # Check for non-ASCII
            for char in msg:
                if ord(char) >= 128:
                    print(f"[❌] {name} unicode leak: {msg}")
                    all_passed = False
                    break
            
            # Check for condensed format in listings if applicable
            if name in ["LEADERBOARD", "SHOP VIEW"]:
                # Should be a single tag_msg call with lots of data
                if "|" not in msg and ":" not in msg:
                    print(f"[⚠️] {name} output seems sparse: {msg}")
            
            print(f"[+] Output: {msg}")

    await db.close()
    if all_passed:
        print("\n[✅] Nomenclature Audit Passed: All tested handlers strictly follow the protocol.")
    else:
        print("\n[❌] Nomenclature Audit Failed: Leaks detected.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(audit_machine_protocol())
