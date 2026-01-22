################################################################################
# File Name: failure_injector.py
# Purpose/Description: Failure injection system for OBD-II simulator testing
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-038
# ================================================================================
################################################################################

"""
Failure injection system for the Eclipse OBD-II simulator.

Provides:
- FailureInjector class for injecting simulated failures
- FailureType enum defining available failure modes
- FailureConfig dataclass for configuring failure behavior
- ScheduledFailure for timed failure injection
- Support for connectionDrop, sensorFailure, intermittentSensor, outOfRange, dtcCodes

This module enables testing error handling and recovery logic by injecting
various failure conditions into the simulated OBD-II connection.

Usage:
    from obd.simulator.failure_injector import FailureInjector, FailureType

    # Create injector
    injector = FailureInjector()

    # Inject a connection drop
    injector.injectFailure(FailureType.CONNECTION_DROP)

    # Inject sensor failure for specific sensor
    injector.injectFailure(
        FailureType.SENSOR_FAILURE,
        FailureConfig(sensorNames=["COOLANT_TEMP"])
    )

    # Schedule a timed failure
    injector.scheduleFailure(
        FailureType.INTERMITTENT_SENSOR,
        startSeconds=5.0,
        durationSeconds=10.0
    )

    # Clear failures
    injector.clearFailure(FailureType.CONNECTION_DROP)
    injector.clearAllFailures()
"""

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Default intermittent failure probability (30% chance of failure)
DEFAULT_INTERMITTENT_PROBABILITY = 0.3

# Default out-of-range deviation factor
DEFAULT_OUT_OF_RANGE_FACTOR = 3.0

# Common DTC codes for testing
COMMON_DTC_CODES = [
    "P0300",  # Random/Multiple Cylinder Misfire Detected
    "P0171",  # System Too Lean (Bank 1)
    "P0172",  # System Too Rich (Bank 1)
    "P0420",  # Catalyst System Efficiency Below Threshold (Bank 1)
    "P0440",  # Evaporative Emission System Malfunction
    "P0500",  # Vehicle Speed Sensor Malfunction
    "P0128",  # Coolant Thermostat (Coolant Temperature Below Thermostat Regulating Temperature)
    "P0340",  # Camshaft Position Sensor Circuit Malfunction
]


# ================================================================================
# Enums
# ================================================================================

class FailureType(Enum):
    """
    Available failure injection types.

    Attributes:
        CONNECTION_DROP: Simulates loss of OBD-II connection
        SENSOR_FAILURE: Makes specific sensor(s) return null/error
        INTERMITTENT_SENSOR: Sensors randomly fail/succeed
        OUT_OF_RANGE: Sensors return values outside normal range
        DTC_CODES: Simulates diagnostic trouble codes being set
    """

    CONNECTION_DROP = "connectionDrop"
    SENSOR_FAILURE = "sensorFailure"
    INTERMITTENT_SENSOR = "intermittentSensor"
    OUT_OF_RANGE = "outOfRange"
    DTC_CODES = "dtcCodes"

    @classmethod
    def fromString(cls, value: str) -> Optional["FailureType"]:
        """
        Convert string to FailureType enum.

        Args:
            value: String representation of failure type

        Returns:
            FailureType enum or None if not found
        """
        # Normalize input (lowercase, handle both camelCase and snake_case)
        normalized = value.lower().replace("_", "").replace("-", "")

        for failureType in cls:
            if failureType.value.lower().replace("_", "") == normalized:
                return failureType

        return None


