################################################################################
# File Name: test_carousel_obd_link_typed_unknown.py
# Purpose/Description: US-663 (F-138) -- the OBD-link state must be a TYPED
#   UNKNOWN WITH A REASON, never a guess and never an omission.
#
#   WHAT THE STORY REPORTED vs WHAT IS ACTUALLY IN THE TREE. The story's headline
#   is that `obdLink` VANISHES from system-status. It does not, and it cannot:
#   `buildSystemStatusState` builds the block unconditionally on both branches
#   (system_status_emitter.py:184-191) and there is exactly ONE writer of this
#   file in src/ (asserted below, by sweep, not by hand-grep). The first test
#   section RECORDS that as a pass and pins it against 120 consecutive samples --
#   Atlas's own 2 Hz / 60 s drill, run against the real producer.
#
#   BUT THE DEFECT THE STORY NAMES IS REAL, one layer in. On the unavailable
#   branch the producer writes `"state": null` -- which is the project's ratified
#   typed-NA shape (source_availability.py's header: "a typed absence is NULL +
#   a reason string that travels with it"), and is INDISTINGUISHABLE from an
#   omitted key to every consumer in the repo: carousel.js reaches `obdLink.state`
#   through `isObj()` + `===` compares, so a missing key and a null key take the
#   identical branch. Atlas's probe could not have told them apart either. So the
#   measurement stands, the mechanism is `null`, and the AC that bites is the
#   NEGATIVE CASE: the reason travelling with that null must be a fact, not a
#   guess.
#
#   THE FIX THIS FILE DRIVES (and it is the fix story for I-us637, filed by
#   US-637's sweep one story earlier with characterisation tests left behind on
#   purpose). `_gatherObdLinkState` reaches `available: false` down THREE paths
#   and published ONE word for all three: `REASON_OBD_OFF` -- "OBD: off", a claim
#   about the CAR. Two of the three are claims about US:
#     * no connection object at all      -> nothing has looked at the link yet
#     * `conn.getStatus()` RAISED        -> we looked and could not read it
#     * disconnected, never connected    -> we looked: no car. A MEASUREMENT.
#   Only the third is "OBD: off". The other two now carry their own reason, so a
#   driver in a running car whose adapter handle died is no longer told the car
#   is off, and the state file no longer collapses three different faults with
#   three different fixes into one word.
#
#   THE LOAD-BEARING PIN IS THE COMPOSED INVARIANT, not any single reason string:
#   a null `obdLink.state` ALWAYS travels with a non-null `source.obd.reason`,
#   and a non-null state NEVER carries one. Swept over every branch the producer
#   can reach. That biconditional is what actually closes the story's red line --
#   "a consumer cannot distinguish 'not written yet' from 'unknown' from 'the
#   emitter died'" -- because under it an absence is always self-describing and
#   a reading never wears an absence's clothes.
#
#   SECOND CAUSE OF THE STROBE, RECORDED NOT FIXED (conditionalOutcome 2 asked
#   for exactly this). The grey/yellow flicker does NOT need an omission to
#   explain it: `available` is `totalConnections > 0` on the `down` branch but
#   unconditionally True on the `reconnecting` branch, so a car that has NEVER
#   linked while the reconnect loop cycles CONNECTING -> DISCONNECTED publishes
#   neutral, amber, neutral, amber on successive samples -- the same physical
#   condition wearing two glyph colours. Measured at the foot of this file and
#   filed as I-us663.
#
#   🔴 THAT FINDING WAS FIXED BY US-672 ON 2026-09-03 and the two characterisation
#   tests at the foot of this file are RE-RECORDED, not deleted. Atlas ruled
#   (2026-09-02) that retry phase must not ride on `available`, AND that this
#   story's own "OBD: off is true for the never-connected branch" call was wrong:
#   `totalConnections == 0` is a fact about US, so the reason is now "never
#   connected". The full guard for the fixed behaviour is
#   tests/ui/test_carousel_obd_availability_holds_one_value.py.
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
# 2026-08-31    | Ralph (Rex)  | Initial -- US-663 typed-unknown OBD link + the
#               |              | availability-flap finding (I-us663).
# 2026-09-03    | Ralph (Rex)  | US-672: re-record the two I-us663
#               |              | characterisation tests (the flap is fixed) and
#               |              | the never-connected reason ("OBD: off" ->
#               |              | "never connected", Atlas's reversal of this
#               |              | file's own recorded call).
# ================================================================================
################################################################################

