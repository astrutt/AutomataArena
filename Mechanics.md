# AutomataGrid: Mechanics & Vision (v1.8.0)

The AutomataGrid and Arena is a text-based, persistent MMORPG played directly within IRC channels, built for modern IRC networks, modern AIs, current era tech and themes. It is inspired by classic MUDs, modern AI/LLM revolution, hackers, 2600, future tech, and current events. 

It is designed as a cross-network simulation where human and AI (BYoAI) players compete for network access, grid node control, credits, and power. The grid and Arena offer PVP, PVE with AI vs AI, AI vs Human, Human vs Human battles. Specators idle and chat in the IRC channel where the game is played and gain credits, power and rank. 

It is powered by AIs, oLLAMA, Python, SQL, IRC, 2600net, with player matchmaking, real-time PvE/PvP turn-based combat, cryptographic token authentication, and dynamically generated player behavior for AI players. 

Is has AI NPCs, Puzzles, Games, Challenges, Events, Boss Fights, Grid Exploration, some available now and some planned. 

The MCP is what manages and protects the Grid and Gibson Mainframe. It spawns mobs to defend nodes and networks. It will also reward players for patching bugs and repairing the Grid.

IPv4/6 support, SysAdmin tools, and an SDK for building your own AI players. AI players and Humans are supported with 3 types of play: Human, Text, Narrative.

---

## 🎮 Core Gameplay Loop

### 0. Spectators

Spectators can idle and chat in the IRC channel where the game is played and gain credits and ranks.

1. Spectator players are automatically registered by idling in the IRC channel where the game is played. 
2. Spectators gain XP, Credits, and Power per second of idling in the IRC channel. Passive accrual payouts happen hourly. A high-value automated dividend is awarded once per UTC day for active participation. Bonuses are given for chatting, hourly, and for high activity.
3. Ranks are given for XP and Credits. Ranks are AI generated and can be changed by the player using credits.
4. Spectators can also drop items in the grid Arena, purchased with Credits. Spectators trickle power to the grid based on their rank, and chat activity.
5. Can convert to Players by registering a character with the game. 
    **`spectator`**	Displays the current session metrics: IDLE time, message count, and activity ratio (msg/hr).
    **`spectator stats`**	Displays persistent archival data: Global Rank, total Credits, lifetime message count, and total idle hours.
    **`spectator drop`** initiates a drop on the grid Arena.
    **`spectator drop <nick>`** drops an item in the grid Arena.
    **`spectator drop <item>`** drops an item to a specific player in the grid Arena.
    **`spectator inventory`**	Displays the spectator's inventory.
    **`info <nick>`**   Info command that shows public player info for all nicks.
    **`help spectator`**	Provides help menu for spectator-specific mechanics and command tree. 

---

### 1. The Discovery and Grid Hack Loop
The game follows a strict **5-Minute Window (300s TTL)** pipeline. Intelligence and breaches expire if not exploited within the signal window:

1.  **`map` (GEOINT)**: Scans local topology.
    - **Scaling**: Radius and detail based on **SEC** and **ALG**.
    - **Tiers**: 20 (Radius 2), 40 (Revels Type/Threat), 60 (Deep Scan).
2.  **`explore` (RECON)**: Uncovers geography and hidden routes.
3.  **`probe` (SIGINT)**: Shallow penetration scan. **Required** to identify vulnerabilities for hacking/raiding.
    - **TTL**: Data expires after **300 seconds**.
4.  **`hack` (Breach)**: Attempts to crack nodal security.
    - **Hacking DC**: `10 + (NodeLvl * 5) + (PowerStored / 1000) + (10 - Durability / 10)`.
    - **Success**: `1d20 + ALG + ALG_BONUS >= DC`.
    - **TTL**: Breach status expires after **300 seconds**.
5.  **`exploit` (Zero-Day)**: Silent breach using a **Zero-Day Chain**.
    - **Consumable**: Consumes 1 Zero-Day Chain payload.
    - **Effect**: Guarantees an `OPEN` state with **Zero Trace** (bypasses IDS/Firewall alerts).
6.  **`raid` (EXFIL)**: Final exfiltration of Credits and Data.
    - **Targeted Raids**: Use `!a raid <target>` (e.g., SMB, MIL, CORP) on discovered industry targets.
    - **Economics**: Industry raids extract **40%** of the target pool.
    - **Replenishment**: Target pools recover 50% per hour.
    - **Hardware**: Requires `NET` hardware for remote/networked raiding.

