################################################################################
# File Name: tiered_stft.py
# Purpose/Description: Tiered threshold evaluation for STFT (short-term fuel trim)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Added STFT thresholds for US-108
# 2026-04-14    | Sweep 5      | Extracted from tiered_thresholds.py (task 4 split)
# ================================================================================
################################################################################
"""
STFT (short-term fuel trim) tiered-threshold evaluation.

STFT is bidirectional around 0%. Positive = lean correction (ECU adding
fuel); negative = rich correction (ECU removing fuel). Evaluation uses
abs(value) for threshold comparison and selects lean/rich messages by
sign. Values loaded from config['pi']['tieredThresholds']['stft'].
"""

from dataclasses import dataclass
from typing import Any

from .exceptions import AlertConfigurationError
from .tiered_core import AlertSeverity, TieredThresholdResult


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
    tiered = config.get("pi", {}).get("tieredThresholds")
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
