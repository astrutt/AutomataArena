# test_task_055.py
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from ai_grid.core.handlers.grid import handle_grid_map
from ai_grid.core.handlers.personal import handle_options
from ai_grid.core.command_router import CommandRouter

class TestTask055(unittest.IsolatedAsyncioTestCase):
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
        self.router = CommandRouter(self.node)

    async def test_options_radius(self):
        # Test options radius 7
        await handle_options(self.node, "Player", ["radius", "7"], "#test")
        self.node.db.set_pref.assert_called_with("Player", "TestNet", "radius", 7)
        
        # Test invalid radius
        self.node.db.set_pref.reset_mock()
        await handle_options(self.node, "Player", ["radius", "99"], "#test")
        self.node.db.set_pref.assert_not_called()

    async def test_map_commands(self):
        char = MagicMock()
        char.prefs = '{"radius": 5}'
        char.current_node.x, char.current_node.y = 10, 10
        self.node.db.get_character_by_nick.return_value = char
        
        # 1. Test grid map stats
        await handle_grid_map(self.node, "Player", "#test", ["stats"])
        self.node.db.get_grid_stats.assert_called_once()

        # 2. Test grid map full
        await handle_grid_map(self.node, "Player", "#test", ["full"])
        sent_msgs = [c.args[0] for c in self.node.send.call_args_list]
        self.assertTrue(any("Global Topology Matrix" in m for m in sent_msgs))

        # 3. Test grid map <x> <y>
        with patch('ai_grid.core.handlers.grid.generate_ascii_map', AsyncMock(return_value="[MAP]")) as mock_map:
            await handle_grid_map(self.node, "Player", "#test", ["20", "30"])
            mock_map.assert_called_once()
            _, kwargs = mock_map.call_args
            self.assertEqual(kwargs['center_override'], (20, 30))

if __name__ == '__main__':
    unittest.main()
