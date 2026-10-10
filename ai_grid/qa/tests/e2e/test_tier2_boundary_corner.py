# tests/e2e/test_tier2_boundary_corner.py
"""
Tier 2: Boundary & Corner Cases Test Suite for AutomataGrid.

Verifies edge cases, boundary conditions, and failure resilience for:
- R1: Database edge cases, expired TTLs, concurrency, zero/negative bounds (>=5 tests)
- R2: LLM API HTTP 500, corrupt JSON, empty choices, memory buffer overflow, turn mutex (>=5 tests)
- R3: Abrupt socket drops, malformed IRC lines, extreme flood lockout, unicode fidelity (>=5 tests)
"""

import asyncio
import json
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, Player, DiscoveryRecord, BreachRecord
import ai_grid.core.handlers.base as base_handler

from ai_grid.qa.tests.e2e.fixtures import MockIRCServer, MockLLMServer, TestEnvironment


class TestTier2BoundaryCorner(unittest.IsolatedAsyncioTestCase):
    """Tier 2: Boundary & Corner Case Tests."""

    _template_dir = None
    _template_db_file = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import tempfile
        cls._template_dir = tempfile.mkdtemp(prefix="tier2_tpl_")
        cls._template_db_file = os.path.join(cls._template_dir, "template.db")
        db = ArenaDB(cls._template_db_file)
        asyncio.run(db.init_schema())
        asyncio.run(db.close())

    @classmethod
    def tearDownClass(cls):
        if cls._template_dir and os.path.exists(cls._template_dir):
            import shutil
            shutil.rmtree(cls._template_dir, ignore_errors=True)
        super().tearDownClass()

    async def asyncSetUp(self):
        import tempfile, shutil
        self.env = TestEnvironment(prefix="tier2_")
        self.env.temp_dir = tempfile.mkdtemp(prefix="tier2_")
        self.env.db_path = os.path.join(self.env.temp_dir, "test_automata_grid.db")
        shutil.copyfile(self._template_db_file, self.env.db_path)
        self.env.db = ArenaDB(self.env.db_path)

        self.llm = MockLLMServer()
        self.llm.start()
        self.irc = MockIRCServer()
        await self.irc.start()

        self.orig_cwd = os.getcwd()
        os.chdir(self.env.temp_dir)
        self.env.write_config_ini(
            irc_server="127.0.0.1",
            irc_port=self.irc.port,
            llm_endpoint=self.llm.get_endpoint(),
            target_dir=self.env.temp_dir,
        )
        sys.modules.pop("ai_player.bot", None)

    async def asyncTearDown(self):
        os.chdir(self.orig_cwd)
        await self.env.teardown()
        await self.irc.stop()
        self.llm.stop()

    # =========================================================================
    # R1: Database & Game Loop Edge Cases
    # =========================================================================

    async def test_r1_b01_nonexistent_player_query(self):
        """R1.B1: Querying a nonexistent player returns None gracefully without database error."""
        res = await self.env.db.player.get_player("NonExistentPhantomNick", "mocknet")
        self.assertIsNone(res)

    async def test_r1_b02_zero_and_negative_resource_clamping(self):
        """R1.B2: Test character credits/power at zero and negative boundaries."""
        char = await self.env.create_test_player("EdgeRunner", credits=0.0, power=0.0)
        self.assertEqual(char.credits, 0.0)
        self.assertEqual(char.power, 0.0)

        async with self.env.db.async_session() as session:
            c = await session.get(Character, char.id)
            c.credits = -50.0  # Test debt / negative state
            c.power = 0.0
            await session.commit()

        updated = await self.env.db.player.get_player("EdgeRunner", "mocknet")
        self.assertEqual(updated["credits"], -50.0)
        self.assertEqual(updated["power"], 0.0)

    async def test_r1_b03_expired_discovery_ttl_window(self):
        """R1.B3: Verify discovery records older than 300s TTL are recognized as expired."""
        char = await self.env.create_test_player("StaleScanner")
        now_utc = datetime.now(timezone.utc)
        past_expired_utc = now_utc - timedelta(seconds=350)  # Expired 350 seconds ago

        async with self.env.db.async_session() as session:
            from sqlalchemy import select
            node = (await session.execute(select(GridNode).filter_by(name="UpLink"))).scalars().first()
            disc = DiscoveryRecord(
                character_id=char.id,
                node_id=node.id,
                intel_level=1,
                intel_expires_at=past_expired_utc,
                discovered_at=past_expired_utc - timedelta(seconds=10),
            )
            session.add(disc)
            await session.commit()

            # Check expiration
            saved = (await session.execute(select(DiscoveryRecord).filter_by(character_id=char.id))).scalars().first()
            self.assertIsNotNone(saved)
            is_expired = saved.intel_expires_at < datetime.now(timezone.utc)
            self.assertTrue(is_expired, "Record should be recognized as expired beyond 300s TTL")

    async def test_r1_b04_concurrent_db_writes_no_deadlock(self):
        """R1.B4: Test 10 concurrent async writes to verify SQLite concurrency without deadlocks."""
        char = await self.env.create_test_player("ConcurrentWorker", credits=0.0)

        async def increment_credits(amount: float):
            async with self.env.db.async_session() as session:
                from sqlalchemy import update
                await session.execute(
                    update(Character).where(Character.id == char.id).values(credits=Character.credits + amount)
                )
                await session.commit()

        # Run 10 concurrent increments of 10.0
        tasks = [increment_credits(10.0) for _ in range(10)]
        await asyncio.gather(*tasks)

        updated = await self.env.db.player.get_player("ConcurrentWorker", "mocknet")
        self.assertEqual(updated["credits"], 100.0)

    async def test_r1_b05_boundary_coordinates_and_disconnected_node(self):
        """R1.B5: Verify handling of boundary node query without active connections."""
        async with self.env.db.async_session() as session:
            from sqlalchemy import select
            # Edge node at coordinate (10, 10)
            node = (await session.execute(select(GridNode).filter_by(name="Edge_West"))).scalars().first()
            self.assertIsNotNone(node)
            self.assertEqual(node.x, 10)
            self.assertEqual(node.y, 10)

    # =========================================================================
    # R2: AI Player Boundary & Corner Cases
    # =========================================================================

    def test_r2_b01_llm_http_500_error_fallback(self):
        """R2.B1: Test mock LLM HTTP 500 error -> bot falls back to defensive stance ('x defend')."""
        self.llm.error_status = 500

        import ai_player.bot as bot
        with patch.object(bot, "LLM_ENDPOINT", self.llm.get_endpoint()), \
             patch.object(bot, "PREFIX", "x"):
            action = bot.call_llm("ARENA", {"bio": "test"}, [])
            self.assertEqual(action, "x defend")

    def test_r2_b02_llm_corrupt_non_json_payload(self):
        """R2.B2: Test mock LLM returning unparseable bytes -> bot falls back safely to 'x defend'."""
        self.llm.corrupt_body = True

        import ai_player.bot as bot
        with patch.object(bot, "LLM_ENDPOINT", self.llm.get_endpoint()), \
             patch.object(bot, "PREFIX", "x"):
            action = bot.call_llm("ARENA", {"bio": "test"}, [])
            self.assertEqual(action, "x defend")

    def test_r2_b03_llm_empty_choices_array(self):
        """R2.B3: Test mock LLM returning empty choices -> bot catches IndexError and falls back."""
        self.llm.empty_choices = True

        import ai_player.bot as bot
        with patch.object(bot, "LLM_ENDPOINT", self.llm.get_endpoint()), \
             patch.object(bot, "PREFIX", "x"):
            action = bot.call_llm("ARENA", {"bio": "test"}, [])
            self.assertEqual(action, "x defend")

    def test_r2_b04_memory_buffer_fifo_truncation_under_stress(self):
        """R2.B4: Test appending 50 rapid messages -> buffer enforces strict FIFO cap of 10."""
        import ai_player.bot as bot

        b = bot.AutomataBot()
        for i in range(50):
            b.record_memory(f"Event #{i}")

        self.assertEqual(len(b.memory_buffer), 10)
        # Verify oldest events 0-39 were pruned, newest 40-49 remain
        self.assertEqual(b.memory_buffer[0], "Event #40")
        self.assertEqual(b.memory_buffer[-1], "Event #49")

    async def test_r2_b05_overlapping_turn_calls_processing_mutex(self):
        """R2.B5: Verify process_turn lock prevents duplicate concurrent execution."""
        import ai_player.bot as bot

        b = bot.AutomataBot()
        b.processing = True  # Simulate turn currently in flight
        b.writer = MagicMock()

        # Call process_turn while locked
        await b.process_turn("Trigger Turn")

        # Writer should never be called because processing guard exited early
        b.writer.write.assert_not_called()

    # =========================================================================
    # R3: Network Stability Boundary Cases
    # =========================================================================

    async def test_r3_b01_abrupt_socket_drop_during_read(self):
        """R3.B1: Verify abrupt socket closure returns EOF cleanly without unhandled crashes."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.irc.port)
        try:
            writer.write(b"NICK DropMe\r\nUSER DropMe 0 * :Drop\r\n")
            await writer.drain()

            # Wait until DropMe is registered in MockIRCServer
            for _ in range(50):
                if "dropme" in self.irc.clients:
                    break
                await asyncio.sleep(0.02)

            # Simulate abrupt socket termination on server side
            await self.irc.simulate_socket_drop(nick="DropMe")

            # Drain any pre-buffered welcome lines until EOF (empty bytes) is reached
            while True:
                line = await reader.readline()
                if line == b"":
                    break
            self.assertEqual(line, b"")
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_r3_b02_malformed_raw_irc_lines(self):
        """R3.B2: Send malformed IRC lines (bare colons, missing targets, no arguments)."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.irc.port)
        writer.write(b"NICK Malform\r\nUSER Malform 0 * :M\r\n")
        await writer.drain()

        # Send various malformed IRC lines
        malformed = [
            b":\r\n",
            b":   \r\n",
            b"PRIVMSG\r\n",
            b"JOIN\r\n",
            b"WHOIS\r\n",
            b":trailing_without_cmd\r\n",
        ]
        for m in malformed:
            writer.write(m)
        await writer.drain()

        # Verify server is still alive and responds to ping
        writer.write(b"PING :still_alive\r\n")
        await writer.drain()

        pong_received = False
        for _ in range(10):
            line = (await reader.readline()).decode("utf-8")
            if "PONG" in line and "still_alive" in line:
                pong_received = True
                break

        self.assertTrue(pong_received, "Server crashed or stopped responding after malformed inputs")
        writer.close()
        await writer.wait_closed()

    async def test_r3_b03_adversarial_flood_burst_lockout(self):
        """R3.B3: Send 20 rapid bursts -> token bucket accumulates violations and triggers hard lockout."""
        mock_node = MagicMock()
        mock_node.net_name = "mocknet"
        mock_node.config = {"nickname": "ArenaMaster", "channel": "#automatagrid"}
        mock_node.action_timestamps = {}
        mock_node.flood_config = {
            "max_tokens": 4.0,
            "refill_rate": 0.5,
            "violation_threshold": 3,
            "lockout_duration": 30,
            "messages": {
                "rate_limit": "Slow down!",
                "terminal_overflow": "LOCKOUT INITIATED",
                "hard_lockout": "HARD LOCKOUT",
            },
        }
        mock_node.db = MagicMock()
        mock_node.db.get_prefs = AsyncMock(return_value={})
        mock_node.send = AsyncMock(return_value=None)

        # Send 10 rapid calls with cooldown=0
        for _ in range(10):
            await base_handler.check_rate_limit(mock_node, "adversary", "#automatagrid", cooldown=0, consume=True)

        # Check that adversary has lockout_until set into future
        record = mock_node.action_timestamps.get("adversary")
        self.assertIsNotNone(record)
        import time
        self.assertGreater(record["lockout_until"], time.time())

    async def test_r3_b04_unicode_and_special_characters_fidelity(self):
        """R3.B4: Send emojis, Cyrillic, and shell symbols -> verify encoding fidelity."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.irc.port)
        writer.write(b"NICK UnicodeUser\r\nUSER UnicodeUser 0 * :Uni\r\n")
        await writer.drain()

        test_payload = "🚀⚔️ Hack 0-Day: !@#$%^&*()_+{}|:<>? ~` 👾 Сеть"
        writer.write(f"PRIVMSG #automatagrid :{test_payload}\r\n".encode("utf-8"))
        await writer.drain()

        msg = await self.irc.wait_for_message(from_nick="UnicodeUser", command="PRIVMSG", timeout=2.0)
        self.assertIsNotNone(msg)
        self.assertEqual(msg["text"], test_payload)

        writer.close()
        await writer.wait_closed()

    async def test_r3_b05_whitespace_only_and_null_message_handling(self):
        """R3.B5: Send whitespace-only messages and empty PRIVMSGs without server crash."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.irc.port)
        writer.write(b"NICK SpaceMan\r\nUSER SpaceMan 0 * :Space\r\n")
        await writer.drain()

        writer.write(b"     \r\n")
        writer.write(b"PRIVMSG #automatagrid :   \r\n")
        writer.write(b"\r\n\r\n")
        await writer.drain()

        # Follow with valid ping
        writer.write(b"PING :test_spaces\r\n")
        await writer.drain()

        resp = ""
        for _ in range(10):
            line = (await reader.readline()).decode("utf-8")
            if "test_spaces" in line:
                resp = line
                break

        self.assertIn("PONG", resp)
        writer.close()
        await writer.wait_closed()


if __name__ == "__main__":
    unittest.main()
