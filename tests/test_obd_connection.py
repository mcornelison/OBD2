################################################################################
# File Name: test_obd_connection.py
# Purpose/Description: Tests for Bluetooth OBD-II connection module
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-003
# ================================================================================
################################################################################

"""
Tests for the OBD-II connection module.

Run with:
    pytest tests/test_obd_connection.py -v
"""

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch, call

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from obd.obd_connection import (
    ObdConnection,
    ObdConnectionError,
    ObdConnectionTimeoutError,
    ObdNotAvailableError,
    ObdConnectionFailedError,
    ConnectionState,
    ConnectionStatus,
    createConnectionFromConfig,
    isObdAvailable,
    DEFAULT_RETRY_DELAYS,
    DEFAULT_CONNECTION_TIMEOUT,
    EVENT_TYPE_CONNECT_ATTEMPT,
    EVENT_TYPE_CONNECT_SUCCESS,
    EVENT_TYPE_CONNECT_FAILURE,
    EVENT_TYPE_DISCONNECT,
    EVENT_TYPE_RECONNECT,
)

from obd.database import ObdDatabase


# ================================================================================
# Fixtures
# ================================================================================

@pytest.fixture
def validConfig() -> Dict[str, Any]:
    """Provide valid OBD configuration."""
    return {
        'bluetooth': {
            'macAddress': '00:11:22:33:44:55',
            'retryDelays': [1, 2, 4, 8, 16],
            'maxRetries': 5,
            'connectionTimeoutSeconds': 30
        }
    }


@pytest.fixture
def minimalConfig() -> Dict[str, Any]:
    """Provide minimal configuration without bluetooth section."""
    return {}


@pytest.fixture
def tempDb(tmp_path: Path) -> ObdDatabase:
    """Provide initialized temporary database."""
    dbPath = str(tmp_path / 'test_obd.db')
    db = ObdDatabase(dbPath)
    db.initialize()
    return db


@pytest.fixture
def mockObdConnection():
    """Provide mock OBD connection object."""
    mock = MagicMock()
    mock.is_connected.return_value = True
    return mock


@pytest.fixture
def mockObdFactory(mockObdConnection):
    """Provide factory that creates mock OBD connections."""
    def factory(macAddress: str, timeout: int):
        return mockObdConnection
    return factory


@pytest.fixture
def failingObdFactory():
    """Provide factory that always fails."""
    def factory(macAddress: str, timeout: int):
        raise ObdConnectionError("Connection failed")
    return factory


# ================================================================================
# ConnectionStatus Tests
# ================================================================================

class TestConnectionStatus:
    """Tests for ConnectionStatus dataclass."""

    def test_init_defaults_hasCorrectValues(self):
        """
        Given: No arguments
        When: ConnectionStatus is created
        Then: Defaults are applied correctly
        """
        status = ConnectionStatus()

        assert status.state == ConnectionState.DISCONNECTED
        assert status.macAddress is None
        assert status.connected is False
        assert status.lastConnectTime is None
        assert status.lastErrorTime is None
        assert status.lastError is None
        assert status.retryCount == 0
        assert status.totalConnections == 0
        assert status.totalErrors == 0

    def test_init_withValues_storesValues(self):
        """
        Given: Custom values
        When: ConnectionStatus is created
        Then: Values are stored correctly
        """
        now = datetime.now()
        status = ConnectionStatus(
            state=ConnectionState.CONNECTED,
            macAddress='00:11:22:33:44:55',
            connected=True,
            lastConnectTime=now,
            totalConnections=5
        )

        assert status.state == ConnectionState.CONNECTED
        assert status.macAddress == '00:11:22:33:44:55'
        assert status.connected is True
        assert status.lastConnectTime == now
        assert status.totalConnections == 5

    def test_toDict_returnsCorrectStructure(self):
        """
        Given: ConnectionStatus with values
        When: toDict is called
        Then: Returns correct dictionary structure
        """
        now = datetime.now()
        status = ConnectionStatus(
            state=ConnectionState.CONNECTED,
            macAddress='00:11:22:33:44:55',
            connected=True,
            lastConnectTime=now,
            totalConnections=1
        )

        result = status.toDict()

        assert result['state'] == 'connected'
        assert result['macAddress'] == '00:11:22:33:44:55'
        assert result['connected'] is True
        assert result['lastConnectTime'] == now.isoformat()
        assert result['totalConnections'] == 1

    def test_toDict_withNullDates_handlesGracefully(self):
        """
        Given: ConnectionStatus with null dates
        When: toDict is called
        Then: Returns None for date fields
        """
        status = ConnectionStatus()
        result = status.toDict()

        assert result['lastConnectTime'] is None
        assert result['lastErrorTime'] is None


