################################################################################
# File Name: test_carousel_loading_state.py
# Purpose/Description: US-700 (F-123) tests -- LOADING is a third state, and it
#   was missing. A tile whose payload had NOT ARRIVED YET rendered
#   `— / unavailable`, byte-identical to what it renders when the producer is
#   DEAD. The CIO read a working panel at boot as a defect, which is exactly the
#   misreading the render invited: one string covering two opposite situations.
#
#   The three states this file pins apart, on every affected surface:
#     loading     -- nothing has arrived yet, and the bound is still open
#     ready-but-unusable -- the payload arrived and is not renderable: today's
#                    typed NA + reason, UNCHANGED (loading must never dress a
#                    broken feed up as a starting one)
#     unavailable -- no producer, or one that answered once and then died
#
#   THE TWO PINS THAT DO THE REAL WORK, because a naive fix passes everything
#   else: (1) an ARRIVED-but-unusable payload must NOT become "loading" -- that
#   would hide a real defect behind a reassuring word; (2) LOADING must EXPIRE.
#   A tile that says LOADING forever is the same defect wearing a nicer word, so
#   the bound is asserted on both sides and grounded against the producer's own
#   publish cadence rather than a number somebody liked.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-10    | Ralph (Rex)  | Initial -- US-700 loading vs unavailable.
# ================================================================================
################################################################################

"""US-700: a tile can say whether it is still loading or genuinely broken."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

import pytest

from pi.obdii.orchestrator.types import DEFAULT_CARD_STATE_EMIT_INTERVAL
from tests.ui import render_harness as rh

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_DIST = os.path.join(_ROOT, "src", "pi", "ui", "dashboard")
_JS = os.path.join(_DIST, "carousel.js")
_CSS = os.path.join(_DIST, "dashboard.css")

# The panel the copy is actually read on (480x320, US-482 design box).
PANEL = (480, 320)

_TS = "2026-09-10T12:00:00+00:00"
_NOW_MS = 1789041600000  # the virtual wall clock; only {advanceMs} moves it

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _view(fn: str, *args: object) -> Any:
    """Evaluate one carousel.js export against fixtures via the node probe."""
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _grace() -> int:
    """The shipped bound, read from the shipped module -- never re-typed here."""
    return int(_view("loadingGraceMs"))


def _status(**extra: object) -> dict:
    payload: dict = {
        "drive": {"state": "idle", "driveId": None,
                  "lastDrive": {"driveId": 35, "startedAtTs": "2026-09-10T10:00:00Z"}},
        "idle": True,
        "ts": _TS,
    }
    payload.update(extra)
    return payload


def _upsDownBattery() -> dict:
    """A battery payload that ARRIVED and is unusable -- the UPS is not readable.

    This is the fixture the whole story turns on: it must keep today's typed NA,
    because the panel genuinely knows something here and "loading" would throw
    that knowledge away.
    """
    return {"ts": _TS, "source": {"ups": {"available": False,
                                          "reason": "gauge unreadable"}}}


# ---------------------------------------------------------------------------
# THE PREDICATE. One rule, asked by every surface that renders a whole payload.
# ---------------------------------------------------------------------------


def test_loadPhase_payloadInHand_isReadyEvenAtZeroWait():
    """An ARRIVED payload always wins. Loading is about the waiting room, and a
    payload that is here was never in it."""
    assert _view("loadPhase", {"ts": _TS}, 0) == "ready"


def test_loadPhase_nothingArrivedYet_isLoading():
    """The pre-fetch window -- the state that did not exist before this story."""
    assert _view("loadPhase", None, 0) == "loading"


def test_loadPhase_justInsideTheBound_isStillLoading():
    """One millisecond under is still starting up."""
    assert _view("loadPhase", None, _grace() - 1) == "loading"


def test_loadPhase_atTheBound_fallsThroughToUnavailable():
    """THE BOUND. A tile that says LOADING forever is the same defect wearing a
    nicer word, so the pre-fetch state EXPIRES."""
    assert _view("loadPhase", None, _grace()) == "unavailable"


def test_loadPhase_wellPastTheBound_staysUnavailable():
    """And it does not oscillate back once expired."""
    assert _view("loadPhase", None, _grace() * 10) == "unavailable"


def test_loadPhase_feedThatAnsweredOnceAndDied_isNeverLoadingAgain():
    """A null `waitedMs` is the ledger saying 'this feed HAS answered'. A dead
    producer must read as broken, not as one that is still starting -- otherwise
    every mid-drive feed death re-acquires the reassuring word."""
    assert _view("loadPhase", None, None) == "unavailable"


def test_loadPhase_negativeWait_isUnavailableNotLoading():
    """Clock skew is real on this Pi (no RTC battery, boots before NTP). A
    negative wait is nonsense, and nonsense resolves to the honest state."""
    assert _view("loadPhase", None, -5000) == "unavailable"


def test_loadingGrace_isGroundedOnTheProducersPublishCadence():
    """RULE 2. The bound is not a number somebody liked: it is THREE consecutive
    missed publications of the card-state emitter. Change the emitter's cadence
    and this fails, which is the point -- the two numbers are one fact."""
    assert _grace() == int(3 * DEFAULT_CARD_STATE_EMIT_INTERVAL * 1000)


# ---------------------------------------------------------------------------
# THE LEDGER. Which feeds have ever answered -- the state loading turns on.
# ---------------------------------------------------------------------------


def test_feedWaitedMs_neverAnswered_reportsTheWaitSoFar():
    assert _view("feedWaitedMs", {}, "system-status", 1000, 3500) == 2500


def test_feedWaitedMs_alreadyAnswered_reportsNoWait():
    """Null, not 0: 0 would read as 'just started waiting' and put a dead feed
    back into loading at every tick."""
    assert _view("feedWaitedMs", {"system-status": True},
                 "system-status", 1000, 999999) is None


def test_feedObserved_realPayload_marksTheFeedAnswered():
    assert _view("feedObserved", {}, "imu", {"ts": _TS}) == {"imu": True}


def test_feedObserved_nullRead_leavesTheFeedInTheWaitingRoom():
    """A 404 / abort / malformed read is not an answer. If it marked the feed
    answered, LOADING would end on the first failed fetch -- i.e. never fire."""
    assert _view("feedObserved", {}, "imu", None) == {}


def test_feedObserved_answeredThenNull_staysAnswered():
    """The death case, recorded: once a feed has spoken, a later silence is a
    silence FROM a known-live producer."""
    assert _view("feedObserved", {"imu": True}, "imu", None) == {"imu": True}


# ---------------------------------------------------------------------------
# LAST DRIVE -- one of the three tiles the CIO misread.
# ---------------------------------------------------------------------------


def test_idleLastDriveFact_prefetch_readsAsLoading():
    fact = _view("idleLastDriveFact", None, 0)

    assert fact["level"] == "loading"
    assert "LOADING" in fact["value"]


def test_idleLastDriveFact_prefetchAndAbsent_areNotConfusable():
    """THE STORY. The two renders must differ in the slot the operator reads at
    arm's length -- not merely in a level attribute the panel does not speak."""
    loading = _view("idleLastDriveFact", None, 0)
    absent = _view("idleLastDriveFact", None, None)

    assert loading["value"] != absent["value"]
    assert loading["detail"] != absent["detail"]
    assert loading["level"] != absent["level"]


