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
# AC5: Engine onComplete callback logs completion and notifies display
# ================================================================================


class TestOnCompleteCallback:
    """Tests that analysis completion is logged and display is notified."""

    def test_handleAnalysisComplete_logsCompletion(
        self, statsConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with analysis complete handler
        When: _handleAnalysisComplete() is called
        Then: Logs 'Statistical analysis completed' at INFO level
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockResult = MagicMock()

        # Act
        with caplog.at_level(logging.INFO):
            orchestrator._handleAnalysisComplete(mockResult)

        # Assert
        assert any(
            'Statistical analysis completed' in record.message
            for record in caplog.records
        )

    def test_handleAnalysisComplete_notifiesDisplay_withResult(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with display manager
        When: _handleAnalysisComplete() is called
        Then: Display receives showAnalysisResult() call with the result
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockDisplay = MagicMock()
        mockDisplay.showAnalysisResult = MagicMock()
        orchestrator._displayManager = mockDisplay
        mockResult = MagicMock()

        # Act
        orchestrator._handleAnalysisComplete(mockResult)

        # Assert
        mockDisplay.showAnalysisResult.assert_called_once_with(mockResult)

    def test_handleAnalysisComplete_survivesDisplayError(
        self, statsConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator where display raises an error
        When: _handleAnalysisComplete() is called
        Then: No exception propagated, error logged at DEBUG
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockDisplay = MagicMock()
        mockDisplay.showAnalysisResult.side_effect = RuntimeError("Display fail")
        orchestrator._displayManager = mockDisplay
        mockResult = MagicMock()

        # Act - should not raise
        with caplog.at_level(logging.DEBUG):
            orchestrator._handleAnalysisComplete(mockResult)

        # Assert
        assert any(
            'Display analysis result failed' in record.message
            for record in caplog.records
        )

    def test_handleAnalysisComplete_callsExternalCallback(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with external onAnalysisComplete callback
        When: _handleAnalysisComplete() is called
        Then: External callback receives the result
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        externalCallback = MagicMock()
        orchestrator._onAnalysisComplete = externalCallback
        mockResult = MagicMock()

        # Act
        orchestrator._handleAnalysisComplete(mockResult)

        # Assert
        externalCallback.assert_called_once_with(mockResult)

    def test_handleAnalysisComplete_survivesCallbackError(
        self, statsConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator where external callback raises
        When: _handleAnalysisComplete() is called
        Then: No exception propagated, warning logged
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        externalCallback = MagicMock(side_effect=RuntimeError("Callback fail"))
        orchestrator._onAnalysisComplete = externalCallback
        mockResult = MagicMock()

        # Act - should not raise
        with caplog.at_level(logging.WARNING):
            orchestrator._handleAnalysisComplete(mockResult)

        # Assert
        assert any(
            'onAnalysisComplete callback error' in record.message
            for record in caplog.records
        )

    def test_handleAnalysisComplete_noDisplay_noCrash(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no display manager (headless)
        When: _handleAnalysisComplete() is called
        Then: Completes without error
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        orchestrator._displayManager = None
        mockResult = MagicMock()

        # Act + Assert - should not raise
        orchestrator._handleAnalysisComplete(mockResult)

    def test_callbackRegistration_registersOnComplete_withEngine(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with a StatisticsEngine
        When: _setupComponentCallbacks() runs
        Then: registerCallbacks() is called with onAnalysisComplete handler
        """
        # Arrange
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        assert 'onAnalysisComplete' in callKwargs
        assert callable(callKwargs['onAnalysisComplete'])
        assert callKwargs['onAnalysisComplete'].__name__ == '_handleAnalysisComplete'
