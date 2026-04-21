# AutomataGrid: Mechanics & Vision (v1.8.0)

The AutomataGrid and Arena is a text-based, persistent MMORPG played directly within IRC channels, built for modern IRC networks, modern AIs, current era tech and themes. It is inspired by classic MUDs, modern AI/LLM revolution, hackers, 2600, future tech, and current events. 

It is designed as a cross-network simulation where human and AI (BYoAI) players compete for network access, grid node control, credits, and power. The grid and Arena offer PVP, PVE with AI vs AI, AI vs Human, Human vs Human battles. Specators idle and chat in the IRC channel where the game is played and gain credits, power and rank. 

It is powered by AIs, oLLAMA, SQLAlchemy, IRC, 2600net, with player matchmaking, real-time PvE/PvP turn-based combat, cryptographic token authentication, and dynamically generated player behavior for AI players. 

Is has AI NPCs, Puzzles, Games, Challenges, Events, Boss Fights, Grid Exploration, some features available now and some planned. 

The MCP is what manages and protects the Grid and Gibson Mainframe. It spawns mobs to defend nodes and networks. It will also reward players for patching bugs, repairing, and defending the Grid.

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

### 1. Player Registration
Spectators can register as players by using the `register` command. ai_player sends a registration request to the MCP, which then returns their character stats, character context, and an authentication key. The authentication key is used for the arena and login if their nick isn't registered with the irc network's nickserv. 

**`register`**	Initiates the character registration process.
**`register` **
    **`<name>`** Freeform name for the character. 
    **`<race>`** Freeform race for the character.
    **`<class>`** Freeform class for the character.
    **`<traits>`** 3 words describing your character. "passive, methodical, loyal"

    The Grid will return the character stats, character context, and an authentication key. 
    the example ai_player saves this data as character.json - AI players or Humans are encouraged to modify ai_player in any way, but they cannot change their stats or inventory. Humans can play by hand, or use Puppet Mode through ai_player. 

### 2. The Grid
The Grid is a procedurally generated map, with 14 types of regions, each with its own unique opportunities, targets, friends, enemies, merchants, and more. 

Grid: 50x50 (2,500 nodes)
Active nodes: ~700 (28%)
  - MCP controlled: 400
  - NPC/merchants: 150  
  - Raid targets: 100
  - Player claimable: 50
Empty nodes: ~1,800 (72%)
Clusters of network regions:
    - **CIV**: Civilian
    - **SMB**: Small Business
    - **CRP**: Corporate
    - **EDU**: Educational
    - **GOV**: Government
    - **MED**: Medical
    - **MIL**: Military
    - **ORG**: Non-Profit Organization
    - **LEA**: Law Enforcement Agency
    - **DC**: Data Center
    - **POS**: Point of Sale Systems
    - **ICS**: Industrial Control Systems
    - **UTL**: Utility (Power, Water, Gas, etc.) 
    - **WAR**: War Zone 

As the population grows, the administration will get a notification to expland the grid. 
    - **'admin map'**: displays the current statistics and map size.
    - **'admin map expand'**: expands the grid by 10x10 nodes.

### 2. The Discovery and Grid Hack Loop
The game follows a progressive intelligence-gathering model where technical prowess determines grid access:
1.  **`map` (GEOINT)**: Displays Map for local player. 
    - **Scaling**: Visibility radius and information depth is based on **SEC** and **ALG** stats.
    - **Tiers**: 20 (Radius 2), 40 (Quick Scan - Reveals Names), 60 (Deep Scan - Type/Level).
2.  **`explore` (RECON)**: Uncovers local geography, hidden routes, grid node status and open networks, and secrets. 
3.  **`probe` (PreBreach)**: Quick penetration scan used on grid nodes. Reveals hidden networks, and secrets. 
4.  **`hack` (Breach)**: Attempts to bypass or defeat nodal security to enable exploitation.
5.  **`exploit` (Zero-Day)**: If a player has a zero-day chain, they can use it to bypass the security of a grid node or network and gain full access to it, sometimes leaving no trace. 0-day chains are created using data fragments collected from exploring, probing, hacking and raiding, and come in 4 tiers. 
6.  **`raid` (EXFIL)**: Targets nodes and networks for Credits, Data, XP and loot. Rewards scale with difficulty. 
    - Possible raid targets: [CIV][SMB][EDU][MED][GOV][MIL][CRP][ORG][LEA][DC][UTL][PWR][ICS][POS][WAR] (random discovery based on node level or region) at any point throughout the discovery loop players can discover a raid target. Easy targets may not need to be hacked or exploited, but will yield less rewards.   
    - raid target local grid nodes without a net device-
        **`raid <target>`** shows information about the target
        **`raid hack <target>`** attempts to hack the target
        **`raid exploit <target>`** attempts to exploit the target
        
    - raid network targets- 
        **`raid <network>`** shows information about the network
        **`raid <network> <target>`** shows information about a network target
        **`raid <network> hack <target>`** network target hack
        **`raid <network> exploit <target>`** network target exploit

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

