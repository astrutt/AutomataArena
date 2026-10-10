# ai_grid/database/repositories/remote_net_repo.py
import json
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any, List

from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func, or_

from ai_grid.models import (
    Character,
    Player,
    NetworkAlias,
    GridNode,
    DiscoveryRecord,
    RaidTarget,
    BreachRecord,
    Memo,
    CharacterSkill,
    InventoryItem,
    ItemTemplate,
)
from ai_grid.database.core import CONFIG
from ai_grid.database.base_repo import BaseRepository
from ai_grid.core.security_utils import get_security_dc_multiplier, is_action_hostile


def get_net_device_state(node: Optional[GridNode]) -> str:
    """
    Returns the effective NET access state for a node: OPEN, CLOSED, or STEALTH.
    Defaults to node.availability_mode if set, or OPEN.
    """
    if not node:
        return "CLOSED"
    addons = json.loads(node.addons_json or "{}") if isinstance(node.addons_json, str) else (node.addons_json or {})
    if not addons.get("NET"):
        return (node.availability_mode or "CLOSED").upper()

    if "NET_STATE" in addons and str(addons["NET_STATE"]).upper() in ["OPEN", "CLOSED", "STEALTH"]:
        return str(addons["NET_STATE"]).upper()

    net_val = addons.get("NET")
    if isinstance(net_val, dict) and "state" in net_val and str(net_val["state"]).upper() in ["OPEN", "CLOSED", "STEALTH"]:
        return str(net_val["state"]).upper()
    if isinstance(net_val, str) and net_val.upper() in ["OPEN", "CLOSED", "STEALTH"]:
        return net_val.upper()

    if node.availability_mode and str(node.availability_mode).upper() in ["OPEN", "CLOSED", "STEALTH"]:
        return str(node.availability_mode).upper()

    return "OPEN"