"""US-663 tests: the OBD link reports a typed unknown with a reason, never a guess."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import render_harness as rh  # noqa: E402

from pi.obdii.orchestrator.card_state_emitter import (  # noqa: E402
    REASON_OBD_LINK_NOT_READ,
    REASON_OBD_LINK_UNREADABLE,
    REASON_OBD_NEVER_CONNECTED,
    CardStateEmitterMixin,
)
from pi.splash.source_availability import REASON_OBD_OFF  # noqa: E402
from pi.splash.system_status_emitter import (  # noqa: E402
    OBD_DOWN,
    OBD_LINKED,
    OBD_RECONNECTING,
    SYSTEM_STATUS_FILENAME,
)

_NODE = shutil.which("node")

# The shipped panel, not the harness default.
PANEL = (480, 320)

_FRESH_SYNC = "2026-08-31T15:45:22Z"


# ---------------------------------------------------------------------------
# The REAL acquisition path. Every payload in this file is written to a real
# file by the real orchestrator emit tick -- no hand-written JSON anywhere, so a
# rename or a re-shape at ANY link fails here.
# ---------------------------------------------------------------------------


class _Orch(CardStateEmitterMixin):
    """The minimal composing object the mixin reads, as the orchestrator does.

    Mirrors tests/ui/test_carousel_obd_source_unavailable_render.py::_Orch and
    tests/pi/orchestrator/test_card_state_emitters.py::_FakeOrch. Every source
    OTHER than OBD is deliberately healthy, so anything unavailable that this
    file observes can only have come from the OBD link.
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
        self._cardPowerModeProvider = SimpleNamespace(getPowerMode=lambda: "car")
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = _FRESH_SYNC
        self._lastSyncRows = 1204


def _connectionStatus(**kwargs: Any) -> Any:
    base: dict[str, Any] = {
        "connected": False,
        "retryCount": 0,
        "totalConnections": 0,
        "state": "disconnected",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _raisingConnection() -> Any:
    """A connection whose own status cannot be read -- validationCriterion 2."""

    def _raise() -> Any:
        raise RuntimeError("adapter handle gone")

    return SimpleNamespace(getStatus=_raise)


def _connection(**status: Any) -> Any:
    return SimpleNamespace(getStatus=lambda: _connectionStatus(**status))


def _emit(tmp_path, connection: Any = None) -> dict:
    """Run the REAL orchestrator emit once and return what it wrote to disk."""
    statesDir = str(tmp_path / "states")
    orch = _Orch(statesDir, connection=connection)
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True, "the emitter wrote nothing"
    return json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )


# Every cause the shipped producer can reach, named. Keyed by cause so a failure
# names the FAULT rather than an index, and so the sweeps below cannot silently
# lose a branch when one is added.
def _allCauses() -> dict[str, Any]:
    return {
        "never_looked": None,
        "status_unreadable": _raisingConnection(),
        "never_connected": _connection(state="disconnected", totalConnections=0),
        "dropped_after_connecting": _connection(
            state="disconnected", retryCount=3, totalConnections=2
        ),
        # US-672 SPLIT THE OLD SINGLE `reconnecting` ROW IN TWO. It carried
        # `totalConnections=0` -- a car this Pi has NEVER reached -- and under
        # the availability rule of the day that row was the only thing exercising
        # the `reconnecting` TOKEN. Once availability stopped following the retry
        # phase that row became an ABSENCE, and the token would have quietly
        # dropped out of every sweep in this file. Both rows are named now, and
        # they differ in the one thing that decides availability.
        "reconnecting_never_linked": _connection(
            state="connecting", retryCount=1, totalConnections=0
        ),
        "reconnecting_seen_before": _connection(
            state="reconnecting", retryCount=1, totalConnections=2
        ),
        "linked": _connection(connected=True, state="connected", totalConnections=2),
    }


