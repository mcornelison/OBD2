################################################################################
# File Name: power.py
# Purpose/Description: 12V adapter disconnect detection and power source monitoring
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Refactored from power_monitor.py for US-012
# ================================================================================
################################################################################
"""
12V adapter disconnect detection and power source monitoring module.

Provides:
- Primary power status monitoring via GPIO or power management HAT
- Power transition event logging (AC→Battery, Battery→AC)
- Power source display on status screen
- Power saving mode when on battery (lower polling rate, dim display)
- Database logging of power events
- Statistics tracking

Features:
- Detect when primary 12V power is lost
- Switch to battery backup mode automatically
- Reduce power consumption when on battery
- Log all power transition events
- Display current power source

Usage:
    from power.power import PowerMonitor

    # Create manually
    monitor = PowerMonitor(
        pollingIntervalSeconds=5,
        reducedPollingIntervalSeconds=30,
        displayDimPercentage=30,
    )

    # Set up power status reader (GPIO or power management HAT)
    def readPowerStatus():
        # Read GPIO pin or power management HAT
        # Return True if on AC power, False if on battery
        return gpio.input(POWER_PIN) == HIGH

    monitor.setPowerStatusReader(readPowerStatus)
    monitor.start()

    # On shutdown
    monitor.stop()
"""

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .types import (
    DEFAULT_DISPLAY_DIM_PERCENTAGE,
    DEFAULT_POLLING_INTERVAL_SECONDS,
    DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS,
    MIN_POLLING_INTERVAL_SECONDS,
    POWER_LOG_EVENT_AC_POWER,
    POWER_LOG_EVENT_BATTERY_POWER,
    POWER_LOG_EVENT_POWER_SAVING_DISABLED,
    POWER_LOG_EVENT_POWER_SAVING_ENABLED,
    POWER_LOG_EVENT_TRANSITION_TO_AC,
    POWER_LOG_EVENT_TRANSITION_TO_BATTERY,
    PowerMonitorState,
    PowerReading,
    PowerSource,
    PowerStats,
)

logger = logging.getLogger(__name__)


