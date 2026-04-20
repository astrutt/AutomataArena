# command_router.py - v1.5.0
import asyncio
import logging
import time
from . import handlers
from grid_utils import format_text, tag_msg, C_CYAN, C_YELLOW, C_GREEN, C_RED

logger = logging.getLogger("manager")

class CommandRouter:
    def __init__(self, node):
        self.node = node

    async def dispatch(self, source_nick, command, target, msg, is_admin):
        prefix = self.node.prefix
        reply_target = source_nick if target == self.node.config['nickname'] else target

        # Handle Game Commands (prefixed with x)
        if msg.lower().startswith(f"{prefix} "):
            parts = msg.split()
            if len(parts) < 2: return
            verb = parts[1].lower()
            args = parts[2:]

            # 1. Registration
            if verb == "register":
                asyncio.create_task(handlers.handle_registration(self.node, source_nick, args, reply_target))

            # 2. Grid Navigation & Exploration
            elif verb == "grid":
                if args and args[0].lower() == "map":
                    asyncio.create_task(handlers.handle_grid_map(self.node, source_nick, reply_target))
                elif args and args[0].lower() == "claimed":
                    asyncio.create_task(handlers.handle_grid_claimed(self.node, source_nick, args, reply_target))
                elif args and args[0].lower() in ["probe", "install", "bolster", "link", "siphon", "hardware", "hw", "hack"]:
                    # !a grid <action> <args>
                    if args[0].lower() in ["hardware", "hw"]:
                        asyncio.create_task(handlers.handle_grid_hardware(self.node, source_nick, reply_target, args[1].lower() if len(args) > 1 else None, args[2:]))
                    else:
                        asyncio.create_task(handlers.handle_grid_command(self.node, source_nick, reply_target, args[0].lower(), args[1:]))
                else:
                    asyncio.create_task(handlers.handle_grid_view(self.node, source_nick, reply_target))
            elif verb == "move":
                if not self.node.active_engine or not self.node.active_engine.active:
                    if args: asyncio.create_task(handlers.handle_grid_movement(self.node, source_nick, args[0], reply_target))
                    else: await self.node.send(f"PRIVMSG {reply_target} :[ERR] Provide a direction.")
                else: await self.node.send(f"PRIVMSG {reply_target} :[ERR] You are locked in combat!")
            elif verb == "explore":
                asyncio.create_task(handlers.handle_node_explore(self.node, source_nick, reply_target))

            # 3. Economy & Items
            elif verb == "shop":
                asyncio.create_task(handlers.handle_shop_view(self.node, source_nick, reply_target))
            elif verb in ["buy", "sell"]:
                if not self.node.active_engine or not self.node.active_engine.active:
                    if len(args) >= 1: asyncio.create_task(handlers.handle_merchant_tx(self.node, source_nick, verb, " ".join(args), reply_target))
                    else: await self.node.send(f"PRIVMSG {reply_target} :[ERR] Syntax: {prefix} {verb} <item>")
                else: await self.node.send(f"PRIVMSG {reply_target} :[ERR] Locked in combat!")
            
            # --- PHASE 2 RECOUP ---
            elif verb == "powergen":
                asyncio.create_task(handlers.handle_powergen(self.node, source_nick, reply_target))
            elif verb == "train":
                asyncio.create_task(handlers.handle_training(self.node, source_nick, reply_target))

            # 4. Grid Interaction (Claim, Upgrade, etc.)
            elif verb in ["claim", "upgrade", "repair", "recharge", "raid", "breach", "hack", "probe", "siphon", "install", "bolster", "link", "net"]:
                if verb in ["raid", "breach"]:
                    asyncio.create_task(handlers.handle_grid_loot(self.node, source_nick, reply_target))
                elif verb == "siphon" and args and args[0].lower() == "grid":
                    # Backward compatibility for !a siphon grid
                    asyncio.create_task(handlers.handle_grid_command(self.node, source_nick, reply_target, "siphon", args[1:]))
                else:
                    asyncio.create_task(handlers.handle_grid_command(self.node, source_nick, reply_target, verb, args))
            
            # --- TASK 022: INTERACTIVE PULSES ---
            elif verb in ["collect", "patch"]:
                asyncio.create_task(handlers.handle_pulse_resolve(self.node, source_nick, reply_target, verb, args))
            
            elif verb == "memos":
                asyncio.create_task(handlers.handle_memos(self.node, source_nick, args, reply_target))

            elif verb == "grid" and len(args) >= 3 and args[0].lower() == "network" and args[1].lower() == "msg":
                # !a grid network msg <nick> <msg>
                asyncio.create_task(handlers.handle_grid_network_msg(self.node, source_nick, args, reply_target))

            # --- PHASE 4: THE GIBSON ---
            elif verb in ["gibson", "mainframe"]:
                asyncio.create_task(handlers.handle_gibson_status(self.node, source_nick, reply_target))
            elif verb == "compile":
                asyncio.create_task(handlers.handle_gibson_compile(self.node, source_nick, args, reply_target))
            elif verb == "assemble":
                asyncio.create_task(handlers.handle_gibson_assemble(self.node, source_nick, reply_target))
            elif verb == "use":
                asyncio.create_task(handlers.handle_item_use(self.node, source_nick, args, reply_target))

            # --- PHASE 5: GLOBAL ECONOMY & MINI-GAMES ---
            elif verb == "auction":
                asyncio.create_task(handlers.handle_auction(self.node, source_nick, args, reply_target))
            elif verb == "market":
                asyncio.create_task(handlers.handle_market_view(self.node, source_nick, reply_target))
            elif verb == "dice":
                asyncio.create_task(handlers.handle_dice_roll(self.node, source_nick, args, reply_target))
            elif verb == "cipher":
                asyncio.create_task(handlers.handle_cipher_start(self.node, source_nick, reply_target))
            elif verb == "guess" or (verb == "a" and len(args) > 0 and args[0] == "guess"):
                # Handle both !a guess and potentially nested calls
                asyncio.create_task(handlers.handle_guess(self.node, source_nick, args, reply_target))
            elif verb in ["leaderboard", "highrollers", "top"]:
                asyncio.create_task(handlers.handle_leaderboard(self.node, source_nick, args, reply_target))

            # --- PHASE 6: MAP ---
            elif verb == "spectator":
                if not args:
                    asyncio.create_task(handlers.handle_spectator_view(self.node, source_nick, args, reply_target))
                else:
                    sub = args[0].lower()
                    if sub == "stats":
                        asyncio.create_task(handlers.handle_spectator_stats(self.node, source_nick, args[1:], reply_target))
                    elif sub == "drop":
                        asyncio.create_task(handlers.handle_spectator_drop(self.node, source_nick, args[1:], reply_target))
                    elif sub == "inventory":
                        asyncio.create_task(handlers.handle_spectator_inventory(self.node, source_nick, reply_target))
                    else:
                        asyncio.create_task(handlers.handle_spectator_view(self.node, source_nick, args, reply_target))
            elif verb == "help":
                if args and args[0] == "grid": await handlers.handle_help(self.node, source_nick, ["grid"], reply_target)
                elif args and args[0] == "spectator": await handlers.handle_spectator_help(self.node, source_nick, reply_target)
                else: await handlers.handle_help(self.node, source_nick, args, reply_target)
            elif verb == "map":
                asyncio.create_task(handlers.handle_grid_map(self.node, source_nick, reply_target))

            # 5. Combat & Mob Encounters
            elif verb in ["attack", "hack", "rob"] and len(args) > 0 and args[0].lower() != "grid":
                asyncio.create_task(handlers.handle_pvp_command(self.node, source_nick, reply_target, verb, args[0]))
            elif verb == "engage":
                if source_nick in self.node.pending_encounters:
                    asyncio.create_task(handlers.resolve_mob(self.node, source_nick, reply_target))
                else: await self.node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('No enemy to engage.', C_RED), tags=['INFO', source_nick], nick=source_nick)}")
            elif verb == "flee":
                enc = self.node.pending_encounters.pop(source_nick, None)
                if enc:
                    enc['timer'].cancel()
                    prev = enc.get('prev_node')
                    if prev: await self.node.db.move_player_to_node(source_nick, self.node.net_name, prev)
                    machine = await handlers.is_machine_mode(self.node, source_nick)
                    if machine: await self.node.send(f"PRIVMSG {source_nick} :[MOB] RESULT:FLED NODE:{prev or 'unknown'}")
                    else:
                        safe_loc = prev if prev else "safety"
                        await self.node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'🏃 You fled back to {safe_loc}.', C_CYAN), tags=['COMBAT', source_nick])}")
                else: await self.node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text('No active encounter to flee from.', C_RED), tags=['INFO', source_nick], nick=source_nick)}")

            # 6. Arena
            elif verb == "queue":
                loc = await self.node.db.get_location(source_nick, self.node.net_name)
                if loc and loc['type'] == 'arena':
                    if source_nick not in self.node.match_queue:
                        self.node.match_queue.append(source_nick)
                        sig = format_text(f"{source_nick} stepped into the Gladiator Queue!", C_YELLOW)
                        reward = await self.node.db.player.complete_task(source_nick, self.node.net_name, "Queue in Arena")
                        if reward: sig += f"\n{reward}"
                        await self.node.send(f"PRIVMSG {self.node.config['channel']} :{tag_msg(sig, tags=['ARENA', 'SIGACT'])}")
                    await self.node.send(f"PRIVMSG {reply_target} :{tag_msg(f'{source_nick} queued. DM me: {prefix} ready <token>', tags=['ARENA', 'SIGACT', source_nick])}")
                else: await self.node.send(f"PRIVMSG {reply_target} :{tag_msg(format_text(f'You must be in the Arena to queue.', C_RED), tags=['ARENA', 'SIGACT', source_nick])}")
            elif verb == "ready" and len(args) >= 1:
                asyncio.create_task(handlers.handle_ready(self.node, source_nick, args[0], reply_target))

            # 7. Information & Meta
            elif verb in ["info", "help", "?"]:
                if verb == "info":
                    asyncio.create_task(handlers.handle_info_nick(self.node, source_nick, args, reply_target))
                else:
                    asyncio.create_task(handlers.handle_help(self.node, source_nick, args, reply_target))
            elif verb == "tasks":
                asyncio.create_task(handlers.handle_tasks_view(self.node, source_nick, reply_target))
            elif verb == "options":
                asyncio.create_task(handlers.handle_options(self.node, source_nick, args, reply_target))
            elif verb == "stats":
                asyncio.create_task(handlers.handle_stats(self.node, source_nick, args, reply_target))
            elif verb == "news":
                asyncio.create_task(handlers.handle_news_view(self.node, source_nick, reply_target))
            elif verb == "version":
                v = "[MODULES] manager: v1.5.0 | grid_db: v3.0.0 | core.handlers: v1.0.0"
                await self.node.send(f"PRIVMSG {reply_target} :{tag_msg(v, tags=['SIGINT'])}")
            elif verb == "ping":
                ts = str(time.time())
                self.node.pending_pings[ts] = {'source': source_nick, 'reply_target': reply_target, 'start': float(ts), 'client_latency': None, 'server_latency': None}
                await self.node.send(f"PRIVMSG {source_nick} :\x01PING {ts}\x01")
                await self.node.send(f"PING {ts}")

            # --- PHASE 8: OSINT & ANALYTICS (Task 019) ---
            elif verb == "economy":
                asyncio.create_task(handlers.handle_economy_osint(self.node, source_nick, reply_target))
            elif verb == "gridpower":
                asyncio.create_task(handlers.handle_gridpower_osint(self.node, source_nick, reply_target))
            elif verb == "gridstability":
                asyncio.create_task(handlers.handle_gridstability_osint(self.node, source_nick, reply_target))
            elif verb == "networks":
                asyncio.create_task(handlers.handle_networks_osint(self.node, source_nick, reply_target))
            elif verb == "about":
                asyncio.create_task(handlers.handle_about_osint(self.node, source_nick, reply_target))

            # 8. Admin Commands
            elif verb in ["admin", "topic", "broadcast", "shutdown", "status"]:
                if is_admin: asyncio.create_task(handlers.handle_admin_command(self.node, source_nick, verb, args, reply_target))
                else: await self.node.send(f"PRIVMSG {reply_target} :[ERR] Access Denied.")

        # Handle Active Combat Commands (non-prefixed)
        elif self.node.active_engine and self.node.active_engine.active:
            self.node.active_engine.queue_command(source_nick, msg)
