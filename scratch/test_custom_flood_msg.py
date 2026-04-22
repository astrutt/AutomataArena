
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock

# Mocking parts of the system
class MockNode:
    def __init__(self):
        self.flood_config = {
            'max_tokens': 4.0,
            'refill_rate': 0.5,
            'violation_threshold': 2, # Low for testing
            'lockout_duration': 5,
            'messages': {
                "hard_lockout": "MOCK LOCKOUT: {rem}s",
                "cooldown": "MOCK COOLDOWN: {rem}s",
                "terminal_overflow": "MOCK OVERFLOW: {lockout_duration}s",
                "pacing_warning": "MOCK PACING: {rem:.1f}s"
            }
        }
        self.action_timestamps = {}
        self.net_name = "test_net"
        self.db = MagicMock()
        self.db.get_prefs = AsyncMock(return_value={"output_mode": "human", "msg_type": "privmsg"})
        self.send = AsyncMock()
        self.config = {'channel': '#test'}

# Import the function to test
# We need to add the path to ai_grid to sys.path
import sys
import os
sys.path.append('/Users/astrutt/Documents/AutomataGrid')

from ai_grid.core.handlers.base import check_rate_limit

async def run_test():
    node = MockNode()
    nick = "Tester"
    target = "#test"

    print("--- Test 1: Pacing Warning ---")
    # Consume all tokens with 0 cooldown to avoid interval failures
    for _ in range(4):
        await check_rate_limit(node, nick, target, cooldown=0, consume=True)
    
    # Next call should trigger pacing warning
    result = await check_rate_limit(node, nick, target, cooldown=0, consume=True)
    await asyncio.sleep(0.1)
    print(f"Result: {result}")
    sent_msgs = [call.args[0] for call in node.send.call_args_list]
    for m in sent_msgs:
        if "MOCK PACING" in m:
            print(f"Captured: {m}")

    print("\n--- Test 2: Terminal Overflow ---")
    node.send.reset_mock()
    # We already have 1 violation from Test 1. One more should trigger overflow.
    await check_rate_limit(node, nick, target, cooldown=0, consume=True) # 2nd violation
    await asyncio.sleep(0.1)
    print(f"Calls to node.send: {len(node.send.call_args_list)}")
    sent_msgs = [call.args[0] for call in node.send.call_args_list]
    for m in sent_msgs:
        if "MOCK OVERFLOW" in m:
            print(f"Captured: {m}")

    print("\n--- Test 3: Hard Lockout ---")
    node.send.reset_mock()
    # Call while locked out
    await check_rate_limit(node, nick, target, consume=True)
    await asyncio.sleep(0.1)
    sent_msgs = [call.args[0] for call in node.send.call_args_list]
    for m in sent_msgs:
        if "MOCK LOCKOUT" in m:
            print(f"Captured: {m}")

    print("\n--- Test 4: Cooldown ---")
    node.send.reset_mock()
    node.action_timestamps = {} # Clear state
    # First action
    await check_rate_limit(node, nick, target, cooldown=10, consume=True)
    # Second action immediately after
    await check_rate_limit(node, nick, target, cooldown=10, consume=True)
    await asyncio.sleep(0.1)
    sent_msgs = [call.args[0] for call in node.send.call_args_list]
    for m in sent_msgs:
        if "MOCK COOLDOWN" in m:
            print(f"Captured: {m}")

if __name__ == "__main__":
    asyncio.run(run_test())
