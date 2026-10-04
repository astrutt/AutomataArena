"""
tests/stress_test_m2_challenger.py — Empirical Challenger Stress Test Suite for Milestone 2.

Exhaustively verifies:
1. Player registration anti-hijacking:
   - 3 args, 4 args, case-insensitive matching, special characters, whitespace, hijacking rejections, duplicate registration.
2. Combat router command collision handling:
   - Prefixed vs non-prefixed verbs in and out of combat, single-word vs multi-word commands,
   - Node breach (!a hack, !a hack grid) vs PvP combat (!a hack <player>).
3. Combat repository tuple return consistency:
   - Success, failure, evasion, and database exceptions for grid_attack, grid_hack, and grid_rob.
   - Empirical verification that power deduction is committed to the database upon evasion.
"""

import asyncio
import os
import random
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.future import select
from sqlalchemy.exc import OperationalError

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Player, Character, GridNode, NetworkAlias, InventoryItem, ItemTemplate
from ai_grid.grid_combat import CombatEngine, Entity
from ai_grid.core.command_router import CommandRouter
import ai_grid.core.handlers as handlers
from ai_grid.database.repositories.combat_repo import CombatRepository
from tests.e2e.fixtures.test_env import TestEnvironment


class MockLLM:
    """Deterministic Mock LLM for bio generation."""
    async def generate_bio(self, bot_name, race, b_class, traits):
        return f"{bot_name} is a {race} {b_class} characterized by {traits}."


class MockNode:
    """Mock GridNode engine node for testing command dispatch and handlers."""
    def __init__(self, db: ArenaDB, net_name: str = "mocknet"):
        self.db = db
        self.net_name = net_name
        self.prefix = "!a"
        self.config = {
            "nickname": "ArenaMaster",
            "channel": "#automatagrid",
            "admin_token": "SecretAdminToken"
        }
        self.admins = []
        self.nickserv_verified = set()
        self.admin_sessions = {}
        self.active_engine = None
        self.match_queue = []
        self.pending_encounters = {}
        self.ready_players = []
        self.flood_config = {
            'max_tokens': 100.0,
            'refill_rate': 10.0,
            'violation_threshold': 50,
            'lockout_duration': 30,
            'messages': {}
        }
        self.token_buckets = {}
        self.user_mutes = {}
        self.action_timestamps = {}
        self.llm = MockLLM()
        self.sent_messages = []

    async def send(self, msg: str):
        self.sent_messages.append(msg)

    async def set_dynamic_topic(self):
        pass


