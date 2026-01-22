#!/usr/bin/env python3
################################################################################
# File Name: run_tests_display_manager.py
# Purpose/Description: Manual test runner for display manager module
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-007
# ================================================================================
################################################################################

"""
Manual test runner for display manager module.

This test runner works without pytest, using Python's built-in unittest.
It provides comprehensive tests for the display modes functionality.

Usage:
    python tests/run_tests_display_manager.py
"""

import io
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch, call

# Add src directory to path
srcPath = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if srcPath not in sys.path:
    sys.path.insert(0, srcPath)

from obd.display_manager import (
    DisplayMode,
    DisplayManager,
    StatusInfo,
    AlertInfo,
    HeadlessDisplayDriver,
    MinimalDisplayDriver,
    DeveloperDisplayDriver,
    BaseDisplayDriver,
    DisplayError,
    DisplayInitializationError,
    DisplayOutputError,
    createDisplayManagerFromConfig,
    getDisplayModeFromConfig,
    isDisplayAvailable,
    _NullDisplayAdapter,
)


class TestDisplayModeEnum(unittest.TestCase):
    """Tests for DisplayMode enum."""

    def test_enumValues_existWithCorrectStrings(self):
        """All display modes should have correct string values."""
        self.assertEqual(DisplayMode.HEADLESS.value, "headless")
        self.assertEqual(DisplayMode.MINIMAL.value, "minimal")
        self.assertEqual(DisplayMode.DEVELOPER.value, "developer")

    def test_fromString_validMode_returnsEnum(self):
        """fromString should convert valid strings to enum."""
        self.assertEqual(DisplayMode.fromString("headless"), DisplayMode.HEADLESS)
        self.assertEqual(DisplayMode.fromString("minimal"), DisplayMode.MINIMAL)
        self.assertEqual(DisplayMode.fromString("developer"), DisplayMode.DEVELOPER)

    def test_fromString_caseInsensitive_returnsEnum(self):
        """fromString should be case insensitive."""
        self.assertEqual(DisplayMode.fromString("HEADLESS"), DisplayMode.HEADLESS)
        self.assertEqual(DisplayMode.fromString("Minimal"), DisplayMode.MINIMAL)
        self.assertEqual(DisplayMode.fromString("DEVELOPER"), DisplayMode.DEVELOPER)

    def test_fromString_withWhitespace_handlesCorrectly(self):
        """fromString should handle whitespace."""
        self.assertEqual(DisplayMode.fromString("  headless  "), DisplayMode.HEADLESS)
        self.assertEqual(DisplayMode.fromString("minimal "), DisplayMode.MINIMAL)

    def test_fromString_invalidMode_raisesValueError(self):
        """fromString should raise ValueError for invalid mode."""
        with self.assertRaises(ValueError) as ctx:
            DisplayMode.fromString("invalid")
        self.assertIn("Invalid display mode", str(ctx.exception))
        self.assertIn("headless", str(ctx.exception))

    def test_isValid_validModes_returnsTrue(self):
        """isValid should return True for valid modes."""
        self.assertTrue(DisplayMode.isValid("headless"))
        self.assertTrue(DisplayMode.isValid("minimal"))
        self.assertTrue(DisplayMode.isValid("developer"))

    def test_isValid_invalidMode_returnsFalse(self):
        """isValid should return False for invalid modes."""
        self.assertFalse(DisplayMode.isValid("invalid"))
        self.assertFalse(DisplayMode.isValid(""))
        self.assertFalse(DisplayMode.isValid("full"))


