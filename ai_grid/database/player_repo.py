# player_repo.py
import json
import uuid
import datetime
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from models import Player, NetworkAlias, Character, InventoryItem, ItemTemplate, GridNode, Syndicate
from .core import logger, DEFAULT_PREFS

class PlayerRepository:
    def __init__(self, async_session):
        self.async_session = async_session

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
                return dict(DEFAULT_PREFS)
            try:
                return {**DEFAULT_PREFS, **json.loads(char.prefs or '{}')}
            except Exception:
                return dict(DEFAULT_PREFS)

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
                prefs = {**DEFAULT_PREFS, **json.loads(char.prefs or '{}')}
            except Exception:
                prefs = dict(DEFAULT_PREFS)
            prefs[key] = value
            char.prefs = json.dumps(prefs)
            await session.commit()
            return True

    async def get_daily_tasks(self, name: str, network: str) -> str:
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return "{}"
            
            today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
            try: tasks = json.loads(char.daily_tasks)
            except: tasks = {}
            
            if tasks.get("date") != today:
                tasks = {"date": today, "Claim a Node": 0, "Defend a Node": 0, "Hack a Player": 0, "Repair a Node": 0, "Kill a Grid Bug": 0, "Queue in Arena": 0, "completed": False}
                char.daily_tasks = json.dumps(tasks)
                await session.commit()
            return char.daily_tasks

    async def complete_task(self, name: str, network: str, task_key: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return None
            
            reward_msg = await increment_daily_task(session, char, task_key)
            await session.commit()
            return reward_msg

    async def register_fighter(self, name: str, network: str, race: str, bot_class: str, bio: str, stats: dict):
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
                power=stats.get('power', 100.0),
                stability=stats.get('stability', 100.0),
                alignment=stats.get('alignment', 0),
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

    async def get_fighter(self, name: str, network: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.inventory).selectinload(InventoryItem.template),
                selectinload("syndicate").selectinload(Syndicate.active_mission)
            )
            
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
                    'alignment': char.alignment,
                    'stability': char.stability,
                    'power': char.power,
                    'status': char.status,
                    'elo': char.elo,
                    'wins': char.wins,
                    'losses': char.losses,
                    'credits': char.credits,
                    'current_hp': char.current_hp,
                    'max_hp': char.ram * 5,
                    'data_units': char.data_units,
                    'syndicate_id': char.syndicate_id,
                    'active_mission': char.syndicate.active_mission.mission_type if char.syndicate and char.syndicate.active_mission else None,
                    'war_target': char.syndicate.target_syndicate_id if char.syndicate else None
                }
            return None

    async def authenticate_fighter(self, name: str, network: str, provided_token: str):
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

async def increment_daily_task(session, char, task_key):
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

