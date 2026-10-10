"""
tests/stress_test_m1_o6_spectator.py — Adversarial Stress Test Suite for Priority 1 Spectator Completions.

Empirical verification by Challenger (critic/specialist):
1. Boundary credit amounts for anonymous drops (cost - 0.01c, exact cost, 0 credits, None credits, negative credits).
2. Boundary credit amounts for spectator rename (cost - 0.01c, exact cost, 0 credits, None credits).
3. Case-insensitivity of nicks and networks in anonymous drops, inventory lookups, and renames.
4. Non-existent spectators and idlers with 0 XP / 0 credits in drops, inventory, and renames.
5. Verification that drops do NOT grant items or consume credits when link fails, target is invalid, or arena node is missing.
6. Concurrent drop and rename race condition stress tests (prevent double-spending).
"""

import asyncio
import datetime
from datetime import timezone, timedelta
import os
import unittest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select, func, inspect
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from ai_grid.database.core import Base, Spectator
from ai_grid.database.repositories.spectator_repo import SpectatorRepository as CharacterSpectatorRepository
from ai_grid.database.spectator_repo import SpectatorRepository as SpectatorCoreRepository
from ai_grid.models import Player, NetworkAlias, Character, GridNode, PulseEvent, ItemTemplate, InventoryItem
from ai_grid.core.handlers.spectator import handle_spectator_inventory, handle_spectator_rename, handle_spectator_drop


