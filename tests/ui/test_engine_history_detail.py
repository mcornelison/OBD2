################################################################################
# File Name: test_engine_history_detail.py
# Purpose/Description: US-889-d (F-127; specs/v030-engine-page-design.md s3a/s3b,
#   CIO option B 2026-10-27) -- the Engine page's HISTORY › button and the
#   ENGINE HISTORY detail it opens on US-894-g's shared page-detail host.
#
#   What is pinned here:
#     - the exit test: parked, a tap on HISTORY › opens ENGINE HISTORY with the
#       three charts and the status row, and '‹ BACK' returns to the Engine
#       page; not parked, the button is hidden and a tap opens nothing;
#     - the button is the shared detail button (US-894-g) with no state colour:
#       its winning colour --text-primary, its border --text-secondary;
#     - the detail's geometry is scoped to #engine-detail (the card's --eng-*
#       would not reach the shared host): --eng-graph-h resolves on the chart
#       where it renders, and the detail paints from the provider;
#     - the detail declares NO host geometry (no --pd-* of its own);
#     - R1: leaving parked closes the detail and the Engine page shows;
#     - Q1 (Atlas S119 gate): a MODELLED height budget from the DECLARED
#       CSS/tokens -- every charged line its declared line-height token, never
#       `normal` -- for the fit cases mil-on-twelve-codes + fan-cycle-history
#       and history-empty-after-restart, inside the host's 270 px body, with a
#       planted-overflow negative control that FAILS.
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
# 2026-10-27    | Ralph (Rex)  | Initial -- US-889-d HISTORY › + ENGINE HISTORY.
# ================================================================================
################################################################################

