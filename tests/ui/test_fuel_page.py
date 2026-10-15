################################################################################
# File Name: test_fuel_page.py
# Purpose/Description: US-890-a (F-127) tests for the Fuel card -- V0.30 Fuel
#   layout A (specs/v030-fuel-page-design.md s3-s4.4). Guarded:
#     1. the SLOT -- the Fuel card replaces Fuel Trim (aria-label Fuel,
#        data-page-name FUEL) at index 2, after Engine; still bound to
#        states/ltft-trend and still shipping the vehicle gate closed;
#     2. the UPPER ROWS -- airflow, loop, total trim and the three MPG figures
#        ship "--" + "not published" until their stories land, and stay so
#        under every trend state (gated, absent, live): never blank;
#     3. the TREND VIEW -- dots are exactly the inMedian points (a 7-drive
#        payload draws 5), the median is one flat line across them, the
#        baseline dashed, colour only from `level`, a point with isReset is
#        not drawn and the row says "ECU relearning", insufficient -> the
#        provider's reason and no chart;
#     4. the SHIPPED DOM -- the same, painted by the real tick;
#     5. the GREP GATE -- no trim threshold in carousel.js, with a planted
#        negative control;
#     6. the CSS -- colour only through data-level, the dots never coloured.
#   NOT GUARDED, stated rather than implied: the render harness resolves the
#   cascade, not layout (render_harness.py fidelity limit 1); the glass check
#   is the R15 screenshot owed on the Pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Ralph (Rex)  | Initial -- US-890-a Fuel card + trend row.
# ================================================================================
################################################################################

"""US-890-a tests for the Fuel card and its fuel-trim trend row."""

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
    _driving,
    _parked,
)
from tests.ui.test_dashboard_fidelity_pass import _stripJsComments  # noqa: E402
from tests.ui.test_engine_page import _classes, _ms, _textOf  # noqa: E402

_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
_CSS = os.path.join(rh.DASHBOARD_DIR, "dashboard.css")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "fuel")
_ARCH = os.path.join(os.path.dirname(__file__), "..", "..", "specs", "architecture.md")

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped browser JS",
)

# The card order (US-890-a validation row "Card order"), by kit label.
CARD_ORDER = [
    "Driving", "Engine", "Fuel", "Home", "Alerts", "System Status", "Battery", "Light"
]

# This story's fixtures (spec s7). Later Fuel stories add their own to the same
# directory, so the set is asserted as PRESENT, not as the whole directory.
FIXTURE_NAMES = ["trend-healthy", "trend-amber", "ltft-reset-zero-flat", "trend-seven-drives"]

# The upper rows and the story that owns each (acceptance 3).
UPPER_SLOTS = [
    ("airflow", "AIRFLOW"),
    ("loop", "LOOP"),
    ("total-trim", "TOTAL TRIM"),
    ("mpg-last30", "LAST 30 S"),
    ("mpg-this-drive", "THIS DRIVE"),
    ("mpg-since-reset", "SINCE RESET"),
]
NOT_PUBLISHED = "not published"
RELEARNING = "ECU relearning"
TREND_LABEL = "FUEL TRIM TREND"
GATED_REASON = "no engine data"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _trend(name: str) -> dict[str, Any]:
    return _fixture(name)["ltft-trend"]


