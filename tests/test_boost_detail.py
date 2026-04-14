################################################################################
# File Name: test_boost_detail.py
# Purpose/Description: Tests for Boost Detail Page (US-125)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-125
# 2026-04-12    | Ralph Agent  | US-143: Update defaults BOOST_CAUTION 18→14, BOOST_DANGER 22→15
# ================================================================================
################################################################################
"""
Tests for the Boost Detail Page (US-125).

Validates:
- BoostThresholds configurable defaults and custom values
- evaluateBoost severity evaluation at threshold boundaries
- BoostTracker peak tracking across multiple readings
- BoostTracker per-drive reset
- BoostDetailState construction with mock ECMLink data
- Page hidden when ECMLink not connected
- Display text formatting for boost values
"""

from pi.alert.tiered_thresholds import AlertSeverity
from pi.display.screens.boost_detail import (
    BOOST_CAUTION_DEFAULT,
    BOOST_DANGER_DEFAULT,
    BoostThresholds,
    BoostTracker,
    buildBoostDetailState,
    evaluateBoost,
    isBoostPageAvailable,
)

# ================================================================================
# BoostThresholds Tests
# ================================================================================


class TestBoostThresholds:
    """Tests for BoostThresholds configuration."""

    def test_boostThresholds_defaultValues(self):
        """
        Given: No custom thresholds
        When: creating BoostThresholds with defaults
        Then: uses module-level default constants
        """
        thresholds = BoostThresholds()

        assert thresholds.cautionMin == BOOST_CAUTION_DEFAULT
        assert thresholds.dangerMin == BOOST_DANGER_DEFAULT

    def test_boostThresholds_customValues(self):
        """
        Given: Custom threshold values
        When: creating BoostThresholds with overrides
        Then: uses the custom values
        """
        thresholds = BoostThresholds(cautionMin=20.0, dangerMin=25.0)

        assert thresholds.cautionMin == 20.0
        assert thresholds.dangerMin == 25.0


# ================================================================================
# evaluateBoost Tests
# ================================================================================


class TestEvaluateBoost:
    """Tests for boost pressure severity evaluation."""

    def test_evaluateBoost_normalRange_returnsNormal(self):
        """
        Given: Boost pressure within normal range (below caution)
        When: evaluating severity
        Then: returns NORMAL severity with green color
        """
        thresholds = BoostThresholds(cautionMin=18.0, dangerMin=22.0)
        severity, color = evaluateBoost(15.0, thresholds)

        assert severity == AlertSeverity.NORMAL
        assert color == "green"

    def test_evaluateBoost_zeroPsi_returnsNormal(self):
        """
        Given: Zero boost (vacuum/atmospheric)
        When: evaluating severity
        Then: returns NORMAL severity
        """
        thresholds = BoostThresholds()
        severity, color = evaluateBoost(0.0, thresholds)

        assert severity == AlertSeverity.NORMAL
        assert color == "green"

    def test_evaluateBoost_negativePsi_returnsNormal(self):
        """
        Given: Negative pressure (vacuum at idle)
        When: evaluating severity
        Then: returns NORMAL severity
        """
        thresholds = BoostThresholds()
        severity, color = evaluateBoost(-12.0, thresholds)

        assert severity == AlertSeverity.NORMAL
        assert color == "green"

    def test_evaluateBoost_atCautionBoundary_staysNormal(self):
        """
        Given: Boost exactly at caution boundary
        When: evaluating severity
        Then: stays NORMAL (strictly greater than triggers caution)
        """
        thresholds = BoostThresholds(cautionMin=18.0, dangerMin=22.0)
        severity, color = evaluateBoost(18.0, thresholds)

        assert severity == AlertSeverity.NORMAL
        assert color == "green"

    def test_evaluateBoost_aboveCaution_returnsCaution(self):
        """
        Given: Boost above caution but below danger
        When: evaluating severity
        Then: returns CAUTION severity with yellow color
        """
        thresholds = BoostThresholds(cautionMin=18.0, dangerMin=22.0)
        severity, color = evaluateBoost(20.0, thresholds)

        assert severity == AlertSeverity.CAUTION
        assert color == "yellow"

    def test_evaluateBoost_justAboveCaution_returnsCaution(self):
        """
        Given: Boost barely above caution threshold
        When: evaluating severity
        Then: returns CAUTION severity
        """
        thresholds = BoostThresholds(cautionMin=18.0, dangerMin=22.0)
        severity, color = evaluateBoost(18.1, thresholds)

        assert severity == AlertSeverity.CAUTION
        assert color == "yellow"

    def test_evaluateBoost_atDangerBoundary_staysCaution(self):
        """
        Given: Boost exactly at danger boundary
        When: evaluating severity
        Then: stays CAUTION (strictly greater than triggers danger)
        """
        thresholds = BoostThresholds(cautionMin=18.0, dangerMin=22.0)
        severity, color = evaluateBoost(22.0, thresholds)

        assert severity == AlertSeverity.CAUTION
        assert color == "yellow"

    def test_evaluateBoost_aboveDanger_returnsDanger(self):
        """
        Given: Boost above danger threshold (overboost)
        When: evaluating severity
        Then: returns DANGER severity with red color
        """
        thresholds = BoostThresholds(cautionMin=18.0, dangerMin=22.0)
        severity, color = evaluateBoost(25.0, thresholds)

        assert severity == AlertSeverity.DANGER
        assert color == "red"

    def test_evaluateBoost_justAboveDanger_returnsDanger(self):
        """
        Given: Boost barely above danger threshold
        When: evaluating severity
        Then: returns DANGER severity
        """
        thresholds = BoostThresholds(cautionMin=18.0, dangerMin=22.0)
        severity, color = evaluateBoost(22.1, thresholds)

        assert severity == AlertSeverity.DANGER
        assert color == "red"

    def test_evaluateBoost_extremeOverboost_returnsDanger(self):
        """
        Given: Extreme overboost condition (wastegate failure)
        When: evaluating severity
        Then: returns DANGER severity
        """
        thresholds = BoostThresholds()
        severity, color = evaluateBoost(35.0, thresholds)

        assert severity == AlertSeverity.DANGER
        assert color == "red"


