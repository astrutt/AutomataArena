import asyncio
import os
import json
import unittest
from unittest.mock import MagicMock, patch

# Mocking config and character loading before importing bot
with open('config.ini', 'w') as f:
    f.write("[IRC]\nServer = localhost\nPort = 6667\nUseSSL = False\nNickname = TestBot\nChannel = #test\nManagerNick = GridManager\nPrefix = !\n[LLM]\nEndpoint = http://test/v1\nModel = test-model\n[LOGGING]\nLevel = DEBUG\n[BOT]\nRace = Android\nClass = Hacker\nTraits = fast\n")

if os.path.exists('character.json'):
    os.remove('character.json')

import ai_player.bot as bot

class MockWriter:
    def __init__(self):
        self.sent = []
    def write(self, data):
        self.sent.append(data.decode('utf-8'))
    async def drain(self):
        pass

class TestBotRecovery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = bot.AutomataBot()
        self.bot.writer = MockWriter()
        self.bot.char_data = {"token": "old_token"}
        with open('character.json', 'w') as f:
            json.dump(self.bot.char_data, f)

    async def test_account_loss_detection_and_purge(self):
        print("\n[TEST] Detecting Account Loss & State Purge")
        # Trigger message from Manager
        msg = "[GRID][MCP][ERR] TestBot - not a registered player"
        
        # Simulate the listen_loop logic for PRIVMSG from MANAGER
        if "[GRID][MCP][ERR]" in msg and "not a registered player" in msg:
            await self.bot.attempt_recovery()
        
        # 1. State should be purged
        self.assertIsNone(self.bot.char_data)
        self.assertFalse(os.path.exists('character.json'))
        print("SUCCESS: Local character state purged.")

        # 2. Registration sequence should be sent
        sent_msgs = "".join(self.bot.writer.sent)
        self.assertIn("PRIVMSG #test :! register TestBot Android Hacker fast", sent_msgs)
        print("SUCCESS: Registration sequence emitted.")

    async def test_circuit_breaker(self):
        print("\n[TEST] Recovery Circuit Breaker (3 Attempts)")
        self.bot.recovery_attempts = 2
        self.bot.last_recovery_time = 0 # Force immediate
        
        # Third attempt
        await self.bot.attempt_recovery()
        self.assertEqual(self.bot.recovery_attempts, 3)
        self.assertFalse(self.bot.puppet_mode)
        
        # Fourth attempt
        self.bot.last_recovery_time = 0 
        await self.bot.attempt_recovery()
        self.assertTrue(self.bot.puppet_mode)
        print("SUCCESS: Circuit breaker triggered after 3 failures.")

    async def asyncTearDown(self):
        if os.path.exists('config.ini'): os.remove('config.ini')
        if os.path.exists('character.json'): os.remove('character.json')

if __name__ == "__main__":
    unittest.main()
