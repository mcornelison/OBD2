################################################################################
# File Name: test_engine_history_render.py
# Purpose/Description: US-889-c (F-127) tests for the Engine card's scroll half
#   -- V0.30 Engine layout B below the fold (specs/v030-engine-page-design.md
#   s3-s4, ACs 5-11). Guarded:
#     1. the FIXTURES -- the eleven new cases under fixtures/states/engine/,
#        history payloads byte-equal to US-889-a's engine-history.json cases;
#     2. the HISTORY VIEW -- spans come ONLY from a point's band (amber/red),
#        never from a value; an omitted bucket breaks the line; IAT neutral in
#        every fixture; the window label from engine-history.partial/sinceTs
#        alone; end value converted by the series' unit through displayUnits;
#        an empty or absent history is the typed absence, never a chart;
#     3. the STATUS VIEW -- RUN TIME from RUNTIME_SEC (h:mm, never drive time),
#        CHECK ENGINE from MIL_ON by value, the count line from DTC_COUNT while
#        ON, a tap to the Alerts card only while parked;
#     4. the SHIPPED DOM -- the same, painted by the real tick, including the
#        parked tap navigating to ALERTS and the moving tap going nowhere;
#     5. the GREP GATE -- no coolant/battery threshold literal in carousel.js;
#     6. the CSS -- span colour only through data-band tokens, the status grid
#        max-content / 1fr with an 8 px scoped gap, and a width model of the
#        status row at a 2- and 3-digit count with negative controls.
#   NOT GUARDED, stated rather than implied: the render harness resolves the
#   cascade, not layout (render_harness.py fidelity limit 1), so "no tile
#   overflows" is the arithmetic model in section 6 plus the absence of any
#   fixed height; the glass check is the R15 screenshot owed on the Pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Ralph (Rex)  | Initial -- US-889-c Engine scroll half.
# 2026-10-19    | Ralph (Rex)  | US-909: mil-on-one-code joins MIL_FIXTURES;
#               |              | DTC_COUNT 1 reads '1 code ›' (spec s3:53).
# 2026-10-22    | Ralph (Rex)  | US-511-b MOVED PIN: parked is states/gear (P/N),
#               |              | so the parked boots serve a gear route too.
# ================================================================================
################################################################################

"""US-889-c tests for the Engine card's history graphs and status row."""

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
    _gearMoving,
    _gearParked,
    _parked,
)
from tests.ui.test_dashboard_fidelity_pass import _stripJsComments  # noqa: E402
from tests.ui.test_engine_page import (  # noqa: E402
    _bodyWidthPx,
    _child,
    _classes,
    _decl,
    _enginePaths,
    _engineRules,
    _monoWidth,
    _ms,
    _px,
    _rule,
    _textOf,
)
from tests.ui.test_topbar_three_column_grid import michromaWidthPx  # noqa: E402

_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_STATES = os.path.join(os.path.dirname(__file__), "fixtures", "states")
_FIXTURES = os.path.join(_STATES, "engine")
_ARCH = os.path.join(os.path.dirname(__file__), "..", "..", "specs", "architecture.md")

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped browser JS",
)

HISTORY_FIXTURES = [
    "cold-start-history",
    "fan-cycle-history",
    "coolant-dwell-fired",
    "bucket-worst-band",
    "history-gap",
    "history-trimmed-2h",
    "history-restart-mid-drive",
    "history-empty-after-restart",
]
MIL_FIXTURES = {
    "mil-on-one-code": 1,
    "mil-on-two-codes": 2,
    "mil-on-twelve-codes": 12,
    "mil-on-zero-codes": 0,
}
SERIES = [("COOLANT_TEMP", "COOLANT"), ("INTAKE_TEMP", "INTAKE AIR"), ("BATTERY_V", "BATTERY")]
ABSENCE = "History not recorded yet. It starts with this drive's first readings."
SPAN_BANDS = ("amber", "red")
CHART_W = 100.0


def _codesText(count: int) -> str:
    """The count line for a read DTC_COUNT: singular at exactly one
    (specs/v030-engine-page-design.md:53), plural for 0 and for 2+."""
    return f"{count} code ›" if count == 1 else f"{count} codes ›"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _probe(fn: str, *args: object, tz: str = "UTC") -> Any:
    """Call a carousel.js export in node, on a pinned local time zone."""
    cmd = [_NODE or "node", _PROBE, fn] + [json.dumps(a) for a in args]
    env = dict(os.environ, TZ=tz)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _history(name: str) -> dict[str, Any]:
    return _fixture(name)["engine-history"]


def _historyView(name: str) -> dict[str, Any]:
    return _probe("engineHistoryView", _history(name))


def _series(view: dict[str, Any], pid: str) -> dict[str, Any]:
    return next(s for s in view["series"] if s["pid"] == pid)


