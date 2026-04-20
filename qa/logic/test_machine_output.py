import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../ai_grid')))

from ai_grid.grid_utils import tag_msg, format_text

def test_machine_output():
    print("--- [TEST: MACHINE MODE PROTOCOL] ---")
    
    # 1. Basic Tagged Message
    res1 = tag_msg("Scanning node architecture...", action="RECON", result="SUCCESS", nick="TestBot", is_machine=True)
    print(f"Test 1 (Basic): {res1}")
    assert "[GRID][ACTION:RECON][RESULT:SUCCESS][NICK:TestBot]" in res1
    assert "Scanning node architecture..." in res1
    
    # 2. Icon Stripping Check
    res2 = tag_msg("Found 💎 and 💰 and 🛡️", action="EXPLORE", is_machine=True)
    print(f"Test 2 (Icons): {res2}")
    # Verify no unicode
    for char in res2:
        assert ord(char) < 128, f"Found non-ASCII char: {char}"
    
    # 3. IRC Code Stripping
    text_with_codes = format_text("Colored Text", color_code="03", bold=True, is_machine=True)
    res3 = tag_msg(text_with_codes, action="OSINT", is_machine=True)
    print(f"Test 3 (IRC Codes): {res3}")
    assert "\x03" not in res3
    assert "\x02" not in res3
    
    # 4. Location Tag
    res4 = tag_msg("Landed in Sector-X", action="GEOINT", location="Sector-X", is_machine=True)
    print(f"Test 4 (Location): {res4}")
    assert "[LOC:SECTOR-X]" in res4

def test_human_output():
    print("\n--- [TEST: HUMAN MODE AESTHETICS] ---")
    
    # 1. Basic Tagged Message
    res1 = tag_msg("Landed in North-S1", action="GEOINT", result="SUCCESS", nick="PlayerOne", is_machine=False)
    print(f"Test 1 (Human): {res1}")
    assert "[GRID]" in res1
    # Check for icons (should be there)
    # GEOINT icon is 📡 or similar
    
    # 2. Color Codes
    res2 = format_text("Red Text", color_code="05", is_machine=False)
    print(f"Test 2 (Colors): {res2}")
    assert "\x0305" in res2

if __name__ == "__main__":
    try:
        test_machine_output()
        test_human_output()
        print("\n[SUCCESS] Protocol verification passed.")
    except Exception as e:
        print(f"\n[FAILURE] Protocol verification failed: {e}")
        sys.exit(1)
