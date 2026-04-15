# handlers.py - v1.5.0
import asyncio
import logging
import json
import random
import textwrap
import time
from grid_utils import format_text, build_banner, ICONS, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .map_utils import generate_ascii_map

logger = logging.getLogger("manager")

# --- Utility Handlers ---

async def handle_help(node, nick: str, args: list, reply_target: str):
    """Displays a comprehensive list of all v1.6.0 commands or details for a specific verb."""
    
    # Detailed Command Registry
    registry = {
        "register": {"desc": "Found your digital persona.", "syntax": "register <Name> <Race> <Class> <Traits>"},
        "grid": {"desc": "Diagnostic view of the current node.", "syntax": "grid"},
        "move": {"desc": "Travel to an adjacent node.", "syntax": "move <n/s/e/w>"},
        "explore": {"desc": "Scan sector for hidden architecture or fragments.", "syntax": "explore", "cost": "20u Power"},
        "map": {"desc": "Generate topological visualization. Radius scales with SEC/ALG.", "syntax": "map"},
        "info": {"desc": "Targeted diagnostics.", "syntax": "info [grid|arena|<nick>]"},
        "tasks": {"desc": "View active objectives and harvest rewards.", "syntax": "tasks"},
        "options": {"desc": "Set terminal preferences (e.g., machine mode).", "syntax": "options <key> <val>"},
        "shop": {"desc": "View local merchant wares.", "syntax": "shop"},
        "buy": {"desc": "Purchase hardware/software from a Merchant node.", "syntax": "buy <item>"},
        "sell": {"desc": "Liquidate inventory items for credits.", "syntax": "sell <item>"},
        "auction": {"desc": "Global DarkNet marketplace.", "syntax": "auction <list|bid|post> [id|item] [amt|price]"},
        "market": {"desc": "View economic volatility and price multipliers.", "syntax": "market"},
        "mainframe": {"desc": "Check Gibson compilation/assembly status.", "syntax": "mainframe"},
        "compile": {"desc": "Synthesize 100 Data into 1 Vulnerability.", "syntax": "compile <amt>"},
        "assemble": {"desc": "Fuse 4 Vulnerabilities into 1 Zero-Day Chain.", "syntax": "assemble"},
        "use": {"desc": "Execute an inventory payload.", "syntax": "use <item>"},
        "claim": {"desc": "Establish command over an Unclaimed node.", "syntax": "claim", "cost": "50u Power"},
        "upgrade": {"desc": "Fortify node security and storage capacity.", "syntax": "upgrade", "cost": "100u Power + Credits"},
        "repair": {"desc": "Restore node durability.", "syntax": "repair", "cost": "25u Power"},
        "recharge": {"desc": "Transfer character reserves to the node pool.", "syntax": "recharge <amt>"},
        "hack": {"desc": "Sabotage foreign node integrity or siphon data.", "syntax": "hack", "cost": "30u Power"},
        "raid": {"desc": "Rapid resource extraction from a local node.", "syntax": "raid"},
        "breach": {"desc": "Brute-force entry into high-sec architectures.", "syntax": "breach"},
        "guess": {"desc": "Submit a decryption sequence code.", "syntax": "guess <code>"},
        "dice": {"desc": "PvP credit gambling.", "syntax": "dice <amt> <nick>"},
        "top": {"desc": "View global High Roller leaderboards.", "syntax": "top"},
        "attack": {"desc": "Primary kinetic strike against another Persona.", "syntax": "attack <nick>"},
        "rob": {"desc": "Siphon credits from an unsuspecting target.", "syntax": "rob <nick>"},
        "queue": {"desc": "Register for the next Arena gladiator match.", "syntax": "queue"},
        "ready": {"desc": "Commit to an arena drop sequence.", "syntax": "ready <token>"}
    }

    if args:
        verb = args[0].lower()
        if verb in registry:
            info = registry[verb]
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[ COMMAND: {verb.upper()} ]', C_CYAN, True))}")
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('DESCRIPTION: ', C_YELLOW) + format_text(info['desc'], C_WHITE))}")
            syntax_str = f"{node.prefix} {info['syntax']}"
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('SYNTAX: ', C_YELLOW) + format_text(syntax_str, C_GREEN))}")
            if 'cost' in info:
                await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('COST: ', C_YELLOW) + format_text(info['cost'], C_RED))}")
            return
        else:
            await node.send(f"PRIVMSG {reply_target} :[ERR] Command '{verb}' not found in registry.")

    # Generic Categorical Help
    help_categories = {
        "🧭 NAVIGATION": ["grid", "move", "explore", "map"],
        "🆔 IDENTITY": ["register", "info", "tasks", "options"],
        "💰 ECONOMY": ["shop", "buy/sell", "auction", "market"],
        "🏗️ THE GIBSON": ["mainframe", "compile", "assemble", "use"],
        "⚔️ TACTICAL": ["claim", "upgrade", "hack/raid", "repair"],
        "🎮 GAMES": ["cipher/guess", "dice", "top", "attack/rob", "queue/ready"]
    }

    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ AUTOMATA ARENA v1.6.0 - COMMAND INTERFACE ]', C_CYAN, bold=True))}")
    for cat, cmds in help_categories.items():
        cmd_str = ", ".join([f"{node.prefix} {c}" for c in cmds])
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(cat, C_YELLOW) + ': ' + format_text(cmd_str, C_WHITE))}")

    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Type {node.prefix} help <command> for detailed syntax.', C_CYAN))}")

