################################################################################
# File Name: test_touch_interactions.py
# Purpose/Description: Tests for Touch Interactions and Safety Constraints (US-127)
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
Tests for Touch Interactions and Safety Constraints (US-127).

Validates:
- Gesture recognition (tap, swipe left, swipe right, tap-and-hold)
- Safety constraint enforcement (speed > 0 blocks state-changing interactions)
- Page cycling order: Primary → Thermal → Fuel → Knock → Boost → System
- Phase 2 pages (Fuel, Knock, Boost) skipped when ECMLink not connected
- Alert detail display on tap
- Alert acknowledgement on tap-and-hold (parked only)
"""

from pi.display.screens.touch_interactions import (
    HOLD_DURATION_SECONDS,
    GestureType,
    InteractionResult,
    NavigationState,
    PageType,
    TouchInteractionHandler,
    buildAvailablePages,
)

# ================================================================================
# PageType Enum Tests
# ================================================================================


class TestPageType:
    """Tests for PageType enum values and ordering."""

    def test_pageType_hasSixValues(self):
        """
        Given: PageType enum
        When: checking values
        Then: contains all six page types
        """
        assert PageType.PRIMARY.value == "primary"
        assert PageType.THERMAL.value == "thermal"
        assert PageType.FUEL.value == "fuel"
        assert PageType.KNOCK.value == "knock"
        assert PageType.BOOST.value == "boost"
        assert PageType.SYSTEM.value == "system"

    def test_pageType_isPhase2_fuelKnockBoostArePhase2(self):
        """
        Given: all PageType values
        When: checking isPhase2 property
        Then: FUEL, KNOCK, BOOST are Phase 2; PRIMARY, THERMAL, SYSTEM are not
        """
        assert not PageType.PRIMARY.isPhase2
        assert not PageType.THERMAL.isPhase2
        assert PageType.FUEL.isPhase2
        assert PageType.KNOCK.isPhase2
        assert PageType.BOOST.isPhase2
        assert not PageType.SYSTEM.isPhase2


# ================================================================================
# GestureType Enum Tests
# ================================================================================


class TestGestureType:
    """Tests for GestureType enum values."""

    def test_gestureType_hasFourValues(self):
        """
        Given: GestureType enum
        When: checking values
        Then: contains TAP, SWIPE_LEFT, SWIPE_RIGHT, TAP_AND_HOLD
        """
        assert GestureType.TAP.value == "tap"
        assert GestureType.SWIPE_LEFT.value == "swipe_left"
        assert GestureType.SWIPE_RIGHT.value == "swipe_right"
        assert GestureType.TAP_AND_HOLD.value == "tap_and_hold"

    def test_gestureType_isStateChanging_onlyTapAndHold(self):
        """
        Given: all GestureType values
        When: checking isStateChanging property
        Then: only TAP_AND_HOLD is state-changing
        """
        assert not GestureType.TAP.isStateChanging
        assert not GestureType.SWIPE_LEFT.isStateChanging
        assert not GestureType.SWIPE_RIGHT.isStateChanging
        assert GestureType.TAP_AND_HOLD.isStateChanging


# ================================================================================
# InteractionResult Enum Tests
# ================================================================================


class TestInteractionResult:
    """Tests for InteractionResult enum values."""

    def test_interactionResult_hasFourValues(self):
        """
        Given: InteractionResult enum
        When: checking values
        Then: contains NAVIGATED, ALERT_SHOWN, ALERT_DISMISSED, BLOCKED_BY_SAFETY
        """
        assert InteractionResult.NAVIGATED.value == "navigated"
        assert InteractionResult.ALERT_SHOWN.value == "alert_shown"
        assert InteractionResult.ALERT_DISMISSED.value == "alert_dismissed"
        assert InteractionResult.BLOCKED_BY_SAFETY.value == "blocked_by_safety"


# ================================================================================
# buildAvailablePages Tests
# ================================================================================


class TestBuildAvailablePages:
    """Tests for buildAvailablePages function."""

    def test_buildAvailablePages_ecmlinkConnected_allSixPages(self):
        """
        Given: ECMLink is connected
        When: building available pages
        Then: returns all six pages in correct order
        """
        pages = buildAvailablePages(ecmlinkConnected=True)
        assert pages == [
            PageType.PRIMARY,
            PageType.THERMAL,
            PageType.FUEL,
            PageType.KNOCK,
            PageType.BOOST,
            PageType.SYSTEM,
        ]

    def test_buildAvailablePages_ecmlinkDisconnected_threePages(self):
        """
        Given: ECMLink is not connected
        When: building available pages
        Then: returns only non-Phase-2 pages (Primary, Thermal, System)
        """
        pages = buildAvailablePages(ecmlinkConnected=False)
        assert pages == [
            PageType.PRIMARY,
            PageType.THERMAL,
            PageType.SYSTEM,
        ]

    def test_buildAvailablePages_ecmlinkDisconnected_noPhase2Pages(self):
        """
        Given: ECMLink not connected
        When: building available pages
        Then: FUEL, KNOCK, BOOST are excluded
        """
        pages = buildAvailablePages(ecmlinkConnected=False)
        assert PageType.FUEL not in pages
        assert PageType.KNOCK not in pages
        assert PageType.BOOST not in pages

    def test_buildAvailablePages_orderMatchesSpec(self):
        """
        Given: ECMLink connected
        When: building available pages
        Then: order is Primary → Thermal → Fuel → Knock → Boost → System
        """
        pages = buildAvailablePages(ecmlinkConnected=True)
        assert pages[0] == PageType.PRIMARY
        assert pages[-1] == PageType.SYSTEM


# ================================================================================
# NavigationState Tests
# ================================================================================


class TestNavigationState:
    """Tests for NavigationState dataclass."""

    def test_navigationState_defaultsToStart(self):
        """
        Given: fresh NavigationState
        When: checking defaults
        Then: currentPage is PRIMARY, speed is 0, no active alert
        """
        state = NavigationState()
        assert state.currentPage == PageType.PRIMARY
        assert state.vehicleSpeedMph == 0.0
        assert state.ecmlinkConnected is False
        assert state.hasActiveAlert is False
        assert state.activeAlertIsCritical is False

    def test_navigationState_isMoving_speedZero_notMoving(self):
        """
        Given: vehicle speed is 0
        When: checking isMoving
        Then: returns False
        """
        state = NavigationState(vehicleSpeedMph=0.0)
        assert not state.isMoving

    def test_navigationState_isMoving_speedPositive_isMoving(self):
        """
        Given: vehicle speed > 0
        When: checking isMoving
        Then: returns True
        """
        state = NavigationState(vehicleSpeedMph=5.0)
        assert state.isMoving

    def test_navigationState_isMoving_speedOne_isMoving(self):
        """
        Given: vehicle speed is 1 mph
        When: checking isMoving
        Then: returns True (any speed > 0 means moving)
        """
        state = NavigationState(vehicleSpeedMph=1.0)
        assert state.isMoving


# ================================================================================
# TouchInteractionHandler — Page Cycling Tests
# ================================================================================


class TestPageCycling:
    """Tests for swipe-based page cycling through the handler."""

    def test_swipeRight_fromPrimary_goesToThermal(self):
        """
        Given: on Primary page, ECMLink connected
        When: swiping right
        Then: navigates to Thermal page
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY, ecmlinkConnected=True
        )
        result, newState = handler.processGesture(GestureType.SWIPE_RIGHT, state)
        assert result == InteractionResult.NAVIGATED
        assert newState.currentPage == PageType.THERMAL

    def test_swipeRight_fromSystem_wrapsToStart(self):
        """
        Given: on System page (last page), ECMLink connected
        When: swiping right
        Then: wraps around to Primary page
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.SYSTEM, ecmlinkConnected=True
        )
        result, newState = handler.processGesture(GestureType.SWIPE_RIGHT, state)
        assert result == InteractionResult.NAVIGATED
        assert newState.currentPage == PageType.PRIMARY

    def test_swipeLeft_fromPrimary_wrapsToEnd(self):
        """
        Given: on Primary page (first page), ECMLink connected
        When: swiping left
        Then: wraps around to System page
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY, ecmlinkConnected=True
        )
        result, newState = handler.processGesture(GestureType.SWIPE_LEFT, state)
        assert result == InteractionResult.NAVIGATED
        assert newState.currentPage == PageType.SYSTEM

    def test_swipeLeft_fromThermal_goesToPrimary(self):
        """
        Given: on Thermal page
        When: swiping left
        Then: navigates to Primary page
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.THERMAL, ecmlinkConnected=True
        )
        result, newState = handler.processGesture(GestureType.SWIPE_LEFT, state)
        assert result == InteractionResult.NAVIGATED
        assert newState.currentPage == PageType.PRIMARY

    def test_swipeRight_fullCycle_ecmlinkConnected(self):
        """
        Given: ECMLink connected, starting at Primary
        When: swiping right through all pages
        Then: visits all 6 pages in order and returns to Primary
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY, ecmlinkConnected=True
        )

        expectedOrder = [
            PageType.THERMAL,
            PageType.FUEL,
            PageType.KNOCK,
            PageType.BOOST,
            PageType.SYSTEM,
            PageType.PRIMARY,
        ]

        for expectedPage in expectedOrder:
            _, state = handler.processGesture(GestureType.SWIPE_RIGHT, state)
            assert state.currentPage == expectedPage

    def test_swipeRight_fullCycle_ecmlinkDisconnected(self):
        """
        Given: ECMLink disconnected, starting at Primary
        When: swiping right through all pages
        Then: skips Phase 2 pages (Fuel, Knock, Boost), visits 3 pages
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY, ecmlinkConnected=False
        )

        expectedOrder = [
            PageType.THERMAL,
            PageType.SYSTEM,
            PageType.PRIMARY,
        ]

        for expectedPage in expectedOrder:
            _, state = handler.processGesture(GestureType.SWIPE_RIGHT, state)
            assert state.currentPage == expectedPage

    def test_swipeLeft_fullCycle_ecmlinkDisconnected(self):
        """
        Given: ECMLink disconnected, starting at Primary
        When: swiping left through all pages
        Then: skips Phase 2 pages in reverse order
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY, ecmlinkConnected=False
        )

        expectedOrder = [
            PageType.SYSTEM,
            PageType.THERMAL,
            PageType.PRIMARY,
        ]

        for expectedPage in expectedOrder:
            _, state = handler.processGesture(GestureType.SWIPE_LEFT, state)
            assert state.currentPage == expectedPage

    def test_swipe_whileMoving_stillAllowed(self):
        """
        Given: vehicle is moving (speed > 0)
        When: swiping to navigate
        Then: navigation is allowed (read-only, not state-changing)
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY,
            vehicleSpeedMph=45.0,
            ecmlinkConnected=True,
        )
        result, newState = handler.processGesture(GestureType.SWIPE_RIGHT, state)
        assert result == InteractionResult.NAVIGATED
        assert newState.currentPage == PageType.THERMAL


# ================================================================================
# TouchInteractionHandler — Tap Tests
# ================================================================================


class TestTapInteraction:
    """Tests for tap gesture on status indicator."""

    def test_tap_withActiveAlert_showsAlertDetails(self):
        """
        Given: there is an active alert
        When: tapping
        Then: shows alert details
        """
        handler = TouchInteractionHandler()
        state = NavigationState(hasActiveAlert=True)
        result, _ = handler.processGesture(GestureType.TAP, state)
        assert result == InteractionResult.ALERT_SHOWN

    def test_tap_noActiveAlert_noEffect(self):
        """
        Given: no active alert
        When: tapping
        Then: result is NAVIGATED (no-op, stays on same page)
        """
        handler = TouchInteractionHandler()
        state = NavigationState(hasActiveAlert=False)
        result, newState = handler.processGesture(GestureType.TAP, state)
        assert result == InteractionResult.NAVIGATED
        assert newState.currentPage == state.currentPage

    def test_tap_whileMoving_withAlert_stillShowsDetails(self):
        """
        Given: vehicle is moving with an active alert
        When: tapping
        Then: shows alert details (tap is read-only, not state-changing)
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            vehicleSpeedMph=60.0, hasActiveAlert=True
        )
        result, _ = handler.processGesture(GestureType.TAP, state)
        assert result == InteractionResult.ALERT_SHOWN


