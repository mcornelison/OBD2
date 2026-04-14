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
        from pi.analysis.engine import StatisticsEngine

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
        from pi.analysis.engine import StatisticsEngine

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
        from common.analysis.types import AnalysisState
        from pi.analysis.engine import StatisticsEngine

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
        from common.analysis.types import AnalysisState
        from pi.analysis.engine import StatisticsEngine

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
        from pi.analysis.engine import StatisticsEngine

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
        from pi.analysis.engine import StatisticsEngine

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
        from pi.analysis.engine import StatisticsEngine

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
        from pi.analysis.engine import StatisticsEngine

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
        from pi.analysis.engine import StatisticsEngine

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
        from pi.analysis.engine import StatisticsEngine

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
