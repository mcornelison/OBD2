################################################################################
# File Name: test_driving_page.py
# Purpose/Description: US-888-a (F-140) tests for the Driving card -- V0.30
#   layout B (specs/v030-driving-page-design.md), the new landing card. Guarded:
#     1. the SLOT -- a new card at index 0 that the carousel lands on, with the
#        Home/IMU card moved to index 1 byte-for-byte and the idle/live swap
#        left with it;
#     2. the UNITS -- ONE display-units helper converts by the provider's
#        `unit` ('C' -> deg F, 'km/h' -> mph), passes target units through and
#        renders an unknown unit raw (Atlas G1);
#     3. the VALUES -- every s7 fixture (tests/ui/fixtures/states/driving/)
#        through the exported view AND through the shipped DOM: band colour
#        only from the provider, neutral for an unbanded value, stale shows
#        last.value dimmed with its age, not-read shows '--' + reason;
#     4. the TYPE -- gear at --fs-giant in Michroma 400 without synthesis,
#        every reading >= 34 px in --font-mono with tabular-nums, labels in
#        Michroma at --fs-meta with letter-spacing 0;
#     5. the CSS GATE -- tokens only: no literal colour anywhere in the
#        Driving rules, literal px only inside the ONE `#driving-card`
#        custom-property block (Iris G-4), motion only when state-qualified;
#     6. the FIT -- a height/width model of layout B at 480x320 built from
#        the shipped values, with negative controls.
#   NOT GUARDED, stated rather than implied: the render harness resolves the
#   cascade, not layout (render_harness.py fidelity limit 1), so "no clipping"
#   here is the arithmetic model in section 6; the glass check is the R15
#   screenshot owed on the Pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Ralph (Rex)  | Initial -- US-888-a Driving card.
# 2026-10-15    | Ralph (Rex)  | US-888-b: CSS gate admits state-qualified motion
#               |              | only (+ planted bare-animation control).
# ================================================================================
################################################################################

"""US-888-a tests for the Driving card (layout B, the landing card)."""

from __future__ import annotations

import glob
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

from tests.ui.css_type_scale import (  # noqa: E402
    DASHBOARD_CSS,
    readCss,
    scaleValues,
)
from tests.ui.test_topbar_three_column_grid import (  # noqa: E402
    PI_MONO_ADVANCE_EM,
    michromaWidthPx,
)

_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "driving")

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped browser JS",
)

# The card order (US-888-a validation row "Card order"), by kit label.
CARD_ORDER = ["Driving", "Home", "Alerts", "System Status", "Battery", "Fuel Trim", "Light"]

# The Home/IMU slot as it shipped before this story (US-887-c tree). It moves
# to index 1 with its DOM UNCHANGED (Iris Q1), so the tag is pinned verbatim.
HOME_SLOT_MARKUP = (
    '<section class="card" data-idle-home data-face="idle" id="home-card"\n'
    '               aria-label="Home" data-page-name="MOTION">\n'
    '        <div class="card-body"><span class="idle-boot">standby …</span></div>\n'
    "      </section>"
)

# The five readings and where layout B puts them (spec s3, D-12).
READING_PIDS = ["COOLANT_TEMP", "INTAKE_TEMP", "SPEED", "RPM", "BATTERY_V"]
# The three engine numbers whose colour IS the provider band (spec s4.3). RPM's
# number stays warm white (style rule 4; its red is US-888-b) and SPEED has no
# band at all.
BANDED_PIDS = {"COOLANT_TEMP", "INTAKE_TEMP", "BATTERY_V"}
BAND_TOKEN = {
    "green": "var(--green-ok)",
    "amber": "var(--amber-warn)",
    "red": "var(--critical-red)",
}

