################################################################################
# File Name: primary_screen.py
# Purpose/Description: Primary driving screen state and status indicator logic
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-121
# ================================================================================
################################################################################
"""
Primary driving screen for the 3.5" touchscreen (480x320).

The driver is DRIVING — information must be glanceable in under 1 second.
This module manages the screen state: parameter evaluations, overall status
indicator (worst-status-wins), and Phase 2 element visibility.

Display elements by priority:
- Status Indicator: large, always visible (Green circle / Yellow triangle / Red X)
- Coolant Temperature: large, 1 Hz
- RPM: medium, 1 Hz
- Boost: medium, Phase 2 only (ECMLink + MAP sensor)
- AFR: medium, Phase 2 only (ECMLink + wideband)
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from alert.tiered_thresholds import (
    AlertSeverity,
    CoolantTempThresholds,
    RPMThresholds,
    TieredThresholdResult,
    evaluateCoolantTemp,
    evaluateRPM,
)

logger = logging.getLogger(__name__)

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 320

_SEVERITY_TO_STATUS_ORDER = {
    AlertSeverity.INFO: 0,
    AlertSeverity.NORMAL: 0,
    AlertSeverity.CAUTION: 1,
    AlertSeverity.DANGER: 2,
}

_SEVERITY_TO_INDICATOR = {
    AlertSeverity.INFO: "blue",
    AlertSeverity.NORMAL: "green",
    AlertSeverity.CAUTION: "yellow",
    AlertSeverity.DANGER: "red",
}

_PARAMETER_CONFIG = {
    "COOLANT_TEMP": {"label": "Coolant", "unit": "F", "priority": "large", "isPhase2": False},
    "RPM": {"label": "RPM", "unit": "rpm", "priority": "medium", "isPhase2": False},
    "BOOST": {"label": "Boost", "unit": "psi", "priority": "medium", "isPhase2": True},
    "AFR": {"label": "AFR", "unit": "", "priority": "medium", "isPhase2": True},
}


# ================================================================================
# Enums
# ================================================================================


class OverallStatus(Enum):
    """
    Overall system status indicator for primary driving screen.

    GREEN: All parameters within normal range. Drive happy.
    YELLOW: One or more parameters in caution range. Tap for details.
    RED: One or more parameters in danger range. Audible alert.
    """

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"

    @property
    def severityOrder(self) -> int:
        """Numeric ordering for worst-status-wins comparison."""
        return {"green": 0, "yellow": 1, "red": 2}[self.value]


# ================================================================================
# Data Classes
# ================================================================================


@dataclass
class ParameterDisplay:
    """
    Display state for a single parameter on the primary screen.

    Attributes:
        name: OBD-II parameter identifier (e.g., COOLANT_TEMP, RPM)
        label: Human-readable label for display
        value: Current parameter value
        unit: Display unit (F, rpm, psi, etc.)
        severity: Current threshold evaluation severity
        indicatorColor: Color string for value display (green/yellow/red/blue)
        isPhase2: Whether this parameter requires ECMLink hardware
        priority: Display size priority (large, medium)
    """

    name: str
    label: str
    value: float
    unit: str
    severity: AlertSeverity
    indicatorColor: str
    isPhase2: bool = False
    priority: str = "medium"


@dataclass
class PrimaryScreenState:
    """
    Complete state for the primary driving screen.

    Attributes:
        overallStatus: Aggregated status indicator (worst-status-wins)
        parameters: All parameter display states (including hidden Phase 2)
        visibleParameters: Only parameters that should render on screen
        ecmlinkConnected: Whether ECMLink Phase 2 hardware is connected
        screenWidth: Screen width in pixels
        screenHeight: Screen height in pixels
    """

    overallStatus: OverallStatus = OverallStatus.GREEN
    parameters: list[ParameterDisplay] = field(default_factory=list)
    ecmlinkConnected: bool = False
    screenWidth: int = SCREEN_WIDTH
    screenHeight: int = SCREEN_HEIGHT

    @property
    def visibleParameters(self) -> list[ParameterDisplay]:
        """Parameters that should render (hides Phase 2 when ECMLink disconnected)."""
        return getVisibleParameters(self.parameters, self.ecmlinkConnected)


# ================================================================================
# Core Functions
# ================================================================================


def computeOverallStatus(severities: list[AlertSeverity]) -> OverallStatus:
    """
    Compute overall status from parameter severities using worst-status-wins.

    Args:
        severities: List of AlertSeverity values from all evaluated parameters

    Returns:
        OverallStatus: GREEN if all normal, YELLOW if any caution, RED if any danger
    """
    if not severities:
        return OverallStatus.GREEN

    worstOrder = max(_SEVERITY_TO_STATUS_ORDER.get(s, 0) for s in severities)

    if worstOrder >= 2:
        return OverallStatus.RED
    elif worstOrder >= 1:
        return OverallStatus.YELLOW
    return OverallStatus.GREEN


def getVisibleParameters(
    parameters: list[ParameterDisplay],
    ecmlinkConnected: bool,
) -> list[ParameterDisplay]:
    """
    Filter parameters based on Phase 2 hardware availability.

    Phase 2 elements (Boost, AFR) are hidden when ECMLink is not connected.
    The screen adapts its layout to show only available parameters.

    Args:
        parameters: All parameter display states
        ecmlinkConnected: Whether ECMLink hardware is connected

    Returns:
        List of parameters that should be rendered on screen
    """
    if ecmlinkConnected:
        return list(parameters)
    return [p for p in parameters if not p.isPhase2]


def _evaluateParameter(
    name: str,
    value: float,
    thresholdConfigs: dict[str, Any],
) -> TieredThresholdResult | None:
    """
    Evaluate a parameter value against its configured thresholds.

    Args:
        name: Parameter name (COOLANT_TEMP, RPM)
        value: Current parameter value
        thresholdConfigs: Threshold configurations from obd_config.json

    Returns:
        TieredThresholdResult or None if no threshold config exists
    """
    if name == "COOLANT_TEMP" and "coolantTemp" in thresholdConfigs:
        config = thresholdConfigs["coolantTemp"]
        thresholds = CoolantTempThresholds(
            normalMin=config["normalMin"],
            cautionMin=config["cautionMin"],
            dangerMin=config["dangerMin"],
        )
        return evaluateCoolantTemp(value, thresholds)

    if name == "RPM" and "rpm" in thresholdConfigs:
        config = thresholdConfigs["rpm"]
        thresholds = RPMThresholds(
            normalMin=config["normalMin"],
            cautionMin=config["cautionMin"],
            dangerMin=config["dangerMin"],
        )
        return evaluateRPM(value, thresholds)

    return None


def _buildParameterDisplay(
    name: str,
    value: float,
    thresholdResult: TieredThresholdResult | None,
) -> ParameterDisplay:
    """
    Build a ParameterDisplay from a reading and optional threshold evaluation.

    Args:
        name: Parameter name
        value: Current value
        thresholdResult: Threshold evaluation result, or None for Phase 2 params

    Returns:
        ParameterDisplay with severity and color information
    """
    config = _PARAMETER_CONFIG.get(name, {
        "label": name, "unit": "", "priority": "medium", "isPhase2": False,
    })

    if thresholdResult is not None:
        severity = thresholdResult.severity
        indicatorColor = thresholdResult.indicator
    else:
        severity = AlertSeverity.NORMAL
        indicatorColor = "green"

    return ParameterDisplay(
        name=name,
        label=config["label"],
        value=value,
        unit=config["unit"],
        severity=severity,
        indicatorColor=indicatorColor,
        isPhase2=config["isPhase2"],
        priority=config["priority"],
    )


def buildPrimaryScreenState(
    readings: dict[str, float],
    thresholdConfigs: dict[str, Any],
    ecmlinkConnected: bool = False,
) -> PrimaryScreenState:
    """
    Build complete primary screen state from current parameter readings.

    Evaluates all available parameters against their thresholds, computes
    the overall status indicator (worst-status-wins), and determines which
    Phase 2 elements should be visible.

    Args:
        readings: Current parameter values keyed by name (e.g., {"RPM": 2500.0})
        thresholdConfigs: Threshold configs from obd_config.json tieredThresholds
        ecmlinkConnected: Whether ECMLink Phase 2 hardware is connected

    Returns:
        PrimaryScreenState with all display information
    """
    parameters: list[ParameterDisplay] = []
    severities: list[AlertSeverity] = []

    displayOrder = ["COOLANT_TEMP", "RPM", "BOOST", "AFR"]

    for paramName in displayOrder:
        if paramName not in readings:
            continue

        value = readings[paramName]
        thresholdResult = _evaluateParameter(paramName, value, thresholdConfigs)
        paramDisplay = _buildParameterDisplay(paramName, value, thresholdResult)
        parameters.append(paramDisplay)
        severities.append(paramDisplay.severity)

    overallStatus = computeOverallStatus(severities)

    return PrimaryScreenState(
        overallStatus=overallStatus,
        parameters=parameters,
        ecmlinkConnected=ecmlinkConnected,
    )
