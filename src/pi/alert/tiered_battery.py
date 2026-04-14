################################################################################
# File Name: tiered_battery.py
# Purpose/Description: Tiered threshold evaluation for battery / control-module voltage
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Added Battery Voltage thresholds for US-111
# 2026-04-12    | Ralph Agent  | US-145: Clarify descriptive-only fields in docstring
# 2026-04-14    | Sweep 5      | Extracted from tiered_thresholds.py (task 4 split)
# ================================================================================
################################################################################
"""
Battery voltage tiered-threshold evaluation.

Battery voltage is bidirectional: both too-low (charging failure) and
too-high (regulator failure) are dangerous. Spool-authoritative values
live in config.json under pi.tieredThresholds.batteryVoltage and must
not be changed here.
"""

from dataclasses import dataclass
from typing import Any

from .exceptions import AlertConfigurationError
from .tiered_core import AlertSeverity, TieredThresholdResult


@dataclass
class BatteryVoltageThresholds:
    """
    Battery voltage threshold configuration from obd_config.json.

    Battery voltage is bidirectional: both too-low (charging failure) and
    too-high (regulator failure) are dangerous. Uses separate boundaries
    for each direction with distinct messages.

    Runtime comparison fields (used by evaluateBatteryVoltage):
        normalMin, normalMax, dangerLowMax, dangerHighMin

    Descriptive-only fields (NOT used in evaluateBatteryVoltage comparisons):
        cautionLowMin, cautionHighMax — These describe the approximate
        boundaries of the caution ranges for documentation and config
        readability. They do not affect runtime behavior.

    Attributes:
        normalMin: Lower boundary for normal range (V), inclusive [RUNTIME]
        normalMax: Upper boundary for normal range (V), inclusive [RUNTIME]
        cautionLowMin: Descriptive lower boundary for caution-low range (V) [NOT USED IN COMPARISONS]
        cautionHighMax: Descriptive upper boundary for caution-high range (V) [NOT USED IN COMPARISONS]
        dangerLowMax: Upper boundary for danger-low range (V), inclusive [RUNTIME]
        dangerHighMin: Lower boundary for danger-high range (V), exclusive [RUNTIME]
        unit: Voltage unit label
        cautionMessageLow: Message template for low-voltage caution
        cautionMessageHigh: Message template for high-voltage caution
        dangerMessageLow: Message template for low-voltage danger
        dangerMessageHigh: Message template for high-voltage danger
    """

    normalMin: float
    normalMax: float
    cautionLowMin: float
    cautionHighMax: float
    dangerLowMax: float
    dangerHighMin: float
    unit: str = "volts"
    cautionMessageLow: str = (
        "Battery voltage low ({value}V). "
        "Weak alternator output. Monitor charging system."
    )
    cautionMessageHigh: str = (
        "Battery voltage high ({value}V). "
        "Voltage regulator starting to fail. Monitor closely."
    )
    dangerMessageLow: str = (
        "DANGER: Battery voltage critical ({value}V). "
        "Charging system failure. Engine may stall. "
        "Check alternator and belt."
    )
    dangerMessageHigh: str = (
        "DANGER: Battery voltage excessive ({value}V). "
        "Voltage regulator failed. Risk of damage to "
        "battery and electronics."
    )


