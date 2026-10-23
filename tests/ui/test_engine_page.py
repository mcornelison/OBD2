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
#     6. the FIT -- a height/width model of the above-the-fold half at 480x320
#        from the shipped values, with negative controls.
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
CARD_ORDER = [
    "Driving", "Navigation", "Engine", "Fuel", "Motion", "Light", "Alerts",
    "System Status",
]

ENGINE_PIDS = ["ENGINE_LOAD", "THROTTLE_POS", "TIMING_ADVANCE"]
BAR_PIDS = ["ENGINE_LOAD", "THROTTLE_POS"]
TIMING_BASIS = "base timing · not knock"
SCROLL_CUE = "↓ history and status below"

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


def _boot(name: str) -> rh.Surface:
    fx = _fixture(name)
    dom = rh.runDashboard(
        routes={"/obd-live": fx["obd-live"]}, nowMs=_ms(fx["now"]), steps=[{"flush": 4}]
    )
    return rh.dashboardSurface(dom["tree"])


def _engineRules() -> list[tuple[str, str]]:
    """Every dashboard.css rule that styles the Engine card (comments stripped)."""
    return [
        (rule.selector.strip(), rule.declarations)
        for rule in rh.parseCss(_read(DASHBOARD_CSS))
        if "#engine-card" in rule.selector or ".eng-" in rule.selector
    ]


def _rule(selector: str) -> str:
    bodies = [body for sel, body in _engineRules() if sel == selector]
    assert bodies, f"no rule {selector!r}"
    return " ".join(bodies)


def _decl(body: str, prop: str) -> str | None:
    found = rh.declarationOf(body, prop)
    return None if found is None else found[0]


def _scopedVars() -> dict[str, str]:
    block = _rule("#engine-card")
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


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_theShippedDomPaintsTheView(name: str):
    view = _view(name)
    surface = _boot(name)
    for pid in ENGINE_PIDS:
        r = view["readings"][pid]
        path = _byPid(surface, "eng-reading", pid)
        attrs = path[-1]["attrs"]
        assert _textOf(_child(path, "eng-value")[-1]) == r["text"], (name, pid)
        assert _textOf(_child(path, "eng-unit")[-1]) == r["unit"], (name, pid)
        note = _child(path, "eng-note")
        assert _textOf(note[-1]) == r["note"], (name, pid)
        assert surface.rendered(note) == bool(r["note"]), (name, pid, "note box")
        assert attrs.get("data-stale") == ("true" if r["stale"] else "false"), (name, pid)
        assert attrs.get("data-note") == (r["noteKind"] or "none"), (name, pid)
    for pid in BAR_PIDS:
        bar = view["bars"][pid]
        col = _byPid(surface, "eng-bar-col", pid)
        fill = _child(col, "eng-bar-fill")
        height = ((fill[-1].get("style") or {}).get("height") or "").strip()
        assert height == f"{bar['fill'] if bar['fill'] is not None else 0}%", (name, pid, height)
        assert col[-1]["attrs"].get("data-stale") == ("true" if bar["stale"] else "false")


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_timingBasis_andScrollCue_areOnTheGlass_inEveryFixture(name: str):
    surface = _boot(name)
    basis = _enginePaths(surface, "eng-basis")
    assert len(basis) == 1 and _textOf(basis[0][-1]) == TIMING_BASIS
    assert surface.rendered(basis[0])
    cue = _enginePaths(surface, "eng-cue")
    assert len(cue) == 1 and _textOf(cue[0][-1]) == SCROLL_CUE
    assert surface.rendered(cue[0])


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_valuesAreNeutral_andBarsAreAccent(name: str):
    surface = _boot(name)
    for pid in ENGINE_PIDS:
        value = _child(_byPid(surface, "eng-reading", pid), "eng-value")
        assert surface.winningDeclaration(value, "color")[0] == "var(--text-primary)", (name, pid)
    for pid in BAR_PIDS:
        fill = _child(_byPid(surface, "eng-bar-col", pid), "eng-bar-fill")
        assert surface.winningDeclaration(fill, "background-color")[0] == "var(--accent)"


@_NODE_ONLY
def test_staleReading_isDimmed_andItsAgeIsAmber_reasonIsNot():
    surface = _boot("stale")
    path = _byPid(surface, "eng-reading", "ENGINE_LOAD")
    opacity = surface.winningDeclaration(_child(path, "eng-line"), "opacity")
    assert opacity is not None and _number(opacity[0]) == pytest.approx(0.4)
    assert surface.winningDeclaration(_child(path, "eng-note"), "color")[0] == "var(--amber-warn)"
    barOpacity = surface.winningDeclaration(_byPid(surface, "eng-bar-col", "ENGINE_LOAD"), "opacity")
    assert barOpacity is not None and _number(barOpacity[0]) == pytest.approx(0.4)
    fresh = _boot("idle-warm")
    line = _child(_byPid(fresh, "eng-reading", "ENGINE_LOAD"), "eng-line")
    assert fresh.winningDeclaration(line, "opacity") is None
    unread = _boot("not-read-with-reason")
    note = _child(_byPid(unread, "eng-reading", "THROTTLE_POS"), "eng-note")
    assert unread.winningDeclaration(note, "color")[0] == "var(--text-secondary)"


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
        if "eng-unit" in selector or "eng-basis" in selector or "eng-cue" in selector:
            assert "var(--font-display)" not in body, selector


def test_labels_areMichroma_atFsMeta_letterSpacingZero():
    body = _rule("#engine-card .eng-label")
    assert _decl(body, "font-family") == "var(--font-display)"
    assert _decl(body, "font-weight") == "400"
    assert _decl(body, "font-synthesis") == "none"
    assert _decl(body, "font-size") == "var(--fs-meta)"
    assert _decl(body, "letter-spacing") == "0"
    labels = re.findall(r'<span class="eng-label">([^<]+)</span>', _engineMarkup())
    assert sorted(labels) == sorted(["LOAD", "THR", "LOAD", "THROTTLE", "TIMING"])
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


