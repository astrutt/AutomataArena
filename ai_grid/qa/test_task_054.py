# test_task_054.py
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from ai_grid.core.command_router import CommandRouter
from ai_grid.core.handlers.grid import handle_grid_movement

class TestTask054(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.node = MagicMock()
        self.node.prefix = "x"
        self.node.config = {'nickname': 'Bot', 'channel': '#test'}
        self.node.net_name = "TestNet"
        self.node.send = AsyncMock()
        self.node.db = MagicMock()
        self.node.db.get_location = AsyncMock(return_value={'name': 'OldNode', 'exits': ['north']})
        self.node.db.move_player = AsyncMock(return_value=("Nexus", "Traversed north to Nexus"))
        self.node.active_engine = None
        self.router = CommandRouter(self.node)

    async def test_move_subcommand_alias(self):
        # Test x move n
        with patch('ai_grid.core.handlers.handle_grid_movement', AsyncMock()) as mock_move:
            with patch('ai_grid.core.handlers.base.check_rate_limit', AsyncMock(return_value=True)):
                await self.router.dispatch("Player", "PRIVMSG", "#test", "x move n", False)
                await asyncio.sleep(0.1)
                mock_move.assert_called_once()
                args, _ = mock_move.call_args
                self.assertEqual(args[2], "n")

    async def test_move_diagonal(self):
        # Test x move ne
        with patch('ai_grid.core.handlers.handle_grid_movement', AsyncMock()) as mock_move:
            with patch('ai_grid.core.handlers.base.check_rate_limit', AsyncMock(return_value=True)):
                await self.router.dispatch("Player", "PRIVMSG", "#test", "x move ne", False)
                await asyncio.sleep(0.1)
                mock_move.assert_called_once()
                args, _ = mock_move.call_args
                self.assertEqual(args[2], "ne")

    async def test_tagging_refinement(self):
        # Mock move_player to return a node name
        self.node.db.move_player = AsyncMock(return_value=("Nexus", "Traversed north to Nexus"))
        self.node.db.get_location = AsyncMock(return_value={'name': 'OldNode'})
        
        # Test Machine Mode
        with patch('ai_grid.core.handlers.grid.get_action_routing', AsyncMock(return_value=("Player", "#test", True, "PRIVMSG"))):
            with patch('ai_grid.core.handlers.grid.handle_grid_view', AsyncMock()):
                await handle_grid_movement(self.node, "Player", "north", "#test")
                sent_msgs = [call.args[0] for call in self.node.send.call_args_list]
                # Machine mode tags use KV pairs
                self.assertTrue(any("[ACTION:MOVEMENT][RESULT:MOVED][NICK:Player]" in m for m in sent_msgs))

        self.node.send.reset_mock()

        # Test Human Mode (check for icons and tags, ignoring color codes)
        with patch('ai_grid.core.handlers.grid.get_action_routing', AsyncMock(return_value=("Player", "#test", False, "PRIVMSG"))):
            with patch('ai_grid.core.handlers.grid.handle_grid_view', AsyncMock()):
                await handle_grid_movement(self.node, "Player", "north", "#test")
                sent_msgs = [call.args[0] for call in self.node.send.call_args_list]
                
                # Check for icons - MOVEMENT uses 🚀, TRAVEL uses 🚶
                self.assertTrue(any("🚀" in m for m in sent_msgs))
                self.assertTrue(any("🚶" in m for m in sent_msgs))
                # Check for tags
                self.assertTrue(any("MOVEMENT" in m for m in sent_msgs))
                self.assertTrue(any("TRAVEL" in m for m in sent_msgs))

if __name__ == '__main__':
    unittest.main()
