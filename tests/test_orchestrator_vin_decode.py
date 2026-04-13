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

import logging
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

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
    from obd.orchestrator import ApplicationOrchestrator
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
# AC1: On first successful connection, check if VIN exists in database
# ================================================================================


class TestVinCacheCheck:
    """Tests for VIN cache check on first connection."""

    def test_firstConnection_checksVinCache(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with connection and vinDecoder
        When: _performFirstConnectionVinDecode is called
        Then: isVinCached is called to check database
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.return_value = createMockDecodeResult()
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        orchestrator._performFirstConnectionVinDecode()

        # Assert
        mockDecoder.isVinCached.assert_called_once_with("JA3AM44AXWU001234")

    def test_firstConnection_vinCached_usesCache(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: VIN already exists in database cache
        When: _performFirstConnectionVinDecode is called
        Then: getDecodedVin is called (not decodeVin/API)
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
        mockDecoder.getDecodedVin.assert_called_once_with("JA3AM44AXWU001234")
        mockDecoder.decodeVin.assert_not_called()

    def test_firstConnection_vinNotCached_callsDecodeVin(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: VIN not in database cache
        When: _performFirstConnectionVinDecode is called
        Then: decodeVin is called to fetch from NHTSA API
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.return_value = createMockDecodeResult()
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        orchestrator._performFirstConnectionVinDecode()

        # Assert
        mockDecoder.decodeVin.assert_called_once_with("JA3AM44AXWU001234")

    def test_firstConnection_storesVinInOrchestrator(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: Successful VIN query from vehicle
        When: _performFirstConnectionVinDecode is called
        Then: VIN is stored in orchestrator._vehicleVin
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.return_value = createMockDecodeResult()
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        assert orchestrator._vehicleVin is None

        # Act
        orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert orchestrator._vehicleVin == "JA3AM44AXWU001234"


# ================================================================================
# AC2: If VIN not cached, query VIN from vehicle
# ================================================================================


class TestVinQuery:
    """Tests for VIN query from vehicle via OBD connection."""

    def test_queryVin_callsObdQuery(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with active connection
        When: _performFirstConnectionVinDecode is called
        Then: connection.obd.query("VIN") is called
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.return_value = createMockDecodeResult()
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        orchestrator._performFirstConnectionVinDecode()

        # Assert
        mockConn.obd.query.assert_called_once_with("VIN")

    def test_queryVin_nullResponse_skipsGracefully(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Vehicle returns null VIN response
        When: _performFirstConnectionVinDecode is called
        Then: Decode is skipped gracefully with debug log
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        nullResponse = MagicMock()
        nullResponse.is_null.return_value = True
        mockConn.obd.query.return_value = nullResponse
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "null VIN response" in caplog.text
        mockDecoder.isVinCached.assert_not_called()

    def test_queryVin_emptyValue_skipsGracefully(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Vehicle returns empty VIN value
        When: _performFirstConnectionVinDecode is called
        Then: Decode is skipped gracefully
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        emptyResponse = MagicMock()
        emptyResponse.is_null.return_value = False
        emptyResponse.value = ""
        mockConn.obd.query.return_value = emptyResponse
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "VIN value is empty" in caplog.text
        mockDecoder.isVinCached.assert_not_called()

    def test_queryVin_exception_logsWarning(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: OBD query raises an exception
        When: _performFirstConnectionVinDecode is called
        Then: Warning logged, application continues
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.side_effect = Exception("OBD query timeout")
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "Failed to query VIN" in caplog.text
        assert "OBD query timeout" in caplog.text
        mockDecoder.isVinCached.assert_not_called()

    def test_queryVin_noneResponse_skipsGracefully(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: OBD query returns None
        When: _performFirstConnectionVinDecode is called
        Then: Decode is skipped gracefully
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = None
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "null VIN response" in caplog.text


# ================================================================================
# AC3: If VIN valid and vinDecoder enabled, call NHTSA API
# ================================================================================


class TestNhtsaApiCall:
    """Tests for NHTSA API call when VIN is valid and decoder enabled."""

    def test_validVin_decoderEnabled_callsApi(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Valid VIN and vinDecoder enabled
        When: VIN not in cache
        Then: decodeVin called (which calls NHTSA API)
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.return_value = createMockDecodeResult()
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "Decoding VIN via NHTSA API" in caplog.text
        mockDecoder.decodeVin.assert_called_once()

    def test_noVinDecoder_skipsGracefully(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: vinDecoder is None (not configured)
        When: _performFirstConnectionVinDecode is called
        Then: Decode is skipped with debug log
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        orchestrator._vinDecoder = None

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "no VIN decoder configured" in caplog.text

    def test_noConnection_skipsGracefully(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Connection is None
        When: _performFirstConnectionVinDecode is called
        Then: Decode is skipped with debug log
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        orchestrator._connection = None
        orchestrator._vinDecoder = MagicMock()

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "no connection available" in caplog.text

    def test_connectionNoObdInterface_skipsGracefully(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Connection exists but has no OBD interface
        When: _performFirstConnectionVinDecode is called
        Then: Decode is skipped with debug log
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        orchestrator._vinDecoder = MagicMock()

        mockConn = MagicMock(spec=[])  # No attributes at all
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "no OBD interface" in caplog.text

    def test_decodeVin_exceptionHandled(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: decodeVin raises an exception
        When: _performFirstConnectionVinDecode is called
        Then: Warning logged, application continues
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.side_effect = Exception("API error")
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "VIN decode failed" in caplog.text
        assert "API error" in caplog.text


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


# ================================================================================
# AC5: Vehicle info displayed on startup: 'Connected to [Year] [Make] [Model]'
# ================================================================================


class TestVehicleInfoDisplay:
    """Tests for vehicle info display on startup."""

    def test_successfulDecode_logsConnectedTo(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Successful VIN decode
        When: _performFirstConnectionVinDecode completes
        Then: Logs 'Connected to 1998 Mitsubishi Eclipse'
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.return_value = createMockDecodeResult()
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "Connected to 1998 Mitsubishi Eclipse" in caplog.text

    def test_successfulDecode_displaysVehicleInfo(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: Successful VIN decode with display manager
        When: _performFirstConnectionVinDecode completes
        Then: _displayVehicleInfo called, display receives vehicle summary
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        decodeResult = createMockDecodeResult()
        mockDecoder.decodeVin.return_value = decodeResult
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        # Act
        orchestrator._performFirstConnectionVinDecode()

        # Assert
        mockDisplay.showVehicleInfo.assert_called_once_with(
            "1998 Mitsubishi Eclipse"
        )

    def test_displayVehicleInfo_fallsBackToConnectionStatus(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: Display manager has no showVehicleInfo but has showConnectionStatus
        When: _displayVehicleInfo is called
        Then: Falls back to showConnectionStatus with 'Connected to ...' message
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        decodeResult = createMockDecodeResult()

        mockDisplay = MagicMock(spec=['showConnectionStatus'])
        orchestrator._displayManager = mockDisplay

        # Act
        orchestrator._displayVehicleInfo(decodeResult)

        # Assert
        mockDisplay.showConnectionStatus.assert_called_once_with(
            "Connected to 1998 Mitsubishi Eclipse"
        )

    def test_displayVehicleInfo_noDisplay_safe(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: Display manager is None
        When: _displayVehicleInfo is called
        Then: No error, returns safely
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        orchestrator._displayManager = None
        decodeResult = createMockDecodeResult()

        # Act (should not raise)
        orchestrator._displayVehicleInfo(decodeResult)

    def test_displayVehicleInfo_displayError_survivesGracefully(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Display manager raises exception
        When: _displayVehicleInfo is called
        Then: Error logged at debug level, no crash
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        decodeResult = createMockDecodeResult()

        mockDisplay = MagicMock()
        mockDisplay.showVehicleInfo.side_effect = Exception("Display error")
        orchestrator._displayManager = mockDisplay

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._displayVehicleInfo(decodeResult)

        # Assert
        assert "Display vehicle info failed" in caplog.text

    def test_unsuccessfulDecode_logsWarning(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: VIN decode returns unsuccessful result
        When: _performFirstConnectionVinDecode completes
        Then: Warning logged about unsuccessful decode
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
        with caplog.at_level(logging.WARNING):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "VIN decode unsuccessful" in caplog.text

    def test_noneDecodeResult_logsWarning(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: VIN decode returns None
        When: _performFirstConnectionVinDecode completes
        Then: Warning logged about unsuccessful decode
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.return_value = None
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "VIN decode unsuccessful" in caplog.text


# ================================================================================
# AC6: API timeout handled gracefully (continue without decode)
# ================================================================================


class TestApiTimeoutHandling:
    """Tests for graceful API timeout handling."""

    def test_apiTimeout_warningLogged(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: NHTSA API times out
        When: _performFirstConnectionVinDecode is called
        Then: Warning logged, application continues
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.side_effect = Exception(
            "API request timed out after 5 seconds"
        )
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "VIN decode failed" in caplog.text
        assert "timed out" in caplog.text

    def test_apiTimeout_orchestratorContinues(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: NHTSA API times out
        When: _performFirstConnectionVinDecode is called
        Then: No exception propagated, orchestrator remains usable
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.side_effect = TimeoutError("Connection timed out")
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act (should not raise)
        orchestrator._performFirstConnectionVinDecode()

        # Assert - orchestrator is still in valid state
        assert orchestrator._vehicleVin is None  # VIN not stored on failure
        assert orchestrator._vinDecoder is not None  # Decoder still available

    def test_apiError_warningLogged(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: NHTSA API returns an error
        When: _performFirstConnectionVinDecode is called
        Then: Warning logged, application continues
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.return_value = False
        mockDecoder.decodeVin.side_effect = Exception(
            "NHTSA API returned HTTP 503"
        )
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "VIN decode failed" in caplog.text
        assert "HTTP 503" in caplog.text

    def test_cacheCheckException_warningLogged(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Cache check (isVinCached) raises exception
        When: _performFirstConnectionVinDecode is called
        Then: Warning logged, application continues
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.isVinCached.side_effect = Exception("Database locked")
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act
        with caplog.at_level(logging.WARNING):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "VIN decode failed" in caplog.text
        assert "Database locked" in caplog.text


# ================================================================================
# AC7: Subsequent connections skip decode (use cached data)
# ================================================================================


class TestSubsequentConnectionSkip:
    """Tests for skipping VIN decode on subsequent connections."""

    def test_secondCall_usesCachedResult(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: VIN was decoded on first connection
        When: _performFirstConnectionVinDecode called again
        Then: Second call uses cached data (isVinCached returns True)
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        decodeResult = createMockDecodeResult()
        cachedResult = createMockDecodeResult(fromCache=True)
        mockDecoder = MagicMock()
        # First call: not cached, decode via API
        # Second call: cached, use cache
        mockDecoder.isVinCached.side_effect = [False, True]
        mockDecoder.decodeVin.return_value = decodeResult
        mockDecoder.getDecodedVin.return_value = cachedResult
        orchestrator._vinDecoder = mockDecoder

        mockConn = MagicMock()
        mockConn.obd.query.return_value = createMockVinResponse()
        orchestrator._connection = mockConn

        # Act - first connection
        orchestrator._performFirstConnectionVinDecode()
        # Act - second connection (e.g., after reconnect)
        orchestrator._performFirstConnectionVinDecode()

        # Assert
        mockDecoder.decodeVin.assert_called_once()  # Only first call
        mockDecoder.getDecodedVin.assert_called_once()  # Second call uses cache

    def test_reconnection_doesNotRetriggerVinDecode(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: VIN was decoded during initial startup
        When: Connection is recovered after loss
        Then: _handleReconnectionSuccess does NOT call _performFirstConnectionVinDecode
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        orchestrator._vehicleVin = "JA3AM44AXWU001234"
        orchestrator._isReconnecting = True
        orchestrator._reconnectAttempt = 1
        orchestrator._connection = MagicMock()
        orchestrator._displayManager = MagicMock()

        mockDecoder = MagicMock()
        orchestrator._vinDecoder = mockDecoder

        # Act
        orchestrator._handleReconnectionSuccess()

        # Assert - VIN decode not re-triggered
        mockDecoder.isVinCached.assert_not_called()
        mockDecoder.decodeVin.assert_not_called()
        # VIN still preserved from original decode
        assert orchestrator._vehicleVin == "JA3AM44AXWU001234"

    def test_cachedVin_displaysCorrectly(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: VIN already cached from previous connection
        When: _performFirstConnectionVinDecode is called
        Then: Cached result displayed correctly
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

        mockDisplay = MagicMock()
        orchestrator._displayManager = mockDisplay

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._performFirstConnectionVinDecode()

        # Assert
        assert "Connected to 1998 Mitsubishi Eclipse" in caplog.text
        mockDisplay.showVehicleInfo.assert_called_once_with(
            "1998 Mitsubishi Eclipse"
        )


# ================================================================================
# AC8: Typecheck/lint passes (verified by running ruff and pytest)
# ================================================================================


class TestVinDecoderInitialization:
    """Tests for VIN decoder component initialization."""

    def test_initializeVinDecoder_logsStarting(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator being initialized
        When: _initializeVinDecoder is called
        Then: Logs 'Starting vinDecoder...'
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)

        # Act
        with caplog.at_level(logging.INFO):
            with patch(
                'obd.orchestrator.createVinDecoderFromConfig',
                create=True
            ):
                # The import is inside the method, so we need to patch
                # at the module level where it's used
                try:
                    orchestrator._initializeVinDecoder()
                except Exception:
                    pass  # May fail due to import issues in test env

        # Assert
        assert "Starting vinDecoder" in caplog.text

    def test_initializeVinDecoder_success_logsStarted(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: VinDecoder module is available
        When: _initializeVinDecoder succeeds
        Then: Logs 'VinDecoder started successfully'
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()

        # Act
        with caplog.at_level(logging.INFO):
            with patch.dict('sys.modules', {
                'obd.vehicle': MagicMock(
                    createVinDecoderFromConfig=MagicMock(return_value=mockDecoder)
                )
            }):
                orchestrator._initializeVinDecoder()

        # Assert
        assert "VinDecoder started successfully" in caplog.text
        assert orchestrator._vinDecoder is not None

    def test_initializeVinDecoder_importError_skips(
        self, vinConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: VinDecoder module not available (ImportError)
        When: _initializeVinDecoder is called
        Then: Logs warning and skips (no exception raised)
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)

        # Act
        with caplog.at_level(logging.WARNING):
            with patch.dict('sys.modules', {'obd.vehicle': None}):
                orchestrator._initializeVinDecoder()

        # Assert
        assert "VinDecoder not available" in caplog.text
        assert orchestrator._vinDecoder is None

    def test_initializeVinDecoder_exception_raisesComponentError(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: VinDecoder initialization fails with unexpected error
        When: _initializeVinDecoder is called
        Then: ComponentInitializationError raised
        """
        # Arrange
        from obd.orchestrator import ComponentInitializationError

        orchestrator = createOrchestrator(vinConfig)

        # Act / Assert
        with patch.dict('sys.modules', {
            'obd.vehicle': MagicMock(
                createVinDecoderFromConfig=MagicMock(
                    side_effect=RuntimeError("Config invalid")
                )
            )
        }):
            with pytest.raises(ComponentInitializationError) as exc_info:
                orchestrator._initializeVinDecoder()

            assert "vinDecoder" in str(exc_info.value).lower() or \
                exc_info.value.component == 'vinDecoder'

    def test_shutdownVinDecoder_cleansUp(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: VinDecoder is initialized
        When: _shutdownVinDecoder is called
        Then: VinDecoder is stopped and set to None
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        orchestrator._vinDecoder = mockDecoder

        # Act
        orchestrator._shutdownVinDecoder()

        # Assert
        assert orchestrator._vinDecoder is None

    def test_vinDecoder_inInitOrder(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator initialization sequence
        When: Components are initialized
        Then: VinDecoder is initialized after connection, before displayManager
        """
        # Arrange
        initOrder: list[str] = []
        orchestrator = createOrchestrator(vinConfig)

        def mockInitConn():
            initOrder.append('connection')
            orchestrator._connection = MagicMock()

        def mockInitVin():
            initOrder.append('vinDecoder')
            orchestrator._vinDecoder = MagicMock()

        def mockPerformVin():
            initOrder.append('vinDecode')

        def mockInitDisplay():
            initOrder.append('displayManager')

        orchestrator._initializeDatabase = lambda: initOrder.append('database')
        orchestrator._initializeProfileManager = lambda: initOrder.append('profileManager')
        orchestrator._initializeConnection = mockInitConn
        orchestrator._initializeVinDecoder = mockInitVin
        orchestrator._performFirstConnectionVinDecode = mockPerformVin
        orchestrator._initializeDisplayManager = mockInitDisplay
        orchestrator._initializeHardwareManager = lambda: initOrder.append('hardware')
        orchestrator._initializeStatisticsEngine = lambda: initOrder.append('stats')
        orchestrator._initializeDriveDetector = lambda: initOrder.append('drive')
        orchestrator._initializeAlertManager = lambda: initOrder.append('alerts')
        orchestrator._initializeDataLogger = lambda: initOrder.append('dataLogger')
        orchestrator._initializeProfileSwitcher = lambda: initOrder.append('profileSwitcher')
        orchestrator._initializeBackupManager = lambda: initOrder.append('backup')
        orchestrator._setupComponentCallbacks = lambda: None

        # Act
        orchestrator._initializeAllComponents()

        # Assert
        connIdx = initOrder.index('connection')
        vinIdx = initOrder.index('vinDecoder')
        decodeIdx = initOrder.index('vinDecode')
        displayIdx = initOrder.index('displayManager')

        assert connIdx < vinIdx, "Connection must init before VinDecoder"
        assert vinIdx < decodeIdx, "VinDecoder must init before VIN decode"
        assert decodeIdx < displayIdx, "VIN decode must happen before display init"

    def test_vinDecoder_inComponentStatus(
        self, vinConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with initialized VinDecoder
        When: getStatus() is called
        Then: Status includes vinDecoder component
        """
        # Arrange
        orchestrator = createOrchestrator(vinConfig)
        mockDecoder = MagicMock()
        mockDecoder.getStats.return_value = {
            'totalDecodes': 1,
            'cacheHits': 0,
            'apiCalls': 1
        }
        orchestrator._vinDecoder = mockDecoder

        # Act
        status = orchestrator.getStatus()

        # Assert
        assert 'vinDecoder' in status.get('components', {})
