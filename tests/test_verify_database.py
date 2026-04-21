################################################################################
# File Name: test_verify_database.py
# Purpose/Description: Tests for database verify and initialization script
# Author: Ralph (Agent 1)
# Creation Date: 2026-01-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-31    | Ralph        | Initial implementation for US-DBI-004
# 2026-04-11    | Ralph        | US-DBI-002: Add tests for [INIT] messages and
#               |              | read-only verify guarantee
# 2026-04-20    | Ralph (Rex)  | US-207 TD-017: convert CLI tests from
#               |              | subprocess.run to in-process main() calls.
#               |              | Removes Windows Store Python cold-start flake.
# ================================================================================
################################################################################

"""
Tests for the database verify and initialization script.

Covers US-DBI-001 (verify), US-DBI-002 (init mode), and US-DBI-003 (importable module).
TDD: These tests are written first, before the implementation.

Run with:
    pytest tests/test_verify_database.py -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))
projectRoot = Path(__file__).parent.parent
sys.path.insert(0, str(projectRoot))

from pi.obdii.database import ALL_INDEXES, ALL_SCHEMAS, ObdDatabase
from scripts.verify_database import (
    initializeAndVerify,
    verifyDatabase,
)
from scripts.verify_database import (
    main as verifyDatabaseCliMain,
)

# ================================================================================
# Fixtures
# ================================================================================

@pytest.fixture
def freshDbPath(tmp_path: Path) -> str:
    """Provide path to a fresh (non-existent) database file."""
    return str(tmp_path / 'test_verify.db')


@pytest.fixture
def initializedDbPath(tmp_path: Path) -> str:
    """Provide path to a fully initialized database."""
    dbPath = str(tmp_path / 'test_initialized.db')
    db = ObdDatabase(dbPath, walMode=True)
    db.initialize()
    return dbPath


@pytest.fixture
def partialDbPath(tmp_path: Path) -> str:
    """Provide path to a database missing one table (profiles)."""
    dbPath = str(tmp_path / 'test_partial.db')
    db = ObdDatabase(dbPath, walMode=True)
    db.initialize()
    # Drop the 'profiles' table to simulate a partial database
    conn = sqlite3.connect(dbPath)
    conn.execute('DROP TABLE IF EXISTS profiles')
    conn.commit()
    conn.close()
    return dbPath


@pytest.fixture
def populatedDbPath(tmp_path: Path) -> str:
    """Provide path to an initialized database with test data."""
    dbPath = str(tmp_path / 'test_populated.db')
    db = ObdDatabase(dbPath, walMode=True)
    db.initialize()
    conn = sqlite3.connect(dbPath)
    conn.execute(
        "INSERT INTO vehicle_info (vin, make, model, year) "
        "VALUES ('1HGBH41JXMN109186', 'Honda', 'Accord', 2021)"
    )
    conn.execute(
        "INSERT INTO profiles (id, name, description, created_at) "
        "VALUES ('default', 'Default', 'Default profile', datetime('now'))"
    )
    conn.commit()
    conn.close()
    return dbPath


# ================================================================================
# Tests: verifyDatabase (US-DBI-001 / US-DBI-003)
# ================================================================================

class TestVerifyDatabase:
    """Tests for the verifyDatabase function."""

    def test_verifyDatabase_freshDatabase_allPassedFalse(
        self, freshDbPath: str
    ) -> None:
        """
        Given: A fresh (empty) temp database with no tables
        When: verifyDatabase is called
        Then: Returns allPassed: False (no tables exist)
        """
        # Arrange - create an empty database file
        conn = sqlite3.connect(freshDbPath)
        conn.close()

        # Act
        result = verifyDatabase(freshDbPath)

        # Assert
        assert result['allPassed'] is False
        assert isinstance(result['tables'], dict)
        # All tables should be marked False
        for tableName, _ in ALL_SCHEMAS:
            assert result['tables'][tableName] is False

    def test_verifyDatabase_initializedDatabase_allPassedTrue(
        self, initializedDbPath: str
    ) -> None:
        """
        Given: A fully initialized database with all tables and indexes
        When: verifyDatabase is called
        Then: Returns allPassed: True
        """
        # Act
        result = verifyDatabase(initializedDbPath)

        # Assert
        assert result['allPassed'] is True
        for tableName, _ in ALL_SCHEMAS:
            assert result['tables'][tableName] is True
        for indexName, _ in ALL_INDEXES:
            assert result['indexes'][indexName] is True

    def test_verifyDatabase_missingOneTable_allPassedFalse(
        self, partialDbPath: str
    ) -> None:
        """
        Given: A database missing the 'profiles' table
        When: verifyDatabase is called
        Then: Returns allPassed: False with profiles marked False
        """
        # Act
        result = verifyDatabase(partialDbPath)

        # Assert
        assert result['allPassed'] is False
        assert result['tables']['profiles'] is False
        # Other tables should still be True
        assert result['tables']['vehicle_info'] is True
        assert result['tables']['realtime_data'] is True

    def test_verifyDatabase_walModeEnabled_returnsTrue(
        self, initializedDbPath: str
    ) -> None:
        """
        Given: An initialized database with WAL mode enabled
        When: verifyDatabase is called
        Then: walMode is True in results
        """
        # Act
        result = verifyDatabase(initializedDbPath)

        # Assert
        assert result['walMode'] is True

    def test_verifyDatabase_recordCounts_correctAfterInsert(
        self, populatedDbPath: str
    ) -> None:
        """
        Given: A database with 1 vehicle_info and 1 profile record
        When: verifyDatabase is called
        Then: recordCounts reflect the inserted data
        """
        # Act
        result = verifyDatabase(populatedDbPath)

        # Assert
        assert result['recordCounts']['vehicle_info'] == 1
        assert result['recordCounts']['profiles'] == 1
        assert result['recordCounts']['realtime_data'] == 0

    def test_verifyDatabase_resultsDictStructure(
        self, initializedDbPath: str
    ) -> None:
        """
        Given: An initialized database
        When: verifyDatabase is called
        Then: Results dict contains all required keys with correct types
        """
        # Act
        result = verifyDatabase(initializedDbPath)

        # Assert
        assert isinstance(result['tables'], dict)
        assert isinstance(result['indexes'], dict)
        assert isinstance(result['walMode'], bool)
        assert isinstance(result['recordCounts'], dict)
        assert isinstance(result['fileSizeBytes'], int)
        assert isinstance(result['allPassed'], bool)

    def test_verifyDatabase_fileSizeBytes_isPositive(
        self, initializedDbPath: str
    ) -> None:
        """
        Given: An initialized database file on disk
        When: verifyDatabase is called
        Then: fileSizeBytes is a positive integer
        """
        # Act
        result = verifyDatabase(initializedDbPath)

        # Assert
        assert result['fileSizeBytes'] > 0

    def test_verifyDatabase_readOnly_doesNotCreateTables(
        self, freshDbPath: str
    ) -> None:
        """
        Given: A fresh (empty) database with no tables
        When: verifyDatabase is called (without --init)
        Then: No tables are created (read-only verification)
        """
        # Arrange - create empty database file
        conn = sqlite3.connect(freshDbPath)
        conn.close()

        # Act
        verifyDatabase(freshDbPath)

        # Assert - database should still have no tables
        conn = sqlite3.connect(freshDbPath)
        cursor = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        tableCount = cursor.fetchone()[0]
        conn.close()
        assert tableCount == 0, "verifyDatabase must not create tables"

    def test_verifyDatabase_noExceptionsOnFailure(
        self, freshDbPath: str
    ) -> None:
        """
        Given: A fresh database that will fail verification
        When: verifyDatabase is called
        Then: No exceptions are raised; returns results with allPassed: False
        """
        # Arrange - create empty database
        conn = sqlite3.connect(freshDbPath)
        conn.close()

        # Act - should not raise
        result = verifyDatabase(freshDbPath)

        # Assert
        assert result['allPassed'] is False


# ================================================================================
# Tests: initializeAndVerify (US-DBI-002 / US-DBI-003)
# ================================================================================

class TestInitializeAndVerify:
    """Tests for the initializeAndVerify function."""

    def test_initializeAndVerify_freshDatabase_allPassedTrue(
        self, freshDbPath: str
    ) -> None:
        """
        Given: A fresh temp database path (file does not exist yet)
        When: initializeAndVerify is called
        Then: Returns allPassed: True (creates and verifies)
        """
        # Act
        result = initializeAndVerify(freshDbPath)

        # Assert
        assert result['allPassed'] is True
        for tableName, _ in ALL_SCHEMAS:
            assert result['tables'][tableName] is True
        for indexName, _ in ALL_INDEXES:
            assert result['indexes'][indexName] is True

    def test_initializeAndVerify_preservesExistingRecords(
        self, populatedDbPath: str
    ) -> None:
        """
        Given: A populated database with existing test data
        When: initializeAndVerify is called
        Then: Existing records are preserved (not deleted)
        """
        # Act
        result = initializeAndVerify(populatedDbPath)

        # Assert
        assert result['allPassed'] is True
        assert result['recordCounts']['vehicle_info'] == 1
        assert result['recordCounts']['profiles'] == 1

    def test_initializeAndVerify_walModeEnabled(
        self, freshDbPath: str
    ) -> None:
        """
        Given: A fresh database
        When: initializeAndVerify is called
        Then: WAL mode is enabled
        """
        # Act
        result = initializeAndVerify(freshDbPath)

        # Assert
        assert result['walMode'] is True

    def test_initializeAndVerify_freshDb_printsCreatedMessage(
        self, freshDbPath: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: A fresh database path (file does not exist)
        When: initializeAndVerify is called
        Then: Prints '[INIT] Created database at <path>'
        """
        # Act
        initializeAndVerify(freshDbPath)

        # Assert
        captured = capsys.readouterr()
        assert '[INIT]' in captured.out
        assert f'Created database at {freshDbPath}' in captured.out

    def test_initializeAndVerify_existingDb_printsAlreadyExistsMessage(
        self, initializedDbPath: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: An already-initialized database
        When: initializeAndVerify is called
        Then: Prints '[INIT] Database already exists at <path>'
        """
        # Act
        initializeAndVerify(initializedDbPath)

        # Assert
        captured = capsys.readouterr()
        assert '[INIT]' in captured.out
        assert f'Database already exists at {initializedDbPath}' in captured.out


# ================================================================================
# Tests: CLI (US-DBI-001)
# ================================================================================

class TestVerifyDatabaseCli:
    """Tests for the CLI entry point."""

    # US-207 TD-017 restructure: the three CLI tests below called
    # `subprocess.run([sys.executable, verify_database.py, ...])` which, under
    # Windows Store Python cold-start + heavy suite load, hit pathological
    # 30-200s spawn latency and intermittently timed out. The CLI contract
    # under test is the exit-code return from ``main(args)``; calling
    # ``main()`` in-process exercises the same code path (argparse +
    # verifyDatabase/initializeAndVerify + exit-code selection) deterministically
    # in milliseconds. No subprocess spawn, no cold start, no timeout.

    def test_cli_successExitCode_onInitializedDb(
        self, initializedDbPath: str
    ) -> None:
        """
        Given: An initialized database
        When: main() is invoked with --db-path
        Then: Exit code is 0 (success)
        """
        exitCode = verifyDatabaseCliMain(['--db-path', initializedDbPath])

        assert exitCode == 0

    def test_cli_failureExitCode_onFreshDb(
        self, freshDbPath: str
    ) -> None:
        """
        Given: A fresh (empty) database file
        When: main() is invoked with --db-path
        Then: Exit code is 1 (failure)
        """
        # Arrange - create empty database file
        conn = sqlite3.connect(freshDbPath)
        conn.close()

        exitCode = verifyDatabaseCliMain(['--db-path', freshDbPath])

        assert exitCode == 1

    def test_cli_initFlag_createsAndVerifies(
        self, freshDbPath: str
    ) -> None:
        """
        Given: A fresh database path (no file exists)
        When: main() is invoked with --init
        Then: Exit code is 0 (success after init)
        """
        exitCode = verifyDatabaseCliMain(['--db-path', freshDbPath, '--init'])

        assert exitCode == 0