# Iris's fixture list (SHAPE-CHECK S103, 888-a). Hint and takeover fixtures are
# deliberately absent (US-904 / Warnings).
FIXTURE_NAMES = [
    "idle-neutral",
    "gear-1",
    "gear-2",
    "gear-3",
    "gear-4",
    "gear-5",
    "between-gears-no-hint",
    "coolant-amber",
    "coolant-red",
    "iat-neutral",
    "engine-off-voltage-unbanded",
    "battery-amber-gap",
    "ecu-silent-stale",
    "coolant-stale-last-red",
    "value-null-with-reason",
    # US-888-b (Iris G-1): the builder's output for python-obd's measured units.
    "driving-published-units",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _probe(fn: str, *args: object) -> Any:
    cmd = [_NODE or "node", _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _view(name: str) -> dict[str, Any]:
    fx = _fixture(name)
    return _probe("drivingView", fx["obd-live"], fx["gear"], _ms(fx["now"]))


def _sectionTags(html: str) -> list[str]:
    return re.findall(r'<section class="card"[^>]*>', html, re.S)


def _drivingMarkup() -> str:
    html = _read(_HTML)
    match = re.search(r'<section class="card"[^>]*id="driving-card".*?</section>', html, re.S)
    assert match is not None, "no #driving-card section in dashboard.html"
    return match.group(0)


def _textOf(node: dict[str, Any]) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _textOf(child))
    return "".join(out).strip()


def _classes(node: dict[str, Any]) -> list[str]:
    return (node.get("attrs", {}).get("class") or "").split()


def _inDriving(path: list[dict[str, Any]]) -> bool:
    return any(n.get("attrs", {}).get("id") == "driving-card" for n in path)


def _drivingPaths(surface: rh.Surface, cls: str) -> list[list[dict[str, Any]]]:
    return [p for p in surface.pathsByClass(cls) if _inDriving(p)]


def _readingPath(surface: rh.Surface, pid: str) -> list[dict[str, Any]]:
    for path in _drivingPaths(surface, "drv-reading"):
        if path[-1].get("attrs", {}).get("data-pid") == pid:
            return path
    raise AssertionError(f"no .drv-reading for {pid}")


def _child(path: list[dict[str, Any]], cls: str) -> list[dict[str, Any]]:
    """The first descendant of ``path`` carrying ``cls``, as a full path."""

    def walk(node: dict[str, Any], trail: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        for child in node.get("children", []):
            if "tag" not in child:
                continue
            here = trail + [child]
            if cls in _classes(child):
                return here
            found = walk(child, here)
            if found is not None:
                return found
        return None

    found = walk(path[-1], path)
    assert found is not None, f"no .{cls} under {path[-1].get('attrs')}"
    return found


def _boot(name: str, extraRoutes: dict[str, Any] | None = None) -> rh.Surface:
    fx = _fixture(name)
    routes: dict[str, Any] = {"/obd-live": fx["obd-live"], "/gear": fx["gear"]}
    routes.update(extraRoutes or {})
    dom = rh.runDashboard(routes=routes, nowMs=_ms(fx["now"]), steps=[{"flush": 4}])
    return rh.dashboardSurface(dom["tree"])


def _drivingRules() -> list[tuple[str, str]]:
    """Every dashboard.css rule that styles the Driving card (comments stripped)."""
    return [
        (rule.selector.strip(), rule.declarations)
        for rule in rh.parseCss(_read(DASHBOARD_CSS))
        if "#driving-card" in rule.selector or ".drv-" in rule.selector
    ]


def _rule(selector: str) -> str:
    bodies = [body for sel, body in _drivingRules() if sel == selector]
    assert bodies, f"no rule {selector!r}"
    return " ".join(bodies)


def _decl(body: str, prop: str) -> str | None:
    found = rh.declarationOf(body, prop)
    return None if found is None else found[0]


def _scopedVars() -> dict[str, str]:
    block = _rule("#driving-card")
    return {
        name: value.strip() for name, value in re.findall(r"(--drv-[\w-]+)\s*:\s*([^;]+);", block)
    }


def _px(value: str) -> float:
    """Resolve a length to px through the scoped block and the token scale."""
    value = value.strip()
    var = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if var:
        name = var.group(1)
        scoped = _scopedVars()
        if name in scoped:
            return _px(scoped[name])
        scale = scaleValues(readCss(DASHBOARD_CSS))
        if name[2:] in scale:
            return float(scale[name[2:]])
        root = re.search(rf"^\s*{re.escape(name)}:\s*([0-9.]+)px", _read(DASHBOARD_CSS), re.M)
        assert root is not None, f"{name} does not resolve to px"
        return float(root.group(1))
    match = re.fullmatch(r"([0-9.]+)px", value)
    assert match is not None, f"{value!r} is not a px length"
    return float(match.group(1))


def _number(value: str) -> float:
    var = re.fullmatch(r"var\((--drv-[\w-]+)\)", value.strip())
    return float(_scopedVars()[var.group(1)] if var else value)


# ---------------------------------------------------------------------------
# 1. The slot -- index 0, the landing card; Home moves to index 1 unchanged.
# ---------------------------------------------------------------------------


def test_cardOrder_drivingFirst_thenTheSixExistingCards():
    labels = re.findall(r'<section class="card"[^>]*?aria-label="([^"]+)"', _read(_HTML), re.S)
    assert labels == CARD_ORDER


def test_drivingCard_isNamedDriving_andInheritsNoHomeSlotMachinery():
    tag = _sectionTags(_read(_HTML))[0]
    assert 'id="driving-card"' in tag
    assert 'data-page-name="DRIVING"' in tag
    assert "data-landing" in tag
    # The idle/live swap stays with the Home slot (Iris Q1): no face switch, no
    # idle-home marker, and no generic availability state that would gray it.
    for attr in ("data-idle-home", "data-face", "data-state", "data-vehicle-gated"):
        assert attr not in tag, attr


def test_homeSlot_movesToIndexOne_withItsMarkupUnchanged():
    html = _read(_HTML)
    assert HOME_SLOT_MARKUP in html
    assert 'id="home-card"' in _sectionTags(html)[1]


def test_drivingFacts_doNotUseTheTileClass():
    """The 4-fact ceiling counts `.tile` (test_carousel_card_set.py); layout B
    is not a tile grid and must not spend that budget."""
    assert not re.search(r'class="[^"]*\btile\b', _drivingMarkup())


@_NODE_ONLY
@pytest.mark.parametrize("idle", [True, False])
def test_theCarouselLandsOnDriving_whicheverWayTheIdleEdgeFires(idle: bool):
    """The first tick always fires the home-nav edge (lastIdle starts null), so
    landing on Driving is decided by WHERE that edge goes, not by index 0 alone.
    """
    fx = _fixture("idle-neutral")
    sys_ = {"idle": idle, "source": {"obd": {"available": not idle}}, "ts": fx["now"]}
    surface = _boot("idle-neutral", {"/system-status": sys_})
    name = surface.pathById("page-name")
    assert name is not None
    assert _textOf(name[-1]) == "DRIVING"
    dots = surface.pathsByClass("dot")
    assert dots and "active" in _classes(dots[0][-1])


def test_theHomeNavEdge_targetsTheLandingCard():
    js = _read(_JS)
    start = js.index("function updateHomeNav(sysData)")
    body = js[start : js.index("\n      }", start)]
    assert "goTo(landingIndex)" in body


# ---------------------------------------------------------------------------
# 2. Units -- ONE helper, keyed by the provider's unit (Atlas G1).
# ---------------------------------------------------------------------------


@_NODE_ONLY
@pytest.mark.parametrize(
    ("value", "unit", "text", "shown"),
    [
        (88, "C", "190", "°F"),
        (190, "F", "190", "°F"),
        (64, "km/h", "40", "mph"),
        (40, "mph", "40", "mph"),
        (12, "X", "12", "X"),
        (14.1, "V", "14.1", "V"),
    ],
)
def test_displayUnits_convertsByTheProvidersUnit(value: float, unit: str, text: str, shown: str):
    assert _probe("displayUnits", value, unit) == {"text": text, "unit": shown}


@_NODE_ONLY
def test_displayUnits_missingUnit_rendersTheRawValueWithNoUnit():
    assert _probe("displayUnits", 12, None) == {"text": "12", "unit": ""}


def test_displayUnits_isTheOnlyConversionInCarouselJs():
    code = _read(_JS)
    assert code.count("function displayUnits(") == 1
    assert len(re.findall(r"9\s*/\s*5|\b1\.8\b", code)) == 1, "a second C->F conversion"
    assert len(re.findall(r"KM_PER_MILE\s*=", code)) == 1


# ---------------------------------------------------------------------------
# 3. Values -- every fixture, through the view and through the shipped DOM.
# ---------------------------------------------------------------------------


def test_everyIrisFixtureIsPresent_andNoHintOrTakeoverFixture():
    names = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(_FIXTURES, "*.json")))
    assert names == sorted(FIXTURE_NAMES)


