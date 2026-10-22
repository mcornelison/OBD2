################################################################################
# File Name: test_warnings_icon.py
# Purpose/Description: US-898-a (F-127; specs/v030-warnings-page-design.md s4.2)
#   tests for the top bar's warnings icon and the WiFi glyph redrawn to make room
#   for it. Guarded here:
#     1. the VIEW -- the pure `alertIconView(alerts)` maps each states/alerts
#        fixture (tests/ui/fixtures/states/alerts/, written by the REAL provider
#        `buildAlertsState`) to Iris's look table (898-1), and a missing payload
#        reads `--`, never the provider's `none` all-clear;
#     2. the DOM -- the shipped carousel.js, booted over the shipped markup and
#        stylesheet, paints that view into `#glyph-warnings` with token colours,
#        reads states/alerts on EVERY tick, shows the icon on every card, and
#        navigates to ALERTS on a tap while moving;
#     3. the MOTION -- the pulse runs only for a live unacknowledged STOP and only
#        under `prefers-reduced-motion: no-preference`; reduced motion gets a
#        steady red outline instead;
#     4. the MARKUP -- the icon is a `span.glyph` in the left cluster, a control
#        with the #menu-btn hit-box pattern, and WiFi is a 1ch SVG whose id,
#        title and data-state binding are unchanged.
#   The width budget the icon spends lives in test_topbar_three_column_grid.py.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Ralph (Rex)  | Initial -- US-898-a top-bar warnings icon.
# 2026-10-20    | Ralph (Rex)  | US-898-b1 -- MOVED PIN: the tap finds ALERTS by the
#                               card's id, not its bar name (Iris U2).
# ================================================================================
################################################################################

