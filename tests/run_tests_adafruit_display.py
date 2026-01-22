#!/usr/bin/env python3
################################################################################
# File Name: run_tests_adafruit_display.py
# Purpose/Description: Test runner for Adafruit display adapter (US-008)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
################################################################################

"""
Test suite for Adafruit ST7789 1.3" 240x240 display adapter.

Tests cover:
- Display adapter initialization
- Color definitions and conversion
- Drawing operations (text, lines, shapes)
- Graceful handling when hardware is not available
- Integration with MinimalDisplayDriver
- Auto-refresh functionality
- Status screen layout rendering

Run with: python tests/run_tests_adafruit_display.py
"""

import os
import sys
import time
import threading
import unittest
from datetime import datetime
from io import StringIO
from unittest.mock import MagicMock, patch, PropertyMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestColors(unittest.TestCase):
    """Test cases for Colors class."""

    def test_colorConstants_areRgbTuples(self):
        """Colors should be RGB tuples with 3 values."""
        from obd.adafruit_display import Colors

        self.assertEqual(len(Colors.WHITE), 3)
        self.assertEqual(len(Colors.BLACK), 3)
        self.assertEqual(len(Colors.RED), 3)

    def test_colorWhite_isCorrect(self):
        """White should be (255, 255, 255)."""
        from obd.adafruit_display import Colors

        self.assertEqual(Colors.WHITE, (255, 255, 255))

    def test_colorBlack_isCorrect(self):
        """Black should be (0, 0, 0)."""
        from obd.adafruit_display import Colors

        self.assertEqual(Colors.BLACK, (0, 0, 0))

    def test_colorRed_isCorrect(self):
        """Red should be (255, 0, 0)."""
        from obd.adafruit_display import Colors

        self.assertEqual(Colors.RED, (255, 0, 0))

    def test_fromName_validColor_returnsRgb(self):
        """fromName should return RGB tuple for valid color names."""
        from obd.adafruit_display import Colors

        self.assertEqual(Colors.fromName('red'), Colors.RED)
        self.assertEqual(Colors.fromName('green'), Colors.GREEN)
        self.assertEqual(Colors.fromName('blue'), Colors.BLUE)

    def test_fromName_caseInsensitive(self):
        """fromName should be case-insensitive."""
        from obd.adafruit_display import Colors

        self.assertEqual(Colors.fromName('RED'), Colors.RED)
        self.assertEqual(Colors.fromName('Red'), Colors.RED)
        self.assertEqual(Colors.fromName('rEd'), Colors.RED)

    def test_fromName_invalidColor_returnsWhite(self):
        """fromName should return white for unknown color names."""
        from obd.adafruit_display import Colors

        self.assertEqual(Colors.fromName('unknown'), Colors.WHITE)
        self.assertEqual(Colors.fromName('notacolor'), Colors.WHITE)

    def test_fromName_grayBothSpellings(self):
        """fromName should accept both 'gray' and 'grey'."""
        from obd.adafruit_display import Colors

        self.assertEqual(Colors.fromName('gray'), Colors.GRAY)
        self.assertEqual(Colors.fromName('grey'), Colors.GRAY)


class TestDisplayAdapterExceptions(unittest.TestCase):
    """Test cases for display adapter exceptions."""

    def test_displayAdapterError_hasDetails(self):
        """DisplayAdapterError should store details dict."""
        from obd.adafruit_display import DisplayAdapterError

        err = DisplayAdapterError("Test error", {'key': 'value'})
        self.assertEqual(str(err), "Test error")
        self.assertEqual(err.details['key'], 'value')

    def test_displayAdapterError_defaultEmptyDetails(self):
        """DisplayAdapterError should default to empty dict."""
        from obd.adafruit_display import DisplayAdapterError

        err = DisplayAdapterError("Test error")
        self.assertEqual(err.details, {})

    def test_displayInitializationError_inherits(self):
        """DisplayInitializationError should inherit from DisplayAdapterError."""
        from obd.adafruit_display import DisplayAdapterError, DisplayInitializationError

        err = DisplayInitializationError("Init failed")
        self.assertIsInstance(err, DisplayAdapterError)

    def test_displayRenderError_inherits(self):
        """DisplayRenderError should inherit from DisplayAdapterError."""
        from obd.adafruit_display import DisplayAdapterError, DisplayRenderError

        err = DisplayRenderError("Render failed")
        self.assertIsInstance(err, DisplayAdapterError)


