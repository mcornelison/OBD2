################################################################################
# File Name: fuel_detail.py
# Purpose/Description: Fuel detail page state and threshold evaluation logic
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-123
# 2026-04-12    | Ralph Agent  | US-143: Fix stub default INJECTOR_CAUTION 80→75
# ================================================================================
################################################################################
"""
Fuel system detail page for the 3.5" touchscreen (480x320).

Phase 2 page — requires ECMLink connection. Shows:
- AFR actual vs target (deviation-based severity)
- STFT / LTFT values (bidirectional threshold coloring)
- Injector duty cycle (with color at threshold boundaries)
- Ethanol content % (from flex fuel sensor, informational)

Hidden/unavailable when ECMLink not connected. Threshold defaults are
configurable stubs — B-029 will supply tuning-specific thresholds when
hardware is installed.
"""

import logging
from dataclasses import dataclass

from alert.tiered_thresholds import AlertSeverity

logger = logging.getLogger(__name__)

AFR_CAUTION_DEVIATION_DEFAULT: float = 0.5
AFR_DANGER_DEVIATION_DEFAULT: float = 1.0
INJECTOR_CAUTION_DEFAULT: float = 75.0
INJECTOR_DANGER_DEFAULT: float = 85.0

FUEL_TRIM_CAUTION_ABS: float = 5.0
FUEL_TRIM_DANGER_ABS: float = 15.0


# ================================================================================
# Threshold Configuration
# ================================================================================


@dataclass
class AFRThresholds:
    """
    AFR deviation thresholds for severity evaluation.

    Severity is based on absolute deviation from target AFR, not absolute
    AFR value — because target varies by operating condition (14.7 at idle,
    ~11.5 under boost).

    Attributes:
        cautionDeviation: Absolute deviation triggering caution (e.g., 0.5)
        dangerDeviation: Absolute deviation triggering danger (e.g., 1.0)
    """

    cautionDeviation: float = AFR_CAUTION_DEVIATION_DEFAULT
    dangerDeviation: float = AFR_DANGER_DEVIATION_DEFAULT


@dataclass
class InjectorDutyThresholds:
    """
    Injector duty cycle thresholds for severity evaluation.

    High duty cycle means injectors are near max capacity — risk of running
    lean at high RPM if duty exceeds 85%.

    Attributes:
        cautionMin: Duty cycle % triggering caution (e.g., 80)
        dangerMin: Duty cycle % triggering danger (e.g., 85)
    """

    cautionMin: float = INJECTOR_CAUTION_DEFAULT
    dangerMin: float = INJECTOR_DANGER_DEFAULT


# ================================================================================
# Data Classes
# ================================================================================


@dataclass
class AFRInfo:
    """
    AFR display information.

    Attributes:
        actual: Current measured AFR
        target: Target AFR for current operating condition
        deviation: actual - target (positive = lean, negative = rich)
        severity: Threshold evaluation severity
        indicatorColor: Color string for display (green/yellow/red)
        displayText: Formatted string like '14.7 / 14.7'
    """

    actual: float
    target: float
    deviation: float
    severity: AlertSeverity
    indicatorColor: str
    displayText: str


@dataclass
class FuelTrimInfo:
    """
    Fuel trim display information (used for both STFT and LTFT).

    Attributes:
        value: Fuel trim percentage (positive = lean correction, negative = rich)
        label: Parameter label ('STFT' or 'LTFT')
        severity: Threshold evaluation severity
        indicatorColor: Color string for display
        displayText: Formatted string like '+3.5%'
    """

    value: float
    label: str
    severity: AlertSeverity
    indicatorColor: str
    displayText: str


@dataclass
class InjectorDutyInfo:
    """
    Injector duty cycle display information.

    Attributes:
        dutyCyclePercent: Current injector duty cycle 0-100%
        severity: Threshold evaluation severity
        indicatorColor: Color string for display
        displayText: Formatted string like '65%'
    """

    dutyCyclePercent: float
    severity: AlertSeverity
    indicatorColor: str
    displayText: str


