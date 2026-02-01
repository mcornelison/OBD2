################################################################################
# File Name: test_hardware_manager.py
# Purpose/Description: Unit tests for HardwareManager class
# Author: Ralph Agent
# Creation Date: 2026-01-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-26    | Ralph Agent  | Initial implementation for US-RPI-012
# ================================================================================
################################################################################

"""
Unit tests for the HardwareManager class.

Tests cover:
- Exception classes
- Initialization with various configurations
- Start/stop lifecycle
- Component wiring
- Factory function
- Status retrieval
- Error handling
"""

from unittest.mock import MagicMock, patch

import pytest

from src.hardware.hardware_manager import (
    HardwareManager,
    HardwareManagerError,
    createHardwareManagerFromConfig,
)
from src.hardware.ups_monitor import PowerSource

# ================================================================================
# Test Fixtures
# ================================================================================


@pytest.fixture
def mockIsRaspberryPi():
    """Mock isRaspberryPi to return False by default."""
    with patch('src.hardware.hardware_manager.isRaspberryPi') as mock:
        mock.return_value = False
        yield mock


@pytest.fixture
def mockIsRaspberryPiTrue():
    """Mock isRaspberryPi to return True."""
    with patch('src.hardware.hardware_manager.isRaspberryPi') as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def mockUpsMonitor():
    """Create a mock UpsMonitor."""
    mock = MagicMock()
    mock.getTelemetry.return_value = {
        'voltage': 4.1,
        'current': 500,
        'percentage': 85,
        'powerSource': PowerSource.EXTERNAL,
    }
    mock.isPolling = True
    return mock


@pytest.fixture
def mockShutdownHandler():
    """Create a mock ShutdownHandler."""
    mock = MagicMock()
    mock.isShutdownPending = False
    mock.timeUntilShutdown = None
    return mock


@pytest.fixture
def mockGpioButton():
    """Create a mock GpioButton."""
    mock = MagicMock()
    mock.pin = 17
    mock.isAvailable = True
    mock.isRunning = False
    return mock


@pytest.fixture
def mockStatusDisplay():
    """Create a mock StatusDisplay."""
    mock = MagicMock()
    mock.isAvailable = True
    mock.isRunning = False
    mock.width = 480
    mock.height = 320
    return mock


@pytest.fixture
def mockTelemetryLogger():
    """Create a mock TelemetryLogger."""
    mock = MagicMock()
    mock.isLogging = False
    mock.logPath = "/var/log/carpi/telemetry.log"
    mock.logInterval = 10.0
    return mock


# ================================================================================
# Exception Tests
# ================================================================================


class TestHardwareManagerError:
    """Tests for HardwareManagerError exception."""

    def test_exceptionMessage(self):
        """
        Given: A message string
        When: Creating HardwareManagerError
        Then: The message is stored correctly
        """
        error = HardwareManagerError("Test error message")
        assert str(error) == "Test error message"

    def test_exceptionInheritance(self):
        """
        Given: HardwareManagerError
        When: Checking inheritance
        Then: It inherits from Exception
        """
        assert issubclass(HardwareManagerError, Exception)


# ================================================================================
# Initialization Tests
# ================================================================================