class TestAdafruitDisplayAdapterInit(unittest.TestCase):
    """Test cases for AdafruitDisplayAdapter initialization."""

    def test_init_defaultValues(self):
        """Adapter should have correct default values."""
        from obd.adafruit_display import AdafruitDisplayAdapter

        adapter = AdafruitDisplayAdapter()
        self.assertEqual(adapter._csPin, 8)
        self.assertEqual(adapter._dcPin, 25)
        self.assertEqual(adapter._rstPin, 24)
        self.assertEqual(adapter._blPin, 18)
        self.assertEqual(adapter._rotation, 180)
        self.assertEqual(adapter._brightness, 100)

    def test_init_customPins(self):
        """Adapter should accept custom pin configuration."""
        from obd.adafruit_display import AdafruitDisplayAdapter

        adapter = AdafruitDisplayAdapter(csPin=5, dcPin=6, rstPin=7, blPin=12)
        self.assertEqual(adapter._csPin, 5)
        self.assertEqual(adapter._dcPin, 6)
        self.assertEqual(adapter._rstPin, 7)
        self.assertEqual(adapter._blPin, 12)

    def test_init_customRotation(self):
        """Adapter should accept custom rotation."""
        from obd.adafruit_display import AdafruitDisplayAdapter

        adapter = AdafruitDisplayAdapter(rotation=90)
        self.assertEqual(adapter._rotation, 90)

    def test_init_configOverrides(self):
        """Adapter should read pins from config dict."""
        from obd.adafruit_display import AdafruitDisplayAdapter

        config = {'csPin': 10, 'dcPin': 11}
        adapter = AdafruitDisplayAdapter(config=config)
        self.assertEqual(adapter._csPin, 10)
        self.assertEqual(adapter._dcPin, 11)

    def test_isInitialized_falseByDefault(self):
        """isInitialized should be False before initialization."""
        from obd.adafruit_display import AdafruitDisplayAdapter

        adapter = AdafruitDisplayAdapter()
        self.assertFalse(adapter.isInitialized)

    def test_width_returns240(self):
        """width property should return 240."""
        from obd.adafruit_display import AdafruitDisplayAdapter

        adapter = AdafruitDisplayAdapter()
        self.assertEqual(adapter.width, 240)

    def test_height_returns240(self):
        """height property should return 240."""
        from obd.adafruit_display import AdafruitDisplayAdapter

        adapter = AdafruitDisplayAdapter()
        self.assertEqual(adapter.height, 240)


class TestAdafruitDisplayAdapterWithoutHardware(unittest.TestCase):
    """Test cases for AdafruitDisplayAdapter when hardware is not available."""

    def test_initialize_returnssFalse_whenLibraryUnavailable(self):
        """initialize should return False when Adafruit libraries not available."""
        from obd.adafruit_display import AdafruitDisplayAdapter, ADAFRUIT_AVAILABLE

        if ADAFRUIT_AVAILABLE:
            self.skipTest("Adafruit libraries are available - cannot test unavailable case")

        adapter = AdafruitDisplayAdapter()
        result = adapter.initialize()
        self.assertFalse(result)

    def test_isDisplayHardwareAvailable_reflectsLibraryStatus(self):
        """isDisplayHardwareAvailable should reflect library import status."""
        from obd.adafruit_display import isDisplayHardwareAvailable, ADAFRUIT_AVAILABLE

        self.assertEqual(isDisplayHardwareAvailable(), ADAFRUIT_AVAILABLE)


