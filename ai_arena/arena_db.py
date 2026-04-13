import asyncio
import json
import uuid
import logging
import argparse
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from models import Base, Player, NetworkAlias, Character, InventoryItem, ItemTemplate, GridNode, NodeConnection

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

try:
    with open(CONFIG_FILE, 'r') as f:
        CONFIG = json.load(f)
        db_name = CONFIG.get('database', {}).get('file', 'automata_arena.db')
        DB_FILE = os.path.join(BASE_DIR, db_name)
except (FileNotFoundError, json.JSONDecodeError):
    CONFIG = {}
    DB_FILE = os.path.join(BASE_DIR, 'automata_arena.db')

logger = logging.getLogger("arena_db")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

fh = logging.FileHandler(os.path.join(BASE_DIR, 'arena_db.log'))
fh.setFormatter(formatter)
logger.addHandler(fh)

ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

class ArenaDB:
    def __init__(self, db_path=DB_FILE):
        self.db_path = f"sqlite+aiosqlite:///{db_path}"
        self.engine = create_async_engine(self.db_path, echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        
    async def close(self):
        await self.engine.dispose()
        
    async def init_schema(self):
        logger.info("Initializing database schema via SQLAlchemy...")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        
        async with self.async_session() as session:
            # 1. Initialize Nodes
            uplink = GridNode(name="The_Grid_Uplink", description="The central nexus. A safezone where new connections manifest.", node_type="safezone")
            arena_node = GridNode(name="The_Arena", description="The main fighting grounds. Blood and RAM are spilled here.", node_type="arena")
            wilderness = GridNode(name="The_CPU_Socket", description="A vast wasteland of processing power. Danger lurks.", node_type="wilderness")
            black_market = GridNode(name="Black_Market_Port", description="Shadowy merchants peddle encrypted wares here.", node_type="merchant")
            
            session.add_all([uplink, arena_node, wilderness, black_market])
            await session.flush() # Flush to get assigned IDs
            
            # 2. Establish Topology (Connections)
            connections = [
                NodeConnection(source_node_id=uplink.id, target_node_id=arena_node.id, direction="north"),
                NodeConnection(source_node_id=arena_node.id, target_node_id=uplink.id, direction="south"),
                
                NodeConnection(source_node_id=uplink.id, target_node_id=wilderness.id, direction="east"),
                NodeConnection(source_node_id=wilderness.id, target_node_id=uplink.id, direction="west"),
                
                NodeConnection(source_node_id=uplink.id, target_node_id=black_market.id, direction="down"),
                NodeConnection(source_node_id=black_market.id, target_node_id=uplink.id, direction="up")
            ]
            session.add_all(connections)
            
            # 3. Item Templates
            item_tpl = ItemTemplate(name="Basic_Ration", item_type="consumable", base_value=10, effects_json='{"heal": 15}')
            rifle_tpl = ItemTemplate(name="Pulse_Rifle", item_type="weapon", base_value=100, effects_json='{"damage": 25, "type": "kinetic"}')
            session.add_all([item_tpl, rifle_tpl])
            
            await session.commit()
        logger.info("Schema v2 successfully initialized with seeded Grid topology.")

    async def register_fighter(self, name, network, race, bot_class, bio, stats: dict):
        logger.info(f"Attempting to register fighter: {name} on {network}")
        auth_token = str(uuid.uuid4())
        
        async with self.async_session() as session:
            stmt_player = select(Player).join(NetworkAlias).where(NetworkAlias.nickname == name, NetworkAlias.network_name == network)
            result = await session.execute(stmt_player)
            player = result.scalars().first()
            
            if not player:
                player = Player(global_name=f"{name}_{network}", is_autonomous=False)
                session.add(player)
                await session.flush()
                
                alias = NetworkAlias(player_id=player.id, network_name=network, nickname=name)
                session.add(alias)
                await session.flush()
                
            stmt_char = select(Character).where(Character.name == name, Character.player_id == player.id)
            result = await session.execute(stmt_char)
            if result.scalars().first():
                logger.warning(f"Registration failed: Fighter '{name}' already exists.")
                return None
            
            stmt_node = select(GridNode).where(GridNode.name == "The_Grid_Uplink")
            result = await session.execute(stmt_node)
            node = result.scalars().first()
                
            character = Character(
                player_id=player.id,
                node_id=node.id if node else None,
                name=name,
                race=race,
                char_class=bot_class,
                bio=bio,
                cpu=stats.get('cpu', 5),
                ram=stats.get('ram', 5),
                bnd=stats.get('bnd', 5),
                sec=stats.get('sec', 5),
                alg=stats.get('alg', 5),
                auth_token=auth_token
            )
            session.add(character)
            await session.flush()
            
            stmt_item = select(ItemTemplate).where(ItemTemplate.name == "Basic_Ration")
            res = await session.execute(stmt_item)
            tpl = res.scalars().first()
            if tpl:
                inv_item = InventoryItem(character_id=character.id, template_id=tpl.id, quantity=1)
                session.add(inv_item)
                
            await session.commit()
            return auth_token

    async def get_fighter(self, name, network):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.inventory).selectinload(InventoryItem.template))
            
            result = await session.execute(stmt)
            char = result.scalars().first()
            if char:
                inv = [item.template.name for item in char.inventory] if char.inventory else []
                return {
                    'name': char.name,
                    'is_npc': False,
                    'cpu': char.cpu,
                    'ram': char.ram,
                    'bnd': char.bnd,
                    'sec': char.sec,
                    'alg': char.alg,
                    'bio': char.bio,
                    'inventory': json.dumps(inv), 
                    'alignment': 0,
                    'status': char.status,
                    'elo': char.elo,
                    'wins': char.wins,
                    'losses': char.losses,
                    'credits': char.credits
                }
            return None

    async def authenticate_fighter(self, name, network, provided_token):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            )
            result = await session.execute(stmt)
            char = result.scalars().first()
            if char and char.auth_token == provided_token:
                return True
            return False

    async def list_fighters(self, network=None):
        async with self.async_session() as session:
            stmt = select(Character, NetworkAlias).select_from(Character).join(Player).join(NetworkAlias)
            if network:
                stmt = stmt.where(NetworkAlias.network_name == network)
            stmt = stmt.order_by(Character.elo.desc())
            
            result = await session.execute(stmt)
            fighters = []
            for char, alias in result:
                fighters.append({
                    'name': char.name,
                    'network': alias.network_name,
                    'elo': char.elo,
                    'wins': char.wins,
                    'losses': char.losses,
                    'credits': char.credits
                })
            return fighters

    async def get_location(self, name, network):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node)
                .selectinload(GridNode.exits)
                .selectinload(NodeConnection.target_node)
            )
            result = await session.execute(stmt)
            char = result.scalars().first()
            if not char:
                return None
            node = char.current_node
            if not node:
                return None
            exits = [f"{c.direction} -> {c.target_node.name}" for c in node.exits]
            return {
                'name': node.name,
                'description': node.description,
                'type': node.node_type,
                'exits': exits,
                'credits': char.credits,
                'level': char.level,
            }

    async def move_fighter(self, name, network, direction):
        from models import NodeConnection  # Ensure it's imported or globally available
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node)
                .selectinload(GridNode.exits)
                .selectinload(NodeConnection.target_node)
            )
            result = await session.execute(stmt)
            char = result.scalars().first()
            if not char: return None, "System offline."
            if not char.current_node: return None, "You are floating in the void."
            
            for conn in char.current_node.exits:
                if conn.direction.lower() == direction.lower():
                    char.node_id = conn.target_node_id
                    await session.commit()
                    return conn.target_node.name, f"Traversed {direction} to {conn.target_node.name}."
            return None, f"No valid route found for '{direction}'."

    async def list_shop_items(self):
        from models import ItemTemplate
        async with self.async_session() as session:
            stmt = select(ItemTemplate).order_by(ItemTemplate.base_value.asc())
            result = await session.execute(stmt)
            return [{'name': t.name, 'type': t.item_type, 'cost': t.base_value} for t in result.scalars().all()]

    async def process_transaction(self, name, network, action, item_name):
        from models import InventoryItem, ItemTemplate
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.inventory).selectinload(InventoryItem.template)
            )
            result = await session.execute(stmt)
            char = result.scalars().first()
            if not char: return False, "System offline: Fighter not found."
            if not char.current_node or char.current_node.node_type != "merchant":
                return False, "Transaction Failed: No merchant in this node."
                
            stmt_item = select(ItemTemplate).where(ItemTemplate.name.ilike(item_name))
            result = await session.execute(stmt_item)
            tpl = result.scalars().first()
            if not tpl: return False, f"Unknown item: '{item_name}'"
            
            if action == "buy":
                if char.credits < tpl.base_value:
                    return False, f"Insufficient credits. {tpl.name} costs {tpl.base_value}c."
                char.credits -= tpl.base_value
                
                existing = next((i for i in char.inventory if i.template_id == tpl.id), None)
                if existing:
                    existing.quantity += 1
                else:
                    new_item = InventoryItem(character_id=char.id, template_id=tpl.id)
                    session.add(new_item)
                
                await session.commit()
                return True, f"Purchased {tpl.name} for {tpl.base_value}c. Balance: {char.credits}c."
            
            elif action == "sell":
                existing = next((i for i in char.inventory if i.template_id == tpl.id and i.quantity > 0), None)
                if not existing:
                    return False, f"You do not possess a {tpl.name}."
                
                sell_price = max(1, int(tpl.base_value * 0.5))
                char.credits += sell_price
                existing.quantity -= 1
                if existing.quantity <= 0:
                    await session.delete(existing)
                
                await session.commit()
                return True, f"Sold {tpl.name} for {sell_price}c. Balance: {char.credits}c."
            return False, "Invalid action."


    async def record_match_result(self, winner_name, loser_name, network):
        async with self.async_session() as session:
            # We assume winner and loser both exist on this network
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name.in_([winner_name, loser_name]),
                NetworkAlias.network_name == network
            )
            result = await session.execute(stmt)
            chars = result.scalars().all()
            
            winner, loser = None, None
            for c in chars:
                if c.name == winner_name: winner = c
                if c.name == loser_name: loser = c
            
            if winner:
                winner.wins += 1
                winner.elo += 15
                winner.xp += 50
                winner.credits += 100
                if winner.xp >= winner.level * 100:
                    winner.level += 1
                    winner.xp = 0
                    winner.cpu += 1
            if loser:
                loser.losses += 1
                loser.elo = max(0, loser.elo - 15)
                loser.xp += 10
            
            await session.commit()

async def async_main():
    parser = argparse.ArgumentParser(description="AutomataArena Async SQLAlchemy DB Manager")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("init", help="Initialize the database schema")
    list_parser = subparsers.add_parser("list", help="List all registered fighters")
    list_parser.add_argument("--network", type=str, help="Filter by IRC network")

    args = parser.parse_args()
    db = ArenaDB()

    if args.command == "init":
        await db.init_schema()
        print("[*] Database schema initialized.")
    elif args.command == "list":
        fighters = await db.list_fighters(args.network)
        print(f"\n--- Registered Fighters ({len(fighters)}) ---")
        print(f"{'Name':<15} | {'Network':<10} | {'Elo':<6} | {'W/L':<7} | {'Credits'}")
        print("-" * 55)
        for f in fighters:
            wl = f"{f['wins']}/{f['losses']}"
            print(f"{f['name']:<15} | {f['network']:<10} | {f['elo']:<6} | {wl:<7} | {f['credits']}")
        print()
    else:
        parser.print_help()
        
    await db.close()

if __name__ == "__main__":
    asyncio.run(async_main())
