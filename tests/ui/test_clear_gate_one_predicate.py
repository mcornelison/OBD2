################################################################################
# File Name: test_clear_gate_one_predicate.py
# Purpose/Description: US-919 [F-161] -- the carousel.js copy of the DTC clear
#   gate (clearGateReason, the page's button state) answers the SAME reason as
#   the two Python copies for every row of the shared case table
#   (tests/pi/splash/clear_gate_cases.py), and the page's Clear button shows the
#   new `pending_not_read` label parked or moving, while `moving` still replaces
#   only an otherwise-ok gate (Atlas RULED 2026-10-21 (B)).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-21    | Ralph (Rex)  | Initial -- US-919 one predicate, one table.
# 2026-10-22    | Ralph (Rex)  | US-511-b MOVED PIN: moving reads 'stop to clear'
#               |              | over a known gear; 'gear unknown' otherwise.
# ================================================================================
################################################################################

"""US-919 tests: carousel.js clearGateReason agrees with the Python copies."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

import pytest

from pi.splash import dtc_clear
from tests.pi.splash.clear_gate_cases import CLEAR_GATE_CASES, READ_TS
from tests.pi.splash.test_clear_gate_one_predicate import dtcStateOf

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "carousel_probe.js")

_needsNode = pytest.mark.skipif(
    _NODE is None, reason="node not on PATH -- carousel.js is evaluated under node"
)

# The page labels (carousel.js CLEAR_REASON_LABEL). pending_not_read is Iris's
# 2026-10-20 text, verbatim from the story.
# MOVED PIN (US-511-b, Atlas B2): moving is 'stop to clear' (was 'engine off
# to clear'), and an unknown gear has its own word.
_LABEL_PENDING_NOT_READ = "🔒 CLEAR CODES — pending codes haven’t been read"
_LABEL_MOVING = "🔒 CLEAR CODES — stop to clear"
_LABEL_GEAR_UNKNOWN = "🔒 CLEAR CODES — gear unknown"


def _map(fn: str, argLists: list[list[Any]]) -> list[Any]:
    """Evaluate one carousel.js export once per argument list (probe --map)."""
    proc = subprocess.run(
        [_NODE or "node", _PROBE, "--map", fn],
        input=json.dumps(argLists),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@_needsNode
def test_displayMirror_answersTheTableReason_forEveryRow():
    """
    Given: every row of the shared case table
    When: carousel.js clearGateReason evaluates each, and dtc_clear does too
    Then: the page's reason is the row's reason -- and dtc_clear's -- row by row.
    """
    states = [dtcStateOf(c) for c in CLEAR_GATE_CASES]

    page = _map("clearGateReason", [[s] for s in states])

    got = {c["id"]: r for c, r in zip(CLEAR_GATE_CASES, page, strict=True)}
    want = {c["id"]: c["expected"] for c in CLEAR_GATE_CASES}
    authoritative = {
        c["id"]: dtc_clear.evaluateClearGate(s).reason
        for c, s in zip(CLEAR_GATE_CASES, states, strict=True)
    }
    assert got == want
    assert got == authoritative


def _storedMinor(pendingCheckedAtTs: str | None) -> dict[str, Any]:
    return {
        "codes": [{"code": "P0443", "status": "stored", "severity": "minor",
                   "logged": True, "syncAcked": True}],
        "pendingCheckedAtTs": pendingCheckedAtTs,
        "sessionResetLock": [],
    }


@_needsNode
@pytest.mark.parametrize("parked", [True, False], ids=["parked", "moving"])
def test_pendingUnread_buttonIsVisibleDisabledAndSaysPendingNotRead(parked: bool):
    """
    Given: a stored MINOR (logged, synced) and pendingCheckedAtTs null
    When: the page builds the Clear button, parked OR moving
    Then: visible, disabled, the pending_not_read label in both -- `moving`
          never replaces a reason other than ok.
    """
    [view] = _map("clearButtonView", [[_storedMinor(None), parked]])

    assert view == {
        "visible": True,
        "enabled": False,
        "reason": "pending_not_read",
        "label": _LABEL_PENDING_NOT_READ,
    }


@_needsNode
def test_pendingRead_moving_readsStopToClear_onlyOverOk():
    """
    MOVED PIN (US-511-b): was ..._readsEngineOffToClear_onlyOverOk.

    Given: a stored MINOR synced, pending read, no lock
    When: the page builds the Clear button while moving (gear known), with the
          gear unknown, and while parked
    Then: moving -> 'stop to clear'; unknown -> 'gear unknown' (both over ok
          only); parked -> ok.
    """
    moving, unknown, parked = _map(
        "clearButtonView",
        [
            [_storedMinor(READ_TS), False, True],
            [_storedMinor(READ_TS), False, False],
            [_storedMinor(READ_TS), True, True],
        ],
    )

    assert moving["reason"] == "moving" and moving["label"] == _LABEL_MOVING, moving
    assert moving["enabled"] is False, moving
    assert unknown["reason"] == "parked_unknown", unknown
    assert unknown["label"] == _LABEL_GEAR_UNKNOWN and unknown["enabled"] is False, unknown
    assert parked["reason"] == "ok" and parked["enabled"] is True, parked


@_needsNode
def test_pendingOnlyMinor_showsTheButton_notNoCodes():
    """
    Given: a pending-only MINOR, synced, pending read
    When: the page builds the Clear button parked
    Then: visible and enabled -- a pending-only set is NOT no_codes.
    """
    state = {
        "codes": [{"code": "P0443", "status": "pending", "severity": "minor",
                   "logged": True, "syncAcked": True}],
        "pendingCheckedAtTs": READ_TS,
        "sessionResetLock": [],
    }

    [view] = _map("clearButtonView", [[state, True]])

    assert view["visible"] is True and view["enabled"] is True, view
    assert view["reason"] == "ok", view