class RemoteNetRepository(BaseRepository):
    """
    Repository for NET Device State Management and Cross-Network Operations (Section 6).
    Handles:
    - NET device state transitions (OPEN, CLOSED, STEALTH)
    - Remote discovery-to-raid loop (explore, probe, hack, siphon, exploit, raid)
    - Distance dampening & latency difficulty modifiers
    - Gated remote PvP/PvE queue access
    """

    # --- Distance & Yield Modifiers ---
    @staticmethod
    def calculate_remote_explore_yield(base_credits: float, base_data: float) -> Tuple[float, float]:
        """-20% yield (remote dampening)."""
        return round(base_credits * 0.80, 2), round(base_data * 0.80, 2)

    @staticmethod
    def calculate_remote_hack_difficulty(base_difficulty: int) -> int:
        """+20% hack difficulty (latency penalty)."""
        return int(base_difficulty * 1.20)

    @staticmethod
    def calculate_remote_siphon_yield(base_yield: float) -> float:
        """-10% exfiltration yield."""
        return round(base_yield * 0.90, 2)

    @staticmethod
    def calculate_remote_raid_yield(base_credits: float, base_data: float) -> Tuple[float, float]:
        """-20% reward yield."""
        return int(base_credits * 0.80), round(base_data * 0.80, 2)

    # --- State Management ---
    async def set_net_device_state(
        self, name: str, network: str, state: str, node_name: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Toggles NET device access state: OPEN, CLOSED, or STEALTH."""
        state = state.upper()
        if state not in ["OPEN", "CLOSED", "STEALTH"]:
            return False, f"Invalid state '{state}'. Permitted states: OPEN, CLOSED, STEALTH."

        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char:
                return False, "System offline: Character not found."

            if node_name:
                clean_name = node_name.strip("[]").strip()
                node_stmt = select(GridNode).where(
                    (func.lower(GridNode.name) == node_name.lower()) | (func.lower(GridNode.name) == clean_name.lower())
                )
                node = (await session.execute(node_stmt)).scalars().first()
                if not node:
                    return False, f"Node '{node_name}' not found."
            else:
                node = char.current_node

            if not node:
                return False, "Target node unavailable."

            if node.owner_character_id != char.id:
                return False, "Permission Denied: Only the node owner can configure NET device access states."

            addons = json.loads(node.addons_json or "{}") if isinstance(node.addons_json, str) else (node.addons_json or {})
            if not addons.get("NET"):
                return False, "Hardware Conflict: NET device not installed on this node."

            node.availability_mode = state
            addons["NET_STATE"] = state
            if isinstance(addons.get("NET"), dict):
                addons["NET"]["state"] = state
            node.addons_json = json.dumps(addons)
            await session.commit()
            return True, f"NET Device Configuration: {node.name} access state set to {state}."

    async def is_node_pvp_pve_accessible(self, node_id: int, character_id: Optional[int]) -> Tuple[bool, str]:
        """
        Remote PvP/PvE Gating:
        - OPEN node: PvP and PvE available immediately via mutual queue
        - CLOSED/STEALTH node: Requires successful hack or exploit first to unlock PvP/PvE
        """
        if not character_id:
            return False, "Character identification required."

        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.id == node_id))).scalars().first()
            if not node:
                return False, "Target node not found."

            if node.owner_character_id is not None and node.owner_character_id == character_id:
                return True, "PvP and PvE queue accessible (Node Owner)."

            state = get_net_device_state(node)
            if state == "OPEN":
                return True, "PvP and PvE queue accessible immediately (OPEN state)."

            expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
            stmt = select(BreachRecord).where(
                BreachRecord.character_id == character_id,
                BreachRecord.node_id == node.id,
                BreachRecord.breached_at > expiry_limit
            ).order_by(BreachRecord.breached_at.desc())
            breach = (await session.execute(stmt)).scalars().first()
            if breach:
                return True, f"PvP and PvE queue unlocked via active breach ({state} state)."

            return False, f"Access Denied: Node in {state} state requires successful hack or exploit to unlock PvP/PvE."

    # --- Prerequisite Verification ---
    def verify_remote_prerequisites(
        self, char: Optional[Character], target_network: str
    ) -> Tuple[bool, str, Optional[GridNode]]:
        """
        Verifies that attacker is stationed at a claimed or authorized node
        equipped with an active NET device pointed at target_network.
        """
        if not char or not char.current_node:
            return False, "System offline: Character not stationed at a valid node.", None

        node = char.current_node
        if node.owner_character_id is None:
            return False, "Access Denied: Remote operations require a claimed node.", None

        if node.owner_character_id != char.id and get_net_device_state(node) != "OPEN":
            return False, "Access Denied: Node is claimed by another entity.", None

        addons = json.loads(node.addons_json or "{}") if isinstance(node.addons_json, str) else (node.addons_json or {})
        if not addons.get("NET"):
            return False, "Hardware Error: Active NET device required for remote operations.", None

        if not node.net_affinity or node.net_affinity.lower() != target_network.lower():
            return (
                False,
                f"Alignment Error: NET device must be pointed at '{target_network}' (currently: '{node.net_affinity or 'None'}').",
                None,
            )

        return True, "Authorized", node

    # --- Remote Operations ---

    async def remote_explore(self, name: str, network: str, target_network: str) -> Dict[str, Any]:
        """
        net <network> explore:
        - No detection risk
        - -20% yield (remote dampening)
        - STEALTH nodes completely hidden
        - CLOSED nodes visible only as existing
        """
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.skills)
            )
            char = (await session.execute(stmt)).scalars().first()
            ok, msg, local_node = self.verify_remote_prerequisites(char, target_network)
            if not ok:
                return {"success": False, "msg": msg}

            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('explore', 5.0)
            if char.power < cost:
                return {"success": False, "msg": f"Insufficient POWER. Remote explore requires {cost} uP."}

            char.power -= cost

            # Query all nodes on target network
            target_stmt = select(GridNode).where(GridNode.net_affinity.ilike(target_network)).options(
                selectinload(GridNode.active_target)
            )
            target_nodes = (await session.execute(target_stmt)).scalars().all()
            target_nodes = [n for n in target_nodes if n.id != local_node.id]
            if not target_nodes:
                return {
                    "success": False,
                    "msg": f"Remote exploration failed: No active grid nodes found on network '{target_network}'.",
                }

            visible_nodes = []
            stealth_count = 0
            for tn in target_nodes:
                tn_state = get_net_device_state(tn)
                if tn_state == "STEALTH":
                    stealth_count += 1
                    continue  # STEALTH nodes never appear in explore results

                visible_nodes.append({
                    "name": tn.name,
                    "state": tn_state,
                    "type": tn.node_type,
                    "level": tn.upgrade_level,
                })

                # Create persistent DiscoveryRecord
                disc_stmt = select(DiscoveryRecord).where(
                    DiscoveryRecord.character_id == char.id,
                    DiscoveryRecord.node_id == tn.id,
                    DiscoveryRecord.raid_target_id == None
                )
                existing_disc = (await session.execute(disc_stmt)).scalars().first()
                if not existing_disc:
                    session.add(DiscoveryRecord(character_id=char.id, node_id=tn.id, intel_level='EXPLORE'))
                else:
                    # Do not downgrade active PROBE intelligence
                    now_utc = datetime.now(timezone.utc)
                    is_active_probe = (
                        existing_disc.intel_level == 'PROBE'
                        and (
                            (existing_disc.intel_expires_at and existing_disc.intel_expires_at > now_utc)
                            or (existing_disc.discovered_at and existing_disc.discovered_at > (now_utc - timedelta(seconds=300)))
                        )
                    )
                    if not is_active_probe:
                        existing_disc.intel_level = 'EXPLORE'

            # Recon skill modifier + remote dampening (-20%)
            if visible_nodes:
                recon_skill = next((s for s in char.skills if s.skill_name == 'recon'), None) if char.skills else None
                recon_lvl = recon_skill.level if recon_skill else 0
                recon_mult = 1.0 + (0.10 * recon_lvl)

                base_credits = 25.0 * recon_mult
                base_data = 2.0 * recon_mult
                cred_gain, data_gain = self.calculate_remote_explore_yield(base_credits, base_data)

                char.credits += cred_gain
                char.data_units += data_gain
            else:
                cred_gain, data_gain = 0.0, 0.0

            await session.commit()

            discovered_names = [f"{n['name']} [{n['state']}]" for n in visible_nodes]
            summary = ", ".join(discovered_names) if discovered_names else "No open sectors detected"
            return {
                "success": True,
                "target_network": target_network,
                "visible_nodes": visible_nodes,
                "credits_gained": cred_gain,
                "data_gained": data_gain,
                "yield_modifier": "-20%",
                "msg": f"Remote exploration of {target_network} complete: {len(visible_nodes)} node(s) mapped ({summary}). Yielded {cred_gain:.1f}c, {data_gain:.1f} Data.",
            }

    async def remote_probe(
        self, name: str, network: str, target_network: str, target_name: str
    ) -> Dict[str, Any]:
        """
        net <network> probe <target>:
        - Low detection risk
        - Normal yield/intel
        - STEALTH node resolved at 30% base chance only
        """
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.skills)
            )
            char = (await session.execute(stmt)).scalars().first()
            ok, msg, local_node = self.verify_remote_prerequisites(char, target_network)
            if not ok:
                return {"success": False, "msg": msg}

            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('probe', 10.0)
            if char.power < cost:
                return {"success": False, "msg": f"Insufficient POWER. Remote probe requires {cost} uP."}

            char.power -= cost

            # Locate target node on target network
            clean_target = target_name.strip("[]").strip()
            target_stmt = select(GridNode).where(
                (func.lower(GridNode.name) == target_name.lower()) | (func.lower(GridNode.name) == clean_target.lower()),
                GridNode.net_affinity.ilike(target_network)
            ).options(selectinload(GridNode.active_target))
            target_node = (await session.execute(target_stmt)).scalars().first()

            if not target_node:
                return {"success": False, "msg": f"Target '{target_name}' not detected on {target_network}."}

            if target_node.id == local_node.id:
                return {"success": False, "msg": "Target Conflict: Cannot target the local operating node via remote NET device."}

            tn_state = get_net_device_state(target_node)

            # STEALTH Gate: 30% base chance
            if tn_state == "STEALTH":
                roll = random.random()
                if roll >= 0.30:
                    await session.commit()
                    return {
                        "success": False,
                        "msg": f"PROBE FAILED: Stealth sensor interference on {target_network}. Target unresolvable.",
                    }

            # Calculate hack DC for intelligence
            addons = json.loads(target_node.addons_json or "{}") if isinstance(target_node.addons_json, str) else (target_node.addons_json or {})
            base_dc = 10 + (target_node.upgrade_level * 5) + int(target_node.power_stored / 1000) + int(10 - target_node.durability / 10)
            dc_mult = get_security_dc_multiplier(addons)
            local_dc = int(base_dc * dc_mult)
            remote_dc = self.calculate_remote_hack_difficulty(local_dc)

            # Create or update PROBE DiscoveryRecord (300s TTL)
            duration = CONFIG.get('mechanics', {}).get('probe_duration_seconds', 300)
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=duration)
            disc_stmt = select(DiscoveryRecord).where(
                DiscoveryRecord.character_id == char.id,
                DiscoveryRecord.node_id == target_node.id,
                DiscoveryRecord.raid_target_id == None
            ).order_by(DiscoveryRecord.id.desc())
            disc = (await session.execute(disc_stmt)).scalars().first()
            if disc:
                disc.intel_level = 'PROBE'
                disc.intel_expires_at = expires_at
                disc.discovered_at = datetime.now(timezone.utc)
            else:
                session.add(DiscoveryRecord(
                    character_id=char.id,
                    node_id=target_node.id,
                    intel_level='PROBE',
                    intel_expires_at=expires_at,
                    discovered_at=datetime.now(timezone.utc)
                ))

            # Detection Risk: Low
            alert_data = None
            is_owner = target_node.owner_character_id == char.id
            if not is_owner and (addons.get("IDS") or target_node.upgrade_level > 2):
                if random.random() < 0.25:  # Low detection trigger
                    target_node.ids_alerts += 1
                    alert_msg = f"[GRID][ALARM] Target: {target_node.name} | Remote Probe from {network} by: {char.name}"
                    if target_node.owner_character_id:
                        session.add(Memo(recipient_id=target_node.owner_character_id, message=alert_msg, source_node_id=target_node.id))
                    alert_data = {
                        "target_network": target_network,
                        "alert_msg": alert_msg,
                        "recipient_id": target_node.owner_character_id,
                    }

            await session.commit()

            return {
                "success": True,
                "name": target_node.name,
                "state": tn_state,
                "level": target_node.upgrade_level,
                "durability": target_node.durability,
                "remote_hack_dc": remote_dc,
                "alert_data": alert_data,
                "msg": f"PROBE REPORT: {target_node.name} [{tn_state}] | Lvl:{target_node.upgrade_level} | Durability:{target_node.durability:.1f}% | Remote Hack DC:{remote_dc} (+20% Latency).",
            }

    async def remote_hack(
        self, name: str, network: str, target_network: str, target_name: str
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        net <network> hack <target>:
        - Medium detection risk
        - +20% hack difficulty (latency penalty)
        - Requires valid remote PROBE within 5m
        """
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.skills)
            )
            char = (await session.execute(stmt)).scalars().first()
            ok, msg, local_node = self.verify_remote_prerequisites(char, target_network)
            if not ok:
                return False, msg, None

            # Locate target node
            clean_target = target_name.strip("[]").strip()
            target_stmt = select(GridNode).where(
                (func.lower(GridNode.name) == target_name.lower()) | (func.lower(GridNode.name) == clean_target.lower()),
                GridNode.net_affinity.ilike(target_network)
            )
            target_node = (await session.execute(target_stmt)).scalars().first()
            if not target_node:
                return False, f"Target '{target_name}' not detected on {target_network}.", None

            if target_node.id == local_node.id:
                return False, "Target Conflict: Cannot target the local operating node via remote NET device.", None

            # Prerequisite: Valid PROBE within 300s
            expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
            disc_stmt = select(DiscoveryRecord).where(
                DiscoveryRecord.character_id == char.id,
                DiscoveryRecord.node_id == target_node.id,
                DiscoveryRecord.raid_target_id == None,
                DiscoveryRecord.intel_level == 'PROBE',
                DiscoveryRecord.discovered_at > expiry_limit
            ).order_by(DiscoveryRecord.id.desc())
            disc = (await session.execute(disc_stmt)).scalars().first()
            if not disc:
                return False, f"ACCESS DENIED: Valid PROBE of {target_node.name} required (< 5m old).", None

            tn_state = get_net_device_state(target_node)
            if tn_state == "OPEN":
                return False, "Node protocols already OPEN.", None

            addons = json.loads(target_node.addons_json or "{}") if isinstance(target_node.addons_json, str) else (target_node.addons_json or {})
            is_owner = target_node.owner_character_id == char.id

            # Base DC calculation
            base_dc = 10 + (target_node.upgrade_level * 5) + int(target_node.power_stored / 1000) + int(10 - target_node.durability / 10)
            local_dc = int(base_dc * get_security_dc_multiplier(addons))

            # Fortify skill modifier
            if target_node.owner_character_id and not is_owner:
                fortify_stmt = select(CharacterSkill).where(
                    CharacterSkill.character_id == target_node.owner_character_id,
                    CharacterSkill.skill_name == 'fortify'
                )
                fortify_skill = (await session.execute(fortify_stmt)).scalars().first()
                if fortify_skill and fortify_skill.level > 0:
                    local_dc = int(local_dc * (1.0 + 0.10 * fortify_skill.level))

            # Enforce distance modifier: +20% hack difficulty (latency penalty)
            difficulty = self.calculate_remote_hack_difficulty(local_dc)

            # Medium detection risk
            alert_data = None
            if not is_owner and (addons.get("IDS") or target_node.upgrade_level > 2 or random.random() < 0.50):
                target_node.ids_alerts += 1
                alert_msg = f"[GRID][ALARM] Target: {target_node.name} | Remote Breach ATTEMPT from {network} by: {char.name}"
                if target_node.owner_character_id:
                    session.add(Memo(recipient_id=target_node.owner_character_id, message=alert_msg, source_node_id=target_node.id))
                alert_data = {
                    "target_network": target_network,
                    "alert_msg": alert_msg,
                    "recipient_id": target_node.owner_character_id,
                }

            # Roll hack
            roll = random.randint(1, 20) + char.alg + char.alg_bonus
            char.alg_bonus = 0

            if roll >= difficulty:
                target_node.availability_mode = 'OPEN'
                addons["NET_STATE"] = "OPEN"
                if isinstance(addons.get("NET"), dict):
                    addons["NET"]["state"] = "OPEN"
                target_node.addons_json = json.dumps(addons)
                char.last_breach_node_id = target_node.id

                breach_stmt = select(BreachRecord).where(
                    BreachRecord.character_id == char.id,
                    BreachRecord.node_id == target_node.id,
                    BreachRecord.raid_target_id == None
                ).order_by(BreachRecord.breached_at.desc())
                breach = (await session.execute(breach_stmt)).scalars().first()
                if breach:
                    breach.breached_at = datetime.now(timezone.utc)
                    breach.is_silent = False
                else:
                    session.add(BreachRecord(character_id=char.id, node_id=target_node.id, is_silent=False))

                if addons.get("FIREWALL") and not is_owner:
                    target_node.firewall_hits += 1
                    fw_alert = f"[GRID][ALARM] CRITICAL: Remote Firewall Breach on {target_node.name} by: {char.name}"
                    if target_node.owner_character_id:
                        session.add(Memo(recipient_id=target_node.owner_character_id, message=fw_alert, source_node_id=target_node.id))
                    alert_data = {
                        "target_network": target_network,
                        "alert_msg": fw_alert,
                        "recipient_id": target_node.owner_character_id,
                    }

                char.credits += 25.0
                char.data_units += 10.0
                await session.commit()
                return True, f"Cracked remote security! (Rolled {roll} vs DC {difficulty} [+20% Latency]). {target_node.name} is now OPEN.", alert_data
            else:
                await session.commit()
                return False, f"Remote hack failed (Rolled {roll} vs DC {difficulty} [+20% Latency]).", alert_data

    async def remote_siphon(
        self, name: str, network: str, target_network: str, target_name: str, percent: float = 100.0
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        net <network> siphon <target>:
        - High detection risk
        - -10% exfiltration yield
        - CLOSED nodes require breach
        """
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.skills)
            )
            char = (await session.execute(stmt)).scalars().first()
            ok, msg, local_node = self.verify_remote_prerequisites(char, target_network)
            if not ok:
                return False, msg, None

            # Locate target node
            clean_target = target_name.strip("[]").strip()
            target_stmt = select(GridNode).where(
                (func.lower(GridNode.name) == target_name.lower()) | (func.lower(GridNode.name) == clean_target.lower()),
                GridNode.net_affinity.ilike(target_network)
            )
            target_node = (await session.execute(target_stmt)).scalars().first()
            if not target_node:
                return False, f"Target '{target_name}' not detected on {target_network}.", None

            if target_node.id == local_node.id:
                return False, "Target Conflict: Cannot target the local operating node via remote NET device.", None

            if target_node.power_stored <= 0:
                return False, f"Power reserves on {target_node.name} depleted (0 uP available).", None

            tn_state = get_net_device_state(target_node)
            is_owner = target_node.owner_character_id == char.id

            # Access Gating: CLOSED and STEALTH require breach
            expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
            breach_stmt = select(BreachRecord).where(
                BreachRecord.character_id == char.id,
                BreachRecord.node_id == target_node.id,
                BreachRecord.raid_target_id == None,
                BreachRecord.breached_at > expiry_limit
            ).order_by(BreachRecord.breached_at.desc())
            breach = (await session.execute(breach_stmt)).scalars().first()

            if tn_state in ["CLOSED", "STEALTH"] and not breach:
                return False, f"ACCESS DENIED: Remote node {target_node.name} in {tn_state} state must be HACKED before siphoning.", None

            is_silent = breach.is_silent if breach else False

            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('siphon', 5.0)
            if char.power < cost:
                return False, f"Insufficient POWER. Remote siphon requires {cost} uP.", None
            char.power -= cost

            # Calculate base yield
            percent = max(1.0, min(100.0, percent))
            base_available = target_node.power_stored * (percent / 100.0)
            base_amount = min(target_node.power_stored, max(1.0, base_available))

            siphon_skill = next((s for s in char.skills if s.skill_name == 'siphon'), None) if char.skills else None
            siphon_lvl = siphon_skill.level if siphon_skill else 0
            siphon_mult = 1.0 + (0.10 * siphon_lvl)
            local_yield = base_amount * siphon_mult

            # Enforce distance modifier: -10% exfiltration yield
            yield_amount = self.calculate_remote_siphon_yield(local_yield)

            target_node.power_stored = max(0.0, target_node.power_stored - base_amount)
            char.power += yield_amount

            # High detection risk
            alert_data = None
            addons = json.loads(target_node.addons_json or "{}") if isinstance(target_node.addons_json, str) else (target_node.addons_json or {})
            if not is_owner and not is_silent:
                target_node.ids_alerts += 1
                alert_msg = f"[GRID][ALARM] Target: {target_node.name} | Unauthorized Remote Siphon from {network} by: {char.name} | Amount: {yield_amount:.1f} uP"
                if target_node.owner_character_id:
                    session.add(Memo(recipient_id=target_node.owner_character_id, message=alert_msg, source_node_id=target_node.id))
                alert_data = {
                    "target_network": target_network,
                    "alert_msg": alert_msg,
                    "recipient_id": target_node.owner_character_id,
                }

            await session.commit()
            return True, f"Remote Siphon Successful: Extracted {yield_amount:.1f} uP from {target_node.name} on {target_network} (-10% remote dampening).", alert_data

    async def remote_exploit(
        self, name: str, network: str, target_network: str, target_name: str, item_name: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        net <network> exploit <target>:
        - Very high detection risk (unless silent zero-day)
        - True damage/bypass (ignores distance dampening)
        - Bypasses security DC
        """
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
            ok, msg, local_node = self.verify_remote_prerequisites(char, target_network)
            if not ok:
                return False, msg, None

            # Locate target node
            clean_target = target_name.strip("[]").strip()
            target_stmt = select(GridNode).where(
                (func.lower(GridNode.name) == target_name.lower()) | (func.lower(GridNode.name) == clean_target.lower()),
                GridNode.net_affinity.ilike(target_network)
            )
            target_node = (await session.execute(target_stmt)).scalars().first()
            if not target_node:
                return False, f"Target '{target_name}' not detected on {target_network}.", None

            if target_node.id == local_node.id:
                return False, "Target Conflict: Cannot target the local operating node via remote NET device.", None

            # Check for zero-day / exploit item in inventory
            def _is_valid_exploit(item):
                if not item or not item.template:
                    return False
                tname = (item.template.name or "").upper()
                effects = (item.template.effects_json or "").lower()
                return (
                    any(k in tname for k in ["EXPLOIT", "ZERODAY", "ZERO_DAY", "APT", "ROOTKIT", "PAYLOAD", "SCRIPT"])
                    or "exploit" in effects
                )

            exploit_item = None
            if item_name:
                candidate = next(
                    (i for i in char.inventory if i.template.name.upper() == item_name.upper()), None
                )
                if not candidate:
                    return False, f"Hardware/Payload '{item_name}' not found in inventory.", None
                if not _is_valid_exploit(candidate):
                    return False, f"Item '{candidate.template.name}' is not a valid Zero-Day or exploit artifact.", None
                exploit_item = candidate
            else:
                exploit_item = next((i for i in char.inventory if _is_valid_exploit(i)), None)

            if not exploit_item:
                return False, "Access Denied: Zero-Day chain or exploit artifact required in inventory.", None

            # True damage / bypass: ignores distance dampening
            target_node.availability_mode = 'OPEN'
            addons = json.loads(target_node.addons_json or "{}") if isinstance(target_node.addons_json, str) else (target_node.addons_json or {})
            addons["NET_STATE"] = "OPEN"
            if isinstance(addons.get("NET"), dict):
                addons["NET"]["state"] = "OPEN"
            target_node.addons_json = json.dumps(addons)
            char.last_breach_node_id = target_node.id

            is_silent = "ROOTKIT" in exploit_item.template.name.upper() or "APT" in exploit_item.template.name.upper()

            # Record breach
            breach_stmt = select(BreachRecord).where(
                BreachRecord.character_id == char.id,
                BreachRecord.node_id == target_node.id,
                BreachRecord.raid_target_id == None
            ).order_by(BreachRecord.breached_at.desc())
            breach = (await session.execute(breach_stmt)).scalars().first()
            if breach:
                breach.breached_at = datetime.now(timezone.utc)
                breach.is_silent = is_silent
            else:
                session.add(BreachRecord(character_id=char.id, node_id=target_node.id, is_silent=is_silent))

            # Consume 1 charge of single-use exploit
            if exploit_item.quantity > 1:
                exploit_item.quantity -= 1
            else:
                await session.delete(exploit_item)

            # Very high detection risk if not silent
            alert_data = None
            is_owner = target_node.owner_character_id == char.id
            if not is_owner and not is_silent:
                target_node.ids_alerts += 1
                alert_msg = f"[GRID][ALARM] CRITICAL ZERO-DAY BREACH on {target_node.name} from {network} by: {char.name}!"
                if target_node.owner_character_id:
                    session.add(Memo(recipient_id=target_node.owner_character_id, message=alert_msg, source_node_id=target_node.id))
                alert_data = {
                    "target_network": target_network,
                    "alert_msg": alert_msg,
                    "recipient_id": target_node.owner_character_id,
                }

            await session.commit()
            return True, f"Zero-Day Exploit Deployed: {target_node.name} security bypassed with true damage (distance dampening ignored).", alert_data

    async def remote_raid(
        self, name: str, network: str, target_network: str, target_name: str
    ) -> Dict[str, Any]:
        """
        net <network> raid <target>:
        - High detection risk
        - -20% reward yield
        - CLOSED nodes require breach
        - Requires valid PROBE (< 5m old) unless exploit breach
        """
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.skills)
            )
            char = (await session.execute(stmt)).scalars().first()
            ok, msg, local_node = self.verify_remote_prerequisites(char, target_network)
            if not ok:
                return {"success": False, "msg": msg}

            # Locate target node
            clean_target = target_name.strip("[]").strip()
            target_stmt = select(GridNode).where(
                (func.lower(GridNode.name) == target_name.lower()) | (func.lower(GridNode.name) == clean_target.lower()),
                GridNode.net_affinity.ilike(target_network)
            )
            target_node = (await session.execute(target_stmt)).scalars().first()
            if not target_node:
                return {"success": False, "msg": f"Target '{target_name}' not detected on {target_network}."}

            if target_node.id == local_node.id:
                return {"success": False, "msg": "Target Conflict: Cannot target the local operating node via remote NET device."}

            tn_state = get_net_device_state(target_node)
            is_owner = target_node.owner_character_id == char.id
            if is_owner:
                return {"success": False, "msg": "Self-Raid Blocked: Cannot raid your own node."}

            # Check breach record
            expiry_limit = datetime.now(timezone.utc) - timedelta(seconds=300)
            breach_stmt = select(BreachRecord).where(
                BreachRecord.character_id == char.id,
                BreachRecord.node_id == target_node.id,
                BreachRecord.raid_target_id == None,
                BreachRecord.breached_at > expiry_limit
            ).order_by(BreachRecord.breached_at.desc())
            breach = (await session.execute(breach_stmt)).scalars().first()
            is_silent = breach.is_silent if breach else False

            # Access Gating: CLOSED and STEALTH require breach
            if tn_state in ["CLOSED", "STEALTH"] and not breach:
                return {
                    "success": False,
                    "msg": f"Cannot raid {tn_state} network. System protocols must be 'hacked' or 'exploited' first.",
                }

            # Sequence check: require PROBE unless silent breach
            if not is_silent:
                disc_stmt = select(DiscoveryRecord).where(
                    DiscoveryRecord.character_id == char.id,
                    DiscoveryRecord.node_id == target_node.id,
                    DiscoveryRecord.raid_target_id == None,
                    DiscoveryRecord.intel_level == 'PROBE',
                    DiscoveryRecord.discovered_at > expiry_limit
                ).order_by(DiscoveryRecord.id.desc())
                disc = (await session.execute(disc_stmt)).scalars().first()
                if not disc:
                    return {
                        "success": False,
                        "msg": f"ACCESS DENIED: Valid PROBE of {target_node.name} required (< 5m old).",
                    }

            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('raid', 15.0)
            if char.power < cost:
                return {"success": False, "msg": f"Insufficient POWER. Remote raid requires {cost} uP."}
            char.power -= cost

            # Calculate local base rewards
            scaling = 1.5 if target_node.upgrade_level >= 3 else 1.0
            base_c = int(random.randint(100, 300) * target_node.upgrade_level * scaling)
            base_d = round(random.uniform(30.0, 60.0) * target_node.upgrade_level * scaling, 2)

            # Apply remote distance modifier: -20% reward yield
            c_gain, d_gain = self.calculate_remote_raid_yield(base_c, base_d)

            char.credits += c_gain
            char.data_units += d_gain

            # Damage target node
            addons = json.loads(target_node.addons_json or "{}") if isinstance(target_node.addons_json, str) else (target_node.addons_json or {})
            dur_loss = 25.0
            if addons.get("FIREWALL"):
                dur_loss *= 0.5
                target_node.firewall_hits += 1
            target_node.durability = max(0.0, target_node.durability - dur_loss)

            # High detection risk: Alert routed to target node owner's network channel
            alert_data = None
            if not is_silent:
                target_node.ids_alerts += 1
                alert_msg = f"SECURITY BREACH: Node {target_node.name} RAIDED by {char.name} from {network}!"
                if target_node.owner_character_id:
                    session.add(Memo(recipient_id=target_node.owner_character_id, message=alert_msg, source_node_id=target_node.id))
                alert_data = {
                    "target_network": target_network,
                    "alert_msg": alert_msg,
                    "recipient_id": target_node.owner_character_id,
                }

            await session.commit()

            return {
                "success": True,
                "credits_gained": c_gain,
                "data_gained": d_gain,
                "yield_modifier": "-20%",
                "alert_data": alert_data,
                "msg": f"Remote Raid Successful! Extracted {c_gain}c and {d_gain:.1f} Data from {target_node.name} on {target_network} (-20% remote dampening).",
            }
