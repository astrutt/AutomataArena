# database/repositories/communication_repo.py
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from models import Character, Player, NetworkAlias, Memo
from ..base_repo import BaseRepository

class CommunicationRepository(BaseRepository):
    async def get_memos(self, name: str, network: str, only_unread: bool = False) -> list:
        """Retrieves system memos for a character."""
        async with self.async_session() as session:
            stmt = select(Memo).join(Character, Memo.recipient_id == Character.id).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Memo.sender), selectinload(Memo.source_node))
            
            if only_unread:
                stmt = stmt.where(Memo.is_read == False)
            
            memos = (await session.execute(stmt.order_by(Memo.timestamp.desc()))).scalars().all()
            return [{
                "id": m.id,
                "sender": m.sender.name if m.sender else "SYSTEM",
                "message": m.message,
                "timestamp": m.timestamp,
                "is_read": m.is_read,
                "node": m.source_node.name if m.source_node else None
            } for m in memos]

    async def mark_memos_read(self, name: str, network: str) -> int:
        """Marks all unread memos as read for a character."""
        async with self.async_session() as session:
            char = await self.get_character_by_nick(name, network, session)
            if not char: return 0
            
            stmt = select(Memo).where(Memo.recipient_id == char.id, Memo.is_read == False)
            memos = (await session.execute(stmt)).scalars().all()
            for m in memos:
                m.is_read = True
            await session.commit()
            return len(memos)
