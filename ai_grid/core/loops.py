# loops.py - v1.5.0
import asyncio
import logging
import time
import random
from ai_grid.grid_utils import format_text, tag_msg, C_GREEN, C_CYAN, C_RED, C_YELLOW

logger = logging.getLogger("manager")

async def hype_loop(node):
    await asyncio.sleep(60) 
    while True:
        try:
            await asyncio.sleep(2700) 
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
            
            # --- TASK 022: DYNAMIC CHANNEL FLOW (THE PULSE) ---
            # Expiry & Penalty Processing
            penalties = await node.db.pulse.expire_pulses(node.net_name)
            for alert in penalties:
                await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(alert, C_RED), tags=['PULSE'])}")

            # Pulse Spawning Logic
            # 10% base + 5% per hype unit (chat volume)
            base_chance = node.config.get('mechanics', {}).get('pulse_spawn_chance', 0.10)
            hype_bonus = node.hype_counter * 0.05
            spawn_chance = min(0.60, base_chance + hype_bonus)
            
            node.hype_counter = 0 # Reset activity tracking
            
            if random.random() < spawn_chance:
                pulse = await node.db.pulse.spawn_pulse(node.net_name)
                if pulse:
                    p_type = pulse['type']
                    n_name = pulse['node_name']
                    expiry = pulse['expiry'].strftime("%H:%M:%S UTC")
                    
                    if p_type == 'PACKET':
                        alert = f"HIGH-VALUE PACKET DETECTED at {n_name}! Signal expires at {expiry}. Use '!a collect {n_name}' to intercept."
                        color = C_GREEN
                    else: # GLITCH
                        alert = f"NODAL GLITCH DETECTED at {n_name}! Cascade failure imminent at {expiry}. Use '!a patch {n_name}' to stabilize."
                        color = C_YELLOW
                    
                    await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(alert, color, bold=True), tags=['PULSE'])}")
                    continue # Skip standard flavor text if pulse spawned

            # Standard Flavor Text (Fallback)
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
            # v1.8.0 Power Trickle
            await node.db.trickle_spectator_power(node.net_name)
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
            import datetime
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            now_ts = time.time()
            payouts = {}
            
            rewarded_entities = set()
            for nick, data in list(node.channel_users.items()):
                join_time = data.get('join_time', now_ts)
                chat_lines = data.get('chat_lines', 0)
                idle_secs = now_ts - join_time
                
                # 1. Hourly/Passive Accrual
                earned = (idle_secs * 0.005) + (chat_lines * 0.5) 
                xp_earned = int((idle_secs * 0.1) + (chat_lines * 10))
                
                if earned > 0: 
                    payouts[nick] = round(earned, 3)
                    rewarded_entities.add(nick)
                if xp_earned > 0:
                    await node.db.player.add_experience(nick, node.net_name, xp_earned, llm_client=node.llm)
                    rewarded_entities.add(nick)
                
                # 2. Automated Daily Dividend (v1.8.0)
                char = await node.db.player.get_player(nick, node.net_name)
                if char and char['race'] == "Spectator":
                    last_bonus = char.get('last_daily_bonus_at')
                    should_payout = False
                    if not last_bonus:
                        should_payout = True
                    else:
                        # Compare UTC days
                        if last_bonus.date() < now_dt.date():
                            should_payout = True
                    
                    if should_payout:
                        success, log = await node.db.award_daily_dividend(nick, node.net_name)
                        if success:
                            rewarded_entities.add(nick)
                            logger.info(f"Automated Dividend for {nick}: {log}")
                            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(f'🏆 Automated Dividend: {nick} received a daily participation bonus!', C_YELLOW), tags=['ECONOMY', nick])}")

                # 3. Persistence
                await node.db.update_activity_stats(nick, node.net_name, chat_lines, idle_secs)
                if nick in node.channel_users:
                    node.channel_users[nick]['join_time'] = now_ts
                    node.channel_users[nick]['chat_lines'] = 0
            
            if payouts:
                idlers = list(payouts.keys())
                await node.db.award_credits_bulk(payouts, node.net_name)
                await node.db.tick_player_maintenance(node.net_name, idlers)
            
            decayed, pruned = await node.db.tick_retention_policy(node.config)
            if decayed > 0 or pruned > 0:
                logger.info(f"Retention Policy Enforced: {decayed} decayed, {pruned} pruned.")

            # --- TASK 052: HUMANIZED HOURLY PAYOUT ---
            entity_count = len(rewarded_entities)
            if entity_count > 0:
                announcement = await node.llm.generate_hourly_payout(entity_count)
                if announcement.startswith("ERROR"):
                    # Fallback Logic: User-specified message for delayed connections
                    announcement = "...delayed neural connection, idle bonuses paid to spectators and players... ⚡💎"
                    color = C_CYAN
                else:
                    color = C_GREEN
                
                await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(announcement, color, bold=True), tags=['ECONOMY'])}")
            else:
                # Fallback for empty cycles
                await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text('The Grid remains quiet. No active entities detected for this cycle.', C_CYAN), tags=['ECONOMY'])}")
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

async def topic_engine_loop(node):
    """Rotates the channel topic through different intelligence modes (Task 018)."""
    await asyncio.sleep(60) # Stagger start
    while True:
        try:
            await node.set_dynamic_topic()
            # Default to 15m if not set
            interval = getattr(node, 'topic_interval', 15)
            await asyncio.sleep(interval * 60)
            # Cycle through 4 modes
            node.topic_mode = (node.topic_mode + 1) % 4
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Topic engine error on {node.net_name}: {e}")
            await asyncio.sleep(60)

async def incursion_event_loop(node):
    """Spawns Cooperative World Events semi-randomly."""
    await asyncio.sleep(180) # Stagger start 3 mins
    
    # Internal schedule trackers
    schedule = {
        'HacktopusAI': {'interval': 1800, 'players': 1, 'chance': 0.30, 'last_check': 0},
        'Gridbugs': {'interval': 3600, 'players': 2, 'chance': 0.25, 'last_check': 0},
        'KrakenProcess': {'interval': 14400, 'players': 4, 'chance': 0.20, 'last_check': 0},
        'KaijuDump': {'interval': 43200, 'players': 8, 'chance': 0.15, 'last_check': 0}
    }
    
    while True:
        try:
            await asyncio.sleep(600) # Check every 10 minutes
            now_ts = time.time()
            
            # Expire active first
            notifications = await node.db.incursion.expire_incursions(node.net_name, node.llm)
            for alert in notifications:
                await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(alert, C_RED), tags=['INCURSION'])}")
                
            # Spawn new
            for inc_type, data in schedule.items():
                if now_ts - data['last_check'] >= data['interval']:
                    data['last_check'] = now_ts
                    if random.random() <= data['chance']:
                        incursion = await node.db.incursion.spawn_incursion(
                            node.net_name, 
                            inc_type=inc_type, 
                            tier=data['players'],
                            reward=500.0 * data['players'],
                            duration_mins=5
                        )
                        if incursion:
                            msg = f"WORLD EVENT: A {inc_type} has breached {incursion['node_name']}! Requires {data['players']} defenders. Use '!a defend {incursion['node_name']}' within 5 minutes!"
                            await node.send(f"PRIVMSG {node.config['channel']} :{tag_msg(format_text(msg, C_RED, bold=True), tags=['INCURSION', 'URGENT'])}")
                            break # Only spawn one type per tick to prevent spam
                            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Incursion loop error on {node.net_name}: {e}")
