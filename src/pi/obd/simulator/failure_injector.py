################################################################################
# File Name: failure_injector.py
# Purpose/Description: FailureInjector class for simulator testing; re-exports failure types
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-038
# 2026-04-14    | Sweep 5       | Types extracted to failure_types.py; factories to failure_factory.py
# ================================================================================
################################################################################

"""
Failure injection system for the Eclipse OBD-II simulator.

Provides the FailureInjector class for injecting simulated failures.
Supporting types (FailureType, FailureConfig, ScheduledFailure, etc.)
live in failure_types.py and are re-exported here for backwards compat.
Factory helpers (createFailureInjectorFromConfig) live in failure_factory.py.

Usage:
    from obd.simulator.failure_injector import FailureInjector, FailureType

    injector = FailureInjector()
    injector.injectFailure(FailureType.CONNECTION_DROP)

    injector.scheduleFailure(
        FailureType.INTERMITTENT_SENSOR,
        startSeconds=5.0,
        durationSeconds=10.0,
    )

    injector.clearFailure(FailureType.CONNECTION_DROP)
    injector.clearAllFailures()
"""

import logging
import random
import threading
import time
from collections.abc import Callable

from .failure_types import (
    COMMON_DTC_CODES,
    DEFAULT_INTERMITTENT_PROBABILITY,
    DEFAULT_OUT_OF_RANGE_FACTOR,
    ActiveFailure,
    FailureConfig,
    FailureState,
    FailureType,
    InjectorStatus,
    ScheduledFailure,
)

logger = logging.getLogger(__name__)


__all__ = [
    'COMMON_DTC_CODES',
    'DEFAULT_INTERMITTENT_PROBABILITY',
    'DEFAULT_OUT_OF_RANGE_FACTOR',
    'ActiveFailure',
    'FailureConfig',
    'FailureInjector',
    'FailureState',
    'FailureType',
    'InjectorStatus',
    'ScheduledFailure',
]


