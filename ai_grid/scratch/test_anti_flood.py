# test_anti_flood.py
import asyncio
import time
import sys
import os

# Mock Node for testing
class MockNode:
    def __init__(self):
        self.net_name = "test"
        self.action_timestamps = {}
        self.flood_config = {
            'max_tokens': 4.0,
            'refill_rate': 0.5,
            'violation_threshold': 5,
            'lockout_duration': 30
        }
        self.sent_messages = []
        self.prefix = "!"
        self.config = {'channel': '#test'}
        self.active_engine = None
        self.db = None # Not needed for rate limit mock

    async def send(self, msg, immediate=False):
        self.sent_messages.append(msg)

# Mock DB for get_prefs
class MockDB:
    async def get_prefs(self, nick, net):
        return {'output_mode': 'human', 'msg_type': 'privmsg'}

# Monkeypatch base.get_action_routing to avoid DB hits
import ai_grid.core.handlers.base as base

async def mock_routing(node, nick, target):
    return nick, "#test", False, "PRIVMSG"

base.get_action_routing = mock_routing

async def run_test():
    node = MockNode()
    nick = "Tester"
    target = "#test"
    
    print("[*] Starting Remediation Verification (Centralized Pacing)...")
    
    # 1. Verify Central Consumption (Simulated Router Dispatch)
    print("[*] Testing Global Protection (Simulated Move/Economy)...")
    # All game commands consume 1 token immediately
    res1 = await base.check_rate_limit(node, nick, target, consume=True)
    res2 = await base.check_rate_limit(node, nick, target, consume=True)
    res3 = await base.check_rate_limit(node, nick, target, consume=True)
    res4 = await base.check_rate_limit(node, nick, target, consume=True)
    
    record = node.action_timestamps[nick.lower()]
    print(f"[+] 4 actions consumed. Tokens remaining: {record['tokens']:.1f}")
    
    # 5th action should fail (Bucket Empty)
    res5 = await base.check_rate_limit(node, nick, target, consume=True)
    if not res5:
        print("[+] SUCCESS: Central pacing correctly throttled the 5th command.")
    else:
        print("[!] FAILED: 5th command bypassed central pacing.")
        return

    # 2. Verify Synchronized Interval (Explore - 15s)
    print("[*] Testing Handler Synchronization (Explore - 15s)...")
    # Reset tokens for interval test
    record['tokens'] = 4.0
    record['last_action'] = time.time()
    
    # This should FAIL because last_action was 0s ago, even though tokens are full
    # (Using cooldown=15 as per explore)
    res_explore = await base.check_rate_limit(node, nick, target, cooldown=15, consume=False)
    if not res_explore:
        print("[+] SUCCESS: Explore correctly enforced 15s interval without consuming extra tokens.")
    else:
        print("[!] FAILED: Explore interval (15s) not enforced.")
        return

    # 3. Verify No Double Consumption
    print("[*] Verifying No Double Consumption...")
    pre_tokens = record['tokens']
    # If we check again without consuming, tokens stay the same
    await base.check_rate_limit(node, nick, target, cooldown=15, consume=False)
    if record['tokens'] == pre_tokens:
        print("[+] SUCCESS: Handler check (consume=False) did not tax the bucket.")
    else:
        print("[!] FAILED: Handler check double-consumed tokens.")

    # Import CommandRouter and AsyncMock for end-to-end routing tests
    from unittest.mock import AsyncMock
    from ai_grid.core.command_router import CommandRouter

    # 4. New Test Case 1: Spam '!a move n' (Global Token Consumption on Move)
    print("\n[*] New Test Case 1: Spam '!a move n'...")
    node_move = MockNode()
    node_move.prefix = "!a"
    class DummyMoveDB:
        async def move_player(self, nick, net, direction):
            return "Node_Beta", "Traversed north"
        async def get_location(self, nick, net):
            return {
                'name': 'Node_Alpha', 'type': 'void', 'level': 1, 'exits': ['north'],
                'power_stored': 100, 'upgrade_level': 1, 'durability': 100,
                'credits_pool': 500, 'visibility_mode': 'OPEN', 'net_affinity': None
            }
        async def get_prefs(self, nick, net):
            return {'output_mode': 'human', 'msg_type': 'privmsg'}
        def async_session(self):
            from contextlib import asynccontextmanager
            @asynccontextmanager
            async def dummy_session():
                yield None
            return dummy_session()
        async def get_character_by_nick(self, nick, net, session):
            return None
    node_move.db = DummyMoveDB()
    router_move = CommandRouter(node_move)
    
    # Send 4 moves to drain burst bucket (4.0 -> 0.0)
    for i in range(4):
        await router_move.dispatch("Mover", "PRIVMSG", "#test", "!a move n", is_admin=False)
        await asyncio.sleep(0.01)
    
    rec_move = node_move.action_timestamps["mover"]
    print(f"[+] 4 moves dispatched. Tokens remaining: {rec_move['tokens']:.1f}")
    assert rec_move['tokens'] <= 0.05, f"Expected tokens <= 0, got {rec_move['tokens']}"
    
    # 5th move must be throttled and fire pacing message
    node_move.sent_messages.clear()
    await router_move.dispatch("Mover", "PRIVMSG", "#test", "!a move n", is_admin=False)
    await asyncio.sleep(0.01)
    pacing_fired = any("FLOOD CONTROL" in m or "pacing" in m.lower() for m in node_move.sent_messages)
    assert pacing_fired, f"Pacing message did not fire! Messages: {node_move.sent_messages}"
    print("[+] SUCCESS: Spamming '!a move n' correctly consumed tokens and fired pacing message.")

    # 5. New Test Case 2: Spam '!a buy <item>' (Global Token Consumption on Economy)
    print("\n[*] New Test Case 2: Spam '!a buy <item>' (Economy)...")
    node_econ = MockNode()
    node_econ.prefix = "!a"
    class DummyEconDB:
        async def process_transaction(self, nick, net, verb, item):
            return True, "Purchased Nano_Patch"
        async def get_prefs(self, nick, net):
            return {'output_mode': 'human', 'msg_type': 'privmsg'}
    node_econ.db = DummyEconDB()
    router_econ = CommandRouter(node_econ)
    
    for i in range(4):
        await router_econ.dispatch("Shopper", "PRIVMSG", "#test", "!a buy Nano_Patch", is_admin=False)
        await asyncio.sleep(0.01)
        
    rec_econ = node_econ.action_timestamps["shopper"]
    print(f"[+] 4 buy commands dispatched. Tokens remaining: {rec_econ['tokens']:.1f}")
    assert rec_econ['tokens'] <= 0.05, f"Expected tokens <= 0, got {rec_econ['tokens']}"
    
    node_econ.sent_messages.clear()
    await router_econ.dispatch("Shopper", "PRIVMSG", "#test", "!a buy Nano_Patch", is_admin=False)
    await asyncio.sleep(0.01)
    pacing_fired_econ = any("FLOOD CONTROL" in m or "pacing" in m.lower() for m in node_econ.sent_messages)
    assert pacing_fired_econ, f"Pacing message did not fire! Messages: {node_econ.sent_messages}"
    print("[+] SUCCESS: Spamming '!a buy <item>' correctly consumed tokens and fired pacing message.")

    # 6. New Test Case 3: Spam '!a explore' (15s cooldown fires, exactly ONE token consumed per command)
    print("\n[*] New Test Case 3: Spam '!a explore' (15s Cooldown & Single Token Consumption)...")
    node_exp = MockNode()
    node_exp.prefix = "!a"
    class DummyExpDB:
        async def explore_node(self, nick, net):
            return {'status': 'success', 'msg': 'Explored sector'}
        async def get_location(self, nick, net):
            return {'name': 'Node_Alpha', 'type': 'void'}
        async def get_prefs(self, nick, net):
            return {'output_mode': 'human', 'msg_type': 'privmsg'}
    node_exp.db = DummyExpDB()
    node_exp.add_xp = AsyncMock()
    router_exp = CommandRouter(node_exp)
    
    # 1st explore: should succeed and consume exactly ONE token (4.0 -> 3.0)
    await router_exp.dispatch("Scout", "PRIVMSG", "#test", "!a explore", is_admin=False)
    await asyncio.sleep(0.01)
    rec_exp = node_exp.action_timestamps["scout"]
    tokens_after_first = rec_exp['tokens']
    print(f"[+] 1st explore dispatched. Tokens remaining: {tokens_after_first:.1f}")
    assert abs(tokens_after_first - 3.0) < 0.1, f"Expected 3.0 tokens after 1st explore, got {tokens_after_first}"
    
    # 2nd explore (sent immediately after): 15s cooldown fires, handler does NOT consume an extra token
    node_exp.sent_messages.clear()
    await router_exp.dispatch("Scout", "PRIVMSG", "#test", "!a explore", is_admin=False)
    await asyncio.sleep(0.01)
    cooldown_fired = any("COOLDOWN" in m for m in node_exp.sent_messages)
    tokens_after_second = rec_exp['tokens']
    print(f"[+] 2nd explore dispatched. Tokens remaining: {tokens_after_second:.1f}")
    assert cooldown_fired, f"15s cooldown message did not fire! Messages: {node_exp.sent_messages}"
    assert abs(tokens_after_second - 2.0) < 0.1, f"Expected 2.0 tokens after 2nd explore, got {tokens_after_second}"
    print("[+] SUCCESS: Explore 15s cooldown fired with exactly 1 token consumed per command (no double-consumption).")

    print("\n[*] All Verification Tests Passed Successfully.")

if __name__ == "__main__":
    asyncio.run(run_test())
