################################################################################
# File Name: test_carousel_live_home_card.py
# Purpose/Description: US-508 (F-124) tests -- the live/motion instrument is
#   re-issued to the CIO-locked spec and MOVES INTO THE HOME SLOT as one slot
#   with two faces (parked -> idle, driving -> live). Six groups:
#     1. The home-slot swap. ONE slot decides its face; `homeFace` is that one
#        decision. A LIVE + FRESH states/imu shows the instrument and anything
#        else falls back -- never a frozen motion display (AC-2/AC-3).
#        SUPERSEDED IN PART BY US-541 (F-127): "parked wins outright" is GONE.
#        The live IMU instrument is now the PERMANENT home face, so the decision
#        reads the motion feed only and no longer takes system-status at all.
#        The always-on contract itself lives in test_carousel_imu_always_on.py;
#        what stays here is the freshness/absence fallback US-508 built.
#     2. The fallback must not FABRICATE A PARKED STATE. The shipped idle hero
#        reads "STANDBY / engine off - OBD asleep". Rendering that while the car
#        is moving because the IMU feed died would be a confident lie about the
#        vehicle, so the idle FACE carries two dispositions, not one.
#        US-541 makes the PARKED disposition unreachable through the renderer
#        (the reason is now always passed), and US-542 retires the STANDBY hero
#        outright. `idleCardView` is still a live pure function until then, so
#        these pins stay green and stay honest about what they cover.
#     3. The compass TAPE (replaces the built rotating needle). The load-bearing
#        property is DIRECTION: a tape that scrolls the wrong way is a plausible
#        instrument that is exactly backwards, and it wraps across north.
#     4. The GEAR glyph. Gear is Spool's OBD derivation from a SEPARATE producer
#        (Atlas: explicitly NOT states/imu), and no producer exists yet -- so it
#        follows the altitude precedent: typed-NA "--", never a guessed number.
#     5. Amber at 0.6 g (Spool), which is a DIFFERENT fact from the 1.0 g
#        full-scale clamp -- both must survive.
#     6. The ~15-min grade trend: decimated, evicted, and on a FIXED scale (an
#        autoscaled sparkline turns a flat road into a mountain range).
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
# 2026-07-31    | Ralph (Rex)  | Initial -- US-508 live card re-issue + home swap.
# ================================================================================
################################################################################

"""US-508 tests for the live/motion home card and the idle<->live home swap."""

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "specs", "UI", "dist", "dashboard-pi"
)
_HTML = os.path.join(_DIST, "dashboard.html")
_JS = os.path.join(_DIST, "carousel.js")
_CSS = os.path.join(_DIST, "dashboard.css")

_TS = "2026-07-31T12:00:00+00:00"
_TS_MS = int(datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)

# The card's own constants, mirrored so a drift in either breaks a test.
_STALE_SEC = 2.0
_G_AMBER = 0.6  # Spool: the advisory lateral/longitudinal nudge
_G_FULL_SCALE = 1.0  # the outer ring -- a DIFFERENT fact from the amber threshold
_TAPE_SPAN_DEG = 90.0
_TREND_WINDOW_SEC = 900.0  # ~15 min (Iris locked spec)
_TREND_BUCKET_MS = 5000
_IMU_POLL_MS = 100  # Atlas transport ruling: the live card polls at ~10 Hz

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


def _imu(**over: object) -> dict:
    """A live, fully-resolved states/imu payload (specs/architecture.md 10.8.2)."""
    payload = {
        "available": True,
        "ts": _TS,
        "headingDeg": 247.0,
        "gradePct": 3.0,
        "gLat": 0.30,
        "gLon": 0.12,
        "gMag": 0.323,
        "altitude": None,
        "reasons": {"altitude": "no_source"},
    }
    payload.update(over)
    return payload


def _sys(idle: bool) -> dict:
    return {"available": True, "ts": _TS, "idle": idle}


# ---------------------------------------------------------------------------
# 1. The home-slot swap -- ONE slot, two faces (AC-2)
# ---------------------------------------------------------------------------