class PowerMonitor:
    """
    Monitors 12V adapter power status and handles power transitions.

    Detects when primary 12V power is lost/restored, logs transitions,
    displays power source on status screen, and reduces power consumption
    when running on battery.

    Features:
    - Power status monitoring via configurable reader function
    - Automatic power saving mode when on battery
    - Display dimming when on battery
    - Reduced polling rate when on battery
    - Database logging of power events
    - Statistics tracking
    - Callback support for custom event handling

    Example:
        monitor = PowerMonitor(
            database=db,
            displayManager=display,
            batteryMonitor=battery,
            pollingIntervalSeconds=5,
            reducedPollingIntervalSeconds=30,
        )
        monitor.setPowerStatusReader(readPowerStatusFromGpio)
        monitor.start()

        # In shutdown
        monitor.stop()
    """

    def __init__(
        self,
        database: Any | None = None,
        displayManager: Any | None = None,
        batteryMonitor: Any | None = None,
        pollingIntervalSeconds: float = DEFAULT_POLLING_INTERVAL_SECONDS,
        reducedPollingIntervalSeconds: float = DEFAULT_REDUCED_POLLING_INTERVAL_SECONDS,
        displayDimPercentage: int = DEFAULT_DISPLAY_DIM_PERCENTAGE,
        enabled: bool = True,
    ):
        """
        Initialize the power monitor.

        Args:
            database: ObdDatabase instance for logging power events
            displayManager: DisplayManager instance for status display
            batteryMonitor: BatteryMonitor instance for battery status
            pollingIntervalSeconds: Polling interval when on AC (default 5s)
            reducedPollingIntervalSeconds: Polling interval when on battery (default 30s)
            displayDimPercentage: Display brightness when on battery (default 30%)
            enabled: Whether monitoring is enabled
        """
        self._database = database
        self._displayManager = displayManager
        self._batteryMonitor = batteryMonitor
        self._pollingIntervalSeconds = max(MIN_POLLING_INTERVAL_SECONDS, pollingIntervalSeconds)
        self._reducedPollingIntervalSeconds = max(MIN_POLLING_INTERVAL_SECONDS, reducedPollingIntervalSeconds)
        self._displayDimPercentage = max(0, min(100, displayDimPercentage))
        self._enabled = enabled

        # Power status reader function (to be set based on hardware)
        self._powerStatusReader: Callable[[], bool] | None = None

        # State
        self._state = PowerMonitorState.STOPPED
        self._currentPowerSource = PowerSource.UNKNOWN
        self._stats = PowerStats()
        self._powerSavingEnabled = False
        self._originalDisplayBrightness: int | None = None
        self._originalPollingInterval: float | None = None

        # Callbacks
        self._onAcPowerCallbacks: list[Callable[[PowerReading], None]] = []
        self._onBatteryPowerCallbacks: list[Callable[[PowerReading], None]] = []
        self._onTransitionCallbacks: list[Callable[[PowerSource, PowerSource], None]] = []
        self._onReadingCallbacks: list[Callable[[PowerReading], None]] = []

        # Polling thread
        self._pollingThread: threading.Thread | None = None
        self._stopPolling = threading.Event()

        # Thread safety
        self._lock = threading.Lock()

    # ================================================================================
    # Configuration
    # ================================================================================

    def setDatabase(self, database: Any) -> None:
        """
        Set the database instance.

        Args:
            database: ObdDatabase instance
        """
        self._database = database

    def setDisplayManager(self, displayManager: Any) -> None:
        """
        Set the display manager instance.

        Args:
            displayManager: DisplayManager instance
        """
        self._displayManager = displayManager

    def setBatteryMonitor(self, batteryMonitor: Any) -> None:
        """
        Set the battery monitor instance.

        Args:
            batteryMonitor: BatteryMonitor instance
        """
        self._batteryMonitor = batteryMonitor

    def setPollingInterval(self, seconds: float) -> None:
        """
        Set the polling interval for AC power mode.

        Args:
            seconds: Polling interval in seconds (minimum 1)
        """
        self._pollingIntervalSeconds = max(MIN_POLLING_INTERVAL_SECONDS, seconds)
        logger.debug(f"Polling interval set to {self._pollingIntervalSeconds}s")

    def setReducedPollingInterval(self, seconds: float) -> None:
        """
        Set the reduced polling interval for battery mode.

        Args:
            seconds: Polling interval in seconds (minimum 1)
        """
        self._reducedPollingIntervalSeconds = max(MIN_POLLING_INTERVAL_SECONDS, seconds)
        logger.debug(f"Reduced polling interval set to {self._reducedPollingIntervalSeconds}s")

    def setDisplayDimPercentage(self, percentage: int) -> None:
        """
        Set the display dim percentage for battery mode.

        Args:
            percentage: Display brightness percentage (0-100)
        """
        self._displayDimPercentage = max(0, min(100, percentage))
        logger.debug(f"Display dim percentage set to {self._displayDimPercentage}%")

    def setEnabled(self, enabled: bool) -> None:
        """
        Enable or disable monitoring.

        Args:
            enabled: True to enable, False to disable
        """
        self._enabled = enabled

    def setPowerStatusReader(self, reader: Callable[[], bool]) -> None:
        """
        Set the power status reader function.

        The reader function should return True if on AC power,
        False if on battery. This allows for different hardware
        configurations (GPIO pin, power management HAT, etc.).

        Args:
            reader: Function that returns True if on AC power

        Example:
            def readFromGpio():
                # HIGH = AC power connected, LOW = on battery
                return GPIO.input(POWER_STATUS_PIN) == GPIO.HIGH

            monitor.setPowerStatusReader(readFromGpio)
        """
        self._powerStatusReader = reader
        logger.debug("Power status reader function configured")

    # ================================================================================
    # Lifecycle
    # ================================================================================

    def start(self) -> bool:
        """
        Start the power monitor.

        Begins background polling for power status.

        Returns:
            True if started successfully
        """
        with self._lock:
            if self._state in (PowerMonitorState.RUNNING, PowerMonitorState.POWER_SAVING):
                return True

            self._stopPolling.clear()
            self._state = PowerMonitorState.RUNNING

            # Start polling thread
            self._pollingThread = threading.Thread(
                target=self._pollingLoop,
                daemon=True,
                name="PowerMonitor-Polling",
            )
            self._pollingThread.start()

            logger.info(
                f"Power monitor started | interval={self._pollingIntervalSeconds}s, "
                f"reduced_interval={self._reducedPollingIntervalSeconds}s"
            )
            return True

    def stop(self) -> None:
        """Stop the power monitor."""
        with self._lock:
            if self._state == PowerMonitorState.STOPPED:
                return

            # Disable power saving mode before stopping
            if self._powerSavingEnabled:
                self._disablePowerSaving()

            # Signal polling thread to stop
            self._stopPolling.set()

            # Wait for polling thread to finish (with timeout)
            if self._pollingThread and self._pollingThread.is_alive():
                self._pollingThread.join(timeout=2.0)

            self._state = PowerMonitorState.STOPPED
            logger.info("Power monitor stopped")

    def isRunning(self) -> bool:
        """Check if power monitor is running."""
        return self._state in (PowerMonitorState.RUNNING, PowerMonitorState.POWER_SAVING)

    def getState(self) -> PowerMonitorState:
        """Get current state."""
        return self._state

    def getCurrentPowerSource(self) -> PowerSource:
        """Get current power source."""
        return self._currentPowerSource

    def isPowerSavingEnabled(self) -> bool:
        """Check if power saving mode is enabled."""
        return self._powerSavingEnabled

    # ================================================================================
    # Polling
    # ================================================================================

    def _pollingLoop(self) -> None:
        """
        Background polling loop.

        Reads power status at configured interval and processes readings.
        Uses reduced interval when on battery power.
        Sleeps in small increments for responsive shutdown.
        """
        logger.debug("Power polling loop started")

        while not self._stopPolling.is_set():
            if self._enabled:
                powerStatus = self.readPowerStatus()
                if powerStatus is not None:
                    self.checkPowerStatus(powerStatus)

            # Use appropriate polling interval based on power source
            if self._powerSavingEnabled:
                sleepTime = self._reducedPollingIntervalSeconds
            else:
                sleepTime = self._pollingIntervalSeconds

            # Sleep in small increments for responsive shutdown
            sleepIncrement = 0.1
            while sleepTime > 0 and not self._stopPolling.is_set():
                time.sleep(min(sleepIncrement, sleepTime))
                sleepTime -= sleepIncrement

        logger.debug("Power polling loop stopped")

    # ================================================================================
    # Power Status Reading
    # ================================================================================

    def readPowerStatus(self) -> bool | None:
        """
        Read current power status using configured reader.

        Returns:
            True if on AC power, False if on battery, None if reading failed
        """
        if self._powerStatusReader is None:
            logger.debug("No power status reader configured")
            return None

        try:
            onAcPower = self._powerStatusReader()
            logger.debug(f"Read power status: {'AC' if onAcPower else 'Battery'}")
            return onAcPower
        except Exception as e:
            logger.error(f"Error reading power status: {e}")
            return None

    def checkPowerStatus(self, onAcPower: bool) -> PowerReading | None:
        """
        Check power status and handle transitions.

        Creates a PowerReading, updates stats, checks for transitions,
        triggers callbacks, updates display, and logs to database.

        Args:
            onAcPower: True if on AC power, False if on battery

        Returns:
            PowerReading if enabled, None if disabled
        """
        if not self._enabled:
            return None

        with self._lock:
            now = datetime.now()
            newPowerSource = PowerSource.AC_POWER if onAcPower else PowerSource.BATTERY
            reading = PowerReading(
                powerSource=newPowerSource,
                onAcPower=onAcPower,
                timestamp=now
            )

            # Check for power transition
            previousSource = self._currentPowerSource
            if previousSource != PowerSource.UNKNOWN and previousSource != newPowerSource:
                self._handleTransition(previousSource, newPowerSource, now)

            # Update current power source
            self._currentPowerSource = newPowerSource

            # Update statistics
            self._updateStats(reading)

            # Trigger reading callbacks
            self._triggerReadingCallbacks(reading)

            # Trigger power source specific callbacks
            if onAcPower:
                self._triggerAcPowerCallbacks(reading)
            else:
                self._triggerBatteryPowerCallbacks(reading)

            # Update display with power source
            self._updateDisplayPowerSource(newPowerSource)

            # Log to database
            eventType = POWER_LOG_EVENT_AC_POWER if onAcPower else POWER_LOG_EVENT_BATTERY_POWER
            self._logToDatabase(reading, eventType)

            return reading

    # ================================================================================
    # Power Transition Handling
    # ================================================================================

    def _handleTransition(
        self,
        fromSource: PowerSource,
        toSource: PowerSource,
        timestamp: datetime
    ) -> None:
        """
        Handle power source transition.

        Args:
            fromSource: Previous power source
            toSource: New power source
            timestamp: Time of transition
        """
        logger.info(
            f"Power transition: {fromSource.value} -> {toSource.value}"
        )

        self._stats.lastTransitionTime = timestamp

        if toSource == PowerSource.BATTERY:
            # Transition to battery
            self._stats.transitionsToBattery += 1
            self._stats.batteryStartTime = timestamp
            self._enablePowerSaving()
            self._logTransitionToDatabase(POWER_LOG_EVENT_TRANSITION_TO_BATTERY, timestamp)
        else:
            # Transition to AC power
            self._stats.transitionsToAc += 1

            # Calculate battery time
            if self._stats.batteryStartTime:
                batteryDuration = (timestamp - self._stats.batteryStartTime).total_seconds()
                self._stats.totalBatteryTimeSeconds += batteryDuration
                self._stats.batteryStartTime = None

            self._disablePowerSaving()
            self._logTransitionToDatabase(POWER_LOG_EVENT_TRANSITION_TO_AC, timestamp)

        # Trigger transition callbacks
        self._triggerTransitionCallbacks(fromSource, toSource)

    def _enablePowerSaving(self) -> None:
        """Enable power saving mode for battery operation."""
        if self._powerSavingEnabled:
            return

        logger.info(
            f"Enabling power saving mode | "
            f"reduced_polling={self._reducedPollingIntervalSeconds}s, "
            f"display_dim={self._displayDimPercentage}%"
        )

        self._powerSavingEnabled = True
        self._state = PowerMonitorState.POWER_SAVING

        # Dim display
        if self._displayManager:
            self._dimDisplay()

        # Reduce battery monitor polling if available
        if self._batteryMonitor and hasattr(self._batteryMonitor, 'setPollingInterval'):
            self._originalPollingInterval = getattr(
                self._batteryMonitor, '_pollingIntervalSeconds', None
            )
            try:
                self._batteryMonitor.setPollingInterval(self._reducedPollingIntervalSeconds)
            except Exception as e:
                logger.error(f"Error setting battery monitor polling interval: {e}")

        # Log power saving enabled
        self._logPowerSavingEvent(POWER_LOG_EVENT_POWER_SAVING_ENABLED)

    def _disablePowerSaving(self) -> None:
        """Disable power saving mode when back on AC power."""
        if not self._powerSavingEnabled:
            return

        logger.info("Disabling power saving mode")

        self._powerSavingEnabled = False
        self._state = PowerMonitorState.RUNNING

        # Restore display brightness
        if self._displayManager:
            self._restoreDisplayBrightness()

        # Restore battery monitor polling interval
        if self._batteryMonitor and self._originalPollingInterval:
            try:
                self._batteryMonitor.setPollingInterval(self._originalPollingInterval)
            except Exception as e:
                logger.error(f"Error restoring battery monitor polling interval: {e}")
            self._originalPollingInterval = None

        # Log power saving disabled
        self._logPowerSavingEvent(POWER_LOG_EVENT_POWER_SAVING_DISABLED)

    def _dimDisplay(self) -> None:
        """Dim the display for power saving."""
        if not self._displayManager:
            return

        # Store original brightness if possible
        if hasattr(self._displayManager, '_driver'):
            driver = self._displayManager._driver
            if hasattr(driver, '_brightness'):
                self._originalDisplayBrightness = driver._brightness

            # Set dim brightness
            if hasattr(driver, 'setBrightness'):
                try:
                    driver.setBrightness(self._displayDimPercentage)
                    logger.debug(f"Display dimmed to {self._displayDimPercentage}%")
                except Exception as e:
                    logger.error(f"Error dimming display: {e}")
            elif hasattr(driver, '_displayAdapter') and driver._displayAdapter:
                adapter = driver._displayAdapter
                if hasattr(adapter, 'setBrightness'):
                    try:
                        adapter.setBrightness(self._displayDimPercentage)
                        logger.debug(f"Display dimmed to {self._displayDimPercentage}%")
                    except Exception as e:
                        logger.error(f"Error dimming display via adapter: {e}")

    def _restoreDisplayBrightness(self) -> None:
        """Restore the display brightness after power saving."""
        if not self._displayManager or self._originalDisplayBrightness is None:
            return

        if hasattr(self._displayManager, '_driver'):
            driver = self._displayManager._driver
            if hasattr(driver, 'setBrightness'):
                try:
                    driver.setBrightness(self._originalDisplayBrightness)
                    logger.debug(f"Display brightness restored to {self._originalDisplayBrightness}%")
                except Exception as e:
                    logger.error(f"Error restoring display brightness: {e}")
            elif hasattr(driver, '_displayAdapter') and driver._displayAdapter:
                adapter = driver._displayAdapter
                if hasattr(adapter, 'setBrightness'):
                    try:
                        adapter.setBrightness(self._originalDisplayBrightness)
                        logger.debug(f"Display brightness restored to {self._originalDisplayBrightness}%")
                    except Exception as e:
                        logger.error(f"Error restoring display brightness via adapter: {e}")

        self._originalDisplayBrightness = None

    def _updateDisplayPowerSource(self, powerSource: PowerSource) -> None:
        """
        Update display with current power source.

        Args:
            powerSource: Current power source to display
        """
        if not self._displayManager:
            return

        # Show alert for power transitions if display supports it
        if hasattr(self._displayManager, 'showAlert'):
            if powerSource == PowerSource.BATTERY:
                try:
                    self._displayManager.showAlert(
                        message="ON BATTERY POWER",
                        priority=3,
                    )
                except Exception as e:
                    logger.error(f"Error showing battery alert: {e}")

    # ================================================================================
    # Statistics
    # ================================================================================

    def _updateStats(self, reading: PowerReading) -> None:
        """
        Update statistics with new reading.

        Args:
            reading: The power reading
        """
        self._stats.totalReadings += 1
        self._stats.lastReading = reading.powerSource

        if reading.onAcPower:
            self._stats.acPowerReadings += 1
        else:
            self._stats.batteryReadings += 1

    def getStats(self) -> PowerStats:
        """
        Get power statistics.

        Returns:
            PowerStats with current statistics
        """
        with self._lock:
            # Calculate current battery time if on battery
            totalBatteryTime = self._stats.totalBatteryTimeSeconds
            if self._stats.batteryStartTime:
                currentBatteryTime = (datetime.now() - self._stats.batteryStartTime).total_seconds()
                totalBatteryTime += currentBatteryTime

            return PowerStats(
                totalReadings=self._stats.totalReadings,
                acPowerReadings=self._stats.acPowerReadings,
                batteryReadings=self._stats.batteryReadings,
                transitionsToBattery=self._stats.transitionsToBattery,
                transitionsToAc=self._stats.transitionsToAc,
                lastTransitionTime=self._stats.lastTransitionTime,
                totalBatteryTimeSeconds=totalBatteryTime,
                lastReading=self._stats.lastReading,
            )

    def resetStats(self) -> None:
        """Reset statistics."""
        with self._lock:
            self._stats = PowerStats()
            logger.debug("Power statistics reset")

    # ================================================================================
    # Database Logging
    # ================================================================================

    def _logToDatabase(self, reading: PowerReading, eventType: str) -> None:
        """
        Log power reading to database.

        Args:
            reading: The power reading to log
            eventType: Type of event (ac_power, battery_power)
        """
        if self._database is None:
            return

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO power_log
                    (timestamp, event_type, power_source, on_ac_power)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        reading.timestamp,
                        eventType,
                        reading.powerSource.value,
                        1 if reading.onAcPower else 0,
                    )
                )
                logger.debug(f"Logged power status to database | type={eventType}")
        except Exception as e:
            logger.error(f"Error logging power status to database: {e}")

    def _logTransitionToDatabase(self, eventType: str, timestamp: datetime) -> None:
        """
        Log power transition event to database.

        Args:
            eventType: Type of transition event
            timestamp: Time of transition
        """
        if self._database is None:
            return

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO power_log
                    (timestamp, event_type, power_source, on_ac_power)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        timestamp,
                        eventType,
                        self._currentPowerSource.value,
                        1 if self._currentPowerSource == PowerSource.AC_POWER else 0,
                    )
                )
                logger.debug(f"Logged power transition to database | type={eventType}")
        except Exception as e:
            logger.error(f"Error logging power transition to database: {e}")

    def _logPowerSavingEvent(self, eventType: str) -> None:
        """
        Log power saving mode event to database.

        Args:
            eventType: Type of power saving event
        """
        if self._database is None:
            return

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO power_log
                    (timestamp, event_type, power_source, on_ac_power)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        datetime.now(),
                        eventType,
                        self._currentPowerSource.value,
                        1 if self._currentPowerSource == PowerSource.AC_POWER else 0,
                    )
                )
                logger.debug(f"Logged power saving event to database | type={eventType}")
        except Exception as e:
            logger.error(f"Error logging power saving event to database: {e}")

    def getPowerHistory(
        self,
        limit: int = 100,
        eventType: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Get power history from database.

        Args:
            limit: Maximum number of records to return
            eventType: Filter by event type (optional)

        Returns:
            List of power event records
        """
        if self._database is None:
            return []

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()

                query = "SELECT * FROM power_log WHERE 1=1"
                params: list[Any] = []

                if eventType:
                    query += " AND event_type = ?"
                    params.append(eventType)

                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()

                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error getting power history: {e}")
            return []

    # ================================================================================
    # Callbacks
    # ================================================================================

    def onAcPower(self, callback: Callable[[PowerReading], None]) -> None:
        """
        Register a callback for AC power events.

        Args:
            callback: Function to call when on AC power
        """
        self._onAcPowerCallbacks.append(callback)

    def onBatteryPower(self, callback: Callable[[PowerReading], None]) -> None:
        """
        Register a callback for battery power events.

        Args:
            callback: Function to call when on battery power
        """
        self._onBatteryPowerCallbacks.append(callback)

    def onTransition(self, callback: Callable[[PowerSource, PowerSource], None]) -> None:
        """
        Register a callback for power transitions.

        Args:
            callback: Function to call on power transition (fromSource, toSource)
        """
        self._onTransitionCallbacks.append(callback)

    def onReading(self, callback: Callable[[PowerReading], None]) -> None:
        """
        Register a callback for all power readings.

        Args:
            callback: Function to call for every power reading
        """
        self._onReadingCallbacks.append(callback)

    def _triggerAcPowerCallbacks(self, reading: PowerReading) -> None:
        """Trigger AC power callbacks."""
        for callback in self._onAcPowerCallbacks:
            try:
                callback(reading)
            except Exception as e:
                logger.error(f"Error in AC power callback: {e}")

    def _triggerBatteryPowerCallbacks(self, reading: PowerReading) -> None:
        """Trigger battery power callbacks."""
        for callback in self._onBatteryPowerCallbacks:
            try:
                callback(reading)
            except Exception as e:
                logger.error(f"Error in battery power callback: {e}")

    def _triggerTransitionCallbacks(
        self,
        fromSource: PowerSource,
        toSource: PowerSource
    ) -> None:
        """Trigger transition callbacks."""
        for callback in self._onTransitionCallbacks:
            try:
                callback(fromSource, toSource)
            except Exception as e:
                logger.error(f"Error in transition callback: {e}")

    def _triggerReadingCallbacks(self, reading: PowerReading) -> None:
        """Trigger reading callbacks."""
        for callback in self._onReadingCallbacks:
            try:
                callback(reading)
            except Exception as e:
                logger.error(f"Error in reading callback: {e}")

    # ================================================================================
    # Status
    # ================================================================================

    def getStatus(self) -> dict[str, Any]:
        """
        Get current power monitor status.

        Returns:
            Dictionary with status information
        """
        with self._lock:
            return {
                'state': self._state.value,
                'enabled': self._enabled,
                'currentPowerSource': self._currentPowerSource.value,
                'powerSavingEnabled': self._powerSavingEnabled,
                'pollingIntervalSeconds': self._pollingIntervalSeconds,
                'reducedPollingIntervalSeconds': self._reducedPollingIntervalSeconds,
                'displayDimPercentage': self._displayDimPercentage,
                'hasPowerStatusReader': self._powerStatusReader is not None,
                'hasDatabase': self._database is not None,
                'hasDisplayManager': self._displayManager is not None,
                'hasBatteryMonitor': self._batteryMonitor is not None,
                'stats': self.getStats().toDict(),
            }