def _probe(fn: str, *args: object) -> Any:
    cmd = [_NODE or "node", _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _view(payload: Any) -> Any:
    return _probe("fuelTrendView", payload)


def _fuelMarkup() -> str:
    match = re.search(r'<section class="card"[^>]*id="fuel-card".*?</section>', _read(_HTML), re.S)
    assert match is not None, "no #fuel-card section in dashboard.html"
    return match.group(0)


def _inFuel(path: list[dict[str, Any]]) -> bool:
    return any(n.get("attrs", {}).get("id") == "fuel-card" for n in path)


def _fuelPaths(surface: rh.Surface, cls: str) -> list[list[dict[str, Any]]]:
    return [p for p in surface.pathsByClass(cls) if _inFuel(p)]


def _fuelText(surface: rh.Surface, cls: str) -> list[str]:
    return [_textOf(p[-1]) for p in _fuelPaths(surface, cls) if surface.rendered(p)]


def _boot(trend: Any = None, system: Any = None, nowIso: str = "2026-10-20T15:12:30Z") -> rh.Surface:
    routes: dict[str, Any] = {}
    if trend is not None:
        routes["/ltft-trend"] = trend
    if system is not None:
        routes["/system-status"] = system
    dom = rh.runDashboard(routes=routes, nowMs=_ms(nowIso), steps=[{"flush": 4}])
    return rh.dashboardSurface(dom["tree"])


def _bootFixture(name: str) -> rh.Surface:
    fx = _fixture(name)
    return _boot(trend=fx["ltft-trend"], system=_driving(), nowIso=fx["now"])


def _dotDrives(surface: rh.Surface) -> list[str]:
    return [p[-1]["attrs"].get("data-drive") for p in _fuelPaths(surface, "fuel-trend-dot")]


def _fuelRules() -> list[tuple[str, str]]:
    return [
        (rule.selector.strip(), rule.declarations)
        for rule in rh.parseCss(_read(_CSS))
        if "#fuel-card" in rule.selector
    ]


def _rule(selector: str) -> str:
    bodies = [body for sel, body in _fuelRules() if sel == selector]
    assert bodies, f"no rule {selector!r}"
    return " ".join(bodies)


# ---------------------------------------------------------------------------
# 1. The slot -- Fuel replaces Fuel Trim, index 2 after Engine (E-2).
# ---------------------------------------------------------------------------


def test_cardOrder_fuelSitsRightAfterEngine():
    labels = re.findall(r'<section class="card"[^>]*?aria-label="([^"]+)"', _read(_HTML), re.S)
    assert labels == CARD_ORDER


def test_fuelCard_isNamedFuel_andKeepsTheTrendSourceAndItsGate():
    tags = re.findall(r'<section class="card"[^>]*>', _read(_HTML), re.S)
    tag = tags[2]
    assert 'id="fuel-card"' in tag
    assert 'aria-label="Fuel"' in tag
    assert 'data-page-name="FUEL"' in tag
    assert 'data-state="ltft-trend"' in tag
    assert 'data-gated="true"' in tag


def test_fuelTrimCard_isRetired():
    markup = re.sub(r"<!--.*?-->", "", _read(_HTML), flags=re.S)
    assert 'aria-label="Fuel"' in markup, "the stripper ate the markup -- the pin below is vacuous"
    assert "Fuel Trim" not in markup
    assert "FUEL TRIM\"" not in markup


def test_sourceCardSpec_ltftTrendIsTheFuelCardTrendSlot():
    spec = _probe("sourceCardSpec", "ltft-trend")
    assert spec["title"] == "Fuel"
    assert spec["slot"] == ".fuel-trend"
    assert spec["vehicleGated"] is True
    assert spec["noData"]["label"] == TREND_LABEL


def test_thisStorysFixturesArePresent():
    for name in FIXTURE_NAMES:
        fx = _fixture(name)
        assert fx["description"], name
        assert isinstance(fx["ltft-trend"], dict), name


# ---------------------------------------------------------------------------
# 2. The upper rows -- "--" + "not published", never blank.
# ---------------------------------------------------------------------------


def test_upperRows_shipDashDashAndNotPublished_inTheMarkup():
    markup = _fuelMarkup()
    for slot, label in UPPER_SLOTS:
        match = re.search(
            rf'<div class="fuel-reading[^"]*" data-slot="{slot}"[^>]*>(.*?)</div>', markup, re.S
        )
        assert match is not None, f"no {slot} slot"
        inner = match.group(1)
        assert f'<span class="fuel-label">{label}</span>' in inner, slot
        assert '<span class="fuel-value">--</span>' in inner, slot
        assert f'<span class="fuel-note">{NOT_PUBLISHED}</span>' in inner, slot


@_NODE_ONLY
@pytest.mark.parametrize(
    "trend,system",
    [
        (None, None),
        (None, "driving"),
        ("trend-healthy", "parked"),
        ("trend-healthy", "driving"),
    ],
    ids=["nothing-read", "no-trend-file", "gated-bench", "live-trend"],
)
def test_upperRows_stayDashDashUnderEveryTrendState(trend: str | None, system: str | None):
    payload = None if trend is None else _trend(trend)
    sysPayload = {"driving": _driving(), "parked": _parked(), None: None}[system]
    surface = _boot(trend=payload, system=sysPayload)
    assert _fuelText(surface, "fuel-label")[: len(UPPER_SLOTS)] == [lbl for _s, lbl in UPPER_SLOTS]
    assert _fuelText(surface, "fuel-value") == ["--"] * len(UPPER_SLOTS)
    assert _fuelText(surface, "fuel-note") == [NOT_PUBLISHED] * len(UPPER_SLOTS)


# ---------------------------------------------------------------------------
# 3. The trend view.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_sevenDrives_drawsExactlyTheFiveInMedian():
    payload = _trend("trend-seven-drives")
    assert len(payload["points"]) == 7
    view = _view(payload)
    assert [d["driveId"] for d in view["chart"]["dots"]] == [111, 112, 113, 114, 115]
    inMedian = [p["driveId"] for p in payload["points"] if p["inMedian"]]
    assert [d["driveId"] for d in view["chart"]["dots"]] == inMedian


@_NODE_ONLY
@pytest.mark.parametrize("name", ["trend-healthy", "trend-amber", "trend-seven-drives"])
def test_medianLine_isFlatAcrossTheDrawnDots(name: str):
    chart = _view(_trend(name))["chart"]
    xs = [d["x"] for d in chart["dots"]]
    assert chart["median"]["x1"] == min(xs)
    assert chart["median"]["x2"] == max(xs)
    assert chart["baseline"] is not None


@_NODE_ONLY
def test_headline_isTheProviderMedian_andLevelIsTheProviders():
    payload = _trend("trend-amber")
    view = _view(payload)
    assert view["level"] == "amber"
    assert view["value"] == "+3.20%"
    assert payload["median"] == 3.2


@_NODE_ONLY
def test_level_comesOnlyFromTheProvider_notFromTheValues():
    """The same points under a different provider level -> a different level and
    the identical chart: the view never reads a colour off a trim."""
    payload = _trend("trend-amber")
    relabelled = dict(payload, level="ok")
    amber = _view(payload)
    ok = _view(relabelled)
    assert ok["level"] == "ok"
    assert ok["chart"] == amber["chart"]


@_NODE_ONLY
def test_resetPoint_isNotDrawn_andTheRowSaysEcuRelearning():
    payload = _trend("ltft-reset-zero-flat")
    reset = [p for p in payload["points"] if p.get("isReset")]
    assert [p["driveId"] for p in reset] == [115]
    assert reset[0]["ltftAvg"] == 0.0 and reset[0]["inMedian"] is True
    view = _view(payload)
    assert view["relearning"] == RELEARNING
    assert [d["driveId"] for d in view["chart"]["dots"]] == [111, 112, 113, 114]


@_NODE_ONLY
def test_noResetPoint_saysNothingAboutRelearning():
    assert _view(_trend("trend-healthy"))["relearning"] is None


@_NODE_ONLY
def test_insufficient_showsTheProvidersReason_andNoChart():
    payload = dict(
        _trend("trend-healthy"), sufficient=False, level="insufficient", median=None,
        reason="not enough qualifying drives yet",
    )
    view = _view(payload)
    assert view["sufficient"] is False
    assert view["level"] == "insufficient"
    assert view["value"] is None
    assert view["reason"] == "not enough qualifying drives yet"
    assert view["chart"] is None


@_NODE_ONLY
def test_claimedSufficientWithNoMedian_isStillInsufficient():
    """`ltftTrendView`'s sufficiency rule carries over (contextAnchor)."""
    view = _view(dict(_trend("trend-healthy"), median=None))
    assert view["sufficient"] is False
    assert view["chart"] is None


@_NODE_ONLY
def test_nonObjectPayload_isNoView():
    assert _view(None) is None
    assert _view([]) is None


# ---------------------------------------------------------------------------
# 4. The shipped DOM.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_dom_sevenDrives_paintsFiveDots():
    surface = _bootFixture("trend-seven-drives")
    assert _dotDrives(surface) == ["111", "112", "113", "114", "115"]
    assert len(_fuelPaths(surface, "fuel-trend-median")) == 1
    assert len(_fuelPaths(surface, "fuel-trend-baseline")) == 1


@_NODE_ONLY
def test_dom_amber_headlineRowCarriesTheLevel_dotsCarryNone():
    surface = _bootFixture("trend-amber")
    rows = _fuelPaths(surface, "fuel-trend-row")
    assert len(rows) == 1
    assert rows[0][-1]["attrs"]["data-level"] == "amber"
    assert _fuelText(surface, "fuel-trend-value") == ["+3.20%"]
    for dot in _fuelPaths(surface, "fuel-trend-dot"):
        assert "data-level" not in dot[-1]["attrs"]


@_NODE_ONLY
def test_dom_reset_saysEcuRelearning_andDrawsNoDotForThatDrive():
    surface = _bootFixture("ltft-reset-zero-flat")
    assert _fuelText(surface, "fuel-trend-relearn") == [RELEARNING]
    assert "115" not in _dotDrives(surface)
    assert _dotDrives(surface) == ["111", "112", "113", "114"]


@_NODE_ONLY
def test_dom_benchWithNoVehicle_trendRowSpeaksTheGate_andShowsNoDots():
    surface = _boot(trend=_trend("trend-healthy"), system=_parked())
    card = _fuelPaths(surface, "card")
    assert card and card[0][-1]["attrs"].get("data-gated") == "true"
    host = _fuelPaths(surface, "fuel-trend")
    assert host
    text = _textOf(host[0][-1])
    assert TREND_LABEL in text and GATED_REASON in text
    assert _dotDrives(surface) == []


@_NODE_ONLY
def test_dom_vehicleConnected_opensTheGate():
    surface = _bootFixture("trend-healthy")
    card = _fuelPaths(surface, "card")
    assert card[0][-1]["attrs"].get("data-gated") == "false"
    assert _fuelText(surface, "fuel-label")[-1] == TREND_LABEL


@_NODE_ONLY
@pytest.mark.parametrize(
    "overrides",
    [
        {"sufficient": False, "level": "insufficient", "median": None,
         "reason": "not enough qualifying drives yet"},
        {"level": "ok", "median": None},
        {"sufficient": False, "level": "ok"},
    ],
    ids=["insufficient", "claims-sufficient-no-median", "mislabelled-ok"],
)
def test_dom_insufficient_neverPaintsATrimOrADot(overrides: dict[str, Any]):
    """Ported from the retired test_carousel_fuel_trim_visible_unavailable.py:
    too little data never paints a confident trim -- no headline value, no dot,
    no percent anywhere in the trend row, and the row is not green-or-amber."""
    payload = dict(_trend("trend-healthy"), **overrides)
    surface = _boot(trend=payload, system=_driving())
    rows = _fuelPaths(surface, "fuel-trend-row")
    assert rows[0][-1]["attrs"]["data-level"] == "insufficient"
    assert _fuelPaths(surface, "fuel-trend-value") == []
    assert _dotDrives(surface) == []
    assert "%" not in _textOf(_fuelPaths(surface, "fuel-trend")[0][-1])


@_NODE_ONLY
def test_dom_noTrendFile_namesTheTrend_notABlank():
    surface = _boot(system=_driving())
    text = _textOf(_fuelPaths(surface, "fuel-trend")[0][-1])
    assert TREND_LABEL in text
    assert text.strip() != ""


# ---------------------------------------------------------------------------
# 5. The grep gate -- no trim threshold in carousel.js.
# ---------------------------------------------------------------------------

# The provider's threshold fields: the page must never read them.
_THRESHOLD_FIELDS = ("noiseFloorPp", "faultAbs", "okAbs", "driftAbs", "deviationPp")
# A trim compared with a number literal.
_TRIM_COMPARE = re.compile(
    r"\b(?:ltftAvg|median|baseline|LONG_FUEL_TRIM_1|SHORT_FUEL_TRIM_1)\b[\w.\]\)]*\s*"
    r"(?:[<>]=?)\s*-?\d"
)


def _trimThresholdHits(source: str) -> list[str]:
    code = _stripJsComments(source)
    hits = [name for name in _THRESHOLD_FIELDS if name in code]
    hits += _TRIM_COMPARE.findall(code)
    return hits


def test_carouselJs_holdsNoTrimThreshold():
    assert _trimThresholdHits(_read(_JS)) == []


@pytest.mark.parametrize(
    "planted",
    ["if (p.ltftAvg >= 10) x = 1;", "var y = data.faultAbs;", "if (median < -4) z();"],
)
def test_trimThresholdGate_catchesAPlantedThreshold(planted: str):
    assert _trimThresholdHits(_read(_JS) + "\n" + planted + "\n") != []


# ---------------------------------------------------------------------------
# 6. The CSS -- colour only through data-level; the dots never colour.
# ---------------------------------------------------------------------------


def test_css_trendColour_onlyThroughDataLevel():
    for selector in (
        '#fuel-card .fuel-trend-row[data-level="amber"] .fuel-trend-value',
        '#fuel-card .fuel-trend-row[data-level="down"] .fuel-trend-value',
    ):
        assert "var(--amber-warn)" in _rule(selector), selector
    assert "var(--text-primary)" in _rule("#fuel-card .fuel-trend-value")


def test_css_dotsNeverColour():
    for selector, body in _fuelRules():
        if "fuel-trend-dot" in selector:
            assert "data-level" not in selector, selector
            assert "amber" not in body and "red" not in body and "green" not in body, selector


def test_css_fuelRules_useTokensOutsideTheScopedBlock():
    for selector, body in _fuelRules():
        if selector == "#fuel-card":
            continue
        assert not re.search(r"\b\d+px\b", body), (selector, body)
        assert "#" not in body, (selector, body)


# ---------------------------------------------------------------------------
# 7. Rule 10 -- architecture.md names the card and the state it reads.
# ---------------------------------------------------------------------------


def test_architectureMd_namesTheFuelCardAndItsStates():
    arch = _read(_ARCH)
    assert "US-890-a" in arch
    section = arch[arch.index("US-890-a"):]
    assert "Fuel Trim" in section[:3000]
    assert "states/ltft-trend" in section[:3000]
    assert "inMedian" in section[:3000]


@_NODE_ONLY
def test_dom_fuelCard_paintsNoLegacyBarsAndNoTiles_whenLive():
    """The Fuel Trim card's per-drive bars (each coloured by its own level) are
    gone from the Fuel card: a coloured single drive is what s4.4 forbids."""
    surface = _bootFixture("trend-healthy")
    assert _fuelPaths(surface, "ltft-bars") == []
    assert _fuelPaths(surface, "ltft-bar") == []
    assert _fuelPaths(surface, "tile") == []
    for path in _fuelPaths(surface, "fuel-reading"):
        assert "tile" not in _classes(path[-1])
