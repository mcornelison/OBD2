################################################################################
# File Name: test_carousel_light_stale_fallback.py
# Purpose/Description: US-641 -- RECORD THE PASS for the states/light freshness
#   contract: past ``luxStaleSec`` the reading is typed stale on the Light card
#   AND the display brightness falls back to ``defaultLevel``, rather than
#   continuing to dim from a frozen value.
#
#   WHY THIS FILE EXISTS WHEN THE BEHAVIOUR ALREADY HAD TESTS. The two halves
#   were covered in opposite directions and nothing composed them:
#     * test_carousel_brightness.py pins brightnessLevel() as PURE MATH, called
#       through the node probe on a HAND-WRITTEN dict. It never renders a pixel
#       and never involves the producer.
#     * The same file's wiring assertions are STRING GREPS over carousel.js
#       (`'setProperty("--display-brightness"' in js`). A grep cannot witness a
#       value reaching the panel, and stays green if the level is computed once
#       at boot and never again -- which IS the defect this story names.
#   That is the US-494/495/498 shape this project keeps shipping: two correct
#   halves, no test on the join.
#
#   AND THE PART NO EXISTING TEST COULD REACH AT ALL. A freshness window can be
#   crossed two ways -- move the reading's `ts` back, or move `now` forward. Every
#   pre-existing test does the first, which models "the producer wrote an old
#   reading". The fault the story actually describes is the second: the producer
#   STOPPED, the file is frozen byte-identical, and the clock walks past it. This
#   file adds the harness clock (render_harness `nowMs` + {advanceMs}) so the
#   panel can be driven LIVE and dimmed by a real reading FIRST, then aged out
#   underneath the operator. A cold boot that happens to read stale would pass a
#   single-shot assertion while proving nothing about a value going stale.
#
#   GROUNDING: the injected auto-dim config is read from the REAL config.json by
#   the REAL loader the states server uses (loadDisplayAutoDimConfig), not by a
#   hand-copied fixture -- see the DRIFT note on _AUTODIM below.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-641 recorded pass: frozen-feed
#               |              | staleness, end to end from the real bridge to
#               |              | the rendered panel + the CSS var that consumes it.
# ================================================================================
################################################################################

"""US-641: a stale light reading degrades honestly instead of holding its value."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "src",
    ),
)

import render_harness as rh  # noqa: E402

from pi.bus.sample import Sample  # noqa: E402
from pi.sensors.light_state_bridge import (  # noqa: E402
    LIGHT_STATE_FILENAME,
    LightStateBridge,
)
from pi.splash.states_http_server import loadDisplayAutoDimConfig  # noqa: E402

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default.
PANEL = (480, 320)

_REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
CONFIG_PATH = os.path.join(_REPO, "config.json")

# THE DEPLOYED auto-dim curve, read by the same loader states_http_server calls to
# substitute window.DISPLAY_AUTODIM. Deliberately NOT a literal:
#
#   DRIFT FOUND 2026-08-31 (US-641), recorded because it is the reason this is a
#   loader call and not a copy. test_carousel_brightness.py's `_CFG` is commented
#   "mirrors config.json pi.display.autoDim" and NO LONGER DOES -- it carries
#   luxFull 1000.0 / minLevel 0.15 / defaultLevel 0.70, which are the VALIDATOR
#   DEFAULTS (validator.py DEFAULTS), while config.json ships 300.0 / 0.75 / 1.0
#   after the US-627 retune. Both files are internally consistent, so nothing went
#   red; the cost is that no test exercised the curve the Pi actually runs. Reading
#   the real file means a future retune moves these assertions with it. See
#   TD-us641.
_AUTODIM: dict[str, Any] | None = loadDisplayAutoDimConfig(CONFIG_PATH)

# A fixed instant + the canonical second-resolution ISO the producer stamps
# (common.time.helper.CANONICAL_ISO_FORMAT -- "YYYY-MM-DDTHH:MM:SSZ").
_T0 = dt.datetime(2026, 8, 31, 12, 0, 0, tzinfo=dt.UTC)
_T0_MS = int(_T0.timestamp() * 1000)
_T0_ISO = _T0.strftime("%Y-%m-%dT%H:%M:%SZ")

# A cabin dark enough to sit at/below luxMin, so the curve pins to its floor and
# the dimmed level is unambiguous.
_DARK_LUX = 1.0


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def autoDim() -> dict[str, Any]:
    """The deployed pi.display.autoDim, or fail loudly rather than guess."""
    assert _AUTODIM is not None, f"could not load pi.display.autoDim from {CONFIG_PATH}"
    return _AUTODIM


# ------------------------------------------------------------------------- helpers


def _luxSample(value: float | None, *, tsUtc: str = _T0_ISO) -> Sample:
    """One raw.light.lux bus sample carrying the sensor's own read-time."""
    return Sample(
        topic="raw.light.lux",
        source="light",
        value=value,
        unit="lux",
        tsUtc=tsUtc,
        tsCapture=1.0,
        driveId=None,
        dataSource="real",
        seq=1,
    )


