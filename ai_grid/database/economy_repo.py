# economy_repo.py
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from models import Character, Player, NetworkAlias, ItemTemplate, InventoryItem, GridNode
from .core import logger

class EconomyRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def list_shop_items(self):
        async with self.async_session() as session:
            stmt = select(ItemTemplate).order_by(ItemTemplate.base_value.asc())
            result = await session.execute(stmt)
            return [{'name': t.name, 'type': t.item_type, 'cost': t.base_value} for t in result.scalars().all()]

    async def award_credits_bulk(self, payouts: dict, network: str):
        async with self.async_session() as session:
            for nick, amt in payouts.items():
                stmt = select(Character).join(Player).join(NetworkAlias).where(
                    Character.name == nick,
                    NetworkAlias.nickname == nick,
                    NetworkAlias.network_name == network
                )
                result = await session.execute(stmt)
                char = result.scalars().first()
                if char:
                    char.credits += amt
            await session.commit()

    async def process_transaction(self, name: str, network: str, action: str, item_name: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.inventory).selectinload(InventoryItem.template)
            )
            result = await session.execute(stmt)
            char = result.scalars().first()
            if not char: return False, "System offline: Fighter not found."
            if not char.current_node or char.current_node.node_type != "merchant":
                return False, "Transaction Failed: No merchant in this node."
                
            stmt_item = select(ItemTemplate).where(ItemTemplate.name.ilike(item_name))
            result = await session.execute(stmt_item)
            tpl = result.scalars().first()
            if not tpl: return False, f"Unknown item: '{item_name}'"
            
            if action == "buy":
                if char.credits < tpl.base_value:
                    return False, f"Insufficient credits. {tpl.name} costs {tpl.base_value}c."
                char.credits -= tpl.base_value
                
                existing = next((i for i in char.inventory if i.template_id == tpl.id), None)
                if existing:
                    existing.quantity += 1
                else:
                    new_item = InventoryItem(character_id=char.id, template_id=tpl.id)
                    session.add(new_item)
                
                await session.commit()
                return True, f"Purchased {tpl.name} for {tpl.base_value}c. Balance: {char.credits}c."
            
            elif action == "sell":
                existing = next((i for i in char.inventory if i.template_id == tpl.id and i.quantity > 0), None)
                if not existing:
                    return False, f"You do not possess a {tpl.name}."
                
                sell_price = max(1, int(tpl.base_value * 0.5))
                char.credits += sell_price
                existing.quantity -= 1
                if existing.quantity <= 0:
                    await session.delete(existing)
                
                await session.commit()
                return True, f"Sold {tpl.name} for {sell_price}c. Balance: {char.credits}c."
            return False, "Invalid action."