class TestAdafruitDisplayAdapterMocked(unittest.TestCase):
    """Test cases for AdafruitDisplayAdapter with mocked hardware."""

    def setUp(self):
        """Set up mock objects for hardware."""
        # Create mock modules
        self.mockBoard = MagicMock()
        self.mockDigitalio = MagicMock()
        self.mockSt7789 = MagicMock()
        self.mockImage = MagicMock()
        self.mockImageDraw = MagicMock()
        self.mockImageFont = MagicMock()

        # Set up attribute access for board pins
        self.mockBoard.D8 = MagicMock()
        self.mockBoard.D25 = MagicMock()
        self.mockBoard.D24 = MagicMock()
        self.mockBoard.D18 = MagicMock()
        self.mockBoard.SPI = MagicMock(return_value=MagicMock())

    @patch.dict('sys.modules', {
        'board': MagicMock(),
        'digitalio': MagicMock(),
        'adafruit_rgb_display': MagicMock(),
        'adafruit_rgb_display.st7789': MagicMock(),
        'PIL': MagicMock(),
        'PIL.Image': MagicMock(),
        'PIL.ImageDraw': MagicMock(),
        'PIL.ImageFont': MagicMock(),
    })
    def test_createAdafruitAdapter_createsAdapter(self):
        """createAdafruitAdapter should create an adapter instance."""
        # Import fresh to get mocked version
        from obd.adafruit_display import AdafruitDisplayAdapter

        adapter = AdafruitDisplayAdapter()
        self.assertIsNotNone(adapter)


class TestMinimalDisplayDriverAutoRefresh(unittest.TestCase):
    """Test cases for MinimalDisplayDriver auto-refresh functionality."""

    def test_autoRefreshEnabled_byDefault(self):
        """Auto-refresh should be enabled by default."""
        from obd.display_manager import MinimalDisplayDriver

        driver = MinimalDisplayDriver()
        self.assertTrue(driver._autoRefreshEnabled)

    def test_autoRefreshDisabled_viaConfig(self):
        """Auto-refresh should be disabled when config specifies."""
        from obd.display_manager import MinimalDisplayDriver

        driver = MinimalDisplayDriver(config={'autoRefresh': False})
        self.assertFalse(driver._autoRefreshEnabled)

    def test_refreshRateMs_defaultIs1000(self):
        """Default refresh rate should be 1000ms (1 second)."""
        from obd.display_manager import MinimalDisplayDriver

        driver = MinimalDisplayDriver()
        self.assertEqual(driver._refreshRateMs, 1000)

    def test_refreshRateMs_fromConfig(self):
        """Refresh rate should be configurable via config."""
        from obd.display_manager import MinimalDisplayDriver

        driver = MinimalDisplayDriver(config={'refreshRateMs': 500})
        self.assertEqual(driver._refreshRateMs, 500)

    def test_setRefreshRate_updatesInterval(self):
        """setRefreshRate should update the refresh interval."""
        from obd.display_manager import MinimalDisplayDriver

        driver = MinimalDisplayDriver()
        driver.setRefreshRate(2000)
        self.assertEqual(driver._refreshRateMs, 2000)

    def test_setRefreshRate_minimumIs100ms(self):
        """setRefreshRate should enforce 100ms minimum."""
        from obd.display_manager import MinimalDisplayDriver

        driver = MinimalDisplayDriver()
        driver.setRefreshRate(50)
        self.assertEqual(driver._refreshRateMs, 100)

    def test_enableAutoRefresh_toggles(self):
        """enableAutoRefresh should toggle auto-refresh state."""
        from obd.display_manager import MinimalDisplayDriver

        driver = MinimalDisplayDriver(config={'autoRefresh': False})
        self.assertFalse(driver._autoRefreshEnabled)

        driver.enableAutoRefresh(True)
        self.assertTrue(driver._autoRefreshEnabled)

        driver.enableAutoRefresh(False)
        self.assertFalse(driver._autoRefreshEnabled)


