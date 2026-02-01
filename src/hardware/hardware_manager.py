################################################################################
# File Name: hardware_manager.py
# Purpose/Description: Hardware module integration manager for Raspberry Pi
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
Hardware module integration manager for Raspberry Pi.

This module provides the HardwareManager class that initializes and coordinates
all hardware modules (UpsMonitor, ShutdownHandler, GpioButton, StatusDisplay,
TelemetryLogger) and wires them together for integrated operation.

Usage:
    from hardware import HardwareManager, createHardwareManagerFromConfig

    # Create from config
    manager = createHardwareManagerFromConfig(config)

    # Start all hardware modules
    manager.start()

    # Get status
    status = manager.getStatus()

    # Stop all hardware modules
    manager.stop()

Note:
    On non-Raspberry Pi systems, the HardwareManager will skip initialization
    of hardware-specific modules and log warnings. This allows the application
    to run on development machines without hardware.
"""

import logging
import threading
from typing import Any, Dict, Optional

from .gpio_button import GpioButton, GpioButtonError
from .platform_utils import isRaspberryPi
from .shutdown_handler import ShutdownHandler
from .status_display import StatusDisplay, StatusDisplayError
from .telemetry_logger import TelemetryLogger
from .ups_monitor import PowerSource, UpsMonitor, UpsMonitorError

logger = logging.getLogger(__name__)


# ================================================================================
# Hardware Manager Exceptions
# ================================================================================


class HardwareManagerError(Exception):
    """Base exception for hardware manager errors."""
    pass


# ================================================================================
# Hardware Manager Class
# ================================================================================


class HardwareManager:
    """
    Manager for all hardware modules on Raspberry Pi.

    Initializes and coordinates the following hardware modules:
    - UpsMonitor: Monitors UPS battery status
    - ShutdownHandler: Handles graceful shutdown on power loss
    - GpioButton: Handles physical shutdown button
    - StatusDisplay: Shows system status on display
    - TelemetryLogger: Logs system telemetry to file

    The manager wires these components together:
    - UpsMonitor power-change callback -> ShutdownHandler
    - UpsMonitor readings -> StatusDisplay updates
    - GpioButton long press -> ShutdownHandler execute shutdown

    On non-Pi systems, hardware modules are not initialized and the manager
    operates in a disabled mode with appropriate warnings.

    Attributes:
        isAvailable: Whether hardware is available on this system
        isRunning: Whether the manager is currently running
        upsMonitor: The UPS monitor instance (or None if not available)
        shutdownHandler: The shutdown handler instance (or None)
        gpioButton: The GPIO button instance (or None)
        statusDisplay: The status display instance (or None)
        telemetryLogger: The telemetry logger instance (or None)

    Example:
        manager = HardwareManager()
        manager.start()
        status = manager.getStatus()
        manager.stop()
    """

    def __init__(
        self,
        upsAddress: int = 0x36,
        i2cBus: int = 1,
        shutdownButtonPin: int = 17,
        statusLedPin: int = 27,
        pollInterval: float = 5.0,
        shutdownDelay: int = 30,
        lowBatteryThreshold: int = 10,
        displayEnabled: bool = True,
        displayRefreshRate: float = 2.0,
        telemetryLogPath: str = "/var/log/carpi/telemetry.log",
        telemetryLogInterval: float = 10.0,
        telemetryMaxBytes: int = 100 * 1024 * 1024,
        telemetryBackupCount: int = 7,
    ):
        """
        Initialize the hardware manager.

        Args:
            upsAddress: I2C address of the UPS (default: 0x36)
            i2cBus: I2C bus number (default: 1)
            shutdownButtonPin: GPIO pin for shutdown button (default: 17)
            statusLedPin: GPIO pin for status LED (default: 27, currently unused)
            pollInterval: UPS polling interval in seconds (default: 5.0)
            shutdownDelay: Seconds to wait before shutdown on power loss (default: 30)
            lowBatteryThreshold: Battery percentage for immediate shutdown (default: 10)
            displayEnabled: Whether to enable the status display (default: True)
            displayRefreshRate: Display refresh rate in seconds (default: 2.0)
            telemetryLogPath: Path to telemetry log file
            telemetryLogInterval: Telemetry logging interval in seconds (default: 10.0)
            telemetryMaxBytes: Maximum telemetry log file size (default: 100MB)
            telemetryBackupCount: Number of telemetry backup files (default: 7)
        """
        self._upsAddress = upsAddress
        self._i2cBus = i2cBus
        self._shutdownButtonPin = shutdownButtonPin
        self._statusLedPin = statusLedPin
        self._pollInterval = pollInterval
        self._shutdownDelay = shutdownDelay
        self._lowBatteryThreshold = lowBatteryThreshold
        self._displayEnabled = displayEnabled
        self._displayRefreshRate = displayRefreshRate
        self._telemetryLogPath = telemetryLogPath
        self._telemetryLogInterval = telemetryLogInterval
        self._telemetryMaxBytes = telemetryMaxBytes
        self._telemetryBackupCount = telemetryBackupCount

        # Component instances (initialized on start)
        self._upsMonitor: Optional[UpsMonitor] = None
        self._shutdownHandler: Optional[ShutdownHandler] = None
        self._gpioButton: Optional[GpioButton] = None
        self._statusDisplay: Optional[StatusDisplay] = None
        self._telemetryLogger: Optional[TelemetryLogger] = None

        # State
        self._isAvailable = isRaspberryPi()
        self._isRunning = False
        self._lock = threading.Lock()

        # Display update thread
        self._displayUpdateThread: Optional[threading.Thread] = None
        self._stopEvent = threading.Event()

        if not self._isAvailable:
            logger.warning(
                "Hardware manager: Not running on Raspberry Pi. "
                "Hardware modules will be disabled."
            )

        logger.debug(
            f"HardwareManager initialized: available={self._isAvailable}, "
            f"upsAddress=0x{upsAddress:02x}, i2cBus={i2cBus}, "
            f"shutdownButtonPin={shutdownButtonPin}"
        )

    def start(self) -> bool:
        """
        Start all hardware modules.

        Initializes and starts all hardware components, wiring them together
        for integrated operation. On non-Pi systems, logs a warning and
        returns False.

        Returns:
            True if hardware modules started successfully, False if not available

        Raises:
            HardwareManagerError: If manager is already running
        """
        with self._lock:
            if self._isRunning:
                raise HardwareManagerError("Hardware manager is already running")

            if not self._isAvailable:
                logger.warning(
                    "Cannot start hardware manager - not running on Raspberry Pi"
                )
                return False

            try:
                # Initialize components in order
                self._initializeUpsMonitor()
                self._initializeShutdownHandler()
                self._initializeGpioButton()
                self._initializeStatusDisplay()
                self._initializeTelemetryLogger()

                # Wire components together
                self._wireComponents()

                # Start components
                self._startComponents()

                self._isRunning = True
                logger.info("Hardware manager started successfully")
                return True

            except Exception as e:
                logger.error(f"Failed to start hardware manager: {e}")
                self._cleanup()
                raise HardwareManagerError(
                    f"Failed to start hardware manager: {e}"
                ) from e

    def stop(self) -> None:
        """
        Stop all hardware modules.

        Stops all running hardware components and releases resources.
        Safe to call even if not running.
        """
        with self._lock:
            if not self._isRunning:
                return

            logger.info("Stopping hardware manager...")
            self._stopEvent.set()

            # Stop display update thread
            if (self._displayUpdateThread is not None and
                    self._displayUpdateThread.is_alive()):
                self._displayUpdateThread.join(timeout=5.0)

            self._cleanup()
            self._isRunning = False
            logger.info("Hardware manager stopped")

    def _initializeUpsMonitor(self) -> None:
        """Initialize the UPS monitor."""
        try:
            self._upsMonitor = UpsMonitor(
                address=self._upsAddress,
                bus=self._i2cBus,
                pollInterval=self._pollInterval
            )
            logger.debug("UPS monitor initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize UPS monitor: {e}")
            self._upsMonitor = None

    def _initializeShutdownHandler(self) -> None:
        """Initialize the shutdown handler."""
        self._shutdownHandler = ShutdownHandler(
            shutdownDelay=self._shutdownDelay,
            lowBatteryThreshold=self._lowBatteryThreshold
        )
        logger.debug("Shutdown handler initialized")

    def _initializeGpioButton(self) -> None:
        """Initialize the GPIO button."""
        try:
            self._gpioButton = GpioButton(pin=self._shutdownButtonPin)
            logger.debug("GPIO button initialized")
        except GpioButtonError as e:
            logger.warning(f"Failed to initialize GPIO button: {e}")
            self._gpioButton = None

    def _initializeStatusDisplay(self) -> None:
        """Initialize the status display."""
        if not self._displayEnabled:
            logger.debug("Status display disabled by configuration")
            return

        try:
            self._statusDisplay = StatusDisplay(
                refreshRate=self._displayRefreshRate
            )
            logger.debug("Status display initialized")
        except StatusDisplayError as e:
            logger.warning(f"Failed to initialize status display: {e}")
            self._statusDisplay = None

    def _initializeTelemetryLogger(self) -> None:
        """Initialize the telemetry logger."""
        try:
            self._telemetryLogger = TelemetryLogger(
                logPath=self._telemetryLogPath,
                logInterval=self._telemetryLogInterval,
                maxBytes=self._telemetryMaxBytes,
                backupCount=self._telemetryBackupCount
            )
            logger.debug("Telemetry logger initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize telemetry logger: {e}")
            self._telemetryLogger = None

    def _wireComponents(self) -> None:
        """Wire hardware components together."""
        # Wire UPS monitor to shutdown handler
        if self._upsMonitor is not None and self._shutdownHandler is not None:
            self._shutdownHandler.registerWithUpsMonitor(self._upsMonitor)
            logger.debug("Wired UPS monitor -> shutdown handler")

        # Wire GPIO button long press to shutdown
        if self._gpioButton is not None and self._shutdownHandler is not None:
            self._gpioButton.onLongPress = self._shutdownHandler._executeShutdown
            logger.debug("Wired GPIO button -> shutdown handler")

        # Wire UPS monitor to telemetry logger
        if self._upsMonitor is not None and self._telemetryLogger is not None:
            self._telemetryLogger.setUpsMonitor(self._upsMonitor)
            logger.debug("Wired UPS monitor -> telemetry logger")

    def _startComponents(self) -> None:
        """Start all hardware components."""
        # Start UPS monitoring
        if self._upsMonitor is not None:
            try:
                self._upsMonitor.startPolling()
                logger.debug("UPS polling started")
            except Exception as e:
                logger.warning(f"Failed to start UPS polling: {e}")

        # Start GPIO button
        if self._gpioButton is not None:
            try:
                self._gpioButton.start()
                logger.debug("GPIO button started")
            except GpioButtonError as e:
                logger.warning(f"Failed to start GPIO button: {e}")

        # Start status display
        if self._statusDisplay is not None:
            try:
                self._statusDisplay.start()
                logger.debug("Status display started")

                # Start display update thread
                self._stopEvent.clear()
                self._displayUpdateThread = threading.Thread(
                    target=self._displayUpdateLoop,
                    name="HardwareDisplayUpdate",
                    daemon=True
                )
                self._displayUpdateThread.start()
            except StatusDisplayError as e:
                logger.warning(f"Failed to start status display: {e}")

        # Start telemetry logging
        if self._telemetryLogger is not None:
            try:
                self._telemetryLogger.start()
                logger.debug("Telemetry logger started")
            except Exception as e:
                logger.warning(f"Failed to start telemetry logger: {e}")

    def _displayUpdateLoop(self) -> None:
        """Background loop for updating display with UPS readings."""
        while not self._stopEvent.is_set():
            try:
                if self._upsMonitor is not None and self._statusDisplay is not None:
                    # Get UPS telemetry
                    try:
                        telemetry = self._upsMonitor.getTelemetry()

                        # Update battery info
                        self._statusDisplay.updateBatteryInfo(
                            percentage=telemetry['percentage'],
                            voltage=telemetry['voltage']
                        )

                        # Update power source
                        powerSource = telemetry['powerSource']
                        if powerSource == PowerSource.EXTERNAL:
                            self._statusDisplay.updatePowerSource('external')
                        elif powerSource == PowerSource.BATTERY:
                            self._statusDisplay.updatePowerSource('battery')
                        else:
                            self._statusDisplay.updatePowerSource('unknown')

                        # Check for low battery
                        if (self._shutdownHandler is not None and
                                telemetry['percentage'] is not None):
                            self._shutdownHandler.onLowBattery(
                                telemetry['percentage']
                            )

                    except UpsMonitorError as e:
                        logger.debug(f"Could not get UPS telemetry: {e}")

            except Exception as e:
                logger.error(f"Error in display update loop: {e}")

            # Wait for next update interval (use UPS poll interval)
            self._stopEvent.wait(timeout=self._pollInterval)

    def _cleanup(self) -> None:
        """Clean up all hardware components."""
        # Stop telemetry logger
        if self._telemetryLogger is not None:
            try:
                self._telemetryLogger.close()
            except Exception as e:
                logger.warning(f"Error closing telemetry logger: {e}")
            self._telemetryLogger = None

        # Stop status display
        if self._statusDisplay is not None:
            try:
                self._statusDisplay.close()
            except Exception as e:
                logger.warning(f"Error closing status display: {e}")
            self._statusDisplay = None

        # Stop GPIO button
        if self._gpioButton is not None:
            try:
                self._gpioButton.close()
            except Exception as e:
                logger.warning(f"Error closing GPIO button: {e}")
            self._gpioButton = None

        # Stop shutdown handler
        if self._shutdownHandler is not None:
            try:
                self._shutdownHandler.close()
            except Exception as e:
                logger.warning(f"Error closing shutdown handler: {e}")
            self._shutdownHandler = None

        # Stop UPS monitor
        if self._upsMonitor is not None:
            try:
                self._upsMonitor.close()
            except Exception as e:
                logger.warning(f"Error closing UPS monitor: {e}")
            self._upsMonitor = None

        self._displayUpdateThread = None
        self._stopEvent.clear()

    def getStatus(self) -> Dict[str, Any]:
        """
        Get the current status of all hardware components.

        Returns:
            Dictionary with status information for each component:
            - isAvailable: Whether hardware is available
            - isRunning: Whether the manager is running
            - ups: UPS status (voltage, percentage, powerSource) or None
            - shutdownPending: Whether a shutdown is pending
            - gpioButton: GPIO button status or None
            - display: Display status or None
            - telemetry: Telemetry logger status or None
        """
        status: Dict[str, Any] = {
            'isAvailable': self._isAvailable,
            'isRunning': self._isRunning,
            'ups': None,
            'shutdownPending': False,
            'timeUntilShutdown': None,
            'gpioButton': None,
            'display': None,
            'telemetry': None,
        }

        # UPS status
        if self._upsMonitor is not None:
            try:
                telemetry = self._upsMonitor.getTelemetry()
                status['ups'] = {
                    'voltage': telemetry['voltage'],
                    'current': telemetry['current'],
                    'percentage': telemetry['percentage'],
                    'powerSource': telemetry['powerSource'].value,
                    'isPolling': self._upsMonitor.isPolling,
                }
            except UpsMonitorError as e:
                status['ups'] = {'error': str(e)}

        # Shutdown handler status
        if self._shutdownHandler is not None:
            status['shutdownPending'] = self._shutdownHandler.isShutdownPending
            status['timeUntilShutdown'] = self._shutdownHandler.timeUntilShutdown

        # GPIO button status
        if self._gpioButton is not None:
            status['gpioButton'] = {
                'pin': self._gpioButton.pin,
                'isAvailable': self._gpioButton.isAvailable,
                'isRunning': self._gpioButton.isRunning,
            }

        # Status display status
        if self._statusDisplay is not None:
            status['display'] = {
                'isAvailable': self._statusDisplay.isAvailable,
                'isRunning': self._statusDisplay.isRunning,
                'width': self._statusDisplay.width,
                'height': self._statusDisplay.height,
            }

        # Telemetry logger status
        if self._telemetryLogger is not None:
            status['telemetry'] = {
                'isLogging': self._telemetryLogger.isLogging,
                'logPath': self._telemetryLogger.logPath,
                'logInterval': self._telemetryLogger.logInterval,
            }

        return status

    def updateObdStatus(self, status: str) -> None:
        """
        Update OBD2 connection status on the display.

        Args:
            status: Connection status ('connected', 'disconnected', 'reconnecting')
        """
        if self._statusDisplay is not None:
            self._statusDisplay.updateObdStatus(status)

    def updateErrorCount(self, warnings: int = 0, errors: int = 0) -> None:
        """
        Update error and warning counts on the display.

        Args:
            warnings: Number of warnings
            errors: Number of errors
        """
        if self._statusDisplay is not None:
            self._statusDisplay.updateErrorCount(warnings=warnings, errors=errors)

    @property
    def isAvailable(self) -> bool:
        """Check if hardware is available on this system."""
        return self._isAvailable

    @property
    def isRunning(self) -> bool:
        """Check if the manager is currently running."""
        return self._isRunning

    @property
    def upsMonitor(self) -> Optional[UpsMonitor]:
        """Get the UPS monitor instance (or None if not available)."""
        return self._upsMonitor

    @property
    def shutdownHandler(self) -> Optional[ShutdownHandler]:
        """Get the shutdown handler instance (or None)."""
        return self._shutdownHandler

    @property
    def gpioButton(self) -> Optional[GpioButton]:
        """Get the GPIO button instance (or None if not available)."""
        return self._gpioButton

    @property
    def statusDisplay(self) -> Optional[StatusDisplay]:
        """Get the status display instance (or None if not available)."""
        return self._statusDisplay

    @property
    def telemetryLogger(self) -> Optional[TelemetryLogger]:
        """Get the telemetry logger instance (or None if not available)."""
        return self._telemetryLogger

    def close(self) -> None:
        """
        Close the hardware manager and release all resources.

        Safe to call multiple times.
        """
        self.stop()
        logger.debug("HardwareManager closed")

    def __enter__(self) -> 'HardwareManager':
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - close the manager."""
        self.close()

    def __del__(self) -> None:
        """Destructor - ensure resources are released."""
        # Check for _lock to handle partially initialized objects
        if hasattr(self, '_lock'):
            self.close()