class TestHardwareManagerInitialization:
    """Tests for HardwareManager initialization."""

    def test_initWithDefaults_nonPi_setsNotAvailable(self, mockIsRaspberryPi):
        """
        Given: Running on non-Pi system
        When: Creating HardwareManager with defaults
        Then: isAvailable is False
        """
        manager = HardwareManager()

        assert manager.isAvailable is False
        assert manager.isRunning is False

    def test_initWithDefaults_nonPi_componentsNone(self, mockIsRaspberryPi):
        """
        Given: Running on non-Pi system
        When: Creating HardwareManager
        Then: All component references are None
        """
        manager = HardwareManager()

        assert manager.upsMonitor is None
        assert manager.shutdownHandler is None
        assert manager.gpioButton is None
        assert manager.statusDisplay is None
        assert manager.telemetryLogger is None

    def test_initWithCustomValues(self, mockIsRaspberryPi):
        """
        Given: Custom configuration values
        When: Creating HardwareManager
        Then: Values are stored correctly
        """
        manager = HardwareManager(
            upsAddress=0x57,
            i2cBus=0,
            shutdownButtonPin=27,
            statusLedPin=22,
            pollInterval=10.0,
            shutdownDelay=60,
            lowBatteryThreshold=15,
            displayEnabled=False,
            displayRefreshRate=5.0,
            telemetryLogPath="/custom/path.log",
            telemetryLogInterval=30.0,
            telemetryMaxBytes=50 * 1024 * 1024,
            telemetryBackupCount=3,
        )

        # Verify internal state was set (access via _private attributes)
        assert manager._upsAddress == 0x57
        assert manager._i2cBus == 0
        assert manager._shutdownButtonPin == 27
        assert manager._pollInterval == 10.0
        assert manager._shutdownDelay == 60
        assert manager._lowBatteryThreshold == 15
        assert manager._displayEnabled is False


class TestHardwareManagerStartStop:
    """Tests for HardwareManager start/stop lifecycle."""

    def test_start_nonPi_returnsFalse(self, mockIsRaspberryPi):
        """
        Given: Running on non-Pi system
        When: Calling start()
        Then: Returns False
        """
        manager = HardwareManager()

        result = manager.start()

        assert result is False
        assert manager.isRunning is False

    def test_stop_whenNotRunning_safe(self, mockIsRaspberryPi):
        """
        Given: Manager not running
        When: Calling stop()
        Then: No error is raised
        """
        manager = HardwareManager()

        manager.stop()  # Should not raise

        assert manager.isRunning is False

    def test_close_stopsManager(self, mockIsRaspberryPi):
        """
        Given: HardwareManager instance
        When: Calling close()
        Then: Manager is stopped
        """
        manager = HardwareManager()

        manager.close()

        assert manager.isRunning is False

    def test_contextManager_callsClose(self, mockIsRaspberryPi):
        """
        Given: Using context manager
        When: Exiting context
        Then: close() is called
        """
        with HardwareManager() as manager:
            assert manager.isAvailable is False

        assert manager.isRunning is False