class TestMinimalDisplayDriverInitialization(unittest.TestCase):
    """Test cases for MinimalDisplayDriver initialization."""

    def test_initialize_withNullAdapter_returnsTrue(self):
        """Initialize should succeed with null adapter when hardware unavailable."""
        from obd.display_manager import MinimalDisplayDriver

        driver = MinimalDisplayDriver(config={'useHardware': False, 'autoRefresh': False})
        result = driver.initialize()
        self.assertTrue(result)
        self.assertTrue(driver.isInitialized)

    def test_initialize_gracefulDegradation(self):
        """Initialize should gracefully degrade when hardware unavailable."""
        from obd.display_manager import MinimalDisplayDriver

        driver = MinimalDisplayDriver(config={'useHardware': True, 'autoRefresh': False})
        result = driver.initialize()
        # Should succeed even without hardware (uses null adapter)
        self.assertTrue(result)

    def test_shutdown_stopsAutoRefresh(self):
        """Shutdown should stop the auto-refresh thread."""
        from obd.display_manager import MinimalDisplayDriver

        driver = MinimalDisplayDriver(config={'useHardware': False})
        driver.initialize()

        # Give thread time to start
        time.sleep(0.1)

        driver.shutdown()

        # Thread should be stopped
        self.assertIsNone(driver._autoRefreshThread)
        self.assertFalse(driver.isInitialized)

    def test_dimensions_are240x240(self):
        """Display dimensions should be 240x240."""
        from obd.display_manager import MinimalDisplayDriver

        driver = MinimalDisplayDriver()
        self.assertEqual(driver.WIDTH, 240)
        self.assertEqual(driver.HEIGHT, 240)


class TestMinimalDisplayDriverLayoutConstants(unittest.TestCase):
    """Test cases for MinimalDisplayDriver layout constants."""

    def test_layoutConstants_defined(self):
        """Layout constants should be defined."""
        from obd.display_manager import MinimalDisplayDriver

        self.assertEqual(MinimalDisplayDriver.HEADER_Y, 5)
        self.assertEqual(MinimalDisplayDriver.HEADER_HEIGHT, 50)
        self.assertEqual(MinimalDisplayDriver.MAIN_Y, 60)
        self.assertEqual(MinimalDisplayDriver.ALERTS_Y, 155)
        self.assertEqual(MinimalDisplayDriver.FOOTER_Y, 205)