def test_idleLastDriveFact_noProducer_keepsTodaysUnavailable():
    """The dead-producer render is UNCHANGED -- this story adds a state, it does
    not restyle the one that was already honest."""
    fact = _view("idleLastDriveFact", None, None)

    assert fact["value"] == "—"
    assert fact["detail"] == "unavailable"
    assert fact["level"] == "unavailable"


def test_idleLastDriveFact_arrivedButUnusable_isNotDressedUpAsLoading():
    """THE PIN THAT KILLS THE NAIVE FIX. The payload is HERE and carries no
    drive block -- a real absence of a source. Calling that "loading" would hide
    a defect behind a reassuring word, which is the same class of lie this story
    exists to remove."""
    fact = _view("idleLastDriveFact", {"idle": True, "ts": _TS}, 0)

    assert fact["level"] == "unavailable"
    assert "LOADING" not in fact["value"]


def test_idleLastDriveFact_realDriveDuringTheWindow_stillRendersTheDrive():
    """Control: an open loading window never suppresses data that arrived."""
    fact = _view("idleLastDriveFact", _status(), 0)

    assert fact["value"] == "Drive 35"


def test_idleLastDriveFact_pastTheBound_fallsThroughToUnavailable():
    fact = _view("idleLastDriveFact", None, _grace())

    assert fact["level"] == "unavailable"


# ---------------------------------------------------------------------------
# BATTERY -- the second misread tile, and the one with a real typed NA to keep.
# ---------------------------------------------------------------------------


def test_idleBatteryFact_prefetch_readsAsLoading():
    fact = _view("idleBatteryFact", None, 0)

    assert fact["level"] == "loading"
    assert "LOADING" in fact["value"]


def test_idleBatteryFact_prefetchAndAbsent_areNotConfusable():
    loading = _view("idleBatteryFact", None, 0)
    absent = _view("idleBatteryFact", None, None)

    assert loading["value"] != absent["value"]
    assert loading["detail"] != absent["detail"]