class TestStatusInfo(unittest.TestCase):
    """Tests for StatusInfo dataclass."""

    def test_defaultValues_allFieldsHaveDefaults(self):
        """StatusInfo should have sensible defaults."""
        status = StatusInfo()
        self.assertEqual(status.connectionStatus, "Disconnected")
        self.assertEqual(status.databaseStatus, "Unknown")
        self.assertIsNone(status.currentRpm)
        self.assertIsNone(status.coolantTemp)
        self.assertEqual(status.activeAlerts, [])
        self.assertEqual(status.profileName, "daily")
        self.assertIsNone(status.timestamp)

    def test_customValues_allFieldsSet(self):
        """StatusInfo should accept custom values."""
        now = datetime.now()
        status = StatusInfo(
            connectionStatus="Connected",
            databaseStatus="Ready",
            currentRpm=2500.0,
            coolantTemp=85.0,
            activeAlerts=["Alert 1", "Alert 2"],
            profileName="performance",
            timestamp=now
        )
        self.assertEqual(status.connectionStatus, "Connected")
        self.assertEqual(status.databaseStatus, "Ready")
        self.assertEqual(status.currentRpm, 2500.0)
        self.assertEqual(status.coolantTemp, 85.0)
        self.assertEqual(status.activeAlerts, ["Alert 1", "Alert 2"])
        self.assertEqual(status.profileName, "performance")
        self.assertEqual(status.timestamp, now)

    def test_toDict_returnsValidDictionary(self):
        """toDict should return a serializable dictionary."""
        now = datetime.now()
        status = StatusInfo(
            connectionStatus="Connected",
            currentRpm=3000.0,
            timestamp=now
        )
        d = status.toDict()
        self.assertEqual(d['connectionStatus'], "Connected")
        self.assertEqual(d['currentRpm'], 3000.0)
        self.assertEqual(d['timestamp'], now.isoformat())

    def test_toDict_noneTimestamp_returnsNone(self):
        """toDict should handle None timestamp."""
        status = StatusInfo()
        d = status.toDict()
        self.assertIsNone(d['timestamp'])


class TestAlertInfo(unittest.TestCase):
    """Tests for AlertInfo dataclass."""

    def test_defaultValues_allFieldsHaveDefaults(self):
        """AlertInfo should have sensible defaults."""
        alert = AlertInfo(message="Test alert")
        self.assertEqual(alert.message, "Test alert")
        self.assertEqual(alert.priority, 3)
        self.assertIsNone(alert.timestamp)
        self.assertFalse(alert.acknowledged)

    def test_customValues_allFieldsSet(self):
        """AlertInfo should accept custom values."""
        now = datetime.now()
        alert = AlertInfo(
            message="Critical alert",
            priority=1,
            timestamp=now,
            acknowledged=True
        )
        self.assertEqual(alert.message, "Critical alert")
        self.assertEqual(alert.priority, 1)
        self.assertEqual(alert.timestamp, now)
        self.assertTrue(alert.acknowledged)

    def test_toDict_returnsValidDictionary(self):
        """toDict should return a serializable dictionary."""
        now = datetime.now()
        alert = AlertInfo(message="Test", priority=2, timestamp=now)
        d = alert.toDict()
        self.assertEqual(d['message'], "Test")
        self.assertEqual(d['priority'], 2)
        self.assertEqual(d['timestamp'], now.isoformat())


class TestHeadlessDisplayDriver(unittest.TestCase):
    """Tests for HeadlessDisplayDriver."""

    def test_initialize_alwaysSucceeds(self):
        """Headless driver should always initialize successfully."""
        driver = HeadlessDisplayDriver()
        result = driver.initialize()
        self.assertTrue(result)
        self.assertTrue(driver.isInitialized)

    def test_shutdown_setsInitializedFalse(self):
        """Shutdown should set initialized to false."""
        driver = HeadlessDisplayDriver()
        driver.initialize()
        driver.shutdown()
        self.assertFalse(driver.isInitialized)

    def test_showStatus_storesLastStatus(self):
        """showStatus should store the status."""
        driver = HeadlessDisplayDriver()
        driver.initialize()
        status = StatusInfo(connectionStatus="Connected", currentRpm=2000)
        driver.showStatus(status)
        self.assertEqual(driver.getLastStatus(), status)

    def test_showAlert_addsToActiveAlerts(self):
        """showAlert should add non-acknowledged alerts to active list."""
        driver = HeadlessDisplayDriver()
        driver.initialize()
        alert = AlertInfo(message="Test alert", priority=2)
        driver.showAlert(alert)
        alerts = driver.getActiveAlerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].message, "Test alert")

    def test_showAlert_acknowledgedNotAdded(self):
        """showAlert should not add acknowledged alerts."""
        driver = HeadlessDisplayDriver()
        driver.initialize()
        alert = AlertInfo(message="Test", acknowledged=True)
        driver.showAlert(alert)
        self.assertEqual(len(driver.getActiveAlerts()), 0)

    def test_clearDisplay_clearsAlerts(self):
        """clearDisplay should clear active alerts."""
        driver = HeadlessDisplayDriver()
        driver.initialize()
        driver.showAlert(AlertInfo(message="Alert 1"))
        driver.showAlert(AlertInfo(message="Alert 2"))
        self.assertEqual(len(driver.getActiveAlerts()), 2)
        driver.clearDisplay()
        self.assertEqual(len(driver.getActiveAlerts()), 0)


