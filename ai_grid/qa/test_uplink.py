# test_uplink.py
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from ai_grid.database.repositories.navigation_repo import NavigationRepository
from ai_grid.models import Character, GridNode, DiscoveryRecord

class TestUplink(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = MagicMock()
        self.session.execute = AsyncMock()
        self.session.commit = AsyncMock()
        self.repo = NavigationRepository(MagicMock())
        self.repo.async_session = MagicMock()
        self.repo.async_session.return_value.__aenter__ = AsyncMock(return_value=self.session)
        self.repo.async_session.return_value.__aexit__ = AsyncMock()

    async def test_bridge_traversal_logic(self):
        # Mock Character and Node
        char = MagicMock(spec=Character)
        char.id = 1
        char.power = 100
        char.current_node = MagicMock(spec=GridNode)
        char.current_node.net_affinity = "Rizon"
        char.current_node.addons_json = '{"NET": true}'
        char.current_node.name = "Nexus"
        char.current_node.availability_mode = 'OPEN'
        char.current_node.owner_character_id = 1
        
        # Mock Session results
        # 1. get character
        res_char = MagicMock()
        res_char.scalars().first.return_value = char
        
        # 2. Find landing node
        landing_node = MagicMock(spec=GridNode)
        landing_node.id = 2
        landing_node.name = "LandingZone"
        landing_node.availability_mode = 'OPEN'
        res_entry = MagicMock()
        res_entry.scalars().first.return_value = landing_node
        
        # 3. Discovery record
        res_disc = MagicMock()
        res_disc.scalars().first.return_value = None # New discovery
        
        # Setup session.execute to return these in order
        self.session.execute.side_effect = [res_char, res_entry, res_disc]
        
        # Override CONFIG for move cost
        with patch('ai_grid.database.repositories.navigation_repo.CONFIG', {'mechanics': {'action_costs': {'move': 1.0}}, 'networks': {'rizon': {'enabled': True}}}):
            # Attempt move to "Rizon"
            node_name, msg = await self.repo.move_player("Player", "TestNet", "Rizon")
            
            self.assertEqual(node_name, "LandingZone")
            self.assertIn("BRIDGE ESTABLISHED", msg)
            self.assertEqual(char.node_id, 2)
            self.assertEqual(char.power, 98) # 100 - (1.0 * 2)

if __name__ == '__main__':
    unittest.main()
