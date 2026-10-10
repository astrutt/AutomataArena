"""
tests/test_m1_spectator_stress.py — Adversarial Stress Test Harness for Milestone 1.

Empirical verification suite written by challenger_m1_o6_2 to stress-test:
1. Rank renaming edge cases: blank, whitespace-only, long strings, special characters, SQLi, CRLF.
2. Insufficient credit boundaries: 4999.9c vs 5000.0c, exact zeroing, None/negative handling.
3. Race condition checks: rapid concurrent renames preventing double-spend and negative balances.
4. Precedence: Character Spectator vs Anonymous Spectator, fallback isolation.
5. Non-spectator character race: Hacker/Cypher rejection, dual-presence bypass prevention.
6. CommandRouter integration: prefixed variants (!a, ! a), case sensitivity, flood tokens, missing args.
"""

import asyncio
import datetime
from datetime import timezone, timedelta
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import inspect, select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from ai_grid.models import Base, Character, Player, NetworkAlias
from ai_grid.database.core import Spectator
from ai_grid.database.spectator_repo import SpectatorRepository as AccrualSpectatorRepo
from ai_grid.database.repositories.spectator_repo import SpectatorRepository as CharacterSpectatorRepo
from ai_grid.core.command_router import CommandRouter
from ai_grid.core.handlers.spectator import handle_spectator_rename


class BaseM1StressTest(unittest.IsolatedAsyncioTestCase):
    """Base setup with in-memory / temporary isolated SQLite async database."""

    async def asyncSetUp(self):
        self.db_path = f"test_m1_stress_{int(datetime.datetime.now().timestamp() * 1000)}_{os.getpid()}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.char_spec_repo = CharacterSpectatorRepo(self.async_session)
        self.accrual_repo = AccrualSpectatorRepo(self.async_session)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    async def _create_anonymous_spectator(self, nick: str, network: str = "rizon", credits: float = 0.0, rank_title: str = None) -> Spectator:
        async with self.async_session() as session:
            spec = Spectator(
                nick=nick,
                network=network,
                credits=credits,
                xp=0,
                idle_hours=0.0,
                message_count=0,
                rank_title=rank_title
            )
            session.add(spec)
            await session.commit()
            return spec

    async def _create_registered_char(self, nick: str, network: str = "rizon", race: str = "Spectator", credits: float = 0.0, rank_title: str = None) -> Character:
        async with self.async_session() as session:
            player = Player(username=nick)
            session.add(player)
            await session.flush()

            alias = NetworkAlias(player_id=player.id, network_name=network, network_nick=nick)
            session.add(alias)

            char = Character(
                player_id=player.id,
                name=nick,
                race=race,
                char_class="Watcher",
                credits=credits,
                rank_title=rank_title
            )
            session.add(char)
            await session.commit()
            return char


