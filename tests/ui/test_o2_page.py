################################################################################
# File Name: test_o2_page.py
# Purpose/Description: US-891-c (F-127) tests for the O2 page
#   (specs/v030-o2-page-design.md s3-s7, layout A, stacked): FRONT and REAR
#   volts with their age and the provider's sample rate, a 5-minute dot trace
#   and the verdict chips, between Fuel and Motion. Guarded:
#     1. the fixtures -- the ten of spec s7, each the REAL provider's payload
#        (O2History + buildO2State over a scripted drive), regenerated here and
#        compared, so a fixture cannot drift from the producer;
#     2. the pure view (node): chips by the '_' -> space rule, the full meta
#        line from samplePeriodSec / windowSec, stale, null, absent, the trace
#        geometry and the mid-line from midlineV;
#     3. the SHIPPED DOM, painted by the real tick over every fixture;
#     4. the grep gates on the O2 code (no threshold, no AFR, no joining line,
#        no promise word) and the stylesheet rules (tokens only, one px, no
#        fixed height but the trace, no hidden overflow).
#   NOT GUARDED: layout on the glass (render_harness resolves the cascade, not
#   boxes): both rows and traces whole is the bigDefinitionOfDone screenshot.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-26    | Rex (US-891-c) | Initial -- the O2 page.
# ================================================================================
################################################################################

"""US-891-c tests for the O2 page."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

from pi.obdii.o2_state import O2History, O2Settings, buildO2State  # noqa: E402

_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_CSS = os.path.join(rh.DASHBOARD_DIR, "dashboard.css")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "o2")
_NODE = shutil.which("node")

_NODE_ONLY = pytest.mark.skipif(
    _NODE is None, reason="node not on PATH -- these tests run the shipped browser JS"
)

# --- 1. the fixtures, from the real provider ---------------------------------

# pi.display.stale.obdLiveSec and pi.display.o2.windowSec (validator DEFAULTS).
STALE_SEC = 5.0
WINDOW_SEC = 300.0
# One poll cycle (spec s2, Spool MEASURED ~2.2 s); within it the status, the
# coolant, the front and the rear are read back to back.
CYCLE_SEC = 2.2
STATUS_AT, COOLANT_AT, FRONT_AT, REAR_AT = 0.0, 0.3, 0.6, 0.9
FULL = 136  # cycles in a 5-minute window at today's rate (spec s3)
T0 = datetime(2026, 10, 26, 15, 0, 0, tzinfo=UTC)

SWITCHING = [0.12, 0.78, 0.20, 0.71, 0.48, 0.65, 0.15, 0.78]
REAR_LOW = [0.16, 0.18, 0.21, 0.18]

# name -> (description, cycles, front, rear, status, coolant, seconds from the
# last front read to the write)
SCENARIOS: dict[str, tuple[str, int, list[float], list[float], int, float, float]] = {
    "switching": ("closed loop, warm, the front swings both sides", FULL, SWITCHING,
                  REAR_LOW, 2, 90.0, 1.4),
    "stuck-lean": ("closed loop, warm, the front stays low", FULL, [0.08, 0.12, 0.15, 0.10],
                   REAR_LOW, 2, 90.0, 1.4),
    "stuck-rich": ("closed loop, warm, the front stays high", FULL, [0.78, 0.82, 0.75, 0.80],
                   REAR_LOW, 2, 90.0, 1.4),
    "unclear": ("closed loop, warm, the front hovers mid-range", FULL, [0.40, 0.52, 0.44, 0.50],
                REAR_LOW, 2, 90.0, 1.4),
    "not-enough-data": ("closed loop, warm, 30 samples only", 30, SWITCHING, REAR_LOW, 2,
                        90.0, 1.4),
    "open-loop": ("status 1 (open loop) the whole window", FULL, SWITCHING, REAR_LOW, 1,
                  90.0, 1.4),
    "cold-closed-loop": ("closed loop, coolant 80 C", FULL, SWITCHING, REAR_LOW, 2, 80.0, 1.4),
    "rear-held": ("rear read low on every sample, front switching", FULL, SWITCHING,
                  [0.15, 0.22, 0.26, 0.18], 2, 90.0, 1.4),
    "o2-null": ("neither sensor ever read, gate inputs live", FULL, [], [], 2, 90.0, 1.4),
    "stale": ("switching, then every reading stops 12 s before the write", FULL, SWITCHING,
              REAR_LOW, 2, 90.0, 12.0),
}
FIXTURE_NAMES = list(SCENARIOS)


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def buildFixture(name: str) -> dict[str, Any]:
    """One fixture: the scripted drive fed through the real O2History."""
    description, cycles, front, rear, status, coolant, gap = SCENARIOS[name]
    history = O2History(O2Settings(windowSec=WINDOW_SEC))
    lastFront = T0
    for i in range(cycles):
        base = T0 + timedelta(seconds=i * CYCLE_SEC)
        history.observe("FUEL_SYSTEM_STATUS", status, base + timedelta(seconds=STATUS_AT))
        history.observe("COOLANT_TEMP", coolant, base + timedelta(seconds=COOLANT_AT))
        lastFront = base + timedelta(seconds=FRONT_AT)
        if front:
            history.observe("O2_B1S1", front[i % len(front)], lastFront)
        if rear:
            history.observe("O2_B1S2", rear[i % len(rear)], base + timedelta(seconds=REAR_AT))
    now = lastFront + timedelta(seconds=gap)
    payload = buildO2State(history.snapshot(), nowUtc=now, staleSec=STALE_SEC)
    return {"description": description, "now": _iso(now), "o2": payload}


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _now(name: str) -> int:
    return _ms(_fixture(name)["now"])


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_isTheRealProvidersPayload(name):
    """
    Given: the committed fixture
    When: the same scripted drive is fed through O2History + buildO2State
    Then: the payload is identical -- the page is tested on what the Pi writes
    """
    assert _fixture(name) == json.loads(json.dumps(buildFixture(name)))


def test_fixtures_areExactlyTheSpecSet():
    """Spec s7's ten, and nothing else in the directory."""
    names = sorted(f[:-5] for f in os.listdir(_FIXTURES) if f.endswith(".json"))
    assert names == sorted(FIXTURE_NAMES)


