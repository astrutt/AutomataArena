# ai_grid/database/repositories/skill_repo.py
import asyncio
import datetime
from datetime import timezone
from sqlalchemy import func
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from ai_grid.models import Character, Player, NetworkAlias, CharacterSkill
from ai_grid.database.base_repo import BaseRepository

MAX_CONCURRENT_SKILLS = 4
MAX_SKILL_LEVEL = 4
SESSIONS_PER_LEVEL = 24
TRAINING_COOLDOWN_SECONDS = 3600 # 1 session per hour

SKILL_DEFINITIONS = {
    "powergen": {
        "name": "powergen",
        "display_name": "Power Generation",
        "category": "initial",
        "description": "Optimizes internal capacitance and harvesting algorithms to boost Unit Power generation rate.",
        "effect": "+10% power generation rate per level",
        "bonus_per_level": 0.10,
        "bonus_stat": "powergen_rate",
    },
    "attack": {
        "name": "attack",
        "display_name": "Kinetic Strike",
        "category": "initial",
        "description": "Calibrates kinetic combat subroutines to deliver higher damage in physical strikes.",
        "effect": "+10% kinetic damage per level",
        "bonus_per_level": 0.10,
        "bonus_stat": "kinetic_damage",
    },
    "defend": {
        "name": "defend",
        "display_name": "Damage Buffer",
        "category": "initial",
        "description": "Hardens chassis shielding and defensive buffering to mitigate incoming combat damage.",
        "effect": "+10% damage reduction per level",
        "bonus_per_level": 0.10,
        "bonus_stat": "damage_reduction",
    },
    "hack": {
        "name": "hack",
        "display_name": "Cyber Injection",
        "category": "initial",
        "description": "Sharpens offensive cyber payloads and code injection vectors to deal higher cyber damage.",
        "effect": "+10% cyber damage per level",
        "bonus_per_level": 0.10,
        "bonus_stat": "cyber_damage",
    },
    "recon": {
        "name": "recon",
        "display_name": "Reconnaissance",
        "category": "expansion",
        "description": "Enhances sensor resolution and stealth telemetry during sector exploration and node probing.",
        "effect": "+10% explore/probe yield, -10% detection chance per level",
        "bonus_per_level": 0.10,
        "bonus_stat": "recon_yield",
    },
    "siphon": {
        "name": "siphon",
        "display_name": "Data Siphon",
        "category": "expansion",
        "description": "Optimizes exfiltration channels to accelerate extraction speed and increase resource siphoning quantity.",
        "effect": "+10% exfil speed and quantity per level",
        "bonus_per_level": 0.10,
        "bonus_stat": "siphon_yield",
    },
    "stealth": {
        "name": "stealth",
        "display_name": "Stealth Operations",
        "category": "expansion",
        "description": "Masks electronic signatures and obfuscates command traces to suppress MCP heat buildup.",
        "effect": "-10% MCP heat generation per action per level",
        "bonus_per_level": 0.10,
        "bonus_stat": "heat_reduction",
    },
    "fortify": {
        "name": "fortify",
        "display_name": "Node Fortification",
        "category": "expansion",
        "description": "Reinforces defense architectures, firewall thresholds, and bolstering efficiency on player-owned nodes.",
        "effect": "+10% owned node defense efficiency per level",
        "bonus_per_level": 0.10,
        "bonus_stat": "node_defense",
    },
}

ALL_SKILLS = list(SKILL_DEFINITIONS.keys())