def _producedLightState(tmpPath: Path, sample: Sample) -> dict[str, Any]:
    """Run the REAL bridge and return the bytes it actually wrote to states/light.

    The payload every test below serves is the producer's own output, so a
    producer change that stops publishing a usable `ts` fails HERE rather than
    being masked by a hand-written fixture that always had one.
    """
    LightStateBridge(None, str(tmpPath)).handleSample(sample)
    return json.loads(
        (tmpPath / LIGHT_STATE_FILENAME).read_text(encoding="utf-8")
    )


def _findAttr(node: Any, attr: str, value: str) -> dict[str, Any] | None:
    if isinstance(node, dict) and node.get("attrs", {}).get(attr) == value:
        return node
    for child in (node or {}).get("children", []) or []:
        found = _findAttr(child, attr, value)
        if found is not None:
            return found
    return None


def _text(node: dict[str, Any] | None) -> str:
    if node is None:
        return ""
    if "text" in node:
        return str(node["text"])
    return " ".join(_text(c) for c in node.get("children", []) or []).strip()


def _brightness(tree: dict[str, Any]) -> float:
    """The --display-brightness the SHIPPED js left on the screen frame."""
    screen = _findAttr(tree, "id", "screen")
    assert screen is not None, "#screen is not in the rendered tree"
    style = screen.get("style") or {}
    assert "--display-brightness" in style, (
        f"the js set no --display-brightness (inline style: {style})"
    )
    return float(style["--display-brightness"])


def _lightCardText(tree: dict[str, Any]) -> str:
    card = _findAttr(tree, "data-state", "light")
    assert card is not None, "the Light card is not in the rendered tree"
    return _text(card)


def _run(
    autoDimCfg: dict[str, Any],
    light: Any,
    *,
    nowMs: int,
    steps: list[dict[str, Any]] | None = None,
    dtc: Any = None,
) -> dict[str, Any]:
    """Boot the SHIPPED carousel over the SHIPPED markup at the panel size.

    ``light`` is served at /light; pass None to model the state file being ABSENT
    (an unlisted route 404s -- nothing is invented on the test's behalf).
    """
    routes: dict[str, Any] = {}
    if light is not None:
        routes["/light"] = light
    if dtc is not None:
        routes["/dtc"] = dtc
    return rh.runDashboard(
        routes=routes,
        autoDim=autoDimCfg,
        nowMs=nowMs,
        steps=steps or [{"flush": 3}],
        viewport=PANEL,
    )


# =============================================================================
# 1. The recorded pass -- the panel tracks a LIVE reading, producer to pixel.
#    These are the control: without them a later "fell back to defaultLevel" is
#    indistinguishable from a panel that never responded to lux at all.
# =============================================================================


def test_liveDarkReading_dimsThePanelToTheCurveFloor(autoDim, tmp_path):
    """
    Given: the REAL bridge publishes a dark cabin reading, one second old
    When: the shipped carousel ticks over the shipped markup
    Then: the screen frame carries the CURVE level (clamped to minLevel), and the
          Light card prints the reading -- so the panel is demonstrably live
    """
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX))

    tree = _run(autoDim, state, nowMs=_T0_MS + 1000)["tree"]

    assert _brightness(tree) == pytest.approx(autoDim["minLevel"])
    assert "lx" in _lightCardText(tree)


def test_liveMidRangeReading_landsBetweenTheFloorAndFull(autoDim, tmp_path):
    """
    Given: a reading high enough that the log curve clears minLevel
    When: the panel renders it
    Then: the brightness is STRICTLY between the floor and full

    A level that only ever reads minLevel or 1.0 could be produced by a
    two-branch stub; this is what proves the curve is actually evaluated, and it
    makes the fallback below a real change of behaviour rather than a coincidence.
    """
    state = _producedLightState(tmp_path, _luxSample(150.0))

    level = _brightness(_run(autoDim, state, nowMs=_T0_MS + 1000)["tree"])

    assert autoDim["minLevel"] < level < 1.0


