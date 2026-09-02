################################################################################
# File Name: test_carousel_fuel_trim_visible_unavailable.py
# Purpose/Description: US-660 (punch-list 5.1) -- RECORD THE PASS on the Fuel
#   Trim card: it is VISIBLE and it says WHY it has nothing to show.
#
#   THE STORY'S HEADLINE IS MEASURABLY FALSE, and the reason is a three-way
#   collision of similar names. "The Fuel Trim card is vehicle-gated, so a card
#   with no producer has been invisible for months" describes a card nothing
#   hides. There are THREE mechanisms one word apart, and only the third does
#   anything at all to this card:
#
#     1. `data-gated`         -- markup attribute + a per-paint DOM marker.
#                                ZERO rules in the shipped stylesheet mention it.
#                                It hides NOTHING; it exists so a render test can
#                                prove the gate fired rather than the data.
#     2. `data-vehicle-gated` -- the REAL visibility mechanism (`applyVehicleGate`
#                                sets `.hidden`, and the US-495 guard gives a
#                                hidden element no box). It is on ZERO shipped
#                                cards, so `gatedCards` is empty and the loop
#                                hides nothing at all.
#     3. `vehicleGated: true` -- the SOURCE_CARDS table flag. This one is live,
#                                and it selects the card's WORDS, never its
#                                visibility: no vehicle -> "no engine data",
#                                vehicle -> the trend, or "no data -- trend not
#                                computed" when no producer has written one.
#
#   So the CIO's ruling ("VISIBLE AND UNAVAILABLE. Drop data-gated=true.") names
#   a mechanism that does not do what he was told it does. His GOAL is already
#   met in every reachable state, which is exactly what Atlas photographed at
#   10:50 -- "FUEL TRIM / NA / no engine data". Dropping the attribute would
#   change nothing the driver sees; this file records the pass instead, per the
#   story's own conditionalOutcome ("a change made to a working surface is worse,
#   because it risks a regression for no gain").
#
#   EVERY assertion here is made on the SHIPPED carousel.js, over the SHIPPED
#   markup, with the SHIPPED stylesheet resolved at the SHIPPED 480x320 panel --
#   never on `ltftTrendView` or `sourceCardView` alone. US-494/495/498 were all
#   two-correct-halves defects that every pure unit test passed, and this card's
#   own gate lives in the renderer while its words live in the view.
#
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-660 recorded pass + the two
#                                findings (no freshness gate; the producer is
#                                built but unwired).
# ================================================================================
################################################################################

"""US-660: the Fuel Trim card is visible and honestly unavailable (recorded pass)."""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "src"))
sys.path.insert(0, _REPO)

import render_harness as rh  # noqa: E402

from pi.splash.ltft_trend_emitter import (  # noqa: E402
    LTFT_PID,
    LTFT_TREND_FILENAME,
    buildLtftTrendState,
)

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default. Measuring the 3.5in kit at
# 1920x1080 resolves media queries the operator never sees.
PANEL = (480, 320)

_DASH = os.path.join(_REPO, "src", "pi", "ui", "dashboard")
_HTML = os.path.join(_DASH, "dashboard.html")
_CSS = os.path.join(_DASH, "dashboard.css")
_JS = os.path.join(_DASH, "carousel.js")

# The card's state key and the two absence strings the shipped renderer paints.
# Spelled as constants so a retitle shows up as ONE failure here rather than as a
# scatter of unrelated string mismatches.
STATE_KEY = "ltft-trend"
CARD_LABEL = "FUEL TRIM"
NA_TOKEN = "NA"
GATED_REASON = "no engine data"
NO_PRODUCER_REASON = "no data -- trend not computed"

# The two system-status shapes that select the branch. `vehicleConnected()` is
# deliberately strict -- only a positive `source.obd.available === true` counts --
# so an ABSENT system-status is a third input, covered separately below.
NO_VEHICLE: dict[str, Any] = {
    "source": {"obd": {"available": False, "reason": "not read yet"}}
}
VEHICLE: dict[str, Any] = {"source": {"obd": {"available": True, "reason": None}}}

