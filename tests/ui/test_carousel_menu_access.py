################################################################################
# File Name: test_carousel_menu_access.py
# Purpose/Description: US-490 fixture tests for context-aware system-setup menu
#   access (src/pi/ui/dashboard/carousel.js + dashboard.css +
#   dashboard.html). Iris polish P-2, CIO-locked Option C: the top-bar `⋮` is a
#   SINGLE-TAP path into consequential actions (service stop, Exit UI), so it is
#   offered ONLY while the emitter says parked/idle, and is hidden while driving.
#   The deliberate ~5s long-press stays available in EVERY state so the operator
#   is never locked out. These tests drive the pure export through the node
#   probe (carousel_probe.js) and guard the wiring by source inspection -- the
#   pure function is inert unless the poll actually applies it and the tap
#   handler actually honours it.
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-27    | Ralph (Rex)  | Initial -- US-490 context-aware menu access.
# ================================================================================
################################################################################

"""US-490 fixture tests for context-aware system-setup menu access (via node)."""

import json
import os
import shutil
import subprocess

import pytest

# Reuse the canonical CSS parsers rather than re-implementing them: `_ruleBlock`
# is line-anchored, so a descendant rule can never be mistaken for the base rule
# it overrides.
from tests.ui.test_dashboard_stop_tier_safety import _read, _ruleBlock

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard")
_CSS = os.path.join(_DIST, "dashboard.css")
_JS = os.path.join(_DIST, "carousel.js")
_HTML = os.path.join(_DIST, "dashboard.html")


def _view(fn: str, *args: object) -> dict:
    """Evaluate one carousel.js export against N fixtures via the node probe.

    `encoding` is pinned to utf-8 deliberately -- `text=True` alone decodes
    node's UTF-8 with the Windows locale codepage and mangles any non-ASCII
    copy under test (TD-068).
    """
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _sys(idle: object, *, driveState: str = "idle", driveId: object = None) -> dict:
    """A system-status payload carrying the US-480-a `idle` SSOT boolean.

    `idle` is deliberately typed `object` so a test can plant a non-boolean and
    pin the fail-closed path.
    """
    return {
        "obdLink": {"state": None, "retries": 0, "lastSeenS": None},
        "sync": {"lastOkTs": None, "rows": 0, "pending": 0, "stale": False},
        "power": {"mode": "car", "source": "battery"},
        "drive": {"state": driveState, "driveId": driveId},
        "idle": idle,
        "ts": "2026-07-27T20:10:00Z",
    }


def _driving() -> dict:
    """The state this whole story exists to protect: a drive is recording."""
    return _sys(False, driveState="recording", driveId=27)


_NODE_TESTS = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _fnBody(js: str, signature: str) -> str:
    """Slice one function's source out of carousel.js by its opening line."""
    start = js.index(signature)
    return js[start : js.index("\n    }", start)]


# ---------------------------------------------------------------------------
# AC1 -- the `⋮` single-tap affordance is PARKED-ONLY.
#
# US-511 MOVED THE SEAM THESE TESTS SIT ON, and the tests moved with it rather
# than being deleted. `menuAccess` used to take the system-status payload and
# call `carouselIdle` on it; it now takes an already-debounced boolean, so a
# payload fixture can no longer reach it. What these tests were really guarding
# -- that "is the vehicle parked?" is read from the `idle` SSOT and fails CLOSED
# on every unreadable variant -- is unchanged and still lives on this path, one
# link upstream. So they are re-aimed at `carouselIdle`, the link that now owns
# that question, and the policy half is pinned on the boolean it now receives.
# US-511's own suite (test_carousel_parked_debounce.py) covers the debounce
# between the two.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_menuAccess_parked_offersTheTapAffordance():
    """Parked (engine off): the ⋮ is a convenience, not a hazard."""
    assert _view("carouselIdle", _sys(True)) is True
    assert _view("menuAccess", True)["tapVisible"] is True


@_NODE_TESTS
def test_menuAccess_driving_hidesTheTapAffordance():
    """The whole point (AC-4): no single-tap path into stop/Exit while driving."""
    assert _view("carouselIdle", _driving()) is False
    assert _view("menuAccess", False)["tapVisible"] is False


@_NODE_TESTS
def test_menuAccess_stateUnreadable_failsClosedToHidden():
    """An absent/unreadable system-status is a known-UNKNOWN, and the unknown
    side of "am I driving?" is the dangerous one -- hide. Safe to fail closed
    ONLY because the long-press override is unconditional (see AC2 below)."""
    assert _view("carouselIdle", None) is False


@_NODE_TESTS
def test_menuAccess_idleFlagAbsent_failsClosedToHidden():
    """A payload from an emitter that never wrote `idle` must not read parked."""
    state = _sys(True)
    del state["idle"]
    assert _view("carouselIdle", state) is False


@_NODE_TESTS
def test_menuAccess_idleNotBoolean_failsClosedToHidden():
    """The truthy string "false" is the classic way a JSON-ish flag lies. Only a
    real `true` boolean counts as parked."""
    for junk in ("true", "false", 1, {}):
        assert _view("carouselIdle", _sys(junk)) is False, junk


