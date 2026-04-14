# arena_db.py - v2.1.0
# Database layer with auth-gated prefs, daily tasks, and Grid PvP transactions
import asyncio
import json
import uuid
import logging
import argparse
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
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

    DEFAULT_PREFS = {
        "output_mode": "human",
        "auto_sell_trash": False,
        "tutorial_mode": True,
        "reminders": True
    }

    async def get_prefs(self, name: str, network: str) -> dict:
        async with self.async_session() as session:
            name_lower = name.lower()
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == name_lower,
                func.lower(NetworkAlias.nickname) == name_lower,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char:
                return dict(self.DEFAULT_PREFS)
            try:
                return {**self.DEFAULT_PREFS, **json.loads(char.prefs or '{}')}
            except Exception:
                return dict(self.DEFAULT_PREFS)

    async def set_pref(self, name: str, network: str, key: str, value) -> bool:
        async with self.async_session() as session:
            name_lower = name.lower()
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == name_lower,
                func.lower(NetworkAlias.nickname) == name_lower,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char:
                return False
            try:
                prefs = {**self.DEFAULT_PREFS, **json.loads(char.prefs or '{}')}
            except Exception:
                prefs = dict(self.DEFAULT_PREFS)
            prefs[key] = value
            char.prefs = json.dumps(prefs)
            await session.commit()
            return True

    async def grid_repair(self, name, network):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            
            node = char.current_node
            if not node.owner_character_id: return False, "You cannot repair unclaimed wilderness."
            if node.durability >= 100.0: return False, "Grid is already at maximum durability."
            if char.credits < 100.0: return False, "You need 100c to repair the node."
            
            char.credits -= 100.0
            node.durability = 100.0
            reward_msg = await self.increment_daily_task(session, char, "Repair a Node")
            await session.commit()
            
            msg = "Grid repaired to 100% durability."
            if reward_msg: msg += f" {reward_msg}"
            return True, msg

    async def grid_recharge(self, name, network):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            
            node = char.current_node
            if not node.owner_character_id: return False, "You cannot recharge unclaimed wilderness."
            max_power = node.upgrade_level * 100.0
            if node.power_stored >= max_power: return False, "Grid power is already at maximum."
            if char.credits < 100.0: return False, "You need 100c to recharge power."
            
            char.credits -= 100.0
            node.power_stored = max_power
            await session.commit()
            
            return True, f"Grid recharged to MAX ({max_power} uP)."

    async def get_daily_tasks(self, name, network):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return "{}"
            
            import datetime
            today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
            try: tasks = json.loads(char.daily_tasks)
            except: tasks = {}
        if tasks.get("date") != today:
            tasks = {"date": today, "Claim a Node": 0, "Defend a Node": 0, "Hack a Player": 0, "Repair a Node": 0, "Kill a Grid Bug": 0, "Queue in Arena": 0, "completed": False}
            char.daily_tasks = json.dumps(tasks)
            await session.commit()
        return char.daily_tasks

    async def complete_task(self, name, network, task_key):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return None
            
            reward_msg = await self.increment_daily_task(session, char, task_key)
            await session.commit()
            return reward_msg

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
            existing = result.scalars().first()
            if existing:
                if existing.race == "Spectator" and race != "Spectator":
                    existing.race = race
                    existing.char_class = bot_class
                    existing.bio = bio
                    existing.cpu = stats.get('cpu', 5)
                    existing.ram = stats.get('ram', 5)
                    existing.bnd = stats.get('bnd', 5)
                    existing.sec = stats.get('sec', 5)
                    existing.alg = stats.get('alg', 5)
                    existing.current_hp = stats.get('ram', 5) * 5
                    await session.commit()
                    return existing.auth_token
                else:
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
                current_hp=stats.get('ram', 5) * 5,
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
                    'race': char.race,
                    'char_class': char.char_class,
                    'level': char.level,
                    'xp': char.xp,
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
                    'credits': char.credits,
                    'current_hp': char.current_hp,
                    'max_hp': char.ram * 5
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
                .selectinload(NodeConnection.target_node),
                selectinload(Character.current_node)
                .selectinload(GridNode.owner)
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
                'power_stored': node.power_stored,
                'power_consumed': node.power_consumed,
                'power_generated': node.power_generated,
                'owner': node.owner.name if node.owner else "Unclaimed",
                'upgrade_level': node.upgrade_level,
                'durability': node.durability,
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

    async def award_credits_bulk(self, payouts: dict, network: str):
        async with self.async_session() as session:
            for nick, amt in payouts.items():
                stmt = select(Character).join(Player).join(NetworkAlias).where(
                    Character.name == nick,
                    NetworkAlias.nickname == nick,
                    NetworkAlias.network_name == network
                )
                result = await session.execute(stmt)
                char = result.scalars().first()
                if char:
                    char.credits += amt
            await session.commit()

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
                
                xp_threshold = winner.level * 1000
                if winner.xp >= xp_threshold:
                    winner.xp -= xp_threshold
                    winner.level += 1
                    winner.cpu += 1
            if loser:
                loser.losses += 1
                loser.elo = max(0, loser.elo - 15)
                loser.xp += 10
            
            await session.commit()

    async def claim_node(self, name, network):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            node = char.current_node
            
            if node.owner_character_id:
                if node.owner_character_id == char.id:
                    return False, "You already command this node."
                return False, "This node is controlled by a rival. You must seize it."
                
            node.owner_character_id = char.id
            node.power_stored = 100.0
            node.durability = 100.0
            
            reward_msg = await self.increment_daily_task(session, char, "Claim a Node")
            await session.commit()
            msg = f"Control established over {node.name}."
            if reward_msg: msg += f" {reward_msg}"
            return True, msg

    async def upgrade_node(self, name, network):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            node = char.current_node
            if node.owner_character_id != char.id: return False, "You do not command this node."
            
            cost = node.upgrade_level * 500
            if char.credits < cost: return False, f"Insufficient credits. Upgrade requires {cost}c."
            
            char.credits -= cost
            node.upgrade_level += 1
            await session.commit()
            return True, f"Upgraded {node.name} to Level {node.upgrade_level} for {cost}c! Max Capacity increased."

    async def siphon_node(self, name, network):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            node = char.current_node
            
            if not node.owner_character_id: return False, "Node is already Unclaimed. Type '{config.prefix} claim' to seize it."
            if node.owner_character_id == char.id: return False, "You cannot siphon your own node."
            if node.upgrade_level > 2: return False, "Cannot siphon a heavily upgraded node. Security ICE is too high."
            
            siphon_amount = min(50.0, node.power_stored)
            node.power_stored -= siphon_amount
            char.credits += siphon_amount * 2 
            
            if node.power_stored <= 0:
                node.power_stored = 0
                node.owner_character_id = None
                await session.commit()
                return True, f"You siphoned {siphon_amount} power and crashed the grid. The node is now Unclaimed."
                
            await session.commit()
            return True, f"You siphoned {siphon_amount} power. The node is destabilizing."

    async def hack_node(self, name, network):
        import random
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node).selectinload(GridNode.owner))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            node = char.current_node
            
            if not node.owner_character_id: return False, "Node is Unclaimed."
            if node.owner_character_id == char.id: return False, "You already own this node."
            
            max_power = node.upgrade_level * 100
            if node.power_stored >= max_power * 0.9:
                return False, "PVE_GUARDIAN_SPAWN"
            
            roll = random.randint(1, 20) + char.alg
            difficulty = 10 + (node.upgrade_level * 2)
            
            if roll >= difficulty:
                old_owner = node.owner.name if node.owner else "Unknown"
                node.owner_character_id = char.id
                reward_msg = await self.increment_daily_task(session, char, "Claim a Node")
                await session.commit()
                msg = f"Hack Successful (Rolled {roll} vs DC {difficulty}). You violently stripped command from {old_owner}!"
                if reward_msg: msg += f" {reward_msg}"
                return True, msg
            else:
                char.credits = max(0.0, char.credits - 50.0) # Penalty
                await session.commit()
                return False, f"Hack Failed (Rolled {roll} vs DC {difficulty}). The ICE rejected your intrusion and fined you 50c."

    async def increment_daily_task(self, session, char, task_key):
        import datetime
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        
        try: tasks = json.loads(char.daily_tasks)
        except: tasks = {}
        
        if tasks.get("date") != today:
            tasks = {
                "date": today,
                "Claim a Node": 0,
                "Defend a Node": 0,
                "Hack a Player": 0,
                "Repair a Node": 0,
                "Kill a Grid Bug": 0,
                "Queue in Arena": 0,
                "completed": False
            }
            
        if tasks.get("completed"): return None

        if task_key in tasks and tasks[task_key] < 1:
            tasks[task_key] += 1
            
        completed_count = sum(1 for k, v in tasks.items() if k not in ["date", "completed"] and v >= 1)
        reward_msg = None
        
        if completed_count >= 3 and not tasks.get("completed"):
            tasks["completed"] = True
            char.credits += 500.0
            reward_msg = f"[SIGACT] 🏆 {char.name} completed 3 Daily Tasks and earned a 500c bonus!"
            
        char.daily_tasks = json.dumps(tasks)
        return reward_msg

    async def tick_grid_power(self):
        async with self.async_session() as session:
            stmt = select(GridNode).options(selectinload(GridNode.characters_present))
            nodes = (await session.execute(stmt)).scalars().all()
            for node in nodes:
                occupants = len(node.characters_present)
                if node.owner_character_id:
                    if occupants > 0:
                        # Idle repair/recharge
                        generated = occupants * 5.0
                        max_power = node.upgrade_level * 100.0
                        node.power_generated += generated
                        node.power_stored = min(max_power, node.power_stored + generated)
                        node.durability = min(100.0, node.durability + (occupants * 2.0))
                    else:
                        # Decay over time if empty
                        node.durability -= 5.0
                        if node.durability <= 0:
                            if node.upgrade_level > 1:
                                node.upgrade_level -= 1
                                node.durability = 100.0
                            else:
                                node.owner_character_id = None # Node is lost
                                node.upgrade_level = 1
                                node.durability = 100.0
            await session.commit()

    async def grid_attack(self, attacker_name, target_name, network):
        import random
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name.in_([attacker_name, target_name]),
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.inventory)
            )
            result = (await session.execute(stmt)).scalars().all()
            
            attacker, target = None, None
            for c in result:
                if c.name.lower() == attacker_name.lower(): attacker = c
                if c.name.lower() == target_name.lower(): target = c
                
            if not attacker or not target: return False, "Target not found on this network."
            if attacker.node_id != target.node_id: return False, "You must be in the same Network Node as your target."
            if not target.current_node or target.current_node.node_type == "safezone": return False, "Combat is strictly prohibited in this zone."
            if attacker.id == target.id: return False, "Self-termination is illogical."
            
            # Simple 1-hit resolution
            evade_roll = random.randint(1, 100)
            if evade_roll <= (target.bnd * 2):
                return True, f"{attacker.name} swung wildly at {target.name}, but they evaded!"
                
            raw_dmg = attacker.cpu * 3
            final_dmg = max(1, raw_dmg - target.sec)
            if random.randint(1, 100) <= attacker.alg: final_dmg *= 2 # Crit
            
            target.current_hp -= final_dmg
            if target.current_hp <= 0:
                looted = target.credits * 0.10
                target.credits -= looted
                attacker.credits += looted
                
                # Move to safezone
                uplink = (await session.execute(select(GridNode).where(GridNode.name == "The_Grid_Uplink"))).scalars().first()
                if uplink: target.node_id = uplink.id
                target.current_hp = target.ram * 5 # Reset HP
                
                await session.commit()
                return True, f"{attacker.name} struck {target.name} for {final_dmg} DMG! {target.name} flatlines... {attacker.name} loots {looted:.2f}c."
                
            await session.commit()
            return True, f"{attacker.name} struck {target.name} for {final_dmg} DMG! ({target.current_hp}/{target.ram*5} HP)"

    async def grid_hack(self, attacker_name, target_name, network):
        import random
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name.in_([attacker_name, target_name]),
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            result = (await session.execute(stmt)).scalars().all()
            
            attacker, target = None, None
            for c in result:
                if c.name.lower() == attacker_name.lower(): attacker = c
                if c.name.lower() == target_name.lower(): target = c
                
            if not attacker or not target: return False, "Target not found."
            if attacker.node_id != target.node_id: return False, "Target is not in your current sector."
            if target.current_node and target.current_node.node_type == "safezone": return False, "ICE prevents hacking in safezones."
            if attacker.id == target.id: return False, "..."
            
            roll = random.randint(1, 20) + attacker.alg
            dc = 10 + target.sec
            if roll >= dc:
                looted = target.credits * 0.05
                target.credits -= looted
                attacker.credits += looted
                reward_msg = await self.increment_daily_task(session, attacker, "Hack a Player")
                await session.commit()
                msg = f"Hack Successful! {attacker.name} breached {target.name}'s firewall and siphoned {looted:.2f}c."
                return True, msg, reward_msg
            else:
                attacker.credits = max(0.0, attacker.credits - 50.0)
                await session.commit()
                return False, f"Hack Failed. {target.name}'s ICE traced the intrusion. {attacker.name} is fined 50c!"

    async def grid_rob(self, attacker_name, target_name, network):
        import random
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name.in_([attacker_name, target_name]),
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.inventory)
            )
            result = (await session.execute(stmt)).scalars().all()
            
            attacker, target = None, None
            for c in result:
                if c.name.lower() == attacker_name.lower(): attacker = c
                if c.name.lower() == target_name.lower(): target = c
                
            if not attacker or not target: return False, "Target not found."
            if attacker.node_id != target.node_id: return False, "Target is not in your locale."
            if target.current_node and target.current_node.node_type == "safezone": return False, "No physical theft allowed here."
            if attacker.id == target.id: return False, "..."
            if not target.inventory: return False, f"{target.name}'s pockets are empty."
            
            roll = random.randint(1, 20) + attacker.bnd
            dc = 10 + target.bnd
            if roll >= dc:
                item_to_steal = random.choice(target.inventory)
                item_to_steal.character_id = attacker.id
                await session.commit()
                return True, f"Sleight of hand successful! {attacker.name} lifted an item."
            else:
                return False, f"{attacker.name} clumsily attempted to rob {target.name} and was caught!"

async def async_main():
    parser = argparse.ArgumentParser(description="AutomataArena Async SQLAlchemy DB Manager")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("init", help="Initialize the database schema")
    list_parser = subparsers.add_parser("list", help="List all registered fighters")
    del_parser = subparsers.add_parser("delete", help="Delete a player")
    del_parser.add_argument("--name", type=str, required=True, help="Player nickname")

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
