################################################################################
# File Name: test_settings_lux_ends.py
# Purpose/Description: US-895-b (F-126; specs/v030-system-page-design.md s4.7)
#   -- the Settings band's AUTO-DIM ENDS row: pi.display.autoDim.luxMin /
#   luxFull drawn as ONE row of kind 'ladder', each end a stepper on the
#   1-2-3-5 ladder bounded 1..1000 lux. The ends hide their -/+, an off-ladder
#   stored value shows as stored and steps to its neighbour, the page disables
#   the crossing step, and a crossing write that reaches the seam (the recorded
#   real 400 in settings-lux-cross-rejected) ends "couldn't save" + snap back.
#
#   The DOM half boots the SHIPPED carousel.js over the SHIPPED markup through
#   the render harness, with the band-state stub prepended to a TEMP COPY of
#   carousel.js (tests/ui/test_settings_lock.py `_carousel`).
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-23    | Ralph (Rex)  | Initial -- US-895-b the auto-dim ends row.
# ================================================================================
################################################################################

"""US-895-b: Settings can set the auto-dim ends, and they can never cross."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import render_harness as rh  # noqa: E402
from test_settings_lock import (  # noqa: E402
    _BOOT,
    _FIXTURE_DIR,
    _HOLD_8S,
    _NOW_MS,
    _OPEN_KEBAB,
    PANEL,
    _attrs,
    _carousel,
    _fixture,
    _generator,
    _needsNode,
    _posts,
    _read,
    _routes,
    _text,
    _view,
)

_LUX_MIN = "pi.display.autoDim.luxMin"
_LUX_FULL = "pi.display.autoDim.luxFull"
_AUTO_ROTATE = "pi.display.carousel.autoRotateS"
_LADDER = [1, 2, 3, 5, 10, 20, 30, 50, 100, 200, 300, 500, 1000]
_APPLY = "applies at the next light reading"
_CROSS = "settings-lux-cross-rejected"


def _spec(key: str) -> dict:
    (spec,) = [s for s in _view("settingsSpecs") if s["key"] == key]
    return spec


def _settings(luxMin: Any, luxFull: Any) -> dict[str, Any]:
    """The band-state stub, the shipped rows plus the two ends."""
    stub = dict(_fixture("settings-parked-idling")["payloads"]["settings"])
    stub[_LUX_MIN] = {"found": True, "value": luxMin}
    stub[_LUX_FULL] = {"found": True, "value": luxFull}
    return stub


def _run(tmp_path, name: str, steps: list[dict], *, settings: dict | None = None,
         routes: dict | None = None) -> dict[str, Any]:
    fx = _fixture(name)
    out = rh.runDashboard(
        routes=routes if routes is not None else _routes(fx),
        steps=steps,
        carouselPath=_carousel(
            tmp_path, settings if settings is not None else fx["payloads"]["settings"]
        ),
        viewport=PANEL,
        nowMs=_NOW_MS,
    )
    out["surface"] = rh.dashboardSurface(out["tree"], viewport=PANEL)
    return out


def _parked(tmp_path, settings: dict, extra: list[dict] | None = None,
            routes: dict | None = None) -> dict[str, Any]:
    return _run(tmp_path, "settings-parked-idling",
                _BOOT + _HOLD_8S + _OPEN_KEBAB + (extra or []),
                settings=settings, routes=routes)


def _ends(surface) -> dict[str, list[dict]]:
    return {_attrs(p)["data-key"]: p for p in surface.pathsByClass("set-end")}


def _find(node: dict, cls: str) -> list[dict]:
    found: list[dict] = []

    def walk(n: dict) -> None:
        if cls in (n.get("attrs", {}).get("class") or "").split():
            found.append(n)
        for child in n.get("children", []):
            if "tag" in child:
                walk(child)

    walk(node)
    return found


def _endValue(surface, key: str) -> str:
    (value,) = _find(_ends(surface)[key][-1], "set-value")
    return _text(value)


def _endSteps(surface, key: str) -> dict[str, dict]:
    """The end's drawn steps by class ('minus'/'plus'), each its attrs."""
    end = _ends(surface)[key][-1]
    out = {}
    for kind in ("minus", "plus"):
        nodes = _find(end, f"set-step-{kind}")
        if nodes:
            out[kind] = nodes[0].get("attrs", {})
    return out


def _luxRow(surface) -> dict:
    rows = [p for p in surface.pathsByClass("set-row") if _attrs(p)["data-key"] == _LUX_MIN]
    assert len(rows) == 1
    return rows[0][-1]


# ---------------------------------------------------------------------------
# The spec table: two ladder specs, one row, first in DISPLAY.
# ---------------------------------------------------------------------------