def _spanBuckets(payload: dict[str, Any], pid: str) -> list[float]:
    """Where the page must paint a span: the START x of every amber/red bucket,
    on the shared axis (the extent of the buckets across all three series)."""
    interval = payload["intervalSec"] * 1000
    allPts = [p for s in payload["series"].values() for p in s]
    x0 = min(_ms(p["ts"]) for p in allPts) - interval
    x1 = max(_ms(p["ts"]) for p in allPts)
    return [
        round((_ms(p["ts"]) - interval - x0) / (x1 - x0) * CHART_W, 1)
        for p in payload["series"][pid]
        if p["band"] in SPAN_BANDS
    ]


def _status(obdLive: Any, parked: bool = False) -> dict[str, Any]:
    return _probe("engineStatusView", obdLive, parked, 0)


def _param(value: float | None, unit: str, **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "value": value, "unit": unit, "ts": "2026-10-20T15:12:29Z", "stale": False,
        "band": None, "noBandReason": "no_band_defined", "last": None,
    }
    entry.update(extra)
    return entry


def _boot(
    history: Any = None, obdLive: Any = None, system: Any = None,
    steps: list[dict[str, Any]] | None = None, nowIso: str = "2026-10-20T15:12:30Z",
    gear: Any = None,
) -> rh.Surface:
    routes: dict[str, Any] = {}
    # MOVED PIN (US-511-b): parked is states/gear (P or N), not system-status idle.
    if gear is not None:
        routes["/gear"] = gear
    if history is not None:
        routes["/engine-history"] = history
    if obdLive is not None:
        routes["/obd-live"] = obdLive
    if system is not None:
        routes["/system-status"] = system
    dom = rh.runDashboard(routes=routes, nowMs=_ms(nowIso), steps=steps or [{"flush": 4}])
    return rh.dashboardSurface(dom["tree"])


def _bootHistory(name: str) -> rh.Surface:
    fx = _fixture(name)
    return _boot(history=fx["engine-history"], nowIso=fx["now"])


# Parked is the US-511 debounce: the parked GEAR (US-511-b) must be HELD for
# parkedOnS (8 s).
_HOLD_PARKED = [{"flush": 4}, {"advanceMs": 9000, "flush": 4}]


def _bootMil(name: str, parked: bool, click: bool = False) -> rh.Surface:
    fx = _fixture(name)
    steps = list(_HOLD_PARKED)
    if click:
        steps += [{"click": "engine-codes"}, {"flush": 2}]
    return _boot(
        obdLive=fx["obd-live"], system=_parked() if parked else _driving(),
        steps=steps, nowIso=fx["now"], gear=_gearParked() if parked else _gearMoving(),
    )


def _pageName(surface: rh.Surface) -> str:
    path = surface.pathById("page-name")
    assert path is not None
    return _textOf(path[-1])


def _stat(surface: rh.Surface, pid: str) -> list[dict[str, Any]]:
    for path in _enginePaths(surface, "eng-stat"):
        if path[-1].get("attrs", {}).get("data-pid") == pid:
            return path
    raise AssertionError(f"no .eng-stat for {pid}")


def _descendants(path: list[dict[str, Any]], cls: str) -> list[list[dict[str, Any]]]:
    found: list[list[dict[str, Any]]] = []

    def walk(node: dict[str, Any], trail: list[dict[str, Any]]) -> None:
        for child in node.get("children", []):
            if "tag" not in child:
                continue
            here = trail + [child]
            if cls in _classes(child):
                found.append(here)
            walk(child, here)

    walk(path[-1], path)
    return found


def _historyHost(surface: rh.Surface) -> list[dict[str, Any]]:
    hosts = _enginePaths(surface, "eng-history")
    assert len(hosts) == 1
    return hosts[0]


def _histBox(surface: rh.Surface, pid: str) -> list[dict[str, Any]]:
    for path in _descendants(_historyHost(surface), "eng-hist"):
        if path[-1]["attrs"].get("data-pid") == pid:
            return path
    raise AssertionError(f"no .eng-hist for {pid}")


# ---------------------------------------------------------------------------
# 1. Fixtures.
# ---------------------------------------------------------------------------


def test_thisStorysFixturesArePresent():
    for name in HISTORY_FIXTURES + list(MIL_FIXTURES):
        assert os.path.isfile(os.path.join(_FIXTURES, name + ".json")), name


@pytest.mark.parametrize("name", HISTORY_FIXTURES)
def test_historyPayloads_areCopiedFromUs889aFixtureCases(name: str):
    """The page is tested on exactly what the provider's own tests produced
    (tests/pi/obdii/test_engine_history.py builds these through the real
    tracker), not on a hand-drawn shape that could drift from it."""
    source = json.loads(_read(os.path.join(_STATES, "engine-history.json")))
    assert _history(name) == source[name]
    assert _fixture(name)["now"] == source[name]["ts"]


@pytest.mark.parametrize(("name", "count"), sorted(MIL_FIXTURES.items()))
def test_milFixtures_lampOnWithTheirCount(name: str, count: int):
    params = _fixture(name)["obd-live"]["params"]
    assert params["MIL_ON"]["value"] == 1
    assert params["DTC_COUNT"]["value"] == count
    assert params["RUNTIME_SEC"]["value"] == 1380


# ---------------------------------------------------------------------------
# 2. The history view.
# ---------------------------------------------------------------------------


