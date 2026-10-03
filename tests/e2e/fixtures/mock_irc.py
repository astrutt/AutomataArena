# tests/e2e/fixtures/mock_irc.py
"""
Mock IRC Server Fixture for AutomataGrid E2E Testing.

Provides a fully offline, deterministic, RFC 1459/2812 compliant asyncio IRC server.
Supports client connections, nick registration, join/part, private/channel messages,
NickServ emulation, WHOIS numerics (307, 330, 379), keepalive PING/PONG, error code simulation
(433 ERR_NICKNAMEINUSE), abrupt socket drops, deterministic teardown, and message queue assertions.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Callable

logger = logging.getLogger("mock_irc")


class MockIRCClientConnection:
    """Represents an active client socket connection on the Mock IRC server."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.nick: str = ""
        self.user: str = ""
        self.realname: str = ""
        self.channels: Set[str] = set()
        self.registered: bool = False       # RFC 1459/2812 handshake complete
        self.identified: bool = False       # NickServ identified (+r)
        self.modes: Set[str] = set()        # Client modes e.g. {'r'}
        self.task: Optional[asyncio.Task] = None
        self._closed: bool = False

    async def send_raw(self, line: str):
        """Send a raw IRC line terminated with CRLF."""
        if not self._closed and not self.writer.is_closing():
            try:
                data = f"{line}\r\n".encode("utf-8")
                self.writer.write(data)
                await self.writer.drain()
            except Exception as e:
                logger.debug(f"[MockIRC] Error sending to {self.nick}: {e}")

    async def close(self):
        """Close client connection safely and immediately."""
        if self._closed:
            return
        self._closed = True

        if self.task and not self.task.done() and self.task != asyncio.current_task():
            self.task.cancel()

        try:
            if not self.writer.is_closing():
                self.writer.close()
            # Transport abort ensures immediate socket closure at OS level
            transport = self.writer.transport
            if transport and not transport.is_closing():
                transport.abort()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), timeout=0.5)
            except (asyncio.TimeoutError, Exception):
                pass
        except Exception:
            pass


