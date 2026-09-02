################################################################################
# File Name: test_carousel_gear_derived.py
# Purpose/Description: US-630 END STATE -- "the tile shows the derived gear".
#   Pinned where the driver reads it: the SHIPPED config.json bands -> the REAL
#   deriver -> the REAL states/gear emitter -> a real file -> the SHIPPED
#   carousel.js over the SHIPPED markup and stylesheet at 480x320.
#
#   WHY IT HAS TO BE THE WHOLE CHAIN. Both halves of this feature were already
#   green in isolation and had been for weeks: `gearView()` has rendered a gear
#   correctly since US-508, and the derivation has been correct since last
#   iteration. What did not exist was the JOIN -- carousel.js polled no `gear`
#   state at all (`lastGear` was a var initialised to null and never assigned),
#   so a perfect producer and a perfect renderer would still have left the tile
#   reading "-- / no source" forever. That is the US-494/495/498 shape exactly,
#   and only an end-to-end pin can see it.
#
#   THE GEAR GLYPH LIVES ON THE LIVE FACE of the home slot, which renders only
#   while the motion feed is alive (US-541). Every test here therefore supplies
#   a live states/imu, and a negative control asserts that face really painted
#   -- an absence measured on a face that failed to render is not a measurement
#   (the US-638 lesson, which cost that story a wrong first draft).
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
# 2026-08-31    | Rex (US-630) | Initial -- the derived gear, as the panel shows it.
# ================================================================================
################################################################################

"""US-630: the derived gear, from the measured bands to the rendered glyph."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "src",
    ),
)

import render_harness as rh  # noqa: E402

from common.config.validator import ConfigValidator  # noqa: E402
from pi.obdii import gear_derivation as gd  # noqa: E402
from pi.obdii.gear_state_emitter import (  # noqa: E402
    GEAR_STATE_FILENAME,
    makeGearStateEmitter,
)

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default.
PANEL = (480, 320)

# Spelled as a named constant: this file is written and re-read over a Windows
# SMB share where raw non-ASCII has been mangled before.
EN_DASH_PAIR = "--"

_REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
CONFIG_PATH = os.path.join(_REPO, "config.json")

# Steady cruises at Atlas's MEASURED medians, so the number the panel prints is
# traceable to a measurement rather than to a value picked to make a test pass.
_CRUISE = {
    3: (80.0, 44.3 * 80.0),   # 3rd, measured median 44.3 rpm/kph
    5: (100.0, 27.0 * 100.0),  # 5th, measured median 27.0 rpm/kph
}
_POLL_PERIOD_S = 0.25


def _shippedDeriver() -> gd.GearDeriver:
    """The deriver the Pi actually builds, from the shipped config.json."""
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        config = ConfigValidator().validate(json.load(fh))
    deriver = gd.createGearDeriverFromConfig(config)
    assert deriver is not None, "config.json no longer enables the derivation"
    return deriver


def _emitCruise(tmp_path, gear: int) -> dict:
    """Drive a steady cruise through the REAL producer; return what it wrote."""
    return _emitCruiseAt(tmp_path, *_CRUISE[gear])


def _emitCruiseAt(tmp_path, speedKph: float, rpm: float) -> dict:
    """Hold one steady operating point past the debounce, through the producer."""
    statesDir = str(tmp_path / "states")
    emit = makeGearStateEmitter(statesDir)
    deriver = _shippedDeriver()

    nowS = 1000.0
    elapsed = 0.0
    while elapsed <= gd.DEFAULT_DEBOUNCE_S + 0.5:
        emit(
            deriver.update(
                speed=gd.Reading(speedKph, nowS),
                rpm=gd.Reading(rpm, nowS),
                nowS=nowS,
            )
        )
        nowS += _POLL_PERIOD_S
        elapsed += _POLL_PERIOD_S

    with open(os.path.join(statesDir, GEAR_STATE_FILENAME), encoding="utf-8") as fh:
        return json.load(fh)


def _emitAbsence(tmp_path, speedKph: float, rpm: float) -> dict:
    """One derivation of a non-resolving operating point, through the producer."""
    statesDir = str(tmp_path / "states")
    emit = makeGearStateEmitter(statesDir)
    emit(
        _shippedDeriver().update(
            speed=gd.Reading(speedKph, 1000.0),
            rpm=gd.Reading(rpm, 1000.0),
            nowS=1000.0,
        )
    )
    with open(os.path.join(statesDir, GEAR_STATE_FILENAME), encoding="utf-8") as fh:
        return json.load(fh)


def _liveImu() -> dict:
    """A states/imu payload the shipped imuView accepts as LIVE.

    Stamped from the wall clock, not a fixed instant: imuView ages the reading
    against Date.now() inside node, so a frozen stamp would go stale on its own
    and drop the home slot back to the idle face -- which has no gear glyph at
    all, and every assertion here would then pass for the wrong reason.
    """
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "ts": now,
        "available": True,
        "gLat": 0.01,
        "gLon": 0.02,
        "gMag": 0.03,
        "pitchDeg": 0.5,
        "rollDeg": 0.2,
        "headingDeg": 180.0,
    }


def _surface(gearPayload: Any, steps: list[dict[str, Any]] | None = None):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet."""
    routes: dict[str, Any] = {"/imu": _liveImu()}
    if gearPayload is not None:
        routes["/gear"] = gearPayload
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _textOf(node: dict) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return out


