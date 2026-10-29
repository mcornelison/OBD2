################################################################################
# File Name: test_motion_imu_detail.py
# Purpose/Description: US-892-d (F-127; specs/v030-motion-page-design.md s3a,
#   CIO 2026-10-27) -- the Motion page with no scroll: the health block is ONE
#   row COMPASS | GYRO, each g cell has ONE sub-line, and UPDATED, TILT FIX and
#   the full reasons + peaks move to the IMU detail on US-894-g's shared
#   page-detail host.
#
#   What is pinned here:
#     - the exit test: health labels COMPASS, GYRO; no motion-updated in the
#       markup; a parked tap on the health row opens the IMU detail with
#       UPDATED and TILT FIX; not parked, a tap opens nothing and no ' ›'
#       shows; the reason replaces the peak; band pad / gap resolve to 4 px;
#     - the detail rows (six, full reasons) on gyro-unjudged and
#       compass-uncalibrated, R1 (leaving parked closes it), and that it
#       declares no host geometry;
#     - every glance reason is one line with an ellipsis (Motion AC 17), read
#       off the cascade on gyro-unjudged; the detail's reason WRAPS, clamped
#       to 2 lines (UIDEV-022);
#     - Q1 (Atlas S119 gate): MODELLED height budgets from the DECLARED
#       CSS/tokens -- the glance <= the 254 px card body, the detail <= the
#       host's 270 px body -- each with a planted-overflow negative control
#       that FAILS; widths from michroma-advances.json and the Pi's mono
#       advance, each line's widest case against its column.
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
# 2026-10-27    | Ralph (Rex)  | Initial -- US-892-d health row + IMU detail.
# 2026-10-28    | Rex (US-892-e) | Width docstring: the GYRO column is capped.
# ================================================================================
################################################################################

"""US-892-d tests: Motion's COMPASS | GYRO health row and the IMU detail."""

from __future__ import annotations

import math
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
)
from tests.ui.test_engine_page import _bodyHeightPx, _bodyWidthPx  # noqa: E402
from tests.ui.test_motion_page import STALE, _call, _fixture, _now  # noqa: E402
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
_CSS = os.path.join(_DASH, "dashboard.css")
_HTML = os.path.join(_DASH, "dashboard.html")
_TOKENS = os.path.join(_DASH, "..", "tokens.css")

TITLE = "IMU"
CHEVRON = "›"
MOTION_DOT = 5  # Driving, Navigation, Engine, Fuel, O2, Motion (E-2 order)
DETAIL_ROWS = ["UPDATED", "COMPASS", "TILT FIX", "GYRO", "ACCEL", "CORNER"]
STATE_TOKENS = ("--amber-warn", "--green-ok", "--critical-red")
HOLD_MS = 9000  # past the 8 s parked hold (US-511-b)

_HOLD_PARKED = [{"flush": 4}, {"advanceMs": HOLD_MS, "flush": 4}]
_TO_MOTION = [{"clickNth": {"selector": ".dot", "index": MOTION_DOT}}, {"flush": 2}]
_OPEN = [{"click": "motion-health"}, {"flush": 2}]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _routes(name: str) -> dict[str, Any]:
    fx = _fixture(name)
    return {"/imu": fx["imu"], "/grade-history": fx["gradeHistory"],
            "/system-status": _driving()}


def _render(name: str, *, parked: bool, steps: list[dict[str, Any]] | None = None) -> rh.Surface:
    routes = _routes(name)
    routes["/gear"] = _gearParked() if parked else _gearMoving()
    # Start HOLD_MS early so the fixture reads fresh once the hold has run.
    nowMs = _now(name) - HOLD_MS
    tree = rh.runDashboard(routes=routes, steps=_HOLD_PARKED + _TO_MOTION + (steps or []),
                           viewport=PANEL, nowMs=nowMs, displayStale=STALE)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _text(node: dict[str, Any]) -> str:
    return "".join(c["text"] if "text" in c else _text(c) for c in node.get("children", []))


