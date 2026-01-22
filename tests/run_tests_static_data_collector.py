#!/usr/bin/env python3
################################################################################
# File Name: run_tests_static_data_collector.py
# Purpose/Description: Manual test runner for StaticDataCollector module
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-011
# ================================================================================
################################################################################

"""
Manual test runner for StaticDataCollector module.

This module runs tests without requiring pytest, making it suitable
for environments where pytest may not be available.

Usage:
    python tests/run_tests_static_data_collector.py
"""

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Add src directory to path
srcPath = Path(__file__).parent.parent / 'src'
if str(srcPath) not in sys.path:
    sys.path.insert(0, str(srcPath))

from obd.static_data_collector import (
    StaticDataCollector,
    StaticReading,
    CollectionResult,
    StaticDataError,
    VinNotAvailableError,
    StaticDataStorageError,
    createStaticDataCollectorFromConfig,
    collectStaticDataOnFirstConnection,
    verifyStaticDataExists,
    getStaticDataCount,
)
from obd.database import ObdDatabase


# ================================================================================
# Test Utilities
# ================================================================================

def createTestConfig(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a test configuration dictionary."""
    config = {
        'staticData': {
            'parameters': ['VIN', 'FUEL_TYPE', 'OBD_COMPLIANCE', 'ECU_NAME'],
            'queryOnFirstConnection': True
        },
        'database': {
            'path': ':memory:',
            'walMode': False
        }
    }

    if overrides:
        for key, value in overrides.items():
            parts = key.split('.')
            current = config
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value

    return config


def createMockConnection(isConnected: bool = True, vinValue: str = 'TEST1234567890123') -> MagicMock:
    """Create a mock OBD connection."""
    mockConn = MagicMock()
    mockConn.isConnected.return_value = isConnected

    # Create mock OBD object
    mockObd = MagicMock()

    # Configure query responses
    def mockQuery(cmd):
        response = MagicMock()
        cmdName = cmd if isinstance(cmd, str) else getattr(cmd, 'name', str(cmd))

        if cmdName == 'VIN':
            response.value = vinValue
            response.is_null.return_value = vinValue is None
        elif cmdName == 'FUEL_TYPE':
            response.value = 'Gasoline'
            response.is_null.return_value = False
        elif cmdName == 'OBD_COMPLIANCE':
            response.value = 'OBD-II'
            response.is_null.return_value = False
        elif cmdName == 'ECU_NAME':
            # Simulate unavailable parameter
            response.value = None
            response.is_null.return_value = True
        else:
            response.value = 'TestValue'
            response.is_null.return_value = False

        response.unit = None
        return response

    mockObd.query = mockQuery
    mockConn.obd = mockObd

    return mockConn


def createTestDatabase() -> ObdDatabase:
    """Create an in-memory test database with initialized schema."""
    # Use a temp file for SQLite to allow multiple connections with proper schema
    import tempfile
    tempFile = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    tempFile.close()

    db = ObdDatabase(tempFile.name, walMode=False)
    db.initialize()
    return db


# ================================================================================
# Test Classes
# ================================================================================

class TestStaticReading:
    """Tests for StaticReading dataclass."""

    def test_init_withAllFields(self):
        """StaticReading should initialize with all fields."""
        now = datetime.now()
        reading = StaticReading(
            parameterName='VIN',
            value='1G1YY22G955104367',
            queriedAt=now,
            unit='text'
        )
        assert reading.parameterName == 'VIN'
        assert reading.value == '1G1YY22G955104367'
        assert reading.queriedAt == now
        assert reading.unit == 'text'

    def test_init_withNoneValue(self):
        """StaticReading should accept None value for unavailable params."""
        now = datetime.now()
        reading = StaticReading(
            parameterName='ECU_NAME',
            value=None,
            queriedAt=now
        )
        assert reading.parameterName == 'ECU_NAME'
        assert reading.value is None
        assert reading.unit is None

    def test_toDict_serializesCorrectly(self):
        """toDict should serialize all fields properly."""
        now = datetime.now()
        reading = StaticReading(
            parameterName='FUEL_TYPE',
            value='Gasoline',
            queriedAt=now,
            unit=None
        )
        d = reading.toDict()
        assert d['parameterName'] == 'FUEL_TYPE'
        assert d['value'] == 'Gasoline'
        assert d['queriedAt'] == now.isoformat()
        assert d['unit'] is None


class TestCollectionResult:
    """Tests for CollectionResult dataclass."""

    def test_defaultValues(self):
        """CollectionResult should have sensible defaults."""
        result = CollectionResult()
        assert result.vin is None
        assert result.success is False
        assert result.parametersCollected == 0
        assert result.parametersUnavailable == 0
        assert result.readings == []
        assert result.errorMessage is None
        assert result.wasSkipped is False

    def test_toDict_serializesCorrectly(self):
        """toDict should serialize all fields properly."""
        now = datetime.now()
        reading = StaticReading('VIN', 'TEST123', now)
        result = CollectionResult(
            vin='TEST123',
            success=True,
            parametersCollected=5,
            parametersUnavailable=1,
            readings=[reading],
            errorMessage=None,
            wasSkipped=False
        )
        d = result.toDict()
        assert d['vin'] == 'TEST123'
        assert d['success'] is True
        assert d['parametersCollected'] == 5
        assert d['parametersUnavailable'] == 1
        assert len(d['readings']) == 1
        assert d['wasSkipped'] is False


class TestStaticDataCollector:
    """Tests for StaticDataCollector class."""

    def test_init_extractsConfigCorrectly(self):
        """Should extract configuration parameters correctly."""
        config = createTestConfig()
        mockConn = createMockConnection()
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)

        assert collector._parameters == ['VIN', 'FUEL_TYPE', 'OBD_COMPLIANCE', 'ECU_NAME']
        assert collector._queryOnFirstConnection is True

    def test_init_withEmptyConfig(self):
        """Should handle empty config gracefully."""
        config = {}
        mockConn = createMockConnection()
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)

        assert collector._parameters == []
        assert collector._queryOnFirstConnection is True

    def test_getConfiguredParameters_returnsList(self):
        """getConfiguredParameters should return parameter list."""
        config = createTestConfig()
        mockConn = createMockConnection()
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        params = collector.getConfiguredParameters()

        assert params == ['VIN', 'FUEL_TYPE', 'OBD_COMPLIANCE', 'ECU_NAME']


class TestVinExistsInDatabase:
    """Tests for VIN existence checking."""

    def test_vinExistsInDatabase_notFound(self):
        """Should return False when VIN not in database."""
        config = createTestConfig()
        mockConn = createMockConnection()
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        exists = collector.vinExistsInDatabase('NONEXISTENT123456')

        assert exists is False

    def test_vinExistsInDatabase_foundInVehicleInfo(self):
        """Should return True when VIN in vehicle_info table."""
        config = createTestConfig()
        mockConn = createMockConnection()
        db = createTestDatabase()

        # Insert VIN into vehicle_info
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO vehicle_info (vin) VALUES (?)",
                ('EXISTINGVIN12345',)
            )

        collector = StaticDataCollector(config, mockConn, db)
        exists = collector.vinExistsInDatabase('EXISTINGVIN12345')

        assert exists is True

    def test_vinExistsInDatabase_foundInStaticData(self):
        """Should return True when VIN in static_data table."""
        config = createTestConfig()
        mockConn = createMockConnection()
        db = createTestDatabase()

        # Insert into vehicle_info first (foreign key)
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO vehicle_info (vin) VALUES (?)", ('VIN123456789',))
            cursor.execute(
                "INSERT INTO static_data (vin, parameter_name, value) VALUES (?, ?, ?)",
                ('VIN123456789', 'FUEL_TYPE', 'Gasoline')
            )

        collector = StaticDataCollector(config, mockConn, db)
        exists = collector.vinExistsInDatabase('VIN123456789')

        assert exists is True


class TestShouldCollectStaticData:
    """Tests for shouldCollectStaticData method."""

    def test_shouldCollectStaticData_configDisabled(self):
        """Should return False when queryOnFirstConnection is disabled."""
        config = createTestConfig({'staticData.queryOnFirstConnection': False})
        mockConn = createMockConnection()
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        should = collector.shouldCollectStaticData()

        assert should is False

    def test_shouldCollectStaticData_notConnected(self):
        """Should return False when not connected."""
        config = createTestConfig()
        mockConn = createMockConnection(isConnected=False)
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        should = collector.shouldCollectStaticData()

        assert should is False

    def test_shouldCollectStaticData_vinNotAvailable(self):
        """Should return False when VIN cannot be read."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue=None)
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        should = collector.shouldCollectStaticData()

        assert should is False

    def test_shouldCollectStaticData_vinAlreadyExists(self):
        """Should return False when VIN already exists in database."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='EXISTING_VIN_1234')
        db = createTestDatabase()

        # Insert VIN into vehicle_info
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO vehicle_info (vin) VALUES (?)",
                ('EXISTING_VIN_1234',)
            )

        collector = StaticDataCollector(config, mockConn, db)
        should = collector.shouldCollectStaticData()

        assert should is False

    def test_shouldCollectStaticData_newVin(self):
        """Should return True for new VIN not in database."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='NEW_VIN_1234567')
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        should = collector.shouldCollectStaticData()

        assert should is True


class TestCollectStaticData:
    """Tests for collectStaticData method."""

    def test_collectStaticData_notConnected(self):
        """Should return error when not connected."""
        config = createTestConfig()
        mockConn = createMockConnection(isConnected=False)
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        result = collector.collectStaticData()

        assert result.success is False
        assert 'Not connected' in result.errorMessage

    def test_collectStaticData_vinNotAvailable(self):
        """Should return error when VIN cannot be read."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue=None)
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        result = collector.collectStaticData()

        assert result.success is False
        assert result.vin is None

    def test_collectStaticData_successfulCollection(self):
        """Should collect and store all parameters successfully."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='TEST1234567890123')
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        result = collector.collectStaticData()

        assert result.success is True
        assert result.vin == 'TEST1234567890123'
        assert result.parametersCollected == 3  # VIN, FUEL_TYPE, OBD_COMPLIANCE
        assert result.parametersUnavailable == 1  # ECU_NAME (null)
        assert len(result.readings) == 4
        assert result.wasSkipped is False

    def test_collectStaticData_storesInDatabase(self):
        """Should store collected data in database."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='TEST_DB_STORE_123')
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        result = collector.collectStaticData()

        # Verify vehicle_info record created
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM vehicle_info WHERE vin = ?",
                ('TEST_DB_STORE_123',)
            )
            assert cursor.fetchone()[0] == 1

            # Verify static_data records created
            cursor.execute(
                "SELECT COUNT(*) FROM static_data WHERE vin = ?",
                ('TEST_DB_STORE_123',)
            )
            assert cursor.fetchone()[0] == 4

    def test_collectStaticData_skipsExistingVin(self):
        """Should skip collection when VIN already exists."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='EXISTING_VIN_1234')
        db = createTestDatabase()

        # Insert VIN into vehicle_info
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO vehicle_info (vin) VALUES (?)",
                ('EXISTING_VIN_1234',)
            )

        collector = StaticDataCollector(config, mockConn, db)
        result = collector.collectStaticData()

        assert result.success is True
        assert result.wasSkipped is True
        assert result.parametersCollected == 0

    def test_collectStaticData_forceCollect(self):
        """Should collect even when VIN exists if forceCollect=True."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='FORCE_VIN_1234567')
        db = createTestDatabase()

        # Insert VIN into vehicle_info
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO vehicle_info (vin) VALUES (?)",
                ('FORCE_VIN_1234567',)
            )

        collector = StaticDataCollector(config, mockConn, db)
        result = collector.collectStaticData(forceCollect=True)

        assert result.success is True
        assert result.wasSkipped is False
        assert result.parametersCollected > 0

    def test_collectStaticData_handlesUnavailableParameters(self):
        """Should handle unavailable parameters gracefully with NULL."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='UNAVAIL_VIN_123456')
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        result = collector.collectStaticData()

        # ECU_NAME should be unavailable (NULL)
        ecuReading = next(
            (r for r in result.readings if r.parameterName == 'ECU_NAME'),
            None
        )
        assert ecuReading is not None
        assert ecuReading.value is None

        # Verify it's stored as NULL in database
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM static_data WHERE vin = ? AND parameter_name = ?",
                ('UNAVAIL_VIN_123456', 'ECU_NAME')
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] is None


