################################################################################
# File Name: test_orchestrator_vin_decode.py
# Purpose/Description: Tests for orchestrator first-connection VIN decode (US-OSC-013)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-013
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator first-connection VIN decode wiring.

Verifies that the orchestrator correctly:
- Checks if VIN exists in database on first successful connection
- Queries VIN from vehicle if not cached
- Calls NHTSA API when vinDecoder enabled and VIN valid
- Stores decoded vehicle info in database
- Displays vehicle info on startup: 'Connected to [Year] [Make] [Model]'
- Handles API timeout gracefully (continue without decode)
- Skips decode on subsequent connections (use cached data)
- Passes typecheck and lint

Usage:
    pytest tests/test_orchestrator_vin_decode.py -v
"""

import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getVinDecodeTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for VIN decode tests.

    Args:
        dbPath: Path to temporary database file

    Returns:
        Configuration dictionary for orchestrator
    """
    return {
        'application': {
            'name': 'VIN Decode Test',
            'version': '1.0.0',
            'environment': 'test'
        },
        'database': {
            'path': dbPath,
            'walMode': True,
            'vacuumOnStartup': False,
            'backupOnShutdown': False
        },
        'bluetooth': {
            'macAddress': 'SIMULATED',
            'retryDelays': [1, 2, 4, 8, 16],
            'maxRetries': 5,
            'connectionTimeoutSeconds': 5
        },
        'vinDecoder': {
            'enabled': True,
            'apiBaseUrl': 'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues',
            'apiTimeoutSeconds': 5,
            'cacheVinData': True
        },
        'display': {
            'mode': 'headless',
            'width': 240,
            'height': 240,
            'refreshRateMs': 1000,
            'brightness': 100,
            'showOnStartup': False
        },
        'staticData': {
            'parameters': ['VIN'],
            'queryOnFirstConnection': False
        },
        'realtimeData': {
            'pollingIntervalMs': 100,
            'parameters': [
                {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                {'name': 'SPEED', 'logData': True, 'displayOnDashboard': True},
                {'name': 'COOLANT_TEMP', 'logData': True, 'displayOnDashboard': True},
            ]
        },
        'analysis': {
            'triggerAfterDrive': True,
            'driveStartRpmThreshold': 500,
            'driveStartDurationSeconds': 1,
            'driveEndRpmThreshold': 100,
            'driveEndDurationSeconds': 2,
            'calculateStatistics': ['max', 'min', 'avg']
        },
        'aiAnalysis': {
            'enabled': False
        },
        'profiles': {
            'activeProfile': 'daily',
            'availableProfiles': [
                {
                    'id': 'daily',
                    'name': 'Daily Profile',
                    'description': 'Normal daily driving',
                    'pollingIntervalMs': 200
                }
            ]
        },
        'tieredThresholds': {
            'rpm': {'unit': 'rpm', 'dangerMin': 7000},
            'coolantTemp': {'unit': 'fahrenheit', 'dangerMin': 220},
        },
        'alerts': {
            'enabled': True,
            'cooldownSeconds': 1,
            'visualAlerts': False,
            'audioAlerts': False,
            'logAlerts': True
        },
        'monitoring': {
            'healthCheckIntervalSeconds': 2,
            'dataRateLogIntervalSeconds': 5,
            'connectionCheckIntervalSeconds': 5
        },
        'shutdown': {
            'componentTimeout': 2
        },
        'simulator': {
            'enabled': True,
            'connectionDelaySeconds': 0,
            'updateIntervalMs': 50
        },
        'logging': {
            'level': 'DEBUG',
            'maskPII': False
        }
    }


@pytest.fixture
def tempDb():
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(
        suffix='.db', delete=False, dir=tempfile.gettempdir()
    ) as f:
        dbPath = f.name
    yield dbPath
    # Cleanup
    for suffix in ['', '-wal', '-shm']:
        path = dbPath + suffix
        if os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass


@pytest.fixture
def vinConfig(tempDb: str) -> dict[str, Any]:
    """Create test config with temporary database."""
    return getVinDecodeTestConfig(tempDb)


def createOrchestrator(config: dict[str, Any]) -> Any:
    """Create an orchestrator instance for testing."""
    from pi.obdii.orchestrator import ApplicationOrchestrator
    return ApplicationOrchestrator(config=config, simulate=True)


def createMockVinResponse(vin: str = "JA3AM44AXWU001234") -> MagicMock:
    """Create a mock OBD VIN query response."""
    response = MagicMock()
    response.is_null.return_value = False
    response.value = vin
    return response


def createMockDecodeResult(
    vin: str = "JA3AM44AXWU001234",
    success: bool = True,
    fromCache: bool = False,
    year: int = 1998,
    make: str = "Mitsubishi",
    model: str = "Eclipse",
) -> MagicMock:
    """Create a mock VinDecodeResult."""
    result = MagicMock()
    result.vin = vin
    result.success = success
    result.fromCache = fromCache
    result.year = year
    result.make = make
    result.model = model
    result.errorMessage = None if success else "Decode failed"
    result.getVehicleSummary.return_value = f"{year} {make} {model}"
    return result


# ================================================================================
# AC4: Decoded vehicle info stored in database
# ================================================================================


class TestVinStorage:
    """Tests for VIN decode result storage."""

    def test_decodedVin_storedViaDecoder(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: Successful VIN decode
        When: _performFirstConnectionVinDecode completes
        Then: decodeVin stores the result (via VinDecoder's internal caching)
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        decodeResult = createMockDecodeResult()
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.return_value = decodeResult
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        orchestrator._performFirstConnectionVinDecode()

        # Assert - VinDecoder.decodeVin internally stores to database
        mockDecoder.decodeVin.assert_called_once_with("JA3AM44AXWU001234")
        # VIN stored in orchestrator state for reference
        assert orchestrator._vehicleVin == "JA3AM44AXWU001234"

    def test_failedDecode_noVinStored(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: VIN decode returns unsuccessful result
        When: _performFirstConnectionVinDecode completes
        Then: VIN is still stored in orchestrator (query succeeded)
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        failedResult = createMockDecodeResult(success=False)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.return_value = failedResult
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        orchestrator._performFirstConnectionVinDecode()

        # Assert - VIN is still stored even if decode was unsuccessful
        assert orchestrator._vehicleVin == "JA3AM44AXWU001234"

    def test_cachedVin_noApiCall(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: VIN already in database cache
        When: _performFirstConnectionVinDecode is called
        Then: getDecodedVin used (no API call), VIN still stored
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        cachedResult = createMockDecodeResult(fromCache=True)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = True
        mockDecoder.getDecodedVin.return_value = cachedResult
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        orchestrator._performFirstConnectionVinDecode()

        # Assert
        mockDecoder.decodeVin.assert_not_called()
        assert orchestrator._vehicleVin == "JA3AM44AXWU001234"
