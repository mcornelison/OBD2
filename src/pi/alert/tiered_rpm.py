################################################################################
# File Name: tiered_rpm.py
# Purpose/Description: Tiered threshold evaluation for engine RPM
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Added RPM thresholds for US-110
# 2026-04-14    | Sweep 5      | Extracted from tiered_thresholds.py (task 4 split)
# ================================================================================
################################################################################
"""
Engine RPM tiered-threshold evaluation.

Boundaries from 4G63 stock valvetrain limits (97-99 2G factory redline
7000 RPM). Spool-authoritative values live in config.json under
pi.tieredThresholds.rpm and must not be changed here.
"""

from dataclasses import dataclass
from typing import Any

from .exceptions import AlertConfigurationError
from .tiered_core import AlertSeverity, TieredThresholdResult


@dataclass
class RPMThresholds:
    """
    RPM threshold configuration from obd_config.json.

    Attributes:
        normalMin: Lower boundary for normal idle range (RPM)
        cautionMin: Upper boundary for normal range (RPM), exclusive
        dangerMin: Lower boundary for danger range (RPM), exclusive
        unit: Unit label (rpm)
        lowIdleMessage: Message template for low idle alerts
        cautionMessage: Message template for high RPM caution
        dangerMessage: Message template for over-rev danger
    """

    normalMin: float
    cautionMin: float
    dangerMin: float
    unit: str = "rpm"
    lowIdleMessage: str = (
        "Idle RPM too low ({value} RPM). "
        "Possible vacuum leak or IAC issue."
    )
    cautionMessage: str = (
        "High RPM warning ({value} RPM). Stock redline approaching."
    )
    dangerMessage: str = (
        "DANGER: Over-rev ({value} RPM). "
        "Valve float risk on stock springs."
    )


def evaluateRPM(
    value: float,
    thresholds: RPMThresholds,
) -> TieredThresholdResult:
    """
    Evaluate engine RPM against tiered thresholds.

    Ranges (boundaries from 4G63 stock valvetrain limits):
    - Low Idle: value < normalMin — Possible vacuum leak or IAC issue
    - Normal: normalMin <= value <= cautionMin — No action
    - Caution: cautionMin < value <= dangerMin — Stock redline approaching
    - Danger: value > dangerMin — Valve float risk on stock springs

    Args:
        value: Engine RPM
        thresholds: Threshold configuration from obd_config.json

    Returns:
        TieredThresholdResult with severity, message, indicator, shouldLog
    """
    if value > thresholds.dangerMin:
        return TieredThresholdResult(
            parameterName="RPM",
            severity=AlertSeverity.DANGER,
            value=value,
            message=thresholds.dangerMessage.replace("{value}", str(value)),
            indicator="red",
            shouldLog=True,
        )

    if value > thresholds.cautionMin:
        return TieredThresholdResult(
            parameterName="RPM",
            severity=AlertSeverity.CAUTION,
            value=value,
            message=thresholds.cautionMessage.replace("{value}", str(value)),
            indicator="yellow",
            shouldLog=True,
        )

    if value >= thresholds.normalMin:
        return TieredThresholdResult(
            parameterName="RPM",
            severity=AlertSeverity.NORMAL,
            value=value,
            message="RPM within normal range.",
            indicator="green",
            shouldLog=False,
        )

    return TieredThresholdResult(
        parameterName="RPM",
        severity=AlertSeverity.INFO,
        value=value,
        message=thresholds.lowIdleMessage.replace("{value}", str(value)),
        indicator="blue",
        shouldLog=True,
    )


def loadRPMThresholds(
    config: dict[str, Any],
) -> RPMThresholds:
    """
    Load RPM thresholds from obd_config.json.

    Args:
        config: Full application configuration dictionary

    Returns:
        RPMThresholds loaded from config

    Raises:
        AlertConfigurationError: If tieredThresholds.rpm is missing
    """
    tiered = config.get("pi", {}).get("tieredThresholds")
    if not tiered:
        raise AlertConfigurationError(
            "Missing tieredThresholds section in config",
            details={"requiredKey": "tieredThresholds"},
        )

    rpm = tiered.get("rpm")
    if not rpm:
        raise AlertConfigurationError(
            "Missing tieredThresholds.rpm section in config",
            details={"requiredKey": "tieredThresholds.rpm"},
        )

    return RPMThresholds(
        normalMin=rpm["normalMin"],
        cautionMin=rpm["cautionMin"],
        dangerMin=rpm["dangerMin"],
        unit=rpm.get("unit", "rpm"),
        lowIdleMessage=rpm.get(
            "lowIdleMessage",
            "Idle RPM too low ({value} RPM). "
            "Possible vacuum leak or IAC issue.",
        ),
        cautionMessage=rpm.get(
            "cautionMessage",
            "High RPM warning ({value} RPM). Stock redline approaching.",
        ),
        dangerMessage=rpm.get(
            "dangerMessage",
            "DANGER: Over-rev ({value} RPM). "
            "Valve float risk on stock springs.",
        ),
    )
