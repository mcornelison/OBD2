################################################################################
# File Name: timing_thresholds.py
# Purpose/Description: Timing advance threshold evaluation with baseline tracking
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-109
# ================================================================================
################################################################################
"""
Timing advance threshold evaluation with per-RPM/load baseline tracking.

Unlike coolant/STFT (absolute ranges), timing advance uses baseline-relative
evaluation. The stock ECU retards timing when the knock sensor detects
detonation. A sudden drop at a specific RPM/load point means the engine
is knocking there — our only window into knock activity without ECMLink.

The system learns baselines per RPM/load operating point and detects:
- Sudden drops (> cautionDropDegrees below baseline) → Caution
- Timing at 0 or negative under load → Danger (active detonation)
- Repeated retards at the same operating point → Pattern flag

Thresholds are loaded from obd_config.json under tieredThresholds.timingAdvance.
"""

import logging
from dataclasses import dataclass
from typing import Any

from .exceptions import AlertConfigurationError
from .tiered_thresholds import AlertSeverity, TieredThresholdResult

logger = logging.getLogger(__name__)


# ================================================================================
# Data Classes
# ================================================================================


@dataclass
class TimingAdvanceThresholds:
    """
    Timing advance threshold configuration from obd_config.json.

    Attributes:
        cautionDropDegrees: Degrees below baseline to trigger caution (exclusive)
        dangerValue: At or below this value under load triggers danger
        loadThresholdPercent: Engine load % above which "under load" applies
        repeatCountForPattern: Retards at same point to flag as pattern
        rpmBandSize: RPM bucket size for baseline grouping
        loadBandSize: Load % bucket size for baseline grouping
        defaultBaseline: Timing advance assumed when no data learned
        unit: Unit label
        cautionMessage: Template for caution alerts
        dangerMessage: Template for danger alerts
        patternMessage: Template for pattern alerts
    """

    cautionDropDegrees: float
    dangerValue: float
    loadThresholdPercent: float
    repeatCountForPattern: int
    rpmBandSize: int
    loadBandSize: int
    defaultBaseline: float
    unit: str = "degrees"
    cautionMessage: str = (
        "Timing retard detected ({value} deg at {rpm} RPM"
        "/{load}% load). Dropped {drop} deg below baseline."
        " Possible knock event."
    )
    dangerMessage: str = (
        "DANGER: Timing advance at {value} deg under load."
        " Active detonation. Reduce throttle immediately."
        " Do not continue at this load."
    )
    patternMessage: str = (
        "PATTERN: Repeated timing retard at {rpm} RPM"
        "/{load}% load ({count} occurrences)."
        " Review fueling/boost at this operating point."
    )


@dataclass
class TimingBaselineEntry:
    """
    Learned baseline for a single RPM/load operating point.

    Attributes:
        rpmBand: RPM band floor value
        loadBand: Load band floor value
        baselineValue: Running average of normal timing advance
        sampleCount: Number of readings contributing to the average
    """

    rpmBand: int
    loadBand: int
    baselineValue: float
    sampleCount: int


# ================================================================================
# Tracker Class
# ================================================================================