@dataclass
class FuelDetailState:
    """
    Complete display state for the fuel detail page.

    Attributes:
        afrInfo: AFR actual vs target display data
        stftInfo: Short-term fuel trim display data
        ltftInfo: Long-term fuel trim display data
        injectorDutyInfo: Injector duty cycle display data
        ethanolContentPercent: Ethanol content from flex fuel sensor (0-100)
        ethanolDisplayText: Formatted ethanol percentage string
        ecmlinkConnected: Whether ECMLink hardware is connected
        available: Whether this page should be shown (requires ECMLink)
    """

    afrInfo: AFRInfo
    stftInfo: FuelTrimInfo
    ltftInfo: FuelTrimInfo
    injectorDutyInfo: InjectorDutyInfo
    ethanolContentPercent: float
    ethanolDisplayText: str
    ecmlinkConnected: bool
    available: bool


# ================================================================================
# Evaluation Functions
# ================================================================================


def evaluateAFRDeviation(
    actual: float,
    target: float,
    thresholds: AFRThresholds,
) -> tuple[AlertSeverity, str]:
    """
    Evaluate AFR severity based on deviation from target.

    Uses absolute deviation for threshold comparison. Boundary semantics:
    strictly greater than threshold triggers the higher severity level
    (value == boundary stays in lower level).

    Args:
        actual: Measured AFR value
        target: Target AFR for current operating condition
        thresholds: AFR threshold configuration

    Returns:
        Tuple of (AlertSeverity, indicator color string)
    """
    absDeviation = abs(actual - target)

    if absDeviation > thresholds.dangerDeviation:
        return AlertSeverity.DANGER, "red"
    if absDeviation > thresholds.cautionDeviation:
        return AlertSeverity.CAUTION, "yellow"
    return AlertSeverity.NORMAL, "green"


def evaluateInjectorDuty(
    dutyCycle: float,
    thresholds: InjectorDutyThresholds,
) -> tuple[AlertSeverity, str]:
    """
    Evaluate injector duty cycle severity.

    Boundary semantics: strictly greater than threshold triggers the higher
    severity level (value == boundary stays in lower level).

    Args:
        dutyCycle: Current injector duty cycle percentage (0-100)
        thresholds: Injector duty threshold configuration

    Returns:
        Tuple of (AlertSeverity, indicator color string)
    """
    if dutyCycle > thresholds.dangerMin:
        return AlertSeverity.DANGER, "red"
    if dutyCycle > thresholds.cautionMin:
        return AlertSeverity.CAUTION, "yellow"
    return AlertSeverity.NORMAL, "green"


def _evaluateFuelTrim(value: float) -> tuple[AlertSeverity, str]:
    """
    Evaluate fuel trim severity using bidirectional thresholds.

    STFT and LTFT share the same bidirectional logic: positive = lean
    correction, negative = rich correction. Uses abs(value) for threshold
    comparison.

    Args:
        value: Fuel trim percentage

    Returns:
        Tuple of (AlertSeverity, indicator color string)
    """
    absValue = abs(value)

    if absValue >= FUEL_TRIM_DANGER_ABS:
        return AlertSeverity.DANGER, "red"
    if absValue >= FUEL_TRIM_CAUTION_ABS:
        return AlertSeverity.CAUTION, "yellow"
    return AlertSeverity.NORMAL, "green"


# ================================================================================
# Builder Functions
# ================================================================================


def buildAFRInfo(
    actual: float,
    target: float,
    thresholds: AFRThresholds,
) -> AFRInfo:
    """
    Build AFR display info from current reading and target.

    Args:
        actual: Measured AFR value
        target: Target AFR for current operating condition
        thresholds: AFR threshold configuration

    Returns:
        AFRInfo with deviation, severity, and formatted display text
    """
    deviation = actual - target
    severity, color = evaluateAFRDeviation(actual, target, thresholds)
    displayText = f"{actual:g} / {target:g}"

    return AFRInfo(
        actual=actual,
        target=target,
        deviation=deviation,
        severity=severity,
        indicatorColor=color,
        displayText=displayText,
    )


