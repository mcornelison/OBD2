################################################################################
# File Name: test_carousel_nav_model.py
# Purpose/Description: US-506 (F-124) tests -- the carousel NAVIGATION MODEL:
#   wrap-around that skips gated cards, hands-off auto-rotate with a calm
#   time-to-next progress bar, and a VELOCITY-based swipe that distinguishes a
#   deliberate settle from a flick.
#
#   Three behaviours, one surface:
#     1. WRAP (AC-12). The shipped contract clamped at both ends. It now wraps,
#        and the wrap must traverse only VISIBLE cards -- a wrap that lands on a
#        vehicle-gated card paints a blank frame the operator cannot swipe out
#        of, which is strictly worse than the clamp it replaced.
#     2. AUTO-ROTATE (AC-13). Visible cards cycle every autoRotateS. The bar
#        renders time-to-next as a 0..1 fraction, never a countdown number.
#     3. VELOCITY (AC-14). The shipped swipe was DISTANCE-ONLY, so it could not
#        tell "I flicked past this" from "I settled here". Now: fast flick ->
#        advance + RESUME; slow settle -> advance one + PAUSE. A pause always
#        expires after resumeIdleS so the carousel can never freeze forever.
#
#   Every threshold is a config parameter (pi.display.carousel.*) resolved over
#   grounded defaults, reached through the SAME serve-time injection seam
#   US-483-b built for the auto-dim curve -- so retuning the feel is a config
#   change, not a code change.
#
#   Pure logic runs through the shared node probe (tests/ui/carousel_probe.js);
#   the browser-only DOM wiring is pinned by reading the shipped artifacts,
#   since a correct routine the tick never calls is worth nothing (US-494/495).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-31    | Ralph (Rex)  | Initial -- US-506 wrap + auto-rotate + velocity.
# ================================================================================
################################################################################

"""US-506 tests for the carousel navigation model (wrap/auto-rotate/velocity)."""

import json
import os
import shutil
import subprocess

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "specs", "UI", "dist", "dashboard-pi"
)
_HTML = os.path.join(_DIST, "dashboard.html")
_JS = os.path.join(_DIST, "carousel.js")
_CSS = os.path.join(_DIST, "dashboard.css")
_CONFIG = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")

# The grounded defaults (config.json pi.display.carousel -- mirrored by
# CAROUSEL_DEFAULTS in carousel.js). Named here so a test that changes meaning
# when a threshold is retuned fails on the VALUE, not silently on the feel.
_AUTO_ROTATE_S = 8
_RESUME_IDLE_S = 45
_SWIPE_MIN_PX = 40
_FAST_V_PX_PER_MS = 0.6
_FAST_TRAVEL_FRAC = 0.55

# The design-box card width the travel fraction is measured against (STAGE_W).
_CARD_W = 480

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


def _fnBody(js: str, name: str) -> str:
    """The source text of one `function <name>(` up to the next top-level one."""
    start = js.index("function " + name + "(")
    nxt = js.find("\n    function ", start + 1)
    nxt2 = js.find("\n      function ", start + 1)
    ends = [e for e in (nxt, nxt2) if e != -1]
    return js[start : min(ends)] if ends else js[start:]


def _gesture(dx: float, dtMs: float, *, dy: float = 0, width: float = _CARD_W) -> dict:
    """One pointer-up gesture through the velocity model (default config)."""
    return _view("swipeGesture", dx, dy, dtMs, width, None)


# ---------------------------------------------------------------------------
# AC-12 -- WRAP, traversing only visible cards.
# ---------------------------------------------------------------------------


def test_nextVisibleIndex_wrapsForwardPastTheLastCard():
    """Swiping past the last card lands on the FIRST -- the clamp is gone."""
    assert _view("nextVisibleIndex", 2, 1, [False, False, False]) == 0


def test_nextVisibleIndex_wrapsBackwardPastTheFirstCard():
    """And symmetrically: back from the first card lands on the LAST."""
    assert _view("nextVisibleIndex", 0, -1, [False, False, False]) == 2


def test_nextVisibleIndex_wrapSkipsAGatedCard():
    """The load-bearing half. A wrap that lands on a vehicle-gated card paints a
    blank frame the operator cannot swipe out of -- strictly worse than the
    clamp it replaces. Forward from the last VISIBLE card must skip the trailing
    hidden one and land on the first visible."""
    assert _view("nextVisibleIndex", 1, 1, [False, False, True]) == 0
    assert _view("nextVisibleIndex", 1, -1, [True, False, False]) == 2