# ================================================================================
# BoostTracker Tests
# ================================================================================


class TestBoostTracker:
    """Tests for BoostTracker per-drive peak tracking."""

    def test_boostTracker_initialState_zeroPeak(self):
        """
        Given: Freshly created tracker
        When: checking peak boost
        Then: peak is 0.0
        """
        tracker = BoostTracker()

        assert tracker.peakBoost == 0.0

    def test_boostTracker_singleReading_setsPeak(self):
        """
        Given: Empty tracker
        When: recording a single boost reading
        Then: peak equals that reading
        """
        tracker = BoostTracker()
        tracker.updateBoost(12.5)

        assert tracker.peakBoost == 12.5

    def test_boostTracker_multipleReadings_tracksPeak(self):
        """
        Given: Multiple boost readings over time
        When: querying peak
        Then: returns the highest reading seen
        """
        tracker = BoostTracker()
        tracker.updateBoost(10.0)
        tracker.updateBoost(15.0)
        tracker.updateBoost(12.0)
        tracker.updateBoost(8.0)

        assert tracker.peakBoost == 15.0

    def test_boostTracker_peakNotLoweredBySubsequentReadings(self):
        """
        Given: Peak recorded at 20 psi
        When: subsequent readings are lower
        Then: peak remains at 20 psi
        """
        tracker = BoostTracker()
        tracker.updateBoost(20.0)
        tracker.updateBoost(5.0)
        tracker.updateBoost(0.0)
        tracker.updateBoost(-10.0)

        assert tracker.peakBoost == 20.0

    def test_boostTracker_newHigherPeak_updatesPeak(self):
        """
        Given: Existing peak of 15 psi
        When: recording higher boost (e.g., higher RPM pull)
        Then: peak updates to the new high
        """
        tracker = BoostTracker()
        tracker.updateBoost(15.0)
        tracker.updateBoost(10.0)
        tracker.updateBoost(18.0)

        assert tracker.peakBoost == 18.0

    def test_boostTracker_resetDrive_clearsPeak(self):
        """
        Given: Tracker with accumulated peak boost
        When: resetting for a new drive
        Then: peak resets to 0.0
        """
        tracker = BoostTracker()
        tracker.updateBoost(22.0)
        assert tracker.peakBoost == 22.0

        tracker.resetDrive()

        assert tracker.peakBoost == 0.0

    def test_boostTracker_resetDrive_allowsNewPeakAccumulation(self):
        """
        Given: Tracker reset after previous drive
        When: recording new boost readings
        Then: peak tracks new drive's values independently
        """
        tracker = BoostTracker()
        tracker.updateBoost(22.0)
        tracker.resetDrive()

        tracker.updateBoost(10.0)
        tracker.updateBoost(14.0)

        assert tracker.peakBoost == 14.0

    def test_boostTracker_negativeBoost_peakStaysAtZero(self):
        """
        Given: Only negative (vacuum) readings
        When: checking peak
        Then: peak stays at 0.0 (no positive boost achieved)
        """
        tracker = BoostTracker()
        tracker.updateBoost(-5.0)
        tracker.updateBoost(-10.0)

        assert tracker.peakBoost == 0.0

    def test_boostTracker_getState_ecmlinkConnected(self):
        """
        Given: Tracker with boost data and ECMLink connected
        When: getting display state
        Then: returns available state with current values
        """
        tracker = BoostTracker()
        tracker.updateBoost(15.0)

        state = tracker.getState(
            currentBoost=12.5,
            targetBoost=14.0,
            ecmlinkConnected=True,
        )

        assert state.available is True
        assert state.ecmlinkConnected is True
        assert state.currentBoost == 12.5
        assert state.targetBoost == 14.0
        assert state.peakBoost == 15.0

    def test_boostTracker_getState_ecmlinkDisconnected(self):
        """
        Given: Tracker with ECMLink disconnected
        When: getting display state
        Then: returns unavailable state
        """
        tracker = BoostTracker()

        state = tracker.getState(
            currentBoost=0.0,
            targetBoost=0.0,
            ecmlinkConnected=False,
        )

        assert state.available is False
        assert state.ecmlinkConnected is False

    def test_boostTracker_getState_customThresholds(self):
        """
        Given: Custom boost thresholds
        When: getting state with high boost
        Then: severity reflects custom thresholds
        """
        tracker = BoostTracker()
        tracker.updateBoost(20.0)

        thresholds = BoostThresholds(cautionMin=15.0, dangerMin=20.0)
        state = tracker.getState(
            currentBoost=16.0,
            targetBoost=14.0,
            ecmlinkConnected=True,
            boostThresholds=thresholds,
        )

        assert state.severity == AlertSeverity.CAUTION
        assert state.indicatorColor == "yellow"