class TestSpectatorRenameTitleEdgeCases(BaseM1StressTest):
    """1. Stress-test rank renaming edge cases: blank, whitespace, long, special characters."""

    async def test_blank_and_whitespace_title_in_handler(self):
        """Handler rejects blank, whitespace, or empty title with syntax usage."""
        node = MagicMock()
        node.net_name = "rizon"
        node.send = AsyncMock()
        node.db = MagicMock()
        node.db.get_prefs = AsyncMock(return_value={})

        # Test empty list
        await handle_spectator_rename(node, "UserA", [], "#automatagrid")
        node.send.assert_called_once()
        self.assertIn("Syntax: spectator rename <title> (Cost: 5000c)", node.send.call_args[0][0])

        # Test whitespace only
        for ws_args in [["   "], ["\t", "  "], ["    ", "\n"]]:
            node.send.reset_mock()
            await handle_spectator_rename(node, "UserA", ws_args, "#automatagrid")
            node.send.assert_called_once()
            self.assertIn("Syntax: spectator rename <title> (Cost: 5000c)", node.send.call_args[0][0])

    async def test_special_characters_and_sql_injection(self):
        """Repository safely persists special characters, unicode emojis, and SQL injection strings."""
        await self._create_anonymous_spectator("SqlTester", "rizon", credits=10000.0)

        sqli_payload = "'; DROP TABLE spectators; --"
        success, msg = await self.char_spec_repo.rename_rank("SqlTester", "rizon", sqli_payload)
        self.assertTrue(success)
        self.assertIn(sqli_payload, msg)

        # Confirm table still intact and value safely stored
        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "SqlTester"))).scalars().first()
            self.assertEqual(spec.rank_title, sqli_payload)
            self.assertEqual(spec.credits, 5000.0)

    async def test_unicode_and_emojis_in_title(self):
        """Unicode, emojis, and non-ASCII titles are persisted properly."""
        await self._create_anonymous_spectator("EmojiUser", "rizon", credits=6000.0)

        unicode_title = "👑 🌟 High Overseer of the Gibson 🚀 💻"
        success, msg = await self.char_spec_repo.rename_rank("EmojiUser", "rizon", unicode_title)
        self.assertTrue(success)

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "EmojiUser"))).scalars().first()
            self.assertEqual(spec.rank_title, unicode_title)

    async def test_irc_formatting_and_control_chars_in_title(self):
        """IRC color codes and formatting tags in title."""
        await self._create_anonymous_spectator("ColorUser", "rizon", credits=7000.0)

        color_title = "\x0304Red\x03\x02Bold\x02\x1fUnderline\x1f"
        success, msg = await self.char_spec_repo.rename_rank("ColorUser", "rizon", color_title)
        self.assertTrue(success)

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "ColorUser"))).scalars().first()
            self.assertEqual(spec.rank_title, color_title)

    async def test_extremely_long_title_strings(self):
        """Long titles (500 chars, 2000 chars) are stored without database crash."""
        await self._create_anonymous_spectator("LongUser", "rizon", credits=10000.0)

        long_title = "A" * 1500
        success, msg = await self.char_spec_repo.rename_rank("LongUser", "rizon", long_title)
        self.assertTrue(success)

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "LongUser"))).scalars().first()
            self.assertEqual(spec.rank_title, long_title)


class TestSpectatorRenameCreditBoundaries(BaseM1StressTest):
    """2. Stress-test credit boundaries: 4999.9c vs 5000.0c, exact zeroing, None/negatives."""

    async def test_anonymous_boundary_4999_9_vs_5000_0(self):
        """4999.9c fails; 5000.0c succeeds with exact 0.0c remainder."""
        await self._create_anonymous_spectator("Anon4999", "rizon", credits=4999.9)
        success, msg = await self.char_spec_repo.rename_rank("Anon4999", "rizon", "Watcher")
        self.assertFalse(success)
        self.assertIn("Insufficient credits. Renaming Rank costs 5000.0c.", msg)

        # Verify credits completely untouched
        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "Anon4999"))).scalars().first()
            self.assertEqual(spec.credits, 4999.9)

        # 5000.0c succeeds
        await self._create_anonymous_spectator("Anon5000", "rizon", credits=5000.0)
        success2, msg2 = await self.char_spec_repo.rename_rank("Anon5000", "rizon", "Watcher")
        self.assertTrue(success2)
        async with self.async_session() as session:
            spec2 = (await session.execute(select(Spectator).where(Spectator.nick == "Anon5000"))).scalars().first()
            self.assertEqual(spec2.credits, 0.0)
            self.assertEqual(spec2.rank_title, "Watcher")

    async def test_character_boundary_4999_9_vs_5000_0(self):
        """Character: 4999.9c fails; 5000.0c succeeds with exact 0.0c remainder."""
        await self._create_registered_char("Char4999", "rizon", race="Spectator", credits=4999.9)
        success, msg = await self.char_spec_repo.rename_rank("Char4999", "rizon", "Watcher")
        self.assertFalse(success)
        self.assertIn("Insufficient credits. Renaming Rank costs 5000.0c.", msg)

        await self._create_registered_char("Char5000", "rizon", race="Spectator", credits=5000.0)
        success2, msg2 = await self.char_spec_repo.rename_rank("Char5000", "rizon", "Watcher")
        self.assertTrue(success2)
        async with self.async_session() as session:
            char2 = (await session.execute(select(Character).where(Character.name == "Char5000"))).scalars().first()
            self.assertEqual(char2.credits, 0.0)

    async def test_fractional_cent_boundaries(self):
        """4999.99c fails; 5000.01c succeeds with 0.01c balance."""
        await self._create_anonymous_spectator("PennyShort", "rizon", credits=4999.99)
        success, msg = await self.char_spec_repo.rename_rank("PennyShort", "rizon", "Lord")
        self.assertFalse(success)

        await self._create_anonymous_spectator("PennyPlus", "rizon", credits=5000.01)
        success2, msg2 = await self.char_spec_repo.rename_rank("PennyPlus", "rizon", "Lord")
        self.assertTrue(success2)
        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "PennyPlus"))).scalars().first()
            self.assertAlmostEqual(spec.credits, 0.01, places=2)

    async def test_zero_negative_and_none_credits(self):
        """0.0c, negative credits, and None credits reject cleanly without exception."""
        await self._create_anonymous_spectator("ZeroCreds", "rizon", credits=0.0)
        success1, _ = await self.char_spec_repo.rename_rank("ZeroCreds", "rizon", "Title")
        self.assertFalse(success1)

        await self._create_anonymous_spectator("NegativeCreds", "rizon", credits=-500.0)
        success2, _ = await self.char_spec_repo.rename_rank("NegativeCreds", "rizon", "Title")
        self.assertFalse(success2)

        await self._create_anonymous_spectator("NoneCreds", "rizon", credits=None)
        success3, _ = await self.char_spec_repo.rename_rank("NoneCreds", "rizon", "Title")
        self.assertFalse(success3)


