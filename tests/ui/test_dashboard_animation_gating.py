################################################################################
# File Name: test_dashboard_animation_gating.py
# Purpose/Description: US-537 (F-124, Atlas RCA #3) guard tests for MOTION and
#   COMPOSITOR pressure on the Pi dashboard surface (src/pi/ui/dashboard/).
#
#   WHAT THE STORY IS ACTUALLY FIXING. Two things sit permanently in the
#   stylesheet and cost the Pi's GPU command buffer:
#     1. `#track { will-change: transform }` -- an UNCONDITIONAL promotion of the
#        full-width carousel track (every card, side by side) to its own
#        compositor layer, held for the entire session whether or not a swipe is
#        in flight. This is the one declaration in the sheet that is always-on by
#        construction, and it is what auto-rotate's every-N-seconds transform
#        transition lands on top of.
#     2. `animation: ribbon-pulse ... infinite` declared on the BASE `#dtc-ribbon`
#        rule, and `stop-alarm-pulse` left matching an ACKNOWLEDGED takeover
#        because `hideTakeover()` never cleared `data-severity`.
#
#   HONEST PREMISE CORRECTION (stated, not buried -- see the story notes): neither
#   pulse actually RAN at idle before this story. Both surfaces ship `hidden`, the
#   US-495 guard resolves `[hidden]` to `display: none !important`, and a
#   `display: none` element runs no animations. So the pre-US-537 motion was
#   gated -- but gated ONLY as a side effect of PAINTING, by the exact `!important`
#   display rule US-495 had to add after an author `display` declaration silently
#   outranked the UA `[hidden]` sheet. Re-lose that race and a phantom alert band
#   pulses across every card. This story moves both gates onto the STATE attribute
#   the JS already owns in lockstep (`data-level` / `data-severity`), so motion is
#   tied to the alert being real rather than to the display cascade holding.
#
#   These tests resolve the SHIPPED stylesheet over the post-JS DOM the SHIPPED
#   carousel.js actually leaves behind (US-499 render harness), so they pin the
#   gate as a MECHANISM. The static sweep at the bottom is the weaker, explicitly
#   labelled companion that stops a future always-on animation being added.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-07    | Ralph (Rex)  | Initial -- US-537 animation gating + will-change.
# ================================================================================
################################################################################

"""US-537 tests: dashboard motion runs only while its alert is real."""

import os
import re
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the gate is resolved over the DOM the shipped JS leaves",
)

_CSS_PATH = os.path.join(rh.DASHBOARD_DIR, "dashboard.css")

_RIBBON_ID = "dtc-ribbon"
_TAKEOVER_ID = "dtc-takeover"
_TRACK_ID = "track"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# --- lifecycle fixtures ------------------------------------------------------
# The three DTC states the operator actually passes through. Deliberately driven
# through the REAL poll + the REAL click handlers, so "acknowledged" is whatever
# the shipped JS leaves on the DOM, not a hand-built attribute set.


def _sysState() -> dict:
    return {
        "obdLink": {"state": "down", "retries": 0, "lastSeenS": 2},
        "sync": {"lastOkTs": "2026-08-07T09:41:50Z", "rows": 50, "pending": 0, "stale": False},
        "power": {"mode": "car", "source": "external"},
        "drive": {"state": "idle", "driveId": None},
        "source": {"obd": {"available": False}},
        "idle": True,
        "ts": "2026-08-07T09:42:00Z",
    }


def _routes(dtc: dict) -> dict:
    return {
        "/system-status": _sysState(),
        "/battery-health": {"soc": 88, "vcell": 4.02, "crate": -1.2, "ts": "2026-08-07T09:42:00Z"},
        "/light": {"lux": 120.0, "ts": "2026-08-07T09:42:00Z"},
        "/dtc": dtc,
        "/ltft-trend": None,
    }


def _noCodes() -> dict:
    return _routes({"codes": [], "newSinceTs": None, "ts": "2026-08-07T09:42:00Z"})


def _newStopCode() -> dict:
    return _routes(
        {
            "codes": [
                {
                    "code": "P0301",
                    "severity": "stop",
                    "short": "Cylinder 1 misfire detected",
                    "logged": True,
                    "syncAcked": True,
                }
            ],
            "newSinceTs": "2026-08-07T09:41:00Z",
            "ts": "2026-08-07T09:42:00Z",
        }
    )


def _surfaceFor(routes: dict, steps: list[dict] | None = None) -> rh.Surface:
    dom = rh.runDashboard(routes=routes, steps=steps or [{"flush": 4}])
    return rh.dashboardSurface(dom["tree"])


