################################################################################
# File Name: touch_interactions.py
# Purpose/Description: Touch gesture handling and safety constraints for 480x320
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-127
# ================================================================================
################################################################################
"""
Touch interactions and safety constraints for the 3.5" touchscreen (480x320).

Gestures:
- Tap status indicator: show details of current alert
- Swipe left/right: cycle between detail pages
- Tap-and-hold (3 sec): acknowledge/dismiss non-critical alert

SAFETY CRITICAL:
- No interactions while vehicle speed > 0 that change system behavior
- Read-only while driving (page navigation only)
- Critical alerts cannot be dismissed even when parked

Page order: Primary → Thermal → Fuel → Knock → Boost → System
Phase 2 pages (Fuel, Knock, Boost) skipped when ECMLink not connected.
"""

import logging
from dataclasses import dataclass, replace
from enum import Enum

logger = logging.getLogger(__name__)

HOLD_DURATION_SECONDS: float = 3.0

PAGE_ORDER: list[str] = ["primary", "thermal", "fuel", "knock", "boost", "system"]


# ================================================================================
# Enums
# ================================================================================


class PageType(Enum):
    """
    Screen page identifiers in display order.

    PRIMARY: Main driving screen with status indicator
    THERMAL: Temperature trends and time-at-temperature
    FUEL: AFR, fuel trims, injector duty (Phase 2)
    KNOCK: Detonation events and context (Phase 2)
    BOOST: Boost pressure tracking (Phase 2)
    SYSTEM: Pi health, connectivity, drive stats
    """

    PRIMARY = "primary"
    THERMAL = "thermal"
    FUEL = "fuel"
    KNOCK = "knock"
    BOOST = "boost"
    SYSTEM = "system"

    @property
    def isPhase2(self) -> bool:
        """Whether this page requires ECMLink hardware."""
        return self.value in ("fuel", "knock", "boost")


class GestureType(Enum):
    """
    Touch gesture types recognized by the interaction handler.

    TAP: Single tap on status indicator — shows alert details (read-only)
    SWIPE_LEFT: Swipe left — navigate to previous page (read-only)
    SWIPE_RIGHT: Swipe right — navigate to next page (read-only)
    TAP_AND_HOLD: 3-second hold — acknowledge/dismiss alert (state-changing)
    """

    TAP = "tap"
    SWIPE_LEFT = "swipe_left"
    SWIPE_RIGHT = "swipe_right"
    TAP_AND_HOLD = "tap_and_hold"

    @property
    def isStateChanging(self) -> bool:
        """Whether this gesture changes system behavior (vs read-only navigation)."""
        return self == GestureType.TAP_AND_HOLD


class InteractionResult(Enum):
    """
    Result of processing a touch gesture.

    NAVIGATED: Page changed or no-op navigation (tap with no alert)
    ALERT_SHOWN: Alert details displayed
    ALERT_DISMISSED: Non-critical alert acknowledged and dismissed
    BLOCKED_BY_SAFETY: Interaction blocked by safety constraint
    """

    NAVIGATED = "navigated"
    ALERT_SHOWN = "alert_shown"
    ALERT_DISMISSED = "alert_dismissed"
    BLOCKED_BY_SAFETY = "blocked_by_safety"


# ================================================================================
# Data Classes
# ================================================================================


@dataclass(frozen=True)
class NavigationState:
    """
    Immutable state for the touch interaction system.

    Attributes:
        currentPage: Currently displayed page
        vehicleSpeedMph: Current vehicle speed from PID 0x0D
        ecmlinkConnected: Whether ECMLink Phase 2 hardware is connected
        hasActiveAlert: Whether there is a currently active alert
        activeAlertIsCritical: Whether the active alert is critical severity
    """

    currentPage: PageType = PageType.PRIMARY
    vehicleSpeedMph: float = 0.0
    ecmlinkConnected: bool = False
    hasActiveAlert: bool = False
    activeAlertIsCritical: bool = False

    @property
    def isMoving(self) -> bool:
        """Whether the vehicle is in motion (speed > 0)."""
        return self.vehicleSpeedMph > 0.0


# ================================================================================
# Core Functions
# ================================================================================


def buildAvailablePages(ecmlinkConnected: bool) -> list[PageType]:
    """
    Build the ordered list of available pages based on hardware state.

    Phase 2 pages (Fuel, Knock, Boost) are excluded when ECMLink is not
    connected. The order always follows the spec:
    Primary → Thermal → [Fuel → Knock → Boost →] System

    Args:
        ecmlinkConnected: Whether ECMLink hardware is connected

    Returns:
        Ordered list of available PageType values
    """
    allPages = [
        PageType.PRIMARY,
        PageType.THERMAL,
        PageType.FUEL,
        PageType.KNOCK,
        PageType.BOOST,
        PageType.SYSTEM,
    ]

    if ecmlinkConnected:
        return allPages
    return [p for p in allPages if not p.isPhase2]


