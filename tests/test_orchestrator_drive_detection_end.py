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
from unittest.mock import MagicMock, patch

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
# AC4: Detector onDriveEnd callback: logs drive end with duration, triggers
#      statistics and AI analysis, updates display
# ================================================================================


class TestDriveEndCallback:
    """Tests that drive end callback logs duration, triggers stats, updates display."""

    def test_handleDriveEnd_logsMessage_withDuration(
        self, driveDetectionConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with drive detector wired
        When: Drive end event fires with duration
        Then: INFO log message includes 'Drive ended' and duration
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        session = MagicMock()
        session.duration = 120.5

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._handleDriveEnd(session)

        # Assert
        assert any(
            'Drive ended' in record.message and '120.5' in record.message
            for record in caplog.records
        )

    def test_handleDriveEnd_updatesDisplay_withStoppedStatus(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: Drive end event fires
        Then: Display shows 'stopped' status
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        mockDisplay.showDriveStatus = MagicMock()
        orchestrator._displayManager = mockDisplay

        session = MagicMock()
        session.duration = 60.0

        # Act
        orchestrator._handleDriveEnd(session)

        # Assert
        mockDisplay.showDriveStatus.assert_called_once_with('stopped')

    def test_handleDriveEnd_callsExternalCallback(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with external onDriveEnd callback registered
        When: Drive end event fires
        Then: External callback is called with session
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        externalCallback = MagicMock()
        orchestrator._onDriveEnd = externalCallback

        session = MagicMock()
        session.duration = 300.0

        # Act
        orchestrator._handleDriveEnd(session)

        # Assert
        externalCallback.assert_called_once_with(session)

    def test_driveDetector_triggersStatistics_onDriveEnd(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: DriveDetector initialized with statisticsEngine
        When: Drive ends (RPM drops below threshold for duration)
        Then: statisticsEngine.scheduleAnalysis is called

        Note: Statistics triggering happens inside DriveDetector._endDrive(),
        which calls _triggerAnalysis() -> statisticsEngine.scheduleAnalysis().
        This test verifies the wiring from detector to stats engine.
        """
        # Arrange
        from pi.obd.drive import DriveDetector

        mockEngine = MagicMock()
        mockEngine.scheduleAnalysis = MagicMock()

        config = driveDetectionConfig
        detector = DriveDetector(config, statisticsEngine=mockEngine)
        detector.start()

        # Simulate drive start: RPM above threshold for duration
        from datetime import timedelta
        startTime = datetime(2026, 4, 11, 10, 0, 0)

        with patch('pi.obd.drive.detector.datetime') as mockDatetime:
            mockDatetime.now.return_value = startTime
            mockDatetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
            detector.processValue('RPM', 800)

            # Advance time past driveStartDurationSeconds (1s)
            mockDatetime.now.return_value = startTime + timedelta(seconds=2)
            detector.processValue('RPM', 800)

            # Now simulate drive end: RPM drops below threshold
            endTime = startTime + timedelta(seconds=30)
            mockDatetime.now.return_value = endTime
            detector.processValue('RPM', 0)

            # Advance time past driveEndDurationSeconds (2s)
            endTime2 = endTime + timedelta(seconds=3)
            mockDatetime.now.return_value = endTime2
            detector.processValue('RPM', 0)

        # Assert - statistics engine was called for post-drive analysis
        mockEngine.scheduleAnalysis.assert_called_once()

    def test_driveDetector_triggersAnalysis_whenConfigEnabled(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Config with triggerAfterDrive=True
        When: DriveDetector created from this config
        Then: Detector config has triggerAnalysisAfterDrive=True
        """
        # Arrange
        from pi.obd.drive import DriveDetector

        # Act
        detector = DriveDetector(driveDetectionConfig)

        # Assert
        assert detector.getConfig().triggerAnalysisAfterDrive is True

    def test_handleDriveEnd_displayError_doesNotCrash(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager that raises
        When: Drive end event fires
        Then: Display error caught, callback still fires
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockDisplay = MagicMock()
        mockDisplay.showDriveStatus.side_effect = RuntimeError("display error")
        orchestrator._displayManager = mockDisplay

        externalCallback = MagicMock()
        orchestrator._onDriveEnd = externalCallback

        session = MagicMock()
        session.duration = 45.0

        # Act - should not raise
        orchestrator._handleDriveEnd(session)

        # Assert
        externalCallback.assert_called_once_with(session)
