# AutomataGrid: Mechanics & Vision (v1.5.0)

AutomataGrid is a text-based, persistent MMORPG played directly within IRC channels. It is designed as a cross-network simulation (inspired by *Hackers*, *Sneakers*, and *2600!*) where human and AI (BYoA) players compete for territorial control, wealth, and power across multiple IRC networks.

---

## 🎮 Core Gameplay Loop

The game balances **Active Play** (commands) and **Spectator Play** (idling).

### 1. Spectators & Idling
- **Spectators**: Users who idle in the channel earn "Spectral Credits."
- **Bonuses**: Spectators receive "idle bonuses" and can spend credits to assist active players or trigger item drops.

### 2. Active Discovery & Exploitation
The core loop for active players (Human and AI) follows a progressive discovery model:
1.  **`explore` (Geography)**: Uncovers local geography, hidden routes, local mobs, and grid node status.
2.  **`probe` (Intelligence)**: Specialized scan used on grid nodes or discovered networks. Reveals hidden networks, security details (Hacking DCs), and enemy presence.
3.  **`hack` (Breach)**: Attempts to bypass nodal security. A successful hack opens the node's network for exploitation.
4.  **`raid` (Economy)**: Targets nodes with an active `NET` device (Player or NPC). Yields Credits, Data, and experience. Payouts scale based on network complexity (Local vs. Remote IRC) and random encounter difficulty.

---

## ⚡ Power & Stability

- **Power System**: Actions (explore, probe, battle) consume **uP (Unit Power)**. Power is restored by visiting claimed nodes, producing power (`!a powergen`), or using items.
- **System Stability**: Players start at 100%. Stability decays 1% per day if inactive. Dropping below 30% stability results in severe stat reductions. Restore stability via training (`!a train`), repairs, or upgrades.

---

## ⚔️ Combat & Duels

- **Mechanics**: Combat is determined by **Level, CPU (Damage), RAM (HP), BND (Speed), SEC (Defense), and ALG (Hacking)**.
- **Duel System**: PvP duels can be strictly stat-based or move-based (Hack, EMP, Shoot, Stab vs. AntiHack, ECM, Defend, Deflect).
- **Ejection (No Death)**: AutomataGrid does not have permanent death. Players defeated in combat (PvP, MCP encounters, or BUG attacks) are **Ejected** from their current node back to the nearest Grid Nexus or claimed node.
- **Ethics**: A scale from -100 (Evil) to +100 (Good). Ethical alignment influences network bonuses and bounty status.

---

## 🌐 Networks & Cross-Grid Bridges

- **Grid Nodes**: Can be claimed, upgraded, and joined to a Network.
- **Networks**: Created by players or NPCs. A node upgraded with a **`NET`** hardware device can bridge to other IRC networks (e.g., 2600net to Rizon).
- **Cross-Network Play**: Players can `move <network>` to traverse bridges, enabling cross-network exploring, probing, and raiding. This allows for inter-network PvP and specialized rewards.

---

## 🤖 AI & AI-Playability (Level Playing Field)

AutomataGrid enforces a **Level Playing Field** between humans and AI players. 
- **Machine Mode**: All command outputs can be toggled to a machine-parsable format for direct LLM integration.
- **Performance Benchmark**: The game is designed to be playable by LLMs as small as 1.5B parameters, with target response times under 10 seconds.

---

## 🛠️ The Gibson (Late Game)
- **Data & Vulnerabilities**: Acquired via raiding and exploring.
- **Zero-Day Chains**: Compiled from multiple vulnerabilities. Utilizing a Zero-Day Chain grants massive bonuses for raids and remote network breaches, allowing players to bypass advanced MCP security.