"""US-889-d tests: the HISTORY › button and the ENGINE HISTORY detail."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

from tests.ui.test_carousel_kebab_always_visible import (  # noqa: E402
    _gearMoving,
    _gearParked,
)
from tests.ui.test_system_last_updated import (  # noqa: E402
    _bodyHeight,
    _geometry,
)
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
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "engine")

TITLE = "ENGINE HISTORY"
BUTTON = "HISTORY"
SERIES_LABELS = ["COOLANT", "INTAKE AIR", "BATTERY"]
ABSENCE = "History not recorded yet. It starts with this drive's first readings."
ENGINE_DOT = 2  # Driving, Navigation, Engine (E-2 order)
STATE_TOKENS = ("--amber-warn", "--green-ok", "--critical-red")

_HOLD_PARKED = [{"flush": 4}, {"advanceMs": 9000, "flush": 4}]
_TO_ENGINE = [{"clickNth": {"selector": ".dot", "index": ENGINE_DOT}}, {"flush": 2}]
_OPEN = [{"click": "engine-history-btn"}, {"flush": 2}]


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


def _probe(fn: str, *args: object) -> Any:
    cmd = [_NODE or "node", _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, TZ="UTC")
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _routes(history: str = "fan-cycle-history", mil: str = "mil-on-twelve-codes") -> dict[str, Any]:
    return {
        "/engine-history": _fixture(history)["engine-history"],
        "/obd-live": _fixture(mil)["obd-live"],
    }


def _render(
    routes: dict[str, Any], *, parked: bool, steps: list[dict[str, Any]] | None = None
) -> rh.Surface:
    routes = dict(routes)
    routes["/gear"] = _gearParked() if parked else _gearMoving()
    allSteps = _HOLD_PARKED + _TO_ENGINE + (steps or [])
    nowMs = _ms(_fixture("fan-cycle-history")["now"])
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
    path = surface.pathById("engine-history-btn")
    assert path is not None, "no HISTORY › button"
    return path


# ---------------------------------------------------------------------------
# The exit test, and the button.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_engine_history_button_opens_detail_when_parked():
    """Parked tap -> ENGINE HISTORY with the charts + the status row; '‹ BACK'
    returns to the Engine page. Unparked -> hidden, and a tap opens nothing."""
    opened = _render(_routes(), parked=True, steps=_OPEN)
    assert _detailOpen(opened)
    assert _text(opened.pathById("page-detail-title")[-1]) == TITLE
    body = opened.pathById("page-detail-body")
    detail = opened.pathById("engine-detail")
    assert detail is not None and detail[: len(body)] == body, "the detail is not in the host's body"
    assert opened.rendered(detail)
    charts = _inside(opened, "engine-detail", "eng-hist")
    labels = [
        _text(next(c for c in p[-1]["children"] if "eng-hist-head" in _classes(c))["children"][0])
        for p in charts
    ]
    assert labels == SERIES_LABELS
    assert len(_inside(opened, "engine-detail", "eng-hist-chart")) == 3
    (status,) = _inside(opened, "engine-detail", "eng-status")
    assert opened.rendered(status)
    assert [p[-1]["attrs"]["data-pid"] for p in _inside(opened, "engine-detail", "eng-stat")] == [
        "RUNTIME_SEC", "MIL_ON",
    ]
    # The history + status appear only in the detail, never on the card.
    assert _inside(opened, "engine-card", "eng-history") == []
    assert _inside(opened, "engine-card", "eng-status") == []

    back = _render(_routes(), parked=True, steps=_OPEN + [{"click": "page-detail-back"}, {"flush": 1}])
    assert not _detailOpen(back)
    assert _pageName(back) == "ENGINE"

    unparked = _render(_routes(), parked=False, steps=_OPEN)
    assert not _detailOpen(unparked)
    btn = _button(unparked)
    assert btn[-1]["attrs"].get("data-parked") == "false"
    assert unparked.winningDeclaration(btn, "visibility")[0] == "hidden"
    assert unparked.displayOf(btn)[0] != "none", "its space is kept"


@_NODE_ONLY
def test_theButton_saysHistory_andIsVisibleWhenParked():
    surface = _render(_routes(), parked=True)
    btn = _button(surface)
    assert _text(btn[-1]) == BUTTON + " ›"
    assert btn[-1]["attrs"].get("data-parked") == "true"
    visibility = surface.winningDeclaration(btn, "visibility")
    assert visibility is None or visibility[0] == "visible", visibility
    # It sits in the card's action row, after the readings (bottom right).
    assert any(n.get("attrs", {}).get("id") == "engine-card" for n in btn)
    assert "eng-actions" in _classes(btn[-2])


@_NODE_ONLY
def test_theButton_hasNoStateColour_cascade():
    """AC: winning colour --text-primary, border colour --text-secondary; no
    rule that can reach the button carries a state token."""
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


def test_theButtonIsTheSharedKit_wiredOnce():
    js = _read(_JS)
    assert js.count("appendPageDetailButton(") == 2  # the definition + this call
    assert re.search(
        r"appendPageDetailButton\(\s*engineActions,\s*ENGINE_HISTORY_BUTTON,\s*engineHistoryDetail\s*\)",
        js,
    )
    assert 'var ENGINE_HISTORY_BUTTON = "HISTORY";' in js
    assert 'var ENGINE_HISTORY_TITLE = "ENGINE HISTORY";' in js


# ---------------------------------------------------------------------------
# The detail paints from the provider, on its own scoped geometry.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_theDetail_paintsFromTheProvider_notEmpty():
    surface = _render(_routes(), parked=True, steps=_OPEN)
    lines = _inside(surface, "engine-detail", "eng-hist-line")
    assert lines, "no history line in the open detail"
    assert _inside(surface, "engine-detail", "eng-absence") == []
    view = _probe("engineHistoryView", _fixture("fan-cycle-history")["engine-history"])
    ends = [_text(p[-1]) for p in _inside(surface, "engine-detail", "eng-hist-value")]
    assert ends == [s["end"]["text"] for s in view["series"]]
    codes = surface.pathById("engine-codes")
    assert codes is not None and _text(codes[-1]) == "12 codes ›" and surface.rendered(codes)


@_NODE_ONLY
def test_engGraphH_resolvesOnTheChart_whereItRenders():
    """--eng-* scoped to #engine-card would not reach the shared host: the
    chart's height token resolves on an ancestor INSIDE the detail."""
    surface = _render(_routes(), parked=True, steps=_OPEN)
    chart = _inside(surface, "engine-detail", "eng-hist-chart")[0]
    assert surface.winningDeclaration(chart, "height")[0] == "var(--eng-graph-h)"
    resolved = None
    for depth in range(len(chart), 0, -1):
        found = surface.winningDeclaration(chart[:depth], "--eng-graph-h")
        if found is not None:
            resolved = (chart[depth - 1].get("attrs", {}).get("id"), found[0])
            break
    assert resolved == ("engine-detail", "40px"), resolved
    # The card's own scope does not declare it (nothing there renders a chart).
    card = surface.pathById("engine-card")
    assert surface.winningDeclaration(card, "--eng-graph-h") is None


def test_theDetailDeclaresNoHostGeometry():
    """Consumes US-894-g's host: no Engine rule touches #page-detail or a
    --pd-* property, and the host's own block is unchanged."""
    for rule in rh.parseCss(_read(_CSS)):
        if "eng-" in rule.selector or "engine" in rule.selector:
            assert "page-detail" not in rule.selector, rule.selector
            assert "--pd-" not in rule.declarations.replace("var(--pd-", ""), rule.selector
    assert _bodyHeight() == 270


