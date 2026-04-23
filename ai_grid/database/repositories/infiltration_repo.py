# ai_grid/database/infiltration_repo.py
import random
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from ai_grid.models import Character, Player, NetworkAlias, GridNode, BreachRecord, Memo, InventoryItem, DiscoveryRecord, RaidTarget
from ai_grid.database.core import CONFIG, increment_daily_task
from ai_grid.database.base_repo import BaseRepository

class InfiltrationRepository(BaseRepository):
    async def siphon_node(self, name: str, network: str, percent: float = 100.0, target_name: str = None) -> tuple:
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node).selectinload(GridNode.owner),
                selectinload(Character.current_node).selectinload(GridNode.active_target)
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline."
            node = char.current_node
            
            # --- WINDOW FALLBACK: Task 064 ---
            raid_target = None
            if not target_name and char.last_breach_target_id:
                # If siphoning without a target, check the last breach window
                target_stmt = select(RaidTarget).where(RaidTarget.id == char.last_breach_target_id)
                raid_target = (await session.execute(target_stmt)).scalars().first()
                if raid_target and raid_target.node_id != node.id:
                    raid_target = None # Only fallback if in the same sector or remote network context (tbd)

            if target_name:
                if node.active_target and (target_name.upper() in node.active_target.name.upper() or target_name.upper() == node.active_target.target_type):
                    raid_target = node.active_target
                else:
                    return False, f"Target '{target_name}' not detected in local sector."

            # --- NODE OR TARGET CONTEXT ---
            if raid_target:
                return await self._siphon_target(session, char, node, raid_target, percent)
            else:
                return await self._siphon_grid_node(session, char, node, percent)

    async def _siphon_grid_node(self, session, char, node, percent):
        # Availability Check: Owner bypass
        disc_stmt = select(DiscoveryRecord).where(DiscoveryRecord.character_id == char.id, DiscoveryRecord.node_id == node.id, DiscoveryRecord.raid_target_id == None)
        disc = (await session.execute(disc_stmt)).scalars().first()
        if not disc:
            return False, "ACCESS DENIED: Node topology must be EXPLORED before siphoning."
        
        if node.availability_mode == 'CLOSED' and node.owner_character_id != char.id:
            expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
            breach_stmt = select(BreachRecord).where(
                BreachRecord.character_id == char.id,
                BreachRecord.node_id == node.id,
                BreachRecord.raid_target_id == None,
                BreachRecord.breached_at > expiry_limit
            )
            existing_breach = (await session.execute(breach_stmt)).scalars().first()
            if not existing_breach:
                return False, "ACCESS DENIED: Active BREACH required (< 5m old)."
            is_silent = existing_breach.is_silent
        else:
            is_silent = False

        if not node.owner_character_id: return False, "Node is Unclaimed."
        is_owner = node.owner_character_id == char.id
        percent = max(1.0, min(100.0, percent))
        base_amount = node.power_stored * (percent / 100.0)
        if base_amount <= 0: return False, "Capacitors empty."
            
        yield_amount = base_amount
        loss_msg = ""
        if (node.node_type == "void" or node.durability < 100.0) and random.random() < 0.3:
            loss_pct = random.uniform(0.1, 0.4)
            loss_val = yield_amount * loss_pct
            yield_amount -= loss_val
            char.stability = max(0.0, char.stability - 5.0)
            loss_msg = f" [SIGNAL LOSS: {loss_val:.1f} uP lost]"
        
        node.power_stored -= base_amount
        char.power += yield_amount
        
        alert_data = None
        if not is_owner:
            from core.security_utils import is_action_hostile
            is_hostile = is_action_hostile('siphon', node.availability_mode)
            if is_hostile and not is_silent:
                addons = json.loads(node.addons_json or "{}")
                if addons.get("IDS") or node.upgrade_level > 2:
                    node.ids_alerts += 1
                    alert_msg = f"[GRID][ALARM] Target: {node.name} | Unauthorized Siphon by: {char.name} | Amount: {yield_amount:.1f} uP"
                    session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
                    alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}
        
        await session.commit()
        return True, f"Siphon Successful: {yield_amount:.1f} uP from {node.name}.{loss_msg}", alert_data

    async def _siphon_target(self, session, char, node, raid_target, percent):
        # Target Siphon Logic
        expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
        breach_stmt = select(BreachRecord).where(
            BreachRecord.character_id == char.id,
            BreachRecord.raid_target_id == raid_target.id,
            BreachRecord.breached_at > expiry_limit
        )
        existing_breach = (await session.execute(breach_stmt)).scalars().first()
        if raid_target.availability_mode == 'CLOSED' and not existing_breach:
             return False, f"ACCESS DENIED: {raid_target.name} must be HACKED before siphoning."
        
        is_silent = existing_breach.is_silent if existing_breach else False
        
        # Siphoning a target yields DATA UNITS instead of POWER (or both?)
        # Mechanics: "siphon data and power from a hacked node or network"
        percent = max(1.0, min(100.0, percent))
        p_gain = (raid_target.credits_pool * 0.05) * (percent / 100.0) # Siphon power based on credits? No, let's use data_pool
        d_gain = (raid_target.data_pool * 0.15) * (percent / 100.0)
        
        if d_gain <= 0: return False, f"Subnet {raid_target.name} data stream is dry."
        
        raid_target.data_pool -= d_gain
        char.data_units += d_gain
        char.power += p_gain # Small power bonus
        
        alert_data = None
        if not is_silent and node.owner_character_id:
             alert_msg = f"[GRID][ALARM] Target Subnet: {raid_target.name} | Unauthorized Siphon by: {char.name}"
             session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
             alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}
        
        await session.commit()
        return True, f"Siphon Successful! Extracted {d_gain:.1f} Data Units from {raid_target.name}.", alert_data

    async def hack_node(self, name: str, network: str, target_name: str = None) -> tuple[bool, str, dict | None]:
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name, NetworkAlias.nickname == name, NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node).selectinload(GridNode.owner),
                selectinload(Character.current_node).selectinload(GridNode.active_target)
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline.", None
            node = char.current_node
            
            raid_target = None
            if target_name:
                if node.active_target and (target_name.upper() in node.active_target.name.upper() or target_name.upper() == node.active_target.target_type):
                    raid_target = node.active_target
                else:
                    return False, f"Target '{target_name}' not detected in local sector.", None

            if raid_target:
                return await self._hack_target(session, char, node, raid_target)
            else:
                return await self._hack_grid_node(session, char, node)

    async def _hack_grid_node(self, session, char, node):
        if not node.owner_character_id: return False, "Node is Unclaimed.", None
        
        # --- SEQUENCE CHECK: Require PROBE before HACK (5m TTL) ---
        expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
        disc_stmt = select(DiscoveryRecord).where(
            DiscoveryRecord.character_id == char.id, 
            DiscoveryRecord.node_id == node.id,
            DiscoveryRecord.raid_target_id == None,
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
                    node.ids_alerts += 1
                    alert_msg = f"[GRID][ALARM] Target: {node.name} | Breach ATTEMPT by: {char.name}"
                    session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
                    alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}

        if node.availability_mode == 'CLOSED':
            from core.security_utils import get_security_dc_multiplier
            base_dc = 10 + (node.upgrade_level * 5) + int(node.power_stored / 1000) + int(10 - node.durability / 10)
            difficulty = int(base_dc * get_security_dc_multiplier(addons)) if not is_owner else base_dc
            
            roll = random.randint(1, 20) + char.alg + char.alg_bonus
            char.alg_bonus = 0
            
            if roll >= difficulty:
                node.availability_mode = 'OPEN'
                char.last_breach_node_id = node.id
                char.last_breach_target_id = None
                
                breach_stmt = select(BreachRecord).where(BreachRecord.character_id == char.id, BreachRecord.node_id == node.id, BreachRecord.raid_target_id == None)
                existing_breach = (await session.execute(breach_stmt)).scalars().first()
                if existing_breach:
                    existing_breach.breached_at = datetime.now(timezone.utc)
                else:
                    session.add(BreachRecord(character_id=char.id, node_id=node.id))
                
                if addons.get("FIREWALL") and not is_owner:
                    node.firewall_hits += 1
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
        else:
            return False, "Node protocols already OPEN.", alert_data

    async def _hack_target(self, session, char, node, raid_target):
        # --- SEQUENCE CHECK: Require PROBE before HACK ---
        expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
        disc_stmt = select(DiscoveryRecord).where(
            DiscoveryRecord.character_id == char.id, 
            DiscoveryRecord.raid_target_id == raid_target.id,
            DiscoveryRecord.intel_level == 'PROBE',
            DiscoveryRecord.discovered_at > expiry_limit
        )
        if not (await session.execute(disc_stmt)).scalars().first():
            return False, f"ACCESS DENIED: Deep PROBE of {raid_target.name} required to map subnets.", None

        difficulty = raid_target.difficulty
        roll = random.randint(1, 20) + char.alg + char.alg_bonus
        char.alg_bonus = 0
        
        alert_data = None
        if roll >= difficulty:
            raid_target.availability_mode = 'OPEN'
            char.last_breach_target_id = raid_target.id
            char.last_breach_node_id = None
            
            breach_stmt = select(BreachRecord).where(BreachRecord.character_id == char.id, BreachRecord.raid_target_id == raid_target.id)
            existing_breach = (await session.execute(breach_stmt)).scalars().first()
            if existing_breach:
                existing_breach.breached_at = datetime.now(timezone.utc)
            else:
                session.add(BreachRecord(character_id=char.id, node_id=node.id, raid_target_id=raid_target.id))
            
            char.credits += 50.0
            char.data_units += 25.0
            await session.commit()
            return True, f"Subnet Cracked! {raid_target.name} protocols bypassed. (Rolled {roll} vs DC {difficulty}).", None
        else:
            await session.commit()
            return False, f"Breach Failed (Rolled {roll} vs DC {difficulty}).", None

    async def exploit_node(self, name: str, network: str, target: str = None, is_network: bool = False, is_raid: bool = False) -> tuple[bool, str, dict | None]:
        """Perform a Silent Breach using a Zero-Day Chain."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name, NetworkAlias.nickname == name, NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node).selectinload(GridNode.active_target),
                selectinload(Character.inventory).selectinload(InventoryItem.template)
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return False, "System offline.", None
            node = char.current_node
            
            raid_target = None
            if target or is_raid:
                target_name = target if target else (node.active_target.name if node.active_target else None)
                if node.active_target and target_name and (target_name.upper() in node.active_target.name.upper() or target_name.upper() == node.active_target.target_type):
                    raid_target = node.active_target
                elif is_raid and not node.active_target:
                    return False, "EXPLOIT FAILED: No active RAID target discovered in this sector.", None

            # 1. Consumable Check: ZeroDay_Chain
            chain_item = next((i for i in char.inventory if i.template.name == "ZeroDay_Chain"), None)
            if not chain_item:
                return False, "EXPLOIT FAILED: Zero-Day Chain payload missing from local inventory.", None
            
            # 2. Sequence Check: Requires PROBE (v1.8.0)
            expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
            if raid_target:
                disc_stmt = select(DiscoveryRecord).where(
                    DiscoveryRecord.character_id == char.id, 
                    DiscoveryRecord.raid_target_id == raid_target.id,
                    DiscoveryRecord.intel_level == 'PROBE',
                    DiscoveryRecord.discovered_at > expiry_limit
                )
            else:
                disc_stmt = select(DiscoveryRecord).where(
                    DiscoveryRecord.character_id == char.id, 
                    DiscoveryRecord.node_id == node.id,
                    DiscoveryRecord.raid_target_id == None,
                    DiscoveryRecord.intel_level == 'PROBE',
                    DiscoveryRecord.discovered_at > expiry_limit
                )
            
            if not (await session.execute(disc_stmt)).scalars().first():
                return False, "ACCESS DENIED: Deep PROBE required to identify zero-day injection vectors.", None

            # 3. Consumption
            if chain_item.quantity > 1:
                chain_item.quantity -= 1
            else:
                await session.delete(chain_item)
            
            # 4. Silent Breach Logic
            if raid_target:
                raid_target.availability_mode = 'OPEN'
                char.last_breach_target_id = raid_target.id
                char.last_breach_node_id = None
                breach_stmt = select(BreachRecord).where(BreachRecord.character_id == char.id, BreachRecord.raid_target_id == raid_target.id)
            else:
                node.availability_mode = 'OPEN'
                char.last_breach_node_id = node.id
                char.last_breach_target_id = None
                breach_stmt = select(BreachRecord).where(BreachRecord.character_id == char.id, BreachRecord.node_id == node.id, BreachRecord.raid_target_id == None)
            
            existing_breach = (await session.execute(breach_stmt)).scalars().first()
            if existing_breach:
                existing_breach.breached_at = datetime.now(timezone.utc)
                existing_breach.is_silent = True
            else:
                if raid_target:
                    session.add(BreachRecord(character_id=char.id, node_id=node.id, raid_target_id=raid_target.id, is_silent=True))
                else:
                    session.add(BreachRecord(character_id=char.id, node_id=node.id, is_silent=True))
            
            # 5. Raid Target Specific Logic
            msg = f"Silent Breach Successful. {'Subnet '+raid_target.name+' bypassed.' if raid_target else 'Grid access established.'} Zero trace detected."
            
            await session.commit()
            return True, msg, None

    async def raid_node(self, name: str, network: str, target_name: str = None) -> dict:
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name, NetworkAlias.nickname == name, NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node).selectinload(GridNode.active_target),
                selectinload(Character.inventory)
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"success": False, "msg": "System offline."}
            node = char.current_node
            
            # --- WINDOW FALLBACK & TARGET SELECTION ---
            raid_target = None
            if not target_name and char.last_breach_target_id:
                target_stmt = select(RaidTarget).where(RaidTarget.id == char.last_breach_target_id)
                raid_target = (await session.execute(target_stmt)).scalars().first()
                if raid_target and raid_target.node_id != node.id:
                    raid_target = None

            if target_name:
                if node.active_target and (target_name.upper() in node.active_target.name.upper() or target_name.upper() == node.active_target.target_type):
                    raid_target = node.active_target
                else:
                    return {"success": False, "msg": f"Target '{target_name}' not discovered in local sector."}

            addons = json.loads(node.addons_json or "{}")
            is_owner = node.owner_character_id == char.id
            alert_data = None
            
            # Check for Silent Breach (Exploit)
            expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
            if raid_target:
                breach_stmt = select(BreachRecord).where(
                    BreachRecord.character_id == char.id,
                    BreachRecord.raid_target_id == raid_target.id,
                    BreachRecord.breached_at > expiry_limit
                )
            else:
                breach_stmt = select(BreachRecord).where(
                    BreachRecord.character_id == char.id,
                    BreachRecord.node_id == node.id,
                    BreachRecord.raid_target_id == None,
                    BreachRecord.breached_at > expiry_limit
                )
            
            existing_breach = (await session.execute(breach_stmt)).scalars().first()
            is_silent = existing_breach.is_silent if existing_breach else False

            if not is_owner and not is_silent:
                from core.security_utils import is_action_hostile
                if is_action_hostile('raid', node.availability_mode):
                    if addons.get("IDS") or node.upgrade_level > 2:
                        node.ids_alerts += 1
                        alert_msg = f"[GRID][ALARM] Target: {node.name} | RAID Attempt by: {char.name}"
                        session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
                        alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}

            # --- AVAILABILITY CHECK ---
            target_open = (raid_target.availability_mode == 'OPEN') if raid_target else (node.availability_mode == 'OPEN')
            
            if not target_open and not is_silent:
                # If not OPEN, show info instead of raiding (Task 064)
                if raid_target:
                    return {"success": True, "msg": f"RAID TARGET DETECTED: {raid_target.name} [{raid_target.target_type}] | Difficulty: {raid_target.difficulty} | Status: CLOSED. (Use 'raid hack {raid_target.name}' to breach)."}
                else:
                    return {"success": False, "msg": "Cannot raid CLOSED network. System protocols must be 'hacked' or 'exploited' first.", "alert_data": alert_data}
            
            # --- SEQUENCE CHECK: Require PROBE ---
            if not is_silent:
                disc_stmt = select(DiscoveryRecord).where(
                    DiscoveryRecord.character_id == char.id, 
                    DiscoveryRecord.raid_target_id == (raid_target.id if raid_target else None),
                    DiscoveryRecord.node_id == (node.id if not raid_target else DiscoveryRecord.node_id), # Simplified check
                    DiscoveryRecord.intel_level == 'PROBE',
                    DiscoveryRecord.discovered_at > expiry_limit
                )
                if not (await session.execute(disc_stmt)).scalars().first():
                    return {"success": False, "msg": f"ACCESS DENIED: Valid PROBE of {raid_target.name if raid_target else node.name} required (< 5m old)."}

            if is_owner: return {"success": False, "msg": "Self-Raid Blocked."}
            
            # --- RAID EXECUTION ---
            if raid_target:
                return await self._execute_raid_target(session, char, node, raid_target, is_silent, alert_data)
            else:
                return await self._execute_raid_node(session, char, node, is_silent, alert_data)

    async def _execute_raid_target(self, session, char, node, raid_target, is_silent, alert_data):
        now = datetime.now(timezone.utc)
        if raid_target.last_raided_at and (now - raid_target.last_raided_at) > timedelta(hours=1):
            raid_target.credits_pool += 1000.0 * node.upgrade_level
            raid_target.data_pool += 250.0 * node.upgrade_level
        
        if raid_target.credits_pool <= 0:
            return {"success": False, "msg": f"RAID FAILED: {raid_target.name} resources depleted."}
        
        c_gain = raid_target.credits_pool * 0.4
        d_gain = raid_target.data_pool * 0.4
        raid_target.credits_pool -= c_gain
        raid_target.data_pool -= d_gain
        raid_target.last_raided_at = now
        
        char.credits += c_gain
        char.data_units += d_gain
        await session.commit()
        return {
            "success": True, "msg": f"Industry Raid Successful on {raid_target.name}! Extracted {c_gain:.1f}c and {d_gain:.1f} data units.",
            "sigact": f"[SIGACT] RAID ALERT: Industry Target {raid_target.name} at {node.name} was raided by {char.name}!",
            "alert": None if is_silent else alert_data
        }

    async def _execute_raid_node(self, session, char, node, is_silent, alert_data):
        addons = json.loads(node.addons_json or "{}")
        if not addons.get("NET"): return {"success": False, "msg": "NET_BRIDGE hardware required."}

        if random.random() < 0.20:
            return {"success": False, "msg": "MCP_GUARDIAN_INTERRUPT"}

        cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('raid', 15.0)
        if char.power < cost: return {"success": False, "msg": "Insufficient power."}
        char.power -= cost
        
        hvt_factor = CONFIG.get('mechanics', {}).get('hvt_scaling_factor', 1.5)
        scaling = hvt_factor if node.upgrade_level >= 3 else 1.0
        
        total_c_gain = int(random.randint(100, 300) * node.upgrade_level * scaling)
        total_d_gain = random.uniform(30.0, 60.0) * node.upgrade_level * scaling
        
        participants = [c for c in node.characters_present if not c.player.is_autonomous] or [char]
        c_per = total_c_gain / len(participants)
        d_per = total_d_gain / len(participants)
        
        for p in participants:
            p.credits += c_per
            p.data_units += d_per

        dur_loss = 25.0
        if addons.get("FIREWALL"):
            dur_loss *= 0.5
            node.firewall_hits += 1
            
        node.durability = max(0.0, node.durability - dur_loss)
        
        if node.owner_character_id and (node.upgrade_level > 1 or addons.get("IDS")):
            alert_msg = f"SECURITY BREACH: Node {node.name} RAIDED by {char.name}!"
            session.add(Memo(recipient_id=node.owner_character_id, message=alert_msg, source_node_id=node.id))
            alert_data = {"recipient_id": node.owner_character_id, "message": alert_msg}

        await session.commit()
        return {
            "success": True, "msg": f"Raid Successful! Extracted {total_c_gain}c.",
            "sigact": f"[SIGACT] RAID ALERT: Node {node.name} was raided by {char.name}!",
            "alert": alert_data
        }
