################################################################################
# File Name: test_carousel_source_cards.py
# Purpose/Description: Tests for the three SOURCE CARDS -- Battery, Light and
#   Fuel Trim. These three were standalone cards, became sections of the US-507
#   merged "Health" card (6 -> 4 screens, CIO 2026-07-31), and are cards again
#   under US-540-b (4 -> 6) because the US-540-a legibility scale leaves a card
#   affording ~3 facts and Health was carrying six.
#
#   The file survives all three arrangements because its subject never changed:
#   the per-source HONEST-INSTRUMENT rules, which have travelled through every
#   layout because each source is read through the SAME view function each time.
#   That is why the coverage below is worth porting rather than deleting with
#   the card -- the arrangement was never what it was testing.
#     1. Composition -- three source cards in the locked order (Battery, Light,
#        Fuel Trim), with "LTFT Trend" retitled to the plain "Fuel Trim" and
#        Spool's LTFT SEMANTICS untouched.
#     2. INDEPENDENCE -- a dead UPS grays Battery alone and never blanks the
#        live Light reading. This was the merge's hardest property to keep; the
#        split makes it structural, and these tests are what prove it did not
#        get lost in the other direction (one card's fault speaking for its
#        neighbours) while the code was moving.
#     3. Every honest-instrument state of all three sources: the battery F-9
#        stale-green data-age guard, the light null/stale individual graying,
#        the fuel-trim insufficient-never-green rule.
#     4. The fuel-trim VEHICLE GATE. As a pre-US-507 standalone card the gate
#        HID it ("does not apply right now"). US-507 had to make it SPEAK ("no
#        engine data") because a section cannot vanish without leaving a hole,
#        and US-540-b KEEPS the speaking version even though a card could hide
#        again -- six cards are locked, and a card that disappears on a bench
#        breaks the set where the panel is read most days. Never a fabricated
#        0%, and never confused with "the feed is broken".
#   Pure logic runs through the shared node probe (tests/ui/carousel_probe.js);
#   the browser-only DOM wiring is pinned by reading the shipped artifacts, since
#   a correct routine the tick never calls renders nothing (US-494/US-495).
#   The card SET itself (which cards, in what order, how many) is US-540-b's
#   own gate -- tests/ui/test_carousel_card_set.py.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-31    | Ralph (Rex)  | Initial -- US-507 merged Health card (6 -> 4).
# 2026-08-11    | Ralph (Rex)  | US-540-b: Health retires; renamed from
#               |              | test_carousel_health_card.py and retargeted
#               |              | onto sourceCardView (one card per source).
# ================================================================================
################################################################################

"""Tests for the Battery / Light / Fuel Trim source cards."""

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
        "health": "good",
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


def _cards(
    *,
    battery: object = "default",
    light: object = "default",
    ltft: object = "default",
    obdAvailable: bool = True,
    sysData: object = "default",
) -> dict:
    """Run sourceCardView for EACH source -> {stateName: view}.

    Deliberately one probe call per card, mirroring the tick: the tick renders
    one card at a time, so a helper that composed all three in a single call
    would be testing a seam the shipped code no longer has.
    """
    payloads = {
        "battery-health": _battery() if battery == "default" else battery,
        "light": _light() if light == "default" else light,
        "ltft-trend": _ltft() if ltft == "default" else ltft,
    }
    sys_ = _sys(obdAvailable=obdAvailable) if sysData == "default" else sysData
    specs = _view("sourceCardSpecs")
    return {
        spec["key"]: _view("sourceCardView", spec, payloads[spec["key"]], sys_, None, _TS_MS)
        for spec in specs  # type: ignore[union-attr]
    }


def _section(cards: dict, key: str) -> dict:
    if key not in cards:
        raise AssertionError(f"no {key} card in {sorted(cards)}")
    return cards[key]


# ---------------------------------------------------------------------------
# Composition -- three sources, one card each, in the locked order.
# ---------------------------------------------------------------------------


def test_sourceCardSpecs_carriesTheThreeSourcesInTheLockedOrder():
    """
    Given: the shipped source-card table
    Then: exactly three specs, Battery then Light then Fuel Trim

    The order is the CIO-locked reading order (the two Pi-local always-available
    readouts first, the vehicle-dependent one last). Under US-540-b it is also
    the CAROUSEL order, so the table and the markup have to agree -- which
    tests/ui/test_carousel_card_set.py pins from the markup side.
    """
    specs = _view("sourceCardSpecs")
    assert [s["key"] for s in specs] == [  # type: ignore[union-attr]
        "battery-health",
        "light",
        "ltft-trend",
    ]


