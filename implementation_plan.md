# Implementation Plan - Task 048 Remediation: Centralized Pacing

This plan resolves the audit failure where `move` and `economy` commands bypassed the anti-flood system. It centralizes token consumption in the CommandRouter and refactors the rate-limiter to support command-specific intervals without double-consuming tokens.

## User Review Required

> [!IMPORTANT]
> **Central Pacing**: Every command prefixed with `!a ` will now consume 1 token immediately upon dispatch. This ensures no command can bypass the global 1 msg / 2s limit.
> **Dual-Mode Rate Limiting**: The `check_rate_limit` function will be refactored to support a `consume=False` mode, allowing handlers to check for long-interval cooldowns (e.g., 30s for Probe) without penalizing the user twice.

## Proposed Changes

### [Core Engine]

#### [MODIFY] [handlers/base.py](file:///Users/astrutt/Documents/AutomataGrid/ai_grid/core/handlers/base.py)
- Update `check_rate_limit` to support `consume: bool = True`.
- Implement logic to check `cooldown` against `last_action`.
- Ensure token consumption only happens when `consume=True`.

#### [MODIFY] [command_router.py](file:///Users/astrutt/Documents/AutomataGrid/ai_grid/core/command_router.py)
- Import `check_rate_limit` from `handlers.base`.
- Insert a global `check_rate_limit(..., consume=True)` check at the start of the game command block (line 25 approx).
- This protects `move`, `economy`, and all other previously uncovered commands.

### [Handlers Synchronization]

#### [MODIFY] [handlers/grid.py](file:///Users/astrutt/Documents/AutomataGrid/ai_grid/core/handlers/grid.py) / [handlers/combat.py](file:///Users/astrutt/Documents/AutomataGrid/ai_grid/core/handlers/combat.py)
- Update all existing `check_rate_limit` calls in handlers (Explore, Probe, Exploit, Loot, PvP) to use `consume=False`.
- This ensures they correctly enforce the 10s-120s intervals using the `last_action` timestamp updated by the router.

## Open Questions
None. The goal is parity with the original Task 048 intent but with central enforcement.

## Verification Plan

### Automated Tests
- Update `ai_grid/scratch/test_anti_flood.py` to:
    - Verify that `move` (unprotected before) now consumes tokens.
    - Verify that `economy` (unprotected before) now consumes tokens.
    - Verify that `explore` (protected in handler) enforces 15s but only consumes **one** token total.

### Manual Verification
- Spam `!a move n` and verify pacing messages.
- Spam `!a grid map` and verify pacing messages.