# ================================================================================
# Custom Exception Tests
# ================================================================================

class TestObdConnectionError:
    """Tests for ObdConnectionError exception."""

    def test_init_withMessage_storesMessage(self):
        """
        Given: Error message
        When: ObdConnectionError is created
        Then: Message is accessible
        """
        error = ObdConnectionError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"

    def test_init_withDetails_storesDetails(self):
        """
        Given: Error with details
        When: ObdConnectionError is created
        Then: Details are accessible
        """
        error = ObdConnectionError("Test error", details={'key': 'value'})
        assert error.details == {'key': 'value'}

    def test_init_withoutDetails_hasEmptyDict(self):
        """
        Given: Error without details
        When: ObdConnectionError is created
        Then: Details is empty dict
        """
        error = ObdConnectionError("Test error")
        assert error.details == {}


class TestObdConnectionTimeoutError:
    """Tests for ObdConnectionTimeoutError exception."""

    def test_inheritance_isObdConnectionError(self):
        """
        Given: ObdConnectionTimeoutError
        When: Checking inheritance
        Then: Is subclass of ObdConnectionError
        """
        error = ObdConnectionTimeoutError("Timeout")
        assert isinstance(error, ObdConnectionError)


class TestObdNotAvailableError:
    """Tests for ObdNotAvailableError exception."""

    def test_inheritance_isObdConnectionError(self):
        """
        Given: ObdNotAvailableError
        When: Checking inheritance
        Then: Is subclass of ObdConnectionError
        """
        error = ObdNotAvailableError("Not available")
        assert isinstance(error, ObdConnectionError)


# ================================================================================
# ObdConnection Initialization Tests
# ================================================================================

class TestObdConnectionInit:
    """Tests for ObdConnection initialization."""

    def test_init_withValidConfig_extractsBluetoothSettings(self, validConfig, mockObdFactory):
        """
        Given: Valid configuration
        When: ObdConnection is created
        Then: Bluetooth settings are extracted
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)

        assert conn.macAddress == '00:11:22:33:44:55'
        assert conn.retryDelays == [1, 2, 4, 8, 16]
        assert conn.maxRetries == 5
        assert conn.connectionTimeout == 30

    def test_init_withMinimalConfig_usesDefaults(self, minimalConfig, mockObdFactory):
        """
        Given: Minimal configuration without bluetooth section
        When: ObdConnection is created
        Then: Defaults are used
        """
        conn = ObdConnection(minimalConfig, obdFactory=mockObdFactory)

        assert conn.macAddress == ''
        assert conn.retryDelays == DEFAULT_RETRY_DELAYS
        assert conn.connectionTimeout == DEFAULT_CONNECTION_TIMEOUT

    def test_init_setsInitialStatus(self, validConfig, mockObdFactory):
        """
        Given: Valid configuration
        When: ObdConnection is created
        Then: Initial status is disconnected
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)
        status = conn.getStatus()

        assert status.state == ConnectionState.DISCONNECTED
        assert status.connected is False
        assert status.macAddress == '00:11:22:33:44:55'


# ================================================================================
# Connection Tests
# ================================================================================

