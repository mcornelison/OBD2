#!/usr/bin/env python3
################################################################################
# File Name: run_tests_power_monitor.py
# Purpose/Description: Tests for the PowerMonitor 12V adapter disconnect detection
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-023 tests
# ================================================================================
################################################################################

"""
Comprehensive tests for the PowerMonitor module.

Tests cover:
- PowerReading dataclass
- PowerStats dataclass
- PowerMonitor initialization
- Configuration methods
- Power status reading
- Power transition handling (AC→Battery, Battery→AC)
- Power saving mode (reduced polling, display dim)
- Display integration
- Database logging
- Statistics tracking
- Callback support
- Helper functions
"""

import os
import sys
import tempfile
import time
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.power_monitor import (
    PowerMonitor,
    PowerReading,
    PowerStats,
    PowerSource,
    PowerMonitorState,
    PowerError,
    PowerConfigurationError,
    createPowerMonitorFromConfig,
    getPowerMonitoringConfig,
    isPowerMonitoringEnabled,
    createGpioPowerStatusReader,
    createI2cPowerStatusReader,
    DEFAULT_POLLING_INTERVAL_SECONDS,
    DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS,
    DEFAULT_DISPLAY_DIM_PERCENTAGE,
    POWER_LOG_EVENT_AC_POWER,
    POWER_LOG_EVENT_BATTERY_POWER,
    POWER_LOG_EVENT_TRANSITION_TO_BATTERY,
    POWER_LOG_EVENT_TRANSITION_TO_AC,
    POWER_LOG_EVENT_POWER_SAVING_ENABLED,
    POWER_LOG_EVENT_POWER_SAVING_DISABLED,
)


# ================================================================================
# Test PowerReading
# ================================================================================

class TestPowerReading(unittest.TestCase):
    """Tests for PowerReading dataclass."""

    def test_init_acPower(self):
        """Test AC power reading initialization."""
        reading = PowerReading(
            powerSource=PowerSource.AC_POWER,
            onAcPower=True,
            timestamp=datetime.now()
        )
        self.assertEqual(reading.powerSource, PowerSource.AC_POWER)
        self.assertTrue(reading.onAcPower)
        self.assertIsNotNone(reading.timestamp)

    def test_init_batteryPower(self):
        """Test battery power reading initialization."""
        reading = PowerReading(
            powerSource=PowerSource.BATTERY,
            onAcPower=False
        )
        self.assertEqual(reading.powerSource, PowerSource.BATTERY)
        self.assertFalse(reading.onAcPower)

    def test_init_defaultTimestamp(self):
        """Test default timestamp is set if not provided."""
        reading = PowerReading(powerSource=PowerSource.AC_POWER, onAcPower=True)
        self.assertIsNotNone(reading.timestamp)
        self.assertIsInstance(reading.timestamp, datetime)

    def test_toDict_acPower(self):
        """Test conversion to dictionary for AC power."""
        now = datetime.now()
        reading = PowerReading(
            powerSource=PowerSource.AC_POWER,
            onAcPower=True,
            timestamp=now
        )
        result = reading.toDict()
        self.assertEqual(result['powerSource'], 'ac_power')
        self.assertTrue(result['onAcPower'])
        self.assertEqual(result['timestamp'], now.isoformat())

    def test_toDict_batteryPower(self):
        """Test conversion to dictionary for battery power."""
        now = datetime.now()
        reading = PowerReading(
            powerSource=PowerSource.BATTERY,
            onAcPower=False,
            timestamp=now
        )
        result = reading.toDict()
        self.assertEqual(result['powerSource'], 'battery')
        self.assertFalse(result['onAcPower'])


# ================================================================================
# Test PowerStats
# ================================================================================

