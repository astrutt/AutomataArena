# test_anti_flood_remediated.py
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
        self.prefix = "!"
        self.config = {'nickname': 'Antigravity', 'channel': '#test'}
        self.sent_messages = []

    async def send(self, msg, immediate=False):
        self.sent_messages.append(msg)

# Import the real logic
import ai_grid.core.handlers.base as base

# Mock get_action_routing
async def mock_routing(node, nick, target):
    return nick, "#test", False, "PRIVMSG"
base.get_action_routing = mock_routing

async def run_test():
    node = MockNode()
    nick = "Tester"
    target = "#test"
    
    print("[*] Starting Remediation Verification (Centralized Pacing)...")
    
    # 1. Central Consumption (Simulate Router)
    print("[*] Simulating Router Dispatch (1 action)...")
    res_router = await base.check_rate_limit(node, nick, target, consume=True)
    if not res_router:
        print("[!] FAILED: Router blocked first command.")
        return
        
    record = node.action_timestamps[nick.lower()]
    print(f"[+] Token Consumed. Remaining: {record['tokens']:.1f}")
    
    # 2. Handler Interval Check (Simulate Explore - 30s)
    print("[*] Simulating Handler Check (Explore 30s, No Consume)...")
    # This should FAIL because last_action was 0s ago and explore needs 30s
    res_handler = await base.check_rate_limit(node, nick, target, cooldown=30, consume=False)
    if res_handler:
        print("[!] FAILED: Explore should be blocked by 30s cooldown.")
    else:
        print("[+] Cooldown correctly enforced.")
    
    # 3. Multiple Commands (Burst Protection)
    print("[*] Depleting Burst (4 total actions)...")
    for i in range(3): # already did 1 in step 1
        await base.check_rate_limit(node, nick, target, consume=True)
    
    print(f"[*] Tokens after burst: {record['tokens']:.1f}")
    
    # 5th action should fail and trigger violation
    res_fail = await base.check_rate_limit(node, nick, target, consume=True)
    if res_fail:
        print("[!] FAILED: 5th command should be blocked (Empty Bucket).")
    else:
        print(f"[+] Pacing active. Violations: {record['violations']}")

    # 4. Global Protection (Move/Economy Bypass check)
    print("[*] Verifying Global Protection (Simulated Move)...")
    # Tokens are zero, so it should fail.
    res_move = await base.check_rate_limit(node, nick, target, consume=True)
    if res_move:
        print("[!] FAILED: Move bypassed the pacer!")
    else:
        print("[+] Move correctly throttled by central pacer.")

    print("[*] Verification Complete.")

if __name__ == "__main__":
    asyncio.run(run_test())
