################################################################################
# File Name: test_carousel_obd_source_unavailable_render.py
# Purpose/Description: US-637 (F-138, punch-list 3.1) -- RECORD THE PASS on the
#   OBD source's honest unavailability, ON THE RENDERED PANEL and through the
#   REAL acquisition path, and record the finding the recording exposed.
#
#   WHY THIS FILE EXISTS WHEN THE BEHAVIOUR IS "ALREADY TESTED". It is tested in
#   two halves that never meet:
#     * tests/pi/splash/test_source_availability.py proves the PRODUCER emits
#       {"available": false, "reason": "OBD: off"}.
#     * tests/ui/test_carousel_honest_availability.py:67 proves the VIEW turns
#       that into a typed-NA tile -- from a HAND-WRITTEN dict that this file's
#       author, not the emitter, decided the shape of.
#   Neither notices if the producer renames the key, neither renders a pixel,
#   and NOTHING anywhere asserts the REASON on the production path: the only
#   test of `_gatherObdLinkState`'s unavailable branch
#   (test_card_state_emitters.py::test_maybeEmit_noConnection_parked_
#   idleTrueTypedNa) reads `available` and stops. The word the driver actually
#   reads was unpinned. That is the US-494/495/498 two-correct-halves shape for
#   the fourth sprint running, so every assertion below goes end to end:
#   REAL orchestrator -> REAL emitter -> state file -> SHIPPED carousel.js ->
#   SHIPPED markup + stylesheet at 480x320.
#
#   THE PASS IS REAL AND IS RECORDED BELOW. Atlas's punch-list 3.1 observation
#   (available:false, reason:"OBD: off") is CORRECT, and correct all the way to
#   the panel: the OBD LINK tile paints `NA` over the emitter's own reason at the
#   `unavailable` level, the BT glyph goes NEUTRAL rather than `down` ("we could
#   not look" is not "no signal"), the summary line refuses to say OK over it,
#   and the drill-down row carries the reason WITHOUT fabricating a seen-age.
#
#   THE LOAD-BEARING PIN IS THE OVERRIDE. `sourceUnavailable()` beats `obdLink`
#   outright, so a source marked unavailable renders NA even when a STALE
#   `state:"linked"` is sitting beside it in the same payload. That is the
#   story's "never renders as available-with-no-data" in its sharpest form, and
#   it is the one property no existing test could see -- every prior fixture
#   zeroed `obdLink` and `naTile` alongside each other, so a renderer that had
#   simply preferred `obdLink` would have passed them all.
#
#   FINDING RECORDED, NOT FIXED (sprint contract: a VERIFY story that finds a
#   defect RECORDS it and FILES a fix story -- it must NEVER quietly become the
#   fix, because that hides the defect rate the sweep exists to measure).
#   `card_state_emitter.py:341` publishes the reason as a CONSTANT:
#   `obdUnavailableReason=None if obdAvailable else REASON_OBD_OFF`. But
#   `_gatherObdLinkState` reaches False down THREE distinct paths -- no
#   connection object at all, `getStatus()` RAISED, and never-connected -- and
#   all three publish the words "OBD: off", which is a claim about the CAR. Two
#   of them are claims about US. Same shape as US-632's six causes collapsed to
#   one bare `unknown`, and the exact distinction wifiGlyphState's own comment
#   (carousel.js:873) exists to protect. Filed as
#   offices/pm/issues/I-us637-obd-off-is-a-constant-not-a-measurement.md and
#   held by the characterisation tests at the foot of this file.
#
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-637 punch-list 3.1 recorded pass +
#               |              | the constant-reason finding (I-us637).
# ================================================================================
################################################################################

"""US-637 tests: the OBD source renders honest unavailability with its reason."""

from __future__ import annotations

import json
import os
import shutil
import sys
from types import SimpleNamespace
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

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin  # noqa: E402
from pi.splash.source_availability import (  # noqa: E402
    REASON_OBD_OFF,
    buildSourceState,
)
from pi.splash.system_status_emitter import buildSystemStatusState  # noqa: E402

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default. Measuring the 3.5in kit at
# 1920x1080 resolves media queries the operator never sees.
PANEL = (480, 320)

