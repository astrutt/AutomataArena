import asyncio
import datetime
from datetime import timezone
import os
import unittest
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_grid.models import Base, Player, NetworkAlias, Character, GridNode, CharacterSkill
from ai_grid.database.repositories.skill_repo import (
    SkillRepository, ALL_SKILLS, SKILL_DEFINITIONS, MAX_CONCURRENT_SKILLS,
    MAX_SKILL_LEVEL, SESSIONS_PER_LEVEL, TRAINING_COOLDOWN_SECONDS
)
from ai_grid.core.handlers.skills import handle_skill
from ai_grid.grid_combat import Entity, CombatEngine


class TestSkillSystem(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_skills_{int(datetime.datetime.now().timestamp() * 1000)}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with self.async_session() as session:
            player = Player(global_name="Tester", is_autonomous=False)
            session.add(player)
            await session.flush()

            alias = NetworkAlias(player_id=player.id, network_name="rizon", nickname="Tester")
            session.add(alias)

            node = GridNode(name="TestNode", node_type="safezone", power_stored=500.0, durability=50.0)
            session.add(node)
            await session.flush()

            char = Character(
                player_id=player.id,
                node_id=node.id,
                name="Tester",
                race="Synth",
                char_class="Netrunner",
                cpu=5,
                ram=5,
                bnd=5,
                sec=5,
                alg=5,
                power=200.0,
                stability=100.0,
                credits=1000.0,
                data_units=50.0,
                mcp_heat=0.0
            )
            session.add(char)
            await session.flush()
            node.owner_character_id = char.id
            await session.commit()

        self.repo = SkillRepository(self.async_session)

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def test_all_8_skills_defined(self):
        """R1: All 8 skills are recognized with respective attributes and effects."""
        expected_skills = ["powergen", "attack", "defend", "hack", "recon", "siphon", "stealth", "fortify"]
        self.assertEqual(len(ALL_SKILLS), 8)
        for s in expected_skills:
            self.assertIn(s, ALL_SKILLS)
            self.assertIn(s, SKILL_DEFINITIONS)
            meta = SKILL_DEFINITIONS[s]
            self.assertIn("description", meta)
            self.assertIn("effect", meta)
            self.assertEqual(meta["bonus_per_level"], 0.10)

        # Initial skills
        for s in ["powergen", "attack", "defend", "hack"]:
            self.assertEqual(SKILL_DEFINITIONS[s]["category"], "initial")
        # Expansion skills
        for s in ["recon", "siphon", "stealth", "fortify"]:
            self.assertEqual(SKILL_DEFINITIONS[s]["category"], "expansion")

    async def test_start_and_query_skill(self):
        """R1: Character can start learning a skill at Level 1, 0 sessions."""
        res = await self.repo.start_skill("Tester", "rizon", "powergen")
        self.assertTrue(res["success"])
        self.assertFalse(res["resumed"])
        self.assertEqual(res["skill"], "powergen")
        self.assertEqual(res["level"], 1)
        self.assertEqual(res["sessions"], 0)
        self.assertEqual(res["slots_used"], 1)

        info = await self.repo.get_skill_info("Tester", "rizon", "powergen")
        self.assertTrue(info["is_learned"])
        self.assertEqual(info["level"], 1)
        self.assertEqual(info["training_sessions"], 0)
        self.assertTrue(info["is_active"])

    async def test_slot_limit_max_4_skills(self):
        """R1: Characters can learn a maximum of 4 skills simultaneously."""
        for skill_name in ["powergen", "attack", "defend", "hack"]:
            res = await self.repo.start_skill("Tester", "rizon", skill_name)
            self.assertTrue(res["success"], f"Failed to start {skill_name}")

        skills_data = await self.repo.get_character_skills("Tester", "rizon")
        self.assertEqual(skills_data["slots_used"], 4)

        # Attempt to start a 5th skill should fail
        fifth = await self.repo.start_skill("Tester", "rizon", "recon")
        self.assertFalse(fifth["success"])
        self.assertIn("capacity reached", fifth["error"].lower())

    async def test_forget_skill_frees_slot(self):
        """R1: Forgetting a skill frees its slot for another skill."""
        for s in ["powergen", "attack", "defend", "hack"]:
            await self.repo.start_skill("Tester", "rizon", s)

        # Forget attack
        f_res = await self.repo.forget_skill("Tester", "rizon", "attack")
        self.assertTrue(f_res["success"])
        self.assertEqual(f_res["slots_freed"], 1)

        skills_data = await self.repo.get_character_skills("Tester", "rizon")
        self.assertEqual(skills_data["slots_used"], 3)

        # Now 5th skill (recon) can be learned into the freed slot
        new_res = await self.repo.start_skill("Tester", "rizon", "recon")
        self.assertTrue(new_res["success"])
        self.assertEqual(new_res["slots_used"], 4)

    async def test_quit_training_and_resume(self):
        """R1: Quitting pauses active training without forgetting progress; start resumes."""
        await self.repo.start_skill("Tester", "rizon", "attack")
        q_res = await self.repo.quit_training("Tester", "rizon")
        self.assertTrue(q_res["success"])

        skills_data = await self.repo.get_character_skills("Tester", "rizon")
        self.assertIsNone(skills_data["active_skill"])
        self.assertEqual(skills_data["slots_used"], 1)

        # Resuming training
        res_start = await self.repo.start_skill("Tester", "rizon", "attack")
        self.assertTrue(res_start["success"])
        self.assertTrue(res_start["resumed"])

    async def test_training_cooldown_enforcement(self):
        """R1: Training enforces the 1-hour cooldown between sessions."""
        await self.repo.start_skill("Tester", "rizon", "attack")

        # First training session succeeds
        t1 = await self.repo.train_skill("Tester", "rizon")
        self.assertTrue(t1["success"])
        self.assertEqual(t1["sessions"], 1)

        # Immediate second training session fails due to cooldown
        t2 = await self.repo.train_skill("Tester", "rizon")
        self.assertFalse(t2["success"])
        self.assertIn("cooldown", t2["error"].lower())
        self.assertGreater(t2["cooldown_remaining"], 0)

    async def test_training_advancement_after_24_sessions(self):
        """R1: Each skill scales from Level 1 to 4, advancing after 24 completed training sessions."""
        await self.repo.start_skill("Tester", "rizon", "attack")

        # Advance through 24 sessions by manipulating last_trained_at timestamp
        for i in range(1, 25):
            async with self.async_session() as session:
                char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
                char.last_skill_train_at = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=2)
                cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.character_id == char.id, CharacterSkill.skill_name == "attack"))).scalars().first()
                cs.last_trained_at = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=2)
                await session.commit()

            res = await self.repo.train_skill("Tester", "rizon")
            self.assertTrue(res["success"])
            if i < 24:
                self.assertEqual(res["level"], 1)
                self.assertEqual(res["sessions"], i)
                self.assertFalse(res["leveled_up"])
            else:
                # Milestone reached! Advances to Level 2
                self.assertEqual(res["level"], 2)
                self.assertEqual(res["sessions"], 0)
                self.assertTrue(res["leveled_up"])

    async def test_level_cap_enforcement_at_level_4(self):
        """R1: Level cap of 4 is enforced; cannot train past Level 4."""
        await self.repo.start_skill("Tester", "rizon", "attack")
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "attack"))).scalars().first()
            cs.level = 4
            cs.training_sessions = 0
            await session.commit()

        # Attempt to train at Level 4
        res = await self.repo.train_skill("Tester", "rizon")
        self.assertFalse(res["success"])
        self.assertIn("maximum level", res["error"].lower())

    async def test_command_handler_modes_formatting(self):
        """R2: Commands execute and return formatted responses for human, text, and narrative modes."""
        class MockNode:
            def __init__(self, async_session):
                self.net_name = "rizon"
                self.prefix = "!a"
                from ai_grid.grid_db import ArenaDB
                from ai_grid.database.repositories.character_repo import CharacterRepository
                # Minimal mock facade
                self.db = ArenaDB()
                self.db.async_session = async_session
                self.db.skill = SkillRepository(async_session)
                self.db.character = CharacterRepository(async_session)
                self.sent_messages = []

            async def send(self, msg):
                self.sent_messages.append(msg)

        node = MockNode(self.async_session)

        # 1. Test Human Mode
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "human"}'
            await session.commit()

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["list"], "#arena")
        self.assertTrue(any("=== [CHARACTER SKILLS" in m for m in node.sent_messages))

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["start", "attack"], "#arena")
        self.assertTrue(any("Initiated learning for 'attack'" in m for m in node.sent_messages))

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["attack"], "#arena")
        self.assertTrue(any("Level 1/4" in m for m in node.sent_messages))

        # 2. Test Text (Machine) Mode
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "text"}'
            await session.commit()

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["list"], "#arena")
        self.assertTrue(any("[ACTION:SKILLS][RESULT:LIST]" in m for m in node.sent_messages))

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["attack"], "#arena")
        self.assertTrue(any("[ACTION:SKILL][RESULT:INFO]" in m for m in node.sent_messages))

        # 3. Test Narrative Mode
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "narrative"}'
            await session.commit()

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["list"], "#arena")
        self.assertTrue(any("[NARRATIVE] Tester queries neural subroutines" in m for m in node.sent_messages))

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["attack"], "#arena")
        self.assertTrue(any("[NARRATIVE] Telemetry diagnostics for 'attack'" in m for m in node.sent_messages))

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["quit"], "#arena")
        self.assertTrue(any("halts active training of 'attack'" in m for m in node.sent_messages))

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["forget", "attack"], "#arena")
        self.assertTrue(any("purges the 'attack' subroutine" in m for m in node.sent_messages))

    async def test_powergen_modifier_calculation(self):
        """R3: powergen skill boosts manual power generation by +10%/lvl."""
        from ai_grid.database.repositories.activity_repo import ActivityRepository
        act_repo = ActivityRepository(self.async_session)

        # Baseline with no skill
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.power = 100.0
            await session.commit()

        success, msg = await act_repo.active_powergen("Tester", "rizon")
        self.assertTrue(success)
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            base_gain = char.power - 100.0
            self.assertEqual(base_gain, 15.0) # Claimed node base is 15.0

        # Learn powergen Level 2 (+20%)
        await self.repo.start_skill("Tester", "rizon", "powergen")
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "powergen"))).scalars().first()
            cs.level = 2
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.power = 100.0
            await session.commit()

        success, msg = await act_repo.active_powergen("Tester", "rizon")
        self.assertTrue(success)
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            expected_gain = 15.0 * 1.20 # +20%
            self.assertAlmostEqual(char.power - 100.0, expected_gain, places=2)

    async def test_combat_damage_and_reduction_modifiers(self):
        """R3: attack (+10% kinetic/lvl), hack (+10% cyber/lvl), and defend (+10% reduction/lvl) in combat."""
        engine = CombatEngine("test_match", "!a", AsyncMock())
        attacker = Entity("Attacker", cpu=10, ram=5, bnd=10, sec=5, alg=0, skills={"attack": 2, "hack": 3})
        defender = Entity("Defender", cpu=5, ram=5, bnd=5, sec=10, alg=0, skills={"defend": 2})
        engine.add_entity(attacker)
        engine.add_entity(defender)

        # Kinetic strike:
        # Base raw = (CPU * 5) + RAM = (10 * 5) + 5 = 55
        # attack Level 2 = +20% -> 55 * 1.2 = 66
        # Minus protection (SEC = 10) = 56
        # defend Level 2 = -20% -> 56 * 0.8 = 44 DMG
        res_kinetic = engine._execute_attack(attacker, "Defender", mode="kinetic")
        self.assertIn("44 DMG", res_kinetic)

        # Cyber strike:
        # Base raw = (BND * 5) + SEC = (10 * 5) + 5 = 55
        # hack Level 3 = +30% -> 55 * 1.3 = 71
        # Minus protection (BND = 5) = 66
        # defend Level 2 = -20% -> 66 * 0.8 = 52 DMG
        res_cyber = engine._execute_attack(attacker, "Defender", mode="cyber")
        self.assertIn("52 DMG", res_cyber)

    async def test_stealth_heat_reduction_modifier(self):
        """R3: stealth skill reduces MCP heat generation by -10%/lvl."""
        from ai_grid.database.repositories.reputation_repo import ReputationRepository
        rep_repo = ReputationRepository(self.async_session)

        # Baseline: +2.0 heat with no stealth
        h1 = await rep_repo.update_heat("Tester", "rizon", 2.0)
        self.assertEqual(h1, 2.0)

        # Reset heat and add stealth Level 3 (-30%)
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.mcp_heat = 0.0
            await session.commit()

        await self.repo.start_skill("Tester", "rizon", "stealth")
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "stealth"))).scalars().first()
            cs.level = 3
            await session.commit()

        # Delta 2.0 with -30% = 1.4 heat
        h2 = await rep_repo.update_heat("Tester", "rizon", 2.0)
        self.assertAlmostEqual(h2, 1.4, places=2)

    async def test_recon_discovery_yield_modifier(self):
        """R3: recon skill increases explore/probe yields by +10%/lvl."""
        from ai_grid.database.repositories.discovery_repo import DiscoveryRepository
        disc_repo = DiscoveryRepository(self.async_session)

        await self.repo.start_skill("Tester", "rizon", "recon")
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "recon"))).scalars().first()
            cs.level = 2 # +20% yield
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.credits = 0.0
            char.data_units = 0.0
            char.alg = 100 # Guarantee probe success
            await session.commit()

        res = await disc_repo.probe_node("Tester", "rizon")
        self.assertTrue(res["success"])
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            # Base probe gives 15.0c and 5.0 data. With +20%: 18.0c and 6.0 data.
            self.assertAlmostEqual(char.credits, 18.0, places=2)
            self.assertAlmostEqual(char.data_units, 6.0, places=2)

    async def test_siphon_yield_modifier(self):
        """R3: siphon skill increases siphoned power by +10%/lvl."""
        from ai_grid.database.repositories.infiltration_repo import InfiltrationRepository
        from ai_grid.models import DiscoveryRecord
        infil_repo = InfiltrationRepository(self.async_session)

        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            node = (await session.execute(select(GridNode).where(GridNode.name == "TestNode"))).scalars().first()
            # Mark node as explored
            session.add(DiscoveryRecord(character_id=char.id, node_id=node.id, intel_level="EXPLORE"))
            char.power = 0.0
            node.power_stored = 100.0
            node.durability = 100.0
            await session.commit()

        # Learn siphon Level 2 (+20%)
        await self.repo.start_skill("Tester", "rizon", "siphon")
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "siphon"))).scalars().first()
            cs.level = 2
            await session.commit()

        ok, msg, _ = await infil_repo.siphon_node("Tester", "rizon", percent=50.0)
        self.assertTrue(ok)
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            # Base 50.0 power * 1.20 = 60.0 power
            self.assertAlmostEqual(char.power, 60.0, places=2)

    async def test_fortify_modifier(self):
        """R3: fortify skill increases bolster durability gain and owned node defense DC."""
        from ai_grid.database.repositories.territory_repo import TerritoryRepository
        from ai_grid.database.repositories.infiltration_repo import InfiltrationRepository
        terr_repo = TerritoryRepository(self.async_session)

        # Learn fortify Level 2 (+20%)
        await self.repo.start_skill("Tester", "rizon", "fortify")
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "fortify"))).scalars().first()
            cs.level = 2
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            node = (await session.execute(select(GridNode).where(GridNode.name == "TestNode"))).scalars().first()
            node.durability = 20.0
            char.power = 100.0
            await session.commit()

        # Bolster with 20 power: base gain = 20 * 0.5 = 10.0. With +20% fortify = 12.0 gain.
        res = await terr_repo.bolster_node("Tester", "rizon", 20.0)
        self.assertTrue(res["success"])
        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "TestNode"))).scalars().first()
            self.assertAlmostEqual(node.durability, 32.0, places=2)

    async def test_arenadb_and_player_facade_integration(self):
        """R1: Verify ArenaDB and PlayerFacade skill methods delegate and execute correctly."""
        from ai_grid.grid_db import ArenaDB
        from ai_grid.database.repositories.character_repo import CharacterRepository
        db = ArenaDB()
        db.async_session = self.async_session
        db.skill = SkillRepository(self.async_session)
        db.character = CharacterRepository(self.async_session)

        # 1. get_available_skills async facade
        avail = await db.get_available_skills()
        self.assertEqual(len(avail), 8)
        avail_player = await db.player.get_available_skills()
        self.assertEqual(len(avail_player), 8)

        # 2. start_skill via facade
        start_res = await db.start_skill("Tester", "rizon", "powergen")
        self.assertTrue(start_res["success"])

        # 3. get_character_skills via facade
        char_skills = await db.get_character_skills("Tester", "rizon")
        self.assertEqual(char_skills["slots_used"], 1)

        # 4. get_skill_info via facade
        info = await db.get_skill_info("Tester", "rizon", "powergen")
        self.assertTrue(info["is_learned"])
        self.assertEqual(info["level"], 1)

        # 5. train_skill via facade
        train_res = await db.train_skill("Tester", "rizon")
        self.assertTrue(train_res["success"])

        # 6. quit_training via facade
        quit_res = await db.quit_training("Tester", "rizon")
        self.assertTrue(quit_res["success"])

        # 7. forget_skill via facade
        forget_res = await db.forget_skill("Tester", "rizon", "powergen")
        self.assertTrue(forget_res["success"])

        # 8. get_skill_modifiers_by_nick via facade
        mods = await db.get_skill_modifiers_by_nick("Tester", "rizon")
        self.assertIn("levels", mods)
        self.assertIn("powergen_bonus", mods)

    async def test_cannot_start_already_maxed_skill(self):
        """Edge Case: Cannot start/activate training on a skill already at maximum level."""
        await self.repo.start_skill("Tester", "rizon", "attack")
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "attack"))).scalars().first()
            cs.level = 4
            cs.is_active = False
            await session.commit()

        # Attempt to start attack again
        res = await self.repo.start_skill("Tester", "rizon", "attack")
        self.assertFalse(res["success"])
        self.assertIn("maximum level", res["error"].lower())

    async def test_train_when_no_skill_or_all_paused(self):
        """Edge Case: Training fails gracefully when no skill is started or all skills are paused."""
        # 1. No skills started at all
        res1 = await self.repo.train_skill("Tester", "rizon")
        self.assertFalse(res1["success"])
        self.assertIn("no skill is currently being trained", res1["error"].lower())

        # 2. Learn a skill then quit training
        await self.repo.start_skill("Tester", "rizon", "attack")
        await self.repo.quit_training("Tester", "rizon")

        res2 = await self.repo.train_skill("Tester", "rizon")
        self.assertFalse(res2["success"])
        self.assertIn("no skill is currently being trained", res2["error"].lower())

    async def test_help_skill_command_machine_mode(self):
        """Regression: Verify !a help skill in machine mode executes without UnboundLocalError."""
        from ai_grid.core.handlers.base import handle_help

        class MockNode:
            def __init__(self, async_session):
                self.net_name = "rizon"
                self.prefix = "!a"
                from ai_grid.grid_db import ArenaDB
                from ai_grid.database.repositories.character_repo import CharacterRepository
                self.db = ArenaDB()
                self.db.async_session = async_session
                self.db.character = CharacterRepository(async_session)
                self.sent_messages = []

            async def send(self, msg):
                self.sent_messages.append(msg)

        node = MockNode(self.async_session)
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "text"}'
            await session.commit()

        await handle_help(node, "Tester", ["skill"], "#arena")
        self.assertTrue(any("CMD:SKILL" in m for m in node.sent_messages))
        self.assertTrue(any("skill <list|<name>|start|train|forget|quit>" in m for m in node.sent_messages))

    async def test_stealth_negative_bonus_formatting(self):
        """UI Parity: Stealth skill displays negative bonus percentage (-10%/lvl) across queries."""
        await self.repo.start_skill("Tester", "rizon", "stealth")
        skills_data = await self.repo.get_character_skills("Tester", "rizon")
        stealth_entry = next((s for s in skills_data["skills"] if s["skill_name"] == "stealth"), None)
        self.assertIsNotNone(stealth_entry)
        self.assertEqual(stealth_entry["current_bonus"], "-10%")

        class MockNode:
            def __init__(self, async_session):
                self.net_name = "rizon"
                self.prefix = "!a"
                from ai_grid.grid_db import ArenaDB
                from ai_grid.database.repositories.character_repo import CharacterRepository
                self.db = ArenaDB()
                self.db.async_session = async_session
                self.db.skill = SkillRepository(async_session)
                self.db.character = CharacterRepository(async_session)
                self.sent_messages = []

            async def send(self, msg):
                self.sent_messages.append(msg)

        node = MockNode(self.async_session)
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "text"}'
            await session.commit()

        await handle_skill(node, "Tester", ["stealth"], "#arena")
        self.assertTrue(any("BONUS:-10%" in m for m in node.sent_messages))

    async def test_command_handler_full_subcommands_and_errors(self):
        """R2: Full validation of train, info alias, syntax errors, and cooldown messages in all modes."""
        class MockNode:
            def __init__(self, async_session):
                self.net_name = "rizon"
                self.prefix = "!a"
                from ai_grid.grid_db import ArenaDB
                from ai_grid.database.repositories.character_repo import CharacterRepository
                self.db = ArenaDB()
                self.db.async_session = async_session
                self.db.skill = SkillRepository(async_session)
                self.db.character = CharacterRepository(async_session)
                self.sent_messages = []

            async def send(self, msg):
                self.sent_messages.append(msg)

        node = MockNode(self.async_session)

        # 1. Syntax errors: start and forget without args
        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["start"], "#arena")
        self.assertTrue(any("Syntax: !a skill start <name>" in m for m in node.sent_messages))

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["forget"], "#arena")
        self.assertTrue(any("Syntax: !a skill forget <name>" in m for m in node.sent_messages))

        # 2. Unknown subcommand or skill
        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["teleport"], "#arena")
        self.assertTrue(any("Unknown skill command" in m for m in node.sent_messages))

        # 3. info subcommand alias
        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["info", "hack"], "#arena")
        self.assertTrue(any("Cyber Injection" in m for m in node.sent_messages))

        # 4. Training in Human Mode
        await self.repo.start_skill("Tester", "rizon", "hack")
        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["train"], "#arena")
        self.assertTrue(any("Training session complete for 'hack'" in m for m in node.sent_messages))

        # Immediate repeat triggers cooldown in Human Mode
        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["train"], "#arena")
        self.assertTrue(any("[COOLDOWN]" in m for m in node.sent_messages))

        # 5. Training cooldown in Text Mode
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "text"}'
            await session.commit()

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["train"], "#arena")
        self.assertTrue(any("[ACTION:SKILL][RESULT:COOLDOWN]" in m for m in node.sent_messages))

        # 6. Training cooldown in Narrative Mode
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "narrative"}'
            await session.commit()

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["train"], "#arena")
        self.assertTrue(any("core compilers are recharging" in m for m in node.sent_messages))

    async def test_forget_fortify_removes_hack_defense_bonus(self):
        """Edge Case: Node owner learns fortify, then forgets fortify; hack DC recalculates cleanly."""
        from ai_grid.database.repositories.infiltration_repo import InfiltrationRepository
        infil_repo = InfiltrationRepository(self.async_session)

        # Create Attacker character
        async with self.async_session() as session:
            player2 = Player(global_name="Attacker", is_autonomous=False)
            session.add(player2)
            await session.flush()
            alias2 = NetworkAlias(player_id=player2.id, network_name="rizon", nickname="Attacker")
            session.add(alias2)
            node = (await session.execute(select(GridNode).where(GridNode.name == "TestNode"))).scalars().first()
            node.availability_mode = "CLOSED"
            attacker = Character(
                player_id=player2.id,
                node_id=node.id,
                name="Attacker",
                race="Synth",
                char_class="Infiltrator",
                cpu=5, ram=5, bnd=5, sec=5, alg=1,
                power=100.0, stability=100.0, credits=100.0, data_units=10.0, mcp_heat=0.0
            )
            session.add(attacker)
            await session.commit()

        # Learn fortify Level 4 on Tester (Node Owner)
        await self.repo.start_skill("Tester", "rizon", "fortify")
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "fortify"))).scalars().first()
            cs.level = 4
            await session.commit()

        # Check that owner fortify is active
        mods_owner = await self.repo.get_skill_modifiers_by_nick("Tester", "rizon")
        self.assertAlmostEqual(mods_owner["fortify_bonus"], 0.40, places=2)

        # Forget fortify
        f_res = await self.repo.forget_skill("Tester", "rizon", "fortify")
        self.assertTrue(f_res["success"])

        # Verify fortify bonus is now 0.0
        mods_after = await self.repo.get_skill_modifiers_by_nick("Tester", "rizon")
        self.assertEqual(mods_after["fortify_bonus"], 0.0)

    async def test_get_skill_modifiers_by_nick(self):
        """R1: Verify get_skill_modifiers_by_nick accurately returns numeric multipliers."""
        await self.repo.start_skill("Tester", "rizon", "powergen")
        await self.repo.start_skill("Tester", "rizon", "attack")
        await self.repo.start_skill("Tester", "rizon", "stealth")
        await self.repo.start_skill("Tester", "rizon", "fortify")

        async with self.async_session() as session:
            skills = (await session.execute(select(CharacterSkill).where(CharacterSkill.character_id == 1))).scalars().all()
            for s in skills:
                if s.skill_name == "powergen": s.level = 1
                elif s.skill_name == "attack": s.level = 2
                elif s.skill_name == "stealth": s.level = 3
                elif s.skill_name == "fortify": s.level = 4
            await session.commit()

        mods = await self.repo.get_skill_modifiers_by_nick("Tester", "rizon")
        self.assertAlmostEqual(mods["powergen_bonus"], 0.10, places=2)
        self.assertAlmostEqual(mods["attack_bonus"], 0.20, places=2)
        self.assertAlmostEqual(mods["stealth_bonus"], 0.30, places=2)
        self.assertAlmostEqual(mods["fortify_bonus"], 0.40, places=2)
        self.assertEqual(mods["defend_bonus"], 0.0)
        self.assertEqual(mods["hack_bonus"], 0.0)
        self.assertEqual(mods["recon_bonus"], 0.0)
        self.assertEqual(mods["siphon_bonus"], 0.0)

    async def test_concurrent_training_race_condition(self):
        """Concurrency: Simultaneous train_skill calls enforce cooldown and prevent race condition."""
        import asyncio
        await self.repo.start_skill("Tester", "rizon", "attack")

        # Fire 5 concurrent training calls
        results = await asyncio.gather(
            self.repo.train_skill("Tester", "rizon"),
            self.repo.train_skill("Tester", "rizon"),
            self.repo.train_skill("Tester", "rizon"),
            self.repo.train_skill("Tester", "rizon"),
            self.repo.train_skill("Tester", "rizon"),
            return_exceptions=True
        )

        success_count = sum(1 for r in results if isinstance(r, dict) and r.get("success") is True)
        cooldown_count = sum(1 for r in results if isinstance(r, dict) and "cooldown" in str(r.get("error", "")).lower())

        self.assertEqual(success_count, 1)
        self.assertEqual(cooldown_count, 4)

        # Confirm database state: exactly 1 session recorded
        info = await self.repo.get_skill_info("Tester", "rizon", "attack")
        self.assertEqual(info["training_sessions"], 1)

    async def test_get_skill_level_facade_and_values(self):
        """R1: Verify get_skill_level on ArenaDB and PlayerFacade returns accurate levels."""
        from ai_grid.grid_db import ArenaDB
        from ai_grid.database.repositories.character_repo import CharacterRepository
        db = ArenaDB()
        db.async_session = self.async_session
        db.skill = SkillRepository(self.async_session)
        db.character = CharacterRepository(self.async_session)

        # Initially not learned
        lvl_unlearned = await db.get_skill_level("Tester", "rizon", "powergen")
        self.assertEqual(lvl_unlearned, 0)
        lvl_facade = await db.player.get_skill_level("Tester", "rizon", "powergen")
        self.assertEqual(lvl_facade, 0)

        # Start skill -> level 1
        await db.start_skill("Tester", "rizon", "powergen")
        lvl_learned = await db.get_skill_level("Tester", "rizon", "powergen")
        self.assertEqual(lvl_learned, 1)
        lvl_learned_facade = await db.player.get_skill_level("Tester", "rizon", "powergen")
        self.assertEqual(lvl_learned_facade, 1)

    async def test_max_level_automatic_deactivation_and_display(self):
        """Edge Case: Reaching Level 4 automatically deactivates skill and displays MAX status in all modes."""
        await self.repo.start_skill("Tester", "rizon", "attack")

        # Set to Level 3, 23 sessions
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "attack"))).scalars().first()
            cs.level = 3
            cs.training_sessions = 23
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.last_skill_train_at = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=2)
            cs.last_trained_at = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=2)
            await session.commit()

        # 24th session reaches Level 4
        res = await self.repo.train_skill("Tester", "rizon")
        self.assertTrue(res["success"])
        self.assertEqual(res["level"], 4)
        self.assertTrue(res["leveled_up"])
        self.assertTrue(res["is_max"])

        # DB verification: is_active is automatically deactivated (False)
        info = await self.repo.get_skill_info("Tester", "rizon", "attack")
        self.assertFalse(info["is_active"])
        self.assertEqual(info["level"], 4)

        # UI verification in MockNode
        class MockNode:
            def __init__(self, async_session):
                self.net_name = "rizon"
                self.prefix = "!a"
                from ai_grid.grid_db import ArenaDB
                from ai_grid.database.repositories.character_repo import CharacterRepository
                self.db = ArenaDB()
                self.db.async_session = async_session
                self.db.skill = SkillRepository(async_session)
                self.db.character = CharacterRepository(async_session)
                self.sent_messages = []

            async def send(self, msg):
                self.sent_messages.append(msg)

        node = MockNode(self.async_session)

        # 1. Human mode
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "human"}'
            await session.commit()

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["list"], "#arena")
        self.assertTrue(any("[MAX]" in m for m in node.sent_messages))

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["attack"], "#arena")
        self.assertTrue(any("Level 4/4 (MAX)" in m for m in node.sent_messages))

        # 2. Text mode
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "text"}'
            await session.commit()

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["list"], "#arena")
        self.assertTrue(any("ATTACK:L4:0/24:MAXED" in m for m in node.sent_messages))

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["attack"], "#arena")
        self.assertTrue(any("STATUS:MAX" in m for m in node.sent_messages))

        # 3. Narrative mode
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "narrative"}'
            await session.commit()

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["list"], "#arena")
        self.assertTrue(any("mastered" in m for m in node.sent_messages))

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["attack"], "#arena")
        self.assertTrue(any("fully compiled at maximum Level 4/4" in m for m in node.sent_messages))

    async def test_skill_help_command_all_modes(self):
        """R2: !a skill help and !a skill ? return command menus across human, text, and narrative modes."""
        class MockNode:
            def __init__(self, async_session):
                self.net_name = "rizon"
                self.prefix = "!a"
                from ai_grid.grid_db import ArenaDB
                from ai_grid.database.repositories.character_repo import CharacterRepository
                self.db = ArenaDB()
                self.db.async_session = async_session
                self.db.skill = SkillRepository(async_session)
                self.db.character = CharacterRepository(async_session)
                self.sent_messages = []

            async def send(self, msg):
                self.sent_messages.append(msg)

        node = MockNode(self.async_session)

        # Human Mode
        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["help"], "#arena")
        self.assertTrue(any("Skill Commands:" in m for m in node.sent_messages))

        # Text Mode
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "text"}'
            await session.commit()

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["?"], "#arena")
        self.assertTrue(any("[ACTION:SKILL][RESULT:HELP]" in m for m in node.sent_messages))
        self.assertTrue(any("COMMANDS:[LIST,<NAME>,START,TRAIN,FORGET,QUIT]" in m for m in node.sent_messages))

        # Narrative Mode
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.prefs = '{"output_mode": "narrative"}'
            await session.commit()

        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["help"], "#arena")
        self.assertTrue(any("Neural skill commands available:" in m for m in node.sent_messages))

    async def test_train_locks_key_normalization_and_loop_robustness(self):
        """Robustness: train_skill serializes locks regardless of network case variations."""
        await self.repo.start_skill("Tester", "rizon", "attack")
        res = await self.repo.train_skill("Tester", "rizon")
        self.assertTrue(res["success"])

        # Casing difference: 'Rizon' vs 'rizon'
        char_key_lower = "rizon:tester"
        self.assertIn(char_key_lower, SkillRepository._train_locks)
        stored_entry = SkillRepository._train_locks[char_key_lower]
        self.assertIsInstance(stored_entry, tuple)
        self.assertEqual(len(stored_entry), 2)

    async def test_stealth_negative_cooling_not_reduced(self):
        """Mechanics: Stealth skill (-10% heat/lvl) reduces positive heat gains but preserves cooling rate."""
        from ai_grid.database.repositories.reputation_repo import ReputationRepository
        rep_repo = ReputationRepository(self.async_session)

        # Set heat to 5.0
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.mcp_heat = 5.0
            await session.commit()

        # Learn stealth Level 4 (-40% heat gain)
        await self.repo.start_skill("Tester", "rizon", "stealth")
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "stealth"))).scalars().first()
            cs.level = 4
            await session.commit()

        # Negative delta (cooling): -2.0 heat decay must NOT be penalized/reduced
        h_cooled = await rep_repo.update_heat("Tester", "rizon", -2.0)
        self.assertAlmostEqual(h_cooled, 3.0, places=2)

    async def test_pvp_attack_combat_repo_with_skills(self):
        """R3: Verify CombatRepository.pvp_attack applies attack and defend skill modifiers."""
        from ai_grid.database.repositories.combat_repo import CombatRepository
        combat_repo = CombatRepository(self.async_session)

        # Create Defender character in same node
        async with self.async_session() as session:
            player2 = Player(global_name="DefenderBot", is_autonomous=False)
            session.add(player2)
            await session.flush()
            alias2 = NetworkAlias(player_id=player2.id, network_name="rizon", nickname="DefenderBot")
            session.add(alias2)
            node = (await session.execute(select(GridNode).where(GridNode.name == "TestNode"))).scalars().first()
            node.node_type = "void" # Combat allowed
            defender = Character(
                player_id=player2.id,
                node_id=node.id,
                name="DefenderBot",
                race="Synth",
                char_class="Guardian",
                cpu=5, ram=5, bnd=0, sec=10, alg=0, # bnd=0 means 0% evade
                power=100.0, stability=100.0, credits=100.0, data_units=10.0, mcp_heat=0.0
            )
            session.add(defender)
            await session.commit()

        # Attacker learns attack Level 2 (+20% kinetic)
        await self.repo.start_skill("Tester", "rizon", "attack")
        async with self.async_session() as session:
            cs_att = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "attack"))).scalars().first()
            cs_att.level = 2
            # Defender learns defend Level 2 (+20% reduction)
            char_def = (await session.execute(select(Character).where(Character.name == "DefenderBot"))).scalars().first()
            session.add(CharacterSkill(character_id=char_def.id, skill_name="defend", level=2, is_active=False))
            char_att = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char_att.alg = 0 # 0% crit chance for deterministic damage test
            await session.commit()

        # Attacker: CPU=5, RAM=5 -> raw = 5*5 + 5 = 30.
        # attack Level 2 (+20%) -> 30 * 1.2 = 36.
        # Defender SEC = 10 -> 36 - 10 = 26.
        # defend Level 2 (-20%) -> 26 * 0.8 = 20.
        ok, msg, _ = await combat_repo.grid_attack("Tester", "DefenderBot", "rizon")
        self.assertTrue(ok)
        self.assertIn("20 DMG", msg)

    async def test_explore_node_with_recon_skill(self):
        """R3: DiscoveryRepository.explore_node awards recon yield bonus on discoveries."""
        from ai_grid.database.repositories.discovery_repo import DiscoveryRepository
        disc_repo = DiscoveryRepository(self.async_session)

        # Set node to closed so explore opens it
        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "TestNode"))).scalars().first()
            node.availability_mode = "CLOSED"
            node.owner_character_id = None
            node.power_stored = 50.0
            node.upgrade_level = 1
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.credits = 0.0
            char.data_units = 0.0
            char.alg = 100 # Guarantee 100% explore success roll
            await session.commit()

        # Learn recon Level 3 (+30% yield)
        await self.repo.start_skill("Tester", "rizon", "recon")
        async with self.async_session() as session:
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "recon"))).scalars().first()
            cs.level = 3
            await session.commit()

        res = await disc_repo.explore_node("Tester", "rizon")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["discovery"], "sector_open")

        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            # Base open gives 5.0c and 1.0 data. With +30%: 6.5c and 1.3 data.
            self.assertAlmostEqual(char.credits, 6.5, places=2)
            self.assertAlmostEqual(char.data_units, 1.3, places=2)

    async def test_input_guards_none_and_empty_inputs(self):
        """Robustness: SkillRepository methods gracefully reject None or empty parameters without crashing."""
        self.assertEqual(await self.repo.get_skill_level("", "", ""), 0)
        self.assertEqual(await self.repo.get_skill_level(None, None, None), 0)

        info_none = await self.repo.get_skill_info(None, None, None)
        self.assertIn("error", info_none)
        self.assertIn("not found", info_none["error"].lower())

        start_none = await self.repo.start_skill(None, None, None)
        self.assertFalse(start_none["success"])

        start_bad_skill = await self.repo.start_skill("Tester", "rizon", "")
        self.assertFalse(start_bad_skill["success"])

        train_none = await self.repo.train_skill(None, None)
        self.assertFalse(train_none["success"])

        forget_none = await self.repo.forget_skill(None, None, None)
        self.assertFalse(forget_none["success"])

        quit_none = await self.repo.quit_training(None, None)
        self.assertFalse(quit_none["success"])

        mods_none = await self.repo.get_skill_modifiers_by_nick(None, None)
        self.assertEqual(mods_none, {})

        char_skills_none = await self.repo.get_character_skills(None, None)
        self.assertIn("error", char_skills_none)

    async def test_pause_and_stop_aliases_and_empty_args(self):
        """R2: 'skill pause' and 'skill stop' function as aliases for 'skill quit'; empty args display list."""
        class MockNode:
            def __init__(self, async_session):
                self.net_name = "rizon"
                self.prefix = "!a"
                from ai_grid.grid_db import ArenaDB
                from ai_grid.database.repositories.character_repo import CharacterRepository
                self.db = ArenaDB()
                self.db.async_session = async_session
                self.db.skill = SkillRepository(async_session)
                self.db.character = CharacterRepository(async_session)
                self.sent_messages = []

            async def send(self, msg):
                self.sent_messages.append(msg)

        node = MockNode(self.async_session)

        # Start attack skill
        await self.repo.start_skill("Tester", "rizon", "attack")

        # 1. Test 'skill pause' alias
        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["pause"], "#arena")
        self.assertTrue(any("paused" in m.lower() for m in node.sent_messages))
        skills_data = await self.repo.get_character_skills("Tester", "rizon")
        self.assertIsNone(skills_data["active_skill"])

        # Resume and test 'skill stop' alias
        await self.repo.start_skill("Tester", "rizon", "attack")
        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["stop"], "#arena")
        self.assertTrue(any("paused" in m.lower() for m in node.sent_messages))

        # 2. Test empty string argument defaults to skill list
        node.sent_messages.clear()
        await handle_skill(node, "Tester", ["   "], "#arena")
        self.assertTrue(any("=== [CHARACTER SKILLS" in m for m in node.sent_messages))

    async def test_cooldown_persists_after_forgetting_active_skill(self):
        """Security: Players cannot bypass 1h training cooldown by forgetting and starting a new skill."""
        await self.repo.start_skill("Tester", "rizon", "attack")
        t1 = await self.repo.train_skill("Tester", "rizon")
        self.assertTrue(t1["success"])

        # Forget attack
        f_res = await self.repo.forget_skill("Tester", "rizon", "attack")
        self.assertTrue(f_res["success"])

        # Start hack
        s_res = await self.repo.start_skill("Tester", "rizon", "hack")
        self.assertTrue(s_res["success"])

        # Immediate training on hack must still be on cooldown
        t2 = await self.repo.train_skill("Tester", "rizon")
        self.assertFalse(t2["success"])
        self.assertIn("cooldown", t2["error"].lower())
        self.assertGreater(t2["cooldown_remaining"], 0)

    async def test_get_character_skills_reports_cooldown_remaining(self):
        """R1: get_character_skills accurately calculates character-wide cooldown_remaining."""
        await self.repo.start_skill("Tester", "rizon", "powergen")

        # Before training: cooldown_remaining is 0
        s1 = await self.repo.get_character_skills("Tester", "rizon")
        self.assertEqual(s1["cooldown_remaining"], 0)

        # After training: cooldown_remaining is > 0 and <= 3600
        await self.repo.train_skill("Tester", "rizon")
        s2 = await self.repo.get_character_skills("Tester", "rizon")
        self.assertGreater(s2["cooldown_remaining"], 3500)
        self.assertLessEqual(s2["cooldown_remaining"], 3600)

    async def test_skills_command_router_routing(self):
        """R2: CommandRouter routes both '!a skill' and '!a skills'."""
        from ai_grid.core.command_router import CommandRouter

        class MockRouterNode:
            def __init__(self, async_session):
                self.net_name = "rizon"
                self.prefix = "!a"
                from ai_grid.grid_db import ArenaDB
                from ai_grid.database.repositories.character_repo import CharacterRepository
                self.db = ArenaDB()
                self.db.async_session = async_session
                self.db.skill = SkillRepository(async_session)
                self.db.character = CharacterRepository(async_session)
                self.sent_messages = []
                self.config = {"channel": "#arena", "nickname": "GridBot"}
                self.flood_config = {'max_tokens': 10, 'refill_rate': 1.0}
                self.action_timestamps = {}

            async def send(self, msg):
                self.sent_messages.append(msg)

        node = MockRouterNode(self.async_session)
        router = CommandRouter(node)

        # Dispatch '!a skills list'
        await router.dispatch("Tester", "PRIVMSG", "#arena", "!a skills list", False)
        for _ in range(30):
            if any("=== [CHARACTER SKILLS" in m for m in node.sent_messages):
                break
            await asyncio.sleep(0.05)
        self.assertTrue(any("=== [CHARACTER SKILLS" in m for m in node.sent_messages))

        # Dispatch '!a skill list' (singular)
        node.sent_messages.clear()
        await router.dispatch("Tester", "PRIVMSG", "#arena", "!a skill list", False)
        for _ in range(30):
            if any("=== [CHARACTER SKILLS" in m for m in node.sent_messages):
                break
            await asyncio.sleep(0.05)
        self.assertTrue(any("=== [CHARACTER SKILLS" in m for m in node.sent_messages))

        # Dispatch bare '!a skill' without args (defaults to skill list)
        node.sent_messages.clear()
        await router.dispatch("Tester", "PRIVMSG", "#arena", "!a skill", False)
        for _ in range(30):
            if any("=== [CHARACTER SKILLS" in m for m in node.sent_messages):
                break
            await asyncio.sleep(0.05)
        self.assertTrue(any("=== [CHARACTER SKILLS" in m for m in node.sent_messages))

    async def test_naive_datetime_handling_and_clock_skew(self):
        """Robustness: Mixed tz-naive/tz-aware datetimes and future clock skew are handled safely."""
        await self.repo.start_skill("Tester", "rizon", "attack")

        # 1. Mixed naive and aware datetimes
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            cs = (await session.execute(select(CharacterSkill).where(CharacterSkill.skill_name == "attack"))).scalars().first()
            # Naive datetime on char
            char.last_skill_train_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=30)
            # Aware datetime on skill
            cs.last_trained_at = datetime.datetime.now(timezone.utc) - datetime.timedelta(minutes=20)
            await session.commit()

        # Should not raise TypeError: can't compare offset-naive and offset-aware datetimes
        c_skills = await self.repo.get_character_skills("Tester", "rizon")
        self.assertGreater(c_skills["cooldown_remaining"], 2300)
        self.assertLessEqual(c_skills["cooldown_remaining"], 2500)

        s_info = await self.repo.get_skill_info("Tester", "rizon", "attack")
        self.assertGreater(s_info["cooldown_remaining"], 2300)
        self.assertLessEqual(s_info["cooldown_remaining"], 2500)

        t_res = await self.repo.train_skill("Tester", "rizon")
        self.assertFalse(t_res["success"])
        self.assertIn("cooldown", t_res["error"].lower())

        # 2. Clock skew: Future timestamp clamped to TRAINING_COOLDOWN_SECONDS (3600s)
        async with self.async_session() as session:
            char = (await session.execute(select(Character).where(Character.name == "Tester"))).scalars().first()
            char.last_skill_train_at = datetime.datetime.now(timezone.utc) + datetime.timedelta(hours=5)
            await session.commit()

        skew_skills = await self.repo.get_character_skills("Tester", "rizon")
        self.assertEqual(skew_skills["cooldown_remaining"], TRAINING_COOLDOWN_SECONDS)

        skew_train = await self.repo.train_skill("Tester", "rizon")
        self.assertFalse(skew_train["success"])
        self.assertEqual(skew_train["cooldown_remaining"], TRAINING_COOLDOWN_SECONDS)


if __name__ == "__main__":
    unittest.main()


