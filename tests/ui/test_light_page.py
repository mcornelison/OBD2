################################################################################
# File Name: test_light_page.py
# Purpose/Description: US-893-b (F-127) tests for the Light page
#   (specs/v030-light-page-design.md layout A + glyph, governed by the Atlas
#   L1-L6 / Iris L1-L7 rulings of 2026-10-19): the Light card moves to right
#   after Motion and shows the provider's DAY/DUSK/NIGHT with its glyph, the
#   ambient lux, the auto-dim curve drawn from states/light.curve with a live
#   dot at the APPLIED level, the IR / FULL / VISIBLE / RANGE cells and the
#   applied brightness. Guarded:
#     1. the fixtures -- present, described, each the REAL buildLightState
#        output for its recorded inputs;
#     2. the pure logic (node): luxAxisX, the word, the formats, the reasons
#        in order, the raw cells, the status from the applied basis, the
#        curve geometry and the dot on / off the line;
#     3. the code gates: every Math.log inside luxAxisX, no curve literal,
#        the retired light view names;
#     4. the markup + stylesheet: the slot, tokens only, the brand face only
#        on the word and the labels, the width budget;
#     5. the SHIPPED DOM, painted by the real tick with fetch and the clock
#        stubbed.
#   NOT GUARDED: layout on the glass (render_harness resolves the cascade, not
#   boxes): "no clip" and the >= 34 px reads are owed as R15 screenshots on the
#   Pi; here the widths are computed from the measured advances.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-19    | Rex (US-893-b) | Initial -- the Light page.
# ================================================================================
################################################################################

"""US-893-b tests for the Light page."""

from __future__ import annotations

import json
import math
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

from tests.ui.css_type_scale import ADVANCE_OBSERVED  # noqa: E402
from tests.ui.test_topbar_three_column_grid import michromaWidthPx  # noqa: E402

_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_CSS = os.path.join(rh.DASHBOARD_DIR, "dashboard.css")
_TOKENS = os.path.join(rh.DASHBOARD_DIR, "..", "tokens.css")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "light")
_NODE = shutil.which("node")

_NODE_ONLY = pytest.mark.skipif(
    _NODE is None, reason="node not on PATH -- these tests run the shipped browser JS"
)

FIXTURE_NAMES = [
    "night-0.6lux", "dusk-22lux", "day-1400lux", "sun-at-limit",
    "config-retuned-boundaries", "light-stale", "light-null", "stop-override",
    "dot-off-curve",
]
ON_CURVE = ["night-0.6lux", "dusk-22lux", "day-1400lux", "config-retuned-boundaries"]

