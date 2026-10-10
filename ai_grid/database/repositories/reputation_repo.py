import logging
from sqlalchemy import func
from sqlalchemy.future import select

from ai_grid.database.base_repo import BaseRepository
from ai_grid.models import Character, NetworkAlias, Player

logger = logging.getLogger("reputation_repo")

REPUTATION_RULES = {
    "MED": {"LEA": -5.0, "GOV": -3.0},
    "GOV": {"MIL": -10.0, "_HEAT": 2.0},
    "MIL": {"_HEAT": 5.0, "LEA": -5.0},
    "CRP": {"GOV": -2.0},
    "CORP": {"GOV": -2.0},
    "ICS": {"GOV": -15.0, "MIL": -10.0},
    "UTL": {"GOV": -15.0, "MIL": -10.0},
}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def rep_status(score: float) -> str:
    if score >= 75:
        return "Trusted"
    if score >= 25:
        return "Neutral"
    if score >= -24:
        return "Unknown"
    if score >= -74:
        return "Flagged"
    return "Hostile"


def heat_status(heat: float) -> str:
    if heat <= 2.0:
        return "Passive"
    if heat <= 4.0:
        return "Alert"
    if heat <= 6.0:
        return "Hostile"
    if heat <= 8.0:
        return "Bounty"
    return "Critical"


class ReputationRepository(BaseRepository):
    async def _get_character(self, nick: str, network: str, session):
        nick_lower = nick.lower()
        stmt = select(Character).join(Player).join(NetworkAlias).where(
            func.lower(Character.name) == nick_lower,
            func.lower(NetworkAlias.nickname) == nick_lower,
            NetworkAlias.network_name == network,
        )
        return (await session.execute(stmt)).scalars().first()

    async def update_rep(self, nick: str, network: str, node_type: str, delta: float):
        async with self.async_session() as session:
            char = await self._get_character(nick, network, session)
            if not char:
                return {"nick": nick, "status": "Unknown", "score": 0.0, "updated": False}

            rep_map = dict(char.node_rep or {})
            region_key = str(node_type or "SAFEZONE").upper()
            current = float(rep_map.get(region_key, 0.0))
            updated_score = round(clamp(current + float(delta), -100.0, 100.0), 2)
            rep_map[region_key] = updated_score

            if float(delta) < 0:
                for target_region, secondary_delta in REPUTATION_RULES.get(region_key, {}).items():
                    if target_region == "_HEAT":
                        continue
                    target_value = float(rep_map.get(target_region, 0.0))
                    rep_map[target_region] = round(clamp(target_value + secondary_delta, -100.0, 100.0), 2)

            char.node_rep = rep_map
            await session.commit()

            return {
                "nick": nick,
                "region": region_key,
                "score": updated_score,
                "status": rep_status(updated_score),
                "updated": True,
                "regions": rep_map,
            }

    async def update_heat(self, nick: str, network: str, delta: float):
        async with self.async_session() as session:
            char = await self._get_character(nick, network, session)
            if not char:
                return 0.0

            current = float(char.mcp_heat or 0.0)
            updated_heat = round(clamp(current + float(delta), 0.0, 10.0), 2)
            char.mcp_heat = updated_heat
            await session.commit()
            return updated_heat

    async def get_rep_summary(self, nick: str, network: str):
        async with self.async_session() as session:
            char = await self._get_character(nick, network, session)
            if not char:
                return {"nick": nick, "network": network, "heat": 0.0, "status": "Passive", "regions": {}}

            rep_map = dict(char.node_rep or {})
            heat_value = float(char.mcp_heat or 0.0)
            status = heat_status(heat_value)
            return {
                "nick": nick,
                "network": network,
                "heat": round(heat_value, 2),
                "status": status,
                "regions": {k: round(float(v), 2) for k, v in rep_map.items()},
            }