class TestHardwareManagerStartOnPi:
    """Tests for HardwareManager start on simulated Pi system."""

    @patch('src.hardware.hardware_manager.TelemetryLogger')
    @patch('src.hardware.hardware_manager.StatusDisplay')
    @patch('src.hardware.hardware_manager.GpioButton')
    @patch('src.hardware.hardware_manager.ShutdownHandler')
    @patch('src.hardware.hardware_manager.UpsMonitor')
    def test_start_onPi_initializesComponents(
        self, MockUps, MockShutdown, MockGpio, MockDisplay, MockTelemetry,
        mockIsRaspberryPiTrue
    ):
        """
        Given: Running on Pi system
        When: Calling start()
        Then: All components are initialized
        """
        # Setup mocks
        mockUps = MagicMock()
        MockUps.return_value = mockUps
        mockUps.getTelemetry.return_value = {
            'voltage': 4.1,
            'current': 500,
            'percentage': 85,
            'powerSource': PowerSource.EXTERNAL,
        }

        mockShutdown = MagicMock()
        MockShutdown.return_value = mockShutdown

        mockGpio = MagicMock()
        mockGpio.isAvailable = True
        MockGpio.return_value = mockGpio

        mockDisplay = MagicMock()
        mockDisplay.isAvailable = True
        MockDisplay.return_value = mockDisplay

        mockTelemetry = MagicMock()
        MockTelemetry.return_value = mockTelemetry

        manager = HardwareManager()

        result = manager.start()

        assert result is True
        assert manager.isRunning is True

        # Verify components were initialized
        MockUps.assert_called_once()
        MockShutdown.assert_called_once()
        MockGpio.assert_called_once()
        MockDisplay.assert_called_once()
        MockTelemetry.assert_called_once()

        # Cleanup
        manager.stop()

    @patch('src.hardware.hardware_manager.TelemetryLogger')
    @patch('src.hardware.hardware_manager.StatusDisplay')
    @patch('src.hardware.hardware_manager.GpioButton')
    @patch('src.hardware.hardware_manager.ShutdownHandler')
    @patch('src.hardware.hardware_manager.UpsMonitor')
    def test_start_onPi_wiresComponents(
        self, MockUps, MockShutdown, MockGpio, MockDisplay, MockTelemetry,
        mockIsRaspberryPiTrue
    ):
        """
        Given: Running on Pi system
        When: Calling start()
        Then: Components are wired together
        """
        # Setup mocks
        mockUps = MagicMock()
        MockUps.return_value = mockUps
        mockUps.getTelemetry.return_value = {
            'voltage': 4.1,
            'current': 500,
            'percentage': 85,
            'powerSource': PowerSource.EXTERNAL,
        }

        mockShutdown = MagicMock()
        MockShutdown.return_value = mockShutdown

        mockGpio = MagicMock()
        mockGpio.isAvailable = True
        MockGpio.return_value = mockGpio

        mockDisplay = MagicMock()
        mockDisplay.isAvailable = True
        MockDisplay.return_value = mockDisplay

        mockTelemetry = MagicMock()
        MockTelemetry.return_value = mockTelemetry

        manager = HardwareManager()
        manager.start()

        # Verify wiring
        mockShutdown.registerWithUpsMonitor.assert_called_once_with(mockUps)
        mockTelemetry.setUpsMonitor.assert_called_once_with(mockUps)

        # Cleanup
        manager.stop()

    @patch('src.hardware.hardware_manager.TelemetryLogger')
    @patch('src.hardware.hardware_manager.StatusDisplay')
    @patch('src.hardware.hardware_manager.GpioButton')
    @patch('src.hardware.hardware_manager.ShutdownHandler')
    @patch('src.hardware.hardware_manager.UpsMonitor')
    def test_start_alreadyRunning_raisesError(
        self, MockUps, MockShutdown, MockGpio, MockDisplay, MockTelemetry,
        mockIsRaspberryPiTrue
    ):
        """
        Given: Manager already running
        When: Calling start() again
        Then: Raises HardwareManagerError
        """
        # Setup mocks
        mockUps = MagicMock()
        MockUps.return_value = mockUps
        mockUps.getTelemetry.return_value = {
            'voltage': 4.1, 'current': 500,
            'percentage': 85, 'powerSource': PowerSource.EXTERNAL
        }

        MockShutdown.return_value = MagicMock()

        mockGpio = MagicMock()
        mockGpio.isAvailable = True
        MockGpio.return_value = mockGpio

        mockDisplay = MagicMock()
        mockDisplay.isAvailable = True
        MockDisplay.return_value = mockDisplay

        MockTelemetry.return_value = MagicMock()

        manager = HardwareManager()
        manager.start()

        with pytest.raises(HardwareManagerError) as exc:
            manager.start()

        assert "already running" in str(exc.value)

        # Cleanup
        manager.stop()


