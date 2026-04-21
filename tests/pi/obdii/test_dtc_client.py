################################################################################
# File Name: test_dtc_client.py
# Purpose/Description: Unit tests for DtcClient (US-204 -- Mode 03 + Mode 07
#                      DTC retrieval on the 2G Eclipse).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-204) | Initial -- DTC retrieval client tests.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.obdii.dtc_client`.

DtcClient wraps python-obd's GET_DTC (Mode 03, stored) and
GET_CURRENT_DTC (Mode 07, pending) commands. The 2G DSM ECU on the
Eclipse supports Mode 03 but may not support Mode 07 (pre-OBD2 full
compliance) -- the client probes Mode 07 once per connection and
records the result so callers can skip the second call.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.pi.obdii.dtc_client import (
    DiagnosticCode,
    DtcClient,
    Mode07ProbeResult,
)

# ================================================================================
# Fakes
# ================================================================================


class _FakeResponse:
    """Stands in for a python-obd OBDResponse."""

    def __init__(self, value: Any, null: bool = False) -> None:
        self.value = value
        self._null = null

    def is_null(self) -> bool:
        return self._null


class _FakeConnection:
    """Stands in for ObdConnection; just exposes .obd.query + isConnected."""

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        connected: bool = True,
    ) -> None:
        self._responses = responses or {}
        self._connected = connected
        self.obd = SimpleNamespace(query=self._query)

    def _query(self, cmd: Any) -> Any:
        name = cmd if isinstance(cmd, str) else getattr(cmd, "name", str(cmd))
        resp = self._responses.get(name)
        if resp is None:
            return _FakeResponse(value=None, null=True)
        return resp

    def isConnected(self) -> bool:
        return self._connected


def _fakeCommandFactory(name: str) -> str:
    """Return the command name verbatim so FakeConnection can route by key."""
    return name


# ================================================================================
# DiagnosticCode dataclass contract
# ================================================================================


class TestDiagnosticCodeContract:
    """The DiagnosticCode record carries code/description/status."""

    def test_storedStatusOnMode03(self) -> None:
        code = DiagnosticCode(code="P0171", description="System Too Lean (Bank 1)", status="stored")
        assert code.code == "P0171"
        assert code.status == "stored"

    def test_pendingStatusOnMode07(self) -> None:
        code = DiagnosticCode(code="P0420", description="Cat Efficiency", status="pending")
        assert code.status == "pending"

    def test_emptyDescriptionWhenUnknown(self) -> None:
        code = DiagnosticCode(code="P1234", description="", status="stored")
        assert code.description == ""


# ================================================================================
# readStoredDtcs -- Mode 03 (GET_DTC)
# ================================================================================


class TestReadStoredDtcs:
    """Mode 03 returns stored DTCs keyed to the current DTC set."""

    def test_emptyListWhenNoCodes(self) -> None:
        """Null response from ECU -> empty list (no DTCs is the healthy case)."""
        conn = _FakeConnection(responses={"GET_DTC": _FakeResponse(value=[], null=False)})
        client = DtcClient(commandFactory=_fakeCommandFactory)

        codes = client.readStoredDtcs(conn)

        assert codes == []

    def test_nullResponseReturnsEmptyList(self) -> None:
        """ECU returning null (no frame) is treated as 'no stored codes'."""
        conn = _FakeConnection()  # default: unknown key -> null response
        client = DtcClient(commandFactory=_fakeCommandFactory)

        codes = client.readStoredDtcs(conn)

        assert codes == []

    def test_singleDtcDecoded(self) -> None:
        resp = _FakeResponse(value=[("P0171", "System Too Lean (Bank 1)")])
        conn = _FakeConnection(responses={"GET_DTC": resp})
        client = DtcClient(commandFactory=_fakeCommandFactory)

        codes = client.readStoredDtcs(conn)

        assert len(codes) == 1
        assert codes[0].code == "P0171"
        assert codes[0].description == "System Too Lean (Bank 1)"
        assert codes[0].status == "stored"

    def test_multipleDtcDecoded(self) -> None:
        resp = _FakeResponse(value=[
            ("P0171", "System Too Lean (Bank 1)"),
            ("P0420", "Catalyst System Efficiency Below Threshold (Bank 1)"),
            ("P0300", "Random/Multiple Cylinder Misfire Detected"),
        ])
        conn = _FakeConnection(responses={"GET_DTC": resp})
        client = DtcClient(commandFactory=_fakeCommandFactory)

        codes = client.readStoredDtcs(conn)

        assert [c.code for c in codes] == ["P0171", "P0420", "P0300"]
        assert all(c.status == "stored" for c in codes)

    def test_unknownCodeHasEmptyDescription(self) -> None:
        """Invariant #6: unknown codes (Mitsubishi P1XXX) get empty description, no fabrication."""
        resp = _FakeResponse(value=[("P1234", None)])  # python-obd may return None when unmapped
        conn = _FakeConnection(responses={"GET_DTC": resp})
        client = DtcClient(commandFactory=_fakeCommandFactory)

        codes = client.readStoredDtcs(conn)

        assert len(codes) == 1
        assert codes[0].code == "P1234"
        assert codes[0].description == ""

    def test_disconnectedRaises(self) -> None:
        """Not connected -> explicit error, not silent empty."""
        conn = _FakeConnection(connected=False)
        client = DtcClient(commandFactory=_fakeCommandFactory)

        with pytest.raises(RuntimeError, match="not connected"):
            client.readStoredDtcs(conn)

    def test_ignoresMalformedTupleEntries(self) -> None:
        """A single malformed entry must not crash the whole fetch."""
        resp = _FakeResponse(value=[("P0171", "ok"), ("bogus-entry",), ("P0420", "cat")])
        conn = _FakeConnection(responses={"GET_DTC": resp})
        client = DtcClient(commandFactory=_fakeCommandFactory)

        codes = client.readStoredDtcs(conn)

        # Malformed entry is skipped; valid entries pass through.
        assert [c.code for c in codes] == ["P0171", "P0420"]


