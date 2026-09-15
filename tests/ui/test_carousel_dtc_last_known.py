################################################################################
# File Name: test_carousel_dtc_last_known.py
# Purpose/Description: US-752 (F-123) -- the resting Alerts card shows the codes
#   the system already holds, dated, and never makes them actionable.
#
#   Payloads are built by the REAL emitter (`buildDtcState`), not hand-written
#   (the US-628 lesson): the producer's null live fields and the consumer's
#   rendering are asserted against ONE payload, because it is their join that
#   the operator reads.
#
#   Pinned, in the story's own terms:
#     * key-off with codes held  -> codes + age render; never "not read yet"
#     * never read               -> "DTC not read" still renders
#     * remembered codes         -> no clear offered (display mirror AND the
#                                   authoritative gate, runner never called)
#     * remembered codes         -> no takeover, no ribbon, newSinceTs null
#
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Ralph (Rex)  | Initial -- US-752 last-known Alerts card.
# ================================================================================
################################################################################

"""US-752 tests: remembered DTCs at rest -- shown, dated, never actionable."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "src"))

import render_harness as rh  # noqa: E402

from pi.splash import dtc_clear  # noqa: E402
from pi.splash.dtc_emitter import buildDtcState  # noqa: E402

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

_AS_OF = "2026-09-14T09:00:00Z"
_NOW_ISO = "2026-09-14T12:00:00Z"
_NOW_MS = int(datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)

# The two codes stored on the car. Neither is in the shipped P1xxx table, so an
# empty table reproduces their live `unknown` enrichment.
_TABLE: dict[str, dict[str, Any]] = {}


def _lastKnown() -> dict[str, Any]:
    """The readLastKnownDtcs shape, as the reader returns it."""
    return {
        "codes": [
            {
                "code": "P0443",
                "status": "stored",
                "description": "EVAP purge control valve circuit",
                "driveId": None,
                "lastSeenTs": _AS_OF,
            },
            {
                "code": "P0400",
                "status": "stored",
                "description": "EGR flow",
                "driveId": None,
                "lastSeenTs": "2026-09-13T18:00:00Z",
            },
        ],
        "asOfTs": _AS_OF,
        "source": "dtc_log",
    }


def _resting(lastKnown: dict[str, Any] | None) -> dict[str, Any]:
    """The payload the boot / key-off path publishes (link down)."""
    return buildDtcState(
        codes=[],
        severityTable=_TABLE,
        mil=False,
        newSinceTs=None,
        sessionResetLock=[],
        nowIso=_NOW_ISO,
        dtcAvailable=False,
        lastKnown=lastKnown,
    )


def _probe(fn: str, *args: Any) -> Any:
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _surface(state: dict[str, Any]):
    return rh.dashboardSurface(
        rh.runDashboard(routes={"/dtc": state}, nowMs=_NOW_MS)["tree"]
    )


def _textOf(node: dict) -> list[str]:
    out = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _alertsText(state: dict[str, Any]) -> str:
    surface = _surface(state)
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == "dtc":
            return " ".join(_textOf(path[-1]))
    return ""


def test_restingPayload_liveFieldsAreNull_lastKnownIsDated():
    """
    Given: the link is down and codes were read before
    When: the resting state is built
    Then: codes/mil are null (not []/false) beside available:false, and the
          lastKnown block carries both codes, asOfTs and last-known-lit MIL
    """
    state = _resting(_lastKnown())

    assert state["codes"] is None
    assert state["mil"] is None
    assert state["source"]["dtc"]["available"] is False
    assert state["newSinceTs"] is None
    assert state["lastKnown"]["asOfTs"] == _AS_OF
    assert state["lastKnown"]["mil"] is True
    assert state["lastKnown"]["source"] == "dtc_log"
    assert [c["code"] for c in state["lastKnown"]["codes"]] == ["P0443", "P0400"]


def test_alertsCard_keyOffWithKnownCodes_rendersThemWithTheirAge():
    """
    Given: the resting payload holding P0443 + P0400, last read 3 h ago
    When: the shipped card renders it
    Then: both codes and the age are on the card, and it says neither
          "DTC not read" / "not read yet" nor "No stored codes"
    """
    text = _alertsText(_resting(_lastKnown()))

    assert "P0443" in text, text
    assert "P0400" in text, text
    assert "LAST KNOWN CODES" in text, text
    assert "last read 3 h ago" in text, text
    assert "DTC not read" not in text, text
    assert "not read yet" not in text, text
    assert "No stored codes" not in text, text


def test_alertsCard_neverRead_stillRendersNotRead():
    """
    Given: a genuinely never-read state (no dtc_log rows -> lastKnown null)
    When: the card renders
    Then: "DTC not read" -- the true typed absence keeps its meaning
    """
    state = _resting(None)
    assert state["lastKnown"] is None

    text = _alertsText(state)

    assert "DTC not read" in text, text
    assert "LAST KNOWN" not in text, text


def test_rememberedCodes_offerNoClear_onTheDisplayOrTheAuthoritativeGate():
    """
    Given: no live codes but a populated lastKnown
    When: both clear gates are asked
    Then: the display hides the button (no_codes) and the server gate refuses
          WITHOUT calling the Mode-04 runner -- a clear on remembered codes is a
          safety inversion
    """
    state = _resting(_lastKnown())

    button = _probe("clearButtonView", state)
    assert button["visible"] is False, button
    assert button["reason"] == "no_codes", button

    calls: list[int] = []
    outcome = dtc_clear.performClear(
        state, clearRunner=lambda: calls.append(1) or {"stored": [], "pending": []}
    )
    assert outcome.issued is False
    assert outcome.reason == dtc_clear.GATE_NO_CODES
    assert calls == []


def test_rememberedCodes_neverTriggerTheTakeoverOrTheRibbon():
    """
    Given: the resting payload with remembered codes
    When: the US-405 takeover and the ribbon are evaluated
    Then: newSinceTs is null, neither view exists, and the ribbon does not paint
    """
    state = _resting(_lastKnown())

    assert state["newSinceTs"] is None
    assert _probe("takeoverView", state) is None
    assert _probe("ribbonView", state) is None

    surface = _surface(state)
    ribbon = surface.pathById("dtc-ribbon")
    assert ribbon is None or not surface.rendered(ribbon)
