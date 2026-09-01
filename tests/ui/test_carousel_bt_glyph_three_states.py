################################################################################
# File Name: test_carousel_bt_glyph_three_states.py
# Purpose/Description: US-658 (F-138) -- the BT glyph must show THREE distinct
#   states: unknown = NEUTRAL GREY, degraded = AMBER, connected = GREEN
#   (CIO ruling, punch-list H1).
#
#   OUTCOME: RECORDED PASS. The story's headline -- "the BT glyph has no unknown
#   state, so an unread link is indistinguishable from a degraded one" -- is
#   MEASURED FALSE at the glyph. `btGlyphState` (carousel.js:653) returns
#   `neutral` on BOTH of its unknown paths (non-object payload, and a `state`
#   token it does not recognise, which is where `null` lands), and the render
#   path forces `neutral` a second way whenever `source.obd.available` is false.
#   Every one of the seven causes the shipped producer can reach was rendered and
#   read off the panel; the table is in `test_theThreeStatesArePairwiseDistinct`.
#
#   WHY THE STORY IS STILL WORTH ITS TESTS, and it is the same shape US-633 found
#   in the SYNC glyph one story earlier. `btGlyphState` was referenced by ZERO
#   tests in this repository. Four assertions on the glyph's data-state existed
#   (test_carousel_obd_source_unavailable_render.py:497-498/575,
#   test_carousel_obd_link_typed_unknown.py:680/744-745) and they cover only
#   `neutral`, `amber` and `down`. **THE GREEN STATE HAD NEVER BEEN ASSERTED** --
#   the one state a driver reads to mean "the car is talking to me". Everything
#   else on the top bar is layout-only (test_topbar_three_column_grid.py:321,
#   tests/deploy/test_dashboard_kit.py:117 loop over three glyph IDs checking the
#   ELEMENT is laid out; neither reads its state).
#
#   THE LOAD-BEARING PIN IS THE COLOUR, NOT THE TOKEN, and this is what actually
#   reconciles the shipped code to the CIO's ruling. The glyph vocabulary has
#   FOUR tokens -- ok / amber / down / neutral -- and the ruling names THREE
#   states. They agree only because the shipped stylesheet paints `down` and
#   `amber` with the SAME token (dashboard.css:257, a deliberate US-488 call:
#   "a DOWN link is DEGRADED, not dangerous"). Nothing in this repository said
#   so. Assert the tokens alone and a sheet that gave `down` its own hue would
#   leave this file green while the panel grew a fourth state; assert the
#   COLOURS and the ruling is pinned as the driver experiences it.
#
#   THE STORY'S SYMPTOM IS REAL AND IT IS UPSTREAM -- conditionalOutcome 1
#   ("the glyph cannot invent a distinction its SSOT does not carry, and that
#   would be a producer story, not this one") fires. A link that has NEVER been
#   read paints AMBER whenever the reconnect loop is mid-attempt, because
#   `_gatherObdLinkState` returns `available: True` unconditionally on the
#   `reconnecting` branch while gating the `down` branch on
#   `totalConnections > 0`. That is I-us663, already filed, and its two
#   characterisation tests live in test_carousel_obd_link_typed_unknown.py. NOT
#   duplicated here. What this file adds is the ARCH-007 reading of it -- amber
#   is a CLAIM ABOUT A MEASUREMENT -- plus the proof that the divergence is in
#   the PRODUCER and not in either glyph: the BT glyph and the WiFi glyph are
#   shown obeying the SAME source rule on the SAME payload shape.
#
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-658 recorded pass: three glyph
#               |              | states, pinned as COLOURS, plus the never-
#               |              | asserted green and the stale-green reset.
# ================================================================================
################################################################################

