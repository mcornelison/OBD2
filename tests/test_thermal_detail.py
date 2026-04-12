################################################################################
# File Name: test_thermal_detail.py
# Purpose/Description: Tests for Thermal Detail Page (US-122)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-122
# ================================================================================
################################################################################
"""
Tests for the Thermal Detail Page (US-122).

Validates:
- Trend arrow calculation (rising, falling, stable) from last 60 seconds
- Time-at-temperature accumulation (coolant > 200F threshold)
- Per-drive reset of time-at-temperature counter
- ThermalTracker state management and display output
"""

from display.screens.thermal_detail import (
    TEMP_AT_THRESHOLD_DEFAULT,
    TREND_FALLING_THRESHOLD,
    TREND_RISING_THRESHOLD,
    TREND_WINDOW_SECONDS,
    ThermalDetailState,
    ThermalTracker,
    TrendDirection,
    calculateTrend,
    computeTimeAtTemperature,
)

# ================================================================================
# TrendDirection Enum Tests
# ================================================================================


class TestTrendDirection:
    """Tests for TrendDirection enum values."""

    def test_trendDirection_hasThreeValues(self):
        """
        Given: TrendDirection enum
        When: checking values
        Then: contains RISING, FALLING, STABLE
        """
        assert TrendDirection.RISING.value == "rising"
        assert TrendDirection.FALLING.value == "falling"
        assert TrendDirection.STABLE.value == "stable"

    def test_trendDirection_arrowSymbols(self):
        """
        Given: each TrendDirection value
        When: getting arrow symbol
        Then: returns correct Unicode arrow
        """
        assert TrendDirection.RISING.arrow == "▲"
        assert TrendDirection.FALLING.arrow == "▼"
        assert TrendDirection.STABLE.arrow == "▶"


# ================================================================================
# calculateTrend Tests
# ================================================================================


class TestCalculateTrend:
    """Tests for trend calculation from temperature readings over time."""

    def test_calculateTrend_risingTemperature_returnsRising(self):
        """
        Given: coolant readings rising at ~2F/min over 60 seconds
        When: calculating trend
        Then: returns RISING (slope > +0.5F/min)
        """
        readings = [
            (0.0, 180.0),
            (15.0, 180.5),
            (30.0, 181.0),
            (45.0, 181.5),
            (60.0, 182.0),
        ]
        result = calculateTrend(readings)
        assert result == TrendDirection.RISING

    def test_calculateTrend_fallingTemperature_returnsFalling(self):
        """
        Given: coolant readings falling at ~2F/min over 60 seconds
        When: calculating trend
        Then: returns FALLING (slope < -0.5F/min)
        """
        readings = [
            (0.0, 200.0),
            (15.0, 199.5),
            (30.0, 199.0),
            (45.0, 198.5),
            (60.0, 198.0),
        ]
        result = calculateTrend(readings)
        assert result == TrendDirection.FALLING

    def test_calculateTrend_stableTemperature_returnsStable(self):
        """
        Given: coolant readings varying less than 0.5F/min
        When: calculating trend
        Then: returns STABLE
        """
        readings = [
            (0.0, 185.0),
            (15.0, 185.1),
            (30.0, 185.0),
            (45.0, 185.1),
            (60.0, 185.2),
        ]
        result = calculateTrend(readings)
        assert result == TrendDirection.STABLE

    def test_calculateTrend_exactlyAtRisingThreshold_returnsStable(self):
        """
        Given: slope exactly at +0.5F/min boundary
        When: calculating trend
        Then: returns STABLE (boundary semantics: > threshold, not >=)
        """
        # 0.5F over 60 seconds = 0.5F/min exactly
        readings = [
            (0.0, 185.0),
            (60.0, 185.5),
        ]
        result = calculateTrend(readings)
        assert result == TrendDirection.STABLE

    def test_calculateTrend_exactlyAtFallingThreshold_returnsStable(self):
        """
        Given: slope exactly at -0.5F/min boundary
        When: calculating trend
        Then: returns STABLE (boundary semantics: < threshold, not <=)
        """
        readings = [
            (0.0, 185.5),
            (60.0, 185.0),
        ]
        result = calculateTrend(readings)
        assert result == TrendDirection.STABLE

    def test_calculateTrend_justAboveRisingThreshold_returnsRising(self):
        """
        Given: slope just above +0.5F/min
        When: calculating trend
        Then: returns RISING
        """
        # 0.6F over 60 seconds = 0.6F/min > 0.5
        readings = [
            (0.0, 185.0),
            (60.0, 185.6),
        ]
        result = calculateTrend(readings)
        assert result == TrendDirection.RISING

    def test_calculateTrend_justBelowFallingThreshold_returnsFalling(self):
        """
        Given: slope just below -0.5F/min
        When: calculating trend
        Then: returns FALLING
        """
        readings = [
            (0.0, 185.6),
            (60.0, 185.0),
        ]
        result = calculateTrend(readings)
        assert result == TrendDirection.FALLING

    def test_calculateTrend_singleReading_returnsStable(self):
        """
        Given: only one reading (insufficient data for trend)
        When: calculating trend
        Then: returns STABLE (default)
        """
        readings = [(0.0, 185.0)]
        result = calculateTrend(readings)
        assert result == TrendDirection.STABLE

    def test_calculateTrend_emptyReadings_returnsStable(self):
        """
        Given: no readings
        When: calculating trend
        Then: returns STABLE (default)
        """
        result = calculateTrend([])
        assert result == TrendDirection.STABLE

    def test_calculateTrend_zeroTimeDelta_returnsStable(self):
        """
        Given: multiple readings at the same timestamp
        When: calculating trend
        Then: returns STABLE (avoids division by zero)
        """
        readings = [(10.0, 185.0), (10.0, 190.0)]
        result = calculateTrend(readings)
        assert result == TrendDirection.STABLE

    def test_calculateTrend_rapidRise_returnsRising(self):
        """
        Given: temperature jumping 10F in 30 seconds (20F/min)
        When: calculating trend
        Then: returns RISING
        """
        readings = [
            (0.0, 180.0),
            (30.0, 190.0),
        ]
        result = calculateTrend(readings)
        assert result == TrendDirection.RISING