class TestPowerStats(unittest.TestCase):
    """Tests for PowerStats dataclass."""

    def test_init_defaults(self):
        """Test default initialization."""
        stats = PowerStats()
        self.assertEqual(stats.totalReadings, 0)
        self.assertEqual(stats.acPowerReadings, 0)
        self.assertEqual(stats.batteryReadings, 0)
        self.assertEqual(stats.transitionsToBattery, 0)
        self.assertEqual(stats.transitionsToAc, 0)
        self.assertIsNone(stats.lastTransitionTime)
        self.assertEqual(stats.totalBatteryTimeSeconds, 0.0)
        self.assertIsNone(stats.lastReading)

    def test_toDict(self):
        """Test conversion to dictionary."""
        now = datetime.now()
        stats = PowerStats(
            totalReadings=100,
            acPowerReadings=80,
            batteryReadings=20,
            transitionsToBattery=5,
            transitionsToAc=5,
            lastTransitionTime=now,
            totalBatteryTimeSeconds=3600.0,
            lastReading=PowerSource.AC_POWER,
        )
        result = stats.toDict()
        self.assertEqual(result['totalReadings'], 100)
        self.assertEqual(result['acPowerReadings'], 80)
        self.assertEqual(result['batteryReadings'], 20)
        self.assertEqual(result['transitionsToBattery'], 5)
        self.assertEqual(result['transitionsToAc'], 5)
        self.assertEqual(result['lastTransitionTime'], now.isoformat())
        self.assertEqual(result['totalBatteryTimeSeconds'], 3600.0)
        self.assertEqual(result['lastReading'], 'ac_power')


# ================================================================================
# Test PowerSource Enum
# ================================================================================

class TestPowerSourceEnum(unittest.TestCase):
    """Tests for PowerSource enum."""

    def test_values(self):
        """Test enum values."""
        self.assertEqual(PowerSource.UNKNOWN.value, 'unknown')
        self.assertEqual(PowerSource.AC_POWER.value, 'ac_power')
        self.assertEqual(PowerSource.BATTERY.value, 'battery')


# ================================================================================
# Test PowerMonitorState Enum
# ================================================================================

class TestPowerMonitorStateEnum(unittest.TestCase):
    """Tests for PowerMonitorState enum."""

    def test_values(self):
        """Test enum values."""
        self.assertEqual(PowerMonitorState.STOPPED.value, 'stopped')
        self.assertEqual(PowerMonitorState.RUNNING.value, 'running')
        self.assertEqual(PowerMonitorState.POWER_SAVING.value, 'power_saving')
        self.assertEqual(PowerMonitorState.ERROR.value, 'error')


# ================================================================================
# Test PowerMonitor Initialization
# ================================================================================

class TestPowerMonitorInit(unittest.TestCase):
    """Tests for PowerMonitor initialization."""

    def test_init_defaults(self):
        """Test default initialization."""
        monitor = PowerMonitor()
        self.assertEqual(monitor._pollingIntervalSeconds, DEFAULT_POLLING_INTERVAL_SECONDS)
        self.assertEqual(monitor._reducedPollingIntervalSeconds, DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS)
        self.assertEqual(monitor._displayDimPercentage, DEFAULT_DISPLAY_DIM_PERCENTAGE)
        self.assertTrue(monitor._enabled)
        self.assertEqual(monitor.getState(), PowerMonitorState.STOPPED)
        self.assertEqual(monitor.getCurrentPowerSource(), PowerSource.UNKNOWN)

    def test_init_customValues(self):
        """Test initialization with custom values."""
        monitor = PowerMonitor(
            pollingIntervalSeconds=10,
            reducedPollingIntervalSeconds=60,
            displayDimPercentage=50,
        )
        self.assertEqual(monitor._pollingIntervalSeconds, 10)
        self.assertEqual(monitor._reducedPollingIntervalSeconds, 60)
        self.assertEqual(monitor._displayDimPercentage, 50)

    def test_init_disabled(self):
        """Test initialization in disabled state."""
        monitor = PowerMonitor(enabled=False)
        self.assertFalse(monitor._enabled)

    def test_init_withDependencies(self):
        """Test initialization with database and display manager."""
        mockDb = MagicMock()
        mockDisplay = MagicMock()
        mockBattery = MagicMock()

        monitor = PowerMonitor(
            database=mockDb,
            displayManager=mockDisplay,
            batteryMonitor=mockBattery,
        )
        self.assertEqual(monitor._database, mockDb)
        self.assertEqual(monitor._displayManager, mockDisplay)
        self.assertEqual(monitor._batteryMonitor, mockBattery)

    def test_init_minimumPollingInterval(self):
        """Test minimum polling interval is enforced."""
        monitor = PowerMonitor(pollingIntervalSeconds=0.1)
        self.assertEqual(monitor._pollingIntervalSeconds, 1)  # Minimum is 1 second

    def test_init_displayDimPercentageBounds(self):
        """Test display dim percentage is clamped to valid range."""
        monitor1 = PowerMonitor(displayDimPercentage=-10)
        self.assertEqual(monitor1._displayDimPercentage, 0)

        monitor2 = PowerMonitor(displayDimPercentage=150)
        self.assertEqual(monitor2._displayDimPercentage, 100)


