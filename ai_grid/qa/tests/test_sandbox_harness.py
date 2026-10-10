"""
tests/test_sandbox_harness.py — Automated Verification for Programmatic Sandbox Harness.
"""

import unittest
from ai_grid.qa.tests.sandbox_harness import SandboxHarness


class TestSandboxHarness(unittest.IsolatedAsyncioTestCase):

    async def test_01_harness_lifecycle(self):
        """Verify harness boots and shuts down cleanly without hanging or port collisions."""
        harness = SandboxHarness()
        await harness.start()
        self.assertIsNotNone(harness.irc_server.port)
        self.assertGreater(harness.irc_server.port, 0)
        self.assertIsNotNone(harness.db)
        await harness.stop()

    async def test_02_command_injection_explore(self):
        """Verify sending command 'explore' returns tactical grid response from ArenaMaster."""
        async with SandboxHarness() as harness:
            reply = await harness.send_command("explore", timeout=5.0)
            self.assertIsNotNone(reply, "Expected reply from ArenaMaster")
            self.assertEqual(reply["from"].lower(), harness.manager_nick.lower())

    async def test_03_db_state_persistence(self):
        """Verify player character state is queryable directly via harness DB helpers."""
        async with SandboxHarness() as harness:
            char = await harness.get_player_character("TestPlayer")
            self.assertIsNotNone(char)
            self.assertEqual(char.name, "TestPlayer")
            self.assertEqual(char.credits, 2000.0)

    async def test_04_grid_node_query(self):
        """Verify grid node state is queryable directly via harness DB helpers."""
        async with SandboxHarness() as harness:
            # Query spawn node or UpLink
            node = await harness.get_grid_node("UpLink")
            self.assertIsNotNone(node)
            self.assertEqual(node.name, "UpLink")

    async def test_05_send_raw_irc(self):
        """Verify raw IRC line injection into the network."""
        async with SandboxHarness() as harness:
            await harness.send_raw_irc("PRIVMSG #automatagrid :Hello world")
            found = False
            for _ in range(50):
                if any("Hello world" in line for line in harness.irc_server.raw_lines):
                    found = True
                    break
                await asyncio.sleep(0.02)
            self.assertTrue(found, "Expected raw line to be received by MockIRCServer")
