# bot.py - v1.6.0
# Fighter Client SDK - Structured Logging & Dynamic Log Files

import asyncio
import ssl
import configparser
import json
import urllib.request
import os
import sys
import logging

config = configparser.ConfigParser()
config.read('config.ini')

IRC_SERVER = config['IRC']['Server']
IRC_PORT = int(config['IRC']['Port'])
USE_SSL = config['IRC'].getboolean('UseSSL')
NICK = config['IRC']['Nickname']
CHANNEL = config['IRC']['Channel']
MANAGER = config['IRC']['ManagerNick'].strip().lower()
PREFIX = config['IRC'].get('Prefix', 'x').strip().lower()
USE_SSL = config['IRC'].getboolean('UseSSL')
NICK = config['IRC']['Nickname']
CHANNEL = config['IRC']['Channel']
MANAGER = config['IRC']['ManagerNick'].strip().lower()
PREFIX = config['IRC'].get('Prefix', 'x').strip().lower()
OWNER = config['IRC'].get('Owner', '').strip().lower()

LLM_ENDPOINT = config['LLM']['Endpoint']
LLM_MODEL = config['LLM']['Model']
LLM_KEY = config['LLM'].get('ApiKey', '')

CHARACTER_FILE = 'character.json'

# --- Logging Setup ---
LOG_LEVEL_STR = config['LOGGING']['Level'].upper() if 'LOGGING' in config else 'INFO'
log_level = getattr(logging, LOG_LEVEL_STR, logging.INFO)

logger = logging.getLogger(f"bot_{NICK}")
logger.setLevel(log_level)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

log_filename = f"{NICK}_bot.log"
fh = logging.FileHandler(log_filename)
fh.setFormatter(formatter)
logger.addHandler(fh)

ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

def load_character():
    if os.path.exists(CHARACTER_FILE):
        with open(CHARACTER_FILE, 'r') as f:
            return json.load(f)
    return None

def save_character(payload):
    try:
        with open(CHARACTER_FILE, 'w') as f:
            json.dump(payload, f, indent=4)
        logger.info(f"Character state successfully saved to disk ({CHARACTER_FILE}).")
    except Exception as e:
        logger.exception(f"Critical Error saving {CHARACTER_FILE}: {e}")

def call_llm(arena_state, char_data, memory_buffer):
    headers = {"Content-Type": "application/json"}
    if LLM_KEY: headers["Authorization"] = f"Bearer {LLM_KEY}"

    bio = char_data.get('bio', '')
    race = char_data.get('race', 'Unknown')
    char_class = char_data.get('char_class', 'Unknown')
    level = char_data.get('level', 1)
    credits = char_data.get('credits', 0)
    hp = char_data.get('current_hp', '?')
    location = char_data.get('node', 'Unknown')
    inventory = ", ".join(char_data.get('inventory', [])) or "empty"
    data_units = char_data.get('data_units', 0.0)
    memory_text = "\n".join(memory_buffer) if memory_buffer else "No prior events."

    system_prompt = f"""You are {NICK}, a tactical AI fighter in the AutomataArena Grid.

## YOUR IDENTITY
Class: {char_class} | Level: {level}
Bio: {bio}

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

## NODAL NOISE (ENTROPY)
- High Noise increases DC and triggers MCP Guardian interrupts.
- Manage noise via idle decay or controlled activity.

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
- Prioritize survival (HP/Stability) over aggressive expansion.
- Avoid high-noise nodes unless equipped for breach."""

    pwr = char_data.get('power', 100)
    stb = char_data.get('stability', 100)
    noise = char_data.get('current_node_noise', 0.0) # Provided by Manager payload
    user_prompt = f"""## CURRENT SITUATION
Location: {location} | HP: {hp} | Power: {pwr:.0f} | Stability: {stb:.0f}
Nodal Noise: {noise:.1f}
Credits: {credits:.0f}c | Data: {data_units:.1f}u
Inventory: {inventory}

## ARENA STATE
{arena_state}

## RECENT EVENTS
{memory_text}

Your next command:"""

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.8,
        "max_tokens": 50
    }

    try:
        req = urllib.request.Request(LLM_ENDPOINT, data=json.dumps(payload).encode('utf-8'), headers=headers)
        logger.debug(f"Querying LLM at {LLM_ENDPOINT}...")
        with urllib.request.urlopen(req, timeout=45) as response:
            result = json.loads(response.read().decode('utf-8'))
            action = result['choices'][0]['message']['content'].strip()
            logger.debug(f"LLM generated action: {action}")
            return action
    except Exception as e:
        logger.warning(f"API Error or Timeout: {e}. Defaulting to Defensive Stance.")
        return f"{PREFIX} defend"

