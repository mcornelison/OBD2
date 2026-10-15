################################################################################
# File Name: test_driving_rpm_bar.py
# Purpose/Description: US-888-b (F-140) tests for the Driving card's RPM bar
#   and its motion (specs/v030-driving-page-design.md s4.1, s4.2). Guarded:
#     1. the STEP -- the bar is a pure function of ONE real sample: 2000 then
#        4000 is two paints with nothing in between, and no transition on a
#        segment can fabricate the values the ECU never sent;
#     2. the ZONES -- every segment is zoned by its lower edge against
#        params.RPM.scale {amberFrom, redFrom} and nothing else; carousel.js
#        holds no 5500 / 7000 literal (grep gate, with a negative control);
#     3. the STALE bar -- last.value, dimmed, with its age on the RPM slot;
#     4. the REDLINE -- RPM >= scale.redFrom flashes the lit red segments
#        (0.5 s, 2 steps) and the number is --critical-red from params.RPM.band
#        only; amber stays warm white; reduced-motion keeps the colour and
#        drops the flash;
#     5. the GLIDE -- the gear glides only when the measured gear changes.
#   NOT GUARDED, stated rather than implied: the render harness resolves the
#   cascade and treats every non-width @media as matching, so "reduced motion
#   shows no flash" is pinned as "every Driving animation is declared only
#   inside (prefers-reduced-motion: no-preference)"; the glass check is the R15
#   screenshot owed on the Pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Ralph (Rex)  | Initial -- US-888-b RPM bar, redline, glide.
# ================================================================================
################################################################################

