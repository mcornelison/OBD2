################################################################################
# File Name: test_tiered_thresholds.py
# Purpose/Description: Tests for tiered threshold evaluation system (US-107)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-107
# ================================================================================
################################################################################

"""
Tests for tiered threshold evaluation system.

Validates coolant temperature tiered thresholds with 4 levels:
Cold (<180F), Normal (180-210F), Caution (>210-220F), Danger (>220F).

Boundary values from acceptance criteria:
159F=cold, 160F=cold, 179F=cold, 180F=normal, 210F=normal,
211F=caution, 220F=caution, 221F=danger.

Usage:
    pytest tests/test_tiered_thresholds.py -v
"""

import json
import os
from typing import Any

import pytest

from src.alert.tiered_thresholds import (
    AlertSeverity,
    CoolantTempThresholds,
    evaluateCoolantTemp,
    loadCoolantTempThresholds,
)

# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture
def coolantThresholds() -> CoolantTempThresholds:
    """
    Provide standard coolant temp thresholds matching obd_config.json.

    Returns:
        CoolantTempThresholds with 4G63 values
    """
    return CoolantTempThresholds(
        normalMin=180,
        cautionMin=210,
        dangerMin=220,
        unit="fahrenheit",
        cautionMessage="Coolant temperature elevated ({value}F). Monitor closely.",
        dangerMessage=(
            "DANGER: Coolant temperature critical ({value}F). "
            "Risk of head gasket failure. Reduce load immediately."
        ),
    )


@pytest.fixture
def sampleConfig() -> dict[str, Any]:
    """
    Provide sample config with tieredThresholds section.

    Returns:
        Config dict with coolantTemp thresholds
    """
    return {
        "tieredThresholds": {
            "coolantTemp": {
                "unit": "fahrenheit",
                "normalMin": 180,
                "cautionMin": 210,
                "dangerMin": 220,
                "cautionMessage": (
                    "Coolant temperature elevated ({value}F). Monitor closely."
                ),
                "dangerMessage": (
                    "DANGER: Coolant temperature critical ({value}F). "
                    "Risk of head gasket failure. Reduce load immediately."
                ),
            }
        }
    }


# ================================================================================
# Cold Threshold Tests (<180F)
# ================================================================================


