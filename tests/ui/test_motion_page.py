################################################################################
# File Name: test_motion_page.py
# Purpose/Description: US-892-b (F-127) tests for the Motion card's top two
#   bands (specs/v030-motion-page-design.md s3/s4, layout A, with the Atlas B1-B6
#   and Iris M1-M4 rulings of 2026-10-19): the interim Home card becomes the
#   Motion card at index 4 -- PITCH beside a 15-minute GRADE graph from
#   states/grade-history, then ACCEL/BRAKE and CORNER L/R g now with this
#   drive's peaks from states/imu.peaks. Guarded:
#     1. the fixtures -- present, described, each the REAL provider's payload
#        (buildImuState; GradeHistory replayed from the recorded writes);
#     2. the pure logic (node): pitch sign/rounding/reasons, the g words and
#        numbers, the peak lines, stale, LOADING, and the graph geometry;
#     3. the markup + stylesheet: the slot, the skeleton, tokens only, the
#        brand face only on labels;
#     4. the SHIPPED DOM, painted by the real loops with fetch and the clock
#        stubbed -- the validation rows, the gap, the empty history, no meter.
#   NOT GUARDED: layout on the glass (render_harness resolves the cascade, not
#   boxes): "no clip" and the >= 34 px reads are owed as R15 screenshots on the
#   Pi; here the sizes are pinned through the tokens they bind.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-19    | Rex (US-892-b) | Initial -- Motion pitch, grade graph, g + peaks.
# ================================================================================
################################################################################

