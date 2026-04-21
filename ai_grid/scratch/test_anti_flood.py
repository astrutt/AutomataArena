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
    nick = "Spammer"
    
    print("[*] Starting Anti-Flood Verification...")
    
    # 1. Burst Capacity (4 commands)
    print("[*] Testing Burst Capacity (4 commands)...")
    for i in range(4):
        res = await base.check_rate_limit(node, nick, "#test")
        if not res:
            print(f"[!] FAILED: Command {i+1} blocked incorrectly.")
            return
    print("[+] Burst PASS.")
    
    # 2. Pacing Trigger (5th command)
    print("[*] Testing Pacing Trigger...")
    res = await base.check_rate_limit(node, nick, "#test")
    if res:
        print("[!] FAILED: 5th command should be blocked.")
        return
    print("[+] Pacing PASS (Blocked as expected).")
    
    # 3. Violation Accumulation (Commands 6-9)
    print("[*] Testing Violation Accumulation...")
    for i in range(3):
        await base.check_rate_limit(node, nick, "#test")
    
    record = node.action_timestamps[nick.lower()]
    print(f"[*] Current Violations: {record['violations']}")
    
    # 4. Hard Lockout (10th/11th total action, hits threshold 5)
    print("[*] Testing Hard Lockout (Hit threshold)...")
    res = await base.check_rate_limit(node, nick, "#test")
    if res:
        print("[!] FAILED: Should be locked out.")
    
    if record['lockout_until'] > time.time():
        print(f"[+] Hard Lockout PASS (Active for {int(record['lockout_until'] - time.time())}s).")
    else:
        print("[!] FAILED: Lockout timestamp not set.")

    # 5. Continuous Refill
    print("[*] Testing Continuous Refill (Wait 4s for 2 tokens)...")
    node.action_timestamps[nick.lower()]['lockout_until'] = 0 # manually clear for test
    node.action_timestamps[nick.lower()]['tokens'] = 0
    node.action_timestamps[nick.lower()]['last_refill'] = time.time()
    
    await asyncio.sleep(4.1) # Should get 2 tokens
    res1 = await base.check_rate_limit(node, nick, "#test")
    res2 = await base.check_rate_limit(node, nick, "#test")
    res3 = await base.check_rate_limit(node, nick, "#test") # should fail
    
    if res1 and res2 and not res3:
        print("[+] Refill PASS.")
    else:
        print(f"[!] FAILED: Refill logic error. (Res: {res1}, {res2}, {res3})")

    print("[*] Verification Complete.")

if __name__ == "__main__":
    asyncio.run(run_test())