# ---------------------------------------------------------------------------
# Reading the rendered panel (only where the DRIVER's reading is the claim).
# ---------------------------------------------------------------------------


def _surface(payload: Any):
    tree = rh.runDashboard(routes={"/system-status": payload}, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _textOf(node: dict) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _obdTile(payload: Any) -> dict:
    """The OBD LINK tile as the operator sees it on the 480x320 panel."""
    surface = _surface(payload)
    path = None
    for candidate in surface.pathsByClass("tile"):
        for child in candidate[-1].get("children", []):
            if "OBD LINK" in _textOf({"children": [child]}):
                path = candidate
    assert path is not None, "no OBD LINK tile in the rendered DOM"
    assert surface.rendered(path), "the OBD LINK tile is in the DOM but not displayed"

    value = ""
    detail = ""
    for child in path[-1].get("children", []):
        classes = (child.get("attrs", {}).get("class") or "").split()
        if "tile-value" in classes:
            value = " ".join(_textOf(child))
        elif "tile-detail" in classes:
            detail = " ".join(_textOf(child))
    return {
        "value": value,
        "detail": detail,
        "level": path[-1].get("attrs", {}).get("data-level"),
    }


def _btGlyph(payload: Any) -> str:
    surface = _surface(payload)
    path = surface.pathById("glyph-bt")
    assert path is not None, "no #glyph-bt in the rendered DOM"
    assert surface.rendered(path), "#glyph-bt is in the DOM but not displayed"
    return path[-1].get("attrs", {}).get("data-state")


_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)


# ---------------------------------------------------------------------------
# END STATE, part 1 -- `obdLink` is present in EVERY emitted payload.
#
# RECORDED AS A PASS. This half of the story was already true; it had simply
# never been asserted as an invariant over the producer's whole branch set.
# ---------------------------------------------------------------------------


def test_obdLinkBlockIsPresentWithAStateKey_downEveryCauseTheProducerCanReach(tmp_path):
    """
    Given: every distinct cause `_gatherObdLinkState` can reach -- no connection
           object, an unreadable status, a never-connected car, a dropped link, a
           reconnect in flight, and a live link
    When: the REAL orchestrator emits system-status for each
    Then: `obdLink` is present in all of them, with all three of its keys.

          The story's END STATE, swept rather than spot-checked. Keyed by cause
          so a regression names the fault it broke, and so this sweep fails loudly
          if a branch is ever added without being considered here.
    """
    for cause, conn in _allCauses().items():
        payload = _emit(tmp_path / cause, connection=conn)
        assert "obdLink" in payload, cause
        block = payload["obdLink"]
        assert isinstance(block, dict), cause
        assert set(block) == {"state", "retries", "lastSeenS"}, (cause, block)


def test_sampledAt2HzForSixtySecondsWithTheLinkDown_obdLinkIsPresentInEverySample(
    tmp_path,
):
    """
    Given: a car that has never linked -- the state Atlas sampled at 15:50
    When: the producer emits 120 times, which is his 2 Hz x 60 s drill
    Then: `obdLink` is present in 100% of the samples.

          validationCriterion 1, run against the producer rather than the Pi.
          The count is asserted, not just "no exception": a producer that emitted
          115 good payloads and 5 without the block would pass a spot check and
          is exactly the intermittency the story reports.

          THE HONEST LIMIT, stated because this test cannot close the field
          report on its own: this exercises the EMITTER, not the Pi's disk. If
          the key really does go missing in the field, the cause is downstream of
          here (a partial/non-atomic write), which the story itself routes to a
          separate defect.
    """
    statesDir = str(tmp_path / "states")
    orch = _Orch(statesDir, connection=_connection(state="disconnected"))
    orch._initializeCardStateEmitters()
    target = tmp_path / "states" / SYSTEM_STATUS_FILENAME

    present = 0
    for _ in range(120):
        assert orch._maybeEmitCardStates() is True
        block = json.loads(target.read_text(encoding="utf-8")).get("obdLink")
        if isinstance(block, dict) and "state" in block:
            present += 1
    assert present == 120