def _animationOf(surface: rh.Surface, elementId: str) -> tuple[str, str] | None:
    """The winning `animation` declaration for one element, or None."""
    path = surface.pathById(elementId)
    assert path is not None, f"#{elementId} is missing from the shipped markup"
    return surface.winningDeclaration(path, "animation")


def _isPainted(surface: rh.Surface, elementId: str) -> bool:
    path = surface.pathById(elementId)
    assert path is not None, f"#{elementId} is missing from the shipped markup"
    return surface.rendered(path)


# --- AC-1: the ribbon pulses only while it carries a live level --------------


@_NODE_ONLY
def test_idleDashboard_ribbonDeclaresNoPulse():
    """
    Given: a bench Pi with no stored codes, booted by the shipped carousel.js
    When: the shipped stylesheet is resolved over the resulting DOM
    Then: NO `animation` wins on #dtc-ribbon at all

    Pre-US-537 the pulse is declared on the base `#dtc-ribbon` rule, so it wins
    here and is silenced only by `[hidden] { display: none !important }` -- the
    same author-vs-UA cascade race that produced US-495. This asserts the gate is
    the state, not the paint.
    """
    surface = _surfaceFor(_noCodes())
    animation = _animationOf(surface, _RIBBON_ID)
    assert animation is None, (
        "#dtc-ribbon still resolves an animation with no code present -- "
        f"`{animation[1]} {{ animation: {animation[0]} }}`. Motion is gated only by "
        "the display cascade, so any author `display` rule re-arms a phantom pulse."
    )


@_NODE_ONLY
@pytest.mark.parametrize("severity", ["stop", "watch", "minor", "unknown"])
def test_liveCode_ribbonStillPulses_atEverySeverity(severity):
    """
    Given: a live code at EACH alertable severity
    Then: the ribbon resolves its pulse for every one of them

    Two cheap ways to pass the gating test exist, and this closes both. The first
    is deleting the animation outright, dropping the F-6/US-405 "a persistent
    alert never fades into chrome" motion channel. The second is subtler and is
    why this is parametrized rather than a single `stop` case: gating on
    `[data-level="stop"]` instead of `[data-level]` also silences the idle
    phantom, but it silently strands WATCH/MINOR/UNKNOWN ribbons static. The base
    rule pulsed for all four levels; tightening the gate must not quietly narrow
    that to one. `ribbonView` sets `level: hero.severity` verbatim, so these four
    are the whole domain.
    """
    surface = _surfaceFor(
        _routes(
            {
                "codes": [{"code": "P0301", "severity": severity, "short": "Test code"}],
                "newSinceTs": None,
                "ts": "2026-08-07T09:42:00Z",
            }
        )
    )
    assert _isPainted(surface, _RIBBON_ID), f"a {severity} code should raise the ribbon at all"
    animation = _animationOf(surface, _RIBBON_ID)
    assert animation is not None, (
        f"a live {severity.upper()} ribbon renders STATIC -- the gate is tighter than "
        "the alert, so three of the four levels lost their motion channel"
    )
    assert "ribbon-pulse" in animation[0]


# --- AC-1: the STOP alarm pulses only while a STOP is genuinely mounted ------


@_NODE_ONLY
def test_liveStop_takeoverPulses():
    """
    Given: a NEW stop-severity code -- the takeover's firing condition
    Then: the STOP alarm animation resolves on #dtc-takeover

    Spool's 6d multi-channel STOP treatment carries MOTION as one of five
    reinforcing channels. Losing it is a safety regression, so it is pinned
    before anything is allowed to gate it.
    """
    surface = _surfaceFor(_newStopCode())
    animation = _animationOf(surface, _TAKEOVER_ID)
    assert animation is not None, "a live STOP takeover lost its alarm pulse"
    assert "stop-alarm-pulse" in animation[0]


@_NODE_ONLY
def test_acknowledgedStop_takeoverStopsDeclaringItsAlarm():
    """
    Given: a STOP takeover that the operator has acknowledged
    When: the shipped stylesheet is resolved over the post-click DOM
    Then: NO `animation` wins on #dtc-takeover

    Pre-US-537 `hideTakeover()` sets `hidden` but leaves `data-severity="stop"`
    behind, so the alarm rule keeps matching an acknowledged takeover forever --
    inert only because the element has no box. The attribute and the alarm must
    be cleared in lockstep, exactly as `renderRibbon` already clears `data-level`.
    """
    surface = _surfaceFor(
        _newStopCode(),
        steps=[{"flush": 3}, {"click": "takeover-dismiss"}, {"flush": 1}],
    )
    animation = _animationOf(surface, _TAKEOVER_ID)
    assert animation is None, (
        "an ACKNOWLEDGED STOP takeover still resolves "
        f"`{animation[1]} {{ animation: {animation[0]} }}` -- the alarm outlives the alarm state"
    )


