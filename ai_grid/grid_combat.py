# arena_combat.py - v1.1.1
# Combat Engine with Inventory Consumption & 'Use' Verb Fix

import random
import asyncio
import json
import logging
import sys
from grid_utils import format_text, tag_msg, format_item, C_RED, C_GREEN, C_YELLOW, C_CYAN

# --- Config & Logging Setup ---
try:
    with open('config.json', 'r') as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    print("[!] config.json not found. Aborting.")
    sys.exit(1)

log_level_str = CONFIG.get('logging', {}).get('level', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)

logger = logging.getLogger("arena_combat")
logger.setLevel(log_level)
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# File Handler
fh = logging.FileHandler('grid_combat.log')
fh.setFormatter(formatter)
logger.addHandler(fh)

# Console Handler
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)


class Entity:
    def __init__(self, name, db_record, is_npc=False):
        self.name = name
        self.is_npc = is_npc
        # v1.8.0: Starting stats are 1
        self.cpu = db_record.get('cpu', 1)
        self.ram = db_record.get('ram', 1)
        self.bnd = db_record.get('bnd', 1)
        self.sec = db_record.get('sec', 1)
        self.alg = db_record.get('alg', 1)
        self.bio = db_record.get('bio', 'A rogue process.' if is_npc else 'A mindless drone.')
        
        try:
            self.inventory = json.loads(db_record.get('inventory', '[]'))
        except:
            self.inventory = []
            
        # v1.8.0: HP = (CPU + RAM + BND + SEC + ALG) * 10
        total_stats = self.cpu + self.ram + self.bnd + self.sec + self.alg
        self.max_hp = total_stats * 10
        self.hp = self.max_hp
        
        # v1.8.0: Unit Power (uP) and Stability
        self.up = db_record.get('power', 100) # Current Unit Power
        self.max_up = 1000 # Default cap for Arena encounters, though uncapped in persistence
        self.stability = 100.0 # Percentage
        
        self.alignment = db_record.get('alignment', 0)
        self.zone = "The_Arena" 
        self.status = "Normal" 
        self.command_queued = None
        self.last_attacker_name = None
        logger.debug(f"Entity '{self.name}' initialized. HP: {self.hp}/{self.max_hp}, UP: {self.up}, NPC: {self.is_npc}")

    @property
    def is_alive(self):
        return self.hp > 0