def _gateViolations(rules: list[tuple[str, str]]) -> list[str]:
    bad = []
    for selector, body in rules:
        if "#engine-card" not in selector:
            bad.append(f"{selector}: an Engine rule not scoped to #engine-card")
        if _COLOUR_LITERAL.search(body):
            bad.append(f"{selector}: literal colour")
        if selector == "#engine-card":
            for decl in filter(None, (d.strip() for d in body.split(";"))):
                if not decl.startswith("--eng-"):
                    bad.append(f"{selector}: {decl} is not a scoped --eng- property")
        elif _PX_LITERAL.search(body):
            bad.append(f"{selector}: literal px outside the #engine-card block")
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
        ("#engine-card .eng-bar-fill", "transition: height 0.2s"),
    ]
    assert len(_gateViolations(planted)) == 3


def test_everyScopedPropertyIsConsumed():
    css = rh._stripComments(_read(DASHBOARD_CSS))
    for name in _scopedVars():
        assert f"var({name})" in css, f"{name} is declared and never used"


def test_layoutGeometry_isNotInRoot():
    root = re.search(r":root\s*\{(.*?)\}", rh._stripComments(_read(DASHBOARD_CSS)), re.S)
    assert root is not None and "--eng-" not in root.group(1)


def test_barGeometry_is26x120():
    assert _px(_decl(_rule("#engine-card .eng-bar"), "width") or "") == 26
    assert _px(_decl(_rule("#engine-card .eng-bar"), "height") or "") == 120


# ---------------------------------------------------------------------------
# 6. Fit -- the above-the-fold half at 480x320 (no scrolling, no clipping).
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
    return _px(size) * _number(line)


def _monoWidth(text: str, sizeVar: str) -> float:
    return len(text) * _px(sizeVar) * PI_MONO_ADVANCE_EM


def _meta() -> str:
    return "var(--fs-meta)"


def _aboveTheFoldHeight(barH: float | None = None) -> float:
    """Worst case: every reading carries a note (inline on its row)."""
    labelLine = _lineBox(_meta(), _decl(_rule("#engine-card .eng-label"), "line-height") or "")
    lineH = _decl(_rule("#engine-card .eng-line"), "line-height") or ""
    loadLine = _lineBox("var(--fs-hero)", lineH)
    rowLine = _lineBox("var(--fs-primary)", lineH)
    noteLine = _lineBox(_meta(), _decl(_rule("#engine-card .eng-basis"), "line-height") or "")
    gap = _px(_decl(_rule("#engine-card .eng-readings"), "gap") or "")
    # LOAD's label wraps above the hero number across the row's own gap; then
    # load, throttle, timing and the basis caption stack with three gaps.
    wrap = _px(_decl(_rule("#engine-card .eng-reading"), "gap") or "")
    readings = labelLine + wrap + loadLine + rowLine + rowLine + noteLine + 3 * gap
    bar = barH if barH is not None else _px("var(--eng-bar-h)")
    barGap = _px(_decl(_rule("#engine-card .eng-bar-col"), "gap") or "")
    bars = bar + barGap + labelLine
    bodyGap = _px(_decl(_rule("#engine-card .card-body"), "gap") or "")
    cue = _lineBox(_meta(), _decl(_rule("#engine-card .eng-cue"), "line-height") or "")
    return max(readings, bars) + bodyGap + cue


def test_aboveTheFold_fitsTheBody_withTheCueVisible():
    assert _aboveTheFoldHeight() <= _bodyHeightPx(), (_aboveTheFoldHeight(), _bodyHeightPx())


def test_heightModel_failsAPlantedTallBar():
    assert _aboveTheFoldHeight(barH=260) > _bodyHeightPx()


def _barsWidth() -> float:
    gap = _px(_decl(_rule("#engine-card .eng-bars"), "gap") or "")
    load = max(_px("var(--eng-bar-w)"), michromaWidthPx("LOAD", 15))
    thr = max(_px("var(--eng-bar-w)"), michromaWidthPx("THR", 15))
    return load + gap + thr


def _rowWidth(label: str, value: str, unit: str, note: str, sizeVar: str) -> float:
    gap = _px(_decl(_rule("#engine-card .eng-reading"), "gap") or "")
    unitGap = _px(_decl(_rule("#engine-card .eng-unit"), "margin-inline-start") or "")
    width = _monoWidth(value, sizeVar) + unitGap + _monoWidth(unit, "var(--fs-label)")
    if label:
        width += michromaWidthPx(label, 15) + gap
    if note:
        width += gap + _monoWidth(note, _meta())
    return width


def _readingsWidth() -> float:
    colGap = _px(_decl(_rule("#engine-card .eng-main"), "gap") or "")
    return _bodyWidthPx() - _barsWidth() - colGap


def test_everyRow_fitsTheReadingsColumn_worstCase():
    col = _readingsWidth()
    assert _rowWidth("THROTTLE", "100", "%", "not read", "var(--fs-primary)") <= col
    assert _rowWidth("TIMING", "40", "° ATDC", "no source", "var(--fs-primary)") <= col
    assert _rowWidth("", "100", "%", "no source", "var(--fs-hero)") <= col
    assert _monoWidth(TIMING_BASIS, _meta()) <= col
    assert _monoWidth(SCROLL_CUE, _meta()) <= _bodyWidthPx()


def test_widthModel_failsAPlantedWideRow():
    assert _rowWidth("THROTTLE", "100.00", "percent", "not read at all", "var(--fs-hero)") > (
        _readingsWidth()
    )