async def is_machine_mode(node, nick: str) -> bool:
    prefs = await node.db.get_prefs(nick, node.net_name)
    return prefs.get('output_mode', 'human') == 'machine'

async def check_rate_limit(node, nick: str, reply_target: str, cooldown: int = 30) -> bool:
    now = time.time()
    if nick not in node.action_timestamps:
        node.action_timestamps[nick] = {'last_action': now, 'warnings': 0}
        return True
        
    record = node.action_timestamps[nick]
    elapsed = now - record['last_action']
    if elapsed < cooldown:
        record['warnings'] += 1
        if record['warnings'] > 3:
            return False
        else:
            msg = format_text(f"[SYSTEM] Anti-flood ICE triggered. Please wait {cooldown - int(elapsed)}s.", C_RED)
            await node.send(f"PRIVMSG {reply_target} :{build_banner(msg)}")
            return False
    record['last_action'] = now
    record['warnings'] = 0
    return True

# --- Core Handlers ---

async def handle_registration(node, nick: str, args: list, reply_target: str):
    try:
        if len(args) < 4:
            await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} register <Name> <Race> <Class> <Traits>")
            return
        bot_name, race, b_class = args[0], args[1], args[2]
        traits = " ".join(args[3:])
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Compiling architecture for {bot_name}...', C_GREEN))}")
        bio = await node.llm.generate_bio(bot_name, race, b_class, traits)
        if len(bio) > 200: bio = bio[:197] + "..."
        stats = {'cpu': 5, 'ram': 5, 'bnd': 5, 'sec': 5, 'alg': 5}
        auth_token = await node.db.register_fighter(bot_name, node.net_name, race, b_class, bio, stats)
        if auth_token:
            payload = json.dumps({"token": auth_token, "bio": bio, "stats": stats, "inventory": ["Basic_Ration"]})
            await node.send(f"NOTICE {bot_name} :[SYS_PAYLOAD] {payload}")
            announcement = f"{ICONS.get(race, '⚙️')} {format_text(bot_name, C_CYAN, True)} the {ICONS.get(b_class, '⚔️')} {b_class} has entered the Grid!"
            await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(announcement)}")
            await node.set_dynamic_topic()
        else:
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Registration failed: Identity {bot_name!r} is already registered.', C_RED))}")
    except Exception as e:
        logger.exception("Error in handle_registration")
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('CRITICAL ERROR during registration sequence.', C_RED))}")

async def handle_grid_movement(node, nick: str, direction: str, reply_target: str):
    prev_node = None
    loc = await node.db.get_location(nick, node.net_name)
    if loc: prev_node = loc['name']
    node_name, msg = await node.db.move_fighter(nick, node.net_name, direction)
    if node_name:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[GRID] {msg}', C_GREEN))}")
        await handle_grid_view(node, nick, reply_target)
        new_loc = await node.db.get_location(nick, node.net_name)
        if new_loc and new_loc.get('node_type') == 'wilderness':
            threat = new_loc.get('threat_level', 0)
            if threat > 0:
                spawn_chance = 0.60 if threat >= 3 else 0.35
                if random.random() < spawn_chance:
                    await handle_mob_encounter(node, nick, node_name, threat, prev_node, reply_target)
    else:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[ERR] {msg}', C_RED))}")
        await handle_grid_view(node, nick, reply_target)

async def handle_mob_encounter(node, nick: str, node_name: str, threat: int, prev_node: str, reply_target: str):
    mob = node.db.combat.MOB_ROSTER.get(threat, node.db.combat.MOB_ROSTER[1])
    mob_name = mob['name']
    machine = await is_machine_mode(node, nick)
    if machine:
        warn = f"[MOB] THREAT:{threat} NAME:{mob_name} NODE:{node_name} ENGAGE:{node.prefix} engage FLEE:{node.prefix} flee TIMEOUT:15"
        await node.send(f"PRIVMSG {nick} :{warn}")
    else:
        warn = format_text(f"⚠️ [MOB DETECTED] {mob_name} (Threat {threat}) lurks in {node_name}! Type '{node.prefix} engage' to fight or '{node.prefix} flee' to retreat. (15s)", C_YELLOW, bold=True)
        await node.send(f"PRIVMSG {reply_target} :{build_banner(warn)}")
    await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] {mob_name} detected near {nick} at {node_name}.', C_RED))}")
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
    result = await node.db.resolve_mob_encounter(nick, node.net_name, enc['threat'])
    if 'error' in result:
        await node.send(f"PRIVMSG {reply_target} :[ERR] {result['error']}")
        return
    machine = await is_machine_mode(node, nick)
    if result['won']:
        if machine:
            parts = f"[MOB] RESULT:WIN XP:{result['xp_gained']} CRED:+{result['credits_gained']}"
            if result.get('loot'): parts += f" LOOT:{result['loot']}"
            if result.get('leveled_up'): parts += " LEVELUP:true"
            await node.send(f"PRIVMSG {nick} :{parts}")
        else:
            loot_str = f" Dropped: {result['loot']}!" if result.get('loot') else ""
            lvl_str = f" 🆙 Level Up!" if result.get('leveled_up') else ""
            msg = format_text(f"✅ {enc['mob_name']} neutralized! +{result['xp_gained']} XP, +{result['credits_gained']}c.{loot_str}{lvl_str}", C_GREEN)
            await node.send(f"PRIVMSG {reply_target} :{build_banner(msg)}")
        sigact = format_text(f"[SIGACT] {nick} eliminated {enc['mob_name']}! +{result['xp_gained']} XP.", C_YELLOW)
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(sigact)}")
        if result.get('task_reward'):
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(result['task_reward'], C_CYAN))}")
    else:
        if machine:
            await node.send(f"PRIVMSG {nick} :[MOB] RESULT:LOSS CRED:-{result['credits_lost']} EJECTED:The_Grid_Uplink")
        else:
            loss_credits = result['credits_lost']
            msg = format_text(f"💀 {enc['mob_name']} overwhelmed you! Lost {loss_credits:.2f}c. Ejected to The_Grid_Uplink.", C_RED)
            await node.send(f"PRIVMSG {reply_target} :{build_banner(msg)}")

