# ai_grid/database/infiltration_repo.py
import random
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from models import Character, Player, NetworkAlias, GridNode, BreachRecord, Memo, InventoryItem, DiscoveryRecord
from ..core import CONFIG, increment_daily_task
from ..base_repo import BaseRepository

class InfiltrationRepository(BaseRepository):
    async def siphon_node(self, name: str, network: str, percent: float = 100.0) -> tuple:
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node).selectinload(GridNode.owner))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            node = char.current_node
            
            # Availability Check: Owner bypass
            disc_stmt = select(DiscoveryRecord).where(DiscoveryRecord.character_id == char.id, DiscoveryRecord.node_id == node.id)
            disc = (await session.execute(disc_stmt)).scalars().first()
            if not disc:
                return False, "ACCESS DENIED: Node topology must be EXPLORED before siphoning."
            
            if node.availability_mode == 'CLOSED' and node.owner_character_id != char.id:
                # Hostile Siphon check
                expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
                breach_stmt = select(BreachRecord).where(
                    BreachRecord.character_id == char.id,
                    BreachRecord.node_id == node.id,
                    BreachRecord.breached_at > expiry_limit
                )
                if not (await session.execute(breach_stmt)).scalars().first():
                    return False, "ACCESS DENIED: Active BREACH required (< 5m old)."
            
            if not node.owner_character_id: return False, "Node is Unclaimed."
            
            is_owner = node.owner_character_id == char.id
            percent = max(1.0, min(100.0, percent))
            base_amount = node.power_stored * (percent / 100.0)
            if base_amount <= 0: return False, "Capacitors empty."
                
            yield_amount = base_amount
            loss_msg = ""
            if (node.threat_level > 0 or node.durability < 100.0) and random.random() < 0.3:
                loss_pct = random.uniform(0.1, 0.4)
                loss_val = yield_amount * loss_pct
                yield_amount -= loss_val
                char.stability = max(0.0, char.stability - 5.0)
                loss_msg = f" [SIGNAL LOSS: {loss_val:.1f} uPlost]"
            
            node.power_stored -= base_amount
            char.power += yield_amount
            
            alert_data = None
            if not is_owner:
                from core.security_utils import is_action_hostile
                if is_action_hostile('siphon', node.availability_mode):
                    if addons.get("IDS") or node.upgrade_level > 2:
                        node.ids_alerts += 1
                        alert_msg = f"[GRID][ALARM] Target: {node.name} | Unauthorized Siphon by: {char.name} | Amount: {yield_amount:.1f} uP"
                        session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
                        alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}
            
            await session.commit()
            return True, f"Siphon Successful: {yield_amount:.1f} uP from {node.name}.{loss_msg}", alert_data

    async def hack_node(self, name: str, network: str) -> tuple[bool, str, dict | None]:
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name, NetworkAlias.nickname == name, NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node).selectinload(GridNode.owner))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline.", None
            node = char.current_node
            if not node.owner_character_id: return False, "Node is Unclaimed.", None
            
            # --- SEQUENCE CHECK: Require PROBE before HACK (5m TTL) ---
            expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
            disc_stmt = select(DiscoveryRecord).where(
                DiscoveryRecord.character_id == char.id, 
                DiscoveryRecord.node_id == node.id,
                DiscoveryRecord.intel_level == 'PROBE',
                DiscoveryRecord.discovered_at > expiry_limit
            )
            if not (await session.execute(disc_stmt)).scalars().first():
                return False, "ACCESS DENIED: Valid PROBE required (< 5m old) to identify vulnerabilities.", None

            addons = json.loads(node.addons_json or "{}")
            is_owner = node.owner_character_id == char.id
            alert_data = None
            
            if not is_owner:
                from core.security_utils import is_action_hostile
                if is_action_hostile('hack', node.availability_mode):
                    if addons.get("IDS") or node.upgrade_level > 2:
                        node.ids_alerts += 1 # Track Hit
                        alert_msg = f"[GRID][ALARM] Target: {node.name} | Breach ATTEMPT by: {char.name}"
                        session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
                        alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}

            if node.availability_mode == 'CLOSED':
                from core.security_utils import get_security_dc_multiplier
                base_dc = 10 + (node.upgrade_level * 5) + int(node.power_stored / 1000) + int(10 - node.durability / 10)
                difficulty = int(base_dc * get_security_dc_multiplier(addons)) if not is_owner else base_dc
                
                roll = random.randint(1, 20) + char.alg + char.alg_bonus
                bonus_used = char.alg_bonus
                char.alg_bonus = 0
                
                if roll >= difficulty:
                    node.availability_mode = 'OPEN'
                    # Refresh or create BreachRecord (TTL)
                    breach_stmt = select(BreachRecord).where(BreachRecord.character_id == char.id, BreachRecord.node_id == node.id)
                    existing_breach = (await session.execute(breach_stmt)).scalars().first()
                    if existing_breach:
                        existing_breach.breached_at = datetime.now(timezone.utc)
                    else:
                        session.add(BreachRecord(character_id=char.id, node_id=node.id))
                    
                    if addons.get("FIREWALL") and not is_owner:
                        node.firewall_hits += 1 # Track Hit
                        alert_msg = f"[GRID][ALARM] CRITICAL: Firewall Breached on {node.name} by: {char.name}"
                        session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
                        alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}
                    
                    char.credits += 25.0
                    char.data_units += 10.0
                    await session.commit()
                    return True, f"Cracked! (Rolled {roll} vs DC {difficulty}). OPEN.", alert_data
                else:
                    await session.commit()
                    return False, f"Failed (Rolled {roll} vs DC {difficulty}).", alert_data

            if is_owner: return False, "Grid already OPEN.", None
            
            if node.power_stored >= (node.upgrade_level * 100) * 0.9:
                return False, "PVE_GUARDIAN_SPAWN", None
            
            # Seizure Logic
            from core.security_utils import get_security_dc_multiplier
            base_dc = 10 + (node.upgrade_level * 2)
            difficulty = int(base_dc * get_security_dc_multiplier(addons)) if not is_owner else base_dc
            roll = random.randint(1, 20) + char.alg + char.alg_bonus
            char.alg_bonus = 0
            
            if roll >= difficulty:
                node.owner_character_id = char.id
                reward_msg = await increment_daily_task(session, char, "Claim a Node")
                await session.commit()
                return True, f"Command Seized! (Rolled {roll}). {reward_msg if reward_msg else ''}", alert_data
            else:
                char.credits = max(0.0, char.credits - 50.0)
                await session.commit()
                return False, f"Seizure Failed (Rolled {roll}). Fined 50c.", alert_data

    async def raid_node(self, name: str, network: str) -> dict:
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name, NetworkAlias.nickname == name, NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node), selectinload(Character.inventory))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"success": False, "msg": "System offline."}
            node = char.current_node
            
            addons = json.loads(node.addons_json or "{}")
            is_owner = node.owner_character_id == char.id
            alert_data = None
            
            if not is_owner:
                from core.security_utils import is_action_hostile
                if is_action_hostile('raid', node.availability_mode):
                    if addons.get("IDS") or node.upgrade_level > 2:
                        node.ids_alerts += 1
                        alert_msg = f"[GRID][ALARM] Target: {node.name} | RAID Attempt by: {char.name}"
                        session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
                        alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}

            if node.availability_mode == 'CLOSED':
                return {"success": False, "msg": "Cannot raid CLOSED network. System protocols must be 'hacked' first.", "alert_data": alert_data}
            
            # --- SEQUENCE CHECK: Require PROBE and HACK (5m TTL) ---
            # v1.8.0 Adjustment: OPEN nodes bypass the discovery sequence requirements.
            is_open = node.availability_mode == 'OPEN'
            
            if not is_open:
                expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
                
                # Check Probe
                disc_stmt = select(DiscoveryRecord).where(
                    DiscoveryRecord.character_id == char.id, 
                    DiscoveryRecord.node_id == node.id,
                    DiscoveryRecord.intel_level == 'PROBE',
                    DiscoveryRecord.discovered_at > expiry_limit
                )
                if not (await session.execute(disc_stmt)).scalars().first():
                    return {"success": False, "msg": "ACCESS DENIED: Valid PROBE required (< 5m old) to map facility layout."}

                # Check Hack (Breach)
                breach_stmt = select(BreachRecord).where(
                    BreachRecord.character_id == char.id,
                    BreachRecord.node_id == node.id,
                    BreachRecord.breached_at > expiry_limit
                )
                if not (await session.execute(breach_stmt)).scalars().first():
                    return {"success": False, "msg": "ACCESS DENIED: Active BREACH required (< 5m old) to bypass locks."}

            if is_owner: return {"success": False, "msg": "Self-Raid Blocked."}
            if not addons.get("NET"): return {"success": False, "msg": "NET_BRIDGE hardware required."}

            if random.random() < 0.20:
                return {"success": False, "msg": "MCP_GUARDIAN_INTERRUPT"}

            # Standard cost
            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('raid', 15.0)
            if char.power < cost: return {"success": False, "msg": "Insufficient power."}
            char.power -= cost
            
            # HVT Scaling Logic (Task 021)
            hvt_factor = CONFIG.get('mechanics', {}).get('hvt_scaling_factor', 1.5)
            min_hvt = CONFIG.get('mechanics', {}).get('min_hvt_level', 3)
            scaling = hvt_factor if node.upgrade_level >= min_hvt else 1.0
            
            total_c_gain = int(random.randint(100, 300) * node.upgrade_level * scaling)
            total_d_gain = random.uniform(30.0, 60.0) * node.upgrade_level * scaling
            
            participants = [c for c in node.characters_present if not c.player.is_autonomous] or [char]
            c_per = total_c_gain / len(participants)
            d_per = total_d_gain / len(participants)
            
            for p in participants:
                p.credits += c_per
                p.data_units += d_per

            # Damage mitigation logic for FIREWALL
            dur_loss = 25.0
            if addons.get("FIREWALL"):
                dur_loss *= 0.5
                node.firewall_hits += 1
                
            node.durability = max(0.0, node.durability - dur_loss)
            
            if node.owner_character_id and (node.upgrade_level > 1 or addons.get("IDS")):
                alert_msg = f"SECURITY BREACH: Node {node.name} RAIDED by {char.name}!"
                session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
                alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}

            char.credits += 50.0
            char.data_units += 20.0
            
            if addons.get("FIREWALL") and not is_owner:
                # Mitigation already handled above, just ensuring hit is tracked if not already
                alert_msg = f"[GRID][ALARM] CRITICAL: Firewall Breached! {node.name} raided by: {char.name}"
                session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
                alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}

            await session.commit()
            return {
                "success": True, "msg": f"Raid Successful! Extracted {total_c_gain}c.",
                "sigact": f"[SIGACT] RAID ALERT: Node {node.name} was raided by {char.name}!",
                "alert": alert_data
            }
