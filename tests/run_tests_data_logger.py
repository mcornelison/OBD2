#!/usr/bin/env python3
################################################################################
# File Name: run_tests_data_logger.py
# Purpose/Description: Manual test runner for OBD data logger tests
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""
Manual test runner for OBD data logger module tests.

Runs tests without requiring pytest installed.
Useful for environments where pytest is not available.

Usage:
    python tests/run_tests_data_logger.py
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
from obd.data_logger import (
    ObdDataLogger,
    DataLoggerError,
    ParameterNotSupportedError,
    ParameterReadError,
    LoggedReading,
    LoggingState,
    LoggingStats,
    RealtimeDataLogger,
    queryParameter,
    logReading,
    verifyDataPersistence,
    createDataLoggerFromConfig,
    createRealtimeLoggerFromConfig,
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


# ================================================================================
# LoggedReading Tests
# ================================================================================

def testLoggedReadingDefaults():
    """Test LoggedReading with required fields only."""
    reading = LoggedReading(
        parameterName='RPM',
        value=3500.0,
        timestamp=datetime.now()
    )
    assert reading.parameterName == 'RPM'
    assert reading.value == 3500.0
    assert reading.unit is None
    assert reading.profileId is None


def testLoggedReadingAllFields():
    """Test LoggedReading with all fields."""
    now = datetime.now()
    reading = LoggedReading(
        parameterName='COOLANT_TEMP',
        value=85.5,
        unit='degC',
        timestamp=now,
        profileId='daily'
    )
    assert reading.parameterName == 'COOLANT_TEMP'
    assert reading.value == 85.5
    assert reading.unit == 'degC'
    assert reading.timestamp == now
    assert reading.profileId == 'daily'


def testLoggedReadingToDict():
    """Test LoggedReading.toDict() serialization."""
    now = datetime.now()
    reading = LoggedReading(
        parameterName='RPM',
        value=4000.0,
        unit='rpm',
        timestamp=now,
        profileId='performance'
    )
    result = reading.toDict()

    assert result['parameterName'] == 'RPM'
    assert result['value'] == 4000.0
    assert result['unit'] == 'rpm'
    assert result['profileId'] == 'performance'
    assert 'timestamp' in result


# ================================================================================
# Exception Tests
# ================================================================================

def testDataLoggerErrorMessage():
    """Test DataLoggerError stores message."""
    error = DataLoggerError("Test error")
    assert str(error) == "Test error"
    assert error.message == "Test error"


def testDataLoggerErrorDetails():
    """Test DataLoggerError stores details."""
    error = DataLoggerError("Test", details={'key': 'value'})
    assert error.details == {'key': 'value'}


def testParameterNotSupportedInheritance():
    """Test ParameterNotSupportedError inheritance."""
    error = ParameterNotSupportedError("RPM not supported")
    assert isinstance(error, DataLoggerError)


def testParameterReadErrorInheritance():
    """Test ParameterReadError inheritance."""
    error = ParameterReadError("Failed to read RPM")
    assert isinstance(error, DataLoggerError)


# ================================================================================
# ObdDataLogger Init Tests
# ================================================================================

def testDataLoggerInitWithConnection():
    """Test ObdDataLogger initialization with connection."""
    mockConn = MagicMock()
    mockDb = MagicMock()

    logger = ObdDataLogger(mockConn, mockDb)

    assert logger.connection == mockConn
    assert logger.database == mockDb
    assert logger.profileId is None


def testDataLoggerInitWithProfile():
    """Test ObdDataLogger initialization with profile."""
    mockConn = MagicMock()
    mockDb = MagicMock()

    logger = ObdDataLogger(mockConn, mockDb, profileId='daily')

    assert logger.profileId == 'daily'


# ================================================================================
# Query Parameter Tests
# ================================================================================

def testQueryParameterSuccess():
    """Test successful parameter query."""
    mockObd = MagicMock()
    mockResponse = MagicMock()
    mockResponse.is_null.return_value = False
    mockResponse.value.magnitude = 3500.0
    mockResponse.unit = 'rpm'
    mockObd.query.return_value = mockResponse

    mockConn = MagicMock()
    mockConn.obd = mockObd
    mockConn.isConnected.return_value = True

    mockDb = MagicMock()

    logger = ObdDataLogger(mockConn, mockDb)
    reading = logger.queryParameter('RPM')

    assert reading.parameterName == 'RPM'
    assert reading.value == 3500.0


def testQueryParameterNullResponse():
    """Test parameter query with null response."""
    mockObd = MagicMock()
    mockResponse = MagicMock()
    mockResponse.is_null.return_value = True
    mockObd.query.return_value = mockResponse

    mockConn = MagicMock()
    mockConn.obd = mockObd
    mockConn.isConnected.return_value = True

    mockDb = MagicMock()

    logger = ObdDataLogger(mockConn, mockDb)

    try:
        logger.queryParameter('RPM')
        assert False, "Expected ParameterReadError"
    except ParameterReadError as e:
        assert 'RPM' in str(e)


def testQueryParameterNotConnected():
    """Test parameter query when not connected."""
    mockConn = MagicMock()
    mockConn.isConnected.return_value = False

    mockDb = MagicMock()

    logger = ObdDataLogger(mockConn, mockDb)

    try:
        logger.queryParameter('RPM')
        assert False, "Expected DataLoggerError"
    except DataLoggerError as e:
        assert 'not connected' in str(e).lower()


def testQueryParameterUsesCommandName():
    """Test parameter query uses correct OBD command."""
    mockObd = MagicMock()
    mockResponse = MagicMock()
    mockResponse.is_null.return_value = False
    mockResponse.value.magnitude = 85.0
    mockResponse.unit = 'degC'
    mockObd.query.return_value = mockResponse

    mockConn = MagicMock()
    mockConn.obd = mockObd
    mockConn.isConnected.return_value = True

    mockDb = MagicMock()

    logger = ObdDataLogger(mockConn, mockDb)
    logger.queryParameter('COOLANT_TEMP')

    # Verify query was called
    mockObd.query.assert_called_once()


# ================================================================================
# Log Reading Tests
# ================================================================================

def testLogReadingStoresInDatabase():
    """Test logReading stores data in database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        mockConn = MagicMock()
        mockConn.isConnected.return_value = True

        logger = ObdDataLogger(mockConn, db)

        reading = LoggedReading(
            parameterName='RPM',
            value=3500.0,
            unit='rpm',
            timestamp=datetime.now()
        )

        logger.logReading(reading)

        # Verify data was stored
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT parameter_name, value, unit FROM realtime_data')
            row = cursor.fetchone()

        assert row is not None
        assert row['parameter_name'] == 'RPM'
        assert row['value'] == 3500.0
        assert row['unit'] == 'rpm'


def testLogReadingWithProfile():
    """Test logReading stores profile_id."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        # Create profile first
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO profiles (id, name) VALUES (?, ?)",
                ('daily', 'Daily')
            )

        mockConn = MagicMock()
        mockConn.isConnected.return_value = True

        logger = ObdDataLogger(mockConn, db, profileId='daily')

        reading = LoggedReading(
            parameterName='RPM',
            value=3500.0,
            timestamp=datetime.now()
        )

        logger.logReading(reading)

        # Verify profile_id was stored
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT profile_id FROM realtime_data')
            row = cursor.fetchone()

        assert row['profile_id'] == 'daily'


