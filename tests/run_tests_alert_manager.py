#!/usr/bin/env python3
################################################################################
# File Name: run_tests_alert_manager.py
# Purpose/Description: Tests for the AlertManager threshold-based alert system
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-017 tests
# ================================================================================
################################################################################

"""
Comprehensive tests for the AlertManager module.

Tests cover:
- AlertThreshold dataclass
- AlertEvent dataclass
- AlertStats dataclass
- AlertManager initialization
- Threshold configuration
- Value checking and alert triggering
- Cooldown mechanism
- Visual alert integration
- Database logging
- Callbacks
- Statistics tracking
- Helper functions
"""

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.alert_manager import (
    AlertManager,
    AlertThreshold,
    AlertEvent,
    AlertStats,
    AlertDirection,
    AlertState,
    AlertError,
    AlertConfigurationError,
    AlertDatabaseError,
    createAlertManagerFromConfig,
    getAlertThresholdsForProfile,
    isAlertingEnabled,
    getDefaultThresholds,
    checkThresholdValue,
    ALERT_TYPE_RPM_REDLINE,
    ALERT_TYPE_COOLANT_TEMP_CRITICAL,
    ALERT_TYPE_BOOST_PRESSURE_MAX,
    ALERT_TYPE_OIL_PRESSURE_LOW,
    DEFAULT_COOLDOWN_SECONDS,
    MIN_COOLDOWN_SECONDS,
    PARAMETER_ALERT_TYPES,
    THRESHOLD_KEY_TO_PARAMETER,
    ALERT_PRIORITIES,
)


# ================================================================================
# Test AlertThreshold
# ================================================================================

class TestAlertThreshold(unittest.TestCase):
    """Tests for AlertThreshold dataclass."""

    def test_init_basicThreshold(self):
        """Test basic threshold initialization."""
        threshold = AlertThreshold(
            parameterName='RPM',
            alertType=ALERT_TYPE_RPM_REDLINE,
            threshold=6500,
            direction=AlertDirection.ABOVE,
        )
        self.assertEqual(threshold.parameterName, 'RPM')
        self.assertEqual(threshold.alertType, ALERT_TYPE_RPM_REDLINE)
        self.assertEqual(threshold.threshold, 6500)
        self.assertEqual(threshold.direction, AlertDirection.ABOVE)
        self.assertEqual(threshold.priority, 3)  # default

    def test_init_withPriority(self):
        """Test threshold with custom priority."""
        threshold = AlertThreshold(
            parameterName='COOLANT_TEMP',
            alertType=ALERT_TYPE_COOLANT_TEMP_CRITICAL,
            threshold=110,
            direction=AlertDirection.ABOVE,
            priority=1,
        )
        self.assertEqual(threshold.priority, 1)

    def test_init_withMessage(self):
        """Test threshold with custom message."""
        threshold = AlertThreshold(
            parameterName='RPM',
            alertType=ALERT_TYPE_RPM_REDLINE,
            threshold=7000,
            direction=AlertDirection.ABOVE,
            message='Engine RPM critical!',
        )
        self.assertEqual(threshold.message, 'Engine RPM critical!')

    def test_init_defaultMessageAbove(self):
        """Test default message for ABOVE direction."""
        threshold = AlertThreshold(
            parameterName='RPM',
            alertType=ALERT_TYPE_RPM_REDLINE,
            threshold=6500,
            direction=AlertDirection.ABOVE,
        )
        self.assertEqual(threshold.message, 'RPM above 6500')

    def test_init_defaultMessageBelow(self):
        """Test default message for BELOW direction."""
        threshold = AlertThreshold(
            parameterName='OIL_PRESSURE',
            alertType=ALERT_TYPE_OIL_PRESSURE_LOW,
            threshold=20,
            direction=AlertDirection.BELOW,
        )
        self.assertEqual(threshold.message, 'OIL_PRESSURE below 20')

    def test_checkValue_aboveExceeded(self):
        """Test checkValue when value exceeds ABOVE threshold."""
        threshold = AlertThreshold(
            parameterName='RPM',
            alertType=ALERT_TYPE_RPM_REDLINE,
            threshold=6500,
            direction=AlertDirection.ABOVE,
        )
        self.assertTrue(threshold.checkValue(7000))
        self.assertFalse(threshold.checkValue(6500))  # Equal doesn't exceed
        self.assertFalse(threshold.checkValue(6000))

    def test_checkValue_belowExceeded(self):
        """Test checkValue when value exceeds BELOW threshold."""
        threshold = AlertThreshold(
            parameterName='OIL_PRESSURE',
            alertType=ALERT_TYPE_OIL_PRESSURE_LOW,
            threshold=20,
            direction=AlertDirection.BELOW,
        )
        self.assertTrue(threshold.checkValue(15))
        self.assertFalse(threshold.checkValue(20))  # Equal doesn't exceed
        self.assertFalse(threshold.checkValue(25))

    def test_toDict(self):
        """Test toDict serialization."""
        threshold = AlertThreshold(
            parameterName='RPM',
            alertType=ALERT_TYPE_RPM_REDLINE,
            threshold=6500,
            direction=AlertDirection.ABOVE,
            priority=2,
            message='RPM warning',
        )
        d = threshold.toDict()
        self.assertEqual(d['parameterName'], 'RPM')
        self.assertEqual(d['alertType'], ALERT_TYPE_RPM_REDLINE)
        self.assertEqual(d['threshold'], 6500)
        self.assertEqual(d['direction'], 'above')
        self.assertEqual(d['priority'], 2)
        self.assertEqual(d['message'], 'RPM warning')