def evaluateBatteryVoltage(
    value: float,
    thresholds: BatteryVoltageThresholds,
) -> TieredThresholdResult:
    """
    Evaluate battery voltage against tiered thresholds.

    Battery voltage is bidirectional: both too-low and too-high are problems.
    Evaluation order: danger-high, danger-low, normal, then caution (with
    low/high message selection based on which side of normal).

    Ranges (engine running):
    - Danger Low: value <= dangerLowMax — Charging failure
    - Caution Low: dangerLowMax < value < normalMin — Weak alternator
    - Normal: normalMin <= value <= normalMax — Healthy
    - Caution High: normalMax < value <= dangerHighMin — Regulator issue
    - Danger High: value > dangerHighMin — Regulator failed

    Args:
        value: Battery/control module voltage in volts
        thresholds: Threshold configuration from obd_config.json

    Returns:
        TieredThresholdResult with severity, message, indicator, shouldLog
    """
    if value > thresholds.dangerHighMin:
        return TieredThresholdResult(
            parameterName="BATTERY_VOLTAGE",
            severity=AlertSeverity.DANGER,
            value=value,
            message=thresholds.dangerMessageHigh.replace("{value}", str(value)),
            indicator="red",
            shouldLog=True,
        )

    if value <= thresholds.dangerLowMax:
        return TieredThresholdResult(
            parameterName="BATTERY_VOLTAGE",
            severity=AlertSeverity.DANGER,
            value=value,
            message=thresholds.dangerMessageLow.replace("{value}", str(value)),
            indicator="red",
            shouldLog=True,
        )

    if thresholds.normalMin <= value <= thresholds.normalMax:
        return TieredThresholdResult(
            parameterName="BATTERY_VOLTAGE",
            severity=AlertSeverity.NORMAL,
            value=value,
            message="Battery voltage normal. Charging system healthy.",
            indicator="green",
            shouldLog=False,
        )

    if value < thresholds.normalMin:
        return TieredThresholdResult(
            parameterName="BATTERY_VOLTAGE",
            severity=AlertSeverity.CAUTION,
            value=value,
            message=thresholds.cautionMessageLow.replace("{value}", str(value)),
            indicator="yellow",
            shouldLog=True,
        )

    return TieredThresholdResult(
        parameterName="BATTERY_VOLTAGE",
        severity=AlertSeverity.CAUTION,
        value=value,
        message=thresholds.cautionMessageHigh.replace("{value}", str(value)),
        indicator="yellow",
        shouldLog=True,
    )


def loadBatteryVoltageThresholds(
    config: dict[str, Any],
) -> BatteryVoltageThresholds:
    """
    Load battery voltage thresholds from obd_config.json.

    Args:
        config: Full application configuration dictionary

    Returns:
        BatteryVoltageThresholds loaded from config

    Raises:
        AlertConfigurationError: If tieredThresholds.batteryVoltage is missing
    """
    tiered = config.get("pi", {}).get("tieredThresholds")
    if not tiered:
        raise AlertConfigurationError(
            "Missing tieredThresholds section in config",
            details={"requiredKey": "tieredThresholds"},
        )

    bv = tiered.get("batteryVoltage")
    if not bv:
        raise AlertConfigurationError(
            "Missing tieredThresholds.batteryVoltage section in config",
            details={"requiredKey": "tieredThresholds.batteryVoltage"},
        )

    return BatteryVoltageThresholds(
        normalMin=bv["normalMin"],
        normalMax=bv["normalMax"],
        cautionLowMin=bv.get("cautionLowMin", 12.01),
        cautionHighMax=bv.get("cautionHighMax", 14.99),
        dangerLowMax=bv.get("dangerLowMax", 12.0),
        dangerHighMin=bv.get("dangerHighMin", 15.0),
        unit=bv.get("unit", "volts"),
        cautionMessageLow=bv.get(
            "cautionMessageLow",
            "Battery voltage low ({value}V). "
            "Weak alternator output. Monitor charging system.",
        ),
        cautionMessageHigh=bv.get(
            "cautionMessageHigh",
            "Battery voltage high ({value}V). "
            "Voltage regulator starting to fail. Monitor closely.",
        ),
        dangerMessageLow=bv.get(
            "dangerMessageLow",
            "DANGER: Battery voltage critical ({value}V). "
            "Charging system failure. Engine may stall. "
            "Check alternator and belt.",
        ),
        dangerMessageHigh=bv.get(
            "dangerMessageHigh",
            "DANGER: Battery voltage excessive ({value}V). "
            "Voltage regulator failed. Risk of damage to "
            "battery and electronics.",
        ),
    )
