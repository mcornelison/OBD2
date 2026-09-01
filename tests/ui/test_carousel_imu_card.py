################################################################################
# File Name: test_carousel_imu_card.py
# Purpose/Description: US-497 (S4-card, F-113) tests -- the IMU live-instrument
#   card renders g-force + compass LIVE from the states/imu file US-478's bridge
#   writes, and is a PURE CONSUMER (it maps + formats the derived contract; it
#   never fuses, never re-derives). Four groups:
#     1. The freshness gate. A live graphical instrument has a failure mode a
#        text tile does not -- FREEZING. A gray "NA" reads as dead; a g-dot
#        frozen at 0.4 g reads exactly like a car holding a steady corner. So an
#        explicit available:false, an UNDATED payload, or a reading older than
#        the stale window falls back to the calm idle body (AC-3), and the
#        instrument geometry is not rendered at all.
#     2. Per-field honest-availability. A dead magnetometer grays HEADING alone
#        while the g fields stay live; altitude is ALWAYS typed-NA "no source"
#        (the ICM-20948 has no barometer) and never blocks the card.
#     3. The instrument geometry -- the sign contract (gLon + = accelerating,
#        gLat + = RIGHT) mapped to screen coordinates, the full-scale clamp, the
#        compass rose, and the client-side trail window (Atlas Q-B: the trail is
#        accumulated from polled values, so its EVICTION is correctness).
#     4. Wiring + SSOT. The tick must actually call the view + renderer (a
#        correct routine nobody calls is worth nothing -- US-494/495/496), the
#        card ships always-present (NOT vehicle-gated -- the IMU is a Pi-local
#        sensor), and the CSS introduces no palette of its own.
#   Pure logic runs through the shared node probe (tests/ui/carousel_probe.js);
#   the browser-only DOM wiring is pinned by reading the shipped artifacts.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-31    | Ralph (Rex)  | Initial -- US-497 IMU live-instrument card.
# ================================================================================
################################################################################

"""US-497 tests for the IMU live-instrument card (g-force + compass)."""

import json
import math
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard"
)
_HTML = os.path.join(_DIST, "dashboard.html")
_JS = os.path.join(_DIST, "carousel.js")
_CSS = os.path.join(_DIST, "dashboard.css")

# A fixed read-time + its epoch-ms so every freshness assertion is deterministic.
_TS = "2026-07-31T12:00:00+00:00"
_TS_MS = int(datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)

# The card's own constants, mirrored here so a drift in either breaks a test.
# IMU_STALE_SEC is derived from the PRODUCER's cadence: the bridge writes at
# pi.sensors.imu.stateHz (4 Hz -> 250 ms), so 2.0 s is 8 missed writes.
_STALE_SEC = 2.0
_G_FULL_SCALE = 1.0  # outer ring of the g-meter, in g
_TRAIL_SEC = 35.0  # Iris live-instrument spec: a 35 s g-trail

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _view(fn: str, *args: object) -> object:
    """Evaluate one carousel.js export against fixtures via the node probe."""
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _imu(
    *,
    available: bool = True,
    ts: str | None = _TS,
    gLat: float | None = 0.0,
    gLon: float | None = 0.0,
    gMag: float | None = 0.0,
    headingDeg: float | None = 0.0,
    gradePct: float | None = 0.0,
    reasons: dict | None = None,
) -> dict:
    """A states/imu payload exactly as imu_state_bridge.buildImuState writes it.

    Built from the CONTRACT in specs/architecture.md 10.8.2, not from the
    bridge's own test fixtures -- so this suite pins the contract rather than
    agreeing with the producer's tests about a shared misreading.
    """
    payload: dict = {
        "available": available,
        "ts": ts,
        "gLat": gLat,
        "gLon": gLon,
        "gMag": gMag,
        "headingDeg": headingDeg,
        "gradePct": gradePct,
        "altitude": None,
        "reasons": {"altitude": "no_source"},
    }
    if reasons:
        payload["reasons"].update(reasons)
    return payload


def _absent(reason: str = "sensor_absent") -> dict:
    """The explicit available:false state the bridge writes for an unwired IMU."""
    return _imu(
        available=False,
        gLat=None,
        gLon=None,
        gMag=None,
        headingDeg=None,
        gradePct=None,
        reasons={
            f: reason
            for f in ("gLat", "gLon", "gMag", "headingDeg", "gradePct")
        },
    )


def _fnBody(js: str, name: str) -> str:
    """The source text of one `function <name>(` up to the next top-level one."""
    start = js.index(f"function {name}(")
    nxt = js.find("\n  function ", start + 1)
    return js[start:] if nxt == -1 else js[start:nxt]


