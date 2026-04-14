################################################################################
# File Name: test_iat_thresholds.py
# Purpose/Description: Tests for IAT tiered threshold evaluation (US-112)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-112
# ================================================================================
################################################################################

"""
Tests for Intake Air Temperature (IAT) tiered threshold evaluation.

Validates IAT thresholds with 4 levels:
Normal (ambient to 130F), Caution (130-150F), Danger (>160F),
Sensor Failure (-40F consecutive readings).

The IAT sensor is inside the MAF housing on 2G DSMs. A constant -40F
reading means sensor disconnected or failed (known 2G quirk). Sensor
failure detection requires N consecutive -40F readings (configurable,
default 5) to distinguish from genuinely cold air.

Usage:
    pytest tests/test_iat_thresholds.py -v
"""

import json
import os
from typing import Any

import pytest

from src.pi.alert.iat_thresholds import (
    IATSensorTracker,
    IATThresholds,
    evaluateIAT,
    loadIATThresholds,
)
from src.pi.alert.tiered_thresholds import AlertSeverity

# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture
def iatThresholds() -> IATThresholds:
    """
    Provide standard IAT thresholds matching obd_config.json.

    Returns:
        IATThresholds with heat soak and sensor failure boundaries
    """
    return IATThresholds(
        cautionMin=130.0,
        dangerMin=160.0,
        sensorFailureValue=-40.0,
        consecutiveReadingsForFailure=5,
        unit="fahrenheit",
        cautionMessage=(
            "IAT elevated ({value}F). Heat soak building. "
            "Power loss and increased knock risk."
        ),
        dangerMessage=(
            "DANGER: IAT critical ({value}F). Significant knock risk "
            "at boost. Reduce load."
        ),
        sensorFailureMessage=(
            "IAT sensor failure detected. Reading fixed at {value}F "
            "for {count} consecutive readings. "
            "Sensor disconnected or failed (check MAF housing connector)."
        ),
    )


@pytest.fixture
def sampleConfig() -> dict[str, Any]:
    """
    Provide sample config with tieredThresholds.iat section.

    Returns:
        Config dict with IAT thresholds
    """
    return {
        "pi": {
            "tieredThresholds": {
                "iat": {
                    "unit": "fahrenheit",
                    "cautionMin": 130.0,
                    "dangerMin": 160.0,
                    "sensorFailureValue": -40.0,
                    "consecutiveReadingsForFailure": 5,
                    "cautionMessage": (
                        "IAT elevated ({value}F). Heat soak building. "
                        "Power loss and increased knock risk."
                    ),
                    "dangerMessage": (
                        "DANGER: IAT critical ({value}F). Significant knock risk "
                        "at boost. Reduce load."
                    ),
                    "sensorFailureMessage": (
                        "IAT sensor failure detected. Reading fixed at {value}F "
                        "for {count} consecutive readings. "
                        "Sensor disconnected or failed (check MAF housing connector)."
                    ),
                }
            }
        }
    }


@pytest.fixture
def tracker(iatThresholds: IATThresholds) -> IATSensorTracker:
    """
    Provide a fresh IATSensorTracker instance.

    Returns:
        IATSensorTracker with default thresholds
    """
    return IATSensorTracker(iatThresholds)


# ================================================================================
# Normal Range Tests (ambient to 130F)
# ================================================================================


