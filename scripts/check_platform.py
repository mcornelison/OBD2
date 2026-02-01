#!/usr/bin/env python3
################################################################################
# File Name: check_platform.py
# Purpose/Description: Verify platform configuration and dependencies
# Author: Claude
# Creation Date: 2026-01-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-23    | Claude       | Initial implementation
# ================================================================================
################################################################################

"""
Platform verification script.

Checks that the current platform is properly configured for the Eclipse OBD-II
system. Run on both Windows (development) and Raspberry Pi (production) to
verify the setup.

Usage:
    python scripts/check_platform.py
"""

import os
import platform
import sys
from pathlib import Path


def printHeader(title: str) -> None:
    """Print a formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def printCheck(name: str, available: bool, details: str = "") -> None:
    """Print a check result."""
    icon = "[OK]" if available else "[--]"
    status = "Available" if available else "Not available"
    print(f"  {icon} {name}: {status}")
    if details:
        print(f"      {details}")


def checkPlatform() -> dict:
    """Check platform information."""
    printHeader("Platform Information")

    info = {
        'system': platform.system(),
        'release': platform.release(),
        'machine': platform.machine(),
        'python': platform.python_version(),
        'is_windows': platform.system() == 'Windows',
        'is_linux': platform.system() == 'Linux',
        'is_raspberry_pi': False,
    }

    # Check if Raspberry Pi
    if info['is_linux']:
        try:
            with open('/proc/device-tree/model', 'r') as f:
                model = f.read()
                if 'Raspberry Pi' in model:
                    info['is_raspberry_pi'] = True
                    info['pi_model'] = model.strip()
        except FileNotFoundError:
            pass

    print(f"  System: {info['system']} {info['release']}")
    print(f"  Machine: {info['machine']}")
    print(f"  Python: {info['python']}")

    if info['is_raspberry_pi']:
        print(f"  Raspberry Pi: {info.get('pi_model', 'Yes')}")
    elif info['is_windows']:
        print(f"  Environment: Windows Development")
    else:
        print(f"  Environment: Linux (non-Pi)")

    return info


def checkCoreDependencies() -> None:
    """Check core dependencies available on all platforms."""
    printHeader("Core Dependencies")

    # sqlite3 (built-in)
    try:
        import sqlite3
        printCheck("sqlite3", True, f"SQLite version: {sqlite3.sqlite_version}")
    except ImportError as e:
        printCheck("sqlite3", False, str(e))

    # python-dotenv
    try:
        import dotenv
        printCheck("python-dotenv", True)
    except ImportError:
        printCheck("python-dotenv", False, "pip install python-dotenv")

    # pydantic
    try:
        import pydantic
        printCheck("pydantic", True, f"Version: {pydantic.__version__}")
    except ImportError:
        printCheck("pydantic", False, "pip install pydantic")

    # pytest
    try:
        import pytest
        printCheck("pytest", True, f"Version: {pytest.__version__}")
    except ImportError:
        printCheck("pytest", False, "pip install pytest")


def checkHardwareDependencies() -> None:
    """Check Raspberry Pi hardware dependencies."""
    printHeader("Hardware Dependencies (Raspberry Pi)")

    # OBD library
    try:
        import obd
        printCheck("obd", True, f"Version: {obd.__version__}")
    except ImportError:
        printCheck("obd", False, "pip install obd")

    # RPi.GPIO
    try:
        import RPi.GPIO
        printCheck("RPi.GPIO", True)
    except (ImportError, RuntimeError):
        printCheck("RPi.GPIO", False, "Raspberry Pi only")

    # Adafruit display
    try:
        import board
        printCheck("adafruit-blinka (board)", True)
    except (ImportError, NotImplementedError, RuntimeError):
        printCheck("adafruit-blinka (board)", False, "Raspberry Pi only")

    try:
        from adafruit_rgb_display import st7789
        printCheck("adafruit-rgb-display", True)
    except (ImportError, NotImplementedError, RuntimeError):
        printCheck("adafruit-rgb-display", False, "Raspberry Pi only")

    # Pillow
    try:
        from PIL import Image
        printCheck("Pillow", True)
    except ImportError:
        printCheck("Pillow", False, "pip install Pillow")


def checkProjectStructure() -> None:
    """Check project directory structure."""
    printHeader("Project Structure")

    projectRoot = Path(__file__).parent.parent

    requiredDirs = [
        'src/obd',
        'src/common',
        'tests',
        'data',
        'specs',
    ]

    requiredFiles = [
        'src/obd/database.py',
        'requirements.txt',
        'pyproject.toml',
    ]

    for dir in requiredDirs:
        path = projectRoot / dir
        exists = path.is_dir()
        printCheck(f"Directory: {dir}", exists)

    for file in requiredFiles:
        path = projectRoot / file
        exists = path.is_file()
        printCheck(f"File: {file}", exists)


def checkDatabase() -> None:
    """Check database connectivity."""
    printHeader("Database")

    projectRoot = Path(__file__).parent.parent
    dbPath = projectRoot / 'data' / 'obd.db'

    if dbPath.exists():
        printCheck("Database file exists", True, str(dbPath))

        # Try to connect
        try:
            sys.path.insert(0, str(projectRoot / 'src'))
            from obd.database import ObdDatabase

            db = ObdDatabase(str(dbPath))
            tables = db.getTableNames()
            stats = db.getStats()

            printCheck("Database connection", True, f"{len(tables)} tables")
            printCheck("WAL mode", stats['wal_mode'])

            totalRows = sum(stats['table_counts'].values())
            printCheck("Data", True, f"{totalRows} total rows")

        except Exception as e:
            printCheck("Database connection", False, str(e))
    else:
        printCheck("Database file exists", False, "Run: python -c \"from src.obd.database import initializeDatabase; initializeDatabase({})\"")


def main() -> int:
    """Run all platform checks."""
    print("\n" + "=" * 60)
    print("  Eclipse OBD-II Platform Check")
    print("=" * 60)

    info = checkPlatform()
    checkCoreDependencies()
    checkHardwareDependencies()
    checkProjectStructure()
    checkDatabase()

    # Summary
    printHeader("Summary")

    if info['is_raspberry_pi']:
        print("  Platform: Raspberry Pi (Production)")
        print("  Recommendation: Ensure all hardware dependencies are installed")
        print("                  pip install -r requirements-pi.txt")
    elif info['is_windows']:
        print("  Platform: Windows (Development)")
        print("  Recommendation: Use simulator mode for testing")
        print("                  python src/main.py --simulate")
    else:
        print("  Platform: Linux (Development/CI)")
        print("  Recommendation: Hardware features unavailable, use simulator")

    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
