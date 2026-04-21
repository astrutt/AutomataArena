# test_task_052.py
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock
from ai_grid.grid_llm import ArenaLLM
from ai_grid.core.loops import idle_payout_loop

class TestTask052(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {
            'llm': {
                'endpoint': 'http://localhost:8000/v1/chat/completions',
                'model': 'gpt-3.5-turbo',
                'temperature': 0.7
            },
            'channel': '#test-grid',
            'mechanics': {'retention': {'decay_rate': 0.01, 'prune_threshold': 30}}
        }
        self.node = MagicMock()
        self.node.config = self.config
        self.node.net_name = "TestNet"
        self.node.llm = ArenaLLM(self.config)
        self.node.llm._make_request = MagicMock(return_value="Humanized reward message! ⚡")
        self.node.send = AsyncMock()
        self.node.db = MagicMock()
        self.node.db.player.add_experience = AsyncMock()
        self.node.db.player.get_player = AsyncMock(return_value=None)
        self.node.db.award_credits_bulk = AsyncMock()
        self.node.db.tick_player_maintenance = AsyncMock()
        self.node.db.tick_retention_policy = AsyncMock(return_value=(0, 0))
        self.node.db.update_activity_stats = AsyncMock()
        self.node.channel_users = {
            'player1': {'join_time': 0, 'chat_lines': 5}
        }

    async def test_idle_payout_humanization(self):
        # We need to bypass the 1 hour sleep for testing
        # We can mock asyncio.sleep
        with unittest.mock.patch('asyncio.sleep', AsyncMock()):
            # We want to run it once and break
            # idle_payout_loop has a 'while True', so we'll use a side effect to raise CancelledError
            self.node.send.side_effect = [None, asyncio.CancelledError]
            
            try:
                await idle_payout_loop(self.node)
            except asyncio.CancelledError:
                pass
            
            # Check if generate_hourly_payout was called
            # Since I mocked _make_request, I should check if the final message contains the mock response
            # The first call to send is usually from loop setup or previous iterations, but here it's the first one
            self.node.send.assert_called()
            args, kwargs = self.node.send.call_args
            self.assertIn("Humanized reward message!", args[0])

    async def test_idle_payout_fallback(self):
        self.node.llm._make_request = MagicMock(return_value="ERROR: Timeout")
        with unittest.mock.patch('asyncio.sleep', AsyncMock()):
            self.node.send.side_effect = [None, asyncio.CancelledError]
            try:
                await idle_payout_loop(self.node)
            except asyncio.CancelledError:
                pass
            
            args, kwargs = self.node.send.call_args
            self.assertIn("delayed neural connection", args[0])
            self.assertIn("⚡💎", args[0])

if __name__ == '__main__':
    unittest.main()
