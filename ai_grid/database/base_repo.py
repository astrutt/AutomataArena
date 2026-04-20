# ai_grid/database/base_repo.py
from sqlalchemy import func
from sqlalchemy.future import select
from models import Character, Player, NetworkAlias, GridNode
from sqlalchemy.orm import selectinload

class BaseRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def get_available_node_power(self, node, session) -> float:
        """Returns the specific node's power or the pooled power of its local network."""
        if not node.owner_character_id or not node.local_network:
            return node.power_stored
            
        # Sum power from all nodes in the same local network owned by the same player
        stmt = select(func.sum(GridNode.power_stored)).where(
            GridNode.owner_character_id == node.owner_character_id,
            GridNode.local_network == node.local_network
        )
        res = await session.execute(stmt)
        return res.scalar() or 0.0

    async def consume_node_power(self, node, amount: float, session) -> bool:
        """Deducts power from the node or the pool proportionately."""
        if not node.owner_character_id or not node.local_network:
            if node.power_stored < amount: return False
            node.power_stored -= amount
            return True
            
        # Get pool members
        stmt = select(GridNode).where(
            GridNode.owner_character_id == node.owner_character_id,
            GridNode.local_network == node.local_network
        )
        pool_nodes = (await session.execute(stmt)).scalars().all()
        total_pool = sum(n.power_stored for n in pool_nodes)
        if total_pool < amount: return False
        
        # Deduct proportionately or just sequentially
        remaining = amount
        for n in pool_nodes:
            can_take = min(remaining, n.power_stored)
            n.power_stored -= can_take
            remaining -= can_take
            if remaining <= 0: break
        return True
    async def get_character_by_nick(self, nick: str, network: str, session) -> Character:
        """Shared utility for resolving a nickname to a Character model within a session."""
        nick_lower = nick.lower()
        stmt = select(Character).join(Player).join(NetworkAlias).where(
            func.lower(Character.name) == nick_lower,
            func.lower(NetworkAlias.nickname) == nick_lower,
            NetworkAlias.network_name == network
        ).options(selectinload(Character.current_node))
        return (await session.execute(stmt)).scalars().first()

    async def verify_presence(self, char: Character, target_node, command_label: str) -> tuple[bool, str]:
        """ Standardizes physical presence checks for grid interactions.
            Allows remote interaction for specific commands (collect, defend, patch, repair).
        """
        remote_allowed = ['collect', 'defend', 'patch', 'repair']
        
        # If command is in the remote allowed list, bypass the presence check
        if command_label.lower() in remote_allowed:
            return True, ""
            
        # Verify physical presence
        if not char.node_id or char.node_id != target_node.id:
            return False, f"[GRID][SITREP] Physical presence required at {target_node.name} for {command_label.upper()} protocols."
            
        return True, ""