def _normalize_dt(dt):
    if dt is not None and getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class SkillRepository(BaseRepository):
    @classmethod
    async def get_available_skills(cls) -> dict:
        """Returns metadata for all 8 defined skills."""
        return dict(SKILL_DEFINITIONS)

    @staticmethod
    def get_available_skills_sync() -> dict:
        """Returns metadata for all 8 defined skills synchronously."""
        return dict(SKILL_DEFINITIONS)

    async def get_character_skills(self, name: str, network: str) -> dict:
        """Retrieves learned skills, active training status, and slot capacity for a character."""
        if not name or not network:
            return {"error": "Character not found."}

        async with self.async_session() as session:
            char = await self.get_character_by_nick(name, network, session)
            if not char:
                return {"error": "Character not found."}

            stmt = select(CharacterSkill).where(CharacterSkill.character_id == char.id).order_by(CharacterSkill.id)
            skills = (await session.execute(stmt)).scalars().all()

            now = datetime.datetime.now(timezone.utc)
            latest_train = _normalize_dt(char.last_skill_train_at)

            skill_list = []
            active_skill = None
            for s in skills:
                s_trained = _normalize_dt(s.last_trained_at)
                if s_trained and (latest_train is None or s_trained > latest_train):
                    latest_train = s_trained

                meta = SKILL_DEFINITIONS.get(s.skill_name, {})
                sign = "-" if s.skill_name == "stealth" else "+"
                bonus_val = int(s.level * meta.get('bonus_per_level', 0.10) * 100)
                s_dict = {
                    "skill_name": s.skill_name,
                    "display_name": meta.get("display_name", s.skill_name.capitalize()),
                    "category": meta.get("category", "initial"),
                    "level": s.level,
                    "max_level": MAX_SKILL_LEVEL,
                    "training_sessions": s.training_sessions,
                    "max_sessions": SESSIONS_PER_LEVEL,
                    "is_active": s.is_active,
                    "last_trained_at": s.last_trained_at,
                    "effect": meta.get("effect", ""),
                    "current_bonus": f"{sign}{bonus_val}%",
                }
                skill_list.append(s_dict)
                if s.is_active:
                    active_skill = s_dict

            cooldown_remaining = 0
            if latest_train:
                if latest_train.tzinfo is None:
                    latest_train = latest_train.replace(tzinfo=timezone.utc)
                elapsed = (now - latest_train).total_seconds()
                if elapsed < TRAINING_COOLDOWN_SECONDS:
                    cooldown_remaining = max(0, min(TRAINING_COOLDOWN_SECONDS, int(TRAINING_COOLDOWN_SECONDS - elapsed)))

            return {
                "character": char.name,
                "skills": skill_list,
                "active_skill": active_skill,
                "slots_used": len(skill_list),
                "slots_max": MAX_CONCURRENT_SKILLS,
                "last_trained_at": latest_train,
                "cooldown_remaining": cooldown_remaining,
            }

    async def get_skill_info(self, name: str, network: str, skill_name: str) -> dict:
        """Retrieves specific skill info for a character, including level and training progress."""
        if not name or not network or not skill_name:
            return {"error": "Character not found."}

        skill_clean = skill_name.lower().strip()
        meta = SKILL_DEFINITIONS.get(skill_clean)
        if not meta:
            return {"error": f"Unknown skill '{skill_name}'. Valid skills: {', '.join(ALL_SKILLS)}"}

        async with self.async_session() as session:
            char = await self.get_character_by_nick(name, network, session)
            if not char:
                return {"error": "Character not found."}

            stmt = select(CharacterSkill).where(
                CharacterSkill.character_id == char.id,
                CharacterSkill.skill_name == skill_clean
            )
            learned = (await session.execute(stmt)).scalars().first()

            now = datetime.datetime.now(timezone.utc)
            cooldown_remaining = 0
            last_train = _normalize_dt(char.last_skill_train_at)
            learned_trained = _normalize_dt(learned.last_trained_at) if learned else None
            if learned_trained and (last_train is None or learned_trained > last_train):
                last_train = learned_trained

            if last_train:
                elapsed = (now - last_train).total_seconds()
                if elapsed < TRAINING_COOLDOWN_SECONDS:
                    cooldown_remaining = max(0, min(TRAINING_COOLDOWN_SECONDS, int(TRAINING_COOLDOWN_SECONDS - elapsed)))

            return {
                "skill_name": skill_clean,
                "display_name": meta["display_name"],
                "category": meta["category"],
                "description": meta["description"],
                "effect": meta["effect"],
                "is_learned": learned is not None,
                "level": learned.level if learned else 0,
                "max_level": MAX_SKILL_LEVEL,
                "training_sessions": learned.training_sessions if learned else 0,
                "max_sessions": SESSIONS_PER_LEVEL,
                "is_active": learned.is_active if learned else False,
                "cooldown_remaining": cooldown_remaining,
                "bonus_per_level": meta["bonus_per_level"],
            }

    async def start_skill(self, name: str, network: str, skill_name: str) -> dict:
        """Begins or resumes training for a skill, enforcing the 4-skill slot limit."""
        if not name or not network:
            return {"success": False, "error": "Character not found."}

        skill_clean = (skill_name or "").lower().strip()
        if skill_clean not in SKILL_DEFINITIONS:
            return {"success": False, "error": f"Unknown skill '{skill_name}'. Valid skills: {', '.join(ALL_SKILLS)}"}

        for attempt in range(3):
            try:
                async with self.async_session() as session:
                    char = await self.get_character_by_nick(name, network, session)
                    if not char:
                        return {"success": False, "error": "Character not found."}

                    stmt = select(CharacterSkill).where(CharacterSkill.character_id == char.id)
                    existing_skills = (await session.execute(stmt)).scalars().all()

                    target_skill = next((s for s in existing_skills if s.skill_name == skill_clean), None)

                    if target_skill:
                        if target_skill.is_active:
                            return {"success": False, "error": f"Skill '{skill_clean}' is already being actively trained."}
                        if target_skill.level >= MAX_SKILL_LEVEL:
                            return {"success": False, "error": f"Skill '{skill_clean}' is already at maximum level (Level {MAX_SKILL_LEVEL})."}
                        # Resume training on existing skill
                        for s in existing_skills:
                            s.is_active = (s.id == target_skill.id)
                        await session.commit()
                        return {
                            "success": True,
                            "resumed": True,
                            "skill": skill_clean,
                            "level": target_skill.level,
                            "sessions": target_skill.training_sessions,
                            "slots_used": len(existing_skills),
                        }

                    # New skill learning: check 4-slot limit
                    if len(existing_skills) >= MAX_CONCURRENT_SKILLS:
                        return {
                            "success": False,
                            "error": f"Skill capacity reached ({MAX_CONCURRENT_SKILLS}/{MAX_CONCURRENT_SKILLS} slots). Use 'skill forget <name>' to free a slot."
                        }

                    # Pause any currently active skill
                    for s in existing_skills:
                        s.is_active = False

                    new_skill = CharacterSkill(
                        character_id=char.id,
                        skill_name=skill_clean,
                        level=1,
                        training_sessions=0,
                        is_active=True,
                    )
                    session.add(new_skill)
                    await session.commit()

                    return {
                        "success": True,
                        "resumed": False,
                        "skill": skill_clean,
                        "level": 1,
                        "sessions": 0,
                        "slots_used": len(existing_skills) + 1,
                    }
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))

    _train_locks = {}

    async def train_skill(self, name: str, network: str) -> dict:
        """Executes a training session for the currently active skill, enforcing 1h cooldown and 24 sessions/lvl."""
        if not name or not network:
            return {"success": False, "error": "Character not found."}

        char_key = f"{network.lower().strip()}:{name.lower().strip()}"
        loop = asyncio.get_running_loop()
        entry = SkillRepository._train_locks.get(char_key)
        if entry is None or entry[0] != loop or getattr(entry[0], 'is_closed', lambda: False)():
            lock = asyncio.Lock()
            SkillRepository._train_locks[char_key] = (loop, lock)
        else:
            lock = entry[1]

        async with lock:
            for attempt in range(3):
                try:
                    async with self.async_session() as session:
                        char = await self.get_character_by_nick(name, network, session)
                        if not char:
                            return {"success": False, "error": "Character not found."}

                        stmt = select(CharacterSkill).where(
                            CharacterSkill.character_id == char.id,
                            CharacterSkill.is_active == True
                        )
                        active_skill = (await session.execute(stmt)).scalars().first()

                        if not active_skill:
                            return {"success": False, "error": "No skill is currently being trained. Use 'skill start <name>' to begin training."}

                        if active_skill.level >= MAX_SKILL_LEVEL:
                            active_skill.is_active = False
                            await session.commit()
                            return {"success": False, "error": f"Skill '{active_skill.skill_name}' is already at maximum level (Level {MAX_SKILL_LEVEL})."}

                        # Enforce 1-hour cooldown constraint
                        now = datetime.datetime.now(timezone.utc)
                        last_train = _normalize_dt(char.last_skill_train_at)
                        active_trained = _normalize_dt(active_skill.last_trained_at)
                        if active_trained and (last_train is None or active_trained > last_train):
                            last_train = active_trained

                        if last_train:
                            elapsed = (now - last_train).total_seconds()
                            if elapsed < TRAINING_COOLDOWN_SECONDS:
                                rem = max(0, min(TRAINING_COOLDOWN_SECONDS, int(TRAINING_COOLDOWN_SECONDS - elapsed)))
                                mins = rem // 60
                                secs = rem % 60
                                return {
                                    "success": False,
                                    "error": f"Training on cooldown. Next session available in {mins}m {secs}s.",
                                    "cooldown_remaining": rem,
                                }

                        active_skill.training_sessions += 1
                        active_skill.last_trained_at = now
                        char.last_skill_train_at = now

                        leveled_up = False
                        if active_skill.training_sessions >= SESSIONS_PER_LEVEL:
                            active_skill.level += 1
                            active_skill.training_sessions = 0
                            leveled_up = True
                            if active_skill.level >= MAX_SKILL_LEVEL:
                                active_skill.is_active = False

                        await session.commit()
                        return {
                            "success": True,
                            "skill": active_skill.skill_name,
                            "level": active_skill.level,
                            "sessions": active_skill.training_sessions,
                            "max_sessions": SESSIONS_PER_LEVEL,
                            "leveled_up": leveled_up,
                            "is_max": active_skill.level >= MAX_SKILL_LEVEL,
                        }
                except Exception as e:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.05 * (attempt + 1))

    async def forget_skill(self, name: str, network: str, skill_name: str) -> dict:
        """Removes a skill from the character and frees its slot."""
        if not name or not network:
            return {"success": False, "error": "Character not found."}

        skill_clean = (skill_name or "").lower().strip()
        for attempt in range(3):
            try:
                async with self.async_session() as session:
                    char = await self.get_character_by_nick(name, network, session)
                    if not char:
                        return {"success": False, "error": "Character not found."}

                    stmt = select(CharacterSkill).where(
                        CharacterSkill.character_id == char.id,
                        CharacterSkill.skill_name == skill_clean
                    )
                    target = (await session.execute(stmt)).scalars().first()

                    if not target:
                        return {"success": False, "error": f"Skill '{skill_clean}' is not currently learned."}

                    await session.delete(target)
                    await session.commit()

                    return {
                        "success": True,
                        "skill": skill_clean,
                        "slots_freed": 1,
                    }
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))

    async def quit_training(self, name: str, network: str) -> dict:
        """Pauses the current active training session without forgetting the skill."""
        if not name or not network:
            return {"success": False, "error": "Character not found."}

        for attempt in range(3):
            try:
                async with self.async_session() as session:
                    char = await self.get_character_by_nick(name, network, session)
                    if not char:
                        return {"success": False, "error": "Character not found."}

                    stmt = select(CharacterSkill).where(
                        CharacterSkill.character_id == char.id,
                        CharacterSkill.is_active == True
                    )
                    active_skill = (await session.execute(stmt)).scalars().first()

                    if not active_skill:
                        return {"success": False, "error": "No active training session in progress."}

                    active_skill.is_active = False
                    await session.commit()

                    return {
                        "success": True,
                        "skill": active_skill.skill_name,
                        "level": active_skill.level,
                        "sessions": active_skill.training_sessions,
                    }
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))

    async def get_skill_level(self, name: str, network: str, skill_name: str) -> int:
        """Returns the current level (1-4) of a specific skill, or 0 if not learned."""
        if not name or not network or not skill_name:
            return 0

        async with self.async_session() as session:
            char = await self.get_character_by_nick(name, network, session)
            if not char:
                return 0

            stmt = select(CharacterSkill.level).where(
                CharacterSkill.character_id == char.id,
                CharacterSkill.skill_name == skill_name.lower().strip()
            )
            res = (await session.execute(stmt)).scalar()
            return res or 0

    async def get_skill_modifiers_by_nick(self, name: str, network: str) -> dict:
        """Returns all active skill levels and numeric modifier multipliers for a character."""
        if not name or not network:
            return {}

        async with self.async_session() as session:
            char = await self.get_character_by_nick(name, network, session)
            if not char:
                return {}

            stmt = select(CharacterSkill).where(CharacterSkill.character_id == char.id)
            skills = (await session.execute(stmt)).scalars().all()

            mods = {
                "levels": {s.skill_name: s.level for s in skills},
                "powergen_bonus": 0.0,
                "attack_bonus": 0.0,
                "defend_bonus": 0.0,
                "hack_bonus": 0.0,
                "recon_bonus": 0.0,
                "siphon_bonus": 0.0,
                "stealth_bonus": 0.0,
                "fortify_bonus": 0.0,
            }

            for s in skills:
                if s.skill_name == "powergen":
                    mods["powergen_bonus"] = 0.10 * s.level
                elif s.skill_name == "attack":
                    mods["attack_bonus"] = 0.10 * s.level
                elif s.skill_name == "defend":
                    mods["defend_bonus"] = 0.10 * s.level
                elif s.skill_name == "hack":
                    mods["hack_bonus"] = 0.10 * s.level
                elif s.skill_name == "recon":
                    mods["recon_bonus"] = 0.10 * s.level
                elif s.skill_name == "siphon":
                    mods["siphon_bonus"] = 0.10 * s.level
                elif s.skill_name == "stealth":
                    mods["stealth_bonus"] = 0.10 * s.level
                elif s.skill_name == "fortify":
                    mods["fortify_bonus"] = 0.10 * s.level

            return mods