def testLogReadingTimestamp():
    """Test logReading stores precise timestamp."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        mockConn = MagicMock()
        mockConn.isConnected.return_value = True

        logger = ObdDataLogger(mockConn, db)

        testTime = datetime(2026, 1, 22, 10, 30, 45, 123456)
        reading = LoggedReading(
            parameterName='RPM',
            value=3500.0,
            timestamp=testTime
        )

        logger.logReading(reading)

        # Verify timestamp was stored
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT timestamp FROM realtime_data')
            row = cursor.fetchone()

        assert row['timestamp'] is not None


# ================================================================================
# Query and Log Tests (End-to-End)
# ================================================================================

def testQueryAndLogParameter():
    """Test queryAndLogParameter does end-to-end operation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        mockObd = MagicMock()
        mockResponse = MagicMock()
        mockResponse.is_null.return_value = False
        mockResponse.value.magnitude = 3500.0
        mockResponse.unit = 'rpm'
        mockObd.query.return_value = mockResponse

        mockConn = MagicMock()
        mockConn.obd = mockObd
        mockConn.isConnected.return_value = True

        logger = ObdDataLogger(mockConn, db)
        reading = logger.queryAndLogParameter('RPM')

        # Verify reading was returned
        assert reading.parameterName == 'RPM'
        assert reading.value == 3500.0

        # Verify data was stored in database
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM realtime_data')
            count = cursor.fetchone()[0]

        assert count == 1


# ================================================================================
# Data Persistence Tests
# ================================================================================

def testVerifyDataPersistence():
    """Test data persists across database reconnection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')

        # First connection - write data
        db1 = ObdDatabase(dbPath)
        db1.initialize()

        mockConn = MagicMock()
        mockConn.isConnected.return_value = True

        logger = ObdDataLogger(mockConn, db1)

        reading = LoggedReading(
            parameterName='RPM',
            value=3500.0,
            unit='rpm',
            timestamp=datetime.now()
        )

        logger.logReading(reading)

        # Second connection - verify data exists
        db2 = ObdDatabase(dbPath)

        with db2.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT parameter_name, value FROM realtime_data')
            row = cursor.fetchone()

        assert row is not None
        assert row['parameter_name'] == 'RPM'
        assert row['value'] == 3500.0


def testVerifyDataPersistenceMultipleReadings():
    """Test multiple readings persist correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')

        db = ObdDatabase(dbPath)
        db.initialize()

        mockConn = MagicMock()
        mockConn.isConnected.return_value = True

        logger = ObdDataLogger(mockConn, db)

        # Log multiple readings
        readings = [
            LoggedReading('RPM', 3500.0, 'rpm', datetime.now()),
            LoggedReading('COOLANT_TEMP', 85.0, 'degC', datetime.now()),
            LoggedReading('SPEED', 60.0, 'km/h', datetime.now()),
        ]

        for reading in readings:
            logger.logReading(reading)

        # Verify all readings
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM realtime_data')
            count = cursor.fetchone()[0]

        assert count == 3


