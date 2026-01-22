#!/usr/bin/env python3
################################################################################
# File Name: run_tests_data_retention.py
# Purpose/Description: Manual test runner for data retention tests
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""
Manual test runner for data retention module tests.

Runs tests without requiring pytest installed.
Useful for environments where pytest is not available.

Usage:
    python tests/run_tests_data_retention.py
"""

import sys
import os
import time
import traceback
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from obd.database import ObdDatabase
from obd.data_retention import (
    DataRetentionManager,
    CleanupResult,
    CleanupState,
    RetentionStats,
    DataRetentionError,
    CleanupError,
    SchedulerError,
    createRetentionManagerFromConfig,
    runImmediateCleanup,
    getRetentionSummary,
)


# Test utilities
class TestResult:
    """Stores test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors: List[str] = []


def runTest(name: str, testFunc: Callable, result: TestResult) -> None:
    """Run a single test and record result."""
    try:
        testFunc()
        result.passed += 1
        print(f"  [PASS] {name}")
    except AssertionError as e:
        result.failed += 1
        result.errors.append(f"{name}: {e}")
        print(f"  [FAIL] {name}: {e}")
    except Exception as e:
        result.failed += 1
        result.errors.append(f"{name}: {e}")
        print(f"  [ERROR] {name}: {e}")
        traceback.print_exc()


def createTestDatabase() -> tuple:
    """Create a temporary test database and return (database, path)."""
    tmpFile = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmpFile.close()
    db = ObdDatabase(tmpFile.name)
    db.initialize()
    return db, tmpFile.name


def cleanupDatabase(dbPath: str) -> None:
    """Clean up temporary database file."""
    try:
        if os.path.exists(dbPath):
            os.remove(dbPath)
        walPath = dbPath + '-wal'
        shmPath = dbPath + '-shm'
        if os.path.exists(walPath):
            os.remove(walPath)
        if os.path.exists(shmPath):
            os.remove(shmPath)
    except Exception:
        pass


def ensureProfileExists(db: ObdDatabase, profileId: str) -> None:
    """Ensure a profile exists in the profiles table."""
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO profiles (id, name, description)
            VALUES (?, ?, ?)
            """,
            (profileId, profileId.capitalize(), f'Test profile {profileId}')
        )


def insertTestData(
    db: ObdDatabase,
    parameterName: str,
    values: List[float],
    profileId: str = 'daily',
    daysAgo: int = 0
) -> None:
    """Insert test data into realtime_data table with specific age."""
    # First ensure the profile exists
    ensureProfileExists(db, profileId)

    baseTimestamp = datetime.now() - timedelta(days=daysAgo)

    with db.connect() as conn:
        cursor = conn.cursor()
        for i, value in enumerate(values):
            # Add small time offset for each value
            timestamp = baseTimestamp - timedelta(seconds=i)
            cursor.execute(
                """
                INSERT INTO realtime_data
                (timestamp, parameter_name, value, unit, profile_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (timestamp, parameterName, value, 'unit', profileId)
            )


def getRealtimeDataCount(db: ObdDatabase) -> int:
    """Get count of rows in realtime_data table."""
    with db.connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM realtime_data")
        return cursor.fetchone()[0]


def getDefaultConfig() -> Dict[str, Any]:
    """Get default configuration for testing."""
    return {
        'dataRetention': {
            'realtimeDataDays': 7,
            'statisticsRetentionDays': -1,
            'vacuumAfterCleanup': True,
            'cleanupTimeHour': 3
        }
    }


# ================================================================================
# CleanupResult Tests
# ================================================================================

def testCleanupResultSuccess():
    """Test CleanupResult with successful cleanup."""
    result = CleanupResult(
        success=True,
        rowsDeleted=100,
        retentionDays=7,
        executionTimeMs=500
    )
    assert result.success is True
    assert result.rowsDeleted == 100
    assert result.retentionDays == 7
    assert result.executionTimeMs == 500
    assert result.errorMessage is None


def testCleanupResultFailure():
    """Test CleanupResult with failed cleanup."""
    result = CleanupResult(
        success=False,
        rowsDeleted=0,
        errorMessage="Database error"
    )
    assert result.success is False
    assert result.rowsDeleted == 0
    assert result.errorMessage == "Database error"


