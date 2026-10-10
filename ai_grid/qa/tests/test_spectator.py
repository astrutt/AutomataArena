# tests/test_spectator.py
import unittest
import asyncio
import datetime
from datetime import timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import os
import re

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from ai_grid.models import Base, Character, Player, NetworkAlias, GridNode, PulseEvent, ItemTemplate, InventoryItem
from ai_grid.database.core import Spectator
from ai_grid.database.spectator_repo import SpectatorRepository, SpectatorRepo
from ai_grid.database.repositories.spectator_repo import SpectatorRepository as CharacterSpectatorRepository
from ai_grid.grid_db import ArenaDB
from ai_grid.core.irc_client import IRCClient
from ai_grid.core.loops import spectator_payout_loop, distribute_spectator_payout
from ai_grid.core.command_router import CommandRouter
from ai_grid.core.handlers.spectator import handle_spectator_drop, handle_spectator_inventory, handle_spectator_rename


class TestSpectatorSchemaAndPersistence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_spectator_{int(datetime.datetime.now().timestamp() * 1000)}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.repo = SpectatorRepository(self.async_session)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    async def test_init_schema_creates_spectators_table_and_unique_constraint(self):
        """R1: Verify spectators table exists with unique constraint on (nick, network)."""
        async with self.engine.connect() as conn:
            def check_schema(connection):
                insp = inspect(connection)
                tables = insp.get_table_names()
                self.assertIn("spectators", tables)

                # Check unique constraints or unique indices
                uqs = insp.get_unique_constraints("spectators")
                indexes = insp.get_indexes("spectators")
                
                # Check for unique constraint on ('nick', 'network')
                found = False
                for uq in uqs:
                    cols = [c.lower() for c in uq.get("column_names", [])]
                    if "nick" in cols and "network" in cols:
                        found = True
                        break
                if not found:
                    for idx in indexes:
                        if idx.get("unique"):
                            cols = [c.lower() for c in idx.get("column_names", [])]
                            if "nick" in cols and "network" in cols:
                                found = True
                                break
                self.assertTrue(found, "Unique constraint or unique index on ('nick', 'network') not found")

            await conn.run_sync(check_schema)

    async def test_upsert_spectator_creates_new_and_is_idempotent(self):
        """R1: Calling upsert_spectator creates a record on first call and is idempotent."""
        spec1 = await self.repo.upsert_spectator("Alice", "rizon")
        self.assertIsNotNone(spec1)
        self.assertEqual(spec1.nick, "Alice")
        self.assertEqual(spec1.network, "rizon")
        self.assertEqual(spec1.xp, 0)
        self.assertEqual(spec1.credits, 0.0)
        self.assertEqual(spec1.idle_hours, 0.0)
        self.assertEqual(spec1.message_count, 0)

        # Idempotent successive call
        spec2 = await self.repo.upsert_spectator("Alice", "rizon")
        self.assertEqual(spec1.id, spec2.id)

        # Case-insensitive nick lookup
        spec3 = await self.repo.upsert_spectator("alice", "rizon")
        self.assertEqual(spec1.id, spec3.id)

    async def test_record_message_increments_and_refreshes_last_seen(self):
        """R1: record_message increments message count and refreshes last_seen."""
        spec = await self.repo.upsert_spectator("Bob", "rizon")
        t0 = spec.last_seen

        await asyncio.sleep(0.01)
        updated1 = await self.repo.record_message("Bob", "rizon")
        self.assertEqual(updated1.message_count, 1)
        self.assertEqual(updated1.lifetime_messages, 1)
        self.assertGreaterEqual(updated1.last_seen, t0)

        updated2 = await self.repo.record_message("Bob", "rizon")
        self.assertEqual(updated2.message_count, 2)
        self.assertEqual(updated2.lifetime_messages, 2)

    async def test_apply_payout_atomically_updates_xp_and_credits(self):
        """R1: apply_payout atomically updates XP and credits."""
        await self.repo.upsert_spectator("Charlie", "rizon")
        res1 = await self.repo.apply_payout("Charlie", "rizon", xp=10, credits=5.0)
        self.assertEqual(res1.xp, 10)
        self.assertEqual(res1.credits, 5.0)

        res2 = await self.repo.apply_payout("Charlie", "rizon", xp=15, credits=10.0)
        self.assertEqual(res2.xp, 25)
        self.assertEqual(res2.credits, 15.0)

    async def test_record_idle_hours_and_reset_message_count(self):
        """R1: record_idle_hours increments hours, reset_message_count resets to 0."""
        await self.repo.upsert_spectator("Dave", "rizon")
        await self.repo.record_message("Dave", "rizon")
        await self.repo.record_message("Dave", "rizon")

        # Increment idle hours
        res_idle = await self.repo.record_idle_hours("Dave", "rizon", 1.0)
        self.assertEqual(res_idle.idle_hours, 1.0)
        res_idle2 = await self.repo.record_idle_hours("Dave", "rizon", 1.0)
        self.assertEqual(res_idle2.idle_hours, 2.0)

        # Reset message count
        res_reset = await self.repo.reset_message_count("Dave", "rizon")
        self.assertEqual(res_reset.message_count, 0)
        self.assertEqual(res_reset.lifetime_messages, 2)

    async def test_get_all_active_filters_by_since_minutes_threshold(self):
        """R1: get_all_active filters spectators by threshold (excluding idlers > 90m)."""
        now = datetime.datetime.now(timezone.utc)
        
        # Spectator 1: active (seen 10 mins ago)
        spec1 = await self.repo.upsert_spectator("ActiveUser", "rizon")
        async with self.async_session() as session:
            db_s1 = await self.repo.get_spectator("ActiveUser", "rizon")
            async with self.async_session() as s2:
                from sqlalchemy import update
                await s2.execute(
                    update(Spectator)
                    .where(Spectator.id == spec1.id)
                    .values(last_seen=now - timedelta(minutes=10))
                )
                await s2.commit()

        # Spectator 2: inactive (seen 120 mins ago, > 90m threshold)
        spec2 = await self.repo.upsert_spectator("InactiveUser", "rizon")
        async with self.async_session() as session:
            from sqlalchemy import update
            await session.execute(
                update(Spectator)
                .where(Spectator.id == spec2.id)
                .values(last_seen=now - timedelta(minutes=120))
            )
            await session.commit()

        active_list = await self.repo.get_all_active(network="rizon", since_minutes=90)
        active_nicks = [s.nick for s in active_list]
        self.assertIn("ActiveUser", active_nicks)
        self.assertNotIn("InactiveUser", active_nicks)