# ================================================================================
# computeTimeAtTemperature Tests
# ================================================================================


class TestComputeTimeAtTemperature:
    """Tests for time-at-temperature accumulation."""

    def test_computeTimeAtTemp_aboveThreshold_accumulates(self):
        """
        Given: coolant at 205F (above 200F threshold), 10 seconds elapsed
        When: computing time-at-temperature
        Then: accumulates the time delta
        """
        result = computeTimeAtTemperature(
            currentTemp=205.0,
            threshold=200.0,
            previousAccumulated=30.0,
            timeDelta=10.0,
        )
        assert result == 40.0

    def test_computeTimeAtTemp_belowThreshold_noAccumulation(self):
        """
        Given: coolant at 195F (below 200F threshold), 10 seconds elapsed
        When: computing time-at-temperature
        Then: does not accumulate (returns previous value)
        """
        result = computeTimeAtTemperature(
            currentTemp=195.0,
            threshold=200.0,
            previousAccumulated=30.0,
            timeDelta=10.0,
        )
        assert result == 30.0

    def test_computeTimeAtTemp_exactlyAtThreshold_noAccumulation(self):
        """
        Given: coolant exactly at 200F threshold
        When: computing time-at-temperature
        Then: does NOT accumulate (must be ABOVE threshold)
        """
        result = computeTimeAtTemperature(
            currentTemp=200.0,
            threshold=200.0,
            previousAccumulated=30.0,
            timeDelta=10.0,
        )
        assert result == 30.0

    def test_computeTimeAtTemp_zeroPreviousAccumulated(self):
        """
        Given: no previous accumulation, coolant above threshold
        When: computing time-at-temperature
        Then: starts accumulating from zero
        """
        result = computeTimeAtTemperature(
            currentTemp=210.0,
            threshold=200.0,
            previousAccumulated=0.0,
            timeDelta=5.0,
        )
        assert result == 5.0

    def test_computeTimeAtTemp_negativeTimeDelta_treatedAsZero(self):
        """
        Given: negative time delta (clock anomaly)
        When: computing time-at-temperature
        Then: treats as zero (no negative accumulation)
        """
        result = computeTimeAtTemperature(
            currentTemp=210.0,
            threshold=200.0,
            previousAccumulated=30.0,
            timeDelta=-5.0,
        )
        assert result == 30.0


