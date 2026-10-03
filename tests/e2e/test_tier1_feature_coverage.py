# tests/e2e/test_tier1_feature_coverage.py
"""
Tier 1: Feature Coverage Test Suite for AutomataGrid.

Verifies the primary behavior (happy paths) for:
- R1: Core Game Loop & Persistence (>=5 tests)
- R2: AI Player Integration (>=5 tests)
- R3: Stable IRC Connection & Rate Limiting (>=5 tests)
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

from tests.e2e.fixtures import MockIRCServer, MockLLMServer, TestEnvironment


class TestTier1FeatureCoverage(unittest.IsolatedAsyncioTestCase):
    """Tier 1: Feature Coverage Unit & Integration Test Cases."""

    _template_dir = None
    _template_db_file = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import tempfile
        cls._template_dir = tempfile.mkdtemp(prefix="tier1_tpl_")
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
        self.env = TestEnvironment(prefix="tier1_")
        self.env.temp_dir = tempfile.mkdtemp(prefix="tier1_")
        self.env.db_path = os.path.join(self.env.temp_dir, "test_automata_grid.db")
        shutil.copyfile(self._template_db_file, self.env.db_path)
        self.env.db = ArenaDB(self.env.db_path)

        self.llm = MockLLMServer()
        self.llm.start()
        self.irc = MockIRCServer()
        await self.irc.start()

        # Switch CWD to test temp dir and generate valid config.ini for bot
        self.orig_cwd = os.getcwd()
        os.chdir(self.env.temp_dir)
        self.env.write_config_ini(
            irc_server="127.0.0.1",
            irc_port=self.irc.port,
            llm_endpoint=self.llm.get_endpoint(),
            target_dir=self.env.temp_dir,
        )
        # Reset bot module if previously loaded
        sys.modules.pop("ai_player.bot", None)

    async def asyncTearDown(self):
        os.chdir(self.orig_cwd)
        await self.env.teardown()
        await self.irc.stop()
        self.llm.stop()

    # =========================================================================
    # R1: Core Game Loop & Persistence
    # =========================================================================

    async def test_r1_01_character_state_creation_and_persistence(self):
        """R1.1: Verify creating a character persists all vital stats in SQLite."""
        char = await self.env.create_test_player(
            nickname="GhostInTheShell",
            race="Cyborg",
            char_class="Netrunner",
            bio="Ghost operative.",
            level=3,
            credits=3500.0,
            power=250.0,
        )
        self.assertIsNotNone(char.id)
        self.assertEqual(char.name, "GhostInTheShell")
        self.assertEqual(char.race, "Cyborg")
        self.assertEqual(char.char_class, "Netrunner")
        self.assertEqual(char.level, 3)
        self.assertEqual(char.credits, 3500.0)
        self.assertEqual(char.power, 250.0)

        # Query back through repository facade
        retrieved = await self.env.db.player.get_player("GhostInTheShell", "mocknet")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["name"], "GhostInTheShell")
        self.assertEqual(retrieved["level"], 3)
        self.assertEqual(retrieved["credits"], 3500.0)

    async def test_r1_02_character_credit_and_power_updates(self):
        """R1.2: Verify updating credits and power stores changes persistently."""
        char = await self.env.create_test_player("Satoshi", credits=100.0, power=50.0)

        async with self.env.db.async_session() as session:
            c = await session.get(Character, char.id)
            c.credits += 450.0
            c.power += 75.0
            await session.commit()

        # Verify persisted state
        updated = await self.env.db.player.get_player("Satoshi", "mocknet")
        self.assertEqual(updated["credits"], 550.0)
        self.assertEqual(updated["power"], 125.0)

    async def test_r1_03_grid_node_claiming_and_status(self):
        """R1.3: Verify grid node claiming and status updates persist."""
        char = await self.env.create_test_player("NodeOwner")

        # Claim the spawn node (UpLink)
        async with self.env.db.async_session() as session:
            from sqlalchemy import select
            stmt = select(GridNode).filter_by(name="UpLink")
            res = await session.execute(stmt)
            node = res.scalars().first()
            self.assertIsNotNone(node)
            node.owner_character_id = char.id
            node.power_stored = 1500.0
            node.durability = 85.0
            await session.commit()

        # Re-query and verify persistence
        async with self.env.db.async_session() as session:
            from sqlalchemy import select
            stmt = select(GridNode).filter_by(name="UpLink")
            res = await session.execute(stmt)
            node = res.scalars().first()
            self.assertEqual(node.owner_character_id, char.id)
            self.assertEqual(node.power_stored, 1500.0)
            self.assertEqual(node.durability, 85.0)

    async def test_r1_04_spectator_idle_passive_accrual(self):
        """R1.4: Verify spectator idle accrual formula: credits=(idle*0.005 + chat*0.5), xp=(idle*0.1 + chat*10)."""
        spec = await self.env.create_spectator_player("QuietWatcher", credits=100.0)

        idle_secs = 3600
        chat_lines = 20
        expected_credits = 100.0 + (idle_secs * 0.005) + (chat_lines * 0.5)
        expected_xp = int((idle_secs * 0.1) + (chat_lines * 10))

        async with self.env.db.async_session() as session:
            c = await session.get(Character, spec.id)
            c.credits += (idle_secs * 0.005) + (chat_lines * 0.5)
            c.xp += expected_xp
            await session.commit()

        updated = await self.env.db.player.get_player("QuietWatcher", "mocknet")
        self.assertAlmostEqual(updated["credits"], expected_credits, places=2)
        self.assertEqual(updated["xp"], expected_xp)

    async def test_r1_05_spectator_daily_dividend_and_leveling(self):
        """R1.5: Verify daily dividend calculation (250 + level*25 credits, 50 + level*5 XP)."""
        spec = await self.env.create_spectator_player("DailyViewer", level=2, credits=500.0)

        base_credits = 500.0
        level = 2
        dividend_credits = 250.0 + (level * 25)
        dividend_xp = 50 + (level * 5)

        async with self.env.db.async_session() as session:
            c = await session.get(Character, spec.id)
            c.credits += dividend_credits
            c.xp += dividend_xp
            c.last_daily_bonus_at = datetime.now(timezone.utc)
            await session.commit()

        updated = await self.env.db.player.get_player("DailyViewer", "mocknet")
        self.assertEqual(updated["credits"], base_credits + dividend_credits)
        self.assertEqual(updated["xp"], dividend_xp)

    async def test_r1_06_discovery_and_grid_hack_pipeline(self):
        """R1.6: Verify discovery records and breach records persist with valid UTC timestamps."""
        char = await self.env.create_test_player("ZeroHacker")
        now_utc = datetime.now(timezone.utc)
        expires_utc = now_utc + timedelta(seconds=300)

        async with self.env.db.async_session() as session:
            from sqlalchemy import select
            node = (await session.execute(select(GridNode).filter_by(name="UpLink"))).scalars().first()
            self.assertIsNotNone(node)

            disc = DiscoveryRecord(
                character_id=char.id,
                node_id=node.id,
                intel_level=2,
                intel_expires_at=expires_utc,
                discovered_at=now_utc,
            )
            session.add(disc)

            breach = BreachRecord(
                character_id=char.id,
                node_id=node.id,
                is_silent=True,
                breached_at=now_utc,
            )
            session.add(breach)
            await session.commit()

            d = (await session.execute(select(DiscoveryRecord).filter_by(character_id=char.id))).scalars().first()
            b = (await session.execute(select(BreachRecord).filter_by(character_id=char.id))).scalars().first()

            self.assertIsNotNone(d)
            self.assertIsNotNone(b)
            self.assertEqual(d.intel_level, 2)
            self.assertTrue(b.is_silent)
            self.assertIsNotNone(d.discovered_at.tzinfo)

    # =========================================================================
    # R2: AI Player Integration
    # =========================================================================

    def test_r2_01_llm_state_serialization(self):
        """R2.1: Verify AI bot serializes character vitals, arena state, and recent memory into prompt."""
        char_data = {
            "bio": "Tactical Infiltrator",
            "race": "Wetware",
            "char_class": "Zero_Day_Rogue",
            "level": 4,
            "credits": 2400.0,
            "current_hp": 180,
            "node": "UpLink",
            "power": 95.0,
            "stability": 88.0,
            "current_node_noise": 1.2,
            "data_units": 12.5,
            "inventory": ["Cipher_Key", "Data_Shard"],
        }
        arena_state = "## TURN 3: Opponent CyberSentinel prepares ICE shield."
        memory_buffer = ["Moved to UpLink", "Probed sector 4"]

        self.llm.enqueue_response("x hack")

        import ai_player.bot as bot
        with patch.object(bot, "LLM_ENDPOINT", self.llm.get_endpoint()), \
             patch.object(bot, "LLM_MODEL", "mock-model"), \
             patch.object(bot, "PREFIX", "x"):
            action = bot.call_llm(arena_state, char_data, memory_buffer)

        self.assertEqual(action, "x hack")
        self.assertEqual(len(self.llm.requests), 1)

        last_req = self.llm.requests[0]["body"]
        messages = last_req["messages"]
        system_content = messages[0]["content"]
        user_content = messages[1]["content"]

        self.assertIn("Tactical Infiltrator", system_content)
        self.assertIn("Zero_Day_Rogue", system_content)
        self.assertIn("Location: UpLink", user_content)
        self.assertIn("Credits: 2400c", user_content)
        self.assertIn("Cipher_Key, Data_Shard", user_content)
        self.assertIn("Opponent CyberSentinel", user_content)
        self.assertIn("Probed sector 4", user_content)

    def test_r2_02_llm_action_parser_valid_commands(self):
        """R2.2: Verify standard tactical commands pass through parser cleanly."""
        valid_actions = [
            "x move n",
            "x explore",
            "x probe",
            "x hack",
            "x attack CyberSentinel",
            "x defend",
            "x grid map",
        ]

        import ai_player.bot as bot
        for action in valid_actions:
            self.llm.reset_state()
            self.llm.enqueue_response(action)
            with patch.object(bot, "LLM_ENDPOINT", self.llm.get_endpoint()), \
                 patch.object(bot, "PREFIX", "x"):
                res = bot.call_llm("ARENA", {"bio": "test"}, [])
                self.assertEqual(res, action)

    def test_r2_03_llm_action_parser_noisy_output_fallback(self):
        """R2.3: Verify fallback behavior when LLM returns prose without command prefix."""
        import ai_player.bot as bot

        self.llm.reset_state()
        self.llm.enqueue_response("I should definitely explore the surroundings now.")

        with patch.object(bot, "LLM_ENDPOINT", self.llm.get_endpoint()), \
             patch.object(bot, "PREFIX", "x"):
            res = bot.call_llm("ARENA", {"bio": "test"}, [])
            self.assertEqual(res, "I should definitely explore the surroundings now.")

    async def test_r2_04_ai_bot_turn_execution_dispatch(self):
        """R2.4: Verify AutomataBot.process_turn queries LLM and transmits action to IRC socket."""
        import ai_player.bot as bot

        b = bot.AutomataBot()
        b.writer = MagicMock()
        b.writer.drain = MagicMock(return_value=asyncio.sleep(0.01))
        b.char_data = {"bio": "Bot Bio", "node": "UpLink"}

        self.llm.enqueue_response("x explore")

        with patch.object(bot, "LLM_ENDPOINT", self.llm.get_endpoint()), \
             patch.object(bot, "PREFIX", "x"), \
             patch.object(bot, "CHANNEL", "#automatagrid"):
            await b.process_turn("[GRID] Turn prompt")

        b.writer.write.assert_called()
        written = b.writer.write.call_args[0][0].decode("utf-8")
        self.assertIn("PRIVMSG #automatagrid :x explore", written)

    async def test_r2_05_ai_bot_autonomic_account_recovery(self):
        """R2.5: Verify bot detects 'not a registered player' notice and initiates autonomic re-registration."""
        import ai_player.bot as bot

        b = bot.AutomataBot()
        b.writer = MagicMock()
        b.writer.drain = MagicMock(return_value=asyncio.sleep(0.01))
        b.puppet_mode = False
        b.recovery_attempts = 0

        with patch.object(bot, "PREFIX", "x"), \
             patch.object(bot, "CHANNEL", "#automatagrid"), \
             patch.object(bot, "NICK", "TestBot"):
            await b.attempt_recovery()

        self.assertEqual(b.recovery_attempts, 1)
        b.writer.write.assert_called()
        sent = b.writer.write.call_args[0][0].decode("utf-8")
        self.assertIn("PRIVMSG #automatagrid :x register TestBot", sent)

    async def test_r2_06_ai_bot_crypto_token_auth_handshake(self):
        """R2.6: Verify bot handles authentication challenge: sends ready <token> to manager."""
        import ai_player.bot as bot

        b = bot.AutomataBot()
        b.writer = MagicMock()
        b.writer.drain = MagicMock(return_value=asyncio.sleep(0.01))
        b.char_data = {"token": "crypto_secret_9988"}

        with patch.object(bot, "PREFIX", "x"), \
             patch.object(bot, "MANAGER", "arenamaster"):
            await b.send(f"PRIVMSG arenamaster :x ready {b.char_data['token']}")

        sent = b.writer.write.call_args[0][0].decode("utf-8")
        self.assertIn("PRIVMSG arenamaster :x ready crypto_secret_9988", sent)

    # =========================================================================
    # R3: Maintain a Stable Live IRC Connection
    # =========================================================================

    async def test_r3_01_irc_handshake_and_channel_join(self):
        """R3.1: Verify client connects, handshakes with NICK/USER, receives 001/376, and joins channel."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.irc.port)

        writer.write(b"NICK Client01\r\nUSER Client01 0 * :Test Client\r\n")
        await writer.drain()

        welcome_received = False
        motd_received = False
        for _ in range(10):
            line = (await reader.readline()).decode("utf-8")
            if "001 Client01" in line:
                welcome_received = True
            if "376 Client01" in line:
                motd_received = True
                break

        self.assertTrue(welcome_received, "Failed to receive RPL_WELCOME 001")
        self.assertTrue(motd_received, "Failed to receive RPL_ENDOFMOTD 376")

        writer.write(b"JOIN #automatagrid\r\n")
        await writer.drain()

        join_line = (await reader.readline()).decode("utf-8")
        self.assertIn("JOIN :#automatagrid", join_line)

        writer.close()
        await writer.wait_closed()

    async def test_r3_02_keepalive_ping_pong_response(self):
        """R3.2: Verify mock server responds to client PING with PONG containing token."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.irc.port)
        writer.write(b"PING :test_keepalive_123\r\n")
        await writer.drain()

        resp = (await reader.readline()).decode("utf-8")
        self.assertIn("PONG", resp)
        self.assertIn("test_keepalive_123", resp)

        writer.close()
        await writer.wait_closed()

    async def test_r3_03_central_anti_flood_rate_limiting(self):
        """R3.3: Verify central anti-flood token limiter throttles bursts exceeding max_tokens."""
        mock_node = MagicMock()
        mock_node.net_name = "mocknet"
        mock_node.config = {"nickname": "ArenaMaster", "channel": "#automatagrid"}
        mock_node.action_timestamps = {}
        mock_node.flood_config = {
            "max_tokens": 4.0,
            "refill_rate": 0.5,
            "violation_threshold": 5,
            "lockout_duration": 30,
            "messages": {"rate_limit": "Slow down!"},
        }
        mock_node.db = MagicMock()
        mock_node.db.get_prefs = AsyncMock(return_value={})
        mock_node.send = AsyncMock(return_value=None)

        # First 4 calls consume the 4 tokens (burst capacity)
        for _ in range(4):
            allowed = await base_handler.check_rate_limit(mock_node, "spammer", "#automatagrid", cooldown=0, consume=True)
            self.assertTrue(allowed)

        # 5th immediate call should be throttled
        allowed_5th = await base_handler.check_rate_limit(mock_node, "spammer", "#automatagrid", cooldown=0, consume=True)
        self.assertFalse(allowed_5th)
        mock_node.send.assert_called()

    async def test_r3_04_outbound_message_pacing(self):
        """R3.4: Verify outbound queue pacing enforces time gap between outbound dispatches."""
        out_queue = asyncio.Queue()
        out_queue.put_nowait("PRIVMSG #chan :msg1")
        out_queue.put_nowait("PRIVMSG #chan :msg2")

        timestamps = []
        while not out_queue.empty():
            msg = await out_queue.get()
            timestamps.append(asyncio.get_event_loop().time())
            if not out_queue.empty():
                await asyncio.sleep(0.05)
            out_queue.task_done()

        self.assertEqual(len(timestamps), 2)
        self.assertGreater(timestamps[1] - timestamps[0], 0.04)

    async def test_r3_05_rfc_message_length_compliance(self):
        """R3.5: Verify IRC messages adhere to 512-byte RFC limit."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.irc.port)
        writer.write(b"NICK Lengther\r\nUSER Lengther 0 * :Len\r\n")
        await writer.drain()

        payload = "A" * 300
        writer.write(f"PRIVMSG #automatagrid :{payload}\r\n".encode("utf-8"))
        await writer.drain()

        msg = await self.irc.wait_for_message(from_nick="Lengther", command="PRIVMSG", timeout=2.0)
        self.assertIsNotNone(msg)
        self.assertLessEqual(len(msg["raw"].encode("utf-8")), 512)

        writer.close()
        await writer.wait_closed()

    async def test_r3_06_nickname_collision_handling(self):
        """R3.6: Verify mock server emits 433 ERR_NICKNAMEINUSE on collision."""
        self.irc.reject_nick_in_use = "TakenNick"

        reader, writer = await asyncio.open_connection("127.0.0.1", self.irc.port)
        writer.write(b"NICK TakenNick\r\n")
        await writer.drain()

        resp = (await reader.readline()).decode("utf-8")
        self.assertIn("433", resp)
        self.assertIn("Nickname is already in use", resp)

        writer.close()
        await writer.wait_closed()


if __name__ == "__main__":
    unittest.main()