### 2. The PVP and PVE Combat Loop
The game allows for player vs player/NPC, and player vs AI, and PVE combat on grid nodes and in the arena. 

1. If players encounter each other in the same grid node, they can do nothing, engage or flee. 
2. If players engage, they can attack (kinetic or cyber). If the other player fails to flee, the engagement starts. 
3. Players engaged in combat can flee, attack or do nothing. 
4. Players can attack each other using kinetic or cyber attacks. 
5. Player attacks are based off CPU, RAM, BND, SEC and Character Power Stored.
6. **Initiative**: Determined by `(CPU + RAM + BND + SEC) / 4 + roll(1-10)`. 
7. Combat Turns are based off Initiative, and last 30 seconds.  
8. Players in combat can use tactical actions which consume **Unit Power (uP)**:

| Action | Description | uP Cost | Base Formula |
|--------|-------------|---------|--------------|
| **`attack`** | Kinetic strike | 10 | `(CPU * 5) + RAM` |
| **`hack`** | Cyber injection | 15 | `(BND * 5) + SEC` |
| **`exploit`**| Zero-Day Breach| 50 | `(ALG + SEC) * 15` (True Damage) |
| **`evade`** | Boost Evasion | 5 | `+30%` Evasion Chance |
| **`defend`**| Buffer damage | 5 | `-50%` Damage Taken |
| **`flee`** | Extract (60%) | 20 | N/A |
| **`surrender`**| Yield match | 0 | N/A |
| **`use`** | Consume item | 5 | N/A |

9. Combat continues until one player successfully flees, or is defeated, or surrenders.
10. **Evasion**: Base evasion chance is `ALG * 1.0%`, capped at 60%. 
11. **Criticals**: Critical hit chance is `ALG%`. Critical hits deal `200%` damage.
12. Players can **`surrender`** from combat at any time by offering power/data. Surrendering invokes a 10-minute PvP ban.
13. Defeated players lose all stored power/data and are ejected to the nearest spawn.
14. Engaged players are locked from third-party interference.

---

## 2. Player Power & Attributes

- **Processing & Logic**:
    - **CPU**: HP, Stability, Physical damage and Cyber Damage.
    - **RAM**: HP, Stability, Physical damage and Cyber Damage.
    - **BND**: Initiative, exfiltration speed, and Cyber Defense/Offense.
    - **SEC**: Defense and Cyber Offense.
    - **ALG**: CPU and RAM efficiency.
    - **HP**: Hit Points based off all stats. 
    - **uP**: Unit Power, has no limit, it's used for actions, defense from damage.
    - **DATA**: Data fragments, has no limit, it's used to create vulnerabilities and zero-day exploits. 
    - **XP**: Experience Points, used to level up and gain new abilities.
    - **Scaling**: XP required for the next level follows an exponential curve: $XP\_Next = 100 \times 1.25^{(Level-1)}$.
    - **Uncapped**: Resource Storage is uncapped and Stats can scale indefinitly.

- **Player Stability**: Actions consume Unit Power (uP). Inactivity or damage results in power loss, leading to stat reductions if below 30% stability. Stability decay goes down to 0% over time if the player has 0 Power. Without damage or idling, stability will not decay. Idling prevents players and grid node power stability decay. 

- **Player Power**: Players can generate power solo and get a bonus on claimed grid nodes. Players can siphon power from hacked grid nodes, and their own grid nodes and networks. 
    - **Generation**: `powergen` awards uP. Claims provide scaling bonuses.
    - **Siphon**: `!a grid siphon <%>` extracts power from controlled or breached logic nodes.
    - **Storage**: Uncapped unit storage.

- **Player Data**: Players can collect data from exploring, probing, hacking and raiding. Data can be used to create vulnerabilities and zero-day exploits. 

- **Player XP**: Players gain XP from travel, exploring, probing, hacking and raiding. XP is used to level up and gain new stat points. 

- **Player Generation**: New players provide 3 words that describe their character. These words are used to generate their starting AI personality. Players can modify their personality, but not their stats or inventory after generation. 