def test_sourceCardSpec_resolvesAStateNameAndRejectsAnUnknownOne():
    """
    Given: the lookup the tick uses to decide "is this a source card?"
    Then: a known state resolves; an unknown one returns null

    The tick routes on this. If it resolved anything truthy for an unknown
    state, every remaining card (System Status, Alerts) would be dragged onto
    the source-card path and render a typed NA instead of its own body.
    """
    assert _view("sourceCardSpec", "ltft-trend")["title"] == "Fuel Trim"  # type: ignore[index]
    assert _view("sourceCardSpec", "system-status") is None
    assert _view("sourceCardSpec", "dtc") is None


def test_sourceCardView_fuelTrimSectionIsPlainEnglish_notJargon():
    """
    Given: the fuel-trim source card
    Then: it is titled "Fuel Trim", never "LTFT Trend"

    A LABEL change only (US-507 AC-2). The jargon leaves the title; Spool's
    LTFT semantics stay exactly where they were (proved by the sufficiency +
    drift tests below, which are the original card's rules unchanged).
    """
    sec = _section(_cards(), "ltft-trend")
    assert sec["title"] == "Fuel Trim"
    assert "LTFT Trend" not in sec["title"]


def test_sourceCardView_sectionTitlesNameTheirInstrument():
    """Each card is self-labelling. The title is carried in the VIEW, not only
    in the markup, because it is also the word a typed-NA body has to be
    readable beside."""
    view = _cards()
    assert _section(view, "battery-health")["title"] == "Battery"
    assert _section(view, "light")["title"] == "Light"


# ---------------------------------------------------------------------------
# AC-4 -- every honest-instrument state of the three sources survives the move.
# ---------------------------------------------------------------------------


def test_sourceCardView_batterySection_keepsTheStaleGreenGuard():
    """
    Given: a GOOD battery verdict whose last health check is a month old
    Then: the section still carries the "last health check ... (N days ago)"
          line

    F-9 is the trap this card was built around: a month-old GOOD must never
    read as live. Relocating the card must not drop the guard that made it
    honest.
    """
    sec = _section(_cards(), "battery-health")
    assert sec["view"]["health"]["value"] == "GOOD"
    assert "last health check" in sec["view"]["health"]["detail"]
    assert "30 days ago" in sec["view"]["health"]["detail"]


def test_sourceCardView_batterySection_keepsVoltsNeverPercent():
    """F-8: a null SoC omits the percent and shows volts. A voltage rendered as
    a percent is the render-breaking trap Spool named for this source."""
    sec = _section(_cards(battery=_battery(soc=None)), "battery-health")
    assert sec["view"]["vcell"]["value"] == "4.02 V"
    assert sec["view"]["soc"]["shown"] is False


def test_sourceCardView_batterySection_keepsTheDrainLadder():
    """F-2/A-6: the failsafe ladder exists ONLY while actually draining -- it
    rides along with the section rather than being lost in the merge."""
    sec = _section(_cards(battery=_battery(draining=True)), "battery-health")
    assert sec["view"]["ladder"] is not None


def test_sourceCardView_lightSection_rendersTheRealLux():
    """The light section is still a pure consumer of the SAME states/light file
    that drives the auto-dim, so the number can never disagree with the screen
    it explains."""
    sec = _section(_cards(), "light")
    assert sec["view"]["ambient"]["value"] == "412 lx"
    assert sec["view"]["band"]["value"] != "NA"


def test_sourceCardView_lightSection_nullLuxGraysWithinTheSection():
    """
    Given: a null lux (the bridge's honest saturated/unreadable marker)
    Then: the AMBIENT + CONDITION fields gray INDIVIDUALLY -- the section is
          still present and is NOT promoted to a whole-section NA

    The old card grayed fields, not itself. Escalating that to a section-level
    NA in the merge would LOSE information (which of the two fields is dead).
    """
    sec = _section(_cards(light=_light(None)), "light")
    assert sec["unavailable"] is False
    assert sec["view"]["ambient"]["value"] == "NA"
    assert sec["view"]["band"]["value"] == "NA"


def test_sourceCardView_fuelTrimSection_insufficientIsNeverGreen():
    """The insufficient-window guard is Spool's, and it survives the retitle: too
    little data can never paint a confident healthy verdict."""
    ltft = _ltft(sufficient=False, points=[], current=None)
    sec = _section(_cards(ltft=ltft), "ltft-trend")
    assert sec["view"]["headline"]["level"] == "insufficient"
    assert sec["view"]["headline"]["value"] == "insufficient data"


