################################################################################
# File Name: test_shutdown_state_emitter.py
# Purpose/Description: Tests for the F-103 shutdown-state emitter (US-394). The
#   shutdown-state schema builder is pure; the phase-emit factory is best-effort
#   (write failures are logged, never raised -- spec §6 / Atlas A-2 constraint c
#   "write failures logged but never block shutdown progress"). Covers the
#   pinned schema shape, atomic write, the same-origin states-dir provisioning,
#   and the never-raise guarantee.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Ralph (Rex)  | Initial implementation (US-394 F-103 shutdown splash)
# 2026-10-23    | Rex (US-883-a) | The payload gains step (null for grace).
# 2026-10-23    | Rex (US-883-b) | The payload gains sync (null until a drain pass).
# 2026-10-25    | Rex (US-883-c) | sync carries state + outcome; the docstring
#               |                | names what sync null means.
# ================================================================================
################################################################################

"""Tests for ``pi.splash.shutdown_state_emitter``."""

import json
import os

from pi.splash.shutdown_state_emitter import (
    DEFAULT_REASON,
    PHASE_CANCELLED,
    PHASE_FLUSHING,
    PHASE_GRACE,
    PHASE_POWERING_OFF,
    SHUTDOWN_STATE_FILENAME,
    VALID_PHASES,
    buildShutdownState,
    makeShutdownPhaseEmitter,
)

_GRACE_START = "2026-06-29T19:50:00Z"
_NOW = "2026-06-29T19:50:02Z"


def test_buildShutdownState_pinnedSchema_hasExactKeys():
    """Given the pinned Atlas A-2 schema fields,
    When buildShutdownState assembles the payload,
    Then it emits exactly the spec §6 keys with the supplied values."""
    state = buildShutdownState(
        PHASE_GRACE,
        tGraceStartedAtIso=_GRACE_START,
        tGraceTotalS=7.0,
        tRemainingS=5.0,
        reason=DEFAULT_REASON,
        nowIso=_NOW,
    )
    assert state == {
        "phase": "grace",
        "tGraceStartedAt": _GRACE_START,
        "tGraceTotalS": 7.0,
        "tRemainingS": 5.0,
        "reason": "ignition_off",
        "ts": _NOW,
        "step": None,
        "sync": None,
    }


def test_buildShutdownState_carriesTheSyncProgress():
    """
    Given: sync progress {waitingAtKeyOff, confirmed} from the acked marks (US-883-b)
    When:  the payload is built
    Then:  it carries a copy of that sync beside the step
    """
    sync = {"waitingAtKeyOff": 400, "confirmed": 250}
    state = buildShutdownState(
        PHASE_FLUSHING,
        tGraceStartedAtIso=_GRACE_START,
        tGraceTotalS=7.0,
        tRemainingS=0.0,
        reason=DEFAULT_REASON,
        nowIso=_NOW,
        step={"index": 2, "of": 5, "name": "drain"},
        sync=sync,
    )
    assert state["sync"] == {"waitingAtKeyOff": 400, "confirmed": 250}
    assert state["sync"] is not sync


def test_emitter_writesTheSync(tmp_path):
    """The emit callable writes the sync it is handed; without one, sync is null."""
    emit = makeShutdownPhaseEmitter(str(tmp_path), nowIsoFn=lambda: _NOW)
    target = tmp_path / SHUTDOWN_STATE_FILENAME

    emit(PHASE_FLUSHING, tGraceStartedAtIso=_GRACE_START, tGraceTotalS=7.0,
         tRemainingS=0.0, reason=DEFAULT_REASON)
    assert json.loads(target.read_text(encoding="utf-8"))["sync"] is None

    emit(PHASE_FLUSHING, tGraceStartedAtIso=_GRACE_START, tGraceTotalS=7.0,
         tRemainingS=0.0, reason=DEFAULT_REASON,
         sync={"waitingAtKeyOff": 5, "confirmed": 3})
    assert json.loads(target.read_text(encoding="utf-8"))["sync"] == {
        "waitingAtKeyOff": 5, "confirmed": 3,
    }


def test_buildShutdownState_carriesTheCeremonyStep():
    """
    Given: a step {index, of, name} from the sequencer (US-883-a)
    When:  the payload is built
    Then:  it carries that step as given, beside the unchanged spec §6 keys
    """
    step = {"index": 2, "of": 5, "name": "drain"}
    state = buildShutdownState(
        PHASE_FLUSHING,
        tGraceStartedAtIso=_GRACE_START,
        tGraceTotalS=7.0,
        tRemainingS=0.0,
        reason=DEFAULT_REASON,
        nowIso=_NOW,
        step=step,
    )
    assert state["phase"] == "flushing"
    assert state["step"] == {"index": 2, "of": 5, "name": "drain"}
    assert state["step"] is not step


