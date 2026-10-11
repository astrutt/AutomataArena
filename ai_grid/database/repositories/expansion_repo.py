# expansion_repo.py - v2.0 Grid Expansion logic
import json
import logging
from sqlalchemy import func, insert
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from ai_grid.database.base_repo import BaseRepository
from ai_grid.models import Character, GridNode, Player, NetworkAlias, RaidTarget

logger = logging.getLogger("grid_db")

ALL_REGION_TYPES = [
    "CIV", "SMB", "CRP", "EDU", "GOV", "MED", "MIL", "ORG",
    "LEA", "DTC", "POS", "ICS", "UTL", "ARN", "WAR", "VOD"
]

class ExpansionRepository(BaseRepository):
    """
    Manages the expansion and topology telemetry of the coordinate-based grid.
    Tracks population density, administrative inspection, and perimeter expansion.
    """
    
    async def get_expansion_telemetry(self):
        """Audit the grid for population density and unlock status."""
        async with self.async_session() as session:
            total_stmt = select(func.count(GridNode.id))
            total_count = (await session.execute(total_stmt)).scalar() or 0
            
            unlocked_stmt = select(func.count(GridNode.id)).where(GridNode.is_unlocked == True)
            unlocked_count = (await session.execute(unlocked_stmt)).scalar() or 0
            
            char_count_stmt = select(func.count(Character.id))
            char_count = (await session.execute(char_count_stmt)).scalar() or 0
            
            density = char_count / unlocked_count if unlocked_count > 0 else 0
            
            return {
                "total_nodes": total_count,
                "unlocked_nodes": unlocked_count,
                "player_count": char_count,
                "global_density": round(density, 2),
                "expansion_recommended": density > 1.5
            }

    async def manual_expand_sector(self, cluster_id: int = None):
        """Manually unlock all nodes in a priority cluster."""
        async with self.async_session() as session:
            if cluster_id is None:
                stmt = select(GridNode.cluster_id).where(
                    GridNode.is_unlocked == False,
                    GridNode.cluster_id != None
                ).limit(1)
                cluster_id = (await session.execute(stmt)).scalar()
            
            if cluster_id is None:
                return False, "No locked clusters available for expansion."
            
            update_stmt = select(GridNode).where(GridNode.cluster_id == cluster_id)
            nodes = (await session.execute(update_stmt)).scalars().all()
            for node in nodes:
                node.is_unlocked = True
            
            await session.commit()
            logger.info(f"GRID EXPANSION: Cluster {cluster_id} unlocked manually. ({len(nodes)} nodes)")
            return True, f"Sector Cluster {cluster_id} is now ONLINE. {len(nodes)} new coordinates reachable."

    async def get_grid_stats(self) -> dict:
        """
        Audit comprehensive grid statistics: dimensions (width x height),
        active vs void node counts, and breakdown of all 14+ region types.
        """
        async with self.async_session() as session:
            dim_res = (await session.execute(select(func.max(GridNode.x), func.max(GridNode.y)))).first()
            max_x = dim_res[0] if dim_res and dim_res[0] is not None else -1
            max_y = dim_res[1] if dim_res and dim_res[1] is not None else -1
            width = max_x + 1 if max_x >= 0 else 0
            height = max_y + 1 if max_y >= 0 else 0

            total_count = (await session.execute(select(func.count(GridNode.id)))).scalar() or 0
            
            # Count by region
            region_stmt = select(GridNode.region_type, func.count(GridNode.id)).group_by(GridNode.region_type)
            region_rows = (await session.execute(region_stmt)).all()
            regions = {r: 0 for r in ALL_REGION_TYPES}
            for r_type, count in region_rows:
                key = str(r_type or "VOD").upper()
                regions[key] = count

            void_count = regions.get("VOD", 0)
            active_count = total_count - void_count

            # Count by controller
            ctrl_stmt = select(GridNode.controller, func.count(GridNode.id)).group_by(GridNode.controller)
            ctrl_rows = (await session.execute(ctrl_stmt)).all()
            controllers = {}
            for ctrl, count in ctrl_rows:
                controllers[ctrl or "NONE"] = count

            # Count raid targets
            raid_count = (await session.execute(select(func.count(RaidTarget.id)))).scalar() or 0

            return {
                "width": width,
                "height": height,
                "total_nodes": total_count,
                "active_nodes": active_count,
                "void_nodes": void_count,
                "regions": regions,
                "controllers": controllers,
                "raid_targets_count": raid_count
            }

    async def get_grid_status(self) -> dict:
        """
        Audit overall grid health, power grid load, stability averages,
        total claimed nodes, and active connected network home nodes.
        """
        async with self.async_session() as session:
            # Active nodes durability & stability
            stat_stmt = select(
                func.avg(GridNode.durability),
                func.sum(GridNode.power_stored),
                func.sum(GridNode.power_consumed),
                func.sum(GridNode.power_generated)
            ).where(GridNode.region_type != 'VOD')
            dur_avg, power_stored, power_load, power_gen = (await session.execute(stat_stmt)).first()

            if dur_avg is None:
                # Fallback to all nodes
                stat_all = select(
                    func.avg(GridNode.durability),
                    func.sum(GridNode.power_stored),
                    func.sum(GridNode.power_consumed),
                    func.sum(GridNode.power_generated)
                )
                dur_avg, power_stored, power_load, power_gen = (await session.execute(stat_all)).first()

            claimed_stmt = select(func.count(GridNode.id)).where(GridNode.owner_character_id != None)
            claimed_count = (await session.execute(claimed_stmt)).scalar() or 0

            # Network home nodes (nodes with net_affinity)
            net_stmt = select(GridNode.net_affinity).where(GridNode.net_affinity != None).distinct()
            home_rows = (await session.execute(net_stmt)).scalars().all()
            home_map = {}
            for n in home_rows:
                if n:
                    s = str(n)
                    k = s.lower()
                    if k not in home_map or (s[0].isupper() and not home_map[k][0].isupper()):
                        home_map[k] = s
            home_nodes = sorted(list(home_map.values()))

            return {
                "health": round(float(dur_avg or 100.0), 1),
                "stability": round(float(dur_avg or 100.0), 1),
                "power_stored": round(float(power_stored or 0.0), 1),
                "power_load": round(float(power_load or 0.0), 1),
                "power_generated": round(float(power_gen or 0.0), 1),
                "claimed_nodes": claimed_count,
                "home_nodes": home_nodes
            }

    async def get_node_info(self, loc_or_x, y=None) -> dict:
        """
        Inspect coordinate-specific or node-specific telemetry:
        coordinates, region type, security level, durability, power stored,
        owner, installed hardware, and availability state.
        """
        async with self.async_session() as session:
            stmt = None
            if y is not None:
                try:
                    target_x, target_y = int(loc_or_x), int(y)
                    stmt = select(GridNode).where(GridNode.x == target_x, GridNode.y == target_y)
                except (ValueError, TypeError):
                    stmt = select(GridNode).where(func.lower(GridNode.name) == str(loc_or_x).lower())
            elif isinstance(loc_or_x, (list, tuple)) and len(loc_or_x) == 2:
                try:
                    stmt = select(GridNode).where(GridNode.x == int(loc_or_x[0]), GridNode.y == int(loc_or_x[1]))
                except (ValueError, TypeError):
                    stmt = select(GridNode).where(func.lower(GridNode.name) == str(loc_or_x).lower())
            elif isinstance(loc_or_x, str):
                cleaned = loc_or_x.strip().strip("()[]<>")
                cleaned_delim = cleaned.replace(',', ' ').replace('(', ' ').replace(')', ' ').replace('[', ' ').replace(']', ' ').replace('<', ' ').replace('>', ' ')
                parts = cleaned_delim.split()
                if len(parts) == 2:
                    try:
                        stmt = select(GridNode).where(GridNode.x == int(parts[0]), GridNode.y == int(parts[1]))
                    except (ValueError, TypeError):
                        stmt = select(GridNode).where(
                            (func.lower(GridNode.name) == cleaned.lower()) |
                            (func.lower(GridNode.name) == cleaned.replace(' ', '_').lower())
                        )
                else:
                    stmt = select(GridNode).where(
                        (func.lower(GridNode.name) == cleaned.lower()) |
                        (func.lower(GridNode.name) == cleaned.replace(' ', '_').lower())
                    )
            else:
                stmt = select(GridNode).where(func.lower(GridNode.name) == str(loc_or_x).lower())

            stmt = stmt.options(selectinload(GridNode.owner), selectinload(GridNode.active_target))
            node = (await session.execute(stmt)).scalars().first()
            if not node and isinstance(loc_or_x, str):
                # Fallback: check if target matches a RaidTarget name (e.g. "[SMB] SMB_38_26")
                rt_stmt = select(RaidTarget).where(func.lower(RaidTarget.name) == str(loc_or_x).strip().lower())
                rt = (await session.execute(rt_stmt)).scalars().first()
                if rt and rt.node_id:
                    node = (await session.execute(
                        select(GridNode).where(GridNode.id == rt.node_id).options(selectinload(GridNode.owner), selectinload(GridNode.active_target))
                    )).scalars().first()

            if not node:
                return None

            addons = {}
            try:
                addons = json.loads(node.addons_json or "{}")
            except Exception:
                addons = {}

            owner_name = node.owner.name if node.owner else "Unclaimed"
            return {
                "name": node.name,
                "x": node.x,
                "y": node.y,
                "region_type": node.region_type or "VOD",
                "node_type": node.node_type or "void",
                "upgrade_level": node.upgrade_level or 1,
                "durability": round(float(node.durability or 100.0), 1),
                "power_stored": round(float(node.power_stored or 0.0), 1),
                "owner": owner_name,
                "controller": node.controller,
                "addons": addons,
                "availability_mode": node.availability_mode or "OPEN",
                "net_affinity": node.net_affinity,
                "is_unlocked": node.is_unlocked
            }

    async def expand_grid(self, delta_w: int = 10, delta_h: int = 10) -> tuple:
        """
        Dynamically expands the grid by +delta_w x +delta_h coordinates (e.g. 50x50 -> 60x60)
        with proportionate realistic clustering on the expanded perimeter without corrupting
        or deleting existing nodes, characters, stashes, or hardware.
        """
        if delta_w <= 0 or delta_h <= 0:
            return False, "Expansion dimensions must be positive integers.", {}
        if delta_w > 50 or delta_h > 50:
            return False, "Expansion delta exceeds maximum permitted limit (+50x50 per operation).", {}

        async with self.async_session() as session:
            dim_res = (await session.execute(select(func.max(GridNode.x), func.max(GridNode.y)))).first()
            cur_max_x = dim_res[0] if dim_res and dim_res[0] is not None else 49
            cur_max_y = dim_res[1] if dim_res and dim_res[1] is not None else 49
            old_w = cur_max_x + 1
            old_h = cur_max_y + 1
            new_w = old_w + delta_w
            new_h = old_h + delta_h

            # Identify all existing coordinates to prevent duplicate creation or coordinate gaps
            existing_coords = set(
                (row[0], row[1]) for row in (await session.execute(
                    select(GridNode.x, GridNode.y).where(GridNode.x != None, GridNode.y != None)
                )).all()
            )

            # Identify all new perimeter coordinates in expanded matrix
            new_coords = []
            for gx in range(new_w):
                for gy in range(new_h):
                    if (gx, gy) not in existing_coords:
                        new_coords.append((gx, gy))

            total_added = len(new_coords)
            if total_added == 0:
                return False, "No expansion coordinates calculated.", {}

            # Population targets on perimeter (~28% active, ~72% void)
            target_active = round(total_added * 0.28)
            target_void = total_added - target_active

            # Sub-allocations (57% MCP, 21% NPC, 14% Raid, 7% Claimable)
            mcp_target = round(target_active * (400 / 700))
            npc_target = round(target_active * (150 / 700))
            raid_target = round(target_active * (100 / 700))
            claim_target = target_active - (mcp_target + npc_target + raid_target)

            # Define perimeter cluster anchors extending existing sectors
            # East perimeter: Corporate/Financial extension
            # North perimeter: Defense extension
            # West perimeter: Infrastructure extension
            # South perimeter: Civic/Conflict extension
            perimeter_anchors = [
                {"name": "Corporate_Perimeter", "center": (new_w - 5, old_h // 2), "types": ["CRP", "DTC", "POS"]},
                {"name": "Defense_Perimeter", "center": (old_w // 2, new_h - 5), "types": ["GOV", "LEA", "MIL"]},
                {"name": "Infra_Perimeter", "center": (5, new_h - 5), "types": ["ICS", "UTL"]},
                {"name": "Civic_Conflict_Perimeter", "center": (new_w - 5, 5), "types": ["CIV", "SMB", "EDU", "ORG", "MED", "WAR", "ARN"]},
            ]

            # Score new coordinates by distance to closest perimeter anchor
            coord_scores = []
            for gx, gy in new_coords:
                min_d = 99999
                best_anchor = perimeter_anchors[0]
                for anc in perimeter_anchors:
                    ax, ay = anc["center"]
                    d = abs(gx - ax) + abs(gy - ay)
                    if d < min_d:
                        min_d = d
                        best_anchor = anc
                coord_scores.append((min_d, gx, gy, best_anchor))

            # Sort coordinates so closest to perimeter anchors become active
            coord_scores.sort(key=lambda item: item[0])

            active_coords_data = coord_scores[:target_active]
            void_coords_data = coord_scores[target_active:]

            # Categorize active assignments
            categories = (
                ["CLAIMABLE"] * claim_target +
                ["RAID"] * raid_target +
                ["NPC"] * npc_target +
                ["MCP"] * mcp_target
            )

            cur_max_node_id = (await session.execute(select(func.max(GridNode.id)))).scalar() or 0
            cur_max_rt_id = (await session.execute(select(func.max(RaidTarget.id)))).scalar() or 0
            node_counter = cur_max_node_id + 1
            rt_counter = cur_max_rt_id + 1

            new_node_dicts = []
            new_raid_dicts = []

            for i, (_, gx, gy, anchor) in enumerate(active_coords_data):
                role = categories[i] if i < len(categories) else "MCP"
                available_types = anchor["types"]
                
                # Topological grouping within anchor
                if anchor["name"] == "Infra_Perimeter":
                    r_type = "ICS" if gx % 2 == 0 else "UTL"
                elif anchor["name"] == "Corporate_Perimeter":
                    r_type = available_types[(gx + gy) % len(available_types)]
                elif anchor["name"] == "Defense_Perimeter":
                    r_type = available_types[(gx + gy) % len(available_types)]
                else:
                    r_type = available_types[(gx * 3 + gy) % len(available_types)]

                # Operational type mapping
                if r_type == "ARN":
                    n_type = "arena"
                elif role == "NPC" or r_type in ["SMB", "POS"]:
                    n_type = "merchant"
                elif r_type in ["CIV", "MED", "ORG"]:
                    n_type = "safezone"
                else:
                    n_type = "void"

                avail_mode = "OPEN" if role in ["CLAIMABLE", "NPC"] else "CLOSED"
                lvl = 1 + (gx + gy) % 4
                current_node_id = node_counter
                node_counter += 1
                
                at_id = None
                if role == "RAID":
                    at_id = rt_counter
                    rt_counter += 1
                    new_raid_dicts.append({
                        "id": at_id,
                        "node_id": current_node_id,
                        "name": f"[{r_type}] {r_type}_{gx}_{gy}",
                        "target_type": r_type,
                        "difficulty": 10 + (lvl * 5),
                        "credits_pool": 500.0 * lvl,
                        "data_pool": 50.0 * lvl,
                        "is_active": True,
                        "availability_mode": "CLOSED"
                    })

                new_node_dicts.append({
                    "id": current_node_id,
                    "name": f"{r_type}_{gx}_{gy}",
                    "description": f"Perimeter sector at ({gx}, {gy}) in {anchor['name']}.",
                    "x": gx,
                    "y": gy,
                    "node_type": n_type,
                    "region_type": r_type,
                    "controller": role,
                    "upgrade_level": lvl,
                    "durability": 100.0,
                    "power_stored": 100.0 * lvl,
                    "availability_mode": avail_mode,
                    "is_unlocked": False,
                    "active_target_id": at_id,
                    "addons_json": "{}"
                })

            # Generate remaining void nodes
            for _, gx, gy, _ in void_coords_data:
                current_node_id = node_counter
                node_counter += 1
                new_node_dicts.append({
                    "id": current_node_id,
                    "name": f"Sector_{gx}_{gy}",
                    "description": f"Unrouted wasteland sector at ({gx}, {gy}).",
                    "x": gx,
                    "y": gy,
                    "node_type": "void",
                    "region_type": "VOD",
                    "controller": None,
                    "upgrade_level": 1,
                    "durability": 100.0,
                    "power_stored": 0.0,
                    "availability_mode": "CLOSED",
                    "is_unlocked": False,
                    "active_target_id": None,
                    "addons_json": "{}"
                })

            await session.execute(insert(GridNode), new_node_dicts)
            if new_raid_dicts:
                await session.execute(insert(RaidTarget), new_raid_dicts)
            await session.commit()
            logger.info(f"Grid expanded: {old_w}x{old_h} -> {new_w}x{new_h} (+{total_added} nodes, {target_active} active).")
            
            feedback = f"Grid expanded from {old_w}x{old_h} to {new_w}x{new_h} (+{total_added:,} coordinates added). Perimeter successfully synchronized."
            return True, feedback, {
                "old_dimensions": (old_w, old_h),
                "new_dimensions": (new_w, new_h),
                "total_added": total_added,
                "active_added": target_active,
                "void_added": target_void
            }

    async def ensure_network_home_node(self, network_name: str) -> GridNode:
        """
        Dynamically spawns or ensures a dedicated home node for the given IRC network.
        Configured as an entry point with OPEN state, level 1, net_affinity set to network_name,
        and an active NET device installed so cross-network traffic and bridging work immediately.
        """
        if not network_name or not str(network_name).strip():
            return None
        network_name = str(network_name).strip()

        async with self.async_session() as session:
            # Check by name or net_affinity (case-insensitive)
            stmt = select(GridNode).where(
                func.lower(GridNode.name) == network_name.lower()
            )
            node = (await session.execute(stmt)).scalars().first()
            if not node:
                stmt_aff = select(GridNode).where(
                    func.lower(GridNode.net_affinity) == network_name.lower()
                )
                node = (await session.execute(stmt_aff)).scalars().first()

            if not node:
                # Find an unallocated void sector named Sector_x_y without net_affinity, active target, or owner,
                # explicitly protecting fixed hubs, nodes with player stashes, and sectors occupied by characters
                void_stmt = select(GridNode).options(
                    selectinload(GridNode.characters_present)
                ).where(
                    GridNode.region_type == 'VOD',
                    GridNode.net_affinity == None,
                    GridNode.owner_character_id == None,
                    GridNode.active_target_id == None,
                    GridNode.name.not_in(["Edge_West", "Edge_East", "UpLink", "Arena", "Vault"])
                ).order_by(GridNode.id.desc())
                candidate_voids = (await session.execute(void_stmt)).scalars().all()
                target_void = None
                for cv in candidate_voids:
                    if cv.characters_present and len(cv.characters_present) > 0:
                        continue
                    stash = []
                    try:
                        if cv.stash_inventory:
                            stash = cv.stash_inventory if isinstance(cv.stash_inventory, list) else json.loads(cv.stash_inventory)
                    except Exception:
                        pass
                    if not stash:
                        target_void = cv
                        break

                if target_void:
                    node = target_void
                    node.name = network_name
                    node.description = f"Entry point for the {network_name} local mesh."
                    node.region_type = "DTC"
                    node.node_type = "void"
                else:
                    bounds = (await session.execute(select(func.max(GridNode.x), func.max(GridNode.y)))).first()
                    cur_max_x = bounds[0] if bounds and bounds[0] is not None else -1
                    cur_max_y = bounds[1] if bounds and bounds[1] is not None else -1
                    
                    # Search for any unallocated coordinates in existing grid bounding box
                    existing_coords = set(
                        (row[0], row[1]) for row in (await session.execute(
                            select(GridNode.x, GridNode.y).where(GridNode.x != None, GridNode.y != None)
                        )).all()
                    )
                    nx, ny = None, None
                    if cur_max_x >= 0 and cur_max_y >= 0:
                        for gx in range(cur_max_x + 1):
                            for gy in range(cur_max_y + 1):
                                if (gx, gy) not in existing_coords:
                                    nx, ny = gx, gy
                                    break
                            if nx is not None:
                                break
                    if nx is None:
                        nx = cur_max_x + 1 if cur_max_x >= 0 else 0
                        ny = 0

                    node = GridNode(
                        name=network_name,
                        description=f"Entry point for the {network_name} local mesh.",
                        x=nx,
                        y=ny,
                        node_type="void",
                        region_type="DTC"
                    )
                    session.add(node)
                    await session.flush()

            # Enforce standard entry point parameters
            node.availability_mode = 'OPEN'
            node.upgrade_level = max(1, node.upgrade_level or 1)
            node.controller = "MCP"
            node.power_stored = max(100.0, float(node.power_stored or 0.0))
            if not node.net_affinity or (node.net_affinity.islower() and not network_name.islower()):
                node.net_affinity = network_name
            if node.name.islower() and not network_name.islower():
                node.name = network_name
            node.is_unlocked = True
            
            addons = {}
            try:
                addons = json.loads(node.addons_json or "{}")
            except Exception:
                addons = {}
            addons["NET"] = True
            node.addons_json = json.dumps(addons)

            await session.commit()
            logger.info(f"Dynamic IRC Network Home Node ensured: {network_name} (Node: {node.name})")
            return node