# ================================================================================
# Test AlertEvent
# ================================================================================

class TestAlertEvent(unittest.TestCase):
    """Tests for AlertEvent dataclass."""

    def test_init_basicEvent(self):
        """Test basic event initialization."""
        event = AlertEvent(
            alertType=ALERT_TYPE_RPM_REDLINE,
            parameterName='RPM',
            value=7000,
            threshold=6500,
        )
        self.assertEqual(event.alertType, ALERT_TYPE_RPM_REDLINE)
        self.assertEqual(event.parameterName, 'RPM')
        self.assertEqual(event.value, 7000)
        self.assertEqual(event.threshold, 6500)
        self.assertIsNone(event.profileId)
        self.assertFalse(event.acknowledged)
        self.assertIsNotNone(event.timestamp)

    def test_init_withProfile(self):
        """Test event with profile ID."""
        event = AlertEvent(
            alertType=ALERT_TYPE_COOLANT_TEMP_CRITICAL,
            parameterName='COOLANT_TEMP',
            value=115,
            threshold=110,
            profileId='performance',
        )
        self.assertEqual(event.profileId, 'performance')

    def test_init_withTimestamp(self):
        """Test event with explicit timestamp."""
        ts = datetime(2026, 1, 22, 12, 0, 0)
        event = AlertEvent(
            alertType=ALERT_TYPE_RPM_REDLINE,
            parameterName='RPM',
            value=7000,
            threshold=6500,
            timestamp=ts,
        )
        self.assertEqual(event.timestamp, ts)

    def test_toDict(self):
        """Test toDict serialization."""
        ts = datetime(2026, 1, 22, 12, 0, 0)
        event = AlertEvent(
            alertType=ALERT_TYPE_RPM_REDLINE,
            parameterName='RPM',
            value=7000,
            threshold=6500,
            profileId='daily',
            timestamp=ts,
        )
        d = event.toDict()
        self.assertEqual(d['alertType'], ALERT_TYPE_RPM_REDLINE)
        self.assertEqual(d['parameterName'], 'RPM')
        self.assertEqual(d['value'], 7000)
        self.assertEqual(d['threshold'], 6500)
        self.assertEqual(d['profileId'], 'daily')
        self.assertEqual(d['timestamp'], '2026-01-22T12:00:00')
        self.assertFalse(d['acknowledged'])


# ================================================================================
# Test AlertStats
# ================================================================================

class TestAlertStats(unittest.TestCase):
    """Tests for AlertStats dataclass."""

    def test_init_defaults(self):
        """Test default stats initialization."""
        stats = AlertStats()
        self.assertEqual(stats.totalChecks, 0)
        self.assertEqual(stats.alertsTriggered, 0)
        self.assertEqual(stats.alertsSuppressed, 0)
        self.assertEqual(stats.alertsByType, {})
        self.assertIsNone(stats.lastAlertTime)

    def test_init_withValues(self):
        """Test stats with explicit values."""
        ts = datetime.now()
        stats = AlertStats(
            totalChecks=100,
            alertsTriggered=5,
            alertsSuppressed=3,
            alertsByType={'rpm_redline': 3, 'coolant_temp_critical': 2},
            lastAlertTime=ts,
        )
        self.assertEqual(stats.totalChecks, 100)
        self.assertEqual(stats.alertsTriggered, 5)
        self.assertEqual(stats.alertsByType['rpm_redline'], 3)
        self.assertEqual(stats.lastAlertTime, ts)

    def test_toDict(self):
        """Test toDict serialization."""
        ts = datetime(2026, 1, 22, 12, 0, 0)
        stats = AlertStats(
            totalChecks=50,
            alertsTriggered=2,
            alertsSuppressed=1,
            alertsByType={'rpm_redline': 2},
            lastAlertTime=ts,
        )
        d = stats.toDict()
        self.assertEqual(d['totalChecks'], 50)
        self.assertEqual(d['alertsTriggered'], 2)
        self.assertEqual(d['alertsSuppressed'], 1)
        self.assertEqual(d['alertsByType'], {'rpm_redline': 2})
        self.assertEqual(d['lastAlertTime'], '2026-01-22T12:00:00')


