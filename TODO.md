# To-Do List

This document tracks active or upcoming, near-term tasks for AutomataArena.

## 🚀 Phase 1: Resource & Grid Foundation (In Progress)
- [ ] Add `Stability`, `Power`, and `Alignment` columns to `Character` model
- [ ] Update `GridNode` model for `is_hidden`, `visibility_mode`, and `irc_affinity`
- [ ] Configure `MECHANICS_CFG` in `config.json` for adjustable game balance

## ⚡ Phase 2: Action Economy & Production
- [ ] Implement `!a powergen` (Active power generation)
- [ ] Implement `!a train` (Stability recovery)
- [ ] Implement `!a repair` (Node & stability maintenance)
- [ ] Implement **Stability Decay** (1% per 24h of inactivity)
- [ ] Integrate Power costs for `move`, `attack`, `hack`, and `explore`

## 📡 Phase 3: Discovery & Cross-Network Messaging
- [ ] Expand `!a explore` with randomized discovery (Disconnected, NPC, Local, IRC)
- [ ] Implement `!a grid network msg <nick> <msg>` for IRC-bridge nodes
- [ ] Logic for **Breaching** Closed Networks (Attack/Hack requirement)

## 🏗️ Phase 4: Mainframe Manufacturing (The Gibson)
- [ ] Implement **The Gibson** background task engine
- [ ] Data Compilation logic (100 Data = 1 Tiered Vuln)
- [ ] Zero-Day Assembly (4 Vulns = 1.0/Tiered Chain)
- [ ] Shared Power Generation Pools for network-connected nodes

## 💰 Phase 5: Global Economy & Mini-Games
- [ ] Realtime Global **DarkNet Auction** (Cross-IRC sync)
- [ ] **CipherLock** mini-game for NPC breaches
- [ ] Player-vs-Player **Dice** gambling games

## 🛠️ Misc / Polish
- [ ] Text map for IRC (`x map`)
- [ ] Graphical map for web
- [ ] Dynamic Combat Flavor Text via LLM
- [ ] Spectator item drops / interaction
- [ ] Factions/Teams/Alliances system (Guild treasuries, private routing)

## ✅ Completed Tasks
- [x] Give Fighter Bots "Short-Term Memory"
- [x] Shop Viewing / Economy Discovery
- [x] Rework Pulse Logic (Pulse on queue/combat only)
- [x] Ambient World Ticker
- [x] Public Echoes/SIGACTs
- [x] Add `x options`, `x news`, `x info` commands
- [x] Node claiming mechanics
- [x] NPC Balance pass
- [x] Spectator rewards for chatting
