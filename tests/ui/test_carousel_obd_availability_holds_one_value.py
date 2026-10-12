################################################################################
# File Name: test_carousel_obd_availability_holds_one_value.py
# Purpose/Description: US-672 (F-138) -- `source.obd.available` must describe the
#   link's CONDITION, never the retry loop's instantaneous PHASE.
#
#   THE DEFECT, MEASURED 2026-09-01 by the CIO: 83 samples at 4 s over 5.5
#   minutes, on a PARKED car with the key OUT and nothing about the world
#   changing, produced 45 AMBER / 38 GREY in runs of AMBER 104 s -> GREY 152 s ->
#   AMBER 84 s. Two branches of `_gatherObdLinkState` describe the SAME condition
#   -- we have never connected -- and disagree about availability:
#     * mid-attempt   (`connecting`/`reconnecting`) -> available TRUE  -> amber
#     * between them  (`disconnected`)              -> available FALSE -> grey
#   The link is equally absent in both. This file is the fix's guard, and its
#   calibration half reproduces the split above so "no flips" cannot be what a
#   fixture that never flipped would also report.
#
#   ATLAS RULING 2026-09-02, both halves:
#     (1) Retry phase is a fact about OUR CLIENT, not about the car. US-429
#         defined `source.obd.available` as "is the source ABSENT", and that
#         answer must not change every 100 seconds. Availability is therefore
#         `totalConnections > 0` on EVERY not-connected branch.
#     (2) The REASON was wrong too, and this half was missed when US-663 shipped.
#         `REASON_OBD_OFF` -- "OBD: off" -- is a claim about the CAR, derived
#         from the fact that WE have never connected. With the key ON it is
#         simply false. The honest reason is "never connected".
#
#   THIS REVERSES A RECORDED US-663 DECISION, ON PURPOSE AND ON THE RECORD.
#   `test_aCarThatWasLookedForAndNotFound_stillSaysObdOff_soTheFixDidNotRelabelIt`
#   kept "OBD: off" for this branch as "the one case where it is true". Atlas
#   overruled that on 2026-09-02: the branch is reached from an absence of
#   evidence about OURSELVES, so it cannot license an assertion about the car.
#   That test is re-recorded in test_carousel_obd_link_typed_unknown.py rather
#   than deleted.
#
#   BOTH CHEAP WRONG ANSWERS ARE FORBIDDEN by the story and both are pinned
#   against here: pinning everything AMBER asserts an active failure against a
#   genuinely absent source (bench, no dongle), and pinning everything NEUTRAL
#   restores US-663's defect (a real car with a real dropped link reading as
#   "no source"). The load-bearing claim is therefore a DISTINGUISHABILITY one:
#   never-connected and dropped-after-connecting must land on DIFFERENT colours,
#   and each must hold its own colour across the whole retry cycle.
#
#   Skipped when node is not on PATH (a node-less CI box) -- but only the render
#   half. The availability sweep is producer-level and always runs.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-03    | Ralph (Rex)  | Initial -- US-672: availability describes the
#               |              | condition, and the reason stops claiming the
#               |              | car is off.
# ================================================================================
################################################################################

"""US-672 tests: OBD availability holds one value while the condition holds."""

from __future__ import annotations

import ast
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
    OBD_LINKED,
    SYSTEM_STATUS_FILENAME,
    buildSystemStatusState,
)

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default.
PANEL = (480, 320)

# The design tokens the shipped stylesheet resolves each glyph state to. Named
# after the driver's reading, never asserted as a colour name -- resolved through
# the real cascade by `_btGlyph`.
GREEN = "var(--green-ok)"
AMBER = "var(--amber-warn)"
NEUTRAL = "var(--text-secondary)"

_FRESH_SYNC = "2026-09-01T15:45:22Z"

_CAROUSEL_JS = os.path.join(_REPO_ROOT, "src", "pi", "ui", "dashboard", "carousel.js")
_CARD_STATE_EMITTER = os.path.join(
    _REPO_ROOT, "src", "pi", "obdii", "orchestrator", "card_state_emitter.py"
)
_SRC = os.path.join(_REPO_ROOT, "src")


