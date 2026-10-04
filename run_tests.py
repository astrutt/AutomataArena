#!/usr/bin/env python3
"""
run_tests.py — Consolidated Test Runner for Automata Grid.

Discovers and executes unittest suites across the repository with zero
external dependencies. Provides targeted tier execution (--tier1, --tier2,
--harness, --security, --mechanics), filtering, output buffering,
and exit codes for local development and CI pipelines.
"""

import argparse
import os
import sys
import time
import unittest
from typing import List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


TIER_MODULES = {
    "tier1": "tests.e2e.test_tier1_feature_coverage",
    "tier2": "tests.e2e.test_tier2_boundary_corner",
    "harness": "tests.test_sandbox_harness",
    "security": "tests.e2e.test_r1_security_hardening",
    "mechanics": "tests.e2e.test_r2_game_mechanics",
}


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Automata Grid Consolidated Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py                     # Run all discovered tests in tests/
  python run_tests.py --tier1             # Run Tier 1 feature coverage suite
  python run_tests.py --tier2             # Run Tier 2 boundary cases suite
  python run_tests.py --harness           # Run sandbox harness tests
  python run_tests.py -v -b               # Verbose output with stdout/stderr buffering
  python run_tests.py -k explore          # Run only tests matching substring 'explore'
  python run_tests.py tests/e2e/test_tier1_feature_coverage.py
        """,
    )

    suite_group = parser.add_argument_group("Suite Selection")
    suite_group.add_argument(
        "--tier1", action="store_true", help="Run Tier 1 feature coverage tests"
    )
    suite_group.add_argument(
        "--tier2", action="store_true", help="Run Tier 2 boundary & corner tests"
    )
    suite_group.add_argument(
        "--harness", action="store_true", help="Run programmatic sandbox harness tests"
    )
    suite_group.add_argument(
        "--security", action="store_true", help="Run R1 security hardening audit tests"
    )
    suite_group.add_argument(
        "--mechanics", action="store_true", help="Run R2 game mechanics tests"
    )
    suite_group.add_argument(
        "--all", action="store_true", help="Force run all discovered tests (default)"
    )

    discovery_group = parser.add_argument_group("Discovery Options")
    discovery_group.add_argument(
        "-s", "--start-dir", default="tests",
        help="Directory to start test discovery (default: tests)"
    )
    discovery_group.add_argument(
        "-p", "--pattern", default="test_*.py",
        help="Pattern to match test files (default: test_*.py)"
    )
    discovery_group.add_argument(
        "-t", "--top-level-dir", default=PROJECT_ROOT,
        help="Top-level project directory (default: project root)"
    )

    control_group = parser.add_argument_group("Execution Controls")
    control_group.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose test output (verbosity level 2)"
    )
    control_group.add_argument(
        "-q", "--quiet", action="store_true",
        help="Quiet test output (verbosity level 0)"
    )
    control_group.add_argument(
        "-f", "--failfast", action="store_true",
        help="Stop on first failure or error"
    )
    control_group.add_argument(
        "-b", "--buffer", action="store_true",
        help="Buffer stdout and stderr during test runs"
    )
    control_group.add_argument(
        "-k", "--filter", type=str, default="",
        help="Only run tests whose test name matches the given substring"
    )

    parser.add_argument(
        "targets", nargs="*",
        help="Optional test files, modules, or test classes/methods to run"
    )

    return parser


def filter_suite(suite: unittest.TestSuite, substring: str) -> unittest.TestSuite:
    """Filter test cases in a suite by method name substring."""
    filtered = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            sub = filter_suite(item, substring)
            if sub.countTestCases() > 0:
                filtered.addTest(sub)
        elif isinstance(item, unittest.TestCase):
            test_id = item.id().lower()
            if substring.lower() in test_id:
                filtered.addTest(item)
    return filtered


def build_suite(loader: unittest.TestLoader, args: argparse.Namespace) -> unittest.TestSuite:
    suite = unittest.TestSuite()

    # 1. Targeted positional targets
    if args.targets:
        for target in args.targets:
            target_clean = target.replace("/", ".").replace("\\", ".")
            if target_clean.endswith(".py"):
                target_clean = target_clean[:-3]
            try:
                loaded = loader.loadTestsFromName(target_clean)
                suite.addTest(loaded)
            except Exception as e:
                print(f"[ERROR] Failed to load test target '{target}': {e}", file=sys.stderr)
                sys.exit(2)
        return suite

    # 2. Targeted tier flags
    selected_tiers = []
    if args.tier1:
        selected_tiers.append("tier1")
    if args.tier2:
        selected_tiers.append("tier2")
    if args.harness:
        selected_tiers.append("harness")
    if args.security:
        selected_tiers.append("security")
    if args.mechanics:
        selected_tiers.append("mechanics")

    if selected_tiers:
        for tier in selected_tiers:
            mod_name = TIER_MODULES.get(tier)
            if mod_name:
                try:
                    loaded = loader.loadTestsFromName(mod_name)
                    suite.addTest(loaded)
                except (ImportError, AttributeError, ModuleNotFoundError) as e:
                    print(f"[WARNING] Suite '{tier}' ({mod_name}) not found or error loading: {e}", file=sys.stderr)
        return suite

    # 3. Default: Full discovery within tests/ directory (excludes venv)
    start_dir = os.path.join(PROJECT_ROOT, args.start_dir) if not os.path.isabs(args.start_dir) else args.start_dir
    if not os.path.exists(start_dir):
        print(f"[ERROR] Start directory '{start_dir}' does not exist.", file=sys.stderr)
        sys.exit(2)

    discovered = loader.discover(
        start_dir=start_dir,
        pattern=args.pattern,
        top_level_dir=args.top_level_dir,
    )
    suite.addTest(discovered)
    return suite


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()

    verbosity = 1
    if args.verbose:
        verbosity = 2
    elif args.quiet:
        verbosity = 0

    loader = unittest.TestLoader()
    suite = build_suite(loader, args)

    if args.filter:
        suite = filter_suite(suite, args.filter)

    total_tests = suite.countTestCases()
    if total_tests == 0:
        print("[INFO] No tests found matching the specified criteria.")
        return 0

    print("=" * 70)
    print(f"Automata Grid Test Runner — Executing {total_tests} test cases")
    print(f"Working Directory: {PROJECT_ROOT}")
    print(f"Python Executable: {sys.executable}")
    print("=" * 70)

    start_time = time.time()
    runner = unittest.TextTestRunner(
        verbosity=verbosity,
        failfast=args.failfast,
        buffer=args.buffer,
    )
    result = runner.run(suite)
    elapsed = time.time() - start_time

    print("-" * 70)
    print(f"Ran {result.testsRun} tests in {elapsed:.3f}s")
    print(f"Passed:   {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors:   {len(result.errors)}")
    print(f"Skipped:  {len(result.skipped)}")
    print("-" * 70)

    if result.wasSuccessful():
        print("RESULT: SUCCESS (all tests passed)")
        return 0
    else:
        print("RESULT: FAILURE (test failures or errors encountered)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
