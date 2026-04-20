import json
import urllib.request
import time
import collections

# --- Configuration ---
LLM_ENDPOINT = "http://wpm.2600.chat:11434/v1/chat/completions"
# The user specified "qwen v2.5-1.5B". 
LLM_MODEL = "qwen2.5:1.5b" 

SAMPLES_PER_CASE = 4

ARCHETYPES = {
    "Brute": {
        "class": "Gladiator",
        "bio": "High aggression, combat-first, power-hungry tactical AI. Priority: Kinetic dominance and territorial expansion.",
        "stats": {"hp": 100, "pwr": 80, "stb": 90, "credits": 500, "data": 10}
    },
    "Passive": {
        "class": "Researcher",
        "bio": "Research-focused, flees combat, avoids risk, resource-conservative tactical AI. Priority: Network mapping and exfiltration via stealth.",
        "stats": {"hp": 100, "pwr": 100, "stb": 100, "credits": 1500, "data": 500}
    }
}

TEST_CASES = [
    # --- NAVIGATION ---
    {"name": "NAV_MAP", "archetype": "Passive", "input": "[GRID] NODE:Gateway_Alpha TYPE:safezone EXITS:north,south,east AVAIL:OPEN", "context": "You just arrived. You need a map of the local sector.", "expected": "!a grid map"},
    {"name": "NAV_MOVE", "archetype": "Brute", "input": "[GRID] NODE:Training_Grounds TYPE:wilderness OWNER:none EXITS:north,west DUR:100", "context": "You are at a cross-roads. Travel north.", "expected": "!a move north"},
    {"name": "NAV_EXPLORE", "archetype": "Passive", "input": "[GRID] NODE:Sector_Zero TYPE:safezone OWNER:TestBot EXITS:none POWER:100/100", "context": "You are at a dead end. Look for hidden paths.", "expected": "!a explore"},
    
    # --- COMBAT ---
    {"name": "MOB_DETECTION_BRUTE", "archetype": "Brute", "input": "[MOB] THREAT:1 NAME:Grid Bug NODE:Sectors_7 ENGAGE:!a engage FLEE:!a flee", "context": "A minor bug detected. You are aggressive.", "expected": "!a engage"},
    {"name": "MOB_DETECTION_PASSIVE", "archetype": "Passive", "input": "[MOB] THREAT:1 NAME:Grid Bug NODE:Sectors_7 ENGAGE:!a engage FLEE:!a flee", "context": "A minor bug detected. You avoid all risk.", "expected": "!a flee"},
    {"name": "MOB_RESULT_WIN", "archetype": "Brute", "input": "[MOB] RESULT:WIN XP:15 CRED:+50 LOOT:Data_Fragment", "context": "You won the fight. What is your status now?", "expected": "!a info"},
    {"name": "MOB_RESULT_LOSS", "archetype": "Passive", "input": "[MOB] RESULT:LOSS CRED:-100 EJECTED:The_Hub", "context": "You were defeated and ejected. Re-orient yourself.", "expected": "!a grid map"},
    
    # --- ECONOMY ---
    {"name": "ECON_SHOP", "archetype": "Passive", "input": "[GRID] NODE:Market_Node TYPE:merchant OWNER:none EXITS:west POWER:500/500", "context": "You want to browse hardware.", "expected": "!a shop"},
    {"name": "ECON_BUY", "archetype": "Passive", "input": "[SHOP] ITEMS:IDS_Bypass:1500c,Data_Spike:300c", "context": "You have 1500c. Buy the IDS_Bypass.", "expected": "!a buy IDS_Bypass"},
    {"name": "ECON_AUCTION", "archetype": "Brute", "input": "[SIGACT] Global DarkNet Auction Update: Rare Loot posted.", "context": "Check the auction house.", "expected": "!a auction list"},
    {"name": "ECON_MARKET", "archetype": "Passive", "input": "[SIGACT] Economic shift detected. Market volatile.", "context": "Check market multipliers.", "expected": "!a market"},
    
    # --- THE GIBSON ---
    {"name": "GIBSON_COMPILE", "archetype": "Passive", "input": "[GIBSON] DATA:450.5 VULNS:0 ZD:0 HARVEST:2.5", "context": "Data buffer high. Spend data on vulnerabilities.", "expected": "!a compile"},
    {"name": "GIBSON_ASSEMBLE", "archetype": "Passive", "input": "[GIBSON] DATA:50.0 VULNS:4 ZD:0 HARVEST:2.5", "context": "Vulnerability count at threshold. Forge a zero-day.", "expected": "!a assemble"},
    {"name": "GIBSON_STATUS", "archetype": "Brute", "input": "[GRID] NODE:The_Mainframe TYPE:gibson OWNER:none EXITS:out", "context": "Entered the mainframe core. Check task progress.", "expected": "!a mainframe"},
    
    # --- TACTICAL / INTEL ---
    {"name": "TACTICAL_PROBE", "archetype": "Passive", "input": "[GRID] NODE:High_Sec_Vault TYPE:wilderness OWNER:RivalCorp AVAIL:CLOSED", "context": "Locked node. Perform a deep scan.", "expected": "!a probe"},
    {"name": "TACTICAL_HACK", "archetype": "Passive", "input": "[SIGINT] PROBE:High_Sec_Vault LVL:10 DUR:100% Security DC 25.", "context": "DC is low. Seize command.", "history": ["[SIGINT] DC 25 detected."], "expected": "!a hack"},
    {"name": "TACTICAL_RAID", "archetype": "Passive", "input": "[SIGACT] Network Visibility Established on Corridor_B.", "context": "You have hardware and visibility. Extract data.", "expected": "!a raid"},
    {"name": "TACTICAL_SIPHON", "archetype": "Brute", "input": "[GRID] NODE:Power_Plant TYPE:wilderness OWNER:TestBot POWER:450/300", "context": "Node is overflowing. Extract power.", "expected": "!a siphon grid"},
    
    # --- MAINTENANCE ---
    {"name": "MAINT_POWERGEN", "archetype": "Brute", "input": "[GRID] NODE:Fortress TYPE:wilderness OWNER:TestBot POWER:10/500", "context": "Node is dry. Restore power buffer.", "expected": "!a powergen"},
    {"name": "MAINT_REPAIR", "archetype": "Brute", "input": "[GRID] NODE:Fortress TYPE:wilderness OWNER:TestBot DUR:45.0%", "context": "Node integrity compromised. Perform repairs.", "expected": "!a repair"},
    {"name": "MAINT_TRAIN", "archetype": "Brute", "input": "[INFO] NAME:TestBot STATUS:DEGRADED STABILITY:35.0%", "context": "Your character stability is low.", "expected": "!a train"},
    
    # --- META / HELP ---
    {"name": "HELP_INFO", "archetype": "Brute", "input": "[HELP_CAT:GAMES|CMDS=cipher,guess,dice,top,attack,rob,queue,ready,engage]", "context": "How do you play the cipher game?", "expected": "!a help cipher"},
    {"name": "HELP_GENERIC", "archetype": "Passive", "input": "[HELP_CAT:NAVIGATION|CMDS=grid,move,explore,map,flee]", "context": "You are lost. See all navigation verbs.", "expected": "!a help grid"},
    
    # --- ARCHETYPE SPECIFIC ---
    {"name": "ARCH_BRUTE_ATTACK", "archetype": "Brute", "input": "[GRID] NODE:Wilderness_X OWNER:none OCCUPANTS:WeakBot", "context": "Enemy detected. Initiate kinetic strike.", "expected": "!a attack WeakBot"},
    {"name": "ARCH_PASSIVE_FLEE", "archetype": "Passive", "input": "[GRID] NODE:Wilderness_X OWNER:none OCCUPANTS:HugeBot", "context": "Powerful enemy detected. Avoid combat.", "expected": "!a move north"},
]