# ---------------------------------------------------------------------------
# The REAL acquisition path. Every payload in this file is written to a real file
# by the real orchestrator emit tick -- no hand-written JSON anywhere.
# Mirrors tests/ui/test_carousel_obd_link_typed_unknown.py::_Orch.
# ---------------------------------------------------------------------------


class _Orch(CardStateEmitterMixin):
    """The minimal composing object the mixin reads, as the orchestrator does.

    Every source OTHER than OBD is deliberately healthy, so anything unavailable
    this file observes can only have come from the OBD link.
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


def _connection(**status: Any) -> Any:
    return SimpleNamespace(getStatus=lambda: _connectionStatus(**status))


def _raisingConnection() -> Any:
    def _raise() -> Any:
        raise RuntimeError("adapter handle gone")

    return SimpleNamespace(getStatus=_raise)


def _emit(tmp_path, connection: Any = None) -> dict:
    """Run the REAL orchestrator emit once and return what it wrote to disk."""
    statesDir = str(tmp_path / "states")
    orch = _Orch(statesDir, connection=connection)
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True, "the emitter wrote nothing"
    return json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )


# Every cause the shipped producer can reach. Keyed by CAUSE so a failure names
# the fault, and so the sweeps cannot silently lose a branch when one is added.
# The two `reconnecting_*` and the two never/dropped rows differ ONLY in whether
# this Pi has ever spoken to the car -- the axis this story is about.
def _allCauses() -> dict[str, Any]:
    return {
        "never_looked": None,
        "status_unreadable": _raisingConnection(),
        "never_connected": _connection(state="disconnected", totalConnections=0),
        "reconnecting_never_linked": _connection(
            state="connecting", retryCount=1, totalConnections=0
        ),
        "dropped_after_connecting": _connection(
            state="disconnected", retryCount=3, totalConnections=2
        ),
        "reconnecting_seen_before": _connection(
            state="reconnecting", retryCount=1, totalConnections=2
        ),
        "linked": _connection(connected=True, state="connected", totalConnections=2),
    }


# ---------------------------------------------------------------------------
# THE CIO'S 2026-09-01 WINDOW, as a fixture. 4 s sampling, runs of
# AMBER 104 s -> GREY 152 s -> AMBER 84 s on a parked car with the key OUT.
#
# THE TWO HALVES OF HIS REPORT DIFFER BY TWO SAMPLES AND THAT IS RECORDED, NOT
# RECONCILED AWAY: "83 samples ... 45 AMBER / 38 GREY" sums to 83, while the run
# lengths at 4 s give 26 + 38 + 21 = 85 samples and 47 amber. The GREY run is 152
# s = 38 samples on both accounts. The two amber runs are the ones the
# observation window clips -- a run seen as 104 s may have started before
# sampling began -- so the fixture is built from the RUN LENGTHS (the physical
# claim) and the calibration asserts grey EXACTLY and amber over the band both
# accounts span. Picking one number and hiding the other would have been the
# fabrication.
# ---------------------------------------------------------------------------

_SAMPLE_INTERVAL_S = 4
_RUNS_S = (("connecting", 104), ("disconnected", 152), ("connecting", 84))


def _cioWindow() -> list[str]:
    """The connection-state token at each 4 s sample of the measured window."""
    samples: list[str] = []
    for stateToken, seconds in _RUNS_S:
        samples.extend([stateToken] * (seconds // _SAMPLE_INTERVAL_S))
    return samples


def _legacyObdAvailable(stateToken: str, totalConnections: int) -> bool:
    """The availability rule AS IT STOOD at d81e2b67, restated for calibration.

    ``card_state_emitter.py:570-574`` before this story::

        if "reconnect" in stateStr or "connecting" in stateStr:
            return (OBD_RECONNECTING, retries, True, None)
        available = totalConns > 0

    RESTATED, WHICH IS A RISK, SO IT IS MADE LOAD-BEARING: the calibration test
    below asserts this reproduces the CIO's own measured split. A restatement
    that had drifted from the removed code would fail there rather than quietly
    certify the fix against a rule nobody ever ran.
    """
    if "reconnect" in stateToken or "connecting" in stateToken:
        return True
    return totalConnections > 0


# ---------------------------------------------------------------------------
# Reading the rendered panel.
# ---------------------------------------------------------------------------


def _surface(payload: Any):
    tree = rh.runDashboard(routes={"/system-status": payload}, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _btGlyph(payload: Any) -> tuple[str, str]:
    """The BT glyph as the driver sees it -> (data-state, resolved colour).

    The COLOUR travels with the token because the shipped vocabulary has FOUR
    tokens for THREE colours -- `down` and `amber` both resolve to
    ``--amber-warn`` (dashboard.css:251/257, the deliberate US-488 call "a DOWN
    link is DEGRADED, not dangerous"). An assertion on tokens alone would call a
    stable colour unstable, and that distinction is load-bearing in this file.
    """
    surface = _surface(payload)
    path = surface.pathById("glyph-bt")
    assert path is not None, "no #glyph-bt in the rendered DOM"
    assert surface.rendered(path), "#glyph-bt is in the DOM but not displayed"
    declaration = surface.winningDeclaration(path, "color")
    return (
        path[-1].get("attrs", {}).get("data-state"),
        declaration[0] if declaration else "",
    )


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
    return {"value": value, "detail": detail}


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS FIRST. Most of this file is stability-shaped ("holds one
# value"), and every such assertion passes vacuously if the fixture never varies
# or the harness reads nothing at all.
# ---------------------------------------------------------------------------


def test_theCalibrationFixtureReproducesTheCIOsMeasuredSplit():
    """
    Given: the 2026-09-01 window -- AMBER 104 s / GREY 152 s / AMBER 84 s at 4 s
    When: the REMOVED availability rule is run over it
    Then: it reproduces the measured split: 38 grey exactly, amber in [45, 47],
          and exactly TWO flips (three runs).

          THE CONTROL THIS WHOLE FILE RESTS ON. "available never flips" is also
          what a fixture that never varied would report, so the fixture is first
          shown to have CONTAINED the defect. Same shape as US-645's flip-count
          calibration and US-673's 30-minute control.

          The [45, 47] band is the story's own two accounts, both kept -- see the
          fixture comment above. Narrowing it to one number would be inventing a
          precision the measurement does not have.
    """
    window = _cioWindow()
    flags = [_legacyObdAvailable(token, 0) for token in window]

    grey = flags.count(False)
    amber = flags.count(True)
    flips = sum(1 for a, b in zip(flags, flags[1:]) if a != b)

    assert grey == 38, (grey, amber)
    assert 45 <= amber <= 47, (grey, amber)
    assert flips == 2, flips


@_needsNode
def test_theHarnessActuallyReadsTheBtGlyphAndTheTile_negativeControl(tmp_path):
    """
    Given: every "holds one colour" assertion below fails open if the glyph is
           unreadable
    When: an unmistakably LINKED car is rendered
    Then: the harness reads a real state, a real colour and a real tile.
    """
    payload = _emit(tmp_path, _allCauses()["linked"])
    state, colour = _btGlyph(payload)
    assert state == "ok", f"harness read no glyph state: {state!r}"
    assert colour == GREEN, f"harness read no glyph colour: {colour!r}"
    assert _obdTile(payload)["value"] == "LINKED"


# ---------------------------------------------------------------------------
# validationCriterion 1 -- the END STATE. One condition, one availability, for
# the whole window.
# ---------------------------------------------------------------------------


def test_acrossTheFullMeasuredWindow_availabilityHoldsExactlyOneValue(tmp_path):
    """
    Given: the CIO's 2026-09-01 window replayed against the REAL producer -- a
           car this Pi has never connected to, the retry loop cycling
           connecting -> disconnected, and NOTHING about the car changing
    When: every sample is emitted through the real orchestrator emit tick
    Then: `source.obd.available` is the SAME value at every one of them.

          validationCriterion 1, stated as the criterion states it: the test
          fails if ANY flip occurs. Today this window returns 45/38 across three
          runs; that split IS the defect.
    """
    flags = []
    for index, stateToken in enumerate(_cioWindow()):
        payload = _emit(
            tmp_path / f"s{index:03d}",
            connection=_connection(
                state=stateToken, retryCount=index % 6, totalConnections=0
            ),
        )
        flags.append(payload["source"]["obd"]["available"])

    assert len(flags) == 85, len(flags)
    assert len(set(flags)) == 1, {
        "flips": sum(1 for a, b in zip(flags, flags[1:]) if a != b),
        "true": flags.count(True),
        "false": flags.count(False),
    }
    # And it is the honest value: a car we have never spoken to is an ABSENT
    # source. Pinned so "one value" cannot be satisfied by pinning it True.
    assert flags[0] is False


def test_theReasonAlsoHoldsOneValueAcrossTheWindow_notJustTheBoolean(tmp_path):
    """
    Given: the same window
    When: the typed-NA reason is read at every sample
    Then: it is the same word throughout, and it is "never connected".

          The boolean holding still is not enough. A driver reads the WORD, and a
          reason that alternated between two spellings of one condition would
          strobe the tile's detail line while `available` sat perfectly still --
          the same defect one field over.
    """
    reasons = set()
    for index, stateToken in enumerate(_cioWindow()[:20]):
        payload = _emit(
            tmp_path / f"r{index:03d}",
            connection=_connection(state=stateToken, totalConnections=0),
        )
        reasons.add(payload["source"]["obd"]["reason"])
    assert reasons == {REASON_OBD_NEVER_CONNECTED}, reasons


def test_availabilityIsAFunctionOfHavingEverConnected_andOfNothingElse(tmp_path):
    """
    Given: every connection-state token the adapter can hold, at each of the two
           values of "have we ever connected"
    When: each is emitted
    Then: availability tracks `totalConnections > 0` and NOTHING else.

          THE INVARIANT IN ITS GENERAL FORM, and the one that survives a new
          state token being added to `ConnectionState` later. The story's
          symptom is one instance of it; asserting only the instance would let
          the next token re-open the defect. `connected` is excluded because a
          connected link is available by definition and cannot have
          totalConnections == 0.
    """
    tokens = ("disconnected", "connecting", "reconnecting", "error")
    for token in tokens:
        for totalConns in (0, 2):
            payload = _emit(
                tmp_path / f"{token}-{totalConns}",
                connection=_connection(state=token, totalConnections=totalConns),
            )
            assert payload["source"]["obd"]["available"] is (totalConns > 0), (
                token,
                totalConns,
                payload["source"]["obd"],
            )


def test_theRetryPhaseIsNotAnInputToAvailability_readAtTheAcquisition(tmp_path):
    """
    Given: `_gatherObdLinkState` directly, holding the condition fixed and moving
           ONLY the retry phase
    When: the third element of the tuple is read
    Then: it does not move.

          Asserted at the ACQUISITION as well as end-to-end because that is where
          the rule lives, and because Atlas's ruling is about this function's
          contract: "retry phase is a fact about OUR CLIENT, not about the car".
          Both values of the condition are swept, so a producer pinned to one
          answer fails here.
    """
    for totalConns in (0, 2):
        seen = set()
        for token in ("disconnected", "connecting", "reconnecting", "error"):
            _, _, available, _ = _Orch(
                str(tmp_path / f"acq-{token}-{totalConns}"),
                connection=_connection(state=token, totalConnections=totalConns),
            )._gatherObdLinkState()
            seen.add(available)
        assert seen == {totalConns > 0}, (totalConns, seen)


# ---------------------------------------------------------------------------
# validationCriterion 2 -- the card never claims the CAR is off on the strength
# of a retry-cycle gap. Atlas's second half.
# ---------------------------------------------------------------------------


def test_noBranchTheProducerCanReachEverPublishesTheStringObdOff(tmp_path):
    """
    Given: every cause the shipped producer can reach
    When: each emitted payload is searched for the literal "OBD: off"
    Then: it appears nowhere in any of them.

          validationCriterion 2 as an EXECUTABLE PREDICATE over the whole
          payload, not an assertion about one field: a grep returning zero. The
          string is a claim about the CAR, and every route to it was reached from
          an absence of evidence about US. Searching the serialised payload
          rather than `source.obd.reason` means a future field that re-introduced
          the word anywhere fails here too.
    """
    for cause, conn in _allCauses().items():
        blob = json.dumps(_emit(tmp_path / cause, connection=conn))
        assert REASON_OBD_OFF not in blob, (cause, blob)


def test_theCarOffClaimHasNoProducerLeftAnywhereInSrc():
    """
    Given: `REASON_OBD_OFF` is still DEFINED (specs/ssot-design-pattern.md cites
           it by name, and specs are read-only to this office)
    When: src/ is parsed and swept for every CODE reference to the symbol
    Then: the only file that references it is the one that defines it.

          THE PREDICATE THAT KEEPS THE FIX FROM DECAYING. The constant is
          retained deliberately -- it is the FORBIDDEN word, and the `!=`
          controls in test_carousel_obd_link_typed_unknown.py are worth more
          against a real symbol than against a literal. But a retained constant
          with no producer is exactly the shape that gets quietly re-adopted, so
          "no producer" is asserted rather than assumed.

          SWEPT THROUGH `ast`, NOT THROUGH A GREP, and the difference is not
          cosmetic: this file's history is written in comments that NAME the
          constant to explain why it is not used, and a line-wise grep counts
          those as producers. It read three "uses" on the first run, two of them
          prose. That is US-667's lesson recurring -- an assertion about what
          code DOES must not be satisfiable, or defeated, by what a comment SAYS.
    """
    uses = []
    for root, _dirs, files in os.walk(_SRC):
        if "__pycache__" in root:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
            for node in ast.walk(tree):
                referenced = (
                    isinstance(node, ast.Name) and node.id == "REASON_OBD_OFF"
                ) or (
                    isinstance(node, ast.alias) and node.name == "REASON_OBD_OFF"
                ) or (
                    isinstance(node, ast.Constant) and node.value == "REASON_OBD_OFF"
                )
                if referenced:
                    rel = os.path.relpath(path, _REPO_ROOT).replace("\\", "/")
                    uses.append((rel, getattr(node, "lineno", 0)))

    files = {use[0] for use in uses}
    assert files == {"src/pi/splash/source_availability.py"}, uses
    # Its own definition, plus its `__all__` entry. A third is a new producer.
    assert len(uses) == 2, uses


@_needsNode
def test_theDriverReadsNeverConnected_notThatTheCarIsOff(tmp_path):
    """
    Given: a car this Pi has never connected to, with the key ON
    When: the SHIPPED dashboard renders what the REAL producer wrote
    Then: the OBD LINK tile prints "never connected" and never "OBD: off".

          The driver's half of validationCriterion 2. `naTile` renders
          `source.obd.reason` VERBATIM, so the producer's word IS the driver's
          word -- which is why the claim is worth reading off the panel rather
          than off the state file.
    """
    payload = _emit(tmp_path, connection=_connection(state="disconnected"))
    tile = _obdTile(payload)
    assert tile["value"] == "NA", tile
    assert tile["detail"] == REASON_OBD_NEVER_CONNECTED, tile
    assert tile["detail"] != REASON_OBD_OFF, tile


def test_theNewWordIsPinnedAsALITERAL_notAsTheConstantItComesFrom(tmp_path):
    """
    Given: the branch Atlas re-worded
    When: its reason is compared against the text a driver actually reads
    Then: it is "never connected".

          US-663's lesson, re-applied: every other assertion here imports the
          CONSTANT and compares symbolically, which cannot see a change to what
          the constant CONTAINS. Measured there: swapping two constants' values
          left the whole suite green while the panel started lying. So the word
          is pinned once, literally, and this is the file to edit when it is
          deliberately revised (an Iris call).
    """
    payload = _emit(tmp_path, connection=_connection(state="disconnected"))
    assert payload["source"]["obd"]["reason"] == "never connected"


def test_theOtherTwoAbsenceWordsAreUntouched_soThisWasNotABlanketRelabel(tmp_path):
    """
    Given: the two causes US-663 gave their own words
    When: they are emitted after this story's change
    Then: they still say exactly what US-663 made them say.

          The control that keeps this story from becoming a rename. US-663's
          whole finding was "one word for three causes"; a fix that gave all four
          causes a NEW single word would satisfy every assertion above and
          destroy the distinction that story bought.
    """
    causes = _allCauses()
    assert (
        _emit(tmp_path / "nl", connection=causes["never_looked"])["source"]["obd"][
            "reason"
        ]
        == REASON_OBD_LINK_NOT_READ
    )
    assert (
        _emit(tmp_path / "su", connection=causes["status_unreadable"])["source"]["obd"][
            "reason"
        ]
        == REASON_OBD_LINK_UNREADABLE
    )


def test_theFourUnavailableCausesStillCarryThreeDistinctWords(tmp_path):
    """
    Given: every cause that now reaches `available: false`
    When: their reasons are collected
    Then: FOUR causes, THREE words -- and the two that share a word are the two
          that share a CONDITION.

          The precise shape the fix should have. `never_connected` and
          `reconnecting_never_linked` are the same fact about the world observed
          at two instants of the retry cycle, so they MUST read alike; the other
          two are different faults with different fixes, so they must not. A
          count alone would not say which pairs collapsed.
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
    }, reasons
    assert reasons["never_connected"] == reasons["reconnecting_never_linked"]
    assert len(set(reasons.values())) == 3, reasons


