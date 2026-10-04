"""
tests/test_m2_adversarial_stress.py — Milestone 2 Adversarial Stress & Hardening Test Suite.

Authored by Challenger M2 (challenger_m2_3) to empirically stress-test:
1. CRLF and newline injection attack scenarios against sanitize_irc_outbound,
   IRCClient.send(), and AutomataBot.send().
2. Validation fuzzing on validate_nickname, validate_node_name, validate_direction,
   validate_item_name, validate_quantity, and validate_token.
3. Administrative RBAC bypass attempts on manager.py check_admin_privilege and
   handlers/admin.py (spoofed nicks, unverified nicks, expired sessions, forged tokens,
   public channel attempts).
"""

import asyncio
import time
import unittest
from unittest.mock import MagicMock, AsyncMock

from ai_grid.core.validation import (
    sanitize_irc_outbound,
    validate_nickname,
    validate_node_name,
    validate_direction,
    validate_item_name,
    validate_quantity,
    validate_token,
)
from ai_grid.core.irc_client import IRCClient
from ai_player.bot import AutomataBot


class MockSocketWriter:
    """Mock StreamWriter for capturing outbound wire bytes."""
    def __init__(self):
        self.buffer = bytearray()
        self.written_lines = []
        self.closed = False

    def write(self, data: bytes):
        self.buffer.extend(data)
        self.written_lines.append(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class TestCRLFAndNewlineInjectionAdversarial(unittest.TestCase):
    """Deep adversarial stress testing on CRLF sanitization and protocol framing."""

    def test_crlf_combinations_and_embedded_protocol_injection(self):
        """Test varied combinations of CRLF, LF, CR, and repeated separators."""
        attack_payloads = [
            "PRIVMSG #chan :hello\r\nQUIT :pwned",
            "PRIVMSG #chan :hello\nJOIN #secret",
            "PRIVMSG #chan :hello\rKICK #chan victim",
            "PRIVMSG #chan :hello\r\r\r\n\n\nPRIVMSG #chan :injected",
            "\r\n\r\n\r\n",
            "foo\rbar\nbaz\r\nqux",
            "NOTICE target :test\r\nMODE target +o",
        ]
        for payload in attack_payloads:
            cleaned = sanitize_irc_outbound(payload)
            self.assertNotIn("\r", cleaned, f"Payload contained unescaped CR: {payload!r}")
            self.assertNotIn("\n", cleaned, f"Payload contained unescaped LF: {payload!r}")

    def test_wire_framing_guarantee_rfc2812(self):
        """Ensure wire payload with terminating CRLF never exceeds 512 bytes."""
        fuzz_lengths = [0, 1, 100, 500, 509, 510, 511, 512, 513, 1000, 50000]
        for length in fuzz_lengths:
            raw = "X" * length
            sanitized = sanitize_irc_outbound(raw)
            # Wire format appends \r\n (2 bytes)
            wire_bytes = f"{sanitized}\r\n".encode("utf-8")
            self.assertLessEqual(
                len(wire_bytes),
                512,
                f"Wire bytes exceeded 512 RFC limit for length {length}: {len(wire_bytes)} bytes",
            )

    def test_multibyte_utf8_boundary_truncation(self):
        """Stress-test multibyte UTF-8 characters falling precisely across the 510-byte boundary."""
        # 3-byte character: ⚡ (0xE2 0x9A 0xA1) or 🛡 (4-byte: 0xF0 0x9F 0x9B 0xA1)
        shield = "🛡"  # 4 bytes
        # Construct string where 4-byte char crosses 510 bytes
        for pad_len in [507, 508, 509, 510]:
            payload = ("A" * pad_len) + (shield * 5)
            sanitized = sanitize_irc_outbound(payload)
            encoded = sanitized.encode("utf-8")
            self.assertLessEqual(len(encoded), 510)
            # Must decode cleanly without replacement or corrupted bytes
            decoded = encoded.decode("utf-8")
            self.assertEqual(decoded, sanitized)

    def test_none_and_non_string_types_to_sanitizer(self):
        """Sanitizer must gracefully handle None, numbers, booleans, and objects."""
        test_inputs = [None, 12345, 99.9, True, False, ["list"], {"dict": 1}]
        for item in test_inputs:
            res = sanitize_irc_outbound(item)
            self.assertIsInstance(res, str)
            self.assertNotIn("\r", res)
            self.assertNotIn("\n", res)
            self.assertLessEqual(len(res.encode("utf-8")), 510)


class TestIRCClientAndBotOutboundFraming(unittest.IsolatedAsyncioTestCase):
    """Verify that socket writers for IRCClient and AutomataBot enforce strict framing."""

    async def test_irc_client_send_framing(self):
        """IRCClient.send must sanitize and emit exactly one trailing CRLF."""
        client = IRCClient("test_net", {"server": "127.0.0.1", "port": 6667})
        writer = MockSocketWriter()
        client.writer = writer

        malicious = "PRIVMSG #arena :Normal attack\r\nQUIT :Drop all connections\r\n"
        await client.send(malicious)

        # Inspect raw bytes written
        raw = bytes(writer.buffer)
        # Must end with \r\n
        self.assertTrue(raw.endswith(b"\r\n"))
        # Must have no other \r or \n
        content_before_ending = raw[:-2]
        self.assertNotIn(b"\r", content_before_ending)
        self.assertNotIn(b"\n", content_before_ending)
        self.assertLessEqual(len(raw), 512)

    async def test_automata_bot_send_framing(self):
        """AutomataBot.send must sanitize and emit exactly one trailing CRLF."""
        bot = AutomataBot()
        writer = MockSocketWriter()
        bot.writer = writer

        malicious = "PRIVMSG #arena :!a strike\n!a admin shutdown\r\n"
        await bot.send(malicious)

        raw = bytes(writer.buffer)
        self.assertTrue(raw.endswith(b"\r\n"))
        content_before_ending = raw[:-2]
        self.assertNotIn(b"\r", content_before_ending)
        self.assertNotIn(b"\n", content_before_ending)
        self.assertLessEqual(len(raw), 512)

    async def test_automata_bot_process_turn_multiline_llm_splitting(self):
        """AutomataBot.process_turn must only take first non-empty line of LLM output."""
        bot = AutomataBot()
        writer = MockSocketWriter()
        bot.writer = writer
        bot.char_data = {"name": "AI_Bot", "race": "Synth", "class": "Warrior"}
        bot.manual_override_until = 0
        bot.puppet_mode = False
        bot.last_action_time = 0

        # Mock LLM returning multiline command injection
        multiline_llm = "!a strike Enemy\n!a admin shutdown\n!a quit"
        with unittest.mock.patch("ai_player.bot.call_llm", return_value=multiline_llm):
            await bot.process_turn("TURN 1: RESULTS")

        raw = bytes(writer.buffer)
        self.assertTrue(raw.endswith(b"\r\n"))
        content = raw.decode("utf-8")
        self.assertIn("!a strike Enemy", content)
        self.assertNotIn("admin shutdown", content)
        self.assertNotIn("!a quit", content)


class TestValidationFuzzingAdversarial(unittest.TestCase):
    """Exhaustive boundary and fuzzing test cases on validation functions."""

    def test_validate_nickname_fuzzing(self):
        """Fuzz validate_nickname with valid RFC chars, boundaries, and malicious inputs."""
        # Valid nicknames
        valid = [
            "a", "A", "Z" * 30, "nick_name", "bot[1]", "team{alpha}",
            "user\\name", "nick^3", "pipe|nick", "dash-nick", "Alpha_123"
        ]
        for v in valid:
            self.assertTrue(validate_nickname(v), f"Expected valid nickname: {v}")

        # Invalid nicknames
        invalid = [
            "",  # empty
            "A" * 31,  # too long (max 30)
            "A" * 1000,
            "nick name",  # space
            " nick",  # leading space
            "nick ",  # trailing space
            "nick\nname",  # newline
            "nick\rname",  # CR
            "nick\x00name",  # NULL
            "nick!user",  # ! not allowed
            "nick@host",  # @ not allowed
            "nick#chan",  # # not allowed
            "nick:admin",  # : not allowed
            "nick*mask",  # * not allowed
            "nick?mask",  # ? not allowed
            "👾bot",  # Unicode emoji
            "nïck",  # Accented unicode
            "nick\u200b",  # Zero-width space
            None, 123, True, False, [], {}
        ]
        for inv in invalid:
            self.assertFalse(validate_nickname(inv), f"Expected invalid nickname: {inv!r}")

    def test_validate_node_name_fuzzing(self):
        """Fuzz validate_node_name with boundary lengths and illegal characters."""
        # Valid: alphanumeric + _, 1-11 chars
        valid = ["A", "a", "1", "Sector_9", "Alpha_1", "ABCDEFGHIJK", "12345678901"]
        for v in valid:
            self.assertTrue(validate_node_name(v), f"Expected valid node: {v}")

        # Invalid
        invalid = [
            "",
            "ABCDEFGHIJKL",  # 12 chars (> 11)
            "A" * 100,
            "Node-1",  # Hyphen is NOT permitted in node name regex
            "Node 1",  # Space
            "Node.1",
            "Node;DROP",
            "Node/1",
            "Node$1",
            "Sector\n9",
            None, 1234, False, [], {}
        ]
        for inv in invalid:
            self.assertFalse(validate_node_name(inv), f"Expected invalid node: {inv!r}")

    def test_validate_direction_fuzzing(self):
        """Fuzz validate_direction with case variants, abbreviations, and garbage."""
        valid_map = {
            "north": "north", "NORTH": "north", "NoRtH": "north", "n": "north", "N": "north",
            "south": "south", "SOUTH": "south", "s": "south", "S": "south",
            "east": "east", "EAST": "east", "e": "east", "E": "east",
            "west": "west", "WEST": "west", "w": "west", "W": "west",
            "up": "up", "UP": "up", "u": "up", "U": "up",
            "down": "down", "DOWN": "down", "d": "down", "D": "down",
            "  north  ": "north", "\tn\t": "north",
        }
        for inp, expected in valid_map.items():
            self.assertEqual(validate_direction(inp), expected, f"Failed on {inp!r}")

        invalid = [
            "", "   ", "northwest", "nw", "se", "left", "right", "forward",
            "back", "in", "out", "north;drop", "123", None, 1, False, []
        ]
        for inv in invalid:
            self.assertIsNone(validate_direction(inv), f"Expected None for {inv!r}")

    def test_validate_item_name_fuzzing(self):
        """Fuzz validate_item_name with valid characters, whitespace, and injection strings."""
        valid = [
            "A", "Nano_Patch", "ZeroDay_Chain", "Laser Rifle", "MK-IV Armor",
            "A" * 50, "Item 1 2 3", "Item-Name_Test"
        ]
        for v in valid:
            self.assertTrue(validate_item_name(v), f"Expected valid item: {v}")

        invalid = [
            "", "   ", "\t", "\n",
            "A" * 51,  # > 50 chars
            "Item; DROP TABLE inventory;",
            "Item<script>",
            "Item/Slash",
            "Item$Dollar",
            "Item*Asterisk",
            None, 123, True, False, []
        ]
        for inv in invalid:
            self.assertFalse(validate_item_name(inv), f"Expected invalid item: {inv!r}")

    def test_validate_quantity_fuzzing(self):
        """Fuzz validate_quantity across integer boundaries, types, overflows, and DoS."""
        # Valid values
        self.assertEqual(validate_quantity(1), 1)
        self.assertEqual(validate_quantity("100"), 100)
        self.assertEqual(validate_quantity(100.0), 100)
        self.assertEqual(validate_quantity(1_000_000_000), 1_000_000_000)
        self.assertEqual(validate_quantity("  50  "), 50)

        # Invalid values
        invalid = [
            0,  # Below default min_val 1
            -1,  # Negative
            -9999999,
            1_000_000_001,  # Above default max_val
            "0",
            "-50",
            "100.5",  # Non-integer float string
            100.5,  # Non-integer float
            True,  # Boolean (critical: bool is int subclass in Python!)
            False,
            None,
            "abc",
            "NaN",
            "Inf",
            "-Inf",
            "100; DROP",
            "1e6",
            "9" * 16,  # > 15 chars string length limit (DoS protection)
            "9" * 100,
            [],
            {},
        ]
        for inv in invalid:
            self.assertIsNone(validate_quantity(inv), f"Expected None for quantity: {inv!r}")

        # Custom bounds
        self.assertEqual(validate_quantity(0, min_val=0), 0)
        self.assertIsNone(validate_quantity(-1, min_val=0))
        self.assertEqual(validate_quantity(50, min_val=10, max_val=50), 50)
        self.assertIsNone(validate_quantity(51, min_val=10, max_val=50))

    def test_validate_token_fuzzing(self):
        """Fuzz validate_token across lengths, characters, and malicious payloads."""
        valid = [
            "12345678",  # 8 chars (min)
            "c8f43a98-3f44-42b7-8326-0e363d6f4661",  # UUID 36 chars
            "A" * 64,  # 64 chars (max)
            "token-with-hyphens-12345",
        ]
        for v in valid:
            self.assertTrue(validate_token(v), f"Expected valid token: {v}")

        invalid = [
            "",
            "1234567",  # 7 chars (< 8)
            "A" * 65,  # 65 chars (> 64)
            "token with spaces",
            "token_with_underscore",  # Underscore is NOT allowed in auth token regex
            "token;DROP",
            "token'OR'1'='1",
            "token\n1234",
            None, 12345678, True, False, []
        ]
        for inv in invalid:
            self.assertFalse(validate_token(inv), f"Expected invalid token: {inv!r}")


class TestAdminRBACAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress-testing of check_admin_privilege and admin handler RBAC."""

    def setUp(self):
        # Create a mock GridNode
        self.node = MagicMock()
        self.node.admins = ["admin_alice", "admin_bob"]
        self.node.nickserv_verified = set()
        self.node.admin_sessions = {}
        self.node.prefix = "!a"
        self.node.config = {"channel": "#automatagrid", "admin_token": "SecretPassphrase123"}
        self.node.net_name = "mocknet"
        self.node.send = AsyncMock()

        # Bind the actual check_admin_privilege logic
        from ai_grid.manager import GridNode
        self.node.check_admin_privilege = GridNode.check_admin_privilege.__get__(self.node, GridNode)
        self.node.is_admin = GridNode.is_admin.__get__(self.node, GridNode)

    async def test_spoofed_nick_not_in_admins(self):
        """Attacker using non-admin nickname is immediately rejected."""
        ok, reason = self.node.check_admin_privilege("EvilHacker")
        self.assertFalse(ok)
        self.assertEqual(reason, "NOT_ADMIN")
        self.assertFalse(self.node.is_admin("EvilHacker"))

    async def test_admin_nick_without_nickserv_verification(self):
        """Attacker spoofing admin nick without +r NickServ status is rejected."""
        ok, reason = self.node.check_admin_privilege("admin_alice")
        self.assertFalse(ok)
        self.assertEqual(reason, "NOT_VERIFIED")
        self.assertFalse(self.node.is_admin("admin_alice"))

    async def test_admin_nick_case_insensitivity(self):
        """Case variations of admin nick (ADMIN_ALICE, Admin_Alice) check properly."""
        ok, reason = self.node.check_admin_privilege("ADMIN_ALICE")
        self.assertFalse(ok)
        self.assertEqual(reason, "NOT_VERIFIED")

        # Now verify in NickServ (stored lowercase)
        self.node.nickserv_verified.add("admin_alice")

        # Config has admin_token, so without session it should require session
        import ai_grid.manager as mgr
        old_cfg = mgr.CONFIG.get("admin_token")
        try:
            mgr.CONFIG["admin_token"] = "SecretPassphrase123"
            ok, reason = self.node.check_admin_privilege("ADMIN_ALICE")
            self.assertFalse(ok)
            self.assertEqual(reason, "SESSION_REQUIRED")

            # With active session
            self.node.admin_sessions["admin_alice"] = time.time() + 3600
            ok, reason = self.node.check_admin_privilege("ADMIN_ALICE")
            self.assertTrue(ok)
            self.assertEqual(reason, "AUTHORIZED")
        finally:
            if old_cfg is not None:
                mgr.CONFIG["admin_token"] = old_cfg
            else:
                mgr.CONFIG.pop("admin_token", None)

    async def test_admin_session_expiry_time_travel(self):
        """Admin session becomes invalid after TTL expiry."""
        self.node.nickserv_verified.add("admin_alice")
        self.node.admin_sessions["admin_alice"] = time.time() - 1  # Expired 1s ago

        import ai_grid.manager as mgr
        old_cfg = mgr.CONFIG.get("admin_token")
        try:
            mgr.CONFIG["admin_token"] = "SecretPassphrase123"
            ok, reason = self.node.check_admin_privilege("admin_alice")
            self.assertFalse(ok)
            self.assertEqual(reason, "SESSION_REQUIRED")
        finally:
            if old_cfg is not None:
                mgr.CONFIG["admin_token"] = old_cfg
            else:
                mgr.CONFIG.pop("admin_token", None)

    async def test_admin_handler_public_channel_auth_rejection(self):
        """Attempting !a admin auth in public channel triggers security alarm and rejects."""
        from ai_grid.core.handlers.admin import handle_admin_command

        self.node.nickserv_verified.add("admin_alice")
        # In public channel '#automatagrid'
        await handle_admin_command(
            self.node,
            admin_nick="admin_alice",
            verb="admin",
            args=["auth", "SecretPassphrase123"],
            reply_target="#automatagrid",
        )

        # Must not establish session
        self.assertNotIn("admin_alice", self.node.admin_sessions)
        # Must emit security alarm to PM
        self.assertTrue(self.node.send.called)
        sent_msgs = [call.args[0] for call in self.node.send.call_args_list]
        alarm_sent = any("CRITICAL: Admin authentication commands must be executed via Private Message" in m for m in sent_msgs)
        self.assertTrue(alarm_sent, f"Expected alarm message in calls: {sent_msgs}")

    async def test_admin_handler_forged_token_pm_auth(self):
        """PM auth with wrong token fails and logs warning."""
        from ai_grid.core.handlers.admin import handle_admin_command

        self.node.nickserv_verified.add("admin_alice")

        import ai_grid.manager as mgr
        old_cfg = mgr.CONFIG.get("admin_token")
        try:
            mgr.CONFIG["admin_token"] = "SecretPassphrase123"
            await handle_admin_command(
                self.node,
                admin_nick="admin_alice",
                verb="admin",
                args=["auth", "ForgedTokenPayload"],
                reply_target="admin_alice",  # PM
            )

            self.assertNotIn("admin_alice", self.node.admin_sessions)
            sent_msgs = [call.args[0] for call in self.node.send.call_args_list]
            self.assertTrue(any("Authentication failed: Invalid token" in m for m in sent_msgs))
        finally:
            if old_cfg is not None:
                mgr.CONFIG["admin_token"] = old_cfg
            else:
                mgr.CONFIG.pop("admin_token", None)

    async def test_admin_handler_valid_token_pm_auth_and_deauth(self):
        """PM auth with valid token succeeds; deauth terminates session."""
        from ai_grid.core.handlers.admin import handle_admin_command

        self.node.nickserv_verified.add("admin_alice")

        import ai_grid.manager as mgr
        old_cfg = mgr.CONFIG.get("admin_token")
        try:
            mgr.CONFIG["admin_token"] = "SecretPassphrase123"
            # 1. Auth
            await handle_admin_command(
                self.node,
                admin_nick="admin_alice",
                verb="admin",
                args=["auth", "SecretPassphrase123"],
                reply_target="admin_alice",
            )
            self.assertIn("admin_alice", self.node.admin_sessions)
            self.assertGreater(self.node.admin_sessions["admin_alice"], time.time())

            # 2. Deauth
            await handle_admin_command(
                self.node,
                admin_nick="admin_alice",
                verb="admin",
                args=["deauth"],
                reply_target="admin_alice",
            )
            self.assertNotIn("admin_alice", self.node.admin_sessions)
        finally:
            if old_cfg is not None:
                mgr.CONFIG["admin_token"] = old_cfg
            else:
                mgr.CONFIG.pop("admin_token", None)

    async def test_admin_handler_unauthorized_command_rejection(self):
        """Non-admin or unverified user calling admin commands gets Access Denied."""
        from ai_grid.core.handlers.admin import handle_admin_command

        # Unverified admin attempts status
        await handle_admin_command(
            self.node,
            admin_nick="admin_alice",
            verb="status",
            args=[],
            reply_target="#automatagrid",
        )
        sent_msgs = [call.args[0] for call in self.node.send.call_args_list]
        self.assertTrue(any("Access Denied" in m for m in sent_msgs))



class TestPlayerIdentityAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress-testing of registration and player identity spoofing."""

    def setUp(self):
        self.node = MagicMock()
        self.node.prefix = "!a"
        self.node.net_name = "mocknet"
        self.node.config = {"channel": "#automatagrid"}
        self.node.send = AsyncMock()
        self.node.llm = MagicMock()
        self.node.llm.generate_bio = AsyncMock(return_value="Synthetic Bio")
        self.node.db = MagicMock()
        self.node.db.register_player = AsyncMock(return_value="token-12345678")
        self.node.set_dynamic_topic = AsyncMock()

    async def test_registration_spoofing_other_user_strictly_rejected(self):
        """Attacker attempting to register on behalf of Victim is blocked."""
        from ai_grid.core.handlers.personal import handle_registration

        await handle_registration(
            self.node,
            nick="Attacker",
            args=["Victim", "Cyborg", "Hacker", "Stealth"],
            reply_target="#automatagrid",
        )

        # Ensure register_player was NEVER called for the victim
        self.node.db.register_player.assert_not_called()
        # Verify rejection message was sent
        self.assertTrue(self.node.send.called)
        sent = [c.args[0] for c in self.node.send.call_args_list]
        self.assertTrue(any("Registration rejected: Identity 'Victim' does not match" in m for m in sent))

    async def test_registration_illegal_nickname_rejected(self):
        """Registration with illegal nickname is rejected."""
        from ai_grid.core.handlers.personal import handle_registration

        await handle_registration(
            self.node,
            nick="User\r\nInject",
            args=["Cyborg", "Hacker", "Fast"],
            reply_target="#automatagrid",
        )

        self.node.db.register_player.assert_not_called()
        sent = [c.args[0] for c in self.node.send.call_args_list]
        self.assertTrue(any("Registration rejected: Nickname contains illegal characters" in m for m in sent))

    async def test_registration_legitimate_same_nick_succeeds(self):
        """Legitimate user registering their own name succeeds."""
        from ai_grid.core.handlers.personal import handle_registration

        await handle_registration(
            self.node,
            nick="ValidUser",
            args=["ValidUser", "Cyborg", "Hacker", "Stealth"],
            reply_target="#automatagrid",
        )

        self.node.db.register_player.assert_called_once()
        sent = [c.args[0] for c in self.node.send.call_args_list]
        self.assertTrue(any("has entered the Grid!" in m for m in sent))


class TestCombatAdversarial(unittest.TestCase):
    """Stress testing combat engine queueing and intent parsing."""

    def test_combat_queue_command_verbs_and_prefixes(self):
        """Combat engine handles various prefix and command permutations."""
        from ai_grid.grid_combat import CombatEngine, Entity

        engine = CombatEngine("match_adv", "!a", AsyncMock())
        player = Entity("FighterX", {"cpu": 5, "ram": 5, "bnd": 5, "sec": 5, "alg": 5, "power": 100})
        engine.add_entity(player)
        engine.active = True

        test_cases = [
            ("!a strike Enemy", "kinetic", "strike"),
            ("strike Enemy", "kinetic", "strike"),
            ("!a defend", "defend", "defend"),
            ("defend", "defend", "defend"),
            ("!a scan Target", "cyber", "scan"),
            ("scan", "cyber", "scan"),
            ("!a hack Target", "cyber", "hack"),
        ]

        for cmd, expected_intent, expected_verb in test_cases:
            engine.queue_command("FighterX", cmd)
            self.assertIsNotNone(player.command_queued, f"Failed to queue {cmd}")
            self.assertEqual(player.command_queued["intent"], expected_intent, f"Wrong intent for {cmd}")
            self.assertEqual(player.command_queued["raw_verb"], expected_verb, f"Wrong verb for {cmd}")


if __name__ == "__main__":
    unittest.main()
