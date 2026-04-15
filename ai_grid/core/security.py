# security.py - v1.5.0
import asyncio
import logging

logger = logging.getLogger("manager")

async def request_nickserv_check(node, nick: str):
    """Send WHO with flags to check if nick is identified with NickServ (+r mode)."""
    # IRC extended WHO: %na gives us account name in a 354 response
    await node.send(f"WHO {nick} %na")

async def schedule_spectator_registration(node, nick: str):
    """Wait 5 minutes, then register as Spectator if NickServ-verified and unknown."""
    try:
        await asyncio.sleep(300)  # 5 minute idle gate
        nick_lower = nick.lower()
        # Only proceed if still in channel and NickServ verified
        if nick_lower not in node.channel_users:
            return
        if nick_lower not in node.nickserv_verified:
            logger.debug(f"[{node.net_name}] Skipping auto-reg for {nick}: not NickServ-identified.")
            return
        existing = await node.db.get_fighter(nick_lower, node.net_name)
        if not existing:
            logger.info(f"[{node.net_name}] Auto-registering {nick} as Spectator after 5min idle + NickServ check.")
            await node.db.register_fighter(nick_lower, node.net_name, "Spectator", "Civilian", "An orbital spectator.", {'cpu': 1, 'ram': 1, 'bnd': 1, 'sec': 1, 'alg': 1})
    except asyncio.CancelledError:
        pass
    finally:
        node.pending_registrations.pop(nick.lower(), None)

def start_registration_timer(node, nick: str):
    """Kick off NickServ check + 5-min timer for a new nick."""
    nick_lower = nick.lower()
    if nick_lower in node.pending_registrations:
        return  # Already scheduled
    asyncio.create_task(request_nickserv_check(node, nick_lower))
    task = asyncio.create_task(schedule_spectator_registration(node, nick_lower))
    node.pending_registrations[nick_lower] = task
