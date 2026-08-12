################################################################################
# File Name: test_carousel_imu_always_on.py
# Purpose/Description: US-541 (F-127) tests -- Atlas's three UI change requests.
#   (1) IMU-ALWAYS-ON. The live IMU instrument becomes the PERMANENT home face.
#       US-508 let `parked` win outright, so the one instrument that is Pi-local
#       and always-live was hidden exactly when the operator is sitting still
#       looking at it. The face decision now reads the MOTION FEED ONLY -- the
#       idle face survives solely as the honest fallback for a dead feed, and it
#       always names the reason (US-508 suppressed the reason when parked; under
#       the new rule "parked" is no longer why the fallback ever fires).
#   (2) The carousel order (Home . Alerts . System Status . ...) -- landed with
#       the US-540-b 6-card re-lay; this story VERIFIES it rather than re-doing it.
#   (3) auto-rotate OFF. Verified in two halves on purpose: config.json's
#       DECLARATION (true, green) and the consumer MECHANISM (broken -- the
#       resolver discards 0; see the xfail below and BL-031).
#   The parked live face is where the honest-availability pattern stops being
#   theoretical: OBD-dependent bits (gear) and unsourced ones (altitude) render
#   typed-NA/greyed, while a TRUE 0.0 g renders as a measured zero. Absence and
#   measured-zero looking alike is the one defect that would make US-542's
#   idle-face retirement dishonest, so both directions are pinned.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-11    | Ralph (Rex)  | Initial -- US-541 IMU-always-on + order + rotate.
# ================================================================================
################################################################################

"""US-541 tests: the live IMU instrument is the permanent home face."""

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_DIST = os.path.join(_ROOT, "specs", "UI", "dist", "dashboard-pi")
_HTML = os.path.join(_DIST, "dashboard.html")
_JS = os.path.join(_DIST, "carousel.js")
_CONFIG = os.path.join(_ROOT, "config.json")

_TS = "2026-08-11T12:00:00+00:00"
_TS_MS = int(datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)
_STALE_SEC = 2.0  # the card's own IMU_STALE_SEC, mirrored so drift breaks a test

# US-536 disposition B (CIO): auto-rotate OFF is the durable freeze fix.
_AUTO_ROTATE_OFF = 0

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


def _parkedImu() -> dict:
    """Parked and honest: the compass still reads, and the g is a TRUE zero.

    This is the payload US-542's retirement argument rests on -- parked, the IMU
    is CORRECT, not unavailable. It must render as an instrument, not as a gap.
    """
    return _imu(gLat=0.0, gLon=0.0, gMag=0.0, gradePct=0.0)


def _fnBody(js: str, name: str) -> str:
    """One `function <name>(` up to the next declaration at the SAME indent.

    Indent-aware because `renderHome` is nested six spaces deep inside the
    browser-only block; a fixed two-space probe would swallow the rest of the
    file and make every absence assertion below vacuous.
    """
    start = js.index(f"function {name}(")
    indent = js[js.rfind("\n", 0, start) + 1 : start]
    nxt = js.find("\n" + indent + "function ", start + 1)
    return js[start:] if nxt == -1 else js[start:nxt]


def _codeOnly(src: str) -> str:
    """Drop comment lines so an absence assertion cannot fire on the prose that
    DOCUMENTS the removal (the US-507 lesson). Line-based, not string-aware --
    adequate here because every body it is used on is comment-and-code only,
    and `test_codeOnly_stillSeesRealCode` is the negative control that proves
    it has not eaten the text the pins hunt for."""
    keep = []
    for line in src.splitlines():
        bare = line.strip()
        if bare.startswith("//") or bare.startswith("*") or bare.startswith("/*"):
            continue
        keep.append(line)
    return "\n".join(keep)


# ---------------------------------------------------------------------------
# 1. IMU-ALWAYS-ON: the face decision reads the motion feed, nothing else (AC-1)
# ---------------------------------------------------------------------------


