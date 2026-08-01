################################################################################
# File Name: test_carousel_health_card.py
# Purpose/Description: US-507 (F-124) tests -- the merged "Health" card. The
#   Battery Health + Light + LTFT-Trend cards are consolidated into ONE card so
#   the carousel is fewer screens (CIO 2026-07-31). This is a RELOCATION, not a
#   redesign, so the tests are written to prove exactly that:
#     1. Composition -- three sections in the locked order (Battery, Light,
#        Fuel Trim) inside one card, with "LTFT Trend" retitled to the plain
#        "Fuel Trim" and Spool's LTFT SEMANTICS untouched.
#     2. Section INDEPENDENCE -- a dead UPS grays the Battery section alone and
#        never blanks the live Light reading beside it. Merging three cards must
#        not merge their failures; that would be a new (and dishonest) coupling.
#     3. Every honest-instrument state of all three sources survives the move:
#        the battery F-9 stale-green data-age guard, the light null/stale
#        individual graying, the fuel-trim insufficient-never-green rule.
#     4. The fuel-trim VEHICLE GATE, whose vocabulary necessarily changes with
#        the merge. As a standalone card the gate HID it ("does not apply right
#        now"). A section inside an always-visible card cannot vanish without
#        leaving a hole, so it renders the honest words "no engine data" --
#        never a fabricated 0%, and never confused with "the feed is broken".
#   Pure logic runs through the shared node probe (tests/ui/carousel_probe.js);
#   the browser-only DOM wiring is pinned by reading the shipped artifacts, since
#   a correct routine the tick never calls renders nothing (US-494/US-495).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-31    | Ralph (Rex)  | Initial -- US-507 merged Health card (6 -> 4).
# ================================================================================
################################################################################

"""US-507 tests for the merged Health card (Battery + Light + Fuel Trim)."""

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "specs", "UI", "dist", "dashboard-pi"
)
_HTML = os.path.join(_DIST, "dashboard.html")
_JS = os.path.join(_DIST, "carousel.js")

