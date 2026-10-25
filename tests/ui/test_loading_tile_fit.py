################################################################################
# File Name: test_loading_tile_fit.py
# Purpose/Description: US-760 (F-132) guard: the word LOADING always shows
#   WHOLE, on its OWN line, on every card that paints the US-700 loadingTile.
#   CIO 2026-10-23 "fix so the word LOADING fully shows"; Iris measured V0.30
#   already fits, so this file PINS it so a later style change cannot clip it.
#   The fit method is OWN LINE -- never scale, never wrap (Iris C-Iris-7).
#     1. coverage: every loadingTile( / renderLoadingBody( call site in
#        carousel.js is found by scanning the source, and a site this file
#        does not render is a red, not a silent gap;
#     2. per caller, the SHIPPED DOM painted in its loading state (no route
#        answered yet) and resolved against the SHIPPED stylesheet:
#        (a) the value text is exactly LOADING; (b) label and value are
#        separate children of the flex-column .tile; (c) LOADING's width in
#        the measured Pi mono model fits the card body's content width, both
#        computed from the sheet; (d) no nowrap+clip and no shrunken font.
#   NOT GUARDED: layout on the glass -- the harness resolves the cascade, not
#   boxes; the width is the repo's measured mono model, never a Windows font.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-24    | Rex (US-760) | Initial -- LOADING whole and on its own line.
# ================================================================================
################################################################################

"""US-760: LOADING always shows whole, on its own line, on every loading tile."""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections import Counter
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

# The measured-not-guessed width model, IMPORTED so it cannot drift from the
# top bar's (Iris 2026-10-24 call 3: never a copy, never a Windows advance).
from tests.ui.test_topbar_three_column_grid import (  # noqa: E402
    PI_MONO_ADVANCE_EM,
    _textWidthPx,
)

_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
_CSS = os.path.join(rh.DASHBOARD_DIR, "dashboard.css")
_NODE = shutil.which("node")

_NODE_ONLY = pytest.mark.skipif(
    _NODE is None, reason="node not on PATH -- these tests run the shipped browser JS"
)

LOADING = "LOADING"
STALE = {"imuSec": 3.0, "fuelResetConfirmSec": 6}
NOW_MS = 1_800_000_000_000

# Every call site of the two loading painters, keyed by (callee, its argument
# text with whitespace collapsed) -> the CASE below that renders it. The
# renderLoadingBody body's own `loadingTile(label)` is the shared painter, so
# it is covered by every renderLoadingBody case. A new call site -- even one
# with the same arguments as an old one -- changes this multiset and goes red.
COVERED_CALL_SITES: dict[tuple[str, str], str] = {
    ("loadingTile", '"MOTION"'): "motion",
    ("loadingTile", "label"): "renderLoadingBody",
    ("renderLoadingBody", "body, view.label"): "source",
    ("renderLoadingBody", 'body, card.getAttribute("data-page-name") || ""'): "alerts",
    (
        "renderLoadingBody",
        'body, nd ? nd.label : (card.getAttribute("data-page-name") || "")',
    ): "availability",
}

# Where each case's loading tile lands in the shipped markup. The generic
# data-state availability path is the System card's (Light and Fuel route
# through renderSourceCard first, US-540-b).
CASES: dict[str, tuple[str, str]] = {
    "motion": ("id", "motion-card"),
    "source": ("id", "light-card"),
    "alerts": ("id", "alerts-card"),
    "availability": ("data-state", "system-status"),
}

_CALL = re.compile(r"(?<![\w.])(loadingTile|renderLoadingBody)\s*\(")


# ---------------------------------------------------------------------------
# 1. Coverage: the callers are found, not listed from memory
# ---------------------------------------------------------------------------


def _stripJsComments(js: str) -> str:
    """Comments out, line structure kept: prose naming a painter is no call."""
    js = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), js, flags=re.DOTALL)
    out = []
    for line in js.split("\n"):
        if line.lstrip().startswith("//"):
            out.append("")
            continue
        # A trailing comment; `://` inside a URL string has no leading space.
        cut = line.find(" //")
        out.append(line if cut == -1 else line[:cut])
    return "\n".join(out)