class TestMinimalDisplayDriver(unittest.TestCase):
    """Tests for MinimalDisplayDriver."""

    def test_initialize_withoutAdapter_usesNullAdapter(self):
        """Initialize without adapter should use null adapter."""
        driver = MinimalDisplayDriver()
        result = driver.initialize()
        self.assertTrue(result)
        self.assertTrue(driver.isInitialized)

    def test_initialize_withConfig_setsParameters(self):
        """Initialize should use config parameters."""
        config = {'refreshRateMs': 500, 'brightness': 80}
        driver = MinimalDisplayDriver(config)
        driver.initialize()
        self.assertEqual(driver._refreshRateMs, 500)
        self.assertEqual(driver._brightness, 80)

    def test_setDisplayAdapter_setsAdapter(self):
        """setDisplayAdapter should set the adapter."""
        driver = MinimalDisplayDriver()
        mockAdapter = MagicMock()
        driver.setDisplayAdapter(mockAdapter)
        driver.initialize()
        mockAdapter.initialize.assert_called_once()

    def test_showStatus_callsAdapterMethods(self):
        """showStatus should call adapter drawing methods."""
        driver = MinimalDisplayDriver()
        mockAdapter = MagicMock()
        mockAdapter.drawText = MagicMock()
        mockAdapter.clear = MagicMock()
        mockAdapter.refresh = MagicMock()
        driver.setDisplayAdapter(mockAdapter)
        driver.initialize()

        status = StatusInfo(connectionStatus="Connected", currentRpm=2500)
        driver.showStatus(status)

        mockAdapter.clear.assert_called()
        mockAdapter.drawText.assert_called()

    def test_showAlert_highPriority_rendersFullScreen(self):
        """High priority alerts should render full screen."""
        driver = MinimalDisplayDriver()
        mockAdapter = MagicMock()
        mockAdapter.fill = MagicMock()
        driver.setDisplayAdapter(mockAdapter)
        driver.initialize()

        alert = AlertInfo(message="Critical!", priority=1)
        driver.showAlert(alert)

        # High priority should call fill for background
        mockAdapter.fill.assert_called()

    def test_shutdown_callsAdapterShutdown(self):
        """shutdown should call adapter shutdown."""
        driver = MinimalDisplayDriver()
        mockAdapter = MagicMock()
        driver.setDisplayAdapter(mockAdapter)
        driver.initialize()
        driver.shutdown()
        mockAdapter.shutdown.assert_called_once()

    def test_clearDisplay_callsAdapterClear(self):
        """clearDisplay should call adapter clear."""
        driver = MinimalDisplayDriver()
        mockAdapter = MagicMock()
        driver.setDisplayAdapter(mockAdapter)
        driver.initialize()
        driver.clearDisplay()
        mockAdapter.clear.assert_called()

    def test_dimensions_correctValues(self):
        """Display dimensions should be 240x240."""
        self.assertEqual(MinimalDisplayDriver.WIDTH, 240)
        self.assertEqual(MinimalDisplayDriver.HEIGHT, 240)