@_NODE_ONLY
@pytest.mark.parametrize("name", HISTORY_FIXTURES)
def test_spansAreExactlyThePointsWhoseBandIsAmberOrRed(name: str):
    """AC 6: colour comes ONLY from each point's band. Every amber/red bucket
    is a span at its own place on the axis; no other bucket is."""
    payload = _history(name)
    view = _historyView(name)
    if view["empty"]:
        assert all(not pts for pts in payload["series"].values())
        return
    for pid, _ in SERIES:
        spans = _series(view, pid)["spans"]
        assert [s["x"] for s in spans] == _spanBuckets(payload, pid), (name, pid)
        expected = [p["band"] for p in payload["series"].get(pid, []) if p["band"] in SPAN_BANDS]
        assert [s["band"] for s in spans] == expected, (name, pid)


@_NODE_ONLY
def test_fanCycle_101CPeaks_allGreen_noSpan():
    """Validation row: fan-cycle-history (101 C peaks, all bands green)."""
    view = _historyView("fan-cycle-history")
    assert max(p["value"] for p in _history("fan-cycle-history")["series"]["COOLANT_TEMP"]) == 101.0
    for pid, _ in SERIES:
        assert _series(view, pid)["spans"] == [], pid


@_NODE_ONLY
def test_lineCrossing104_withNoAmberBand_showsNoColour():
    """AC 6: coolant-dwell-fired crosses 104 C at 15:01:30 while its band is
    still green -- that bucket is NOT painted; the span starts where the
    provider's dwell fired."""
    payload = _history("coolant-dwell-fired")
    crossing = payload["series"]["COOLANT_TEMP"][2]
    assert (crossing["value"], crossing["band"]) == (106.0, "green")
    spans = _series(_historyView("coolant-dwell-fired"), "COOLANT_TEMP")["spans"]
    # The crossing bucket starts at x 16.7 on this 12-bucket axis; the first span is the next one.
    assert [s["x"] for s in spans] == [25.0, 33.3, 41.7]


@_NODE_ONLY
def test_amberBucketBelowTheNumber_isStillAmber():
    """Validation row: bucket-worst-band -- the bucket's plotted value (its LAST
    sample, 101.0 C) is below the amber number, its band is amber, so it is an
    amber span anyway."""
    payload = _history("bucket-worst-band")
    below = payload["series"]["COOLANT_TEMP"][2]
    assert (below["value"], below["band"]) == (101.0, "amber")
    spans = _series(_historyView("bucket-worst-band"), "COOLANT_TEMP")["spans"]
    assert {"x": 50.0, "width": 25.0, "band": "amber"} in spans


@_NODE_ONLY
def test_examplePoint_103Amber_isAnAmberSpan_endLabel217F():
    """Story example: COOLANT {ts 15:20:00Z, value 103.0, band amber} -> amber
    span, end label '217' deg F."""
    payload = {
        "ts": "2026-10-20T15:20:02Z", "sinceTs": "2026-10-20T15:19:00Z", "partial": False,
        "intervalSec": 30.0, "unit": {"COOLANT_TEMP": "C"},
        "series": {
            "COOLANT_TEMP": [
                {"ts": "2026-10-20T15:19:30Z", "value": 101.0, "band": "green"},
                {"ts": "2026-10-20T15:20:00Z", "value": 103.0, "band": "amber"},
            ],
            "INTAKE_TEMP": [], "BATTERY_V": [],
        },
    }
    coolant = _series(_probe("engineHistoryView", payload), "COOLANT_TEMP")
    assert coolant["spans"] == [{"x": 50.0, "width": 50.0, "band": "amber"}]
    assert coolant["end"] == {"text": "217", "unit": "°F"}


@_NODE_ONLY
def test_aGreenOrNullOrUnknownBand_isNeverASpan():
    pts = [
        {"ts": "2026-10-20T15:00:30Z", "value": 120.0, "band": "green"},
        {"ts": "2026-10-20T15:01:00Z", "value": 120.0, "band": None},
        {"ts": "2026-10-20T15:01:30Z", "value": 120.0, "band": "orange"},
        {"ts": "2026-10-20T15:02:00Z", "value": 120.0, "band": "red"},
    ]
    payload = {"partial": False, "intervalSec": 30, "unit": {"COOLANT_TEMP": "C"},
               "series": {"COOLANT_TEMP": pts}}
    spans = _series(_probe("engineHistoryView", payload), "COOLANT_TEMP")["spans"]
    assert [s["band"] for s in spans] == ["red"]


@_NODE_ONLY
@pytest.mark.parametrize("name", HISTORY_FIXTURES)
def test_intakeAir_isNeutralInEveryFixture(name: str):
    """AC 9: INTAKE_TEMP has no band (no_band_defined) -> never a span."""
    view = _historyView(name)
    if not view["empty"]:
        assert _series(view, "INTAKE_TEMP")["spans"] == []


