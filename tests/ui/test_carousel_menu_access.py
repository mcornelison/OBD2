################################################################################
# File Name: test_carousel_menu_access.py
# Purpose/Description: Originally US-490 -- context-aware system-setup menu
#   access: the top-bar `⋮` was offered ONLY while the emitter said parked/idle
#   and hidden while driving, with the ~5s long-press as the state-blind
#   override.
#
#   ⚠️ US-659 (CIO ruling 2026-08-31, punch-list H6) RETIRED THAT FEATURE. The
#   menu is now always shown: the long-press was always state-blind, so the menu
#   was reachable in every state the gate hid the glyph in -- the glyph was not
#   protecting the affordance, it was misreporting it. `menuAccess`,
#   `applyMenuAccess` and `updateMenuAccess` no longer exist, and the markup no
#   longer ships the button hidden.
#
#   SEVEN TESTS WERE RETIRED FROM THIS FILE, not repaired, because their SUBJECT
#   was deleted -- a test of a removed conditional cannot be made to pass without
#   asserting the opposite of the ruling. Their replacements live in
#   tests/ui/test_carousel_kebab_always_visible.py, which pins the removal and
#   drives the long-press end-to-end. The retirements are listed by name at the
#   bottom of this header so the count is auditable rather than merely smaller.
#
#   WHAT THIS FILE STILL COVERS, and it is why the file was not deleted:
#     - `carouselIdle`, the strict reading of the `idle` SSOT boolean. It no
#       longer feeds the ⋮; it feeds `updateHomeNav` (carousel.js:5111), which
#       returns the carousel to the home card on the parked<->driving edge. The
#       fail-closed behaviour and the "never re-derive idle from the drive-state
#       string" rule (Atlas idle-SSOT b) are unchanged and still load-bearing.
#     - The AC3 scope fence: destructive menu items keep their confirms.
#
#   RETIRED BY US-659: test_menuAccess_parked_offersTheTapAffordance (menuAccess
#   half only -- the carouselIdle half survives in the renamed test below),
#   test_menuAccess_driving_hidesTheTapAffordance (likewise),
#   test_menuAccess_longPress_survivesEveryState,
#   test_menuAccess_longPress_isNotTheTapAffordance,
#   test_applyMenuAccess_hidesTheButtonItself,
#   test_tapHandlerIsGatedByVisibility_notCssAlone,
#   test_menuButtonShipsHidden_soBootIsFailClosed,
#   test_hiddenMenuButtonIsRemoved_notMerelyTransparent (MOVED, not dropped --
#   the `#menu-btn[hidden]` rule is KEPT and is now what makes the deletion test
#   able to fail; it is asserted in test_carousel_kebab_always_visible.py with
#   that reasoning attached).
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
# 2026-08-31    | Ralph (Rex)  | US-659: the visibility gate is gone. Retired the
#               |              | 7 gate tests; repointed the carouselIdle tests
#               |              | at the consumer that survives.
# ================================================================================
################################################################################

"""Post-US-659: the `idle` SSOT reading that outlived the ⋮ visibility gate."""

import json
import os
import shutil
import subprocess

import pytest

# US-659 dropped this file's `_ruleBlock` import along with its last CSS
# assertion: the `#menu-btn[hidden]` rule is KEPT in the stylesheet but is now
# asserted in tests/ui/test_carousel_kebab_always_visible.py, where the reason
# it survives (it is what lets the deletion test fail) can be stated beside it.
from tests.ui.test_dashboard_stop_tier_safety import _read

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard")
_JS = os.path.join(_DIST, "carousel.js")


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
    """A drive is recording -- the not-idle pole."""
    return _sys(False, driveState="recording", driveId=27)


_NODE_TESTS = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