# (pid -> (text, unit, band, stale, note)) per fixture, from the provider data.
EXPECTED: dict[str, dict[str, tuple[str, str, str | None, bool, str]]] = {
    "idle-neutral": {
        "RPM": ("0", "", "green", False, ""),
        "SPEED": ("0", "mph", None, False, ""),
        "COOLANT_TEMP": ("104", "°F", "green", False, ""),
        "INTAKE_TEMP": ("72", "°F", None, False, ""),
        "BATTERY_V": ("12.6", "V", None, False, ""),
    },
    "coolant-amber": {"COOLANT_TEMP": ("221", "°F", "amber", False, "")},
    "coolant-red": {"COOLANT_TEMP": ("230", "°F", "red", False, "")},
    "iat-neutral": {"INTAKE_TEMP": ("113", "°F", None, False, "")},
    "engine-off-voltage-unbanded": {"BATTERY_V": ("12.4", "V", None, False, "")},
    "battery-amber-gap": {"BATTERY_V": ("13.0", "V", None, False, "")},
    "ecu-silent-stale": {
        "RPM": ("2450", "", "green", True, "12 s"),
        "SPEED": ("40", "mph", None, True, "12 s"),
        "COOLANT_TEMP": ("190", "°F", "green", True, "12 s"),
        "INTAKE_TEMP": ("88", "°F", None, True, "12 s"),
        "BATTERY_V": ("14.1", "V", "green", True, "12 s"),
    },
    "coolant-stale-last-red": {"COOLANT_TEMP": ("232", "°F", "red", True, "12 s")},
    "value-null-with-reason": {
        "INTAKE_TEMP": ("--", "", None, False, "not read"),
        "BATTERY_V": ("--", "", None, False, "not read"),
    },
}

