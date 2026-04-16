# loops.py - v1.5.0
import asyncio
import logging
import time
import random
from grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW

logger = logging.getLogger("manager")

async def hype_loop(node):
    await asyncio.sleep(60) 
    while True:
        try:
            await asyncio.sleep(2700) 
            await node.set_dynamic_topic()
            if not node.active_engine:
                hype_msg = await node.llm.generate_hype()
                if not hype_msg.startswith("ERROR"):
                    await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(hype_msg, C_YELLOW, True), tags=['RUMINT'])}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Hype loop error on {node.net_name}: {e}")

async def ambient_event_loop(node):
    await asyncio.sleep(120) 
    while True:
        try:
            await asyncio.sleep(600)  # 10 minute interval
            if not node.active_engine or not node.active_engine.active:
                event = await node.llm.generate_ambient_event()
                cat = event.get('category', 'SYS').upper()
                msg = event.get('message', '')
                await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(msg, C_CYAN, True), tags=[cat])}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ambient event error on {node.net_name}: {e}")

async def arena_call_loop(node):
    await asyncio.sleep(120) 
    while True:
        try:
            await asyncio.sleep(3600)  # 60 minute interval
            if not node.active_engine or not node.active_engine.active:
                alert = format_text("The Gladiator Gates are open. Travel to The Arena node to 'queue'!", C_YELLOW, True)
                await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(alert, tags=['ARENA'])}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Arena call error on {node.net_name}: {e}")

async def power_tick_loop(node):
    await asyncio.sleep(30)
    while True:
        try:
            await asyncio.sleep(600)  # 10 minute interval
            await node.db.tick_grid_power()
            msg = format_text("Environmental Power levels restabilized based on organic loads.", C_CYAN)
            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(msg, tags=['MAINT'])}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Power tick error on {node.net_name}: {e}")

async def idle_payout_loop(node):
    await asyncio.sleep(60) 
    while True:
        try:
            await asyncio.sleep(3600)  # 60 minute interval
            now = time.time()
            payouts = {}
            for nick, data in list(node.channel_users.items()):
                join_time = data.get('join_time', now)
                chat_lines = data.get('chat_lines', 0)
                idle_secs = now - join_time
                earned = (idle_secs * 0.001) + (chat_lines * 0.1) # Boosted chat bonus
                if earned > 0:
                    payouts[nick] = round(earned, 3)
                
                # PERSIST STATS
                await node.db.update_activity_stats(nick, node.net_name, chat_lines, idle_secs)
                
                if nick in node.channel_users:
                    node.channel_users[nick]['join_time'] = now
                    node.channel_users[nick]['chat_lines'] = 0
            
            if payouts:
                idlers = list(payouts.keys())
                await node.db.award_credits_bulk(payouts, node.net_name)
                await node.db.tick_player_maintenance(node.net_name, idlers)
            
            # Enforce Unified Retention Policy
            decayed, pruned = await node.db.tick_retention_policy(node.config)
            if decayed > 0 or pruned > 0:
                logger.info(f"Retention Policy Enforced: {decayed} decayed, {pruned} pruned.")

            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text('Hourly rewards distributed. Absence-based retention policy enforced.', C_GREEN), tags=['ECONOMY'])}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Payout loop error on {node.net_name}: {e}")

async def mainframe_loop(node):
    """Processes background Gibson tasks and MemoServ notifications."""
    await asyncio.sleep(45)
    while True:
        try:
            await asyncio.sleep(60) # Process every minute
            notifications = await node.db.tick_mainframe_tasks()
            
            for note in notifications:
                # We only process notes for the current network in this loop instance
                if note['network'].lower() == node.net_name.lower():
                    # Channel Alert
                    await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(note['msg'], C_CYAN), tags=['SIGINT', note['nickname']])}")
                    
                    # MemoServ Integration (Global)
                    if CONFIG.get('mechanics', {}).get('mainframe', {}).get('memoserv_enabled', True):
                        await node.hub.send_memo(note['network'], note['nickname'], note['msg'])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Mainframe loop error on {node.net_name}: {e}")

async def auction_loop(node):
    """Checks for expired DarkNet auctions and processes fulfillment."""
    await asyncio.sleep(30)
    while True:
        try:
            await asyncio.sleep(60) # Tick every minute
            notifications = await node.db.tick_auctions()
            
            for note in notifications:
                # MemoServ Integration (Global)
                if CONFIG.get('mechanics', {}).get('mainframe', {}).get('memoserv_enabled', True):
                    await node.hub.send_memo(note['network'], note['nickname'], note['msg'])
                
                # If the recipient is currently on THIS network, give them a live alert too
                if note['network'].lower() == node.net_name.lower():
                    await node.send(f"PRIVMSG {note['nickname']} :{tag_msg(format_text(note['msg'], C_YELLOW), tags=['ECONOMY', note['nickname']])}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Auction loop error on {node.net_name}: {e}")

async def economic_ticker_loop(node):
    """LLM-driven market fluctuations every 60 minutes."""
    await asyncio.sleep(15) # Stagger start
    while True:
        try:
            # Generate Market News via LLM
            news_text = await node.hub.llm.generate_market_news()
            
            # Simple heuristic to extract multipliers from LLM output or just random-walk
            # For robustness, we'll use a random walk with LLM flavor text
            multipliers = {
                "junk": round(random.uniform(0.8, 1.5), 2),
                "hack": round(random.uniform(0.9, 1.3), 2),
                "weapon": round(random.uniform(0.9, 1.2), 2),
                "gear": round(random.uniform(0.9, 1.1), 2)
            }
            
            await node.db.update_market_rates(multipliers, news_text)
            
            # Broadcast news to the channel
            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(news_text, C_CYAN), tags=['ECONOMY'])}")
            
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Economic ticker error: {e}")
            await asyncio.sleep(300)

async def hype_drop_loop(node):
    """Rewards active spectators during chat volume spikes."""
    await asyncio.sleep(60)
    while True:
        try:
            await asyncio.sleep(300) # Check every 5 minutes
            threshold = 15
            if node.hype_counter >= threshold:
                # Find active chatters (last 5 mins)
                # For simplicity, we filter from channel_users who have > 0 lines
                chatters = [nick for nick, data in node.channel_users.items() if data.get('chat_lines', 0) > 0]
                
                if chatters:
                    count = min(3, len(chatters))
                    lucky = random.sample(chatters, count)
                    
                    for nick in lucky:
                        # Award 100c or 5 Data
                        reward_type = random.choice(["credits", "data"])
                        if reward_type == "credits":
                            await node.db.economy.award_credits(nick, node.net_name, 100)
                        else:
                            await node.db.economy.award_data(nick, node.net_name, 5.0)
                        
                        node.channel_users[nick]['chat_lines'] = 0 # Reset activity for this user
                    
                    msg = format_text(f"The Grid resonates with your energy! Rewards dropped to: {', '.join(lucky)}", C_YELLOW, bold=True)
                    await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(msg, tags=['SIGACT'])}")
            
            node.hype_counter = 0 # Reset global counter
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Hype drop loop error: {e}")
