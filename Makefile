# ==============================================================================
# Automata Grid Makefile
# ==============================================================================
# Targets for testing, local sandbox execution, linting, and environment cleanup.

# Detect Python interpreter: prefer project virtual environment, then active venv, then python3
PYTHON ?= $(shell \
	if [ -x .venv/bin/python ]; then \
		echo .venv/bin/python; \
	elif [ -n "$$VIRTUAL_ENV" ] && [ -x "$$VIRTUAL_ENV/bin/python" ]; then \
		echo "$$VIRTUAL_ENV/bin/python"; \
	elif command -v python3 >/dev/null 2>&1; then \
		echo python3; \
	else \
		echo python; \
	fi)

TEST_RUNNER := run_tests.py
SANDBOX_CLI := sandbox.py

# Optional arguments passed into sandbox or test runner
SANDBOX_ARGS ?=
TEST_ARGS ?=

.PHONY: all help test test-sandbox test-tier1 test-tier2 test-harness test-fast test-security test-mechanics clean lint

.DEFAULT_GOAL := help

help:
	@echo "Automata Grid Management & Testing Commands:"
	@echo "  make test           Run consolidated test suite via run_tests.py"
	@echo "  make test-sandbox   Start single-command interactive sandbox REPL (offline)"
	@echo "  make test-tier1     Run Tier 1 feature coverage test suite"
	@echo "  make test-tier2     Run Tier 2 boundary & corner case test suite"
	@echo "  make test-harness   Run headless programmatic sandbox harness verification"
	@echo "  make test-fast      Run tests with --failfast and --buffer flags"
	@echo "  make test-security  Run Milestone 2 security audit test suite"
	@echo "  make test-mechanics Run Milestone 3 game mechanics test suite"
	@echo "  make lint           Check code syntax and compile bytecode"
	@echo "  make clean          Clean temporary databases, cache files, and logs"
	@echo ""
	@echo "Variables:"
	@echo "  PYTHON              Python binary (current: $(PYTHON))"
	@echo "  SANDBOX_ARGS        CLI args passed to sandbox.py (e.g. --nick Player1 --role player)"
	@echo "  TEST_ARGS           CLI args passed to run_tests.py (e.g. -v -f -b)"

test:
	$(PYTHON) $(TEST_RUNNER) $(TEST_ARGS)

test-sandbox:
	$(PYTHON) $(SANDBOX_CLI) $(SANDBOX_ARGS)

test-tier1:
	$(PYTHON) $(TEST_RUNNER) --tier1 $(TEST_ARGS)

test-tier2:
	$(PYTHON) $(TEST_RUNNER) --tier2 $(TEST_ARGS)

test-harness:
	$(PYTHON) $(TEST_RUNNER) --harness $(TEST_ARGS)

test-fast:
	$(PYTHON) $(TEST_RUNNER) --failfast --buffer $(TEST_ARGS)

test-security:
	$(PYTHON) $(TEST_RUNNER) --security $(TEST_ARGS)

test-mechanics:
	$(PYTHON) $(TEST_RUNNER) --mechanics $(TEST_ARGS)

lint:
	$(PYTHON) -m compileall -q ai_grid ai_player

clean:
	@echo "Cleaning temporary test artifacts, databases, and caches..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -maxdepth 2 -type f -name "*.log" -delete 2>/dev/null || true
	find . -maxdepth 2 -type f -name "*_test.db*" -delete 2>/dev/null || true
	find . -maxdepth 2 -type f -name "test_automata_grid.db*" -delete 2>/dev/null || true
	rm -f character.json
	@echo "Cleanup complete."