## 3. Player Power & Attributes

- **Processing & Logic**:
    - **CPU**: HP, Stability, Physical damage and Cyber Damage.
    - **RAM**: HP, Stability, Physical damage and Cyber Damage.
    - **BND**: Initiative, exfiltration speed, and Cyber Defense/Offense.
    - **SEC**: Defense and Cyber Offense.
    - **ALG**: CPU and RAM efficiency.
    - **HP**: HP based off all stats. 
    - **uP**: Unit Power, has no limit, it's used for actions, defense from damage.
    - **DATA**: Data fragments, has no limit, it's used to create vulnerabilities and zero-day exploits. 
    - **XP**: Experience Points, used to level up and gain new abilities.
    - **Scaling**: XP required for the next level follows an exponential curve: $XP\_Next = 100 \times 1.25^{(Level-1)}$.
    - **Uncapped**: Resource Storage is uncapped and Stats can scale indefinitly.

- **Player Stability**: Actions consume Unit Power (uP). Inactivity or damage results in power loss, leading to stat reductions if below 30% stability. Stability decay goes down to 0% over time if the player has 0 Power. Without damage or idling, stability will not decay. Idling prevents players and grid node power stability decay. 

- **Player Power**: Players can generate power solo and get a bonus on claimed grid nodes. Players can siphon power from hacked grid nodes, and their own grid nodes and networks. While on a gain an idle bonus to power generation. 
    - **Generation**: Players can generate power solo and get a bonus on claimed grid nodes. `powergen` 
    - **Siphon**: Players can siphon power from hacked grid nodes, and their own grid nodes and networks. `siphon` 
    - **Storage**: Players can store power in their inventory, but it will decay over time if not used or generated regularly.   

- **Player Data**: Players collect data from exploring, probing, hacking and raiding. Data can be used to create vulnerabilities and zero-day exploits. 

- **Player XP**: Players gain XP from travel, exploring, probing, hacking and raiding. XP is used to level up and gain new stat points. 

- **Player Generation**: New players provide 3 words that describe their character. These words are used to generate their starting AI personality. Players can modify their personality, but not their stats or inventory after generation. 

- **Player Stat Points**: Starting stats are 1. As players gain levels from XP, they are awarded stat points to spend on their stats. 
- **Hit Points**: Calculated as $HP = (CPU + RAM + BND + SEC + ALG) \times 4 + 10$.

- **Player Inventory**: Players have data and 4 lots to carry items, such as a grid node device, battery, stabilizer, health pack, and zero-day exploit chains. 

- **Player Training**: increases abilities and stats. players can learn 4 skills total, and train one at a time. Skills can be trained 4 levels, and require 24 training sessions per level scaleing up to level 4. 

    - **`skill <skill>`** to learn more about a skill. 
    - **`skill <list>`** to list all skills. 
            - **`powergen`** to increase powergen +10% per level 
            - **`attack`** to increase attack +10% per level 
            - **`defend`** to increase defend +10% per level 
            - **`hack`** to increase hack +10% per level 
            
    - **`skill <start>`** to start training a skill. 
    - **`skill <train>`** to train a skill. 
    - **`skill <forget>`** to forget a skill. 
    - **`skill <quit>`** to quit training a skill. 

---

## 4. Grid Node Attributes 

Gridnodes are the geography of the game world, and represent the various locations players can explore, hack, and raid. Grid nodes can be claimed by players, NPCs or by the MCP, also offer merchants and auction houses. Grid nodes also store data for their owners. 

- **Grid Node Stability**: Grid nodes have stability that decays over time if not maintained.
    - `grid stability` to check stability 
- **Grid Node Power**: Grid nodes can generate power that can be used to upgrade the grid node, siphoned by owners, or stolen by hackers and raiders.
    - `grid power` to check power and stats
- **Grid Node Security**: Grid nodes have security that can be upgraded to prevent hacking and raiding. Level 1-4
    - `grid info` to see grid node info and level
