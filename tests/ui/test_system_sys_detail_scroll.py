################################################################################
# File Name: test_system_sys_detail_scroll.py
# Purpose/Description: US-894-i (spec specs/v030-system-page-design.md s4.6.3;
#   CIO ruling 2026-10-28 via Iris; Atlas review F7) -- every System detail
#   (OBD, DATA, WIFI, UPS, Pi) scrolls in ONE container, #sys-detail-body, with
#   a VISIBLE thin token scrollbar, so no row is hidden without a sign and
#   ‹ Back never scrolls away.
#
#   What is pinned here:
#     - for each of the five details opened parked: #sys-detail-body's winning
#       declarations are the #setup-menu bar (overflow-y auto, scrollbar-width
#       thin, scrollbar-color var(--text-secondary) var(--surface)) plus
#       min-height 0 / flex 1 1 auto, and #sys-detail's winning overflow is
#       hidden;
#     - ‹ Back stays in #sys-detail's top 44 px with the body scrolled to its
#       end on rows-not-counted (the tallest real case, DATA): no scroll
#       container sits between #sys-detail and ‹ Back. The harness has no
#       layout engine, so the scroll is MODELLED: an element moves by the
#       scroll offset exactly when the scrolling container is its ancestor;
#     - LAST ROW REACHABLE (a guard): the DATA detail's last element, the
#       .obd-detail-sentence card, is inside #sys-detail-body, and nothing
#       between them clips it or fixes its height.
#
#   Skipped when node is not on PATH.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-28    | Ralph (Rex)  | Initial -- US-894-i #sys-detail-body scrolls.
# ================================================================================
################################################################################