def buildFuelTrimInfo(value: float, label: str) -> FuelTrimInfo:
    """
    Build fuel trim display info for STFT or LTFT.

    Args:
        value: Fuel trim percentage
        label: Parameter label ('STFT' or 'LTFT')

    Returns:
        FuelTrimInfo with severity and formatted display text
    """
    severity, color = _evaluateFuelTrim(value)
    sign = "+" if value >= 0 else ""
    displayText = f"{sign}{value:g}%"

    return FuelTrimInfo(
        value=value,
        label=label,
        severity=severity,
        indicatorColor=color,
        displayText=displayText,
    )


def buildInjectorDutyInfo(
    dutyCycle: float,
    thresholds: InjectorDutyThresholds,
) -> InjectorDutyInfo:
    """
    Build injector duty cycle display info.

    Args:
        dutyCycle: Current injector duty cycle percentage (0-100)
        thresholds: Injector duty threshold configuration

    Returns:
        InjectorDutyInfo with severity and formatted display text
    """
    severity, color = evaluateInjectorDuty(dutyCycle, thresholds)
    displayText = f"{dutyCycle:g}%"

    return InjectorDutyInfo(
        dutyCyclePercent=dutyCycle,
        severity=severity,
        indicatorColor=color,
        displayText=displayText,
    )


def isFuelPageAvailable(ecmlinkConnected: bool) -> bool:
    """
    Check if the fuel detail page should be shown.

    Args:
        ecmlinkConnected: Whether ECMLink hardware is connected

    Returns:
        True if ECMLink is connected, False otherwise
    """
    return ecmlinkConnected


def buildFuelDetailState(
    afrActual: float,
    afrTarget: float,
    stft: float,
    ltft: float,
    injectorDutyCycle: float,
    ethanolContent: float,
    ecmlinkConnected: bool,
    afrThresholds: AFRThresholds | None = None,
    injectorThresholds: InjectorDutyThresholds | None = None,
) -> FuelDetailState:
    """
    Build the complete fuel detail page state.

    Aggregates AFR, fuel trim, injector duty, and ethanol content into
    a single display state. Each parameter is independently evaluated
    against its thresholds for color coding.

    Args:
        afrActual: Measured AFR value
        afrTarget: Target AFR for current operating condition
        stft: Short-term fuel trim percentage
        ltft: Long-term fuel trim percentage
        injectorDutyCycle: Injector duty cycle percentage (0-100)
        ethanolContent: Ethanol content percentage from flex fuel sensor
        ecmlinkConnected: Whether ECMLink hardware is connected
        afrThresholds: Optional custom AFR thresholds (defaults used if None)
        injectorThresholds: Optional custom injector thresholds (defaults if None)

    Returns:
        FuelDetailState with all fuel parameter display data
    """
    resolvedAFRThresholds = afrThresholds if afrThresholds is not None else AFRThresholds()
    resolvedInjectorThresholds = (
        injectorThresholds if injectorThresholds is not None else InjectorDutyThresholds()
    )

    afrInfo = buildAFRInfo(afrActual, afrTarget, resolvedAFRThresholds)
    stftInfo = buildFuelTrimInfo(stft, "STFT")
    ltftInfo = buildFuelTrimInfo(ltft, "LTFT")
    injectorDutyInfo = buildInjectorDutyInfo(injectorDutyCycle, resolvedInjectorThresholds)
    ethanolDisplayText = f"{ethanolContent:g}%"
    available = isFuelPageAvailable(ecmlinkConnected)

    return FuelDetailState(
        afrInfo=afrInfo,
        stftInfo=stftInfo,
        ltftInfo=ltftInfo,
        injectorDutyInfo=injectorDutyInfo,
        ethanolContentPercent=ethanolContent,
        ethanolDisplayText=ethanolDisplayText,
        ecmlinkConnected=ecmlinkConnected,
        available=available,
    )
