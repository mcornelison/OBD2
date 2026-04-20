################################################################################
# File Name: test_polling_tiers.py
# Purpose/Description: Tests for tiered polling configuration validation (US-136)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-136
# ================================================================================
################################################################################

"""
Tests for tiered polling configuration.

Validates that the polling tier structure matches Spool's tuning-driven
specification:
  Tier 1 (every cycle, ~1 Hz): Coolant Temp, RPM, Engine Load, Timing Advance, STFT B1
  Tier 2 (every 3 cycles, ~0.3 Hz): Throttle Position, Vehicle Speed
  Tier 3 (every 10 cycles, ~0.1 Hz): LTFT B1, Intake Air Temp, O2 Sensor B1S1
  Tier 4 (every 30 cycles, ~0.03 Hz): Control Module Voltage, Manifold Pressure (MDP)

MDP caveat: PID 0x0B is MDP (EGR-related) on 2G Eclipse, NOT true manifold pressure.

Usage:
    pytest tests/test_polling_tiers.py -v
"""

import json
import os
from typing import Any

import pytest

from pi.obdii.data.polling_tiers import (
    PollingTierConfig,
    getParametersForCycle,
    getParameterTier,
    loadPollingTiers,
    shouldPollParameter,
)

# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture
def spoolTierConfig() -> dict[str, Any]:
    """
    Provide Spool's 4-tier polling configuration.

    Returns:
        Dict matching the pollingTiers section of obd_config.json
    """
    return {
        "tier1": {
            "cycleInterval": 1,
            "description": "Safety-critical — every cycle (~1 Hz)",
            "parameters": [
                {"name": "COOLANT_TEMP", "pid": "0x05"},
                {"name": "RPM", "pid": "0x0C"},
                {"name": "ENGINE_LOAD", "pid": "0x04"},
                {"name": "TIMING_ADVANCE", "pid": "0x0E"},
                {"name": "SHORT_FUEL_TRIM_1", "pid": "0x06"},
            ],
        },
        "tier2": {
            "cycleInterval": 3,
            "description": "Driving context — every 3 cycles (~0.3 Hz)",
            "parameters": [
                {"name": "THROTTLE_POS", "pid": "0x11"},
                {"name": "SPEED", "pid": "0x0D"},
            ],
        },
        "tier3": {
            "cycleInterval": 10,
            "description": "Trend analysis — every 10 cycles (~0.1 Hz)",
            "parameters": [
                {"name": "LONG_FUEL_TRIM_1", "pid": "0x07"},
                {"name": "INTAKE_TEMP", "pid": "0x0F"},
                {"name": "O2_B1S1", "pid": "0x14"},
            ],
        },
        "tier4": {
            "cycleInterval": 30,
            "description": "Background monitoring — every 30 cycles (~0.03 Hz)",
            "parameters": [
                {
                    "name": "CONTROL_MODULE_VOLTAGE",
                    "pid": "0x42",
                },
                {
                    "name": "INTAKE_PRESSURE",
                    "pid": "0x0B",
                    "caveat": "PID 0x0B is MDP (EGR only) on 2G Eclipse, "
                    "NOT true manifold pressure — cannot be used for "
                    "boost measurement",
                },
            ],
        },
    }


@pytest.fixture
def fullConfig(spoolTierConfig: dict[str, Any]) -> dict[str, Any]:
    """
    Provide a full config dict with pollingTiers section.

    Args:
        spoolTierConfig: The polling tier config fixture

    Returns:
        Config dict suitable for loadPollingTiers()
    """
    return {"pi": {"pollingTiers": spoolTierConfig}}


@pytest.fixture
def loadedTiers(fullConfig: dict[str, Any]) -> PollingTierConfig:
    """
    Provide a loaded PollingTierConfig from the standard fixture.

    Args:
        fullConfig: Full configuration dict

    Returns:
        Parsed PollingTierConfig object
    """
    return loadPollingTiers(fullConfig)


# ================================================================================
# Config Structure Tests — validate 4-tier structure exists
# ================================================================================


