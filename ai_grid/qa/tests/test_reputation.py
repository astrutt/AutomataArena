# tests/test_reputation.py
import datetime
import os
import unittest

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_grid.models import Base, Character, NetworkAlias, Player
from ai_grid.database.repositories.reputation_repo import ReputationRepository


class TestReputationRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_reputation_{int(datetime.datetime.now().timestamp() * 1000)}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with self.async_session() as session:
            player = Player(global_name="Alpha", is_autonomous=False)
            session.add(player)
            await session.flush()
            session.add(NetworkAlias(player_id=player.id, network_name="rizon", nickname="Alpha"))
            session.add(Character(
                player_id=player.id,
                name="Alpha",
                race="Wetware",
                char_class="PyFighter",
                credits=100.0,
                mcp_heat=0.0,
                node_rep={}
            ))
            await session.commit()

        self.repo = ReputationRepository(self.async_session)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_schema_includes_reputation_fields(self):
        async with self.engine.connect() as conn:
            def check_schema(connection):
                insp = inspect(connection)
                cols = [c['name'] for c in insp.get_columns('characters')]
                self.assertIn('mcp_heat', cols)
                self.assertIn('node_rep', cols)

            await conn.run_sync(check_schema)

    async def test_update_rep_and_heat(self):
        rep = await self.repo.update_rep('Alpha', 'rizon', 'MED', -25.0)
        self.assertEqual(rep['score'], -25.0)
        self.assertEqual(rep['status'], 'Flagged')

        heat = await self.repo.update_heat('Alpha', 'rizon', 2.5)
        self.assertEqual(heat, 2.5)

    async def test_get_rep_summary(self):
        await self.repo.update_rep('Alpha', 'rizon', 'MED', -25.0)
        await self.repo.update_heat('Alpha', 'rizon', 3.0)

        summary = await self.repo.get_rep_summary('Alpha', 'rizon')
        self.assertEqual(summary['heat'], 3.0)
        self.assertEqual(summary['status'], 'Alert')
        self.assertIn('MED', summary['regions'])


if __name__ == '__main__':
    unittest.main()