# ---------------------------------------------------------------------------
# validationCriteria 3 and 4 -- BOTH cheap wrong answers are forbidden, and the
# proof is that the two conditions land on DIFFERENT colours.
# ---------------------------------------------------------------------------


@_needsNode
def test_aGenuinelyAbsentSourceIsNeutralAndStaysNeutralThroughTheRetryCycle(tmp_path):
    """
    Given: a bench with no dongle paired -- nothing has ever connected
    When: the glyph is read at BOTH instants of the retry cycle
    Then: it is NEUTRAL at both.

          validationCriterion 3, and the half that proves the fix did not simply
          pin everything to amber. Read at both instants on purpose: a
          single-sample assertion is exactly what let the flap ship.
    """
    midAttempt = _emit(
        tmp_path / "mid",
        connection=_connection(state="connecting", retryCount=1, totalConnections=0),
    )
    between = _emit(
        tmp_path / "between",
        connection=_connection(state="disconnected", retryCount=1, totalConnections=0),
    )
    assert _btGlyph(midAttempt) == ("neutral", NEUTRAL)
    assert _btGlyph(between) == ("neutral", NEUTRAL)


@_needsNode
def test_aRealCarWithADroppedLinkIsAmberAndStaysAmberThroughTheRetryCycle(tmp_path):
    """
    Given: a car this Pi HAS connected to, whose link has dropped and is retrying
    When: the glyph is read at both instants of the retry cycle
    Then: the COLOUR is amber at both.

          validationCriterion 4, and the half that proves the fix did not pin
          everything to neutral and restore US-663's defect.

          THE CLAIM IS ON THE COLOUR, NOT THE TOKEN, and here that distinction
          does real work: the token genuinely differs across the cycle
          (`reconnecting` mid-attempt, `down` between) because `obdLink.state`
          still carries the retry PHASE -- which is where Atlas said a "trying
          now" fact may live, as long as it does not ride on `available`. The
          driver sees one colour because dashboard.css paints both with
          `--amber-warn`. That coincidence is load-bearing for this story, so it
          is asserted rather than relied upon: see the test below.
    """
    midAttempt = _emit(
        tmp_path / "mid",
        connection=_connection(state="reconnecting", retryCount=1, totalConnections=2),
    )
    between = _emit(
        tmp_path / "between",
        connection=_connection(state="disconnected", retryCount=3, totalConnections=2),
    )
    assert _btGlyph(midAttempt)[1] == AMBER
    assert _btGlyph(between)[1] == AMBER


