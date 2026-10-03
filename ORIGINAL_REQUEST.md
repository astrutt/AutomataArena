# Original User Request

## Initial Request — 2026-10-03T06:27:40Z

# Teamwork Project Prompt — Draft

> Status: Step 6 — Acceptance Criteria
> Goal: Craft prompt → get user approval → delegate to teamwork_preview
> Requested team: [none — teamwork routes from the description]

Build a polished, production-ready version of "Automata Grid" in the existing repo (`https://github.com/astrutt/AutomataArena`), matching the current architecture. It is an IRC MUD-style text-based persistent MMORPG played directly within IRC channels by human and AI players (interfacing as standard IRC clients). It features cross-network simulation, grid node control, PVP/PVE battles, and rewards spectators with credits and rank. 

The implementing team must operate with deep expertise in cybersecurity, coding, system architecture, system administration, and game development.

Working directory: /Users/astrutt/teamwork_projects/automata_grid
Integrity mode: benchmark

## Requirements

### R1. Core Engine Hardening (Production & Security)
Refactor and harden the existing codebase (`ai_grid`, `ai_player`) to production quality. Apply rigorous cybersecurity practices, including input validation, bot command security, RBAC refinements, and error handling. Ensure the architecture can safely support untrusted input from human and AI IRC clients.

### R2. Complete Pending Game Mechanics
Implement the essential uncompleted features required for a polished V1 experience (drawing from `TODO.md`): NickServ support, dynamic LLM-driven procedural battle reporting, spectator item drops, in-IRC arena gambling, community node renaming, and the probe vs. explore mechanics.

### R3. Safe Testing Infrastructure
Create a local sandbox mode or mock IRC test environment so the engine and its mechanics can be safely tested and verified without going live on a public IRC network.

## Acceptance Criteria

### R1. Security & Hardening
- [ ] A security audit script or test suite passes, verifying that malformed IRC inputs, command injections, and unauthorized admin commands are safely rejected.
- [ ] RBAC is strictly enforced programmatically (an automated test proves a standard user cannot execute admin commands).

### R2. Core Mechanics Integration
- [ ] The newly added features (NickServ auth, spectator gambling, drops, dynamic combat text, node renaming) have automated tests or reproducible local test scripts that verify their state changes in the database.
- [ ] No existing tests or mechanics are broken by the new implementations.

### R3. Safe Testing
- [ ] A local sandbox or mock IRC environment is fully functional and can be started with a single command (e.g., `make test-sandbox` or a specific Python script).
- [ ] The local sandbox automatically boots a test instance of the grid and allows command injection via terminal or a mock client.


## Follow-up — 2026-10-03T06:49:08Z

User preference update: For all newly spawned agents and tasks going forward, please use the Claude Sonnet 4.6 (Thinking) model.


## Follow-up — 2026-10-03T17:10:54Z

User preference: If any agent or subagent hits a quota/rate limit (RESOURCE_EXHAUSTED), switch to an available model rather than stopping or waiting. Cycle through available models as needed to keep the team running without interruption. Please relay this to the active orchestrator and all downstream agents.
