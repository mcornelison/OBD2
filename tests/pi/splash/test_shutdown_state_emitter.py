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
