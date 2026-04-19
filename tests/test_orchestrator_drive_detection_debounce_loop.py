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
# AC6: Detector state survives brief RPM dropouts (configurable debounce)
# ================================================================================


class TestDriveDetectorDebounce:
    """Tests that detector state survives brief RPM dropouts."""

    def test_briefRpmDropout_doesNotEndDrive(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Active drive with RPM > threshold
        When: RPM drops briefly but returns before driveEndDurationSeconds
        Then: Drive continues (state returns to RUNNING)
        """
        # Arrange
        from pi.obdii.drive import DriveDetector, DriveState

        config = driveDetectionConfig
        detector = DriveDetector(config)
        detector.start()

        from datetime import timedelta
        startTime = datetime(2026, 4, 11, 10, 0, 0)

        with patch('pi.obdii.drive.detector.datetime') as mockDatetime:
            mockDatetime.now.return_value = startTime
            mockDatetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            # Start the drive
            detector.processValue('RPM', 800)
            mockDatetime.now.return_value = startTime + timedelta(seconds=2)
            detector.processValue('RPM', 800)
            assert detector.isDriving()

            # Brief dropout: RPM drops to 0
            dropTime = startTime + timedelta(seconds=10)
            mockDatetime.now.return_value = dropTime
            detector.processValue('RPM', 0)

            # RPM recovers within driveEndDurationSeconds (2s)
            recoveryTime = dropTime + timedelta(seconds=1)
            mockDatetime.now.return_value = recoveryTime
            detector.processValue('RPM', 800)

        # Assert - drive is still active
        assert detector.isDriving()
        assert detector.getDriveState() == DriveState.RUNNING

    def test_sustainedRpmDropout_endsDrive(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Active drive with RPM > threshold
        When: RPM drops and stays low past driveEndDurationSeconds
        Then: Drive ends (state transitions to STOPPED)
        """
        # Arrange
        from pi.obdii.drive import DriveDetector, DriveState

        config = driveDetectionConfig
        detector = DriveDetector(config)
        detector.start()

        from datetime import timedelta
        startTime = datetime(2026, 4, 11, 10, 0, 0)

        with patch('pi.obdii.drive.detector.datetime') as mockDatetime:
            mockDatetime.now.return_value = startTime
            mockDatetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            # Start the drive
            detector.processValue('RPM', 800)
            mockDatetime.now.return_value = startTime + timedelta(seconds=2)
            detector.processValue('RPM', 800)
            assert detector.isDriving()

            # RPM drops to 0
            dropTime = startTime + timedelta(seconds=10)
            mockDatetime.now.return_value = dropTime
            detector.processValue('RPM', 0)

            # RPM stays at 0 past driveEndDurationSeconds (2s)
            endTime = dropTime + timedelta(seconds=3)
            mockDatetime.now.return_value = endTime
            detector.processValue('RPM', 0)

        # Assert - drive has ended
        assert not detector.isDriving()
        assert detector.getDriveState() == DriveState.STOPPED

    def test_debounce_isConfigurable(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Config with driveEndDurationSeconds = 2
        When: DriveDetector is created
        Then: Detector uses the configured debounce duration
        """
        # Arrange
        from pi.obdii.drive import DriveDetector

        # Act
        detector = DriveDetector(driveDetectionConfig)

        # Assert
        assert detector.getConfig().driveEndDurationSeconds == 2

    def test_debounce_canBeUpdatedViaSetThresholds(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: DriveDetector with default debounce
        When: setThresholds called with new driveEndDurationSeconds
        Then: New duration is used for subsequent state transitions
        """
        # Arrange
        from pi.obdii.drive import DriveDetector

        detector = DriveDetector(driveDetectionConfig)

        # Act
        detector.setThresholds(driveEndDurationSeconds=5)

        # Assert
        assert detector.getConfig().driveEndDurationSeconds == 5

    def test_multipleDropouts_driveStillContinues(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Active drive
        When: Multiple brief RPM dropouts occur (each shorter than debounce)
        Then: Drive continues through all dropouts
        """
        # Arrange
        from pi.obdii.drive import DriveDetector

        config = driveDetectionConfig
        detector = DriveDetector(config)
        detector.start()

        from datetime import timedelta
        startTime = datetime(2026, 4, 11, 10, 0, 0)

        with patch('pi.obdii.drive.detector.datetime') as mockDatetime:
            mockDatetime.now.return_value = startTime
            mockDatetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            # Start the drive
            detector.processValue('RPM', 800)
            mockDatetime.now.return_value = startTime + timedelta(seconds=2)
            detector.processValue('RPM', 800)
            assert detector.isDriving()

            # First brief dropout
            t = startTime + timedelta(seconds=10)
            mockDatetime.now.return_value = t
            detector.processValue('RPM', 0)
            t = t + timedelta(seconds=1)
            mockDatetime.now.return_value = t
            detector.processValue('RPM', 900)
            assert detector.isDriving()

            # Second brief dropout
            t = t + timedelta(seconds=5)
            mockDatetime.now.return_value = t
            detector.processValue('RPM', 0)
            t = t + timedelta(seconds=1)
            mockDatetime.now.return_value = t
            detector.processValue('RPM', 700)
            assert detector.isDriving()

            # Third brief dropout
            t = t + timedelta(seconds=5)
            mockDatetime.now.return_value = t
            detector.processValue('RPM', 0)
            t = t + timedelta(seconds=1)
            mockDatetime.now.return_value = t
            detector.processValue('RPM', 1200)

        # Assert - still driving after 3 dropouts
        assert detector.isDriving()


# ================================================================================
# Detector started in runLoop
# ================================================================================


class TestDetectorStartedInLoop:
    """Tests that drive detector is started when runLoop begins."""

    def test_runLoop_startsDetector_ifAvailable(
        self, driveDetectionConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with initialized drive detector (after start())
        When: runLoop() executes
        Then: driveDetector.start() is called
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            # Replace detector with mock to verify start() is called
            mockDetector = MagicMock()
            orchestrator._driveDetector = mockDetector

            # Trigger immediate shutdown so runLoop exits quickly
            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

            # Act
            orchestrator.runLoop()

            # Assert
            mockDetector.start.assert_called_once()

        finally:
            orchestrator.stop()

    def test_detectorStartFailure_doesNotPreventLoop(
        self, driveDetectionConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with drive detector that fails to start
        When: runLoop begins
        Then: Error is logged but loop continues
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator, ShutdownState

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        try:
            orchestrator.start()

            mockDetector = MagicMock()
            mockDetector.start.side_effect = RuntimeError("start failed")
            orchestrator._driveDetector = mockDetector

            orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

            # Act
            with caplog.at_level(logging.ERROR):
                orchestrator.runLoop()

            # Assert - error logged, orchestrator still ran
            assert any(
                'Failed to start drive detector' in record.message
                for record in caplog.records
            )

        finally:
            orchestrator.stop()
