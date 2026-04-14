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