def test_homeFace_liveImu_showsLiveFace():
    """
    Given: states/imu is fresh + available
    When: the home slot resolves its face
    Then: the home slot IS the live instrument (the US-508 swap)

    US-541 note: the `_sys` fixture no longer reaches this decision at all --
    the vehicle state was dropped from the signature so the face cannot be
    re-coupled to it. The parked-shows-live contract is pinned in
    test_carousel_imu_always_on.py.
    """
    face = _view("homeFace", _imu(), _TS_MS)
    assert face["face"] == "live"


def test_homeFace_staleImu_fallsBackToIdleFace():
    """
    Given: the last IMU write is older than the freshness window
    When: the home slot resolves its face
    Then: it falls back to the idle face -- never a frozen motion display (AC-3)
    """
    stale_ms = _TS_MS + int((_STALE_SEC + 1.0) * 1000)
    face = _view("homeFace", _imu(), stale_ms)
    assert face["face"] == "idle"
    assert "stale" in face["reason"]


def test_homeFace_absentImuFile_fallsBackToIdleFace():
    """
    Given: there is no states/imu file at all (null payload)
    When: the home slot resolves its face
    Then: idle face with an honest reason -- absence is not a motion reading
    """
    face = _view("homeFace", None, _TS_MS)
    assert face["face"] == "idle"
    assert face["reason"]


def test_homeFace_unwiredSensor_fallsBackToIdleFace():
    """
    Given: the bridge writes available:false (the sensor is not wired)
    When: the home slot resolves its face
    Then: idle face carrying the bridge's own reason, not a generic word
    """
    payload = _imu(available=False, reasons={"gLat": "sensor_absent"})
    face = _view("homeFace", payload, _TS_MS)
    assert face["face"] == "idle"
    assert face["reason"] == "sensor not detected"


def test_homeFace_carriesNoParkedVerdictForTheRendererToActOn():
    """
    Given: US-541 removed system-status from the face decision
    When: the face resolves
    Then: there is no `parked` field on it.

    US-508 shipped one so the renderer could suppress the motion reason and show
    the calm STANDBY hero instead. Leaving the field behind would let a renderer
    read `face.parked` -- always falsy now -- and branch on a verdict nothing
    computes: a dead field is how the retired coupling would grow back.
    """
    assert "parked" not in _view("homeFace", _imu(), _TS_MS)


# ---------------------------------------------------------------------------
# 2. The idle FACE must not fabricate a parked state (the honesty trap)
# ---------------------------------------------------------------------------


def test_idleCardView_parked_keepsTheShippedStandbyHero():
    """
    Given: the home slot is idle because the car is genuinely parked
    When: the idle view is assembled with no motion reason
    Then: the shipped STANDBY hero is unchanged (US-481 relocation, not a redesign)
    """
    view = _view("idleCardView", _sys(True), None, None, None)
    assert view["hero"]["title"] == "STANDBY"
    assert view["hero"]["level"] == "neutral"


def test_idleCardView_drivingWithDeadFeed_neverClaimsEngineOff():
    """
    Given: the car is MOVING but the motion feed is down, so the idle face shows
    When: the idle view is assembled with the motion reason
    Then: the hero says the FEED is missing -- it never says "engine off", which
          would be a confident lie about the vehicle built out of a sensor fault
    """
    view = _view("idleCardView", _sys(False), None, None, "sensor not detected")
    assert view["hero"]["title"] != "STANDBY"
    assert "engine off" not in view["hero"]["substate"]
    assert "sensor not detected" in view["hero"]["substate"]


def test_idleCardView_drivingWithDeadFeed_keepsTheRealFacts():
    """
    Given: the motion-absent idle face
    When: the view is assembled
    Then: the three fact tiles are still the real ones -- one dead instrument
          does not blank the readouts that are still true
    """
    view = _view("idleCardView", _sys(False), None, None, "no compass reading")
    assert set(view["facts"]) == {"lastDrive", "battery", "faults"}


