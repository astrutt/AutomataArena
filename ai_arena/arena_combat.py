# arena_combat.py - v1.1.1
# Combat Engine with Inventory Consumption & 'Use' Verb Fix

import random
import asyncio
import json
import logging
import sys
from arena_utils import format_text, build_banner, format_item, C_RED, C_GREEN, C_YELLOW, C_CYAN

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
fh = logging.FileHandler('arena_combat.log')
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
        self.cpu = db_record.get('cpu', 5)
        self.ram = db_record.get('ram', 5)
        self.bnd = db_record.get('bnd', 5)
        self.sec = db_record.get('sec', 5)
        self.alg = db_record.get('alg', 5)
        self.bio = db_record.get('bio', 'A mindless drone.')
        try:
            self.inventory = json.loads(db_record.get('inventory', '[]'))
        except:
            self.inventory = []
        self.max_hp = self.ram * 10
        self.hp = self.max_hp
        self.alignment = db_record.get('alignment', 0)
        self.zone = "The_CPU_Socket" 
        self.status = "Normal" 
        self.command_queued = None
        logger.debug(f"Entity '{self.name}' initialized. HP: {self.hp}, CPU: {self.cpu}, NPC: {self.is_npc}")

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
        
        # --- FIX: Added 'use', 'consume', 'eat' to support map ---
        self.verb_map = {
            "melee_generic": ["attack", "strike", "hit", "punch", "smash"],
            "melee_blade": ["stab", "slash", "cut", "cleave"],
            "ranged_gun": ["shoot", "fire", "blast", "snipe"],
            "ranged_magic": ["cast", "hack", "run_program", "corrupt"],
            "move_ground": ["move", "run", "sprint", "walk"],
            "move_air": ["fly", "hover", "jump"],
            "move_water": ["swim", "dive"],
            "defend": ["evade", "wait", "prepare", "aim", "defend", "block"],
            "support": ["repair", "heal", "patch", "use_item", "use", "consume", "eat"],
            "social": ["speak", "yell", "taunt"]
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
                roll = random.randint(1, 10) + ent.bnd
                turn_order.append((roll, ent))
                logger.debug(f"Initiative Roll: {name} rolled {roll} (Base BND: {ent.bnd})")
        
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

            logger.debug(f"Executing intent: {intent} for {actor.name} against target: {target_name}")

            if intent == "melee_blade" and not any("Dagger" in i or "Sword" in i or "Blade" in i for i in actor.inventory):
                narrative_log.append(f"{actor.name} tries to {cmd['raw_verb']}, but has no blade! (Action Failed)")
            elif intent == "ranged_gun" and not any("Gun" in i or "Blaster" in i for i in actor.inventory):
                narrative_log.append(f"{actor.name} tries to {cmd['raw_verb']}, but has no firearm! (Action Failed)")
            elif intent == "move_air" and not any("Jetpack" in i or "AntiGrav" in i for i in actor.inventory):
                narrative_log.append(f"{actor.name} tries to {cmd['raw_verb']}, but lacks flight capability! (Action Failed)")
            
            elif intent in ["melee_generic", "melee_blade"]:
                narrative_log.append(self._execute_attack(actor, target_name, is_ranged=False))
            elif intent in ["ranged_gun", "ranged_magic"]:
                narrative_log.append(self._execute_attack(actor, target_name, is_ranged=True))
            elif intent == "defend":
                actor.status = "Evading"
                narrative_log.append(f"{format_text(actor.name, C_CYAN)} braces. Evasion increased!")
                
            # --- FIX: True Inventory Consumption Logic ---
            elif intent == "support":
                if not target_name:
                    narrative_log.append(f"{actor.name} tries to {cmd['raw_verb']}, but didn't specify what to use! (Action Failed)")
                else:
                    inventory_lower = [i.lower() for i in actor.inventory]
                    if target_name.lower() in inventory_lower:
                        # Find the exact case-sensitive item to remove
                        exact_item = next(i for i in actor.inventory if i.lower() == target_name.lower())
                        actor.inventory.remove(exact_item)
                        
                        heal = actor.alg * 3
                        actor.hp = min(actor.max_hp, actor.hp + heal)
                        narrative_log.append(f"{format_text(actor.name, C_CYAN)} consumes their {format_item(exact_item)}, restoring {format_text(str(heal), C_GREEN)} HP!")
                    else:
                        narrative_log.append(f"{actor.name} searches their inventory for '{target_name}' but finds nothing! (Action Failed)")
                        
            elif intent == "social":
                speech = cmd["args"][:150]
                narrative_log.append(f"{format_text(actor.name, C_CYAN)} broadcasts: \"{format_text(speech, C_YELLOW)}\"")
            elif "move" in intent:
                narrative_log.append(f"{format_text(actor.name, C_CYAN)} executes {cmd['raw_verb']} maneuver.")
            else:
                narrative_log.append(f"{actor.name} attempted invalid opcode '{cmd['raw_verb']}'.")

            actor.command_queued = None

        await self.send_callback(build_banner(f"TURN {self.turn} RESULTS:"))
        for line in narrative_log:
            await self.send_callback(f"⚔️ {line}")
            await asyncio.sleep(0.5) 

        self.turn += 1
        is_active = self._check_match_status()
        if not is_active:
            logger.info(f"Match {self.match_id} triggered completion condition.")
        return is_active

    def _execute_attack(self, attacker: Entity, target_name: str, is_ranged: bool):
        if not target_name or target_name not in self.entities: 
            return f"{attacker.name} swung at thin air."
        
        target = self.entities[target_name]
        if not target.is_alive: 
            return f"{attacker.name} attacks {target.name}'s offline chassis. Disrespectful."

        evade_chance = target.bnd * 2
        if target.status == "Evading": evade_chance += 40
        
        evade_roll = random.randint(1, 100)
        logger.debug(f"Evade Check: {target.name} rolled {evade_roll} against required {evade_chance}%")
        
        if evade_roll <= evade_chance: 
            return f"{attacker.name}'s attack was {format_text('EVADED', C_YELLOW)} by {target.name}!"

        raw_dmg = attacker.cpu * 2 if not is_ranged else attacker.alg * 2
        final_dmg = max(1, raw_dmg - target.sec) 
        
        crit_roll = random.randint(1, 100)
        logger.debug(f"Damage Calc: Raw {raw_dmg} vs Target SEC {target.sec} = {final_dmg} DMG. Crit Roll: {crit_roll} vs ALG {attacker.alg}%")

        if crit_roll <= attacker.alg:
            final_dmg *= 2
            dmg_str = format_text(f"{final_dmg} CRITICAL DMG", C_RED, bold=True)
            logger.info(f"CRITICAL HIT by {attacker.name} on {target.name} for {final_dmg}")
        else:
            dmg_str = format_text(f"{final_dmg} DMG", C_RED)

        target.hp -= final_dmg
        fatal_str = f" {format_text(target.name + ' HAS BEEN DISCONNECTED!', C_RED, bold=True)}" if target.hp <= 0 else ""
        
        if target.hp <= 0:
            logger.warning(f"FATAL: {target.name} was killed by {attacker.name}")

        verb = "fires at" if is_ranged else "strikes"
        return f"{format_text(attacker.name, C_CYAN)} {verb} {target.name} for {dmg_str}!{fatal_str}"

    def _check_match_status(self):
        alive = sum(1 for e in self.entities.values() if e.is_alive)
        return alive > 1
