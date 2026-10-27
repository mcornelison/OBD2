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
#        baseline dashed, colour only from `level`, insufficient -> the
#        provider's reason (after a reset, its "ECU relearning") and no chart;
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
# 2026-10-15    | Rex (US-890-b) | AIRFLOW from params.MAF against params.MAF
#                                .scale.max (section 8). PIN CHANGE: the two
#                                upper-row tests no longer expect AIRFLOW to be
#                                "not published" (UNPUBLISHED_SLOTS).
# 2026-10-15    | Rex (US-890-c) | LOOP chip + TOTAL TRIM from obd-live.fuel
#                                (section 9). PIN CHANGES: UNPUBLISHED_SLOTS
#                                drops loop and total-trim; with no obd-live
#                                file both now say "no source" (as AIRFLOW);
#                                the builder-equality test also covers this
#                                story's fixtures and feeds a status label
#                                ('CL') as itself.
# 2026-10-15    | Rex (US-890-d) | THIS DRIVE + SINCE RESET from states/fuel-
#                                economy with the s4.6 reasons (section 10).
#                                PIN CHANGES: UNPUBLISHED_SLOTS drops both (only
#                                LAST 30 S stays "not published"); with no
#                                fuel-economy file both say "no source".
# 2026-10-15    | Rex (US-890-e) | LAST 30 S from fuel-economy.recent (section 11).
#                                PIN CHANGES: MPG_REASON_TEXT gains
#                                too_few_samples, so the one-case-per-code test
#                                matches the table against thisDrive's AND
#                                recent's codes; mpg-null-reasons and
#                                sinceReset-never regenerated with 'recent'
#                                (last30-not-published keeps it absent).
# 2026-10-19    | Ralph (Rex)  | US-892-b -- MOVED PIN: the Motion card replaces the Home
#                               card at index 4.
# 2026-10-19    | Ralph (Rex)  | US-890-g -- the per-point isReset branch and the
#                               ltft-reset-zero-flat fixture go; 'ECU relearning'
#                               is the provider's reason (ltft-relearning-after-reset,
#                               == buildLtftTrendState of _RELEARNING_DRIVES).
# 2026-10-23    | Ralph (Rex)  | US-894-e -- MOVED PIN: the Battery card is retired
#               |              | (9 -> 8).
# 2026-10-26    | Rex (US-891-c) | MOVED PIN: the O2 card joins between Fuel and Motion.
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

from pi.splash.ltft_trend_emitter import REASON_RELEARNING_AFTER_RESET  # noqa: E402
from tests.ui.test_carousel_kebab_always_visible import (  # noqa: E402
    _driving,
    _parked,
)
from tests.ui.test_dashboard_fidelity_pass import _stripJsComments  # noqa: E402
from tests.ui.test_engine_page import (  # noqa: E402
    _bodyWidthPx,
    _classes,
    _decl,
    _monoWidth,
    _ms,
    _px,
    _textOf,
)

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

# This story's fixtures (spec s7). Later Fuel stories add their own to the same
# directory, so the set is asserted as PRESENT, not as the whole directory.
# US-890-g: ltft-reset-zero-flat (a hand-set per-point isReset) is retired; the
# relearning fixture is the provider's own output for _RELEARNING_DRIVES.
FIXTURE_NAMES = [
    "trend-healthy", "trend-amber", "ltft-relearning-after-reset", "trend-seven-drives",
]

# US-890-g: the relearning fixture's per-drive input. Drive 111 reads LTFT 0.00
# flat (an adaptive-memory reset); 112-114 each clear the gate (90 C >= 85 C,
# closed loop, 25 >= 20 samples), so the reset epoch holds 3 points, short of 5.
# driveId: (drive start ts, LTFT %, samples).
_RELEARNING_DRIVES: dict[int, tuple[str, float, int]] = {
    111: ("2026-10-11T14:00:00Z", 0.0, 25),
    112: ("2026-10-12T14:00:00Z", -1.2, 25),
    113: ("2026-10-13T14:00:00Z", -0.8, 25),
    114: ("2026-10-14T14:00:00Z", -1.6, 25),
}
_RELEARNING_COOLANT_C = 90.0
_RELEARNING_CADENCE_S = 5  # the ~5 s LTFT cadence the provider's gate is sized on

# The upper rows and the story that owns each (acceptance 3).
UPPER_SLOTS = [
    ("airflow", "AIRFLOW"),
    ("loop", "LOOP"),
    ("total-trim", "TOTAL TRIM"),
    ("mpg-last30", "LAST 30 S"),
    ("mpg-this-drive", "THIS DRIVE"),
    ("mpg-since-reset", "SINCE RESET"),
]
# US-890-b: AIRFLOW is published now; US-890-c: LOOP and TOTAL TRIM too;
# US-890-d: THIS DRIVE and SINCE RESET (states/fuel-economy). LAST 30 S reads
# fuel-economy.recent since US-890-e, but with NO fuel-economy file (or one from
# a provider without the field) it still says "not published".
_OBD_LIVE_SLOTS = ("airflow", "loop", "total-trim")
_FUEL_ECONOMY_SLOTS = ("mpg-this-drive", "mpg-since-reset")
UNPUBLISHED_SLOTS = [
    (s, lbl) for s, lbl in UPPER_SLOTS if s not in _OBD_LIVE_SLOTS + _FUEL_ECONOMY_SLOTS
]
NOT_PUBLISHED = "not published"
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


def _relearningPerDrive() -> dict[int, tuple[str, list[tuple[str, str, float]]]]:
    """_RELEARNING_DRIVES as buildDriveRecords' raw rows: coolant, loop, LTFT per cycle."""
    from datetime import datetime, timedelta

    from pi.splash import ltft_trend_emitter as lte

    perDrive: dict[int, tuple[str, list[tuple[str, str, float]]]] = {}
    for driveId, (startTs, ltft, samples) in _RELEARNING_DRIVES.items():
        start = datetime.strptime(startTs, "%Y-%m-%dT%H:%M:%SZ")
        rows: list[tuple[str, str, float]] = []
        for cycle in range(samples):
            for offset, name, value in (
                (0, lte.COOLANT_PID, _RELEARNING_COOLANT_C),
                (1, lte.FUEL_SYSTEM_PID, float(lte.FUEL_SYSTEM_CLOSED_LOOP)),
                (2, lte.LTFT_PID, ltft),
            ):
                at = start + timedelta(seconds=cycle * _RELEARNING_CADENCE_S + offset)
                rows.append((at.strftime("%Y-%m-%dT%H:%M:%SZ"), name, value))
        perDrive[driveId] = (startTs, rows)
    return perDrive


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


def _boot(
    trend: Any = None,
    system: Any = None,
    nowIso: str = "2026-10-20T15:12:30Z",
    obdLive: Any = None,
    fuelEconomy: Any = None,
) -> rh.Surface:
    routes: dict[str, Any] = {}
    if trend is not None:
        routes["/ltft-trend"] = trend
    if system is not None:
        routes["/system-status"] = system
    if obdLive is not None:
        routes["/obd-live"] = obdLive
    if fuelEconomy is not None:
        routes["/fuel-economy"] = fuelEconomy
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
    # MOVED PIN (US-896-a): the NAV card took index 1, so Fuel is index 3.
    tag = tags[3]
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
    for slot, label in UNPUBLISHED_SLOTS:
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
    # US-890-b/c/d: no obd-live and no fuel-economy file -> AIRFLOW, LOOP,
    # TOTAL TRIM, THIS DRIVE and SINCE RESET say why ("no source"), never
    # blank; LAST 30 S is still "not published".
    assert _fuelText(surface, "fuel-note") == [
        NOT_PUBLISHED if (s, lbl) in UNPUBLISHED_SLOTS else "no source" for s, lbl in UPPER_SLOTS
    ]


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


def test_relearningFixture_ltftTrendIsWhatTheBuilderEmits():
    """
    Given: the ltft-relearning-after-reset fixture
    When: _RELEARNING_DRIVES is run through buildDriveRecords + buildLtftTrendState
          at the fixture's `now`
    Then: the builder's output equals the payload -- the provider, not a hand,
          says 'ECU relearning' (US-890-g).
    """
    from pi.splash.ltft_trend_emitter import buildDriveRecords, buildLtftTrendState

    fx = _fixture("ltft-relearning-after-reset")
    built = buildLtftTrendState(
        driveRecords=buildDriveRecords(_relearningPerDrive()), nowIso=fx["now"]
    )
    assert fx["ltft-trend"] == built
    assert built["reason"] == REASON_RELEARNING_AFTER_RESET
    assert built["epochBreak"] is True and len(built["points"]) == 3


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
def test_dom_relearning_saysEcuRelearningInTheReason_andDrawsNoDot():
    surface = _bootFixture("ltft-relearning-after-reset")
    assert _fuelText(surface, "fuel-trend-reason") == [REASON_RELEARNING_AFTER_RESET]
    assert _dotDrives(surface) == []
    assert _fuelPaths(surface, "fuel-trend-chart") == []


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


# ---------------------------------------------------------------------------
# 8. US-890-b -- AIRFLOW from params.MAF against params.MAF.scale.max.
#    specs/v030-fuel-page-design.md s4.1 (Atlas S104 ruling 2): one decimal at
#    --fs-hero, a bar 0..max; above max the bar is exactly full, the number
#    unclamped, no "sensor limit", nothing amber or red.
# ---------------------------------------------------------------------------

