import asyncio
import datetime
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_grid.models import (
    Base,
    Character,
    Player,
    NetworkAlias,
    GridNode,
    DiscoveryRecord,
    BreachRecord,
    Memo,
    ItemTemplate,
    InventoryItem,
    CharacterSkill,
)
from ai_grid.database.repositories.territory_repo import TerritoryRepository
from ai_grid.database.repositories.remote_net_repo import RemoteNetRepository, get_net_device_state
from ai_grid.core.security_utils import is_action_hostile
from ai_grid.core.command_router import CommandRouter
import ai_grid.core.handlers as handlers


class TestRemoteNetRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_path = f"test_remote_net_{int(datetime.datetime.now().timestamp() * 1000)}.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.repo = RemoteNetRepository(self.async_session)
        self.territory_repo = TerritoryRepository(self.async_session)

        # Seed Attacker on 2600net
        async with self.async_session() as session:
            # Item Templates
            session.add(ItemTemplate(name="NET", item_type="node_addon", base_value=1000, effects_json='{"type": "NET"}'))
            session.add(ItemTemplate(name="AMP", item_type="node_addon", base_value=500, effects_json='{"type": "AMP"}'))
            session.add(ItemTemplate(name="IDS", item_type="node_addon", base_value=500, effects_json='{"type": "IDS"}'))
            session.add(ItemTemplate(name="FIREWALL", item_type="node_addon", base_value=500, effects_json='{"type": "FIREWALL"}'))
            session.add(ItemTemplate(name="T4_APT_EXPLOIT", item_type="gear", base_value=5000, effects_json='{"action": "exploit"}'))

            # Attacker Player & Character
            att_player = Player(global_name="Attacker", is_autonomous=False)
            session.add(att_player)
            await session.flush()
            session.add(NetworkAlias(player_id=att_player.id, network_name="2600net", nickname="Attacker"))

            att_char = Character(
                player_id=att_player.id,
                name="Attacker",
                race="Cyborg",
                char_class="Netrunner",
                credits=100.0,
                power=200.0,
                alg=5,
            )
            session.add(att_char)
            await session.flush()

            # Attacker Local Node on 2600net pointed at Rizon
            att_node = GridNode(
                name="AttackerCore",
                node_type="safezone",
                owner_character_id=att_char.id,
                net_affinity="Rizon",
                addons_json=json.dumps({"NET": True, "NET_STATE": "OPEN"}),
                availability_mode="OPEN",
                power_stored=500.0,
                durability=100.0,
            )
            session.add(att_node)
            await session.flush()
            att_char.node_id = att_node.id

            # Defender Player & Character on Rizon
            def_player = Player(global_name="Defender", is_autonomous=False)
            session.add(def_player)
            await session.flush()
            session.add(NetworkAlias(player_id=def_player.id, network_name="Rizon", nickname="Defender"))

            def_char = Character(
                player_id=def_player.id,
                name="Defender",
                race="Ghost",
                char_class="Sentinel",
                credits=500.0,
                power=200.0,
            )
            session.add(def_char)
            await session.flush()

            # Target Nodes on Rizon
            # 1. Open Target Node
            node_open = GridNode(
                name="Rizon_Open",
                node_type="void",
                owner_character_id=def_char.id,
                net_affinity="Rizon",
                addons_json=json.dumps({"NET": True, "NET_STATE": "OPEN"}),
                availability_mode="OPEN",
                power_stored=200.0,
                durability=100.0,
                upgrade_level=1,
            )
            session.add(node_open)

            # 2. Closed Target Node with IDS and FIREWALL
            node_closed = GridNode(
                name="Rizon_Closed",
                node_type="void",
                owner_character_id=def_char.id,
                net_affinity="Rizon",
                addons_json=json.dumps({"NET": True, "NET_STATE": "CLOSED", "IDS": True, "FIREWALL": True}),
                availability_mode="CLOSED",
                power_stored=500.0,
                durability=100.0,
                upgrade_level=2,
            )
            session.add(node_closed)

            # 3. Stealth Target Node
            node_stealth = GridNode(
                name="Rizon_Stealth",
                node_type="void",
                owner_character_id=def_char.id,
                net_affinity="Rizon",
                addons_json=json.dumps({"NET": True, "NET_STATE": "STEALTH", "IDS": True}),
                availability_mode="STEALTH",
                power_stored=300.0,
                durability=100.0,
                upgrade_level=1,
            )
            session.add(node_stealth)

            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    # =========================================================================
    # R1: NET Device States & Access Gating Tests
    # =========================================================================

    async def test_r1_net_device_state_transitions(self):
        """R1: Node owner can toggle NET states between OPEN, CLOSED, and STEALTH."""
        # 1. Transition to CLOSED
        ok, msg = await self.repo.set_net_device_state("Attacker", "2600net", "CLOSED")
        self.assertTrue(ok)
        self.assertIn("CLOSED", msg)

        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "AttackerCore"))).scalars().first()
            self.assertEqual(get_net_device_state(node), "CLOSED")
            self.assertEqual(node.availability_mode, "CLOSED")

        # 2. Transition to STEALTH
        ok, msg = await self.repo.set_net_device_state("Attacker", "2600net", "STEALTH")
        self.assertTrue(ok)
        self.assertIn("STEALTH", msg)

        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "AttackerCore"))).scalars().first()
            self.assertEqual(get_net_device_state(node), "STEALTH")
            self.assertEqual(node.availability_mode, "STEALTH")

        # 3. Transition back to OPEN
        ok, msg = await self.repo.set_net_device_state("Attacker", "2600net", "OPEN")
        self.assertTrue(ok)
        self.assertIn("OPEN", msg)

        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "AttackerCore"))).scalars().first()
            self.assertEqual(get_net_device_state(node), "OPEN")

    async def test_r1_stealth_requires_net_device(self):
        """R1: STEALTH state requires an active NET device."""
        async with self.async_session() as session:
            # Create a node without NET device
            plain_node = GridNode(
                name="PlainNode",
                node_type="void",
                owner_character_id=1,
                addons_json=json.dumps({"AMP": True}),
                availability_mode="OPEN",
            )
            session.add(plain_node)
            await session.commit()

        # Attempt to set STEALTH on PlainNode via territory_repo.set_grid_mode
        ok, msg = await self.territory_repo.set_grid_mode("Attacker", "2600net", "STEALTH", node_name="PlainNode")
        self.assertFalse(ok)
        self.assertIn("NET device", msg)

    async def test_r1_only_owner_can_configure_net_state(self):
        """R1: Non-owners cannot reconfigure NET device states."""
        ok, msg = await self.repo.set_net_device_state("Defender", "Rizon", "STEALTH", node_name="AttackerCore")
        self.assertFalse(ok)
        self.assertIn("Permission Denied", msg)

    async def test_r1_remote_pvp_pve_gating(self):
        """R1: Remote PvP/PvE queue accessible immediately on OPEN, locked on CLOSED until breached."""
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            node_open = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Open"))).scalars().first()
            node_closed = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Closed"))).scalars().first()

            att_id = att.id
            open_id = node_open.id
            closed_id = node_closed.id

        # 1. OPEN node: Accessible immediately without breach
        accessible, msg = await self.repo.is_node_pvp_pve_accessible(open_id, att_id)
        self.assertTrue(accessible)
        self.assertIn("OPEN", msg)

        # 2. CLOSED node: Blocked without breach
        accessible, msg = await self.repo.is_node_pvp_pve_accessible(closed_id, att_id)
        self.assertFalse(accessible)
        self.assertIn("hack or exploit", msg)

        # 3. CLOSED node: Unlocked after valid breach
        async with self.async_session() as session:
            session.add(BreachRecord(character_id=att_id, node_id=closed_id))
            await session.commit()

        accessible, msg = await self.repo.is_node_pvp_pve_accessible(closed_id, att_id)
        self.assertTrue(accessible)
        self.assertIn("active breach", msg)

    # =========================================================================
    # R2: Remote Discovery-to-Raid Operations & Distance Modifiers Tests
    # =========================================================================

    async def test_r2_hardware_and_alignment_prerequisites(self):
        """R2: Attacker must be at a claimed node with active NET device pointed at target network."""
        # Case A: Attacker node pointed at Rizon -> succeeds
        res = await self.repo.remote_explore("Attacker", "2600net", "Rizon")
        self.assertTrue(res["success"])

        # Case B: Pointed at foreign network "Libera", but attacker aims at "Rizon" -> Alignment Error
        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "AttackerCore"))).scalars().first()
            node.net_affinity = "Libera"
            await session.commit()

        res = await self.repo.remote_explore("Attacker", "2600net", "Rizon")
        self.assertFalse(res["success"])
        self.assertIn("Alignment Error", res["msg"])

        # Case C: NET device missing -> Hardware Error
        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "AttackerCore"))).scalars().first()
            node.net_affinity = "Rizon"
            node.addons_json = json.dumps({"AMP": True})
            await session.commit()

        res = await self.repo.remote_explore("Attacker", "2600net", "Rizon")
        self.assertFalse(res["success"])
        self.assertIn("Hardware Error", res["msg"])

    async def test_r2_stealth_hidden_from_explore_and_explore_dampening(self):
        """R2: STEALTH nodes never appear in explore; explore has -20% yield and no detection."""
        res = await self.repo.remote_explore("Attacker", "2600net", "Rizon")
        self.assertTrue(res["success"])

        # STEALTH node must NOT appear
        visible_names = [n["name"] for n in res["visible_nodes"]]
        self.assertIn("Rizon_Open", visible_names)
        self.assertIn("Rizon_Closed", visible_names)
        self.assertNotIn("Rizon_Stealth", visible_names)

        # -20% yield dampening: base 25c -> 20c
        self.assertEqual(res["yield_modifier"], "-20%")
        self.assertAlmostEqual(res["credits_gained"], 20.0, places=1)

    async def test_r2_stealth_probe_probability(self):
        """R2: STEALTH node resolves via remote probe only at 30% base chance."""
        # 1. When random roll >= 0.30 -> Probe fails
        with patch("random.random", return_value=0.50):
            res = await self.repo.remote_probe("Attacker", "2600net", "Rizon", "Rizon_Stealth")
            self.assertFalse(res["success"])
            self.assertIn("Stealth sensor interference", res["msg"])

        # 2. When random roll < 0.30 -> Probe succeeds
        with patch("random.random", return_value=0.20):
            res = await self.repo.remote_probe("Attacker", "2600net", "Rizon", "Rizon_Stealth")
            self.assertTrue(res["success"])
            self.assertEqual(res["name"], "Rizon_Stealth")
            self.assertEqual(res["state"], "STEALTH")

    async def test_r2_remote_hack_latency_penalty(self):
        """R2: Remote hack applies +20% hack difficulty (latency penalty)."""
        # First: probe to satisfy requirement
        await self.repo.remote_probe("Attacker", "2600net", "Rizon", "Rizon_Closed")

        # Base DC on Rizon_Closed: upgrade_level=2, power=500, dur=100 -> base_dc = 10 + 10 + 0 + 0 = 20.
        # With FIREWALL (1.35x), local_dc = int(20 * 1.35) = 27.
        # Remote latency penalty (+20%): 30 * 1.20 = 36.
        # Let's test with patch on randint so roll = 10 + alg (5) = 15 (< 36) -> Fails
        with patch("random.randint", return_value=10):
            ok, msg, alert = await self.repo.remote_hack("Attacker", "2600net", "Rizon", "Rizon_Closed")
            self.assertFalse(ok)
            self.assertIn("+20% Latency", msg)

        # When roll >= 36 (e.g. roll=32 + 5 = 37) -> Succeeds
        with patch("random.randint", return_value=32):
            ok, msg, alert = await self.repo.remote_hack("Attacker", "2600net", "Rizon", "Rizon_Closed")
            self.assertTrue(ok)
            self.assertIn("OPEN", msg)

    async def test_r2_remote_siphon_dampening_and_access_gating(self):
        """R2: Siphon CLOSED node is blocked without breach; remote yield applies -10% exfiltration dampening."""
        # 1. Closed node without breach -> Blocked
        ok, msg, _ = await self.repo.remote_siphon("Attacker", "2600net", "Rizon", "Rizon_Closed", percent=50.0)
        self.assertFalse(ok)
        self.assertIn("ACCESS DENIED", msg)

        # 2. OPEN node -> Allowed, -10% exfiltration yield
        # Rizon_Open has 200 power stored. 50% = 100 power. -10% remote dampening = 90.0 power gained.
        ok, msg, alert = await self.repo.remote_siphon("Attacker", "2600net", "Rizon", "Rizon_Open", percent=50.0)
        self.assertTrue(ok)
        self.assertIn("-10% remote dampening", msg)

        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            # Initial power 200 - 5 (cost) + 90.0 (yield) = 285.0
            self.assertAlmostEqual(att.power, 285.0, places=1)

    async def test_r2_remote_exploit_true_damage(self):
        """R2: Exploit deploys true damage, ignoring distance dampening and bypassing DC."""
        # Give attacker the exploit item
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            tmpl = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == "T4_APT_EXPLOIT"))).scalars().first()
            session.add(InventoryItem(character_id=att.id, template_id=tmpl.id, quantity=1))
            await session.commit()

        ok, msg, alert = await self.repo.remote_exploit("Attacker", "2600net", "Rizon", "Rizon_Closed")
        self.assertTrue(ok)
        self.assertIn("true damage", msg)
        self.assertIn("distance dampening ignored", msg)

        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Closed"))).scalars().first()
            self.assertEqual(node.availability_mode, "OPEN")

    async def test_r2_remote_raid_yield_modifier(self):
        """R2: Remote raid applies -20% reward yield."""
        # Satisfy probe and breach prerequisites
        await self.repo.remote_probe("Attacker", "2600net", "Rizon", "Rizon_Open")

        with patch("random.randint", return_value=200), patch("random.uniform", return_value=50.0):
            res = await self.repo.remote_raid("Attacker", "2600net", "Rizon", "Rizon_Open")
            self.assertTrue(res["success"])
            self.assertEqual(res["yield_modifier"], "-20%")
            # Base 200c * 0.8 = 160c
            self.assertEqual(res["credits_gained"], 160)
            # Base 50.0 data * 0.8 = 40.0 data
            self.assertAlmostEqual(res["data_gained"], 40.0, places=1)

    # =========================================================================
    # R3: Cross-Network Detection & Messaging Tests
    # =========================================================================

    async def test_r3_detection_routing_to_target_channel(self):
        """R3: IDS/breach alerts route notifications to target network channel, NOT attacker home channel."""
        mock_attacker_node = MagicMock()
        mock_attacker_node.net_name = "2600net"
        mock_attacker_node.config = {"channel": "#2600net"}
        mock_attacker_node.send = AsyncMock()

        mock_target_bot = MagicMock()
        mock_target_bot.config = {"channel": "#rizon"}
        mock_target_bot.send = AsyncMock()

        mock_hub = MagicMock()
        mock_hub.nodes = {"rizon": mock_target_bot, "2600net": mock_attacker_node}
        mock_attacker_node.hub = mock_hub
        mock_attacker_node.db = MagicMock()
        mock_attacker_node.db.remote_net = self.repo
        mock_attacker_node.add_xp = AsyncMock()

        # Execute remote raid which triggers high detection risk on Rizon_Open
        await self.repo.remote_probe("Attacker", "2600net", "Rizon", "Rizon_Open")
        await handlers.remote_net.handle_remote_net_command(
            mock_attacker_node, "Attacker", "#2600net", "Rizon", ["raid", "Rizon_Open"]
        )
        await asyncio.sleep(0.05)

        # 1. Attacker's home channel #2600net must NEVER receive the breach alarm
        for call_args in mock_attacker_node.send.call_args_list:
            raw_msg = call_args[0][0]
            self.assertNotIn("SECURITY BREACH", raw_msg)
            self.assertNotIn("RAIDED by", raw_msg)

        # 2. Target network channel #rizon MUST receive the breach alert
        mock_target_bot.send.assert_called_once()
        target_sent = mock_target_bot.send.call_args[0][0]
        self.assertIn("PRIVMSG #rizon", target_sent)
        self.assertIn("SECURITY BREACH", target_sent)
        self.assertIn("Rizon_Open RAIDED by Attacker", target_sent)

    async def test_r3_net_messaging_broadcast_and_direct(self):
        """R3: net <network> msg supports global broadcast and direct player communication."""
        mock_attacker_node = MagicMock()
        mock_attacker_node.net_name = "2600net"
        mock_attacker_node.prefix = "!a"
        mock_attacker_node.config = {"channel": "#2600net"}
        mock_attacker_node.send = AsyncMock()

        mock_target_bot = MagicMock()
        mock_target_bot.config = {"channel": "#rizon"}
        mock_target_bot.send = AsyncMock()

        mock_hub = MagicMock()
        mock_hub.nodes = {"rizon": mock_target_bot, "2600net": mock_attacker_node}
        mock_attacker_node.hub = mock_hub
        mock_attacker_node.db = MagicMock()
        mock_attacker_node.db.remote_net = self.repo
        mock_attacker_node.db.async_session = self.async_session

        async def get_char_mock(nick, net, session):
            stmt = select(Character).where(Character.name == nick).options(selectinload(Character.current_node))
            return (await session.execute(stmt)).scalars().first()

        mock_attacker_node.db.get_character_by_nick = get_char_mock

        # 1. Broadcast syntax: net Rizon msg Hello from 2600net!
        await handlers.remote_net.handle_remote_net_command(
            mock_attacker_node, "Attacker", "#2600net", "Rizon", ["msg", "Hello", "from", "2600net!"]
        )
        mock_target_bot.send.assert_called_with("PRIVMSG #rizon :[NET BROADCAST from Attacker@2600net] Hello from 2600net!")

        # 2. Direct player syntax: net Rizon msg #rizon Defender Status report please
        mock_target_bot.send.reset_mock()
        await handlers.remote_net.handle_remote_net_command(
            mock_attacker_node, "Attacker", "#2600net", "Rizon", ["msg", "#rizon", "Defender", "Status", "report", "please"]
        )
        # Verifies relay to channel and direct nick
        calls = [c[0][0] for c in mock_target_bot.send.call_args_list]
        self.assertTrue(any("PRIVMSG #rizon :Defender: <Attacker@2600net> Status report please" in c for c in calls))
        self.assertTrue(any("PRIVMSG Defender :<Attacker@2600net> Status report please" in c for c in calls))

    # =========================================================================
    # Command Router Aliasing Tests
    # =========================================================================

    async def test_command_router_net_and_grid_net_dispatch(self):
        """Verify command router dispatches both 'net <network> ...' and 'x grid net <network> ...'."""
        mock_node = MagicMock()
        mock_node.prefix = "!a"
        mock_node.config = {"nickname": "bot"}
        mock_node.send = AsyncMock()
        mock_node.active_engine = None

        router = CommandRouter(mock_node)

        with patch("ai_grid.core.handlers.handle_remote_net_command", new_callable=AsyncMock) as mock_handler:
            # 1. Direct verb: !a net Rizon explore
            await router.dispatch("Attacker", "PRIVMSG", "#2600net", "!a net Rizon explore", is_admin=False)
            await asyncio.sleep(0.01)
            mock_handler.assert_called_with(mock_node, "Attacker", "#2600net", "Rizon", ["explore"])

            # 2. Aliased via grid: !a grid net Rizon explore
            mock_handler.reset_mock()
            await router.dispatch("Attacker", "PRIVMSG", "#2600net", "!a grid net Rizon explore", is_admin=False)
            await asyncio.sleep(0.01)
            mock_handler.assert_called_with(mock_node, "Attacker", "#2600net", "Rizon", ["explore"])

            # 3. State command: !a net state STEALTH
            mock_handler.reset_mock()
            await router.dispatch("Attacker", "PRIVMSG", "#2600net", "!a net state STEALTH", is_admin=False)
            await asyncio.sleep(0.01)
            mock_handler.assert_called_with(mock_node, "Attacker", "#2600net", "state", ["STEALTH"])

    # =========================================================================
    # Edge Cases & Robustness Audit Tests
    # =========================================================================

    async def test_r1_net_device_installation_and_hardware_slots(self):
        """R1: Installing NET via install_node_addon and filling all 4 hardware slots succeeds."""
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            tmpl_net = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == "NET"))).scalars().first()
            tmpl_amp = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == "AMP"))).scalars().first()
            tmpl_ids = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == "IDS"))).scalars().first()
            tmpl_fw = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == "FIREWALL"))).scalars().first()

            # Fresh 4-slot node with no addons
            slot_node = GridNode(
                name="SlotNode",
                node_type="safezone",
                owner_character_id=att.id,
                net_affinity="Rizon",
                addons_json="{}",
                availability_mode="OPEN",
                max_slots=4,
            )
            session.add(slot_node)
            await session.flush()
            att.node_id = slot_node.id

            # Give modules to attacker
            session.add(InventoryItem(character_id=att.id, template_id=tmpl_net.id, quantity=1))
            session.add(InventoryItem(character_id=att.id, template_id=tmpl_amp.id, quantity=1))
            session.add(InventoryItem(character_id=att.id, template_id=tmpl_ids.id, quantity=1))
            session.add(InventoryItem(character_id=att.id, template_id=tmpl_fw.id, quantity=1))
            await session.commit()

        # 1. Install NET
        res = await self.territory_repo.install_node_addon("Attacker", "2600net", "NET", node_name="SlotNode")
        self.assertTrue(res["success"])

        # 2. Configure state to STEALTH (which writes NET_STATE)
        ok, msg = await self.repo.set_net_device_state("Attacker", "2600net", "STEALTH", node_name="SlotNode")
        self.assertTrue(ok)

        # 3. Install remaining 3 modules (AMP, IDS, FIREWALL)
        res_amp = await self.territory_repo.install_node_addon("Attacker", "2600net", "AMP", node_name="SlotNode")
        self.assertTrue(res_amp["success"])
        res_ids = await self.territory_repo.install_node_addon("Attacker", "2600net", "IDS", node_name="SlotNode")
        self.assertTrue(res_ids["success"])
        res_fw = await self.territory_repo.install_node_addon("Attacker", "2600net", "FIREWALL", node_name="SlotNode")
        self.assertTrue(res_fw["success"])

        # Verify all 4 modules are active
        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "SlotNode"))).scalars().first()
            addons = json.loads(node.addons_json or "{}")
            self.assertTrue(addons.get("NET"))
            self.assertTrue(addons.get("AMP"))
            self.assertTrue(addons.get("IDS"))
            self.assertTrue(addons.get("FIREWALL"))

    async def test_r1_decommission_net_reverts_stealth_and_cleans_metadata(self):
        """R1: Decommissioning NET reverts STEALTH node to CLOSED and cleans up NET_STATE."""
        # Configure AttackerCore as STEALTH
        ok, msg = await self.repo.set_net_device_state("Attacker", "2600net", "STEALTH")
        self.assertTrue(ok)

        # Uninstall NET
        res = await self.territory_repo.uninstall_node_addon("Attacker", "2600net", "NET")
        self.assertTrue(res["success"])

        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "AttackerCore"))).scalars().first()
            addons = json.loads(node.addons_json or "{}")
            self.assertNotIn("NET", addons)
            self.assertNotIn("NET_STATE", addons)
            # Must no longer be STEALTH
            self.assertNotEqual(node.availability_mode, "STEALTH")
            self.assertEqual(node.availability_mode, "CLOSED")

    async def test_r2_stealth_node_blocks_unbreached_siphon_and_raid(self):
        """R2: STEALTH nodes block unbreached siphon and raid operations."""
        # 1. Resolve probe on Rizon_Stealth
        with patch("random.random", return_value=0.10):
            res_probe = await self.repo.remote_probe("Attacker", "2600net", "Rizon", "Rizon_Stealth")
            self.assertTrue(res_probe["success"])

        # 2. Attempt siphon on STEALTH without breach -> must fail
        ok_siph, msg_siph, _ = await self.repo.remote_siphon("Attacker", "2600net", "Rizon", "Rizon_Stealth")
        self.assertFalse(ok_siph)
        self.assertIn("ACCESS DENIED", msg_siph)

        # 3. Attempt raid on STEALTH without breach -> must fail
        res_raid = await self.repo.remote_raid("Attacker", "2600net", "Rizon", "Rizon_Stealth")
        self.assertFalse(res_raid["success"])
        self.assertIn("Cannot raid STEALTH network", res_raid["msg"])

        # 4. Now breach node
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            stealth_node = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Stealth"))).scalars().first()
            session.add(BreachRecord(character_id=att.id, node_id=stealth_node.id))
            await session.commit()

        # 5. Subsequent siphon now succeeds
        ok_siph2, msg_siph2, _ = await self.repo.remote_siphon("Attacker", "2600net", "Rizon", "Rizon_Stealth", percent=20.0)
        self.assertTrue(ok_siph2)

    async def test_r2_foreign_stealth_node_blocks_unauthorized_attacker(self):
        """R2: Visitor stationed at foreign STEALTH node cannot use it for remote operations."""
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            stealth_node = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Stealth"))).scalars().first()
            # Move attacker to Defender's STEALTH node
            att.node_id = stealth_node.id
            await session.commit()

        res = await self.repo.remote_explore("Attacker", "2600net", "Rizon")
        self.assertFalse(res["success"])
        self.assertIn("Access Denied: Node is claimed by another entity", res["msg"])

    async def test_r2_explore_empty_network_fails(self):
        """R2: Remote explore on an unmapped / empty network returns failure without awarding currency."""
        # Align node to EmptyNet
        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "AttackerCore"))).scalars().first()
            node.net_affinity = "EmptyNet"
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            initial_credits = att.credits
            await session.commit()

        res = await self.repo.remote_explore("Attacker", "2600net", "EmptyNet")
        self.assertFalse(res["success"])
        self.assertIn("No active grid nodes found", res["msg"])

        # Ensure no credits were awarded
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            self.assertEqual(att.credits, initial_credits)

    async def test_r2_explore_does_not_downgrade_probe_intel(self):
        """R2: Running explore does not downgrade an active PROBE intelligence record."""
        # 1. Probe Rizon_Closed
        res_probe = await self.repo.remote_probe("Attacker", "2600net", "Rizon", "Rizon_Closed")
        self.assertTrue(res_probe["success"])

        # 2. Run explore
        res_exp = await self.repo.remote_explore("Attacker", "2600net", "Rizon")
        self.assertTrue(res_exp["success"])

        # 3. Verify intelligence is STILL 'PROBE'
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            node = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Closed"))).scalars().first()
            disc = (await session.execute(
                select(DiscoveryRecord).where(
                    DiscoveryRecord.character_id == att.id,
                    DiscoveryRecord.node_id == node.id,
                )
            )).scalars().first()
            self.assertEqual(disc.intel_level, "PROBE")

    async def test_r3_hub_case_insensitive_lookup(self):
        """R3: Hub targets resolve correctly regardless of network name casing."""
        mock_attacker_node = MagicMock()
        mock_attacker_node.net_name = "2600net"
        mock_attacker_node.prefix = "!a"
        mock_attacker_node.config = {"channel": "#2600net"}
        mock_attacker_node.send = AsyncMock()

        mock_target_bot = MagicMock()
        mock_target_bot.config = {"channel": "#RizonChannel"}
        mock_target_bot.send = AsyncMock()

        # Key in hub is capitalized "Rizon"
        mock_hub = MagicMock()
        mock_hub.nodes = {"Rizon": mock_target_bot, "2600net": mock_attacker_node}
        mock_attacker_node.hub = mock_hub
        mock_attacker_node.db = MagicMock()
        mock_attacker_node.db.remote_net = self.repo
        mock_attacker_node.db.async_session = self.async_session

        async def get_char_mock(nick, net, session):
            stmt = select(Character).where(Character.name == nick).options(selectinload(Character.current_node))
            return (await session.execute(stmt)).scalars().first()

        mock_attacker_node.db.get_character_by_nick = get_char_mock

        # Call with lowercase "rizon"
        await handlers.remote_net.handle_remote_net_command(
            mock_attacker_node, "Attacker", "#2600net", "rizon", ["msg", "Testing", "case", "insensitivity"]
        )
        mock_target_bot.send.assert_called_with("PRIVMSG #RizonChannel :[NET BROADCAST from Attacker@2600net] Testing case insensitivity")

    async def test_r2_self_targeting_local_station_blocked(self):
        """R2: Attacker cannot target their own local station through the remote NET device."""
        # Attempt probe on local node
        res_probe = await self.repo.remote_probe("Attacker", "2600net", "Rizon", "AttackerCore")
        self.assertFalse(res_probe["success"])
        self.assertIn("Target Conflict", res_probe["msg"])

        # Attempt hack on local node
        ok_hack, msg_hack, _ = await self.repo.remote_hack("Attacker", "2600net", "Rizon", "AttackerCore")
        self.assertFalse(ok_hack)
        self.assertIn("Target Conflict", msg_hack)

        # Attempt siphon on local node
        ok_siph, msg_siph, _ = await self.repo.remote_siphon("Attacker", "2600net", "Rizon", "AttackerCore")
        self.assertFalse(ok_siph)
        self.assertIn("Target Conflict", msg_siph)

        # Attempt exploit on local node
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            tmpl = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == "T4_APT_EXPLOIT"))).scalars().first()
            session.add(InventoryItem(character_id=att.id, template_id=tmpl.id, quantity=1))
            await session.commit()

        ok_exp, msg_exp, _ = await self.repo.remote_exploit("Attacker", "2600net", "Rizon", "AttackerCore")
        self.assertFalse(ok_exp)
        self.assertIn("Target Conflict", msg_exp)

        # Attempt raid on local node
        res_raid = await self.repo.remote_raid("Attacker", "2600net", "Rizon", "AttackerCore")
        self.assertFalse(res_raid["success"])
        self.assertIn("Target Conflict", res_raid["msg"])

    async def test_r2_explore_100_percent_stealth_network_yields_zero_rewards(self):
        """R2: When all remote nodes are STEALTH, explore yields 0 nodes mapped and 0 rewards."""
        # Setup a network with only STEALTH nodes
        async with self.async_session() as session:
            stealth_net_node = GridNode(
                name="ShadowNet_1",
                node_type="void",
                net_affinity="ShadowNet",
                addons_json=json.dumps({"NET": True, "NET_STATE": "STEALTH"}),
                availability_mode="STEALTH",
            )
            session.add(stealth_net_node)
            # Align attacker to ShadowNet
            att_node = (await session.execute(select(GridNode).where(GridNode.name == "AttackerCore"))).scalars().first()
            att_node.net_affinity = "ShadowNet"
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            initial_credits = att.credits
            initial_data = att.data_units
            await session.commit()

        res = await self.repo.remote_explore("Attacker", "2600net", "ShadowNet")
        self.assertTrue(res["success"])
        self.assertEqual(len(res["visible_nodes"]), 0)
        self.assertEqual(res["credits_gained"], 0.0)
        self.assertEqual(res["data_gained"], 0.0)

        # Verify no credits or data were added to character
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            self.assertEqual(att.credits, initial_credits)
            self.assertEqual(att.data_units, initial_data)

    async def test_r1_owner_pvp_pve_queue_access_unlocked_on_closed_and_stealth(self):
        """R1: Node owner has immediate PvP/PvE queue access on their own CLOSED and STEALTH nodes."""
        async with self.async_session() as session:
            def_char = (await session.execute(select(Character).where(Character.name == "Defender"))).scalars().first()
            node_closed = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Closed"))).scalars().first()
            node_stealth = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Stealth"))).scalars().first()
            def_id = def_char.id
            closed_id = node_closed.id
            stealth_id = node_stealth.id

        # Defender is owner of Rizon_Closed and Rizon_Stealth
        accessible_closed, msg_closed = await self.repo.is_node_pvp_pve_accessible(closed_id, def_id)
        self.assertTrue(accessible_closed)
        self.assertIn("Node Owner", msg_closed)

        accessible_stealth, msg_stealth = await self.repo.is_node_pvp_pve_accessible(stealth_id, def_id)
        self.assertTrue(accessible_stealth)
        self.assertIn("Node Owner", msg_stealth)

    async def test_r2_siphon_depleted_power_node_rejected(self):
        """R2: Siphoning a node with 0 power is rejected with depleted error."""
        async with self.async_session() as session:
            node_open = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Open"))).scalars().first()
            node_open.power_stored = 0.0
            await session.commit()

        ok, msg, _ = await self.repo.remote_siphon("Attacker", "2600net", "Rizon", "Rizon_Open")
        self.assertFalse(ok)
        self.assertIn("depleted", msg)

    async def test_r2_loud_hack_clears_silent_exploit_breach_status(self):
        """R2: Subsequent loud hack clears silent breach status on a previously exploited node."""
        # 1. Exploit node silently
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            tmpl = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == "T4_APT_EXPLOIT"))).scalars().first()
            session.add(InventoryItem(character_id=att.id, template_id=tmpl.id, quantity=1))
            await session.commit()

        ok_exp, msg_exp, _ = await self.repo.remote_exploit("Attacker", "2600net", "Rizon", "Rizon_Closed")
        self.assertTrue(ok_exp)

        # Verify breach is currently silent
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            node = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Closed"))).scalars().first()
            breach = (await session.execute(
                select(BreachRecord).where(BreachRecord.character_id == att.id, BreachRecord.node_id == node.id)
            )).scalars().first()
            self.assertTrue(breach.is_silent)

        # 2. Reset node to CLOSED to allow a remote hack test
        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Closed"))).scalars().first()
            node.availability_mode = "CLOSED"
            addons = json.loads(node.addons_json or "{}")
            addons["NET_STATE"] = "CLOSED"
            node.addons_json = json.dumps(addons)
            await session.commit()

        # 3. Probe and perform loud hack
        await self.repo.remote_probe("Attacker", "2600net", "Rizon", "Rizon_Closed")
        with patch("random.randint", return_value=35):
            ok_hack, msg_hack, _ = await self.repo.remote_hack("Attacker", "2600net", "Rizon", "Rizon_Closed")
            self.assertTrue(ok_hack)

        # Verify breach is now loud (is_silent == False)
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            node = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Closed"))).scalars().first()
            breach = (await session.execute(
                select(BreachRecord).where(BreachRecord.character_id == att.id, BreachRecord.node_id == node.id)
            )).scalars().first()
            self.assertFalse(breach.is_silent)

    async def test_r1_is_action_hostile_supports_stealth_and_case_insensitive(self):
        """R1: is_action_hostile treats all breach/info gathering on STEALTH nodes as hostile."""
        self.assertTrue(is_action_hostile("probe", "STEALTH"))
        self.assertTrue(is_action_hostile("probe", "stealth"))
        self.assertTrue(is_action_hostile("hack", "STEALTH"))
        self.assertTrue(is_action_hostile("siphon", "STEALTH"))
        self.assertTrue(is_action_hostile("raid", "STEALTH"))
        self.assertTrue(is_action_hostile("exploit", "STEALTH"))
        self.assertTrue(is_action_hostile("hack", "open"))
        self.assertTrue(is_action_hostile("raid", "OPEN"))
        self.assertFalse(is_action_hostile("probe", "OPEN"))
        self.assertFalse(is_action_hostile("explore", "OPEN"))
        self.assertFalse(is_action_hostile("probe", None))

    async def test_r2_remote_exploit_rejects_non_exploit_item(self):
        """R2: Exploit rejects non-exploit items and does not breach the node or consume the item."""
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            tmpl = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == "AMP"))).scalars().first()
            session.add(InventoryItem(character_id=att.id, template_id=tmpl.id, quantity=1))
            await session.commit()

        ok, msg, _ = await self.repo.remote_exploit("Attacker", "2600net", "Rizon", "Rizon_Closed", item_name="AMP")
        self.assertFalse(ok)
        self.assertIn("not a valid Zero-Day", msg)

        # Confirm node is STILL closed and item is still in inventory
        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Closed"))).scalars().first()
            self.assertEqual(node.availability_mode, "CLOSED")
            item = (await session.execute(
                select(InventoryItem).join(ItemTemplate).where(
                    InventoryItem.character_id == att.id,
                    ItemTemplate.name == "AMP"
                )
            )).scalars().first()
            self.assertIsNotNone(item)

    async def test_r2_remote_exploit_syncs_net_dict_state(self):
        """R2: Exploit synchronizes addons['NET']['state'] when NET addon is stored as a dictionary."""
        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Closed"))).scalars().first()
            addons = {"NET": {"state": "CLOSED"}, "NET_STATE": "CLOSED"}
            node.addons_json = json.dumps(addons)
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            tmpl = (await session.execute(select(ItemTemplate).where(ItemTemplate.name == "T4_APT_EXPLOIT"))).scalars().first()
            session.add(InventoryItem(character_id=att.id, template_id=tmpl.id, quantity=1))
            await session.commit()

        ok, msg, _ = await self.repo.remote_exploit("Attacker", "2600net", "Rizon", "Rizon_Closed")
        self.assertTrue(ok)

        async with self.async_session() as session:
            node = (await session.execute(select(GridNode).where(GridNode.name == "Rizon_Closed"))).scalars().first()
            addons = json.loads(node.addons_json)
            self.assertEqual(addons.get("NET_STATE"), "OPEN")
            self.assertIsInstance(addons.get("NET"), dict)
            self.assertEqual(addons["NET"].get("state"), "OPEN")

    async def test_r1_is_node_pvp_pve_accessible_unclaimed_or_none_char_id(self):
        """R1: Unclaimed node or missing character ID does not mistakenly grant owner access."""
        async with self.async_session() as session:
            unclaimed = GridNode(
                name="UnclaimedSector",
                node_type="void",
                owner_character_id=None,
                net_affinity="Rizon",
                addons_json=json.dumps({"NET": True, "NET_STATE": "CLOSED"}),
                availability_mode="CLOSED",
            )
            session.add(unclaimed)
            await session.commit()
            unclaimed_id = unclaimed.id

        # Missing character_id -> denied
        accessible, msg = await self.repo.is_node_pvp_pve_accessible(unclaimed_id, None)
        self.assertFalse(accessible)

        # Non-owner character -> denied
        async with self.async_session() as session:
            att = (await session.execute(select(Character).where(Character.name == "Attacker"))).scalars().first()
            att_id = att.id

        accessible2, msg2 = await self.repo.is_node_pvp_pve_accessible(unclaimed_id, att_id)
        self.assertFalse(accessible2)

    async def test_r3_net_messaging_does_not_impose_punitive_cooldown(self):
        """R3: Sending net msg does not trigger a 60-second operational lockout."""
        mock_node = MagicMock()
        mock_node.net_name = "2600net"
        mock_node.prefix = "!a"
        mock_node.config = {"channel": "#2600net"}
        mock_node.send = AsyncMock()
        mock_node.action_timestamps = {}
        mock_node.flood_config = {}

        mock_target = MagicMock()
        mock_target.config = {"channel": "#rizon"}
        mock_target.send = AsyncMock()

        mock_node.hub = MagicMock()
        mock_node.hub.nodes = {"rizon": mock_target}
        mock_node.db = MagicMock()
        mock_node.db.remote_net = self.repo
        mock_node.db.async_session = self.async_session

        async def get_char_mock(nick, net, session):
            stmt = select(Character).where(Character.name == nick).options(selectinload(Character.current_node))
            return (await session.execute(stmt)).scalars().first()

        mock_node.db.get_character_by_nick = get_char_mock

        # First message
        await handlers.remote_net.handle_remote_net_command(
            mock_node, "Attacker", "#2600net", "Rizon", ["msg", "Ping 1"]
        )
        self.assertTrue(mock_target.send.called)

        # Second message immediately after without waiting 60s
        mock_target.send.reset_mock()
        await handlers.remote_net.handle_remote_net_command(
            mock_node, "Attacker", "#2600net", "Rizon", ["msg", "Ping 2"]
        )
        self.assertTrue(mock_target.send.called)

    async def test_command_router_grid_state_missing_argument(self):
        """Router: 'grid state' without arguments responds with syntax error rather than falling back to grid_view."""
        mock_node = MagicMock()
        mock_node.prefix = "!a"
        mock_node.config = {"nickname": "bot"}
        mock_node.send = AsyncMock()
        mock_node.active_engine = None

        router = CommandRouter(mock_node)
        await router.dispatch("Attacker", "PRIVMSG", "#2600net", "!a grid state", is_admin=False)
        mock_node.send.assert_called_with("PRIVMSG #2600net :[ERR] Syntax: !a grid state <OPEN|CLOSED|STEALTH>")

    async def test_r2_target_name_with_brackets_resolves_cleanly(self):
        """R2: Target names surrounded by brackets resolve seamlessly across remote operations."""
        # Probe with brackets
        res_probe = await self.repo.remote_probe("Attacker", "2600net", "Rizon", "[Rizon_Open]")
        self.assertTrue(res_probe["success"])
        self.assertEqual(res_probe["name"], "Rizon_Open")

        # Siphon with brackets
        ok_siph, msg_siph, _ = await self.repo.remote_siphon("Attacker", "2600net", "Rizon", "[Rizon_Open]", percent=10.0)
        self.assertTrue(ok_siph)
        self.assertIn("Rizon_Open", msg_siph)

    async def test_r3_remote_alert_routing_catches_transport_exceptions(self):
        """R3: Alert routing handles broken socket/transport exceptions without raising unhandled asyncio errors."""
        mock_node = MagicMock()
        broken_bot = MagicMock()
        broken_bot.config = {"channel": "#rizon"}
        broken_bot.send = AsyncMock(side_effect=ConnectionResetError("Socket broken"))
        mock_node.hub = MagicMock()
        mock_node.hub.nodes = {"rizon": broken_bot}

        alert_data = {"target_network": "Rizon", "alert_msg": "Test Alert"}
        # Must execute and catch exception cleanly
        await handlers.remote_net.handle_remote_alert_routing(mock_node, alert_data)


if __name__ == "__main__":
    unittest.main()
