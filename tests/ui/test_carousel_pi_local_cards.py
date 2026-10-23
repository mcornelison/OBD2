################################################################################
# File Name: test_carousel_pi_local_cards.py
# Purpose/Description: US-496 (S3, F-121) tests -- the Pi-local carousel cards
#   render LIVE from their states/ files with honest-availability, and the
#   vehicle-dependent card is HIDDEN (not grayed) until a vehicle is actually
#   connected. Three groups:
#     1. The new Light card (a pure consumer of the states/light file US-483-a
#        writes -- {lux, ts}). A live reading renders; a null lux (saturated /
#        unreadable) reads '--' + its reason and a STALE reading dims with its
#        age (US-893-b) rather than rendering a frozen number as current.
#     2. The absent-state message per card. A missing `dtc` state reads a calm
#        gray "no data", NEVER "no stored codes" (a false all-clear) and never a
#        red alert at idle -- the F-6 no-phantom rule at the CARD level.
#     3. The vehicle gate + the visible-index math it needs. A hidden card takes
#        no slot in the flex track, so translateX/page-dots/swipe must count
#        VISIBLE cards; the gate itself demands an explicit
#        source.obd.available === true and fails closed to hidden.
#   Pure logic runs through the shared node probe (tests/ui/carousel_probe.js);
#   the browser-only DOM wiring is pinned by reading the shipped artifacts, since
#   a correct routine the tick never calls is worth nothing (US-494/US-495).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-29    | Ralph (Rex)  | Initial -- US-496 Pi-local cards live + gate.
# 2026-10-19    | Rex (US-893-a)| MOVED PIN (US-893-a, Atlas A1): CONDITION maps
#               |              | the PROVIDER's lightBand (night/dusk/day ->
#               |              | DARK/DIM/DAYLIGHT); the page luxBand and its
#               |              | BRIGHTNESS_DEFAULTS thresholds are gone.
# 2026-10-19    | Rex (US-893-b)| MOVED PIN (US-893-b): lightView/lightBandWord
#               |              | RETIRED; the light cases re-pointed at
#               |              | lightPageView (word = lightBand upper-cased,
#               |              | '--' + reason, stale dims with its age, an
#               |              | absent file is the page's own absence).
# 2026-10-20    | Ralph (Rex)  | MOVED PIN (US-898-b1): the ALERTS card reads
#               |              | states/alerts; noDataView carries no dtc entry
#               |              | and its absence is warningsPageView's '--' +
#               |              | 'no warnings data'.
# ================================================================================
################################################################################

"""US-496 tests for the live Pi-local cards + the vehicle-gated card."""

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime

import pytest

from tests.ui.render_harness import _fnBody

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard"
)
_HTML = os.path.join(_DIST, "dashboard.html")
_JS = os.path.join(_DIST, "carousel.js")
_CSS = os.path.join(_DIST, "dashboard.css")

# A fixed read-time + its epoch-ms so every freshness assertion is deterministic
# (the probe compares nowMs against Date.parse(ts)).
_TS = "2026-07-29T12:00:00+00:00"
_TS_MS = int(datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)

# The page's luxStaleSec default (BRIGHTNESS_DEFAULTS since US-893-a holds only
# defaultLevel and luxStaleSec; the band thresholds live in the bridge).
_STALE_SEC = 10

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
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _light(lux: float | None, *, ts: str | None = _TS, **extra: object) -> dict:
    """A states/light payload as light_state_bridge.buildLightState writes it."""
    payload: dict = {"lux": lux, "ts": ts}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# AC-1 -- the Light card renders LIVE from states/light.
# ---------------------------------------------------------------------------


