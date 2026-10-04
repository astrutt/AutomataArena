"""
tests/stress_test_m1_challenger.py — Adversarial Stress Test Suite for Milestone 1.

Written by Challenger 1 to empirically verify:
1. MockIRCServer concurrency, socket drops, NickServ state transitions, WHOIS numerics, task leaks.
2. SandboxHarness burst command injection, unthrottled message handling, DB query consistency.
3. sandbox.py headless execution, meta-commands, error resilience, and clean shutdown.
"""

import asyncio
import os
import signal
import subprocess
import sys
import time
import unittest
from typing import List

from tests.e2e.fixtures.mock_irc import MockIRCServer
from tests.sandbox_harness import SandboxHarness


class TestMockIRCServerAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress testing against MockIRCServer."""

    async def asyncSetUp(self):
        self.server = MockIRCServer(host="127.0.0.1", port=0)
        await self.server.start()

    async def asyncTearDown(self):
        if self.server:
            await self.server.stop()

    async def test_01_high_concurrency_connections_and_join(self):
        """Stress-test: 50 concurrent clients connecting, registering, and joining channels."""
        num_clients = 50
        writers: List[asyncio.StreamWriter] = []
        readers: List[asyncio.StreamReader] = []

        async def connect_client(idx: int):
            r, w = await asyncio.open_connection("127.0.0.1", self.server.port)
            readers.append(r)
            writers.append(w)
            nick = f"StressUser{idx:02d}"
            w.write(f"NICK {nick}\r\nUSER {nick} 0 * :{nick}\r\nJOIN #stresstest\r\n".encode())
            await w.drain()

        # Connect all 50 clients simultaneously
        tasks = [asyncio.create_task(connect_client(i)) for i in range(num_clients)]
        await asyncio.gather(*tasks)

        # Wait for all clients to be registered in server.clients
        for _ in range(100):
            if len(self.server.clients) >= num_clients:
                break
            await asyncio.sleep(0.05)

        self.assertEqual(len(self.server.clients), num_clients)
        self.assertIn("#stresstest", self.server.channels)
        self.assertEqual(len(self.server.channels["#stresstest"]), num_clients)
        self.assertEqual(len(self.server._client_tasks), num_clients)

        # Clean up
        for w in writers:
            w.close()
        await asyncio.sleep(0.1)

    async def test_02_abrupt_disconnect_storm_and_recovery(self):
        """Stress-test: 30 clients connect; 15 abruptly abort transport; remaining 15 broadcast."""
        num_clients = 30
        clients = []

        for i in range(num_clients):
            r, w = await asyncio.open_connection("127.0.0.1", self.server.port)
            nick = f"StormUser{i:02d}"
            w.write(f"NICK {nick}\r\nUSER {nick} 0 * :{nick}\r\nJOIN #storm\r\n".encode())
            await w.drain()
            clients.append((nick, r, w))

        # Await registration
        for _ in range(100):
            if len(self.server.clients) >= num_clients:
                break
            await asyncio.sleep(0.05)

        self.assertEqual(len(self.server.clients), num_clients)

        # Abruptly abort sockets for the first 15 clients (simulate network drops / crashes)
        dropped_nicks = set()
        for i in range(15):
            nick, r, w = clients[i]
            dropped_nicks.add(nick.lower())
            w.transport.abort()

        # Allow server to detect disconnects and run _cleanup_client
        for _ in range(100):
            if len(self.server.clients) <= 15:
                break
            await asyncio.sleep(0.05)

        self.assertEqual(len(self.server.clients), 15)
        for dropped in dropped_nicks:
            self.assertNotIn(dropped, self.server.clients)
            self.assertNotIn(dropped, self.server.channels.get("#storm", set()))

        # Remaining 15 clients send messages simultaneously
        remaining_clients = clients[15:]
        for nick, r, w in remaining_clients:
            w.write(f"PRIVMSG #storm :Survivors {nick}\r\n".encode())
            await w.drain()

        # Wait for messages to be registered in server.received_messages
        for _ in range(100):
            survivor_msgs = [m for m in self.server.received_messages if "Survivors" in m["text"]]
            if len(survivor_msgs) >= 15:
                break
            await asyncio.sleep(0.05)

        survivor_msgs = [m for m in self.server.received_messages if "Survivors" in m["text"]]
        self.assertEqual(len(survivor_msgs), 15)

        # Cleanup remaining
        for _, _, w in remaining_clients:
            w.close()

    async def test_03_nickserv_transitions_and_whois_numerics_deep(self):
        """Stress-test: Validate NickServ IDENTIFY, REGISTER, CONFIRM, and WHOIS numerics 307, 330, 379."""
        r, w = await asyncio.open_connection("127.0.0.1", self.server.port)
        nick = "Alice"
        w.write(f"NICK {nick}\r\nUSER {nick} 0 * :Alice In Chains\r\n".encode())
        await w.drain()

        # Wait for welcome MOTD
        while True:
            line = (await r.readline()).decode()
            if "376" in line or not line:
                break

        # 1. Check WHOIS prior to identification
        w.write(b"WHOIS Alice\r\n")
        await w.drain()

        whois_lines_unident = []
        while True:
            line = (await r.readline()).decode()
            whois_lines_unident.append(line)
            if " 318 " in line or not line:
                break

        # Unidentified: Should NOT contain 307, 330, or 379
        self.assertTrue(any(" 311 " in l for l in whois_lines_unident))
        self.assertTrue(any(" 318 " in l for l in whois_lines_unident))
        self.assertFalse(any(" 307 " in l for l in whois_lines_unident))
        self.assertFalse(any(" 330 " in l for l in whois_lines_unident))
        self.assertFalse(any(" 379 " in l for l in whois_lines_unident))

        # 2. Test NickServ IDENTIFY
        w.write(b"PRIVMSG NickServ :IDENTIFY SuperSecret123\r\n")
        await w.drain()

        notice_line = (await r.readline()).decode()
        self.assertIn("Password accepted", notice_line)
        self.assertIn("NOTICE Alice", notice_line)
        self.assertTrue(self.server.is_identified("Alice"))
        conn = self.server.clients["alice"]
        self.assertTrue(conn.identified)
        self.assertIn("r", conn.modes)

        # 3. Check WHOIS after IDENTIFY: must include 307, 330, 379 in correct order
        w.write(b"WHOIS Alice\r\n")
        await w.drain()

        whois_lines_ident = []
        while True:
            line = (await r.readline()).decode()
            whois_lines_ident.append(line)
            if " 318 " in line or not line:
                break

        # Verify numeric codes present
        codes = [l.split()[1] for l in whois_lines_ident if len(l.split()) > 1]
        self.assertIn("311", codes)
        self.assertIn("307", codes)
        self.assertIn("330", codes)
        self.assertIn("379", codes)
        self.assertIn("318", codes)

        # Verify exact text format
        line_307 = next(l for l in whois_lines_ident if " 307 " in l)
        self.assertIn(":is a registered nick", line_307)
        line_330 = next(l for l in whois_lines_ident if " 330 " in l)
        self.assertIn(":is logged in as", line_330)
        line_379 = next(l for l in whois_lines_ident if " 379 " in l)
        self.assertIn(":is using modes +r", line_379)

        # 4. Test NickServ REGISTER with another client
        r2, w2 = await asyncio.open_connection("127.0.0.1", self.server.port)
        w2.write(b"NICK Bob\r\nUSER Bob 0 * :Bob\r\n")
        await w2.drain()
        while True:
            l = (await r2.readline()).decode()
            if "376" in l or not l:
                break

        w2.write(b"PRIVMSG nickserv :REGISTER BobPass bob@example.com\r\n")
        await w2.drain()
        ns_reg_notice = (await r2.readline()).decode()
        self.assertIn("Nickname Bob registered", ns_reg_notice)
        self.assertTrue(self.server.is_identified("Bob"))
        self.assertIn("bob", self.server.registered_nicks)
        self.assertEqual(self.server.registered_nicks["bob"]["email"], "bob@example.com")

        # 5. Test NickServ CONFIRM
        w2.write(b"PRIVMSG NickServ :CONFIRM 98765\r\n")
        await w2.drain()
        ns_conf_notice = (await r2.readline()).decode()
        self.assertIn("Nickname Bob confirmed", ns_conf_notice)

        # 6. Test WHOIS on non-existent nick -> 401 ERR_NOSUCHNICK
        w.write(b"WHOIS NobodySpecial\r\n")
        await w.drain()
        err_line = (await r.readline()).decode()
        self.assertIn(" 401 ", err_line)
        self.assertIn("No such nick/channel", err_line)

        w.close()
        w2.close()

    async def test_04_zero_task_leaks_on_abrupt_server_stop(self):
        """Stress-test: Verify clean task cancellation and zero leaked tasks upon server.stop()."""
        writers = []
        for i in range(20):
            _, w = await asyncio.open_connection("127.0.0.1", self.server.port)
            w.write(f"NICK LeakUser{i}\r\nUSER LeakUser{i} 0 * :User\r\n".encode())
            await w.drain()
            writers.append(w)

        # Wait for connections
        for _ in range(50):
            if len(self.server._client_tasks) >= 20:
                break
            await asyncio.sleep(0.05)

        self.assertEqual(len(self.server._client_tasks), 20)

        # Stop server abruptly
        await self.server.stop()

        # All client tasks in _client_tasks must be cancelled and cleared
        self.assertEqual(len(self.server._client_tasks), 0)
        self.assertEqual(len(self.server.clients), 0)
        self.assertEqual(len(self.server.connections), 0)
        self.assertIsNone(self.server.server)

        # Verify stop() is idempotent
        await self.server.stop()
        self.assertEqual(len(self.server._client_tasks), 0)

        for w in writers:
            w.close()


class TestSandboxHarnessAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress testing against SandboxHarness."""

    async def test_01_rapid_command_burst_and_stale_reply_filtering(self):
        """Stress-test: Inject rapid sequential commands without waiting, then verify responses."""
        async with SandboxHarness() as harness:
            # 1. Burst commands
            commands = ["status", "help", "inventory", "explore", "status"]
            replies = []
            for cmd in commands:
                reply = await harness.send_command(cmd, timeout=5.0)
                self.assertIsNotNone(reply, f"Expected reply for '{cmd}'")
                replies.append(reply)

            self.assertEqual(len(replies), 5)

            # 2. Test rapid concurrent injection
            coros = [
                harness.send_command("help", wait_reply=False),
                harness.send_command("status", wait_reply=False),
                harness.send_command("inventory", wait_reply=False),
            ]
            await asyncio.gather(*coros)

            # Wait for replies to accumulate
            await asyncio.sleep(0.5)
            self.assertGreaterEqual(len(harness.irc_server.received_messages), 8)

    async def test_02_db_query_consistency_and_state_updates(self):
        """Stress-test: Verify DB state persistence under repeated queries and commands."""
        async with SandboxHarness() as harness:
            char1 = await harness.get_player_character("TestPlayer")
            self.assertIsNotNone(char1)
            initial_credits = char1.credits

            node = await harness.get_grid_node("UpLink")
            self.assertIsNotNone(node)
            self.assertEqual(node.name, "UpLink")

            # Execute explore command
            reply = await harness.send_command("explore", timeout=5.0)
            self.assertIsNotNone(reply)

            # Re-query character
            char2 = await harness.get_player_character("TestPlayer")
            self.assertIsNotNone(char2)
            self.assertEqual(char2.name, "TestPlayer")
            self.assertEqual(char2.credits, initial_credits)

    async def test_03_harness_clean_teardown_and_reboot(self):
        """Stress-test: Lifecycle restart test to prove zero port or task leaks."""
        for cycle in range(2):
            harness = SandboxHarness()
            await harness.start()
            port = harness.irc_server.port
            self.assertGreater(port, 0)

            reply = await harness.send_command("help", timeout=5.0)
            self.assertIsNotNone(reply)

            await harness.stop()
            # Double stop should be safe
            await harness.stop()


