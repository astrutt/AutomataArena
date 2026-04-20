import asyncio
import os
import sys

# Root inclusion for models import
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'ai_grid'))

import grid_utils
grid_utils.CONFIG = {'logging': {'level': 'DEBUG'}}

from ai_grid.core.arena import set_dynamic_topic

class MockDB:
    async def list_players(self, net): return ["Player1", "Player2"]
    async def get_grid_telemetry(self):
        return {'claimed_nodes': 5, 'total_nodes': 20, 'claimed_percent': 25.0, 'total_power': 450.5}

class MockLLM:
    async def generate_topic(self, bots, net):
        return "SIGINT: Rogue process detected in Sub-Sector 4. DarkNet traffic surging."

class MockNode:
    def __init__(self):
        self.net_name = "2600net"
        self.config = {"channel": "#grid"}
        self.topic_mode = 0
        self.registered_bots = 2
        self.active_engine = None
        self.hype_counter = 7
        self.match_queue = ["P1", "P2"]
        self.db = MockDB()
        self.llm = MockLLM()
        self.sent = []
    async def send(self, msg):
        self.sent.append(msg)

async def test_topic_rotations():
    print("\n[TEST] Channel Topic Engine Aesthetic Audit")
    node = MockNode()
    
    modes = ["STATUS", "INTEL", "NEWS", "EVENTS"]
    
    for i in range(4):
        node.topic_mode = i
        node.sent = []
        await set_dynamic_topic(node)
        
        output = node.sent[0] if node.sent else "NO OUTPUT"
        print(f"\n--- MODE {i} ({modes[i]}) ---")
        # Clean IRC codes for console visibility if needed, but here we want to see the formatting
        print(f"OUTPUT: {output}")
        
        # Verification Checks
        if "『" in output and "』" in output and "░▒▓" in output:
            print(f"SUCCESS: Cyber-Clean branding detected in {modes[i]} mode.")
        else:
            print(f"FAILURE: Missing branding in {modes[i]} mode.")
            
        if i == 0 and "LOAD:" in output: print(" > Telemetry Meter: Found.")
        if i == 1 and "MESH:" in output: print(" > Grid Metrics: Found.")
        if i == 2 and "SIGINT:" in output: print(" > AI News Ticker: Found.")
        if i == 3 and "QUEUE:" in output: print(" > Event Status: Found.")

if __name__ == "__main__":
    asyncio.run(test_topic_rotations())