AIRFLOW_FIXTURES = [
    "idle-closed", "cruise-closed", "wot-near-max", "synthetic-scale-150", "maf-null", "stale",
]

# Fixture -> (text, unit, fill %, stale, note). The fill is value / scale.max.
_AIRFLOW_EXPECTED: dict[str, tuple[str, str, float | None, bool, str]] = {
    "idle-closed": ("3.6", "g/s", 3.57 / 160 * 100, False, ""),
    "cruise-closed": ("16.2", "g/s", 16.24 / 160 * 100, False, ""),
    "wot-near-max": ("158.7", "g/s", 158.69 / 160 * 100, False, ""),
    "synthetic-scale-150": ("158.7", "g/s", 100, False, ""),
    "maf-null": ("--", "", None, False, "not read"),
    "stale": ("16.2", "g/s", 16.24 / 160 * 100, True, "12 s"),
}


def _airflowView(obdLive: Any, nowIso: str = "2026-10-20T15:12:30Z") -> dict[str, Any]:
    return _probe("fuelAirflowView", obdLive, _ms(nowIso))


def _airflowFixtureView(name: str) -> dict[str, Any]:
    fx = _fixture(name)
    return _airflowView(fx["obd-live"], fx["now"])


def _maf(value: Any, **extra: Any) -> dict[str, Any]:
    param = {
        "value": value, "unit": "g/s", "ts": "2026-10-20T15:12:29Z", "stale": False,
        "band": None, "last": None, "noBandReason": "no_band_defined", "scale": {"max": 160.0},
    }
    param.update(extra)
    return {"params": {"MAF": param}, "dataSource": "real", "ts": "2026-10-20T15:12:30Z"}


def _inAirflow(path: list[dict[str, Any]]) -> bool:
    return any("fuel-airflow" in _classes(n) for n in path)


def _airflowPaths(surface: rh.Surface, cls: str) -> list[list[dict[str, Any]]]:
    return [p for p in _fuelPaths(surface, cls) if _inAirflow(p)]


def _bootAirflow(name: str) -> rh.Surface:
    fx = _fixture(name)
    return _boot(system=_driving(), nowIso=fx["now"], obdLive=fx["obd-live"])


def test_airflowFixturesArePresent_andDescribed():
    for name in AIRFLOW_FIXTURES:
        fx = _fixture(name)
        assert fx["description"], name
        assert isinstance(fx["obd-live"], dict), name


def test_syntheticScaleFixture_saysItIsSynthetic():
    """The 150 is made up to prove pinning; it must never read as this car's clip."""
    fx = _fixture("synthetic-scale-150")
    assert fx["obd-live"]["params"]["MAF"]["scale"] == {"max": 150.0}
    assert "SYNTHETIC" in fx["description"]
    assert "not this car's clip" in fx["description"].lower()


def test_wotNearMax_isTheCorpusMaxAgainstTheRealDefault():
    from common.config.validator import DEFAULTS

    maf = _fixture("wot-near-max")["obd-live"]["params"]["MAF"]
    assert maf["value"] == 158.69
    assert maf["scale"] == {"max": float(DEFAULTS["pi.display.scale.mafMaxGs"])}


# US-890-c's fixtures (section 9), declared here so the builder-equality test
# below covers them too.
LOOP_TRIM_FIXTURES = ["closed-loop-trim", "open-loop-trim", "loop-unknown", "trim-stale"]


@pytest.mark.parametrize("name", AIRFLOW_FIXTURES + LOOP_TRIM_FIXTURES)
def test_airflowFixture_obdLiveIsWhatTheBuilderEmits(name: str):
    """
    Given: a fixture's obd-live payload
    When: its readings are fed through a real ObdLiveTracker (its MAF scale max
          as pi.display.scale.mafMaxGs) and built at the payload's ts
    Then: the builder's output equals the payload -- the page is tested against
          the provider's real shape, scale and fuel block included. A status
          label with no python-obd unit name ('CL', 'OL-drive') is fed as itself.
    """
    from pi.obdii import obd_live_emitter as ole
    from pi.obdii import units

    payload = _fixture(name)["obd-live"]
    config: dict[str, Any] = {"pi": {"time": {"localZone": "UTC"}}}
    maf = payload["params"].get("MAF")
    if maf is not None:
        config["pi"]["display"] = {"scale": {"mafMaxGs": maf["scale"]["max"]}}
    pythonObdName = {canonical: raw for raw, canonical in units.CANONICAL_UNITS.items()}
    tracker = ole.ObdLiveTracker(config)
    for pid, param in payload["params"].items():
        value = param["last"]["value"] if param["stale"] else param["value"]
        tracker.observeReading(
            _Reading(pid, value, _naiveUtc(param["ts"]),
                     pythonObdName.get(param["unit"], param["unit"]))
        )
    built = ole.buildObdLiveState(
        tracker.snapshot(),
        nowUtc=_awareUtc(payload["ts"]),
        staleSec=ole.DEFAULT_OBD_LIVE_STALE_S,
        dataSource=payload["dataSource"],
    )
    assert built == payload


class _Reading:
    def __init__(self, parameterName: str, value: Any, timestamp: Any, unit: str) -> None:
        self.parameterName = parameterName
        self.value = value
        self.timestamp = timestamp
        self.unit = unit


def _awareUtc(iso: str) -> Any:
    from datetime import datetime

    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _naiveUtc(iso: str) -> Any:
    return _awareUtc(iso).replace(tzinfo=None)


@_NODE_ONLY
@pytest.mark.parametrize("name", AIRFLOW_FIXTURES)
def test_airflowView_perFixture(name: str):
    text, unit, fill, stale, note = _AIRFLOW_EXPECTED[name]
    view = _airflowFixtureView(name)
    r = view["reading"]
    assert (r["text"], r["unit"], r["stale"], r["note"]) == (text, unit, stale, note)
    if fill is None:
        assert view["bar"]["fill"] is None
    else:
        assert view["bar"]["fill"] == pytest.approx(fill)
    assert view["bar"]["stale"] == (stale and fill is not None)


@_NODE_ONLY
def test_validation_maf16_24_onMax160_reads16_2_andTheBarIsAboutTenPercent():
    view = _airflowView(_maf(16.24))
    assert (view["reading"]["text"], view["reading"]["unit"]) == ("16.2", "g/s")
    assert view["bar"]["fill"] == pytest.approx(10.15)


@_NODE_ONLY
def test_validation_aboveTheMax_barIsExactlyFull_numberUnclamped():
    view = _airflowFixtureView("synthetic-scale-150")
    assert view["bar"]["fill"] == 100
    assert view["reading"]["text"] == "158.7"
    assert view["reading"]["note"] == ""


@_NODE_ONLY
def test_airflow_stepsPerReading_noSmoothing():
    """Two consecutive readings -> two views, each exactly its own sample."""
    a = _airflowView(_maf(16.24))
    b = _airflowView(_maf(42.0))
    assert a["reading"]["text"] == "16.2" and b["reading"]["text"] == "42.0"
    assert b["bar"]["fill"] == pytest.approx(42.0 / 160 * 100)


@_NODE_ONLY
def test_airflow_scaleIsTheProvidersMax_notALiteral():
    """The same reading against two published maxes -> two fills."""
    at160 = _airflowView(_maf(80.0))["bar"]["fill"]
    at200 = _airflowView(_maf(80.0, scale={"max": 200.0}))["bar"]["fill"]
    assert at160 == pytest.approx(50.0)
    assert at200 == pytest.approx(40.0)


@_NODE_ONLY
@pytest.mark.parametrize(
    "scale", [None, {}, {"max": 0}, {"max": -160}, {"max": "160"}, {"max": None}],
    ids=["absent", "no-max", "zero", "negative", "string", "null"],
)
def test_airflow_unusableScale_drawsNoBar_butKeepsTheNumber(scale: Any):
    maf = _maf(16.24)
    if scale is None:
        del maf["params"]["MAF"]["scale"]
    else:
        maf["params"]["MAF"]["scale"] = scale
    view = _airflowView(maf)
    assert view["reading"]["text"] == "16.2"
    assert view["bar"]["fill"] is None


@_NODE_ONLY
def test_airflow_unitNotGramsPerSecond_drawsNoBar():
    """The max is in g/s: a reading in any other unit is not on that scale."""
    view = _airflowView(_maf(16.24, unit="lb/min"))
    assert view["bar"]["fill"] is None


@_NODE_ONLY
def test_airflow_zero_isAnEmptyBar_notNull():
    view = _airflowView(_maf(0.0))
    assert view["reading"]["text"] == "0.0"
    assert view["bar"]["fill"] == 0


@_NODE_ONLY
def test_airflow_noObdLive_isDashDashNoSource():
    view = _airflowView(None)
    assert (view["reading"]["text"], view["reading"]["note"]) == ("--", "no source")
    assert view["bar"]["fill"] is None


@_NODE_ONLY
def test_airflow_staleWithNoLastValue_isDashDashWithTheReason():
    maf = _maf(None, stale=True, noBandReason="stale", last=None)
    r = _airflowView(maf)["reading"]
    assert (r["text"], r["note"], r["noteKind"]) == ("--", "stale", "reason")