def test_fixtures_coverEveryFrontToken():
    """Each provider verdict the page renders has a fixture behind it."""
    verdicts = {_fixture(n)["o2"]["frontVerdict"] for n in FIXTURE_NAMES}
    assert {"switching", "stuck_lean", "stuck_rich", "unclear", "not_enough_data",
            "open_loop", "warming_up"} <= verdicts


# --- 2. the pure view ----------------------------------------------------------


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


def _view(name: str, payload: Any = None, shiftMs: int = 0) -> dict[str, Any]:
    data = _fixture(name)["o2"] if payload is None else payload
    return _call("o2View", data, _now(name) + shiftMs)


FRONT_CHIP = {
    "switching": ("SWITCHING", True),
    "stuck-lean": ("STUCK LEAN", True),
    "stuck-rich": ("STUCK RICH", True),
    "unclear": ("unclear", False),
    "not-enough-data": ("not enough data", False),
    "open-loop": ("open loop", False),
    "cold-closed-loop": ("warming up", False),
    "rear-held": ("SWITCHING", True),
    "o2-null": ("not enough data", False),
    # The window still holds >= 60 gated samples, so the provider still rates.
    "stale": ("SWITCHING", True),
}


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_view_frontChip_isTheProvidersWord(name):
    chip = _view(name)["front"]["chip"]
    assert (chip["text"], chip["live"]) == FRONT_CHIP[name]


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_view_rearAndCatalyst_readNotRated(name):
    view = _view(name)
    assert view["rear"]["chip"] == {"text": "not rated", "live": False}
    assert view["catalyst"]["chip"] == {"text": "not rated", "live": False}


@_NODE_ONLY
def test_view_withheldWords_areTheTokenWithUnderscoresAsSpaces():
    """Every reason, including one the page has never seen (s3)."""
    for token, words in [
        ("not_enough_data", "not enough data"), ("open_loop", "open loop"),
        ("warming_up", "warming up"), ("no_data", "no data"), ("unclear", "unclear"),
        ("not_rated", "not rated"), ("some_new_reason", "some new reason"),
    ]:
        assert _call("o2Chip", token, token) == {"text": words, "live": False}
        assert "yet" not in words


