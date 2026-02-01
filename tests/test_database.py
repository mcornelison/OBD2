################################################################################
# File Name: test_database.py
# Purpose/Description: Tests for OBD-II SQLite database module
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
Tests for the OBD-II database module.

Run with:
    pytest tests/test_database.py -v
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from obd.database import (
    ALL_INDEXES,
    ALL_SCHEMAS,
    DatabaseConnectionError,
    DatabaseError,
    DatabaseInitializationError,
    ObdDatabase,
    createDatabaseFromConfig,
    initializeDatabase,
)

# ================================================================================
# Fixtures
# ================================================================================

@pytest.fixture
def tempDbPath(tmp_path: Path) -> str:
    """Provide temporary database path."""
    return str(tmp_path / 'test_obd.db')


@pytest.fixture
def memoryDb() -> ObdDatabase:
    """Provide in-memory database."""
    return ObdDatabase(':memory:')


@pytest.fixture
def initializedDb(tempDbPath: str) -> ObdDatabase:
    """Provide initialized database."""
    db = ObdDatabase(tempDbPath)
    db.initialize()
    return db


@pytest.fixture
def validConfig(tempDbPath: str) -> dict[str, Any]:
    """Provide valid database configuration."""
    return {
        'database': {
            'path': tempDbPath,
            'walMode': True
        }
    }


# ================================================================================
# Custom Exception Tests
# ================================================================================

class TestDatabaseError:
    """Tests for DatabaseError exception."""

    def test_init_withMessage_storesMessage(self):
        """
        Given: Error message
        When: DatabaseError is created
        Then: Message is accessible
        """
        error = DatabaseError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"

    def test_init_withDetails_storesDetails(self):
        """
        Given: Error with details
        When: DatabaseError is created
        Then: Details are accessible
        """
        error = DatabaseError("Test", details={'path': '/test/path'})
        assert error.details == {'path': '/test/path'}

    def test_init_noDetails_defaultsToEmptyDict(self):
        """
        Given: Error without details
        When: DatabaseError is created
        Then: Details defaults to empty dict
        """
        error = DatabaseError("Test")
        assert error.details == {}


class TestDatabaseConnectionError:
    """Tests for DatabaseConnectionError exception."""

    def test_inheritsFromDatabaseError(self):
        """
        Given: DatabaseConnectionError
        When: Checking inheritance
        Then: Is subclass of DatabaseError
        """
        error = DatabaseConnectionError("Connection failed")
        assert isinstance(error, DatabaseError)


class TestDatabaseInitializationError:
    """Tests for DatabaseInitializationError exception."""

    def test_inheritsFromDatabaseError(self):
        """
        Given: DatabaseInitializationError
        When: Checking inheritance
        Then: Is subclass of DatabaseError
        """
        error = DatabaseInitializationError("Init failed")
        assert isinstance(error, DatabaseError)


# ================================================================================
# ObdDatabase Initialization Tests
# ================================================================================

class TestObdDatabaseInit:
    """Tests for ObdDatabase initialization."""

    def test_init_withPath_storesPath(self, tempDbPath: str):
        """
        Given: Database path
        When: ObdDatabase is created
        Then: Path is stored
        """
        db = ObdDatabase(tempDbPath)
        assert db.dbPath == tempDbPath

    def test_init_defaultWalMode_isTrue(self, tempDbPath: str):
        """
        Given: No walMode specified
        When: ObdDatabase is created
        Then: walMode defaults to True
        """
        db = ObdDatabase(tempDbPath)
        assert db.walMode is True

    def test_init_walModeFalse_storesValue(self, tempDbPath: str):
        """
        Given: walMode=False
        When: ObdDatabase is created
        Then: walMode is False
        """
        db = ObdDatabase(tempDbPath, walMode=False)
        assert db.walMode is False

    def test_init_notInitialized(self, tempDbPath: str):
        """
        Given: New ObdDatabase
        When: Checking initialized state
        Then: isInitialized returns False
        """
        db = ObdDatabase(tempDbPath)
        assert db.isInitialized() is False


# ================================================================================
# ObdDatabase.initialize() Tests
# ================================================================================