# =============================================================================
# 2. THE NEGATIVE CASE THE STORY NAMES: a FROZEN feed ages out.
#    The state file is byte-identical across every test in this section -- only
#    the wall clock moves, which is the whole point (see the file header).
# =============================================================================


def test_frozenFeed_beforeItAges_panelIsStillDimmedByTheReading(autoDim, tmp_path):
    """
    Given: the frozen dark reading, read 1 s ago
    When: the panel renders
    Then: it is dimmed to the curve floor

    THE CONTROL for the test below. Without it, "the aged panel reads
    defaultLevel" is satisfied by a panel that was at defaultLevel the whole
    time and never honoured the reading at all.
    """
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX))

    tree = _run(autoDim, state, nowMs=_T0_MS + 1000)["tree"]

    assert _brightness(tree) == pytest.approx(autoDim["minLevel"])


def test_frozenFeed_agedPastLuxStaleSec_panelReturnsToDefaultLevel(autoDim, tmp_path):
    """
    Given: the SAME frozen dark reading -- the producer has stopped writing
    When: the clock walks 30 s past it and the panel repaints
    Then: brightness is defaultLevel, NOT the dimmed level it was holding

    This is the story's headline claim: it must not keep dimming from a frozen
    value. The payload is never rewritten; only time passes.
    """
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX))

    tree = _run(
        autoDim,
        state,
        nowMs=_T0_MS + 1000,
        steps=[{"flush": 3}, {"advanceMs": 30_000, "flush": 3}],
    )["tree"]

    assert _brightness(tree) == pytest.approx(autoDim["defaultLevel"])
    assert _brightness(tree) != pytest.approx(autoDim["minLevel"])


def test_frozenFeed_agedPastLuxStaleSec_cardTypesTheReadingStale(autoDim, tmp_path):
    """
    Given: the same frozen reading, aged out
    When: the Light card repaints
    Then: it reads NA with a stale reason, and the READING IS GONE

    The "typed stale" half. Asserted as a REPLACEMENT -- the unit `lx` only ever
    appears beside a real reading, so its absence is the frozen value being
    withdrawn rather than a card that never painted one.
    """
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX))

    text = _lightCardText(
        _run(
            autoDim,
            state,
            nowMs=_T0_MS + 1000,
            steps=[{"flush": 3}, {"advanceMs": 30_000, "flush": 3}],
        )["tree"]
    )

    assert "NA" in text
    assert "stale" in text
    assert "lx" not in text, f"a stale card still printed a reading: {text!r}"


def test_frozenFeed_bothSurfacesAgreeOnTheSameTick(autoDim, tmp_path):
    """
    Given: the frozen reading aged out
    When: ONE tick paints both the card and the screen frame
    Then: the card says stale AND the brightness is the fallback, together

    carousel.js resolves the whole tick against a single `nowMs` (US-496) so the
    card can never contradict the surface it explains. Both facts are read from
    ONE DOM snapshot; checking them in separate runs could not witness the
    coupling.
    """
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX))

    tree = _run(
        autoDim,
        state,
        nowMs=_T0_MS + 1000,
        steps=[{"flush": 3}, {"advanceMs": 30_000, "flush": 3}],
    )["tree"]

    assert "stale" in _lightCardText(tree)
    assert _brightness(tree) == pytest.approx(autoDim["defaultLevel"])


def test_stalledSensor_stillWriting_goesStaleBecauseTheTsIsTheREADTime(
    autoDim, tmp_path
):
    """
    Given: the sensor is stuck -- the bridge writes NOW, but the sample carries a
           read-time 60 s old
    When: the panel renders that freshly-written file
    Then: it is still treated as stale

    THE PRODUCER HALF, and the one a consumer-only test cannot reach. The bridge
    stamps the SAMPLE's read-time, never its own write-time (light_state_bridge
    header). Were that ever "simplified" to write-time, a stuck sensor would look
    permanently fresh and the panel would dim on a frozen value forever -- with
    every freshness test in this file still green, because they all age the CLOCK
    rather than the write.
    """
    staleReadTime = (_T0 - dt.timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX, tsUtc=staleReadTime))

    tree = _run(autoDim, state, nowMs=_T0_MS)["tree"]

    assert state["ts"] == staleReadTime, "the bridge did not carry the sample read-time"
    assert _brightness(tree) == pytest.approx(autoDim["defaultLevel"])
    assert "stale" in _lightCardText(tree)


