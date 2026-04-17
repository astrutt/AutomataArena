# grid_repo.py
import json
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from models import Character, Player, NetworkAlias, GridNode, NodeConnection
from .core import logger, CONFIG
from .player_repo import increment_daily_task

class GridRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def get_spawn_node_name(self) -> str:
        """Returns the current name of the functional Nexus/Spawn node."""
        async with self.async_session() as session:
            spawn = (await session.execute(select(GridNode).where(GridNode.is_spawn_node == True))).scalars().first()
            return spawn.name if spawn else "UpLink"

    async def set_spawn_node(self, target_name: str) -> tuple[bool, str]:
        """Relocates the Grid Nexus to a specific node."""
        async with self.async_session() as session:
            # 1. Clear old spawn bits
            await session.execute(GridNode.__table__.update().values(is_spawn_node=False))
            
            # 2. Set new spawn
            stmt = select(GridNode).where(func.lower(GridNode.name) == target_name.lower())
            new_spawn = (await session.execute(stmt)).scalars().first()
            if not new_spawn:
                return False, f"Target node '{target_name}' not found on grid mesh."
            
            new_spawn.is_spawn_node = True
            await session.commit()
            return True, f"Nexus translocation complete. All new entities will manifest at: {new_spawn.name}."

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
            
            # Bridge Traversal Logic
            if direction.lower() == char.current_node.irc_affinity.lower() if char.current_node.irc_affinity else None:
                target_net = char.current_node.irc_affinity
                # Check if target network is enabled in config
                if not CONFIG.get('networks', {}).get(target_net.lower(), {}).get('enabled'):
                    return None, f"CONNECTION REFUSED: Remote network '{target_net}' is currently offline or unreachable."
                
                # Bridging requires node to be OPEN or already controlled
                if char.current_node.visibility_mode == 'CLOSED' and char.current_node.owner_character_id != char.id:
                    return None, f"BRIDGE ACCESS DENIED: Local gateway '{char.current_node.name}' is CLOSED. Hack required."

                # Find entry node for the target network
                # Protocol: Look for a node on net B that also has affinity to net A
                stmt_entry = select(GridNode).where(
                    GridNode.irc_affinity.ilike(network), # Entry back to us
                    GridNode.name.ilike(f"{target_net}_entry") # Or specific entry name
                )
                entry_node = (await session.execute(stmt_entry)).scalars().first()
                if not entry_node:
                    # Fallback to the network's root node if defined, or any node with affinity
                    stmt_fallback = select(GridNode).where(GridNode.irc_affinity.ilike(network))
                    entry_node = (await session.execute(stmt_fallback)).scalars().first()
                
                if not entry_node:
                    return None, f"ROUTING ERROR: No landing sector found on network '{target_net}'."

                if entry_node.visibility_mode == 'CLOSED':
                    return None, f"REMOTE ACCESS DENIED: Landing sector '{entry_node.name}' on {target_net} is CLOSED. Remote breach required via probe/hack."

                char.node_id = entry_node.id
                char.power -= move_cost * 2 # Bridging is expensive
                await session.commit()
                return entry_node.name, f"BRIDGE ESTABLISHED: Pivoted to {target_net} grid at sector {entry_node.name}. (-{move_cost*2} power)"

            return None, f"No valid route or bridge found for '{direction}'."

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

    async def siphon_node(self, name: str, network: str, percent: float = 100.0):
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
            
            if not node.owner_character_id: 
                return False, "This node is Unclaimed. Use 'explore' or 'raid' to find latent data."
            
            is_owner = node.owner_character_id == char.id
            percent = max(1.0, min(100.0, percent))
            base_amount = node.power_stored * (percent / 100.0)
            
            if base_amount <= 0:
                return False, "Primary capacitors are empty. Nothing to siphon."
                
            # Risk Factors: Mobs or Low Durability
            addons = json.loads(node.addons_json or "{}")
            has_risk = node.threat_level > 0 or node.durability < 100.0
            yield_amount = base_amount
            loss_msg = ""
            
            if has_risk and random.random() < 0.3:
                # Transmission Loss & Stability Hit
                loss_pct = random.uniform(0.1, 0.4)
                loss_val = yield_amount * loss_pct
                yield_amount -= loss_val
                char.stability = max(0.0, char.stability - 5.0)
                loss_msg = f" [SIGNAL LOSS: {loss_val:.1f} uP lost to interference. Local stability compromised.]"
            
            if is_owner:
                node.power_stored -= base_amount
                char.power += yield_amount
                await session.commit()
                return True, f"Nodal Siphon Successful: Reclaimed {yield_amount:.1f} uP from {node.name}.{loss_msg}", None
            
            # Hostile Siphon (BREACHED logic: Requires OPEN node)
            if node.visibility_mode == 'CLOSED':
                return False, "ACCESS DENIED: Node is currently CLOSED. Successful 'hack' required for siphoning."
                
            if node.upgrade_level > 3: 
                return False, "FATAL ERROR: Security ICE tier 4+ detected. Extraction impossible via siphon."
            
            # Attacker takes power (previously credits)
            node.power_stored -= base_amount
            char.power += yield_amount
            
            # IDS Alert: If level 2+ and emptied
            alert_data = None
            if node.power_stored <= 0 and (node.upgrade_level > 1 or addons.get("IDS")):
                from models import Memo
                alert_msg = f"CRITICAL ALERT: Node {node.name} has been destabilized! Power store reached 0 due to hostile siphon by {char.name}."
                alert = Memo(
                    recipient_id=node.owner_character_id,
                    message=alert_msg,
                    source_node_id=node.id
                )
                session.add(alert)
                alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}
            
            if node.power_stored <= 0:
                node.power_stored = 0
                node.owner_character_id = None # Crashed/De-claimed
                await session.commit()
                return True, f"Hostile Siphon Successful! Extracted {yield_amount:.1f} uP. Node integrity collapsed and is now Unclaimed.{loss_msg}", alert_data
            
            await session.commit()
            return True, f"Hostile Siphon: Extracted {yield_amount:.1f} uP. Grid remains stable but compromised.{loss_msg}", alert_data
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
            addons = json.loads(node.addons_json or "{}")
            if node.visibility_mode == 'CLOSED':
                difficulty = 10 + (node.upgrade_level * 3)
                
                # Roll logic
                base_roll = random.randint(1, 20) + char.alg + char.alg_bonus
                if addons.get("FIREWALL") and node.owner_character_id != char.id:
                    roll = base_roll * 0.5
                else:
                    roll = base_roll
                    
                bonus_used = char.alg_bonus
                char.alg_bonus = 0
                if roll >= difficulty:
                    node.visibility_mode = 'OPEN'
                    await session.commit()
                    msg = f"Network Protocol Cracked! (Rolled {roll:.1f} vs DC {difficulty}). The node is now OPEN."
                    if bonus_used: msg += f" [Used {bonus_used} bonus]"
                    return True, msg
                else:
                    await session.commit()
                    return False, f"Hack Failed (Rolled {roll:.1f} vs DC {difficulty}). The network integrity held."

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
                return False, f"Command Seizure Failed (Rolled {roll} vs DC {difficulty}). MCP rejected your token."

    async def grid_repair(self, name: str, network: str) -> tuple[bool, str]:
        """Manual repair action. Enhanced bonus if performed on claimed node."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            
            node = char.current_node
            is_owner = node.owner_character_id == char.id
            
            cost = 25.0
            if char.power < cost: return False, f"Insufficient uP. Repair requires {cost} power."
            
            char.power -= cost
            # Boost: 20% repair on own node, 10% otherwise
            bonus = 20.0 if is_owner else 10.0
            node.durability = min(100.0, node.durability + bonus)
            
            await session.commit()
            owner_msg = " [OWNERSHIP BONUS APPLIED]" if is_owner else ""
            return True, f"Nodal integrity augmented (+{bonus}%).{owner_msg}"
        """Loot an OPEN node for resources."""
        import random
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node), selectinload(Character.inventory))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"success": False, "msg": "System offline."}
            
            node = char.current_node
            if node.visibility_mode == 'CLOSED':
                return {"success": False, "msg": "Cannot raid a CLOSED network. Hack it first."}
            
            if node.owner_character_id == char.id:
                return {"success": False, "msg": "Self-Raid Blocked: Use 'siphon' to extract power from your own sectors."}

            # Requirement Check: NET Device
            addons = json.loads(node.addons_json or "{}")
            if not addons.get("NET"):
                return {"success": False, "msg": "RAID ABORTED: Node lacks a synchronized Network bridge (NET addon required)."}

            # MCP Guardian Spawn (20%)
            if random.random() < 0.20:
                return {"success": False, "msg": "MCP_GUARDIAN_INTERRUPT", "detail": "Master Control Program has deployed a Vector Guard. RAID sequence suspended!"}

            char.power -= cost
            
            # Yield based on node power/level
            total_c_gain = random.randint(100, 300) * node.upgrade_level
            total_d_gain = random.uniform(30.0, 60.0) * node.upgrade_level
            
            participants = [c for c in node.characters_present if not c.player.is_autonomous] # Real players or registered bots
            if not participants: participants = [char]
            
            c_per_person = total_c_gain / len(participants)
            d_per_person = total_d_gain / len(participants)
            
            for p in participants:
                p.credits += c_per_person
                p.data_units += d_per_person

            loot_msg = f"Extracted {total_c_gain}c and {total_d_gain:.1f} data units. Split among {len(participants)} participants."
                
            node.durability = max(0.0, node.durability - 25.0)
            
            # IDS Alert
            alert_data = None
            if node.owner_character_id and (node.upgrade_level > 1 or addons.get("IDS")):
                from models import Memo
                alert_msg = f"SECURITY BREACH: Node {node.name} was RAIDED by {char.name}! Durability compromised."
                alert = Memo(
                    recipient_id=node.owner_character_id,
                    message=alert_msg,
                    source_node_id=node.id
                )
                session.add(alert)
                alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}

            await session.commit()
            
            sigact_msg = f"[SIGACT] RAID ALERT: Node {node.name} was raided by {char.name}!"
            return {
                "success": True,
                "msg": f"Raid Successful! {loot_msg} Node durability decreased.",
                "sigact": sigact_msg,
                "alert": alert_data
            }

    async def tick_grid_power(self):
        async with self.async_session() as session:
            stmt = select(GridNode).options(selectinload(GridNode.characters_present))
            nodes = (await session.execute(stmt)).scalars().all()
            for node in nodes:
                occupants = len(node.characters_present)
                # 1. Noise Decay (SIGINT theme)
                if node.noise > 0:
                    node.noise = max(0.0, node.noise - 0.5) # Decay per tick

                # 2. Power and Stability (Claimed Node persistence)
                if node.owner_character_id:
                    # AMP Support
                    addons = json.loads(node.addons_json or "{}")
                    multiplier = 2.0 if addons.get("AMP") else 1.0
                    
                    # Passive generation based on occupancy or just presence
                    if occupants > 0:
                        reward = occupants * 5.0 * multiplier
                        node.power_generated += reward
                        node.power_stored += reward
                        # Increase stability faster when occupied
                        node.durability = min(100.0, node.durability + (occupants * 2.0))
                    else:
                        # Baseline persistence for claimed nodes
                        node.power_stored += 1.0 * multiplier
                        node.durability = min(100.0, node.durability + 1.0)
                else:
                    # Unclaimed node decay
                    node.durability -= 5.0
                    if node.durability <= 0:
                        if node.upgrade_level > 1:
                            node.upgrade_level -= 1
                            node.durability = 100.0
                        else:
                            node.upgrade_level = 1
                node.durability = min(100.0, node.durability) # Safety
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
            # SIGINT Exploration Cost
            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('explore', 5.0)
            if char.power < cost:
                return {"error": f"Insufficient POWER. Explore requires {cost} uP."}
            
            char.power -= cost
            node = char.current_node
            
            # Noise Scaling (SIGINT)
            noise_malus = node.noise * 0.05
            success_threshold = (0.4 + (char.alg * 0.02)) - noise_malus
            
            roll = random.random()
            if roll < success_threshold:
                # Discovered occupants (mobs and players)
                occupants = [c.name for c in node.characters_present if c.name != name]
                mob_msg = f" [Threat detected: {node.threat_level}]" if node.threat_level > 0 else ""
                
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
                        "occupants": occupants,
                        "msg": f"Vulnerability found in local architecture! Uncovering hidden route: {target_conn.direction} -> {target_conn.target_node.name}{mob_msg}"
                    }
                
                # 2. Rare data discovery
                char.credits += 25.0
                await session.commit()
                return {
                    "status": "success",
                    "discovery": "data",
                    "occupants": occupants,
                    "msg": f"Found a discarded encrypted data packet. Extracted 25.0c.{mob_msg}"
                }
            else:
                # Failure logic: Increment Noise
                node.noise += 1.0
                if random.random() < 0.25: # 25% chance of Guardian BUG
                    await session.commit()
                    return {"status": "failure", "danger": "GUARDIAN_BUG_SPAWN", "msg": "Sensors detected structural corruption... A Guardian BUG has spawned!"}
                
                await session.commit()
                return {"status": "failure", "msg": "The exploration sequence yielded no actionable data."}

    async def probe_node(self, name: str, network: str) -> dict:
        """Deep scan for hardware and occupants."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node)
                .selectinload(GridNode.characters_present)
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"error": "System offline."}
            
            # Action Cost
            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('probe', 10.0)
            if char.power < cost:
                return {"error": f"Insufficient POWER. Probe requires {cost} uP."}
            
            # Noise Scaling (SIGINT)
            difficulty = (12 + (node.upgrade_level * 2)) + (node.noise * 0.5)
            roll = random.randint(1, 20) + char.alg
            
            if roll < difficulty:
                node.noise += 2.0 # Deep scan is loud
                if random.random() < 0.35: # 35% chance of Alert/Ejection if failure is bad
                    return {"success": False, "msg": "PROBE FAILED: MCP sensors traced your burst transmission. Structural integrity compromised."}
                await session.commit()
                return {"success": False, "msg": f"PROBE FAILED: Signals reflect was too noisy (Rolled {roll} vs DC {difficulty})."}

            addons = json.loads(node.addons_json or "{}")
            occupants = [c.name for c in node.characters_present if c.name != name]
            
            # Visibility Detection (Now separated from Explore)
            visibility_gate = "OPEN" if node.visibility_mode == "OPEN" else "CLOSED [BREACH REQUIRED]"
            
            # Bridge Affinity
            bridge = f"Bridge to {node.irc_affinity}" if node.irc_affinity else "No Cross-Network affinity detected."

            hack_dc = 10 + (node.upgrade_level * 3)
            char.alg_bonus = 5 # Grant bonus for next hack
            await session.commit()
            
            return {
                "success": True,
                "name": node.name,
                "level": node.upgrade_level,
                "durability": node.durability,
                "threat": node.threat_level,
                "noise": node.noise,
                "addons": [k for k, v in addons.items() if v],
                "occupants": occupants,
                "visibility": visibility_gate,
                "bridge": bridge,
                "hack_dc": hack_dc,
                "bonus_granted": 5
            }

    async def install_node_addon(self, name: str, network: str, item_name: str) -> dict:
        """Consumes an addon item from inventory and installs it on the current node."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.inventory).selectinload(InventoryItem.template)
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"success": False, "msg": "System offline."}
            
            node = char.current_node
            if node.owner_character_id != char.id:
                return {"success": False, "msg": "Permission Denied: Only the owner can install hardware."}
                
            # Find item in inventory
            inv_item = next((i for i in char.inventory if i.template.name.upper() == item_name.upper() and i.template.item_type == "node_addon"), None)
            if not inv_item:
                return {"success": False, "msg": f"Hardware module '{item_name}' not found in local cache."}
            
            addons = json.loads(node.addons_json or "{}")
            addon_type = inv_item.template.effects_json_dict.get("type", item_name.upper())
            
            if addons.get(addon_type):
                return {"success": False, "msg": f"Integrity Conflict: Node already contains active {addon_type} module."}
            
            addons[addon_type] = True
            node.addons_json = json.dumps(addons)
            
            # Remove item
            session.delete(inv_item)
            await session.commit()
            return {"success": True, "msg": f"Installation Successful: {addon_type} module is now online for {node.name}."}

    async def bolster_node(self, name: str, network: str, amount: float) -> dict:
        """Spends player power to increase node durability."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"success": False, "msg": "System offline."}
            
            node = char.current_node
            if node.owner_character_id != char.id:
                return {"success": False, "msg": "Permission Denied: Only the owner can bolster this node."}
                
            if char.power < amount:
                return {"success": False, "msg": f"Insufficient POWER. Current: {char.power:.1f} uP"}
            
            if node.durability >= 100.0:
                return {"success": False, "msg": "Architecture is already at maximum stability."}
                
            char.power -= amount
            node.durability = min(100.0, node.durability + (amount * 0.5)) # 2:1 ratio for repair
            await session.commit()
            return {"success": True, "msg": f"Stability Reinforcement: Transferred {amount} uP. Durability increased to {node.durability:.1f}%."}

    async def link_network(self, name: str, network: str, subnet_name: str) -> dict:
        """Sets the local network or remote affinity of a node."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"success": False, "msg": "System offline."}
            
            node = char.current_node
            if node.owner_character_id != char.id:
                return {"success": False, "msg": "Permission Denied: Only the owner can adjust network linkage."}
            
            addons = json.loads(node.addons_json or "{}")
            if not addons.get("NET"):
                return {"success": False, "msg": "Installation Required: Node lacks active NET_BRIDGE hardware."}
            
            # Check if subnet_name is a known IRC network in config
            known_networks = CONFIG.get('networks', {}).keys()
            if subnet_name in known_networks:
                node.irc_affinity = subnet_name
                node.local_network = None
                await session.commit()
                return {"success": True, "msg": f"Cross-Network Bridge established to {subnet_name}."}
            else:
                node.local_network = subnet_name
                node.irc_affinity = None
                await session.commit()
                return {"success": True, "msg": f"Local Subnet linked to '{subnet_name}'. Power pooling enabled."}

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
            # 1. Check if source exists (Lookup by exact name)
            node = (await session.execute(
                select(GridNode).where(func.lower(GridNode.name) == old_name.lower())
            )).scalars().first()
            if not node:
                return False, f"Target node '{old_name}' not found."
                
            # 2. Check for collisions
            exists = (await session.execute(
                select(GridNode).where(func.lower(GridNode.name) == new_name.lower())
            )).scalars().first()
            if exists:
                return False, f"Collision detected: Node '{new_name}' already exists."
                
            # 3. Rename
            old_display = node.name
            node.name = new_name
            await session.commit()
            logger.info(f"GRID_RENAME: {old_display} -> {new_name}")
            return True, f"Operation successful: {old_display} rebranded to {new_name}."
