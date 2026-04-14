################################################################################
# File Name: thermal_detail.py
# Purpose/Description: Thermal detail page state and trend calculation logic
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-122
# ================================================================================
################################################################################
"""
Thermal detail page for the 3.5" touchscreen (480x320).

Shows temperature trends and time-at-temperature monitoring:
- Coolant temp with trend arrow (stable, rising, falling)
- Intake air temp
- Time at temperature (how long coolant has been above 200F this drive)

Trend arrow calculated from last 60 seconds of readings:
- Rising if average slope > +0.5F/min
- Falling if average slope < -0.5F/min
- Stable otherwise
"""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

TREND_WINDOW_SECONDS: float = 60.0
TREND_RISING_THRESHOLD: float = 0.5
TREND_FALLING_THRESHOLD: float = -0.5
TEMP_AT_THRESHOLD_DEFAULT: float = 200.0


# ================================================================================
# Enums
# ================================================================================


class TrendDirection(Enum):
    """
    Temperature trend direction for coolant trend arrow.

    RISING: Temperature increasing > 0.5F/min
    FALLING: Temperature decreasing < -0.5F/min
    STABLE: Temperature change within +/- 0.5F/min
    """

    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"

    @property
    def arrow(self) -> str:
        """Unicode arrow symbol for display."""
        return {"rising": "▲", "falling": "▼", "stable": "▶"}[self.value]


# ================================================================================
# Data Classes
# ================================================================================


@dataclass
class ThermalDetailState:
    """
    Display state for the thermal detail page.

    Attributes:
        coolantTemp: Current coolant temperature in F
        intakeAirTemp: Current intake air temperature in F
        trendDirection: Coolant temperature trend over last 60 seconds
        trendArrow: Unicode arrow symbol for the trend
        timeAtTempSeconds: Seconds coolant has been above threshold this drive
        tempAtThreshold: Temperature threshold for time-at-temp tracking (F)
    """

    coolantTemp: float
    intakeAirTemp: float
    trendDirection: TrendDirection
    trendArrow: str
    timeAtTempSeconds: float
    tempAtThreshold: float

    @property
    def formattedTimeAtTemp(self) -> str:
        """Format time-at-temp as M:SS string."""
        totalSeconds = int(self.timeAtTempSeconds)
        minutes = totalSeconds // 60
        seconds = totalSeconds % 60
        return f"{minutes}:{seconds:02d}"


# ================================================================================
# Core Functions
# ================================================================================


def calculateTrend(readings: list[tuple[float, float]]) -> TrendDirection:
    """
    Calculate temperature trend from timestamped readings.

    Uses first and last readings in the buffer to compute average slope
    over the window period. Boundary semantics: strictly greater/less than
    the threshold (not equal).

    Args:
        readings: List of (timestamp_seconds, temperature_F) tuples

    Returns:
        TrendDirection based on slope vs +/- 0.5 F/min thresholds
    """
    if len(readings) < 2:
        return TrendDirection.STABLE

    firstTimestamp, firstTemp = readings[0]
    lastTimestamp, lastTemp = readings[-1]

    timeDeltaSeconds = lastTimestamp - firstTimestamp
    if timeDeltaSeconds <= 0:
        return TrendDirection.STABLE

    timeDeltaMinutes = timeDeltaSeconds / 60.0
    slopePerMinute = (lastTemp - firstTemp) / timeDeltaMinutes

    if slopePerMinute > TREND_RISING_THRESHOLD:
        return TrendDirection.RISING
    elif slopePerMinute < TREND_FALLING_THRESHOLD:
        return TrendDirection.FALLING
    return TrendDirection.STABLE


def computeTimeAtTemperature(
    currentTemp: float,
    threshold: float,
    previousAccumulated: float,
    timeDelta: float,
) -> float:
    """
    Accumulate time spent above a temperature threshold.

    Only accumulates when currentTemp is strictly above the threshold.
    Negative time deltas are treated as zero (clock anomaly protection).

    Args:
        currentTemp: Current coolant temperature in F
        threshold: Temperature threshold in F (default 200F)
        previousAccumulated: Previously accumulated seconds
        timeDelta: Seconds since last reading

    Returns:
        Updated accumulated seconds
    """
    if timeDelta <= 0:
        return previousAccumulated
    if currentTemp > threshold:
        return previousAccumulated + timeDelta
    return previousAccumulated


# ================================================================================
# Stateful Tracker
# ================================================================================


class ThermalTracker:
    """
    Stateful tracker for thermal detail page data.

    Maintains a rolling window of coolant readings for trend calculation
    and accumulates time-at-temperature across a drive session. Call
    resetDrive() when starting a new drive to clear per-drive counters.
    """

    def __init__(self, tempAtThreshold: float = TEMP_AT_THRESHOLD_DEFAULT) -> None:
        self._tempAtThreshold = tempAtThreshold
        self._readingBuffer: list[tuple[float, float]] = []
        self._timeAtTempSeconds: float = 0.0
        self._coolantTemp: float = 0.0
        self._intakeAirTemp: float = 0.0
        self._lastTimestamp: float | None = None

    def addReading(
        self,
        timestamp: float,
        coolantTemp: float,
        intakeAirTemp: float,
    ) -> None:
        """
        Add a new temperature reading to the tracker.

        Args:
            timestamp: Reading timestamp in seconds (monotonic)
            coolantTemp: Current coolant temperature in F
            intakeAirTemp: Current intake air temperature in F
        """
        self._coolantTemp = coolantTemp
        self._intakeAirTemp = intakeAirTemp

        self._readingBuffer.append((timestamp, coolantTemp))
        self._pruneBuffer(timestamp)

        if self._lastTimestamp is not None:
            timeDelta = timestamp - self._lastTimestamp
            self._timeAtTempSeconds = computeTimeAtTemperature(
                currentTemp=coolantTemp,
                threshold=self._tempAtThreshold,
                previousAccumulated=self._timeAtTempSeconds,
                timeDelta=timeDelta,
            )

        self._lastTimestamp = timestamp

    def resetDrive(self) -> None:
        """Reset all per-drive counters for a new drive session."""
        self._readingBuffer.clear()
        self._timeAtTempSeconds = 0.0
        self._coolantTemp = 0.0
        self._intakeAirTemp = 0.0
        self._lastTimestamp = None

    def getState(self) -> ThermalDetailState:
        """
        Get current thermal detail state snapshot for display rendering.

        Returns:
            ThermalDetailState with current values and computed trend
        """
        trend = calculateTrend(self._readingBuffer)

        return ThermalDetailState(
            coolantTemp=self._coolantTemp,
            intakeAirTemp=self._intakeAirTemp,
            trendDirection=trend,
            trendArrow=trend.arrow,
            timeAtTempSeconds=self._timeAtTempSeconds,
            tempAtThreshold=self._tempAtThreshold,
        )

    def _pruneBuffer(self, currentTimestamp: float) -> None:
        """Remove readings older than the trend window."""
        cutoff = currentTimestamp - TREND_WINDOW_SECONDS
        self._readingBuffer = [
            (t, temp) for t, temp in self._readingBuffer if t >= cutoff
        ]
