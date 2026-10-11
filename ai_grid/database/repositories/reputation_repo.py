import logging
import random
import re
from typing import Optional
from sqlalchemy import func
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from ai_grid.database.base_repo import BaseRepository
from ai_grid.models import Character, NetworkAlias, Player

logger = logging.getLogger("reputation_repo")

REPUTATION_RULES = {
    "MED": {"LEA": -5.0, "GOV": -3.0},
    "GOV": {"_DYNAMIC_LESS_DAMAGING": True, "_HEAT": 2.0},
    "MIL": {"LEA": -5.0, "MIL": -5.0, "_HEAT": 5.0},
    "CRP": {"GOV": -2.0, "LEA": -2.0},
    "CORP": {"GOV": -2.0, "LEA": -2.0},
    "ICS": {"GOV": -15.0, "MIL": -10.0},
    "UTL": {"GOV": -15.0, "MIL": -10.0},
}


KNOWN_REGIONS = {
    "CIV", "SMB", "CRP", "CORP", "EDU", "GOV", "MED",
    "MIL", "ORG", "LEA", "DTC", "POS", "ICS", "UTL",
    "ARN", "WAR", "VOD", "SAFEZONE",
}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def clean_region_key(region: Optional[str]) -> str:
    if not region:
        return ""
    s = str(region).strip()
    m = re.search(r"\[([A-Za-z0-9_]+)\]", s)
    if m:
        tag = m.group(1).upper()
        if tag in KNOWN_REGIONS:
            return tag
        sub = re.split(r"[_\-]", tag)[0]
        if sub in KNOWN_REGIONS:
            return sub
        return tag
    s_clean = s.strip("[]").strip().upper()
    if s_clean in KNOWN_REGIONS:
        return s_clean
    tokens = [t for t in re.split(r"[\s_\-:/]+", s_clean) if t]
    if tokens and tokens[0] in KNOWN_REGIONS:
        return tokens[0]
    for t in tokens:
        if t in REPUTATION_RULES:
            return t
    for t in tokens:
        if t in KNOWN_REGIONS:
            return t
    return s_clean


def rep_status(score: float) -> str:
    try:
        s = float(score if score is not None else 0.0)
    except (ValueError, TypeError):
        return "Unknown"
    if s >= 75.0:
        return "Trusted"
    if s >= 25.0:
        return "Neutral"
    if s > -25.0:
        return "Unknown"
    if s > -75.0:
        return "Flagged"
    return "Hostile"


def heat_status(heat: float) -> str:
    try:
        h = float(heat if heat is not None else 0.0)
    except (ValueError, TypeError):
        return "Passive"
    if h <= 2.0:
        return "Passive"
    if h <= 4.0:
        return "Alert"
    if h <= 6.0:
        return "Hostile"
    if h <= 8.0:
        return "Bounty"
    return "Critical"


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v if v is not None else default)
    except (ValueError, TypeError):
        return default


