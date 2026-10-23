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
#   THAT FINDING IS NOW FIXED (US-663, 2026-08-31), which is exactly what the
#   characterisation tests were left here to force. The three causes now publish
#   three different reasons, so the three tests below that pinned the collapse
#   have been RE-RECORDED against the new behaviour rather than deleted -- the
#   cases stay, the expectations moved. `REASON_OBD_OFF` survives on the ONE
#   branch it was ever true of (we looked, and there is no car), and the wider
#   invariant is pinned in tests/ui/test_carousel_obd_link_typed_unknown.py.
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
# 2026-10-23    | Ralph (Rex)  | MOVED PIN (US-894-a): #glyph-bt is the link
#               |              | chain; its dots read `link`, not source.obd.
# 2026-10-23    | Ralph (Rex)  | MOVED PIN (US-894-b): the OBD LINK tile, the
#               |              | `SYSTEM · …` summary and obdLink are retired. The
#               |              | panel half now reads the System page's OBD row,
#               |              | which reads `link` verbatim and ignores
#               |              | source.obd (spec s4.2); the PRODUCER half -- one
#               |              | typed reason per cause in source.obd -- is
#               |              | unchanged and still pinned end to end.
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

from pi.obdii.orchestrator.card_state_emitter import (  # noqa: E402
    REASON_OBD_LINK_NOT_READ,
    REASON_OBD_LINK_UNREADABLE,
    CardStateEmitterMixin,
)
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

    MOVED PIN (US-894-b): obdLink and its two builder parameters are retired;
    the payload carries no link state outside `link`.
    """
    args: dict[str, Any] = {
        "syncLastOkTs": _FRESH_SYNC,
        # MOVED PIN (US-894-c): syncRows / syncPending dropped -- sync.rows / sync.pending retired (Atlas P7).
        "syncStale": False,
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


def _textOf(node: dict) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _obdRow(payload: Any) -> dict:
    """The System page's OBD row as the operator sees it on the 480x320 panel.

    MOVED PIN (US-894-b): was `_obdTile` (the retired OBD LINK tile). Returns
    the printed sentence, each step's look, the level the stylesheet is keyed
    on and the colour the first step actually resolves to.
    """
    surface = _surface(payload)
    # MOVED PIN (US-894-c): the DATA row follows; this reads the OBD row.
    rows = [p for p in surface.pathsByClass("sys-row")
            if p[-1]["attrs"].get("data-row") == "obd"]
    assert len(rows) == 1, f"the System page paints {len(rows)} rows, not the OBD row"
    path = rows[0]
    assert surface.rendered(path), "the OBD row is in the DOM but not displayed"
    sentence = surface.pathsByClass("sys-row-sentence")[0]
    steps = surface.pathsByClass("obd-step")
    colour = surface.winningDeclaration(steps[0], "color")
    return {
        "sentence": " ".join(_textOf(sentence[-1])),
        "steps": [step[-1]["attrs"].get("data-state") for step in steps],
        "level": path[-1].get("attrs", {}).get("data-level"),
        "colour": colour[0] if colour else "",
        "texts": _textOf(path[-1]),
    }


def _systemCardText(payload: Any) -> list[str]:
    """The whole System Status card's rendered text, in reading order."""
    surface = _surface(payload)
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == "system-status":
            return _textOf(path[-1])
    return []


def _chain(payload: Any) -> dict[str, str]:
    """MOVED PIN (US-894-a): #glyph-bt is the link chain -> {layer: data-state}."""
    surface = _surface(payload)
    path = surface.pathById("glyph-bt")
    assert path is not None, "no #glyph-bt in the rendered DOM"
    assert surface.rendered(path), "#glyph-bt is in the DOM but not displayed"
    dots = surface.pathsByClass("chain-dot")
    assert len(dots) == 3, f"the chain paints {len(dots)} dots, not 3"
    return {
        dot[-1]["attrs"]["data-layer"]: dot[-1]["attrs"].get("data-state") for dot in dots
    }


_HOLLOW = {"bt": "hollow", "adapter": "hollow", "ecu": "hollow"}
_DASHED = ["dashed", "dashed", "dashed"]