class TestMinimalDisplayDriverStatusScreen(unittest.TestCase):
    """Test cases for MinimalDisplayDriver status screen rendering."""

    def setUp(self):
        """Set up test fixtures."""
        from obd.display_manager import MinimalDisplayDriver, StatusInfo

        self.driver = MinimalDisplayDriver(config={'useHardware': False, 'autoRefresh': False})
        self.mockAdapter = MagicMock()
        self.driver.setDisplayAdapter(self.mockAdapter)
        self.driver.initialize()

    def tearDown(self):
        """Clean up after test."""
        self.driver.shutdown()

    def test_showStatus_callsDrawText(self):
        """showStatus should call drawText on adapter."""
        from obd.display_manager import StatusInfo

        status = StatusInfo(
            connectionStatus="Connected",
            databaseStatus="Ready",
            currentRpm=2500,
            coolantTemp=85
        )
        self.driver.showStatus(status)

        self.mockAdapter.drawText.assert_called()

    def test_showStatus_clearsFirst(self):
        """showStatus should clear the display first."""
        from obd.display_manager import StatusInfo

        status = StatusInfo(connectionStatus="Connected")
        self.driver.showStatus(status)

        self.mockAdapter.clear.assert_called()

    def test_showStatus_refreshesDisplay(self):
        """showStatus should refresh the display at the end."""
        from obd.display_manager import StatusInfo

        status = StatusInfo(connectionStatus="Connected")
        self.driver.showStatus(status)

        self.mockAdapter.refresh.assert_called()

    def test_showStatus_displaysConnectionStatus(self):
        """showStatus should display connection status."""
        from obd.display_manager import StatusInfo

        status = StatusInfo(connectionStatus="Connected")
        self.driver.showStatus(status)

        # Find calls containing "OBD:"
        calls = [str(c) for c in self.mockAdapter.drawText.call_args_list]
        connectionCalls = [c for c in calls if 'OBD:' in c]
        self.assertTrue(len(connectionCalls) > 0)

    def test_showStatus_displaysDatabaseStatus(self):
        """showStatus should display database status."""
        from obd.display_manager import StatusInfo

        status = StatusInfo(databaseStatus="Ready")
        self.driver.showStatus(status)

        calls = [str(c) for c in self.mockAdapter.drawText.call_args_list]
        dbCalls = [c for c in calls if 'DB:' in c]
        self.assertTrue(len(dbCalls) > 0)

    def test_showStatus_displaysRpm(self):
        """showStatus should display RPM value."""
        from obd.display_manager import StatusInfo

        status = StatusInfo(currentRpm=3000)
        self.driver.showStatus(status)

        calls = [str(c) for c in self.mockAdapter.drawText.call_args_list]
        rpmCalls = [c for c in calls if 'RPM' in c or '3000' in c]
        self.assertTrue(len(rpmCalls) > 0)

    def test_showStatus_displaysCoolantTemp(self):
        """showStatus should display coolant temperature."""
        from obd.display_manager import StatusInfo

        status = StatusInfo(coolantTemp=90)
        self.driver.showStatus(status)

        calls = [str(c) for c in self.mockAdapter.drawText.call_args_list]
        tempCalls = [c for c in calls if 'COOLANT' in c or '90' in c]
        self.assertTrue(len(tempCalls) > 0)

    def test_showStatus_displaysProfileName(self):
        """showStatus should display profile name."""
        from obd.display_manager import StatusInfo

        status = StatusInfo(profileName="performance")
        self.driver.showStatus(status)

        calls = [str(c) for c in self.mockAdapter.drawText.call_args_list]
        profileCalls = [c for c in calls if 'Profile:' in c or 'performance' in c]
        self.assertTrue(len(profileCalls) > 0)

    def test_showStatus_displaysAlertCount(self):
        """showStatus should display alert count."""
        from obd.display_manager import StatusInfo

        status = StatusInfo(activeAlerts=["Alert 1", "Alert 2"])
        self.driver.showStatus(status)

        calls = [str(c) for c in self.mockAdapter.drawText.call_args_list]
        alertCalls = [c for c in calls if 'ALERT' in c]
        self.assertTrue(len(alertCalls) > 0)

    def test_showStatus_noAlerts_showsNone(self):
        """showStatus should show 'none' when no alerts."""
        from obd.display_manager import StatusInfo

        status = StatusInfo(activeAlerts=[])
        self.driver.showStatus(status)

        calls = [str(c) for c in self.mockAdapter.drawText.call_args_list]
        noneAlertCalls = [c for c in calls if 'none' in c.lower()]
        self.assertTrue(len(noneAlertCalls) > 0)