EXPECTED_GEAR = {
    "idle-neutral": ("N", True),
    "gear-1": ("1", True),
    "gear-2": ("2", True),
    "gear-3": ("3", True),
    "gear-4": ("4", True),
    "gear-5": ("5", True),
    "between-gears-no-hint": ("--", False),
    "engine-off-voltage-unbanded": ("N", True),
}


@_NODE_ONLY
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_drivingView_readingsMatchTheProvider(name: str):
    readings = _view(name)["readings"]
    for pid, (text, unit, band, stale, note) in EXPECTED[name].items():
        got = readings[pid]
        assert (got["text"], got["unit"], got["band"], got["stale"], got["note"]) == (
            text,
            unit,
            band,
            stale,
            note,
        ), (name, pid, got)


@_NODE_ONLY
@pytest.mark.parametrize("name", sorted(EXPECTED_GEAR))
def test_drivingView_gearIsTheProducersGlyph_withNoHint(name: str):
    gear = _view(name)["gear"]
    assert (gear["text"], gear["measured"]) == EXPECTED_GEAR[name]
    assert set(gear) == {"text", "measured"}, "the page grew a hint it does not compute"


@_NODE_ONLY
def test_drivingView_noObdLive_isDashDashWithAReason_never0():
    view = _probe("drivingView", None, None, 0)
    for pid in READING_PIDS:
        r = view["readings"][pid]
        assert (r["text"], r["band"], r["stale"]) == ("--", None, False)
        assert r["note"] == "no source"
    assert view["gear"] == {"text": "--", "measured": False}


