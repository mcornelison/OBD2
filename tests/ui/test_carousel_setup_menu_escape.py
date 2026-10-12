################################################################################
# File Name: test_carousel_setup_menu_escape.py
# Purpose/Description: US-747 (F-132) -- SYSTEM SETUP was a trap: the ✕ gave a
#   flicker and the same screen, and only a reboot escaped it.
#
#   CAUSE (a), MEASURED IN THIS HARNESS BEFORE ANY FIX: the overlay CLOSES and is
#   RE-OPENED. It is not a close-button bug. The long-press handler kept its
#   50 ms interval in ONE variable, `timer`. A second pointerdown before the
#   pointerup (a second finger, a palm, or a duplicated contact) overwrote that
#   handle, so the first interval was never cleared. On the release,
#   `clearPress()` nulled `pressStart` -- and the orphan then computed
#   `Date.now() - null`, i.e. the whole epoch, which is always past the 5 s hold.
#   It called `openMenu()` on EVERY tick, forever. Tapping ✕ really did close the
#   menu; the orphan re-opened it within 50 ms (the flicker), and it rebuilt the
#   rows on every tick so a tap on any other row rarely landed either. A reboot
#   escaped because it destroyed the page, not because anything was cleared.
#
#   Pre-fix harness readings (shipped carousel.js @ af7fb5f0):
#     one tap on the carousel ..................... menu closed
#     two pointerdowns + one pointerup, 0 ms held . menu OPEN (no hold at all)
#     ...then ✕ + one render round ................ menu OPEN again
#     ⋮ open, ✕, three rounds ..................... menu closed
#     5 s hold open, release, ✕, three rounds ..... menu closed
#   The last two are why a close-handler test would have passed throughout.
#
#   CAUSE (b) EXCLUDED by the same readings: ✕ closes the menu in every sequence
#   that has no orphan. PERSISTENCE EXCLUDED: nothing in the dashboard UI reads or
#   writes localStorage / sessionStorage / location.hash / cookies, and the markup
#   ships the menu `hidden`; the Settings footer refers to config values saved
#   server-side, never to the overlay's open state.
#
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Ralph (Rex)  | Initial -- US-747 setup-menu trap guard.
# ================================================================================
################################################################################

"""US-747: SYSTEM SETUP can always be left, and stays left."""

from __future__ import annotations

import os
import re
import shutil
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

PANEL = (480, 320)
_NOW_MS = 1_756_659_000_000

_DASH = os.path.join(_REPO_ROOT, "src", "pi", "ui", "dashboard")
_CAROUSEL_JS = os.path.join(_DASH, "carousel.js")
_HTML = os.path.join(_DASH, "dashboard.html")