# ================================================================================
# readPendingDtcs -- Mode 07 (GET_CURRENT_DTC) with probe
# ================================================================================


class TestReadPendingDtcs:
    """Mode 07 is probe-first: 2G DSM may not support it."""

    def test_nullResponseMarksUnsupported(self) -> None:
        """Null Mode 07 response on 2G DSM is the canonical 'unsupported' signal."""
        conn = _FakeConnection()  # any non-configured key -> null
        client = DtcClient(commandFactory=_fakeCommandFactory)

        codes, probe = client.readPendingDtcs(conn)

        assert codes == []
        assert probe.supported is False
        assert "unsupported" in probe.reason.lower()

    def test_supportedResponseReturnsPendingCodes(self) -> None:
        resp = _FakeResponse(value=[("P0171", "System Too Lean (Bank 1)")])
        conn = _FakeConnection(responses={"GET_CURRENT_DTC": resp})
        client = DtcClient(commandFactory=_fakeCommandFactory)

        codes, probe = client.readPendingDtcs(conn)

        assert len(codes) == 1
        assert codes[0].code == "P0171"
        assert codes[0].status == "pending"
        assert probe.supported is True

    def test_emptyListSupportedResponse(self) -> None:
        """Empty list (supported but no pending codes) is a pass, not unsupported."""
        resp = _FakeResponse(value=[], null=False)
        conn = _FakeConnection(responses={"GET_CURRENT_DTC": resp})
        client = DtcClient(commandFactory=_fakeCommandFactory)

        codes, probe = client.readPendingDtcs(conn)

        assert codes == []
        assert probe.supported is True

    def test_disconnectedRaises(self) -> None:
        conn = _FakeConnection(connected=False)
        client = DtcClient(commandFactory=_fakeCommandFactory)

        with pytest.raises(RuntimeError, match="not connected"):
            client.readPendingDtcs(conn)


# ================================================================================
# Mode07ProbeResult
# ================================================================================


class TestMode07ProbeResult:
    """Tiny value object; carries enough to cache on ObdConnection."""

    def test_supportedCarriesFlag(self) -> None:
        r = Mode07ProbeResult(supported=True, reason="supported")
        assert r.supported is True

    def test_unsupportedCarriesReason(self) -> None:
        r = Mode07ProbeResult(supported=False, reason="unsupported")
        assert r.supported is False
        assert r.reason == "unsupported"


# ================================================================================
# Command-factory injection seam
# ================================================================================


class TestCommandFactoryInjection:
    """The command factory is the only hook that imports obd.commands.

    This keeps DtcClient testable off-Pi without a python-obd install.
    """

    def test_usesInjectedFactoryForMode03(self) -> None:
        calls: list[str] = []

        def fac(name: str) -> str:
            calls.append(name)
            return name

        conn = _FakeConnection(responses={"GET_DTC": _FakeResponse(value=[])})
        client = DtcClient(commandFactory=fac)
        client.readStoredDtcs(conn)

        assert "GET_DTC" in calls

    def test_usesInjectedFactoryForMode07(self) -> None:
        calls: list[str] = []

        def fac(name: str) -> str:
            calls.append(name)
            return name

        conn = _FakeConnection(responses={"GET_CURRENT_DTC": _FakeResponse(value=[])})
        client = DtcClient(commandFactory=fac)
        client.readPendingDtcs(conn)

        assert "GET_CURRENT_DTC" in calls