# ================================================================================
# TouchInteractionHandler — Tap-and-Hold Tests
# ================================================================================


class TestTapAndHold:
    """Tests for tap-and-hold (3 sec) alert acknowledgement."""

    def test_tapAndHold_parked_nonCriticalAlert_dismissesAlert(self):
        """
        Given: vehicle is parked, non-critical alert active
        When: tap-and-hold for 3 seconds
        Then: alert is dismissed
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            vehicleSpeedMph=0.0,
            hasActiveAlert=True,
            activeAlertIsCritical=False,
        )
        result, newState = handler.processGesture(GestureType.TAP_AND_HOLD, state)
        assert result == InteractionResult.ALERT_DISMISSED
        assert not newState.hasActiveAlert

    def test_tapAndHold_parked_criticalAlert_blockedBySafety(self):
        """
        Given: vehicle is parked, CRITICAL alert active
        When: tap-and-hold
        Then: blocked — critical alerts cannot be dismissed
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            vehicleSpeedMph=0.0,
            hasActiveAlert=True,
            activeAlertIsCritical=True,
        )
        result, newState = handler.processGesture(GestureType.TAP_AND_HOLD, state)
        assert result == InteractionResult.BLOCKED_BY_SAFETY
        assert newState.hasActiveAlert is True

    def test_tapAndHold_moving_nonCriticalAlert_blockedBySafety(self):
        """
        Given: vehicle is moving, non-critical alert active
        When: tap-and-hold
        Then: blocked — state-changing interactions blocked while moving
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            vehicleSpeedMph=30.0,
            hasActiveAlert=True,
            activeAlertIsCritical=False,
        )
        result, newState = handler.processGesture(GestureType.TAP_AND_HOLD, state)
        assert result == InteractionResult.BLOCKED_BY_SAFETY
        assert newState.hasActiveAlert is True

    def test_tapAndHold_moving_criticalAlert_blockedBySafety(self):
        """
        Given: vehicle is moving, critical alert active
        When: tap-and-hold
        Then: blocked on two grounds — moving AND critical
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            vehicleSpeedMph=55.0,
            hasActiveAlert=True,
            activeAlertIsCritical=True,
        )
        result, newState = handler.processGesture(GestureType.TAP_AND_HOLD, state)
        assert result == InteractionResult.BLOCKED_BY_SAFETY
        assert newState.hasActiveAlert is True

    def test_tapAndHold_noActiveAlert_noEffect(self):
        """
        Given: no active alert
        When: tap-and-hold
        Then: no effect (nothing to dismiss)
        """
        handler = TouchInteractionHandler()
        state = NavigationState(hasActiveAlert=False)
        result, newState = handler.processGesture(GestureType.TAP_AND_HOLD, state)
        assert result == InteractionResult.NAVIGATED
        assert not newState.hasActiveAlert

    def test_holdDuration_isThreeSeconds(self):
        """
        Given: the HOLD_DURATION_SECONDS constant
        When: checking its value
        Then: it equals 3.0 seconds per spec
        """
        assert HOLD_DURATION_SECONDS == 3.0


