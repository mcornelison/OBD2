################################################################################
# File Name: test_logger_v2_decoders.py
# Purpose/Description: Integration tests for logger.py + v2 decoders (US-199)
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
Integration tests for ObdDataLogger routing Spool Data v2 parameter_names
through the PARAMETER_DECODERS registry.

These tests mock the python-obd connection and verify:

1. queryParameter('FUEL_SYSTEM_STATUS') queries the FUEL_STATUS command
   and decodes the tuple response into an enum code + textLabel.
2. queryParameter('BATTERY_V') queries ELM_VOLTAGE (adapter-level) and
   stores the float voltage directly.
3. Unsupported PIDs (per connection.supportedPids) raise
   ParameterNotSupportedError before the query dispatches.
4. LoggedReading.unit carries the enum textLabel for enum parameters.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.pi.obdii.data.exceptions import (
    ParameterNotSupportedError,
    ParameterReadError,
)
from src.pi.obdii.data.logger import ObdDataLogger
from src.pi.obdii.pid_probe import SupportedPidSet

# ================================================================================
# Fakes
# ================================================================================


class FakeObdConnection:
    """Stands in for ObdConnection in logger integration tests."""

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        supportedPids: SupportedPidSet | None = None,
        connected: bool = True,
    ) -> None:
        self._responses = responses or {}
        self.supportedPids = supportedPids
        self._connected = connected
        # python-obd facade
        self.obd = SimpleNamespace(query=self._query)

    def _query(self, cmd: Any) -> Any:
        name = cmd if isinstance(cmd, str) else getattr(cmd, "name", str(cmd))
        resp = self._responses.get(name)
        if resp is None:
            return SimpleNamespace(value=None, unit=None, is_null=lambda: True)
        return resp

    def isConnected(self) -> bool:
        return self._connected


def _db() -> MagicMock:
    """MagicMock database stand-in — only used to satisfy ObdDataLogger ctor."""
    return MagicMock()


