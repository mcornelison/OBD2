################################################################################
# File Name: test_card_last_drive_wiring.py
# Purpose/Description: US-505 tests that the real Pi-local last-drive fact
#   actually REACHES the system-status state file the idle card reads.
#
#   The two halves of this story were each individually correct and simply never
#   connected -- the exact failure shape that cost US-494 / US-499 / US-502 /
#   US-503, all of which stayed green through per-half tests.  So this suite
#   drives the REAL mixin against a REAL drive_summary table and reads the REAL
#   emitted state file.
#
#   It also pins the boot-order trap this sprint has now hit four times: the
#   card emitters are constructed in _initializeAllComponents while their
#   dependencies are built LATER, so anything captured at emitter-init time is
#   None for the life of the process -- with fully green unit tests.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Ralph (Rex)  | Initial -- US-505 last-drive wiring.
# ================================================================================
################################################################################

"""US-505: the real last-drive fact reaches the system-status state file."""

import json
import sqlite3
from contextlib import contextmanager

from pi.obdii.drive_summary import SCHEMA_DRIVE_SUMMARY
from pi.obdii.last_drive_summary import LAST_DRIVE_DATA_SOURCE
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin


class _FakeDatabase:
    """An in-memory drive_summary shaped exactly like the Pi's."""

    def __init__(self, drives=()):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute(SCHEMA_DRIVE_SUMMARY)
        for driveId, startedAt, dataSource in drives:
            self._conn.execute(
                "INSERT INTO drive_summary "
                "(drive_id, drive_start_timestamp, data_source) "
                "VALUES (?, ?, ?)",
                (driveId, startedAt, dataSource),
            )
        self._conn.commit()

    @contextmanager
    def connect(self):
        yield self._conn


def _realDrive(driveId, startedAt):
    return (driveId, startedAt, LAST_DRIVE_DATA_SOURCE)


class _FakeOrch(CardStateEmitterMixin):
    """Minimal composing object exposing the attrs the mixin reads."""

    def __init__(self, config, *, database=None, driveDetector=None):
        self._config = config
        self._connection = None
        self._driveDetector = driveDetector
        self._powerSourceProvider = None
        self._hardwareManager = None
        if database is not None:
            self._database = database
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = None
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0


def _config(tmp_path):
    return {
        "pi": {
            "splash": {"statesDir": str(tmp_path / "states")},
            "dashboard": {"stateEmitIntervalSeconds": 0.0},
        }
    }


def _emitAndRead(tmp_path, orch):
    orch._initializeCardStateEmitters()
    orch._maybeEmitCardStates()
    return json.loads(
        (tmp_path / "states" / "system-status").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# The real fact reaches the card.
# ---------------------------------------------------------------------------


def test_emit_carriesTheRealLastDriveFromDriveSummary(tmp_path):
    """The whole point of the story: a recorded drive exists Pi-locally, so the
    state file must carry it instead of the null that renders 'No recent
    drive'."""
    db = _FakeDatabase([_realDrive(35, "2026-08-02T09:15:00Z")])
    orch = _FakeOrch(_config(tmp_path), database=db)

    ss = _emitAndRead(tmp_path, orch)

    assert ss["drive"]["lastDrive"] == {
        "driveId": 35,
        "startedAtTs": "2026-08-02T09:15:00Z",
    }


def test_emit_noDrivesEverRecorded_lastDriveIsNull(tmp_path):
    """A genuinely fresh Pi keeps the honest absence -- the fix must not
    manufacture a drive to avoid an empty tile."""
    orch = _FakeOrch(_config(tmp_path), database=_FakeDatabase())

    ss = _emitAndRead(tmp_path, orch)

    assert ss["drive"]["lastDrive"] is None


def test_emit_noDatabaseAtAll_lastDriveIsNullAndEmitStillSucceeds(tmp_path):
    """On the bench there is no database attribute at all. The card must still
    emit -- a missing last drive can never take the whole status card down."""
    orch = _FakeOrch(_config(tmp_path))

    ss = _emitAndRead(tmp_path, orch)

    assert ss["drive"]["lastDrive"] is None
    assert ss["drive"]["state"] == "idle"


def test_emit_unreadableDatabase_lastDriveIsNullAndEmitStillSucceeds(tmp_path):
    """A locked / mid-migration DB degrades to the honest null rather than
    raising into the emit loop."""

    class _Exploding:
        @contextmanager
        def connect(self):
            raise sqlite3.OperationalError("database is locked")
            yield  # pragma: no cover

    orch = _FakeOrch(_config(tmp_path), database=_Exploding())

    ss = _emitAndRead(tmp_path, orch)

    assert ss["drive"]["lastDrive"] is None


def test_emit_databaseAttachedAfterEmitterInit_isStillRead(tmp_path):
    """BOOT-ORDER GUARD (US-501/502/503/504b all hit this shape).

    The emitters are constructed in _initializeAllComponents; their
    dependencies are built later in the boot order. A database reference
    captured at emitter-init time would be None for the entire life of the
    process -- a permanently empty tile with fully green unit tests. The read
    must be late-bound, at emit time.
    """
    orch = _FakeOrch(_config(tmp_path))
    orch._initializeCardStateEmitters()

    # ... only NOW does the database appear, exactly as the real boot order does.
    orch._database = _FakeDatabase([_realDrive(77, "2026-08-02T06:00:00Z")])
    orch._maybeEmitCardStates()

    ss = json.loads(
        (tmp_path / "states" / "system-status").read_text(encoding="utf-8")
    )
    assert ss["drive"]["lastDrive"]["driveId"] == 77


def test_emit_whileRecording_activeAndLastDriveAreDifferentFacts(tmp_path):
    """While a drive records, driveId is the ACTIVE drive and lastDrive is the
    previous one. Merging them would make the card contradict itself."""

    class _Driving:
        def isDriving(self):
            return True

    db = _FakeDatabase([_realDrive(35, "2026-08-02T09:15:00Z")])
    orch = _FakeOrch(_config(tmp_path), database=db, driveDetector=_Driving())

    ss = _emitAndRead(tmp_path, orch)

    assert ss["drive"]["state"] == "recording"
    assert ss["drive"]["lastDrive"]["driveId"] == 35


def test_emit_simulatedDriveOnly_lastDriveIsNull(tmp_path):
    """A bench physics_sim run is not the operator's last drive. Reporting it as
    one would be a fabrication in the only terms the panel has."""
    db = _FakeDatabase([(41, "2026-08-02T09:15:00Z", "physics_sim")])
    orch = _FakeOrch(_config(tmp_path), database=db)

    ss = _emitAndRead(tmp_path, orch)

    assert ss["drive"]["lastDrive"] is None


def test_emit_readsFreshEachTick_soANewDriveArrivesWithoutRestart(tmp_path):
    """The summary is re-read per emit, so a drive recorded while the
    orchestrator runs reaches the card without a service restart."""
    db = _FakeDatabase([_realDrive(35, "2026-08-02T09:15:00Z")])
    orch = _FakeOrch(_config(tmp_path), database=db)

    first = _emitAndRead(tmp_path, orch)
    assert first["drive"]["lastDrive"]["driveId"] == 35

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO drive_summary "
            "(drive_id, drive_start_timestamp, data_source) VALUES (?, ?, ?)",
            (36, "2026-08-02T11:30:00Z", LAST_DRIVE_DATA_SOURCE),
        )

    orch._lastCardStateEmitTime = None
    orch._maybeEmitCardStates()
    second = json.loads(
        (tmp_path / "states" / "system-status").read_text(encoding="utf-8")
    )
    assert second["drive"]["lastDrive"]["driveId"] == 36
