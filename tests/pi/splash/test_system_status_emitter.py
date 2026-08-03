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
        # US-505 `lastDrive` is ALWAYS a key (null when unknown) -- see the
        # always-present catalog below for why absence is the dangerous shape.
        "drive": {"state": "recording", "driveId": 27, "lastDrive": None},
        # US-480-a idle-SSOT (b): recording -> never idle (a drive is active).
        "idle": False,
        "source": {"obd": {"available": True, "reason": None}},
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
    # A verbatim `down` link is still an AVAILABLE source (we are talking to /
    # retrying a car) -- distinct from US-429 obd-unavailable (no car at all).
    assert state["source"]["obd"] == {"available": True, "reason": None}
    # US-480-a idle-SSOT (b): the OBD source is AVAILABLE (a car we are retrying),
    # so this is NOT the calm parked/asleep state -- idle stays False even though
    # the drive is idle. Idle requires the OBD source to be ABSENT.
    assert state["idle"] is False


# ---------------------------------------------------------------------------
# US-505 `drive.lastDrive` -- the ALWAYS-PRESENT key (I-041 / US-528).
# ---------------------------------------------------------------------------


def test_buildSystemStatusState_lastDriveKey_isPresentInEveryShape():
    """Given every call shape the emitter supports (arg omitted, explicit None,
    a real summary, and idle-with-no-history),
    When buildSystemStatusState assembles the payload,
    Then `drive.lastDrive` is ALWAYS a key -- null when unknown, never absent.

    This is the assertion I-041 was missing. An exact-shape equality check
    proves the key exists for ONE call shape; a renderer breaks on the shape
    where it goes missing. A sometimes-absent key is the failure mode US-505
    designed against: `undefined` silently falls through to the wrong branch,
    whereas an explicit null is a value the display can test against.
    """
    baseKwargs = {
        "obdLinkState": OBD_LINKED,
        "obdRetries": 0,
        "obdLastSeenS": 1,
        "syncLastOkTs": _SYNC_OK,
        "syncRows": 1,
        "syncPending": 0,
        "syncStale": False,
        "powerMode": "car",
        "powerSource": "external",
        "nowIso": _NOW,
    }
    shapes = {
        # The kwarg omitted entirely -- the production default path.
        "omitted": dict(baseKwargs, driveState="recording", driveId=27),
        # Explicitly None -- a caller that has no drive on record.
        "explicitNone": dict(
            baseKwargs, driveState="recording", driveId=27, lastDrive=None
        ),
        # A real US-505 summary while a NEW drive is already recording.
        "populated": dict(
            baseKwargs,
            driveState="recording",
            driveId=28,
            lastDrive={"driveId": 27, "startedAtTs": _SYNC_OK},
        ),
        # Parked with nothing on record -- the coldest branch.
        "idleNoHistory": dict(baseKwargs, driveState="idle", driveId=None),
    }

    for shapeName, kwargs in shapes.items():
        drive = buildSystemStatusState(**kwargs)["drive"]
        assert "lastDrive" in drive, f"lastDrive key vanished in shape: {shapeName}"


def test_buildSystemStatusState_lastDrive_isVerbatimAndDistinctFromDriveId():
    """Given a parked Pi (idle, no active drive) that HAS a completed drive,
    When the payload is assembled,
    Then lastDrive is transported verbatim and driveId stays null.

    `lastDrive` (last COMPLETED drive) and `driveId` (the ACTIVE drive) are
    different facts. Merging them would make a parked Pi read as recording,
    so this pins the separation as well as the no-reformat contract -- the
    emitter transports the producer's fact, it never re-derives it.
    """
    summary = {"driveId": 27, "startedAtTs": _SYNC_OK}
    state = buildSystemStatusState(
        obdLinkState=OBD_DOWN,
        obdRetries=0,
        obdLastSeenS=None,
        syncLastOkTs=_SYNC_OK,
        syncRows=0,
        syncPending=0,
        syncStale=False,
        powerMode="car",
        powerSource="battery",
        driveState="idle",
        driveId=None,
        nowIso=_NOW,
        lastDrive=summary,
    )

    assert state["drive"]["lastDrive"] == summary  # verbatim, not reformatted
    assert state["drive"]["driveId"] is None  # a completed drive is NOT active
    assert state["drive"]["state"] == "idle"


# ---------------------------------------------------------------------------
# US-429 honest-availability -- the OBD source governs the obdLink tile.
# ---------------------------------------------------------------------------