def test_thereIsExactlyOneWriterOfTheSystemStatusFileInSrc():
    """
    Given: the story forbids adding a second acquisition path
    When: src/ is swept for anything that writes the system-status filename
    Then: only the emitter module names it.

          Swept rather than hand-grepped, because "the producer always emits" is
          only a guarantee about the FILE while one producer owns it -- a second
          writer would make every assertion in this file a statement about a race.
    """
    writers = set()
    for root, _dirs, files in os.walk(os.path.join(_REPO_ROOT, "src")):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            text = open(path, encoding="utf-8").read()  # noqa: SIM115
            # A writer is a module that BOTH names this file and writes a state
            # file. Each sibling emitter (dtc / battery-health / gear / ...)
            # writes its OWN slot through the same shared helper, so the write
            # call alone does not identify one; the conjunction does.
            namesTheSlot = re.search(
                r"SYSTEM_STATUS_FILENAME\s*=|=\s*[\"']system-status[\"']", text
            )
            writesAState = "writeStateAtomic(" in text
            if namesTheSlot and writesAState:
                writers.add(os.path.basename(path))
    assert writers == {"system_status_emitter.py"}, writers


# ---------------------------------------------------------------------------
# END STATE, part 2 -- THE NEGATIVE CASE. A typed unknown carries a reason, and
# the reason is a fact about what we know, never a guess about the car.
# ---------------------------------------------------------------------------


def test_beforeTheFirstObdReadOfABoot_theReasonSaysSo_andIsNotAClaimAboutTheCar(
    tmp_path,
):
    """
    Given: the orchestrator has no connection object yet -- the payload emitted
           before the first OBD read of a boot
    When: it emits
    Then: the absence is typed, carries its own reason, and that reason is NOT
          "OBD: off".

          validationCriterion 3. "OBD: off" says the car is off. At this instant
          nobody has looked at all, and the car may well be running.
    """
    payload = _emit(tmp_path, connection=None)
    assert payload["obdLink"]["state"] is None
    assert payload["source"]["obd"]["available"] is False
    assert payload["source"]["obd"]["reason"] == REASON_OBD_LINK_NOT_READ
    assert payload["source"]["obd"]["reason"] != REASON_OBD_OFF


def test_whenTheLinkStateReadFails_theReasonSaysWeCouldNotLook_notThatTheCarIsOff(
    tmp_path,
):
    """
    Given: `conn.getStatus()` RAISES -- the Pi cannot read its own connection
    When: it emits
    Then: the absence carries the unreadable reason, not the car-off reason.

          validationCriterion 2, and the sharpest form of "never guess a value":
          a driver sitting in a RUNNING car whose adapter handle died was being
          told the car was off. Two different faults, two different fixes, and
          the panel is where the operator picks which one to chase.
    """
    payload = _emit(tmp_path, connection=_raisingConnection())
    assert payload["obdLink"]["state"] is None
    assert payload["source"]["obd"]["available"] is False
    assert payload["source"]["obd"]["reason"] == REASON_OBD_LINK_UNREADABLE
    assert payload["source"]["obd"]["reason"] != REASON_OBD_OFF


def test_aCarThatWasLookedForAndNotFound_saysNeverConnected_notThatTheCarIsOff(
    tmp_path,
):
    """
    Given: a connection object reporting disconnected, never connected
    When: it emits
    Then: the reason is "never connected".

          🔴 RE-RECORDED BY US-672 (Atlas, 2026-09-02). THIS TEST USED TO ASSERT
          THE OPPOSITE, and the reversal is deliberate, not a relaxation.

          US-663 kept "OBD: off" here and called this branch "the one case where
          it is true -- we looked and there is no car". Atlas ruled that reading
          wrong: the branch is reached from `totalConnections == 0`, which is a
          fact about US, not a measurement of the car. *"That is an assertion
          about the world drawn from an absence of evidence about ourselves."*
          The CIO's key was in the ON position while this branch rendered
          "OBD: off" on the System Status card -- US-663's ORIGINAL defect,
          intact, inside US-663's own fix.

          The control this test provides SURVIVES the re-recording and is worth
          more than the word it used to pin: the branch still gets a word of its
          OWN. See the sibling test that the other two causes are untouched.
    """
    payload = _emit(tmp_path, connection=_connection(state="disconnected"))
    assert payload["source"]["obd"]["reason"] == REASON_OBD_NEVER_CONNECTED
    assert payload["source"]["obd"]["reason"] != REASON_OBD_OFF


