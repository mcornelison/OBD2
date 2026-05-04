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
import time
from typing import Any

from src.pi.power.battery_health import BatteryHealthRecorder
from src.pi.power.orchestrator import (
    PowerDownOrchestrator,
    PowerLogWriter,
    ShutdownThresholds,
)

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
        displayForceSoftwareRenderer: bool = True,
        telemetryLogPath: str = "/var/log/carpi/telemetry.log",
        telemetryLogInterval: float = 10.0,
        telemetryMaxBytes: int = 100 * 1024 * 1024,
        telemetryBackupCount: int = 7,
        shutdownThresholds: ShutdownThresholds | None = None,
        batteryHealthRecorder: BatteryHealthRecorder | None = None,
        powerLogWriter: PowerLogWriter | None = None,
        tickHealthCheckIntervalS: float = 60.0,
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
            displayForceSoftwareRenderer: Force SDL software renderer for the
                status_display overlay (default: True). Fix for TD-024 GL
                BadAccess under X11. See StatusDisplay.__init__ for details.
            telemetryLogPath: Path to telemetry log file
            telemetryLogInterval: Telemetry logging interval in seconds (default: 10.0)
            telemetryMaxBytes: Maximum telemetry log file size (default: 100MB)
            telemetryBackupCount: Number of telemetry backup files (default: 7)
            shutdownThresholds: US-216 staged-shutdown config. When
                ``enabled=True`` (the default once config is wired), the
                PowerDownOrchestrator drives the shutdown path and the
                legacy ShutdownHandler 30s timer + 10% trigger are
                suppressed. None = preserve pre-US-216 behavior.
            batteryHealthRecorder: US-217 drain-event writer. Required
                when shutdownThresholds is set; passed in so hardware_manager
                doesn't own database construction. None is fine when
                shutdownThresholds is None.
            powerLogWriter: US-252 ``(eventType, vcell)`` callable that
                persists PowerDownOrchestrator stage transitions to
                ``power_log``.  Lifecycle constructs a closure over the
                live ObdDatabase and passes it in so hardware_manager
                doesn't own database construction. None is fine -- the
                orchestrator handles a missing writer as a no-op.
            tickHealthCheckIntervalS: US-265 cadence (seconds) for the
                in-loop ``_powerDownTickThread`` liveness probe.  At
                this cadence the loop snapshots the orchestrator's
                ``tickCount`` and, when the prior window was on
                BATTERY, raises an ERROR-level alarm if the counter
                did not advance.  Default 60.0; tests pass 0.0 to
                disable the throttle so the check runs on every loop
                iteration.
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
        self._displayForceSoftwareRenderer = displayForceSoftwareRenderer
        self._telemetryLogPath = telemetryLogPath
        self._telemetryLogInterval = telemetryLogInterval
        self._telemetryMaxBytes = telemetryMaxBytes
        self._telemetryBackupCount = telemetryBackupCount
        self._shutdownThresholds = shutdownThresholds
        self._batteryHealthRecorder = batteryHealthRecorder
        self._powerLogWriter = powerLogWriter
        self._tickHealthCheckIntervalS = tickHealthCheckIntervalS

        # US-265 tick-thread liveness state.  The check fires only when
        # the prior snapshot was on BATTERY -- AC operation is allowed
        # to leave tickCount unchanged across windows (the orchestrator
        # legitimately skips work when source != BATTERY in some paths;
        # though the US-262 counter increments BEFORE early-returns,
        # gating the alarm on prior-BATTERY keeps the contract simple).
        self._lastTickHealthCheckMono: float = time.monotonic()
        self._lastTickHealthCheckCount: int = 0
        self._lastTickHealthCheckOnBattery: bool = False
        self._tickHealthAlarmCount: int = 0

        # Component instances (initialized on start)
        self._upsMonitor: UpsMonitor | None = None
        self._shutdownHandler: ShutdownHandler | None = None
        self._gpioButton: GpioButton | None = None
        self._statusDisplay: StatusDisplay | None = None
        self._telemetryLogger: TelemetryLogger | None = None
        self._powerDownOrchestrator: PowerDownOrchestrator | None = None

        # State
        self._isAvailable = isRaspberryPi()
        self._isRunning = False
        self._lock = threading.Lock()

        # Display update thread
        self._displayUpdateThread: threading.Thread | None = None
        # US-252: dedicated ladder thread, started independently of the
        # display.  Across 5 drain tests the staged-shutdown ladder NEVER
        # FIRED because the orchestrator's tick() was gated on the
        # display-update thread (which only spawns when statusDisplay
        # initializes).  Decoupling moves the safety-critical path off
        # the UI dependency.
        self._powerDownTickThread: threading.Thread | None = None
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
                self._initializePowerDownOrchestrator()
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

            # US-252: stop dedicated power-down tick thread
            if (self._powerDownTickThread is not None and
                    self._powerDownTickThread.is_alive()):
                self._powerDownTickThread.join(timeout=5.0)

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
        # US-216: when a staged-ladder config is provided AND it's enabled,
        # suppress the legacy ShutdownHandler auto-trigger paths to prevent
        # the TD-D race with the new PowerDownOrchestrator.
        suppressLegacy = bool(
            self._shutdownThresholds is not None
            and self._shutdownThresholds.enabled
        )
        self._shutdownHandler = ShutdownHandler(
            shutdownDelay=self._shutdownDelay,
            lowBatteryThreshold=self._lowBatteryThreshold,
            suppressLegacyTriggers=suppressLegacy,
        )
        logger.debug(
            "Shutdown handler initialized (suppressLegacy=%s)",
            suppressLegacy,
        )

    def _initializePowerDownOrchestrator(self) -> None:
        """Initialize US-216 PowerDownOrchestrator when config + deps present.

        V0.24.1 hotfix: every silent-skip path is now WARNING-level (was
        DEBUG/INFO).  Prior DEBUG-level "no shutdownThresholds supplied"
        was invisible in journalctl at production INFO level, masking
        the failure mode where the ladder was never constructed.  Per
        US-281 anti-pattern doc: silent boot-safety fallbacks for
        REQUIRED wiring are worse than crashing -- they give false
        confidence that the safety system is armed.
        """
        if self._shutdownThresholds is None:
            logger.warning(
                "PowerDownOrchestrator: no shutdownThresholds supplied "
                "-- ladder will not be constructed; graceful shutdown "
                "disarmed.  Check config.json pi.power.shutdownThresholds."
            )
            return
        if not self._shutdownThresholds.enabled:
            logger.warning(
                "PowerDownOrchestrator: disabled by config (legacy path "
                "active) -- ladder will not fire.  Set "
                "pi.power.shutdownThresholds.enabled=true to arm graceful "
                "shutdown."
            )
            return
        if self._batteryHealthRecorder is None:
            logger.warning(
                "PowerDownOrchestrator: shutdownThresholds enabled but no "
                "BatteryHealthRecorder supplied -- ladder will not be "
                "constructed; graceful shutdown disarmed"
            )
            return
        if self._shutdownHandler is None:
            logger.warning(
                "PowerDownOrchestrator: ShutdownHandler not available "
                "-- ladder will not be constructed; graceful shutdown "
                "disarmed"
            )
            return

        self._powerDownOrchestrator = PowerDownOrchestrator(
            thresholds=self._shutdownThresholds,
            batteryHealthRecorder=self._batteryHealthRecorder,
            shutdownAction=self._shutdownHandler._executeShutdown,  # noqa: SLF001
            powerLogWriter=self._powerLogWriter,
        )
        logger.info(
            "PowerDownOrchestrator initialized: warning=%.2fV imminent=%.2fV "
            "trigger=%.2fV hysteresis=%.2fV",
            self._shutdownThresholds.warningVcell,
            self._shutdownThresholds.imminentVcell,
            self._shutdownThresholds.triggerVcell,
            self._shutdownThresholds.hysteresisVcell,
        )

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
                refreshRate=self._displayRefreshRate,
                forceSoftwareRenderer=self._displayForceSoftwareRenderer,
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

        # US-252: spawn the staged-shutdown tick thread independently of
        # the display.  Across 5 drain tests the orchestrator NEVER FIRED
        # because tick() was called from _displayUpdateLoop, which only
        # ran when _statusDisplay was non-None.  This thread decouples
        # the safety-critical ladder from the UI: as long as a UPS
        # monitor + an orchestrator are wired, the tick fires at the
        # configured poll cadence.  _stopEvent is shared with the display
        # thread so a single stop() call halts both.
        if (self._upsMonitor is not None
                and self._powerDownOrchestrator is not None):
            self._stopEvent.clear()
            self._powerDownTickThread = threading.Thread(
                target=self._powerDownTickLoop,
                name="PowerDownOrchestratorTick",
                daemon=True,
            )
            self._powerDownTickThread.start()
            logger.info(
                "PowerDownOrchestrator tick thread spawned "
                "(decoupled from display, US-252; daemon=%s, "
                "ident=%s; US-265 liveness probe active)",
                self._powerDownTickThread.daemon,
                self._powerDownTickThread.ident,
            )

        # Start telemetry logging
        if self._telemetryLogger is not None:
            try:
                self._telemetryLogger.start()
                logger.debug("Telemetry logger started")
            except Exception as e:
                logger.warning(f"Failed to start telemetry logger: {e}")

    def _displayUpdateLoop(self) -> None:
        """Background loop for updating display with UPS readings.

        US-252: the staged-shutdown ladder no longer rides on this loop.
        ``_powerDownTickLoop`` runs in its own thread so a missing or
        failed display cannot disable the safety path.  This loop is now
        UI-only.
        """
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

                    except UpsMonitorError as e:
                        logger.debug(f"Could not get UPS telemetry: {e}")

            except Exception as e:
                logger.error(f"Error in display update loop: {e}")

            # Wait for next update interval (use UPS poll interval)
            self._stopEvent.wait(timeout=self._pollInterval)

    def _powerDownTickLoop(self) -> None:
        """Background loop driving PowerDownOrchestrator ticks (US-252 + US-265).

        Polls UpsMonitor at the UPS cadence and feeds (vcell, source)
        pairs to the orchestrator.  Decoupled from the display so a
        missing / failed StatusDisplay cannot disable the staged-shutdown
        ladder -- the bug class that survived 5 drain tests across 3
        weeks (Sprint 16 -> Sprint 20).

        Loop body parallels _displayUpdateLoop's prior orchestrator-feed
        block but without UI-coupled guards.  Also runs the legacy
        low-battery check on ShutdownHandler so the suppressLegacyTriggers
        contract continues to apply.

        US-265 instrumentation: at loop entry, log ``tid=<id>`` at INFO
        so journalctl can correlate the OS thread with the start
        decision in :meth:`_startComponents`.  After each iteration,
        run :meth:`_checkTickThreadHealth` which on a 60s cadence
        (configurable) compares the orchestrator's ``tickCount`` to the
        prior snapshot and raises an alarm event when the counter has
        not advanced while on BATTERY.  Drain Test 6 produced 1
        ``power_log`` row across a 21-min battery window proving the
        ladder did not fire; this in-loop probe makes that failure
        diagnosable in real time on the next drain.
        """
        logger.info(
            "PowerDownOrchestrator tick thread started, tid=%s "
            "(US-265 liveness instrumentation active; "
            "healthCheckIntervalS=%.1f)",
            threading.get_ident(),
            self._tickHealthCheckIntervalS,
        )
        while not self._stopEvent.is_set():
            currentSource: PowerSource | None = None
            try:
                if self._upsMonitor is not None:
                    try:
                        telemetry = self._upsMonitor.getTelemetry()
                        currentSource = telemetry['powerSource']

                        # US-216 + US-234: feed the orchestrator at the
                        # poll cadence.  US-234 switched from SOC% (broken
                        # on this MAX17048) to VCELL volts.
                        if (self._powerDownOrchestrator is not None
                                and telemetry['voltage'] is not None):
                            self._powerDownOrchestrator.tick(
                                currentVcell=float(telemetry['voltage']),
                                currentSource=telemetry['powerSource'],
                            )

                        # Legacy low-battery check (no-op when
                        # suppressLegacyTriggers=True per US-216).
                        if (self._shutdownHandler is not None
                                and telemetry['percentage'] is not None):
                            self._shutdownHandler.onLowBattery(
                                telemetry['percentage']
                            )

                    except UpsMonitorError as e:
                        logger.debug(
                            f"Could not get UPS telemetry for tick: {e}"
                        )

            except Exception as e:
                logger.error(f"Error in power-down tick loop: {e}")

            # US-265 liveness probe.  Wrapped in broad try/except
            # because the invariant says the health check MUST NOT
            # halt the tick loop -- forensics cannot block safety.
            try:
                tickCount = (
                    self._powerDownOrchestrator.tickCount
                    if self._powerDownOrchestrator is not None
                    else 0
                )
                isBattery = (
                    currentSource == PowerSource.BATTERY
                    if currentSource is not None
                    else False
                )
                self._checkTickThreadHealth(
                    currentTickCount=tickCount, isBattery=isBattery,
                )
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "PowerDownOrchestrator tick health-check raised "
                    "(loop continues): %s", e,
                )

            self._stopEvent.wait(timeout=self._pollInterval)
        logger.debug("PowerDownOrchestrator tick loop stopped")

    def _checkTickThreadHealth(
        self, *, currentTickCount: int, isBattery: bool,
    ) -> bool:
        """US-265: snapshot tickCount and alarm on stalled increments.

        Hypothesis-A discriminator from Spool's truth-table.  On a 60s
        cadence (configurable via ``tickHealthCheckIntervalS``):

        * If the configured interval has not elapsed since the last
          snapshot, return ``False`` immediately and do not advance
          internal state.  The throttle prevents the check from firing
          on every poll iteration (5s default).
        * If the elapsed interval is >= the configured interval, take
          a fresh snapshot.  When the PRIOR snapshot recorded the
          system as on BATTERY AND the current call is also on BATTERY
          AND ``currentTickCount`` has not changed, raise an alarm:
          log at ERROR level and increment :attr:`tickHealthAlarmCount`.
        * Otherwise (AC path, healthy increment, or just-transitioned
          to BATTERY), update the snapshot silently or with an INFO
          log of the delta on the healthy path.

        Args:
            currentTickCount: A snapshot of
                :attr:`PowerDownOrchestrator.tickCount` at the moment
                the helper was invoked.  Passed in (rather than read
                here) so the loop can capture it from the same
                telemetry block that called ``orch.tick``.
            isBattery: True iff the current power source is BATTERY.
                The alarm only fires when both this AND the prior
                window were BATTERY -- the post-Drain-7 verdict relies
                on the ladder firing under load, not under wall power.

        Returns:
            True iff this call raised the alarm; False otherwise.

        Note:
            Single-threaded invariant: this helper is called only from
            :meth:`_powerDownTickLoop` so no lock is required around
            the snapshot state.  Callers from tests are expected to
            observe the same single-thread discipline.
        """
        nowMono = time.monotonic()
        elapsed = nowMono - self._lastTickHealthCheckMono
        if elapsed < self._tickHealthCheckIntervalS:
            return False

        alarmRaised = False
        if isBattery and self._lastTickHealthCheckOnBattery:
            if currentTickCount == self._lastTickHealthCheckCount:
                logger.error(
                    "PowerDownOrchestrator tick liveness alarm: "
                    "tickCount=%d unchanged across %.1fs while on "
                    "BATTERY -- tick thread may be dead "
                    "(US-265 hypothesis A)",
                    currentTickCount, elapsed,
                )
                self._tickHealthAlarmCount += 1
                alarmRaised = True
            else:
                logger.info(
                    "PowerDownOrchestrator tick health OK: "
                    "tickCount=%d (delta=%d across %.1fs on BATTERY)",
                    currentTickCount,
                    currentTickCount - self._lastTickHealthCheckCount,
                    elapsed,
                )

        self._lastTickHealthCheckMono = nowMono
        self._lastTickHealthCheckCount = currentTickCount
        self._lastTickHealthCheckOnBattery = isBattery
        return alarmRaised

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

        # Release the power-down orchestrator reference (no close needed --
        # it's a pure state machine with no owned resources).
        self._powerDownOrchestrator = None

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
        # US-252: clear dedicated tick thread reference
        self._powerDownTickThread = None
        self._stopEvent.clear()

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
            - display: Display status or None
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
    def statusDisplay(self) -> StatusDisplay | None:
        """Get the status display instance (or None if not available)."""
        return self._statusDisplay

    @property
    def telemetryLogger(self) -> TelemetryLogger | None:
        """Get the telemetry logger instance (or None if not available)."""
        return self._telemetryLogger

    @property
    def powerDownOrchestrator(self) -> PowerDownOrchestrator | None:
        """Get the US-216 orchestrator instance (or None when ladder disabled)."""
        return self._powerDownOrchestrator

    @property
    def tickHealthAlarmCount(self) -> int:
        """US-265 cumulative count of tick-thread liveness alarms raised.

        Each alarm corresponds to one full :attr:`tickHealthCheckIntervalS`
        window where ``orchestrator.tickCount`` did not advance while
        on BATTERY.  Operators monitor this via the journalctl ERROR
        line each alarm emits; tests read the property directly.
        """
        return self._tickHealthAlarmCount

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
    batteryHealthRecorder: BatteryHealthRecorder | None = None,
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
            - hardware.display.enabled: Display enabled (default: True)
            - hardware.display.refreshRate: Display refresh rate (default: 2)
            - hardware.statusDisplay.enabled: StatusDisplay overlay enabled
                (default: True; falls back to hardware.display.enabled)
            - hardware.statusDisplay.forceSoftwareRenderer: Force SDL software
                renderer for the overlay (default: True; TD-024 fix)
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
    # statusDisplay.enabled takes precedence; falls back to legacy display.enabled
    # to preserve the pre-US-198 config contract.
    displayEnabled = getConfigValue(
        'hardware.statusDisplay.enabled',
        getConfigValue('hardware.display.enabled', True),
    )
    displayRefreshRate = getConfigValue('hardware.display.refreshRate', 2.0)
    displayForceSoftwareRenderer = getConfigValue(
        'hardware.statusDisplay.forceSoftwareRenderer', True
    )
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

    # US-216 + US-234: read pi.power.shutdownThresholds. If present AND
    # enabled, construct a ShutdownThresholds; hardware_manager will then
    # create the PowerDownOrchestrator and suppress the legacy trigger
    # paths. US-234 fields are VCELL volts (3.70/3.55/3.45/0.05) since
    # MAX17048 SOC% on this hardware is 40-pt off and unfireable.
    shutdownThresholds: ShutdownThresholds | None = None
    powerSection = getConfigValue('pi.power.shutdownThresholds', None)
    if isinstance(powerSection, dict):
        shutdownThresholds = ShutdownThresholds(
            enabled=bool(powerSection.get('enabled', True)),
            warningVcell=float(powerSection.get('warningVcell', 3.70)),
            imminentVcell=float(powerSection.get('imminentVcell', 3.55)),
            triggerVcell=float(powerSection.get('triggerVcell', 3.45)),
            hysteresisVcell=float(powerSection.get('hysteresisVcell', 0.05)),
        )

    # US-265: liveness probe cadence.  Default 60.0s matches Spool's
    # spec.  Tests pass 0.0 to disable the throttle.
    tickHealthCheckIntervalS = float(
        getConfigValue('pi.power.tickHealthCheckIntervalS', 60.0)
    )

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
        displayForceSoftwareRenderer=bool(displayForceSoftwareRenderer),
        telemetryLogPath=telemetryLogPath,
        telemetryLogInterval=float(telemetryLogInterval),
        telemetryMaxBytes=int(telemetryMaxBytes),
        telemetryBackupCount=int(telemetryBackupCount),
        shutdownThresholds=shutdownThresholds,
        batteryHealthRecorder=batteryHealthRecorder,
        powerLogWriter=powerLogWriter,
        tickHealthCheckIntervalS=tickHealthCheckIntervalS,
    )
