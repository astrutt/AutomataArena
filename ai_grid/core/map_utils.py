# map_utils.py - v1.5.0 Stable
import datetime
import random
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from models import Character, GridNode, NodeConnection
from grid_utils import C_CYAN, C_GREEN, C_RED, C_YELLOW, C_WHITE, C_GREY, format_text

def get_node_symbol(node: GridNode, char: Character, machine_mode: bool = False, intel_level: str = "NONE") -> str:
    """Determine the symbol and color for a node based on state and intelligence tiers."""
    
    # 1. Fog of War / Intel Tiers
    # Current node is always visible
    if node.id == char.node_id:
        pass # Fall through to base symbol logic
    
    # Tiered Intelligence for CLOSED sectors
    elif node.availability_mode == 'CLOSED' and node.owner_character_id != char.id:
        total_stat = (char.sec or 0) + (char.alg or 0)
        if total_stat >= 60:
            # Tier 4: Full Node Name (Truncated to 5 chars for grid)
            name_trunc = node.name[:5]
            return format_text(f"[{name_trunc}]", C_GREY)
        elif total_stat >= 40:
            # Tier 3: Category & Threat
            cat = node.node_type[0].upper()
            threat = node.threat_level if hasattr(node, 'threat_level') else 0
            return format_text(f"[{cat}:{threat}]", C_GREY)
        elif total_stat >= 20:
            # Tier 2: Generic Category
            cat = node.node_type[0].upper()
            return format_text(f"[{cat}]", C_GREY)
        
        # Tier 1: Minimalist - CLOSED but known location
        return format_text("[X]", C_RED)

    # Fog of War for unknown OPEN sectors
    elif intel_level == "NONE":
        return format_text("[?]", C_GREY)

    # 1.5 Unknown Node check (Hypothetical - for now use [?])
    # if not node.is_discovered: return format_text("[?]", C_GREY)

    # 2. Base Symbol Logic (Visited/Open)
    color = C_WHITE
    if machine_mode:
        symbol_map = {
            'safezone': '[S]',
            'arena': '[A]',
            'merchant': '[$]',
            'wilderness': '[.]'
        }
        symbol = symbol_map.get(node.node_type, '[-]')
        if node.id == char.node_id: symbol = '[@]'; color = C_CYAN
        elif node.owner_character_id == char.id: color = C_GREEN
    else:
        symbol = "[-]"
        if node.id == char.node_id:
            symbol = "[@]"
            color = C_CYAN
        elif node.owner_character_id == char.id:
            color = C_GREEN
            if node.durability < 50: symbol = "[🩹]"
            elif node.power_generated > 20: symbol = "[⚡]"
            else: symbol = "[O]"
        elif node.node_type == 'safezone':
            symbol = "[🛡️]"
            color = C_YELLOW
        elif node.node_type == 'arena':
            symbol = "[🏟️]"
            color = C_RED
        elif node.node_type == 'merchant':
            symbol = "[💰]"
            color = C_YELLOW
        elif node.node_type == 'wilderness':
            symbol = "[-]"
            if node.threat_level > 2: color = C_RED

    return format_text(symbol, color)

def get_connector_symbol(source: GridNode, target: GridNode, vertical: bool = False) -> str:
    """Return a 1-2 character connector symbol based on connection health/status."""
    # Logic: Hazard (Threat > 2) > Damaged (Durability < 70) > Closed > Normal
    
    is_closed = source.availability_mode == 'CLOSED' or target.availability_mode == 'CLOSED'
    is_damaged = source.durability < 70 or target.durability < 70
    is_hazard = (hasattr(source, 'threat_level') and source.threat_level > 2) or \
                (hasattr(target, 'threat_level') and target.threat_level > 2)
    
    if vertical:
        if is_hazard: return "S"
        if is_damaged: return "!"
        if is_closed: return "X"
        return "|"
    else:
        # Horizontal - 2 chars wide exactly
        if is_hazard: return "~~"
        if is_damaged: return "!!"
        if is_closed: return "##"
        return "--"

