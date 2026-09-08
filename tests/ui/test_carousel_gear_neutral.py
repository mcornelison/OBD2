################################################################################
# File Name: test_carousel_gear_neutral.py
# Purpose/Description: US-687-a END STATE -- "the gear tile reads N at a light".
#   Pinned where the driver reads it: the SHIPPED config.json bands -> the REAL
#   deriver -> the REAL states/gear emitter -> a real file -> the SHIPPED
#   carousel.js over the SHIPPED markup and stylesheet at 480x320.
#
#   THIS SUB-STORY IS PRODUCER-ONLY AND THIS FILE IS WHY THAT IS SAFE TO SAY.
#   `gearView` has carried `value:"N", detail:"neutral", level:"neutral"` since
#   US-508 -- the fifth renderer-with-no-producer on this project -- so the
#   claim being verified here is that the EXISTING render path still works when
#   a producer finally reaches it, not that a new one was added. A story that
#   asserts an untouched renderer without rendering it is asserting a memory.
#
#   ONE RENDERER CHANGE DOES SHIP HERE, and it is not the N branch: the gear
#   reasons reached the panel as raw snake_case (`below_threshold` was on the
#   card at every stoplight). `gearReasonText` is the one place they become
#   driver English; the token in states/gear is unchanged.
#
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-07    | Rex (US-687-a) | Initial -- N on the panel, and the sweep that
#               |                | keeps machine vocabulary off it.
# ================================================================================
################################################################################

"""US-687-a: neutral, from the stationary sample to the rendered glyph."""

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

# MEASURED on this car, and the whole point of the fixture. Idle averages 800
# rpm (min 684) and 91.6 % of stationary samples fall BELOW the 900 rpm ratio
# floor -- so an implementation gated on that floor renders correctly at 1,200
# rpm on a bench and never once lights at a real stoplight.
_MEASURED_IDLE_RPM = 800.0

# 2500 rpm at 45 km/h is 55.6 rpm/kph -- inside the SHIPPED 2nd-gear band
# (54.3 to 86.7). Both readings present, both above every gate.
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


def _emitOnce(tmp_path, speed: gd.Reading | None, rpm: gd.Reading | None) -> dict:
    """One derivation through the REAL producer; return what it wrote."""
    statesDir = str(tmp_path / "states")
    emit = makeGearStateEmitter(statesDir)
    emit(_shippedDeriver().update(speed=speed, rpm=rpm, nowS=1000.0))
    with open(os.path.join(statesDir, GEAR_STATE_FILENAME), encoding="utf-8") as fh:
        return json.load(fh)


def _emitStationary(tmp_path, rpm: float = _MEASURED_IDLE_RPM) -> dict:
    """The car at a light: SPEED PRESENT and reading exactly zero."""
    return _emitOnce(tmp_path, gd.Reading(0.0, 1000.0), gd.Reading(rpm, 1000.0))


def _emitHeld(tmp_path, speedKph: float, rpm: float) -> dict:
    """Hold one steady moving point past the debounce, through the producer."""
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


# Every reason the producer can put in states/gear. Read from the MODULE, not
# retyped: a new reason added to the deriver joins this sweep automatically
# instead of quietly bypassing it.
_PRODUCER_REASONS = (
    gd.REASON_ENGAGED,
    gd.REASON_NEUTRAL,
    gd.REASON_NO_DATA,
    gd.REASON_STALE,
    gd.REASON_NOT_CALIBRATED,
    gd.REASON_BELOW_THRESHOLD,
    gd.REASON_NO_BAND,
    gd.REASON_AMBIGUOUS,
    gd.REASON_SETTLING,
)


# ---------------------------------------------------------------------------
# Negative control. Every claim below is about what the GEAR glyph reads, and
# all of them would "pass" on a live face that never painted.
# ---------------------------------------------------------------------------


