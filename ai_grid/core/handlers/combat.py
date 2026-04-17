# handlers/combat.py - Combat, PvP & Mini-Game Handlers
import asyncio
import random
import logging
from grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode, check_rate_limit, get_action_routing

logger = logging.getLogger("manager")

async def handle_mob_encounter(node, nick: str, node_name: str, threat: int, prev_node: str, reply_target: str):
    mob = node.db.combat.MOB_ROSTER.get(threat, node.db.combat.MOB_ROSTER[1])
    mob_name = mob['name']
    
    tactical_target, broadcast_chan, machine, tactical_cmd = await get_action_routing(node, nick, reply_target)
    
    if machine:
        warn = f"[MOB] THREAT:{threat} NAME:{mob_name} NODE:{node_name} ENGAGE:{node.prefix} engage FLEE:{node.prefix} flee TIMEOUT:15"
        await node.send(f"{tactical_cmd} {tactical_target} :{warn}")
    else:
        warn = format_text(f"⚠️ [MOB DETECTED] {mob_name} (Threat {threat}) lurks in {node_name}! Type '{node.prefix} engage' to fight or '{node.prefix} flee' to retreat. (15s)", C_YELLOW, bold=True)
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(warn, tags=['COMBAT', nick], location=node_name)}")
    
    await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{mob_name} detected near {nick} at {node_name}.', C_RED), tags=['SIGACT'])}")
    async def auto_engage():
        try:
            await asyncio.sleep(15)
            if nick in node.pending_encounters:
                asyncio.create_task(resolve_mob(node, nick, reply_target))
        except asyncio.CancelledError: pass
    timer = asyncio.create_task(auto_engage())
    node.pending_encounters[nick] = {'mob_name': mob_name, 'threat': threat, 'prev_node': prev_node, 'timer': timer, 'reply_target': reply_target}

async def resolve_mob(node, nick: str, reply_target: str):
    enc = node.pending_encounters.pop(nick, None)
    if not enc: return
    enc['timer'].cancel()
    
    tactical_target, broadcast_chan, machine, tactical_cmd = await get_action_routing(node, nick, reply_target)
    
    result = await node.db.resolve_mob_encounter(nick, node.net_name, enc['threat'])
    if 'error' in result:
        await node.send(f"{tactical_cmd} {tactical_target} :[ERR] {result['error']}")
        return
    
    if result['won']:
        loot_str = f" Dropped: {result['loot']}!" if result.get('loot') else ""
        lvl_str = f" 🆙 Level Up!" if result.get('leveled_up') else ""
        
        if machine:
            # Tactical (PM/Notice)
            parts = f"[MOB] RESULT:WIN XP:{result['xp_gained']} CRED:+{result['credits_gained']}"
            if result.get('loot'): parts += f" LOOT:{result['loot']}"
            if result.get('leveled_up'): parts += " LEVELUP:true"
            await node.send(f"{tactical_cmd} {tactical_target} :{parts}")
            
            # Narrative (Channel)
            narrative = format_text(f"{nick} neutralized {enc['mob_name']}! +{result['xp_gained']} XP, +{result['credits_gained']}c.{loot_str}{lvl_str}", C_YELLOW)
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(narrative, tags=['SIGACT'])}")
        else:
            # Human Mode: Standard aesthetic delivery
            msg = format_text(f"✅ {enc['mob_name']} neutralized! +{result['xp_gained']} XP, +{result['credits_gained']}c.{loot_str}{lvl_str}", C_GREEN)
            await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(msg, tags=['COMBAT', nick])}")
        
        if result.get('task_reward'):
            await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(result['task_reward'], C_CYAN), tags=['SIGACT', nick])}")
    else:
        if machine:
            await node.send(f"{tactical_cmd} {tactical_target} :[MOB] RESULT:LOSS CRED:-{result['credits_lost']} EJECTED:UpLink")
            narrative = format_text(f"{nick} was overwhelmed by {enc['mob_name']} and ejected to UpLink.", C_RED)
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(narrative, tags=['SIGACT'])}")
        else:
            loss_credits = result['credits_lost']
            msg = format_text(f"💀 {enc['mob_name']} overwhelmed you! Lost {loss_credits:.2f}c. Ejected to UpLink.", C_RED)
            await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(msg, tags=['COMBAT', nick])}")