class TestConnect:
    """Tests for ObdConnection.connect()."""

    def test_connect_success_returnsTrue(self, validConfig, mockObdFactory):
        """
        Given: Valid configuration and working dongle
        When: connect is called
        Then: Returns True and status is connected
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)

        result = conn.connect()

        assert result is True
        status = conn.getStatus()
        assert status.state == ConnectionState.CONNECTED
        assert status.connected is True
        assert status.totalConnections == 1

    def test_connect_success_setsLastConnectTime(self, validConfig, mockObdFactory):
        """
        Given: Successful connection
        When: connect completes
        Then: lastConnectTime is set
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)

        conn.connect()

        status = conn.getStatus()
        assert status.lastConnectTime is not None
        assert isinstance(status.lastConnectTime, datetime)

    def test_connect_withDatabase_logsEvents(self, validConfig, tempDb, mockObdFactory):
        """
        Given: Connection with database
        When: connect succeeds
        Then: Events are logged to database
        """
        conn = ObdConnection(validConfig, database=tempDb, obdFactory=mockObdFactory)

        conn.connect()

        # Verify connection log entries
        with tempDb.connect() as dbConn:
            cursor = dbConn.cursor()
            cursor.execute('SELECT event_type, success FROM connection_log ORDER BY id')
            rows = cursor.fetchall()

        assert len(rows) >= 2
        # First event is connect_attempt
        assert rows[0]['event_type'] == EVENT_TYPE_CONNECT_ATTEMPT
        # Second event is connect_success
        assert rows[1]['event_type'] == EVENT_TYPE_CONNECT_SUCCESS
        assert rows[1]['success'] == 1

    def test_connect_failure_returnsFalse(self, validConfig, failingObdFactory):
        """
        Given: Failing connection
        When: connect is called
        Then: Returns False after all retries
        """
        # Use short retry delays for faster test
        validConfig['bluetooth']['retryDelays'] = [0.01, 0.01]
        validConfig['bluetooth']['maxRetries'] = 2
        conn = ObdConnection(validConfig, obdFactory=failingObdFactory)

        result = conn.connect()

        assert result is False
        status = conn.getStatus()
        assert status.state == ConnectionState.ERROR
        assert status.lastError is not None

    def test_connect_failure_incrementsErrorCount(self, validConfig, failingObdFactory):
        """
        Given: Failing connection
        When: connect fails
        Then: totalErrors is incremented
        """
        validConfig['bluetooth']['retryDelays'] = [0.01]
        validConfig['bluetooth']['maxRetries'] = 1
        conn = ObdConnection(validConfig, obdFactory=failingObdFactory)

        conn.connect()

        status = conn.getStatus()
        assert status.totalErrors == 2  # Initial attempt + 1 retry

    def test_connect_failure_setsLastError(self, validConfig, failingObdFactory):
        """
        Given: Failing connection
        When: connect fails
        Then: lastError contains error message
        """
        validConfig['bluetooth']['retryDelays'] = [0.01]
        validConfig['bluetooth']['maxRetries'] = 1
        conn = ObdConnection(validConfig, obdFactory=failingObdFactory)

        conn.connect()

        status = conn.getStatus()
        assert 'Connection failed' in status.lastError

    def test_connect_retries_withExponentialBackoff(self, validConfig):
        """
        Given: Failing connection with retry delays
        When: connect retries
        Then: Uses exponential backoff delays
        """
        callTimes = []

        def trackingFactory(macAddress: str, timeout: int):
            callTimes.append(time.time())
            raise ObdConnectionError("Failure")

        validConfig['bluetooth']['retryDelays'] = [0.1, 0.2, 0.4]
        validConfig['bluetooth']['maxRetries'] = 3
        conn = ObdConnection(validConfig, obdFactory=trackingFactory)

        conn.connect()

        # Verify delays between calls
        assert len(callTimes) == 4  # Initial + 3 retries
        # Check delay between first and second call (should be ~0.1s)
        delay1 = callTimes[1] - callTimes[0]
        assert 0.08 <= delay1 <= 0.15
        # Check delay between second and third call (should be ~0.2s)
        delay2 = callTimes[2] - callTimes[1]
        assert 0.18 <= delay2 <= 0.25

    def test_connect_noObdLibrary_raisesObdNotAvailableError(self, validConfig):
        """
        Given: No OBD library and no factory
        When: connect is called
        Then: Raises ObdNotAvailableError
        """
        conn = ObdConnection(validConfig)
        conn._obdFactory = None

        with patch('obd.obd_connection.OBD_AVAILABLE', False):
            with pytest.raises(ObdNotAvailableError):
                conn.connect()


# ================================================================================
# Disconnect Tests
# ================================================================================