def test_lightPageView_freshReading_rendersTheRealLuxValue():
    """A fresh finite lux renders the real reading -- the card is a pure
    consumer of the same states/light file that drives the auto-dim, so the
    number on the card can never disagree with the screen.

    MOVED PIN (US-893-b): lightView -> lightPageView; the unit is 'lux' and a
    fresh reading shows no age (the age appears only once it is stale)."""
    view = _view("lightPageView", _light(412.0), None, _TS_MS + 400)
    assert view["absent"] is False and view["stale"] is False
    assert (view["ambient"]["value"], view["ambient"]["unit"]) == ("412", "lux")
    assert view["age"] is None


def test_lightPageView_subTenLux_keepsOneDecimal():
    """Near the dark end the integer would round two distinct cabins together
    (2.4 and 3.4 lux straddle the night boundary), so sub-10 keeps a decimal.
    MOVED PIN (US-893-b): the unit moved to its own field."""
    view = _view("lightPageView", _light(2.35), None, _TS_MS)
    assert view["ambient"]["value"] == "2.4"


def test_lightPageView_nullLux_isDashPlusReason_butKeepsTheCard():
    """A null lux is the bridge's HONEST saturation/unreadable marker. AMBIENT
    reads '--' with the reason (the card stays present, the always-present
    contract) and never 0 lux or a last-known value.

    MOVED PIN (US-893-b, Atlas L1): typed '--' + the reasons.lux text instead
    of an NA tile; the word is the provider's band, so with none it is '--'."""
    view = _view("lightPageView", _light(None), None, _TS_MS)
    assert view["absent"] is False
    assert view["ambient"] == {"value": "--", "unit": "", "none": True}
    assert view["reason"] == "no reading"
    assert view["word"] == {"text": "--", "glyph": None}


def test_lightPageView_staleReading_dimsWithItsAge_neverPaintsItAsCurrent():
    """A reading older than luxStaleSec is a reading NOT TAKEN NOW. It is
    dimmed with its age (so the operator learns the feed stopped), never
    painted as current -- the same freshness rule the brightness applier uses.

    MOVED PIN (US-893-b, Iris L6): stale dims the published values and shows
    the age ('60 s', amber) instead of replacing them with an NA tile."""
    nowMs = _TS_MS + (_STALE_SEC + 50) * 1000
    view = _view("lightPageView", _light(412.0), None, nowMs)
    assert view["stale"] is True
    assert view["age"] == {"text": "60 s", "tone": "warn"}  # the age is named
    assert view["ambient"]["value"] == "412"


def test_lightPageView_noReadTime_isStale():
    """A payload with no parseable ts cannot be dated -> stale, never assumed
    fresh (an undated reading is the one most likely to be stale).
    MOVED PIN (US-893-b): dimmed with 'no timestamp' in place of the age."""
    view = _view("lightPageView", _light(412.0, ts=None), None, _TS_MS)
    assert view["stale"] is True
    assert view["age"]["text"] == "no timestamp"


def test_lightPageView_absentFile_isThePagesOwnAbsence():
    """A missing/malformed states/light -> the Light page's own absent view.

    MOVED PIN (US-893-b, Atlas L1): was null so the shell rendered a typed NA;
    the page now paints '--' + 'no light data' in its own layout, beside the
    brightness it fell back to. The shell still learns the feed is missing
    (`absent`, see test_carousel_source_cards.py)."""
    view = _view("lightPageView", None, None, _TS_MS)
    assert view["absent"] is True
    assert view["reason"] == "no light data"
    assert view["ambient"]["value"] == "--"


def test_lightPageView_sourceUnavailable_isAbsentWithTheReason():
    """An explicit honest-availability `source.light.available: false` (the
    sensor is gated off / unreadable) -> absent, with the reason travelling
    with it. MOVED PIN (US-893-b): absent view, not a whole-card NA tile."""
    view = _view(
        "lightPageView",
        _light(None, source={"light": {"available": False, "reason": "sensor disabled"}}),
        None,
        _TS_MS,
    )
    assert view["absent"] is True
    assert view["reason"] == "sensor disabled"


