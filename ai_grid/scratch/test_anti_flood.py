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

    print("[*] Verification Complete.")

if __name__ == "__main__":
    asyncio.run(run_test())