# ================================================================================
# Test AlertManager Initialization
# ================================================================================

class TestAlertManagerInit(unittest.TestCase):
    """Tests for AlertManager initialization."""

    def test_init_defaults(self):
        """Test initialization with defaults."""
        manager = AlertManager()
        self.assertIsNone(manager._database)
        self.assertIsNone(manager._displayManager)
        self.assertEqual(manager._cooldownSeconds, DEFAULT_COOLDOWN_SECONDS)
        self.assertTrue(manager._enabled)
        self.assertTrue(manager._visualAlerts)
        self.assertTrue(manager._logAlerts)
        self.assertEqual(manager._state, AlertState.STOPPED)

    def test_init_withParameters(self):
        """Test initialization with custom parameters."""
        mockDb = MagicMock()
        mockDisplay = MagicMock()
        manager = AlertManager(
            database=mockDb,
            displayManager=mockDisplay,
            cooldownSeconds=60,
            enabled=False,
            visualAlerts=False,
            logAlerts=False,
        )
        self.assertEqual(manager._database, mockDb)
        self.assertEqual(manager._displayManager, mockDisplay)
        self.assertEqual(manager._cooldownSeconds, 60)
        self.assertFalse(manager._enabled)
        self.assertFalse(manager._visualAlerts)
        self.assertFalse(manager._logAlerts)

    def test_init_minimumCooldown(self):
        """Test that cooldown is enforced to minimum."""
        manager = AlertManager(cooldownSeconds=0)
        self.assertEqual(manager._cooldownSeconds, MIN_COOLDOWN_SECONDS)

    def test_setDatabase(self):
        """Test setDatabase method."""
        manager = AlertManager()
        mockDb = MagicMock()
        manager.setDatabase(mockDb)
        self.assertEqual(manager._database, mockDb)

    def test_setDisplayManager(self):
        """Test setDisplayManager method."""
        manager = AlertManager()
        mockDisplay = MagicMock()
        manager.setDisplayManager(mockDisplay)
        self.assertEqual(manager._displayManager, mockDisplay)

    def test_setCooldown(self):
        """Test setCooldown method."""
        manager = AlertManager()
        manager.setCooldown(45)
        self.assertEqual(manager._cooldownSeconds, 45)

    def test_setCooldown_enforceMinimum(self):
        """Test setCooldown enforces minimum."""
        manager = AlertManager()
        manager.setCooldown(0)
        self.assertEqual(manager._cooldownSeconds, MIN_COOLDOWN_SECONDS)


# ================================================================================
# Test AlertManager Lifecycle
# ================================================================================

class TestAlertManagerLifecycle(unittest.TestCase):
    """Tests for AlertManager start/stop lifecycle."""

    def test_start(self):
        """Test starting the alert manager."""
        manager = AlertManager()
        result = manager.start()
        self.assertTrue(result)
        self.assertEqual(manager._state, AlertState.RUNNING)
        self.assertTrue(manager.isRunning())

    def test_start_alreadyRunning(self):
        """Test starting when already running."""
        manager = AlertManager()
        manager.start()
        result = manager.start()  # Second call
        self.assertTrue(result)
        self.assertEqual(manager._state, AlertState.RUNNING)

    def test_stop(self):
        """Test stopping the alert manager."""
        manager = AlertManager()
        manager.start()
        manager.stop()
        self.assertEqual(manager._state, AlertState.STOPPED)
        self.assertFalse(manager.isRunning())

    def test_getState(self):
        """Test getState method."""
        manager = AlertManager()
        self.assertEqual(manager.getState(), AlertState.STOPPED)
        manager.start()
        self.assertEqual(manager.getState(), AlertState.RUNNING)
        manager.stop()
        self.assertEqual(manager.getState(), AlertState.STOPPED)


# ================================================================================
# Test AlertManager Threshold Configuration
# ================================================================================

