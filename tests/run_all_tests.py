#!/usr/bin/env python
################################################################################
# File Name: run_all_tests.py
# Purpose/Description: Run all test modules and aggregate results
# Author: Michael Cornelison
# Creation Date: 2026-01-21
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
################################################################################

"""
Comprehensive test runner that executes all test modules.

This script provides a unified way to run all tests when pytest is not available.
It discovers and runs all run_tests_*.py files in the tests directory.

Run with:
    python run_all_tests.py
    python run_all_tests.py --verbose
"""

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def parseArgs():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Run all test modules'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output'
    )
    parser.add_argument(
        '--module', '-m',
        help='Run only specific test module (e.g., "config_validator")'
    )
    return parser.parse_args()


def discoverTestRunners(projectRoot):
    """
    Discover all test runner scripts.

    Args:
        projectRoot: Path to project root directory

    Returns:
        List of test runner script paths
    """
    runners = []
    for path in projectRoot.glob('run_tests_*.py'):
        runners.append(path)
    return sorted(runners)


def runTestModule(scriptPath, verbose=False):
    """
    Run a single test module script.

    Args:
        scriptPath: Path to the test runner script
        verbose: Whether to show detailed output

    Returns:
        Tuple of (moduleName, passed, failed, success)
    """
    moduleName = scriptPath.stem.replace('run_tests_', '')

    if verbose:
        print(f"\n{'=' * 60}")
        print(f"Running: {scriptPath.name}")
        print('=' * 60)

    try:
        result = subprocess.run(
            [sys.executable, str(scriptPath)],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        output = result.stdout + result.stderr

        # Parse results from output
        passed = 0
        failed = 0
        for line in output.split('\n'):
            if 'passed' in line.lower() and 'failed' in line.lower():
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == 'passed,':
                        try:
                            passed = int(parts[i - 1])
                        except (ValueError, IndexError):
                            pass
                    if part == 'failed':
                        try:
                            failed = int(parts[i - 1])
                        except (ValueError, IndexError):
                            pass

        if verbose:
            print(output)

        success = result.returncode == 0
        return moduleName, passed, failed, success

    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT] {moduleName}")
        return moduleName, 0, 1, False
    except Exception as e:
        print(f"  [ERROR] {moduleName}: {e}")
        return moduleName, 0, 1, False


def printSummary(results):
    """
    Print summary of all test results.

    Args:
        results: List of (moduleName, passed, failed, success) tuples
    """
    totalPassed = sum(r[1] for r in results)
    totalFailed = sum(r[2] for r in results)
    totalModules = len(results)
    passingModules = sum(1 for r in results if r[3])

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    print("\nModule Results:")
    for moduleName, passed, failed, success in results:
        status = "[PASS]" if success else "[FAIL]"
        print(f"  {status} {moduleName}: {passed} passed, {failed} failed")

    print(f"\nTotal: {totalPassed} tests passed, {totalFailed} tests failed")
    print(f"Modules: {passingModules}/{totalModules} passing")
    print("=" * 60)


def main():
    """Main entry point."""
    args = parseArgs()
    projectRoot = Path(__file__).parent

    # Discover test runners
    runners = discoverTestRunners(projectRoot)

    if not runners:
        print("No test runners found (run_tests_*.py)")
        return 1

    # Filter if specific module requested
    if args.module:
        runners = [r for r in runners if args.module in r.stem]
        if not runners:
            print(f"No test runner found for module: {args.module}")
            return 1

    print(f"Discovered {len(runners)} test module(s)")

    # Run all test modules
    results = []
    for runner in runners:
        result = runTestModule(runner, verbose=args.verbose)
        results.append(result)

        # Print progress
        moduleName, passed, failed, success = result
        status = "PASS" if success else "FAIL"
        print(f"  [{status}] {moduleName}: {passed} passed, {failed} failed")

    # Print summary
    printSummary(results)

    # Return overall status
    allPassing = all(r[3] for r in results)
    return 0 if allPassing else 1


if __name__ == '__main__':
    sys.exit(main())