def _layers(bt: str | None, adapter: str | None, ecu: str | None) -> dict:
    return {
        layer: {"state": state, "ts": _NOW if state else None, "lastOkTs": None}
        for layer, state in (("bt", bt), ("adapter", adapter), ("ecu", ecu))
    }


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS FIRST. Most assertions in this file are absence-shaped
# ("never green", "never a reading"), and every one of them passes vacuously
# if the harness reads nothing at all. A renamed class or a probe crash would
# turn the whole file green while pinning nothing.
# ---------------------------------------------------------------------------


def test_theHarnessActuallyReadsTheObdRow_negativeControl():
    """
    Given: every "must not" assertion below fails open if the row is unreadable
    When: an unmistakably live chain is rendered
    Then: the harness reads a real sentence, real step looks and a real colour.

          MOVED PIN (US-894-b): was the OBD LINK tile's LINKED / ok / green.
    """
    row = _obdRow(_systemStatus(obdAvailable=True, link=_layers("up", "up", "up")))
    assert row["sentence"] == "ECU answering", row
    assert row["steps"] == ["ok", "ok", "ok"], row
    assert row["colour"] == GREEN, row


def test_theStylesheetPaintsGreenOnlyForTheOkStep():
    """
    Given: this file claims an unread chain is "not green"
    When: the shipped stylesheet is resolved for each step look in turn
    Then: `ok` is the ONLY look that resolves to the green token.

          MOVED PIN (US-894-b): was the tile's per-level value colour.
    """
    surface = _surface(_systemStatus())
    step = surface.pathsByClass("obd-step")[0]
    resolved = {}
    for look in ("ok", "neutral", "secondary", "tertiary", "amber", "dashed"):
        step[-1]["attrs"]["data-state"] = look
        declaration = surface.winningDeclaration(step, "color")
        resolved[look] = declaration[0] if declaration else ""
    assert resolved["ok"] == GREEN, resolved
    greens = [look for look, colour in resolved.items() if colour == GREEN]
    assert greens == ["ok"], f"green is reachable from more than `ok`: {resolved}"


def test_theSystemCardIsReachableWhileTheObdSourceIsAbsent():
    """
    Given: `idle` is (not obdAvailable) and not recording -- so EVERY default
           payload in this file sets idle True
    When: that payload is rendered
    Then: the System page is still painted, OBD row included.
    """
    payload = _systemStatus()
    assert payload["idle"] is True, "fixture no longer exercises the idle path"
    assert "OBD" in _systemCardText(payload), (
        "the System card did not paint while the OBD source was absent"
    )


# ---------------------------------------------------------------------------
# THE PANEL. MOVED PIN (US-894-b): the OBD row reads `link` verbatim and
# ignores source.obd (spec s4.2; S109 publishes link regardless). An absent
# source with an unread chain is therefore a row that says it has not read
# anything -- dashed steps, `not read yet` -- never a link state, and never
# the solid `down` look. The typed NA tile that printed source.obd's reason is
# retired with the OBD LINK tile; the reason itself is still published and
# pinned on the producer half below.
# ---------------------------------------------------------------------------


def test_obdUnavailable_unreadChain_isDashedAndNotReadYet_neverALinkState():
    row = _obdRow(_systemStatus())
    assert row["steps"] == _DASHED, row
    assert row["sentence"] == "Bluetooth not read yet", row
    assert row["colour"] != GREEN, row
    text = " ".join(_systemCardText(_systemStatus())).lower()
    assert "linked" not in text and "down" not in text, text


def test_obdUnavailable_aLiveChainStillRenders_theRowIgnoresSourceObd():
    """The positive control that the dashed row is not unconditional."""
    payload = _systemStatus(link=_layers("up", "up", "connecting"))
    assert payload["source"]["obd"]["available"] is False
    row = _obdRow(payload)
    assert row["steps"] == ["ok", "ok", "neutral"], row
    assert row["sentence"] == "ECU not answering (key off?)", row


def test_obdAvailableButBtDown_rendersTheMemberMeasurement_notAnAbsence():
    """
    Given: Bluetooth read DOWN (no retry authority) -- a MEASUREMENT
    When: rendered
    Then: the BT step is amber with the `bt` member's reason, never the dashed
          not-read look. MOVED PIN (US-894-b): was the tile's DOWN.
    """
    payload = _systemStatus(obdAvailable=True, link=_layers("down", None, None))
    member = payload["verdict"]["members"][0]
    assert member["key"] == "bt"
    row = _obdRow(payload)
    assert row["steps"][0] == "amber", row
    assert row["sentence"] == member["reason"], row


