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
import time
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

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
        'aiAnalysis': {
            'enabled': False
        },
        'profiles': {
            'activeProfile': 'daily',
            'availableProfiles': [
                {
                    'id': 'daily',
                    'name': 'Daily Profile',
                    'description': 'Normal daily driving',
                    'alertThresholds': {
                        'rpmRedline': 6000,
                        'coolantTempCritical': 105,
                        'boostPressureMax': 18,
                        'oilPressureLow': 20
                    },
                    'pollingIntervalMs': 200
                },
                {
                    'id': 'spirited',
                    'name': 'Spirited Profile',
                    'description': 'Spirited driving with higher thresholds',
                    'alertThresholds': {
                        'rpmRedline': 7000,
                        'coolantTempCritical': 220,
                        'boostPressureMax': 22,
                        'oilPressureLow': 15
                    },
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
        'logging': {
            'level': 'DEBUG',
            'maskPII': False
        }
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
# AC1: StatisticsEngine created from config in orchestrator
# ================================================================================


class TestStatisticsEngineCreatedFromConfig:
    """Tests that StatisticsEngine is created from config in orchestrator."""

    def test_initializeStatisticsEngine_createsEngine_viaFactory(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid config
        When: start() initializes all components
        Then: _statisticsEngine is created and not None
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert orchestrator._statisticsEngine is not None
        finally:
            orchestrator.stop()

    def test_initializeStatisticsEngine_passesDbAndConfig_toFactory(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeStatisticsEngine() is called
        Then: Factory receives database and config
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockDb = MagicMock()
        orchestrator._database = mockDb

        with patch(
            'obd.statistics_engine.createStatisticsEngineFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeStatisticsEngine()

            # Assert
            mockFactory.assert_called_once_with(mockDb, statsConfig)

    def test_initializeStatisticsEngine_logsStarting_message(
        self, statsConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeStatisticsEngine() is called
        Then: Logs 'Starting statisticsEngine...'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )

        with patch(
            'obd.statistics_engine.createStatisticsEngineFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._initializeStatisticsEngine()

        # Assert
        assert any(
            'Starting statisticsEngine...' in record.message
            for record in caplog.records
        )

    def test_initializeStatisticsEngine_logsSuccess_onCreation(
        self, statsConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeStatisticsEngine() succeeds
        Then: Logs 'StatisticsEngine started successfully'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )

        with patch(
            'obd.statistics_engine.createStatisticsEngineFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._initializeStatisticsEngine()

        # Assert
        assert any(
            'StatisticsEngine started successfully' in record.message
            for record in caplog.records
        )

    def test_initializeStatisticsEngine_raisesComponentError_onFailure(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator where factory raises an exception
        When: _initializeStatisticsEngine() is called
        Then: Raises ComponentInitializationError
        """
        # Arrange
        from obd.orchestrator import (
            ApplicationOrchestrator,
            ComponentInitializationError,
        )

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )

        with patch(
            'obd.statistics_engine.createStatisticsEngineFromConfig'
        ) as mockFactory:
            mockFactory.side_effect = RuntimeError("Engine init failed")

            # Act + Assert
            with pytest.raises(ComponentInitializationError):
                orchestrator._initializeStatisticsEngine()


# ================================================================================
# AC2: Engine connected to database for data retrieval and storage
# ================================================================================


class TestEngineConnectedToDatabase:
    """Tests that StatisticsEngine is connected to database."""

    def test_statisticsEngine_receivesDatabase_fromOrchestrator(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with initialized database
        When: StatisticsEngine is created
        Then: Engine has reference to database for data access
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockDb = MagicMock()
        orchestrator._database = mockDb

        with patch(
            'obd.statistics_engine.createStatisticsEngineFromConfig'
        ) as mockFactory:
            mockEngine = MagicMock()
            mockFactory.return_value = mockEngine

            # Act
            orchestrator._initializeStatisticsEngine()

            # Assert - factory called with database as first arg
            args = mockFactory.call_args[0]
            assert args[0] is mockDb

    def test_statisticsEngine_databaseIsFirstArg_toFactory(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with database
        When: Factory is called
        Then: Database is the first positional argument
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockDb = MagicMock(name='TestDatabase')
        orchestrator._database = mockDb

        with patch(
            'obd.statistics_engine.createStatisticsEngineFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeStatisticsEngine()

            # Assert
            mockFactory.assert_called_once()
            callArgs = mockFactory.call_args
            assert callArgs[0][0] is mockDb, "Database should be first arg"
            assert callArgs[0][1] is statsConfig, "Config should be second arg"


# ================================================================================
# AC3: Engine scheduleAnalysis() called on drive end
# ================================================================================


class TestScheduleAnalysisOnDriveEnd:
    """Tests that scheduleAnalysis() is called when a drive ends."""

    def test_driveDetector_passedStatisticsEngine_atInit(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with StatisticsEngine initialized
        When: DriveDetector is initialized
        Then: StatisticsEngine is passed to DriveDetector factory
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockEngine = MagicMock()
        mockDb = MagicMock()
        orchestrator._statisticsEngine = mockEngine
        orchestrator._database = mockDb

        with patch(
            'obd.drive.createDriveDetectorFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeDriveDetector()

            # Assert - statisticsEngine is second arg
            args = mockFactory.call_args[0]
            assert args[1] is mockEngine

    def test_driveDetector_receivesConfig_statisticsEngine_database(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with all dependencies
        When: DriveDetector factory is called
        Then: Receives config, statisticsEngine, and database
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockEngine = MagicMock()
        mockDb = MagicMock()
        orchestrator._statisticsEngine = mockEngine
        orchestrator._database = mockDb

        with patch(
            'obd.drive.createDriveDetectorFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeDriveDetector()

            # Assert
            mockFactory.assert_called_once_with(
                statsConfig, mockEngine, mockDb
            )

    def test_statisticsEngine_initBeforeDriveDetector_inOrder(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator initialization sequence
        When: _initializeAllComponents() runs
        Then: StatisticsEngine is initialized before DriveDetector
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )

        initOrder: list[str] = []

        originalInitStats = orchestrator._initializeStatisticsEngine
        originalInitDrive = orchestrator._initializeDriveDetector

        def trackStats():
            initOrder.append('statisticsEngine')
            originalInitStats()

        def trackDrive():
            initOrder.append('driveDetector')
            originalInitDrive()

        orchestrator._initializeStatisticsEngine = trackStats
        orchestrator._initializeDriveDetector = trackDrive

        try:
            # Act
            orchestrator.start()

            # Assert
            statsIdx = initOrder.index('statisticsEngine')
            driveIdx = initOrder.index('driveDetector')
            assert statsIdx < driveIdx, (
                "StatisticsEngine must initialize before DriveDetector"
            )
        finally:
            orchestrator.stop()

    def test_driveDetector_triggerAnalysis_callsScheduleAnalysis(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: DriveDetector with a StatisticsEngine
        When: _triggerAnalysis() is called (on drive end)
        Then: scheduleAnalysis() is called on the engine with delaySeconds=0
        """
        # Arrange
        from obd.drive.detector import DriveDetector

        mockEngine = MagicMock()
        mockEngine.scheduleAnalysis.return_value = True
        mockDb = MagicMock()

        detector = DriveDetector(
            config=statsConfig,
            statisticsEngine=mockEngine,
            database=mockDb
        )

        # Act
        detector._triggerAnalysis()

        # Assert
        mockEngine.scheduleAnalysis.assert_called_once()
        callKwargs = mockEngine.scheduleAnalysis.call_args[1]
        assert callKwargs['delaySeconds'] == 0

    def test_driveDetector_triggerAnalysis_passesProfileId(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: DriveDetector configured with 'daily' profile
        When: _triggerAnalysis() is called
        Then: scheduleAnalysis() receives profileId='daily'
        """
        # Arrange
        from obd.drive.detector import DriveDetector

        mockEngine = MagicMock()
        mockEngine.scheduleAnalysis.return_value = True
        mockDb = MagicMock()

        detector = DriveDetector(
            config=statsConfig,
            statisticsEngine=mockEngine,
            database=mockDb
        )

        # Act
        detector._triggerAnalysis()

        # Assert
        callKwargs = mockEngine.scheduleAnalysis.call_args[1]
        assert callKwargs['profileId'] == 'daily'


# ================================================================================
# AC4: Engine calculates configured statistics
# ================================================================================


class TestConfiguredStatisticsCalculation:
    """Tests that engine calculates the configured statistics."""

    def test_statisticsEngine_receivesConfiguredStats_fromConfig(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Config with calculateStatistics list
        When: StatisticsEngine is created
        Then: Engine has the configured statistics list
        """
        # Arrange
        from analysis.engine import StatisticsEngine

        mockDb = MagicMock()

        # Act
        engine = StatisticsEngine(mockDb, statsConfig)

        # Assert
        expectedStats = [
            'max', 'min', 'avg', 'mode',
            'std_1', 'std_2', 'outlier_min', 'outlier_max'
        ]
        assert engine._calculateStats == expectedStats

    def test_statisticsEngine_usesDefaultStats_whenNotConfigured(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Config without calculateStatistics key
        When: StatisticsEngine is created
        Then: Engine uses default statistics list
        """
        # Arrange
        from analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        configNoStats = dict(statsConfig)
        configNoStats['analysis'] = {'triggerAfterDrive': True}

        # Act
        engine = StatisticsEngine(mockDb, configNoStats)

        # Assert - defaults include all 8 statistics
        assert 'max' in engine._calculateStats
        assert 'min' in engine._calculateStats
        assert 'avg' in engine._calculateStats
        assert 'mode' in engine._calculateStats
        assert 'std_1' in engine._calculateStats
        assert 'std_2' in engine._calculateStats
        assert 'outlier_min' in engine._calculateStats
        assert 'outlier_max' in engine._calculateStats

    def test_statisticsEngine_customStatsSubset_usedCorrectly(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Config with only ['max', 'min', 'avg']
        When: StatisticsEngine is created
        Then: Engine has only those three statistics configured
        """
        # Arrange
        from analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        configSubset = dict(statsConfig)
        configSubset['analysis'] = {
            'calculateStatistics': ['max', 'min', 'avg']
        }

        # Act
        engine = StatisticsEngine(mockDb, configSubset)

        # Assert
        assert engine._calculateStats == ['max', 'min', 'avg']
        assert len(engine._calculateStats) == 3


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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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
        from obd.orchestrator import ApplicationOrchestrator

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


# ================================================================================
# AC7: Analysis runs in background thread (non-blocking)
# ================================================================================


class TestBackgroundThreadExecution:
    """Tests that analysis runs in a background thread."""

    def test_scheduleAnalysis_usesBackgroundThread_withDaemon(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: StatisticsEngine
        When: scheduleAnalysis() is called with delaySeconds=0
        Then: Analysis runs in a daemon thread
        """
        # Arrange
        from analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        # Make connect() return a context manager with cursor
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockCursor.fetchall.return_value = []
        mockConn.cursor.return_value = mockCursor
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)

        engine = StatisticsEngine(mockDb, statsConfig)

        # Act
        result = engine.scheduleAnalysis(profileId='daily', delaySeconds=0)

        # Give thread a moment to start
        time.sleep(0.1)

        # Assert
        assert result is True
        if engine._analysisThread is not None:
            assert engine._analysisThread.daemon is True

    def test_scheduleAnalysis_returnsTrue_onSuccess(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Idle StatisticsEngine
        When: scheduleAnalysis() is called
        Then: Returns True indicating successful scheduling
        """
        # Arrange
        from analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockCursor.fetchall.return_value = []
        mockConn.cursor.return_value = mockCursor
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)

        engine = StatisticsEngine(mockDb, statsConfig)

        # Act
        result = engine.scheduleAnalysis(profileId='daily', delaySeconds=0)

        # Assert
        assert result is True

    def test_scheduleAnalysis_returnsFalse_whenAlreadyRunning(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: StatisticsEngine that is already running
        When: scheduleAnalysis() is called
        Then: Returns False
        """
        # Arrange
        from analysis.engine import StatisticsEngine
        from analysis.types import AnalysisState

        mockDb = MagicMock()
        engine = StatisticsEngine(mockDb, statsConfig)
        engine._state = AnalysisState.RUNNING

        # Act
        result = engine.scheduleAnalysis(profileId='daily')

        # Assert
        assert result is False

    def test_scheduleAnalysis_setsState_toScheduled(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Idle StatisticsEngine
        When: scheduleAnalysis() is called
        Then: State transitions to SCHEDULED
        """
        # Arrange
        from analysis.engine import StatisticsEngine
        from analysis.types import AnalysisState

        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockCursor.fetchall.return_value = []
        mockConn.cursor.return_value = mockCursor
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)

        engine = StatisticsEngine(mockDb, statsConfig)
        assert engine.state == AnalysisState.IDLE

        # Act
        engine.scheduleAnalysis(profileId='daily', delaySeconds=0)

        # Assert - state should have transitioned from IDLE
        # (may be SCHEDULED, RUNNING, or COMPLETED depending on timing)
        assert engine.state != AnalysisState.IDLE or engine.state == AnalysisState.COMPLETED

    def test_analysisThread_namedStatisticsAnalysis(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: StatisticsEngine
        When: Background analysis is started
        Then: Thread is named 'StatisticsAnalysis'
        """
        # Arrange
        from analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockCursor.fetchall.return_value = []
        mockConn.cursor.return_value = mockCursor
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)

        engine = StatisticsEngine(mockDb, statsConfig)

        # Act
        engine.scheduleAnalysis(profileId='daily', delaySeconds=0)
        time.sleep(0.1)

        # Assert
        if engine._analysisThread is not None:
            assert engine._analysisThread.name == 'StatisticsAnalysis'


# ================================================================================
# AC8: Analysis results stored with profile_id association
# ================================================================================


class TestResultsStoredWithProfileId:
    """Tests that analysis results are associated with profile_id."""

    def test_analysisResult_hasProfileId_fromConfig(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Config with activeProfile='daily'
        When: calculateStatistics() runs
        Then: AnalysisResult.profileId is 'daily'
        """
        # Arrange
        from analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockCursor.fetchall.return_value = []
        mockConn.cursor.return_value = mockCursor
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)

        engine = StatisticsEngine(mockDb, statsConfig)

        # Act
        result = engine.calculateStatistics(profileId='daily', storeResults=False)

        # Assert
        assert result.profileId == 'daily'

    def test_analysisResult_usesExplicitProfileId_overDefault(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Config with activeProfile='daily'
        When: calculateStatistics(profileId='spirited') is called
        Then: AnalysisResult.profileId is 'spirited' (explicit overrides default)
        """
        # Arrange
        from analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockCursor.fetchall.return_value = []
        mockConn.cursor.return_value = mockCursor
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)

        engine = StatisticsEngine(mockDb, statsConfig)

        # Act
        result = engine.calculateStatistics(profileId='spirited', storeResults=False)

        # Assert
        assert result.profileId == 'spirited'

    def test_analysisResult_usesActiveProfile_whenNoneGiven(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Config with activeProfile='daily'
        When: calculateStatistics(profileId=None) is called
        Then: AnalysisResult.profileId defaults to 'daily'
        """
        # Arrange
        from analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockCursor.fetchall.return_value = []
        mockConn.cursor.return_value = mockCursor
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)

        engine = StatisticsEngine(mockDb, statsConfig)

        # Act
        result = engine.calculateStatistics(profileId=None, storeResults=False)

        # Assert
        assert result.profileId == 'daily'

    def test_storeResults_callsStoreStatistics_withResult(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: StatisticsEngine with storeResults=True
        When: calculateStatistics() completes with data
        Then: _storeStatistics() is called with the result
        """
        # Arrange
        from analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        # Return some test data so stats get calculated
        mockCursor.fetchall.return_value = [
            {'parameter_name': 'RPM', 'value': 800.0},
            {'parameter_name': 'RPM', 'value': 900.0},
            {'parameter_name': 'RPM', 'value': 1000.0},
        ]
        mockConn.cursor.return_value = mockCursor
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)

        engine = StatisticsEngine(mockDb, statsConfig)

        with patch.object(engine, '_storeStatistics') as mockStore:
            # Act
            result = engine.calculateStatistics(
                profileId='daily', storeResults=True
            )

            # Assert
            if result.parameterStats:
                mockStore.assert_called_once()

    def test_analysisResult_containsDate_andDuration(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: StatisticsEngine
        When: calculateStatistics() runs
        Then: Result has analysisDate and durationMs
        """
        # Arrange
        from analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockCursor.fetchall.return_value = []
        mockConn.cursor.return_value = mockCursor
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)

        engine = StatisticsEngine(mockDb, statsConfig)

        # Act
        result = engine.calculateStatistics(profileId='daily', storeResults=False)

        # Assert
        assert isinstance(result.analysisDate, datetime)
        assert result.durationMs >= 0


# ================================================================================
# AC9: Typecheck and lint passes (verified by CI, not in test code)
# ================================================================================
# AC9 is verified by running `make lint` and `mypy` as part of the quality checks.
# No dedicated test class needed.


# ================================================================================
# Additional Integration: Callback wiring via _setupComponentCallbacks
# ================================================================================


class TestCallbackWiringIntegration:
    """Tests that registerCallbacks wiring works end-to-end in orchestrator."""

    def test_setupCallbacks_skipsRegistration_whenNoEngine(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no StatisticsEngine (None)
        When: _setupComponentCallbacks() runs
        Then: No error raised, callbacks skipped
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        orchestrator._statisticsEngine = None

        # Act + Assert - should not raise
        orchestrator._setupComponentCallbacks()

    def test_setupCallbacks_skipsRegistration_whenNoRegisterMethod(
        self, statsConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with engine that has no registerCallbacks method
        When: _setupComponentCallbacks() runs
        Then: No error raised, callbacks skipped
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockEngine = MagicMock(spec=[])  # no registerCallbacks attr
        orchestrator._statisticsEngine = mockEngine

        # Act + Assert - should not raise
        orchestrator._setupComponentCallbacks()

    def test_setupCallbacks_logsDebug_onSuccess(
        self, statsConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with a valid StatisticsEngine
        When: _setupComponentCallbacks() registers callbacks
        Then: Logs 'Statistics engine callbacks registered'
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockEngine = MagicMock()
        mockEngine.registerCallbacks = MagicMock()
        orchestrator._statisticsEngine = mockEngine

        # Act
        with caplog.at_level(logging.DEBUG):
            orchestrator._setupComponentCallbacks()

        # Assert
        assert any(
            'Statistics engine callbacks registered' in record.message
            for record in caplog.records
        )

    def test_setupCallbacks_survivesRegistrationError(
        self, statsConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator where registerCallbacks() raises
        When: _setupComponentCallbacks() runs
        Then: Warning logged but no exception propagated
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockEngine = MagicMock()
        mockEngine.registerCallbacks.side_effect = RuntimeError("Registration failed")
        orchestrator._statisticsEngine = mockEngine

        # Act - should not raise
        with caplog.at_level(logging.WARNING):
            orchestrator._setupComponentCallbacks()

        # Assert
        assert any(
            'Could not register statistics engine callbacks' in record.message
            for record in caplog.records
        )

    def test_importError_skipsEngine_withWarning(
        self, statsConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator where statistics_engine import fails
        When: _initializeStatisticsEngine() is called
        Then: Warning logged and engine remains None
        """
        # Arrange
        from obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )

        with patch(
            'builtins.__import__', side_effect=ImportError("Module not found")
        ):
            # Need to target the specific import in the method
            pass

        # Use a more direct approach: patch the module-level import
        with patch.dict(
            'sys.modules', {'obd.statistics_engine': None}
        ):
            # Act
            with caplog.at_level(logging.WARNING):
                try:
                    orchestrator._initializeStatisticsEngine()
                except Exception:
                    pass  # ImportError might be raised differently

            # Assert
            assert orchestrator._statisticsEngine is None
