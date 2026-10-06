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


## Follow-up — 2026-10-03T17:40:35Z

IMPORTANT directory clarification from the user: The `AutomataArena/` subdirectory is a legacy duplicate and should NOT be touched. The active codebase lives at:
- `/Users/astrutt/teamwork_projects/automata_grid/ai_grid/` — the game server and backend (manager.py, grid_db.py, grid_combat.py, grid_llm.py, models.py, etc.)
- `/Users/astrutt/teamwork_projects/automata_grid/ai_player/` — the example AI player client (bot.py)

All R1 (security hardening) and R2 (game mechanics) implementation work should target `ai_grid/` and `ai_player/` directly. Please relay this to the active orchestrator and all downstream workers immediately.


## Follow-up — 2026-10-03T18:04:17Z

Update: The `AutomataArena/` directory has been permanently deleted from the repository by the user. It no longer exists on disk. Please update PROJECT.md and any agent briefings to remove all references to it. The only active directories are `ai_grid/` (server/backend) and `ai_player/` (AI player client).


## Follow-up — 2026-10-03T22:09:11Z

Build a polished, production-ready version of "Automata Grid" in the existing repo, matching the current architecture. It is an IRC MUD-style text-based persistent MMORPG played directly within IRC channels by human and AI players (interfacing as standard IRC clients). It features cross-network simulation, grid node control, PVP/PVE battles, and rewards spectators with credits and rank.

The implementing team must operate with deep expertise in cybersecurity, coding, system architecture, system administration, and game development.

Working directory: /Users/astrutt/teamwork_projects/automata_grid
Integrity mode: benchmark

**IMPORTANT — CONTINUATION RUN**: 
The quota cooldown period has expired (current time > 18:00 EDT).
M1 (Safe Testing Infrastructure) was fully completed and verified clean.
M2 (Core Engine Hardening & Security / R1) was implemented and was in the final verification / review phase when paused.
Do NOT restart the survey phase or redo completed work. Instead:
- Read `.agents/teamwork/orchestrator_2/PROJECT.md` and related handoffs for the latest project plan and state.
- Verify M2 test suites pass (`tests/e2e/test_r1_security_hardening.py`, etc.) and push M2 through the review/challenge gate.
- Advance immediately to M3 (R2 Game Mechanics: NickServ support, spectator gambling/drops, dynamic combat text, community node renaming, probe vs. explore mechanics).
- Note: The `AutomataArena/` directory was permanently deleted. Only `ai_grid/` (server/backend) and `ai_player/` (AI player client) are active.
- If any quota/rate limit error is encountered on subagents, switch models gracefully rather than stopping.

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


## Follow-up — 2026-10-03T23:44:58Z

User preference update: Please use the current model configuration (Gemini 3.8 Flash Low) for any newly spawned subagents and tasks going forward. Relay to orchestrator_4.


## Follow-up — 2026-10-06T01:00:28Z

This is a single self-contained fix; keep it small and focused.

Implement the Spectator System passive accrual core for AutomataArena (v1.5.0), tracking IRC channel idlers and chatters in the database to award passive hourly XP, Credits, and session metrics.

Working directory: /Users/astrutt/teamwork_projects/automata_grid
Integrity mode: benchmark

## Requirements

### R1. Spectator Database Model & Repository
Define the `Spectator` model in `ai_grid/database/core.py` (inheriting from SQLAlchemy `Base`, table name `spectators`, with unique constraint on `("nick", "network")`) and create `ai_grid/database/spectator_repo.py` following the established async repository patterns (`upsert_spectator`, `record_message`, `get_spectator`, `get_all_active`, `apply_payout`, `record_idle_hours`, `reset_message_count`).

### R2. IRC Channel Activity Tracking
In `ai_grid/core/irc_client.py`, automatically track spectators on game channel activity:
- For every incoming `PRIVMSG` in the game channel from non-bot nicks, asynchronously invoke `upsert_spectator` and `record_message`.
- For every incoming `JOIN` to the game channel, asynchronously invoke `upsert_spectator`.
- Ignore bot nick and administrator nicks (`config['admins']`). Ensure calls are fire-and-forget (`asyncio.create_task`) without blocking the event loop.

### R3. Background Hourly Payout Engine
In `ai_grid/core/loops.py`, implement `spectator_payout_loop(node)` running every 3600 seconds and register it in `start_loops(node)`:
- Retrieve active spectators within the past 90 minutes.
- Calculate rewards: Base XP (10), Base Credits (5), Chat bonus (+2 credits per 10 messages since last payout, capped at +20), and Idle bonus (+1 XP per hour of session time).
- Atomically commit rewards via `apply_payout`, increment idle hours by 1.0 via `record_idle_hours`, reset message count via `reset_message_count`, and broadcast a single summary notice to the channel: `[GRID DIVIDEND] Hourly accrual distributed to N spectators.`

### R4. Spectator User Commands
In `ai_grid/core/command_router.py`, handle `!a spectator` and `!a spectator stats` via private message reply:
- `!a spectator`: Session metrics (`[SPECTATOR] {nick} | Session: {elapsed_time} | Messages: {count} | Rate: {msg/hr:.1f}`).
- `!a spectator stats`: Persistent data (`[SPECTATOR STATS] {nick} | XP: {xp} | Credits: {credits}c | Idle Hours: {idle_hours:.1f}h | Messages (lifetime): {message_count}`).
- Both commands ensure an initial spectator row exists via `upsert_spectator` and consume 1 global flood token via the centralized router rate limiter.

### R5. Constraints & Architectural Guardrails
- Do NOT modify `ai_grid/core/handlers/` combat or grid handler files.
- Do NOT modify `ai_grid/database/combat_repo.py` or `ai_grid/database/grid_repo.py`.
- Do not merge spectator records with character `players` records.
- Preserve all existing 128 tests passing with zero regressions.

## Acceptance Criteria

### Schema & Persistence
- [ ] Initializing schema via `init_schema()` creates the `spectators` table with unique constraint on `("nick", "network")`.
- [ ] Calling `upsert_spectator` creates a new record on first call and is idempotent on successive calls.
- [ ] `record_message` increments message count and refreshes `last_seen`.
- [ ] `apply_payout` atomically updates XP and credits.
- [ ] `get_all_active` filters spectators by `since_minutes` threshold (excluding idlers inactive > 90m).

### Activity & Payout Logic
- [ ] Game channel PRIVMSGs and JOINs trigger non-blocking spectator upserts while skipping admins and bot nick.
- [ ] Payout calculation accurately awards Base XP (10), Base Credits (5), Chat bonus (+2 credits per full 10 messages capped at +20), and Idle bonus (+1 XP/hr).
- [ ] Payout execution increments idle hours and resets `message_count` to 0.
- [ ] Channel broadcast message `[GRID DIVIDEND] Hourly accrual distributed to N spectators.` is sent upon distribution.

### Router & Interface Output
- [ ] `!a spectator` replies privately with expected tag format: `[SPECTATOR] {nick} | Session: {elapsed_time} | Messages: {count} | Rate: {msg/hr:.1f}`.
- [ ] `!a spectator stats` replies privately with expected tag format: `[SPECTATOR STATS] {nick} | XP: {xp} | Credits: {credits}c | Idle Hours: {idle_hours:.1f}h | Messages (lifetime): {message_count}`.
- [ ] Spectator commands deduct 1 token from the global rate limit bucket.

### Test Verification
- [ ] New comprehensive test suite `tests/test_spectator.py` passes all unit tests for model, repository, payout formula, and command routing.
- [ ] Full regression test suite (`run_tests.py`) passes all 128+ tests with zero failures or errors.
