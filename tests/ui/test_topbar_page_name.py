################################################################################
# File Name: test_topbar_page_name.py
# Purpose/Description: US-887-c (F-127) tests for the top bar's page name. The
#   V0.30 frame (specs/v030-frame-and-style-design.md s3, s3.2) names the page
#   in the bar's right slot and takes the per-card title row away, returning a
#   title band to every card body. Guarded here:
#     1. the NAMES -- each card carries its bar name in markup (`data-page-name`),
#        exactly Iris's measured list, and no card renders an `.card-title`;
#     2. the SLOT -- `#page-name` lives INSIDE `.topbar-right` (the grid keeps
#        three children), in Michroma 400 at --fs-meta, letter-spacing 0;
#     3. the FIT -- every name in use is <= 122 px wide, computed from Iris's
#        Michroma advance table, and a planted 135 px name fails the rule;
#     4. the RUNTIME -- the shipped carousel.js, booted against the shipped
#        markup, writes the current card's name into the bar on every move;
#     5. the CHIP -- #version-chip left the bar for #sys-detail, markup intact;
#     6. the DOT -- the active page dot is the one `--accent` element (s4.4).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Ralph (Rex)  | Initial -- US-887-c top-bar page name.
# ================================================================================
################################################################################

"""US-887-c tests for the top-bar page name and the retired card title row."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

from tests.ui.css_type_scale import DASHBOARD_CSS, readCss, ruleBlock  # noqa: E402
from tests.ui.test_topbar_three_column_grid import (  # noqa: E402
    PAGE_NAME_MAX_PX,
    michromaWidthPx,
    shippedPageNames,
)

_REPO = os.path.join(os.path.dirname(__file__), "..", "..")
_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_CONFIG = os.path.join(_REPO, "config.json")

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped browser JS",
)

# Iris's bar names (pm/inbox/2026-10-14-from-iris-SHAPE-CHECK-S103-PRD-...), keyed
# by the card's aria-label -- the kit label, which is a DIFFERENT string and keeps
# its value (tests/deploy/test_dashboard_kit.py). Driving is listed because it is
# the landing card from US-888-a; a name only has to be here to be allowed.
BAR_NAMES = {
    "Driving": "DRIVING",
    # MOVED PIN (US-896-a): the NAV card (CIO 2026-10-14: NAVIGATION is 135 px
    # and does not fit the 122 px slot; nav spec s3).
    "Navigation": "NAV",
    # MOVED PIN (US-889-b): the Engine card (Iris, 80 px).
    "Engine": "ENGINE",
    # MOVED PIN (US-890-a): the Fuel card replaces Fuel Trim (Iris, 53.5 px).
    "Fuel": "FUEL",
    "Home": "MOTION",
    "Alerts": "ALERTS",
    "System Status": "SYSTEM",
    "Battery": "BATTERY",
    "Light": "LIGHT",
}

# Iris's measured widths at 15 px / letter-spacing 0, rounded to the px she
# published. The model must reproduce them, or it is not her model.
IRIS_MEASURED_PX = {
    "DRIVING": 88,
    "ENGINE": 80,
    "MOTION": 87,
    "ALERTS": 86,
    "SYSTEM": 95,
    "BATTERY": 104,
    "FUEL": 53.5,
    "LIGHT": 62,
    "NAVIGATION": 135,
}


def _readHtml() -> str:
    with open(_HTML, encoding="utf-8") as fh:
        return fh.read()


def _stripComments(markup: str) -> str:
    return re.sub(r"<!--.*?-->", "", markup, flags=re.DOTALL)


def _cardTags(html: str) -> list[str]:
    """Every `<section class="card" ...>` opening tag, comments stripped."""
    return re.findall(r'<section class="card"[^>]*>', _stripComments(html), re.DOTALL)


def _attr(tag: str, name: str) -> str | None:
    match = re.search(rf'(?<![-\w]){re.escape(name)}="([^"]*)"', tag)
    return match.group(1) if match is not None else None


def _fontPx(token: str) -> float:
    match = re.search(rf"--{re.escape(token)}:\s*([0-9.]+)px", readCss(DASHBOARD_CSS))
    assert match is not None, f"--{token} is not a px token"
    return float(match.group(1))


# ---------------------------------------------------------------------------
# 1. The names, and the title rows that are gone.
# ---------------------------------------------------------------------------


def test_everyCardCarriesItsIrisBarName():
    """Each card names itself in the bar with Iris's short form, and the kit's
    aria-label keeps its own (longer) value -- two strings, two jobs."""
    tags = _cardTags(_readHtml())
    assert tags, "no cards found -- the markup moved"
    for tag in tags:
        label = _attr(tag, "aria-label")
        assert label in BAR_NAMES, f"card {label!r} has no agreed bar name"
        assert _attr(tag, "data-page-name") == BAR_NAMES[label], tag


def test_noCardRendersATitleRow():
    """Spec s3: pages no longer spend a title row. Markup AND sheet, so a stray
    rule cannot wait for the next h2 to come back."""
    assert "card-title" not in _stripComments(_readHtml())
    css = re.sub(r"/\*.*?\*/", "", readCss(DASHBOARD_CSS), flags=re.DOTALL)
    assert ".card-title" not in css


# ---------------------------------------------------------------------------
# 2. The slot.
# ---------------------------------------------------------------------------


def test_pageNameLivesInsideTheRightCluster_besideTheKebab():
    match = re.search(
        r'<div class="topbar-right">(.*?)</div>', _stripComments(_readHtml()), re.DOTALL
    )
    assert match is not None
    right = match.group(1)
    assert 'id="page-name"' in right
    assert right.index('id="page-name"') < right.index('id="menu-btn"')


def test_pageNameIsMichroma400AtTheMetaTier_noSpacing_noSynthesis():
    block = ruleBlock(readCss(DASHBOARD_CSS), "#page-name")
    assert "font-family: var(--font-display)" in block
    assert "font-weight: 400" in block
    assert "font-synthesis: none" in block
    assert "font-size: var(--fs-meta)" in block
    assert re.search(r"letter-spacing:\s*0\s*;", block), block
    assert not re.search(r"margin[-\w]*:[^;]*\bauto\b", block), "no auto margin (US-555)"
    assert _fontPx("fs-meta") >= 15, "a page name is never below 15 px"


def test_pageNameShipsEmpty_carouselFillsIt():
    """Like the clock: a literal name before the first paint would be a claim
    about a page the carousel has not yet decided."""
    assert re.search(r'<span id="page-name"></span>', _readHtml())


# ---------------------------------------------------------------------------
# 3. The fit -- Iris's 122 px rule.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,expected", sorted(IRIS_MEASURED_PX.items()))
def test_theModelReproducesIrisMeasurements(name: str, expected: int):
    assert michromaWidthPx(name, _fontPx("fs-meta")) == pytest.approx(expected, abs=1.0)


def test_everyPageNameInUseFitsTheBarRule():
    names = shippedPageNames()
    assert names, "no page names read from the markup"
    for name in names:
        width = michromaWidthPx(name, _fontPx("fs-meta"))
        assert width <= PAGE_NAME_MAX_PX, f"{name!r} is {width:.1f}px > {PAGE_NAME_MAX_PX}px"


def test_aPlanted135pxNameFailsTheRule_negativeControl():
    assert michromaWidthPx("NAVIGATION", _fontPx("fs-meta")) > PAGE_NAME_MAX_PX


def test_aGlyphMissingFromTheAdvanceTableFails_notGuessed():
    with pytest.raises(AssertionError, match="no Michroma advance"):
        michromaWidthPx("Driving", _fontPx("fs-meta"))


# ---------------------------------------------------------------------------
# 4. The runtime -- the shipped JS writes the name on every move.
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _routes() -> dict[str, Any]:
    return {
        "/system-status": {
            "wifi": {"state": "up", "ssid": "bench", "rssiDbm": -50},
            "obdLink": {"state": "down", "retries": 0, "lastSeenS": 2},
            "sync": {"lastOkTs": _now(), "rows": 50, "pending": 0, "stale": False},
            "power": {"mode": "car", "source": "external"},
            "drive": {"state": "idle", "driveId": None},
            "source": {"obd": {"available": False}},
            "idle": True,
            "ts": _now(),
        },
        "/light": {"lux": 120.0, "ts": _now()},
        "/dtc": {"codes": [], "newSinceTs": None, "ts": _now()},
        "/ltft-trend": None,
    }


def _textOf(node: dict[str, Any]) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _textOf(child))
    return "".join(out).strip()


def _barName(steps: list[dict[str, Any]]) -> tuple[str, rh.Surface]:
    dom = rh.runDashboard(routes=_routes(), steps=steps)
    surface = rh.dashboardSurface(dom["tree"])
    path = surface.pathById("page-name")
    assert path is not None, "#page-name is not in the DOM"
    return _textOf(path[-1]), surface


@_NODE_ONLY
def test_theBarNamesEveryCard_asTheCarouselMovesOntoIt():
    tags = _cardTags(_readHtml())
    for index, tag in enumerate(tags):
        steps = [{"flush": 4}, {"clickNth": {"selector": ".dot", "index": index}}, {"flush": 1}]
        name, surface = _barName(steps)
        if not surface.rendered(surface.pathsByClass("card")[index]):
            continue  # a vehicle-gated card owns no dot; the guard refuses it
        assert name == _attr(tag, "data-page-name"), (index, name)


@_NODE_ONLY
def test_theLandingCardIsNamedAtBoot_andNoTitleRowPaints():
    name, surface = _barName([{"flush": 4}])
    assert name == _attr(_cardTags(_readHtml())[0], "data-page-name")
    assert surface.pathsByClass("card-title") == []


# ---------------------------------------------------------------------------
# 5. The version chip moved; 6. the accent dot; 7. no timer moves the page.
# ---------------------------------------------------------------------------


def test_versionChipLivesInSysDetail_markupUnchanged():
    html = _stripComments(_readHtml())
    bar = re.search(r'<header id="topbar">(.*?)</header>', html, re.DOTALL)
    assert bar is not None and "version-chip" not in bar.group(1)
    detail = re.search(r'<div id="sys-detail"[^>]*>(.*?)\n  </div>', html, re.DOTALL)
    assert detail is not None, "#sys-detail moved"
    assert '<span id="version-chip">__DEPLOY_VERSION__</span>' in detail.group(1)


def test_theActivePageDotUsesTheAccent():
    block = ruleBlock(readCss(DASHBOARD_CSS), ".dot.active::before")
    assert "var(--accent)" in block


def test_noTimerChangesThePage_autoRotateStaysOff():
    with open(_CONFIG, encoding="utf-8") as fh:
        config = json.load(fh)
    assert config["pi"]["display"]["carousel"]["autoRotateS"] == 0