# =============================================================================
# 3. The freshness EDGE. `ageSec <= luxStaleSec` is inclusive; pinned on both
#    sides so a future `<` (or a unit slip) cannot pass unnoticed.
# =============================================================================


def test_readingExactlyAtLuxStaleSec_isStillFresh(autoDim, tmp_path):
    """
    Given: the reading is exactly luxStaleSec old
    When: the panel renders
    Then: it is FRESH -- the boundary is inclusive
    """
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX))
    ageMs = int(float(autoDim["luxStaleSec"]) * 1000)

    tree = _run(autoDim, state, nowMs=_T0_MS + ageMs)["tree"]

    assert _brightness(tree) == pytest.approx(autoDim["minLevel"])


def test_readingOneMsPastLuxStaleSec_isStale(autoDim, tmp_path):
    """
    Given: the same reading, one millisecond older
    When: the panel renders
    Then: it has fallen back -- the edge is where it is claimed to be
    """
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX))
    ageMs = int(float(autoDim["luxStaleSec"]) * 1000) + 1

    tree = _run(autoDim, state, nowMs=_T0_MS + ageMs)["tree"]

    assert _brightness(tree) == pytest.approx(autoDim["defaultLevel"])


# =============================================================================
# 4. The OTHER absences. Three distinct faults must reach the fallback by three
#    distinguishable routes -- the card names which one, the brightness does not
#    have to.
# =============================================================================


def test_saturatedReading_holdsDefaultAndNamesTheCauseNotStaleness(autoDim, tmp_path):
    """
    Given: the REAL bridge writes a saturated read (lux null, honest -- never 0.0)
    When: the panel renders it FRESH
    Then: brightness is the fallback and the card says unreadable, NOT stale

    A saturated sensor and a stopped one are different faults; collapsing them
    would leave the operator unable to tell a blinded sensor from a dead feed.
    """
    state = _producedLightState(tmp_path, _luxSample(None))
    assert state["lux"] is None, "the bridge fabricated a reading for a saturated read"

    tree = _run(autoDim, state, nowMs=_T0_MS + 1000)["tree"]
    text = _lightCardText(tree)

    assert _brightness(tree) == pytest.approx(autoDim["defaultLevel"])
    assert "NA" in text
    assert "stale" not in text, f"a saturated read was reported as stale: {text!r}"


def test_absentStateFile_holdsDefaultNeverGoesDark(autoDim):
    """
    Given: no states/light at all (the route 404s -- the bridge never ran)
    When: the panel renders
    Then: brightness is defaultLevel

    The failure that would matter is the opposite one: a missing file read as
    lux 0 would drive the panel to its floor in broad daylight.
    """
    tree = _run(autoDim, None, nowMs=_T0_MS)["tree"]

    assert _brightness(tree) == pytest.approx(autoDim["defaultLevel"])


def test_undatedReading_isNeverTreatedAsCurrent(autoDim):
    """
    Given: a payload carrying a real lux but no parseable read time
    When: the panel renders
    Then: it falls back rather than assuming the reading is current

    An undated reading is the one MOST likely to be stale, so "no ts" must never
    resolve to "fresh". Served directly: the shipped bridge cannot emit this
    shape, and the consumer must not depend on that staying true.
    """
    tree = _run(autoDim, {"lux": _DARK_LUX, "ts": "not-a-timestamp"}, nowMs=_T0_MS)[
        "tree"
    ]

    assert _brightness(tree) == pytest.approx(autoDim["defaultLevel"])


# =============================================================================
# 5. The fallback must not defeat the safety override, and must not be a
#    hardcoded number.
# =============================================================================


# The STOP override is asserted against configs whose OTHER answer is not 1.0.
#
# WHY THAT MATTERS, and it is a trap this file fell into first: the DEPLOYED
# config has defaultLevel 1.0, which is exactly STOP_ALARM_LEVEL. Asserting
# "brightness == 1.0" under the shipped numbers is therefore satisfied by the
# stale fallback ALONE -- measured, not reasoned: deleting
# `if (alarmActive) return STOP_ALARM_LEVEL` left that assertion GREEN. An
# assertion two different mechanisms satisfy is evidence for neither.
_DIM_FALLBACK_CFG = {
    "luxMin": 3.0,
    "luxFull": 300.0,
    "minLevel": 0.20,
    "defaultLevel": 0.42,  # deliberately NOT full, so only the alarm can reach 1.0
    "luxStaleSec": 10,
    "curve": "logarithmic",
}