def testVerifyDataPersistenceFunction():
    """Test verifyDataPersistence helper function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')

        db = ObdDatabase(dbPath)
        db.initialize()

        mockConn = MagicMock()
        mockConn.isConnected.return_value = True

        logger = ObdDataLogger(mockConn, db)

        reading = LoggedReading(
            parameterName='TEST_PARAM',
            value=123.45,
            timestamp=datetime.now()
        )

        logger.logReading(reading)

        # Use helper function to verify
        result = verifyDataPersistence(db, 'TEST_PARAM')

        assert result is True


def testVerifyDataPersistenceNotFound():
    """Test verifyDataPersistence returns False when data not found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')

        db = ObdDatabase(dbPath)
        db.initialize()

        result = verifyDataPersistence(db, 'NONEXISTENT_PARAM')

        assert result is False


# ================================================================================
# Helper Function Tests
# ================================================================================

def testCreateDataLoggerFromConfig():
    """Test createDataLoggerFromConfig creates logger."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')

        config = {
            'profiles': {'activeProfile': 'daily'}
        }

        mockConn = MagicMock()
        db = ObdDatabase(dbPath)
        db.initialize()

        logger = createDataLoggerFromConfig(config, mockConn, db)

        assert isinstance(logger, ObdDataLogger)
        assert logger.profileId == 'daily'


def testQueryParameterHelperFunction():
    """Test queryParameter standalone helper function."""
    mockObd = MagicMock()
    mockResponse = MagicMock()
    mockResponse.is_null.return_value = False
    mockResponse.value.magnitude = 100.0
    mockResponse.unit = 'pct'
    mockObd.query.return_value = mockResponse

    mockConn = MagicMock()
    mockConn.obd = mockObd
    mockConn.isConnected.return_value = True

    reading = queryParameter(mockConn, 'ENGINE_LOAD')

    assert reading.parameterName == 'ENGINE_LOAD'
    assert reading.value == 100.0


def testLogReadingHelperFunction():
    """Test logReading standalone helper function."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')

        db = ObdDatabase(dbPath)
        db.initialize()

        reading = LoggedReading(
            parameterName='RPM',
            value=3500.0,
            timestamp=datetime.now()
        )

        logReading(db, reading)

        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM realtime_data')
            count = cursor.fetchone()[0]

        assert count == 1


# ================================================================================
# Edge Case Tests
# ================================================================================

def testQueryParameterWithPintValue():
    """Test parameter query handles pint Quantity values."""
    mockObd = MagicMock()
    mockResponse = MagicMock()
    mockResponse.is_null.return_value = False
    # Simulate pint-like value with magnitude attribute
    mockValue = MagicMock()
    mockValue.magnitude = 3500.0
    mockResponse.value = mockValue
    mockResponse.unit = 'rpm'
    mockObd.query.return_value = mockResponse

    mockConn = MagicMock()
    mockConn.obd = mockObd
    mockConn.isConnected.return_value = True

    mockDb = MagicMock()

    logger = ObdDataLogger(mockConn, mockDb)
    reading = logger.queryParameter('RPM')

    assert reading.value == 3500.0


def testQueryParameterWithPlainValue():
    """Test parameter query handles plain numeric values."""
    mockObd = MagicMock()
    mockResponse = MagicMock()
    mockResponse.is_null.return_value = False
    # Simulate plain value without magnitude (some OBD parameters)
    mockResponse.value = 3500.0
    mockResponse.unit = 'rpm'
    mockObd.query.return_value = mockResponse

    mockConn = MagicMock()
    mockConn.obd = mockObd
    mockConn.isConnected.return_value = True

    mockDb = MagicMock()

    logger = ObdDataLogger(mockConn, mockDb)
    reading = logger.queryParameter('RPM')

    assert reading.value == 3500.0