"""US-892-b tests for the Motion card's pitch, grade graph and g + peaks."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_CSS = os.path.join(rh.DASHBOARD_DIR, "dashboard.css")
_TOKENS = os.path.join(rh.DASHBOARD_DIR, "..", "tokens.css")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "motion")
_NODE = shutil.which("node")

_NODE_ONLY = pytest.mark.skipif(
    _NODE is None, reason="node not on PATH -- these tests run the shipped browser JS"
)

FIXTURE_NAMES = [
    "climb-accel", "descent-brake", "corner-left", "corner-right",
    "gyro-implausible", "stale-imu", "history-empty-after-restart",
    "peaks-null-after-drive-start",
]

IMU_SEC = 3.0
STALE = {"imuSec": IMU_SEC, "fuelResetConfirmSec": 6}
MINUS = "−"  # U+2212, the true minus (Iris M3)

# The graph's frame (spec s3: 300 x 58; the line spans 236, mockup motion:graph).
GRAPH_W, GRAPH_H, PLOT_W = 300, 58, 236


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _now(name: str) -> int:
    return _ms(_fixture(name)["now"])


def _call(fn: str, *args: Any) -> Any:
    """One exported carousel.js function, called with JSON args."""
    script = (
        'const a = JSON.parse(require("fs").readFileSync(0, "utf-8"));'
        "const c = require(a.js);"
        "const v = c[a.fn].apply(null, a.args);"
        "process.stdout.write(JSON.stringify(v === undefined ? null : v));"
    )
    proc = subprocess.run(
        [_NODE or "node", "-e", script],
        input=json.dumps({"js": _JS, "fn": fn, "args": list(args)}),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _view(name: str, shiftMs: int = 0, imu: Any = None) -> dict[str, Any]:
    payload = _fixture(name)["imu"] if imu is None else imu
    return _call("motionView", payload, _now(name) + shiftMs, IMU_SEC, None)


def _graph(history: Any) -> dict[str, Any]:
    return _call("motionGradeGraph", history)


# ---------------------------------------------------------------------------
# 1. Fixtures -- the provider's real shape, not a typed one.
# ---------------------------------------------------------------------------


def test_fixturesArePresent_andDescribed():
    assert sorted(f[:-5] for f in os.listdir(_FIXTURES)) == sorted(FIXTURE_NAMES)
    for name in FIXTURE_NAMES:
        fx = _fixture(name)
        assert fx["description"], name
        assert fx["now"] and fx["imu"] and "gradeHistory" in fx, name


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_everyImuFixture_isWhatTheRealBridgeBuilderEmits(name: str):
    from pi.sensors.imu_state_bridge import buildImuState

    fx = _fixture(name)
    kwargs = dict(fx["inputs"])
    for key in ("gravity", "linear", "mag"):
        kwargs[key] = tuple(kwargs[key])
    assert buildImuState(**kwargs) == fx["imu"]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_everyHistoryFixture_isTheRealGradeHistoryReplayed(name: str):
    """The recorded writes, folded by the provider's own GradeHistory at the
    shipped 10 s / 900 s, give exactly the published states/grade-history."""
    from pi.sensors.imu_state_bridge import GradeHistory

    fx = _fixture(name)
    history = GradeHistory(intervalSec=10, windowSec=900)
    for ts, grade in fx["historyInputs"]:
        history.observe(ts, grade)
    assert history.snapshot() == fx["gradeHistory"]


def test_theFixturesCarryTheCasesTheyAreNamedFor():
    assert _fixture("gyro-implausible")["imu"]["reasons"]["pitchDeg"] == "gyro_implausible"
    assert _fixture("history-empty-after-restart")["gradeHistory"]["points"] == []
    peaks = _fixture("peaks-null-after-drive-start")["imu"]["peaks"]
    assert [peaks[k] for k in ("accelG", "brakeG", "leftG", "rightG")] == [None] * 4
    assert peaks["sinceTs"]
    points = _fixture("climb-accel")["gradeHistory"]["points"]
    assert None in [p["gradePct"] for p in points]
    assert points[-1]["gradePct"] == 5.0


# ---------------------------------------------------------------------------
# 2. Pure logic
# ---------------------------------------------------------------------------


@_NODE_ONLY
def test_validation_climbAccel_pitchAccelAndPeaks():
    """VC row 1: '+3.1°' 'nose up'; 'ACCEL 0.31 g'; '▲0.31 ▼0.38'."""
    v = _view("climb-accel")
    assert (v["loading"], v["stale"]) == (False, False)
    assert (v["pitch"]["value"] + v["pitch"]["unit"], v["pitch"]["sub"]) == ("+3.1°", "nose up")
    lon = v["lon"]
    assert (lon["label"], lon["value"] + lon["unit"]) == ("ACCEL", "0.31 g")
    assert lon["peak"] == "peak ▲0.31 ▼0.38"
    lat = v["lat"]
    assert (lat["label"], lat["value"] + lat["unit"]) == ("CORNER R", "0.22 g")
    assert lat["peak"] == "peak L0.27 R0.31"


@_NODE_ONLY
def test_validation_descentBrake_isBrakeWithTheMagnitude():
    """VC row 2: gLon -0.22 -> 'BRAKE 0.22 g'; the pitch carries a true minus."""
    v = _view("descent-brake")
    assert (v["lon"]["label"], v["lon"]["value"] + v["lon"]["unit"]) == ("BRAKE", "0.22 g")
    assert (v["pitch"]["value"], v["pitch"]["sub"]) == (MINUS + "2.4", "nose down")


@_NODE_ONLY
@pytest.mark.parametrize(("name", "label", "value"), [
    ("corner-left", "CORNER L", "0.27 g"),
    ("corner-right", "CORNER R", "0.31 g"),
])
def test_corner_theWordIsTheSignOfGLat_plusIsRight(name: str, label: str, value: str):
    lat = _view(name)["lat"]
    assert (lat["label"], lat["value"] + lat["unit"]) == (label, value)


@_NODE_ONLY
@pytest.mark.parametrize(("pitch", "value", "sub"), [
    (3.1, "+3.1", "nose up"),
    (-2.4, MINUS + "2.4", "nose down"),
    (0.04, "0.0", "level"),
    (-0.04, "0.0", "level"),
    (0.0, "0.0", "level"),
    (-0.06, MINUS + "0.1", "nose down"),
    (0.05, "+0.1", "nose up"),
])
def test_pitch_signFromTheRoundedValue_zeroIsLevel(pitch: float, value: str, sub: str):
    """Iris M3: never '−0.0°', never 'nose up' at zero."""
    imu = dict(_fixture("climb-accel")["imu"], pitchDeg=pitch)
    p = _view("climb-accel", imu=imu)["pitch"]
    assert (p["value"], p["unit"], p["sub"], p["none"]) == (value, "°", sub, False)


@_NODE_ONLY
def test_pitch_gyroImplausible_isDashAndTheOneReasonText_amber():
    """Atlas B5: the existing IMU_REASON_TEXT 'gyro implausible'."""
    p = _view("gyro-implausible")["pitch"]
    assert (p["value"], p["unit"], p["sub"], p["none"], p["warn"]) == (
        "--", "", "gyro implausible", True, True
    )


@_NODE_ONLY
def test_pitch_anyOtherNull_isDashPlusItsReason_notAmber():
    imu = dict(_fixture("climb-accel")["imu"], pitchDeg=None,
               reasons={"pitchDeg": "pitch_out_of_range"})
    p = _view("climb-accel", imu=imu)["pitch"]
    assert (p["value"], p["sub"], p["warn"]) == ("--", "pitch beyond range", False)


@_NODE_ONLY
@pytest.mark.parametrize(("gLon", "label", "value"), [
    (0.31, "ACCEL", "0.31"),
    (-0.22, "BRAKE", "0.22"),
    (-0.004, "ACCEL", "0.00"),
    (0.0, "ACCEL", "0.00"),
    (-0.006, "BRAKE", "0.01"),
])
def test_g_twoDecimals_theWordFollowsTheRoundedSign(gLon: float, label: str, value: str):
    """'0.00' is never labelled BRAKE: the word follows what is printed."""
    imu = dict(_fixture("climb-accel")["imu"], gLon=gLon)
    lon = _view("climb-accel", imu=imu)["lon"]
    assert (lon["label"], lon["value"]) == (label, value)


@_NODE_ONLY
def test_g_null_isDashPlusReason_andNamesNoDirection():
    imu = dict(_fixture("climb-accel")["imu"], gLon=None, gLat=None,
               reasons={"gLon": "tilt_unresolved", "gLat": "tilt_unresolved"})
    v = _view("climb-accel", imu=imu)
    assert (v["lon"]["label"], v["lon"]["value"], v["lon"]["note"]) == (
        "ACCEL BRAKE", "--", "orientation unresolved"
    )
    assert (v["lat"]["label"], v["lat"]["value"], v["lat"]["note"]) == (
        "CORNER", "--", "orientation unresolved"
    )


@_NODE_ONLY
def test_peaks_nullAfterDriveStart_areDashes():
    v = _view("peaks-null-after-drive-start")
    assert v["lon"]["peak"] == "peak ▲-- ▼--"
    assert v["lat"]["peak"] == "peak L-- R--"


@_NODE_ONLY
def test_peaks_aSingleNullPeak_isDashBesideTheOthers():
    """Iris M1: 'peak ▲-- ▼0.38'."""
    imu = _fixture("climb-accel")["imu"]
    imu = dict(imu, peaks=dict(imu["peaks"], accelG=None))
    assert _view("climb-accel", imu=imu)["lon"]["peak"] == "peak ▲-- ▼0.38"


@_NODE_ONLY
def test_peaks_aLegacyPayloadWithNoPeaksBlock_isAllDashes():
    imu = {k: v for k, v in _fixture("climb-accel")["imu"].items() if k != "peaks"}
    v = _view("climb-accel", imu=imu)
    assert (v["lon"]["peak"], v["lat"]["peak"]) == ("peak ▲-- ▼--", "peak L-- R--")


@_NODE_ONLY
def test_validation_stale_3point5sDims_2point5sLive_strictGreaterThan():
    """The one IMU key shared with NAV; strict age > imuSec. The values are
    kept (dimmed), never blanked."""
    assert _view("stale-imu")["stale"] is True
    assert _view("stale-imu", shiftMs=-1000)["stale"] is False
    assert _view("stale-imu", shiftMs=-500)["stale"] is False  # exactly 3.0 s
    v = _view("stale-imu")
    assert v["pitch"]["value"] == "+3.1"


@_NODE_ONLY
@pytest.mark.parametrize("ts", [None, "not a time"])
def test_stale_anUndatedPayload_isStale(ts: Any):
    """Iris M4: ts null or unparseable is stale."""
    imu = dict(_fixture("climb-accel")["imu"], ts=ts)
    assert _view("climb-accel", imu=imu)["stale"] is True


@_NODE_ONLY
def test_noFeed_afterTheBound_isDashPlusNoMotionFeed_notStale():
    v = _call("motionView", None, _now("climb-accel"), IMU_SEC, None)
    assert v["loading"] is False and v["stale"] is False
    assert (v["pitch"]["value"], v["pitch"]["sub"]) == ("--", "no motion feed")
    assert (v["lon"]["value"], v["lon"]["note"]) == ("--", "no motion feed")


@_NODE_ONLY
def test_beforeTheFirstRead_isUs700Loading_untilTheBound():
    """Atlas Q-1: bounded LOADING via loadPhase/loadingTile, then '--' + reason."""
    grace = _call("loadingGraceMs")
    early = _call("motionView", None, 0, IMU_SEC, 0)
    assert early["loading"] is True
    assert (early["tile"]["value"], early["tile"]["level"]) == ("LOADING", "loading")
    assert _call("motionView", None, 0, IMU_SEC, grace)["loading"] is False


# --- the grade graph --------------------------------------------------------


def _y(rangePct: float, pct: float) -> float:
    pad = 4
    return round(pad + (GRAPH_H - 2 * pad) * (1 - (pct + rangePct) / (2 * rangePct)), 1)


@_NODE_ONLY
def test_validation_graphEndLabel_isTheLastNonNullPoint_atTheEndDot():
    """VC row 3: last non-null point +5.0 -> end label '+5.0%' at the end dot;
    line, dot and label on ONE scale."""
    g = _graph(_fixture("climb-accel")["gradeHistory"])
    assert g["empty"] is False
    end = g["end"]
    assert end["label"] == "+5.0%"
    assert (end["x"], end["y"]) == (PLOT_W, _y(g["rangePct"], 5.0))
    assert end["labelY"] == round(end["y"] + 5, 1)
    last = g["segments"][-1].split(" ")[-1]
    assert last == f"{end['x']:g},{end['y']:g}"
    assert g["zeroY"] == _y(g["rangePct"], 0.0)


@_NODE_ONLY
def test_graph_aNullPointEndsTheSegment_neverALineAcrossTheGap():
    """Iris M3: each null ENDS the polyline; the next real point starts anew."""
    hist = _fixture("climb-accel")["gradeHistory"]
    g = _graph(hist)
    runs = [len(seg.split(" ")) for seg in g["segments"]]
    grades = [p["gradePct"] for p in hist["points"]]
    expected, n = [], 0
    for v in grades + [None]:
        if v is None:
            if n:
                expected.append(n)
            n = 0
        else:
            n += 1
    assert runs == expected == [3, 5]


@_NODE_ONLY
def test_graph_newestPointAtTheRightEdge_slotsFromThePublishedWindow():
    """intervalS / windowS are the PROVIDER's keys (Atlas B4): 900 / 10 = 90
    slots, the newest at PLOT_W, so a short history sits at the right."""
    g = _graph(_fixture("climb-accel")["gradeHistory"])
    xs = [float(p.split(",")[0]) for seg in g["segments"] for p in seg.split(" ")]
    step = PLOT_W / 89
    assert xs[-1] == PLOT_W
    assert xs[0] == round(PLOT_W - 9 * step, 1)


@_NODE_ONLY
def test_graph_descentLabel_carriesATrueMinus():
    g = _graph(_fixture("descent-brake")["gradeHistory"])
    assert g["end"]["label"] == MINUS + "4.2%"


@_NODE_ONLY
@pytest.mark.parametrize("history", [
    {"points": [], "windowS": 900, "intervalS": 10, "ts": None},
    {"points": [{"ts": "2026-10-20T15:00:10Z", "gradePct": None}] * 3,
     "windowS": 900, "intervalS": 10, "ts": "2026-10-20T15:00:30Z"},
    None,
])
def test_graph_emptyOrAllNull_isTheTypedAbsence_neverAFlatLine(history: Any):
    g = _graph(history)
    assert g["empty"] is True
    assert g["text"] == "no grade history yet"
    assert g["segments"] == [] and g["end"] is None
    assert g["zeroY"] == GRAPH_H / 2


@_NODE_ONLY
@pytest.mark.parametrize(("peak", "rangePct"), [(0.4, 4), (3.9, 4), (4.1, 6), (5.0, 6), (9.2, 10)])
def test_graph_scaleIsSymmetric_growsInTwoPercentSteps_neverUnderFour(peak: float, rangePct: int):
    hist = {"points": [{"ts": "t", "gradePct": -0.1}, {"ts": "t", "gradePct": peak}],
            "windowS": 900, "intervalS": 10}
    assert _graph(hist)["rangePct"] == rangePct


# ---------------------------------------------------------------------------
# 3. Markup + stylesheet
# ---------------------------------------------------------------------------


def _sectionTags(html: str) -> list[str]:
    return re.findall(r'<section class="card"[^>]*>', html, re.S)


def _motionMarkup() -> str:
    html = _read(_HTML)
    start = html.index('id="motion-card"')
    return html[start:html.index("</section>", start)]


def test_slot_motionIsIndexFour_afterNavEngineFuel():
    """Card order (E-2): Driving, NAV, Engine, Fuel, Motion, Alerts, ..."""
    tags = _sectionTags(_read(_HTML))
    labels = [re.search(r'aria-label="([^"]+)"', t).group(1) for t in tags]
    assert labels[:6] == ["Driving", "Navigation", "Engine", "Fuel", "Motion", "Alerts"]
    tag = tags[4]
    assert 'id="motion-card"' in tag and 'data-page-name="MOTION"' in tag
    for attr in ("data-state", "data-idle-home", "data-face"):
        assert attr not in tag, attr


def test_theInterimHomeCardIsGone():
    html = _read(_HTML)
    assert 'id="home-card"' not in html
    assert 'aria-label="Home"' not in html


def test_skeleton_notReadFaces_literalPeakGlyphs_gradeLabelWithoutMiddleDot():
    """The ▲ ▼ are authored as literal characters (test_probe_utf8_roundtrip);
    the label has no '·' -- the Michroma subset lacks it (Iris G-4)."""
    m = _motionMarkup()
    assert "peak ▲-- ▼--" in m and "peak L-- R--" in m
    assert "GRADE  LAST 15 MIN" in m and "·" not in m
    assert 'viewBox="0 0 300 58"' in m
    assert m.count('class="motion-value">--<') == 3


def _motionRules() -> dict[str, str]:
    return {r.selector.strip(): r.declarations for r in rh.parseCss(_read(_CSS))
            if r.selector.strip().startswith("#motion-card")}


def test_css_tokensOnly_noHexLiteral():
    for selector, body in _motionRules().items():
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), selector


def test_css_literalPxOnlyInTheScopedGeometry_andNeverTheBandBudgetNumbers():
    rules = _motionRules()
    for selector, body in rules.items():
        if selector == "#motion-card":
            continue
        assert not re.search(r"\b\d+(\.\d+)?px", body), selector
    for value in re.findall(r"(\d+(?:\.\d+)?)px", rules["#motion-card"]):
        assert value not in ("28", "24", "14"), value


def test_css_valuesBindFsPrimary_atLeast34px():
    tokens = _read(_TOKENS)
    primary = float(re.search(r"--fs-primary:\s*(\d+)px", tokens).group(1))
    assert primary >= 34
    assert "font-size: var(--fs-primary)" in _motionRules()["#motion-card .motion-value"]


def test_css_onlyTheLabelsAreMichroma_andEachSets400NoSynthesis():
    """Iris G-4 / Atlas C3: the peak glyphs, minus and degree sign inherit the
    body mono; no rule here names --font-body (it is not a token)."""
    for selector, body in _motionRules().items():
        assert "--font-body" not in body, selector
        if "var(--font-display)" in body:
            assert selector == "#motion-card .motion-label", selector
            assert "font-weight: 400" in body and "font-synthesis: none" in body
        else:
            assert "font-family" not in body, selector


def test_css_staleDimsBothBands():
    rules = _motionRules()
    assert "opacity: var(--motion-stale-opacity)" in rules[
        '#motion-card[data-stale="true"] .motion-band'
    ]


def test_css_peakLineIsLabelTierSecondary_neverColoured():
    body = _motionRules()["#motion-card .motion-peak"]
    assert "font-size: var(--fs-label)" in body and "color: var(--text-secondary)" in body


def test_js_noGBandColouring_andTheClientTrendIsGone():
    """G_AMBER_G retired with the g tile; the client-side grade trend too."""
    js = _read(_JS)
    for name in ("G_AMBER_G", "pushGradeTrend", "GRADE_TREND_WINDOW_SEC",
                 "smoothedImuView", "renderHomeCard", "homeFace"):
        assert name not in js, name


def test_js_motionRepaintsOnTheImuLoop_andPollsGradeHistoryOnTheTick():
    js = _read(_JS)
    imuTick = js[js.index("      async function imuTick()"):]
    imuTick = imuTick[:imuTick.index("\n      }\n")]
    assert "renderMotion(" in imuTick
    assert 'lastGradeHistory = await stateOnce("grade-history")' in js


# ---------------------------------------------------------------------------
# 4. The shipped DOM
# ---------------------------------------------------------------------------


def _find(node: Any, pred) -> list[dict[str, Any]]:
    if not isinstance(node, dict):
        return []
    out = [node] if pred(node) else []
    for child in node.get("children", []) or []:
        out += _find(child, pred)
    return out


def _classes(node: dict[str, Any]) -> list[str]:
    return (node.get("attrs", {}).get("class") or "").split()


def _rawText(node: dict[str, Any]) -> str:
    return "".join(c["text"] if "text" in c else _rawText(c)
                   for c in node.get("children", []))


def _textOf(node: dict[str, Any]) -> str:
    return _rawText(node).strip()


def _card(dom: dict[str, Any]) -> dict[str, Any]:
    roots = dom["tree"] if isinstance(dom["tree"], list) else [dom["tree"]]
    hits = [n for r in roots for n in _find(r, lambda n: n.get("attrs", {}).get("id") == "motion-card")]
    assert len(hits) == 1
    return hits[0]


def _one(node: dict[str, Any], cls: str) -> dict[str, Any]:
    hits = _find(node, lambda n: cls in _classes(n))
    assert len(hits) == 1, (cls, len(hits))
    return hits[0]


def _boot(name: str, shiftMs: int = 0, routes: dict[str, Any] | None = None) -> dict[str, Any]:
    fx = _fixture(name)
    r = {"/imu": fx["imu"], "/grade-history": fx["gradeHistory"]}
    if routes is not None:
        r = routes
    return _card(rh.runDashboard(routes=r, nowMs=_now(name) + shiftMs,
                                 steps=[{"flush": 4}], displayStale=STALE))


def _cell(card: dict[str, Any], cls: str) -> str:
    return " ".join(_textOf(n) for n in _one(card, cls).get("children", [])
                    if "hidden" not in n.get("attrs", {}) and _textOf(n))


@_NODE_ONLY
def test_dom_validation_climbAccel():
    card = _boot("climb-accel")
    assert card["attrs"]["data-stale"] == "false"
    assert _cell(card, "motion-pitch") == "PITCH +3.1° nose up"
    assert _cell(card, "motion-lon") == "ACCEL 0.31 g peak ▲0.31 ▼0.38"
    assert _cell(card, "motion-lat") == "CORNER R 0.22 g peak L0.27 R0.31"


@_NODE_ONLY
def test_dom_validation_descentBrake():
    card = _boot("descent-brake")
    assert _cell(card, "motion-lon").startswith("BRAKE 0.22 g")
    assert _cell(card, "motion-pitch") == f"PITCH {MINUS}2.4° nose down"


@_NODE_ONLY
def test_dom_validation_gradeEndLabelAtTheEndDot_andTheGapIsTwoLines():
    card = _boot("climb-accel")
    svg = _one(card, "motion-graph")
    lines = _find(svg, lambda n: "motion-graph-line" in _classes(n))
    dot = _one(svg, "motion-graph-dot")
    label = _one(svg, "motion-graph-end")
    assert len(lines) == 2
    assert _textOf(label) == "+5.0%"
    assert lines[-1]["attrs"]["points"].split(" ")[-1] == (
        dot["attrs"]["cx"] + "," + dot["attrs"]["cy"]
    )
    assert not _find(svg, lambda n: "motion-graph-empty" in _classes(n))


@_NODE_ONLY
def test_dom_historyEmptyAfterRestart_typedAbsenceAboveTheZeroLine_noLine():
    card = _boot("history-empty-after-restart")
    svg = _one(card, "motion-graph")
    empty = _one(svg, "motion-graph-empty")
    zero = _one(svg, "motion-graph-zero")
    assert _textOf(empty) == "no grade history yet"
    assert float(empty["attrs"]["y"]) < float(zero["attrs"]["y1"])
    assert not _find(svg, lambda n: _classes(n)[:1] in (["motion-graph-line"], ["motion-graph-dot"]))


@_NODE_ONLY
def test_dom_gyroImplausible_dashAndReason_amberFlag():
    card = _boot("gyro-implausible")
    pitch = _one(card, "motion-pitch")
    assert pitch["attrs"]["data-warn"] == "true"
    assert _cell(card, "motion-pitch") == "PITCH -- gyro implausible"


@_NODE_ONLY
def test_dom_peaksNullAfterDriveStart():
    card = _boot("peaks-null-after-drive-start")
    assert _textOf(_one(_one(card, "motion-lon"), "motion-peak")) == "peak ▲-- ▼--"
    assert _textOf(_one(_one(card, "motion-lat"), "motion-peak")) == "peak L-- R--"


@_NODE_ONLY
def test_dom_validation_stale_dimsTheCard_valuesKept():
    card = _boot("stale-imu")
    assert card["attrs"]["data-stale"] == "true"
    assert _cell(card, "motion-pitch") == "PITCH +3.1° nose up"
    assert _boot("stale-imu", shiftMs=-1000)["attrs"]["data-stale"] == "false"


@_NODE_ONLY
def test_dom_validation_noGMeterDotOrTrail():
    """VC row 4 (US-733): no meter / dot / trail element anywhere in the DOM."""
    dom = rh.runDashboard(
        routes={"/imu": _fixture("climb-accel")["imu"],
                "/grade-history": _fixture("climb-accel")["gradeHistory"]},
        nowMs=_now("climb-accel"), steps=[{"flush": 4}], displayStale=STALE,
    )
    roots = dom["tree"] if isinstance(dom["tree"], list) else [dom["tree"]]
    bad = [c for r in roots for n in _find(r, lambda n: True) for c in _classes(n)
           if re.search(r"meter|trail|^imu-|^live-", c)]
    assert bad == []
    card = _card(dom)
    circles = _find(card, lambda n: n.get("tag") == "circle")
    assert [_classes(c) for c in circles] == [["motion-graph-dot"]]


@_NODE_ONLY
def test_dom_beforeTheFirstRead_isLoading_thenDashAndReason():
    early = _boot("climb-accel", routes={})
    loading = _one(early, "motion-loading")
    assert "hidden" not in loading["attrs"]
    assert "LOADING" in _textOf(loading)
    bands = _find(early, lambda n: "motion-band" in _classes(n))
    assert bands and all("hidden" in b["attrs"] for b in bands)
    late = _card(rh.runDashboard(
        routes={}, nowMs=_now("climb-accel"),
        steps=[{"flush": 4}, {"advanceMs": _call("loadingGraceMs") + 4000}, {"flush": 4}],
        displayStale=STALE,
    ))
    assert "hidden" in _one(late, "motion-loading")["attrs"]
    assert _cell(late, "motion-pitch") == "PITCH -- no motion feed"


@_NODE_ONLY
def test_dom_theBarNamesTheCardMotion():
    card = _boot("climb-accel")
    assert card["attrs"]["data-page-name"] == "MOTION"
    assert card["attrs"]["aria-label"] == "Motion"