class TestMinimalDisplayDriverAlertScreen(unittest.TestCase):
    """Test cases for MinimalDisplayDriver alert screen rendering."""

    def setUp(self):
        """Set up test fixtures."""
        from obd.display_manager import MinimalDisplayDriver

        self.driver = MinimalDisplayDriver(config={'useHardware': False, 'autoRefresh': False})
        self.mockAdapter = MagicMock()
        self.driver.setDisplayAdapter(self.mockAdapter)
        self.driver.initialize()

    def tearDown(self):
        """Clean up after test."""
        self.driver.shutdown()

    def test_showAlert_highPriority_rendersFillScreen(self):
        """High priority alert should fill screen."""
        from obd.display_manager import AlertInfo

        alert = AlertInfo(message="Critical Alert", priority=1)
        self.driver.showAlert(alert)

        # Should call fill for high priority
        self.mockAdapter.fill.assert_called()

    def test_showAlert_lowPriority_updatesStatus(self):
        """Low priority alert should update status screen."""
        from obd.display_manager import AlertInfo, StatusInfo

        # Set a status first
        status = StatusInfo(connectionStatus="Connected")
        self.driver.showStatus(status)
        self.mockAdapter.reset_mock()

        alert = AlertInfo(message="Minor Alert", priority=4)
        self.driver.showAlert(alert)

        # Should add to active alerts
        self.assertIn(alert, self.driver._activeAlerts)

    def test_showAlert_addsToActiveAlerts(self):
        """showAlert should add unacknowledged alerts to active list."""
        from obd.display_manager import AlertInfo

        alert = AlertInfo(message="Test Alert", priority=3)
        self.driver.showAlert(alert)

        self.assertEqual(len(self.driver._activeAlerts), 1)

    def test_showAlert_acknowledgedNotAdded(self):
        """showAlert should not add acknowledged alerts to active list."""
        from obd.display_manager import AlertInfo

        alert = AlertInfo(message="Test Alert", priority=3, acknowledged=True)
        self.driver.showAlert(alert)

        self.assertEqual(len(self.driver._activeAlerts), 0)


class TestMinimalDisplayDriverClear(unittest.TestCase):
    """Test cases for MinimalDisplayDriver clear functionality."""

    def setUp(self):
        """Set up test fixtures."""
        from obd.display_manager import MinimalDisplayDriver

        self.driver = MinimalDisplayDriver(config={'useHardware': False, 'autoRefresh': False})
        self.mockAdapter = MagicMock()
        self.driver.setDisplayAdapter(self.mockAdapter)
        self.driver.initialize()

    def tearDown(self):
        """Clean up after test."""
        self.driver.shutdown()

    def test_clearDisplay_callsAdapterClear(self):
        """clearDisplay should call clear on adapter."""
        self.driver.clearDisplay()
        self.mockAdapter.clear.assert_called()

    def test_clearDisplay_clearsActiveAlerts(self):
        """clearDisplay should clear active alerts list."""
        from obd.display_manager import AlertInfo

        alert = AlertInfo(message="Test", priority=3)
        self.driver.showAlert(alert)
        self.assertEqual(len(self.driver._activeAlerts), 1)

        self.driver.clearDisplay()
        self.assertEqual(len(self.driver._activeAlerts), 0)


class TestDisplayManagerIntegration(unittest.TestCase):
    """Integration tests for DisplayManager with minimal mode."""

    def test_fromConfig_minimalMode_createsMinimalDriver(self):
        """fromConfig should create MinimalDisplayDriver for minimal mode."""
        from obd.display_manager import DisplayManager, DisplayMode, MinimalDisplayDriver

        config = {'display': {'mode': 'minimal', 'autoRefresh': False}}
        manager = DisplayManager.fromConfig(config)

        self.assertEqual(manager.mode, DisplayMode.MINIMAL)
        self.assertIsInstance(manager._driver, MinimalDisplayDriver)

    def test_minimalMode_showStatus_worksWithConfig(self):
        """showStatus should work with minimal mode from config."""
        from obd.display_manager import DisplayManager

        config = {
            'display': {
                'mode': 'minimal',
                'useHardware': False,
                'autoRefresh': False
            }
        }
        manager = DisplayManager.fromConfig(config)
        manager.initialize()

        # Should not raise
        manager.showStatus(
            connectionStatus="Connected",
            databaseStatus="Ready",
            currentRpm=2500,
            coolantTemp=85,
            profileName="daily"
        )

        manager.shutdown()