@_needsNode
def test_theEndsAreTwoLadderSpecs_drawnAsOneRow_thatMustNotCross():
    luxMin, luxFull = _spec(_LUX_MIN), _spec(_LUX_FULL)
    for spec in (luxMin, luxFull):
        assert spec["kind"] == "ladder"
        assert spec["row"] == "AUTO-DIM ENDS"
        assert spec["section"] == "DISPLAY"
        assert spec["steps"] == _LADDER
        assert spec["applyNote"] == _APPLY
    assert (luxMin["below"], luxMin["above"]) == (_LUX_FULL, None)
    assert (luxFull["below"], luxFull["above"]) == (None, _LUX_MIN)
    assert [s["key"] for s in _view("settingsSpecs")][:3] == [_LUX_MIN, _LUX_FULL, _AUTO_ROTATE]


@_needsNode
@pytest.mark.parametrize(
    ("stored", "direction", "nextValue"),
    [
        (4, 1, 5), (4, -1, 3),          # off the ladder: the neighbour (spec s4.7)
        (3, 1, 5), (3, -1, 2),
        (300, 1, 500), (300, -1, 200),
        (1, -1, None),                  # the bottom end: its - is hidden
        (1000, 1, None),                # the top end: its + is hidden
        (0.5, 1, 1), (0.5, -1, None),
        (2000, -1, 1000), (2000, 1, None),
        (None, 1, None),
    ],
)
def test_ladderStep_movesToTheNeighbourRung(stored, direction, nextValue):
    for key in (_LUX_MIN, _LUX_FULL):
        assert _view("settingsStepNext", _spec(key), stored, direction) == nextValue


@_needsNode
@pytest.mark.parametrize(("stored", "shown"), [(3, "3 lux"), (4, "4 lux"), (3.4, "3.4 lux"),
                                                (300, "300 lux"), (1000, "1000 lux")])
def test_ladderRow_showsTheStoredLux_onOrOffTheLadder(stored, shown):
    row = _view("settingsRowView", _spec(_LUX_FULL), stored)
    assert (row["known"], row["display"], row["value"]) == (True, shown, stored)


@_needsNode
@pytest.mark.parametrize("junk", [None, 0, -3, "3", True, {}])
def test_ladderRow_aValueTheOverlayCouldNotStore_isUnknown(junk):
    row = _view("settingsRowView", _spec(_LUX_MIN), junk)
    assert (row["known"], row["display"]) == (False, "Unknown")


@_needsNode
@pytest.mark.parametrize(
    ("key", "nextValue", "partner", "crosses"),
    [
        (_LUX_MIN, 300, 300, True), (_LUX_MIN, 500, 300, True), (_LUX_MIN, 200, 300, False),
        (_LUX_FULL, 3, 3, True), (_LUX_FULL, 2, 3, True), (_LUX_FULL, 5, 3, False),
        (_LUX_MIN, 300, None, False),   # an unknown partner: the seam is the rule
        (_AUTO_ROTATE, 30, 5, False),   # a spec with no partner never crosses
    ],
)
def test_stepCrosses_isLuxFullAboveLuxMin_strict(key, nextValue, partner, crosses):
    assert _view("settingsStepCrosses", _spec(key), nextValue, partner) is crosses


@_needsNode
def test_ladderWritesTheChosenLux():
    assert _view("settingsWriteValue", _spec(_LUX_FULL), 500) == 500


# ---------------------------------------------------------------------------
# The fixture is the generator's, and its 400 is the real server's.
# ---------------------------------------------------------------------------


def test_theCrossFixtureOnDiskIsWhatTheGeneratorBuilds():
    gen = _generator()
    assert _CROSS in gen.fixtureNames()
    assert _read(os.path.join(_FIXTURE_DIR, f"{_CROSS}.json")) == gen.render(
        gen.buildFixture(_CROSS)
    ), f"{_CROSS}.json is stale -- re-run tests/ui/fixtures/states/system/_generate.py"


def test_theCrossFixturesWriteIsTheServersRecorded400():
    write = _fixture(_CROSS)["payloads"]["settings-write"]
    assert write["status"] == 400
    assert write["body"] == {
        "ok": False, "key": _LUX_FULL, "value": 300.0,
        "error": "luxFull must be greater than luxMin",
    }


# ---------------------------------------------------------------------------
# DOM: one row, two ends.
# ---------------------------------------------------------------------------


@_needsNode
def test_oneRow_namedAutoDimEnds_withBothEndsAndOneApplyTag(tmp_path):
    surface = _parked(tmp_path, _settings(3.0, 300.0))["surface"]
    row = _luxRow(surface)
    (name,) = _find(row, "set-name")
    assert _text(name) == "AUTO-DIM ENDS"
    (tag,) = _find(row, "set-apply")
    assert _text(tag) == _APPLY
    assert [_attrs(p)["data-key"] for p in surface.pathsByClass("set-end")] == [
        _LUX_MIN, _LUX_FULL,
    ]
    assert [_text(n) for n in _find(row, "set-end-name")] == ["DIM-START", "FULL-BRIGHT"]
    assert (_endValue(surface, _LUX_MIN), _endValue(surface, _LUX_FULL)) == (
        "3 lux", "300 lux",
    )
    # DISPLAY opens on it, before ROTATE PAGES.
    keys = [_attrs(p)["data-key"] for p in surface.pathsByClass("set-row")]
    assert keys[:2] == [_LUX_MIN, _AUTO_ROTATE]


