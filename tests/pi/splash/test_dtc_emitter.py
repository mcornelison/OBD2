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
        "lastKnown",
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


def test_buildDtcState_unavailable_liveFieldsAreHonestNulls_noTakeoverTrigger():
    """US-429 / Bug-3b, amended by US-752 (Atlas 2026-09-14): an unavailable DTC
    source publishes NO live values -- codes and mil are null, not []/false (a
    default read as a measurement), newSinceTs None (the US-405 takeover can NOT
    mis-fire), a stale caller value never leaks through, and with nothing
    remembered the lastKnown block is null."""
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
    assert state["codes"] is None
    assert state["newSinceTs"] is None
    assert state["mil"] is None
    assert state["lastKnown"] is None
    assert state["source"] == {"dtc": {"available": False, "reason": "not read yet"}}


def _lastKnownBlock(*codes: dict) -> dict:
    return {"codes": list(codes), "asOfTs": "2026-09-14T09:00:00Z", "source": "dtc_log"}


def _knownCode(code: str, *, status: str = "stored", lastSeenTs: str = "2026-09-14T09:00:00Z"):
    return {
        "code": code,
        "status": status,
        "description": "remembered",
        "driveId": None,
        "lastSeenTs": lastSeenTs,
    }


def test_buildDtcState_unavailable_withLastKnown_enrichedAndDatedSeparately():
    """
    Given: the source is down and dtc_log remembers a tabled + an un-tabled code
    When: the state is built
    Then: live codes/mil stay null; lastKnown carries both codes enriched like
          live ones (tier never invented), each with lastSeenTs, plus asOfTs,
          source and the stored-code MIL proxy
    """
    state = buildDtcState(
        codes=[],
        severityTable=_TABLE,
        mil=False,
        newSinceTs=None,
        sessionResetLock=[],
        nowIso="2026-09-14T12:00:00Z",
        dtcAvailable=False,
        lastKnown=_lastKnownBlock(
            _knownCode("p1300"),
            _knownCode("P0443", status="pending", lastSeenTs="2026-09-13T09:00:00Z"),
        ),
    )

    assert state["codes"] is None
    assert state["mil"] is None
    lk = state["lastKnown"]
    assert lk["asOfTs"] == "2026-09-14T09:00:00Z"
    assert lk["source"] == "dtc_log"
    assert lk["mil"] is True
    assert [c["code"] for c in lk["codes"]] == ["P1300", "P0443"]
    assert lk["codes"][0]["severity"] == "watch"
    assert lk["codes"][1]["severity"] == "unknown"
    assert lk["codes"][1]["lastSeenTs"] == "2026-09-13T09:00:00Z"


def test_buildDtcState_lastKnownPendingOnly_milIsNotLastKnownLit():
    """Two facts, not one boolean: a pending-only memory does not claim a lit MIL."""
    state = buildDtcState(
        codes=[],
        severityTable=_TABLE,
        mil=False,
        newSinceTs=None,
        sessionResetLock=[],
        nowIso="2026-09-14T12:00:00Z",
        dtcAvailable=False,
        lastKnown=_lastKnownBlock(_knownCode("P0443", status="pending")),
    )
    assert state["mil"] is None
    assert state["lastKnown"]["mil"] is False


def test_buildDtcState_available_ignoresLastKnown_liveReadWins():
    """A live read is the truth: any remembered block is dropped."""
    state = buildDtcState(
        codes=[_rawCode("P1300")],
        severityTable=_TABLE,
        mil=True,
        newSinceTs=None,
        sessionResetLock=[],
        nowIso="2026-09-14T12:00:00Z",
        lastKnown=_lastKnownBlock(_knownCode("P0443")),
    )
    assert state["lastKnown"] is None
    assert [c["code"] for c in state["codes"]] == ["P1300"]
    assert state["mil"] is True


def test_buildDtcState_lastKnown_neverReachesTheClearGate():
    """
    Given: a remembered code that WOULD be clearable if it were live (MINOR,
           logged) and no live codes
    When: the state is built and the authoritative gate re-derives from it
    Then: the published gate and dtc_clear both see no codes; the Mode-04 runner
          is never called
    """
    from pi.splash import dtc_clear

    table = {
        **_TABLE,
        "P0442": {
            "severity": "minor",
            "severityCaveat": None,
            "short": "EVAP small leak",
            "long": "EVAP small leak",
            "suggestedFix": "Check the fuel cap seal",
            "fixProvenance": "spool-validated",
            "clearEligible": True,
        },
    }
    state = buildDtcState(
        codes=[],
        severityTable=table,
        mil=False,
        newSinceTs=None,
        sessionResetLock=[],
        nowIso="2026-09-14T12:00:00Z",
        dtcAvailable=False,
        lastKnown=_lastKnownBlock(_knownCode("P0442")),
    )

    assert state["clearGate"] == {"enabled": False, "reason": "ok"}
    assert dtc_clear.evaluateClearGate(state).reason == dtc_clear.GATE_NO_CODES
    calls: list[int] = []
    outcome = dtc_clear.performClear(state, clearRunner=lambda: calls.append(1) or {})
    assert outcome.issued is False
    assert calls == []


def test_makeDtcEmitter_passesLastKnownThroughToTheFile(tmp_path):
    """The emit callable carries lastKnown into the written `dtc` state."""
    emit = makeDtcEmitter(
        str(tmp_path), severityTable=_TABLE, nowIsoFn=lambda: "2026-09-14T12:00:00Z"
    )

    emit(
        codes=[],
        mil=False,
        dtcAvailable=False,
        lastKnown=_lastKnownBlock(_knownCode("P0443")),
    )

    payload = json.loads((tmp_path / DTC_FILENAME).read_text())
    assert payload["codes"] is None
    assert payload["lastKnown"]["codes"][0]["code"] == "P0443"


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
