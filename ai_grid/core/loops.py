# loops.py - v1.5.0
import asyncio
import logging
import time
from grid_utils import format_text, build_banner, C_GREEN, C_CYAN, C_RED, C_YELLOW

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
                    alert = format_text(f"[ARENA BROADCAST] {hype_msg}", C_YELLOW, True)
                    await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(alert)}")
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
                
                alert = format_text(f"[{cat}] {msg}", C_CYAN, True)
                await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(alert)}")
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
                alert = format_text("[ARENA CALL] The Gladiator Gates are open. Travel to The Arena node to 'queue'!", C_YELLOW, True)
                await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(alert)}")
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
            msg = format_text("[GRID] Environmental Power levels restabilized based on organic loads.", C_CYAN)
            await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(msg)}")
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
                earned = (idle_secs * 0.001) + (chat_lines * 0.01)
                if earned > 0:
                    payouts[nick] = round(earned, 3)
                
                if nick in node.channel_users:
                    node.channel_users[nick]['join_time'] = now
                    node.channel_users[nick]['chat_lines'] = 0
            
            if payouts:
                await node.db.award_credits_bulk(payouts, node.net_name)
                await node.send(f"PRIVMSG {node.config['channel']} :{build_banner(format_text('[ECONOMY] Hourly universal basic income and network tips distributed.', C_GREEN))}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Payout loop error on {node.net_name}: {e}")