# --- the load-bearing one: motion and paint agree at every lifecycle step ----


@_NODE_ONLY
@pytest.mark.parametrize(
    "label,routes,steps",
    [
        ("no code", _noCodes(), None),
        ("new stop code", _newStopCode(), [{"flush": 4}]),
        (
            "acknowledged stop",
            _newStopCode(),
            [{"flush": 3}, {"click": "takeover-dismiss"}, {"flush": 1}],
        ),
    ],
)
@pytest.mark.parametrize("elementId", [_RIBBON_ID, _TAKEOVER_ID])
def test_motionIsDeclaredExactlyWhenTheSurfaceIsPainted(label, routes, steps, elementId):
    """
    Given: each state the DTC surfaces actually pass through
    Then: an `animation` is declared IF AND ONLY IF the surface is on screen

    Carousel spec 4 -- motion never implies a state that isn't real -- expressed
    as an agreement rather than as two independent facts (the US-530 lesson).
    Checking "the animation is gated" and "the surface is hidden" separately lets
    the two drift apart; this cannot pass unless they move together. It also
    covers the direction the story is NOT about: gating so hard that a real alert
    goes static.

    Note the acknowledged-stop row deliberately expects the RIBBON to keep
    pulsing -- acknowledging drops the takeover TO the ribbon, so the alert is
    still real and its motion still honest.
    """
    surface = _surfaceFor(routes, steps)
    animated = _animationOf(surface, elementId) is not None
    painted = _isPainted(surface, elementId)
    assert animated == painted, (
        f"[{label}] #{elementId}: animation declared={animated} but painted={painted} -- "
        "motion and paint disagree, so either a phantom pulse is armed or a live "
        "alert renders static"
    )


# --- AC-1: drop the permanent compositor layer on the carousel track ---------


@_NODE_ONLY
def test_carouselTrack_holdsNoPermanentCompositorLayer():
    """
    Given: the shipped carousel markup + stylesheet
    Then: no `will-change` wins on #track

    `will-change: transform` promotes the FULL-WIDTH track -- every card side by
    side -- to its own compositor layer and holds that backing store for the
    whole session, idle or not. It is the only unconditionally-always-on GPU cost
    in this sheet, and it is what auto-rotate's transform transition lands on.
    Atlas RCA #3: drop the hint and let the browser promote for the 0.25s the
    transition actually runs.
    """
    surface = _surfaceFor(_noCodes())
    path = surface.pathById(_TRACK_ID)
    assert path is not None, "#track is missing from the shipped markup"
    winner = surface.winningDeclaration(path, "will-change")
    assert winner is None, (
        f"#track still declares `will-change: {winner[0]}` via `{winner[1]}` -- "
        "a permanently-promoted full-width layer, held even while nothing moves"
    )


@_NODE_ONLY
def test_carouselTrack_keepsItsTransformTransition():
    """
    Given: the track with its compositor hint dropped
    Then: it STILL animates card-to-card via a transform transition

    The cheap way to pass the test above is to delete the whole `#track` rule or
    the transition with it, which would turn every swipe into a hard cut. The
    story removes a HINT, never the motion.
    """
    surface = _surfaceFor(_noCodes())
    path = surface.pathById(_TRACK_ID)
    assert path is not None
    winner = surface.winningDeclaration(path, "transition")
    assert winner is not None, "#track lost its transition -- swipes became hard cuts"
    assert "transform" in winner[0]


# --- the static companion: no NEW always-on animation can be added ----------


def test_everyAnimationDeclaration_isStateQualified():
    """
    Given: every `animation` declaration in the shipped stylesheet
    Then: each one's selector carries a state qualifier (an attribute or class),
          never a bare element/id rule

    HONEST BOUND, stated because an unstated one is how a lenient test passes: is
    this a source-text sweep, not a render. It cannot prove the qualifier is the
    RIGHT one -- the harness tests above do that for the two surfaces that exist
    today. What it does do is fail the day someone adds a third infinite
    animation to a base rule, which is the regression this story is preventing
    and which no per-surface test can see.
    """
    css = re.sub(r"/\*.*?\*/", "", _read(_CSS_PATH), flags=re.DOTALL)
    offenders = []
    for prelude, block in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        prelude = prelude.strip()
        if prelude.startswith("@") or not re.search(r"(?:^|[;{])\s*animation\s*:", block):
            continue
        for selector in (s.strip() for s in prelude.split(",")):
            if not re.search(r"\[[^\]]*\]|\.[\w-]+", selector):
                offenders.append(selector)
    assert not offenders, (
        "these rules run an animation with no state qualifier, so the motion is "
        f"always-on whenever the element paints: {offenders}"
    )