# ================================================================================
# Test PowerMonitor Configuration
# ================================================================================

class TestPowerMonitorConfiguration(unittest.TestCase):
    """Tests for PowerMonitor configuration methods."""

    def test_setDatabase(self):
        """Test setting database."""
        monitor = PowerMonitor()
        mockDb = MagicMock()
        monitor.setDatabase(mockDb)
        self.assertEqual(monitor._database, mockDb)

    def test_setDisplayManager(self):
        """Test setting display manager."""
        monitor = PowerMonitor()
        mockDisplay = MagicMock()
        monitor.setDisplayManager(mockDisplay)
        self.assertEqual(monitor._displayManager, mockDisplay)

    def test_setBatteryMonitor(self):
        """Test setting battery monitor."""
        monitor = PowerMonitor()
        mockBattery = MagicMock()
        monitor.setBatteryMonitor(mockBattery)
        self.assertEqual(monitor._batteryMonitor, mockBattery)

    def test_setPollingInterval(self):
        """Test setting polling interval."""
        monitor = PowerMonitor()
        monitor.setPollingInterval(15)
        self.assertEqual(monitor._pollingIntervalSeconds, 15)

    def test_setPollingInterval_minimum(self):
        """Test polling interval minimum is enforced."""
        monitor = PowerMonitor()
        monitor.setPollingInterval(0.5)
        self.assertEqual(monitor._pollingIntervalSeconds, 1)

    def test_setReducedPollingInterval(self):
        """Test setting reduced polling interval."""
        monitor = PowerMonitor()
        monitor.setReducedPollingInterval(45)
        self.assertEqual(monitor._reducedPollingIntervalSeconds, 45)

    def test_setDisplayDimPercentage(self):
        """Test setting display dim percentage."""
        monitor = PowerMonitor()
        monitor.setDisplayDimPercentage(40)
        self.assertEqual(monitor._displayDimPercentage, 40)

    def test_setEnabled(self):
        """Test enabling/disabling monitor."""
        monitor = PowerMonitor(enabled=False)
        self.assertFalse(monitor._enabled)
        monitor.setEnabled(True)
        self.assertTrue(monitor._enabled)

    def test_setPowerStatusReader(self):
        """Test setting power status reader."""
        monitor = PowerMonitor()
        reader = lambda: True
        monitor.setPowerStatusReader(reader)
        self.assertEqual(monitor._powerStatusReader, reader)


# ================================================================================
# Test PowerMonitor Lifecycle
# ================================================================================

class TestPowerMonitorLifecycle(unittest.TestCase):
    """Tests for PowerMonitor lifecycle methods."""

    def test_start(self):
        """Test starting the monitor."""
        monitor = PowerMonitor()
        result = monitor.start()
        self.assertTrue(result)
        self.assertEqual(monitor.getState(), PowerMonitorState.RUNNING)
        self.assertTrue(monitor.isRunning())
        monitor.stop()

    def test_start_alreadyRunning(self):
        """Test starting when already running."""
        monitor = PowerMonitor()
        monitor.start()
        result = monitor.start()  # Should return True without error
        self.assertTrue(result)
        monitor.stop()

    def test_stop(self):
        """Test stopping the monitor."""
        monitor = PowerMonitor()
        monitor.start()
        monitor.stop()
        self.assertEqual(monitor.getState(), PowerMonitorState.STOPPED)
        self.assertFalse(monitor.isRunning())

    def test_stop_alreadyStopped(self):
        """Test stopping when already stopped."""
        monitor = PowerMonitor()
        monitor.stop()  # Should not raise
        self.assertEqual(monitor.getState(), PowerMonitorState.STOPPED)


# ================================================================================
# Test Power Status Reading
# ================================================================================