class MockIRCServer:
    """
    Async Mock IRC Server for offline testing.
    Runs on localhost with an automatically assigned or specified port.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.requested_port = port
        self.port: int = 0
        self.server: Optional[asyncio.Server] = None
        self.clients: Dict[str, MockIRCClientConnection] = {}  # nick.lower() -> client
        self.connections: List[MockIRCClientConnection] = []
        self.channels: Dict[str, Set[str]] = {}  # channel.lower() -> set of nick.lower()

        # NickServ and identity tracking
        self.identified_nicks: Set[str] = set()
        self.registered_nicks: Dict[str, dict] = {}
        self.whois_numerics: Set[str] = {"307", "330", "379"}
        self.nickserv_host: str = "NickServ!services@services.host"

        # Task tracking for rock-solid teardown
        self._client_tasks: Set[asyncio.Task] = set()

        # Message inspection logs
        self.received_messages: List[dict] = []  # dict with 'from', 'target', 'text', 'raw', 'command'
        self.raw_lines: List[str] = []
        self._message_event: asyncio.Event = asyncio.Event()

        # Control flags
        self.reject_nick_in_use: Optional[str] = None  # Nickname to reject with 433
        self.server_name = "mock.irc.2600.net"

    def mark_identified(self, nick: str):
        """Manually mark a nickname as NickServ-identified (+r)."""
        nick_key = nick.lower()
        self.identified_nicks.add(nick_key)
        client = self.clients.get(nick_key)
        if client:
            client.identified = True
            client.modes.add("r")

    def mark_unidentified(self, nick: str):
        """Manually unmark a nickname as NickServ-identified."""
        nick_key = nick.lower()
        self.identified_nicks.discard(nick_key)
        client = self.clients.get(nick_key)
        if client:
            client.identified = False
            client.modes.discard("r")

    def is_identified(self, nick: str) -> bool:
        """Check if a nickname is identified (+r)."""
        return nick.lower() in self.identified_nicks

    async def start(self):
        """Start the mock IRC server."""
        self.server = await asyncio.start_server(
            self._handle_client, self.host, self.requested_port
        )
        # Determine actual assigned port
        sockets = self.server.sockets
        if sockets:
            self.port = sockets[0].getsockname()[1]
        logger.info(f"[MockIRC] Server started on {self.host}:{self.port}")
        return self

    async def stop(self):
        """Stop the mock IRC server and disconnect all clients cleanly."""
        # 1. Close server listening socket
        if self.server:
            self.server.close()
            try:
                await asyncio.wait_for(self.server.wait_closed(), timeout=1.0)
            except (asyncio.TimeoutError, Exception):
                pass
            self.server = None

        # 2. Close and abort all client connections
        close_coros = [conn.close() for conn in list(self.connections)]
        if close_coros:
            await asyncio.gather(*close_coros, return_exceptions=True)

        # 3. Cancel all pending client handler tasks
        current = asyncio.current_task()
        pending_tasks = [t for t in self._client_tasks if not t.done() and t != current]
        for t in pending_tasks:
            t.cancel()

        if pending_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending_tasks, return_exceptions=True),
                    timeout=1.0,
                )
            except (asyncio.TimeoutError, Exception):
                pass

        self._client_tasks.clear()
        self.connections.clear()
        self.clients.clear()
        self.channels.clear()
        logger.info("[MockIRC] Server stopped cleanly.")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        conn = MockIRCClientConnection(reader, writer)
        task = asyncio.current_task()
        if task:
            conn.task = task
            self._client_tasks.add(task)
        self.connections.append(conn)

        try:
            while True:
                line_bytes = await reader.readline()
                if not line_bytes:
                    break  # Client disconnected
                line = line_bytes.decode("utf-8", errors="ignore").rstrip("\r\n")
                if not line:
                    continue

                self.raw_lines.append(line)
                await self._process_command(conn, line)
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            if task:
                self._client_tasks.discard(task)
            await self._cleanup_client(conn)

    async def _cleanup_client(self, conn: MockIRCClientConnection):
        if conn in self.connections:
            self.connections.remove(conn)
        if conn.nick and conn.nick.lower() in self.clients:
            del self.clients[conn.nick.lower()]
        for ch, members in list(self.channels.items()):
            if conn.nick and conn.nick.lower() in members:
                members.remove(conn.nick.lower())
        await conn.close()

    async def _handle_nickserv_command(self, conn: MockIRCClientConnection, cmd: str, text: str):
        """Handle NickServ commands (IDENTIFY, REGISTER, CONFIRM)."""
        tokens = text.strip().split()
        if not tokens:
            return

        ns_verb = tokens[0].upper()
        ns_args = tokens[1:]

        if ns_verb == "IDENTIFY":
            # PRIVMSG NickServ :IDENTIFY <pass>
            password = ns_args[0] if ns_args else ""
            conn.identified = True
            conn.modes.add("r")
            if conn.nick:
                self.identified_nicks.add(conn.nick.lower())
            notice = f":{self.nickserv_host} NOTICE {conn.nick} :Password accepted - you are now recognized."
            await conn.send_raw(notice)

        elif ns_verb == "REGISTER":
            # PRIVMSG NickServ :REGISTER <pass> <email>
            password = ns_args[0] if len(ns_args) > 0 else ""
            email = ns_args[1] if len(ns_args) > 1 else ""
            conn.identified = True
            conn.modes.add("r")
            if conn.nick:
                self.identified_nicks.add(conn.nick.lower())
                self.registered_nicks[conn.nick.lower()] = {
                    "password": password,
                    "email": email,
                }
            notice = f":{self.nickserv_host} NOTICE {conn.nick} :Nickname {conn.nick} registered."
            await conn.send_raw(notice)

        elif ns_verb == "CONFIRM":
            # PRIVMSG NickServ :CONFIRM <code>
            code = ns_args[0] if ns_args else ""
            conn.identified = True
            conn.modes.add("r")
            if conn.nick:
                self.identified_nicks.add(conn.nick.lower())
            notice = f":{self.nickserv_host} NOTICE {conn.nick} :Nickname {conn.nick} confirmed."
            await conn.send_raw(notice)

        else:
            notice = f":{self.nickserv_host} NOTICE {conn.nick} :Unknown NickServ command: {ns_verb}"
            await conn.send_raw(notice)

    async def _process_command(self, conn: MockIRCClientConnection, line: str):
        # Parse IRC command line
        prefix = ""
        rest = line
        if rest.startswith(":"):
            idx = rest.find(" ")
            if idx != -1:
                prefix = rest[1:idx]
                rest = rest[idx + 1:].lstrip()

        # Split command and parameters
        trailing = None
        if " :" in rest:
            params_str, trailing = rest.split(" :", 1)
            parts = params_str.split()
        else:
            parts = rest.split()

        if not parts:
            return

        cmd = parts[0].upper()
        args = parts[1:]
        if trailing is not None:
            args.append(trailing)

        # Record incoming message
        source_nick = conn.nick or "UNREGISTERED"
        target = args[0] if len(args) > 0 else ""
        text = args[-1] if len(args) > 1 else (args[0] if len(args) == 1 else "")
        msg_entry = {
            "from": source_nick,
            "command": cmd,
            "target": target,
            "text": text,
            "args": args,
            "raw": line,
        }
        self.received_messages.append(msg_entry)
        self._message_event.set()

        # Command Dispatch
        if cmd == "NICK":
            new_nick = args[0] if args else ""
            if self.reject_nick_in_use and new_nick.lower() == self.reject_nick_in_use.lower():
                await conn.send_raw(f":{self.server_name} 433 * {new_nick} :Nickname is already in use")
                return

            old_nick = conn.nick
            conn.nick = new_nick
            if old_nick and old_nick.lower() in self.clients:
                del self.clients[old_nick.lower()]
            self.clients[new_nick.lower()] = conn

            # Synchronize identification state if nickname was pre-identified
            if new_nick.lower() in self.identified_nicks:
                conn.identified = True
                conn.modes.add("r")

            if old_nick and old_nick != new_nick:
                await conn.send_raw(f":{old_nick}!{conn.user}@localhost NICK :{new_nick}")

            await self._check_registration(conn)

        elif cmd == "USER":
            if args:
                conn.user = args[0]
            if len(args) > 3:
                conn.realname = args[3]
            await self._check_registration(conn)

        elif cmd == "PING":
            token = args[0] if args else "ping"
            await conn.send_raw(f":{self.server_name} PONG {self.server_name} :{token}")

        elif cmd == "PONG":
            pass

        elif cmd == "JOIN":
            if not args:
                return
            chan = args[0]
            chan_key = chan.lower()
            if chan_key not in self.channels:
                self.channels[chan_key] = set()
            self.channels[chan_key].add(conn.nick.lower())
            conn.channels.add(chan_key)

            # Broadcast JOIN to all members in channel
            join_msg = f":{conn.nick}!{conn.user}@127.0.0.1 JOIN :{chan}"
            await self._broadcast_to_channel(chan_key, join_msg, include_sender=True)

            # RPL_NAMREPLY (353) and RPL_ENDOFNAMES (366)
            nicks = " ".join(self.channels[chan_key])
            await conn.send_raw(f":{self.server_name} 353 {conn.nick} = {chan} :{nicks}")
            await conn.send_raw(f":{self.server_name} 366 {conn.nick} {chan} :End of /NAMES list.")

        elif cmd == "PART":
            if not args:
                return
            chan = args[0]
            chan_key = chan.lower()
            if chan_key in self.channels and conn.nick.lower() in self.channels[chan_key]:
                self.channels[chan_key].remove(conn.nick.lower())
            conn.channels.discard(chan_key)
            part_msg = f":{conn.nick}!{conn.user}@127.0.0.1 PART :{chan}"
            await self._broadcast_to_channel(chan_key, part_msg, include_sender=True)

        elif cmd in ["PRIVMSG", "NOTICE"]:
            if len(args) < 2:
                return
            tgt = args[0]
            msg_content = args[1]
            out_line = f":{conn.nick}!{conn.user}@127.0.0.1 {cmd} {tgt} :{msg_content}"

            # Intercept NickServ commands
            if tgt.lower() == "nickserv":
                await self._handle_nickserv_command(conn, cmd, msg_content)
                return

            if tgt.startswith("#"):
                # Channel broadcast
                chan_key = tgt.lower()
                await self._broadcast_to_channel(chan_key, out_line, include_sender=False, sender_nick=conn.nick)
            else:
                # Direct message to user
                tgt_key = tgt.lower()
                if tgt_key in self.clients:
                    await self.clients[tgt_key].send_raw(out_line)

        elif cmd == "WHOIS":
            target_nick = args[0] if args else ""
            tgt_key = target_nick.lower()
            if tgt_key in self.clients:
                target_client = self.clients[tgt_key]
                await conn.send_raw(f":{self.server_name} 311 {conn.nick} {target_client.nick} {target_client.user} 127.0.0.1 * :{target_client.realname or 'User'}")

                # Check NickServ identification
                is_ident = target_client.identified or (tgt_key in self.identified_nicks) or ("r" in target_client.modes)
                if is_ident:
                    if "307" in self.whois_numerics:
                        await conn.send_raw(f":{self.server_name} 307 {conn.nick} {target_client.nick} :is a registered nick")
                    if "330" in self.whois_numerics:
                        account_name = target_client.nick
                        await conn.send_raw(f":{self.server_name} 330 {conn.nick} {target_client.nick} {account_name} :is logged in as")
                    if "379" in self.whois_numerics:
                        await conn.send_raw(f":{self.server_name} 379 {conn.nick} {target_client.nick} :is using modes +r")

                await conn.send_raw(f":{self.server_name} 318 {conn.nick} {target_client.nick} :End of /WHOIS list.")
            else:
                await conn.send_raw(f":{self.server_name} 401 {conn.nick} {target_nick} :No such nick/channel")

        elif cmd == "QUIT":
            await conn.close()

    async def _check_registration(self, conn: MockIRCClientConnection):
        if conn.nick and conn.user and not conn.registered:
            conn.registered = True
            nick = conn.nick
            await conn.send_raw(f":{self.server_name} 001 {nick} :Welcome to the Mock IRC Network {nick}!{conn.user}@127.0.0.1")
            await conn.send_raw(f":{self.server_name} 002 {nick} :Your host is {self.server_name}, running v1.0")
            await conn.send_raw(f":{self.server_name} 003 {nick} :This server was created today")
            await conn.send_raw(f":{self.server_name} 004 {nick} {self.server_name} 1.0 o o")
            await conn.send_raw(f":{self.server_name} 375 {nick} :- {self.server_name} Message of the Day -")
            await conn.send_raw(f":{self.server_name} 372 {nick} :- Welcome to AutomataGrid Mock IRC!")
            await conn.send_raw(f":{self.server_name} 376 {nick} :End of /MOTD command.")

    async def _broadcast_to_channel(self, chan_key: str, line: str, include_sender: bool = False, sender_nick: str = ""):
        if chan_key not in self.channels:
            return
        for member_nick in self.channels[chan_key]:
            if not include_sender and member_nick == sender_nick.lower():
                continue
            client = self.clients.get(member_nick)
            if client:
                await client.send_raw(line)

    async def broadcast(self, line: str):
        """Send raw line to all connected clients."""
        for conn in list(self.connections):
            await conn.send_raw(line)

    async def send_to(self, nick: str, line: str) -> bool:
        """Send raw line to a specific nickname."""
        client = self.clients.get(nick.lower())
        if client:
            await client.send_raw(line)
            return True
        return False

    async def send_privmsg(self, from_nick: str, to_target: str, text: str):
        """Convenience method to inject a PRIVMSG into the network."""
        line = f":{from_nick}!bot@127.0.0.1 PRIVMSG {to_target} :{text}"
        if to_target.startswith("#"):
            await self._broadcast_to_channel(to_target.lower(), line, include_sender=True)
        else:
            await self.send_to(to_target, line)

    async def send_notice(self, from_nick: str, to_target: str, text: str):
        """Convenience method to inject a NOTICE into the network."""
        line = f":{from_nick}!bot@127.0.0.1 NOTICE {to_target} :{text}"
        if to_target.startswith("#"):
            await self._broadcast_to_channel(to_target.lower(), line, include_sender=True)
        else:
            await self.send_to(to_target, line)

    async def simulate_socket_drop(self, nick: Optional[str] = None):
        """Abruptly terminate connection for specified nick or all clients."""
        if nick:
            client = self.clients.get(nick.lower())
            if not client:
                for _ in range(50):
                    await asyncio.sleep(0.02)
                    client = self.clients.get(nick.lower())
                    if client:
                        break
            if client:
                await client.close()
        else:
            for conn in list(self.connections):
                await conn.close()

    async def wait_for_message(
        self,
        command: Optional[str] = None,
        target: Optional[str] = None,
        from_nick: Optional[str] = None,
        contains: Optional[str] = None,
        timeout: float = 5.0,
    ) -> Optional[dict]:
        """
        Wait until a message matching all given criteria is received.
        Returns matching message dict or None if timeout expires.
        """
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            for msg in reversed(self.received_messages):
                match = True
                if command and msg["command"] != command.upper():
                    match = False
                if target and msg["target"].lower() != target.lower():
                    match = False
                if from_nick and msg["from"].lower() != from_nick.lower():
                    match = False
                if contains and contains not in msg["text"]:
                    match = False
                if match:
                    return msg

            self._message_event.clear()
            try:
                remaining = timeout - (asyncio.get_event_loop().time() - start_time)
                if remaining > 0:
                    await asyncio.wait_for(self._message_event.wait(), timeout=min(0.2, remaining))
            except asyncio.TimeoutError:
                pass
        return None
