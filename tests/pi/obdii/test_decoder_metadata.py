################################################################################
# File Name: test_decoder_metadata.py
# Purpose/Description: Tests for ECU-dependency metadata on PARAMETER_DECODERS
#                      (US-229 -- drive_end never fired on Drive 3 because
#                      ELM_VOLTAGE heartbeat kept the detector open past
#                      engine-off; the fix tags each decoder with
#                      isEcuDependent so the detector can distinguish
#                      adapter-level heartbeats from real ECU polls).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex (US-229) | Initial -- decoder-registry metadata tests.
# ================================================================================
################################################################################

"""Tests for :data:`PARAMETER_DECODERS` ECU-dependency metadata (US-229).

Every entry in the decoder registry MUST explicitly tag
``isEcuDependent``.  Mode 01 PIDs (ECU-sourced) tag ``True``;
adapter-level commands (ELM327 ``ATRV`` a.k.a. ``ELM_VOLTAGE``) tag
``False`` so the drive-end detector can ignore them as a drive-liveness
signal.

The companion helper :func:`isEcuDependentParameter` covers legacy
parameter names that flow through the getattr(obdlib.commands, name)
fallback path (``RPM``, ``SPEED``, ``COOLANT_TEMP`` etc.) -- all Mode
01 PIDs by OBD-II spec, all ECU-sourced.
"""

from __future__ import annotations

import pytest

from src.pi.obdii import decoders

# ================================================================================
# Acceptance #2: every PARAMETER_DECODERS entry has isEcuDependent
# ================================================================================


class TestRegistryMetadataCompleteness:
    """Acceptance #2 + #6 -- every decoder entry explicitly tags isEcuDependent."""

    def test_everyDecoderEntry_hasIsEcuDependent(self) -> None:
        """Completeness: every PARAMETER_DECODERS entry exposes isEcuDependent."""
        for parameterName, entry in decoders.PARAMETER_DECODERS.items():
            assert hasattr(entry, "isEcuDependent"), (
                f"PARAMETER_DECODERS[{parameterName!r}] is missing "
                "isEcuDependent metadata (US-229 requirement)"
            )
            assert isinstance(entry.isEcuDependent, bool), (
                f"PARAMETER_DECODERS[{parameterName!r}].isEcuDependent "
                f"must be bool; got {type(entry.isEcuDependent).__name__}"
            )

    @pytest.mark.parametrize(
        "parameterName",
        [
            "FUEL_SYSTEM_STATUS",
            "MIL_ON",
            "DTC_COUNT",
            "RUNTIME_SEC",
            "BAROMETRIC_KPA",
            "O2_BANK1_SENSOR2_V",
        ],
    )
    def test_mode01Pid_tagsEcuDependentTrue(self, parameterName: str) -> None:
        """All Mode 01 PIDs in the registry tag True -- they are ECU-sourced."""
        entry = decoders.PARAMETER_DECODERS[parameterName]
        assert entry.isEcuDependent is True

    def test_elmVoltage_tagsEcuDependentFalse(self) -> None:
        """BATTERY_V via ELM_VOLTAGE (ATRV) is adapter-level, NOT ECU-sourced."""
        entry = decoders.PARAMETER_DECODERS["BATTERY_V"]
        assert entry.isEcuDependent is False
        # Sanity-check the pidCode is None (confirming adapter-level origin).
        assert entry.pidCode is None
        assert entry.obdCommand == "ELM_VOLTAGE"


# ================================================================================
# Acceptance #6: helper resolves ECU-dependency for any parameter name
# ================================================================================