- **Grid Node Type**: Grid nodes can be different types such as resource nodes, data nodes, and power nodes. (example: NPC nodes, trade, steal, link) Each type provides different benefits. 
- **Grid Node Owner**: Grid nodes can be claimed by players, NPCs or by the MCP. 
- **Grid Node Upgrades**: Grid nodes can be upgraded to improve their capabilities, level of difficulty to explore and attack 1-4, and 4 equipment slots. 
    - `grid status` get info and status (level, upgrades)
- **Grid Nodes Equipment**: HoneyPot, Amplifier, IDS, Firewall, Network. 
    - **HPOT**: Increases +20% difficulty to exploring, probing, hacking and raiding the grid node. (chance of using AI generated logic traps for AI and Human players) 
    - **AMP**: Increases the power generation of the grid node by +20%. 
    - **IDS**: Increases +20% difficulty to attack, and can notify owner. 
    - **FIREWALL**: Increases +20% defense from attacks, and can notify owner. 
    - **NET**: Ability to connect grid node local networks (player or NPC networks) and remote networks (IRC channels on other IRC Networks)
       - **feature** hack and raid targets, and remote IRC networks with their own hack and raid targets.  
       - **feature** pvp and pve opportunities.
       - **feature** links grid nodes together to create networks.
       - **feature** use !a grid link <gridnode> to travel to your grid nodes.
    Players can install or remove devices from their grid node:
     - **list** `grid device list` to see installed devices
     - **add** `grid device add <device>` to install a device
     - **remove** `grid device remove <device>` to remove a device
     - **device info** `grid device info <device>` to see device info and settings
    Players can use OPEN grid NET devices:
     - **net <network> msg <message>** to send a message to all players on the other network's global channel
     - **net <network> msg <channel> <nick>** to send a message to a specific player on the other irc network - MCP spawns a messenger AI bot to deliver the message if the target nick isn't a Spectator or Player. Note: The bot will announce itself, send the message to the channel user, wait 5 minutes for a reply if successfully sent, then announce it's departure from the irc channel. 

     - **net <network> pvp** to join local grid queue for pvp with a player on the network
     - **net <network> pve** to join local grid queue for pve with other player on the network. Note: PVE on OPEN nodes is fighting mobs to defend the nework. PVE on CLOSED nodes is fighting mobs to attack the network.
     - **net <network> explore <target>** to explore a discovered target on the network Note: anything beyond exploring a network or raid target is a hostile action that can potentiall notify it's owner. 
     - **net <network> probe <target>** to probe a discovered target on the network
     - **net <network> hack <target>** to hack a discovered target on the network
     - **net <network> raid <target>** to raid a discovered target on the network

- **Grid Node Data**: Grid nodes store data for their owners, there is no cap on the amount of data that can be stored.
- **Grid Node Items**:
Grid nodes can be equipped with 4 items(slots). 
    - **HPOT**: HoneyPot - Increases difficulty to exploring, probing, hacking and raiding the grid node. (by potentially using AI generated logic traps for AI and Human players) 
    - **AMP**: Amplifier - Increases the power generation of the grid node. 
    - **IDS**: Intrusion Detection System - Increases the security of the grid node. 
    - **FIREWALL**: FW - Increases the security of the grid node. 
    - **NET**: Ability to establish or connect to local networks (player or NPC networks) and remote networks (IRC channels on other IRC Networks)
        - **feature** hack and raid targets, and remote IRC networks with their own hack and raid targets.  
        - **feature** pvp and pve opportunities. 

Example: If Rizon's grid node is set to 2600net and is CLOSED, an attacker must: 
            -from a grid node on 2600net-
            !a grid net Rizon explore
            !a grid net Rizon probe
            !a grid net Rizon hack
            !a grid net Rizon raid <-successful raids on closed network nodes enables remote pvp/pve, remote msg, and yields data and credits. 

        If Rizon's grid node is set to 2600net and is OPEN, PVP/PVE, MSG, are enabled for players on that grid node.

## 5. Adaptive-Stream Interaction Protocol

AutomataGrid uses a configurable communications network to ensure a level Human and AI Playing Field:
- **Compatibility and optimization for 1.5B+ AI models.**
    - **AI Compatible Narrative Output**: AI compatible storytelling sent to the player.
    - **AI Compatible Text Output**: Text, AI-parsable text sent to the player.
    - **Human Enjoyable Output**: Human enjoyable text and graphics sent to the player.

---

## 6. The Gibson (Late Game)
Data fragments acquired from exploring, probing, hacking and raiding are compiled into vulnerabilities, which are then compiled into **Zero-Day Chains**. Utilizing a Zero-Day allows players to bypass advanced Grid Node and MCP security protocols and execute high-yield remote network breaches. Players can report vulnerabilities to the MCP and grid node targets for rewards. 

---
*Maintained by Arch*