def test_obdUnavailable_unreadLinkChainIsHollow_neverDown():
    """
    Given: `down` on the top bar is a MEASUREMENT -- we looked and there is no
           link
    When: the link layers were not read
    Then: the chain is three HOLLOW dots -- never the solid `down` look.

          MOVED PIN (US-894-a): this pinned the single BT glyph NEUTRAL under an
          unavailable source. The chain reads `link` per layer (spec s4.2.1); an
          unread layer is hollow (ARCH-062), and a read `down` on a member layer
          is amber -- the positive control that the hollow is not unconditional.
    """
    assert _chain(_systemStatus()) == _HOLLOW
    assert _chain(_systemStatus(link=_layers("down", None, None)))["bt"] == "amber"


def test_theVerdictIsTheProviders_theRetiredSummaryWordsAreGone():
    """
    MOVED PIN (US-894-b): this pinned `SYSTEM · 1 UNAVAILABLE` over an absent
    OBD source. The page no longer counts anything (spec s4.1): the verdict is
    the provider's, and nothing read is no issue -- so the line reads the
    provider's ALL OK, and none of the retired summary's words survive.
    """
    payload = _systemStatus()
    assert payload["verdict"] == {"issueCount": 0, "members": []}
    text = _systemCardText(payload)
    assert text[0] == "ALL OK", text
    joined = " ".join(text)
    assert f"SYSTEM {MIDDLE_DOT}" not in joined, joined
    assert "UNAVAILABLE" not in joined and "NA" not in text, joined


def test_aStaleObdLinkBlockSittingBesideAnUnreadChain_isIgnored():
    """
    Given: a payload carrying a stale `obdLink.state: "linked"` (a producer
           regression that brought the retired block back) beside an unread
           chain
    When: rendered -- the row AND the top bar
    Then: neither reads it. The chain is the one link fact.

          MOVED PIN (US-894-b): was "the unavailable source beats the stale
          linked block" on the tile.
    """
    stale = _systemStatus()
    stale["obdLink"] = {"state": "linked", "retries": 0}
    assert _chain(stale) == _HOLLOW
    row = _obdRow(stale)
    assert row["steps"] == _DASHED, row
    assert "LINKED" not in " ".join(_systemCardText(stale)).upper()


def test_theTopBarChainReadsLinkVerbatim_neitherObdLinkNorSourceObd():
    """
    Given: a stale `linked` obdLink beside unread link layers, and live link
           layers beside an unavailable OBD source
    When: each is rendered at the TOP BAR
    Then: the chain follows `link` alone -- hollow for the first, green for the
          second.

          MOVED PIN (US-894-a): the BT glyph's `obdOff ? "neutral"` branch is
          retired with btGlyphState. The chain reads link verbatim and ignores
          source.obd (S109 publishes link regardless), so only a payload where
          the two halves DISAGREE can show which input it reads.
    """
    stale = _systemStatus()
    stale["obdLink"] = {"state": "linked", "retries": 0}
    assert _chain(stale) == _HOLLOW
    live = _systemStatus(link=_layers("up", "up", "up"))
    assert live["source"]["obd"]["available"] is False
    assert _chain(live) == {"bt": "ok", "adapter": "ok", "ecu": "ok"}


def test_unavailableWithNoReason_theProducerStillPublishesAReason():
    """
    Given: an unavailable source ALWAYS carries a reason
    When: the source block is unavailable with a null reason (the producer's
          own fallback path, `buildSourceState(False, None)`)
    Then: the published reason is the producer's fallback word, never blank.

          MOVED PIN (US-894-b): the tile that printed it is retired; the
          producer's half of the guarantee stands.
    """
    payload = _systemStatus()
    payload["source"]["obd"] = buildSourceState(False, None)
    assert payload["source"]["obd"]["reason"] == "unavailable"


def test_theProducerPublishesNoObdLinkBlock():
    """MOVED PIN (US-894-b): was "the producer blanks obdLink"; it is retired."""
    assert "obdLink" not in _systemStatus()
    assert "obdLink" not in _systemStatus(obdAvailable=True)


# ---------------------------------------------------------------------------
# THE CHAIN, END TO END. The fact this story is about is decided one layer UP
# from `buildSystemStatusState`, and the layer above is where the reason is
# CHOSEN. US-634's lesson: when a default is load-bearing, exercise the path
# production actually takes.
# ---------------------------------------------------------------------------


