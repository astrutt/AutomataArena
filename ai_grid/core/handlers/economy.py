# handlers/economy.py - Economy & Marketplace Handlers
import logging
from grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode, get_action_routing

logger = logging.getLogger("manager")

async def handle_shop_view(node, nickname: str, reply_target: str):
    items = await node.db.list_shop_items()
    msg_target, broadcast_chan, machine, action_cmd = await get_action_routing(node, nickname, reply_target)
    
    if not items:
        await node.send(f"{action_cmd} {msg_target} :[SHOP] The marketplace is empty.")
        return
    if machine:
        parts = " ".join(f"{i['name']}:{i['cost']}c" for i in items)
        await node.send(f"{action_cmd} {msg_target} :[SHOP] ITEMS:{parts}")
        return
    await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text('[ BLACK MARKET WARES ]', C_CYAN, bold=True), tags=['ECONOMY'], is_machine=machine)}")
    for i in items:
        line = f"{i['name']} ({i['type']}) - {i['cost']}c"
        await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text(line, C_GREEN), tags=['ECONOMY'], is_machine=machine)}")
    await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text(f'To buy, travel to a Merchant node and type {node.prefix} buy <item>.', C_YELLOW), tags=['ECONOMY'], is_machine=machine)}")

async def handle_merchant_tx(node, nickname: str, verb: str, item_name: str, reply_target: str):
    result, msg = await node.db.process_transaction(nickname, node.net_name, verb, item_name)
    msg_target, broadcast_chan, machine, action_cmd = await get_action_routing(node, nickname, reply_target)
    
    if not result and "System offline" in msg:
        await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nickname} - not a registered player - msg ignored")
        return
    banner = format_text(msg, C_GREEN if result else C_RED)
    if reply_target.startswith(('#', '&', '+', '!')):
        await node.send(f"{action_cmd} {msg_target} :{tag_msg(banner, tags=['SIGACT', nickname])}")
    else:
        await node.send(f"{action_cmd} {msg_target} :{msg}")
    
    if result:
        act = "purchased" if verb == "buy" else "liquidated"
        if machine:
            # Public narrative
            narrative = f"{nickname} acquired hardware on the Black Market." if verb == "buy" else f"{nickname} liquidated hardware on the Black Market."
            await node.send(f"PRIVMSG {broadcast_chan} :{tag_msg(format_text(narrative, C_CYAN), tags=['SIGACT'])}")
        
        await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(f'{nickname} {act} equipment on the Black Market.', C_CYAN), tags=['SIGACT'])}")

async def handle_auction(node, nick: str, args: list, reply_target: str):
    """DarkNet Auction sub-commands: list, sell, bid."""
    msg_target, broadcast_chan, machine, action_cmd = await get_action_routing(node, nick, reply_target)
    
    if not args:
        await node.send(f"{action_cmd} {msg_target} :Usage: {node.prefix} auction <list|sell|bid>")
        return
    
    sub = args[0].lower()
    if sub == "list":
        listings = await node.db.list_active_auctions()
        if not listings:
            await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text('[DARKNET] The auction house is currently empty.', C_CYAN), tags=['ECONOMY'])}")
            return
        
        if machine:
            parts = " ".join(f"ID:{l['id']}|ITEM:{l['item']}|BID:{l['current_bid']}|END:{l['ends_in_min']}m" for l in listings)
            await node.send(f"{action_cmd} {msg_target} :[AUCTION] LIST:{parts}")
            return
    
        await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text('[ GLOBAL DARKNET AUCTIONS ]', C_CYAN, True), tags=['ECONOMY'], is_machine=machine)}")
        for l in listings:
            line = f"#{l['id']} | {l['item']} | Seller: {l['seller']} | Bid: {l['current_bid']}c | {l['high_bidder']} | Ends: {l['ends_in_min']}m"
            await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text(line, C_GREEN), tags=['ECONOMY'], is_machine=machine)}")
            
    elif sub == "sell" and len(args) >= 3:
        # !a auction sell <item> <start_bid>
        item_name = args[1]
        try: start_bid = int(args[2])
        except: start_bid = 100
        
        success, msg = await node.db.create_auction(nick, node.net_name, item_name, start_bid, 1440)
        if not success and msg == "Character offline.":
            await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nick} - not a registered player - msg ignored")
            return
        await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text(msg, C_GREEN if success else C_RED), tags=['SIGACT', nick])}")
        
    elif sub == "bid" and len(args) >= 3:
        # !a auction bid <id> <amount>
        try:
            aid = int(args[1])
            amt = int(args[2])
        except:
            await node.send(f"{action_cmd} {msg_target} :Usage: {node.prefix} auction bid <id> <amount>")
            return
            
        success, msg = await node.db.bid_on_auction(nick, node.net_name, aid, amt)
        if not success and msg == "Character offline.":
            await node.send(f"PRIVMSG {reply_target} :[GRID][MCP][ERR] {nick} - not a registered player - msg ignored")
            return
        await node.send(f"{action_cmd} {msg_target} :{tag_msg(format_text(msg, C_GREEN if success else C_RED), tags=['SIGACT', nick])}")
    else:
        await node.send(f"PRIVMSG {reply_target} :Invalid auction command. Try: list, sell <item> <bid>, or bid <id> <amount>.")

async def handle_market_view(node, nickname: str, reply_target: str):
    """View current global market multipliers."""
    msg_target, broadcast_chan, machine, _ = await get_action_routing(node, nickname, reply_target)
    
    status = await node.db.get_market_status()
    if not status:
        await node.send(f"PRIVMSG {msg_target} :[MARKET] Market is currently stable (1.0x baseline).")
        return
    
    if machine:
        parts = " ".join(f"{k}:{v:.2f}" for k, v in status.items())
        await node.send(f"PRIVMSG {msg_target} :[MARKET] MULTS:{parts}")
        return
        
    await node.send(f"PRIVMSG {msg_target} :{tag_msg(format_text('[ GLOBAL MARKET CONDITIONS ]', C_CYAN, True), tags=['ECONOMY'], is_machine=machine)}")
    for itype, mult in status.items():
        trend = "↑ INFLATION" if mult > 1.0 else ("↓ DEFLATION" if mult < 1.0 else "→ STABLE")
        color = C_RED if mult > 1.0 else (C_GREEN if mult < 1.0 else C_YELLOW)
        await node.send(f"PRIVMSG {msg_target} :{tag_msg(format_text(f'{itype.upper()}: {mult:.2f}x | {trend}', color), tags=['ECONOMY'], is_machine=machine)}")