class TestRegistrationAntiHijacking(unittest.IsolatedAsyncioTestCase):
    """Focus Area 1: Player registration anti-hijacking permutations."""

    async def asyncSetUp(self):
        self.env = TestEnvironment(prefix="ag_stress_reg_")
        await self.env.setup()
        self.node = MockNode(self.env.db)

    async def asyncTearDown(self):
        await self.env.teardown()

    async def test_01_registration_3_args_successful_binding(self):
        """Verify 3-arg syntax 'register <Race> <Class> <Traits>' binds directly to source_nick."""
        nick = "Alice"
        args = ["Cyborg", "Hacker", "Stealthy"]
        await handlers.handle_registration(self.node, nick, args, reply_target=nick)

        char = await self.env.db.player.get_player("Alice", self.node.net_name)
        self.assertIsNotNone(char, "Character Alice should be created in DB")
        self.assertEqual(char["name"], "Alice")
        self.assertEqual(char["race"], "Cyborg")
        self.assertEqual(char["char_class"], "Hacker")
        self.assertTrue(any("entered the Grid" in m for m in self.node.sent_messages))

    async def test_02_registration_4_args_exact_case_match(self):
        """Verify 4-arg syntax 'register <Name> <Race> <Class> <Traits>' succeeds when name matches source_nick."""
        nick = "Bob"
        args = ["Bob", "Synth", "Guardian", "Resilient"]
        await handlers.handle_registration(self.node, nick, args, reply_target=nick)

        char = await self.env.db.player.get_player("Bob", self.node.net_name)
        self.assertIsNotNone(char, "Character Bob should be created in DB")
        self.assertEqual(char["name"], "Bob")
        self.assertEqual(char["char_class"], "Guardian")

    async def test_03_registration_4_args_case_insensitivity_permutations(self):
        """Verify 4-arg registration allows case-insensitive matches (lowercase, UPPERCASE, MixedCase)."""
        test_cases = [
            ("Charlie", ["charlie", "AI", "Operative", "Fast"]),
            ("Dave", ["DAVE", "Human", "Soldier", "Tough"]),
            ("eVe", ["EvE", "Cyborg", "Infiltrator", "Agile"]),
        ]
        for nick, args in test_cases:
            self.node.sent_messages.clear()
            await handlers.handle_registration(self.node, nick, args, reply_target=nick)
            char = await self.env.db.player.get_player(nick, self.node.net_name)
            self.assertIsNotNone(char, f"Character {nick} should be registered successfully")
            self.assertEqual(char["name"], nick)

    async def test_04_registration_hijack_attempt_rejected(self):
        """Verify attacker Mallory cannot register identity 'Victim'."""
        attacker = "Mallory"
        args = ["Victim", "Cyborg", "Hacker", "Hostile"]
        await handlers.handle_registration(self.node, attacker, args, reply_target=attacker)

        # 1. Victim should NOT exist in DB
        victim = await self.env.db.player.get_player("Victim", self.node.net_name)
        self.assertIsNone(victim, "Victim must NOT be registered by attacker")

        # 2. Mallory should NOT exist in DB either
        mallory = await self.env.db.player.get_player("Mallory", self.node.net_name)
        self.assertIsNone(mallory, "Mallory must NOT be registered via rejected hijack")

        # 3. Explicit rejection message sent
        self.assertTrue(any("Registration rejected: Identity 'Victim' does not match" in m for m in self.node.sent_messages))

    async def test_05_registration_syntax_under_3_args_rejected(self):
        """Verify command with < 3 args returns syntax error without DB modification."""
        nick = "Shorty"
        for short_args in [[], ["Cyborg"], ["Cyborg", "Hacker"]]:
            self.node.sent_messages.clear()
            await handlers.handle_registration(self.node, nick, short_args, reply_target=nick)
            self.assertTrue(any("Syntax: register" in m for m in self.node.sent_messages))
            char = await self.env.db.player.get_player(nick, self.node.net_name)
            self.assertIsNone(char)

    async def test_06_registration_multi_word_traits_joined(self):
        """Verify traits with 5+ arguments are joined properly."""
        nick = "Explorer"
        args = ["Explorer", "Synth", "Scout", "Swift", "and", "Quiet", "Infiltrator"]
        await handlers.handle_registration(self.node, nick, args, reply_target=nick)

        char = await self.env.db.player.get_player("Explorer", self.node.net_name)
        self.assertIsNotNone(char)
        # LLM bio includes joined traits
        self.assertIn("Swift and Quiet Infiltrator", char["bio"])

    async def test_07_registration_rfc_special_characters_in_nick(self):
        """Verify valid RFC 1459/2812 nickname characters ([], _, {}, ^, |, -) register properly."""
        valid_nicks = ["bot[0]", "Agent_47", "net{link}", "alpha^beta", "pipe|line", "dash-nick"]
        for vnick in valid_nicks:
            self.node.sent_messages.clear()
            args = [vnick, "AI", "Agent", "Analytical"]
            await handlers.handle_registration(self.node, vnick, args, reply_target=vnick)
            char = await self.env.db.player.get_player(vnick, self.node.net_name)
            self.assertIsNotNone(char, f"Nickname {vnick} should be accepted")

    async def test_08_registration_illegal_characters_rejected(self):
        """Verify illegal nickname characters (spaces, semicolons, null bytes, CRLF) are rejected."""
        illegal_nicks = ["Bad Nick", "Bad;Nick", "Bad\x00Nick", "Bad\r\nNick", "Bad!Nick", "Bad@Host", "A"*35]
        for inick in illegal_nicks:
            self.node.sent_messages.clear()
            args = [inick, "AI", "Agent", "Illegal"]
            await handlers.handle_registration(self.node, inick, args, reply_target=inick)
            self.assertTrue(
                any("illegal characters or exceeds length limit" in m or "does not match" in m for m in self.node.sent_messages),
                f"Illegal nick {inick!r} should be rejected"
            )

    async def test_09_duplicate_registration_does_not_overwrite(self):
        """Verify re-registering an existing character fails and does not reset stats/credits."""
        # 1. Initial registration
        await handlers.handle_registration(self.node, "ExistingUser", ["Cyborg", "Hacker", "Original"], "ExistingUser")
        char1 = await self.env.db.player.get_player("ExistingUser", self.node.net_name)
        self.assertIsNotNone(char1)
        original_bio = char1["bio"]

        # Award some credits to make state distinct
        await self.env.db.economy.award_credits_bulk({"ExistingUser": 500.0}, self.node.net_name)
        char_funded = await self.env.db.player.get_player("ExistingUser", self.node.net_name)
        self.assertEqual(char_funded["credits"], 500.0)

        # 2. Re-registration attempt
        self.node.sent_messages.clear()
        await handlers.handle_registration(self.node, "ExistingUser", ["Human", "Soldier", "Overwritten"], "ExistingUser")
        self.assertTrue(any("already exists" in m for m in self.node.sent_messages))

        # 3. Verify state remains intact
        char2 = await self.env.db.player.get_player("ExistingUser", self.node.net_name)
        self.assertEqual(char2["credits"], 500.0, "Credits should not be reset")
        self.assertEqual(char2["race"], "Cyborg", "Race should not be overwritten")
        self.assertEqual(char2["bio"], original_bio, "Bio should not be overwritten")

    async def test_10_registration_3_arg_sneak_hijack_prevention(self):
        """Verify that passing someone else's name as first arg in 3-arg syntax does not register them."""
        # Attacker tries: register Alice Cyborg Hacker
        # Under 3-arg syntax, args[0] is race, args[1] is class, args[2] is traits
        # bot_name MUST be attacker's nick
        attacker = "Mallory"
        args = ["Alice", "Cyborg", "Hacker"]
        await handlers.handle_registration(self.node, attacker, args, reply_target=attacker)

        alice = await self.env.db.player.get_player("Alice", self.node.net_name)
        self.assertIsNone(alice, "Alice must not be created")

        mallory = await self.env.db.player.get_player("Mallory", self.node.net_name)
        self.assertIsNotNone(mallory, "Mallory is registered with race=Alice")
        self.assertEqual(mallory["race"], "Alice")


