################################################################################
# File Name: run_tests_shutdown_manager.py
# Purpose/Description: Manual test runner for shutdown_manager module
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-005
# ================================================================================
################################################################################

"""
Manual test runner for the shutdown_manager module.

Run with: python tests/run_tests_shutdown_manager.py
"""

import sys
import os
import signal
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Add project root to path
projectRoot = Path(__file__).parent.parent
sys.path.insert(0, str(projectRoot))
sys.path.insert(0, str(projectRoot / 'src'))

# Test counters
testsPassed = 0
testsFailed = 0


def runTest(testFunc):
    """Run a single test function and track results."""
    global testsPassed, testsFailed
    testName = testFunc.__name__
    try:
        testFunc()
        print(f"  [PASS] {testName}")
        testsPassed += 1
    except AssertionError as e:
        print(f"  [FAIL] {testName}: {e}")
        testsFailed += 1
    except Exception as e:
        print(f"  [ERROR] {testName}: {type(e).__name__}: {e}")
        testsFailed += 1


# ================================================================================
# Test: ShutdownManager Initialization
# ================================================================================

def test_shutdownManager_init_defaultState():
    """
    Given: No parameters
    When: ShutdownManager is created
    Then: Default state is set correctly
    """
    from obd.shutdown_manager import ShutdownManager

    manager = ShutdownManager()

    assert manager._shutdownRequested is False
    assert manager._shutdownComplete is False
    assert manager._database is None
    assert manager._connection is None


def test_shutdownManager_init_withComponents():
    """
    Given: Database and connection components
    When: ShutdownManager is created with components
    Then: Components are stored correctly
    """
    from obd.shutdown_manager import ShutdownManager

    mockDb = MagicMock()
    mockConn = MagicMock()

    manager = ShutdownManager(database=mockDb, connection=mockConn)

    assert manager._database is mockDb
    assert manager._connection is mockConn


def test_shutdownManager_registerComponents_afterInit():
    """
    Given: A ShutdownManager instance
    When: Components are registered after initialization
    Then: Components are stored correctly
    """
    from obd.shutdown_manager import ShutdownManager

    manager = ShutdownManager()
    mockDb = MagicMock()
    mockConn = MagicMock()

    manager.registerDatabase(mockDb)
    manager.registerConnection(mockConn)

    assert manager._database is mockDb
    assert manager._connection is mockConn


# ================================================================================
# Test: Signal Handling
# ================================================================================

def test_shutdownManager_installHandlers_registersSignals():
    """
    Given: A ShutdownManager instance
    When: installHandlers is called
    Then: SIGTERM and SIGINT handlers are registered
    """
    from obd.shutdown_manager import ShutdownManager

    manager = ShutdownManager()

    with patch('signal.signal') as mockSignal:
        manager.installHandlers()

        # Check that both signals were registered
        calls = mockSignal.call_args_list
        signalsRegistered = [c[0][0] for c in calls]

        # On Windows, SIGTERM may not be available, so check for SIGINT at minimum
        assert signal.SIGINT in signalsRegistered


def test_shutdownManager_handleSignal_setsShutdownRequested():
    """
    Given: A ShutdownManager with handlers installed
    When: A signal is received
    Then: Shutdown requested flag is set to True
    """
    from obd.shutdown_manager import ShutdownManager

    manager = ShutdownManager()

    # Call the internal handler directly
    manager._handleSignal(signal.SIGINT, None)

    assert manager._shutdownRequested is True


def test_shutdownManager_handleSignal_secondSignal_forcesExit():
    """
    Given: A ShutdownManager with shutdown already requested
    When: A second signal is received
    Then: System exits immediately
    """
    from obd.shutdown_manager import ShutdownManager

    manager = ShutdownManager()
    manager._shutdownRequested = True

    with patch('sys.exit') as mockExit:
        manager._handleSignal(signal.SIGINT, None)
        mockExit.assert_called_once_with(1)


def test_shutdownManager_isShutdownRequested_returnsState():
    """
    Given: A ShutdownManager instance
    When: isShutdownRequested is called
    Then: Returns the current shutdown requested state
    """
    from obd.shutdown_manager import ShutdownManager

    manager = ShutdownManager()

    assert manager.isShutdownRequested() is False

    manager._shutdownRequested = True

    assert manager.isShutdownRequested() is True


