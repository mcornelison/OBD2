################################################################################
# File Name: tiered_coolant.py
# Purpose/Description: Tiered threshold evaluation for coolant temperature
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-107
# 2026-04-14    | Sweep 5      | Extracted from tiered_thresholds.py (task 4 split)
# ================================================================================
################################################################################
"""
Coolant temperature tiered-threshold evaluation.

Boundaries from 4G63 head gasket thermal limits. Load from
config['pi']['tieredThresholds']['coolantTemp'] — Spool-authoritative values
are in config.json and MUST NOT be changed here.
"""

from dataclasses import dataclass
from typing import Any

from .exceptions import AlertConfigurationError
from .tiered_core import AlertSeverity, TieredThresholdResult


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
    tiered = config.get("pi", {}).get("tieredThresholds")
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
