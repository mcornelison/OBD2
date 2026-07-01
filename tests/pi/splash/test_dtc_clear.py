################################################################################
# File Name: test_dtc_clear.py
# Purpose/Description: US-407 (F-111) tests for the AUTHORITATIVE clear-gate SSOT
#   + clear orchestration (pi.splash.dtc_clear). The load-bearing safety layer:
#   the Mode-04 issuance re-checks the gate at the privileged action path,
#   RE-DERIVED from the raw captured codes -- it NEVER trusts the UI-supplied
#   `clearGate.enabled` flag (S-10 / F-3). Gate = every stored (non-`na`) code is
#   MINOR (green) AND logged AND server-sync-acked; any STOP/WATCH -> disabled; an
#   un-synced MINOR -> disabled; a code that re-set this session (sessionResetLock)
#   -> disabled ("don't chase the light", advisory sec 4d). performClear refuses
#   to call the vehicle-write runner when the gate fails, and flags an instant
#   re-set from the post-clear re-read.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial -- US-407 authoritative clear gate.
# ================================================================================
################################################################################

"""Tests for the US-407 authoritative clear gate + performClear orchestration."""

from __future__ import annotations

from typing import Any

from pi.splash import dtc_clear


def _code(
    code: str,
    severity: str,
    *,
    status: str = "stored",
    logged: bool = True,
    syncAcked: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "status": status,
        "logged": logged,
        "syncAcked": syncAcked,
    }


def _state(codes: list[dict], *, sessionResetLock: list[str] | None = None) -> dict:
    # NOTE: clearGate.enabled is deliberately set to True here so the tests prove
    # the action path RE-DERIVES the gate from the codes and ignores this flag.
    return {
        "mil": True,
        "codes": codes,
        "newSinceTs": None,
        "clearGate": {"enabled": True, "reason": "ok"},
        "sessionResetLock": list(sessionResetLock or []),
        "ts": "2026-06-30T19:42:00Z",
    }


# ---------------------------------------------------------------------------
# evaluateClearGate -- the authoritative re-check (S-10 / F-3)
# ---------------------------------------------------------------------------


def test_gate_allMinorLoggedSynced_enabled():
    """S-6 ok: every stored code MINOR + logged + synced -> gate enabled."""
    decision = dtc_clear.evaluateClearGate(_state([_code("P0443", "minor")]))
    assert decision.enabled is True
    assert decision.reason == dtc_clear.GATE_OK


def test_gate_stopPresent_disabledSeverity_ignoresUiFlag():
    """S-10 / F-3 (load-bearing): a STOP stored code disables the gate EVEN THOUGH
    the state's clearGate.enabled says True -- the gate is re-derived, never
    trusted from the UI."""
    state = _state([_code("P0443", "minor"), _code("P0301", "stop")])
    assert state["clearGate"]["enabled"] is True  # the UI/state claims clearable
    decision = dtc_clear.evaluateClearGate(state)
    assert decision.enabled is False
    assert decision.reason == dtc_clear.GATE_SEVERITY


def test_gate_watchPresent_disabledSeverity():
    """A WATCH code also blocks the all-or-nothing clear."""
    decision = dtc_clear.evaluateClearGate(_state([_code("P0420", "watch")]))
    assert decision.enabled is False
    assert decision.reason == dtc_clear.GATE_SEVERITY


def test_gate_minorNotSynced_disabledSyncPending():
    """S-6 sync_pending: a MINOR code not yet logged+server-acked blocks the clear
    (capture-before-clear, advisory sec 4c)."""
    decision = dtc_clear.evaluateClearGate(
        _state([_code("P0443", "minor", logged=True, syncAcked=False)])
    )
    assert decision.enabled is False
    assert decision.reason == dtc_clear.GATE_SYNC


def test_gate_noStoredCodes_disabledNoCodes():
    """Nothing to clear -> the gate is disabled with a no_codes reason."""
    decision = dtc_clear.evaluateClearGate(_state([]))
    assert decision.enabled is False
    assert decision.reason == dtc_clear.GATE_NO_CODES


def test_gate_naCodesIgnored_neverBlockNorEnableAlone():
    """`na` (auto-trans P1xxx on this manual car) is not a real fault: it never
    blocks the gate, and an na-only state is 'no_codes' (nothing clearable)."""
    decision = dtc_clear.evaluateClearGate(_state([_code("P1750", "na")]))
    assert decision.enabled is False
    assert decision.reason == dtc_clear.GATE_NO_CODES


def test_gate_sessionLockedCode_disabled_dontChaseTheLight():
    """S-8: a MINOR code that re-set this session (in sessionResetLock) locks the
    clear -- refuse a 2nd clear ('don't chase the light', advisory sec 4d)."""
    decision = dtc_clear.evaluateClearGate(
        _state([_code("P0443", "minor")], sessionResetLock=["P0443"])
    )
    assert decision.enabled is False
    assert decision.reason == dtc_clear.GATE_SESSION_LOCKED


# ---------------------------------------------------------------------------
# performClear -- gate re-check refuses the vehicle-write; re-set detection
# ---------------------------------------------------------------------------


def test_performClear_gateFails_runnerNeverCalled():
    """S-10 / F-2 / F-4: when the gate fails the Mode-04 runner is NEVER called --
    no vehicle-write, no freeze-frame destroyed."""
    calls = []

    def runner():
        calls.append(True)
        return {"stored": [], "pending": [], "mil": False}

    outcome = dtc_clear.performClear(
        _state([_code("P0301", "stop")]), clearRunner=runner
    )

    assert outcome.issued is False, "gate failed -> not issued"
    assert outcome.reason == dtc_clear.GATE_SEVERITY
    assert calls == [], "the vehicle-write runner must never run when the gate fails"


def test_performClear_gateOk_issuesAndProvesCleared():
    """Gate ok -> runner runs; a clean re-read proves cleared (0/0, MIL off)."""

    def runner():
        return {"stored": [], "pending": [], "mil": False}

    outcome = dtc_clear.performClear(
        _state([_code("P0443", "minor")]), clearRunner=runner
    )

    assert outcome.issued is True
    assert outcome.cleared is True
    assert outcome.storedAfter == []
    assert outcome.milAfter is False
    assert outcome.reSetCodes == []


def test_performClear_instantReSet_flaggedNotCleared():
    """I-7 / S-8: a code present before AND after the wipe is an instant re-set ->
    flagged for the session-lock, and cleared is False (it did NOT clear)."""

    def runner():
        return {"stored": ["P0443"], "pending": [], "mil": True}

    outcome = dtc_clear.performClear(
        _state([_code("P0443", "minor")]), clearRunner=runner
    )

    assert outcome.issued is True
    assert outcome.cleared is False, "a returned code means it did not clear"
    assert outcome.reSetCodes == ["P0443"], "the re-set code is flagged to lock"