@_NODE_ONLY
@pytest.mark.parametrize("name", AIRFLOW_FIXTURES)
def test_dom_airflowPaintsTheView(name: str):
    view = _airflowFixtureView(name)
    r = view["reading"]
    surface = _bootAirflow(name)
    slot = _fuelPaths(surface, "fuel-airflow")
    assert len(slot) == 1
    attrs = slot[0][-1]["attrs"]
    assert attrs.get("data-stale") == ("true" if r["stale"] else "false"), name
    assert attrs.get("data-note") == (r["noteKind"] or "none"), name
    assert _fuelText(surface, "fuel-value")[0] == r["text"], name
    assert [_textOf(p[-1]) for p in _airflowPaths(surface, "fuel-unit")] == [r["unit"]], name
    note = _airflowPaths(surface, "fuel-note")
    assert len(note) == 1
    assert _textOf(note[0][-1]) == r["note"], name
    assert surface.rendered(note[0]) == bool(r["note"]), name
    fill = _airflowPaths(surface, "fuel-bar-fill")
    assert len(fill) == 1
    width = ((fill[0][-1].get("style") or {}).get("width") or "").strip()
    expected = view["bar"]["fill"]
    assert width == f"{expected if expected is not None else 0}%", (name, width)
    bar = _airflowPaths(surface, "fuel-bar")
    assert bar[0][-1]["attrs"].get("data-stale") == ("true" if view["bar"]["stale"] else "false")


@_NODE_ONLY
def test_dom_aboveTheMax_noSensorLimitText_andTheBarIsFull():
    surface = _bootAirflow("synthetic-scale-150")
    text = _textOf(_fuelPaths(surface, "fuel-airflow")[0][-1]).lower()
    assert "sensor limit" not in text
    assert "limit" not in text
    fill = _airflowPaths(surface, "fuel-bar-fill")[0][-1]
    assert (fill.get("style") or {}).get("width") == "100%"
    assert _fuelText(surface, "fuel-value")[0] == "158.7"


_WARN_TOKENS = ("--amber-warn", "--red", "--red-light", "--red-dark", "--alarm")


@_NODE_ONLY
@pytest.mark.parametrize("name", ["synthetic-scale-150", "wot-near-max", "stale"])
def test_dom_nothingOnTheAirflowElementIsAmberOrRed(name: str):
    surface = _bootAirflow(name)
    for cls in ("fuel-airflow", "fuel-label", "fuel-value", "fuel-unit", "fuel-note",
                "fuel-bar", "fuel-bar-fill"):
        paths = _airflowPaths(surface, cls) if cls != "fuel-airflow" else _fuelPaths(surface, cls)
        assert paths, cls
        for path in paths:
            for prop in ("color", "background-color", "border-color"):
                won = surface.winningDeclaration(path, prop)
                if won is not None:
                    assert not any(tok in won[0] for tok in _WARN_TOKENS), (name, cls, prop, won)


def test_css_noAirflowRuleNamesAWarnColour():
    for selector, body in _fuelRules():
        if any(k in selector for k in ("fuel-airflow", "fuel-bar", "fuel-unit", "fuel-line")):
            assert not any(tok in body for tok in _WARN_TOKENS), (selector, body)


def test_css_airflowValueIsFsHero_andTheBarHasNoTransition():
    assert "var(--fs-hero)" in _rule("#fuel-card .fuel-airflow .fuel-value")
    for selector, body in _fuelRules():
        if "fuel-bar" in selector:
            assert "transition" not in body and "animation" not in body, selector


def test_css_staleAirflow_isDimmed():
    assert "opacity" in _rule('#fuel-card .fuel-airflow[data-stale="true"] .fuel-line')
    assert "opacity" in _rule('#fuel-card .fuel-bar[data-stale="true"]')


@_NODE_ONLY
def test_dom_staleAirflow_isDimmed_freshIsNot():
    stale = _bootAirflow("stale")
    line = _airflowPaths(stale, "fuel-line")
    assert stale.winningDeclaration(line[0], "opacity") is not None
    fresh = _bootAirflow("cruise-closed")
    assert fresh.winningDeclaration(_airflowPaths(fresh, "fuel-line")[0], "opacity") is None


def test_theFuelAirflowRenderReadsTheTicksObdLive():
    js = _read(_JS)
    assert re.search(r"renderFuelAirflow\(\s*fuelCard,\s*fuelAirflowView\(\s*await stateOnce\(\"obd-live\"\)", js)
    assert 'document.getElementById("fuel-card")' in js


# The grep gate: no MAF max literal in carousel.js (the scale is the provider's).
_MAF_MAX_LITERAL = re.compile(r"(?<![\w.])(?:160|150|158\.69)(?:\.0+)?(?![\w.])")


def _mafMaxHits(source: str) -> list[str]:
    return _MAF_MAX_LITERAL.findall(_stripJsComments(source))


def test_carouselJs_holdsNoMafMaxLiteral():
    assert _mafMaxHits(_read(_JS)) == []


@pytest.mark.parametrize("planted", ["var MAF_MAX = 160;", "fill = v / 160.0 * 100;"])
def test_mafMaxGate_catchesAPlantedLiteral(planted: str):
    assert _mafMaxHits(_read(_JS) + "\n" + planted + "\n") != []


def test_architectureMd_recordsParamsMafScale():
    arch = _read(_ARCH)
    heading = "#### V0.30 Fuel card AIRFLOW against params.MAF.scale (US-890-b"
    assert heading in arch
    section = arch[arch.index(heading):][:3000]
    assert "pi.display.scale.mafMaxGs" in section
    assert "synthetic-scale-150" in section
    # The obd-live contract names the field too.
    assert "**`params.MAF.scale`** (US-890-b" in arch


# ---------------------------------------------------------------------------
# 9. US-890-c -- LOOP chip + TOTAL TRIM from states/obd-live `fuel` only.
#    specs/v030-fuel-page-design.md s4.2 (Atlas S104 total-trim ruling (b)):
#    the chip reads fuel.loop (CLOSED LOOP / OPEN LOOP / "--"), outlined and
#    never coloured; TOTAL TRIM reads fuel.totalTrimNow, signed, one decimal,
#    "%", unbanded and neutral; a null shows "--" + its reason's text, and
#    only open_loop dims the "--".
# ---------------------------------------------------------------------------

OPEN_LOOP_TEXT = "not applied in open loop"

# Fixture -> (chip text, chip note, trim text, trim note, trim dimmed).
_SIDE_EXPECTED: dict[str, tuple[str, str, str, str, bool]] = {
    "closed-loop-trim": ("CLOSED LOOP", "", "+1.5 %", "", False),
    "open-loop-trim": ("OPEN LOOP", "", "--", OPEN_LOOP_TEXT, True),
    "loop-unknown": ("--", "loop unknown", "--", "loop unknown", False),
    "trim-stale": ("CLOSED LOOP", "", "--", "stale", False),
    # An airflow fixture: no status and no trims read.
    "cruise-closed": ("--", "loop unknown", "--", "not read", False),
}


def _loopView(obdLive: Any) -> dict[str, Any]:
    return _probe("fuelLoopView", obdLive)


def _trimView(obdLive: Any) -> dict[str, Any]:
    return _probe("fuelTotalTrimView", obdLive)


def _withTrim(**trim: Any) -> dict[str, Any]:
    block = {"value": None, "unit": "%", "ts": "2026-10-20T15:12:28Z", "reason": None}
    block.update(trim)
    return {"params": {}, "fuel": {"loop": "closed", "totalTrimNow": block},
            "dataSource": "real", "ts": "2026-10-20T15:12:30Z"}


def _sidePath(surface: rh.Surface, slotCls: str, cls: str) -> list[dict[str, Any]]:
    paths = [p for p in _fuelPaths(surface, cls) if any(slotCls in _classes(n) for n in p)]
    assert len(paths) == 1, (slotCls, cls, len(paths))
    return paths[0]


def test_loopTrimFixturesArePresent_andDescribed():
    for name in LOOP_TRIM_FIXTURES:
        fx = _fixture(name)
        assert fx["description"], name
        assert isinstance(fx["obd-live"]["fuel"], dict), name


@_NODE_ONLY
@pytest.mark.parametrize("name", sorted(_SIDE_EXPECTED))
def test_loopAndTrimViews_perFixture(name: str):
    chip, chipNote, trim, trimNote, dimmed = _SIDE_EXPECTED[name]
    obdLive = _fixture(name)["obd-live"]
    loop = _loopView(obdLive)
    total = _trimView(obdLive)
    assert (loop["text"], loop["note"]) == (chip, chipNote)
    assert (total["text"], total["note"], total["dimmed"]) == (trim, trimNote, dimmed)
    assert loop["dimmed"] is False


@_NODE_ONLY
@pytest.mark.parametrize(
    ("value", "text"),
    [(1.5000000000000002, "+1.5 %"), (1.5, "+1.5 %"), (-1.64, "−1.6 %"),
     (12.0, "+12.0 %"), (0, "+0.0 %"), (-0.04, "+0.0 %"), (-25.0, "−25.0 %")],
)
def test_totalTrim_isSignedOneDecimalPercent(value: float, text: str):
    """toFixed(1), never String(float): 1.5000000000000002 reads '+1.5 %'."""
    assert _trimView(_withTrim(value=value))["text"] == text


