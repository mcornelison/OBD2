################################################################################
# File Name: test_battery_voltage_thresholds.py
# Purpose/Description: Tests for battery voltage tiered threshold evaluation (US-111)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-111
# ================================================================================
################################################################################

"""
Tests for battery voltage tiered threshold evaluation.

Validates battery voltage thresholds with 3 levels (engine running):
Normal (13.5-14.5V), Caution (12.5-13.5V or 14.5-14.8V),
Danger (<12.0V or >15.0V).

Battery voltage is bidirectional: both too-low and too-high readings
indicate problems. Messages distinguish low-voltage (alternator/charging)
from high-voltage (regulator) conditions.

Boundary values from acceptance criteria:
Low side: 11.9=danger, 12.0=danger, 12.4=caution, 12.5=caution,
13.4=caution, 13.5=normal, 14.0=normal, 14.5=normal
High side: 14.6=caution, 14.8=caution, 14.9=caution, 15.0=caution,
15.1=danger

Usage:
    pytest tests/test_battery_voltage_thresholds.py -v
"""

import json
import os
from typing import Any

import pytest

from src.alert.tiered_thresholds import (
    AlertSeverity,
    BatteryVoltageThresholds,
    evaluateBatteryVoltage,
    loadBatteryVoltageThresholds,
)

# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture
def batteryThresholds() -> BatteryVoltageThresholds:
    """
    Provide standard battery voltage thresholds matching obd_config.json.

    Returns:
        BatteryVoltageThresholds with charging system boundaries
    """
    return BatteryVoltageThresholds(
        normalMin=13.5,
        normalMax=14.5,
        cautionLowMin=12.5,
        cautionHighMax=15.0,
        dangerLowMax=12.0,
        dangerHighMin=15.0,
        unit="volts",
        cautionMessageLow=(
            "Battery voltage low ({value}V). "
            "Weak alternator output. Monitor charging system."
        ),
        cautionMessageHigh=(
            "Battery voltage high ({value}V). "
            "Voltage regulator starting to fail. Monitor closely."
        ),
        dangerMessageLow=(
            "DANGER: Battery voltage critical ({value}V). "
            "Charging system failure. Engine may stall. "
            "Check alternator and belt."
        ),
        dangerMessageHigh=(
            "DANGER: Battery voltage excessive ({value}V). "
            "Voltage regulator failed. Risk of damage to "
            "battery and electronics."
        ),
    )


@pytest.fixture
def sampleConfig() -> dict[str, Any]:
    """
    Provide sample config with tieredThresholds.batteryVoltage section.

    Returns:
        Config dict with batteryVoltage thresholds
    """
    return {
        "tieredThresholds": {
            "batteryVoltage": {
                "unit": "volts",
                "normalMin": 13.5,
                "normalMax": 14.5,
                "cautionLowMin": 12.5,
                "cautionHighMax": 15.0,
                "dangerLowMax": 12.0,
                "dangerHighMin": 15.0,
                "cautionMessageLow": (
                    "Battery voltage low ({value}V). "
                    "Weak alternator output. Monitor charging system."
                ),
                "cautionMessageHigh": (
                    "Battery voltage high ({value}V). "
                    "Voltage regulator starting to fail. Monitor closely."
                ),
                "dangerMessageLow": (
                    "DANGER: Battery voltage critical ({value}V). "
                    "Charging system failure. Engine may stall. "
                    "Check alternator and belt."
                ),
                "dangerMessageHigh": (
                    "DANGER: Battery voltage excessive ({value}V). "
                    "Voltage regulator failed. Risk of damage to "
                    "battery and electronics."
                ),
            }
        }
    }


# ================================================================================
# Danger Low Tests (< 12.0V)
# ================================================================================