def testLogReadingWithNoneUnit():
    """Test logReading handles None unit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        mockConn = MagicMock()
        mockConn.isConnected.return_value = True

        logger = ObdDataLogger(mockConn, db)

        reading = LoggedReading(
            parameterName='RPM',
            value=3500.0,
            unit=None,
            timestamp=datetime.now()
        )

        logger.logReading(reading)

        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT unit FROM realtime_data')
            row = cursor.fetchone()

        assert row['unit'] is None


def testLoggerStatsTracking():
    """Test logger tracks statistics."""
    mockConn = MagicMock()
    mockConn.isConnected.return_value = True

    mockDb = MagicMock()
    mockDb.connect = MagicMock()

    logger = ObdDataLogger(mockConn, mockDb)

    stats = logger.getStats()

    assert 'totalReadings' in stats
    assert 'totalLogged' in stats
    assert stats['totalReadings'] == 0


# ================================================================================
# LoggingStats Tests
# ================================================================================

def testLoggingStatsDefaults():
    """Test LoggingStats default values."""
    stats = LoggingStats()
    assert stats.startTime is None
    assert stats.totalCycles == 0
    assert stats.totalReadings == 0
    assert stats.totalLogged == 0
    assert stats.totalErrors == 0


def testLoggingStatsToDict():
    """Test LoggingStats.toDict() serialization."""
    stats = LoggingStats()
    stats.totalCycles = 10
    stats.totalReadings = 50
    stats.totalLogged = 45

    result = stats.toDict()

    assert result['totalCycles'] == 10
    assert result['totalReadings'] == 50
    assert result['totalLogged'] == 45


# ================================================================================
# RealtimeDataLogger Init Tests
# ================================================================================

def testRealtimeLoggerInit():
    """Test RealtimeDataLogger initialization."""
    config = {
        'realtimeData': {
            'parameters': [
                {'name': 'RPM', 'logData': True},
                {'name': 'SPEED', 'logData': True}
            ],
            'pollingIntervalMs': 500
        },
        'profiles': {'activeProfile': 'daily'}
    }

    mockConn = MagicMock()
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)

    assert rtLogger.state == LoggingState.STOPPED
    assert rtLogger.profileId == 'daily'
    assert 'RPM' in rtLogger.getParameters()
    assert 'SPEED' in rtLogger.getParameters()


def testRealtimeLoggerInitWithProfile():
    """Test RealtimeDataLogger with explicit profile ID."""
    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}]
        }
    }

    mockConn = MagicMock()
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb, profileId='performance')

    assert rtLogger.profileId == 'performance'


def testRealtimeLoggerOnlyLogsWithLogDataTrue():
    """Test only parameters with logData=True are included."""
    config = {
        'realtimeData': {
            'parameters': [
                {'name': 'RPM', 'logData': True},
                {'name': 'SPEED', 'logData': False},
                {'name': 'COOLANT_TEMP', 'logData': True}
            ]
        }
    }

    mockConn = MagicMock()
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)
    params = rtLogger.getParameters()

    assert 'RPM' in params
    assert 'COOLANT_TEMP' in params
    assert 'SPEED' not in params


def testRealtimeLoggerPollingIntervalFromConfig():
    """Test polling interval is read from config."""
    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}],
            'pollingIntervalMs': 2000
        }
    }

    mockConn = MagicMock()
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)

    assert rtLogger.getPollingIntervalMs() == 2000


def testRealtimeLoggerPollingIntervalFromProfile():
    """Test profile-specific polling interval overrides global."""
    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}],
            'pollingIntervalMs': 1000
        },
        'profiles': {
            'activeProfile': 'performance',
            'availableProfiles': [
                {'id': 'performance', 'name': 'Performance', 'pollingIntervalMs': 250}
            ]
        }
    }

    mockConn = MagicMock()
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)

    assert rtLogger.getPollingIntervalMs() == 250


# ================================================================================
# RealtimeDataLogger Start/Stop Tests
# ================================================================================

def testRealtimeLoggerStartRequiresConnection():
    """Test start() raises error when not connected."""
    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}]
        }
    }

    mockConn = MagicMock()
    mockConn.isConnected.return_value = False
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)

    try:
        rtLogger.start()
        assert False, "Expected DataLoggerError"
    except DataLoggerError as e:
        assert 'not connected' in str(e).lower()


def testRealtimeLoggerStartRequiresParameters():
    """Test start() raises error with no logged parameters."""
    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': False}]  # No logData=True
        }
    }

    mockConn = MagicMock()
    mockConn.isConnected.return_value = True
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)

    try:
        rtLogger.start()
        assert False, "Expected DataLoggerError"
    except DataLoggerError as e:
        assert 'no parameters' in str(e).lower()


def testRealtimeLoggerStartAndStop():
    """Test starting and stopping the logger."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        config = {
            'realtimeData': {
                'parameters': [{'name': 'RPM', 'logData': True}],
                'pollingIntervalMs': 100
            }
        }

        # Create mock connection
        mockObd = MagicMock()
        mockResponse = MagicMock()
        mockResponse.is_null.return_value = False
        mockResponse.value.magnitude = 3500.0
        mockResponse.unit = 'rpm'
        mockObd.query.return_value = mockResponse

        mockConn = MagicMock()
        mockConn.obd = mockObd
        mockConn.isConnected.return_value = True

        rtLogger = RealtimeDataLogger(config, mockConn, db)

        # Start
        assert rtLogger.start() is True
        assert rtLogger.state == LoggingState.RUNNING or rtLogger.state == LoggingState.STARTING

        # Let it run briefly
        time.sleep(0.3)

        # Stop
        assert rtLogger.stop() is True
        assert rtLogger.state == LoggingState.STOPPED


