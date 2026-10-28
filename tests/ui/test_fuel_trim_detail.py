################################################################################
# File Name: test_fuel_trim_detail.py
# Purpose/Description: US-890-h (F-127; specs/v030-fuel-page-design.md s3a/s3b,
#   CIO 2026-10-27) -- the Fuel glance cut and the FUEL TRIM detail it opens on
#   US-894-g's shared page-detail host.
#
#   What is pinned here:
#     - the exit test: the glance has neither TOTAL TRIM nor the trend; a
#       parked tap on FUEL TRIM › opens the detail with both; not parked, the
#       button is hidden and a tap opens nothing;
#     - the button is the shared detail button with no state colour;
#     - the vehicle gate reaches the moved trend (sourceCardSpec slotHost):
#       (a) source.obd.available false + detail open -> 'no engine data' in
#       the detail and no %, (b) the card carries data-gated="true", (c)
#       closed-loop-trim parked -> the detail shows the summed TOTAL TRIM and
#       its loop word; and the gate keeps painting while another detail has
#       detached #fuel-detail from the host's body;
#     - R1: leaving parked closes the detail and the Fuel page shows;
#     - the detail declares NO host geometry (no --pd-* of its own);
#     - Q1 (Atlas S119 gate): MODELLED height budgets from the DECLARED
#       CSS/tokens -- the glance <= the 254 px card body charging every line
#       any MPG state can show at once (so the 'resetting…', "couldn't
#       confirm" and widest-reason fit cases are bounded by it), and the
#       detail <= the host's 270 px body -- each with a planted-overflow
#       negative control that FAILS; widths from michroma-advances.json and
#       the Pi's mono advance.
#
#   Skipped when node is not on PATH -- the CSS models always run.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-27    | Ralph (Rex)  | Initial -- US-890-h FUEL TRIM › + FUEL TRIM detail.
# ================================================================================
################################################################################