@_NODE_ONLY
@pytest.mark.parametrize(
    ("trim", "note"),
    [({"reason": "open_loop"}, OPEN_LOOP_TEXT), ({"reason": "not_read"}, "not read"),
     ({"reason": "loop_unknown"}, "loop unknown"), ({"reason": "stale"}, "stale"),
     ({"reason": "brand_new_code"}, "brand_new_code"), ({"reason": None}, "not read"),
     ({"reason": "stale", "value": 1.5}, "stale")],
    ids=["open-loop", "not-read", "loop-unknown", "stale", "unknown-code-raw",
         "null-value-no-reason", "reason-wins-over-a-value"],
)
def test_totalTrim_null_isDashDashPlusTheReasonText(trim: dict[str, Any], note: str):
    view = _trimView(_withTrim(**trim))
    assert (view["text"], view["note"], view["noteKind"]) == ("--", note, "reason")
    assert view["dimmed"] == (trim["reason"] == "open_loop")


@_NODE_ONLY
def test_totalTrim_stale_hasNoAgeAndNoLastValue():
    view = _trimView(_withTrim(reason="stale", value=None))
    assert (view["text"], view["note"]) == ("--", "stale")
    assert set(view) == {"text", "note", "noteKind", "dimmed"}


@_NODE_ONLY
@pytest.mark.parametrize(
    ("obdLive", "note"),
    [(None, "no source"),
     ({"params": {}, "dataSource": "real", "ts": "2026-10-20T15:12:30Z"}, "not published")],
    ids=["no-obd-live", "provider-without-fuel-block"],
)
def test_noFuelBlock_bothSlotsSayWhy(obdLive: Any, note: str):
    for view in (_loopView(obdLive), _trimView(obdLive)):
        assert (view["text"], view["note"]) == ("--", note)


@_NODE_ONLY
@pytest.mark.parametrize("loop", [None, "half-open", 2, True])
def test_chip_unknownLoopValue_isDashDash_neverAGuess(loop: Any):
    obdLive = _withTrim()
    obdLive["fuel"]["loop"] = loop
    view = _loopView(obdLive)
    assert (view["text"], view["note"]) == ("--", "loop unknown")


@_NODE_ONLY
@pytest.mark.parametrize("name", LOOP_TRIM_FIXTURES)
def test_dom_loopAndTrimPaintTheViews(name: str):
    chip, chipNote, trim, trimNote, dimmed = _SIDE_EXPECTED[name]
    fx = _fixture(name)
    surface = _boot(system=_driving(), nowIso=fx["now"], obdLive=fx["obd-live"])
    assert _textOf(_sidePath(surface, "fuel-loop", "fuel-value")[-1]) == chip
    assert _textOf(_sidePath(surface, "fuel-total-trim", "fuel-value")[-1]) == trim
    for slotCls, note in (("fuel-loop", chipNote), ("fuel-total-trim", trimNote)):
        notePath = _sidePath(surface, slotCls, "fuel-note")
        assert _textOf(notePath[-1]) == note, (name, slotCls)
        assert surface.rendered(notePath) == bool(note), (name, slotCls)
    slot = _sidePath(surface, "fuel-total-trim", "fuel-value")[-2]
    assert slot["attrs"].get("data-dimmed") == ("true" if dimmed else "false")


@_NODE_ONLY
def test_dom_openLoop_dimsTheTrimDashDash_closedAndStaleDoNot():
    def opacity(name: str) -> Any:
        fx = _fixture(name)
        surface = _boot(system=_driving(), nowIso=fx["now"], obdLive=fx["obd-live"])
        return surface.winningDeclaration(
            _sidePath(surface, "fuel-total-trim", "fuel-value"), "opacity"
        )

    assert opacity("open-loop-trim") is not None
    assert opacity("closed-loop-trim") is None
    assert opacity("trim-stale") is None


@_NODE_ONLY
@pytest.mark.parametrize("name", ["open-loop-trim", "closed-loop-trim"])
def test_dom_chipAndTrim_neverColoured(name: str):
    fx = _fixture(name)
    surface = _boot(system=_driving(), nowIso=fx["now"], obdLive=fx["obd-live"])
    for slotCls in ("fuel-loop", "fuel-total-trim"):
        for cls in ("fuel-value", "fuel-note", "fuel-label"):
            path = _sidePath(surface, slotCls, cls)
            for prop in ("color", "background-color", "border-color"):
                won = surface.winningDeclaration(path, prop)
                if won is not None:
                    assert not any(tok in won[0] for tok in _WARN_TOKENS), (name, cls, won)
                    assert "--accent" not in won[0], (name, cls, won)


def test_css_chipIsOutlinedAtFsLabel_noColourRule():
    body = _rule("#fuel-card .fuel-chip")
    assert _decl(body, "font-size") == "var(--fs-label)"
    assert _decl(body, "border-style") == "solid"
    assert _decl(body, "white-space") == "nowrap"
    for selector, ruleBody in _fuelRules():
        if any(k in selector for k in ("fuel-chip", "fuel-loop", "fuel-total-trim")):
            assert "data-loop" not in selector, selector
            assert not any(tok in ruleBody for tok in _WARN_TOKENS), (selector, ruleBody)


def test_css_totalTrimIsFsPrimary_andOnlyOpenLoopDims():
    assert _decl(_rule("#fuel-card .fuel-value"), "font-size") == "var(--fs-primary)"
    for selector, body in _fuelRules():
        if "fuel-total-trim" in selector:
            assert _decl(body, "font-size") is None, selector
            if _decl(body, "opacity") is not None:
                assert selector == '#fuel-card .fuel-total-trim[data-dimmed="true"] .fuel-value'


# The fit rule: "not applied in open loop" (24 chars) fits its tile. The harness
# resolves the cascade, not layout, so the width is modelled from the sheet:
# the side column is as wide as its widest line (the notes never wrap), and it
# must fit beside the airflow reading's widest line inside the card body.
def _fuelPx(value: str) -> float:
    var = re.fullmatch(r"var\((--fuel-[\w-]+)\)", value.strip())
    if var:
        scoped = dict(re.findall(r"(--fuel-[\w-]+)\s*:\s*([^;]+);", _rule("#fuel-card")))
        return _fuelPx(scoped[var.group(1)].strip())
    return _px(value)


def _sideColumnWidth(trimNote: str, trimText: str = "−25.0 %") -> float:
    chipBody = _rule("#fuel-card .fuel-chip")
    chip = (
        _monoWidth("CLOSED LOOP", "var(--fs-label)")
        + 2 * _fuelPx("var(--fuel-chip-pad-x)")
        + 2 * _fuelPx(_decl(chipBody, "border-width") or "")
    )
    return max(
        chip,
        _monoWidth("TOTAL TRIM", "var(--fs-meta)"),
        _monoWidth(trimText, "var(--fs-primary)"),
        _monoWidth(trimNote, "var(--fs-meta)"),
        _monoWidth("loop unknown", "var(--fs-meta)"),
    )


def _airflowWidth() -> float:
    return max(
        _monoWidth("AIRFLOW", "var(--fs-meta)"),
        _monoWidth("158.7", "var(--fs-hero)") + _fuelPx("var(--fuel-unit-gap)")
        + _monoWidth("g/s", "var(--fs-label)"),
        _monoWidth("no source", "var(--fs-meta)"),
    )


def _sideFits(trimNote: str) -> bool:
    available = _bodyWidthPx() - _fuelPx("var(--fuel-col-gap)") - _airflowWidth()
    return _sideColumnWidth(trimNote) <= available


def test_openLoopText_is24Chars_andFitsItsTile():
    assert len(OPEN_LOOP_TEXT) == 24
    assert _sideFits(OPEN_LOOP_TEXT)


def test_sideFitModel_failsAPlantedOverflow():
    assert not _sideFits(OPEN_LOOP_TEXT * 3)


def test_css_sideNotesNeverWrap():
    for selector in ("#fuel-card .fuel-loop .fuel-note", "#fuel-card .fuel-total-trim .fuel-note"):
        assert _decl(_rule(selector), "white-space") == "nowrap", selector


# The grep gate (Atlas ruling AC 3/4): the page reads only obd-live.fuel -- no
# trim PID, no status PID, no trim addition, never ltft-trend.totalTrim.
_FORBIDDEN_NAMES = re.compile(
    r"\b(?:LONG_FUEL_TRIM_1|SHORT_FUEL_TRIM_1|FUEL_SYSTEM_STATUS)\b|\btotalTrim\b(?!Now)"
)
_TRIM_ADDITION = re.compile(
    r"\b(?:ltft|stft)\w*(?:\.\w+)*\s*\+(?!\+)|(?<!\+)\+\s*[\w.]*\b(?:ltft|stft)\w*", re.I
)


def _fuelSourceHits(source: str) -> list[str]:
    code = _stripJsComments(source)
    return _FORBIDDEN_NAMES.findall(code) + _TRIM_ADDITION.findall(code)


def test_carouselJs_readsOnlyTheFuelBlock():
    assert _fuelSourceHits(_read(_JS)) == []


@pytest.mark.parametrize(
    "planted",
    ["var s = p.LONG_FUEL_TRIM_1.value;", "if (code === p.FUEL_SYSTEM_STATUS) {}",
     "var t = trend.totalTrim;", "var sum = ltft.value + stft.value;", "var x = a + stftValue;"],
)
def test_fuelSourceGate_catchesAPlantedRead(planted: str):
    assert _fuelSourceHits(_read(_JS) + "\n" + planted + "\n") != []


