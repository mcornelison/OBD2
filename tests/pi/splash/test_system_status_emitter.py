################################################################################
# File Name: test_system_status_emitter.py
# Purpose/Description: Tests for the F-092 system-status emitter (US-400). The
#   system-status schema builder is pure (Atlas A-3 shape); the emit factory is
#   best-effort (write failures logged, never raised -- same contract as the
#   F-103 emitters). Covers: the A-3 schema shape, honest-instrument
#   serialization (a down/reconnecting link is reported verbatim, never a
#   fabricated `linked`), the stale-while-driving policy (I-033 / I-4), atomic
#   write + states-dir provisioning, and the never-raise guarantee.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial implementation (US-400 system-status card)
# ================================================================================
################################################################################

"""Tests for ``pi.splash.system_status_emitter``."""

import json
import os

from pi.splash.system_status_emitter import (
    OBD_DOWN,
    OBD_LINKED,
    OBD_RECONNECTING,
    SYSTEM_STATUS_FILENAME,
    buildSystemStatusState,
    isSyncStaleWhileDriving,
    makeSystemStatusEmitter,
)

_NOW = "2026-06-30T19:42:00Z"
_SYNC_OK = "2026-06-30T19:40:00Z"  # 120s before _NOW


# ---------------------------------------------------------------------------
# buildSystemStatusState -- the pure A-3 schema builder.
# ---------------------------------------------------------------------------


def test_buildSystemStatusState_a3Schema_hasExactShape():
    """Given the Atlas A-3 fields,
    When buildSystemStatusState assembles the payload,
    Then it emits exactly the A-3 nested shape with the supplied values."""
    state = buildSystemStatusState(
        obdLinkState=OBD_RECONNECTING,
        obdRetries=3,
        obdLastSeenS=14,
        syncLastOkTs=_SYNC_OK,
        syncRows=1204,
        syncPending=0,
        syncStale=False,
        powerMode="car",
        powerSource="external",
        driveState="recording",
        driveId=27,
        nowIso=_NOW,
    )
    assert state == {
        "obdLink": {"state": "reconnecting", "retries": 3, "lastSeenS": 14},
        "sync": {"lastOkTs": _SYNC_OK, "rows": 1204, "pending": 0, "stale": False},
        "power": {"mode": "car", "source": "external"},
        "drive": {"state": "recording", "driveId": 27},
        "ts": _NOW,
    }


def test_buildSystemStatusState_honestInstrument_downLinkIsVerbatim():
    """A down link with no last-seen is serialized faithfully (state='down',
    lastSeenS=None) -- the emitter never fabricates a 'linked' state."""
    state = buildSystemStatusState(
        obdLinkState=OBD_DOWN,
        obdRetries=0,
        obdLastSeenS=None,
        syncLastOkTs=None,
        syncRows=0,
        syncPending=12,
        syncStale=True,
        powerMode="car",
        powerSource="battery",
        driveState="idle",
        driveId=None,
        nowIso=_NOW,
    )
    assert state["obdLink"] == {"state": "down", "retries": 0, "lastSeenS": None}
    assert state["obdLink"]["state"] != OBD_LINKED
    assert state["sync"]["lastOkTs"] is None
    assert state["drive"]["driveId"] is None


# ---------------------------------------------------------------------------
# isSyncStaleWhileDriving -- the stale-while-driving policy (I-4 / I-033).
# ---------------------------------------------------------------------------


def test_isSyncStaleWhileDriving_recordingAndOldSync_isStale():
    """Recording with a last-sync older than the threshold -> stale (amber)."""
    assert (
        isSyncStaleWhileDriving(
            "recording", _SYNC_OK, _NOW, thresholdS=60
        )
        is True
    )


def test_isSyncStaleWhileDriving_recordingAndFreshSync_isNotStale():
    """Recording with a last-sync inside the threshold -> not stale."""
    assert (
        isSyncStaleWhileDriving(
            "recording", _SYNC_OK, _NOW, thresholdS=600
        )
        is False
    )


def test_isSyncStaleWhileDriving_idle_isNeverStale():
    """Parked/idle -> never flagged stale (parked syncs catch up; the flag is
    'stale-WHILE-DRIVING' only)."""
    assert (
        isSyncStaleWhileDriving("idle", _SYNC_OK, _NOW, thresholdS=1)
        is False
    )


def test_isSyncStaleWhileDriving_recordingNeverSynced_isStale():
    """Recording with no successful sync yet -> stale (data at risk, honest)."""
    assert (
        isSyncStaleWhileDriving("recording", None, _NOW, thresholdS=60)
        is True
    )


def test_isSyncStaleWhileDriving_unparseableTimestamp_isStale():
    """An unparseable last-sync while driving -> stale (never claim fresh when we
    cannot prove freshness -- no green-when-broken)."""
    assert (
        isSyncStaleWhileDriving("recording", "not-a-date", _NOW, thresholdS=60)
        is True
    )


# ---------------------------------------------------------------------------
# makeSystemStatusEmitter -- best-effort atomic writer (A-3 ownership).
# ---------------------------------------------------------------------------


def test_emitter_writesSystemStatusFile_andComputesStale(tmp_path):
    """Given a states dir,
    When the emit callable fires while recording with an old sync,
    Then it writes states/system-status with the A-3 payload and the policy
    computes sync.stale=True (provisioning the dir if absent -- C-5)."""
    statesDir = str(tmp_path / "states")  # does NOT exist yet
    emit = makeSystemStatusEmitter(
        statesDir, syncStaleThresholdS=60, nowIsoFn=lambda: _NOW
    )

    emit(
        obdLinkState=OBD_RECONNECTING,
        obdRetries=2,
        obdLastSeenS=8,
        syncLastOkTs=_SYNC_OK,
        syncRows=10,
        syncPending=4,
        powerMode="car",
        powerSource="external",
        driveState="recording",
        driveId=27,
    )

    written = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )
    assert written["obdLink"] == {"state": "reconnecting", "retries": 2, "lastSeenS": 8}
    assert written["sync"]["pending"] == 4
    assert written["sync"]["stale"] is True  # recording + 120s-old sync > 60s
    assert written["drive"] == {"state": "recording", "driveId": 27}
    assert written["ts"] == _NOW


def test_emitter_neverRaises_onWriteFailure(tmp_path):
    """Best-effort: a write failure is logged but NEVER raised -- the emit hook
    must never block the orchestrator. Point it at an un-creatable path."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    statesDir = str(blocker / "states")  # parent is a file -> mkdir fails
    emit = makeSystemStatusEmitter(
        statesDir, syncStaleThresholdS=60, nowIsoFn=lambda: _NOW
    )

    # Must not raise.
    emit(
        obdLinkState=OBD_LINKED,
        obdRetries=0,
        obdLastSeenS=1,
        syncLastOkTs=_SYNC_OK,
        syncRows=1,
        syncPending=0,
        powerMode="car",
        powerSource="external",
        driveState="idle",
        driveId=None,
    )
    assert not os.path.exists(statesDir)
