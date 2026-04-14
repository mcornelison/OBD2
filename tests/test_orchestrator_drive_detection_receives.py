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
