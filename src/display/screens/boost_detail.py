################################################################################
# File Name: boost_detail.py
# Purpose/Description: Boost detail page state, peak tracking, and threshold
#                      evaluation logic
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-125
# 2026-04-12    | Ralph Agent  | US-143: Fix stub defaults CAUTION 18→14, DANGER 22→15
# ================================================================================
################################################################################
"""
Boost monitoring detail page for the 3.5" touchscreen (480x320).

Phase 2 page — requires ECMLink connection with MAP sensor. Shows:
- Current boost pressure
- Target boost pressure
- Peak boost this drive

Hidden/unavailable when ECMLink not connected. Threshold defaults are
configurable stubs — B-029 will supply tuning-specific thresholds when
hardware is installed.
"""

import logging
from dataclasses import dataclass

from alert.tiered_thresholds import AlertSeverity

logger = logging.getLogger(__name__)

# Stock TD04-13G turbo values. Will be finalized in B-029 Phase 2.
BOOST_CAUTION_DEFAULT: float = 14.0
BOOST_DANGER_DEFAULT: float = 15.0


# ================================================================================
# Threshold Configuration
# ================================================================================


@dataclass
class BoostThresholds:
    """
    Boost pressure thresholds for severity evaluation.

    Overboost is a safety concern on a 4G63 turbo — wastegate failure
    can send boost to destructive levels. Defaults are conservative
    for a stock TD04-13G turbo; B-029 will supply tuning-specific values.

    Attributes:
        cautionMin: Boost psi triggering caution (e.g., 14.0)
        dangerMin: Boost psi triggering danger / overboost (e.g., 15.0)
    """

    cautionMin: float = BOOST_CAUTION_DEFAULT
    dangerMin: float = BOOST_DANGER_DEFAULT


# ================================================================================
# Data Classes
# ================================================================================


@dataclass
class BoostDetailState:
    """
    Complete display state for the boost detail page.

    Attributes:
        currentBoost: Current boost pressure in psi
        targetBoost: Target boost pressure in psi
        peakBoost: Peak boost this drive in psi
        severity: Threshold evaluation severity for current boost
        indicatorColor: Color string for display (green/yellow/red)
        currentBoostDisplay: Formatted current boost string (e.g., '12.5 psi')
        targetBoostDisplay: Formatted target boost string
        peakBoostDisplay: Formatted peak boost string
        ecmlinkConnected: Whether ECMLink hardware is connected
        available: Whether this page should be shown (requires ECMLink)
    """

    currentBoost: float
    targetBoost: float
    peakBoost: float
    severity: AlertSeverity
    indicatorColor: str
    currentBoostDisplay: str
    targetBoostDisplay: str
    peakBoostDisplay: str
    ecmlinkConnected: bool
    available: bool


# ================================================================================
# Stateful Tracker
# ================================================================================


class BoostTracker:
    """
    Stateful tracker for boost detail page data.

    Tracks peak boost across a drive session. Call resetDrive() when
    starting a new drive to clear the per-drive peak. Only positive
    boost values update the peak — vacuum readings at idle are ignored.
    """

    def __init__(self) -> None:
        self._peakBoost: float = 0.0

    @property
    def peakBoost(self) -> float:
        """Peak boost pressure this drive in psi."""
        return self._peakBoost

    def updateBoost(self, currentBoost: float) -> None:
        """
        Update peak tracking with a new boost reading.

        Only updates peak if the reading exceeds the current peak
        and is positive (vacuum/negative readings are ignored).

        Args:
            currentBoost: Current boost pressure reading in psi
        """
        if currentBoost > self._peakBoost:
            self._peakBoost = currentBoost

    def resetDrive(self) -> None:
        """Reset per-drive peak for a new drive session."""
        self._peakBoost = 0.0

    def getState(
        self,
        currentBoost: float,
        targetBoost: float,
        ecmlinkConnected: bool,
        boostThresholds: BoostThresholds | None = None,
    ) -> BoostDetailState:
        """
        Get current boost detail state snapshot for display rendering.

        Args:
            currentBoost: Current boost pressure in psi
            targetBoost: Target boost pressure in psi
            ecmlinkConnected: Whether ECMLink hardware is connected
            boostThresholds: Optional custom thresholds (defaults if None)

        Returns:
            BoostDetailState with current values and availability
        """
        return buildBoostDetailState(
            currentBoost=currentBoost,
            targetBoost=targetBoost,
            peakBoost=self._peakBoost,
            ecmlinkConnected=ecmlinkConnected,
            boostThresholds=boostThresholds,
        )


# ================================================================================
# Evaluation Functions
# ================================================================================


def evaluateBoost(
    boostPsi: float,
    thresholds: BoostThresholds,
) -> tuple[AlertSeverity, str]:
    """
    Evaluate boost pressure severity.

    Boundary semantics: strictly greater than threshold triggers the higher
    severity level (value == boundary stays in lower level).

    Args:
        boostPsi: Current boost pressure in psi
        thresholds: Boost threshold configuration

    Returns:
        Tuple of (AlertSeverity, indicator color string)
    """
    if boostPsi > thresholds.dangerMin:
        return AlertSeverity.DANGER, "red"
    if boostPsi > thresholds.cautionMin:
        return AlertSeverity.CAUTION, "yellow"
    return AlertSeverity.NORMAL, "green"


# ================================================================================
# Builder Functions
# ================================================================================


def isBoostPageAvailable(ecmlinkConnected: bool) -> bool:
    """
    Check if the boost detail page should be shown.

    Args:
        ecmlinkConnected: Whether ECMLink hardware is connected

    Returns:
        True if ECMLink is connected, False otherwise
    """
    return ecmlinkConnected


def buildBoostDetailState(
    currentBoost: float,
    targetBoost: float,
    peakBoost: float,
    ecmlinkConnected: bool,
    boostThresholds: BoostThresholds | None = None,
) -> BoostDetailState:
    """
    Build the complete boost detail page state.

    Evaluates current boost against thresholds for color coding and
    formats all values for display rendering.

    Args:
        currentBoost: Current boost pressure in psi
        targetBoost: Target boost pressure in psi
        peakBoost: Peak boost this drive in psi
        ecmlinkConnected: Whether ECMLink hardware is connected
        boostThresholds: Optional custom thresholds (defaults if None)

    Returns:
        BoostDetailState with all boost display data
    """
    resolvedThresholds = boostThresholds if boostThresholds is not None else BoostThresholds()
    severity, color = evaluateBoost(currentBoost, resolvedThresholds)
    available = isBoostPageAvailable(ecmlinkConnected)

    return BoostDetailState(
        currentBoost=currentBoost,
        targetBoost=targetBoost,
        peakBoost=peakBoost,
        severity=severity,
        indicatorColor=color,
        currentBoostDisplay=f"{currentBoost:g} psi",
        targetBoostDisplay=f"{targetBoost:g} psi",
        peakBoostDisplay=f"{peakBoost:g} psi",
        ecmlinkConnected=ecmlinkConnected,
        available=available,
    )