class TimingRetardTracker:
    """
    Stateful tracker for timing advance baselines and retard patterns.

    Learns per-RPM/load baselines during normal operation and detects
    sudden timing retards indicating knock events. Tracks repeat
    occurrences at the same operating point for pattern detection.
    """

    def __init__(self, thresholds: TimingAdvanceThresholds) -> None:
        self._thresholds = thresholds
        self._baselines: dict[tuple[int, int], TimingBaselineEntry] = {}
        self._retardCounts: dict[tuple[int, int], int] = {}

    def getRpmBand(self, rpm: float) -> int:
        """Map RPM to its band floor value."""
        return int(rpm // self._thresholds.rpmBandSize) * self._thresholds.rpmBandSize

    def getLoadBand(self, load: float) -> int:
        """Map load percentage to its band floor value."""
        return (
            int(load // self._thresholds.loadBandSize) * self._thresholds.loadBandSize
        )

    def getBaseline(self, rpm: float, load: float) -> float:
        """
        Get the learned baseline for an RPM/load point.

        Args:
            rpm: Engine RPM
            load: Engine load percentage

        Returns:
            Learned baseline value, or defaultBaseline if none learned
        """
        key = (self.getRpmBand(rpm), self.getLoadBand(load))
        entry = self._baselines.get(key)
        if entry is not None:
            return entry.baselineValue
        return self._thresholds.defaultBaseline

    def updateBaseline(self, rpm: float, load: float, value: float) -> None:
        """
        Update the running-average baseline for an RPM/load point.

        Only called during normal operation (not during retard events)
        to prevent retarded values from corrupting the baseline.

        Args:
            rpm: Engine RPM
            load: Engine load percentage
            value: Timing advance reading
        """
        key = (self.getRpmBand(rpm), self.getLoadBand(load))
        entry = self._baselines.get(key)
        if entry is None:
            self._baselines[key] = TimingBaselineEntry(
                rpmBand=key[0],
                loadBand=key[1],
                baselineValue=value,
                sampleCount=1,
            )
        else:
            entry.sampleCount += 1
            entry.baselineValue += (value - entry.baselineValue) / entry.sampleCount

    def recordRetard(self, rpm: float, load: float) -> int:
        """
        Record a timing retard event at an RPM/load point.

        Args:
            rpm: Engine RPM
            load: Engine load percentage

        Returns:
            Total retard count at this operating point
        """
        key = (self.getRpmBand(rpm), self.getLoadBand(load))
        self._retardCounts[key] = self._retardCounts.get(key, 0) + 1
        return self._retardCounts[key]

    def getRetardCount(self, rpm: float, load: float) -> int:
        """
        Get the retard count for an RPM/load point.

        Args:
            rpm: Engine RPM
            load: Engine load percentage

        Returns:
            Number of retard events recorded at this operating point
        """
        key = (self.getRpmBand(rpm), self.getLoadBand(load))
        return self._retardCounts.get(key, 0)

    def evaluate(
        self, value: float, rpm: float, load: float
    ) -> TieredThresholdResult:
        """
        Evaluate timing advance against baseline and thresholds.

        Mutates internal state: updates baselines on normal readings,
        records retard events on caution/danger readings.

        Evaluation order:
        1. Danger: value <= dangerValue AND load > loadThresholdPercent
        2. Caution: drop from baseline > cautionDropDegrees
        3. Normal: update baseline with this reading

        Args:
            value: Timing advance in degrees
            rpm: Engine RPM
            load: Engine load percentage

        Returns:
            TieredThresholdResult with severity, message, indicator, shouldLog
        """
        thresholds = self._thresholds
        rpmBand = self.getRpmBand(rpm)
        loadBand = self.getLoadBand(load)

        isUnderLoad = load > thresholds.loadThresholdPercent
        if value <= thresholds.dangerValue and isUnderLoad:
            self.recordRetard(rpm, load)
            message = thresholds.dangerMessage.replace("{value}", str(value))
            return TieredThresholdResult(
                parameterName="TIMING_ADVANCE",
                severity=AlertSeverity.DANGER,
                value=value,
                message=message,
                indicator="red",
                shouldLog=True,
            )

        baseline = self.getBaseline(rpm, load)
        drop = baseline - value

        if drop > thresholds.cautionDropDegrees:
            retardCount = self.recordRetard(rpm, load)

            if retardCount >= thresholds.repeatCountForPattern:
                message = thresholds.patternMessage
                message = message.replace("{rpm}", str(rpmBand))
                message = message.replace("{load}", str(loadBand))
                message = message.replace("{count}", str(retardCount))
            else:
                message = thresholds.cautionMessage
                message = message.replace("{value}", str(value))
                message = message.replace("{rpm}", str(rpmBand))
                message = message.replace("{load}", str(loadBand))
                message = message.replace("{drop}", f"{drop:.1f}")

            return TieredThresholdResult(
                parameterName="TIMING_ADVANCE",
                severity=AlertSeverity.CAUTION,
                value=value,
                message=message,
                indicator="yellow",
                shouldLog=True,
            )

        self.updateBaseline(rpm, load, value)
        return TieredThresholdResult(
            parameterName="TIMING_ADVANCE",
            severity=AlertSeverity.NORMAL,
            value=value,
            message="Timing advance normal.",
            indicator="green",
            shouldLog=False,
        )


# ================================================================================
# Config Loading
# ================================================================================


def loadTimingAdvanceThresholds(
    config: dict[str, Any],
) -> TimingAdvanceThresholds:
    """
    Load timing advance thresholds from obd_config.json.

    Args:
        config: Full application configuration dictionary

    Returns:
        TimingAdvanceThresholds loaded from config

    Raises:
        AlertConfigurationError: If tieredThresholds.timingAdvance is missing
    """
    tiered = config.get("tieredThresholds")
    if not tiered:
        raise AlertConfigurationError(
            "Missing tieredThresholds section in config",
            details={"requiredKey": "tieredThresholds"},
        )

    timing = tiered.get("timingAdvance")
    if not timing:
        raise AlertConfigurationError(
            "Missing tieredThresholds.timingAdvance section in config",
            details={"requiredKey": "tieredThresholds.timingAdvance"},
        )

    return TimingAdvanceThresholds(
        cautionDropDegrees=timing["cautionDropDegrees"],
        dangerValue=timing["dangerValue"],
        loadThresholdPercent=timing["loadThresholdPercent"],
        repeatCountForPattern=timing["repeatCountForPattern"],
        rpmBandSize=timing["rpmBandSize"],
        loadBandSize=timing["loadBandSize"],
        defaultBaseline=timing["defaultBaseline"],
        unit=timing.get("unit", "degrees"),
        cautionMessage=timing.get(
            "cautionMessage",
            "Timing retard detected ({value} deg at {rpm} RPM"
            "/{load}% load). Dropped {drop} deg below baseline."
            " Possible knock event.",
        ),
        dangerMessage=timing.get(
            "dangerMessage",
            "DANGER: Timing advance at {value} deg under load."
            " Active detonation. Reduce throttle immediately."
            " Do not continue at this load.",
        ),
        patternMessage=timing.get(
            "patternMessage",
            "PATTERN: Repeated timing retard at {rpm} RPM"
            "/{load}% load ({count} occurrences)."
            " Review fueling/boost at this operating point.",
        ),
    )