def _cycleForward(
    currentPage: PageType,
    availablePages: list[PageType],
) -> PageType:
    """
    Cycle to the next page in the available pages list.

    Wraps from the last page back to the first. If the current page is not
    in the available list (e.g., ECMLink just disconnected), returns the
    first available page.

    Args:
        currentPage: Currently displayed page
        availablePages: Ordered list of available pages

    Returns:
        Next page in the cycle
    """
    if currentPage not in availablePages:
        return availablePages[0]
    currentIndex = availablePages.index(currentPage)
    nextIndex = (currentIndex + 1) % len(availablePages)
    return availablePages[nextIndex]


def _cycleBackward(
    currentPage: PageType,
    availablePages: list[PageType],
) -> PageType:
    """
    Cycle to the previous page in the available pages list.

    Wraps from the first page to the last. If the current page is not
    in the available list, returns the last available page.

    Args:
        currentPage: Currently displayed page
        availablePages: Ordered list of available pages

    Returns:
        Previous page in the cycle
    """
    if currentPage not in availablePages:
        return availablePages[-1]
    currentIndex = availablePages.index(currentPage)
    prevIndex = (currentIndex - 1) % len(availablePages)
    return availablePages[prevIndex]


# ================================================================================
# Interaction Handler
# ================================================================================


class TouchInteractionHandler:
    """
    Processes touch gestures with safety constraint enforcement.

    Safety rules:
    - Vehicle moving (speed > 0): only read-only interactions (navigation, view alerts)
    - Vehicle parked (speed == 0): all interactions allowed except dismissing critical alerts
    - Critical alerts can never be dismissed via touch (require explicit reset)
    """

    def processGesture(
        self,
        gesture: GestureType,
        state: NavigationState,
    ) -> tuple[InteractionResult, NavigationState]:
        """
        Process a touch gesture against the current navigation state.

        Enforces safety constraints before executing the gesture. Returns
        a new NavigationState — the original is never mutated.

        Args:
            gesture: The type of touch gesture detected
            state: Current navigation state (immutable)

        Returns:
            Tuple of (InteractionResult, new NavigationState)
        """
        if gesture == GestureType.SWIPE_RIGHT:
            return self._handleSwipe(state, forward=True)

        if gesture == GestureType.SWIPE_LEFT:
            return self._handleSwipe(state, forward=False)

        if gesture == GestureType.TAP:
            return self._handleTap(state)

        if gesture == GestureType.TAP_AND_HOLD:
            return self._handleTapAndHold(state)

        return (InteractionResult.NAVIGATED, state)

    def _handleSwipe(
        self,
        state: NavigationState,
        forward: bool,
    ) -> tuple[InteractionResult, NavigationState]:
        """Handle swipe left/right — always allowed (read-only navigation)."""
        availablePages = buildAvailablePages(state.ecmlinkConnected)

        if forward:
            nextPage = _cycleForward(state.currentPage, availablePages)
        else:
            nextPage = _cycleBackward(state.currentPage, availablePages)

        newState = replace(state, currentPage=nextPage)
        return (InteractionResult.NAVIGATED, newState)

    def _handleTap(
        self,
        state: NavigationState,
    ) -> tuple[InteractionResult, NavigationState]:
        """Handle tap — shows alert details if alert active (read-only)."""
        if state.hasActiveAlert:
            return (InteractionResult.ALERT_SHOWN, state)
        return (InteractionResult.NAVIGATED, state)

    def _handleTapAndHold(
        self,
        state: NavigationState,
    ) -> tuple[InteractionResult, NavigationState]:
        """Handle tap-and-hold — dismiss non-critical alert if parked."""
        if not state.hasActiveAlert:
            return (InteractionResult.NAVIGATED, state)

        if state.isMoving:
            logger.warning(
                "Blocked alert dismissal: vehicle moving at %.1f mph",
                state.vehicleSpeedMph,
            )
            return (InteractionResult.BLOCKED_BY_SAFETY, state)

        if state.activeAlertIsCritical:
            logger.warning("Blocked alert dismissal: alert is critical severity")
            return (InteractionResult.BLOCKED_BY_SAFETY, state)

        newState = replace(state, hasActiveAlert=False, activeAlertIsCritical=False)
        return (InteractionResult.ALERT_DISMISSED, newState)