def _firstRendered(surface, className: str) -> str | None:
    """The printed text of the first PAINTED element with ``className``.

    Painted, not merely present: a glyph inside a display:none ancestor is not
    on the panel, and the whole point of resolving the real cascade is that a
    test cannot be satisfied by an element the driver cannot see.
    """
    for path in surface.pathsByClass(className):
        if not surface.rendered(path):
            continue
        return " ".join(_textOf(path[-1])).strip()
    return None


def _gearGlyph(surface) -> str | None:
    return _firstRendered(surface, "imu-gear")


def _gearDetail(surface) -> str | None:
    return _firstRendered(surface, "imu-gear-detail")


# ---------------------------------------------------------------------------
# Negative control. Every claim below is about what the GEAR glyph reads, and
# all of them would "pass" on a live face that never painted.
# ---------------------------------------------------------------------------


def test_theLiveFaceRenders_negativeControlForEveryClaimBelow(tmp_path):
    """
    Given: a live motion feed and a resolved gear
    When:  the panel renders
    Then:  the live face is genuinely painted, glyph element and all
    """
    surface = _surface(_emitCruise(tmp_path, 3))

    assert _firstRendered(surface, "imu-gear-label") == "GEAR", (
        "the live face did not paint -- every assertion in this file would be "
        "an artefact of the harness rather than a fact about the panel"
    )


# ---------------------------------------------------------------------------
# THE END STATE. A measured band, through the real producer, onto the panel.
# ---------------------------------------------------------------------------


class TestTheDerivedGearReachesThePanel:
    """"the tile shows the derived gear when SPEED and RPM are both live"."""

    def test_steadyThirdGearCruise_paintsA3(self, tmp_path):
        """
        Given: a cruise at Atlas's measured 3rd-gear median, 44.3 rpm/kph
        When:  the producer's states/gear is served to the shipped carousel
        Then:  the GEAR glyph on the panel reads 3
        """
        surface = _surface(_emitCruise(tmp_path, 3))

        assert _gearGlyph(surface) == "3"

    def test_resolvedGear_paintsEngagedAsItsDetail(self, tmp_path):
        """
        Given: a resolved gear
        When:  the panel renders
        Then:  the detail line reads `engaged`, not a stale absence reason
        """
        surface = _surface(_emitCruise(tmp_path, 3))

        assert _gearDetail(surface) == "engaged"

    def test_thirdAndFifth_doNotCollapseIntoOneAnother(self, tmp_path):
        """
        Given: two different measured cruises
        When:  each is rendered
        Then:  the panel prints two different digits

        Held as a direct comparison because both tests above would pass against
        a glyph hardcoded to whichever digit was checked first -- which is
        precisely how a producer that never ran could look correct.
        """
        third = _surface(_emitCruise(tmp_path / "a", 3))
        fifth = _surface(_emitCruise(tmp_path / "b", 5))

        assert _gearGlyph(third) == "3"
        assert _gearGlyph(fifth) == "5"

    def test_theProducerIsWhatDecidesTheDigit_notTheRenderer(self, tmp_path):
        """
        Given: the payload the producer actually wrote for a 3rd-gear cruise
        When:  it is inspected before it ever reaches the renderer
        Then:  it already says 3

        Splits the chain deliberately: if this passes and the render test above
        fails, the defect is in the transport; if both fail, it is in the
        derivation. Without it a red end-to-end test names no component.
        """
        assert _emitCruise(tmp_path, 3) == {
            "available": True,
            "gear": 3,
            "reason": gd.REASON_ENGAGED,
            "ts": _emitCruise(tmp_path, 3)["ts"],
        }


# ---------------------------------------------------------------------------
# THE NEGATIVE CASE, on the panel. "never a guessed gear, never a held one."
# ---------------------------------------------------------------------------