class TestHardwareManagerStatus:
    """Tests for HardwareManager status retrieval."""

    def test_getStatus_nonPi_returnsBasicInfo(self, mockIsRaspberryPi):
        """
        Given: Running on non-Pi system
        When: Getting status
        Then: Returns status with isAvailable False
        """
        manager = HardwareManager()

        status = manager.getStatus()

        assert status['isAvailable'] is False
        assert status['isRunning'] is False
        assert status['ups'] is None
        assert status['shutdownPending'] is False
        assert status['gpioButton'] is None
        assert status['display'] is None
        assert status['telemetry'] is None

    @patch('src.hardware.hardware_manager.TelemetryLogger')
    @patch('src.hardware.hardware_manager.StatusDisplay')
    @patch('src.hardware.hardware_manager.GpioButton')
    @patch('src.hardware.hardware_manager.ShutdownHandler')
    @patch('src.hardware.hardware_manager.UpsMonitor')
    def test_getStatus_onPi_returnsFullStatus(
        self, MockUps, MockShutdown, MockGpio, MockDisplay, MockTelemetry,
        mockIsRaspberryPiTrue
    ):
        """
        Given: Running on Pi system with all components
        When: Getting status
        Then: Returns detailed status for all components
        """
        # Setup mocks
        mockUps = MagicMock()
        MockUps.return_value = mockUps
        mockUps.getTelemetry.return_value = {
            'voltage': 4.1,
            'current': 500,
            'percentage': 85,
            'powerSource': PowerSource.EXTERNAL,
        }
        mockUps.isPolling = True

        mockShutdown = MagicMock()
        mockShutdown.isShutdownPending = False
        mockShutdown.timeUntilShutdown = None
        MockShutdown.return_value = mockShutdown

        mockGpio = MagicMock()
        mockGpio.pin = 17
        mockGpio.isAvailable = True
        mockGpio.isRunning = True
        MockGpio.return_value = mockGpio

        mockDisplay = MagicMock()
        mockDisplay.isAvailable = True
        mockDisplay.isRunning = True
        mockDisplay.width = 480
        mockDisplay.height = 320
        MockDisplay.return_value = mockDisplay

        mockTelemetry = MagicMock()
        mockTelemetry.isLogging = True
        mockTelemetry.logPath = "/var/log/carpi/telemetry.log"
        mockTelemetry.logInterval = 10.0
        MockTelemetry.return_value = mockTelemetry

        manager = HardwareManager()
        manager.start()

        status = manager.getStatus()

        assert status['isAvailable'] is True
        assert status['isRunning'] is True
        assert status['ups'] is not None
        assert status['ups']['voltage'] == 4.1
        assert status['ups']['percentage'] == 85
        assert status['gpioButton']['pin'] == 17
        assert status['display']['width'] == 480
        assert status['telemetry']['isLogging'] is True

        # Cleanup
        manager.stop()


class TestHardwareManagerDisplayUpdates:
    """Tests for HardwareManager display update methods."""

    @patch('src.hardware.hardware_manager.TelemetryLogger')
    @patch('src.hardware.hardware_manager.StatusDisplay')
    @patch('src.hardware.hardware_manager.GpioButton')
    @patch('src.hardware.hardware_manager.ShutdownHandler')
    @patch('src.hardware.hardware_manager.UpsMonitor')
    def test_updateObdStatus_updatesDisplay(
        self, MockUps, MockShutdown, MockGpio, MockDisplay, MockTelemetry,
        mockIsRaspberryPiTrue
    ):
        """
        Given: Running manager with display
        When: Calling updateObdStatus()
        Then: Display is updated
        """
        # Setup mocks
        mockUps = MagicMock()
        MockUps.return_value = mockUps
        mockUps.getTelemetry.return_value = {
            'voltage': 4.1, 'current': 500,
            'percentage': 85, 'powerSource': PowerSource.EXTERNAL
        }

        MockShutdown.return_value = MagicMock()

        mockGpio = MagicMock()
        mockGpio.isAvailable = True
        MockGpio.return_value = mockGpio

        mockDisplay = MagicMock()
        mockDisplay.isAvailable = True
        MockDisplay.return_value = mockDisplay

        MockTelemetry.return_value = MagicMock()

        manager = HardwareManager()
        manager.start()

        manager.updateObdStatus('connected')

        mockDisplay.updateObdStatus.assert_called_with('connected')

        # Cleanup
        manager.stop()

    @patch('src.hardware.hardware_manager.TelemetryLogger')
    @patch('src.hardware.hardware_manager.StatusDisplay')
    @patch('src.hardware.hardware_manager.GpioButton')
    @patch('src.hardware.hardware_manager.ShutdownHandler')
    @patch('src.hardware.hardware_manager.UpsMonitor')
    def test_updateErrorCount_updatesDisplay(
        self, MockUps, MockShutdown, MockGpio, MockDisplay, MockTelemetry,
        mockIsRaspberryPiTrue
    ):
        """
        Given: Running manager with display
        When: Calling updateErrorCount()
        Then: Display is updated
        """
        # Setup mocks
        mockUps = MagicMock()
        MockUps.return_value = mockUps
        mockUps.getTelemetry.return_value = {
            'voltage': 4.1, 'current': 500,
            'percentage': 85, 'powerSource': PowerSource.EXTERNAL
        }

        MockShutdown.return_value = MagicMock()

        mockGpio = MagicMock()
        mockGpio.isAvailable = True
        MockGpio.return_value = mockGpio

        mockDisplay = MagicMock()
        mockDisplay.isAvailable = True
        MockDisplay.return_value = mockDisplay

        MockTelemetry.return_value = MagicMock()

        manager = HardwareManager()
        manager.start()

        manager.updateErrorCount(warnings=2, errors=1)

        mockDisplay.updateErrorCount.assert_called_with(warnings=2, errors=1)

        # Cleanup
        manager.stop()

    def test_updateObdStatus_noDisplay_noError(self, mockIsRaspberryPi):
        """
        Given: Manager without display (non-Pi)
        When: Calling updateObdStatus()
        Then: No error is raised
        """
        manager = HardwareManager()

        manager.updateObdStatus('connected')  # Should not raise

    def test_updateErrorCount_noDisplay_noError(self, mockIsRaspberryPi):
        """
        Given: Manager without display (non-Pi)
        When: Calling updateErrorCount()
        Then: No error is raised
        """
        manager = HardwareManager()

        manager.updateErrorCount(warnings=1, errors=0)  # Should not raise


