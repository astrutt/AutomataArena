import asyncio
import argparse
import logging
import os
import shutil
import json
import datetime
from sqlalchemy import inspect, text, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select

from models import (
    Base, Player, NetworkAlias, Character, GridNode, NodeConnection, 
    PulseEvent, DiscoveryRecord, BreachRecord, ItemTemplate, InventoryItem, 
    MainframeTask, AuctionListing, Leaderboard, CipherSession, GlobalMarket, Memo
)
from database.core import DB_FILE, logger, CONFIG, GRID_EXPANSION, GRID_CONNECTIONS, BRIDGE_MAPPING, LOOT_TEMPLATES
from database.repositories.navigation_repo import NavigationRepository
from database.repositories.territory_repo import TerritoryRepository
from database.repositories.discovery_repo import DiscoveryRepository
from database.repositories.infiltration_repo import InfiltrationRepository
from database.repositories.maintenance_repo import MaintenanceRepository
from database.repositories.player_repo import PlayerRepository
from database.repositories.economy_repo import EconomyRepository
from database.repositories.mainframe_repo import MainframeRepository
from database.repositories.minigame_repo import MiniGameRepository
from database.repositories.combat_repo import CombatRepository
from database.repositories.pulse_repo import PulseRepository

class ArenaDB:
    def __init__(self, db_path=DB_FILE):
        self.db_path = f"sqlite+aiosqlite:///{db_path}"
        self.engine = create_async_engine(self.db_path, echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        
        # Repositories (Domain Partitions)
        self.player = PlayerRepository(self.async_session)
        self.economy = EconomyRepository(self.async_session)
        self.combat = CombatRepository(self.async_session)
        self.mainframe = MainframeRepository(self.async_session)
        self.minigame = MiniGameRepository(self.async_session)
        
        # Grid domains
        self.navigation = NavigationRepository(self.async_session)
        self.territory = TerritoryRepository(self.async_session)
        self.discovery = DiscoveryRepository(self.async_session)
        self.infiltration = InfiltrationRepository(self.async_session)
        self.maintenance = MaintenanceRepository(self.async_session)
        self.pulse = PulseRepository(self.async_session)

        # Legacy Facade Compatibility (grid object proxy)
        class GridFacade:
            def __init__(self, db):
                self.db = db
            async def get_spawn_node_name(self, *a, **k): return await self.db.navigation.get_spawn_node_name(*a, **k)
            async def set_spawn_node(self, *a, **k): return await self.db.navigation.set_spawn_node(*a, **k)
            async def get_claimed_nodes(self, *a, **k): return await self.db.navigation.get_claimed_nodes(*a, **k)
            async def get_location(self, *a, **k): return await self.db.navigation.get_location(*a, **k)
            async def move_player(self, *a, **k): return await self.db.navigation.move_player(*a, **k)
            async def move_player_to_node(self, *a, **k): return await self.db.navigation.move_player_to_node(*a, **k)
            async def claim_node(self, *a, **k): return await self.db.territory.claim_node(*a, **k)
            async def upgrade_node(self, *a, **k): return await self.db.territory.upgrade_node(*a, **k)
            async def set_grid_mode(self, *a, **k): return await self.db.territory.set_grid_mode(*a, **k)
            async def grid_repair(self, *a, **k): return await self.db.territory.grid_repair(*a, **k)
            async def grid_recharge(self, *a, **k): return await self.db.territory.grid_recharge(*a, **k)
            async def install_node_addon(self, *a, **k): return await self.db.territory.install_node_addon(*a, **k)
            async def bolster_node(self, *a, **k): return await self.db.territory.bolster_node(*a, **k)
            async def link_network(self, *a, **k): return await self.db.territory.link_network(*a, **k)
            async def rename_node(self, *a, **k): return await self.db.territory.rename_node(*a, **k)
            async def update_node_description(self, *a, **k): return await self.db.territory.update_node_description(*a, **k)
            async def explore_node(self, *a, **k): return await self.db.discovery.explore_node(*a, **k)
            async def probe_node(self, *a, **k): return await self.db.discovery.probe_node(*a, **k)
            async def hack_node(self, *a, **k): return await self.db.infiltration.hack_node(*a, **k)
            async def siphon_node(self, *a, **k): return await self.db.infiltration.siphon_node(*a, **k)
            async def raid_node(self, *a, **k): return await self.db.infiltration.raid_node(*a, **k)
            async def tick_grid_power(self, *a, **k): return await self.db.maintenance.tick_grid_power(*a, **k)
            async def get_grid_telemetry(self, *a, **k): return await self.db.maintenance.get_grid_telemetry(*a, **k)

        self.grid = GridFacade(self)

    # Primary Facade Methods (Direct delegation for ArenaDB level calls)
    async def get_spawn_node_name(self, *a, **k): return await self.navigation.get_spawn_node_name(*a, **k)
    async def set_spawn_node(self, *a, **k): return await self.navigation.set_spawn_node(*a, **k)
    async def get_location(self, *a, **k): return await self.navigation.get_location(*a, **k)
    async def move_player(self, *a, **k): return await self.navigation.move_player(*a, **k)
    async def claim_node(self, *a, **k): return await self.territory.claim_node(*a, **k)
    async def upgrade_node(self, *a, **k): return await self.territory.upgrade_node(*a, **k)
    async def grid_repair(self, *a, **k): return await self.territory.grid_repair(*a, **k)
    async def grid_recharge(self, *a, **k): return await self.territory.grid_recharge(*a, **k)
    async def siphon_node(self, *a, **k): return await self.infiltration.siphon_node(*a, **k)
    async def hack_node(self, *a, **k): return await self.infiltration.hack_node(*a, **k)
    async def raid_node(self, *a, **k): return await self.infiltration.raid_node(*a, **k)
    async def install_node_addon(self, *a, **k): return await self.territory.install_node_addon(*a, **k)
    async def bolster_node(self, *a, **k): return await self.territory.bolster_node(*a, **k)
    async def link_network(self, *a, **k): return await self.territory.link_network(*a, **k)
    async def explore_node(self, *a, **k): return await self.discovery.explore_node(*a, **k)
    async def probe_node(self, *a, **k): return await self.discovery.probe_node(*a, **k)

    async def close(self):
        await self.engine.dispose()

    async def init_schema(self):
        logger.info("Initializing database schema via SQLAlchemy...")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        
        async with self.async_session() as session:
            # 1. Initialize Nodes
            uplink = GridNode(name="UpLink", description="The central nexus. A safezone where new connections manifest.", node_type="safezone", is_spawn_node=True)
            arena_node = GridNode(name="The_Arena", description="The main fighting grounds. Blood and RAM are spilled here.", node_type="arena")
            wilderness = GridNode(name="The_CPU_Socket", description="A vast wasteland of processing power. Danger lurks.", node_type="wilderness")
            black_market = GridNode(
                name="Black_Market_Port", 
                description="Shadowy merchants peddle encrypted wares here.", 
                node_type="merchant",
                is_darknet=True,
                availability_mode='CLOSED'
            )
            
            session.add_all([uplink, arena_node, wilderness, black_market])
            await session.flush()
            
            # 2. Topology and Items are seeded via seed_grid_expansion and seed_items_only
            await session.commit()
            
            # 3. Item Templates
            item_tpl = ItemTemplate(name="Basic_Ration", item_type="consumable", base_value=10, effects_json='{"heal": 15}')
            rifle_tpl = ItemTemplate(name="Pulse_Rifle", item_type="weapon", base_value=1000, is_darknet=True, effects_json='{"damage": 25, "type": "kinetic"}')
            session.add_all([item_tpl, rifle_tpl])
            
            await session.commit()
        logger.info("Schema successfully initialized.")

    async def create_snapshot(self):
        """Creates a timestamped backup of the current database."""
        if not os.path.exists(DB_FILE):
             logger.warning("No database file found to snapshot.")
             return False
        
        bak_file = f"{DB_FILE}.bak"
        shutil.copy2(DB_FILE, bak_file)
        logger.info(f"Database snapshot created: {bak_file}")
        return True

    async def rollback_schema(self):
        """Reverts the database to the latest .bak snapshot."""
        bak_file = f"{DB_FILE}.bak"
        if not os.path.exists(bak_file):
            logger.error("No snapshot found to rollback to.")
            return False, "No snapshot file detected."
            
        shutil.copy2(bak_file, DB_FILE)
        logger.info("Database rolled back to snapshot successfully.")
        return True, "Rollback successful."

    async def update_schema(self):
        """Non-destructive schema update (Reflective Migration)."""
        logger.info("Starting reflective schema update...")
        await self.create_snapshot()
        
        def sync_columns(conn):
            inspector = inspect(conn)
            existing_tables = inspector.get_table_names()
            
            for table_name, table in Base.metadata.tables.items():
                if table_name not in existing_tables:
                    logger.info(f"Creating missing table: {table_name}")
                    table.create(conn)
                    continue

                existing_cols = [c['name'] for c in inspector.get_columns(table_name)]
                for col_name, col in table.columns.items():
                    if col_name not in existing_cols:
                        logger.info(f"Adding missing column: {table_name}.{col_name}")
                        # SQLite-specific ALTER TABLE logic
                        col_type = col.type.compile(dialect=conn.dialect)
                        # Handle defaults if possible
                        default_val = f" DEFAULT {col.default.arg}" if col.default else ""
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}{default_val}"))

        async with self.engine.begin() as conn:
            await conn.run_sync(sync_columns)
        
        logger.info("Schema update complete.")
        return True

    async def verify_integrity(self):
        """Audit the database for structural sync and logical consistency."""
        logger.info("Running database integrity audit...")
        issues = []
        
        # 1. Structural Audit (Missing Tables/Columns)
        def get_db_schema(conn):
            from sqlalchemy import inspect
            inspector = inspect(conn)
            schema = {}
            for table_name in inspector.get_table_names():
                schema[table_name] = [c['name'] for c in inspector.get_columns(table_name)]
            return schema

        try:
            async with self.engine.connect() as conn:
                db_schema = await conn.run_sync(get_db_schema)
                
                for table_name, table in Base.metadata.tables.items():
                    if table_name not in db_schema:
                        issues.append(f"[CRITICAL] Missing table: {table_name}")
                        continue
                    
                    for col in table.columns:
                        if col.name not in db_schema[table_name]:
                            issues.append(f"[CRITICAL] Missing column: {table_name}.{col.name}")
        except Exception as e:
            issues.append(f"[CRITICAL] Failed to inspect database schema: {e}")

        # If structural issues found, instruct admin and return early
        if any("[CRITICAL]" in i for i in issues):
            logger.error("Database schema desync detected!")
            logger.error("Run 'python3 ai_grid/grid_db.py update' to safely synchronize without data loss.")
            return issues

        # 2. Logical Audit
        async with self.async_session() as session:
            # 1. Check Uplink
            uplink = (await session.execute(select(GridNode).where(GridNode.name == "UpLink"))).scalars().first()
            if not uplink: issues.append("[CRITICAL] UpLink node is missing.")
            
            # 2. Check Item Templates
            items = (await session.execute(select(ItemTemplate))).scalars().all()
            if len(items) < 2: issues.append("[WARNING] Core item templates (Food/Weapon) are missing.")
            
            # 3. Check for Ghost Characters (no owner)
            ghosts = (await session.execute(select(Character).where(Character.player_id == None))).scalars().all()
            if ghosts: issues.append(f"[WARNING] Detected {len(ghosts)} orphaned 'Ghost' characters.")

        if not issues: logger.info("Integrity check passed: No issues detected.")
        else:
            for issue in issues: logger.warning(issue)
        return issues

    async def run_repairs(self):
        """Self-heal core data and connections."""
        logger.info("Executing database self-repair...")
        
        # 1. Item Seeding (Always additive)
        await self.seed_items_only()
        
        # 2. Spawn Node Check
        async with self.async_session() as session:
            spawn = (await session.execute(select(GridNode).where(GridNode.is_spawn_node == True))).scalars().first()
            if not spawn:
                # Fallback: Find UpLink or first safezone
                fallback = (await session.execute(select(GridNode).where(GridNode.name == "UpLink"))).scalars().first()
                if not fallback:
                    fallback = (await session.execute(select(GridNode).where(GridNode.node_type == "safezone"))).scalars().first()
                
                if fallback:
                    fallback.is_spawn_node = True
                    logger.info(f"Restored Spawn Flag to existing node: {fallback.name}")
                else:
                    new_uplink = GridNode(name="UpLink", description="Central nexus.", node_type="safezone", is_spawn_node=True)
                    session.add(new_uplink)
                    logger.info("Restored missing central nexus (Uplink).")
                await session.commit()
        
        logger.info("Repair sequence finished.")
        return True

    async def seed_items_only(self):
        """Add missing item templates without touching the map."""
        async with self.async_session() as session:
            for tpl_data in LOOT_TEMPLATES:
                exists = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == tpl_data["name"]))).scalars().first()
                if not exists: session.add(ItemTemplate(**tpl_data))
            await session.commit()

    async def seed_grid_expansion(self):
        """Smart Seeding: Add missing expansion nodes and connections."""
        async with self.async_session() as session:
            # Seed nodes additively
            for name, desc, node_type, threat in GRID_EXPANSION:
                exists = (await session.execute(select(GridNode).where(GridNode.name == name))).scalars().first()
                if not exists:
                    is_spawn = (name == "UpLink")
                    session.add(GridNode(name=name, description=desc, node_type=node_type, threat_level=threat, is_spawn_node=is_spawn))
            
            await session.flush()

            # --- SEED BRIDGE AFFINITIES (Task 021 Fix) ---
            for node_name, net_target in BRIDGE_MAPPING.items():
                node = (await session.execute(select(GridNode).where(GridNode.name == node_name))).scalars().first()
                if node:
                    node.net_affinity = net_target
                    logger.info(f"Seeded net_affinity: {node_name} -> {net_target}")

            # --- SEED NETWORK HOME NODES (Task 021) ---
            for net_name in CONFIG.get('networks', {}).keys():
                node_stmt = select(GridNode).where(GridNode.name == net_name)
                node = (await session.execute(node_stmt)).scalars().first()
                if not node:
                    node = GridNode(name=net_name, description=f"Entry point for the {net_name} local mesh.", node_type="wilderness")
                    session.add(node)
                    logger.info(f"Created Network Home Node: {net_name}")
                
                # Enforce standard entry parameters
                node.availability_mode = 'OPEN'
                node.upgrade_level = 1
                node.net_affinity = net_name
                node.addons_json = json.dumps({"NET": True})
                logger.debug(f"Configured {net_name} entry: OPEN, Level 1, NET Hardware.")

            await session.commit()

            # Seed connections
            for src_name, tgt_name, direction in GRID_CONNECTIONS:
                src = (await session.execute(select(GridNode).where(GridNode.name == src_name))).scalars().first()
                tgt = (await session.execute(select(GridNode).where(GridNode.name == tgt_name))).scalars().first()
                if not src or not tgt: continue
                exists = (await session.execute(select(NodeConnection).where(
                    NodeConnection.source_node_id == src.id, NodeConnection.target_node_id == tgt.id, NodeConnection.direction == direction
                ))).scalars().first()
                if not exists: session.add(NodeConnection(source_node_id=src.id, target_node_id=tgt.id, direction=direction))

            # Threat level fixes
            threat_map = {"The_CPU_Socket": 1, "Black_Market_Port": 0, "The_Arena": 0}
            for node_name, threat in threat_map.items():
                node = (await session.execute(select(GridNode).where(GridNode.name == node_name))).scalars().first()
                if node and node.threat_level != threat: node.threat_level = threat

            await session.commit()
            logger.info("Grid expansion seeded successfully.")

    # Delegation methods
    async def get_prefs(self, name, network): return await self.player.get_prefs(name, network)
    async def set_pref(self, name, network, key, value): return await self.player.set_pref(name, network, key, value)
    async def get_daily_tasks(self, name, network): return await self.player.get_daily_tasks(name, network)
    async def complete_task(self, name, network, task_key): return await self.player.complete_task(name, network, task_key)
    async def register_player(self, name, network, race, bot_class, bio, stats): return await self.player.register_player(name, network, race, bot_class, bio, stats)
    async def get_player(self, name, network): return await self.player.get_player(name, network)
    async def authenticate_player(self, name, network, provided_token): return await self.player.authenticate_player(name, network, provided_token)
    async def list_players(self, network=None): return await self.player.list_players(network)
    async def get_character_by_nick(self, nick: str, network: str, session): return await self.player.get_character_by_nick(nick, network, session)
    async def update_last_seen(self, nick: str, network: str): return await self.player.update_last_seen(nick, network)
    async def update_activity_stats(self, nick, net, chat, idle): return await self.player.update_activity_stats(nick, net, chat, idle)
    async def get_spectator_stats(self, nick, net, config): return await self.player.get_spectator_stats(nick, net, config)
    async def tick_retention_policy(self, config): return await self.player.tick_retention_policy(config)
    async def tick_player_maintenance(self, network, idlers): return await self.player.tick_player_maintenance(network, idlers)
    async def active_powergen(self, name, network): return await self.player.active_powergen(name, network)
    async def active_training(self, name, network): return await self.player.active_training(name, network)
    async def explore_node(self, name, network): return await self.grid.explore_node(name, network)
    async def raid_node(self, name, network): return await self.grid.raid_node(name, network)

    async def get_location(self, name, network): return await self.grid.get_location(name, network)
    async def move_player(self, name, network, direction): return await self.grid.move_player(name, network, direction)
    async def move_player_to_node(self, name, network, node_name): return await self.grid.move_player_to_node(name, network, node_name)
    async def grid_repair(self, name, network): return await self.grid.grid_repair(name, network)
    async def grid_recharge(self, name, network): return await self.grid.grid_recharge(name, network)
    async def claim_node(self, name, network): return await self.grid.claim_node(name, network)
    async def upgrade_node(self, name, network): return await self.grid.upgrade_node(name, network)
    async def siphon_node(self, name, network, percentage=100.0): return await self.grid.siphon_node(name, network, percentage)
    async def hack_node(self, name, network): return await self.grid.hack_node(name, network)
    async def probe_node(self, name, network): return await self.grid.probe_node(name, network)
    async def install_node_addon(self, name, network, item_name): return await self.grid.install_node_addon(name, network, item_name)
    async def bolster_node(self, name, network, amount): return await self.grid.bolster_node(name, network, amount)
    async def link_network(self, name, network, local_net_name): return await self.grid.link_network(name, network, local_net_name)
    async def tick_grid_power(self): return await self.grid.tick_grid_power()
    async def get_grid_telemetry(self): return await self.grid.get_grid_telemetry()
    async def rename_node(self, old, new): return await self.grid.rename_node(old, new)
    async def get_prefs_by_id(self, char_id): return await self.player.get_prefs_by_id(char_id)
    async def get_nickname_by_id(self, char_id): return await self.player.get_nickname_by_id(char_id)

    async def list_shop_items(self): return await self.economy.list_shop_items()
    async def award_credits_bulk(self, payouts, network): return await self.economy.award_credits_bulk(payouts, network)
    async def process_transaction(self, name, network, action, item_name): return await self.economy.process_transaction(name, network, action, item_name)
    async def get_global_economy(self): return await self.economy.get_global_economy()

    async def record_match_result(self, winner_name, loser_name, network): return await self.combat.record_match_result(winner_name, loser_name, network)
    async def resolve_mob_encounter(self, name, network, threat_level): return await self.combat.resolve_mob_encounter(name, network, threat_level)
    async def grid_attack(self, attacker_name, target_name, network): return await self.combat.grid_attack(attacker_name, target_name, network)
    async def grid_hack(self, attacker_name, target_name, network): return await self.combat.grid_hack(attacker_name, target_name, network)
    async def grid_rob(self, attacker_name, target_name, network): return await self.combat.grid_rob(attacker_name, target_name, network)
    async def use_item(self, name, network, item_name): return await self.economy.use_item(name, network, item_name)
    
    # Economy (Auctions)
    async def list_active_auctions(self): return await self.economy.list_active_auctions()
    async def create_auction(self, name, network, item, start, dur): return await self.economy.create_auction(name, network, item, start, dur)
    async def bid_on_auction(self, name, network, aid, amt): return await self.economy.bid_on_auction(name, network, aid, amt)
    async def tick_auctions(self): return await self.economy.tick_auctions()
    async def update_market_rates(self, rates, text=None): return await self.economy.update_market_rates(rates, text)
    async def get_market_status(self): return await self.economy.get_market_status()

    # Mini-Games & Leaderboards
    async def roll_dice(self, name, net, bet, choice): return await self.minigame.roll_dice(name, net, bet, choice)
    async def start_cipher(self, name, net): return await self.minigame.start_cipher(name, net)
    async def guess_cipher(self, name, net, guess): return await self.minigame.submit_guess(name, net, guess)
    async def get_leaderboard(self, cat): return await self.minigame.get_leaderboard(cat)


    # Mainframe (The Gibson)
    async def get_gibson_status(self, name, network): return await self.mainframe.get_gibson_status(name, network)
    async def start_compilation(self, name, network, amount): return await self.mainframe.start_compilation(name, network, amount)
    async def start_assembly(self, name, network): return await self.mainframe.start_assembly(name, network)
    async def tick_mainframe_tasks(self): return await self.mainframe.tick_mainframe_tasks()