"""US-898-a tests: the top bar's warnings icon, on every page."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

from pi.obdii.alerts_arbiter import buildAlertsState  # noqa: E402
from tests.ui.css_type_scale import DASHBOARD_CSS, readCss, ruleBlock  # noqa: E402

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped browser JS",
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROBE = os.path.join(_HERE, "carousel_probe.js")
_FIXTURES = os.path.join(_HERE, "fixtures", "states", "alerts")
_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")

ICON_ID = "glyph-warnings"

# The shipped panel: a top-bar glyph is a 3.5" signal (US-696 precedent).
PANEL = (480, 320)

# Iris's look table (brief 2026-10-18 + S108 review 2026-10-19), per fixture:
# (state, text, pulse, colour token).
LOOK = {
    "icon-none": ("none", "△", False, "--text-tertiary"),
    "icon-not-checked": ("not_checked", "?", False, "--amber-warn"),
    "icon-watch-2": ("watch", "▲2", False, "--amber-warn"),
    "icon-stop-pulsing": ("stop", "▲1", True, "--critical-red"),
    "icon-stop-acknowledged": ("stop", "▲1", False, "--critical-red"),
    "icon-count-120": ("watch", "▲99", False, "--amber-warn"),
    "icon-missing-payload": ("missing", "--", False, "--text-tertiary"),
}


def _fixture(name: str) -> Any:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _view(fn: str, *args: Any) -> Any:
    """One pure carousel.js function, evaluated under node.

    Through the probe's `--map` stdin mode: the 120-entry fixture overruns the
    Windows command-line limit as an argv argument.
    """
    proc = subprocess.run(
        [_NODE, _PROBE, "--map", fn],
        input=json.dumps([list(args)]),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)[0]


def _textOf(node: dict[str, Any]) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _textOf(child))
    return "".join(out).strip()


def _systemStatus(moving: bool) -> dict[str, Any]:
    now = "2026-10-20T17:30:00Z"
    return {
        "wifi": {"state": "up", "ssid": "bench", "rssiDbm": -50},
        # MOVED PIN (US-876-a): obdLink.lastSeenS is gone from system-status.
        "obdLink": {"state": "linked", "retries": 0},
        "sync": {"lastOkTs": now, "rows": 50, "pending": 0, "stale": False},
        "power": {"mode": "car", "source": "external"},
        "drive": {"state": "driving" if moving else "idle", "driveId": 7 if moving else None},
        "source": {"obd": {"available": True}},
        "idle": not moving,
        "ts": now,
    }


def _routes(alerts: Any, moving: bool = False) -> dict[str, Any]:
    routes: dict[str, Any] = {"/system-status": _systemStatus(moving)}
    if alerts is not None:
        routes["/alerts"] = alerts
    return routes


def _icon(dom: dict[str, Any]) -> tuple[list[dict[str, Any]], rh.Surface]:
    surface = rh.dashboardSurface(dom["tree"], viewport=PANEL)
    path = surface.pathById(ICON_ID)
    assert path is not None, f"#{ICON_ID} is not in the DOM"
    return path, surface


def _stripComments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _leftCluster() -> str:
    html = _stripComments(open(_HTML, encoding="utf-8").read())
    match = re.search(r'<div class="topbar-left">(.*?)</div>', html, re.DOTALL)
    assert match is not None, "the left cluster moved"
    return match.group(1)


# ---------------------------------------------------------------------------
# 0. The fixtures ARE the provider's shape.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(n for n in LOOK if n != "icon-missing-payload"))
def test_everyFixtureIsAStatesAlertsPayloadInTheProvidersShape(name: str):
    """A hand-drifted fixture stays green through a provider rename (US-628), so
    each one is held to the key set the SHIPPED builder emits today."""
    shipped = buildAlertsState([], None, datetime(2026, 10, 20, tzinfo=UTC),
                               dataSource=None, bootId="b")
    payload = _fixture(name)
    assert sorted(payload) == sorted(shipped)
    assert sorted(payload["icon"]) == sorted(shipped["icon"])


def test_theMissingPayloadFixtureIsNoPayloadAtAll():
    assert _fixture("icon-missing-payload") is None


# ---------------------------------------------------------------------------
# 1. The pure view -- 898-1.
# ---------------------------------------------------------------------------


@_NODE_ONLY
@pytest.mark.parametrize("name", sorted(LOOK))
def test_alertIconView_rendersIrisLookTable(name: str):
    state, text, pulse, _ = LOOK[name]
    assert _view("alertIconView", _fixture(name)) == {
        "state": state, "text": text, "pulse": pulse,
    }


@_NODE_ONLY
@pytest.mark.parametrize(
    "payload",
    [None, {}, {"icon": None}, {"icon": {"state": "bogus", "count": 1}}, "garbage"],
    ids=["null", "no-icon", "icon-null", "unknown-state", "not-an-object"],
)
def test_noReadablePayload_readsDashes_neverTheAllClearTriangle(payload: Any):
    """`none` is the provider's claim that the codes were read and nothing is
    active. Without a payload that claim is false (Iris S108 review)."""
    view = _view("alertIconView", payload)
    assert view == {"state": "missing", "text": "--", "pulse": False}


@_NODE_ONLY
def test_questionMarkOnlyForNotChecked():
    for name in LOOK:
        view = _view("alertIconView", _fixture(name))
        assert ("?" in view["text"]) == (view["state"] == "not_checked"), name


@_NODE_ONLY
@pytest.mark.parametrize("count,text", [(1, "▲1"), (9, "▲9"), (99, "▲99"), (100, "▲99")])
def test_countAbove99ShowsTheCap(count: int, text: str):
    alerts = {"icon": {"state": "watch", "count": count, "pulse": False}}
    assert _view("alertIconView", alerts)["text"] == text


@_NODE_ONLY
def test_aPulseFlagOnAWatchIconDoesNotAnimate():
    """Iris's table pulses STOP only; a watch with the flag set stays steady."""
    alerts = {"icon": {"state": "watch", "count": 1, "pulse": True}}
    assert _view("alertIconView", alerts)["pulse"] is False


# ---------------------------------------------------------------------------
# 2. The DOM the shipped JS leaves, resolved through the shipped cascade.
# ---------------------------------------------------------------------------


@_NODE_ONLY
@pytest.mark.parametrize("name", sorted(LOOK))
def test_theIconDomMatchesTheTable_perFixture(name: str):
    state, text, pulse, token = LOOK[name]
    dom = rh.runDashboard(routes=_routes(_fixture(name)), viewport=PANEL)
    path, surface = _icon(dom)
    attrs = path[-1]["attrs"]
    assert _textOf(path[-1]) == text
    assert attrs["data-state"] == state
    assert attrs["data-pulse"] == ("true" if pulse else "false")
    assert attrs.get("class") == "glyph"
    assert surface.rendered(path), "the icon is never hidden"
    color = surface.winningDeclaration(path, "color")
    assert color is not None and color[0] == f"var({token})", (name, color)