class TestGetStaticDataForVin:
    """Tests for getStaticDataForVin method."""

    def test_getStaticDataForVin_noData(self):
        """Should return empty list when no data for VIN."""
        config = createTestConfig()
        mockConn = createMockConnection()
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        readings = collector.getStaticDataForVin('NONEXISTENT')

        assert readings == []

    def test_getStaticDataForVin_returnsStoredData(self):
        """Should return all stored data for VIN."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='GET_DATA_VIN_1234')
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        collector.collectStaticData()

        readings = collector.getStaticDataForVin('GET_DATA_VIN_1234')

        assert len(readings) == 4
        paramNames = [r.parameterName for r in readings]
        assert 'VIN' in paramNames
        assert 'FUEL_TYPE' in paramNames


class TestVinCaching:
    """Tests for VIN caching functionality."""

    def test_getCachedVin_initiallyNone(self):
        """getCachedVin should return None initially."""
        config = createTestConfig()
        mockConn = createMockConnection()
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)

        assert collector.getCachedVin() is None

    def test_getCachedVin_afterCollection(self):
        """getCachedVin should return VIN after collection."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='CACHED_VIN_1234567')
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        collector.collectStaticData()

        assert collector.getCachedVin() == 'CACHED_VIN_1234567'

    def test_clearCachedVin(self):
        """clearCachedVin should reset cached VIN to None."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='CLEAR_VIN_12345678')
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        collector.collectStaticData()

        assert collector.getCachedVin() is not None

        collector.clearCachedVin()

        assert collector.getCachedVin() is None


class TestHelperFunctions:
    """Tests for module helper functions."""

    def test_createStaticDataCollectorFromConfig(self):
        """createStaticDataCollectorFromConfig should create collector."""
        config = createTestConfig()
        mockConn = createMockConnection()
        db = createTestDatabase()

        collector = createStaticDataCollectorFromConfig(config, mockConn, db)

        assert isinstance(collector, StaticDataCollector)
        assert collector.config == config

    def test_collectStaticDataOnFirstConnection_newVin(self):
        """collectStaticDataOnFirstConnection should collect for new VIN."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='HELPER_VIN_1234567')
        db = createTestDatabase()

        result = collectStaticDataOnFirstConnection(config, mockConn, db)

        assert result.success is True
        assert result.wasSkipped is False

    def test_collectStaticDataOnFirstConnection_existingVin(self):
        """collectStaticDataOnFirstConnection should skip for existing VIN."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='EXIST_HELP_VIN_123')
        db = createTestDatabase()

        # Insert VIN
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO vehicle_info (vin) VALUES (?)",
                ('EXIST_HELP_VIN_123',)
            )

        result = collectStaticDataOnFirstConnection(config, mockConn, db)

        assert result.success is True
        assert result.wasSkipped is True

    def test_verifyStaticDataExists_true(self):
        """verifyStaticDataExists should return True when data exists."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='VERIFY_VIN_12345678')
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        collector.collectStaticData()

        exists = verifyStaticDataExists(db, 'VERIFY_VIN_12345678')

        assert exists is True

    def test_verifyStaticDataExists_false(self):
        """verifyStaticDataExists should return False when no data."""
        db = createTestDatabase()

        exists = verifyStaticDataExists(db, 'NONEXISTENT_VIN')

        assert exists is False

    def test_getStaticDataCount(self):
        """getStaticDataCount should return correct count."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='COUNT_VIN_123456789')
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        collector.collectStaticData()

        count = getStaticDataCount(db, 'COUNT_VIN_123456789')

        assert count == 4  # 4 parameters configured


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_emptyParametersList(self):
        """Should handle empty parameters list."""
        config = createTestConfig({'staticData.parameters': []})
        mockConn = createMockConnection(vinValue='EMPTY_PARAM_VIN_12')
        db = createTestDatabase()

        collector = StaticDataCollector(config, mockConn, db)
        result = collector.collectStaticData()

        assert result.success is True
        assert result.parametersCollected == 0
        assert len(result.readings) == 0

    def test_queryExceptionHandling(self):
        """Should handle query exceptions gracefully."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='EXCEPTION_VIN_1234')
        db = createTestDatabase()

        # Make one parameter query throw exception
        originalQuery = mockConn.obd.query
        def faultyQuery(cmd):
            cmdName = cmd if isinstance(cmd, str) else str(cmd)
            if 'FUEL_TYPE' in cmdName:
                raise RuntimeError("Simulated query error")
            return originalQuery(cmd)
        mockConn.obd.query = faultyQuery

        collector = StaticDataCollector(config, mockConn, db)
        result = collector.collectStaticData()

        # Should still succeed overall (graceful handling)
        assert result.success is True
        # FUEL_TYPE should be marked as unavailable
        fuelReading = next(
            (r for r in result.readings if r.parameterName == 'FUEL_TYPE'),
            None
        )
        assert fuelReading is not None
        assert fuelReading.value is None

    def test_databaseErrorOnVinCheck(self):
        """Should handle database errors during VIN check."""
        config = createTestConfig()
        mockConn = createMockConnection(vinValue='DB_ERROR_VIN_12345')

        # Create a mock database that throws errors
        mockDb = MagicMock()
        mockDb.connect.side_effect = Exception("Database error")

        collector = StaticDataCollector(config, mockConn, mockDb)
        exists = collector.vinExistsInDatabase('ANY_VIN')

        # Should return False on error (safe default)
        assert exists is False

    def test_tupleResponseValue(self):
        """Should handle tuple response values correctly."""
        config = createTestConfig({'staticData.parameters': ['CALIBRATION_ID']})
        mockConn = createMockConnection(vinValue='TUPLE_VIN_123456789')
        db = createTestDatabase()

        # Configure mock to return tuple
        def tupleQuery(cmd):
            response = MagicMock()
            cmdName = cmd if isinstance(cmd, str) else str(cmd)
            if cmdName == 'VIN':
                response.value = 'TUPLE_VIN_123456789'
                response.is_null.return_value = False
            elif cmdName == 'CALIBRATION_ID':
                response.value = ('CAL001', 'CAL002')
                response.is_null.return_value = False
            else:
                response.value = 'Default'
                response.is_null.return_value = False
            response.unit = None
            return response
        mockConn.obd.query = tupleQuery

        collector = StaticDataCollector(config, mockConn, db)
        result = collector.collectStaticData()

        calReading = next(
            (r for r in result.readings if r.parameterName == 'CALIBRATION_ID'),
            None
        )
        assert calReading is not None
        assert calReading.value == 'CAL001, CAL002'

    def test_listResponseValue(self):
        """Should handle list response values correctly."""
        config = createTestConfig({'staticData.parameters': ['GET_DTC']})
        mockConn = createMockConnection(vinValue='LIST_VIN_1234567890')
        db = createTestDatabase()

        # Configure mock to return list
        def listQuery(cmd):
            response = MagicMock()
            cmdName = cmd if isinstance(cmd, str) else str(cmd)
            if cmdName == 'VIN':
                response.value = 'LIST_VIN_1234567890'
                response.is_null.return_value = False
            elif cmdName == 'GET_DTC':
                response.value = ['P0300', 'P0420']
                response.is_null.return_value = False
            else:
                response.value = 'Default'
                response.is_null.return_value = False
            response.unit = None
            return response
        mockConn.obd.query = listQuery

        collector = StaticDataCollector(config, mockConn, db)
        result = collector.collectStaticData()

        dtcReading = next(
            (r for r in result.readings if r.parameterName == 'GET_DTC'),
            None
        )
        assert dtcReading is not None
        assert dtcReading.value == 'P0300, P0420'


