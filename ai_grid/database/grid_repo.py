# grid_repo.py
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from models import Character, Player, NetworkAlias, GridNode, NodeConnection
from .core import logger
from .player_repo import increment_daily_task

class GridRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def get_location(self, name: str, network: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node)
                .selectinload(GridNode.exits)
                .selectinload(NodeConnection.target_node),
                selectinload(Character.current_node)
                .selectinload(GridNode.owner)
            )
            result = await session.execute(stmt)
            char = result.scalars().first()
            if not char:
                return None
            node = char.current_node
            if not node:
                return None
            exits = [f"{c.direction} -> {c.target_node.name}" for c in node.exits]
            return {
                'name': node.name,
                'description': node.description,
                'type': node.node_type,
                'node_type': node.node_type,
                'exits': exits,
                'credits': char.credits,
                'level': char.level,
                'power_stored': node.power_stored,
                'power_consumed': node.power_consumed,
                'power_generated': node.power_generated,
                'owner': node.owner.name if node.owner else "Unclaimed",
                'upgrade_level': node.upgrade_level,
                'durability': node.durability,
                'threat_level': node.threat_level,
            }

    async def move_fighter(self, name: str, network: str, direction: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node)
                .selectinload(GridNode.exits)
                .selectinload(NodeConnection.target_node)
            )
            result = await session.execute(stmt)
            char = result.scalars().first()
            if not char: return None, "System offline."
            if not char.current_node: return None, "You are floating in the void."
            
            for conn in char.current_node.exits:
                if conn.direction.lower() == direction.lower():
                    char.node_id = conn.target_node_id
                    await session.commit()
                    return conn.target_node.name, f"Traversed {direction} to {conn.target_node.name}."
            return None, f"No valid route found for '{direction}'."

    async def move_fighter_to_node(self, name: str, network: str, node_name: str) -> bool:
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == name.lower(),
                func.lower(NetworkAlias.nickname) == name.lower(),
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char:
                return False
            node = (await session.execute(
                select(GridNode).where(GridNode.name == node_name)
            )).scalars().first()
            if not node:
                return False
            char.node_id = node.id
            await session.commit()
            return True

    async def grid_repair(self, name: str, network: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            
            node = char.current_node
            if not node.owner_character_id: return False, "You cannot repair unclaimed wilderness."
            if node.durability >= 100.0: return False, "Grid is already at maximum durability."
            if char.credits < 100.0: return False, "You need 100c to repair the node."
            
            char.credits -= 100.0
            node.durability = 100.0
            reward_msg = await increment_daily_task(session, char, "Repair a Node")
            await session.commit()
            
            msg = "Grid repaired to 100% durability."
            if reward_msg: msg += f" {reward_msg}"
            return True, msg

    async def grid_recharge(self, name: str, network: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            
            node = char.current_node
            if not node.owner_character_id: return False, "You cannot recharge unclaimed wilderness."
            max_power = node.upgrade_level * 100.0
            if node.power_stored >= max_power: return False, "Grid power is already at maximum."
            if char.credits < 100.0: return False, "You need 100c to recharge power."
            
            char.credits -= 100.0
            node.power_stored = max_power
            await session.commit()
            
            return True, f"Grid recharged to MAX ({max_power} uP)."

    async def claim_node(self, name: str, network: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            node = char.current_node
            
            if node.owner_character_id:
                if node.owner_character_id == char.id:
                    return False, "You already command this node."
                return False, "This node is controlled by a rival. You must seize it."
                
            node.owner_character_id = char.id
            node.power_stored = 100.0
            node.durability = 100.0
            
            reward_msg = await increment_daily_task(session, char, "Claim a Node")
            await session.commit()
            msg = f"Control established over {node.name}."
            if reward_msg: msg += f" {reward_msg}"
            return True, msg

    async def upgrade_node(self, name: str, network: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            node = char.current_node
            if node.owner_character_id != char.id: return False, "You do not command this node."
            
            cost = node.upgrade_level * 500
            if char.credits < cost: return False, f"Insufficient credits. Upgrade requires {cost}c."
            
            char.credits -= cost
            node.upgrade_level += 1
            await session.commit()
            return True, f"Upgraded {node.name} to Level {node.upgrade_level} for {cost}c! Max Capacity increased."

    async def siphon_node(self, name: str, network: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            node = char.current_node
            
            if not node.owner_character_id: return False, "Node is already Unclaimed."
            if node.owner_character_id == char.id: return False, "You cannot siphon your own node."
            if node.upgrade_level > 2: return False, "Cannot siphon a heavily upgraded node. Security ICE is too high."
            
            siphon_amount = min(50.0, node.power_stored)
            node.power_stored -= siphon_amount
            char.credits += siphon_amount * 2 
            
            if node.power_stored <= 0:
                node.power_stored = 0
                node.owner_character_id = None
                await session.commit()
                return True, f"You siphoned {siphon_amount} power and crashed the grid. The node is now Unclaimed."
                
            await session.commit()
            return True, f"You siphoned {siphon_amount} power. The node is destabilizing."

    async def hack_node(self, name: str, network: str):
        import random
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node).selectinload(GridNode.owner))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            node = char.current_node
            
            if not node.owner_character_id: return False, "Node is Unclaimed."
            if node.owner_character_id == char.id: return False, "You already own this node."
            
            max_power = node.upgrade_level * 100
            if node.power_stored >= max_power * 0.9:
                return False, "PVE_GUARDIAN_SPAWN"
            
            roll = random.randint(1, 20) + char.alg
            difficulty = 10 + (node.upgrade_level * 2)
            
            if roll >= difficulty:
                old_owner = node.owner.name if node.owner else "Unknown"
                node.owner_character_id = char.id
                reward_msg = await increment_daily_task(session, char, "Claim a Node")
                await session.commit()
                msg = f"Hack Successful (Rolled {roll} vs DC {difficulty}). You violently stripped command from {old_owner}!"
                if reward_msg: msg += f" {reward_msg}"
                return True, msg
            else:
                char.credits = max(0.0, char.credits - 50.0)
                await session.commit()
                return False, f"Hack Failed (Rolled {roll} vs DC {difficulty}). The ICE rejected your intrusion and fined you 50c."

    async def tick_grid_power(self):
        async with self.async_session() as session:
            stmt = select(GridNode).options(selectinload(GridNode.characters_present))
            nodes = (await session.execute(stmt)).scalars().all()
            for node in nodes:
                occupants = len(node.characters_present)
                if node.owner_character_id:
                    if occupants > 0:
                        generated = occupants * 5.0
                        max_power = node.upgrade_level * 100.0
                        node.power_generated += generated
                        node.power_stored = min(max_power, node.power_stored + generated)
                        node.durability = min(100.0, node.durability + (occupants * 2.0))
                    else:
                        node.durability -= 5.0
                        if node.durability <= 0:
                            if node.upgrade_level > 1:
                                node.upgrade_level -= 1
                                node.durability = 100.0
                            else:
                                node.owner_character_id = None
                                node.upgrade_level = 1
                                node.durability = 100.0
            await session.commit()
