import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

# Add root to path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)

from ai_grid.core.handlers.grid import handle_grid_loot

async def test_compromise_loop_dispatch():
    print("[*] Starting Compromise Loop Dispatch Audit (Task 065)...")
    
    # Mock Node
    node = MagicMock()
    node.net_name = "2600net"
    node.send = AsyncMock()
    node.add_xp = AsyncMock()
    node.db = MagicMock()
    
    # Mock Repos
    node.db.discovery.probe_node = AsyncMock(return_value={'success': True, 'name': '[SMB]', 'visibility': 'OPEN', 'hack_dc': 15, 'raid_target': None})
    node.db.infiltration.hack_node = AsyncMock(return_value=(True, "HACK SUCCESS", None))
    node.db.infiltration.exploit_node = AsyncMock(return_value=(True, "EXPLOIT SUCCESS", None))
    node.db.infiltration.siphon_node = AsyncMock(return_value=(True, "SIPHON SUCCESS", None))
    node.db.infiltration.raid_node = AsyncMock(return_value={'success': True, 'msg': "RAID SUCCESS"})
    
    # Mock get_action_routing
    with patch('ai_grid.core.handlers.grid.get_action_routing', AsyncMock(return_value=("#tester", None, False, "PRIVMSG"))), \
         patch('ai_grid.core.handlers.grid.check_rate_limit', AsyncMock(return_value=True)):
        
        nick = "Tester"
        chan = "#grid"

        print("[1] Testing: raid probe [SMB]...")
        await handle_grid_loot(node, nick, chan, ["probe", "[SMB]"])
        node.db.discovery.probe_node.assert_called_once_with(nick, "2600net", target_name="[SMB]")
        print(" | Result: [✅] PASS")

        print("[2] Testing: raid Rizon hack [SMB]...")
        await handle_grid_loot(node, nick, chan, ["Rizon", "hack", "[SMB]"])
        node.db.infiltration.hack_node.assert_called_once_with(nick, "Rizon", target_name="[SMB]")
        print(" | Result: [✅] PASS")

        print("[3] Testing: raid siphon [SMB]...")
        await handle_grid_loot(node, nick, chan, ["siphon", "[SMB]"])
        node.db.infiltration.siphon_node.assert_called_once_with(nick, "2600net", target_name="[SMB]")
        print(" | Result: [✅] PASS")

        print("[4] Testing: raid exploit [SMB]...")
        await handle_grid_loot(node, nick, chan, ["exploit", "[SMB]"])
        node.db.infiltration.exploit_node.assert_called_once_with(nick, "2600net", target="[SMB]")
        print(" | Result: [✅] PASS")

        print("[5] Testing: raid [SMB] (Extraction)...")
        await handle_grid_loot(node, nick, chan, ["[SMB]"])
        node.db.infiltration.raid_node.assert_called_once_with(nick, "2600net", target_name="[SMB]")
        print(" | Result: [✅] PASS")

    print("\n[✅] Compromise Loop Dispatch Audit COMPLETE.")

if __name__ == "__main__":
    asyncio.run(test_compromise_loop_dispatch())