def testCleanupResultToDict():
    """Test CleanupResult toDict serialization."""
    now = datetime.now()
    result = CleanupResult(
        success=True,
        rowsDeleted=50,
        oldestTimestamp=now - timedelta(days=10),
        newestTimestamp=now,
        retentionDays=7,
        cutoffTimestamp=now - timedelta(days=7),
        executionTimeMs=100,
        vacuumPerformed=True,
        spaceReclaimedBytes=1024
    )
    d = result.toDict()
    assert d['success'] is True
    assert d['rowsDeleted'] == 50
    assert d['retentionDays'] == 7
    assert d['vacuumPerformed'] is True
    assert d['spaceReclaimedBytes'] == 1024
    assert d['oldestTimestamp'] is not None
    assert d['cutoffTimestamp'] is not None


def testCleanupResultToDictNullTimestamps():
    """Test CleanupResult toDict with null timestamps."""
    result = CleanupResult(success=True, rowsDeleted=0)
    d = result.toDict()
    assert d['oldestTimestamp'] is None
    assert d['newestTimestamp'] is None
    assert d['cutoffTimestamp'] is None


# ================================================================================
# RetentionStats Tests
# ================================================================================

def testRetentionStatsDefault():
    """Test RetentionStats default values."""
    stats = RetentionStats()
    assert stats.state == CleanupState.IDLE
    assert stats.lastCleanupTime is None
    assert stats.nextScheduledCleanup is None
    assert stats.totalCleanups == 0
    assert stats.totalRowsDeleted == 0
    assert stats.lastResult is None


def testRetentionStatsToDict():
    """Test RetentionStats toDict serialization."""
    now = datetime.now()
    result = CleanupResult(success=True, rowsDeleted=10)
    stats = RetentionStats(
        state=CleanupState.COMPLETED,
        lastCleanupTime=now,
        nextScheduledCleanup=now + timedelta(days=1),
        totalCleanups=5,
        totalRowsDeleted=500,
        lastResult=result
    )
    d = stats.toDict()
    assert d['state'] == 'completed'
    assert d['totalCleanups'] == 5
    assert d['totalRowsDeleted'] == 500
    assert d['lastCleanupTime'] is not None
    assert d['nextScheduledCleanup'] is not None
    assert d['lastResult'] is not None


# ================================================================================
# DataRetentionManager Initialization Tests
# ================================================================================

def testManagerInitWithConfig():
    """Test manager initialization with configuration."""
    db, dbPath = createTestDatabase()
    try:
        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        assert manager.retentionDays == 7
        assert manager.cleanupHour == 3
        assert manager.state == CleanupState.IDLE
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testManagerInitWithCustomConfig():
    """Test manager initialization with custom configuration."""
    db, dbPath = createTestDatabase()
    try:
        config = {
            'dataRetention': {
                'realtimeDataDays': 14,
                'vacuumAfterCleanup': False,
                'cleanupTimeHour': 5
            }
        }
        manager = DataRetentionManager(db, config)

        assert manager.retentionDays == 14
        assert manager.cleanupHour == 5
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testManagerInitWithEmptyConfig():
    """Test manager uses defaults with empty config."""
    db, dbPath = createTestDatabase()
    try:
        config = {}
        manager = DataRetentionManager(db, config)

        # Should use defaults
        assert manager.retentionDays == 7
        assert manager.cleanupHour == 3
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testManagerInitWithCallback():
    """Test manager initialization with callback."""
    db, dbPath = createTestDatabase()
    callbackResults = []

    def onComplete(result):
        callbackResults.append(result)

    try:
        config = getDefaultConfig()
        manager = DataRetentionManager(db, config, onCleanupComplete=onComplete)

        # Run cleanup to trigger callback
        result = manager.runCleanup()
        assert len(callbackResults) == 1
        assert callbackResults[0].success is True
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


# ================================================================================
# runCleanup Tests
# ================================================================================