# =============================================================================
# 1. The freshness gate -- a live instrument must never freeze (AC-3).
# =============================================================================


class TestImuFreshnessGate:
    """Absent / unavailable / undated / stale -> the calm idle body, never a
    frozen or zeroed live instrument."""

    def test_imuView_absentStateFile_returnsNullSoTheShellRendersNoData(self):
        """
        Given: no states/imu file at all (the fetch yielded null)
        When: the view is built
        Then: null -- the shell owns the whole-card absent message, exactly as
              it does for every other card (one place decides absence)
        """
        assert _view("imuView", None, _TS_MS) is None
        assert _view("imuView", "not-an-object", _TS_MS) is None

    def test_imuView_sensorNotWired_fallsBackToIdleNamingTheSensor(self):
        """
        Given: the bridge's EXPLICIT available:false state (IMU unplugged)
        When: the view is built
        Then: the idle fallback, carrying the sensor_absent reason in words --
              the instrument is NOT rendered (AC-3: never a zeroed instrument)
        """
        view = _view("imuView", _absent(), _TS_MS)
        assert view["idle"] is True
        assert "sensor not detected" in view["reason"]
        assert "g" not in view  # no instrument geometry at all

    def test_imuView_undatedPayload_fallsBackToIdle(self):
        """
        Given: a payload claiming available but carrying no parseable ts
        When: the view is built
        Then: idle -- an UNDATED reading is the one most likely to be stale, so
              it can never be rendered as a live instrument
        """
        assert _view("imuView", _imu(ts=None), _TS_MS)["idle"] is True
        assert _view("imuView", _imu(ts="not-a-date"), _TS_MS)["idle"] is True

    def test_imuView_staleReading_fallsBackToIdleAndSaysHowStale(self):
        """
        Given: a reading older than the stale window (the feed stopped)
        When: the view is built
        Then: idle, and the reason reports the AGE -- "the feed stopped" is a
              different fault from "no sensor" and the operator needs to know
        """
        nowMs = _TS_MS + int((_STALE_SEC + 3.0) * 1000)
        view = _view("imuView", _imu(), nowMs)
        assert view["idle"] is True
        assert "stale" in view["reason"]

    def test_imuView_freshReading_rendersTheLiveInstrument(self):
        """
        Given: a reading inside the stale window
        When: the view is built
        Then: the live instrument, not the idle body
        """
        nowMs = _TS_MS + int((_STALE_SEC - 0.5) * 1000)
        view = _view("imuView", _imu(gLat=0.10, gLon=-0.20, gMag=0.22), nowMs)
        assert view["idle"] is False
        assert view["g"]["available"] is True

    def test_imuView_aZeroReadingIsLiveNotAbsent(self):
        """
        Given: a genuinely stationary vehicle -- a real, fresh 0.00 g reading
        When: the view is built
        Then: LIVE (0 g is a measurement, not a missing value). The honest
              instrument must distinguish "measured zero" from "no reading";
              collapsing them is the fabrication this whole card guards against.
        """
        view = _view("imuView", _imu(gLat=0.0, gLon=0.0, gMag=0.0), _TS_MS)
        assert view["idle"] is False
        assert view["g"]["available"] is True
        assert view["g"]["dot"] == {"x": 0.0, "y": 0.0, "clamped": False}


# =============================================================================
# 2. Per-field honest-availability -- one dead field never blanks the card.
# =============================================================================