@pytest.mark.parametrize(("band", "word"), [("night", "NIGHT"), ("dusk", "DUSK"), ("day", "DAY")])
def test_lightPageView_wordIsTheProvidersBand(band: str, word: str):
    """MOVED PIN (US-893-b): lightBandWord (DARK/DIM/DAYLIGHT) RETIRED with the
    CONDITION tile; the word is the bridge's lightBand upper-cased. The page
    holds no threshold, so it cannot drift from the curve."""
    view = _view("lightPageView", _light(412.0, lightBand=band), None, _TS_MS)
    assert view["word"] == {"text": word, "glyph": band}


@pytest.mark.parametrize("band", [None, "", "NIGHT", "twilight", 3])
def test_lightPageView_unknownBand_isDash(band):
    """Anything but the three provider bands names nothing -- '--', no glyph.
    MOVED PIN (US-893-b): was lightBandWord -> null."""
    view = _view("lightPageView", _light(412.0, lightBand=band), None, _TS_MS)
    assert view["word"] == {"text": "--", "glyph": None}


def test_lightPageView_word_isTheProvidersBand_luxMinIsDusk():
    """
    Given: a fresh reading AT luxMin (3.0 lux), which the bridge bands 'dusk'
    When: the Light page renders
    Then: the word reads DUSK

    THE ONE BOUNDARY SHIFT, named (Atlas A1, US-893-a): the old page luxBand
    made lux == luxMin DARK (lux <= luxMin); the provider makes it dusk (night
    is lux < luxMin). MOVED PIN (US-893-b): DIM -> DUSK, the provider's word.
    """
    from pi.sensors.light_state_bridge import lightBand

    band = lightBand(3.0, {"luxMin": 3.0, "luxFull": 300.0})
    view = _view("lightPageView", _light(3.0, lightBand=band), None, _TS_MS)

    assert band == "dusk"
    assert view["word"]["text"] == "DUSK"


def test_lightPageView_word_followsTheProviderNotTheLux():
    """A day band on a dark-looking lux reads DAY: the page never re-derives
    the band from lux (a retuned autoDim moves the word through the bridge).
    MOVED PIN (US-893-b): DAYLIGHT -> DAY."""
    view = _view("lightPageView", _light(50.0, lightBand="day"), None, _TS_MS)
    assert view["word"]["text"] == "DAY"


def test_lightPageView_freshReadingWithoutABand_dashesTheWordAlone():
    """Atlas A1: a null band -> the word '--'; the reading still shows.
    MOVED PIN (US-893-b): the word, not an NA CONDITION tile."""
    view = _view("lightPageView", _light(412.0), None, _TS_MS)
    assert view["ambient"]["value"] == "412"
    assert view["word"] == {"text": "--", "glyph": None}


# ---------------------------------------------------------------------------
# AC-1 (recursive) -- an existing card's sub-field with no producer grays alone.
# ---------------------------------------------------------------------------


def test_systemStatusView_absentPowerBlock_graysOnlyThatTile():
    """Honest-availability applies INSIDE a card: one absent sub-block grays its
    own tile while every other tile still renders its real value.
    MOVED PIN (US-894-b): the OBD LINK tile is retired; sync is the witness.
    MOVED PIN (US-894-c): the SYNC tile is retired too; the DATA row (its
    sync stamp) is the witness that the rest of the card still renders."""
    view = _view(
        "systemStatusView",
        {
            # MOVED PIN (US-876-a): obdLink.lastSeenS is gone from system-status.
            "obdLink": {"state": "linked", "retries": 0},
            "sync": {"lastOkTs": None, "rows": 0, "pending": 0, "stale": False},
            "drive": {"state": "idle", "driveId": None},
            "ts": _TS,
        },
    )
    assert view["tiles"]["power"]["level"] == "unavailable"
    assert view["rows"][1]["key"] == "data"
    assert view["rows"][1]["value"].endswith("no sync on record")
    # MOVED PIN (US-894-c): the DRIVE tile is retired (spec s4.3 I3).
    assert "drive" not in view["tiles"]