class ReputationRepository(BaseRepository):
    async def _get_character(self, nick: str, network: str, session):
        nick_lower = nick.lower()
        stmt = select(Character).join(Player).join(NetworkAlias).where(
            func.lower(Character.name) == nick_lower,
            func.lower(NetworkAlias.nickname) == nick_lower,
            NetworkAlias.network_name == network,
        ).options(selectinload(Character.skills), selectinload(Character.current_node))
        return (await session.execute(stmt)).scalars().first()

    async def update_rep(self, nick: str, network: str, node_type: str, delta: float):
        async with self.async_session() as session:
            char = await self._get_character(nick, network, session)
            if not char:
                return {"nick": nick, "status": "Unknown", "score": 0.0, "updated": False, "regions": {}, "heat": 0.0}

            rep_map = {clean_region_key(k): _safe_float(v) for k, v in (char.node_rep or {}).items() if clean_region_key(k)}
            region_key = clean_region_key(node_type) or "SAFEZONE"
            current = _safe_float(rep_map.get(region_key, 0.0))
            delta_val = _safe_float(delta, 0.0)
            updated_score = round(clamp(current + delta_val, -100.0, 100.0), 2)
            rep_map[region_key] = updated_score

            sec_heat = 0.0
            current_heat = _safe_float(char.mcp_heat, 0.0)
            if delta_val < 0:
                if region_key == "GOV":
                    # Dynamically penalize less damaging target between LEA and MIL
                    # (penalize whichever of LEA or MIL currently has higher reputation score by -10.0; if tied, penalize MIL), plus MCP Heat +2.0
                    lea_score = _safe_float(rep_map.get("LEA", 0.0))
                    mil_score = _safe_float(rep_map.get("MIL", 0.0))
                    target = "LEA" if lea_score > mil_score else "MIL"
                    current_target = _safe_float(rep_map.get(target, 0.0))
                    rep_map[target] = round(clamp(current_target - 10.0, -100.0, 100.0), 2)
                    sec_heat = 2.0
                elif region_key in REPUTATION_RULES:
                    for target_region, secondary_delta in REPUTATION_RULES[region_key].items():
                        if target_region == "_HEAT":
                            sec_heat = float(secondary_delta)
                            continue
                        target_value = _safe_float(rep_map.get(target_region, 0.0))
                        rep_map[target_region] = round(clamp(target_value + secondary_delta, -100.0, 100.0), 2)

                # Update updated_score in case region_key itself had a secondary penalty (e.g. MIL)
                updated_score = rep_map.get(region_key, updated_score)

                # Apply secondary heat increase with character stealth skill reduction
                if sec_heat > 0:
                    stealth_skill = next((s for s in char.skills if s.skill_name == 'stealth'), None) if char.skills else None
                    stealth_lvl = stealth_skill.level if stealth_skill else 0
                    effective_sec_heat = sec_heat * max(0.0, 1.0 - (0.10 * stealth_lvl)) if stealth_lvl > 0 else sec_heat
                    current_heat = round(clamp(current_heat + effective_sec_heat, 0.0, 10.0), 2)

            char.node_rep = rep_map
            char.mcp_heat = current_heat
            flag_modified(char, "node_rep")
            await session.commit()

            return {
                "nick": nick,
                "region": region_key,
                "score": updated_score,
                "status": rep_status(updated_score),
                "updated": True,
                "regions": rep_map,
                "heat": char.mcp_heat,
            }

    async def update_heat(self, nick: str, network: str, delta: float):
        async with self.async_session() as session:
            char = await self._get_character(nick, network, session)
            if not char:
                return 0.0

            effective_delta = _safe_float(delta, 0.0)
            if effective_delta > 0:
                stealth_skill = next((s for s in char.skills if s.skill_name == 'stealth'), None) if char.skills else None
                stealth_lvl = stealth_skill.level if stealth_skill else 0
                if stealth_lvl > 0:
                    effective_delta = effective_delta * max(0.0, 1.0 - (0.10 * stealth_lvl))

            current = _safe_float(char.mcp_heat, 0.0)
            updated_heat = round(clamp(current + effective_delta, 0.0, 10.0), 2)
            char.mcp_heat = updated_heat
            await session.commit()
            return updated_heat

    async def decay_reputation_and_heat(
        self,
        nick: str,
        network: str,
        elapsed_hours: float = 1.0,
        rep_decay_rate: float = 1.0,
        heat_decay_rate: float = 0.5,
    ) -> dict:
        """Passive time-based decay of reputation towards 0.0 and MCP heat cooldown."""
        async with self.async_session() as session:
            char = await self._get_character(nick, network, session)
            if not char:
                return {"nick": nick, "network": network, "heat": 0.0, "status": "Passive", "regions": {}, "decay_applied": False}

            hours = max(0.0, _safe_float(elapsed_hours, 1.0))
            r_rate = max(0.0, _safe_float(rep_decay_rate, 1.0))
            h_rate = max(0.0, _safe_float(heat_decay_rate, 0.5))
            rep_delta = r_rate * hours
            heat_delta = h_rate * hours

            rep_map = dict(char.node_rep or {})
            for r, score in list(rep_map.items()):
                s = _safe_float(score, 0.0)
                if s > 0:
                    rep_map[r] = round(max(0.0, s - rep_delta), 2)
                elif s < 0:
                    rep_map[r] = round(min(0.0, s + rep_delta), 2)
                else:
                    rep_map[r] = 0.0

            current_heat = _safe_float(char.mcp_heat, 0.0)
            new_heat = round(max(0.0, current_heat - heat_delta), 2)

            char.node_rep = rep_map
            char.mcp_heat = new_heat
            flag_modified(char, "node_rep")
            await session.commit()

            return {
                "nick": nick,
                "network": network,
                "heat": new_heat,
                "status": heat_status(new_heat),
                "regions": rep_map,
                "decay_applied": True,
                "elapsed_hours": hours,
            }

    async def apply_passive_decay(
        self,
        elapsed_hours: float = 1.0,
        rep_decay_rate: float = 1.0,
        heat_decay_rate: float = 0.5,
    ) -> dict:
        """Batch scheduled sweep for passive reputation and heat decay across all characters."""
        async with self.async_session() as session:
            stmt = select(Character).options(selectinload(Character.skills))
            chars = (await session.execute(stmt)).scalars().all()
            decayed_count = 0
            hours = max(0.0, _safe_float(elapsed_hours, 1.0))
            r_rate = max(0.0, _safe_float(rep_decay_rate, 1.0))
            h_rate = max(0.0, _safe_float(heat_decay_rate, 0.5))
            rep_delta = r_rate * hours
            heat_delta = h_rate * hours

            for char in chars:
                rep_map = dict(char.node_rep or {})
                heat = _safe_float(char.mcp_heat, 0.0)
                has_rep_decay = any(_safe_float(s, 0.0) != 0.0 for s in rep_map.values())
                has_heat_decay = heat > 0.0

                if has_rep_decay or has_heat_decay:
                    for r, score in list(rep_map.items()):
                        s = _safe_float(score, 0.0)
                        if s > 0:
                            rep_map[r] = round(max(0.0, s - rep_delta), 2)
                        elif s < 0:
                            rep_map[r] = round(min(0.0, s + rep_delta), 2)
                        else:
                            rep_map[r] = 0.0

                    char.node_rep = rep_map
                    char.mcp_heat = round(max(0.0, heat - heat_delta), 2)
                    flag_modified(char, "node_rep")
                    decayed_count += 1

            if decayed_count > 0:
                await session.commit()

            return {"decayed_count": decayed_count, "elapsed_hours": hours}

    async def check_defender_spawn(
        self,
        nick: str,
        network: str,
        region_type: Optional[str] = None,
        roll: Optional[float] = None,
    ) -> dict:
        """Threshold-triggered defender mob spawn check upon node entry."""
        async with self.async_session() as session:
            char = await self._get_character(nick, network, session)
            if not char:
                return {"spawn": False, "status": "Unknown", "score": 0.0, "chance": 0.0, "threat": 0, "mob_name": None}

            if not region_type and char.current_node:
                raw_reg = str(char.current_node.region_type or "")
            else:
                raw_reg = str(region_type or "")
            reg = clean_region_key(raw_reg)

            rep_map = dict(char.node_rep or {})
            score = _safe_float(rep_map.get(reg, 0.0))
            status = rep_status(score)

            chance = 0.0
            threat = 0
            mob_name = None

            if status == "Flagged":
                chance = 0.25
                threat = 1
                mob_name = "Rogue_Process"
            elif status == "Hostile":
                chance = 0.75
                threat = 2
                mob_name = "ICE_Drone"

            r = roll if roll is not None else random.random()
            should_spawn = (r < chance) if chance > 0 else False

            return {
                "spawn": should_spawn,
                "status": status,
                "score": score,
                "region": reg,
                "chance": chance,
                "roll": r,
                "threat": threat if should_spawn else 0,
                "mob_name": mob_name if should_spawn else None,
            }

    check_node_entry_encounter = check_defender_spawn

    async def is_bounty_eligible(self, nick: str, network: str) -> dict:
        """Eligible for bounty flags when hostile with 2+ region types or MCP heat > 6.0."""
        async with self.async_session() as session:
            char = await self._get_character(nick, network, session)
            if not char:
                return {"eligible": False, "is_bounty_eligible": False, "hostile_regions": [], "heat": 0.0, "status": "Passive", "reasons": []}

            rep_map = dict(char.node_rep or {})
            heat_val = _safe_float(char.mcp_heat, 0.0)
            hostile_regions = sorted(list({
                clean_region_key(r)
                for r, s in rep_map.items()
                if rep_status(_safe_float(s, 0.0)) == "Hostile" and clean_region_key(r)
            }))
            is_hostile_multi = len(hostile_regions) >= 2
            is_heat_bounty = heat_val > 6.0
            eligible = is_hostile_multi or is_heat_bounty

            reasons = []
            if is_hostile_multi:
                reasons.append(f"Hostile with {len(hostile_regions)} regions: {', '.join(hostile_regions)}")
            if is_heat_bounty:
                reasons.append(f"MCP Heat {heat_val:.2f} > 6.0 ({heat_status(heat_val)})")

            return {
                "eligible": eligible,
                "is_bounty_eligible": eligible,
                "hostile_regions": hostile_regions,
                "heat": heat_val,
                "status": heat_status(heat_val),
                "reasons": reasons,
            }

    async def get_rep_summary(self, nick: str, network: str):
        async with self.async_session() as session:
            char = await self._get_character(nick, network, session)
            if not char:
                return {"nick": nick, "network": network, "heat": 0.0, "status": "Passive", "regions": {}, "bounty_eligible": False}

            rep_map = dict(char.node_rep or {})
            heat_value = _safe_float(char.mcp_heat, 0.0)
            status = heat_status(heat_value)
            hostile_regions = sorted(list({
                clean_region_key(r)
                for r, s in rep_map.items()
                if rep_status(_safe_float(s, 0.0)) == "Hostile" and clean_region_key(r)
            }))
            bounty_eligible = len(hostile_regions) >= 2 or heat_value > 6.0
            return {
                "nick": nick,
                "network": network,
                "heat": round(heat_value, 2),
                "status": status,
                "regions": {k: round(_safe_float(v, 0.0), 2) for k, v in rep_map.items()},
                "bounty_eligible": bounty_eligible,
            }
