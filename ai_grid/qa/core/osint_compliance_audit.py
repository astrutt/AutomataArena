import asyncio
import os
import sys

# Root inclusion for modules import
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'ai_grid'))

import ai_grid.grid_utils as grid_utils
grid_utils.CONFIG = {'logging': {'level': 'DEBUG'}}

from ai_grid.core.handlers.osint import (
    handle_economy_osint, handle_gridpower_osint, handle_networks_osint
)

class MockDB:
    async def get_prefs(self, nick, net):
        return {'output_mode': self.mode, 'msg_type': 'privmsg'}
    async def get_global_economy(self):
        return {'total_credits': 1000000, 'total_data_units': 500.5}
    async def get_market_status(self):
        return {'junk': 1.15}
    async def get_grid_telemetry(self):
        return {'total_nodes': 10, 'total_power': 450.0, 'total_generation': 50.0, 'claimed_nodes': 3, 'claimed_percent': 30.0}

class MockHub:
    def __init__(self):
        self.nodes = {'net1': type('obj', (object,), {'net_name': 'testnet', 'config': {'channel': '#test'}, 'registered_bots': 5})}

class MockNode:
    def __init__(self):
        self.prefix = "!"
        self.net_name = "testnet"
        self.config = {"nickname": "Antigravity", "channel": "#grid"}
        self.db = MockDB()
        self.hub = MockHub()
        self.action_timestamps = {}
        self.sent = []
    async def send(self, msg):
        self.sent.append(msg)

async def test_osint_machine_mode():
    print("\n[TEST 1] OSINT Machine Mode Compliance")
    node = MockNode()
    node.db.mode = "machine"
    
    # 1. Economy
    node.action_timestamps = {}
    await handle_economy_osint(node, "AI_Bot", "AI_Bot")
    out = node.sent[-1]
    print(f" > Economy: {out}")
    if "[OSINT] ECONOMY|CIRCULATING:1000000|RESERVES:500.5|VARIANCE:1.15" in out:
        print("   SUCCESS: Economy KV format verified.")
    else:
        print("   FAILURE: Economy format mismatch.")

    # 2. GridPower
    node.action_timestamps = {}
    await handle_gridpower_osint(node, "AI_Bot", "AI_Bot")
    out = node.sent[-1]
    print(f" > Power: {out}")
    if "[OSINT] GRIDPOWER|STORED:450|CAPACITY:10000|GEN:50" in out:
        print("   SUCCESS: Power KV format verified.")
    else:
        print("   FAILURE: Power format mismatch.")

    # 3. Topology
    node.action_timestamps = {}
    await handle_networks_osint(node, "AI_Bot", "AI_Bot")
    out = node.sent[-1]
    print(f" > Topology: {out}")
    if "[OSINT] TOPOLOGY|NETS:testnet:5" in out:
        print("   SUCCESS: Topology KV format verified.")
    else:
        print("   FAILURE: Topology format mismatch.")

async def test_osint_rate_limiting():
    print("\n[TEST 2] OSINT Flood Protection")
    node = MockNode()
    node.db.mode = "human"
    
    # Call 1: Should pass
    await handle_economy_osint(node, "Spammer", "#grid")
    
    # Call 2: Should be throttled (cooldown default 2s)
    await handle_economy_osint(node, "Spammer", "#grid")
    
    await asyncio.sleep(0.1) # Allow background warning task to run
    out = "\n".join(node.sent)
    if "Anti-flood MCP triggered" in out:
        print("   SUCCESS: Rate limiting enforced on OSINT commands.")
    else:
        print("   FAILURE: Flood protection bypassed.")

if __name__ == "__main__":
    asyncio.run(test_osint_machine_mode())
    asyncio.run(test_osint_rate_limiting())