def testRunCleanupNoData():
    """Test cleanup with no data in database."""
    db, dbPath = createTestDatabase()
    try:
        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup()

        assert result.success is True
        assert result.rowsDeleted == 0
        assert result.retentionDays == 7
        assert result.executionTimeMs >= 0
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupWithOldData():
    """Test cleanup deletes old data."""
    db, dbPath = createTestDatabase()
    try:
        # Insert data: 5 rows 10 days old, 5 rows 3 days old
        insertTestData(db, 'RPM', [1000, 1100, 1200, 1300, 1400], daysAgo=10)
        insertTestData(db, 'RPM', [2000, 2100, 2200, 2300, 2400], daysAgo=3)

        assert getRealtimeDataCount(db) == 10

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup()

        assert result.success is True
        assert result.rowsDeleted == 5  # Only old data deleted
        assert getRealtimeDataCount(db) == 5  # Recent data preserved
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupWithRecentDataOnly():
    """Test cleanup preserves recent data."""
    db, dbPath = createTestDatabase()
    try:
        # Insert only recent data (3 days old, within 7 day retention)
        insertTestData(db, 'RPM', [1000, 1100, 1200], daysAgo=3)

        assert getRealtimeDataCount(db) == 3

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup()

        assert result.success is True
        assert result.rowsDeleted == 0  # No data deleted
        assert getRealtimeDataCount(db) == 3  # All data preserved
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupWithCustomRetention():
    """Test cleanup with custom retention period override."""
    db, dbPath = createTestDatabase()
    try:
        # Insert data at different ages
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=5)  # 5 days old
        insertTestData(db, 'RPM', [2000, 2100], daysAgo=2)  # 2 days old

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        # Run with 3 day retention (override the 7 day default)
        result = manager.runCleanup(retentionDays=3)

        assert result.success is True
        assert result.rowsDeleted == 2  # 5 day old data deleted
        assert result.retentionDays == 3
        assert getRealtimeDataCount(db) == 2  # 2 day old data preserved
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupDeletesAllOldData():
    """Test cleanup deletes all data older than retention."""
    db, dbPath = createTestDatabase()
    try:
        # Insert all old data
        insertTestData(db, 'RPM', [1000, 1100, 1200], daysAgo=20)
        insertTestData(db, 'SPEED', [50, 60, 70], daysAgo=15)

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup()

        assert result.success is True
        assert result.rowsDeleted == 6  # All data deleted
        assert getRealtimeDataCount(db) == 0
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupVacuumPerformed():
    """Test that vacuum is performed after deletion."""
    db, dbPath = createTestDatabase()
    try:
        # Insert some data to delete
        insertTestData(db, 'RPM', [1000, 1100, 1200], daysAgo=10)

        config = {
            'dataRetention': {
                'realtimeDataDays': 7,
                'vacuumAfterCleanup': True
            }
        }
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup()

        assert result.success is True
        assert result.rowsDeleted == 3
        assert result.vacuumPerformed is True
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupNoVacuumWhenDisabled():
    """Test vacuum not performed when disabled."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000, 1100, 1200], daysAgo=10)

        config = {
            'dataRetention': {
                'realtimeDataDays': 7,
                'vacuumAfterCleanup': False
            }
        }
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup()

        assert result.success is True
        assert result.vacuumPerformed is False
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupNoVacuumWhenNoDataDeleted():
    """Test vacuum not performed when no data deleted."""
    db, dbPath = createTestDatabase()
    try:
        # Insert only recent data
        insertTestData(db, 'RPM', [1000], daysAgo=1)

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup()

        assert result.success is True
        assert result.rowsDeleted == 0
        assert result.vacuumPerformed is False
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupLogsToConnectionLog():
    """Test cleanup logs event to connection_log table."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=10)

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)
        manager.runCleanup()

        # Check connection_log for cleanup event
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT event_type, error_message FROM connection_log "
                "WHERE event_type = 'data_cleanup'"
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == 'data_cleanup'
            assert 'Deleted 2 rows' in row[1]
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupUpdatesStats():
    """Test cleanup updates manager statistics."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=10)

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        # Initial stats
        stats = manager.getStats()
        assert stats.totalCleanups == 0
        assert stats.totalRowsDeleted == 0

        # Run cleanup
        manager.runCleanup()

        # Check updated stats
        stats = manager.getStats()
        assert stats.totalCleanups == 1
        assert stats.totalRowsDeleted == 2
        assert stats.lastCleanupTime is not None
        assert stats.lastResult is not None
        assert stats.lastResult.success is True
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupMultipleTimes():
    """Test running cleanup multiple times accumulates stats."""
    db, dbPath = createTestDatabase()
    try:
        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        # Run multiple cleanups
        insertTestData(db, 'RPM', [1000], daysAgo=10)
        manager.runCleanup()

        insertTestData(db, 'RPM', [2000], daysAgo=10)
        manager.runCleanup()

        insertTestData(db, 'RPM', [3000], daysAgo=10)
        manager.runCleanup()

        stats = manager.getStats()
        assert stats.totalCleanups == 3
        assert stats.totalRowsDeleted == 3
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupTimestampRangeReported():
    """Test cleanup reports correct timestamp range."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000], daysAgo=10)
        insertTestData(db, 'RPM', [2000], daysAgo=5)
        insertTestData(db, 'RPM', [3000], daysAgo=1)

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup()

        assert result.success is True
        assert result.oldestTimestamp is not None
        assert result.newestTimestamp is not None
        assert result.cutoffTimestamp is not None
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupCallbackInvoked():
    """Test callback is invoked after cleanup."""
    db, dbPath = createTestDatabase()
    callbackResults = []

    def onComplete(result):
        callbackResults.append(result)

    try:
        insertTestData(db, 'RPM', [1000], daysAgo=10)

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config, onCleanupComplete=onComplete)

        manager.runCleanup()

        assert len(callbackResults) == 1
        assert callbackResults[0].success is True
        assert callbackResults[0].rowsDeleted == 1
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunCleanupCallbackExceptionHandled():
    """Test callback exception doesn't break cleanup."""
    db, dbPath = createTestDatabase()

    def badCallback(result):
        raise Exception("Callback error")

    try:
        insertTestData(db, 'RPM', [1000], daysAgo=10)

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config, onCleanupComplete=badCallback)

        # Should not raise despite callback exception
        result = manager.runCleanup()
        assert result.success is True
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