def test_theLoopAndTrimRenderReadsTheTicksObdLive():
    js = _read(_JS)
    assert re.search(r"fuelLoopView\(\s*await stateOnce\(\"obd-live\"\)\s*\)", js)
    assert re.search(r"fuelTotalTrimView\(\s*await stateOnce\(\"obd-live\"\)\s*\)", js)


def test_architectureMd_recordsTheFuelBlockAndTheSharedCodeSet():
    arch = _read(_ARCH)
    heading = "#### V0.30 Fuel card LOOP + TOTAL TRIM from obd-live.fuel (US-890-c"
    assert heading in arch
    section = arch[arch.index(heading):][:3500]
    for needle in ("totalTrimNow", "CLOSED_LOOP_FUEL_STATUS_CODES", "pi/obdii/fuel_status.py",
                   "not applied in open loop", "loop_unknown"):
        assert needle in section, needle
    assert "**`fuel`** (US-890-c" in arch


# ---------------------------------------------------------------------------
# 10. US-890-d -- the MPG row: THIS DRIVE and SINCE RESET from states/fuel-
#     economy, every null with its s4.6 reason. specs/v030-fuel-page-design.md
#     s4.3/s4.6: every figure carries the approximately sign, one decimal; the
#     approximate flag reads "open loop" (--amber-warn, --fs-meta); LAST 30 S
#     is "--" + "not published" until its provider field lands (US-890-e).
# ---------------------------------------------------------------------------

MPG_FIXTURES = ["mpg-null-reasons", "sinceReset-never", "last30-not-published", "mpg-last30"]

# s4.6, the code -> text table (the spec's, verbatim; US-890-e adds recent's
# too_few_samples).
MPG_REASON_TEXT = {
    "maf_untrusted": "MAF not fitted",
    "maf_stale": "no MAF reading",
    "maf_zero_running": "MAF reads zero",
    "gaps": "too many gaps",
    "too_short": "too short yet",
    "no_fuel": "no fuel counted",
    "too_few_samples": "too few samples",
}
OPEN_LOOP_FLAG = "open loop"
# Every other text the row can show (s4.3 + this story's never-blank fallbacks).
MPG_OTHER_TEXTS = ["not started", "never reset", "no source", NOT_PUBLISHED, "no reason sent"]
MPG_ROW_FIT_CHARS = 16


def _mpgView(payload: Any) -> dict[str, Any]:
    return _probe("fuelMpgView", payload)


def _slot(view: dict[str, Any], key: str) -> tuple[str, str]:
    return (view[key]["text"], view[key]["note"])


def _fuelEconomy(thisDrive: Any = None, sinceReset: Any = None) -> dict[str, Any]:
    return {"thisDrive": thisDrive, "sinceReset": sinceReset, "ts": "2026-10-20T15:03:09Z"}


def _drive(**fields: Any) -> dict[str, Any]:
    block = {"fuelL": 1.9, "mpg": None, "sinceTs": "2026-10-20T15:00:00Z",
             "approximate": False, "openLoopAirPct": 4.1, "mpgNullReason": "too_short"}
    block.update(fields)
    return block


def _resetRow(mpg: Any) -> dict[str, Any]:
    return {"fuelL": 39.39, "distanceKm": 412.0, "mpg": mpg, "resetAtTs": "2026-10-01T12:00:00Z"}


def _mpgCases() -> list[tuple[str, dict[str, Any]]]:
    """Every (case id, case) across this story's fixtures."""
    out = []
    for name in MPG_FIXTURES:
        fx = _fixture(name)
        if "cases" in fx:
            out += [(f"{name}:{code}", case) for code, case in fx["cases"].items()]
        else:
            out.append((name, fx))
    return out


def _buildFuelEconomy(inputs: dict[str, Any], nowIso: str) -> dict[str, Any]:
    """The real builder over a fixture's recorded inputs.

    US-890-e: ``inputs.recent`` is the RecentWindow's sums ``{airG, km,
    mafSamples}``; ``recentPublished: false`` records a provider from before
    the field existed, so the stored payload has no ``recent`` key.
    US-923: ``inputs.resetAllowed`` is the orchestrator's gate verdict
    ``{value, reason}``; absent, the payload has no ``resetAllowed`` key.
    """
    from dataclasses import replace

    from common.config.validator import DEFAULTS
    from pi.obdii import fuel_economy_emitter as fee

    settings = replace(fee.FuelSettings.fromConfig({}), mafTrusted=inputs["mafTrusted"])
    snapIn = inputs["snap"]
    if snapIn is None:
        snap = fee.FuelSnapshot(started=False, airG=0.0, openLoopAirG=0.0, excludedS=0.0,
                                windowS=0.0, lastMafGPerS=None, lastMafEventUtc=None,
                                lastMafEngineRunning=None)
    else:
        event = snapIn["lastMafEventUtc"]
        snap = fee.FuelSnapshot(**{**snapIn, "lastMafEventUtc": _awareUtc(event) if event else None})
    recentIn = inputs.get("recent")
    payload = fee.buildFuelEconomyState(
        snap, settings, distanceKm=inputs["distanceKm"],
        distanceSinceTs=inputs["distanceSinceTs"], nowUtc=_awareUtc(nowIso),
        staleSec=float(DEFAULTS["pi.display.stale.obdLiveSec"]), sinceReset=inputs["sinceReset"],
        recent=None if recentIn is None else fee.RecentSnapshot(**recentIn),
        resetAllowed=inputs.get("resetAllowed"),
    )
    if inputs.get("recentPublished") is False:
        del payload["recent"]
    return payload


def _mpgSlotPath(surface: rh.Surface, slotCls: str, cls: str) -> list[dict[str, Any]]:
    paths = [p for p in _fuelPaths(surface, cls) if any(slotCls in _classes(n) for n in p)]
    assert len(paths) == 1, (slotCls, cls, len(paths))
    return paths[0]


def _mpgColumnWidth() -> float:
    """One of the row's three equal grid columns (repeat(3, 1fr))."""
    assert _decl(_rule("#fuel-card .fuel-mpg"), "grid-template-columns") == "repeat(3, 1fr)"
    return (_bodyWidthPx() - 2 * _fuelPx("var(--fuel-col-gap)")) / 3


def _mpgTextFits(text: str) -> bool:
    return _monoWidth(text, "var(--fs-meta)") <= _mpgColumnWidth()


def test_mpgFixturesArePresent_andDescribed():
    for name in MPG_FIXTURES:
        assert _fixture(name)["description"], name


def test_mpgNullReasons_hasOneCasePerProviderCode():
    from pi.obdii.fuel_economy_emitter import MPG_NULL_REASONS, RECENT_NULL_REASONS

    cases = _fixture("mpg-null-reasons")["cases"]
    assert sorted(cases) == sorted(MPG_NULL_REASONS)
    # US-890-e pin change: the ONE table covers thisDrive's and recent's codes.
    assert sorted(MPG_REASON_TEXT) == sorted(set(MPG_NULL_REASONS) | set(RECENT_NULL_REASONS))
    for code, case in cases.items():
        assert case["fuel-economy"]["thisDrive"]["mpgNullReason"] == code


@pytest.mark.parametrize("caseId", [cid for cid, _c in _mpgCases()])
def test_mpgFixture_isWhatTheBuilderEmits(caseId: str):
    """
    Given: a fixture case's recorded inputs (snapshot, distance, since-reset row)
    When: they are built by the real buildFuelEconomyState at the fixture's now
    Then: the output equals the stored payload -- the page is tested against the
          provider's real shape and reason codes, not a hand-typed one.
    """
    case = dict(_mpgCases())[caseId]
    now = _fixture(caseId.split(":")[0])["now"]
    assert _buildFuelEconomy(case["inputs"], now) == case["fuel-economy"]


def test_last30Fixture_hasNoRecentField_andRealFigures():
    payload = _fixture("last30-not-published")["fuel-economy"]
    assert "recent" not in payload
    assert payload["thisDrive"]["mpg"] is not None and payload["sinceReset"]["mpg"] is not None


@_NODE_ONLY
# US-890-e: thisDrive's codes (pinned == MPG_NULL_REASONS above), not the whole
# table -- too_few_samples is recent's only (section 11).
@pytest.mark.parametrize("code", sorted(_fixture("mpg-null-reasons")["cases"]))
def test_thisDrive_nullMpg_showsTheS46Text(code: str):
    view = _mpgView(_fixture("mpg-null-reasons")["cases"][code]["fuel-economy"])
    assert _slot(view, "thisDrive") == ("--", MPG_REASON_TEXT[code])
    assert view["thisDrive"]["noteKind"] == "reason"
    assert _slot(view, "sinceReset") == ("--", "never reset")


@_NODE_ONLY
def test_validation_tooShort_isDashDashTooShortYet():
    view = _mpgView(_fuelEconomy(thisDrive=_drive(mpgNullReason="too_short")))
    assert _slot(view, "thisDrive") == ("--", "too short yet")


@_NODE_ONLY
@pytest.mark.parametrize("code", ["zzz_new", "a_much_longer_future_code"])
def test_validation_unknownCode_showsTheRawCode_neverBlank(code: str):
    view = _mpgView(_fuelEconomy(thisDrive=_drive(mpgNullReason=code)))
    assert _slot(view, "thisDrive") == ("--", code)