# A fixed read-time + its epoch-ms so every freshness assertion is deterministic.
_TS = "2026-07-31T12:00:00+00:00"
_TS_MS = int(datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _view(fn: str, *args: object) -> object:
    """Evaluate one carousel.js export against fixtures via the node probe."""
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _fnBody(js: str, name: str) -> str:
    """The source text of one `function <name>(` up to the next top-level one.

    Crude but sufficient: it lets a wiring test assert what a SPECIFIC routine
    references, instead of grepping the whole 3400-line file where a match could
    come from anywhere (the coincidence US-495 warned about).
    """
    start = js.index("function " + name + "(")
    candidates = [
        js.find("\n  function ", start + 1),
        js.find("\n    function ", start + 1),
        js.find("\n      function ", start + 1),
    ]
    ends = [e for e in candidates if e != -1]
    return js[start : min(ends)] if ends else js[start:]


def _stripJsComments(js: str) -> str:
    """carousel.js with `//` and block comments removed, string literals intact.

    A pin that greps for an identifier's NAME fires on its own documentation.
    The first cut of the renamed-renderer test below asserted
    `"renderLtftTrendCard" not in js` and went RED against correct code, because
    the comment marking the deleted branch NAMES the function it replaced. Prose
    is not a call site, so that pin has to read code only.

    String-aware deliberately: `"http://www.w3.org/2000/svg"` (carousel.js:2331)
    loses its tail to a naive line-comment strip. Over-stripping is the
    dangerous direction for an ABSENCE assertion -- it removes the very text the
    test hunts for and passes VACUOUSLY -- so the stripper is itself pinned by
    test_stripJsComments_* before any assertion trusts it.
    """
    out: list[str] = []
    i, n = 0, len(js)
    quote: str | None = None
    while i < n:
        ch = js[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:  # an escaped quote does not close it
                out.append(js[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and js[i + 1] == "/":
            while i < n and js[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and js[i + 1] == "*":
            end = js.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# --- fixtures ---------------------------------------------------------------


def _battery(**extra: object) -> dict:
    """A states/battery-health payload as the US-401 emitter writes it."""
    payload: dict = {
        "health": "green",
        "vcellV": 4.02,
        "soc": 88,
        "socCalibrated": True,
        "draining": False,
        "lastHealthCheckTs": "2026-07-01T09:00:00+00:00",
        "ts": _TS,
    }
    payload.update(extra)
    return payload


def _light(lux: float | None = 412.0, **extra: object) -> dict:
    """A states/light payload as light_state_bridge.buildLightState writes it."""
    payload: dict = {"lux": lux, "ts": _TS}
    payload.update(extra)
    return payload


def _ltft(*, sufficient: bool = True, **extra: object) -> dict:
    """A states/ltft-trend payload as the US-420 emitter writes it."""
    payload: dict = {
        "sufficient": sufficient,
        "level": "ok",
        "trend": "improving",
        "minDrives": 2,
        "current": {"ltftAvg": -2.5},
        "points": [
            {"driveId": 30, "ltftAvg": -6.25, "level": "ok"},
            {"driveId": 31, "ltftAvg": -2.5, "level": "ok"},
        ],
        "ts": _TS,
    }
    payload.update(extra)
    return payload


def _sys(*, obdAvailable: bool) -> dict:
    """A states/system-status payload -- only the OBD source matters here."""
    return {
        "source": {"obd": {"available": obdAvailable, "reason": None}},
        "ts": _TS,
    }


def _health(
    *,
    battery: object = "default",
    light: object = "default",
    ltft: object = "default",
    obdAvailable: bool = True,
    sysData: object = "default",
) -> dict:
    """Run healthCardView over the three state files + system-status."""
    states = {
        "battery-health": _battery() if battery == "default" else battery,
        "light": _light() if light == "default" else light,
        "ltft-trend": _ltft() if ltft == "default" else ltft,
    }
    sys_ = _sys(obdAvailable=obdAvailable) if sysData == "default" else sysData
    return _view("healthCardView", states, sys_, None, _TS_MS)  # type: ignore[return-value]


def _section(view: dict, key: str) -> dict:
    for sec in view["sections"]:
        if sec["key"] == key:
            return sec
    raise AssertionError(f"no {key} section in {[s['key'] for s in view['sections']]}")


# ---------------------------------------------------------------------------
# AC-1 / AC-3 -- three sources, one card, in the locked order.
# ---------------------------------------------------------------------------


def test_healthCardView_mergesThreeSourcesInTheLockedOrder():
    """
    Given: all three state files readable and a vehicle connected
    Then: ONE view carries exactly three sections, Battery then Light then
          Fuel Trim

    The order is the CIO-locked reading order (the two Pi-local always-available
    readouts first, the vehicle-dependent one last), not an accident of which
    card happened to be declared first in the old markup.
    """
    view = _health()
    assert [s["key"] for s in view["sections"]] == [
        "battery-health",
        "light",
        "ltft-trend",
    ]


def test_healthCardView_fuelTrimSectionIsPlainEnglish_notJargon():
    """
    Given: the merged card
    Then: the fuel-trim section is titled "Fuel Trim", never "LTFT Trend"

    AC-2 is a LABEL change only. The jargon leaves the title; Spool's LTFT
    semantics stay exactly where they were (proved by the sufficiency +
    drift tests below, which are the old card's rules unchanged).
    """
    sec = _section(_health(), "ltft-trend")
    assert sec["title"] == "Fuel Trim"
    assert "LTFT Trend" not in sec["title"]


def test_healthCardView_sectionTitlesNameTheirInstrument():
    """Each section is self-labelling -- with three readouts stacked on one card
    an unlabelled block is ambiguous in a way a whole card never was."""
    view = _health()
    assert _section(view, "battery-health")["title"] == "Battery"
    assert _section(view, "light")["title"] == "Light"


# ---------------------------------------------------------------------------
# AC-4 -- every honest-instrument state of the three sources survives the move.
# ---------------------------------------------------------------------------


def test_healthCardView_batterySection_keepsTheStaleGreenGuard():
    """
    Given: a GREEN battery verdict whose last health check is a month old
    Then: the section still carries the "last health check ... (N days ago)"
          line

    F-9 is the trap this card was built around: a month-old GREEN must never
    read as live. Relocating the card must not drop the guard that made it
    honest.
    """
    sec = _section(_health(), "battery-health")
    assert sec["view"]["health"]["value"] == "HEALTHY"
    assert "last health check" in sec["view"]["health"]["detail"]
    assert "30 days ago" in sec["view"]["health"]["detail"]


def test_healthCardView_batterySection_keepsVoltsNeverPercent():
    """F-8: a null SoC omits the percent and shows volts. A voltage rendered as
    a percent is the render-breaking trap Spool named for this source."""
    sec = _section(_health(battery=_battery(soc=None)), "battery-health")
    assert sec["view"]["vcell"]["value"] == "4.02 V"
    assert sec["view"]["soc"]["shown"] is False


def test_healthCardView_batterySection_keepsTheDrainLadder():
    """F-2/A-6: the failsafe ladder exists ONLY while actually draining -- it
    rides along with the section rather than being lost in the merge."""
    sec = _section(_health(battery=_battery(draining=True)), "battery-health")
    assert sec["view"]["ladder"] is not None


def test_healthCardView_lightSection_rendersTheRealLux():
    """The light section is still a pure consumer of the SAME states/light file
    that drives the auto-dim, so the number can never disagree with the screen
    it explains."""
    sec = _section(_health(), "light")
    assert sec["view"]["ambient"]["value"] == "412 lx"
    assert sec["view"]["band"]["value"] != "NA"


def test_healthCardView_lightSection_nullLuxGraysWithinTheSection():
    """
    Given: a null lux (the bridge's honest saturated/unreadable marker)
    Then: the AMBIENT + CONDITION fields gray INDIVIDUALLY -- the section is
          still present and is NOT promoted to a whole-section NA

    The old card grayed fields, not itself. Escalating that to a section-level
    NA in the merge would LOSE information (which of the two fields is dead).
    """
    sec = _section(_health(light=_light(None)), "light")
    assert sec["unavailable"] is False
    assert sec["view"]["ambient"]["value"] == "NA"
    assert sec["view"]["band"]["value"] == "NA"


def test_healthCardView_fuelTrimSection_insufficientIsNeverGreen():
    """The insufficient-window guard is Spool's, and it survives the retitle: too
    little data can never paint a confident healthy verdict."""
    ltft = _ltft(sufficient=False, points=[], current=None)
    sec = _section(_health(ltft=ltft), "ltft-trend")
    assert sec["view"]["headline"]["level"] == "insufficient"
    assert sec["view"]["headline"]["value"] == "insufficient data"


def test_healthCardView_fuelTrimSection_driftRendersItsOwnLevel():
    """A drive beyond +/-10% keeps its own non-green level -- the semantics the
    emitter classifies, which this view only maps."""
    ltft = _ltft(level="down", points=[{"driveId": 32, "ltftAvg": 12.5, "level": "down"}])
    sec = _section(_health(ltft=ltft), "ltft-trend")
    assert sec["view"]["headline"]["level"] == "down"
    assert sec["view"]["points"][0]["value"] == "+12.50%"


# ---------------------------------------------------------------------------
# AC-4 -- SECTION INDEPENDENCE. Merging three cards must not merge their
# failures; the old cards failed one at a time and so must the sections.
# ---------------------------------------------------------------------------


def test_healthCardView_deadUpsDoesNotBlankTheLiveLightReading():
    """
    Given: the UPS source is unavailable but the light feed is live
    Then: the Battery section reports its own NA and the Light section still
          renders the real lux

    This is THE risk the merge introduces. On separate cards a dead UPS could
    only ever blank its own card. Route the merged card through one card-level
    availability check and one dead feed silently blanks two live instruments --
    a fabricated "nothing is readable" built out of one real fault.
    """
    dead = {"source": {"ups": {"available": False, "reason": "UPS: I2C read failed"}}}
    view = _health(battery=dead)
    battery = _section(view, "battery-health")
    light = _section(view, "light")
    assert battery["view"]["unavailable"] is True
    assert light["view"]["ambient"]["value"] == "412 lx"


def test_healthCardView_absentLightFileDoesNotBlankTheBatterySection():
    """The inverse direction -- an ABSENT state file (not merely a degraded
    source) must also stay contained to its own section."""
    view = _health(light=None)
    assert _section(view, "light")["unavailable"] is True
    assert _section(view, "battery-health")["view"]["health"]["value"] == "HEALTHY"


def test_healthCardView_absentSection_namesItsSilentInstrument():
    """
    Given: an absent state file
    Then: the section says WHICH instrument is silent

    On a standalone card the card title supplied that context. Stacked three
    deep, a bare "unavailable" no longer says which of three readouts died.
    """
    view = _health(battery=None, light=None)
    assert _section(view, "battery-health")["na"]["reason"].lower().startswith("no data")
    assert "no data" in _section(view, "light")["na"]["reason"].lower()


# ---------------------------------------------------------------------------
# AC-2 -- the fuel-trim VEHICLE GATE, in its new (section) vocabulary.
# ---------------------------------------------------------------------------


def test_healthCardView_benchNoVehicle_fuelTrimReadsNoEngineData():
    """
    Given: a bench Pi -- system-status reports source.obd.available false
    Then: the Fuel Trim section reads the honest "no engine data"

    The gate's vocabulary NECESSARILY changes with the merge. A standalone card
    could be HIDDEN, which says "this does not apply right now". A section
    inside an always-visible card cannot vanish without leaving a hole, so the
    same fact is spoken instead of shown.
    """
    sec = _section(_health(obdAvailable=False), "ltft-trend")
    assert sec["gated"] is True
    assert sec["na"]["reason"] == "no engine data"


def test_healthCardView_benchNoVehicle_fuelTrimLeaksNoValueEvenWithAState():
    """
    Given: NO vehicle, but a complete and perfectly readable ltft-trend file
    Then: the section still renders the gate, carrying NO trim value at all

    The load-bearing one. A stale ltft-trend file left on disk from the last
    drive is exactly the input that would let a bench render a confident fuel
    trim for an engine that is not running. The gate must beat the data, not
    lose to it -- so the view carries no reading to leak.
    """
    sec = _section(_health(obdAvailable=False, ltft=_ltft()), "ltft-trend")
    assert sec["gated"] is True
    assert sec["view"] is None
    assert "-2.50%" not in json.dumps(sec)


def test_healthCardView_vehicleConnected_fuelTrimRendersTheRealTrend():
    """The inverse -- without it "always gate" would pass. A connected vehicle
    reveals the real trend, which is the whole point of keeping the section."""
    sec = _section(_health(obdAvailable=True), "ltft-trend")
    assert sec["gated"] is False
    assert sec["view"]["headline"]["value"] == "-2.50%"


def test_healthCardView_absentSystemStatus_failsClosedToGated():
    """No readable system-status -> "is a car connected?" is UNKNOWN, and an
    unknown must never render as a state -> fail closed to the gate, exactly as
    the card-level gate did (US-496)."""
    sec = _section(_health(sysData=None), "ltft-trend")
    assert sec["gated"] is True


def test_healthCardView_gatedAndBrokenAreDistinctStates():
    """
    Given: a vehicle IS connected but the ltft-trend file is absent
    Then: the section reads a no-data fault, NOT the "no engine data" gate

    Two different facts -- "the instrument does not apply" vs "the instrument is
    broken". Collapsing them would tell an operator with a running engine that
    there is no engine.
    """
    sec = _section(_health(obdAvailable=True, ltft=None), "ltft-trend")
    assert sec["gated"] is False
    assert sec["unavailable"] is True
    assert sec["na"]["reason"] != "no engine data"


def test_healthCardView_batteryAndLightAreNeverVehicleGated():
    """AC-2: Battery + Light stay available regardless of a vehicle -- they are
    PI-LOCAL sensors that read on a bench with no car. Gating them would blank a
    working instrument, the exact bench-validatability US-496 fought for."""
    view = _health(obdAvailable=False)
    assert _section(view, "battery-health")["gated"] is False
    assert _section(view, "light")["gated"] is False
    assert _section(view, "battery-health")["view"]["health"]["value"] == "HEALTHY"


# ---------------------------------------------------------------------------
# Wiring -- the shipped artifacts actually carry + call the logic above.
# ---------------------------------------------------------------------------


def test_dashboardHtml_shipsOneHealthCardWithThreeSectionSlots():
    """AC-1: the merged card exists in the markup with a slot per source. The
    tick discovers cards from the markup, so no slot = no section, whatever the
    JS says (US-494)."""
    html = _read(_HTML)
    assert 'aria-label="Health"' in html
    # Count section ROOTS only -- `health-section-title` / `-body` share the
    # prefix, so a prefix count would read 9 and pass for the wrong reason.
    roots = re.findall(r'class="health-section [\w-]+"', html)
    assert len(roots) == 3, f"expected 3 section roots, found {roots}"
    for cls in ("health-battery", "health-light", "health-fueltrim"):
        assert cls in html, f"missing the {cls} section slot"


def test_dashboardHtml_dropsTheTwoNowMergedStandaloneCards():
    """AC-3: the three merged sources no longer own standalone cards. Leaving a
    duplicate card behind would render the same reading twice and let the two
    copies disagree."""
    html = _read(_HTML)
    assert 'data-state="battery-health"' not in html
    assert 'data-state="light"' not in html
    assert 'data-state="ltft-trend"' not in html


def test_dashboardHtml_healthCardDeclaresItsThreeSourceStates():
    """The merged card is a MULTI-SOURCE card: it names every state file it
    consumes so the tick fetches all three (a section whose state is never
    fetched renders a permanent no-data)."""
    html = _read(_HTML)
    match = re.search(r'<section[^>]*aria-label="Health"[^>]*>', html, re.S)
    assert match is not None
    decl = match.group(0)
    for name in ("battery-health", "light", "ltft-trend"):
        assert name in decl, f"the Health card does not declare the {name} state"


def test_dashboardHtml_cardOrderIsSystemStatusThenHealthThenAlerts():
    """AC-3: the reading order the CIO locked -- the diagnostics card, then the
    reference readouts, then the alerts."""
    html = _read(_HTML)
    order = [
        html.index('aria-label="System Status"'),
        html.index('aria-label="Health"'),
        html.index('aria-label="Alerts"'),
    ]
    assert order == sorted(order), "the carousel order drifted from the locked one"


def test_carouselJs_tickRendersTheHealthCard():
    """The merged card is wired into the poll -- a view function nothing calls
    renders nothing (the US-494 default-argument lesson, one story after it cost
    a whole story)."""
    tick = _fnBody(_read(_JS), "tick")
    assert "healthCardView" in tick
    assert "renderHealthCard" in tick


def test_carouselJs_healthCardGateReadsTheSameSystemStatus():
    """The fuel-trim gate resolves against the system-status the tick already
    fetched -- a second independent read could disagree with the vehicle state
    the rest of the card was rendered against."""
    tick = _fnBody(_read(_JS), "tick")
    assert re.search(r'stateOnce\(\s*"system-status"\s*\)', tick), (
        "the health path must resolve its gate from the shared per-tick state"
    )


def test_carouselJs_healthSectionsReuseTheTokenizedTile():
    """The merged sections render through the shared `.tile` component, already
    bound to specs/UI/tokens.css. A bespoke health-card palette is exactly the
    drift the SSOT rule exists to prevent."""
    render = _fnBody(_read(_JS), "renderHealthCard")
    assert "renderHealthSection" in render


def test_carouselJs_gatedSectionMarksItselfInTheDom():
    """The gate is readable off the rendered DOM, so the render-regression
    backstop can prove the gated section painted the gate rather than the
    data -- the check no pure-function test can make."""
    render = _fnBody(_read(_JS), "renderHealthSection")
    assert "data-gated" in render


def test_carouselJs_hasNoDanglingCallsToTheRenamedCardRenderers():
    """
    Given: the three card renderers became BODY renderers in this story
    Then: no call site still names the old card-taking functions

    Found by inspection, not by a failing test, and that is the point: the dead
    `ltft-trend` branch still called `renderLtftTrendCard` after the rename. No
    card carries that state any more, so nothing executed it -- and nothing
    proved it still resolved either. It would have thrown a ReferenceError the
    day a card re-declared that state. Same shape as the US-500 defect: the
    dangerous line is the one that never runs.
    """
    js = _stripJsComments(_read(_JS))
    for gone in (
        "renderLtftTrendCard",
        "renderLightCard",
        "renderBatteryHealthCard",
    ):
        assert gone not in js, f"{gone} was renamed but is still referenced"


def test_stripJsComments_keepsCodeAndCommentLookalikeStrings():
    """
    Given: the absence pin above reads comment-stripped source
    Then: the stripper removes prose WITHOUT eating code or string literals

    A stripper that over-strips makes every `not in` assertion pass VACUOUSLY --
    the one failure mode an absence test must not have. So it is pinned against
    the shipped file before it is trusted: code landmarks survive, and so does
    the SVG namespace string, which CONTAINS `//` and is exactly what a naive
    line-comment strip would truncate.
    """
    src = _stripJsComments(_read(_JS))
    assert "function renderHealthCard(" in src
    assert "function renderLtftTrendBody(" in src
    assert "http://www.w3.org/2000/svg" in src
    # ...and prose genuinely goes (this sentence exists only in a comment).
    assert "A branch no card can reach is not harmless" not in src


def test_stripJsComments_removesBothCommentFormsAndSpansLines():
    """The two comment syntaxes, and a block comment that spans lines -- pinned
    on a synthetic sample so a failure names the stripper, not carousel.js."""
    src = _stripJsComments(
        'var a = 1; // renderLightCard\n'
        "/* renderLightCard\n   still a comment */\n"
        "var b = \"// not a comment\";\n"
    )
    assert "renderLightCard" not in src
    assert "var a = 1;" in src
    assert "var b" in src
    assert "// not a comment" in src


def test_carouselJs_fetchesEachStateOnlyOncePerTick():
    """The Health card and the auto-dim both consume states/light. Fetching it
    twice in one tick could resolve the card and the screen brightness against
    two DIFFERENT readings -- the contradiction US-496 removed by sharing the
    payload, preserved here through a per-tick cache."""
    tick = _fnBody(_read(_JS), "tick")
    assert "stateOnce" in tick
    assert "lightFetched" not in tick, (
        "the ad-hoc single-consumer flag should be gone -- the cache replaces it"
    )
