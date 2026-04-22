# ai_grid/database/repositories/pulse_repo.py
import random
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from ai_grid.models import PulseEvent, GridNode, Character
from ai_grid.database.base_repo import BaseRepository
from ai_grid.database.core import CONFIG

logger = logging.getLogger("grid_db")

class PulseRepository(BaseRepository):
    async def spawn_pulse(self, network: str) -> dict | None:
        """Manifests a new interactive Pulse on a random local node."""
        async with self.async_session() as session:
            # Select random non-safezone node on this network
            stmt = select(GridNode).where(
                GridNode.net_affinity == network,
                GridNode.node_type != 'safezone'
            ).order_by(func.random()).limit(1)
            
            node = (await session.execute(stmt)).scalars().first()
            if not node:
                return None
            
            # 10% base chance is handled by the loop caller, we just spawn here
            event_type = random.choice(['PACKET', 'GLITCH'])
            reward = round(random.uniform(200, 500) * node.upgrade_level, 2)
            
            # Duration from config or default 10m
            duration_mins = CONFIG.get('mechanics', {}).get('pulse_duration', 10)
            expiry = datetime.now(timezone.utc) + timedelta(minutes=duration_mins)
            
            pulse = PulseEvent(
                node_id=node.id,
                network_name=network,
                event_type=event_type,
                reward_val=reward,
                expires_at=expiry,
                status='ACTIVE'
            )
            session.add(pulse)
            await session.commit()
            
            return {
                "node_name": node.name,
                "type": event_type,
                "reward": reward,
                "expiry": expiry
            }

    async def resolve_pulse(self, char_name: str, network: str, node_name: str, action: str) -> tuple[bool, str]:
        """Validates and resolves an active Pulse interaction."""
        async with self.async_session() as session:
            # Get character
            stmt_char = select(Character).where(Character.name == char_name)
            char = (await session.execute(stmt_char)).scalars().first()
            if not char:
                return False, "Character not found."
            
            # Get target node
            stmt_node = select(GridNode).where(GridNode.name == node_name, GridNode.net_affinity == network)
            node = (await session.execute(stmt_node)).scalars().first()
            if not node:
                return False, "Target node not found on this network."
            
            # Find active pulse on this node
            pulse_stmt = select(PulseEvent).where(
                PulseEvent.node_id == node.id,
                PulseEvent.status == 'ACTIVE',
                PulseEvent.expires_at > datetime.now(timezone.utc)
            )
            pulse = (await session.execute(pulse_stmt)).scalars().first()
            
            if not pulse:
                return False, "No active signal or glitch detected at this coordinate."
            
            # Location Validation
            success, err_msg = await self.verify_presence(char, node, action)
            if not success:
                return False, err_msg
            
            # Command Validation
            # !a collect -> PACKET
            # !a patch -> GLITCH
            if action == 'collect' and pulse.event_type != 'PACKET':
                return False, f"Invalid Action: Targeting a {pulse.event_type} with 'collect' protocols."
            if action == 'patch' and pulse.event_type != 'GLITCH':
                return False, f"Invalid Action: Targeting a {pulse.event_type} with 'patch' protocols."
            
            # Success logic using v1.8.3 calibrated scaling
            pkg = self.calculate_mcp_rewards(char.level, action)
            char.credits += pkg['credits']
            char.data_units += pkg['data']
            await self.add_xp_to_char(char, pkg['xp'], session)
            
            p_type = "Data packet intercepted" if pulse.event_type == 'PACKET' else "Nodal glitch patched"
            msg = f"SUCCESS: {p_type}. Rewards: {pkg['credits']}c | {pkg['data']} Data | {pkg['xp']} XP."
            
            pulse.status = 'RESOLVED'
            await session.commit()
            return True, msg

    async def expire_pulses(self, network: str) -> list[str]:
        """Tials through expired pulses and applies penalties for missed glitches."""
        notifications = []
        async with self.async_session() as session:
            now = datetime.now(timezone.utc)
            stmt = select(PulseEvent).where(
                PulseEvent.network_name == network,
                PulseEvent.status == 'ACTIVE',
                PulseEvent.expires_at <= now
            ).options(selectinload(PulseEvent.node))
            
            expired = (await session.execute(stmt)).scalars().all()
            
            for pulse in expired:
                pulse.status = 'EXPIRED'
                if pulse.event_type == 'GLITCH':
                    # Penalty: Random node loses 25% power
                    target_stmt = select(GridNode).where(
                        GridNode.net_affinity == network,
                        GridNode.power_stored > 0
                    ).order_by(func.random()).limit(1)
                    
                    target_node = (await session.execute(target_stmt)).scalars().first()
                    if target_node:
                        loss = target_node.power_stored * 0.25
                        target_node.power_stored -= loss
                        notifications.append(f"CRITICAL: Unpatched glitch on {pulse.node.name} caused cascade failure! {target_node.name} lost {loss:.1f} uP.")
                    else:
                        notifications.append(f"WARNING: Glitch on {pulse.node.name} expired. Signal resonance dissipated.")
                else:
                    notifications.append(f"INFO: Data packet on {pulse.node.name} fragmented. Signal lost.")
            
            await session.commit()
        return notifications