class TestObdDatabaseInitialize:
    """Tests for database schema initialization."""

    def test_initialize_createsAllTables(self, tempDbPath: str):
        """
        Given: New database
        When: initialize() is called
        Then: All required tables are created
        """
        db = ObdDatabase(tempDbPath)
        db.initialize()

        tables = db.getTableNames()

        # Check all schema tables exist
        expectedTables = [name for name, _ in ALL_SCHEMAS]
        for tableName in expectedTables:
            assert tableName in tables, f"Missing table: {tableName}"

    def test_initialize_createsAllIndexes(self, tempDbPath: str):
        """
        Given: New database
        When: initialize() is called
        Then: All required indexes are created
        """
        db = ObdDatabase(tempDbPath)
        db.initialize()

        indexes = db.getIndexNames()

        # Check all indexes exist
        expectedIndexes = [name for name, _ in ALL_INDEXES]
        for indexName in expectedIndexes:
            assert indexName in indexes, f"Missing index: {indexName}"

    def test_initialize_setsInitializedFlag(self, tempDbPath: str):
        """
        Given: New database
        When: initialize() is called
        Then: isInitialized returns True
        """
        db = ObdDatabase(tempDbPath)
        db.initialize()

        assert db.isInitialized() is True

    def test_initialize_isIdempotent(self, tempDbPath: str):
        """
        Given: Already initialized database
        When: initialize() is called again
        Then: No error occurs
        """
        db = ObdDatabase(tempDbPath)
        db.initialize()
        db.initialize()  # Should not raise

        assert db.isInitialized() is True

    def test_initialize_createsParentDirectories(self, tmp_path: Path):
        """
        Given: Database path with non-existent parent directories
        When: initialize() is called
        Then: Parent directories are created
        """
        deepPath = str(tmp_path / 'a' / 'b' / 'c' / 'test.db')
        db = ObdDatabase(deepPath)
        db.initialize()

        assert os.path.exists(deepPath)

    def test_initialize_returnsTrue(self, tempDbPath: str):
        """
        Given: Valid database path
        When: initialize() is called
        Then: Returns True
        """
        db = ObdDatabase(tempDbPath)
        result = db.initialize()

        assert result is True

    def test_initialize_inMemoryDb_works(self):
        """
        Given: In-memory database path
        When: initialize() is called
        Then: Initialization succeeds
        """
        db = ObdDatabase(':memory:')
        db.initialize()

        assert db.isInitialized() is True


# ================================================================================
# ObdDatabase.connect() Tests
# ================================================================================

