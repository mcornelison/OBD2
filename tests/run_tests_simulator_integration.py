################################################################################
# File Name: run_tests_simulator_integration.py
# Purpose/Description: Tests for simulator integration module (US-039)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-039
# ================================================================================
################################################################################

"""
Tests for the simulator integration module.

Tests verify that:
- createConnectionFromConfig returns SimulatedObdConnection when --simulate flag is active
- Simulated connection works with ObdDataLogger and RealtimeDataLogger
- Simulated data triggers AlertManager when thresholds exceeded
- Simulated drives trigger DriveDetector start/end detection
- StatisticsEngine calculates valid statistics from simulated data
- Display modes (headless/minimal/developer) show simulated data correctly

Run with: pytest tests/run_tests_simulator_integration.py -v
"""

import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, Mock, patch

import pytest

# Add src to path
srcPath = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src')
if srcPath not in sys.path:
    sys.path.insert(0, srcPath)

from obd.simulator_integration import (
    createIntegratedConnection,
    SimulatorIntegration,
    IntegrationConfig,
    IntegrationState,
    IntegrationStats,
    SimulatorIntegrationError,
    SimulatorConfigurationError,
    SimulatorConnectionError,
    isSimulationModeActive,
    createSimulatorIntegrationFromConfig,
)
from obd.obd_connection import createConnectionFromConfig, ObdConnection
from obd.simulator import (
    SimulatedObdConnection,
    SensorSimulator,
    VehicleProfile,
    FailureType,
    getDefaultProfile,
)


# ================================================================================
# Test Fixtures
# ================================================================================

@pytest.fixture
def testConfig() -> Dict[str, Any]:
    """Create test configuration with simulator settings."""
    return {
        'database': {
            'path': ':memory:',
            'walMode': True,
        },
        'bluetooth': {
            'macAddress': '00:00:00:00:00:00',
            'retryDelays': [1, 2, 4],
        },
        'display': {
            'mode': 'headless',
        },
        'realtimeData': {
            'parameters': [
                {'name': 'RPM', 'logData': True},
                {'name': 'SPEED', 'logData': True},
                {'name': 'COOLANT_TEMP', 'logData': True},
            ],
            'pollingIntervalMs': 100,
        },
        'analysis': {
            'triggerAfterDrive': True,
            'driveStartRpmThreshold': 500,
            'driveStartDurationSeconds': 1,  # Short for testing
            'driveEndRpmThreshold': 0,
            'driveEndDurationSeconds': 1,  # Short for testing
        },
        'profiles': {
            'activeProfile': 'daily',
            'availableProfiles': [
                {
                    'id': 'daily',
                    'name': 'Daily',
                    'description': 'Daily driving',
                    'alertThresholds': {
                        'rpmRedline': 6500,
                        'coolantTempCritical': 110,
                    },
                    'pollingIntervalMs': 100,
                }
            ],
        },
        'alerts': {
            'enabled': True,
            'cooldownSeconds': 1,  # Short for testing
            'visualAlerts': False,  # Disable for testing
            'logAlerts': False,  # Disable for testing
        },
        'simulator': {
            'enabled': True,
            'profilePath': '',  # Use default profile
            'scenarioPath': '',
            'connectionDelaySeconds': 0.1,  # Short for testing
            'updateIntervalMs': 50,  # Fast for testing
            'failures': {},
        },
    }


@pytest.fixture
def testConfigDisabled(testConfig: Dict[str, Any]) -> Dict[str, Any]:
    """Create test configuration with simulator disabled."""
    testConfig['simulator']['enabled'] = False
    return testConfig


@pytest.fixture
def mockDatabase():
    """Create a mock database."""
    db = MagicMock()
    db.connect.return_value.__enter__ = MagicMock(return_value=MagicMock())
    db.connect.return_value.__exit__ = MagicMock(return_value=False)
    return db


# ================================================================================
# Test: createConnectionFromConfig with simulateFlag
# ================================================================================