# ================================================================================
# Test: Graceful Shutdown
# ================================================================================

def test_shutdownManager_shutdown_disconnectsConnection():
    """
    Given: A ShutdownManager with a registered connection
    When: shutdown is called
    Then: Connection disconnect is called
    """
    from obd.shutdown_manager import ShutdownManager

    mockConn = MagicMock()
    manager = ShutdownManager(connection=mockConn)

    manager.shutdown()

    mockConn.disconnect.assert_called_once()


def test_shutdownManager_shutdown_handlesConnectionError():
    """
    Given: A ShutdownManager with a connection that errors on disconnect
    When: shutdown is called
    Then: Error is caught and logged, shutdown continues
    """
    from obd.shutdown_manager import ShutdownManager

    mockConn = MagicMock()
    mockConn.disconnect.side_effect = Exception("Disconnect error")
    manager = ShutdownManager(connection=mockConn)

    # Should not raise
    manager.shutdown()

    assert manager._shutdownComplete is True


def test_shutdownManager_shutdown_closesDatabase():
    """
    Given: A ShutdownManager with a registered database
    When: shutdown is called
    Then: Database resources are properly closed
    """
    from obd.shutdown_manager import ShutdownManager

    mockDb = MagicMock()
    manager = ShutdownManager(database=mockDb)

    manager.shutdown()

    # Database should be vacuumed to flush writes
    mockDb.vacuum.assert_called_once()


def test_shutdownManager_shutdown_logsShutdownEvent():
    """
    Given: A ShutdownManager with a database
    When: shutdown is called
    Then: Shutdown event is logged to database with timestamp
    """
    from obd.shutdown_manager import ShutdownManager

    mockDb = MagicMock()
    mockConn = MagicMock()
    mockCursor = MagicMock()
    mockConn.__enter__ = MagicMock(return_value=mockConn)
    mockConn.__exit__ = MagicMock(return_value=False)
    mockConn.cursor.return_value = mockCursor
    mockDb.connect.return_value = mockConn

    manager = ShutdownManager(database=mockDb)

    manager.shutdown()

    # Verify connection_log insert was called
    assert mockCursor.execute.called


def test_shutdownManager_shutdown_setsCompleteFlag():
    """
    Given: A ShutdownManager instance
    When: shutdown is called
    Then: Shutdown complete flag is set to True
    """
    from obd.shutdown_manager import ShutdownManager

    manager = ShutdownManager()

    manager.shutdown()

    assert manager._shutdownComplete is True


def test_shutdownManager_shutdown_idempotent():
    """
    Given: A ShutdownManager that has already completed shutdown
    When: shutdown is called again
    Then: Shutdown is not performed again
    """
    from obd.shutdown_manager import ShutdownManager

    mockConn = MagicMock()
    manager = ShutdownManager(connection=mockConn)

    # First shutdown
    manager.shutdown()
    assert mockConn.disconnect.call_count == 1

    # Second shutdown should be no-op
    manager.shutdown()
    assert mockConn.disconnect.call_count == 1


# ================================================================================
# Test: Callback Support
# ================================================================================

def test_shutdownManager_registerCallback_addsToList():
    """
    Given: A ShutdownManager instance
    When: A callback is registered
    Then: Callback is added to the callbacks list
    """
    from obd.shutdown_manager import ShutdownManager

    manager = ShutdownManager()
    callback = MagicMock()

    manager.registerShutdownCallback(callback)

    assert callback in manager._shutdownCallbacks


def test_shutdownManager_shutdown_executesCallbacks():
    """
    Given: A ShutdownManager with registered callbacks
    When: shutdown is called
    Then: All callbacks are executed
    """
    from obd.shutdown_manager import ShutdownManager

    manager = ShutdownManager()
    callback1 = MagicMock()
    callback2 = MagicMock()

    manager.registerShutdownCallback(callback1)
    manager.registerShutdownCallback(callback2)

    manager.shutdown()

    callback1.assert_called_once()
    callback2.assert_called_once()


