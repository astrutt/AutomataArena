# ai_grid/database/spectator_repo.py
import datetime
from datetime import timezone, timedelta
import logging
from sqlalchemy import func
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError, OperationalError
from ai_grid.database.base_repo import BaseRepository
from ai_grid.database.core import Spectator, logger
import asyncio


class SpectatorRepository(BaseRepository):
    def __init__(self, async_session):
        super().__init__(async_session)

    async def upsert_spectator(self, nick: str, network: str) -> Spectator | None:
        """
        Creates a new spectator record on first call, or returns existing record.
        Idempotent on successive calls.
        """
        if not nick or not network:
            return None

        for attempt in range(5):
            try:
                async with self.async_session() as session:
                    stmt = select(Spectator).where(
                        func.lower(Spectator.nick) == nick.lower(),
                        func.lower(Spectator.network) == network.lower()
                    )
                    spec = (await session.execute(stmt)).scalars().first()
                    if spec:
                        return spec

                    now = datetime.datetime.now(timezone.utc)
                    spec = Spectator(
                        nick=nick,
                        network=network,
                        xp=0,
                        credits=0.0,
                        idle_hours=0.0,
                        message_count=0,
                        lifetime_messages=0,
                        last_seen=now,
                        joined_at=now,
                        created_at=now
                    )
                    session.add(spec)
                    try:
                        await session.commit()
                        await session.refresh(spec)
                        return spec
                    except IntegrityError:
                        await session.rollback()
                        stmt = select(Spectator).where(
                            func.lower(Spectator.nick) == nick.lower(),
                            func.lower(Spectator.network) == network.lower()
                        )
                        res = (await session.execute(stmt)).scalars().first()
                        if res:
                            return res
                        continue
            except OperationalError as e:
                if "locked" in str(e).lower() and attempt < 4:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise

    async def record_message(self, nick: str, network: str) -> Spectator | None:
        """
        Increments message_count and lifetime_messages, and refreshes last_seen.
        """
        if not nick or not network:
            return None

        for attempt in range(5):
            try:
                async with self.async_session() as session:
                    stmt = select(Spectator).where(
                        func.lower(Spectator.nick) == nick.lower(),
                        func.lower(Spectator.network) == network.lower()
                    )
                    spec = (await session.execute(stmt)).scalars().first()
                    now = datetime.datetime.now(timezone.utc)
                    if not spec:
                        spec = Spectator(
                            nick=nick,
                            network=network,
                            xp=0,
                            credits=0.0,
                            idle_hours=0.0,
                            message_count=1,
                            lifetime_messages=1,
                            last_seen=now,
                            joined_at=now,
                            created_at=now
                        )
                        session.add(spec)
                        try:
                            await session.commit()
                            await session.refresh(spec)
                            return spec
                        except IntegrityError:
                            await session.rollback()
                            stmt = select(Spectator).where(
                                func.lower(Spectator.nick) == nick.lower(),
                                func.lower(Spectator.network) == network.lower()
                            )
                            spec = (await session.execute(stmt)).scalars().first()
                            if spec:
                                spec.message_count = (spec.message_count or 0) + 1
                                spec.lifetime_messages = (spec.lifetime_messages or 0) + 1
                                spec.last_seen = now
                                await session.commit()
                                await session.refresh(spec)
                                return spec
                            continue
                    else:
                        spec.message_count = (spec.message_count or 0) + 1
                        spec.lifetime_messages = (spec.lifetime_messages or 0) + 1
                        spec.last_seen = now
                        await session.commit()
                        await session.refresh(spec)
                        return spec
            except OperationalError as e:
                if "locked" in str(e).lower() and attempt < 4:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise

    async def get_spectator(self, nick: str, network: str) -> Spectator | None:
        """
        Fetches spectator record by nickname and network.
        """
        if not nick or not network:
            return None

        async with self.async_session() as session:
            stmt = select(Spectator).where(
                func.lower(Spectator.nick) == nick.lower(),
                func.lower(Spectator.network) == network.lower()
            )
            return (await session.execute(stmt)).scalars().first()

    async def get_all_active(self, since_minutes=90, network=None, **kwargs) -> list[Spectator]:
        """
        Retrieves active spectators who have been seen within `since_minutes` (default 90).
        Excludes spectators whose last_seen exceeds the threshold.
        Supports:
          get_all_active()
          get_all_active(since_minutes=90)
          get_all_active(network="rizon", since_minutes=90)
          get_all_active("rizon", 90)
          get_all_active(90, "rizon")
        """
        if isinstance(since_minutes, str):
            temp_net = since_minutes
            if isinstance(network, (int, float)):
                since_minutes = int(network)
            else:
                since_minutes = 90
            network = temp_net
        else:
            since_minutes = int(since_minutes) if since_minutes is not None else 90

        if 'since_minutes' in kwargs:
            since_minutes = kwargs['since_minutes']
        if 'network' in kwargs:
            network = kwargs['network']

        async with self.async_session() as session:
            stmt = select(Spectator)
            if network:
                stmt = stmt.where(func.lower(Spectator.network) == network.lower())
            results = (await session.execute(stmt)).scalars().all()

            now = datetime.datetime.now(timezone.utc)
            cutoff = now - timedelta(minutes=since_minutes)
            active = []
            for s in results:
                ls = s.last_seen
                if ls is not None:
                    if ls.tzinfo is None:
                        ls = ls.replace(tzinfo=timezone.utc)
                    if ls >= cutoff:
                        active.append(s)
            return active

    async def apply_payout(self, nick: str, network: str, xp: int, credits: float) -> Spectator | None:
        """
        Atomically increments XP and Credits for the given spectator.
        """
        if not nick or not network:
            return None

        for attempt in range(5):
            try:
                async with self.async_session() as session:
                    stmt = select(Spectator).where(
                        func.lower(Spectator.nick) == nick.lower(),
                        func.lower(Spectator.network) == network.lower()
                    )
                    spec = (await session.execute(stmt)).scalars().first()
                    if not spec:
                        return None
                    spec.xp = (spec.xp or 0) + max(0, int(xp))
                    spec.credits = (spec.credits or 0.0) + max(0.0, float(credits))
                    await session.commit()
                    await session.refresh(spec)
                    return spec
            except OperationalError as e:
                if "locked" in str(e).lower() and attempt < 4:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise

    async def record_idle_hours(self, nick: str, network: str, hours: float = 1.0) -> Spectator | None:
        """
        Increments idle_hours by `hours` (default 1.0).
        """
        if not nick or not network:
            return None

        for attempt in range(5):
            try:
                async with self.async_session() as session:
                    stmt = select(Spectator).where(
                        func.lower(Spectator.nick) == nick.lower(),
                        func.lower(Spectator.network) == network.lower()
                    )
                    spec = (await session.execute(stmt)).scalars().first()
                    if not spec:
                        return None
                    spec.idle_hours = (spec.idle_hours or 0.0) + max(0.0, float(hours))
                    await session.commit()
                    await session.refresh(spec)
                    return spec
            except OperationalError as e:
                if "locked" in str(e).lower() and attempt < 4:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise

    async def reset_message_count(self, nick: str, network: str) -> Spectator | None:
        """
        Resets message_count to 0 following hourly payout distribution.
        """
        if not nick or not network:
            return None

        for attempt in range(5):
            try:
                async with self.async_session() as session:
                    stmt = select(Spectator).where(
                        func.lower(Spectator.nick) == nick.lower(),
                        func.lower(Spectator.network) == network.lower()
                    )
                    spec = (await session.execute(stmt)).scalars().first()
                    if not spec:
                        return None
                    spec.message_count = 0
                    await session.commit()
                    await session.refresh(spec)
                    return spec
            except OperationalError as e:
                if "locked" in str(e).lower() and attempt < 4:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
                raise


SpectatorRepo = SpectatorRepository
__all__ = ['SpectatorRepository', 'SpectatorRepo']