def test_homeFace_parkedWithLiveImu_showsTheLiveInstrument():
    """
    Given: the car is parked and states/imu is live + fresh
    When: the home slot resolves its face
    Then: the LIVE instrument shows.

          This inverts US-508 deliberately. The IMU is Pi-local and always-live,
          so parked is precisely when its readings are both true and worth
          looking at; hiding it behind a STANDBY hero spent the one always-on
          instrument on the one state where nothing else is readable.
    """
    face = _view("homeFace", _parkedImu(), _TS_MS)
    assert face["face"] == "live"


def test_homeFace_takesTheMotionFeedAndAClockAndNothingElse():
    """
    Given: the always-on rule
    When: the shipped declaration is read
    Then: `homeFace` has exactly the motion payload and the clock in its
          signature.

          The parameter list is the guard. A function that cannot SEE
          system-status cannot re-couple the home face to the vehicle state --
          a later edit would have to widen the signature first, which is a
          visible act rather than a one-line condition slipped into the body.
    """
    js = _read(_JS)
    sig = re.search(r"function homeFace\(([^)]*)\)", js)
    assert sig, "homeFace is gone"
    params = [p.strip() for p in sig.group(1).split(",") if p.strip()]
    assert len(params) == 2, f"homeFace should take (imuData, nowMs), got {params}"
    assert "now" in params[1].lower()


def test_homeFace_neverConsultsTheParkedSignal():
    """
    Given: `carouselIdle` is still the parked SSOT for the auto-rotate pause
    When: the home-face decision is read
    Then: it does not call it. Two consumers of one signal is fine; what US-541
          removes is this ONE consumer, and a grep of the body is what proves
          the removal rather than the signature alone (a stale global would be
          just as coupling as a parameter).
    """
    body = _codeOnly(_fnBody(_read(_JS), "homeFace"))
    assert "carouselIdle" not in body
    assert "imuView(" in body, "negative control: the pin can still see real code"


@pytest.mark.parametrize(
    ("payload", "expect"),
    [
        (None, "no motion feed"),
        ({"available": False, "ts": _TS, "reasons": {"gLat": "sensor_absent"}},
         "sensor not detected"),
    ],
)
def test_homeFace_deadFeedStillFallsBackWithAReason(payload, expect):
    """
    Given: no states/imu file at all, or a bridge reporting an unwired sensor
    When: the face resolves
    Then: the idle face, carrying the honest reason.

          ALWAYS-ON is about the parked state, not about pretending a dead
          sensor is alive. The fallback is the whole reason the idle face
          survives US-541 at all (US-542 retires only its STANDBY disposition).
    """
    face = _view("homeFace", payload, _TS_MS)
    assert face["face"] == "idle"
    assert face["reason"] == expect


def test_homeFace_staleFeedFallsBackEvenThoughTheCarIsParked():
    """
    Given: a parked car whose last IMU write is older than the freshness window
    When: the face resolves
    Then: still the idle fallback.

          The subtle regression this catches: "parked no longer forces idle"
          must not become "parked no longer matters, so paint whatever was last
          read". A stale reading on a parked car is exactly the frozen
          instrument AC-3 has forbidden since US-497.
    """
    stale_ms = _TS_MS + int((_STALE_SEC + 1.0) * 1000)
    face = _view("homeFace", _parkedImu(), stale_ms)
    assert face["face"] == "idle"
    assert "stale" in face["reason"]


def test_renderHome_alwaysNamesTheDeadInstrument():
    """
    Given: the idle face now fires ONLY because the motion feed died
    When: the home renderer is read
    Then: it passes the reason through unconditionally.

          US-508 suppressed the reason when parked (`face.parked ? null : ...`)
          so the calm STANDBY hero could show. With parked no longer a route to
          the idle face, that ternary would silently pick the STANDBY hero for
          a DEAD SENSOR -- the exact "engine off is a lie built from a sensor
          fault" defect US-508's own tests were written to prevent, arriving
          through the back door of a condition that is now always false.
    """
    body = _codeOnly(_fnBody(_read(_JS), "renderHome"))
    assert "idleCardView(" in body, "negative control: the pin can see real code"
    assert "parked" not in body


