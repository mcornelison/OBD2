################################################################################
# File Name: battery.py
# Purpose/Description: Battery backup voltage monitoring for Raspberry Pi
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Refactored from battery_monitor.py for US-012
# ================================================================================
################################################################################
"""
Battery backup voltage monitoring module for the Eclipse OBD-II system.

Provides:
- Voltage monitoring via GPIO ADC or I2C power monitor
- Configurable warning and critical voltage thresholds
- Visual alert integration with DisplayManager
- Graceful shutdown trigger on critical voltage
- Database logging of voltage readings every 60 seconds
- Statistics tracking

Features:
- Warning threshold (e.g., 11.5V): logs warning, displays alert
- Critical threshold (e.g., 11.0V): initiates graceful shutdown
- Pluggable voltage reader for different hardware configurations
- Background polling thread for continuous monitoring

Usage:
    from obd.power.battery import BatteryMonitor

    # Create manually
    monitor = BatteryMonitor(
        warningVoltage=11.5,
        criticalVoltage=11.0,
        pollingIntervalSeconds=60,
    )

    # Set up voltage reader (GPIO ADC or I2C)
    def readVoltageFromAdc():
        # Read from ADC and convert to voltage
        return voltage

    monitor.setVoltageReader(readVoltageFromAdc)
    monitor.start()

    # On shutdown
    monitor.stop()
"""

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .types import (
    BatteryState,
    BatteryStats,
    VoltageReading,
    DEFAULT_WARNING_VOLTAGE,
    DEFAULT_CRITICAL_VOLTAGE,
    DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS,
    MIN_POLLING_INTERVAL_SECONDS,
    BATTERY_LOG_EVENT_VOLTAGE,
    BATTERY_LOG_EVENT_WARNING,
    BATTERY_LOG_EVENT_CRITICAL,
    BATTERY_LOG_EVENT_SHUTDOWN,
)

logger = logging.getLogger(__name__)


