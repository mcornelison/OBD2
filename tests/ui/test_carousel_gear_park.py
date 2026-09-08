################################################################################
# File Name: test_carousel_gear_park.py
# Purpose/Description: US-687-b (F-138) -- "P" from the switched-off car all the
#   way to the painted glyph, through the SHIPPED config, the REAL deriver, the
#   REAL emitter, a real state file and the SHIPPED carousel.js.
#
#   WHY BOTH HALVES SHIP IN ONE STORY, and it is the asymmetry that split
#   US-687 in two. `gearView` has handled `"N"` since US-508 -- so US-687-a was
#   producer-only and this file's sibling merely CONFIRMED the render path. `"P"`
#   is handled NOWHERE: before this story a producer emitting it fell through
#   gearView's final branch and painted `--`. A producer emitting a state the
#   renderer discards is the renderer-with-no-producer defect wearing the other
#   shoe, and this project has now catalogued five of the first kind.
#
#   THE NEGATIVE CONTROL AT THE TOP IS LOAD-BEARING (US-638): every claim here is
#   about what the GEAR glyph reads, and all of them "pass" on a live face that
#   never painted. An absence test whose SUBJECT failed to render is not a
#   measurement.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-07    | Rex (US-687-b) | Initial -- P on the shipped panel, the dwell
#               |                | and link conditions end to end, and a
#               |                | machine-vocabulary sweep that discovers the
#               |                | producer's reasons instead of copying them.
# ================================================================================
################################################################################

"""US-687-b: park, from the switched-off car to the rendered glyph."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
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
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

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

# MEASURED (Atlas, drives 64-68, 2,141 RPM samples): the worst in-drive gap.
_WORST_MEASURED_RPM_GAP_S = 13.0

_MEASURED_IDLE_RPM = 800.0
_MOVING_SPEED_KPH = 45.0
_MOVING_RPM = 2500.0

_POLL_PERIOD_S = 0.25


def _shippedDeriver() -> gd.GearDeriver:
    """The deriver the Pi actually builds, from the shipped config.json."""
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        config = ConfigValidator().validate(json.load(fh))
    deriver = gd.createGearDeriverFromConfig(config)
    assert deriver is not None, "config.json no longer enables the derivation"
    return deriver


def _shippedParkDwellS() -> float:
    """The dwell the SHIPPED config produces -- read, never assumed.

    Every "held past the dwell" fixture below is timed off this rather than off
    the module default, so a config that disagreed with the module would make
    these tests fail rather than silently re-time them.
    """
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        config = ConfigValidator().validate(json.load(fh))
    return float(config["pi"]["gear"]["parkDwellSec"])


def _emitParked(
    tmp_path,
    *,
    linkHealthy: bool = True,
    holdS: float | None = None,
    speedKph: float | None = None,
    lastRpm: gd.Reading | None = None,
) -> dict:
    """Hold "no usable RPM" through the REAL producer; return what it wrote.

    ``lastRpm`` lets a caller hand the deriver a reading that AGES OUT instead
    of one that was never taken -- the post-drive state, and the one the story
    says a MISSING-only branch would never fire on.

    THE DEFAULT HOLD INCLUDES `maxAgeSec`, and that is not padding. The dwell
    clock starts when RPM becomes UNUSABLE, which for a present-but-ageing
    reading is one freshness window AFTER the data actually stopped -- so the
    real key-off-to-P delay is `parkDwellSec + maxAgeSec`. Pinned as a fact in
    `test_gear_park.py`; used here so the fixture is honest about it rather
    than a round number that happens to work for the absent case only.
    """
    statesDir = str(tmp_path / "states")
    emit = makeGearStateEmitter(statesDir)
    deriver = _shippedDeriver()
    limit = (
        _shippedParkDwellS() + gd.DEFAULT_MAX_AGE_S + 2.0 if holdS is None else holdS
    )

    startS = 1000.0
    nowS = startS
    while nowS <= startS + limit:
        emit(
            deriver.update(
                speed=None if speedKph is None else gd.Reading(speedKph, nowS),
                rpm=lastRpm,
                nowS=nowS,
                linkHealthy=linkHealthy,
            )
        )
        nowS += _POLL_PERIOD_S

    with open(os.path.join(statesDir, GEAR_STATE_FILENAME), encoding="utf-8") as fh:
        return json.load(fh)


def _emitOnce(tmp_path, speed: gd.Reading | None, rpm: gd.Reading | None) -> dict:
    """One derivation through the REAL producer; return what it wrote."""
    statesDir = str(tmp_path / "states")
    emit = makeGearStateEmitter(statesDir)
    emit(
        _shippedDeriver().update(
            speed=speed, rpm=rpm, nowS=1000.0, linkHealthy=True
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


def _surface(gearPayload: Any):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet."""
    routes: dict[str, Any] = {"/imu": _liveImu()}
    if gearPayload is not None:
        routes["/gear"] = gearPayload
    tree = rh.runDashboard(routes=routes, viewport=PANEL)["tree"]
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
    """The printed text of the first PAINTED element with ``className``."""
    for path in surface.pathsByClass(className):
        if not surface.rendered(path):
            continue
        return " ".join(_textOf(path[-1])).strip()
    return None