def test_codeOnly_stillSeesRealCode():
    """
    Given: the comment stripper the absence pins above depend on
    When: it runs over the shipped JS
    Then: real code survives. Over-stripping is the dangerous direction -- it
          deletes the very text an absence assertion hunts for, so the pin
          passes VACUOUSLY over a file that still carries the defect.
    """
    stripped = _codeOnly(_read(_JS))
    assert "function homeFace(" in stripped
    assert "function carouselIdle(" in stripped
    assert "// US-541" not in stripped


# ---------------------------------------------------------------------------
# 2. The parked live face must be an instrument, not a fabrication (AC-1)
# ---------------------------------------------------------------------------


def test_liveCardView_parked_gearIsTypedNaAndGreyed():
    """
    Given: the parked live face, and no gear producer anywhere (Atlas: gear is
           Spool's OBD derivation from a SEPARATE producer that does not exist)
    When: the live view is assembled
    Then: gear is the typed-NA glyph at the `unavailable` level -- never a
          number, never "N".

          Newly load-bearing: before US-541 the live face never rendered while
          parked, so an OBD-dependent tile sitting on a screen with no engine
          running was not a state the card could reach. It is now the DEFAULT
          state on a bench, which is where the CIO reads the panel most days.
    """
    view = _view("liveCardView", _parkedImu(), None, _TS_MS)
    assert view["gear"]["available"] is False
    assert view["gear"]["level"] == "unavailable"
    assert view["gear"]["value"] == "--"
    assert view["gear"]["detail"], "typed-NA without a reason is a bare shrug"


def test_liveCardView_parked_altitudeIsTypedNaAndGreyed():
    """
    Given: the ICM-20948 has no barometer and no GPS is wired
    When: the parked live view is assembled
    Then: altitude is typed-NA at the `unavailable` level. A zeroed altitude
          renders as sea level, which is a confident lie the moment the car is
          parked on a hill -- and the grade tile beside it would disagree.
    """
    view = _view("liveCardView", _parkedImu(), None, _TS_MS)
    assert view["altitude"]["value"] == "NA"
    assert view["altitude"]["level"] == "unavailable"


def test_liveCardView_parked_trueZeroGIsAMeasuredZeroNotAnAbsence():
    """
    Given: a parked car -- the accelerometer honestly reads 0.0 g
    When: the live view is assembled
    Then: the g tile is AVAILABLE with a real dot at the origin.

          This is the fact US-542's idle-face retirement is built on: parked,
          the IMU is correct, not unavailable. If a true zero rendered as a gap
          the always-on face would show nothing on a parked car and the
          retirement would have removed a real readout for an empty one.
    """
    view = _view("liveCardView", _parkedImu(), None, _TS_MS)
    assert view["g"]["available"] is True
    assert view["g"]["dot"] is not None


def test_liveCardView_absentGIsNotDrawnAtTheOrigin():
    """
    Given: a live payload whose g axes are missing entirely
    When: the live view is assembled
    Then: unavailable, with NO dot.

          The negative control for the test above: without it, "0.0 g renders a
          dot at the origin" would also be satisfied by a card that draws an
          origin dot for a DEAD accelerometer -- absence and measured-zero
          painted identically, which is the zeroed instrument AC-3 forbids.
    """
    payload = _parkedImu()
    payload["gLat"] = None
    payload["gLon"] = None
    payload["gMag"] = None
    view = _view("liveCardView", payload, None, _TS_MS)
    assert view["g"]["available"] is False
    assert view["g"]["dot"] is None