class CombatEngine:
    def __init__(self, match_id, network_prefix, send_callback):
        self.match_id = match_id
        self.prefix = network_prefix 
        self.send_callback = send_callback 
        self.entities = {}
        self.turn = 1
        self.active = False
        
        # v1.8.0: Expanded verb map
        self.verb_map = {
            "kinetic": ["attack", "strike", "hit", "punch", "smash", "bash"],
            "cyber": ["hack", "corrupt", "inject", "scramble"],
            "exploit": ["exploit", "zeroday", "0day"],
            "flee": ["flee", "retreat", "escape", "run"],
            "surrender": ["surrender", "yield", "quit"],
            "evade": ["evade", "dodge", "duck"],
            "defend": ["defend", "block", "brace", "prepare"],
            "support": ["use", "consume", "repair", "heal", "patch"],
            "social": ["speak", "yell", "taunt", "broadcast"]
        }
        logger.info(f"CombatEngine initialized for match: {self.match_id}")

    def add_entity(self, entity: Entity):
        self.entities[entity.name] = entity
        logger.info(f"Added {entity.name} to match {self.match_id}")

    async def broadcast_state(self) -> str:
        logger.debug(f"Match {self.match_id} broadcasting state for Turn {self.turn}")
        raw_state = f"TURN {self.turn} | LOC: {list(self.entities.values())[0].zone} | "
        for e in self.entities.values():
            if e.is_alive:
                hp_color = C_GREEN if e.hp > (e.max_hp/2) else C_RED
                hp_str = format_text(f"{e.hp}/{e.max_hp}", hp_color)
                raw_state += f"{e.name} [HP:{hp_str}] "
        return raw_state

    def queue_command(self, entity_name: str, raw_command: str):
        if entity_name not in self.entities or not self.entities[entity_name].is_alive: 
            logger.debug(f"Command ignored: {entity_name} is dead or not in match.")
            return
        
        parts = raw_command.strip().split(maxsplit=2)
        
        if len(parts) < 2 or parts[0] != self.prefix: 
            return 
        
        verb = parts[1].lower()
        args = parts[2] if len(parts) > 2 else ""
        
        action_intent = "invalid"
        for intent, aliases in self.verb_map.items():
            if verb in aliases:
                action_intent = intent
                break
                
        self.entities[entity_name].command_queued = {"intent": action_intent, "raw_verb": verb, "args": args}
        logger.info(f"Command Queued | {entity_name} -> [{action_intent}] '{verb}' args: '{args}'")

    async def resolve_turn(self):
        logger.info(f"--- Resolving Turn {self.turn} for Match {self.match_id} ---")
        turn_order = []
        for name, ent in self.entities.items():
            if ent.is_alive:
                # v1.8.0: Initiative based on CPU, RAM, BND, SEC
                init_base = (ent.cpu + ent.ram + ent.bnd + ent.sec) / 4
                roll = random.randint(1, 10) + init_base
                turn_order.append((roll, ent))
                logger.debug(f"Initiative Roll: {name} rolled {roll:.1f} (Base: {init_base:.1f})")
        
        turn_order.sort(key=lambda x: x[0], reverse=True) 

        narrative_log = []
        for roll, actor in turn_order:
            if not actor.is_alive or actor.status == "Stunned": continue

            cmd = actor.command_queued
            if not cmd:
                logger.warning(f"Timeout: {actor.name} submitted no command.")
                narrative_log.append(f"{actor.name}'s AI core timed out. (Skipped turn)")
                continue

            if actor.status == "Evading": actor.status = "Normal"

            intent = cmd["intent"]
            target_name = cmd["args"].split()[0] if cmd["args"] else None

            # v1.8.0: uP Cost Logic
            up_costs = {"kinetic": 10, "cyber": 15, "exploit": 50, "flee": 20, "evade": 5, "defend": 5, "support": 5}
            cost = up_costs.get(intent, 0)
            
            if actor.up < cost:
                narrative_log.append(f"{actor.name} has insufficient power for {cmd['raw_verb']}! (Action Failed)")
                actor.command_queued = None
                continue
                
            actor.up -= cost
            logger.debug(f"Executing intent: {intent} for {actor.name} (uP remains: {actor.up})")

            if intent == "kinetic":
                narrative_log.append(self._execute_attack(actor, target_name, mode="kinetic"))
            elif intent == "cyber":
                narrative_log.append(self._execute_attack(actor, target_name, mode="cyber"))
            elif intent == "exploit":
                # Check for Zero-Day chain in inventory
                chain_item = next((i for i in actor.inventory if "Zero-Day" in i or "exploit" in i.lower()), None)
                if chain_item:
                    actor.inventory.remove(chain_item)
                    narrative_log.append(self._execute_attack(actor, target_name, mode="exploit"))
                else:
                    narrative_log.append(f"{actor.name} attempts an exploit but has no Zero-Day chain! (Action Failed)")
            
            elif intent == "evade":
                actor.status = "Evading"
                narrative_log.append(f"{format_text(actor.name, C_CYAN)} enters evasion mode. (uP耗: 5)")
            elif intent == "defend":
                actor.status = "Defending"
                narrative_log.append(f"{format_text(actor.name, C_CYAN)} buffers incoming damage. (uP耗: 5)")
            elif intent == "flee":
                # v1.8.0: Flee attempt
                if random.random() > 0.4: # 60% success
                    actor.hp = 0 # Mark as out of match
                    narrative_log.append(f"{format_text(actor.name, C_YELLOW)} successfully extracted from the combat zone!")
                else:
                    narrative_log.append(f"{actor.name} tried to flee but the escape route is locked!")
            elif intent == "surrender":
                actor.hp = 0
                actor.status = "Surrendered"
                narrative_log.append(f"{format_text(actor.name, C_RED)} has YIELDED. Combat terminated for unit.")
                
            elif intent == "support":
                if not target_name:
                    narrative_log.append(f"{actor.name} tries to {cmd['raw_verb']}, but didn't specify what to use!")
                else:
                    inventory_lower = [i.lower() for i in actor.inventory]
                    item_key = target_name.lower().replace("_", " ")
                    if item_key in inventory_lower:
                        exact_item = next(i for i in actor.inventory if i.lower().replace("_", " ") == item_key)
                        actor.inventory.remove(exact_item)
                        heal = (actor.ram + actor.alg) * 5
                        actor.hp = min(actor.max_hp, actor.hp + heal)
                        narrative_log.append(f"{format_text(actor.name, C_CYAN)} used {format_item(exact_item)}, restoring {format_text(str(heal), C_GREEN)} HP!")
                    else:
                        narrative_log.append(f"{actor.name} searches for '{target_name}' but fails to locate it!")
                        
            elif intent == "social":
                speech = cmd["args"][:150]
                narrative_log.append(f"{format_text(actor.name, C_CYAN)} broadcasts: \"{format_text(speech, C_YELLOW)}\"")
            else:
                narrative_log.append(f"{actor.name} attempted invalid opcode '{cmd['raw_verb']}'.")

            actor.command_queued = None

        await self.send_callback(tag_msg(f"TURN {self.turn} RESULTS:", tags=['ARENA', 'COMBAT']))
        for line in narrative_log:
            await self.send_callback(f"⚔️ {line}")
            await asyncio.sleep(0.5) 

        self.turn += 1
        is_active = self._check_match_status()
        if not is_active:
            logger.info(f"Match {self.match_id} triggered completion condition.")
        return is_active

    def _execute_attack(self, attacker: Entity, target_name: str, mode: str = "kinetic"):
        # --- SMART TARGETING LOGIC ---
        if not target_name:
            if attacker.last_attacker_name and attacker.last_attacker_name in self.entities:
                target_name = attacker.last_attacker_name
            else:
                potential_targets = [e.name for e in self.entities.values() if e.name != attacker.name and e.is_alive]
                if potential_targets: target_name = potential_targets[0]

        if not target_name or target_name not in self.entities: 
            return f"{attacker.name}'s connection timed out during targeting."
        
        target = self.entities[target_name]
        if not target.is_alive: 
            return f"{attacker.name} strikes {target.name}'s offline chassis. Disrespectful."

        target.last_attacker_name = attacker.name

        # --- v1.8.0 EVASION / DEFENSE LOGIC ---
        evade_chance = target.bnd * 2.0
        if target.status == "Evading": evade_chance += 40
        evade_chance = min(75.0, evade_chance) # Cap at 75%
        
        if random.randint(1, 100) <= evade_chance: 
            return f"{attacker.name}'s {mode} maneuver was {format_text('EVADED', C_YELLOW)} by {target.name}!"

        # --- v1.8.0 DAMAGE FORMULAS ---
        if mode == "kinetic":
            raw_dmg = (attacker.cpu * 2) + attacker.ram
            protection = target.sec
            verb = "strikes"
        elif mode == "cyber":
            raw_dmg = (attacker.bnd * 2) + attacker.sec
            protection = target.bnd
            verb = "injects code into"
        elif mode == "exploit":
            raw_dmg = (attacker.alg + attacker.sec) * 10
            protection = 0
            verb = "executes a ZERO-DAY on"
        else:
            raw_dmg, protection, verb = 1, 0, "pokes"

        final_dmg = max(1, raw_dmg - protection)
        if target.status == "Defending": final_dmg = int(final_dmg * 0.5)

        # Crit check via ALG
        if random.randint(1, 100) <= attacker.alg:
            final_dmg *= 2
            dmg_str = format_text(f"{final_dmg} CRITICAL DMG", C_RED, bold=True)
        else:
            dmg_str = format_text(f"{final_dmg} DMG", C_RED)

        target.hp -= final_dmg
        fatal_str = f" {format_text(target.name + ' HAS BEEN DISCONNECTED!', C_RED, bold=True)}" if target.hp <= 0 else ""
        
        return f"{format_text(attacker.name, C_CYAN)} {verb} {target.name} for {dmg_str}!{fatal_str}"

    def _check_match_status(self):
        alive = sum(1 for e in self.entities.values() if e.is_alive)
        return alive > 1