def _gearGlyph(surface) -> str | None:
    return _firstRendered(surface, "imu-gear")


def _gearDetail(surface) -> str | None:
    return _firstRendered(surface, "imu-gear-detail")


def _probe(fn: str, *args: object) -> object:
    """Evaluate one carousel.js export against fixtures via the node probe."""
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _everyProducerReason() -> tuple[str, ...]:
    """Every reason token the deriver can publish, DISCOVERED not copied.

    Read off the module by introspection rather than retyped, so a reason added
    to the producer joins this sweep the moment it exists. Its sibling file
    keeps a hand-written tuple, which is a sweep that expires the next time the
    vocabulary grows -- this story grew it once already.
    """
    reasons = tuple(
        getattr(gd, name)
        for name in sorted(dir(gd))
        if name.startswith("REASON_") and isinstance(getattr(gd, name), str)
    )
    assert gd.REASON_PARK in reasons, "introspection missed this story's own token"
    assert len(reasons) >= 10, f"the sweep found only {len(reasons)} reasons"
    return reasons


# ---------------------------------------------------------------------------
# Negative control. Every claim below is about what the GEAR glyph reads, and
# all of them would "pass" on a live face that never painted.
# ---------------------------------------------------------------------------


def test_theLiveFaceRenders_negativeControlForEveryClaimBelow(tmp_path):
    """
    Given: a live motion feed and a parked gear state
    When:  the panel renders
    Then:  the live face is genuinely painted, glyph element and all
    """
    surface = _surface(_emitParked(tmp_path))

    assert _firstRendered(surface, "imu-gear-label") == "GEAR", (
        "the live face did not paint -- every assertion in this file would be "
        "an artefact of the harness rather than a fact about the panel"
    )


# ---------------------------------------------------------------------------
# THE END STATE. The switched-off car, through the real producer, onto the
# panel -- and specifically NOT as the dash it painted before this story.
# ---------------------------------------------------------------------------


class TestParkReachesThePanel:
    """"the gear tile reads P when the OBD link gives no RPM"."""

    def test_aHealthyLinkWithNoRpm_heldPastTheDwell_paintsAP(self, tmp_path):
        """
        Given: a healthy link and no RPM, held past parkDwellSec
        When:  the producer's states/gear is served to the shipped carousel
        Then:  the GEAR glyph on the panel reads P
        """
        surface = _surface(_emitParked(tmp_path))

        assert _gearGlyph(surface) == "P"

    def test_park_doesNotFallThroughToTheDash(self, tmp_path):
        """
        Given: the parked state on the panel
        When:  the glyph is read
        Then:  it is NOT the `--` an unhandled gear value produces

        Stated as its own assertion rather than left implied by the test above,
        because `--` is exactly what this payload rendered BEFORE the story: the
        producer half alone would have looked complete and changed nothing on
        the panel.
        """
        surface = _surface(_emitParked(tmp_path))

        assert _gearGlyph(surface) != EN_DASH_PAIR

    def test_park_paintsDriverEnglishAsItsDetail(self, tmp_path):
        """
        Given: the parked state on the panel
        When:  the detail line is read
        Then:  it says `parked` -- words, not the `park` state token verbatim
        """
        assert _gearDetail(_surface(_emitParked(tmp_path))) == "parked"

    def test_theProducerIsWhatDecidesTheP_notTheRenderer(self, tmp_path):
        """
        Given: the payload the producer actually wrote for a parked car
        When:  it is inspected before it ever reaches the renderer
        Then:  it already says P

        Splits the chain deliberately: if this passes and the render test above
        fails, the defect is in the transport; if both fail, it is in the
        derivation. Without it a red end-to-end test names no component.
        """
        payload = _emitParked(tmp_path)

        assert payload["available"] is True
        assert payload["gear"] == "P"
        assert payload["reason"] == gd.REASON_PARK

    def test_gearView_hasAPCase_thatReturnsARenderedValue(self):
        """
        Given: a `"P"` payload put straight through the shipped gearView
        When:  the returned view is read
        Then:  it is available, and its value is P rather than the fallthrough

        The story's grep criterion, expressed as a call rather than a grep: a
        text search for "P" in a 5,600-line file cannot distinguish a branch
        from a comment, and it cannot tell whether the branch RETURNS anything.
        """
        view = _probe("gearView", {"available": True, "gear": "P", "reason": "park"})

        assert view["available"] is True
        assert view["value"] == "P"
        assert view["value"] != EN_DASH_PAIR

    def test_theShippedConfigCarriesTheRuledDwell(self):
        """
        Given: config.json as it ships
        When:  pi.gear.parkDwellSec is read through the validator
        Then:  it is the ruled 20.0, above the 13 s floor and inside the ~45 s
               pre-shutdown ceiling

        A GUARD ON THE FIXTURE, NOT ON THE CODE. Every timing fixture in this
        file is measured off the shipped value, so a config edit re-times them
        all silently and they would keep passing. This fails instead.
        """
        dwell = _shippedParkDwellS()

        assert dwell == 20.0
        assert dwell > _WORST_MEASURED_RPM_GAP_S
        assert dwell < 45.0