"""US-890-h tests: the Fuel glance cut and the FUEL TRIM detail."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

from tests.ui.test_carousel_kebab_always_visible import (  # noqa: E402
    _driving,
    _gearMoving,
    _gearParked,
    _parked,
)
from tests.ui.test_engine_page import _bodyHeightPx, _bodyWidthPx, _buttonHeight  # noqa: E402
from tests.ui.test_system_last_updated import _bodyHeight, _geometry  # noqa: E402
from tests.ui.test_topbar_three_column_grid import (  # noqa: E402
    PI_MONO_ADVANCE_EM,
    michromaWidthPx,
)

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped carousel.js",
)

PANEL = (480, 320)
_DASH = rh.DASHBOARD_DIR
_JS = os.path.join(_DASH, "carousel.js")
_CSS = os.path.join(_DASH, "dashboard.css")
_HTML = os.path.join(_DASH, "dashboard.html")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "fuel")

TITLE = "FUEL TRIM"
BUTTON = "FUEL TRIM"
TREND_LABEL = "FUEL TRIM TREND"
GATED_REASON = "no engine data"
FUEL_DOT = 3  # Driving, Navigation, Engine, Fuel (E-2 order)
STATE_TOKENS = ("--amber-warn", "--green-ok", "--critical-red")

_HOLD_PARKED = [{"flush": 4}, {"advanceMs": 9000, "flush": 4}]
_TO_FUEL = [{"clickNth": {"selector": ".dot", "index": FUEL_DOT}}, {"flush": 2}]
_OPEN = [{"click": "fuel-trim-btn"}, {"flush": 2}]


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
    from datetime import datetime

    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _routes(
    trend: str = "trend-healthy", obd: str = "closed-loop-trim", system: Any = None
) -> dict[str, Any]:
    return {
        "/ltft-trend": _fixture(trend)["ltft-trend"],
        "/obd-live": _fixture(obd)["obd-live"],
        "/system-status": _driving() if system is None else system,
    }


def _render(
    routes: dict[str, Any], *, parked: bool, steps: list[dict[str, Any]] | None = None
) -> rh.Surface:
    routes = dict(routes)
    routes["/gear"] = _gearParked() if parked else _gearMoving()
    allSteps = _HOLD_PARKED + _TO_FUEL + (steps or [])
    nowMs = _ms(_fixture("closed-loop-trim")["now"])
    tree = rh.runDashboard(routes=routes, steps=allSteps, viewport=PANEL, nowMs=nowMs)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _text(node: dict[str, Any]) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _text(child))
    return "".join(out)


def _classes(node: dict[str, Any]) -> list[str]:
    return (node.get("attrs", {}).get("class") or "").split()


def _detailOpen(surface: rh.Surface) -> bool:
    path = surface.pathById("page-detail")
    assert path is not None
    return path[-1]["attrs"].get("hidden") is None


def _inside(surface: rh.Surface, ancestorId: str, cls: str) -> list[list[dict[str, Any]]]:
    return [
        p for p in surface.pathsByClass(cls)
        if any(n.get("attrs", {}).get("id") == ancestorId for n in p)
    ]


def _pageName(surface: rh.Surface) -> str:
    path = surface.pathById("page-name")
    assert path is not None
    return _text(path[-1]).strip()


def _button(surface: rh.Surface) -> list[dict[str, Any]]:
    path = surface.pathById("fuel-trim-btn")
    assert path is not None, "no FUEL TRIM › button"
    return path


def _slotText(surface: rh.Surface, slotCls: str, cls: str) -> str:
    (path,) = [
        p for p in _inside(surface, "fuel-detail", cls) if any(slotCls in _classes(n) for n in p)
    ]
    return _text(path[-1])


# ---------------------------------------------------------------------------
# The exit test, and the button.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_fuel_glance_has_no_total_trim_or_trend():
    """Spec s3a/s3b: the glance has neither; a parked tap shows both in the
    FUEL TRIM detail; unparked, the button is hidden and a tap opens nothing."""
    opened = _render(_routes(), parked=True, steps=_OPEN)
    # The glance: neither TOTAL TRIM nor the trend anywhere in the card.
    assert _inside(opened, "fuel-card", "fuel-total-trim") == []
    assert _inside(opened, "fuel-card", "fuel-trend") == []
    # The detail: open, titled, in the host's body, and showing both.
    assert _detailOpen(opened)
    assert _text(opened.pathById("page-detail-title")[-1]) == TITLE
    body = opened.pathById("page-detail-body")
    detail = opened.pathById("fuel-detail")
    assert detail is not None and detail[: len(body)] == body, "the detail is not in the host's body"
    assert opened.rendered(detail)
    (trim,) = _inside(opened, "fuel-detail", "fuel-total-trim")
    (trend,) = _inside(opened, "fuel-detail", "fuel-trend")
    assert opened.rendered(trim) and opened.rendered(trend)
    assert TREND_LABEL in _text(trend[-1])

    back = _render(_routes(), parked=True, steps=_OPEN + [{"click": "page-detail-back"}, {"flush": 1}])
    assert not _detailOpen(back)
    assert _pageName(back) == "FUEL"

    unparked = _render(_routes(), parked=False, steps=_OPEN)
    assert not _detailOpen(unparked)
    btn = _button(unparked)
    assert btn[-1]["attrs"].get("data-parked") == "false"
    assert unparked.winningDeclaration(btn, "visibility")[0] == "hidden"
    assert unparked.displayOf(btn)[0] != "none", "its space is kept"


@_NODE_ONLY
def test_theButton_saysFuelTrim_andSitsBottomRightOfTheGlance():
    surface = _render(_routes(), parked=True)
    btn = _button(surface)
    assert _text(btn[-1]) == BUTTON + " ›"
    assert btn[-1]["attrs"].get("data-parked") == "true"
    visibility = surface.winningDeclaration(btn, "visibility")
    assert visibility is None or visibility[0] == "visible", visibility
    assert any(n.get("attrs", {}).get("id") == "fuel-card" for n in btn)
    assert "fuel-actions" in _classes(btn[-2])
    actions = " ".join(r.declarations for r in rh.parseCss(_read(_CSS))
                       if r.selector.strip() == "#fuel-card .fuel-actions")
    assert rh.declarationOf(actions, "justify-content")[0] == "flex-end"


@_NODE_ONLY
def test_theButton_hasNoStateColour_cascade():
    surface = _render(_routes(), parked=True)
    btn = _button(surface)
    assert surface.winningDeclaration(btn, "color")[0] == "var(--text-primary)"
    border = surface.winningDeclaration(btn, "border")
    assert border is not None and border[0] == "1px solid var(--text-secondary)"
    assert surface.winningDeclaration(btn, "border-color") is None
    for rule in rh.parseCss(_read(_CSS)):
        if rule.selector and rh.isResolvable(rule.selector) and rh.matchesSelector(rule.selector, btn):
            for token in STATE_TOKENS:
                assert token not in rule.declarations, (rule.selector, token)


def test_theButtonIsTheSharedKit_andTheMarkupHoldsNoFuelTrimLabel():
    """The label is built by carousel.js, so test_fuel_page.py's retired-card
    pin ('FUEL TRIM\"' never in the markup) still holds."""
    js = _read(_JS)
    assert re.search(
        r"appendPageDetailButton\(\s*fuelActions,\s*FUEL_TRIM_BUTTON,\s*fuelTrimDetail\s*\)", js
    )
    assert 'var FUEL_TRIM_BUTTON = "FUEL TRIM";' in js
    assert 'var FUEL_TRIM_TITLE = "FUEL TRIM";' in js
    markup = re.sub(r"<!--.*?-->", "", _read(_HTML), flags=re.S)
    assert "FUEL TRIM\"" not in markup and "Fuel Trim" not in markup


def test_theDetailShipsInTheHostsBody_andTheGlanceMarkupIsCut():
    html = _read(_HTML)
    body = html.index('<div id="page-detail-body"')
    assert body < html.index('<div id="fuel-detail"') < html.index('<div id="clear-confirm"')
    card = re.search(r'<section class="card"[^>]*id="fuel-card".*?</section>', html, re.S)
    assert card is not None
    assert "fuel-total-trim" not in card.group(0)
    assert "fuel-trend" not in card.group(0)
    detail = html[html.index('<div id="fuel-detail"'):]
    # TOTAL TRIM first, the LOOP chip beside it, then the trend.
    assert detail.index("fuel-total-trim") < detail.index("fuel-loop") < detail.index("fuel-trend")


# ---------------------------------------------------------------------------
# The vehicle gate reaches the moved trend (Iris S119 review; Fuel s3b).
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_gate_aBenchSpeaksNoEngineDataInTheDetail_andTheCardIsGated():
    """(a) source.obd.available false + detail open -> the gate text in the
    detail's trend, no %; (b) the card is data-gated="true"."""
    surface = _render(_routes(system=_parked()), parked=True, steps=_OPEN)
    assert _detailOpen(surface)
    (trend,) = _inside(surface, "fuel-detail", "fuel-trend")
    text = _text(trend[-1])
    assert GATED_REASON in text, text
    assert "%" not in text, text
    assert _inside(surface, "fuel-detail", "fuel-trend-dot") == []
    card = surface.pathById("fuel-card")
    assert card[-1]["attrs"].get("data-gated") == "true"


