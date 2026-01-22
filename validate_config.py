#!/usr/bin/env python3
################################################################################
# File Name: validate_config.py
# Purpose/Description: Validate project configuration before running
# Author: Michael Cornelison
# Creation Date: 2026-01-21
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-21    | M. Cornelison | Initial implementation
# ================================================================================
################################################################################

"""
Configuration validation script.

Run this script to validate your configuration before running the application.

Usage:
    python validate_config.py
    python validate_config.py --config path/to/config.json
    python validate_config.py --verbose
"""

import argparse
import sys
from pathlib import Path

# Add src to path
srcPath = Path(__file__).parent / 'src'
if str(srcPath) not in sys.path:
    sys.path.insert(0, str(srcPath))

from common.config_validator import ConfigValidator, ConfigValidationError
from common.secrets_loader import loadConfigWithSecrets, loadEnvFile


def printHeader(message: str) -> None:
    """Print a section header."""
    print()
    print("=" * 60)
    print(f"  {message}")
    print("=" * 60)


def printStatus(label: str, status: bool, details: str = "") -> None:
    """Print a status line with check mark or X."""
    icon = "[OK]" if status else "[X]"
    detail = f" - {details}" if details else ""
    print(f"  {icon} {label}{detail}")


def validateEnvironment(verbose: bool = False) -> bool:
    """Validate environment variables are loaded."""
    printHeader("Environment Variables")

    # Load .env file
    loaded = loadEnvFile('.env')

    if Path('.env').exists():
        printStatus(".env file exists", True)
    else:
        printStatus(".env file exists", False, "Create from .env.example")
        print()
        print("  To fix: cp .env.example .env")
        print("  Then edit .env with your values")
        return False

    # Check critical variables
    import os
    criticalVars = ['DB_SERVER', 'DB_NAME', 'API_BASE_URL']
    allPresent = True

    for var in criticalVars:
        present = var in os.environ and os.environ[var]
        printStatus(f"{var}", present, "set" if present else "missing")
        if not present:
            allPresent = False

    return allPresent


def validateConfig(configPath: str, verbose: bool = False) -> bool:
    """Validate configuration file."""
    printHeader("Configuration File")

    configFile = Path(configPath)

    if not configFile.exists():
        printStatus("Config file exists", False, f"{configPath} not found")
        return False

    printStatus("Config file exists", True, configPath)

    try:
        # Load and validate
        config = loadConfigWithSecrets(configPath)
        validator = ConfigValidator()
        config = validator.validate(config)

        printStatus("Config format valid", True)
        printStatus("Required fields present", True)
        printStatus("Secrets resolved", True)

        if verbose:
            print()
            print("  Configuration sections:")
            for key in config.keys():
                print(f"    - {key}")

        return True

    except ConfigValidationError as e:
        printStatus("Configuration valid", False, str(e))
        if e.missingFields:
            print()
            print("  Missing fields:")
            for field in e.missingFields:
                print(f"    - {field}")
        return False

    except Exception as e:
        printStatus("Configuration valid", False, str(e))
        return False


def validateDependencies(verbose: bool = False) -> bool:
    """Validate Python dependencies are installed."""
    printHeader("Dependencies")

    requiredPackages = [
        ('python-dotenv', 'dotenv'),
        ('pydantic', 'pydantic'),
    ]

    allInstalled = True

    for packageName, importName in requiredPackages:
        try:
            __import__(importName)
            printStatus(packageName, True)
        except ImportError:
            printStatus(packageName, False, "not installed")
            allInstalled = False

    if not allInstalled:
        print()
        print("  To fix: pip install -r requirements.txt")

    return allInstalled


def validateProjectStructure(verbose: bool = False) -> bool:
    """Validate project folder structure."""
    printHeader("Project Structure")

    requiredPaths = [
        'src/',
        'src/common/',
        'src/config.json',
        'tests/',
        'specs/',
        'requirements.txt',
    ]

    allExist = True

    for path in requiredPaths:
        exists = Path(path).exists()
        printStatus(path, exists)
        if not exists:
            allExist = False

    return allExist


def main() -> int:
    """Run all validations."""
    parser = argparse.ArgumentParser(description='Validate project configuration')
    parser.add_argument('--config', '-c', default='src/config.json',
                        help='Path to configuration file')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed output')
    args = parser.parse_args()

    print()
    print("Configuration Validation")
    print("========================")

    results = []

    # Run validations
    results.append(('Project Structure', validateProjectStructure(args.verbose)))
    results.append(('Dependencies', validateDependencies(args.verbose)))
    results.append(('Environment', validateEnvironment(args.verbose)))
    results.append(('Configuration', validateConfig(args.config, args.verbose)))

    # Summary
    printHeader("Summary")

    allPassed = True
    for name, passed in results:
        printStatus(name, passed)
        if not passed:
            allPassed = False

    print()
    if allPassed:
        print("All validations passed! Ready to run.")
        return 0
    else:
        print("Some validations failed. Please fix the issues above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