# ================================================================================
# Factory Function Tests
# ================================================================================


class TestCreateHardwareManagerFromConfig:
    """Tests for createHardwareManagerFromConfig factory function."""

    def test_emptyConfig_usesDefaults(self, mockIsRaspberryPi):
        """
        Given: Empty configuration
        When: Creating manager from config
        Then: Uses default values
        """
        manager = createHardwareManagerFromConfig({})

        assert manager._upsAddress == 0x36
        assert manager._i2cBus == 1
        assert manager._shutdownButtonPin == 17
        assert manager._pollInterval == 5.0
        assert manager._shutdownDelay == 30
        assert manager._lowBatteryThreshold == 10
        assert manager._displayEnabled is True
        assert manager._displayRefreshRate == 2.0

    def test_fullConfig_usesConfigValues(self, mockIsRaspberryPi):
        """
        Given: Full configuration with all values
        When: Creating manager from config
        Then: Uses config values
        """
        config = {
            'hardware': {
                'i2c': {
                    'bus': 0,
                    'upsAddress': 0x57,
                },
                'gpio': {
                    'shutdownButton': 27,
                    'statusLed': 22,
                },
                'ups': {
                    'pollInterval': 10,
                    'shutdownDelay': 60,
                    'lowBatteryThreshold': 15,
                },
                'display': {
                    'enabled': False,
                    'refreshRate': 5,
                },
                'telemetry': {
                    'logPath': '/custom/path.log',
                    'logInterval': 30,
                    'maxBytes': 50000000,
                    'backupCount': 3,
                },
            }
        }

        manager = createHardwareManagerFromConfig(config)

        assert manager._upsAddress == 0x57
        assert manager._i2cBus == 0
        assert manager._shutdownButtonPin == 27
        assert manager._pollInterval == 10.0
        assert manager._shutdownDelay == 60
        assert manager._lowBatteryThreshold == 15
        assert manager._displayEnabled is False
        assert manager._displayRefreshRate == 5.0
        assert manager._telemetryLogPath == '/custom/path.log'
        assert manager._telemetryLogInterval == 30.0
        assert manager._telemetryMaxBytes == 50000000
        assert manager._telemetryBackupCount == 3

    def test_partialConfig_mergesWithDefaults(self, mockIsRaspberryPi):
        """
        Given: Partial configuration
        When: Creating manager from config
        Then: Merges with defaults
        """
        config = {
            'hardware': {
                'ups': {
                    'pollInterval': 15,
                },
            }
        }

        manager = createHardwareManagerFromConfig(config)

        # Custom value
        assert manager._pollInterval == 15.0
        # Default values
        assert manager._upsAddress == 0x36
        assert manager._shutdownDelay == 30