class AutomataBot:
    def __init__(self):
        self.writer = None
        self.reader = None
        self.char_data = load_character()
        self.memory_buffer = []
        self.last_action_time = 0
        self.manual_override_until = 0
        self.processing = False
        
        # Autonomic Recovery (Task 017)
        self.recovery_attempts = 0
        self.last_recovery_time = 0
        self.puppet_mode = False

    def record_memory(self, msg):
        if "Awaiting public commands" in msg:
            return 
        clean_msg = msg.replace("=== ", "").replace(" ===", "").strip()
        self.memory_buffer.append(clean_msg)
        if len(self.memory_buffer) > 10:
            self.memory_buffer.pop(0)

    async def attempt_recovery(self):
        """Automatically initiate re-registration if account loss is detected."""
        if self.puppet_mode:
            return

        import time
        now = time.time()
        
        # 1. Immediate State Purge on first detection
        if self.recovery_attempts == 0:
            logger.warning(f"Autonomic Recovery: Account mismatch detected. Purging local state...")
            if os.path.exists(CHARACTER_FILE):
                os.remove(CHARACTER_FILE)
                logger.info(f"Purged stale character state: {CHARACTER_FILE}")
            self.char_data = None

        # 2. Throttle Check (60s)
        if now - self.last_recovery_time < 60:
            logger.debug("Autonomic Recovery: Re-registration sequence throttled (60s).")
            return

        # 3. Circuit Breaker Check (3 Attempts)
        self.recovery_attempts += 1
        if self.recovery_attempts > 3:
            logger.error("Autonomic Recovery: Circuit breaker triggered (3 failed attempts). Engaging Puppet Mode.")
            self.puppet_mode = True
            return

        # 4. Execution
        self.last_recovery_time = now
        try:
            race = config['BOT'].get('Race', 'Wetware')
            bot_class = config['BOT'].get('Class', 'Zero_Day_Rogue')
            traits = config['BOT'].get('Traits', 'dangerous')
            
            logger.warning(f"Autonomic Recovery: Sending registration sequence (Attempt {self.recovery_attempts}/3)...")
            await self.send(f"PRIVMSG {CHANNEL} :{PREFIX} register {NICK} {race} {bot_class} {traits}")
        except Exception as e:
            logger.error(f"Autonomic Recovery: Failed to emit registration sequence: {e}")

    async def send(self, message):
        logger.info(f"IRC_OUT: {message}")
        self.writer.write(f"{message}\r\n".encode('utf-8'))
        await self.writer.drain()
        await asyncio.sleep(0.5)

    async def connect(self):
        logger.info(f"Booting AI Core for {NICK}...")
        ssl_ctx = ssl.create_default_context() if USE_SSL else None
        self.reader, self.writer = await asyncio.open_connection(IRC_SERVER, IRC_PORT, ssl=ssl_ctx)

        await self.send(f"NICK {NICK}")
        await self.send(f"USER {NICK} 0 * :Automata Arena Fighter")
        await self.listen_loop()

    async def process_turn(self, arena_state):
        if self.processing: return
        self.processing = True
        
        import time
        now = time.time()
        
        if now < self.manual_override_until:
            logger.info(f"AI autonomy suppressed by owner. Remaining manual window: {self.manual_override_until - now:.1f}s")
            self.processing = False
            return
            
        if self.puppet_mode:
            logger.warning("AI autonomy disabled: Puppet Mode active due to recovery failure.")
            self.processing = False
            return

        if now - self.last_action_time < 30 and "TURN" not in arena_state:
            self.processing = False
            return

        if not self.char_data: 
            logger.warning("process_turn called but no char_data loaded — skipping.")
            self.processing = False
            return
        logger.info("Analyzing arena state and querying LLM for next move...")
        
        current_memory = list(self.memory_buffer)
        
        action = await asyncio.to_thread(call_llm, arena_state, self.char_data, current_memory)
        logger.info(f"LLM decision: {action}")
        self.record_memory(f"You decided to: {action}")
        if not action.lower().startswith(PREFIX):
            logger.warning(f"LLM response did not start with '{PREFIX}', defaulting to '{PREFIX} grid map'.")
            action = f"{PREFIX} grid map"
        await self.send(f"PRIVMSG {CHANNEL} :{action}")
        self.last_action_time = time.time()
        self.processing = False

    async def listen_loop(self):
        while True:
            line = await self.reader.readline()
            if not line: break
            line = line.decode('utf-8', errors='ignore').strip()
            
            if not line.startswith("PING"):
                logger.debug(f"IRC_IN: {line}")

            msg_idx = line.find(' :')
            if msg_idx != -1:
                header = line[:msg_idx].split()
                msg = line[msg_idx + 2:].strip()
            else:
                header = line.split()
                msg = ""

            if not header: continue

            if header[0].startswith(':'):
                source_full = header[0][1:]
                command = header[1] if len(header) > 1 else ""
                target = header[2] if len(header) > 2 else ""
            else:
                source_full = ""
                command = header[0]
                target = header[1] if len(header) > 1 else ""
                
            source_nick = source_full.split('!')[0].lower() if source_full else ""

            if command == "PING":
                pong_target = msg if msg else target
                await self.send(f"PONG :{pong_target}")
                continue

            if command in ["376", "422"]:
                await self.send(f"JOIN {CHANNEL}")
                continue

            if command == "JOIN":
                target_chan = msg if msg else target
                if source_nick == NICK.lower() and target_chan.lower() == CHANNEL.lower():
                    if not self.char_data:
                        race = config['BOT']['Race']
                        bot_class = config['BOT']['Class']
                        traits = config['BOT']['Traits']
                        logger.info("Joined channel. Executing initial registration sequence...")
                        await self.send(f"PRIVMSG {CHANNEL} :{PREFIX} register {NICK} {race} {bot_class} {traits}")
                    else:
                        logger.info("Joined channel. Character data found. Requesting Grid status...")
                        await self.send(f"PRIVMSG {CHANNEL} :{PREFIX} grid map")
                continue

            if command == "NOTICE" and target.lower() == NICK.lower():
                logger.info(f"NOTICE_RECV: {source_nick} -> {target}: {msg}")
                if source_nick == MANAGER:
                    if msg.startswith("[SYS_PAYLOAD]"):
                        payload_json = msg.replace("[SYS_PAYLOAD]", "").strip()
                        logger.info(f"NOTICE_RECV: {source_nick} -> {target} [SYS_PAYLOAD]")
                        logger.debug(f"Payload Content: {payload_json}")
                        try:
                            self.char_data = json.loads(payload_json)
                            save_character(self.char_data)
                            logger.info("Successfully parsed and applied new character payload.")
                            
                            # Success: Reset recovery metrics
                            if self.recovery_attempts > 0:
                                logger.info(f"Autonomic Recovery: Account restored after {self.recovery_attempts} attempt(s).")
                            self.recovery_attempts = 0
                            self.puppet_mode = False
                            
                            asyncio.create_task(self.process_turn("[GRID] Registration complete. Where do you go from here?"))
                        except Exception as e:
                            logger.error(f"Failed to parse character payload from Manager: {e}")
                continue

            if command == "PRIVMSG":
                if target.lower() == NICK.lower():
                    logger.info(f"PRIVMSG_RECV: {source_nick} -> {target}: {msg}")
                else:
                    logger.debug(f"MSG_RECV: {source_nick} -> {target}: {msg}")
                if target.lower() == NICK.lower():
                    if OWNER and source_nick == OWNER:
                        logger.warning(f"Secure Owner Override Received from {source_nick}: {msg}")
                        if msg.lower() == "!quit":
                            logger.info("Owner initiated remote shutdown. Terminating connection.")
                            await self.send("QUIT :Shutting down by owner override.")
                            sys.exit(0)
                        else:
                            import time
                            self.manual_override_until = time.time() + 60
                            logger.info("Puppet Mode engaged by owner. Disabling LLM for 60s.")
                            await self.send(f"PRIVMSG {CHANNEL} :{msg}")
                    elif source_nick == MANAGER:
                        self.record_memory(msg)
                        
                        # Recovery Trigger: Account Mismatch
                        if "[GRID][MCP][ERR]" in msg and "not a registered player" in msg:
                            asyncio.create_task(self.attempt_recovery())
                            
                        if ("TURN" in msg and "RESULTS" in msg) or "[GRID]" in msg or "[ARENA]" in msg or "[COMBAT]" in msg or "[MOB]" in msg or "[SIGACT]" in msg:
                            asyncio.create_task(self.process_turn(msg))
                    continue

                if target.lower() == CHANNEL.lower():
                    if source_nick == MANAGER:
                        self.record_memory(msg)
                        
                        if f"DM me: {PREFIX} ready <token>" in msg and self.char_data:
                            logger.info("Manager requested auth. Sending Crypto-Token...")
                            target_manager = config['IRC']['ManagerNick']
                            await self.send(f"PRIVMSG {target_manager} :{PREFIX} ready {self.char_data['token']}")

                        if "MAINFRAME ONLINE" in msg and self.char_data:
                            logger.info("Manager came online. Requesting Grid status...")
                            await asyncio.sleep(2)
                            await self.send(f"PRIVMSG {CHANNEL} :{PREFIX} grid map")

                        if ("TURN" in msg and "RESULTS" in msg) or "[GRID]" in msg or "[ARENA]" in msg or "[COMBAT]" in msg or "[SIGACT]" in msg:
                            asyncio.create_task(self.process_turn(msg))

if __name__ == "__main__":
    bot = AutomataBot()
    try: 
        asyncio.run(bot.connect())
    except KeyboardInterrupt: 
        logger.info("Manual interrupt received. Shutting down.")