@_NODE_ONLY
def test_gate_closedLoopTrimParked_detailShowsTheSummedTrimAndItsLoopWord():
    """(c) closed-loop-trim: the provider's summed TOTAL TRIM (+1.5 %) beside
    CLOSED LOOP, and the open gate paints the trend's headline."""
    surface = _render(_routes(), parked=True, steps=_OPEN)
    assert _slotText(surface, "fuel-total-trim", "fuel-value") == "+1.5 %"
    assert _slotText(surface, "fuel-loop", "fuel-value") == "CLOSED LOOP"
    assert surface.pathById("fuel-card")[-1]["attrs"].get("data-gated") == "false"
    assert _inside(surface, "fuel-detail", "fuel-trend-row") != []


@_NODE_ONLY
def test_gate_keepsPaintingWhileAnotherDetailHasDetachedTheTrend():
    """ENGINE HISTORY's paint empties the host's body, detaching #fuel-detail;
    the bench goes live while it is open, and the card still un-gates.
    LIMIT, stated: mini_dom's getElementById also finds a DETACHED node (a
    by-id mutant passes here), so this pins the behaviour, not the held
    reference that gives it in a real browser (sourceSlotHost's comment)."""
    steps = [
        {"click": "engine-history-btn"}, {"flush": 2},
        {"setRoutes": {"/system-status": _driving()}}, {"flush": 4},
    ]
    surface = _render(_routes(system=_parked()), parked=True, steps=steps)
    assert _text(surface.pathById("page-detail-title")[-1]) == "ENGINE HISTORY"
    assert surface.pathById("fuel-detail") is None, "the trend should be detached here"
    assert surface.pathById("fuel-card")[-1]["attrs"].get("data-gated") == "false"


