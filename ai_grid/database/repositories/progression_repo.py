# database/repositories/progression_repo.py
from sqlalchemy.future import select
from models import Character
from ..base_repo import BaseRepository

class ProgressionRepository(BaseRepository):
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

    async def get_spectator_stats(self, nick: str, network: str, config):
        """Retrieve persistent stats and calculate rank based on Level/XP."""
        async with self.async_session() as session:
            char = await self.get_character_by_nick(nick, network, session)
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