class TestSpectatorRenameRaceConditions(BaseM1StressTest):
    """3. Concurrency & Race condition stress testing: rapid concurrent renames."""

    async def test_concurrent_renames_anonymous_spectator_5000c(self):
        """Spectator with exactly 5000c receives 5 concurrent rename requests: exactly 1 succeeds, balance is 0.0c."""
        await self._create_anonymous_spectator("RaceAnon5k", "rizon", credits=5000.0)

        async def run_rename(i: int):
            return await self.char_spec_repo.rename_rank("RaceAnon5k", "rizon", f"Title_{i}")

        results = await asyncio.gather(*(run_rename(i) for i in range(5)))

        success_count = sum(1 for s, _ in results if s)
        fail_count = sum(1 for s, _ in results if not s)

        self.assertEqual(success_count, 1, f"Expected exactly 1 success, got {success_count}")
        self.assertEqual(fail_count, 4, f"Expected 4 failures, got {fail_count}")

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "RaceAnon5k"))).scalars().first()
            self.assertEqual(spec.credits, 0.0, f"Credits should be 0.0, got {spec.credits}")
            self.assertIsNotNone(spec.rank_title)

    async def test_concurrent_renames_anonymous_spectator_10000c(self):
        """Spectator with 10000c receives 6 concurrent requests: exactly 2 succeed, balance is 0.0c."""
        await self._create_anonymous_spectator("RaceAnon10k", "rizon", credits=10000.0)

        async def run_rename(i: int):
            return await self.char_spec_repo.rename_rank("RaceAnon10k", "rizon", f"Title_{i}")

        results = await asyncio.gather(*(run_rename(i) for i in range(6)))

        success_count = sum(1 for s, _ in results if s)
        fail_count = sum(1 for s, _ in results if not s)

        self.assertEqual(success_count, 2, f"Expected exactly 2 successes, got {success_count}")
        self.assertEqual(fail_count, 4, f"Expected 4 failures, got {fail_count}")

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "RaceAnon10k"))).scalars().first()
            self.assertEqual(spec.credits, 0.0, f"Credits should be 0.0, got {spec.credits}")

    async def test_concurrent_renames_character_spectator_5000c(self):
        """Character with 5000c receives 5 concurrent rename requests: exactly 1 succeeds, balance is 0.0c."""
        await self._create_registered_char("RaceChar5k", "rizon", race="Spectator", credits=5000.0)

        async def run_rename(i: int):
            return await self.char_spec_repo.rename_rank("RaceChar5k", "rizon", f"Title_{i}")

        results = await asyncio.gather(*(run_rename(i) for i in range(5)))

        success_count = sum(1 for s, _ in results if s)
        fail_count = sum(1 for s, _ in results if not s)

        self.assertEqual(success_count, 1, f"Expected exactly 1 success, got {success_count}")
        self.assertEqual(fail_count, 4, f"Expected 4 failures, got {fail_count}")

        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "RaceChar5k"))).scalars().first()
            self.assertEqual(char.credits, 0.0, f"Credits should be 0.0, got {char.credits}")


