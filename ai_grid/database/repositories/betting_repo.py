import math
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple
from sqlalchemy.future import select
from sqlalchemy import func
from ai_grid.models import Character, Player, NetworkAlias, ArenaBet
from ai_grid.database.core import logger

class BetRecord(dict):
    def __getattr__(self, name):
        if name in self:
            return self[name]
        if name == "bettor_nick":
            return self.get("nick")
        if name == "chosen_fighter":
            return self.get("fighter")
        raise AttributeError(f"'BetRecord' object has no attribute '{name}'")

class BettingRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def place_bet(
        self,
        nick: str,
        network: str,
        match_id: str,
        fighter: str,
        amount: float,
        valid_fighters: Optional[List[str]] = None
    ) -> Tuple[bool, str]:
        if amount is None or not isinstance(amount, (int, float)) or math.isnan(amount) or math.isinf(amount) or amount <= 0:
            return False, "Bet amount must be greater than 0."

        if valid_fighters and fighter.lower() not in [f.lower() for f in valid_fighters]:
            return False, f"Invalid fighter: '{fighter}' is not in this match. Valid fighters: {', '.join(valid_fighters)}"

        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == nick.lower(),
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char:
                return False, f"Player character '{nick}' not found on {network}."

            if char.credits < amount:
                return False, f"Insufficient credits. You have {char.credits:.0f}c, but bet requires {amount:.0f}c."

            char.credits -= amount
            bet = ArenaBet(
                match_id=match_id,
                player_id=char.player_id,
                nick=nick,
                network=network,
                fighter=fighter,
                amount=amount,
                payout=0.0,
                status="PENDING",
                created_at=datetime.now(timezone.utc)
            )
            session.add(bet)
            await session.commit()
            return True, f"Bet registered: {amount:.0f}c on {fighter} (Match: {match_id}). Remaining credits: {char.credits:.0f}c."

    async def resolve_bets(self, match_id: str, winner_name: str, odds: float = 2.0) -> List[Dict]:
        results = []
        async with self.async_session() as session:
            stmt = select(ArenaBet).where(
                ArenaBet.match_id == match_id,
                ArenaBet.status == "PENDING"
            )
            bets = (await session.execute(stmt)).scalars().all()
            now = datetime.now(timezone.utc)

            for bet in bets:
                stmt_char = select(Character).join(Player).join(NetworkAlias).where(
                    func.lower(Character.name) == bet.nick.lower(),
                    NetworkAlias.network_name == bet.network
                )
                char = (await session.execute(stmt_char)).scalars().first()

                if bet.fighter.lower() == winner_name.lower():
                    payout = round(bet.amount * odds, 2)
                    bet.status = "WON"
                    bet.payout = payout
                    bet.resolved_at = now
                    if char:
                        char.credits += payout
                    results.append(BetRecord({"id": bet.id, "nick": bet.nick, "fighter": bet.fighter, "amount": bet.amount, "payout": payout, "status": "WON"}))
                else:
                    bet.status = "LOST"
                    bet.payout = 0.0
                    bet.resolved_at = now

            await session.commit()
        return results

    async def refund_bets(self, match_id: str) -> List[Dict]:
        refunds = []
        async with self.async_session() as session:
            stmt = select(ArenaBet).where(
                ArenaBet.match_id == match_id,
                ArenaBet.status == "PENDING"
            )
            bets = (await session.execute(stmt)).scalars().all()
            now = datetime.now(timezone.utc)

            for bet in bets:
                stmt_char = select(Character).join(Player).join(NetworkAlias).where(
                    func.lower(Character.name) == bet.nick.lower(),
                    NetworkAlias.network_name == bet.network
                )
                char = (await session.execute(stmt_char)).scalars().first()

                bet.status = "REFUNDED"
                bet.payout = bet.amount
                bet.resolved_at = now
                if char:
                    char.credits += bet.amount
                refunds.append(BetRecord({"id": bet.id, "nick": bet.nick, "fighter": bet.fighter, "amount": bet.amount, "payout": bet.amount, "status": "REFUNDED"}))

            await session.commit()
        return refunds

    async def get_match_bets(self, match_id: str) -> List[Dict]:
        async with self.async_session() as session:
            stmt = select(ArenaBet).where(ArenaBet.match_id == match_id)
            bets = (await session.execute(stmt)).scalars().all()
            return [BetRecord({"id": b.id, "nick": b.nick, "fighter": b.fighter, "amount": b.amount, "payout": b.payout, "status": b.status}) for b in bets]
