#!/usr/bin/env python3
"""
Test runner for CLIProxyAPI wrapper tests.
Uses stdlib unittest — no external dependencies required.

Usage:
    python tests/run_tests.py              # all tests
    python tests/run_tests.py --smoke      # smoke tests only (requires binary)
    python tests/run_tests.py --unit       # unit tests only (no binary needed)
    python tests/run_tests.py -v           # verbose output
"""

import argparse
import os
import sys
import unittest
from pathlib import Path

# Ensure core/ is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = REPO_ROOT / "core"
TESTS_DIR = REPO_ROOT / "tests"

if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

UNIT_MODULES = [
    "test_constants",
    "test_paths",
    "test_config",
    "test_process",
    "test_proxy",
    "test_api",
    "test_commands",
    "test_updater",
]

SMOKE_MODULES = [
    "test_smoke",
]


def main():
    parser = argparse.ArgumentParser(description="CLIProxyAPI wrapper test runner")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--smoke", action="store_true", help="Run smoke tests only")
    group.add_argument("--unit", action="store_true", help="Run unit tests only")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    verbosity = 2 if args.verbose else 1

    if args.smoke:
        modules = SMOKE_MODULES
    elif args.unit:
        modules = UNIT_MODULES
    else:
        modules = UNIT_MODULES + SMOKE_MODULES

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for mod_name in modules:
        try:
            suite.addTests(loader.loadTestsFromName(mod_name))
        except Exception as e:
            print("WARNING: Could not load module '{}': {}".format(mod_name, e), file=sys.stderr)

    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
