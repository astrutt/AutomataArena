# ai_grid/database/discovery_repo.py
import random
import json
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from sqlalchemy import func, update
from models import Character, Player, NetworkAlias, GridNode, NodeConnection, DiscoveryRecord, RaidTarget
from ..core import CONFIG
from ..base_repo import BaseRepository

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
                mob_msg = "" # Threat display removed
                
                # 1. Tiered Opening Logic
                is_simple = node.owner_character_id is None and node.upgrade_level == 1 and node.power_stored < 100
                if node.availability_mode == 'CLOSED' and is_simple:
                    node.availability_mode = 'OPEN'
                    msg = f"Vulnerability found in local architecture! System protocols breached. The node is now OPEN.{mob_msg}"
                    char.credits += 5.0
                    char.data_units += 1.0
                    await session.commit()
                    return {"status": "success", "discovery": "sector_open", "occupants": occupants, "msg": msg}

                # 2. Hidden connections
                hidden_conns = [c for c in node.exits if c.is_hidden]
                if hidden_conns:
                    target_conn = hidden_conns[0]
                    msg = f"Vulnerability found in local architecture! Uncovering hidden route: {target_conn.direction} -> {target_conn.target_node.name}{mob_msg}"
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
                return {"status": "success", "discovery": "data", "occupants": occupants, "msg": f"Found a discarded encrypted data packet. Extracted 25.0c.{mob_msg}"}
            else:
                node.noise += 1.0
                if random.random() < 0.25:
                    await session.commit()
                    return {"status": "failure", "danger": "GUARDIAN_BUG_SPAWN", "msg": "Sensors detected structural corruption... A Guardian BUG has spawned!"}
                await session.commit()
                return {"status": "failure", "msg": "The exploration sequence yielded no actionable data."}

    async def probe_node(self, name: str, network: str, direction: str = None) -> dict:
        """Deep scan for hardware and occupants."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node).selectinload(GridNode.characters_present),
                selectinload(Character.current_node).selectinload(GridNode.exits)
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"success": False, "error": "System offline."}
            node = char.current_node
            
            # --- SEQUENCE CHECK: Require EXPLORE before PROBE (Task 021) ---
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
                        from models import Memo
                        alert_msg = f"DEEP_PROBE_DETECTION TARGET:{node.name} SOURCE:{char.name}"
                        session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
                        alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}
            
            if direction:
                conn = next((c for c in node.exits if c.direction.lower() == direction.lower()), None)
                if not conn: return {"success": False, "error": f"Invalid direction: '{direction}'."}
                if conn.is_hidden: return {"success": False, "error": f"Direction '{direction}' is not yet mapped."}
                node = conn.target_node
            
            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('probe', 10.0)
            if char.power < cost: return {"success": False, "error": "Insufficient POWER."}
            
            difficulty = (12 + (node.upgrade_level * 2)) + (char.current_node.noise * 0.5)
            if direction: difficulty += 3
            
            roll = random.randint(1, 20) + char.alg
            if roll < difficulty:
                char.current_node.noise += 2.0
                if random.random() < 0.35:
                    return {"success": False, "msg": f"PROBE FAILED: MCP sensors traced your burst transmission."}
                await session.commit()
                return {"success": False, "msg": f"PROBE FAILED: Signals reflect too noisy."}

            # --- PERSISTENT DISCOVERY & TTL REFRESH ---
            disc_stmt = select(DiscoveryRecord).where(DiscoveryRecord.character_id == char.id, DiscoveryRecord.node_id == node.id)
            existing_disc = (await session.execute(disc_stmt)).scalars().first()
            if existing_disc:
                existing_disc.intel_level = 'PROBE'
                existing_disc.discovered_at = datetime.now(timezone.utc) # Refresh TTL
            else:
                session.add(DiscoveryRecord(character_id=char.id, node_id=node.id, intel_level='PROBE'))

            addons = json.loads(node.addons_json or "{}")
            occupants = [c.name for c in node.characters_present if c.name != name]
            
            is_moderate = node.owner_character_id is None and node.upgrade_level <= 2 and node.power_stored < 500
            if node.availability_mode == "CLOSED" and is_moderate:
                node.availability_mode = "OPEN"
                visibility_gate = "OPEN [BYPASS_PROBE]"
            else:
                visibility_gate = "OPEN" if node.availability_mode == "OPEN" else "CLOSED [BREACH REQUIRED]"
            
            # --- TASK 038: Deep Scan Raid Targets ---
            target_info = None
            if not node.active_target_id and random.random() < 0.40:
                t_tier = "DC" if node.upgrade_level >= 4 else random.choice(["CORP", "MIL", "LEA", "ORG", "GOV"])
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
                target_info = {"name": new_target.name, "type": new_target.target_type, "difficulty": new_target.difficulty}
            elif node.active_target_id:
                target_stmt = select(RaidTarget).where(RaidTarget.id == node.active_target_id)
                t = (await session.execute(target_stmt)).scalars().first()
                if t: target_info = {"name": t.name, "type": t.target_type, "difficulty": t.difficulty}

            bridge = f"Bridge to {node.net_affinity}" if node.net_affinity else "No affinity detected."
            hack_dc = 10 + (node.upgrade_level * 3)
            char.alg_bonus = 5
            char.credits += 15.0
            char.data_units += 5.0
            await session.commit()
            
            return {
                "success": True, "name": node.name, "level": node.upgrade_level, "durability": node.durability,
                "noise": node.noise, "addons": [k for k, v in addons.items() if v],
                "occupants": occupants, "visibility": visibility_gate, "bridge": bridge, "hack_dc": hack_dc, "bonus_granted": 5,
                "alert_data": alert_data, "raid_target": target_info
            }