@_needsNode
def test_bothAvailableNotConnectedTokensResolveToOneColour_soThePhaseCannotStrobe(
    tmp_path,
):
    """
    Given: the two link-state tokens an AVAILABLE-but-not-connected link can
           publish across the retry cycle
    When: each is resolved through the SHIPPED stylesheet
    Then: they land on the SAME colour.

          THE PIN THAT MAKES THE PREVIOUS TEST HONEST. `obdLink.state` is left
          carrying the retry phase deliberately -- the OBD LINK tile's
          "RECONNECTING / retry 3" is a diagnostic a driver goes looking for, and
          deleting it would cost US-658's three-state vocabulary its `down`
          token. That is only safe while `down` and `amber` share a hue
          (dashboard.css:251/257, US-488: "a DOWN link is DEGRADED, not
          dangerous"). Give `down` its own colour and validationCriterion 4
          re-opens for every previously-connected car -- so that change fails
          HERE, with this docstring attached, instead of shipping as a fresh
          strobe nobody connected to this story.
    """
    midAttempt = _emit(
        tmp_path / "mid",
        connection=_connection(state="reconnecting", totalConnections=2),
    )
    between = _emit(
        tmp_path / "between",
        connection=_connection(state="disconnected", totalConnections=2),
    )
    assert midAttempt["obdLink"]["state"] == "reconnecting"
    assert between["obdLink"]["state"] == "down"
    assert _btGlyph(midAttempt)[0] != _btGlyph(between)[0], "the tokens must differ"
    assert _btGlyph(midAttempt)[1] == _btGlyph(between)[1]