class TestPowerStatusReading(unittest.TestCase):
    """Tests for power status reading."""

    def test_readPowerStatus_noReader(self):
        """Test reading power status without a reader configured."""
        monitor = PowerMonitor()
        result = monitor.readPowerStatus()
        self.assertIsNone(result)

    def test_readPowerStatus_acPower(self):
        """Test reading AC power status."""
        monitor = PowerMonitor()
        monitor.setPowerStatusReader(lambda: True)
        result = monitor.readPowerStatus()
        self.assertTrue(result)

    def test_readPowerStatus_batteryPower(self):
        """Test reading battery power status."""
        monitor = PowerMonitor()
        monitor.setPowerStatusReader(lambda: False)
        result = monitor.readPowerStatus()
        self.assertFalse(result)

    def test_readPowerStatus_readerError(self):
        """Test handling reader error."""
        monitor = PowerMonitor()

        def errorReader():
            raise RuntimeError("Read error")

        monitor.setPowerStatusReader(errorReader)
        result = monitor.readPowerStatus()
        self.assertIsNone(result)


# ================================================================================
# Test Power Status Checking
# ================================================================================

class TestPowerStatusChecking(unittest.TestCase):
    """Tests for checking power status."""

    def test_checkPowerStatus_acPower(self):
        """Test checking AC power status."""
        monitor = PowerMonitor()
        reading = monitor.checkPowerStatus(onAcPower=True)
        self.assertIsNotNone(reading)
        self.assertEqual(reading.powerSource, PowerSource.AC_POWER)
        self.assertTrue(reading.onAcPower)
        self.assertEqual(monitor.getCurrentPowerSource(), PowerSource.AC_POWER)

    def test_checkPowerStatus_batteryPower(self):
        """Test checking battery power status."""
        monitor = PowerMonitor()
        reading = monitor.checkPowerStatus(onAcPower=False)
        self.assertIsNotNone(reading)
        self.assertEqual(reading.powerSource, PowerSource.BATTERY)
        self.assertFalse(reading.onAcPower)
        self.assertEqual(monitor.getCurrentPowerSource(), PowerSource.BATTERY)

    def test_checkPowerStatus_disabled(self):
        """Test checking power status when disabled."""
        monitor = PowerMonitor(enabled=False)
        reading = monitor.checkPowerStatus(onAcPower=True)
        self.assertIsNone(reading)

    def test_checkPowerStatus_updatesStats(self):
        """Test that checking power status updates statistics."""
        monitor = PowerMonitor()
        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=False)

        stats = monitor.getStats()
        self.assertEqual(stats.totalReadings, 3)
        self.assertEqual(stats.acPowerReadings, 2)
        self.assertEqual(stats.batteryReadings, 1)


# ================================================================================
# Test Power Transitions
# ================================================================================

class TestPowerTransitions(unittest.TestCase):
    """Tests for power source transitions."""

    def test_transition_acToBattery(self):
        """Test transition from AC to battery."""
        monitor = PowerMonitor()

        # Start on AC power
        monitor.checkPowerStatus(onAcPower=True)
        self.assertEqual(monitor.getCurrentPowerSource(), PowerSource.AC_POWER)

        # Transition to battery
        monitor.checkPowerStatus(onAcPower=False)
        self.assertEqual(monitor.getCurrentPowerSource(), PowerSource.BATTERY)

        stats = monitor.getStats()
        self.assertEqual(stats.transitionsToBattery, 1)
        self.assertEqual(stats.transitionsToAc, 0)

    def test_transition_batteryToAc(self):
        """Test transition from battery to AC."""
        monitor = PowerMonitor()

        # Start on battery
        monitor.checkPowerStatus(onAcPower=False)
        self.assertEqual(monitor.getCurrentPowerSource(), PowerSource.BATTERY)

        # Transition to AC
        monitor.checkPowerStatus(onAcPower=True)
        self.assertEqual(monitor.getCurrentPowerSource(), PowerSource.AC_POWER)

        stats = monitor.getStats()
        self.assertEqual(stats.transitionsToAc, 1)

    def test_transition_multipleTransitions(self):
        """Test multiple power transitions."""
        monitor = PowerMonitor()

        # AC -> Battery -> AC -> Battery
        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=False)  # Transition 1
        monitor.checkPowerStatus(onAcPower=True)   # Transition 2
        monitor.checkPowerStatus(onAcPower=False)  # Transition 3

        stats = monitor.getStats()
        self.assertEqual(stats.transitionsToBattery, 2)
        self.assertEqual(stats.transitionsToAc, 1)

    def test_transition_noTransitionOnSameSource(self):
        """Test no transition counted when power source doesn't change."""
        monitor = PowerMonitor()

        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=True)

        stats = monitor.getStats()
        self.assertEqual(stats.transitionsToBattery, 0)
        self.assertEqual(stats.transitionsToAc, 0)


