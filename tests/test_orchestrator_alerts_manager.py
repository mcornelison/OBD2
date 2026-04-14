################################################################################
# File Name: test_orchestrator_alerts.py
# Purpose/Description: Tests for orchestrator alert system wiring (US-OSC-008)
# Author: Ralph Agent
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | Initial implementation for US-OSC-008
# 2026-04-13    | Ralph Agent  | Sweep 2a task 5 — add tieredThresholds to test config; RPM 7000 from tiered
# ================================================================================
################################################################################

"""
Tests for ApplicationOrchestrator alert system wiring.

Verifies that the orchestrator correctly:
- Creates AlertManager from config via factory function
- Routes all realtime values to AlertManager for threshold checking
- Uses active profile's alert thresholds
- Handles onAlert callback: logs at WARNING, sends to display, records in database
- Respects cooldown period (no repeated alerts for same condition)
- Displays alert priorities correctly (critical > warning > info)
- Provides queryable alert history from database
- Passes typecheck and lint

Usage:
    pytest tests/test_orchestrator_alerts.py -v
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


def getAlertTestConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for alert system wiring tests.

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
                'name': 'Alert System Test',
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
            }
        },
        'server': {
            'ai': {'enabled': False},
            'database': {},
            'api': {}
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
def alertConfig(tempDb: str) -> dict[str, Any]:
    """Create alert test configuration with temp database."""
    return getAlertTestConfig(tempDb)


# ================================================================================
# AC1: AlertManager created from config in orchestrator
# ================================================================================


class TestAlertManagerCreatedFromConfig:
    """Tests that AlertManager is created from config in orchestrator."""

    def test_initializeAlertManager_createsManager_viaFactory(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with valid alert config
        When: start() initializes all components
        Then: _alertManager is created and not None
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )

        try:
            # Act
            orchestrator.start()

            # Assert
            assert orchestrator._alertManager is not None
        finally:
            orchestrator.stop()

    def test_initializeAlertManager_passesConfig_toFactory(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert config
        When: _initializeAlertManager() is called
        Then: Factory receives config, database, and displayManager
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockDb = MagicMock()
        mockDisplay = MagicMock()
        orchestrator._database = mockDb
        orchestrator._displayManager = mockDisplay

        with patch(
            'pi.alert.createAlertManagerFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            orchestrator._initializeAlertManager()

            # Assert
            mockFactory.assert_called_once_with(
                alertConfig, mockDb, mockDisplay
            )

    def test_initializeAlertManager_logsSuccess_onCreation(
        self, alertConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeAlertManager() succeeds
        Then: Logs 'AlertManager started successfully'
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )

        with patch(
            'pi.alert.createAlertManagerFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._initializeAlertManager()

        # Assert
        assert any(
            'AlertManager started successfully' in record.message
            for record in caplog.records
        )

    def test_initializeAlertManager_logsStarting_message(
        self, alertConfig: dict[str, Any], caplog: pytest.LogCaptureFixture
    ):
        """
        Given: Orchestrator with valid config
        When: _initializeAlertManager() is called
        Then: Logs 'Starting alertManager...'
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )

        with patch(
            'pi.alert.createAlertManagerFromConfig'
        ) as mockFactory:
            mockFactory.return_value = MagicMock()

            # Act
            with caplog.at_level(logging.INFO):
                orchestrator._initializeAlertManager()

        # Assert
        assert any(
            'Starting alertManager' in record.message
            for record in caplog.records
        )

    def test_initializeAlertManager_raisesError_onFailure(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Factory raises an exception
        When: _initializeAlertManager() is called
        Then: ComponentInitializationError is raised
        """
        # Arrange
        from pi.obd.orchestrator import (
            ApplicationOrchestrator,
            ComponentInitializationError,
        )

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )

        with patch(
            'pi.alert.createAlertManagerFromConfig'
        ) as mockFactory:
            mockFactory.side_effect = RuntimeError("test error")

            # Act & Assert
            with pytest.raises(ComponentInitializationError):
                orchestrator._initializeAlertManager()


# ================================================================================
# AC2: Manager receives all realtime values from logger
# ================================================================================


class TestAlertManagerReceivesValues:
    """Tests that AlertManager receives all realtime values from the logger."""

    def test_handleReading_callsCheckValue_withParameterAndValue(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert manager wired
        When: _handleReading() is called with a reading
        Then: alertManager.checkValue() receives parameterName and value
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 5500.0

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockAlertManager.checkValue.assert_called_once_with('RPM', 5500.0)

    def test_handleReading_callsCheckValue_forCoolantTemp(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert manager wired
        When: _handleReading() receives COOLANT_TEMP reading
        Then: alertManager.checkValue() is called with COOLANT_TEMP
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager

        mockReading = MagicMock()
        mockReading.parameterName = 'COOLANT_TEMP'
        mockReading.value = 98.0

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockAlertManager.checkValue.assert_called_once_with(
            'COOLANT_TEMP', 98.0
        )

    def test_handleReading_skipsCheckValue_whenAlertManagerIsNone(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with no alert manager
        When: _handleReading() is called
        Then: No error occurs (graceful degradation)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        orchestrator._alertManager = None

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 7000.0

        # Act (should not raise)
        orchestrator._handleReading(mockReading)

    def test_handleReading_skipsCheckValue_whenValueIsNone(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: Orchestrator with alert manager
        When: _handleReading() receives None value
        Then: checkValue is NOT called
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockAlertManager = MagicMock()
        orchestrator._alertManager = mockAlertManager

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = None

        # Act
        orchestrator._handleReading(mockReading)

        # Assert
        mockAlertManager.checkValue.assert_not_called()

    def test_handleReading_continuesOnCheckValueError(
        self, alertConfig: dict[str, Any]
    ):
        """
        Given: alertManager.checkValue() raises an exception
        When: _handleReading() is called
        Then: No exception propagates (error is caught and logged)
        """
        # Arrange
        from pi.obd.orchestrator import ApplicationOrchestrator

        orchestrator = ApplicationOrchestrator(
            config=alertConfig,
            simulate=True
        )
        mockAlertManager = MagicMock()
        mockAlertManager.checkValue.side_effect = RuntimeError("check failed")
        orchestrator._alertManager = mockAlertManager

        mockReading = MagicMock()
        mockReading.parameterName = 'RPM'
        mockReading.value = 5000.0

        # Act (should not raise)
        orchestrator._handleReading(mockReading)