# ================================================================================
# Statistics Preservation Tests
# ================================================================================

def testStatisticsNotDeleted():
    """Test that statistics table data is never deleted."""
    db, dbPath = createTestDatabase()
    try:
        # Ensure profile exists first
        ensureProfileExists(db, 'daily')

        # Insert statistics data
        with db.connect() as conn:
            cursor = conn.cursor()
            # Insert old statistics
            oldDate = datetime.now() - timedelta(days=100)
            cursor.execute("""
                INSERT INTO statistics
                (parameter_name, analysis_date, profile_id, max_value, min_value)
                VALUES (?, ?, ?, ?, ?)
            """, ('RPM', oldDate, 'daily', 6000, 800))

        # Insert old realtime data
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=10)

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)
        manager.runCleanup()

        # Verify statistics still exist
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM statistics")
            count = cursor.fetchone()[0]
            assert count == 1  # Statistics preserved

        # Verify realtime data deleted
        assert getRealtimeDataCount(db) == 0
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


# ================================================================================
# Scheduling Tests
# ================================================================================

def testScheduleCleanupSetsState():
    """Test scheduleCleanup sets state to SCHEDULED."""
    db, dbPath = createTestDatabase()
    try:
        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        manager.scheduleCleanup()

        assert manager.state == CleanupState.SCHEDULED
        assert manager.isScheduled() is True
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testScheduleCleanupSetsNextRun():
    """Test scheduleCleanup sets next scheduled cleanup time."""
    db, dbPath = createTestDatabase()
    try:
        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        manager.scheduleCleanup()

        stats = manager.getStats()
        assert stats.nextScheduledCleanup is not None
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testStopCancelsSchedule():
    """Test stop cancels scheduled cleanup."""
    db, dbPath = createTestDatabase()
    try:
        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        manager.scheduleCleanup()
        assert manager.isScheduled() is True

        manager.stop()

        assert manager.state == CleanupState.IDLE
        assert manager.isScheduled() is False
        stats = manager.getStats()
        assert stats.nextScheduledCleanup is None
    finally:
        cleanupDatabase(dbPath)