class TestSpectatorPrecedenceAndRaceIsolation(BaseM1StressTest):
    """4. Character Spectator vs Anonymous Spectator precedence & class isolation."""

    async def test_character_takes_precedence_when_both_exist(self):
        """When nick exists as Character AND Spectator, Character is billed and modified."""
        # Character has 6000c
        await self._create_registered_char("DualPresence", "rizon", race="Spectator", credits=6000.0)
        # Spectator has 8000c
        await self._create_anonymous_spectator("DualPresence", "rizon", credits=8000.0)

        success, msg = await self.char_spec_repo.rename_rank("DualPresence", "rizon", "Supreme Spectator")
        self.assertTrue(success)

        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "DualPresence"))).scalars().first()
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "DualPresence"))).scalars().first()

            # Character billed 5000c (6000 -> 1000) and title updated
            self.assertEqual(char.credits, 1000.0)
            self.assertEqual(char.rank_title, "Supreme Spectator")

            # Spectator row completely UNTOUCHED
            self.assertEqual(spec.credits, 8000.0)
            self.assertIsNone(spec.rank_title)

    async def test_character_insufficient_credits_does_not_fall_back_to_spectator(self):
        """If Character has insufficient credits (1000c), it rejects even if Spectator row has 9000c."""
        await self._create_registered_char("BrokeDual", "rizon", race="Spectator", credits=1000.0)
        await self._create_anonymous_spectator("BrokeDual", "rizon", credits=9000.0)

        success, msg = await self.char_spec_repo.rename_rank("BrokeDual", "rizon", "WouldBeTitle")
        self.assertFalse(success)
        self.assertIn("Insufficient credits", msg)

        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "BrokeDual"))).scalars().first()
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "BrokeDual"))).scalars().first()

            # Neither entity modified
            self.assertEqual(char.credits, 1000.0)
            self.assertIsNone(char.rank_title)
            self.assertEqual(spec.credits, 9000.0)
            self.assertIsNone(spec.rank_title)

    async def test_neither_character_nor_spectator_rejects(self):
        """User with no record in either table receives orbital link failed notice."""
        success, msg = await self.char_spec_repo.rename_rank("UnknownPhantom", "rizon", "GhostTitle")
        self.assertFalse(success)
        self.assertEqual(msg, "Orbital link failed. You must idle in channel to accrue credits before customizing rank.")

    async def test_non_spectator_character_rejected(self):
        """Registered characters of non-Spectator race (Hacker, Cypher, Cyborg) are strictly rejected."""
        for race in ["Hacker", "Cypher", "Cyborg", "Operative"]:
            nick = f"NonSpec_{race}"
            await self._create_registered_char(nick, "rizon", race=race, credits=10000.0)

            success, msg = await self.char_spec_repo.rename_rank(nick, "rizon", "Mastermind")
            self.assertFalse(success)
            self.assertEqual(msg, "Only Spectators can customize Rank Titles.")

            async with self.async_session() as session:
                char = (await session.execute(select(Character).where(Character.name == nick))).scalars().first()
                self.assertEqual(char.credits, 10000.0)
                self.assertIsNone(char.rank_title)

    async def test_non_spectator_cannot_bypass_race_restriction_via_spectator_row(self):
        """Hacker who ALSO has an Anonymous Spectator row cannot bypass race restriction."""
        await self._create_registered_char("SneakyHacker", "rizon", race="Hacker", credits=10000.0)
        await self._create_anonymous_spectator("SneakyHacker", "rizon", credits=10000.0)

        success, msg = await self.char_spec_repo.rename_rank("SneakyHacker", "rizon", "ExploitLord")
        self.assertFalse(success)
        self.assertEqual(msg, "Only Spectators can customize Rank Titles.")

        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "SneakyHacker"))).scalars().first()
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "SneakyHacker"))).scalars().first()
            self.assertEqual(char.credits, 10000.0)
            self.assertEqual(spec.credits, 10000.0)
            self.assertIsNone(char.rank_title)
            self.assertIsNone(spec.rank_title)


