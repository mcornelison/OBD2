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
# 2026-04-19    | Ralph Agent  | US-198 (TD-024): thread displayForceSoftwareRenderer
#               |              | through constructor + factory so config.json
#               |              | pi.hardware.statusDisplay.{enabled,
#               |              | forceSoftwareRenderer} reach StatusDisplay.
# 2026-04-22    | Rex (US-216) | Wire PowerDownOrchestrator: thread
#               |              | ShutdownThresholds through constructor +
#               |              | factory; pass suppressLegacyTriggers to
#               |              | ShutdownHandler when ladder enabled; feed
#               |              | orchestrator.tick() from the display-update
#               |              | loop at the UPS poll cadence; open the
#               |              | BatteryHealthRecorder on init.
# 2026-05-01    | Rex (US-252) | DECOUPLE orchestrator.tick from the display
#               |              | loop.  Across 5 drain tests the staged-
#               |              | shutdown ladder NEVER FIRED because tick()
#               |              | rode on _displayUpdateLoop, which only
#               |              | spawned when StatusDisplay successfully
#               |              | initialized.  New: dedicated
#               |              | _powerDownTickLoop on its own thread, started
#               |              | whenever upsMonitor + orchestrator are wired
#               |              | regardless of display state.  Orchestrator
#               |              | tick removed from _displayUpdateLoop; legacy
#               |              | low-battery ShutdownHandler check moved
#               |              | along with it.  Threaded a powerLogWriter
#               |              | callable through constructor + factory so
#               |              | each stage transition leaves a forensic row
#               |              | in power_log.
# 2026-05-16    | Ralph Agent  | T9 follow-up: wire
#               |              | pi.shutdown.poweroffTimeoutSeconds into
#               |              | ShutdownHandler construction (constructor +
#               |              | factory, mirroring the existing pi.* config
#               |              | threading pattern; default 30).
# 2026-05-02    | Rex (US-265) | Discriminator A liveness instrumentation.
#               |              | Drain Test 6 produced 1 power_log row across
#               |              | a 21-min battery window proving US-252's
#               |              | tick/display decouple did not actually fix
#               |              | the ladder.  Hypothesis A from Spool's
#               |              | truth-table: _powerDownTickThread silently
#               |              | never starts or dies immediately.  This
#               |              | patch makes that hypothesis diagnosable in
#               |              | real time: (1) loop entry now logs
#               |              | tid=<id> at INFO so journalctl confirms the
#               |              | OS thread; (2) every loop iteration runs
#               |              | _checkTickThreadHealth, a 60s-cadence
#               |              | snapshot of orchestrator.tickCount that
#               |              | logs ERROR + increments tickHealthAlarmCount
#               |              | when the count has not advanced across a
#               |              | full window while on BATTERY (and stays
#               |              | silent on AC + first BATTERY window).  New
#               |              | constructor parameter
#               |              | tickHealthCheckIntervalS (default 60.0)
#               |              | threaded through the factory from
#               |              | pi.power.tickHealthCheckIntervalS config.
#               |              | The Drain-7 logger CSV's pd_tick_count
#               |              | column + this in-loop alarm together
#               |              | discriminate Sprint 22's hypothesis A.
# 2026-07-01    | Rex (US-427) | TD-058 cleanup: REMOVED the dead
#               |              | batteryHealthRecorder param + store.  It was a
#               |              | ghost of the SS-T5-deleted PowerDownOrchestrator
#               |              | -- constructed in lifecycle.py, threaded through
#               |              | the factory, stored, and NEVER called (grep for
#               |              | startDrainEvent/endDrainEvent -> 0 callers in
#               |              | src/).  The live drain-event writer is the bench
#               |              | CLI scripts/record_drain_test.py (US-427).
# 2026-07-22    | Rex (US-485) | pygame status_display SUNSET.  REMOVED all
#               |              | StatusDisplay wiring now that the HTML carousel
#               |              | is the sole dashboard surface: the import, the
#               |              | _statusDisplay store, _initializeStatusDisplay,
#               |              | the _startComponents display branch +
#               |              | _displayUpdateThread/_displayUpdateLoop, the
#               |              | _cleanup branch, the statusDisplay property, the
#               |              | display* constructor params + factory config
#               |              | reads, and the getStatus 'display' payload
#               |              | (key kept as a permanent None for consumer
#               |              | back-compat).  updateObdStatus/updateErrorCount
#               |              | are retained as no-op stubs so the orchestrator's
#               |              | best-effort status push (event_router) stays
#               |              | valid; OBD status + alert counts now reach the
#               |              | dashboard via the US-480 state-file emitters.
# ================================================================================
################################################################################