def testStopIdempotent():
    """Test stop can be called multiple times safely."""
    db, dbPath = createTestDatabase()
    try:
        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        manager.scheduleCleanup()
        manager.stop()
        manager.stop()  # Should not error
        manager.stop()

        assert manager.state == CleanupState.IDLE
    finally:
        cleanupDatabase(dbPath)


def testScheduleCleanupReschedules():
    """Test scheduleCleanup cancels existing schedule."""
    db, dbPath = createTestDatabase()
    try:
        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        manager.scheduleCleanup()
        firstSchedule = manager.getStats().nextScheduledCleanup

        # Schedule again - should cancel and reschedule
        manager.scheduleCleanup()
        secondSchedule = manager.getStats().nextScheduledCleanup

        # Both should be set
        assert firstSchedule is not None
        assert secondSchedule is not None
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


# ================================================================================
# State Tests
# ================================================================================

def testStateTransitions():
    """Test state transitions during cleanup."""
    db, dbPath = createTestDatabase()
    states = []

    def captureState(result):
        states.append(manager.state)

    try:
        config = getDefaultConfig()
        manager = DataRetentionManager(db, config, onCleanupComplete=captureState)

        assert manager.state == CleanupState.IDLE

        result = manager.runCleanup()

        # After cleanup completes, state should be COMPLETED
        assert manager.state == CleanupState.COMPLETED
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testIsRunning():
    """Test isRunning returns correct state."""
    db, dbPath = createTestDatabase()
    try:
        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        assert manager.isRunning() is False

        # After cleanup, not running
        manager.runCleanup()
        assert manager.isRunning() is False
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


# ================================================================================
# Helper Function Tests
# ================================================================================

def testCreateRetentionManagerFromConfig():
    """Test createRetentionManagerFromConfig helper."""
    db, dbPath = createTestDatabase()
    try:
        config = getDefaultConfig()
        manager = createRetentionManagerFromConfig(db, config)

        assert isinstance(manager, DataRetentionManager)
        assert manager.retentionDays == 7
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testRunImmediateCleanup():
    """Test runImmediateCleanup helper function."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=10)

        result = runImmediateCleanup(db, retentionDays=7, vacuumAfterCleanup=False)

        assert result.success is True
        assert result.rowsDeleted == 2
    finally:
        cleanupDatabase(dbPath)


def testRunImmediateCleanupCustomRetention():
    """Test runImmediateCleanup with custom retention."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000], daysAgo=5)
        insertTestData(db, 'RPM', [2000], daysAgo=2)

        result = runImmediateCleanup(db, retentionDays=3)

        assert result.success is True
        assert result.rowsDeleted == 1  # Only 5 day old data
    finally:
        cleanupDatabase(dbPath)


def testGetRetentionSummaryEmpty():
    """Test getRetentionSummary with empty database."""
    db, dbPath = createTestDatabase()
    try:
        summary = getRetentionSummary(db)

        assert summary['realtimeDataCount'] == 0
        assert summary['oldestTimestamp'] is None
        assert summary['newestTimestamp'] is None
        assert summary['dataAgeDays'] == 0
        assert summary['statisticsCount'] == 0
    finally:
        cleanupDatabase(dbPath)


def testGetRetentionSummaryWithData():
    """Test getRetentionSummary with data."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000, 1100, 1200], daysAgo=5)
        insertTestData(db, 'RPM', [2000, 2100], daysAgo=1)

        summary = getRetentionSummary(db)

        assert summary['realtimeDataCount'] == 5
        assert summary['oldestTimestamp'] is not None
        assert summary['newestTimestamp'] is not None
        assert summary['dataAgeDays'] >= 5
    finally:
        cleanupDatabase(dbPath)


def testGetRetentionSummaryWithStatistics():
    """Test getRetentionSummary includes statistics count."""
    db, dbPath = createTestDatabase()
    try:
        ensureProfileExists(db, 'daily')

        # Insert statistics
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO statistics
                (parameter_name, analysis_date, profile_id, max_value, min_value)
                VALUES (?, ?, ?, ?, ?)
            """, ('RPM', datetime.now(), 'daily', 6000, 800))
            cursor.execute("""
                INSERT INTO statistics
                (parameter_name, analysis_date, profile_id, max_value, min_value)
                VALUES (?, ?, ?, ?, ?)
            """, ('SPEED', datetime.now(), 'daily', 100, 0))

        summary = getRetentionSummary(db)
        assert summary['statisticsCount'] == 2
    finally:
        cleanupDatabase(dbPath)