class TestDeveloperDisplayDriver(unittest.TestCase):
    """Tests for DeveloperDisplayDriver."""

    def test_initialize_printsHeader(self):
        """Initialize should print header to output stream."""
        driver = DeveloperDisplayDriver()
        output = io.StringIO()
        driver.setOutputStream(output)
        driver.initialize()
        result = output.getvalue()
        self.assertIn("Eclipse OBD-II", result)
        self.assertIn("Developer Mode", result)

    def test_initialize_alwaysSucceeds(self):
        """Developer driver should always initialize."""
        driver = DeveloperDisplayDriver()
        driver.setOutputStream(io.StringIO())
        result = driver.initialize()
        self.assertTrue(result)
        self.assertTrue(driver.isInitialized)

    def test_showStatus_printsStatusInfo(self):
        """showStatus should print status information."""
        driver = DeveloperDisplayDriver({'useColors': False})
        output = io.StringIO()
        driver.setOutputStream(output)
        driver.initialize()

        status = StatusInfo(
            connectionStatus="Connected",
            databaseStatus="Ready",
            currentRpm=3000,
            profileName="performance"
        )
        driver.showStatus(status)

        result = output.getvalue()
        self.assertIn("STATUS UPDATE", result)
        self.assertIn("Connected", result)
        self.assertIn("Ready", result)
        self.assertIn("3000", result)
        self.assertIn("performance", result)

    def test_showAlert_printsAlertInfo(self):
        """showAlert should print alert information."""
        driver = DeveloperDisplayDriver({'useColors': False})
        output = io.StringIO()
        driver.setOutputStream(output)
        driver.initialize()

        alert = AlertInfo(message="High Temperature", priority=2)
        driver.showAlert(alert)

        result = output.getvalue()
        self.assertIn("ALERT", result)
        self.assertIn("High Temperature", result)
        self.assertIn("P2", result)

    def test_shutdown_printsSummary(self):
        """shutdown should print summary statistics."""
        driver = DeveloperDisplayDriver({'useColors': False})
        output = io.StringIO()
        driver.setOutputStream(output)
        driver.initialize()
        driver.showStatus(StatusInfo())
        driver.showStatus(StatusInfo())
        driver.showAlert(AlertInfo(message="Test"))
        driver.shutdown()

        result = output.getvalue()
        self.assertIn("Shutdown", result)
        self.assertIn("Status updates: 2", result)
        self.assertIn("Alerts shown: 1", result)

    def test_colorOutput_canBeDisabled(self):
        """Color output should be disabled when configured."""
        driver = DeveloperDisplayDriver({'useColors': False})
        result = driver._color('red', 'test')
        self.assertEqual(result, 'test')

    def test_colorOutput_addsCodes(self):
        """Color output should add ANSI codes when enabled."""
        driver = DeveloperDisplayDriver({'useColors': True})
        result = driver._color('red', 'test')
        self.assertIn('\033[', result)
        self.assertIn('test', result)

    def test_timestamps_canBeDisabled(self):
        """Timestamps should be disabled when configured."""
        driver = DeveloperDisplayDriver({'showTimestamps': False})
        timestamp = driver._getTimestamp()
        self.assertEqual(timestamp, "")

    def test_clearDisplay_printsClearMessage(self):
        """clearDisplay should print clear message."""
        driver = DeveloperDisplayDriver({'useColors': False})
        output = io.StringIO()
        driver.setOutputStream(output)
        driver.initialize()
        driver.clearDisplay()
        result = output.getvalue()
        self.assertIn("CLEARED", result)