class TestObdDatabaseConnect:
    """Tests for database connection management."""

    def test_connect_contextManager_providesConnection(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Using connect() context manager
        Then: Valid connection is provided
        """
        with initializedDb.connect() as conn:
            assert conn is not None
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            assert cursor.fetchone()[0] == 1

    def test_connect_autoCommits_onSuccess(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Making changes in context manager
        Then: Changes are committed automatically
        """
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO profiles (id, name) VALUES (?, ?)",
                ('test', 'Test Profile')
            )

        # Verify data persisted
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM profiles WHERE id = 'test'")
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == 'Test Profile'

    def test_connect_rollbackOnException(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Exception occurs in context manager
        Then: Changes are rolled back
        """
        try:
            with initializedDb.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO profiles (id, name) VALUES (?, ?)",
                    ('rollback_test', 'Test')
                )
                raise ValueError("Force rollback")
        except ValueError:
            pass

        # Verify data was NOT persisted
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM profiles WHERE id = 'rollback_test'")
            assert cursor.fetchone() is None

    def test_connect_enablesWalMode(self, tempDbPath: str):
        """
        Given: Database with walMode=True
        When: Connecting
        Then: WAL mode is enabled
        """
        db = ObdDatabase(tempDbPath, walMode=True)
        db.initialize()

        stats = db.getStats()
        assert stats['wal_mode'] is True

    def test_connect_walModeDisabled_usesDelete(self, tempDbPath: str):
        """
        Given: Database with walMode=False
        When: Connecting
        Then: WAL mode is not enabled
        """
        db = ObdDatabase(tempDbPath, walMode=False)
        db.initialize()

        stats = db.getStats()
        assert stats['wal_mode'] is False

    def test_connect_enablesForeignKeys(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Connecting
        Then: Foreign key constraints are enabled
        """
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('PRAGMA foreign_keys')
            result = cursor.fetchone()[0]
            assert result == 1


# ================================================================================
# Schema Verification Tests
# ================================================================================

class TestSchemaStructure:
    """Tests verifying database schema structure."""

    def test_realtimeData_hasRequiredColumns(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Checking realtime_data table
        Then: All required columns exist
        """
        columns = initializedDb.getTableInfo('realtime_data')
        columnNames = [col['name'] for col in columns]

        assert 'id' in columnNames
        assert 'timestamp' in columnNames
        assert 'parameter_name' in columnNames
        assert 'value' in columnNames
        assert 'unit' in columnNames
        assert 'profile_id' in columnNames

    def test_realtimeData_hasTimestampIndex(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Checking indexes
        Then: realtime_data has timestamp index
        """
        indexes = initializedDb.getIndexNames()
        assert 'IX_realtime_data_timestamp' in indexes

    def test_statistics_hasRequiredColumns(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Checking statistics table
        Then: All required columns exist
        """
        columns = initializedDb.getTableInfo('statistics')
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

    def test_aiRecommendations_hasRequiredColumns(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Checking ai_recommendations table
        Then: All required columns exist
        """
        columns = initializedDb.getTableInfo('ai_recommendations')
        columnNames = [col['name'] for col in columns]

        assert 'id' in columnNames
        assert 'timestamp' in columnNames
        assert 'recommendation' in columnNames
        assert 'priority_rank' in columnNames
        assert 'is_duplicate_of' in columnNames
        assert 'profile_id' in columnNames

    def test_profiles_hasRequiredColumns(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Checking profiles table
        Then: All required columns exist
        """
        columns = initializedDb.getTableInfo('profiles')
        columnNames = [col['name'] for col in columns]

        assert 'id' in columnNames
        assert 'name' in columnNames
        assert 'description' in columnNames
        assert 'alert_config_json' in columnNames
        assert 'created_at' in columnNames

    def test_calibrationSessions_hasRequiredColumns(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Checking calibration_sessions table
        Then: All required columns exist
        """
        columns = initializedDb.getTableInfo('calibration_sessions')
        columnNames = [col['name'] for col in columns]

        assert 'session_id' in columnNames
        assert 'start_time' in columnNames
        assert 'end_time' in columnNames
        assert 'notes' in columnNames
        assert 'profile_id' in columnNames

    def test_vehicleInfo_hasVinAsPrimaryKey(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Checking vehicle_info table
        Then: VIN is the primary key
        """
        columns = initializedDb.getTableInfo('vehicle_info')
        vinCol = next((c for c in columns if c['name'] == 'vin'), None)

        assert vinCol is not None
        assert vinCol['pk'] == 1  # Primary key

    def test_staticData_hasForeignKeyToVehicleInfo(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Checking static_data table
        Then: Has foreign key to vehicle_info
        """
        columns = initializedDb.getTableInfo('static_data')
        vinCol = next((c for c in columns if c['name'] == 'vin'), None)

        assert vinCol is not None


# ================================================================================
# Data Operations Tests
# ================================================================================

class TestDataOperations:
    """Tests for data insertion and retrieval."""

    def test_insertProfile_succeeds(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Inserting a profile
        Then: Profile is stored
        """
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO profiles (id, name, description, alert_config_json)
                   VALUES (?, ?, ?, ?)""",
                ('daily', 'Daily Driving', 'Normal driving mode', '{"rpmRedline": 6500}')
            )

        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM profiles WHERE id = 'daily'")
            row = cursor.fetchone()

            assert row is not None
            assert row['name'] == 'Daily Driving'

    def test_insertRealtimeData_succeeds(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database with profile
        When: Inserting realtime data
        Then: Data is stored with timestamp
        """
        # Create profile first
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO profiles (id, name) VALUES (?, ?)",
                ('test_profile', 'Test')
            )

        # Insert realtime data
        now = datetime.now().isoformat()
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO realtime_data (timestamp, parameter_name, value, unit, profile_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (now, 'RPM', 2500.0, 'rpm', 'test_profile')
            )

        # Verify
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM realtime_data WHERE parameter_name = 'RPM'")
            row = cursor.fetchone()

            assert row is not None
            assert row['value'] == 2500.0
            assert row['unit'] == 'rpm'

    def test_insertStatistics_succeeds(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database with profile
        When: Inserting statistics
        Then: Statistics are stored with all fields
        """
        # Create profile
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO profiles (id, name) VALUES (?, ?)",
                ('stats_profile', 'Stats Test')
            )

        # Insert statistics
        now = datetime.now().isoformat()
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO statistics
                   (parameter_name, analysis_date, profile_id,
                    max_value, min_value, avg_value, mode_value,
                    std_1, std_2, outlier_min, outlier_max, sample_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ('RPM', now, 'stats_profile',
                 7000.0, 800.0, 2500.0, 2000.0,
                 500.0, 1000.0, 1500.0, 3500.0, 100)
            )

        # Verify
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM statistics WHERE parameter_name = 'RPM'")
            row = cursor.fetchone()

            assert row is not None
            assert row['max_value'] == 7000.0
            assert row['min_value'] == 800.0
            assert row['avg_value'] == 2500.0
            assert row['outlier_min'] == 1500.0
            assert row['outlier_max'] == 3500.0

    def test_insertAiRecommendation_withPriorityRank(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Inserting AI recommendation with priority
        Then: Recommendation is stored with rank
        """
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO ai_recommendations (recommendation, priority_rank)
                   VALUES (?, ?)""",
                ('Consider leaning out air/fuel ratio at idle', 3)
            )

        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_recommendations")
            row = cursor.fetchone()

            assert row is not None
            assert row['priority_rank'] == 3

    def test_aiRecommendation_priorityRankConstraint(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Inserting recommendation with invalid priority (>5)
        Then: Constraint violation occurs
        """
        with pytest.raises(DatabaseConnectionError) as excinfo:
            with initializedDb.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO ai_recommendations (recommendation, priority_rank)
                       VALUES (?, ?)""",
                    ('Test', 10)  # Invalid: must be 1-5
                )
        assert "CHECK constraint failed" in str(excinfo.value)


# ================================================================================
# Helper Function Tests
# ================================================================================

class TestHelperFunctions:
    """Tests for helper functions."""

    def test_createDatabaseFromConfig_createsDb(self, validConfig: dict[str, Any]):
        """
        Given: Valid configuration
        When: createDatabaseFromConfig is called
        Then: Returns configured ObdDatabase
        """
        db = createDatabaseFromConfig(validConfig)

        assert db.dbPath == validConfig['database']['path']
        assert db.walMode == validConfig['database']['walMode']

    def test_createDatabaseFromConfig_usesDefaults(self, tmp_path: Path):
        """
        Given: Configuration without walMode
        When: createDatabaseFromConfig is called
        Then: Uses default walMode=True
        """
        config = {
            'database': {
                'path': str(tmp_path / 'default.db')
            }
        }

        db = createDatabaseFromConfig(config)

        assert db.walMode is True

    def test_createDatabaseFromConfig_emptyConfig_usesAllDefaults(self):
        """
        Given: Empty configuration
        When: createDatabaseFromConfig is called
        Then: Uses all defaults
        """
        config = {}

        db = createDatabaseFromConfig(config)

        assert db.dbPath == './data/obd.db'
        assert db.walMode is True

    def test_initializeDatabase_returnsInitializedDb(self, validConfig: dict[str, Any]):
        """
        Given: Valid configuration
        When: initializeDatabase is called
        Then: Returns initialized database
        """
        db = initializeDatabase(validConfig)

        assert db.isInitialized() is True
        assert len(db.getTableNames()) > 0


# ================================================================================
# Database Stats Tests
# ================================================================================

class TestDatabaseStats:
    """Tests for database statistics."""

    def test_getStats_returnsFileSize(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database on disk
        When: getStats is called
        Then: Returns file size
        """
        stats = initializedDb.getStats()

        assert 'file_size_bytes' in stats
        assert stats['file_size_bytes'] > 0

    def test_getStats_returnsTableCounts(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: getStats is called
        Then: Returns table row counts
        """
        stats = initializedDb.getStats()

        assert 'table_counts' in stats
        assert 'profiles' in stats['table_counts']
        assert 'realtime_data' in stats['table_counts']

    def test_getStats_returnsWalMode(self, initializedDb: ObdDatabase):
        """
        Given: Database with WAL mode
        When: getStats is called
        Then: Returns wal_mode status
        """
        stats = initializedDb.getStats()

        assert 'wal_mode' in stats
        assert stats['wal_mode'] is True


# ================================================================================
# Vacuum Tests
# ================================================================================

class TestVacuum:
    """Tests for database vacuum operation."""

    def test_vacuum_executesWithoutError(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: vacuum is called
        Then: No error occurs
        """
        initializedDb.vacuum()  # Should not raise


# ================================================================================
# Edge Cases and Error Handling
# ================================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_getTableNames_uninitializedDb_returnsEmpty(self, tempDbPath: str):
        """
        Given: New uninitialized database
        When: getTableNames is called
        Then: Returns empty list
        """
        db = ObdDatabase(tempDbPath)
        # Don't initialize

        # This creates the file but no tables
        tables = db.getTableNames()
        assert tables == []

    def test_realtimeData_nullProfileId_allowed(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Inserting realtime data with null profile_id
        Then: Insert succeeds
        """
        now = datetime.now().isoformat()
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO realtime_data (timestamp, parameter_name, value, profile_id)
                   VALUES (?, ?, ?, ?)""",
                (now, 'RPM', 2500.0, None)
            )

        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT profile_id FROM realtime_data")
            row = cursor.fetchone()
            assert row['profile_id'] is None

    def test_foreignKeyConstraint_invalidProfileId(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database with foreign key constraints
        When: Inserting statistics with non-existent profile_id
        Then: Foreign key constraint is enforced
        """
        # Note: Foreign key constraints require the referenced row to exist
        # unless the value is NULL
        now = datetime.now().isoformat()

        with pytest.raises(DatabaseConnectionError) as excinfo:
            with initializedDb.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO statistics
                       (parameter_name, analysis_date, profile_id)
                       VALUES (?, ?, ?)""",
                    ('RPM', now, 'nonexistent_profile')
                )
        assert "FOREIGN KEY constraint failed" in str(excinfo.value)

    def test_duplicateProfileId_raisesError(self, initializedDb: ObdDatabase):
        """
        Given: Database with existing profile
        When: Inserting profile with same id
        Then: Constraint violation occurs
        """
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO profiles (id, name) VALUES (?, ?)",
                ('unique_test', 'First')
            )

        with pytest.raises(DatabaseConnectionError) as excinfo:
            with initializedDb.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO profiles (id, name) VALUES (?, ?)",
                    ('unique_test', 'Second')  # Same id
                )
        assert "UNIQUE constraint failed" in str(excinfo.value)

    def test_calibrationSession_endTimeNullable(self, initializedDb: ObdDatabase):
        """
        Given: Initialized database
        When: Creating calibration session without end_time
        Then: Session is created with null end_time
        """
        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO calibration_sessions (notes) VALUES (?)",
                ('Test session',)
            )
            sessionId = cursor.lastrowid

        with initializedDb.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT end_time FROM calibration_sessions WHERE session_id = ?",
                (sessionId,)
            )
            row = cursor.fetchone()
            assert row['end_time'] is None

    def test_allSchemas_haveTableNames(self):
        """
        Given: ALL_SCHEMAS constant
        When: Checking structure
        Then: All entries have table names
        """
        for tableName, schema in ALL_SCHEMAS:
            assert tableName is not None
            assert len(tableName) > 0
            assert 'CREATE TABLE' in schema

    def test_allIndexes_haveIndexNames(self):
        """
        Given: ALL_INDEXES constant
        When: Checking structure
        Then: All entries have index names
        """
        for indexName, indexSql in ALL_INDEXES:
            assert indexName is not None
            assert len(indexName) > 0
            assert 'CREATE INDEX' in indexSql
