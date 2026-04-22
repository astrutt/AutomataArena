import asyncio
import sys
import os
import time
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Add root to path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)

from ai_grid.core.handlers.base import check_rate_limit

async def test_flood_customization():
    print("[*] Starting Anti-Flood Message Audit (Task 059)...")
    
    # Load config to get expected messages
    config_path = os.path.join(root_dir, "config.json")
    with open(config_path, 'r') as f:
        config = json.load(f)
    expected_msgs = config.get("flood_messages", {})
    
    # Mock Node
    node = MagicMock()
    node.net_name = "TestNet"
    node.flood_config = {
        'max_tokens': 4.0,
        'refill_rate': 0.5,
        'violation_threshold': 3, # Lowered for faster test
        'lockout_duration': 30,
        'messages': expected_msgs
    }
    node.action_timestamps = {}
    node.send = AsyncMock()
    node.db = MagicMock()
    # Mock get_prefs to return human mode
    node.db.get_prefs = AsyncMock(return_value={'output_mode': 'human', 'msg_type': 'privmsg'})
    
    nick = "Tester"
    reply_target = "#grid"

    async def get_last_msg():
        if not node.send.called: return None
        # Extract message content from PRIVMSG #grid :[TAG] Content
        raw = node.send.call_args.args[0]
        return raw.split(" :")[1]

    print("[1] Testing: pacing_warning...")
    # Drain tokens
    node.action_timestamps[nick.lower()] = {
        'last_action': time.time(),
        'tokens': 0.1, # Not enough for 1.0
        'violations': 0,
        'lockout_until': 0,
        'last_refill': time.time(),
        'warned': False
    }
    
    allowed = await check_rate_limit(node, nick, reply_target, cooldown=0, consume=True)
    if not allowed:
        msg = await get_last_msg()
        print(f" | Found: {msg}")
        # Template is "BANDWIDTH THROTTLED: Neural bucket empty. Refilling... (Next token in {rem}s)"
        if "BANDWIDTH THROTTLED" in msg:
            print(" | Result: [✅] MATCH")
        else:
            print(" | Result: [❌] MISMATCH")
    
    print("\n[2] Testing: cooldown...")
    node.action_timestamps[nick.lower()]['tokens'] = 4.0
    node.action_timestamps[nick.lower()]['warned'] = False
    node.action_timestamps[nick.lower()]['last_action'] = time.time()
    
    allowed = await check_rate_limit(node, nick, reply_target, cooldown=10, consume=True)
    if not allowed:
        msg = await get_last_msg()
        print(f" | Found: {msg}")
        # Template is "PROTOCOL SYNCING: Initializing neural buffer. Please wait {rem}s."
        if "PROTOCOL SYNCING" in msg:
            print(" | Result: [✅] MATCH")
        else:
            print(" | Result: [❌] MISMATCH")

    print("\n[3] Testing: terminal_overflow (Threshold Trigger)...")
    node.action_timestamps[nick.lower()]['tokens'] = 0.0
    node.action_timestamps[nick.lower()]['violations'] = 2 # Threshold is 3
    node.action_timestamps[nick.lower()]['warned'] = False
    
    allowed = await check_rate_limit(node, nick, reply_target, cooldown=0, consume=True)
    if not allowed:
        msg = await get_last_msg()
        print(f" | Found: {msg}")
        # Template is "SYSTEM ALERT: Buffer overflow threshold exceeded. LOCKOUT INITIATED ({lockout_duration}s)."
        if "SYSTEM ALERT" in msg:
            print(" | Result: [✅] MATCH")
        else:
            print(" | Result: [❌] MISMATCH")

    print("\n[4] Testing: hard_lockout...")
    # Now that we are locked out
    allowed = await check_rate_limit(node, nick, reply_target, cooldown=0, consume=True)
    if not allowed:
        msg = await get_last_msg()
        print(f" | Found: {msg}")
        # Template is "NEURAL LINK SEVERED: Critical overflow detected. Terminal access suspended for {rem}s."
        if "NEURAL LINK SEVERED" in msg:
            print(" | Result: [✅] MATCH")
        else:
            print(" | Result: [❌] MISMATCH")

    print("\n[✅] Anti-Flood Customization Audit COMPLETE.")

if __name__ == "__main__":
    asyncio.run(test_flood_customization())