class TestImuPerFieldAvailability:
    """A dead magnetometer grays HEADING alone; altitude is always typed-NA."""

    def test_imuView_altitudeIsAlwaysTypedNaNoSource(self):
        """
        Given: a fully live IMU reading
        When: the view is built
        Then: altitude STILL reads NA "no source" -- the ICM-20948 has no
              barometer, and a zeroed altitude renders as sea level, a
              confident lie. It must not block the card (AC-2).
        """
        view = _view("imuView", _imu(), _TS_MS)
        assert view["altitude"]["value"] == "NA"
        assert view["altitude"]["level"] == "unavailable"
        assert "no source" in view["altitude"]["detail"]
        assert view["idle"] is False  # does not block the card

    def test_imuView_deadMagnetometer_graysHeadingOnlyAndLeavesGLive(self):
        """
        Given: a live accel reading but no magnetometer reading
        When: the view is built
        Then: HEADING is a typed-NA tile naming the reason, while the g
              instrument stays fully live -- honest-availability is PER FIELD
        """
        view = _view(
            "imuView",
            _imu(gLat=0.3, gLon=0.1, gMag=0.32, headingDeg=None,
                 reasons={"headingDeg": "no_mag_reading"}),
            _TS_MS,
        )
        assert view["heading"]["value"] == "NA"
        assert "compass" in view["heading"]["detail"]
        assert view["heading"]["available"] is False
        assert view["g"]["available"] is True  # unaffected

    def test_imuView_pitchOutOfRange_graysGradeOnly(self):
        """
        Given: a pitch past the bridge's 85-degree guard (gradePct null)
        When: the view is built
        Then: GRADE grays with its own reason; g + heading stay live
        """
        view = _view(
            "imuView",
            _imu(gradePct=None, reasons={"gradePct": "pitch_out_of_range"}),
            _TS_MS,
        )
        assert view["grade"]["value"] == "NA"
        assert "pitch" in view["grade"]["detail"]
        assert view["g"]["available"] is True
        assert view["heading"]["available"] is True

    def test_imuView_unresolvedTilt_graysGWhileHeadingSurvives(self):
        """
        Given: the horizontal g could not be resolved (tilt_unresolved)
        When: the view is built
        Then: the g tile grays AND carries no dot -- a dot at the origin would
              be a fabricated "stationary" reading, the exact zeroed-instrument
              AC-3 forbids
        """
        view = _view(
            "imuView",
            _imu(gLat=None, gLon=None, gMag=None,
                 reasons={"gLat": "tilt_unresolved", "gLon": "tilt_unresolved"}),
            _TS_MS,
        )
        assert view["g"]["available"] is False
        assert view["g"]["dot"] is None
        assert "orientation" in view["g"]["detail"]

    def test_imuView_unknownReasonCode_passesTheRawCodeThrough(self):
        """
        Given: a reason vocabulary the card does not know (a future bridge code)
        When: the view is built
        Then: the raw code is shown, never swallowed into a generic word -- an
              unmapped reason is still information the operator can act on
        """
        view = _view(
            "imuView",
            _imu(headingDeg=None, reasons={"headingDeg": "mag_calibrating"}),
            _TS_MS,
        )
        assert "mag_calibrating" in view["heading"]["detail"]


# =============================================================================
# 3. Instrument geometry -- the sign contract, the clamp, the rose, the trail.
# =============================================================================


class TestGDotGeometry:
    """The contract's sign conventions mapped to SCREEN coordinates."""

    def test_gDotPosition_acceleratingPutsTheDotUp(self):
        """
        Given: gLon +0.5 (the contract: + = accelerating)
        When: the dot is placed
        Then: y is NEGATIVE -- up the screen. Getting this backwards inverts the
              instrument in a way that still looks plausible in a screenshot.
        """
        dot = _view("gDotPosition", 0.0, 0.5, _G_FULL_SCALE)
        assert dot["y"] < 0
        assert dot["x"] == 0.0

    def test_gDotPosition_brakingPutsTheDotDown(self):
        """
        Given: gLon -0.5 (the contract: - = braking)
        When: the dot is placed
        Then: y is POSITIVE -- down the screen
        """
        assert _view("gDotPosition", 0.0, -0.5, _G_FULL_SCALE)["y"] > 0

    def test_gDotPosition_rightHandTurnPutsTheDotRight(self):
        """
        Given: gLat +0.5 (the contract: + = RIGHT, automotive convention)
        When: the dot is placed
        Then: x is POSITIVE -- right of centre
        """
        assert _view("gDotPosition", 0.5, 0.0, _G_FULL_SCALE)["x"] > 0

    def test_gDotPosition_beyondFullScale_clampsToTheRingKeepingDirection(self):
        """
        Given: a reading past the outer ring (a hard 1.4 g stop)
        When: the dot is placed
        Then: it sits ON the ring (magnitude 1) with its DIRECTION preserved and
              a `clamped` flag -- the dot never leaves the instrument, and the
              numeric readout still carries the true magnitude, so the clamp
              cannot understate the event silently
        """
        dot = _view("gDotPosition", 0.0, -1.4, _G_FULL_SCALE)
        assert dot["clamped"] is True
        assert math.isclose(math.hypot(dot["x"], dot["y"]), 1.0, rel_tol=1e-9)
        assert dot["y"] > 0  # still braking, still downward

    def test_gDotPosition_clampPreservesTheAngleNotJustTheMagnitude(self):
        """
        Given: an over-scale diagonal (equal lateral + longitudinal)
        When: the dot is clamped
        Then: it stays on the 45-degree diagonal -- clamping each axis
              independently would swing the dot to the corner and misreport
              WHICH WAY the car was loaded
        """
        dot = _view("gDotPosition", 2.0, 2.0, _G_FULL_SCALE)
        assert math.isclose(abs(dot["x"]), abs(dot["y"]), rel_tol=1e-9)

    def test_gDotPosition_nonFiniteReading_returnsNullNotAnOrigin(self):
        """
        Given: a null / non-finite component
        When: the dot is placed
        Then: null -- never the origin, which would render as a real "no g"
        """
        assert _view("gDotPosition", None, 0.2, _G_FULL_SCALE) is None
        assert _view("gDotPosition", 0.2, None, _G_FULL_SCALE) is None


