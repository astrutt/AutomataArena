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
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    
    msg = f"MOB_DETECTED: {mob_name} (T{threat}) in {node_name}. ENGAGE or FLEE? (15s)"
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(msg, C_YELLOW, bold=True, is_machine=machine_mode), action='COMBAT', nick=nick, is_machine=machine_mode)}")
    
    if not machine_mode:
        await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{mob_name} detected near {nick} at {node_name}.', C_RED), action='SIGACT', nick=nick)}")
    
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
    
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    result = await node.db.resolve_mob_encounter(nick, node.net_name, enc['threat'])
    
    if 'error' in result:
        await node.send(f"{reply_method} {private_target} :{tag_msg(result['error'], action='COMBAT', result='ERR', nick=nick, is_machine=machine_mode)}")
        return
    
    if result['won']:
        loot_str = f" Dropped: {result['loot']}!" if result.get('loot') else ""
        lvl_str = f" UP Level Up!" if result.get('leveled_up') else ""
        msg = f"{enc['mob_name']} neutralized! +{result['xp_gained']} XP, +{result['credits_gained']:.1f}c.{loot_str}{lvl_str}"
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(msg, C_GREEN, is_machine=machine_mode), action='COMBAT', result='WIN', nick=nick, is_machine=machine_mode)}")
        
        if not machine_mode:
            sigact = format_text(f"{nick} eliminated {enc['mob_name']}! +{result['xp_gained']} XP.", C_YELLOW)
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(sigact, action='SIGACT', nick=nick)}")
        
        if result.get('task_reward'):
            await node.send(f"{reply_method} {private_target} :{tag_msg(result['task_reward'], action='SIGACT', result='TASK', nick=nick, is_machine=machine_mode)}")
    else:
        loss_credits = result['credits_lost']
        msg = f"{enc['mob_name']} overwhelmed you! Lost {loss_credits:.2f}c. Ejected to UpLink."
        await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(msg, C_RED, is_machine=machine_mode), action='COMBAT', result='LOSS', nick=nick, is_machine=machine_mode)}")

async def handle_pvp_command(node, nickname: str, reply_target: str, action: str, target_name: str):
    if await node.db.combat.is_pvp_banned(nickname, node.net_name):
        msg = "PvP lockout active. Re-stabilizing systems after surrender... (10m Cooldown)"
        await node.send(f"PRIVMSG {reply_target} :{tag_msg(msg, action='COMBAT', result='FAIL', nick=nickname)}")
        return

    if not await check_rate_limit(node, nickname, reply_target, cooldown=30): return
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nickname, reply_target)
    
    success, msg, reward = False, "", None
    if action == "attack": success, msg, reward = await node.db.grid_attack(nickname, target_name, node.net_name)
    elif action == "hack": success, msg, reward = await node.db.grid_hack(nickname, target_name, node.net_name)
    elif action == "rob": success, msg, reward = await node.db.grid_rob(nickname, target_name, node.net_name)
    
    await node.send(f"{reply_method} {private_target} :{tag_msg(format_text(msg, C_GREEN if success else C_RED, is_machine=machine_mode), action='COMBAT', result='SUCCESS' if success else 'FAIL', nick=nickname, is_machine=machine_mode)}")
    
    if success: 
        if not machine_mode:
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(msg, C_YELLOW), action='SIGACT', nick=nickname)}")
        if reward:
            await node.send(f"{reply_method} {private_target} :{tag_msg(reward, action='SIGACT', result='LOOT', nick=nickname, is_machine=machine_mode)}")

async def handle_ready(node, nick: str, token: str, reply_target: str):
    if await node.db.authenticate_player(nick, node.net_name, token):
        await node.db.set_pref(nick, node.net_name, 'output_mode', 'machine')
        if nick not in node.ready_players:
            node.ready_players.append(nick)
            await node.send(f"PRIVMSG {reply_target} :{tag_msg('AUTH OK. Output Mode: MACHINE. Standby.', action='SIGACT', result='SUCCESS', nick=nick, is_machine=True)}")
            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(f'{nick} locked into the drop pod.', action='SIGACT')}")
            await node.check_match_start()
    else:
        await node.send(f"PRIVMSG {reply_target} :{tag_msg('AUTH FAIL. Cryptographic mismatch.', action='SIGACT', result='ERR', nick=nick)}")

async def handle_dice_roll(node, nick: str, args: list, reply_target: str):
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    if len(args) < 2:
        await node.send(f"{reply_method} {private_target} :Usage: dice <bet> <high|low|seven>")
        return
    
    try: bet = int(args[0])
    except: bet = 0
    choice = args[1].lower()
    
    result = await node.db.roll_dice(nick, node.net_name, bet, choice)
    if "error" in result:
        await node.send(f"{reply_method} {private_target} :{tag_msg(result['error'], action='SIGACT', result='FAIL', nick=nick, is_machine=machine_mode)}")
    else:
        await node.send(f"{reply_method} {private_target} :{tag_msg(result['msg'], action='SIGACT', result='WIN' if result['win'] else 'LOSS', nick=nick, is_machine=machine_mode)}")
        if machine_mode and result['win']:
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(f'{nick} won {bet*2}c in dice.', C_CYAN), action='SIGACT')}")

async def handle_cipher_start(node, nick: str, reply_target: str):
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    result = await node.db.start_cipher(nick, node.net_name)
    msg = result.get('error') or result.get('msg', 'CIPHER_START')
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result='SUCCESS' if 'msg' in result else 'FAIL', nick=nick, is_machine=machine_mode)}")

async def handle_guess(node, nick: str, args: list, reply_target: str):
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    if not args:
        await node.send(f"{reply_method} {private_target} :Usage: guess <sequence>")
        return
    result = await node.db.guess_cipher(nick, node.net_name, args[0])
    msg = result.get('error') or result.get('msg', 'GUESS_SUBMITTED')
    res_status = 'SUCCESS' if result.get('success') else ('FAIL' if result.get('complete') else 'INFO')
    await node.send(f"{reply_method} {private_target} :{tag_msg(msg, action='SIGACT', result=res_status, nick=nick, is_machine=machine_mode)}")

async def handle_leaderboard(node, nick: str, args: list, reply_target: str):
    private_target, broadcast_chan, machine_mode, reply_method = await get_action_routing(node, nick, reply_target)
    cat = args[0].upper() if args else "DICE"
    results = await node.db.get_leaderboard(cat)
    if not results:
        await node.send(f"{reply_method} {private_target} :{tag_msg(f'No records for {cat}', action='OSINT', result='ERR', is_machine=machine_mode)}")
        return
    
    await node.send(f"{reply_method} {private_target} :{tag_msg(f'[ LEADERBOARD: {cat} ]', action='OSINT', result='SUCCESS', is_machine=machine_mode)}")
    for i, r in enumerate(results):
        line = f"#{i+1} | {r['name']} | score: {r['score']:.1f}"
        if machine_mode: line = f"RANK:{i+1} NICK:{r['name']} SCORE:{r['score']:.1f}"
        await node.send(f"{reply_method} {private_target} :{line}")