class FailureState(Enum):
    """Failure injection state."""

    INACTIVE = "inactive"
    ACTIVE = "active"
    SCHEDULED = "scheduled"


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class FailureConfig:
    """
    Configuration for a failure injection.

    Attributes:
        sensorNames: List of sensor names affected (for sensor-specific failures)
        probability: Probability of failure occurring (0.0-1.0, for intermittent)
        outOfRangeFactor: Factor by which to exceed normal range (for out_of_range)
        outOfRangeDirection: Direction of out-of-range: 'high', 'low', or 'random'
        dtcCodes: List of DTC codes to report (for dtc_codes)
        customValue: Custom value to return instead of simulated value
        affectsAllSensors: If True, affects all sensors (not just sensorNames)
    """

    sensorNames: List[str] = field(default_factory=list)
    probability: float = DEFAULT_INTERMITTENT_PROBABILITY
    outOfRangeFactor: float = DEFAULT_OUT_OF_RANGE_FACTOR
    outOfRangeDirection: str = "random"  # 'high', 'low', or 'random'
    dtcCodes: List[str] = field(default_factory=list)
    customValue: Optional[float] = None
    affectsAllSensors: bool = False

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        # Normalize sensor names to uppercase
        self.sensorNames = [s.upper() for s in self.sensorNames]

        # Clamp probability to valid range
        self.probability = max(0.0, min(1.0, self.probability))

        # Validate out-of-range direction
        validDirections = {"high", "low", "random"}
        if self.outOfRangeDirection not in validDirections:
            self.outOfRangeDirection = "random"

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sensorNames": self.sensorNames,
            "probability": self.probability,
            "outOfRangeFactor": self.outOfRangeFactor,
            "outOfRangeDirection": self.outOfRangeDirection,
            "dtcCodes": self.dtcCodes,
            "customValue": self.customValue,
            "affectsAllSensors": self.affectsAllSensors,
        }

    @classmethod
    def fromDict(cls, data: Dict[str, Any]) -> "FailureConfig":
        """Create from dictionary."""
        return cls(
            sensorNames=data.get("sensorNames", []),
            probability=data.get("probability", DEFAULT_INTERMITTENT_PROBABILITY),
            outOfRangeFactor=data.get("outOfRangeFactor", DEFAULT_OUT_OF_RANGE_FACTOR),
            outOfRangeDirection=data.get("outOfRangeDirection", "random"),
            dtcCodes=data.get("dtcCodes", []),
            customValue=data.get("customValue"),
            affectsAllSensors=data.get("affectsAllSensors", False),
        )


@dataclass
class ScheduledFailure:
    """
    A scheduled failure injection.

    Attributes:
        failureType: Type of failure to inject
        config: Configuration for the failure
        startSeconds: Seconds from now to start the failure
        durationSeconds: How long the failure should last (None = permanent)
        startTime: Actual start time (set when scheduled)
        endTime: Actual end time (set when scheduled)
        id: Unique identifier for this scheduled failure
    """

    failureType: FailureType
    config: FailureConfig
    startSeconds: float
    durationSeconds: Optional[float]
    startTime: Optional[float] = None
    endTime: Optional[float] = None
    id: str = ""

    def __post_init__(self) -> None:
        """Set start and end times."""
        if not self.id:
            self.id = f"{self.failureType.value}_{id(self)}"

        currentTime = time.time()
        self.startTime = currentTime + self.startSeconds

        if self.durationSeconds is not None:
            self.endTime = self.startTime + self.durationSeconds
        else:
            self.endTime = None

    def isActive(self, currentTime: Optional[float] = None) -> bool:
        """Check if this scheduled failure is currently active."""
        if currentTime is None:
            currentTime = time.time()

        if self.startTime is None:
            return False

        if currentTime < self.startTime:
            return False  # Not started yet

        if self.endTime is None:
            return True  # Permanent after start

        return currentTime < self.endTime

    def isExpired(self, currentTime: Optional[float] = None) -> bool:
        """Check if this scheduled failure has expired."""
        if currentTime is None:
            currentTime = time.time()

        if self.endTime is None:
            return False  # Never expires

        return currentTime >= self.endTime

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "failureType": self.failureType.value,
            "config": self.config.toDict(),
            "startSeconds": self.startSeconds,
            "durationSeconds": self.durationSeconds,
            "startTime": self.startTime,
            "endTime": self.endTime,
            "id": self.id,
        }


@dataclass
class ActiveFailure:
    """
    An active failure injection.

    Attributes:
        failureType: Type of failure
        config: Configuration for the failure
        activatedAt: When the failure was activated
        scheduledFailure: Reference to scheduled failure if applicable
    """

    failureType: FailureType
    config: FailureConfig
    activatedAt: float = field(default_factory=time.time)
    scheduledFailure: Optional[ScheduledFailure] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "failureType": self.failureType.value,
            "config": self.config.toDict(),
            "activatedAt": self.activatedAt,
            "scheduledFailureId": (
                self.scheduledFailure.id if self.scheduledFailure else None
            ),
        }


@dataclass
class InjectorStatus:
    """
    Status of the failure injector.

    Attributes:
        isActive: Whether any failures are currently active
        activeFailures: List of currently active failure types
        scheduledFailures: Number of scheduled failures pending
        totalInjected: Total number of failures ever injected
        dtcCodes: Currently active DTC codes
    """

    isActive: bool = False
    activeFailures: List[str] = field(default_factory=list)
    scheduledFailures: int = 0
    totalInjected: int = 0
    dtcCodes: List[str] = field(default_factory=list)

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "isActive": self.isActive,
            "activeFailures": self.activeFailures,
            "scheduledFailures": self.scheduledFailures,
            "totalInjected": self.totalInjected,
            "dtcCodes": self.dtcCodes,
        }