"""US-888-b tests for the Driving card's stepped RPM bar."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

from tests.ui.css_type_scale import DASHBOARD_CSS  # noqa: E402

_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "driving")

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped browser JS",
)

# The shipped provider scale (band_producer.rpmScale from pi.bands.rpm.*) and
# a moved one: the edges must follow the payload, never the page.
SCALE = {"amberFrom": 5500, "redFrom": 7000}
MOVED_SCALE = {"amberFrom": 6000, "redFrom": 7500}
# Spec s4.1: 16 segments x 500 rpm.
SEGMENTS = 16
SEGMENT_RPM = 500
NO_PREFERENCE = "prefers-reduced-motion: no-preference"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _probe(fn: str, *args: object) -> Any:
    cmd = [_NODE or "node", _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _rpm(value: float | None, band: str | None = "green", scale: Any = None) -> dict[str, Any]:
    """An obd-live params.RPM entry as the emitter publishes it."""
    return {
        "value": value,
        "unit": "rpm",
        "ts": "2026-10-13T12:30:08Z",
        "stale": False,
        "band": None if band is None else {"band": band, "since": "2026-10-13T12:30:08Z"},
        "last": None,
        "scale": copy.deepcopy(SCALE if scale is None else scale),
    }


def _bar(param: Any) -> dict[str, Any]:
    return _probe("rpmBarView", param)


def _withRpm(name: str, rpm: dict[str, Any]) -> dict[str, Any]:
    fx = _fixture(name)
    fx["obd-live"]["params"]["RPM"] = rpm
    return fx


def _surface(fx: dict[str, Any], steps: list[dict[str, Any]] | None = None) -> rh.Surface:
    routes: dict[str, Any] = {"/obd-live": fx["obd-live"], "/gear": fx["gear"]}
    dom = rh.runDashboard(routes=routes, nowMs=_ms(fx["now"]), steps=steps or [{"flush": 4}])
    return rh.dashboardSurface(dom["tree"])


def _inDriving(path: list[dict[str, Any]]) -> bool:
    return any(n.get("attrs", {}).get("id") == "driving-card" for n in path)


def _paths(surface: rh.Surface, cls: str) -> list[list[dict[str, Any]]]:
    return [p for p in surface.pathsByClass(cls) if _inDriving(p)]


def _segments(surface: rh.Surface) -> list[list[dict[str, Any]]]:
    return _paths(surface, "drv-seg")


def _litCount(surface: rh.Surface) -> int:
    return sum(1 for p in _segments(surface) if p[-1]["attrs"].get("data-lit") == "true")


def _barAttrs(surface: rh.Surface) -> dict[str, str]:
    bars = _paths(surface, "drv-rpm-bar")
    assert len(bars) == 1
    return bars[0][-1]["attrs"]


def _rpmSlot(surface: rh.Surface) -> list[dict[str, Any]]:
    for path in _paths(surface, "drv-reading"):
        if path[-1]["attrs"].get("data-pid") == "RPM":
            return path
    raise AssertionError("no RPM .drv-reading")


def _descendant(path: list[dict[str, Any]], cls: str) -> list[dict[str, Any]]:
    def walk(node: dict[str, Any], trail: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        for child in node.get("children", []):
            if "tag" not in child:
                continue
            here = trail + [child]
            if cls in (child.get("attrs", {}).get("class") or "").split():
                return here
            found = walk(child, here)
            if found is not None:
                return found
        return None

    found = walk(path[-1], path)
    assert found is not None, f"no .{cls}"
    return found


def _textOf(node: dict[str, Any]) -> str:
    return "".join(
        c["text"] if "text" in c else _textOf(c) for c in node.get("children", [])
    ).strip()


def _gear(surface: rh.Surface) -> list[dict[str, Any]]:
    gears = _paths(surface, "drv-gear")
    assert len(gears) == 1
    return gears[0]


def _drivingRules() -> list[rh.Rule]:
    return [
        rule
        for rule in rh.parseCss(_read(DASHBOARD_CSS))
        if "#driving-card" in rule.selector or ".drv-" in rule.selector
    ]


def _scopedVar(name: str) -> str:
    block = " ".join(r.declarations for r in _drivingRules() if r.selector == "#driving-card")
    match = re.search(rf"{re.escape(name)}\s*:\s*([^;]+);", block)
    assert match is not None, f"{name} is not declared on #driving-card"
    return match.group(1).strip()


def _keyframes(name: str) -> str:
    css = rh._stripComments(_read(DASHBOARD_CSS))
    match = re.search(rf"@keyframes\s+{re.escape(name)}\s*\{{(.*?\}})\s*\}}", css, re.S)
    assert match is not None, f"no @keyframes {name}"
    return match.group(1)


# ---------------------------------------------------------------------------
# 1. The step -- one sample, one paint; nothing interpolated.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_barView_hasSixteenSegmentsOf500Rpm():
    view = _bar(_rpm(2000))
    assert len(view["segments"]) == SEGMENTS
    # Segment i is lit once the sample reaches its lower edge i * 500.
    assert view["lit"] == 2000 // SEGMENT_RPM + 1


@_NODE_ONLY
def test_samples2000Then4000_paintTwoStatesAndNothingBetween():
    first, second = _bar(_rpm(2000)), _bar(_rpm(4000))
    assert (first["lit"], second["lit"]) == (5, 9)
    for view in (first, second):
        lit = [s["lit"] for s in view["segments"]]
        assert lit == [True] * view["lit"] + [False] * (SEGMENTS - view["lit"])


@_NODE_ONLY
def test_theShippedDomSteps_onTheNextRealSample():
    low = _withRpm("gear-3", _rpm(2000))
    high = _withRpm("gear-3", _rpm(4000))
    assert _litCount(_surface(low)) == 5
    stepped = _surface(
        low,
        steps=[{"flush": 4}, {"setRoutes": {"/obd-live": high["obd-live"]}}, {"advanceMs": 1000},
               {"flush": 4}],
    )
    assert _litCount(stepped) == 9
    assert len(_segments(stepped)) == SEGMENTS, "the bar re-built its segments"


@_NODE_ONLY
def test_noSegmentTransitionsOrAnimates_belowTheRedline():
    """A transition between two samples would paint values the ECU never sent
    (Spool 08-07): no segment may declare one, and below redFrom none animates."""
    surface = _surface(_withRpm("gear-3", _rpm(6999, band="amber")))
    for path in _segments(surface):
        assert surface.winningDeclaration(path, "transition") is None
        assert surface.winningDeclaration(path, "animation") is None
    for rule in _drivingRules():
        if ".drv-seg" in rule.selector or ".drv-rpm-bar" in rule.selector:
            assert rh.declarationOf(rule.declarations, "transition") is None, rule.selector


# ---------------------------------------------------------------------------
# 2. The zones -- from params.RPM.scale only.
# ---------------------------------------------------------------------------


@_NODE_ONLY
@pytest.mark.parametrize(
    "value,zone",
    [(5499, "green"), (5500, "amber"), (6999, "amber"), (7000, "red")],
)
def test_leadingZone_followsTheProviderScale(value: int, zone: str):
    assert _bar(_rpm(value))["zone"] == zone


@_NODE_ONLY
@pytest.mark.parametrize(
    "value,zone",
    [(5999, "green"), (6000, "amber"), (7499, "amber"), (7500, "red")],
)
def test_movedScale_movesTheEdges(value: int, zone: str):
    assert _bar(_rpm(value, scale=MOVED_SCALE))["zone"] == zone


@_NODE_ONLY
def test_everySegmentIsZonedByItsLowerEdge():
    zones = [s["zone"] for s in _bar(_rpm(8000))["segments"]]
    assert zones == ["green"] * 11 + ["amber"] * 3 + ["red"] * 2
    moved = [s["zone"] for s in _bar(_rpm(8000, scale=MOVED_SCALE))["segments"]]
    assert moved == ["green"] * 12 + ["amber"] * 3 + ["red"] * 1


@_NODE_ONLY
@pytest.mark.parametrize("scale", [None, {}, {"amberFrom": 5500}, {"amberFrom": "x", "redFrom": 1}])
def test_noUsableScale_paintsNoZone_andNeverFlashes(scale: Any):
    param = _rpm(7500, band="red")
    param["scale"] = scale
    view = _bar(param)
    assert {s["zone"] for s in view["segments"]} == {"none"}
    assert view["zone"] is None and view["redline"] is False
    assert view["lit"] == SEGMENTS


def test_carouselJs_holdsNoRpmZoneLiteral():
    assert _zoneLiterals(_read(_JS)) == []


def test_zoneLiteralGate_catchesAPlantedThreshold():
    assert _zoneLiterals("var X = 1; if (rpm >= 7000) red();") == ["7000"]
    assert _zoneLiterals("var amber = 5500;") == ["5500"]
    assert _zoneLiterals("var t = 155000; var u = 70001;") == []


def _zoneLiterals(source: str) -> list[str]:
    return re.findall(r"(?<![\w.])(5500|7000)(?![\w.])", source)


# ---------------------------------------------------------------------------
# 3. Not read and stale.
# ---------------------------------------------------------------------------


@_NODE_ONLY
@pytest.mark.parametrize("param", [None, {"value": None, "unit": "rpm", "stale": False}])
def test_notRead_lightsNothing(param: Any):
    view = _bar(param)
    assert view["lit"] == 0 and view["zone"] is None and view["redline"] is False
    assert not any(s["lit"] for s in view["segments"])


@_NODE_ONLY
def test_stale_paintsLastValue_dimmed_andNeverFlashes():
    param = _rpm(None, band=None)
    param.update({"stale": True, "last": {"value": 7200, "band": {"band": "red"}}})
    view = _bar(param)
    assert view["stale"] is True and view["lit"] == 15 and view["zone"] == "red"
    # A flash says "over the redline NOW"; a stale sample cannot say that.
    assert view["redline"] is False


@_NODE_ONLY
def test_staleBar_isDimmed_andTheRpmSlotShowsItsAge():
    surface = _surface(_fixture("ecu-silent-stale"))
    attrs = _barAttrs(surface)
    assert attrs.get("data-stale") == "true"
    assert _litCount(surface) == 2450 // SEGMENT_RPM + 1
    bar = _paths(surface, "drv-rpm-bar")[0]
    opacity = surface.winningDeclaration(bar, "opacity")
    assert opacity == ("var(--drv-stale-opacity)", '#driving-card .drv-rpm-bar[data-stale="true"]')
    note = _descendant(_rpmSlot(surface), "drv-note")
    assert surface.rendered(note) and re.fullmatch(r"\d+ s", _textOf(note[-1]))


# ---------------------------------------------------------------------------
# 4. The redline -- flash + red number; amber stays white; reduced motion.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_redline_flashesTheLitRedSegments_andTheNumberIsRed():
    surface = _surface(_withRpm("gear-3", _rpm(7000, band="red")))
    assert _barAttrs(surface).get("data-redline") == "true"
    flashing = []
    for path in _segments(surface):
        attrs = path[-1]["attrs"]
        animation = surface.winningDeclaration(path, "animation")
        if attrs.get("data-lit") == "true" and attrs.get("data-zone") == "red":
            assert animation is not None and "drv-redline-flash" in animation[0]
            flashing.append(path)
        else:
            assert animation is None, attrs
    assert len(flashing) == 1
    value = _descendant(_rpmSlot(surface), "drv-value")
    assert surface.winningDeclaration(value, "color")[0] == "var(--critical-red)"


def test_redlineFlash_is0_5sInTwoSteps():
    assert _scopedVar("--drv-flash-s") == "0.5s"
    rules = [r for r in _drivingRules() if "drv-redline-flash" in r.declarations]
    assert len(rules) == 1
    decl = rh.declarationOf(rules[0].declarations, "animation")
    assert decl is not None
    assert "var(--drv-flash-s)" in decl[0] and re.search(r"steps\(2\b", decl[0])
    assert "infinite" in decl[0]
    assert "var(--line)" in _keyframes("drv-redline-flash")


@_NODE_ONLY
@pytest.mark.parametrize("band", ["amber", "green", None])
def test_rpmNumber_staysWarmWhite_unlessTheBandIsRed(band: str | None):
    surface = _surface(_withRpm("gear-3", _rpm(6000, band=band)))
    value = _descendant(_rpmSlot(surface), "drv-value")
    assert surface.winningDeclaration(value, "color")[0] == "var(--text-primary)"
    assert _barAttrs(surface).get("data-redline") == "false"


@_NODE_ONLY
def test_rpmNumberRed_comesFromTheBand_notFromTheScale():
    """The number's red is params.RPM.band; a red band with no scale still
    paints it, and a value over redFrom with a green band does not."""
    noScale = _rpm(7200, band="red")
    noScale["scale"] = None
    surface = _surface(_withRpm("gear-3", noScale))
    value = _descendant(_rpmSlot(surface), "drv-value")
    assert surface.winningDeclaration(value, "color")[0] == "var(--critical-red)"
    green = _surface(_withRpm("gear-3", _rpm(7200, band="green")))
    gv = _descendant(_rpmSlot(green), "drv-value")
    assert green.winningDeclaration(gv, "color")[0] == "var(--text-primary)"


def test_everyDrivingAnimation_isStateQualified_andMotionOptIn():
    """Reduced motion keeps the colour and drops the flash: every Driving
    animation lives only inside (prefers-reduced-motion: no-preference) and on
    a data-attribute-qualified selector (test_dashboard_animation_gating)."""
    animated = [r for r in _drivingRules() if rh.declarationOf(r.declarations, "animation")]
    assert len(animated) >= 3, "redline flash + two glide keyframe rules"
    for rule in animated:
        assert NO_PREFERENCE in rule.media, rule.selector
        assert re.search(r"\[data-[\w-]+=\"[^\"]+\"\]", rule.selector), rule.selector


def test_redColours_doNotDependOnMotion():
    """The red number and the zone colours hold under reduced motion: they are
    declared OUTSIDE any motion media query."""
    colourRules = [
        r
        for r in _drivingRules()
        if "var(--critical-red)" in r.declarations
        and ('data-pid="RPM"' in r.selector or ".drv-seg" in r.selector)
    ]
    assert len(colourRules) == 2
    assert all("reduced-motion" not in r.media for r in colourRules)


# ---------------------------------------------------------------------------
# 5. The glide -- only on a measured gear change.
# ---------------------------------------------------------------------------


def _gearSteps(*names: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    first = _fixture(names[0])
    steps: list[dict[str, Any]] = [{"flush": 4}]
    for name in names[1:]:
        steps += [{"setRoutes": {"/gear": _fixture(name)["gear"]}}, {"advanceMs": 1000},
                  {"flush": 4}]
    return first, steps


@_NODE_ONLY
def test_firstGear_doesNotGlide():
    fx, steps = _gearSteps("gear-3")
    surface = _surface(fx, steps)
    assert "data-glide" not in _gear(surface)[-1]["attrs"]
    assert surface.winningDeclaration(_gear(surface), "animation") is None


@_NODE_ONLY
def test_sameGearAgain_doesNotGlide():
    fx, steps = _gearSteps("gear-3", "gear-3")
    surface = _surface(fx, steps)
    assert "data-glide" not in _gear(surface)[-1]["attrs"]


@_NODE_ONLY
@pytest.mark.parametrize(
    "names", [("gear-3", "gear-4"), ("gear-3", "between-gears-no-hint", "gear-4")]
)
def test_aMeasuredGearChange_glides(names: tuple[str, ...]):
    fx, steps = _gearSteps(*names)
    surface = _surface(fx, steps)
    gear = _gear(surface)
    assert _textOf(gear[-1]) == "4"
    assert gear[-1]["attrs"].get("data-glide") in ("a", "b")
    animation = surface.winningDeclaration(gear, "animation")
    assert animation is not None and "drv-gear-glide" in animation[0]


@_NODE_ONLY
def test_twoChanges_alternateTheGlide_soTheAnimationRestarts():
    once = _gear(_surface(*_gearSteps("gear-3", "gear-4")))[-1]["attrs"].get("data-glide")
    twice = _gear(_surface(*_gearSteps("gear-3", "gear-4", "gear-5")))[-1]["attrs"]
    assert {once, twice.get("data-glide")} == {"a", "b"}


@_NODE_ONLY
def test_betweenGears_doesNotGlide():
    fx, steps = _gearSteps("gear-3", "between-gears-no-hint")
    assert "data-glide" not in _gear(_surface(fx, steps))[-1]["attrs"]


def test_glide_is0_35s_fadeAnd14pxRise():
    assert _scopedVar("--drv-glide-s") == "0.35s"
    assert _scopedVar("--drv-glide-rise") == "14px"
    for name in ("drv-gear-glide-a", "drv-gear-glide-b"):
        frames = _keyframes(name)
        assert "opacity: 0" in frames and "translateY(var(--drv-glide-rise))" in frames