# ---------------------------------------------------------------------------
# THE CONDITIONS, END TO END. Each of these is a payload the panel must NOT
# paint a P for, and each corresponds to a real incident or a real drive.
# ---------------------------------------------------------------------------


class TestTheConditionsHoldOnThePanel:
    """The dwell and the link condition, measured at the glyph."""

    def test_noRpmButBelowTheDwell_stillPaintsADash(self, tmp_path):
        """
        Given: a healthy link with no RPM, held for less than parkDwellSec
        When:  the panel renders
        Then:  the honest dash, not P. The dwell is the point.
        """
        surface = _surface(
            _emitParked(tmp_path, holdS=_shippedParkDwellS() - 5.0)
        )

        assert _gearGlyph(surface) == EN_DASH_PAIR

    def test_anUnhealthyLink_neverPaintsAP(self, tmp_path):
        """
        Given: no RPM and an UNHEALTHY link, held far past the dwell
        When:  the panel renders
        Then:  no P -- the 2026-09-04 loose-dongle incident

        That day the dongle gave `Connected: no` with 41 failed attempts and
        capture produced nothing for two days. Without this condition the panel
        would have read a confident PARK throughout, manufactured out of a
        broken connector.
        """
        surface = _surface(
            _emitParked(
                tmp_path, linkHealthy=False, holdS=_shippedParkDwellS() * 2.0
            )
        )

        assert _gearGlyph(surface) != "P"

    def test_theThirteenSecondBusStallAtSpeed_paintsNoP(self, tmp_path):
        """
        Given: the worst RPM gap measured over 2,141 samples, with SPEED alive
        When:  the panel renders
        Then:  no P

        The measurement that sized the dwell, taken at the glyph rather than at
        the deriver -- because the claim the CIO cares about is what the panel
        shows him at 60 mph.
        """
        surface = _surface(
            _emitParked(
                tmp_path,
                holdS=_WORST_MEASURED_RPM_GAP_S,
                speedKph=_MOVING_SPEED_KPH,
            )
        )

        assert _gearGlyph(surface) != "P"

    def test_aPostDriveStaleReading_paintsAP(self, tmp_path):
        """
        Given: an RPM reading that AGED OUT rather than went away
        When:  a healthy link holds that past the dwell and the panel renders
        Then:  P

        🔴 THE NORMAL PARKED CASE, and the one a MISSING-only branch never
        reaches. `_lastRpmReading` is never cleared by the orchestrator; after a
        drive it is PRESENT and OLD. If this file only ever fed `None` it would
        be testing a cold boot, which is not when anybody looks at this tile.
        """
        surface = _surface(
            _emitParked(tmp_path, lastRpm=gd.Reading(_MEASURED_IDLE_RPM, 1000.0))
        )

        assert _gearGlyph(surface) == "P"


# ---------------------------------------------------------------------------
# P MUST NOT SWALLOW ITS NEIGHBOURS. Three glyphs, three distinct payloads,
# compared against each other -- a hardcoded glyph passes any one of them.
# ---------------------------------------------------------------------------