@_NODE_ONLY
def test_view_switching_theFullMetaLine():
    """The story's example: 0.78 V, 2 s old, ~2.2 s, last 5 min."""
    front = _view("switching")["front"]["reading"]
    assert (front["text"], front["unit"]) == ("0.78", " V")
    assert front["meta"] == "2 s old · 1 sample / ~2.2 s · last 5 min"
    assert front["stale"] is False and front["none"] is False


@_NODE_ONLY
def test_view_rateAndWindow_comeFromTheProvider_neverALiteral():
    payload = dict(_fixture("switching")["o2"], samplePeriodSec=3.4, windowSec=600)
    meta = _view("switching", payload)["front"]["reading"]["meta"]
    assert meta == "2 s old · 1 sample / ~3.4 s · last 10 min"
    payload = dict(payload, samplePeriodSec=None)
    assert "~-- s" in _view("switching", payload)["front"]["reading"]["meta"]


@_NODE_ONLY
def test_view_stale_rendersTheLastValueDimmedWithItsAge():
    front = _view("stale")["front"]["reading"]
    assert _fixture("stale")["o2"]["front"]["value"] is None
    assert front["stale"] is True
    assert front["text"] == f"{_fixture('stale')['o2']['front']['last']['value']:.2f}"
    age = round((_now("stale") - _ms(_fixture("stale")["o2"]["front"]["ts"])) / 1000)
    assert age > STALE_SEC
    assert front["meta"].startswith(f"{age} s old · ")


@_NODE_ONLY
def test_view_null_isDashAndTheProvidersReason_neverZero():
    view = _view("o2-null")
    for side in ("front", "rear"):
        reading = view[side]["reading"]
        assert (reading["text"], reading["unit"], reading["meta"]) == ("--", "", "not read")
        assert reading["none"] is True
        assert view[side]["trace"]["dots"] == []


@_NODE_ONLY
def test_view_statesO2Absent_isNoSource():
    view = _call("o2View", None, _now("switching"))
    for side in ("front", "rear"):
        assert view[side]["reading"]["text"] == "--"
        assert view[side]["reading"]["meta"] == "no source"
        assert view[side]["chip"] == {"text": "no source", "live": False}
        assert view[side]["trace"] == {"midY": None, "dots": []}
    assert view["catalyst"]["chip"]["text"] == "no source"


@_NODE_ONLY
def test_view_trace_oneDotPerSample_atItsOwnTs_acrossTheWindow():
    data = _fixture("switching")["o2"]
    trace = _view("switching")["front"]["trace"]
    assert len(trace["dots"]) == len(data["front"]["samples"])
    xs = [d["x"] for d in trace["dots"]]
    assert xs == sorted(xs)
    assert 0 <= xs[0] and xs[-1] <= 456
    # The newest sample is ~2 s (whole-second ts) before the write: ~2/300 of 456 in.
    assert xs[-1] == pytest.approx(456 * (1 - 2 / 300), abs=3.1)
    # 0 V at the bottom, 1 V at the top, inside the 3-unit pad.
    lowest = min(range(len(xs)), key=lambda i: data["front"]["samples"][i]["v"])
    assert trace["dots"][lowest]["y"] > trace["midY"]


@_NODE_ONLY
def test_view_midline_isDrawnFromMidlineV():
    payload = _fixture("switching")["o2"]
    base = _view("switching")["front"]["trace"]["midY"]
    assert base == pytest.approx(3 + 38 * (1 - payload["midlineV"]), abs=0.05)
    moved = _view("switching", dict(payload, midlineV=0.2))["front"]["trace"]["midY"]
    assert moved == pytest.approx(3 + 38 * 0.8, abs=0.05)
    assert _view("switching", dict(payload, midlineV=None))["front"]["trace"]["midY"] is None


# --- 3. the shipped DOM ----------------------------------------------------------


def _classes(node: dict[str, Any]) -> list[str]:
    return (node.get("attrs", {}).get("class") or "").split()


def _find(node: Any, pred) -> list[dict[str, Any]]:
    if not isinstance(node, dict):
        return []
    out = [node] if pred(node) else []
    for child in node.get("children", []) or []:
        out += _find(child, pred)
    return out


def _rawText(node: dict[str, Any]) -> str:
    return "".join(c["text"] if "text" in c else _rawText(c)
                   for c in node.get("children", []))