def _resp(value: Any, unit: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(value=value, unit=unit, is_null=lambda: value is None)


# ================================================================================
# FUEL_SYSTEM_STATUS — enum decoding round-trip
# ================================================================================


class TestFuelSystemStatusDecoding:
    def test_query_returnsLoggedReading_withEnumCodeAndTextLabel(self) -> None:
        conn = FakeObdConnection(
            responses={"FUEL_STATUS": _resp(("Closed loop, using oxygen sensor feedback", ""))}
        )
        logger = ObdDataLogger(conn, _db())
        reading = logger.queryParameter("FUEL_SYSTEM_STATUS")

        assert reading.parameterName == "FUEL_SYSTEM_STATUS"
        assert reading.value == 2.0  # CL
        assert reading.unit == "CL"  # textLabel lands in unit column
        assert isinstance(reading.timestamp, datetime)


# ================================================================================
# BATTERY_V — adapter-level (ELM_VOLTAGE) path
# ================================================================================


class TestBatteryVoltageAdapterPath:
    def test_query_routesToElmVoltageCommand_notPid0x42(self) -> None:
        conn = FakeObdConnection(responses={"ELM_VOLTAGE": _resp(12.6, unit="volt")})
        logger = ObdDataLogger(conn, _db())
        reading = logger.queryParameter("BATTERY_V")

        assert reading.value == pytest.approx(12.6)
        assert reading.unit == "V"

    def test_query_bypassesSupportedPidCheck_forAdapterCommand(self) -> None:
        """BATTERY_V has pidCode=None — supportedPids should be ignored."""
        # Empty supported set (no PIDs supported) should NOT block ELM_VOLTAGE
        conn = FakeObdConnection(
            responses={"ELM_VOLTAGE": _resp(12.8, unit="volt")},
            supportedPids=SupportedPidSet(supported=set()),
        )
        logger = ObdDataLogger(conn, _db())
        reading = logger.queryParameter("BATTERY_V")
        assert reading.value == pytest.approx(12.8)


# ================================================================================
# MIL_ON / DTC_COUNT — STATUS PID extraction
# ================================================================================


class TestMilAndDtcCountExtraction:
    def test_milOn_extractsBoolFromStatusResponse(self) -> None:
        status = SimpleNamespace(MIL=True, DTC_count=2)
        conn = FakeObdConnection(responses={"STATUS": _resp(status)})
        logger = ObdDataLogger(conn, _db())

        reading = logger.queryParameter("MIL_ON")
        assert reading.value == 1.0
        assert reading.unit == "ON"

    def test_dtcCount_extractsIntFromStatusResponse(self) -> None:
        status = SimpleNamespace(MIL=True, DTC_count=5)
        conn = FakeObdConnection(responses={"STATUS": _resp(status)})
        logger = ObdDataLogger(conn, _db())

        reading = logger.queryParameter("DTC_COUNT")
        assert reading.value == 5.0
        assert reading.unit == "count"


# ================================================================================
# Support-probe gating
# ================================================================================


class TestSupportedPidGating:
    def test_unsupportedPid_raisesParameterNotSupported_beforeDispatch(self) -> None:
        """When supportedPids explicitly excludes the PID, the logger must not
        even attempt the query — Spool's 'silent-skip' acceptance criterion."""
        conn = FakeObdConnection(
            responses={},  # response map empty — query would hit ELM null fallback
            supportedPids=SupportedPidSet(supported={"0x0C"}),  # only RPM
        )
        logger = ObdDataLogger(conn, _db())

        with pytest.raises(ParameterNotSupportedError):
            logger.queryParameter("O2_BANK1_SENSOR2_V")  # PID 0x15 not in set

    def test_supportedPid_proceedsToQuery(self) -> None:
        conn = FakeObdConnection(
            responses={"O2_B1S2": _resp((SimpleNamespace(magnitude=0.7), SimpleNamespace(magnitude=0.0)))},
            supportedPids=SupportedPidSet(supported={"0x15"}),
        )
        logger = ObdDataLogger(conn, _db())

        reading = logger.queryParameter("O2_BANK1_SENSOR2_V")
        assert reading.value == pytest.approx(0.7)

    def test_noSupportedPidsCache_treatsAsSupported(self) -> None:
        """Legacy connections (supportedPids=None) must not regress."""
        conn = FakeObdConnection(
            responses={"RUN_TIME": _resp(42, unit="second")},
            supportedPids=None,
        )
        logger = ObdDataLogger(conn, _db())

        reading = logger.queryParameter("RUNTIME_SEC")
        assert reading.value == 42.0

    def test_fallbackAllowAll_proceedsToQuery(self) -> None:
        conn = FakeObdConnection(
            responses={"BAROMETRIC_PRESSURE": _resp(101, unit="kilopascal")},
            supportedPids=SupportedPidSet.alwaysSupported(),
        )
        logger = ObdDataLogger(conn, _db())

        reading = logger.queryParameter("BAROMETRIC_KPA")
        assert reading.value == 101.0


# ================================================================================
# Null-response handling
# ================================================================================


class TestNullResponseHandling:
    def test_nullResponse_raisesParameterReadError_notSilentZero(self) -> None:
        """A null response from python-obd must raise, not silently log a zero."""
        conn = FakeObdConnection(
            responses={"FUEL_STATUS": _resp(None)},  # is_null -> True
        )
        logger = ObdDataLogger(conn, _db())

        with pytest.raises(ParameterReadError):
            logger.queryParameter("FUEL_SYSTEM_STATUS")


# ================================================================================
# Legacy parameters still work (regression guard)
# ================================================================================


class TestLegacyParameterPathUnchanged:
    def test_rpm_stillFlowsThroughLegacyPath(self) -> None:
        """Parameters not in PARAMETER_DECODERS must still use legacy _extractValue."""
        resp = _resp(SimpleNamespace(magnitude=3500.0), unit="rpm")
        conn = FakeObdConnection(responses={"RPM": resp})
        logger = ObdDataLogger(conn, _db())

        reading = logger.queryParameter("RPM")
        assert reading.value == 3500.0
        assert reading.parameterName == "RPM"