@_needsNode
def test_theTwoConditionsAreDistinguishable_soNeitherCheapAnswerWasTaken(tmp_path):
    """
    Given: a never-connected link and a dropped-after-connecting link, each read
           at BOTH instants of the retry cycle
    When: all four glyphs are compared
    Then: the two CONDITIONS differ in colour, and neither condition varies
          across the cycle.

          THE LOAD-BEARING CLAIM OF THE STORY, stated as one composed assertion
          because either half alone is satisfiable the wrong way: pinning
          everything neutral gives perfect stability and destroys the
          distinction, and so does pinning everything amber. Stability AND
          distinguishability, or the fix is one of the two answers the story
          forbids by name.
    """
    never = [
        _btGlyph(
            _emit(
                tmp_path / f"never-{token}",
                connection=_connection(state=token, totalConnections=0),
            )
        )
        for token in ("connecting", "disconnected")
    ]
    dropped = [
        _btGlyph(
            _emit(
                tmp_path / f"dropped-{token}",
                connection=_connection(state=token, totalConnections=2),
            )
        )[1]
        for token in ("reconnecting", "disconnected")
    ]

    assert len({colour for _, colour in never}) == 1, never
    assert len(set(dropped)) == 1, dropped
    assert never[0][1] != dropped[0], (never, dropped)