class TestAlertManagerThresholds(unittest.TestCase):
    """Tests for AlertManager threshold configuration."""

    def test_setProfileThresholds(self):
        """Test setting thresholds for a profile."""
        manager = AlertManager()
        thresholds = {
            'rpmRedline': 6500,
            'coolantTempCritical': 110,
        }
        manager.setProfileThresholds('daily', thresholds)

        profileThresholds = manager.getThresholdsForProfile('daily')
        self.assertEqual(len(profileThresholds), 2)

        # Check RPM threshold
        rpmThreshold = next(
            (t for t in profileThresholds if t.parameterName == 'RPM'),
            None
        )
        self.assertIsNotNone(rpmThreshold)
        self.assertEqual(rpmThreshold.threshold, 6500)
        self.assertEqual(rpmThreshold.direction, AlertDirection.ABOVE)

    def test_setProfileThresholds_oilPressure(self):
        """Test oil pressure threshold (BELOW direction)."""
        manager = AlertManager()
        manager.setProfileThresholds('daily', {'oilPressureLow': 20})

        thresholds = manager.getThresholdsForProfile('daily')
        self.assertEqual(len(thresholds), 1)

        oilThreshold = thresholds[0]
        self.assertEqual(oilThreshold.parameterName, 'OIL_PRESSURE')
        self.assertEqual(oilThreshold.direction, AlertDirection.BELOW)

    def test_setProfileThresholds_unknownKey(self):
        """Test handling of unknown threshold key."""
        manager = AlertManager()
        manager.setProfileThresholds('daily', {'unknownThreshold': 100})

        thresholds = manager.getThresholdsForProfile('daily')
        self.assertEqual(len(thresholds), 0)

    def test_setActiveProfile(self):
        """Test setting active profile."""
        manager = AlertManager()
        manager.setActiveProfile('performance')
        self.assertEqual(manager._activeProfileId, 'performance')

    def test_getActiveThresholds(self):
        """Test getting active profile thresholds."""
        manager = AlertManager()
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setProfileThresholds('performance', {'rpmRedline': 7200})
        manager.setActiveProfile('performance')

        activeThresholds = manager.getActiveThresholds()
        self.assertEqual(len(activeThresholds), 1)
        self.assertEqual(activeThresholds[0].threshold, 7200)

    def test_getActiveThresholds_noProfile(self):
        """Test getting active thresholds with no profile set."""
        manager = AlertManager()
        activeThresholds = manager.getActiveThresholds()
        self.assertEqual(activeThresholds, [])


# ================================================================================
# Test AlertManager Value Checking
# ================================================================================

class TestAlertManagerValueChecking(unittest.TestCase):
    """Tests for AlertManager value checking and alert triggering."""

    def setUp(self):
        """Set up test fixtures."""
        self.manager = AlertManager(cooldownSeconds=1)
        self.manager.setProfileThresholds('daily', {
            'rpmRedline': 6500,
            'coolantTempCritical': 110,
            'oilPressureLow': 20,
        })
        self.manager.setActiveProfile('daily')
        self.manager.start()

    def tearDown(self):
        """Clean up after tests."""
        self.manager.stop()

    def test_checkValue_triggersAlert(self):
        """Test that checkValue triggers alert when threshold exceeded."""
        event = self.manager.checkValue('RPM', 7000)
        self.assertIsNotNone(event)
        self.assertEqual(event.alertType, ALERT_TYPE_RPM_REDLINE)
        self.assertEqual(event.value, 7000)
        self.assertEqual(event.threshold, 6500)

    def test_checkValue_noAlert(self):
        """Test that checkValue returns None when threshold not exceeded."""
        event = self.manager.checkValue('RPM', 6000)
        self.assertIsNone(event)

    def test_checkValue_coolantTemp(self):
        """Test coolant temp alert."""
        event = self.manager.checkValue('COOLANT_TEMP', 115)
        self.assertIsNotNone(event)
        self.assertEqual(event.alertType, ALERT_TYPE_COOLANT_TEMP_CRITICAL)

    def test_checkValue_oilPressureLow(self):
        """Test oil pressure low alert (BELOW direction)."""
        event = self.manager.checkValue('OIL_PRESSURE', 15)
        self.assertIsNotNone(event)
        self.assertEqual(event.alertType, ALERT_TYPE_OIL_PRESSURE_LOW)

    def test_checkValue_notRunning(self):
        """Test that checkValue returns None when not running."""
        self.manager.stop()
        event = self.manager.checkValue('RPM', 7000)
        self.assertIsNone(event)

    def test_checkValue_disabled(self):
        """Test that checkValue returns None when disabled."""
        self.manager.setEnabled(False)
        event = self.manager.checkValue('RPM', 7000)
        self.assertIsNone(event)

    def test_checkValue_noProfile(self):
        """Test checkValue with no active profile."""
        manager = AlertManager()
        manager.start()
        event = manager.checkValue('RPM', 7000)
        self.assertIsNone(event)

    def test_checkValue_withExplicitProfile(self):
        """Test checkValue with explicit profile parameter."""
        event = self.manager.checkValue('RPM', 7000, profileId='daily')
        self.assertIsNotNone(event)
        self.assertEqual(event.profileId, 'daily')

    def test_checkValues_multiple(self):
        """Test checking multiple values at once."""
        values = {
            'RPM': 7000,  # Over threshold
            'COOLANT_TEMP': 100,  # Under threshold
        }
        events = self.manager.checkValues(values)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].parameterName, 'RPM')

    def test_checkValue_unknownParameter(self):
        """Test checkValue with unknown parameter."""
        event = self.manager.checkValue('UNKNOWN_PARAM', 9999)
        self.assertIsNone(event)


# ================================================================================
# Test AlertManager Cooldown
# ================================================================================