def test_theDriversThreeWordsArePinnedAsLITERALS_notAsTheConstantsTheyComeFrom(
    tmp_path,
):
    """
    Given: the three causes that publish an absence
    When: each reason is compared against the literal text a driver reads
    Then: it matches, cause by cause.

          THE ONLY TEST IN THIS FILE THAT PINS THE WORDS THEMSELVES, and it is
          here because every other assertion imports the CONSTANTS and compares
          symbolically -- which cannot see a change to what the constants
          CONTAIN. Measured: swapping the two new constants' values left the
          entire suite, this file included, green. The producer and the tests
          moved together and the panel silently started telling a driver in a
          running car that nothing had looked at the link.

          So the mapping from cause to WORD is asserted once, literally. That
          makes this the file to edit when the wording is deliberately revised
          (an Iris call), and the file that fails when it is revised by accident.
    """
    causes = _allCauses()
    assert (
        _emit(tmp_path / "a", connection=causes["never_looked"])["source"]["obd"][
            "reason"
        ]
        == "not read yet"
    )
    assert (
        _emit(tmp_path / "b", connection=causes["status_unreadable"])["source"]["obd"][
            "reason"
        ]
        == "link unreadable"
    )
    # US-672 re-recorded this line from "OBD: off". See
    # test_aCarThatWasLookedForAndNotFound_saysNeverConnected_notThatTheCarIsOff
    # for Atlas's reasoning; this is the LITERAL half of it.
    assert (
        _emit(tmp_path / "c", connection=causes["never_connected"])["source"]["obd"][
            "reason"
        ]
        == "never connected"
    )


def test_theDistinctUnavailableCausesAreStillDistinguishableFromEachOther(tmp_path):
    """
    Given: every cause that reaches `available: false`
    When: all of them are emitted
    Then: there are FOUR such causes and THREE different words -- and the two
          that share a word are the two that share a CONDITION.

          This is the assertion I-us637 was filed against, inverted. Before that
          fix these payloads were byte-identical in the source block, so nobody
          reading the state file -- or the panel -- could tell "no car is plugged
          in" from "the Pi lost its own adapter handle" from "nothing has looked
          yet".

          US-672 RE-RECORDED THE COUNT, NOT THE CLAIM. A fourth cause joined the
          unavailable set -- `reconnecting_never_linked`, which used to publish
          available:true purely because an attempt happened to be in flight --
          and it deliberately shares `never_connected`'s word. That is the point:
          they are ONE condition observed at two instants of the retry cycle, and
          US-672 exists because they were being reported as two different facts.

          So the claim is now stated as a partition rather than a count: same
          condition -> same word, different fault -> different word. A count
          alone could not say which pair collapsed, and 3-of-4 would look like a
          regression of exactly the drift this test was built to catch.
    """
    reasons = {}
    for cause, conn in _allCauses().items():
        payload = _emit(tmp_path / cause, connection=conn)
        if payload["source"]["obd"]["available"] is False:
            reasons[cause] = payload["source"]["obd"]["reason"]

    assert set(reasons) == {
        "never_looked",
        "status_unreadable",
        "never_connected",
        "reconnecting_never_linked",
    }
    assert reasons["never_connected"] == reasons["reconnecting_never_linked"]
    assert len(set(reasons.values())) == 3, reasons


