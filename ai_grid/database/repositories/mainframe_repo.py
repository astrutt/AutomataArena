# mainframe_repo.py - v1.5.0
import datetime
import random
import json
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from models import Character, Player, NetworkAlias, MainframeTask, GridNode, InventoryItem, ItemTemplate
from ..core import logger, CONFIG

class MainframeRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def get_gibson_status(self, name: str, network: str) -> dict:
        """Get status of active tasks and available resources."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.inventory).selectinload(InventoryItem.template))
            char = (await session.execute(stmt)).scalars().first()
            if not char: return {"error": "Character not found."}

            tasks_stmt = select(MainframeTask).where(MainframeTask.character_id == char.id, MainframeTask.is_collected == False)
            tasks = (await session.execute(tasks_stmt)).scalars().all()

            vulns = sum(1 for i in char.inventory if i.template.name == "Vulnerability")
            zero_days = sum(1 for i in char.inventory if i.template.name == "ZeroDay_Chain")

            active_tasks = []
            now = datetime.datetime.now(datetime.timezone.utc)
            node = char.current_node
            
            for t in tasks:
                remaining = (t.completion_time - now).total_seconds()
                active_tasks.append({
                    "type": t.task_type,
                    "remaining_sec": max(0, int(remaining)),
                    "amount": t.amount
                })

            # Calculate Global Harvest (All owned nodes)
            power_stmt = select(func.sum(GridNode.power_generated)).where(GridNode.owner_character_id == char.id)
            harvest = (await session.execute(power_stmt)).scalar() or 0.0

            is_owner = node.owner_character_id == char.id
            
            return {
                "active_tasks": active_tasks,
                "data": char.data_units,
                "vulns": vulns,
                "zero_days": zero_days,
                "user_power": char.power,
                "is_owner": is_owner
            }

    async def start_compilation(self, name: str, network: str, data_amount: int) -> dict:
        """Start a compilation task: 100 Data -> 1 Vuln."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"error": "System offline."}

            # Constraint: Must be on an owned node
            if char.current_node.owner_character_id != char.id:
                return {"error": "ACCESS DENIED. You must be at a Grid Node you command to access The Gibson."}

            if char.data_units < data_amount:
                return {"error": f"Insufficient Data Units. Required: {data_amount} | Available: {char.data_units:.1f}"}

            cost_cfg = CONFIG.get('mechanics', {}).get('action_costs', {}).get('compile', 10.0)
            target_yield = data_amount // 100
            if target_yield < 1: return {"error": "Minimum compilation requires 100 Data Units."}

            # Node Power First Logic
            node = char.current_node
            total_cost = cost_cfg * target_yield
            node_contribution = min(node.power_stored, total_cost)
            node.power_stored -= node_contribution
            remaining_cost = total_cost - node_contribution

            if remaining_cost > 0:
                if char.power < remaining_cost:
                    return {"error": f"Insufficient Power. Node contributed {node_contribution:.1f} uP, but {remaining_cost:.1f} more is needed from Character reserves."}
                char.power -= remaining_cost

            char.data_units -= data_amount
            
            # Duration: base 10m per vuln, reduced by global harvest rate?
            # For now, stick to fixed duration 10m
            base_duration = CONFIG.get('mechanics', {}).get('mainframe', {}).get('compilation_time_minutes', 10)
            completion = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=base_duration * target_yield)

            task = MainframeTask(
                character_id=char.id,
                task_type="COMPILE",
                amount=target_yield,
                completion_time=completion
            )
            session.add(task)
            await session.commit()

            return {
                "success": True,
                "msg": f"Compilation Initiated. {target_yield}x Vulnerabilities will be ready in {base_duration * target_yield} minutes.",
                "node_used": node_contribution,
                "char_used": remaining_cost
            }

    async def start_assembly(self, name: str, network: str) -> dict:
        """Start an assembly task: 4 Vulns -> 1 Zero-Day."""
        async with self.async_session() as session:
            stmt = select(Character).join(Player).join(NetworkAlias).where(
                Character.name == name,
                NetworkAlias.nickname == name,
                NetworkAlias.network_name == network
            ).options(selectinload(Character.inventory).selectinload(InventoryItem.template), selectinload(Character.current_node))
            char = (await session.execute(stmt)).scalars().first()
            if not char or not char.current_node: return {"error": "System offline."}

            if char.current_node.owner_character_id != char.id:
                return {"error": "ACCESS DENIED. You must be at a Grid Node you command to access The Gibson."}

            vuln_items = [i for i in char.inventory if i.template.name == "Vulnerability"]
            if len(vuln_items) < 4:
                return {"error": f"Insufficient Vulnerabilities. Required: 4 | Available: {len(vuln_items)}"}

            cost_cfg = CONFIG.get('mechanics', {}).get('action_costs', {}).get('assemble', 25.0)
            
            # Node Power First
            node = char.current_node
            node_contribution = min(node.power_stored, cost_cfg)
            node.power_stored -= node_contribution
            remaining_cost = cost_cfg - node_contribution

            if remaining_cost > 0:
                if char.power < remaining_cost:
                    return {"error": f"Insufficient Power. Node contributed {node_contribution:.1f} uP, but {remaining_cost:.1f} more is needed."}
                char.power -= remaining_cost

            # Consume items
            for i in vuln_items[:4]:
                await session.delete(i)

            base_duration = CONFIG.get('mechanics', {}).get('mainframe', {}).get('assembly_time_minutes', 60)
            completion = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=base_duration)

            task = MainframeTask(
                character_id=char.id,
                task_type="ASSEMBLE",
                amount=1,
                completion_time=completion
            )
            session.add(task)
            await session.commit()

            return {
                "success": True,
                "msg": f"Assembly Started. Zero-Day Chain will be compiled in {base_duration} minutes.",
                "node_used": node_contribution,
                "char_used": remaining_cost
            }

    async def tick_mainframe_tasks(self) -> list:
        """Process completed tasks. Returns a list of (nick, network, msg) for notifications."""
        notifications = []
        async with self.async_session() as session:
            now = datetime.datetime.now(datetime.timezone.utc)
            stmt = select(MainframeTask).where(MainframeTask.completion_time <= now, MainframeTask.is_collected == False).options(selectinload(MainframeTask.owner).selectinload(Character.player).selectinload(Player.aliases))
            tasks = (await session.execute(stmt)).scalars().all()

            if not tasks: return []

            for t in tasks:
                char = t.owner
                # Find the primary alias for the character
                alias = next((a for a in char.player.aliases if a.nickname == char.name), None)
                if not alias: continue

                # Award item
                result = await self._award_mainframe_reward(session, char, t.task_type, t.amount)
                if result:
                    t.is_collected = True
                    notifications.append({
                        "nickname": alias.nickname,
                        "network": alias.network_name,
                        "msg": f"SYSTEM: {t.task_type} Task Complete. Output: {t.amount}x {result} added to local buffers."
                    })
            
            await session.commit()
        return notifications

    async def _award_mainframe_reward(self, session, char, task_type, amount):
        template_name = "Vulnerability" if task_type == "COMPILE" else "ZeroDay_Chain"
        tmpl_stmt = select(ItemTemplate).where(ItemTemplate.name == template_name)
        template = (await session.execute(tmpl_stmt)).scalars().first()
        
        if not template:
            # Fallback/Auto-seed if missing
            template = ItemTemplate(
                name=template_name,
                item_type="hack",
                base_value=500 if task_type == "COMPILE" else 2500,
                effects_json=json.dumps({"alg_boost": 5 if task_type == "COMPILE" else 15})
            )
            session.add(template)
            await session.flush()

        # Stacking Logic (Task 038)
        exist_stmt = select(InventoryItem).where(InventoryItem.character_id == char.id, InventoryItem.template_id == template.id)
        existing = (await session.execute(exist_stmt)).scalars().first()
        
        if existing:
            existing.quantity += amount
        else:
            new_item = InventoryItem(character_id=char.id, template_id=template.id, quantity=amount)
            session.add(new_item)
        return template_name