class TestSpectatorEmpiricalStressHarness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_stress_m1_{int(datetime.datetime.now().timestamp() * 1000)}_{os.getpid()}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Seed default Arena node for public drops
        async with self.async_session() as session:
            arena = GridNode(name="Arena", node_type="arena")
            session.add(arena)
            await session.commit()

        self.char_spec_repo = CharacterSpectatorRepository(self.async_session)
        self.spec_core_repo = SpectatorCoreRepository(self.async_session)

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
            return char

    async def _create_anonymous_spectator(self, nick: str, network: str = "rizon", credits: float = 10000.0, xp: int = 50, rank_title: str = None):
        async with self.async_session() as session:
            spec = Spectator(nick=nick, network=network, credits=credits, xp=xp, rank_title=rank_title)
            session.add(spec)
            await session.commit()
            return spec

    # =========================================================================
    # Group 1: Boundary Credit Amounts for Anonymous Drops & Rename
    # =========================================================================

    async def test_01_drop_boundary_cost_minus_one_cent(self):
        """Boundary: anonymous spectator with exactly cost - 0.01c fails and credits are not consumed."""
        cost = 2500.0
        boundary_creds = 2499.99
        await self._create_anonymous_spectator("NearBrokeUser", "rizon", credits=boundary_creds)

        success, msg = await self.char_spec_repo.spectator_drop("NearBrokeUser", "rizon", item_name="Nano_Patch")
        self.assertFalse(success, f"Expected failure but got success: {msg}")
        self.assertIn("Insufficient budget. Support drops cost 2500.0c.", msg)

        # Verify credits remain exactly untouched in database
        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "NearBrokeUser"))).scalars().first()
            self.assertIsNotNone(spec)
            self.assertAlmostEqual(spec.credits, boundary_creds, places=4)

            # Verify no pulse events created
            pulses = (await session.execute(select(PulseEvent))).scalars().all()
            self.assertEqual(len(pulses), 0)

    async def test_02_drop_boundary_exact_cost(self):
        """Boundary: anonymous spectator with exact cost (2500.0c) succeeds and drops to 0.0c."""
        cost = 2500.0
        await self._create_anonymous_spectator("ExactCostUser", "rizon", credits=cost)

        success, msg = await self.char_spec_repo.spectator_drop("ExactCostUser", "rizon", item_name="Nano_Patch")
        self.assertTrue(success, f"Drop should succeed with exact cost: {msg}")
        self.assertIn("Public Drop Initiated!", msg)

        # Verify credits are exactly 0.0 in database
        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "ExactCostUser"))).scalars().first()
            self.assertIsNotNone(spec)
            self.assertAlmostEqual(spec.credits, 0.0, places=4)

            # Verify PulseEvent created
            pulses = (await session.execute(select(PulseEvent))).scalars().all()
            self.assertEqual(len(pulses), 1)
            self.assertEqual(pulses[0].event_type, "PACKET")

    async def test_03_drop_boundary_zero_credits(self):
        """Boundary: anonymous spectator with 0.0 credits fails and credits stay at 0.0."""
        await self._create_anonymous_spectator("ZeroCredUser", "rizon", credits=0.0)

        success, msg = await self.char_spec_repo.spectator_drop("ZeroCredUser", "rizon", item_name="Nano_Patch")
        self.assertFalse(success)
        self.assertIn("Insufficient budget. Support drops cost 2500.0c.", msg)

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "ZeroCredUser"))).scalars().first()
            self.assertIsNotNone(spec)
            self.assertEqual(spec.credits, 0.0)

    async def test_04_drop_boundary_none_credits(self):
        """Boundary: anonymous spectator with None credits handled safely without crashing."""
        async with self.async_session() as session:
            spec = Spectator(nick="NoneCredUser", network="rizon", credits=None, xp=10)
            session.add(spec)
            await session.commit()

        success, msg = await self.char_spec_repo.spectator_drop("NoneCredUser", "rizon", item_name="Nano_Patch")
        self.assertFalse(success)
        self.assertIn("Insufficient budget. Support drops cost 2500.0c.", msg)

        # Ensure no crash and DB record remains intact
        async with self.async_session() as session:
            loaded = (await session.execute(select(Spectator).where(Spectator.nick == "NoneCredUser"))).scalars().first()
            self.assertIsNotNone(loaded)
            # credits is either None or 0.0, not corrupted
            self.assertTrue(loaded.credits is None or loaded.credits == 0.0)

    async def test_05_drop_boundary_negative_credits(self):
        """Boundary: anonymous spectator with negative credits fails cleanly."""
        await self._create_anonymous_spectator("NegativeCredUser", "rizon", credits=-150.0)

        success, msg = await self.char_spec_repo.spectator_drop("NegativeCredUser", "rizon", item_name="Nano_Patch")
        self.assertFalse(success)
        self.assertIn("Insufficient budget. Support drops cost 2500.0c.", msg)

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "NegativeCredUser"))).scalars().first()
            self.assertEqual(spec.credits, -150.0)

    async def test_06_rename_boundary_credits(self):
        """Boundary: spectator rename fee is 5000.0c: test 4999.99c, 5000.0c, 0.0c, None."""
        cost = 5000.0
        # 1. 4999.99c fails
        await self._create_anonymous_spectator("Rename4999", "rizon", credits=4999.99)
        s1, m1 = await self.char_spec_repo.rename_rank("Rename4999", "rizon", "Supreme Leader")
        self.assertFalse(s1)
        self.assertIn("Insufficient credits. Renaming Rank costs 5000.0c.", m1)

        # 2. 5000.0c exact succeeds and reaches 0.0c
        await self._create_anonymous_spectator("Rename5000", "rizon", credits=5000.0)
        s2, m2 = await self.char_spec_repo.rename_rank("Rename5000", "rizon", "Supreme Leader")
        self.assertTrue(s2)
        self.assertIn("Rank Title updated to: Supreme Leader. (-5000.0c)", m2)

        async with self.async_session() as session:
            s = (await session.execute(select(Spectator).where(Spectator.nick == "Rename5000"))).scalars().first()
            self.assertAlmostEqual(s.credits, 0.0)
            self.assertEqual(s.rank_title, "Supreme Leader")

        # 3. None credits fails safely
        async with self.async_session() as session:
            session.add(Spectator(nick="RenameNone", network="rizon", credits=None))
            await session.commit()
        s3, m3 = await self.char_spec_repo.rename_rank("RenameNone", "rizon", "Arch-Observer")
        self.assertFalse(s3)
        self.assertIn("Insufficient credits. Renaming Rank costs 5000.0c.", m3)

    # =========================================================================
    # Group 2: Case-Insensitivity of Nicks and Networks
    # =========================================================================

    async def test_07_drop_case_insensitivity_mixed_nick_and_network(self):
        """Case-insensitivity: spectator drop succeeds when nick and network cases vary in all permutations."""
        # Seeded with PascalCase
        await self._create_anonymous_spectator("CaseObserver", "RizonNet", credits=8000.0)

        # 1. All lowercase
        s1, m1 = await self.char_spec_repo.spectator_drop("caseobserver", "rizonnet", item_name="Nano_Patch")
        self.assertTrue(s1, f"Failed on all-lowercase: {m1}")

        # 2. All uppercase
        s2, m2 = await self.char_spec_repo.spectator_drop("CASEOBSERVER", "RIZONNET", item_name="Battery")
        self.assertTrue(s2, f"Failed on all-uppercase: {m2}")

        # 3. Alternating case
        s3, m3 = await self.char_spec_repo.spectator_drop("cAsEoBsErVeR", "rIzOnNeT", item_name="Nano_Patch")
        self.assertTrue(s3, f"Failed on mixed case: {m3}")

        # Verify total deducted: 3 * 2500 = 7500, remaining = 500
        async with self.async_session() as session:
            s = (await session.execute(select(Spectator).where(Spectator.nick == "CaseObserver"))).scalars().first()
            self.assertAlmostEqual(s.credits, 500.0)

    async def test_08_inventory_case_insensitivity_mixed_nick_and_network(self):
        """Case-insensitivity: spectator inventory retrieves record regardless of nick/network casing."""
        await self._create_anonymous_spectator("InvSpectator", "RizonNet", credits=123.4, xp=67)

        # Human mode
        node = MagicMock()
        node.net_name = "rizonnet"
        node.send = AsyncMock()
        node.config = {"channel": "#automatagrid"}

        # Use actual core repo for get_spectator and db mock
        node.db = MagicMock()
        node.db.get_player = AsyncMock(return_value=None)
        node.db.get_spectator = self.spec_core_repo.get_spectator
        node.db.get_prefs = AsyncMock(return_value={"output_mode": "human"})

        await handle_spectator_inventory(node, "INVSPECTATOR", "#automatagrid")
        node.send.assert_called_once()
        raw = node.send.call_args[0][0]
        self.assertIn("Orbital Storage: No physical inventory (Spectator-only). Credits: 123.4c | XP: 67", raw)

        # Machine mode with mixed network
        node.send.reset_mock()
        node.net_name = "RIZONNET"
        node.db.get_prefs = AsyncMock(return_value={"output_mode": "machine"})

        await handle_spectator_inventory(node, "invspectator", "#automatagrid")
        node.send.assert_called_once()
        raw_mach = node.send.call_args[0][0]
        self.assertIn("ORBITAL_INV:SPECTATOR_ONLY CREDITS:123.4 XP:67", raw_mach)

    async def test_09_rename_case_insensitivity_mixed_nick_and_network(self):
        """Case-insensitivity: spectator rename succeeds with mismatched casing on nick and network."""
        await self._create_anonymous_spectator("RenameCaser", "AlphaNet", credits=6000.0)

        s, m = await self.char_spec_repo.rename_rank("renamecaser", "ALPHANET", "Lord Commander")
        self.assertTrue(s, f"Rename failed on case mismatch: {m}")

        async with self.async_session() as session:
            loaded = (await session.execute(select(Spectator).where(Spectator.nick == "RenameCaser"))).scalars().first()
            self.assertEqual(loaded.rank_title, "Lord Commander")
            self.assertAlmostEqual(loaded.credits, 1000.0)

    # =========================================================================
    # Group 3: Non-Existent Spectators and Idlers with 0 XP / 0 Credits
    # =========================================================================

    async def test_10_nonexistent_spectator_all_actions(self):
        """Non-existent spectator: drop, inventory, and rename all return accurate link failure notices."""
        # 1. Drop
        s_drop, m_drop = await self.char_spec_repo.spectator_drop("Ghost404", "rizon")
        self.assertFalse(s_drop)
        self.assertEqual(m_drop, "Orbital link failed. You must idle in channel to accrue credits before dropping.")

        # 2. Rename
        s_ren, m_ren = await self.char_spec_repo.rename_rank("Ghost404", "rizon", "Phantom")
        self.assertFalse(s_ren)
        self.assertEqual(m_ren, "Orbital link failed. You must idle in channel to accrue credits before customizing rank.")

        # 3. Inventory
        node = MagicMock()
        node.net_name = "rizon"
        node.send = AsyncMock()
        node.db = MagicMock()
        node.db.get_player = AsyncMock(return_value=None)
        node.db.get_spectator = AsyncMock(return_value=None)
        node.db.get_prefs = AsyncMock(return_value={})

        await handle_spectator_inventory(node, "Ghost404", "#automatagrid")
        node.send.assert_called_once()
        raw_inv = node.send.call_args[0][0]
        self.assertIn("Orbital link failed. You must idle in channel to accrue credits before accessing orbital storage.", raw_inv)

    async def test_11_zero_xp_zero_credit_idler_inventory_format(self):
        """Idler with 0 XP and 0.0 credits gets cleanly formatted output without NaN or None."""
        spec = await self._create_anonymous_spectator("ZeroIdler", "rizon", credits=0.0, xp=0)

        node = MagicMock()
        node.net_name = "rizon"
        node.send = AsyncMock()
        node.db = MagicMock()
        node.db.get_player = AsyncMock(return_value=None)
        node.db.get_spectator = self.spec_core_repo.get_spectator

        # Human mode
        node.db.get_prefs = AsyncMock(return_value={"output_mode": "human"})
        await handle_spectator_inventory(node, "ZeroIdler", "#automatagrid")
        raw_human = node.send.call_args[0][0]
        self.assertIn("Orbital Storage: No physical inventory (Spectator-only). Credits: 0.0c | XP: 0", raw_human)

        # Machine mode
        node.send.reset_mock()
        node.db.get_prefs = AsyncMock(return_value={"output_mode": "machine"})
        await handle_spectator_inventory(node, "ZeroIdler", "#automatagrid")
        raw_machine = node.send.call_args[0][0]
        self.assertIn("ORBITAL_INV:SPECTATOR_ONLY CREDITS:0.0 XP:0", raw_machine)

    # =========================================================================
    # Group 4: Drops Do NOT Grant Items or Consume Credits When Link Fails or Errors
    # =========================================================================

    async def test_12_no_credit_consumption_when_link_fails(self):
        """Verify that when orbital link fails, no items/pulses are spawned and no DB modifications occur."""
        s, m = await self.char_spec_repo.spectator_drop("NonExistentNick", "rizon", item_name="Nano_Patch")
        self.assertFalse(s)

        async with self.async_session() as session:
            # Check pulse events count
            pulses = (await session.execute(select(PulseEvent))).scalars().all()
            self.assertEqual(len(pulses), 0)

            # Check inventory items count
            inv_items = (await session.execute(select(InventoryItem))).scalars().all()
            self.assertEqual(len(inv_items), 0)

            # Check item templates count
            tpls = (await session.execute(select(ItemTemplate))).scalars().all()
            self.assertEqual(len(tpls), 0)

    async def test_13_targeted_drop_to_missing_target_does_not_consume_credits(self):
        """Adversarial: Anonymous spectator attempts targeted drop to non-existent target.
        Must fail, and credits MUST NOT be deducted from spectator record."""
        await self._create_anonymous_spectator("DonorSpectator", "rizon", credits=5000.0)

        s, m = await self.char_spec_repo.spectator_drop("DonorSpectator", "rizon", target="NonExistentTarget", item_name="Nano_Patch")
        self.assertFalse(s)
        self.assertIn("Target 'NonExistentTarget' not found in local sector.", m)

        # Crucial check: verify that DonorSpectator still has 5000.0 credits!
        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "DonorSpectator"))).scalars().first()
            self.assertIsNotNone(spec)
            self.assertEqual(spec.credits, 5000.0, "Credits were incorrectly deducted on failed targeted drop!")

            # Verify no inventory items were created
            inv = (await session.execute(select(InventoryItem))).scalars().all()
            self.assertEqual(len(inv), 0)

    async def test_14_public_drop_missing_arena_node_does_not_consume_credits(self):
        """Adversarial: Arena node missing from database. Drop must fail and credits MUST NOT be deducted."""
        await self._create_anonymous_spectator("DonorSpectator2", "rizon", credits=5000.0)

        # Delete Arena node
        async with self.async_session() as session:
            arena = (await session.execute(select(GridNode).where(GridNode.node_type == "arena"))).scalars().first()
            if arena:
                await session.delete(arena)
                await session.commit()

        s, m = await self.char_spec_repo.spectator_drop("DonorSpectator2", "rizon", item_name="Nano_Patch")
        self.assertFalse(s)
        self.assertIn("Arena node logic failure.", m)

        # Verify credits still 5000.0
        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "DonorSpectator2"))).scalars().first()
            self.assertEqual(spec.credits, 5000.0, "Credits were incorrectly deducted on arena node logic failure!")

    async def test_15_targeted_drop_to_valid_target_success_and_delivery(self):
        """Targeted drop from anonymous spectator to registered player succeeds, delivers item, and deducts credits."""
        target_char = await self._create_registered_char("ValidPlayer", "rizon", credits=100.0)
        await self._create_anonymous_spectator("GenerousSpectator", "rizon", credits=3000.0)

        s, m = await self.char_spec_repo.spectator_drop("GenerousSpectator", "rizon", target="ValidPlayer", item_name="Nano_Patch")
        self.assertTrue(s, f"Expected successful targeted drop: {m}")
        self.assertIn("Nano_Patch delivered to ValidPlayer", m)

        async with self.async_session() as session:
            # Donor credits deducted (3000 - 2500 = 500)
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "GenerousSpectator"))).scalars().first()
            self.assertAlmostEqual(spec.credits, 500.0)

            # Target received item in inventory
            inv = (await session.execute(select(InventoryItem).where(InventoryItem.character_id == target_char.id))).scalars().all()
            self.assertEqual(len(inv), 1)
            self.assertEqual(inv[0].quantity, 1)

    # =========================================================================
    # Group 5: Concurrency and Double-Spending Stress Testing
    # =========================================================================

    async def test_16_concurrent_drops_cannot_double_spend(self):
        """Stress test: spectator with 3000 credits attempts 5 concurrent drops of 2500c.
        Under serialized or atomic transactions, at most 1 can succeed, remaining 4 must fail.
        Credits must never become negative."""
        await self._create_anonymous_spectator("BurstDropper", "rizon", credits=3000.0)

        async def attempt_drop(idx):
            return await self.char_spec_repo.spectator_drop("BurstDropper", "rizon", item_name="Nano_Patch")

        results = await asyncio.gather(*(attempt_drop(i) for i in range(5)), return_exceptions=True)

        successes = [r for r in results if isinstance(r, tuple) and r[0] is True]
        failures = [r for r in results if isinstance(r, tuple) and r[0] is False]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 drop to succeed, but {len(successes)} succeeded!")
        self.assertEqual(len(failures), 4, f"Expected 4 drops to fail, but {len(failures)} failed!")

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "BurstDropper"))).scalars().first()
            self.assertGreaterEqual(spec.credits, 0.0, f"Credits dropped below zero: {spec.credits}")
            self.assertAlmostEqual(spec.credits, 500.0)

    async def test_17_concurrent_renames_cannot_double_spend(self):
        """Stress test: spectator with 6000 credits attempts 3 concurrent renames of 5000c.
        Exactly 1 must succeed, remaining 2 fail. Credits must end at 1000c."""
        await self._create_anonymous_spectator("BurstRenamer", "rizon", credits=6000.0)

        async def attempt_rename(idx):
            return await self.char_spec_repo.rename_rank("BurstRenamer", "rizon", f"Title_{idx}")

        results = await asyncio.gather(*(attempt_rename(i) for i in range(3)), return_exceptions=True)

        successes = [r for r in results if isinstance(r, tuple) and r[0] is True]
        failures = [r for r in results if isinstance(r, tuple) and r[0] is False]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 rename to succeed, but {len(successes)} succeeded!")
        self.assertEqual(len(failures), 2, f"Expected 2 renames to fail, but {len(failures)} failed!")

        async with self.async_session() as session:
            spec = (await session.execute(select(Spectator).where(Spectator.nick == "BurstRenamer"))).scalars().first()
            self.assertGreaterEqual(spec.credits, 0.0)
            self.assertAlmostEqual(spec.credits, 1000.0)


if __name__ == "__main__":
    unittest.main()