def test_theDetailShipsInTheHostsBody():
    html = _read(_HTML)
    body = html.index('<div id="page-detail-body"')
    assert body < html.index('<div id="engine-detail"') < html.index('<div id="clear-confirm"')
    js = _read(_JS)
    assert re.search(r"renderEngineScroll\(\s*engineDetail,", js)


# ---------------------------------------------------------------------------
# R1 -- leaving parked closes the detail and the Engine page shows.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_R1_gearD_closesTheDetail_andTheEnginePageShows():
    leaving = _OPEN + [{"setRoutes": {"/gear": _gearMoving()}}, {"flush": 2}]
    held = _render(_routes(), parked=True, steps=leaving + [{"advanceMs": 1000, "flush": 4}])
    assert _detailOpen(held), "still parked 1 s in (the debounce): the detail stays"
    closed = _render(_routes(), parked=True, steps=leaving + [{"advanceMs": 3500, "flush": 4}])
    assert not _detailOpen(closed)
    assert _pageName(closed) == "ENGINE"
    assert _button(closed)[-1]["attrs"].get("data-parked") == "false"


@_NODE_ONLY
def test_theCodesTap_stillGoesToWarnings_andClosesTheDetail():
    surface = _render(_routes(), parked=True, steps=_OPEN + [{"click": "engine-codes"}, {"flush": 2}])
    assert not _detailOpen(surface)
    assert _pageName(surface) == "ALERTS"


# ---------------------------------------------------------------------------
# Q1 -- the modelled height budget of the detail (270 px body).
# ---------------------------------------------------------------------------


def _rules(css: str | None = None) -> list[tuple[str, str]]:
    return [(r.selector.strip(), r.declarations) for r in rh.parseCss(css or _read(_CSS))]


def _rule(selector: str, css: str | None = None) -> str:
    bodies = [body for sel, body in _rules(css) if sel == selector]
    assert bodies, f"no rule {selector!r}"
    return " ".join(bodies)


def _decl(body: str, prop: str) -> str | None:
    found = rh.declarationOf(body, prop)
    return None if found is None else found[0]


def _scoped(css: str | None = None) -> dict[str, str]:
    block = _rule("#engine-detail", css)
    return {n: v.strip() for n, v in re.findall(r"(--eng-[\w-]+)\s*:\s*([^;]+);", block)}


def _px(value: str, css: str | None = None) -> float:
    value = value.strip()
    var = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if var:
        name = var.group(1)
        scoped = _scoped(css)
        if name in scoped:
            return _px(scoped[name], css)
        root = re.search(rf"^\s*{re.escape(name)}:\s*([0-9.]+)px", _read(_CSS), re.M)
        assert root is not None, f"{name} does not resolve to px"
        return float(root.group(1))
    m = re.fullmatch(r"([0-9.]+)px", value)
    assert m is not None, f"{value!r} is not a px length"
    return float(m.group(1))


def _number(value: str, css: str | None = None) -> float:
    var = re.fullmatch(r"var\((--eng-[\w-]+)\)", value.strip())
    return float(_scoped(css)[var.group(1)] if var else value)


# Every rule whose line box the detail model charges: each declares an
# explicit line-height token, never `normal` (the Pi renders the mono stack in
# Liberation Mono, 30 px at 26 px under `normal`; the bench renders Consolas).
_CHARGED = {
    "label": "#engine-detail .eng-label",
    "window": "#engine-detail .eng-hist-window",
    "end": "#engine-detail .eng-hist-end",
    "absence": "#engine-detail .eng-absence",
    "value": "#engine-detail .eng-stat-value",
    "codes": "#engine-detail .eng-codes",
    "note": "#engine-detail .eng-note",
}


def _line(key: str, css: str | None = None) -> float:
    body = _rule(_CHARGED[key], css)
    return _px(_decl(body, "font-size") or "", css) * _number(_decl(body, "line-height") or "", css)


def test_everyChargedLine_declaresALineHeightToken_neverNormal():
    for key, selector in _CHARGED.items():
        assert _decl(_rule(selector), "line-height") == "var(--eng-line)", key
    assert _number("var(--eng-line)") > 1


def _detailWidth() -> float:
    return 480 - 2 * _geometry()["bodyPadX"]


def _lines(text: str, sizePx: float, width: float) -> int:
    """Greedy word wrap in the fixed-width face."""
    count, line = 1, ""
    for word in text.split(" "):
        trial = f"{line} {word}" if line else word
        if len(trial) * sizePx * PI_MONO_ADVANCE_EM <= width:
            line = trial
        else:
            count, line = count + 1, word
    return count


