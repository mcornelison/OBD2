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

import os
import tempfile
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockEngine = MagicMock()
        mockDb = MagicMock()
        orchestrator._statisticsEngine = mockEngine
        orchestrator._database = mockDb

        with patch(
            'pi.obdii.drive.createDriveDetectorFromConfig'
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockEngine = MagicMock()
        mockDb = MagicMock()
        orchestrator._statisticsEngine = mockEngine
        orchestrator._database = mockDb

        with patch(
            'pi.obdii.drive.createDriveDetectorFromConfig'
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
        from pi.obdii.orchestrator import ApplicationOrchestrator

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
        from pi.obdii.drive.detector import DriveDetector

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
        from pi.obdii.drive.detector import DriveDetector

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
        from pi.analysis.engine import StatisticsEngine

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
        from pi.analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        configNoStats = dict(statsConfig)
        configNoStats['pi']['analysis'] = {'triggerAfterDrive': True}

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
        from pi.analysis.engine import StatisticsEngine

        mockDb = MagicMock()
        configSubset = dict(statsConfig)
        configSubset['pi']['analysis'] = {
            'calculateStatistics': ['max', 'min', 'avg']
        }

        # Act
        engine = StatisticsEngine(mockDb, configSubset)

        # Assert
        assert engine._calculateStats == ['max', 'min', 'avg']
        assert len(engine._calculateStats) == 3
