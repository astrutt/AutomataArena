# tests/e2e/fixtures/test_env.py
"""
Test Environment Setup & Lifecycle Fixture.

Provides isolated SQLite database instances, configuration files, and
domain entity creation helpers for AutomataGrid E2E testing.
"""

import asyncio
import json
import os
import shutil
import tempfile
from typing import Optional

from ai_grid.grid_db import ArenaDB
from ai_grid.models import Player, Character, GridNode, NetworkAlias


class TestEnvironment:
    """Manages an isolated temporary test directory with dedicated SQLite DB and config files."""

    def __init__(self, prefix: str = "ag_e2e_"):
        self.prefix = prefix
        self.temp_dir: str = ""
        self.db_path: str = ""
        self.db: Optional[ArenaDB] = None
        self.config_json_path: str = ""
        self.config_ini_path: str = ""

    async def __aenter__(self):
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.teardown()

    async def setup(self):
        """Creates temp dir, initializes database schema and seed data."""
        self.temp_dir = tempfile.mkdtemp(prefix=self.prefix)
        self.db_path = os.path.join(self.temp_dir, "test_automata_grid.db")
        
        # Instantiate ArenaDB on temp path and init schema
        self.db = ArenaDB(self.db_path)
        await self.db.init_schema()
        return self

    async def teardown(self):
        """Closes DB connection pool and removes temp directory."""
        if self.db:
            try:
                await self.db.close()
            except Exception:
                pass
            self.db = None

        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception:
                pass

    def write_config_ini(
        self,
        irc_server: str = "127.0.0.1",
        irc_port: int = 6667,
        use_ssl: bool = False,
        nickname: str = "TestBot",
        channel: str = "#automatagrid",
        manager_nick: str = "ArenaMaster",
        prefix: str = "x",
        owner: str = "test_owner",
        llm_endpoint: str = "http://127.0.0.1:11434/v1/chat/completions",
        llm_model: str = "mock-model",
        llm_key: str = "",
        target_dir: Optional[str] = None,
    ) -> str:
        """Writes a valid config.ini for ai_player/bot.py."""
        dest_dir = target_dir or self.temp_dir
        path = os.path.join(dest_dir, "config.ini")
        content = f"""[IRC]
Server = {irc_server}
Port = {irc_port}
UseSSL = {str(use_ssl).lower()}
Nickname = {nickname}
Channel = {channel}
ManagerNick = {manager_nick}
Prefix = {prefix}
Owner = {owner}

[LLM]
Endpoint = {llm_endpoint}
Model = {llm_model}
ApiKey = {llm_key}

[LOGGING]
Level = INFO

[BOT]
Race = Wetware
Class = Zero_Day_Rogue
Traits = dangerous
"""
        with open(path, "w") as f:
            f.write(content)
        self.config_ini_path = path
        return path

    def write_config_json(
        self,
        irc_server: str = "127.0.0.1",
        irc_port: int = 6667,
        channel: str = "#automatagrid",
        nickname: str = "ArenaMaster",
        prefix: str = "x",
        llm_endpoint: str = "http://127.0.0.1:11434/v1/chat/completions",
        llm_model: str = "mock-model",
        target_dir: Optional[str] = None,
    ) -> str:
        """Writes a valid config.json for ai_grid/manager.py."""
        dest_dir = target_dir or self.temp_dir
        path = os.path.join(dest_dir, "config.json")
        cfg = {
            "networks": {
                "mocknet": {
                    "server": irc_server,
                    "port": irc_port,
                    "ssl": False,
                    "nickname": nickname,
                    "channel": channel,
                    "cmd_prefix": prefix,
                }
            },
            "database": self.db_path,
            "logging": {"level": "INFO"},
            "llm": {
                "endpoint": llm_endpoint,
                "model": llm_model,
            },
            "admins": ["test_admin"],
            "flood_messages": {
                "rate_limit": "Slow down! Rate limit exceeded.",
                "lockout": "Excess flood detected. Temporarily muted.",
            },
        }
        with open(path, "w") as f:
            json.dump(cfg, f, indent=2)
        self.config_json_path = path
        return path

    async def create_test_player(
        self,
        nickname: str,
        network: str = "mocknet",
        race: str = "Wetware",
        char_class: str = "Zero_Day_Rogue",
        bio: str = "A rogue AI unit.",
        level: int = 1,
        credits: float = 1000.0,
        power: float = 100.0,
        stability: float = 100.0,
    ) -> Character:
        """Helper to register and persist a character in the test DB."""
        auth_token = f"auth_tok_{nickname.lower()}"
        async with self.db.async_session() as session:
            # Create player
            player = Player(global_name=nickname)
            session.add(player)
            await session.flush()

            # Create alias
            alias = NetworkAlias(player_id=player.id, network_name=network, nickname=nickname)
            session.add(alias)

            # Spawn node lookup
            spawn_node = await self.db.get_spawn_node_name()
            from sqlalchemy import select
            loc_node = await session.execute(
                select(GridNode).filter_by(name=spawn_node)
            )
            node_obj = loc_node.scalars().first()
            node_id = node_obj.id if node_obj else None

            # Create character
            char = Character(
                player_id=player.id,
                node_id=node_id,
                name=nickname,
                race=race,
                char_class=char_class,
                bio=bio,
                level=level,
                credits=credits,
                power=power,
                stability=stability,
                auth_token=auth_token,
                status="Active",
                current_hp=(5 + 5 + 5 + 5 + 5) * 6 + 20,
            )
            session.add(char)
            await session.commit()
            await session.refresh(char)
            return char

    async def create_spectator_player(
        self,
        nickname: str,
        network: str = "mocknet",
        level: int = 1,
        credits: float = 250.0,
    ) -> Character:
        """Helper to create a spectator character."""
        return await self.create_test_player(
            nickname=nickname,
            network=network,
            race="Spectator",
            char_class="Civilian",
            bio="Channel Spectator",
            level=level,
            credits=credits,
            power=50.0,
        )
