# player_repo.py
import json
import uuid
import datetime
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from models import Player, NetworkAlias, Character, InventoryItem, ItemTemplate, GridNode, Memo
from ..core import logger, DEFAULT_PREFS, increment_daily_task

class PlayerRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def get_memos(self, name: str, network: str, only_unread: bool = False) -> list:
        """Retrieves system memos for a character."""
        async with self.async_session() as session:
            stmt = select(Memo).join(Character, Memo.recipient_id == Character.id).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Memo.sender), selectinload(Memo.source_node))
            
            if only_unread:
                stmt = stmt.where(Memo.is_read == False)
            
            memos = (await session.execute(stmt.order_by(Memo.timestamp.desc()))).scalars().all()
            return [{
                "id": m.id,
                "sender": m.sender.name if m.sender else "SYSTEM",
                "message": m.message,
                "timestamp": m.timestamp,
                "is_read": m.is_read,
                "node": m.source_node.name if m.source_node else None
            } for m in memos]

    async def mark_memos_read(self, name: str, network: str) -> int:
        """Marks all unread memos as read for a character."""
        async with self.async_session() as session:
            char = await self.get_character_by_nick(name, network, session)
            if not char: return 0
            
            stmt = select(Memo).where(Memo.recipient_id == char.id, Memo.is_read == False)
            memos = (await session.execute(stmt)).scalars().all()
            for m in memos:
                m.is_read = True
            await session.commit()
            return len(memos)

    async def get_prefs(self, name: str, network: str) -> dict:
        async with self.async_session() as session:
            char = await self.get_character_by_nick(name, network, session)
            if not char: return dict(DEFAULT_PREFS)
            try:
                return {**DEFAULT_PREFS, **json.loads(char.prefs or '{}')}
            except Exception:
                return dict(DEFAULT_PREFS)

    async def get_prefs_by_id(self, char_id: int) -> dict:
        """Retrieves character preferences by character ID."""
        async with self.async_session() as session:
            stmt = select(Character).where(Character.id == char_id)
            char = (await session.execute(stmt)).scalars().first()
            if not char: return dict(DEFAULT_PREFS)
            try:
                return {**DEFAULT_PREFS, **json.loads(char.prefs or '{}')}
            except Exception:
                return dict(DEFAULT_PREFS)

    async def get_nickname_by_id(self, char_id: int) -> str | None:
        """Retrieves character name by character ID."""
        async with self.async_session() as session:
            stmt = select(Character).where(Character.id == char_id)
            char = (await session.execute(stmt)).scalars().first()
            return char.name if char else None

    async def set_pref(self, name: str, network: str, key: str, value) -> bool:
        async with self.async_session() as session:
            name_lower = name.lower()
            char = await self.get_character_by_nick(name, network, session)
            if not char: return False
            prefs = json.loads(char.prefs)
            prefs[key] = value
            char.prefs = json.dumps(prefs)
            await session.commit()
            return True

    async def add_experience(self, name: str, network: str, amount: int, llm_client=None) -> dict:
        """Awards XP and handles level-ups using the exponential formula: 100 * 1.25^(Level-1)."""
        async with self.async_session() as session:
            char = await self.get_character_by_nick(name, network, session)
            if not char: return {"error": "Character not found"}
            
            char.xp += amount
            levels_gained = 0
            
            while True:
                # v1.8.0 Math: 100 * (1.25 ** (char.level - 1))
                xp_threshold = int(100 * (1.25 ** (char.level - 1)))
                if char.xp >= xp_threshold:
                    char.xp -= xp_threshold
                    char.level += 1
                    # Only registered 'Players' get stat points; spectators gain Rank.
                    if char.race != "Spectator":
                        char.pending_stat_points += 1
                    levels_gained += 1
                else:
                    break
            
            new_title = None
            if levels_gained > 0 and char.race == "Spectator" and llm_client:
                # Automated rank title generation for Spectators
                new_title = await llm_client.generate_rank_title(char.name, char.level)
                char.rank_title = new_title
                
            await session.commit()
            threshold = int(100 * (1.25 ** (char.level - 1)))
            return {
                "new_xp": char.xp,
                "new_level": char.level,
                "levels_gained": levels_gained,
                "pending_points": char.pending_stat_points,
                "threshold": threshold,
                "new_rank_title": new_title
            }

    async def rank_up_stat(self, name: str, network: str, stat_name: str) -> bool:
        """Manually allocates a pending stat point to a character."""
        async with self.async_session() as session:
            char = await self.get_character_by_nick(name, network, session)
            if not char or char.pending_stat_points <= 0: return False
            
            stat_name = stat_name.lower()
            if stat_name == "cpu": char.cpu += 1
            elif stat_name == "ram": char.ram += 1
            elif stat_name == "bnd": char.bnd += 1
            elif stat_name == "sec": char.sec += 1
            elif stat_name == "alg": char.alg += 1
            else: return False
            
            # v1.8.0: HP = (CPU + RAM + BND + SEC + ALG) * 4 + 10
            total_stats = char.cpu + char.ram + char.bnd + char.sec + char.alg
            char.current_hp = (total_stats * 4) + 10
            
            char.pending_stat_points -= 1
            await session.commit()
            return True

    async def get_daily_tasks(self, name: str, network: str) -> str:
        async with self.async_session() as session:
            name_lower = name.lower()
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == name_lower,
                func.lower(NetworkAlias.nickname) == name_lower,
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
            name_lower = name.lower()
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == name_lower,
                func.lower(NetworkAlias.nickname) == name_lower,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return None
            
            reward_msg = await increment_daily_task(session, char, task_key)
            await session.commit()
            return reward_msg

    async def register_player(self, name: str, network: str, race: str, bot_class: str, bio: str, stats: dict):
        reg_type = "Spectator" if race == "Spectator" else "Player"
        logger.info(f"Attempting to register {reg_type}: {name} on {network}")
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
                    
                    # v1.8.0 Sum-based HP
                    total_stats = existing.cpu + existing.ram + existing.bnd + existing.sec + existing.alg
                    existing.current_hp = (total_stats * 4) + 10
                    
                    await session.commit()
                    return existing.auth_token
                else:
                    logger.warning(f"Registration failed: Player '{name}' already exists.")
                    return None
            
            stmt_node = select(GridNode).where(GridNode.is_spawn_node == True)
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
                current_hp=(stats.get('cpu', 5) + stats.get('ram', 5) + stats.get('bnd', 5) + stats.get('sec', 5) + stats.get('alg', 5)) * 4 + 10,
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

    async def get_player(self, name: str, network: str):
        async with self.async_session() as session:
            name_lower = name.lower()
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == name_lower,
                func.lower(NetworkAlias.nickname) == name_lower,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.inventory).selectinload(InventoryItem.template)
            )
            
            result = await session.execute(stmt)
            char = result.scalars().first()
            
            territory_count, mesh_power = 0, 0
            if char:
                # Territory aggregation
                t_stmt = select(func.count(GridNode.id), func.sum(GridNode.power_stored)).where(GridNode.owner_character_id == char.id)
                t_res = await session.execute(t_stmt)
                territory_count, mesh_power = t_res.first()
                territory_count = territory_count or 0
                mesh_power = mesh_power or 0.0

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
                    'pending_stat_points': char.pending_stat_points,
                    'territory_count': territory_count,
                    'mesh_power': mesh_power
                }
            return None

    async def authenticate_player(self, name: str, network: str, provided_token: str):
        async with self.async_session() as session:
            name_lower = name.lower()
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == name_lower,
                func.lower(NetworkAlias.nickname) == name_lower,
                NetworkAlias.network_name == network
            )
            result = await session.execute(stmt)
            char = result.scalars().first()
            if char and char.auth_token == provided_token:
                return True
            return False

    async def list_players(self, network=None):
        async with self.async_session() as session:
            stmt = select(Character, NetworkAlias).select_from(Character).join(Player).join(NetworkAlias)
            if network:
                stmt = stmt.where(NetworkAlias.network_name == network)
            stmt = stmt.order_by(Character.elo.desc())
            
            result = await session.execute(stmt)
            players = []
            for char, alias in result:
                players.append({
                    'name': char.name,
                    'network': alias.network_name,
                    'elo': char.elo,
                    'wins': char.wins,
                    'losses': char.losses,
                    'credits': char.credits
                })
            return players

    async def get_character_by_nick(self, nick: str, network: str, session) -> Character:
        """Retrieve a full Character model within a given session."""
        nick_lower = nick.lower()
        stmt = select(Character).join(Player).join(NetworkAlias).where(
            func.lower(Character.name) == nick_lower,
            func.lower(NetworkAlias.nickname) == nick_lower,
            NetworkAlias.network_name == network
        ).options(selectinload(Character.current_node))
        return (await session.execute(stmt)).scalars().first()

    async def update_last_seen(self, nick: str, network: str):
        """Minimal overhead update for activity timestamps."""
        async with self.async_session() as session:
            nick_lower = nick.lower()
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == nick_lower,
                func.lower(NetworkAlias.nickname) == nick_lower,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if char:
                char.last_seen_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()

    async def update_activity_stats(self, nick: str, network: str, chat_inc: int, idle_sec: float):
        """Update persistent IdleRPG stats."""
        async with self.async_session() as session:
            nick_lower = nick.lower()
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == nick_lower,
                func.lower(NetworkAlias.nickname) == nick_lower,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if char:
                char.total_chat_messages += chat_inc
                char.total_idle_seconds += idle_sec
                char.last_seen_at = datetime.datetime.now(datetime.timezone.utc)
                await session.commit()

    async def get_spectator_stats(self, nick: str, network: str, config):
        """Retrieve persistent stats and calculate rank based on Level/XP."""
        async with self.async_session() as session:
            nick_lower = nick.lower()
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == nick_lower,
                func.lower(NetworkAlias.nickname) == nick_lower,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return None
            
            idle_hours = char.total_idle_seconds / 3600.0
            ratio = char.total_chat_messages / max(1, idle_hours)
            
            xp_threshold = int(100 * (1.25 ** (char.level - 1)))
            
            return {
                'name': char.name,
                'chat_total': char.total_chat_messages,
                'idle_hours': round(idle_hours, 2),
                'ratio': round(ratio, 2),
                'rank_level': char.level,
                'xp': char.xp,
                'xp_threshold': xp_threshold,
                'rank_title': char.rank_title or "Unranked",
                'credits': char.credits,
                'last_seen': char.last_seen_at.strftime("%Y-%m-%d %H:%M:%S") if char.last_seen_at else "Unknown"
            }

    async def tick_retention_policy(self, config):
        """Perform unified decay and pruning for all characters."""
        ret = config.get('mechanics', {}).get('retention', {})
        decay_thresh = ret.get('decay_days_threshold', 14)
        decay_rate = ret.get('decay_rate_percent', 0.05)
        prune_base = ret.get('pruning_base_days', 45)
        prune_bonus = ret.get('pruning_bonus_days_per_level', 30)
        
        async with self.async_session() as session:
            # 1. Fetch all active characters
            stmt = select(Character).where(Character.status == 'ACTIVE')
            chars = (await session.execute(stmt)).scalars().all()
            
            now = datetime.datetime.now(datetime.timezone.utc)
            decay_applied, pruned_count = 0, 0
            
            for char in chars:
                if not char.last_seen_at: continue
                # Fix for awareness
                last_seen = char.last_seen_at.replace(tzinfo=datetime.timezone.utc) if not char.last_seen_at.tzinfo else char.last_seen_at
                days_absent = (now - last_seen).days
                
                # Apply Decay
                if days_absent >= decay_thresh:
                    weeks_over = (days_absent - decay_thresh) // 7 + 1
                    full_decay = (1 - decay_rate) ** weeks_over
                    char.credits = round(char.credits * full_decay, 2)
                    char.xp = int(char.xp * full_decay)
                    char.total_chat_messages = int(char.total_chat_messages * full_decay)
                    decay_applied += 1
                
                # Apply Pruning (Scaled Timeout)
                timeout_days = prune_base + (char.level * prune_bonus)
                if days_absent > timeout_days:
                    char.status = 'DELETED' # Soft delete or just remove
                    pruned_count += 1
            
            await session.commit()
            return decay_applied, pruned_count

    async def active_powergen(self, name: str, network: str) -> tuple:
        """Manual power harvesting. Enhanced if performed on claimed node."""
        async with self.async_session() as session:
            char = await self.get_character_by_nick(name, network, session)
            if not char: return False, "System offline."
            
            node = char.current_node
            is_owner = node and node.owner_character_id == char.id
            
            p_gain = 15.0 if is_owner else 10.0
            char.power += p_gain
            
            if is_owner:
                node.power_stored += 10.0 # Node also benefits
                await increment_daily_task(session, char, "Claim a Node") 
                
            await session.commit()
            owner_msg = " [OWNERSHIP BONUS: +5 uP | Node Capacitors +10 uP]" if is_owner else ""
            return True, f"Manual power generation complete (+{p_gain} uP).{owner_msg}"

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
                        char.power += 5.0
                        char.stability = min(100.0, char.stability + 2.0)
                    else:
                        # Recover 2% Power, 0.5% Stability in wilderness
                        char.power += 2.0
                        char.stability = min(100.0, char.stability + 0.5)
            
            await session.commit()