class FailureInjector:
    """
    Failure injection system for OBD-II simulator testing.

    Allows injecting various failure conditions into the simulated OBD-II
    connection to test error handling and recovery logic.

    Attributes:
        isConnectionDropped: Whether connection drop is active
        failedSensors: Set of sensors that are in failure mode
        activeDtcCodes: List of active DTC codes

    Example:
        injector = FailureInjector()

        # Inject connection drop
        injector.injectFailure(FailureType.CONNECTION_DROP)

        # Check if connected (will return False due to injection)
        if injector.isConnectionDropped:
            print("Connection is simulated as dropped")

        # Clear the failure
        injector.clearFailure(FailureType.CONNECTION_DROP)
    """

    def __init__(self) -> None:
        """Initialize FailureInjector."""
        # Active failures by type
        self._activeFailures: dict[FailureType, ActiveFailure] = {}

        # Scheduled failures
        self._scheduledFailures: list[ScheduledFailure] = []

        # Lock for thread safety
        self._lock = threading.Lock()

        # Scheduler thread
        self._schedulerThread: threading.Thread | None = None
        self._schedulerRunning = False
        self._schedulerInterval = 0.1  # Check every 100ms

        # Statistics
        self._totalInjected = 0

        # Callbacks
        self._onFailureInjected: Callable[[FailureType, FailureConfig], None] | None = None
        self._onFailureCleared: Callable[[FailureType], None] | None = None

        logger.debug("FailureInjector initialized")

    # ==========================================================================
    # Failure Injection
    # ==========================================================================

    def injectFailure(
        self,
        failureType: FailureType,
        config: FailureConfig | None = None
    ) -> bool:
        """
        Inject a failure mode.

        Args:
            failureType: Type of failure to inject
            config: Configuration for the failure (uses defaults if None)

        Returns:
            True if failure was injected, False if already active
        """
        with self._lock:
            # Check if already active
            if failureType in self._activeFailures:
                logger.debug(f"Failure already active: {failureType.value}")
                return False

            # Use default config if not provided
            if config is None:
                config = FailureConfig()

            # Add default DTC codes if none specified for DTC_CODES type
            if failureType == FailureType.DTC_CODES and not config.dtcCodes:
                config.dtcCodes = [COMMON_DTC_CODES[0]]

            # Create active failure
            activeFailure = ActiveFailure(
                failureType=failureType,
                config=config,
            )

            self._activeFailures[failureType] = activeFailure
            self._totalInjected += 1

            logger.info(
                f"Failure injected: {failureType.value} | "
                f"config={config.toDict()}"
            )

            # Trigger callback
            if self._onFailureInjected:
                try:
                    self._onFailureInjected(failureType, config)
                except Exception as e:
                    logger.warning(f"Failure injected callback error: {e}")

            return True

    def clearFailure(self, failureType: FailureType) -> bool:
        """
        Clear a specific failure mode.

        Args:
            failureType: Type of failure to clear

        Returns:
            True if failure was cleared, False if not active
        """
        with self._lock:
            if failureType not in self._activeFailures:
                logger.debug(f"Failure not active: {failureType.value}")
                return False

            del self._activeFailures[failureType]

            logger.info(f"Failure cleared: {failureType.value}")

            # Trigger callback
            if self._onFailureCleared:
                try:
                    self._onFailureCleared(failureType)
                except Exception as e:
                    logger.warning(f"Failure cleared callback error: {e}")

            return True

    def clearAllFailures(self) -> int:
        """
        Clear all active failure modes.

        Returns:
            Number of failures cleared
        """
        with self._lock:
            count = len(self._activeFailures)
            failureTypes = list(self._activeFailures.keys())

            for failureType in failureTypes:
                del self._activeFailures[failureType]

                # Trigger callback for each
                if self._onFailureCleared:
                    try:
                        self._onFailureCleared(failureType)
                    except Exception as e:
                        logger.warning(f"Failure cleared callback error: {e}")

            # Also clear scheduled failures
            self._scheduledFailures.clear()

            logger.info(f"All failures cleared | count={count}")
            return count

    # ==========================================================================
    # Scheduled Failures
    # ==========================================================================

    def scheduleFailure(
        self,
        failureType: FailureType,
        startSeconds: float,
        durationSeconds: float | None = None,
        config: FailureConfig | None = None
    ) -> ScheduledFailure:
        """
        Schedule a failure to be injected at a future time.

        Args:
            failureType: Type of failure to inject
            startSeconds: Seconds from now to start the failure
            durationSeconds: How long the failure should last (None = permanent)
            config: Configuration for the failure

        Returns:
            ScheduledFailure object for tracking
        """
        if config is None:
            config = FailureConfig()

        # Add default DTC codes if none specified for DTC_CODES type
        if failureType == FailureType.DTC_CODES and not config.dtcCodes:
            config.dtcCodes = [COMMON_DTC_CODES[0]]

        scheduled = ScheduledFailure(
            failureType=failureType,
            config=config,
            startSeconds=startSeconds,
            durationSeconds=durationSeconds,
        )

        with self._lock:
            self._scheduledFailures.append(scheduled)

        logger.info(
            f"Failure scheduled: {failureType.value} | "
            f"startIn={startSeconds}s | "
            f"duration={durationSeconds}s"
        )

        # Ensure scheduler is running
        self._ensureSchedulerRunning()

        return scheduled

    def cancelScheduledFailure(self, scheduledFailure: ScheduledFailure) -> bool:
        """
        Cancel a scheduled failure.

        Args:
            scheduledFailure: The scheduled failure to cancel

        Returns:
            True if cancelled, False if not found
        """
        with self._lock:
            if scheduledFailure in self._scheduledFailures:
                self._scheduledFailures.remove(scheduledFailure)
                logger.info(f"Scheduled failure cancelled: {scheduledFailure.id}")
                return True
            return False

    def _ensureSchedulerRunning(self) -> None:
        """Ensure the scheduler thread is running."""
        if self._schedulerRunning:
            return

        self._schedulerRunning = True
        self._schedulerThread = threading.Thread(
            target=self._schedulerLoop,
            daemon=True,
            name="FailureInjectorScheduler"
        )
        self._schedulerThread.start()
        logger.debug("Scheduler thread started")

    def _schedulerLoop(self) -> None:
        """Main scheduler loop that processes scheduled failures."""
        while self._schedulerRunning:
            try:
                self._processScheduledFailures()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            time.sleep(self._schedulerInterval)

    def _processScheduledFailures(self) -> None:
        """Process scheduled failures - activate/deactivate as needed."""
        currentTime = time.time()

        with self._lock:
            # Check for failures to activate
            for scheduled in list(self._scheduledFailures):
                if scheduled.isActive(currentTime):
                    # Check if already activated from this schedule
                    if scheduled.failureType in self._activeFailures:
                        activeFailure = self._activeFailures[scheduled.failureType]
                        if activeFailure.scheduledFailure == scheduled:
                            continue  # Already active from this schedule

                    # Activate the failure
                    activeFailure = ActiveFailure(
                        failureType=scheduled.failureType,
                        config=scheduled.config,
                        scheduledFailure=scheduled,
                    )
                    self._activeFailures[scheduled.failureType] = activeFailure
                    self._totalInjected += 1

                    logger.info(f"Scheduled failure activated: {scheduled.id}")

                    if self._onFailureInjected:
                        try:
                            self._onFailureInjected(
                                scheduled.failureType,
                                scheduled.config
                            )
                        except Exception as e:
                            logger.warning(f"Callback error: {e}")

            # Check for expired failures
            expiredSchedules: list[ScheduledFailure] = []
            for scheduled in self._scheduledFailures:
                if scheduled.isExpired(currentTime):
                    expiredSchedules.append(scheduled)

            # Remove expired and deactivate
            for scheduled in expiredSchedules:
                self._scheduledFailures.remove(scheduled)

                # Deactivate if this scheduled failure is the active one
                if scheduled.failureType in self._activeFailures:
                    activeFailure = self._activeFailures[scheduled.failureType]
                    if activeFailure.scheduledFailure == scheduled:
                        del self._activeFailures[scheduled.failureType]
                        logger.info(f"Scheduled failure expired: {scheduled.id}")

                        if self._onFailureCleared:
                            try:
                                self._onFailureCleared(scheduled.failureType)
                            except Exception as e:
                                logger.warning(f"Callback error: {e}")

    def stopScheduler(self) -> None:
        """Stop the scheduler thread."""
        self._schedulerRunning = False
        if self._schedulerThread:
            self._schedulerThread.join(timeout=1.0)
            self._schedulerThread = None
        logger.debug("Scheduler thread stopped")

    # ==========================================================================
    # Failure Checking
    # ==========================================================================

    def isFailureActive(self, failureType: FailureType) -> bool:
        """
        Check if a specific failure type is active.

        Args:
            failureType: Failure type to check

        Returns:
            True if the failure is currently active
        """
        with self._lock:
            return failureType in self._activeFailures

    def getActiveFailureConfig(
        self,
        failureType: FailureType
    ) -> FailureConfig | None:
        """
        Get the configuration for an active failure.

        Args:
            failureType: Failure type to get config for

        Returns:
            FailureConfig if active, None otherwise
        """
        with self._lock:
            if failureType in self._activeFailures:
                return self._activeFailures[failureType].config
            return None

    @property
    def isConnectionDropped(self) -> bool:
        """Check if connection drop failure is active."""
        return self.isFailureActive(FailureType.CONNECTION_DROP)

    @property
    def failedSensors(self) -> set[str]:
        """Get set of sensors that are in failure mode."""
        result: set[str] = set()

        with self._lock:
            # Check SENSOR_FAILURE
            if FailureType.SENSOR_FAILURE in self._activeFailures:
                config = self._activeFailures[FailureType.SENSOR_FAILURE].config
                if config.affectsAllSensors:
                    return {"*"}  # Special marker for all sensors
                result.update(config.sensorNames)

        return result

    @property
    def activeDtcCodes(self) -> list[str]:
        """Get list of active DTC codes."""
        with self._lock:
            if FailureType.DTC_CODES in self._activeFailures:
                config = self._activeFailures[FailureType.DTC_CODES].config
                return list(config.dtcCodes)
            return []

    def shouldSensorFail(self, sensorName: str) -> bool:
        """
        Check if a sensor should fail (return null).

        Considers both SENSOR_FAILURE and INTERMITTENT_SENSOR modes.

        Args:
            sensorName: Name of the sensor to check

        Returns:
            True if the sensor should fail
        """
        sensorName = sensorName.upper()

        with self._lock:
            # Check permanent sensor failure
            if FailureType.SENSOR_FAILURE in self._activeFailures:
                config = self._activeFailures[FailureType.SENSOR_FAILURE].config
                if config.affectsAllSensors:
                    return True
                if sensorName in config.sensorNames:
                    return True

            # Check intermittent sensor failure
            if FailureType.INTERMITTENT_SENSOR in self._activeFailures:
                config = self._activeFailures[FailureType.INTERMITTENT_SENSOR].config

                # Check if this sensor is affected
                isAffected = (
                    config.affectsAllSensors or
                    not config.sensorNames or
                    sensorName in config.sensorNames
                )

                if isAffected:
                    # Random failure based on probability
                    return random.random() < config.probability

        return False

    def getModifiedValue(
        self,
        sensorName: str,
        originalValue: float
    ) -> float | None:
        """
        Get a potentially modified value for out-of-range failure.

        Args:
            sensorName: Name of the sensor
            originalValue: Original simulated value

        Returns:
            Modified value if out-of-range failure applies, or None to use original
        """
        sensorName = sensorName.upper()

        with self._lock:
            if FailureType.OUT_OF_RANGE not in self._activeFailures:
                return None

            config = self._activeFailures[FailureType.OUT_OF_RANGE].config

            # Check if this sensor is affected
            isAffected = (
                config.affectsAllSensors or
                not config.sensorNames or
                sensorName in config.sensorNames
            )

            if not isAffected:
                return None

            # Use custom value if provided
            if config.customValue is not None:
                return config.customValue

            # Calculate out-of-range value
            direction = config.outOfRangeDirection
            if direction == "random":
                direction = random.choice(["high", "low"])

            factor = config.outOfRangeFactor
            if direction == "high":
                return originalValue * factor
            else:
                # Low direction - could be negative for some values
                return originalValue / factor if factor != 0 else 0.0

        return None

    # ==========================================================================
    # Status and Callbacks
    # ==========================================================================

    def getStatus(self) -> InjectorStatus:
        """
        Get current status of the failure injector.

        Returns:
            InjectorStatus with current state information
        """
        with self._lock:
            activeTypes = [f.value for f in self._activeFailures.keys()]
            dtcCodes = []

            if FailureType.DTC_CODES in self._activeFailures:
                dtcCodes = list(
                    self._activeFailures[FailureType.DTC_CODES].config.dtcCodes
                )

            return InjectorStatus(
                isActive=bool(self._activeFailures),
                activeFailures=activeTypes,
                scheduledFailures=len(self._scheduledFailures),
                totalInjected=self._totalInjected,
                dtcCodes=dtcCodes,
            )

    def getActiveFailures(self) -> dict[str, ActiveFailure]:
        """
        Get all active failures.

        Returns:
            Dictionary of failure type string to ActiveFailure
        """
        with self._lock:
            return {
                ft.value: af for ft, af in self._activeFailures.items()
            }

    def getScheduledFailures(self) -> list[ScheduledFailure]:
        """
        Get all scheduled failures.

        Returns:
            List of scheduled failures
        """
        with self._lock:
            return list(self._scheduledFailures)

    def setOnFailureInjectedCallback(
        self,
        callback: Callable[[FailureType, FailureConfig], None] | None
    ) -> None:
        """
        Set callback for when a failure is injected.

        Args:
            callback: Function(failureType, config) to call, or None to clear
        """
        self._onFailureInjected = callback

    def setOnFailureClearedCallback(
        self,
        callback: Callable[[FailureType], None] | None
    ) -> None:
        """
        Set callback for when a failure is cleared.

        Args:
            callback: Function(failureType) to call, or None to clear
        """
        self._onFailureCleared = callback

    def reset(self) -> None:
        """Reset injector to clean state."""
        self.stopScheduler()
        with self._lock:
            self._activeFailures.clear()
            self._scheduledFailures.clear()
            self._totalInjected = 0
        logger.debug("FailureInjector reset")