def test_idleCardView_footerIsPartOfTheViewNotAHiddenDomLiteral():
    """
    Given: the two idle dispositions need two different footers
    When: the view is assembled either way
    Then: the footer is a VIEW field, so the copy is pinnable rather than buried
          in the renderer where no test can reach it
    """
    parked = _view("idleCardView", _sys(True), None, None, None)
    motionless = _view("idleCardView", _sys(False), None, None, "sensor not detected")
    assert parked["footer"]
    assert motionless["footer"]
    assert parked["footer"] != motionless["footer"]


# ---------------------------------------------------------------------------
# 3. The compass TAPE (replaces the rotating needle)
# ---------------------------------------------------------------------------


def test_compassTape_currentHeadingSitsUnderTheCaret():
    """
    Given: a heading that lands exactly on a tick
    When: the tape is built
    Then: that tick is at offset 0 -- the caret is fixed and the TAPE moves
    """
    tape = _view("compassTape", 90.0, _TAPE_SPAN_DEG)
    under = [t for t in tape["ticks"] if abs(t["offset"]) < 1e-9]
    assert len(under) == 1
    assert under[0]["deg"] == 90.0


def test_compassTape_scrollsTheRightWayForARightTurn():
    """
    Given: a heading of 0 degrees, then the vehicle turns RIGHT to 30 degrees
    When: the tape is rebuilt
    Then: the 45-degree tick moves LEFT (its offset decreases). A tape that
          scrolls the wrong way is a plausible instrument that is exactly
          backwards -- the single most likely defect in this whole card.
    """
    before = _view("compassTape", 0.0, _TAPE_SPAN_DEG)
    after = _view("compassTape", 30.0, _TAPE_SPAN_DEG)

    def offset_of(tape: dict, deg: float) -> float:
        for tick in tape["ticks"]:
            if abs(tick["deg"] - deg) < 1e-9:
                return tick["offset"]
        raise AssertionError(f"no {deg} tick on the tape")

    assert offset_of(after, 45.0) < offset_of(before, 45.0)


def test_compassTape_wrapsAcrossNorth():
    """
    Given: a heading of 350 degrees, so the visible window straddles 0/360
    When: the tape is built
    Then: ticks on BOTH sides of north appear, and none of them is a ~350-degree
          jump away -- a tape that cannot wrap tears itself apart pointing north
    """
    tape = _view("compassTape", 350.0, _TAPE_SPAN_DEG)
    degs = {t["deg"] for t in tape["ticks"]}
    assert 345.0 in degs
    assert 0.0 in degs or 360.0 in degs
    assert all(-1.0 <= t["offset"] <= 1.0 for t in tape["ticks"])


def test_compassTape_labelsTheCardinalsOnly():
    """
    Given: a built tape
    When: the ticks are inspected
    Then: 45-degree multiples carry a rose label and the minor ticks do not --
          a label on every tick is unreadable at 480x320
    """
    tape = _view("compassTape", 0.0, _TAPE_SPAN_DEG)
    labelled = {t["deg"]: t["label"] for t in tape["ticks"] if t["label"]}
    assert labelled.get(0.0) == "N" or labelled.get(360.0) == "N"
    assert labelled.get(45.0) == "NE"
    assert all(deg % 45 == 0 for deg in labelled)


def test_compassTape_absentHeading_hasNoTicksAtAll():
    """
    Given: a dead magnetometer (headingDeg is null)
    When: the tape is built
    Then: it is EMPTY, not frozen at its last bearing. A tape parked under the
          caret reads as a confident heading exactly as a frozen needle did.
    """
    tape = _view("compassTape", None, _TAPE_SPAN_DEG)
    assert tape["ticks"] == []
    assert tape["available"] is False


# ---------------------------------------------------------------------------
# 4. The GEAR glyph -- a separate producer that does not exist yet
# ---------------------------------------------------------------------------