class TestDisconnect:
    """Tests for ObdConnection.disconnect()."""

    def test_disconnect_whenConnected_closesConnection(self, validConfig, mockObdFactory, mockObdConnection):
        """
        Given: Connected OBD connection
        When: disconnect is called
        Then: Connection is closed
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)
        conn.connect()

        conn.disconnect()

        mockObdConnection.close.assert_called_once()

    def test_disconnect_updatesStatus(self, validConfig, mockObdFactory):
        """
        Given: Connected OBD connection
        When: disconnect is called
        Then: Status is updated to disconnected
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)
        conn.connect()

        conn.disconnect()

        status = conn.getStatus()
        assert status.state == ConnectionState.DISCONNECTED
        assert status.connected is False

    def test_disconnect_whenNotConnected_handlesGracefully(self, validConfig, mockObdFactory):
        """
        Given: Not connected
        When: disconnect is called
        Then: No error is raised
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)

        # Should not raise
        conn.disconnect()

        status = conn.getStatus()
        assert status.state == ConnectionState.DISCONNECTED

    def test_disconnect_withDatabase_logsEvent(self, validConfig, tempDb, mockObdFactory):
        """
        Given: Connection with database
        When: disconnect is called
        Then: Event is logged
        """
        conn = ObdConnection(validConfig, database=tempDb, obdFactory=mockObdFactory)
        conn.connect()

        conn.disconnect()

        with tempDb.connect() as dbConn:
            cursor = dbConn.cursor()
            cursor.execute(
                'SELECT event_type FROM connection_log WHERE event_type = ?',
                (EVENT_TYPE_DISCONNECT,)
            )
            rows = cursor.fetchall()

        assert len(rows) == 1

    def test_disconnect_closeError_handledGracefully(self, validConfig, mockObdFactory, mockObdConnection):
        """
        Given: Connection where close() raises error
        When: disconnect is called
        Then: Error is handled gracefully
        """
        mockObdConnection.close.side_effect = Exception("Close error")
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)
        conn.connect()

        # Should not raise
        conn.disconnect()

        status = conn.getStatus()
        assert status.state == ConnectionState.DISCONNECTED


# ================================================================================
# Reconnect Tests
# ================================================================================

class TestReconnect:
    """Tests for ObdConnection.reconnect()."""

    def test_reconnect_disconnectsAndConnects(self, validConfig, mockObdFactory, mockObdConnection):
        """
        Given: Connected OBD connection
        When: reconnect is called
        Then: Disconnects then connects again
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)
        conn.connect()
        mockObdConnection.reset_mock()

        result = conn.reconnect()

        assert result is True
        mockObdConnection.close.assert_called_once()

    def test_reconnect_whenNotConnected_connects(self, validConfig, mockObdFactory):
        """
        Given: Not connected
        When: reconnect is called
        Then: Connects successfully
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)

        result = conn.reconnect()

        assert result is True
        status = conn.getStatus()
        assert status.connected is True


# ================================================================================
# isConnected Tests
# ================================================================================

class TestIsConnected:
    """Tests for ObdConnection.isConnected()."""

    def test_isConnected_whenConnected_returnsTrue(self, validConfig, mockObdFactory):
        """
        Given: Connected OBD connection
        When: isConnected is called
        Then: Returns True
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)
        conn.connect()

        assert conn.isConnected() is True

    def test_isConnected_whenNotConnected_returnsFalse(self, validConfig, mockObdFactory):
        """
        Given: Not connected
        When: isConnected is called
        Then: Returns False
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)

        assert conn.isConnected() is False

    def test_isConnected_afterDisconnect_returnsFalse(self, validConfig, mockObdFactory):
        """
        Given: Connected then disconnected
        When: isConnected is called
        Then: Returns False
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)
        conn.connect()
        conn.disconnect()

        assert conn.isConnected() is False


# ================================================================================
# getStatus Tests
# ================================================================================

class TestGetStatus:
    """Tests for ObdConnection.getStatus()."""

    def test_getStatus_returnsConnectionStatus(self, validConfig, mockObdFactory):
        """
        Given: ObdConnection instance
        When: getStatus is called
        Then: Returns ConnectionStatus object
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)

        status = conn.getStatus()

        assert isinstance(status, ConnectionStatus)

    def test_getStatus_updatesConnectedState(self, validConfig, mockObdFactory, mockObdConnection):
        """
        Given: Connection where is_connected changes
        When: getStatus is called
        Then: connected state reflects current state
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)
        conn.connect()

        # Initially connected
        assert conn.getStatus().connected is True

        # Simulate disconnection
        mockObdConnection.is_connected.return_value = False
        assert conn.getStatus().connected is False