# ---------------------------------------------------------------------------
# `carouselIdle` -- the strict reading of the `idle` SSOT boolean.
#
# THESE TESTS HAVE NOW OUTLIVED TWO CONSUMERS, and that is the reason they are
# worth keeping rather than a reason to be suspicious of them. US-490 wrote them
# against the ⋮ visibility gate; US-511 re-aimed them at `carouselIdle` when the
# debounce took over the acquisition; US-659 removed the gate entirely. The
# question they actually guard -- "is the vehicle parked?", read from the `idle`
# SSOT and never re-derived from the drive-state string -- did not move, and it
# now serves `updateHomeNav` (carousel.js:5111), which returns the carousel to
# the home card on the parked<->driving edge.
#
# THE NAMES CHANGED WITH THE CONSUMER. "failsClosedToHidden" described what the
# gate did with the answer; nothing hides any more, so the tests now say what
# `carouselIdle` RETURNS. Leaving the old names would have left this file
# describing a feature the codebase no longer has.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_carouselIdle_parked_readsTrue():
    """Parked (engine off, no OBD link) is the affirmative case."""
    assert _view("carouselIdle", _sys(True)) is True


@_NODE_TESTS
def test_carouselIdle_driving_readsFalse():
    """A drive is recording -- not idle."""
    assert _view("carouselIdle", _driving()) is False


@_NODE_TESTS
def test_carouselIdle_stateUnreadable_failsClosedToNotIdle():
    """An absent/unreadable system-status is a known-UNKNOWN, and this resolves
    it to not-idle rather than guessing a calm parked state. US-659 changed what
    hangs off that answer, not the answer: an unknown must still not be reported
    as a settled `parked`."""
    assert _view("carouselIdle", None) is False


@_NODE_TESTS
def test_carouselIdle_idleFlagAbsent_failsClosedToNotIdle():
    """A payload from an emitter that never wrote `idle` must not read parked."""
    state = _sys(True)
    del state["idle"]
    assert _view("carouselIdle", state) is False


@_NODE_TESTS
def test_carouselIdle_idleNotBoolean_failsClosedToNotIdle():
    """The truthy string "false" is the classic way a JSON-ish flag lies. Only a
    real `true` boolean counts as parked."""
    for junk in ("true", "false", 1, {}):
        assert _view("carouselIdle", _sys(junk)) is False, junk


@_NODE_TESTS
def test_carouselIdle_readsTheIdleSsot_notTheDriveString():
    """Atlas idle-SSOT b: the display RENDERS the emitter's flag and never
    re-derives idle from the drive-state string. Pinned in BOTH directions so a
    future "helpful" fallback to `drive.state` re-reds this test."""
    # drive says idle, the SSOT says otherwise -> the SSOT wins.
    assert _view("carouselIdle", _sys(False, driveState="idle")) is False
    # drive says recording, the SSOT says parked -> the SSOT wins.
    assert _view("carouselIdle", _sys(True, driveState="recording", driveId=27)) is True


@_NODE_TESTS
def test_carouselIdle_isStillConsumed_soTheseTestsAreNotGuardingDeadCode():
    """US-659 removed one of this function's two consumers. Keeping a pure
    function under test after its last caller is gone is how a suite grows tests
    for code nothing runs -- so the surviving caller is asserted by name. If
    `updateHomeNav` also goes, this file should be retired with it rather than
    quietly kept."""
    js = _read(_JS)
    start = js.index("function updateHomeNav(sysData)")
    # Bounded at its own closing brace (6-space indent -- this one is nested
    # inside setup()), so the assertion cannot be satisfied by a carouselIdle
    # call somewhere else in the file.
    assert "carouselIdle(sysData)" in js[start : js.index("\n      }", start)]


# ---------------------------------------------------------------------------
# The long-press, as a SCOPE FENCE. US-659 made this the only gate on the menu,
# so the requirement that it stay state-blind got stronger, not weaker.
#
# This is an ABSENCE assertion and cannot prove the hold still works; the
# behavioural half (a real 5s press opening a real menu) lives in
# tests/ui/test_carousel_kebab_always_visible.py section 4. Both are needed.
# ---------------------------------------------------------------------------


def test_longPressPathIsNotGatedByIdleState():
    """Gating the override with an idle check would lock the operator out while
    driving -- the one state where they may most need to stop a misbehaving
    service. Post-US-659 it would also leave the menu with NO way in at all."""
    js = _read(_JS)
    start = js.index('carousel.addEventListener("pointerdown"')
    block = js[start : js.index('carousel.addEventListener("pointercancel"', start)]
    for gate in ("menuAccess", "tapVisible", "carouselIdle", "menuBtn.hidden"):
        assert gate not in block, f"the long-press override is gated by {gate}"


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