# Spelled as escapes, never literals -- this file is written and re-read on a
# Windows SMB share where a raw em-dash / middle dot has been mangled before
# (the precaution test_carousel_sync_stamp.py and US-633's file both take).
MIDDLE_DOT = "·"
EM_DASH = "—"

# Design tokens, resolved through the REAL cascade rather than asserted as a
# colour name -- a stylesheet that repainted `unavailable` green must fail here
# rather than pass on a string comparison.
GREEN = "var(--green-ok)"

_NOW = "2026-08-31T14:46:00Z"
_FRESH_SYNC = "2026-08-31T14:45:22Z"


# ---------------------------------------------------------------------------
# Fixtures -- assembled by the SHIPPED emitter's own builder, never by hand.
# ---------------------------------------------------------------------------


def _systemStatus(**overrides: Any) -> dict:
    """A system-status payload from the shipped producer.

    Defaults describe Atlas's punch-list 3.1 bench: no car, parked, wall power,
    sync healthy -- i.e. the OBD source UNAVAILABLE, which is the state this
    story records. Every other source is deliberately HEALTHY so that any
    non-green this file observes can only have come from the OBD source.

    `obdLastSeenS` is a REAL NUMBER on purpose. The producer blanks the whole
    `obdLink` block when the source is unavailable, so a fixture that passed
    None here would make that blanking invisible: the drill-down's freshness
    would read "age not reported" whether the producer zeroed the field or not,
    and the assertion that it does would be inert. Handing it a value the
    producer must throw away is what makes the guard load-bearing.
    """
    args: dict[str, Any] = {
        "obdLinkState": "down",
        "obdRetries": 0,
        "obdLastSeenS": 7,
        "syncLastOkTs": _FRESH_SYNC,
        "syncRows": 1204,
        "syncPending": 0,
        "syncStale": False,
        "powerMode": "wall",
        "powerSource": "external",
        "driveState": "idle",
        "driveId": None,
        "nowIso": _NOW,
        "obdAvailable": False,
        "obdUnavailableReason": REASON_OBD_OFF,
    }
    args.update(overrides)
    return buildSystemStatusState(**args)


# ---------------------------------------------------------------------------
# The REAL acquisition path. `buildSystemStatusState` is only the second link in
# the chain; the field this story is about is decided one layer UP, in the
# orchestrator, and that layer's choice of reason is what reaches the driver.
# ---------------------------------------------------------------------------


class _Orch(CardStateEmitterMixin):
    """The minimal composing object the mixin reads, as the orchestrator does.

    Mirrors tests/pi/orchestrator/test_card_state_emitters.py::_FakeOrch. The
    point of using the mixin at all rather than calling the emitter directly is
    that `_gatherObdLinkState` -> `obdUnavailableReason` is the wiring this
    story's word ("with its reason") actually lives in.
    """

    def __init__(self, statesDir: str, *, connection: Any = None) -> None:
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
            }
        }
        self._connection = connection
        self._driveDetector = None
        self._powerSourceProvider = SimpleNamespace(
            isAvailable=True, isExternalPowerPresent=lambda: True
        )
        self._hardwareManager = None
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = SimpleNamespace(getPowerMode=lambda: "wall")
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = _FRESH_SYNC
        self._lastSyncRows = 1204


def _emitToStateFile(tmp_path, connection: Any = None) -> dict:
    """Run the REAL orchestrator emit and return what it wrote to disk."""
    statesDir = str(tmp_path / "states")
    orch = _Orch(statesDir, connection=connection)
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True, "the emitter wrote nothing"
    return json.loads(
        (tmp_path / "states" / "system-status").read_text(encoding="utf-8")
    )