# ================================================================================
# Test Power Saving Mode
# ================================================================================

class TestPowerSavingMode(unittest.TestCase):
    """Tests for power saving mode."""

    def test_powerSaving_enabledOnBatteryTransition(self):
        """Test power saving mode enabled when transitioning to battery."""
        monitor = PowerMonitor()

        # Start on AC
        monitor.checkPowerStatus(onAcPower=True)
        self.assertFalse(monitor.isPowerSavingEnabled())

        # Transition to battery - should enable power saving
        monitor.checkPowerStatus(onAcPower=False)
        self.assertTrue(monitor.isPowerSavingEnabled())
        self.assertEqual(monitor.getState(), PowerMonitorState.POWER_SAVING)

    def test_powerSaving_disabledOnAcTransition(self):
        """Test power saving mode disabled when transitioning to AC."""
        monitor = PowerMonitor()

        # Start on battery
        monitor.checkPowerStatus(onAcPower=False)

        # Transition to battery
        monitor.checkPowerStatus(onAcPower=True)

        # Now transition back to battery then AC
        monitor.checkPowerStatus(onAcPower=False)
        self.assertTrue(monitor.isPowerSavingEnabled())

        # Transition to AC - should disable power saving
        monitor.checkPowerStatus(onAcPower=True)
        self.assertFalse(monitor.isPowerSavingEnabled())
        self.assertEqual(monitor.getState(), PowerMonitorState.RUNNING)

    def test_powerSaving_reducesPollingOnBattery(self):
        """Test that polling is reduced when on battery."""
        monitor = PowerMonitor(
            pollingIntervalSeconds=5,
            reducedPollingIntervalSeconds=30,
        )
        mockBattery = MagicMock()
        mockBattery._pollingIntervalSeconds = 60
        monitor.setBatteryMonitor(mockBattery)

        # Start on AC then transition to battery
        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=False)

        # Battery monitor should have reduced polling interval
        mockBattery.setPollingInterval.assert_called()


# ================================================================================
# Test Display Integration
# ================================================================================

class TestDisplayIntegration(unittest.TestCase):
    """Tests for display manager integration."""

    def test_showsAlertOnBatteryTransition(self):
        """Test that alert is shown when transitioning to battery."""
        monitor = PowerMonitor()
        mockDisplay = MagicMock()
        monitor.setDisplayManager(mockDisplay)

        # Start on AC then transition to battery
        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=False)

        # Should show alert
        mockDisplay.showAlert.assert_called()
        call_args = mockDisplay.showAlert.call_args
        self.assertIn("BATTERY", call_args[1].get('message', call_args[0][0] if call_args[0] else ''))


# ================================================================================
# Test Database Logging
# ================================================================================

class TestDatabaseLogging(unittest.TestCase):
    """Tests for database logging."""

    def test_logsAcPowerReading(self):
        """Test logging AC power reading to database."""
        monitor = PowerMonitor()
        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)
        mockConn.cursor.return_value = mockCursor
        monitor.setDatabase(mockDb)

        monitor.checkPowerStatus(onAcPower=True)

        mockCursor.execute.assert_called()
        call_args = mockCursor.execute.call_args[0]
        self.assertIn("INSERT INTO power_log", call_args[0])

    def test_logsBatteryPowerReading(self):
        """Test logging battery power reading to database."""
        monitor = PowerMonitor()
        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)
        mockConn.cursor.return_value = mockCursor
        monitor.setDatabase(mockDb)

        monitor.checkPowerStatus(onAcPower=False)

        mockCursor.execute.assert_called()

    def test_logsTransitionEvents(self):
        """Test logging transition events to database."""
        monitor = PowerMonitor()
        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)
        mockConn.cursor.return_value = mockCursor
        monitor.setDatabase(mockDb)

        # Transition from AC to battery
        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=False)

        # Should have multiple calls (reading + transition + power saving)
        self.assertGreaterEqual(mockCursor.execute.call_count, 2)


