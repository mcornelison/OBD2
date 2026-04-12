################################################################################
# File Name: test_rpm_thresholds.py
# Purpose/Description: Tests for RPM tiered threshold evaluation (US-110)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-110
# ================================================================================
################################################################################

"""
Tests for RPM tiered threshold evaluation system.

Validates engine RPM tiered thresholds with 4 levels:
Low Idle (<600), Normal (600-6500), Caution (>6500-7000), Danger (>7000).

Boundary values from acceptance criteria:
599=low_idle, 600=normal, 6500=normal, 6501=caution,
7000=caution, 7001=danger.

Usage:
    pytest tests/test_rpm_thresholds.py -v
"""

import json
import os
from typing import Any

import pytest

from src.alert.tiered_thresholds import (
    AlertSeverity,
    RPMThresholds,
    evaluateRPM,
    loadRPMThresholds,
)

# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture
def rpmThresholds() -> RPMThresholds:
    """
    Provide standard RPM thresholds matching obd_config.json.

    Returns:
        RPMThresholds with 4G63 stock values
    """
    return RPMThresholds(
        normalMin=600,
        cautionMin=6500,
        dangerMin=7000,
        unit="rpm",
        lowIdleMessage=(
            "Idle RPM too low ({value} RPM). "
            "Possible vacuum leak or IAC issue."
        ),
        cautionMessage=(
            "High RPM warning ({value} RPM). Stock redline approaching."
        ),
        dangerMessage=(
            "DANGER: Over-rev ({value} RPM). "
            "Valve float risk on stock springs."
        ),
    )


@pytest.fixture
def sampleConfig() -> dict[str, Any]:
    """
    Provide sample config with tieredThresholds.rpm section.

    Returns:
        Config dict with rpm thresholds
    """
    return {
        "tieredThresholds": {
            "rpm": {
                "unit": "rpm",
                "normalMin": 600,
                "cautionMin": 6500,
                "dangerMin": 7000,
                "lowIdleMessage": (
                    "Idle RPM too low ({value} RPM). "
                    "Possible vacuum leak or IAC issue."
                ),
                "cautionMessage": (
                    "High RPM warning ({value} RPM). "
                    "Stock redline approaching."
                ),
                "dangerMessage": (
                    "DANGER: Over-rev ({value} RPM). "
                    "Valve float risk on stock springs."
                ),
            }
        }
    }


# ================================================================================
# Low Idle Threshold Tests (<600 RPM)
# ================================================================================


