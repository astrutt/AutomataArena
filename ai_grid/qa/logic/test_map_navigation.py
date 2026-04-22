# ai_grid/qa/logic/test_map_navigation.py
import asyncio
import unittest
import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from ai_grid.core.map_utils import get_node_symbol, generate_ascii_map
from ai_grid.models import Character, GridNode, DiscoveryRecord

class TestMapNavigation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = AsyncMock()
        self.char = MagicMock(spec=Character)
        self.char.id = 1
        self.char.node_id = 10
        self.char.prefs = '{"radius": 5}'
        self.char.current_node = MagicMock(spec=GridNode)
        self.char.current_node.id = 10
        self.char.current_node.x, self.char.current_node.y = 25, 25

    def test_get_node_symbol_single_char(self):
        # 1. Unknown node
        node = MagicMock(spec=GridNode)
        node.id = 20
        sym = get_node_symbol(node, self.char, intel_level="NONE")
        self.assertIn("[?]", sym)

        # 2. Explored node (Civilian)
        node.node_type = "void"
        node.active_target = MagicMock()
        node.active_target.target_type = "CIV"
        sym = get_node_symbol(node, self.char, intel_level="EXPLORE")
        self.assertIn("[C]", sym)

        # 3. Safezone node
        node.active_target = None
        node.node_type = "safezone"
        sym = get_node_symbol(node, self.char, intel_level="EXPLORE")
        self.assertIn("[S]", sym)

        # 4. Priority: Current Node even if NONE intel
        node.id = self.char.node_id
        sym = get_node_symbol(node, self.char, intel_level="NONE")
        self.assertIn("[@]", sym)

    async def test_generate_map_legend_explored(self):
        nodes = [MagicMock(spec=GridNode)]
        nodes[0].id = 100
        nodes[0].x, nodes[0].y = 25, 25
        nodes[0].node_type = "void"
        nodes[0].active_target = None

        disc = MagicMock(spec=DiscoveryRecord)
        disc.node_id = 100
        disc.intel_level = "EXPLORE"
        disc.intel_expires_at = None

        mock_res = MagicMock()
        mock_res.scalars.return_value.all.side_effect = [nodes, [disc]]
        self.session.execute = AsyncMock(return_value=mock_res)

        with patch('ai_grid.core.map_utils.select'):
            map_text = await generate_ascii_map(self.session, self.char, show_legend=True)
            self.assertIn("[EXP]", map_text)
            self.assertIn("Type: [VOD]", map_text)
            self.assertIn("Grid: (25, 25)", map_text)

    async def test_generate_map_legend_probed(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(minutes=45)
        
        nodes = [MagicMock(spec=GridNode)]
        nodes[0].id = 100
        nodes[0].x, nodes[0].y = 25, 25
        nodes[0].node_type = "void"
        nodes[0].upgrade_level = 4
        nodes[0].active_target = None

        disc = MagicMock(spec=DiscoveryRecord)
        disc.node_id = 100
        disc.intel_level = "PROBE"
        disc.intel_expires_at = expires_at

        mock_res = MagicMock()
        mock_res.scalars.return_value.all.side_effect = [nodes, [disc]]
        self.session.execute = AsyncMock(return_value=mock_res)

        with patch('ai_grid.core.map_utils.select'):
            map_text = await generate_ascii_map(self.session, self.char, show_legend=True)
            self.assertIn("[PRB:44]", map_text) 
            self.assertIn("Type: [VOD:4]", map_text)

    async def test_generate_map_legend_expired(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now - datetime.timedelta(minutes=5)
        
        nodes = [MagicMock(spec=GridNode)]
        nodes[0].id = 100
        nodes[0].x, nodes[0].y = 25, 25
        nodes[0].node_type = "void"
        nodes[0].active_target = None

        disc = MagicMock(spec=DiscoveryRecord)
        disc.node_id = 100
        disc.intel_level = "PROBE"
        disc.intel_expires_at = expires_at

        mock_res = MagicMock()
        mock_res.scalars.return_value.all.side_effect = [nodes, [disc]]
        self.session.execute = AsyncMock(return_value=mock_res)

        with patch('ai_grid.core.map_utils.select'):
            map_text = await generate_ascii_map(self.session, self.char, show_legend=True)
            self.assertIn("[EXP]", map_text) 
            self.assertIn("Type: [VOD]", map_text)

if __name__ == '__main__':
    unittest.main()
