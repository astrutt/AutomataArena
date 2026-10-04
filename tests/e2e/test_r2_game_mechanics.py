# tests/e2e/test_r2_game_mechanics.py
"""
End-to-End Game Mechanics Test Suite for Automata Grid Milestone 3 (R2).

Covers all 7 Milestone 3 features:
- R2-F1: NickServ Authentication Support & Admin Gating
- R2-F4: In-IRC Arena Gambling System
- R2-F3: Spectator Item Drops & Live Combat Injection
- R2-F2: Dynamic LLM Battle Reporting & Procedural Fallbacks
- R2-F5: Community Node Renaming & Critical Node Protection
- R2-F6: Probe vs Explore Discovery Mechanics & Ephemeral TTL
- R2-F7: Database State Verification
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, Player, DiscoveryRecord, ArenaBet, InventoryItem
from ai_grid.grid_combat import CombatEngine, Entity
from ai_grid.grid_llm import ArenaLLM
from ai_grid.core.handlers.combat import handle_bet
from ai_grid.core.handlers.spectator import handle_spectator_drop, parse_drop_args
from ai_grid.core.handlers.grid import handle_grid_command, handle_node_probe
from ai_grid.core.handlers.admin import handle_admin_command
from ai_grid.core.map_utils import generate_ascii_map

from tests.e2e.fixtures import MockLLMServer, TestEnvironment


class TestNickServAuthenticationAndGating(unittest.IsolatedAsyncioTestCase):
    """R2-F1: NickServ Authentication Support & Admin Gating."""

    def test_01_bot_identifies_to_nickserv_on_connect(self):
        """Verifies AutomataBot sends PRIVMSG NickServ :IDENTIFY on connect and challenge."""
        from ai_player.bot import AutomataBot

        # Test with password configured
        bot = AutomataBot({"irc": {"server": "127.0.0.1", "port": 6667, "nickname": "TestBot", "channel": "#test", "nickserv_pass": "SecretAuthPass123"}})
        sent_messages = []
        bot.send_raw = MagicMock(side_effect=lambda line: sent_messages.append(line))

        # 1. Connected numeric 001
        bot._on_registered("001", "Welcome to the Internet Relay Network")
        self.assertIn("PRIVMSG NickServ :IDENTIFY SecretAuthPass123", sent_messages)

        # 2. Challenge notice from NickServ
        sent_messages.clear()
        bot._on_notice("NickServ", "NickServ!service@services.irc", "This nickname is registered. Please identify with :IDENTIFY <password>")
        self.assertIn("PRIVMSG NickServ :IDENTIFY SecretAuthPass123", sent_messages)

        # 3. Without password configured
        bot_nopass = AutomataBot({"irc": {"server": "127.0.0.1", "port": 6667, "nickname": "NoPassBot", "channel": "#test"}})
        sent_nopass = []
        bot_nopass.send_raw = MagicMock(side_effect=lambda line: sent_nopass.append(line))
        bot_nopass._on_registered("001", "Welcome")
        self.assertEqual(len(sent_nopass), 0)

    def test_02_manager_whois_parsing_sets_nickserv_verified(self):
        """Verifies GridNode sets nickserv_verified on WHOIS numerics 307, 330, 379 and NickServ notices."""
        from ai_grid.manager import GridNode as ManagerGridNode

        config = {
            "networks": {
                "testnet": {
                    "server": "127.0.0.1",
                    "port": 6667,
                    "nickname": "ArenaMaster",
                    "channel": "#arena",
                    "cmd_prefix": "!",
                }
            },
            "database": ":memory:",
            "admins": ["alice", "bob"]
        }
        node = ManagerGridNode("testnet", config, None)

        # Initial state: unverified
        self.assertFalse(node.is_user_verified("alice"))
        self.assertFalse(node.is_user_verified("bob"))
        self.assertFalse(node.is_user_verified("charlie"))

        # WHOIS 307: identified
        node._handle_numeric("307", ["ArenaMaster", "alice", "is identified for this nick"])
        self.assertTrue(node.is_user_verified("alice"))

        # WHOIS 330: logged in
        node._handle_numeric("330", ["ArenaMaster", "bob", "bob_acct", "is logged in as"])
        self.assertTrue(node.is_user_verified("bob"))

        # WHOIS 379: modes +r
        node._handle_numeric("379", ["ArenaMaster", "charlie", "is using modes +r"])
        self.assertTrue(node.is_user_verified("charlie"))

        # NickServ NOTICE confirmation
        self.assertFalse(node.nickserv_identified)
        node._handle_notice("NickServ", "Password accepted - you are now recognized.")
        self.assertTrue(node.nickserv_identified)
        self.assertTrue(node.is_user_verified("arenamaster"))

    async def test_03_admin_gate_strictly_blocks_unverified_nick(self):
        """Verifies admin commands are denied when caller lacks NickServ verification."""
        mock_node = MagicMock()
        mock_node.config = {"admins": ["admin_user"]}
        mock_node.is_user_verified = MagicMock(return_value=False)
        mock_node.send = AsyncMock()

        # Caller is configured admin but unverified -> strictly blocked
        await handle_admin_command(mock_node, "admin_user", ["shutdown"], "#arena")
        mock_node.send.assert_called_once()
        sent_line = mock_node.send.call_args[0][0]
        self.assertTrue("FAIL" in sent_line or "AUTH_DENIED" in sent_line or "NickServ" in sent_line or "Security Exception" in sent_line)

        # When caller is NickServ-verified -> permitted through gate
        mock_node.send.reset_mock()
        mock_node.is_user_verified = MagicMock(return_value=True)
        await handle_admin_command(mock_node, "admin_user", ["help"], "#arena")
        mock_node.send.assert_called_once()
        self.assertIn("ADMIN", mock_node.send.call_args[0][0])


class TestArenaGamblingSystem(unittest.IsolatedAsyncioTestCase):
    """R2-F4: In-IRC Arena Gambling System."""

    async def asyncSetUp(self):
        self.env = TestEnvironment(prefix="m3_gambling_")
        await self.env.setup()
        self.match_id = "match_gambling_test_01"

        # Create fighters and bettors
        await self.env.create_test_player("GladiatorAlice", "mocknet", credits=1000.0)
        await self.env.create_test_player("GladiatorBob", "mocknet", credits=1000.0)
        await self.env.create_spectator_player("Bettor1", "mocknet", credits=1000.0)
        await self.env.create_spectator_player("Bettor2", "mocknet", credits=1000.0)

    async def asyncTearDown(self):
        await self.env.teardown()

    async def test_04_place_bet_deducts_credits_and_creates_record(self):
        """Verifies credits deducted and ArenaBet row created with status PENDING."""
        success, msg = await self.env.db.betting.place_bet(
            "Bettor1", "mocknet", self.match_id, "GladiatorAlice", 250.0
        )
        self.assertTrue(success)
        self.assertIn("Bet registered", msg)

        # Check credits deducted in DB
        async with self.env.db.async_session() as session:
            c = (await session.execute(select(Character).where(Character.name == "Bettor1"))).scalars().first()
            self.assertEqual(c.credits, 750.0)

        # Check ArenaBet row
        bets = await self.env.db.betting.get_match_bets(self.match_id)
        self.assertEqual(len(bets), 1)
        self.assertEqual(bets[0].bettor_nick, "Bettor1")
        self.assertEqual(bets[0].chosen_fighter, "GladiatorAlice")
        self.assertEqual(bets[0].amount, 250.0)
        self.assertEqual(bets[0].status, "PENDING")

    async def test_05_place_bet_insufficient_credits_rejected(self):
        """Verifies bets exceeding credit balance are rejected without deducting credits."""
        success, msg = await self.env.db.betting.place_bet(
            "Bettor1", "mocknet", self.match_id, "GladiatorAlice", 2500.0
        )
        self.assertFalse(success)
        self.assertIn("Insufficient credits", msg)

        # Credits untouched
        async with self.env.db.async_session() as session:
            c = (await session.execute(select(Character).where(Character.name == "Bettor1"))).scalars().first()
            self.assertEqual(c.credits, 1000.0)

        bets = await self.env.db.betting.get_match_bets(self.match_id)
        self.assertEqual(len(bets), 0)

    async def test_06_place_bet_invalid_fighter_rejected(self):
        """Verifies bets on non-participating entities are rejected."""
        valid_fighters = ["GladiatorAlice", "GladiatorBob"]
        success, msg = await self.env.db.betting.place_bet(
            "Bettor1", "mocknet", self.match_id, "UnknownRival", 100.0, valid_fighters=valid_fighters
        )
        self.assertFalse(success)
        self.assertIn("Invalid fighter", msg)

    async def test_07_place_bet_window_closed_rejected(self):
        """Verifies bets placed after countdown expires are rejected."""
        node = MagicMock()
        node.betting_open = False
        node.current_match_id = self.match_id
        node.send = AsyncMock()

        await handle_bet(node, "Bettor1", ["GladiatorAlice", "100"], "#arena")
        node.send.assert_called_once()
        self.assertIn("closed", node.send.call_args[0][0].lower())

    async def test_08_resolve_bets_winner_pays_2x(self):
        """Verifies 2.0x payout credited to winner, ArenaBet WON/LOST updated."""
        await self.env.db.betting.place_bet("Bettor1", "mocknet", self.match_id, "GladiatorAlice", 200.0)
        await self.env.db.betting.place_bet("Bettor2", "mocknet", self.match_id, "GladiatorBob", 300.0)

        payouts = await self.env.db.betting.resolve_bets(self.match_id, "GladiatorAlice")
        self.assertEqual(len(payouts), 1)
        self.assertEqual(payouts[0]["payout"], 400.0)

        # Bettor1 had 800 + 400 = 1200; Bettor2 had 700 (lost)
        async with self.env.db.async_session() as session:
            b1 = (await session.execute(select(Character).where(Character.name == "Bettor1"))).scalars().first()
            b2 = (await session.execute(select(Character).where(Character.name == "Bettor2"))).scalars().first()
            self.assertEqual(b1.credits, 1200.0)
            self.assertEqual(b2.credits, 700.0)

        bets = await self.env.db.betting.get_match_bets(self.match_id)
        b1_bet = next(b for b in bets if b.bettor_nick == "Bettor1")
        b2_bet = next(b for b in bets if b.bettor_nick == "Bettor2")
        self.assertEqual(b1_bet.status, "WON")
        self.assertEqual(b2_bet.status, "LOST")

    async def test_09_refund_bets_on_draw_or_cancellation(self):
        """Verifies 1.0x refund credited to bettors on draw/cancel, ArenaBet REFUNDED."""
        await self.env.db.betting.place_bet("Bettor1", "mocknet", self.match_id, "GladiatorAlice", 250.0)
        await self.env.db.betting.place_bet("Bettor2", "mocknet", self.match_id, "GladiatorBob", 350.0)

        refunds = await self.env.db.betting.refund_bets(self.match_id)
        self.assertEqual(len(refunds), 2)

        async with self.env.db.async_session() as session:
            b1 = (await session.execute(select(Character).where(Character.name == "Bettor1"))).scalars().first()
            b2 = (await session.execute(select(Character).where(Character.name == "Bettor2"))).scalars().first()
            self.assertEqual(b1.credits, 1000.0)
            self.assertEqual(b2.credits, 1000.0)

        bets = await self.env.db.betting.get_match_bets(self.match_id)
        self.assertTrue(all(b.status == "REFUNDED" for b in bets))

    async def test_10_irc_command_routing_for_betting(self):
        """Verifies !a bet <fighter> <amt> command parsing and response."""
        node = MagicMock()
        node.betting_open = True
        node.pending_fighters = ["GladiatorAlice", "GladiatorBob"]
        node.current_match_id = self.match_id
        node.db = self.env.db
        node.net_name = "mocknet"
        node.config = {"channel": "#arena"}
        node.send = AsyncMock()

        await handle_bet(node, "Bettor1", ["GladiatorAlice", "150"], "#arena")
        self.assertTrue(node.send.called)
        sent = [str(c) for c in node.send.call_args_list]
        self.assertTrue(any("BET_ACCEPTED" in s or "GladiatorAlice" in s for s in sent))

        bets = await self.env.db.betting.get_match_bets(self.match_id)
        self.assertEqual(len(bets), 1)


class TestSpectatorItemDrops(unittest.IsolatedAsyncioTestCase):
    """R2-F3: Spectator Item Drops & Live Combat Injection."""

    async def asyncSetUp(self):
        self.env = TestEnvironment(prefix="m3_spectator_")
        await self.env.setup()
        await self.env.create_spectator_player("SpecMaster", "mocknet", credits=10000.0)
        await self.env.create_test_player("FighterOne", "mocknet", credits=1000.0)

    async def asyncTearDown(self):
        await self.env.teardown()

    async def test_11_spectator_drop_single_deduction_only(self):
        """Proves credits are deducted exactly once (fixing line 78/105 double deduction bug)."""
        # 1. Public Drop costs exactly 2500c (10000 -> 7500, NOT 5000)
        success, msg = await self.env.db.spectator_drop("SpecMaster", "mocknet", target=None)
        self.assertTrue(success)
        async with self.env.db.async_session() as session:
            c = (await session.execute(select(Character).where(Character.name == "SpecMaster"))).scalars().first()
            self.assertEqual(c.credits, 7500.0)

        # 2. Targeted drop of ZeroDay_Chain costs 7500c (7500 -> 0)
        success2, msg2 = await self.env.db.spectator_drop("SpecMaster", "mocknet", target="FighterOne", item_name="ZeroDay_Chain")
        self.assertTrue(success2)
        async with self.env.db.async_session() as session:
            c = (await session.execute(select(Character).where(Character.name == "SpecMaster"))).scalars().first()
            self.assertEqual(c.credits, 0.0)

    async def test_12_spectator_drop_inventory_delivery(self):
        """Verifies InventoryItem is delivered to target player in DB."""
        await self.env.create_spectator_player("DonorSpec", "mocknet", credits=5000.0)
        success, msg = await self.env.db.spectator_drop("DonorSpec", "mocknet", target="FighterOne", item_name="Nano_Patch")
        self.assertTrue(success)

        async with self.env.db.async_session() as session:
            char = (await session.execute(
                select(Character).where(Character.name == "FighterOne")
                .options(selectinload(Character.inventory).selectinload(InventoryItem.template))
            )).scalars().first()
            inv_names = [item.template.name for item in char.inventory]
            self.assertIn("Nano_Patch", inv_names)

    async def test_13_spectator_drop_live_arena_entity_injection(self):
        """Verifies dropping Nano_Patch, Battery, ZeroDay_Chain restores live HP/power and exploit."""
        from ai_grid.grid_combat import Entity
        fighter_ent = Entity("FighterOne", hp=20, max_hp=100, up=10, max_up=100)
        mock_engine = MagicMock()
        mock_engine.active = True
        mock_engine.entities = {"FighterOne": fighter_ent}
        mock_engine.turn_events = []

        node = MagicMock()
        node.active_engine = mock_engine
        node.db = self.env.db
        node.net_name = "mocknet"
        node.config = {"channel": "#arena"}
        node.send = AsyncMock()

        await self.env.create_spectator_player("LiveDonor", "mocknet", credits=20000.0)

        # 1. Nano_Patch restores 50 HP (20 + 50 = 70)
        await handle_spectator_drop(node, "LiveDonor", ["FighterOne", "Nano_Patch"], "#arena")
        self.assertEqual(fighter_ent.hp, 70)

        # 2. Battery restores 50 uP (10 + 50 = 60)
        await handle_spectator_drop(node, "LiveDonor", ["Battery", "FighterOne"], "#arena")
        self.assertEqual(fighter_ent.up, 60)

        # 3. ZeroDay_Chain injects Zero-Day into inventory
        await handle_spectator_drop(node, "LiveDonor", ["FighterOne", "ZeroDay_Chain"], "#arena")
        self.assertIn("Zero-Day", fighter_ent.inventory)

        # All 3 injections recorded in turn_events
        self.assertEqual(len(mock_engine.turn_events), 3)

    async def test_14_spectator_drop_item_selection_costs(self):
        """Verifies tiered costs (Nano_Patch 2500c, Battery 2500c, ZeroDay_Chain 7500c) and budget checks."""
        # Insufficient for 2500c
        await self.env.create_spectator_player("PoorSpec", "mocknet", credits=2000.0)
        success, msg = await self.env.db.spectator_drop("PoorSpec", "mocknet", target=None, item_name="Nano_Patch")
        self.assertFalse(success)
        self.assertIn("Insufficient budget", msg)

        # Insufficient for 7500c
        await self.env.create_spectator_player("MidSpec", "mocknet", credits=5000.0)
        success, msg = await self.env.db.spectator_drop("MidSpec", "mocknet", target=None, item_name="ZeroDay_Chain")
        self.assertFalse(success)
        self.assertIn("Insufficient budget", msg)


class TestDynamicCombatNarrative(unittest.IsolatedAsyncioTestCase):
    """R2-F2: Dynamic LLM Battle Reporting & Combat Events."""

    def test_15_combat_engine_event_aggregation(self):
        """Verifies CombatEngine aggregates structured turn event dictionaries."""
        engine = CombatEngine("match_combat_01", "!", AsyncMock())
        alice = Entity("Alice", hp=100, max_hp=100, up=100, max_up=100)
        bob = Entity("Bob", hp=100, max_hp=100, up=100, max_up=100)
        engine.entities = {"Alice": alice, "Bob": bob}
        engine.combatants = ["Alice", "Bob"]
        engine.turn_events = []

        engine._execute_attack("Alice", "Bob", "STRIKE")
        self.assertTrue(len(engine.turn_events) > 0)
        ev = engine.turn_events[0]
        self.assertIn("type", ev)
        self.assertEqual(ev["actor"], "Alice")
        self.assertEqual(ev["target"], "Bob")

    async def test_16_dynamic_battle_report_with_mock_llm(self):
        """Verifies battle report generated via MockLLMServer."""
        llm_server = MockLLMServer()
        llm_server.start()
        try:
            llm_server.enqueue_response("Alice pierced Bob's defenses with surgical lethality.")
            arena_llm = ArenaLLM({"endpoint": llm_server.endpoint, "model": "mock-model"})
            events = [{"type": "attack", "actor": "Alice", "target": "Bob", "damage": 35, "critical": True}]
            lines = await arena_llm.generate_turn_battle_report(1, events, ["Alice", "Bob"])
            self.assertTrue(len(lines) > 0)
            self.assertIn("surgical lethality", lines[0])
        finally:
            llm_server.stop()

    async def test_17_deterministic_fallback_on_llm_timeout_or_error(self):
        """Verifies fallback procedural text when LLM endpoint is unreachable."""
        arena_llm = ArenaLLM({"endpoint": "http://127.0.0.1:9999/unreachable", "model": "mock-model"})
        events = [{"type": "attack", "actor": "Alice", "target": "Bob", "damage": 20}]
        fallback = ["Alice hits Bob for 20 damage!"]
        lines = await arena_llm.generate_turn_battle_report(1, events, ["Alice", "Bob"], fallback_lines=fallback)
        self.assertEqual(lines, fallback)


class TestCommunityNodeRenaming(unittest.IsolatedAsyncioTestCase):
    """R2-F5: Community Node Renaming & Critical Node Protection."""

    async def asyncSetUp(self):
        self.env = TestEnvironment(prefix="m3_rename_")
        await self.env.setup()
        await self.env.create_test_player("CitizenAlice", "mocknet", credits=10000.0)
        async with self.env.db.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "Memory_Heap"))).scalars().first()
            char = (await session.execute(select(Character).where(Character.name == "CitizenAlice"))).scalars().first()
            if node and char:
                char.node_id = node.id
                await session.commit()

    async def asyncTearDown(self):
        await self.env.teardown()

    async def test_18_community_rename_success_cost_and_db_update(self):
        """Verifies 5000c deducted and GridNode.name updated in database."""
        success, msg = await self.env.db.territory.community_rename_node(
            "CitizenAlice", "mocknet", "Neon_Core", target_node="Memory_Heap"
        )
        self.assertTrue(success)
        self.assertIn("5000c", msg)

        async with self.env.db.async_session() as session:
            c = (await session.execute(select(Character).where(Character.name == "CitizenAlice"))).scalars().first()
            self.assertEqual(c.credits, 5000.0)
            node = (await session.execute(select(GridNode).where(GridNode.name == "Neon_Core"))).scalars().first()
            self.assertIsNotNone(node)

    async def test_19_community_rename_insufficient_credits_rejected(self):
        """Verifies rejection when credits < 5000c."""
        await self.env.create_test_player("BrokeCitizen", "mocknet", credits=1500.0)
        success, msg = await self.env.db.territory.community_rename_node(
            "BrokeCitizen", "mocknet", "Cyber_Node", target_node="Memory_Heap"
        )
        self.assertFalse(success)
        self.assertIn("Insufficient credits", msg)

    async def test_20_community_rename_name_length_and_format_validation(self):
        """Verifies rejection of names > 11 chars or containing invalid symbols."""
        # Name too long
        success, msg = await self.env.db.territory.community_rename_node(
            "CitizenAlice", "mocknet", "TooLongNameHere123", target_node="Memory_Heap"
        )
        self.assertFalse(success)
        self.assertIn("Invalid node name", msg)

        # Invalid characters
        success2, msg2 = await self.env.db.territory.community_rename_node(
            "CitizenAlice", "mocknet", "Bad-Name!", target_node="Memory_Heap"
        )
        self.assertFalse(success2)
        self.assertIn("Invalid node name", msg2)

    async def test_21_community_rename_uplink_and_safezone_protection(self):
        """Verifies UpLink and safezone nodes cannot be renamed, and identifier UpLink is reserved."""
        # Cannot rename UpLink
        success, msg = await self.env.db.territory.community_rename_node(
            "CitizenAlice", "mocknet", "New_Spawn", target_node="UpLink"
        )
        self.assertFalse(success)
        self.assertIn("Critical infrastructure", msg)

        # Cannot rename another node to UpLink
        success2, msg2 = await self.env.db.territory.community_rename_node(
            "CitizenAlice", "mocknet", "UpLink", target_node="Memory_Heap"
        )
        self.assertFalse(success2)
        self.assertIn("Reserved system identifier", msg2)

    async def test_22_community_rename_collision_check(self):
        """Verifies renaming to an existing node name fails."""
        success, msg = await self.env.db.territory.community_rename_node(
            "CitizenAlice", "mocknet", "Null_Space", target_node="Memory_Heap"
        )
        self.assertFalse(success)
        self.assertIn("collision", msg.lower())

    async def test_23_community_rename_irc_command_routing(self):
        """Verifies routing for !a grid rename and alias !a rename."""
        node = MagicMock()
        node.db = self.env.db
        node.net_name = "mocknet"
        node.config = {"channel": "#grid"}
        node.send = AsyncMock()
        node.add_xp = AsyncMock()

        await handle_grid_command(node, "CitizenAlice", "#grid", "rename", ["Core_One"])
        sent = [str(c) for c in node.send.call_args_list]
        self.assertTrue(any("Core_One" in s for s in sent))


class TestProbeVsExploreMechanics(unittest.IsolatedAsyncioTestCase):
    """R2-F6: Probe vs Explore Discovery Mechanics."""

    async def asyncSetUp(self):
        self.env = TestEnvironment(prefix="m3_discovery_")
        await self.env.setup()
        await self.env.create_test_player("ExplorerOne", "mocknet", credits=1000.0, power=100.0)

    async def asyncTearDown(self):
        await self.env.teardown()

    async def test_24_explore_creates_permanent_discovery_record_on_success(self):
        """Verifies DiscoveryRecord with intel_level='EXPLORE' and intel_expires_at=None created on success."""
        with patch("random.random", return_value=0.01):
            res = await self.env.db.discovery.explore_node("ExplorerOne", "mocknet")
        self.assertEqual(res["status"], "success")

        async with self.env.db.async_session() as session:
            c = (await session.execute(select(Character).where(Character.name == "ExplorerOne"))).scalars().first()
            disc = (await session.execute(
                select(DiscoveryRecord).where(DiscoveryRecord.character_id == c.id, DiscoveryRecord.node_id == c.node_id)
            )).scalars().first()
            self.assertIsNotNone(disc)
            self.assertEqual(disc.intel_level, "EXPLORE")
            self.assertIsNone(disc.intel_expires_at)

    async def test_25_explore_failure_does_not_create_discovery_record(self):
        """Verifies failed explore creates no DB record (fixing premature record creation bug)."""
        await self.env.create_test_player("UnluckyScout", "mocknet", credits=1000.0, power=100.0)
        with patch("random.random", return_value=0.99):
            res = await self.env.db.discovery.explore_node("UnluckyScout", "mocknet")
        self.assertEqual(res["status"], "failure")

        async with self.env.db.async_session() as session:
            c = (await session.execute(select(Character).where(Character.name == "UnluckyScout"))).scalars().first()
            disc = (await session.execute(
                select(DiscoveryRecord).where(DiscoveryRecord.character_id == c.id, DiscoveryRecord.node_id == c.node_id)
            )).scalars().first()
            self.assertIsNone(disc)

    async def test_26_probe_creates_ephemeral_record_with_ttl(self):
        """Verifies probe creates record with intel_level='PROBE' and intel_expires_at > now."""
        with patch("random.randint", return_value=20):
            res = await self.env.db.discovery.probe_node("ExplorerOne", "mocknet")
        self.assertTrue(res["success"])

        async with self.env.db.async_session() as session:
            c = (await session.execute(select(Character).where(Character.name == "ExplorerOne"))).scalars().first()
            disc = (await session.execute(
                select(DiscoveryRecord).where(DiscoveryRecord.character_id == c.id, DiscoveryRecord.node_id == c.node_id)
            )).scalars().first()
            self.assertIsNotNone(disc)
            self.assertEqual(disc.intel_level, "PROBE")
            self.assertIsNotNone(disc.intel_expires_at)
            self.assertGreater(disc.intel_expires_at, datetime.now(timezone.utc))

    async def test_27_probe_argument_forwarding(self):
        """Verifies handle_node_probe forwards target and direction arguments."""
        node = MagicMock()
        node.db = MagicMock()
        node.db.probe_node = AsyncMock(return_value={
            "success": True, "name": "Deep_Sector", "level": 1,
            "durability": 100, "visibility": "OPEN", "hack_dc": 12, "bonus_granted": 5
        })
        node.send = AsyncMock()
        node.channel_users = {}
        node.net_name = "mocknet"
        node.config = {"channel": "#grid"}

        await handle_node_probe(node, "ExplorerOne", "#grid", args=["north"])
        node.db.probe_node.assert_called_with("ExplorerOne", "mocknet", direction="north", target_name=None)

    async def test_28_probe_expiration_handling(self):
        """Verifies expired probe reverts to NONE and does not permanently unlock explore features."""
        async with self.env.db.async_session() as session:
            c = (await session.execute(select(Character).where(Character.name == "ExplorerOne"))).scalars().first()
            # Find an adjacent node that is NOT the current node
            other_node = (await session.execute(select(GridNode).where(GridNode.id != c.node_id))).scalars().first()
            expired_time = datetime.now(timezone.utc) - timedelta(minutes=15)
            session.add(DiscoveryRecord(
                character_id=c.id, node_id=other_node.id, intel_level="PROBE", intel_expires_at=expired_time
            ))
            await session.commit()

            # Render map: the expired other_node must NOT show as explored/open
            map_str = await generate_ascii_map(session, c, show_legend=False)
            # Other node returns to fog of war
            self.assertIn("[?]", map_str)


if __name__ == "__main__":
    unittest.main()