class TestAlertManagerCooldown(unittest.TestCase):
    """Tests for AlertManager cooldown mechanism."""

    def test_cooldown_suppressesRepeatedAlerts(self):
        """Test that cooldown suppresses repeated alerts."""
        manager = AlertManager(cooldownSeconds=60)
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        # First alert should trigger
        event1 = manager.checkValue('RPM', 7000)
        self.assertIsNotNone(event1)

        # Second alert should be suppressed
        event2 = manager.checkValue('RPM', 7500)
        self.assertIsNone(event2)

        # Check stats
        stats = manager.getStats()
        self.assertEqual(stats.alertsTriggered, 1)
        self.assertEqual(stats.alertsSuppressed, 1)

        manager.stop()

    def test_cooldown_allowsAfterExpiry(self):
        """Test that alerts are allowed after cooldown expires by clearing cooldowns."""
        manager = AlertManager(cooldownSeconds=60)  # Use long cooldown
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        # First alert
        event1 = manager.checkValue('RPM', 7000)
        self.assertIsNotNone(event1)

        # Clear cooldowns to simulate cooldown expiry
        manager.clearCooldowns()

        # Second alert should be allowed now
        event2 = manager.checkValue('RPM', 7500)
        self.assertIsNotNone(event2)

        manager.stop()

    def test_clearCooldowns(self):
        """Test clearing cooldowns."""
        manager = AlertManager(cooldownSeconds=60)
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        # Trigger alert
        manager.checkValue('RPM', 7000)

        # Clear cooldowns
        manager.clearCooldowns()

        # Should be able to trigger again
        event = manager.checkValue('RPM', 7500)
        self.assertIsNotNone(event)

        manager.stop()

    def test_cooldown_perAlertType(self):
        """Test that cooldown is per alert type."""
        manager = AlertManager(cooldownSeconds=60)
        manager.setProfileThresholds('daily', {
            'rpmRedline': 6500,
            'coolantTempCritical': 110,
        })
        manager.setActiveProfile('daily')
        manager.start()

        # Trigger RPM alert
        event1 = manager.checkValue('RPM', 7000)
        self.assertIsNotNone(event1)

        # Coolant alert should still trigger (different type)
        event2 = manager.checkValue('COOLANT_TEMP', 115)
        self.assertIsNotNone(event2)

        # Second RPM alert should be suppressed
        event3 = manager.checkValue('RPM', 7500)
        self.assertIsNone(event3)

        manager.stop()


# ================================================================================
# Test AlertManager Visual Alerts
# ================================================================================

class TestAlertManagerVisualAlerts(unittest.TestCase):
    """Tests for AlertManager visual alert integration."""

    def test_visualAlert_triggered(self):
        """Test that visual alert is shown on display."""
        mockDisplay = MagicMock()
        mockDisplay.showAlert = MagicMock()

        manager = AlertManager(
            displayManager=mockDisplay,
            visualAlerts=True,
            cooldownSeconds=1,
        )
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        manager.checkValue('RPM', 7000)

        mockDisplay.showAlert.assert_called_once()
        callArgs = mockDisplay.showAlert.call_args
        self.assertIn('message', callArgs.kwargs)
        self.assertIn('priority', callArgs.kwargs)

        manager.stop()

    def test_visualAlert_disabled(self):
        """Test that visual alerts can be disabled."""
        mockDisplay = MagicMock()
        mockDisplay.showAlert = MagicMock()

        manager = AlertManager(
            displayManager=mockDisplay,
            visualAlerts=False,
            cooldownSeconds=1,
        )
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        manager.checkValue('RPM', 7000)

        mockDisplay.showAlert.assert_not_called()

        manager.stop()

    def test_visualAlert_noDisplayManager(self):
        """Test handling when no display manager is set."""
        manager = AlertManager(
            displayManager=None,
            visualAlerts=True,
            cooldownSeconds=1,
        )
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        # Should not raise an error
        event = manager.checkValue('RPM', 7000)
        self.assertIsNotNone(event)

        manager.stop()


# ================================================================================
# Test AlertManager Database Logging
# ================================================================================

class TestAlertManagerDatabaseLogging(unittest.TestCase):
    """Tests for AlertManager database logging."""

    def test_logAlert_toDatabase(self):
        """Test that alerts are logged to database."""
        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)
        mockConn.cursor.return_value = mockCursor

        manager = AlertManager(
            database=mockDb,
            logAlerts=True,
            cooldownSeconds=1,
        )
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        manager.checkValue('RPM', 7000)

        mockCursor.execute.assert_called_once()
        # Check the INSERT statement was called
        callArgs = mockCursor.execute.call_args
        self.assertIn('INSERT INTO alert_log', callArgs[0][0])

        manager.stop()

    def test_logAlert_disabled(self):
        """Test that database logging can be disabled."""
        mockDb = MagicMock()

        manager = AlertManager(
            database=mockDb,
            logAlerts=False,
            cooldownSeconds=1,
        )
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        manager.checkValue('RPM', 7000)

        mockDb.connect.assert_not_called()

        manager.stop()

    def test_logAlert_databaseError(self):
        """Test handling of database errors during logging."""
        mockDb = MagicMock()
        mockDb.connect.side_effect = Exception("Database error")

        manager = AlertManager(
            database=mockDb,
            logAlerts=True,
            cooldownSeconds=1,
        )
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        # Should not raise, just log error
        event = manager.checkValue('RPM', 7000)
        self.assertIsNotNone(event)

        manager.stop()