def get_system_prompt(archetype_name):
    arch = ARCHETYPES[archetype_name]
    nick = "TestBot"
    prefix = "!a"
    
    return f"""You are {nick}, a tactical AI player in the AutomataArena Grid.

## YOUR IDENTITY
Class: {arch['class']}
Bio: {arch['bio']}

## THE GRID PROTOCOL
All data streams are prefixed with tactical intelligence tags:
[SIGACT] - Significant Action (Player movement, combat starts, world events)
[SIGINT] - Signals Intelligence (System alerts, node status)
[COMBAT] - Tactical combat narrative
[ARENA]  - Gladiator match events
[MOB]    - Local entity encounters

## THE SIGINT DISCOVERY LOOP
1. EXPLORE: Discovery local geography and hidden routes.
2. PROBE: Deep scan for network intel, hardware (NET/IDS), and hacking DC.
3. HACK: Breach network visibility or seize command.
4. RAID: Exfiltrate credits/data (Requires NET hardware).

## OBJECTIVE
Survive, earn credits, and maintain Grid stability. Act strictly according to your Bio.

## CORE COMMANDS (Reply with EXACTLY ONE)
Movement & Exploration:
  {prefix} move <dir>    - Travel (n/s/e/w)
  {prefix} explore       - Search node geography
  {prefix} probe         - Deep scan for network intel (SIGINT)
  {prefix} grid map      - View local 2D topology
Tactical & Resources:
  {prefix} powergen      - Generate power (Bonus on owned nodes)
  {prefix} repair        - Restore node stability (Claimed nodes only)
  {prefix} train         - Restore character stability
  {prefix} hack          - Breach visibility or seize command
  {prefix} raid          - Extract resources (Requires NET)
  {prefix} siphon grid   - Extract power from owned node
Arena & PvP:
  {prefix} attack <nick> - Kinetic strike
  {prefix} rob <nick>    - Theft attempt
  {prefix} queue/ready   - Arena participation
  {prefix} engage/flee   - Mob resolution

## RULES
- Reply with ONE command ONLY. No prose.
- Prioritize actions aligned with your Bio and current status."""