def test_shutdownManager_shutdown_callbackOrder():
    """
    Given: A ShutdownManager with callbacks and components
    When: shutdown is called
    Then: Callbacks are executed before closing components
    """
    from obd.shutdown_manager import ShutdownManager

    callOrder = []
    mockConn = MagicMock()
    mockConn.disconnect.side_effect = lambda: callOrder.append('disconnect')

    manager = ShutdownManager(connection=mockConn)

    callback = MagicMock(side_effect=lambda: callOrder.append('callback'))
    manager.registerShutdownCallback(callback)

    manager.shutdown()

    assert callOrder == ['callback', 'disconnect']


def test_shutdownManager_shutdown_callbackError_continues():
    """
    Given: A ShutdownManager with a callback that throws
    When: shutdown is called
    Then: Error is caught and shutdown continues
    """
    from obd.shutdown_manager import ShutdownManager

    manager = ShutdownManager()
    badCallback = MagicMock(side_effect=Exception("Callback error"))
    goodCallback = MagicMock()

    manager.registerShutdownCallback(badCallback)
    manager.registerShutdownCallback(goodCallback)

    # Should not raise
    manager.shutdown()

    # Good callback should still be called
    goodCallback.assert_called_once()
    assert manager._shutdownComplete is True


# ================================================================================
# Test: Pending Writes / Flush
# ================================================================================

def test_shutdownManager_flushPendingWrites_vacuumsDatabase():
    """
    Given: A ShutdownManager with database
    When: _flushPendingWrites is called
    Then: Database is vacuumed to ensure all writes are flushed
    """
    from obd.shutdown_manager import ShutdownManager

    mockDb = MagicMock()
    manager = ShutdownManager(database=mockDb)

    manager._flushPendingWrites()

    mockDb.vacuum.assert_called_once()


def test_shutdownManager_flushPendingWrites_handlesDatabaseError():
    """
    Given: A ShutdownManager with a database that errors on vacuum
    When: _flushPendingWrites is called
    Then: Error is caught and logged
    """
    from obd.shutdown_manager import ShutdownManager

    mockDb = MagicMock()
    mockDb.vacuum.side_effect = Exception("Vacuum error")
    manager = ShutdownManager(database=mockDb)

    # Should not raise
    manager._flushPendingWrites()


# ================================================================================
# Test: Status and Monitoring
# ================================================================================

def test_shutdownManager_getStatus_returnsDict():
    """
    Given: A ShutdownManager instance
    When: getStatus is called
    Then: Returns a dictionary with status information
    """
    from obd.shutdown_manager import ShutdownManager

    manager = ShutdownManager()

    status = manager.getStatus()

    assert isinstance(status, dict)
    assert 'shutdownRequested' in status
    assert 'shutdownComplete' in status
    assert 'hasDatabase' in status
    assert 'hasConnection' in status
    assert 'callbackCount' in status


def test_shutdownManager_getStatus_reflectsState():
    """
    Given: A ShutdownManager with components registered
    When: getStatus is called
    Then: Status reflects the actual state
    """
    from obd.shutdown_manager import ShutdownManager

    mockDb = MagicMock()
    mockConn = MagicMock()
    callback = MagicMock()

    manager = ShutdownManager(database=mockDb, connection=mockConn)
    manager.registerShutdownCallback(callback)
    manager._shutdownRequested = True

    status = manager.getStatus()

    assert status['shutdownRequested'] is True
    assert status['shutdownComplete'] is False
    assert status['hasDatabase'] is True
    assert status['hasConnection'] is True
    assert status['callbackCount'] == 1


# ================================================================================
# Test: Helper Functions
# ================================================================================

def test_createShutdownManager_fromConfig():
    """
    Given: A config dictionary with components
    When: createShutdownManager is called
    Then: Returns a configured ShutdownManager
    """
    from obd.shutdown_manager import createShutdownManager

    mockDb = MagicMock()
    mockConn = MagicMock()

    manager = createShutdownManager(database=mockDb, connection=mockConn)

    assert manager._database is mockDb
    assert manager._connection is mockConn


def test_installGlobalShutdownHandler():
    """
    Given: Components to manage
    When: installGlobalShutdownHandler is called
    Then: Returns a configured ShutdownManager with handlers installed
    """
    from obd.shutdown_manager import installGlobalShutdownHandler

    mockDb = MagicMock()
    mockConn = MagicMock()

    with patch('signal.signal'):
        manager = installGlobalShutdownHandler(database=mockDb, connection=mockConn)

    assert manager._database is mockDb
    assert manager._connection is mockConn