# ---------------------------------------------------------------------------
# The producer is the fix, not the renderer.
# ---------------------------------------------------------------------------


def test_theFixIsInTheProducer_theGlyphStillReadsTheStateItIsGiven():
    """
    Given: the story forbids debouncing the GLYPH -- `system-status` is read by
           more than the glyph, and smoothing it at the renderer leaves every
           other consumer reading a value that flips
    When: `btGlyphState` is read out of the shipped carousel.js
    Then: it is still a pure `===` chain over `o.state` -- no timers, no history,
          no previous-value memory.

          An executable form of "fix the producer". A debounce would need STATE,
          and the names below are how state enters this function.

          CASE-INSENSITIVE, and that is not fussiness: the mutation that proved
          this test needed writing held its memory in `_btPrevState`, which a
          case-SENSITIVE search for "prev" walks straight past. It was killed by
          the behavioural tests above, so the guard was never load-bearing on its
          own -- but a static check that a capital letter defeats is worse than
          no static check, because it reads like one.
    """
    source = open(_CAROUSEL_JS, encoding="utf-8").read()
    start = source.index("function btGlyphState(")
    body = source[start : source.index("\n  function ", start + 1)].lower()
    for smell in ("settimeout", "setinterval", "date.now", "last", "prev", "cache"):
        assert smell not in body, (smell, body)


