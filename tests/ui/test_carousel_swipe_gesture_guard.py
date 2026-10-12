################################################################################
# File Name: test_carousel_swipe_gesture_guard.py
# Purpose/Description: US-746 (F-123) -- swipe stopped changing cards; only the
#   page dots navigated.
#
#   CAUSE (c), MEASURED IN A REAL ENGINE BEFORE ANY FIX (Chrome 152 headless,
#   CDP Input.dispatchTouchEvent, 480x320, shipped dashboard @ 3cf45216):
#     touch swipe-left over .card-body ............ pointerdown, 1 pointermove,
#                                                    POINTERCANCEL, no pointerup;
#                                                    card index 0 -> 0
#     touch swipe-right, same ...................... same; 0 -> 0
#     MOUSE drag-left, same element ................ pointerup; 0 -> 1
#     touch swipe-left, .card-body overflow visible  pointerup; 0 -> 1
#     touch swipe-left, .card-body touch-action pan-y pointerup; 0 -> 1
#     touch swipe-left, #carousel touch-action pan-y POINTERCANCEL; 0 -> 0
#     touch tap on dot 3 ........................... pointerup; 0 -> 2
#
#   (a) EXCLUDED: the #track listeners fire -- pointerdown arrives on every
#   touch, and the mouse drag runs the same handler to a card change.
#   (b) EXCLUDED: the identical 200 px / 180 ms gesture is accepted the moment
#   a pointerup reaches the handler (mouse; overflow visible; pan-y). No
#   threshold was touched, and none is touched by the fix.
#   (c) CONFIRMED: `.card-body { overflow-y: auto }` (overflow-x computes auto
#   with it) is a scroll container. Chromium re-allows panning inside a
#   scroller, so the `html, body { touch-action: pan-y }` rule does not reach
#   the card body -- its touch-action computes `auto` -- and the browser claims
#   a horizontal drag as a pan and cancels the pointer stream. Taps never pan,
#   which is the tap-works / swipe-fails signature exactly.
#
#   REGRESSION POINT: 4186b0e9 (US-557, 2026-08-21) added that `.card-body`
#   rule. `git log -S "overscroll-behavior: contain"` returns that one commit;
#   no commit changed the #track handler or the thresholds between US-506
#   (f22b4101) and US-747 (3cf45216, long-press only).
#
#   FIX: `touch-action: pan-y` on the scroller itself. Vertical card-body
#   scroll is kept; nothing in the gesture model changed.
#
#   THREE LAYERS OF GUARD, because the harness that boots carousel.js (mini_dom)
#   has no touch-action and delivers any pointerup it is handed -- a harness-only
#   swipe test passes against this defect:
#     1. cascade: every scroller inside #track keeps horizontal pans off.
#     2. harness: the #track handler turns a synthesised swipe into +1 / -1 and
#        ignores a short, short-slow or near-vertical drag; a dot tap still maps.
#     3. real Chromium (skipped with no browser): a real touch swipe advances,
#        and the same probe with the pan-y reverted does NOT -- so the probe is
#        proven able to see this regression.
#
#   Skipped when node / a Chromium-family browser is not available.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Ralph (Rex)  | Initial -- US-746 swipe gesture guard.
# ================================================================================
################################################################################