# ================================================================================
# Test Statistics
# ================================================================================

class TestStatistics(unittest.TestCase):
    """Tests for statistics tracking."""

    def test_getStats_initial(self):
        """Test getting initial statistics."""
        monitor = PowerMonitor()
        stats = monitor.getStats()
        self.assertEqual(stats.totalReadings, 0)
        self.assertEqual(stats.acPowerReadings, 0)
        self.assertEqual(stats.batteryReadings, 0)

    def test_getStats_afterReadings(self):
        """Test statistics after readings."""
        monitor = PowerMonitor()

        # AC power readings
        for _ in range(5):
            monitor.checkPowerStatus(onAcPower=True)

        # Battery readings
        for _ in range(3):
            monitor.checkPowerStatus(onAcPower=False)

        stats = monitor.getStats()
        self.assertEqual(stats.totalReadings, 8)
        self.assertEqual(stats.acPowerReadings, 5)
        self.assertEqual(stats.batteryReadings, 3)

    def test_resetStats(self):
        """Test resetting statistics."""
        monitor = PowerMonitor()
        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=False)

        monitor.resetStats()
        stats = monitor.getStats()
        self.assertEqual(stats.totalReadings, 0)


# ================================================================================
# Test Callbacks
# ================================================================================

class TestCallbacks(unittest.TestCase):
    """Tests for callback support."""

    def test_onAcPower_callback(self):
        """Test AC power callback."""
        monitor = PowerMonitor()
        callback = MagicMock()
        monitor.onAcPower(callback)

        monitor.checkPowerStatus(onAcPower=True)
        callback.assert_called_once()
        reading = callback.call_args[0][0]
        self.assertTrue(reading.onAcPower)

    def test_onBatteryPower_callback(self):
        """Test battery power callback."""
        monitor = PowerMonitor()
        callback = MagicMock()
        monitor.onBatteryPower(callback)

        monitor.checkPowerStatus(onAcPower=False)
        callback.assert_called_once()
        reading = callback.call_args[0][0]
        self.assertFalse(reading.onAcPower)

    def test_onTransition_callback(self):
        """Test transition callback."""
        monitor = PowerMonitor()
        callback = MagicMock()
        monitor.onTransition(callback)

        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=False)

        callback.assert_called_once()
        args = callback.call_args[0]
        self.assertEqual(args[0], PowerSource.AC_POWER)
        self.assertEqual(args[1], PowerSource.BATTERY)

    def test_onReading_callback(self):
        """Test reading callback."""
        monitor = PowerMonitor()
        callback = MagicMock()
        monitor.onReading(callback)

        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=False)

        self.assertEqual(callback.call_count, 2)

    def test_callback_errorHandling(self):
        """Test that callback errors are handled gracefully."""
        monitor = PowerMonitor()

        def errorCallback(reading):
            raise RuntimeError("Callback error")

        monitor.onReading(errorCallback)

        # Should not raise
        monitor.checkPowerStatus(onAcPower=True)


# ================================================================================
# Test Status
# ================================================================================

class TestStatus(unittest.TestCase):
    """Tests for status reporting."""

    def test_getStatus(self):
        """Test getting status."""
        monitor = PowerMonitor()
        status = monitor.getStatus()

        self.assertEqual(status['state'], 'stopped')
        self.assertTrue(status['enabled'])
        self.assertEqual(status['currentPowerSource'], 'unknown')
        self.assertFalse(status['powerSavingEnabled'])
        self.assertIn('pollingIntervalSeconds', status)
        self.assertIn('reducedPollingIntervalSeconds', status)
        self.assertIn('displayDimPercentage', status)
        self.assertIn('stats', status)


# ================================================================================
# Test Helper Functions
# ================================================================================