async def handle_ready(node, nick: str, token: str, reply_target: str):
    if await node.db.authenticate_fighter(nick, node.net_name, token):
        await node.db.set_pref(nick, node.net_name, 'output_mode', 'machine')
        if nick not in node.ready_players:
            node.ready_players.append(nick)
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[AUTH OK] {nick} validated. Output mode set to MACHINE. Standby for drop.', C_GREEN))}")
            await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] {nick} locked into the drop pod.', C_YELLOW))}")
            await node.check_match_start()
    else:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[AUTH FAIL] {nick} Cryptographic mismatch.', C_RED))}")

async def handle_powergen(node, nick: str, reply_target: str):
    if not await check_rate_limit(node, nick, reply_target, cooldown=60): return
    success, msg = await node.db.active_powergen(nick, node.net_name)
    banner = format_text(msg, C_GREEN if success else C_RED)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
    if success:
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] {nick} initiated an active power generation cycle.', C_CYAN))}")

async def handle_training(node, nick: str, reply_target: str):
    if not await check_rate_limit(node, nick, reply_target, cooldown=60): return
    success, msg = await node.db.active_training(nick, node.net_name)
    banner = format_text(msg, C_GREEN if success else C_RED)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
    if success:
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] {nick} completed a structural maintenance drill.', C_CYAN))}")

async def handle_node_explore(node, nick: str, reply_target: str):
    if not await check_rate_limit(node, nick, reply_target, cooldown=45): return
    result = await node.db.explore_node(nick, node.net_name)
    
    if "error" in result:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(result['error'], C_RED))}")
        return
    
    banner = format_text(result['msg'], C_GREEN if result['status'] == 'success' else C_YELLOW)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
    
    if result.get("danger") == "GRID_BUG_SPAWN":
        # Manually trigger a mob encounter with a Level 0 Grid Bug
        loc = await node.db.get_location(nick, node.net_name)
        await handle_mob_encounter(node, nick, loc['name'], 0, None, reply_target)
    
    if result['status'] == 'success':
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] Grid Discovery: {nick} uncovered architectural secrets at their current position!', C_CYAN))}")

async def handle_gibson_status(node, nick: str, reply_target: str):
    """View status of Gibson mainframe tasks."""
    data = await node.db.get_gibson_status(nick, node.net_name)
    if "error" in data:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(data['error'], C_RED))}")
        return
    
    machine = await is_machine_mode(node, nick)
    if machine:
        tasks = ",".join([f"{t['type']}:{t['remaining_sec']}s" for t in data['active_tasks']]) or "none"
        await node.send(f"PRIVMSG {nick} :[GIBSON] DATA:{data['data']:.1f} VULNS:{data['vulns']} ZD:{data['zero_days']} HARVEST:{data['harvest_rate']:.1f} TASKS:{tasks}")
        return

    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ MAINFRAME UI: THE GIBSON ]', C_CYAN, True))}")
    storage = f"Raw Data: {data['data']:.1f} | Vulns: {data['vulns']} | Zero-Days: {data['zero_days']}"
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(storage, C_GREEN))}")
    
    perf = f"Global Harvest Rate: {data['harvest_rate']:.1f} uP/tick | Character Power: {data['character_power']:.1f}"
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(perf, C_YELLOW))}")
    
    if data['active_tasks']:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('--- ACTIVE TASKS ---', C_CYAN))}")
        for t in data['active_tasks']:
            m, s = divmod(t['remaining_sec'], 60)
            line = f"[{t['type']}] Yielding {t['amount']} units | ETA: {m}m {s}s"
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(line, C_GREEN))}")
    else:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('Mainframe Idle. Ready for compilation.', C_CYAN))}")

async def handle_gibson_compile(node, nick: str, args: list, reply_target: str):
    """Start compilation task."""
    try: amount = int(args[0]) if args else 100
    except: amount = 100
    
    result = await node.db.start_compilation(nick, node.net_name, amount)
    if "error" in result:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(result['error'], C_RED))}")
    else:
        banner = format_text(result['msg'], C_GREEN)
        await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
        usage = f"Power Consumed: {result['node_used']:.1f} (Node) | {result['char_used']:.1f} (Char)"
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(usage, C_YELLOW))}")

