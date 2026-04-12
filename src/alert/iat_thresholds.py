################################################################################
# File Name: iat_thresholds.py
# Purpose/Description: IAT threshold evaluation with sensor failure detection
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-112
# ================================================================================
################################################################################
"""
Intake Air Temperature (IAT) threshold evaluation with sensor failure detection.

IAT on 2G DSMs has a unique characteristic: the sensor is inside the MAF housing.
When it disconnects, OBD-II returns exactly -40F (-40C), which is the protocol's
default "no signal" value. This module detects that condition by tracking
consecutive -40F readings (configurable threshold, default 5).

Temperature thresholds evaluate heat soak risk on the turbocharged 4G63:
- Normal: ambient to cautionMin (130F) — normal for turbocharged intake
- Caution: cautionMin < value <= dangerMin — heat soak, power loss, knock risk
- Danger: value > dangerMin (160F) — significant knock risk at boost

Thresholds are loaded from obd_config.json under tieredThresholds.iat.
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
class IATThresholds:
    """
    IAT threshold configuration from obd_config.json.

    Attributes:
        cautionMin: Temperature above which caution is triggered (F), exclusive
        dangerMin: Temperature above which danger is triggered (F), exclusive
        sensorFailureValue: The exact value indicating sensor failure (F)
        consecutiveReadingsForFailure: Number of consecutive failure-value readings
            required before flagging sensor failure
        unit: Temperature unit (fahrenheit)
        cautionMessage: Message template for caution alerts
        dangerMessage: Message template for danger alerts
        sensorFailureMessage: Message template for sensor failure alerts
    """

    cautionMin: float
    dangerMin: float
    sensorFailureValue: float = -40.0
    consecutiveReadingsForFailure: int = 5
    unit: str = "fahrenheit"
    cautionMessage: str = (
        "IAT elevated ({value}F). Heat soak building. "
        "Power loss and increased knock risk."
    )
    dangerMessage: str = (
        "DANGER: IAT critical ({value}F). Significant knock risk "
        "at boost. Reduce load."
    )
    sensorFailureMessage: str = (
        "IAT sensor failure detected. Reading fixed at {value}F "
        "for {count} consecutive readings. "
        "Sensor disconnected or failed (check MAF housing connector)."
    )


# ================================================================================
# Stateless Evaluation
# ================================================================================


def evaluateIAT(
    value: float,
    thresholds: IATThresholds,
) -> TieredThresholdResult:
    """
    Evaluate IAT against tiered thresholds (stateless, no sensor failure check).

    Ranges (boundaries from turbo 4G63 heat soak limits):
    - Normal: value <= cautionMin — Normal for turbocharged intake
    - Caution: cautionMin < value <= dangerMin — Heat soak building
    - Danger: value > dangerMin — Significant knock risk at boost

    Args:
        value: Intake air temperature in the configured unit
        thresholds: Threshold configuration from obd_config.json

    Returns:
        TieredThresholdResult with severity, message, indicator, shouldLog
    """
    if value > thresholds.dangerMin:
        return TieredThresholdResult(
            parameterName="IAT",
            severity=AlertSeverity.DANGER,
            value=value,
            message=thresholds.dangerMessage.replace("{value}", str(value)),
            indicator="red",
            shouldLog=True,
        )

    if value > thresholds.cautionMin:
        return TieredThresholdResult(
            parameterName="IAT",
            severity=AlertSeverity.CAUTION,
            value=value,
            message=thresholds.cautionMessage.replace("{value}", str(value)),
            indicator="yellow",
            shouldLog=True,
        )

    return TieredThresholdResult(
        parameterName="IAT",
        severity=AlertSeverity.NORMAL,
        value=value,
        message="IAT within normal range.",
        indicator="green",
        shouldLog=False,
    )


# ================================================================================
# Stateful Sensor Failure Tracker
# ================================================================================


class IATSensorTracker:
    """
    Tracks IAT readings to detect sensor failure via consecutive -40F readings.

    The 2G DSM IAT sensor is inside the MAF housing. When disconnected, OBD-II
    returns -40F/-40C. A single -40F could be genuinely cold air, so we require
    N consecutive readings at exactly the failure value before flagging.

    Usage:
        tracker = IATSensorTracker(thresholds)
        result = tracker.evaluate(currentIAT)
    """

    def __init__(self, thresholds: IATThresholds) -> None:
        """
        Initialize the IAT sensor tracker.

        Args:
            thresholds: IAT threshold configuration
        """
        self._thresholds = thresholds
        self._consecutiveFailureCount: int = 0

    def evaluate(self, value: float) -> TieredThresholdResult:
        """
        Evaluate IAT with sensor failure detection.

        Tracks consecutive readings at the sensor failure value. Once the
        configured threshold is reached, returns a sensor failure result
        instead of a normal threshold evaluation.

        Args:
            value: Current IAT reading in configured unit

        Returns:
            TieredThresholdResult — sensor failure if consecutive threshold met,
            otherwise standard threshold evaluation
        """
        if value == self._thresholds.sensorFailureValue:
            self._consecutiveFailureCount += 1
            if (
                self._consecutiveFailureCount
                >= self._thresholds.consecutiveReadingsForFailure
            ):
                message = self._thresholds.sensorFailureMessage.replace(
                    "{value}", str(value)
                ).replace("{count}", str(self._consecutiveFailureCount))
                return TieredThresholdResult(
                    parameterName="IAT",
                    severity=AlertSeverity.INFO,
                    value=value,
                    message=message,
                    indicator="blue",
                    shouldLog=True,
                )
            return evaluateIAT(value, self._thresholds)
        else:
            self._consecutiveFailureCount = 0
            return evaluateIAT(value, self._thresholds)

    def reset(self) -> None:
        """Reset the consecutive failure counter."""
        self._consecutiveFailureCount = 0


# ================================================================================
# Config Loading
# ================================================================================


def loadIATThresholds(
    config: dict[str, Any],
) -> IATThresholds:
    """
    Load IAT thresholds from obd_config.json.

    Args:
        config: Full application configuration dictionary

    Returns:
        IATThresholds loaded from config

    Raises:
        AlertConfigurationError: If tieredThresholds.iat is missing
    """
    tiered = config.get("tieredThresholds")
    if not tiered:
        raise AlertConfigurationError(
            "Missing tieredThresholds section in config",
            details={"requiredKey": "tieredThresholds"},
        )

    iat = tiered.get("iat")
    if not iat:
        raise AlertConfigurationError(
            "Missing tieredThresholds.iat section in config",
            details={"requiredKey": "tieredThresholds.iat"},
        )

    return IATThresholds(
        cautionMin=iat["cautionMin"],
        dangerMin=iat["dangerMin"],
        sensorFailureValue=iat.get("sensorFailureValue", -40.0),
        consecutiveReadingsForFailure=iat.get("consecutiveReadingsForFailure", 5),
        unit=iat.get("unit", "fahrenheit"),
        cautionMessage=iat.get(
            "cautionMessage",
            "IAT elevated ({value}F). Heat soak building. "
            "Power loss and increased knock risk.",
        ),
        dangerMessage=iat.get(
            "dangerMessage",
            "DANGER: IAT critical ({value}F). Significant knock risk "
            "at boost. Reduce load.",
        ),
        sensorFailureMessage=iat.get(
            "sensorFailureMessage",
            "IAT sensor failure detected. Reading fixed at {value}F "
            "for {count} consecutive readings. "
            "Sensor disconnected or failed (check MAF housing connector).",
        ),
    )