def test_sourceCardSpec_namesTheDetailAsTheSlotHost():
    js = _read(_JS)
    assert re.search(
        r'key: "ltft-trend", title: "Fuel", slot: "\.fuel-trend", slotHost: "fuel-detail",', js
    )
    body = rh._fnBody(js, "renderSourceCard")
    assert "spec.slotHost" in body and "sourceSlotHost(" in body


# ---------------------------------------------------------------------------
# R1 -- leaving parked closes the detail and the Fuel page shows.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_R1_gearD_closesTheDetail_andTheFuelPageShows():
    leaving = _OPEN + [{"setRoutes": {"/gear": _gearMoving()}}, {"flush": 2}]
    held = _render(_routes(), parked=True, steps=leaving + [{"advanceMs": 1000, "flush": 4}])
    assert _detailOpen(held), "still parked 1 s in (the debounce): the detail stays"
    closed = _render(_routes(), parked=True, steps=leaving + [{"advanceMs": 3500, "flush": 4}])
    assert not _detailOpen(closed)
    assert _pageName(closed) == "FUEL"
    assert _button(closed)[-1]["attrs"].get("data-parked") == "false"


def test_theDetailDeclaresNoHostGeometry():
    """Consumes US-894-g's host: no Fuel rule touches #page-detail or a --pd-*
    property, and the host's body is still 270."""
    for rule in rh.parseCss(_read(_CSS)):
        if "fuel" in rule.selector:
            assert "page-detail" not in rule.selector, rule.selector
            assert "--pd-" not in rule.declarations.replace("var(--pd-", ""), rule.selector
    assert _bodyHeight() == 270


# ---------------------------------------------------------------------------
# Q1 -- the modelled height budgets (glance 254, detail 270).
# ---------------------------------------------------------------------------


def _rules(css: str | None = None) -> list[tuple[str, str]]:
    return [(r.selector.strip(), r.declarations) for r in rh.parseCss(css or _read(_CSS))]


def _rule(selector: str, css: str | None = None) -> str:
    bodies = [body for sel, body in _rules(css) if sel == selector]
    assert bodies, f"no rule {selector!r}"
    return " ".join(bodies)


def _decl(selector: str, prop: str, css: str | None = None) -> str:
    found = rh.declarationOf(_rule(selector, css), prop)
    assert found is not None, (selector, prop)
    return found[0]


def _scoped(root: str, css: str | None = None) -> dict[str, str]:
    block = _rule(root, css)
    return {n: v.strip() for n, v in re.findall(r"(--fuel-[\w-]+)\s*:\s*([^;]+);", block)}


def _px(value: str, root: str, css: str | None = None) -> float:
    value = value.strip()
    var = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if var:
        name = var.group(1)
        scoped = _scoped(root, css)
        if name in scoped:
            return _px(scoped[name], root, css)
        found = re.search(rf"^\s*{re.escape(name)}:\s*([0-9.]+)px", _read(_CSS), re.M)
        assert found is not None, f"{name} does not resolve to px"
        return float(found.group(1))
    m = re.fullmatch(r"([0-9.]+)px", value)
    assert m is not None, f"{value!r} is not a px length"
    return float(m.group(1))


def _number(value: str, root: str, css: str | None = None) -> float:
    var = re.fullmatch(r"var\((--fuel-[\w-]+)\)", value.strip())
    return float(_scoped(root, css)[var.group(1)] if var else value)


def _lineBox(root: str, sizeVar: str, css: str | None = None) -> float:
    """A line at ``sizeVar``, charged the scoped --fuel-line (never `normal`)."""
    return _px(sizeVar, root, css) * _number("var(--fuel-line)", root, css)