@_NODE_ONLY
def test_drivingView_absentPid_isNotRead():
    view = _probe("drivingView", {"params": {}}, None, 0)
    assert view["readings"]["SPEED"]["text"] == "--"
    assert view["readings"]["SPEED"]["note"] == "not read"


@_NODE_ONLY
def test_drivingView_unbandedValue_carriesNoReasonText():
    """IAT no_band_defined and battery amber_not_shipped are by design, not
    faults: neutral, with no reason line (Iris G-1/G-2)."""
    assert _view("iat-neutral")["readings"]["INTAKE_TEMP"]["note"] == ""
    assert _view("battery-amber-gap")["readings"]["BATTERY_V"]["note"] == ""


@_NODE_ONLY
def test_drivingView_staleLastValue_convertsByTheSameUnit():
    coolant = _view("ecu-silent-stale")["readings"]["COOLANT_TEMP"]
    assert (coolant["text"], coolant["unit"], coolant["stale"]) == ("190", "°F", True)


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_theShippedDomPaintsTheView(name: str):
    """The renderer paints exactly what the view says: text, unit, note, the
    band/stale/note state attributes, and the gear glyph."""
    view = _view(name)
    surface = _boot(name)
    for pid in READING_PIDS:
        r = view["readings"][pid]
        path = _readingPath(surface, pid)
        attrs = path[-1]["attrs"]
        assert _textOf(_child(path, "drv-value")[-1]) == r["text"], (name, pid)
        assert _textOf(_child(path, "drv-unit")[-1]) == r["unit"], (name, pid)
        note = _child(path, "drv-note")
        assert _textOf(note[-1]) == r["note"], (name, pid)
        assert surface.rendered(note) == bool(r["note"]), (name, pid, "note box")
        assert attrs.get("data-band") == (r["band"] or "none"), (name, pid)
        assert attrs.get("data-stale") == ("true" if r["stale"] else "false"), (name, pid)
    gear = _drivingPaths(surface, "drv-gear")
    assert len(gear) == 1
    assert _textOf(gear[0][-1]) == view["gear"]["text"]
    assert gear[0][-1]["attrs"].get("data-measured") == (
        "true" if view["gear"]["measured"] else "false"
    )


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_valueColour_isTheProviderBand_orNeutral(name: str):
    view = _view(name)
    surface = _boot(name)
    for pid in READING_PIDS:
        r = view["readings"][pid]
        value = _child(_readingPath(surface, pid), "drv-value")
        colour = surface.winningDeclaration(value, "color")
        assert colour is not None, (name, pid)
        if pid in BANDED_PIDS and r["band"] is not None:
            assert colour[0] == BAND_TOKEN[r["band"]], (name, pid, colour)
        else:
            assert colour[0] == "var(--text-primary)", (name, pid, colour)


@_NODE_ONLY
def test_staleReading_isDimmed_andItsAgeIsAmber():
    surface = _boot("coolant-stale-last-red")
    path = _readingPath(surface, "COOLANT_TEMP")
    line = _child(path, "drv-line")
    opacity = surface.winningDeclaration(line, "opacity")
    assert opacity is not None and _number(opacity[0]) == pytest.approx(0.4)
    assert surface.winningDeclaration(_child(path, "drv-value"), "color")[0] == (
        "var(--critical-red)"
    )
    note = _child(path, "drv-note")
    assert surface.winningDeclaration(note, "color")[0] == "var(--amber-warn)"
    fresh = _readingPath(surface, "INTAKE_TEMP")
    assert surface.winningDeclaration(_child(fresh, "drv-line"), "opacity") is None


