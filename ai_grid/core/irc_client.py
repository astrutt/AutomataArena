# irc_client.py - v1.5.0
import asyncio
import ssl
import logging

logger = logging.getLogger("manager")

class IRCClient:
    def __init__(self, net_name, config):
        self.net_name = net_name
        self.config = config
        self.reader = None
        self.writer = None
        self.nickname = config['nickname']
        self.channel = config['channel']

    async def connect(self):
        logger.info(f"Connecting to {self.net_name} ({self.config['server']}:{self.config['port']})...")
        ssl_ctx = ssl.create_default_context() if self.config['ssl'] else None
        self.reader, self.writer = await asyncio.open_connection(
            self.config['server'], self.config['port'], ssl=ssl_ctx
        )
        
        await self.send(f"NICK {self.nickname}")
        await self.send(f"USER {self.nickname} 0 * :AutomataArena Master Node")
        # JOIN is usually handled after receiving the 001 welcome message in the listen loop
        # But we can put it here if we want to be simple, though it might fail if we aren't registered yet.

    async def send(self, message: str):
        if self.writer:
            logger.debug(f"[{self.net_name}] > {message}")
            self.writer.write(f"{message}\r\n".encode('utf-8'))
            await self.writer.drain()
            await asyncio.sleep(0.3)

    async def privmsg(self, target: str, message: str):
        await self.send(f"PRIVMSG {target} :{message}")

    async def notice(self, target: str, message: str):
        await self.send(f"NOTICE {target} :{message}")

    async def join(self, channel: str):
        await self.send(f"JOIN {channel}")

    async def part(self, channel: str):
        await self.send(f"PART {channel}")

    def is_connected(self):
        return self.reader is not None and self.writer is not None

    async def readline(self):
        if not self.reader:
            return None
        try:
            line = await self.reader.readline()
            if not line:
                return None
            return line.decode('utf-8', errors='ignore').strip()
        except Exception as e:
            logger.error(f"Error reading from {self.net_name}: {e}")
            return None

    async def close(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self.reader = None
        self.writer = None