def test_nextVisibleIndex_stillStepsOverAHiddenCardMidRow():
    """The pre-existing skip behaviour is preserved by the wrap rewrite."""
    assert _view("nextVisibleIndex", 0, 1, [False, True, False]) == 2
    assert _view("nextVisibleIndex", 2, -1, [False, True, False]) == 0


def test_nextVisibleIndex_oneVisibleCard_staysPut():
    """A single visible card has nowhere to wrap TO. It must terminate on the
    current index -- a wrap loop with no visible target is the one way this
    rewrite could hang the kiosk."""
    assert _view("nextVisibleIndex", 1, 1, [True, False, True]) == 1
    assert _view("nextVisibleIndex", 1, -1, [True, False, True]) == 1


def test_nextVisibleIndex_everyCardHidden_staysPut():
    """Degenerate (nothing visible at all) -> hold, never spin."""
    assert _view("nextVisibleIndex", 0, 1, [True, True]) == 0


def test_nextVisibleIndex_zeroDirection_staysPut():
    """A sub-threshold gesture (dir 0) must not move the carousel."""
    assert _view("nextVisibleIndex", 1, 0, [False, False, False]) == 1


# ---------------------------------------------------------------------------
# AC-13 -- auto-rotate cadence + the calm time-to-next bar.
# ---------------------------------------------------------------------------


def test_shouldAutoAdvance_firesAtTheConfiguredInterval():
    """Visible cards auto-cycle every autoRotateS while unpaused."""
    assert _view("shouldAutoAdvance", False, _AUTO_ROTATE_S * 1000, _AUTO_ROTATE_S) is True


def test_shouldAutoAdvance_holdsBeforeTheInterval():
    assert _view("shouldAutoAdvance", False, 7999, _AUTO_ROTATE_S) is False


def test_shouldAutoAdvance_pausedNeverAdvances():
    """The whole point of swipe-to-pause: a paused carousel does not move under
    the operator while they are reading it."""
    assert _view("shouldAutoAdvance", True, 999999, _AUTO_ROTATE_S) is False


def test_shouldAutoAdvance_nonPositiveIntervalDisablesRotation():
    """A misconfigured interval must DISABLE auto-rotate, never spin the
    carousel every tick -- the failure mode that would make the panel unusable
    and look like a hardware fault."""
    assert _view("shouldAutoAdvance", False, 999999, 0) is False
    assert _view("shouldAutoAdvance", False, 999999, -5) is False


def test_rotateProgress_isTheFractionOfTimeElapsed():
    """The bar renders time-to-next as 0..1 (no countdown number -- AC-13)."""
    assert _view("rotateProgress", 0, _AUTO_ROTATE_S) == 0
    assert _view("rotateProgress", 4000, _AUTO_ROTATE_S) == pytest.approx(0.5)


def test_rotateProgress_clampsAtOne():
    """A late tick (the tmpfs poll is 250 ms, not a real-time clock) must not
    overfill the bar past its track."""
    assert _view("rotateProgress", 99999, _AUTO_ROTATE_S) == 1


def test_rotateProgress_nonPositiveIntervalReadsEmpty():
    """Auto-rotate disabled -> an empty bar, never a full one implying an
    imminent advance that will never come."""
    assert _view("rotateProgress", 4000, 0) == 0


# ---------------------------------------------------------------------------
# AC-14 -- the velocity model. The shipped swipe was DISTANCE-ONLY.
# ---------------------------------------------------------------------------


def test_swipeGesture_belowTheDistanceThresholdIsATap():
    """Distance >= swipeMinPx is still required to count as a swipe AT ALL --
    the velocity model adds a dimension, it does not replace the deadzone. A
    5 px twitch in 2 ms is 2.5 px/ms and must NOT read as a flick."""
    assert _gesture(-5, 2)["dir"] == 0
    assert _gesture(-39, 100)["dir"] == 0


def test_swipeGesture_verticalGestureIsIgnored():
    """A vertical drag scrolls the card body (touch-action: pan-y); it must
    never also page the carousel."""
    assert _gesture(-50, 200, dy=-120)["dir"] == 0


def test_swipeGesture_swipeLeftAdvances_swipeRightGoesBack():
    """Direction contract unchanged from the shipped swipeDirection."""
    assert _gesture(-60, 300)["dir"] == 1
    assert _gesture(60, 300)["dir"] == -1


