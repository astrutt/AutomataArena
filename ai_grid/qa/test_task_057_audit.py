# ai_grid/qa/test_task_055_audit.py
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from ai_grid.core.handlers.grid import handle_grid_map
from ai_grid.core.handlers.personal import handle_options
from ai_grid.core.map_utils import get_node_symbol

class TestTask057Audit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.node = MagicMock()
        self.node.prefix = "x"
        self.node.net_name = "TestNet"
        self.node.config = {'nickname': 'Antigravity', 'channel': '#grid', 'web_url': 'https://test.io'}
        self.node.send = AsyncMock()
        self.node.db = MagicMock()
        self.node.db.get_prefs = AsyncMock(return_value={'radius': 5, 'output_mode': 'human'})
        self.node.db.set_pref = AsyncMock()
        self.node.db.get_character_by_nick = AsyncMock()
        self.node.db.get_grid_stats = AsyncMock(return_value="TOTAL_NODES: 100")
        self.node.active_engine = None

    async def test_radius_cap(self):
        # Test max 10
        await handle_options(self.node, "Player", ["radius", "10"], "#test")
        self.node.db.set_pref.assert_called_with("Player", "TestNet", "radius", 10)
        
        # Test out of bounds (11)
        self.node.db.set_pref.reset_mock()
        await handle_options(self.node, "Player", ["radius", "11"], "#test")
        self.node.db.set_pref.assert_not_called()

    def test_iconography_gov(self):
        # Create a mock node with a GOV raid target
        node = MagicMock()
        node.id = 5
        node.node_type = "void"
        node.availability_mode = "OPEN"
        node.owner_character_id = None
        node.active_target = MagicMock()
        node.active_target.target_type = "GOV"
        
        char = MagicMock()
        char.node_id = 10 # Player is elsewhere
        
        # Test with EXPLORE intel
        symbol = get_node_symbol(node, char, intel_level="EXPLORE")
        self.assertIn("[G]", symbol)
        
        # Test with PROBE intel
        symbol = get_node_symbol(node, char, intel_level="PROBE")
        self.assertIn("[G]", symbol)
        
        # Test with NONE intel (should show Fog of War)
        symbol = get_node_symbol(node, char, intel_level="NONE")
        self.assertIn("[?]", symbol)

    def test_iconography_mil(self):
        node = MagicMock()
        node.id = 6
        node.node_type = "void"
        node.availability_mode = "OPEN"
        node.owner_character_id = None
        node.active_target = MagicMock()
        node.active_target.target_type = "MIL"
        
        char = MagicMock()
        char.node_id = 10
        
        symbol = get_node_symbol(node, char, intel_level="EXPLORE")
        self.assertIn("[M]", symbol)

if __name__ == '__main__':
    unittest.main()
