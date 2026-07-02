################################################################################
# File Name: test_dtc_emitter.py
# Purpose/Description: US-404 (F-111) tests for the `dtc` state emitter. Verifies
#   the pure builder produces the design-spec §8 schema (codes + severity +
#   suggestedFix + provenance + freeze-frame/fallback + log/sync + clearGate),
#   that Spool's P1xxx severity table is merged verbatim (caveat carried, tier
#   never auto-upgraded), that un-tabled codes degrade honestly to `unknown`,
#   that a KOEO read stamps driveId=None on every code, and that the emit
#   factory writes atomically + never raises (the dashboard hook can't block).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial -- US-404 `dtc` emitter.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.splash.dtc_emitter` (US-404)."""

from __future__ import annotations

import json

from pi.splash.dtc_emitter import (
    DTC_FILENAME,
    buildDtcState,
    makeDtcEmitter,
)

# A minimal severity table fixture (the loader's output shape) -- the emitter
# is tested against this map, not the real markdown (that is the loader's test).
_TABLE = {
    "P1300": {
        "severity": "watch",
        "severityCaveat": "\U0001f534 if knock",
        "short": "Ignition Timing Adjustment circuit",
        "long": "Ignition Timing Adjustment circuit",
        "suggestedFix": "Verify base timing is set.",
        "fixProvenance": "spool-validated",
        "clearEligible": False,
    },
    "P1750": {
        "severity": "na",
        "severityCaveat": None,
        "short": "Solenoid Assembly (A/T)",
        "long": "Solenoid Assembly (A/T)",
        "suggestedFix": None,
        "fixProvenance": "none",
        "clearEligible": False,
    },
}


def _rawCode(code: str, *, status: str = "stored", desc: str = "", **kw) -> dict:
    """A captured-code dict in the shape the dispatcher hands the builder."""
    base = {
        "code": code,
        "status": status,
        "description": desc,
        "driveId": None,
        "setAtTs": "2026-06-30T19:40:00Z",
        "logged": True,
        "syncAcked": False,
    }
    base.update(kw)
    return base


def test_buildDtcState_schema_hasAllSpecKeys():
    """
    Given: a single captured code
    When: the state is built
    Then: the top-level schema matches design-spec §8 exactly
    """
    state = buildDtcState(
        codes=[_rawCode("P1300")],
        severityTable=_TABLE,
        mil=True,
        newSinceTs="2026-06-30T19:40:00Z",
        sessionResetLock=[],
        nowIso="2026-06-30T19:42:00Z",
    )

    assert set(state) == {
        "mil",
        "codes",
        "newSinceTs",
        "clearGate",
        "sessionResetLock",
        "source",
        "ts",
    }
    assert state["mil"] is True
    assert state["ts"] == "2026-06-30T19:42:00Z"
    assert state["newSinceTs"] == "2026-06-30T19:40:00Z"


def test_buildDtcState_tabledCode_mergesSpoolSeverityVerbatim():
    """
    Given: a code present in Spool's table (P1300, condition-dependent)
    When: the state is built
    Then: severity is WATCH (NOT upgraded), the caveat is carried, and the
          Spool fix + provenance flow through
    """
    state = buildDtcState(
        codes=[_rawCode("P1300")],
        severityTable=_TABLE,
        mil=True,
        newSinceTs=None,
        sessionResetLock=[],
        nowIso="2026-06-30T19:42:00Z",
    )

    code = state["codes"][0]
    assert code["severity"] == "watch"  # caveat does NOT auto-upgrade (R-1)
    assert "knock" in code["severityCaveat"].lower()
    assert code["fixProvenance"] == "spool-validated"
    assert code["clearEligible"] is False
    assert code["freezeFrame"] is None  # Mode 02 unsupported on MD326328


def test_buildDtcState_unTabledCode_degradesToUnknownNeverFabricates():
    """
    Given: a code absent from Spool's table (generic P0443, no enrichment yet)
    When: the state is built
    Then: severity is `unknown`, no fix is fabricated, and the raw python-obd
          description flows through as the short text (honest-instrument)
    """
    state = buildDtcState(
        codes=[_rawCode("P0443", desc="EVAP purge control valve")],
        severityTable=_TABLE,
        mil=True,
        newSinceTs=None,
        sessionResetLock=[],
        nowIso="2026-06-30T19:42:00Z",
    )

    code = state["codes"][0]
    assert code["severity"] == "unknown"
    assert code["suggestedFix"] is None  # never invented
    assert code["fixProvenance"] == "none"
    assert code["short"] == "EVAP purge control valve"
    assert code["clearEligible"] is False


