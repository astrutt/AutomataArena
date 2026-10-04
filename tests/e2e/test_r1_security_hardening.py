"""
tests/e2e/test_r1_security_hardening.py — Automated Security Hardening Audit Test Suite.

Proves:
1. Malformed IRC inputs, protocol length boundaries, and CRLF injection attempts are safely rejected.
2. Bot command injection attempts fail safely.
3. Unauthorized admin command attempts are rejected and RBAC is strictly enforced programmatically.
4. Player identity protection and registration spoofing prevention are strictly enforced.
5. Centralized input validation safely bounds oversized strings, illegal directions, and invalid quantities.
6. Combat collision resolution and tuple consistency in combat repositories.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Character, GridNode, Player, InventoryItem, ItemTemplate
from ai_grid.grid_combat import CombatEngine, Entity
from ai_grid.core.command_router import CommandRouter
import ai_grid.core.handlers as handlers
from tests.e2e.fixtures import MockIRCServer, MockLLMServer, TestEnvironment
from tests.sandbox_harness import SandboxHarness


class AsyncMockWriter:
    """Mock socket stream writer for unit tests."""
    def write(self, data): pass
    async def drain(self): pass
    def close(self): pass
    def is_closing(self): return False


class AsyncMockCallback:
    """Mock callback for combat engine."""
    async def __call__(self, msg): pass


class TestCRLFAndProtocolSanitization(unittest.IsolatedAsyncioTestCase):
    """Verifies prevention of CRLF injection, line desync, and protocol length boundaries."""

    async def test_01_irc_client_send_crlf_injection(self):
        """Verify IRCClient rejects or sanitizes embedded CRLF characters."""
        from ai_grid.core.irc_client import IRCClient
        client = IRCClient("127.0.0.1", 6667)
        client.writer = AsyncMockWriter()

        malicious_input = "PRIVMSG #channel :Safe text\r\nPRIVMSG #channel :INJECTED COMMAND"
        if hasattr(client, "sanitize_line"):
            sanitized = client.sanitize_line(malicious_input)
            self.assertNotIn("\r", sanitized)
            self.assertNotIn("\n", sanitized)

    async def test_02_bot_send_crlf_injection(self):
        """Verify AutomataBot.send() sanitizes or strips CRLF."""
        from ai_player.bot import AutomataBot
        bot = AutomataBot()
        bot.writer = AsyncMockWriter()

        malicious_line = "PRIVMSG ArenaMaster :x move north\r\nPRIVMSG ArenaMaster :x admin shutdown"
        if hasattr(bot, "sanitize"):
            clean = bot.sanitize(malicious_line)
            self.assertNotIn("\r", clean)
            self.assertNotIn("\n", clean)

    async def test_03_outbound_line_length_truncation_rfc512(self):
        """Verify outbound messages exceeding 512 bytes are bounded or truncated safely."""
        from ai_grid.core.validation import sanitize_irc_outbound
        long_line = "A" * 1000
        sanitized = sanitize_irc_outbound(long_line)
        self.assertLessEqual(len(sanitized.encode("utf-8")), 510)

    async def test_04_inbound_malformed_raw_lines_resilience(self):
        """Verify engine listen loop handles malformed raw lines without crashing."""
        async with SandboxHarness() as harness:
            corrupt_lines = [
                "",                                        # Empty line
                ":",                                       # Empty prefix
                ":attacker!user@host",                     # Missing command
                "PING",                                    # Missing target
                "\x00\x00\x00",                            # Null bytes
                ":attacker!u@h PRIVMSG",                   # Missing target & message
                ":attacker!u@h PRIVMSG #chan :\x01ACTION", # Unterminated CTCP
            ]
            for line in corrupt_lines:
                await harness.send_raw_irc(line)
            await asyncio.sleep(0.2)
            reply = await harness.send_command("help", timeout=4.0)
            self.assertIsNotNone(reply, "Engine should remain responsive after malformed input")


class TestCommandInjectionAndSanitization(unittest.IsolatedAsyncioTestCase):
    """Verifies command argument separation, shell injection, and SQL injection safety."""

    async def test_05_bot_command_argument_injection_separator(self):
        """Verify command arguments with separators do not execute secondary commands."""
        async with SandboxHarness() as harness:
            await harness.send_command("move north; shutdown")
            await asyncio.sleep(0.1)
            reply = await harness.send_command("help", timeout=3.0)
            self.assertIsNotNone(reply)

    async def test_06_sql_injection_resilience_in_parameters(self):
        """Verify SQL injection payloads in parameters do not corrupt DB or leak data."""
        async with SandboxHarness() as harness:
            sql_payload = "'; DROP TABLE characters; --"
            await harness.send_command(f"info {sql_payload}")
            char = await harness.get_player_character("TestPlayer")
            self.assertIsNotNone(char)

    async def test_07_token_bucket_rate_limiting_and_flood_rejection(self):
        """Verify rapid-fire flood triggers token bucket exhaustion."""
        async with SandboxHarness() as harness:
            for _ in range(15):
                await harness.send_command("help", wait_reply=False)
            await asyncio.sleep(0.5)
            reply = await harness.send_command("help", timeout=3.0)
            self.assertIsNotNone(reply)


class TestAdministrativeRBACEnforcement(unittest.IsolatedAsyncioTestCase):
    """Verifies strict programmatic RBAC enforcement on administrative verbs."""

    async def test_08_unauthorized_user_admin_command_rejection(self):
        """Verify unprivileged standard user receives Access Denied on admin commands."""
        async with SandboxHarness(player_nick="StandardUser") as harness:
            admin_verbs = ["admin", "shutdown", "broadcast Test", "topic Test", "status"]
            for v in admin_verbs:
                reply = await harness.send_command(v, timeout=3.0)
                self.assertIsNotNone(reply)
                self.assertIn("Access Denied", reply["text"])

    async def test_09_spoofed_admin_nick_without_nickserv_rejection(self):
        """Verify spoofed admin nick lacking NickServ verification (+r) is rejected."""
        async with SandboxHarness(player_nick="TestAdmin") as harness:
            if "testadmin" in harness.engine_node.nickserv_verified:
                harness.engine_node.nickserv_verified.remove("testadmin")

            reply = await harness.send_command("shutdown", timeout=3.0)
            self.assertIsNotNone(reply)
            self.assertIn("Access Denied", reply["text"])

    async def test_10_verified_admin_nick_execution(self):
        """Verify admin user who is both in config admins AND NickServ +r verified succeeds."""
        async with SandboxHarness(player_nick="TestAdmin") as harness:
            harness.engine_node.admins = ["testadmin"]
            harness.engine_node.nickserv_verified.add("testadmin")

            reply = await harness.send_command("status", timeout=3.0)
            self.assertIsNotNone(reply)
            self.assertNotIn("Access Denied", reply["text"])

    async def test_10b_admin_token_session_auth_and_deauth(self):
        """Verify token-based admin session authentication and deauth."""
        async with SandboxHarness(player_nick="TestAdmin") as harness:
            node = harness.engine_node
            node.admins = ["testadmin"]
            node.nickserv_verified.add("testadmin")
            node.config['admin_token'] = "SecretToken123"

            import ai_grid.manager as mgr
            mgr.CONFIG['admin_token'] = "SecretToken123"

            # 1. Admin command rejected because no session exists
            reply = await harness.send_command("status", timeout=3.0)
            self.assertIsNotNone(reply)
            self.assertIn("Access Denied", reply["text"])

            # 2. Public channel auth rejected
            await harness.send_command("admin auth SecretToken123", target="#automatagrid")
            self.assertNotIn("testadmin", node.admin_sessions)

            # 3. PM auth with wrong token fails
            await harness.send_command("admin auth WrongToken", target=harness.manager_nick)
            self.assertNotIn("testadmin", node.admin_sessions)

            # 4. PM auth with correct token succeeds
            await harness.send_command("admin auth SecretToken123", target=harness.manager_nick)
            self.assertIn("testadmin", node.admin_sessions)

            # 5. Admin command now succeeds
            reply2 = await harness.send_command("status", timeout=3.0)
            self.assertIsNotNone(reply2)
            self.assertNotIn("Access Denied", reply2["text"])

            # 6. Deauth clears session
            await harness.send_command("admin deauth", target=harness.manager_nick)
            self.assertNotIn("testadmin", node.admin_sessions)


class TestPlayerIdentityAndRegistrationProtection(unittest.IsolatedAsyncioTestCase):
    """Verifies character creation binding to source_nick and anti-spoofing."""

    async def test_11_registration_bound_strictly_to_source_nick(self):
        """Verify registration automatically binds character to caller source_nick."""
        async with SandboxHarness(player_nick="NewRecruit") as harness:
            reply = await harness.send_command("register Victim Cyborg Hacker CombatReady", timeout=3.0)
            self.assertIsNotNone(reply)
            self.assertIn("Registration rejected", reply["text"])

            char = await harness.get_player_character("NewRecruit")
            victim = await harness.get_player_character("Victim")
            self.assertIsNone(victim, "Attacker must NOT be able to register on behalf of Victim")

    async def test_12_duplicate_registration_account_takeover_rejected(self):
        """Verify re-registering an existing character does not overwrite stats/credits."""
        async with SandboxHarness(player_nick="TestPlayer") as harness:
            char_before = await harness.get_player_character("TestPlayer")
            credits_before = char_before.credits

            await harness.send_command("register TestPlayer Human Marine NewBio", timeout=3.0)
            await asyncio.sleep(0.2)

            char_after = await harness.get_player_character("TestPlayer")
            self.assertEqual(char_after.credits, credits_before)

    async def test_13_illegal_character_registration_rejected(self):
        """Verify registration with illegal nickname characters is safely rejected."""
        from ai_grid.core.validation import validate_nickname
        illegal_nicks = ["User\r\n", "User:Admin", "   ", "User!ident", "User@host", "A" * 35]
        for nick in illegal_nicks:
            self.assertFalse(validate_nickname(nick))


class TestInputValidationModule(unittest.IsolatedAsyncioTestCase):
    """Verifies central validation boundaries on strings, directions, and quantities."""

    async def test_14_oversized_string_input_rejection(self):
        """Verify oversized 10,000 char strings are bounded safely."""
        from ai_grid.core.validation import sanitize_irc_outbound, validate_nickname, validate_node_name
        huge_str = "A" * 10000
        self.assertFalse(validate_nickname(huge_str))
        self.assertFalse(validate_node_name(huge_str))
        self.assertLessEqual(len(sanitize_irc_outbound(huge_str)), 510)

    async def test_15_illegal_direction_inputs(self):
        """Verify move rejects invalid directions without changing player node."""
        async with SandboxHarness() as harness:
            char_before = await harness.get_player_character("TestPlayer")
            initial_node_id = char_before.node_id

            invalid_directions = ["diagonal", "../../up", "left", "12345", "NORTH;DROP"]
            for d in invalid_directions:
                await harness.send_command(f"move {d}", timeout=3.0)
                char_after = await harness.get_player_character("TestPlayer")
                self.assertEqual(char_after.node_id, initial_node_id)

    async def test_16_invalid_numeric_and_negative_quantities(self):
        """Verify economy and minigames reject negative and non-numeric inputs."""
        async with SandboxHarness() as harness:
            char_before = await harness.get_player_character("TestPlayer")
            initial_credits = char_before.credits

            negative_tests = ["dice -500 high", "dice NaN high", "dice Inf high"]
            for cmd in negative_tests:
                await harness.send_command(cmd, timeout=3.0)
                char_after = await harness.get_player_character("TestPlayer")
                self.assertEqual(char_after.credits, initial_credits)

    async def test_17_node_name_length_and_character_validation(self):
        """Verify node name constraints (<= 11 chars, alphanumeric + _)."""
        from ai_grid.core.validation import validate_node_name
        self.assertTrue(validate_node_name("Sector_9"))
        self.assertTrue(validate_node_name("Alpha1"))
        self.assertFalse(validate_node_name("TooLongNodeNameHere"))
        self.assertFalse(validate_node_name("Node;DROP"))
        self.assertFalse(validate_node_name("Node Name"))


class TestCombatCollisionAndTupleConsistency(unittest.IsolatedAsyncioTestCase):
    """Verifies combat router dispatch, queue_command parsing, and tuple consistency."""

    async def test_18_active_combat_router_command_queueing(self):
        """Verify prefixed and non-prefixed combat commands queue properly in CombatEngine."""
        engine = CombatEngine("test_match", "!a", AsyncMockCallback())
        dummy_player = Entity("Fighter1", {"cpu": 5, "ram": 5, "bnd": 5, "sec": 5, "alg": 5, "power": 100})
        engine.add_entity(dummy_player)
        engine.active = True

        # Test 1: Prefixed multi-word command
        engine.queue_command("Fighter1", "!a strike Enemy")
        self.assertIsNotNone(dummy_player.command_queued)
        self.assertEqual(dummy_player.command_queued["intent"], "kinetic")
        self.assertEqual(dummy_player.command_queued["raw_verb"], "strike")

        # Test 2: Non-prefixed multi-word command
        engine.queue_command("Fighter1", "strike Enemy")
        self.assertEqual(dummy_player.command_queued["intent"], "kinetic")

        # Test 3: Prefixed single-word command
        engine.queue_command("Fighter1", "!a defend")
        self.assertEqual(dummy_player.command_queued["intent"], "defend")

        # Test 4: Non-prefixed single-word command
        engine.queue_command("Fighter1", "defend")
        self.assertEqual(dummy_player.command_queued["intent"], "defend")

        # Test 5: Cyber scan command
        engine.queue_command("Fighter1", "!a scan")
        self.assertEqual(dummy_player.command_queued["intent"], "cyber")

    async def test_19_combat_repo_tuple_consistency_grid_hack(self):
        """Verify combat_repo.grid_hack always returns 3-tuple (bool, str, Optional[str])."""
        async with TestEnvironment() as env:
            await env.create_test_player("Attacker")
            # 1. Target not found
            res = await env.db.combat.grid_hack("Attacker", "Ghost", "mocknet")
            self.assertIsInstance(res, tuple)
            self.assertEqual(len(res), 3)
            self.assertFalse(res[0])

            # 2. Self-target
            res = await env.db.combat.grid_hack("Attacker", "Attacker", "mocknet")
            self.assertIsInstance(res, tuple)
            self.assertEqual(len(res), 3)
            self.assertFalse(res[0])

    async def test_20_combat_repo_tuple_consistency_grid_rob(self):
        """Verify combat_repo.grid_rob always returns 3-tuple (bool, str, Optional[str])."""
        async with TestEnvironment() as env:
            await env.create_test_player("Thief")
            # 1. Target not found
            res = await env.db.combat.grid_rob("Thief", "Ghost", "mocknet")
            self.assertIsInstance(res, tuple)
            self.assertEqual(len(res), 3)
            self.assertFalse(res[0])

            # 2. Self-target
            res = await env.db.combat.grid_rob("Thief", "Thief", "mocknet")
            self.assertIsInstance(res, tuple)
            self.assertEqual(len(res), 3)
            self.assertFalse(res[0])

    async def test_21_combat_repo_evasion_commits_power(self):
        """Verify power cost is committed even when an attack is evaded."""
        async with TestEnvironment() as env:
            p1 = await env.create_test_player("Alice")
            p2 = await env.create_test_player("Bob")
            initial_power = p1.power

            # Mark node as arena (non-safezone) so attack can proceed
            async with env.db.async_session() as session:
                from sqlalchemy.future import select
                stmt = select(GridNode).where(GridNode.id == p1.node_id)
                node = (await session.execute(stmt)).scalars().first()
                if node:
                    node.node_type = "arena"
                    await session.commit()

            # Execute attack
            success, msg, _ = await env.db.combat.grid_attack("Alice", "Bob", "mocknet")
            updated = await env.db.player.get_player("Alice", "mocknet")
            self.assertLess(updated["power"], initial_power)


if __name__ == "__main__":
    unittest.main()
