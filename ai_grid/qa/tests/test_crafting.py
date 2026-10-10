import datetime
import os
import unittest

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_grid.models import Base, Character, InventoryItem, ItemTemplate, NetworkAlias, Player
from ai_grid.database.repositories.economy_repo import EconomyRepository


class TestCraftingRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_crafting_{int(datetime.datetime.now().timestamp() * 1000)}.db"
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
                data_units=0.0,
                power=100.0,
            )
            session.add(char)
            await session.flush()

            for template_name in ("Vulnerability", "ZeroDay_Chain"):
                session.add(ItemTemplate(
                    name=template_name,
                    item_type="hack",
                    base_value=500 if template_name == "Vulnerability" else 2500,
                    effects_json='{}'
                ))

            await session.commit()

        self.repo = EconomyRepository(self.async_session)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_craft_vulnerability_recipe(self):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == 'Alpha',
                NetworkAlias.nickname == 'Alpha',
                NetworkAlias.network_name == 'rizon'
            )
            char = (await session.execute(stmt)).scalars().first()
            char.data_units = 10.0
            await session.commit()

        result = await self.repo.craft_item('Alpha', 'rizon', 'vuln')
        self.assertTrue(result['success'])
        self.assertEqual(result['item'], 'Vulnerability')

        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == 'Alpha',
                NetworkAlias.nickname == 'Alpha',
                NetworkAlias.network_name == 'rizon'
            ).options(selectinload(Character.inventory).selectinload(InventoryItem.template))
            char = (await session.execute(stmt)).scalars().first()
            self.assertEqual(char.data_units, 0.0)
            self.assertEqual(sum(i.quantity for i in char.inventory if i.template.name == 'Vulnerability'), 1)

    async def test_craft_zeroday_recipe(self):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == 'Alpha',
                NetworkAlias.nickname == 'Alpha',
                NetworkAlias.network_name == 'rizon'
            ).options(selectinload(Character.inventory).selectinload(InventoryItem.template))
            char = (await session.execute(stmt)).scalars().first()
            char.data_units = 200.0
            vuln_template = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == 'Vulnerability'))).scalars().first()
            session.add(InventoryItem(character_id=char.id, template_id=vuln_template.id, quantity=15))
            await session.commit()

        result = await self.repo.craft_item('Alpha', 'rizon', 'zeroday', 2)
        self.assertTrue(result['success'])
        self.assertEqual(result['item'], 'ZeroDay_Chain')

        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == 'Alpha',
                NetworkAlias.nickname == 'Alpha',
                NetworkAlias.network_name == 'rizon'
            ).options(selectinload(Character.inventory).selectinload(InventoryItem.template))
            char = (await session.execute(stmt)).scalars().first()
            self.assertEqual(char.data_units, 0.0)
            self.assertEqual(sum(i.quantity for i in char.inventory if i.template.name == 'ZeroDay_Chain'), 1)

    async def test_craft_menu(self):
        menu = await self.repo.get_craft_menu()
        self.assertIn('vuln', menu.lower())
        self.assertIn('zeroday', menu.lower())


if __name__ == '__main__':
    unittest.main()
