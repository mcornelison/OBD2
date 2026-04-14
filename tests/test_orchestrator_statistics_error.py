################################################################################
# File Name: test_orchestrator_statistics.py
# Purpose/Description: Tests for orchestrator statistics engine wiring (US-OSC-009)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-009
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator statistics engine wiring.

Verifies that the orchestrator correctly:
- Creates StatisticsEngine from config via factory function
- Connects engine to database for data retrieval and storage
- Calls scheduleAnalysis() on drive end (via DriveDetector)
- Calculates configured statistics: max, min, avg, mode, std_1, std_2, outlier bounds
- Handles onComplete callback: logs completion and notifies display
- Handles onError callback: logs error and continues operation
- Runs analysis in background thread (non-blocking)
- Stores analysis results with profile_id association
- Passes typecheck and lint

Usage:
    pytest tests/test_orchestrator_statistics.py -v
"""

import logging
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock

import pytest

# ================================================================================
# Test Configuration
# ================================================================================


def getStatisticsTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for statistics engine wiring tests.

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
                'name': 'Statistics Engine Test',
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
                    {'name': 'INTAKE_PRESSURE', 'logData': True, 'displayOnDashboard': True},
                ]
            },
            'analysis': {
                'triggerAfterDrive': True,
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 1,
                'driveEndRpmThreshold': 100,
                'driveEndDurationSeconds': 2,
                'calculateStatistics': [
                    'max', 'min', 'avg', 'mode',
                    'std_1', 'std_2', 'outlier_min', 'outlier_max'
                ]
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
                        'id': 'spirited',
                        'name': 'Spirited Profile',
                        'description': 'Spirited driving with higher thresholds',
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
def statsConfig(tempDb: str) -> dict[str, Any]:
    """Create statistics test configuration with temp database."""
    return getStatisticsTestConfig(tempDb)


# ================================================================================
# AC6: Engine onError callback logs error and continues operation
# ================================================================================


class TestOnErrorCallback:
    """Tests that analysis errors are logged and operation continues."""

    def test_handleAnalysisError_logsError_withProfileAndMessage(
        self, statsConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with analysis error handler
        When: _handleAnalysisError() is called
        Then: Logs at ERROR level with profile and error details
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        testError = RuntimeError("Calculation overflow")

        # Act
        with caplog.at_level(logging.ERROR):
            orchestrator._handleAnalysisError('daily', testError)

        # Assert
        errorRecords = [
            r for r in caplog.records
            if r.levelno >= logging.ERROR
        ]
        assert len(errorRecords) >= 1
        errorMsg = errorRecords[0].message
        assert 'daily' in errorMsg
        assert 'Calculation overflow' in errorMsg

    def test_handleAnalysisError_incrementsTotalErrors(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with totalErrors = 0
        When: _handleAnalysisError() is called
        Then: totalErrors is incremented by 1
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        initialErrors = orchestrator._healthCheckStats.totalErrors

        # Act
        orchestrator._handleAnalysisError('daily', RuntimeError("test"))

        # Assert
        assert orchestrator._healthCheckStats.totalErrors == initialErrors + 1

    def test_handleAnalysisError_doesNotStopOrchestrator(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Running orchestrator
        When: _handleAnalysisError() is called
        Then: Orchestrator continues running (no exception raised)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        orchestrator._running = True

        # Act - should not raise
        orchestrator._handleAnalysisError('spirited', RuntimeError("DB locked"))

        # Assert
        assert orchestrator._running is True

    def test_callbackRegistration_registersOnError_withEngine(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with a StatisticsEngine
        When: _setupComponentCallbacks() runs
        Then: registerCallbacks() is called with onAnalysisError handler
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockEngine = MagicMock()
        mockEngine.registerCallbacks = MagicMock()
        orchestrator._statisticsEngine = mockEngine

        # Act
        orchestrator._setupComponentCallbacks()

        # Assert
        mockEngine.registerCallbacks.assert_called_once()
        callKwargs = mockEngine.registerCallbacks.call_args[1]
        assert 'onAnalysisError' in callKwargs
        assert callable(callKwargs['onAnalysisError'])
        assert callKwargs['onAnalysisError'].__name__ == '_handleAnalysisError'

    def test_handleAnalysisError_multipleErrors_allCounted(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no errors
        When: _handleAnalysisError() is called 3 times
        Then: totalErrors is incremented to 3
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )

        # Act
        orchestrator._handleAnalysisError('daily', RuntimeError("error 1"))
        orchestrator._handleAnalysisError('spirited', RuntimeError("error 2"))
        orchestrator._handleAnalysisError('daily', RuntimeError("error 3"))

        # Assert
        assert orchestrator._healthCheckStats.totalErrors == 3
