
import asyncio
import unittest
from datetime import datetime, timezone, timedelta
from ai_grid.database.repositories.pulse_repo import PulseRepository
from ai_grid.database.repositories.incursion_repo import IncursionRepository
from ai_grid.database.repositories.territory_repo import TerritoryRepository
from models import Character, GridNode, PulseEvent, IncursionEvent, Player, NetworkAlias, Base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

class TestRemoteCoordination(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        self.AsyncSession = sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self.pulse_repo = PulseRepository(self.AsyncSession)
        self.inc_repo = IncursionRepository(self.AsyncSession)
        self.terr_repo = TerritoryRepository(self.AsyncSession)

    async def _setup_basic_state(self):
        async with self.AsyncSession() as session:
            node_a = GridNode(name="SectorA", net_affinity="2600net", node_type="void")
            node_b = GridNode(name="SectorB", net_affinity="2600net", node_type="void")
            session.add_all([node_a, node_b])
            await session.commit()
            
            p = Player(global_name="ShortDiodes")
            session.add(p)
            await session.commit()
            
            char = Character(
                name="ShortDiodes", player_id=p.id, node_id=node_b.id, 
                power=100.0, credits=100, level=1, xp=0, race="Human", char_class="Hacker"
            )
            session.add(char)
            session.add(NetworkAlias(player_id=p.id, nickname="ShortDiodes", network_name="2600net"))
            
            pulse = PulseEvent(
                node_id=node_a.id, network_name="2600net", event_type="GLITCH", 
                status="ACTIVE", expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)
            )
            session.add(pulse)
            await session.commit()

    async def test_remote_patch_success(self):
        """Verify !a patch works from a different node."""
        await self._setup_basic_state()
        success, msg = await self.pulse_repo.resolve_pulse("ShortDiodes", "2600net", "SectorA", "patch")
        self.assertTrue(success, f"Remote patch failed: {msg}")
        self.assertIn("SUCCESS", msg)

    async def test_remote_claim_failure(self):
        """Verify !a claim fails when not physically present."""
        await self._setup_basic_state()
        success, msg = await self.terr_repo.claim_node("ShortDiodes", "2600net", "SectorA")
        self.assertFalse(success, "Remote claim should have failed")
        self.assertIn("Physical presence required", msg)

    async def test_remote_repair_success(self):
        """Verify !a repair works from a different node (Targeted)."""
        await self._setup_basic_state()
        success, msg = await self.terr_repo.grid_repair("ShortDiodes", "2600net", "SectorA")
        self.assertTrue(success, f"Remote repair failed: {msg}")
        self.assertIn("Nodal integrity augmented", msg)

if __name__ == "__main__":
    unittest.main()
