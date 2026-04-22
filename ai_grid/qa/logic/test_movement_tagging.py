import asyncio
import sys
import os

# Add root and ai_grid to path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "ai_grid"))

from ai_grid.grid_utils import tag_msg, C_GREEN, C_CYAN, C_WHITE, C_YELLOW, C_GREY

class MockDB:
    async def get_location(self, nick, net):
        return {'name': 'Sector_25_25', 'x': 25, 'y': 25}
    async def move_player(self, nick, net, direction):
        return "Sector_25_24", f"Traversed north to Sector_25_24 (25, 24). (-1.0 power)"

class MockNode:
    def __init__(self):
        self.db = MockDB()
        self.net_name = "testnet"
        self.config = {"channel": "#arena"}
        self.messages = []
    async def send(self, msg):
        self.messages.append(msg)

# Mocking get_action_routing manually within the test execution
async def mock_get_action_routing(node, nick, reply_target, mode="human"):
    if mode == "machine":
        return nick, "#arena", True, "PRIVMSG"
    else:
        return reply_target, "#arena", False, "PRIVMSG"

async def handle_grid_movement_logic(node, nick, direction, reply_target, mode="human"):
    # This logic is extracted from ai_grid/core/handlers/grid.py:11-37
    prev_node = None
    loc = await node.db.get_location(nick, node.net_name)
    if loc: prev_node = loc['name']
    
    private_target, broadcast_chan, machine_mode, reply_method = await mock_get_action_routing(node, nick, reply_target, mode=mode)
    
    node_name, msg = await node.db.move_player(nick, node.net_name, direction)
    if node_name:
        # Structured machine report
        # REFINED: Includes source and destination tags
        await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='MOVEMENT', result='MOVED', nick=nick, source=prev_node, destination=node_name, is_machine=machine_mode)}")
        
        if not machine_mode:
            # Public atmospheric narrative
            adjective = "traversed"
            target_node = node_name # Simplified for test
            narrative = f"{nick} {adjective} {direction} towards {target_node}."
            # REFINED: Includes source and destination tags
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(narrative, action='TRAVEL', nick=nick, source=prev_node, destination=node_name)}")

async def test_movement_tagging():
    print("[*] Starting Movement & Tagging Audit (REFINED)...")
    
    # 1. Human Mode
    print("\n[Case 1] Human Mode Movement")
    node_h = MockNode()
    await handle_grid_movement_logic(node_h, "Alice", "north", "#arena", mode="human")
    print(f"| Private: {node_h.messages[0]}")
    print(f"| Public:  {node_h.messages[1]}")
    assert "MOVEMENT" in node_h.messages[0]
    assert "MOVED" in node_h.messages[0]
    assert "Alice" in node_h.messages[0]
    assert "Sector_25_25" in node_h.messages[0] # Source
    assert "Sector_25_24" in node_h.messages[0] # Destination
    print("[+] Human mode verified (Source/Destination tags present)")

    # 2. Machine Mode
    print("\n[Case 2] Machine Mode Movement")
    node_m = MockNode()
    await handle_grid_movement_logic(node_m, "Alice", "north", "Alice", mode="machine")
    print(f"| RECV: {node_m.messages[0]}")
    assert "[ACTION:MOVEMENT]" in node_m.messages[0]
    assert "[RESULT:MOVED]" in node_m.messages[0]
    assert "[NICK:Alice]" in node_m.messages[0]
    assert "[SRC:SECTOR_25_25]" in node_m.messages[0]
    assert "[DST:SECTOR_25_24]" in node_m.messages[0]
    print("[+] Machine mode verified (Structured SRC/DST tags present)")

    print("\n[✅] Movement & Tagging Audit Complete!")

if __name__ == "__main__":
    asyncio.run(test_movement_tagging())
