################################################################################
# File Name: knock_detail.py
# Purpose/Description: Knock detail page state and per-drive tracking logic
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-124
# ================================================================================
################################################################################
"""
Knock monitoring detail page for the 3.5" touchscreen (480x320).

Phase 2 page — requires ECMLink connection. Shows:
- Knock count this drive
- Knock sum this drive (cumulative intensity)
- Last knock event details: RPM, load, timing at moment of knock

Hidden/unavailable when ECMLink not connected. Designed and stubbed now
so Phase 2 data flows in when hardware is installed.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ================================================================================
# Data Classes
# ================================================================================


@dataclass
class KnockEvent:
    """
    Engine state snapshot at the moment of a knock event.

    Attributes:
        rpm: Engine RPM at moment of knock
        loadPercent: Engine load percentage at moment of knock
        timingDegrees: Ignition timing in degrees at moment of knock
        knockIntensity: Knock intensity value from ECMLink
        timestamp: Event timestamp in seconds (monotonic)
    """

    rpm: float
    loadPercent: float
    timingDegrees: float
    knockIntensity: float
    timestamp: float

    @property
    def formattedRpm(self) -> str:
        """RPM as integer string."""
        return f"{round(self.rpm)}"

    @property
    def formattedLoad(self) -> str:
        """Load percentage with % sign."""
        return f"{self.loadPercent:g}%"

    @property
    def formattedTiming(self) -> str:
        """Timing degrees with degree symbol."""
        return f"{self.timingDegrees:g}\u00b0"


@dataclass
class KnockDetailState:
    """
    Complete display state for the knock detail page.

    Attributes:
        knockCount: Total knock events this drive
        knockSum: Cumulative knock intensity this drive
        lastEvent: Most recent knock event (None if no knocks)
        ecmlinkConnected: Whether ECMLink hardware is connected
        available: Whether this page should be shown (requires ECMLink)
        knockCountDisplay: Formatted knock count string
        knockSumDisplay: Formatted knock sum string
    """

    knockCount: int
    knockSum: float
    lastEvent: KnockEvent | None
    ecmlinkConnected: bool
    available: bool
    knockCountDisplay: str
    knockSumDisplay: str


# ================================================================================
# Stateful Tracker
# ================================================================================


class KnockTracker:
    """
    Stateful tracker for knock detail page data.

    Accumulates knock count and sum across a drive session, and retains
    the most recent knock event for display. Call resetDrive() when
    starting a new drive to clear per-drive counters.
    """

    def __init__(self) -> None:
        self._knockCount: int = 0
        self._knockSum: float = 0.0
        self._lastEvent: KnockEvent | None = None

    @property
    def knockCount(self) -> int:
        """Total knock events this drive."""
        return self._knockCount

    @property
    def knockSum(self) -> float:
        """Cumulative knock intensity this drive."""
        return self._knockSum

    @property
    def lastEvent(self) -> KnockEvent | None:
        """Most recent knock event, or None if no knocks."""
        return self._lastEvent

    def recordKnock(
        self,
        knockIntensity: float,
        rpm: float,
        loadPercent: float,
        timingDegrees: float,
        timestamp: float,
    ) -> None:
        """
        Record a knock event with engine state snapshot.

        Args:
            knockIntensity: Knock intensity value from ECMLink
            rpm: Engine RPM at moment of knock
            loadPercent: Engine load percentage at moment of knock
            timingDegrees: Ignition timing in degrees at moment of knock
            timestamp: Event timestamp in seconds (monotonic)
        """
        self._knockCount += 1
        self._knockSum += knockIntensity
        self._lastEvent = KnockEvent(
            rpm=rpm,
            loadPercent=loadPercent,
            timingDegrees=timingDegrees,
            knockIntensity=knockIntensity,
            timestamp=timestamp,
        )

    def resetDrive(self) -> None:
        """Reset all per-drive counters for a new drive session."""
        self._knockCount = 0
        self._knockSum = 0.0
        self._lastEvent = None

    def getState(self, ecmlinkConnected: bool) -> KnockDetailState:
        """
        Get current knock detail state snapshot for display rendering.

        Args:
            ecmlinkConnected: Whether ECMLink hardware is connected

        Returns:
            KnockDetailState with current values and availability
        """
        return buildKnockDetailState(
            knockCount=self._knockCount,
            knockSum=self._knockSum,
            lastEvent=self._lastEvent,
            ecmlinkConnected=ecmlinkConnected,
        )


# ================================================================================
# Builder Functions
# ================================================================================


def isKnockPageAvailable(ecmlinkConnected: bool) -> bool:
    """
    Check if the knock detail page should be shown.

    Args:
        ecmlinkConnected: Whether ECMLink hardware is connected

    Returns:
        True if ECMLink is connected, False otherwise
    """
    return ecmlinkConnected


def buildKnockDetailState(
    knockCount: int,
    knockSum: float,
    lastEvent: KnockEvent | None,
    ecmlinkConnected: bool,
) -> KnockDetailState:
    """
    Build the complete knock detail page state.

    Args:
        knockCount: Total knock events this drive
        knockSum: Cumulative knock intensity this drive
        lastEvent: Most recent knock event (None if no knocks)
        ecmlinkConnected: Whether ECMLink hardware is connected

    Returns:
        KnockDetailState with all knock display data
    """
    return KnockDetailState(
        knockCount=knockCount,
        knockSum=knockSum,
        lastEvent=lastEvent,
        ecmlinkConnected=ecmlinkConnected,
        available=isKnockPageAvailable(ecmlinkConnected),
        knockCountDisplay=str(knockCount),
        knockSumDisplay=f"{knockSum:g}",
    )
