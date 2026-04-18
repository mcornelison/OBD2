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
# 2026-04-17    | Ralph Agent  | US-164: basic-tier 6-param state + layout helpers
# ================================================================================
################################################################################
"""
Primary driving screen for the 3.5" touchscreen (480x320).

The driver is DRIVING — information must be glanceable in under 1 second.
This module manages the screen state: parameter evaluations, overall status
indicator (worst-status-wins), and Phase 2 element visibility.

Two entry points:

1. ``buildPrimaryScreenState`` — original Phase-1/Phase-2 aware state used by
   the legacy primary-screen flow. Hides ``isPhase2`` parameters when ECMLink
   is not connected.

2. ``buildBasicTierScreenState`` — Sprint 10 crawl-tier basic primary screen
   (US-164). Shows the 6 parameters Spool Gate 1 confirmed (RPM, Coolant,
   Boost, AFR, Speed, Battery Voltage) regardless of ECMLink state, plus a
   header and footer. Pairs with ``computeBasicTierLayout`` which returns a
   pure list of ``LayoutElement``s that a pygame renderer can draw.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pi.alert.tiered_thresholds import (
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
    "SPEED": {"label": "Speed", "unit": "mph", "priority": "large", "isPhase2": False},
    "BATTERY_VOLTAGE": {
        "label": "Volts", "unit": "V", "priority": "large", "isPhase2": False,
    },
}

# US-164: Spool Gate 1 confirmed parameter order for the basic-tier primary
# screen (offices/pm/inbox/2026-04-16-from-spool-gate1-primary-screen.md).
BASIC_TIER_DISPLAY_ORDER: tuple[str, ...] = (
    "RPM",
    "COOLANT_TEMP",
    "BOOST",
    "AFR",
    "SPEED",
    "BATTERY_VOLTAGE",
)


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


# ================================================================================
# US-164 Basic Tier (Sprint 10 Pi Crawl) — header, footer, layout
# ================================================================================


@dataclass
class ScreenHeader:
    """Header strip on the primary screen.

    Attributes:
        hostname: Device short name shown top-left (default: Eclipse-01)
        obdConnected: True -> green center dot, False -> red
        profileIndicator: Single-letter profile tag (default 'D' for daily)
    """

    hostname: str = "Eclipse-01"
    obdConnected: bool = False
    profileIndicator: str = "D"


@dataclass
class ScreenFooter:
    """Footer strip on the primary screen.

    Attributes:
        alertMessages: Zero or more active alert messages (first one shown)
        batterySocPercent: Battery state-of-charge as 0-100, or None if unknown
        powerSource: 'ac_power', 'battery', or 'unknown'
    """

    alertMessages: list[str] = field(default_factory=list)
    batterySocPercent: float | None = None
    powerSource: str = "unknown"


@dataclass
class BasicTierScreenState:
    """Composite screen state for the basic (crawl) primary screen.

    Bundles the legacy ``PrimaryScreenState`` body with a ``ScreenHeader``
    and ``ScreenFooter``. The renderer consumes this through
    ``computeBasicTierLayout``.
    """

    header: ScreenHeader
    body: PrimaryScreenState
    footer: ScreenFooter


@dataclass
class LayoutElement:
    """One drawable element in a layout plan.

    Pure-data representation of a text/circle/rect primitive with a region
    tag so tests can filter by area. A pygame renderer walks the list and
    calls the matching primitive.
    """

    kind: str  # 'text', 'circle', 'rect'
    region: str  # 'header', 'body', 'footer'
    text: str = ""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    radius: int = 0
    fontSize: str = "normal"  # 'small', 'normal', 'medium', 'large', 'xlarge'
    color: str = "white"


def _evaluateBasicTierParameter(
    name: str,
    value: float,
    thresholdConfigs: dict[str, Any],
) -> TieredThresholdResult | None:
    """Evaluate a parameter for the basic tier.

    Reuses the legacy evaluator for coolant/rpm, returns None for SPEED (no
    threshold defined) and BATTERY_VOLTAGE (bidirectional threshold — crawl
    does not colour-code it; that is Walk-phase Gate 2 work).
    """
    if name in ("COOLANT_TEMP", "RPM"):
        return _evaluateParameter(name, value, thresholdConfigs)
    return None


def buildBasicTierScreenState(
    readings: dict[str, float],
    thresholdConfigs: dict[str, Any],
    header: ScreenHeader | None = None,
    footer: ScreenFooter | None = None,
) -> BasicTierScreenState:
    """Build the composite basic-tier primary-screen state.

    Unlike ``buildPrimaryScreenState`` this does not hide BOOST/AFR based
    on ECMLink presence — crawl shows what is in ``readings``. The body's
    ``overallStatus`` is still computed with worst-status-wins.

    Args:
        readings: Parameter values keyed by name. Missing keys are skipped.
        thresholdConfigs: ``tieredThresholds`` section from obd_config.json.
        header: Optional header state; defaults to Eclipse-01/disconnected/D.
        footer: Optional footer state; defaults to empty.

    Returns:
        BasicTierScreenState ready for ``computeBasicTierLayout``.
    """
    parameters: list[ParameterDisplay] = []
    severities: list[AlertSeverity] = []

    for paramName in BASIC_TIER_DISPLAY_ORDER:
        if paramName not in readings:
            continue
        value = readings[paramName]
        thresholdResult = _evaluateBasicTierParameter(
            paramName, value, thresholdConfigs
        )
        paramDisplay = _buildParameterDisplay(paramName, value, thresholdResult)
        parameters.append(paramDisplay)
        severities.append(paramDisplay.severity)

    body = PrimaryScreenState(
        overallStatus=computeOverallStatus(severities),
        parameters=parameters,
        ecmlinkConnected=False,
    )

    return BasicTierScreenState(
        header=header if header is not None else ScreenHeader(),
        body=body,
        footer=footer if footer is not None else ScreenFooter(),
    )


# ---- Layout geometry (480x320 OSOYOO 3.5" HDMI)

HEADER_HEIGHT = 50
FOOTER_HEIGHT = 50
BODY_TOP = HEADER_HEIGHT + 10
BODY_GRID_COLS = 3
BODY_GRID_ROWS = 2
BODY_CELL_W = 480 // BODY_GRID_COLS  # 160
BODY_CELL_H = 100
HEADER_PADDING_X = 10
FOOTER_PADDING_X = 10

_PLACEHOLDER_VALUE = "---"


def _formatValue(paramName: str, value: float) -> str:
    """Format a numeric parameter value for the display.

    RPM and SPEED are integer gauges; everything else keeps one decimal.
    """
    if paramName in ("RPM", "SPEED"):
        return str(int(round(value)))
    return f"{value:.1f}"


def _bodyCellOrigin(index: int) -> tuple[int, int]:
    """Return (x, y) for the top-left of the grid cell at ``index``."""
    row = index // BODY_GRID_COLS
    col = index % BODY_GRID_COLS
    x = col * BODY_CELL_W
    y = BODY_TOP + row * BODY_CELL_H
    return x, y


def _severityToColor(severity: AlertSeverity) -> str:
    """Map AlertSeverity to a high-contrast text color for the dark theme."""
    if severity == AlertSeverity.DANGER:
        return "red"
    if severity == AlertSeverity.CAUTION:
        return "yellow"
    return "white"


def computeBasicTierLayout(
    state: BasicTierScreenState,
    width: int = 480,
    height: int = 320,
) -> list[LayoutElement]:
    """Produce a pure list of ``LayoutElement`` for a basic-tier screen.

    Output is deterministic and tests can filter by region (header/body/footer)
    and kind (text/circle/rect). No pygame dependency.
    """
    elements: list[LayoutElement] = []

    # ---- Header ----------------------------------------------------------
    elements.append(
        LayoutElement(
            kind="text",
            region="header",
            text=state.header.hostname,
            x=HEADER_PADDING_X,
            y=14,
            fontSize="medium",
            color="white",
        )
    )
    dotColor = "green" if state.header.obdConnected else "red"
    elements.append(
        LayoutElement(
            kind="circle",
            region="header",
            x=width // 2,
            y=HEADER_HEIGHT // 2,
            radius=12,
            color=dotColor,
        )
    )
    elements.append(
        LayoutElement(
            kind="text",
            region="header",
            text=f"[{state.header.profileIndicator}]",
            x=width - 50,
            y=14,
            fontSize="medium",
            color="white",
        )
    )
    # Header/body separator
    elements.append(
        LayoutElement(
            kind="rect",
            region="header",
            x=0,
            y=HEADER_HEIGHT,
            width=width,
            height=2,
            color="gray",
        )
    )

    # ---- Body grid: 6 cells (3 cols x 2 rows) ----------------------------
    readingsByName = {p.name: p for p in state.body.parameters}
    for index, paramName in enumerate(BASIC_TIER_DISPLAY_ORDER):
        cellX, cellY = _bodyCellOrigin(index)
        config = _PARAMETER_CONFIG[paramName]
        label = config["label"]
        unit = config["unit"]

        # Label line (smaller, top of cell)
        elements.append(
            LayoutElement(
                kind="text",
                region="body",
                text=label,
                x=cellX + 10,
                y=cellY + 8,
                fontSize="normal",
                color="white",
            )
        )

        if paramName in readingsByName:
            param = readingsByName[paramName]
            valueStr = _formatValue(paramName, param.value)
            colorName = _severityToColor(param.severity)
        else:
            valueStr = _PLACEHOLDER_VALUE
            colorName = "gray"

        # Value line (large, middle of cell)
        elements.append(
            LayoutElement(
                kind="text",
                region="body",
                text=valueStr,
                x=cellX + 10,
                y=cellY + 36,
                fontSize="large",
                color=colorName,
            )
        )

        # Unit line (small, bottom of cell), only when we have a unit string
        if unit:
            elements.append(
                LayoutElement(
                    kind="text",
                    region="body",
                    text=unit,
                    x=cellX + 10,
                    y=cellY + 78,
                    fontSize="small",
                    color="white",
                )
            )

    # ---- Footer ----------------------------------------------------------
    footerY = height - FOOTER_HEIGHT
    elements.append(
        LayoutElement(
            kind="rect",
            region="footer",
            x=0,
            y=footerY - 2,
            width=width,
            height=2,
            color="gray",
        )
    )

    if state.footer.alertMessages:
        elements.append(
            LayoutElement(
                kind="text",
                region="footer",
                text=state.footer.alertMessages[0],
                x=FOOTER_PADDING_X,
                y=footerY + 14,
                fontSize="normal",
                color="yellow",
            )
        )

    if state.footer.batterySocPercent is not None:
        socInt = int(round(state.footer.batterySocPercent))
        socColor = "red" if socInt < 25 else ("yellow" if socInt < 50 else "white")
        elements.append(
            LayoutElement(
                kind="text",
                region="footer",
                text=f"Bat: {socInt}%",
                x=width // 2 - 40,
                y=footerY + 14,
                fontSize="normal",
                color=socColor,
            )
        )

    powerLabel = _powerSourceLabel(state.footer.powerSource)
    if powerLabel:
        elements.append(
            LayoutElement(
                kind="text",
                region="footer",
                text=powerLabel,
                x=width - 60,
                y=footerY + 14,
                fontSize="normal",
                color="white",
            )
        )

    return elements


def _powerSourceLabel(source: str) -> str:
    """Human-readable power-source label for the footer."""
    if source == "ac_power":
        return "AC"
    if source == "battery":
        return "BATT"
    return ""