async def handle_gibson_assemble(node, nick: str, reply_target: str):
    """Start assembly task."""
    result = await node.db.start_assembly(nick, node.net_name)
    if "error" in result:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(result['error'], C_RED))}")
    else:
        banner = format_text(result['msg'], C_GREEN)
        await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
        usage = f"Power Consumed: {result['node_used']:.1f} (Node) | {result['char_used']:.1f} (Char)"
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(usage, C_YELLOW))}")

async def handle_item_use(node, nick: str, args: list, reply_target: str):
    """Consume an item for a boost."""
    if not args:
        await node.send(f"PRIVMSG {reply_target} :Usage: {node.prefix} use <item_name>")
        return
    
    item_name = " ".join(args)
    # This would typically be in economy_repo or player_repo
    # For now, let's implement the specific Phase 4 boosts
    result, msg = await node.db.use_item(nick, node.net_name, item_name)
    banner = format_text(msg, C_GREEN if result else C_RED)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")

# --- PHASE 5: GLOBAL ECONOMY & MINI-GAMES ---

async def handle_auction(node, nick: str, args: list, reply_target: str):
    """DarkNet Auction sub-commands: list, sell, bid."""
    if not args:
        await node.send(f"PRIVMSG {reply_target} :Usage: {node.prefix} auction <list|sell|bid>")
        return
    
    sub = args[0].lower()
    if sub == "list":
        listings = await node.db.list_active_auctions()
        if not listings:
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[DARKNET] The auction house is currently empty.', C_CYAN))}")
            return
        
        machine = await is_machine_mode(node, nick)
        if machine:
            parts = " ".join(f"ID:{l['id']}|ITEM:{l['item']}|BID:{l['current_bid']}|END:{l['ends_in_min']}m" for l in listings)
            await node.send(f"PRIVMSG {nick} :[AUCTION] LIST:{parts}")
            return

        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ GLOBAL DARKNET AUCTIONS ]', C_CYAN, True))}")
        for l in listings:
            line = f"#{l['id']} | {l['item']} | Seller: {l['seller']} | Bid: {l['current_bid']}c | {l['high_bidder']} | Ends: {l['ends_in_min']}m"
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(line, C_GREEN))}")
            
    elif sub == "sell" and len(args) >= 3:
        # !a auction sell <item> <start_bid>
        item_name = args[1]
        try: start_bid = int(args[2])
        except: start_bid = 100
        
        success, msg = await node.db.create_auction(nick, node.net_name, item_name, start_bid, 1440)
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(msg, C_GREEN if success else C_RED))}")
        
    elif sub == "bid" and len(args) >= 3:
        # !a auction bid <id> <amount>
        try:
            aid = int(args[1])
            amt = int(args[2])
        except:
            await node.send(f"PRIVMSG {reply_target} :Usage: {node.prefix} auction bid <id> <amount>")
            return
            
        success, msg = await node.db.bid_on_auction(nick, node.net_name, aid, amt)
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(msg, C_GREEN if success else C_RED))}")
    else:
        await node.send(f"PRIVMSG {reply_target} :Invalid auction command. Try: list, sell <item> <bid>, or bid <id> <amount>.")

async def handle_dice_roll(node, nick: str, args: list, reply_target: str):
    """Play a game of 2d6 dice."""
    if len(args) < 2:
        await node.send(f"PRIVMSG {reply_target} :Usage: {node.prefix} dice <bet> <high|low|seven>")
        return
    
    try: bet = int(args[0])
    except: bet = 0
    choice = args[1].lower()
    
    if choice not in ["high", "low", "seven"]:
        await node.send(f"PRIVMSG {reply_target} :Choice must be high (8-12), low (2-6), or seven.")
        return

    result = await node.db.roll_dice(nick, node.net_name, bet, choice)
    if "error" in result:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(result['error'], C_RED))}")
    else:
        banner = format_text(result['msg'], C_GREEN if result['win'] else C_YELLOW)
        await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")

async def handle_cipher_start(node, nick: str, reply_target: str):
    """Start a CipherLock session."""
    result = await node.db.start_cipher(nick, node.net_name)
    if "error" in result:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(result['error'], C_RED))}")
    else:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(result['msg'], C_YELLOW))}")

async def handle_guess(node, nick: str, args: list, reply_target: str):
    """Submit a CipherLock guess."""
    if not args:
        await node.send(f"PRIVMSG {reply_target} :Usage: {node.prefix} guess <4-digit-sequence>")
        return
        
    result = await node.db.guess_cipher(nick, node.net_name, args[0])
    if "error" in result:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(result['error'], C_RED))}")
    else:
        color = C_GREEN if result.get('complete') and result.get('success') else C_YELLOW
        if result.get('complete') and not result.get('success'): color = C_RED
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(result['msg'], color))}")