def _connectionStatus(**kwargs: Any) -> Any:
    base: dict[str, Any] = {
        "connected": False,
        "retryCount": 0,
        "totalConnections": 0,
        "state": "disconnected",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Reading the rendered panel.
# ---------------------------------------------------------------------------


def _surface(payload: Any, steps: list[dict[str, Any]] | None = None):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet."""
    routes = {} if payload is None else {"/system-status": payload}
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


# The drill-down is rendered only while the overlay is OPEN, so reaching it
# means TAPPING the summary line the way the operator does. The line is built by
# carousel.js and carries no id, so it is reached by class via the `clickNth`
# step US-635 added for exactly this reason.
_OPEN_DRILL = [
    {"flush": 4},
    {"clickNth": {"selector": ".sys-summary", "index": 0}},
    {"flush": 1},
]


def _textOf(node: dict) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _tilePathByLabel(surface, label: str) -> list[dict] | None:
    """The rendered `.tile` whose own label reads `label`.

    Found by its PRINTED LABEL rather than by grid position, so a tile that
    moved in the 2x2 layout still resolves and a tile that vanished fails loudly
    instead of silently matching its neighbour.
    """
    for path in surface.pathsByClass("tile"):
        for child in path[-1].get("children", []):
            for text in _textOf({"children": [child]}):
                if text == label:
                    return path
    return None


def _obdTile(payload: Any) -> dict:
    """The OBD LINK tile as the operator sees it on the 480x320 panel.

    Returns the printed value/detail, the level the stylesheet is keyed on, and
    the COLOUR that level actually resolves to -- because "not green" is a claim
    about the panel, and a level token only means not-green while the sheet
    agrees.
    """
    surface = _surface(payload)
    path = _tilePathByLabel(surface, "OBD LINK")
    assert path is not None, "no OBD LINK tile in the rendered DOM"
    assert surface.rendered(path), "the OBD LINK tile is in the DOM but not displayed"

    texts = _textOf(path[-1])
    value = ""
    detail = ""
    for child in path[-1].get("children", []):
        classes = (child.get("attrs", {}).get("class") or "").split()
        if "tile-value" in classes:
            value = " ".join(_textOf(child))
        elif "tile-detail" in classes:
            detail = " ".join(_textOf(child))

    valuePath = None
    for child in path[-1].get("children", []):
        if "tile-value" in (child.get("attrs", {}).get("class") or "").split():
            valuePath = path + [child]
    declaration = (
        surface.winningDeclaration(valuePath, "color") if valuePath else None
    )
    return {
        "value": value,
        "detail": detail,
        "level": path[-1].get("attrs", {}).get("data-level"),
        "colour": declaration[0] if declaration else "",
        "texts": texts,
    }


def _systemCardText(payload: Any) -> list[str]:
    """The whole System Status card's rendered text, in reading order."""
    surface = _surface(payload)
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == "system-status":
            return _textOf(path[-1])
    return []


def _btGlyph(payload: Any) -> str:
    surface = _surface(payload)
    path = surface.pathById("glyph-bt")
    assert path is not None, "no #glyph-bt in the rendered DOM"
    assert surface.rendered(path), "#glyph-bt is in the DOM but not displayed"
    return path[-1].get("attrs", {}).get("data-state")


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS FIRST. Most assertions in this file are absence-shaped
# ("never green", "no fabricated age"), and every one of them passes vacuously
# if the harness reads nothing at all. A renamed class or a probe crash would
# turn the whole file green while pinning nothing.
# ---------------------------------------------------------------------------


def test_theHarnessActuallyReadsTheObdTile_negativeControl():
    """
    Given: every "must not" assertion below fails open if the tile is unreadable
    When: an unmistakably AVAILABLE, linked OBD source is rendered
    Then: the harness reads a real value, a real level and a real colour.
    """
    tile = _obdTile(
        _systemStatus(obdAvailable=True, obdLinkState="linked", obdLastSeenS=2)
    )
    assert tile["value"] == "LINKED", f"harness read no tile value: {tile!r}"
    assert tile["level"] == "ok", f"harness read no tile level: {tile!r}"
    assert tile["colour"] == GREEN, f"harness read no tile colour: {tile!r}"


def test_theStylesheetPaintsGreenOnlyForTheOkLevel():
    """
    Given: this file repeatedly claims the NA tile is "not green"
    When: the shipped stylesheet is resolved for each tile level in turn
    Then: `ok` is the ONLY level that resolves to the green token.

          Without this, "not green" only means "the token is not the string ok",
          and a sheet that painted `unavailable` green would leave this file
          passing while the panel claimed a link it never had.
    """
    surface = _surface(_systemStatus())
    path = _tilePathByLabel(surface, "OBD LINK")
    assert path is not None
    valuePath = None
    for child in path[-1].get("children", []):
        if "tile-value" in (child.get("attrs", {}).get("class") or "").split():
            valuePath = path + [child]
    assert valuePath is not None

    resolved = {}
    for level in ("ok", "amber", "down", "neutral", "unavailable"):
        path[-1]["attrs"]["data-level"] = level
        declaration = surface.winningDeclaration(valuePath, "color")
        resolved[level] = declaration[0] if declaration else ""

    assert resolved["ok"] == GREEN, resolved
    greens = [level for level, colour in resolved.items() if colour == GREEN]
    assert greens == ["ok"], f"green is reachable from more than `ok`: {resolved}"


def test_theSystemCardIsReachableWhileTheObdSourceIsAbsent():
    """
    Given: `idle` is (not obdAvailable) and not recording -- so EVERY payload in
           this file sets idle True, and US-542 retired the STANDBY face that
           idle used to select
    When: that payload is rendered
    Then: the System Status card is still painted.

          THE WHOLE FILE RESTS ON THIS. If `idle` still routed the panel away
          from the System card, every "the tile says NA" assertion below would
          be pinning a surface no operator can reach -- true, and worthless.
          US-636 is the precedent: an absence test passed there for the wrong
          nested reason and the mutation was what exposed it, so the reachability
          is asserted by name rather than inferred from the tile being findable.
    """
    payload = _systemStatus()
    assert payload["idle"] is True, "fixture no longer exercises the idle path"
    assert "OBD LINK" in _systemCardText(payload), (
        "the System card did not paint while the OBD source was absent"
    )


# ---------------------------------------------------------------------------
# THE RECORDED PASS (validationCriteria 1). Atlas observed source.obd
# available:false with reason "OBD: off" (punch list 3.1) and believed it
# correct. It is correct, and this is now evidence rather than a memory.
# ---------------------------------------------------------------------------


def test_obdUnavailable_tilePaintsTypedNaOverTheEmittersOwnReason():
    """
    Given: THE OBSERVATION THIS STORY RECORDS -- source.obd.available false with
           reason "OBD: off"
    When: the shipped dashboard renders it on the 480x320 panel
    Then: the tile reads NA over that reason, at the `unavailable` level, and is
          NOT painted green.

          The reason is asserted against REASON_OBD_OFF -- the producer's own
          constant -- not against the string "OBD: off". A test that hard-codes
          the words passes after someone changes them, which is the one moment
          it needed to speak up.
    """
    tile = _obdTile(_systemStatus())
    assert tile["value"] == "NA", tile
    assert tile["detail"] == REASON_OBD_OFF, tile
    assert tile["level"] == "unavailable", tile
    assert tile["colour"] != GREEN, tile


def test_obdUnavailable_theReasonIsPrintedNotJustCarried():
    """
    Given: "with its reason" is the story's title, and a reason held in the view
           object but never painted would satisfy every prior test
    When: the System card is rendered
    Then: the reason appears in the card's rendered TEXT.
    """
    assert REASON_OBD_OFF in _systemCardText(_systemStatus())


def test_obdAvailable_rendersTheRealLinkState_soTheNaIsNotUnconditional():
    """
    Given: "always NA" would pass every assertion above
    When: the OBD source is AVAILABLE and the link is live
    Then: the real link state renders and the NA is nowhere on the card.
    """
    payload = _systemStatus(obdAvailable=True, obdLinkState="linked", obdLastSeenS=2)
    tile = _obdTile(payload)
    assert tile["value"] == "LINKED", tile
    assert tile["detail"] == "seen 2s ago", tile
    assert REASON_OBD_OFF not in _systemCardText(payload)


def test_obdAvailableButDown_stillRendersTheMeasurement_notTheAbsence():
    """
    Given: a link that DROPPED after a real connection -- the source is present
           (we are retrying a car we have actually spoken to), the link is not
    When: rendered
    Then: the tile says DOWN, a MEASUREMENT, not the typed NA.

          This is the distinction the whole honest-availability contract turns
          on, and it is the half a "when in doubt say NA" regression would break
          silently: an operator who is told NA while the Pi is actively retrying
          a real car has been denied the one fact that would explain the panel.
    """
    tile = _obdTile(
        _systemStatus(obdAvailable=True, obdLinkState="down", obdRetries=3)
    )
    assert tile["value"] == "DOWN", tile
    assert tile["level"] == "down", tile


def test_obdUnavailable_btGlyphGoesNeutral_neverDown():
    """
    Given: `down` on the top bar is a MEASUREMENT -- we looked and there is no
           link
    When: the source is unavailable, i.e. we could not look
    Then: the glyph is NEUTRAL.

          carousel.js:873 states this rule for the WIFI glyph in the same file;
          the OBD glyph obeys it too and nothing said so. Painting "no signal"
          when the truth is "we could not look" is a fabricated reading.
    """
    assert _btGlyph(_systemStatus()) == "neutral"
    assert _btGlyph(_systemStatus(obdAvailable=True, obdLinkState="down")) == "down"


def test_obdUnavailable_summaryNeverClaimsSystemOk():
    """
    Given: the summary line is a LOSSY compression of four tiles, which makes it
           exactly where a green-when-unread lie enters
    When: the OBD source is unavailable and every OTHER source is healthy
    Then: the headline counts the unknown and names the source, and the words
          SYSTEM OK appear nowhere on the card.

          The other three sources are healthy ON PURPOSE: it means the only
          thing that can stop this card going green is the OBD source itself.
    """
    text = _systemCardText(_systemStatus())
    assert f"SYSTEM {MIDDLE_DOT} 1 UNAVAILABLE" in text, text
    assert f"OBD LINK {MIDDLE_DOT} NA" in text, text
    assert f"SYSTEM {MIDDLE_DOT} OK" not in text, text


def test_allSourcesHealthy_summaryDoesSayOk_soTheGuardAboveIsNotVacuous():
    """
    Given: "SYSTEM OK is absent" also passes on a card that can never say it
    When: every source including OBD is healthy
    Then: the card DOES say SYSTEM OK.
    """
    text = _systemCardText(
        _systemStatus(obdAvailable=True, obdLinkState="linked", obdLastSeenS=2)
    )
    assert f"SYSTEM {MIDDLE_DOT} OK" in text, text


# ---------------------------------------------------------------------------
# THE OVERRIDE. The story's negative case -- "an unavailable source never
# renders as available-with-no-data" -- in its sharpest form. Every prior
# fixture zeroed `obdLink` and marked the source unavailable TOGETHER, so a
# renderer that simply preferred `obdLink` would have passed all of them.
# ---------------------------------------------------------------------------


def test_unavailableSourceBeatsAStaleLinkedBlockSittingBesideIt():
    """
    Given: a payload carrying BOTH `source.obd.available: false` AND a stale
           `obdLink.state: "linked"` with a seen-age -- the shape a producer
           regression that stopped zeroing the link block would emit
    When: rendered
    Then: the tile is the typed NA. The source is the one truth; the stale link
          block loses.

          This is the property that makes the contract worth anything: without
          it, honest availability holds only for as long as one producer keeps
          voluntarily blanking a field the renderer was never told to ignore.
    """
    payload = _systemStatus()
    payload["obdLink"] = {"state": "linked", "retries": 0, "lastSeenS": 4}
    tile = _obdTile(payload)
    assert tile["value"] == "NA", tile
    assert tile["detail"] == REASON_OBD_OFF, tile
    assert "LINKED" not in _systemCardText(payload)
    assert "seen 4s ago" not in _systemCardText(payload)


def test_unavailableSourceBeatsAStaleLinkedBlock_onTheGLYPHToo():
    """
    Given: the same both-halves-disagree payload, read at the TOP BAR
    When: rendered
    Then: the BT glyph is NEUTRAL, not the green a stale `linked` would earn.

          Split from the tile assertion deliberately. On the producer's real
          output the glyph is neutral for a SECOND, weaker reason -- the emitter
          blanked `obdLink`, so `btGlyphState` would return neutral even if the
          glyph consulted the wrong input entirely. Only a payload where the two
          halves DISAGREE can tell which guarantee is holding, and the glyph's
          own `obdOff ? "neutral"` branch is the one this story is about.
    """
    payload = _systemStatus()
    payload["obdLink"] = {"state": "linked", "retries": 0, "lastSeenS": 4}
    assert _btGlyph(payload) == "neutral"


def test_unavailableWithNoReason_stillPrintsAReason_neverABlankDetail():
    """
    Given: the story's negative case -- an unavailable source ALWAYS carries a
           reason
    When: the source block is unavailable with a null reason (the producer's own
           fallback path, `buildSourceState(False, None)`)
    Then: the tile still prints a word, and it is the producer's fallback.

          A blank detail line is the failure this guards: it renders as a tile
          that simply says NA and declines to say why, which is the difference
          between an instrument reporting an absence and one that has stopped
          talking.
    """
    payload = _systemStatus()
    payload["source"]["obd"] = buildSourceState(False, None)
    assert payload["source"]["obd"]["reason"] == "unavailable"
    tile = _obdTile(payload)
    assert tile["value"] == "NA", tile
    assert tile["detail"] == "unavailable", tile
    assert tile["detail"] != "", tile


def test_unavailableSource_drillRowCarriesTheReasonAndNoFabricatedAge():
    """
    Given: the drill-down reads freshness from `data.obdLink.lastSeenS` -- a
           SECOND read, independent of the tile it lists
    When: the real producer's unavailable payload is rendered and the overlay
          drawn
    Then: the row carries the reason and says the age was NOT REPORTED.

          The honesty of that row therefore depends on the PRODUCER zeroing
          `obdLink`, not on the renderer. Two individually-correct halves with
          nothing on the join -- so the join is what is asserted, on the real
          producer's own output.
    """
    payload = _systemStatus()
    surface = _surface(payload, steps=_OPEN_DRILL)
    rows = [
        " ".join(_textOf(path[-1]))
        for path in surface.pathsByClass("sys-issue-row")
    ]
    obdRows = [row for row in rows if "OBD LINK" in row]
    assert len(obdRows) == 1, rows
    assert REASON_OBD_OFF in obdRows[0], obdRows
    # Asserted on the RENDERED ROW before the producer field, so a producer that
    # stops blanking `obdLink` fails here showing the fabricated age it printed
    # -- the thing the operator would actually read -- rather than as a fixture
    # complaint about a field.
    assert "age not reported" in obdRows[0], obdRows
    assert "seen" not in obdRows[0], obdRows
    assert payload["obdLink"]["lastSeenS"] is None, (
        "the producer stopped blanking obdLink -- the drill row can now print an "
        "age for a source nobody read"
    )


# ---------------------------------------------------------------------------
# THE CHAIN, END TO END. Everything above starts at `buildSystemStatusState`.
# The fact this story is about is decided one layer UP, and the layer above is
# where the reason is CHOSEN. US-634's lesson: when a default is load-bearing,
# exercise the path production actually takes.
# ---------------------------------------------------------------------------


def test_realOrchestratorWithNoConnection_paintsNaAndTheReasonOnThePanel(tmp_path):
    """
    Given: the REAL orchestrator on a bench with no OBD connection at all --
           Atlas's punch-list 3.1 Pi
    When: it emits system-status to a real file, and the SHIPPED dashboard reads
          that file
    Then: the panel paints NA over the reason the orchestrator chose.

          Acquisition -> producer -> state file -> renderer -> DOM, in one
          assertion. No hand-written JSON anywhere in it, so a rename or a
          re-shape at ANY link fails here.
    """
    state = _emitToStateFile(tmp_path)
    assert state["source"]["obd"]["available"] is False
    assert state["source"]["obd"]["reason"] == REASON_OBD_OFF

    tile = _obdTile(state)
    assert tile["value"] == "NA", tile
    assert tile["detail"] == REASON_OBD_OFF, tile
    assert tile["level"] == "unavailable", tile


def test_realOrchestratorWithALiveCar_paintsTheLink_notTheAbsence(tmp_path):
    """
    Given: the REAL orchestrator with a connected car
    When: the same chain runs
    Then: the panel paints LINKED -- so the test above is pinning the
          orchestrator's DECISION, not a constant it always writes.
    """
    conn = SimpleNamespace(
        getStatus=lambda: _connectionStatus(
            connected=True, totalConnections=2, state="connected"
        )
    )
    state = _emitToStateFile(tmp_path, connection=conn)
    assert state["source"]["obd"]["available"] is True
    assert state["source"]["obd"]["reason"] is None

    tile = _obdTile(state)
    assert tile["value"] == "LINKED", tile


def test_realOrchestratorWithADroppedButSeenCar_paintsDown_notNa(tmp_path):
    """
    Given: the REAL orchestrator with a link that dropped after connecting
    When: the same chain runs
    Then: the source stays AVAILABLE and the panel paints the DOWN measurement.

          The third branch of `_gatherObdLinkState`, and the one that keeps the
          typed NA from swallowing a real fault: a car we have spoken to and
          lost is a MEASUREMENT, and reporting it as "we could not look" would
          hide a dropped link behind a shrug.
    """
    conn = SimpleNamespace(
        getStatus=lambda: _connectionStatus(
            connected=False, retryCount=3, totalConnections=2, state="disconnected"
        )
    )
    state = _emitToStateFile(tmp_path, connection=conn)
    assert state["source"]["obd"]["available"] is True

    tile = _obdTile(state)
    assert tile["value"] == "DOWN", tile


# ---------------------------------------------------------------------------
# CHARACTERISATION -- the finding (I-us637). These tests pin behaviour that is
# WRONG, so that fixing it fails here ON PURPOSE and the number gets re-recorded
# rather than quietly drifting. DO NOT relax them: re-record them.
# ---------------------------------------------------------------------------


def test_characterisation_unreadableStatusPublishesObdOff_aClaimAboutTheCar(
    tmp_path,
):
    """
    Given: `conn.getStatus()` RAISES -- the Pi cannot read its own connection
    When: the real orchestrator emits and the panel renders
    Then: the driver is told "OBD: off".

          MEASURED, NOT INFERRED, and it is the finding. "OBD: off" is a claim
          about the CAR. The truth here is a claim about US: we could not look.
          The producer has exactly one word for three different causes
          (card_state_emitter.py:341 hard-codes REASON_OBD_OFF), which is the
          same collapse US-632 recorded for the battery verdict's bare
          `unknown`, and the same distinction carousel.js:873 protects for wifi.

          WHEN THIS IS FIXED this test FAILS. That is intended -- re-record the
          new reason here, do not delete the case.
    """

    def _raise() -> Any:
        raise RuntimeError("adapter handle gone")

    conn = SimpleNamespace(getStatus=_raise)
    state = _emitToStateFile(tmp_path, connection=conn)
    assert state["source"]["obd"]["reason"] == REASON_OBD_OFF

    tile = _obdTile(state)
    assert tile["detail"] == REASON_OBD_OFF, tile


def test_characterisation_neverConnectedAndUnreadableAreIndistinguishable(tmp_path):
    """
    Given: three different causes reach `available: false`
    When: two of them are emitted -- no connection object, and a status read
          that raised
    Then: the state files are IDENTICAL in the source block.

          So the panel, the state file and anyone reading either has no way to
          tell "no car is plugged in" from "the Pi lost its own adapter handle".
          Those are different faults with different fixes. Recorded as the
          measurement behind I-us637.
    """

    def _raise() -> Any:
        raise RuntimeError("adapter handle gone")

    noConn = _emitToStateFile(tmp_path / "a")
    unreadable = _emitToStateFile(tmp_path / "b", connection=SimpleNamespace(getStatus=_raise))
    assert noConn["source"]["obd"] == unreadable["source"]["obd"]
    assert noConn["obdLink"] == unreadable["obdLink"]


def test_characterisation_absentSourceBlockRendersAMeasurementNotAnAbsence():
    """
    Given: `sourceUnavailable()` requires `available === false` EXACTLY, and
           treats a missing `source` block as AVAILABLE (carousel.js:527, an
           explicit pre-US-429 backward-compat choice)
    When: a payload arrives with no source block but a `down` link
    Then: the panel paints DOWN -- a measurement -- over a source it never
          confirmed.

          Recorded rather than filed as a defect: every shipped producer writes
          the block, so this is unreachable today. It is pinned because the
          default is LOAD-BEARING and invisible -- the same shape as US-633's
          `stale === true ? amber : ok`, where an else-branch that looked like a
          fallback turned out to be an affirmative claim.
    """
    payload = _systemStatus(obdAvailable=True, obdLinkState="down")
    del payload["source"]
    tile = _obdTile(payload)
    assert tile["value"] == "DOWN", tile
    assert tile["level"] == "down", tile
