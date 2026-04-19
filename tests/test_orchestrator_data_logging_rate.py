################################################################################
# File Name: test_orchestrator_data_logging.py
# Purpose/Description: Tests for orchestrator realtime data logging wiring (US-OSC-006)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-006
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator realtime data logging wiring.

Verifies that the orchestrator correctly:
- Creates RealtimeDataLogger from config via factory function
- Connects logger to OBD connection and database
- Uses profile-specific polling interval
- Filters parameters by logData flag
- Routes dashboard parameters to display manager
- Wires onReading callback to update display, drive detector, and alert manager
- Wires onError callback to log warnings and continue
- Logs data rate every 5 minutes (configurable)

Usage:
    pytest tests/test_orchestrator_data_logging.py -v
"""

import logging
import os
import tempfile
from datetime import datetime, timedelta
from typing import Any

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getDataLoggingTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for data logging wiring tests.

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
                'name': 'Data Logging Test',
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
                    {'name': 'THROTTLE_POS', 'logData': True, 'displayOnDashboard': False},
                    {'name': 'INTAKE_TEMP', 'logData': False, 'displayOnDashboard': False}
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
                'activeProfile': 'daily',
                'availableProfiles': [
                    {
                        'id': 'daily',
                        'name': 'Daily Profile',
                        'description': 'Normal daily driving',
                        'pollingIntervalMs': 200
                    },
                    {
                        'id': 'performance',
                        'name': 'Performance Profile',
                        'description': 'Performance driving',
                        'pollingIntervalMs': 50
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
def dataLoggingConfig(tempDb: str) -> dict[str, Any]:
    """Create data logging test configuration with temp database."""
    return getDataLoggingTestConfig(tempDb)


# ================================================================================
# AC9: Data logging rate logged every 5 minutes (records/minute)
# ================================================================================


class TestDataLoggingRateTracking:
    """Tests that data logging rate is logged periodically."""

    def test_logDataLoggingRate_logsRecordsPerMinute(
        self, dataLoggingConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with some readings processed
        When: _logDataLoggingRate is called
        Then: Records/minute rate is logged at INFO level
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        # Simulate prior state: 100 readings over 5 minutes
        orchestrator._lastDataRateLogTime = datetime.now() - timedelta(minutes=5)
        orchestrator._lastDataRateLogCount = 0
        orchestrator._healthCheckStats.totalReadings = 100

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._logDataLoggingRate()

        # Assert
        infoMessages = [
            r.message for r in caplog.records if r.levelno == logging.INFO
        ]
        assert any('DATA LOGGING RATE' in m for m in infoMessages)
        assert any('records/min=' in m for m in infoMessages)

    def test_logDataLoggingRate_calculatesCorrectRate(
        self, dataLoggingConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: 60 readings in 1 minute
        When: _logDataLoggingRate is called
        Then: Rate is approximately 60 records/minute
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        orchestrator._lastDataRateLogTime = datetime.now() - timedelta(minutes=1)
        orchestrator._lastDataRateLogCount = 0
        orchestrator._healthCheckStats.totalReadings = 60

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._logDataLoggingRate()

        # Assert - rate should be ~60/min
        infoMessages = [
            r.message for r in caplog.records if r.levelno == logging.INFO
        ]
        rateMessage = next(
            (m for m in infoMessages if 'records/min=' in m), None
        )
        assert rateMessage is not None
        assert 'records/min=60.0' in rateMessage or 'records/min=59' in rateMessage

    def test_dataRateLogInterval_configurableFromConfig(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Config with dataRateLogIntervalSeconds=5
        When: Orchestrator is created
        Then: _dataRateLogInterval is set to 5
        """
        # Arrange & Act
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        # Assert
        assert orchestrator._dataRateLogInterval == 5

    def test_dataRateLogInterval_defaultsToFiveMinutes(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Config without dataRateLogIntervalSeconds
        When: Orchestrator is created
        Then: _dataRateLogInterval defaults to 300 seconds (5 minutes)
        """
        # Arrange
        from pi.obdii.orchestrator import (
            DEFAULT_DATA_RATE_LOG_INTERVAL,
            ApplicationOrchestrator,
        )

        configWithoutInterval = dict(dataLoggingConfig)
        configWithoutInterval['pi']['monitoring'] = {}

        # Act
        orchestrator = ApplicationOrchestrator(
            config=configWithoutInterval,
            simulate=True
        )

        # Assert
        assert orchestrator._dataRateLogInterval == DEFAULT_DATA_RATE_LOG_INTERVAL
        assert DEFAULT_DATA_RATE_LOG_INTERVAL == 300.0

    def test_logDataLoggingRate_updatesTrackingState(
        self, dataLoggingConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with readings tracked
        When: _logDataLoggingRate is called
        Then: _lastDataRateLogCount is updated to current total
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        orchestrator._lastDataRateLogTime = datetime.now() - timedelta(minutes=1)
        orchestrator._lastDataRateLogCount = 0
        orchestrator._healthCheckStats.totalReadings = 50

        # Act
        orchestrator._logDataLoggingRate()

        # Assert
        assert orchestrator._lastDataRateLogCount == 50

    def test_logDataLoggingRate_logsTotalLogged(
        self, dataLoggingConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with 200 total readings
        When: _logDataLoggingRate is called
        Then: Log message includes total_logged=200
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=dataLoggingConfig,
            simulate=True
        )

        orchestrator._lastDataRateLogTime = datetime.now() - timedelta(minutes=2)
        orchestrator._lastDataRateLogCount = 100
        orchestrator._healthCheckStats.totalReadings = 200

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._logDataLoggingRate()

        # Assert
        infoMessages = [
            r.message for r in caplog.records if r.levelno == logging.INFO
        ]
        assert any('total_logged=200' in m for m in infoMessages)