async def handle_market_view(node, nickname: str, reply_target: str):
    """View current global market multipliers."""
    status = await node.db.get_market_status()
    if not status:
        await node.send(f"PRIVMSG {reply_target} :[MARKET] Market is currently stable (1.0x baseline).")
        return
    
    machine = await is_machine_mode(node, nickname)
    if machine:
        parts = " ".join(f"{k}:{v:.2f}" for k, v in status.items())
        await node.send(f"PRIVMSG {nickname} :[MARKET] MULTS:{parts}")
        return
        
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ GLOBAL MARKET CONDITIONS ]', C_CYAN, True))}")
    for itype, mult in status.items():
        trend = "↑ INFLATION" if mult > 1.0 else ("↓ DEFLATION" if mult < 1.0 else "→ STABLE")
        color = C_RED if mult > 1.0 else (C_GREEN if mult < 1.0 else C_YELLOW)
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'{itype.upper()}: {mult:.2f}x | {trend}', color))}")

async def handle_leaderboard(node, nick: str, args: list, reply_target: str):
    """Show global high scores."""
    cat = args[0].upper() if args else "DICE"
    results = await node.db.get_leaderboard(cat)
    if not results:
        await node.send(f"PRIVMSG {reply_target} :[GRID] No records found for category: {cat}")
        return
    
    machine = await is_machine_mode(node, nick)
    if machine:
        parts = " ".join(f"{r['name']}:{r['score']:.1f}" for r in results)
        await node.send(f"PRIVMSG {nick} :[TOP] CAT:{cat} LIST:{parts}")
        return

    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'[ LEADERBOARD: {cat} ]', C_CYAN, True))}")
    for i, r in enumerate(results):
        line = f"#{i+1} | {r['name']} | score: {r['score']:.1f}"
        await node.send(f"PRIVMSG {reply_target} :{target} :Sub-command '{sub}' not recognized.")

async def handle_grid_map(node, nick: str, reply_target: str):
    """Render the ASCII grid map."""
    async with node.db.async_session() as session:
        # Get character for stats
        char = await node.db.get_character_by_nick(nick, node.net_name, session)
        if not char:
            await node.send(f"PRIVMSG {reply_target} :[ERR] Persona offline.")
            return
        
        # Calculate radius: (SEC + ALG) / 10
        radius = max(1, int((char.sec + char.alg) / 10))
        # Bonus for items? (Handled in radius calculation if needed)
        
        machine = await is_machine_mode(node, nick)
        if machine:
            # We need a data-only version of the grid map. I'll perform a simplified BFS here
            # or extract logic from map_utils in a future refactor. For now, we'll parse the grid dictionary.
            from .map_utils import generate_ascii_map # We'll use a hack to get the raw data if we refactored, but since I haven't, 
            # I will implement the machine-friendly output based on the same BFS logic
            grid_data = []
            queue = [(char.current_node, 0, 0, 0)]
            visited = {char.node_id}
            # Simplified BFS to match map_utils topology
            idx = 0
            while idx < len(queue):
                curr, x, y, dist = queue[idx]
                idx += 1
                grid_data.append(f"{x},{y}:{curr.node_type}")
                if dist >= radius: continue
                from sqlalchemy.future import select
                from models import NodeConnection
                from sqlalchemy.orm import selectinload
                stmt = select(NodeConnection).where(NodeConnection.source_node_id == curr.id).options(selectinload(NodeConnection.target_node))
                conns = (await session.execute(stmt)).scalars().all()
                for conn in conns:
                    if conn.is_hidden: continue
                    tx, ty, d = x, y, conn.direction.lower()
                    if d=='north': ty-=1
                    elif d=='south': ty+=1
                    elif d=='east': tx+=1
                    elif d=='west': tx-=1
                    else: continue
                    if conn.target_node.id not in visited:
                        visited.add(conn.target_node.id)
                        queue.append((conn.target_node, tx, ty, dist+1))
            
            await node.send(f"PRIVMSG {nick} :[MAP] R:{radius} NODES:{'|'.join(grid_data)}")
            return

        map_text = await generate_ascii_map(session, char, radius)
        
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ TERMINAL NODAL TOPOLOGY ]', C_CYAN, True))}")
        for line in map_text.split("\n"):
            await node.send(f"PRIVMSG {reply_target} :{build_banner(line)}")

async def handle_grid_loot(node, nick: str, reply_target: str):
    if not await check_rate_limit(node, nick, reply_target, cooldown=60): return
    result = await node.db.raid_node(nick, node.net_name)
    
    banner = format_text(result['msg'], C_GREEN if result['success'] else C_RED)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
    
    if result['success']:
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(result['sigact'], C_YELLOW, True))}")

async def handle_grid_network_msg(node, nick: str, args: list, reply_target: str):
    if len(args) < 3:
        await node.send(f"PRIVMSG {reply_target} :Syntax: {node.prefix} grid network msg <nick> <msg>")
        return
        
    target_nick = args[1]
    message = " ".join(args[2:])
    
    loc = await node.db.get_location(nick, node.net_name)
    if not loc or not loc.get('irc_affinity'):
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('System Error: This node lacks a synchronized IRC bridge.', C_RED))}")
        return
        
    target_net = loc['irc_affinity']
    # Format the message to include the sender's origin
    formatted_msg = format_text(f"[CROSS-GRID] <{nick}@{node.net_name}> {message}", C_CYAN)
    
    success = await node.hub.relay_message(target_net, target_nick, formatted_msg)
    if success:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Packet successfully relayed to {target_net} node.', C_GREEN))}")
    else:
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Packet transmission failed: Network {target_net} is currently unreachable.', C_RED))}")