# ================================================================================
# FailureInjector Class
# ================================================================================

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
        self._activeFailures: Dict[FailureType, ActiveFailure] = {}

        # Scheduled failures
        self._scheduledFailures: List[ScheduledFailure] = []

        # Lock for thread safety
        self._lock = threading.Lock()

        # Scheduler thread
        self._schedulerThread: Optional[threading.Thread] = None
        self._schedulerRunning = False
        self._schedulerInterval = 0.1  # Check every 100ms

        # Statistics
        self._totalInjected = 0

        # Callbacks
        self._onFailureInjected: Optional[Callable[[FailureType, FailureConfig], None]] = None
        self._onFailureCleared: Optional[Callable[[FailureType], None]] = None

        logger.debug("FailureInjector initialized")

    # ==========================================================================
    # Failure Injection
    # ==========================================================================

    def injectFailure(
        self,
        failureType: FailureType,
        config: Optional[FailureConfig] = None
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
        durationSeconds: Optional[float] = None,
        config: Optional[FailureConfig] = None
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
            expiredSchedules: List[ScheduledFailure] = []
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
    ) -> Optional[FailureConfig]:
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
    def failedSensors(self) -> Set[str]:
        """Get set of sensors that are in failure mode."""
        result: Set[str] = set()

        with self._lock:
            # Check SENSOR_FAILURE
            if FailureType.SENSOR_FAILURE in self._activeFailures:
                config = self._activeFailures[FailureType.SENSOR_FAILURE].config
                if config.affectsAllSensors:
                    return {"*"}  # Special marker for all sensors
                result.update(config.sensorNames)

        return result

    @property
    def activeDtcCodes(self) -> List[str]:
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
    ) -> Optional[float]:
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

    def getActiveFailures(self) -> Dict[str, ActiveFailure]:
        """
        Get all active failures.

        Returns:
            Dictionary of failure type string to ActiveFailure
        """
        with self._lock:
            return {
                ft.value: af for ft, af in self._activeFailures.items()
            }

    def getScheduledFailures(self) -> List[ScheduledFailure]:
        """
        Get all scheduled failures.

        Returns:
            List of scheduled failures
        """
        with self._lock:
            return list(self._scheduledFailures)

    def setOnFailureInjectedCallback(
        self,
        callback: Optional[Callable[[FailureType, FailureConfig], None]]
    ) -> None:
        """
        Set callback for when a failure is injected.

        Args:
            callback: Function(failureType, config) to call, or None to clear
        """
        self._onFailureInjected = callback

    def setOnFailureClearedCallback(
        self,
        callback: Optional[Callable[[FailureType], None]]
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


# ================================================================================
# Helper Functions
# ================================================================================

def createFailureInjectorFromConfig(
    config: Dict[str, Any]
) -> FailureInjector:
    """
    Create a FailureInjector from configuration.

    Config may contain a 'simulator.failures' section with pre-configured
    failures to inject on startup.

    Args:
        config: Configuration dictionary

    Returns:
        Configured FailureInjector instance

    Example:
        config = {
            "simulator": {
                "failures": {
                    "connectionDrop": False,
                    "sensorFailure": {
                        "enabled": True,
                        "sensors": ["COOLANT_TEMP"]
                    }
                }
            }
        }
        injector = createFailureInjectorFromConfig(config)
    """
    injector = FailureInjector()

    # Get failures config
    failuresConfig = config.get("simulator", {}).get("failures", {})

    # Process each failure type
    for failureTypeStr, failureData in failuresConfig.items():
        failureType = FailureType.fromString(failureTypeStr)
        if failureType is None:
            logger.warning(f"Unknown failure type in config: {failureTypeStr}")
            continue

        # Handle boolean or dict config
        if isinstance(failureData, bool):
            if failureData:
                injector.injectFailure(failureType)
        elif isinstance(failureData, dict):
            enabled = failureData.get("enabled", True)
            if enabled:
                failureConfig = FailureConfig(
                    sensorNames=failureData.get("sensors", []),
                    probability=failureData.get(
                        "probability",
                        DEFAULT_INTERMITTENT_PROBABILITY
                    ),
                    outOfRangeFactor=failureData.get(
                        "outOfRangeFactor",
                        DEFAULT_OUT_OF_RANGE_FACTOR
                    ),
                    outOfRangeDirection=failureData.get(
                        "outOfRangeDirection",
                        "random"
                    ),
                    dtcCodes=failureData.get("dtcCodes", []),
                    affectsAllSensors=failureData.get("affectsAllSensors", False),
                )
                injector.injectFailure(failureType, failureConfig)

    return injector


def getDefaultFailureInjector() -> FailureInjector:
    """
    Get a default FailureInjector ready for use.

    Returns:
        FailureInjector with no active failures
    """
    return FailureInjector()