@_NODE_ONLY
@pytest.mark.parametrize("code", [None, "", "absent"], ids=["null-code", "empty-code", "no-code-key"])
def test_thisDrive_nullMpgWithNoCode_stillSaysWhy(code: Any):
    drive = _drive(mpgNullReason=code)
    if code == "absent":
        del drive["mpgNullReason"]
    view = _mpgView(_fuelEconomy(thisDrive=drive))
    assert _slot(view, "thisDrive") == ("--", "no reason sent")


@_NODE_ONLY
def test_example_tooShortDrive_andNeverReset():
    """The story's example payload, then the sinceReset-never fixture."""
    view = _mpgView(_fuelEconomy(thisDrive=_drive(), sinceReset=None))
    assert _slot(view, "thisDrive") == ("--", "too short yet")
    assert _slot(view, "sinceReset") == ("--", "never reset")
    never = _mpgView(_fixture("sinceReset-never")["fuel-economy"])
    assert _slot(never, "thisDrive") == ("--", "not started")
    assert _slot(never, "sinceReset") == ("--", "never reset")


@_NODE_ONLY
def test_sinceReset_nullMpg_isTooShortYet_withNoGuessAtTheCause():
    view = _mpgView(_fuelEconomy(sinceReset=_resetRow(None)))
    assert _slot(view, "sinceReset") == ("--", "too short yet")


@_NODE_ONLY
@pytest.mark.parametrize(
    ("mpg", "text"),
    [(26.301, "≈26.3"), (24.6, "≈24.6"), (42.64440395833332, "≈42.6"), (99.96, "≈100.0"),
     (7, "≈7.0"), (0.04, "≈0.0")],
)
def test_figures_carryTheApproxSign_withOneDecimal(mpg: float, text: str):
    view = _mpgView(_fuelEconomy(thisDrive=_drive(mpg=mpg), sinceReset=_resetRow(mpg)))
    assert _slot(view, "thisDrive") == (text, "")
    assert _slot(view, "sinceReset") == (text, "")
    assert view["thisDrive"]["noteKind"] == view["sinceReset"]["noteKind"] == "none"


@_NODE_ONLY
@pytest.mark.parametrize("mpg", ["26.3", True, [26.3], {"v": 1}])
def test_aNonNumberMpg_isNeverShownAsAFigure(mpg: Any):
    view = _mpgView(_fuelEconomy(thisDrive=_drive(mpg=mpg), sinceReset=_resetRow(mpg)))
    assert view["thisDrive"]["text"] == view["sinceReset"]["text"] == "--"
    assert view["thisDrive"]["note"] and view["sinceReset"]["note"]


@_NODE_ONLY
def test_lastThirty_fixture_rendersFiguresAndNotPublished():
    view = _mpgView(_fixture("last30-not-published")["fuel-economy"])
    assert _slot(view, "last30") == ("--", NOT_PUBLISHED)
    assert _slot(view, "thisDrive") == ("≈26.3", "")
    assert _slot(view, "sinceReset") == ("≈24.6", "")
    assert view["thisDrive"]["flag"] == ""


@_NODE_ONLY
@pytest.mark.parametrize(
    ("payload", "thisDrive", "sinceReset"),
    [(None, "no source", "no source"), ([], "no source", "no source"),
     ({"ts": None}, NOT_PUBLISHED, NOT_PUBLISHED),
     (_fuelEconomy(thisDrive=5, sinceReset="x"), NOT_PUBLISHED, NOT_PUBLISHED)],
    ids=["no-file", "not-an-object", "blocks-absent", "blocks-malformed"],
)
def test_noOrBrokenPayload_saysWhy_andLast30StaysNotPublished(
    payload: Any, thisDrive: str, sinceReset: str
):
    view = _mpgView(payload)
    assert _slot(view, "last30") == ("--", NOT_PUBLISHED)
    assert _slot(view, "thisDrive") == ("--", thisDrive)
    assert _slot(view, "sinceReset") == ("--", sinceReset)


@_NODE_ONLY
def test_validation_approximate_flagsOpenLoopBesideTheFigure():
    view = _mpgView(_fuelEconomy(thisDrive=_drive(mpg=31.2, approximate=True)))
    assert view["thisDrive"]["text"] == "≈31.2"
    assert view["thisDrive"]["flag"] == OPEN_LOOP_FLAG
    assert view["sinceReset"]["flag"] == view["last30"]["flag"] == ""


@_NODE_ONLY
@pytest.mark.parametrize(
    "drive", [_drive(mpg=31.2, approximate=False), _drive(mpg=31.2, approximate="yes"),
              _drive(mpg=None, approximate=True)],
    ids=["closed-loop", "truthy-not-true", "no-figure"],
)
def test_noFlag_unlessApproximateIsTrueAndAFigureShows(drive: dict[str, Any]):
    assert _mpgView(_fuelEconomy(thisDrive=drive))["thisDrive"]["flag"] == ""


@_NODE_ONLY
@pytest.mark.parametrize("caseId", [cid for cid, _c in _mpgCases()])
def test_dom_mpgRowPaintsTheView(caseId: str):
    payload = dict(_mpgCases())[caseId]["fuel-economy"]
    view = _mpgView(payload)
    surface = _boot(system=_driving(), fuelEconomy=payload)
    for slotCls, key in (("fuel-mpg-last30", "last30"), ("fuel-mpg-this-drive", "thisDrive"),
                         ("fuel-mpg-since-reset", "sinceReset")):
        assert _textOf(_mpgSlotPath(surface, slotCls, "fuel-value")[-1]) == view[key]["text"]
        notePath = _mpgSlotPath(surface, slotCls, "fuel-note")
        assert _textOf(notePath[-1]) == view[key]["note"], slotCls
        assert surface.rendered(notePath) == bool(view[key]["note"]), slotCls
    assert not surface.rendered(_mpgSlotPath(surface, "fuel-mpg-this-drive", "fuel-flag"))


@_NODE_ONLY
def test_dom_approximate_paintsAnAmberMetaOpenLoopFlag():
    payload = _fuelEconomy(thisDrive=_drive(mpg=31.2, approximate=True))
    surface = _boot(system=_driving(), fuelEconomy=payload)
    flag = _mpgSlotPath(surface, "fuel-mpg-this-drive", "fuel-flag")
    assert surface.rendered(flag)
    assert _textOf(flag[-1]) == OPEN_LOOP_FLAG
    assert surface.winningDeclaration(flag, "color")[0] == "var(--amber-warn)"
    assert surface.winningDeclaration(flag, "font-size")[0] == "var(--fs-meta)"
    assert _textOf(_mpgSlotPath(surface, "fuel-mpg-this-drive", "fuel-value")[-1]) == "≈31.2"
    assert not surface.rendered(_mpgSlotPath(surface, "fuel-mpg-this-drive", "fuel-note"))


@_NODE_ONLY
def test_dom_valueTiers_last30Primary_driveAndResetSecondary():
    surface = _boot(system=_driving(), fuelEconomy=_fixture("last30-not-published")["fuel-economy"])
    for slotCls, tier in (("fuel-mpg-last30", "--fs-primary"),
                          ("fuel-mpg-this-drive", "--fs-secondary"),
                          ("fuel-mpg-since-reset", "--fs-secondary")):
        won = surface.winningDeclaration(_mpgSlotPath(surface, slotCls, "fuel-value"), "font-size")
        assert won[0] == f"var({tier})", slotCls
    assert _px("var(--fs-primary)") >= 34


def test_css_mpgLabels_areMichromaAtFsMeta_letterSpacingZero():
    body = _rule("#fuel-card .fuel-mpg .fuel-label")
    assert _decl(body, "font-family") == "var(--font-display)"
    assert _decl(body, "font-weight") == "400"
    assert _decl(body, "font-synthesis") == "none"
    assert _decl(body, "letter-spacing") == "0"
    assert _decl(body, "font-size") is None
    assert _decl(_rule("#fuel-card .fuel-label"), "font-size") == "var(--fs-meta)"


def test_css_openLoopFlag_isAmberWarnAtFsMeta_andTheOnlyAmberInTheMpgRow():
    body = _rule("#fuel-card .fuel-flag")
    assert _decl(body, "color") == "var(--amber-warn)"
    assert _decl(body, "font-size") == "var(--fs-meta)"
    for selector, ruleBody in _fuelRules():
        if "fuel-mpg" in selector:
            assert not any(tok in ruleBody for tok in _WARN_TOKENS), (selector, ruleBody)


def test_css_mpgNotes_wrapRatherThanOverflow():
    assert _decl(_rule("#fuel-card .fuel-mpg .fuel-note"), "overflow-wrap") == "anywhere"


# The fit rule (acceptance 5: no reason text is wider than its MPG column). The
# harness resolves the cascade, not layout, so scrollWidth <= clientWidth is
# modelled from the sheet: a third of the card body less the two column gaps,
# against each text's width in the fixed-width face at --fs-meta.
@pytest.mark.parametrize(
    "text", list(MPG_REASON_TEXT.values()) + MPG_OTHER_TEXTS + [OPEN_LOOP_FLAG]
)
def test_everyMpgRowText_isAtMost16Chars_andFitsItsColumn(text: str):
    assert len(text) <= MPG_ROW_FIT_CHARS, text
    assert _mpgTextFits(text), (text, _monoWidth(text, "var(--fs-meta)"), _mpgColumnWidth())