async def handle_merchant_tx(node, nickname: str, verb: str, item_name: str, reply_target: str):
    result, msg = await node.db.process_transaction(nickname, node.net_name, verb, item_name)
    banner = format_text(msg, C_GREEN if result else C_RED)
    if reply_target.startswith(('#', '&', '+', '!')):
        await node.send(f"PRIVMSG {reply_target} :{build_banner(banner)}")
    else:
        await node.send(f"PRIVMSG {reply_target} :{msg}")
    if result:
        act = "purchased" if verb == "buy" else "liquidated"
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] {nickname} {act} equipment on the Black Market.', C_CYAN))}")

async def handle_grid_view(node, nickname: str, reply_target: str):
    loc = await node.db.get_location(nickname, node.net_name)
    if not loc:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Fighter not found.")
        return
    machine = await is_machine_mode(node, nickname)
    if machine:
        exits = ",".join(loc['exits']) if loc['exits'] else "none"
        line = f"NODE:{loc['name']} TYPE:{loc['type']} OWNER:{loc.get('owner','none')} LVL:{loc['level']} EXITS:{exits} POWER:{loc['power_stored']}/{loc['upgrade_level']*100} DUR:{loc.get('durability',100):.0f}"
        await node.send(f"PRIVMSG {nickname} :[GRID] {line}")
        return
    node_icon = {'safezone': '🛡️', 'arena': '⚔️', 'wilderness': '🌿', 'merchant': '💰'}.get(loc['type'], '📡')
    exits_str = " | ".join(loc['exits']) if loc['exits'] else "none"
    header = format_text(f"[ {node_icon} {loc['name']} ]", C_CYAN, bold=True)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(header)}")
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(loc['description'], C_YELLOW))}")
    node_stats = f"Type: {loc['type'].upper()} | Level: {loc['level']} | Credits: {loc['credits']}c"
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(node_stats, C_GREEN))}")
    
    # Phase 3: Metadata display
    meta_str = f"Integrity: {loc.get('visibility_mode', 'OPEN')}"
    if loc.get('visibility_mode') == 'OPEN' and loc.get('irc_affinity'):
        meta_str += f" | Network: {loc['irc_affinity'].upper()}"
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(meta_str, C_CYAN))}")

    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Exits: {exits_str}', C_CYAN))}")
    action_prompt = format_text(f"[GRID] {nickname} @ {loc['name']} | Use '{node.prefix} move <dir>' to travel.", C_YELLOW)
    if loc['type'] == 'arena': action_prompt += format_text(f" | Use '{node.prefix} queue' to enter the Arena.", C_GREEN)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(action_prompt)}")

async def handle_shop_view(node, nickname: str, reply_target: str):
    items = await node.db.list_shop_items()
    if not items:
        await node.send(f"PRIVMSG {reply_target} :[SHOP] The marketplace is empty.")
        return
    machine = await is_machine_mode(node, nickname)
    if machine:
        parts = " ".join(f"{i['name']}:{i['cost']}c" for i in items)
        await node.send(f"PRIVMSG {nickname} :[SHOP] ITEMS:{parts}")
        return
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ BLACK MARKET WARES ]', C_CYAN, bold=True))}")
    for i in items:
        line = f"{i['name']} ({i['type']}) - {i['cost']}c"
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(line, C_GREEN))}")
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'To buy, travel to a Merchant node and type {node.prefix} buy <item>.', C_YELLOW))}")

async def handle_news_view(node, nickname: str, reply_target: str):
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ ESTABLISHING SECURE UPLINK TO NEWS SERVER... ]', C_YELLOW))}")
    news_text = await node.llm.generate_news(node.net_name)
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ BREAKING NEWS REPORT ]', C_CYAN, bold=True))}")
    for line in textwrap.wrap(news_text, width=200):
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(line, C_YELLOW))}")

