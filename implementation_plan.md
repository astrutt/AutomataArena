# Implementation Plan: AutomataGrid v2.0 Procedural Grid Re-Design

This plan details the transition from a manually connected graph-based topology to a procedurally generated, coordinate-based 50x50 grid with dynamic expansion mechanics.

## User Review Required

> [!IMPORTANT]
> **Data Reset**: This transition fundamentally changes the grid topology. Existing `NodeConnection` data will be deprecated, and current character locations will likely need to be reset to the new `Spawn` coordinate (25, 25).
> **Math Rebalance**: Starting node power (1M uP) and Level (4) represent a significant inflation compared to current Level 1 wilderness.

## Proposed Changes

### [Database Layer]

#### [MODIFY] [models.py](file:///Users/astrutt/Documents/AutomataGrid/ai_grid/models.py)
- **GridNode**:
    - Add `x = Column(Integer, index=True)` and `y = Column(Integer, index=True)`.
    - Add `is_unlocked = Column(Boolean, default=False)`.
    - Add `cluster_id = Column(Integer, nullable=True)`.

#### [MODIFY] [grid_db.py](file:///Users/astrutt/Documents/AutomataGrid/ai_grid/grid_db.py)
- Implement `generate_master_grid(width=50, height=50)`:
    - Procedurally place 700 active nodes using a clustered distribution algorithm.
    - Set Spawn at (25, 25).
    - Map Network Home Nodes to specific coordinates.
- Update `seed_grid_expansion`:
    - Incorporate the Level 4 / 1M Power / 100% Stability requirement for starting nodes.

### [Repository Layer]

#### [MODIFY] [navigation_repo.py](file:///Users/astrutt/Documents/AutomataGrid/ai_grid/database/repositories/navigation_repo.py)
- Refactor `move_player` to use coordinate math (+1/-1 X or Y) instead of `NodeConnection` lookups.
- Refactor `get_location` to provide coordinate-aware SITREP data.

#### [MODIFY] [discovery_repo.py](file:///Users/astrutt/Documents/AutomataGrid/ai_grid/database/repositories/discovery_repo.py)
- Update `map` (GEOINT) logic to use coordinate radius instead of graph hops.
- Update `explore`/`probe` success thresholds to align with the new Level 4 node standards.

#### [NEW] [expansion_repo.py](file:///Users/astrutt/Documents/AutomataGrid/ai_grid/database/repositories/expansion_repo.py)
- Implement `check_expansion_trigger()`: Monitors player count and toggles `is_unlocked` for neighboring clusters/sectors.

### [Core/Manager Layer]

#### [MODIFY] [manager.py](file:///Users/astrutt/Documents/AutomataGrid/ai_grid/manager.py)
- Monitor population thresholds and log expansion readiness. No automatic sector unlocking.

#### [NEW] [Admin Handler]
- Implement `!a admin map`: Displays grid statistics, population density, and expansion readiness notifications. Includes manual trigger for sector unlocking.

## Configuration & Policies

> [!NOTE]
> 1. **Expansion Thresholds**: Log recommendation for expansion when player-to-active-node density exceeds healthy thresholds.
> 2. **Migration**: All nodes start as **unclaimed** for the v2.0 launch. Existing character locations reset to (25, 25).
> 3. **Empty Node Interaction**: Players **can move freely** across the entire 50x50 grid; empty nodes function as reachable wilderness. Expansion focuses on "active" node deployment (MCP, Merchants, etc.).

## Verification Plan

### Automated Tests
- `pytest tests/test_grid_procedural.py`: Verify grid distribution (MCP vs NPC counts) and coordinate-based movement.
- `pytest tests/test_expansion.py`: Simulate player growth to verify sector unlocking.

### Manual Verification
- Join the grid and use `move north` to verify coordinate incrementing.
- Verify `map` displays nearby coordinates correctly.