def test_idleBatteryFact_upsUnreadableDuringTheWindow_keepsTheTypedNaAndReason():
    """AC-2 verbatim: a payload present but unusable keeps today's typed NA plus
    the REASON. The reason is the operator's only lead on what to fix."""
    fact = _view("idleBatteryFact", _upsDownBattery(), 0)

    assert fact["value"] == "NA"
    assert fact["detail"] == "gauge unreadable"
    assert fact["level"] == "unavailable"


def test_idleBatteryFact_pastTheBound_fallsThroughToUnavailable():
    fact = _view("idleBatteryFact", None, _grace())

    assert fact["level"] == "unavailable"
    assert fact["detail"] == "unavailable"


# ---------------------------------------------------------------------------
# THE MOTION CARD -- the third, and the one with its own arbiter (homeFace).
# ---------------------------------------------------------------------------


def test_homeFace_prefetch_saysItIsWaitingNotThatTheFeedIsGone():
    face = _view("homeFace", None, _NOW_MS, 0)

    assert face["face"] == "idle"
    assert face["loading"] is True
    assert face["reason"] != "no motion feed"


def test_homeFace_noProducer_keepsTodaysNoMotionFeedReason():
    face = _view("homeFace", None, _NOW_MS, None)

    assert face["face"] == "idle"
    assert face["loading"] is False
    assert face["reason"] == "no motion feed"


def test_homeFace_unwiredSensorDuringTheWindow_isNotReportedAsLoading():
    """THE SECOND PIN. The bridge ANSWERED and said `available:false`. That is a
    known-broken instrument with a reason, and the reason must survive: a
    "loading" hero here would tell the operator to keep waiting for a sensor
    that is never coming."""
    face = _view("homeFace", {"available": False, "ts": _TS,
                              "reasons": {"gLat": "imu not wired"}},
                 _NOW_MS, 0)

    assert face["loading"] is False
    assert face["reason"] == "imu not wired"


def test_homeFace_pastTheBound_stopsSayingLoading():
    face = _view("homeFace", None, _NOW_MS, _grace())

    assert face["loading"] is False


# ---------------------------------------------------------------------------
# THE ASSEMBLED IDLE FACE -- what the renderer is actually handed.
# ---------------------------------------------------------------------------


def test_idleCardView_everythingLoading_carriesLoadingToBothFactsAndTheHero():
    view = _view("idleCardView", None, None, "waiting for first read",
                 {"systemStatus": 0, "battery": 0, "motionLoading": True})

    assert view["facts"]["lastDrive"]["level"] == "loading"
    assert view["facts"]["battery"]["level"] == "loading"
    assert view["hero"]["title"] != "NO MOTION DATA"


def test_idleCardView_loadingFooter_doesNotPromiseAReturn():
    """"resumes when the motion feed returns" is a claim that it was ever here.
    At first paint it was not, and a footer is copy the operator believes."""
    view = _view("idleCardView", None, None, "waiting for first read",
                 {"systemStatus": 0, "battery": 0, "motionLoading": True})

    assert "returns" not in view["footer"]


def test_idleCardView_noWaitsSupplied_isTodaysViewUnchanged():
    """The regression pin: every pre-US-700 caller passes three arguments, and
    the fourth being absent must leave the shipped face exactly as it was."""
    view = _view("idleCardView", None, None, "no motion feed")

    assert view["hero"]["title"] == "NO MOTION DATA"
    assert view["footer"] == "live instrument resumes when the motion feed returns"
    assert view["facts"]["battery"]["level"] == "unavailable"


# ---------------------------------------------------------------------------
# THE SOURCE CARDS -- siblings of the BATTERY tile. Leaving them inconsistent
# re-creates the confusion one swipe away (conditionalOutcome 1).
# ---------------------------------------------------------------------------


def _batterySpec() -> dict:
    for spec in _view("sourceCardSpecs"):
        if spec["key"] == "battery-health":
            return spec
    raise AssertionError("no battery-health source card spec")


def _fuelTrimSpec() -> dict:
    for spec in _view("sourceCardSpecs"):
        if spec["key"] == "ltft-trend":
            return spec
    raise AssertionError("no ltft-trend source card spec")


def test_sourceCardView_prefetch_isLoadingNotAConfidentFeedAbsent():
    view = _view("sourceCardView", _batterySpec(), None, _status(), None,
                 _NOW_MS, 0)

    assert view["loading"] is True
    assert view["unavailable"] is False


def test_sourceCardView_noProducer_keepsTheShippedFeedAbsentWording():
    view = _view("sourceCardView", _batterySpec(), None, _status(), None,
                 _NOW_MS, None)

    assert view["loading"] is False
    assert view["unavailable"] is True
    assert view["na"]["reason"] == "no data -- UPS feed absent"