def test_buildSystemStatusState_obdUnavailable_typedNaNotStaleLink():
    """US-429: on wall power / car off the OBD source is unavailable -> the
    obdLink value is a FRESH typed NULL (never a stale/fabricated link state) and
    the typed reason travels in source.obd. Sync/power/drive stay independent."""
    state = buildSystemStatusState(
        obdLinkState=OBD_LINKED,  # a stale caller value must NOT leak through
        obdRetries=5,
        obdLastSeenS=3,
        syncLastOkTs=_SYNC_OK,
        syncRows=10,
        syncPending=0,
        syncStale=False,
        powerMode="wall",
        powerSource="external",
        driveState="idle",
        driveId=None,
        nowIso=_NOW,
        obdAvailable=False,
        obdUnavailableReason="OBD: off",
    )
    assert state["obdLink"] == {"state": None, "retries": 0, "lastSeenS": None}
    assert state["source"]["obd"] == {"available": False, "reason": "OBD: off"}
    # Other sources are unaffected (one truth per SOURCE).
    assert state["sync"]["rows"] == 10
    assert state["power"]["mode"] == "wall"
    # US-480-a idle-SSOT (b): OBD source ABSENT + not recording -> this IS the
    # calm parked/asleep state -> idle True (US-481 renders the idle home card).
    assert state["idle"] is True


# ---------------------------------------------------------------------------
# US-480-a idle-SSOT (b) -- the emitter OWNS the idle decision (Atlas ruling).
# ---------------------------------------------------------------------------


def test_buildSystemStatusState_idle_trueOnlyWhenObdAbsentAndNotRecording():
    """idle == parked-and-asleep: OBD source ABSENT (no car) AND no drive
    recording. The emitter owns both inputs so the display never re-derives it."""
    state = buildSystemStatusState(
        obdLinkState=OBD_DOWN,
        obdRetries=0,
        obdLastSeenS=None,
        syncLastOkTs=None,
        syncRows=0,
        syncPending=0,
        syncStale=False,
        powerMode="wall",
        powerSource="external",
        driveState="idle",
        driveId=None,
        nowIso=_NOW,
        obdAvailable=False,
    )
    assert state["idle"] is True


def test_buildSystemStatusState_idle_falseWhenObdAvailable():
    """OBD source present (car awake) -> NOT idle, even with no drive recording
    (Iris AC-4: idle flips false the moment the OBD source wakes)."""
    state = buildSystemStatusState(
        obdLinkState=OBD_LINKED,
        obdRetries=0,
        obdLastSeenS=1,
        syncLastOkTs=_SYNC_OK,
        syncRows=0,
        syncPending=0,
        syncStale=False,
        powerMode="car",
        powerSource="external",
        driveState="idle",
        driveId=None,
        nowIso=_NOW,
        obdAvailable=True,
    )
    assert state["idle"] is False


def test_buildSystemStatusState_idle_falseWhileRecording():
    """A recording drive -> NOT idle even if the OBD source were reported absent
    (Iris AC-4: idle flips false the moment a drive records). Belt-and-suspenders
    on the driveState half of the SSOT."""
    state = buildSystemStatusState(
        obdLinkState=OBD_LINKED,
        obdRetries=0,
        obdLastSeenS=1,
        syncLastOkTs=_SYNC_OK,
        syncRows=5,
        syncPending=0,
        syncStale=False,
        powerMode="car",
        powerSource="external",
        driveState="recording",
        driveId=42,
        nowIso=_NOW,
        obdAvailable=False,
    )
    assert state["idle"] is False


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
    assert written["drive"] == {
        "state": "recording",
        "driveId": 27,
        "lastDrive": None,  # US-505: always a key, even when the caller omits it
    }
    assert written["ts"] == _NOW


def test_emitter_forwardsLastDrive_verbatimThroughTheJsonRoundTrip(tmp_path):
    """Given a caller that supplies a real US-505 last-drive summary,
    When the emit callable fires,
    Then the written JSON carries it verbatim under drive.lastDrive.

    This is the OTHER half of the always-present contract and it cannot be
    proved at the builder. `emit` has its own `lastDrive=None` default, so if
    the emit->build forwarding were dropped the builder default would still
    supply the KEY and every presence assertion above would stay green while
    the real value silently never reached the display. Only a populated value
    observed on the far side of the file write pins the wiring.
    """
    statesDir = str(tmp_path / "states")
    summary = {"driveId": 27, "startedAtTs": _SYNC_OK}
    emit = makeSystemStatusEmitter(
        statesDir, syncStaleThresholdS=60, nowIsoFn=lambda: _NOW
    )

    emit(
        obdLinkState=OBD_LINKED,
        obdRetries=0,
        obdLastSeenS=1,
        syncLastOkTs=_SYNC_OK,
        syncRows=10,
        syncPending=0,
        powerMode="car",
        powerSource="external",
        driveState="idle",
        driveId=None,
        lastDrive=summary,
    )

    written = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )
    assert written["drive"]["lastDrive"] == summary
    assert written["drive"]["driveId"] is None


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