class TestDisplayManager(unittest.TestCase):
    """Tests for DisplayManager class."""

    def test_init_defaultMode_isHeadless(self):
        """Default mode should be headless."""
        manager = DisplayManager()
        self.assertEqual(manager.mode, DisplayMode.HEADLESS)

    def test_init_specifiedMode_setsCorrectMode(self):
        """Specified mode should be set correctly."""
        manager = DisplayManager(mode=DisplayMode.DEVELOPER)
        self.assertEqual(manager.mode, DisplayMode.DEVELOPER)

    def test_fromConfig_validMode_createsManager(self):
        """fromConfig should create manager with correct mode."""
        config = {'display': {'mode': 'developer'}}
        manager = DisplayManager.fromConfig(config)
        self.assertEqual(manager.mode, DisplayMode.DEVELOPER)

    def test_fromConfig_invalidMode_defaultsToHeadless(self):
        """fromConfig should default to headless for invalid mode."""
        config = {'display': {'mode': 'invalid'}}
        manager = DisplayManager.fromConfig(config)
        self.assertEqual(manager.mode, DisplayMode.HEADLESS)

    def test_fromConfig_missingDisplaySection_defaultsToHeadless(self):
        """fromConfig should default to headless if display section missing."""
        config = {}
        manager = DisplayManager.fromConfig(config)
        self.assertEqual(manager.mode, DisplayMode.HEADLESS)

    def test_initialize_headless_succeeds(self):
        """Initialize headless mode should succeed."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        result = manager.initialize()
        self.assertTrue(result)
        self.assertTrue(manager.isInitialized)

    def test_initialize_developer_succeeds(self):
        """Initialize developer mode should succeed."""
        manager = DisplayManager(
            mode=DisplayMode.DEVELOPER,
            config={'useColors': False}
        )
        # Redirect output
        with patch('sys.stdout', io.StringIO()):
            result = manager.initialize()
        self.assertTrue(result)

    def test_initialize_minimal_succeeds(self):
        """Initialize minimal mode should succeed (with null adapter)."""
        manager = DisplayManager(mode=DisplayMode.MINIMAL)
        result = manager.initialize()
        self.assertTrue(result)

    def test_shutdown_setsInitializedFalse(self):
        """shutdown should set initialized to false."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()
        manager.shutdown()
        self.assertFalse(manager.isInitialized)

    def test_showStatus_withParameters_createsStatusInfo(self):
        """showStatus should create and display StatusInfo."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()
        manager.showStatus(
            connectionStatus="Connected",
            databaseStatus="Ready",
            currentRpm=2500,
            coolantTemp=85
        )
        status = manager.getLastStatus()
        self.assertIsNotNone(status)
        self.assertEqual(status.connectionStatus, "Connected")
        self.assertEqual(status.currentRpm, 2500)

    def test_showStatusInfo_withStatusObject(self):
        """showStatusInfo should display StatusInfo object."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()
        status = StatusInfo(connectionStatus="Connected")
        manager.showStatusInfo(status)
        self.assertEqual(manager.getLastStatus().connectionStatus, "Connected")

    def test_showAlert_withParameters_createsAlertInfo(self):
        """showAlert should create and display AlertInfo."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()
        manager.showAlert(message="Test alert", priority=2)
        alerts = manager.getActiveAlerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].message, "Test alert")
        self.assertEqual(alerts[0].priority, 2)

    def test_showAlertInfo_withAlertObject(self):
        """showAlertInfo should display AlertInfo object."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()
        alert = AlertInfo(message="Critical", priority=1)
        manager.showAlertInfo(alert)
        alerts = manager.getActiveAlerts()
        self.assertEqual(len(alerts), 1)

    def test_clearDisplay_clearsState(self):
        """clearDisplay should clear display state."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()
        manager.showAlert("Alert 1")
        manager.clearDisplay()
        self.assertEqual(len(manager.getActiveAlerts()), 0)

    def test_changeMode_changesDriver(self):
        """changeMode should change the display driver."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()
        result = manager.changeMode(DisplayMode.DEVELOPER)
        self.assertTrue(result)
        self.assertEqual(manager.mode, DisplayMode.DEVELOPER)

    def test_changeMode_sameMode_noChange(self):
        """changeMode to same mode should succeed without change."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()
        result = manager.changeMode(DisplayMode.HEADLESS)
        self.assertTrue(result)

    def test_onStatusUpdate_callbackCalled(self):
        """Status update callback should be called."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()

        callbackCalled = []
        def callback(status):
            callbackCalled.append(status)

        manager.onStatusUpdate(callback)
        manager.showStatus(connectionStatus="Connected")

        self.assertEqual(len(callbackCalled), 1)
        self.assertEqual(callbackCalled[0].connectionStatus, "Connected")

    def test_onAlert_callbackCalled(self):
        """Alert callback should be called."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()

        callbackCalled = []
        def callback(alert):
            callbackCalled.append(alert)

        manager.onAlert(callback)
        manager.showAlert("Test alert")

        self.assertEqual(len(callbackCalled), 1)
        self.assertEqual(callbackCalled[0].message, "Test alert")

    def test_onModeChange_callbackCalled(self):
        """Mode change callback should be called."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()

        callbackCalled = []
        def callback(oldMode, newMode):
            callbackCalled.append((oldMode, newMode))

        manager.onModeChange(callback)
        manager.changeMode(DisplayMode.DEVELOPER)

        self.assertEqual(len(callbackCalled), 1)
        self.assertEqual(callbackCalled[0][0], DisplayMode.HEADLESS)
        self.assertEqual(callbackCalled[0][1], DisplayMode.DEVELOPER)