@_NODE_ONLY
def test_historyGap_breaksEveryLineIntoTwoSegments():
    """Validation row: history-gap -> two separate line segments, and neither
    reaches across the omitted buckets (15:01:30, 15:02:00)."""
    view = _historyView("history-gap")
    for pid, _ in SERIES:
        segments = _series(view, pid)["segments"]
        assert len(segments) == 2, pid
        firstEnd = float(segments[0].split()[-1].split(",")[0])
        secondStart = float(segments[1].split()[0].split(",")[0])
        assert (firstEnd, secondStart) == (33.3, 66.7), pid


@_NODE_ONLY
@pytest.mark.parametrize("name", [n for n in HISTORY_FIXTURES if n != "history-gap"])
def test_contiguousBuckets_areOneSegment(name: str):
    view = _historyView(name)
    for series in view["series"]:
        assert len(series["segments"]) == (0 if series["empty"] else 1), (name, series["pid"])


@_NODE_ONLY
def test_theLineSteps_flatAcrossEachBucket_noInterpolation():
    """AC 4: each bucket is a flat run at its own value with a riser at the
    boundary -- two vertices per bucket, the pair sharing one y."""
    view = _historyView("fan-cycle-history")
    coords = [tuple(map(float, xy.split(","))) for xy in _series(view, "COOLANT_TEMP")["segments"][0].split()]
    assert len(coords) == 2 * 20
    for i in range(0, len(coords), 2):
        assert coords[i][1] == coords[i + 1][1]
        if i:
            assert coords[i][0] == coords[i - 1][0]


@_NODE_ONLY
@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("cold-start-history", "THIS DRIVE"),
        ("history-trimmed-2h", "SINCE 3:02"),
        ("history-restart-mid-drive", "SINCE 3:12"),
    ],
)
def test_windowLabel_fromPartialAndSinceTsAlone(name: str, label: str):
    """AC (Atlas G3): partial false -> THIS DRIVE; partial true -> SINCE h:mm
    from sinceTs (local time; the probe pins TZ=UTC)."""
    assert _historyView(name)["window"] == label


@_NODE_ONLY
def test_windowLabel_sinceTs1305_readsSince105():
    """Validation row: history-trimmed-2h shape with sinceTs 13:05 -> 'SINCE
    1:05' -- h:mm on the panel's 12-hour face."""
    payload = dict(_history("history-trimmed-2h"), sinceTs="2026-10-20T13:05:00Z")
    assert _probe("engineHistoryView", payload)["window"] == "SINCE 1:05"


@_NODE_ONLY
def test_windowLabel_isLocalTime():
    payload = _history("history-trimmed-2h")
    assert _probe("engineHistoryView", payload, tz="Asia/Tokyo")["window"] == "SINCE 12:02"


@_NODE_ONLY
def test_windowLabel_partialWithAnUnreadableSinceTs_neverInventsATime():
    payload = dict(_history("history-trimmed-2h"), sinceTs="2026-10-20T15:02:00")
    assert _probe("engineHistoryView", payload)["window"] == "SINCE --"


def test_historyView_readsNoOtherProvidersClock():
    """AC (Atlas G3): the window comes from engine-history alone -- the view
    takes ONE argument and reads no clock, no drive id, no other state."""
    js = _read(_JS)
    assert re.search(r"function engineHistoryView\(data\)", js)
    for fn in ("engineHistoryView", "engineHistoryWindow", "engineHistorySeries"):
        body = _stripJsComments(rh._fnBody(js, fn))
        for banned in ("Date.now", "nowMs", "driveId", "stateOnce", "drive"):
            assert banned not in body, (fn, banned)


@_NODE_ONLY
@pytest.mark.parametrize(
    ("name", "ends"),
    [
        ("bucket-worst-band", {"COOLANT_TEMP": ("214", "°F"), "INTAKE_TEMP": ("95", "°F"),
                               "BATTERY_V": ("14.0", "V")}),
        ("cold-start-history", {"COOLANT_TEMP": ("176", "°F"), "INTAKE_TEMP": ("77", "°F"),
                                "BATTERY_V": ("14.1", "V")}),
    ],
)
def test_endValue_isTheLastPointConvertedByItsUnit(name: str, ends: dict[str, tuple[str, str]]):
    view = _historyView(name)
    for pid, (text, unit) in ends.items():
        assert _series(view, pid)["end"] == {"text": text, "unit": unit}, pid


@_NODE_ONLY
def test_endValue_withNoPublishedUnit_rendersRaw_neverAssumesCelsius():
    payload = dict(_history("bucket-worst-band"), unit={})
    assert _series(_probe("engineHistoryView", payload), "COOLANT_TEMP")["end"] == {
        "text": "101", "unit": ""
    }


@_NODE_ONLY
@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"series": "nope", "intervalSec": 30},
        {"series": {"COOLANT_TEMP": [{"ts": "2026-10-20T15:00:30Z", "value": 90, "band": None}]},
         "intervalSec": 0},
    ],
)
def test_absentOrUnreadableHistory_isTheTypedAbsence(payload: Any):
    view = _probe("engineHistoryView", payload)
    assert view["empty"] is True and view["series"] == [] and view["absence"] == ABSENCE


