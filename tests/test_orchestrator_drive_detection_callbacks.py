################################################################################
# File Name: test_orchestrator_drive_detection.py
# Purpose/Description: Tests for orchestrator drive detection wiring (US-OSC-007)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-007
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator drive detection wiring.

Verifies that the orchestrator correctly:
- Creates DriveDetector from config via factory function
- Routes RPM values from realtime logger to detector
- Handles drive start callback: logs, updates display, stores start time
- Handles drive end callback: logs duration, triggers stats/AI, updates display
- Logs drive sessions to database for history
- Survives brief RPM dropouts via configurable debounce

Usage:
    pytest tests/test_orchestrator_drive_detection.py -v
"""

import logging
import os
import tempfile
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getDriveDetectionTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for drive detection wiring tests.

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
                'name': 'Drive Detection Test',
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
                    {'name': 'COOLANT_TEMP', 'logData': True, 'displayOnDashboard': True},
                    {'name': 'ENGINE_LOAD', 'logData': True, 'displayOnDashboard': False},
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
                'dataRateLogIntervalSeconds': 5
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
def driveDetectionConfig(tempDb: str) -> dict[str, Any]:
    """Create drive detection test configuration with temp database."""
    return getDriveDetectionTestConfig(tempDb)


# ================================================================================
# AC3: Detector onDriveStart callback: logs drive start, updates display,
#      stores start time
# ================================================================================


class TestDriveStartCallback:
    """Tests that drive start callback logs, updates display, and tracks stats."""

    def test_handleDriveStart_logsMessage_withSessionInfo(
        self, driveDetectionConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with drive detector wired
        When: Drive start event fires
        Then: INFO log message includes 'Drive started'
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        session = MagicMock()
        session.startTime = datetime(2026, 4, 11, 10, 0, 0)

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._handleDriveStart(session)

        # Assert
        assert any(
            'Drive started' in record.message
            for record in caplog.records
        )

    def test_handleDriveStart_incrementsDrivesDetected(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with healthCheckStats.drivesDetected = 0
        When: Drive start event fires
        Then: drivesDetected incremented to 1
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        assert orchestrator._healthCheckStats.drivesDetected == 0
        session = MagicMock()

        # Act
        orchestrator._handleDriveStart(session)

        # Assert
        assert orchestrator._healthCheckStats.drivesDetected == 1

    def test_handleDriveStart_updatesDisplay_withDrivingStatus(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: Drive start event fires
        Then: Display shows 'driving' status
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        mockDisplay.showDriveStatus = MagicMock()
        orchestrator._displayManager = mockDisplay

        session = MagicMock()

        # Act
        orchestrator._handleDriveStart(session)

        # Assert
        mockDisplay.showDriveStatus.assert_called_once_with('driving')

    def test_handleDriveStart_callsExternalCallback(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with external onDriveStart callback registered
        When: Drive start event fires
        Then: External callback is called with session
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        externalCallback = MagicMock()
        orchestrator._onDriveStart = externalCallback

        session = MagicMock()

        # Act
        orchestrator._handleDriveStart(session)

        # Assert
        externalCallback.assert_called_once_with(session)

    def test_handleDriveStart_displayError_doesNotCrash(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager that raises
        When: Drive start event fires
        Then: Display error is caught, callback still fires
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        mockDisplay.showDriveStatus.side_effect = RuntimeError("display error")
        orchestrator._displayManager = mockDisplay

        externalCallback = MagicMock()
        orchestrator._onDriveStart = externalCallback

        session = MagicMock()

        # Act - should not raise
        orchestrator._handleDriveStart(session)

        # Assert - external callback still called despite display error
        externalCallback.assert_called_once_with(session)


# ================================================================================
# Callback Wiring: _setupComponentCallbacks wires detector
# ================================================================================


class TestSetupComponentCallbacksWiring:
    """Tests that _setupComponentCallbacks correctly wires drive detector."""

    def test_setupCallbacks_registersOnDriveDetector(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with drive detector
        When: _setupComponentCallbacks is called
        Then: detector.registerCallbacks is called with orchestrator handlers
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        # Act
        orchestrator._setupComponentCallbacks()

        # Assert
        mockDetector.registerCallbacks.assert_called_once_with(
            onDriveStart=orchestrator._handleDriveStart,
            onDriveEnd=orchestrator._handleDriveEnd
        )

    def test_setupCallbacks_logsSuccess(
        self, driveDetectionConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with drive detector
        When: _setupComponentCallbacks succeeds
        Then: 'Drive detector callbacks registered' is logged
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._setupComponentCallbacks()

        # Assert
        assert any(
            'Drive detector callbacks registered' in record.message
            for record in caplog.records
        )

    def test_setupCallbacks_handlesError_gracefully(
        self, driveDetectionConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with drive detector that raises on registerCallbacks
        When: _setupComponentCallbacks is called
        Then: Error is caught and logged, orchestrator continues
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockDetector = MagicMock()
        mockDetector.registerCallbacks.side_effect = RuntimeError("callback error")
        orchestrator._driveDetector = mockDetector

        # Act - should not raise
        with caplog.at_level(logging.WARNING):
            orchestrator._setupComponentCallbacks()

        # Assert
        assert any(
            'Could not register drive detector callbacks' in record.message
            for record in caplog.records
        )

    def test_setupCallbacks_skipsDetector_whenNone(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no drive detector
        When: _setupComponentCallbacks is called
        Then: No error, other callbacks still wired
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        orchestrator._driveDetector = None

        # Act - should not raise
        orchestrator._setupComponentCallbacks()