class TestDangerLow:
    """Tests for danger-low voltage conditions (charging failure)."""

    def test_evaluateBatteryVoltage_belowDangerLow_returnsDanger(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 11.9V (below 12.0V danger threshold)
        When: evaluateBatteryVoltage is called
        Then: Returns DANGER severity with low-voltage message
        """
        result = evaluateBatteryVoltage(11.9, batteryThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True
        assert "11.9" in result.message
        assert "Charging system failure" in result.message
        assert result.parameterName == "BATTERY_VOLTAGE"

    def test_evaluateBatteryVoltage_atDangerLowBoundary_returnsDanger(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at exactly 12.0V (at danger boundary)
        When: evaluateBatteryVoltage is called
        Then: Returns DANGER severity (boundary inclusive for danger)
        """
        result = evaluateBatteryVoltage(12.0, batteryThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True

    def test_evaluateBatteryVoltage_extremeLow_returnsDanger(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 9.0V (extremely low - dead battery)
        When: evaluateBatteryVoltage is called
        Then: Returns DANGER severity
        """
        result = evaluateBatteryVoltage(9.0, batteryThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"


# ================================================================================
# Caution Low Tests (12.5V - 13.5V, exclusive of normalMin)
# ================================================================================


class TestCautionLow:
    """Tests for caution-low voltage conditions (weak alternator)."""

    def test_evaluateBatteryVoltage_atCautionLowMin_returnsCaution(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 12.5V (at caution low boundary)
        When: evaluateBatteryVoltage is called
        Then: Returns CAUTION severity with low-voltage message
        """
        result = evaluateBatteryVoltage(12.5, batteryThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True
        assert "12.5" in result.message
        assert "Weak alternator" in result.message

    def test_evaluateBatteryVoltage_midCautionLow_returnsCaution(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 13.0V (middle of caution-low range)
        When: evaluateBatteryVoltage is called
        Then: Returns CAUTION severity
        """
        result = evaluateBatteryVoltage(13.0, batteryThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluateBatteryVoltage_justBelowNormal_returnsCaution(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 13.4V (just below normal 13.5V)
        When: evaluateBatteryVoltage is called
        Then: Returns CAUTION severity
        """
        result = evaluateBatteryVoltage(13.4, batteryThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"

    def test_evaluateBatteryVoltage_gapBetweenDangerAndCaution_returnsCaution(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 12.4V (between danger 12.0V and caution 12.5V)
        When: evaluateBatteryVoltage is called
        Then: Returns CAUTION severity (gap treated as caution-low)
        """
        result = evaluateBatteryVoltage(12.4, batteryThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"


# ================================================================================
# Normal Tests (13.5V - 14.5V)
# ================================================================================


class TestNormal:
    """Tests for normal voltage conditions (healthy charging)."""

    def test_evaluateBatteryVoltage_atNormalMin_returnsNormal(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 13.5V (at normal minimum boundary)
        When: evaluateBatteryVoltage is called
        Then: Returns NORMAL severity
        """
        result = evaluateBatteryVoltage(13.5, batteryThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False
        assert result.parameterName == "BATTERY_VOLTAGE"

    def test_evaluateBatteryVoltage_midNormal_returnsNormal(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 14.0V (middle of normal range)
        When: evaluateBatteryVoltage is called
        Then: Returns NORMAL severity
        """
        result = evaluateBatteryVoltage(14.0, batteryThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False

    def test_evaluateBatteryVoltage_atNormalMax_returnsNormal(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 14.5V (at normal maximum boundary)
        When: evaluateBatteryVoltage is called
        Then: Returns NORMAL severity (boundary inclusive)
        """
        result = evaluateBatteryVoltage(14.5, batteryThresholds)

        assert result.severity == AlertSeverity.NORMAL
        assert result.indicator == "green"
        assert result.shouldLog is False


# ================================================================================
# Caution High Tests (14.5V - 15.0V, exclusive of normalMax)
# ================================================================================


class TestCautionHigh:
    """Tests for caution-high voltage conditions (regulator issue)."""

    def test_evaluateBatteryVoltage_justAboveNormal_returnsCaution(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 14.6V (just above normal 14.5V)
        When: evaluateBatteryVoltage is called
        Then: Returns CAUTION severity with high-voltage message
        """
        result = evaluateBatteryVoltage(14.6, batteryThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True
        assert "14.6" in result.message
        assert "regulator" in result.message.lower()

    def test_evaluateBatteryVoltage_atCautionHighMax_returnsCaution(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 14.8V (within caution-high range)
        When: evaluateBatteryVoltage is called
        Then: Returns CAUTION severity
        """
        result = evaluateBatteryVoltage(14.8, batteryThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"
        assert result.shouldLog is True

    def test_evaluateBatteryVoltage_gapBetweenCautionAndDangerHigh_returnsCaution(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 14.9V (between caution 14.8V and danger 15.0V)
        When: evaluateBatteryVoltage is called
        Then: Returns CAUTION severity (gap treated as caution-high)
        """
        result = evaluateBatteryVoltage(14.9, batteryThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"

    def test_evaluateBatteryVoltage_atDangerHighBoundary_returnsCaution(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at exactly 15.0V (at danger-high boundary)
        When: evaluateBatteryVoltage is called
        Then: Returns CAUTION severity (boundary exclusive for danger-high)
        """
        result = evaluateBatteryVoltage(15.0, batteryThresholds)

        assert result.severity == AlertSeverity.CAUTION
        assert result.indicator == "yellow"


# ================================================================================
# Danger High Tests (> 15.0V)
# ================================================================================


class TestDangerHigh:
    """Tests for danger-high voltage conditions (regulator failed)."""

    def test_evaluateBatteryVoltage_aboveDangerHigh_returnsDanger(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 15.1V (above 15.0V danger threshold)
        When: evaluateBatteryVoltage is called
        Then: Returns DANGER severity with high-voltage message
        """
        result = evaluateBatteryVoltage(15.1, batteryThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True
        assert "15.1" in result.message
        assert "regulator failed" in result.message.lower()
        assert result.parameterName == "BATTERY_VOLTAGE"

    def test_evaluateBatteryVoltage_extremeHigh_returnsDanger(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: Voltage at 16.5V (extremely high - runaway regulator)
        When: evaluateBatteryVoltage is called
        Then: Returns DANGER severity
        """
        result = evaluateBatteryVoltage(16.5, batteryThresholds)

        assert result.severity == AlertSeverity.DANGER
        assert result.indicator == "red"
        assert result.shouldLog is True


# ================================================================================
# Alert Log Entry Tests
# ================================================================================


class TestAlertLogEntry:
    """Tests for alert log entry generation from battery voltage results."""

    def test_toLogEntry_dangerLow_containsRequiredFields(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: A DANGER result from low voltage
        When: toLogEntry is called
        Then: Log entry contains severity, parameterName, value, message
        """
        result = evaluateBatteryVoltage(11.5, batteryThresholds)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "danger"
        assert logEntry["parameterName"] == "BATTERY_VOLTAGE"
        assert logEntry["value"] == 11.5
        assert "11.5" in logEntry["message"]

    def test_toLogEntry_cautionHigh_containsRequiredFields(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: A CAUTION result from high voltage
        When: toLogEntry is called
        Then: Log entry contains severity, parameterName, value, message
        """
        result = evaluateBatteryVoltage(14.7, batteryThresholds)
        logEntry = result.toLogEntry()

        assert logEntry["severity"] == "caution"
        assert logEntry["parameterName"] == "BATTERY_VOLTAGE"
        assert logEntry["value"] == 14.7

    def test_normalResult_shouldNotLog(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: A NORMAL result
        When: shouldLog is checked
        Then: shouldLog is False
        """
        result = evaluateBatteryVoltage(14.0, batteryThresholds)

        assert result.shouldLog is False


# ================================================================================
# Config Loading Tests
# ================================================================================


class TestLoadBatteryVoltageThresholds:
    """Tests for loading battery voltage thresholds from config."""

    def test_loadBatteryVoltageThresholds_validConfig_returnsThresholds(
        self, sampleConfig: dict[str, Any]
    ) -> None:
        """
        Given: Valid config with tieredThresholds.batteryVoltage
        When: loadBatteryVoltageThresholds is called
        Then: Returns BatteryVoltageThresholds with correct values
        """
        thresholds = loadBatteryVoltageThresholds(sampleConfig)

        assert thresholds.normalMin == 13.5
        assert thresholds.normalMax == 14.5
        assert thresholds.cautionLowMin == 12.5
        assert thresholds.dangerLowMax == 12.0
        assert thresholds.dangerHighMin == 15.0
        assert thresholds.unit == "volts"

    def test_loadBatteryVoltageThresholds_missingTiered_raisesError(
        self,
    ) -> None:
        """
        Given: Config missing tieredThresholds section
        When: loadBatteryVoltageThresholds is called
        Then: Raises AlertConfigurationError
        """
        from src.alert.exceptions import AlertConfigurationError

        with pytest.raises(AlertConfigurationError):
            loadBatteryVoltageThresholds({})

    def test_loadBatteryVoltageThresholds_missingBatteryVoltage_raisesError(
        self,
    ) -> None:
        """
        Given: Config with tieredThresholds but missing batteryVoltage
        When: loadBatteryVoltageThresholds is called
        Then: Raises AlertConfigurationError
        """
        from src.alert.exceptions import AlertConfigurationError

        config: dict[str, Any] = {"tieredThresholds": {}}
        with pytest.raises(AlertConfigurationError):
            loadBatteryVoltageThresholds(config)

    def test_loadBatteryVoltageThresholds_defaultMessages_usedWhenNotInConfig(
        self,
    ) -> None:
        """
        Given: Config without custom messages
        When: loadBatteryVoltageThresholds is called
        Then: Default messages are used
        """
        config: dict[str, Any] = {
            "tieredThresholds": {
                "batteryVoltage": {
                    "normalMin": 13.5,
                    "normalMax": 14.5,
                    "cautionLowMin": 12.5,
                    "cautionHighMax": 15.0,
                    "dangerLowMax": 12.0,
                    "dangerHighMin": 15.0,
                }
            }
        }
        thresholds = loadBatteryVoltageThresholds(config)

        assert "{value}" in thresholds.cautionMessageLow
        assert "{value}" in thresholds.dangerMessageHigh

    def test_loadBatteryVoltageThresholds_fromActualConfig_loadsSuccessfully(
        self,
    ) -> None:
        """
        Given: The actual obd_config.json file
        When: loadBatteryVoltageThresholds is called
        Then: Loads without error
        """
        configPath = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "src",
            "obd_config.json",
        )
        with open(configPath) as f:
            config = json.load(f)

        thresholds = loadBatteryVoltageThresholds(config)

        assert thresholds.normalMin == 13.5
        assert thresholds.normalMax == 14.5


# ================================================================================
# Message Distinction Tests
# ================================================================================


class TestMessageDistinction:
    """Tests verifying alert messages distinguish low from high conditions."""

    def test_cautionLow_messageIndicatesLowVoltage(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: A caution-low voltage reading
        When: evaluateBatteryVoltage is called
        Then: Message references weak alternator / low voltage
        """
        result = evaluateBatteryVoltage(13.0, batteryThresholds)

        assert "low" in result.message.lower() or "alternator" in result.message.lower()

    def test_cautionHigh_messageIndicatesHighVoltage(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: A caution-high voltage reading
        When: evaluateBatteryVoltage is called
        Then: Message references regulator / high voltage
        """
        result = evaluateBatteryVoltage(14.7, batteryThresholds)

        assert (
            "high" in result.message.lower()
            or "regulator" in result.message.lower()
        )

    def test_dangerLow_messageIndicatesChargingFailure(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: A danger-low voltage reading
        When: evaluateBatteryVoltage is called
        Then: Message references charging failure / stall risk
        """
        result = evaluateBatteryVoltage(11.0, batteryThresholds)

        assert "charging" in result.message.lower() or "stall" in result.message.lower()

    def test_dangerHigh_messageIndicatesRegulatorFailure(
        self, batteryThresholds: BatteryVoltageThresholds
    ) -> None:
        """
        Given: A danger-high voltage reading
        When: evaluateBatteryVoltage is called
        Then: Message references regulator failure / damage risk
        """
        result = evaluateBatteryVoltage(16.0, batteryThresholds)

        assert (
            "regulator" in result.message.lower()
            or "damage" in result.message.lower()
        )