def _shown(node: dict[str, Any]) -> str:
    """The texts a reader sees: hidden subtrees dropped, leaves space-joined."""
    if "hidden" in node.get("attrs", {}):
        return ""
    out = []
    for child in node.get("children", []):
        piece = child["text"].strip() if "text" in child else _shown(child)
        if piece:
            out.append(piece)
    return " ".join(out)


def _classes(node: dict[str, Any]) -> list[str]:
    return (node.get("attrs", {}).get("class") or "").split()


def _inside(surface: rh.Surface, ancestorId: str, cls: str) -> list[list[dict[str, Any]]]:
    return [p for p in surface.pathsByClass(cls)
            if any(n.get("attrs", {}).get("id") == ancestorId for n in p)]


def _detailOpen(surface: rh.Surface) -> bool:
    path = surface.pathById("page-detail")
    assert path is not None
    return path[-1]["attrs"].get("hidden") is None


def _pageName(surface: rh.Surface) -> str:
    return _text(surface.pathById("page-name")[-1]).strip()


def _detailRows(surface: rh.Surface) -> dict[str, str]:
    """{label: the row's shown value + reason} in #motion-detail."""
    rows = {}
    for path in _inside(surface, "motion-detail", "motion-drow"):
        (label,) = [c for c in path[-1]["children"] if "motion-dlabel" in _classes(c)]
        (value,) = [c for c in path[-1]["children"] if "motion-dval" in _classes(c)]
        rows[_text(label).strip()] = _shown(value)
    return rows


def _healthMarkup() -> str:
    html = _read(_HTML)
    start = html.index('id="motion-card"')
    card = html[start:html.index("</section>", start)]
    return card[card.index('class="motion-health"'):]


def _rules(css: str | None = None) -> list[tuple[str, str]]:
    return [(r.selector.strip(), r.declarations) for r in rh.parseCss(css or _read(_CSS))]


def _rule(selector: str, css: str | None = None) -> str:
    """Every block whose selector list names ``selector`` (grouped or alone)."""
    bodies = [body for sel, body in _rules(css)
              if selector in [s.strip() for s in sel.split(",")]]
    assert bodies, f"no rule {selector!r}"
    return " ".join(bodies)


def _decl(selector: str, prop: str, css: str | None = None) -> str:
    found = rh.declarationOf(_rule(selector, css), prop)
    assert found is not None, (selector, prop)
    return found[0]


