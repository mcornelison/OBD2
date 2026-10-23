################################################################################
# File Name: test_nav_page.py
# Purpose/Description: US-896-a (F-160) tests for the NAV card's heading half
#   (specs/v030-navigation-page-design.md s3/s4.1/s4.2, layout A): a new card at
#   index 1 whose hero is the bearing tape (90 deg window, 5/15/45 ticks, centre
#   hairline), the zero-padded digits and an 8-point compass point (R25), the
#   1 s shortest-arc glide, and the five heading states with their badges.
#   Guarded:
#     1. the fixtures -- present, described, each the REAL buildImuState's
#        payload (the two boundary bearings patched, stated);
#     2. the pure logic (node probe): the 8-point point, the digits, the heading
#        states in precedence order, the stale key, the glide, the tape;
#     3. the markup + stylesheet: the slot, the skeleton, tokens only;
#     4. the SHIPPED DOM, painted by the real motion loop with fetch and the
#        clock stubbed -- digits, point, badge, and the tape's presence/absence.
#   NOT GUARDED: layout on the glass (render_harness resolves the cascade, not
#   boxes): "no clip" and the >= 34 px reads are owed as R15 screenshots on the
#   Pi; here the sizes are pinned through the tokens they bind.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-18    | Rex (US-896-a) | Initial -- NAV bearing tape, digits, point,
#                                glide and heading states.
# 2026-10-18    | Rex (US-896-b) | The bottom row: GRADE (states/imu) and the
#                                trip (system-status drive: distance, elapsed,
#                                THIS DRIVE / SINCE h:mm / LAST DRIVE).
# 2026-10-19    | Rex (US-911) | NAV's badge note and Motion's COMPASS absent
#                                text built from one CALIBRATION_ABSENT_TEXT.
# ================================================================================
################################################################################

"""US-896-a tests for the NAV card's bearing tape, digits, point and states."""

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

from common.config.validator import DEFAULTS  # noqa: E402
from tests.ui.test_carousel_kebab_always_visible import _driving  # noqa: E402
from tests.ui.test_engine_page import _classes, _ms, _textOf  # noqa: E402

_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_CSS = os.path.join(rh.DASHBOARD_DIR, "dashboard.css")
_TOKENS = os.path.join(rh.DASHBOARD_DIR, "..", "tokens.css")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "nav")
_NODE = shutil.which("node")

_NODE_ONLY = pytest.mark.skipif(
    _NODE is None, reason="node not on PATH -- these tests run the shipped browser JS"
)

FIXTURE_NAMES = [
    "trusted-247", "boundary-22.5", "boundary-337.5", "uncalibrated",
    "legacy-engine-no-flag", "unseeded", "dead-mag", "stale-imu",
    "wrap-350-a", "wrap-350-b", "parked-engine-off",
]

IMU_SEC = 3.0
STALE = {"imuSec": IMU_SEC, "fuelResetConfirmSec": 6}


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _imu(name: str) -> dict[str, Any]:
    return _fixture(name)["imu"]


def _now(name: str) -> int:
    return _ms(_fixture(name)["now"])


# Calls one exported carousel.js function with JSON args and DISPLAY_STALE set
# (or left absent) -- the global is read at call time, as in the kiosk.
_CALL = """
const args = JSON.parse(require("fs").readFileSync(0, "utf-8"));
if (args.stale !== undefined) globalThis.DISPLAY_STALE = args.stale;
const c = require(args.js);
const v = c[args.fn].apply(null, args.args);
process.stdout.write(JSON.stringify(v === undefined ? null : v));
"""