# ================================================================================
# Helper Function Tests
# ================================================================================

class TestCreateConnectionFromConfig:
    """Tests for createConnectionFromConfig helper."""

    def test_createsObdConnection(self, validConfig):
        """
        Given: Valid configuration
        When: createConnectionFromConfig is called
        Then: Returns ObdConnection instance
        """
        conn = createConnectionFromConfig(validConfig)

        assert isinstance(conn, ObdConnection)
        assert conn.macAddress == '00:11:22:33:44:55'

    def test_acceptsDatabase(self, validConfig, tempDb):
        """
        Given: Configuration and database
        When: createConnectionFromConfig is called
        Then: Database is passed to connection
        """
        conn = createConnectionFromConfig(validConfig, tempDb)

        assert conn.database is tempDb


class TestIsObdAvailable:
    """Tests for isObdAvailable helper."""

    def test_returnsBoolean(self):
        """
        Given: Any environment
        When: isObdAvailable is called
        Then: Returns boolean
        """
        result = isObdAvailable()
        assert isinstance(result, bool)


# ================================================================================
# Edge Case Tests
# ================================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_connect_withEmptyMacAddress_handlesGracefully(self, mockObdFactory):
        """
        Given: Empty MAC address
        When: connect is called
        Then: Handles gracefully (no error)
        """
        config = {'bluetooth': {'macAddress': ''}}
        conn = ObdConnection(config, obdFactory=mockObdFactory)

        result = conn.connect()
        assert result is True

    def test_connect_maxRetriesZero_triesToConnectOnce(self, failingObdFactory):
        """
        Given: maxRetries = 0
        When: connect fails
        Then: Only attempts once
        """
        callCount = [0]

        def countingFactory(mac, timeout):
            callCount[0] += 1
            raise ObdConnectionError("Fail")

        config = {
            'bluetooth': {
                'maxRetries': 0,
                'retryDelays': []
            }
        }
        conn = ObdConnection(config, obdFactory=countingFactory)

        conn.connect()

        assert callCount[0] == 1

    def test_connect_retryDelaysEmpty_usesZeroDelay(self):
        """
        Given: Empty retry delays list
        When: connect retries
        Then: Uses zero delay (no sleep)
        """
        config = {
            'bluetooth': {
                'maxRetries': 1,
                'retryDelays': []
            }
        }

        callCount = [0]

        def countingFactory(mac, timeout):
            callCount[0] += 1
            raise ObdConnectionError("Fail")

        conn = ObdConnection(config, obdFactory=countingFactory)

        startTime = time.time()
        conn.connect()
        duration = time.time() - startTime

        # Should complete quickly since no delay
        assert duration < 1.0

    def test_databaseLogging_whenDatabaseFails_continuesWithoutError(self, validConfig, mockObdFactory):
        """
        Given: Database that raises on insert
        When: connection events are logged
        Then: Continues without raising
        """
        mockDb = MagicMock()
        mockDb.connect.side_effect = Exception("DB error")

        conn = ObdConnection(validConfig, database=mockDb, obdFactory=mockObdFactory)

        # Should not raise
        result = conn.connect()
        assert result is True

    def test_status_multipleConnections_tracksTotals(self, validConfig, mockObdFactory):
        """
        Given: Multiple connect/disconnect cycles
        When: checking status
        Then: Totals are accumulated correctly
        """
        conn = ObdConnection(validConfig, obdFactory=mockObdFactory)

        conn.connect()
        conn.disconnect()
        conn.connect()
        conn.disconnect()
        conn.connect()

        status = conn.getStatus()
        assert status.totalConnections == 3

    def test_connect_factoryReturnsDisconnected_retriesAndFails(self, validConfig):
        """
        Given: Factory returns connection that is not connected
        When: connect is called
        Then: Treats as failure and retries
        """
        disconnectedMock = MagicMock()
        disconnectedMock.is_connected.return_value = False

        def disconnectedFactory(mac, timeout):
            return disconnectedMock

        validConfig['bluetooth']['retryDelays'] = [0.01]
        validConfig['bluetooth']['maxRetries'] = 1
        conn = ObdConnection(validConfig, obdFactory=disconnectedFactory)

        result = conn.connect()

        assert result is False
        status = conn.getStatus()
        assert status.state == ConnectionState.ERROR