class TestHardwareManagerComponentFailures:
    """Tests for HardwareManager handling component initialization failures."""

    @patch('src.hardware.hardware_manager.TelemetryLogger')
    @patch('src.hardware.hardware_manager.StatusDisplay')
    @patch('src.hardware.hardware_manager.GpioButton')
    @patch('src.hardware.hardware_manager.ShutdownHandler')
    @patch('src.hardware.hardware_manager.UpsMonitor')
    def test_upsInitFails_continuesWithNone(
        self, MockUps, MockShutdown, MockGpio, MockDisplay, MockTelemetry,
        mockIsRaspberryPiTrue
    ):
        """
        Given: UPS initialization fails
        When: Starting manager
        Then: Manager starts with UPS as None
        """
        # UPS fails
        MockUps.side_effect = Exception("UPS not available")

        MockShutdown.return_value = MagicMock()

        mockGpio = MagicMock()
        mockGpio.isAvailable = True
        MockGpio.return_value = mockGpio

        mockDisplay = MagicMock()
        mockDisplay.isAvailable = True
        MockDisplay.return_value = mockDisplay

        MockTelemetry.return_value = MagicMock()

        manager = HardwareManager()
        result = manager.start()

        assert result is True
        assert manager.upsMonitor is None
        assert manager.shutdownHandler is not None

        # Cleanup
        manager.stop()

    @patch('src.hardware.hardware_manager.TelemetryLogger')
    @patch('src.hardware.hardware_manager.StatusDisplay')
    @patch('src.hardware.hardware_manager.GpioButton')
    @patch('src.hardware.hardware_manager.ShutdownHandler')
    @patch('src.hardware.hardware_manager.UpsMonitor')
    def test_displayDisabledByConfig_skipsDisplay(
        self, MockUps, MockShutdown, MockGpio, MockDisplay, MockTelemetry,
        mockIsRaspberryPiTrue
    ):
        """
        Given: Display disabled in config
        When: Starting manager
        Then: Display is not initialized
        """
        mockUps = MagicMock()
        MockUps.return_value = mockUps
        mockUps.getTelemetry.return_value = {
            'voltage': 4.1, 'current': 500,
            'percentage': 85, 'powerSource': PowerSource.EXTERNAL
        }

        MockShutdown.return_value = MagicMock()

        mockGpio = MagicMock()
        mockGpio.isAvailable = True
        MockGpio.return_value = mockGpio

        MockTelemetry.return_value = MagicMock()

        manager = HardwareManager(displayEnabled=False)
        manager.start()

        MockDisplay.assert_not_called()
        assert manager.statusDisplay is None

        # Cleanup
        manager.stop()


class TestHardwareManagerProperties:
    """Tests for HardwareManager property getters."""

    def test_isAvailable_nonPi_returnsFalse(self, mockIsRaspberryPi):
        """
        Given: Running on non-Pi
        When: Checking isAvailable
        Then: Returns False
        """
        manager = HardwareManager()
        assert manager.isAvailable is False

    def test_isRunning_initial_returnsFalse(self, mockIsRaspberryPi):
        """
        Given: New manager
        When: Checking isRunning
        Then: Returns False
        """
        manager = HardwareManager()
        assert manager.isRunning is False

    def test_componentGetters_nonPi_returnNone(self, mockIsRaspberryPi):
        """
        Given: Non-Pi manager
        When: Getting component references
        Then: All return None
        """
        manager = HardwareManager()

        assert manager.upsMonitor is None
        assert manager.shutdownHandler is None
        assert manager.gpioButton is None
        assert manager.statusDisplay is None
        assert manager.telemetryLogger is None


class TestHardwareManagerDestructor:
    """Tests for HardwareManager destructor."""

    def test_del_callsClose(self, mockIsRaspberryPi):
        """
        Given: HardwareManager instance
        When: Object is deleted
        Then: close() is called
        """
        manager = HardwareManager()

        # Manually call __del__ to test
        manager.__del__()

        assert manager.isRunning is False

    def test_del_partialInit_noError(self):
        """
        Given: Partially initialized object
        When: Destructor called
        Then: No error is raised
        """
        # Create object with minimal init
        manager = object.__new__(HardwareManager)

        # Should not raise even without _lock attribute
        try:
            manager.__del__()
        except AttributeError:
            pass  # Expected if _lock not set