class TestSandboxCLIAdversarial(unittest.TestCase):
    """Adversarial stress testing against sandbox.py CLI."""

    def test_01_sandbox_headless_meta_command_burst(self):
        """Stress-test: Headless execution with complete sequence of meta-commands."""
        python_bin = "AutomataArena/venv/bin/python"
        cmd = [
            python_bin,
            "sandbox.py",
            "--no-repl",
            "--irc-port", "0",
            "--llm-port", "0",
            "--exec", "/role admin;/player;/nodes;/db SELECT count(*) FROM grid_nodes;/spawn BotA;/bots;/kill BotA;/flood 3;/player;help;quit",
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, f"sandbox.py failed with stderr: {res.stderr}")

        stdout = res.stdout
        self.assertIn("Character Telemetry: Operator", stdout)
        self.assertIn("Grid Nodes (Total: 2516", stdout)
        self.assertIn("(2516,)", stdout)
        self.assertIn("Spawning bot: BotA", stdout)
        self.assertIn("Bot BotA terminated", stdout)
        self.assertIn("Injecting 3 rapid messages", stdout)
        self.assertIn("Tearing down sandbox resources...", stdout)
        self.assertIn("Sandbox shutdown complete.", stdout)

    def test_02_sandbox_error_resilience_in_exec(self):
        """Stress-test: Send invalid and malformed meta-commands to verify fault tolerance."""
        python_bin = "AutomataArena/venv/bin/python"
        cmd = [
            python_bin,
            "sandbox.py",
            "--no-repl",
            "--irc-port", "0",
            "--llm-port", "0",
            "--exec", "/role invalid_role;/kill NonExistentBot;/db SELECT * FROM invalid_table;/unknown_cmd;quit",
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, f"sandbox.py crashed on invalid commands: {res.stderr}")

        stdout = res.stdout
        self.assertIn("Usage: /role <player|admin|spectator>", stdout)
        self.assertIn("Bot NonExistentBot not found", stdout)
        self.assertIn("SQL Error:", stdout)
        self.assertIn("no such table: invalid_table", stdout)
        self.assertIn("Unknown meta-command: /unknown_cmd", stdout)
        self.assertIn("Sandbox shutdown complete.", stdout)

    def test_03_sandbox_sigint_clean_shutdown(self):
        """Stress-test: Start sandbox in subprocess without --no-repl, send SIGINT, verify clean shutdown."""
        python_bin = "AutomataArena/venv/bin/python"
        proc = subprocess.Popen(
            [python_bin, "sandbox.py", "--irc-port", "0", "--llm-port", "0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
        )

        # Give it a moment to boot
        time.sleep(3.0)

        # Send SIGINT (Ctrl+C)
        proc.send_signal(signal.SIGINT)

        try:
            stdout, stderr = proc.communicate(timeout=8.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            self.fail("sandbox.py hung on SIGINT and failed to exit within 8s")

        self.assertIn("Received interrupt signal", stdout)
        self.assertIn("Tearing down sandbox resources...", stdout)
        self.assertIn("Sandbox shutdown complete.", stdout)


if __name__ == "__main__":
    unittest.main()
