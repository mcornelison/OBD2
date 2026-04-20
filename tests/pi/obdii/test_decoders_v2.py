################################################################################
# File Name: test_decoders_v2.py
# Purpose/Description: Tests for Spool Data v2 decoders (US-199)
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
Tests for decoders of the 6 new Mode 01 PIDs + ELM_VOLTAGE adapter command.

Each decoder normalizes a python-obd response into a
:class:`DecodedReading` carrying (valueNumeric, unit, textLabel).
``valueNumeric`` goes into realtime_data.value (REAL NOT NULL);
``textLabel`` goes into realtime_data.unit (TEXT) for enum-style
parameters where the human-readable state is what analysis actually
cares about.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.pi.obdii import decoders

# ================================================================================
# Helpers
# ================================================================================


def _response(value: object, unit: str | None = None) -> SimpleNamespace:
    """Build a fake python-obd response with .value (+ optional pint magnitude)."""
    wrapped: object = value
    if isinstance(value, (int, float)):
        wrapped = SimpleNamespace(magnitude=float(value))
    return SimpleNamespace(value=wrapped, unit=unit, is_null=lambda: value is None)


# ================================================================================
# Fuel System Status (Mode 01 PID 0x03) — Spool priority 1
# ================================================================================


class TestDecodeFuelSystemStatus:
    @pytest.mark.parametrize(
        ("response_value", "expected_code", "expected_label"),
        [
            # python-obd returns a tuple/list of status strings for bank 1 / bank 2
            (("Open loop due to insufficient engine temperature", ""), 1.0, "OL"),
            (("Closed loop, using oxygen sensor feedback", ""), 2.0, "CL"),
            (("Open loop due to engine load OR fuel cut due to deceleration", ""), 3.0, "OL-drive"),
            (("Open loop due to system failure", ""), 4.0, "OL-fault"),
            (
                ("Closed loop, but fault with at least one oxygen sensor", ""),
                5.0,
                "CL-fault",
            ),
        ],
    )
    def test_decode_mapsKnownStatusStringsToEnumCode(
        self, response_value: tuple, expected_code: float, expected_label: str
    ) -> None:
        result = decoders.decodeFuelSystemStatus(_response(response_value))
        assert result.valueNumeric == expected_code
        assert result.textLabel == expected_label

    def test_decode_returnsZeroCode_forUnknownStatus(self) -> None:
        result = decoders.decodeFuelSystemStatus(_response(("Definitely not a real status", "")))
        assert result.valueNumeric == 0.0
        assert result.textLabel == "UNKNOWN"

    def test_decode_acceptsPlainString_asFirstBankValue(self) -> None:
        """Some python-obd versions may return a bare string rather than a tuple."""
        result = decoders.decodeFuelSystemStatus(
            _response("Closed loop, using oxygen sensor feedback")
        )
        assert result.valueNumeric == 2.0
        assert result.textLabel == "CL"


# ================================================================================
# STATUS (Mode 01 PID 0x01) — MIL on + DTC count (Spool priority 2)
# ================================================================================


class TestDecodeMilStatus:
    def test_decode_returnsOne_whenMilIsOn(self) -> None:
        """python-obd returns an OBDStatus object with .MIL (bool) and .DTC_count (int)."""
        status = SimpleNamespace(MIL=True, DTC_count=3)
        result = decoders.decodeMilStatus(_response(status))
        assert result.valueNumeric == 1.0
        assert result.textLabel == "ON"

    def test_decode_returnsZero_whenMilIsOff(self) -> None:
        status = SimpleNamespace(MIL=False, DTC_count=0)
        result = decoders.decodeMilStatus(_response(status))
        assert result.valueNumeric == 0.0
        assert result.textLabel == "OFF"

    def test_decode_acceptsDictStyleStatus(self) -> None:
        """Fallback for mocks that hand us dicts rather than OBDStatus."""
        result = decoders.decodeMilStatus(_response({"MIL": True, "DTC_count": 0}))
        assert result.valueNumeric == 1.0
        assert result.textLabel == "ON"


class TestDecodeDtcCount:
    @pytest.mark.parametrize("count", [0, 1, 5, 42, 127])
    def test_decode_returnsDtcCount_asFloat(self, count: int) -> None:
        status = SimpleNamespace(MIL=(count > 0), DTC_count=count)
        result = decoders.decodeDtcCount(_response(status))
        assert result.valueNumeric == float(count)
        assert result.unit == "count"

    def test_decode_returnsZero_whenStatusIsMalformed(self) -> None:
        result = decoders.decodeDtcCount(_response(SimpleNamespace()))
        assert result.valueNumeric == 0.0


# ================================================================================
# Runtime (Mode 01 PID 0x1F) — Spool priority 4
# ================================================================================


class TestDecodeRuntimeSec:
    def test_decode_returnsRuntimeSeconds_fromPintQuantity(self) -> None:
        result = decoders.decodeRuntimeSec(_response(42, unit="second"))
        assert result.valueNumeric == 42.0
        assert result.unit == "s"

    def test_decode_returnsZero_forNewlyStartedEngine(self) -> None:
        result = decoders.decodeRuntimeSec(_response(0, unit="second"))
        assert result.valueNumeric == 0.0

    def test_decode_handlesMaxUint16_18hourRollover(self) -> None:
        """Runtime PID is uint16 -> 65535 sec max (~18hr). Rollover is a non-issue per Spool."""
        result = decoders.decodeRuntimeSec(_response(65535, unit="second"))
        assert result.valueNumeric == 65535.0