# A REAL three-drive trend, built by the REAL producer's builder rather than
# hand-written. This exists for the negative controls: every "the card paints no
# percentage" claim below is worthless unless this file can demonstrate the card
# painting a percentage when one genuinely exists.
_DRIVES = [
    {
        "driveId": 48,
        "ts": "2026-08-20T10:00:00Z",
        "ltftAvg": 8.4,
        "ltftMin": 7.0,
        "ltftMax": 9.1,
        "sampleCount": 300,
    },
    {
        "driveId": 49,
        "ts": "2026-08-24T10:00:00Z",
        "ltftAvg": 6.1,
        "ltftMin": 5.4,
        "ltftMax": 7.0,
        "sampleCount": 310,
    },
    {
        "driveId": 50,
        "ts": "2026-08-28T10:00:00Z",
        "ltftAvg": 3.2,
        "ltftMin": 2.6,
        "ltftMax": 4.0,
        "sampleCount": 290,
    },
]
_TREND_TS = "2026-08-31T14:00:00Z"
# The same instant as epoch ms. The virtual page clock must be anchored to the
# payload's OWN timestamp, or "aged three days" is arithmetic against 1970 and a
# freshness gate that genuinely worked would still see a negative age.
_TREND_TS_MS = int(
    datetime.datetime(2026, 8, 31, 14, 0, 0, tzinfo=datetime.UTC).timestamp() * 1000
)
_THREE_DAYS_MS = 3 * 24 * 3600 * 1000


def _liveTrend() -> dict:
    return buildLtftTrendState(drives=_DRIVES, nowIso=_TREND_TS)


def _oneDriveTrend() -> dict:
    return buildLtftTrendState(drives=_DRIVES[:1], nowIso=_TREND_TS)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# --- the rendered surface ----------------------------------------------------