def test_everyUnavailableReasonIsNonEmptyAndCarriesNoPunctuationSentinel(tmp_path):
    """
    Given: each cause that publishes an absence
    When: its reason is read
    Then: it is a non-empty human string -- never "", never None, never a dash.

          `buildSourceState` falls back to the bare word "unavailable" for a
          reasonless absence, and `buildSystemStatusState` falls back to
          "OBD: off" before that. Both fallbacks are invisible when they fire, so
          this asserts the producer supplies a real reason of its OWN rather than
          riding a default -- the US-634 lesson (when a default is load-bearing,
          do not let the test be satisfied by it).
    """
    for cause, conn in _allCauses().items():
        payload = _emit(tmp_path / cause, connection=conn)
        source = payload["source"]["obd"]
        if source["available"] is False:
            assert isinstance(source["reason"], str) and source["reason"].strip(), cause
            assert source["reason"] not in {"unavailable", "-", "—", "NA"}, cause


# ---------------------------------------------------------------------------
# THE LOAD-BEARING PIN -- the biconditional. This is what actually closes the
# story's red line, and no single-payload assertion above can state it.
# ---------------------------------------------------------------------------


def test_aNullLinkStateAlwaysCarriesAReason_andARealLinkStateNeverDoes(tmp_path):
    """
    Given: every cause the producer can reach
    When: each emitted payload is read
    Then: `obdLink.state is None` if and only if `source.obd.reason` is set.

          BOTH DIRECTIONS, on purpose, because each half fails a different way.
          Forward: an absence with no reason is the story's defect -- a consumer
          cannot tell "unknown" from "not written yet" from "the emitter died".
          Reverse: a reason sitting beside a REAL state would let a live link
          render as an absence (US-637's override makes `source` win outright),
          so a producer that set the reason too eagerly would blank a working
          panel.

          Stated as one composed claim because either half alone is satisfiable
          the wrong way: always-null passes the forward half, always-reasonless
          passes the reverse.
    """
    for cause, conn in _allCauses().items():
        payload = _emit(tmp_path / cause, connection=conn)
        stateIsNull = payload["obdLink"]["state"] is None
        hasReason = payload["source"]["obd"]["reason"] is not None
        assert stateIsNull == hasReason, (cause, payload["obdLink"], payload["source"])


def test_theAcquisitionItselfWithholdsAReasonOnEveryAvailableBranch(tmp_path):
    """
    Given: `_gatherObdLinkState` directly, on every branch it can take
    When: the fourth element of the tuple is read
    Then: it is None exactly when the third element is True.

          THIS TEST EXISTS BECAUSE THE END-TO-END VERSION CANNOT SEE IT, and the
          reason is worth keeping: `buildSourceState` FORCES `reason` to None
          whenever `available` is True (source_availability.py:82), so a
          producer that published a reason beside a live link would have it
          silently discarded one layer down and every payload assertion in this
          file would still pass. Measured, not assumed -- mutating the LINKED and
          the available-DOWN branches to publish a reason left the whole
          end-to-end suite green.

          The same shape as US-639's M13: a layer that throws a value away makes
          the layer above's mistake invisible, so the guarantee has to be pinned
          where it is actually made. The discard downstream is correct and stays;
          this asserts the producer is not relying on it.
    """
    for cause, conn in _allCauses().items():
        _, _, available, reason = _Orch(
            str(tmp_path / cause), connection=conn
        )._gatherObdLinkState()
        assert (reason is None) == available, (cause, available, reason)


def test_bothSidesOfThatBiconditionalAreActuallyReached_soItIsNotVacuous(tmp_path):
    """
    Given: the same sweep
    When: the two sides are counted
    Then: both are non-empty.

          A biconditional over a sweep that only ever visits one side is true and
          worthless. This is the negative control for the test above.
    """
    nulls, reals = [], []
    for cause, conn in _allCauses().items():
        payload = _emit(tmp_path / cause, connection=conn)
        (nulls if payload["obdLink"]["state"] is None else reals).append(cause)
    assert nulls and reals, (nulls, reals)
    # US-672 re-recorded this set. `reconnecting_never_linked` moved from the
    # `reals` side to the `nulls` side -- a car we have never reached is an
    # ABSENT source at every instant of the retry cycle, not only between
    # attempts -- and `reconnecting_seen_before` was added so the RECONNECTING
    # token is still exercised by the sweeps in this file.
    assert set(reals) == {
        "dropped_after_connecting",
        "reconnecting_seen_before",
        "linked",
    }


