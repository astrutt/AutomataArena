# tests/test_reputation.py
import datetime
import os
import unittest

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_grid.models import Base, Character, CharacterSkill, GridNode, ItemTemplate, NetworkAlias, Player
from ai_grid.database.repositories.reputation_repo import ReputationRepository, rep_status, heat_status
from ai_grid.database.repositories.economy_repo import EconomyRepository
from ai_grid.database.repositories.discovery_repo import DiscoveryRepository


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
            char = Character(
                player_id=player.id,
                name="Alpha",
                race="Wetware",
                char_class="PyFighter",
                credits=200.0,
                mcp_heat=0.0,
                node_rep={}
            )
            session.add(char)
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

    # --- R1: Cross-Type Consequences & Secondary Heat Tests ---

    async def test_cross_type_med_attack(self):
        """R1: [MED] attacked/hacked: [LEA] rep -5.0, [GOV] rep -3.0."""
        rep = await self.repo.update_rep('Alpha', 'rizon', 'MED', -10.0)
        self.assertEqual(rep['score'], -10.0)
        self.assertEqual(rep['regions']['MED'], -10.0)
        self.assertEqual(rep['regions']['LEA'], -5.0)
        self.assertEqual(rep['regions']['GOV'], -3.0)
        # No secondary heat for MED
        self.assertEqual(rep['heat'], 0.0)

    async def test_cross_type_gov_attack_dynamic_mil_lea_penalty(self):
        """
        R1: [GOV] attacked/hacked: Dynamically penalize whichever of [LEA] or [MIL]
        currently has higher reputation score by -10.0 (if tied, penalize [MIL]), plus MCP Heat +2.0.
        """
        # Case 1: LEA and MIL tied (both 0.0) -> penalizes MIL by -10.0
        rep1 = await self.repo.update_rep('Alpha', 'rizon', 'GOV', -15.0)
        self.assertEqual(rep1['regions']['GOV'], -15.0)
        self.assertEqual(rep1['regions']['MIL'], -10.0)
        self.assertEqual(rep1['regions'].get('LEA', 0.0), 0.0)
        self.assertEqual(rep1['heat'], 2.0)

        # Case 2: LEA score is higher than MIL score -> penalizes LEA by -10.0
        # First set LEA to +20.0
        await self.repo.update_rep('Alpha', 'rizon', 'LEA', 20.0)
        rep2 = await self.repo.update_rep('Alpha', 'rizon', 'GOV', -10.0)
        # LEA was 20.0, MIL was -10.0 -> LEA had higher rep -> LEA penalized by -10.0 (now 10.0)
        self.assertEqual(rep2['regions']['LEA'], 10.0)
        self.assertEqual(rep2['regions']['MIL'], -10.0)
        self.assertEqual(rep2['heat'], 4.0)

        # Case 3: MIL score is higher than LEA score -> penalizes MIL by -10.0
        # Set MIL to +30.0 (now MIL is 20.0, LEA is 10.0)
        await self.repo.update_rep('Alpha', 'rizon', 'MIL', 30.0)
        rep3 = await self.repo.update_rep('Alpha', 'rizon', 'GOV', -10.0)
        # MIL was 20.0, LEA was 10.0 -> MIL had higher rep -> MIL penalized by -10.0 (now 10.0)
        self.assertEqual(rep3['regions']['MIL'], 10.0)
        self.assertEqual(rep3['regions']['LEA'], 10.0)
        self.assertEqual(rep3['heat'], 6.0)

    async def test_cross_type_mil_attack_double_penalty_and_heat(self):
        """R1: [MIL] attacked/hacked: [LEA] rep -5.0 and [MIL] rep -5.0 (in addition to primary penalty), MCP Heat +5.0."""
        rep = await self.repo.update_rep('Alpha', 'rizon', 'MIL', -20.0)
        # Primary was -20.0, secondary -5.0 -> total MIL = -25.0
        self.assertEqual(rep['score'], -25.0)
        self.assertEqual(rep['regions']['MIL'], -25.0)
        self.assertEqual(rep['regions']['LEA'], -5.0)
        self.assertEqual(rep['heat'], 5.0)

    async def test_cross_type_crp_attack(self):
        """R1: [CRP] attacked/hacked: [GOV] rep -2.0 and [LEA] rep -2.0 (corporate lobbying)."""
        rep = await self.repo.update_rep('Alpha', 'rizon', 'CRP', -15.0)
        self.assertEqual(rep['regions']['CRP'], -15.0)
        self.assertEqual(rep['regions']['GOV'], -2.0)
        self.assertEqual(rep['regions']['LEA'], -2.0)
        self.assertEqual(rep['heat'], 0.0)

    async def test_cross_type_ics_and_utl_attack(self):
        """R1: [ICS] or [UTL] attacked/hacked: [GOV] rep -15.0, [MIL] rep -10.0 (critical infrastructure)."""
        rep_ics = await self.repo.update_rep('Alpha', 'rizon', 'ICS', -5.0)
        self.assertEqual(rep_ics['regions']['ICS'], -5.0)
        self.assertEqual(rep_ics['regions']['GOV'], -15.0)
        self.assertEqual(rep_ics['regions']['MIL'], -10.0)

        # Reset and test UTL
        rep_utl = await self.repo.update_rep('Alpha', 'rizon', 'UTL', -5.0)
        self.assertEqual(rep_utl['regions']['UTL'], -5.0)
        self.assertEqual(rep_utl['regions']['GOV'], -30.0)
        self.assertEqual(rep_utl['regions']['MIL'], -20.0)

    async def test_secondary_heat_respects_stealth_skill(self):
        """R1: Character stealth skill reduces incoming heat gains (including secondary gains)."""
        # Add stealth skill level 2 (-20% heat generation)
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            session.add(CharacterSkill(character_id=char.id, skill_name='stealth', level=2))
            await session.commit()

        # Attacking MIL adds base secondary heat +5.0. With lvl 2 stealth: 5.0 * 0.8 = 4.0 heat
        rep = await self.repo.update_rep('Alpha', 'rizon', 'MIL', -10.0)
        self.assertAlmostEqual(rep['heat'], 4.0, places=2)

        # Add stealth level 4 (-40% heat generation)
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == 'stealth'))).scalars().first()
            cs.level = 4
            await session.commit()

        # Attacking GOV adds base secondary heat +2.0. With lvl 4 stealth: 2.0 * 0.6 = 1.2 heat
        # Current heat was 4.0, so updated heat should be 4.0 + 1.2 = 5.2
        rep2 = await self.repo.update_rep('Alpha', 'rizon', 'GOV', -10.0)
        self.assertAlmostEqual(rep2['heat'], 5.2, places=2)

    # --- R2: Automated Passive Decay Tests ---

    async def test_passive_reputation_decay_drifts_to_zero_without_overshooting(self):
        """R2: Over time, non-zero reputation scores passively drift back toward 0.0 without exceeding 0.0."""
        # Setup positive, negative, small positive, small negative, and zero scores
        await self.repo.update_rep('Alpha', 'rizon', 'SAFEZONE', 0.0)
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_rep = {
                'POS_HIGH': 10.0,
                'POS_LOW': 0.4,
                'NEG_HIGH': -10.0,
                'NEG_LOW': -0.4,
                'ZERO': 0.0,
            }
            await session.commit()

        # Decay for 1 hour at rate 1.0 point/hr
        res = await self.repo.decay_reputation_and_heat('Alpha', 'rizon', elapsed_hours=1.0)
        regs = res['regions']
        self.assertEqual(regs['POS_HIGH'], 9.0)
        self.assertEqual(regs['POS_LOW'], 0.0)  # Drifted to 0.0, did not go negative
        self.assertEqual(regs['NEG_HIGH'], -9.0)
        self.assertEqual(regs['NEG_LOW'], 0.0)  # Drifted to 0.0, did not go positive
        self.assertEqual(regs['ZERO'], 0.0)

        # Decay for another 9 hours -> POS_HIGH and NEG_HIGH should reach 0.0 exactly
        res2 = await self.repo.decay_reputation_and_heat('Alpha', 'rizon', elapsed_hours=9.0)
        self.assertEqual(res2['regions']['POS_HIGH'], 0.0)
        self.assertEqual(res2['regions']['NEG_HIGH'], 0.0)

    async def test_passive_heat_decay_cooldown_without_overshoot(self):
        """R2: MCP Heat passively cools down over time (e.g. -0.5 heat per hour) without dropping below 0.0."""
        await self.repo.update_heat('Alpha', 'rizon', 4.0)

        # 2 hours elapsed -> heat should cool by 2 * 0.5 = 1.0 -> 3.0
        res = await self.repo.decay_reputation_and_heat('Alpha', 'rizon', elapsed_hours=2.0)
        self.assertEqual(res['heat'], 3.0)
        self.assertEqual(res['status'], 'Alert')

        # 8 more hours elapsed -> heat drops from 3.0 by 4.0 -> clamped at 0.0
        res2 = await self.repo.decay_reputation_and_heat('Alpha', 'rizon', elapsed_hours=8.0)
        self.assertEqual(res2['heat'], 0.0)
        self.assertEqual(res2['status'], 'Passive')

    async def test_apply_passive_decay_batch(self):
        """R2: Batch scheduled sweep apply_passive_decay updates all active characters."""
        # Create second character Beta
        async with self.async_session() as session:
            player2 = Player(global_name="Beta", is_autonomous=False)
            session.add(player2)
            await session.flush()
            session.add(NetworkAlias(player_id=player2.id, network_name="rizon", nickname="Beta"))
            session.add(Character(
                player_id=player2.id,
                name="Beta",
                race="Synth",
                char_class="NetRunner",
                mcp_heat=5.0,
                node_rep={'MIL': -20.0}
            ))
            # Set Alpha heat and rep
            char_a = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char_a.mcp_heat = 2.0
            char_a.node_rep = {'CRP': 15.0}
            await session.commit()

        sweep_res = await self.repo.apply_passive_decay(elapsed_hours=2.0)
        self.assertEqual(sweep_res['decayed_count'], 2)

        # Check Alpha decayed
        sum_a = await self.repo.get_rep_summary('Alpha', 'rizon')
        self.assertEqual(sum_a['heat'], 1.0)  # 2.0 - 2*0.5
        self.assertEqual(sum_a['regions']['CRP'], 13.0)  # 15.0 - 2*1.0

        # Check Beta decayed
        sum_b = await self.repo.get_rep_summary('Beta', 'rizon')
        self.assertEqual(sum_b['heat'], 4.0)  # 5.0 - 2*0.5
        self.assertEqual(sum_b['regions']['MIL'], -18.0)  # -20.0 + 2*1.0

    # --- R3: Threshold-Triggered World Responses Tests ---

    async def test_merchant_discount_trusted_and_lockout_hostile(self):
        """R3: Trusted (+15% merchant buy discount and sell bonus) vs Hostile (merchant lockout)."""
        economy_repo = EconomyRepository(self.async_session)

        # Create merchant node with region CRP and item template
        async with self.async_session() as session:
            node = GridNode(name="CRP_Market", node_type="merchant", region_type="CRP", upgrade_level=1)
            session.add(node)
            item = ItemTemplate(name="Battery_Pack", item_type="hardware", base_value=100)
            session.add(item)
            await session.flush()

            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_id = node.id
            char.credits = 500.0
            await session.commit()

        # 1. Neutral status (rep 0.0): buy costs standard 100c, sell yields standard 50c
        success, msg = await economy_repo.process_transaction('Alpha', 'rizon', 'buy', 'Battery_Pack')
        self.assertTrue(success)
        self.assertIn("100c", msg)

        success_sell, msg_sell = await economy_repo.process_transaction('Alpha', 'rizon', 'sell', 'Battery_Pack')
        self.assertTrue(success_sell)
        self.assertIn("50c", msg_sell)

        # 2. Trusted status (rep 80.0 in CRP):
        # Buy receives +15% discount: 100 * 0.85 = 85c
        # Sell receives +15% bonus: 50 * 1.15 = 57c
        await self.repo.update_rep('Alpha', 'rizon', 'CRP', 80.0)
        success_trusted_buy, msg_t_buy = await economy_repo.process_transaction('Alpha', 'rizon', 'buy', 'Battery_Pack')
        self.assertTrue(success_trusted_buy)
        self.assertIn("85c", msg_t_buy)

        success_trusted_sell, msg_t_sell = await economy_repo.process_transaction('Alpha', 'rizon', 'sell', 'Battery_Pack')
        self.assertTrue(success_trusted_sell)
        self.assertIn("57c", msg_t_sell)

        # 3. Hostile status (rep -80.0 in CRP): Merchant lockout!
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_rep = {'CRP': -80.0}
            await session.commit()

        success_hostile_buy, msg_h_buy = await economy_repo.process_transaction('Alpha', 'rizon', 'buy', 'Battery_Pack')
        self.assertFalse(success_hostile_buy)
        self.assertIn("Merchant Lockout", msg_h_buy)

        success_hostile_sell, msg_h_sell = await economy_repo.process_transaction('Alpha', 'rizon', 'sell', 'Battery_Pack')
        self.assertFalse(success_hostile_sell)
        self.assertIn("Merchant Lockout", msg_h_sell)

    async def test_probe_explore_dc_bonus_trusted(self):
        """R3: Reduced explore/probe difficulty (-2 DC bonus) for Trusted status."""
        disc_repo = DiscoveryRepository(self.async_session)

        async with self.async_session() as session:
            node = GridNode(name="MED_Facility", node_type="void", region_type="MED", upgrade_level=1, noise=0.0)
            session.add(node)
            await session.flush()
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_id = node.id
            char.power = 100.0
            char.alg = 50
            # Set Trusted status in MED
            char.node_rep = {'MED': 85.0}
            await session.commit()

        # Probe the node: baseline difficulty is 12 + upgrade_level*2 = 14.
        # With -2 DC bonus for Trusted, difficulty is 12.
        # Check that probe succeeds cleanly
        res = await disc_repo.probe_node('Alpha', 'rizon')
        self.assertTrue(res['success'])

    async def test_defender_mob_spawn_check(self):
        """
        R3: Threshold-triggered defender mob encounters upon entering matching regional nodes:
        - Flagged: 25% chance of security mob encounter (threat 1).
        - Hostile: 75% chance of security mob encounter (threat 2).
        - Neutral/Unknown/Trusted: 0% chance.
        """
        # 1. Flagged (-50.0 in MIL): chance = 0.25
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_rep = {'MIL': -50.0}
            await session.commit()

        # Roll below 0.25 triggers spawn
        enc_flagged_hit = await self.repo.check_defender_spawn('Alpha', 'rizon', 'MIL', roll=0.15)
        self.assertTrue(enc_flagged_hit['spawn'])
        self.assertEqual(enc_flagged_hit['status'], 'Flagged')
        self.assertEqual(enc_flagged_hit['chance'], 0.25)
        self.assertEqual(enc_flagged_hit['threat'], 1)

        # Roll at or above 0.25 does not spawn
        enc_flagged_miss = await self.repo.check_defender_spawn('Alpha', 'rizon', 'MIL', roll=0.35)
        self.assertFalse(enc_flagged_miss['spawn'])

        # 2. Hostile (-85.0 in MIL): chance = 0.75
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_rep = {'MIL': -85.0}
            await session.commit()

        # Roll below 0.75 triggers spawn
        enc_hostile_hit = await self.repo.check_defender_spawn('Alpha', 'rizon', 'MIL', roll=0.60)
        self.assertTrue(enc_hostile_hit['spawn'])
        self.assertEqual(enc_hostile_hit['status'], 'Hostile')
        self.assertEqual(enc_hostile_hit['chance'], 0.75)
        self.assertEqual(enc_hostile_hit['threat'], 2)

        # Roll above 0.75 does not spawn
        enc_hostile_miss = await self.repo.check_defender_spawn('Alpha', 'rizon', 'MIL', roll=0.85)
        self.assertFalse(enc_hostile_miss['spawn'])

        # 3. Neutral or Trusted (0.0 or 80.0): chance = 0.0
        enc_neutral = await self.repo.check_defender_spawn('Alpha', 'rizon', 'CRP', roll=0.01)
        self.assertFalse(enc_neutral['spawn'])
        self.assertEqual(enc_neutral['chance'], 0.0)

    async def test_bounty_eligibility(self):
        """R3: Eligible for bounty flags when hostile with 2+ region types or MCP heat > 6.0 ("Bounty")."""
        # Baseline: not eligible
        res1 = await self.repo.is_bounty_eligible('Alpha', 'rizon')
        self.assertFalse(res1['eligible'])

        # 1. Hostile with only 1 region type and heat <= 6.0 -> NOT eligible
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_rep = {'MED': -80.0}
            char.mcp_heat = 4.0
            await session.commit()

        res2 = await self.repo.is_bounty_eligible('Alpha', 'rizon')
        self.assertFalse(res2['eligible'])

        # 2. Hostile with 2 region types -> ELIGIBLE
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_rep = {'MED': -80.0, 'MIL': -76.0}
            await session.commit()

        res3 = await self.repo.is_bounty_eligible('Alpha', 'rizon')
        self.assertTrue(res3['eligible'])
        self.assertIn('MED', res3['hostile_regions'])
        self.assertIn('MIL', res3['hostile_regions'])

        # 3. Hostile with 0 region types, but MCP heat > 6.0 ("Bounty" tier) -> ELIGIBLE
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_rep = {}
            char.mcp_heat = 7.0
            await session.commit()

        res4 = await self.repo.is_bounty_eligible('Alpha', 'rizon')
        self.assertTrue(res4['eligible'])
        self.assertEqual(res4['status'], 'Bounty')

        summary = await self.repo.get_rep_summary('Alpha', 'rizon')
        self.assertTrue(summary['bounty_eligible'])

    async def test_rep_status_boundary_precision(self):
        """Adversarial test: Floating point threshold boundaries for reputation status bands."""
        # Hostile is -75 to -100
        self.assertEqual(rep_status(-75.0), 'Hostile')
        self.assertEqual(rep_status(-100.0), 'Hostile')
        # -74.5 is strictly above -75.0 -> Flagged
        self.assertEqual(rep_status(-74.5), 'Flagged')
        self.assertEqual(rep_status(-74.0), 'Flagged')
        self.assertEqual(rep_status(-50.0), 'Flagged')
        self.assertEqual(rep_status(-25.0), 'Flagged')
        # -24.5 is strictly above -25.0 -> Unknown
        self.assertEqual(rep_status(-24.5), 'Unknown')
        self.assertEqual(rep_status(-24.0), 'Unknown')
        self.assertEqual(rep_status(0.0), 'Unknown')
        self.assertEqual(rep_status(24.9), 'Unknown')
        # Neutral: 25 to 74
        self.assertEqual(rep_status(25.0), 'Neutral')
        self.assertEqual(rep_status(74.5), 'Neutral')
        # Trusted: 75 to 100
        self.assertEqual(rep_status(75.0), 'Trusted')
        self.assertEqual(rep_status(100.0), 'Trusted')

    async def test_whitespace_and_bracket_formatting_resilience(self):
        """Adversarial test: Formats with brackets and spaces in region names like ' [MED] '."""
        rep = await self.repo.update_rep('Alpha', 'rizon', ' [MED] ', -10.0)
        self.assertEqual(rep['region'], 'MED')
        self.assertEqual(rep['score'], -10.0)
        self.assertEqual(rep['regions']['LEA'], -5.0)
        self.assertEqual(rep['regions']['GOV'], -3.0)

        # Check defender spawn with space-padded bracketed region
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_rep = {'MIL': -85.0}
            await session.commit()

        enc = await self.repo.check_defender_spawn('Alpha', 'rizon', region_type=' [MIL] ', roll=0.1)
        self.assertTrue(enc['spawn'])
        self.assertEqual(enc['region'], 'MIL')
        self.assertEqual(enc['status'], 'Hostile')

    async def test_apply_reputation_hooks_prioritizes_region_type(self):
        """Adversarial test: _apply_reputation_hooks in grid.py must use node region_type, not node_type."""
        from ai_grid.core.handlers.grid import _apply_reputation_hooks
        from unittest.mock import AsyncMock, MagicMock

        # Create mock node with db navigation location returning void node_type but MIL region_type
        mock_node = MagicMock()
        mock_node.net_name = 'rizon'
        mock_node.db = MagicMock()
        mock_node.db.get_location = AsyncMock(return_value={
            'name': 'Outpost_MIL',
            'type': 'void',  # node_type
            'region_type': 'MIL',  # region_type
        })
        mock_node.db.update_heat = AsyncMock()
        mock_node.db.update_rep = AsyncMock()

        await _apply_reputation_hooks(mock_node, 'Alpha', node_type=None, rep_delta=-10.0, heat_delta=1.0)
        # Verify update_rep was called with resolved region_type 'MIL', NOT 'VOID'
        mock_node.db.update_rep.assert_called_once_with('Alpha', 'rizon', 'MIL', -10.0)

    async def test_probe_directional_target_trusted_bonus(self):
        """Adversarial test: Probing with direction evaluates target node's region reputation."""
        disc_repo = DiscoveryRepository(self.async_session)

        async with self.async_session() as session:
            # Current node is SAFEZONE (at 0,0)
            node_here = GridNode(name="Home_Base", node_type="void", region_type="SAFEZONE", x=0, y=0, upgrade_level=1, noise=0.0)
            session.add(node_here)
            # Target node to the south is MED (at 0,1)
            node_target = GridNode(name="Hospital_Sector", node_type="void", region_type="MED", x=0, y=1, upgrade_level=1, noise=0.0)
            session.add(node_target)
            await session.flush()

            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_id = node_here.id
            char.power = 100.0
            char.alg = 50  # Ensure deterministic success on d20 roll
            # Alpha is Trusted in MED (+80.0), but Unknown in SAFEZONE (0.0)
            char.node_rep = {'MED': 80.0, 'SAFEZONE': 0.0}
            await session.commit()

        # Probing south into MED sector should benefit from Trusted DC bonus (-2 DC)
        res = await disc_repo.probe_node('Alpha', 'rizon', direction='south')
        self.assertTrue(res['success'])

    async def test_npc_trade_node_type_acceptance(self):
        """Adversarial test: NPC trade node types ('npc_trade', 'trade') allow buy/sell with discounts."""
        economy_repo = EconomyRepository(self.async_session)

        async with self.async_session() as session:
            node = GridNode(name="Trade_Depot", node_type="npc_trade", region_type="CRP", upgrade_level=1)
            session.add(node)
            item = ItemTemplate(name="Coolant", item_type="hardware", base_value=100)
            session.add(item)
            await session.flush()

            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_id = node.id
            char.credits = 500.0
            char.node_rep = {'CRP': 80.0}  # Trusted
            await session.commit()

        success, msg = await economy_repo.process_transaction('Alpha', 'rizon', 'buy', 'Coolant')
        self.assertTrue(success)
        self.assertIn("85c", msg)  # 15% discount on 100c base

    async def test_null_and_malformed_values_resilience(self):
        """Adversarial test: None and malformed values in node_rep must not crash methods."""
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_rep = {'MED': None, 'GOV': 'corrupt', 'MIL': -80.0}
            char.mcp_heat = None
            await session.commit()

        # is_bounty_eligible shouldn't raise TypeError
        bounty = await self.repo.is_bounty_eligible('Alpha', 'rizon')
        self.assertIsInstance(bounty, dict)

        # get_rep_summary shouldn't raise TypeError
        summary = await self.repo.get_rep_summary('Alpha', 'rizon')
        self.assertEqual(summary['heat'], 0.0)

        # decay shouldn't raise TypeError
        decay = await self.repo.decay_reputation_and_heat('Alpha', 'rizon', elapsed_hours=1.0)
        self.assertTrue(decay['decay_applied'])

    async def test_target_name_region_tag_extraction(self):
        """Adversarial test: Region tags embedded in target names (e.g. '[MED] Clinic') apply consequences."""
        rep = await self.repo.update_rep('Alpha', 'rizon', '[MED] Regional Hospital', -10.0)
        self.assertEqual(rep['region'], 'MED')
        self.assertEqual(rep['score'], -10.0)
        self.assertEqual(rep['regions']['MED'], -10.0)
        self.assertEqual(rep['regions']['LEA'], -5.0)
        self.assertEqual(rep['regions']['GOV'], -3.0)

    async def test_bounty_eligibility_deduplicates_region_aliases(self):
        """Adversarial test: Duplicate bracketed keys in node_rep do not falsely trigger multi-region bounty."""
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            # Only 1 distinct region ('MED'), but stored with two key representations
            char.node_rep = {'MED': -80.0, '[MED]': -85.0}
            char.mcp_heat = 2.0
            await session.commit()

        bounty_res = await self.repo.is_bounty_eligible('Alpha', 'rizon')
        self.assertFalse(bounty_res['eligible'])
        self.assertEqual(bounty_res['hostile_regions'], ['MED'])

        # Now add truly distinct second hostile region 'MIL'
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_rep = {'MED': -80.0, 'MIL': -85.0}
            await session.commit()

        bounty_res2 = await self.repo.is_bounty_eligible('Alpha', 'rizon')
        self.assertTrue(bounty_res2['eligible'])
        self.assertEqual(bounty_res2['hostile_regions'], ['MED', 'MIL'])

    async def test_discovery_repo_resilient_to_corrupt_rep_values(self):
        """Adversarial test: explore_node and probe_node handle None/corrupted rep without crashing."""
        disc_repo = DiscoveryRepository(self.async_session)
        async with self.async_session() as session:
            node = GridNode(name="Corrupt_Sector", node_type="void", region_type="MED", upgrade_level=1, noise=0.0)
            session.add(node)
            await session.flush()
            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_id = node.id
            char.power = 100.0
            char.alg = 50
            char.node_rep = {'MED': None, 'GOV': 'corrupted'}
            await session.commit()

        # explore_node must safely succeed or fail without TypeError/ValueError
        res_exp = await disc_repo.explore_node('Alpha', 'rizon')
        self.assertNotIn('error', res_exp)

        # probe_node must safely succeed without TypeError/ValueError
        res_probe = await disc_repo.probe_node('Alpha', 'rizon')
        self.assertTrue(res_probe['success'])

    async def test_concurrent_combat_encounters_multi_player(self):
        """Adversarial test: Multiple players triggering encounters on the same tick maintain isolated state."""
        from unittest.mock import MagicMock, AsyncMock
        from ai_grid.core.handlers.combat import handle_mob_encounter, resolve_mob

        mock_node = MagicMock()
        mock_node.net_name = 'rizon'
        mock_node.pending_encounters = {}
        mock_node.send = AsyncMock()
        mock_node.db = MagicMock()
        mock_node.db.combat = MagicMock()
        mock_node.db.combat.MOB_ROSTER = {
            1: {'name': 'Rogue_Process', 'xp': 20, 'credits': 15.0},
            2: {'name': 'ICE_Drone', 'xp': 50, 'credits': 40.0},
        }
        mock_node.db.resolve_mob_encounter = AsyncMock(return_value={
            'won': True,
            'xp_gained': 20,
            'credits_gained': 15.0,
            'mob_name': 'Rogue_Process',
        })

        # Players Alpha and Beta both encounter mobs
        await handle_mob_encounter(mock_node, 'Alpha', 'Node_MIL_1', threat=1, prev_node='Spawn', reply_target='#chan')
        await handle_mob_encounter(mock_node, 'Beta', 'Node_MIL_1', threat=2, prev_node='Spawn', reply_target='#chan')

        self.assertIn('Alpha', mock_node.pending_encounters)
        self.assertIn('Beta', mock_node.pending_encounters)
        self.assertEqual(mock_node.pending_encounters['Alpha']['threat'], 1)
        self.assertEqual(mock_node.pending_encounters['Beta']['threat'], 2)

        # Alpha triggers a second encounter before timer expires (superseded encounter)
        old_timer = mock_node.pending_encounters['Alpha']['timer']
        await handle_mob_encounter(mock_node, 'Alpha', 'Node_MIL_2', threat=2, prev_node='Node_MIL_1', reply_target='#chan')
        import asyncio
        await asyncio.sleep(0)
        self.assertTrue(old_timer.cancelled())
        self.assertEqual(mock_node.pending_encounters['Alpha']['threat'], 2)

        # Resolve Beta independently
        await resolve_mob(mock_node, 'Beta', '#chan')
        self.assertNotIn('Beta', mock_node.pending_encounters)
        self.assertIn('Alpha', mock_node.pending_encounters)  # Alpha still active

        # Clean up Alpha's timer
        mock_node.pending_encounters['Alpha']['timer'].cancel()
        await asyncio.sleep(0)

    async def test_raid_actions_apply_reputation_hooks(self):
        """Adversarial test: !a raid hack/exploit/raid against target applies reputation consequences to that target."""
        from unittest.mock import MagicMock, AsyncMock
        from ai_grid.core.handlers.grid import handle_grid_loot

        mock_node = MagicMock()
        mock_node.net_name = 'rizon'
        mock_node.send = AsyncMock()
        mock_node.add_xp = AsyncMock()
        mock_node.db = MagicMock()
        mock_node.db.update_heat = AsyncMock()
        mock_node.db.update_rep = AsyncMock()
        mock_node.db.get_location = AsyncMock(return_value={'region_type': 'VOD', 'type': 'void'})
        mock_node.db.infiltration = MagicMock()
        mock_node.db.infiltration.hack_node = AsyncMock(return_value=(True, "Breach success", None))
        mock_node.db.infiltration.exploit_node = AsyncMock(return_value=(True, "Exploit success", None))
        mock_node.db.infiltration.raid_node = AsyncMock(return_value={'success': True, 'msg': "Raid success"})

        # 1. raid hack [MED] -> must call update_rep with resolved region 'MED'
        await handle_grid_loot(mock_node, 'Alpha', '#chan', ['hack', '[MED]'])
        mock_node.db.update_rep.assert_called_with('Alpha', 'rizon', 'MED', -5.0)

        mock_node.db.update_rep.reset_mock()
        # 2. raid exploit [GOV] -> must call update_rep with resolved region 'GOV'
        await handle_grid_loot(mock_node, 'Alpha', '#chan', ['exploit', '[GOV]'])
        mock_node.db.update_rep.assert_called_with('Alpha', 'rizon', 'GOV', -5.0)

        mock_node.db.update_rep.reset_mock()
        # 3. raid [MIL] -> must call update_rep with resolved region 'MIL'
        await handle_grid_loot(mock_node, 'Alpha', '#chan', ['[MIL]'])
        mock_node.db.update_rep.assert_called_with('Alpha', 'rizon', 'MIL', -5.0)

    async def test_clean_region_key_trailing_brackets_and_delimiters(self):
        """Adversarial test: Trailing brackets and delimited node names extract region and trigger institutional rules."""
        from ai_grid.database.repositories.reputation_repo import clean_region_key

        self.assertEqual(clean_region_key("Regional Hospital [MED]"), "MED")
        self.assertEqual(clean_region_key("MED_12_34"), "MED")
        self.assertEqual(clean_region_key("Node_MIL_1"), "MIL")
        self.assertEqual(clean_region_key("GOV-Terminal"), "GOV")
        self.assertEqual(clean_region_key("[CRP] Corporate Vault"), "CRP")

        # Directly test update_rep with delimited node name 'MED_12_34'
        rep = await self.repo.update_rep('Alpha', 'rizon', 'MED_12_34', -10.0)
        self.assertEqual(rep['region'], 'MED')
        self.assertEqual(rep['score'], -10.0)
        self.assertEqual(rep['regions']['MED'], -10.0)
        self.assertEqual(rep['regions']['LEA'], -5.0)
        self.assertEqual(rep['regions']['GOV'], -3.0)

    async def test_probe_raid_target_checks_target_type_reputation(self):
        """Adversarial test: Probing raid target evaluates raid_target.target_type rather than outer node.region_type."""
        from ai_grid.models import RaidTarget
        disc_repo = DiscoveryRepository(self.async_session)

        async with self.async_session() as session:
            # Create void node with a [GOV] raid target
            node = GridNode(name="Void_Sector", node_type="void", region_type="VOD", upgrade_level=1, noise=0.0)
            session.add(node)
            await session.flush()
            rt = RaidTarget(name="[GOV] Defense Hub", node_id=node.id, target_type="GOV", difficulty=15, is_active=True)
            session.add(rt)
            await session.flush()
            node.active_target_id = rt.id

            char = (await session.execute(select(Character).where(Character.name == 'Alpha'))).scalars().first()
            char.node_id = node.id
            char.power = 100.0
            char.alg = 50
            # Alpha is Trusted in GOV (+80.0), but Unknown in VOD (0.0)
            char.node_rep = {'GOV': 80.0, 'VOD': 0.0}
            await session.commit()

        # Probing the GOV raid target should use GOV reputation (Trusted -> difficulty 15 - 2 - 2 = 11)
        res = await disc_repo.probe_node('Alpha', 'rizon', target_name='[GOV] Defense Hub')
        self.assertTrue(res['success'])

    async def test_territorial_hack_preserves_target_argument(self):
        """Adversarial test: grid hack [MED] preserves target argument in _apply_reputation_hooks."""
        from unittest.mock import MagicMock, AsyncMock
        from ai_grid.core.handlers.grid import handle_grid_command

        mock_node = MagicMock()
        mock_node.net_name = 'rizon'
        mock_node.send = AsyncMock()
        mock_node.add_xp = AsyncMock()
        mock_node.db = MagicMock()
        mock_node.db.hack_node = AsyncMock(return_value=(True, "Breach success", None))
        mock_node.db.update_heat = AsyncMock()
        mock_node.db.update_rep = AsyncMock()
        mock_node.db.get_location = AsyncMock(return_value={'region_type': 'VOD', 'type': 'void'})

        await handle_grid_command(mock_node, 'Alpha', '#chan', 'hack', ['[MED]'])
        mock_node.db.update_rep.assert_called_with('Alpha', 'rizon', 'MED', -5.0)


if __name__ == '__main__':
    unittest.main()