def test_sourceCardView_fuelTrimSection_driftRendersItsOwnLevel():
    """A drive beyond +/-10% keeps its own non-green level -- the semantics the
    emitter classifies, which this view only maps."""
    ltft = _ltft(level="down", points=[{"driveId": 32, "ltftAvg": 12.5, "level": "down"}])
    sec = _section(_cards(ltft=ltft), "ltft-trend")
    assert sec["view"]["headline"]["level"] == "down"
    assert sec["view"]["points"][0]["value"] == "+12.50%"


# ---------------------------------------------------------------------------
# AC-4 -- SECTION INDEPENDENCE. Merging three cards must not merge their
# failures; the old cards failed one at a time and so must the sections.
# ---------------------------------------------------------------------------


def test_sourceCardView_deadUpsDoesNotBlankTheLiveLightReading():
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
    view = _cards(battery=dead)
    battery = _section(view, "battery-health")
    light = _section(view, "light")
    assert battery["view"]["unavailable"] is True
    assert light["view"]["ambient"]["value"] == "412 lx"


def test_sourceCardView_absentLightFileDoesNotBlankTheBatterySection():
    """The inverse direction -- an ABSENT state file (not merely a degraded
    source) must also stay contained to its own section."""
    view = _cards(light=None)
    assert _section(view, "light")["unavailable"] is True
    assert _section(view, "battery-health")["view"]["health"]["value"] == "GOOD"


def test_sourceCardView_absentSection_namesItsSilentInstrument():
    """
    Given: an absent state file
    Then: the section says WHICH instrument is silent

    On a standalone card the card title supplied that context. Stacked three
    deep, a bare "unavailable" no longer says which of three readouts died.
    """
    view = _cards(battery=None, light=None)
    assert _section(view, "battery-health")["na"]["reason"].lower().startswith("no data")
    assert "no data" in _section(view, "light")["na"]["reason"].lower()


# ---------------------------------------------------------------------------
# AC-2 -- the fuel-trim VEHICLE GATE, in its new (section) vocabulary.
# ---------------------------------------------------------------------------


def test_sourceCardView_benchNoVehicle_fuelTrimReadsNoEngineData():
    """
    Given: a bench Pi -- system-status reports source.obd.available false
    Then: the Fuel Trim section reads the honest "no engine data"

    The gate's vocabulary NECESSARILY changes with the merge. A standalone card
    could be HIDDEN, which says "this does not apply right now". A section
    inside an always-visible card cannot vanish without leaving a hole, so the
    same fact is spoken instead of shown.
    """
    sec = _section(_cards(obdAvailable=False), "ltft-trend")
    assert sec["gated"] is True
    assert sec["na"]["reason"] == "no engine data"


def test_sourceCardView_benchNoVehicle_fuelTrimLeaksNoValueEvenWithAState():
    """
    Given: NO vehicle, but a complete and perfectly readable ltft-trend file
    Then: the section still renders the gate, carrying NO trim value at all

    The load-bearing one. A stale ltft-trend file left on disk from the last
    drive is exactly the input that would let a bench render a confident fuel
    trim for an engine that is not running. The gate must beat the data, not
    lose to it -- so the view carries no reading to leak.
    """
    sec = _section(_cards(obdAvailable=False, ltft=_ltft()), "ltft-trend")
    assert sec["gated"] is True
    assert sec["view"] is None
    assert "-2.50%" not in json.dumps(sec)


def test_sourceCardView_vehicleConnected_fuelTrimRendersTheRealTrend():
    """The inverse -- without it "always gate" would pass. A connected vehicle
    reveals the real trend, which is the whole point of keeping the section."""
    sec = _section(_cards(obdAvailable=True), "ltft-trend")
    assert sec["gated"] is False
    assert sec["view"]["headline"]["value"] == "-2.50%"


def test_sourceCardView_absentSystemStatus_failsClosedToGated():
    """No readable system-status -> "is a car connected?" is UNKNOWN, and an
    unknown must never render as a state -> fail closed to the gate, exactly as
    the card-level gate did (US-496)."""
    sec = _section(_cards(sysData=None), "ltft-trend")
    assert sec["gated"] is True


def test_sourceCardView_gatedAndBrokenAreDistinctStates():
    """
    Given: a vehicle IS connected but the ltft-trend file is absent
    Then: the section reads a no-data fault, NOT the "no engine data" gate

    Two different facts -- "the instrument does not apply" vs "the instrument is
    broken". Collapsing them would tell an operator with a running engine that
    there is no engine.
    """
    sec = _section(_cards(obdAvailable=True, ltft=None), "ltft-trend")
    assert sec["gated"] is False
    assert sec["unavailable"] is True
    assert sec["na"]["reason"] != "no engine data"