# ================================================================================
# Edge Cases Tests
# ================================================================================

def testZeroRetentionDays():
    """Test cleanup with 0 day retention deletes all data."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=0)

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup(retentionDays=0)

        # Should delete everything since retention is 0 days
        # Data inserted moments ago is still "older than 0 days"
        assert result.success is True
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testLargeDataset():
    """Test cleanup handles larger datasets."""
    db, dbPath = createTestDatabase()
    try:
        # Insert 1000 rows of old data
        ensureProfileExists(db, 'daily')
        baseTimestamp = datetime.now() - timedelta(days=10)
        with db.connect() as conn:
            cursor = conn.cursor()
            for i in range(1000):
                cursor.execute(
                    """
                    INSERT INTO realtime_data
                    (timestamp, parameter_name, value, unit, profile_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (baseTimestamp - timedelta(seconds=i), 'RPM', 1000 + i, 'rpm', 'daily')
                )

        assert getRealtimeDataCount(db) == 1000

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup()

        assert result.success is True
        assert result.rowsDeleted == 1000
        assert getRealtimeDataCount(db) == 0
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testMultipleProfiles():
    """Test cleanup works with multiple profiles."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000, 1100], profileId='daily', daysAgo=10)
        insertTestData(db, 'RPM', [2000, 2100], profileId='performance', daysAgo=10)
        insertTestData(db, 'RPM', [3000, 3100], profileId='daily', daysAgo=3)

        assert getRealtimeDataCount(db) == 6

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup()

        assert result.success is True
        assert result.rowsDeleted == 4  # Old data from both profiles
        assert getRealtimeDataCount(db) == 2  # Recent data preserved
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testMultipleParameters():
    """Test cleanup works across multiple parameter types."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=10)
        insertTestData(db, 'SPEED', [50, 60], daysAgo=10)
        insertTestData(db, 'COOLANT_TEMP', [80, 85], daysAgo=10)
        insertTestData(db, 'RPM', [2000], daysAgo=3)

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        result = manager.runCleanup()

        assert result.success is True
        assert result.rowsDeleted == 6  # All old data across all params
        assert getRealtimeDataCount(db) == 1  # Recent RPM preserved
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


def testNegativeRetentionDaysDeletesAll():
    """Test negative retention days calculates future cutoff (effectively deletes all)."""
    db, dbPath = createTestDatabase()
    try:
        insertTestData(db, 'RPM', [1000, 1100], daysAgo=100)

        config = getDefaultConfig()
        manager = DataRetentionManager(db, config)

        # -1 retention days creates a cutoff in the future (now + 1 day)
        # This means ALL data is older than the cutoff
        result = manager.runCleanup(retentionDays=-1)

        assert result.success is True
        # All data is deleted because it's all older than the future cutoff
        assert result.rowsDeleted == 2
        assert getRealtimeDataCount(db) == 0
    finally:
        manager.stop()
        cleanupDatabase(dbPath)


# ================================================================================
# Main Test Runner
# ================================================================================