class TestCreateAdafruitAdapter(unittest.TestCase):
    """Test cases for createAdafruitAdapter helper function."""

    def test_createAdafruitAdapter_withNoConfig(self):
        """createAdafruitAdapter should work with no config."""
        from obd.adafruit_display import createAdafruitAdapter

        adapter = createAdafruitAdapter()
        self.assertIsNotNone(adapter)

    def test_createAdafruitAdapter_withConfig(self):
        """createAdafruitAdapter should use config values."""
        from obd.adafruit_display import createAdafruitAdapter

        config = {
            'display': {
                'rotation': 90,
                'brightness': 50
            }
        }
        adapter = createAdafruitAdapter(config)

        self.assertEqual(adapter._rotation, 90)
        self.assertEqual(adapter._brightness, 50)


class TestDisplayConstants(unittest.TestCase):
    """Test cases for display constants."""

    def test_displayWidth_is240(self):
        """DISPLAY_WIDTH should be 240."""
        from obd.adafruit_display import DISPLAY_WIDTH

        self.assertEqual(DISPLAY_WIDTH, 240)

    def test_displayHeight_is240(self):
        """DISPLAY_HEIGHT should be 240."""
        from obd.adafruit_display import DISPLAY_HEIGHT

        self.assertEqual(DISPLAY_HEIGHT, 240)


class TestModuleExports(unittest.TestCase):
    """Test cases for module exports."""

    def test_obdModule_exportsAdafruitAdapter(self):
        """OBD module should export AdafruitDisplayAdapter."""
        from obd import AdafruitDisplayAdapter

        self.assertIsNotNone(AdafruitDisplayAdapter)

    def test_obdModule_exportsColors(self):
        """OBD module should export Colors."""
        from obd import Colors

        self.assertIsNotNone(Colors)

    def test_obdModule_exportsDisplayConstants(self):
        """OBD module should export display constants."""
        from obd import DISPLAY_WIDTH, DISPLAY_HEIGHT

        self.assertEqual(DISPLAY_WIDTH, 240)
        self.assertEqual(DISPLAY_HEIGHT, 240)

    def test_obdModule_exportsIsDisplayHardwareAvailable(self):
        """OBD module should export isDisplayHardwareAvailable."""
        from obd import isDisplayHardwareAvailable

        # Should return boolean
        result = isDisplayHardwareAvailable()
        self.assertIsInstance(result, bool)


def runTests():
    """Run all tests and return results."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestColors))
    suite.addTests(loader.loadTestsFromTestCase(TestDisplayAdapterExceptions))
    suite.addTests(loader.loadTestsFromTestCase(TestAdafruitDisplayAdapterInit))
    suite.addTests(loader.loadTestsFromTestCase(TestAdafruitDisplayAdapterWithoutHardware))
    suite.addTests(loader.loadTestsFromTestCase(TestAdafruitDisplayAdapterMocked))
    suite.addTests(loader.loadTestsFromTestCase(TestMinimalDisplayDriverAutoRefresh))
    suite.addTests(loader.loadTestsFromTestCase(TestMinimalDisplayDriverInitialization))
    suite.addTests(loader.loadTestsFromTestCase(TestMinimalDisplayDriverLayoutConstants))
    suite.addTests(loader.loadTestsFromTestCase(TestMinimalDisplayDriverStatusScreen))
    suite.addTests(loader.loadTestsFromTestCase(TestMinimalDisplayDriverAlertScreen))
    suite.addTests(loader.loadTestsFromTestCase(TestMinimalDisplayDriverClear))
    suite.addTests(loader.loadTestsFromTestCase(TestDisplayManagerIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestCreateAdafruitAdapter))
    suite.addTests(loader.loadTestsFromTestCase(TestDisplayConstants))
    suite.addTests(loader.loadTestsFromTestCase(TestModuleExports))

    # Run tests
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
    print(f"Skipped: {len(result.skipped)}")

    if result.wasSuccessful():
        print("\nAll tests passed!")
    else:
        print("\nSome tests failed!")
        sys.exit(1)