def _call(fn: str, *args: Any, stale: Any = None) -> Any:
    payload: dict[str, Any] = {"js": _JS, "fn": fn, "args": list(args)}
    if stale is not None:
        payload["stale"] = stale
    proc = subprocess.run(
        [_NODE or "node", "-e", _CALL], input=json.dumps(payload),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# Runs a sequence of readings through the glide (navHeadingView -> navGlideStep)
# and samples the drawn bearing: each event is {imu, nowMs} (a paint with that
# payload) or {sampleMs} (the drawn bearing at that instant, no new paint).
_GLIDE = """
const args = JSON.parse(require("fs").readFileSync(0, "utf-8"));
const c = require(args.js);
let glide = c.navGlideInit();
let last = null;
const out = [];
for (const ev of args.events) {
  if (ev.imu !== undefined) {
    const view = c.navHeadingView(ev.imu, ev.nowMs, args.imuSec);
    glide = c.navGlideStep(glide, view, ev.nowMs, args.reduced === true);
    last = ev.nowMs;
    out.push({state: view.state, drawn: c.navDrawnDeg(glide, ev.nowMs)});
  } else {
    out.push({drawn: c.navDrawnDeg(glide, ev.sampleMs),
              gliding: c.navGliding(glide, ev.sampleMs)});
  }
}
process.stdout.write(JSON.stringify(out));
"""


def _glide(events: list[dict[str, Any]], reduced: bool = False) -> list[dict[str, Any]]:
    payload = {"js": _JS, "events": events, "imuSec": IMU_SEC, "reduced": reduced}
    proc = subprocess.run(
        [_NODE or "node", "-e", _GLIDE], input=json.dumps(payload),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _arc(a: float, b: float) -> float:
    """Unsigned circular distance between two bearings."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _view(name: str, ageShiftMs: int = 0) -> dict[str, Any]:
    return _call("navHeadingView", _imu(name), _now(name) + ageShiftMs, IMU_SEC)


# ---------------------------------------------------------------------------
# 1. Fixtures
# ---------------------------------------------------------------------------


def test_fixturesArePresent_andDescribed():
    for name in FIXTURE_NAMES:
        fx = _fixture(name)
        assert fx["description"], name
        assert fx["now"] and fx["imu"], name


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_everyFixture_isWhatTheRealBridgeBuilderEmits(name: str):
    """The page is tested against the provider's real shape, not a typed one.
    The bridge publishes whole degrees, so the two sector boundaries (22.5 and
    337.5) can only ever be DRAWN bearings mid-glide; those fixtures patch
    headingDeg and say so in `drawnHeadingDeg`."""
    from pi.sensors.imu_state_bridge import buildImuState

    fx = _fixture(name)
    kwargs = dict(fx["inputs"])
    for key in ("gravity", "linear", "mag"):
        if kwargs.get(key) is not None:
            kwargs[key] = tuple(kwargs[key])
    built = buildImuState(**kwargs)
    if "drawnHeadingDeg" in fx:
        built["headingDeg"] = fx["drawnHeadingDeg"]
    assert built == fx["imu"]


def test_theLegacyFixture_carriesNoCalibrationKey_andTheUnseededOneIsTyped():
    assert "headingCalibrated" not in _imu("legacy-engine-no-flag")
    assert _imu("unseeded")["reasons"]["headingDeg"] == "heading_unseeded"
    assert _imu("dead-mag")["reasons"]["headingDeg"] == "no_mag_reading"


# ---------------------------------------------------------------------------
# 2. Pure logic
# ---------------------------------------------------------------------------


@_NODE_ONLY
@pytest.mark.parametrize(
    ("deg", "point"),
    [(247, "SW"), (22.5, "NE"), (337.5, "N"), (0, "N"), (22.4, "N"), (67.5, "E"),
     (90, "E"), (135, "SE"), (180, "S"), (202.5, "SW"), (270, "W"), (315, "NW"),
     (337.4, "NW"), (359.9, "N"), (-90, "W"), (720, "N")],
)
def test_compassPoint8_isEightPoint_roundHalfUp_wrappingToNorth(deg: float, point: str):
    assert _call("compassPoint8", deg) == point


@_NODE_ONLY
def test_compassPoint8_null_isNull_andHeadingCardinalIsStillSixteenPoint():
    """The interim card's 16-point function is not converted in place."""
    assert _call("compassPoint8", None) is None
    assert _call("headingCardinal", 247) == "WSW"


@_NODE_ONLY
@pytest.mark.parametrize(
    ("deg", "text"),
    [(247, "247°"), (5, "005°"), (47, "047°"), (0, "000°"), (359.6, "000°"),
     (359.4, "359°"), (-13, "347°"), (None, "---°")],
)
def test_fmtHeadingDigits_zeroPaddedThreeDigits(deg: Any, text: str):
    assert _call("fmtHeadingDigits", deg) == text


@_NODE_ONLY
@pytest.mark.parametrize(
    ("a", "b", "arc"), [(350, 10, 20), (10, 350, -20), (0, 180, 180), (90, 45, -45)]
)
def test_shortestArc_crossesNorth_neverTheLongWay(a: float, b: float, arc: float):
    assert _call("shortestArcDeg", a, b) == arc


@_NODE_ONLY
def test_state_trusted247_noBadge_tapeCentredOn247():
    view = _view("trusted-247")
    assert view["state"] == "trusted"
    assert view["tape"] is True
    assert view["headingDeg"] == 247
    assert view["badge"] is None and view["badgeNote"] is None


@_NODE_ONLY
def test_state_uncalibrated_tapeNormal_badgeNotCalibrated():
    view = _view("uncalibrated")
    assert (view["state"], view["tape"], view["badge"]) == ("uncalibrated", True, "NOT CALIBRATED")
    assert view["headingDeg"] == 247


@_NODE_ONLY
def test_state_legacyEngine_dashPlusReason_neverNotCalibrated():
    view = _view("legacy-engine-no-flag")
    assert (view["state"], view["tape"], view["badge"]) == ("legacy", True, "--")
    assert view["badgeNote"] == "calibration not published"
    assert "not calib" not in json.dumps(view).lower()


@_NODE_ONLY
def test_state_legacyEngine_aPublishedReason_isTheNote():
    imu = dict(_imu("legacy-engine-no-flag"))
    imu["reasons"] = dict(imu["reasons"], headingCalibrated="no_source")
    view = _call("navHeadingView", imu, _now("legacy-engine-no-flag"), IMU_SEC)
    assert (view["badge"], view["badgeNote"]) == ("--", "no source")


@_NODE_ONLY
def test_state_unseeded_startingUp_fromTheOneReasonTable():
    view = _view("unseeded")
    assert (view["state"], view["tape"], view["headingDeg"]) == ("unseeded", True, None)
    assert view["badge"] == "STARTING UP"
    # The text lives in the ONE reason table (imuReason's IMU_REASON_TEXT).
    src = _read(_JS)
    table = src[src.index("var IMU_REASON_TEXT = {"):]
    table = table[: table.index("};")]
    assert 'heading_unseeded: "starting up"' in table


@_NODE_ONLY
def test_state_deadMag_noTape_noHeadingPlusReason():
    view = _view("dead-mag")
    assert (view["state"], view["tape"], view["headingDeg"]) == ("dead", False, None)
    assert view["reason"] == "no compass reading"
    assert view["badge"] is None


@_NODE_ONLY
@pytest.mark.parametrize(
    ("payload", "reason"),
    [(None, "no motion feed"),
     ({"available": False, "ts": "2026-10-20T15:12:29Z", "headingDeg": None,
       "reasons": {"headingDeg": "sensor_absent"}}, "sensor not detected"),
     ({"available": True, "headingDeg": 247.0, "reasons": {}}, "no read time")],
    ids=["no-file", "unwired", "undated"],
)
def test_state_noFile_unwired_undated_areDead(payload: Any, reason: str):
    view = _call("navHeadingView", payload, _ms("2026-10-20T15:12:30Z"), IMU_SEC)
    assert (view["state"], view["tape"], view["reason"]) == ("dead", False, reason)


@_NODE_ONLY
def test_validation_stale_2point5sLive_3point5sNoUpdate3s():
    live = _view("stale-imu", ageShiftMs=-1000)  # the fixture is 3.5 s old
    assert (live["state"], live["badge"]) == ("trusted", None)
    stale = _view("stale-imu")
    assert (stale["state"], stale["tape"], stale["badge"]) == ("stale", True, "NO UPDATE 3 s")
    assert stale["headingDeg"] == 247


@_NODE_ONLY
def test_stale_isStrictlyGreaterThan_andTheBadgeCountsUp():
    ts = _ms(_imu("stale-imu")["ts"])
    imu = _imu("stale-imu")
    assert _call("navHeadingView", imu, ts + 3000, IMU_SEC)["state"] == "trusted"
    assert _call("navHeadingView", imu, ts + 3001, IMU_SEC)["badge"] == "NO UPDATE 3 s"
    assert _call("navHeadingView", imu, ts + 12400, IMU_SEC)["badge"] == "NO UPDATE 12 s"


@_NODE_ONLY
def test_stale_winsOverStartingUp_andOverNotCalibrated_butNotOverDead():
    """First match wins (spec s4.2)."""
    late = 5000
    for name in ("unseeded", "uncalibrated", "legacy-engine-no-flag"):
        assert _view(name, ageShiftMs=late)["state"] == "stale", name
    assert _view("dead-mag", ageShiftMs=late)["state"] == "dead"


@_NODE_ONLY
def test_navStale_readsTheOneImuKey_resolveImuStaleSec():
    """No second key: the renderer passes resolveImuStaleSec(DISPLAY_STALE)."""
    src = _read(_JS)
    body = src[src.index("function renderNav(nowMs)"):]
    body = body[: body.index("\n      }\n")]
    assert "resolveImuStaleSec(global && global.DISPLAY_STALE)" in body
    assert DEFAULTS["pi.display.stale.imuSec"] == IMU_SEC
    assert _call("resolveImuStaleSec", None) == IMU_SEC


@_NODE_ONLY
def test_validation_wrap350to10_at500ms_drawnIsZero_neverVia180():
    a, b = _imu("wrap-350-a"), _imu("wrap-350-b")
    t0 = _now("wrap-350-b")
    samples = [{"sampleMs": t0 + ms} for ms in range(0, 1001, 50)]
    out = _glide([{"imu": a, "nowMs": t0 - 1000}, {"imu": b, "nowMs": t0}, *samples])
    assert out[0]["drawn"] == 350  # the first reading steps (nothing drawn yet)
    drawn = [s["drawn"] for s in out[2:]]
    assert drawn[10] == 0  # 500 ms: moved +10 of +20
    # Every frame sits on the short arc through north, never past 180.
    assert all(_arc(d, 0) <= 10 + 1e-9 for d in drawn), drawn
    assert drawn[-1] == 10 and out[-1]["gliding"] is False


@_NODE_ONLY
def test_glide_reachesTheTargetWithinOneSecond_easeInOut():
    a = dict(_imu("trusted-247"), headingDeg=200.0)
    b = _imu("trusted-247")
    t0 = _now("trusted-247")
    out = _glide([{"imu": a, "nowMs": t0}, {"imu": b, "nowMs": t0},
                  {"sampleMs": t0 + 250}, {"sampleMs": t0 + 999}, {"sampleMs": t0 + 1000}])
    quarter, nearEnd, end = out[2]["drawn"], out[3]["drawn"], out[4]["drawn"]
    assert 200 < quarter < 200 + 47 / 4  # ease-in: under a quarter of the arc at 25 %
    assert 246 < nearEnd < 247
    assert end == 247 and out[4]["gliding"] is False


@_NODE_ONLY
def test_glide_aReadingMidGlide_restartsFromTheDrawnBearing():
    base = _imu("trusted-247")
    t0 = _now("trusted-247")
    out = _glide([
        {"imu": dict(base, headingDeg=0.0), "nowMs": t0},
        {"imu": dict(base, headingDeg=40.0), "nowMs": t0},
        {"imu": dict(base, headingDeg=80.0), "nowMs": t0 + 500},
        {"sampleMs": t0 + 500}, {"sampleMs": t0 + 1500},
    ])
    # At 500 ms the first glide had drawn 20; the new glide starts THERE.
    assert out[2]["drawn"] == 20
    assert out[3]["drawn"] == 20
    assert out[4]["drawn"] == 80


@_NODE_ONLY
def test_glide_theSameReadingAgain_isNotANewGlide():
    base = _imu("trusted-247")
    t0 = _now("trusted-247")
    out = _glide([
        {"imu": dict(base, headingDeg=0.0), "nowMs": t0},
        {"imu": dict(base, headingDeg=40.0), "nowMs": t0},
        {"imu": dict(base, headingDeg=40.0), "nowMs": t0 + 500},
        {"sampleMs": t0 + 1000},
    ])
    assert out[3]["drawn"] == 40  # finished on the first glide's clock


@_NODE_ONLY
def test_glide_reducedMotion_steps():
    base = _imu("trusted-247")
    t0 = _now("trusted-247")
    out = _glide([{"imu": dict(base, headingDeg=350.0), "nowMs": t0},
                  {"imu": dict(base, headingDeg=10.0), "nowMs": t0},
                  {"sampleMs": t0 + 1}], reduced=True)
    assert out[1]["drawn"] == 10 and out[2]["drawn"] == 10
    assert out[2]["gliding"] is False


@_NODE_ONLY
def test_glide_stale_freezesTheTape_andDeadDropsIt():
    base = _imu("trusted-247")
    t0 = _now("trusted-247")
    out = _glide([
        {"imu": base, "nowMs": t0},
        {"imu": base, "nowMs": t0 + 5000},          # stale: frozen at 247
        {"sampleMs": t0 + 9000},
        {"imu": _imu("dead-mag"), "nowMs": t0},     # dead: no bearing at all
    ])
    assert out[1]["state"] == "stale" and out[1]["drawn"] == 247
    assert out[2]["drawn"] == 247 and out[2]["gliding"] is False
    assert out[3]["state"] == "dead" and out[3]["drawn"] is None


@_NODE_ONLY
def test_glide_aBootIntoAStaleFile_stillShowsItsLastBearing():
    out = _glide([{"imu": _imu("stale-imu"), "nowMs": _now("stale-imu")}])
    assert out[0] == {"state": "stale", "drawn": 247}


@_NODE_ONLY
def test_tape_ninetyDegreeWindow_fiveFifteenFortyFiveTicks_lettersAt45():
    tape = _call("navTape", 247)
    assert tape["available"] is True and tape["spanDeg"] == 90
    degs = [t["deg"] for t in tape["ticks"]]
    assert degs == list(range(205, 295, 5))  # 202..292 on the 5-degree lattice
    for t in tape["ticks"]:
        want = "major" if t["deg"] % 45 == 0 else "minor" if t["deg"] % 15 == 0 else "fine"
        assert t["tier"] == want, t
        assert (t["label"] is not None) == (t["deg"] % 45 == 0), t
    assert {t["label"] for t in tape["ticks"] if t["label"]} == {"SW", "W"}


@_NODE_ONLY
def test_tape_direction_clockwiseIsRight_acrossNorth():
    """The interim tape's direction contract, on the NAV lattice."""
    tape = _call("navTape", 350)
    byDeg = {t["deg"]: t for t in tape["ticks"]}
    assert byDeg[0]["offset"] > 0 and byDeg[0]["label"] == "N"
    assert byDeg[315]["offset"] < 0 and byDeg[315]["label"] == "NW"
    assert byDeg[350]["offset"] == 0
    assert min(t["offset"] for t in tape["ticks"]) >= -1
    assert max(t["offset"] for t in tape["ticks"]) <= 1


@_NODE_ONLY
def test_tape_noBearing_isNoTape_andTheInterimLatticeIsUnchanged():
    assert _call("navTape", None)["available"] is False
    interim = _call("compassTape", 247, 90)
    assert [t["deg"] for t in interim["ticks"]] == [210, 225, 240, 255, 270, 285]


@_NODE_ONLY
def test_glideDuration_isTheCioOneSecond():
    assert _call("navDrawnDeg", {"fromDeg": 0, "toDeg": 40, "startMs": 0}, 1000) == 40
    src = _read(_JS)
    assert re.search(r"var NAV_GLIDE_MS = 1000;", src)
    assert "CIO N-4" in src[src.index("var NAV_GLIDE_MS") - 200: src.index("var NAV_GLIDE_MS")]


# ---------------------------------------------------------------------------
# 3. Markup + stylesheet
# ---------------------------------------------------------------------------


def _cardTags() -> list[str]:
    return re.findall(r'<section class="card"[^>]*>', _read(_HTML), re.S)


def _navMarkup() -> str:
    html = _read(_HTML)
    start = html.index('<section class="card" id="nav-card"')
    return html[start: html.index("</section>", start)]


def test_slot_navIsIndexOne_rightAfterDriving():
    tags = _cardTags()
    assert 'id="driving-card"' in tags[0]
    tag = tags[1]
    assert 'id="nav-card"' in tag
    assert 'aria-label="Navigation"' in tag
    assert 'data-page-name="NAV"' in tag
    for attr in ("data-state", "data-landing", "data-idle-home", "data-vehicle-gated"):
        assert attr not in tag, attr


def test_skeleton_badgeRowAboveTheBand_noTapeShipped_digitsUnread():
    """The badge has its own row ABOVE the tape (Iris G-1), so it can never
    cover the tape; no tape is shipped before a bearing exists."""
    markup = _navMarkup()
    assert markup.index('class="nav-badge-row"') < markup.index('class="nav-band"')
    assert markup.index('class="nav-band"') < markup.index('class="nav-readout"')
    band = markup[markup.index('class="nav-band"'): markup.index('class="nav-readout"')]
    assert "nav-badge" not in band
    assert "nav-tape" not in markup
    assert ">---°<" in markup and ">not read<" in markup


def _navRules() -> dict[str, str]:
    out: dict[str, str] = {}
    for rule in rh.parseCss(_read(_CSS)):
        if "#nav-card" in rule.selector:
            out[rule.selector.strip()] = out.get(rule.selector.strip(), "") + rule.declarations
    return out


def _tokenPx(name: str) -> float:
    m = re.search(r"--" + name + r":\s*([\d.]+)px", _read(_TOKENS))
    assert m, name
    return float(m.group(1))


def test_css_tokensOnly_literalPxOnlyInTheScopedGeometry():
    rules = _navRules()
    assert rules, "no #nav-card rules"
    for selector, body in rules.items():
        if selector == "#nav-card":
            continue
        assert not re.search(r"\d(px|%)|#[0-9a-fA-F]{3,6}\b|rgba?\(", body), (selector, body)


def test_css_heroValues_atLeast34px_viaTheirTokens():
    rules = _navRules()
    assert "font-size: var(--fs-hero)" in rules["#nav-card .nav-digits"]
    assert "font-size: var(--fs-primary)" in rules["#nav-card .nav-point"]
    assert _tokenPx("fs-hero") >= 34 and _tokenPx("fs-primary") >= 34


def test_css_badgeIsFsLabelOnAmberWarn_rightAligned():
    rules = _navRules()
    badge = rules["#nav-card .nav-badge"]
    assert "font-size: var(--fs-label)" in badge
    assert "background: var(--amber-warn)" in badge
    assert "justify-content: flex-end" in rules["#nav-card .nav-badge-row"]
    assert "height: var(--nav-badge-h)" in rules["#nav-card .nav-badge-row"]


def test_css_northPrimary_othersSecondary_hairlineTwoPx():
    rules = _navRules()
    assert "fill: var(--text-secondary)" in rules["#nav-card .nav-tape-label"]
    assert "fill: var(--text-primary)" in rules["#nav-card .nav-tape-north"]
    hair = rules["#nav-card .nav-tape-hairline"]
    assert "stroke: var(--text-primary)" in hair
    assert "stroke-width: var(--nav-hairline)" in hair
    assert re.search(r"--nav-hairline:\s*2px", rules["#nav-card"])


def test_css_aStaleNavDoesNotDim():
    """Spec s7: the badge is the stale signal; NAV freezes but never dims."""
    for selector, body in _navRules().items():
        assert "stale" not in selector, selector
        assert "opacity" not in body, selector


# ---------------------------------------------------------------------------
# 4. The shipped DOM
# ---------------------------------------------------------------------------


def _find(node: dict[str, Any], pred) -> list[dict[str, Any]]:
    out = [node] if pred(node) else []
    for child in node.get("children", []):
        if "tag" in child:
            out += _find(child, pred)
    return out


def _all(tree: Any, pred) -> list[dict[str, Any]]:
    roots = tree if isinstance(tree, list) else [tree]
    out: list[dict[str, Any]] = []
    for root in roots:
        out += _find(root, pred)
    return out


def _navCard(dom: dict[str, Any]) -> dict[str, Any]:
    hits = _all(dom["tree"], lambda n: n.get("attrs", {}).get("id") == "nav-card")
    assert len(hits) == 1
    return hits[0]


def _one(node: dict[str, Any], cls: str) -> dict[str, Any]:
    hits = _find(node, lambda n: cls in _classes(n))
    assert len(hits) == 1, (cls, len(hits))
    return hits[0]


def _shown(node: dict[str, Any]) -> bool:
    return "hidden" not in node.get("attrs", {})


def _glass(dom: dict[str, Any]) -> dict[str, Any]:
    card = _navCard(dom)
    badge, note = _one(card, "nav-badge"), _one(card, "nav-badge-note")
    blank = _one(card, "nav-blank")
    head = _one(blank, "nav-blank-head")
    tapes = _find(card, lambda n: "nav-tape" in _classes(n))
    return {
        "state": card["attrs"].get("data-heading"),
        "digits": _textOf(_one(card, "nav-digits")),
        "point": _textOf(_one(card, "nav-point")),
        "badge": _textOf(badge) if _shown(badge) else "",
        "note": _textOf(note) if _shown(note) else "",
        "blank": (_textOf(head) + " " if _shown(head) else "") + _textOf(_one(blank, "nav-blank-note"))
        if _shown(blank) else "",
        "tapes": tapes,
    }


def _labels(tape: dict[str, Any]) -> list[tuple[str, list[str]]]:
    return [(_textOf(n), _classes(n)) for n in _find(tape, lambda n: n.get("tag") == "text")]


def _boot(imu: Any, nowMs: int, steps: list[dict[str, Any]] | None = None,
          system: Any = None, stale: Any = STALE) -> dict[str, Any]:
    routes = {"/system-status": system if system is not None else _driving(), "/imu": imu}
    return rh.runDashboard(routes=routes, nowMs=nowMs, steps=steps or [{"flush": 4}],
                           displayStale=stale)


@_NODE_ONLY
def test_dom_validation_trusted247_digitsPointNoBadge_tapeCentredOn247():
    dom = _boot(_imu("trusted-247"), _now("trusted-247"))
    glass = _glass(dom)
    assert (glass["state"], glass["digits"], glass["point"]) == ("trusted", "247°", "SW")
    assert (glass["badge"], glass["note"], glass["blank"]) == ("", "", "")
    assert len(glass["tapes"]) == 1
    tape = glass["tapes"][0]
    assert tape["attrs"]["viewBox"] == "0 0 456 70"
    hair = _find(tape, lambda n: "nav-tape-hairline" in _classes(n))
    assert len(hair) == 1 and hair[0]["attrs"]["x1"] == "228"
    # SW (225) sits LEFT of the 247 centre, W (270) right of it.
    xs = {_textOf(n): float(n["attrs"]["x"]) for n in _find(tape, lambda n: n.get("tag") == "text")}
    assert set(xs) == {"SW", "W"}
    assert xs["SW"] < 228 < xs["W"]
    ticks = _find(tape, lambda n: "nav-tick" in _classes(n))
    assert len(ticks) == 18


@_NODE_ONLY
@pytest.mark.parametrize(("name", "point"), [("boundary-22.5", "NE"), ("boundary-337.5", "N")])
def test_dom_validation_boundaries(name: str, point: str):
    glass = _glass(_boot(_imu(name), _now(name)))
    assert glass["point"] == point


@_NODE_ONLY
def test_dom_uncalibrated_tapeDrawn_badgeNotCalibrated():
    glass = _glass(_boot(_imu("uncalibrated"), _now("uncalibrated")))
    assert (glass["badge"], glass["note"], glass["digits"]) == ("NOT CALIBRATED", "", "247°")
    assert len(glass["tapes"]) == 1


@_NODE_ONLY
def test_dom_legacyEngine_dashChipAndReason():
    glass = _glass(_boot(_imu("legacy-engine-no-flag"), _now("legacy-engine-no-flag")))
    assert (glass["badge"], glass["note"]) == ("--", "calibration not published")
    assert len(glass["tapes"]) == 1 and glass["digits"] == "000°" and glass["point"] == "N"


@_NODE_ONLY
def test_dom_unseeded_startingUp_bandWaits_noTicks():
    glass = _glass(_boot(_imu("unseeded"), _now("unseeded")))
    assert (glass["badge"], glass["digits"], glass["point"]) == ("STARTING UP", "---°", "")
    assert glass["blank"] == "waiting for the first heading reading"
    assert glass["tapes"] == []


@_NODE_ONLY
def test_dom_validation_deadMag_noTapeElement_noHeadingPlusReason():
    dom = _boot(_imu("dead-mag"), _now("dead-mag"))
    glass = _glass(dom)
    assert glass["tapes"] == []
    # Not anywhere in the document either: absent, not hidden.
    assert _all(dom["tree"], lambda n: "nav-tape" in _classes(n)) == []
    assert (glass["digits"], glass["badge"]) == ("---°", "")
    assert glass["blank"] == "NO HEADING no compass reading"


@_NODE_ONLY
def test_dom_aDeadSensor_removesATapeThatWasDrawn():
    steps = [{"flush": 4}, {"setRoutes": {"/imu": _imu("dead-mag")}}, {"flush": 2}]
    glass = _glass(_boot(_imu("trusted-247"), _now("trusted-247"), steps=steps))
    assert glass["tapes"] == [] and glass["digits"] == "---°"


@_NODE_ONLY
def test_dom_validation_stale_frozenTape_noUpdateCounting():
    imu = _imu("stale-imu")
    ts = _ms(imu["ts"])
    live = _glass(_boot(imu, ts + 2500))
    assert (live["badge"], live["digits"]) == ("", "247°")
    stale = _glass(_boot(imu, ts + 3500))
    assert (stale["badge"], stale["digits"], stale["point"]) == ("NO UPDATE 3 s", "247°", "SW")
    assert len(stale["tapes"]) == 1  # frozen, still drawn
    later = _glass(_boot(imu, ts + 3500, steps=[{"flush": 4}, {"advanceMs": 2000, "flush": 2}]))
    assert later["badge"] == "NO UPDATE 5 s"


@_NODE_ONLY
def test_dom_validation_wrap350to10_glidesThroughNorth():
    a, b = _imu("wrap-350-a"), _imu("wrap-350-b")
    t0 = _now("wrap-350-a")
    steps = [{"flush": 4}, {"setRoutes": {"/imu": b}}, {"flush": 1},
             {"advanceMs": 500, "flush": 1}]
    glass = _glass(_boot(a, t0, steps=steps))
    assert (glass["digits"], glass["point"]) == ("000°", "N")
    labels = _labels(glass["tapes"][0])
    north = [cls for text, cls in labels if text == "N"]
    assert north and "nav-tape-north" in north[0]
    assert all("nav-tape-north" not in cls for text, cls in labels if text != "N")
    done = _glass(_boot(a, t0, steps=[*steps, {"advanceMs": 600, "flush": 1}]))
    assert done["digits"] == "010°"


@_NODE_ONLY
def test_dom_parkedEngineOff_headingStaysLive():
    fx = _fixture("parked-engine-off")
    glass = _glass(_boot(fx["imu"], _now("parked-engine-off"), system=fx["system-status"]))
    assert (glass["state"], glass["digits"], glass["point"], glass["badge"]) == (
        "trusted", "092°", "E", ""
    )


@_NODE_ONLY
def test_dom_noImuFile_noHeading_noMotionFeed():
    glass = _glass(_boot(None, _now("trusted-247")))
    assert glass["tapes"] == [] and glass["blank"] == "NO HEADING no motion feed"


@_NODE_ONLY
def test_dom_theBarNamesTheCardNav():
    steps = [{"flush": 4}, {"clickNth": {"selector": ".dot", "index": 1}}, {"flush": 1}]
    dom = _boot(_imu("trusted-247"), _now("trusted-247"), steps=steps)
    name = _all(dom["tree"], lambda n: n.get("attrs", {}).get("id") == "page-name")
    assert _textOf(name[0]) == "NAV"



# ---------------------------------------------------------------------------
# US-896-b: the bottom row -- GRADE and the trip (spec s4.3/s4.4/s4.5)
# ---------------------------------------------------------------------------

TRIP_FIXTURES = [
    "trip-mid-drive", "trip-drive-start", "trip-last-drive", "trip-not-measured",
    "trip-partial-parked", "trip-state-null", "trip-partial-after-restart",
]
_ZONE = "America/Chicago"


def _sys(name: str) -> dict[str, Any]:
    return _fixture(name)["system-status"]


def _callTz(fn: str, *args: Any, tz: str = _ZONE) -> Any:
    """_call on a pinned local zone: SINCE's h:mm is LOCAL time."""
    payload = {"js": _JS, "fn": fn, "args": list(args)}
    proc = subprocess.run(
        [_NODE or "node", "-e", _CALL], input=json.dumps(payload),
        capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, TZ=tz),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _trip(payload: Any) -> tuple[str, str | None, str, str]:
    v = _callTz("navTripView", payload)
    return (v["label"], v["time"], v["distance"], v["elapsed"])


def test_tripFixtures_arePresent_described_andTheRealProvidersPayload():
    """Each trip fixture IS buildSystemStatusState's output for its inputs, so
    the page is tested against the provider's real drive block."""
    from pi.splash.system_status_emitter import buildSystemStatusState

    for name in TRIP_FIXTURES:
        fx = _fixture(name)
        assert fx["description"] and fx["zone"] == _ZONE, name
        assert buildSystemStatusState(**fx["inputs"]) == fx["system-status"], name


# The trip fixtures' system-status SHAPE, written out by hand (never read from
# an older fixture). A story that adds or removes a system-status key
# regenerates the fixtures from the real builder and edits THIS table, so the
# regenerated files can differ from the old ones only in the keys named here.
# US-876-a: obdLink lost `lastSeenS` (and the inputs lost `obdLastSeenS`).
# US-876-c: the new top-level `link` block, its three layers (checked below).
# US-876-d: NO delta -- link.adapter fills keys US-876-c already publishes and
#           the builder gains no input (the provider feeds the existing `link`).
# US-876-e: NO delta -- link.bt likewise fills keys US-876-c already publishes
#           (the BT sampler feeds the existing `link`; no new builder input).
# US-732:   `wifi` gains `home` and `ts` (null in every trip fixture: no wifi
#           input). No input key added or removed. One VALUE moves with them:
#           source.wifi.reason "wifi: not read" -> "not_read" (Atlas W8).
# US-916:   `sync` gains `rowsWaiting`, `edrRowsWaiting` and `notCounted` (null
#           in every trip fixture: no database in a trip scene); the inputs
#           gain the three builder parameters behind them, all null.
# US-877-a: the new top-level `pi` health block (every key null and overLimit
#           [] in every trip fixture: no sampler in a trip scene); the inputs
#           gain its one builder parameter, piHealth, null.
# US-877-b: the new top-level `verdict` {issueCount, members} (0 and [] in
#           every trip fixture: nothing read is no issue); the inputs gain its
#           one builder parameter, captureHealth, null.
# US-894-b: MOVED PIN (US-894-b) -- `obdLink` is retired (Atlas A2/P6); the
#           inputs drop its two builder parameters, obdLinkState and
#           obdRetries. Nothing else moved (checked at regeneration: each new
#           block == the old one minus obdLink).
_TRIP_STATUS_KEYS = {
    "sync": {
        "lastOkTs", "rows", "pending", "stale",
        "rowsWaiting", "edrRowsWaiting", "notCounted",
    },
    "power": {"source", "reasons"},
    "wifi": {"state", "ssid", "rssiDbm", "home", "ts"},
    "link": {"bt", "adapter", "ecu"},
    "pi": {
        "cpuTempC", "cpuTempTs", "cpuTempLimitC",
        "throttled", "throttledHex", "throttledSinceBoot", "throttledTs",
        "diskFreeBytes", "diskThresholdBytes", "diskVerdict", "diskTs",
        "uptimeS", "uptimeTs", "overLimit",
    },
    "drive": {
        "state", "driveId", "lastDrive", "distanceKm", "distanceSinceTs",
        "elapsedSec", "distancePartial",
    },
    "idle": None,
    "priorShutdown": None,
    "runMode": None,
    "source": {"obd", "wifi"},
    "ts": None,
    "verdict": {"issueCount", "members"},
}
_TRIP_LINK_LAYER_KEYS = {"state", "ts", "lastOkTs"}
_TRIP_INPUT_KEYS_REMOVED = {"obdLastSeenS", "obdLinkState", "obdRetries"}
_TRIP_INPUT_KEYS_ADDED = {
    "syncRowsWaiting", "syncEdrRowsWaiting", "syncNotCounted", "piHealth",
    "captureHealth",
}


def test_tripFixtures_carryExactlyTheExpectedTopLevelAndBlockKeys():
    """Every regenerated trip fixture has the hand-written key set above, at the
    top level and inside each block, and no input the builder no longer takes."""
    for name in TRIP_FIXTURES:
        fx = _fixture(name)
        status = fx["system-status"]
        assert set(status) == set(_TRIP_STATUS_KEYS), name
        for block, keys in _TRIP_STATUS_KEYS.items():
            if keys is not None:
                assert set(status[block]) == keys, (name, block)
        for layer in _TRIP_STATUS_KEYS["link"]:
            assert set(status["link"][layer]) == _TRIP_LINK_LAYER_KEYS, (name, layer)
        assert not _TRIP_INPUT_KEYS_REMOVED & set(fx["inputs"]), name
        assert _TRIP_INPUT_KEYS_ADDED <= set(fx["inputs"]), name


def test_gradeNullFixture_isTheRealBridgesPayload_gradeOnlyNull():
    from pi.sensors.imu_state_bridge import buildImuState

    fx = _fixture("grade-null")
    kwargs = dict(fx["inputs"])
    for key in ("gravity", "linear", "mag"):
        if kwargs.get(key) is not None:
            kwargs[key] = tuple(kwargs[key])
    assert buildImuState(**kwargs) == fx["imu"]
    assert fx["imu"]["gradePct"] is None
    assert fx["imu"]["reasons"]["gradePct"] == "pitch_out_of_range"
    assert fx["imu"]["headingDeg"] == 247.0


@_NODE_ONLY
@pytest.mark.parametrize(("pct", "value", "slope"), [
    (4.1, "+4.1 %", "up"),
    (-2.4, "−2.4 %", "down"),
    (0.0, "+0.0 %", "flat"),
    (0.04, "+0.0 %", "flat"),
    (-0.06, "−0.1 %", "down"),
])
def test_grade_oneDecimalSigned_glyphTiltsWithThePrintedSign(pct: float, value: str, slope: str):
    imu = dict(_imu("trusted-247"), gradePct=pct)
    v = _call("navGradeView", imu, _now("trusted-247"))
    assert (v["value"], v["slope"], v["reason"]) == (value, slope, None)


@_NODE_ONLY
def test_grade_null_isDashPlusItsReason():
    v = _call("navGradeView", _imu("grade-null"), _now("grade-null"))
    assert (v["value"], v["slope"], v["reason"]) == ("--", None, "pitch beyond range")


@_NODE_ONLY
@pytest.mark.parametrize(("payload", "reason"), [
    (None, "no motion feed"),
    ({"available": True, "gradePct": 4.1}, "no read time"),
])
def test_grade_noFeedOrUndated_isDashPlusReason(payload: Any, reason: str):
    v = _call("navGradeView", payload, _now("trusted-247"))
    assert (v["value"], v["reason"]) == ("--", reason)


@_NODE_ONLY
@pytest.mark.parametrize(("sec", "text"), [
    (0, "0:00"), (1380, "0:23"), (1800, "0:30"), (1439, "0:23"), (3725, "1:02"),
    (None, None), (-5, None),
])
def test_fmtElapsed_hMm_wholeMinutes(sec: Any, text: str | None):
    assert _call("fmtElapsed", sec) == text


@_NODE_ONLY
@pytest.mark.parametrize(("name", "expected"), [
    ("trip-mid-drive", ("THIS DRIVE", None, "12.4 mi", "0:23 elapsed")),
    ("trip-drive-start", ("THIS DRIVE", None, "0.0 mi", "0:00 elapsed")),
    ("trip-last-drive", ("LAST DRIVE", None, "12.4 mi", "0:30 elapsed")),
    ("trip-not-measured", ("THIS DRIVE", None, "-- mi", "not measured")),
    ("trip-partial-parked", ("SINCE", "2:49", "12.4 mi", "0:23 elapsed")),
    ("trip-state-null", ("THIS DRIVE", None, "12.4 mi", "0:23 elapsed")),
    ("trip-partial-after-restart", ("SINCE", "2:49", "12.4 mi", "0:23 elapsed")),
])
def test_validation_tripLabel_precedence_perFixture(name: str, expected: tuple):
    assert _trip(_sys(name)) == expected


@_NODE_ONLY
def test_validation_distancePartialNull_with19km_isNotMeasured():
    status = json.loads(json.dumps(_sys("trip-mid-drive")))
    status["drive"]["distancePartial"] = None
    assert _trip(status)[2:] == ("-- mi", "not measured")


@_NODE_ONLY
@pytest.mark.parametrize("state, label", [
    ("idle", "LAST DRIVE"),
    ("recording", "THIS DRIVE"),
    (None, "THIS DRIVE"),
])
def test_notMeasured_labelStaysStateDerived(state: Any, label: str):
    """CIO ruling 2026-10-19 (Q-A): not-measured never fixes THIS DRIVE --
    LAST DRIVE when the state is known and not recording, else THIS DRIVE."""
    status = json.loads(json.dumps(_sys("trip-last-drive")))
    status["drive"]["state"] = state
    status["drive"]["distancePartial"] = None
    assert _trip(status) == (label, None, "-- mi", "not measured")


@_NODE_ONLY
def test_partialWins_overParked_neverLastDrive():
    """A partial window never claims LAST DRIVE, whatever the state says."""
    for state in ("idle", "waiting", "recording"):
        status = json.loads(json.dumps(_sys("trip-partial-parked")))
        status["drive"]["state"] = state
        assert _trip(status)[:2] == ("SINCE", "2:49"), state


@_NODE_ONLY
def test_since_isTwelveHourWithoutAmPm_inTheLocalZone():
    """19:49Z is 14:49 in Chicago and 04:49 next day in Tokyo: the panel's
    local clock, never UTC, never a meridiem."""
    status = _sys("trip-partial-after-restart")
    assert _callTz("navTripView", status)["time"] == "2:49"
    assert _callTz("navTripView", status, tz="Asia/Tokyo")["time"] == "4:49"


@_NODE_ONLY
def test_noPageTimeArithmetic_elapsedIsTheProvidersOnly():
    """sinceTs 23 min before the payload's ts, elapsedSec 60: the page prints
    0:01. A page-side now - sinceTs would print 0:23."""
    status = json.loads(json.dumps(_sys("trip-mid-drive")))
    status["drive"]["elapsedSec"] = 60
    assert _trip(status)[3] == "0:01 elapsed"
    status["drive"]["elapsedSec"] = None
    assert _trip(status)[3] == "elapsed not read"


@_NODE_ONLY
def test_staleSystemStatus_isNeverExtrapolated():
    """The same drive block, dated hours earlier, prints the same figures:
    the page never extends a published window."""
    status = json.loads(json.dumps(_sys("trip-mid-drive")))
    status["ts"] = "2026-10-20T08:00:00Z"
    assert _trip(status) == _trip(_sys("trip-mid-drive"))


@_NODE_ONLY
@pytest.mark.parametrize("payload", [None, {}, {"drive": None}, {"drive": {"state": "recording"}}])
def test_noSystemStatus_isNotMeasured_andNeverParked(payload: Any):
    assert _trip(payload) == ("THIS DRIVE", None, "-- mi", "not measured")


@_NODE_ONLY
def test_tripView_carriesNoSpeed():
    """CIO N-2: the driving page owns speed."""
    v = _callTz("navTripView", _sys("trip-mid-drive"))
    assert not any("speed" in k.lower() for k in v)


def test_skeleton_bottomRowUnderTheReadout_notReadFaces():
    markup = _navMarkup()
    assert markup.index('class="nav-readout"') < markup.index('class="nav-bottom"')
    bottom = markup[markup.index('class="nav-bottom"'):]
    assert bottom.index('class="nav-grade"') < bottom.index('class="nav-trip"')
    assert ">GRADE<" in bottom and ">THIS DRIVE<" in bottom
    assert ">--<" in bottom and ">not read<" in bottom
    assert ">-- mi<" in bottom and ">not measured<" in bottom
    assert "mph" not in markup and "speed" not in markup.lower()


def test_css_bottomRow_valuesFsPrimary_labelsMichromaMeta_timeMono():
    rules = _navRules()
    for sel in ("#nav-card .nav-grade-value", "#nav-card .nav-trip-distance"):
        assert "font-size: var(--fs-primary)" in rules[sel], sel
        assert "font-family: var(--font-mono)" in rules[sel], sel
    label = rules["#nav-card .nav-label"]
    assert "font-family: var(--font-display)" in label
    assert "font-size: var(--fs-meta)" in label
    time = rules["#nav-card .nav-trip-time"]
    assert "font-family: var(--font-mono)" in time and "font-size: var(--fs-meta)" in time
    assert "font-size: var(--fs-label)" in rules["#nav-card .nav-trip-elapsed"]
    assert "font-size: var(--fs-label)" in rules["#nav-card .nav-grade-note"]
    assert "align-items: flex-end" in rules["#nav-card .nav-trip"]
    assert _tokenPx("fs-primary") >= 34


def _bottom(dom: dict[str, Any]) -> dict[str, Any]:
    card = _navCard(dom)
    grade, trip = _one(card, "nav-grade"), _one(card, "nav-trip")
    note, time = _one(grade, "nav-grade-note"), _one(trip, "nav-trip-time")
    glyph = _one(grade, "nav-slope")
    return {
        "grade": _textOf(_one(grade, "nav-grade-value")),
        "note": _textOf(note) if _shown(note) else "",
        "slope": grade["attrs"].get("data-slope"),
        "glyph": _shown(glyph),
        "label": _textOf(_one(trip, "nav-trip-label")),
        "time": _textOf(time) if _shown(time) else "",
        "distance": _textOf(_one(trip, "nav-trip-distance")),
        "elapsed": _textOf(_one(trip, "nav-trip-elapsed")),
        "window": trip["attrs"].get("data-window"),
    }


@_NODE_ONLY
@pytest.mark.parametrize(("name", "expected"), [
    ("trip-mid-drive", ("THIS DRIVE", "", "12.4 mi", "0:23 elapsed")),
    ("trip-last-drive", ("LAST DRIVE", "", "12.4 mi", "0:30 elapsed")),
    ("trip-partial-after-restart", ("SINCE", "2:49", "12.4 mi", "0:23 elapsed")),
    ("trip-partial-parked", ("SINCE", "2:49", "12.4 mi", "0:23 elapsed")),
    ("trip-state-null", ("THIS DRIVE", "", "12.4 mi", "0:23 elapsed")),
    ("trip-not-measured", ("THIS DRIVE", "", "-- mi", "not measured")),
    ("trip-drive-start", ("THIS DRIVE", "", "0.0 mi", "0:00 elapsed")),
])
def test_dom_validation_tripOnTheGlass(name: str, expected: tuple, monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    b = _bottom(_boot(_imu("trusted-247"), _now("trusted-247"), system=_sys(name)))
    assert (b["label"], b["time"], b["distance"], b["elapsed"]) == expected


@_NODE_ONLY
def test_dom_grade_trusted_isLiveFlat_andNullShowsItsReason():
    live = _bottom(_boot(_imu("trusted-247"), _now("trusted-247")))
    assert (live["grade"], live["note"], live["slope"], live["glyph"]) == (
        "+0.0 %", "", "flat", True
    )
    null = _bottom(_boot(_imu("grade-null"), _now("grade-null")))
    assert (null["grade"], null["note"], null["slope"], null["glyph"]) == (
        "--", "pitch beyond range", "none", False
    )


@_NODE_ONLY
def test_dom_parkedEngineOff_gradeAndTripStayLive():
    """Spec s4.5: nothing greys out because the car stopped."""
    fx = _fixture("parked-engine-off")
    b = _bottom(_boot(fx["imu"], _now("parked-engine-off"), system=_sys("trip-last-drive")))
    assert (b["grade"], b["label"], b["distance"]) == ("+0.0 %", "LAST DRIVE", "12.4 mi")


@_NODE_ONLY
def test_dom_noImuFile_gradeSaysNoMotionFeed():
    b = _bottom(_boot(None, _now("trusted-247")))
    assert (b["grade"], b["note"]) == ("--", "no motion feed")


# ---------------------------------------------------------------------------
# US-911: NAV's badge note and Motion's COMPASS absent text are built from ONE
# constant, CALIBRATION_ABSENT_TEXT (Atlas X3; CIO 2026-10-19 chose Iris's
# wording). NAV's output stays 'calibration not published'.
# ---------------------------------------------------------------------------

_MOTION_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "motion")
_ABSENT_DECL = 'var CALIBRATION_ABSENT_TEXT = "not published";'
_SENTINEL = "SENTINEL-911"


def _motionImu(name: str) -> dict[str, Any]:
    with open(os.path.join(_MOTION_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)["imu"]


def _enclosingFunction(lines: list[str], index: int) -> str:
    for line in reversed(lines[:index]):
        m = re.match(r"\s*function (\w+)\(", line)
        if m:
            return m.group(1)
    return ""


def test_calibrationAbsentText_isOneConstant_andTheOldNamesAreGone():
    src = _read(_JS)
    assert src.count(_ABSENT_DECL) == 1
    assert "NAV_CALIBRATION_ABSENT_TEXT" not in src
    assert "MOTION_CALIBRATION_ABSENT_TEXT" not in src
    assert '"calibration not published"' not in src
    assert '"calibration " + CALIBRATION_ABSENT_TEXT' in src


def test_notPublishedLiteral_onlyTheConstant_outsideTheFuelPage():
    """The literal appears once in the NAV and Motion code (the constant); the
    Fuel page's own 'not published' literals stay (acceptance)."""
    lines = _read(_JS).splitlines()
    outside = [
        i + 1 for i, line in enumerate(lines)
        if '"not published"' in line and line.strip() != _ABSENT_DECL
        and not _enclosingFunction(lines, i).startswith("fuel")
    ]
    assert outside == []


def _callCopy(js: str, calls: list[list[Any]]) -> list[Any]:
    script = (
        'const a = JSON.parse(require("fs").readFileSync(0, "utf-8"));'
        "const c = require(a.js);"
        "process.stdout.write(JSON.stringify(a.calls.map("
        "(k) => c[k[0]].apply(null, k.slice(1)))));"
    )
    proc = subprocess.run(
        [_NODE or "node", "-e", script], input=json.dumps({"js": js, "calls": calls}),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _mutatedCopy(tmp_path) -> str:
    src = _read(_JS)
    assert src.count(_ABSENT_DECL) == 1
    out = tmp_path / "carousel.js"
    out.write_text(
        src.replace(_ABSENT_DECL, f'var CALIBRATION_ABSENT_TEXT = "{_SENTINEL}";'),
        encoding="utf-8",
    )
    return str(out)


def _bothViews(js: str, navImu: Any, motionImu: Any) -> tuple[Any, Any]:
    nav, motion = _callCopy(js, [
        ["navHeadingView", navImu, _now("legacy-engine-no-flag"), IMU_SEC],
        ["motionView", motionImu, _ms(_fixture("legacy-engine-no-flag")["now"]), 1e9, None],
    ])
    return (nav["badge"], nav["badgeNote"]), (
        motion["health"]["compass"]["value"], motion["health"]["compass"]["sub"])


@_NODE_ONLY
def test_navNoteAndMotionCompass_areBothBuiltFromTheOneConstant(tmp_path):
    """Change the constant's text in a copy: BOTH pages follow it, so neither
    keeps a second copy of the wording."""
    nav, motion = _bothViews(
        _mutatedCopy(tmp_path), _imu("legacy-engine-no-flag"), _motionImu("compass-legacy-engine"))
    assert nav == ("--", "calibration " + _SENTINEL)
    assert motion == ("--", _SENTINEL)


@_NODE_ONLY
def test_validation_shippedText_navCalibrationNotPublished_motionNotPublished():
    nav, motion = _bothViews(
        _JS, _imu("legacy-engine-no-flag"), _motionImu("compass-legacy-engine"))
    assert nav == ("--", "calibration not published")
    assert motion == ("--", "not published")


@_NODE_ONLY
def test_aPublishedHeadingCalibratedReason_stillWinsOnBothPages(tmp_path):
    navImu, motionImu = _imu("legacy-engine-no-flag"), _motionImu("compass-legacy-engine")
    navImu = dict(navImu, reasons=dict(navImu.get("reasons") or {}, headingCalibrated="no_source"))
    motionImu = dict(motionImu, reasons=dict(motionImu["reasons"], headingCalibrated="no_source"))
    nav, motion = _bothViews(_mutatedCopy(tmp_path), navImu, motionImu)
    assert nav == ("--", "no source")
    assert motion == ("--", "no source")