def _surface(routes: dict[str, Any], nowMs: int | None = None, steps: Any = None):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet."""
    tree = rh.runDashboard(routes=routes, viewport=PANEL, nowMs=nowMs, steps=steps)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _textOf(node: dict) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _cardPath(surface, stateKey: str = STATE_KEY):
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == stateKey:
            return path
    return None


def _card(routes: dict[str, Any], nowMs: int | None = None, steps: Any = None):
    """(rendered?, attrs, every word painted) for the Fuel Trim card.

    Read from the CARD DOWN rather than tile by tile: the absence claims here are
    about the WHOLE card, and a stray percentage that landed in the title or an
    orphaned tile would slip straight past a per-tile lookup.
    """
    surface = _surface(routes, nowMs=nowMs, steps=steps)
    path = _cardPath(surface)
    assert path is not None, "no Fuel Trim card in the shipped markup at all"
    return surface.rendered(path), path[-1].get("attrs", {}), _textOf(path[-1])


def _joined(texts: list[str]) -> str:
    return " ".join(texts)


# A live Light payload stamped at the SAME instant as the trend. It exists for
# exactly one job: the Light card DOES have a freshness gate (US-641), so it can
# witness that the virtual clock really advanced in a run where the Fuel Trim
# card did not change.
_LIGHT_LIVE: dict[str, Any] = {
    "lux": 120.0,
    "band": "day",
    "ts": _TREND_TS,
    "source": {"light": {"available": True, "reason": None}},
}


def _twoCards(routes: dict[str, Any], nowMs: int | None = None, steps: Any = None):
    """(fuel trim words, light words) from ONE boot of the panel.

    One boot, not two: the whole point of the control is that both cards saw the
    SAME clock, which two separate runs could not establish.
    """
    surface = _surface(routes, nowMs=nowMs, steps=steps)
    out = []
    for key in (STATE_KEY, "light"):
        path = _cardPath(surface, key)
        assert path is not None, f"no {key} card in the shipped markup"
        out.append(_textOf(path[-1]))
    return out[0], out[1]


# The three input shapes that produce an ABSENCE, and the reason each must give.
# Parameterised rather than copy-pasted so a new absence branch cannot be added
# without a reason, and so every negative-case assertion below covers all three.
_ABSENCE_CASES = [
    pytest.param({}, GATED_REASON, id="no-state-files-at-all"),
    pytest.param({"/system-status": NO_VEHICLE}, GATED_REASON, id="no-vehicle"),
    pytest.param(
        {"/system-status": VEHICLE}, NO_PRODUCER_REASON, id="vehicle-but-no-producer"
    ),
]


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS FIRST. Almost every assertion in this file says something is
# NOT on the card. Each is worthless if the card never rendered, or if the reader
# cannot see the thing it claims is missing.
# ---------------------------------------------------------------------------


def test_theCardCanPaintARealTrend_negativeControl():
    """The card DOES paint a trend when a producer has written one.

    Without this, every "no percentage on this card" assertion below could be
    true because the card is incapable of painting one -- which would make this
    whole file a record of a broken card rather than a working one.
    """
    rendered, _, text = _card({"/system-status": VEHICLE, "/ltft-trend": _liveTrend()})
    assert rendered, "the Fuel Trim card had no box even with a live trend"
    joined = _joined(text)
    assert "+3.20%" in joined, joined
    assert "trend: migrating toward 0" in joined, joined


def test_theReaderSeesPerDriveBars_negativeControl():
    """The per-drive bars reach `_textOf`.

    The negative case forbids "an empty chart"; that claim needs a reader proven
    able to SEE the chart. The bars carry their drive ids, so their absence later
    is a measurement rather than a blind spot.
    """
    _, _, text = _card({"/system-status": VEHICLE, "/ltft-trend": _liveTrend()})
    joined = _joined(text)
    for driveId in ("#48", "#49", "#50"):
        assert driveId in joined, joined


# ---------------------------------------------------------------------------
# THE HEADLINE, MEASURED: the card is VISIBLE. Not "not hidden by the one
# mechanism the story names" -- it has a BOX, decided by the shipped cascade.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("routes,expectedReason", _ABSENCE_CASES)
def test_theCardHasABoxInEveryAbsenceState(routes, expectedReason):
    """The story says this card has been invisible for months. It has not.

    `surface.rendered()` is the shipped stylesheet's verdict over the post-JS
    DOM, so this is the panel's answer and not the markup's intention.
    """
    rendered, _, text = _card(routes)
    assert rendered, f"the Fuel Trim card had no box ({expectedReason})"
    assert text, "the card rendered an empty body"


@pytest.mark.parametrize("routes,expectedReason", _ABSENCE_CASES)
def test_theCardIsNotHiddenInAnyAbsenceState(routes, expectedReason):
    """`hidden` is never set on this card.

    Asserted separately from `rendered()` because they fail for different
    reasons: `hidden` is what `applyVehicleGate` would set, while `rendered()`
    also answers a `display:none` arriving from any other rule. A future gate
    could reach either one without touching the other.
    """
    _, attrs, _ = _card(routes)
    assert "hidden" not in attrs, attrs


def test_theCardCarriesNoVehicleGatedAttribute():
    """The ACTUAL hide mechanism is absent from this card.

    `applyVehicleGate` collects cards by `data-vehicle-gated` and sets `.hidden`
    on them. The Fuel Trim card does not carry it, so that loop can never reach
    this card -- which is the structural reason the story's premise cannot be
    true, independent of what any single render happens to show.
    """
    html = _read(_HTML)
    match = re.search(r'<section[^>]*aria-label="Fuel Trim"[^>]*>', html, re.S)
    assert match is not None, "no Fuel Trim card in the shipped markup"
    assert "data-vehicle-gated" not in match.group(0), match.group(0)


def test_noShippedCardCarriesTheVehicleGatedAttribute():
    """conditionalOutcome 1, answered by measurement: there are no OTHER gated
    cards to expose, because there are no gated cards at all.

    The story asks what dropping the vehicle gate would reveal elsewhere. The
    answer is nothing: `data-vehicle-gated` appears on ZERO shipped sections, so
    `gatedCards` is empty on the real Pi and `applyVehicleGate` hides nothing.
    Recorded here so the question does not have to be re-asked by hand.
    """
    html = _read(_HTML)
    assert 'data-vehicle-gated' not in html, (
        "a card now carries the real hide mechanism -- US-660's conditionalOutcome 1 "
        "just became live and needs its own story"
    )


def test_dataGatedDecidesNothingInTheShippedStylesheet():
    """THE MEASUREMENT THAT REFRAMES THE CIO'S RULING.

    The ruling says "Drop data-gated=true" to make the card visible. This asserts
    the attribute cannot affect visibility in the first place: no rule in the
    shipped stylesheet mentions it, so dropping it changes no cascade and no
    pixel. Parsed out of the real CSS rather than grepped, so a rule added inside
    an @media block is caught too.

    MEASURED CASCADE, recorded because it makes the point twice over. Adding a
    rule for this attribute would not be enough to hide the card either:

        no rule (shipped) .............. display:flex, decided by `.card`
        [data-gated="true"]{none} ...... display:flex, decided by `.card`
        ...{none !important} ........... display:none,  decided by the attribute

    `.card` and an attribute selector have EQUAL specificity (0,1,0), and `.card`
    is later in the sheet, so it wins on source order. Only `!important` could
    take the card off the panel -- which is a second, independent reason the
    attribute the ruling names is not what has been hiding anything.
    """
    rules = rh.parseCss(_read(_CSS))
    offenders = [r.selector for r in rules if "data-gated" in r.selector]
    assert offenders == [], (
        "`data-gated` now participates in the cascade, so US-660's finding is "
        f"stale and the attribute really can hide the card: {offenders}"
    )


# ---------------------------------------------------------------------------
# validationCriteria 1: no ltft-trend state file -> VISIBLE, typed absence WITH a
# reason. This is Atlas's 10:50 photograph, reproduced on the rendered panel.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("routes,expectedReason", _ABSENCE_CASES)
def test_everyAbsenceCarriesTheCardLabelTheTypedNaAndAReason(routes, expectedReason):
    """The three parts of an honest absence, asserted together.

    Together and not separately: a card showing `NA` with no label does not say
    WHICH instrument is silent, and a card showing a label with no reason does
    not say why. The story asks for a typed absence WITH a reason, which is the
    conjunction -- so the test is the conjunction.
    """
    _, _, text = _card(routes)
    joined = _joined(text)
    assert CARD_LABEL in joined, joined
    assert NA_TOKEN in text, text
    assert expectedReason in joined, joined


def test_theAbsenceReasonsAreDifferentWordsForDifferentCauses():
    """One word per cause (the US-663 idiom), pinned as a DISTINCTION.

    "No engine is running" and "the engine is running but nothing has computed a
    trend" are different facts, and the second is the one that reveals the
    missing producer. A renderer that collapsed them to a single reason would
    still pass every individual absence test above -- so the claim that matters
    is that the two branches DISAGREE.
    """
    _, _, noVehicle = _card({"/system-status": NO_VEHICLE})
    _, _, withVehicle = _card({"/system-status": VEHICLE})
    assert GATED_REASON in _joined(noVehicle)
    assert NO_PRODUCER_REASON in _joined(withVehicle)
    assert _joined(noVehicle) != _joined(withVehicle), (
        "both causes now paint the same words -- the card can no longer tell the "
        "driver that the producer is the thing that is missing"
    )


def test_theMissingProducerIsWhatTheDrivingCaseReports():
    """THE CIO'S WHOLE POINT, on the surface he reads it from.

    His reasoning is that hiding the card is what let "no producer exists" go
    unnoticed. With an engine connected and no producer, the card states exactly
    that -- and states it in words that are not about the engine, because the
    engine is fine.
    """
    _, _, text = _card({"/system-status": VEHICLE})
    joined = _joined(text)
    assert NO_PRODUCER_REASON in joined, joined
    assert GATED_REASON not in joined, (
        "the card blames the engine for a missing producer while the engine is "
        "connected -- the I-us663 mistake on a different card"
    )


# ---------------------------------------------------------------------------
# THE NEGATIVE CASE, stated by the story: never an empty chart, a zero, or a
# plausible-looking flat line.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("routes,expectedReason", _ABSENCE_CASES)
def test_noAbsenceStatePaintsAPercentage(routes, expectedReason):
    """No trim reading of any kind on an absent card."""
    joined = _joined(_card(routes)[2])
    assert "%" not in joined, joined


@pytest.mark.parametrize("routes,expectedReason", _ABSENCE_CASES)
def test_noAbsenceStatePaintsADigit(routes, expectedReason):
    """Stronger than banning "0%": NO digit reaches the card.

    A fabricated flat line could arrive as `0`, `0.00`, `+0.00%`, `--` beside a
    drive id, or a bar labelled `#50` from a trend that was never computed. A
    digit ban covers all of them at once, and it is assertable here precisely
    because an honest absence on this card has nothing numeric to say.
    """
    joined = _joined(_card(routes)[2])
    assert not re.search(r"\d", joined), joined


@pytest.mark.parametrize("routes,expectedReason", _ABSENCE_CASES)
def test_noAbsenceStatePaintsBars(routes, expectedReason):
    """No chart, empty or otherwise.

    The bars are a separate DOM subtree from the headline tile, so a renderer
    that painted an empty bar row under an honest headline would pass every text
    assertion above. Counted on the rendered tree instead.
    """
    surface = _surface(routes)
    card = _cardPath(surface)
    bars = [
        p
        for p in surface.pathsByClass("ltft-bar")
        if any(n is card[-1] for n in p) and surface.rendered(p)
    ]
    assert bars == [], f"{len(bars)} bar(s) painted on a card with no trend"


def test_theWordUnavailableIsReplacedNotLeftBeside():
    """The shipped markup body reads `unavailable`; the render must REPLACE it.

    A typed absence sitting beside the shell's bare "unavailable" reads as a
    doubly-dead card, and it is the exact residue a renderer that appended
    instead of clearing would leave.
    """
    _, _, text = _card({"/system-status": VEHICLE})
    assert "unavailable" not in _joined(text).lower(), text


# ---------------------------------------------------------------------------
# WHY THE GATE MUST NOT SIMPLY BE DELETED. The vehicle gate is the ONLY thing
# standing between a bench and a confident fuel trim for an engine that is not
# running -- there is no freshness check anywhere on this card (see the
# characterisation test at the end of this file).
# ---------------------------------------------------------------------------


def test_aRealTrendOnDiskIsSuppressedWhenNoVehicleIsConnected():
    """The gate's real job, measured with a real trend to suppress.

    The identical payload that paints "+3.20%" with a vehicle connected paints
    "no engine data" without one. That is the behaviour any proposal to "drop the
    gate" would remove, and it is why this story's ruling was read as a words
    change rather than a gate deletion.
    """
    routes = {"/system-status": NO_VEHICLE, "/ltft-trend": _liveTrend()}
    rendered, _, text = _card(routes)
    joined = _joined(text)
    assert rendered
    assert GATED_REASON in joined, joined
    assert "3.20" not in joined, "a bench painted a trim for an engine that is not running"


def test_anAbsentSystemStatusFailsClosedToTheGate():
    """"Is a car connected?" UNKNOWN must not render as connected.

    With no system-status at all the answer is genuinely unknown, and an unknown
    rendered as a state is US-492/US-494. The card still speaks -- it is the
    WORDS that fail closed, not the visibility.
    """
    rendered, _, text = _card({"/ltft-trend": _liveTrend()})
    joined = _joined(text)
    assert rendered
    assert GATED_REASON in joined, joined
    assert "3.20" not in joined, joined


def test_oneDriveRendersInsufficientAndNeverAConfidentTrim():
    """Too little data is its own honest state, distinct from both absences.

    A single real drive is a genuine reading and is shown -- but the HEADLINE
    refuses to inherit a verdict from it, which is the honest-instrument guard
    the emitter and the view both implement. Recorded because it is the state
    the card will actually sit in on the first drive after US-661 wires the
    producer.
    """
    _, _, text = _card({"/system-status": VEHICLE, "/ltft-trend": _oneDriveTrend()})
    joined = _joined(text)
    assert "insufficient data" in joined, joined
    assert "need 2+ drives (1 captured)" in joined, joined
    assert "trend:" not in joined, "a trend direction was claimed from a single drive"


# ---------------------------------------------------------------------------
# conditionalOutcome 3 -- "THIS ALSO NARROWS US-661". Measured, because the
# narrowing is much sharper than the story assumes: the producer is not missing,
# it is UNWIRED, and the data it reads is already being captured.
# ---------------------------------------------------------------------------


def test_theProducerModuleIsCompleteNotMissing():
    """Reader, classifier, builder and atomic writer all exist and import.

    US-661 is scoped as "build the emitter". It is already built -- US-420 built
    it -- so what US-661 actually needs is a call site.
    """
    from pi.splash import ltft_trend_emitter as mod

    for name in ("readLtftTrend", "buildLtftTrendState", "makeLtftTrendEmitter"):
        assert hasattr(mod, name), name
    assert LTFT_TREND_FILENAME == "ltft-trend", LTFT_TREND_FILENAME


def test_nothingInSrcCallsTheProducer_whichIsWhyTheFileNeverExists():
    """THE MEASURED ROOT CAUSE of the empty card.

    `makeLtftTrendEmitter` has no call site anywhere in `src/` outside its own
    module, so nothing ever writes `states/ltft-trend`. This is the finding that
    sizes US-661, and it is pinned so that WIRING the producer fails this test on
    purpose -- at which point US-661 is done and this assertion should be deleted
    with it.
    """
    callers: list[str] = []
    for root, _dirs, files in os.walk(os.path.join(_REPO, "src")):
        if "__pycache__" in root:
            continue
        for name in files:
            if not name.endswith(".py") or name == "ltft_trend_emitter.py":
                continue
            path = os.path.join(root, name)
            if "makeLtftTrendEmitter" in _read(path):
                callers.append(os.path.relpath(path, _REPO))
    assert callers == [], (
        "the ltft-trend producer is now wired -- US-661 has landed, so delete "
        f"this assertion along with US-660's finding: {callers}"
    )


def test_theTrimPidIsAlreadyPolledAndLogged():
    """The producer's INPUT is already being captured.

    `readLtftTrend` reads `realtime_data` rows for LONG_FUEL_TRIM_1 with
    `data_source='real'`. That PID is in the shipped polling tiers with
    `logData: true`, so the rows the producer needs are already landing on every
    real drive. This is what shrinks US-661 from "specify a fuel-trim feature" to
    "wire an emitter that already exists" -- the point the story asks be passed
    to Spool.
    """
    with open(os.path.join(_REPO, "config.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    logged = [
        p
        for p in cfg["pi"]["realtimeData"]["parameters"]
        if p["name"] == LTFT_PID and p.get("logData") is True
    ]
    assert logged, f"{LTFT_PID} is no longer logged -- US-661 grew a data-source problem"
    polled = [
        p
        for tier in cfg["pi"]["pollingTiers"].values()
        for p in tier["parameters"]
        if p["name"] == LTFT_PID
    ]
    assert polled, f"{LTFT_PID} is no longer polled"


# ---------------------------------------------------------------------------
# CHARACTERISATION -- recorded, NOT fixed. This test asserts current behaviour
# that is arguably wrong; whoever fixes it will fail this test ON PURPOSE, which
# is the point. See offices/pm/issues/I-us660-*.md.
# ---------------------------------------------------------------------------


def test_characterisation_theCardHasNoFreshnessGateSoAStaleTrendPaintsAsCurrent():
    """FINDING: `cardAvailability` accepts ANY object, so age is never checked.

    A trend emitted three days ago still paints "+3.20%" as the current drift,
    with no age qualifier, whenever a vehicle is connected. The page clock is
    advanced WITHOUT rewriting the file, which is the only honest way to render
    "the producer stopped underneath the operator" as opposed to "the producer
    wrote an old reading".

    NOT A LIVE DEFECT TODAY, and the bound matters: nothing writes this file at
    all (see the test above), and with no vehicle the gate suppresses it anyway.
    It becomes reachable the moment US-661 wires the producer, and the emitter is
    best-effort by contract -- a swallowed write failure leaves the last file on
    disk. Whether a MULTI-DRIVE trend should even have a freshness window is a
    Spool question about LTFT semantics, not a call Ralph may take, which is why
    this is recorded rather than fixed.

    THIS TEST FAILS ON PURPOSE when a freshness gate is added. That is correct:
    delete it then, and cite this docstring in the fix.
    """
    routes = {
        "/system-status": VEHICLE,
        "/ltft-trend": _liveTrend(),
        "/light": _LIGHT_LIVE,
    }
    steps = [{"flush": 4}, {"advanceMs": _THREE_DAYS_MS}, {"flush": 4}]
    trimText, lightText = _twoCards(routes, nowMs=_TREND_TS_MS, steps=steps)

    # THE CONTROL, and without it this test is worthless: the Light card was
    # stamped at the same instant and DOES have a freshness gate, so its
    # degradation proves the three days really elapsed on the page clock. If the
    # clock had not moved, Fuel Trim's unchanged reading would prove nothing.
    assert "stale" in _joined(lightText).lower(), (
        "the virtual clock did not advance -- this test cannot measure staleness: "
        f"{lightText}"
    )

    joined = _joined(trimText)
    assert "+3.20%" in joined, (
        "the card now degrades a stale trend -- the US-660 finding has been fixed, "
        "so delete this characterisation test"
    )
    assert "stale" not in joined.lower(), joined


def test_characterisation_theShippedMarkupStillCarriesTheInertGatedAttribute():
    """FINDING: the CIO's ruling asked for this attribute to be dropped.

    It was NOT dropped, deliberately. It decides nothing in the cascade (proven
    above), the renderer overwrites it on every paint, and three shipped tests
    assert it as a US-540-b fail-closed marker -- so removing it would risk a
    regression for no visible gain, which this story's own conditionalOutcome
    forbids. Recorded here so the decision is visible rather than silent, and so
    that dropping it later is a deliberate act that fails this test.
    """
    html = _read(_HTML)
    match = re.search(r'<section[^>]*aria-label="Fuel Trim"[^>]*>', html, re.S)
    assert match is not None
    assert 'data-gated="true"' in match.group(0), (
        "the inert `data-gated` marker was dropped -- if that was deliberate, "
        "delete this test and the three US-540-b assertions that pin it too"
    )
