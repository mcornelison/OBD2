#!/usr/bin/env python3
################################################################################
# File Name: run_tests_obd_connection.py
# Purpose/Description: Manual test runner for OBD connection tests
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""
Manual test runner for OBD connection module tests.

Runs tests without requiring pytest installed.
Useful for environments where pytest is not available.

Usage:
    python tests/run_tests_obd_connection.py
"""

import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, patch

# Add src to path
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
    EVENT_TYPE_CONNECT_ATTEMPT,
    EVENT_TYPE_CONNECT_SUCCESS,
    EVENT_TYPE_CONNECT_FAILURE,
    EVENT_TYPE_DISCONNECT,
)

from obd.database import ObdDatabase

import tempfile
import os


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
# ConnectionStatus Tests
# ================================================================================

def testConnectionStatusDefaults():
    """Test ConnectionStatus defaults."""
    status = ConnectionStatus()
    assert status.state == ConnectionState.DISCONNECTED
    assert status.macAddress is None
    assert status.connected is False
    assert status.retryCount == 0


def testConnectionStatusToDict():
    """Test ConnectionStatus.toDict()."""
    now = datetime.now()
    status = ConnectionStatus(
        state=ConnectionState.CONNECTED,
        macAddress='00:11:22:33:44:55',
        connected=True,
        lastConnectTime=now
    )
    result = status.toDict()
    assert result['state'] == 'connected'
    assert result['macAddress'] == '00:11:22:33:44:55'
    assert result['connected'] is True


# ================================================================================
# Exception Tests
# ================================================================================

def testObdConnectionErrorMessage():
    """Test ObdConnectionError stores message."""
    error = ObdConnectionError("Test error")
    assert str(error) == "Test error"
    assert error.message == "Test error"


def testObdConnectionErrorDetails():
    """Test ObdConnectionError stores details."""
    error = ObdConnectionError("Test", details={'key': 'value'})
    assert error.details == {'key': 'value'}


def testObdNotAvailableInheritance():
    """Test ObdNotAvailableError inheritance."""
    error = ObdNotAvailableError("Not available")
    assert isinstance(error, ObdConnectionError)


# ================================================================================
# ObdConnection Init Tests
# ================================================================================

def testObdConnectionInitExtractsConfig():
    """Test ObdConnection extracts bluetooth settings."""
    config = {
        'bluetooth': {
            'macAddress': '00:11:22:33:44:55',
            'retryDelays': [1, 2, 4],
            'maxRetries': 3,
            'connectionTimeoutSeconds': 60
        }
    }
    mockFactory = lambda mac, timeout: MagicMock(is_connected=lambda: True)
    conn = ObdConnection(config, obdFactory=mockFactory)

    assert conn.macAddress == '00:11:22:33:44:55'
    assert conn.retryDelays == [1, 2, 4]
    assert conn.maxRetries == 3
    assert conn.connectionTimeout == 60


def testObdConnectionInitUsesDefaults():
    """Test ObdConnection uses defaults when config is minimal."""
    mockFactory = lambda mac, timeout: MagicMock(is_connected=lambda: True)
    conn = ObdConnection({}, obdFactory=mockFactory)

    assert conn.macAddress == ''
    assert conn.retryDelays == DEFAULT_RETRY_DELAYS


def testObdConnectionInitialStatus():
    """Test ObdConnection initial status."""
    config = {'bluetooth': {'macAddress': 'AA:BB:CC:DD:EE:FF'}}
    mockFactory = lambda mac, timeout: MagicMock(is_connected=lambda: True)
    conn = ObdConnection(config, obdFactory=mockFactory)
    status = conn.getStatus()

    assert status.state == ConnectionState.DISCONNECTED
    assert status.macAddress == 'AA:BB:CC:DD:EE:FF'


# ================================================================================
# Connect Tests
# ================================================================================

def testConnectSuccess():
    """Test successful connection."""
    config = {'bluetooth': {'macAddress': '00:11:22:33:44:55'}}
    mockObd = MagicMock()
    mockObd.is_connected.return_value = True
    mockFactory = lambda mac, timeout: mockObd

    conn = ObdConnection(config, obdFactory=mockFactory)
    result = conn.connect()

    assert result is True
    assert conn.getStatus().state == ConnectionState.CONNECTED
    assert conn.getStatus().totalConnections == 1


def testConnectSetsLastConnectTime():
    """Test connection sets lastConnectTime."""
    config = {'bluetooth': {}}
    mockObd = MagicMock()
    mockObd.is_connected.return_value = True
    mockFactory = lambda mac, timeout: mockObd

    conn = ObdConnection(config, obdFactory=mockFactory)
    conn.connect()

    status = conn.getStatus()
    assert status.lastConnectTime is not None
    assert isinstance(status.lastConnectTime, datetime)


def testConnectFailureAfterRetries():
    """Test connection failure after all retries."""
    config = {
        'bluetooth': {
            'retryDelays': [0.01, 0.01],
            'maxRetries': 2
        }
    }
    failingFactory = lambda mac, timeout: (_ for _ in ()).throw(
        ObdConnectionError("Connection failed")
    )

    conn = ObdConnection(config, obdFactory=failingFactory)
    result = conn.connect()

    assert result is False
    assert conn.getStatus().state == ConnectionState.ERROR
    assert conn.getStatus().lastError is not None


def testConnectIncrementsErrorCount():
    """Test connection failure increments error count."""
    config = {
        'bluetooth': {
            'retryDelays': [0.01],
            'maxRetries': 1
        }
    }

    def failingFactory(mac, timeout):
        raise ObdConnectionError("Fail")

    conn = ObdConnection(config, obdFactory=failingFactory)
    conn.connect()

    # Initial + 1 retry = 2 errors
    assert conn.getStatus().totalErrors == 2


def testConnectWithDatabase():
    """Test connection logs events to database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dbPath = os.path.join(tmpdir, 'test.db')
        db = ObdDatabase(dbPath)
        db.initialize()

        config = {'bluetooth': {'macAddress': 'AA:BB:CC:DD:EE:FF'}}
        mockObd = MagicMock()
        mockObd.is_connected.return_value = True
        mockFactory = lambda mac, timeout: mockObd

        conn = ObdConnection(config, database=db, obdFactory=mockFactory)
        conn.connect()

        # Check logged events
        with db.connect() as dbConn:
            cursor = dbConn.cursor()
            cursor.execute('SELECT event_type, success FROM connection_log ORDER BY id')
            rows = cursor.fetchall()

        assert len(rows) >= 2
        eventTypes = [r['event_type'] for r in rows]
        assert EVENT_TYPE_CONNECT_ATTEMPT in eventTypes
        assert EVENT_TYPE_CONNECT_SUCCESS in eventTypes


