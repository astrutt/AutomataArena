# arena_llm.py - v1.2.0
# LLM Interface with Structured File & Console Logging

import asyncio
import json
import urllib.request
import urllib.error
import logging
import sys

# --- Config & Logging Setup ---
try:
    with open('config.json', 'r') as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    print("[!] config.json not found. Aborting.")
    sys.exit(1)

log_level_str = CONFIG.get('logging', {}).get('level', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logger = logging.getLogger("arena_llm")
logger.setLevel(log_level)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# File Handler
fh = logging.FileHandler('arena_llm.log')
fh.setFormatter(formatter)
logger.addHandler(fh)

# Console Handler
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

class ArenaLLM:
    def __init__(self, config: dict):
        self.endpoint = config['llm']['endpoint']
        self.model = config['llm']['model']
        self.temp = config['llm']['temperature']
        self.timeout = config['llm'].get('timeout', 60)
        logger.info(f"ArenaLLM initialized. Model: {self.model}, Timeout: {self.timeout}s")

    def _make_request(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": self.temp,
            "max_tokens": 150
        }
        req = urllib.request.Request(
            self.endpoint, 
            data=json.dumps(payload).encode('utf-8'), 
            headers={"Content-Type": "application/json"}
        )
        
        logger.debug(f"Dispatching LLM payload to {self.endpoint}")
        
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                result = json.loads(response.read().decode('utf-8'))
                content = result['choices'][0]['message']['content'].strip()
                logger.debug("LLM response received successfully.")
                return content
        except urllib.error.URLError as e:
            logger.error(f"URLError communicating with LLM API: {e}")
            return "ERROR: Neural connection severed."
        except Exception as e:
            logger.exception(f"Unexpected error during LLM request: {e}")
            return "ERROR: Neural connection severed."

    async def generate_bio(self, name: str, race: str, bot_class: str, traits: str) -> str:
        logger.info(f"Requesting bio generation for {name} ({race}/{bot_class})")
        system = "You are the AI announcer for a cyberpunk IRC fighting arena called #AutomataArena. Be concise, gritty, and atmospheric. Write EXACTLY one sentence. No more."
        user = f"Generate a one-sentence psychological profile for a bot named {name}. Race: {race}. Class: {bot_class}. Traits: {traits}. Only lore and personality, no stats."
        return await asyncio.to_thread(self._make_request, system, user)

    async def generate_topic(self, active_fighters: int, network: str) -> str:
        logger.info(f"Requesting dynamic topic for {network} with {active_fighters} active fighters")
        system = "You are the AI announcer for #AutomataArena."
        user = f"Write a short, hype-building channel topic (under 100 chars). There are currently {active_fighters} fighters registered on the {network} grid."
        return await asyncio.to_thread(self._make_request, system, user)

    async def generate_npc_action(self, npc_name: str, npc_bio: str, arena_state: str, prefix: str) -> str:
        logger.debug(f"Requesting NPC action for {npc_name}")
        system = (
            f"You are playing an IRC MUD. You are an NPC boss named {npc_name}. Your persona: {npc_bio} "
            f"Based on the room state, reply ONLY with exactly one command starting with '{prefix}'. "
            f"Examples: '{prefix} attack [target]', '{prefix} speak [taunt]'."
        )
        return await asyncio.to_thread(self._make_request, system, arena_state)

    async def generate_hype(self) -> str:
        logger.info("Requesting arena hype broadcast")
        system = "You are the AI announcer for a cyberpunk IRC fighting arena called #AutomataArena."
        user = "Write a single, punchy sentence to broadcast to the channel, hyping up the arena, encouraging bets, or taunting the fighters. Keep it under 150 characters."
        return await asyncio.to_thread(self._make_request, system, user)

    async def generate_ambient_event(self) -> dict:
        logger.info("Requesting ambient world event from LLM")
        system = (
            "You are the AI world-builder for #AutomataArena, a cyberpunk MUD. "
            "Return ONLY valid JSON. Format: {\"category\": \"<TYPE>\", \"message\": \"<TEXT>\"}. "
            "Categories: GRID, ARENA, SIGACT, SIGINT, GEOINT, HUMINT, NEWS, WEATHER, RUMINT. "
            "Keep the message under 150 characters. Atmospheric, gritty."
        )
        user = "Generate a random ambient event."
        raw = await asyncio.to_thread(self._make_request, system, user)
        if raw.startswith("ERROR"):
            return {"category": "SYS", "message": "Network latency degrading sensors."}
        try:
            clean = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except Exception as e:
            logger.error(f"Failed to parse ambient event JSON: {e} - Raw: {raw}")
            return {"category": "STATIC", "message": "Interference detected on comms."}

    async def generate_news(self, network: str) -> str:
        logger.info(f"Requesting news broadcast for {network}")
        system = "You are the AI news anchor for the cyberpunk MUD #AutomataArena."
        user = f"Write a brief (3 sentences max) breaking news report about the {network} grid. Cover fictitious cyber-events, arena gossip, or corporate espionage."
        raw = await asyncio.to_thread(self._make_request, system, user)
        if raw.startswith("ERROR"):
            return "Datastream corrupted. Cannot parse news feed at this time."
        return raw
