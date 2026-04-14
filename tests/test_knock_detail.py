################################################################################
# File Name: test_knock_detail.py
# Purpose/Description: Tests for Knock Detail Page (US-124)
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
Tests for the Knock Detail Page (US-124).

Validates:
- KnockEvent data capture (RPM, load, timing at moment of knock)
- KnockTracker per-drive accumulation (count, sum)
- KnockTracker per-drive reset
- Last knock event updates in real-time
- KnockDetailState construction with mock ECMLink data
- Page hidden when ECMLink not connected
"""

from pi.display.screens.knock_detail import (
    KnockEvent,
    KnockTracker,
    buildKnockDetailState,
    isKnockPageAvailable,
)

# ================================================================================
# KnockEvent Tests
# ================================================================================


class TestKnockEvent:
    """Tests for KnockEvent data capture."""

    def test_knockEvent_capturesEngineSnapshot(self):
        """
        Given: Engine state at moment of knock
        When: creating KnockEvent
        Then: stores RPM, load, timing, and knock intensity
        """
        event = KnockEvent(
            rpm=5500.0,
            loadPercent=85.0,
            timingDegrees=12.0,
            knockIntensity=3.5,
            timestamp=1000.0,
        )

        assert event.rpm == 5500.0
        assert event.loadPercent == 85.0
        assert event.timingDegrees == 12.0
        assert event.knockIntensity == 3.5
        assert event.timestamp == 1000.0

    def test_knockEvent_formattedRpm(self):
        """
        Given: KnockEvent with RPM value
        When: getting formatted display text
        Then: returns integer-formatted RPM string
        """
        event = KnockEvent(
            rpm=5500.0, loadPercent=85.0, timingDegrees=12.0,
            knockIntensity=3.5, timestamp=1000.0,
        )
        assert event.formattedRpm == "5500"

    def test_knockEvent_formattedRpm_fractional(self):
        """
        Given: KnockEvent with fractional RPM
        When: getting formatted display text
        Then: rounds to nearest integer
        """
        event = KnockEvent(
            rpm=3247.6, loadPercent=50.0, timingDegrees=15.0,
            knockIntensity=1.0, timestamp=500.0,
        )
        assert event.formattedRpm == "3248"

    def test_knockEvent_formattedLoad(self):
        """
        Given: KnockEvent with load percentage
        When: getting formatted display text
        Then: returns load with percent sign
        """
        event = KnockEvent(
            rpm=5500.0, loadPercent=85.0, timingDegrees=12.0,
            knockIntensity=3.5, timestamp=1000.0,
        )
        assert event.formattedLoad == "85%"

    def test_knockEvent_formattedLoad_fractional(self):
        """
        Given: KnockEvent with fractional load
        When: getting formatted display text
        Then: returns load with one decimal and percent sign
        """
        event = KnockEvent(
            rpm=4000.0, loadPercent=72.5, timingDegrees=14.0,
            knockIntensity=2.0, timestamp=800.0,
        )
        assert event.formattedLoad == "72.5%"

    def test_knockEvent_formattedTiming(self):
        """
        Given: KnockEvent with timing degrees
        When: getting formatted display text
        Then: returns timing with degree symbol
        """
        event = KnockEvent(
            rpm=5500.0, loadPercent=85.0, timingDegrees=12.0,
            knockIntensity=3.5, timestamp=1000.0,
        )
        assert event.formattedTiming == "12°"

    def test_knockEvent_formattedTiming_negative(self):
        """
        Given: KnockEvent with negative timing (retarded)
        When: getting formatted display text
        Then: returns negative timing with degree symbol
        """
        event = KnockEvent(
            rpm=6000.0, loadPercent=90.0, timingDegrees=-5.0,
            knockIntensity=8.0, timestamp=1200.0,
        )
        assert event.formattedTiming == "-5°"

    def test_knockEvent_formattedTiming_fractional(self):
        """
        Given: KnockEvent with fractional timing
        When: getting formatted display text
        Then: returns timing with decimal and degree symbol
        """
        event = KnockEvent(
            rpm=4500.0, loadPercent=70.0, timingDegrees=10.5,
            knockIntensity=2.5, timestamp=900.0,
        )
        assert event.formattedTiming == "10.5°"


# ================================================================================
# KnockTracker Tests
# ================================================================================


class TestKnockTracker:
    """Tests for KnockTracker per-drive accumulation."""

    def test_knockTracker_initialState_zeroCounts(self):
        """
        Given: Fresh KnockTracker
        When: checking initial state
        Then: knock count and sum are zero, no last event
        """
        tracker = KnockTracker()

        assert tracker.knockCount == 0
        assert tracker.knockSum == 0.0
        assert tracker.lastEvent is None

    def test_knockTracker_recordKnock_incrementsCount(self):
        """
        Given: KnockTracker with no events
        When: recording a knock event
        Then: knock count becomes 1
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=3.5, rpm=5500.0, loadPercent=85.0,
            timingDegrees=12.0, timestamp=1000.0,
        )

        assert tracker.knockCount == 1

    def test_knockTracker_recordKnock_accumulatesSum(self):
        """
        Given: KnockTracker with no events
        When: recording a knock with intensity 3.5
        Then: knock sum becomes 3.5
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=3.5, rpm=5500.0, loadPercent=85.0,
            timingDegrees=12.0, timestamp=1000.0,
        )

        assert tracker.knockSum == 3.5

    def test_knockTracker_recordKnock_capturesLastEvent(self):
        """
        Given: KnockTracker with no events
        When: recording a knock event
        Then: lastEvent contains engine snapshot at moment of knock
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=3.5, rpm=5500.0, loadPercent=85.0,
            timingDegrees=12.0, timestamp=1000.0,
        )

        event = tracker.lastEvent
        assert event is not None
        assert event.rpm == 5500.0
        assert event.loadPercent == 85.0
        assert event.timingDegrees == 12.0
        assert event.knockIntensity == 3.5
        assert event.timestamp == 1000.0

    def test_knockTracker_multipleKnocks_accumulates(self):
        """
        Given: KnockTracker
        When: recording multiple knock events
        Then: count and sum accumulate correctly
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=3.5, rpm=5500.0, loadPercent=85.0,
            timingDegrees=12.0, timestamp=1000.0,
        )
        tracker.recordKnock(
            knockIntensity=2.0, rpm=4800.0, loadPercent=75.0,
            timingDegrees=14.0, timestamp=1005.0,
        )
        tracker.recordKnock(
            knockIntensity=5.5, rpm=6000.0, loadPercent=90.0,
            timingDegrees=10.0, timestamp=1010.0,
        )

        assert tracker.knockCount == 3
        assert tracker.knockSum == 11.0

    def test_knockTracker_multipleKnocks_lastEventIsNewest(self):
        """
        Given: KnockTracker with multiple events
        When: checking last event
        Then: last event is the most recently recorded
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=3.5, rpm=5500.0, loadPercent=85.0,
            timingDegrees=12.0, timestamp=1000.0,
        )
        tracker.recordKnock(
            knockIntensity=5.5, rpm=6000.0, loadPercent=90.0,
            timingDegrees=10.0, timestamp=1010.0,
        )

        event = tracker.lastEvent
        assert event is not None
        assert event.rpm == 6000.0
        assert event.knockIntensity == 5.5
        assert event.timestamp == 1010.0

    def test_knockTracker_resetDrive_clearsCounts(self):
        """
        Given: KnockTracker with accumulated data
        When: resetDrive called
        Then: count and sum reset to zero
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=3.5, rpm=5500.0, loadPercent=85.0,
            timingDegrees=12.0, timestamp=1000.0,
        )
        tracker.recordKnock(
            knockIntensity=2.0, rpm=4800.0, loadPercent=75.0,
            timingDegrees=14.0, timestamp=1005.0,
        )

        tracker.resetDrive()

        assert tracker.knockCount == 0
        assert tracker.knockSum == 0.0

    def test_knockTracker_resetDrive_clearsLastEvent(self):
        """
        Given: KnockTracker with last event
        When: resetDrive called
        Then: lastEvent is None
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=3.5, rpm=5500.0, loadPercent=85.0,
            timingDegrees=12.0, timestamp=1000.0,
        )

        tracker.resetDrive()

        assert tracker.lastEvent is None

    def test_knockTracker_resetDrive_allowsNewAccumulation(self):
        """
        Given: KnockTracker after resetDrive
        When: recording new knock events
        Then: accumulates from zero fresh
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=10.0, rpm=5500.0, loadPercent=85.0,
            timingDegrees=12.0, timestamp=1000.0,
        )

        tracker.resetDrive()

        tracker.recordKnock(
            knockIntensity=2.5, rpm=3000.0, loadPercent=50.0,
            timingDegrees=18.0, timestamp=2000.0,
        )

        assert tracker.knockCount == 1
        assert tracker.knockSum == 2.5
        assert tracker.lastEvent is not None
        assert tracker.lastEvent.rpm == 3000.0

    def test_knockTracker_zeroIntensityKnock_stillCounts(self):
        """
        Given: KnockTracker
        When: recording a knock with zero intensity
        Then: still increments count (ECMLink reported an event)
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=0.0, rpm=4000.0, loadPercent=60.0,
            timingDegrees=16.0, timestamp=1000.0,
        )

        assert tracker.knockCount == 1
        assert tracker.knockSum == 0.0


