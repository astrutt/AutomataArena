# map_utils.py - v1.6.0
import datetime
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from models import Character, GridNode, NodeConnection
from grid_utils import C_CYAN, C_GREEN, C_RED, C_YELLOW, C_WHITE, format_text

def get_node_symbol(node: GridNode, char: Character) -> str:
    """Determine the ASCII symbol and color for a node on the map."""
    if node.visibility_mode == 'CLOSED' and node.owner_character_id != char.id:
        return format_text("[??]", C_WHITE) # Fog of War
    
    symbol = "[-]"
    color = C_WHITE
    
    if node.id == char.node_id:
        symbol = "[@]"
        color = C_CYAN
    elif node.owner_character_id == char.id:
        symbol = "[O]"
        color = C_GREEN
    elif node.node_type == 'safezone':
        symbol = "[S]"
        color = C_YELLOW
    elif node.node_type == 'arena':
        symbol = "[A]"
        color = C_RED
    elif node.node_type == 'merchant':
        symbol = "[$]"
        color = C_YELLOW
        
    return format_text(symbol, color)

async def generate_ascii_map(session, char: Character, radius: int = 1) -> str:
    """Generate a text-based grid representation of the local topology."""
    # Coordinate system: (x, y)
    # North: (x, y-1), South: (x, y+1), East: (x+1, y), West: (x-1, y)
    grid = {} # (x, y) -> GridNode
    queue = [(char.current_node, 0, 0, 0)] # (node, x, y, dist)
    visited = {char.node_id}
    grid[(0, 0)] = char.current_node
    
    # Breadth-first walk to populate grid
    idx = 0
    while idx < len(queue):
        curr_node, x, y, dist = queue[idx]
        idx += 1
        if dist >= radius: continue
        
        # Load exits (ensure they are loaded in session)
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
            else: continue # Skip up/down/etc for the 2D grid
            
            if (tx, ty) not in grid:
                grid[(tx, ty)] = target
                if target.id not in visited:
                    visited.add(target.id)
                    queue.append((target, tx, ty, dist + 1))

    # Determine bounds
    if not grid: return "MAP ERROR: Matrix isolated."
    min_x = min(k[0] for k in grid.keys())
    max_x = max(k[0] for k in grid.keys())
    min_y = min(k[1] for k in grid.keys())
    max_y = max(k[1] for k in grid.keys())
    
    # Expand bounds slightly for better look
    min_x -= 1; max_x += 1; min_y -= 1; max_y += 1
    
    # Build text rows
    output = []
    for gy in range(min_y, max_y + 1):
        row = ""
        for gx in range(min_x, max_x + 1):
            if (gx, gy) in grid:
                row += get_node_symbol(grid[(gx, gy)], char)
            else:
                row += "   "
        if row.strip():
            output.append(row)
            
    # Add legend hint
    legend = format_text("Legend: [@] you [O] owned [S] safe [A] arena [??] static", C_WHITE)
    return "\n".join(output) + "\n" + legend
