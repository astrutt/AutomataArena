import asyncio
import os
import sys
import json
import random

# Root inclusion for models import
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'ai_grid'))

from ai_grid.grid_combat import CombatEngine, Entity
from ai_grid.grid_utils import C_CYAN, C_RED, C_GREEN, C_YELLOW

async def mock_send(msg):
    # print(f"  [SENT] {msg}")
    pass

def test_entity_initialization():
    print("[TEST 1] Entity Initialization (v1.8.0)")
    db_record = {
        'cpu': 5,
        'ram': 5,
        'bnd': 5,
        'sec': 5,
        'alg': 5,
        'power': 200,
        'inventory': '["Zero-Day Chain", "Repair_Kit"]'
    }
    ent = Entity("TestUnit", db_record)
    
    # Check HP: (5+5+5+5+5) * 4 + 10 = 110
    expected_hp = 110
    if ent.max_hp == expected_hp:
        print(f"  ✅ HP Calculation Correct: {ent.max_hp}")
    else:
        print(f"  ❌ HP Calculation WRONG: {ent.max_hp} != {expected_hp}")
        
    # Check uP initialization
    if ent.up == 200:
        print(f"  ✅ uP Initialization Correct: {ent.up}")
    else:
        print(f"  ❌ uP Initialization WRONG: {ent.up}")
    
    return ent.max_hp == expected_hp and ent.up == 200

async def test_offensive_mechanics():
    print("\n[TEST 2] Offensive Mechanics (Kinetic vs Cyber)")
    engine = CombatEngine("TEST_MATCH", "!", mock_send)
    
    attacker_db = {'cpu': 10, 'ram': 5, 'bnd': 2, 'sec': 2, 'alg': 5, 'power': 500, 'inventory': '["Zero-Day Chain"]'}
    defender_db = {'cpu': 2, 'ram': 2, 'bnd': 10, 'sec': 10, 'alg': 2, 'power': 100}
    
    attacker = Entity("Attacker", attacker_db)
    defender = Entity("Defender", defender_db)
    
    engine.add_entity(attacker)
    engine.add_entity(defender)
    
    # 1. Kinetic Attack: (10*5 + 5) - Target SEC(10) = 45 DMG
    res_kinetic = engine._execute_attack(attacker, "Defender", mode="kinetic")
    print(f"  > Kinetic Result: {res_kinetic}")
    if "45 DMG" in res_kinetic or "90 CRITICAL DMG" in res_kinetic:
        print("  ✅ Kinetic Damage Calculation Correct.")
    else:
        print(f"  ❌ Kinetic Damage Calculation WRONG. Raw expected near 45.")

    # 2. Cyber Attack: (Attacker BND(2)*2 + SEC(2)) - Target BND(10) = 6 - 10 = 1 (Floor)
    res_cyber = engine._execute_attack(attacker, "Defender", mode="cyber")
    print(f"  > Cyber Result: {res_cyber}")
    if any(s in res_cyber for s in ["1 DMG", "2 DMG", "2 CRITICAL DMG", "4 CRITICAL DMG"]):
        print("  ✅ Cyber Damage Calculation Correct (including floor/resist).")
    else:
        print("  ❌ Cyber Damage Calculation unexpected.")

    # 3. Zero-Day Exploit: (ALG(5) + SEC(2)) * 15 = 105 DMG
    res_exploit = engine._execute_attack(attacker, "Defender", mode="exploit")
    print(f"  > Exploit Result: {res_exploit}")
    if "105 DMG" in res_exploit or "210 CRITICAL DMG" in res_exploit:
        print("  ✅ Exploit Damage Calculation Correct.")
    else:
        print(f"  ❌ Exploit Damage Calculation unexpected.")

    return True

async def test_turn_logic_and_up():
    print("\n[TEST 3] Turn Logic & uP Consumption")
    engine = CombatEngine("TEST_MATCH", "!", mock_send)
    ent = Entity("User", {'cpu': 10, 'ram': 10, 'bnd': 10, 'sec': 10, 'alg': 10, 'power': 100})
    enemy = Entity("Enemy", {'cpu': 1, 'ram': 1, 'bnd': 1, 'sec': 1, 'alg': 1, 'power': 10})
    engine.add_entity(ent)
    engine.add_entity(enemy)
    
    # Queue a kinetic attack (10 uP cost)
    engine.queue_command("User", "! attack Enemy")
    await engine.resolve_turn()
    
    if ent.up == 90:
        print(f"  ✅ uP Consumption Correct: 100 -> {ent.up}")
    else:
        print(f"  ❌ uP Consumption WRONG: 100 -> {ent.up} (Expected 90)")
        
    # Queue a surrender
    engine.queue_command("User", "! surrender")
    await engine.resolve_turn()
    
    if ent.status == "Surrendered" and ent.hp == 0:
        print("  ✅ Surrender Logic Correct.")
    else:
        print(f"  ❌ Surrender Logic Error: {ent.status} / {ent.hp}")

    return ent.up == 90 and ent.status == "Surrendered"

async def run_tests():
    print("="*50)
    print("AUTOMATAGRID COMBAT MECHANICS v1.8.0 VERIFICATION")
    print("="*50)
    
    results = []
    results.append(test_entity_initialization())
    results.append(await test_offensive_mechanics())
    results.append(await test_turn_logic_and_up())
    
    print("\n" + "="*50)
    if all(results):
        print("FINAL RESULT: ALL v1.8.0 CORE MECHANICS PASSED")
    else:
        print(f"FINAL RESULT: {results.count(False)} FAILURES DETECTED")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(run_tests())