"""US-746: a horizontal swipe changes cards, on a real touch pipeline."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_CSS = os.path.join(rh.DASHBOARD_DIR, "dashboard.css")
_PROBE = os.path.join(_HERE, "touch_swipe_probe.mjs")

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None, reason="node not on PATH -- the harness boots the shipped carousel.js"
)

PANEL = (480, 320)
_NOW_MS = 1_756_659_000_000

_SCROLLING = ("auto", "scroll")
_PAN_SAFE = ("pan-y", "none")
_OVERFLOW_PROPS = ("overflow", "overflow-x", "overflow-y")

# Scroll containers that are allowed to leave horizontal panning to the browser.
# Each entry says WHY, and the overlay ones are re-checked against the markup
# below so an exemption cannot quietly outlive the reason it was granted.
_EXEMPT_SCROLLERS = {
    "#setup-menu": "fixed overlay OUTSIDE #track -- no card swipe starts on it",
    "#dtc-detail": "fixed overlay OUTSIDE #track -- no card swipe starts on it",
    "#sys-detail": "fixed overlay OUTSIDE #track -- no card swipe starts on it",
    ".ltft-bars": (
        "horizontal scroller BY DESIGN inside the Fuel Trim card; a drag that "
        "starts on the bar row scrolls the bars, not the carousel"
    ),
}


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Section 1 -- the cascade. The layer that actually regressed.
# ---------------------------------------------------------------------------


def _scrollersInsideTrackWithoutPanY(css: str) -> list[str]:
    surface = rh.Surface(rh.parseMarkup(_HTML), css, PANEL)
    offenders = []
    for path in surface.paths():
        if not any(n.get("attrs", {}).get("id") == "track" for n in path[:-1]):
            continue
        scrolls = any(
            (surface.winningDeclaration(path, prop) or ("",))[0] in _SCROLLING
            for prop in _OVERFLOW_PROPS
        )
        if not scrolls:
            continue
        touchAction = (surface.winningDeclaration(path, "touch-action") or ("auto",))[0]
        if touchAction not in _PAN_SAFE:
            attrs = path[-1].get("attrs", {})
            offenders.append(f"<{path[-1]['tag']} class={attrs.get('class')!r}> {touchAction}")
    return offenders


def _scrollersInsideTrack(css: str) -> int:
    surface = rh.Surface(rh.parseMarkup(_HTML), css, PANEL)
    return sum(
        1
        for path in surface.paths()
        if any(n.get("attrs", {}).get("id") == "track" for n in path[:-1])
        and any(
            (surface.winningDeclaration(path, prop) or ("",))[0] in _SCROLLING
            for prop in _OVERFLOW_PROPS
        )
    )


def test_everyScrollerInsideTheTrack_keepsHorizontalPansOffTheBrowser():
    css = _read(_CSS)
    assert _scrollersInsideTrack(css) >= 6, "control: no card-body scrollers found -- vacuous"
    assert _scrollersInsideTrackWithoutPanY(css) == []


def test_theCascadeGuard_catchesTheUs557Shape():
    """Mutation: the shipped sheet with the US-746 line removed must offend."""
    css = _read(_CSS)
    reverted = re.sub(r"(\.card-body \{[^}]*?)\s*touch-action: pan-y;", r"\1", css, count=1)
    assert reverted != css, "the plant did not take -- the .card-body rule was reshaped"
    assert _scrollersInsideTrackWithoutPanY(reverted), "guard is inert against the regression"


def test_everyScrollingRule_declaresPanYOrIsANamedExemption():
    """Catches a scroller that only JS builds (not in the static markup)."""
    unguarded = []
    for rule in rh.parseCss(_read(_CSS)):
        scrolls = any(
            (rh.declarationOf(rule.declarations, prop) or ("",))[0] in _SCROLLING
            for prop in _OVERFLOW_PROPS
        )
        if not scrolls:
            continue
        touchAction = (rh.declarationOf(rule.declarations, "touch-action") or ("auto",))[0]
        if touchAction in _PAN_SAFE or rule.selector in _EXEMPT_SCROLLERS:
            continue
        unguarded.append(rule.selector)
    assert unguarded == [], (
        f"scroll container(s) {unguarded} leave horizontal pans to the browser: a swipe "
        "that starts on one is cancelled (US-746). Add touch-action: pan-y, or exempt "
        "it here with the reason."
    )


def test_theOverlayExemptionsReallyLiveOutsideTheTrack():
    surface = rh.Surface(rh.parseMarkup(_HTML), _read(_CSS), PANEL)
    for selector in _EXEMPT_SCROLLERS:
        if not selector.startswith("#"):
            continue
        path = surface.pathById(selector[1:])
        assert path is not None, f"{selector} is gone -- drop its exemption"
        inside = any(n.get("attrs", {}).get("id") == "track" for n in path)
        assert not inside, f"{selector} moved inside #track -- its exemption no longer holds"


# ---------------------------------------------------------------------------
# Section 2 -- the handler, through the harness.
# ---------------------------------------------------------------------------


def _pointer(kind: str, x: int, y: int) -> dict[str, Any]:
    return {"pointer": {"id": "track", "type": kind, "x": x, "y": y}}


def _swipe(dx: int, dy: int = 0, ms: int = 150, x: int = 300, y: int = 150) -> list[dict[str, Any]]:
    return [
        _pointer("pointerdown", x, y),
        {"advanceMs": ms, "flush": 1},
        _pointer("pointerup", x + dx, y + dy),
        {"flush": 1},
    ]


_BOOT = {"flush": 4}


def _surface(steps: list[dict[str, Any]]) -> rh.Surface:
    tree = rh.runDashboard(routes={}, steps=steps, viewport=PANEL, nowMs=_NOW_MS)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _activeIndex(surface: rh.Surface) -> int:
    dots = surface.pathsByClass("dot")
    active = [
        i
        for i, p in enumerate(dots)
        if "active" in (p[-1]["attrs"].get("class") or "").split()
    ]
    assert len(active) == 1, f"expected exactly one active dot, got {active}"
    return active[0]


def _trackStep(surface: rh.Surface) -> int:
    path = surface.pathById("track")
    assert path is not None, "#track is not in the DOM"
    transform = ((path[-1].get("style") or {}).get("transform") or "").strip()
    match = re.fullmatch(r"translateX\((-?\d+(?:\.\d+)?)%\)", transform)
    assert match, f"unreadable track transform {transform!r}"
    return int(-float(match.group(1)) // 100)


@_needsNode
def test_swipeLeft_advancesExactlyOneCard():
    surface = _surface([_BOOT, *_swipe(-200)])
    assert _activeIndex(surface) == 1
    assert _trackStep(surface) == 1


@_needsNode
def test_swipeRight_goesBackExactlyOneCard():
    surface = _surface([_BOOT, *_swipe(-200), *_swipe(-200), *_swipe(200)])
    assert _activeIndex(surface) == 1
    assert _trackStep(surface) == 1


@_needsNode
@pytest.mark.parametrize(
    "gesture",
    [
        {"dx": -20},  # short: under the 40 px deadzone
        {"dx": -30, "ms": 2000},  # short AND slow
        {"dx": -60, "dy": 120},  # near-vertical: a card-body scroll
    ],
    ids=["short", "short_slow", "near_vertical"],
)
def test_aDragThatIsNotAPageTurn_leavesTheCardAlone(gesture):
    surface = _surface([_BOOT, *_swipe(**gesture)])
    assert _activeIndex(surface) == 0
    assert _trackStep(surface) == 0


@_needsNode
def test_aDotTap_stillNavigates_afterASwipe():
    steps = [_BOOT, *_swipe(-200), {"clickNth": {"selector": ".dot", "index": 3}}, {"flush": 1}]
    surface = _surface(steps)
    assert _activeIndex(surface) == 3
    assert _trackStep(surface) == 3


# ---------------------------------------------------------------------------
# Section 3 -- a real Chromium touch pipeline. The only layer that saw it.
# ---------------------------------------------------------------------------


def _findChromium() -> str | None:
    env = os.environ.get("CHROME_BIN")
    if env and os.path.exists(env):
        return env
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


_CHROMIUM = _findChromium()
_needsChromium = pytest.mark.skipif(
    _NODE is None or _CHROMIUM is None,
    reason="needs node and a Chromium-family browser -- the defect is in the touch pipeline",
)

_BODY = ".card-body"
_REVERTED = ".card-body { touch-action: auto !important; }"
_SCENARIOS = [
    {"selector": _BODY, "kind": "touch", "dx": -200, "dy": 0, "ms": 180},
    {"selector": _BODY, "kind": "touch", "dx": 200, "dy": 0, "ms": 180},
    {"selector": _BODY, "kind": "touch", "dx": -30, "dy": -120, "ms": 180},
    {"selector": "#dots .dot:nth-child(3)", "kind": "tap"},
    {"selector": _BODY, "kind": "touch", "dx": -200, "dy": 0, "ms": 180, "css": _REVERTED},
]


@pytest.fixture(scope="module")
def realTouch() -> list[dict[str, Any]]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump({"html": _HTML, "chrome": _CHROMIUM, "scenarios": _SCENARIOS}, fh)
        inputPath = fh.name
    try:
        done = subprocess.run(
            ["node", _PROBE, inputPath],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
    finally:
        os.unlink(inputPath)
    assert done.returncode == 0, f"touch probe failed: {done.stderr}"
    return json.loads(done.stdout)["results"]


@_needsChromium
def test_realTouchSwipeLeft_overACardBody_advancesOneCard(realTouch):
    r = realTouch[0]
    assert r["startTouchAction"] == "pan-y"
    assert r["counts"].get("pointercancel") is None, "the browser claimed the swipe as a pan"
    assert r["index1"] == r["index0"] + 1


@_needsChromium
def test_realTouchSwipeRight_goesBackOneCard(realTouch):
    r = realTouch[1]
    assert r["counts"].get("pointerup") == 1
    assert r["index1"] == (r["index0"] - 1) % r["dots"]


@_needsChromium
def test_realNearVerticalDrag_doesNotChangeCards(realTouch):
    r = realTouch[2]
    assert r["index1"] == r["index0"]


@_needsChromium
def test_realDotTap_stillNavigates(realTouch):
    r = realTouch[3]
    assert r["index1"] == 2


@_needsChromium
def test_theRealProbe_seesTheRegression_whenPanYIsReverted(realTouch):
    """The guard is not inert: with the fix reverted the same swipe is cancelled."""
    r = realTouch[4]
    assert r["startTouchAction"] == "auto"
    assert r["counts"].get("pointercancel") == 1
    assert r["index1"] == r["index0"]