"""US-658 tests: the BT glyph shows three distinct states, and unknown is one."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import render_harness as rh  # noqa: E402

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin  # noqa: E402
from pi.splash.system_status_emitter import (  # noqa: E402
    SYSTEM_STATUS_FILENAME,
    buildSystemStatusState,
)

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default: the top bar is laid out under a
# media query and reading it at 1920x1080 measures a bar the driver never sees.
PANEL = (480, 320)

_CAROUSEL_JS = os.path.join(_REPO_ROOT, "src", "pi", "ui", "dashboard", "carousel.js")

# The design tokens the shipped stylesheet resolves each glyph state to. Named
# after the CIO's THREE STATES, not after the four internal tokens, because the
# ruling is about what the driver sees. Resolved through the real cascade below,
# never asserted as a colour name.
GREEN = "var(--green-ok)"       # connected
AMBER = "var(--amber-warn)"     # degraded
NEUTRAL = "var(--text-secondary)"  # unknown

_NOW = "2026-08-31T15:45:52Z"
_FRESH_SYNC = "2026-08-31T15:45:22Z"


# ---------------------------------------------------------------------------
# The REAL acquisition path. Every payload in the recorded-pass sections is
# written to a real file by the real orchestrator emit tick -- no hand-written
# JSON -- so a rename or a re-shape at ANY link in the chain fails here.
# Mirrors tests/ui/test_carousel_obd_link_typed_unknown.py::_Orch.
# ---------------------------------------------------------------------------


class _Orch(CardStateEmitterMixin):
    """The minimal composing object the mixin reads, as the orchestrator does.

    Every source OTHER than OBD is deliberately healthy, so anything unavailable
    this file observes can only have come from the OBD link.
    """

    def __init__(self, statesDir: str, *, connection: Any = None) -> None:
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
            }
        }
        self._connection = connection
        self._driveDetector = None
        self._powerSourceProvider = SimpleNamespace(
            isAvailable=True, isExternalPowerPresent=lambda: True
        )
        self._hardwareManager = None
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = SimpleNamespace(getPowerMode=lambda: "car")
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = _FRESH_SYNC
        self._lastSyncRows = 1204


def _connectionStatus(**kwargs: Any) -> Any:
    base: dict[str, Any] = {
        "connected": False,
        "retryCount": 0,
        "totalConnections": 0,
        "state": "disconnected",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _connection(**status: Any) -> Any:
    return SimpleNamespace(getStatus=lambda: _connectionStatus(**status))


def _raisingConnection() -> Any:
    """A connection whose own status cannot be read -- a fault in the Pi."""

    def _raise() -> Any:
        raise RuntimeError("adapter handle gone")

    return SimpleNamespace(getStatus=_raise)


def _emit(tmp_path, connection: Any = None) -> dict:
    """Run the REAL orchestrator emit once and return what it wrote to disk."""
    statesDir = str(tmp_path / "states")
    orch = _Orch(statesDir, connection=connection)
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True, "the emitter wrote nothing"
    return json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )


# Every cause the shipped producer can reach, keyed by CAUSE so a failure names
# the fault rather than an index, and so a sweep cannot silently lose a branch
# when one is added. `reconnecting` appears twice on purpose: the two differ ONLY
# in whether this Pi has ever spoken to the car, which is the axis I-us663 is
# about, and a single sample would hide that they render identically.
def _allCauses() -> dict[str, Any]:
    return {
        "never_looked": None,
        "status_unreadable": _raisingConnection(),
        "never_connected": _connection(state="disconnected", totalConnections=0),
        "dropped_after_connecting": _connection(
            state="disconnected", retryCount=3, totalConnections=2
        ),
        "reconnecting_never_linked": _connection(
            state="connecting", retryCount=1, totalConnections=0
        ),
        "reconnecting_seen_before": _connection(
            state="reconnecting", retryCount=1, totalConnections=2
        ),
        "linked": _connection(connected=True, state="connected", totalConnections=2),
    }


def _expectedColour(payload: dict) -> str:
    """The CIO's ruling, applied to the SSOT -- what the glyph OUGHT to be.

    Written from the RULING (unknown grey / degraded amber / connected green) and
    the two state-file fields it speaks about, NOT from carousel.js -- a renderer
    that changed its mind still fails against this.

    Deliberately keyed on the PAYLOAD rather than on the cause name. A cause->
    colour table would be a second, hidden assertion about what the producer
    publishes for each cause, and that is exactly the question I-us663 leaves
    open: whichever way that availability rule is settled, this expectation
    follows it, so these sweeps keep testing the GLYPH instead of quietly
    becoming change-detectors for a producer fix.
    """
    if payload["source"]["obd"]["available"] is not True:
        return NEUTRAL                      # we could not look -- not a claim
    state = payload["obdLink"]["state"]
    if state == "linked":
        return GREEN
    if state in ("reconnecting", "down"):
        return AMBER
    return NEUTRAL                          # read, but ungradeable -- still not a claim


def _handBuilt(**overrides: Any) -> dict:
    """A payload from the shipped builder, for the halves-DISAGREE cases only.

    The producer cannot emit a null link state beside an AVAILABLE source, so the
    only way to ask which of the renderer's two neutral gates is holding is to
    build the disagreeing payload directly. Used in exactly two tests below, both
    of which say so in their docstrings.
    """
    args: dict[str, Any] = {
        "obdLinkState": "linked",
        "obdRetries": 0,
        "obdLastSeenS": 1,
        "syncLastOkTs": _FRESH_SYNC,
        "syncRows": 1204,
        "syncPending": 0,
        "syncStale": False,
        "powerMode": "car",
        "powerSource": "external",
        "driveState": "idle",
        "driveId": None,
        "nowIso": _NOW,
        "obdAvailable": True,
    }
    args.update(overrides)
    return buildSystemStatusState(**args)


# ---------------------------------------------------------------------------
# Reading the rendered panel.
# ---------------------------------------------------------------------------


def _surface(routes: dict[str, Any], steps: list[dict[str, Any]] | None = None):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet."""
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _glyphOn(surface, elementId: str) -> tuple[str, str]:
    path = surface.pathById(elementId)
    assert path is not None, f"no #{elementId} in the rendered DOM"
    assert surface.rendered(path), f"#{elementId} is in the DOM but not displayed"
    state = path[-1].get("attrs", {}).get("data-state")
    declaration = surface.winningDeclaration(path, "color")
    return (state, declaration[0] if declaration else "")