class TestHelperFunctions(unittest.TestCase):
    """Tests for helper functions."""

    def test_createPowerMonitorFromConfig_defaults(self):
        """Test creating monitor from config with defaults."""
        config = {}
        monitor = createPowerMonitorFromConfig(config)
        self.assertFalse(monitor._enabled)  # Default is disabled
        self.assertEqual(monitor._pollingIntervalSeconds, DEFAULT_POLLING_INTERVAL_SECONDS)

    def test_createPowerMonitorFromConfig_custom(self):
        """Test creating monitor from config with custom values."""
        config = {
            'powerMonitoring': {
                'enabled': True,
                'pollingIntervalSeconds': 10,
                'reducedPollingIntervalSeconds': 60,
                'displayDimPercentage': 40,
            }
        }
        monitor = createPowerMonitorFromConfig(config)
        self.assertTrue(monitor._enabled)
        self.assertEqual(monitor._pollingIntervalSeconds, 10)
        self.assertEqual(monitor._reducedPollingIntervalSeconds, 60)
        self.assertEqual(monitor._displayDimPercentage, 40)

    def test_createPowerMonitorFromConfig_withDependencies(self):
        """Test creating monitor with dependencies."""
        config = {'powerMonitoring': {'enabled': True}}
        mockDb = MagicMock()
        mockDisplay = MagicMock()
        mockBattery = MagicMock()

        monitor = createPowerMonitorFromConfig(
            config,
            database=mockDb,
            displayManager=mockDisplay,
            batteryMonitor=mockBattery
        )
        self.assertEqual(monitor._database, mockDb)
        self.assertEqual(monitor._displayManager, mockDisplay)
        self.assertEqual(monitor._batteryMonitor, mockBattery)

    def test_getPowerMonitoringConfig(self):
        """Test getting power monitoring config section."""
        config = {
            'powerMonitoring': {
                'enabled': True,
                'pollingIntervalSeconds': 10,
            }
        }
        result = getPowerMonitoringConfig(config)
        self.assertEqual(result['enabled'], True)
        self.assertEqual(result['pollingIntervalSeconds'], 10)

    def test_getPowerMonitoringConfig_missing(self):
        """Test getting power monitoring config when section missing."""
        config = {}
        result = getPowerMonitoringConfig(config)
        self.assertEqual(result, {})

    def test_isPowerMonitoringEnabled_true(self):
        """Test checking if monitoring is enabled."""
        config = {'powerMonitoring': {'enabled': True}}
        self.assertTrue(isPowerMonitoringEnabled(config))

    def test_isPowerMonitoringEnabled_false(self):
        """Test checking if monitoring is disabled."""
        config = {'powerMonitoring': {'enabled': False}}
        self.assertFalse(isPowerMonitoringEnabled(config))

    def test_isPowerMonitoringEnabled_missing(self):
        """Test checking when config is missing."""
        config = {}
        self.assertFalse(isPowerMonitoringEnabled(config))


# ================================================================================
# Test GPIO Power Status Reader
# ================================================================================

class TestGpioPowerStatusReader(unittest.TestCase):
    """Tests for GPIO power status reader helper."""

    def test_createGpioPowerStatusReader_activeHigh(self):
        """Test creating GPIO reader with active high."""
        mockGpioRead = MagicMock(return_value=1)
        reader = createGpioPowerStatusReader(
            gpioPin=17,
            activeHigh=True,
            gpioReadFunction=mockGpioRead
        )
        result = reader()
        self.assertTrue(result)
        mockGpioRead.assert_called_with(17)

    def test_createGpioPowerStatusReader_activeLow(self):
        """Test creating GPIO reader with active low."""
        mockGpioRead = MagicMock(return_value=0)
        reader = createGpioPowerStatusReader(
            gpioPin=18,
            activeHigh=False,
            gpioReadFunction=mockGpioRead
        )
        result = reader()
        self.assertTrue(result)  # 0 with active low = on AC power

    def test_createGpioPowerStatusReader_noFunction(self):
        """Test GPIO reader without read function raises error."""
        reader = createGpioPowerStatusReader(gpioPin=17)
        with self.assertRaises(PowerConfigurationError):
            reader()


# ================================================================================
# Test I2C Power Status Reader
# ================================================================================

