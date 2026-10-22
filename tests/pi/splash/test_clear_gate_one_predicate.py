################################################################################
# File Name: test_clear_gate_one_predicate.py
# Purpose/Description: US-919 [F-161] -- the two Python copies of the DTC clear
#   gate (dtc_emitter._computeClearGate, the published block; dtc_clear.
#   evaluateClearGate, the authoritative action-path gate) answer the SAME
#   reason for every row of the shared case table (clear_gate_cases.py). The
#   carousel.js copy runs the same rows in tests/ui/test_clear_gate_one_predicate.py.
#   Also pins the parts of the story a reason cannot show: a code both stored
#   and pending is ONE relevant entry, a pending code that returns after a clear
#   locks the session, and the action path re-checks pending_not_read.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-21    | Ralph (Rex)  | Initial -- US-919 one predicate, one table.
# ================================================================================
################################################################################

"""US-919 tests: one clear-gate predicate, the same in both Python copies."""

from __future__ import annotations

from typing import Any

import pytest

from pi.splash import dtc_clear, dtc_emitter
from tests.pi.splash.clear_gate_cases import CLEAR_GATE_CASES, READ_TS

_IDS = [c["id"] for c in CLEAR_GATE_CASES]


def gateCodes(case: dict[str, Any]) -> list[dict[str, Any]]:
    """The row's codes with the row's ``syncAcked`` applied to each (a new list)."""
    return [{**c, "syncAcked": case["syncAcked"]} for c in case["codes"]]


def dtcStateOf(case: dict[str, Any]) -> dict[str, Any]:
    """The row as the `dtc` state mapping dtc_clear and carousel.js read."""
    return {
        "codes": gateCodes(case),
        "pendingCheckedAtTs": case["pendingCheckedAtTs"],
        "sessionResetLock": list(case["lock"]),
    }


def _neverRuns() -> tuple[list[int], Any]:
    calls: list[int] = []

    def runner() -> dict:
        calls.append(1)
        return {"stored": [], "pending": [], "mil": False}

    return calls, runner


# ---------------------------------------------------------------------------
# The shared table through both Python copies.
# ---------------------------------------------------------------------------


def test_theCaseTableCoversEveryReasonInTheChain():
    """
    Given: the shared case table
    When: its expected reasons are collected
    Then: every reason the chain can give appears at least once, so no branch
          of any copy is left unexercised by the table.
    """
    assert {c["expected"] for c in CLEAR_GATE_CASES} == {
        dtc_clear.GATE_NO_CODES,
        dtc_clear.GATE_SEVERITY,
        dtc_clear.GATE_SEVERITY_UNKNOWN,
        dtc_clear.GATE_PENDING_NOT_READ,
        dtc_clear.GATE_SYNC,
        dtc_clear.GATE_SESSION_LOCKED,
        dtc_clear.GATE_OK,
    }


@pytest.mark.parametrize("case", CLEAR_GATE_CASES, ids=_IDS)
def test_authoritativeGate_answersTheTableReason(case: dict[str, Any]):
    """
    Given: one row of the shared table
    When: dtc_clear.evaluateClearGate re-derives the gate from it
    Then: the row's reason, and enabled only for `ok`.
    """
    decision = dtc_clear.evaluateClearGate(dtcStateOf(case))

    assert decision.reason == case["expected"], case["id"]
    assert decision.enabled is (case["expected"] == dtc_clear.GATE_OK), case["id"]


@pytest.mark.parametrize("case", CLEAR_GATE_CASES, ids=_IDS)
def test_publishedGate_answersTheTableReason(case: dict[str, Any]):
    """
    Given: one row of the shared table
    When: dtc_emitter._computeClearGate computes the published block from it
    Then: the row's reason, and enabled only for `ok` -- the same as dtc_clear.
    """
    gate = dtc_emitter._computeClearGate(
        gateCodes(case),
        pendingCheckedAtTs=case["pendingCheckedAtTs"],
        sessionResetLock=list(case["lock"]),
    )

    assert gate == {
        "enabled": case["expected"] == dtc_clear.GATE_OK,
        "reason": case["expected"],
    }, case["id"]


@pytest.mark.parametrize("case", CLEAR_GATE_CASES, ids=_IDS)
def test_aRefusedRow_neverReachesTheMode04Runner(case: dict[str, Any]):
    """
    Given: one row of the shared table
    When: a clear is submitted at the action path
    Then: the Mode 04 runner runs only for an `ok` row -- pending_not_read is
          re-checked there like every other reason.
    """
    calls, runner = _neverRuns()

    outcome = dtc_clear.performClear(dtcStateOf(case), clearRunner=runner)

    assert outcome.reason == case["expected"], case["id"]
    assert outcome.issued is (case["expected"] == dtc_clear.GATE_OK), case["id"]
    assert calls == ([1] if outcome.issued else []), case["id"]


# ---------------------------------------------------------------------------
# What a reason cannot show.
# ---------------------------------------------------------------------------