class TestCombatRouterCommandCollision(unittest.IsolatedAsyncioTestCase):
    """Focus Area 2: Combat router command collision handling."""

    async def asyncSetUp(self):
        self.env = TestEnvironment(prefix="ag_stress_router_")
        await self.env.setup()
        self.node = MockNode(self.env.db)
        self.router = CommandRouter(self.node)

    async def asyncTearDown(self):
        await self.env.teardown()

    async def test_11_active_combat_prefixed_and_nonprefixed_verbs(self):
        """Verify CombatEngine parses both prefixed and non-prefixed verbs for queued actions."""
        callback = AsyncMock()
        engine = CombatEngine("match_01", "!a", callback)
        fighter = Entity("Warrior", {"cpu": 10, "ram": 5, "bnd": 5, "sec": 5, "alg": 5, "power": 100})
        engine.add_entity(fighter)
        engine.active = True
        self.node.active_engine = engine

        # 1. Prefixed kinetic: "!a strike Enemy"
        await self.router.dispatch("Warrior", "PRIVMSG", "#automatagrid", "!a strike Enemy", is_admin=False)
        self.assertEqual(fighter.command_queued["intent"], "kinetic")
        self.assertEqual(fighter.command_queued["raw_verb"], "strike")
        self.assertEqual(fighter.command_queued["args"], "Enemy")

        # 2. Non-prefixed kinetic: "strike Enemy"
        await self.router.dispatch("Warrior", "PRIVMSG", "#automatagrid", "strike Enemy", is_admin=False)
        self.assertEqual(fighter.command_queued["intent"], "kinetic")
        self.assertEqual(fighter.command_queued["raw_verb"], "strike")

        # 3. Prefixed defend (single word): "!a defend"
        await self.router.dispatch("Warrior", "PRIVMSG", "#automatagrid", "!a defend", is_admin=False)
        self.assertEqual(fighter.command_queued["intent"], "defend")
        self.assertEqual(fighter.command_queued["raw_verb"], "defend")
        self.assertEqual(fighter.command_queued["args"], "")

        # 4. Non-prefixed defend (single word): "defend"
        await self.router.dispatch("Warrior", "PRIVMSG", "#automatagrid", "defend", is_admin=False)
        self.assertEqual(fighter.command_queued["intent"], "defend")
        self.assertEqual(fighter.command_queued["args"], "")

        # 5. Prefixed cyber scan: "!a scan"
        await self.router.dispatch("Warrior", "PRIVMSG", "#automatagrid", "!a scan", is_admin=False)
        self.assertEqual(fighter.command_queued["intent"], "cyber")
        self.assertEqual(fighter.command_queued["raw_verb"], "scan")

        # 6. Non-prefixed cyber scan: "scan"
        await self.router.dispatch("Warrior", "PRIVMSG", "#automatagrid", "scan", is_admin=False)
        self.assertEqual(fighter.command_queued["intent"], "cyber")
        self.assertEqual(fighter.command_queued["raw_verb"], "scan")

        # 7. Prefixed cyber hack: "!a hack Target"
        await self.router.dispatch("Warrior", "PRIVMSG", "#automatagrid", "!a hack Target", is_admin=False)
        self.assertEqual(fighter.command_queued["intent"], "cyber")
        self.assertEqual(fighter.command_queued["raw_verb"], "hack")
        self.assertEqual(fighter.command_queued["args"], "Target")

    async def test_12_active_combat_non_combatant_and_dead_fighter_ignored(self):
        """Verify non-combatants and dead fighters cannot queue commands."""
        callback = AsyncMock()
        engine = CombatEngine("match_02", "!a", callback)
        alive_fighter = Entity("Alice", {"cpu": 5, "ram": 5, "bnd": 5, "sec": 5, "alg": 5, "power": 100})
        dead_fighter = Entity("Bob", {"cpu": 5, "ram": 5, "bnd": 5, "sec": 5, "alg": 5, "power": 100})
        dead_fighter.hp = 0

        engine.add_entity(alive_fighter)
        engine.add_entity(dead_fighter)
        engine.active = True
        self.node.active_engine = engine

        # Spectator / non-combatant
        await self.router.dispatch("Spectator", "PRIVMSG", "#automatagrid", "defend", is_admin=False)
        self.assertIsNone(alive_fighter.command_queued)

        # Dead fighter
        await self.router.dispatch("Bob", "PRIVMSG", "#automatagrid", "strike Alice", is_admin=False)
        self.assertIsNone(dead_fighter.command_queued)

    async def test_13_out_of_combat_nonprefixed_verbs_do_not_execute(self):
        """Verify non-prefixed verbs when out of combat do not trigger combat or errors."""
        self.node.active_engine = None
        # Send non-prefixed verbs
        for verb in ["defend", "strike", "scan", "hack Bob", "flee"]:
            await self.router.dispatch("Citizen", "PRIVMSG", "#automatagrid", verb, is_admin=False)
        # Should produce zero engine error responses
        self.assertEqual(len(self.node.sent_messages), 0)

    async def test_14_out_of_combat_node_breach_vs_pvp_hack(self):
        """Verify disambiguation between !a hack (node breach) and !a hack <player> (PvP combat)."""
        await self.env.create_test_player("Attacker")
        await self.env.create_test_player("Defender")

        self.node.active_engine = None

        with patch("ai_grid.core.handlers.grid.handle_grid_command", new_callable=AsyncMock) as mock_grid, \
             patch("ai_grid.core.handlers.combat.handle_pvp_command", new_callable=AsyncMock) as mock_pvp:

            # 1. "!a hack" with no arguments -> node breach (handle_grid_command)
            await self.router.dispatch("Attacker", "PRIVMSG", "#automatagrid", "!a hack", is_admin=False)
            await asyncio.sleep(0.05)
            mock_grid.assert_called_once_with(self.node, "Attacker", "#automatagrid", "hack", [])
            mock_pvp.assert_not_called()

            mock_grid.reset_mock()
            mock_pvp.reset_mock()

            # 2. "!a hack grid" -> node breach (handle_grid_command)
            await self.router.dispatch("Attacker", "PRIVMSG", "#automatagrid", "!a hack grid", is_admin=False)
            await asyncio.sleep(0.05)
            mock_grid.assert_called_once_with(self.node, "Attacker", "#automatagrid", "hack", ["grid"])
            mock_pvp.assert_not_called()

            mock_grid.reset_mock()
            mock_pvp.reset_mock()

            # 3. "!a hack Defender" -> PvP hack (handle_pvp_command)
            await self.router.dispatch("Attacker", "PRIVMSG", "#automatagrid", "!a hack Defender", is_admin=False)
            await asyncio.sleep(0.05)
            mock_pvp.assert_called_once_with(self.node, "Attacker", "#automatagrid", "hack", "Defender")
            mock_grid.assert_not_called()

    async def test_15_out_of_combat_pvp_hack_invalid_nickname_rejected(self):
        """Verify !a hack with invalid nickname is cleanly rejected without routing to PvP."""
        with patch("ai_grid.core.handlers.combat.handle_pvp_command", new_callable=AsyncMock) as mock_pvp:
            await self.router.dispatch("Attacker", "PRIVMSG", "#automatagrid", "!a hack Bad;Nick", is_admin=False)
            await asyncio.sleep(0.05)
            mock_pvp.assert_not_called()
            self.assertTrue(any("Invalid target nickname" in m for m in self.node.sent_messages))

    async def test_16_out_of_combat_pvp_attack_and_rob_routing(self):
        """Verify !a attack <target> and !a rob <target> route to PvP handlers."""
        with patch("ai_grid.core.handlers.combat.handle_pvp_command", new_callable=AsyncMock) as mock_pvp:
            # Attack
            await self.router.dispatch("Attacker", "PRIVMSG", "#automatagrid", "!a attack TargetPlayer", is_admin=False)
            await asyncio.sleep(0.05)
            mock_pvp.assert_called_with(self.node, "Attacker", "#automatagrid", "attack", "TargetPlayer")

            mock_pvp.reset_mock()
            # Rob
            await self.router.dispatch("Attacker", "PRIVMSG", "#automatagrid", "!a rob TargetPlayer", is_admin=False)
            await asyncio.sleep(0.05)
            mock_pvp.assert_called_with(self.node, "Attacker", "#automatagrid", "rob", "TargetPlayer")


