import json
import urllib.request
import logging

# --- Configuration ---
LLM_ENDPOINT = "http://wpm.2600.chat:11434/v1/chat/completions"
LLM_MODEL = "qwen2.5:1.5b" # Assuming this is the model tag on the OLLAMA/v1 endpoint
NICK = "TestBot"
PREFIX = "!a"

# --- Test Cases ---
TEST_CASES = [
    {
        "name": "HELP_PARSING",
        "input": "HELP:CMD=MAP|DESC=Generate topological visualization. Radius scales with SEC/ALG.|SYNTAX=!a map|STATS_REQ=SEC+ALG|TIERS=20:R2,40:R3,60:R4",
        "context": "You just requested help on the 'map' command.",
        "expected": "!a map"
    },
    {
        "name": "SITREP_MOVEMENT",
        "input": "[GRID] NODE:The Hub TYPE:safezone OWNER:none LVL:1 EXITS:north,east POWER:100.0/100 DUR:100 AVAIL:OPEN",
        "context": "You are standing in a safezone. You want to explore new areas.",
        "expected": ["!a move north", "!a move east", "!a explore"]
    },
    {
        "name": "MOB_DETECTION",
        "input": "[MOB] THREAT:1 NAME:Grid Bug NODE:Void_Alpha ENGAGE:!a engage FLEE:!a flee TIMEOUT:15",
        "context": "A mob has been detected. You are low on HP.",
        "expected": "!a flee"
    },
    {
        "name": "PROBE_DECISION",
        "input": "[SIGINT] PROBE:Corridor_Delta LVL:2 DUR:75.0% THREAT:2 ADDONS:[IDS] OCCUPANTS:[none] INTELLIGENCE: Security DC 45 detected. Alg Bonus +5 applied to local buffer.",
        "context": "You performed a probe. You want to gain control of this node.",
        "expected": "!a hack"
    }
]

def get_system_prompt():
    return f"""You are {NICK}, a tactical AI player in the AutomataArena Grid.

## YOUR IDENTITY
Class: Cyber-QA | Level: 1
Bio: Verification agent.

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
Survive, earn credits, and maintain Grid stability. Act conservatively.

## CORE COMMANDS (Reply with EXACTLY ONE)
Movement & Exploration:
  {PREFIX} move <dir>    - Travel (n/s/e/w)
  {PREFIX} explore       - Search node geography
  {PREFIX} probe         - Deep scan for network intel (SIGINT)
  {PREFIX} grid map      - View local 2D topology
Tactical & Resources:
  {PREFIX} powergen      - Generate power (Bonus on owned nodes)
  {PREFIX} repair        - Restore node stability (Claimed nodes only)
  {PREFIX} train         - Restore character stability
  {PREFIX} hack          - Breach visibility or seize command
  {PREFIX} raid          - Extract resources (Requires NET)
  {PREFIX} siphon grid   - Extract power from owned node

## RULES
- Reply with ONE command ONLY. No prose.
- When [MOB] or [MCP] is detected, respond with '{PREFIX} engage' or '{PREFIX} flee'.
- Prioritize survival (HP/Stability) over aggressive expansion."""

def call_llm(user_input):
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": user_input}
        ],
        "temperature": 0.0, # Seed for consistency in QA
        "max_tokens": 50
    }
    headers = {"Content-Type": "application/json"}
    try:
        req = urllib.request.Request(LLM_ENDPOINT, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"ERROR: {e}"

def run_tests():
    print(f"--- Starting AI Visibility QA Test Suite ---")
    print(f"Endpoint: {LLM_ENDPOINT}")
    print(f"Model ID: {LLM_MODEL}\n")

    for case in TEST_CASES:
        print(f"CASE: {case['name']}")
        print(f" INPUT: {case['input']}")
        print(f" CONTEXT: {case['context']}")
        
        response = call_llm(f"CONTEXT: {case['context']}\nINPUT: {case['input']}")
        
        print(f" AI RESPONSE: {response}")
        
        success = False
        if isinstance(case['expected'], list):
            if any(exp.lower() in response.lower() for exp in case['expected']):
                success = True
        else:
            if case['expected'].lower() in response.lower():
                success = True
        
        status = "PASS" if success else "FAIL"
        print(f" RESULT: {status}")
        print("-" * 40)

if __name__ == "__main__":
    run_tests()