class TestIsEcuDependentParameter:
    """Helper covers PARAMETER_DECODERS entries + legacy ECU params + unknowns."""

    # ---- PARAMETER_DECODERS entries ----

    @pytest.mark.parametrize(
        "parameterName",
        [
            "FUEL_SYSTEM_STATUS",
            "MIL_ON",
            "DTC_COUNT",
            "RUNTIME_SEC",
            "BAROMETRIC_KPA",
            "O2_BANK1_SENSOR2_V",
        ],
    )
    def test_registryMode01Pid_returnsTrue(self, parameterName: str) -> None:
        assert decoders.isEcuDependentParameter(parameterName) is True

    def test_registryAdapterLevel_returnsFalse(self) -> None:
        assert decoders.isEcuDependentParameter("BATTERY_V") is False

    # ---- Legacy ECU params (not in PARAMETER_DECODERS) ----

    @pytest.mark.parametrize(
        "parameterName",
        [
            "RPM",
            "SPEED",
            "COOLANT_TEMP",
            "ENGINE_LOAD",
            "THROTTLE_POS",
            "TIMING_ADVANCE",
            "SHORT_FUEL_TRIM_1",
            "LONG_FUEL_TRIM_1",
            "INTAKE_TEMP",
            "O2_B1S1",
            "CONTROL_MODULE_VOLTAGE",
            "INTAKE_PRESSURE",
        ],
    )
    def test_legacyEcuParam_returnsTrue(self, parameterName: str) -> None:
        """Legacy Mode 01 PIDs (polled via getattr fallback) return True."""
        assert decoders.isEcuDependentParameter(parameterName) is True

    # ---- Unknown / adapter-level defaults ----

    def test_unknownParameter_returnsFalse(self) -> None:
        """Safe default: unknown parameters return False to avoid extending
        drive_end spuriously (US-229 invariant: 'Missing metadata defaults
        to False (safe for unknown adapter-level commands)')."""
        assert decoders.isEcuDependentParameter("TOTALLY_MADE_UP_PID") is False

    def test_emptyString_returnsFalse(self) -> None:
        assert decoders.isEcuDependentParameter("") is False


# ================================================================================
# Registry structural guarantees
# ================================================================================


class TestLegacyEcuParametersFrozenset:
    """LEGACY_ECU_PARAMETERS is immutable + enumerates the legacy Mode 01 polls."""

    def test_legacyEcuParameters_isFrozenset(self) -> None:
        assert isinstance(decoders.LEGACY_ECU_PARAMETERS, frozenset)

    def test_legacyEcuParameters_excludesRegistryEntries(self) -> None:
        """Legacy set must NOT overlap PARAMETER_DECODERS entries -- decoders
        own the explicit flag; the legacy set is the fallback universe."""
        overlap = decoders.LEGACY_ECU_PARAMETERS & set(decoders.PARAMETER_DECODERS.keys())
        assert overlap == set(), (
            f"LEGACY_ECU_PARAMETERS overlaps PARAMETER_DECODERS: {overlap}. "
            "Those keys should be tagged via ParameterDecoderEntry.isEcuDependent "
            "instead of duplicated in the legacy set."
        )

    def test_legacyEcuParameters_coversCollectorPollTiers(self) -> None:
        """Every tier 1/2/3/4 ECU-sourced name from config.json pollingTiers
        (that isn't in PARAMETER_DECODERS) MUST be in the legacy set.
        Drift protection: if a new tier adds a Mode 01 PID without a
        decoder, this test fails until someone updates LEGACY_ECU_PARAMETERS."""
        # Mode 01 PIDs from config.json pollingTiers (Sprint 18 snapshot).
        # Excludes PARAMETER_DECODERS entries (FUEL_SYSTEM_STATUS, MIL_ON,
        # DTC_COUNT, RUNTIME_SEC, BAROMETRIC_KPA, O2_BANK1_SENSOR2_V,
        # BATTERY_V) and the CONTROL_MODULE_VOLTAGE-probe-only entry.
        requiredMode01Legacy = {
            "RPM",
            "SPEED",
            "COOLANT_TEMP",
            "ENGINE_LOAD",
            "THROTTLE_POS",
            "TIMING_ADVANCE",
            "SHORT_FUEL_TRIM_1",
            "LONG_FUEL_TRIM_1",
            "INTAKE_TEMP",
            "O2_B1S1",
            "CONTROL_MODULE_VOLTAGE",
            "INTAKE_PRESSURE",
        }
        missing = requiredMode01Legacy - decoders.LEGACY_ECU_PARAMETERS
        assert missing == set(), (
            f"LEGACY_ECU_PARAMETERS is missing Mode 01 PIDs: {missing}. "
            "Any Mode 01 PID polled by the collector is ECU-sourced by "
            "OBD-II spec; add them to LEGACY_ECU_PARAMETERS or move them "
            "into PARAMETER_DECODERS with a decoder + isEcuDependent=True."
        )
