################################################################################
# File Name: tiered_thresholds.py
# Purpose/Description: Tiered threshold evaluation for multi-level alerts
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-107
# 2026-04-12    | Ralph Agent  | Added STFT thresholds for US-108
# ================================================================================
################################################################################
"""
Tiered threshold evaluation for multi-level parameter alerts.

Unlike single-threshold alerts (above/below one value), tiered thresholds
evaluate a parameter against multiple ranges, each with its own severity,
indicator color, and message. Used for parameters where different ranges
require different driver responses (e.g., coolant temp: cold/normal/caution/danger).

Thresholds are loaded from obd_config.json under the tieredThresholds key.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .exceptions import AlertConfigurationError

logger = logging.getLogger(__name__)


# ================================================================================
# Enums
# ================================================================================


class AlertSeverity(Enum):
    """Severity levels for tiered threshold evaluation."""

    INFO = "info"
    NORMAL = "normal"
    CAUTION = "caution"
    DANGER = "danger"


# ================================================================================
# Data Classes
# ================================================================================


@dataclass
class CoolantTempThresholds:
    """
    Coolant temperature threshold configuration from obd_config.json.

    Attributes:
        normalMin: Lower boundary for normal range (F)
        cautionMin: Lower boundary for caution range (F), exclusive
        dangerMin: Lower boundary for danger range (F), exclusive
        unit: Temperature unit (fahrenheit)
        cautionMessage: Message template for caution alerts
        dangerMessage: Message template for danger alerts
    """

    normalMin: float
    cautionMin: float
    dangerMin: float
    unit: str = "fahrenheit"
    cautionMessage: str = (
        "Coolant temperature elevated ({value}F). Monitor closely."
    )
    dangerMessage: str = (
        "DANGER: Coolant temperature critical ({value}F). "
        "Risk of head gasket failure. Reduce load immediately."
    )


@dataclass
class STFTThresholds:
    """
    STFT threshold configuration from obd_config.json.

    STFT is bidirectional (symmetric around 0%): positive values indicate
    lean correction, negative values indicate rich correction. Thresholds
    use abs(value) for comparison, with separate messages for each direction.

    Attributes:
        cautionMin: Absolute value threshold for caution (e.g., 5 = ±5%)
        dangerMin: Absolute value threshold for danger (e.g., 15 = ±15%)
        unit: Unit label (percent)
        cautionMessageLean: Message template for positive caution
        cautionMessageRich: Message template for negative caution
        dangerMessageLean: Message template for positive danger
        dangerMessageRich: Message template for negative danger
    """

    cautionMin: float
    dangerMin: float
    unit: str = "percent"
    cautionMessageLean: str = (
        "STFT lean correction elevated ({value}%). "
        "ECU compensating. Monitor for trend."
    )
    cautionMessageRich: str = (
        "STFT rich correction elevated ({value}%). "
        "ECU compensating. Monitor for trend."
    )
    dangerMessageLean: str = (
        "DANGER: STFT at correction limit ({value}%). "
        "Active lean condition. Possible vacuum leak, "
        "weak fuel pump, or clogged injector."
    )
    dangerMessageRich: str = (
        "DANGER: STFT at correction limit ({value}%). "
        "Active rich condition. Check for leaking injector "
        "or fuel pressure regulator."
    )


@dataclass
class TieredThresholdResult:
    """
    Result of a tiered threshold evaluation.

    Attributes:
        parameterName: OBD-II parameter name
        severity: Evaluated severity level
        value: The evaluated value
        message: Human-readable alert message
        indicator: Indicator color (blue, green, yellow, red)
        shouldLog: Whether this result should create an alert log entry
    """

    parameterName: str
    severity: AlertSeverity
    value: float
    message: str
    indicator: str
    shouldLog: bool

    def toLogEntry(self) -> dict[str, Any]:
        """
        Convert to alert log entry dict for database storage.

        Returns:
            Dictionary with severity, parameterName, value, message
        """
        return {
            "severity": self.severity.value,
            "parameterName": self.parameterName,
            "value": self.value,
            "message": self.message,
        }


# ================================================================================
# Evaluation Functions
# ================================================================================


def evaluateCoolantTemp(
    value: float,
    thresholds: CoolantTempThresholds,
) -> TieredThresholdResult:
    """
    Evaluate coolant temperature against tiered thresholds.

    Ranges (boundaries from 4G63 head gasket thermal limits):
    - Cold: value < normalMin — Engine not at operating temp
    - Normal: normalMin <= value <= cautionMin — No action
    - Caution: cautionMin < value <= dangerMin — Monitor closely
    - Danger: value > dangerMin — Risk of head gasket failure

    Args:
        value: Coolant temperature in the configured unit
        thresholds: Threshold configuration from obd_config.json

    Returns:
        TieredThresholdResult with severity, message, indicator, shouldLog
    """
    if value > thresholds.dangerMin:
        return TieredThresholdResult(
            parameterName="COOLANT_TEMP",
            severity=AlertSeverity.DANGER,
            value=value,
            message=thresholds.dangerMessage.replace("{value}", str(value)),
            indicator="red",
            shouldLog=True,
        )

    if value > thresholds.cautionMin:
        return TieredThresholdResult(
            parameterName="COOLANT_TEMP",
            severity=AlertSeverity.CAUTION,
            value=value,
            message=thresholds.cautionMessage.replace("{value}", str(value)),
            indicator="yellow",
            shouldLog=True,
        )

    if value >= thresholds.normalMin:
        return TieredThresholdResult(
            parameterName="COOLANT_TEMP",
            severity=AlertSeverity.NORMAL,
            value=value,
            message="Coolant temperature normal.",
            indicator="green",
            shouldLog=False,
        )

    return TieredThresholdResult(
        parameterName="COOLANT_TEMP",
        severity=AlertSeverity.INFO,
        value=value,
        message="Engine not at operating temperature. Normal during warmup.",
        indicator="blue",
        shouldLog=False,
    )


def evaluateSTFT(
    value: float,
    thresholds: STFTThresholds,
) -> TieredThresholdResult:
    """
    Evaluate STFT against symmetric tiered thresholds.

    STFT is bidirectional: positive = lean (ECU adding fuel),
    negative = rich (ECU removing fuel). Uses abs(value) for threshold
    comparison, then selects lean or rich message based on sign.

    Ranges:
    - Normal: abs(value) < cautionMin — Small corrections, healthy
    - Caution: cautionMin <= abs(value) < dangerMin — ECU working harder
    - Danger: abs(value) >= dangerMin — ECU at correction limit

    Args:
        value: STFT percentage (positive = lean, negative = rich)
        thresholds: Threshold configuration from obd_config.json

    Returns:
        TieredThresholdResult with severity, message, indicator, shouldLog
    """
    absValue = abs(value)
    isLean = value > 0

    if absValue >= thresholds.dangerMin:
        message = (
            thresholds.dangerMessageLean if isLean else thresholds.dangerMessageRich
        )
        return TieredThresholdResult(
            parameterName="STFT",
            severity=AlertSeverity.DANGER,
            value=value,
            message=message.replace("{value}", str(value)),
            indicator="red",
            shouldLog=True,
        )

    if absValue >= thresholds.cautionMin:
        message = (
            thresholds.cautionMessageLean
            if isLean
            else thresholds.cautionMessageRich
        )
        return TieredThresholdResult(
            parameterName="STFT",
            severity=AlertSeverity.CAUTION,
            value=value,
            message=message.replace("{value}", str(value)),
            indicator="yellow",
            shouldLog=True,
        )

    return TieredThresholdResult(
        parameterName="STFT",
        severity=AlertSeverity.NORMAL,
        value=value,
        message="STFT within normal range.",
        indicator="green",
        shouldLog=False,
    )


# ================================================================================
# Config Loading
# ================================================================================


def loadCoolantTempThresholds(
    config: dict[str, Any],
) -> CoolantTempThresholds:
    """
    Load coolant temperature thresholds from obd_config.json.

    Args:
        config: Full application configuration dictionary

    Returns:
        CoolantTempThresholds loaded from config

    Raises:
        AlertConfigurationError: If tieredThresholds.coolantTemp is missing
    """
    tiered = config.get("tieredThresholds")
    if not tiered:
        raise AlertConfigurationError(
            "Missing tieredThresholds section in config",
            details={"requiredKey": "tieredThresholds"},
        )

    coolant = tiered.get("coolantTemp")
    if not coolant:
        raise AlertConfigurationError(
            "Missing tieredThresholds.coolantTemp section in config",
            details={"requiredKey": "tieredThresholds.coolantTemp"},
        )

    return CoolantTempThresholds(
        normalMin=coolant["normalMin"],
        cautionMin=coolant["cautionMin"],
        dangerMin=coolant["dangerMin"],
        unit=coolant.get("unit", "fahrenheit"),
        cautionMessage=coolant.get(
            "cautionMessage",
            "Coolant temperature elevated ({value}F). Monitor closely.",
        ),
        dangerMessage=coolant.get(
            "dangerMessage",
            "DANGER: Coolant temperature critical ({value}F). "
            "Risk of head gasket failure. Reduce load immediately.",
        ),
    )


def loadSTFTThresholds(
    config: dict[str, Any],
) -> STFTThresholds:
    """
    Load STFT thresholds from obd_config.json.

    Args:
        config: Full application configuration dictionary

    Returns:
        STFTThresholds loaded from config

    Raises:
        AlertConfigurationError: If tieredThresholds.stft is missing
    """
    tiered = config.get("tieredThresholds")
    if not tiered:
        raise AlertConfigurationError(
            "Missing tieredThresholds section in config",
            details={"requiredKey": "tieredThresholds"},
        )

    stft = tiered.get("stft")
    if not stft:
        raise AlertConfigurationError(
            "Missing tieredThresholds.stft section in config",
            details={"requiredKey": "tieredThresholds.stft"},
        )

    return STFTThresholds(
        cautionMin=stft["cautionMin"],
        dangerMin=stft["dangerMin"],
        unit=stft.get("unit", "percent"),
        cautionMessageLean=stft.get(
            "cautionMessageLean",
            "STFT lean correction elevated ({value}%). "
            "ECU compensating. Monitor for trend.",
        ),
        cautionMessageRich=stft.get(
            "cautionMessageRich",
            "STFT rich correction elevated ({value}%). "
            "ECU compensating. Monitor for trend.",
        ),
        dangerMessageLean=stft.get(
            "dangerMessageLean",
            "DANGER: STFT at correction limit ({value}%). "
            "Active lean condition. Possible vacuum leak, "
            "weak fuel pump, or clogged injector.",
        ),
        dangerMessageRich=stft.get(
            "dangerMessageRich",
            "DANGER: STFT at correction limit ({value}%). "
            "Active rich condition. Check for leaking injector "
            "or fuel pressure regulator.",
        ),
    )
