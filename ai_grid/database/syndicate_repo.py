# syndicate_repo.py - v1.6.0
import datetime
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from models import Character, Player, NetworkAlias, Syndicate, SyndicateMember, GridNode, SyndicateMission
from .core import logger

RANK_LIMITS = {
    0: 250.0,   # Initiate
    1: 1000.0,  # Member
    2: 5000.0,  # Admin
    3: 100000.0 # Founder (virtually unlimited)
}

class SyndicateRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def create_syndicate(self, name: str, network: str, syn_name: str) -> (bool, str):
        """Found a new Syndicate for 5000c."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return False, "Character offline."
            if char.syndicate_id: return False, "You are already a member of a Syndicate."
            if char.credits < 5000: return False, "Founding a Syndicate costs 5000c."

            # Create Syndicate
            syn = Syndicate(name=syn_name, founder_id=char.id)
            session.add(syn)
            await session.flush()

            # Create Membership
            member = SyndicateMember(syndicate_id=syn.id, character_id=char.id, rank=3)
            session.add(member)
            
            char.credits -= 5000
            char.syndicate_id = syn.id
            
            await session.commit()
            return True, f"Syndicate '{syn_name}' founded! You are the Founder."

    async def join_syndicate(self, name: str, network: str, syn_name: str) -> (bool, str):
        """Join an existing Syndicate."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return False, "Character offline."
            if char.syndicate_id: return False, "You are already in a Syndicate."

            syn_stmt = select(Syndicate).where(Syndicate.name == syn_name)
            syn = (await session.execute(syn_stmt)).scalars().first()
            if not syn: return False, f"Syndicate '{syn_name}' not found."

            # For now, automated join. Future: Invitation tokens.
            member = SyndicateMember(syndicate_id=syn.id, character_id=char.id, rank=0)
            session.add(member)
            char.syndicate_id = syn.id
            
            await session.commit()
            return True, f"You have joined the '{syn_name}' Syndicate as an Initiate."

    async def store_power(self, name: str, network: str, amount: float) -> (bool, str):
        """Donate personal power to the Syndicate pool."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.syndicate_id: return False, "Syndicate membership required."
            if char.power < amount: return False, "Insufficient personal power."

            syn = await session.get(Syndicate, char.syndicate_id)
            if syn.power_stored + amount > syn.max_power:
                return False, f"Syndicate storage full. Max: {syn.max_power}u."

            char.power -= amount
            syn.power_stored += amount
            await session.commit()
            return True, f"Stashed {amount:.1f}u into Syndicate pool. New Total: {syn.power_stored:.1f}u."

    async def draw_power(self, name: str, network: str, amount: float) -> (bool, str):
        """Withdraw power from the Syndicate pool (subject to rank limits)."""
        async with self.async_session() as session:
            stmt = select(SyndicateMember).join(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(SyndicateMember.syndicate), selectinload(SyndicateMember.character))
            member = (await session.execute(stmt)).scalars().first()
            if not member: return False, "Syndicate membership required."

            syn = member.syndicate
            char = member.character
            if syn.power_stored < amount: return False, "Syndicate pool insufficient."

            # Daily Limit Check
            now = datetime.datetime.now(datetime.timezone.utc)
            if member.last_draw_date.date() < now.date():
                member.daily_power_withdrawn = 0.0
                member.last_draw_date = now

            limit = RANK_LIMITS.get(member.rank, 250.0)
            if member.daily_power_withdrawn + amount > limit:
                return False, f"Daily limit reached. Your rank allows {limit}u/day. Remaining: {max(0, limit - member.daily_power_withdrawn):.1f}u."

            syn.power_stored -= amount
            char.power += amount
            member.daily_power_withdrawn += amount
            
            await session.commit()
            return True, f"Withdrew {amount:.1f}u from Syndicate pool. Daily used: {member.daily_power_withdrawn:.1f}/{limit}u."

    async def get_syndicate_info(self, name: str, network: str) -> dict:
        """Get stats for the character's syndicate, including Phase 7 warfare telemetry."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.syndicate_id: return {"error": "No Syndicate found."}

            syn = await session.get(Syndicate, char.syndicate_id)
            members_stmt = select(SyndicateMember).where(SyndicateMember.syndicate_id == syn.id).options(selectinload(SyndicateMember.character))
            members = (await session.execute(members_stmt)).scalars().all()
            
            data = {
                "id": syn.id,
                "name": syn.name,
                "power": syn.power_stored,
                "max_power": syn.max_power,
                "credits": syn.credits,
                "member_count": len(members),
                "members": [{"name": m.character.name, "rank": m.rank} for m in members],
                "target_syndicate_name": None,
                "war_time_left": None,
                "ceasefire_status": syn.ceasefire_status,
                "enemy_proposed_ceasefire": False
            }

            if syn.target_syndicate_id:
                target = await session.get(Syndicate, syn.target_syndicate_id)
                if target:
                    data["target_syndicate_name"] = target.name
                    if target.ceasefire_status == 'PROPOSED':
                        data["enemy_proposed_ceasefire"] = True
                    
                if syn.war_active_until:
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if syn.war_active_until > now:
                        diff = syn.war_active_until - now
                        hours, remainder = divmod(diff.total_seconds(), 3600)
                        minutes, _ = divmod(remainder, 60)
                        data["war_time_left"] = f"{int(hours)}h {int(minutes)}m"
                    else:
                        # Auto-resolve expired war
                        syn.target_syndicate_id = None
                        syn.war_active_until = None
                        syn.ceasefire_status = 'NONE'
                        if target:
                            target.target_syndicate_id = None
                            target.war_active_until = None
                            target.ceasefire_status = 'NONE'
                        await session.commit()

            return data

    async def get_syndicate_mission(self, name: str, network: str) -> dict:
        """Fetch current active mission for the faction."""
        async with self.async_session() as session:
            stmt = select(Character).where(Character.name == name).options(selectinload(Character.syndicate))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.syndicate_id: return {"error": "Membership required."}
            
            syn = await session.get(Syndicate, char.syndicate_id)
            if not syn.current_mission_id: return {"active": False}
            
            from models import SyndicateMission
            mission = await session.get(SyndicateMission, syn.current_mission_id)
            if not mission or not mission.is_active: return {"active": False}
            
            return {
                "active": True,
                "mission": {
                    "type": mission.mission_type,
                    "target": mission.target_value,
                    "current": mission.current_value,
                    "reward": mission.reward_credits
                }
            }

    async def start_syndicate_mission(self, name: str, network: str) -> tuple:
        """Rank 2+ only. Initiates a random faction objective."""
        async with self.async_session() as session:
            stmt = select(SyndicateMember).join(Character).where(Character.name == name).options(selectinload(SyndicateMember.syndicate))
            member = (await session.execute(stmt)).scalars().first()
            if not member or member.rank < 2: return False, "Insufficient privileges."
            
            syn = member.syndicate
            if syn.current_mission_id: return False, "A mission is already active."
            
            import random
            from models import SyndicateMission
            m_types = [
                ("POWER", 5000.0, 2000.0),
                ("SABOTAGE", 10.0, 3500.0),
                ("MOB_SLAYER", 25.0, 1500.0)
            ]
            m_type, target, reward = random.choice(m_types)
            
            new_mission = SyndicateMission(
                syndicate_id=syn.id,
                mission_type=m_type,
                target_value=target,
                reward_credits=reward,
                expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)
            )
            session.add(new_mission)
            await session.flush()
            
            syn.current_mission_id = new_mission.id
            await session.commit()
            return True, f"Mission Accepted: {m_type}. Objective: {target} | Reward: {reward}c"

    async def list_syndicates(self) -> list:
        """Return a list of all syndicates."""
        async with self.async_session() as session:
            stmt = select(Syndicate).order_by(Syndicate.name.asc())
            result = await session.execute(stmt)
            syns = result.scalars().all()
            
            output = []
            for s in syns:
                from sqlalchemy import func
                m_stmt = select(func.count(SyndicateMember.id)).where(SyndicateMember.syndicate_id == s.id)
                count = (await session.execute(m_stmt)).scalar() or 0
                output.append({"name": s.name, "members": count, "power": s.power_stored})
            return output
