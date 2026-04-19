# AutomataGrid: Mechanics & Vision (v1.6.0)

AutomataGrid is a text-based, persistent MMORPG played directly within IRC channels. It is designed as a cross-network simulation where human and AI (BYoAI) players compete for network access, grid node control, wealth, and power. The grid and Arena offer PVP, PVE with AI vs AI, AI vs Human, Human vs Human battles. Specators idle and chat in the IRC channel where the game is played and gain credits and ranks. 

---

## 🎮 Core Gameplay Loop

### 1. The Discovery Loop
The game follows a progressive intelligence-gathering model where technical prowess determines grid access:
1.  **`map` (GEOINT)**: Displays Map for local player. 
    - **Scaling**: Visibility radius and information depth depend on the sum of **SEC** (Security) and **ALG** (Algorithm) stats.
    - **Tiers**: 20 (Radius 2), 40 (Quick Scan - Reveals Type/Threat), 60 (Deep Scan - Reveals Names).
2.  **`explore` (RECON)**: Uncovers local geography, hidden routes, grid node status and open networks, and secrets. 
3.  **`probe` (PreBreach)**: Quick penetration scan used on grid nodes. Reveals hidden networks, and secrets. 
4.  **`hack` (Breach)**: Attempts to bypass or defeat nodal security to enable exploitation.
5.  **`exploit` (Zero-Day)**: If a player has a zero-day chain, they can use it to bypass the security of a grid node or network and gain full access to it, sometimes leaving no trace. 0-day chains are created using data fragments collected from exploring, probing, hacking and raiding, and come in 4 tiers. 
6.  **`raid` (EXFIL)**: Targets nodes and networks for Credits, Data, XP and loot. Rewards scale with difficulty.

### 2. The PVP Loop
The game allows for player vs player combat in the grid nodes and in the arena. 

1. If players encounter each other in the same grid node, they can do nothing, engage or flee. 
2. If players engage, they attack (kinetic or cyber). If the other player fails to flee, the engagement starts. 
3. Players engaged in combat can flee, attack or do nothing. 
4. Players can attack each other using kinetic or cyber attacks. 
5. Player attacks are based off CPU, RAM, BND, and SEC.
6. Player Initiative CPU, RAM, BND, and SEC.  
7. 
8. 

---

## 2. Player Power & Attributes

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
    - **Uncapped**: Resource Storage is uncapped and Stats can scale infinitely.

- **Player Stability**: Actions consume Unit Power (uP). Inactivity or damage results in power loss, leading to stat reductions if below 30% stability. Stability decay goes down to 0% over time if the player has 0 Power. Without damage or idling, stability will not decay. Idling prevents player and grid node stability decay. 

- **Player Power**: Players can generate power solo and get a bonus on claimed grid nodes. Players can siphon power from hacked grid nodes, and their own grid nodes and networks. 

- **Player Data**: Players can collect data from exploring, probing, hacking and raiding. Data can be used to create vulnerabilities and zero-day exploits. 

- **Player XP**: Players gain XP from travel, exploring, probing, hacking and raiding. XP is used to level up and gain new stat points. 

- **Player Generation**: New players provide 3 words that describe their character. These words are used to generate their starting AI personality. Players can modify their personality, but not their stats or inventory after generation. 

- **Player Stat Points**: Starting stats are 1. As players gain levels from XP, they are awarded stat points to spend on their stats. Hit points are calculated as: $HP = (CPU + RAM + BND + SEC + ALG) \times 10$. 
---

## 3. Grid Node Attributes 

Gridnodes are the geography of the game world, and represent the various locations players can explore, hack, and raid. Grid nodes can be claimed by players, NPCs or by the MCP, also offer merchants and auction houses. Grid nodes also store data for their owners. 

- **Grid Node Stability**: Grid nodes have stability that decays over time if not maintained. 
- **Grid Node Power**: Grid nodes can generate power that can be used to upgrade the grid node. 
- **Grid Node Security**: Grid nodes have security that can be upgraded to prevent hacking and raiding. 
- **Grid Node Type**: Grid nodes can be different types, such as resource nodes, data nodes, and power nodes. 
- **Grid Node Owner**: Grid nodes can be owned by players, NPCs or by the MCP. 
- **Grid Node Upgrades**: Grid nodes can be upgraded to improve their capabilities, level of difficulty to explore and attack 1-4, and 4 equipment slots. 
- **Grid Nodes Equipment**: HoneyPot, Amplifier, IDS, Firewall, Network. 
    - **HPOT**: Increases difficulty to exploring, probing, hacking and raiding the grid node. (by potentially using AI generated logic traps for AI and Human players) 
    - **AMP**: Increases the power generation of the grid node. 
    - **IDS**: Increases the security of the grid node. 
    - **FIREWALL**: Increases the security of the grid node. 
    - **NET**: Ability to establish or connect to local networks (player or NPC networks) and remote networks (IRC channels on other IRC Networks)
       - **feature** hack and raid targets, and remote IRC networks with their own hack and raid targets.  
       - **feature** pvp and pve opportunities. 
- **Grid Node Data**: Grid nodes store data for their owners, there is no cap on the amount of data that can be stored. 

--- 

## 4. Adaptive-Stream Interaction Protocol

AutomataGrid uses an adaptive communication architecture to ensure a level Human and AI Playing Field:
- **Compatibility and optimization for 1.5B+ AI models.**
    - **AI Compatible Narrative Output**: AI compatible storytelling sent to the player.
    - **AI Compatible Text Output**: Text, AI-parsable text sent to the player.
    - **Human Enjoyable Output**: Human enjoyable text and graphics sent to the player.

---

## 5. The Gibson (Late Game)
Data fragments acquired from exploring, probing, hacking and raiding are compiled into **Zero-Day Chains**. Utilizing a Zero-Day allows players to bypass advanced Grid Node and MCP security protocols and execute high-yield remote network breaches.

---
*Maintained by Mech*
