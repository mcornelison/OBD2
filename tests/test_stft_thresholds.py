################################################################################
# File Name: test_stft_thresholds.py
# Purpose/Description: Tests for STFT tiered threshold evaluation (US-108)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-108
# ================================================================================
################################################################################

"""
Tests for STFT (Short-Term Fuel Trim) tiered threshold evaluation.

Validates STFT thresholds with 3 symmetric levels:
Normal (-5% to +5%), Caution (±5% to ±15%), Danger (beyond ±15%).

STFT is bidirectional: positive = lean (ECU adding fuel),
negative = rich (ECU removing fuel). Messages distinguish lean vs rich.

Boundary values from acceptance criteria:
-15.1=danger, -15=danger, -10=caution, -5=caution, -4.9=normal,
+4.9=normal, +5=caution, +10=caution, +15=danger, +15.1=danger.

Usage:
    pytest tests/test_stft_thresholds.py -v
"""

import json
import os
from typing import Any

import pytest

from src.pi.alert.tiered_thresholds import (
    AlertSeverity,
    STFTThresholds,
    evaluateSTFT,
    loadSTFTThresholds,
)

# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture
def stftThresholds() -> STFTThresholds:
    """
    Provide standard STFT thresholds matching obd_config.json.

    Returns:
        STFTThresholds with symmetric ±5%/±15% boundaries
    """
    return STFTThresholds(
        cautionMin=5,
        dangerMin=15,
        unit="percent",
        cautionMessageLean=(
            "STFT lean correction elevated ({value}%). "
            "ECU compensating. Monitor for trend."
        ),
        cautionMessageRich=(
            "STFT rich correction elevated ({value}%). "
            "ECU compensating. Monitor for trend."
        ),
        dangerMessageLean=(
            "DANGER: STFT at correction limit ({value}%). "
            "Active lean condition. Possible vacuum leak, "
            "weak fuel pump, or clogged injector."
        ),
        dangerMessageRich=(
            "DANGER: STFT at correction limit ({value}%). "
            "Active rich condition. Check for leaking injector "
            "or fuel pressure regulator."
        ),
    )


@pytest.fixture
def sampleSTFTConfig() -> dict[str, Any]:
    """
    Provide sample config with tieredThresholds.stft section.

    Returns:
        Config dict with STFT thresholds
    """
    return {
        "tieredThresholds": {
            "stft": {
                "unit": "percent",
                "cautionMin": 5,
                "dangerMin": 15,
                "cautionMessageLean": (
                    "STFT lean correction elevated ({value}%). "
                    "ECU compensating. Monitor for trend."
                ),
                "cautionMessageRich": (
                    "STFT rich correction elevated ({value}%). "
                    "ECU compensating. Monitor for trend."
                ),
                "dangerMessageLean": (
                    "DANGER: STFT at correction limit ({value}%). "
                    "Active lean condition. Possible vacuum leak, "
                    "weak fuel pump, or clogged injector."
                ),
                "dangerMessageRich": (
                    "DANGER: STFT at correction limit ({value}%). "
                    "Active rich condition. Check for leaking injector "
                    "or fuel pressure regulator."
                ),
            }
        }
    }


# ================================================================================
# Normal Threshold Tests (-5% < value < +5%)
# ================================================================================


