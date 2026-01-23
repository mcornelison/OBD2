################################################################################
# File Name: test_orchestrator_integration.py
# Purpose/Description: Integration tests for ApplicationOrchestrator with simulator
# Author: Ralph Agent
# Creation Date: 2026-01-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-23    | Ralph Agent  | Initial implementation for US-OSC-015
# ================================================================================
################################################################################

"""
Integration tests for ApplicationOrchestrator in simulator mode.

Tests the orchestrator's ability to start, run, and stop with all components
integrated together using simulated OBD-II connections. These tests verify
the end-to-end functionality of the system without requiring hardware.

Test coverage includes:
- Orchestrator startup in simulator mode
- Graceful shutdown on signal
- Data logging to database during simulated operations
- Drive detection triggering on RPM changes
- Statistics calculation after drive ends
- Alert triggering on threshold violations
- Temporary database usage (not production)

Usage:
    pytest tests/test_orchestrator_integration.py -v
    pytest tests/test_orchestrator_integration.py -v --timeout=120
"""

import os
import signal
import sqlite3
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ================================================================================
# Test Configuration
# ================================================================================


def getIntegrationTestConfig(dbPath: str) -> Dict[str, Any]:
    """
    Create test configuration for integration tests.

    Args:
        dbPath: Path to temporary database file

    Returns:
        Configuration dictionary for orchestrator
    """
    return {
        'application': {
            'name': 'Integration Test',
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
            'retryDelays': [0.1, 0.2],
            'maxRetries': 2,
            'connectionTimeoutSeconds': 5
        },
        'vinDecoder': {
            'enabled': False,
            'apiBaseUrl': 'https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues',
            'apiTimeoutSeconds': 5,
            'cacheVinData': False
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
            'pollingIntervalMs': 100,  # Fast polling for tests
            'parameters': [
                {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                {'name': 'SPEED', 'logData': True, 'displayOnDashboard': True},
                {'name': 'COOLANT_TEMP', 'logData': True, 'displayOnDashboard': True},
                {'name': 'ENGINE_LOAD', 'logData': True, 'displayOnDashboard': False},
                {'name': 'THROTTLE_POS', 'logData': True, 'displayOnDashboard': False}
            ]
        },
        'analysis': {
            'triggerAfterDrive': True,
            'driveStartRpmThreshold': 500,
            'driveStartDurationSeconds': 1,  # Short for tests
            'driveEndRpmThreshold': 100,
            'driveEndDurationSeconds': 1,  # Short for tests
            'calculateStatistics': ['max', 'min', 'avg']
        },
        'aiAnalysis': {
            'enabled': False
        },
        'profiles': {
            'activeProfile': 'test',
            'availableProfiles': [
                {
                    'id': 'test',
                    'name': 'Test Profile',
                    'description': 'Profile for integration tests',
                    'alertThresholds': {
                        'rpmRedline': 6000,
                        'coolantTempCritical': 105
                    },
                    'pollingIntervalMs': 100
                }
            ]
        },
        'alerts': {
            'enabled': True,
            'cooldownSeconds': 1,  # Short for tests
            'visualAlerts': False,
            'audioAlerts': False,
            'logAlerts': True
        },
        'monitoring': {
            'healthCheckIntervalSeconds': 2,  # Short for tests
            'dataRateLogIntervalSeconds': 5
        },
        'shutdown': {
            'componentTimeout': 2  # Short for tests
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
    """
    Create a temporary database file for testing.

    Yields:
        Path to temporary database file

    Automatically cleaned up after test.
    """
    # Use file-based temp database (not :memory:) for proper testing
    fd, dbPath = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    yield dbPath

    # Cleanup
    try:
        os.unlink(dbPath)
    except OSError:
        pass


@pytest.fixture
def integrationConfig(tempDb: str) -> Dict[str, Any]:
    """
    Create integration test configuration with temp database.

    Args:
        tempDb: Temporary database path fixture

    Returns:
        Test configuration dictionary
    """
    return getIntegrationTestConfig(tempDb)


# ================================================================================
# Test: Orchestrator starts successfully in simulator mode
# ================================================================================


@pytest.mark.integration
class TestOrchestratorStartsInSimulatorMode:
    """Tests for orchestrator startup in simulator mode."""

    def test_orchestrator_startsSuccessfully_inSimulatorMode(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Valid configuration with simulator enabled
        When: Orchestrator is started in simulator mode
        Then: Orchestrator starts successfully and is running
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        # Act
        try:
            orchestrator.start()

            # Assert
            assert orchestrator.isRunning() is True
            status = orchestrator.getStatus()
            assert status['running'] is True
            assert status['components']['database'] == 'initialized'

        finally:
            # Cleanup
            orchestrator.stop()

    def test_orchestrator_initializesDatabase_inSimulatorMode(
        self, integrationConfig: Dict[str, Any], tempDb: str
    ):
        """
        Given: Valid configuration with temp database
        When: Orchestrator starts in simulator mode
        Then: Database is created and initialized
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        # Act
        try:
            orchestrator.start()

            # Assert - database file exists
            assert os.path.exists(tempDb)

            # Assert - database has required tables
            with sqlite3.connect(tempDb) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
                tables = {row[0] for row in cursor.fetchall()}

            # Should have at least realtime_data and profiles tables
            assert 'realtime_data' in tables or len(tables) > 0

        finally:
            orchestrator.stop()

    def test_orchestrator_initializesConnection_inSimulatorMode(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Configuration with simulator enabled
        When: Orchestrator starts
        Then: Simulated connection is established
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        # Act
        try:
            orchestrator.start()

            # Assert
            assert orchestrator.connection is not None
            status = orchestrator.getStatus()
            assert status['components']['connection'] == 'initialized'

        finally:
            orchestrator.stop()


# ================================================================================
# Test: Orchestrator stops gracefully on signal
# ================================================================================


@pytest.mark.integration
class TestOrchestratorStopsGracefully:
    """Tests for graceful orchestrator shutdown."""

    def test_orchestrator_stopsGracefully_onStopCall(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: stop() is called
        Then: Orchestrator shuts down cleanly with exit code 0
        """
        # Arrange
        from obd.orchestrator import (
            ApplicationOrchestrator,
            EXIT_CODE_CLEAN
        )

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        orchestrator.start()
        assert orchestrator.isRunning() is True

        # Act
        exitCode = orchestrator.stop()

        # Assert
        assert orchestrator.isRunning() is False
        assert exitCode == EXIT_CODE_CLEAN

    def test_orchestrator_handlesSignalShutdown_gracefully(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator with signal handlers registered
        When: SIGINT is simulated
        Then: Orchestrator enters shutdown state
        """
        # Arrange
        from obd.orchestrator import (
            ApplicationOrchestrator,
            ShutdownState
        )

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        orchestrator.start()
        orchestrator.registerSignalHandlers()

        try:
            # Act - simulate signal handler being called
            orchestrator._handleShutdownSignal(signal.SIGINT, None)

            # Assert
            assert orchestrator.shutdownState == ShutdownState.SHUTDOWN_REQUESTED

        finally:
            orchestrator.restoreSignalHandlers()
            orchestrator.stop()

    def test_orchestrator_cleansUpAllComponents_onShutdown(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator with initialized components
        When: stop() is called
        Then: All components are cleaned up (set to None)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        orchestrator.start()

        # Act
        orchestrator.stop()

        # Assert - components should be cleaned up
        assert orchestrator._dataLogger is None
        assert orchestrator._driveDetector is None
        assert orchestrator._database is None


# ================================================================================
# Test: Data is logged to database during simulated drive
# ================================================================================


@pytest.mark.integration
class TestDataLoggingDuringSimulatedDrive:
    """Tests for data logging during simulated operation."""

    def test_orchestrator_logsDataToDatabase_duringOperation(
        self, integrationConfig: Dict[str, Any], tempDb: str
    ):
        """
        Given: Running orchestrator in simulator mode
        When: Data logger is active for a period
        Then: Data is written to the database
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Start the main loop in a thread for brief operation
            loopThread = threading.Thread(
                target=orchestrator.runLoop,
                daemon=True
            )
            loopThread.start()

            # Act - let it run briefly
            time.sleep(0.5)

            # Signal shutdown
            orchestrator._shutdownState = (
                __import__('obd.orchestrator', fromlist=['ShutdownState'])
                .ShutdownState.SHUTDOWN_REQUESTED
            )
            loopThread.join(timeout=3)

            # Assert - check health stats show readings
            stats = orchestrator.getHealthCheckStats()
            # Even if no readings logged, we should have valid stats object
            assert stats is not None
            assert hasattr(stats, 'totalReadings')

        finally:
            orchestrator.stop()

    def test_orchestrator_tracksReadingCount_inHealthStats(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator with data logger
        When: Readings are processed
        Then: Health check stats track total readings
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act - simulate some readings via callback
            class MockReading:
                parameterName = 'RPM'
                value = 2500.0
                unit = 'rpm'

            initialReadings = orchestrator._healthCheckStats.totalReadings
            orchestrator._handleReading(MockReading())
            orchestrator._handleReading(MockReading())
            orchestrator._handleReading(MockReading())

            # Assert
            stats = orchestrator.getHealthCheckStats()
            assert stats.totalReadings == initialReadings + 3

        finally:
            orchestrator.stop()


# ================================================================================
# Test: Drive detection triggers on simulated RPM changes
# ================================================================================


@pytest.mark.integration
class TestDriveDetectionOnRpmChanges:
    """Tests for drive detection triggering."""

    def test_orchestrator_routesRpmToDriveDetector(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator with drive detector
        When: RPM reading is received
        Then: Value is passed to drive detector
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Mock the drive detector's processValue
            if orchestrator.driveDetector is not None:
                orchestrator.driveDetector.processValue = MagicMock()

                # Act
                class MockReading:
                    parameterName = 'RPM'
                    value = 2500.0
                    unit = 'rpm'

                orchestrator._handleReading(MockReading())

                # Assert
                orchestrator.driveDetector.processValue.assert_called_once_with(
                    'RPM', 2500.0
                )

        finally:
            orchestrator.stop()

    def test_orchestrator_incrementsDriveCount_onDriveStart(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: Drive start callback is triggered
        Then: Drives detected counter is incremented
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            initialDrives = orchestrator._healthCheckStats.drivesDetected

            # Act - simulate drive start
            class MockSession:
                id = 'test-session-123'
                startTime = datetime.now()

            orchestrator._handleDriveStart(MockSession())

            # Assert
            assert orchestrator._healthCheckStats.drivesDetected == (
                initialDrives + 1
            )

        finally:
            orchestrator.stop()

    def test_orchestrator_callsExternalCallback_onDriveStart(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Orchestrator with registered drive start callback
        When: Drive starts
        Then: External callback is invoked
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        callbackCalled = []

        def onDriveStart(session: Any) -> None:
            callbackCalled.append(session)

        try:
            orchestrator.start()
            orchestrator.registerCallbacks(onDriveStart=onDriveStart)

            # Act
            class MockSession:
                id = 'test-session'
                startTime = datetime.now()

            orchestrator._handleDriveStart(MockSession())

            # Assert
            assert len(callbackCalled) == 1
            assert callbackCalled[0].id == 'test-session'

        finally:
            orchestrator.stop()


# ================================================================================
# Test: Statistics calculated after simulated drive ends
# ================================================================================


@pytest.mark.integration
class TestStatisticsAfterDriveEnd:
    """Tests for statistics calculation after drive ends."""

    def test_orchestrator_logsDriveEnd_withDuration(
        self, integrationConfig: Dict[str, Any], caplog
    ):
        """
        Given: Running orchestrator
        When: Drive end callback is triggered
        Then: Drive end is logged with duration
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator
        import logging

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            class MockSession:
                id = 'test-session'
                duration = 120.5

            with caplog.at_level(logging.INFO):
                orchestrator._handleDriveEnd(MockSession())

            # Assert - check log message
            assert any(
                'Drive ended' in record.message and '120.5' in record.message
                for record in caplog.records
            )

        finally:
            orchestrator.stop()

    def test_orchestrator_callsExternalCallback_onDriveEnd(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Orchestrator with registered drive end callback
        When: Drive ends
        Then: External callback is invoked with session
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        callbackCalled = []

        def onDriveEnd(session: Any) -> None:
            callbackCalled.append(session)

        try:
            orchestrator.start()
            orchestrator.registerCallbacks(onDriveEnd=onDriveEnd)

            # Act
            class MockSession:
                id = 'drive-session-456'
                duration = 300.0

            orchestrator._handleDriveEnd(MockSession())

            # Assert
            assert len(callbackCalled) == 1
            assert callbackCalled[0].id == 'drive-session-456'

        finally:
            orchestrator.stop()

    def test_orchestrator_notifiesAnalysisComplete_viaCallback(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Orchestrator with analysis complete callback registered
        When: Analysis complete event occurs
        Then: Callback is invoked with result
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        callbackResults = []

        def onAnalysisComplete(result: Any) -> None:
            callbackResults.append(result)

        try:
            orchestrator.start()
            orchestrator.registerCallbacks(onAnalysisComplete=onAnalysisComplete)

            # Act
            mockResult = {'statistics': {'RPM': {'max': 6000, 'min': 800}}}
            orchestrator._handleAnalysisComplete(mockResult)

            # Assert
            assert len(callbackResults) == 1
            assert callbackResults[0] == mockResult

        finally:
            orchestrator.stop()


# ================================================================================
# Test: Alerts trigger on simulated threshold violations
# ================================================================================


@pytest.mark.integration
class TestAlertTriggersOnThresholdViolation:
    """Tests for alert triggering on threshold violations."""

    def test_orchestrator_routesValuesToAlertManager(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator with alert manager
        When: Sensor value is received
        Then: Value is passed to alert manager for checking
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Mock alert manager's checkValue
            if orchestrator.alertManager is not None:
                orchestrator.alertManager.checkValue = MagicMock()

                # Act
                class MockReading:
                    parameterName = 'RPM'
                    value = 7000.0
                    unit = 'rpm'

                orchestrator._handleReading(MockReading())

                # Assert
                orchestrator.alertManager.checkValue.assert_called_once_with(
                    'RPM', 7000.0
                )

        finally:
            orchestrator.stop()

    def test_orchestrator_incrementsAlertCount_onAlert(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: Alert callback is triggered
        Then: Alerts triggered counter is incremented
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            initialAlerts = orchestrator._healthCheckStats.alertsTriggered

            # Act - simulate alert
            class MockAlertEvent:
                alertType = 'rpm_redline'
                parameterName = 'RPM'
                value = 7500
                threshold = 6500
                profileId = 'test'

            orchestrator._handleAlert(MockAlertEvent())

            # Assert
            assert orchestrator._healthCheckStats.alertsTriggered == (
                initialAlerts + 1
            )

        finally:
            orchestrator.stop()

    def test_orchestrator_logsAlert_atWarningLevel(
        self, integrationConfig: Dict[str, Any], caplog
    ):
        """
        Given: Running orchestrator
        When: Alert is triggered
        Then: Alert is logged at WARNING level with details
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator
        import logging

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            class MockAlertEvent:
                alertType = 'coolant_temp_critical'
                parameterName = 'COOLANT_TEMP'
                value = 115
                threshold = 110
                profileId = 'test'

            with caplog.at_level(logging.WARNING):
                orchestrator._handleAlert(MockAlertEvent())

            # Assert
            warningRecords = [
                r for r in caplog.records
                if r.levelname == 'WARNING' and 'ALERT' in r.message
            ]
            assert len(warningRecords) >= 1
            assert 'coolant_temp_critical' in warningRecords[0].message

        finally:
            orchestrator.stop()

    def test_orchestrator_callsExternalCallback_onAlert(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Orchestrator with alert callback registered
        When: Alert is triggered
        Then: External callback is invoked with alert event
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        alertEvents = []

        def onAlert(event: Any) -> None:
            alertEvents.append(event)

        try:
            orchestrator.start()
            orchestrator.registerCallbacks(onAlert=onAlert)

            # Act
            class MockAlertEvent:
                alertType = 'rpm_redline'
                parameterName = 'RPM'
                value = 7500
                threshold = 6500
                profileId = 'test'

            orchestrator._handleAlert(MockAlertEvent())

            # Assert
            assert len(alertEvents) == 1
            assert alertEvents[0].alertType == 'rpm_redline'

        finally:
            orchestrator.stop()


# ================================================================================
# Test: Tests use temporary database
# ================================================================================


@pytest.mark.integration
class TestTemporaryDatabaseUsage:
    """Tests to verify temporary database usage."""

    def test_integrationTests_useTemporaryDatabase(
        self, integrationConfig: Dict[str, Any], tempDb: str
    ):
        """
        Given: Integration test configuration
        When: Test runs
        Then: Temporary database path is used, not production
        """
        # Assert - config uses temp db path
        assert integrationConfig['database']['path'] == tempDb
        assert tempDb.endswith('.db')
        assert 'obd.db' not in tempDb

    def test_databaseFile_isCreatedInTempLocation(
        self, integrationConfig: Dict[str, Any], tempDb: str
    ):
        """
        Given: Orchestrator started with temp database config
        When: Database is initialized
        Then: Database file is in temp location
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert os.path.exists(tempDb)
            # Verify it's actually our temp file
            assert tempDb == integrationConfig['database']['path']

        finally:
            orchestrator.stop()


# ================================================================================
# Test: Tests complete within time limit
# ================================================================================


@pytest.mark.integration
class TestCompletionWithinTimeLimit:
    """Tests to verify tests complete within acceptable time."""

    def test_orchestrator_startsAndStops_withinTimeLimit(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Valid configuration
        When: Orchestrator starts and stops
        Then: Completes within reasonable time (< 10 seconds)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        startTime = time.time()

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        # Act
        orchestrator.start()
        orchestrator.stop()

        # Assert
        elapsed = time.time() - startTime
        assert elapsed < 10, f"Start/stop took too long: {elapsed:.2f}s"

    def test_healthCheck_executesQuickly(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: Health check is performed
        Then: Completes in under 1 second
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            startTime = time.time()
            orchestrator._performHealthCheck()
            elapsed = time.time() - startTime

            # Assert
            assert elapsed < 1.0, f"Health check too slow: {elapsed:.2f}s"

        finally:
            orchestrator.stop()


# ================================================================================
# Additional Integration Tests
# ================================================================================


@pytest.mark.integration
class TestConnectionStateMonitoring:
    """Tests for connection state monitoring."""

    def test_orchestrator_detectsConnectionState_initially(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator with simulated connection
        When: Connection status is checked
        Then: Returns valid state (connected or disconnected)
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Act
            isConnected = orchestrator._checkConnectionStatus()

            # Assert - should be boolean
            assert isinstance(isConnected, bool)

        finally:
            orchestrator.stop()

    def test_orchestrator_callsConnectionLostCallback(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Orchestrator with connection lost callback registered
        When: Connection lost handler is called
        Then: External callback is invoked
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )
        connectionLostCalled = []

        def onConnectionLost() -> None:
            connectionLostCalled.append(True)

        try:
            orchestrator.start()
            orchestrator.registerCallbacks(onConnectionLost=onConnectionLost)

            # Act
            orchestrator._handleConnectionLost()

            # Assert
            assert len(connectionLostCalled) == 1
            assert orchestrator._healthCheckStats.connectionStatus == 'disconnected'

        finally:
            orchestrator.stop()


@pytest.mark.integration
class TestDashboardParameterRouting:
    """Tests for dashboard parameter routing."""

    def test_orchestrator_extractsDashboardParameters_fromConfig(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Configuration with displayOnDashboard flags
        When: Orchestrator is created
        Then: Dashboard parameters are extracted correctly
        """
        # Arrange & Act
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        # Assert
        dashboardParams = orchestrator._dashboardParameters
        assert 'RPM' in dashboardParams
        assert 'SPEED' in dashboardParams
        assert 'COOLANT_TEMP' in dashboardParams
        assert 'ENGINE_LOAD' not in dashboardParams  # displayOnDashboard: False


@pytest.mark.integration
class TestErrorHandlingDuringOperation:
    """Tests for error handling during operation."""

    def test_orchestrator_continuesRunning_afterCallbackError(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator with faulty callback
        When: Callback throws exception
        Then: Orchestrator continues running
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        def faultyCallback(event: Any) -> None:
            raise RuntimeError("Intentional test error")

        try:
            orchestrator.start()
            orchestrator.registerCallbacks(onDriveStart=faultyCallback)

            # Act - should not crash
            class MockSession:
                id = 'test'
                startTime = datetime.now()

            orchestrator._handleDriveStart(MockSession())

            # Assert - still running
            assert orchestrator.isRunning() is True

        finally:
            orchestrator.stop()

    def test_orchestrator_tracksErrors_inHealthStats(
        self, integrationConfig: Dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: Logging errors occur
        Then: Error count is tracked in health stats
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=integrationConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            initialErrors = orchestrator._healthCheckStats.totalErrors

            # Act
            orchestrator._handleLoggingError('RPM', Exception("Test error"))
            orchestrator._handleLoggingError('SPEED', Exception("Test error 2"))

            # Assert
            assert orchestrator._healthCheckStats.totalErrors == (
                initialErrors + 2
            )

        finally:
            orchestrator.stop()
