# Repository Guidelines & Behavioral Invariants

## Test Suite Execution & Token Efficiency
1. **Targeted Unit Testing First**: When developing, reviewing, or debugging specific features (e.g. spectator, economy, combat), ALWAYS run the targeted unit test file (e.g., `ai_grid/qa/tests/test_spectator.py`) rather than the monolithic test runner (`run_tests.py`).
2. **Never Re-run Heavy Suites in Iterative Review Loops**: The full test runner (`run_tests.py`) runs 128+ integration tests, executes procedural 50x50 grid generation, and takes ~10 minutes.
   - Do NOT run `run_tests.py` across multiple consecutive reviewer rounds or incremental edits.
   - Run `run_tests.py` strictly ONCE during final audit/verification before sign-off.
3. **Sandbox Sockets**: Unit tests must use mock transports or in-memory SQLite (`aiosqlite`) to avoid triggering macOS sandbox `PermissionError` on raw socket binds.
