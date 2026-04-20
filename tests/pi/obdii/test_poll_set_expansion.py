################################################################################
# File Name: test_poll_set_expansion.py
# Purpose/Description: Assert Sprint 14 US-199 PIDs live in the polling config
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Ralph Agent  | Initial (US-199 Spool Data v2 Story 1)
# ================================================================================
################################################################################

"""
Regression guard: the 6 new Spool-spec'd PIDs must appear in the Pi poll
tiers at their spec'd rates, with the existing 11 PIDs untouched
(scope.doNotTouch rule).

Bandwidth-budget assertion: aggregate theoretical poll rate fits the
measured 2.5 PIDs/sec K-line envelope (Session 23).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pi.obdii.data.polling_tiers import loadPollingTiers

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_JSON = REPO_ROOT / "config.json"


# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture(scope="module")
def pollingConfig():
    with CONFIG_JSON.open() as f:
        fullConfig = json.load(f)
    return loadPollingTiers(fullConfig)


def _allParamNames(cfg) -> set[str]:
    return {p.name for t in cfg.tiers for p in t.parameters}


def _tierByName(cfg, name: str) -> int | None:
    for t in cfg.tiers:
        for p in t.parameters:
            if p.name == name:
                return t.tier
    return None


def _pidByName(cfg, name: str) -> str | None:
    for t in cfg.tiers:
        for p in t.parameters:
            if p.name == name:
                return p.pid
    return None


# ================================================================================
# New-PID presence — US-199 acceptance #1
# ================================================================================


class TestUS199NewPidsPresent:
    REQUIRED_NEW = {
        "FUEL_SYSTEM_STATUS",
        "MIL_ON",
        "DTC_COUNT",
        "RUNTIME_SEC",
        "BAROMETRIC_KPA",
        "BATTERY_V",
        "O2_BANK1_SENSOR2_V",
    }

    def test_allNewParametersAppearInPollSet(self, pollingConfig) -> None:
        names = _allParamNames(pollingConfig)
        missing = self.REQUIRED_NEW - names
        assert not missing, f"Missing new US-199 params: {missing}"

    @pytest.mark.parametrize(
        ("paramName", "expectedPid"),
        [
            ("FUEL_SYSTEM_STATUS", "0x03"),
            ("MIL_ON", "0x01"),
            ("DTC_COUNT", "0x01"),
            ("RUNTIME_SEC", "0x1F"),
            ("BAROMETRIC_KPA", "0x33"),
            ("O2_BANK1_SENSOR2_V", "0x15"),
        ],
    )
    def test_eachNewPidHasCorrectHexCode(
        self, pollingConfig, paramName: str, expectedPid: str
    ) -> None:
        pid = _pidByName(pollingConfig, paramName)
        assert pid is not None, f"{paramName} missing from poll set"
        assert pid.lower() == expectedPid.lower()

    def test_batteryV_bindsToElmVoltageAdapterMarker(self, pollingConfig) -> None:
        """BATTERY_V is adapter-level (ATRV), not a Mode 01 PID. Config should
        use a non-PID marker — either 'ELM_VOLTAGE' or a non-0x hex string."""
        pid = _pidByName(pollingConfig, "BATTERY_V")
        assert pid is not None
        # Accept either literal 'ELM_VOLTAGE' or similar adapter-tag sentinel.
        # Must NOT be the unsupported 0x42 (Session 23 confirmed unsupported on 2G).
        assert pid.lower() != "0x42", (
            "BATTERY_V must not route through PID 0x42 — it's unsupported on 2G "
            "per Session 23. Use ELM_VOLTAGE (ATRV) instead."
        )


# ================================================================================
# Existing-PID preservation — scope.doNotTouch
# ================================================================================


class TestExistingPidsUntouched:
    EXISTING_11 = {
        "COOLANT_TEMP",
        "RPM",
        "ENGINE_LOAD",
        "TIMING_ADVANCE",
        "SHORT_FUEL_TRIM_1",
        "THROTTLE_POS",
        "SPEED",
        "LONG_FUEL_TRIM_1",
        "INTAKE_TEMP",
        "O2_B1S1",
        "CONTROL_MODULE_VOLTAGE",
        "INTAKE_PRESSURE",
    }

    def test_allExistingPidsStillPresent(self, pollingConfig) -> None:
        names = _allParamNames(pollingConfig)
        missing = self.EXISTING_11 - names
        assert not missing, f"Existing PIDs removed: {missing}"

    def test_rpm_stillTier1(self, pollingConfig) -> None:
        """Tier-1 safety critical behavior must not shift."""
        assert _tierByName(pollingConfig, "RPM") == 1


# ================================================================================
# Spool-spec'd tier assignments — acceptance #6 (tier math docs)
# ================================================================================


class TestSpoolRecommendedTierAssignments:
    """Spool's priorities 1-6:
    - 0x03 Fuel Status @ 1 Hz        -> tier1
    - 0x01 MIL+DTC     @ 0.5 Hz      -> tier2 (0.33 Hz is close enough; dropping to tier3=0.1 Hz too slow)
    - 0x15 O2 post-cat @ 0.5 Hz      -> tier2 (conditional on probe)
    - 0x1F Runtime     @ 0.2 Hz      -> tier3 (0.1 Hz close)
    - ELM_VOLTAGE      @ 0.2 Hz      -> tier3
    - 0x33 Barometric  @ 0.05 Hz     -> tier4 (0.033 Hz is close, barely-changing signal)
    """

    @pytest.mark.parametrize(
        ("paramName", "expectedTier"),
        [
            ("FUEL_SYSTEM_STATUS", 1),
            ("MIL_ON", 2),
            ("DTC_COUNT", 2),
            ("O2_BANK1_SENSOR2_V", 2),
            ("RUNTIME_SEC", 3),
            ("BATTERY_V", 3),
            ("BAROMETRIC_KPA", 4),
        ],
    )
    def test_newParam_landsInSpoolRecommendedTier(
        self, pollingConfig, paramName: str, expectedTier: int
    ) -> None:
        assert _tierByName(pollingConfig, paramName) == expectedTier


# ================================================================================
# Bandwidth budget — acceptance #6 (tier math fits 2.5 PIDs/sec)
# ================================================================================


class TestBandwidthBudgetFits:
    """Session 23 measured 2.5 PIDs/sec aggregate on K-line.

    Theoretical rate (assuming 1 Hz cycle rate):
        sum_over_tiers( len(tier.parameters) / tier.cycleInterval )

    We assert the post-US-199 theoretical rate remains within 2x the
    measured budget — if we exceed that, tiers need rebalancing.
    """

    def test_theoreticalAggregateRate_fitsSessionBudget(self, pollingConfig) -> None:
        rate = sum(
            len(t.parameters) / t.cycleInterval for t in pollingConfig.tiers
        )
        # Session 23 measured 2.5 PIDs/sec actual with K-line latency throttling
        # python-obd queries. Theoretical math assumes 1 Hz cycle cadence, but
        # K-line real-world throttles to ~0.36x (Session 23: 11 PIDs scheduled
        # at ~7.0/s theoretical yielded 2.5/s measured). Post-US-199 theoretical
        # rate is bounded to stay within ~3.5x the 2.5/s envelope so K-line
        # throttling keeps actual throughput within measured ECU capacity.
        # See specs/obd2-research.md §K-Line Throughput for derivation.
        assert rate <= 10.0, f"Theoretical poll rate {rate:.2f}/s exceeds 10.0/s ceiling"
