# ai_grid/database/repositories/incursion_repo.py
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from models import IncursionEvent, IncursionDefender, GridNode, Character
from ..base_repo import BaseRepository

logger = logging.getLogger("grid_db")

class IncursionRepository(BaseRepository):
    async def spawn_incursion(self, network: str, inc_type: str, tier: int, reward: float = 500.0, duration_mins: int = 5) -> dict | None:
        """Manifests a new Incursion Event on a random local node."""
        async with self.async_session() as session:
            # Select random non-safezone node on this network
            stmt = select(GridNode).where(
                GridNode.net_affinity == network,
                GridNode.node_type != 'safezone'
            ).order_by(func.random()).limit(1)
            
            node = (await session.execute(stmt)).scalars().first()
            if not node:
                return None
            
            expiry = datetime.now(timezone.utc) + timedelta(minutes=duration_mins)
            
            inc = IncursionEvent(
                node_id=node.id,
                network_name=network,
                incursion_type=inc_type,
                tier=tier,
                reward_val=reward,
                expires_at=expiry,
                status='ACTIVE'
            )
            session.add(inc)
            await session.commit()
            
            return {
                "node_name": node.name,
                "type": inc_type,
                "tier": tier,
                "reward": reward,
                "expiry": expiry
            }

    async def register_defense(self, char_name: str, network: str, node_name: str) -> tuple[bool, str, list[str]]:
        """Registers a player's defense against an active incursion and checks resolution."""
        async with self.async_session() as session:
            # Get character
            stmt_char = select(Character).where(Character.name == char_name)
            char = (await session.execute(stmt_char)).scalars().first()
            if not char:
                return False, "Character not found.", []
            
            # Get node
            stmt_node = select(GridNode).where(GridNode.name == node_name, GridNode.net_affinity == network)
            node = (await session.execute(stmt_node)).scalars().first()
            if not node:
                return False, "Target node not found on this network.", []
                
            # Find active incursion
            inc_stmt = select(IncursionEvent).where(
                IncursionEvent.node_id == node.id,
                IncursionEvent.status == 'ACTIVE',
                IncursionEvent.expires_at > datetime.now(timezone.utc)
            ).options(selectinload(IncursionEvent.defenders))
            
            inc = (await session.execute(inc_stmt)).scalars().first()
            if not inc:
                return False, "No active incursion detected at this coordinate.", []
                
            # Location Validation
            success, err_msg = await self.verify_presence(char, node, "defend")
            if not success:
                return False, err_msg, []
                
            # Check if already defended
            if any(d.character_id == char.id for d in inc.defenders):
                return False, f"You have already deployed defense protocols against the {inc.incursion_type}.", []
                
            # Register Defense
            defense = IncursionDefender(incursion_id=inc.id, character_id=char.id)
            session.add(defense)
            
            # Need to commit to refresh the defenders relationship accurately or just append to the list in memory
            inc.defenders.append(defense)
            
            current_defenders = len(inc.defenders)
            required = inc.tier
            
            if current_defenders >= required:
                # Resolve Incursion
                inc.status = 'RESOLVED'
                victors = []
                
                # Pay out rewards
                for d in inc.defenders:
                    # Refresh char reference? Better to query them
                    stmt_d_char = select(Character).where(Character.id == d.character_id)
                    d_char = (await session.execute(stmt_d_char)).scalars().first()
                    if d_char:
                        d_char.credits += inc.reward_val
                        victors.append(d_char.name)
                        
                msg = f"SUCCESS: The {inc.incursion_type} has been repelled! Vaulted {inc.reward_val:.1f}c."
                await session.commit()
                return True, msg, victors
            else:
                await session.commit()
                msg = f"Defense protocols engaged. Waiting for {required - current_defenders} more player(s) to repel {inc.incursion_type}."
                return True, msg, []

    async def expire_incursions(self, network: str, llm_client=None) -> list[str]:
        """Tails through expired incursions and handles flavor generation."""
        notifications = []
        async with self.async_session() as session:
            now = datetime.now(timezone.utc)
            stmt = select(IncursionEvent).where(
                IncursionEvent.network_name == network,
                IncursionEvent.status == 'ACTIVE',
                IncursionEvent.expires_at <= now
            ).options(selectinload(IncursionEvent.node))
            
            expired = (await session.execute(stmt)).scalars().all()
            
            for inc in expired:
                inc.status = 'EXPIRED'
                # Use LLM if defined to generate description
                flavor_text = f"The {inc.incursion_type} on {inc.node.name} dissipated into the net before full materialization."
                
                if llm_client:
                    try:
                        flavor_text = await llm_client.generate_incursion_flavor(inc.incursion_type, inc.node.name)
                    except Exception as e:
                        logger.error(f"Error generating incursion flavor: {e}")
                
                notifications.append(f"[GRID ALARM] {flavor_text}")
            
            await session.commit()
        return notifications
