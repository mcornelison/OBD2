################################################################################
# File Name: test_system_sys_detail_r1.py
# Purpose/Description: US-894-j (spec specs/v030-system-page-design.md s4.6.3
#   R1; Atlas re-gate 2026-10-27 s3) -- an open System drill-down (#sys-detail:
#   OBD, DATA, WIFI, UPS or Pi) closes when the car leaves parked, the same R1
#   closer S119 built for #page-detail.
#
#   What is pinned here:
#     - each of the five details, opened parked, is still open 1 s after gear
#       D / link_down (the parked fact is the DEBOUNCED one, US-511-b) and
#       closed at +3.5 s with the System page (.sys-verdict) still painted;
#     - negative control: gear stays P, +3.5 s -> still open;
#     - structure: the closer runs on the open's predicate
#       ('currentParked().parked !== true') and on the render tick, directly
#       after the page-detail closer.
#
#   #dtc-detail is deliberately OUT of R1 (Iris 2026-10-28; warnings spec
#   s4.5 keeps the open code detail visible with its lock label).
#
#   Skipped when node is not on PATH -- the source pins always run.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-28    | Ralph (Rex)  | Initial -- US-894-j #sys-detail R1 closer.
# ================================================================================
################################################################################

"""US-894-j tests: System drill-downs close when the car leaves parked (R1)."""

from __future__ import annotations

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import render_harness as rh  # noqa: E402

from tests.ui.test_system_last_updated import (  # noqa: E402
    _CAROUSEL_JS,
    _NOW_MS,
    _ZONE,
    PANEL,
    _gear,
    _read,
    _routes,
    _text,
)

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped carousel.js",
)

FIXTURE = "all-ok-driving"

# (selector, index, the detail's head) -- the verdict opens Pi; the four
# .sys-row entries open OBD, DATA, WIFI, UPS in page order.
DETAILS = [
    (".sys-verdict", 0, "PI"),
    (".sys-row", 0, "OBD"),
    (".sys-row", 1, "DATA"),
    (".sys-row", 2, "WIFI"),
    (".sys-row", 3, "UPS"),
]
LEAVES = [False, None]


def _open(selector: str, index: int) -> list[dict]:
    return [{"clickNth": {"selector": selector, "index": index}}, {"flush": 2}]


def _render(steps: list[dict]):
    """Boots the dashboard PARKED (gear P), then runs ``steps``."""
    routes = _routes(FIXTURE)
    routes["/gear"] = _gear(True)
    allSteps = [{"flush": 4}, {"advanceMs": 9000, "flush": 4}] + steps
    tree = rh.runDashboard(routes=routes, steps=allSteps, viewport=PANEL, nowMs=_NOW_MS)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _sysDetailOpen(surface) -> bool:
    return surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is None


@_needsNode
@pytest.mark.parametrize("leave", LEAVES, ids=["gear-D", "link-down"])
@pytest.mark.parametrize(("selector", "index", "head"), DETAILS, ids=[d[2] for d in DETAILS])
def test_sys_detail_closes_when_leaving_parked(selector, index, head, leave, monkeypatch):
    """Exit test: opened parked; after the not-parked hold it closes and the
    System page beneath it shows."""
    monkeypatch.setenv("TZ", _ZONE)
    opened = _open(selector, index)
    leaving = opened + [{"setRoutes": {"/gear": _gear(leave)}}, {"flush": 2}]

    held = _render(leaving + [{"advanceMs": 1000, "flush": 4}])
    assert _sysDetailOpen(held), "still parked 1 s in: the detail stays"
    assert _text(held.pathById("sys-detail-head")[-1]) == head

    surface = _render(leaving + [{"advanceMs": 3500, "flush": 4}])
    assert not _sysDetailOpen(surface)
    assert surface.pathsByClass("sys-verdict"), "the System page is still painted"


@_needsNode
@pytest.mark.parametrize(("selector", "index", "head"), DETAILS, ids=[d[2] for d in DETAILS])
def test_sys_detail_staysOpen_whileTheGearStaysParked(selector, index, head, monkeypatch):
    """Negative control (Atlas review F8): gear stays P, +3.5 s -> still open."""
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(_open(selector, index) + [{"advanceMs": 3500, "flush": 4}])
    assert _sysDetailOpen(surface)
    assert _text(surface.pathById("sys-detail-head")[-1]) == head


def test_theSysCloserRunsOnTheTick_onTheOpensPredicate():
    """R1 for #sys-detail is run on every render tick, directly after the
    page-detail closer, on the predicate openSysDetail opens on."""
    js = _read(_CAROUSEL_JS)
    closer = rh._fnBody(js, "closeSysDetailUnlessParked")
    assert "currentParked().parked !== true" in closer
    assert "sysDetailOpen()" in closer and "closeSysDetail()" in closer
    assert "currentParked().parked !== true" in rh._fnBody(js, "openSysDetail")
    tick = rh._fnBody(js, "tick")
    assert "closeSysDetailUnlessParked()" in tick
    pageAt = tick.index("closePageDetailUnlessParked()")
    sysAt = tick.index("closeSysDetailUnlessParked()")
    assert pageAt < sysAt
    between = tick[pageAt + len("closePageDetailUnlessParked()"):sysAt]
    assert between.strip(" \t\r\n;") == "", "directly after the page-detail closer"