def test_liveCardView_parked_headingIsStillARealBearing():
    """
    Given: the parked live face
    When: the view is assembled
    Then: the compass reads a real magnetic bearing and the tape is built from
          it. Heading is the readout that makes the always-on face worth the
          screen while the engine is off.
    """
    view = _view("liveCardView", _parkedImu(), None, _TS_MS)
    assert view["heading"]["available"] is True
    assert view["tape"]["available"] is True


# ---------------------------------------------------------------------------
# 3. AC-2 -- the carousel order (landed with US-540-b; VERIFIED here)
# ---------------------------------------------------------------------------


def test_html_alertsIsTheSecondCard():
    """
    Given: US-541 AC-2 asks for Home . Alerts . System Status . ...
    When: the shipped markup is read in order
    Then: the first two slots are Home and Alerts.

          Landed with the US-540-b re-lay (the 6-card set had to be authored in
          one pass), so this story verifies rather than re-does it. Asserted as
          an ORDERED prefix: a set-or-count assertion goes green on a carousel
          that opens on Light.
    """
    cards = re.findall(r'<section class="card"[^>]*aria-label="([^"]+)"',
                       _read(_HTML), re.S)
    assert cards[:3] == ["Home", "Alerts", "System Status"]


# ---------------------------------------------------------------------------
# 4. AC-3 -- auto-rotate OFF. The DECLARATION is true; the MECHANISM is not.
# ---------------------------------------------------------------------------


def test_configJson_declaresAutoRotateOff():
    """
    Given: US-536 disposition B -- the CIO rejected --disable-gpu BECAUSE
           auto-rotate-off was the durable freeze fix
    When: the shipped config is read
    Then: pi.display.carousel.autoRotateS is 0.

          Half of AC-3, and only half: this pins what the config file SAYS.
          A test asserting a declaration cannot witness the consumer -- see the
          xfail below, which is the same fact asserted where it actually acts.
    """
    cfg = json.loads(_read(_CONFIG))
    carousel = cfg["pi"]["display"]["carousel"]
    assert carousel["autoRotateS"] == _AUTO_ROTATE_OFF


def test_shouldAutoAdvance_aZeroPeriodNeverAdvances():
    """
    Given: the auto-advance predicate
    When: it is driven with the OFF value and a long-elapsed clock
    Then: it refuses to advance.

          The downstream half is already correct, which is what makes the
          resolver defect a one-line fix rather than a redesign: `0` already
          means OFF everywhere it is consumed. Only the resolver disagrees.
    """
    assert _view("shouldAutoAdvance", False, 60_000, _AUTO_ROTATE_OFF) is False
    assert _view("rotateProgress", 60_000, _AUTO_ROTATE_OFF) == 0


def test_resolveCarouselConfig_honoursTheShippedOffValue():
    """
    Given: the dashboard is served the config's `autoRotateS: 0`
    When: the injected config is resolved against the grounded defaults
    Then: the resolved period is 0 -- auto-rotate is OFF on the panel.

          THE MECHANISM half of AC-3. This shipped as a strict xfail while the
          defect was open (BL-031 / I-us536): `0` meant "broken, ignore me" to
          the US-506 resolver and "off, obey me" to US-536 and to the US-533
          operator toggle, which writes exactly the value the resolver dropped.
          Every layer reported success; only the consumer quietly disagreed.

          US-541-a (Atlas Option-1, CIO-ratified 2026-08-11) relaxed the guard
          FOR THIS KEY ONLY, so the assertion below now stands on its own and
          the marker is gone -- which is the whole reason it was written as the
          DESIRED behaviour rather than pinned to the broken value. The
          per-key-ness of that relaxation is pinned next door, in
          test_carousel_nav_model.py's resolver section.
    """
    resolved = _view("resolveCarouselConfig", {"autoRotateS": _AUTO_ROTATE_OFF})
    assert resolved["autoRotateS"] == _AUTO_ROTATE_OFF