def test_swipeGesture_slowSettleIsNotFast():
    """60 px over 300 ms = 0.2 px/ms and 12.5% of the card -- under BOTH
    thresholds. This is the operator settling on a screen: move one card, and
    the caller PAUSES."""
    g = _gesture(-60, 300)
    assert g["dir"] == 1
    assert g["fast"] is False


def test_swipeGesture_fastFlickByVelocity():
    """60 px over 50 ms = 1.2 px/ms, past the 0.6 px/ms threshold -- a flick.
    The caller advances and RESUMES auto-rotate."""
    g = _gesture(-60, 50)
    assert g["dir"] == 1
    assert g["fast"] is True


def test_swipeGesture_justUnderTheVelocityThresholdIsSlow():
    """Pin the threshold itself, not just a value comfortably either side: at
    0.59 px/ms the gesture is still a settle."""
    assert _gesture(-59, 100)["fast"] is False  # 0.59 px/ms
    assert _gesture(-60, 100)["fast"] is True  # 0.60 px/ms -- inclusive


def test_swipeGesture_longSlowDragIsFastByTravel():
    """A deliberate full-width drag is a page turn even when it is slow: 280 px
    over 2 s is only 0.14 px/ms but is 58% of the card, past swipeFastTravelFrac.
    Someone who dragged the card most of the way across MEANT to turn the page."""
    g = _gesture(-280, 2000)
    assert g["fast"] is True


def test_swipeGesture_zeroDurationDoesNotFabricateAFlick():
    """dt == 0 is an UNMEASURABLE duration, not an infinitely fast flick.
    Dividing by it would fabricate a velocity from a measurement failure --
    honest-instrument: fall back to the travel test, which IS a real reading."""
    g = _gesture(-60, 0)
    assert g["dir"] == 1
    assert g["fast"] is False


def test_swipeGesture_zeroDurationFullWidthDragStillReadsFast():
    """...and the travel test still answers on its own evidence."""
    assert _gesture(-300, 0)["fast"] is True


def test_swipeGesture_unusableWidthFallsBackToVelocityAlone():
    """A 0/absent card width (a transient 0x0 layout pass) must not divide by
    zero, and must not silently classify every swipe as a full-width drag."""
    assert _gesture(-60, 300, width=0)["fast"] is False
    assert _gesture(-60, 50, width=0)["fast"] is True


# ---------------------------------------------------------------------------
# AC-15 -- pause never freezes forever.
# ---------------------------------------------------------------------------


def test_shouldAutoResume_afterTheIdleWindow():
    """A tap/overlay/settle pauses; after resumeIdleS of NO interaction the
    carousel resumes on its own, so a pause can never freeze it forever."""
    assert _view("shouldAutoResume", True, _RESUME_IDLE_S * 1000, _RESUME_IDLE_S) is True


def test_shouldAutoResume_holdsInsideTheIdleWindow():
    assert _view("shouldAutoResume", True, 44999, _RESUME_IDLE_S) is False


def test_shouldAutoResume_notPausedIsNotAResume():
    """Only a PAUSED carousel resumes -- otherwise the predicate would re-arm a
    running rotation every tick and hide a stuck pause flag."""
    assert _view("shouldAutoResume", False, 999999, _RESUME_IDLE_S) is False


# ---------------------------------------------------------------------------
# Config -- every constant is a grounded, injectable parameter.
# ---------------------------------------------------------------------------


def test_resolveCarouselConfig_absentConfigUsesGroundedDefaults():
    """The file:// preview / unconfigured Pi gets the grounded defaults, never a
    zeroed config (which would disable rotation and read as a dead feature)."""
    cfg = _view("resolveCarouselConfig", None)
    assert cfg["autoRotateS"] == _AUTO_ROTATE_S
    assert cfg["resumeIdleS"] == _RESUME_IDLE_S
    assert cfg["swipeMinPx"] == _SWIPE_MIN_PX
    assert cfg["swipeFastVelocityPxPerMs"] == _FAST_V_PX_PER_MS
    assert cfg["swipeFastTravelFrac"] == _FAST_TRAVEL_FRAC


def test_resolveCarouselConfig_wellTypedOverridesWin():
    cfg = _view("resolveCarouselConfig", {"autoRotateS": 12, "swipeMinPx": 55})
    assert cfg["autoRotateS"] == 12
    assert cfg["swipeMinPx"] == 55
    assert cfg["resumeIdleS"] == _RESUME_IDLE_S  # untouched keys keep the default