async def update_faction_mission(session, syndicate_id, mission_type, amount):
    """Increments progress for a syndicate's active mission."""
    from models import Syndicate, SyndicateMission
    stmt = select(Syndicate).where(Syndicate.id == syndicate_id).options(selectinload(Syndicate.active_mission))
    result = await session.execute(stmt)
    syn = result.scalars().first()
    
    if syn and syn.active_mission and syn.active_mission.is_active:
        mission = syn.active_mission
        if mission.mission_type == mission_type:
            mission.current_value += amount
            if mission.current_value >= mission.target_value:
                # Mission Complete!
                mission.is_active = False
                syn.credits += mission.reward_credits
                syn.current_mission_id = None
                return f"[SIGACT] 🏆 Syndicate Mission Complete: {mission_type}! +{mission.reward_credits}c to the vault."
    return None

    async def active_powergen(self, name: str, network: str) -> tuple:
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return False, "System offline."
            if char.power >= 100.0: return False, "Power at maximum capacity."
            
            p_gain = 10.0
            char.power = min(100.0, char.power + p_gain)
            
            # Phase 7: Mission Hook
            if char.syndicate_id:
                await update_faction_mission(session, char.syndicate_id, "POWER", p_gain)
                
            await session.commit()
            return True, f"Manual power generation complete. (+{p_gain} uP)"

    async def active_training(self, name: str, network: str) -> tuple:
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return False, "System offline."
            if char.stability >= 100.0: return False, "Structural stability at maximum."
            
            s_gain = 5.0
            char.stability = min(100.0, char.stability + s_gain)
            await session.commit()
            return True, f"Training routine synchronized. Structural integrity improved. (+{s_gain}%)"

    async def tick_player_maintenance(self, network: str, idlers: list):
        """
        Handles periodic resource decay and recovery.
        - All players lose 1% stability per 'day' (scaled to the tick rate).
        - Idlers in Safezones or Own nodes recover Power and Stability.
        """
        async with self.async_session() as session:
            # 1. Background Stability Decay (Applied to everyone on this network)
            # scaled to approx 1% per 24h. If this runs hourly, it's 0.01 / 24 per tick.
            decay_rate = 0.01 / 24.0
            
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            result = await session.execute(stmt)
            characters = result.scalars().all()
            
            for char in characters:
                # Apply decay
                char.stability = max(0.0, char.stability - (char.stability * decay_rate))
                
                # 2. Recovery for Idlers
                if char.name in idlers:
                    node = char.current_node
                    is_safe = node and (node.node_type == 'safezone' or node.owner_character_id == char.id)
                    
                    if is_safe:
                        # Recover 5% Power and 2% Stability per hour
                        char.power = min(100.0, char.power + 5.0)
                        char.stability = min(100.0, char.stability + 2.0)
                    else:
                        # Recover 2% Power, 0.5% Stability in wilderness
                        char.power = min(100.0, char.power + 2.0)
                        char.stability = min(100.0, char.stability + 0.5)
            
            await session.commit()

    async def declare_war(self, nick: str, network: str, target_name: str) -> tuple:
        """Initiates a 72-hour war with another syndicate."""
        from models import Syndicate, SyndicateMember
        async with self.async_session() as session:
            stmt = select(Character).join(NetworkAlias).where(NetworkAlias.nickname == nick, NetworkAlias.network_name == network)
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.syndicate_id: return False, "You aren't in a Syndicate."
            
            # Check rank (Must be Rank 2+)
            m_stmt = select(SyndicateMember).where(SyndicateMember.character_id == char.id)
            member = (await session.execute(m_stmt)).scalars().first()
            if not member or member.rank < 2: return False, "Insufficient rank to declare war."
            
            # Find target
            t_stmt = select(Syndicate).where(Syndicate.name == target_name)
            target = (await session.execute(t_stmt)).scalars().first()
            if not target: return False, f"Syndicate '{target_name}' not found."
            if target.id == char.syndicate_id: return False, "You cannot declare war on yourself."
            
            source_syn = await session.get(Syndicate, char.syndicate_id)
            if source_syn.target_syndicate_id: return False, "You are already at war or in negotiations."
            
            # Initiate War
            war_end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=72)
            source_syn.target_syndicate_id = target.id
            source_syn.war_active_until = war_end
            source_syn.ceasefire_status = 'NONE'
            
            target.target_syndicate_id = source_syn.id
            target.war_active_until = war_end
            target.ceasefire_status = 'NONE'
            
            await session.commit()
            return True, f"WAR DECLARED: Conflict with {target_name} will persist for 72 hours."

    async def manage_ceasefire(self, nick: str, network: str, action: str) -> tuple:
        """Handle ceasefire proposals. Logic: If both propose, war ends."""
        from models import Syndicate, SyndicateMember
        async with self.async_session() as session:
            stmt = select(Character).join(NetworkAlias).where(NetworkAlias.nickname == nick, NetworkAlias.network_name == network)
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.syndicate_id: return False, "Fighter offline or unaffiliated."
            
            m_stmt = select(SyndicateMember).where(SyndicateMember.character_id == char.id)
            member = (await session.execute(m_stmt)).scalars().first()
            if not member or member.rank < 2: return False, "Admins only."
            
            syn = await session.get(Syndicate, char.syndicate_id)
            if not syn.target_syndicate_id: return False, "Not currently at war."
            
            target_syn = await session.get(Syndicate, syn.target_syndicate_id)
            
            if action == 'propose':
                syn.ceasefire_status = 'PROPOSED'
                if target_syn.ceasefire_status == 'PROPOSED':
                    # RESOLVE: Both agreed
                    target_name = target_syn.name
                    syn.target_syndicate_id = None
                    syn.war_active_until = None
                    syn.ceasefire_status = 'NONE'
                    target_syn.target_syndicate_id = None
                    target_syn.war_active_until = None
                    target_syn.ceasefire_status = 'NONE'
                    await session.commit()
                    return True, f"CEASEFIRE RATIFIED. Peace restored with {target_name}."
                else:
                    await session.commit()
                    return True, "Ceasefire proposal transmitted. Waiting for enemy response."
            elif action == 'reject':
                syn.ceasefire_status = 'NONE'
                target_syn.ceasefire_status = 'NONE'
                await session.commit()
                return True, "Ceasefire rejected. The conflict continues."
            return False, "Unknown diplomatic action."

    async def fortify_node(self, nick: str, network: str) -> tuple:
        """Upgrade node fortified_level using Syndicate pool (500 Power + 1000 Credits)."""
        from models import Syndicate, SyndicateMember, GridNode
        async with self.async_session() as session:
            stmt = select(Character).join(NetworkAlias).options(selectinload(Character.current_node)).where(NetworkAlias.nickname == nick, NetworkAlias.network_name == network)
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "Uplink failure."
            
            node = char.current_node
            if node.owner_alliance_id != char.syndicate_id: return False, "This node does not belong to your Syndicate."
            if node.fortified_level >= 5: return False, "Maximum fortification reached."
            
            syn = await session.get(Syndicate, char.syndicate_id)
            cost_pwr, cost_cred = 500.0, 1000.0
            if syn.power_stored < cost_pwr or syn.credits < cost_cred:
                return False, f"Insufficient Syndicate resources. Need {cost_pwr}u Power and {cost_cred}c Credits."
            
            syn.power_stored -= cost_pwr
            syn.credits -= cost_cred
            node.fortified_level += 1
            await session.commit()
            return True, f"Node {node.name} fortified to Level {node.fortified_level}."