def test_gearView_noProducer_readsDashesNotAGuess():
    """
    Given: no gear producer exists (Atlas: gear is Spool's OBD derivation from a
           SEPARATE producer, explicitly not states/imu)
    When: the glyph is built from a null payload
    Then: it reads "--" with an honest reason -- the altitude precedent exactly,
          never a fabricated gear number
    """
    view = _view("gearView", None)
    assert view["value"] == "--"
    assert view["available"] is False
    assert view["detail"]


def test_gearView_ambiguous_readsDashes():
    """
    Given: a producer that reports an ambiguous gear (Spool: speed < 5 km/h,
           rpm < 900, ratio > 15% off the nearest gear)
    When: the glyph is built
    Then: "--" -- never a wrong number (Spool's rule, quoted in the AC)
    """
    view = _view("gearView", {"available": True, "gear": None, "reason": "ambiguous"})
    assert view["value"] == "--"
    assert view["available"] is False


def test_gearView_rollingNeutral_readsN():
    """
    Given: the producer reports rolling neutral
    When: the glyph is built
    Then: "N" -- a real disposition, distinct from "--" (unknown)
    """
    view = _view("gearView", {"available": True, "gear": "N"})
    assert view["value"] == "N"
    assert view["available"] is True


def test_gearView_realGear_rendersTheNumber():
    """
    Given: the producer reports 3rd gear
    When: the glyph is built
    Then: "3"
    """
    view = _view("gearView", {"available": True, "gear": 3})
    assert view["value"] == "3"
    assert view["available"] is True


def test_gearView_isNeverSourcedFromTheImuPayload():
    """
    Given: a states/imu payload that (wrongly) carried a gear field
    When: the live view is assembled
    Then: the gear glyph still reads "--". Atlas ruled gear OUT of states/imu;
          quietly honouring it here would re-merge two producers into one fact.
    """
    view = _view("liveCardView", _imu(gear=4), None, _TS_MS)
    assert view["gear"]["value"] == "--"


# ---------------------------------------------------------------------------
# 5. Amber at 0.6 g -- distinct from the 1.0 g full-scale clamp
# ---------------------------------------------------------------------------


def test_gLevel_belowThreshold_isNeutral():
    """
    Given: a magnitude below the Spool advisory threshold
    When: the level is resolved
    Then: neutral -- this card is calm, and ordinary driving is not a warning
    """
    assert _view("gLevel", _G_AMBER - 0.01) == "neutral"


def test_gLevel_atThreshold_isAmber():
    """
    Given: exactly 0.6 g
    When: the level is resolved
    Then: amber -- the threshold is inclusive (Spool's stated value is the point
          at which the nudge applies, not the point just past it)
    """
    assert _view("gLevel", _G_AMBER) == "amber"


def test_gLevel_amberEngagesWellBeforeTheFullScaleClamp():
    """
    Given: a magnitude between the amber threshold and the ring's full scale
    When: the level is resolved
    Then: amber. The built card only ever went amber at the 1.0 g CLAMP, which
          made a hard 0.8 g corner look identical to a gentle one (the AC's
          "not just the 1.0 g full-scale clamp").
    """
    assert _G_AMBER < 0.8 < _G_FULL_SCALE
    assert _view("gLevel", 0.8) == "amber"


def test_gLevel_unreadableMagnitude_isNeutralNotAmber():
    """
    Given: no resolvable magnitude
    When: the level is resolved
    Then: neutral -- an absent reading must never paint a warning colour
    """
    assert _view("gLevel", None) == "neutral"


def test_liveCardView_hardCorner_carriesAmberOnTheGTile():
    """
    Given: a live payload at 0.72 g
    When: the live view is assembled
    Then: the G-FORCE tile carries the amber level AND its true magnitude --
          the colour is a nudge, it never replaces the number
    """
    view = _view("liveCardView", _imu(gLat=0.70, gLon=0.17, gMag=0.72), None, _TS_MS)
    assert view["g"]["level"] == "amber"
    assert "0.72" in view["g"]["value"]