# ================================================================================
# Factory Function
# ================================================================================


def createHardwareManagerFromConfig(config: Dict[str, Any]) -> HardwareManager:
    """
    Create a HardwareManager from configuration dictionary.

    Args:
        config: Configuration dictionary with hardware settings:
            - hardware.enabled: Whether hardware is enabled (default: True)
            - hardware.i2c.bus: I2C bus number (default: 1)
            - hardware.i2c.upsAddress: UPS I2C address (default: 0x36)
            - hardware.gpio.shutdownButton: Shutdown button GPIO pin (default: 17)
            - hardware.gpio.statusLed: Status LED GPIO pin (default: 27)
            - hardware.ups.pollInterval: UPS poll interval (default: 5)
            - hardware.ups.shutdownDelay: Shutdown delay (default: 30)
            - hardware.ups.lowBatteryThreshold: Low battery threshold (default: 10)
            - hardware.display.enabled: Display enabled (default: True)
            - hardware.display.refreshRate: Display refresh rate (default: 2)
            - hardware.telemetry.logPath: Telemetry log path
            - hardware.telemetry.logInterval: Telemetry log interval (default: 10)
            - hardware.telemetry.maxBytes: Max log file size (default: 100MB)
            - hardware.telemetry.backupCount: Backup file count (default: 7)

    Returns:
        Configured HardwareManager instance

    Example:
        config = {'hardware': {'i2c': {'bus': 1, 'upsAddress': 0x36}}}
        manager = createHardwareManagerFromConfig(config)
    """
    # Helper to get nested config value with default
    def getConfigValue(path: str, default: Any) -> Any:
        """Get nested config value using dot notation."""
        keys = path.split('.')
        value = config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    # Extract configuration values
    i2cBus = getConfigValue('hardware.i2c.bus', 1)
    upsAddress = getConfigValue('hardware.i2c.upsAddress', 0x36)
    shutdownButtonPin = getConfigValue('hardware.gpio.shutdownButton', 17)
    statusLedPin = getConfigValue('hardware.gpio.statusLed', 27)
    pollInterval = getConfigValue('hardware.ups.pollInterval', 5)
    shutdownDelay = getConfigValue('hardware.ups.shutdownDelay', 30)
    lowBatteryThreshold = getConfigValue('hardware.ups.lowBatteryThreshold', 10)
    displayEnabled = getConfigValue('hardware.display.enabled', True)
    displayRefreshRate = getConfigValue('hardware.display.refreshRate', 2.0)
    telemetryLogPath = getConfigValue(
        'hardware.telemetry.logPath',
        '/var/log/carpi/telemetry.log'
    )
    telemetryLogInterval = getConfigValue('hardware.telemetry.logInterval', 10.0)
    telemetryMaxBytes = getConfigValue(
        'hardware.telemetry.maxBytes',
        100 * 1024 * 1024
    )
    telemetryBackupCount = getConfigValue('hardware.telemetry.backupCount', 7)

    return HardwareManager(
        upsAddress=upsAddress,
        i2cBus=i2cBus,
        shutdownButtonPin=shutdownButtonPin,
        statusLedPin=statusLedPin,
        pollInterval=float(pollInterval),
        shutdownDelay=int(shutdownDelay),
        lowBatteryThreshold=int(lowBatteryThreshold),
        displayEnabled=displayEnabled,
        displayRefreshRate=float(displayRefreshRate),
        telemetryLogPath=telemetryLogPath,
        telemetryLogInterval=float(telemetryLogInterval),
        telemetryMaxBytes=int(telemetryMaxBytes),
        telemetryBackupCount=int(telemetryBackupCount),
    )