class TestRPMLowIdle:
    """Tests for Low Idle level: RPM below minimum idle threshold."""

    def test_evaluateRPM_599_returnsLowIdle(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 599 (just below normal idle)
        When: Evaluated against thresholds
        Then: Returns info severity with blue indicator
        """
        result = evaluateRPM(599, rpmThresholds)

        assert result.severity == AlertSeverity.INFO
        assert result.indicator == "blue"
        assert result.shouldLog is True

    def test_evaluateRPM_0_returnsLowIdle(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 0 (engine off or stalled)
        When: Evaluated against thresholds
        Then: Returns info severity
        """
        result = evaluateRPM(0, rpmThresholds)

        assert result.severity == AlertSeverity.INFO
        assert result.indicator == "blue"

    def test_evaluateRPM_400_returnsLowIdle(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 400 (very low idle)
        When: Evaluated against thresholds
        Then: Returns info severity
        """
        result = evaluateRPM(400, rpmThresholds)

        assert result.severity == AlertSeverity.INFO

    def test_evaluateRPM_lowIdle_messageFormat(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 599 (low idle)
        When: Evaluated against thresholds
        Then: Message mentions vacuum leak or IAC
        """
        result = evaluateRPM(599, rpmThresholds)

        assert "599" in result.message
        assert "vacuum leak" in result.message or "IAC" in result.message

    def test_evaluateRPM_lowIdle_shouldLog(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at low idle level
        When: Evaluated against thresholds
        Then: shouldLog is True (potential issue worth logging)
        """
        result = evaluateRPM(500, rpmThresholds)

        assert result.shouldLog is True


# ================================================================================
# Normal Threshold Tests (600-6500 RPM)
# ================================================================================


class TestRPMNormal:
    """Tests for Normal level: healthy operating RPM range."""

    def test_evaluateRPM_600_returnsNormal(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 600 (lower normal boundary)
        When: Evaluated against thresholds
        Then: Returns normal severity with green indicator
        """
        result = evaluateRPM(600, rpmThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False

    def test_evaluateRPM_3000_returnsNormal(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 3000 (mid-range normal)
        When: Evaluated against thresholds
        Then: Returns normal severity
        """
        result = evaluateRPM(3000, rpmThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"

    def test_evaluateRPM_6500_returnsNormal(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 6500 (upper normal boundary)
        When: Evaluated against thresholds
        Then: Returns normal severity (not caution)
        """
        result = evaluateRPM(6500, rpmThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False

    def test_evaluateRPM_normal_noLogEntry(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at normal level
        When: Evaluated against thresholds
        Then: shouldLog is False
        """
        result = evaluateRPM(3500, rpmThresholds)

        assert result.shouldLog is False


# ================================================================================
# Caution Threshold Tests (>6500-7000 RPM)
# ================================================================================


class TestRPMCaution:
    """Tests for Caution level: high RPM approaching redline."""

    def test_evaluateRPM_6501_returnsCaution(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 6501 (just above normal)
        When: Evaluated against thresholds
        Then: Returns caution severity with yellow indicator
        """
        result = evaluateRPM(6501, rpmThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluateRPM_7000_returnsCaution(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 7000 (upper caution boundary, == dangerMin)
        When: Evaluated against thresholds
        Then: Returns caution severity (boundary stays in lower level)
        """
        result = evaluateRPM(7000, rpmThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluateRPM_caution_messageFormat(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 6501 (caution)
        When: Evaluated against thresholds
        Then: Message mentions redline approaching
        """
        result = evaluateRPM(6501, rpmThresholds)

        assert "6501" in result.message
        assert "redline" in result.message.lower()


# ================================================================================
# Danger Threshold Tests (>7000 RPM)
# ================================================================================


class TestRPMDanger:
    """Tests for Danger level: over-rev territory."""

    def test_evaluateRPM_7001_returnsDanger(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 7001 (just above dangerMin boundary)
        When: Evaluated against thresholds
        Then: Returns danger severity with red indicator
        """
        result = evaluateRPM(7001, rpmThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True

    def test_evaluateRPM_7200_returnsDanger(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 7200 (previously caution, now danger with dangerMin=7000)
        When: Evaluated against thresholds
        Then: Returns danger severity
        """
        result = evaluateRPM(7200, rpmThresholds)

        assert result.severity == AlertSeverity.DANGER

    def test_evaluateRPM_8000_returnsDanger(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 8000 (extreme over-rev)
        When: Evaluated against thresholds
        Then: Returns danger severity
        """
        result = evaluateRPM(8000, rpmThresholds)

        assert result.severity == AlertSeverity.DANGER

    def test_evaluateRPM_danger_messageFormat(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at 7001 (danger)
        When: Evaluated against thresholds
        Then: Message mentions valve float risk
        """
        result = evaluateRPM(7001, rpmThresholds)

        assert "7001" in result.message
        assert "valve float" in result.message.lower()


# ================================================================================
# Alert Log Entry Tests
# ================================================================================


class TestRPMAlertLog:
    """Tests for alert log entry creation at various levels."""

    def test_evaluateRPM_lowIdle_createsLogEntry(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at low idle level
        When: Evaluated against thresholds
        Then: shouldLog is True with info severity
        """
        result = evaluateRPM(500, rpmThresholds)

        assert result.shouldLog is True
        assert result.severity == AlertSeverity.INFO

    def test_evaluateRPM_caution_createsLogEntry(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at caution level
        When: Evaluated against thresholds
        Then: shouldLog is True with caution severity
        """
        result = evaluateRPM(6800, rpmThresholds)

        assert result.shouldLog is True
        assert result.severity == AlertSeverity.CAUTION
        assert "6800" in result.message

    def test_evaluateRPM_danger_createsLogEntry(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at danger level
        When: Evaluated against thresholds
        Then: shouldLog is True with danger severity
        """
        result = evaluateRPM(7500, rpmThresholds)

        assert result.shouldLog is True
        assert result.severity == AlertSeverity.DANGER
        assert "7500" in result.message

    def test_evaluateRPM_caution_logEntry_format(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at caution level
        When: Alert log entry dict is generated
        Then: Contains severity, parameterName, value, message
        """
        result = evaluateRPM(6800, rpmThresholds)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "caution"
        assert logEntry["parameterName"] == "RPM"
        assert logEntry["value"] == 6800
        assert "message" in logEntry

    def test_evaluateRPM_danger_logEntry_format(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: RPM at danger level
        When: Alert log entry dict is generated
        Then: Contains severity=danger and valve float message
        """
        result = evaluateRPM(7500, rpmThresholds)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "danger"
        assert logEntry["parameterName"] == "RPM"
        assert logEntry["value"] == 7500
        assert "valve float" in logEntry["message"].lower()


# ================================================================================
# Result Object Tests
# ================================================================================


class TestRPMResultObject:
    """Tests for TieredThresholdResult from RPM evaluation."""

    def test_resultContainsAllFields(
        self, rpmThresholds: RPMThresholds
    ) -> None:
        """
        Given: Any RPM evaluation
        When: Result returned
        Then: Contains parameterName, severity, value, message, indicator
        """
        result = evaluateRPM(3000, rpmThresholds)

        assert result.parameterName == "RPM"
        assert result.value == 3000
        assert isinstance(result.severity, AlertSeverity)
        assert isinstance(result.indicator, str)
        assert isinstance(result.message, str)


# ================================================================================
# Config Loading Tests
# ================================================================================


class TestLoadRPMThresholds:
    """Tests for loading RPM thresholds from obd_config.json."""

    def test_loadFromConfig_validConfig_returnsThresholds(
        self, sampleConfig: dict[str, Any]
    ) -> None:
        """
        Given: Valid config with tieredThresholds.rpm section
        When: loadRPMThresholds called
        Then: Returns RPMThresholds with correct values
        """
        thresholds = loadRPMThresholds(sampleConfig)

        assert thresholds.normalMin == 600
        assert thresholds.cautionMin == 6500
        assert thresholds.dangerMin == 7000
        assert thresholds.unit == "rpm"

    def test_loadFromConfig_messagesPreserved(
        self, sampleConfig: dict[str, Any]
    ) -> None:
        """
        Given: Config with custom messages
        When: loadRPMThresholds called
        Then: Messages match config values with {value} placeholder
        """
        thresholds = loadRPMThresholds(sampleConfig)

        assert "{value}" in thresholds.lowIdleMessage
        assert "{value}" in thresholds.cautionMessage
        assert "{value}" in thresholds.dangerMessage

    def test_loadFromConfig_missingSection_raisesError(self) -> None:
        """
        Given: Config without tieredThresholds section
        When: loadRPMThresholds called
        Then: Raises AlertConfigurationError
        """
        from src.alert.exceptions import AlertConfigurationError

        with pytest.raises(AlertConfigurationError):
            loadRPMThresholds({})

    def test_loadFromConfig_missingRpm_raisesError(self) -> None:
        """
        Given: Config with tieredThresholds but no rpm
        When: loadRPMThresholds called
        Then: Raises AlertConfigurationError
        """
        from src.alert.exceptions import AlertConfigurationError

        config: dict[str, Any] = {"tieredThresholds": {}}
        with pytest.raises(AlertConfigurationError):
            loadRPMThresholds(config)

    def test_thresholdsFromConfig_notHardcoded(self) -> None:
        """
        Given: Config with custom threshold values
        When: Loaded and used for evaluation
        Then: Evaluation uses config values, not hardcoded defaults
        """
        customConfig: dict[str, Any] = {
            "tieredThresholds": {
                "rpm": {
                    "unit": "rpm",
                    "normalMin": 700,
                    "cautionMin": 6000,
                    "dangerMin": 7000,
                    "lowIdleMessage": "Custom low idle ({value} RPM).",
                    "cautionMessage": "Custom caution ({value} RPM).",
                    "dangerMessage": "Custom danger ({value} RPM).",
                }
            }
        }
        thresholds = loadRPMThresholds(customConfig)
        result = evaluateRPM(650, thresholds)

        assert result.severity == AlertSeverity.INFO
        assert "Custom low idle" in result.message

    def test_liveConfig_hasRpmThresholds(self) -> None:
        """
        Given: The actual obd_config.json file
        When: Loaded
        Then: Contains tieredThresholds.rpm with all required fields
        """
        configPath = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "src", "obd_config.json"
        )
        with open(configPath) as f:
            config = json.load(f)

        thresholds = loadRPMThresholds(config)

        assert thresholds.normalMin == 600
        assert thresholds.cautionMin == 6500
        assert thresholds.dangerMin == 7000
        assert thresholds.unit == "rpm"
        assert "{value}" in thresholds.lowIdleMessage
        assert "{value}" in thresholds.cautionMessage
        assert "{value}" in thresholds.dangerMessage