@_NODE_ONLY
def test_emptyAfterRestart_isTheTypedAbsence():
    view = _historyView("history-empty-after-restart")
    assert (view["empty"], view["absence"], view["series"]) == (True, ABSENCE, [])


@_NODE_ONLY
def test_trimmed_seriesWithNoPoints_isNotAnEmptyChart():
    view = _historyView("history-trimmed-2h")
    for pid in ("INTAKE_TEMP", "BATTERY_V"):
        assert _series(view, pid) == {
            "pid": pid, "label": dict(SERIES)[pid], "empty": True,
            "segments": [], "spans": [], "end": None,
        }


@_NODE_ONLY
def test_flatSeries_drawsMidHeight_notOffTheChart():
    view = _historyView("history-gap")
    ys = {xy.split(",")[1] for seg in _series(view, "COOLANT_TEMP")["segments"] for xy in seg.split()}
    assert ys == {"23"}


# ---------------------------------------------------------------------------
# 3. The status view.
# ---------------------------------------------------------------------------


@_NODE_ONLY
@pytest.mark.parametrize(("name", "count"), sorted(MIL_FIXTURES.items()))
def test_milOn_isOn_withTheCountLine(name: str, count: int):
    for parked in (False, True):
        view = _status(_fixture(name)["obd-live"], parked)
        assert view["mil"]["text"] == "ON"
        assert view["codes"] == {"text": _codesText(count), "tap": parked}, (name, parked)


@_NODE_ONLY
def test_milOff_isOff_withNoCountLine():
    view = _status({"params": {"MIL_ON": _param(0.0, "mil"), "DTC_COUNT": _param(3.0, "count")}}, True)
    assert (view["mil"]["text"], view["codes"]) == ("OFF", None)


@_NODE_ONLY
@pytest.mark.parametrize("unit", ["mil", "ON", "OFF", None, "count"])
def test_mil_isReadByValue_neverByUnit(unit: str | None):
    view = _status({"params": {"MIL_ON": _param(1.0, unit), "DTC_COUNT": _param(2.0, "count")}})
    assert view["mil"]["text"] == "ON"


@_NODE_ONLY
def test_milWithAValueOtherThan0Or1_isNotRead_neverAGuess():
    view = _status({"params": {"MIL_ON": _param(2.0, "mil")}})
    assert (view["mil"]["text"], view["mil"]["note"], view["codes"]) == ("--", "not read", None)


@_NODE_ONLY
@pytest.mark.parametrize(("name", "text"), [("mil-on-one-code", "1 code ›"), ("mil-on-two-codes", "2 codes ›")])
def test_milOn_countOne_isSingular_twoStaysPlural(name: str, text: str):
    """US-909 validation rows: DTC_COUNT 1 reads '1 code ›' (spec
    v030-engine-page-design.md:53, the most common real MIL case); 2 is
    unchanged. Literal strings, not _codesText, so the rule is pinned twice."""
    view = _status(_fixture(name)["obd-live"], True)
    assert view["codes"] == {"text": text, "tap": True}


@_NODE_ONLY
def test_milOn_countNotRead_keepsTheTapWithDashDash():
    view = _status({"params": {"MIL_ON": _param(1.0, "mil")}}, True)
    assert view["codes"] == {"text": "-- codes ›", "tap": True}


@_NODE_ONLY
@pytest.mark.parametrize(("seconds", "text"), [(1380, "0:23"), (7505, "2:05"), (0, "0:00"), (65535, "18:12")])
def test_runTime_isHMmFromRuntimeSec(seconds: int, text: str):
    view = _status({"params": {"RUNTIME_SEC": _param(float(seconds), "second")}})
    assert (view["runTime"]["text"], view["runTime"]["note"]) == (text, "")


@_NODE_ONLY
def test_runTimeAbsent_isDashDashNotRead():
    """Validation row: params.RUNTIME_SEC absent -> RUN TIME '--' + 'not read'
    (US-889-b's not-read-with-reason fixture carries no RUNTIME_SEC)."""
    obdLive = json.loads(_read(os.path.join(_FIXTURES, "not-read-with-reason.json")))["obd-live"]
    assert "RUNTIME_SEC" not in obdLive["params"]
    view = _status(obdLive)
    assert (view["runTime"]["text"], view["runTime"]["note"]) == ("--", "not read")


@_NODE_ONLY
def test_noObdLive_isDashDashNoSource():
    view = _status(None)
    for key in ("runTime", "mil"):
        assert (view[key]["text"], view[key]["note"]) == ("--", "no source"), key
    assert view["codes"] is None


@_NODE_ONLY
def test_staleRunTime_isLastValueWithItsAge():
    param = _param(None, "second", stale=True, last={"value": 1380.0, "band": None})
    view = _probe("engineStatusView", {"params": {"RUNTIME_SEC": param}}, False,
                  _ms("2026-10-20T15:12:41Z"))
    r = view["runTime"]
    assert (r["text"], r["stale"], r["note"], r["noteKind"]) == ("0:23", True, "12 s", "age")