class TestCombatRepositoryTupleReturnConsistency(unittest.IsolatedAsyncioTestCase):
    """Focus Area 3: Combat repository tuple returns, evasion power persistence, and exceptions."""

    async def asyncSetUp(self):
        self.env = TestEnvironment(prefix="ag_stress_combat_")
        await self.env.setup()
        self.repo = self.env.db.combat

        # Create two test players: Alice and Bob
        self.p1 = await self.env.create_test_player("Alice")
        self.p2 = await self.env.create_test_player("Bob")

        # Put both players in an arena node (non-safezone)
        async with self.env.db.async_session() as session:
            stmt = select(GridNode).where(GridNode.id == self.p1.node_id)
            node = (await session.execute(stmt)).scalars().first()
            if node:
                node.node_type = "arena"
                await session.commit()

    async def asyncTearDown(self):
        await self.env.teardown()

    async def test_17_grid_attack_evasion_commits_power_deduction(self):
        """Empirically prove power deduction is committed to the database when target evades."""
        # Force evasion by setting evade_roll to 1 (<= target.bnd * 2 = 10)
        initial_power = (await self.env.db.player.get_player("Alice", "mocknet"))["power"]

        with patch("random.randint", return_value=1):
            res = await self.repo.grid_attack("Alice", "Bob", "mocknet")

        # 1. Verify 3-tuple return signature
        self.assertIsInstance(res, tuple)
        self.assertEqual(len(res), 3)
        self.assertTrue(res[0], "Evasion attack is considered an attempted action (returns True)")
        self.assertIn("evaded", res[1])
        self.assertIsNone(res[2])

        # 2. Verify power was deducted and committed in a fresh DB session
        updated_char = await self.env.db.player.get_player("Alice", "mocknet")
        expected_power = initial_power - 2.0  # default attack cost is 2.0
        self.assertAlmostEqual(updated_char["power"], expected_power, places=2,
                               msg="Attacker power must be deducted in DB on evasion!")

    async def test_18_grid_attack_success_hit_and_fatal(self):
        """Verify grid_attack returns 3-tuples on successful hit and fatal strike."""
        # 1. Normal hit: evade_roll = 100 (fails evade), alg_roll = 100
        with patch("random.randint", side_effect=[100, 100]):
            res = await self.repo.grid_attack("Alice", "Bob", "mocknet")
        self.assertIsInstance(res, tuple)
        self.assertEqual(len(res), 3)
        self.assertTrue(res[0])
        self.assertIn("struck", res[1])
        self.assertIsNone(res[2])

        # 2. Fatal strike: reduce Bob's HP to 1, then attack
        async with self.env.db.async_session() as session:
            stmt = select(Character).where(Character.name == "Bob")
            bob = (await session.execute(stmt)).scalars().first()
            bob.current_hp = 1
            await session.commit()

        with patch("random.randint", side_effect=[100, 100]):
            res_fatal = await self.repo.grid_attack("Alice", "Bob", "mocknet")
        self.assertIsInstance(res_fatal, tuple)
        self.assertEqual(len(res_fatal), 3)
        self.assertTrue(res_fatal[0])
        self.assertIn("flatlines", res_fatal[1])
        self.assertIsNone(res_fatal[2])

    async def test_19_grid_attack_failure_branches_uniform_tuples(self):
        """Verify all failure branches in grid_attack return uniform 3-tuples."""
        # 1. Target not found
        r1 = await self.repo.grid_attack("Alice", "Ghost", "mocknet")
        self.assertEqual((r1[0], len(r1)), (False, 3))

        # 2. Self-termination
        r2 = await self.repo.grid_attack("Alice", "Alice", "mocknet")
        self.assertEqual((r2[0], len(r2)), (False, 3))
        self.assertIn("Self-termination", r2[1])

        # 3. Insufficient power
        async with self.env.db.async_session() as session:
            stmt = select(Character).where(Character.name == "Alice")
            alice = (await session.execute(stmt)).scalars().first()
            alice.power = 0.5
            await session.commit()
        r3 = await self.repo.grid_attack("Alice", "Bob", "mocknet")
        self.assertEqual((r3[0], len(r3)), (False, 3))
        self.assertIn("Insufficient POWER", r3[1])

        # 4. Safezone prohibited
        async with self.env.db.async_session() as session:
            stmt = select(GridNode).where(GridNode.id == self.p1.node_id)
            node = (await session.execute(stmt)).scalars().first()
            node.node_type = "safezone"
            await session.commit()
        r4 = await self.repo.grid_attack("Alice", "Bob", "mocknet")
        self.assertEqual((r4[0], len(r4)), (False, 3))
        self.assertIn("strictly prohibited", r4[1])

    async def test_20_grid_hack_uniform_tuples_under_all_conditions(self):
        """Verify grid_hack returns uniform 3-tuples on success, failure, and DB exception."""
        # 1. Failure branches
        r_nf = await self.repo.grid_hack("Alice", "Ghost", "mocknet")
        self.assertEqual((r_nf[0], len(r_nf)), (False, 3))

        r_self = await self.repo.grid_hack("Alice", "Alice", "mocknet")
        self.assertEqual((r_self[0], len(r_self)), (False, 3))

        # 2. Hack success: roll >= dc
        with patch("random.randint", return_value=20):
            r_succ = await self.repo.grid_hack("Alice", "Bob", "mocknet")
        self.assertEqual(len(r_succ), 3)
        self.assertTrue(r_succ[0])
        self.assertIn("Hack Successful", r_succ[1])

        # 3. Hack fail (traced): roll < dc
        with patch("random.randint", return_value=1):
            r_fail = await self.repo.grid_hack("Alice", "Bob", "mocknet")
        self.assertEqual(len(r_fail), 3)
        self.assertFalse(r_fail[0])
        self.assertIn("Hack Failed", r_fail[1])

        # 4. Database exception during commit: properly caught and returns 3-tuple
        with patch("random.randint", return_value=20):
            with patch("ai_grid.database.repositories.combat_repo.increment_daily_task", side_effect=OperationalError("COMMIT failed", params=None, orig=Exception("DB lock"))):
                r_exc = await self.repo.grid_hack("Alice", "Bob", "mocknet")
                self.assertIsInstance(r_exc, tuple)
                self.assertEqual(len(r_exc), 3)
                self.assertFalse(r_exc[0])
                self.assertIn("system malfunction", r_exc[1])

        # 5. Vulnerability check: Database exception during query is NOT caught (outside try block)
        with patch.object(self.env.db.combat, "async_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session.execute.side_effect = OperationalError("SELECT failed", params=None, orig=Exception("DB down"))
            mock_session_ctx.return_value.__aenter__.return_value = mock_session
            with self.assertRaises(OperationalError):
                await self.repo.grid_hack("Alice", "Bob", "mocknet")

    async def test_21_grid_rob_uniform_tuples_and_eager_load_flaw(self):
        """Verify grid_rob tuple consistency and uncover MissingGreenlet flaw on item template."""
        # 1. Empty inventory failure returns 3-tuple
        r_empty = await self.repo.grid_rob("Alice", "Bob", "mocknet")
        self.assertEqual(len(r_empty), 3)
        self.assertFalse(r_empty[0])
        self.assertIn("empty", r_empty[1])

        # 2. Add item to Bob's inventory
        async with self.env.db.async_session() as session:
            stmt = select(ItemTemplate).limit(1)
            tpl = (await session.execute(stmt)).scalars().first()
            if not tpl:
                tpl = ItemTemplate(name="TestItem", item_type="hardware")
                session.add(tpl)
                await session.flush()
            stmt_bob = select(Character).where(Character.name == "Bob")
            bob = (await session.execute(stmt_bob)).scalars().first()
            session.add(InventoryItem(character_id=bob.id, template_id=tpl.id))
            await session.commit()

        # 3. Flaw check: Successful theft roll triggers MissingGreenlet lazy-loading error on template
        # causing grid_rob to fall into except branch and fail every successful robbery!
        with patch("random.randint", return_value=20):
            r_succ = await self.repo.grid_rob("Alice", "Bob", "mocknet")
        self.assertEqual(len(r_succ), 3)
        # Note: Because of missing selectinload(InventoryItem.template), r_succ[0] is False instead of True!
        self.assertFalse(r_succ[0], "Empirical proof: successful theft fails due to MissingGreenlet on template")
        self.assertIn("unexpected disturbance", r_succ[1])

        # 4. Rob caught (roll = 1) returns 3-tuple
        with patch("random.randint", return_value=1):
            r_caught = await self.repo.grid_rob("Alice", "Bob", "mocknet")
        self.assertEqual(len(r_caught), 3)
        self.assertFalse(r_caught[0])
        self.assertIn("caught", r_caught[1])

    async def test_21b_grid_attack_missing_exception_handling(self):
        """Empirically prove grid_attack lacks try...except block and leaks unhandled exceptions."""
        from sqlalchemy.ext.asyncio import AsyncSession
        orig_commit = AsyncSession.commit
        async def failing_commit(self):
            raise OperationalError("COMMIT failed", params=None, orig=Exception("Disk full"))

        AsyncSession.commit = failing_commit
        try:
            with patch("random.randint", side_effect=[100, 100]):
                with self.assertRaises(OperationalError):
                    await self.repo.grid_attack("Alice", "Bob", "mocknet")
        finally:
            AsyncSession.commit = orig_commit

    async def test_22_handle_pvp_command_defensive_unpacking(self):
        """Verify handle_pvp_command safely unpacks various return types without crash."""
        node = MockNode(self.env.db)

        # 1. Normal 3-tuple
        with patch.object(self.env.db, "grid_attack", new_callable=AsyncMock, return_value=(True, "Success message", "Loot item")):
            await handlers.combat.handle_pvp_command(node, "Alice", "#automatagrid", "attack", "Bob")
            self.assertTrue(any("Success message" in m for m in node.sent_messages))

        # 2. Legacy 2-tuple (must not raise ValueError: not enough values to unpack)
        node.sent_messages.clear()
        with patch.object(self.env.db, "grid_hack", new_callable=AsyncMock, return_value=(False, "Legacy 2-tuple error")):
            await handlers.combat.handle_pvp_command(node, "Alice", "#automatagrid", "hack", "Bob")
            self.assertTrue(any("Legacy 2-tuple error" in m for m in node.sent_messages))

        # 3. Raw string (non-tuple)
        node.sent_messages.clear()
        with patch.object(self.env.db, "grid_rob", new_callable=AsyncMock, return_value="Malformed string response"):
            await handlers.combat.handle_pvp_command(node, "Alice", "#automatagrid", "rob", "Bob")
            self.assertTrue(any("Malformed string response" in m for m in node.sent_messages))


if __name__ == "__main__":
    unittest.main()
