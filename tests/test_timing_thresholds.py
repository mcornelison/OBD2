################################################################################
# File Name: test_timing_thresholds.py
# Purpose/Description: Tests for timing advance threshold evaluation (US-109)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-109
# ================================================================================
################################################################################

"""
Tests for timing advance tiered threshold evaluation.

Unlike coolant/STFT thresholds (absolute ranges), timing advance uses
baseline-relative evaluation. The system tracks per-RPM/load baselines
and detects sudden drops indicating knock/detonation events.

Levels:
- Normal: Timing matches learned baseline for RPM/load point
- Caution: Drops > 5 degrees below baseline suddenly
- Danger: Timing at 0 or negative under load (active detonation)

Pattern detection: repeated timing retards at the same RPM/load point
are flagged for review.

Usage:
    pytest tests/test_timing_thresholds.py -v
"""

import json
import os
from typing import Any

import pytest

from src.alert.tiered_thresholds import AlertSeverity
from src.alert.timing_thresholds import (
    TimingAdvanceThresholds,
    TimingRetardTracker,
    loadTimingAdvanceThresholds,
)

# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture
def timingThresholds() -> TimingAdvanceThresholds:
    """
    Provide standard timing advance thresholds matching obd_config.json.

    Returns:
        TimingAdvanceThresholds with 4G63 knock-detection values
    """
    return TimingAdvanceThresholds(
        cautionDropDegrees=5.0,
        dangerValue=0.0,
        loadThresholdPercent=30.0,
        repeatCountForPattern=3,
        rpmBandSize=500,
        loadBandSize=10,
        defaultBaseline=15.0,
    )


@pytest.fixture
def tracker(timingThresholds: TimingAdvanceThresholds) -> TimingRetardTracker:
    """
    Provide a fresh TimingRetardTracker with standard thresholds.

    Returns:
        TimingRetardTracker with no learned baselines
    """
    return TimingRetardTracker(timingThresholds)


@pytest.fixture
def sampleConfig() -> dict[str, Any]:
    """
    Provide sample config with tieredThresholds.timingAdvance section.

    Returns:
        Config dict with timingAdvance thresholds
    """
    return {
        "tieredThresholds": {
            "timingAdvance": {
                "unit": "degrees",
                "cautionDropDegrees": 5.0,
                "dangerValue": 0.0,
                "loadThresholdPercent": 30.0,
                "repeatCountForPattern": 3,
                "rpmBandSize": 500,
                "loadBandSize": 10,
                "defaultBaseline": 15.0,
                "cautionMessage": (
                    "Timing retard detected ({value} deg at {rpm} RPM"
                    "/{load}% load). Dropped {drop} deg below baseline."
                    " Possible knock event."
                ),
                "dangerMessage": (
                    "DANGER: Timing advance at {value} deg under load."
                    " Active detonation. Reduce throttle immediately."
                    " Do not continue at this load."
                ),
                "patternMessage": (
                    "PATTERN: Repeated timing retard at {rpm} RPM"
                    "/{load}% load ({count} occurrences)."
                    " Review fueling/boost at this operating point."
                ),
            }
        }
    }


# ================================================================================
# Tracker Baseline Tests
# ================================================================================