"""US-894-i tests: the System details scroll with a visible bar."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped carousel.js",
)

PANEL = (480, 320)
_ZONE = "America/Chicago"
_DASH = os.path.join(_REPO_ROOT, "src", "pi", "ui", "dashboard")
_CSS = os.path.join(_DASH, "dashboard.css")
_SYSTEM_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "states", "system")
_NOW = "2026-10-22T23:10:00Z"
_NOW_MS = int(datetime(2026, 10, 22, 23, 10, tzinfo=UTC).timestamp() * 1000)
_TALLEST = "rows-not-counted"
# Atlas measured the DATA detail at 843 px of content in the 320 px overlay
# (offices/architect/evidence/2026-10-28-s119-gate-g/fitcheck-s119-run2.raw.txt:27).
_DATA_CONTENT_PX = 843
_HEAD_BAND_PX = 44
_SCROLLING = {"auto", "scroll"}
_CLIPPING = {"hidden", "clip"}

# The five details and the tap that opens each (rows: OBD, DATA, WIFI, UPS;
# the verdict opens the Pi detail).
_DETAILS = {
    "OBD": (".sys-row", 0),
    "DATA": (".sys-row", 1),
    "WIFI": (".sys-row", 2),
    "UPS": (".sys-row", 3),
    "PI": (".sys-verdict", 0),
}


def _gearParked() -> dict:
    from pi.obdii.gear_derivation import GEAR_PARK, REASON_PARK, GearReading
    from pi.obdii.gear_state_emitter import buildGearState

    return buildGearState(GearReading(True, GEAR_PARK, REASON_PARK), nowIso=_NOW)


def _open(name: str, tap: tuple[str, int], css: str | None = None):
    with open(os.path.join(_SYSTEM_DIR, f"{name}.json"), encoding="utf-8") as fh:
        payloads = json.load(fh)["payloads"]
    routes: dict[str, Any] = {"/" + k: v for k, v in payloads.items()}
    routes["/gear"] = _gearParked()
    steps = [
        {"flush": 4}, {"advanceMs": 9000, "flush": 4},
        {"clickNth": {"selector": tap[0], "index": tap[1]}}, {"flush": 1},
    ]
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL, nowMs=_NOW_MS)["tree"]
    if css is None:
        return rh.dashboardSurface(tree, viewport=PANEL)
    return rh.Surface(tree, css, viewport=PANEL)


def _text(node: dict) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _text(child))
    return "".join(out)


def _declared(surface, path, prop: str) -> str | None:
    found = surface.winningDeclaration(path, prop)
    return None if found is None else found[0].strip()


def _overflowY(surface, path) -> str | None:
    return _declared(surface, path, "overflow-y") or _declared(surface, path, "overflow")


def _px(value: str) -> float:
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)px", value.strip())
    assert m, value
    return float(m.group(1))


def _scroller(surface, path) -> list[dict] | None:
    """The nearest ancestor of ``path`` that scrolls vertically, as a path."""
    for depth in range(len(path) - 2, -1, -1):
        if _overflowY(surface, path[: depth + 1]) in _SCROLLING:
            return path[: depth + 1]
    return None


def _backTopPx(surface, scrollTop: float) -> float:
    """‹ Back's top, relative to #sys-detail, with the content scrolled.

    The content scroller is the nearest scrolling ancestor of the DATA
    detail's last card; ‹ Back moves up by ``scrollTop`` exactly when that
    scroller is also ITS ancestor (or #sys-detail itself).
    """
    detail = surface.pathById("sys-detail")
    back = surface.pathById("sys-detail-back")
    (sentence,) = surface.pathsByClass("obd-detail-sentence")
    scroller = _scroller(surface, sentence)
    assert scroller is not None, "the DATA detail scrolls in no container"
    padTop = _px(_declared(surface, detail, "padding").split()[0])
    moves = back[: len(scroller)] == scroller
    return padTop - (scrollTop if moves else 0.0)


def _assertLastRowReachable(surface) -> None:
    body = surface.pathById("sys-detail-body")
    lastChild = [c for c in body[-1]["children"] if "tag" in c][-1]
    assert "obd-detail-sentence" in lastChild["attrs"]["class"].split()
    assert "NOT COUNTED" in _text(body[-1]), "rows-not-counted no longer paints its most cards"
    (sentence,) = surface.pathsByClass("obd-detail-sentence")
    assert sentence[: len(body)] == body, "the sentence card is outside #sys-detail-body"
    for depth in range(len(body), len(sentence)):
        el = sentence[: depth + 1]
        if depth < len(sentence) - 1:
            assert _overflowY(surface, el) not in _CLIPPING, el[-1]["attrs"]
        assert _declared(surface, el, "max-height") in (None, "none"), el[-1]["attrs"]
        assert _declared(surface, el, "height") in (None, "auto"), el[-1]["attrs"]


@_needsNode
def test_sys_detail_scrolls_with_visible_bar_lastDataRowReachable(monkeypatch):
    """
    Given: each of the five System details opened parked
    When:  the winning declarations on #sys-detail and #sys-detail-body resolve
    Then:  the body is the ONE scroller with a visible thin token bar, the
           overlay itself is overflow hidden, ‹ Back stays in the top 44 px with
           the DATA detail scrolled to its end, and its last card is reachable
    """
    monkeypatch.setenv("TZ", _ZONE)
    for head, tap in _DETAILS.items():
        surface = _open(_TALLEST, tap)
        detail = surface.pathById("sys-detail")
        assert detail[-1]["attrs"].get("hidden") is None, head
        assert _text(surface.pathById("sys-detail-head")[-1]) == head
        body = surface.pathById("sys-detail-body")
        assert _declared(surface, body, "overflow-y") == "auto", head
        assert _declared(surface, body, "scrollbar-width") == "thin", head
        assert _declared(surface, body, "scrollbar-color") == (
            "var(--text-secondary) var(--surface)"
        ), head
        assert _declared(surface, body, "min-height") == "0", head
        assert _declared(surface, body, "flex") == "1 1 auto", head
        assert _declared(surface, detail, "overflow") == "hidden", head
        assert _declared(surface, detail, "overflow-y") is None, head

    data = _open(_TALLEST, _DETAILS["DATA"])
    maxScroll = _DATA_CONTENT_PX - PANEL[1]
    assert 0 <= _backTopPx(data, 0) < _HEAD_BAND_PX
    assert 0 <= _backTopPx(data, maxScroll) < _HEAD_BAND_PX
    _assertLastRowReachable(data)


@_needsNode
def test_negativeControl_theOldSheetScrollsBackAway(monkeypatch):
    """The pre-story rule (overflow-y on #sys-detail) fails the Back check."""
    monkeypatch.setenv("TZ", _ZONE)
    css = open(_CSS, encoding="utf-8").read()
    old = re.sub(r"#sys-detail-body \{[^}]*\}", "", css)
    old = old.replace(
        "box-sizing: border-box; overflow: hidden;\n}\n#sys-detail[hidden]",
        "box-sizing: border-box; overflow-y: auto;\n}\n#sys-detail[hidden]",
    )
    assert old != css
    surface = _open(_TALLEST, _DETAILS["DATA"], css=old)
    assert _backTopPx(surface, _DATA_CONTENT_PX - PANEL[1]) < 0


@_needsNode
def test_negativeControl_aClippingWrapperFailsLastRowReachable(monkeypatch):
    """A planted max-height on the sentence card is caught by the guard."""
    monkeypatch.setenv("TZ", _ZONE)
    css = open(_CSS, encoding="utf-8").read() + "\n.obd-detail-sentence { max-height: 20px; }\n"
    surface = _open(_TALLEST, _DETAILS["DATA"], css=css)
    with pytest.raises(AssertionError):
        _assertLastRowReachable(surface)