def test_sourceCardView_batteryAndLightAreNeverVehicleGated():
    """AC-2: Battery + Light stay available regardless of a vehicle -- they are
    PI-LOCAL sensors that read on a bench with no car. Gating them would blank a
    working instrument, the exact bench-validatability US-496 fought for."""
    view = _cards(obdAvailable=False)
    assert _section(view, "battery-health")["gated"] is False
    assert _section(view, "light")["gated"] is False
    assert _section(view, "battery-health")["view"]["health"]["value"] == "GOOD"


# ---------------------------------------------------------------------------
# Wiring -- the shipped artifacts actually carry + call the logic above.
# ---------------------------------------------------------------------------


def test_dashboardHtml_shipsOneCardPerSource():
    """US-540-b: each source owns a card again, declaring its OWN state file.
    The tick discovers cards from the markup, so no card = no readout, whatever
    the JS says (US-494)."""
    html = _read(_HTML)
    for label, state in (
        ("Battery", "battery-health"),
        ("Light", "light"),
        ("Fuel Trim", "ltft-trend"),
    ):
        match = re.search(r'<section[^>]*aria-label="' + label + r'"[^>]*>', html, re.S)
        assert match is not None, f"no {label} card in the markup"
        assert 'data-state="' + state + '"' in match.group(0), (
            f"the {label} card does not consume states/{state}"
        )


def test_dashboardHtml_shipsNoMergedHealthCard():
    """The merged card is gone, and so is the multi-source declaration that only
    ever existed to serve it. Leaving a Health card behind beside the three new
    ones would render every reading twice and let the copies disagree."""
    html = _read(_HTML)
    assert 'aria-label="Health"' not in html
    assert "data-states" not in html
    assert "health-section" not in html


def test_dashboardHtml_fuelTrimShipsGatedClosed():
    """The pre-first-poll window -- nothing read yet, "is a car connected?"
    genuinely unknown -- must fail CLOSED to the gate. Shipping `data-gated`
    absent would leave that window looking ungated, which is a claim about the
    vehicle made before anything was read."""
    html = _read(_HTML)
    match = re.search(r'<section[^>]*aria-label="Fuel Trim"[^>]*>', html, re.S)
    assert match is not None
    assert 'data-gated="true"' in match.group(0)


def test_carouselJs_tickRendersTheSourceCards():
    """The source cards are wired into the poll -- a view function nothing calls
    renders nothing (the US-494 default-argument lesson, one story after it cost
    a whole story)."""
    tick = _fnBody(_read(_JS), "tick")
    assert "sourceCardView" in tick
    assert "renderSourceCard" in tick


def test_carouselJs_sourceCardGateReadsTheSameSystemStatus():
    """The fuel-trim gate resolves against the system-status the tick already
    fetched -- a second independent read could disagree with the vehicle state
    the rest of the panel was rendered against."""
    tick = _fnBody(_read(_JS), "tick")
    assert re.search(r'stateOnce\(\s*"system-status"\s*\)', tick), (
        "the source-card path must resolve its gate from the shared per-tick state"
    )


def test_carouselJs_sourceCardsRouteBeforeTheGenericAvailabilityPath():
    """
    Given: the tick's per-card loop
    Then: the source-card branch is reached BEFORE the generic
          `cardAvailability` handling

    Order is load-bearing for exactly one of the three. The generic path reads
    the DATA first and renders a typed NA on a bad read; fuel trim's gate has to
    be evaluated BEFORE its data, or a bench with a stale ltft-trend file paints
    a trim for an engine that is not running.
    """
    tick = _fnBody(_read(_JS), "tick")
    assert tick.index("sourceCardSpec(") < tick.index("cardAvailability("), (
        "the generic availability path now runs before the gate"
    )


def test_carouselJs_sourceCardsReuseTheTokenizedTile():
    """The cards render through the shared `.tile` component, already bound to
    specs/UI/tokens.css. A bespoke per-card palette is exactly the drift the
    SSOT rule exists to prevent."""
    render = _fnBody(_read(_JS), "renderSourceCard")
    for body in ("renderBatteryHealthBody", "renderLightBody", "renderLtftTrendBody"):
        assert body in render, f"{body} is not reachable from the card renderer"
    assert "renderNaBody" in render


def test_carouselJs_gatedCardMarksItselfInTheDom():
    """The gate is readable off the rendered DOM, so the render-regression
    backstop can prove the gated card painted the gate rather than the data --
    the check no pure-function test can make."""
    render = _fnBody(_read(_JS), "renderSourceCard")
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
    assert "function renderSourceCard(" in src
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