class TestHelperFunctions(unittest.TestCase):
    """Tests for helper functions."""

    def test_createDisplayManagerFromConfig_createsManager(self):
        """createDisplayManagerFromConfig should create manager."""
        config = {'display': {'mode': 'developer'}}
        manager = createDisplayManagerFromConfig(config)
        self.assertIsInstance(manager, DisplayManager)
        self.assertEqual(manager.mode, DisplayMode.DEVELOPER)

    def test_getDisplayModeFromConfig_validMode(self):
        """getDisplayModeFromConfig should return correct mode."""
        config = {'display': {'mode': 'minimal'}}
        mode = getDisplayModeFromConfig(config)
        self.assertEqual(mode, DisplayMode.MINIMAL)

    def test_getDisplayModeFromConfig_invalidMode_defaultsHeadless(self):
        """getDisplayModeFromConfig should default to headless."""
        config = {'display': {'mode': 'invalid'}}
        mode = getDisplayModeFromConfig(config)
        self.assertEqual(mode, DisplayMode.HEADLESS)

    def test_getDisplayModeFromConfig_missingSection(self):
        """getDisplayModeFromConfig should handle missing section."""
        config = {}
        mode = getDisplayModeFromConfig(config)
        self.assertEqual(mode, DisplayMode.HEADLESS)

    def test_isDisplayAvailable_allModesAvailable(self):
        """isDisplayAvailable should return True for all modes."""
        self.assertTrue(isDisplayAvailable(DisplayMode.HEADLESS))
        self.assertTrue(isDisplayAvailable(DisplayMode.MINIMAL))
        self.assertTrue(isDisplayAvailable(DisplayMode.DEVELOPER))


class TestNullDisplayAdapter(unittest.TestCase):
    """Tests for _NullDisplayAdapter."""

    def test_allMethodsExist(self):
        """Null adapter should have all required methods."""
        adapter = _NullDisplayAdapter()
        adapter.initialize()
        adapter.shutdown()
        adapter.clear()
        adapter.drawText(0, 0, "test")
        adapter.drawLine(0, 0, 10, 10)
        adapter.fill("red")
        adapter.refresh()
        # All methods should complete without error


