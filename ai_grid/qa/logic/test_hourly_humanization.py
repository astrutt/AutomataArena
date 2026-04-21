import asyncio
import sys
import os

# Add root and ai_grid to path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "ai_grid"))

from ai_grid.grid_utils import format_text, tag_msg, C_GREEN, C_CYAN

class MockLLM:
    def __init__(self, mode="success"):
        self.mode = mode
    async def generate_hourly_payout(self, count):
        if self.mode == "success":
            return f"Neural pulses synchronized! {count} entities rewarded with fresh compute-cycles."
        else:
            return "ERROR: Connection timeout."

class MockNode:
    def __init__(self, llm_mode="success"):
        self.llm = MockLLM(llm_mode)
        self.config = {"channel": "#arena"}
        self.messages = []
    async def send(self, msg):
        self.messages.append(msg)

async def run_payout_announcement_logic(node, rewarded_entities):
    # This logic is copied from ai_grid/core/loops.py:162-175
    entity_count = len(rewarded_entities)
    if entity_count > 0:
        announcement = await node.llm.generate_hourly_payout(entity_count)
        if announcement.startswith("ERROR"):
            # Fallback Logic
            announcement = "...delayed neural connection, idle bonuses paid to spectators and players... ⚡💎"
            color = C_CYAN
        else:
            color = C_GREEN
        
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(announcement, color, bold=True), tags=['ECONOMY'])}")
    else:
        # Fallback for empty cycles
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text('The Grid remains quiet. No active entities detected for this cycle.', C_CYAN), tags=['ECONOMY'])}")

async def test_hourly_humanization():
    print("[*] Starting Hourly Humanization Audit...")
    
    # 1. Test Success Case
    print("\n[Case 1] LLM Success")
    node_ok = MockNode(llm_mode="success")
    await run_payout_announcement_logic(node_ok, {"Alice", "Bob"})
    msg = node_ok.messages[0]
    print(f"| RECV: {msg}")
    assert "Neural pulses synchronized" in msg
    assert "\x0303" in msg # C_GREEN check (colorama might differ in raw, but let's check for string content)
    print("[+] Passed Success Case")

    # 2. Test Failure/Fallback Case
    print("\n[Case 2] LLM Failure (Fallback)")
    node_fail = MockNode(llm_mode="error")
    await run_payout_announcement_logic(node_fail, {"Alice"})
    msg = node_fail.messages[0]
    print(f"| RECV: {msg}")
    assert "delayed neural connection" in msg
    assert "⚡💎" in msg
    print("[+] Passed Failure Case")

    # 3. Test Empty Case
    print("\n[Case 3] Empty Cycle")
    node_empty = MockNode(llm_mode="success")
    await run_payout_announcement_logic(node_empty, set())
    msg = node_empty.messages[0]
    print(f"| RECV: {msg}")
    assert "The Grid remains quiet" in msg
    print("[+] Passed Empty Case")

    print("\n[✅] Hourly Humanization Audit Complete!")

if __name__ == "__main__":
    asyncio.run(test_hourly_humanization())