def test_realOrchestratorWithNoConnection_publishesTheReason_andThePageReadsNoLink(tmp_path):
    """
    Given: the REAL orchestrator on a bench with no OBD connection at all
    When: it emits system-status to a real file, and the SHIPPED dashboard reads
          that file
    Then: source.obd carries the reason the orchestrator chose, and the OBD row
          reads no link (dashed, not read yet).

          RE-RECORDED 2026-08-31 (US-663): the reason is "not read", not "OBD:
          off" -- with no connection object, NOTHING HAS LOOKED at the link.
          MOVED PIN (US-894-b): the panel half reads the OBD row.
    """
    state = _emitToStateFile(tmp_path)
    assert state["source"]["obd"]["available"] is False
    assert state["source"]["obd"]["reason"] == REASON_OBD_LINK_NOT_READ
    assert "obdLink" not in state

    row = _obdRow(state)
    assert row["steps"] == _DASHED, row
    assert row["sentence"] == "Bluetooth not read yet", row


def test_realOrchestratorWithALiveCar_publishesTheSourceAvailable(tmp_path):
    """
    Given: the REAL orchestrator with a connected car
    When: the same chain runs
    Then: the source is AVAILABLE with no reason -- so the test above is pinning
          the orchestrator's DECISION, not a constant it always writes.
    """
    conn = SimpleNamespace(
        getStatus=lambda: _connectionStatus(
            connected=True, totalConnections=2, state="connected"
        )
    )
    state = _emitToStateFile(tmp_path, connection=conn)
    assert state["source"]["obd"]["available"] is True
    assert state["source"]["obd"]["reason"] is None
    assert "obdLink" not in state


def test_realOrchestratorWithADroppedButSeenCar_keepsTheSourceAvailable(tmp_path):
    """
    Given: the REAL orchestrator with a link that dropped after connecting
    When: the same chain runs
    Then: the source stays AVAILABLE -- a car we have spoken to and lost is a
          MEASUREMENT, never "we could not look".
    """
    conn = SimpleNamespace(
        getStatus=lambda: _connectionStatus(
            connected=False, retryCount=3, totalConnections=2, state="disconnected"
        )
    )
    state = _emitToStateFile(tmp_path, connection=conn)
    assert state["source"]["obd"]["available"] is True


# ---------------------------------------------------------------------------
# WAS CHARACTERISATION, NOW VERIFICATION -- the finding (I-us637) was fixed by
# US-663 on 2026-08-31 and re-recorded against the new behaviour.
# ---------------------------------------------------------------------------


def test_unreadableStatusPublishesItsOwnReason_notAClaimAboutTheCar(
    tmp_path,
):
    """
    Given: `conn.getStatus()` RAISES -- the Pi cannot read its own connection
    When: the real orchestrator emits
    Then: the published reason says the LINK is unreadable, not that the car is
          off.
    """

    def _raise() -> Any:
        raise RuntimeError("adapter handle gone")

    conn = SimpleNamespace(getStatus=_raise)
    state = _emitToStateFile(tmp_path, connection=conn)
    assert state["source"]["obd"]["reason"] == REASON_OBD_LINK_UNREADABLE
    assert state["source"]["obd"]["reason"] != REASON_OBD_OFF


def test_neverLookedAndUnreadableAreDistinguishableInTheStateFile(tmp_path):
    """
    Given: three different causes reach `available: false`
    When: two of them are emitted -- no connection object, and a status read
          that raised
    Then: the source blocks DIFFER, and they differ in the reason.

          The chain is identical between them and that is CORRECT: both read
          nothing. MOVED PIN (US-894-b): was the blanked obdLink block.
    """

    def _raise() -> Any:
        raise RuntimeError("adapter handle gone")

    noConn = _emitToStateFile(tmp_path / "a")
    unreadable = _emitToStateFile(tmp_path / "b", connection=SimpleNamespace(getStatus=_raise))
    assert noConn["source"]["obd"] != unreadable["source"]["obd"]
    assert noConn["source"]["obd"]["reason"] == REASON_OBD_LINK_NOT_READ
    assert unreadable["source"]["obd"]["reason"] == REASON_OBD_LINK_UNREADABLE
    assert noConn["link"] == unreadable["link"]