class TestNormal:
    """Tests for normal IAT conditions (ambient to 130F)."""

    def test_evaluateIAT_ambientTemp_returnsNormal(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: IAT at 75F (typical ambient)
        When: evaluateIAT is called
        Then: Returns NORMAL severity
        """
        result = evaluateIAT(75.0, iatThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False
        assert result.parameterName == "IAT"

    def test_evaluateIAT_atCautionBoundary_returnsNormal(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: IAT at exactly 130F (at caution boundary)
        When: evaluateIAT is called
        Then: Returns NORMAL severity (boundary stays in lower level)
        """
        result = evaluateIAT(130.0, iatThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False

    def test_evaluateIAT_coldAir_returnsNormal(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: IAT at 32F (cold winter air)
        When: evaluateIAT is called
        Then: Returns NORMAL severity
        """
        result = evaluateIAT(32.0, iatThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"

    def test_evaluateIAT_justBelowCaution_returnsNormal(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: IAT at 129.9F (just below caution)
        When: evaluateIAT is called
        Then: Returns NORMAL severity
        """
        result = evaluateIAT(129.9, iatThresholds)

        assert result.severity == AlertSeverity.NORMAL


# ================================================================================
# Caution Range Tests (130-160F)
# ================================================================================


class TestCaution:
    """Tests for caution IAT conditions (heat soak building)."""

    def test_evaluateIAT_justAboveCaution_returnsCaution(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: IAT at 130.1F (just above caution boundary)
        When: evaluateIAT is called
        Then: Returns CAUTION severity with heat soak message
        """
        result = evaluateIAT(130.1, iatThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True
        assert "130.1" in result.message
        assert "Heat soak" in result.message
        assert result.parameterName == "IAT"

    def test_evaluateIAT_midCaution_returnsCaution(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: IAT at 140F (middle of caution range)
        When: evaluateIAT is called
        Then: Returns CAUTION severity
        """
        result = evaluateIAT(140.0, iatThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluateIAT_at150F_returnsCaution(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: IAT at 150F (upper described caution range)
        When: evaluateIAT is called
        Then: Returns CAUTION severity
        """
        result = evaluateIAT(150.0, iatThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"

    def test_evaluateIAT_atDangerBoundary_returnsCaution(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: IAT at exactly 160F (at danger boundary)
        When: evaluateIAT is called
        Then: Returns CAUTION severity (boundary stays in lower level)
        """
        result = evaluateIAT(160.0, iatThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"


# ================================================================================
# Danger Range Tests (> 160F)
# ================================================================================


class TestDanger:
    """Tests for danger IAT conditions (significant knock risk)."""

    def test_evaluateIAT_justAboveDanger_returnsDanger(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: IAT at 160.1F (just above danger boundary)
        When: evaluateIAT is called
        Then: Returns DANGER severity with knock risk message
        """
        result = evaluateIAT(160.1, iatThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True
        assert "160.1" in result.message
        assert "knock risk" in result.message.lower()
        assert result.parameterName == "IAT"

    def test_evaluateIAT_extremeHeat_returnsDanger(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: IAT at 200F (extreme heat soak)
        When: evaluateIAT is called
        Then: Returns DANGER severity
        """
        result = evaluateIAT(200.0, iatThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True


# ================================================================================
# Sensor Failure Detection Tests
# ================================================================================


class TestSensorFailure:
    """Tests for IAT sensor failure detection (-40F consecutive readings)."""

    def test_tracker_singleMinus40_returnsNormal(
        self, tracker: IATSensorTracker
    ) -> None:
        """
        Given: A single -40F reading
        When: evaluate is called
        Then: Returns NORMAL (could be genuinely cold air, not yet confirmed failure)
        """
        result = tracker.evaluate(-40.0)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"

    def test_tracker_fourConsecutiveMinus40_returnsNormal(
        self, tracker: IATSensorTracker
    ) -> None:
        """
        Given: 4 consecutive -40F readings (below threshold of 5)
        When: evaluate is called for the 4th time
        Then: Returns NORMAL (not yet enough consecutive readings)
        """
        for _ in range(3):
            tracker.evaluate(-40.0)
        result = tracker.evaluate(-40.0)

        assert result.severity == AlertSeverity.NORMAL

    def test_tracker_fiveConsecutiveMinus40_returnsSensorFailure(
        self, tracker: IATSensorTracker
    ) -> None:
        """
        Given: 5 consecutive -40F readings (at threshold)
        When: evaluate is called for the 5th time
        Then: Returns INFO severity with sensor failure message
        """
        for _ in range(4):
            tracker.evaluate(-40.0)
        result = tracker.evaluate(-40.0)

        assert result.severity == AlertSeverity.INFO
        assert result.indicator == "blue"
        assert result.shouldLog is True
        assert "sensor failure" in result.message.lower()
        assert "MAF housing" in result.message
        assert result.parameterName == "IAT"

    def test_tracker_sixConsecutiveMinus40_continuesSensorFailure(
        self, tracker: IATSensorTracker
    ) -> None:
        """
        Given: 6 consecutive -40F readings (above threshold)
        When: evaluate is called for the 6th time
        Then: Still returns sensor failure
        """
        for _ in range(5):
            tracker.evaluate(-40.0)
        result = tracker.evaluate(-40.0)

        assert result.severity == AlertSeverity.INFO
        assert result.shouldLog is True

    def test_tracker_minus40InterruptedByNormal_resetsCounter(
        self, tracker: IATSensorTracker
    ) -> None:
        """
        Given: 3 consecutive -40F readings, then a normal reading, then 2 more -40F
        When: evaluate is called
        Then: Counter resets — no sensor failure detected
        """
        for _ in range(3):
            tracker.evaluate(-40.0)
        tracker.evaluate(75.0)
        result = tracker.evaluate(-40.0)

        assert result.severity == AlertSeverity.NORMAL

    def test_tracker_minus40ResetsAfterNormal_needsFullCountAgain(
        self, tracker: IATSensorTracker
    ) -> None:
        """
        Given: 4 consecutive -40F, then normal, then 5 consecutive -40F
        When: evaluate is called
        Then: Sensor failure detected only after the second run of 5
        """
        for _ in range(4):
            tracker.evaluate(-40.0)
        tracker.evaluate(75.0)

        for _ in range(4):
            result = tracker.evaluate(-40.0)
            assert result.severity == AlertSeverity.NORMAL

        result = tracker.evaluate(-40.0)
        assert result.severity == AlertSeverity.INFO
        assert "sensor failure" in result.message.lower()

    def test_tracker_normalReadingAfterSensorFailure_resetsState(
        self, tracker: IATSensorTracker
    ) -> None:
        """
        Given: Sensor failure detected, then a normal reading
        When: evaluate is called with normal value
        Then: Returns normal result and resets counter
        """
        for _ in range(5):
            tracker.evaluate(-40.0)
        result = tracker.evaluate(75.0)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"

    def test_tracker_customConsecutiveCount_respectsConfig(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: Thresholds with consecutiveReadingsForFailure = 3
        When: 3 consecutive -40F readings
        Then: Sensor failure detected after 3 readings
        """
        iatThresholds.consecutiveReadingsForFailure = 3
        customTracker = IATSensorTracker(iatThresholds)

        for _ in range(2):
            result = customTracker.evaluate(-40.0)
            assert result.severity == AlertSeverity.NORMAL

        result = customTracker.evaluate(-40.0)
        assert result.severity == AlertSeverity.INFO
        assert "sensor failure" in result.message.lower()

    def test_tracker_normalValues_passedToEvaluateIAT(
        self, tracker: IATSensorTracker
    ) -> None:
        """
        Given: Normal temperature values
        When: tracker.evaluate is called
        Then: Returns threshold evaluation results (caution/danger as appropriate)
        """
        result = tracker.evaluate(140.0)
        assert result.severity == AlertSeverity.CAUTION

        result = tracker.evaluate(170.0)
        assert result.severity == AlertSeverity.DANGER

    def test_tracker_sensorFailureMessage_includesCount(
        self, tracker: IATSensorTracker
    ) -> None:
        """
        Given: 5 consecutive -40F readings triggering sensor failure
        When: evaluate is called
        Then: Message includes the consecutive count
        """
        for _ in range(4):
            tracker.evaluate(-40.0)
        result = tracker.evaluate(-40.0)

        assert "5" in result.message

    def test_tracker_reset_clearsState(
        self, tracker: IATSensorTracker
    ) -> None:
        """
        Given: Tracker with accumulated -40F readings
        When: reset is called
        Then: Counter is cleared, next evaluate starts fresh
        """
        for _ in range(3):
            tracker.evaluate(-40.0)

        tracker.reset()

        for _ in range(4):
            result = tracker.evaluate(-40.0)
            assert result.severity == AlertSeverity.NORMAL


# ================================================================================
# Alert Log Entry Tests
# ================================================================================


class TestAlertLogEntry:
    """Tests for alert log entry generation from IAT results."""

    def test_toLogEntry_caution_containsRequiredFields(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: A CAUTION result from elevated IAT
        When: toLogEntry is called
        Then: Log entry contains severity, parameterName, value, message
        """
        result = evaluateIAT(140.0, iatThresholds)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "caution"
        assert logEntry["parameterName"] == "IAT"
        assert logEntry["value"] == 140.0
        assert "140.0" in logEntry["message"]

    def test_toLogEntry_danger_containsRequiredFields(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: A DANGER result from critical IAT
        When: toLogEntry is called
        Then: Log entry contains severity, parameterName, value, message
        """
        result = evaluateIAT(170.0, iatThresholds)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "danger"
        assert logEntry["parameterName"] == "IAT"
        assert logEntry["value"] == 170.0

    def test_toLogEntry_sensorFailure_containsRequiredFields(
        self, tracker: IATSensorTracker
    ) -> None:
        """
        Given: A sensor failure result
        When: toLogEntry is called
        Then: Log entry contains info severity and sensor failure message
        """
        for _ in range(5):
            tracker.evaluate(-40.0)
        result = tracker.evaluate(-40.0)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "info"
        assert logEntry["parameterName"] == "IAT"
        assert logEntry["value"] == -40.0

    def test_normalResult_shouldNotLog(
        self, iatThresholds: IATThresholds
    ) -> None:
        """
        Given: A NORMAL result
        When: shouldLog is checked
        Then: shouldLog is False
        """
        result = evaluateIAT(75.0, iatThresholds)

        assert result.shouldLog is False


# ================================================================================
# Config Loading Tests
# ================================================================================


class TestLoadIATThresholds:
    """Tests for loading IAT thresholds from config."""

    def test_loadIATThresholds_validConfig_returnsThresholds(
        self, sampleConfig: dict[str, Any]
    ) -> None:
        """
        Given: Valid config with tieredThresholds.iat
        When: loadIATThresholds is called
        Then: Returns IATThresholds with correct values
        """
        thresholds = loadIATThresholds(sampleConfig)

        assert thresholds.cautionMin == 130.0
        assert thresholds.dangerMin == 160.0
        assert thresholds.sensorFailureValue == -40.0
        assert thresholds.consecutiveReadingsForFailure == 5
        assert thresholds.unit == "fahrenheit"

    def test_loadIATThresholds_missingTiered_raisesError(
        self,
    ) -> None:
        """
        Given: Config missing tieredThresholds section
        When: loadIATThresholds is called
        Then: Raises AlertConfigurationError
        """
        from src.pi.alert.exceptions import AlertConfigurationError

        with pytest.raises(AlertConfigurationError):
            loadIATThresholds({})

    def test_loadIATThresholds_missingIAT_raisesError(
        self,
    ) -> None:
        """
        Given: Config with tieredThresholds but missing iat
        When: loadIATThresholds is called
        Then: Raises AlertConfigurationError
        """
        from src.pi.alert.exceptions import AlertConfigurationError

        config: dict[str, Any] = {"pi": {"tieredThresholds": {}}}
        with pytest.raises(AlertConfigurationError):
            loadIATThresholds(config)

    def test_loadIATThresholds_defaultMessages_usedWhenNotInConfig(
        self,
    ) -> None:
        """
        Given: Config without custom messages
        When: loadIATThresholds is called
        Then: Default messages are used
        """
        config: dict[str, Any] = {
            "pi": {
                "tieredThresholds": {
                    "iat": {
                        "cautionMin": 130.0,
                        "dangerMin": 160.0,
                    }
                }
            }
        }
        thresholds = loadIATThresholds(config)

        assert "{value}" in thresholds.cautionMessage
        assert "{value}" in thresholds.dangerMessage
        assert "{value}" in thresholds.sensorFailureMessage

    def test_loadIATThresholds_defaultSensorFailureConfig(
        self,
    ) -> None:
        """
        Given: Config without sensor failure settings
        When: loadIATThresholds is called
        Then: Defaults to -40F and 5 consecutive readings
        """
        config: dict[str, Any] = {
            "pi": {
                "tieredThresholds": {
                    "iat": {
                        "cautionMin": 130.0,
                        "dangerMin": 160.0,
                    }
                }
            }
        }
        thresholds = loadIATThresholds(config)

        assert thresholds.sensorFailureValue == -40.0
        assert thresholds.consecutiveReadingsForFailure == 5

    def test_loadIATThresholds_fromActualConfig_loadsSuccessfully(
        self,
    ) -> None:
        """
        Given: The actual config.json file
        When: loadIATThresholds is called
        Then: Loads without error
        """
        configPath = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config.json",
        )
        with open(configPath) as f:
            config = json.load(f)

        thresholds = loadIATThresholds(config)

        assert thresholds.cautionMin == 130.0
        assert thresholds.dangerMin == 160.0
        assert thresholds.sensorFailureValue == -40.0