# ================================================================================
# Barometric Pressure (Mode 01 PID 0x33) — Spool priority 5
# ================================================================================


class TestDecodeBarometricKpa:
    def test_decode_returnsKpaValue(self) -> None:
        result = decoders.decodeBarometricKpa(_response(101, unit="kilopascal"))
        assert result.valueNumeric == 101.0
        assert result.unit == "kPa"

    def test_decode_handlesSeaLevelNominal(self) -> None:
        """Chicago near sea level — expect ~101 kPa."""
        result = decoders.decodeBarometricKpa(_response(101.3, unit="kilopascal"))
        assert result.valueNumeric == pytest.approx(101.3)


# ================================================================================
# ELM_VOLTAGE (adapter-level ATRV command) — Spool CR #1 / priority for battery V
# ================================================================================


class TestDecodeBatteryVoltage:
    def test_decode_returnsVoltsFromElm327Response(self) -> None:
        """python-obd ELM_VOLTAGE returns a pint Quantity in volts."""
        result = decoders.decodeBatteryVoltage(_response(12.8, unit="volt"))
        assert result.valueNumeric == pytest.approx(12.8)
        assert result.unit == "V"

    @pytest.mark.parametrize("v", [11.5, 12.0, 13.8, 14.5])
    def test_decode_preservesVoltageAcrossRunningRange(self, v: float) -> None:
        result = decoders.decodeBatteryVoltage(_response(v, unit="volt"))
        assert result.valueNumeric == pytest.approx(v)


# ================================================================================
# Post-cat O2 (Mode 01 PID 0x15) — Spool priority 6 (2G support uncertain)
# ================================================================================


class TestDecodeO2PostCatVoltage:
    def test_decode_extractsVoltageFromTupleResponse(self) -> None:
        """python-obd PID 0x15 returns (voltage, STFT) tuple. Store voltage only
        per story stopCondition #4 — STFT post-cat is future sprint scope."""
        # Tuple: (voltage quantity, STFT quantity) -- we extract magnitude of [0]
        vQ = SimpleNamespace(magnitude=0.75)
        stftQ = SimpleNamespace(magnitude=0.0)
        resp = SimpleNamespace(value=(vQ, stftQ), unit=None, is_null=lambda: False)
        result = decoders.decodeO2PostCatVoltage(resp)
        assert result.valueNumeric == pytest.approx(0.75)
        assert result.unit == "V"

    def test_decode_acceptsBareNumericResponse(self) -> None:
        """When a mock sends a plain float (not a tuple), treat it as voltage directly."""
        result = decoders.decodeO2PostCatVoltage(_response(0.6, unit="volt"))
        assert result.valueNumeric == pytest.approx(0.6)


# ================================================================================
# Decoder registry
# ================================================================================


class TestDecoderRegistry:
    """The registry maps Spool parameter_name -> (obd command name, decoder fn, pid code, unit).

    It must expose all 6 new parameter names required by US-199 acceptance.
    """

    REQUIRED_PARAMS = {
        "FUEL_SYSTEM_STATUS",
        "MIL_ON",
        "DTC_COUNT",
        "RUNTIME_SEC",
        "BAROMETRIC_KPA",
        "BATTERY_V",
        "O2_BANK1_SENSOR2_V",
    }

    def test_registry_containsAllRequiredParameters(self) -> None:
        names = set(decoders.PARAMETER_DECODERS.keys())
        missing = self.REQUIRED_PARAMS - names
        assert not missing, f"Missing decoders: {missing}"

    def test_batteryV_bindsToElmVoltageAdapterCommand(self) -> None:
        """Invariant: BATTERY_V must use ELM_VOLTAGE (ATRV), NOT PID 0x42 which is
        unsupported on 2G per Session 23."""
        entry = decoders.PARAMETER_DECODERS["BATTERY_V"]
        assert entry.obdCommand == "ELM_VOLTAGE"
        assert entry.pidCode is None  # adapter-level, not a Mode 01 PID

    def test_milOn_and_dtcCount_bothShareMode01Pid01(self) -> None:
        """Both MIL_ON and DTC_COUNT come from the same STATUS PID."""
        assert decoders.PARAMETER_DECODERS["MIL_ON"].obdCommand == "STATUS"
        assert decoders.PARAMETER_DECODERS["DTC_COUNT"].obdCommand == "STATUS"
        assert decoders.PARAMETER_DECODERS["MIL_ON"].pidCode == "0x01"
        assert decoders.PARAMETER_DECODERS["DTC_COUNT"].pidCode == "0x01"

    @pytest.mark.parametrize(
        ("parameter", "expectedObdCmd", "expectedPid"),
        [
            ("FUEL_SYSTEM_STATUS", "FUEL_STATUS", "0x03"),
            ("RUNTIME_SEC", "RUN_TIME", "0x1F"),
            ("BAROMETRIC_KPA", "BAROMETRIC_PRESSURE", "0x33"),
            ("O2_BANK1_SENSOR2_V", "O2_B1S2", "0x15"),
        ],
    )
    def test_registry_bindsSpoolNamesToCorrectPythonObdCommands(
        self, parameter: str, expectedObdCmd: str, expectedPid: str
    ) -> None:
        entry = decoders.PARAMETER_DECODERS[parameter]
        assert entry.obdCommand == expectedObdCmd
        assert entry.pidCode == expectedPid