def _argsAt(js: str, openParen: int) -> str:
    depth, i = 0, openParen
    while True:
        ch = js[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return " ".join(js[openParen + 1 : i].split())
        i += 1


def callSites(js: str) -> Counter[tuple[str, str]]:
    """Every call of the two loading painters in a carousel.js source.

    Args:
        js: the carousel.js source.

    Returns:
        (callee, collapsed argument text) -> how many times it is called.
    """
    code = _stripJsComments(js)
    sites: Counter[tuple[str, str]] = Counter()
    for match in _CALL.finditer(code):
        if code[: match.start()].rstrip().endswith("function"):
            continue  # the declaration, not a call
        sites[(match.group(1), _argsAt(code, match.end() - 1))] += 1
    return sites


def uncoveredCallSites(js: str) -> list[str]:
    """The call sites this file does not render, plus covered sites gone missing."""
    found = callSites(js)
    problems = [
        f"{callee}({args}) x{n} -- not rendered by test_loading_tile_fit.py"
        for (callee, args), n in sorted(found.items())
        if (callee, args) not in COVERED_CALL_SITES or n != 1
    ]
    problems += [
        f"{callee}({args}) -- covered here but no longer called in carousel.js"
        for (callee, args) in COVERED_CALL_SITES
        if (callee, args) not in found
    ]
    return problems


def test_coverage_everyLoadingPainterCallSiteIsRenderedHere():
    assert uncoveredCallSites(_readFile(_JS)) == []


def test_coverage_aNewLoadingTileCaller_isRed():
    """VC row 3: a scratch carousel.js with a caller this file does not know."""
    js = _readFile(_JS)
    anchor = "function renderLoadingBody(body, label) {"
    assert anchor in js
    scratch = js.replace(anchor, 'function newLoadingCard(b) { appendTile(b, loadingTile("NEW")); }\n    ' + anchor)
    assert any('loadingTile("NEW")' in p for p in uncoveredCallSites(scratch))


def test_coverage_aSecondCallWithTheSameArguments_isRed():
    js = _readFile(_JS)
    anchor = "function renderLoadingBody(body, label) {"
    scratch = js.replace(anchor, 'function again() { loadingTile("MOTION"); }\n    ' + anchor)
    assert any('loadingTile("MOTION") x2' in p for p in uncoveredCallSites(scratch))


def test_coverage_everyRenderLoadingBodyCaseIsRendered():
    """The shared painter's own call is covered only through real cases."""
    body = {case for (callee, _), case in COVERED_CALL_SITES.items() if callee == "renderLoadingBody"}
    assert body and body <= set(CASES)
    assert {c for c in COVERED_CALL_SITES.values() if c != "renderLoadingBody"} == set(CASES)


# ---------------------------------------------------------------------------
# 2. Every caller, painted in its loading state
# ---------------------------------------------------------------------------


def _readFile(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _classes(node: dict[str, Any]) -> list[str]:
    return (node.get("attrs", {}).get("class") or "").split()


def _text(node: dict[str, Any]) -> str:
    return "".join(c["text"] if "text" in c else _text(c) for c in node.get("children", []))


def _surface(cssPath: str = _CSS) -> rh.Surface:
    """The loading-state DOM (no route answered, inside the bound) + the sheet."""
    dom = rh.runDashboard(routes={}, steps=[{"flush": 4}], nowMs=NOW_MS, displayStale=STALE)
    roots = dom["tree"] if isinstance(dom["tree"], list) else [dom["tree"]]
    root = {"tag": "html", "attrs": {}, "children": [{"tag": "body", "attrs": {}, "children": roots}]}
    return rh.dashboardSurface(root, cssPath=cssPath, viewport=(480, 320))


@pytest.fixture(scope="module")
def surface() -> rh.Surface:
    return _surface()


def _loadingTilePath(s: rh.Surface, case: str) -> list[dict[str, Any]]:
    attr, value = CASES[case]
    hits = [
        p for p in s.pathsByClass("tile")
        if p[-1].get("attrs", {}).get("data-level") == "loading"
        and any(q.get("attrs", {}).get(attr) == value for q in p)
    ]
    assert len(hits) == 1, f"{case}: expected one loading tile, found {len(hits)}"
    assert s.rendered(hits[0]), f"{case}: the loading tile is not rendered"
    return hits[0]


def _child(path: list[dict[str, Any]], cls: str) -> list[dict[str, Any]]:
    hits = [c for c in path[-1].get("children", []) if cls in _classes(c)]
    assert len(hits) == 1, (cls, len(hits))
    return path + [hits[0]]


# --- the stylesheet's numbers, resolved, never typed in ----------------------


def _rootTokens(s: rh.Surface) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for rule in s.rules:
        if rule.selector == ":root":
            for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", rule.declarations):
                tokens[name] = value.strip()
    return tokens


def _resolveVar(s: rh.Surface, path: list[dict[str, Any]], value: str) -> str:
    """Substitute var(--x) from the nearest declaring ancestor, else :root."""
    for _ in range(10):
        match = re.search(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)", value)
        if not match:
            return value
        name, fallback = match.group(1), match.group(2)
        found = None
        for depth in range(len(path), 0, -1):
            win = s.winningDeclaration(path[:depth], name)
            if win is not None:
                found = win[0]
                break
        if found is None:
            found = _rootTokens(s).get(name, fallback)
        assert found is not None, f"{name} is declared nowhere"
        value = value[: match.start()] + found.strip() + value[match.end() :]
    raise AssertionError(f"var() does not resolve: {value}")


def _px(s: rh.Surface, path: list[dict[str, Any]], value: str) -> float:
    """One length in px. Anything else is refused rather than guessed."""
    value = _resolveVar(s, path, value).strip()
    if value == "0":
        return 0.0
    match = re.fullmatch(r"(-?[0-9.]+)px", value)
    assert match, f"not a px length: {value!r}"
    return float(match.group(1))


def _computed(s: rh.Surface, path: list[dict[str, Any]], prop: str) -> str | None:
    win = s.winningDeclaration(path, prop)
    return None if win is None else _resolveVar(s, path, win[0])


_BORDER_STYLES = {"none", "hidden", "dotted", "dashed", "solid", "double",
                  "groove", "ridge", "inset", "outset"}


def _sideLengths(shorthand: str) -> tuple[str, str]:
    """(left, right) of a padding / border-width shorthand."""
    parts = shorthand.split()
    if len(parts) == 1:
        return parts[0], parts[0]
    if len(parts) in (2, 3):
        return parts[1], parts[1]
    return parts[3], parts[1]


def _borderWidth(token: str) -> str:
    widths = [t for t in token.split() if t not in _BORDER_STYLES and re.match(r"^[0-9.]|^var\(", t)]
    return widths[0] if widths else "0"


def _horizontalChrome(s: rh.Surface, path: list[dict[str, Any]]) -> float:
    """Declared left+right padding and border of one element, px.

    Shorthand and longhand are different properties to the harness, so where
    both are declared the WIDER is charged: that can only make the fit stricter.
    """
    def decl(prop: str) -> str | None:
        win = s.winningDeclaration(path, prop)
        return None if win is None else _resolveVar(s, path, win[0])

    total = 0.0
    for side in ("left", "right"):
        cands: list[float] = []
        padding = decl("padding")
        if padding:
            left, right = _sideLengths(padding)
            cands.append(_px(s, path, left if side == "left" else right))
        inline = decl("padding-inline")
        if inline:
            parts = inline.split()
            cands.append(_px(s, path, parts[0] if side == "left" or len(parts) == 1 else parts[1]))
        long = decl(f"padding-{side}")
        if long:
            cands.append(_px(s, path, long))
        total += max(cands, default=0.0)

        bands: list[float] = []
        for prop in ("border", "border-inline", f"border-{side}"):
            value = decl(prop)
            if value:
                bands.append(_px(s, path, _borderWidth(value)))
        width = decl("border-width")
        if width:
            left, right = _sideLengths(width)
            bands.append(_px(s, path, left if side == "left" else right))
        sideWidth = decl(f"border-{side}-width")
        if sideWidth:
            bands.append(_px(s, path, sideWidth))
        total += max(bands, default=0.0)
    return total


def _bodyContentWidth(s: rh.Surface, tilePath: list[dict[str, Any]]) -> float:
    """The 480 px stage less every declared horizontal padding and border
    between it and the tile -- the card and its body included."""
    ids = [n.get("attrs", {}).get("id") for n in tilePath]
    assert "stage" in ids, "the loading tile is not inside #stage"
    at = ids.index("stage")
    stagePath = tilePath[: at + 1]
    stageW = _computed(s, stagePath, "width")
    assert stageW is not None, "#stage declares no width"
    width = _px(s, stagePath, stageW)
    for depth in range(at + 2, len(tilePath) + 1):
        width -= _horizontalChrome(s, tilePath[:depth])
    return width


# --- (a)-(d), per case -------------------------------------------------------


@_NODE_ONLY
@pytest.mark.parametrize("case", sorted(CASES))
def test_a_theValueIsExactlyLoading(surface: rh.Surface, case: str):
    value = _child(_loadingTilePath(surface, case), "tile-value")[-1]
    assert _text(value) == LOADING


@_NODE_ONLY
@pytest.mark.parametrize("case", sorted(CASES))
def test_b_labelAndValueAreSeparateChildrenOfTheFlexColumnTile(surface: rh.Surface, case: str):
    path = _loadingTilePath(surface, case)
    assert _computed(surface, path, "display") == "flex"
    assert _computed(surface, path, "flex-direction") == "column"
    kids = [c for c in path[-1].get("children", []) if "tag" in c]
    order = [k for c in kids for k in _classes(c) if k in ("tile-label", "tile-value")]
    assert order == ["tile-label", "tile-value"], order
    label = _child(path, "tile-label")[-1]
    assert LOADING not in _text(label)


def _valueMetrics(s: rh.Surface, valuePath: list[dict[str, Any]]) -> tuple[float, float]:
    size = _computed(s, valuePath, "font-size")
    assert size is not None, ".tile-value declares no font-size"
    spacing = _computed(s, valuePath, "letter-spacing") or "0em"
    match = re.fullmatch(r"(-?[0-9.]+)em|0", spacing.strip())
    assert match, f"letter-spacing is not in em: {spacing!r}"
    return _px(s, valuePath, size), float(match.group(1) or 0)


@_NODE_ONLY
@pytest.mark.parametrize("case", sorted(CASES))
def test_c_loadingFitsTheCardBody_inTheMeasuredMonoModel(surface: rh.Surface, case: str):
    path = _loadingTilePath(surface, case)
    valuePath = _child(path, "tile-value")
    sizePx, spacingEm = _valueMetrics(surface, valuePath)
    assert sizePx == _px(surface, valuePath, "var(--fs-primary)")
    width = _textWidthPx(LOADING, sizePx, spacingEm)
    body = _bodyContentWidth(surface, path)
    assert width <= body, (
        f"{case}: LOADING is {width:.1f} px at {sizePx} px "
        f"(advance {PI_MONO_ADVANCE_EM} + {spacingEm} em) in a {body:.1f} px body"
    )


def _clipViolations(s: rh.Surface, path: list[dict[str, Any]]) -> list[str]:
    """(d) on the tile and each of its children: nowrap + a clip, any rule or
    the cascade's result, and a font-size below --fs-primary on the value."""
    found: list[str] = []
    floor = _px(s, path, "var(--fs-primary)")
    targets = [path] + [path + [c] for c in path[-1].get("children", []) if "tag" in c]
    for target in targets:
        for rule in s.rules:
            if not rh.isResolvable(rule.selector) or not rh.matchesSelector(rule.selector, target):
                continue
            ws = rh.declarationOf(rule.declarations, "white-space")
            clips = [
                prop for prop in ("overflow", "overflow-x", "text-overflow")
                if (v := rh.declarationOf(rule.declarations, prop))
                and (prop == "text-overflow" or v[0] in ("hidden", "clip"))
            ]
            if ws and ws[0] == "nowrap" and clips:
                found.append(f"{rule.selector}: nowrap + {', '.join(clips)}")
            if "tile-value" in _classes(target[-1]):
                size = rh.declarationOf(rule.declarations, "font-size")
                if size and _px(s, target, size[0]) < floor:
                    found.append(f"{rule.selector}: font-size {size[0]} < --fs-primary")
        ws = _computed(s, target, "white-space")
        overflow = {_computed(s, target, p) for p in ("overflow", "overflow-x")}
        if ws == "nowrap" and (overflow & {"hidden", "clip"} or _computed(s, target, "text-overflow")):
            found.append(f"{_classes(target[-1])}: the cascade resolves nowrap + a clip")
    return found


@_NODE_ONLY
@pytest.mark.parametrize("case", sorted(CASES))
def test_d_noRuleClipsOrShrinksTheLoadingTile(surface: rh.Surface, case: str):
    assert _clipViolations(surface, _loadingTilePath(surface, case)) == []


@_NODE_ONLY
def test_d_aShrunkenLoadingValue_isRed(tmp_path):
    """VC row 2: .tile-value at 20px in the loading level turns (d) red."""
    css = _readFile(_CSS) + '\n.tile[data-level="loading"] .tile-value { font-size: 20px; }\n'
    scratch = tmp_path / "dashboard.css"
    scratch.write_text(css, encoding="utf-8")
    s = _surface(str(scratch))
    for case in CASES:
        assert any("font-size 20px" in v for v in _clipViolations(s, _loadingTilePath(s, case))), case


@_NODE_ONLY
def test_d_aNowrapClipOnTheValue_isRed(tmp_path):
    css = _readFile(_CSS) + "\n.tile-value { white-space: nowrap; overflow: hidden; }\n"
    scratch = tmp_path / "dashboard.css"
    scratch.write_text(css, encoding="utf-8")
    s = _surface(str(scratch))
    assert any("nowrap" in v for v in _clipViolations(s, _loadingTilePath(s, "motion")))


@_NODE_ONLY
def test_c_theBodyWidthIsComputedFromTheSheet_notAConstant(tmp_path):
    """A wider card padding narrows the body the model compares against."""
    css = _readFile(_CSS) + "\n.card { padding: 8px 200px; }\n"
    scratch = tmp_path / "dashboard.css"
    scratch.write_text(css, encoding="utf-8")
    s = _surface(str(scratch))
    wide = _bodyContentWidth(s, _loadingTilePath(s, "motion"))
    shipped = _surface()
    path = _loadingTilePath(shipped, "motion")
    narrow = _bodyContentWidth(shipped, path)
    cardPath = path[: [i for i, n in enumerate(path) if "card" in _classes(n)][0] + 1]
    assert narrow - wide == 2 * 200 - _horizontalChrome(shipped, cardPath)