class TestSpectatorActivityTracking(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {
            "nickname": "ArenaMaster",
            "channel": "#automatagrid",
            "admins": ["AdminOne", "AdminTwo"],
        }
        self.mock_repo = MagicMock()
        self.mock_repo.upsert_spectator = AsyncMock()
        self.mock_repo.record_message = AsyncMock()

        self.client = IRCClient("rizon", self.config)
        self.client.spectator_repo = self.mock_repo

    async def test_privmsg_in_game_channel_triggers_upsert_and_record_message(self):
        """R2: Incoming PRIVMSG in game channel triggers upsert_spectator and record_message."""
        line = ":Viewer1!user@host PRIVMSG #automatagrid :Hello spectators!"
        self.client.track_spectator_activity(line)

        # Allow fire-and-forget task to run
        await asyncio.sleep(0.05)
        self.mock_repo.upsert_spectator.assert_called_once_with("Viewer1", "rizon")
        self.mock_repo.record_message.assert_called_once_with("Viewer1", "rizon")

    async def test_join_in_game_channel_triggers_upsert_spectator(self):
        """R2: Incoming JOIN to game channel triggers upsert_spectator."""
        line = ":Viewer2!user@host JOIN #automatagrid"
        self.client.track_spectator_activity(line)

        await asyncio.sleep(0.05)
        self.mock_repo.upsert_spectator.assert_called_once_with("Viewer2", "rizon")
        self.mock_repo.record_message.assert_not_called()

    async def test_bot_nickname_is_ignored(self):
        """R2: Activity from bot nickname is ignored."""
        line1 = ":ArenaMaster!bot@host PRIVMSG #automatagrid :System message"
        line2 = ":ArenaMaster!bot@host JOIN #automatagrid"
        self.client.track_spectator_activity(line1)
        self.client.track_spectator_activity(line2)

        await asyncio.sleep(0.05)
        self.mock_repo.upsert_spectator.assert_not_called()
        self.mock_repo.record_message.assert_not_called()

    async def test_administrator_nicknames_are_ignored(self):
        """R2: Activity from administrator nicknames is ignored."""
        line1 = ":AdminOne!admin@host PRIVMSG #automatagrid :Admin broadcast"
        line2 = ":AdminTwo!admin@host JOIN #automatagrid"
        self.client.track_spectator_activity(line1)
        self.client.track_spectator_activity(line2)

        await asyncio.sleep(0.05)
        self.mock_repo.upsert_spectator.assert_not_called()
        self.mock_repo.record_message.assert_not_called()

    async def test_other_channels_are_ignored(self):
        """R2: Activity in non-game channels is ignored."""
        line = ":Viewer1!user@host PRIVMSG #otherchannel :Not in game channel"
        self.client.track_spectator_activity(line)

        await asyncio.sleep(0.05)
        self.mock_repo.upsert_spectator.assert_not_called()
        self.mock_repo.record_message.assert_not_called()


class TestSpectatorPayoutEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.node = MagicMock()
        self.node.net_name = "rizon"
        self.node.config = {"channel": "#automatagrid"}
        self.node.send = AsyncMock()

        self.mock_repo = MagicMock()
        self.mock_repo.get_all_active = AsyncMock()
        self.mock_repo.apply_payout = AsyncMock()
        self.mock_repo.record_idle_hours = AsyncMock()
        self.mock_repo.reset_message_count = AsyncMock()

        self.node.db = MagicMock()
        self.node.db.spectator_repo = self.mock_repo

    async def test_payout_calculation_formula(self):
        """R3: Payout calculation accurately awards Base XP (10), Base Credits (5),
        Chat bonus (+2 per 10 messages capped at +20), and Idle bonus (+1 XP/hr)."""
        now = datetime.datetime.now(timezone.utc)
        
        # Spec A: 0 messages, 0 idle hours -> 10 XP, 5 Credits
        spec_a = MagicMock()
        spec_a.nick = "SpecA"
        spec_a.network = "rizon"
        spec_a.message_count = 0
        spec_a.idle_hours = 0.0
        spec_a.joined_at = now

        # Spec B: 25 messages (bonus: (25//10)*2 = +4c), 2.0 idle hours (bonus: +2 XP)
        # -> Total: 12 XP, 9 Credits
        spec_b = MagicMock()
        spec_b.nick = "SpecB"
        spec_b.network = "rizon"
        spec_b.message_count = 25
        spec_b.idle_hours = 2.0
        spec_b.joined_at = now - timedelta(hours=2)

        # Spec C: 150 messages (capped at +20c), 5.0 idle hours (bonus: +5 XP)
        # -> Total: 15 XP, 25 Credits
        spec_c = MagicMock()
        spec_c.nick = "SpecC"
        spec_c.network = "rizon"
        spec_c.message_count = 150
        spec_c.idle_hours = 5.0
        spec_c.joined_at = now - timedelta(hours=5)

        self.mock_repo.get_all_active.return_value = [spec_a, spec_b, spec_c]

        distributed_count = await distribute_spectator_payout(self.node)
        self.assertEqual(distributed_count, 3)

        # Verify Spec A rewards
        self.mock_repo.apply_payout.assert_any_call("SpecA", "rizon", 10, 5.0)
        self.mock_repo.record_idle_hours.assert_any_call("SpecA", "rizon", 1.0)
        self.mock_repo.reset_message_count.assert_any_call("SpecA", "rizon")

        # Verify Spec B rewards
        self.mock_repo.apply_payout.assert_any_call("SpecB", "rizon", 12, 9.0)
        self.mock_repo.record_idle_hours.assert_any_call("SpecB", "rizon", 1.0)
        self.mock_repo.reset_message_count.assert_any_call("SpecB", "rizon")

        # Verify Spec C rewards
        self.mock_repo.apply_payout.assert_any_call("SpecC", "rizon", 15, 25.0)
        self.mock_repo.record_idle_hours.assert_any_call("SpecC", "rizon", 1.0)
        self.mock_repo.reset_message_count.assert_any_call("SpecC", "rizon")

        # Verify broadcast notice
        self.node.send.assert_called_once_with(
            "PRIVMSG #automatagrid :[GRID DIVIDEND] Hourly accrual distributed to 3 spectators."
        )


class TestSpectatorCommandRouting(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.node = MagicMock()
        self.node.net_name = "rizon"
        self.node.prefix = "!a"
        self.node.config = {"nickname": "ArenaMaster", "channel": "#automatagrid"}
        self.node.send = AsyncMock()
        self.node.channel_users = {}
        self.node.active_engine = None

        self.mock_repo = MagicMock()
        self.mock_repo.upsert_spectator = AsyncMock()
        self.mock_repo.get_spectator = AsyncMock()

        self.node.db = MagicMock()
        self.node.db.spectator_repo = self.mock_repo

        # Rate limiting state for node
        self.node.action_timestamps = {}
        self.node.flood_config = {
            'max_tokens': 4.0,
            'refill_rate': 0.5,
            'violation_threshold': 5,
            'lockout_duration': 30,
            'messages': {}
        }

        self.router = CommandRouter(self.node)

    async def test_spectator_session_command_format_and_private_reply(self):
        """R4: !a spectator replies privately with expected tag format."""
        spec = MagicMock()
        spec.nick = "ViewerX"
        spec.network = "rizon"
        spec.message_count = 12
        spec.joined_at = datetime.datetime.now(timezone.utc) - timedelta(hours=1)
        self.mock_repo.upsert_spectator.return_value = spec

        await self.router.dispatch("ViewerX", "PRIVMSG", "#automatagrid", "!a spectator", is_admin=False)

        # Allow dispatched task to run
        await asyncio.sleep(0.05)

        self.mock_repo.upsert_spectator.assert_called_with("ViewerX", "rizon")
        self.node.send.assert_called_once()
        out_msg = self.node.send.call_args[0][0]

        # Verify private message to ViewerX
        self.assertTrue(out_msg.startswith("PRIVMSG ViewerX :"))
        # Verify tag format: [SPECTATOR] {nick} | Session: {elapsed_time} | Messages: {count} | Rate: {msg/hr:.1f}
        pattern = r"PRIVMSG ViewerX :\[SPECTATOR\] ViewerX \| Session: .+ \| Messages: \d+ \| Rate: \d+\.\d"
        self.assertRegex(out_msg, pattern)

    async def test_spectator_stats_command_format_and_private_reply(self):
        """R4: !a spectator stats replies privately with expected persistent stats format."""
        spec = MagicMock()
        spec.nick = "ViewerY"
        spec.network = "rizon"
        spec.xp = 85
        spec.credits = 150.0
        spec.idle_hours = 6.0
        spec.message_count = 42
        spec.lifetime_messages = 42
        self.mock_repo.upsert_spectator.return_value = spec

        await self.router.dispatch("ViewerY", "PRIVMSG", "#automatagrid", "!a spectator stats", is_admin=False)

        await asyncio.sleep(0.05)

        self.mock_repo.upsert_spectator.assert_called_with("ViewerY", "rizon")
        self.node.send.assert_called_once()
        out_msg = self.node.send.call_args[0][0]

        # Verify private message to ViewerY
        self.assertTrue(out_msg.startswith("PRIVMSG ViewerY :"))
        # Expected: [SPECTATOR STATS] {nick} | XP: {xp} | Credits: {credits}c | Idle Hours: {idle_hours:.1f}h | Messages (lifetime): {message_count}
        expected = "PRIVMSG ViewerY :[SPECTATOR STATS] ViewerY | XP: 85 | Credits: 150c | Idle Hours: 6.0h | Messages (lifetime): 42"
        self.assertEqual(out_msg, expected)

    async def test_spectator_commands_deduct_rate_limit_token(self):
        """R4: Spectator commands deduct 1 token from the global rate limit bucket."""
        spec = MagicMock()
        spec.nick = "RateLimitUser"
        spec.network = "rizon"
        spec.message_count = 0
        spec.joined_at = datetime.datetime.now(timezone.utc)
        self.mock_repo.upsert_spectator.return_value = spec

        # First call: starts at max_tokens (4.0), consumes 1.0 -> 3.0
        await self.router.dispatch("RateLimitUser", "PRIVMSG", "#automatagrid", "!a spectator", is_admin=False)
        await asyncio.sleep(0.05)

        record = self.node.action_timestamps.get("ratelimituser")
        self.assertIsNotNone(record)
        self.assertAlmostEqual(record["tokens"], 3.0, delta=0.1)

        # Second call: consumes another token -> ~2.0
        await self.router.dispatch("RateLimitUser", "PRIVMSG", "#automatagrid", "!a spectator stats", is_admin=False)
        await asyncio.sleep(0.05)

        record = self.node.action_timestamps.get("ratelimituser")
        self.assertAlmostEqual(record["tokens"], 2.0, delta=0.1)

    async def test_spectator_stats_with_decimal_credits(self):
        """R4: Decimal credits format properly (e.g. 15.5c)."""
        spec = MagicMock()
        spec.nick = "FractionalUser"
        spec.network = "rizon"
        spec.xp = 10
        spec.credits = 15.5
        spec.idle_hours = 1.2
        spec.message_count = 5
        spec.lifetime_messages = 5
        self.mock_repo.upsert_spectator.return_value = spec

        await self.router.dispatch("FractionalUser", "PRIVMSG", "#automatagrid", "!a spectator stats", is_admin=False)
        await asyncio.sleep(0.05)

        out_msg = self.node.send.call_args[0][0]
        expected = "PRIVMSG FractionalUser :[SPECTATOR STATS] FractionalUser | XP: 10 | Credits: 15.5c | Idle Hours: 1.2h | Messages (lifetime): 5"
        self.assertEqual(out_msg, expected)

    async def test_payout_with_empty_active_spectators(self):
        """R3: When active spectators is empty, distribute returns 0 and does not crash."""
        self.mock_repo.get_all_active.return_value = []
        count = await distribute_spectator_payout(self.node)
        self.assertEqual(count, 0)
        self.node.send.assert_not_called()


class TestSpectatorArenaDBIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_spectator_db_{int(datetime.datetime.now().timestamp() * 1000)}.db"
        self.db = ArenaDB(self.db_path)
        # Ensure schema initialized
        async with self.db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self):
        await self.db.engine.dispose()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    async def test_arena_db_spectator_methods(self):
        """Verify ArenaDB exposes all spectator repo methods."""
        spec = await self.db.upsert_spectator("Eve", "rizon")
        self.assertEqual(spec.nick, "Eve")

        rec = await self.db.record_spectator_message("Eve", "rizon")
        self.assertEqual(rec.message_count, 1)

        fetched = await self.db.get_spectator("Eve", "rizon")
        self.assertEqual(fetched.nick, "Eve")

        paid = await self.db.apply_spectator_payout("Eve", "rizon", xp=10, credits=5.0)
        self.assertEqual(paid.xp, 10)
        self.assertEqual(paid.credits, 5.0)

        idle = await self.db.record_spectator_idle_hours("Eve", "rizon", 1.0)
        self.assertEqual(idle.idle_hours, 1.0)

        reset = await self.db.reset_spectator_message_count("Eve", "rizon")
        self.assertEqual(reset.message_count, 0)


class TestSpectatorAdversarialEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_adv_{int(datetime.datetime.now().timestamp() * 1000)}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.repo = SpectatorRepository(self.async_session)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    async def test_concurrent_spectator_burst_chat_and_payout(self):
        """Attack: 30 concurrent tasks recording messages across multiple networks during payout."""
        # Pre-seed 5 spectators
        for i in range(5):
            await self.repo.upsert_spectator(f"Seeded_{i}", "rizon")
            await self.repo.record_message(f"Seeded_{i}", "rizon")

        node = MagicMock()
        node.net_name = "rizon"
        node.config = {"channel": "#automatagrid"}
        node.send = AsyncMock()
        node.db = MagicMock()
        node.db.spectator_repo = self.repo

        # Concurrently record 25 new spectator messages across 2 networks while running payout
        async def chatter(idx):
            net = "rizon" if idx % 2 == 0 else "2600net"
            nick = f"BurstUser_{idx}"
            await self.repo.upsert_spectator(nick, net)
            await self.repo.record_message(nick, net)

        async def payout_worker():
            await asyncio.sleep(0.01)
            return await distribute_spectator_payout(node)

        tasks = [chatter(i) for i in range(25)]
        tasks.append(payout_worker())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Verify no unhandled exceptions occurred
        for r in results:
            self.assertFalse(isinstance(r, Exception), f"Concurrent burst raised: {r}")

        # Verify all 25 users exist in the database
        for i in range(25):
            net = "rizon" if i % 2 == 0 else "2600net"
            spec = await self.repo.get_spectator(f"BurstUser_{i}", net)
            self.assertIsNotNone(spec)
            self.assertGreaterEqual(spec.message_count + spec.lifetime_messages, 1)

    async def test_clock_jump_future_and_zero_duration_session(self):
        """Verify session calculations withstand future timestamps, zero durations, and naive datetimes."""
        node = MagicMock()
        node.net_name = "rizon"
        node.prefix = "!a"
        node.config = {"nickname": "ArenaMaster", "channel": "#automatagrid"}
        node.send = AsyncMock()
        node.channel_users = {}
        node.active_engine = None
        node.action_timestamps = {}
        node.flood_config = {'max_tokens': 10.0, 'refill_rate': 1.0, 'violation_threshold': 5, 'lockout_duration': 30, 'messages': {}}
        node.db = MagicMock()
        node.db.spectator_repo = self.repo

        router = CommandRouter(node)

        # 1. Spectator with future joined_at (clock drift ahead by 2 hours)
        future_spec = await self.repo.upsert_spectator("FutureDrifter", "rizon")
        async with self.async_session() as session:
            from sqlalchemy import update
            future_time = datetime.datetime.now(timezone.utc) + timedelta(hours=2)
            await session.execute(
                update(Spectator)
                .where(Spectator.id == future_spec.id)
                .values(joined_at=future_time, message_count=5)
            )
            await session.commit()

        await router.handle_spectator_session_command("FutureDrifter")
        node.send.assert_called_once()
        msg1 = node.send.call_args[0][0]
        self.assertIn("PRIVMSG FutureDrifter :[SPECTATOR] FutureDrifter | Session: 0:00:00 | Messages: 5 | Rate: 0.0", msg1)

        # 2. Spectator with naive datetime joined_at (no tzinfo)
        node.send.reset_mock()
        naive_spec = await self.repo.upsert_spectator("NaiveUser", "rizon")
        async with self.async_session() as session:
            naive_time = datetime.datetime.utcnow() - timedelta(hours=1)
            await session.execute(
                update(Spectator)
                .where(Spectator.id == naive_spec.id)
                .values(joined_at=naive_time, message_count=10)
            )
            await session.commit()

        await router.handle_spectator_session_command("NaiveUser")
        node.send.assert_called_once()
        msg2 = node.send.call_args[0][0]
        self.assertIn("[SPECTATOR] NaiveUser | Session: 1:00:0", msg2)
        self.assertIn("Messages: 10 | Rate: 10.0", msg2)

    async def test_chat_bonus_caps_and_boundary_quantization(self):
        """Verify exact chat bonus formula: +2 credits per full 10 messages, capped at +20."""
        node = MagicMock()
        node.net_name = "rizon"
        node.config = {"channel": "#automatagrid"}
        node.send = AsyncMock()
        node.db = MagicMock()
        node.db.spectator_repo = self.repo

        test_cases = [
            (0, 0.0),    # 0 msgs -> +0c
            (9, 0.0),    # 9 msgs -> +0c
            (10, 2.0),   # 10 msgs -> +2c
            (19, 2.0),   # 19 msgs -> +2c
            (20, 4.0),   # 20 msgs -> +4c
            (99, 18.0),  # 99 msgs -> +18c
            (100, 20.0), # 100 msgs -> +20c
            (250, 20.0), # 250 msgs -> +20c (capped)
        ]

        now = datetime.datetime.now(timezone.utc)
        for count, expected_bonus in test_cases:
            nick = f"Chatter_{count}"
            spec = await self.repo.upsert_spectator(nick, "rizon")
            async with self.async_session() as session:
                from sqlalchemy import update
                await session.execute(
                    update(Spectator)
                    .where(Spectator.id == spec.id)
                    .values(message_count=count, idle_hours=0.0, joined_at=now)
                )
                await session.commit()

        count_paid = await distribute_spectator_payout(node)
        self.assertEqual(count_paid, len(test_cases))

        # Check credits and resets for each case
        for count, expected_bonus in test_cases:
            nick = f"Chatter_{count}"
            updated = await self.repo.get_spectator(nick, "rizon")
            expected_total_credits = 5.0 + expected_bonus
            self.assertEqual(updated.credits, expected_total_credits)
            self.assertEqual(updated.xp, 10)  # Base 10 XP + 0 idle bonus
            self.assertEqual(updated.idle_hours, 1.0)
            self.assertEqual(updated.message_count, 0)

    async def test_idle_bonus_quantization_boundaries(self):
        """Verify idle bonus: +1 XP per full hour of session time / idle hours."""
        node = MagicMock()
        node.net_name = "rizon"
        node.config = {"channel": "#automatagrid"}
        node.send = AsyncMock()
        node.db = MagicMock()
        node.db.spectator_repo = self.repo

        test_cases = [
            (0.0, 0),   # 0.0h -> +0 XP
            (0.9, 0),   # 0.9h -> +0 XP
            (1.0, 1),   # 1.0h -> +1 XP
            (2.5, 2),   # 2.5h -> +2 XP
            (10.0, 10), # 10.0h -> +10 XP
        ]

        now = datetime.datetime.now(timezone.utc)
        for hours, expected_bonus in test_cases:
            nick = f"Idler_{int(hours * 10)}"
            spec = await self.repo.upsert_spectator(nick, "rizon")
            async with self.async_session() as session:
                from sqlalchemy import update
                await session.execute(
                    update(Spectator)
                    .where(Spectator.id == spec.id)
                    .values(idle_hours=hours, message_count=0, joined_at=now - timedelta(hours=hours))
                )
                await session.commit()

        await distribute_spectator_payout(node)

        for hours, expected_bonus in test_cases:
            nick = f"Idler_{int(hours * 10)}"
            updated = await self.repo.get_spectator(nick, "rizon")
            self.assertEqual(updated.xp, 10 + expected_bonus)
            self.assertEqual(updated.credits, 5.0)
            self.assertEqual(updated.idle_hours, hours + 1.0)

    async def test_irc_client_edge_cases_and_case_insensitivity(self):
        """Verify IRC tracking ignores admin/bot with mixed casing, and parses various JOIN syntaxes."""
        config = {
            "nickname": "ArenaMaster",
            "channel": "#AutomataGrid",
            "admins": ["SuperAdmin", "Operator"],
        }
        mock_repo = MagicMock()
        mock_repo.upsert_spectator = AsyncMock()
        mock_repo.record_message = AsyncMock()

        client = IRCClient("rizon", config)
        client.spectator_repo = mock_repo

        # Case-insensitive admin check
        client.track_spectator_activity(":SUPERADMIN!user@host PRIVMSG #automatagrid :msg")
        client.track_spectator_activity(":operator!user@host JOIN #automatagrid")
        # Case-insensitive bot check
        client.track_spectator_activity(":arenamaster!bot@host PRIVMSG #automatagrid :msg")
        # Non-game channel
        client.track_spectator_activity(":viewer!user@host PRIVMSG #general :msg")

        await asyncio.sleep(0.05)
        mock_repo.upsert_spectator.assert_not_called()
        mock_repo.record_message.assert_not_called()

        # JOIN with trailing colon syntax: :Nick!u@h JOIN :#AutomataGrid
        client.track_spectator_activity(":NewJoiner!u@h JOIN :#AutomataGrid")
        await asyncio.sleep(0.05)
        mock_repo.upsert_spectator.assert_called_once_with("NewJoiner", "rizon")

    async def test_spectator_model_aware_datetime_persistence(self):
        """Verify AwareDateTime on Spectator preserves UTC timezone awareness across SQLite storage."""
        spec = await self.repo.upsert_spectator("AwareUser", "rizon")
        self.assertIsNotNone(spec.last_seen.tzinfo, "last_seen must have tzinfo")
        self.assertEqual(spec.last_seen.tzinfo, timezone.utc)
        self.assertIsNotNone(spec.joined_at.tzinfo, "joined_at must have tzinfo")
        self.assertEqual(spec.joined_at.tzinfo, timezone.utc)
        self.assertIsNotNone(spec.created_at.tzinfo, "created_at must have tzinfo")
        self.assertEqual(spec.created_at.tzinfo, timezone.utc)

        # Re-fetch through a completely fresh session to test serialization/deserialization
        async with self.async_session() as session:
            stmt = select(Spectator).where(Spectator.nick == "AwareUser")
            loaded = (await session.execute(stmt)).scalars().first()
            self.assertIsNotNone(loaded)
            self.assertIsNotNone(loaded.last_seen.tzinfo, "Deserialized last_seen must be timezone-aware")
            self.assertEqual(loaded.last_seen.tzinfo, timezone.utc)
            self.assertIsNotNone(loaded.joined_at.tzinfo, "Deserialized joined_at must be timezone-aware")
            self.assertEqual(loaded.joined_at.tzinfo, timezone.utc)
            self.assertIsNotNone(loaded.created_at.tzinfo, "Deserialized created_at must be timezone-aware")
            self.assertEqual(loaded.created_at.tzinfo, timezone.utc)

    async def test_irc_client_synchronous_mock_repo(self):
        """Verify IRCClient handles synchronous mock repositories without throwing TypeError."""
        config = {
            "nickname": "ArenaMaster",
            "channel": "#automatagrid",
            "admins": [],
        }
        mock_repo = MagicMock()
        mock_repo.upsert_spectator = MagicMock(return_value={"nick": "Chathound"})
        mock_repo.record_message = MagicMock(return_value={"nick": "Chathound"})

        client = IRCClient("rizon", config)
        client.spectator_repo = mock_repo

        client.track_spectator_activity(":Chathound!u@h PRIVMSG #automatagrid :woof")
        client.track_spectator_activity(":Joinhound!u@h JOIN #automatagrid")

        await asyncio.sleep(0.05)
        self.assertEqual(mock_repo.upsert_spectator.call_count, 2)
        self.assertEqual(mock_repo.record_message.call_count, 1)

    async def test_distribute_payout_synchronous_send_mock(self):
        """Verify distribute_spectator_payout does not crash when node.send is a synchronous MagicMock."""
        await self.repo.upsert_spectator("SyncViewer", "rizon")
        node = MagicMock()
        node.net_name = "rizon"
        node.config = {"channel": "#automatagrid"}
        node.send = MagicMock(return_value=None)
        node.db = MagicMock()
        node.db.spectator_repo = self.repo

        count = await distribute_spectator_payout(node)
        self.assertGreaterEqual(count, 1)
        node.send.assert_called_once()

    async def test_command_router_synchronous_send_mock(self):
        """Verify CommandRouter handles synchronous node.send without throwing TypeError."""
        await self.repo.upsert_spectator("RouterSyncUser", "rizon")
        node = MagicMock()
        node.net_name = "rizon"
        node.prefix = "!a"
        node.config = {"nickname": "ArenaMaster", "channel": "#automatagrid"}
        node.send = MagicMock(return_value=None)
        node.channel_users = {}
        node.active_engine = None
        node.action_timestamps = {}
        node.flood_config = {'max_tokens': 10.0, 'refill_rate': 1.0, 'violation_threshold': 5, 'lockout_duration': 30, 'messages': {}}
        node.db = MagicMock()
        node.db.spectator_repo = self.repo

        router = CommandRouter(node)
        await router.handle_spectator_session_command("RouterSyncUser")
        node.send.assert_called_once()

        node.send.reset_mock()
        await router.handle_spectator_stats_command("RouterSyncUser")
        node.send.assert_called_once()

    async def test_repo_null_and_empty_inputs(self):
        """Verify repository safely handles None and empty inputs without crashing."""
        self.assertIsNone(await self.repo.upsert_spectator(None, "rizon"))
        self.assertIsNone(await self.repo.upsert_spectator("", "rizon"))
        self.assertIsNone(await self.repo.upsert_spectator("User", None))
        self.assertIsNone(await self.repo.upsert_spectator("User", ""))

        self.assertIsNone(await self.repo.record_message(None, "rizon"))
        self.assertIsNone(await self.repo.record_message("User", None))

        self.assertIsNone(await self.repo.get_spectator(None, "rizon"))
        self.assertIsNone(await self.repo.get_spectator("User", None))

        self.assertIsNone(await self.repo.apply_payout(None, "rizon", 10, 5.0))
        self.assertIsNone(await self.repo.apply_payout("User", None, 10, 5.0))

        self.assertIsNone(await self.repo.record_idle_hours(None, "rizon", 1.0))
        self.assertIsNone(await self.repo.record_idle_hours("User", None, 1.0))

        self.assertIsNone(await self.repo.reset_message_count(None, "rizon"))
        self.assertIsNone(await self.repo.reset_message_count("User", None))

    async def test_distribute_payout_fault_isolation(self):
        """Verify distribute_spectator_payout isolates per-spectator failures and pays remaining spectators."""
        s1 = await self.repo.upsert_spectator("HealthySpec1", "rizon")
        s2 = await self.repo.upsert_spectator("ProblematicSpec", "rizon")
        s3 = await self.repo.upsert_spectator("HealthySpec2", "rizon")

        node = MagicMock()
        node.net_name = "rizon"
        node.config = {"channel": "#automatagrid"}
        node.send = AsyncMock()

        # Custom repo mock that raises on ProblematicSpec apply_payout
        mock_repo = MagicMock()
        mock_repo.get_all_active = AsyncMock(return_value=[s1, s2, s3])
        async def mock_apply(nick, net, xp, creds):
            if nick == "ProblematicSpec":
                raise RuntimeError("Simulated DB timeout for ProblematicSpec")
            return s1
        mock_repo.apply_payout = AsyncMock(side_effect=mock_apply)
        mock_repo.record_idle_hours = AsyncMock()
        mock_repo.reset_message_count = AsyncMock()

        node.db = MagicMock()
        node.db.spectator_repo = mock_repo

        count = await distribute_spectator_payout(node)
        self.assertEqual(count, 2)
        node.send.assert_called_once_with(
            "PRIVMSG #automatagrid :[GRID DIVIDEND] Hourly accrual distributed to 2 spectators."
        )

    async def test_spectator_with_detached_session(self):
        """Verify Spectator model and repository operate correctly with expire_on_commit=True."""
        db_path = f"test_detached_{int(datetime.datetime.now().timestamp() * 1000)}.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
        async_session = async_sessionmaker(engine, expire_on_commit=True, class_=AsyncSession)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        repo = SpectatorRepository(async_session)
        spec = await repo.upsert_spectator("DetachedUser", "rizon")
        self.assertEqual(spec.nick, "DetachedUser")
        self.assertEqual(spec.xp, 0)

        # Attribute access outside of active session
        spec_dict = spec.to_dict()
        self.assertEqual(spec_dict["nick"], "DetachedUser")
        self.assertEqual(spec["nick"], "DetachedUser")

        rec = await repo.record_message("DetachedUser", "rizon")
        self.assertEqual(rec.message_count, 1)

        paid = await repo.apply_payout("DetachedUser", "rizon", xp=10, credits=5.0)
        self.assertEqual(paid.xp, 10)

        await engine.dispose()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass

    async def test_arenadb_init_schema_creates_spectators_table(self):
        """Verify ArenaDB.init_schema() creates spectators table with unique constraint."""
        db_path = f"test_arenadb_init_{int(datetime.datetime.now().timestamp() * 1000)}.db"
        db = ArenaDB(db_path)
        try:
            await db.init_schema()
            async with db.engine.connect() as conn:
                def check_table(connection):
                    insp = inspect(connection)
                    tables = insp.get_table_names()
                    self.assertIn("spectators", tables)
                    uqs = insp.get_unique_constraints("spectators")
                    cols = [c.lower() for uq in uqs for c in uq.get("column_names", [])]
                    self.assertIn("nick", cols)
                    self.assertIn("network", cols)
                await conn.run_sync(check_table)
        finally:
            await db.engine.dispose()
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                except OSError:
                    pass


class TestMilestone1SpectatorCompletions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_m1_spec_{int(datetime.datetime.now().timestamp() * 1000)}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Seed arena node for public drops
        async with self.async_session() as session:
            arena = GridNode(name="Arena", node_type="arena")
            session.add(arena)
            await session.commit()

        self.char_spec_repo = CharacterSpectatorRepository(self.async_session)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    async def _create_registered_char(self, nick: str, network: str = "rizon", race: str = "Spectator", credits: float = 10000.0):
        async with self.async_session() as session:
            player = Player()
            session.add(player)
            await session.flush()
            alias = NetworkAlias(player_id=player.id, network_name=network, nickname=nick)
            session.add(alias)
            char = Character(player_id=player.id, name=nick, race=race, char_class="Spectator", credits=credits, inventory=[])
            session.add(char)
            await session.commit()

    async def _create_anonymous_spectator(self, nick: str, network: str = "rizon", credits: float = 10000.0, xp: int = 50):
        async with self.async_session() as session:
            spec = Spectator(nick=nick, network=network, credits=credits, xp=xp)
            session.add(spec)
            await session.commit()

    # --- 1a: Anonymous Spectator Drops ---

    async def test_spectator_drop_anonymous_sufficient_credits(self):
        """1a: Anonymous idler with sufficient credits can trigger a spectator drop."""
        await self._create_anonymous_spectator("AnonDropUser", "rizon", credits=3000.0)

        success, msg = await self.char_spec_repo.spectator_drop("AnonDropUser", "rizon", item_name="Nano_Patch")
        self.assertTrue(success, f"Drop should succeed: {msg}")
        self.assertIn("Public Drop Initiated!", msg)

        # Verify credits deducted from Spectator table (3000 - 2500 = 500)
        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "AnonDropUser"))).scalars().first()
            self.assertIsNotNone(spec)
            self.assertAlmostEqual(spec.credits, 500.0)

            # Verify pulse event created
            pulse = (await session.execute(select(PulseEvent))).scalars().first()
            self.assertIsNotNone(pulse)
            self.assertEqual(pulse.event_type, "PACKET")

    async def test_spectator_drop_anonymous_insufficient_credits(self):
        """1a: Anonymous idler with insufficient credits fails with budget error."""
        await self._create_anonymous_spectator("BrokeAnonDrop", "rizon", credits=1000.0)

        success, msg = await self.char_spec_repo.spectator_drop("BrokeAnonDrop", "rizon", item_name="Nano_Patch")
        self.assertFalse(success)
        self.assertIn("Insufficient budget. Support drops cost 2500.0c.", msg)

        # Verify credits untouched
        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "BrokeAnonDrop"))).scalars().first()
            self.assertEqual(spec.credits, 1000.0)

    async def test_spectator_drop_neither_character_nor_spectator(self):
        """1a: Nick with neither character nor spectator row returns exact orbital link failed message."""
        success, msg = await self.char_spec_repo.spectator_drop("GhostIdler", "rizon")
        self.assertFalse(success)
        self.assertEqual(msg, "Orbital link failed. You must idle in channel to accrue credits before dropping.")

    async def test_spectator_drop_registered_character_intact(self):
        """1a: Registered character drop deducts character credits (existing behavior preserved)."""
        await self._create_registered_char("RegCharUser", "rizon", race="Spectator", credits=6000.0)

        success, msg = await self.char_spec_repo.spectator_drop("RegCharUser", "rizon", item_name="Battery")
        self.assertTrue(success)

        # Verify character credits deducted (6000 - 2500 = 3500)
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "RegCharUser"))).scalars().first()
            self.assertAlmostEqual(char.credits, 3500.0)

    # --- 1b: Spectator Inventory for Anonymous Spectators ---

    async def test_spectator_inventory_anonymous_human_mode_exact_format(self):
        """1b: Anonymous spectator in human mode receives exact orbital storage string."""
        node = MagicMock()
        node.net_name = "rizon"
        node.send = AsyncMock()
        node.config = {"channel": "#automatagrid"}

        spec = Spectator(nick="AnonViewer", network="rizon", credits=125.5, xp=40)
        node.db = MagicMock()
        node.db.get_player = AsyncMock(return_value=None)
        node.db.get_spectator = AsyncMock(return_value=spec)
        node.db.get_prefs = AsyncMock(return_value={"output_mode": "human", "msg_type": "privmsg"})

        await handle_spectator_inventory(node, "AnonViewer", "#automatagrid")

        node.send.assert_called_once()
        raw_sent = node.send.call_args[0][0]
        self.assertIn("Orbital Storage: No physical inventory (Spectator-only). Credits: 125.5c | XP: 40", raw_sent)

    async def test_spectator_inventory_anonymous_machine_mode_exact_format(self):
        """1b: Anonymous spectator in machine mode receives exact ORBITAL_INV tag."""
        node = MagicMock()
        node.net_name = "rizon"
        node.send = AsyncMock()
        node.config = {"channel": "#automatagrid"}

        spec = Spectator(nick="BotViewer", network="rizon", credits=350.0, xp=75)
        node.db = MagicMock()
        node.db.get_player = AsyncMock(return_value=None)
        node.db.get_spectator = AsyncMock(return_value=spec)
        node.db.get_prefs = AsyncMock(return_value={"output_mode": "machine", "msg_type": "privmsg"})

        await handle_spectator_inventory(node, "BotViewer", "#automatagrid")

        node.send.assert_called_once()
        raw_sent = node.send.call_args[0][0]
        self.assertIn("ORBITAL_INV:SPECTATOR_ONLY CREDITS:350.0 XP:75", raw_sent)

    async def test_spectator_inventory_unregistered_failure_message(self):
        """1b: User with neither character nor spectator row gets failure notice."""
        node = MagicMock()
        node.net_name = "rizon"
        node.send = AsyncMock()
        node.config = {"channel": "#automatagrid"}

        node.db = MagicMock()
        node.db.get_player = AsyncMock(return_value=None)
        node.db.get_spectator = AsyncMock(return_value=None)
        node.db.get_prefs = AsyncMock(return_value={})

        await handle_spectator_inventory(node, "GhostUser", "#automatagrid")

        node.send.assert_called_once()
        raw_sent = node.send.call_args[0][0]
        self.assertIn("Orbital link failed. You must idle in channel to accrue credits before accessing orbital storage.", raw_sent)

    async def test_spectator_inventory_registered_character_intact(self):
        """1b: Registered character sees physical inventory (existing behavior preserved)."""
        node = MagicMock()
        node.net_name = "rizon"
        node.send = AsyncMock()
        node.config = {"channel": "#automatagrid"}

        node.db = MagicMock()
        node.db.get_player = AsyncMock(return_value={"name": "RegUser", "inventory": '["Nano_Patch", "Battery"]'})
        node.db.get_prefs = AsyncMock(return_value={"output_mode": "human"})

        await handle_spectator_inventory(node, "RegUser", "#automatagrid")

        node.send.assert_called_once()
        raw_sent = node.send.call_args[0][0]
        self.assertIn("Orbital Storage: Nano_Patch, Battery", raw_sent)

    # --- 1c: Spectator Rank Rename Command ---

    async def test_spectator_rename_anonymous_sufficient_credits(self):
        """1c: Anonymous spectator with >= 5000c deducts 5000c and updates rank_title."""
        await self._create_anonymous_spectator("RichAnon", "rizon", credits=6500.0)

        success, msg = await self.char_spec_repo.rename_rank("RichAnon", "rizon", "Arch-Observer")
        self.assertTrue(success)
        self.assertEqual(msg, "Rank Title updated to: Arch-Observer. (-5000.0c)")

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "RichAnon"))).scalars().first()
            self.assertAlmostEqual(spec.credits, 1500.0)
            self.assertEqual(spec.rank_title, "Arch-Observer")
            self.assertEqual(spec.to_dict()["rank_title"], "Arch-Observer")

    async def test_spectator_rename_anonymous_insufficient_credits(self):
        """1c: Anonymous spectator with < 5000c fails with insufficient credits error."""
        await self._create_anonymous_spectator("PoorAnonRename", "rizon", credits=2500.0)

        success, msg = await self.char_spec_repo.rename_rank("PoorAnonRename", "rizon", "Supreme-Watcher")
        self.assertFalse(success)
        self.assertEqual(msg, "Insufficient credits. Renaming Rank costs 5000.0c.")

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "PoorAnonRename"))).scalars().first()
            self.assertEqual(spec.credits, 2500.0)
            self.assertIsNone(spec.rank_title)

    async def test_spectator_rename_neither_character_nor_spectator(self):
        """1c: Nick with neither character nor spectator row returns exact orbital link failed message."""
        success, msg = await self.char_spec_repo.rename_rank("GhostRenameUser", "rizon", "Shadow")
        self.assertFalse(success)
        self.assertEqual(msg, "Orbital link failed. You must idle in channel to accrue credits before customizing rank.")

    async def test_spectator_rename_registered_spectator_success(self):
        """1c: Registered character of race Spectator can customize rank title for 5000c."""
        await self._create_registered_char("CharSpectator", "rizon", race="Spectator", credits=7500.0)

        success, msg = await self.char_spec_repo.rename_rank("CharSpectator", "rizon", "Grand Sovereign")
        self.assertTrue(success)
        self.assertEqual(msg, "Rank Title updated to: Grand Sovereign. (-5000.0c)")

        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "CharSpectator"))).scalars().first()
            self.assertAlmostEqual(char.credits, 2500.0)
            self.assertEqual(char.rank_title, "Grand Sovereign")

    async def test_spectator_rename_registered_non_spectator_fails(self):
        """1c: Registered character of non-Spectator race cannot customize rank title."""
        await self._create_registered_char("HackerChar", "rizon", race="Cyborg", credits=10000.0)

        success, msg = await self.char_spec_repo.rename_rank("HackerChar", "rizon", "Overlord")
        self.assertFalse(success)
        self.assertEqual(msg, "Only Spectators can customize Rank Titles.")

    async def test_handle_spectator_rename_handler_missing_title(self):
        """1c: handle_spectator_rename without title replies with syntax usage."""
        node = MagicMock()
        node.net_name = "rizon"
        node.send = AsyncMock()
        node.db = MagicMock()
        node.db.get_prefs = AsyncMock(return_value={})

        await handle_spectator_rename(node, "Alice", [], "#automatagrid")

        node.send.assert_called_once()
        raw = node.send.call_args[0][0]
        self.assertIn("Syntax: spectator rename <title> (Cost: 5000c)", raw)

    async def test_handle_spectator_rename_handler_execution(self):
        """1c: handle_spectator_rename invokes db.spectator.rename_rank and formats reply."""
        node = MagicMock()
        node.net_name = "rizon"
        node.send = AsyncMock()
        node.db = MagicMock()
        node.db.get_prefs = AsyncMock(return_value={})
        node.db.spectator = MagicMock()
        node.db.spectator.rename_rank = AsyncMock(return_value=(True, "Rank Title updated to: Cosmic Chief. (-5000.0c)"))

        await handle_spectator_rename(node, "Alice", ["Cosmic", "Chief"], "#automatagrid")

        node.db.spectator.rename_rank.assert_called_once_with("Alice", "rizon", "Cosmic Chief")
        node.send.assert_called_once()
        raw = node.send.call_args[0][0]
        self.assertIn("Cosmic Chief", raw)

    async def test_command_routing_spectator_rename(self):
        """1c: Command router dispatches 'spectator rename <title>' and '!a spectator rename <title>'."""
        node = MagicMock()
        node.net_name = "rizon"
        node.prefix = "!a"
        node.config = {"nickname": "ArenaMaster", "channel": "#automatagrid"}
        node.send = AsyncMock()
        node.channel_users = {}
        node.active_engine = None
        node.db = MagicMock()
        node.db.get_prefs = AsyncMock(return_value={})
        node.db.spectator = MagicMock()
        node.db.spectator.rename_rank = AsyncMock(return_value=(True, "Rank Title updated to: Apex Watcher. (-5000.0c)"))

        node.action_timestamps = {}
        node.flood_config = {
            'max_tokens': 4.0,
            'refill_rate': 0.5,
            'violation_threshold': 5,
            'lockout_duration': 30,
            'messages': {}
        }

        router = CommandRouter(node)

        # Dispatch 1: !a spectator rename Apex Watcher (exercises verb == "spectator")
        await router.dispatch("Tester1", "PRIVMSG", "#automatagrid", "!a spectator rename Apex Watcher", is_admin=False)
        await asyncio.sleep(0.05)
        node.db.spectator.rename_rank.assert_called_with("Tester1", "rizon", "Apex Watcher")

        # Dispatch 2: ! a spectator rename Apex Watcher with prefix ! (exercises verb == "a" and args[0] == "spectator")
        node.prefix = "!"
        node.db.spectator.rename_rank.reset_mock()
        await router.dispatch("Tester2", "PRIVMSG", "#automatagrid", "! a spectator rename Apex Watcher", is_admin=False)
        await asyncio.sleep(0.05)
        node.db.spectator.rename_rank.assert_called_with("Tester2", "rizon", "Apex Watcher")

    async def test_spectator_model_rank_title_persistence(self):
        """1c: Spectator model persists and serializes rank_title."""
        async with self.async_session() as session:
            spec = Spectator(nick="SchemaTester", network="rizon", rank_title="High Judge")
            session.add(spec)
            await session.commit()

        async with self.async_session() as session:
            loaded = (await session.execute(select(Spectator).where(Spectator.nick == "SchemaTester"))).scalars().first()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.rank_title, "High Judge")
            d = loaded.to_dict()
            self.assertEqual(d["rank_title"], "High Judge")


if __name__ == "__main__":
    unittest.main()



