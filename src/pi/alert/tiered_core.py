################################################################################
# File Name: tiered_core.py
# Purpose/Description: Shared AlertSeverity enum + TieredThresholdResult dataclass
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
Shared primitives for the tiered-threshold subsystem.

Provides AlertSeverity enum and TieredThresholdResult dataclass used by the
per-parameter evaluation modules (tiered_coolant, tiered_stft, tiered_rpm,
tiered_battery).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AlertSeverity(Enum):
    """Severity levels for tiered threshold evaluation."""

    INFO = "info"
    NORMAL = "normal"
    CAUTION = "caution"
    DANGER = "danger"


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
