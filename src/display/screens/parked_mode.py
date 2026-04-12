################################################################################
# File Name: parked_mode.py
# Purpose/Description: Parked mode display state and engine mode transition logic
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-128
# ================================================================================
################################################################################
"""
Parked mode display for the 3.5" touchscreen (480x320).

Activates when engine is off (RPM=0 sustained for configurable N seconds).
Returns to primary driving screen when engine restarts (RPM>0 sustained).

Shows:
- Sync status ('Syncing to server... 45%' or 'Sync complete')
- Last drive summary (duration, distance, alerts)
- Server advisory messages (if any downloaded from last sync)
- Battery remaining ('Pi battery: 78% (~1.5 hrs)')

Graceful handling when sync not configured or UPS not available.
Drive summary is a stub/placeholder until B-031 (US-135) is implemented.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from display.screens.system_detail import (
    BatteryInfo,
    SyncInfo,
    buildBatteryInfo,
    buildSyncInfo,
    formatDriveDuration,
)

logger = logging.getLogger(__name__)

DEFAULT_PARKED_THRESHOLD_SECONDS: float = 10.0
DEFAULT_RUNNING_THRESHOLD_SECONDS: float = 3.0
PLACEHOLDER_DISPLAY: str = "--"


# ================================================================================
# Enums
# ================================================================================


class EngineMode(Enum):
    """
    Engine operating mode for display state management.

    RUNNING: Engine is on (RPM > 0) — show primary driving screen
    PARKED: Engine is off (RPM = 0 sustained) — show parked mode screen
    """

    RUNNING = "running"
    PARKED = "parked"

    @property
    def displayLabel(self) -> str:
        """Human-readable label for display."""
        return {"running": "Running", "parked": "Parked"}[self.value]


# ================================================================================
# Data Classes
# ================================================================================


@dataclass
class DriveSummary:
    """
    Summary of the last drive session.

    Stub implementation — will be replaced by B-031 (US-135) drive summary
    generation when that feature is built.

    Attributes:
        durationSeconds: Drive duration in seconds
        distanceMiles: Distance driven in miles
        alertCount: Number of alerts during the drive
        formattedDuration: Human-readable duration string
        formattedDistance: Human-readable distance string
        isPlaceholder: Whether this is a placeholder (no data available)
    """

    durationSeconds: float
    distanceMiles: float
    alertCount: int
    formattedDuration: str
    formattedDistance: str
    isPlaceholder: bool = False


@dataclass
class AdvisoryMessage:
    """
    Server advisory message downloaded during sync.

    Attributes:
        message: Advisory text content
        priority: Message priority ('info', 'warning')
    """

    message: str
    priority: str


@dataclass
class ParkedModeState:
    """
    Display state for the parked mode screen.

    Attributes:
        syncInfo: Server sync status (reused from system_detail)
        driveSummary: Last drive session summary
        advisoryMessages: Server advisory messages (if any)
        batteryInfo: UPS battery information (reused from system_detail)
    """

    syncInfo: SyncInfo
    driveSummary: DriveSummary
    advisoryMessages: list[AdvisoryMessage] = field(default_factory=list)
    batteryInfo: BatteryInfo = field(default_factory=lambda: buildBatteryInfo(False))


# ================================================================================
# Core Functions
# ================================================================================


def formatDistance(miles: float) -> str:
    """
    Format distance as a human-readable string.

    Args:
        miles: Distance in miles

    Returns:
        Formatted string like '45.2 mi' or '0.0 mi'
    """
    return f"{miles:.1f} mi"


def buildDriveSummary(
    durationSeconds: float | None,
    distanceMiles: float | None,
    alertCount: int | None,
) -> DriveSummary:
    """
    Build a drive summary from drive data.

    When any value is None, returns a placeholder summary with dashes.
    Stub implementation until B-031 (US-135) drive summary generation.

    Args:
        durationSeconds: Drive duration in seconds, or None
        distanceMiles: Distance in miles, or None
        alertCount: Alert count, or None

    Returns:
        DriveSummary with formatted strings or placeholder values
    """
    if durationSeconds is None or distanceMiles is None or alertCount is None:
        return DriveSummary(
            durationSeconds=0.0,
            distanceMiles=0.0,
            alertCount=0,
            formattedDuration=PLACEHOLDER_DISPLAY,
            formattedDistance=PLACEHOLDER_DISPLAY,
            isPlaceholder=True,
        )

    return DriveSummary(
        durationSeconds=durationSeconds,
        distanceMiles=distanceMiles,
        alertCount=alertCount,
        formattedDuration=formatDriveDuration(durationSeconds),
        formattedDistance=formatDistance(distanceMiles),
        isPlaceholder=False,
    )


def buildParkedModeState(
    upsAvailable: bool,
    batteryLevelPercent: float | None,
    batteryEstimatedHours: float | None,
    lastSyncTimestamp: str | None,
    syncInProgress: bool,
    syncProgressPercent: float,
    driveDurationSeconds: float | None,
    driveDistanceMiles: float | None,
    driveAlertCount: int | None,
    advisoryMessages: list[AdvisoryMessage],
) -> ParkedModeState:
    """
    Build the complete parked mode display state.

    Aggregates sync, battery, drive summary, and advisory data into a
    single display state. Reuses system_detail builders for sync and battery.

    Args:
        upsAvailable: Whether UPS hardware is present
        batteryLevelPercent: Battery level 0-100, or None
        batteryEstimatedHours: Estimated remaining hours, or None
        lastSyncTimestamp: ISO timestamp of last sync, or None
        syncInProgress: Whether sync is currently running
        syncProgressPercent: Sync progress 0-100
        driveDurationSeconds: Last drive duration, or None
        driveDistanceMiles: Last drive distance, or None
        driveAlertCount: Alert count from last drive, or None
        advisoryMessages: Server advisory messages

    Returns:
        ParkedModeState with all display information
    """
    batteryInfo = buildBatteryInfo(upsAvailable, batteryLevelPercent, batteryEstimatedHours)
    syncInfo = buildSyncInfo(lastSyncTimestamp, syncInProgress, syncProgressPercent)
    driveSummary = buildDriveSummary(driveDurationSeconds, driveDistanceMiles, driveAlertCount)

    return ParkedModeState(
        syncInfo=syncInfo,
        driveSummary=driveSummary,
        advisoryMessages=list(advisoryMessages),
        batteryInfo=batteryInfo,
    )


# ================================================================================
# Stateful Tracker
# ================================================================================


class ParkedModeTracker:
    """
    Stateful tracker for engine mode transitions.

    Monitors RPM readings to detect sustained engine-off (parked) and
    engine-on (running) states. Uses configurable thresholds to prevent
    false transitions from momentary RPM fluctuations (starter cranks,
    brief ignition-off events).

    Call resetDrive() when starting a fresh session.
    """

    def __init__(
        self,
        parkedThresholdSeconds: float = DEFAULT_PARKED_THRESHOLD_SECONDS,
        runningThresholdSeconds: float = DEFAULT_RUNNING_THRESHOLD_SECONDS,
    ) -> None:
        self.parkedThresholdSeconds = parkedThresholdSeconds
        self.runningThresholdSeconds = runningThresholdSeconds

        self._currentMode: EngineMode = EngineMode.RUNNING
        self._lastTransitionTimestamp: float | None = None

        self._zeroRpmStartTimestamp: float | None = None
        self._nonZeroRpmStartTimestamp: float | None = None

    @property
    def currentMode(self) -> EngineMode:
        """Current engine mode."""
        return self._currentMode

    @property
    def lastTransitionTimestamp(self) -> float | None:
        """Timestamp of the most recent mode transition, or None."""
        return self._lastTransitionTimestamp

    def addRpmReading(self, timestamp: float, rpm: float) -> None:
        """
        Process an RPM reading and evaluate mode transitions.

        Args:
            timestamp: Reading timestamp in seconds (monotonic)
            rpm: Current RPM value (0.0 = engine off)
        """
        if rpm <= 0.0:
            self._handleZeroRpm(timestamp)
        else:
            self._handleNonZeroRpm(timestamp)

    def resetDrive(self) -> None:
        """Reset tracker to initial state for a new session."""
        self._currentMode = EngineMode.RUNNING
        self._lastTransitionTimestamp = None
        self._zeroRpmStartTimestamp = None
        self._nonZeroRpmStartTimestamp = None

    def getState(
        self,
        upsAvailable: bool,
        batteryLevelPercent: float | None,
        batteryEstimatedHours: float | None,
        lastSyncTimestamp: str | None,
        syncInProgress: bool,
        syncProgressPercent: float,
        driveDurationSeconds: float | None,
        driveDistanceMiles: float | None,
        driveAlertCount: int | None,
        advisoryMessages: list[AdvisoryMessage],
    ) -> ParkedModeState:
        """
        Build parked mode display state from current subsystem data.

        Args:
            upsAvailable: Whether UPS hardware is present
            batteryLevelPercent: Battery level 0-100, or None
            batteryEstimatedHours: Estimated remaining hours, or None
            lastSyncTimestamp: ISO timestamp of last sync, or None
            syncInProgress: Whether sync is currently running
            syncProgressPercent: Sync progress 0-100
            driveDurationSeconds: Last drive duration, or None
            driveDistanceMiles: Last drive distance, or None
            driveAlertCount: Alert count from last drive, or None
            advisoryMessages: Server advisory messages

        Returns:
            ParkedModeState with all display information
        """
        return buildParkedModeState(
            upsAvailable=upsAvailable,
            batteryLevelPercent=batteryLevelPercent,
            batteryEstimatedHours=batteryEstimatedHours,
            lastSyncTimestamp=lastSyncTimestamp,
            syncInProgress=syncInProgress,
            syncProgressPercent=syncProgressPercent,
            driveDurationSeconds=driveDurationSeconds,
            driveDistanceMiles=driveDistanceMiles,
            driveAlertCount=driveAlertCount,
            advisoryMessages=advisoryMessages,
        )

    def _handleZeroRpm(self, timestamp: float) -> None:
        """Handle an RPM=0 reading for mode transition logic."""
        self._nonZeroRpmStartTimestamp = None

        if self._currentMode == EngineMode.RUNNING:
            if self._zeroRpmStartTimestamp is None:
                self._zeroRpmStartTimestamp = timestamp
            else:
                elapsed = timestamp - self._zeroRpmStartTimestamp
                if elapsed >= self.parkedThresholdSeconds:
                    self._currentMode = EngineMode.PARKED
                    self._lastTransitionTimestamp = timestamp
                    self._zeroRpmStartTimestamp = None

    def _handleNonZeroRpm(self, timestamp: float) -> None:
        """Handle an RPM>0 reading for mode transition logic."""
        self._zeroRpmStartTimestamp = None

        if self._currentMode == EngineMode.PARKED:
            if self._nonZeroRpmStartTimestamp is None:
                self._nonZeroRpmStartTimestamp = timestamp
            else:
                elapsed = timestamp - self._nonZeroRpmStartTimestamp
                if elapsed >= self.runningThresholdSeconds:
                    self._currentMode = EngineMode.RUNNING
                    self._lastTransitionTimestamp = timestamp
                    self._nonZeroRpmStartTimestamp = None