class TestI2cPowerStatusReader(unittest.TestCase):
    """Tests for I2C power status reader helper."""

    def test_createI2cPowerStatusReader(self):
        """Test creating I2C reader."""
        # Return value where bit 2 is set (0b00000100 = 4)
        mockI2cRead = MagicMock(return_value=0x04)
        reader = createI2cPowerStatusReader(
            i2cAddress=0x6B,
            powerRegister=0x00,
            acPowerBit=2,
            i2cReadFunction=mockI2cRead
        )
        result = reader()
        self.assertTrue(result)
        mockI2cRead.assert_called_with(0x6B, 0x00)

    def test_createI2cPowerStatusReader_bitNotSet(self):
        """Test I2C reader when power bit not set."""
        mockI2cRead = MagicMock(return_value=0x00)
        reader = createI2cPowerStatusReader(
            i2cAddress=0x6B,
            powerRegister=0x00,
            acPowerBit=2,
            i2cReadFunction=mockI2cRead
        )
        result = reader()
        self.assertFalse(result)

    def test_createI2cPowerStatusReader_noFunction(self):
        """Test I2C reader without read function raises error."""
        reader = createI2cPowerStatusReader(i2cAddress=0x6B)
        with self.assertRaises(PowerConfigurationError):
            reader()


# ================================================================================
# Test Exceptions
# ================================================================================

class TestExceptions(unittest.TestCase):
    """Tests for exception classes."""

    def test_powerError(self):
        """Test PowerError exception."""
        error = PowerError("Test error", details={'key': 'value'})
        self.assertEqual(str(error), "Test error")
        self.assertEqual(error.message, "Test error")
        self.assertEqual(error.details, {'key': 'value'})

    def test_powerConfigurationError(self):
        """Test PowerConfigurationError exception."""
        error = PowerConfigurationError("Config error")
        self.assertIsInstance(error, PowerError)
        self.assertEqual(str(error), "Config error")


# ================================================================================
# Test Battery Time Tracking
# ================================================================================

class TestBatteryTimeTracking(unittest.TestCase):
    """Tests for battery time tracking."""

    def test_batteryTime_accumulatesOnTransitions(self):
        """Test that battery time accumulates across transitions."""
        monitor = PowerMonitor()

        # Start on AC, transition to battery
        monitor.checkPowerStatus(onAcPower=True)
        monitor.checkPowerStatus(onAcPower=False)

        # Simulate time passing
        monitor._stats.batteryStartTime = datetime.now() - timedelta(seconds=60)

        # Transition back to AC
        monitor.checkPowerStatus(onAcPower=True)

        stats = monitor.getStats()
        self.assertGreaterEqual(stats.totalBatteryTimeSeconds, 59)


# ================================================================================
# Test Power History
# ================================================================================

class TestPowerHistory(unittest.TestCase):
    """Tests for power history retrieval."""

    def test_getPowerHistory_noDatabase(self):
        """Test getting power history without database."""
        monitor = PowerMonitor()
        result = monitor.getPowerHistory()
        self.assertEqual(result, [])

    def test_getPowerHistory_withDatabase(self):
        """Test getting power history with database."""
        monitor = PowerMonitor()
        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)
        mockConn.cursor.return_value = mockCursor
        mockCursor.fetchall.return_value = []
        monitor.setDatabase(mockDb)

        result = monitor.getPowerHistory(limit=50)
        self.assertEqual(result, [])
        mockCursor.execute.assert_called()


# ================================================================================
# Main Runner
# ================================================================================

def runTests():
    """Run all tests and print results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    testClasses = [
        TestPowerReading,
        TestPowerStats,
        TestPowerSourceEnum,
        TestPowerMonitorStateEnum,
        TestPowerMonitorInit,
        TestPowerMonitorConfiguration,
        TestPowerMonitorLifecycle,
        TestPowerStatusReading,
        TestPowerStatusChecking,
        TestPowerTransitions,
        TestPowerSavingMode,
        TestDisplayIntegration,
        TestDatabaseLogging,
        TestStatistics,
        TestCallbacks,
        TestStatus,
        TestHelperFunctions,
        TestGpioPowerStatusReader,
        TestI2cPowerStatusReader,
        TestExceptions,
        TestBatteryTimeTracking,
        TestPowerHistory,
    ]

    for testClass in testClasses:
        tests = loader.loadTestsFromTestCase(testClass)
        suite.addTests(tests)

    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 70)
    print("POWER MONITOR TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.wasSuccessful():
        print("\n[OK] All tests passed!")
    else:
        print("\n[FAIL] Some tests failed")
        if result.failures:
            print("\nFailures:")
            for test, trace in result.failures:
                print(f"  - {test}")
        if result.errors:
            print("\nErrors:")
            for test, trace in result.errors:
                print(f"  - {test}")

    return result.wasSuccessful()


if __name__ == '__main__':
    success = runTests()
    sys.exit(0 if success else 1)
