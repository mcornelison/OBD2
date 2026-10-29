################################################################################
# File Name: test_engine_page.py
# Purpose/Description: US-889-b (F-127) tests for the Engine card above the fold
#   -- V0.30 Engine layout B (specs/v030-engine-page-design.md s3-s4). Guarded:
#     1. the SLOT -- a new card at index 1, right after Driving (E-2 order),
#        every other card keeping its relative order;
#     2. the UNITS -- displayUnits gains ONLY the canonical keys '%', 'deg',
#        'g/s', 'count' (Atlas G1), and carousel.js names no python-obd unit;
#     3. the VALUES -- ENGINE_LOAD, THROTTLE_POS, TIMING_ADVANCE from
#        states/obd-live through the exported view AND the shipped DOM: stale is
#        last.value dimmed with its age, not read / absent is '--' + reason,
#        timing signed as BTDC / ATDC and always captioned 'base timing · not
#        knock', load neutral at 100 %, bars filled 0-100 % in --accent;
#     4. the TYPE -- load --fs-hero, throttle and timing --fs-primary, values
#        and units in --font-mono (it carries the degree glyph), labels in
#        Michroma;
#     5. the CSS GATE -- tokens only, literal px only in the ONE #engine-card
#        custom-property block, motion only when state-qualified;
#     6. the FIT -- a height/width model of the whole glance at 480x320 from
#        the declared values (US-889-d: no scroll, no cue), with negative
#        controls;
#     7. US-889-e -- LOAD and THROTTLE as full-width horizontal bars, the
#        value inside, drawn twice and clipped to the fill.
#   NOT GUARDED, stated rather than implied: the render harness resolves the
#   cascade, not layout (render_harness.py fidelity limit 1), so "visible
#   without scrolling" here is the arithmetic model in section 6; the glass
#   check is the R15 screenshot owed on the Pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Ralph (Rex)  | Initial -- US-889-b Engine card above the fold.
# 2026-10-19    | Ralph (Rex)  | US-892-b -- MOVED PIN: the Motion card replaces the Home
#                               card at index 4.
# 2026-10-23    | Ralph (Rex)  | US-894-e -- MOVED PIN: the Battery card is retired
#               |              | (9 -> 8).
# 2026-10-26    | Rex (US-891-c) | MOVED PIN: the O2 card joins between Fuel and Motion.
# 2026-10-27    | Rex (US-889-d) | MOVED PINS (spec s3a): no scroll cue (:99, :504),
#               |              | bars 26 x 168 (:641-643), the CSS gate admits the
#               |              | #engine-detail scope, and the above-the-fold model
#               |              | (:700/:704) is REPLACED by the glance budget.
# 2026-10-27    | Rex (US-889-e) | Horizontal bars (CIO ruling). MOVED PINS:
#               |              | test_barGeometry_is26x168 -> _isFullWidthBy48, the
#               |              | fill height pins (:500/:535) -> width + copies, the
#               |              | bar-column widths, the bar-height model and the
#               |              | glance budget -> the AC-d re-lay; labels; the
#               |              | planted transition is now for width.
# 2026-10-28    | Rex (US-889-f) | Bar heads hold 18 px with a note (AC-5 model:
#               |              | _headCharge, Atlas's measured 21 under baseline);
#               |              | the footer is charged from the markup. MOVED PINS:
#               |              | _gaugeHeight, _footContentHeight, _glanceHeight
#               |              | (DOM surfaces), _rowWidth -> _timingHeadWidth, the
#               |              | planted-footer control (4th row), worstCase (label
#               |              | line), AC_d (flex-basis on .eng-timing-head).
# ================================================================================
################################################################################

"""US-889-b tests for the Engine card (layout B, above the fold)."""

from __future__ import annotations

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

from pi.obdii.band_producer import NO_BAND_REASONS  # noqa: E402
from tests.ui.css_type_scale import (  # noqa: E402
    DASHBOARD_CSS,
    readCss,
    scaleValues,
)
from tests.ui.test_dashboard_fidelity_pass import _stripJsComments  # noqa: E402
from tests.ui.test_topbar_three_column_grid import (  # noqa: E402
    PI_MONO_ADVANCE_EM,
    michromaWidthPx,
)

_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "engine")

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped browser JS",
)

# The card order (US-889-b validation row "Card order"), by kit label.
# MOVED PIN (US-890-a): the Fuel card replaces Fuel Trim at index 2, after Engine.
# MOVED PIN (US-896-a): the NAV card is index 1, right after Driving (E-2).
# MOVED PIN (US-892-b): the Motion card replaces the Home card at index 4.
# MOVED PIN (US-893-b): Light moves to index 5, right after Motion (E-2).
# MOVED PIN (US-894-e): the Battery card is retired (9 -> 8); its cell is
# the System page's UPS row.
# MOVED PIN (US-891-c): the O2 card joins between Fuel and Motion (8 -> 9).
CARD_ORDER = [
    "Driving", "Navigation", "Engine", "Fuel", "O2", "Motion", "Light", "Alerts",
    "System Status",
]

ENGINE_PIDS = ["ENGINE_LOAD", "THROTTLE_POS", "TIMING_ADVANCE"]
BAR_PIDS = ["ENGINE_LOAD", "THROTTLE_POS"]
TIMING_BASIS = "base timing · not knock"
# US-889-d (spec s3a): the cue is deleted; the page no longer scrolls.
RETIRED_CUE = "↓ history and status below"

# This story's fixtures (spec s7). US-889-c adds its own to the same directory,
# so the set is asserted as PRESENT, not as the directory's whole contents.
FIXTURE_NAMES = ["idle-warm", "wot-pull-load-100", "not-read-with-reason", "stale"]


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


def _view(name: str) -> dict[str, Any]:
    fx = _fixture(name)
    return _probe("engineView", fx["obd-live"], _ms(fx["now"]))


def _param(value: float | None, unit: str = "deg", **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "value": value, "unit": unit, "ts": "2026-10-20T15:12:29Z", "stale": False,
        "band": None, "noBandReason": "no_band_defined", "last": None,
    }
    entry.update(extra)
    return entry


def _sectionTags(html: str) -> list[str]:
    return re.findall(r'<section class="card"[^>]*>', html, re.S)


def _engineMarkup() -> str:
    match = re.search(r'<section class="card"[^>]*id="engine-card".*?</section>', _read(_HTML), re.S)
    assert match is not None, "no #engine-card section in dashboard.html"
    return match.group(0)


def _textOf(node: dict[str, Any]) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _textOf(child))
    return "".join(out).strip()


def _classes(node: dict[str, Any]) -> list[str]:
    return (node.get("attrs", {}).get("class") or "").split()


def _inEngine(path: list[dict[str, Any]]) -> bool:
    return any(n.get("attrs", {}).get("id") == "engine-card" for n in path)


def _enginePaths(surface: rh.Surface, cls: str) -> list[list[dict[str, Any]]]:
    return [p for p in surface.pathsByClass(cls) if _inEngine(p)]


def _byPid(surface: rh.Surface, cls: str, pid: str) -> list[dict[str, Any]]:
    for path in _enginePaths(surface, cls):
        if path[-1].get("attrs", {}).get("data-pid") == pid:
            return path
    raise AssertionError(f"no .{cls} for {pid}")


