################################################################################
# File Name: test_dtc_clear_gate_severity_unknown.py
# Purpose/Description: US-753 [F-123] -- the clear gate refuses an ungraded code
#   with its OWN reason. `severity_present` carried two facts: "a STOP/WATCH
#   code is present" and "severity is unknown, so refuse on principle". The
#   second now reads `severity_unknown` ("severity could not be determined") in
#   all three gate implementations -- the published emitter block, the
#   authoritative dtc_clear, and the carousel.js display mirror. The REFUSAL is
#   unchanged: `enabled` stays false and the Mode-04 runner is never called.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Ralph (Rex)  | Initial -- US-753 split severity_unknown out of
#               |              | severity_present.
# ================================================================================
################################################################################

"""US-753 tests: an unknown severity is refused as unknown, never as STOP/WATCH."""

from __future__ import annotations

import os
import re
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "src"))

from test_carousel_dtc_clear_gate_unread import (  # noqa: E402
    _OPEN_DETAIL,
    _SHIPPED_TABLE_PATH,
    _clearSurface,
    _needsNode,
)
from test_dtc_detail_hierarchy import _NODE_TESTS, _probe  # noqa: E402

from pi.splash import dtc_clear  # noqa: E402
from pi.splash.dtc_emitter import buildDtcState  # noqa: E402
from pi.splash.dtc_severity_table import loadP1xxxSeverityTable  # noqa: E402

_JS = os.path.join(_REPO, "src", "pi", "ui", "dashboard", "carousel.js")

_LABEL_SEVERITY = "🔒 CLEAR CODES — a STOP/WATCH code is present"
_LABEL_UNKNOWN = "🔒 CLEAR CODES — severity could not be determined"

# A fixture table: one clearable MINOR and one WATCH, so the unknown case can be
# set beside each real tier. Un-tabled codes degrade to `unknown` in enrichCode.
_TABLE: dict[str, dict[str, Any]] = {
    "P0442": {
        "severity": "minor",
        "severityCaveat": None,
        "short": "EVAP small leak",
        "long": "EVAP small leak",
        "suggestedFix": "Check the fuel cap seal",
        "fixProvenance": "spool",
        "clearEligible": True,
    },
    "P1300": {
        "severity": "watch",
        "severityCaveat": None,
        "short": "Ignition timing adjust",
        "long": "Ignition timing adjust",
        "suggestedFix": None,
        "fixProvenance": "none",
        "clearEligible": False,
    },
}


def _raw(code: str) -> dict[str, Any]:
    return {
        "code": code,
        "status": "stored",
        "description": "captured description",
        "driveId": None,
        "setAtTs": "2026-09-14T12:00:00Z",
        "logged": True,
        "syncAcked": True,
    }


def _state(codes: list[str], table: dict[str, dict[str, Any]] | None = None) -> dict:
    return buildDtcState(
        codes=[_raw(c) for c in codes],
        severityTable=_TABLE if table is None else table,
        mil=True,
        newSinceTs=None,
        sessionResetLock=[],
        nowIso="2026-09-14T12:00:00Z",
    )


def _neverRuns() -> tuple[list[int], Any]:
    calls: list[int] = []

    def runner() -> dict:
        calls.append(1)
        return {"stored": [], "pending": [], "mil": False}

    return calls, runner


# ---------------------------------------------------------------------------
# VC1 + VC3 -- two unknown codes: unknown reason, still refused, no write.
# ---------------------------------------------------------------------------


def test_twoUnknownCodes_emitterPublishesSeverityUnknown_stillDisabled():
    """
    Given: two stored codes the table does not grade (P0443, P0400 -> `unknown`)
    When: the emitter computes the published clearGate
    Then: {enabled: False, reason: severity_unknown} -- not severity_present.
    """
    state = _state(["P0443", "P0400"])

    assert [c["severity"] for c in state["codes"]] == ["unknown", "unknown"]
    assert state["clearGate"] == {"enabled": False, "reason": "severity_unknown"}


def test_twoUnknownCodes_authoritativeGateRefusesAsUnknown_runnerNeverCalled():
    """
    Given: the same two ungraded codes
    When: a clear is submitted at the privileged action path
    Then: refused with GATE_SEVERITY_UNKNOWN and the Mode-04 runner never runs.
    """
    calls, runner = _neverRuns()
    state = _state(["P0443", "P0400"])

    decision = dtc_clear.evaluateClearGate(state)
    outcome = dtc_clear.performClear(state, clearRunner=runner)

    assert dtc_clear.GATE_SEVERITY_UNKNOWN == "severity_unknown"
    assert decision == dtc_clear.ClearGateDecision(
        enabled=False, reason=dtc_clear.GATE_SEVERITY_UNKNOWN
    )
    assert outcome.issued is False and outcome.reason == "severity_unknown", outcome
    assert calls == [], "an ungraded code reached the vehicle-write runner"


@_needsNode
def test_twoUnknownCodes_panelSaysSeverityCouldNotBeDetermined_buttonDisabled():
    """
    Given: the same two ungraded codes, rendered through the shipped carousel.js
    When: the operator opens the detail
    Then: the <button> is disabled and says severity could not be determined; it
          does NOT claim a STOP/WATCH code is present.
    """
    got = _clearSurface(_state(["P0443", "P0400"]), _OPEN_DETAIL)

    assert got["buttonPaints"] is True, got
    assert got["disabled"] is True, got
    assert got["reason"] == "severity_unknown", got
    assert got["label"] == _LABEL_UNKNOWN, got
    assert "STOP" not in got["label"] and "WATCH" not in got["label"], got