class TestSTFTNormal:
    """Tests for Normal level: ECU making small corrections."""

    def test_evaluateSTFT_negative4point9_returnsNormal(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at -4.9%
        When: Evaluated against thresholds
        Then: Returns normal severity with green indicator
        """
        result = evaluateSTFT(-4.9, stftThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False

    def test_evaluateSTFT_positive4point9_returnsNormal(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at +4.9%
        When: Evaluated against thresholds
        Then: Returns normal severity with green indicator
        """
        result = evaluateSTFT(4.9, stftThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False

    def test_evaluateSTFT_zero_returnsNormal(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at 0%
        When: Evaluated against thresholds
        Then: Returns normal severity
        """
        result = evaluateSTFT(0, stftThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False

    def test_evaluateSTFT_normal_parameterName(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at normal level
        When: Evaluated
        Then: parameterName is STFT
        """
        result = evaluateSTFT(0, stftThresholds)

        assert result.parameterName == "STFT"


# ================================================================================
# Caution Threshold Tests — Positive (Lean)
# ================================================================================


class TestSTFTCautionLean:
    """Tests for Caution level on positive (lean) side."""

    def test_evaluateSTFT_positive5_returnsCaution(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at +5% (lean caution boundary)
        When: Evaluated against thresholds
        Then: Returns caution severity with yellow indicator
        """
        result = evaluateSTFT(5, stftThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluateSTFT_positive10_returnsCaution(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at +10% (mid-range lean caution)
        When: Evaluated against thresholds
        Then: Returns caution severity
        """
        result = evaluateSTFT(10, stftThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluateSTFT_positive_caution_leanMessage(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at +7% (lean caution)
        When: Evaluated against thresholds
        Then: Message uses lean template with interpolated value
        """
        result = evaluateSTFT(7, stftThresholds)

        assert "lean" in result.message.lower()
        assert "7" in result.message


# ================================================================================
# Caution Threshold Tests — Negative (Rich)
# ================================================================================


class TestSTFTCautionRich:
    """Tests for Caution level on negative (rich) side."""

    def test_evaluateSTFT_negative5_returnsCaution(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at -5% (rich caution boundary)
        When: Evaluated against thresholds
        Then: Returns caution severity with yellow indicator
        """
        result = evaluateSTFT(-5, stftThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluateSTFT_negative10_returnsCaution(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at -10% (mid-range rich caution)
        When: Evaluated against thresholds
        Then: Returns caution severity
        """
        result = evaluateSTFT(-10, stftThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluateSTFT_negative_caution_richMessage(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at -7% (rich caution)
        When: Evaluated against thresholds
        Then: Message uses rich template with interpolated value
        """
        result = evaluateSTFT(-7, stftThresholds)

        assert "rich" in result.message.lower()
        assert "-7" in result.message


# ================================================================================
# Danger Threshold Tests — Positive (Lean)
# ================================================================================


class TestSTFTDangerLean:
    """Tests for Danger level on positive (lean) side."""

    def test_evaluateSTFT_positive15_returnsDanger(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at +15% (lean danger boundary)
        When: Evaluated against thresholds
        Then: Returns danger severity with red indicator
        """
        result = evaluateSTFT(15, stftThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True

    def test_evaluateSTFT_positive15point1_returnsDanger(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at +15.1% (beyond lean danger boundary)
        When: Evaluated against thresholds
        Then: Returns danger severity
        """
        result = evaluateSTFT(15.1, stftThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True

    def test_evaluateSTFT_positive_danger_leanMessage(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at +15% (lean danger)
        When: Evaluated against thresholds
        Then: Message uses lean danger template with causes
        """
        result = evaluateSTFT(15, stftThresholds)

        assert "lean" in result.message.lower()
        assert "vacuum leak" in result.message.lower()
        assert "15" in result.message


# ================================================================================
# Danger Threshold Tests — Negative (Rich)
# ================================================================================


class TestSTFTDangerRich:
    """Tests for Danger level on negative (rich) side."""

    def test_evaluateSTFT_negative15_returnsDanger(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at -15% (rich danger boundary)
        When: Evaluated against thresholds
        Then: Returns danger severity with red indicator
        """
        result = evaluateSTFT(-15, stftThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True

    def test_evaluateSTFT_negative15point1_returnsDanger(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at -15.1% (beyond rich danger boundary)
        When: Evaluated against thresholds
        Then: Returns danger severity
        """
        result = evaluateSTFT(-15.1, stftThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True

    def test_evaluateSTFT_negative_danger_richMessage(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at -15% (rich danger)
        When: Evaluated against thresholds
        Then: Message uses rich danger template with causes
        """
        result = evaluateSTFT(-15, stftThresholds)

        assert "rich" in result.message.lower()
        assert "injector" in result.message.lower()
        assert "-15" in result.message


# ================================================================================
# Alert Log Entry Tests
# ================================================================================


class TestSTFTAlertLog:
    """Tests for STFT alert log entry creation at Caution and Danger."""

    def test_evaluateSTFT_normal_noLogEntry(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at normal level
        When: Evaluated
        Then: shouldLog is False
        """
        result = evaluateSTFT(0, stftThresholds)
        assert result.shouldLog is False

    def test_evaluateSTFT_caution_createsLogEntry(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at caution level
        When: Evaluated
        Then: shouldLog is True with severity and message
        """
        result = evaluateSTFT(7, stftThresholds)

        assert result.shouldLog is True
        assert result.severity == AlertSeverity.CAUTION

    def test_evaluateSTFT_danger_createsLogEntry(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at danger level
        When: Evaluated
        Then: shouldLog is True with severity and message
        """
        result = evaluateSTFT(20, stftThresholds)

        assert result.shouldLog is True
        assert result.severity == AlertSeverity.DANGER

    def test_evaluateSTFT_caution_logEntry_hasSeverityField(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at caution level
        When: Alert log entry dict is generated
        Then: Contains severity, parameterName, value, message
        """
        result = evaluateSTFT(7, stftThresholds)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "caution"
        assert logEntry["parameterName"] == "STFT"
        assert logEntry["value"] == 7
        assert "message" in logEntry

    def test_evaluateSTFT_danger_logEntry_format(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at danger level (lean)
        When: Alert log entry dict is generated
        Then: Contains severity=danger and lean danger message
        """
        result = evaluateSTFT(20, stftThresholds)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "danger"
        assert logEntry["parameterName"] == "STFT"
        assert logEntry["value"] == 20
        assert "lean" in logEntry["message"].lower()

    def test_evaluateSTFT_danger_rich_logEntry_format(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: STFT at danger level (rich)
        When: Alert log entry dict is generated
        Then: Contains severity=danger and rich danger message
        """
        result = evaluateSTFT(-20, stftThresholds)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "danger"
        assert logEntry["parameterName"] == "STFT"
        assert logEntry["value"] == -20
        assert "rich" in logEntry["message"].lower()


# ================================================================================
# Lean vs Rich Message Distinction Tests
# ================================================================================


class TestSTFTLeanRichMessages:
    """Tests that messages correctly distinguish lean from rich conditions."""

    def test_evaluateSTFT_positive_usesLeanMessage(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: Positive STFT (lean condition)
        When: Evaluated at caution level
        Then: Message identifies lean condition
        """
        result = evaluateSTFT(7, stftThresholds)
        assert "lean" in result.message.lower()

    def test_evaluateSTFT_negative_usesRichMessage(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: Negative STFT (rich condition)
        When: Evaluated at caution level
        Then: Message identifies rich condition
        """
        result = evaluateSTFT(-7, stftThresholds)
        assert "rich" in result.message.lower()

    def test_evaluateSTFT_positiveDanger_usesLeanDangerMessage(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: Large positive STFT (lean danger)
        When: Evaluated at danger level
        Then: Message includes lean-specific causes
        """
        result = evaluateSTFT(20, stftThresholds)
        assert "vacuum leak" in result.message.lower()

    def test_evaluateSTFT_negativeDanger_usesRichDangerMessage(
        self, stftThresholds: STFTThresholds
    ) -> None:
        """
        Given: Large negative STFT (rich danger)
        When: Evaluated at danger level
        Then: Message includes rich-specific causes
        """
        result = evaluateSTFT(-20, stftThresholds)
        assert "fuel pressure" in result.message.lower() or "injector" in result.message.lower()


# ================================================================================
# Config Loading Tests
# ================================================================================


class TestLoadSTFTThresholds:
    """Tests for loading STFT thresholds from obd_config.json."""

    def test_loadFromConfig_validConfig_returnsThresholds(
        self, sampleSTFTConfig: dict[str, Any]
    ) -> None:
        """
        Given: Valid config with tieredThresholds.stft section
        When: loadSTFTThresholds called
        Then: Returns STFTThresholds with correct values
        """
        thresholds = loadSTFTThresholds(sampleSTFTConfig)

        assert thresholds.cautionMin == 5
        assert thresholds.dangerMin == 15
        assert thresholds.unit == "percent"

    def test_loadFromConfig_messagesPreserved(
        self, sampleSTFTConfig: dict[str, Any]
    ) -> None:
        """
        Given: Config with custom messages
        When: loadSTFTThresholds called
        Then: All four message templates preserved
        """
        thresholds = loadSTFTThresholds(sampleSTFTConfig)

        assert "{value}" in thresholds.cautionMessageLean
        assert "{value}" in thresholds.cautionMessageRich
        assert "{value}" in thresholds.dangerMessageLean
        assert "{value}" in thresholds.dangerMessageRich

    def test_loadFromConfig_missingSection_raisesError(self) -> None:
        """
        Given: Config without tieredThresholds section
        When: loadSTFTThresholds called
        Then: Raises AlertConfigurationError
        """
        from src.pi.alert.exceptions import AlertConfigurationError

        with pytest.raises(AlertConfigurationError):
            loadSTFTThresholds({})

    def test_loadFromConfig_missingSTFT_raisesError(self) -> None:
        """
        Given: Config with tieredThresholds but no stft
        When: loadSTFTThresholds called
        Then: Raises AlertConfigurationError
        """
        from src.pi.alert.exceptions import AlertConfigurationError

        config: dict[str, Any] = {"tieredThresholds": {}}
        with pytest.raises(AlertConfigurationError):
            loadSTFTThresholds(config)

    def test_thresholdsFromConfig_notHardcoded(self) -> None:
        """
        Given: Config with custom threshold values
        When: Loaded and used for evaluation
        Then: Evaluation uses config values, not hardcoded defaults
        """
        customConfig: dict[str, Any] = {
            "tieredThresholds": {
                "stft": {
                    "unit": "percent",
                    "cautionMin": 8,
                    "dangerMin": 20,
                    "cautionMessageLean": "Custom lean caution ({value}%).",
                    "cautionMessageRich": "Custom rich caution ({value}%).",
                    "dangerMessageLean": "Custom lean danger ({value}%).",
                    "dangerMessageRich": "Custom rich danger ({value}%).",
                }
            }
        }
        thresholds = loadSTFTThresholds(customConfig)

        normalResult = evaluateSTFT(6, thresholds)
        assert normalResult.severity == AlertSeverity.NORMAL

        cautionResult = evaluateSTFT(10, thresholds)
        assert cautionResult.severity == AlertSeverity.CAUTION
        assert "Custom lean caution" in cautionResult.message

    def test_liveConfig_hasSTFTThresholds(self) -> None:
        """
        Given: The actual obd_config.json file
        When: Loaded
        Then: Contains tieredThresholds.stft with all required fields
        """
        configPath = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "src", "obd_config.json"
        )
        with open(configPath) as f:
            config = json.load(f)

        thresholds = loadSTFTThresholds(config)

        assert thresholds.cautionMin == 5
        assert thresholds.dangerMin == 15
        assert thresholds.unit == "percent"
        assert "{value}" in thresholds.cautionMessageLean
        assert "{value}" in thresholds.cautionMessageRich
        assert "{value}" in thresholds.dangerMessageLean
        assert "{value}" in thresholds.dangerMessageRich