@_NODE_ONLY
def test_notReadReason_isNotAmber():
    surface = _boot("value-null-with-reason")
    note = _child(_readingPath(surface, "INTAKE_TEMP"), "drv-note")
    assert surface.winningDeclaration(note, "color")[0] == "var(--text-secondary)"


def test_theDrivingRenderUsesTheOneGearFetch():
    js = _read(_JS)
    start = js.index("lastGear = await stateOnce(")
    tail = js[start : start + 2000]
    assert "drivingView(" in tail and "lastGear" in tail[tail.index("drivingView(") :]


# ---------------------------------------------------------------------------
# 4. Type -- gear giant in Michroma, readings mono tabular >= 34 px.
# ---------------------------------------------------------------------------


def test_gear_isFsGiant_inMichroma400_withoutSynthesis():
    body = _rule("#driving-card .drv-gear")
    assert _decl(body, "font-size") == "var(--fs-giant)"
    assert _decl(body, "font-family") == "var(--font-display)"
    assert _decl(body, "font-weight") == "400"
    assert _decl(body, "font-synthesis") == "none"


def test_everyReading_isMonoTabular_atLeast34px():
    body = _rule("#driving-card .drv-value")
    assert _decl(body, "font-family") == "var(--font-mono)"
    assert _decl(body, "font-variant-numeric") == "tabular-nums"
    assert _px(_decl(body, "font-size") or "") >= 34
    unit = _rule("#driving-card .drv-unit")
    assert _decl(unit, "font-family") == "var(--font-mono)"


def test_labels_areMichroma_atFsMeta_letterSpacingZero_andMayWrap():
    body = _rule("#driving-card .drv-label")
    assert _decl(body, "font-family") == "var(--font-display)"
    assert _decl(body, "font-weight") == "400"
    assert _decl(body, "font-synthesis") == "none"
    assert _decl(body, "font-size") == "var(--fs-meta)"
    assert _decl(body, "letter-spacing") == "0"
    assert _decl(body, "white-space") in (None, "normal")


def test_noDrivingRuleSetsAFontBelow15px():
    for selector, body in _drivingRules():
        size = _decl(body, "font-size")
        if size is not None:
            assert _px(size) >= 15, (selector, size)


def test_everyMichromaStringIsInTheSubset():
    """Labels + gear are painted in the 38-glyph subset; a glyph outside it
    would fall back to another face (michromaWidthPx raises on one)."""
    labels = re.findall(r'<span class="drv-label">([^<]+)</span>', _drivingMarkup())
    assert sorted(labels) == sorted(["COOLANT", "INTAKE AIR", "RPM", "BATTERY"])
    for text in labels + ["1", "2", "3", "4", "5", "N", "P", "--"]:
        michromaWidthPx(text, 15)


# ---------------------------------------------------------------------------
# 5. The CSS gate -- tokens only; px only in the one scoped block.
# ---------------------------------------------------------------------------

_COLOUR_LITERAL = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(|(?<![\w-])(?:white|black|red|orange)(?![\w-])"
)
_PX_LITERAL = re.compile(r"(?<![\w-])[0-9.]+px\b")