# ---------------------------------------------------------------------------
# AC-2 -- an absent DTC state is calm gray "no data", never an all-clear.
# ---------------------------------------------------------------------------


def test_noDataView_dtc_readsNoData_notAnAllClear():
    """MOVED PIN (US-898-b1): the ALERTS card no longer reads `dtc`, so the
    shell's no-data table carries no dtc entry. A missing states/alerts is the
    card's OWN absence -- '--' and 'no warnings data', never an all-clear."""
    assert _view("noDataView", "dtc") is None
    view = _view("warningsPageView", None)
    assert view["header"]["text"] == "--"
    assert "no warnings data" == view["empty"]
    assert "no stored codes" not in json.dumps(view).lower()


def test_noDataView_light_namesTheSilentInstrument():
    """The Light card's absent-state message names the feed, so a gray card is
    diagnosable instead of a bare word."""
    view = _view("noDataView", "light")
    assert view is not None
    assert "no data" in view["reason"].lower()


def test_noDataView_unknownCard_isNull_soTheShellFallbackStands():
    """A card with no bespoke message keeps the shipped `unavailable` fallback --
    this story does not restyle the three cards it was not scoped to."""
    assert _view("noDataView", "battery-health") is None
    assert _view("noDataView", "nope") is None


def test_alertsCardView_absentPayload_stillNull():
    """MOVED PIN (US-898-b1): `alertsCardView` retired with the dtc-driven card.
    Its successor reports absence itself rather than as null: an absent
    states/alerts is a `missing` view with no rows."""
    view = _view("warningsPageView", None)
    assert view["missing"] is True
    assert view["rows"] == []


# ---------------------------------------------------------------------------
# AC-3 -- the vehicle-dependent card is HIDDEN until a vehicle is connected.
# ---------------------------------------------------------------------------


def test_vehicleConnected_obdSourceAvailable_true():
    """An explicit available OBD source is the one signal that reveals the
    vehicle-gated card."""
    data = {"source": {"obd": {"available": True, "reason": None}}}
    assert _view("vehicleConnected", data) is True


def test_vehicleConnected_obdSourceUnavailable_false():
    """OBD off / unreadable -> hidden, not gray: the instrument does not APPLY
    (no car), which is a different fact from an instrument that is broken."""
    data = {"source": {"obd": {"available": False, "reason": "OBD: off"}}}
    assert _view("vehicleConnected", data) is False


def test_vehicleConnected_absentSystemStatus_failsClosedToHidden():
    """No readable system-status -> "is a car connected?" is UNKNOWN, and an
    unknown must never render as a state (US-492/US-494) -> fail closed."""
    assert _view("vehicleConnected", None) is False


def test_vehicleConnected_absentSourceBlock_failsClosedToHidden():
    """DELIBERATELY stricter than sourceUnavailable(), which treats an absent
    source block as available for pre-US-429 backward compatibility. A REVEAL
    gate must require the positive claim, or a malformed state file shows a
    vehicle card with no vehicle."""
    assert _view("vehicleConnected", {"obdLink": {"state": "linked"}}) is False


# ---------------------------------------------------------------------------
# AC-3 -- the visible-index math a hidden card forces (flex track, page dots).
# ---------------------------------------------------------------------------


def test_visualPosition_countsOnlyVisibleCards():
    """A display:none card takes NO slot in the flex track, so the translateX
    step count must be the visible position -- otherwise hiding one card slides
    the carousel to a blank frame."""
    assert _view("visualPosition", 3, [False, True, False, False]) == 2
    assert _view("visualPosition", 0, [False, False]) == 0


def test_nextVisibleIndex_stepsOverAHiddenCard():
    """A swipe must never land on a hidden card (an invisible dead slot)."""
    assert _view("nextVisibleIndex", 0, 1, [False, True, False]) == 2
    assert _view("nextVisibleIndex", 2, -1, [False, True, False]) == 0