def test_anAbsenceWithNoSuppliedReasonIsNotGivenTheCarOffClaimOnItsBehalf():
    """
    Given: `buildSystemStatusState` called with `obdAvailable=False` and NO
           `obdUnavailableReason` -- the shape a caller that forgot, or a future
           caller that has no reason to give, produces
    When: the OBD source block is read
    Then: the reason is the bare honest "unavailable", NEVER "OBD: off".

          WHY THIS CANNOT BE WRITTEN END-TO-END, WHICH IS THE WHOLE POINT OF IT
          BEING HERE. The splash emitter used to read
          `obdUnavailableReason or REASON_OBD_OFF`, so an unexplained absence had
          a claim about the CAR filled in for it invisibly. That `or` is now
          gone. But the SHIPPED producer supplies a real reason on every branch
          it can reach, so no payload the orchestrator can emit ever reaches the
          fallback -- restoring the `or` leaves every other test in this file,
          and the whole tests/pi/splash suite, GREEN. MEASURED: mutation M5 of
          this story's battery survived 6/7 until this test was written.

          That is US-639's M13 lesson recurring almost word for word: A FIXTURE
          THAT HANDS A PRODUCER NOTHING TO THROW AWAY CANNOT WITNESS THE THROWING
          AWAY. Here the producer is handed no absence to explain, so the
          explaining-on-its-behalf is invisible through the chain. The only
          witness is a direct call, so this test deliberately does NOT go through
          `_emit`, and must not be "simplified" into the chain later.

          `buildSystemStatusState` is a PUBLIC builder with callers beyond the
          orchestrator, so this is a live contract and not a hypothetical.
    """
    state = buildSystemStatusState(
        obdLinkState=OBD_LINKED,
        obdRetries=0,
        obdLastSeenS=None,
        syncLastOkTs=_FRESH_SYNC,
        syncRows=10,
        syncPending=0,
        syncStale=False,
        powerSource="external",
        driveState="idle",
        driveId=None,
        nowIso=_FRESH_SYNC,
        obdAvailable=False,
        # obdUnavailableReason deliberately NOT supplied.
    )
    assert state["source"]["obd"]["available"] is False
    assert state["source"]["obd"]["reason"] != REASON_OBD_OFF, state["source"]["obd"]
    assert state["source"]["obd"]["reason"] == "unavailable", state["source"]["obd"]


