import asyncio
import os
import sys
import json

# Root inclusion
sys.path.append('ai_grid')
import grid_db
from database.core import CONFIG
from models import Character, Player, NetworkAlias, GridNode, ItemTemplate

# Mock config for networks
CONFIG['networks'] = {
    'localnet': {'enabled': True},
    'remotenet': {'enabled': True}
}

async def audit_uplink_bridge():
    db = grid_db.ArenaDB()
    print("\n[QA] UPLINK BRIDGE AUDIT (TASK 021)")
    
    # Pre-test Cleanup
    async with db.async_session() as session:
        await session.execute(grid_db.text("DELETE FROM grid_nodes WHERE name LIKE 'QA_GATEWAY_%'"))
        await session.execute(grid_db.text("DELETE FROM players WHERE global_name = 'qa_bridge_admin'"))
        await session.commit()

    # 1. Setup Environment
    async with db.async_session() as session:
        # Gateway Alpha (Local) -> Points to RemoteNet
        alpha = GridNode(name="QA_GATEWAY_ALPHA", node_type="safezone", net_affinity="RemoteNet", addons_json='{}')
        session.add(alpha)
        # Gateway Beta (Remote) -> Points to localnet
        beta = GridNode(name="QA_GATEWAY_BETA", node_type="safezone", net_affinity="localnet", addons_json='{}')
        session.add(beta)
        await session.commit() # Persistent and assigned IDs
        
    async with db.async_session() as session:
        # Setup Character
        p = Player(global_name="qa_bridge_admin")
        session.add(p)
        await session.flush()
        
        # Link to alpha (refetched for ID safety)
        alpha_id = (await session.execute(grid_db.select(GridNode).where(GridNode.name == "QA_GATEWAY_ALPHA"))).scalars().first().id
        char = Character(name="QA_BRIDGE_ADMIN", player_id=p.id, power=100.0, node_id=alpha_id, race="Ghost", char_class="Admin")
        session.add(char)
        alias = NetworkAlias(player_id=p.id, nickname="QA_BRIDGE_ADMIN", network_name="localnet")
        session.add(alias)
        await session.commit()

    print("\n[TEST 1] Missing NET_BRIDGE Hardware")
    # Attempt to bridge without hardware
    res1, msg1 = await db.navigation.move_player("QA_BRIDGE_ADMIN", "localnet", "RemoteNet")
    print(f" > Attempt Bridge: {msg1}")
    if "BRIDGE OFFLINE" in msg1:
        print("   SUCCESS: Hardware gating enforced.")
    else:
        print("   FAILURE: Bridging bypassed hardware requirement.")

    print("\n[TEST 2] Insufficient Power")
    # Add hardware but set power to low
    async with db.async_session() as session:
        node = (await session.execute(grid_db.select(GridNode).where(GridNode.name == "QA_GATEWAY_ALPHA"))).scalars().first()
        node.addons_json = json.dumps({"NET": True})
        char = (await session.execute(grid_db.select(Character).where(Character.name == "QA_BRIDGE_ADMIN"))).scalars().first()
        char.power = 1.0 # Requires 2 units (default move is 1.0 * 2)
        await session.commit()
    
    res2, msg2 = await db.navigation.move_player("QA_BRIDGE_ADMIN", "localnet", "RemoteNet")
    print(f" > Attempt Bridge: {msg2}")
    if "Insufficient POWER" in msg2:
        print("   SUCCESS: Power cost (2x) enforced.")
    else:
        print("   FAILURE: Bridge cost bypassed.")

    print("\n[TEST 3] Successful Bridge Jump")
    # Set power to high and attempt jump
    async with db.async_session() as session:
        char = (await session.execute(grid_db.select(Character).where(Character.name == "QA_BRIDGE_ADMIN"))).scalars().first()
        char.power = 100.0
        await session.commit()
        
    res3, msg3 = await db.navigation.move_player("QA_BRIDGE_ADMIN", "localnet", "RemoteNet")
    print(f" > Attempt Bridge: {msg3}")
    if res3 == "QA_GATEWAY_BETA" and "BRIDGE ESTABLISHED" in msg3:
        print("   SUCCESS: Tactical bridge established. Network pivot verified.")
    else:
        print("   FAILURE: Bridge jump failed or routed incorrectly.")

    # Cleanup
    async with db.async_session() as session:
        await session.execute(grid_db.text("DELETE FROM grid_nodes WHERE name LIKE 'QA_GATEWAY_%'"))
        await session.execute(grid_db.text("DELETE FROM players WHERE global_name = 'qa_bridge_admin'"))
        await session.commit()

if __name__ == "__main__":
    asyncio.run(audit_uplink_bridge())