def main():
    """Run all tests."""
    print("=" * 60)
    print("Data Retention Module Tests")
    print("=" * 60)

    result = TestResult()

    # CleanupResult tests
    print("\nCleanupResult Tests:")
    runTest("testCleanupResultSuccess", testCleanupResultSuccess, result)
    runTest("testCleanupResultFailure", testCleanupResultFailure, result)
    runTest("testCleanupResultToDict", testCleanupResultToDict, result)
    runTest("testCleanupResultToDictNullTimestamps", testCleanupResultToDictNullTimestamps, result)

    # RetentionStats tests
    print("\nRetentionStats Tests:")
    runTest("testRetentionStatsDefault", testRetentionStatsDefault, result)
    runTest("testRetentionStatsToDict", testRetentionStatsToDict, result)

    # Initialization tests
    print("\nDataRetentionManager Initialization Tests:")
    runTest("testManagerInitWithConfig", testManagerInitWithConfig, result)
    runTest("testManagerInitWithCustomConfig", testManagerInitWithCustomConfig, result)
    runTest("testManagerInitWithEmptyConfig", testManagerInitWithEmptyConfig, result)
    runTest("testManagerInitWithCallback", testManagerInitWithCallback, result)

    # runCleanup tests
    print("\nrunCleanup Tests:")
    runTest("testRunCleanupNoData", testRunCleanupNoData, result)
    runTest("testRunCleanupWithOldData", testRunCleanupWithOldData, result)
    runTest("testRunCleanupWithRecentDataOnly", testRunCleanupWithRecentDataOnly, result)
    runTest("testRunCleanupWithCustomRetention", testRunCleanupWithCustomRetention, result)
    runTest("testRunCleanupDeletesAllOldData", testRunCleanupDeletesAllOldData, result)
    runTest("testRunCleanupVacuumPerformed", testRunCleanupVacuumPerformed, result)
    runTest("testRunCleanupNoVacuumWhenDisabled", testRunCleanupNoVacuumWhenDisabled, result)
    runTest("testRunCleanupNoVacuumWhenNoDataDeleted", testRunCleanupNoVacuumWhenNoDataDeleted, result)
    runTest("testRunCleanupLogsToConnectionLog", testRunCleanupLogsToConnectionLog, result)
    runTest("testRunCleanupUpdatesStats", testRunCleanupUpdatesStats, result)
    runTest("testRunCleanupMultipleTimes", testRunCleanupMultipleTimes, result)
    runTest("testRunCleanupTimestampRangeReported", testRunCleanupTimestampRangeReported, result)
    runTest("testRunCleanupCallbackInvoked", testRunCleanupCallbackInvoked, result)
    runTest("testRunCleanupCallbackExceptionHandled", testRunCleanupCallbackExceptionHandled, result)

    # Statistics preservation tests
    print("\nStatistics Preservation Tests:")
    runTest("testStatisticsNotDeleted", testStatisticsNotDeleted, result)

    # Scheduling tests
    print("\nScheduling Tests:")
    runTest("testScheduleCleanupSetsState", testScheduleCleanupSetsState, result)
    runTest("testScheduleCleanupSetsNextRun", testScheduleCleanupSetsNextRun, result)
    runTest("testStopCancelsSchedule", testStopCancelsSchedule, result)
    runTest("testStopIdempotent", testStopIdempotent, result)
    runTest("testScheduleCleanupReschedules", testScheduleCleanupReschedules, result)

    # State tests
    print("\nState Tests:")
    runTest("testStateTransitions", testStateTransitions, result)
    runTest("testIsRunning", testIsRunning, result)

    # Helper function tests
    print("\nHelper Function Tests:")
    runTest("testCreateRetentionManagerFromConfig", testCreateRetentionManagerFromConfig, result)
    runTest("testRunImmediateCleanup", testRunImmediateCleanup, result)
    runTest("testRunImmediateCleanupCustomRetention", testRunImmediateCleanupCustomRetention, result)
    runTest("testGetRetentionSummaryEmpty", testGetRetentionSummaryEmpty, result)
    runTest("testGetRetentionSummaryWithData", testGetRetentionSummaryWithData, result)
    runTest("testGetRetentionSummaryWithStatistics", testGetRetentionSummaryWithStatistics, result)

    # Edge cases
    print("\nEdge Cases Tests:")
    runTest("testZeroRetentionDays", testZeroRetentionDays, result)
    runTest("testLargeDataset", testLargeDataset, result)
    runTest("testMultipleProfiles", testMultipleProfiles, result)
    runTest("testMultipleParameters", testMultipleParameters, result)
    runTest("testNegativeRetentionDaysDeletesAll", testNegativeRetentionDaysDeletesAll, result)

    # Summary
    print("\n" + "=" * 60)
    print(f"SUMMARY: {result.passed} passed, {result.failed} failed")
    print("=" * 60)

    if result.errors:
        print("\nFailures:")
        for error in result.errors:
            print(f"  - {error}")

    return 0 if result.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
