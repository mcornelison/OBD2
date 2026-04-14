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
# AC1: DriveDetector created from config in orchestrator
# ================================================================================


class TestDriveDetectorCreatedFromConfig:
    """Tests that DriveDetector is created from config in orchestrator."""

    def test_initializeDriveDetector_createsDetector_viaFactory(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid config
        When: start() initializes all components
        Then: _driveDetector is created via createDriveDetectorFromConfig
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert orchestrator._driveDetector is not None

        finally:
            orchestrator.stop()

    def test_initializeDriveDetector_passesArgs_toFactory(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeDriveDetector is called
        Then: createDriveDetectorFromConfig receives config, statisticsEngine, database
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        with patch(
            'pi.obd.drive.createDriveDetectorFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            orchestrator._statisticsEngine = MagicMock()
            orchestrator._database = MagicMock()

            # Act
            orchestrator._initializeDriveDetector()

            # Assert
            mockFactory.assert_called_once_with(
                driveDetectionConfig,
                orchestrator._statisticsEngine,
                orchestrator._database
            )

    def test_initializeDriveDetector_logsSuccess_onCreation(
        self, driveDetectionConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeDriveDetector succeeds
        Then: 'DriveDetector started successfully' is logged
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        orchestrator._statisticsEngine = MagicMock()
        orchestrator._database = MagicMock()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._initializeDriveDetector()

        # Assert
        assert any(
            'DriveDetector started successfully' in record.message
            for record in caplog.records
        )

    def test_initializeDriveDetector_receivesStatisticsEngine(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with initialized statisticsEngine
        When: _initializeDriveDetector is called
        Then: statisticsEngine is passed to factory for post-drive analysis
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockEngine = MagicMock()
        orchestrator._statisticsEngine = mockEngine
        orchestrator._database = MagicMock()

        with patch(
            'pi.obd.drive.createDriveDetectorFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeDriveDetector()

            # Assert - statisticsEngine is the second argument
            args = mockFactory.call_args[0]
            assert args[1] is mockEngine

    def test_initializeDriveDetector_receivesDatabase(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with initialized database
        When: _initializeDriveDetector is called
        Then: database is passed to factory for drive event logging
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockDb = MagicMock()
        orchestrator._statisticsEngine = MagicMock()
        orchestrator._database = mockDb

        with patch(
            'pi.obd.drive.createDriveDetectorFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeDriveDetector()

            # Assert - database is the third argument
            args = mockFactory.call_args[0]
            assert args[2] is mockDb


# ================================================================================
# AC2: Detector receives RPM values from realtime logger
# ================================================================================


class TestDetectorReceivesRpmFromLogger:
    """Tests that detector receives RPM values from realtime logger."""

    def test_handleReading_passesRpm_toDriveDetector(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with drive detector wired
        When: _handleReading receives RPM reading
        Then: driveDetector.processValue('RPM', value) is called
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        reading = MagicMock()
        reading.parameterName = 'RPM'
        reading.value = 2500
        reading.unit = 'rpm'

        # Act
        orchestrator._handleReading(reading)

        # Assert
        mockDetector.processValue.assert_called_once_with('RPM', 2500)

    def test_handleReading_passesSpeed_toDriveDetector(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with drive detector wired
        When: _handleReading receives SPEED reading
        Then: driveDetector.processValue('SPEED', value) is called
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockDetector = MagicMock()
        orchestrator._driveDetector = mockDetector

        reading = MagicMock()
        reading.parameterName = 'SPEED'
        reading.value = 65
        reading.unit = 'mph'

        # Act
        orchestrator._handleReading(reading)

        # Assert
        mockDetector.processValue.assert_called_once_with('SPEED', 65)

    def test_handleReading_handlesDetectorError_gracefully(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with drive detector that raises
        When: _handleReading processes reading
        Then: Exception is caught and logged, orchestrator continues
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        mockDetector = MagicMock()
        mockDetector.processValue.side_effect = RuntimeError("detector error")
        orchestrator._driveDetector = mockDetector

        reading = MagicMock()
        reading.parameterName = 'RPM'
        reading.value = 3000
        reading.unit = 'rpm'

        # Act - should not raise
        orchestrator._handleReading(reading)

        # Assert - error was caught, no exception propagated

    def test_handleReading_skipsDetector_whenNone(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no drive detector (None)
        When: _handleReading processes reading
        Then: No error, reading processed normally
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        orchestrator._driveDetector = None

        reading = MagicMock()
        reading.parameterName = 'RPM'
        reading.value = 1500
        reading.unit = 'rpm'

        # Act - should not raise
        orchestrator._handleReading(reading)

        # Assert - no error, stats still updated
        assert orchestrator._healthCheckStats.totalReadings == 1


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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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


# ================================================================================
# AC5: Drive sessions logged to database for history
# ================================================================================


class TestDriveSessionsLoggedToDatabase:
    """Tests that drive sessions are logged to database for history."""

    def test_driveDetector_logsDriveStart_toDatabase(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: DriveDetector with database connected
        When: Drive starts
        Then: 'drive_start' event is logged to connection_log table
        """
        # Arrange
        from pi.obd.drive import DriveDetector

        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)
        mockConn.cursor.return_value = mockCursor

        config = driveDetectionConfig
        detector = DriveDetector(config, database=mockDb)
        detector.start()

        # Simulate drive start
        from datetime import timedelta
        startTime = datetime(2026, 4, 11, 10, 0, 0)

        with patch('pi.obd.drive.detector.datetime') as mockDatetime:
            mockDatetime.now.return_value = startTime
            mockDatetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
            detector.processValue('RPM', 800)

            mockDatetime.now.return_value = startTime + timedelta(seconds=2)
            detector.processValue('RPM', 800)

        # Assert - database insert was called with drive_start event
        executeCalls = mockCursor.execute.call_args_list
        assert len(executeCalls) >= 1
        sqlCall = executeCalls[0]
        assert 'connection_log' in sqlCall[0][0]
        assert sqlCall[0][1][1] == 'drive_start'

    def test_driveDetector_logsDriveEnd_toDatabase(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: DriveDetector with database connected and active drive
        When: Drive ends
        Then: 'drive_end' event is logged to connection_log table
        """
        # Arrange
        from pi.obd.drive import DriveDetector

        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)
        mockConn.cursor.return_value = mockCursor

        config = driveDetectionConfig
        detector = DriveDetector(config, database=mockDb)
        detector.start()

        # Simulate full drive cycle
        from datetime import timedelta
        startTime = datetime(2026, 4, 11, 10, 0, 0)

        with patch('pi.obd.drive.detector.datetime') as mockDatetime:
            mockDatetime.now.return_value = startTime
            mockDatetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
            detector.processValue('RPM', 800)

            mockDatetime.now.return_value = startTime + timedelta(seconds=2)
            detector.processValue('RPM', 800)

            endTime = startTime + timedelta(seconds=30)
            mockDatetime.now.return_value = endTime
            detector.processValue('RPM', 0)

            mockDatetime.now.return_value = endTime + timedelta(seconds=3)
            detector.processValue('RPM', 0)

        # Assert - second database call is drive_end
        executeCalls = mockCursor.execute.call_args_list
        assert len(executeCalls) >= 2
        endCall = executeCalls[1]
        assert 'connection_log' in endCall[0][0]
        assert endCall[0][1][1] == 'drive_end'

    def test_driveDetector_storesSession_inHistory(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: DriveDetector with a completed drive
        When: getSessionHistory is called
        Then: Session appears in history with correct profile and timing
        """
        # Arrange
        from pi.obd.drive import DriveDetector

        config = driveDetectionConfig
        detector = DriveDetector(config)
        detector.start()

        from datetime import timedelta
        startTime = datetime(2026, 4, 11, 10, 0, 0)

        with patch('pi.obd.drive.detector.datetime') as mockDatetime:
            mockDatetime.now.return_value = startTime
            mockDatetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
            detector.processValue('RPM', 800)

            mockDatetime.now.return_value = startTime + timedelta(seconds=2)
            detector.processValue('RPM', 800)

            endTime = startTime + timedelta(seconds=30)
            mockDatetime.now.return_value = endTime
            detector.processValue('RPM', 0)

            mockDatetime.now.return_value = endTime + timedelta(seconds=3)
            detector.processValue('RPM', 0)

        # Act
        history = detector.getSessionHistory()

        # Assert
        assert len(history) == 1
        session = history[0]
        assert session.profileId == 'daily'
        assert session.startTime is not None
        assert session.endTime is not None
        assert not session.isActive()

    def test_databaseError_doesNotCrash_detector(
        self, driveDetectionConfig: dict[str, Any]
    ):
        """
        Given: DriveDetector with database that raises on insert
        When: Drive starts
        Then: Database error caught, detector continues operating
        """
        # Arrange
        from pi.obd.drive import DriveDetector

        mockDb = MagicMock()
        mockDb.connect.side_effect = RuntimeError("db connection error")

        config = driveDetectionConfig
        detector = DriveDetector(config, database=mockDb)
        detector.start()

        from datetime import timedelta
        startTime = datetime(2026, 4, 11, 10, 0, 0)

        # Act - should not raise
        with patch('pi.obd.drive.detector.datetime') as mockDatetime:
            mockDatetime.now.return_value = startTime
            mockDatetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
            detector.processValue('RPM', 800)

            mockDatetime.now.return_value = startTime + timedelta(seconds=2)
            detector.processValue('RPM', 800)

        # Assert - detector still detected the drive despite db error
        assert detector.isDriving()


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
        from pi.obd.drive import DriveDetector, DriveState

        config = driveDetectionConfig
        detector = DriveDetector(config)
        detector.start()

        from datetime import timedelta
        startTime = datetime(2026, 4, 11, 10, 0, 0)

        with patch('pi.obd.drive.detector.datetime') as mockDatetime:
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
        from pi.obd.drive import DriveDetector, DriveState

        config = driveDetectionConfig
        detector = DriveDetector(config)
        detector.start()

        from datetime import timedelta
        startTime = datetime(2026, 4, 11, 10, 0, 0)

        with patch('pi.obd.drive.detector.datetime') as mockDatetime:
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
        from pi.obd.drive import DriveDetector

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
        from pi.obd.drive import DriveDetector

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
        from pi.obd.drive import DriveDetector

        config = driveDetectionConfig
        detector = DriveDetector(config)
        detector.start()

        from datetime import timedelta
        startTime = datetime(2026, 4, 11, 10, 0, 0)

        with patch('pi.obd.drive.detector.datetime') as mockDatetime:
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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=driveDetectionConfig,
            simulate=True
        )

        orchestrator._driveDetector = None

        # Act - should not raise
        orchestrator._setupComponentCallbacks()


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
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

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
        from pi.obd.orchestrator import ApplicationOrchestrator, ShutdownState

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
