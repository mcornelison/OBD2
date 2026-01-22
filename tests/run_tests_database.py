#!/usr/bin/env python3
################################################################################
# File Name: run_tests_database.py
# Purpose/Description: Manual test runner for database module tests
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-002
# ================================================================================
################################################################################

"""
Manual test runner for database module tests.

Run with:
    python tests/run_tests_database.py
"""

import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from obd.database import (
    ObdDatabase,
    DatabaseError,
    DatabaseConnectionError,
    DatabaseInitializationError,
    createDatabaseFromConfig,
    initializeDatabase,
    ALL_SCHEMAS,
    ALL_INDEXES,
)


class TestRunner:
    """Simple test runner for manual execution."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def runTest(self, testName: str, testFunc):
        """Run a single test and track results."""
        try:
            testFunc()
            self.passed += 1
            print(f"  [PASS] {testName}")
        except AssertionError as e:
            self.failed += 1
            self.errors.append((testName, str(e)))
            print(f"  [FAIL] {testName}: {e}")
        except Exception as e:
            self.failed += 1
            self.errors.append((testName, f"Error: {e}"))
            print(f"  [ERROR] {testName}: {e}")
            traceback.print_exc()

    def report(self):
        """Print final test report."""
        total = self.passed + self.failed
        print(f"\n{'=' * 60}")
        print(f"Results: {self.passed} passed, {self.failed} failed, {total} total")
        if self.errors:
            print("\nFailures:")
            for name, error in self.errors:
                print(f"  - {name}: {error}")
        return self.failed == 0


def getTempDbPath():
    """Get a temporary database path."""
    return tempfile.mktemp(suffix='.db')


# ================================================================================
# Test Functions
# ================================================================================

def test_databaseError_init():
    """Test DatabaseError initialization."""
    error = DatabaseError("Test error", details={'key': 'value'})
    assert str(error) == "Test error"
    assert error.message == "Test error"
    assert error.details == {'key': 'value'}


def test_databaseConnectionError_inherits():
    """Test DatabaseConnectionError inherits from DatabaseError."""
    error = DatabaseConnectionError("Connection failed")
    assert isinstance(error, DatabaseError)


def test_obdDatabase_init_storesPath():
    """Test ObdDatabase stores path."""
    db = ObdDatabase('/test/path.db')
    assert db.dbPath == '/test/path.db'


def test_obdDatabase_init_defaultWalMode():
    """Test ObdDatabase defaults to WAL mode."""
    db = ObdDatabase('/test/path.db')
    assert db.walMode is True


def test_obdDatabase_init_walModeFalse():
    """Test ObdDatabase with walMode=False."""
    db = ObdDatabase('/test/path.db', walMode=False)
    assert db.walMode is False


def test_obdDatabase_isInitialized_defaultFalse():
    """Test new database is not initialized."""
    db = ObdDatabase('/test/path.db')
    assert db.isInitialized() is False


def test_obdDatabase_initialize_createsAllTables():
    """Test initialize creates all tables."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    tables = db.getTableNames()
    expectedTables = [name for name, _ in ALL_SCHEMAS]
    for tableName in expectedTables:
        assert tableName in tables, f"Missing table: {tableName}"


def test_obdDatabase_initialize_createsAllIndexes():
    """Test initialize creates all indexes."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    indexes = db.getIndexNames()
    expectedIndexes = [name for name, _ in ALL_INDEXES]
    for indexName in expectedIndexes:
        assert indexName in indexes, f"Missing index: {indexName}"


def test_obdDatabase_initialize_setsFlag():
    """Test initialize sets initialized flag."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()
    assert db.isInitialized() is True


def test_obdDatabase_initialize_idempotent():
    """Test initialize is idempotent."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()
    db.initialize()  # Should not raise
    assert db.isInitialized() is True


def test_obdDatabase_initialize_inMemory():
    """Test initialize works with in-memory database."""
    db = ObdDatabase(':memory:')
    db.initialize()
    assert db.isInitialized() is True


def test_obdDatabase_connect_providesConnection():
    """Test connect provides working connection."""
    db = ObdDatabase(':memory:')
    db.initialize()
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        assert cursor.fetchone()[0] == 1


def test_obdDatabase_connect_autoCommits():
    """Test connect auto-commits on success."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO profiles (id, name) VALUES (?, ?)",
            ('test', 'Test Profile')
        )

    # Verify persisted
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM profiles WHERE id = 'test'")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 'Test Profile'


def test_obdDatabase_getTableInfo_returnsColumns():
    """Test getTableInfo returns column information."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    columns = db.getTableInfo('realtime_data')
    columnNames = [col['name'] for col in columns]

    assert 'id' in columnNames
    assert 'timestamp' in columnNames
    assert 'parameter_name' in columnNames
    assert 'value' in columnNames


def test_obdDatabase_getStats_returnsData():
    """Test getStats returns statistics."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    stats = db.getStats()

    assert 'file_size_bytes' in stats
    assert 'table_counts' in stats
    assert 'wal_mode' in stats
    assert stats['wal_mode'] is True


