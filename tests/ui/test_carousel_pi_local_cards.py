################################################################################
# File Name: test_carousel_pi_local_cards.py
# Purpose/Description: US-496 (S3, F-121) tests -- the Pi-local carousel cards
#   render LIVE from their states/ files with honest-availability, and the
#   vehicle-dependent card is HIDDEN (not grayed) until a vehicle is actually
#   connected. Three groups:
#     1. The new Light card (a pure consumer of the states/light file US-483-a
#        writes -- {lux, ts}). A live reading renders; a null lux (saturated /
#        unreadable) or a STALE reading grays the AMBIENT + CONDITION fields
#        INDIVIDUALLY rather than rendering a frozen number as current.
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

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "specs", "UI", "dist", "dashboard-pi"
)
_HTML = os.path.join(_DIST, "dashboard.html")
_JS = os.path.join(_DIST, "carousel.js")
_CSS = os.path.join(_DIST, "dashboard.css")

# A fixed read-time + its epoch-ms so every freshness assertion is deterministic
# (the probe compares nowMs against Date.parse(ts)).
_TS = "2026-07-29T12:00:00+00:00"
_TS_MS = int(datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)

# The grounded auto-dim thresholds the CONDITION band is resolved against
# (config.json pi.display.autoDim -- mirrored by BRIGHTNESS_DEFAULTS).
_LUX_MIN = 3.0
_LUX_FULL = 1000.0
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
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _light(lux: float | None, *, ts: str | None = _TS, **extra: object) -> dict:
    """A states/light payload as light_state_bridge.buildLightState writes it."""
    payload: dict = {"lux": lux, "ts": ts}
    payload.update(extra)
    return payload


def _fnBody(js: str, name: str) -> str:
    """The source text of one `function <name>(` up to the next top-level one.

    Crude but sufficient: it lets a wiring test assert what a specific routine
    references instead of grepping the whole 2500-line file, where a match could
    come from anywhere (the coincidence US-495 warned about).
    """
    start = js.index("function " + name + "(")
    nxt = js.find("\n    function ", start + 1)
    nxt2 = js.find("\n      function ", start + 1)
    ends = [e for e in (nxt, nxt2) if e != -1]
    return js[start : min(ends)] if ends else js[start:]


# ---------------------------------------------------------------------------
# AC-1 -- the Light card renders LIVE from states/light.
# ---------------------------------------------------------------------------


def test_lightView_freshReading_rendersTheRealLuxValue():
    """A fresh finite lux renders the real reading + its read age -- the card is
    a pure consumer of the same {lux, ts} file that drives the auto-dim, so the
    number on the card can never disagree with the screen."""
    view = _view("lightView", _light(412.0), None, _TS_MS + 400)
    assert view["unavailable"] is False
    assert view["ambient"]["value"] == "412 lx"
    assert view["ambient"]["level"] == "ok"
    assert "0.4" in view["ambient"]["detail"]


def test_lightView_subTenLux_keepsOneDecimal():
    """Near the dark end the integer would round two distinct cabins together
    (2.4 lx and 3.4 lx straddle the DARK boundary), so sub-10 keeps a decimal."""
    view = _view("lightView", _light(2.35), None, _TS_MS)
    assert view["ambient"]["value"] == "2.4 lx"


def test_lightView_nullLux_graysAmbientButKeepsTheCard():
    """A null lux is the bridge's HONEST saturation/unreadable marker. It grays
    the AMBIENT + CONDITION fields INDIVIDUALLY (the card stays present, the
    always-present contract) and never renders 0 lx or a last-known value."""
    view = _view("lightView", _light(None), None, _TS_MS)
    assert view["unavailable"] is False
    assert view["ambient"]["value"] == "NA"
    assert view["ambient"]["level"] == "unavailable"
    assert "saturat" in view["ambient"]["detail"] or "unreadable" in view["ambient"]["detail"]
    # The band is DERIVED from lux -- with no lux there is nothing to derive.
    assert view["band"]["value"] == "NA"


def test_lightView_staleReading_graysRatherThanFreezingTheValue():
    """A reading older than luxStaleSec is a reading NOT TAKEN NOW. It grays with
    the age as the reason (so the operator learns the feed stopped), never paints
    the frozen number as current -- the same rule the brightness consumer uses."""
    nowMs = _TS_MS + (_STALE_SEC + 50) * 1000
    view = _view("lightView", _light(412.0), None, nowMs)
    assert view["ambient"]["value"] == "NA"
    assert "stale" in view["ambient"]["detail"]
    assert "60" in view["ambient"]["detail"]  # the age is named, not just "stale"


def test_lightView_noReadTime_grays():
    """A payload with no parseable ts cannot be dated -> gray, never assumed
    fresh (an undated reading is the one most likely to be stale)."""
    view = _view("lightView", _light(412.0, ts=None), None, _TS_MS)
    assert view["ambient"]["value"] == "NA"


def test_lightView_absentFile_isNull_soTheShellRendersNoData():
    """A missing/malformed states/light -> null: the SHELL owns the whole-card
    no-data message (one place decides absence for every card)."""
    assert _view("lightView", None, None, _TS_MS) is None