def test_runTime_isNeverDerivedFromDriveTime():
    """Atlas G4: engine run time and drive time are different facts."""
    js = _read(_JS)
    for fn in ("engineStatusView", "engineRunTimeText"):
        body = _stripJsComments(rh._fnBody(js, fn))
        assert "drive" not in body.lower(), fn
    assert "params.RUNTIME_SEC" in _stripJsComments(rh._fnBody(js, "engineStatusView"))


# ---------------------------------------------------------------------------
# 4. The shipped DOM.
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_dom_emptyAfterRestart_isTheAbsenceText_andNoChartElement():
    """Validation row: history-empty-after-restart -> the typed absence text,
    no chart element."""
    surface = _bootHistory("history-empty-after-restart")
    host = _historyHost(surface)
    absence = _descendants(host, "eng-absence")
    assert [_textOf(p[-1]) for p in absence] == [ABSENCE]
    assert surface.rendered(absence[0])
    for cls in ("eng-hist", "eng-hist-chart", "eng-hist-line", "eng-hist-span"):
        assert _descendants(host, cls) == [], cls


@_NODE_ONLY
def test_dom_noEngineHistoryFile_isTheAbsenceText():
    surface = _boot()
    host = _historyHost(surface)
    assert [_textOf(p[-1]) for p in _descendants(host, "eng-absence")] == [ABSENCE]
    assert _descendants(host, "eng-hist-chart") == []


@_NODE_ONLY
def test_dom_gap_isTwoPolylinesPerChart():
    surface = _bootHistory("history-gap")
    for pid, _ in SERIES:
        assert len(_descendants(_histBox(surface, pid), "eng-hist-line")) == 2, pid


@_NODE_ONLY
def test_dom_bucketWorstBand_paintsAnAmberSpanFromTheToken():
    surface = _bootHistory("bucket-worst-band")
    spans = _descendants(_histBox(surface, "COOLANT_TEMP"), "eng-hist-span")
    assert [p[-1]["attrs"]["data-band"] for p in spans] == ["amber", "amber"]
    assert surface.winningDeclaration(spans[0], "fill")[0] == "var(--amber-warn)"
    assert _descendants(_histBox(surface, "INTAKE_TEMP"), "eng-hist-span") == []


@_NODE_ONLY
def test_dom_fanCycle_hasNoSpan_andTheLineIsNeutral():
    surface = _bootHistory("fan-cycle-history")
    host = _historyHost(surface)
    assert _descendants(host, "eng-hist-span") == []
    for line in _descendants(host, "eng-hist-line"):
        assert surface.winningDeclaration(line, "stroke")[0] == "var(--text-primary)"


@_NODE_ONLY
def test_dom_redSpan_isTheCriticalRedToken():
    payload = dict(_history("bucket-worst-band"))
    payload["series"] = dict(payload["series"], COOLANT_TEMP=[
        {"ts": "2026-10-20T15:00:30Z", "value": 112.0, "band": "red"},
    ])
    surface = _boot(history=payload)
    span = _descendants(_histBox(surface, "COOLANT_TEMP"), "eng-hist-span")
    assert surface.winningDeclaration(span[0], "fill")[0] == "var(--critical-red)"


@_NODE_ONLY
@pytest.mark.parametrize(("name", "window"), [("cold-start-history", "THIS DRIVE"), ("history-trimmed-2h", "SINCE ")])
def test_dom_eachGraph_isLabelledWithItsNameAndWindow_andEndValue(name: str, window: str):
    surface = _bootHistory(name)
    view = _historyView(name)
    for pid, label in SERIES:
        box = _histBox(surface, pid)
        assert _textOf(_child(box, "eng-label")[-1]) == label
        assert _textOf(_child(box, "eng-hist-window")[-1]).startswith("· " + window)
        series = _series(view, pid)
        if series["empty"]:
            assert [_textOf(p[-1]) for p in _descendants(box, "eng-absence")] == [ABSENCE]
            assert _descendants(box, "eng-hist-chart") == []
        else:
            assert _textOf(_child(box, "eng-hist-value")[-1]) == series["end"]["text"]
            assert _textOf(_child(box, "eng-hist-unit")[-1]) == series["end"]["unit"]


@_NODE_ONLY
def test_dom_milOnTwelve_moving_showsTheCount_withNoTapTarget():
    """Validation row: mil-on-twelve-codes moving -> 'ON' / '12 codes ›'; tap
    target absent, and a tap goes nowhere."""
    surface = _bootMil("mil-on-twelve-codes", parked=False, click=True)
    tile = _stat(surface, "MIL_ON")
    assert _textOf(_child(tile, "eng-stat-value")[-1]) == "ON"
    codes = surface.pathById("engine-codes")
    assert codes is not None and _textOf(codes[-1]) == "12 codes ›"
    assert surface.rendered(codes)
    assert codes[-1]["attrs"].get("data-tap") == "false"
    assert "role" not in codes[-1]["attrs"]
    assert _pageName(surface) != "ALERTS"


