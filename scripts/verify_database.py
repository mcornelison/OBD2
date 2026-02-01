#!/usr/bin/env python3
################################################################################
# File Name: verify_database.py
# Purpose/Description: Database verification and initialization CLI script
# Author: Ralph (Agent 1)
# Creation Date: 2026-01-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-31    | Ralph        | Initial implementation for US-DBI-001/002/003
# ================================================================================
################################################################################

"""
Database verification and initialization script for Eclipse OBD-II.

Verifies that the SQLite database has all required tables, indexes,
and WAL mode enabled. Optionally initializes a fresh database.

Usage (CLI):
    python scripts/verify_database.py --db-path ./data/obd.db
    python scripts/verify_database.py --db-path ./data/obd.db --init
    python scripts/verify_database.py --db-path ./data/obd.db --verbose

Usage (importable):
    from scripts.verify_database import verifyDatabase, initializeAndVerify

    result = verifyDatabase('./data/obd.db')
    result = initializeAndVerify('./data/obd.db')
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict

# Resolve src path relative to this script, not CWD
_scriptDir = Path(__file__).resolve().parent
_projectRoot = _scriptDir.parent
_srcPath = _projectRoot / 'src'
sys.path.insert(0, str(_srcPath))

from obd.database import ALL_INDEXES, ALL_SCHEMAS, ObdDatabase


# ================================================================================
# Exit Codes
# ================================================================================

EXIT_SUCCESS = 0
EXIT_FAILURE = 1


# ================================================================================
# Core Functions (US-DBI-003: importable module)
# ================================================================================

def verifyDatabase(dbPath: str) -> Dict[str, Any]:
    """
    Verify that a database has all required tables, indexes, and WAL mode.

    Does NOT modify the database (read-only verification).

    Args:
        dbPath: Path to the SQLite database file

    Returns:
        Results dict with keys:
            tables: {tableName: bool} - True if table exists
            indexes: {indexName: bool} - True if index exists
            walMode: bool - True if WAL journal mode is active
            recordCounts: {tableName: int} - row count per table
            fileSizeBytes: int - database file size
            allPassed: bool - True if all checks pass
    """
    tables: Dict[str, bool] = {}
    indexes: Dict[str, bool] = {}
    recordCounts: Dict[str, int] = {}
    walMode = False
    fileSizeBytes = 0
    allPassed = True

    try:
        conn = sqlite3.connect(dbPath)

        # Get existing tables from sqlite_master
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        existingTables = {row[0] for row in cursor.fetchall()}

        # Check each expected table
        for tableName, _ in ALL_SCHEMAS:
            exists = tableName in existingTables
            tables[tableName] = exists
            if not exists:
                allPassed = False

        # Get existing indexes from sqlite_master
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        existingIndexes = {row[0] for row in cursor.fetchall()}

        # Check each expected index
        for indexName, _ in ALL_INDEXES:
            exists = indexName in existingIndexes
            indexes[indexName] = exists
            if not exists:
                allPassed = False

        # Check WAL mode
        cursor = conn.execute('PRAGMA journal_mode')
        journalMode = cursor.fetchone()[0]
        walMode = journalMode == 'wal'
        if not walMode:
            allPassed = False

        # Get record counts for existing tables
        for tableName, _ in ALL_SCHEMAS:
            if tables.get(tableName):
                cursor = conn.execute(f'SELECT COUNT(*) FROM "{tableName}"')
                recordCounts[tableName] = cursor.fetchone()[0]
            else:
                recordCounts[tableName] = 0

        conn.close()

        # Get file size
        if os.path.exists(dbPath) and dbPath != ':memory:':
            fileSizeBytes = os.path.getsize(dbPath)

    except sqlite3.Error:
        # On database errors, mark everything as failed
        for tableName, _ in ALL_SCHEMAS:
            if tableName not in tables:
                tables[tableName] = False
            if tableName not in recordCounts:
                recordCounts[tableName] = 0
        for indexName, _ in ALL_INDEXES:
            if indexName not in indexes:
                indexes[indexName] = False
        allPassed = False

    return {
        'tables': tables,
        'indexes': indexes,
        'walMode': walMode,
        'recordCounts': recordCounts,
        'fileSizeBytes': fileSizeBytes,
        'allPassed': allPassed,
    }


def initializeAndVerify(dbPath: str) -> Dict[str, Any]:
    """
    Initialize the database (create tables/indexes) then verify.

    Uses ObdDatabase.initialize() which is idempotent (CREATE IF NOT EXISTS).
    Existing data is preserved.

    Args:
        dbPath: Path to the SQLite database file

    Returns:
        Results dict (same structure as verifyDatabase)
    """
    dbExists = os.path.exists(dbPath)

    db = ObdDatabase(dbPath, walMode=True)
    db.initialize()

    if dbExists:
        _printStatus('[INIT]', f'Database already exists at {dbPath}')
    else:
        _printStatus('[INIT]', f'Created database at {dbPath}')

    return verifyDatabase(dbPath)


# ================================================================================
# Output Helpers
# ================================================================================

def _printStatus(tag: str, message: str) -> None:
    """Print a status message with a tag."""
    print(f'{tag} {message}')


def _formatFileSize(sizeBytes: int) -> str:
    """Format file size in human-readable form (KB/MB)."""
    if sizeBytes < 1024:
        return f'{sizeBytes} B'
    elif sizeBytes < 1024 * 1024:
        return f'{sizeBytes / 1024:.1f} KB'
    else:
        return f'{sizeBytes / (1024 * 1024):.1f} MB'


def _printResults(result: Dict[str, Any], verbose: bool = False) -> None:
    """Print verification results as a summary."""
    print('\n=== Database Verification Results ===\n')

    # Tables
    print('Tables:')
    for tableName, exists in result['tables'].items():
        status = 'PASS' if exists else 'FAIL'
        countInfo = ''
        if exists and verbose:
            count = result['recordCounts'].get(tableName, 0)
            countInfo = f' ({count} records)'
        print(f'  [{status}] {tableName}{countInfo}')

    # Indexes
    print('\nIndexes:')
    for indexName, exists in result['indexes'].items():
        status = 'PASS' if exists else 'FAIL'
        print(f'  [{status}] {indexName}')

    # WAL mode
    walStatus = 'PASS' if result['walMode'] else 'FAIL'
    print(f'\nWAL Mode: [{walStatus}]')

    # File size
    if result['fileSizeBytes'] > 0:
        print(f'Database Size: {_formatFileSize(result["fileSizeBytes"])}')

    # WAL file size
    if result.get('walFileSizeBytes', 0) > 0:
        print(f'WAL File Size: {_formatFileSize(result["walFileSizeBytes"])}')

    # Record counts (verbose)
    if verbose:
        print('\nRecord Counts:')
        for tableName, count in result['recordCounts'].items():
            print(f'  {tableName}: {count}')

    # Overall result
    overallStatus = 'PASS' if result['allPassed'] else 'FAIL'
    print(f'\nOverall: [{overallStatus}]')


# ================================================================================
# CLI Entry Point (US-DBI-001)
# ================================================================================

def _parseArgs(args: Any = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Verify and optionally initialize the Eclipse OBD-II database.'
    )
    parser.add_argument(
        '--db-path',
        type=str,
        default=None,
        help='Path to the SQLite database file (default: from obd_config.json)'
    )
    parser.add_argument(
        '--init',
        action='store_true',
        help='Initialize the database before verification'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed output including record counts'
    )
    return parser.parse_args(args)


def _getDefaultDbPath() -> str:
    """
    Get default database path from config via secrets_loader.

    Returns:
        Resolved database path from obd_config.json
    """
    try:
        from common.secrets_loader import loadConfigWithSecrets
        configPath = str(_srcPath / 'obd_config.json')
        config = loadConfigWithSecrets(configPath)
        return config.get('database', {}).get('path', './data/obd.db')
    except Exception:
        return './data/obd.db'


def main(args: Any = None) -> int:
    """
    CLI entry point for database verification.

    Args:
        args: Command-line arguments (None for sys.argv)

    Returns:
        Exit code: 0 on success, 1 on failure
    """
    parsed = _parseArgs(args)

    dbPath = parsed.db_path
    if dbPath is None:
        dbPath = _getDefaultDbPath()

    if parsed.init:
        result = initializeAndVerify(dbPath)
    else:
        result = verifyDatabase(dbPath)

    _printResults(result, verbose=parsed.verbose)

    return EXIT_SUCCESS if result['allPassed'] else EXIT_FAILURE


if __name__ == '__main__':
    sys.exit(main())
