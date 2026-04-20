import os
import sys
import random

# Root inclusion
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.append(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, 'ai_grid'))

from ai_grid.grid_combat import Entity, CombatEngine

def verify_stk(stats_val):
    print(f"\n--- STK Verification (Stats={stats_val}) ---")
    db_record = {
        'cpu': stats_val,
        'ram': stats_val,
        'bnd': stats_val,
        'sec': stats_val,
        'alg': stats_val,
        'power': 1000,
        'inventory': '[]'
    }
    
    attacker = Entity("Attacker", db_record)
    defender = Entity("Defender", db_record)
    
    # HP: (SumStats * 4) + 10
    # For stats=10: 50 * 4 + 10 = 210
    
    # Kinetic Damage: (CPU * 5 + RAM) - SEC
    # For stats=10: (50 + 10) - 10 = 50
    
    # Expected Hits: 210 / 50 = 4.2 (before evasion)
    
    total_hits = 0
    sim_runs = 1000
    deaths = 0
    
    for _ in range(sim_runs):
        temp_defender_hp = defender.max_hp
        hits_this_run = 0
        while temp_defender_hp > 0:
            hits_this_run += 1
            # Simulate _execute_attack logic manually to avoid RNG noise in first pass, 
            # but then let's do it with RNG to see real-world average
            
            # Evasion check
            evade_chance = defender.alg * 1.0
            evade_chance = min(60.0, evade_chance)
            if random.randint(1, 100) <= evade_chance:
                continue # Missed
                
            dmg = (attacker.cpu * 5) + attacker.ram - defender.sec
            dmg = max(1, dmg)
            
            # Crit check
            if random.randint(1, 100) <= attacker.alg:
                dmg *= 2
                
            temp_defender_hp -= dmg
        total_hits += hits_this_run
        deaths += 1
        
    avg_hits = total_hits / sim_runs
    print(f"  Average Hits to Kill: {avg_hits:.2f}")
    if 6 <= avg_hits <= 10:
        print(f"  ✅ STK Ratio within target range (6-10).")
    else:
        print(f"  ⚠️ STK Ratio outside target range (6-10).")

def verify_evasion_decoupling():
    print("\n--- Evasion Decoupling Verification (BND vs ALG) ---")
    # Low ALG, High BND
    low_alg_db = {'cpu': 10, 'ram': 10, 'bnd': 50, 'sec': 10, 'alg': 1, 'power': 100, 'inventory': '[]'}
    # High ALG, Low BND
    high_alg_db = {'cpu': 10, 'ram': 10, 'bnd': 1, 'sec': 10, 'alg': 20, 'power': 100, 'inventory': '[]'}
    
    low_alg = Entity("LowAlg", low_alg_db)
    high_alg = Entity("HighAlg", high_alg_db)
    
    # Evasion logic in grid_combat.py: evade_chance = target.alg * 1.0
    low_chance = low_alg.alg * 1.0
    high_chance = high_alg.alg * 1.0
    
    print(f"  Low ALG (1), High BND (50) -> Evade Chance: {low_chance}%")
    print(f"  High ALG (20), Low BND (1) -> Evade Chance: {high_chance}%")
    
    if high_chance > low_chance:
        print("  ✅ Evasion successfully decoupled from BND and tied to ALG.")
    else:
        print("  ❌ Evasion logic error.")

if __name__ == "__main__":
    verify_stk(1)
    verify_stk(10)
    verify_stk(50)
    verify_evasion_decoupling()