async def handle_pvp_command(node, nickname: str, reply_target: str, action: str, target_name: str):
    if not await check_rate_limit(node, nickname, reply_target, cooldown=30): return
    success, msg, reward = False, "", None
    
    tactical_target, broadcast_chan, machine, tactical_cmd = await get_action_routing(node, nickname, reply_target)
    
    if action == "attack": success, msg, reward = await node.db.grid_attack(nickname, target_name, node.net_name)
    elif action == "hack": success, msg, reward = await node.db.grid_hack(nickname, target_name, node.net_name)
    elif action == "rob": success, msg, reward = await node.db.grid_rob(nickname, target_name, node.net_name)
    
    if success: 
        if machine:
            # Tactical (PM/Notice)
            pvp_parts = f"[PVP] ACTION:{action.upper()} TARGET:{target_name} RESULT:SUCCESS MSG:{msg}"
            await node.send(f"{tactical_cmd} {tactical_target} :{pvp_parts}")
            # Narrative (Channel)
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(msg, C_YELLOW), tags=['SIGACT', 'COMBAT'])}")
        else:
            await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(msg, C_YELLOW), tags=['SIGACT', 'COMBAT'])}")
            
        if reward:
            await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(reward, C_CYAN), tags=['SIGACT', nickname])}")
    else: 
        if msg == "System offline.":
            await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nickname} - not a registered player - msg ignored")
        else:
            if machine:
                await node.send(f"{tactical_cmd} {tactical_target} :[PVP] ACTION:{action.upper()} TARGET:{target_name} RESULT:FAIL MSG:{msg}")
            else:
                await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(msg, C_RED), tags=['COMBAT', nickname])}")

async def handle_ready(node, nick: str, token: str, reply_target: str):
    if await node.db.authenticate_fighter(nick, node.net_name, token):
        await node.db.set_pref(nick, node.net_name, 'output_mode', 'machine')
        if nick not in node.ready_players:
            node.ready_players.append(nick)
            await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'[AUTH OK] {nick} validated. Output mode set to MACHINE. Standby for drop.', C_GREEN), tags=['SIGACT', nick])}")
            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(f'{nick} locked into the drop pod.', C_YELLOW), tags=['SIGACT'])}")
            await node.check_match_start()
    else:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'[AUTH FAIL] {nick} Cryptographic mismatch.', C_RED), tags=['SIGACT', nick])}")

async def handle_dice_roll(node, nick: str, args: list, reply_target: str):
    """Play a game of 2d6 dice."""
    tactical_target, broadcast_chan, machine, tactical_cmd = await get_action_routing(node, nick, reply_target)
    
    if len(args) < 2:
        await node.send(f"{tactical_cmd} {tactical_target} :Usage: {node.prefix} dice <bet> <high|low|seven>")
        return
    
    try: bet = int(args[0])
    except: bet = 0
    choice = args[1].lower()
    
    if choice not in ["high", "low", "seven"]:
        await node.send(f"{tactical_cmd} {tactical_target} :Choice must be high (8-12), low (2-6), or seven.")
        return

    result = await node.db.roll_dice(nick, node.net_name, bet, choice)
    if "error" in result:
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(result['error'], C_RED), tags=['SIGACT', nick])}")
    else:
        banner = format_text(result['msg'], C_GREEN if result['win'] else C_YELLOW)
        await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(banner, tags=['SIGACT', nick])}")
        if machine and result['win']:
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nick} won {bet*2}c in a high stakes dice game!', C_CYAN), tags=['SIGACT'])}")

async def handle_cipher_start(node, nick: str, reply_target: str):
    """Start a CipherLock session."""
    result = await node.db.start_cipher(nick, node.net_name)
    if "error" in result:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(result['error'], C_RED), tags=['SIGACT', nick])}")
    else:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(result['msg'], C_YELLOW), tags=['SIGACT', nick])}")

async def handle_guess(node, nick: str, args: list, reply_target: str):
    """Submit a CipherLock guess."""
    if not args:
        await node.send(f"PRIVMSG {reply_target} :Usage: {node.prefix} guess <4-digit-sequence>")
        return
        
    result = await node.db.guess_cipher(nick, node.net_name, args[0])
    if "error" in result:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(result['error'], C_RED), tags=['SIGACT', nick])}")
    else:
        color = C_GREEN if result.get('complete') and result.get('success') else C_YELLOW
        if result.get('complete') and not result.get('success'): color = C_RED
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(result['msg'], color), tags=['SIGACT', nick])}")

async def handle_leaderboard(node, nick: str, args: list, reply_target: str):
    """Show global high scores."""
    tactical_target, broadcast_chan, machine, tactical_cmd = await get_action_routing(node, nick, reply_target)
    cat = args[0].upper() if args else "DICE"
    results = await node.db.get_leaderboard(cat)
    if not results:
        await node.send(f"{tactical_cmd} {tactical_target} :[GRID] No records found for category: {cat}")
        return
    
    if machine:
        parts = " ".join(f"{r['name']}:{r['score']:.1f}" for r in results)
        await node.send(f"{tactical_cmd} {tactical_target} :[TOP] CAT:{cat} LIST:{parts}")
        return
    await node.send(f"{tactical_cmd} {tactical_target} :{tag_msg(format_text(f'[ LEADERBOARD: {cat} ]', C_CYAN, True), tags=['OSINT'], is_machine=machine)}")
    for i, r in enumerate(results):
        line = f"#{i+1} | {r['name']} | score: {r['score']:.1f}"
        await node.send(f"{tactical_cmd} {tactical_target} :{line}")