# ================================================================================
# Test AlertManager Callbacks
# ================================================================================

class TestAlertManagerCallbacks(unittest.TestCase):
    """Tests for AlertManager callback support."""

    def test_onAlert_callback(self):
        """Test that onAlert callback is triggered."""
        manager = AlertManager(cooldownSeconds=1)
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        callbackData = []

        def callback(event):
            callbackData.append(event)

        manager.onAlert(callback)
        manager.checkValue('RPM', 7000)

        self.assertEqual(len(callbackData), 1)
        self.assertEqual(callbackData[0].value, 7000)

        manager.stop()

    def test_onAlert_multipleCallbacks(self):
        """Test multiple callbacks."""
        manager = AlertManager(cooldownSeconds=1)
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        callback1Data = []
        callback2Data = []

        manager.onAlert(lambda e: callback1Data.append(e))
        manager.onAlert(lambda e: callback2Data.append(e))
        manager.checkValue('RPM', 7000)

        self.assertEqual(len(callback1Data), 1)
        self.assertEqual(len(callback2Data), 1)

        manager.stop()

    def test_onAlert_callbackError(self):
        """Test handling of callback errors."""
        manager = AlertManager(cooldownSeconds=1)
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        def badCallback(event):
            raise Exception("Callback error")

        goodCallbackData = []

        manager.onAlert(badCallback)
        manager.onAlert(lambda e: goodCallbackData.append(e))

        # Should not raise, and good callback should still run
        event = manager.checkValue('RPM', 7000)
        self.assertIsNotNone(event)
        self.assertEqual(len(goodCallbackData), 1)

        manager.stop()


# ================================================================================
# Test AlertManager Statistics
# ================================================================================

class TestAlertManagerStatistics(unittest.TestCase):
    """Tests for AlertManager statistics tracking."""

    def test_stats_totalChecks(self):
        """Test totalChecks counter."""
        manager = AlertManager(cooldownSeconds=1)
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        manager.checkValue('RPM', 5000)
        manager.checkValue('RPM', 6000)
        manager.checkValue('RPM', 7000)

        stats = manager.getStats()
        self.assertEqual(stats.totalChecks, 3)

        manager.stop()

    def test_stats_alertsTriggered(self):
        """Test alertsTriggered counter."""
        manager = AlertManager(cooldownSeconds=60)  # Use long cooldown
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        manager.checkValue('RPM', 7000)
        manager.clearCooldowns()  # Clear to allow second alert
        manager.checkValue('RPM', 7500)

        stats = manager.getStats()
        self.assertEqual(stats.alertsTriggered, 2)

        manager.stop()

    def test_stats_alertsByType(self):
        """Test alertsByType counter."""
        manager = AlertManager(cooldownSeconds=1)  # Longer cooldown - we test different alert types
        manager.setProfileThresholds('daily', {
            'rpmRedline': 6500,
            'coolantTempCritical': 110,
        })
        manager.setActiveProfile('daily')
        manager.start()

        # Different alert types don't share cooldown, so no sleep needed
        manager.checkValue('RPM', 7000)
        manager.checkValue('COOLANT_TEMP', 115)

        stats = manager.getStats()
        self.assertEqual(stats.alertsByType[ALERT_TYPE_RPM_REDLINE], 1)
        self.assertEqual(stats.alertsByType[ALERT_TYPE_COOLANT_TEMP_CRITICAL], 1)

        manager.stop()

    def test_resetStats(self):
        """Test resetting statistics."""
        manager = AlertManager(cooldownSeconds=1)
        manager.setProfileThresholds('daily', {'rpmRedline': 6500})
        manager.setActiveProfile('daily')
        manager.start()

        manager.checkValue('RPM', 7000)
        manager.resetStats()

        stats = manager.getStats()
        self.assertEqual(stats.totalChecks, 0)
        self.assertEqual(stats.alertsTriggered, 0)

        manager.stop()


# ================================================================================
# Test Alert History
# ================================================================================