class TestTheGlyphRefusesToGuess:
    """Typed absences render as an absence, with their reason."""

    def test_noGearStateFileAtAll_readsNoSource(self, tmp_path):
        """
        Given: no states/gear -- an uncalibrated or dark Pi
        When:  the panel renders
        Then:  the glyph is a dash and the detail names no source

        The state the tile has been in since US-508, and the one it must return
        to rather than inventing anything.
        """
        surface = _surface(None)

        assert _gearGlyph(surface) == EN_DASH_PAIR
        assert _gearDetail(surface) == "no source"

    def test_ratioMatchingNoBand_readsTheDashAndItsOwnReason(self, tmp_path):
        """
        Given: a ratio outside the published table entirely (1000 rpm/kph)
        When:  the panel renders
        Then:  the glyph is a dash and the detail is the producer's own reason

        Distinguishable from "no source" on the panel, which is the whole
        purpose of carrying a reason: a producer honestly refusing to guess is
        a different operator fact from a producer that does not exist.

        THE OPERATING POINT IS ARTIFICIAL AND THAT IS THE FINDING, not a flaw
        in the test. Atlas's table is contiguous from 0.0 to 999.0, so the only
        ratios it does not claim are ones no engine and gearbox can produce
        together. See the characterisation below.
        """
        payload = _emitAbsence(tmp_path, 5.0, 5000.0)
        assert payload["reason"] == gd.REASON_NO_BAND

        surface = _surface(payload)

        assert _gearGlyph(surface) == EN_DASH_PAIR
        assert _gearDetail(surface) == gd.REASON_NO_BAND
        assert _gearDetail(surface) != "no source"

    def test_theStateFileVanishesMidSession_theGlyphDropsTheGear(self, tmp_path):
        """
        Given: a settled 3rd gear on the panel
        When:  states/gear disappears -- the producer dies, or /run is cleared
        Then:  the glyph returns to a dash rather than holding the 3

        The story's "never a held previous one", asserted on the RENDERED
        surface. The producer-side version of this is pinned in
        tests/pi/obdii/test_gear_state_emitter.py; this is the half that would
        still fail if the renderer cached the last good gear.
        """
        vanish = [{"flush": 4}, {"setRoutes": {"/gear": None}}, {"flush": 4}]
        surface = _surface(_emitCruise(tmp_path, 3), steps=vanish)

        assert _gearGlyph(surface) == EN_DASH_PAIR

    def test_theVanishTestHasAControl_theGearSurvivesWhenTheFileDoesNot(
        self, tmp_path
    ):
        """
        Given: the same two-step render with states/gear left in place
        When:  the panel renders
        Then:  the glyph still reads 3

        Without this, a harness whose second step reset every route would pass
        the vanish test while proving nothing about the renderer.
        """
        kept = [{"flush": 4}, {"flush": 4}]
        surface = _surface(_emitCruise(tmp_path, 3), steps=kept)

        assert _gearGlyph(surface) == "3"


# ---------------------------------------------------------------------------
# CHARACTERISATION, recorded and NOT fixed. Filed as
# offices/pm/issues/I-us630-fifth-gear-band-opens-at-zero-so-a-coast-reads-5th.md
#
# The story's acceptance says "Clutch-in and coasting legitimately match no
# band". With Atlas's published table they do not: 5th opens at 0.0 rpm/kph, so
# every low-ratio state -- clutch in, neutral, engine braking to idle -- lands
# inside 5th and the panel names it with conviction.
#
# NOT FIXED HERE, deliberately. The story says in as many words to PREFER THE
# EMPIRICAL BANDS and not to conclude the table is wrong from a cross-check that
# fails to reconcile; narrowing 5th's floor myself would be exactly the invented
# number BL-us630 was filed to avoid. The CIO's standing acceptance ("slightly
# incorrect but functioning is fine here; refine later") applies. These tests
# hold the behaviour as it ships so whoever narrows the band fails them ON
# PURPOSE and knows the panel changed.
# ---------------------------------------------------------------------------


class TestCoastingReadsFifthGear_characterisation:
    """A known consequence of a 5th band that opens at zero. Recorded, not fixed."""

    def test_clutchInCoastAtSpeed_currentlyReadsAConfident5(self, tmp_path):
        """
        Given: 120 km/h with the engine at 1000 rpm -- clutch in or in neutral
        When:  the panel renders
        Then:  it reads 5, today

        A ratio of 8.3 rpm/kph is physically impossible in 5th gear (the
        measured 5th spread is 25.3 to 27.4), but 5th's band starts at 0.0 so
        the derivation cannot tell the two apart.
        """
        surface = _surface(_emitCruiseAt(tmp_path, 120.0, 1000.0))

        assert _gearGlyph(surface) == "5"

    def test_theFloorsStillCatchTheStationaryCase(self, tmp_path):
        """
        Given: the car stopped at a light, engine idling
        When:  the panel renders
        Then:  the glyph is a dash -- the speed/rpm floors hold

        The bound on how far the finding above reaches: it is a COASTING
        defect, not a parked one. Without the 5 km/h floor a stationary car
        would sit in a permanent phantom 5th, which would be far worse.
        """
        surface = _surface(_emitAbsence(tmp_path, 0.0, 800.0))

        assert _gearGlyph(surface) == EN_DASH_PAIR


# ---------------------------------------------------------------------------
# Rule B on the consumer side: the dashboard must not acquire gear twice.
# ---------------------------------------------------------------------------


def test_theDashboardReadsTheGearStateExactlyOnce():
    """
    Given: the story's SSOT constraint -- derived once, published, never
           recomputed per consumer
    When:  the shipped carousel.js is searched for gear acquisition
    Then:  it fetches the `gear` state in exactly one place

    Scoped to the FETCH, not to the word `gear`: the renderer legitimately
    mentions gear many times, and a pin that counted those would break on any
    comment edit while missing a genuine second poll.
    """
    js = open(
        os.path.join(rh.DASHBOARD_DIR, "carousel.js"), encoding="utf-8"
    ).read()

    fetches = [
        line.strip()
        for line in js.splitlines()
        if '"gear"' in line and ("stateOnce(" in line or "fetchState(" in line)
    ]

    assert len(fetches) == 1, fetches