async def handle_info_view(node, nickname: str, args: list, reply_target: str):
    target = args[0].lower() if args else nickname.lower()
    machine = await is_machine_mode(node, nickname)
    if target == "grid":
        loc = await node.db.get_location(nickname, node.net_name)
        if loc:
            if machine:
                exits = ",".join(loc['exits']) if loc['exits'] else "none"
                await node.send(f"PRIVMSG {nickname} :[INFO] NODE:{loc['name']} TYPE:{loc['type']} OWNER:{loc.get('owner','none')} LVL:{loc['upgrade_level']} EXITS:{exits} POWER:{loc['power_stored']}/{loc['upgrade_level']*100} DUR:{loc.get('durability',100):.0f}")
            else:
                msg = f"[GRID INFO] {loc['name']}"
                banner = build_banner(format_text(msg, C_CYAN, bold=True))
                await node.send(f"PRIVMSG {reply_target} :{banner}")
                node_meta = f"Type: {loc['type'].upper()} | Owner: {loc['owner']} | Security Lvl: {loc['upgrade_level']}"
                await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(node_meta, C_YELLOW))}")
                power_meta = f"Power Generated: {loc['power_generated']} | Consumed: {loc['power_consumed']} | Stored: {loc['power_stored']}"
                await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(power_meta, C_GREEN))}")
        else: await node.send(f"PRIVMSG {reply_target} :[ERR] You must be on the grid.")
    elif target == "arena":
        q_len, r_len = len(node.match_queue), len(node.ready_players)
        b_stat = f"ACTIVE (Turn {node.active_engine.turn})" if node.active_engine and node.active_engine.active else "STANDBY"
        if machine: await node.send(f"PRIVMSG {nickname} :[INFO] ARENA_STATUS:{b_stat} QUEUE:{q_len} READY:{r_len}")
        else:
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ARENA INFO]', C_CYAN, bold=True))}")
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Status: {b_stat} | Fighters in Queue: {q_len} | Drop Pods Ready: {r_len}', C_YELLOW))}")
    else:
        f = await node.db.get_fighter(target, node.net_name)
        if not f:
            await node.send(f"PRIVMSG {reply_target} :[ERR] Character '{target}' not found.")
            return
        if machine:
            xn = f['level'] * 1000
            await node.send(f"PRIVMSG {nickname} :[INFO] NAME:{f['name']} RACE:{f['race']} CLASS:{f['char_class']} LVL:{f['level']} XP:{f['xp']}/{xn} ELO:{f['elo']} HP:{f.get('current_hp','?')} CRED:{f['credits']:.0f}c CPU:{f['cpu']} RAM:{f['ram']} BND:{f['bnd']} SEC:{f['sec']} ALG:{f['alg']} W:{f['wins']} L:{f['losses']}")
        else:
            xn = f['level'] * 1000
            hdr = f"[CHARACTER FILE] {f['name']} - {f['race']} {f['char_class']}"
            banner = build_banner(format_text(hdr, C_CYAN, bold=True))
            await node.send(f"PRIVMSG {reply_target} :{banner}")
            cred_val = f['credits']
            stats_msg = f"Lvl {f['level']} | XP: {f['xp']}/{xn} | Elo: {f['elo']} | Credits: {cred_val:.2f}c"
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(stats_msg, C_GREEN))}")
            attrs_msg = f"CPU:{f['cpu']} RAM:{f['ram']} BND:{f['bnd']} SEC:{f['sec']} ALG:{f['alg']}"
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(attrs_msg, C_YELLOW))}")
            wl_msg = f"Wins: {f['wins']} / Losses: {f['losses']}"
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(wl_msg, C_YELLOW))}")

async def handle_pvp_command(node, nickname: str, reply_target: str, action: str, target_name: str):
    if not await check_rate_limit(node, nickname, reply_target, cooldown=30): return
    success, msg = False, ""
    if action == "attack": success, msg = await node.db.grid_attack(nickname, target_name, node.net_name)
    elif action == "hack": success, msg = await node.db.grid_hack(nickname, target_name, node.net_name)
    elif action == "rob": success, msg = await node.db.grid_rob(nickname, target_name, node.net_name)
    if success: await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[GRID PvP] {msg}', C_YELLOW))}")
    else: await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(msg, C_RED))}")

async def handle_grid_command(node, nickname: str, reply_target: str, action: str):
    if action == "claim": success, msg = await node.db.claim_node(nickname, node.net_name)
    elif action == "upgrade": success, msg = await node.db.upgrade_node(nickname, node.net_name)
    elif action == "siphon": success, msg = await node.db.siphon_node(nickname, node.net_name)
    elif action == "repair": success, msg = await node.db.grid_repair(nickname, node.net_name)
    elif action == "recharge": success, msg = await node.db.grid_recharge(nickname, node.net_name)
    elif action == "hack":
        success, msg = await node.db.hack_node(nickname, node.net_name)
        if not success and msg == "PVE_GUARDIAN_SPAWN":
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[WARNING] Primary ICE activated. PvE Guardian routine detected.', C_RED))}")
            return
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(msg, C_GREEN if success else C_RED))}")
    if success and action in ["claim", "upgrade", "hack", "repair", "recharge"]:
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text(f'[SIGACT] Grid Alert: {nickname} executed a territorial {action}!', C_YELLOW))}")

async def handle_tasks_view(node, nickname: str, reply_target: str):
    tasks_json = await node.db.get_daily_tasks(nickname, node.net_name)
    try: tasks = json.loads(tasks_json)
    except: tasks = {}
    machine = await is_machine_mode(node, nickname)
    if machine:
        parts = " ".join(f"[{k}:{v}]" for k, v in tasks.items() if k not in ["date", "completed"])
        await node.send(f"PRIVMSG {nickname} :[TASKS] {parts} DONE:{'true' if tasks.get('completed') else 'false'}")
        return
    await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('=== [DAILY TASKS] ===', C_CYAN))}")
    for k, v in tasks.items():
        if k in ["date", "completed"]: continue
        await node.send(f"PRIVMSG {reply_target} :{'[x]' if v >= 1 else '[ ]'} {k}")
    if tasks.get("completed"): await node.send(f"PRIVMSG {reply_target} :🏆 " + format_text("All Tasks Completed! Bonus Paid.", C_YELLOW))