class TestCompassRose:
    """headingDeg -> the 16-point rose the card labels the bearing with."""

    @pytest.mark.parametrize(
        "deg,expected",
        [
            (0, "N"), (90, "E"), (180, "S"), (270, "W"),
            (45, "NE"), (135, "SE"), (225, "SW"), (315, "NW"),
            (22.5, "NNE"), (112.5, "ESE"),
        ],
    )
    def test_headingCardinal_mapsTheEightAndSixteenPointBearings(self, deg, expected):
        """
        Given: a magnetic bearing
        When: it is named
        Then: the correct 16-point rose label
        """
        assert _view("headingCardinal", deg) == expected

    def test_headingCardinal_wrapsAcrossNorthRatherThanFallingOffTheEnd(self):
        """
        Given: a bearing just shy of a full turn (359 degrees)
        When: it is named
        Then: "N" -- the rose is circular; an index that runs off the array end
              would read undefined exactly as the vehicle points north
        """
        assert _view("headingCardinal", 359) == "N"
        assert _view("headingCardinal", 360) == "N"

    def test_headingCardinal_nonFinite_returnsNull(self):
        """
        Given: no bearing
        When: it is named
        Then: null -- never a fabricated "N"
        """
        assert _view("headingCardinal", None) is None


class TestGTrail:
    """The client-side g-trail (Atlas Q-B: accumulated from POLLED values)."""

    def test_pushGTrail_appendsTheNewestPointWithItsTimestamp(self):
        """
        Given: an empty trail
        When: a point is pushed
        Then: it is retained, stamped with the read instant
        """
        trail = _view("pushGTrail", [], {"x": 0.2, "y": -0.1}, _TS_MS, _TRAIL_SEC)
        assert trail == [{"x": 0.2, "y": -0.1, "t": _TS_MS}]

    def test_pushGTrail_evictsPointsOlderThanTheWindow(self):
        """
        Given: a trail holding a point older than the 35 s window
        When: a new point is pushed
        Then: the stale point is DROPPED. The trail is the one piece of client
              state on this card, so eviction is correctness: an unbounded trail
              both leaks and paints a smear of history as if it were current.
        """
        old = {"x": 0.9, "y": 0.9, "t": _TS_MS - int((_TRAIL_SEC + 5) * 1000)}
        keep = {"x": 0.1, "y": 0.1, "t": _TS_MS - 1000}
        trail = _view("pushGTrail", [old, keep], {"x": 0.0, "y": 0.0}, _TS_MS, _TRAIL_SEC)
        assert len(trail) == 2
        assert old not in trail
        assert trail[0] == keep  # chronological order preserved

    def test_pushGTrail_withNoPoint_stillEvictsSoAGapDecays(self):
        """
        Given: a tick with no usable dot (the g went unresolved)
        When: the trail is advanced with no new point
        Then: the old points still age out -- the trail decays to empty rather
              than freezing the last shape on screen forever
        """
        old = {"x": 0.5, "y": 0.5, "t": _TS_MS - int((_TRAIL_SEC + 1) * 1000)}
        assert _view("pushGTrail", [old], None, _TS_MS, _TRAIL_SEC) == []


# =============================================================================
# 4. Wiring + SSOT -- a correct routine nobody calls is worth nothing.
# =============================================================================


