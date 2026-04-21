# expansion_repo.py - v2.0 Grid Expansion logic
import json
import logging
from sqlalchemy import func
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from ..base_repo import BaseRepository
from models import Character, GridNode, Player, NetworkAlias

logger = logging.getLogger("grid_db")

class ExpansionRepository(BaseRepository):
    """
    Manages the expansion of the coordinate-based grid.
    Tracks population density and recommends sector unlocks.
    """
    
    async def get_expansion_telemetry(self):
        """Audit the grid for population density and unlock status."""
        async with self.async_session() as session:
            # 1. Total unlocked vs locked
            total_stmt = select(func.count(GridNode.id))
            total_count = (await session.execute(total_stmt)).scalar()
            
            unlocked_stmt = select(func.count(GridNode.id)).where(GridNode.is_unlocked == True)
            unlocked_count = (await session.execute(unlocked_stmt)).scalar()
            
            # 2. Population density per unlocked node
            char_count_stmt = select(func.count(Character.id))
            char_count = (await session.execute(char_count_stmt)).scalar()
            
            density = char_count / unlocked_count if unlocked_count > 0 else 0
            
            # 3. Identify clusters nearing capacity (Density > 2.0)
            # Find clusters where unlocked nodes are few but players are many
            cluster_stats = {}
            # This is complex in SQLite; we'll do a simplified cluster density check
            
            return {
                "total_nodes": total_count,
                "unlocked_nodes": unlocked_count,
                "player_count": char_count,
                "global_density": round(density, 2),
                "expansion_recommended": density > 1.5
            }

    async def manual_expand_sector(self, cluster_id: int = None):
        """
        Manually unlock all nodes in a priority cluster.
        If cluster_id is None, finds the next logical cluster.
        """
        async with self.async_session() as session:
            if cluster_id is None:
                # Find the first locked cluster with nodes
                stmt = select(GridNode.cluster_id).where(
                    GridNode.is_unlocked == False,
                    GridNode.cluster_id != None
                ).limit(1)
                cluster_id = (await session.execute(stmt)).scalar()
            
            if cluster_id is None:
                return False, "No locked clusters available for expansion."
            
            # Unlock the cluster
            update_stmt = select(GridNode).where(GridNode.cluster_id == cluster_id)
            nodes = (await session.execute(update_stmt)).scalars().all()
            for node in nodes:
                node.is_unlocked = True
            
            await session.commit()
            logger.info(f"GRID EXPANSION: Cluster {cluster_id} unlocked manually. ({len(nodes)} nodes)")
            return True, f"Sector Cluster {cluster_id} is now ONLINE. {len(nodes)} new coordinates reachable."