# ================================================================================
# ThermalTracker Tests
# ================================================================================


class TestThermalTracker:
    """Tests for the stateful ThermalTracker."""

    def test_thermalTracker_initialState_defaults(self):
        """
        Given: newly created ThermalTracker
        When: getting state
        Then: all values are defaults (0 temp, STABLE trend, 0 time-at-temp)
        """
        tracker = ThermalTracker()
        state = tracker.getState()
        assert state.coolantTemp == 0.0
        assert state.intakeAirTemp == 0.0
        assert state.trendDirection == TrendDirection.STABLE
        assert state.timeAtTempSeconds == 0.0

    def test_thermalTracker_addReading_updatesTemperatures(self):
        """
        Given: ThermalTracker
        When: adding a reading
        Then: current temperatures are updated
        """
        tracker = ThermalTracker()
        tracker.addReading(timestamp=10.0, coolantTemp=185.0, intakeAirTemp=72.0)
        state = tracker.getState()
        assert state.coolantTemp == 185.0
        assert state.intakeAirTemp == 72.0

    def test_thermalTracker_addReadings_trendRising(self):
        """
        Given: ThermalTracker with rising temperatures over 60 seconds
        When: getting state
        Then: trend is RISING
        """
        tracker = ThermalTracker()
        for i in range(7):
            t = i * 10.0
            temp = 180.0 + (i * 2.0)
            tracker.addReading(timestamp=t, coolantTemp=temp, intakeAirTemp=70.0)
        state = tracker.getState()
        assert state.trendDirection == TrendDirection.RISING

    def test_thermalTracker_addReadings_trendFalling(self):
        """
        Given: ThermalTracker with falling temperatures over 60 seconds
        When: getting state
        Then: trend is FALLING
        """
        tracker = ThermalTracker()
        for i in range(7):
            t = i * 10.0
            temp = 200.0 - (i * 2.0)
            tracker.addReading(timestamp=t, coolantTemp=temp, intakeAirTemp=70.0)
        state = tracker.getState()
        assert state.trendDirection == TrendDirection.FALLING

    def test_thermalTracker_addReadings_trendStable(self):
        """
        Given: ThermalTracker with stable temperatures
        When: getting state
        Then: trend is STABLE
        """
        tracker = ThermalTracker()
        for i in range(7):
            t = i * 10.0
            tracker.addReading(timestamp=t, coolantTemp=185.0, intakeAirTemp=70.0)
        state = tracker.getState()
        assert state.trendDirection == TrendDirection.STABLE

    def test_thermalTracker_timeAtTemp_accumulatesAboveThreshold(self):
        """
        Given: coolant readings above 200F over several seconds
        When: getting state
        Then: time-at-temp accumulates for each interval above threshold
        """
        tracker = ThermalTracker()
        tracker.addReading(timestamp=0.0, coolantTemp=195.0, intakeAirTemp=70.0)
        tracker.addReading(timestamp=10.0, coolantTemp=205.0, intakeAirTemp=70.0)
        tracker.addReading(timestamp=20.0, coolantTemp=210.0, intakeAirTemp=70.0)
        tracker.addReading(timestamp=30.0, coolantTemp=215.0, intakeAirTemp=70.0)
        state = tracker.getState()
        # t=0->10: 205>200, +10s; t=10->20: 210>200, +10s; t=20->30: 215>200, +10s
        assert state.timeAtTempSeconds == 30.0

    def test_thermalTracker_timeAtTemp_doesNotAccumulateBelowThreshold(self):
        """
        Given: coolant readings below 200F
        When: getting state
        Then: time-at-temp remains at zero
        """
        tracker = ThermalTracker()
        tracker.addReading(timestamp=0.0, coolantTemp=180.0, intakeAirTemp=70.0)
        tracker.addReading(timestamp=10.0, coolantTemp=190.0, intakeAirTemp=70.0)
        tracker.addReading(timestamp=20.0, coolantTemp=195.0, intakeAirTemp=70.0)
        state = tracker.getState()
        assert state.timeAtTempSeconds == 0.0

    def test_thermalTracker_timeAtTemp_mixedReadings(self):
        """
        Given: coolant readings oscillating around 200F threshold
        When: getting state
        Then: only accumulates time during intervals where temp > threshold
        """
        tracker = ThermalTracker()
        tracker.addReading(timestamp=0.0, coolantTemp=195.0, intakeAirTemp=70.0)
        tracker.addReading(timestamp=10.0, coolantTemp=205.0, intakeAirTemp=70.0)
        tracker.addReading(timestamp=20.0, coolantTemp=195.0, intakeAirTemp=70.0)
        tracker.addReading(timestamp=30.0, coolantTemp=210.0, intakeAirTemp=70.0)
        state = tracker.getState()
        # t=0->10: 205>200, +10s; t=10->20: 195<200, +0; t=20->30: 210>200, +10s
        assert state.timeAtTempSeconds == 20.0

    def test_thermalTracker_resetDrive_clearsTimeAtTemp(self):
        """
        Given: ThermalTracker with accumulated time-at-temperature
        When: resetting for new drive
        Then: time-at-temp resets to zero
        """
        tracker = ThermalTracker()
        tracker.addReading(timestamp=0.0, coolantTemp=210.0, intakeAirTemp=70.0)
        tracker.addReading(timestamp=10.0, coolantTemp=210.0, intakeAirTemp=70.0)
        assert tracker.getState().timeAtTempSeconds == 10.0

        tracker.resetDrive()
        state = tracker.getState()
        assert state.timeAtTempSeconds == 0.0

    def test_thermalTracker_resetDrive_clearsTrendBuffer(self):
        """
        Given: ThermalTracker with trend readings from previous drive
        When: resetting for new drive
        Then: trend resets to STABLE (no data from previous drive)
        """
        tracker = ThermalTracker()
        for i in range(7):
            t = i * 10.0
            temp = 180.0 + (i * 3.0)
            tracker.addReading(timestamp=t, coolantTemp=temp, intakeAirTemp=70.0)
        assert tracker.getState().trendDirection == TrendDirection.RISING

        tracker.resetDrive()
        assert tracker.getState().trendDirection == TrendDirection.STABLE

    def test_thermalTracker_resetDrive_clearsTemperatures(self):
        """
        Given: ThermalTracker with recorded temperatures
        When: resetting for new drive
        Then: temperatures reset to zero
        """
        tracker = ThermalTracker()
        tracker.addReading(timestamp=0.0, coolantTemp=185.0, intakeAirTemp=72.0)
        tracker.resetDrive()
        state = tracker.getState()
        assert state.coolantTemp == 0.0
        assert state.intakeAirTemp == 0.0

    def test_thermalTracker_windowPruning_dropsOldReadings(self):
        """
        Given: readings spanning more than 60 seconds
        When: adding new reading beyond the window
        Then: oldest readings are pruned from trend buffer
        """
        tracker = ThermalTracker()
        # Add readings over 120 seconds — first 60s should be pruned
        for i in range(13):
            t = i * 10.0
            tracker.addReading(timestamp=t, coolantTemp=185.0, intakeAirTemp=70.0)
        # Only readings from last 60s should remain in buffer
        assert len(tracker._readingBuffer) <= 7  # At most 7 readings in 60s window at 10s intervals

    def test_thermalTracker_customThreshold(self):
        """
        Given: ThermalTracker with custom time-at-temp threshold (210F)
        When: coolant between 200-210F
        Then: does not accumulate (below custom threshold)
        """
        tracker = ThermalTracker(tempAtThreshold=210.0)
        tracker.addReading(timestamp=0.0, coolantTemp=205.0, intakeAirTemp=70.0)
        tracker.addReading(timestamp=10.0, coolantTemp=208.0, intakeAirTemp=70.0)
        state = tracker.getState()
        assert state.timeAtTempSeconds == 0.0