class TestImuCardWiring:
    """The shipped markup + tick actually reach the view and the renderer."""

    def test_markup_theLiveImuSurfaceIsNeverVehicleGated(self):
        """
        Given: the shipped dashboard.html
        When: the surface carrying the IMU instrument is located
        Then: it is NOT vehicle-gated and NOT hidden.

        RE-AIMED BY US-508. This test used to locate a standalone
        data-state="imu" card, which US-508 deliberately dissolved into the home
        slot. The invariant it was REALLY guarding is untouched and is what is
        re-asserted here: the IMU is a PI-LOCAL sensor that reads on the bench
        with no car, so its surface must never hide behind a vehicle gate.
        """
        html = _read(_HTML)
        m = re.search(r'<section class="card"[^>]*data-idle-home[^>]*>', html)
        assert m, "no home slot in dashboard.html"
        tag = m.group(0)
        assert "data-vehicle-gated" not in tag
        assert "hidden" not in tag

    def test_theLiveLoopCallsTheImuViewAndRenderer(self):
        """
        Given: the shipped live-poll + home-render bodies
        When: the call sites are read
        Then: the polled state really reaches the view and the renderer. US-494
              was a dependency the entry point never injected -- no test of the
              component could see it, so the CALL SITE is what gets pinned. The
              site MOVED with US-508 (tick branch -> the ~10 Hz live loop); the
              reason to pin it did not.
        """
        js = _read(_JS)
        assert re.search(r'fetchState\(\s*"imu"\s*\)', _fnBody(js, "imuTick"))
        assert "renderHome(" in _fnBody(js, "imuTick")
        home = _fnBody(js, "renderHome")
        assert "homeFace(" in home
        assert "liveCardView(" in home
        assert "renderHomeCard(" in home

    def test_oneHomePaint_resolvesEveryFreshnessVerdictAgainstOneClock(self):
        """
        Given: the home renderer
        When: the face decision and the live view are built
        Then: BOTH read the same `nowMs`.

        RE-AIMED BY US-508, and it matters MORE now, not less. The live feed
        moved to its own faster loop, so a second clock inside one paint could
        let `homeFace` say "live" while `liveCardView` says "stale" -- the slot
        would swap to the live face and then render nothing into it.

        RE-AIMED AGAIN BY US-645, which appended a fourth argument (the OBD
        vehicle speed) AFTER the clock. The previous pattern required `nowMs` to
        be the LAST argument, which was incidental to the claim -- the claim is
        that BOTH calls read the SAME clock, not where it sits in the list. Only
        the position is relaxed; a call that dropped the clock, or reached for a
        second one, still fails here.
        """
        home = _fnBody(_read(_JS), "renderHome")
        assert re.search(r"homeFace\([^)]*\bnowMs\b", home)
        assert re.search(r"liveCardView\([^)]*\bnowMs\b", home)

    def test_theLiveLoopClearsTheTrailWhenTheFeedGoesIdle(self):
        """
        Given: the home renderer
        When: the idle path is read
        Then: the trail is reset. Without this, a feed that drops for a minute
              and returns would splice a minute-old shape onto the new point --
              a trail that never happened, drawn as if it did. US-508 adds the
              grade trend, which carries the identical hazard.
        """
        home = _fnBody(_read(_JS), "renderHome")
        assert "gTrail = []" in home
        assert "gradeTrend = []" in home

    def test_noDataView_namesTheSilentImuInstrument(self):
        """
        Given: an absent states/imu file
        When: the shell picks the whole-card message
        Then: it NAMES the instrument -- "no data" for a motion card must not
              read as "not moving", the same fabrication trap as dtc/light
        """
        nd = _view("noDataView", "imu")
        assert nd is not None
        assert "no data" in nd["reason"]

    def test_imuCss_introducesNoPaletteOfItsOwn(self):
        """
        Given: the shipped stylesheet
        When: the IMU rules are read
        Then: every colour is a var(--token) -- AC-4, tokens.css is the SSOT and
              a bespoke local hex is exactly the drift it prevents
        """
        css = _read(_CSS)
        block = "\n".join(
            ln for ln in css.splitlines() if ".imu-" in ln or ln.strip().startswith("--imu")
        )
        # any literal hex colour on an .imu- rule line is a fork of the palette
        assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", block), block

    def test_theImuSurfaceIsCountedByTheVisibleCardGeometry(self):
        """
        Given: the card list the carousel builds
        When: the surface carrying the IMU instrument is located
        Then: it is a plain `.card` inside `#track`, so US-496's visible-index
              geometry (translateX / dots / swipe) counts it automatically -- a
              card added outside the track would own no page dot.

        RE-AIMED BY US-508: that surface is now the HOME slot. Note it must
        carry the bare `class="card"` -- the pre-US-508 idle card was
        `class="card idle-card"`, and a two-faced slot cannot wear a
        permanently-idle class.
        """
        html = _read(_HTML)
        track = html[html.index('<div id="track">'): html.index("</main>")]
        assert re.search(r'<section class="card"[^>]*data-idle-home', track)