def _absenceHeight(text: str, css: str | None = None) -> float:
    size = _px(_decl(_rule(_CHARGED["absence"], css), "font-size") or "", css)
    return _lines(text, size, _detailWidth()) * _line("absence", css)


def _historyHeight(view: dict[str, Any], css: str | None = None) -> float:
    if view["empty"]:
        return _absenceHeight(view["absence"], css)
    head = max(_line("label", css), _line("window", css))
    chart = _px(_decl(_rule("#engine-detail .eng-hist-chart", css), "height") or "", css)
    gap = _px(_decl(_rule("#engine-detail .eng-history", css), "gap") or "", css)
    boxes = []
    for series in view["series"]:
        if series["empty"]:
            # A series with no points is the typed absence, never a chart.
            boxes.append(head + _absenceHeight(ABSENCE, css))
        else:
            boxes.append(head + max(chart, _line("end", css)))
    return sum(boxes) + gap * (len(boxes) - 1)


def _statusHeight(view: dict[str, Any], css: str | None = None) -> float:
    status = _rule("#engine-detail .eng-status", css)
    rule = _px(_decl(status, "border-top-width") or "", css)
    pad = _px(_decl(status, "padding-top") or "", css)
    run = view["runTime"]
    runTile = _line("label", css) + _line("value", css) + (_line("note", css) if run["note"] else 0)
    mil = view["mil"]
    milTile = (
        _line("label", css) + _line("value", css)
        + (_line("codes", css) if view["codes"] else 0)
        + (_line("note", css) if mil["note"] else 0)
    )
    return rule + pad + max(runTile, milTile)


def _detailHeight(historyName: str, milName: str, css: str | None = None) -> float:
    history = _probe("engineHistoryView", _fixture(historyName)["engine-history"])
    fx = _fixture(milName)
    status = _probe("engineStatusView", fx["obd-live"], True, _ms(fx["now"]))
    # The history and the status stack with no gap between them: the
    # status's own rule + padding-top separate them.
    return _historyHeight(history, css) + _statusHeight(status, css)


_FIT_CASES = [
    ("fan-cycle-history", "mil-on-twelve-codes"),
    ("history-empty-after-restart", "mil-on-twelve-codes"),
]


@_NODE_ONLY
@pytest.mark.parametrize(("history", "mil"), _FIT_CASES)
def test_fit_engineHistory_fitsThe270Body(history: str, mil: str):
    """Spec s3b: 3 x (head + chart) + the status row inside the 270 px body,
    the margin the spec calls thin (267 of 270 by its arithmetic)."""
    body = _bodyHeight()
    assert body == 270
    height = _detailHeight(history, mil)
    assert height <= body, (history, mil, height, body)


@_NODE_ONLY
def test_fit_theFullCase_chargesEveryTerm():
    """fan-cycle-history + twelve codes, term by term from the declared rules:
    3 heads (18) + 3 charts (40) + 2 gaps (8) + rule 1 + pad 8 + label 18 +
    ON 24 + '12 codes ›' 24 = 265 -- the real line boxes, not font sizes."""
    assert _detailHeight("fan-cycle-history", "mil-on-twelve-codes") == pytest.approx(265)


@_NODE_ONLY
def test_fit_aPlantedOverflow_fails():
    """Q1 negative control: the old 46 px chart no longer fits the body."""
    css = _read(_CSS).replace("--eng-graph-h: 40px;", "--eng-graph-h: 46px;")
    assert css != _read(_CSS)
    assert _detailHeight("fan-cycle-history", "mil-on-twelve-codes", css) > _bodyHeight()


def test_width_theTitle_andTheWidestHead_fitTheDetail():
    title = michromaWidthPx(TITLE, _px("var(--fs-label)"))
    assert title <= _detailWidth() - _px("var(--tap-min)")
    gap = _px(_decl(_rule("#engine-detail .eng-hist-head"), "gap") or "")
    widest = max(michromaWidthPx(label, 15) for label in SERIES_LABELS)
    window = len("· SINCE 12:59") * _px("var(--fs-meta)") * PI_MONO_ADVANCE_EM
    assert widest + gap + window <= _detailWidth()
    assert not (widest + gap + window * 3 <= _detailWidth()), "the planted wide head must fail"


def test_lines_model_wrapsTheAbsence():
    """The typed absence is wider than the detail, so it is charged two lines."""
    size = _px("var(--fs-meta)")
    assert len(ABSENCE) * size * PI_MONO_ADVANCE_EM > _detailWidth()
    assert _lines(ABSENCE, size, _detailWidth()) == 2
    assert _lines(ABSENCE * 2, size, _detailWidth()) > 2