@_NODE_ONLY
def test_dom_milOnTwelve_parked_isATapToTheAlertsCard():
    """Validation row: mil-on-twelve-codes parked -> the tap target is present
    and opens the Alerts card."""
    before = _bootMil("mil-on-twelve-codes", parked=True)
    codes = before.pathById("engine-codes")
    assert codes is not None and _textOf(codes[-1]) == "12 codes ›"
    assert codes[-1]["attrs"].get("data-tap") == "true"
    assert codes[-1]["attrs"].get("role") == "button"
    after = _bootMil("mil-on-twelve-codes", parked=True, click=True)
    assert _pageName(after) == "ALERTS"


@_NODE_ONLY
def test_dom_parkedGearNotYetHeld_isNotParked():
    """The debounce, not the raw fact: a parked gear for one tick is not parked
    yet. MOVED PIN (US-511-b): was test_dom_idleNotYetHeld_isNotParked."""
    fx = _fixture("mil-on-two-codes")
    surface = _boot(
        obdLive=fx["obd-live"], system=_parked(), nowIso=fx["now"], gear=_gearParked()
    )
    codes = surface.pathById("engine-codes")
    assert codes is not None and codes[-1]["attrs"].get("data-tap") == "false"


@_NODE_ONLY
@pytest.mark.parametrize(("name", "count"), sorted(MIL_FIXTURES.items()))
def test_dom_everyMilFixture_paintsOnAndItsCount(name: str, count: int):
    surface = _bootMil(name, parked=True)
    assert _textOf(_child(_stat(surface, "MIL_ON"), "eng-stat-value")[-1]) == "ON"
    codes = surface.pathById("engine-codes")
    assert codes is not None and _textOf(codes[-1]) == _codesText(count)
    runTime = _stat(surface, "RUNTIME_SEC")
    assert _textOf(_child(runTime, "eng-stat-value")[-1]) == "0:23"


@_NODE_ONLY
def test_dom_milOff_hidesTheCountLine():
    obdLive = {"params": {"MIL_ON": _param(0.0, "mil"), "DTC_COUNT": _param(0.0, "count")}}
    surface = _boot(obdLive=obdLive, system=_parked(), steps=_HOLD_PARKED, gear=_gearParked())
    assert _textOf(_child(_stat(surface, "MIL_ON"), "eng-stat-value")[-1]) == "OFF"
    codes = surface.pathById("engine-codes")
    assert codes is not None and not surface.rendered(codes)


@_NODE_ONLY
def test_dom_runTimeAbsent_isDashDash_withNotReadShown():
    obdLive = json.loads(_read(os.path.join(_FIXTURES, "not-read-with-reason.json")))["obd-live"]
    surface = _boot(obdLive=obdLive)
    tile = _stat(surface, "RUNTIME_SEC")
    assert _textOf(_child(tile, "eng-stat-value")[-1]) == "--"
    note = _child(tile, "eng-note")
    assert _textOf(note[-1]) == "not read" and surface.rendered(note)


def test_noO2SensorsTile_untilUs891():
    """Iris G-3: no O2 SENSORS tile in this story."""
    markup = re.search(r'id="engine-card".*?</section>', _read(_HTML), re.S)
    assert markup is not None
    assert "O2" not in re.sub(r"<!--.*?-->", "", markup.group(0), flags=re.S)


def test_theTickRendersTheScrollHalf_fromEngineHistoryAndTheParkedDebounce():
    js = _read(_JS)
    assert re.search(
        # MOVED PIN (US-511-b): the debounce is fed the gear, not idle.
        r"engineParked = parkedNext\(engineParked, gearParked\(lastGear\), nowMs, carouselCfg\);", js
    )
    assert re.search(
        r"renderEngineScroll\(\s*engineCard,\s*engineHistoryView\(await stateOnce\(\"engine-history\"\)\),"
        r"\s*engineStatusView\(await stateOnce\(\"obd-live\"\), engineParked\.parked, nowMs\)",
        js,
    )


# ---------------------------------------------------------------------------
# 5. The grep gate -- no coolant/battery threshold in carousel.js.
# ---------------------------------------------------------------------------

# pi.bands.coolant.{amberC 104, redC 110, clearBelowC 102} and
# pi.bands.battery.{greenMinV 13.5, greenMaxV 14.5, redBelowV 12.0, redAboveV
# 15.0} (src/common/config/validator.py), plus the coolant numbers in deg F.
_THRESHOLDS = ["104", "110", "102", "13.5", "14.5", "12.0", "12", "15.0", "15",
               "219.2", "219", "230", "215.6", "216"]


def _thresholdHits(js: str) -> list[str]:
    hits = []
    for number in _THRESHOLDS:
        for m in re.finditer(rf"(?<![\w.#-]){re.escape(number)}(?![\w.%]|px)", js):
            line = js[js.rfind("\n", 0, m.start()) + 1 : js.find("\n", m.end())]
            if re.search(r"(?i)coolant|battery|batt|engine|hist|eng[A-Z]|ENGINE", line):
                hits.append(f"{number}: {line.strip()}")
    return hits


def test_carouselJs_carriesNoCoolantOrBatteryThreshold():
    """AC 6 grep gate: the page never compares a history value with a number."""
    assert _thresholdHits(_stripJsComments(_read(_JS))) == []