def test_aCodeBothStoredAndPending_isOneRelevantEntry():
    """
    Given: stored P0443 MINOR + pending P0443 (VC 5)
    When: the relevant set is taken by dtc_clear and by the emitter
    Then: ONE entry each, and it is the stored one.
    """
    codes = [
        {"code": "P0443", "status": "stored", "severity": "minor",
         "logged": True, "syncAcked": True},
        {"code": "P0443", "status": "pending", "severity": "minor",
         "logged": True, "syncAcked": True},
    ]

    authoritative = dtc_clear._relevantStored({"codes": codes})
    published = dtc_emitter._relevantCodes(codes)

    assert [(c["code"], c["status"]) for c in authoritative] == [("P0443", "stored")]
    assert [(c["code"], c["status"]) for c in published] == [("P0443", "stored")]


def test_aCodeBothStoredAndPending_countsOnceWhicheverIsListedFirst():
    """
    Given: the pending P0443 listed BEFORE the stored one
    When: the relevant set is taken
    Then: still one entry, the stored one.
    """
    codes = [
        {"code": "P0443", "status": "pending", "severity": "minor",
         "logged": True, "syncAcked": True},
        {"code": "P0443", "status": "stored", "severity": "minor",
         "logged": True, "syncAcked": True},
    ]

    assert [c["status"] for c in dtc_clear._relevantStored({"codes": codes})] == ["stored"]
    assert [c["status"] for c in dtc_emitter._relevantCodes(codes)] == ["stored"]


@pytest.mark.parametrize("status", ["stored", "pending"])
def test_naIsExcludedWhateverTheStatus(status: str):
    """
    Given: a single `na` code, stored or pending (Atlas Q3)
    When: the relevant set is taken
    Then: empty in both copies.
    """
    codes = [{"code": "P1750", "status": status, "severity": "na",
              "logged": True, "syncAcked": True}]

    assert dtc_clear._relevantStored({"codes": codes}) == []
    assert dtc_emitter._relevantCodes(codes) == []


def test_aPendingCodeThatReturnsAfterAClear_isInTheReSetLock():
    """
    Given: a clearable pending-only MINOR P0442 (synced, pending read)
    When: Mode 04 runs and the re-read reports P0442 pending again
    Then: P0442 is a re-set code -- the session lock covers pending unchanged
          (_codesPresentBefore already counts pending; no change there).
    """
    state = {
        "codes": [{"code": "P0442", "status": "pending", "severity": "minor",
                   "logged": True, "syncAcked": True}],
        "pendingCheckedAtTs": READ_TS,
        "sessionResetLock": [],
    }

    outcome = dtc_clear.performClear(
        state, clearRunner=lambda: {"stored": [], "pending": ["P0442"], "mil": False}
    )

    assert outcome.issued is True
    assert outcome.reSetCodes == ["P0442"]
    # ... and once that lock is published, the next clear is refused for it.
    locked = {**state, "sessionResetLock": outcome.reSetCodes}
    assert dtc_clear.evaluateClearGate(locked).reason == dtc_clear.GATE_SESSION_LOCKED


def test_anAbsentPendingCheckedAtTs_readsAsNotRead():
    """
    Given: a state with a clearable stored MINOR and NO pendingCheckedAtTs key
    When: the authoritative gate runs
    Then: pending_not_read -- an absent time is never read as "checked".
    """
    state = {"codes": [{"code": "P0443", "status": "stored", "severity": "minor",
                        "logged": True, "syncAcked": True}]}

    assert dtc_clear.evaluateClearGate(state).reason == dtc_clear.GATE_PENDING_NOT_READ
    assert dtc_clear.GATE_PENDING_NOT_READ == "pending_not_read"


def test_buildDtcState_publishesTheTableGate_withTheReadTimeAndLockItCarries():
    """
    Given: the story's two examples, assembled by the real builder
    When: buildDtcState publishes them
    Then: the published clearGate is the reason the table names for each.
    """
    table = {
        "P0443": {"severity": "minor", "severityCaveat": None, "short": "s", "long": "l",
                  "suggestedFix": None, "fixProvenance": "none", "clearEligible": True},
        "P0400": {"severity": "watch", "severityCaveat": None, "short": "s", "long": "l",
                  "suggestedFix": None, "fixProvenance": "none", "clearEligible": False},
    }

    def raw(code: str, status: str) -> dict:
        return {"code": code, "status": status, "description": "", "driveId": None,
                "setAtTs": None, "logged": True, "syncAcked": True}

    both = dtc_emitter.buildDtcState(
        codes=[raw("P0443", "stored"), raw("P0400", "pending")], severityTable=table,
        mil=True, newSinceTs=None, sessionResetLock=[], nowIso=READ_TS,
        pendingCheckedAtTs=READ_TS,
    )
    unread = dtc_emitter.buildDtcState(
        codes=[raw("P0443", "stored")], severityTable=table, mil=True, newSinceTs=None,
        sessionResetLock=[], nowIso=READ_TS, pendingCheckedAtTs=None,
    )
    locked = dtc_emitter.buildDtcState(
        codes=[raw("P0443", "stored")], severityTable=table, mil=True, newSinceTs=None,
        sessionResetLock=["P0443"], nowIso=READ_TS, pendingCheckedAtTs=READ_TS,
    )

    assert both["clearGate"] == {"enabled": False, "reason": "severity_present"}
    assert unread["clearGate"] == {"enabled": False, "reason": "pending_not_read"}
    assert locked["clearGate"] == {"enabled": False, "reason": "session_locked"}
