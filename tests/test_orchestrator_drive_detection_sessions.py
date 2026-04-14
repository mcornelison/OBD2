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