def _textLine(root: str, cls: str, css: str | None = None) -> float:
    """One line of a `.cls` rule, its declared font-size and line-height."""
    sel = f"{root} .{cls}"
    assert _decl(sel, "line-height", css) == "var(--fuel-line)", sel
    return _px(_decl(sel, "font-size", css), root, css) * _number("var(--fuel-line)", root, css)


def _chip(root: str, css: str | None = None) -> float:
    sel = f"{root} .fuel-chip"
    pad = _decl(sel, "padding", css).split()[0]
    return (
        _lineBox(root, _decl(sel, "font-size", css), css)
        + 2 * _px(pad, root, css)
        + 2 * _px(_decl(sel, "border-width", css), root, css)
    )


def _gap(selector: str, root: str, css: str | None = None) -> float:
    return _px(_decl(selector, "gap", css), root, css)


def _ruled(selector: str, root: str, css: str | None = None) -> float:
    """A band's own top rule + padding-top."""
    return _px(_decl(selector, "border-top-width", css), root, css) + _px(
        _decl(selector, "padding-top", css), root, css
    )


def _glanceHeight(css: str | None = None) -> float:
    """The glance at its tallest: EVERY line any state can show at once is
    charged together (airflow note shown; each MPG slot's note, flag, reset
    line and hold bar all shown), so 'resetting…', "couldn't confirm" and the
    widest reasons -- each one line, see the width test -- are inside it."""
    root = "#fuel-card"
    label = _textLine(root, "fuel-label", css)
    note = _textLine(root, "fuel-note", css)
    hero = _lineBox(root, _decl("#fuel-card .fuel-airflow .fuel-value", "font-size", css), css)
    airflow = label + hero + note + _px("var(--fuel-bar-h)", root, css)
    side = label + _chip(root, css) + note
    meta = _textLine(root, "fuel-flag", css)
    reset = _textLine(root, "fuel-reset-line", css)
    progress = _px("var(--fuel-reset-progress-h)", root, css)
    primary = _lineBox(root, _decl("#fuel-card .fuel-value", "font-size", css), css)
    secondary = _lineBox(root, _decl("#fuel-card .fuel-mpg-this-drive .fuel-value", "font-size", css), css)
    assert _decl("#fuel-card .fuel-mpg-since-reset .fuel-value", "font-size", css) == "var(--fs-secondary)"
    last30 = label + primary + note
    thisDrive = label + secondary + meta + note
    sinceReset = label + secondary + note + reset + progress
    mpg = _ruled("#fuel-card .fuel-mpg", root, css) + max(last30, thisDrive, sinceReset)
    gap = _gap("#fuel-card .card-body", root, css)
    # Three flex children (top, MPG, actions); the confirm is absolute.
    return max(airflow, side) + gap + mpg + gap + _buttonHeight()


def _detailHeight(withNote: bool, css: str | None = None) -> float:
    """TOTAL TRIM + LOOP (the taller, its note when shown), the gap, the trend
    under its rule: one row of label | value | chart (the width test proves it
    does not wrap)."""
    root = "#fuel-detail"
    label = _textLine(root, "fuel-label", css)
    note = _textLine(root, "fuel-note", css) if withNote else 0.0
    trim = label + _lineBox(root, _decl("#fuel-detail .fuel-value", "font-size", css), css) + note
    loop = label + _chip(root, css) + note
    row = max(
        label,
        _textLine(root, "fuel-trend-value", css),
        _textLine(root, "fuel-trend-reason", css),
        _px(_decl("#fuel-detail .fuel-trend-chart", "height", css), root, css),
    )
    trend = _ruled("#fuel-detail .fuel-trend", root, css) + row
    return max(trim, loop) + _gap("#fuel-detail", root, css) + trend


def test_glance_fitsThe254Body_atItsTallest():
    body = _bodyHeightPx()
    assert body == 254
    height = _glanceHeight()
    assert height <= body, (height, body)


def test_glance_theFullCase_chargesEveryTerm():
    """airflow 18 + 52.8 + 18 + bar 10 = 98.8; gap 6; MPG rule 1 + pad 6 +
    SINCE RESET 18 + 31.2 + 18 + 18 + 3 = 95.2; gap 6; button 40 = 246."""
    assert _glanceHeight() == pytest.approx(246)