"""
Hardware module integration manager for Raspberry Pi.

This module provides the HardwareManager class that initializes and coordinates
all hardware modules (UpsMonitor, ShutdownHandler, GpioButton,
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
from typing import Any

from src.pi.power.types import PowerLogWriter

from .gpio_button import GpioButton, GpioButtonError
from .platform_utils import isRaspberryPi
from .shutdown_handler import ShutdownHandler
from .telemetry_logger import TelemetryLogger
from .ups_monitor import UpsMonitor, UpsMonitorError

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
    - TelemetryLogger: Logs system telemetry to file

    The manager wires these components together:
    - UpsMonitor power-change callback -> ShutdownHandler
    - GpioButton long press -> ShutdownHandler execute shutdown

    On non-Pi systems, hardware modules are not initialized and the manager
    operates in a disabled mode with appropriate warnings.

    Note (US-485): the legacy pygame status_display overlay is retired -- the
    HTML carousel is the sole dashboard surface, fed by the US-480 state-file
    emitters. This manager no longer owns any display.

    Attributes:
        isAvailable: Whether hardware is available on this system
        isRunning: Whether the manager is currently running
        upsMonitor: The UPS monitor instance (or None if not available)
        shutdownHandler: The shutdown handler instance (or None)
        gpioButton: The GPIO button instance (or None)
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
        telemetryLogPath: str = "/var/log/carpi/telemetry.log",
        telemetryLogInterval: float = 10.0,
        telemetryMaxBytes: int = 100 * 1024 * 1024,
        telemetryBackupCount: int = 7,
        powerLogWriter: PowerLogWriter | None = None,
        poweroffTimeoutSeconds: int = 30,
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
            telemetryLogPath: Path to telemetry log file
            telemetryLogInterval: Telemetry logging interval in seconds (default: 10.0)
            telemetryMaxBytes: Maximum telemetry log file size (default: 100MB)
            telemetryBackupCount: Number of telemetry backup files (default: 7)
            powerLogWriter: Lifecycle-owned ``(eventType, vcell)``
                callable that persists power events to ``power_log``.
                Lifecycle constructs a closure over the live ObdDatabase
                and passes it in so hardware_manager doesn't own
                database construction. None is fine.
            poweroffTimeoutSeconds: T9 follow-up. Seconds the
                ShutdownHandler waits on the ``systemctl poweroff``
                subprocess before timing out (default 30). Threaded
                from pi.shutdown.poweroffTimeoutSeconds config.
        """
        self._upsAddress = upsAddress
        self._i2cBus = i2cBus
        self._shutdownButtonPin = shutdownButtonPin
        self._statusLedPin = statusLedPin
        self._pollInterval = pollInterval
        self._shutdownDelay = shutdownDelay
        self._lowBatteryThreshold = lowBatteryThreshold
        self._telemetryLogPath = telemetryLogPath
        self._telemetryLogInterval = telemetryLogInterval
        self._telemetryMaxBytes = telemetryMaxBytes
        self._telemetryBackupCount = telemetryBackupCount
        self._powerLogWriter = powerLogWriter
        self._poweroffTimeoutSeconds = poweroffTimeoutSeconds

        # Component instances (initialized on start)
        self._upsMonitor: UpsMonitor | None = None
        self._shutdownHandler: ShutdownHandler | None = None
        self._gpioButton: GpioButton | None = None
        self._telemetryLogger: TelemetryLogger | None = None

        # State
        self._isAvailable = isRaspberryPi()
        self._isRunning = False
        self._lock = threading.Lock()

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
        """Initialize the shutdown handler.

        Phase-2 cutover: eclipse-powerwatch is the SOLE shutdown decider.
        The legacy in-app automatic low-battery trigger must never fire
        (no dual deciders), so ``suppressLegacyTriggers`` is now
        unconditionally True.  The physical GPIO shutdown BUTTON path is
        a separate ShutdownHandler concern and remains functional --
        only the automatic battery-driven in-app trigger is suppressed.
        """
        self._shutdownHandler = ShutdownHandler(
            shutdownDelay=self._shutdownDelay,
            lowBatteryThreshold=self._lowBatteryThreshold,
            suppressLegacyTriggers=True,
            poweroffTimeoutSeconds=self._poweroffTimeoutSeconds,
        )
        logger.debug(
            "Shutdown handler initialized (suppressLegacyTriggers=True; "
            "eclipse-powerwatch is sole shutdown decider)"
        )

    def _initializeGpioButton(self) -> None:
        """Initialize the GPIO button."""
        try:
            self._gpioButton = GpioButton(pin=self._shutdownButtonPin)
            logger.debug("GPIO button initialized")
        except GpioButtonError as e:
            logger.warning(f"Failed to initialize GPIO button: {e}")
            self._gpioButton = None

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

        # Start telemetry logging
        if self._telemetryLogger is not None:
            try:
                self._telemetryLogger.start()
                logger.debug("Telemetry logger started")
            except Exception as e:
                logger.warning(f"Failed to start telemetry logger: {e}")

    def _cleanup(self) -> None:
        """Clean up all hardware components."""
        # Stop telemetry logger
        if self._telemetryLogger is not None:
            try:
                self._telemetryLogger.close()
            except Exception as e:
                logger.warning(f"Error closing telemetry logger: {e}")
            self._telemetryLogger = None

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

    def getStatus(self) -> dict[str, Any]:
        """
        Get the current status of all hardware components.

        Returns:
            Dictionary with status information for each component:
            - isAvailable: Whether hardware is available
            - isRunning: Whether the manager is running
            - ups: UPS status (voltage, percentage, powerSource) or None
            - shutdownPending: Whether a shutdown is pending
            - gpioButton: GPIO button status or None
            - display: Always None (US-485: the pygame status overlay is
              retired; key retained for consumer back-compat)
            - telemetry: Telemetry logger status or None
        """
        status: dict[str, Any] = {
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
                    'percentage': telemetry['percentage'],
                    'chargeRatePctPerHr': telemetry['chargeRatePctPerHr'],
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

        # Status display retired (US-485): 'display' stays None (set in the
        # initial status dict) -- the HTML carousel is the sole surface.

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
        No-op since US-485 (pygame status overlay retired).

        Retained so the orchestrator's best-effort status push
        (``event_router``) stays valid without an ``AttributeError``. OBD
        connection status now reaches the HTML dashboard through the US-480
        ``system-status`` state-file emitter, not this manager.

        Args:
            status: Connection status ('connected', 'disconnected', 'reconnecting')
        """

    def updateErrorCount(self, warnings: int = 0, errors: int = 0) -> None:
        """
        No-op since US-485 (pygame status overlay retired).

        Retained so the orchestrator's best-effort alert-count push
        (``event_router``) stays valid without an ``AttributeError``. Alert
        state now reaches the HTML dashboard through the US-480 emitters, not
        this manager.

        Args:
            warnings: Number of warnings
            errors: Number of errors
        """

    @property
    def isAvailable(self) -> bool:
        """Check if hardware is available on this system."""
        return self._isAvailable

    @property
    def isRunning(self) -> bool:
        """Check if the manager is currently running."""
        return self._isRunning

    @property
    def upsMonitor(self) -> UpsMonitor | None:
        """Get the UPS monitor instance (or None if not available)."""
        return self._upsMonitor

    @property
    def shutdownHandler(self) -> ShutdownHandler | None:
        """Get the shutdown handler instance (or None)."""
        return self._shutdownHandler

    @property
    def gpioButton(self) -> GpioButton | None:
        """Get the GPIO button instance (or None if not available)."""
        return self._gpioButton

    @property
    def telemetryLogger(self) -> TelemetryLogger | None:
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


def createHardwareManagerFromConfig(
    config: dict[str, Any],
    powerLogWriter: PowerLogWriter | None = None,
) -> HardwareManager:
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
    # US-485: the pygame status_display overlay is retired -- the HTML carousel
    # is the sole dashboard surface (fed by the US-480 state-file emitters). The
    # former pi.hardware.statusDisplay.* config keys are gone; nothing here reads
    # them anymore.
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

    # T9 follow-up: pi.shutdown.poweroffTimeoutSeconds bounds the
    # ShutdownHandler's `systemctl poweroff` subprocess wait.  Default
    # 30 == old hardcoded value, so no behavioral regression; wiring
    # this through finally makes the validated config knob live.
    poweroffTimeoutSeconds = int(
        getConfigValue('pi.shutdown.poweroffTimeoutSeconds', 30)
    )

    return HardwareManager(
        upsAddress=upsAddress,
        i2cBus=i2cBus,
        shutdownButtonPin=shutdownButtonPin,
        statusLedPin=statusLedPin,
        pollInterval=float(pollInterval),
        shutdownDelay=int(shutdownDelay),
        lowBatteryThreshold=int(lowBatteryThreshold),
        telemetryLogPath=telemetryLogPath,
        telemetryLogInterval=float(telemetryLogInterval),
        telemetryMaxBytes=int(telemetryMaxBytes),
        telemetryBackupCount=int(telemetryBackupCount),
        powerLogWriter=powerLogWriter,
        poweroffTimeoutSeconds=poweroffTimeoutSeconds,
    )