def test_sourceCardView_gatedCardDuringTheWindow_staysGated():
    """The vehicle gate wins. A gated card carries no reading to be waiting for,
    and "loading" over a bench with no car would be a promise of data that
    cannot arrive until an engine does."""
    view = _view("sourceCardView", _fuelTrimSpec(), None, _status(), None,
                 _NOW_MS, 0)

    assert view["gated"] is True
    assert view["loading"] is False


# ---------------------------------------------------------------------------
# END TO END: the SHIPPED carousel over the SHIPPED markup, with NO state files
# at all -- the 5-second frame and the 60-second frame the CIO photographs.
# ---------------------------------------------------------------------------


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("children", []) or []:
            yield from _walk(child)


def _classes(node: dict[str, Any]) -> set[str]:
    return set(str(node.get("attrs", {}).get("class") or "").split())


def _text(node: dict[str, Any] | None) -> str:
    if node is None:
        return ""
    if "text" in node:
        return str(node["text"])
    return " ".join(_text(c) for c in node.get("children", []) or []).strip()


def _homeText(tree: dict[str, Any]) -> str:
    for node in _walk(tree):
        if node.get("attrs", {}).get("id") == "home-card":
            return _text(node)
    raise AssertionError("no home card in the rendered tree")


def _levels(tree: dict[str, Any]) -> list[str]:
    return [
        str(node.get("attrs", {}).get("data-level"))
        for node in _walk(tree)
        if "tile" in _classes(node) and node.get("attrs", {}).get("data-level")
    ]


def _boot(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The SHIPPED panel with NO state files at all -- every fetch 404s.

    That is precisely the CIO's boot: the producers exist but have not written
    yet, and the panel must not claim they are gone.
    """
    return rh.runDashboard(
        routes={},
        steps=steps,
        viewport=PANEL,
        nowMs=_NOW_MS,
    )["tree"]


def _frames() -> tuple[dict[str, Any], dict[str, Any]]:
    """The 5-second frame and the 60-second frame, from the same starting state.

    The LATE frame is a boot that then WAITED past the bound -- the panel is
    given every chance to keep saying LOADING and must stop on its own.
    """
    early = _boot([{"flush": 4}])
    late = _boot([{"flush": 4}, {"advanceMs": _grace() + 4000}, {"flush": 4}])
    return early, late


def test_shippedPanel_earlyFrame_readsAsLoading():
    early, _late = _frames()

    assert "LOADING" in _homeText(early)


def test_shippedPanel_lateFrame_hasStoppedSayingLoading():
    """THE BOUND, end to end. The panel must reach a verdict on its own."""
    _early, late = _frames()

    assert "LOADING" not in _homeText(late)


def test_shippedPanel_theTwoFramesAreNotConfusable():
    """AC-4 in the only form a bench can settle: the operator photographs two
    frames and they must not read the same."""
    early, late = _frames()

    assert _homeText(early) != _homeText(late)


def test_shippedPanel_earlyFrame_paintsTheLoadingLevel():
    """The level reaches the DOM, not just the view object -- a level no
    attribute carries is a level the stylesheet can never colour."""
    early, _late = _frames()

    assert "loading" in _levels(early)


def test_shippedPanel_lateFrame_paintsNoLoadingLevel():
    _early, late = _frames()

    assert "loading" not in _levels(late)
    assert "unavailable" in _levels(late), "the late frame lost its tiles entirely"


# ---------------------------------------------------------------------------
# The stylesheet -- a level with no rule is a level the panel cannot show.
# ---------------------------------------------------------------------------


def test_dashboardCss_carriesTheLoadingLevel():
    css = _read(_CSS)

    assert '.tile[data-level="loading"]' in css


def test_dashboardCss_loadingAndUnavailableAreStyledDifferently():
    """Same colour + same italic = two states that are still confusable on the
    panel, whatever the DOM says. The rules must actually differ."""
    css = _read(_CSS)
    rules = rh.parseCss(css)
    loading = [r for r in rules if r.selector.strip()
               == '.tile[data-level="loading"] .tile-value']
    absent = [r for r in rules if r.selector.strip()
              == '.tile[data-level="unavailable"] .tile-value']

    assert loading, "no .tile[data-level=loading] .tile-value rule"
    assert absent, "the unavailable rule vanished -- the comparison is vacuous"
    assert loading[0].declarations.strip() != absent[0].declarations.strip()


def test_shippedJs_theLoadingRenderReachesTheDom():
    """The browser-only block is invisible to the node probe, so pin that the
    renderer the tick calls actually exists (US-503's lesson: a fact the
    renderer never receives paints nothing)."""
    js = _read(_JS)

    assert "renderLoadingBody" in js
    assert "feedWaitedMs(" in js