class BatteryMonitor:
    """
    Monitors battery backup voltage and triggers actions on threshold events.

    Reads battery voltage via a configurable voltage reader function (GPIO ADC
    or I2C power monitor), checks against warning and critical thresholds,
    displays alerts, logs to database, and initiates graceful shutdown
    when critical threshold is reached.

    Features:
    - Configurable warning and critical voltage thresholds
    - Background polling at configurable interval (default 60 seconds)
    - Visual alerts via DisplayManager integration
    - Graceful shutdown via ShutdownManager integration
    - Database logging of all voltage readings and events
    - Statistics tracking
    - Callback support for custom event handling

    Example:
        monitor = BatteryMonitor(
            database=db,
            displayManager=display,
            shutdownManager=shutdown,
            warningVoltage=11.5,
            criticalVoltage=11.0,
        )
        monitor.setVoltageReader(readFromAdc)
        monitor.start()

        # In shutdown
        monitor.stop()
    """

    def __init__(
        self,
        database: Optional[Any] = None,
        displayManager: Optional[Any] = None,
        shutdownManager: Optional[Any] = None,
        warningVoltage: float = DEFAULT_WARNING_VOLTAGE,
        criticalVoltage: float = DEFAULT_CRITICAL_VOLTAGE,
        pollingIntervalSeconds: float = DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS,
        enabled: bool = True,
    ):
        """
        Initialize the battery monitor.

        Args:
            database: ObdDatabase instance for logging voltage readings
            displayManager: DisplayManager instance for visual alerts
            shutdownManager: ShutdownManager instance for graceful shutdown
            warningVoltage: Warning threshold voltage (default 11.5V)
            criticalVoltage: Critical threshold voltage (default 11.0V)
            pollingIntervalSeconds: Polling interval in seconds (default 60)
            enabled: Whether monitoring is enabled
        """
        self._database = database
        self._displayManager = displayManager
        self._shutdownManager = shutdownManager
        self._warningVoltage = warningVoltage
        self._criticalVoltage = criticalVoltage
        self._pollingIntervalSeconds = max(MIN_POLLING_INTERVAL_SECONDS, pollingIntervalSeconds)
        self._enabled = enabled

        # Voltage reader function (to be set by user based on hardware)
        self._voltageReader: Optional[Callable[[], float]] = None

        # State
        self._state = BatteryState.STOPPED
        self._stats = BatteryStats()

        # Callbacks
        self._onWarningCallbacks: List[Callable[[VoltageReading], None]] = []
        self._onCriticalCallbacks: List[Callable[[VoltageReading], None]] = []
        self._onReadingCallbacks: List[Callable[[VoltageReading], None]] = []

        # Polling thread
        self._pollingThread: Optional[threading.Thread] = None
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

    def setShutdownManager(self, shutdownManager: Any) -> None:
        """
        Set the shutdown manager instance.

        Args:
            shutdownManager: ShutdownManager instance
        """
        self._shutdownManager = shutdownManager

    def setWarningVoltage(self, voltage: float) -> None:
        """
        Set the warning voltage threshold.

        Args:
            voltage: Warning threshold in volts
        """
        self._warningVoltage = voltage
        logger.debug(f"Warning voltage set to {voltage}V")

    def setCriticalVoltage(self, voltage: float) -> None:
        """
        Set the critical voltage threshold.

        Args:
            voltage: Critical threshold in volts
        """
        self._criticalVoltage = voltage
        logger.debug(f"Critical voltage set to {voltage}V")

    def setPollingInterval(self, seconds: float) -> None:
        """
        Set the polling interval.

        Args:
            seconds: Polling interval in seconds (minimum 1)
        """
        self._pollingIntervalSeconds = max(MIN_POLLING_INTERVAL_SECONDS, seconds)
        logger.debug(f"Polling interval set to {self._pollingIntervalSeconds}s")

    def setEnabled(self, enabled: bool) -> None:
        """
        Enable or disable monitoring.

        Args:
            enabled: True to enable, False to disable
        """
        self._enabled = enabled

    def setVoltageReader(self, reader: Callable[[], float]) -> None:
        """
        Set the voltage reader function.

        The reader function should return the current battery voltage
        as a float. This allows for different hardware configurations
        (GPIO ADC, I2C power monitor, etc.).

        Args:
            reader: Function that returns voltage as float

        Example:
            def readFromAdc():
                rawValue = readAdcChannel(0)
                voltage = (rawValue / 4095) * 3.3 * 5.0  # 12-bit ADC with divider
                return voltage

            monitor.setVoltageReader(readFromAdc)
        """
        self._voltageReader = reader
        logger.debug("Voltage reader function configured")

    # ================================================================================
    # Lifecycle
    # ================================================================================

    def start(self) -> bool:
        """
        Start the battery monitor.

        Begins background polling for voltage readings.

        Returns:
            True if started successfully
        """
        with self._lock:
            if self._state == BatteryState.RUNNING:
                return True

            self._stopPolling.clear()
            self._state = BatteryState.RUNNING

            # Start polling thread
            self._pollingThread = threading.Thread(
                target=self._pollingLoop,
                daemon=True,
                name="BatteryMonitor-Polling",
            )
            self._pollingThread.start()

            logger.info(
                f"Battery monitor started | warning={self._warningVoltage}V, "
                f"critical={self._criticalVoltage}V, interval={self._pollingIntervalSeconds}s"
            )
            return True

    def stop(self) -> None:
        """Stop the battery monitor."""
        with self._lock:
            if self._state == BatteryState.STOPPED:
                return

            # Signal polling thread to stop
            self._stopPolling.set()

            # Wait for polling thread to finish (with timeout)
            if self._pollingThread and self._pollingThread.is_alive():
                self._pollingThread.join(timeout=2.0)

            self._state = BatteryState.STOPPED
            logger.info("Battery monitor stopped")

    def isRunning(self) -> bool:
        """Check if battery monitor is running."""
        return self._state == BatteryState.RUNNING

    def getState(self) -> BatteryState:
        """Get current state."""
        return self._state

    # ================================================================================
    # Polling
    # ================================================================================

    def _pollingLoop(self) -> None:
        """
        Background polling loop.

        Reads voltage at configured interval and processes readings.
        Sleeps in small increments for responsive shutdown.
        """
        logger.debug("Polling loop started")

        while not self._stopPolling.is_set():
            if self._enabled:
                voltage = self.readVoltage()
                if voltage is not None:
                    self.checkVoltage(voltage)

            # Sleep in small increments for responsive shutdown
            sleepTime = self._pollingIntervalSeconds
            sleepIncrement = 0.1
            while sleepTime > 0 and not self._stopPolling.is_set():
                time.sleep(min(sleepIncrement, sleepTime))
                sleepTime -= sleepIncrement

        logger.debug("Polling loop stopped")

    # ================================================================================
    # Voltage Reading
    # ================================================================================

    def readVoltage(self) -> Optional[float]:
        """
        Read current battery voltage using configured reader.

        Returns:
            Voltage in volts, or None if reading failed
        """
        if self._voltageReader is None:
            logger.debug("No voltage reader configured")
            return None

        try:
            voltage = self._voltageReader()
            logger.debug(f"Read voltage: {voltage}V")
            return voltage
        except Exception as e:
            logger.error(f"Error reading voltage: {e}")
            return None

    def checkVoltage(self, voltage: float) -> Optional[VoltageReading]:
        """
        Check a voltage value against thresholds.

        Creates a VoltageReading, updates stats, checks thresholds,
        triggers alerts and callbacks, and logs to database.

        Args:
            voltage: Voltage value in volts

        Returns:
            VoltageReading if enabled, None if disabled
        """
        if not self._enabled:
            return None

        with self._lock:
            now = datetime.now()
            reading = VoltageReading(voltage=voltage, timestamp=now)

            # Update statistics
            self._updateStats(reading)

            # Trigger reading callbacks
            self._triggerReadingCallbacks(reading)

            # Log to database
            eventType = BATTERY_LOG_EVENT_VOLTAGE
            if reading.isCritical(self._criticalVoltage):
                eventType = BATTERY_LOG_EVENT_CRITICAL
            elif reading.isWarning(self._warningVoltage):
                eventType = BATTERY_LOG_EVENT_WARNING

            self._logToDatabase(reading, eventType)

            # Check thresholds
            if reading.isCritical(self._criticalVoltage):
                self._handleCritical(reading)
            elif reading.isWarning(self._warningVoltage):
                self._handleWarning(reading)

            return reading

    # ================================================================================
    # Threshold Handling
    # ================================================================================

    def _handleWarning(self, reading: VoltageReading) -> None:
        """
        Handle warning threshold exceeded.

        Args:
            reading: The voltage reading that triggered warning
        """
        logger.warning(
            f"Battery voltage WARNING | voltage={reading.voltage}V, "
            f"threshold={self._warningVoltage}V"
        )

        self._state = BatteryState.WARNING

        # Show visual alert
        if self._displayManager and hasattr(self._displayManager, 'showAlert'):
            try:
                self._displayManager.showAlert(
                    message=f"LOW BATTERY: {reading.voltage:.1f}V",
                    priority=2,
                )
            except Exception as e:
                logger.error(f"Error showing warning alert: {e}")

        # Trigger callbacks
        self._triggerWarningCallbacks(reading)

    def _handleCritical(self, reading: VoltageReading) -> None:
        """
        Handle critical threshold exceeded.

        Args:
            reading: The voltage reading that triggered critical
        """
        logger.error(
            f"Battery voltage CRITICAL | voltage={reading.voltage}V, "
            f"threshold={self._criticalVoltage}V - initiating shutdown"
        )

        self._state = BatteryState.CRITICAL

        # Show visual alert
        if self._displayManager and hasattr(self._displayManager, 'showAlert'):
            try:
                self._displayManager.showAlert(
                    message=f"CRITICAL BATTERY: {reading.voltage:.1f}V - SHUTTING DOWN",
                    priority=1,
                )
            except Exception as e:
                logger.error(f"Error showing critical alert: {e}")

        # Trigger callbacks
        self._triggerCriticalCallbacks(reading)

        # Log shutdown event
        self._logToDatabase(reading, BATTERY_LOG_EVENT_SHUTDOWN)

        # Initiate graceful shutdown
        if self._shutdownManager and hasattr(self._shutdownManager, 'shutdown'):
            try:
                logger.info("Initiating graceful shutdown due to critical battery voltage")
                self._shutdownManager.shutdown()
            except Exception as e:
                logger.error(f"Error initiating shutdown: {e}")

    # ================================================================================
    # Statistics
    # ================================================================================

    def _updateStats(self, reading: VoltageReading) -> None:
        """
        Update statistics with new reading.

        Args:
            reading: The voltage reading
        """
        self._stats.totalReadings += 1
        self._stats.lastReading = reading.voltage

        # Update min/max
        if self._stats.minVoltage is None or reading.voltage < self._stats.minVoltage:
            self._stats.minVoltage = reading.voltage
        if self._stats.maxVoltage is None or reading.voltage > self._stats.maxVoltage:
            self._stats.maxVoltage = reading.voltage

        # Update warning/critical counts
        if reading.isCritical(self._criticalVoltage):
            self._stats.criticalCount += 1
            self._stats.lastCriticalTime = reading.timestamp
        elif reading.isWarning(self._warningVoltage):
            self._stats.warningCount += 1
            self._stats.lastWarningTime = reading.timestamp

    def getStats(self) -> BatteryStats:
        """
        Get battery statistics.

        Returns:
            BatteryStats with current statistics
        """
        with self._lock:
            return BatteryStats(
                totalReadings=self._stats.totalReadings,
                warningCount=self._stats.warningCount,
                criticalCount=self._stats.criticalCount,
                lastReading=self._stats.lastReading,
                minVoltage=self._stats.minVoltage,
                maxVoltage=self._stats.maxVoltage,
                lastWarningTime=self._stats.lastWarningTime,
                lastCriticalTime=self._stats.lastCriticalTime,
            )

    def resetStats(self) -> None:
        """Reset statistics."""
        with self._lock:
            self._stats = BatteryStats()
            logger.debug("Battery statistics reset")

    # ================================================================================
    # Database Logging
    # ================================================================================

    def _logToDatabase(self, reading: VoltageReading, eventType: str) -> None:
        """
        Log voltage reading to database.

        Args:
            reading: The voltage reading to log
            eventType: Type of event (voltage, warning, critical, shutdown)
        """
        if self._database is None:
            return

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO battery_log
                    (timestamp, event_type, voltage, warning_threshold, critical_threshold)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        reading.timestamp,
                        eventType,
                        reading.voltage,
                        self._warningVoltage,
                        self._criticalVoltage,
                    )
                )
                logger.debug(f"Logged voltage to database | type={eventType}, voltage={reading.voltage}V")
        except Exception as e:
            logger.error(f"Error logging voltage to database: {e}")

    def getVoltageHistory(
        self,
        limit: int = 100,
        eventType: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get voltage history from database.

        Args:
            limit: Maximum number of records to return
            eventType: Filter by event type (optional)

        Returns:
            List of voltage reading records
        """
        if self._database is None:
            return []

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()

                query = "SELECT * FROM battery_log WHERE 1=1"
                params: List[Any] = []

                if eventType:
                    query += " AND event_type = ?"
                    params.append(eventType)

                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()

                return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error getting voltage history: {e}")
            return []

    # ================================================================================
    # Callbacks
    # ================================================================================

    def onWarning(self, callback: Callable[[VoltageReading], None]) -> None:
        """
        Register a callback for warning events.

        Args:
            callback: Function to call when warning threshold is reached
        """
        self._onWarningCallbacks.append(callback)

    def onCritical(self, callback: Callable[[VoltageReading], None]) -> None:
        """
        Register a callback for critical events.

        Args:
            callback: Function to call when critical threshold is reached
        """
        self._onCriticalCallbacks.append(callback)

    def onReading(self, callback: Callable[[VoltageReading], None]) -> None:
        """
        Register a callback for all voltage readings.

        Args:
            callback: Function to call for every voltage reading
        """
        self._onReadingCallbacks.append(callback)

    def _triggerWarningCallbacks(self, reading: VoltageReading) -> None:
        """Trigger warning callbacks."""
        for callback in self._onWarningCallbacks:
            try:
                callback(reading)
            except Exception as e:
                logger.error(f"Error in warning callback: {e}")

    def _triggerCriticalCallbacks(self, reading: VoltageReading) -> None:
        """Trigger critical callbacks."""
        for callback in self._onCriticalCallbacks:
            try:
                callback(reading)
            except Exception as e:
                logger.error(f"Error in critical callback: {e}")

    def _triggerReadingCallbacks(self, reading: VoltageReading) -> None:
        """Trigger reading callbacks."""
        for callback in self._onReadingCallbacks:
            try:
                callback(reading)
            except Exception as e:
                logger.error(f"Error in reading callback: {e}")

    # ================================================================================
    # Status
    # ================================================================================

    def getStatus(self) -> Dict[str, Any]:
        """
        Get current battery monitor status.

        Returns:
            Dictionary with status information
        """
        with self._lock:
            return {
                'state': self._state.value,
                'enabled': self._enabled,
                'warningVoltage': self._warningVoltage,
                'criticalVoltage': self._criticalVoltage,
                'pollingIntervalSeconds': self._pollingIntervalSeconds,
                'hasVoltageReader': self._voltageReader is not None,
                'hasDatabase': self._database is not None,
                'hasDisplayManager': self._displayManager is not None,
                'hasShutdownManager': self._shutdownManager is not None,
                'stats': self._stats.toDict(),
            }