# The curve graph's frame (spec s3: 200 x 104) and its plot, as carousel.js
# lays it out (LIGHT_CURVE_*).
CURVE_W, CURVE_H, PAD_L, PAD_R, PAD_T, PAD_B = 200, 104, 40, 6, 8, 22
PLOT_W = CURVE_W - PAD_L - PAD_R
PLOT_H = CURVE_H - PAD_T - PAD_B
CARD_BODY_W = 448  # 480 - 2 x 16 px card padding


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _call(fn: str, *args: Any) -> Any:
    """One exported carousel.js function, called with JSON args."""
    script = (
        'const a = JSON.parse(require("fs").readFileSync(0, "utf-8"));'
        "const c = require(a.js);"
        "const v = c[a.fn].apply(null, a.args);"
        "process.stdout.write(JSON.stringify(v === undefined ? null : v));"
    )
    proc = subprocess.run(
        [_NODE or "node", "-e", script],
        input=json.dumps({"js": _JS, "fn": fn, "args": list(args)}),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _alarm(fx: dict[str, Any]) -> bool:
    return bool(fx["dtc"]) and _call("brightnessAlarmActive", fx["dtc"])


def _view(name: str, light: Any = "fixture", shiftMs: int = 0) -> dict[str, Any]:
    fx = _fixture(name)
    payload = fx["light"] if light == "fixture" else light
    return _call("lightPageView", payload, fx["autoDim"], _ms(fx["now"]) + shiftMs, _alarm(fx))


def _y(level: float, yLo: float) -> float:
    return round(PAD_T + PLOT_H * (1 - (min(max(level, yLo), 1) - yLo) / (1 - yLo)), 1)


def _polylineYAt(points: str, x: float) -> float:
    """The polyline's y at pixel x, between the two vertices that bracket it."""
    verts = [tuple(float(v) for v in p.split(",")) for p in points.split(" ")]
    for (x0, y0), (x1, y1) in zip(verts, verts[1:], strict=False):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    raise AssertionError(f"x {x} is outside the polyline")


# ---------------------------------------------------------------------------
# 1. Fixtures -- the provider's real payload, not a typed one.
# ---------------------------------------------------------------------------


def test_fixturesArePresent_andDescribed():
    assert sorted(f[:-5] for f in os.listdir(_FIXTURES)) == sorted(FIXTURE_NAMES)
    for name in FIXTURE_NAMES:
        fx = _fixture(name)
        assert fx["description"] and fx["now"] and fx["light"] and fx["autoDim"], name


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_everyFixture_isWhatTheRealBridgeBuilderEmits(name: str):
    from pi.sensors.light_state_bridge import buildLightState

    fx = _fixture(name)
    assert buildLightState(**fx["inputs"]) == fx["light"]
    assert fx["inputs"]["autoDim"] == fx["autoDim"]  # the page is injected the same


def test_theFixturesCarryTheCasesTheyAreNamedFor():
    assert _fixture("sun-at-limit")["light"]["reasons"] == {"lux": "at_limit"}
    assert _fixture("sun-at-limit")["light"]["atLimit"] == {"ir": False, "full": True}
    retuned = _fixture("config-retuned-boundaries")["light"]
    assert (retuned["lux"], retuned["lightBand"], retuned["curve"]["luxMin"]) == (5.0, "night", 10.0)
    null = _fixture("light-null")["light"]
    assert (null["lux"], null["brightnessMode"], null["brightnessLevel"]) == (None, "default", 1.0)
    assert _fixture("stop-override")["light"]["brightnessLevel"] == pytest.approx(0.8, abs=1e-3)
    off = _fixture("dot-off-curve")
    assert (off["light"]["lux"], off["light"]["brightnessLevel"]) == (22.0, 0.75)
    assert _ms(off["now"]) == _ms(off["light"]["ts"]) + (off["autoDim"]["luxStaleSec"] + 1) * 1000
    assert off["autoDim"]["defaultLevel"] == 1.0


# ---------------------------------------------------------------------------
# 2. Pure logic
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_validation_luxAxisX_pinsBothEnds_andPlacesTheKneeOnTheLogAxis():
    """VC row 5: lux 0 and luxLo -> the left edge; the knee (~94.9) -> its log
    position; luxHi and 2 x luxHi -> the right edge."""
    from pi.sensors.light_state_bridge import brightnessKnee

    lo, hi, w = 0.3, 30000.0, 154
    knee = brightnessKnee(_fixture("dusk-22lux")["autoDim"])
    assert knee == pytest.approx(94.868, abs=1e-3)
    assert _call("luxAxisX", 0, lo, hi, w) == 0
    assert _call("luxAxisX", lo, lo, hi, w) == 0
    expected = w * (math.log10(knee) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
    assert _call("luxAxisX", knee, lo, hi, w) == pytest.approx(expected, abs=1e-9)
    assert _call("luxAxisX", hi, lo, hi, w) == w
    assert _call("luxAxisX", 2 * hi, lo, hi, w) == w


@_NODE_ONLY
@pytest.mark.parametrize("args", [
    [None, 0.3, 30000, 154], ["22", 0.3, 30000, 154],
    [5, 0, 30000, 154], [5, 30000, 0.3, 154],
])
def test_luxAxisX_aNonNumericLuxOrAnUnloggableAxis_hasNoX(args: list[Any]):
    assert _call("luxAxisX", *args) is None


@_NODE_ONLY
def test_validation_day1400_sunGlyph_DAY_1400lux_auto100():
    v = _view("day-1400lux")
    assert v["word"] == {"text": "DAY", "glyph": "day"}
    assert (v["ambient"]["value"], v["ambient"]["unit"]) == ("1,400", "lux")
    assert v["status"]["text"] == "BRIGHTNESS AUTO 100 %"
    assert v["stale"] is False and v["reason"] is None and v["age"] is None
    raw = v["raw"]
    assert [raw[k]["value"] for k in ("ir", "full", "visible")] == ["4,300", "12,400", "8,100"]
    assert raw["range"] == {"gain": "low", "ms": "100 ms"}


@_NODE_ONLY
@pytest.mark.parametrize(("name", "word", "glyph", "value", "status"), [
    ("night-0.6lux", "NIGHT", "night", "0.6", "BRIGHTNESS AUTO 75 %"),
    ("dusk-22lux", "DUSK", "dusk", "22", "BRIGHTNESS AUTO 75 %"),
])
def test_word_isTheProvidersBandUpperCased_withItsGlyph(
    name: str, word: str, glyph: str, value: str, status: str
):
    v = _view(name)
    assert v["word"] == {"text": word, "glyph": glyph}
    assert v["ambient"]["value"] == value
    assert v["status"]["text"] == status


@_NODE_ONLY
def test_validation_lightNull_dashPlusReason_defaultNoReading100():
    v = _view("light-null")
    assert v["word"] == {"text": "--", "glyph": None}
    assert v["ambient"] == {"value": "--", "unit": "", "none": True}
    assert v["reason"] == "no reading"
    assert v["status"]["text"] == "BRIGHTNESS 100 % (default, no reading)"
    assert [v["raw"][k] for k in ("ir", "full", "visible")] == [{"value": "--", "tone": "none"}] * 3
    assert v["raw"]["range"] == {"gain": "--", "ms": "--"}
    assert v["curve"] is not None and v["curve"]["dot"] is None  # no dot, the line stays


@_NODE_ONLY
def test_validation_stopOverride_isBrightness100Alert_andTheDotIsAtFull():
    fx = _fixture("stop-override")
    v = _view("stop-override")
    assert _alarm(fx) is True
    assert v["applied"] == {"level": 1.0, "basis": "alert"}
    assert v["status"]["text"] == "BRIGHTNESS 100 % (alert)"
    assert v["curve"]["dot"]["y"] == _y(1.0, 0.5)


@_NODE_ONLY
def test_validation_configRetunedBoundaries_NIGHT_verticalAt10_noPageChange():
    v = _view("config-retuned-boundaries")
    assert v["word"]["text"] == "NIGHT"
    x10 = round(PAD_L + _call("luxAxisX", 10.0, 0.3, 30000.0, PLOT_W), 1)
    lo, full = v["curve"]["verticals"]
    assert (lo["x"], lo["label"]) == (x10, "10")
    assert full["label"] == "1,000 lux"
    assert [lbl["text"] for lbl in v["curve"]["yLabels"]] == ["100%", "60%"]


@_NODE_ONLY
def test_sunAtLimit_luxIsTheReason_fullAndVisibleReadAtLimit_irItsCount():
    v = _view("sun-at-limit")
    assert v["ambient"]["value"] == "--" and v["reason"] == "sensor at limit"
    assert v["word"] == {"text": "--", "glyph": None}
    assert v["raw"]["full"] == {"value": "at limit", "tone": "warn"}
    assert v["raw"]["visible"] == {"value": "at limit", "tone": "warn"}
    assert v["raw"]["ir"] == {"value": "20,000", "tone": "plain"}
    assert "36,863" not in json.dumps(v)  # never the clipped count
    assert v["status"]["text"] == "BRIGHTNESS 100 % (default, no reading)"


@_NODE_ONLY
def test_atLimit_irFlagAlone_IRandVISIBLEAtLimit_FULLItsCount():
    light = dict(_fixture("day-1400lux")["light"], atLimit={"ir": True, "full": False})
    raw = _view("day-1400lux", light)["raw"]
    assert raw["ir"]["value"] == raw["visible"]["value"] == "at limit"
    assert raw["full"] == {"value": "12,400", "tone": "plain"}


@_NODE_ONLY
def test_atLimit_aNullFlagShowsTheCount_andANullVisibleIsDashNeverZero():
    light = dict(_fixture("day-1400lux")["light"], atLimit={"ir": None, "full": None},
                 visibleCount=None)
    raw = _view("day-1400lux", light)["raw"]
    assert raw["ir"]["value"] == "4,300" and raw["full"]["value"] == "12,400"
    assert raw["visible"] == {"value": "--", "tone": "none"}


@_NODE_ONLY
def test_validation_lightStale_dimsWithTheAge_valuesKept_statusNeverAuto():
    v = _view("light-stale")
    assert v["stale"] is True
    assert v["age"] == {"text": "14 s", "tone": "warn"}
    assert v["word"]["text"] == "DUSK" and v["ambient"]["value"] == "22"
    assert v["applied"] == {"level": 1.0, "basis": "fallback"}
    assert v["status"]["text"] == "BRIGHTNESS 100 % (default, no reading)"
    assert _view("light-stale", shiftMs=-4000)["stale"] is False  # 10 s old: still fresh


@_NODE_ONLY
@pytest.mark.parametrize("ts", [None, "not a time"])
def test_reasons_noTimestamp_valuesAsPublished_dimmed(ts: Any):
    v = _view("dusk-22lux", dict(_fixture("dusk-22lux")["light"], ts=ts))
    assert v["stale"] is True
    assert v["age"] == {"text": "no timestamp", "tone": "none"}
    assert v["word"]["text"] == "DUSK" and v["ambient"]["value"] == "22"


@_NODE_ONLY
def test_reasons_noPayload_isDashNoGlyph_noLightData_andTheFallbackStatus():
    v = _view("dusk-22lux", None)
    assert v["absent"] is True
    assert v["word"] == {"text": "--", "glyph": None}
    assert v["ambient"]["value"] == "--" and v["reason"] == "no light data"
    assert v["curve"] is None
    assert v["status"]["text"] == "BRIGHTNESS 100 % (default, no reading)"


@_NODE_ONLY
@pytest.mark.parametrize(("reasons", "text"), [
    ({"lux": "no_reading"}, "no reading"), ({"lux": "at_limit"}, "sensor at limit"),
    ({}, "no reading"), ({"lux": "lens_fogged"}, "lens_fogged"),
])
def test_reasons_oneTable_aMissingCodeIsNoReading_anUnknownOnePaintsAsItself(
    reasons: dict[str, str], text: str
):
    light = dict(_fixture("light-null")["light"], reasons=reasons)
    assert _view("light-null", light)["reason"] == text


@_NODE_ONLY
def test_word_aNullOrUnknownBandIsDash_neverDerivedFromLux():
    """A day band on a dark lux reads DAY; no band on a bright lux reads '--'."""
    base = _fixture("dusk-22lux")["light"]
    assert _view("dusk-22lux", dict(base, lightBand="day"))["word"]["text"] == "DAY"
    for band in (None, "DUSK", "twilight"):
        assert _view("dusk-22lux", dict(base, lightBand=band))["word"] == {
            "text": "--", "glyph": None}


@_NODE_ONLY
@pytest.mark.parametrize(("lux", "text"), [
    (0.0, "0.0"), (0.35, "0.3"), (9.96, "10.0"), (10.0, "10"), (999.5, "1,000"),
    (30000.0, "30,000"),
])
def test_ambientFormat_underTenOneDecimal_elseRoundedWithAFixedComma(lux: float, text: str):
    light = dict(_fixture("dusk-22lux")["light"], lux=lux)
    assert _view("dusk-22lux", light)["ambient"]["value"] == text


@_NODE_ONLY
@pytest.mark.parametrize("name", ON_CURVE)
def test_validation_onTheCurve_theDotIsOnThePolyline(name: str):
    curve = _view(name)["curve"]
    dot = curve["dot"]
    assert abs(_polylineYAt(curve["points"], dot["x"]) - dot["y"]) <= 0.5, (name, dot)


@_NODE_ONLY
def test_validation_dotOffCurve_isAtTheAppliedLevel_offThePolyline():
    """VC row 7 (Atlas L3): the provider's 0.75 is stale, so the dot sits at the
    injected defaultLevel 1.0 -- off the line, never snapped onto it."""
    v = _view("dot-off-curve")
    assert v["applied"] == {"level": 1.0, "basis": "fallback"}
    dot = v["curve"]["dot"]
    assert dot["y"] == _y(1.0, 0.5)
    assert abs(_polylineYAt(v["curve"]["points"], dot["x"]) - _y(0.75, 0.5)) <= 0.5
    assert v["stale"] is True and v["age"]["text"] == "11 s"


@_NODE_ONLY
def test_curve_everyVertexIsAPublishedPoint_andTheYDomainHasTheHeadroom():
    fx = _fixture("dusk-22lux")
    curve = _view("dusk-22lux")["curve"]
    pts = fx["light"]["curve"]["points"]
    verts = curve["points"].split(" ")
    assert len(verts) == len(pts)
    for (lux, level), vert in zip(pts, verts, strict=True):
        x = round(PAD_L + _call("luxAxisX", lux, pts[0][0], pts[-1][0], PLOT_W), 1)
        assert vert == f"{_num(x)},{_num(_y(level, 0.5))}"
    assert curve["axis"] == {"x0": PAD_L, "x1": CURVE_W - PAD_R, "yTop": PAD_T,
                             "yBottom": PAD_T + PLOT_H}
    assert [y["text"] for y in curve["yLabels"]] == ["100%", "75%"]
    assert [(v["label"], v["anchor"]) for v in curve["verticals"]] == [
        ("3", "end"), ("300 lux", "start")]


def _num(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


@_NODE_ONLY
def test_curve_aLevelBelowTheDomain_pinsToTheBottom_andANullMinLevelIsZeroToOne():
    light = _fixture("dusk-22lux")["light"]
    pinned = _call("lightCurveView", light["curve"], 22.0, 0.3)
    assert pinned["dot"]["y"] == PAD_T + PLOT_H
    loose = _call("lightCurveView", dict(light["curve"], minLevel=None), 22.0, 0.5)
    assert loose["dot"]["y"] == _y(0.5, 0.0)
    assert [y["text"] for y in loose["yLabels"]] == ["100%"]


@_NODE_ONLY
@pytest.mark.parametrize("curve", [
    None, {}, {"points": []}, {"points": [[0.3, 0.75]]},
    {"points": [[0, 0.75], [30000, 1.0]]}, {"points": [[0.3, "x"], [30000, 1.0]]},
])
def test_curve_missingOrMalformed_drawsNothing(curve: Any):
    assert _call("lightCurveView", curve, 22.0, 0.75) is None
    light = dict(_fixture("dusk-22lux")["light"], curve=curve)
    assert _view("dusk-22lux", light)["curve"] is None


# ---------------------------------------------------------------------------
# 3. Code gates
# ---------------------------------------------------------------------------


def _code() -> str:
    from tests.ui.test_carousel_source_cards import _stripJsComments

    return _stripJsComments(_read(_JS))


def _fnSpan(code: str, name: str) -> tuple[int, int]:
    start = code.index("function " + name + "(")
    depth, i = 0, code.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(code[i], 0)
        if depth == 0:
            return start, i
        i += 1


def test_validation_everyMathLogCallSitsInsideLuxAxisX():
    """VC row 6 (Atlas gate item 1): count EVERY Math.log / Math.log10 call in
    comment-stripped carousel.js; all of them are inside luxAxisX."""
    code = _code()
    start, end = _fnSpan(code, "luxAxisX")
    hits = [m.start() for m in re.finditer(r"Math\.log(?:10|2|1p)?\b", code)]
    assert hits, "luxAxisX places x on a log axis -- it must log"
    assert all(start < h < end for h in hits), hits
    assert code.count("function luxAxisX(") == 1


def test_noCurveLiteral_andTheHeadroomIsANamedConstant():
    code = _code()
    assert re.findall(r"\b(luxMin|luxFull|minLevel)\s*[:=]\s*-?[\d.]", code) == []
    assert re.search(r"var CURVE_Y_HEADROOM = 0\.25;", code)
    assert ".toLocaleString(" not in code


def test_theOldLightViewIsRetired_renderLightBodyStays():
    code = _code()
    for gone in ("function lightView(", "luxBand", "function fmtLux(", "freshLux",
                 "lightBandWord", "LIGHT_BAND_WORD", "function fmtAgeSec(", "renderLightCard"):
        assert gone not in code, gone
    assert "function renderLightBody(" in code
    start, end = _fnSpan(code, "renderSourceCard")
    assert "renderLightBody(" in code[start:end]


# ---------------------------------------------------------------------------
# 4. Markup + stylesheet
# ---------------------------------------------------------------------------


def _sectionTags(html: str) -> list[str]:
    return re.findall(r'<section class="card"[^>]*>', html, re.S)


def test_slot_lightIsRightAfterMotion():
    """E-2 / Iris Q6: Driving, NAV, Engine, Fuel, Motion, Light, then the
    INTERIM Alerts / System / Battery tail."""
    tags = _sectionTags(_read(_HTML))
    labels = [re.search(r'aria-label="([^"]+)"', t).group(1) for t in tags]
    assert labels == ["Driving", "Navigation", "Engine", "Fuel", "Motion", "Light",
                      "Alerts", "System Status", "Battery"]
    tag = tags[5]
    for attr in ('id="light-card"', 'data-state="light"', 'data-page-name="LIGHT"'):
        assert attr in tag, attr


def _lightRules() -> dict[str, str]:
    return {r.selector.strip(): r.declarations for r in rh.parseCss(_read(_CSS))
            if r.selector.strip().startswith("#light-card")}


def _px(token: str, css: str) -> float:
    return float(re.search(re.escape(token) + r":\s*([0-9.]+)px", css).group(1))


def test_css_tokensOnly_literalPxOnlyInTheScopedGeometry_neverTheBandBudgetNumbers():
    rules = _lightRules()
    for selector, body in rules.items():
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), selector
        assert "font-size: inherit" not in body, selector
        if selector != "#light-card":
            assert not re.search(r"\b\d+(\.\d+)?px", body), selector
    for value in re.findall(r"(\d+(?:\.\d+)?)px", rules["#light-card"]):
        assert value not in ("28", "24", "14"), value


def test_css_onlyTheWordAndTheLabelsAreMichroma_andEachSets400NoSynthesis():
    michroma = set()
    for selector, body in _lightRules().items():
        assert "--font-body" not in body, selector
        if "var(--font-display)" in body:
            michroma.add(selector)
            assert "font-weight: 400" in body and "font-synthesis: none" in body
        else:
            assert "font-family" not in body, selector
    assert michroma == {"#light-card .light-word", "#light-card .light-label",
                        "#light-card .light-status-label"}


def test_css_wordIsHeroNeutral_ambientIsPrimaryAtLeast34px_curveTextIsMetaTertiary():
    rules, tokens = _lightRules(), _read(_TOKENS)
    word = rules["#light-card .light-word"]
    assert "font-size: var(--fs-hero)" in word and "color: var(--text-primary)" in word
    assert not [s for s in rules if "light-word" in s and "data-" in s]  # never coloured
    assert _px("--fs-primary", tokens) >= 34
    assert "font-size: var(--fs-primary)" in rules["#light-card .light-ambient-value"]
    label = rules["#light-card .light-curve-label"]
    assert "font-size: var(--fs-meta)" in label and "fill: var(--text-tertiary)" in label
    assert "color: var(--amber-warn)" in rules['#light-card .light-age[data-tone="warn"]']
    assert "color: var(--amber-warn)" in rules[
        '#light-card .light-cell[data-tone="warn"] .light-cv']


def test_css_staleDimsTheDimmables_neverTheNotesOrTheStatus():
    rules = _lightRules()
    assert "opacity: var(--light-stale-opacity)" in rules[
        '#light-card .light-page[data-stale="true"] .light-dimmable']
    for selector, body in rules.items():
        if re.search(r"(?<![-\w])opacity\s*:", body):  # not the scoped --light-stale-opacity
            assert "light-dimmable" in selector, selector


def test_css_glyphStroke_isTheTextPrimaryToken_neverAColour():
    body = next(b for s, b in _lightRules().items() if ".glyph path" in s)
    for decl in ("fill: none", "stroke: var(--text-primary)", "stroke-width: 2.5",
                 "stroke-linecap: round"):
        assert decl in body, decl


def test_widthBudget_NIGHTWithItsGlyph_theWidestAmbient_andEveryStatusFit():
    """Measured: NIGHT is 197.1 px in Michroma at --fs-hero (spec s3); the
    status line's worst case is Iris G-2's mixed-tier string."""
    rules, tokens = _lightRules(), _read(_TOKENS)
    root = rules["#light-card"]
    hero, primary = _px("--fs-hero", tokens), _px("--fs-primary", tokens)
    label, meta = _px("--fs-label", tokens), _px("--fs-meta", tokens)
    left = CARD_BODY_W - _px("--light-col-gap", root) - _px("--light-curve-w", root)
    word = _px("--light-glyph", root) + _px("--light-glyph-gap", root) + michromaWidthPx(
        "NIGHT", hero)
    assert word <= left, (word, left)
    ambient = len("30,000") * ADVANCE_OBSERVED * primary + len(" lux") * ADVANCE_OBSERVED * label
    assert ambient <= left
    gap = _px("--light-notes-gap", root)
    for basis in ("auto", "fallback", "alert"):
        s = _call("lightStatusView", {"level": 1.0, "basis": basis})
        width = michromaWidthPx(s["label"], meta) + gap + len(s["value"]) * ADVANCE_OBSERVED * label
        if s["note"]:
            width += gap + len(s["note"]) * ADVANCE_OBSERVED * meta
        assert width <= CARD_BODY_W, (basis, width)


# ---------------------------------------------------------------------------
# 5. The shipped DOM
# ---------------------------------------------------------------------------


def _find(node: Any, pred) -> list[dict[str, Any]]:
    if not isinstance(node, dict):
        return []
    out = [node] if pred(node) else []
    for child in node.get("children", []) or []:
        out += _find(child, pred)
    return out


def _classes(node: dict[str, Any]) -> list[str]:
    return (node.get("attrs", {}).get("class") or "").split()


def _leafTexts(node: dict[str, Any]) -> list[str]:
    if "hidden" in node.get("attrs", {}):
        return []
    out: list[str] = []
    for child in node.get("children", []) or []:
        if "text" in child:
            if child["text"].strip():
                out.append(child["text"].strip())
        else:
            out += _leafTexts(child)
    return out


def _one(node: dict[str, Any], cls: str) -> dict[str, Any]:
    hits = _find(node, lambda n: cls in _classes(n))
    assert len(hits) == 1, (cls, len(hits))
    return hits[0]


def _text(node: dict[str, Any], cls: str) -> str:
    return " ".join(_leafTexts(_one(node, cls)))


def _run(name: str, routes: dict[str, Any] | None = None, steps: Any = None) -> dict[str, Any]:
    fx = _fixture(name)
    r = {"/light": fx["light"]}
    if fx["dtc"]:
        r["/dtc"] = fx["dtc"]
    return rh.runDashboard(routes=r if routes is None else routes, autoDim=fx["autoDim"],
                           nowMs=_ms(fx["now"]), steps=steps or [{"flush": 4}])


def _card(dom: dict[str, Any]) -> dict[str, Any]:
    roots = dom["tree"] if isinstance(dom["tree"], list) else [dom["tree"]]
    hits = [n for r in roots for n in _find(r, lambda n: n.get("attrs", {}).get("id") == "light-card")]
    assert len(hits) == 1
    return hits[0]


def _brightness(dom: dict[str, Any]) -> float:
    roots = dom["tree"] if isinstance(dom["tree"], list) else [dom["tree"]]
    screen = [n for r in roots for n in _find(r, lambda n: n.get("attrs", {}).get("id") == "screen")]
    return float(screen[0]["style"]["--display-brightness"])


@_NODE_ONLY
def test_dom_validation_day1400():
    card = _card(_run("day-1400lux"))
    assert _text(card, "light-word-row") == "DAY"
    glyph = _one(card, "light-glyph")
    assert "hidden" not in glyph["attrs"]
    assert [n["tag"] for n in glyph["children"]] == ["circle", "path"]
    assert _text(card, "light-ambient") == "1,400 lux"
    assert _text(card, "light-raw") == "IR 4,300 FULL 12,400 VISIBLE 8,100 RANGE low 100 ms"
    assert _text(card, "light-status") == "BRIGHTNESS AUTO 100 %"
    assert _one(card, "light-page")["attrs"]["data-stale"] == "false"


@_NODE_ONLY
def test_dom_validation_lightNull_dashReasonNoGlyph_defaultStatus():
    card = _card(_run("light-null"))
    assert _text(card, "light-word-row") == "--"
    assert "hidden" in _one(card, "light-glyph")["attrs"]
    assert _text(card, "light-left") == "-- AMBIENT -- no reading"
    assert _text(card, "light-status") == "BRIGHTNESS 100 % (default, no reading)"
    assert not _find(card, lambda n: "light-curve-dot" in _classes(n))
    assert _find(card, lambda n: "light-curve-line" in _classes(n))


@_NODE_ONLY
def test_dom_validation_stopOverride_alertStatus_andThePanelIsFull():
    dom = _run("stop-override")
    assert _text(_card(dom), "light-status") == "BRIGHTNESS 100 % (alert)"
    assert _brightness(dom) == pytest.approx(1.0)


@_NODE_ONLY
def test_dom_sunAtLimit_amberCells_neverTheClippedCount():
    card = _card(_run("sun-at-limit"))
    assert _text(card, "light-raw") == "IR 20,000 FULL at limit VISIBLE at limit RANGE low 100 ms"
    tones = [_one(card, c)["attrs"]["data-tone"] for c in ("light-ir", "light-full", "light-visible")]
    assert tones == ["plain", "warn", "warn"]
    assert "sensor at limit" in _text(card, "light-notes")


@_NODE_ONLY
def test_dom_validation_dotOffCurve_dotAtFull_dimmedWithItsAge_panelAtTheSameLevel():
    dom = _run("dot-off-curve")
    card = _card(dom)
    dot = _one(card, "light-curve-dot")
    assert float(dot["attrs"]["cy"]) == _y(1.0, 0.5)
    assert _one(card, "light-page")["attrs"]["data-stale"] == "true"
    assert _text(card, "light-notes") == "11 s"
    assert _one(card, "light-age")["attrs"]["data-tone"] == "warn"
    assert _brightness(dom) == pytest.approx(1.0)  # the dot and the panel agree
    for cls in ("light-word-tile", "light-curve", "light-raw"):
        assert "light-dimmable" in _classes(_one(card, cls))
    for cls in ("light-notes", "light-status"):
        assert "light-dimmable" not in _classes(_one(card, cls))


@_NODE_ONLY
def test_dom_configRetuned_NIGHT_dashedVerticalLabelledAt10():
    card = _card(_run("config-retuned-boundaries"))
    assert _text(card, "light-word-row") == "NIGHT"
    labels = [" ".join(_leafTexts(n)) for n in _find(card, lambda n: "light-curve-label" in _classes(n))]
    assert labels == ["100%", "60%", "10", "1,000 lux"]
    assert len(_find(card, lambda n: "light-curve-end" in _classes(n))) == 2


@_NODE_ONLY
def test_dom_noFeed_afterTheLoadingBound_isTheLightPagesOwnAbsence():
    fx = _fixture("dusk-22lux")
    early = _card(_run("dusk-22lux", routes={}))
    assert "LOADING" in " ".join(_leafTexts(early))
    late = _card(_run("dusk-22lux", routes={}, steps=[
        {"flush": 4}, {"advanceMs": _call("loadingGraceMs") + 4000}, {"flush": 4}]))
    assert _text(late, "light-left") == "-- AMBIENT -- no light data"
    assert _text(late, "light-status") == "BRIGHTNESS {} % (default, no reading)".format(
        round(fx["autoDim"]["defaultLevel"] * 100))
    assert not _find(late, lambda n: "light-curve-line" in _classes(n))