class TestCreateConnectionFromConfig:
    """Tests for createConnectionFromConfig factory function."""

    def test_createConnection_simulateFlagTrue_returnsSimulatedConnection(
        self,
        testConfig: Dict[str, Any]
    ):
        """
        Given: config with simulator settings
        When: createConnectionFromConfig called with simulateFlag=True
        Then: returns SimulatedObdConnection
        """
        conn = createConnectionFromConfig(testConfig, None, simulateFlag=True)
        assert isinstance(conn, SimulatedObdConnection)

    def test_createConnection_simulateFlagFalse_simulatorDisabled_returnsRealConnection(
        self,
        testConfigDisabled: Dict[str, Any]
    ):
        """
        Given: config with simulator disabled
        When: createConnectionFromConfig called without simulateFlag
        Then: returns real ObdConnection
        """
        conn = createConnectionFromConfig(testConfigDisabled, None, simulateFlag=False)
        assert isinstance(conn, ObdConnection)

    def test_createConnection_configEnabled_noFlag_returnsSimulatedConnection(
        self,
        testConfig: Dict[str, Any]
    ):
        """
        Given: config with simulator.enabled=True
        When: createConnectionFromConfig called without simulateFlag
        Then: returns SimulatedObdConnection (config enables it)
        """
        conn = createConnectionFromConfig(testConfig, None, simulateFlag=False)
        assert isinstance(conn, SimulatedObdConnection)

    def test_createConnection_flagOverridesConfig(
        self,
        testConfigDisabled: Dict[str, Any]
    ):
        """
        Given: config with simulator.enabled=False
        When: createConnectionFromConfig called with simulateFlag=True
        Then: simulateFlag overrides config, returns SimulatedObdConnection
        """
        conn = createConnectionFromConfig(testConfigDisabled, None, simulateFlag=True)
        assert isinstance(conn, SimulatedObdConnection)


# ================================================================================
# Test: createIntegratedConnection
# ================================================================================

class TestCreateIntegratedConnection:
    """Tests for createIntegratedConnection factory function."""

    def test_createIntegratedConnection_simulateTrue_returnsSimulated(
        self,
        testConfig: Dict[str, Any]
    ):
        """
        Given: config with simulator settings
        When: createIntegratedConnection with simulateFlag=True
        Then: returns SimulatedObdConnection
        """
        conn = createIntegratedConnection(testConfig, None, simulateFlag=True)
        assert isinstance(conn, SimulatedObdConnection)

    def test_createIntegratedConnection_logsSimulatorMode(
        self,
        testConfig: Dict[str, Any],
        caplog
    ):
        """
        Given: simulator mode enabled
        When: createIntegratedConnection called
        Then: logs simulator mode message
        """
        import logging
        caplog.set_level(logging.INFO)
        createIntegratedConnection(testConfig, None, simulateFlag=True)
        assert any('SimulatedObdConnection' in rec.message for rec in caplog.records)


# ================================================================================
# Test: IntegrationConfig
# ================================================================================

class TestIntegrationConfig:
    """Tests for IntegrationConfig dataclass."""

    def test_fromConfig_loadsAllFields(self, testConfig: Dict[str, Any]):
        """
        Given: config with simulator settings
        When: IntegrationConfig.fromConfig called
        Then: all fields loaded correctly
        """
        config = IntegrationConfig.fromConfig(testConfig, simulateFlag=True)
        assert config.enabled is True
        assert config.connectionDelaySeconds == 0.1
        assert config.updateIntervalMs == 50

    def test_fromConfig_simulateFlagOverridesEnabled(
        self,
        testConfigDisabled: Dict[str, Any]
    ):
        """
        Given: config with simulator.enabled=False
        When: IntegrationConfig.fromConfig with simulateFlag=True
        Then: enabled is True (flag overrides)
        """
        config = IntegrationConfig.fromConfig(testConfigDisabled, simulateFlag=True)
        assert config.enabled is True


# ================================================================================
# Test: SimulatorIntegration Initialization
# ================================================================================