class TestTrackerBaseline:
    """Tests for per-RPM/load baseline tracking."""

    def test_getBaseline_noData_returnsDefault(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: No baseline data learned
        When: getBaseline called
        Then: Returns defaultBaseline from config (15.0)
        """
        baseline = tracker.getBaseline(3000, 50)

        assert baseline == 15.0

    def test_updateBaseline_firstReading_setsValue(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: No baseline at RPM/load point
        When: updateBaseline called with first reading
        Then: Baseline set to that value
        """
        tracker.updateBaseline(3000, 50, 18.0)

        assert tracker.getBaseline(3000, 50) == 18.0

    def test_updateBaseline_multipleReadings_computesRunningAverage(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Baseline with one reading of 18.0
        When: Second reading of 16.0 added
        Then: Baseline is running average = 17.0
        """
        tracker.updateBaseline(3000, 50, 18.0)
        tracker.updateBaseline(3000, 50, 16.0)

        assert tracker.getBaseline(3000, 50) == 17.0

    def test_rpmBanding_roundsToFloor(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: RPM band size of 500
        When: Readings at 2750 and 2900 RPM
        Then: Both map to 2500 RPM band (floor)
        """
        tracker.updateBaseline(2750, 50, 18.0)
        baseline = tracker.getBaseline(2900, 50)

        assert baseline == 18.0

    def test_loadBanding_roundsToFloor(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Load band size of 10
        When: Readings at 35% and 39% load
        Then: Both map to 30% load band (floor)
        """
        tracker.updateBaseline(3000, 35, 18.0)
        baseline = tracker.getBaseline(3000, 39)

        assert baseline == 18.0

    def test_differentBands_independentBaselines(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Baselines set at two different RPM/load points
        When: Each is queried
        Then: Each returns its own baseline (no cross-contamination)
        """
        tracker.updateBaseline(2000, 30, 20.0)
        tracker.updateBaseline(5000, 80, 10.0)

        assert tracker.getBaseline(2000, 30) == 20.0
        assert tracker.getBaseline(5000, 80) == 10.0


# ================================================================================
# Normal Evaluation Tests
# ================================================================================


class TestTimingAdvanceNormal:
    """Tests for Normal level: timing matches baseline."""

    def test_evaluate_atBaseline_returnsNormal(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing advance at 15 deg (matches default baseline)
        When: Evaluated at 3000 RPM / 50% load
        Then: Returns normal severity with green indicator
        """
        result = tracker.evaluate(15.0, 3000, 50)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False

    def test_evaluate_3BelowBaseline_returnsNormal(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing 3 deg below baseline (drop < 5)
        When: Evaluated
        Then: Returns normal (drop not big enough for caution)
        """
        result = tracker.evaluate(12.0, 3000, 50)

        assert result.severity == AlertSeverity.NORMAL

    def test_evaluate_exactly5BelowBaseline_returnsNormal(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing exactly 5 deg below baseline (drop == 5, not > 5)
        When: Evaluated
        Then: Returns normal (boundary: must be > 5 for caution)
        """
        result = tracker.evaluate(10.0, 3000, 50)

        assert result.severity == AlertSeverity.NORMAL

    def test_evaluate_aboveBaseline_returnsNormal(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing above baseline (ECU advancing)
        When: Evaluated
        Then: Returns normal
        """
        result = tracker.evaluate(20.0, 3000, 50)

        assert result.severity == AlertSeverity.NORMAL


# ================================================================================
# Caution Evaluation Tests (drops > 5 deg below baseline)
# ================================================================================


class TestTimingAdvanceCaution:
    """Tests for Caution level: sudden timing retard."""

    def test_evaluate_moreThan5BelowBaseline_returnsCaution(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing 5.1 deg below baseline (default 15, value 9.9)
        When: Evaluated
        Then: Returns caution severity with yellow indicator
        """
        result = tracker.evaluate(9.9, 3000, 50)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluate_10BelowBaseline_returnsCaution(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing 10 deg below baseline (default 15, value 5)
        When: Evaluated
        Then: Returns caution severity
        """
        result = tracker.evaluate(5.0, 3000, 50)

        assert result.severity == AlertSeverity.CAUTION

    def test_evaluate_cautionAtLowLoad_stillCaution(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing drop > 5 deg below baseline at low load (20%)
        When: Evaluated
        Then: Returns caution (caution is not load-dependent)
        """
        result = tracker.evaluate(5.0, 3000, 20)

        assert result.severity == AlertSeverity.CAUTION

    def test_evaluate_cautionShouldLog_true(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing retard at caution level
        When: Evaluated
        Then: shouldLog is True for alert log entry
        """
        result = tracker.evaluate(9.0, 3000, 50)

        assert result.shouldLog is True
        assert result.parameterName == "TIMING_ADVANCE"


# ================================================================================
# Danger Evaluation Tests (value <= 0 under load)
# ================================================================================


class TestTimingAdvanceDanger:
    """Tests for Danger level: active detonation."""

    def test_evaluate_zeroUnderLoad_returnsDanger(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing at 0 deg with load > 30% (under load)
        When: Evaluated
        Then: Returns danger severity with red indicator
        """
        result = tracker.evaluate(0.0, 3000, 50)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True

    def test_evaluate_negativeUnderLoad_returnsDanger(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing at -2 deg under load
        When: Evaluated
        Then: Returns danger severity
        """
        result = tracker.evaluate(-2.0, 4000, 60)

        assert result.severity == AlertSeverity.DANGER

    def test_evaluate_zeroAtLowLoad_notDanger(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing at 0 deg but load is 20% (below 30% threshold)
        When: Evaluated
        Then: NOT danger (under-load qualifier not met)
        """
        result = tracker.evaluate(0.0, 800, 20)

        assert result.severity != AlertSeverity.DANGER

    def test_evaluate_zeroAtExactLoadThreshold_notDanger(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing at 0 deg with load exactly at threshold (30%)
        When: Evaluated
        Then: NOT danger (must be > threshold, not >=)
        """
        result = tracker.evaluate(0.0, 3000, 30)

        assert result.severity != AlertSeverity.DANGER

    def test_evaluate_zeroJustAboveLoadThreshold_returnsDanger(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing at 0 deg with load at 30.1% (just above threshold)
        When: Evaluated
        Then: Returns danger
        """
        result = tracker.evaluate(0.0, 3000, 30.1)

        assert result.severity == AlertSeverity.DANGER

    def test_evaluate_dangerShouldLog_true(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Timing at danger level
        When: Evaluated
        Then: shouldLog is True for alert log entry
        """
        result = tracker.evaluate(-1.0, 5000, 80)

        assert result.shouldLog is True
        assert result.parameterName == "TIMING_ADVANCE"


# ================================================================================
# Pattern Detection Tests
# ================================================================================


class TestPatternDetection:
    """Tests for repeated timing retard pattern detection."""

    def test_retardCount_incrementsPerOccurrence(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Repeated caution-level retards at same RPM/load
        When: Evaluated multiple times
        Then: Retard count increments for that operating point
        """
        tracker.evaluate(9.0, 3000, 50)
        tracker.evaluate(9.0, 3000, 50)

        assert tracker.getRetardCount(3000, 50) == 2

    def test_repeatedRetard_flagsPatternAtThreshold(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: 3 retards at same RPM/load (repeatCountForPattern=3)
        When: Third retard evaluated
        Then: Message changes to pattern message
        """
        tracker.evaluate(9.0, 3000, 50)
        tracker.evaluate(8.0, 3000, 50)
        result = tracker.evaluate(9.0, 3000, 50)

        assert result.severity == AlertSeverity.CAUTION
        assert "PATTERN" in result.message
        assert "3" in result.message

    def test_retardAtDifferentPoints_noCrossContamination(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Retards at two different RPM/load points
        When: Counts checked
        Then: Each point has independent count
        """
        tracker.evaluate(9.0, 3000, 50)
        tracker.evaluate(9.0, 3000, 50)
        tracker.evaluate(9.0, 5000, 80)

        assert tracker.getRetardCount(3000, 50) == 2
        assert tracker.getRetardCount(5000, 80) == 1

    def test_dangerAlsoCountsAsRetard(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Danger-level event (timing 0 under load)
        When: Evaluated
        Then: Also recorded as retard for pattern tracking
        """
        tracker.evaluate(0.0, 3000, 50)

        assert tracker.getRetardCount(3000, 50) == 1


# ================================================================================
# Baseline Learning Tests
# ================================================================================


class TestBaselineLearning:
    """Tests for baseline updates during normal operation."""

    def test_normalReading_updatesBaseline(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Normal reading (within baseline range)
        When: Evaluated
        Then: Baseline is updated with the new reading
        """
        tracker.evaluate(18.0, 3000, 50)

        assert tracker.getBaseline(3000, 50) == 18.0

    def test_cautionReading_doesNotUpdateBaseline(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Caution reading (> 5 deg below baseline)
        When: Evaluated
        Then: Baseline is NOT updated (retarded values shouldn't become new normal)
        """
        tracker.evaluate(18.0, 3000, 50)
        tracker.evaluate(5.0, 3000, 50)

        assert tracker.getBaseline(3000, 50) == 18.0

    def test_dangerReading_doesNotUpdateBaseline(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Danger reading (timing at 0 under load)
        When: Evaluated
        Then: Baseline is NOT updated
        """
        tracker.evaluate(18.0, 3000, 50)
        tracker.evaluate(0.0, 3000, 50)

        assert tracker.getBaseline(3000, 50) == 18.0


# ================================================================================
# Message Format Tests
# ================================================================================


class TestMessageFormat:
    """Tests for alert message formatting."""

    def test_cautionMessage_containsValues(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Caution-level timing retard
        When: Evaluated
        Then: Message contains the timing value
        """
        result = tracker.evaluate(9.0, 3000, 50)

        assert "9.0" in result.message
        assert result.severity == AlertSeverity.CAUTION

    def test_dangerMessage_containsDetonationWarning(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Danger-level timing (0 under load)
        When: Evaluated
        Then: Message contains detonation warning per Spool spec
        """
        result = tracker.evaluate(0.0, 4000, 70)

        assert "Reduce throttle immediately" in result.message
        assert "Do not continue at this load" in result.message

    def test_logEntry_matchesSpoolFormat(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: Caution result
        When: toLogEntry called
        Then: Contains severity, parameterName, value, message
        """
        result = tracker.evaluate(9.0, 3000, 50)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "caution"
        assert logEntry["parameterName"] == "TIMING_ADVANCE"
        assert logEntry["value"] == 9.0
        assert "message" in logEntry


# ================================================================================
# Default Baseline Tests
# ================================================================================


class TestDefaultBaseline:
    """Tests for behavior when no learned baseline exists."""

    def test_evaluate_noLearnedBaseline_usesDefault(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: No readings at this RPM/load point (no learned baseline)
        When: Value is > 5 deg below default baseline (15)
        Then: Uses default baseline for comparison, returns caution
        """
        result = tracker.evaluate(9.0, 6000, 90)

        assert result.severity == AlertSeverity.CAUTION

    def test_evaluate_atDefaultBaseline_returnsNormal(
        self, tracker: TimingRetardTracker
    ) -> None:
        """
        Given: No learned baseline, value matches default (15)
        When: Evaluated
        Then: Returns normal
        """
        result = tracker.evaluate(15.0, 6000, 90)

        assert result.severity == AlertSeverity.NORMAL


# ================================================================================
# Config Loading Tests
# ================================================================================


class TestLoadTimingAdvanceThresholds:
    """Tests for loading thresholds from obd_config.json."""

    def test_loadFromConfig_validConfig_returnsThresholds(
        self, sampleConfig: dict[str, Any]
    ) -> None:
        """
        Given: Valid config with tieredThresholds.timingAdvance section
        When: loadTimingAdvanceThresholds called
        Then: Returns TimingAdvanceThresholds with correct values
        """
        thresholds = loadTimingAdvanceThresholds(sampleConfig)

        assert thresholds.cautionDropDegrees == 5.0
        assert thresholds.dangerValue == 0.0
        assert thresholds.loadThresholdPercent == 30.0
        assert thresholds.repeatCountForPattern == 3
        assert thresholds.rpmBandSize == 500
        assert thresholds.loadBandSize == 10
        assert thresholds.defaultBaseline == 15.0

    def test_loadFromConfig_messagesPreserved(
        self, sampleConfig: dict[str, Any]
    ) -> None:
        """
        Given: Config with custom messages
        When: loadTimingAdvanceThresholds called
        Then: Messages match config values
        """
        thresholds = loadTimingAdvanceThresholds(sampleConfig)

        assert "{value}" in thresholds.cautionMessage
        assert "detonation" in thresholds.dangerMessage.lower()

    def test_loadFromConfig_missingSection_raisesError(self) -> None:
        """
        Given: Config without tieredThresholds section
        When: loadTimingAdvanceThresholds called
        Then: Raises AlertConfigurationError
        """
        from src.alert.exceptions import AlertConfigurationError

        with pytest.raises(AlertConfigurationError):
            loadTimingAdvanceThresholds({})

    def test_loadFromConfig_missingTimingAdvance_raisesError(self) -> None:
        """
        Given: Config with tieredThresholds but no timingAdvance
        When: loadTimingAdvanceThresholds called
        Then: Raises AlertConfigurationError
        """
        from src.alert.exceptions import AlertConfigurationError

        config: dict[str, Any] = {"tieredThresholds": {}}
        with pytest.raises(AlertConfigurationError):
            loadTimingAdvanceThresholds(config)

    def test_thresholdsFromConfig_notHardcoded(self) -> None:
        """
        Given: Config with custom threshold values
        When: Loaded and used for evaluation
        Then: Evaluation uses config values, not hardcoded defaults
        """
        customConfig: dict[str, Any] = {
            "tieredThresholds": {
                "timingAdvance": {
                    "unit": "degrees",
                    "cautionDropDegrees": 3.0,
                    "dangerValue": 2.0,
                    "loadThresholdPercent": 20.0,
                    "repeatCountForPattern": 5,
                    "rpmBandSize": 250,
                    "loadBandSize": 5,
                    "defaultBaseline": 20.0,
                }
            }
        }
        thresholds = loadTimingAdvanceThresholds(customConfig)
        tracker = TimingRetardTracker(thresholds)

        result = tracker.evaluate(16.0, 3000, 50)
        assert result.severity == AlertSeverity.CAUTION

    def test_liveConfig_hasTimingAdvanceThresholds(self) -> None:
        """
        Given: The actual obd_config.json file
        When: Loaded
        Then: Contains tieredThresholds.timingAdvance with all required fields
        """
        configPath = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "src", "obd_config.json"
        )
        with open(configPath) as f:
            config = json.load(f)

        thresholds = loadTimingAdvanceThresholds(config)

        assert thresholds.cautionDropDegrees == 5.0
        assert thresholds.dangerValue == 0.0
        assert thresholds.defaultBaseline == 15.0
        assert thresholds.unit == "degrees"