def test_liveCardView_clampFlagSurvivesTheAmberRule():
    """
    Given: an over-scale 1.4 g stop
    When: the live view is assembled
    Then: the dot is clamped to the ring AND the tile keeps the true magnitude.
          Amber and clamped are two different facts and both must survive.
    """
    view = _view("liveCardView", _imu(gLat=0.0, gLon=-1.4, gMag=1.4), None, _TS_MS)
    assert view["g"]["dot"]["clamped"] is True
    assert view["g"]["level"] == "amber"
    assert "1.40" in view["g"]["value"]


# ---------------------------------------------------------------------------
# 6. The ~15-min grade trend
# ---------------------------------------------------------------------------


def test_pushGradeTrend_evictsBeyondTheWindow():
    """
    Given: a point older than the 15-minute window
    When: the trend advances
    Then: the stale point is gone -- the sparkline is a MOVING trend, not a log
    """
    old = [{"v": 5.0, "t": _TS_MS - int(_TREND_WINDOW_SEC * 1000) - 1}]
    out = _view("pushGradeTrend", old, 1.0, _TS_MS, _TREND_WINDOW_SEC, _TREND_BUCKET_MS)
    assert len(out) == 1
    assert out[0]["v"] == 1.0


def test_pushGradeTrend_evictsEvenWithNoNewPoint():
    """
    Given: the feed has stopped (no new value) and every point is now old
    When: the trend advances
    Then: it decays to EMPTY rather than freezing its last shape on screen --
          the same rule the g-trail follows, for the same reason
    """
    old = [{"v": 5.0, "t": _TS_MS - int(_TREND_WINDOW_SEC * 1000) - 1}]
    out = _view("pushGradeTrend", old, None, _TS_MS, _TREND_WINDOW_SEC, _TREND_BUCKET_MS)
    assert out == []


def test_pushGradeTrend_decimatesWithinABucket():
    """
    Given: several samples inside one bucket (the card polls at ~10 Hz, so a
           15-minute window is ~9000 raw samples)
    When: they are pushed
    Then: the bucket holds ONE point, latest-wins -- 9000 nodes on a kiosk Pi
          buys nothing a decimated line does not show
    """
    trend: list = []
    for i in range(5):
        trend = _view(
            "pushGradeTrend", trend, float(i), _TS_MS + i * 100,
            _TREND_WINDOW_SEC, _TREND_BUCKET_MS,
        )
    assert len(trend) == 1
    assert trend[0]["v"] == 4.0  # latest-wins inside the bucket


def test_pushGradeTrend_keepsOnePointPerBucket():
    """
    Given: samples spanning several buckets
    When: they are pushed
    Then: one point survives per bucket, in order
    """
    trend: list = []
    for i in range(3):
        trend = _view(
            "pushGradeTrend", trend, float(i), _TS_MS + i * _TREND_BUCKET_MS,
            _TREND_WINDOW_SEC, _TREND_BUCKET_MS,
        )
    assert [p["v"] for p in trend] == [0.0, 1.0, 2.0]


def test_gradeTrendPoints_usesAFixedScaleNotAnAutoscale():
    """
    Given: a nearly flat road (grade wobbling by hundredths of a percent)
    When: the sparkline geometry is built
    Then: the plotted spread stays tiny. An AUTOSCALED sparkline would stretch
          that wobble to full height and render a flat road as a mountain range
          -- a fabricated terrain built out of real noise.
    """
    flat = [{"v": 0.01 * i, "t": _TS_MS + i * _TREND_BUCKET_MS} for i in range(4)]
    pts = _view("gradeTrendPoints", flat)
    ys = [p["y"] for p in pts]
    assert max(ys) - min(ys) < 0.05


def test_gradeTrendPoints_clampsBeyondTheDisplayScale():
    """
    Given: a grade beyond the display scale
    When: the geometry is built
    Then: it clamps into the box instead of drawing off the card
    """
    steep = [{"v": 60.0, "t": _TS_MS}, {"v": -60.0, "t": _TS_MS + _TREND_BUCKET_MS}]
    pts = _view("gradeTrendPoints", steep)
    assert all(-1.0 <= p["y"] <= 1.0 for p in pts)