# ================================================================================
# ThermalDetailState Tests
# ================================================================================


class TestThermalDetailState:
    """Tests for ThermalDetailState dataclass."""

    def test_thermalDetailState_allFields(self):
        """
        Given: ThermalDetailState with all fields populated
        When: inspecting state
        Then: all values are accessible
        """
        state = ThermalDetailState(
            coolantTemp=205.0,
            intakeAirTemp=85.0,
            trendDirection=TrendDirection.RISING,
            trendArrow="▲",
            timeAtTempSeconds=120.0,
            tempAtThreshold=200.0,
        )
        assert state.coolantTemp == 205.0
        assert state.intakeAirTemp == 85.0
        assert state.trendDirection == TrendDirection.RISING
        assert state.trendArrow == "▲"
        assert state.timeAtTempSeconds == 120.0
        assert state.tempAtThreshold == 200.0

    def test_thermalDetailState_formattedTimeAtTemp_seconds(self):
        """
        Given: time-at-temp under 60 seconds
        When: getting formatted string
        Then: shows seconds only
        """
        state = ThermalDetailState(
            coolantTemp=205.0,
            intakeAirTemp=85.0,
            trendDirection=TrendDirection.STABLE,
            trendArrow="▶",
            timeAtTempSeconds=45.0,
            tempAtThreshold=200.0,
        )
        assert state.formattedTimeAtTemp == "0:45"

    def test_thermalDetailState_formattedTimeAtTemp_minutesAndSeconds(self):
        """
        Given: time-at-temp of 3 minutes 30 seconds
        When: getting formatted string
        Then: shows M:SS format
        """
        state = ThermalDetailState(
            coolantTemp=205.0,
            intakeAirTemp=85.0,
            trendDirection=TrendDirection.STABLE,
            trendArrow="▶",
            timeAtTempSeconds=210.0,
            tempAtThreshold=200.0,
        )
        assert state.formattedTimeAtTemp == "3:30"

    def test_thermalDetailState_formattedTimeAtTemp_zero(self):
        """
        Given: zero time-at-temp
        When: getting formatted string
        Then: shows 0:00
        """
        state = ThermalDetailState(
            coolantTemp=185.0,
            intakeAirTemp=70.0,
            trendDirection=TrendDirection.STABLE,
            trendArrow="▶",
            timeAtTempSeconds=0.0,
            tempAtThreshold=200.0,
        )
        assert state.formattedTimeAtTemp == "0:00"

    def test_thermalDetailState_formattedTimeAtTemp_overOneHour(self):
        """
        Given: time-at-temp of 1 hour 5 minutes 30 seconds
        When: getting formatted string
        Then: shows total minutes (no hour rollover for simplicity)
        """
        state = ThermalDetailState(
            coolantTemp=205.0,
            intakeAirTemp=85.0,
            trendDirection=TrendDirection.STABLE,
            trendArrow="▶",
            timeAtTempSeconds=3930.0,
            tempAtThreshold=200.0,
        )
        assert state.formattedTimeAtTemp == "65:30"


# ================================================================================
# Constants Tests
# ================================================================================


class TestThermalConstants:
    """Tests for module-level constants."""

    def test_trendWindowSeconds_is60(self):
        """
        Given: TREND_WINDOW_SECONDS constant
        When: checking value
        Then: equals 60 (last 60 seconds of readings per spec)
        """
        assert TREND_WINDOW_SECONDS == 60.0

    def test_trendRisingThreshold_isHalf(self):
        """
        Given: TREND_RISING_THRESHOLD constant
        When: checking value
        Then: equals 0.5 F/min per spec
        """
        assert TREND_RISING_THRESHOLD == 0.5

    def test_trendFallingThreshold_isNegativeHalf(self):
        """
        Given: TREND_FALLING_THRESHOLD constant
        When: checking value
        Then: equals -0.5 F/min per spec
        """
        assert TREND_FALLING_THRESHOLD == -0.5

    def test_tempAtThresholdDefault_is200(self):
        """
        Given: TEMP_AT_THRESHOLD_DEFAULT constant
        When: checking value
        Then: equals 200.0 F per spec
        """
        assert TEMP_AT_THRESHOLD_DEFAULT == 200.0
