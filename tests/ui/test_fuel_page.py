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
# 2026-10-15    | Rex (US-890-b) | AIRFLOW from params.MAF against params.MAF
#                                .scale.max (section 8). PIN CHANGE: the two
#                                upper-row tests no longer expect AIRFLOW to be
#                                "not published" (UNPUBLISHED_SLOTS).
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
# US-890-b: AIRFLOW is published now; the rest still wait on their stories.
UNPUBLISHED_SLOTS = [(s, lbl) for s, lbl in UPPER_SLOTS if s != "airflow"]
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


def _boot(
    trend: Any = None,
    system: Any = None,
    nowIso: str = "2026-10-20T15:12:30Z",
    obdLive: Any = None,
) -> rh.Surface:
    routes: dict[str, Any] = {}
    if trend is not None:
        routes["/ltft-trend"] = trend
    if system is not None:
        routes["/system-status"] = system
    if obdLive is not None:
        routes["/obd-live"] = obdLive
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
    # US-890-b: no obd-live file -> AIRFLOW says why ("no source"), never blank.
    assert _fuelText(surface, "fuel-note") == ["no source"] + [NOT_PUBLISHED] * len(UNPUBLISHED_SLOTS)


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


@pytest.mark.parametrize("name", AIRFLOW_FIXTURES)
def test_airflowFixture_obdLiveIsWhatTheBuilderEmits(name: str):
    """
    Given: a fixture's obd-live payload
    When: its readings are fed through a real ObdLiveTracker (its MAF scale max
          as pi.display.scale.mafMaxGs) and built at the payload's ts
    Then: the builder's output equals the payload -- the page is tested against
          the provider's real shape, scale included
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
            _Reading(pid, value, _naiveUtc(param["ts"]), pythonObdName[param["unit"]])
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