class TestExceptions(unittest.TestCase):
    """Tests for exception classes."""

    def test_displayError_storesDetails(self):
        """DisplayError should store details dict."""
        error = DisplayError("Test error", {'key': 'value'})
        self.assertEqual(str(error), "Test error")
        self.assertEqual(error.details, {'key': 'value'})

    def test_displayError_defaultDetails(self):
        """DisplayError should have empty dict as default."""
        error = DisplayError("Test")
        self.assertEqual(error.details, {})

    def test_displayInitializationError_isDisplayError(self):
        """DisplayInitializationError should be DisplayError subclass."""
        error = DisplayInitializationError("Init failed")
        self.assertIsInstance(error, DisplayError)

    def test_displayOutputError_isDisplayError(self):
        """DisplayOutputError should be DisplayError subclass."""
        error = DisplayOutputError("Output failed")
        self.assertIsInstance(error, DisplayError)


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and error handling."""

    def test_showStatus_withNoneDriver(self):
        """showStatus should handle None driver gracefully."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager._driver = None  # Force None driver
        # Should not raise
        manager.showStatus(connectionStatus="Test")

    def test_showAlert_withNoneDriver(self):
        """showAlert should handle None driver gracefully."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager._driver = None
        # Should not raise
        manager.showAlert("Test")

    def test_getLastStatus_notInitialized(self):
        """getLastStatus should return None if not initialized."""
        manager = DisplayManager()
        self.assertIsNone(manager.getLastStatus())

    def test_getActiveAlerts_notInitialized(self):
        """getActiveAlerts should return empty list if not initialized."""
        manager = DisplayManager()
        alerts = manager.getActiveAlerts()
        self.assertEqual(alerts, [])

    def test_callback_exception_doesNotPropagate(self):
        """Callback exceptions should be caught and logged."""
        manager = DisplayManager(mode=DisplayMode.HEADLESS)
        manager.initialize()

        def badCallback(status):
            raise RuntimeError("Callback error")

        manager.onStatusUpdate(badCallback)
        # Should not raise
        manager.showStatus(connectionStatus="Test")

    def test_minimal_adapter_exception_graceful(self):
        """Minimal driver should handle adapter exceptions gracefully."""
        driver = MinimalDisplayDriver()
        mockAdapter = MagicMock()
        mockAdapter.drawText.side_effect = RuntimeError("Draw error")
        mockAdapter.clear = MagicMock()
        driver.setDisplayAdapter(mockAdapter)
        driver.initialize()

        # Should not raise
        status = StatusInfo(connectionStatus="Connected")
        driver.showStatus(status)

    def test_developer_output_exception_graceful(self):
        """Developer driver should handle output errors gracefully."""
        driver = DeveloperDisplayDriver()

        class BadStream:
            def write(self, msg):
                raise IOError("Write error")

        driver.setOutputStream(BadStream())
        driver.initialize()
        # Should not raise - errors are logged


class TestConfigIntegration(unittest.TestCase):
    """Tests for configuration integration."""

    def test_fullConfigIntegration(self):
        """Test complete configuration integration."""
        config = {
            'display': {
                'mode': 'headless',
                'width': 240,
                'height': 240,
                'refreshRateMs': 1000,
                'brightness': 100
            }
        }
        manager = DisplayManager.fromConfig(config)
        self.assertEqual(manager.mode, DisplayMode.HEADLESS)
        result = manager.initialize()
        self.assertTrue(result)

    def test_developerConfigIntegration(self):
        """Test developer mode configuration."""
        config = {
            'display': {
                'mode': 'developer',
                'useColors': False,
                'showTimestamps': True
            }
        }
        manager = DisplayManager.fromConfig(config)
        self.assertEqual(manager.mode, DisplayMode.DEVELOPER)

    def test_minimalConfigIntegration(self):
        """Test minimal mode configuration."""
        config = {
            'display': {
                'mode': 'minimal',
                'width': 240,
                'height': 240,
                'refreshRateMs': 500,
                'brightness': 80
            }
        }
        manager = DisplayManager.fromConfig(config)
        self.assertEqual(manager.mode, DisplayMode.MINIMAL)


def runTests():
    """Run all tests and return exit code."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    testClasses = [
        TestDisplayModeEnum,
        TestStatusInfo,
        TestAlertInfo,
        TestHeadlessDisplayDriver,
        TestMinimalDisplayDriver,
        TestDeveloperDisplayDriver,
        TestDisplayManager,
        TestHelperFunctions,
        TestNullDisplayAdapter,
        TestExceptions,
        TestEdgeCases,
        TestConfigIntegration,
    ]

    for testClass in testClasses:
        tests = loader.loadTestsFromTestCase(testClass)
        suite.addTests(tests)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.wasSuccessful():
        print("\nAll tests passed!")
        return 0
    else:
        print("\nSome tests failed!")
        return 1


if __name__ == '__main__':
    sys.exit(runTests())
