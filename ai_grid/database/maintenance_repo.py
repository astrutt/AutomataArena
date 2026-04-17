# ai_grid/database/maintenance_repo.py
import json
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from models import GridNode
from .core import logger
from .base_repo import BaseRepository

class MaintenanceRepository(BaseRepository):
    async def tick_grid_power(self):
        async with self.async_session() as session:
            stmt = select(GridNode).options(selectinload(GridNode.characters_present))
            nodes = (await session.execute(stmt)).scalars().all()
            for node in nodes:
                occupants = len(node.characters_present)
                # 1. Noise Decay
                if node.noise > 0:
                    node.noise = max(0.0, node.noise - 0.5)

                # 2. Power and Stability
                if node.owner_character_id:
                    addons = json.loads(node.addons_json or "{}")
                    multiplier = 2.0 if addons.get("AMP") else 1.0
                    
                    if occupants > 0:
                        reward = occupants * 5.0 * multiplier
                        node.power_generated += reward
                        node.power_stored += reward
                        node.durability = min(100.0, node.durability + (occupants * 2.0))
                    else:
                        node.power_stored += 1.0 * multiplier
                        node.durability = min(100.0, node.durability + 1.0)
                else:
                    node.durability -= 5.0
                    if node.durability <= 0:
                        if node.upgrade_level > 1:
                            node.upgrade_level -= 1
                            node.durability = 100.0
                        else:
                            node.upgrade_level = 1
                node.durability = min(100.0, node.durability)
            await session.commit()

    async def get_grid_telemetry(self) -> dict:
        """Returns aggregate metrics for the entire grid."""
        async with self.async_session() as session:
            all_nodes = (await session.execute(select(GridNode))).scalars().all()
            total_count = len(all_nodes)
            claimed_nodes = [n for n in all_nodes if n.owner_character_id is not None]
            total_power = sum(n.power_stored for n in all_nodes)
            total_gen = sum(n.power_generated for n in all_nodes)
            
            return {
                "total_nodes": total_count,
                "claimed_nodes": len(claimed_nodes),
                "total_power": total_power,
                "total_generation": total_gen,
                "claimed_percent": (len(claimed_nodes) / total_count * 100) if total_count > 0 else 0
            }