class TestAlertManagerHistory(unittest.TestCase):
    """Tests for AlertManager alert history methods."""

    def test_getAlertHistory_noDatabase(self):
        """Test getAlertHistory with no database."""
        manager = AlertManager()
        history = manager.getAlertHistory()
        self.assertEqual(history, [])

    def test_getAlertHistory_withResults(self):
        """Test getAlertHistory with database results."""
        mockDb = MagicMock()
        mockConn = MagicMock()
        mockCursor = MagicMock()
        mockDb.connect.return_value.__enter__ = MagicMock(return_value=mockConn)
        mockDb.connect.return_value.__exit__ = MagicMock(return_value=False)
        mockConn.cursor.return_value = mockCursor

        # Create mock rows with dict-like access
        mockRow = {'id': 1, 'alert_type': 'rpm_redline', 'value': 7000}
        mockCursor.fetchall.return_value = [mockRow]

        manager = AlertManager(database=mockDb)
        history = manager.getAlertHistory()

        self.assertEqual(len(history), 1)
        mockCursor.execute.assert_called_once()

    def test_getAlertCount_noDatabase(self):
        """Test getAlertCount with no database."""
        manager = AlertManager()
        count = manager.getAlertCount()
        self.assertEqual(count, 0)


# ================================================================================
# Test Helper Functions
# ================================================================================

class TestHelperFunctions(unittest.TestCase):
    """Tests for module helper functions."""

    def test_createAlertManagerFromConfig(self):
        """Test creating AlertManager from config."""
        config = {
            'alerts': {
                'enabled': True,
                'cooldownSeconds': 45,
                'visualAlerts': True,
                'logAlerts': False,
            },
            'profiles': {
                'activeProfile': 'daily',
                'availableProfiles': [
                    {
                        'id': 'daily',
                        'alertThresholds': {
                            'rpmRedline': 6500,
                            'coolantTempCritical': 110,
                        }
                    }
                ]
            }
        }

        manager = createAlertManagerFromConfig(config)

        self.assertTrue(manager._enabled)
        self.assertEqual(manager._cooldownSeconds, 45)
        self.assertTrue(manager._visualAlerts)
        self.assertFalse(manager._logAlerts)
        self.assertEqual(manager._activeProfileId, 'daily')

        thresholds = manager.getThresholdsForProfile('daily')
        self.assertEqual(len(thresholds), 2)

    def test_createAlertManagerFromConfig_defaults(self):
        """Test creating AlertManager with default config."""
        config = {}
        manager = createAlertManagerFromConfig(config)

        self.assertTrue(manager._enabled)
        self.assertEqual(manager._cooldownSeconds, DEFAULT_COOLDOWN_SECONDS)

    def test_getAlertThresholdsForProfile(self):
        """Test getting thresholds from config for a profile."""
        config = {
            'profiles': {
                'availableProfiles': [
                    {
                        'id': 'daily',
                        'alertThresholds': {
                            'rpmRedline': 6500,
                        }
                    },
                    {
                        'id': 'performance',
                        'alertThresholds': {
                            'rpmRedline': 7200,
                        }
                    }
                ]
            }
        }

        thresholds = getAlertThresholdsForProfile(config, 'daily')
        self.assertEqual(thresholds['rpmRedline'], 6500)

        thresholds = getAlertThresholdsForProfile(config, 'performance')
        self.assertEqual(thresholds['rpmRedline'], 7200)

        thresholds = getAlertThresholdsForProfile(config, 'nonexistent')
        self.assertEqual(thresholds, {})

    def test_isAlertingEnabled(self):
        """Test isAlertingEnabled function."""
        self.assertTrue(isAlertingEnabled({'alerts': {'enabled': True}}))
        self.assertFalse(isAlertingEnabled({'alerts': {'enabled': False}}))
        self.assertTrue(isAlertingEnabled({}))  # Default is enabled

    def test_getDefaultThresholds(self):
        """Test getDefaultThresholds function."""
        defaults = getDefaultThresholds()
        self.assertIn('rpmRedline', defaults)
        self.assertIn('coolantTempCritical', defaults)
        self.assertIn('boostPressureMax', defaults)
        self.assertIn('oilPressureLow', defaults)
        self.assertEqual(defaults['rpmRedline'], 6500)

    def test_checkThresholdValue_rpmExceeded(self):
        """Test checkThresholdValue for RPM."""
        thresholds = {'rpmRedline': 6500}
        result = checkThresholdValue('RPM', 7000, thresholds)
        self.assertEqual(result, ALERT_TYPE_RPM_REDLINE)

    def test_checkThresholdValue_rpmNotExceeded(self):
        """Test checkThresholdValue when not exceeded."""
        thresholds = {'rpmRedline': 6500}
        result = checkThresholdValue('RPM', 6000, thresholds)
        self.assertIsNone(result)

    def test_checkThresholdValue_oilPressureLow(self):
        """Test checkThresholdValue for oil pressure (BELOW)."""
        thresholds = {'oilPressureLow': 20}
        result = checkThresholdValue('OIL_PRESSURE', 15, thresholds)
        self.assertEqual(result, ALERT_TYPE_OIL_PRESSURE_LOW)

    def test_checkThresholdValue_unknownParameter(self):
        """Test checkThresholdValue with unknown parameter."""
        thresholds = {'rpmRedline': 6500}
        result = checkThresholdValue('UNKNOWN', 9999, thresholds)
        self.assertIsNone(result)