# ================================================================================
# Disconnect Tests
# ================================================================================

def testDisconnectClosesConnection():
    """Test disconnect closes OBD connection."""
    config = {'bluetooth': {}}
    mockObd = MagicMock()
    mockObd.is_connected.return_value = True
    mockFactory = lambda mac, timeout: mockObd

    conn = ObdConnection(config, obdFactory=mockFactory)
    conn.connect()
    conn.disconnect()

    mockObd.close.assert_called_once()


def testDisconnectUpdatesStatus():
    """Test disconnect updates status."""
    config = {'bluetooth': {}}
    mockObd = MagicMock()
    mockObd.is_connected.return_value = True
    mockFactory = lambda mac, timeout: mockObd

    conn = ObdConnection(config, obdFactory=mockFactory)
    conn.connect()
    conn.disconnect()

    status = conn.getStatus()
    assert status.state == ConnectionState.DISCONNECTED
    assert status.connected is False


def testDisconnectWhenNotConnected():
    """Test disconnect when not connected doesn't error."""
    config = {'bluetooth': {}}
    mockFactory = lambda mac, timeout: MagicMock(is_connected=lambda: True)
    conn = ObdConnection(config, obdFactory=mockFactory)

    # Should not raise
    conn.disconnect()
    assert conn.getStatus().state == ConnectionState.DISCONNECTED


# ================================================================================
# Reconnect Tests
# ================================================================================

def testReconnectDisconnectsAndConnects():
    """Test reconnect disconnects then connects."""
    config = {'bluetooth': {}}
    mockObd = MagicMock()
    mockObd.is_connected.return_value = True
    mockFactory = lambda mac, timeout: mockObd

    conn = ObdConnection(config, obdFactory=mockFactory)
    conn.connect()
    mockObd.reset_mock()

    result = conn.reconnect()

    assert result is True
    mockObd.close.assert_called_once()


# ================================================================================
# isConnected Tests
# ================================================================================

def testIsConnectedWhenConnected():
    """Test isConnected returns True when connected."""
    config = {'bluetooth': {}}
    mockObd = MagicMock()
    mockObd.is_connected.return_value = True
    mockFactory = lambda mac, timeout: mockObd

    conn = ObdConnection(config, obdFactory=mockFactory)
    conn.connect()

    assert conn.isConnected() is True


def testIsConnectedWhenNotConnected():
    """Test isConnected returns False when not connected."""
    config = {'bluetooth': {}}
    mockFactory = lambda mac, timeout: MagicMock(is_connected=lambda: True)
    conn = ObdConnection(config, obdFactory=mockFactory)

    assert conn.isConnected() is False


# ================================================================================
# Helper Function Tests
# ================================================================================

