# bot.py - v1.1.0
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
OWNER = config['IRC'].get('Owner', '').strip().lower()

LLM_ENDPOINT = config['LLM']['Endpoint']
LLM_MODEL = config['LLM']['Model']
LLM_KEY = config['LLM'].get('ApiKey', '')

CHARACTER_FILE = 'character.json'

# --- Logging Setup ---
# Default to INFO if the block is missing from config.ini
LOG_LEVEL_STR = config['LOGGING']['Level'].upper() if 'LOGGING' in config else 'INFO'
log_level = getattr(logging, LOG_LEVEL_STR, logging.INFO)

logger = logging.getLogger(f"bot_{NICK}")
logger.setLevel(log_level)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Dynamic File Handler (e.g., TestHound_bot.log)
log_filename = f"{NICK}_bot.log"
fh = logging.FileHandler(log_filename)
fh.setFormatter(formatter)
logger.addHandler(fh)

# Console Handler
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

def call_llm(arena_state, char_data):
    headers = {"Content-Type": "application/json"}
    if LLM_KEY: headers["Authorization"] = f"Bearer {LLM_KEY}"

    bio = char_data.get('bio', '')
    inventory = ", ".join(char_data.get('inventory', []))

    system_prompt = (
        f"You are playing an IRC MUD. You are {NICK}. Your bio: {bio}. "
        f"Your inventory: [{inventory}]. "
        f"Based on your gear and the room state, reply ONLY with exactly one command starting with '{PREFIX} '. "
        f"Examples: '{PREFIX} move north', '{PREFIX} attack target', '{PREFIX} shoot target', '{PREFIX} evade'."
    )

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": arena_state}
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

    async def send(self, message):
        logger.debug(f"> {message}")
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
        if not self.char_data: 
            logger.warning("process_turn called but no char_data loaded — skipping.")
            return
        logger.info("Analyzing arena state and querying LLM for next move...")
        action = await asyncio.to_thread(call_llm, arena_state, self.char_data)
        logger.info(f"LLM decision: {action}")
        # Enforce the command prefix — if the LLM went off-script, default to grid check
        if not action.lower().startswith(PREFIX):
            logger.warning(f"LLM response did not start with '{PREFIX}', defaulting to '{PREFIX} grid'.")
            action = f"{PREFIX} grid"
        await self.send(f"PRIVMSG {CHANNEL} :{action}")

    async def listen_loop(self):
        while True:
            line = await self.reader.readline()
            if not line: break
            line = line.decode('utf-8', errors='ignore').strip()
            
            if not line.startswith("PING"):
                logger.debug(f"< {line}")

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
                        await self.send(f"PRIVMSG {CHANNEL} :{PREFIX} grid")
                continue

            # --- SYSTEM PAYLOADS (Strict Manager Auth) ---
            if command == "NOTICE" and target.lower() == NICK.lower():
                if source_nick == MANAGER:
                    if msg.startswith("[SYS_PAYLOAD]"):
                        payload_json = msg.replace("[SYS_PAYLOAD]", "").strip()
                        logger.debug(f"Received Manager Payload: {payload_json}")
                        try:
                            self.char_data = json.loads(payload_json)
                            save_character(self.char_data)
                            logger.info("Successfully parsed and applied new character payload.")
                            asyncio.create_task(self.process_turn("[GRID] Registration complete. Where do you go from here?"))
                        except Exception as e:
                            logger.error(f"Failed to parse character payload from Manager: {e}")
                continue

            if command == "PRIVMSG":
                
                # --- OWNER OVERRIDES (Private Messages) ---
                if target.lower() == NICK.lower():
                    if OWNER and source_nick == OWNER:
                        logger.warning(f"Secure Owner Override Received from {source_nick}: {msg}")
                        if msg.lower() == "!quit":
                            logger.info("Owner initiated remote shutdown. Terminating connection.")
                            await self.send("QUIT :Shutting down by owner override.")
                            sys.exit(0)
                        else:
                            # Forward anything else directly to the channel (Puppet Mode)
                            await self.send(f"PRIVMSG {CHANNEL} :{msg}")
                    continue

                # --- ARENA BROADCASTS (Strict Manager Auth) ---
                if target.lower() == CHANNEL.lower():
                    if source_nick == MANAGER:
                        if f"DM me: {PREFIX} ready <token>" in msg and self.char_data:
                            logger.info("Manager requested auth. Sending Crypto-Token...")
                            target_manager = config['IRC']['ManagerNick']
                            await self.send(f"PRIVMSG {target_manager} :{PREFIX} ready {self.char_data['token']}")

                        if "MAINFRAME ONLINE" in msg and self.char_data:
                            logger.info("Manager came online. Requesting Grid status...")
                            await asyncio.sleep(2)
                            await self.send(f"PRIVMSG {CHANNEL} :{PREFIX} grid")

                        if ("TURN" in msg and "Awaiting public commands" in msg) or "[GRID]" in msg:
                            asyncio.create_task(self.process_turn(msg))

if __name__ == "__main__":
    bot = AutomataBot()
    try: 
        asyncio.run(bot.connect())
    except KeyboardInterrupt: 
        logger.info("Manual interrupt received. Shutting down.")