def _one(node: dict[str, Any], cls: str) -> dict[str, Any]:
    hits = _find(node, lambda n: cls in _classes(n))
    assert len(hits) == 1, (cls, len(hits))
    return hits[0]


def _card(dom: dict[str, Any]) -> dict[str, Any]:
    roots = dom["tree"] if isinstance(dom["tree"], list) else [dom["tree"]]
    hits = [n for r in roots for n in _find(r, lambda n: n.get("attrs", {}).get("id") == "o2-card")]
    assert len(hits) == 1
    return hits[0]


def _boot(name: str, routes: dict[str, Any] | None = None) -> dict[str, Any]:
    r = {"/o2": _fixture(name)["o2"]} if routes is None else routes
    return _card(rh.runDashboard(routes=r, nowMs=_now(name), steps=[{"flush": 4}]))


def _row(section: dict[str, Any]) -> tuple[str, str]:
    line = _one(section, "o2-line")
    return _rawText(line), _rawText(_one(section, "o2-meta")).strip()


@_NODE_ONLY
@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_dom_everyFixture_paintsTheProvidersFields(name):
    card = _boot(name)
    view = _view(name)
    for cls, side in ((".o2-front", "front"), (".o2-rear", "rear")):
        section = _one(card, cls[1:])
        chip = _one(section, "o2-chip")
        assert _rawText(chip) == view[side]["chip"]["text"]
        assert chip["attrs"]["data-live"] == ("true" if view[side]["chip"]["live"] else "false")
        reading = view[side]["reading"]
        assert _row(section) == (reading["text"] + reading["unit"], reading["meta"])
        row = _one(section, "o2-row")
        assert row["attrs"]["data-stale"] == ("true" if reading["stale"] else "false")
        assert row["attrs"]["data-none"] == ("true" if reading["none"] else "false")
        dots = _find(section, lambda n: n.get("tag") == "circle")
        assert len(dots) == len(view[side]["trace"]["dots"])
        assert all(_classes(d) == ["o2-trace-dot"] for d in dots)
    assert _rawText(_one(_one(card, "o2-cat"), "o2-chip")) == "not rated"
    assert "0.00 V" not in _rawText(card)


@_NODE_ONLY
def test_dom_switching_theStoryExample():
    card = _boot("switching")
    front = _one(card, "o2-front")
    assert _rawText(_one(front, "o2-label")) == "FRONT  BEFORE CAT"
    assert _rawText(_one(_one(card, "o2-rear"), "o2-label")) == "REAR  AFTER CAT"
    assert _row(front) == ("0.78 V", "2 s old · 1 sample / ~2.2 s · last 5 min")
    assert _rawText(_one(front, "o2-chip")) == "SWITCHING"
    assert _rawText(_one(_one(card, "o2-rear"), "o2-chip")) == "not rated"


@_NODE_ONLY
def test_dom_traceIsDotsOnly_withTheDashedMidline():
    card = _boot("switching")
    assert not _find(card, lambda n: n.get("tag") in ("polyline", "path", "polygon"))
    for cls in ("o2-front", "o2-rear"):
        svg = _one(_one(card, cls), "o2-trace")
        mids = _find(svg, lambda n: "o2-trace-mid" in _classes(n))
        assert len(mids) == 1 and mids[0]["attrs"]["y1"] == mids[0]["attrs"]["y2"]
        lines = _find(svg, lambda n: n.get("tag") == "line")
        assert lines == mids


@_NODE_ONLY
def test_dom_statesO2Absent_isDashAndNoSource_neverZero():
    card = _boot("switching", routes={})
    for cls in ("o2-front", "o2-rear"):
        section = _one(card, cls)
        assert _row(section) == ("--", "no source")
        assert not _find(section, lambda n: n.get("tag") in ("circle", "line"))
    assert "0.00" not in _rawText(card)


@_NODE_ONLY
def test_dom_theCardSitsBetweenFuelAndMotion_namedO2():
    card = _boot("switching")
    assert card["attrs"]["aria-label"] == "O2"
    assert card["attrs"]["data-page-name"] == "O2"
    html = open(_HTML, encoding="utf-8").read()
    order = re.findall(r'<section class="card"[^>]*?aria-label="([^"]+)"', html, re.S)
    i = order.index("O2")
    assert order[i - 1:i + 2] == ["Fuel", "O2", "Motion"]