# ---------------------------------------------------------------------------
# 7. ALTITUDE -- the readout with no producer behind it
#
# The AC asks for a PROMINENT altitude and Atlas ruled it typed-NULL with
# reason "no_source": there is no baro and no GPS on this Pi today. That makes
# it the one tile on this card whose ONLY correct rendering is an absence, and
# absence is the easiest thing to "fix" by accident -- a zeroed altitude reads
# as sea level, which is a confident lie rather than a visible gap. The card's
# own source comment names that hazard; nothing enforced it until here.
# ---------------------------------------------------------------------------


def test_liveCardView_altitude_isTypedNaCarryingTheHonestReason():
    """
    Given: a live payload whose altitude is null with reason "no_source"
    When: the live view is assembled
    Then: the tile is typed-NA and SAYS WHY. "NA" alone is a shrug; the reason
          is what tells an operator the instrument is unbuilt rather than broken.
    """
    view = _view("liveCardView", _imu(), None, _TS_MS)
    assert view["altitude"]["label"] == "ALTITUDE"
    assert view["altitude"]["value"] == "NA"
    assert view["altitude"]["level"] == "unavailable"
    assert view["altitude"]["detail"] == "no source"


def test_liveCardView_altitude_neverRendersANumber():
    """
    Given: the live view
    When: the altitude tile's value is read
    Then: it carries NO DIGIT AT ALL.

          This is the pin that matters. The failure it forbids is not a crash --
          it is a plausible number. A zeroed altitude renders as sea level and a
          defaulted one renders as somewhere; either reads as a working
          instrument to the person driving the car. Asserting "not a number" is
          strictly stronger than asserting == "NA", because it also catches the
          "helpful" 0 ft / --- ft / 0 m variants of the same mistake.
    """
    view = _view("liveCardView", _imu(), None, _TS_MS)
    assert not re.search(r"\d", view["altitude"]["value"]), view["altitude"]


def test_liveCardView_altitude_survivesEvenThoughItIsAlwaysAbsent():
    """
    Given: a field that can never resolve on today's hardware
    When: the live view is assembled
    Then: the tile is STILL THERE.

          Atlas ruled the field stays "for zero-rework later", and the AC calls
          the altitude prominent. The tempting simplification is to drop a tile
          that is unconditionally NA -- and then the day a BMP280 lands, the
          readout has nowhere to appear and the card needs re-laying-out rather
          than re-wiring. An honest gap is a feature here, not dead weight.
    """
    view = _view("liveCardView", _imu(), None, _TS_MS)
    assert "altitude" in view


def test_liveCardView_deadAltitude_neverBlocksTheLiveInstrument():
    """
    Given: the permanently-absent altitude sitting beside three LIVE readings
    When: the live view is assembled
    Then: heading, grade and g all still resolve.

          Same independence property US-507 proved for the Health card's
          sections, one story later and on a different surface: one unavailable
          source must never blank the working instruments beside it. Here it
          would be permanent, because this source is never coming back.
    """
    view = _view("liveCardView", _imu(), None, _TS_MS)
    assert view["altitude"]["level"] == "unavailable"
    for field in ("heading", "grade", "g"):
        assert view[field]["level"] != "unavailable", field


# ---------------------------------------------------------------------------
# 8. Wiring + markup -- a correct routine nobody calls is worth nothing
# ---------------------------------------------------------------------------


def _strip_html_comments(src: str) -> str:
    """Markup only. THIRD occurrence of the lesson US-507 wrote down: a pin that
    greps an identifier fires on the comment that DOCUMENTS it -- and this file's
    markup is heavily commented BY DESIGN, so the two impulses will keep pulling
    against each other. Strip the prose, then count the markup."""
    return re.sub(r"<!--.*?-->", "", src, flags=re.DOTALL)


def test_html_hasExactlyOneHomeSlot():
    """
    Given: the shipped dashboard markup
    When: the home slot is counted
    Then: there is exactly ONE data-idle-home section -- "one slot, two faces"
          is meaningless if two slots claim to be home
    """
    html = _strip_html_comments(_read(_HTML))
    assert html.count("data-idle-home") == 1