def test_nextVisibleIndex_wrapsPastTheLastVisibleCard():
    """SUPERSEDED BY US-506 (F-124): this used to assert the swipe CLAMPED at the
    ends. The nav model now WRAPS -- but the invariant this test was really
    guarding survives intact and is what is re-asserted here: the step never
    lands on a hidden card. A trailing gated card is skipped on the way round,
    so the wrap lands on the first VISIBLE card, not the blank frame behind it.
    Full wrap coverage lives in tests/ui/test_carousel_nav_model.py."""
    assert _view("nextVisibleIndex", 1, 1, [False, False, True]) == 0
    assert _view("nextVisibleIndex", 0, -1, [False, False]) == 1


def test_nearestVisibleIndex_prefersTheEarlierCard():
    """When the current card is hidden mid-session (the vehicle unplugs), land on
    the nearest visible card, preferring the earlier one -- an operator's "back",
    never a forward jump past cards they have not seen."""
    assert _view("nearestVisibleIndex", 2, [False, False, True, False]) == 1
    assert _view("nearestVisibleIndex", 0, [True, False]) == 1


def test_nearestVisibleIndex_nothingVisible_isNull():
    """Degenerate (every card gated off) -> null, so the caller holds its index
    instead of clamping to a hidden card 0."""
    assert _view("nearestVisibleIndex", 0, [True, True]) is None


# ---------------------------------------------------------------------------
# Wiring -- the shipped artifacts actually use the logic above.
# ---------------------------------------------------------------------------


def test_dashboardHtml_shipsTheLightSlot():
    """AC-1: the always-present light readout exists in the markup (the tick
    renders from the DOM, so no slot = no readout, whatever the JS says).

    RELOCATED TWICE: US-507 made it the Light SECTION of the merged Health
    card; US-540-b made it a standalone card again (the US-540-a scale left a
    card affording ~3 facts, and Health carried six). Through both moves it is
    still always-present and still a pure consumer of the same states/light
    file that drives the auto-dim -- which is why this test keeps its subject
    and only changes where it looks.
    """
    html = _read(_HTML)
    match = re.search(r'<section[^>]*aria-label="Light"[^>]*>', html)
    assert match is not None, "no Light card in the markup"
    assert 'data-state="light"' in match.group(0)


def test_dashboardHtml_vehicleGatedSurfaceFailsClosed():
    """AC-3: the vehicle-dependent surface fails CLOSED before the first poll --
    when nothing has been read and "is a car connected?" is genuinely unknown.
    Same shape as the US-490 `⋮` button.

    SUPERSEDED IN FORM BY US-507, not in substance, and US-540-b keeps that
    form. The gated surface used to be a whole CARD that failed closed by
    shipping `hidden`. US-507 made it a SECTION, which cannot vanish without
    leaving a hole, so it failed closed by shipping `data-gated="true"` and
    speaking the gate. It is a card again now and KEEPS the speaking version:
    US-540-b locks six cards, and one that disappears on a bench breaks the set
    where the panel is read most days. The property under test is identical
    across all three: no vehicle reading is shown until a vehicle is positively
    confirmed.
    """
    html = _read(_HTML)
    # MOVED PIN (US-890-a): the Fuel card replaces Fuel Trim and keeps the gate.
    match = re.search(r'<section[^>]*aria-label="Fuel"[^>]*>', html)
    assert match is not None, "no Fuel card in the markup"
    assert 'data-gated="true"' in match.group(0), (
        "the vehicle-gated surface must ship gated, not open"
    )


def test_dashboardHtml_fuelTrimIsTheVehicleGatedSurface():
    """Fuel trim is the vehicle-dependent readout in this generation (its
    emitter is orphaned -- Slice 2 revisits it with Spool). Gating it is what
    takes it out of the always-available set without faking or deleting it --
    and the Battery + Light cards beside it are NOT gated, because they are
    Pi-local sensors that read on a bench with no car."""
    html = _read(_HTML)
    gated = re.findall(r'<section[^>]*data-gated="true"[^>]*>', html)
    assert len(gated) == 1, f"exactly one surface should ship gated, found {gated}"
    # MOVED PIN (US-890-a): the Fuel card replaces Fuel Trim.
    assert 'aria-label="Fuel"' in gated[0]