# --- 4. grep gates: the O2 code and its rules ------------------------------------


def _o2Js() -> str:
    """The O2 sections of carousel.js: the pure view and the DOM render."""
    js = open(_JS, encoding="utf-8").read()
    pure = js[js.index("// --- US-891-c O2 page (F-127)"):js.index("// --- US-889-c Engine card")]
    dom = js[js.index("// --- US-891-c O2 page DOM render"):js.index("// --- US-893-b Light page DOM")]
    return pure + dom


def test_grep_o2Code_holdsNoThresholdNoAfrNoJoinNoPromise():
    code = _o2Js()
    assert "renderO2Card" in code and "o2View" in code
    for literal in ("0.30", "0.45", "0.60", "0.90"):
        assert literal not in code, literal
    assert "AFR" not in code
    assert "polyline" not in code and '"path"' not in code
    assert not re.search(r"\byet\b", code, re.I)


def _o2Rules() -> list[rh.Rule]:
    css = open(_CSS, encoding="utf-8").read()
    rules = [r for r in rh.parseCss(css) if r.selector.startswith("#o2-card")]
    assert rules, "no O2 rules"
    return rules


def test_css_o2Rules_tokensOnly_theOnePxIsTheTraceHeight():
    for rule in _o2Rules():
        body = rule.declarations
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", body), rule.selector
        for decl in filter(None, (d.strip() for d in body.split(";"))):
            if "px" in decl:
                assert decl == "--o2-trace-h: 44px", (rule.selector, decl)


def test_css_noClipping_byRule():
    """No fixed height but the trace's, and nothing hides overflow (s6 AC 7)."""
    for rule in _o2Rules():
        for decl in filter(None, (d.strip() for d in rule.declarations.split(";"))):
            prop, _, value = decl.partition(":")
            prop, value = prop.strip(), value.strip()
            if prop in ("height", "max-height", "block-size", "max-block-size"):
                assert (rule.selector, value) == ("#o2-card .o2-trace", "var(--o2-trace-h)")
            if prop.startswith("overflow"):
                assert value != "hidden", rule.selector


def _decl(selector: str, prop: str) -> str | None:
    for rule in _o2Rules():
        if rule.selector == selector:
            found = rh.declarationOf(rule.declarations, prop)
            if found is not None:
                return found[0]
    return None


def test_css_faces_andSizes():
    """Labels + live chip Michroma; withheld chip mono --fs-label; volts primary."""
    assert _decl("#o2-card .o2-label", "font-family") == "var(--font-display)"
    assert _decl("#o2-card .o2-label", "font-size") == "var(--fs-meta)"
    assert _decl('#o2-card .o2-chip[data-live="true"]', "font-family") == "var(--font-display)"
    assert _decl('#o2-card .o2-chip[data-live="false"]', "font-family") == "var(--font-mono)"
    assert "dashed" in (_decl('#o2-card .o2-chip[data-live="false"]', "border") or "")
    assert _decl('#o2-card .o2-chip[data-live="false"]', "color") == "var(--text-tertiary)"
    assert _decl("#o2-card .o2-chip", "font-size") == "var(--fs-label)"
    assert _decl("#o2-card .o2-value", "font-size") == "var(--fs-primary)"
    assert _decl("#o2-card .o2-meta", "font-family") == "var(--font-mono)"
    assert _decl("#o2-card .o2-meta", "font-size") == "var(--fs-meta)"
    # The live verdict is a description, not a severity: no state colour.
    live = _decl('#o2-card .o2-chip[data-live="true"]', "color")
    assert live == "var(--text-primary)"
    assert "dasharray" in "".join(r.declarations for r in _o2Rules()
                                  if r.selector == "#o2-card .o2-trace-mid")


if __name__ == "__main__":
    # Regenerate the fixtures from the real provider.
    os.makedirs(_FIXTURES, exist_ok=True)
    for fixtureName in FIXTURE_NAMES:
        with open(os.path.join(_FIXTURES, fixtureName + ".json"), "w",
                  encoding="utf-8", newline="\n") as out:
            json.dump(buildFixture(fixtureName), out, indent=2, ensure_ascii=False)
            out.write("\n")