# ================================================================================
# Test Runner
# ================================================================================

def runTests():
    """Run all tests and report results."""
    testClasses = [
        TestStaticReading,
        TestCollectionResult,
        TestStaticDataCollector,
        TestVinExistsInDatabase,
        TestShouldCollectStaticData,
        TestCollectStaticData,
        TestGetStaticDataForVin,
        TestVinCaching,
        TestHelperFunctions,
        TestEdgeCases,
    ]

    totalTests = 0
    passedTests = 0
    failedTests = 0
    errors = []

    print("\n" + "=" * 70)
    print("StaticDataCollector Module Tests")
    print("=" * 70 + "\n")

    for testClass in testClasses:
        className = testClass.__name__
        print(f"\n{className}")
        print("-" * len(className))

        instance = testClass()
        methods = [m for m in dir(instance) if m.startswith('test_')]

        for methodName in methods:
            totalTests += 1
            method = getattr(instance, methodName)

            try:
                method()
                print(f"  [PASS] {methodName}")
                passedTests += 1
            except AssertionError as e:
                print(f"  [FAIL] {methodName}")
                print(f"         {e}")
                failedTests += 1
                errors.append((className, methodName, str(e)))
            except Exception as e:
                print(f"  [ERROR] {methodName}")
                print(f"          {type(e).__name__}: {e}")
                failedTests += 1
                errors.append((className, methodName, f"{type(e).__name__}: {e}"))

    print("\n" + "=" * 70)
    print(f"Results: {passedTests}/{totalTests} tests passed")
    print("=" * 70)

    if errors:
        print("\nFailures and Errors:")
        for className, methodName, error in errors:
            print(f"  {className}.{methodName}: {error}")

    return failedTests == 0


if __name__ == '__main__':
    success = runTests()
    sys.exit(0 if success else 1)