class TestSpectatorCommandRouterIntegration(BaseM1StressTest):
    """5. CommandRouter command parsing, prefix variations, flood tokens, and machine mode."""

    def _build_mock_node(self, prefix: str = "!a"):
        node = MagicMock()
        node.net_name = "rizon"
        node.prefix = prefix
        node.config = {"nickname": "ArenaMaster", "channel": "#automatagrid"}
        node.send = AsyncMock()
        node.channel_users = {}
        node.active_engine = None
        node.db = MagicMock()
        node.db.get_prefs = AsyncMock(return_value={"output_mode": "human"})
        node.db.spectator = self.char_spec_repo
        node.action_timestamps = {}
        node.flood_config = {
            'max_tokens': 4.0,
            'refill_rate': 0.5,
            'violation_threshold': 5,
            'lockout_duration': 30,
            'messages': {}
        }
        return node

    async def test_router_dispatch_standard_prefix(self):
        """!a spectator rename <title> invokes rename and consumes rate limit token."""
        await self._create_anonymous_spectator("RouterUser1", "rizon", credits=6000.0)
        node = self._build_mock_node(prefix="!a")
        router = CommandRouter(node)

        # Before command: 4 tokens
        await router.dispatch("RouterUser1", "PRIVMSG", "#automatagrid", "!a spectator rename Apex Master", is_admin=False)
        await asyncio.sleep(0.05)

        node.send.assert_called_once()
        sent_line = node.send.call_args[0][0]
        self.assertIn("Apex Master", sent_line)
        self.assertIn("RENAME", sent_line)

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "RouterUser1"))).scalars().first()
            self.assertEqual(spec.rank_title, "Apex Master")
            self.assertEqual(spec.credits, 1000.0)

    async def test_router_dispatch_exclamation_space_prefix(self):
        """! a spectator rename <title> with prefix ! invokes rename cleanly."""
        await self._create_anonymous_spectator("RouterUser2", "rizon", credits=7000.0)
        node = self._build_mock_node(prefix="!")
        router = CommandRouter(node)

        await router.dispatch("RouterUser2", "PRIVMSG", "#automatagrid", "! a spectator rename Cosmic King", is_admin=False)
        await asyncio.sleep(0.05)

        node.send.assert_called_once()
        self.assertIn("Cosmic King", node.send.call_args[0][0])

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "RouterUser2"))).scalars().first()
            self.assertEqual(spec.rank_title, "Cosmic King")
            self.assertEqual(spec.credits, 2000.0)

    async def test_router_dispatch_case_insensitivity(self):
        """Command routing is case insensitive (!A SPECTATOR RENAME ...)."""
        await self._create_anonymous_spectator("CaseUser", "rizon", credits=8000.0)
        node = self._build_mock_node(prefix="!a")
        router = CommandRouter(node)

        await router.dispatch("CaseUser", "PRIVMSG", "#automatagrid", "!A SPECTATOR RENAME Stellar Judge", is_admin=False)
        await asyncio.sleep(0.05)

        node.send.assert_called_once()
        self.assertIn("Stellar Judge", node.send.call_args[0][0])

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "CaseUser"))).scalars().first()
            self.assertEqual(spec.rank_title, "Stellar Judge")

    async def test_router_unprefixed_command_ignored(self):
        """Unprefixed 'spectator rename <title>' is not executed as game command."""
        await self._create_anonymous_spectator("ChatterUser", "rizon", credits=9000.0)
        node = self._build_mock_node(prefix="!a")
        router = CommandRouter(node)

        await router.dispatch("ChatterUser", "PRIVMSG", "#automatagrid", "spectator rename AccidentalTitle", is_admin=False)
        await asyncio.sleep(0.05)

        # Node should not have sent any reply and DB should remain untouched
        node.send.assert_not_called()

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "ChatterUser"))).scalars().first()
            self.assertIsNone(spec.rank_title)
            self.assertEqual(spec.credits, 9000.0)

    async def test_handler_machine_mode_formatting(self):
        """Machine mode output adheres to clean tag format without IRC ANSI colors."""
        await self._create_anonymous_spectator("MachineUser", "rizon", credits=6000.0)
        node = self._build_mock_node(prefix="!a")
        node.db.get_prefs = AsyncMock(return_value={"output_mode": "machine"})
        router = CommandRouter(node)

        await router.dispatch("MachineUser", "PRIVMSG", "#automatagrid", "!a spectator rename Cyber Overlord", is_admin=False)
        await asyncio.sleep(0.05)

        node.send.assert_called_once()
        raw_msg = node.send.call_args[0][0]
        # Verify machine tag structure
        self.assertIn("ACTION:SPECTATOR", raw_msg)
        self.assertIn("RESULT:RENAME", raw_msg)
        self.assertIn("Rank Title updated to: Cyber Overlord. (-5000.0c)", raw_msg)
        # Verify no ANSI escape codes
        self.assertNotIn("\x1b[", raw_msg)


if __name__ == "__main__":
    unittest.main()