def test_emitter_writesTheStep(tmp_path):
    """The emit callable writes the step it is handed; grace writes step null."""
    emit = makeShutdownPhaseEmitter(str(tmp_path), nowIsoFn=lambda: _NOW)
    target = tmp_path / SHUTDOWN_STATE_FILENAME

    emit(PHASE_GRACE, tGraceStartedAtIso=_GRACE_START, tGraceTotalS=7.0,
         tRemainingS=7.0, reason=DEFAULT_REASON)
    assert json.loads(target.read_text(encoding="utf-8"))["step"] is None

    emit(PHASE_FLUSHING, tGraceStartedAtIso=_GRACE_START, tGraceTotalS=7.0,
         tRemainingS=0.0, reason=DEFAULT_REASON,
         step={"index": 1, "of": 3, "name": "shed"})
    assert json.loads(target.read_text(encoding="utf-8"))["step"] == {
        "index": 1, "of": 3, "name": "shed",
    }


def test_phaseConstants_areTheFourPinnedTransitions():
    """The four phase constants are exactly the sequencer code-path transitions
    pinned in the spec enum (grace/cancelled/flushing/powering_off)."""
    assert VALID_PHASES == {
        PHASE_GRACE,
        PHASE_CANCELLED,
        PHASE_FLUSHING,
        PHASE_POWERING_OFF,
    }
    assert PHASE_GRACE == "grace"
    assert PHASE_CANCELLED == "cancelled"
    assert PHASE_FLUSHING == "flushing"
    assert PHASE_POWERING_OFF == "powering_off"


def test_emitter_writesShutdownStateFile_atomically(tmp_path):
    """Given a states dir,
    When the phase-emit callable fires,
    Then it writes states/shutdown-state with the full payload (and provisions
    the dir if absent -- C-5 ensureStatesDir)."""
    statesDir = str(tmp_path / "states")  # does NOT exist yet
    emit = makeShutdownPhaseEmitter(statesDir, nowIsoFn=lambda: _NOW)

    emit(
        PHASE_GRACE,
        tGraceStartedAtIso=_GRACE_START,
        tGraceTotalS=7.0,
        tRemainingS=7.0,
        reason=DEFAULT_REASON,
    )

    written = json.loads(
        (tmp_path / "states" / SHUTDOWN_STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert written["phase"] == "grace"
    assert written["tGraceStartedAt"] == _GRACE_START
    assert written["tGraceTotalS"] == 7.0
    assert written["reason"] == "ignition_off"
    assert written["ts"] == _NOW


def test_emitter_overwritesOnPhaseTransition(tmp_path):
    """The shutdown-state file is a single SSOT slot -- a later phase overwrites
    the earlier one (splash polls the same file at 250ms)."""
    statesDir = str(tmp_path)
    emit = makeShutdownPhaseEmitter(statesDir, nowIsoFn=lambda: _NOW)

    emit(
        PHASE_GRACE,
        tGraceStartedAtIso=_GRACE_START,
        tGraceTotalS=7.0,
        tRemainingS=7.0,
        reason=DEFAULT_REASON,
    )
    emit(
        PHASE_POWERING_OFF,
        tGraceStartedAtIso=_GRACE_START,
        tGraceTotalS=7.0,
        tRemainingS=0.0,
        reason=DEFAULT_REASON,
    )

    written = json.loads(
        (tmp_path / SHUTDOWN_STATE_FILENAME).read_text(encoding="utf-8")
    )
    assert written["phase"] == "powering_off"
    assert written["tRemainingS"] == 0.0


def test_emitter_neverRaises_onWriteFailure(tmp_path):
    """Atlas A-2 constraint (c): a write failure is logged but NEVER raised --
    the emit hook must never block the shutdown state machine. Point the emitter
    at an un-creatable path (a file masquerading as the parent dir) and assert
    no exception escapes."""
    # Create a regular FILE where the states dir's parent should be a dir, so
    # mkdir(parents=True) raises NotADirectoryError inside the emitter.
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    statesDir = str(blocker / "states")  # parent is a file -> mkdir fails
    emit = makeShutdownPhaseEmitter(statesDir, nowIsoFn=lambda: _NOW)

    # Must not raise.
    emit(
        PHASE_GRACE,
        tGraceStartedAtIso=_GRACE_START,
        tGraceTotalS=7.0,
        tRemainingS=7.0,
        reason=DEFAULT_REASON,
    )
    assert not os.path.exists(statesDir)


def test_emitter_writesSyncStateAndOutcome(tmp_path):
    """US-883-c: sync.state / sync.outcome reach the file as handed in."""
    emit = makeShutdownPhaseEmitter(str(tmp_path), nowIsoFn=lambda: _NOW)
    target = tmp_path / SHUTDOWN_STATE_FILENAME
    sync = {"state": "ended", "outcome": "stalled", "waitingAtKeyOff": 400, "confirmed": 250}

    emit(PHASE_FLUSHING, tGraceStartedAtIso=_GRACE_START, tGraceTotalS=7.0,
         tRemainingS=0.0, reason=DEFAULT_REASON, sync=sync)

    assert json.loads(target.read_text(encoding="utf-8"))["sync"] == sync


def test_buildShutdownState_docstring_namesWhatSyncNullMeans():
    """Rule 10 in the code: sync null means only not-started or the fast path."""
    doc = buildShutdownState.__doc__ or ""
    assert "has not started" in doc and "fast path" in doc