def test_resolveCarouselConfig_rejectsUnusableValues():
    """Non-numeric, non-finite and NON-POSITIVE values fall back to the default.
    Rejecting <= 0 here is what makes `resumeIdleS: 0` unable to reach the
    resume predicate at all -- the config cannot express a permanent freeze."""
    cfg = _view(
        "resolveCarouselConfig",
        {"autoRotateS": "8", "resumeIdleS": 0, "swipeMinPx": -1},
    )
    assert cfg["autoRotateS"] == _AUTO_ROTATE_S
    assert cfg["resumeIdleS"] == _RESUME_IDLE_S
    assert cfg["swipeMinPx"] == _SWIPE_MIN_PX


def test_resolveCarouselConfig_ignoresUnknownKeys():
    """An unrelated key in the injected object must not leak into the resolved
    config (the injected blob is whatever pi.display.carousel holds)."""
    cfg = _view("resolveCarouselConfig", {"bogus": 1})
    assert "bogus" not in cfg


def test_configJson_carriesTheCarouselSection():
    """The tuning SSOT: the values the display resolves must exist in config.json,
    or 'it is a config parameter' is a claim with nothing behind it."""
    with open(_CONFIG, encoding="utf-8") as fh:
        config = json.load(fh)
    carousel = config["pi"]["display"]["carousel"]
    assert carousel["autoRotateS"] == _AUTO_ROTATE_S
    assert carousel["resumeIdleS"] == _RESUME_IDLE_S
    assert carousel["swipeMinPx"] == _SWIPE_MIN_PX
    assert carousel["swipeFastVelocityPxPerMs"] == _FAST_V_PX_PER_MS
    assert carousel["swipeFastTravelFrac"] == _FAST_TRAVEL_FRAC


# ---------------------------------------------------------------------------
# Wiring -- the shipped artifacts actually use the logic above.
# ---------------------------------------------------------------------------


def test_dashboardHtml_carriesTheCarouselConfigPlaceholder():
    """The serve-time injection seam (US-483-b's shape). Quoted, so the
    un-substituted file:// preview stays valid JS."""
    html = _read(_HTML)
    assert 'window.DISPLAY_CAROUSEL = "__DISPLAY_CAROUSEL__";' in html


def test_dashboardHtml_shipsTheRotateProgressBar():
    """AC-13's calm thin top bar needs a slot -- no element, no bar, whatever
    the JS computes."""
    html = _read(_HTML)
    assert 'id="rotate-progress"' in html
    assert 'id="rotate-progress-fill"' in html


def test_dashboardCss_stylesTheProgressBarThinAndCalm():
    """A 'calm thin' bar is a spec claim; pin the thin part so a later edit
    cannot quietly turn it into a chunky attention-grabber competing with the
    DTC ribbon it sits beside."""
    css = _read(_CSS)
    assert "#rotate-progress" in css
    block = css[css.index("#rotate-progress") :]
    assert "height: 2px" in block


def test_carouselJs_pointerUpUsesTheVelocityModel():
    """The pointer handler must call swipeGesture -- a velocity model the
    gesture path never invokes is the US-494 lesson repeating."""
    js = _read(_JS)
    assert "swipeGesture(" in js
    # The distance-only call must be GONE from the gesture path, not merely
    # supplemented: leaving both is how a half-applied fix ships (US-496).
    wiring = js[js.index('track.addEventListener("pointerdown"') :]
    wiring = wiring[: wiring.index("Keyboard arrows")]
    assert "swipeDirection(" not in wiring


def test_carouselJs_exportsTheNavModel():
    """The pure logic stays node-testable (the S-2 contract)."""
    js = _read(_JS)
    for name in (
        "swipeGesture:",
        "shouldAutoAdvance:",
        "shouldAutoResume:",
        "rotateProgress:",
        "resolveCarouselConfig:",
    ):
        assert name in js, name


def test_carouselJs_readsTheInjectedCarouselConfig():
    """The DOM half resolves the INJECTED config, not the raw defaults -- else
    retuning config.json would change nothing on the panel."""
    js = _read(_JS)
    assert "global.DISPLAY_CAROUSEL" in js
    assert "resolveCarouselConfig(" in js


def test_carouselJs_tapAndOverlayPauseAutoRotate():
    """AC: a tap on a card or opening any overlay PAUSES. Both must route
    through the one pause entry point, so a future overlay cannot forget."""
    js = _read(_JS)
    assert "pauseAutoRotate" in js
    assert js.count("pauseAutoRotate(") >= 2