@_NODE_ONLY
@pytest.mark.parametrize("name", sorted(LOOK))
def test_onlyALiveUnacknowledgedStopDeclaresAnAnimation(name: str):
    dom = rh.runDashboard(routes=_routes(_fixture(name)), viewport=PANEL)
    path, surface = _icon(dom)
    animation = surface.winningDeclaration(path, "animation")
    assert (animation is not None) == LOOK[name][2], (name, animation)


@_NODE_ONLY
def test_theIconReadsStatesAlertsOnEveryTick():
    dom = rh.runDashboard(routes=_routes(_fixture("icon-none")), steps=[{"flush": 4}])
    alerts = [f for f in dom["fetches"] if f["url"] == "/alerts"]
    gear = [f for f in dom["fetches"] if f["url"] == "/gear"]
    assert gear, "the tick read no gear -- the fetch log moved"
    assert len(alerts) == len(gear), (len(alerts), len(gear))


@_NODE_ONLY
def test_aPayloadThatDisappearsFallsBackToDashes():
    """The icon follows the latest read: a 404 after a STOP is `--`, not a
    frozen red triangle."""
    dom = rh.runDashboard(
        routes=_routes(_fixture("icon-stop-pulsing")),
        steps=[{"flush": 4}, {"setRoutes": {"/alerts": None}}, {"flush": 4}],
    )
    path, _ = _icon(dom)
    assert _textOf(path[-1]) == "--"
    assert path[-1]["attrs"]["data-pulse"] == "false"


def _cardCount() -> int:
    return len(re.findall(r'<section class="card"', _stripComments(open(_HTML, encoding="utf-8").read())))


@_NODE_ONLY
def test_aDotWalkAcrossEveryCardShowsTheIconOnEach():
    alerts = _fixture("icon-watch-2")
    seen = 0
    for index in range(_cardCount()):
        steps = [{"flush": 4}, {"clickNth": {"selector": ".dot", "index": index}}, {"flush": 1}]
        dom = rh.runDashboard(routes=_routes(alerts), steps=steps, viewport=PANEL)
        path, surface = _icon(dom)
        card = surface.pathsByClass("card")[index]
        if not surface.rendered(card):
            continue  # a vehicle-gated card owns no dot; the guard refuses it
        seen += 1
        assert surface.rendered(path), f"the icon is not painted on card {index}"
        assert _textOf(path[-1]) == "▲2", index
    assert seen >= 2, "the walk reached too few cards to prove anything"


def _pageName(dom: dict[str, Any]) -> str:
    surface = rh.dashboardSurface(dom["tree"], viewport=PANEL)
    path = surface.pathById("page-name")
    assert path is not None
    return _textOf(path[-1])


@_NODE_ONLY
@pytest.mark.parametrize("name", ["icon-watch-2", "icon-missing-payload"])
def test_tappingTheIconOnDrivingWhileMovingOpensAlerts(name: str):
    """Iris U1: allowed while moving -- it only navigates, which a swipe already
    does. Still tappable with no payload (the `--` icon)."""
    routes = _routes(_fixture(name), moving=True)
    before = rh.runDashboard(routes=routes, steps=[{"flush": 4}], viewport=PANEL)
    assert _pageName(before) == "DRIVING", "the run did not start on the landing card"
    after = rh.runDashboard(
        routes=routes, steps=[{"flush": 4}, {"click": ICON_ID}, {"flush": 1}], viewport=PANEL
    )
    assert _pageName(after) == "ALERTS"


def test_theTapFindsAlertsByItsPageName_notByPosition():
    """MOVED PIN (US-898-b1): Iris U2 re-keys the target by the card's id, so
    the tap still never depends on the card's position."""
    js = open(_JS, encoding="utf-8").read()
    assert 'getAttribute("id") === "alerts-card"' in js


# ---------------------------------------------------------------------------
# 3. Motion -- reduced-motion aware.
# ---------------------------------------------------------------------------


def _iconRules() -> list[rh.Rule]:
    return [r for r in rh.parseCss(readCss(DASHBOARD_CSS)) if ICON_ID in r.selector]