_STOP_DTC = {"codes": [{"code": "P0300", "severity": "stop"}]}


def test_activeStop_overridesTheDimmedCurveOnALiveFeed(autoDim, tmp_path):
    """
    Given: a LIVE dark reading (which alone dims the panel to the curve floor)
           and a real STOP-tier code
    When: the panel renders
    Then: the surface is FULL, not the dimmed level

    US-484-b / Spool 6d ch.4: the darkest cabin cannot dim a PULL-OVER alarm.
    The control is test_liveDarkReading_dimsThePanelToTheCurveFloor, which shows
    this same reading reaching minLevel when no alarm is active.
    """
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX))

    tree = _run(autoDim, state, nowMs=_T0_MS + 1000, dtc=_STOP_DTC)["tree"]

    assert _brightness(tree) == pytest.approx(1.0)
    assert _brightness(tree) != pytest.approx(autoDim["minLevel"])


def test_frozenFeedUnderActiveStop_staysFullBrightnessNotTheFallback(tmp_path):
    """
    Given: the light feed has frozen AND a real STOP-tier code is active
    When: the aged panel renders under a config whose fallback is NOT full
    Then: the surface is FULL -- the alarm overrides the honest fallback

    Pinned HERE because the fallback is the branch most likely to be "tidied"
    into a single return: a dead light sensor must never be able to dim a
    PULL-OVER alarm. The 0.42 fallback is what makes this test able to fail.
    """
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX))

    tree = _run(
        _DIM_FALLBACK_CFG,
        state,
        nowMs=_T0_MS + 1000,
        steps=[{"flush": 3}, {"advanceMs": 30_000, "flush": 3}],
        dtc=_STOP_DTC,
    )["tree"]

    assert _brightness(tree) == pytest.approx(1.0)
    assert _brightness(tree) != pytest.approx(0.42), (
        "a frozen light feed dimmed a live PULL-OVER alarm to the fallback"
    )


def test_fallbackLevelComesFromConfig_notAHardcodedConstant(tmp_path):
    """
    Given: an injected config whose defaultLevel is a value no default supplies
    When: the feed ages out
    Then: the panel falls back to THAT value

    Retunes must be a config change, not a code change (CIO 2026-07-22). With
    only the shipped numbers asserted, a hardcoded fallback would pass every
    other test in this file.
    """
    cfg = {
        "luxMin": 3.0,
        "luxFull": 300.0,
        "minLevel": 0.20,
        "defaultLevel": 0.42,
        "luxStaleSec": 10,
        "curve": "logarithmic",
    }
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX))

    tree = _run(
        cfg,
        state,
        nowMs=_T0_MS + 1000,
        steps=[{"flush": 3}, {"advanceMs": 30_000, "flush": 3}],
    )["tree"]

    assert _brightness(tree) == pytest.approx(0.42)


def test_deployedConfig_keepsDefaultLevelAtOrAboveMinLevel(autoDim):
    """
    Given: the DEPLOYED pi.display.autoDim
    When: the US-627 floor coupling is checked
    Then: defaultLevel >= minLevel

    The fallback branch returns defaultLevel UNCLAMPED on purpose, so this
    inequality is the only thing keeping a dead light sensor from rendering below
    the legibility floor. validate_config enforces it; this pins that the file
    the Pi actually ships still satisfies it.
    """
    assert float(autoDim["defaultLevel"]) >= float(autoDim["minLevel"])


# =============================================================================
# 6. The JS and the CSS agree on the variable. US-495 was correct JS defeated by
#    a stylesheet that never read it -- a grep over either file alone is blind to
#    that, so the var is resolved through the real cascade here.
# =============================================================================


def test_theBrightnessVarTheJsSets_isTheVarTheStylesheetReads(autoDim, tmp_path):
    """
    Given: the shipped js has written --display-brightness on #screen
    When: the shipped stylesheet is resolved over that same tree
    Then: #screen's winning `filter` consumes that exact custom property
    """
    state = _producedLightState(tmp_path, _luxSample(_DARK_LUX))
    tree = _run(autoDim, state, nowMs=_T0_MS + 1000)["tree"]

    surface = rh.dashboardSurface(tree, viewport=PANEL)
    path = surface.pathById("screen")
    assert path is not None, "#screen did not survive into the resolved surface"
    winner = surface.winningDeclaration(path, "filter")

    assert winner is not None, "nothing declares a filter on #screen"
    assert "--display-brightness" in winner[0], (
        f"#screen's filter ignores the var the js sets: {winner}"
    )