def _gateViolations(rules: list[tuple[str, str]]) -> list[str]:
    bad = []
    for selector, body in rules:
        if "#driving-card" not in selector:
            bad.append(f"{selector}: a Driving rule not scoped to #driving-card")
        if _COLOUR_LITERAL.search(body):
            bad.append(f"{selector}: literal colour")
        if selector == "#driving-card":
            for decl in filter(None, (d.strip() for d in body.split(";"))):
                if not decl.startswith("--drv-"):
                    bad.append(f"{selector}: {decl} is not a scoped --drv- property")
        elif _PX_LITERAL.search(body):
            bad.append(f"{selector}: literal px outside the #driving-card block")
        # US-888-b: motion is allowed only on a data-attribute-qualified
        # selector (redline flash, gear glide); a bare rule would run always.
        if re.search(r"\b(?:animation|transition)\s*:", body) and not re.search(
            r"\[data-[\w-]+=\"[^\"]+\"\]", selector
        ):
            bad.append(f"{selector}: animation must be state-qualified")
    return bad


def test_cssGate_tokensOnly_pxOnlyInTheScopedBlock():
    rules = _drivingRules()
    assert len(rules) > 5, "the Driving rules were not found"
    assert _gateViolations(rules) == []


def test_cssGate_catchesAPlantedLiteral():
    planted = _drivingRules() + [
        ("#driving-card .drv-value", "margin-top: 4px; color: #fff"),
        ("#driving-card .drv-gear", "animation: drv-gear-glide-a var(--drv-glide-s)"),
    ]
    assert len(_gateViolations(planted)) == 3


def test_everyScopedPropertyIsConsumed():
    css = rh._stripComments(_read(DASHBOARD_CSS))
    for name in _scopedVars():
        assert f"var({name})" in css, f"{name} is declared and never used"


def test_layoutGeometry_isNotInRoot():
    root = re.search(r":root\s*\{(.*?)\}", rh._stripComments(_read(DASHBOARD_CSS)), re.S)
    assert root is not None and "--drv-" not in root.group(1)


# ---------------------------------------------------------------------------
# 6. Fit -- layout B at 480x320 from the shipped values (no clipping).
# ---------------------------------------------------------------------------

# The longest strings each slot can paint (the speed box holds 3 digits + mph;
# temps reach 3 digits in deg F; battery is xx.x V; RPM four digits, no unit).
WORST_SLOT_TEXT = {
    "COOLANT_TEMP": ("230", "°F"),
    "INTAKE_TEMP": ("113", "°F"),
    "BATTERY_V": ("14.1", "V"),
    "RPM": ("7000", ""),
}
NOTE_TEXT_WORST = "not read"


def _bodyHeightPx() -> float:
    css = _read(DASHBOARD_CSS)

    def token(name: str) -> float:
        m = re.search(rf"^\s*--{name}:\s*([0-9.]+)px", css, re.M)
        assert m is not None, name
        return float(m.group(1))

    stage = re.search(r"#stage\s*\{[^}]*?height:\s*([0-9.]+)px", rh._stripComments(css))
    height = float(stage.group(1)) if stage else 320.0
    return height - token("bar-h") - token("dots-h") - 2 * token("card-pad-y")


def _bodyWidthPx() -> float:
    pad = re.search(r"padding:\s*var\(--card-pad-y\)\s+([0-9.]+)px", _read(DASHBOARD_CSS))
    assert pad is not None
    return 480 - 2 * float(pad.group(1))


def _lineBox(sizeVar: str, lineVar: str) -> float:
    return _px(sizeVar) * _number(lineVar)