def test_glance_aPlantedOverflow_fails():
    css = _read(_CSS).replace("--fuel-bar-h: 10px;", "--fuel-bar-h: 20px;")
    assert css != _read(_CSS)
    assert _glanceHeight(css) > _bodyHeightPx()


@pytest.mark.parametrize("withNote", [True, False], ids=["open-loop-note", "closed-loop"])
def test_detail_fitsThe270Body(withNote: bool):
    """Spec s3b: ~133 of 270 by its arithmetic; modelled, <= 270."""
    body = _bodyHeight()
    assert body == 270
    assert _detailHeight(withNote) <= body


def test_detail_theFullCase_chargesEveryTerm():
    """TOTAL TRIM 18 + 40.8 + note 18 = 76.8; gap 6; rule 1 + pad 6 + the
    trend row at its value line 31.2 = 38.2 -> 121."""
    assert _detailHeight(True) == pytest.approx(121)


def test_detail_aPlantedOverflow_fails():
    css = _read(_CSS).replace("--fuel-trend-h: 30px;", "--fuel-trend-h: 300px;")
    assert css != _read(_CSS)
    assert _detailHeight(True, css) > _bodyHeight()


# ---------------------------------------------------------------------------
# Widths -- each line's widest case against its column (a wrap is caught).
# ---------------------------------------------------------------------------


def _mono(text: str, sizePx: float) -> float:
    return len(text) * sizePx * PI_MONO_ADVANCE_EM


def _detailWidth() -> float:
    return 480 - 2 * _geometry()["bodyPadX"]


def test_width_theButton_andTheTitle_fit():
    root = "#fuel-card"
    label = _px("var(--fs-label)", root)
    button = michromaWidthPx(BUTTON, label) + _mono(" ›", label) + 2 * 12 + 2 * 1
    assert button == pytest.approx(199, abs=1)  # the spec's 199 px
    assert michromaWidthPx(TITLE, label) <= _detailWidth() - _px("var(--tap-min)", root)


def test_width_theTrimRow_fitsTheDetail_andAPlantedWideNoteFails():
    root = "#fuel-detail"
    meta = _px("var(--fs-meta)", root)
    trim = max(_mono("−25.0 %", _px("var(--fs-primary)", root)), _mono("not applied in open loop", meta))
    chip = (_mono("CLOSED LOOP", _px("var(--fs-label)", root))
            + 2 * _px("var(--fuel-chip-pad-x)", root) + 2 * _px("var(--fuel-rule)", root))
    gap = _gap("#fuel-detail .fuel-trim-row", root)
    assert trim + gap + chip <= _detailWidth()
    wide = _mono("not applied in open loop" * 2, meta)
    assert not (wide + gap + chip <= _detailWidth())


def test_width_theTrendRow_staysOneLine_atItsWidestReason():
    root = "#fuel-detail"
    meta = _px("var(--fs-meta)", root)
    gap = _gap("#fuel-detail .fuel-trend-row", root)
    label = _mono(TREND_LABEL, meta)
    widest = max(
        _mono("−25.00%", _px("var(--fs-secondary)", root)),
        _mono("not enough qualifying drives yet", meta),
    )
    assert label + gap + widest <= _detailWidth()


def test_width_theGlanceFitCaseTexts_areOneLineEach():
    """The fit-case texts the glance model charges as ONE line each. The
    reasons fit their column; the reset line is nowrap, so it stays one line
    whatever its width. "couldn't confirm" (US-890-f) is 144.5 px at the Pi's
    mono advance in a 141.3 px column: it overflows by ~3 px sideways (no
    height cost), pre-existing, reported to the PM rather than fixed here."""
    root = "#fuel-card"
    col = (_bodyWidthPx() - 2 * _px(_decl("#fuel-card .fuel-mpg", "gap"), root)) / 3
    meta = _px("var(--fs-meta)", root)
    for text in ("resetting…", "no fuel counted", "too many gaps"):
        assert _mono(text, meta) <= col, text
    assert _decl("#fuel-card .fuel-reset-line", "white-space") == "nowrap"
    assert _mono("couldn't confirm", meta) > col  # recorded, not hidden