# ================================================================================
# Test: Integration
# ================================================================================

def test_shutdownManager_fullShutdownFlow():
    """
    Given: A fully configured ShutdownManager
    When: Signal triggers shutdown
    Then: All components are properly cleaned up
    """
    from obd.shutdown_manager import ShutdownManager

    mockDb = MagicMock()
    mockConn = MagicMock()

    # Set up database connection mock
    mockDbConn = MagicMock()
    mockDbConn.__enter__ = MagicMock(return_value=mockDbConn)
    mockDbConn.__exit__ = MagicMock(return_value=False)
    mockDbConn.cursor.return_value = MagicMock()
    mockDb.connect.return_value = mockDbConn

    callOrder = []
    callback = MagicMock(side_effect=lambda: callOrder.append('callback'))
    mockConn.disconnect.side_effect = lambda: callOrder.append('disconnect')
    mockDb.vacuum.side_effect = lambda: callOrder.append('vacuum')

    manager = ShutdownManager(database=mockDb, connection=mockConn)
    manager.registerShutdownCallback(callback)

    # Simulate signal
    manager._handleSignal(signal.SIGINT, None)

    # Perform shutdown
    manager.shutdown()

    assert manager._shutdownRequested is True
    assert manager._shutdownComplete is True
    assert 'callback' in callOrder
    assert 'disconnect' in callOrder


# ================================================================================
# Test Runner
# ================================================================================

def main():
    """Run all tests."""
    global testsPassed, testsFailed

    print("\n" + "=" * 60)
    print("Running shutdown_manager Tests")
    print("=" * 60 + "\n")

    # Initialization tests
    print("Test: ShutdownManager Initialization")
    runTest(test_shutdownManager_init_defaultState)
    runTest(test_shutdownManager_init_withComponents)
    runTest(test_shutdownManager_registerComponents_afterInit)

    # Signal handling tests
    print("\nTest: Signal Handling")
    runTest(test_shutdownManager_installHandlers_registersSignals)
    runTest(test_shutdownManager_handleSignal_setsShutdownRequested)
    runTest(test_shutdownManager_handleSignal_secondSignal_forcesExit)
    runTest(test_shutdownManager_isShutdownRequested_returnsState)

    # Graceful shutdown tests
    print("\nTest: Graceful Shutdown")
    runTest(test_shutdownManager_shutdown_disconnectsConnection)
    runTest(test_shutdownManager_shutdown_handlesConnectionError)
    runTest(test_shutdownManager_shutdown_closesDatabase)
    runTest(test_shutdownManager_shutdown_logsShutdownEvent)
    runTest(test_shutdownManager_shutdown_setsCompleteFlag)
    runTest(test_shutdownManager_shutdown_idempotent)

    # Callback tests
    print("\nTest: Callback Support")
    runTest(test_shutdownManager_registerCallback_addsToList)
    runTest(test_shutdownManager_shutdown_executesCallbacks)
    runTest(test_shutdownManager_shutdown_callbackOrder)
    runTest(test_shutdownManager_shutdown_callbackError_continues)

    # Flush tests
    print("\nTest: Pending Writes / Flush")
    runTest(test_shutdownManager_flushPendingWrites_vacuumsDatabase)
    runTest(test_shutdownManager_flushPendingWrites_handlesDatabaseError)

    # Status tests
    print("\nTest: Status and Monitoring")
    runTest(test_shutdownManager_getStatus_returnsDict)
    runTest(test_shutdownManager_getStatus_reflectsState)

    # Helper function tests
    print("\nTest: Helper Functions")
    runTest(test_createShutdownManager_fromConfig)
    runTest(test_installGlobalShutdownHandler)

    # Integration tests
    print("\nTest: Integration")
    runTest(test_shutdownManager_fullShutdownFlow)

    # Summary
    print("\n" + "=" * 60)
    print(f"Results: {testsPassed} passed, {testsFailed} failed")
    print("=" * 60 + "\n")

    return 0 if testsFailed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