def test_html_standaloneMotionCardIsGone():
    """
    Given: US-508 absorbs the Motion card into the home slot
    When: the markup is scanned
    Then: no section declares data-state="imu". A separate always-present motion
          card beside a live home slot would poll and paint the same feed twice.
    """
    html = _strip_html_comments(_read(_HTML))
    assert 'data-state="imu"' not in html


def test_htmlStripper_keepsMarkupAndDropsProse():
    """
    Given: the comment stripper the two markup pins above depend on
    When: it runs over the shipped HTML
    Then: real markup survives. Over-stripping is the dangerous direction: it
          deletes the very text an absence assertion hunts for, so the pin
          passes VACUOUSLY (US-507's lesson, applied to the HTML side).
    """
    stripped = _strip_html_comments(_read(_HTML))
    assert 'id="home-card"' in stripped
    assert 'data-state="ltft-trend"' in stripped
    assert "<!--" not in stripped
    assert "US-482 letterbox scaling" not in stripped


def test_html_landsExactlyOneHomeSlot():
    """
    Given: the CIO-locked "one slot, two faces" home design
    When: the card sections are scanned
    Then: exactly ONE `data-idle-home` slot, and no standalone Motion card

    NARROWED BY US-540-b, which is what this test was always about. It used to
    assert a card COUNT of four, which conflated two different facts: US-508's
    home absorption (this story's subject, and permanent) and the card set of
    the day (which US-540-b just moved to six, and which a later story may move
    again). The count now lives with the set it describes, in
    tests/ui/test_carousel_card_set.py; what stays here is the invariant --
    the live instrument is a FACE of the home slot, never a screen of its own,
    so it can never be polled and painted twice.
    """
    # Comment-stripped, like the two markup pins above: the home slot's own
    # comment block NAMES `data-idle-home` while explaining it, so a raw count
    # reads 2 and fails on prose rather than on markup.
    html = _strip_html_comments(_read(_HTML))
    assert len(re.findall(r"data-idle-home", html)) == 1
    assert 'aria-label="Motion"' not in html


def test_js_pollsTheLiveFeedAtAboutTenHertz():
    """
    Given: Atlas's transport ruling (the live card polls states/imu at ~10 Hz off
           the existing states_http_server -- a compass tape and a g-trail will
           not animate at the 4 Hz card poll)
    When: the shipped JS is read
    Then: a dedicated ~100 ms IMU poll exists and the shared card tick is
          UNCHANGED -- raising the whole tick would re-poll every other state
          file 2.5x for nothing
    """
    js = _read(_JS)
    assert re.search(r"IMU_POLL_MS\s*=\s*100\b", js)
    assert re.search(r"POLL_MS\s*=\s*250\b", js)


def test_js_theTickActuallyRendersTheHomeSlot():
    """
    Given: the poll closure
    When: the shipped JS is read
    Then: the face resolver and the home renderer are really called -- US-494's
          lesson (a dependency the entry point never injected cost a whole story)
    """
    js = _strip_js_comments(_read(_JS))
    assert "homeFace(" in js
    assert "renderHomeCard(" in js
    assert "liveCardView(" in js


def test_js_deadStandaloneMotionBranchIsDeletedNotStranded():
    """
    Given: the Motion card no longer exists, so its tick branch can never run
    When: the shipped JS is read
    Then: the branch is GONE. A branch no card can reach is not harmless --
          nothing executes it, so nothing proves it still resolves (US-500).
    """
    js = _strip_js_comments(_read(_JS))
    assert 'name === "imu"' not in js
    assert "renderImuCard" not in js


def test_js_rotatingNeedleIsGoneNotJustUnused():
    """
    Given: the CIO-locked spec froze the compass TAPE and the build shipped a
           rotating needle instead
    When: the shipped JS is read
    Then: the needle builder is removed. Leaving it beside the tape is a second
          heading instrument that can disagree with the first.
    """
    js = _strip_js_comments(_read(_JS))
    assert "buildCompass" not in js
    assert "imu-needle" not in js


