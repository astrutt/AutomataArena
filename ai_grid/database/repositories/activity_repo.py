# database/repositories/activity_repo.py
import json
import datetime
from sqlalchemy.future import select
from sqlalchemy import func
from ai_grid.models import Character, Player, NetworkAlias, GridNode
from ai_grid.database.core import logger, increment_daily_task
from ai_grid.database.base_repo import BaseRepository

class ActivityRepository(BaseRepository):
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
            char = await self.get_character_by_nick(name, network, session)
            if not char: return False, "System offline."
            if char.stability >= 100.0: return False, "Structural stability at maximum."
            
            s_gain = 5.0
            char.stability = min(100.0, char.stability + s_gain)
            await session.commit()
            return True, f"Training routine synchronized. Structural integrity improved. (+{s_gain}%)"