def test_carouselJs_tickRendersTheLightReadout():
    """The light readout is wired into the poll -- a view function nothing calls
    renders nothing (the US-494 default-argument lesson).

    US-540-b: the tick reaches it through the shared source-card route, so the
    wiring pin follows the call chain that actually runs.
    """
    js = _read(_JS)
    tick = _fnBody(js, "tick")
    assert "sourceCardView" in tick
    assert "renderSourceCard" in tick
    render = _fnBody(js, "renderSourceCard")
    assert "renderLightBody" in render


def test_carouselJs_tickAppliesTheVehicleGate():
    """The gate runs every tick off the SAME fetched system-status (no second
    read), so plugging/unplugging the vehicle reveals/hides the card live."""
    js = _read(_JS)
    tick = _fnBody(js, "tick")
    assert "applyVehicleGate" in tick


def test_carouselJs_renderUsesTheVisiblePosition():
    """The translateX step count comes from visualPosition, not the raw index --
    the defect a hidden card would otherwise introduce."""
    js = _read(_JS)
    render = _fnBody(js, "render")
    assert "visualPosition" in render
    # The raw index must be GONE, not merely supplemented -- leaving the old
    # expression alongside the new one is how a half-applied fix ships.
    assert "-current * 100" not in render


def test_carouselJs_moveUsesNextVisibleIndex():
    """Swipes step over hidden cards (nextIndex alone would land on one)."""
    js = _read(_JS)
    move = _fnBody(js, "move")
    assert "nextVisibleIndex" in move


def test_carouselJs_lightReadoutBuildsTheLightPage():
    """AC-4: the light readout introduces no palette of its own -- a bespoke
    light palette is exactly the drift the SSOT rule exists to prevent.

    MOVED PIN (US-893-b): the two `.tile`s (AMBIENT + CONDITION) are replaced
    by the Light page's own skeleton (buildLightPage); its stylesheet is
    tokens-only, pinned in test_light_page.py and by the hex check below."""
    js = _read(_JS)
    render = _fnBody(js, "renderLightBody")
    assert "buildLightPage" in render
    assert "appendTile" not in render


def test_cardAndDotDisplayRules_cannotDefeatTheHiddenGuard():
    """The whole gate rests on `hidden` REMOVING a card (and its page dot) from
    the flex flow. The US-495 guard wins on IMPORTANCE, so `.card`/`.dot` must
    keep their plain `display` declarations: adding `!important` to either would
    tie importance, hand the win to the later same-specificity selector, and
    silently restore a gated card to the track -- the US-495 defect again."""
    css = re.sub(r"/\*.*?\*/", "", _read(_CSS), flags=re.DOTALL)
    for selector, body in re.findall(r"([^{}]*)\{([^}]*)\}", css):
        if selector.strip() not in (".card", ".dot"):
            continue
        for decl in body.split(";"):
            if decl.strip().startswith("display"):
                assert "!important" not in decl, selector.strip()


def test_dashboardCss_gainsNoBespokeLightCardColour():
    """AC-4 (the other half): no new hex literal arrived with the card. Every
    colour on this surface is a token reference."""
    # Comments first: the file's prose mentions `--red-light` and `light` a lot,
    # and a comment is not a declaration. Then only rules whose SELECTOR names the
    # light card -- :root is where tokens legitimately carry the hex values.
    css = re.sub(r"/\*.*?\*/", "", _read(_CSS), flags=re.DOTALL)
    for selector, body in re.findall(r"([^{}]*)\{([^}]*)\}", css):
        sel = selector.strip()
        if "light" not in sel.lower() or sel == ":root":
            continue
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), sel