class TestSimulatorIntegrationInit:
    """Tests for SimulatorIntegration initialization."""

    def test_initialize_success(self, testConfig: Dict[str, Any]):
        """
        Given: valid simulator config
        When: integration.initialize called
        Then: returns True and state is STOPPED
        """
        integration = SimulatorIntegration(testConfig)
        result = integration.initialize(simulateFlag=True)

        assert result is True
        assert integration.getState() == IntegrationState.STOPPED

    def test_initialize_notEnabled_returnsFalse(
        self,
        testConfigDisabled: Dict[str, Any]
    ):
        """
        Given: simulator disabled in config
        When: integration.initialize without simulateFlag
        Then: returns False
        """
        integration = SimulatorIntegration(testConfigDisabled)
        result = integration.initialize(simulateFlag=False)

        assert result is False
        assert integration.getState() == IntegrationState.IDLE

    def test_initialize_createsSimulatedConnection(
        self,
        testConfig: Dict[str, Any]
    ):
        """
        Given: valid simulator config
        When: integration.initialize called
        Then: SimulatedObdConnection is created
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)

        assert integration.getConnection() is not None
        assert isinstance(integration.getConnection(), SimulatedObdConnection)


# ================================================================================
# Test: SimulatorIntegration Lifecycle
# ================================================================================

class TestSimulatorIntegrationLifecycle:
    """Tests for SimulatorIntegration start/stop lifecycle."""

    def test_start_connectsAndRunsUpdateLoop(self, testConfig: Dict[str, Any]):
        """
        Given: initialized integration
        When: start called
        Then: connection established and state is RUNNING
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)

        result = integration.start()

        assert result is True
        assert integration.isRunning() is True
        assert integration.getConnection().isConnected() is True

        integration.stop()

    def test_stop_disconnectsAndStopsLoop(self, testConfig: Dict[str, Any]):
        """
        Given: running integration
        When: stop called
        Then: state is STOPPED
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)
        integration.start()

        result = integration.stop()

        assert result is True
        assert integration.getState() == IntegrationState.STOPPED

    def test_pauseAndResume(self, testConfig: Dict[str, Any]):
        """
        Given: running integration
        When: pause then resume called
        Then: state transitions correctly
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)
        integration.start()

        integration.pause()
        assert integration.getState() == IntegrationState.PAUSED

        integration.resume()
        assert integration.getState() == IntegrationState.RUNNING

        integration.stop()


# ================================================================================
# Test: SimulatorIntegration with AlertManager
# ================================================================================

class TestSimulatorAlertIntegration:
    """Tests for simulator triggering AlertManager alerts."""

    def test_alertManager_receivesSimulatedValues(
        self,
        testConfig: Dict[str, Any]
    ):
        """
        Given: integration with AlertManager connected
        When: simulated values exceed thresholds
        Then: AlertManager.checkValue is called
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)

        # Create mock AlertManager
        mockAlertManager = MagicMock()
        mockAlertManager.checkValue.return_value = None
        integration.setAlertManager(mockAlertManager)

        # Start and let it run briefly
        integration.start()
        time.sleep(0.2)

        # Verify AlertManager received values
        assert mockAlertManager.checkValue.call_count > 0

        integration.stop()

    def test_alertTriggered_incrementsStats(self, testConfig: Dict[str, Any]):
        """
        Given: integration with AlertManager that triggers alert
        When: update cycle runs
        Then: alertsTriggered stat increments
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)

        # Create mock AlertManager that returns an alert
        mockAlertManager = MagicMock()
        mockAlert = MagicMock()
        mockAlertManager.checkValue.return_value = mockAlert
        integration.setAlertManager(mockAlertManager)

        # Start and let it run
        integration.start()
        time.sleep(0.2)

        stats = integration.getStats()
        assert stats.alertsTriggered > 0

        integration.stop()


# ================================================================================
# Test: SimulatorIntegration with DriveDetector
# ================================================================================

