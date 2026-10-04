# database/repositories/spectator_repo.py
import datetime
import random
import json
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from ai_grid.models import Character, Player, NetworkAlias, GridNode, ItemTemplate, InventoryItem, PulseEvent
from datetime import timedelta, timezone
from ai_grid.database.core import logger

class SpectatorRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def rename_rank(self, nick: str, network: str, new_title: str) -> tuple:
        """Allows a spectator to customize their Rank Title for a fee."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == nick.lower(),
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char or char.race != "Spectator":
                return False, "Only Spectators can customize Rank Titles."
            
            cost = 5000.0
            if char.credits < cost:
                return False, f"Insufficient credits. Renaming Rank costs {cost}c."
            
            char.credits -= cost
            char.rank_title = new_title
            await session.commit()
            return True, f"Rank Title updated to: {new_title}. (-{cost}c)"

    async def award_daily_dividend(self, nick: str, network: str) -> tuple:
        """Awards the automated daily dividend based on UTC rollover (v1.8.0)."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == nick.lower(),
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return False, "Orbital link failed."

            bonus_creds = 250.0 + (char.level * 25)
            bonus_xp = 50 + (char.level * 5)
            
            char.credits += bonus_creds
            char.xp += bonus_xp
            char.last_daily_bonus_at = datetime.datetime.now(datetime.timezone.utc)
            
            await session.commit()
            return True, f"Daily Dividend processed: +{bonus_creds}c, +{bonus_xp} XP."

    DEFAULT_DROP_ITEMS = {
        "nano_patch": {"name": "Nano_Patch", "cost": 2500.0, "type": "consumable", "aliases": {"nano_patch", "nanopatch", "patch", "heal", "hp", "nano"}, "effect": "heal", "val": 50},
        "battery": {"name": "Battery", "cost": 2500.0, "type": "consumable", "aliases": {"battery", "batt", "power", "cell", "up", "energy"}, "effect": "power", "val": 50},
        "zeroday_chain": {"name": "ZeroDay_Chain", "cost": 7500.0, "type": "hack", "aliases": {"zeroday_chain", "zeroday", "0day", "chain", "exploit", "zerodaychain"}, "effect": "exploit", "val": 15},
    }

    async def spectator_drop(self, nick: str, network: str, target: str = None, item_name: str = None) -> tuple:
        """High-cost interaction to drop items in the Arena."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == nick.lower(),
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return False, "Orbital link failed."

            matched_info = None
            if item_name:
                norm = item_name.lower().replace("-", "_").replace(" ", "_")
                for k, info in self.DEFAULT_DROP_ITEMS.items():
                    if norm == k or norm == info["name"].lower() or norm in info["aliases"]:
                        matched_info = info
                        break

            if matched_info:
                cost = matched_info["cost"]
                chosen_name = matched_info["name"]
                item_type = matched_info["type"]
            elif item_name:
                cost = 2500.0
                chosen_name = item_name
                item_type = "consumable"
            else:
                cost = 2500.0
                candidates = ["Data_Shard", "Memory_Fragment", "Corrupted_Bit"]
                chosen_name = random.choice(candidates)
                item_type = "junk"

            if char.credits < cost:
                return False, f"Insufficient budget. Support drops cost {cost}c."

            stmt_item = select(ItemTemplate).where(func.lower(ItemTemplate.name) == chosen_name.lower())
            tpl = (await session.execute(stmt_item)).scalars().first()
            if not tpl:
                tpl = ItemTemplate(name=chosen_name, item_type=item_type, base_value=int(cost))
                session.add(tpl)
                await session.flush()

            char.credits -= cost

            if target:
                # Targeted Drop (Direct to inventory if nearby/online?)
                # Simplified: Targeted drop always succeeds if player exists
                stmt_target = select(Character).join(Player).join(NetworkAlias).where(
                    func.lower(Character.name) == target.lower(),
                    NetworkAlias.network_name == network
                ).options(selectinload(Character.inventory))
                target_char = (await session.execute(stmt_target)).scalars().first()

                if not target_char:
                    return False, f"Target '{target}' not found in local sector."

                existing = next((i for i in target_char.inventory if i.template_id == tpl.id), None)
                if existing: existing.quantity += 1
                else:
                    new_item = InventoryItem(character_id=target_char.id, template_id=tpl.id, quantity=1)
                    session.add(new_item)

                await session.commit()
                return True, f"Orbital Drop successful! {tpl.name} delivered to {target_char.name}."
            else:
                # Public Drop (Spawns in Arena)
                arena = (await session.execute(select(GridNode).where(GridNode.node_type == 'arena'))).scalars().first()
                if not arena: return False, "Arena node logic failure."

                # Manifest a high-value Pulse Event in the Arena
                duration_mins = 10
                expiry = datetime.datetime.now(datetime.timezone.utc) + timedelta(minutes=duration_mins)

                pulse = PulseEvent(
                    node_id=arena.id,
                    network_name=network,
                    event_type="PACKET",
                    reward_val=500.0, # High value spectator drop
                    expires_at=expiry,
                    status='ACTIVE'
                )
                session.add(pulse)
                await session.commit()
                return True, f"Public Drop Initiated! A high-value signal package ({tpl.name} equivalent energy) has been launched toward the Arena."

    async def trickle_power(self, network: str):
        """Background task: contribute power to the grid based on spectator presence."""
        async with self.async_session() as session:
            # Find all spectators on this network
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.race == "Spectator",
                NetworkAlias.network_name == network
            )
            spectators = (await session.execute(stmt)).scalars().all()
            
            if not spectators: return
            
            # Simple math: 0.1 power per rank per spectator
            total_trickle = sum(s.level * 0.1 for s in spectators)
            
            # Apply to the global pool (UpLink node for now)
            uplink = (await session.execute(select(GridNode).where(GridNode.name == "UpLink"))).scalars().first()
            if uplink:
                uplink.power_stored += total_trickle
                await session.commit()
                logger.debug(f"Spectator Power Trickle: +{total_trickle:.2f} uP injected from {len(spectators)} observers.")

    async def update_rank_title(self, nick: str, network: str, llm_client) -> str:
        """Automated title generation using LLM (v1.8.0)."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == nick.lower(),
                NetworkAlias.network_name == network
            )
            char = (await session.execute(stmt)).scalars().first()
            if not char: return "Unranked"
            
            new_title = await llm_client.generate_rank_title(char.name, char.level)
            char.rank_title = new_title
            await session.commit()
            return new_title