def test_theLiveFaceRenders_negativeControlForEveryClaimBelow(tmp_path):
    """
    Given: a live motion feed and a stationary gear state
    When:  the panel renders
    Then:  the live face is genuinely painted, glyph element and all
    """
    surface = _surface(_emitStationary(tmp_path))

    assert _firstRendered(surface, "imu-gear-label") == "GEAR", (
        "the live face did not paint -- every assertion in this file would be "
        "an artefact of the harness rather than a fact about the panel"
    )


# ---------------------------------------------------------------------------
# THE END STATE. A stopped car, through the real producer, onto the panel.
# ---------------------------------------------------------------------------


class TestNeutralReachesThePanel:
    """"the gear tile shows N when the engine is turning and SPEED is 0"."""

    def test_measuredIdleAtAStandstill_paintsAnN(self, tmp_path):
        """
        Given: RPM 800 and SPEED 0, both PRESENT -- the CIO stopped at a light
        When:  the producer's states/gear is served to the shipped carousel
        Then:  the GEAR glyph on the panel reads N
        """
        surface = _surface(_emitStationary(tmp_path))

        assert _gearGlyph(surface) == "N"

    def test_neutral_paintsNeutralAsItsDetail(self, tmp_path):
        """
        Given: the stationary state on the panel
        When:  the detail line is read
        Then:  it says `neutral` -- the US-508 branch, confirmed working
        """
        surface = _surface(_emitStationary(tmp_path))

        assert _gearDetail(surface) == "neutral"

    def test_theProducerIsWhatDecidesTheN_notTheRenderer(self, tmp_path):
        """
        Given: the payload the producer actually wrote for a stopped car
        When:  it is inspected before it ever reaches the renderer
        Then:  it already says N

        Splits the chain deliberately: if this passes and the render test above
        fails, the defect is in the transport; if both fail, it is in the
        derivation. Without it a red end-to-end test names no component.
        """
        payload = _emitStationary(tmp_path)

        assert payload["available"] is True
        assert payload["gear"] == "N"
        assert payload["reason"] == gd.REASON_NEUTRAL

    def test_theFixtureIsBelowTheRatioFloor_whichIsThePoint(self, tmp_path):
        """
        Given: the idle rpm this file feeds
        When:  it is compared to the 900 rpm ratio floor
        Then:  it is BELOW it

        A GUARD ON THE FIXTURE ITSELF, not on the code. Every N assertion in
        this file is only worth something because its rpm is under the floor;
        if a future edit "tidies" 800 up to 1,200 the tests all still pass and
        stop testing the thing they were written for. This fails instead.
        """
        assert _MEASURED_IDLE_RPM < gd.DEFAULT_MIN_RPM


class TestNeutralAndTheDerivedGearAreNotTheSameGlyph:
    """N must not swallow the cases either side of it, on the panel."""

    def test_movingAboveEveryGate_paintsTheDerivedGear_notAnN(self, tmp_path):
        """
        Given: RPM 2500 at 45 km/h -- inside the shipped 2nd-gear band
        When:  the panel renders
        Then:  it reads 2, not N

        Held as a direct comparison against the N case below, because both
        tests would pass against a glyph hardcoded to whichever value was
        checked first -- which is precisely how a producer that never ran can
        look correct.
        """
        surface = _surface(_emitHeld(tmp_path, _MOVING_SPEED_KPH, _MOVING_RPM))

        assert _gearGlyph(surface) == "2"

    def test_theTwoStatesPaintTwoDifferentGlyphs(self, tmp_path):
        """
        Given: a stopped car and a moving one
        When:  each is rendered
        Then:  the panel prints two different things
        """
        stopped = _surface(_emitStationary(tmp_path / "a"))
        moving = _surface(_emitHeld(tmp_path / "b", _MOVING_SPEED_KPH, _MOVING_RPM))

        assert _gearGlyph(stopped) == "N"
        assert _gearGlyph(moving) == "2"


