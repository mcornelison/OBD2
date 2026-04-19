################################################################################
# File Name: test_orchestrator_loop.py
# Purpose/Description: Tests for orchestrator main application loop (US-OSC-005)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-005
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator main application loop.

Verifies that the orchestrator's runLoop():
- Runs until shutdown signal is received
- Handles component callbacks: drive start/end, alert, analysis, connection lost
- Performs health checks at configurable interval
- Logs connection status, data rate, and error count during health check
- Catches and logs unexpected exceptions without crashing
- Is memory-efficient (no unbounded growth)
- Integrates with runWorkflow() in main.py

Usage:
    pytest tests/test_orchestrator_loop.py -v
"""

import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getLoopTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create minimal test configuration for loop tests.

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
                'name': 'Loop Test',
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
                'pollingIntervalMs': 100,
                'parameters': [
                    {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'SPEED', 'logData': True, 'displayOnDashboard': True},
                ]
            },
            'analysis': {
                'triggerAfterDrive': True,
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 1,
                'driveEndRpmThreshold': 100,
                'driveEndDurationSeconds': 1,
                'calculateStatistics': ['max', 'min', 'avg']
            },
            'profiles': {
                'activeProfile': 'test',
                'availableProfiles': [
                    {
                        'id': 'test',
                        'name': 'Test Profile',
                        'description': 'Profile for loop tests',
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
                'cooldownSeconds': 1,
                'visualAlerts': False,
                'audioAlerts': False,
                'logAlerts': True
            },
            'monitoring': {
                'healthCheckIntervalSeconds': 0.5,
                'dataRateLogIntervalSeconds': 1.0
            },
            'shutdown': {
                'componentTimeout': 2
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
    """Create a temporary database file for testing."""
    fd, dbPath = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield dbPath
    try:
        os.unlink(dbPath)
    except OSError:
        pass


@pytest.fixture
def loopConfig(tempDb: str) -> dict[str, Any]:
    """Create loop test configuration with temp database."""
    return getLoopTestConfig(tempDb)


# ================================================================================
# AC3: Loop handles component callbacks
# ================================================================================


@pytest.mark.integration
class TestComponentCallbacks:
    """Verify callbacks are wired up for drive, alert, analysis, connection."""

    def test_setupComponentCallbacks_wiresDriveDetector(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with a mock drive detector
        When: _setupComponentCallbacks() is called
        Then: Drive detector has registerCallbacks called
        """
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        orchestrator._setupComponentCallbacks()

        mockDetector.registerCallbacks.assert_called_once()
        callKwargs = mockDetector.registerCallbacks.call_args[1]
        assert 'onDriveStart' in callKwargs
        assert 'onDriveEnd' in callKwargs

    def test_setupComponentCallbacks_wiresAlertManager(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with a mock alert manager
        When: _setupComponentCallbacks() is called
        Then: Alert manager has onAlert registered
        """
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager

        orchestrator._setupComponentCallbacks()

        mockAlertManager.onAlert.assert_called_once()

    def test_setupComponentCallbacks_wiresStatisticsEngine(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with a mock statistics engine
        When: _setupComponentCallbacks() is called
        Then: Statistics engine has registerCallbacks called
        """
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockStats = MagicMock()
        orchestrator._statisticsEngine = mockStats

        orchestrator._setupComponentCallbacks()

        mockStats.registerCallbacks.assert_called_once()
        callKwargs = mockStats.registerCallbacks.call_args[1]
        assert 'onAnalysisComplete' in callKwargs

    def test_setupComponentCallbacks_wiresDataLogger(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with a mock data logger
        When: _setupComponentCallbacks() is called
        Then: Data logger has registerCallbacks called with onReading and onError
        """
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockLogger = MagicMock()
        orchestrator._dataLogger = mockLogger

        orchestrator._setupComponentCallbacks()

        mockLogger.registerCallbacks.assert_called_once()
        callKwargs = mockLogger.registerCallbacks.call_args[1]
        assert 'onReading' in callKwargs
        assert 'onError' in callKwargs

    def test_handleConnectionLost_callbackInvoked(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with connection lost callback registered
        When: Connection state changes from connected to disconnected
        Then: _handleConnectionLost is called and updates health stats
        """
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )

        orchestrator._handleConnectionLost()

        assert orchestrator._healthCheckStats.connectionStatus == "reconnecting"
        assert orchestrator._healthCheckStats.connectionConnected is False

    def test_handleDriveStart_incrementsDrivesDetected(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with health check stats
        When: _handleDriveStart called
        Then: drivesDetected counter incremented
        """
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockSession = MagicMock()
        initialDrives = orchestrator._healthCheckStats.drivesDetected

        orchestrator._handleDriveStart(mockSession)

        assert orchestrator._healthCheckStats.drivesDetected == initialDrives + 1

    def test_handleAlert_incrementsAlertsTriggered(
        self, loopConfig: dict[str, Any]
    ) -> None:
        """
        Given: Orchestrator with health check stats
        When: _handleAlert called
        Then: alertsTriggered counter incremented
        """
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=loopConfig, simulate=True
        )
        mockAlert = MagicMock()
        mockAlert.priority = 'warning'
        mockAlert.parameterName = 'RPM'
        mockAlert.value = 7000
        mockAlert.threshold = 6000
        mockAlert.message = 'RPM exceeded redline'
        initialAlerts = orchestrator._healthCheckStats.alertsTriggered

        orchestrator._handleAlert(mockAlert)

        assert orchestrator._healthCheckStats.alertsTriggered == initialAlerts + 1