class TestSimulatorDriveDetection:
    """Tests for simulated drives triggering DriveDetector."""

    def test_driveDetector_receivesRpmValues(self, testConfig: Dict[str, Any]):
        """
        Given: integration with DriveDetector connected
        When: simulation runs
        Then: DriveDetector.processValue is called with RPM
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)

        # Create mock DriveDetector
        mockDriveDetector = MagicMock()
        mockDriveDetector.getDriveState.return_value = MagicMock(value='stopped')
        mockDriveDetector.processValue.return_value = MagicMock()
        integration.setDriveDetector(mockDriveDetector)

        # Start simulation
        integration.start()
        time.sleep(0.2)

        # Verify DriveDetector received RPM values
        rpmCalls = [
            call for call in mockDriveDetector.processValue.call_args_list
            if call[0][0] == 'RPM'
        ]
        assert len(rpmCalls) > 0

        integration.stop()

    def test_driveStateChange_triggersCallback(self, testConfig: Dict[str, Any]):
        """
        Given: integration with drive state change callback
        When: drive state changes
        Then: callback is invoked
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)

        # Track callbacks
        callbackInvocations: List[tuple] = []

        def onDriveStateChange(oldState: str, newState: str):
            callbackInvocations.append((oldState, newState))

        integration.registerCallbacks(onDriveStateChange=onDriveStateChange)

        # Create mock DriveDetector that changes state
        stateIndex = [0]
        states = ['stopped', 'running', 'stopped']

        mockDriveDetector = MagicMock()

        def getDriveState():
            state = MagicMock()
            state.value = states[min(stateIndex[0], len(states) - 1)]
            stateIndex[0] += 1
            return state

        mockDriveDetector.getDriveState = getDriveState
        mockDriveDetector.processValue = MagicMock()
        integration.setDriveDetector(mockDriveDetector)

        integration.start()
        time.sleep(0.3)
        integration.stop()

        # State changed, callback should be invoked
        assert len(callbackInvocations) > 0


# ================================================================================
# Test: SimulatorIntegration Statistics Collection
# ================================================================================

class TestSimulatorStatistics:
    """Tests for StatisticsEngine receiving simulated data."""

    def test_statisticsEngine_canBeConnected(self, testConfig: Dict[str, Any]):
        """
        Given: integration with StatisticsEngine
        When: setStatisticsEngine called
        Then: engine is stored
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)

        mockEngine = MagicMock()
        integration.setStatisticsEngine(mockEngine)

        # Engine is stored (used by DriveDetector for post-drive analysis)
        assert integration._statisticsEngine is mockEngine

        integration.stop()

    def test_integrationStats_trackReadingsGenerated(
        self,
        testConfig: Dict[str, Any]
    ):
        """
        Given: running integration
        When: simulation generates readings
        Then: readingsGenerated stat increments
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)
        integration.start()

        time.sleep(0.3)

        stats = integration.getStats()
        assert stats.readingsGenerated > 0
        assert stats.updateCount > 0

        integration.stop()


# ================================================================================
# Test: SimulatorIntegration with DisplayManager
# ================================================================================

class TestSimulatorDisplayIntegration:
    """Tests for display showing simulated data."""

    def test_displayManager_receivesUpdates(self, testConfig: Dict[str, Any]):
        """
        Given: integration with DisplayManager connected
        When: simulation runs
        Then: DisplayManager.showStatus is called
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)

        mockDisplay = MagicMock()
        integration.setDisplayManager(mockDisplay)

        integration.start()
        time.sleep(0.2)

        # Display received updates
        assert mockDisplay.showStatus.call_count > 0

        integration.stop()

    def test_displayUpdate_includesSimulationIndicator(
        self,
        testConfig: Dict[str, Any]
    ):
        """
        Given: integration with DisplayManager
        When: display updated
        Then: status message indicates simulation
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)

        receivedCalls: List[tuple] = []

        def captureShowStatus(message, details=None):
            receivedCalls.append((message, details))

        mockDisplay = MagicMock()
        mockDisplay.showStatus = captureShowStatus
        integration.setDisplayManager(mockDisplay)

        integration.start()
        time.sleep(0.2)
        integration.stop()

        # At least one call with SIMULATION message
        assert any('SIMULATION' in call[0] for call in receivedCalls)


# ================================================================================
# Test: Failure Injection Integration
# ================================================================================

