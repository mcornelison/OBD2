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
import subprocess
import sys
from pathlib import Path

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))
projectRoot = Path(__file__).parent.parent
sys.path.insert(0, str(projectRoot))

from obd.database import ALL_INDEXES, ALL_SCHEMAS, ObdDatabase
from scripts.verify_database import initializeAndVerify, verifyDatabase

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


# ================================================================================
# Tests: CLI (US-DBI-001)
# ================================================================================

class TestVerifyDatabaseCli:
    """Tests for the CLI entry point."""

    def test_cli_successExitCode_onInitializedDb(
        self, initializedDbPath: str
    ) -> None:
        """
        Given: An initialized database
        When: The script is run via subprocess with --db-path
        Then: Exit code is 0 (success)
        """
        # Act
        result = subprocess.run(
            [
                sys.executable,
                str(projectRoot / 'scripts' / 'verify_database.py'),
                '--db-path', initializedDbPath,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Assert
        assert result.returncode == 0

    def test_cli_failureExitCode_onFreshDb(
        self, freshDbPath: str
    ) -> None:
        """
        Given: A fresh (empty) database file
        When: The script is run via subprocess with --db-path
        Then: Exit code is 1 (failure)
        """
        # Arrange - create empty database file
        conn = sqlite3.connect(freshDbPath)
        conn.close()

        # Act
        result = subprocess.run(
            [
                sys.executable,
                str(projectRoot / 'scripts' / 'verify_database.py'),
                '--db-path', freshDbPath,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Assert
        assert result.returncode == 1

    def test_cli_initFlag_createsAndVerifies(
        self, freshDbPath: str
    ) -> None:
        """
        Given: A fresh database path (no file exists)
        When: The script is run with --init flag
        Then: Exit code is 0 (success after init)
        """
        # Act
        result = subprocess.run(
            [
                sys.executable,
                str(projectRoot / 'scripts' / 'verify_database.py'),
                '--db-path', freshDbPath,
                '--init',
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Assert
        assert result.returncode == 0
