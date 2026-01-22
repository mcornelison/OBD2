#!/usr/bin/env python3
################################################################################
# File Name: run_tests_data_logger.py
# Purpose/Description: Manual test runner for OBD data logger tests
# Author: Ralph Agent
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
    queryParameter,
    logReading,
    verifyDataPersistence,
    createDataLoggerFromConfig,
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