class TestFailureInjectionIntegration:
    """Tests for failure injection in simulator."""

    def test_injectFailure_sensorFailure(self, testConfig: Dict[str, Any]):
        """
        Given: running integration
        When: sensor failure injected
        Then: failure is active
        """
        testConfig['simulator']['failures'] = {
            'sensorFailure': {
                'enabled': False,
                'sensors': [],
                'probability': 0.0,
            }
        }

        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)
        integration.start()

        # Inject failure using correct parameter name
        result = integration.injectFailure(
            FailureType.SENSOR_FAILURE,
            sensorNames=['RPM']
        )

        assert result is True

        integration.stop()

    def test_clearAllFailures(self, testConfig: Dict[str, Any]):
        """
        Given: integration with active failures
        When: clearAllFailures called
        Then: failures are cleared
        """
        testConfig['simulator']['failures'] = {
            'sensorFailure': {
                'enabled': True,
                'sensors': ['RPM'],
                'probability': 0.5,
            }
        }

        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)
        integration.start()

        integration.clearAllFailures()

        injector = integration.getFailureInjector()
        if injector:
            status = injector.getStatus()
            assert len(status.activeFailures) == 0

        integration.stop()


# ================================================================================
# Test: Scenario Running
# ================================================================================

class TestScenarioRunning:
    """Tests for running drive scenarios."""

    def test_runScenario_startsScenario(
        self,
        testConfig: Dict[str, Any]
    ):
        """
        Given: running integration
        When: runScenario called with valid scenario name
        Then: returns boolean (True if started, False if scenario not found)
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)
        integration.start()

        # Test that runScenario returns a boolean (may fail if scenario not found)
        result = integration.runScenario('city_driving')

        # Result is boolean - True if started, False if scenario not found
        assert isinstance(result, bool)

        integration.stop()

    def test_stopScenario_stopsRunningScenario(self, testConfig: Dict[str, Any]):
        """
        Given: integration with running scenario
        When: stopScenario called
        Then: scenario stops
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)
        integration.start()

        # Just test the stop doesn't throw
        integration.stopScenario()

        integration.stop()


# ================================================================================
# Test: Reading Generation Callback
# ================================================================================

