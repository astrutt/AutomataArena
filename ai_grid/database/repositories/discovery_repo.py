# ai_grid/database/discovery_repo.py
import random
import json
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from sqlalchemy import func, update
from ai_grid.models import Character, Player, NetworkAlias, GridNode, NodeConnection, DiscoveryRecord, RaidTarget
from ai_grid.database.core import CONFIG
from ai_grid.database.base_repo import BaseRepository

class DiscoveryRepository(BaseRepository):
    async def explore_node(self, name: str, network: str) -> dict:
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node).selectinload(GridNode.exits).selectinload(NodeConnection.target_node),
                selectinload(Character.current_node).selectinload(GridNode.characters_present)
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"error": "System offline."}
            
            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('explore', 5.0)
            if char.power < cost: return {"error": f"Insufficient POWER. Explore requires {cost} uP."}
            
            char.power -= cost
            node = char.current_node
            
            # --- PERSISTENT DISCOVERY ---
            disc_stmt = select(DiscoveryRecord).where(DiscoveryRecord.character_id == char.id, DiscoveryRecord.node_id == node.id)
            if not (await session.execute(disc_stmt)).scalars().first():
                session.add(DiscoveryRecord(character_id=char.id, node_id=node.id, intel_level='EXPLORE'))

            noise_malus = node.noise * 0.05
            success_threshold = (0.4 + (char.alg * 0.02)) - noise_malus
            
            roll = random.random()
            if roll < success_threshold:
                occupants = [c.name for c in node.characters_present if c.name != name]

                
                # 1. Tiered Opening Logic
                is_simple = node.owner_character_id is None and node.upgrade_level == 1 and node.power_stored < 100
                if node.availability_mode == 'CLOSED' and is_simple:
                    node.availability_mode = 'OPEN'
                    msg = f"Vulnerability found in local architecture! System protocols breached. The node is now OPEN."
                    char.credits += 5.0
                    char.data_units += 1.0
                    await session.commit()
                    return {"status": "success", "discovery": "sector_open", "occupants": occupants, "msg": msg}

                # 2. Hidden connections
                hidden_conns = [c for c in node.exits if c.is_hidden]
                if hidden_conns:
                    target_conn = hidden_conns[0]
                    msg = f"Vulnerability found in local architecture! Uncovering hidden route: {target_conn.direction} -> {target_conn.target_node.name}"
                    char.credits += 10.0
                    char.data_units += 2.0
                    await session.commit()
                    return {"status": "success", "discovery": "hidden_exit", "target_node": target_conn.target_node.name, "direction": target_conn.direction, "occupants": occupants, "msg": msg}
                
                # 3. Rare data
                char.credits += 25.0
                
                # --- TASK 038: Procedural Raid Target Discovery ---
                if node.node_type == "void" and not node.active_target_id:
                    if random.random() < 0.25:
                        target_type = random.choice(["SMB", "EDU"])
                        new_target = RaidTarget(
                            node_id = node.id,
                            name = f"[{target_type}]",
                            target_type = target_type,
                            difficulty = 12 + (node.upgrade_level * 2),
                            credits_pool = 500.0 * node.upgrade_level,
                            data_pool = 100.0 * node.upgrade_level
                        )
                        session.add(new_target)
                        await session.flush()
                        node.active_target_id = new_target.id
                        await session.commit()
                        return {"status": "success", "discovery": "raid_target", "target": new_target.name, "occupants": occupants, "msg": f"Discovered an insecure local subnet: {new_target.name}. Resources detected."}

                await session.commit()
                return {"status": "success", "discovery": "data", "occupants": occupants, "msg": f"Found a discarded encrypted data packet. Extracted 25.0c."}
            else:
                node.noise += 1.0
                await session.commit()
                return {"status": "failure", "msg": "The exploration sequence yielded no actionable data."}

    async def probe_node(self, name: str, network: str, direction: str = None, target_name: str = None) -> dict:
        """Deep scan for hardware, occupants, or specific raid targets."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node).selectinload(GridNode.characters_present),
                selectinload(Character.current_node).selectinload(GridNode.exits).selectinload(NodeConnection.target_node),
                selectinload(Character.current_node).selectinload(GridNode.active_target)
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"success": False, "error": "System offline."}
            node = char.current_node
            
            # --- TARGET SELECTION ---
            raid_target = None
            if target_name:
                if node.active_target and (target_name.upper() in node.active_target.name.upper() or target_name.upper() == node.active_target.target_type):
                    raid_target = node.active_target
                else:
                    return {"success": False, "error": f"Target '{target_name}' not detected in local sector."}
            
            # --- SEQUENCE CHECK: Require EXPLORE before PROBE ---
            # If probing a target, check if node is explored first
            disc_check_stmt = select(DiscoveryRecord).where(DiscoveryRecord.character_id == char.id, DiscoveryRecord.node_id == node.id)
            existing_disc = (await session.execute(disc_check_stmt)).scalars().first()
            if not existing_disc:
                return {"success": False, "error": "Discovery Conflict: Node topology must be EXPLORED before deep probing."}
            
            # --- SECURITY PRE-CHECK (IDS) ---
            addons = json.loads(node.addons_json or "{}")
            is_owner = node.owner_character_id == char.id
            alert_data = None
            
            if not is_owner:
                from core.security_utils import is_action_hostile
                if is_action_hostile('probe', node.availability_mode):
                    if addons.get("IDS") or node.upgrade_level > 2:
                        from ai_grid.models import Memo
                        alert_msg = f"DEEP_PROBE_DETECTION TARGET:{node.name} {'(SUBSET:'+raid_target.name+')' if raid_target else ''} SOURCE:{char.name}"
                        session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
                        alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}
            
            # Change target node if direction specified
            if direction and not raid_target:
                conn = next((c for c in node.exits if c.direction.lower() == direction.lower()), None)
                if not conn: return {"success": False, "error": f"Invalid direction: '{direction}'."}
                if conn.is_hidden: return {"success": False, "error": f"Direction '{direction}' is not yet mapped."}
                node = conn.target_node
            
            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('probe', 10.0)
            if char.power < cost: return {"success": False, "error": "Insufficient POWER."}
            
            difficulty = (12 + (node.upgrade_level * 2)) + (char.current_node.noise * 0.5)
            if direction: difficulty += 3
            if raid_target: difficulty = raid_target.difficulty - 2 # Targets are slightly easier to probe than nodes
            
            roll = random.randint(1, 20) + char.alg
            if roll < difficulty:
                char.current_node.noise += 2.0
                if random.random() < 0.35:
                    return {"success": False, "msg": f"PROBE FAILED: MCP sensors traced your burst transmission."}
                await session.commit()
                return {"success": False, "msg": f"PROBE FAILED: Signals reflect too noisy."}

            # --- PERSISTENT DISCOVERY & TTL REFRESH ---
            duration = CONFIG.get('mechanics', {}).get('probe_duration_seconds', 3600)
            from datetime import timedelta
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration)
            
            if raid_target:
                # Target-specific DiscoveryRecord
                target_disc_stmt = select(DiscoveryRecord).where(DiscoveryRecord.character_id == char.id, DiscoveryRecord.raid_target_id == raid_target.id)
                existing_target_disc = (await session.execute(target_disc_stmt)).scalars().first()
                if existing_target_disc:
                    existing_target_disc.intel_level = 'PROBE'
                    existing_target_disc.intel_expires_at = expires_at
                else:
                    session.add(DiscoveryRecord(character_id=char.id, node_id=node.id, raid_target_id=raid_target.id, intel_level='PROBE', intel_expires_at=expires_at))
            else:
                # Node-specific DiscoveryRecord
                disc_stmt = select(DiscoveryRecord).where(DiscoveryRecord.character_id == char.id, DiscoveryRecord.node_id == node.id, DiscoveryRecord.raid_target_id == None)
                existing_disc = (await session.execute(disc_stmt)).scalars().first()
                if existing_disc:
                    existing_disc.intel_level = 'PROBE'
                    existing_disc.intel_expires_at = expires_at
                    existing_disc.discovered_at = datetime.now(timezone.utc)
                else:
                    session.add(DiscoveryRecord(character_id=char.id, node_id=node.id, intel_level='PROBE', intel_expires_at=expires_at))

            addons = json.loads(node.addons_json or "{}")
            occupants = [c.name for c in node.characters_present if c.name != name]
            
            is_moderate = node.owner_character_id is None and node.upgrade_level <= 2 and node.power_stored < 500
            if node.availability_mode == "CLOSED" and is_moderate:
                node.availability_mode = "OPEN"
                visibility_gate = "OPEN [BYPASS_PROBE]"
            else:
                visibility_gate = "OPEN" if node.availability_mode == "OPEN" else "CLOSED [BREACH REQUIRED]"
            
            if raid_target and raid_target.availability_mode == 'CLOSED' and is_moderate:
                raid_target.availability_mode = 'OPEN'

            # --- TASK 038: Deep Scan Raid Targets ---
            target_info = None
            if raid_target:
                target_info = {"name": raid_target.name, "type": raid_target.target_type, "difficulty": raid_target.difficulty, "status": raid_target.availability_mode}
            elif not node.active_target_id and random.random() < 0.40:
                t_tier = "DTC" if node.upgrade_level >= 4 else random.choice(["CORP", "MIL", "LEA", "ORG", "GOV"])
                new_target = RaidTarget(
                    node_id = node.id,
                    name = f"[{t_tier}]",
                    target_type = t_tier,
                    difficulty = 15 + (node.upgrade_level * 3),
                    credits_pool = 2000.0 * node.upgrade_level,
                    data_pool = 500.0 * node.upgrade_level
                )
                session.add(new_target)
                await session.flush()
                node.active_target_id = new_target.id
                target_info = {"name": new_target.name, "type": new_target.target_type, "difficulty": new_target.difficulty, "status": new_target.availability_mode}
            elif node.active_target_id:
                target_stmt = select(RaidTarget).where(RaidTarget.id == node.active_target_id)
                t = (await session.execute(target_stmt)).scalars().first()
                if t: target_info = {"name": t.name, "type": t.target_type, "difficulty": t.difficulty, "status": t.availability_mode}

            bridge = f"Bridge to {node.net_affinity}" if node.net_affinity else "No affinity detected."
            hack_dc = (raid_target.difficulty if raid_target else 10 + (node.upgrade_level * 3))
            char.alg_bonus = 5
            char.credits += 15.0
            char.data_units += 5.0
            await session.commit()
            
            return {
                "success": True, "name": raid_target.name if raid_target else node.name, 
                "level": node.upgrade_level, "durability": node.durability,
                "noise": node.noise, "addons": [k for k, v in addons.items() if v],
                "occupants": occupants, "visibility": visibility_gate, "bridge": bridge, "hack_dc": hack_dc, "bonus_granted": 5,
                "alert_data": alert_data, "raid_target": target_info
            }