# ---------------------------------------------------------------------------
# VC2 + VC3 -- a genuine WATCH code: the existing path, unchanged.
# ---------------------------------------------------------------------------


def test_genuineWatchCode_allThreeGatesStillSaySeverityPresent():
    """
    Given: a stored WATCH code (P1300)
    When: the emitter and the authoritative gate evaluate it
    Then: both say severity_present, disabled, runner never called.
    """
    calls, runner = _neverRuns()
    state = _state(["P1300"])

    assert state["clearGate"] == {"enabled": False, "reason": "severity_present"}
    assert dtc_clear.evaluateClearGate(state).reason == dtc_clear.GATE_SEVERITY
    assert dtc_clear.performClear(state, clearRunner=runner).issued is False
    assert calls == []


@_needsNode
def test_genuineWatchCode_panelStillShowsTheStopWatchLabel():
    """
    Given: a stored WATCH code
    When: its detail is opened on the panel
    Then: disabled, severity_present, the existing STOP/WATCH label verbatim.
    """
    got = _clearSurface(_state(["P1300"]), _OPEN_DETAIL)

    assert got["disabled"] is True, got
    assert got["reason"] == "severity_present", got
    assert got["label"] == _LABEL_SEVERITY, got


# ---------------------------------------------------------------------------
# Precedence and edge shapes.
# ---------------------------------------------------------------------------


def test_watchBesideUnknown_severityPresentWins_becauseItIsTrue():
    """
    Given: a WATCH code AND an ungraded code stored together
    When: the gate runs
    Then: severity_present -- a STOP/WATCH code IS present, which is the more
          operator-relevant of two true reasons.
    """
    state = _state(["P0443", "P1300"])

    assert state["clearGate"]["reason"] == "severity_present"
    assert dtc_clear.evaluateClearGate(state).reason == dtc_clear.GATE_SEVERITY


def test_unknownBesideMinor_isRefusedAsUnknown():
    """
    Given: a clearable MINOR code beside an ungraded one
    When: the gate runs (Mode 04 is all-or-nothing)
    Then: severity_unknown, disabled.
    """
    state = _state(["P0442", "P0443"])

    assert state["clearGate"] == {"enabled": False, "reason": "severity_unknown"}
    assert dtc_clear.evaluateClearGate(state).reason == dtc_clear.GATE_SEVERITY_UNKNOWN


@pytest.mark.parametrize("severity", [None, "", "critical"])
def test_missingOrUnrecognisedSeverity_isUnknown_notStopWatch(severity: Any):
    """
    Given: a stored code whose severity is absent or outside the tier vocabulary
    When: the authoritative gate runs
    Then: severity_unknown -- the gate cannot know it is STOP/WATCH either.
    """
    code = {"code": "P0443", "status": "stored", "severity": severity,
            "logged": True, "syncAcked": True}

    decision = dtc_clear.evaluateClearGate({"codes": [code]})

    assert decision == dtc_clear.ClearGateDecision(
        enabled=False, reason=dtc_clear.GATE_SEVERITY_UNKNOWN
    )


@_NODE_TESTS
@pytest.mark.parametrize("severity", ["unknown", None, "critical"])
def test_displayMirror_missingOrUnrecognisedSeverity_isUnknown(severity: Any):
    """The pure carousel.js mirror agrees with dtc_clear on every non-tier value."""
    code = {"code": "P0443", "status": "stored", "severity": severity,
            "logged": True, "syncAcked": True}

    view = _probe("clearButtonView", {"codes": [code]})

    assert view["enabled"] is False, view
    assert view["reason"] == "severity_unknown", view
    assert view["label"] == _LABEL_UNKNOWN, view


def test_theLiveShippedTable_refusesP0443AsUnknown():
    """
    Given: the severity table the Pi loads, which has no P0443 row
    When: the live car's stored P0443 is gated
    Then: severity_unknown -- the F3 finding from US-636, now told truthfully.
    """
    table = loadP1xxxSeverityTable(_SHIPPED_TABLE_PATH)
    assert "P0443" not in table

    assert _state(["P0443"], table=table)["clearGate"]["reason"] == "severity_unknown"


# ---------------------------------------------------------------------------
# One vocabulary: every authoritative reason has a display label.
# ---------------------------------------------------------------------------


def test_everyDisabledGateReason_hasItsOwnDistinctPanelLabel():
    """
    Given: the authoritative GATE_* reasons in dtc_clear
    When: carousel.js CLEAR_REASON_LABEL keys are extracted
    Then: every reason the button can show (all but no_codes, which hides it)
          has a label, and no two reasons share one string.
    """
    with open(_JS, encoding="utf-8") as fh:
        src = fh.read()
    block = re.search(r"var CLEAR_REASON_LABEL = \{(.*?)\};", src, re.S)
    assert block, "CLEAR_REASON_LABEL table not found in carousel.js"
    labels = dict(re.findall(r'^\s*(\w+):\s*"([^"]*)"', block.group(1), re.M))

    reasons = {
        getattr(dtc_clear, name) for name in dtc_clear.__all__ if name.startswith("GATE_")
    }
    assert reasons - {dtc_clear.GATE_NO_CODES} == set(labels), (reasons, labels)
    assert len(set(labels.values())) == len(labels), labels