# ================================================================================
# KnockTracker.getState Tests
# ================================================================================


class TestKnockTrackerGetState:
    """Tests for KnockTracker.getState producing KnockDetailState."""

    def test_getState_noKnocks_ecmlinkConnected(self):
        """
        Given: Fresh tracker, ECMLink connected
        When: getting state
        Then: returns available state with zero counts and no last event
        """
        tracker = KnockTracker()
        state = tracker.getState(ecmlinkConnected=True)

        assert state.knockCount == 0
        assert state.knockSum == 0.0
        assert state.lastEvent is None
        assert state.ecmlinkConnected is True
        assert state.available is True

    def test_getState_withKnocks_displaysAccumulated(self):
        """
        Given: Tracker with recorded knocks
        When: getting state
        Then: state reflects accumulated count and sum
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=3.5, rpm=5500.0, loadPercent=85.0,
            timingDegrees=12.0, timestamp=1000.0,
        )
        tracker.recordKnock(
            knockIntensity=2.0, rpm=4800.0, loadPercent=75.0,
            timingDegrees=14.0, timestamp=1005.0,
        )

        state = tracker.getState(ecmlinkConnected=True)

        assert state.knockCount == 2
        assert state.knockSum == 5.5
        assert state.lastEvent is not None
        assert state.lastEvent.rpm == 4800.0

    def test_getState_ecmlinkDisconnected_notAvailable(self):
        """
        Given: Tracker with data, ECMLink disconnected
        When: getting state
        Then: available is False
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=3.5, rpm=5500.0, loadPercent=85.0,
            timingDegrees=12.0, timestamp=1000.0,
        )

        state = tracker.getState(ecmlinkConnected=False)

        assert state.available is False
        assert state.ecmlinkConnected is False

    def test_getState_formattedKnockCount(self):
        """
        Given: Tracker with 5 knocks
        When: getting state
        Then: knockCountDisplay shows integer count
        """
        tracker = KnockTracker()
        for i in range(5):
            tracker.recordKnock(
                knockIntensity=1.0, rpm=4000.0 + i * 100,
                loadPercent=70.0, timingDegrees=15.0,
                timestamp=1000.0 + i * 5.0,
            )

        state = tracker.getState(ecmlinkConnected=True)

        assert state.knockCountDisplay == "5"

    def test_getState_formattedKnockSum(self):
        """
        Given: Tracker with accumulated knock sum
        When: getting state
        Then: knockSumDisplay shows formatted sum
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=3.5, rpm=5500.0, loadPercent=85.0,
            timingDegrees=12.0, timestamp=1000.0,
        )
        tracker.recordKnock(
            knockIntensity=2.5, rpm=4800.0, loadPercent=75.0,
            timingDegrees=14.0, timestamp=1005.0,
        )

        state = tracker.getState(ecmlinkConnected=True)

        assert state.knockSumDisplay == "6"

    def test_getState_formattedKnockSum_fractional(self):
        """
        Given: Tracker with fractional knock sum
        When: getting state
        Then: knockSumDisplay preserves meaningful decimal
        """
        tracker = KnockTracker()
        tracker.recordKnock(
            knockIntensity=1.5, rpm=4000.0, loadPercent=60.0,
            timingDegrees=16.0, timestamp=1000.0,
        )

        state = tracker.getState(ecmlinkConnected=True)

        assert state.knockSumDisplay == "1.5"

    def test_getState_noKnocks_displayZeros(self):
        """
        Given: Fresh tracker
        When: getting state
        Then: display texts show zero values
        """
        tracker = KnockTracker()
        state = tracker.getState(ecmlinkConnected=True)

        assert state.knockCountDisplay == "0"
        assert state.knockSumDisplay == "0"


# ================================================================================
# isKnockPageAvailable Tests
# ================================================================================


class TestIsKnockPageAvailable:
    """Tests for knock page availability gating on ECMLink."""

    def test_isKnockPageAvailable_ecmlinkConnected_returnsTrue(self):
        """
        Given: ECMLink is connected
        When: checking availability
        Then: returns True
        """
        assert isKnockPageAvailable(ecmlinkConnected=True) is True

    def test_isKnockPageAvailable_ecmlinkDisconnected_returnsFalse(self):
        """
        Given: ECMLink is not connected
        When: checking availability
        Then: returns False
        """
        assert isKnockPageAvailable(ecmlinkConnected=False) is False


# ================================================================================
# buildKnockDetailState Tests
# ================================================================================


class TestBuildKnockDetailState:
    """Tests for building KnockDetailState from raw values."""

    def test_buildKnockDetailState_withKnockEvent(self):
        """
        Given: Mock ECMLink data with a knock event
        When: building state
        Then: all fields populated correctly
        """
        lastEvent = KnockEvent(
            rpm=5500.0, loadPercent=85.0, timingDegrees=12.0,
            knockIntensity=3.5, timestamp=1000.0,
        )

        state = buildKnockDetailState(
            knockCount=3,
            knockSum=8.5,
            lastEvent=lastEvent,
            ecmlinkConnected=True,
        )

        assert state.knockCount == 3
        assert state.knockSum == 8.5
        assert state.lastEvent is lastEvent
        assert state.ecmlinkConnected is True
        assert state.available is True
        assert state.knockCountDisplay == "3"
        assert state.knockSumDisplay == "8.5"

    def test_buildKnockDetailState_noKnockEvent(self):
        """
        Given: ECMLink connected, no knock events yet
        When: building state
        Then: state has zero counts and no last event
        """
        state = buildKnockDetailState(
            knockCount=0,
            knockSum=0.0,
            lastEvent=None,
            ecmlinkConnected=True,
        )

        assert state.knockCount == 0
        assert state.knockSum == 0.0
        assert state.lastEvent is None
        assert state.available is True
        assert state.knockCountDisplay == "0"
        assert state.knockSumDisplay == "0"

    def test_buildKnockDetailState_ecmlinkDisconnected(self):
        """
        Given: ECMLink not connected
        When: building state
        Then: page not available
        """
        state = buildKnockDetailState(
            knockCount=0,
            knockSum=0.0,
            lastEvent=None,
            ecmlinkConnected=False,
        )

        assert state.ecmlinkConnected is False
        assert state.available is False

    def test_buildKnockDetailState_highKnockCount(self):
        """
        Given: Many knock events accumulated
        When: building state
        Then: large count displayed correctly
        """
        state = buildKnockDetailState(
            knockCount=42,
            knockSum=156.5,
            lastEvent=None,
            ecmlinkConnected=True,
        )

        assert state.knockCountDisplay == "42"
        assert state.knockSumDisplay == "156.5"

    def test_buildKnockDetailState_integerSum(self):
        """
        Given: Knock sum is a whole number
        When: building state
        Then: displayed without decimal
        """
        state = buildKnockDetailState(
            knockCount=10,
            knockSum=25.0,
            lastEvent=None,
            ecmlinkConnected=True,
        )

        assert state.knockSumDisplay == "25"