@_needsNode
def test_theEndsHideTheirOuterSteps(tmp_path):
    surface = _parked(tmp_path, _settings(1, 1000))["surface"]
    assert set(_endSteps(surface, _LUX_MIN)) == {"plus"}
    assert set(_endSteps(surface, _LUX_FULL)) == {"minus"}


@_needsNode
def test_theCrossingStepsAreDisabled_andTheOthersAreNot(tmp_path):
    """DIM-START 200 / FULL-BRIGHT 300: DIM-START + would make 300 (>= 300) and
    FULL-BRIGHT - would make 200 (<= 200) -- both disabled, both still drawn."""
    surface = _parked(tmp_path, _settings(200, 300))["surface"]
    low, high = _endSteps(surface, _LUX_MIN), _endSteps(surface, _LUX_FULL)
    assert low["plus"].get("disabled") is not None
    assert high["minus"].get("disabled") is not None
    assert low["minus"].get("disabled") is None
    assert high["plus"].get("disabled") is None


@_needsNode
def test_aTapOnADisabledCrossingStep_writesNothing(tmp_path):
    out = _parked(tmp_path, _settings(200, 300),
                  [{"clickNth": {"selector": ".set-step-plus", "index": 0}}, {"flush": 1}])
    assert _posts(out) == []
    assert _endValue(out["surface"], _LUX_MIN) == "200 lux"


@_needsNode
def test_anOffLadderValue_stepsToItsNeighbour_andShowsTheReRead(tmp_path):
    """Stored 4 (hand-edited): + posts 5, and the end repaints from the 200's
    re-read; the partner's crossing step follows the new value."""
    fx = _fixture("settings-parked-idling")
    routes = _routes(fx)
    routes["/settings"] = {"ok": True, "key": _LUX_MIN, "value": 5}
    out = _parked(tmp_path, _settings(4, 10),
                  [{"clickNth": {"selector": ".set-step-plus", "index": 0}}, {"flush": 1}],
                  routes=routes)
    surface = out["surface"]
    (post,) = _posts(out)
    assert json.loads(post["body"]) == {"key": _LUX_MIN, "value": 5}
    assert _endValue(surface, _LUX_MIN) == "5 lux"
    (tag,) = _find(_luxRow(surface), "set-apply")
    assert _text(tag) == f"{_APPLY} · saved"
    # FULL-BRIGHT 10: its - would now make 5 (<= 5), so it is disabled.
    assert _endSteps(surface, _LUX_FULL)["minus"].get("disabled") is not None
    assert out["tree"]["attrs"].get("data-reloads") is None


@_needsNode
def test_aCrossingWriteThatReachesTheSeam_couldntSave_andSnapsBack(tmp_path):
    """settings-lux-cross-rejected: the page reads DIM-START 3, so FULL-BRIGHT -
    (to 200) is offered; the recorded real 400 refuses it."""
    out = _run(tmp_path, _CROSS, _BOOT + _HOLD_8S + _OPEN_KEBAB + [
        {"clickNth": {"selector": ".set-step-minus", "index": 1}}, {"flush": 1}])
    surface = out["surface"]
    (post,) = _posts(out)
    assert json.loads(post["body"]) == {"key": _LUX_FULL, "value": 200}
    assert _endValue(surface, _LUX_FULL) == "300 lux"
    (tag,) = _find(_luxRow(surface), "set-apply")
    assert _text(tag) == f"{_APPLY} · couldn't save"
    assert out["tree"]["attrs"].get("data-reloads") is None


@_needsNode
def test_lockedTheEndsAreReadable_withNoSteps(tmp_path):
    """Settings rows inherit US-895-a's gear lock."""
    out = _run(tmp_path, "settings-locked-driving", _BOOT + _OPEN_KEBAB + [{"flush": 1}],
               settings=_settings(3.0, 300.0))
    surface = out["surface"]
    assert _attrs(surface.pathById("settings-list"))["data-locked"] == "true"
    assert _endSteps(surface, _LUX_MIN) == {} and _endSteps(surface, _LUX_FULL) == {}
    assert (_endValue(surface, _LUX_MIN), _endValue(surface, _LUX_FULL)) == (
        "3 lux", "300 lux",
    )


def test_theEndsStylesUseTokens_andTheStepsMeetTheTapMinimum():
    css = _read(os.path.join(_FIXTURE_DIR, "..", "..", "..", "..", "..",
                             "src", "pi", "ui", "dashboard", "dashboard.css"))
    for selector in (".set-end {", ".set-end-name {", ".set-step:disabled {"):
        start = css.index(selector)
        assert "#" not in css[start: css.index("}", start)], selector
    start = css.index(".set-step {")
    assert "var(--tap-min)" in css[start: css.index("}", start)]