def _child(path: list[dict[str, Any]], cls: str) -> list[dict[str, Any]]:
    """The first descendant of ``path`` carrying ``cls``, as a full path."""

    def walk(node: dict[str, Any], trail: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        for child in node.get("children", []):
            if "tag" not in child:
                continue
            here = trail + [child]
            if cls in _classes(child):
                return here
            found = walk(child, here)
            if found is not None:
                return found
        return None

    found = walk(path[-1], path)
    assert found is not None, f"no .{cls} under {path[-1].get('attrs')}"
    return found


def _bootTree(name: str) -> dict[str, Any]:
    """The post-JS DOM tree for fixture ``name`` (resolve it against any sheet)."""
    fx = _fixture(name)
    dom = rh.runDashboard(
        routes={"/obd-live": fx["obd-live"]}, nowMs=_ms(fx["now"]), steps=[{"flush": 4}]
    )
    return dom["tree"]


def _boot(name: str) -> rh.Surface:
    return rh.dashboardSurface(_bootTree(name))


def _engineRules() -> list[tuple[str, str]]:
    """Every dashboard.css rule that styles the Engine card or, since US-889-d,
    its ENGINE HISTORY detail (comments stripped)."""
    return [
        (rule.selector.strip(), rule.declarations)
        for rule in rh.parseCss(_read(DASHBOARD_CSS))
        if "#engine-card" in rule.selector or "#engine-detail" in rule.selector
        or ".eng-" in rule.selector
    ]


def _rule(selector: str) -> str:
    bodies = [body for sel, body in _engineRules() if sel == selector]
    assert bodies, f"no rule {selector!r}"
    return " ".join(bodies)


def _decl(body: str, prop: str) -> str | None:
    found = rh.declarationOf(body, prop)
    return None if found is None else found[0]


def _scopedVars() -> dict[str, str]:
    """The Engine's scoped properties: the card's and, since US-889-d, the
    ENGINE HISTORY detail's (#engine-detail). The names do not collide."""
    block = _rule("#engine-card") + " " + _rule("#engine-detail")
    return {
        name: value.strip() for name, value in re.findall(r"(--eng-[\w-]+)\s*:\s*([^;]+);", block)
    }


def _px(value: str) -> float:
    """Resolve a length to px through the scoped block and the token scale."""
    value = value.strip()
    var = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if var:
        name = var.group(1)
        scoped = _scopedVars()
        if name in scoped:
            return _px(scoped[name])
        scale = scaleValues(readCss(DASHBOARD_CSS))
        if name[2:] in scale:
            return float(scale[name[2:]])
        root = re.search(rf"^\s*{re.escape(name)}:\s*([0-9.]+)px", _read(DASHBOARD_CSS), re.M)
        assert root is not None, f"{name} does not resolve to px"
        return float(root.group(1))
    match = re.fullmatch(r"([0-9.]+)px", value)
    assert match is not None, f"{value!r} is not a px length"
    return float(match.group(1))


def _number(value: str) -> float:
    var = re.fullmatch(r"var\((--eng-[\w-]+)\)", value.strip())
    return float(_scopedVars()[var.group(1)] if var else value)


# ---------------------------------------------------------------------------
# 1. The slot -- index 1, right after Driving (E-2).
# ---------------------------------------------------------------------------


def test_cardOrder_engineSitsRightAfterDriving():
    labels = re.findall(r'<section class="card"[^>]*?aria-label="([^"]+)"', _read(_HTML), re.S)
    assert labels == CARD_ORDER


def test_engineCard_isNamedEngine_andCarriesNoPollOrLandingMachinery():
    # MOVED PIN (US-896-a): the NAV card took index 1, so Engine is index 2.
    tag = _sectionTags(_read(_HTML))[2]
    assert 'id="engine-card"' in tag
    assert 'aria-label="Engine"' in tag
    assert 'data-page-name="ENGINE"' in tag
    # The card reads the tick's cached obd-live; the generic availability poll
    # must not gray it, and it is not the landing card or the home slot.
    for attr in ("data-state", "data-landing", "data-idle-home", "data-face", "data-vehicle-gated"):
        assert attr not in tag, attr


def test_engineFacts_doNotUseTheTileClass():
    """The 4-fact ceiling counts `.tile` (test_carousel_card_set.py); layout B
    is not a tile grid and must not spend that budget."""
    assert not re.search(r'class="[^"]*\btile\b', _engineMarkup())


# ---------------------------------------------------------------------------
# 2. Units -- canonical keys only (Atlas G1).
# ---------------------------------------------------------------------------


@_NODE_ONLY
@pytest.mark.parametrize(
    ("value", "unit", "text", "shown"),
    [
        (88, "C", "190", "°F"),
        (64, "km/h", "40", "mph"),
        (14.06, "V", "14.1", "V"),
        (16.24, "g/s", "16.2", "g/s"),
        (22, "deg", "22", "°"),
        (71.4, "%", "71", "%"),
        (3, "count", "3", ""),
        (12, "X", "12", "X"),
    ],
)
def test_displayUnits_canonicalKeys(value: float, unit: str, text: str, shown: str):
    assert _probe("displayUnits", value, unit) == {"text": text, "unit": shown}


def test_displayUnits_keysAreExactlyTheCanonicalSet():
    js = _read(_JS)
    start = js.index("var DISPLAY_UNITS = {")
    block = js[start : js.index("\n  };", start)]
    keys = re.findall(r'^\s*(?:"([^"]+)"|([A-Za-z_]\w*))\s*:\s*\{', block, re.M)
    assert sorted(a or b for a, b in keys) == sorted(
        ["C", "F", "km/h", "mph", "V", "rpm", "%", "deg", "g/s", "count"]
    )


# python-obd's unit NAMES (obd2db realtime_data, US-888-b). The provider maps
# them to canonical units once; the page must never learn them.
_PYTHON_OBD_UNITS = re.compile(
    r"degree_Celsius|kilometer_per_hour|revolutions_per_minute|\bvolt\b|\bpercent\b"
    r"|\bgps\b|[\"']degree[\"']"
)


def test_carouselJs_namesNoPythonObdUnit():
    code = _stripJsComments(_read(_JS))
    assert _PYTHON_OBD_UNITS.findall(code) == []


def test_pythonObdUnitGate_catchesAPlantedKey():
    planted = 'var X = { percent: { unit: "%" }, "degree_Celsius": 1, volt: 2, gps: 3 };'
    assert len(_PYTHON_OBD_UNITS.findall(planted)) == 4


def test_displayUnits_isStillTheOnlyConversion():
    code = _read(_JS)
    assert code.count("function displayUnits(") == 1
    assert len(re.findall(r"9\s*/\s*5|\b1\.8\b", code)) == 1, "a second C->F conversion"


# ---------------------------------------------------------------------------
# 3. Values -- every fixture, through the view and through the shipped DOM.
# ---------------------------------------------------------------------------


def test_thisStorysFixturesArePresent():
    for name in FIXTURE_NAMES:
        assert os.path.isfile(os.path.join(_FIXTURES, name + ".json")), name


# (pid -> (text, unit, stale, note)) per fixture, from the provider data.
EXPECTED: dict[str, dict[str, tuple[str, str, bool, str]]] = {
    "idle-warm": {
        "ENGINE_LOAD": ("21", "%", False, ""),
        "THROTTLE_POS": ("15", "%", False, ""),
        "TIMING_ADVANCE": ("12", "° BTDC", False, ""),
    },
    "wot-pull-load-100": {
        "ENGINE_LOAD": ("100", "%", False, ""),
        "THROTTLE_POS": ("98", "%", False, ""),
        "TIMING_ADVANCE": ("22", "° BTDC", False, ""),
    },
    "not-read-with-reason": {
        "ENGINE_LOAD": ("35", "%", False, ""),
        "THROTTLE_POS": ("--", "", False, "not read"),
        "TIMING_ADVANCE": ("--", "", False, "not read"),
    },
    "stale": {
        "ENGINE_LOAD": ("71", "%", True, "12 s"),
        "THROTTLE_POS": ("48", "%", True, "12 s"),
        "TIMING_ADVANCE": ("4", "° ATDC", True, "12 s"),
    },
}

# (pid -> (fill %, stale)) per fixture; fill None = nothing lit.
EXPECTED_BARS: dict[str, dict[str, tuple[float | None, bool]]] = {
    "idle-warm": {"ENGINE_LOAD": (21.2, False), "THROTTLE_POS": (14.9, False)},
    "wot-pull-load-100": {"ENGINE_LOAD": (100.0, False), "THROTTLE_POS": (98.4, False)},
    "not-read-with-reason": {"ENGINE_LOAD": (34.5, False), "THROTTLE_POS": (None, False)},
    "stale": {"ENGINE_LOAD": (71.0, True), "THROTTLE_POS": (48.2, True)},
}


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_engineView_readingsMatchTheProvider(name: str):
    readings = _view(name)["readings"]
    for pid, (text, unit, stale, note) in EXPECTED[name].items():
        got = readings[pid]
        assert (got["text"], got["unit"], got["stale"], got["note"]) == (
            text, unit, stale, note
        ), (name, pid, got)


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_engineView_barsAreTheSameSampleAsTheNumber(name: str):
    bars = _view(name)["bars"]
    for pid, (fill, stale) in EXPECTED_BARS[name].items():
        assert (bars[pid]["fill"], bars[pid]["stale"]) == (fill, stale), (name, pid)


@_NODE_ONLY
def test_engineView_carriesNoBand_loadAt100IsNeutral():
    """Load is never coloured on its own (spec s4): 100 % at WOT is expected on
    this turbo engine. The view has no band field for the page to paint."""
    view = _view("wot-pull-load-100")
    for pid in ENGINE_PIDS:
        assert "band" not in view["readings"][pid], pid


@_NODE_ONLY
@pytest.mark.parametrize(
    ("value", "expected"),
    [(22.0, "22° BTDC"), (-4.0, "4° ATDC"), (0.0, "0° BTDC"), (-12.5, "13° ATDC")],
)
def test_timing_isSignedAsBtdcOrAtdc_neverANegativeBtdc(value: float, expected: str):
    view = _probe("engineView", {"params": {"TIMING_ADVANCE": _param(value)}}, 0)
    timing = view["readings"]["TIMING_ADVANCE"]
    assert timing["text"] + timing["unit"] == expected
    assert "-" not in timing["text"]


@_NODE_ONLY
def test_timing_22Then_minus4():
    """Validation row: TIMING_ADVANCE 22 then -4 -> '22° BTDC', then '4° ATDC'."""
    shown = []
    for value in (22, -4):
        r = _probe("engineView", {"params": {"TIMING_ADVANCE": _param(value)}}, 0)
        shown.append(r["readings"]["TIMING_ADVANCE"]["text"] + r["readings"]["TIMING_ADVANCE"]["unit"])
    assert shown == ["22° BTDC", "4° ATDC"]


@_NODE_ONLY
def test_timing_inAnUnknownUnit_rendersRaw_withoutClaimingTdc():
    view = _probe("engineView", {"params": {"TIMING_ADVANCE": _param(-4, "X")}}, 0)
    timing = view["readings"]["TIMING_ADVANCE"]
    assert (timing["text"], timing["unit"]) == ("-4", "X")


@_NODE_ONLY
def test_bar_isClampedTo0to100_andEmptyForANonPercentUnit():
    params = {"ENGINE_LOAD": _param(104.0, "%"), "THROTTLE_POS": _param(40.0, "X")}
    bars = _probe("engineView", {"params": params}, 0)["bars"]
    assert bars["ENGINE_LOAD"]["fill"] == 100
    assert bars["THROTTLE_POS"]["fill"] is None


@_NODE_ONLY
def test_engineView_noObdLive_isDashDashWithAReason_never0():
    view = _probe("engineView", None, 0)
    for pid in ENGINE_PIDS:
        r = view["readings"][pid]
        assert (r["text"], r["stale"], r["note"]) == ("--", False, "no source"), pid
    for pid in BAR_PIDS:
        assert view["bars"][pid]["fill"] is None


@_NODE_ONLY
def test_engineView_staleWithNoLastValue_isDashDashWithTheReason():
    param = _param(None, "%", stale=True, noBandReason="stale")
    r = _probe("engineView", {"params": {"ENGINE_LOAD": param}}, 0)["readings"]["ENGINE_LOAD"]
    assert (r["text"], r["note"], r["noteKind"]) == ("--", "stale", "reason")


def _bootLiveTree(obdLive: dict[str, Any] | None, nowMs: int = 0) -> dict[str, Any]:
    routes = {"/obd-live": obdLive} if obdLive is not None else {}
    return rh.runDashboard(routes=routes, nowMs=nowMs, steps=[{"flush": 4}])["tree"]


def _bootLive(obdLive: dict[str, Any] | None, nowMs: int = 0) -> rh.Surface:
    return rh.dashboardSurface(_bootLiveTree(obdLive, nowMs))


def _copies(col: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """A bar's two value copies by role: 'track' (under the fill) and 'fill'."""
    return {"track": _child(col, "eng-on-track"), "fill": _child(col, "eng-on-fill")}


def _fillPct(fill: list[dict[str, Any]]) -> float:
    width = ((fill[-1].get("style") or {}).get("width") or "").strip()
    match = re.fullmatch(r"([0-9.]+)%", width)
    assert match is not None, width
    return float(match.group(1))


def _clipRightPct(copy: list[dict[str, Any]]) -> float:
    """The --bg copy's clip, inset(0 calc(100% - F%) 0 0), as its right inset in %."""
    clip = ((copy[-1].get("style") or {}).get("clip-path") or "").strip()
    match = re.fullmatch(r"inset\(0 calc\(100% - ([0-9.]+)%\) 0 0\)", clip)
    assert match is not None, clip
    return 100 - float(match.group(1))


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_theShippedDomPaintsTheView(name: str):
    """MOVED PIN (US-889-e): the bars carry their readings now -- the value in
    BOTH copies, the note on the header line, the fill as a WIDTH (was the
    vertical fill's height, :500-503); TIMING alone is an .eng-reading."""
    view = _view(name)
    surface = _boot(name)
    r = view["readings"]["TIMING_ADVANCE"]
    path = _byPid(surface, "eng-reading", "TIMING_ADVANCE")
    attrs = path[-1]["attrs"]
    assert _textOf(_child(path, "eng-value")[-1]) == r["text"], name
    assert _textOf(_child(path, "eng-unit")[-1]) == r["unit"], name
    note = _child(path, "eng-note")
    assert _textOf(note[-1]) == r["note"], name
    assert surface.rendered(note) == bool(r["note"]), (name, "note box")
    assert attrs.get("data-stale") == ("true" if r["stale"] else "false"), name
    assert attrs.get("data-note") == (r["noteKind"] or "none"), name
    for pid in BAR_PIDS:
        r, bar = view["readings"][pid], view["bars"][pid]
        col = _byPid(surface, "eng-bar-col", pid)
        attrs = col[-1]["attrs"]
        assert attrs.get("data-stale") == ("true" if r["stale"] else "false"), (name, pid)
        assert attrs.get("data-note") == (r["noteKind"] or "none"), (name, pid)
        assert attrs.get("data-null") == ("true" if r["text"] == "--" else "false"), (name, pid)
        note = _child(_child(col, "eng-bar-head"), "eng-note")
        assert _textOf(note[-1]) == r["note"], (name, pid)
        assert surface.rendered(note) == bool(r["note"]), (name, pid, "note box")
        for role, copy in _copies(col).items():
            assert _textOf(_child(copy, "eng-value")[-1]) == r["text"], (name, pid, role)
            assert _textOf(_child(copy, "eng-unit")[-1]) == r["unit"], (name, pid, role)
        fill = _child(col, "eng-bar-fill")
        if bar["fill"] is None:
            assert not surface.rendered(fill), (name, pid, "a null fill is drawn")
            assert not surface.rendered(_copies(col)["fill"]), (name, pid)
        else:
            assert surface.rendered(fill), (name, pid)
            assert _fillPct(fill) == pytest.approx(bar["fill"]), (name, pid)
            assert _clipRightPct(_copies(col)["fill"]) == pytest.approx(100 - bar["fill"])


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_timingBasis_isOnTheGlass_andTheCueIsGone_inEveryFixture(name: str):
    """MOVED PIN (US-889-d, spec s3a): was ..._andScrollCue_areOnTheGlass_...
    -- the page no longer scrolls, so the cue is deleted."""
    surface = _boot(name)
    basis = _enginePaths(surface, "eng-basis")
    assert len(basis) == 1 and _textOf(basis[0][-1]) == TIMING_BASIS
    assert surface.rendered(basis[0])
    assert _enginePaths(surface, "eng-cue") == []


def test_theCueAndItsArrow_areDeleted_grep():
    """US-889-d AC: no .eng-cue and no '↓' remain in the Engine markup or rules."""
    markup = re.sub(r"<!--.*?-->", "", _engineMarkup(), flags=re.S)
    assert "eng-cue" not in markup and "↓" not in markup
    assert RETIRED_CUE not in _read(_HTML)
    assert all("eng-cue" not in sel for sel, _ in _engineRules())


# US-889-e AC-e: the vertical bars' column and the separate readings column
# (and their geometry) are gone; the value lives in the bar.
_RETIRED_GLANCE = (
    "eng-main", "eng-bars", "eng-readings", "eng-pair", "--eng-bar-w", "--eng-bars-gap",
)


def _mentions(text: str, name: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) is not None


def test_theReadingsColumn_isGone_grep():
    markup = re.sub(r"<!--.*?-->", "", _engineMarkup(), flags=re.S)
    css = rh._stripComments(_read(DASHBOARD_CSS))
    js = _stripJsComments(_read(_JS))
    for name in _RETIRED_GLANCE:
        assert not _mentions(markup, name), name
        assert not _mentions(css, name), name
        assert not _mentions(js, name), name
    # Each bar PID has exactly one home on the card: its gauge.
    for pid in BAR_PIDS:
        assert markup.count(f'data-pid="{pid}"') == 1, pid
    # The only .eng-reading left is TIMING, in the footer.
    assert re.findall(r'class="eng-reading[^"]*"\s+data-pid="(\w+)"', markup) == ["TIMING_ADVANCE"]
    assert markup.index('class="eng-foot"') < markup.index('class="eng-reading')


def test_retiredGlanceGate_catchesAPlantedColumn():
    assert _mentions('<div class="eng-readings">', "eng-readings")
    assert not _mentions('<div class="eng-reading">', "eng-readings")


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_valuesAreNeutral_andBarsAreAccent(name: str):
    """MOVED PIN (US-889-e): a bar's value takes its copy's colour -- warm white
    over the track, --bg over the fill, the tertiary ink for '--'; TIMING is
    unchanged."""
    surface = _boot(name)
    view = _view(name)
    timing = _child(_byPid(surface, "eng-reading", "TIMING_ADVANCE"), "eng-value")
    assert surface.winningDeclaration(timing, "color")[0] == "var(--text-primary)", name
    for pid in BAR_PIDS:
        col = _byPid(surface, "eng-bar-col", pid)
        fill = _child(col, "eng-bar-fill")
        assert surface.winningDeclaration(fill, "background-color")[0] == "var(--accent)"
        copies = _copies(col)
        assert surface.winningDeclaration(copies["track"], "color")[0] == "var(--text-primary)"
        assert surface.winningDeclaration(copies["fill"], "color")[0] == "var(--bg)"
        for role, copy in copies.items():
            unit = surface.winningDeclaration(_child(copy, "eng-unit"), "color")[0]
            assert unit == "inherit", (name, pid, role)
        assert surface.winningDeclaration(_child(copies["fill"], "eng-value"), "color")[0] == "inherit"
        unread = view["readings"][pid]["text"] == "--"
        value = surface.winningDeclaration(_child(copies["track"], "eng-value"), "color")[0]
        assert value == ("var(--text-tertiary)" if unread else "inherit"), (name, pid, value)


@_NODE_ONLY
def test_staleReading_isDimmed_andItsAgeIsAmber_reasonIsNot():
    """MOVED PIN (US-889-e AC-g): the data-stale hook moved to the bar row --
    the bar and the value inside it dim; the age on the header line stays
    amber and undimmed."""
    surface = _boot("stale")
    col = _byPid(surface, "eng-bar-col", "ENGINE_LOAD")
    barOpacity = surface.winningDeclaration(_child(col, "eng-bar"), "opacity")
    assert barOpacity is not None and _number(barOpacity[0]) == pytest.approx(0.4)
    assert surface.winningDeclaration(col, "opacity") is None, "the header is dimmed"
    head = _child(col, "eng-bar-head")
    assert surface.winningDeclaration(_child(head, "eng-note"), "color")[0] == "var(--amber-warn)"
    path = _byPid(surface, "eng-reading", "TIMING_ADVANCE")
    opacity = surface.winningDeclaration(_child(path, "eng-line"), "opacity")
    assert opacity is not None and _number(opacity[0]) == pytest.approx(0.4)
    assert surface.winningDeclaration(_child(path, "eng-note"), "color")[0] == "var(--amber-warn)"
    fresh = _boot("idle-warm")
    freshBar = _child(_byPid(fresh, "eng-bar-col", "ENGINE_LOAD"), "eng-bar")
    assert fresh.winningDeclaration(freshBar, "opacity") is None
    line = _child(_byPid(fresh, "eng-reading", "TIMING_ADVANCE"), "eng-line")
    assert fresh.winningDeclaration(line, "opacity") is None
    unread = _boot("not-read-with-reason")
    head = _child(_byPid(unread, "eng-bar-col", "THROTTLE_POS"), "eng-bar-head")
    assert unread.winningDeclaration(_child(head, "eng-note"), "color")[0] == "var(--text-secondary)"


@_NODE_ONLY
def test_stale_and_notRead_onTheBars_AC_g():
    """AC-g: stale -> the bar keeps its last fill, dimmed, the age right on the
    header; not read -> empty track, ONE '--' in the tertiary ink, the reason
    right on the header, and never a 0 % fill."""
    stale = _boot("stale")
    for pid in BAR_PIDS:
        col = _byPid(stale, "eng-bar-col", pid)
        assert col[-1]["attrs"]["data-stale"] == "true"
        assert stale.rendered(_child(col, "eng-bar-fill"))
        note = _child(_child(col, "eng-bar-head"), "eng-note")
        assert _textOf(note[-1]) == "12 s" and stale.rendered(note)
    unread = _boot("not-read-with-reason")
    col = _byPid(unread, "eng-bar-col", "THROTTLE_POS")
    assert col[-1]["attrs"]["data-null"] == "true"
    assert not unread.rendered(_child(col, "eng-bar-fill")), "a null reading drew a fill"
    copies = _copies(col)
    assert unread.rendered(copies["track"]) and not unread.rendered(copies["fill"])
    assert _textOf(copies["track"][-1]) == "--"
    note = _child(_child(col, "eng-bar-head"), "eng-note")
    assert _textOf(note[-1]) == "not read" and unread.rendered(note)
    # The header line: the label left, the note pushed right.
    head = _rule("#engine-card .eng-bar-head")
    assert _decl(head, "display") == "flex"
    assert _decl(head, "justify-content") == "space-between"
    assert _decl(_rule("#engine-card .eng-note"), "font-size") == "var(--fs-meta)"
    # LOAD in the same fixture IS read: its fill is drawn.
    load = _byPid(unread, "eng-bar-col", "ENGINE_LOAD")
    assert unread.rendered(_child(load, "eng-bar-fill"))


def test_theEngineRenderReadsTheTicksObdLive():
    js = _read(_JS)
    assert re.search(r"renderEngineCard\(\s*engineCard,\s*engineView\(", js)
    assert 'document.getElementById("engine-card")' in js


# ---------------------------------------------------------------------------
# 4. Type.
# ---------------------------------------------------------------------------


def test_load_isFsHero_throttleAndTiming_areFsPrimary_allMonoTabular():
    assert _decl(_rule("#engine-card .eng-value"), "font-size") == "var(--fs-primary)"
    assert _decl(_rule("#engine-card .eng-load .eng-value"), "font-size") == "var(--fs-hero)"
    for selector in ("#engine-card .eng-value", "#engine-card .eng-unit", "#engine-card .eng-note"):
        assert _decl(_rule(selector), "font-family") == "var(--font-mono)", selector
    assert _decl(_rule("#engine-card .eng-value"), "font-variant-numeric") == "tabular-nums"
    assert _px("var(--fs-primary)") >= 34


def test_unitsAreNeverInTheLabelFont():
    """The degree glyph is not in the Michroma subset; a unit in the label font
    would fall back to another face."""
    for selector, body in _engineRules():
        if "eng-unit" in selector or "eng-basis" in selector:
            assert "var(--font-display)" not in body, selector


def test_labels_areMichroma_atFsMeta_letterSpacingZero():
    body = _rule("#engine-card .eng-label")
    assert _decl(body, "font-family") == "var(--font-display)"
    assert _decl(body, "font-weight") == "400"
    assert _decl(body, "font-synthesis") == "none"
    assert _decl(body, "font-size") == "var(--fs-meta)"
    assert _decl(body, "letter-spacing") == "0"
    labels = re.findall(r'<span class="eng-label">([^<]+)</span>', _engineMarkup())
    # MOVED PIN (US-889-e): one label per value -- the bar headers and TIMING.
    assert labels == ["LOAD", "THROTTLE", "TIMING"]
    for text in labels:
        michromaWidthPx(text, 15)  # raises on a glyph outside the subset


def test_noEngineRuleSetsAFontBelow15px():
    for selector, body in _engineRules():
        size = _decl(body, "font-size")
        if size is not None:
            assert _px(size) >= 15, (selector, size)


# ---------------------------------------------------------------------------
# 5. The CSS gate -- tokens only; px only in the one scoped block.
# ---------------------------------------------------------------------------

_COLOUR_LITERAL = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(|(?<![\w-])(?:white|black|red|orange)(?![\w-])"
)
_PX_LITERAL = re.compile(r"(?<![\w-])[0-9.]+px\b")


# MOVED PIN (US-889-d): the history + status render in the ENGINE HISTORY
# detail, #engine-detail, whose geometry is scoped to it (spec s3b) -- the
# card's --eng-* would not reach the shared host. Two scopes, one rule each.
_SCOPES = ("#engine-card", "#engine-detail")


def _gateViolations(rules: list[tuple[str, str]]) -> list[str]:
    bad = []
    for selector, body in rules:
        if not any(scope in selector for scope in _SCOPES):
            bad.append(f"{selector}: an Engine rule not scoped to #engine-card / #engine-detail")
        if _COLOUR_LITERAL.search(body):
            bad.append(f"{selector}: literal colour")
        if selector in _SCOPES:
            for decl in filter(None, (d.strip() for d in body.split(";"))):
                if not decl.startswith("--eng-"):
                    bad.append(f"{selector}: {decl} is not a scoped --eng- property")
        elif _PX_LITERAL.search(body):
            bad.append(f"{selector}: literal px outside the scoped blocks")
        if re.search(r"\b(?:animation|transition)\s*:", body) and not re.search(
            r"\[data-[\w-]+=\"[^\"]+\"\]", selector
        ):
            bad.append(f"{selector}: animation must be state-qualified")
    return bad


def test_cssGate_tokensOnly_pxOnlyInTheScopedBlock():
    rules = _engineRules()
    assert len(rules) > 5, "the Engine rules were not found"
    assert _gateViolations(rules) == []


def test_cssGate_catchesAPlantedLiteral():
    planted = _engineRules() + [
        ("#engine-card .eng-value", "margin-top: 4px; color: #fff"),
        ("#engine-card .eng-bar-fill", "transition: width 0.2s"),
    ]
    assert len(_gateViolations(planted)) == 3


def test_everyScopedPropertyIsConsumed():
    css = rh._stripComments(_read(DASHBOARD_CSS))
    for name in _scopedVars():
        assert f"var({name})" in css, f"{name} is declared and never used"


def test_layoutGeometry_isNotInRoot():
    root = re.search(r":root\s*\{(.*?)\}", rh._stripComments(_read(DASHBOARD_CSS)), re.S)
    assert root is not None and "--eng-" not in root.group(1)


def test_barGeometry_isFullWidthBy48():
    """MOVED PIN (US-889-e): was test_barGeometry_is26x168 -- the bars are
    horizontal now, the body's full width by --eng-bar-h 48 px."""
    bar = _rule("#engine-card .eng-bar")
    assert _decl(bar, "width") == "100%"
    assert _px(_decl(bar, "height") or "") == 48
    assert _decl(bar, "overflow") == "hidden"


# ---------------------------------------------------------------------------
# 6. Fit -- the whole glance at 480x320 (no scrolling, no clipping).
#    US-889-d, Q1 RULED by Atlas (S119 gate 2026-10-27): a MODELLED budget from
#    the DECLARED rules (never copied literals), every term counted, each line
#    charged its declared line-height (never `normal`), widths from the
#    Michroma advances and the Pi's mono advance, against the body's 254.
#    MOVED PIN (US-889-e): the vertical-bar model (bar column widths, the
#    readings column, the bar-height term) is REPLACED by the horizontal
#    re-lay: two gauges (header + bar) then the footer, AC-d's geometry.
# ---------------------------------------------------------------------------


def _bodyHeightPx() -> float:
    css = _read(DASHBOARD_CSS)

    def token(name: str) -> float:
        m = re.search(rf"^\s*--{name}:\s*([0-9.]+)px", css, re.M)
        assert m is not None, name
        return float(m.group(1))

    return 320 - token("bar-h") - token("dots-h") - 2 * token("card-pad-y")


def _bodyWidthPx() -> float:
    pad = re.search(r"padding:\s*var\(--card-pad-y\)\s+([0-9.]+)px", _read(DASHBOARD_CSS))
    assert pad is not None
    return 480 - 2 * float(pad.group(1))


def _lineBox(size: str, line: str) -> float:
    """A line box: a unitless factor times the size, or an absolute length."""
    if re.fullmatch(r"var\(--eng-bar-h\)|[0-9.]+px", line.strip()):
        return _px(line)
    return _px(size) * _number(line)


def _monoWidth(text: str, sizeVar: str) -> float:
    return len(text) * _px(sizeVar) * PI_MONO_ADVANCE_EM


def _meta() -> str:
    return "var(--fs-meta)"


# Every rule whose line box the glance model charges. Each must declare an
# explicit line-height token (the Pi renders the mono stack in Liberation
# Mono, 30 px at 26 px under `normal`; the bench renders Consolas). The two
# in-bar value copies declare the BAR's height (Atlas gate 2026-10-27).
_CHARGED = {
    "#engine-card .eng-label": "var(--eng-line)",
    "#engine-card .eng-line": "var(--eng-line)",
    "#engine-card .eng-note": "var(--eng-line)",
    "#engine-card .eng-basis": "var(--eng-line)",
    "#engine-card .eng-bar-text": "var(--eng-bar-h)",
    "#engine-card .eng-bar-text .eng-unit": "var(--eng-line)",
}


# US-889-f AC-1: TIMING's label line, 'TIMING' left and its note right.
_TIMING_HEAD_CLASS = "eng-timing-head"
_TIMING_HEAD = "#engine-card .eng-timing-head"


def test_everyChargedLine_declaresALineHeightToken_neverNormal():
    for selector, token in _CHARGED.items():
        line = _decl(_rule(selector), "line-height")
        assert line == token, (selector, line)
    assert _number("var(--eng-line)") > 1


def _label() -> float:
    return _lineBox(_meta(), _decl(_rule("#engine-card .eng-label"), "line-height") or "")


def _barHeight() -> float:
    return _px(_decl(_rule("#engine-card .eng-bar"), "height") or "")


def _barWidth() -> float:
    """The bar fills its gauge, which fills the body (a column flex child)."""
    assert _decl(_rule("#engine-card .eng-bar"), "width") == "100%"
    assert _decl(_rule("#engine-card .eng-gauges"), "flex-direction") == "column"
    assert _decl(_rule("#engine-card .eng-bar-col"), "flex-direction") == "column"
    return _bodyWidthPx()


def _gaugeHeight(head: float | None = None, barH: float | None = None) -> float:
    """Header line (``head``, default the label alone) + the header gap + the bar."""
    gap = _px(_decl(_rule("#engine-card .eng-bar-col"), "gap") or "")
    return (head if head is not None else _label()) + gap + (barH if barH is not None else _barHeight())


# US-889-f AC-5 MODEL. Atlas MEASURED each .eng-bar-head at 21 px with its note
# shown under align-items: baseline (the Michroma label's rect top 42, the mono
# --fs-meta note's 45, both 18 tall: 18 -> 21, 2 x 3 = the 6 px of 260/254).
# Source: pm/inbox/2026-10-28-from-atlas-RULINGS-S120-scrollbars-inert-engine-
# 6px-is-bar-heads-C3-yes-with-cap-U4-a.md s2; evidence
# offices/architect/evidence/2026-10-28-scrollbar-gyro/.
_HEAD_BASELINE_MEASURED_PX = 21.0

# The 532b0830 header rule (V0.30.18), kept as text for the negative controls,
# and a planted `height: 18px` that keeps the baseline (Atlas review F1c: the
# 3 px offset survives and pushes the note out of the head box onto the bar).
_HEAD_RULE_532B0830 = (
    "#engine-card .eng-bar-head {\n"
    "  display: flex; align-items: baseline; justify-content: space-between;\n"
    "  gap: var(--eng-inline-gap); min-width: 0;\n"
    "}"
)
_HEAD_RULE_BARE_HEIGHT = (
    "#engine-card .eng-bar-head {\n"
    "  display: flex; align-items: baseline; justify-content: space-between;\n"
    "  gap: var(--eng-inline-gap); min-width: 0; height: 18px;\n"
    "}"
)
_HEAD_RULE_SHIPPED = re.compile(r"#engine-card \.eng-bar-head \{[^}]*\}")


def _cssWithHeadRule(rule: str) -> str:
    """The shipped sheet with its ONE .eng-bar-head rule replaced by ``rule``."""
    css = _read(DASHBOARD_CSS)
    assert len(_HEAD_RULE_SHIPPED.findall(css)) == 1
    return _HEAD_RULE_SHIPPED.sub(lambda _m: rule, css)


def _kids(path: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [path + [c] for c in path[-1].get("children", []) if "tag" in c]


def _winning(surface: rh.Surface, path: list[dict[str, Any]], prop: str) -> str:
    found = surface.winningDeclaration(path, prop)
    assert found is not None, (path[-1].get("attrs"), prop)
    return found[0]


def _headCharge(surface: rh.Surface, head: list[dict[str, Any]]) -> float:
    """A header line (label left, note right). The label alone is its line box.
    With the note shown it is charged that line box ONLY if its winning
    declarations hold it -- align-items not baseline, and every head child at
    line-height var(--eng-line) -- else Atlas's measured 21. A bare height keeps
    the baseline and is charged 21 too (Atlas review F1c)."""
    kids = _kids(head)
    shown = [k for k in kids if surface.rendered(k)]
    assert shown, "an empty header line"
    box = max(_lineBox(_winning(surface, k, "font-size"), _winning(surface, k, "line-height")) for k in shown)
    if len(shown) == 1:
        return box
    align = surface.winningDeclaration(head, "align-items")
    held = (align[0] if align else "normal") != "baseline" and all(
        (surface.winningDeclaration(k, "line-height") or ("",))[0] == "var(--eng-line)" for k in kids
    )
    return box if held else _HEAD_BASELINE_MEASURED_PX


def _barHeads(surface: rh.Surface) -> dict[str, list[dict[str, Any]]]:
    return {pid: _child(_byPid(surface, "eng-bar-col", pid), "eng-bar-head") for pid in BAR_PIDS}


def _noteShown(surface: rh.Surface, head: list[dict[str, Any]]) -> bool:
    return surface.rendered(_child(head, "eng-note"))


def _buttonHeight() -> float:
    """The shared detail button (US-894-g): its declared height, border-box."""
    rules = rh.parseCss(_read(DASHBOARD_CSS))
    body = " ".join(r.declarations for r in rules if r.selector.strip() == ".page-detail-btn")
    assert _decl(body, "box-sizing") == "border-box"
    return _px(_decl(body, "height") or "")


def _buttonWidth() -> float:
    """HISTORY ›: Michroma --fs-label + mono ' ›' + 12 px padding each side."""
    rules = rh.parseCss(_read(DASHBOARD_CSS))
    body = " ".join(r.declarations for r in rules if r.selector.strip() == ".page-detail-btn")
    pad = re.fullmatch(r"0\s+([0-9.]+)px", (_decl(body, "padding") or "").strip())
    assert pad is not None
    label = michromaWidthPx("HISTORY", _px("var(--fs-label)"))
    return label + _monoWidth(" ›", "var(--fs-label)") + 2 * float(pad.group(1))


def _footColumnWidth() -> float:
    """The TIMING stack: the footer's width less HISTORY › and their gap."""
    gap = _px(_decl(_rule("#engine-card .eng-foot"), "gap") or "")
    return _bodyWidthPx() - gap - _buttonWidth()


def _valueWidth(value: str, unit: str, sizeVar: str) -> float:
    """The number at its size, then the unit at --fs-label after its gap (the
    timing unit sits on the number: its own rule zeroes the gap)."""
    gap = _px(_decl(_rule("#engine-card .eng-unit"), "margin-inline-start") or "")
    if unit.startswith("°"):
        timing = _decl(_rule("#engine-card .eng-timing .eng-unit"), "margin-inline-start")
        gap = 0.0 if timing == "0" else _px(timing or "")
    width = _monoWidth(value, sizeVar)
    if unit:
        width += gap + _monoWidth(unit, "var(--fs-label)")
    return width


def _timingHeadWidth(note: str) -> float:
    """US-889-f: TIMING's label line -- 'TIMING' left, its note right."""
    gap = _px(_decl(_rule(_TIMING_HEAD), "gap") or "")
    return michromaWidthPx("TIMING", _px(_meta())) + gap + _monoWidth(note, _meta())


def _wrappedLines(text: str, sizeVar: str, col: float) -> int:
    """Greedy word wrap in the fixed-width face: how many lines ``text`` takes
    in ``col`` px. A single word wider than the column is a clip, not a wrap."""
    lines, line = 1, ""
    for word in text.split(" "):
        assert _monoWidth(word, sizeVar) <= col, (word, col)
        trial = f"{line} {word}" if line else word
        if _monoWidth(trial, sizeVar) <= col:
            line = trial
        else:
            lines, line = lines + 1, word
    return lines


def _footContentHeight(surface: rh.Surface) -> float:
    """MOVED PIN (US-889-f AC-3 MODEL): charged from the MARKUP -- one line box
    per rendered child row of .eng-timing, --eng-gap between rows. The retired
    'note wraps below the value' branch is gone: the note sits on the label
    line, so a 4th row (the 532b0830 shape) is charged as one and fails."""
    timing = _byPid(surface, "eng-reading", "TIMING_ADVANCE")
    rows = [k for k in _kids(timing) if surface.rendered(k)]
    rowGap = _px(_decl(_rule("#engine-card .eng-reading"), "row-gap") or "")
    height = rowGap * (len(rows) - 1)
    for row in rows:
        cls = _classes(row[-1])
        if _TIMING_HEAD_CLASS in cls:
            height += _headCharge(surface, row)
        elif "eng-line" in cls:
            height += _lineBox("var(--fs-primary)", _winning(surface, row, "line-height"))
        elif "eng-basis" in cls:
            lines = _wrappedLines(TIMING_BASIS, _meta(), _footColumnWidth())
            height += lines * _lineBox(_winning(surface, row, "font-size"), _winning(surface, row, "line-height"))
        elif "eng-label" in cls or "eng-note" in cls:
            height += _lineBox(_winning(surface, row, "font-size"), _winning(surface, row, "line-height"))
        else:
            raise AssertionError(f"an unmodelled TIMING row: {cls}")
    return height


def _footHeight() -> float:
    return _px(_decl(_rule("#engine-card .eng-foot"), "height") or "")


def _glanceHeight(surface: rh.Surface, barH: float | None = None) -> float:
    """MOVED PIN (US-889-f AC-5 MODEL): two gauges, each charged its header
    line (_headCharge), their gap, the body gap, then the footer -- the
    declared 96 unless its content (or the button) is taller."""
    gaugeGap = _px(_decl(_rule("#engine-card .eng-gauges"), "gap") or "")
    footGap = _px(_decl(_rule("#engine-card .card-body"), "gap") or "")
    foot = max(_footHeight(), _footContentHeight(surface), _buttonHeight())
    gauges = sum(_gaugeHeight(_headCharge(surface, head), barH) for head in _barHeads(surface).values())
    return gauges + gaugeGap + footGap + foot


# The fit cases (story AC): wot-pull-load-100, not-read-with-reason, the
# inline negative-timing case (TIMING_ADVANCE -40), plus stale (every note).
_NEGATIVE_TIMING = {"params": {"TIMING_ADVANCE": _param(-40.0)}}

# US-889-f AC-5: Atlas's state A (real car-off, all three notes), which no
# fixture holds -- LOAD, THROTTLE and TIMING all not_read, built in memory
# (fixtures/states is never-edit, Atlas review F1).
_ALL_UNREAD = {
    "params": {
        pid: _param(None, "deg" if pid == "TIMING_ADVANCE" else "%", noBandReason="not_read")
        for pid in ENGINE_PIDS
    }
}


def _fitSurfaces() -> dict[str, rh.Surface]:
    surfaces = {name: _boot(name) for name in ("wot-pull-load-100", "not-read-with-reason", "stale")}
    surfaces["timing-minus-40"] = _bootLive(_NEGATIVE_TIMING)
    surfaces["all-unread"] = _bootLive(_ALL_UNREAD)
    return surfaces


@_NODE_ONLY
def test_glance_fitsTheBody_inEveryFitCase():
    """MOVED PIN (US-889-e, US-889-f): US-889-d's glance budget, re-modelled for
    the horizontal re-lay, now over the painted DOM. The footer content charges
    AC-d's 88.8 of 96 (TIMING label line at --fs-meta) in EVERY case."""
    body = _bodyHeightPx()
    assert body == 254
    surfaces = _fitSurfaces()
    timing = _child(_byPid(surfaces["timing-minus-40"], "eng-reading", "TIMING_ADVANCE"), "eng-value")
    assert _textOf(timing[-1]) == "40"
    for name, surface in surfaces.items():
        assert _footContentHeight(surface) == pytest.approx(88.8), name
        assert _footContentHeight(surface) <= _footHeight(), name
        height = _glanceHeight(surface)
        assert height <= body, (name, height, body)
    assert _buttonHeight() <= _footHeight()
    # No scroll, so no cue: nothing on the card points below the fold.
    assert "↓" not in re.sub(r"<!--.*?-->", "", _engineMarkup(), flags=re.S)


@_NODE_ONLY
def test_heightModel_failsAPlantedTallBar():
    """The negative control: a bar that no longer fits fails the same model."""
    surface = _boot("wot-pull-load-100")
    assert _glanceHeight(surface) <= _bodyHeightPx()
    assert _glanceHeight(surface, barH=54) > _bodyHeightPx()


def _plantNoteRow(tree: dict[str, Any]) -> dict[str, Any]:
    """The 532b0830 shape: TIMING's label line unwrapped and its .eng-note
    planted back as its own row after the value (label / value / note / caption)."""
    planted = json.loads(json.dumps(tree))
    timing = _byPid(rh.dashboardSurface(planted), "eng-reading", "TIMING_ADVANCE")[-1]
    kids = [c for c in timing["children"] if "tag" in c]
    head = next(c for c in kids if _TIMING_HEAD_CLASS in _classes(c))
    label, note = [c for c in head["children"] if "tag" in c]
    line = next(c for c in kids if "eng-line" in _classes(c))
    basis = next(c for c in kids if "eng-basis" in _classes(c))
    timing["children"] = [label, line, note, basis]
    return planted


@_NODE_ONLY
def test_heightModel_failsAPlantedOverflowingFooter():
    """MOVED PIN (US-889-f AC-3): the 'wide note wraps below the number' premise
    is retired. The negative control is the 532b0830 shape -- .eng-note planted
    back as its own 4th row: 88.8 + 6 + 18 = 112.8 > 96, and the same budget
    FAILS."""
    tree = _bootTree("not-read-with-reason")
    shipped = rh.dashboardSurface(tree)
    planted = rh.dashboardSurface(_plantNoteRow(tree))
    rows = _kids(_byPid(planted, "eng-reading", "TIMING_ADVANCE"))
    assert [_classes(r[-1])[0] for r in rows] == ["eng-label", "eng-line", "eng-note", "eng-basis"]
    assert planted.rendered(rows[2]), "the planted note row is not drawn"
    assert _footContentHeight(shipped) == pytest.approx(88.8)
    assert _footContentHeight(planted) == pytest.approx(112.8)
    assert _footContentHeight(planted) > _footHeight()
    assert _glanceHeight(planted) > _bodyHeightPx()


# The planted all-unread view, the stale fixture and not-read-with-reason:
# which bar heads show a note, and what the 532b0830 baseline rule costs.
_NOTED_HEADS = {
    "stale": ("ENGINE_LOAD", "THROTTLE_POS"),
    "all-unread": ("ENGINE_LOAD", "THROTTLE_POS"),
    "not-read-with-reason": ("THROTTLE_POS",),
}
_BASELINE_GLANCE = {"stale": 260.0, "all-unread": 260.0, "not-read-with-reason": 257.0}


@_NODE_ONLY
def test_engineGlance_barHeadsHold18px_withNotesShown_fitsInStaleAndNotRead():
    """EXIT TEST (US-889-f AC-5): through the AC-5 model, each .eng-bar-head
    with its note rendered is charged 18 px and each glance <= 254, for fixture
    `stale`, the in-memory all-unread view and `not-read-with-reason`.
    NEGATIVE CONTROLS (Atlas review F1 / F1c): the 532b0830 baseline rule gives
    260 / 260 / 257, and a bare `height: 18px` that keeps the baseline is
    charged 21 per head and fails the same way. FAILS on 532b0830."""
    body = _bodyHeightPx()
    trees = {
        "stale": _bootTree("stale"),
        "all-unread": _bootLiveTree(_ALL_UNREAD),
        "not-read-with-reason": _bootTree("not-read-with-reason"),
    }
    for name, tree in trees.items():
        surface = rh.dashboardSurface(tree)
        heads = _barHeads(surface)
        noted = tuple(pid for pid, head in heads.items() if _noteShown(surface, head))
        assert noted == _NOTED_HEADS[name], name
        for pid, head in heads.items():
            assert _headCharge(surface, head) == pytest.approx(18), (name, pid)
        assert _glanceHeight(surface) <= body, (name, _glanceHeight(surface))
    for rule in (_HEAD_RULE_532B0830, _HEAD_RULE_BARE_HEIGHT):
        css = _cssWithHeadRule(rule)
        for name, tree in trees.items():
            surface = rh.Surface(tree, css)
            for pid, head in _barHeads(surface).items():
                expected = _HEAD_BASELINE_MEASURED_PX if pid in _NOTED_HEADS[name] else 18
                assert _headCharge(surface, head) == pytest.approx(expected), (rule, name, pid)
            height = _glanceHeight(surface)
            assert height == pytest.approx(_BASELINE_GLANCE[name]), (rule, name)
            assert height > body, (rule, name)


def test_glanceGeometry_isTheCiosReLay_AC_d():
    """AC-d, y from the body top: LOAD header 0-18, bar 20-68; THROTTLE header
    76-94, bar 96-144; footer 158-254. HISTORY › bottom right of the footer."""
    head = _label()
    gauge = _gaugeHeight()
    gaugeGap = _px(_decl(_rule("#engine-card .eng-gauges"), "gap") or "")
    footGap = _px(_decl(_rule("#engine-card .card-body"), "gap") or "")
    loadHead = (0.0, head)
    loadBar = (gauge - _barHeight(), gauge)
    thrTop = gauge + gaugeGap
    thrHead = (thrTop, thrTop + head)
    thrBar = (thrTop + gauge - _barHeight(), thrTop + gauge)
    footTop = thrBar[1] + footGap
    foot = (footTop, footTop + _footHeight())
    assert [loadHead, loadBar, thrHead, thrBar, foot] == [
        pytest.approx(v) for v in [(0, 18), (20, 68), (76, 94), (96, 144), (158, 254)]
    ]
    # Atlas's fit check: the THROTTLE bar centre at panel y 162 (body + 42).
    assert (thrBar[0] + thrBar[1]) / 2 + 42 == 162
    assert _decl(_rule("#engine-card .eng-foot"), "align-items") == "flex-end"
    assert _decl(_rule("#engine-card .eng-foot"), "justify-content") == "space-between"
    assert _decl(_rule("#engine-card .eng-reading"), "align-self") == "flex-start"
    # MOVED PIN (US-889-f): the label's flex-basis 100% moves to its label line.
    for selector in ("#engine-card .eng-reading .eng-timing-head", "#engine-card .eng-reading .eng-basis"):
        assert _decl(_rule(selector), "flex-basis") == "100%"
    markup = _engineMarkup()
    foot = markup[markup.index('class="eng-foot"'):]
    assert foot.index("TIMING_ADVANCE") < foot.index("eng-basis") < foot.index('class="eng-actions"')
    assert markup.index('data-pid="ENGINE_LOAD"') < markup.index('data-pid="THROTTLE_POS"')
    assert markup.index('data-pid="THROTTLE_POS"') < markup.index('class="eng-foot"')


@_NODE_ONLY
def test_everyRow_fitsItsColumn_worstCase():
    bar = _barWidth()
    col = _footColumnWidth()
    # In the bar: the widest value never wraps (nowrap) and never clips.
    assert _decl(_rule("#engine-card .eng-bar-text"), "white-space") == "nowrap"
    assert _valueWidth("100", "%", "var(--fs-hero)") <= bar
    # The header line: the label and the widest note side by side.
    gap = _px(_decl(_rule("#engine-card .eng-bar-head"), "gap") or "")
    for label in ("LOAD", "THROTTLE"):
        for note in ("not read", "no source", "999 s"):
            assert michromaWidthPx(label, 15) + gap + _monoWidth(note, _meta()) <= bar, (label, note)
    # The footer's TIMING stack beside HISTORY › (Iris: ~207 + ~175 <= 448).
    # MOVED PIN (US-889-f): the value + note line becomes the label line --
    # 'TIMING' + --eng-inline-gap + the widest note <= the TIMING column; the
    # value row carries the number alone.
    assert col > 0
    for value, unit in (("40", "° ATDC"), ("22", "° BTDC"), ("--", "")):
        assert _valueWidth(value, unit, "var(--fs-primary)") <= col, value
    for note in _timingNoteTexts():
        assert _timingHeadWidth(note) <= col, note
    assert _wrappedLines(TIMING_BASIS, _meta(), col) == 1, "the caption is stacked on ONE line"
    assert michromaWidthPx("TIMING", 15) <= col


def test_widthModel_failsAPlantedWideRow():
    """Negative controls: the caption inline after the value (Iris: ~513 px)
    and a planted wide header both overrun their width."""
    inline = _valueWidth("22", "° BTDC", "var(--fs-primary)") + _monoWidth(" " + TIMING_BASIS, _meta())
    assert inline + _buttonWidth() > _bodyWidthPx()
    assert michromaWidthPx("THROTTLE", 15) + _monoWidth("x" * 60, _meta()) > _barWidth()
    # US-889-f: a TIMING note past the fit rule overruns the label line.
    assert _timingHeadWidth("x" * 40) > _footColumnWidth()


# US-889-f AC-4 fit rule: every TIMING note <= 18 characters (the longest
# emitted reason, 'engine not running', at 9.03 px/char = 0.60205 em x 15 px,
# tests/ui/css_type_scale.py). A longer text needs a shorter word, never a
# wrap or a shrink.
_TIMING_NOTE_MAX_CHARS = 18


def _timingNote(obdLive: dict[str, Any] | None, nowMs: int = 0) -> str:
    note = _probe("engineView", obdLive, nowMs)["readings"]["TIMING_ADVANCE"]["note"]
    assert isinstance(note, str)
    return note


def _timingNoteTexts() -> dict[str, str]:
    """Every TIMING note the page can emit, by where it comes from: absent,
    no obd-live, a stale age (fixture `stale`, a 999 s age, an unparseable ts)
    and drivingReasonText of EVERY code in band_producer.NO_BAND_REASONS."""
    stale = _fixture("stale")
    ts = stale["obd-live"]["params"]["TIMING_ADVANCE"]["ts"]
    staleParam = stale["obd-live"]["params"]["TIMING_ADVANCE"]
    notes = {
        "absent": _timingNote({"params": {}}),
        "no obd-live": _timingNote(None),
        "stale fixture": _timingNote(stale["obd-live"], _ms(stale["now"])),
        "stale 999 s": _timingNote({"params": {"TIMING_ADVANCE": staleParam}}, _ms(ts) + 999_000),
        "stale bad ts": _timingNote({"params": {"TIMING_ADVANCE": dict(staleParam, ts="not a time")}}),
    }
    for code in NO_BAND_REASONS:
        notes[code] = _timingNote({"params": {"TIMING_ADVANCE": _param(None, noBandReason=code)}})
    return notes


@_NODE_ONLY
def test_everyTimingNote_isAtMost18Chars_derivedFromTheReasonTable():
    """US-889-f AC-4: the emitted note texts, listed and asserted one by one."""
    notes = _timingNoteTexts()
    assert (notes["absent"], notes["no obd-live"]) == ("not read", "no source")
    assert (notes["stale fixture"], notes["stale 999 s"], notes["stale bad ts"]) == ("12 s", "999 s", "stale")
    assert set(NO_BAND_REASONS) <= set(notes) and len(NO_BAND_REASONS) == 5
    for source, text in notes.items():
        assert text, source
        assert len(text) <= _TIMING_NOTE_MAX_CHARS, (source, text)
    longest = max(notes.values(), key=len)
    assert len(longest) == _TIMING_NOTE_MAX_CHARS
    assert _monoWidth(longest, _meta()) == pytest.approx(162.6, abs=0.1)


@_NODE_ONLY
def test_timingNote_isOnItsLabelLine_rightAligned_footerHasThreeRows():
    """US-889-f AC-1 / AC-2 / AC-3 DETAIL: .eng-timing holds exactly three rows
    -- label line / value / caption. The label line is 'TIMING' then its note,
    right-aligned at --fs-meta on one line: a reason --text-secondary, a stale
    age --amber-warn. The caption is on the glass when stale and not read."""
    for name, kind, colour in (
        ("not-read-with-reason", "reason", "var(--text-secondary)"),
        ("stale", "age", "var(--amber-warn)"),
    ):
        surface = _boot(name)
        reading = _view(name)["readings"]["TIMING_ADVANCE"]
        timing = _byPid(surface, "eng-reading", "TIMING_ADVANCE")
        assert timing[-1]["attrs"]["data-note"] == kind, name
        rows = _kids(timing)
        assert [_classes(r[-1])[0] for r in rows] == [_TIMING_HEAD_CLASS, "eng-line", "eng-basis"], name
        assert all(surface.rendered(r) for r in rows), name
        label, note = _kids(rows[0])
        assert (_classes(label[-1])[0], _classes(note[-1])[0]) == ("eng-label", "eng-note"), name
        assert _textOf(label[-1]) == "TIMING"
        assert _textOf(note[-1]) == reading["note"] and surface.rendered(note), name
        assert _winning(surface, note, "color") == colour, name
        assert _winning(surface, note, "font-size") == "var(--fs-meta)", name
        assert _winning(surface, note, "white-space") == "nowrap", name
        assert _headCharge(surface, rows[0]) == pytest.approx(18), name
        assert _textOf(rows[2][-1]) == TIMING_BASIS, name
    head = _rule(_TIMING_HEAD)
    assert _decl(head, "display") == "flex"
    assert _decl(head, "justify-content") == "space-between"
    assert _decl(head, "gap") == "var(--eng-inline-gap)"
    assert _decl(head, "min-width") == "0"
    assert _decl(head, "align-items") not in (None, "baseline")
    # Fresh: the label alone, no note drawn, still three rows.
    fresh = _boot("idle-warm")
    rows = _kids(_byPid(fresh, "eng-reading", "TIMING_ADVANCE"))
    assert len(rows) == 3 and not fresh.rendered(_child(rows[0], "eng-note"))


# ---------------------------------------------------------------------------
# 7. US-889-e -- LOAD and THROTTLE as full-width horizontal bars, the value
#    inside (CIO ruling 2026-10-27, relayed by Iris; Atlas gate 2026-10-27).
# ---------------------------------------------------------------------------


def _assertInBarRules() -> None:
    """AC-c's declared rules: both copies over the whole bar, centred, their
    line box the bar's height; the bar clips anything that strays."""
    text = _rule("#engine-card .eng-bar-text")
    assert _decl(text, "position") == "absolute"
    for side in ("left", "top", "right", "bottom"):
        assert _decl(text, side) == "0", side
    assert _decl(text, "text-align") == "center"
    assert _decl(text, "line-height") == "var(--eng-bar-h)"
    assert _decl(_rule("#engine-card .eng-bar"), "overflow") == "hidden"
    assert _decl(_rule("#engine-card .eng-bar"), "position") == "relative"
    # LINE BOX (Atlas): each value's line box <= the bar, at its own tier.
    line = _lineBox("var(--fs-hero)", _decl(text, "line-height") or "")
    assert line <= _barHeight()
    for size in ("var(--fs-hero)", "var(--fs-primary)"):
        assert _px(size) <= line, size
    unit = _rule("#engine-card .eng-bar-text .eng-unit")
    assert _lineBox("var(--fs-label)", _decl(unit, "line-height") or "") <= _barHeight()
    # The value at --eng-line would NOT fit (the gap Atlas found).
    assert _lineBox("var(--fs-hero)", "var(--eng-line)") > _barHeight()
    assert _decl(_rule("#engine-card .eng-on-track"), "color") == "var(--text-primary)"
    assert _decl(_rule("#engine-card .eng-on-fill"), "color") == "var(--bg)"


def _fillPx(col: list[dict[str, Any]]) -> float:
    return _fillPct(_child(col, "eng-bar-fill")) / 100 * _barWidth()


def _clipVisiblePx(col: list[dict[str, Any]]) -> float:
    """How much of the --bg copy shows: the bar's width less its right inset."""
    return (100 - _clipRightPct(_copies(col)["fill"])) / 100 * _barWidth()


@_NODE_ONLY
def test_loadThrottle_areFullWidthHorizontalBars_valueInside():
    """EXIT TEST (US-889-e): AC-a + AC-b (fixture 71) + AC-c. Fails on the
    bench before this story (US-889-d's 26 x 168 vertical bars)."""
    # AC-a: each bar the body's width +-1 px by 48 px, a Michroma --fs-meta
    # header ABOVE it.
    assert abs(_barWidth() - 448) <= 1
    assert _barHeight() == 48
    surface = _boot("stale")
    for pid, label in zip(BAR_PIDS, ("LOAD", "THROTTLE")):
        col = _byPid(surface, "eng-bar-col", pid)
        kids = [c for c in col[-1]["children"] if "tag" in c]
        assert [_classes(k)[0] for k in kids] == ["eng-bar-head", "eng-bar"], pid
        head = _child(col, "eng-bar-head")
        name = _child(head, "eng-label")
        assert _textOf(name[-1]) == label
        assert surface.winningDeclaration(name, "font-family")[0] == "var(--font-display)"
        assert surface.winningDeclaration(name, "font-size")[0] == "var(--fs-meta)"
        assert surface.winningDeclaration(_child(col, "eng-bar"), "width")[0] == "100%"
    # AC-b: LOAD 71 -> the --accent fill is 318 px (71 % of 448), no motion.
    load = _byPid(surface, "eng-bar-col", "ENGINE_LOAD")
    assert _fillPx(load) == pytest.approx(0.71 * 448, abs=1)
    fill = _child(load, "eng-bar-fill")
    assert surface.winningDeclaration(fill, "background-color")[0] == "var(--accent)"
    for prop in ("transition", "animation"):
        assert surface.winningDeclaration(fill, prop) is None, prop
    # AC-c: '71 %' inside the bar, twice -- warm white over the track, --bg
    # over the fill, the --bg copy clipped to the fill's width.
    copies = _copies(load)
    for role, copy in copies.items():
        assert surface.rendered(copy), role
        assert (_textOf(_child(copy, "eng-value")[-1]), _textOf(_child(copy, "eng-unit")[-1])) == (
            "71", "%",
        ), role
        assert surface.winningDeclaration(_child(copy, "eng-value"), "font-variant-numeric")[0] == (
            "tabular-nums"
        )
        assert surface.winningDeclaration(_child(copy, "eng-unit"), "font-size")[0] == "var(--fs-label)"
    assert surface.winningDeclaration(copies["track"], "color")[0] == "var(--text-primary)"
    assert surface.winningDeclaration(copies["fill"], "color")[0] == "var(--bg)"
    assert _clipVisiblePx(load) == pytest.approx(_fillPx(load), abs=1)
    sizes = {
        pid: surface.winningDeclaration(
            _child(_copies(_byPid(surface, "eng-bar-col", pid))["track"], "eng-value"), "font-size"
        )[0]
        for pid in BAR_PIDS
    }
    assert sizes == {"ENGINE_LOAD": "var(--fs-hero)", "THROTTLE_POS": "var(--fs-primary)"}
    # Track (under the fill) -> fill -> --bg copy, in paint order.
    bar = _child(load, "eng-bar")
    order = [_classes(c) for c in bar[-1]["children"] if "tag" in c]
    assert order == [["eng-bar-text", "eng-on-track"], ["eng-bar-fill"], ["eng-bar-text", "eng-on-fill"]]
    _assertInBarRules()


def _barsAt(load: float, throttle: float) -> rh.Surface:
    return _bootLive({"params": {
        "ENGINE_LOAD": _param(load, "%"), "THROTTLE_POS": _param(throttle, "%"),
    }})


@_NODE_ONLY
@pytest.mark.parametrize(
    ("source", "pid", "value"),
    [
        ("inline-0", "ENGINE_LOAD", 0.0),
        ("inline-0", "THROTTLE_POS", 0.0),
        ("stale", "THROTTLE_POS", 48.2),
        ("stale", "ENGINE_LOAD", 71.0),
        ("wot-pull-load-100", "ENGINE_LOAD", 100.0),
    ],
)
def test_fillWidth_isTheValuePercentOfTheTrack_AC_b(source: str, pid: str, value: float):
    surface = _barsAt(0.0, 0.0) if source == "inline-0" else _boot(source)
    col = _byPid(surface, "eng-bar-col", pid)
    assert _fillPx(col) == pytest.approx(value / 100 * 448, abs=1), (source, pid)
    assert _clipVisiblePx(col) == pytest.approx(_fillPx(col), abs=1), (source, pid)


@_NODE_ONLY
def test_bothCopiesAndTheClip_at0And100_AC_c():
    """At 0 % the --bg copy shows nothing (clip 100 % from the right) and the
    warm-white copy carries '0 %'; at 100 % the --bg copy shows the whole bar."""
    empty = _byPid(_barsAt(0.0, 0.0), "eng-bar-col", "THROTTLE_POS")
    full = _byPid(_barsAt(100.0, 100.0), "eng-bar-col", "ENGINE_LOAD")
    assert _fillPx(empty) == 0 and _clipVisiblePx(empty) == 0
    assert _fillPx(full) == pytest.approx(448) and _clipVisiblePx(full) == pytest.approx(448)
    for col, text in ((empty, "0"), (full, "100")):
        assert col[-1]["attrs"]["data-null"] == "false"
        for role, copy in _copies(col).items():
            assert _textOf(_child(copy, "eng-value")[-1]) == text, role
            assert _textOf(_child(copy, "eng-unit")[-1]) == "%", role
    _assertInBarRules()


def test_theFillHasNoMotion_theValueStepsPerSample():
    """Keeps :649's no-transition rule, now for the WIDTH."""
    for selector, body in _engineRules():
        if "eng-bar" in selector:
            assert not re.search(r"\b(?:animation|transition)\s*:", body), selector
    js = _read(_JS)
    start = js.index("function renderEngineCard(")
    block = js[start : js.index("\n    }\n", start)]
    assert 'setProperty("width"' in block
    assert "transition" not in block and "animation" not in block