async def async_main():
    parser = argparse.ArgumentParser(description="AutomataArena Async SQLAlchemy DB Manager")
    parser.add_argument("--network", type=str, help="Filter by network")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    subparsers.add_parser("init", help="Initialize the database schema")
    subparsers.add_parser("update", help="Non-destructive schema sync + seed maps")
    subparsers.add_parser("check", help="Run database integrity audit")
    subparsers.add_parser("rollback", help="Revert to last .bak snapshot")
    subparsers.add_parser("repair", help="Run automatic self-repair sequence")
    subparsers.add_parser("reseed", help="Update grid expansion nodes and connections")
    subparsers.add_parser("list", help="List all registered fighters")
    del_parser = subparsers.add_parser("delete", help="Delete a player")
    del_parser.add_argument("--name", type=str, required=True, help="Player nickname")
    args = parser.parse_args()
    db = ArenaDB()
    if args.command == "init":
        await db.init_schema()
        print("[*] Database schema initialized.")
    elif args.command == "update":
        await db.update_schema()
        await db.seed_grid_expansion()
        print("[*] Reflective update complete. Map seeded.")
    elif args.command == "check":
        issues = await db.verify_integrity()
        if not issues: print("[*] Integrity check passed.")
        else:
            print("[!] Found the following issues:")
            for i in issues: print(f"  - {i}")
    elif args.command == "rollback":
        success, msg = await db.rollback_schema()
        print(f"[{'*' if success else '!'}] {msg}")
    elif args.command == "repair":
        await db.run_repairs()
        print("[*] Repair sequence completed.")
    elif args.command == "reseed":
        await db.seed_grid_expansion()
        print("[*] Grid expansion re-seeded.")
    elif args.command == "list":
        players = await db.list_players(args.network)
        print(f"\n--- Registered Players ({len(players)}) ---")
        print(f"{'Name':<15} | {'Network':<10} | {'Elo':<6} | {'W/L':<7} | {'Credits'}")
        print("-" * 55)
        for p in players:
            wl = f"{p['wins']}/{p['losses']}"
            print(f"{p['name']:<15} | {p['network']:<10} | {p['elo']:<6} | {wl:<7} | {p['credits']}")
    elif args.command == "delete":
        async with db.async_session() as session:
            stmt = select(Player).join(NetworkAlias).where(NetworkAlias.nickname.ilike(args.name))
            p = (await session.execute(stmt)).scalars().first()
            if p:
                await session.delete(p)
                await session.commit()
                print(f"[*] Player {args.name} deleted.")
            else:
                print(f"[!] Player {args.name} not found.")
    else:
        parser.print_help()
    await db.close()

if __name__ == "__main__":
    asyncio.run(async_main())