def test_obdDatabase_vacuum_noError():
    """Test vacuum executes without error."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()
    db.vacuum()  # Should not raise


def test_createDatabaseFromConfig_basic():
    """Test createDatabaseFromConfig creates database."""
    dbPath = getTempDbPath()
    config = {
        'database': {
            'path': dbPath,
            'walMode': False
        }
    }

    db = createDatabaseFromConfig(config)

    assert db.dbPath == dbPath
    assert db.walMode is False


def test_createDatabaseFromConfig_defaults():
    """Test createDatabaseFromConfig uses defaults."""
    config = {}
    db = createDatabaseFromConfig(config)

    assert db.dbPath == './data/obd.db'
    assert db.walMode is True


def test_initializeDatabase_returnsInitialized():
    """Test initializeDatabase returns initialized database."""
    dbPath = getTempDbPath()
    config = {
        'database': {'path': dbPath}
    }

    db = initializeDatabase(config)

    assert db.isInitialized() is True
    assert len(db.getTableNames()) > 0


def test_realtimeData_hasRequiredColumns():
    """Test realtime_data table has required columns."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    columns = db.getTableInfo('realtime_data')
    columnNames = [col['name'] for col in columns]

    assert 'timestamp' in columnNames
    assert 'parameter_name' in columnNames
    assert 'value' in columnNames
    assert 'unit' in columnNames
    assert 'profile_id' in columnNames


def test_statistics_hasRequiredColumns():
    """Test statistics table has required columns."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    columns = db.getTableInfo('statistics')
    columnNames = [col['name'] for col in columns]

    assert 'parameter_name' in columnNames
    assert 'analysis_date' in columnNames
    assert 'profile_id' in columnNames
    assert 'max_value' in columnNames
    assert 'min_value' in columnNames
    assert 'avg_value' in columnNames
    assert 'mode_value' in columnNames
    assert 'std_1' in columnNames
    assert 'std_2' in columnNames
    assert 'outlier_min' in columnNames
    assert 'outlier_max' in columnNames


def test_aiRecommendations_hasRequiredColumns():
    """Test ai_recommendations table has required columns."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    columns = db.getTableInfo('ai_recommendations')
    columnNames = [col['name'] for col in columns]

    assert 'id' in columnNames
    assert 'timestamp' in columnNames
    assert 'recommendation' in columnNames
    assert 'priority_rank' in columnNames
    assert 'is_duplicate_of' in columnNames


def test_profiles_hasRequiredColumns():
    """Test profiles table has required columns."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    columns = db.getTableInfo('profiles')
    columnNames = [col['name'] for col in columns]

    assert 'id' in columnNames
    assert 'name' in columnNames
    assert 'description' in columnNames
    assert 'alert_config_json' in columnNames


def test_calibrationSessions_hasRequiredColumns():
    """Test calibration_sessions table has required columns."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    columns = db.getTableInfo('calibration_sessions')
    columnNames = [col['name'] for col in columns]

    assert 'session_id' in columnNames
    assert 'start_time' in columnNames
    assert 'end_time' in columnNames
    assert 'notes' in columnNames


def test_insertProfile_succeeds():
    """Test inserting a profile."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO profiles (id, name, description) VALUES (?, ?, ?)",
            ('daily', 'Daily Driving', 'Normal mode')
        )

    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM profiles WHERE id = 'daily'")
        row = cursor.fetchone()
        assert row is not None
        assert row['name'] == 'Daily Driving'


def test_insertRealtimeData_succeeds():
    """Test inserting realtime data."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    # Create profile first
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO profiles (id, name) VALUES (?, ?)",
            ('test_profile', 'Test')
        )

    # Insert data
    now = datetime.now().isoformat()
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO realtime_data (timestamp, parameter_name, value, unit, profile_id)
               VALUES (?, ?, ?, ?, ?)""",
            (now, 'RPM', 2500.0, 'rpm', 'test_profile')
        )

    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM realtime_data")
        row = cursor.fetchone()
        assert row is not None
        assert row['value'] == 2500.0


def test_allSchemas_haveTableNames():
    """Test ALL_SCHEMAS has valid entries."""
    for tableName, schema in ALL_SCHEMAS:
        assert tableName is not None
        assert len(tableName) > 0
        assert 'CREATE TABLE' in schema


def test_allIndexes_haveIndexNames():
    """Test ALL_INDEXES has valid entries."""
    for indexName, indexSql in ALL_INDEXES:
        assert indexName is not None
        assert len(indexName) > 0
        assert 'CREATE INDEX' in indexSql


def test_realtimeData_hasTimestampIndex():
    """Test realtime_data has timestamp index."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath)
    db.initialize()

    indexes = db.getIndexNames()
    assert 'IX_realtime_data_timestamp' in indexes


