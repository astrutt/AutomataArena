import asyncio
import os
import sys

# Root inclusion for models import
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'ai_grid'))

from ai_grid.core.handlers.base import handle_help

class MockDB:
    async def get_prefs(self, nick, net):
        # Default to machine mode for part of the test
        return {'output_mode': self.mode, 'msg_type': 'privmsg'}

class MockNode:
    def __init__(self):
        self.prefix = "!"
        self.net_name = "testnet"
        self.config = {"nickname": "Antigravity", "channel": "#grid"}
        self.db = MockDB()
        self.sent = []
    async def send(self, msg):
        self.sent.append(msg)

async def test_help_parity():
    print("\n[TEST 1] Human-Readable Parity (v1.6.4)")
    node = MockNode()
    node.db.mode = "human"
    await handle_help(node, "Auditor", [], "#grid")
    
    output = "\n".join(node.sent)
    checks = ["v1.6.4", "probe", "memos", "net", "link", "bolster", "install"]
    all_pass = True
    for c in checks:
        if c in output:
             print(f" > Found: {c}")
        else:
             print(f" > MISSING: {c}")
             all_pass = False
    
    if all_pass: print("\nSUCCESS: Human-mode parity verified.")
    else: print("\nFAILURE: Missing verbs in help output.")

async def test_help_machine_mode():
    print("\n[TEST 2] Machine-Readable Overview")
    node = MockNode()
    node.db.mode = "machine"
    await handle_help(node, "AI_Bot", [], "AI_Bot")
    
    output = "\n".join(node.sent)
    print(f" > Output: {output}")
    if "[HELP] VERBS:" in output and "probe" in output and "memos" in output:
         print("SUCCESS: Machine-mode overview correctly formatted.")
    else:
         print("FAILURE: Machine-mode overview malformed or missing verbs.")

    print("\n[TEST 3] Machine-Readable Detail")
    node.sent = []
    await handle_help(node, "AI_Bot", ["probe"], "AI_Bot")
    output = "\n".join(node.sent)
    print(f" > Output: {output}")
    if "[HELP] CMD:PROBE DESC:" in output and "SYNTAX:! probe" in output:
         print("SUCCESS: Machine-mode detail correctly formatted.")
    else:
         print("FAILURE: Machine-mode detail malformed.")

if __name__ == "__main__":
    asyncio.run(test_help_parity())
    asyncio.run(test_help_machine_mode())