def test_buildDtcState_keyOnRead_stampsDriveIdNullOnEveryCode():
    """
    Given: KOEO-captured codes (driveId None)
    When: the state is built
    Then: every emitted code carries driveId None (the display renders
          "key-on read" not "Drive N" -- S-11)
    """
    state = buildDtcState(
        codes=[_rawCode("P1300"), _rawCode("P0443", status="pending")],
        severityTable=_TABLE,
        mil=True,
        newSinceTs=None,
        sessionResetLock=[],
        nowIso="2026-06-30T19:42:00Z",
    )

    assert all(c["driveId"] is None for c in state["codes"])


def test_buildDtcState_clearGate_stopOrWatchPresent_disabledSeverity():
    """
    Given: a stored WATCH code (P1300)
    When: the clear gate is computed
    Then: clear is disabled with reason `severity_present` (a non-MINOR code
          is present -- US-407 re-checks this at the action path)
    """
    state = buildDtcState(
        codes=[_rawCode("P1300")],
        severityTable=_TABLE,
        mil=True,
        newSinceTs=None,
        sessionResetLock=[],
        nowIso="2026-06-30T19:42:00Z",
    )

    assert state["clearGate"] == {"enabled": False, "reason": "severity_present"}


def test_buildDtcState_naCode_neverBlocksClearGate():
    """
    Given: only an auto-trans `na` code is stored (not a real fault on this car)
    When: the clear gate is computed
    Then: the `na` code does not count as a severity-present block
    """
    state = buildDtcState(
        codes=[_rawCode("P1750")],
        severityTable=_TABLE,
        mil=False,
        newSinceTs=None,
        sessionResetLock=[],
        nowIso="2026-06-30T19:42:00Z",
    )

    # No real stored fault -> not 'severity_present'; nothing to clear -> 'ok'.
    assert state["clearGate"]["reason"] != "severity_present"


# ---------------------------------------------------------------------------
# US-429 honest-availability -- the DTC source (Bug-3b: no mis-fired takeover).
# ---------------------------------------------------------------------------


def test_buildDtcState_available_carriesAvailableSource():
    """US-429: a real read (available) carries source.dtc available, null reason."""
    state = buildDtcState(
        codes=[_rawCode("P1300")],
        severityTable=_TABLE,
        mil=True,
        newSinceTs="2026-06-30T19:40:00Z",
        sessionResetLock=[],
        nowIso="2026-06-30T19:42:00Z",
    )
    assert state["source"] == {"dtc": {"available": True, "reason": None}}


def test_buildDtcState_unavailable_freshEmptyNoTakeoverTrigger():
    """US-429 / Bug-3b: an unavailable DTC source (no read happened) publishes a
    FRESH empty state -- codes cleared (never stale), newSinceTs None (so the
    US-405 takeover can NOT mis-fire), mil off -- and source.dtc carries the NA
    reason. An absent source reads `unavailable`, not "no codes -> all clear"."""
    state = buildDtcState(
        codes=[_rawCode("P1300")],  # a stale caller value must NOT leak through
        severityTable=_TABLE,
        mil=True,
        newSinceTs="2026-06-30T19:40:00Z",
        sessionResetLock=[],
        nowIso="2026-06-30T19:42:00Z",
        dtcAvailable=False,
        dtcUnavailableReason="not read yet",
    )
    assert state["codes"] == []
    assert state["newSinceTs"] is None
    assert state["mil"] is False
    assert state["source"] == {"dtc": {"available": False, "reason": "not read yet"}}


def test_makeDtcEmitter_writesAtomicValidJsonToDtcFile(tmp_path):
    """
    Given: an emit factory pointed at a states dir
    When: emit is called with captured codes
    Then: the `dtc` state file exists, is valid JSON, and reflects the codes
    """
    emit = makeDtcEmitter(
        str(tmp_path),
        severityTable=_TABLE,
        nowIsoFn=lambda: "2026-06-30T19:42:00Z",
    )

    emit(codes=[_rawCode("P1300")], mil=True, newSinceTs=None, sessionResetLock=[])

    target = tmp_path / DTC_FILENAME
    assert target.exists()
    payload = json.loads(target.read_text())
    assert payload["codes"][0]["code"] == "P1300"
    assert payload["mil"] is True
    # Atomic write leaves no temp file behind.
    assert not (tmp_path / (DTC_FILENAME + ".tmp")).exists()


def test_makeDtcEmitter_writeFailure_neverRaises(tmp_path, monkeypatch):
    """
    Given: writeStateAtomic raises (e.g. tmpfs full)
    When: emit is called
    Then: the exception is swallowed -- the dashboard hook never blocks the
          DTC capture path (best-effort contract)
    """
    import pi.splash.dtc_emitter as mod

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(mod, "writeStateAtomic", _boom)
    emit = makeDtcEmitter(str(tmp_path), severityTable=_TABLE)

    # Must not raise.
    emit(codes=[_rawCode("P1300")], mil=True, newSinceTs=None, sessionResetLock=[])