def test_mpgFitModel_failsAPlantedOverflow():
    assert not _mpgTextFits("x" * (MPG_ROW_FIT_CHARS + 1))


def test_mpgLabels_andTheWidestFigure_fitTheirColumn():
    from tests.ui.test_topbar_three_column_grid import michromaWidthPx

    for label in ("LAST 30 S", "THIS DRIVE", "SINCE RESET"):
        assert michromaWidthPx(label, _px("var(--fs-meta)")) <= _mpgColumnWidth(), label
    assert _monoWidth("≈999.9", "var(--fs-secondary)") <= _mpgColumnWidth()


def test_mpgReasonTable_livesOnceInCarouselJs():
    code = _stripJsComments(_read(_JS))
    for codeName, text in MPG_REASON_TEXT.items():
        assert code.count(f'"{text}"') == 1, text
        assert f"{codeName}: \"{text}\"" in code, codeName


def test_richOverstated_appearsNowhere():
    for path in (_JS, _HTML, _CSS):
        assert "rich, overstated" not in _read(path).lower(), path


# The grep gate (spec s4.3, Atlas S104 ruling 2): the page never divides by a
# MAF value -- MPG is the provider's.
_MAF_DIVIDE = re.compile(r"/\s*\(?\s*[\w.\[\]\"']*maf", re.I)


def _mafDivideHits(source: str) -> list[str]:
    return _MAF_DIVIDE.findall(_stripJsComments(source))


def test_carouselJs_neverDividesByMaf():
    assert _mafDivideHits(_read(_JS)) == []


@pytest.mark.parametrize(
    "planted",
    ["var m = miles / mafGs;", "var m = d / (params.MAF.value * k);", 'var m = d / p["MAF"].value;'],
)
def test_mafDivideGate_catchesAPlantedDivision(planted: str):
    assert _mafDivideHits(_read(_JS) + "\n" + planted + "\n") != []


def test_theMpgRenderReadsTheTicksFuelEconomy():
    assert re.search(r"fuelMpgView\(\s*await stateOnce\(\"fuel-economy\"\)\s*\)", _read(_JS))


# ---------------------------------------------------------------------------
# 11. US-890-e -- LAST 30 S from states/fuel-economy.recent: the provider's
#     ratio of sums over pi.fuel.recentWindowSec. An integer, "99+" at >= 99
#     (Spool 2026-10-14); recent absent -> "not published"; recent null -> "not
#     started" (Iris G-5); a null mpg -> "--" + its s4.6 text.
# ---------------------------------------------------------------------------

_FUEL_ECONOMY_R29 = os.path.join(os.path.dirname(__file__), "fixtures", "states", "fuel-economy.json")

# The mpg-last30 fixture's cases and the LAST 30 S slot each must read.
LAST30_CASES = {
    "cruise": ("27", ""),
    "coast-99plus": ("99+", ""),
    "not-started": ("--", "not started"),
    "too_few_samples": ("--", "too few samples"),
    "too_short": ("--", "too short yet"),
    "maf_stale": ("--", "no MAF reading"),
}


def _withRecent(recent: Any) -> dict[str, Any]:
    payload = _fuelEconomy(thisDrive=_drive())
    payload["recent"] = recent
    return payload


def _recent(**fields: Any) -> dict[str, Any]:
    block = {"mpg": 27.0, "windowSec": 30, "mafSamples": 13}
    block.update(fields)
    return block


def test_mpgLast30Fixture_holdsEveryLast30State():
    assert sorted(_fixture("mpg-last30")["cases"]) == sorted(LAST30_CASES)


@_NODE_ONLY
@pytest.mark.parametrize("case", sorted(LAST30_CASES))
def test_last30_fixtureCase_readsItsSlot(case: str):
    view = _mpgView(_fixture("mpg-last30")["cases"][case]["fuel-economy"])
    assert _slot(view, "last30") == LAST30_CASES[case]
    assert view["last30"]["flag"] == ""


@_NODE_ONLY
def test_validation_recentMpg104p2_reads99Plus():
    view = _mpgView(_withRecent(_recent(mpg=104.2)))
    assert _slot(view, "last30") == ("99+", "")
    assert view["last30"]["noteKind"] == "none"


@_NODE_ONLY
def test_validation_recentNull_readsDashDashNotStarted():
    view = _mpgView(_withRecent(None))
    assert _slot(view, "last30") == ("--", "not started")
    assert view["last30"]["noteKind"] == "reason"


@_NODE_ONLY
@pytest.mark.parametrize(
    ("mpg", "text"),
    [(27.0, "27"), (27.4, "27"), (27.5, "28"), (0.3, "0"), (98.4, "98"), (99, "99+"),
     (99.0, "99+"), (250.7, "99+")],
)
def test_last30_isAnInteger_cappedAt99Plus_withNoApproxSign(mpg: float, text: str):
    assert _slot(_mpgView(_withRecent(_recent(mpg=mpg))), "last30") == (text, "")


@_NODE_ONLY
@pytest.mark.parametrize(
    "code", ["maf_untrusted", "maf_stale", "maf_zero_running", "too_few_samples", "too_short",
             "no_fuel"],
)
def test_last30_nullMpg_showsTheS46Text(code: str):
    view = _mpgView(_withRecent(_recent(mpg=None, mpgNullReason=code)))
    assert _slot(view, "last30") == ("--", MPG_REASON_TEXT[code])


@_NODE_ONLY
@pytest.mark.parametrize(
    ("fields", "note"),
    [({"mpgNullReason": "zzz_new"}, "zzz_new"), ({}, "no reason sent"),
     ({"mpgNullReason": None}, "no reason sent")],
    ids=["unknown-code", "no-code-key", "null-code"],
)
def test_last30_nullMpg_unknownOrMissingCode_neverBlank(fields: dict[str, Any], note: str):
    view = _mpgView(_withRecent(_recent(mpg=None, **fields)))
    assert _slot(view, "last30") == ("--", note)


@_NODE_ONLY
@pytest.mark.parametrize("recent", [5, "27", [27], True], ids=["number", "string", "list", "bool"])
def test_last30_malformedRecent_isNotPublished(recent: Any):
    assert _slot(_mpgView(_withRecent(recent)), "last30") == ("--", NOT_PUBLISHED)


@_NODE_ONLY
@pytest.mark.parametrize("mpg", ["27", True, [27], {"v": 1}])
def test_last30_aNonNumberMpg_isNeverShownAsAFigure(mpg: Any):
    view = _mpgView(_withRecent(_recent(mpg=mpg)))
    assert view["last30"]["text"] == "--"
    assert view["last30"]["note"]


@_NODE_ONLY
@pytest.mark.parametrize(
    ("case", "slot"),
    [("driving", ("43", "")), ("recent-crawl", ("--", "too short yet")),
     ("maf-untrusted", ("--", "MAF not fitted"))],
)
def test_last30_readsTheProvidersR29Fixture(case: str, slot: tuple[str, str]):
    """The page against states/fuel-economy.json, which the provider's own test
    rebuilds through the real integrators and builder."""
    with open(_FUEL_ECONOMY_R29, encoding="utf-8") as fh:
        payload = json.load(fh)[case]
    assert _slot(_mpgView(payload), "last30") == slot


@_NODE_ONLY
def test_dom_last30_paintsTheFigureAtFsPrimary():
    payload = _fixture("mpg-last30")["cases"]["cruise"]["fuel-economy"]
    surface = _boot(system=_driving(), fuelEconomy=payload)
    value = _mpgSlotPath(surface, "fuel-mpg-last30", "fuel-value")
    assert _textOf(value[-1]) == "27"
    assert surface.winningDeclaration(value, "font-size")[0] == "var(--fs-primary)"
    assert not surface.rendered(_mpgSlotPath(surface, "fuel-mpg-last30", "fuel-note"))


def test_last30CapText_fitsItsColumn():
    assert _monoWidth("99+", "var(--fs-primary)") <= _mpgColumnWidth()


def test_architectureMd_recordsTheRecentWindowContract():
    arch = _read(_ARCH)
    heading = "**`recent` -- MPG over the last `pi.fuel.recentWindowSec` (US-890-e"
    assert heading in arch
    section = arch[arch.index(heading):][:3000]
    for needle in ("RecentWindow", "ratio of sums", "too_few_samples", "recentMinMafSamples",
                   "recentMinMiles", "never held together", "99+", "not started"):
        assert needle in section, needle


# ---------------------------------------------------------------------------
# US-922 -- the MPG unit (specs/v030-fuel-page-design.md s4.3 :71-77, AC 5a).
#     Every MPG figure is followed by "MPG" in a .fuel-unit, the airflow g/s
#     pattern (.fuel-line > .fuel-value + .fuel-unit, --fuel-unit-gap 4 px). A
#     "--" never carries it; "99+" does. The figure text itself is unchanged.
# ---------------------------------------------------------------------------

MPG_UNIT = "MPG"  # spec s4.3 :71, "Every MPG figure is followed by MPG"
_MPG_SLOTS = (("fuel-mpg-last30", "last30"), ("fuel-mpg-this-drive", "thisDrive"),
              ("fuel-mpg-since-reset", "sinceReset"))