def _btGlyph(payload: Any, steps: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    """The BT glyph as the driver sees it -> (data-state, resolved colour).

    Returns the COLOUR as well as the token because the CIO ruled on colours and
    the shipped vocabulary has one more token than the ruling has states. A token
    only means "amber" while the stylesheet agrees; resolving through
    `winningDeclaration` makes the two travel together.
    """
    routes = {} if payload is None else {"/system-status": payload}
    return _glyphOn(_surface(routes, steps), "glyph-bt")


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS FIRST. Most of this file is absence-shaped ("never green",
# "never amber"), and every such assertion passes vacuously if the harness reads
# nothing at all -- a renamed ID or a probe crash would turn the whole file green
# while pinning nothing.
# ---------------------------------------------------------------------------


@_needsNode
def test_theHarnessActuallyReadsTheBtGlyph_negativeControl(tmp_path):
    """
    Given: every "must not" assertion below fails open if the glyph is unreadable
    When: an unmistakably LINKED car is rendered
    Then: the harness reads a real state AND a real colour.
    """
    state, colour = _btGlyph(_emit(tmp_path, _allCauses()["linked"]))
    assert state == "ok", f"harness read no glyph state: {state!r}"
    assert colour == GREEN, f"harness read no glyph colour: {colour!r}"


@_needsNode
def test_theStylesheetResolvesTheGlyphVocabularyToExactlyThreeColours(tmp_path):
    """
    Given: the CIO ruled THREE states but the shipped vocabulary has FOUR tokens
    When: the shipped stylesheet is resolved for every token in turn
    Then: they collapse to exactly three colours -- and `down` shares AMBER.

          THE RECONCILIATION THIS WHOLE FILE RESTS ON, and nothing said it
          before. `down` is a fourth token but not a fourth STATE: dashboard.css
          paints it with the amber token deliberately (US-488 -- "a DOWN link is
          DEGRADED, not dangerous"). If that ever changes, the panel grows a
          state the ruling does not have, and every colour assertion below would
          otherwise keep passing on tokens alone.

          An UNKNOWN token is swept too, because that is where a future producer
          word would land: it must fall to neutral, never to a colour.
    """
    surface = _surface({"/system-status": _emit(tmp_path, _allCauses()["linked"])})
    path = surface.pathById("glyph-bt")
    assert path is not None

    resolved = {}
    for token in ("ok", "amber", "down", "neutral", "someFutureToken"):
        path[-1]["attrs"]["data-state"] = token
        declaration = surface.winningDeclaration(path, "color")
        resolved[token] = declaration[0] if declaration else ""

    assert resolved["ok"] == GREEN, resolved
    assert resolved["amber"] == AMBER, resolved
    assert resolved["down"] == AMBER, resolved
    assert resolved["neutral"] == NEUTRAL, resolved
    assert resolved["someFutureToken"] == NEUTRAL, resolved
    assert len(set(resolved.values())) == 3, f"not three colours: {resolved}"
    greens = sorted(t for t, c in resolved.items() if c == GREEN)
    assert greens == ["ok"], f"green is reachable from more than `ok`: {resolved}"


# ---------------------------------------------------------------------------
# THE RECORDED PASS -- validationCriteria 1, 2 and 3, each through the REAL
# producer rather than a hand-written payload.
# ---------------------------------------------------------------------------


@_needsNode
def test_aLiveLinkRendersGreen(tmp_path):
    """
    Given: validationCriterion 3 -- render with a live link
    When: the car is connected
    Then: the BT glyph is GREEN.

          NEVER ASSERTED ANYWHERE BEFORE THIS TEST. The four pre-existing
          assertions on this glyph's state cover neutral, amber and down; the one
          state that means "your car is talking to you" had no coverage of any
          kind, so a renderer that had stopped painting green would have left the
          entire suite passing.
    """
    assert _btGlyph(_emit(tmp_path, _allCauses()["linked"])) == ("ok", GREEN)


@_needsNode
def test_aReadButFailingLinkRendersAmber_whileReconnecting(tmp_path):
    """
    Given: validationCriterion 2 -- render with a read-but-failing link
    When: the Pi is mid-reconnect to a car it has spoken to before
    Then: the BT glyph is AMBER.
    """
    payload = _emit(tmp_path, _allCauses()["reconnecting_seen_before"])
    assert payload["obdLink"]["state"] == "reconnecting"
    assert _btGlyph(payload) == ("amber", AMBER)


@_needsNode
def test_aReadButFailingLinkRendersAmber_whenTheLinkIsDown(tmp_path):
    """
    Given: validationCriterion 2 again, by the OTHER failing shape
    When: a link that HAS been established drops
    Then: the glyph token is `down` and the COLOUR is still AMBER.

          Split from the reconnecting case deliberately, and it is the test that
          earns the colour-not-token discipline: these two failures publish
          DIFFERENT tokens and the driver must read the SAME state, because the
          ruling gives "degraded" one colour. A token-only assertion cannot say
          that; this one does, and it is the only place the four-token/three-
          state reconciliation is exercised on real producer output.
    """
    payload = _emit(tmp_path, _allCauses()["dropped_after_connecting"])
    assert payload["obdLink"]["state"] == "down"
    assert _btGlyph(payload) == ("down", AMBER)


@_needsNode
def test_everyUnreadableCauseRendersOneNeutralGrey_whateverItsReason(tmp_path):
    """
    Given: validationCriterion 1 -- render with obdLink.state null
    When: every cause that leaves the OBD source UNAVAILABLE is emitted
    Then: each renders NEUTRAL GREY -- not amber, not green.

          Swept rather than sampled because US-663 gave these causes three
          DIFFERENT reason words one story ago ("not read yet" / "link
          unreadable" / "OBD: off"). MANY REASONS REACHING ONE COLOUR is exactly
          the shape where a renderer that branched on the reason would drift, and
          the reasons are collected here so the failure names the word that
          broke rather than an index.

          Today that is three causes; the set is discovered from the payloads,
          not hardcoded, so a producer that grows a fourth cause is swept too.
    """
    reasonsSeen = set()
    for cause, connection in _allCauses().items():
        payload = _emit(tmp_path / cause, connection)
        if payload["source"]["obd"]["available"] is True:
            continue
        reasonsSeen.add(payload["source"]["obd"]["reason"])
        assert payload["obdLink"]["state"] is None, cause
        state, colour = _btGlyph(payload)
        assert (state, colour) == ("neutral", NEUTRAL), f"{cause}: {state!r} {colour!r}"
        assert colour != AMBER, cause
        assert colour != GREEN, cause

    assert len(reasonsSeen) > 1, (
        f"the sweep saw only {reasonsSeen!r} -- it is no longer proving that "
        "DIFFERENT reasons reach one colour"
    )


# ---------------------------------------------------------------------------
# THE STORY'S ACTUAL CLAIM. "An unread link is indistinguishable from a degraded
# one" is a DISTINGUISHABILITY claim, and US-656 settled how to test one: stop
# asserting the sentinel and assert that the two are told apart.
# ---------------------------------------------------------------------------


@_needsNode
def test_theThreeStatesArePairwiseDistinctOnTheRenderedPanel(tmp_path):
    """
    Given: the story's title -- an unread link cannot be told from a degraded one
    When: all SEVEN causes the shipped producer can reach are rendered in turn
    Then: they partition into exactly THREE colours, and the partition is the
          CIO's: unknown grey, degraded amber, connected green.

          The measured table, all seven read off the 480x320 panel:

            never_looked               null           grey
            status_unreadable          null           grey
            never_connected            null           grey
            dropped_after_connecting   down           amber
            reconnecting_never_linked  reconnecting   amber
            reconnecting_seen_before   reconnecting   amber
            linked                     linked         green

          Asserted as a PARTITION rather than as seven equalities: the failure
          this guards is two states collapsing into one, and a partition says
          that directly. A count of three alone is satisfied the wrong way by a
          renderer painting three ARBITRARY colours, so each payload is also
          checked against `_expectedColour` -- the ruling read off the SSOT.
    """
    byColour: dict[str, list[str]] = {}
    for cause, connection in _allCauses().items():
        payload = _emit(tmp_path / cause, connection)
        _, colour = _btGlyph(payload)
        assert colour == _expectedColour(payload), (
            f"{cause}: panel {colour!r}, ruling says {_expectedColour(payload)!r} "
            f"for available={payload['source']['obd']['available']!r} "
            f"state={payload['obdLink']['state']!r}"
        )
        byColour.setdefault(colour, []).append(cause)

    assert len(byColour) == 3, f"the panel does not show three states: {byColour}"
    assert set(byColour) == {NEUTRAL, AMBER, GREEN}, byColour

    # The story's sentence, stated as the disjointness it actually asserts: no
    # cause is read by the driver as two states, and no two states share a cause.
    assert not set(byColour[NEUTRAL]) & set(byColour[AMBER])
    assert not set(byColour[NEUTRAL]) & set(byColour[GREEN])
    assert not set(byColour[AMBER]) & set(byColour[GREEN])


@_needsNode
def test_aNullLinkStateIsNeverAmberAndNeverGreen_sweptOverEveryCause(tmp_path):
    """
    Given: the NEGATIVE CASE -- null must NEVER render amber and never green
    When: every producer cause is emitted and the state and glyph read together
    Then: `obdLink.state is None` and `glyph is grey` are the SAME set.

          A BICONDITIONAL, not two one-way checks, and US-663 established why on
          this same field: "null is grey" alone is satisfied by a glyph that is
          grey always, and "a real state is coloured" alone is satisfied by one
          that never goes grey. Together they are non-vacuous from both sides --
          which the assertions below prove by requiring each set to be non-empty.
    """
    nullStates: set[str] = set()
    greyGlyphs: set[str] = set()
    for cause, connection in _allCauses().items():
        payload = _emit(tmp_path / cause, connection)
        if payload["obdLink"]["state"] is None:
            nullStates.add(cause)
        _, colour = _btGlyph(payload)
        if colour == NEUTRAL:
            greyGlyphs.add(cause)

    assert nullStates, "no cause produced a null link state -- the sweep is vacuous"
    assert greyGlyphs != set(_allCauses()), "every glyph is grey -- the sweep is vacuous"
    assert nullStates == greyGlyphs, f"null: {nullStates}, grey: {greyGlyphs}"


# ---------------------------------------------------------------------------
# WHICH GATE IS HOLDING? US-636's lesson: when an absence test passes, ask which
# of the nested gates produced it. A null state reaches neutral TWO independent
# ways -- `obdOff ? "neutral"` at carousel.js:912, and `btGlyphState`'s own
# fallback at carousel.js:658 -- and on every payload the producer can emit BOTH
# fire, so a mutation of either survives every test above. The only way to tell
# them apart is a payload whose halves DISAGREE, which the producer cannot write.
# ---------------------------------------------------------------------------


@_needsNode
def test_theGlyphsOwnFallbackIsNeutral_notInheritedFromTheSourceOverride():
    """
    Given: a null link state sitting beside an AVAILABLE source -- halves that
           disagree, and a payload the shipped producer cannot emit
    When: rendered
    Then: the glyph is still NEUTRAL.

          The source override cannot be what produces this: the source says
          available. Only `btGlyphState`'s own trailing `return "neutral"` can,
          so this test -- and only this test -- pins that fallback. It matters
          beyond the hypothetical, because that fallback is what a FUTURE
          producer state token would fall through to, and its default being
          neutral rather than ok is the difference between this glyph and the
          SYNC glyph that US-633 found defaulting to green.
    """
    payload = _handBuilt()
    payload["obdLink"] = {"state": None, "retries": 0, "lastSeenS": None}
    assert payload["source"]["obd"]["available"] is True, "the halves must disagree"
    assert _btGlyph(payload) == ("neutral", NEUTRAL)


@_needsNode
def test_anUnrecognisedLinkStateIsNeutral_neverGreen():
    """
    Given: a link state token the glyph has not been taught (`connected`, the
           spelling the CONNECTION layer uses -- a plausible future drift)
    When: rendered beside an available source
    Then: NEUTRAL. An unknown word is not a claim.

          This is US-633's sync-glyph defect asked of the BT glyph, and the
          answer is the opposite one: `syncGlyphState` is `stale === true ?
          amber : ok`, so ANY input it does not understand is promoted to green.
          `btGlyphState` tests for each state it knows and falls to neutral, so
          an unrecognised word cannot buy a colour. Pinned so the two glyphs
          cannot be "made consistent" in the wrong direction.
    """
    payload = _handBuilt()
    payload["obdLink"] = {"state": "connected", "retries": 0, "lastSeenS": 1}
    state, colour = _btGlyph(payload)
    assert (state, colour) == ("neutral", NEUTRAL)
    assert colour != GREEN


@_needsNode
def test_anUnavailableSourceOverridesAStaleLinkState_andTheColourGoesGrey():
    """
    Given: an UNAVAILABLE source carrying a stale-looking `linked` state
    When: rendered
    Then: NEUTRAL grey -- not the green a `linked` token would otherwise earn.

          The other gate, and the one this file does not own: the token half is
          already pinned at test_carousel_obd_source_unavailable_render.py:575.
          Re-asserted here on the COLOUR, which that test does not read, because
          the CIO's ruling is about colour and "not the ok token" is a weaker
          claim than "not green" while the stylesheet is free to move.
    """
    payload = _handBuilt(obdAvailable=False)
    payload["obdLink"] = {"state": "linked", "retries": 0, "lastSeenS": 4}
    state, colour = _btGlyph(payload)
    assert (state, colour) == ("neutral", NEUTRAL)
    assert colour != GREEN


# ---------------------------------------------------------------------------
# STALE GREEN. A glyph that keeps its last good colour when the feed dies is
# INVISIBLE on the panel by construction -- a lingering green is indistinguish-
# able from a healthy one. carousel.js has a `resetSystemGlyphs` guard for
# exactly this and nothing held it in place for the BT glyph.
# ---------------------------------------------------------------------------


@_needsNode
def test_aVanishedStateFileReturnsTheGlyphToNeutral_noLingeringGreen(tmp_path):
    """
    Given: a linked car rendering GREEN, and then the state file disappears
    When: the dashboard polls again and gets a 404
    Then: the glyph returns to NEUTRAL.

          The single-render tests above cannot reach this: they never have a
          good read to go stale. Green held over a dead feed is the worst of the
          three states to strand, because it is the one that tells the driver to
          stop worrying.
    """
    linked = _emit(tmp_path, _allCauses()["linked"])
    state, colour = _btGlyph(
        linked,
        steps=[{"flush": 4}, {"setRoutes": {"/system-status": None}}, {"flush": 4}],
    )
    assert (state, colour) == ("neutral", NEUTRAL)
    assert colour != GREEN


@_needsNode
def test_theStateFileIsKeptAndTheGlyphStaysGreen_control(tmp_path):
    """
    Given: the two-step harness above
    When: the SAME two steps run without dropping the route
    Then: the glyph is still GREEN.

          Without this control the reset test passes for a renderer that simply
          neutralises the glyph on every second poll, which is a different (and
          also wrong) behaviour.
    """
    linked = _emit(tmp_path, _allCauses()["linked"])
    assert _btGlyph(
        linked,
        steps=[{"flush": 4}, {"setRoutes": {"/system-status": linked}}, {"flush": 4}],
    ) == ("ok", GREEN)


@_needsNode
def test_theGlyphFollowsTheLinkAcrossAllThreeStatesInOneSession(tmp_path):
    """
    Given: three successive state files on ONE boot -- linked, then dropped,
           then the car gone entirely
    When: the glyph is read after each poll
    Then: GREEN, then AMBER, then GREY.

          A transition test, because every assertion above is a fresh boot and a
          renderer that painted correctly only on its FIRST read would pass all
          of them. This is the sequence a driver actually experiences when the
          engine stops.
    """
    linked = _emit(tmp_path / "a", _allCauses()["linked"])
    dropped = _emit(tmp_path / "b", _allCauses()["dropped_after_connecting"])
    gone = _emit(tmp_path / "c", _allCauses()["never_connected"])

    assert _btGlyph(linked, steps=[{"flush": 4}])[1] == GREEN
    assert _btGlyph(
        linked, steps=[{"flush": 4}, {"setRoutes": {"/system-status": dropped}}, {"flush": 4}]
    )[1] == AMBER
    assert _btGlyph(
        linked,
        steps=[
            {"flush": 4},
            {"setRoutes": {"/system-status": dropped}},
            {"flush": 4},
            {"setRoutes": {"/system-status": gone}},
            {"flush": 4},
        ],
    )[1] == NEUTRAL


# ---------------------------------------------------------------------------
# validationCriterion 4 -- exactly one acquisition of link state.
# ---------------------------------------------------------------------------


@_needsNode
def test_theGlyphNeedsNoRouteBeyondSystemStatus(tmp_path):
    """
    Given: validationCriterion 4, asked of the RUNNING dashboard
    When: `/system-status` is the ONLY route served and every other 404s
    Then: the glyph still reaches all three states.

          The behavioural half of the claim, and the half a source grep cannot
          make: a second acquisition path would have to fetch something, and
          nothing else is on offer here. Every other test in this file is served
          the same single route, so this states the property they all rely on.
    """
    causes = _allCauses()
    assert _btGlyph(_emit(tmp_path / "g", causes["linked"]))[1] == GREEN
    assert _btGlyph(_emit(tmp_path / "a", causes["reconnecting_seen_before"]))[1] == AMBER
    assert _btGlyph(_emit(tmp_path / "n", causes["never_looked"]))[1] == NEUTRAL


def test_theDashboardReadsTheLinkStateExactlyOnce():
    """
    Given: ssot-design-pattern rule B -- one acquisition, however many consumers
    When: carousel.js is swept for reads of `data.obdLink`
    Then: there are exactly two, both inside `systemStatusView`, both off the
          same payload -- and `btGlyphState` is invoked exactly once.

          Two CONSUMERS (the tile and the glyph) off ONE acquisition is the
          shape the rule asks for; two ACQUISITIONS would be the violation. The
          source half of the claim, scoped so that DELETING a consumer fails it
          too -- an assertion that only catches additions would be satisfied by
          a dashboard that had stopped drawing the glyph.
    """
    source = open(_CAROUSEL_JS, encoding="utf-8").read()
    reads = re.findall(r"\bdata\.obdLink\b", source)
    assert len(reads) == 2, f"expected 2 reads of data.obdLink, found {len(reads)}"
    calls = re.findall(r"\bbtGlyphState\s*\(", source)
    # One definition + one invocation. A second invocation would be a second
    # place the glyph's colour is decided, which is the drift this pins.
    assert len(calls) == 2, f"btGlyphState is not called exactly once: {len(calls)}"
    view = source[source.index("function systemStatusView("):]
    view = view[: view.index("\n  function ", 1)]
    assert view.count("data.obdLink") == 2, "a read of data.obdLink escaped the view"


# ---------------------------------------------------------------------------
# CHARACTERISATION -- RECORDED, NOT FIXED. This is I-us663, read on the axis
# US-658's acceptance criteria state it: "AMBER IS A CLAIM ABOUT A MEASUREMENT,
# and you cannot make a claim about a value you have not read."
#
# I-us663's own two characterisation tests (in
# tests/ui/test_carousel_obd_link_typed_unknown.py) pin the FLAP -- one condition
# publishing two availabilities on successive samples. These pin something the
# flap tests do not: that a SINGLE sample, on its own, paints amber over a link
# this Pi has never once read. Both fail on purpose when I-us663 is fixed;
# re-record them, do not relax them.
# ---------------------------------------------------------------------------


@_needsNode
def test_characterisation_amberIsPaintedOverALinkThatHasNeverBeenRead(tmp_path):
    """
    Given: ARCH-007 -- amber is a claim about a MEASUREMENT
    When: the Pi is mid-reconnect to a car it has NEVER connected to
          (`totalConnections == 0`)
    Then: TODAY the glyph is AMBER, and it is indistinguishable from the genuinely
          degraded link two lines below.

          THE STORY'S TITLE, TRUE, BY A MECHANISM THE STORY DID NOT NAME. The
          glyph is not at fault -- it renders `reconnecting` amber because the
          PRODUCER published `available: true`, and `_gatherObdLinkState` does
          that unconditionally on the reconnect branch while gating the `down`
          branch on `totalConnections > 0`. So the ONE thing that separates these
          two payloads -- has this Pi ever spoken to this car -- is the thing the
          availability rule drops. Filed as I-us663 (with the fix options and the
          routing question); NOT fixed here, because conditionalOutcome 1 of this
          story says a distinction the SSOT does not carry is a producer story.
    """
    causes = _allCauses()
    neverRead = _emit(tmp_path / "never", causes["reconnecting_never_linked"])
    genuinelyDegraded = _emit(tmp_path / "seen", causes["reconnecting_seen_before"])

    assert neverRead["source"]["obd"]["available"] is True
    assert _btGlyph(neverRead)[1] == AMBER
    assert _btGlyph(genuinelyDegraded)[1] == AMBER
    assert _btGlyph(neverRead) == _btGlyph(genuinelyDegraded)


@_needsNode
def test_characterisation_bothGlyphsObeyTheSourceRule_soTheDivergenceIsUpstream():
    """
    Given: the WiFi glyph is the ARCH-007 reference implementation
    When: BT and WiFi are handed the same shape -- a live-looking state under an
          UNAVAILABLE source -- on one payload
    Then: BOTH render neutral.

          The exoneration, and the reason this story records rather than fixes.
          If the two glyphs disagreed, the BT glyph would be the defect and this
          story's surface would be the place to fix it. They do not: they apply
          the identical rule. The divergence the driver sees is entirely in what
          the two PRODUCERS publish as `available` -- the WiFi producer defaults
          to unavailable and refuses to derive a state without one
          (system_status_emitter.py:218-223), while the OBD producer asserts
          availability on a link it has never read. Same rule, different inputs,
          so the fix belongs upstream (I-us663).
    """
    payload = _handBuilt(obdAvailable=False, wifiAvailable=False)
    payload["obdLink"] = {"state": "linked", "retries": 0, "lastSeenS": 4}
    payload["wifi"] = {"state": "up", "ssid": "garage", "rssiDbm": -42}

    surface = _surface({"/system-status": payload})
    assert _glyphOn(surface, "glyph-bt") == ("neutral", NEUTRAL)
    assert _glyphOn(surface, "glyph-wifi") == ("neutral", NEUTRAL)