class TestParkStealsNoCaseFromItsNeighbours:
    """P, N and a derived digit are three different things on one tile."""

    def test_engineOffAtAStandstill_paintsPNotN(self, tmp_path):
        """
        Given: RPM 0 and SPEED 0, both present -- the ECU with the engine off
        When:  the panel renders
        Then:  P. A car that is off is not in neutral.
        """
        payload = _emitOnce(tmp_path, gd.Reading(0.0, 1000.0), gd.Reading(0.0, 1000.0))

        assert _gearGlyph(_surface(payload)) == "P"

    def test_measuredIdleAtAStandstill_stillPaintsN(self, tmp_path):
        """
        Given: RPM 800 and SPEED 0 -- the CIO at a stoplight
        When:  the panel renders
        Then:  N, not P -- US-687-a's branch is not regressed

        Pinned at the measured idle average, which is BELOW the 900 rpm ratio
        floor: a fixture at 1,200 rpm passes for an implementation this car
        would fail.
        """
        payload = _emitOnce(
            tmp_path, gd.Reading(0.0, 1000.0), gd.Reading(_MEASURED_IDLE_RPM, 1000.0)
        )

        assert _gearGlyph(_surface(payload)) == "N"

    def test_theThreeStatesPaintThreeDifferentGlyphs(self, tmp_path):
        """
        Given: a parked car, a stopped-but-running car and a moving one
        When:  each is rendered
        Then:  the panel prints three different things

        Held as one comparison rather than three isolated assertions: each of
        those would pass against a glyph hardcoded to whichever value it
        checked, which is precisely how a producer that never ran looks correct.
        """
        parked = _surface(_emitParked(tmp_path / "p"))
        idling = _surface(
            _emitOnce(
                tmp_path / "n",
                gd.Reading(0.0, 1000.0),
                gd.Reading(_MEASURED_IDLE_RPM, 1000.0),
            )
        )

        statesDir = str(tmp_path / "d" / "states")
        emit = makeGearStateEmitter(statesDir)
        deriver = _shippedDeriver()
        nowS = 1000.0
        while nowS <= 1000.0 + gd.DEFAULT_DEBOUNCE_S + 0.5:
            emit(
                deriver.update(
                    speed=gd.Reading(_MOVING_SPEED_KPH, nowS),
                    rpm=gd.Reading(_MOVING_RPM, nowS),
                    nowS=nowS,
                    linkHealthy=True,
                )
            )
            nowS += _POLL_PERIOD_S
        with open(os.path.join(statesDir, GEAR_STATE_FILENAME), encoding="utf-8") as fh:
            moving = _surface(json.load(fh))

        glyphs = (_gearGlyph(parked), _gearGlyph(idling), _gearGlyph(moving))

        assert glyphs == ("P", "N", "2")
        assert len(set(glyphs)) == 3


# ---------------------------------------------------------------------------
# NO RAW INTERNAL TOKEN REACHES THE DRIVER -- swept over a vocabulary this
# story just grew, discovered rather than copied.
# ---------------------------------------------------------------------------


class TestTheDriverNeverSeesMachineVocabulary:
    """`park` is a token; `parked` is a word."""

    def test_everyProducerReason_rendersWithoutAnUnderscore(self):
        """
        Given: every reason constant the deriver module defines
        When:  each is put through the renderer's reason text
        Then:  none reaches the driver carrying an underscore

        DISCOVERED BY INTROSPECTION, so a reason added later without a phrase
        fails here instead of appearing on the panel. This story is the proof
        that matters: it added `park`, and a hand-written sweep would not have
        covered it.
        """
        for reason in _everyProducerReason():
            rendered = _probe("gearReasonText", reason)

            assert "_" not in rendered, f"{reason!r} rendered as {rendered!r}"

    def test_theParkToken_isTranslatedNotPassedThrough(self):
        """
        Given: the `park` reason token
        When:  it goes through the renderer's reason text
        Then:  it comes out as `parked`, not as the raw token

        `park` has no underscore, so the sweep above cannot catch it being
        passed through untranslated -- the one token in this vocabulary where
        the general test is blind. Pinned separately for exactly that reason.
        """
        assert _probe("gearReasonText", gd.REASON_PARK) == "parked"

    def test_theStateFileKeepsTheExactTokenTheRendererHumanised(self, tmp_path):
        """
        Given: the parked payload the producer wrote
        When:  its reason is compared to what the panel printed
        Then:  the file keeps `park` while the panel says `parked`

        Both halves on one payload. Humanising in the PRODUCER would have
        destroyed the precise token on its way to the one consumer that needs
        it least -- tests, logs and any future reader of states/gear all want
        the exact word.
        """
        payload = _emitParked(tmp_path)

        assert payload["reason"] == gd.REASON_PARK
        assert _gearDetail(_surface(payload)) == "parked"
