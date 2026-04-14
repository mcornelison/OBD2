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
# 2026-04-11    | Ralph Agent  | US-OSC-015: Add connection recovery tests (AC8)
#               |              | and profile switch tests (AC9) — 9 new tests
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
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
import tempfile
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getIntegrationTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for integration tests.

    Args:
        dbPath: Path to temporary database file

    Returns:
        Configuration dictionary for orchestrator
    """
    return {
        'protocolVersion': '1.0.0',
        'schemaVersion': '1.0.0',
        'deviceId': 'test-device',
        'logging': {
            'level': 'DEBUG',
            'maskPII': False
        },
        'pi': {
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
            'profiles': {
                'activeProfile': 'test',
                'availableProfiles': [
                    {
                        'id': 'test',
                        'name': 'Test Profile',
                        'description': 'Profile for integration tests',
                        'pollingIntervalMs': 100
                    }
                ]
            },
            'tieredThresholds': {
                'rpm': {'unit': 'rpm', 'dangerMin': 7000},
                'coolantTemp': {'unit': 'fahrenheit', 'dangerMin': 220},
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
        },
        'server': {
            'ai': {
                'enabled': False
            },
            'database': {},
            'api': {},
        },
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
def integrationConfig(tempDb: str) -> dict[str, Any]:
    """
    Create integration test configuration with temp database.

    Args:
        tempDb: Temporary database path fixture

    Returns:
        Test configuration dictionary
    """
    return getIntegrationTestConfig(tempDb)


# ================================================================================
# Test: Alerts trigger on simulated threshold violations
# ================================================================================


@pytest.mark.integration
class TestAlertTriggersOnThresholdViolation:
    """Tests for alert triggering on threshold violations."""

    def test_orchestrator_routesValuesToAlertManager(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator with alert manager
        When: Sensor value is received
        Then: Value is passed to alert manager for checking
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: Alert callback is triggered
        Then: Alerts triggered counter is incremented
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        self, integrationConfig: dict[str, Any], caplog
    ):
        """
        Given: Running orchestrator
        When: Alert is triggered
        Then: Alert is logged at WARNING level with details
        """
        # Arrange
        import logging

        from pi.obd.orchestrator import ApplicationOrchestrator

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
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert callback registered
        When: Alert is triggered
        Then: External callback is invoked with alert event
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

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


@pytest.mark.integration
class TestErrorHandlingDuringOperation:
    """Tests for error handling during operation."""

    def test_orchestrator_continuesRunning_afterCallbackError(
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator with faulty callback
        When: Callback throws exception
        Then: Orchestrator continues running
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        self, integrationConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: Logging errors occur
        Then: Error count is tracked in health stats
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

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
