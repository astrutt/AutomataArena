# combat_repo.py
import random
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from models import Character, Player, NetworkAlias, GridNode, InventoryItem, ItemTemplate
from ..core import logger, MOB_ROSTER, LOOT_TABLE, CONFIG, increment_daily_task
from grid_utils import calculate_elo_change

class CombatRepository:
    def __init__(self, async_session):
        self.async_session = async_session
        self.MOB_ROSTER = MOB_ROSTER

    async def _eject_character(self, session, char):
        """Relocates a character to the Grid Nexus (Spawn)."""
        uplink = (await session.execute(
            select(GridNode).where(GridNode.is_spawn_node == True)
        )).scalars().first()
        if uplink:
            char.node_id = uplink.id
            char.current_hp = char.ram * 5
            return True
        return False

    async def record_match_result(self, winner_name: str, loser_name: str, network: str):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name.in_([winner_name, loser_name]),
                NetworkAlias.network_name == network
            )
            result = await session.execute(stmt)
            chars = result.scalars().all()
            
            winner, loser = None, None
            for c in chars:
                if c.name == winner_name: winner = c
                if c.name == loser_name: loser = c
            
            if winner and loser:
                delta = calculate_elo_change(winner.elo, loser.elo)
                winner.wins += 1
                winner.elo += delta
                winner.xp += 50
                winner.credits += 100
                
                loser.losses += 1
                loser.elo = max(0, loser.elo - delta)
                loser.xp += 10
                
                while True:
                    xp_threshold = winner.level * 1000
                    if winner.xp >= xp_threshold:
                        winner.xp -= xp_threshold
                        winner.level += 1
                        winner.cpu += 1
                        winner.pending_stat_points += 1
                    else:
                        break
            
            await session.commit()

    async def resolve_mob_encounter(self, name: str, network: str, threat_level: int) -> dict:
        mob = MOB_ROSTER.get(threat_level, MOB_ROSTER[1])

        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                func.lower(Character.name) == name.lower(),
                func.lower(NetworkAlias.nickname) == name.lower(),
                NetworkAlias.network_name == network
            ).options(selectinload(Character.inventory).selectinload(InventoryItem.template))
            char = (await session.execute(stmt)).scalars().first()
            if not char:
                return {"error": "Character not found"}

            player_roll = random.randint(1, 20) + char.alg
            mob_dc = 10 + threat_level * 2
            won = player_roll >= mob_dc

            result = {
                "mob_name":    mob["name"],
                "threat":      threat_level,
                "roll":        player_roll,
                "dc":          mob_dc,
                "won":         won,
                "xp_gained":   0,
                "credits_gained": 0,
                "credits_lost":   0,
                "loot":        None,
                "respawned":   False,
            }

            if won:
                char.xp += mob["xp"]
                char.credits += mob["credits"]
                result["xp_gained"] = mob["xp"]
                result["credits_gained"] = mob["credits"]

                while True:
                    xp_threshold = char.level * 1000
                    if char.xp >= xp_threshold:
                        char.xp -= xp_threshold
                        char.level += 1
                        char.alg += 1
                        char.pending_stat_points += 1
                        result["leveled_up"] = True
                    else:
                        break

                if random.random() < 0.20:
                    loot_name = random.choice(LOOT_TABLE)
                    tpl = (await session.execute(
                        select(ItemTemplate).where(ItemTemplate.name == loot_name)
                    )).scalars().first()
                    if tpl:
                        existing = next(
                            (i for i in char.inventory if i.template_id == tpl.id), None
                        )
                        if existing:
                            existing.quantity += 1
                        else:
                            session.add(InventoryItem(character_id=char.id, template_id=tpl.id))
                        result["loot"] = loot_name

                # Post-combat processing
                reward_msg = await increment_daily_task(session, char, "Kill a Grid Bug")
                result["task_reward"] = reward_msg

            else:
                penalty = char.credits * 0.10
                char.credits = max(0.0, char.credits - penalty)
                result["credits_lost"] = round(penalty, 2)

                # Unified Ejection Logic
                result["respawned"] = await self._eject_character(session, char)

            await session.commit()
            return result

    async def grid_attack(self, attacker_name, target_name, network):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name.in_([attacker_name, target_name]),
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.inventory)
            )
            result = (await session.execute(stmt)).scalars().all()
            
            attacker, target = None, None
            for c in result:
                if c.name.lower() == attacker_name.lower(): attacker = c
                if c.name.lower() == target_name.lower(): target = c
                
            if not attacker or not target: return False, "Target not found on this network."
            if attacker.node_id != target.node_id: return False, "You must be in the same Network Node as your target."
            if not target.current_node or target.current_node.node_type == "safezone": return False, "Combat is strictly prohibited in this zone."
            if attacker.id == target.id: return False, "Self-termination is illogical."
            
            # Phase 2: Power Consumption
            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('attack', 2.0)
            if attacker.power < cost:
                return False, f"Insufficient POWER. Need {cost:.1f} uP."
            attacker.power -= cost
            
            evade_roll = random.randint(1, 100)
            if evade_roll <= (target.bnd * 2):
                return True, f"{attacker.name} swung wildly at {target.name}, but they evaded!"
                
            raw_dmg = attacker.cpu * 3
            final_dmg = max(1, raw_dmg - target.sec)
            if random.randint(1, 100) <= attacker.alg: final_dmg *= 2 
            
            target.current_hp -= final_dmg
            target.stability = max(0.0, target.stability - (final_dmg * 0.5)) # Structural damage
            if target.current_hp <= 0:
                looted = target.credits * 0.10
                target.credits -= looted
                attacker.credits += looted
                
                # Unified Ejection Logic
                await self._eject_character(session, target)
                
                await session.commit()
                return True, f"{attacker.name} struck {target.name} for {final_dmg} DMG! {target.name} flatlines... Ejected to Spawn.", None
                
            await session.commit()
            return True, f"{attacker.name} struck {target.name} for {final_dmg} DMG! ({target.current_hp}/{target.ram*5} HP)", None

    async def grid_hack(self, attacker_name, target_name, network):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name.in_([attacker_name, target_name]),
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            result = (await session.execute(stmt)).scalars().all()
            
            attacker, target = None, None
            for c in result:
                if c.name.lower() == attacker_name.lower(): attacker = c
                if c.name.lower() == target_name.lower(): target = c
                
            if not attacker or not target: return False, "Target not found."
            if attacker.node_id != target.node_id: return False, "Target is not in your current sector."
            if target.current_node and target.current_node.node_type == "safezone": return False, "MCP prevents hacking in safezones."
            if attacker.id == target.id: return "..."
            
            # Phase 2: Power Consumption
            cost = CONFIG.get('mechanics', {}).get('action_costs', {}).get('hack', 3.0)
            if attacker.power < cost:
                return False, f"MCP trace active. You need {cost:.1f} power to safely breach."
            attacker.power -= cost
            
            roll = random.randint(1, 20) + attacker.alg
            dc = 10 + target.sec
            if roll >= dc:
                looted = target.credits * 0.05
                target.credits -= looted
                attacker.credits += looted
                reward_msg = await increment_daily_task(session, attacker, "Hack a Player")
                await session.commit()
                msg = f"Hack Successful! {attacker.name} breached {target.name}'s firewall and siphoned {looted:.2f}c."
                return True, msg, reward_msg
            else:
                attacker.credits = max(0.0, attacker.credits - 50.0)
                await session.commit()
                return False, f"Hack Failed. {target.name}'s MCP traced the intrusion. {attacker.name} is fined 50c!", None

    async def grid_rob(self, attacker_name, target_name, network):
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name.in_([attacker_name, target_name]),
                NetworkAlias.network_name == network
            ).options(
                selectinload(Character.current_node),
                selectinload(Character.inventory)
            )
            result = (await session.execute(stmt)).scalars().all()
            
            attacker, target = None, None
            for c in result:
                if c.name.lower() == attacker_name.lower(): attacker = c
                if c.name.lower() == target_name.lower(): target = c
                
            if not attacker or not target: return False, "Target not found."
            if attacker.node_id != target.node_id: return False, "Target is not in your locale."
            if target.current_node and target.current_node.node_type == "safezone": return False, "No physical theft allowed here."
            if attacker.id == target.id: return False, "..."
            if not target.inventory: return False, f"{target.name}'s pockets are empty."
            
            roll = random.randint(1, 20) + attacker.bnd
            dc = 10 + target.bnd
            if roll >= dc:
                item_to_steal = random.choice(target.inventory)
                item_to_steal.character_id = attacker.id
                await session.commit()
                return True, f"Sleight of hand successful! {attacker.name} lifted an item.", None
            else:
                return False, f"{attacker.name} clumsily attempted to rob {target.name} and was caught!", None