# ================================================================================
# Safety Constraint Tests
# ================================================================================


class TestSafetyConstraints:
    """Tests for safety constraint enforcement."""

    def test_safety_movingVehicle_readOnlyAllowed(self):
        """
        Given: vehicle is moving
        When: performing read-only interactions (tap, swipe)
        Then: all are allowed
        """
        handler = TouchInteractionHandler()
        movingState = NavigationState(
            vehicleSpeedMph=65.0, ecmlinkConnected=True
        )

        tapResult, _ = handler.processGesture(GestureType.TAP, movingState)
        swipeRResult, _ = handler.processGesture(GestureType.SWIPE_RIGHT, movingState)
        swipeLResult, _ = handler.processGesture(GestureType.SWIPE_LEFT, movingState)

        assert tapResult == InteractionResult.NAVIGATED
        assert swipeRResult == InteractionResult.NAVIGATED
        assert swipeLResult == InteractionResult.NAVIGATED

    def test_safety_movingVehicle_stateChangingBlocked(self):
        """
        Given: vehicle is moving with non-critical alert
        When: attempting state-changing interaction (tap-and-hold)
        Then: blocked by safety constraint
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            vehicleSpeedMph=10.0,
            hasActiveAlert=True,
            activeAlertIsCritical=False,
        )
        result, _ = handler.processGesture(GestureType.TAP_AND_HOLD, state)
        assert result == InteractionResult.BLOCKED_BY_SAFETY

    def test_safety_parkedVehicle_allInteractionsAllowed(self):
        """
        Given: vehicle is parked (speed == 0)
        When: performing any interaction
        Then: all are allowed (except dismissing critical alerts)
        """
        handler = TouchInteractionHandler()
        parkedState = NavigationState(
            vehicleSpeedMph=0.0,
            ecmlinkConnected=True,
            hasActiveAlert=True,
            activeAlertIsCritical=False,
        )

        tapResult, _ = handler.processGesture(GestureType.TAP, parkedState)
        swipeResult, _ = handler.processGesture(GestureType.SWIPE_RIGHT, parkedState)
        holdResult, _ = handler.processGesture(GestureType.TAP_AND_HOLD, parkedState)

        assert tapResult == InteractionResult.ALERT_SHOWN
        assert swipeResult == InteractionResult.NAVIGATED
        assert holdResult == InteractionResult.ALERT_DISMISSED

    def test_safety_speedExactlyZero_isParked(self):
        """
        Given: speed is exactly 0.0
        When: checking if moving
        Then: not moving (parked)
        """
        state = NavigationState(vehicleSpeedMph=0.0)
        assert not state.isMoving

    def test_safety_veryLowSpeed_isStillMoving(self):
        """
        Given: speed is 0.1 mph (barely moving)
        When: checking if moving
        Then: is moving — any speed > 0 counts
        """
        state = NavigationState(vehicleSpeedMph=0.1)
        assert state.isMoving


# ================================================================================
# Phase 2 Page Skipping Tests
# ================================================================================


class TestPhase2PageSkipping:
    """Tests for Phase 2 page skipping during navigation."""

    def test_ecmlinkDisconnected_cannotNavigateToFuelPage(self):
        """
        Given: ECMLink disconnected
        When: navigating through all pages
        Then: never lands on Fuel page
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY, ecmlinkConnected=False
        )

        visitedPages = [state.currentPage]
        for _ in range(5):
            _, state = handler.processGesture(GestureType.SWIPE_RIGHT, state)
            visitedPages.append(state.currentPage)

        assert PageType.FUEL not in visitedPages

    def test_ecmlinkDisconnected_cannotNavigateToKnockPage(self):
        """
        Given: ECMLink disconnected
        When: navigating through all pages
        Then: never lands on Knock page
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY, ecmlinkConnected=False
        )

        visitedPages = [state.currentPage]
        for _ in range(5):
            _, state = handler.processGesture(GestureType.SWIPE_RIGHT, state)
            visitedPages.append(state.currentPage)

        assert PageType.KNOCK not in visitedPages

    def test_ecmlinkDisconnected_cannotNavigateToBoostPage(self):
        """
        Given: ECMLink disconnected
        When: navigating through all pages
        Then: never lands on Boost page
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY, ecmlinkConnected=False
        )

        visitedPages = [state.currentPage]
        for _ in range(5):
            _, state = handler.processGesture(GestureType.SWIPE_RIGHT, state)
            visitedPages.append(state.currentPage)

        assert PageType.BOOST not in visitedPages

    def test_ecmlinkConnected_canVisitAllPhase2Pages(self):
        """
        Given: ECMLink connected
        When: navigating through all pages
        Then: visits Fuel, Knock, and Boost pages
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY, ecmlinkConnected=True
        )

        visitedPages: set[PageType] = {state.currentPage}
        for _ in range(6):
            _, state = handler.processGesture(GestureType.SWIPE_RIGHT, state)
            visitedPages.add(state.currentPage)

        assert PageType.FUEL in visitedPages
        assert PageType.KNOCK in visitedPages
        assert PageType.BOOST in visitedPages

    def test_currentPageBecomesUnavailable_fallsBackToPrimary(self):
        """
        Given: currently on Fuel page with ECMLink connected
        When: ECMLink disconnects (page no longer available)
        Then: cycling from an unavailable page falls back to first available
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.FUEL, ecmlinkConnected=False
        )
        result, newState = handler.processGesture(GestureType.SWIPE_RIGHT, state)
        assert result == InteractionResult.NAVIGATED
        assert newState.currentPage in buildAvailablePages(False)