# The fit column (spec s4.3 :74): 141.33 px, "136 px when the body's scrollbar
# shows, which is the case to design for" -- the classic 16 px scrollbar out of
# the body, then a third less the two column gaps: (448 - 16 - 24) / 3 = 136.
_BODY_SCROLLBAR_PX = 16
_MPG_SCROLLBAR_COLUMN_PX = 136


def _resetView(payload: Any, phase: str) -> dict[str, Any]:
    state = {"phase": phase, "outcome": None, "baselineTs": None, "resetAtTs": None,
             "confirmFromMs": None}
    return _probe("fuelMpgResetView", payload, state, 30)


def _mpgFigureWithUnitWidth(figure: str, sizeVar: str) -> float:
    """figure + gap + "MPG", as _airflowWidth models the g/s line."""
    return (_monoWidth(figure, sizeVar) + _fuelPx("var(--fuel-unit-gap)")
            + _monoWidth(MPG_UNIT, "var(--fs-label)"))


def _mpgScrollbarColumnWidth() -> float:
    return (_bodyWidthPx() - _BODY_SCROLLBAR_PX - 2 * _fuelPx("var(--fuel-col-gap)")) / 3


def test_markup_eachMpgSlotWrapsItsValueAsTheAirflowLine():
    """
    Given: dashboard.html's three MPG slots
    When: their markup is read
    Then: each carries .fuel-line > .fuel-value "--" + an empty .fuel-unit, as AIRFLOW (:344)
    """
    markup = _fuelMarkup()
    line = ('<span class="fuel-line"><span class="fuel-value">--</span>'
            '<span class="fuel-unit"></span></span>')
    for slotCls, _key in _MPG_SLOTS:
        slot = re.search(rf'<div class="fuel-reading {slotCls}".*?</div>', markup, re.S)
        assert slot is not None, slotCls
        assert line in slot.group(0), slotCls
        assert slot.group(0).count('class="fuel-value"') == 1, slotCls


@_NODE_ONLY
@pytest.mark.parametrize(
    ("payload", "key", "text"),
    [(_fuelEconomy(sinceReset=_resetRow(14.8)), "sinceReset", "≈14.8"),
     (_fuelEconomy(thisDrive=_drive(mpg=26.3)), "thisDrive", "≈26.3"),
     (_fuelEconomy(thisDrive=_drive(mpg=99.96)), "thisDrive", "≈100.0"),
     (_withRecent(_recent(mpg=104.2)), "last30", "99+"),
     (_withRecent(_recent(mpg=27.0)), "last30", "27")],
    ids=["since-reset-14.8", "this-drive", "this-drive-100", "last30-99plus", "last30-27"],
)
def test_validation_aFigure_carriesMpg_andItsTextIsUnchanged(payload: Any, key: str, text: str):
    view = _mpgView(payload)
    assert view[key]["text"] == text  # no literal space, no unit in the figure
    assert view[key]["unit"] == MPG_UNIT
    assert view[key]["noteKind"] == "none"


@_NODE_ONLY
@pytest.mark.parametrize(
    ("payload", "key"),
    [(_fuelEconomy(thisDrive=None), "thisDrive"),                         # not started
     (_fuelEconomy(sinceReset=None), "sinceReset"),                       # never reset
     (_fuelEconomy(thisDrive=_drive(mpgNullReason="too_short")), "thisDrive"),
     (_fuelEconomy(thisDrive=_drive(mpgNullReason="zzz_new")), "thisDrive"),
     (_fuelEconomy(sinceReset=_resetRow(None)), "sinceReset"),
     (_fuelEconomy(thisDrive=5, sinceReset="x"), "thisDrive"),            # not published
     (None, "thisDrive"),                                                 # no source
     (None, "sinceReset"),
     ({"ts": None}, "last30"),                                            # not published
     (_withRecent(None), "last30"),                                       # not started
     (_withRecent(_recent(mpg=None, mpgNullReason="too_few_samples")), "last30")],
    ids=["not-started", "never-reset", "reason", "raw-code", "since-reset-null",
         "not-published", "no-source-drive", "no-source-reset", "last30-unpublished",
         "last30-not-started", "last30-reason"],
)
def test_validation_aDash_neverCarriesTheUnit(payload: Any, key: str):
    view = _mpgView(payload)
    assert view[key]["text"] == "--"
    assert view[key]["unit"] == ""


@_NODE_ONLY
@pytest.mark.parametrize("phase", ["posting", "awaiting"])
def test_resetting_isADash_withNoUnit(phase: str):
    view = _resetView(_fuelEconomy(sinceReset=_resetRow(14.8)), phase)
    assert view["sinceReset"]["text"] == "--"
    assert view["sinceReset"]["note"] == "resetting…"
    assert view["sinceReset"]["unit"] == ""


@_NODE_ONLY
def test_resetOverlay_idle_keepsTheFiguresUnit():
    view = _resetView(_fuelEconomy(sinceReset=_resetRow(14.8)), "idle")
    assert (view["sinceReset"]["text"], view["sinceReset"]["unit"]) == ("≈14.8", MPG_UNIT)


@_NODE_ONLY
@pytest.mark.parametrize("caseId", [cid for cid, _c in _mpgCases()])
def test_dom_mpgUnitPaintsTheView(caseId: str):
    """
    Given: every MPG fixture case
    When: the page boots on it
    Then: each slot's .fuel-unit (inside its .fuel-line) reads the view's unit
    """
    payload = dict(_mpgCases())[caseId]["fuel-economy"]
    view = _mpgView(payload)
    surface = _boot(system=_driving(), fuelEconomy=payload)
    for slotCls, key in _MPG_SLOTS:
        unit = _mpgSlotPath(surface, slotCls, "fuel-unit")
        assert _textOf(unit[-1]) == view[key]["unit"], slotCls
        assert any("fuel-line" in _classes(n) for n in unit), slotCls
        assert _textOf(_mpgSlotPath(surface, slotCls, "fuel-value")[-1]) == view[key]["text"]


@_NODE_ONLY
def test_dom_validation_sinceReset14p8_andLast30Capped_carryMpg_notStartedDoesNot():
    payload = _withRecent(_recent(mpg=104.2))
    payload["thisDrive"] = None
    payload["sinceReset"] = _resetRow(14.8)
    surface = _boot(system=_driving(), fuelEconomy=payload)

    def _pair(slotCls: str) -> tuple[str, str]:
        return (_textOf(_mpgSlotPath(surface, slotCls, "fuel-value")[-1]),
                _textOf(_mpgSlotPath(surface, slotCls, "fuel-unit")[-1]))

    assert _pair("fuel-mpg-since-reset") == ("≈14.8", MPG_UNIT)
    assert _pair("fuel-mpg-last30") == ("99+", MPG_UNIT)
    assert _pair("fuel-mpg-this-drive") == ("--", "")


@_NODE_ONLY
def test_dom_mpgUnit_isTheAirflowUnitStyle():
    surface = _boot(system=_driving(), fuelEconomy=_fuelEconomy(thisDrive=_drive(mpg=26.3)))
    unit = _mpgSlotPath(surface, "fuel-mpg-this-drive", "fuel-unit")
    assert surface.winningDeclaration(unit, "font-size")[0] == "var(--fs-label)"
    assert surface.winningDeclaration(unit, "color")[0] == "var(--text-secondary)"
    assert surface.winningDeclaration(unit, "font-family")[0] == "var(--font-mono)"
    line = _mpgSlotPath(surface, "fuel-mpg-this-drive", "fuel-line")
    assert surface.winningDeclaration(line, "gap")[0] == "var(--fuel-unit-gap)"
    assert _fuelPx("var(--fuel-unit-gap)") == 4  # spec s4.3 :71, "the 4 px --fuel-unit-gap"


def test_css_mpgLine_wrapsRatherThanClips():
    """Spec :77: a seven-character figure drops MPG under it -- never clips."""
    body = _rule("#fuel-card .fuel-mpg .fuel-line")
    assert _decl(body, "flex-wrap") == "wrap"
    for selector, ruleBody in _fuelRules():
        if "fuel-line" in selector or "fuel-unit" in selector:
            assert "nowrap" not in ruleBody, selector
            assert "ellipsis" not in ruleBody, selector


def test_mpgScrollbarColumn_isTheSpecs136px():
    assert _mpgScrollbarColumnWidth() == _MPG_SCROLLBAR_COLUMN_PX


@pytest.mark.parametrize(
    ("figure", "sizeVar", "spec"),
    [("≈100.0", "var(--fs-secondary)", 134.0),   # spec :76, the six-character worst case
     ("≈99.9", "var(--fs-secondary)", 118.4),    # spec :76
     ("99+", "var(--fs-primary)", 101.5)],       # spec :75, LAST 30 S
)
def test_validation_figurePlusMpg_fitsTheScrollbarColumn(figure: str, sizeVar: str, spec: float):
    width = _mpgFigureWithUnitWidth(figure, sizeVar)
    assert round(width, 1) == spec, (figure, width)
    assert width <= _MPG_SCROLLBAR_COLUMN_PX, (figure, width)


def test_mpgUnitFitModel_failsAPlantedSevenCharacterFigure():
    """Spec :77: "≈1000.0" (seven characters) is 149.7 px -- it must wrap, not fit."""
    width = _mpgFigureWithUnitWidth("≈1000.0", "var(--fs-secondary)")
    assert round(width, 1) == 149.7
    assert width > _MPG_SCROLLBAR_COLUMN_PX