def test_thresholdGate_catchesAPlantedLiteral():
    planted = 'var ENGINE_COOLANT_AMBER = 104;\nif (battV < 12.0) {}\nvar engAmber = 219;'
    assert len(_thresholdHits(planted)) == 3


# ---------------------------------------------------------------------------
# 6. CSS and fit.
# ---------------------------------------------------------------------------


def test_spanColour_isOnlyThroughTheDataBandTokens():
    rules = [(sel, body) for sel, body in _engineRules() if "eng-hist" in sel]
    for sel, body in rules:
        if re.search(r"\bfill\s*:\s*var\(--(amber-warn|critical-red)\)", body):
            assert re.search(r'\.eng-hist-span\[data-band="(amber|red)"\]$', sel), sel
        if "eng-hist-line" in sel:
            assert "data-band" not in sel and "amber" not in body and "red)" not in body
    assert _decl(_rule('#engine-card .eng-hist-span[data-band="amber"]'), "fill") == "var(--amber-warn)"
    assert _decl(_rule('#engine-card .eng-hist-span[data-band="red"]'), "fill") == "var(--critical-red)"


def test_statusGrid_isMaxContentThen1fr_withAScoped8pxGap():
    body = _rule("#engine-card .eng-status")
    assert _decl(body, "display") == "grid"
    assert _decl(body, "grid-template-columns") == "max-content 1fr"
    assert _decl(body, "gap") == "var(--eng-stat-gap)"
    assert _px("var(--eng-stat-gap)") == 8


def test_statusTilesAndGraphs_haveNoFixedHeightOrClip():
    """scrollHeight <= clientHeight holds because no tile or graph box is given
    a height to overflow: each is as tall as its content."""
    for sel, body in _engineRules():
        if any(c in sel for c in (".eng-stat", ".eng-hist ", ".eng-hist-head", ".eng-history", ".eng-status")):
            for prop in ("height", "max-height", "overflow"):
                assert _decl(body, prop) is None, (sel, prop)


def test_statusValues_areMonoAtFsLabel_noWrap():
    for selector in ("#engine-card .eng-stat-value", "#engine-card .eng-codes"):
        body = _rule(selector)
        assert _decl(body, "font-family") == "var(--font-mono)", selector
        assert _decl(body, "font-size") == "var(--fs-label)", selector
        assert _decl(body, "white-space") == "nowrap", selector


def test_newLabels_areInTheMichromaSubset():
    for text in ("RUN TIME", "CHECK ENGINE", "COOLANT", "INTAKE AIR", "BATTERY"):
        michromaWidthPx(text, 15)


def _statusFits(count: str, runTime: str = "18:12", note: str = "not read") -> bool:
    gap = _px("var(--eng-stat-gap)")
    runCol = max(
        michromaWidthPx("RUN TIME", 15),
        _monoWidth(runTime, "var(--fs-label)"),
        _monoWidth(note, "var(--fs-meta)"),
    )
    checkCol = _bodyWidthPx() - runCol - gap
    needs = max(
        michromaWidthPx("CHECK ENGINE", 15),
        _monoWidth("OFF", "var(--fs-label)"),
        _monoWidth(f"{count} codes ›", "var(--fs-label)"),
        _monoWidth(note, "var(--fs-meta)"),
    )
    return needs <= checkCol


def test_statusRow_specArithmetic_104Plus160Plus8Is272():
    total = michromaWidthPx("RUN TIME", 15) + michromaWidthPx("CHECK ENGINE", 15) + _px("var(--eng-stat-gap)")
    assert round(total) == 272 and total <= _bodyWidthPx() == 448


@pytest.mark.parametrize("count", ["12", "123"])
def test_statusRow_fitsAt2And3DigitCounts(count: str):
    assert _statusFits(count)


def test_statusFitModel_failsAPlantedOverflow():
    assert not _statusFits("1" * 30)


def _historyHeadFits(window: str) -> bool:
    gap = _px(_decl(_rule("#engine-card .eng-hist-head"), "gap") or "")
    widest = max(michromaWidthPx(label, 15) for _, label in SERIES)
    return widest + gap + _monoWidth("· " + window, "var(--fs-meta)") <= _bodyWidthPx()


def test_historyHead_fitsTheWidestLabelAndWindow():
    assert _historyHeadFits("SINCE 12:59")
    assert not _historyHeadFits("SINCE " + "1" * 40)


def test_historyChart_leavesRoomForTheEndLabel():
    gap = _px(_decl(_rule("#engine-card .eng-hist-row"), "gap") or "")
    end = _monoWidth("230°F", "var(--fs-meta)")
    assert _bodyWidthPx() - gap - end > _bodyWidthPx() / 2
    assert _px(_decl(_rule("#engine-card .eng-hist-chart"), "height") or "") == 46


# ---------------------------------------------------------------------------
# 7. Rule 10 -- the render rule is in the architecture.
# ---------------------------------------------------------------------------


def test_architecture_recordsTheEngineHistoryRenderRule():
    arch = _read(_ARCH)
    assert "US-889-c" in arch
    section = arch[arch.index("US-889-c") :]
    assert "band" in section[:3000] and "never" in section[:3000]