def test_lightView_sourceUnavailable_wholeCardTypedNa():
    """An explicit honest-availability `source.light.available: false` (the
    sensor is gated off / unreadable) -> a typed whole-card NA with the reason
    travelling with it."""
    view = _view(
        "lightView",
        _light(None, source={"light": {"available": False, "reason": "sensor disabled"}}),
        None,
        _TS_MS,
    )
    assert view["unavailable"] is True
    assert view["reason"] == "sensor disabled"


def test_luxBand_resolvesAgainstTheGroundedAutoDimThresholds():
    """The CONDITION band is a NAME for the two thresholds the auto-dim curve
    already uses -- not a third set of numbers that could drift from it."""
    assert _view("luxBand", _LUX_MIN, None) == "DARK"
    assert _view("luxBand", 50.0, None) == "DIM"
    assert _view("luxBand", _LUX_FULL, None) == "DAYLIGHT"


def test_luxBand_honoursAnInjectedConfig_notAHardcodedNumber():
    """The thresholds are CONFIG (pi.display.autoDim, injected at serve time), so
    an override must move the band -- proving the values are read, not baked in."""
    cfg = {"luxMin": 100.0, "luxFull": 200.0}
    assert _view("luxBand", 50.0, cfg) == "DARK"
    assert _view("luxBand", 150.0, cfg) == "DIM"


# ---------------------------------------------------------------------------
# AC-1 (recursive) -- an existing card's sub-field with no producer grays alone.
# ---------------------------------------------------------------------------


def test_systemStatusView_absentPowerBlock_graysOnlyThatTile():
    """Honest-availability applies INSIDE a card: one absent sub-block grays its
    own tile while every other tile still renders its real value."""
    view = _view(
        "systemStatusView",
        {
            "obdLink": {"state": "linked", "retries": 0, "lastSeenS": 1},
            "sync": {"lastOkTs": None, "rows": 0, "pending": 0, "stale": False},
            "drive": {"state": "idle", "driveId": None},
            "ts": _TS,
        },
    )
    assert view["tiles"]["power"]["level"] == "unavailable"
    assert view["tiles"]["obdLink"]["value"] == "LINKED"
    assert view["tiles"]["drive"]["value"] == "IDLE"


# ---------------------------------------------------------------------------
# AC-2 -- an absent DTC state is calm gray "no data", never an all-clear.
# ---------------------------------------------------------------------------


def test_noDataView_dtc_readsNoData_notAnAllClear():
    """A missing `dtc` state means the codes were never read. The card must say
    so; "No stored codes" would be a fabricated clean read (F-6)."""
    view = _view("noDataView", "dtc")
    assert view is not None
    assert view["label"] == "ALERTS"
    assert "no data" in view["reason"].lower()
    assert "no stored codes" not in view["reason"].lower()


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
    """Unchanged contract (tests/deploy/test_dashboard_kit.py): the VIEW reports
    absence as null and the shell renders it. noDataView supplies the words."""
    assert _view("alertsCardView", None) is None


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


def test_dashboardHtml_shipsTheLightCardSlot():
    """AC-1: the always-present Light card exists in the markup (the tick
    discovers cards by [data-state], so no slot = no card, whatever the JS says)."""
    html = _read(_HTML)
    assert 'data-state="light"' in html


def test_dashboardHtml_vehicleGatedCardShipsHidden():
    """AC-3: the vehicle-dependent card carries the gate marker AND ships
    `hidden`, so the pre-first-poll window -- when no state has been read yet --
    shows no vehicle card. Same fail-closed shape as the US-490 `⋮` button."""
    html = _read(_HTML)
    match = re.search(r"<section[^>]*data-vehicle-gated[^>]*>", html)
    assert match is not None, "no card carries data-vehicle-gated"
    assert " hidden" in match.group(0), "the vehicle-gated card must ship hidden"


def test_dashboardHtml_ltftIsTheVehicleGatedCard():
    """The LTFT card is the vehicle-dependent card in this generation (its
    emitter is orphaned -- Slice 2 revisits it with Spool). Gating it is what
    takes it out of the always-present set without faking or deleting it."""
    html = _read(_HTML)
    match = re.search(r"<section[^>]*data-vehicle-gated[^>]*>", html)
    assert 'data-state="ltft-trend"' in match.group(0)


def test_carouselJs_tickRendersTheLightCard():
    """The Light card is wired into the poll -- a view function nothing calls
    renders nothing (the US-494 default-argument lesson)."""
    js = _read(_JS)
    tick = _fnBody(js, "tick")
    assert 'name === "light"' in tick
    assert "renderLightCard" in tick


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


def test_carouselJs_lightCardReusesTheTokenizedTile():
    """AC-4: the new card renders through the shared `.tile` component, which is
    already bound to specs/UI/tokens.css. A bespoke light-card palette is exactly
    the drift the SSOT rule exists to prevent."""
    js = _read(_JS)
    render = _fnBody(js, "renderLightCard")
    assert "appendTile" in render


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