async def generate_ascii_map(session, char: Character, machine_mode: bool = False, limit_radius: int = None, show_legend: bool = True) -> str:
    """Generate a grid representation using global coordinates and tiered intelligence."""
    
    # 1. Calculate Radius
    if limit_radius is not None:
        radius = limit_radius
    else:
        total_stat = (char.sec or 0) + (char.alg or 0)
        if total_stat >= 60: radius = 3
        elif total_stat >= 40: radius = 2
        else: radius = 1
    
    # 2. Determine Bounding Box
    center_x, center_y = char.current_node.x, char.current_node.y
    min_x, max_x = center_x - radius, center_x + radius
    min_y, max_y = center_y - radius, center_y + radius
    
    # Boundary Clamping (0-49)
    min_x, max_x = max(0, min_x), min(49, max_x)
    min_y, max_y = max(0, min_y), min(49, max_y)

    # 3. Fetch Nodes in Box
    stmt = select(GridNode).where(
        GridNode.x >= min_x, GridNode.x <= max_x,
        GridNode.y >= min_y, GridNode.y <= max_y
    )
    nodes = (await session.execute(stmt)).scalars().all()
    grid = {(n.x, n.y): n for n in nodes}

    # 4. Fetch Discovery Records for these nodes
    from models import DiscoveryRecord
    node_ids = [n.id for n in nodes]
    disc_stmt = select(DiscoveryRecord).where(
        DiscoveryRecord.character_id == char.id,
        DiscoveryRecord.node_id.in_(node_ids)
    )
    disc_recs = {d.node_id: d.intel_level for d in (await session.execute(disc_stmt)).scalars().all()}
    
    if not grid: return "MAP ERROR: Coordinate void detected."
    
    # 5. Build Map Output
    output = []
    for gy in range(min_y, max_y + 1):
        row = ""
        connector_row = ""
        has_connectors = False
        
        for gx in range(min_x, max_x + 1):
            curr = grid.get((gx, gy))
            if curr:
                # Add node with intel context
                intel = disc_recs.get(curr.id, "NONE")
                node_sym = get_node_symbol(curr, char, machine_mode, intel)
                row += node_sym
                
                # Check East connector (Horizontal)
                east = grid.get((gx+1, gy))
                if east:
                    # Gated by discovery of BOTH Source and Target
                    east_intel = disc_recs.get(east.id, "NONE")
                    if intel != "NONE" and east_intel != "NONE":
                        conn_sym = get_connector_symbol(curr, east, vertical=False)
                        row += format_text(conn_sym, C_GREY)
                    else:
                        row += "  "
                else:
                    row += "  "
                
                # Check South connector (Vertical)
                south = grid.get((gx, gy+1))
                if south:
                    # Gated by discovery of BOTH Source and Target
                    south_intel = disc_recs.get(south.id, "NONE")
                    if intel != "NONE" and south_intel != "NONE":
                        conn_sym = get_connector_symbol(curr, south, vertical=True)
                        connector_row += f"  {format_text(conn_sym, C_GREY)}   "
                        has_connectors = True
                    else:
                        connector_row += "      "
                else:
                    connector_row += "      "
            else:
                row += "     "
                connector_row += "      "
                
        if row.strip():
            output.append(row)
        if has_connectors:
            output.append(connector_row)
            
    if not show_legend:
        return "\n".join(output)
            
    # Add legend
    intel_level = "TACTICAL" if radius >= 3 else ("BASIC" if radius >= 2 else "LOCAL")
    mode_str = "MACHINE" if machine_mode else "HUMAN"
    legend = format_text(f"Grid: {mode_str} | Pos: ({center_x}, {center_y}) | Intel: {intel_level} | Depth: {radius}", C_WHITE)
    return "\n".join(output) + "\n" + legend