class TestCoolantTempCold:
    """Tests for Cold level: below operating temperature."""

    def test_evaluateCoolantTemp_159F_returnsCold(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 159F
        When: Evaluated against thresholds
        Then: Returns cold severity with blue indicator
        """
        result = evaluateCoolantTemp(159, coolantThresholds)

        assert result.severity == AlertSeverity.INFO
        assert result.indicator == "blue"
        assert result.shouldLog is False

    def test_evaluateCoolantTemp_160F_returnsCold(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 160F
        When: Evaluated against thresholds
        Then: Returns cold severity
        """
        result = evaluateCoolantTemp(160, coolantThresholds)

        assert result.severity == AlertSeverity.INFO
        assert result.indicator == "blue"
        assert result.shouldLog is False

    def test_evaluateCoolantTemp_179F_returnsCold(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 179F (just below normal)
        When: Evaluated against thresholds
        Then: Returns cold severity
        """
        result = evaluateCoolantTemp(179, coolantThresholds)

        assert result.severity == AlertSeverity.INFO
        assert result.indicator == "blue"
        assert result.shouldLog is False

    def test_evaluateCoolantTemp_0F_returnsCold(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 0F (extreme cold)
        When: Evaluated against thresholds
        Then: Returns cold severity
        """
        result = evaluateCoolantTemp(0, coolantThresholds)

        assert result.severity == AlertSeverity.INFO


# ================================================================================
# Normal Threshold Tests (180-210F)
# ================================================================================


class TestCoolantTempNormal:
    """Tests for Normal level: operating temperature."""

    def test_evaluateCoolantTemp_180F_returnsNormal(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 180F (lower normal boundary)
        When: Evaluated against thresholds
        Then: Returns normal severity with green indicator
        """
        result = evaluateCoolantTemp(180, coolantThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False

    def test_evaluateCoolantTemp_195F_returnsNormal(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 195F (mid-range normal)
        When: Evaluated against thresholds
        Then: Returns normal severity
        """
        result = evaluateCoolantTemp(195, coolantThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"

    def test_evaluateCoolantTemp_210F_returnsNormal(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 210F (upper normal boundary)
        When: Evaluated against thresholds
        Then: Returns normal severity
        """
        result = evaluateCoolantTemp(210, coolantThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False


# ================================================================================
# Caution Threshold Tests (>210-220F)
# ================================================================================


class TestCoolantTempCaution:
    """Tests for Caution level: elevated temperature."""

    def test_evaluateCoolantTemp_211F_returnsCaution(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 211F (just above normal)
        When: Evaluated against thresholds
        Then: Returns caution severity with yellow indicator
        """
        result = evaluateCoolantTemp(211, coolantThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluateCoolantTemp_215F_returnsCaution(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 215F (mid-range caution)
        When: Evaluated against thresholds
        Then: Returns caution severity
        """
        result = evaluateCoolantTemp(215, coolantThresholds)

        assert result.severity == AlertSeverity.CAUTION

    def test_evaluateCoolantTemp_220F_returnsCaution(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 220F (upper caution boundary)
        When: Evaluated against thresholds
        Then: Returns caution severity (not danger)
        """
        result = evaluateCoolantTemp(220, coolantThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluateCoolantTemp_caution_messageFormat(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 211F (caution)
        When: Evaluated against thresholds
        Then: Message matches Spool spec format with interpolated value
        """
        result = evaluateCoolantTemp(211, coolantThresholds)

        assert result.message == (
            "Coolant temperature elevated (211F). Monitor closely."
        )


# ================================================================================
# Danger Threshold Tests (>220F)
# ================================================================================


class TestCoolantTempDanger:
    """Tests for Danger level: critical temperature."""

    def test_evaluateCoolantTemp_221F_returnsDanger(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 221F (just above caution)
        When: Evaluated against thresholds
        Then: Returns danger severity with red indicator
        """
        result = evaluateCoolantTemp(221, coolantThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True

    def test_evaluateCoolantTemp_250F_returnsDanger(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 250F (extreme danger)
        When: Evaluated against thresholds
        Then: Returns danger severity
        """
        result = evaluateCoolantTemp(250, coolantThresholds)

        assert result.severity == AlertSeverity.DANGER

    def test_evaluateCoolantTemp_danger_messageFormat(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at 221F (danger)
        When: Evaluated against thresholds
        Then: Message matches Spool spec format with interpolated value
        """
        result = evaluateCoolantTemp(221, coolantThresholds)

        assert result.message == (
            "DANGER: Coolant temperature critical (221F). "
            "Risk of head gasket failure. Reduce load immediately."
        )


# ================================================================================
# Alert Log Entry Tests
# ================================================================================


class TestCoolantTempAlertLog:
    """Tests for alert log entry creation at Caution and Danger transitions."""

    def test_evaluateCoolantTemp_cold_noLogEntry(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at cold level
        When: Evaluated against thresholds
        Then: shouldLog is False (info only, no alert log)
        """
        result = evaluateCoolantTemp(100, coolantThresholds)
        assert result.shouldLog is False

    def test_evaluateCoolantTemp_normal_noLogEntry(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at normal level
        When: Evaluated against thresholds
        Then: shouldLog is False
        """
        result = evaluateCoolantTemp(195, coolantThresholds)
        assert result.shouldLog is False

    def test_evaluateCoolantTemp_caution_createsLogEntry(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at caution level
        When: Evaluated against thresholds
        Then: shouldLog is True with severity and message
        """
        result = evaluateCoolantTemp(215, coolantThresholds)

        assert result.shouldLog is True
        assert result.severity == AlertSeverity.CAUTION
        assert "elevated" in result.message
        assert "215" in result.message

    def test_evaluateCoolantTemp_danger_createsLogEntry(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at danger level
        When: Evaluated against thresholds
        Then: shouldLog is True with severity and message
        """
        result = evaluateCoolantTemp(225, coolantThresholds)

        assert result.shouldLog is True
        assert result.severity == AlertSeverity.DANGER
        assert "critical" in result.message
        assert "225" in result.message

    def test_evaluateCoolantTemp_logEntry_hasSeverityField(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at caution level
        When: Alert log entry dict is generated
        Then: Contains severity and message fields matching Spool spec
        """
        result = evaluateCoolantTemp(215, coolantThresholds)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "caution"
        assert logEntry["parameterName"] == "COOLANT_TEMP"
        assert logEntry["value"] == 215
        assert "message" in logEntry

    def test_evaluateCoolantTemp_danger_logEntry_format(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Coolant temp at danger level
        When: Alert log entry dict is generated
        Then: Contains severity=danger and full danger message
        """
        result = evaluateCoolantTemp(225, coolantThresholds)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "danger"
        assert logEntry["parameterName"] == "COOLANT_TEMP"
        assert logEntry["value"] == 225
        assert "head gasket" in logEntry["message"]


# ================================================================================
# Result Object Tests
# ================================================================================


class TestTieredThresholdResult:
    """Tests for TieredThresholdResult dataclass."""

    def test_resultContainsAllFields(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Any coolant temp evaluation
        When: Result returned
        Then: Contains parameterName, severity, value, message, indicator
        """
        result = evaluateCoolantTemp(195, coolantThresholds)

        assert result.parameterName == "COOLANT_TEMP"
        assert result.value == 195
        assert isinstance(result.severity, AlertSeverity)
        assert isinstance(result.indicator, str)
        assert isinstance(result.message, str)

    def test_coldResult_hasInfoMessage(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Cold coolant temp
        When: Evaluated
        Then: Message indicates engine not at operating temp
        """
        result = evaluateCoolantTemp(150, coolantThresholds)

        assert "operating" in result.message.lower() or "warmup" in result.message.lower()

    def test_normalResult_hasNoActionMessage(
        self, coolantThresholds: CoolantTempThresholds
    ) -> None:
        """
        Given: Normal coolant temp
        When: Evaluated
        Then: Message indicates no action needed
        """
        result = evaluateCoolantTemp(195, coolantThresholds)

        assert result.severity == AlertSeverity.NORMAL


# ================================================================================
# Config Loading Tests
# ================================================================================


class TestLoadCoolantTempThresholds:
    """Tests for loading thresholds from obd_config.json."""

    def test_loadFromConfig_validConfig_returnsThresholds(
        self, sampleConfig: dict[str, Any]
    ) -> None:
        """
        Given: Valid config with tieredThresholds.coolantTemp section
        When: loadCoolantTempThresholds called
        Then: Returns CoolantTempThresholds with correct values
        """
        thresholds = loadCoolantTempThresholds(sampleConfig)

        assert thresholds.normalMin == 180
        assert thresholds.cautionMin == 210
        assert thresholds.dangerMin == 220
        assert thresholds.unit == "fahrenheit"

    def test_loadFromConfig_messagesPreserved(
        self, sampleConfig: dict[str, Any]
    ) -> None:
        """
        Given: Config with custom messages
        When: loadCoolantTempThresholds called
        Then: Messages match config values exactly
        """
        thresholds = loadCoolantTempThresholds(sampleConfig)

        assert "{value}" in thresholds.cautionMessage
        assert "head gasket" in thresholds.dangerMessage

    def test_loadFromConfig_missingSection_raisesError(self) -> None:
        """
        Given: Config without tieredThresholds section
        When: loadCoolantTempThresholds called
        Then: Raises AlertConfigurationError
        """
        from src.alert.exceptions import AlertConfigurationError

        with pytest.raises(AlertConfigurationError):
            loadCoolantTempThresholds({})

    def test_loadFromConfig_missingCoolantTemp_raisesError(self) -> None:
        """
        Given: Config with tieredThresholds but no coolantTemp
        When: loadCoolantTempThresholds called
        Then: Raises AlertConfigurationError
        """
        from src.alert.exceptions import AlertConfigurationError

        config: dict[str, Any] = {"tieredThresholds": {}}
        with pytest.raises(AlertConfigurationError):
            loadCoolantTempThresholds(config)

    def test_thresholdsFromConfig_notHardcoded(self) -> None:
        """
        Given: Config with custom threshold values
        When: Loaded and used for evaluation
        Then: Evaluation uses config values, not hardcoded defaults
        """
        customConfig: dict[str, Any] = {
            "tieredThresholds": {
                "coolantTemp": {
                    "unit": "fahrenheit",
                    "normalMin": 170,
                    "cautionMin": 200,
                    "dangerMin": 210,
                    "cautionMessage": "Custom caution ({value}F).",
                    "dangerMessage": "Custom danger ({value}F).",
                }
            }
        }
        thresholds = loadCoolantTempThresholds(customConfig)
        result = evaluateCoolantTemp(205, thresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert "Custom caution" in result.message

    def test_liveConfig_hasCoolantTempThresholds(self) -> None:
        """
        Given: The actual obd_config.json file
        When: Loaded
        Then: Contains tieredThresholds.coolantTemp with all required fields
        """
        configPath = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "src", "obd_config.json"
        )
        with open(configPath) as f:
            config = json.load(f)

        thresholds = loadCoolantTempThresholds(config)

        assert thresholds.normalMin == 180
        assert thresholds.cautionMin == 210
        assert thresholds.dangerMin == 220
        assert thresholds.unit == "fahrenheit"
        assert "{value}" in thresholds.cautionMessage
        assert "{value}" in thresholds.dangerMessage