def test_walMode_enabled():
    """Test WAL mode is enabled when walMode=True."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath, walMode=True)
    db.initialize()

    stats = db.getStats()
    assert stats['wal_mode'] is True


def test_walMode_disabled():
    """Test WAL mode is disabled when walMode=False."""
    dbPath = getTempDbPath()
    db = ObdDatabase(dbPath, walMode=False)
    db.initialize()

    stats = db.getStats()
    assert stats['wal_mode'] is False


# ================================================================================
# Main
# ================================================================================

def main():
    """Run all tests."""
    print("=" * 60)
    print("Database Module Tests")
    print("=" * 60)

    runner = TestRunner()

    # Custom Exception Tests
    print("\nCustom Exception Tests:")
    runner.runTest("test_databaseError_init", test_databaseError_init)
    runner.runTest("test_databaseConnectionError_inherits", test_databaseConnectionError_inherits)

    # ObdDatabase Init Tests
    print("\nObdDatabase Initialization Tests:")
    runner.runTest("test_obdDatabase_init_storesPath", test_obdDatabase_init_storesPath)
    runner.runTest("test_obdDatabase_init_defaultWalMode", test_obdDatabase_init_defaultWalMode)
    runner.runTest("test_obdDatabase_init_walModeFalse", test_obdDatabase_init_walModeFalse)
    runner.runTest("test_obdDatabase_isInitialized_defaultFalse", test_obdDatabase_isInitialized_defaultFalse)

    # Schema Initialization Tests
    print("\nSchema Initialization Tests:")
    runner.runTest("test_obdDatabase_initialize_createsAllTables", test_obdDatabase_initialize_createsAllTables)
    runner.runTest("test_obdDatabase_initialize_createsAllIndexes", test_obdDatabase_initialize_createsAllIndexes)
    runner.runTest("test_obdDatabase_initialize_setsFlag", test_obdDatabase_initialize_setsFlag)
    runner.runTest("test_obdDatabase_initialize_idempotent", test_obdDatabase_initialize_idempotent)
    runner.runTest("test_obdDatabase_initialize_inMemory", test_obdDatabase_initialize_inMemory)

    # Connection Tests
    print("\nConnection Tests:")
    runner.runTest("test_obdDatabase_connect_providesConnection", test_obdDatabase_connect_providesConnection)
    runner.runTest("test_obdDatabase_connect_autoCommits", test_obdDatabase_connect_autoCommits)

    # Table Info Tests
    print("\nTable Info Tests:")
    runner.runTest("test_obdDatabase_getTableInfo_returnsColumns", test_obdDatabase_getTableInfo_returnsColumns)
    runner.runTest("test_obdDatabase_getStats_returnsData", test_obdDatabase_getStats_returnsData)

    # Utility Tests
    print("\nUtility Tests:")
    runner.runTest("test_obdDatabase_vacuum_noError", test_obdDatabase_vacuum_noError)

    # Helper Function Tests
    print("\nHelper Function Tests:")
    runner.runTest("test_createDatabaseFromConfig_basic", test_createDatabaseFromConfig_basic)
    runner.runTest("test_createDatabaseFromConfig_defaults", test_createDatabaseFromConfig_defaults)
    runner.runTest("test_initializeDatabase_returnsInitialized", test_initializeDatabase_returnsInitialized)

    # Schema Structure Tests
    print("\nSchema Structure Tests:")
    runner.runTest("test_realtimeData_hasRequiredColumns", test_realtimeData_hasRequiredColumns)
    runner.runTest("test_statistics_hasRequiredColumns", test_statistics_hasRequiredColumns)
    runner.runTest("test_aiRecommendations_hasRequiredColumns", test_aiRecommendations_hasRequiredColumns)
    runner.runTest("test_profiles_hasRequiredColumns", test_profiles_hasRequiredColumns)
    runner.runTest("test_calibrationSessions_hasRequiredColumns", test_calibrationSessions_hasRequiredColumns)

    # Data Operation Tests
    print("\nData Operation Tests:")
    runner.runTest("test_insertProfile_succeeds", test_insertProfile_succeeds)
    runner.runTest("test_insertRealtimeData_succeeds", test_insertRealtimeData_succeeds)

    # Schema Constant Tests
    print("\nSchema Constant Tests:")
    runner.runTest("test_allSchemas_haveTableNames", test_allSchemas_haveTableNames)
    runner.runTest("test_allIndexes_haveIndexNames", test_allIndexes_haveIndexNames)
    runner.runTest("test_realtimeData_hasTimestampIndex", test_realtimeData_hasTimestampIndex)

    # WAL Mode Tests
    print("\nWAL Mode Tests:")
    runner.runTest("test_walMode_enabled", test_walMode_enabled)
    runner.runTest("test_walMode_disabled", test_walMode_disabled)

    success = runner.report()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
