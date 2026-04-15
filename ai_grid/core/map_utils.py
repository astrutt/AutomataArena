# map_utils.py - v1.5.0 Stable
import datetime
import random
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from models import Character, GridNode, NodeConnection
from grid_utils import C_CYAN, C_GREEN, C_RED, C_YELLOW, C_WHITE, C_GREY, format_text

def get_node_symbol(node: GridNode, char: Character, machine_mode: bool = False) -> str:
    """Determine the symbol and color for a node based on state and intelligence tiers."""
    
    total_stat = char.sec + char.alg
    
    # 1. Fog of War / Intel Tiers
    if node.visibility_mode == 'CLOSED' and node.owner_character_id != char.id:
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
        
        # Tier 1: Minimalist
        return format_text("[??]" if not machine_mode else "[?]", C_WHITE)

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
    
    is_closed = source.visibility_mode == 'CLOSED' or target.visibility_mode == 'CLOSED'
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

async def generate_ascii_map(session, char: Character, machine_mode: bool = False) -> str:
    """Generate a grid representation with 2-char paths and tiered intelligence."""
    
    # 1. Calculate Radius Tier
    total_stat = char.sec + char.alg
    if total_stat >= 60: radius = 4
    elif total_stat >= 40: radius = 3
    elif total_stat >= 20: radius = 2
    else: radius = 1
    
    grid = {} # (x, y) -> GridNode
    queue = [(char.current_node, 0, 0, 0)] 
    visited = {char.node_id}
    grid[(0, 0)] = char.current_node
    
    # Breadth-first walk
    idx = 0
    while idx < len(queue):
        curr_node, x, y, dist = queue[idx]
        idx += 1
        if dist >= radius: continue
        
        stmt = select(NodeConnection).where(NodeConnection.source_node_id == curr_node.id).options(selectinload(NodeConnection.target_node))
        conns = (await session.execute(stmt)).scalars().all()
        
        for conn in conns:
            if conn.is_hidden: continue
            target = conn.target_node
            tx, ty = x, y
            d = conn.direction.lower()
            if d == 'north': ty -= 1
            elif d == 'south': ty += 1
            elif d == 'east': tx += 1
            elif d == 'west': tx -= 1
            else: continue 
            
            if (tx, ty) not in grid:
                grid[(tx, ty)] = target
                if target.id not in visited:
                    visited.add(target.id)
                    queue.append((target, tx, ty, dist + 1))

    if not grid: return "MAP ERROR: Matrix isolated."
    
    # Determine bounds
    min_x = min(k[0] for k in grid.keys())
    max_x = max(k[0] for k in grid.keys())
    min_y = min(k[1] for k in grid.keys())
    max_y = max(k[1] for k in grid.keys())
    
    min_x -= 1; max_x += 1; min_y -= 1; max_y += 1
    
    # Character Intelligence context
    intel_level = "DEEP SCAN" if radius >= 4 else ("TACTICAL" if radius >= 3 else "BASIC")
    
    # Build text rows
    output = []
    for gy in range(min_y, max_y + 1):
        row = ""
        connector_row = ""
        has_connectors = False
        
        for gx in range(min_x, max_x + 1):
            curr = grid.get((gx, gy))
            if curr:
                # Add node
                node_sym = get_node_symbol(curr, char, machine_mode)
                row += node_sym
                
                # Check East connector
                east = grid.get((gx+1, gy))
                if east:
                    conn_sym = get_connector_symbol(curr, east, vertical=False)
                    row += format_text(conn_sym, C_GREY)
                else:
                    row += "  " # 2 chars wide padding
                
                # Check South connector
                south = grid.get((gx, gy+1))
                if south:
                    conn_sym = get_connector_symbol(curr, south, vertical=True)
                    # Align with the node box (usually 3 chars wide: [X])
                    # We want the connector under the center
                    connector_row += f"  {format_text(conn_sym, C_GREY)}   "
                    has_connectors = True
                else:
                    connector_row += "      "
            else:
                row += "     " # 3 (node) + 2 (link)
                connector_row += "      "
                
        if row.strip():
            output.append(row)
        if has_connectors:
            output.append(connector_row)
            
    # Add legend
    mode_str = "MACHINE" if machine_mode else "HUMAN"
    legend = format_text(f"Mode: {mode_str} | Intel: {intel_level} | Radius: {radius}", C_WHITE)
    return "\n".join(output) + "\n" + legend