def test_aRealLinkStateIsAlwaysOneOfTheThreePublishedTokens_neverAFreeString(tmp_path):
    """
    Given: every cause that publishes a non-null state
    When: the token is read
    Then: it is one of the emitter's own three constants.

          Pinned against the module's constants rather than string literals, so
          renaming a token in the producer fails here instead of silently
          shipping a word `carousel.js`'s `===` chain has no branch for -- which
          would render as `—`/unavailable and look exactly like this story's bug.
    """
    for cause, conn in _allCauses().items():
        state = _emit(tmp_path / cause, connection=conn)["obdLink"]["state"]
        if state is not None:
            assert state in {OBD_LINKED, OBD_RECONNECTING, OBD_DOWN}, (cause, state)


def test_theUnknownBranchesNeverPaintTheDownMeasurement(tmp_path):
    """
    Given: the two branches where the link state cannot be determined
    When: they emit
    Then: no `down` token survives into the payload.

          `_gatherObdLinkState` still hands `OBD_DOWN` back on both, and the
          emitter discards it because the source is unavailable. That discard is
          the only thing standing between "we could not look" and the panel
          printing "DOWN / no signal", so it is pinned rather than assumed: if a
          future change ever surfaces the tuple's first element on an unavailable
          source, this fails.
    """
    for cause in ("never_looked", "status_unreadable"):
        payload = _emit(tmp_path / cause, connection=_allCauses()[cause])
        assert payload["obdLink"]["state"] is None, cause
        assert payload["obdLink"]["retries"] == 0, cause
        assert payload["obdLink"]["lastSeenS"] is None, cause


# ---------------------------------------------------------------------------
# THE DRIVER'S READING. Everything above is the state file; the story's goal is
# what a person sees on a 3.5in panel.
# ---------------------------------------------------------------------------


@_needsNode
def test_theDriverReadsTheUnreadableReason_notThatTheCarIsOff(tmp_path):
    """
    Given: the Pi cannot read its own connection, in a running car
    When: the SHIPPED dashboard reads the file the REAL producer wrote
    Then: the OBD LINK tile prints the honest reason at the unavailable level.

          Acquisition -> producer -> state file -> renderer -> DOM in one
          assertion. `source.obd.reason` is rendered verbatim by `naTile`, so the
          producer's word IS the driver's word and there is no second vocabulary
          to drift.
    """
    payload = _emit(tmp_path, connection=_raisingConnection())
    tile = _obdTile(payload)
    assert tile["value"] == "NA", tile
    assert tile["detail"] == REASON_OBD_LINK_UNREADABLE, tile
    assert tile["detail"] != REASON_OBD_OFF, tile
    assert tile["level"] == "unavailable", tile


@_needsNode
def test_theDriverReadsTheNotReadYetReasonBeforeTheFirstObdReadOfABoot(tmp_path):
    """
    Given: the payload emitted before anything has looked at the link
    When: the panel renders it
    Then: the tile prints "not read yet"-class wording, not "OBD: off".
    """
    payload = _emit(tmp_path, connection=None)
    tile = _obdTile(payload)
    assert tile["detail"] == REASON_OBD_LINK_NOT_READ, tile
    assert tile["level"] == "unavailable", tile


@_needsNode
def test_aLiveCarStillPaintsTheLink_soTheAbsencesAboveAreNotUnconditional(tmp_path):
    """
    Given: a connected car
    When: the same chain runs
    Then: the panel paints LINKED at the ok level.

          The negative control for every absence assertion in this file. A
          producer that had simply been broken into always emitting an absence
          would pass all of them and fail here.
    """
    payload = _emit(tmp_path, connection=_allCauses()["linked"])
    tile = _obdTile(payload)
    assert tile["value"] == "LINKED", tile
    assert tile["level"] == "ok", tile


@_needsNode
def test_anUnreadableLinkGlyphIsNeutral_neverDown(tmp_path):
    """
    Given: the unreadable-status payload
    When: the BT glyph is read off the rendered panel
    Then: it is neutral.

          "We could not look" is not "no signal". The colour is unchanged by this
          story -- deliberately: the fix is to the WORD, and pinning the glyph
          here is what proves the word changed without the colour drifting with
          it.
    """
    assert _btGlyph(_emit(tmp_path, connection=_raisingConnection())) == "neutral"


