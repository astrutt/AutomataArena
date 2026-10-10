import datetime
import os
import unittest

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_grid.models import Base, Character, GridNode, InventoryItem, ItemTemplate, NetworkAlias, Player
from ai_grid.database.repositories.territory_repo import TerritoryRepository


class TestNodeStashRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_node_stash_{int(datetime.datetime.now().timestamp() * 1000)}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with self.async_session() as session:
            player = Player(global_name="Alpha", is_autonomous=False)
            session.add(player)
            await session.flush()
            session.add(NetworkAlias(player_id=player.id, network_name="rizon", nickname="Alpha"))
            char = Character(
                player_id=player.id,
                name="Alpha",
                race="Wetware",
                char_class="PyFighter",
                credits=100.0,
                power=100.0,
            )
            session.add(char)
            await session.flush()

            node = GridNode(name="AlphaNode", node_type="safezone", owner_character_id=char.id, stash_inventory=[])
            session.add(node)
            await session.flush()

            char.node_id = node.id
            session.add(ItemTemplate(name="Nano_Patch", item_type="gear", base_value=250))
            await session.commit()

        self.repo = TerritoryRepository(self.async_session)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_stash_store_and_take_round_trip(self):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == 'Alpha',
                NetworkAlias.nickname == 'Alpha',
                NetworkAlias.network_name == 'rizon'
            ).options(selectinload(Character.inventory).selectinload(InventoryItem.template))
            char = (await session.execute(stmt)).scalars().first()
            tmpl = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == 'Nano_Patch'))).scalars().first()
            session.add(InventoryItem(character_id=char.id, template_id=tmpl.id, quantity=1))
            await session.commit()

        ok, msg = await self.repo.stash_store('Alpha', 'rizon', 'AlphaNode', 'Nano_Patch')
        self.assertTrue(ok)
        self.assertIn('stored', msg.lower())

        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == 'AlphaNode'))).scalars().first()
            self.assertEqual(node.stash_inventory, ['Nano_Patch'])

        ok, msg = await self.repo.stash_take('Alpha', 'rizon', 'AlphaNode', 'Nano_Patch')
        self.assertTrue(ok)
        self.assertIn('taken', msg.lower())

        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == 'AlphaNode'))).scalars().first()
            self.assertEqual(node.stash_inventory, [])

    async def test_stash_take_respects_inventory_capacity(self):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == 'Alpha',
                NetworkAlias.nickname == 'Alpha',
                NetworkAlias.network_name == 'rizon'
            ).options(selectinload(Character.inventory).selectinload(InventoryItem.template))
            char = (await session.execute(stmt)).scalars().first()
            node = (await session.execute(select(GridNode).where(GridNode.name == 'AlphaNode'))).scalars().first()
            tmpl = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == 'Nano_Patch'))).scalars().first()
            node.owner_character_id = char.id
            node.stash_inventory = ['Nano_Patch']
            for index in range(4):
                session.add(InventoryItem(character_id=char.id, template_id=tmpl.id, quantity=1))
            await session.commit()

        ok, msg = await self.repo.stash_take('Alpha', 'rizon', 'AlphaNode', 'Nano_Patch')
        self.assertFalse(ok)
        self.assertIn('capacity', msg.lower())


if __name__ == '__main__':
    unittest.main()