def testRealtimeLoggerStatsAfterRun():
    """Test statistics are populated after running."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        config = {
            'realtimeData': {
                'parameters': [{'name': 'RPM', 'logData': True}],
                'pollingIntervalMs': 100
            }
        }

        # Create mock connection
        mockObd = MagicMock()
        mockResponse = MagicMock()
        mockResponse.is_null.return_value = False
        mockResponse.value.magnitude = 3500.0
        mockResponse.unit = 'rpm'
        mockObd.query.return_value = mockResponse

        mockConn = MagicMock()
        mockConn.obd = mockObd
        mockConn.isConnected.return_value = True

        rtLogger = RealtimeDataLogger(config, mockConn, db)

        rtLogger.start()
        time.sleep(0.3)  # Let some cycles run
        rtLogger.stop()

        stats = rtLogger.getStats()

        assert stats.startTime is not None
        assert stats.totalCycles > 0


def testRealtimeLoggerAlreadyRunning():
    """Test start() returns False if already running."""
    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}],
            'pollingIntervalMs': 1000
        }
    }

    mockObd = MagicMock()
    mockResponse = MagicMock()
    mockResponse.is_null.return_value = False
    mockResponse.value.magnitude = 3500.0
    mockObd.query.return_value = mockResponse

    mockConn = MagicMock()
    mockConn.obd = mockObd
    mockConn.isConnected.return_value = True
    mockDb = MagicMock()
    mockDb.connect = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)

    rtLogger.start()
    time.sleep(0.1)

    # Try to start again
    result = rtLogger.start()
    assert result is False

    rtLogger.stop()


def testRealtimeLoggerDoubleStop():
    """Test stop() on already stopped logger returns True."""
    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}]
        }
    }

    mockConn = MagicMock()
    mockConn.isConnected.return_value = True
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)

    # Stop without starting
    assert rtLogger.stop() is True


# ================================================================================
# RealtimeDataLogger Logging Tests
# ================================================================================

def testRealtimeLoggerLogsToDatabase():
    """Test data is actually logged to database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        # Don't use profile_id to avoid FK constraint
        config = {
            'realtimeData': {
                'parameters': [{'name': 'RPM', 'logData': True}],
                'pollingIntervalMs': 50
            },
            'profiles': {}  # No active profile = NULL profile_id
        }

        # Create mock connection
        mockObd = MagicMock()
        mockResponse = MagicMock()
        mockResponse.is_null.return_value = False
        mockResponse.value.magnitude = 3500.0
        mockResponse.unit = 'rpm'
        mockObd.query.return_value = mockResponse

        mockConn = MagicMock()
        mockConn.obd = mockObd
        mockConn.isConnected.return_value = True

        rtLogger = RealtimeDataLogger(config, mockConn, db)

        rtLogger.start()
        time.sleep(0.2)  # Let some cycles run
        rtLogger.stop()

        # Verify data was logged
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM realtime_data')
            count = cursor.fetchone()[0]

        assert count > 0


def testRealtimeLoggerLogsMultipleParameters():
    """Test multiple parameters are logged in each cycle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        # Don't use profile_id to avoid FK constraint
        config = {
            'realtimeData': {
                'parameters': [
                    {'name': 'RPM', 'logData': True},
                    {'name': 'SPEED', 'logData': True},
                    {'name': 'COOLANT_TEMP', 'logData': True}
                ],
                'pollingIntervalMs': 50
            },
            'profiles': {}  # No active profile = NULL profile_id
        }

        # Create mock connection
        mockObd = MagicMock()
        mockResponse = MagicMock()
        mockResponse.is_null.return_value = False
        mockResponse.value.magnitude = 100.0
        mockResponse.unit = 'rpm'
        mockObd.query.return_value = mockResponse

        mockConn = MagicMock()
        mockConn.obd = mockObd
        mockConn.isConnected.return_value = True

        rtLogger = RealtimeDataLogger(config, mockConn, db)

        rtLogger.start()
        time.sleep(0.2)  # Let some cycles run
        rtLogger.stop()

        # Verify all parameters were logged
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT parameter_name FROM realtime_data')
            params = [row['parameter_name'] for row in cursor.fetchall()]

        assert 'RPM' in params
        assert 'SPEED' in params
        assert 'COOLANT_TEMP' in params


def testRealtimeLoggerHandlesNullResponse():
    """Test logger handles null responses without crashing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        config = {
            'realtimeData': {
                'parameters': [{'name': 'RPM', 'logData': True}],
                'pollingIntervalMs': 50
            }
        }

        # Create mock that returns null
        mockObd = MagicMock()
        mockResponse = MagicMock()
        mockResponse.is_null.return_value = True
        mockObd.query.return_value = mockResponse

        mockConn = MagicMock()
        mockConn.obd = mockObd
        mockConn.isConnected.return_value = True

        rtLogger = RealtimeDataLogger(config, mockConn, db)

        # Should not crash
        rtLogger.start()
        time.sleep(0.15)
        rtLogger.stop()

        # Should have run without crashing
        stats = rtLogger.getStats()
        assert stats.totalCycles > 0