@_NODE_TESTS
def test_menuAccess_readsTheIdleSsot_notTheDriveString():
    """Atlas idle-SSOT b: the display RENDERS the emitter's flag and never
    re-derives idle from the drive-state string. Pinned in BOTH directions so a
    future "helpful" fallback to `drive.state` re-reds this test."""
    # drive says idle, the SSOT says otherwise -> the SSOT wins (stay hidden).
    assert _view("carouselIdle", _sys(False, driveState="idle")) is False
    # drive says recording, the SSOT says parked -> the SSOT wins (show).
    assert _view("carouselIdle", _sys(True, driveState="recording", driveId=27)) is True


# ---------------------------------------------------------------------------
# AC2 -- the 5s long-press override is UNCONDITIONAL. This is what makes the
# fail-closed tap affordance above safe: hiding the ⋮ can never strand the
# operator, because the deliberate hold still opens the menu in every state.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_menuAccess_longPress_survivesEveryState():
    """Every input `menuAccess` can be handed, including the malformed ones --
    the override is the one thing that must never depend on the answer."""
    for parked in (True, False, None, "true", {}):
        assert _view("menuAccess", parked)["longPress"] is True, parked


@_NODE_TESTS
def test_menuAccess_longPress_isNotTheTapAffordance():
    """While driving the two paths must DISAGREE -- if they ever collapse into
    one flag, either the tap comes back or the override disappears."""
    access = _view("menuAccess", False)
    assert access["longPress"] != access["tapVisible"]


# ---------------------------------------------------------------------------
# AC1/AC4 wiring -- the pure function is inert on its own. A story that adds
# menuAccess() and never applies it passes every test above while the ⋮ sits
# visible at 70mph.
# ---------------------------------------------------------------------------


def test_pollAppliesMenuAccessEveryTick():
    """The affordance must track the live state, not the state at boot.

    US-511 added the tick clock to the call (the debounce measures a hold), so
    the expected call text moved with it. The invariant is unchanged: the poll
    applies the policy on every tick."""
    js = _read(_JS)
    assert "updateMenuAccess(sysData, nowMs)" in js, "menuAccess computed but never applied"


def test_applyMenuAccess_hidesTheButtonItself():
    """`hidden` (not a class) is the rendered truth the tap gate reads back."""
    body = _fnBody(_read(_JS), "function applyMenuAccess")
    assert "hidden" in body
    assert "tapVisible" in body


def test_tapHandlerIsGatedByVisibility_notCssAlone():
    """Defence in depth for AC-4: a CSS regression that re-paints the button
    must not also re-open the single-tap path into a service stop."""
    js = _read(_JS)
    # Bound the window tightly at the next listener registration -- a loose
    # slice runs on into openMenu/closeMenu and finds THEIR `hidden` writes,
    # which is how this guard would pass while the handler stayed ungated.
    start = js.index('menuBtn.addEventListener("click"')
    handler = js[start : js.index("if (closeBtn)", start)]
    assert "menuBtn.hidden" in handler, "the click handler trusts CSS alone to hide the tap path"


def test_longPressPathIsNotGatedByIdleState():
    """AC-2 read as a scope fence: the override must stay state-blind. Gating it
    with the same idle check would lock the operator out while driving -- the
    one state where they may most need to stop a misbehaving service."""
    js = _read(_JS)
    start = js.index('carousel.addEventListener("pointerdown"')
    block = js[start : js.index('carousel.addEventListener("pointercancel"', start)]
    for gate in ("menuAccess", "tapVisible", "carouselIdle", "menuBtn.hidden"):
        assert gate not in block, f"the long-press override is gated by {gate}"


def test_menuButtonShipsHidden_soBootIsFailClosed():
    """Before the first poll returns, "am I driving?" is unknown -- the markup
    must not offer the tap path during that window."""
    html = _read(_HTML)
    start = html.index('id="menu-btn"')
    assert "hidden" in html[start : html.index(">", start)]


def test_hiddenMenuButtonIsRemoved_notMerelyTransparent():
    """The kebab's parent is a flex container -- `#topbar .topbar-right` since
    US-555 moved it out of the bar itself, which is now a grid. Either way a
    future `display:flex` on #menu-btn would silently beat the UA [hidden] rule
    and hand back a clickable target while driving. MOVED PIN: this used to say
    "#topbar is a flex container"; the container changed, the hazard did not."""
    block = _ruleBlock(_read(_CSS), "#menu-btn[hidden]")
    assert "display: none" in block


# ---------------------------------------------------------------------------
# AC3 scope fence -- destructive items keep their existing confirms. This story
# changes WHERE the menu can be reached from, never what it does once open.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_stopStillRequiresConfirm():
    assert _view("requiresConfirm", "stop") is True
    assert _view("requiresConfirm", "restart") is False


@_NODE_TESTS
def test_serviceAllowListUnchanged_powerwatchIsRestartOnly():
    items = _view("serviceMenuItems")
    guard = [i for i in items if i["unit"] == "eclipse-powerwatch.service"]
    assert len(items) == 3
    assert guard and guard[0]["canStop"] is False


def test_exitStillRoutesThroughTheConfirmingAction():
    """Exit / Close UI is a dashboard `stop`, so it inherits requiresConfirm --
    it must not gain a direct postAction shortcut while this file is open."""
    js = _read(_JS)
    start = js.index("if (exitBtn) {")
    block = js[start : js.index("\n      }", start)]
    assert 'doAction("eclipse-dashboard.service", "stop")' in block
    assert "postAction(" not in block