_DOWN = {"pointer": {"id": "carousel", "type": "pointerdown", "x": 100, "y": 200}}
_UP = {"pointer": {"id": "carousel", "type": "pointerup", "x": 100, "y": 200}}
_BOOT = {"flush": 4}
# A render round that also lets real time pass: an orphaned interval that only
# fires after the hold would survive a round with a frozen clock.
_LATER = {"advanceMs": 6000, "flush": 3}


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _surface(steps: list[dict[str, Any]], markupPath: str | None = None) -> rh.Surface:
    tree = rh.runDashboard(
        routes={},
        steps=steps,
        markupPath=markupPath,
        viewport=PANEL,
        nowMs=_NOW_MS,
    )["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _rendered(surface: rh.Surface, elementId: str) -> bool:
    path = surface.pathById(elementId)
    assert path is not None, f"#{elementId} is not in the DOM"
    return surface.rendered(path)


def _menuOpen(surface: rh.Surface) -> bool:
    return _rendered(surface, "setup-menu")


# ---------------------------------------------------------------------------
# Section 1 -- THE CAUSE. A second contact must not orphan the hold's interval.
# ---------------------------------------------------------------------------


@_needsNode
def test_twoContactsWithNoHold_doNotOpenTheMenu():
    """The orphan's first symptom: it opened the menu with ZERO ms held."""
    assert _menuOpen(_surface([_BOOT, _DOWN, _DOWN, _UP, _LATER])) is False


@_needsNode
def test_afterASecondContact_closeStaysClosed():
    """The CIO's report, reproduced end to end: a menu opened by a real hold that
    had a second contact in it, then ✕, then the next render cycles."""
    steps = [
        _BOOT,
        _DOWN,
        _DOWN,
        {"advanceMs": 5000, "flush": 1},
        _UP,
        {"click": "menu-close"},
        _LATER,
        _LATER,
    ]
    assert _menuOpen(_surface(steps)) is False


@_needsNode
def test_aSecondContactStillNeedsTheFullHold():
    """The fix must not cancel the hold on a second contact so hard that it can
    never open, nor let the second contact shorten it: it restarts the hold."""
    steps = [_BOOT, _DOWN, {"advanceMs": 3000, "flush": 1}, _DOWN, {"advanceMs": 3000, "flush": 1}]
    assert _menuOpen(_surface(steps)) is False
    assert _menuOpen(_surface([*steps, {"advanceMs": 2000, "flush": 1}])) is True


# ---------------------------------------------------------------------------
# Section 2 -- END STATE, not the event: closed, and still closed later.
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize(
    "opener",
    [
        [{"click": "menu-btn"}, {"flush": 1}],
        [_DOWN, {"advanceMs": 5000, "flush": 1}, _UP],
    ],
    ids=["kebab", "long_press"],
)
def test_closeLeavesTheCardVisibleAndTheMenuClosedAfterFurtherRounds(opener):
    opened = _surface([_BOOT, *opener])
    assert _menuOpen(opened) is True, "control: the menu did not open, so nothing is tested"
    surface = _surface([_BOOT, *opener, {"click": "menu-close"}, _LATER, _LATER])
    assert _menuOpen(surface) is False
    assert _rendered(surface, "carousel") is True


@_needsNode
def test_theCarouselIsInteractiveAfterClose():
    """Interactive, measured: a fresh hold on the card re-opens the menu. A page
    left with a stuck press state would not."""
    steps = [
        _BOOT,
        {"click": "menu-btn"},
        {"click": "menu-close"},
        _LATER,
        _DOWN,
        {"advanceMs": 5000, "flush": 1},
    ]
    assert _menuOpen(_surface(steps)) is True


# ---------------------------------------------------------------------------
# Section 3 -- persistence cause excluded at a keyboard.
# ---------------------------------------------------------------------------


def test_noPersistedStateCanCarryAnOpenOverlay():
    """No such flag exists anywhere in the dashboard UI -- that is the finding.
    If one is ever added, this goes red and the reboot check must be redone."""
    for path in (_CAROUSEL_JS, _HTML):
        text = _read(path)
        for store in ("localStorage", "sessionStorage", "location.hash", "document.cookie"):
            assert store not in text, f"{os.path.basename(path)} now touches {store}"


@_needsNode
def test_firstRenderIsANormalCardNotSystemSetup():
    surface = _surface([{"flush": 0}])
    assert _menuOpen(surface) is False
    assert _rendered(surface, "carousel") is True


# ---------------------------------------------------------------------------
# Section 4 -- a second way out that does not depend on ✕.
# ---------------------------------------------------------------------------


def _withoutCloseControl(tmpPath: str) -> str:
    shipped = _read(_HTML)
    html = re.sub(r'<button id="menu-close"[^>]*>.*?</button>', "", shipped, flags=re.DOTALL)
    assert html != shipped, "the plant did not take -- #menu-close was reshaped"
    with open(tmpPath, "w", encoding="utf-8") as fh:
        fh.write(html)
    return tmpPath


_MENU_DOWN = {"pointer": {"id": "setup-menu", "type": "pointerdown", "x": 240, "y": 160}}
_MENU_UP = {"pointer": {"id": "setup-menu", "type": "pointerup", "x": 240, "y": 160}}


@_needsNode
def test_withNoCloseControl_theSameLongPressDismissesTheMenu(tmp_path):
    markup = _withoutCloseControl(str(tmp_path / "no_close.html"))
    steps = [
        _BOOT,
        {"click": "menu-btn"},
        {"flush": 1},
        _MENU_DOWN,
        {"advanceMs": 5000, "flush": 1},
        _MENU_UP,
        _LATER,
    ]
    surface = _surface(steps, markupPath=markup)
    assert surface.pathById("menu-close") is None, "control: the ✕ was not removed"
    assert _menuOpen(surface) is False


@_needsNode
def test_theDismissHoldIsAlsoTheFullFiveSeconds(tmp_path):
    """Same deliberateness budget as opening (D-6): a resting thumb on a row must
    not throw the operator out of the menu."""
    markup = _withoutCloseControl(str(tmp_path / "no_close.html"))
    steps = [_BOOT, {"click": "menu-btn"}, _MENU_DOWN, {"advanceMs": 4999, "flush": 1}]
    assert _menuOpen(_surface(steps, markupPath=markup)) is True


@_needsNode
def test_aHoldOnTheMenuThatIsReleasedEarlyDoesNothingLater(tmp_path):
    markup = _withoutCloseControl(str(tmp_path / "no_close.html"))
    steps = [_BOOT, {"click": "menu-btn"}, _MENU_DOWN, {"advanceMs": 1000, "flush": 1}, _MENU_UP]
    assert _menuOpen(_surface([*steps, _LATER, _LATER], markupPath=markup)) is True


def test_theSystemSetupEntryPointsAreStillShipped():
    """AC: the fix must not hide the way in."""
    js = _read(_CAROUSEL_JS)
    assert 'menuBtn.addEventListener("click", openMenu)' in js
    assert 'carousel.addEventListener("pointerdown"' in js
    assert '<button id="menu-btn"' in _read(_HTML)