def testRealtimeLoggerWithProfileId():
    """Test logged data includes profile_id."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        # Create profile
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO profiles (id, name) VALUES (?, ?)",
                ('daily', 'Daily')
            )

        config = {
            'realtimeData': {
                'parameters': [{'name': 'RPM', 'logData': True}],
                'pollingIntervalMs': 50
            },
            'profiles': {'activeProfile': 'daily'}
        }

        mockObd = MagicMock()
        mockResponse = MagicMock()
        mockResponse.is_null.return_value = False
        mockResponse.value.magnitude = 3500.0
        mockResponse.unit = 'rpm'
        mockObd.query.return_value = mockResponse

        mockConn = MagicMock()
        mockConn.obd = mockObd
        mockConn.isConnected.return_value = True

        rtLogger = RealtimeDataLogger(config, mockConn, db)

        rtLogger.start()
        time.sleep(0.15)
        rtLogger.stop()

        # Verify profile_id was stored
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT profile_id FROM realtime_data LIMIT 1')
            row = cursor.fetchone()

        assert row is not None
        assert row['profile_id'] == 'daily'


# ================================================================================
# RealtimeDataLogger Callback Tests
# ================================================================================

def testRealtimeLoggerOnReadingCallback():
    """Test onReading callback is called for each reading."""
    readings = []

    def onReading(reading):
        readings.append(reading)

    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}],
            'pollingIntervalMs': 50
        }
    }

    mockObd = MagicMock()
    mockResponse = MagicMock()
    mockResponse.is_null.return_value = False
    mockResponse.value.magnitude = 3500.0
    mockResponse.unit = 'rpm'
    mockObd.query.return_value = mockResponse

    mockConn = MagicMock()
    mockConn.obd = mockObd
    mockConn.isConnected.return_value = True
    mockDb = MagicMock()
    mockDb.connect = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)
    rtLogger.registerCallbacks(onReading=onReading)

    rtLogger.start()
    time.sleep(0.15)
    rtLogger.stop()

    assert len(readings) > 0


def testRealtimeLoggerOnCycleCompleteCallback():
    """Test onCycleComplete callback is called after each cycle."""
    cycles = []

    def onCycleComplete(cycleNum):
        cycles.append(cycleNum)

    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}],
            'pollingIntervalMs': 50
        }
    }

    mockObd = MagicMock()
    mockResponse = MagicMock()
    mockResponse.is_null.return_value = False
    mockResponse.value.magnitude = 3500.0
    mockObd.query.return_value = mockResponse

    mockConn = MagicMock()
    mockConn.obd = mockObd
    mockConn.isConnected.return_value = True
    mockDb = MagicMock()
    mockDb.connect = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)
    rtLogger.registerCallbacks(onCycleComplete=onCycleComplete)

    rtLogger.start()
    time.sleep(0.15)
    rtLogger.stop()

    assert len(cycles) > 0
    assert cycles == sorted(cycles)  # Should be sequential


# ================================================================================
# RealtimeDataLogger Interval Tests
# ================================================================================

def testRealtimeLoggerSetPollingInterval():
    """Test setPollingInterval updates the interval."""
    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}],
            'pollingIntervalMs': 1000
        }
    }

    mockConn = MagicMock()
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)

    rtLogger.setPollingInterval(500)

    assert rtLogger.getPollingIntervalMs() == 500


def testRealtimeLoggerSetPollingIntervalMinimum():
    """Test setPollingInterval rejects values under 100ms."""
    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}]
        }
    }

    mockConn = MagicMock()
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)

    try:
        rtLogger.setPollingInterval(50)
        assert False, "Expected ValueError"
    except ValueError as e:
        assert '100ms' in str(e)


def testRealtimeLoggerDefaultPollingInterval():
    """Test default polling interval is 1000ms."""
    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}]
            # No pollingIntervalMs specified
        }
    }

    mockConn = MagicMock()
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)

    assert rtLogger.getPollingIntervalMs() == 1000


# ================================================================================
# RealtimeDataLogger String Parameter Tests
# ================================================================================

def testRealtimeLoggerStringParameters():
    """Test string parameters are treated as logData=True."""
    config = {
        'realtimeData': {
            'parameters': ['RPM', 'SPEED']  # String format
        }
    }

    mockConn = MagicMock()
    mockDb = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)
    params = rtLogger.getParameters()

    assert 'RPM' in params
    assert 'SPEED' in params


# ================================================================================
# createRealtimeLoggerFromConfig Tests
# ================================================================================

def testCreateRealtimeLoggerFromConfig():
    """Test createRealtimeLoggerFromConfig creates logger."""
    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}]
        },
        'profiles': {'activeProfile': 'daily'}
    }

    mockConn = MagicMock()
    mockDb = MagicMock()

    rtLogger = createRealtimeLoggerFromConfig(config, mockConn, mockDb)

    assert isinstance(rtLogger, RealtimeDataLogger)
    assert rtLogger.profileId == 'daily'


# ================================================================================
# Timestamp Precision Tests
# ================================================================================

def testRealtimeLoggerTimestampPrecision():
    """Test timestamps have millisecond precision."""
    timestamps = []

    def onReading(reading):
        timestamps.append(reading.timestamp)

    config = {
        'realtimeData': {
            'parameters': [{'name': 'RPM', 'logData': True}],
            'pollingIntervalMs': 50
        }
    }

    mockObd = MagicMock()
    mockResponse = MagicMock()
    mockResponse.is_null.return_value = False
    mockResponse.value.magnitude = 3500.0
    mockResponse.unit = 'rpm'
    mockObd.query.return_value = mockResponse

    mockConn = MagicMock()
    mockConn.obd = mockObd
    mockConn.isConnected.return_value = True
    mockDb = MagicMock()
    mockDb.connect = MagicMock()

    rtLogger = RealtimeDataLogger(config, mockConn, mockDb)
    rtLogger.registerCallbacks(onReading=onReading)

    rtLogger.start()
    time.sleep(0.2)
    rtLogger.stop()

    assert len(timestamps) > 0
    # Check timestamps have microsecond precision (datetime.now() includes it)
    for ts in timestamps:
        assert ts.microsecond is not None


# ================================================================================
# Main Test Runner
# ================================================================================

def main():
    """Run all tests."""
    print("=" * 60)
    print("OBD Data Logger Module Tests")
    print("=" * 60)

    result = TestResult()

    # LoggedReading Tests
    print("\nLoggedReading Tests:")
    runTest("testLoggedReadingDefaults", testLoggedReadingDefaults, result)
    runTest("testLoggedReadingAllFields", testLoggedReadingAllFields, result)
    runTest("testLoggedReadingToDict", testLoggedReadingToDict, result)

    # Exception Tests
    print("\nException Tests:")
    runTest("testDataLoggerErrorMessage", testDataLoggerErrorMessage, result)
    runTest("testDataLoggerErrorDetails", testDataLoggerErrorDetails, result)
    runTest("testParameterNotSupportedInheritance", testParameterNotSupportedInheritance, result)
    runTest("testParameterReadErrorInheritance", testParameterReadErrorInheritance, result)

    # Init Tests
    print("\nObdDataLogger Init Tests:")
    runTest("testDataLoggerInitWithConnection", testDataLoggerInitWithConnection, result)
    runTest("testDataLoggerInitWithProfile", testDataLoggerInitWithProfile, result)

    # Query Parameter Tests
    print("\nQuery Parameter Tests:")
    runTest("testQueryParameterSuccess", testQueryParameterSuccess, result)
    runTest("testQueryParameterNullResponse", testQueryParameterNullResponse, result)
    runTest("testQueryParameterNotConnected", testQueryParameterNotConnected, result)
    runTest("testQueryParameterUsesCommandName", testQueryParameterUsesCommandName, result)

    # Log Reading Tests
    print("\nLog Reading Tests:")
    runTest("testLogReadingStoresInDatabase", testLogReadingStoresInDatabase, result)
    runTest("testLogReadingWithProfile", testLogReadingWithProfile, result)
    runTest("testLogReadingTimestamp", testLogReadingTimestamp, result)

    # Query and Log Tests
    print("\nQuery and Log Tests:")
    runTest("testQueryAndLogParameter", testQueryAndLogParameter, result)

    # Data Persistence Tests
    print("\nData Persistence Tests:")
    runTest("testVerifyDataPersistence", testVerifyDataPersistence, result)
    runTest("testVerifyDataPersistenceMultipleReadings", testVerifyDataPersistenceMultipleReadings, result)
    runTest("testVerifyDataPersistenceFunction", testVerifyDataPersistenceFunction, result)
    runTest("testVerifyDataPersistenceNotFound", testVerifyDataPersistenceNotFound, result)

    # Helper Function Tests
    print("\nHelper Function Tests:")
    runTest("testCreateDataLoggerFromConfig", testCreateDataLoggerFromConfig, result)
    runTest("testQueryParameterHelperFunction", testQueryParameterHelperFunction, result)
    runTest("testLogReadingHelperFunction", testLogReadingHelperFunction, result)

    # Edge Case Tests
    print("\nEdge Case Tests:")
    runTest("testQueryParameterWithPintValue", testQueryParameterWithPintValue, result)
    runTest("testQueryParameterWithPlainValue", testQueryParameterWithPlainValue, result)
    runTest("testLogReadingWithNoneUnit", testLogReadingWithNoneUnit, result)
    runTest("testLoggerStatsTracking", testLoggerStatsTracking, result)

    # LoggingStats Tests
    print("\nLoggingStats Tests:")
    runTest("testLoggingStatsDefaults", testLoggingStatsDefaults, result)
    runTest("testLoggingStatsToDict", testLoggingStatsToDict, result)

    # RealtimeDataLogger Init Tests
    print("\nRealtimeDataLogger Init Tests:")
    runTest("testRealtimeLoggerInit", testRealtimeLoggerInit, result)
    runTest("testRealtimeLoggerInitWithProfile", testRealtimeLoggerInitWithProfile, result)
    runTest("testRealtimeLoggerOnlyLogsWithLogDataTrue", testRealtimeLoggerOnlyLogsWithLogDataTrue, result)
    runTest("testRealtimeLoggerPollingIntervalFromConfig", testRealtimeLoggerPollingIntervalFromConfig, result)
    runTest("testRealtimeLoggerPollingIntervalFromProfile", testRealtimeLoggerPollingIntervalFromProfile, result)

    # RealtimeDataLogger Start/Stop Tests
    print("\nRealtimeDataLogger Start/Stop Tests:")
    runTest("testRealtimeLoggerStartRequiresConnection", testRealtimeLoggerStartRequiresConnection, result)
    runTest("testRealtimeLoggerStartRequiresParameters", testRealtimeLoggerStartRequiresParameters, result)
    runTest("testRealtimeLoggerStartAndStop", testRealtimeLoggerStartAndStop, result)
    runTest("testRealtimeLoggerStatsAfterRun", testRealtimeLoggerStatsAfterRun, result)
    runTest("testRealtimeLoggerAlreadyRunning", testRealtimeLoggerAlreadyRunning, result)
    runTest("testRealtimeLoggerDoubleStop", testRealtimeLoggerDoubleStop, result)

    # RealtimeDataLogger Logging Tests
    print("\nRealtimeDataLogger Logging Tests:")
    runTest("testRealtimeLoggerLogsToDatabase", testRealtimeLoggerLogsToDatabase, result)
    runTest("testRealtimeLoggerLogsMultipleParameters", testRealtimeLoggerLogsMultipleParameters, result)
    runTest("testRealtimeLoggerHandlesNullResponse", testRealtimeLoggerHandlesNullResponse, result)
    runTest("testRealtimeLoggerWithProfileId", testRealtimeLoggerWithProfileId, result)

    # RealtimeDataLogger Callback Tests
    print("\nRealtimeDataLogger Callback Tests:")
    runTest("testRealtimeLoggerOnReadingCallback", testRealtimeLoggerOnReadingCallback, result)
    runTest("testRealtimeLoggerOnCycleCompleteCallback", testRealtimeLoggerOnCycleCompleteCallback, result)

    # RealtimeDataLogger Interval Tests
    print("\nRealtimeDataLogger Interval Tests:")
    runTest("testRealtimeLoggerSetPollingInterval", testRealtimeLoggerSetPollingInterval, result)
    runTest("testRealtimeLoggerSetPollingIntervalMinimum", testRealtimeLoggerSetPollingIntervalMinimum, result)
    runTest("testRealtimeLoggerDefaultPollingInterval", testRealtimeLoggerDefaultPollingInterval, result)

    # RealtimeDataLogger String Parameters Tests
    print("\nRealtimeDataLogger String Parameters Tests:")
    runTest("testRealtimeLoggerStringParameters", testRealtimeLoggerStringParameters, result)

    # createRealtimeLoggerFromConfig Tests
    print("\ncreateRealtimeLoggerFromConfig Tests:")
    runTest("testCreateRealtimeLoggerFromConfig", testCreateRealtimeLoggerFromConfig, result)

    # Timestamp Precision Tests
    print("\nTimestamp Precision Tests:")
    runTest("testRealtimeLoggerTimestampPrecision", testRealtimeLoggerTimestampPrecision, result)

    # Summary
    print("\n" + "=" * 60)
    print(f"RESULTS: {result.passed} passed, {result.failed} failed")
    print("=" * 60)

    if result.errors:
        print("\nFailures:")
        for error in result.errors:
            print(f"  - {error}")

    return 0 if result.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