# ================================================================================
# Test Constants
# ================================================================================

class TestConstants(unittest.TestCase):
    """Tests for module constants."""

    def test_alertTypes(self):
        """Test alert type constants."""
        self.assertEqual(ALERT_TYPE_RPM_REDLINE, 'rpm_redline')
        self.assertEqual(ALERT_TYPE_COOLANT_TEMP_CRITICAL, 'coolant_temp_critical')
        self.assertEqual(ALERT_TYPE_BOOST_PRESSURE_MAX, 'boost_pressure_max')
        self.assertEqual(ALERT_TYPE_OIL_PRESSURE_LOW, 'oil_pressure_low')

    def test_parameterAlertTypes(self):
        """Test parameter to alert type mapping."""
        self.assertEqual(PARAMETER_ALERT_TYPES['RPM'], ALERT_TYPE_RPM_REDLINE)
        self.assertEqual(PARAMETER_ALERT_TYPES['COOLANT_TEMP'], ALERT_TYPE_COOLANT_TEMP_CRITICAL)
        self.assertEqual(PARAMETER_ALERT_TYPES['OIL_PRESSURE'], ALERT_TYPE_OIL_PRESSURE_LOW)

    def test_thresholdKeyToParameter(self):
        """Test threshold key to parameter mapping."""
        self.assertEqual(THRESHOLD_KEY_TO_PARAMETER['rpmRedline'], 'RPM')
        self.assertEqual(THRESHOLD_KEY_TO_PARAMETER['coolantTempCritical'], 'COOLANT_TEMP')
        self.assertEqual(THRESHOLD_KEY_TO_PARAMETER['oilPressureLow'], 'OIL_PRESSURE')

    def test_alertPriorities(self):
        """Test alert priorities."""
        self.assertEqual(ALERT_PRIORITIES[ALERT_TYPE_COOLANT_TEMP_CRITICAL], 1)
        self.assertEqual(ALERT_PRIORITIES[ALERT_TYPE_OIL_PRESSURE_LOW], 1)
        self.assertEqual(ALERT_PRIORITIES[ALERT_TYPE_RPM_REDLINE], 2)
        self.assertEqual(ALERT_PRIORITIES[ALERT_TYPE_BOOST_PRESSURE_MAX], 3)


# ================================================================================
# Test Exceptions
# ================================================================================

class TestExceptions(unittest.TestCase):
    """Tests for module exceptions."""

    def test_alertError(self):
        """Test AlertError exception."""
        error = AlertError("Test error", {'key': 'value'})
        self.assertEqual(str(error), "Test error")
        self.assertEqual(error.message, "Test error")
        self.assertEqual(error.details, {'key': 'value'})

    def test_alertError_noDetails(self):
        """Test AlertError without details."""
        error = AlertError("Test error")
        self.assertEqual(error.details, {})

    def test_alertConfigurationError(self):
        """Test AlertConfigurationError inheritance."""
        error = AlertConfigurationError("Config error")
        self.assertIsInstance(error, AlertError)

    def test_alertDatabaseError(self):
        """Test AlertDatabaseError inheritance."""
        error = AlertDatabaseError("DB error")
        self.assertIsInstance(error, AlertError)


# ================================================================================
# Test AlertDirection Enum
# ================================================================================

class TestAlertDirection(unittest.TestCase):
    """Tests for AlertDirection enum."""

    def test_values(self):
        """Test AlertDirection values."""
        self.assertEqual(AlertDirection.ABOVE.value, 'above')
        self.assertEqual(AlertDirection.BELOW.value, 'below')


# ================================================================================
# Test AlertState Enum
# ================================================================================

class TestAlertState(unittest.TestCase):
    """Tests for AlertState enum."""

    def test_values(self):
        """Test AlertState values."""
        self.assertEqual(AlertState.STOPPED.value, 'stopped')
        self.assertEqual(AlertState.RUNNING.value, 'running')
        self.assertEqual(AlertState.ERROR.value, 'error')


# ================================================================================
# Main
# ================================================================================

def runTests():
    """Run all tests and return result."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    testClasses = [
        TestAlertThreshold,
        TestAlertEvent,
        TestAlertStats,
        TestAlertManagerInit,
        TestAlertManagerLifecycle,
        TestAlertManagerThresholds,
        TestAlertManagerValueChecking,
        TestAlertManagerCooldown,
        TestAlertManagerVisualAlerts,
        TestAlertManagerDatabaseLogging,
        TestAlertManagerCallbacks,
        TestAlertManagerStatistics,
        TestAlertManagerHistory,
        TestHelperFunctions,
        TestConstants,
        TestExceptions,
        TestAlertDirection,
        TestAlertState,
    ]

    for testClass in testClasses:
        tests = loader.loadTestsFromTestCase(testClass)
        suite.addTests(tests)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == '__main__':
    result = runTests()

    # Print summary
    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
