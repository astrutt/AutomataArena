# handlers/economy.py - Economy & Marketplace Handlers
import logging
from grid_utils import format_text, build_banner, C_GREEN, C_CYAN, C_RED, C_YELLOW, C_WHITE
from .base import is_machine_mode

logger = logging.getLogger("manager")

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