def _scoped(root: str, css: str | None = None) -> dict[str, str]:
    return {n: v.strip() for n, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", _rule(root, css))}


def _resolve(value: str, root: str, css: str | None = None) -> str:
    """A var() chased through the root's scoped properties, then :root's."""
    value = value.strip()
    var = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if not var:
        return value
    name = var.group(1)
    scoped = _scoped(root, css)
    if name in scoped:
        return _resolve(scoped[name], root, css)
    for source in (css or _read(_CSS), _read(_TOKENS)):
        found = re.search(rf"^\s*{re.escape(name)}:\s*([^;]+);", source, re.M)
        if found:
            return found.group(1).strip()
    raise AssertionError(f"{name} does not resolve")


def _px(value: str, root: str, css: str | None = None) -> float:
    resolved = _resolve(value, root, css)
    m = re.fullmatch(r"([0-9.]+)px", resolved)
    assert m is not None, f"{value!r} -> {resolved!r} is not a px length"
    return float(m.group(1))


def _number(value: str, root: str, css: str | None = None) -> float:
    return float(_resolve(value, root, css))


def _lineOf(selector: str, root: str, css: str | None = None) -> float:
    """One line box of `selector`: its declared font-size x line-height
    (a number, never `normal`)."""
    lh = _decl(selector, "line-height", css)
    assert lh != "normal", selector
    return _px(_decl(selector, "font-size", css), root, css) * _number(lh, root, css)


def _mono(text: str, sizePx: float) -> float:
    return len(text) * sizePx * PI_MONO_ADVANCE_EM


# ---------------------------------------------------------------------------
# The exit test.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_motion_health_row_is_compass_gyro_only():
    """Spec s3a / AC 16: the health row is COMPASS | GYRO; UPDATED and TILT
    FIX leave the page for the IMU detail, which opens on a PARKED tap only."""
    # The markup: one row, two cells, no UPDATED.
    m = _healthMarkup()
    labels = re.findall(r'<span class="motion-label">([^<]+)</span>', m)
    assert labels == ["COMPASS", "GYRO"]
    assert "motion-updated" not in _read(_HTML)
    assert "motion-tilt" not in _read(_HTML)

    # Parked: the tap opens the IMU detail, with UPDATED and TILT FIX.
    opened = _render("health-trusted", parked=True, steps=_OPEN)
    assert _detailOpen(opened)
    assert _text(opened.pathById("page-detail-title")[-1]) == TITLE
    body = opened.pathById("page-detail-body")
    detail = opened.pathById("motion-detail")
    assert detail is not None and detail[: len(body)] == body, "the detail is not in the host's body"
    rows = _detailRows(opened)
    assert list(rows) == DETAIL_ROWS
    assert rows["UPDATED"] == "0 s ago"
    assert rows["TILT FIX"] == "−0.45° from 14 stops"

    # Not parked: a tap opens nothing, and no ' ›' shows on the row.
    unparked = _render("health-trusted", parked=False, steps=_OPEN)
    assert not _detailOpen(unparked)
    health = unparked.pathById("motion-health")
    assert CHEVRON not in _shown(health[-1])
    assert _shown(health[-1]) == "COMPASS calibrated GYRO plausible"

    # Parked, closed: the ' ›' sits on the row's last value.
    parked = _render("health-trusted", parked=True)
    assert _shown(parked.pathById("motion-health")[-1]) == "COMPASS calibrated GYRO plausible ›"

    # The reason replaces the peak (one sub-line per g cell).
    unjudged = _render("gyro-unjudged", parked=False)
    (lon,) = _inside(unjudged, "motion-card", "motion-lon")
    assert _shown(lon[-1]) == "ACCEL BRAKE -- sensor not detected"
    (lat,) = _inside(unjudged, "motion-card", "motion-lat")
    assert _shown(lat[-1]) == "CORNER -- sensor not detected"
    live = _render("climb-accel", parked=False)
    (lon,) = _inside(live, "motion-card", "motion-lon")
    assert _shown(lon[-1]) == "ACCEL 0.31 g peak ▲0.31 ▼0.38"

    # Band padding and gap resolve to 4 px.
    for name in ("--motion-band-pad", "--motion-band-gap"):
        assert _px(f"var({name})", "#motion-card") == 4, name


# ---------------------------------------------------------------------------
# The detail: rows, R1, no host geometry, no state colour on the cue.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_detail_gyroUnjudged_fullReasonsAndThePeaks():
    rows = _detailRows(_render("gyro-unjudged", parked=True, steps=_OPEN))
    assert rows == {
        "UPDATED": "0 s ago",
        "COMPASS": "calibrated",
        "TILT FIX": "-- no stops yet",
        "GYRO": "-- sensor not detected",
        "ACCEL": "peak ▲0.31 ▼0.38",
        "CORNER": "peak L0.27 R0.31",
    }


@_NODE_ONLY
def test_detail_compassUncalibrated_toneAndOneStop():
    surface = _render("compass-uncalibrated", parked=True, steps=_OPEN)
    rows = _detailRows(surface)
    assert rows["COMPASS"] == "not calibrated"
    assert rows["TILT FIX"] == "+0.45° from 1 stop"
    tones = {p[-1]["attrs"].get("data-row"): p[-1]["attrs"].get("data-tone")
             for p in _inside(surface, "motion-detail", "motion-drow")}
    assert tones == {"updated": "plain", "compass": "warn", "tilt": "plain",
                     "gyro": "ok", "accel": "plain", "corner": "plain"}


@_NODE_ONLY
def test_R1_gearD_closesTheDetail_andTheMotionPageShows():
    leaving = _OPEN + [{"setRoutes": {"/gear": _gearMoving()}}, {"flush": 2}]
    held = _render("climb-accel", parked=True, steps=leaving + [{"advanceMs": 1000, "flush": 4}])
    assert _detailOpen(held), "still parked 1 s in (the debounce): the detail stays"
    closed = _render("climb-accel", parked=True, steps=leaving + [{"advanceMs": 3500, "flush": 4}])
    assert not _detailOpen(closed)
    assert _pageName(closed) == "MOTION"
    assert CHEVRON not in _shown(closed.pathById("motion-health")[-1])


@_NODE_ONLY
def test_back_closesTheDetail_ontoTheMotionPage():
    surface = _render("climb-accel", parked=True,
                      steps=_OPEN + [{"click": "page-detail-back"}, {"flush": 1}])
    assert not _detailOpen(surface)
    assert _pageName(surface) == "MOTION"


@_NODE_ONLY
def test_theChevron_carriesNoStateColour():
    surface = _render("health-trusted", parked=True)
    (chev,) = _inside(surface, "motion-card", "motion-hchev")
    assert surface.winningDeclaration(chev, "color")[0] == "var(--text-primary)"
    for rule in rh.parseCss(_read(_CSS)):
        if rule.selector and rh.isResolvable(rule.selector) and rh.matchesSelector(rule.selector, chev):
            for token in STATE_TOKENS:
                assert token not in rule.declarations, (rule.selector, token)


def test_theDetailShipsInTheHostsBody_inRowOrder():
    html = _read(_HTML)
    body = html.index('<div id="page-detail-body"')
    assert body < html.index('<div id="motion-detail"') < html.index('<div id="clear-confirm"')
    detail = html[html.index('<div id="motion-detail"'):]
    detail = detail[:detail.index("<!--")] if "<!--" in detail else detail
    labels = re.findall(r'<span class="motion-dlabel">([^<]+)</span>', detail)
    assert labels[: len(DETAIL_ROWS)] == DETAIL_ROWS


def test_theDetailDeclaresNoHostGeometry():
    """Consumes US-894-g's host: no Motion rule touches #page-detail or a
    --pd-* property, and the host's body is still 270."""
    for selector, body in _rules():
        if "motion" in selector:
            assert "page-detail" not in selector, selector
            assert "--pd-" not in body, selector
    assert _bodyHeight() == 270


# ---------------------------------------------------------------------------
# One line with an ellipsis on the glance (AC 17); 2-line clamp in the detail.
# ---------------------------------------------------------------------------


@_NODE_ONLY
@pytest.mark.parametrize("cls", ["motion-note", "motion-hsub"])
def test_ellipsis_gyroUnjudged_theGlanceReasonIsOneLine(cls: str):
    """text-overflow alone renders nothing on an inline span: the reason is
    a block, min-width 0, nowrap, overflow hidden, ellipsis -- on the
    cascade of the element the gyro-unjudged page actually shows."""
    surface = _render("gyro-unjudged", parked=False)
    paths = [p for p in _inside(surface, "motion-card", cls) if "hidden" not in p[-1]["attrs"]]
    assert paths, cls
    for path in paths:
        assert _text(path[-1]).strip(), "a shown reason has words"
        assert surface.winningDeclaration(path, "display")[0] == "block"
        assert surface.winningDeclaration(path, "min-width")[0] == "0"
        assert surface.winningDeclaration(path, "white-space")[0] == "nowrap"
        assert surface.winningDeclaration(path, "overflow")[0] == "hidden"
        assert surface.winningDeclaration(path, "text-overflow")[0] == "ellipsis"


def test_detail_theReasonWraps_clampedToTwoLines():
    """UIDEV-022: in the detail a reason WRAPS inside the value column, and
    -webkit-line-clamp: 2 + ellipsis is the only cut (the glance rule, one
    line, is unchanged)."""
    val = "#motion-detail .motion-dval"
    assert _decl(val, "display") == "-webkit-box"
    assert _decl(val, "-webkit-box-orient") == "vertical"
    assert _decl(val, "-webkit-line-clamp") == "2"
    assert _decl(val, "overflow") == "hidden"
    assert _decl(val, "text-overflow") == "ellipsis"
    assert _decl(val, "white-space") == "normal"


def test_detail_labelIsMichromaMeta_spaced_neverFsLabel():
    """Iris, motion spec s3a: Michroma --fs-meta, line-height 1.2, 0.06em."""
    root = "#motion-detail"
    label = f"{root} .motion-dlabel"
    assert _decl(label, "font-family") == "var(--font-display)"
    assert _decl(label, "font-size") == "var(--fs-meta)"
    assert _number(_decl(label, "line-height"), root) == 1.2
    assert _resolve(_decl(label, "letter-spacing"), root) == "0.06em"


# ---------------------------------------------------------------------------
# Q1 -- the glance: <= the 254 px card body (modelled, declared values).
# ---------------------------------------------------------------------------


def _glanceHeight(css: str | None = None) -> float:
    """Every term the card body spends, from the declared rules: the two
    bands and the health row, each with its padding, the rules between them
    and the card-body gaps. A g cell charges its TALLER one sub-line (the
    peak at --fs-label vs the reason at --fs-meta)."""
    root = "#motion-card"
    pad = _px(_decl(f"{root} .motion-band", "padding-block", css), root, css)
    gap = _px(_decl(f"{root} .card-body", "gap", css), root, css)
    cellGap = _px(_decl(f"{root} .motion-cell", "gap", css), root, css)
    rule = _px(_decl(f"{root} .motion-band + .motion-band", "border-top", css).split()[0], root, css)
    label = _lineOf(f"{root} .motion-label", root, css)
    value = _px(_decl(f"{root} .motion-value", "font-size", css), root, css) * _number(
        _decl(f"{root} .motion-value", "line-height", css), root, css)
    sub = _lineOf(f"{root} .motion-note", root, css)
    peak = _lineOf(f"{root} .motion-peak", root, css)
    graph = _px(_decl(f"{root} .motion-graph", "height", css), root, css)

    pitch = label + cellGap + value + cellGap + sub
    grade = label + cellGap + graph
    top = 2 * pad + max(pitch, grade)
    g = rule + 2 * pad + label + cellGap + value + cellGap + max(peak, sub)

    hpad = _px(_decl(f"{root} .motion-health", "padding-block", css), root, css)
    hrule = _px(_decl(f"{root} .motion-health", "border-top", css).split()[0], root, css)
    hgap = _px(_decl(f"{root} .motion-hcell", "gap", css), root, css)
    hv = _lineOf(f"{root} .motion-hv", root, css)
    hsub = _lineOf(f"{root} .motion-hsub", root, css)
    chev = _lineOf(f"{root} .motion-hchev", root, css)
    health = hrule + 2 * hpad + label + hgap + max(hv, hsub, chev)
    # Three shown children (top band, g band, health); .motion-loading is hidden.
    return top + gap + g + gap + health


def test_glance_fitsThe254Body():
    body = _bodyHeightPx()
    assert body == 254
    assert _glanceHeight() <= body, (_glanceHeight(), body)


def test_glance_theFullCase_chargesEveryTerm():
    """top 4+4 + max(pitch 18+4+34+4+18, grade 18+4+58 = 80) = 88; gap 4;
    G rule 1 + 4+4 + 18+4+34+4 + peak 24 = 93; gap 4; health rule 1 + 4+4 +
    18+4 + 22 = 53 -> 242 of 254 (the spec's 246 charged the pitch sub at
    --fs-label; the shipped rule is --fs-meta)."""
    assert _glanceHeight() == pytest.approx(242)


def test_glance_aPlantedOverflow_fails():
    css = _read(_CSS).replace("--motion-band-pad: 4px;", "--motion-band-pad: 12px;")
    assert css != _read(_CSS)
    assert _glanceHeight(css) > _bodyHeightPx()


@_NODE_ONLY
@pytest.mark.parametrize("name", ["climb-accel", "gyro-unjudged", "compass-uncalibrated"])
def test_glance_fitCases_oneSubLinePerGCell_oneHealthRow(name: str):
    """The fit cases the model charges: each g cell shows exactly ONE
    sub-line, the health row is two cells, and no reason can wrap."""
    surface = _render(name, parked=False)
    for cls in ("motion-lon", "motion-lat"):
        (cell,) = _inside(surface, "motion-card", cls)
        subs = [c for c in cell[-1]["children"]
                if {"motion-note", "motion-peak"} & set(_classes(c))
                and "hidden" not in c.get("attrs", {})]
        assert len(subs) == 1, (name, cls)
    cells = [p for p in _inside(surface, "motion-card", "motion-hcell")]
    assert len(cells) == 2
    assert _glanceHeight() <= _bodyHeightPx()


def test_glance_widths_eachWidestLineFitsItsColumn():
    """Mono at the Pi's advance, Michroma from michroma-advances.json. The
    g columns split the body; the health row is 1fr | fit-content(the GYRO
    cap, US-892-e; the cap's model is in tests/ui/test_motion_page.py s6)."""
    root = "#motion-card"
    width = _bodyWidthPx()
    label = _px("var(--fs-label)", root)
    meta = _px("var(--fs-meta)", root)
    primary = _px("var(--fs-primary)", root)
    colGap = _px("var(--motion-col-gap)", root)
    gCol = (width - colGap) / 2
    assert _mono("peak ▲0.31 ▼0.38", label) <= gCol
    assert _mono("0.31", primary) + _mono(" g", label) <= gCol
    assert michromaWidthPx("ACCEL BRAKE", meta) <= gCol
    pitchCol = _px("var(--motion-pitch-w)", root)
    assert _mono("+90.0°", primary) <= pitchCol
    hGap = _px("var(--motion-health-col-gap)", root)
    gyro = _mono("implausible" + " ›", label)
    compass = _mono("not calibrated", label)
    assert compass + hGap + gyro <= width
    # A reason cannot wrap: nowrap is the rule (the ellipsis test reads it).
    assert _decl(f"{root} .motion-hsub", "white-space") == "nowrap"


# ---------------------------------------------------------------------------
# Q1 -- the IMU detail: <= the host's 270 px body.
# ---------------------------------------------------------------------------


def _detailWidths(css: str | None = None) -> tuple[float, float]:
    """(label column, value column) from the declared grid and the host's
    body width (its declared side padding)."""
    root = "#motion-detail"
    labelCol = _px(_decl(f"{root} .motion-drow", "grid-template-columns", css).split()[0], root, css)
    body = PANEL[0] - 2 * _geometry()["bodyPadX"]
    return labelCol, body - labelCol


def _rowHeight(value: str, reason: str | None, css: str | None = None) -> float:
    """max(--row-min, label line, value line + (reason lines - 1) x reason
    line), the reason inline after the value at its gap, wrapped at the value
    column at the mono advance and clamped to the declared line count."""
    root = "#motion-detail"
    rowMin = _px(_decl(f"{root} .motion-drow", "min-height", css), root, css)
    label = _lineOf(f"{root} .motion-dlabel", root, css)
    valueLine = _lineOf(f"{root} .motion-dv", root, css)
    reasonLine = _lineOf(f"{root} .motion-dr", root, css)
    lines = 1
    if reason:
        _, col = _detailWidths(css)
        valuePx = _px(_decl(f"{root} .motion-dv", "font-size", css), root, css)
        reasonPx = _px(_decl(f"{root} .motion-dr", "font-size", css), root, css)
        gap = _px(_decl(f"{root} .motion-dr", "margin-left", css), root, css)
        flow = _mono(value, valuePx) + gap + _mono(reason, reasonPx)
        lines = min(math.ceil(flow / col), int(_decl(f"{root} .motion-dval", "-webkit-line-clamp", css)))
    return max(rowMin, label, valueLine + (lines - 1) * reasonLine)


def _detailCells(name: str) -> list[tuple[str, str | None]]:
    """The six rows' (value, reason) as the view paints them for a fixture."""
    view = _call("motionView", _fixture(name)["imu"], _now(name), STALE["imuSec"], None)
    h = view["health"]
    return [(h[k]["value"], h[k]["sub"]) for k in ("updated", "compass", "tilt", "gyro")] + [
        (view["lon"]["peak"], None), (view["lat"]["peak"], None)]


def _detailHeight(cells: list[tuple[str, str | None]], css: str | None = None) -> float:
    """The rows plus the host body's declared row gap between them."""
    declared = _decl(".page-detail-body", "gap", css)
    gap = 0.0 if declared == "0" else _px(declared, "#page-detail", css)
    return sum(_rowHeight(v, r, css) for v, r in cells) + gap * (len(cells) - 1)


@_NODE_ONLY
@pytest.mark.parametrize("name", ["gyro-unjudged", "compass-uncalibrated"])
def test_imuDetail_heightBudget(name: str):
    """Spec s3a (UIDEV-022): 6 x --row-min 44 = 264 of 270, full reasons."""
    cells = _detailCells(name)
    assert len(cells) == 6
    assert _bodyHeight() == 270
    assert _detailHeight(cells) == pytest.approx(264)
    assert _detailHeight(cells) <= _bodyHeight()


def test_imuDetail_aPlanted3LineReason_clampsTo2_andStillFits():
    _, col = _detailWidths()
    reason = "x" * math.ceil(2.5 * col / (15 * PI_MONO_ADVANCE_EM))
    # Unclamped it would be 3 lines; the clamp holds the row to 2.
    flow = _mono("--", 20) + 6 + _mono(reason, 15)
    assert math.ceil(flow / col) >= 3
    row = _rowHeight("--", reason)
    assert row == pytest.approx(44)  # 23.08 + 17.31 = 40.4 <= --row-min
    cells = [("--", reason)] + [("0 s ago", None)] * 5
    assert _detailHeight(cells) <= _bodyHeight()


def test_imuDetail_negativeControl_rowMin48_fails():
    css = re.sub(r"(--row-min:\s*)44px", r"\g<1>48px", _read(_CSS))
    assert css != _read(_CSS)
    cells = [("calibrated", None)] * 6
    assert _detailHeight(cells, css) == pytest.approx(288)
    assert not (_detailHeight(cells, css) <= _bodyHeight())


def test_imuDetail_widths_labelColumnHoldsCompass_valueColumnIs320Plus():
    """COMPASS at Michroma --fs-meta, 0.06em = 120.2 px (spec s3a) inside the
    128 px label column with its 8 px gap; the value column >= 320 px, and
    the longest known one-line row, '--' + 'orientation unresolved', fits it."""
    root = "#motion-detail"
    labelCol, valueCol = _detailWidths()
    meta = _px("var(--fs-meta)", root)
    track = float(_resolve(_decl(f"{root} .motion-dlabel", "letter-spacing"), root).rstrip("em"))
    widest = max(michromaWidthPx(t, meta, track) for t in DETAIL_ROWS)
    assert widest == pytest.approx(michromaWidthPx("COMPASS", meta, track))
    assert widest + 8 <= labelCol
    assert valueCol >= 320
    assert _mono("--", 20) + 6 + _mono("orientation unresolved", meta) <= valueCol