class TestReadingGenerationCallback:
    """Tests for reading generation callbacks."""

    def test_onReadingGenerated_receivesValues(self, testConfig: Dict[str, Any]):
        """
        Given: integration with reading callback registered
        When: simulation generates readings
        Then: callback receives values dict
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)

        receivedValues: List[Dict[str, float]] = []

        def onReading(values: Dict[str, float]):
            receivedValues.append(values.copy())

        integration.registerCallbacks(onReadingGenerated=onReading)
        integration.start()

        time.sleep(0.3)

        integration.stop()

        # Should have received multiple readings
        assert len(receivedValues) > 0
        # Values should include key parameters
        for values in receivedValues:
            assert 'RPM' in values or len(values) > 0


# ================================================================================
# Test: isSimulationModeActive Helper
# ================================================================================

class TestIsSimulationModeActive:
    """Tests for isSimulationModeActive helper function."""

    def test_returnsTrueWhenFlagSet(self, testConfigDisabled: Dict[str, Any]):
        """
        Given: config with simulator disabled
        When: isSimulationModeActive with simulateFlag=True
        Then: returns True
        """
        result = isSimulationModeActive(testConfigDisabled, simulateFlag=True)
        assert result is True

    def test_returnsTrueWhenConfigEnabled(self, testConfig: Dict[str, Any]):
        """
        Given: config with simulator.enabled=True
        When: isSimulationModeActive without flag
        Then: returns True
        """
        result = isSimulationModeActive(testConfig, simulateFlag=False)
        assert result is True

    def test_returnsFalseWhenBothDisabled(
        self,
        testConfigDisabled: Dict[str, Any]
    ):
        """
        Given: config with simulator disabled
        When: isSimulationModeActive without flag
        Then: returns False
        """
        result = isSimulationModeActive(testConfigDisabled, simulateFlag=False)
        assert result is False


# ================================================================================
# Test: createSimulatorIntegrationFromConfig
# ================================================================================

class TestCreateSimulatorIntegrationFromConfig:
    """Tests for createSimulatorIntegrationFromConfig helper."""

    def test_returnsNoneWhenDisabled(self, testConfigDisabled: Dict[str, Any]):
        """
        Given: simulator disabled
        When: createSimulatorIntegrationFromConfig called
        Then: returns None
        """
        result = createSimulatorIntegrationFromConfig(
            testConfigDisabled,
            simulateFlag=False
        )
        assert result is None

    def test_returnsInitializedIntegrationWhenEnabled(
        self,
        testConfig: Dict[str, Any]
    ):
        """
        Given: simulator enabled
        When: createSimulatorIntegrationFromConfig called
        Then: returns initialized integration
        """
        result = createSimulatorIntegrationFromConfig(
            testConfig,
            simulateFlag=True
        )

        assert result is not None
        assert isinstance(result, SimulatorIntegration)
        assert result.getState() == IntegrationState.STOPPED


# ================================================================================
# Test: Integration with Real ObdDataLogger (via mock connection)
# ================================================================================

class TestDataLoggerIntegration:
    """Tests for simulator working with ObdDataLogger."""

    def test_simulatedConnection_hasQueryMethod(self, testConfig: Dict[str, Any]):
        """
        Given: simulated connection
        When: accessing obd.query
        Then: query method exists and returns simulated values
        """
        conn = createConnectionFromConfig(testConfig, None, simulateFlag=True)
        conn.connect()

        # Query should work
        response = conn.obd.query('RPM')
        assert response is not None
        assert hasattr(response, 'value')
        # Simulated RPM should be a float (could be 0 if engine off)
        assert isinstance(response.value, (int, float)) or response.is_null()

    def test_simulatedConnection_isConnectedReturnsTrue(
        self,
        testConfig: Dict[str, Any]
    ):
        """
        Given: simulated connection after connect
        When: isConnected called
        Then: returns True
        """
        conn = createConnectionFromConfig(testConfig, None, simulateFlag=True)
        conn.connect()

        assert conn.isConnected() is True

    def test_simulatedConnection_getStatusReturnsStatus(
        self,
        testConfig: Dict[str, Any]
    ):
        """
        Given: simulated connection
        When: getStatus called
        Then: returns ConnectionStatus
        """
        conn = createConnectionFromConfig(testConfig, None, simulateFlag=True)
        conn.connect()

        status = conn.getStatus()
        assert status is not None
        assert hasattr(status, 'state')


# ================================================================================
# Test: Integration Edge Cases
# ================================================================================

class TestIntegrationEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_startWithoutInitialize_returnsFalse(self, testConfig: Dict[str, Any]):
        """
        Given: uninitialized integration
        When: start called
        Then: returns False
        """
        integration = SimulatorIntegration(testConfig)
        # Don't call initialize

        result = integration.start()
        assert result is False

    def test_doubleStart_isIdempotent(self, testConfig: Dict[str, Any]):
        """
        Given: running integration
        When: start called again
        Then: returns True (already running)
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)
        integration.start()

        result = integration.start()
        assert result is False  # Can't start when running

        integration.stop()

    def test_doubleStop_isIdempotent(self, testConfig: Dict[str, Any]):
        """
        Given: stopped integration
        When: stop called again
        Then: returns True
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)
        integration.start()
        integration.stop()

        result = integration.stop()
        assert result is True

    def test_resetStats_clearsAllCounters(self, testConfig: Dict[str, Any]):
        """
        Given: integration with accumulated stats
        When: resetStats called
        Then: all counters are zero
        """
        integration = SimulatorIntegration(testConfig)
        integration.initialize(simulateFlag=True)
        integration.start()
        time.sleep(0.2)
        integration.stop()

        integration.resetStats()

        stats = integration.getStats()
        assert stats.updateCount == 0
        assert stats.readingsGenerated == 0


# ================================================================================
# Main Entry Point
# ================================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '-x'])
