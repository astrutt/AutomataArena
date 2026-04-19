import asyncio
import sys
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

# Root inclusion
sys.path.append('ai_grid')
import grid_db
from models import Character, Player, NetworkAlias, GridNode

async def debug_bridge_state():
    db = grid_db.ArenaDB()
    async with db.async_session() as session:
        # Load character exactly as the repo does
        stmt = select(Character).join(Player).join(NetworkAlias).where(
            Character.name == "QA_BRIDGE_ADMIN",
            NetworkAlias.network_name == "localnet"
        ).options(
            selectinload(Character.current_node)
        )
        char = (await session.execute(stmt)).scalars().first()
        if not char:
            print("ERROR: Character not found.")
            return
        
        print(f"Character: {char.name}")
        print(f"Node ID: {char.node_id}")
        if char.current_node:
            print(f"Node Name: {char.current_node.name}")
            print(f"Node NetAffinity: {char.current_node.net_affinity}")
            print(f"Node IRCAffinity (stale?): {getattr(char.current_node, 'irc_affinity', 'MISSING')}")
        else:
            print("ERROR: Character has no current_node relationship!")

if __name__ == "__main__":
    asyncio.run(debug_bridge_state())
