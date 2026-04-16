# grid_repo.py
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from models import Character, Player, NetworkAlias, GridNode, NodeConnection
from .core import logger, CONFIG
from .player_repo import increment_daily_task

class GridRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def get_claimed_nodes(self, name: str, network: str) -> int:
        """Returns the count of nodes owned by a character."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return 0
            
            count_stmt = select(func.count(GridNode.id)).where(GridNode.owner_character_id == char.id)
            res = await session.execute(count_stmt)
            return res.scalar() or 0

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
                'is_hidden': node.is_hidden,
                'visibility_mode': node.visibility_mode,
                'irc_affinity': node.irc_affinity
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
            
            # Phase 2: Power Consumption
            move_cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('move', 1.0)
            if char.power < move_cost:
                return None, f"Insufficient POWER. Current: {char.power:.1f} / Need: {move_cost:.1f}"
            
            for conn in char.current_node.exits:
                if conn.direction.lower() == direction.lower():
                    # Phase 3: Visibility Check
                    if conn.target_node.visibility_mode == 'CLOSED':
                        return None, f"NETWORK ACCESS DENIED. Node '{conn.target_node.name}' is CLOSED. A system hack is required."
                    
                    char.node_id = conn.target_node_id
                    char.power -= move_cost
                    await session.commit()
                    return conn.target_node.name, f"Traversed {direction} to {conn.target_node.name}. (-{move_cost} power)"
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
            if char.credits < 100.0: return False, "You need 100c to recharge power."
            
            char.credits -= 100.0
            node.power_stored += 100.0
            await session.commit()
            
            return True, f"Grid recharged. (+100.0 uP) Current Store: {node.power_stored:.1f} uP."

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
            if node.owner_character_id == char.id and node.visibility_mode == 'OPEN': 
                return False, "You already command this node and its network is OPEN."
            
            # Phase 3: Priority - Crack Integrity
            if node.visibility_mode == 'CLOSED':
                difficulty = 10 + (node.upgrade_level * 3)
                roll = random.randint(1, 20) + char.alg + char.alg_bonus
                bonus_used = char.alg_bonus
                char.alg_bonus = 0
                if roll >= difficulty:
                    node.visibility_mode = 'OPEN'
                    await session.commit()
                    msg = f"Network Protocol Cracked! (Rolled {roll} vs DC {difficulty}). The node is now OPEN."
                    if bonus_used: msg += f" [Used {bonus_used} bonus]"
                    return True, msg
                else:
                    await session.commit()
                    return False, f"Hack Failed (Rolled {roll} vs DC {difficulty}). The network integrity held."

            # Ownership seizure logic (only if already OPEN)
            max_power = node.upgrade_level * 100
            if node.power_stored >= max_power * 0.9:
                return False, "PVE_GUARDIAN_SPAWN"
            
            roll = random.randint(1, 20) + char.alg + char.alg_bonus
            bonus_used = char.alg_bonus
            char.alg_bonus = 0
            difficulty = 10 + (node.upgrade_level * 2)
            
            if roll >= difficulty:
                old_owner = node.owner.name if node.owner else "Unknown"
                node.owner_character_id = char.id
                reward_msg = await increment_daily_task(session, char, "Claim a Node")
                    
                await session.commit()
                msg = f"System Command Seized! (Rolled {roll} vs DC {difficulty})."
                if bonus_used: msg += f" [Used {bonus_used} bonus]"
                if reward_msg: msg += f" {reward_msg}"
                return True, msg
            else:
                char.credits = max(0.0, char.credits - 50.0)
                await session.commit()
                return False, f"Command Seizure Failed (Rolled {roll} vs DC {difficulty}). ICE rejected your token."

    async def raid_node(self, name: str, network: str) -> dict:
        """Loot an OPEN node for resources."""
        import random
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"success": False, "msg": "System offline."}
            
            node = char.current_node
            if node.visibility_mode == 'CLOSED':
                return {"success": False, "msg": "Cannot raid a CLOSED network. Hack it first."}
            
            # Raid Cost
            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('hack', 3.0)
            if char.power < cost:
                return {"success": False, "msg": f"Insufficient POWER. Raid requires {cost} uP."}
            
            char.power -= cost
            
            # Yield based on node power/level
            # 10% chance for Data Shard, always a few credits and raw data
            loot_msg = ""
            c_gain = random.randint(10, 50) * node.upgrade_level
            d_gain = random.uniform(5.0, 15.0) * node.upgrade_level
            char.credits += c_gain
            char.data_units += d_gain
            loot_msg = f"Extracted {c_gain}c and {d_gain:.1f} data from local buffers."
            
            if random.random() < 0.2:
                # Give a Data Shard (item)
                # For now just increment a counter or add to inventory if items exist
                loot_msg += " Found 1x [Data_Shard]."
                
            node.durability = max(0.0, node.durability - 10.0)
            await session.commit()
            
            sigact_msg = f"[SIGACT] RAID ALERT: Node {node.name} was raided by {char.name}!"
            return {
                "success": True,
                "msg": f"Raid Successful! {loot_msg} Node durability decreased.",
                "sigact": sigact_msg
            }

    async def tick_grid_power(self):
        async with self.async_session() as session:
            stmt = select(GridNode).options(selectinload(GridNode.characters_present))
            nodes = (await session.execute(stmt)).scalars().all()
            for node in nodes:
                occupants = len(node.characters_present)
                if node.owner_character_id:
                    if occupants > 0:
                        generated = occupants * 5.0
                        node.power_generated += generated
                        node.power_stored += generated
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

    async def explore_node(self, name: str, network: str) -> dict:
        import random
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node).selectinload(GridNode.exits).selectinload(NodeConnection.target_node)
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"error": "System offline."}
            
            # Phase 3 Exploration Cost
            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('explore', 5.0)
            if char.power < cost:
                return {"error": f"Insufficient POWER. Explore requires {cost} uP."}
            
            char.power -= cost
            node = char.current_node
            
            roll = random.random()
            success_threshold = 0.4 + (char.alg * 0.02) # Higher Alg helps discovery
            
            if roll < success_threshold:
                # 1. Look for hidden connections
                hidden_conns = [c for c in node.exits if c.is_hidden]
                if hidden_conns:
                    target_conn = random.choice(hidden_conns)
                    target_conn.is_hidden = False
                    await session.commit()
                    return {
                        "status": "success",
                        "discovery": "hidden_exit",
                        "target_node": target_conn.target_node.name,
                        "direction": target_conn.direction,
                        "msg": f"Vulnerability found in local architecture! Uncovering hidden route: {target_conn.direction} -> {target_conn.target_node.name}"
                    }
                
                # 2. Look for Foreign Hub affinity
                if node.irc_affinity:
                    return {
                        "status": "success",
                        "discovery": "irc_bridge",
                        "affinity": node.irc_affinity,
                        "msg": f"Foreign signal detected... This node appears to be a bridge to {node.irc_affinity}."
                    }
                
                # 3. Rare data discovery
                char.credits += 25.0
                await session.commit()
                return {
                    "status": "success",
                    "discovery": "data",
                    "msg": "Found a discarded encrypted data packet. Extracted 25.0c."
                }
            else:
                # Failure logic
                if random.random() < 0.25: # 25% chance of Grid Bug
                    return {"status": "failure", "danger": "GRID_BUG_SPAWN", "msg": "Sensors detected structural corruption... A Grid Bug has spawned!"}
                
                await session.commit()
                return {"status": "failure", "msg": "The exploration sequence yielded no actionable data."}

    async def get_grid_telemetry(self) -> dict:
        """Returns aggregate metrics for the entire grid."""
        async with self.async_session() as session:
            # 1. Total Nodes vs Claimed
            all_nodes = (await session.execute(select(GridNode))).scalars().all()
            total_count = len(all_nodes)
            claimed_nodes = [n for n in all_nodes if n.owner_character_id is not None]
            
            # 2. Total Power Mesh
            total_power = sum(n.power_stored for n in all_nodes)
            total_gen = sum(n.power_generated for n in all_nodes)
            
            return {
                "total_nodes": total_count,
                "claimed_nodes": len(claimed_nodes),
                "total_power": total_power,
                "total_generation": total_gen,
                "claimed_percent": (len(claimed_nodes) / total_count * 100) if total_count > 0 else 0
            }
    async def rename_node(self, old_name: str, new_name: str) -> tuple[bool, str]:
        """Admin-only: Renames a node. Subject to 11-char limit."""
        if len(new_name) > 11:
            return False, f"Name length violation: {len(new_name)}/11 characters max."
            
        async with self.async_session() as session:
            # 1. Check if source exists
            node = (await session.execute(
                select(GridNode).where(GridNode.name == old_name)
            )).scalars().first()
            if not node:
                return False, f"Target node '{old_name}' not found."
                
            # 2. Check for collisions
            exists = (await session.execute(
                select(GridNode).where(GridNode.name == new_name)
            )).scalars().first()
            if exists:
                return False, f"Collision detected: Node '{new_name}' already exists."
                
            # 3. Rename
            node.name = new_name
            await session.commit()
            logger.info(f"GRID_RENAME: {old_name} -> {new_name}")
            return True, f"Operation successful: {old_name} rebranded to {new_name}."