class TestLoadPollingTiers:
    """Tests for loadPollingTiers function."""

    def test_loadPollingTiers_validConfig_returnsTierConfig(
        self, fullConfig: dict[str, Any]
    ) -> None:
        """
        Given: Valid config with pollingTiers section
        When: loadPollingTiers is called
        Then: Returns a PollingTierConfig with 4 tiers
        """
        result = loadPollingTiers(fullConfig)

        assert isinstance(result, PollingTierConfig)
        assert len(result.tiers) == 4

    def test_loadPollingTiers_missingSection_raisesKeyError(self) -> None:
        """
        Given: Config without pollingTiers section
        When: loadPollingTiers is called
        Then: Raises KeyError
        """
        with pytest.raises(KeyError):
            loadPollingTiers({})

    def test_loadPollingTiers_emptyTiers_raisesValueError(self) -> None:
        """
        Given: Config with empty pollingTiers section
        When: loadPollingTiers is called
        Then: Raises ValueError
        """
        with pytest.raises(ValueError):
            loadPollingTiers({"pi": {"pollingTiers": {}}})


# ================================================================================
# Tier 1 Tests — Safety-critical, every cycle
# ================================================================================


class TestTier1SafetyCritical:
    """Tests for Tier 1 (every cycle, ~1 Hz)."""

    def test_tier1_cycleInterval_is1(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 1 cycle interval
        Then: Interval is 1 (every cycle)
        """
        tier1 = loadedTiers.tiers[0]
        assert tier1.cycleInterval == 1

    def test_tier1_hasCoolantTemp(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 1 parameters
        Then: COOLANT_TEMP (PID 0x05) is present
        """
        tier1 = loadedTiers.tiers[0]
        names = [p.name for p in tier1.parameters]
        assert "COOLANT_TEMP" in names

    def test_tier1_hasRPM(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 1 parameters
        Then: RPM (PID 0x0C) is present
        """
        tier1 = loadedTiers.tiers[0]
        names = [p.name for p in tier1.parameters]
        assert "RPM" in names

    def test_tier1_hasEngineLoad(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 1 parameters
        Then: ENGINE_LOAD (PID 0x04) is present
        """
        tier1 = loadedTiers.tiers[0]
        names = [p.name for p in tier1.parameters]
        assert "ENGINE_LOAD" in names

    def test_tier1_hasTimingAdvance(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 1 parameters
        Then: TIMING_ADVANCE (PID 0x0E) is present
        """
        tier1 = loadedTiers.tiers[0]
        names = [p.name for p in tier1.parameters]
        assert "TIMING_ADVANCE" in names

    def test_tier1_hasSTFT(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 1 parameters
        Then: SHORT_FUEL_TRIM_1 (PID 0x06) is present
        """
        tier1 = loadedTiers.tiers[0]
        names = [p.name for p in tier1.parameters]
        assert "SHORT_FUEL_TRIM_1" in names

    def test_tier1_has5Parameters(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Counting tier 1 parameters
        Then: Exactly 5 parameters in tier 1
        """
        tier1 = loadedTiers.tiers[0]
        assert len(tier1.parameters) == 5

    def test_tier1_tierNumber_is1(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 1 number
        Then: Tier number is 1
        """
        assert loadedTiers.tiers[0].tier == 1


# ================================================================================
# Tier 2 Tests — Driving context, every 3 cycles
# ================================================================================


class TestTier2DrivingContext:
    """Tests for Tier 2 (every 3 cycles, ~0.3 Hz)."""

    def test_tier2_cycleInterval_is3(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 2 cycle interval
        Then: Interval is 3
        """
        tier2 = loadedTiers.tiers[1]
        assert tier2.cycleInterval == 3

    def test_tier2_hasThrottlePos(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 2 parameters
        Then: THROTTLE_POS (PID 0x11) is present
        """
        tier2 = loadedTiers.tiers[1]
        names = [p.name for p in tier2.parameters]
        assert "THROTTLE_POS" in names

    def test_tier2_hasSpeed(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 2 parameters
        Then: SPEED (PID 0x0D) is present
        """
        tier2 = loadedTiers.tiers[1]
        names = [p.name for p in tier2.parameters]
        assert "SPEED" in names

    def test_tier2_has2Parameters(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Counting tier 2 parameters
        Then: Exactly 2 parameters in tier 2
        """
        tier2 = loadedTiers.tiers[1]
        assert len(tier2.parameters) == 2

    def test_tier2_tierNumber_is2(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 2 number
        Then: Tier number is 2
        """
        assert loadedTiers.tiers[1].tier == 2


# ================================================================================
# Tier 3 Tests — Trend analysis, every 10 cycles
# ================================================================================


class TestTier3TrendAnalysis:
    """Tests for Tier 3 (every 10 cycles, ~0.1 Hz)."""

    def test_tier3_cycleInterval_is10(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 3 cycle interval
        Then: Interval is 10
        """
        tier3 = loadedTiers.tiers[2]
        assert tier3.cycleInterval == 10

    def test_tier3_hasLTFT(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 3 parameters
        Then: LONG_FUEL_TRIM_1 (PID 0x07) is present
        """
        tier3 = loadedTiers.tiers[2]
        names = [p.name for p in tier3.parameters]
        assert "LONG_FUEL_TRIM_1" in names

    def test_tier3_hasIntakeTemp(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 3 parameters
        Then: INTAKE_TEMP (PID 0x0F) is present
        """
        tier3 = loadedTiers.tiers[2]
        names = [p.name for p in tier3.parameters]
        assert "INTAKE_TEMP" in names

    def test_tier3_hasO2Sensor(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 3 parameters
        Then: O2_B1S1 (PID 0x14) is present
        """
        tier3 = loadedTiers.tiers[2]
        names = [p.name for p in tier3.parameters]
        assert "O2_B1S1" in names

    def test_tier3_has3Parameters(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Counting tier 3 parameters
        Then: Exactly 3 parameters in tier 3
        """
        tier3 = loadedTiers.tiers[2]
        assert len(tier3.parameters) == 3

    def test_tier3_tierNumber_is3(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 3 number
        Then: Tier number is 3
        """
        assert loadedTiers.tiers[2].tier == 3


# ================================================================================
# Tier 4 Tests — Background monitoring, every 30 cycles
# ================================================================================


class TestTier4BackgroundMonitoring:
    """Tests for Tier 4 (every 30 cycles, ~0.03 Hz)."""

    def test_tier4_cycleInterval_is30(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 4 cycle interval
        Then: Interval is 30
        """
        tier4 = loadedTiers.tiers[3]
        assert tier4.cycleInterval == 30

    def test_tier4_hasControlModuleVoltage(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 4 parameters
        Then: CONTROL_MODULE_VOLTAGE (PID 0x42) is present
        """
        tier4 = loadedTiers.tiers[3]
        names = [p.name for p in tier4.parameters]
        assert "CONTROL_MODULE_VOLTAGE" in names

    def test_tier4_hasIntakePressure(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 4 parameters
        Then: INTAKE_PRESSURE (PID 0x0B) is present
        """
        tier4 = loadedTiers.tiers[3]
        names = [p.name for p in tier4.parameters]
        assert "INTAKE_PRESSURE" in names

    def test_tier4_has2Parameters(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Counting tier 4 parameters
        Then: Exactly 2 parameters in tier 4
        """
        tier4 = loadedTiers.tiers[3]
        assert len(tier4.parameters) == 2

    def test_tier4_tierNumber_is4(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Checking tier 4 number
        Then: Tier number is 4
        """
        assert loadedTiers.tiers[3].tier == 4


# ================================================================================
# MDP Caveat Tests — PID 0x0B is NOT true manifold pressure
# ================================================================================


class TestMDPCaveat:
    """Tests for MDP caveat documentation on PID 0x0B."""

    def test_intakePressure_hasCaveat(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking at INTAKE_PRESSURE parameter
        Then: Caveat field is present and non-empty
        """
        tier4 = loadedTiers.tiers[3]
        intakePressure = next(
            p for p in tier4.parameters if p.name == "INTAKE_PRESSURE"
        )
        assert intakePressure.caveat is not None
        assert len(intakePressure.caveat) > 0

    def test_intakePressure_caveatMentionsMDP(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Loaded polling tier config
        When: Reading INTAKE_PRESSURE caveat
        Then: Caveat mentions MDP and EGR
        """
        tier4 = loadedTiers.tiers[3]
        intakePressure = next(
            p for p in tier4.parameters if p.name == "INTAKE_PRESSURE"
        )
        assert intakePressure.caveat is not None
        assert "MDP" in intakePressure.caveat
        assert "EGR" in intakePressure.caveat

    def test_intakePressure_caveatWarnsNotBoost(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Loaded polling tier config
        When: Reading INTAKE_PRESSURE caveat
        Then: Caveat warns it cannot be used for boost measurement
        """
        tier4 = loadedTiers.tiers[3]
        intakePressure = next(
            p for p in tier4.parameters if p.name == "INTAKE_PRESSURE"
        )
        assert intakePressure.caveat is not None
        assert "boost" in intakePressure.caveat.lower()


# ================================================================================
# PID Mapping Tests — validate hex PIDs match parameters
# ================================================================================


class TestPIDMapping:
    """Tests for PID hex code assignments."""

    def test_coolantTemp_pid0x05(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up COOLANT_TEMP
        Then: PID is 0x05
        """
        tier1 = loadedTiers.tiers[0]
        param = next(p for p in tier1.parameters if p.name == "COOLANT_TEMP")
        assert param.pid == "0x05"

    def test_rpm_pid0x0C(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up RPM
        Then: PID is 0x0C
        """
        tier1 = loadedTiers.tiers[0]
        param = next(p for p in tier1.parameters if p.name == "RPM")
        assert param.pid == "0x0C"

    def test_engineLoad_pid0x04(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up ENGINE_LOAD
        Then: PID is 0x04
        """
        tier1 = loadedTiers.tiers[0]
        param = next(p for p in tier1.parameters if p.name == "ENGINE_LOAD")
        assert param.pid == "0x04"

    def test_timingAdvance_pid0x0E(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up TIMING_ADVANCE
        Then: PID is 0x0E
        """
        tier1 = loadedTiers.tiers[0]
        param = next(p for p in tier1.parameters if p.name == "TIMING_ADVANCE")
        assert param.pid == "0x0E"

    def test_stft_pid0x06(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up SHORT_FUEL_TRIM_1
        Then: PID is 0x06
        """
        tier1 = loadedTiers.tiers[0]
        param = next(p for p in tier1.parameters if p.name == "SHORT_FUEL_TRIM_1")
        assert param.pid == "0x06"

    def test_throttlePos_pid0x11(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up THROTTLE_POS
        Then: PID is 0x11
        """
        tier2 = loadedTiers.tiers[1]
        param = next(p for p in tier2.parameters if p.name == "THROTTLE_POS")
        assert param.pid == "0x11"

    def test_speed_pid0x0D(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up SPEED
        Then: PID is 0x0D
        """
        tier2 = loadedTiers.tiers[1]
        param = next(p for p in tier2.parameters if p.name == "SPEED")
        assert param.pid == "0x0D"

    def test_ltft_pid0x07(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up LONG_FUEL_TRIM_1
        Then: PID is 0x07
        """
        tier3 = loadedTiers.tiers[2]
        param = next(p for p in tier3.parameters if p.name == "LONG_FUEL_TRIM_1")
        assert param.pid == "0x07"

    def test_intakeTemp_pid0x0F(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up INTAKE_TEMP
        Then: PID is 0x0F
        """
        tier3 = loadedTiers.tiers[2]
        param = next(p for p in tier3.parameters if p.name == "INTAKE_TEMP")
        assert param.pid == "0x0F"

    def test_o2Sensor_pid0x14(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up O2_B1S1
        Then: PID is 0x14
        """
        tier3 = loadedTiers.tiers[2]
        param = next(p for p in tier3.parameters if p.name == "O2_B1S1")
        assert param.pid == "0x14"

    def test_controlModuleVoltage_pid0x42(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up CONTROL_MODULE_VOLTAGE
        Then: PID is 0x42
        """
        tier4 = loadedTiers.tiers[3]
        param = next(
            p for p in tier4.parameters if p.name == "CONTROL_MODULE_VOLTAGE"
        )
        assert param.pid == "0x42"

    def test_intakePressure_pid0x0B(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded polling tier config
        When: Looking up INTAKE_PRESSURE
        Then: PID is 0x0B
        """
        tier4 = loadedTiers.tiers[3]
        param = next(p for p in tier4.parameters if p.name == "INTAKE_PRESSURE")
        assert param.pid == "0x0B"


# ================================================================================
# getParameterTier Tests — look up which tier a parameter belongs to
# ================================================================================


class TestGetParameterTier:
    """Tests for getParameterTier function."""

    def test_getParameterTier_tier1Param_returnsTier1(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Loaded config
        When: Looking up RPM
        Then: Returns tier 1
        """
        tier = getParameterTier(loadedTiers, "RPM")
        assert tier is not None
        assert tier.tier == 1

    def test_getParameterTier_tier2Param_returnsTier2(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Loaded config
        When: Looking up SPEED
        Then: Returns tier 2
        """
        tier = getParameterTier(loadedTiers, "SPEED")
        assert tier is not None
        assert tier.tier == 2

    def test_getParameterTier_tier3Param_returnsTier3(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Loaded config
        When: Looking up LONG_FUEL_TRIM_1
        Then: Returns tier 3
        """
        tier = getParameterTier(loadedTiers, "LONG_FUEL_TRIM_1")
        assert tier is not None
        assert tier.tier == 3

    def test_getParameterTier_tier4Param_returnsTier4(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Loaded config
        When: Looking up CONTROL_MODULE_VOLTAGE
        Then: Returns tier 4
        """
        tier = getParameterTier(loadedTiers, "CONTROL_MODULE_VOLTAGE")
        assert tier is not None
        assert tier.tier == 4

    def test_getParameterTier_unknownParam_returnsNone(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Loaded config
        When: Looking up a parameter not in any tier
        Then: Returns None
        """
        tier = getParameterTier(loadedTiers, "UNKNOWN_PARAM")
        assert tier is None


# ================================================================================
# shouldPollParameter Tests — cycle-based polling decisions
# ================================================================================


class TestShouldPollParameter:
    """Tests for shouldPollParameter function."""

    def test_tier1Param_cycle1_shouldPoll(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Tier 1 parameter (every cycle)
        When: Cycle 1
        Then: Should poll
        """
        assert shouldPollParameter(loadedTiers, "RPM", 1) is True

    def test_tier1Param_cycle5_shouldPoll(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Tier 1 parameter (every cycle)
        When: Cycle 5
        Then: Should poll
        """
        assert shouldPollParameter(loadedTiers, "RPM", 5) is True

    def test_tier2Param_cycle3_shouldPoll(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Tier 2 parameter (every 3 cycles)
        When: Cycle 3 (multiple of 3)
        Then: Should poll
        """
        assert shouldPollParameter(loadedTiers, "SPEED", 3) is True

    def test_tier2Param_cycle6_shouldPoll(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Tier 2 parameter (every 3 cycles)
        When: Cycle 6 (multiple of 3)
        Then: Should poll
        """
        assert shouldPollParameter(loadedTiers, "SPEED", 6) is True

    def test_tier2Param_cycle1_shouldNotPoll(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Tier 2 parameter (every 3 cycles)
        When: Cycle 1 (not multiple of 3)
        Then: Should not poll
        """
        assert shouldPollParameter(loadedTiers, "SPEED", 1) is False

    def test_tier2Param_cycle2_shouldNotPoll(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Tier 2 parameter (every 3 cycles)
        When: Cycle 2 (not multiple of 3)
        Then: Should not poll
        """
        assert shouldPollParameter(loadedTiers, "SPEED", 2) is False

    def test_tier3Param_cycle10_shouldPoll(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Tier 3 parameter (every 10 cycles)
        When: Cycle 10 (multiple of 10)
        Then: Should poll
        """
        assert shouldPollParameter(loadedTiers, "INTAKE_TEMP", 10) is True

    def test_tier3Param_cycle7_shouldNotPoll(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Tier 3 parameter (every 10 cycles)
        When: Cycle 7 (not multiple of 10)
        Then: Should not poll
        """
        assert shouldPollParameter(loadedTiers, "INTAKE_TEMP", 7) is False

    def test_tier4Param_cycle30_shouldPoll(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Tier 4 parameter (every 30 cycles)
        When: Cycle 30 (multiple of 30)
        Then: Should poll
        """
        assert shouldPollParameter(
            loadedTiers, "CONTROL_MODULE_VOLTAGE", 30
        ) is True

    def test_tier4Param_cycle15_shouldNotPoll(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Tier 4 parameter (every 30 cycles)
        When: Cycle 15 (not multiple of 30)
        Then: Should not poll
        """
        assert shouldPollParameter(
            loadedTiers, "CONTROL_MODULE_VOLTAGE", 15
        ) is False

    def test_unknownParam_anyC_shouldNotPoll(
        self, loadedTiers: PollingTierConfig
    ) -> None:
        """
        Given: Unknown parameter
        When: Any cycle
        Then: Should not poll
        """
        assert shouldPollParameter(loadedTiers, "UNKNOWN_PARAM", 1) is False


# ================================================================================
# getParametersForCycle Tests — which params to poll each cycle
# ================================================================================


class TestGetParametersForCycle:
    """Tests for getParametersForCycle function."""

    def test_cycle1_onlyTier1(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded config
        When: Cycle 1
        Then: Only tier 1 parameters returned (5 params)
        """
        params = getParametersForCycle(loadedTiers, 1)
        assert len(params) == 5
        assert set(params) == {
            "COOLANT_TEMP",
            "RPM",
            "ENGINE_LOAD",
            "TIMING_ADVANCE",
            "SHORT_FUEL_TRIM_1",
        }

    def test_cycle3_tier1AndTier2(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded config
        When: Cycle 3 (multiple of 1 and 3)
        Then: Tier 1 + Tier 2 parameters returned (7 params)
        """
        params = getParametersForCycle(loadedTiers, 3)
        assert len(params) == 7
        assert "SPEED" in params
        assert "THROTTLE_POS" in params
        assert "RPM" in params

    def test_cycle10_tier1And2And3(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded config
        When: Cycle 10 (multiple of 1 and 10, not 3)
        Then: Tier 1 + Tier 3 parameters returned (8 params)
        """
        params = getParametersForCycle(loadedTiers, 10)
        assert "RPM" in params
        assert "INTAKE_TEMP" in params
        assert "LONG_FUEL_TRIM_1" in params
        assert "SPEED" not in params

    def test_cycle30_allTiers(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded config
        When: Cycle 30 (multiple of 1, 3, 10, and 30)
        Then: All tier parameters returned (12 params)
        """
        params = getParametersForCycle(loadedTiers, 30)
        assert len(params) == 12
        assert "CONTROL_MODULE_VOLTAGE" in params
        assert "INTAKE_PRESSURE" in params
        assert "RPM" in params
        assert "SPEED" in params
        assert "INTAKE_TEMP" in params

    def test_cycle2_onlyTier1(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded config
        When: Cycle 2 (only multiple of 1)
        Then: Only tier 1 params returned
        """
        params = getParametersForCycle(loadedTiers, 2)
        assert len(params) == 5

    def test_cycle60_allTiers(self, loadedTiers: PollingTierConfig) -> None:
        """
        Given: Loaded config
        When: Cycle 60 (multiple of all: 1, 3, 10, 30)
        Then: All tiers returned (12 params)
        """
        params = getParametersForCycle(loadedTiers, 60)
        assert len(params) == 12


# ================================================================================
# Config File Integration Test — validate obd_config.json
# ================================================================================


class TestOBDConfigIntegration:
    """Tests that obd_config.json contains correct polling tier config."""

    @pytest.fixture
    def obdConfig(self) -> dict[str, Any]:
        """
        Load the actual config.json file.

        Returns:
            Parsed config dictionary
        """
        configPath = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.json"
        )
        with open(configPath) as f:
            return json.load(f)

    def test_obdConfig_hasPollingTiers(self, obdConfig: dict[str, Any]) -> None:
        """
        Given: config.json loaded
        When: Checking for pollingTiers section
        Then: Section exists under pi.
        """
        assert "pollingTiers" in obdConfig["pi"]

    def test_obdConfig_pollingTiers_loads(self, obdConfig: dict[str, Any]) -> None:
        """
        Given: obd_config.json loaded
        When: Loading polling tiers
        Then: Loads successfully with 4 tiers
        """
        config = loadPollingTiers(obdConfig)
        assert len(config.tiers) == 4

    def test_obdConfig_tier1_matchesSpool(self, obdConfig: dict[str, Any]) -> None:
        """
        Given: obd_config.json loaded
        When: Checking tier 1
        Then: Matches Spool spec: cycle=1, safety-critical PIDs
            (US-199 added FUEL_SYSTEM_STATUS at Spool's priority 1 rate of 1 Hz)
        """
        config = loadPollingTiers(obdConfig)
        tier1 = config.tiers[0]
        assert tier1.cycleInterval == 1
        names = {p.name for p in tier1.parameters}
        assert names == {
            "COOLANT_TEMP",
            "RPM",
            "ENGINE_LOAD",
            "TIMING_ADVANCE",
            "SHORT_FUEL_TRIM_1",
            "FUEL_SYSTEM_STATUS",
        }

    def test_obdConfig_tier2_matchesSpool(self, obdConfig: dict[str, Any]) -> None:
        """
        Given: obd_config.json loaded
        When: Checking tier 2
        Then: Matches Spool spec: cycle=3, driving-context PIDs
            (US-199 added MIL_ON, DTC_COUNT, O2_BANK1_SENSOR2_V)
        """
        config = loadPollingTiers(obdConfig)
        tier2 = config.tiers[1]
        assert tier2.cycleInterval == 3
        names = {p.name for p in tier2.parameters}
        assert names == {
            "THROTTLE_POS",
            "SPEED",
            "MIL_ON",
            "DTC_COUNT",
            "O2_BANK1_SENSOR2_V",
        }

    def test_obdConfig_tier3_matchesSpool(self, obdConfig: dict[str, Any]) -> None:
        """
        Given: obd_config.json loaded
        When: Checking tier 3
        Then: Matches Spool spec: cycle=10, trend-analysis PIDs
            (US-199 added RUNTIME_SEC, BATTERY_V)
        """
        config = loadPollingTiers(obdConfig)
        tier3 = config.tiers[2]
        assert tier3.cycleInterval == 10
        names = {p.name for p in tier3.parameters}
        assert names == {
            "LONG_FUEL_TRIM_1",
            "INTAKE_TEMP",
            "O2_B1S1",
            "RUNTIME_SEC",
            "BATTERY_V",
        }

    def test_obdConfig_tier4_matchesSpool(self, obdConfig: dict[str, Any]) -> None:
        """
        Given: obd_config.json loaded
        When: Checking tier 4
        Then: Matches Spool spec: cycle=30, background PIDs
            (US-199 added BAROMETRIC_KPA)
        """
        config = loadPollingTiers(obdConfig)
        tier4 = config.tiers[3]
        assert tier4.cycleInterval == 30
        names = {p.name for p in tier4.parameters}
        assert names == {
            "CONTROL_MODULE_VOLTAGE",
            "INTAKE_PRESSURE",
            "BAROMETRIC_KPA",
        }

    def test_obdConfig_mdpCaveat_present(self, obdConfig: dict[str, Any]) -> None:
        """
        Given: obd_config.json loaded
        When: Checking INTAKE_PRESSURE in tier 4
        Then: MDP caveat is documented
        """
        config = loadPollingTiers(obdConfig)
        tier4 = config.tiers[3]
        intakePressure = next(
            p for p in tier4.parameters if p.name == "INTAKE_PRESSURE"
        )
        assert intakePressure.caveat is not None
        assert "MDP" in intakePressure.caveat

    def test_obdConfig_controlModuleVoltage_inRealtimeParams(
        self, obdConfig: dict[str, Any]
    ) -> None:
        """
        Given: obd_config.json loaded
        When: Checking realtimeData parameters
        Then: CONTROL_MODULE_VOLTAGE is present (required for tier 4)
        """
        paramNames = [p["name"] for p in obdConfig["pi"]["realtimeData"]["parameters"]]
        assert "CONTROL_MODULE_VOLTAGE" in paramNames