# ---------------------------------------------------------------------------
# RE-RECORDED BY US-672. These two were CHARACTERISATION tests: they pinned the
# SECOND CAUSE of the strobe (I-us663) as behaviour that was WRONG, so that
# fixing it would fail here on purpose. It did, on 2026-09-03, and the new
# behaviour is recorded in place rather than the cases being deleted.
#
# The FULL guard for the fixed behaviour -- the CIO's 5.5-minute window, both
# forbidden cheap answers, and the never-connected/dropped distinguishability
# claim -- lives in tests/ui/test_carousel_obd_availability_holds_one_value.py.
# What these two keep is the BEFORE/AFTER pair on the exact two samples the
# finding was originally measured on, which is why they stay here beside the
# story that found it.
# ---------------------------------------------------------------------------


def test_oneUnlinkedCarNowPublishesONEAvailabilityAcrossTheRetryCycle(tmp_path):
    """
    Given: a car that has NEVER linked, with the reconnect loop running -- the
           connection cycles `connecting` -> `disconnected` between samples
    When: the two samples are emitted
    Then: the SAME physical condition publishes the SAME availability, and the
          same typed reason, at both instants.

          🔴 RE-RECORDED. This test previously asserted `available:true` then
          `available:false` on these two payloads, and that split was the
          finding: `available` was `totalConnections > 0` on the `down` branch
          but unconditionally True on the `reconnecting` branch, so nothing about
          the car changed between them -- only which instant of the retry cycle
          the 2 s emit tick happened to land on. It alone accounted for the
          grey/yellow flicker, with no omission required (I-us663 -> US-672).

          Both samples are now an ABSENT source carrying "never connected", which
          is the honest answer to "is the source absent" for a car this Pi has
          never reached. The link state is null on both, because the emitter
          blanks the block whenever the source is unavailable.
    """
    connecting = _emit(
        tmp_path / "connecting",
        connection=_connection(state="connecting", retryCount=1, totalConnections=0),
    )
    disconnected = _emit(
        tmp_path / "disconnected",
        connection=_connection(state="disconnected", retryCount=1, totalConnections=0),
    )
    assert connecting["source"]["obd"]["available"] is False
    assert disconnected["source"]["obd"]["available"] is False
    assert connecting["source"]["obd"]["reason"] == REASON_OBD_NEVER_CONNECTED
    assert disconnected["source"]["obd"]["reason"] == REASON_OBD_NEVER_CONNECTED
    assert connecting["obdLink"]["state"] is None
    assert disconnected["obdLink"]["state"] is None


@_needsNode
def test_thatFlapNoLongerReachesTheGlyph_bothSamplesReadNeutral(tmp_path):
    """
    Given: the two payloads above
    When: the SHIPPED panel renders each
    Then: the BT glyph reads neutral on BOTH.

          🔴 RE-RECORDED. This previously asserted amber then neutral -- the
          strobe, on the rendered panel, from the real producer.

          US-663 declined to fix it because choosing what an unlinked-but-
          retrying car should publish is a US-429 availability call, not a
          typed-unknown one. Atlas made that call on 2026-09-02: a car we have
          never spoken to is an ABSENT source, and neutral is the honest colour
          for it -- amber would be a claim about a measurement we have never
          taken (ARCH-007). A car we HAVE spoken to reads amber and keeps
          reading amber; that half is pinned in
          test_carousel_obd_availability_holds_one_value.py, and this test would
          otherwise be satisfiable by a producer pinned neutral for everything.
    """
    connecting = _emit(
        tmp_path / "connecting",
        connection=_connection(state="connecting", retryCount=1, totalConnections=0),
    )
    disconnected = _emit(
        tmp_path / "disconnected",
        connection=_connection(state="disconnected", retryCount=1, totalConnections=0),
    )
    assert _btGlyph(connecting) == "neutral"
    assert _btGlyph(disconnected) == "neutral"