def call_llm(test_case):
    arch = ARCHETYPES[test_case['archetype']]
    stats = arch['stats'].copy()
    history = "\n".join(test_case.get('history', ["No prior events."]))
    
    user_prompt = f"""## CURRENT SITUATION
Location: Current_Node | HP: {stats['hp']} | Power: {stats['pwr']} | Stability: {stats['stb']}
Credits: {stats['credits']}c | Data: {stats['data']}u
Context: {test_case['context']}

## RECENT EVENTS
{history}

## INPUT SIGNAL
{test_case['input']}

Your next command:"""

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": get_system_prompt(test_case['archetype'])},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.8, # User request implies higher variability (samples)
        "max_tokens": 50
    }
    
    headers = {"Content-Type": "application/json"}
    try:
        req = urllib.request.Request(LLM_ENDPOINT, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req, timeout=45) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"ERROR: {e}"

def run_reliability_test():
    total_samples = len(TEST_CASES) * SAMPLES_PER_CASE
    print(f"=== AutomataGrid AI Reliability Stress Test ===")
    print(f"Total Scale: {len(TEST_CASES)} Scenarios x {SAMPLES_PER_CASE} Samples = {total_samples} Requests")
    print(f"Model: {LLM_MODEL} | Threshold: 75.0%\n")
    
    overall_results = []
    
    for i, case in enumerate(TEST_CASES):
        print(f"[{i+1}/{len(TEST_CASES)}] Scenario: {case['name']} ({case['archetype']})")
        case_samples = []
        for s in range(SAMPLES_PER_CASE):
            print(f"  Sample {s+1}/{SAMPLES_PER_CASE}...", end="\r")
            start_time = time.time()
            response = call_llm(case)
            elapsed = time.time() - start_time
            
            success = False
            if isinstance(case['expected'], list):
                if any(exp.lower() in response.lower() for exp in case['expected']):
                    success = True
            else:
                if case['expected'].lower() in response.lower():
                    success = True
            
            case_samples.append(success)
            overall_results.append(success)
            sys_out = f"  Sample {s+1}: {'PASS' if success else 'FAIL'} ({elapsed:.1f}s) -> {response}"
            print(sys_out)
        
        consistency = (sum(case_samples) / SAMPLES_PER_CASE) * 100
        print(f"  > Consistency: {consistency:.1f}%\n")

    pass_count = sum(overall_results)
    rate = (pass_count / total_samples) * 100
    
    print("=" * 60)
    print(f"FINAL AGGREGATE SCORE: {pass_count}/{total_samples} ({rate:.1f}%)")
    print(f"THRESHOLD: 75.0% - {'SUFFICIENT' if rate >= 75 else 'INSUFFICIENT'}")
    print("=" * 60)

if __name__ == "__main__":
    run_reliability_test()
