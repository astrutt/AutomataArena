import asyncio
import os
import sys
import time
import datetime
import random
from sqlalchemy.future import select
from sqlalchemy import delete
from sqlalchemy.orm import selectinload

# Add root and ai_grid dirs to path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "ai_grid"))

from ai_grid.grid_db import ArenaDB
from ai_grid.models import (
    Character, Player, NetworkAlias, ItemTemplate, InventoryItem, 
    PulseEvent, GridNode, BreachRecord, DiscoveryRecord
)
from ai_grid.core.loops import idle_payout_loop

async def test_spectator_system():
    db = ArenaDB()
    network = "rizon"
    spec_nick = "Spec_Audit"
    player_nick = "Player_Audit"
    
    print("[*] Setting up Spectator System Test Environment...")
    
    # 1. Setup Spectator
    async with db.async_session() as session:
        spec = await db.identity.get_character_by_nick(spec_nick, network, session)
    
    if not spec:
        await db.identity.register_player(spec_nick, network, "Spectator", "Idle", "Digital", {"cpu": 1, "ram": 1, "bnd": 1, "sec": 1, "alg": 1})
        async with db.async_session() as session:
            spec = await db.identity.get_character_by_nick(spec_nick, network, session)

    # 2. Setup Player
    async with db.async_session() as session:
        player = await db.identity.get_character_by_nick(player_nick, network, session)
        
    if not player:
        await db.identity.register_player(player_nick, network, "Human", "Hacker", "Bio", {"cpu": 5, "ram": 5, "bnd": 5, "sec": 5, "alg": 5})
        async with db.async_session() as session:
            player = await db.identity.get_character_by_nick(player_nick, network, session)
    
    # 3. Manual Overrides and seeding
    async with db.async_session() as session:
        # Re-fetch both to be in current session
        spec = await db.identity.get_character_by_nick(spec_nick, network, session)
        player = await db.identity.get_character_by_nick(player_nick, network, session)
        
        spec.race = "Spectator"
        spec.credits = 10000.0 # Rich spectator for tests
        spec.xp = 0
        spec.level = 1
        spec.pending_stat_points = 0
        
        # 4. Seed Items for drops
        for item_name in ["Data_Shard", "Memory_Fragment", "Corrupted_Bit"]:
            stmt = select(ItemTemplate).where(ItemTemplate.name == item_name)
            if not (await session.execute(stmt)).scalars().first():
                session.add(ItemTemplate(name=item_name, item_type="junk", base_value=100))
        
        # 5. Setup Arena Node
        arena = (await session.execute(select(GridNode).where(GridNode.node_type == 'arena'))).scalars().first()
        if not arena:
            arena = GridNode(name="Arena_Alpha", node_type="arena", upgrade_level=1, durability=100.0)
            session.add(arena)
        
        # 6. Setup UpLink Node
        uplink = (await session.execute(select(GridNode).where(GridNode.name == 'UpLink'))).scalars().first()
        if not uplink:
            uplink = GridNode(name="UpLink", node_type="void", upgrade_level=1, durability=100.0)
            session.add(uplink)
        
        await session.commit()

    print(f"[+] Environment Ready. Spectator: {spec_nick}, Player: {player_nick}")

    # --- Phase 1: Idle Rewards & Daily Dividend ---
    print("\n[*] Phase 1: Testing Hourly Payout & Daily Dividend...")
    # Simulate idler state
    now_ts = time.time()
    mock_idlers = {
        spec_nick.lower(): {'join_time': now_ts - 3600, 'chat_lines': 10} # 1 hour idle, 10 chats
    }
    
    # We mock the node object since idle_payout_loop expects one
    class MockNode:
        def __init__(self, db):
            self.db = db
            self.net_name = network
            self.config = {"channel": "#arena", "nickname": "GridHub"}
            self.channel_users = mock_idlers
            self.llm = None
            self.hype_counter = 0
        async def send(self, msg):
            print(f"| [IRC-SIM] {msg}")

    node = MockNode(db)
    
    # Trigger one tick of the loop logic (we don't run the actual loop forever)
    # We'll extract the logic from the loop or just run the repo methods
    
    print("[*] Simulating Hourly Payout...")
    # Calculating expected: (3600 * 0.005) + (10 * 0.5) = 18 + 5 = 23 credits
    # XP: (3600 * 0.1) + (10 * 10) = 360 + 100 = 460 XP
    
    # We'll use a snapshot of the code from loops.py to verify math
    idle_secs = 3600
    chat_lines = 10
    earned = (idle_secs * 0.005) + (chat_lines * 0.5)
    xp_earned = int((idle_secs * 0.1) + (chat_lines * 10))
    
    # Award them
    await db.economy.award_credits_bulk({spec_nick: earned}, network)
    await db.player.add_experience(spec_nick, network, xp_earned)
    
    print("[*] Simulating Daily Dividend...")
    success, log = await db.spectator.award_daily_dividend(spec_nick, network)
    print(f"[+] Dividend Result: {log}")
    
    # Verify results
    async with db.async_session() as session:
        char = await db.identity.get_character_by_nick(spec_nick, network, session)
        print(f"[DEBUG] Final Credits: {char.credits:.2f}c")
        print(f"[DEBUG] Final XP: {char.xp}")
        print(f"[DEBUG] Final Level: {char.level}")
        
        assert char.credits > 10000.0, "Credits did not increase!"
        assert char.xp > 0, "XP did not increase!"
        assert char.level > 1, f"Spectator failed to level up from {xp_earned} XP. Current Level: {char.level}"
        assert char.pending_stat_points == 0, "ERROR: Spectator received pending stat points!"

    # --- Phase 2: Orbital Drops ---
    print("\n[*] Phase 2: Testing Orbital Drops...")
    
    # 1. Targeted Drop
    print(f"[*] Executing Targeted Drop to {player_nick}...")
    success, msg = await db.spectator.spectator_drop(spec_nick, network, target=player_nick)
    print(f"[+] Result: {msg}")
    
    # Verify inventory
    async with db.async_session() as session:
        p_char = (await session.execute(
            select(Character).where(Character.name == player_nick).options(selectinload(Character.inventory).selectinload(InventoryItem.template))
        )).scalars().first()
        inv_items = [i.template.name for i in p_char.inventory]
        print(f"[DEBUG] Player Inventory: {inv_items}")
        assert any(item in inv_items for item in ["Data_Shard", "Memory_Fragment", "Corrupted_Bit"]), "Targeted drop failed to arrive!"

    # 2. Public Drop
    print("[*] Executing Public Drop to Arena...")
    success, msg = await db.spectator.spectator_drop(spec_nick, network, target=None)
    print(f"[+] Result: {msg}")
    
    async with db.async_session() as session:
        pulses = (await session.execute(select(PulseEvent).where(PulseEvent.network_name == network, PulseEvent.status == 'ACTIVE'))).scalars().all()
        print(f"[DEBUG] Active Pulses in Arena: {len(pulses)}")
        assert len(pulses) > 0, "Public drop failed to create PulseEvent!"

    # --- Phase 3: Power Trickle ---
    print("\n[*] Phase 3: Testing Power Trickle...")
    
    async with db.async_session() as session:
        uplink = (await session.execute(select(GridNode).where(GridNode.name == 'UpLink'))).scalars().first()
        initial_power = uplink.power_stored
    
    await db.spectator.trickle_power(network)
    
    async with db.async_session() as session:
        uplink = (await session.execute(select(GridNode).where(GridNode.name == 'UpLink'))).scalars().first()
        final_power = uplink.power_stored
        print(f"[DEBUG] UpLink Power: {initial_power:.2f} -> {final_power:.2f}")
        assert final_power > initial_power, "Power Trickle failed to inject energy into UpLink!"

    print("\n[✅] Spectator System Verification Passed!")
    await db.close()

if __name__ == "__main__":
    asyncio.run(test_spectator_system())
