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
        from pi.obd.orchestrator import ApplicationOrchestrator

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
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockDb = MagicMock()
        orchestrator._database = mockDb

        with patch(
            'pi.obd.statistics_engine.createStatisticsEngineFromConfig'
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
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )

        with patch(
            'pi.obd.statistics_engine.createStatisticsEngineFromConfig'
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
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )

        with patch(
            'pi.obd.statistics_engine.createStatisticsEngineFromConfig'
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
        from pi.obd.orchestrator import (
            ApplicationOrchestrator,
            ComponentInitializationError,
        )

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )

        with patch(
            'pi.obd.statistics_engine.createStatisticsEngineFromConfig'
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
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockDb = MagicMock()
        orchestrator._database = mockDb

        with patch(
            'pi.obd.statistics_engine.createStatisticsEngineFromConfig'
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
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=statsConfig,
            simulate=True
        )
        mockDb = MagicMock(name='TestDatabase')
        orchestrator._database = mockDb

        with patch(
            'pi.obd.statistics_engine.createStatisticsEngineFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeStatisticsEngine()

            # Assert
            mockFactory.assert_called_once()
            callArgs = mockFactory.call_args
            assert callArgs[0][0] is mockDb, "Database should be first arg"
            assert callArgs[0][1] is statsConfig, "Config should be second arg"