def test_theIconAnimationLivesOnlyInsideNoPreference():
    animated = [r for r in _iconRules() if rh.declarationOf(r.declarations, "animation")]
    assert animated, "the STOP pulse is gone"
    for rule in animated:
        assert "prefers-reduced-motion: no-preference" in rule.media, rule.selector
        assert '[data-pulse="true"]' in rule.selector and '[data-state="stop"]' in rule.selector


def test_reducedMotionGetsASteadyRedOutline_andNoAnimation():
    reduced = [r for r in _iconRules() if "prefers-reduced-motion: reduce" in r.media]
    assert reduced, "reduced motion has no steady stand-in for the pulse"
    for rule in reduced:
        assert rh.declarationOf(rule.declarations, "animation") is None
    outlines = [rh.declarationOf(r.declarations, "outline") for r in reduced]
    assert any(o and "var(--critical-red)" in o[0] for o in outlines), outlines
    assert all('[data-pulse="true"]' in r.selector for r in reduced)


# ---------------------------------------------------------------------------
# 4. Markup + sheet.
# ---------------------------------------------------------------------------


def test_theIconIsASpanGlyphInTheLeftClusterAfterTheSyncGlyph():
    left = _leftCluster()
    match = re.search(rf'<span ([^>]*id="{ICON_ID}"[^>]*)>([^<]*)</span>', left)
    assert match is not None, "the icon is not a span in the left cluster"
    assert 'class="glyph"' in match.group(1)
    assert "hidden" not in match.group(1), "the icon is never hidden"
    assert match.group(2) == "--", "nothing has been read before the first tick"
    assert left.index('id="glyph-sync"') < left.index(f'id="{ICON_ID}"')


def test_theIconIsAControlWithTheKebabHitBoxPattern():
    css = readCss(DASHBOARD_CSS)
    block = ruleBlock(css, f"#{ICON_ID}")
    assert "position: relative" in block
    assert "cursor: pointer" in block
    after = ruleBlock(css, f"#{ICON_ID}::after")
    assert re.search(r'content:\s*""', after)
    assert "position: absolute" in after
    assert "inset: calc((var(--bar-h) - var(--tap-min)) / 2)" in after


def test_theIconSlotIsAFixedThreeCharacterMonoBox():
    css = readCss(DASHBOARD_CSS)
    block = ruleBlock(css, f"#{ICON_ID}")
    assert "width: calc(3 * (1ch + var(--glyph-ls)))" in block
    assert "min-width" not in block, "min-width reflows at two digits (Iris S108)"
    assert "text-align: start" in block
    assert "font-family: var(--font-mono)" in block
    assert "height: var(--bar-h)" in block
    assert "font-size" not in block, "the icon keeps the bar's glyph tier"


def test_theGlyphLetterSpacingIsOneScopedProperty():
    css = readCss(DASHBOARD_CSS)
    assert "--glyph-ls: 0.04em" in ruleBlock(css, "#topbar")
    assert "letter-spacing: var(--glyph-ls)" in ruleBlock(css, "#topbar .glyph")


def test_iconColoursAreTokensOnly():
    for rule in _iconRules():
        for prop in ("color", "outline", "background"):
            found = rh.declarationOf(rule.declarations, prop)
            if found is None:
                continue
            assert not re.search(r"#[0-9a-fA-F]{3,8}\b", found[0]), (rule.selector, found)


def test_wifiIsA1chSvg_idTitleAndStateBindingUnchanged():
    left = _leftCluster()
    match = re.search(r'<span ([^>]*id="glyph-wifi"[^>]*)>(.*?)</span>', left, re.DOTALL)
    assert match is not None
    attrs, inner = match.groups()
    assert 'class="glyph"' in attrs and 'title="WiFi"' in attrs
    assert 'data-state="neutral"' in attrs
    assert inner.strip().startswith("<svg"), "WiFi is drawn as an inline SVG"
    assert "((•))" not in inner
    assert len(re.findall(r"<path\b", inner)) == 3, "three arcs"
    assert len(re.findall(r"<circle\b", inner)) == 1, "and a dot"
    assert "px" not in inner, "relative units only"
    css = readCss(DASHBOARD_CSS)
    svg = ruleBlock(css, "#glyph-wifi .wifi-mark")
    assert "width: 1ch" in svg and "height: 1em" in svg
    assert "stroke: currentColor" in svg
