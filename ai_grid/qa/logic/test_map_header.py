import asyncio
import sys
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Add root to path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)

from ai_grid.core.handlers.grid import handle_grid_map

class TestMapHeader(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.node = MagicMock()
        self.node.net_name = "Rizon"
        self.node.config = {'nickname': 'Antigravity', 'channel': '#grid'}
        self.node.send = AsyncMock()
        self.node.db = MagicMock()
        self.node.db.get_prefs = AsyncMock(return_value={'radius': 5, 'output_mode': 'human', 'msg_type': 'privmsg'})
        
        # Mock character
        char = MagicMock()
        char.current_node.x, char.current_node.y = 10, 10
        self.node.db.get_character_by_nick = AsyncMock(return_value=char)
        
        # Mock map generation
        self.patcher = patch('ai_grid.core.handlers.grid.generate_ascii_map', AsyncMock(return_value="[MAP]"))
        self.mock_map = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    async def test_fallback_to_net_name(self):
        print("[*] Testing fallback to net_name...")
        # Remove network_name if it exists on the mock
        if hasattr(self.node, 'network_name'):
            del self.node.network_name
        
        await handle_grid_map(self.node, "Tester", "#grid", [])
        
        sent_msgs = [c.args[0] for c in self.node.send.call_args_list]
        header = next((m for m in sent_msgs if "GEOINT" in m and "MAP" in m), None)
        print(f" | Header: {header}")
        self.assertIn("[ Rizon ]", header)
        print(" | Result: [✅] PASS")

    async def test_priority_of_network_name(self):
        print("\n[*] Testing priority of network_name...")
        self.node.network_name = "NeuralNet"
        
        await handle_grid_map(self.node, "Tester", "#grid", [])
        
        sent_msgs = [c.args[0] for c in self.node.send.call_args_list]
        header = next((m for m in sent_msgs if "GEOINT" in m and "MAP" in m), None)
        print(f" | Header: {header}")
        self.assertIn("[ NeuralNet ]", header)
        print(" | Result: [✅] PASS")

if __name__ == "__main__":
    unittest.main()
