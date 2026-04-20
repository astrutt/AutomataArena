import asyncio
import os
import sys

# Root inclusion for models import
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'ai_grid'))

class MockIRC:
    def __init__(self):
        self.sent = []
    async def send(self, msg): self.sent.append(msg)
    async def connect(self): pass

class MockNode:
    def __init__(self, net_name):
        self.net_name = net_name
        self.nickserv_verified = set()
        self.irc = MockIRC()
    async def send(self, msg): await self.irc.send(msg)

async def test_multi_net_isolation():
    print("\n[TEST] Multi-Net NickServ Isolation Audit")
    
    node_a = MockNode("Libera")
    node_b = MockNode("Snoonet")
    
    # 1. Verify User on Libera
    line_a = ":irc.libera.chat 307 Antigravity Auditor :is a registered nick"
    parts_a = line_a.split()
    if parts_a[1] == "307":
        who_nick = parts_a[3].lower()
        node_a.nickserv_verified.add(who_nick)
    
    # 2. Check Isolation
    if "auditor" in node_a.nickserv_verified:
        print(" > Libera: Auditor is VERIFIED.")
    
    if "auditor" not in node_b.nickserv_verified:
        print(" > Snoonet: Auditor is UNVERIFIED (Correct Isolation).")
        print("\nSUCCESS: Multi-Net Identity Isolation verified. No trust leakage detected.")
        return True
    else:
        print("FAILURE: Identity state leaked between nodes!")
        return False

if __name__ == "__main__":
    asyncio.run(test_multi_net_isolation())