class TestAbsentSpeedIsNotZeroSpeed:
    """The trap that would have shipped a branch that never fires."""

    def test_rpmPresentAndTheSpeedKeyAbsent_paintsADashNotAnN(self, tmp_path):
        """
        Given: a live RPM and NO speed reading at all
        When:  the panel renders
        Then:  the glyph is a dash -- absent is not zero

        WHICH BRANCH AND WHY, as the story asks: the producer resolves a None
        reading to its _MISSING sentinel and returns `no_data`, whose glyph is
        the dash. That is correct and it is why N had to trigger on SPEED == 0
        rather than on SPEED being missing -- this car reports a PRESENT zero
        when stopped (388 of drive 64's 614 SPEED rows), so a "speed missing"
        branch would never once have fired at a stoplight.
        """
        payload = _emitOnce(
            tmp_path, None, gd.Reading(_MEASURED_IDLE_RPM, 1000.0)
        )
        assert payload["reason"] == gd.REASON_NO_DATA

        surface = _surface(payload)

        assert _gearGlyph(surface) == EN_DASH_PAIR
        assert _gearGlyph(surface) != "N"


# ---------------------------------------------------------------------------
# NO RAW INTERNAL TOKEN REACHES THE DRIVER.
# ---------------------------------------------------------------------------


class TestTheDriverNeverSeesMachineVocabulary:
    """Every reason the producer can emit, rendered as words."""

    def test_everyProducerReason_rendersWithoutAnUnderscore(self):
        """
        Given: every reason string the deriver can publish
        When:  each is put through the renderer's reason text
        Then:  none of them reaches the driver carrying an underscore

        Swept over the MODULE's constants rather than a hand-written list, so a
        reason added to the producer without a phrase here fails this test
        instead of appearing on the panel.
        """
        for reason in _PRODUCER_REASONS:
            rendered = _probe("gearReasonText", reason)

            assert "_" not in rendered, f"{reason!r} rendered as {rendered!r}"

    def test_belowThreshold_isTheOneTheCioWasActuallyReading(self, tmp_path):
        """
        Given: a car creeping at 0.1 km/h -- the below_threshold case
        When:  the panel renders
        Then:  the detail is English, and the token is nowhere on the card

        Named on its own because it is the specific string the story cites: a
        snake_case token on a 3.5in dashboard read at speed.
        """
        payload = _emitOnce(
            tmp_path, gd.Reading(0.1, 1000.0), gd.Reading(1500.0, 1000.0)
        )
        assert payload["reason"] == gd.REASON_BELOW_THRESHOLD

        surface = _surface(payload)
        detail = _gearDetail(surface)

        assert detail == "too slow to tell"
        assert "below_threshold" not in detail

    def test_theStateFileKeepsTheMachineToken(self, tmp_path):
        """
        Given: the same creeping car
        When:  states/gear is inspected
        Then:  it still carries `below_threshold`, unchanged

        THE OTHER HALF OF THE FIX, and the one that makes it safe. The reason
        is humanised at the RENDERER, so the exact token keeps travelling in
        the state file for tests, logs and any future consumer. Translating it
        in the producer instead would have destroyed the precise value on its
        way to the one place that needs it least.
        """
        payload = _emitOnce(
            tmp_path, gd.Reading(0.1, 1000.0), gd.Reading(1500.0, 1000.0)
        )

        assert payload["reason"] == "below_threshold"

    def test_anUnknownReason_stillReachesTheDriverAsWords(self):
        """
        Given: a reason token this renderer has never heard of
        When:  it is rendered
        Then:  the underscores are gone anyway

        The sweep above is only true of today's vocabulary. This is what keeps
        it true of tomorrow's: a producer that grows a token degrades to
        readable words rather than to machine vocabulary.
        """
        rendered = _probe("gearReasonText", "some_future_token")

        assert rendered == "some future token"

    def test_noReasonAtAll_stillReadsNoSource(self):
        """
        Given: a payload with no reason
        When:  it is rendered
        Then:  the long-standing `no source` text is unchanged

        The US-508 wording the operator already knows, held so the humanising
        pass did not quietly reword the commonest absence on the card.
        """
        assert _probe("gearReasonText", None) == "no source"
        assert _probe("gearReasonText", "") == "no source"