# ================================================================================
# isBoostPageAvailable Tests
# ================================================================================


class TestIsBoostPageAvailable:
    """Tests for boost page availability gating."""

    def test_isBoostPageAvailable_ecmlinkConnected_returnsTrue(self):
        """
        Given: ECMLink hardware is connected
        When: checking page availability
        Then: returns True (boost page should be shown)
        """
        assert isBoostPageAvailable(True) is True

    def test_isBoostPageAvailable_ecmlinkDisconnected_returnsFalse(self):
        """
        Given: ECMLink hardware is NOT connected
        When: checking page availability
        Then: returns False (boost page should be hidden)
        """
        assert isBoostPageAvailable(False) is False


# ================================================================================
# buildBoostDetailState Tests
# ================================================================================


class TestBuildBoostDetailState:
    """Tests for boost detail state construction."""

    def test_buildBoostDetailState_normalBoost(self):
        """
        Given: Normal boost readings with ECMLink connected
        When: building display state
        Then: returns complete state with NORMAL severity
        """
        state = buildBoostDetailState(
            currentBoost=12.5,
            targetBoost=14.0,
            peakBoost=15.0,
            ecmlinkConnected=True,
        )

        assert state.currentBoost == 12.5
        assert state.targetBoost == 14.0
        assert state.peakBoost == 15.0
        assert state.ecmlinkConnected is True
        assert state.available is True
        assert state.severity == AlertSeverity.NORMAL
        assert state.indicatorColor == "green"

    def test_buildBoostDetailState_cautionBoost(self):
        """
        Given: Boost above caution threshold
        When: building display state
        Then: returns state with CAUTION severity
        """
        thresholds = BoostThresholds(cautionMin=18.0, dangerMin=22.0)
        state = buildBoostDetailState(
            currentBoost=20.0,
            targetBoost=14.0,
            peakBoost=20.0,
            ecmlinkConnected=True,
            boostThresholds=thresholds,
        )

        assert state.severity == AlertSeverity.CAUTION
        assert state.indicatorColor == "yellow"

    def test_buildBoostDetailState_dangerBoost(self):
        """
        Given: Boost above danger threshold (overboost)
        When: building display state
        Then: returns state with DANGER severity
        """
        thresholds = BoostThresholds(cautionMin=18.0, dangerMin=22.0)
        state = buildBoostDetailState(
            currentBoost=25.0,
            targetBoost=14.0,
            peakBoost=25.0,
            ecmlinkConnected=True,
            boostThresholds=thresholds,
        )

        assert state.severity == AlertSeverity.DANGER
        assert state.indicatorColor == "red"

    def test_buildBoostDetailState_ecmlinkDisconnected(self):
        """
        Given: ECMLink not connected
        When: building display state
        Then: page is unavailable
        """
        state = buildBoostDetailState(
            currentBoost=0.0,
            targetBoost=0.0,
            peakBoost=0.0,
            ecmlinkConnected=False,
        )

        assert state.available is False
        assert state.ecmlinkConnected is False

    def test_buildBoostDetailState_displayTextFormatting(self):
        """
        Given: Various boost values
        When: building display state
        Then: formatted display texts include 'psi' suffix
        """
        state = buildBoostDetailState(
            currentBoost=12.5,
            targetBoost=14.0,
            peakBoost=18.3,
            ecmlinkConnected=True,
        )

        assert state.currentBoostDisplay == "12.5 psi"
        assert state.targetBoostDisplay == "14 psi"
        assert state.peakBoostDisplay == "18.3 psi"

    def test_buildBoostDetailState_integerBoostFormatting(self):
        """
        Given: Integer boost values (no fractional part)
        When: formatting display text
        Then: shows without trailing decimals
        """
        state = buildBoostDetailState(
            currentBoost=15.0,
            targetBoost=14.0,
            peakBoost=20.0,
            ecmlinkConnected=True,
        )

        assert state.currentBoostDisplay == "15 psi"
        assert state.targetBoostDisplay == "14 psi"
        assert state.peakBoostDisplay == "20 psi"

    def test_buildBoostDetailState_zeroBoost(self):
        """
        Given: Zero boost (atmospheric, no turbo spool)
        When: building display state
        Then: formats correctly with zero value
        """
        state = buildBoostDetailState(
            currentBoost=0.0,
            targetBoost=14.0,
            peakBoost=0.0,
            ecmlinkConnected=True,
        )

        assert state.currentBoostDisplay == "0 psi"
        assert state.peakBoostDisplay == "0 psi"

    def test_buildBoostDetailState_negativeBoost(self):
        """
        Given: Negative boost (vacuum at idle)
        When: building display state
        Then: formats with negative sign
        """
        state = buildBoostDetailState(
            currentBoost=-12.0,
            targetBoost=14.0,
            peakBoost=0.0,
            ecmlinkConnected=True,
        )

        assert state.currentBoostDisplay == "-12 psi"

    def test_buildBoostDetailState_defaultThresholds(self):
        """
        Given: No custom thresholds provided
        When: building state with boost above default caution
        Then: uses default threshold constants for evaluation
        """
        state = buildBoostDetailState(
            currentBoost=BOOST_CAUTION_DEFAULT + 1.0,
            targetBoost=14.0,
            peakBoost=BOOST_CAUTION_DEFAULT + 1.0,
            ecmlinkConnected=True,
        )

        assert state.severity == AlertSeverity.CAUTION

    def test_buildBoostDetailState_customThresholds(self):
        """
        Given: Custom thresholds with higher limits
        When: building state with boost that would be caution under defaults
        Then: evaluates as normal under custom thresholds
        """
        thresholds = BoostThresholds(cautionMin=25.0, dangerMin=30.0)
        state = buildBoostDetailState(
            currentBoost=20.0,
            targetBoost=14.0,
            peakBoost=20.0,
            ecmlinkConnected=True,
            boostThresholds=thresholds,
        )

        assert state.severity == AlertSeverity.NORMAL
        assert state.indicatorColor == "green"