def test_aSuppliedCarOffReasonIsStillHonoured_soThisWasNotABlanketBan():
    """
    Given: a caller that genuinely KNOWS the car is off and says so explicitly
    When: it supplies `REASON_OBD_OFF` itself
    Then: it travels through unchanged.

          The control on the test above. US-672 removes the INVISIBLE DEFAULT --
          a claim inserted on a caller's behalf -- not the word itself. "OBD: off"
          remains true and sayable when something actually established it, and
          `tests/pi/splash/test_system_status_emitter.py` has a caller that does.
          Without this control, "never emit OBD: off" would be satisfied by
          deleting the constant's last legitimate use as well.
    """
    state = buildSystemStatusState(
        obdLinkState=OBD_LINKED,
        obdRetries=0,
        obdLastSeenS=None,
        syncLastOkTs=_FRESH_SYNC,
        syncRows=10,
        syncPending=0,
        syncStale=False,
        powerSource="external",
        driveState="idle",
        driveId=None,
        nowIso=_FRESH_SYNC,
        obdAvailable=False,
        obdUnavailableReason=REASON_OBD_OFF,
    )
    assert state["source"]["obd"]["reason"] == REASON_OBD_OFF


def test_theAvailabilityRuleIsDecidedInExactlyOnePlace():
    """
    Given: rule B -- read once, publish, subscribe
    When: `card_state_emitter.py` is swept for reads of `totalConnections`
    Then: there is exactly one.

          The defect was TWO branches answering one question and disagreeing. A
          second read of the deciding fact is how that comes back, and it would
          come back silently: both copies would be individually correct on the
          day they were written.
    """
    source = open(_CARD_STATE_EMITTER, encoding="utf-8").read()
    reads = re.findall(r'"totalConnections"', source)
    assert len(reads) == 1, f"totalConnections is read {len(reads)} times, expected 1"