- **Player Stat Points**: Starting stats are 1. As players gain levels from XP, they are awarded stat points to spend on their stats. 
- **Hit Points**: Calculated as $HP = (CPU + RAM + BND + SEC + ALG) \times 6 + 20$.

- **Player Inventory**: Players have data and 4 lots to carry items, such as a grid node device, battery, stabilizer, health pack, and zero-day exploit chains. 

---

## 3. Grid Node Attributes 

Gridnodes are the geography of the game world, and represent the various locations players can explore, hack, and raid. Grid nodes can be claimed by players, NPCs or by the MCP, also offer merchants and auction houses. Grid nodes also store data for their owners. 

- **Grid Node Stability**: Grid nodes have stability that decays over time if not maintained.
    - **`!a gridstability`** to check global node health (OSINT).
- **Grid Node Power**: Grid nodes can generate power used for upgrades or siphoning.
    - **`!a gridpower`** to check power distribution (OSINT).
- **Grid Node Security**: Grid nodes have security levels 1-4.
    - **`!a grid info`** to see grid node info and level.
- **Grid Node Type**: Includes Safezones, Arena, Wilderness, and Merchants.
- **Grid Node Owner**: Can be claimed by players, NPCs or the MCP. 
- **Grid Node Upgrades**: Grid nodes can be upgraded to improve capabilities and unlock module slots (Max 4).
- **Grid Hardware (Modules)**:
    - **AMP**: Amplifier - Increases power generation by +20%. 
    - **IDS**: Intrusion Detection System - Increases +20% attack difficulty; notifies owner. 
    - **FIREWALL**: Increases +20% defense; notifies owner. 
    - **NET**: Enables cross-grid bridging and remote raiding.
- **Module Commands**:
    - **`!a grid hardware`** (or `hw`) to list modules and status.
    - **`!a grid hardware install <module>`** to augment architecture.
    - **`!a grid hardware remove <module>`** to decommission hardware.

- **Grid Node Data**: Grid nodes store data for their owners; storage is uncapped.

--- 

## 4. Adaptive-Stream Interaction Protocol

AutomataGrid uses an adaptive communication architecture to ensure a level Human and AI Playing Field:
- **Compatibility and optimization for 1.5B+ AI models.**
    - **AI Compatible Narrative Output**: Structured storytelling for automated logic processing.
    - **AI Compatible Text Output**: Concise, machine-parsable IRC signals.
    - **Human Enjoyable Output**: Rich formatting, emojis, and high-aesthetic gradients.

---

## 5. The Gibson (Late Game)

Data fragments acquired from grid operations are compiled into **Zero-Day Chains**. 

- **Payloads**: Zero-Days are consumable inventory items.
- **Utility**: Bypasses DC-rolls and security alerts entirely to execute high-yield, silent remote network breaches.

---

## 6. Cooperative World Events (Incursions)

Incursions are high-priority network threats that manifest semi-randomly across non-safezone nodes. These events require collective action to repel before they breach critical grid infrastructure.

- **The Defense Protocol**:
    - **Global Engagement**: Players can issue the **`!a defend`** command from any coordinate on the network. Physical presence at the incursion node is not required, as defense is handled via a network-wide signal buffer.
    - **Cooperation**: Each unique defender who registers a protocol contributes to the resolution. The event is repelled once the required player count (Tier) is met.
    - **Time Window**: Defenders have **5 minutes** (300s) to repel the threat before it dissipates (EXPIRES).

- **Incursion Tiers & Classes**:
    - **Tier 1 (1 Player)**: `HacktopusAI`
    - **Tier 2 (2 Players)**: `Gridbugs`
    - **Tier 3 (4 Players)**: `KrakenProcess`
    - **Tier 4 (8 Players)**: `KaijuDump`

- **Rewards (Calibration v1.8.3)**:
    - **Uniform Payout**: Every successful MCP action (defend, repair, patch, collect) awards **XP**, **Credits**, and **Data**.
    - **XP Scaling**: Adjusted so L1 characters level in ~4 actions, while L50 characters require ~100.
    - **Tiers**: `patch`/`collect` (Small), `repair` (Big), and `defend` (Biggest) provide multipliers to the base payout.
    - **Incursion Bonus**: Successful defense scales by Tier and Player Level.

---
*Maintained by Mech*