# ================================================================================
# Edge Case Tests
# ================================================================================


class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_processGesture_preservesOtherStateFields(self):
        """
        Given: state with specific vehicleSpeed and ecmlinkConnected
        When: processing a swipe gesture
        Then: vehicleSpeed and ecmlinkConnected are preserved in new state
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY,
            vehicleSpeedMph=42.5,
            ecmlinkConnected=True,
            hasActiveAlert=True,
            activeAlertIsCritical=False,
        )
        _, newState = handler.processGesture(GestureType.SWIPE_RIGHT, state)
        assert newState.vehicleSpeedMph == 42.5
        assert newState.ecmlinkConnected is True
        assert newState.hasActiveAlert is True

    def test_processGesture_doesNotMutateOriginalState(self):
        """
        Given: a navigation state
        When: processing a gesture
        Then: original state is not mutated (returns new state)
        """
        handler = TouchInteractionHandler()
        state = NavigationState(currentPage=PageType.PRIMARY, ecmlinkConnected=True)
        _, newState = handler.processGesture(GestureType.SWIPE_RIGHT, state)
        assert state.currentPage == PageType.PRIMARY
        assert newState.currentPage == PageType.THERMAL

    def test_rapidSwipes_cycleProperly(self):
        """
        Given: rapid succession of swipes
        When: processing 12 consecutive right swipes (2 full cycles)
        Then: ends back at Primary
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY, ecmlinkConnected=True
        )
        for _ in range(12):
            _, state = handler.processGesture(GestureType.SWIPE_RIGHT, state)
        assert state.currentPage == PageType.PRIMARY

    def test_alternatingSwipes_returnToSamePage(self):
        """
        Given: on Primary page
        When: swiping right then left
        Then: returns to Primary
        """
        handler = TouchInteractionHandler()
        state = NavigationState(
            currentPage=PageType.PRIMARY, ecmlinkConnected=True
        )
        _, state = handler.processGesture(GestureType.SWIPE_RIGHT, state)
        assert state.currentPage == PageType.THERMAL
        _, state = handler.processGesture(GestureType.SWIPE_LEFT, state)
        assert state.currentPage == PageType.PRIMARY
