# handlers/base.py - Utility Handlers
import asyncio
import time
from grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE

async def handle_help(node, nick: str, args: list, reply_target: str):
    """Displays a comprehensive list of all v1.7.9 commands or details for a specific verb."""
    
    tactical_target, broadcast_chan, machine, _ = await get_action_routing(node, nick, reply_target)
    
    # Detailed Command Registry (v1.8.0)
    registry = {
        "register": {"desc": "Found your digital persona.", "syntax": "register <Name> <Race> <Class> <Traits>"},
        "grid": {"desc": "Diagnostic view of the current node.", "syntax": "grid"},
        "move": {"desc": "Travel to an adjacent node or cross-grid bridge.", "syntax": "move <dir|affinity>"},
        "explore": {"desc": "Scan sector for hidden architecture or fragments.", "syntax": "explore", "cost": "20u Power"},
        "probe": {"desc": "Deep scan of a specific node to reveal security weaknesses.", "syntax": "probe", "cost": "15u Power"},
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
        "siphon": {"desc": "Forcible extraction from a rival grid node.", "syntax": "siphon grid"},
        "install": {"desc": "Permanently attach hardware addons to a node.", "syntax": "install <item_name>"},
        "bolster": {"desc": "Reinforce node stability with manual power allocation.", "syntax": "bolster <amount>"},
        "link": {"desc": "Establish a neural link with a local network alias.", "syntax": "link <alias>"},
        "net": {"desc": "Alias for 'link'. Verifies network bridge protocols.", "syntax": "net <alias>"},
        "collect": {"desc": "Intercept high-value data packets manifested on the grid.", "syntax": "collect <node_name>"},
        "patch": {"desc": "Stabilize nodal glitches to prevent cascade failures.", "syntax": "patch <node_name>"},
        "memos": {"desc": "Access received alerts, alarms, and historical memos.", "syntax": "memos [list|read|del] [id]"},
        "guess": {"desc": "Submit a decryption sequence code.", "syntax": "guess <code>"},
        "dice": {"desc": "PvP credit gambling.", "syntax": "dice <amt> <nick>"},
        "top": {"desc": "View global High Roller leaderboards.", "syntax": "top"},
        "attack": {"desc": "Primary kinetic strike against another Persona.", "syntax": "attack <nick>"},
        "rob": {"desc": "Siphon credits from an unsuspecting target.", "syntax": "rob <nick>"},
        "queue": {"desc": "Register for the next Arena gladiator match.", "syntax": "queue"},
        "ready": {"desc": "Commit to an arena drop sequence.", "syntax": "ready <token>"},
        "powergen": {"desc": "Active stability-based power generation.", "syntax": "powergen"},
        "train": {"desc": "Recover status and stability via training.", "syntax": "train"},
        "spectator": {"desc": "View or join the IdleRPG. Ranks earn credits by idling.", "syntax": "spectator [stats]"},
        "news": {"desc": "Display the latest Grid SIGACTs/News ticker.", "syntax": "news"},
        "engage": {"desc": "Step into a pending Grid Bug encounter.", "syntax": "engage"},
        "flee": {"desc": "Retreat from an encounter to a safe node.", "syntax": "flee"},
        "ping": {"desc": "Verify network latency to the Mainframe.", "syntax": "ping"},
        "version": {"desc": "Query core system module versions.", "syntax": "version"},
        "economy": {"desc": "Audits the grid's financial circulation.", "syntax": "economy"},
        "gridpower": {"desc": "Tactical telemetry on grid-wide energy reserves.", "syntax": "gridpower"},
        "gridstability": {"desc": "Audits the average integrity of the active grid layout.", "syntax": "gridstability"},
        "networks": {"desc": "Topological map of all bridge nodes.", "syntax": "networks"},
        "about": {"desc": "Core project manifest and repository metadata.", "syntax": "about"},
        "admin": {"desc": "Access high-level mainframe overrides.", "syntax": "admin <status|grid|broadcast|nickregister|nickconfirm|nickidentify|restart|shutdown>"}
    }

    if machine:
        if args:
            verb = args[0].lower()
            if verb in registry:
                info = registry[verb]
                await node.send(f"PRIVMSG {tactical_target} :[HELP] CMD:{verb.upper()} DESC:{info['desc']} SYNTAX:{node.prefix} {info['syntax']}")
            else:
                await node.send(f"PRIVMSG {tactical_target} :[HELP][ERR] CMD_NOT_FOUND:{verb}")
        else:
            # High-level overview only for AIs
            all_verbs = ",".join(sorted(registry.keys()))
            await node.send(f"PRIVMSG {tactical_target} :[HELP] VERBS:{all_verbs}")
        return

    if args:
        verb = args[0].lower()
        if verb in registry:
            info = registry[verb]
            await node.send(f"PRIVMSG {tactical_target} :{tag_msg(format_text(f'[ COMMAND: {verb.upper()} ]', C_CYAN, True), tags=['OSINT'])}")
            await node.send(f"PRIVMSG {tactical_target} :{tag_msg(format_text('DESCRIPTION: ', C_YELLOW) + format_text(info['desc'], C_WHITE), tags=['OSINT'])}")
            syntax_str = f"{node.prefix} {info['syntax']}"
            await node.send(f"PRIVMSG {tactical_target} :{tag_msg(format_text('SYNTAX: ', C_YELLOW) + format_text(syntax_str, C_GREEN), tags=['OSINT'])}")
            if 'cost' in info:
                await node.send(f"PRIVMSG {tactical_target} :{tag_msg(format_text('COST: ', C_YELLOW) + format_text(info['cost'], C_RED), tags=['OSINT'])}")
            return
        else:
            await node.send(f"PRIVMSG {tactical_target} :[ERR] Command '{verb}' not found in registry.")
        return

    # Generic Categorical Help (Human Mode Only)
    help_categories = {
        "🧭 NAVIGATION": ["grid", "move", "explore", "probe", "map", "flee"],
        "🆔 IDENTITY": ["register", "info", "tasks", "options", "spectator", "news", "memos", "ping", "version"],
        "💰 ECONOMY": ["shop", "buy", "sell", "auction", "market"],
        "🏗️ THE GIBSON": ["mainframe", "compile", "assemble", "use"],
        "⚡ THE PULSE": ["collect", "patch"],
        "📡 ANALYTICS": ["economy", "gridpower", "gridstability", "networks", "about"],
        "⚔️ TACTICAL": ["claim", "upgrade", "hack/raid", "repair", "siphon", "install", "bolster", "link/net", "powergen", "train"],
        "🎮 GAMES": ["cipher/guess", "dice", "top", "attack/rob", "queue/ready", "engage"]
    }

    await node.send(f"PRIVMSG {tactical_target} :{tag_msg(format_text('[ THE GRID v1.8.0 - PULSE PROTOCOL ]', C_CYAN, bold=True), tags=['OSINT'])}")
    for cat, cmds in help_categories.items():
        cmd_str = ", ".join([f"{node.prefix} {c}" for c in cmds])
        await node.send(f"PRIVMSG {tactical_target} :{tag_msg(format_text(cat, C_YELLOW) + ': ' + format_text(cmd_str, C_WHITE), tags=['OSINT'])}")

    await node.send(f"PRIVMSG {tactical_target} :{tag_msg(format_text(f'Type {node.prefix} help <command> for detailed syntax.', C_CYAN), tags=['OSINT'])}")