def testCreateConnectionFromConfig():
    """Test createConnectionFromConfig creates ObdConnection."""
    config = {'bluetooth': {'macAddress': '00:11:22:33:44:55'}}
    conn = createConnectionFromConfig(config)

    assert isinstance(conn, ObdConnection)
    assert conn.macAddress == '00:11:22:33:44:55'


def testIsObdAvailable():
    """Test isObdAvailable returns boolean."""
    result = isObdAvailable()
    assert isinstance(result, bool)


# ================================================================================
# Edge Case Tests
# ================================================================================

def testConnectEmptyMacAddress():
    """Test connect with empty MAC address."""
    config = {'bluetooth': {'macAddress': ''}}
    mockObd = MagicMock()
    mockObd.is_connected.return_value = True
    mockFactory = lambda mac, timeout: mockObd

    conn = ObdConnection(config, obdFactory=mockFactory)
    result = conn.connect()

    assert result is True


def testConnectMaxRetriesZero():
    """Test connect with maxRetries=0 attempts once."""
    callCount = [0]

    def countingFactory(mac, timeout):
        callCount[0] += 1
        raise ObdConnectionError("Fail")

    config = {'bluetooth': {'maxRetries': 0, 'retryDelays': []}}
    conn = ObdConnection(config, obdFactory=countingFactory)
    conn.connect()

    assert callCount[0] == 1


def testMultipleConnectionsCumulative():
    """Test multiple connect/disconnect accumulates totals."""
    config = {'bluetooth': {}}
    mockObd = MagicMock()
    mockObd.is_connected.return_value = True
    mockFactory = lambda mac, timeout: mockObd

    conn = ObdConnection(config, obdFactory=mockFactory)
    conn.connect()
    conn.disconnect()
    conn.connect()
    conn.disconnect()
    conn.connect()

    assert conn.getStatus().totalConnections == 3


# ================================================================================
# Main Test Runner
# ================================================================================

def main():
    """Run all tests."""
    print("=" * 60)
    print("OBD Connection Module Tests")
    print("=" * 60)

    result = TestResult()

    # ConnectionStatus Tests
    print("\nConnectionStatus Tests:")
    runTest("testConnectionStatusDefaults", testConnectionStatusDefaults, result)
    runTest("testConnectionStatusToDict", testConnectionStatusToDict, result)

    # Exception Tests
    print("\nException Tests:")
    runTest("testObdConnectionErrorMessage", testObdConnectionErrorMessage, result)
    runTest("testObdConnectionErrorDetails", testObdConnectionErrorDetails, result)
    runTest("testObdNotAvailableInheritance", testObdNotAvailableInheritance, result)

    # Init Tests
    print("\nObdConnection Init Tests:")
    runTest("testObdConnectionInitExtractsConfig", testObdConnectionInitExtractsConfig, result)
    runTest("testObdConnectionInitUsesDefaults", testObdConnectionInitUsesDefaults, result)
    runTest("testObdConnectionInitialStatus", testObdConnectionInitialStatus, result)

    # Connect Tests
    print("\nConnect Tests:")
    runTest("testConnectSuccess", testConnectSuccess, result)
    runTest("testConnectSetsLastConnectTime", testConnectSetsLastConnectTime, result)
    runTest("testConnectFailureAfterRetries", testConnectFailureAfterRetries, result)
    runTest("testConnectIncrementsErrorCount", testConnectIncrementsErrorCount, result)
    runTest("testConnectWithDatabase", testConnectWithDatabase, result)

    # Disconnect Tests
    print("\nDisconnect Tests:")
    runTest("testDisconnectClosesConnection", testDisconnectClosesConnection, result)
    runTest("testDisconnectUpdatesStatus", testDisconnectUpdatesStatus, result)
    runTest("testDisconnectWhenNotConnected", testDisconnectWhenNotConnected, result)

    # Reconnect Tests
    print("\nReconnect Tests:")
    runTest("testReconnectDisconnectsAndConnects", testReconnectDisconnectsAndConnects, result)

    # isConnected Tests
    print("\nisConnected Tests:")
    runTest("testIsConnectedWhenConnected", testIsConnectedWhenConnected, result)
    runTest("testIsConnectedWhenNotConnected", testIsConnectedWhenNotConnected, result)

    # Helper Function Tests
    print("\nHelper Function Tests:")
    runTest("testCreateConnectionFromConfig", testCreateConnectionFromConfig, result)
    runTest("testIsObdAvailable", testIsObdAvailable, result)

    # Edge Case Tests
    print("\nEdge Case Tests:")
    runTest("testConnectEmptyMacAddress", testConnectEmptyMacAddress, result)
    runTest("testConnectMaxRetriesZero", testConnectMaxRetriesZero, result)
    runTest("testMultipleConnectionsCumulative", testMultipleConnectionsCumulative, result)

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