def _columnHeights(colPx: float) -> tuple[float, float]:
    """(tallest side column, centre column) in px, worst case: every reading
    stale (note line shown) and any label that does not fit on one line wraps."""
    label = _rule("#driving-card .drv-label")
    labelLine = _lineBox(_decl(label, "font-size") or "", _decl(label, "line-height") or "")
    line = _rule("#driving-card .drv-line")
    valueLine = _lineBox(
        _decl(_rule("#driving-card .drv-value"), "font-size") or "",
        _decl(line, "line-height") or "",
    )
    note = _rule("#driving-card .drv-note")
    noteLine = _lineBox(_decl(note, "font-size") or "", _decl(note, "line-height") or "")
    gap = _px(_decl(_rule("#driving-card .drv-col"), "gap") or "")

    def tile(text: str) -> float:
        # Charged at its WORST: a two-word label is allowed to wrap (INTAKE AIR
        # is 119 px against a 120 px column -- Iris: too tight to trust), and a
        # word wider than the column wraps too.
        oneLine = " " not in text and michromaWidthPx(text, _px("var(--fs-meta)")) <= colPx
        lines = 1 if oneLine else 2
        return lines * labelLine + valueLine + noteLine

    left = tile("COOLANT") + gap + tile("INTAKE AIR")
    right = tile("RPM") + gap + tile("BATTERY")
    gear = _rule("#driving-card .drv-gear")
    gearBox = _lineBox(_decl(gear, "font-size") or "", _decl(gear, "line-height") or "")
    box = _rule("#driving-card .drv-box")
    edge = _px(_decl(box, "border-width") or "")
    centreGap = _px(_decl(_rule("#driving-card .drv-centre"), "gap") or "")
    centre = gearBox + centreGap + valueLine + 2 * edge + noteLine
    return max(left, right), centre


def _mainHeightPx() -> float:
    body = _rule("#driving-card .card-body")
    gap = _px(_decl(body, "gap") or "")
    bar = _px(_decl(_rule("#driving-card .drv-rpm-bar"), "height") or "")
    return _bodyHeightPx() - bar - gap


def test_bodyIsTheUs887cBand():
    assert _bodyHeightPx() == 254


def test_layoutB_fitsTheBodyHeight_worstCase():
    side, centre = _columnHeights(_px("var(--drv-col)"))
    main = _mainHeightPx()
    assert side <= main, (side, main)
    assert centre <= main, (centre, main)


def test_layoutB_heightModel_failsAPlantedOverflow():
    """Negative control: the model is not vacuous. A column too narrow for its
    labels grows the stack, and the shipped stack would not fit the pre-F-127
    160 px body the band budget started from."""
    side, centre = _columnHeights(_px("var(--drv-col)"))
    assert _columnHeights(40)[0] > side
    assert max(side, centre) > 160


def _monoWidth(text: str, sizeVar: str) -> float:
    return len(text) * _px(sizeVar) * PI_MONO_ADVANCE_EM


def _readingWidth(value: str, unit: str) -> float:
    gap = _px(_decl(_rule("#driving-card .drv-unit"), "margin-inline-start") or "")
    width = _monoWidth(value, "var(--fs-primary)")
    if unit:
        width += gap + _monoWidth(unit, "var(--fs-label)")
    return width


def test_everySideReading_fitsItsColumn():
    col = _px("var(--drv-col)")
    for pid, (value, unit) in WORST_SLOT_TEXT.items():
        assert _readingWidth(value, unit) <= col, pid
    assert _monoWidth(NOTE_TEXT_WORST, "var(--fs-meta)") <= col


def test_widthModel_failsAPlantedWideReading():
    assert _readingWidth("14.12", "volts") > _px("var(--drv-col)")


def test_theCentreHoldsTheGearAndTheSpeedBox():
    centre = _bodyWidthPx() - 2 * _px("var(--drv-col)")
    for glyph in ["1", "2", "3", "4", "5", "N", "P", "--"]:
        assert michromaWidthPx(glyph, _px("var(--fs-giant)")) <= centre, glyph
    box = _rule("#driving-card .drv-box")
    pad = _px(_decl(box, "padding-inline") or "")
    edge = _px(_decl(box, "border-width") or "")
    assert _readingWidth("150", "mph") + 2 * (pad + edge) <= centre


def test_everyLabelWord_fitsItsColumn_soAWrapNeverClips():
    col = _px("var(--drv-col)")
    for label in ["COOLANT", "INTAKE AIR", "RPM", "BATTERY"]:
        for word in label.split():
            assert michromaWidthPx(word, _px("var(--fs-meta)")) <= col, word