def test_js_altitudeIsActuallyPaintedBesideTheGrade():
    """
    Given: the AC asks for grade % AND a PROMINENT altitude
    When: the home renderer is read
    Then: the altitude tile is appended into the SAME box as the grade.

          A view key nobody paints is not a readout -- and this is the one tile
          most likely to be quietly dropped at the DOM layer, because it is
          unconditionally NA and looks like clutter to anyone tidying the
          renderer. Pinning the value (section 7) proves it is computed
          honestly; only this proves it reaches the glass.
    """
    js = _strip_js_comments(_read(_JS))
    grade = re.search(r"appendTile\(\s*gradeTileBox\s*,\s*view\.grade\s*\)", js)
    alt = re.search(r"appendTile\(\s*gradeTileBox\s*,\s*view\.altitude\s*\)", js)
    assert grade, "the grade tile is not painted into the grade box"
    assert alt, "the altitude tile is computed but never painted"
    assert grade.start() < alt.start(), "altitude must sit WITH the grade, not trail it"


def test_js_gearIsNeverFetchedFromANonexistentStateFile():
    """
    Given: no gear producer exists yet
    When: the shipped JS is read
    Then: nothing polls a `gear` state. Fetching a file that is not written would
          be a 404 ten times a second, and a retry loop is not a data source.
    """
    js = _strip_js_comments(_read(_JS))
    assert 'fetchState("gear")' not in js


def test_css_liveFaceUsesTokensOnly():
    """
    Given: the new live-face chrome (tape, caret, gear glyph, trend)
    When: the stylesheet is scanned for the new selectors
    Then: no raw colour literal -- the live card forks no palette (tokens.css is
          the SSOT; a bespoke local colour is exactly the drift it prevents)
    """
    css = _read(_CSS)
    block = "\n".join(
        line for line in css.splitlines()
        if re.search(r"\.imu-(tape|caret|gear|trend)|\.live-", line)
    )
    assert block, "the live-face selectors are missing from the stylesheet"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", block)


def test_css_faceIsDrivenByTheDataAttributeTheJsSets():
    """
    Given: the home slot swaps faces
    When: the stylesheet is read
    Then: it selects on data-face. The JS and the CSS must agree on ONE switch,
          or a face can be logically live and visually idle (the US-495 class of
          defect: correct JS defeated by a stylesheet the JS cannot see).
    """
    css = _read(_CSS)
    js = _read(_JS)
    assert 'data-face="idle"' in css
    assert 'data-face' in js


# ---------------------------------------------------------------------------
# Comment-stripper (US-507): a pin that greps a removed identifier fires on the
# comment that DOCUMENTS the removal. Strip comments, then grep -- and the
# stripper is string-aware, because carousel.js contains the SVG namespace URL
# ("http://www.w3.org/2000/svg"), whose "//" a naive strip would eat.
# ---------------------------------------------------------------------------


def _strip_js_comments(src: str) -> str:
    out: list[str] = []
    i, n = 0, len(src)
    quote: str | None = None
    while i < n:
        ch = src[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def test_stripper_keepsCodeAndTheSvgNamespace():
    """
    Given: the stripper the absence assertions above depend on
    When: it runs over the shipped JS
    Then: real code and the SVG namespace URL survive. Over-stripping is the
          DANGEROUS direction: it deletes the very text an absence assertion
          hunts for, so the pin passes VACUOUSLY.
    """
    stripped = _strip_js_comments(_read(_JS))
    assert "http://www.w3.org/2000/svg" in stripped
    assert "function imuView" in stripped
    assert "function compassTape" in stripped


def test_stripper_removesProse():
    """
    Given: a line comment and a block comment
    When: the stripper runs
    Then: both are gone
    """
    src = 'var a = 1; // buildCompass\n/* renderImuCard */\nvar b = "buildCompass";'
    stripped = _strip_js_comments(src)
    assert stripped.count("buildCompass") == 1
    assert "renderImuCard" not in stripped