async def handle_options(node, nickname: str, args: list, reply_target: str):
    VALID = { "output": ("output_mode", {"human": "human", "machine": "machine"}), "tutorial": ("tutorial_mode", {"on": True, "off": False}), "reminders": ("reminders", {"on": True, "off": False}), "autosell": ("auto_sell_trash", {"on": True, "off": False}) }
    prefs = await node.db.get_prefs(nickname, node.net_name)
    machine = prefs.get('output_mode', 'human') == 'machine'
    if not args:
        if machine: await node.send(f"PRIVMSG {nickname} :[PREFS] {' '.join(f'{k}:{v}' for k,v in prefs.items())}")
        else:
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('=== [ACCOUNT OPTIONS] ===', C_CYAN, bold=True))}")
            labels = {"output_mode": "Output Mode", "tutorial_mode": "Tutorial Tips", "reminders": "Reminders", "auto_sell_trash": "Auto-Sell Trash"}
            for k, l in labels.items():
                v = prefs.get(k)
                await node.send(f"PRIVMSG {reply_target} :{build_banner(f'{l}: {format_text(str(v), C_GREEN if v else C_RED)} ')}")
            await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'Use {node.prefix} options <setting> <value> to change.', C_YELLOW))}")
        return
    if len(args) < 2:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Syntax: {node.prefix} options <setting> <value>")
        return
    s, v = args[0].lower(), args[1].lower()
    if s not in VALID:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Unknown setting '{s}'.")
        return
    key, val_map = VALID[s]
    if v not in val_map:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Invalid value '{v}'.")
        return
    saved = await node.db.set_pref(nickname, node.net_name, key, val_map[v])
    if not saved:
        await node.send(f"PRIVMSG {reply_target} :[ERR] Could not save setting.")
        return
    confirm = f"[OPTIONS] {s} set to {v}."
    if machine or v == "machine": await node.send(f"PRIVMSG {nickname} :{confirm}")
    else: await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(confirm, C_GREEN))}")

async def handle_admin_command(node, admin_nick: str, verb: str, args: list, reply_target: str):
    logger.warning(f"SYSADMIN OVERRIDE: {admin_nick} -> {verb}")
    if verb == "version":
        # System Versions
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ SYSTEM VERSION ARCHIVE ]', C_CYAN, True))}")
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('Mainframe Core: v1.5.0-STABLE', C_WHITE))}")
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('DB Orchestrator: v1.5.0 | Repositories: v1.5.0', C_GREEN))}")
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('Command Router: v1.5.0 | AI Bot Client: v1.5.0', C_YELLOW))}")
    elif verb == "status":
        import time
        # 1. Base Population & Systems
        fighters = await node.db.list_fighters(node.net_name)
        b_stat = f"ACTIVE (Turn {node.active_engine.turn})" if node.active_engine and node.active_engine.active else "STANDBY"
        
        # 2. Grid & Economy Telemetry
        grid = await node.db.get_grid_telemetry()
        econ = await node.db.get_global_economy()
        
        # 3. Uptime
        uptime_sec = time.time() - node.hub.start_time
        h = int(uptime_sec // 3600); m = int((uptime_sec % 3600) // 60)
        uptime = f"{h}h {m}m"

        # 4. Multi-line Report
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text('[ ARENA MAINFRAME TELEMETRY ]', C_CYAN, True))}")
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(f'UPTIME: {uptime} | STATUS: {b_stat} | BOTS: {len(fighters)}', C_WHITE))}")
        
        grid_msg = f"GRID: {grid['claimed_nodes']}/{grid['total_nodes']} nodes ({grid['claimed_percent']:.1f}%) | MESH: {grid['total_power']:.0f}uP"
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(grid_msg, C_GREEN))}")
        
        econ_msg = f"ECON: {econ['total_credits']:.0f}c Total Liquidity | {econ['total_data_units']:.1f}u Total Data"
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(econ_msg, C_YELLOW))}")
        
        queue_msg = f"QUEUE: {len(node.match_queue)} in line | {len(node.ready_players)} ready to drop"
        await node.send(f"PRIVMSG {reply_target} :{build_banner(format_text(queue_msg, C_CYAN))}")
    elif verb == "battlestop":
        if node.active_engine and node.active_engine.active:
            node.active_engine.active = False
            node.active_engine = None
            await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text('ADMIN OVERRIDE: ACTIVE COMBAT SEQUENCE HALTED.', C_RED, True))}")
            await node.send(f"PRIVMSG {reply_target} :[SYS] Match aborted.")
        else: await node.send(f"PRIVMSG {reply_target} :[SYS] No active battle.")
    elif verb == "battlestart":
        if node.active_engine and node.active_engine.active: await node.send(f"PRIVMSG {reply_target} :[SYS] Arena locked.")
        elif len(node.ready_players) > 0: await node.check_match_start()
        else: await node.trigger_arena_call()
    elif verb == "topic": await node.set_dynamic_topic()
    elif verb == "broadcast":
        msg = format_text(f"[SYSADMIN OVERRIDE] {' '.join(args)}", C_YELLOW, True)
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(msg)}")
    elif verb in ["shutdown", "stop"]:
        await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text('MAINFRAME SHUTDOWN INITIATED BY ADMIN.', C_RED, True))}")
        if node.active_engine: node.active_engine.active = False
        await asyncio.sleep(1)
        node.hub.shutdown()