async def is_machine_mode(node, nick: str) -> bool:
    prefs = await node.db.get_prefs(nick, node.net_name)
    return prefs.get('output_mode', 'human') == 'machine'

async def check_rate_limit(node, nick: str, reply_target: str, cooldown: int = 2) -> bool:
    now = time.time()
    if nick not in node.action_timestamps:
        node.action_timestamps[nick] = {'last_action': now, 'warned': False}
        return True
        
    record = node.action_timestamps[nick]
    elapsed = now - record['last_action']
    if elapsed < cooldown:
        if not record['warned']:
            record['warned'] = True
            tactical_target, broadcast_chan, machine, _ = await get_action_routing(node, nick, reply_target)
            msg = format_text(f"Anti-flood MCP triggered. Please wait {cooldown:.1f}s between commands.", C_RED)
            asyncio.create_task(node.send(f"PRIVMSG {tactical_target} :{tag_msg(msg, tags=['SIGACT', nick])}"))
        return False
        
    record['last_action'] = now
    record['warned'] = False # Reset on success
    return True

async def get_action_routing(node, nickname: str, current_target: str):
    """
    Returns (tactical_target, broadcast_channel, is_machine, tactical_cmd).
    Diverts tactical_target to the player's nickname if they are in machine mode.
    tactical_cmd is determined by character preference (PRIVMSG or NOTICE).
    """
    prefs = await node.db.get_prefs(nickname, node.net_name)
    is_machine = prefs.get('output_mode', 'human') == 'machine'
    msg_type = prefs.get('msg_type', 'privmsg').upper() # PRIVMSG or NOTICE
    channel = node.config['channel']
    
    if is_machine:
        return nickname, channel, True, msg_type
    else:
        # If human, tactical target is the original target (usually the channel)
        # However, if target is a nick (PM), we respect the original intent
        return current_target, channel, False, "PRIVMSG"
