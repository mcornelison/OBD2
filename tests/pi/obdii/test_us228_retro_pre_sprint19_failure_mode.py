################################################################################
# File Name: test_us228_retro_pre_sprint19_failure_mode.py
# Purpose/Description: US-261 retroactive integration test that closes the
#                      Sprint 18 US-228 silent-NULL-metadata failure loop.
#                      Sprint 18's US-228 shipped Option (b) backfill-UPDATE
#                      passes:true but produced all-NULL metadata across
#                      drives 3, 4, and 5 because the UPDATE-backfill code
#                      path was unwired -- the INSERT at drive_start fired
#                      with empty snapshot (sensor readings hadn't arrived
#                      yet) and nothing ever filled the row afterward.  This
#                      test parameterizes over the 3 documented drive
#                      trajectories, simulates the pre-Sprint-19 INSERT-
#                      immediately recorder via a tightly-scoped stub, and
#                      asserts:
#                      (a) pre-Sprint-19 path produces an all-NULL drive_summary
#                          row that never gets backfilled;
#                      (b) post-Sprint-19 (US-236) defer-INSERT path produces
#                          a drive_summary row with at least one non-NULL
#                          sensor field on every trajectory.
#                      Per US-261 stopConditions, no git-checkout of historical
#                      code -- the failure mode is reproduced via mock injection.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex (US-261) | Initial -- 3 drive trajectories from Spool
#                              | drive-grade notes + groundingRef "Drives
#                              | 3/4/5 each had drive_summary metadata
#                              | all-NULL despite Sprint 18 US-228 ship".
# ================================================================================
################################################################################

"""US-261 retroactive integration test for the US-228 cold-start NULL bug.

Failure mode this test would have caught (Sprint 18, 3 production drives)
-------------------------------------------------------------------------
US-228 (Sprint 18) shipped Option (b) -- INSERT at drive_start with
whatever's cached, then UPDATE-backfill missing columns as later
readings arrive.  The INSERT path worked: every drive produced a
drive_summary row.  The UPDATE-backfill path was empirically unwired:

============  ===================  =========  =============  =========
Drive         Mode                 Duration   fromState      Final row
============  ===================  =========  =============  =========
3 (04-23)    real-OBD cold-start   9:30       UNKNOWN        (NULL,NULL,NULL)
4 (04-29)    real-OBD warm-idle    10:47      RUNNING        (NULL,NULL,NULL)
5 (04-29)    real-OBD cold-start   17:39      UNKNOWN        (NULL,NULL,NULL)
============  ===================  =========  =============  =========

Across 3 drives spanning 38 minutes of real-OBD wall time, every
drive_summary row landed with ``ambient_temp_at_start_c``,
``starting_battery_v``, and ``barometric_kpa_at_start`` all NULL.
Drives 4 and 5 ran AFTER US-228 deployed -- the backfill UPDATE had
the entire drive duration to fire and never did.

Sprint 19 US-236 fixed the bug class by switching to Option (a)
defer-INSERT: the recorder no longer INSERTs at drive_start when the
snapshot has no relevant sensor data.  The detector keeps re-calling
on each tick; the FIRST call where IAT / BATTERY_V / BAROMETRIC_KPA
appears triggers the INSERT with that field non-NULL.  The bug class
("INSERT then never fill") is eliminated by construction -- the row
only appears once at least one column will be non-NULL.

Discriminator design (per feedback_runtime_validation_required.md)
------------------------------------------------------------------
Each trajectory feeds the SAME drive-start + sensor-arrival sequence
to two parallel recorders:

* :class:`_PreSprint19InsertImmediatelyRecorder` -- a tightly-scoped
  stub that mirrors the Sprint-18 Option (b) decision logic: INSERT
  at drive_start with whatever's available (typically nothing), then
  rely on a backfill-UPDATE that never fires.  The stub deliberately
  models the unwired-backfill failure mode: subsequent sensor reads
  do NOT update the row, exactly matching production behavior.
* :class:`SummaryRecorder` -- the real Sprint-19 production code.
  Asserts the row gets at least one non-NULL field once the first
  sensor reading arrives.

Why a stub instead of git-checkout
-----------------------------------
Per US-261 stopCondition #1: "If reproducing pre-Sprint-19
trajectories requires git-checkout of historical code -- STOP,
simulate via mock injection."  The stub class is the mock-injection
alternative: a deliberately minimal model of the failure mode (INSERT
with empty snapshot, never UPDATE).  It is not a re-export of the
historical code -- it is a documented reproduction of the BUG CLASS
such that future agents reading this test can see the failure
without checking out historical commits.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive_summary import (
    DRIVE_SUMMARY_TABLE,
    SummaryRecorder,
    buildSummaryFromSnapshot,
)
from src.pi.obdii.engine_state import EngineState

# ================================================================================
# Drive trajectory test data
# ================================================================================


@dataclass(frozen=True)
class _SensorArrival:
    """One sensor reading arriving at a documented offset post drive_start."""

    paramName: str          # 'INTAKE_TEMP' / 'BATTERY_V' / 'BAROMETRIC_KPA'
    value: float
    offsetSeconds: int      # informational only; arrival ORDER drives the test


@dataclass(frozen=True)
class _DriveTrajectory:
    """One production drive reduced to its essential trace.

    Attributes:
        driveId: Drive id matching Spool's drive-grade notes.
        durationSec: Documented drive duration (informational).
        fromState: ``UNKNOWN`` for cold-start, ``RUNNING`` for warm
            restart -- this gates the cold-start ambient rule.
        sensorArrivals: Ordered list of sensor readings arriving
            post drive_start.  Each arrival is one tick; the recorder
            is called with a snapshot containing all readings arrived
            so far (cumulative dict).
        expectedColdStart: True when ``fromState`` triggers ambient
            capture from IAT.  Used to validate the post-Sprint-19
            row's expected non-NULL fields.
    """

    driveId: int
    durationSec: int
    fromState: EngineState
    sensorArrivals: tuple[_SensorArrival, ...]
    expectedColdStart: bool = field(default=True)


# Drive 3: 2026-04-23 9:30 cold-start, thermostat opens at 80C.  Sensor
# readings begin arriving once the ECU starts responding.
_DRIVE_3 = _DriveTrajectory(
    driveId=3,
    durationSec=570,  # 9:30
    fromState=EngineState.UNKNOWN,
    sensorArrivals=(
        _SensorArrival(paramName='INTAKE_TEMP', value=19.0, offsetSeconds=5),
        _SensorArrival(paramName='BATTERY_V', value=13.4, offsetSeconds=5),
        _SensorArrival(paramName='BAROMETRIC_KPA', value=100.2,
                       offsetSeconds=5),
    ),
    expectedColdStart=True,
)

# Drive 4: 2026-04-29 10:47 warm-idle post-jump-start.  Battery was
# the only sensor of interest (alternator hard-charging) -- IAT was
# already heat-soaked so ambient stays NULL by warm-restart rule.
_DRIVE_4 = _DriveTrajectory(
    driveId=4,
    durationSec=647,  # 10:47
    fromState=EngineState.RUNNING,
    sensorArrivals=(
        _SensorArrival(paramName='INTAKE_TEMP', value=85.0, offsetSeconds=3),
        _SensorArrival(paramName='BATTERY_V', value=14.2, offsetSeconds=5),
        _SensorArrival(paramName='BAROMETRIC_KPA', value=100.1,
                       offsetSeconds=8),
    ),
    expectedColdStart=False,
)

# Drive 5: 2026-04-29 17:39 full cold-start cycle.  The cleanest
# dataset to date per Spool's drive-grade note.  All 3 sensors arrive
# within seconds of drive_start.
_DRIVE_5 = _DriveTrajectory(
    driveId=5,
    durationSec=1059,  # 17:39
    fromState=EngineState.UNKNOWN,
    sensorArrivals=(
        _SensorArrival(paramName='INTAKE_TEMP', value=19.0, offsetSeconds=5),
        _SensorArrival(paramName='BATTERY_V', value=13.8, offsetSeconds=5),
        _SensorArrival(paramName='BAROMETRIC_KPA', value=100.2,
                       offsetSeconds=5),
    ),
    expectedColdStart=True,
)

_ALL_DRIVE_TRAJECTORIES = (_DRIVE_3, _DRIVE_4, _DRIVE_5)


# ================================================================================
# Pre-Sprint-19 INSERT-immediately recorder stub (the failure mode reproducer)
# ================================================================================


class _PreSprint19InsertImmediatelyRecorder:
    """Faithful mock of Sprint 18 Option (b) recorder + unwired backfill.

    Models ONLY the failure mode: INSERT at drive_start with whatever's
    in the snapshot (typically empty -- production drive_start fires
    before sensor readings arrive), then no further updates because
    the production backfill UPDATE was empirically unwired.

    The stub does NOT model:
    * Cold-start ambient rule -- handled by
      :func:`buildSummaryFromSnapshot` even on the broken path.
    * UPSERT replay semantics -- not relevant to the bug class.
    * forceInsert / reason fields -- introduced by Sprint 19 US-236.

    Per US-261 stopCondition #1, this stub exists to prove the bug
    class without checking out historical code.  It is intentionally
    minimal: ~25 lines that exactly reproduce the documented "row
    inserted at drive_start with empty snapshot then never updated"
    behavior observed across drives 3, 4, 5.
    """

    def __init__(self, *, database: ObdDatabase) -> None:
        self._database = database

    def captureDriveStart(
        self,
        *,
        driveId: int,
        snapshot: dict[str, Any] | None,
        fromState: EngineState | str | None,
    ) -> None:
        """Sprint 18 Option (b): INSERT a row immediately, even if all-NULL.

        Reproduces the production failure mode: drive_start fires before
        any sensor reading is cached, the snapshot is effectively empty,
        the cold-start rule + ``buildSummaryFromSnapshot`` produce a row
        with all 3 metadata columns NULL, and that row is INSERTed.
        """
        summary = buildSummaryFromSnapshot(
            driveId=driveId,
            snapshot=snapshot,
            fromState=fromState,
        )
        with self._database.connect() as conn:
            conn.execute(
                f"INSERT OR IGNORE INTO {DRIVE_SUMMARY_TABLE} "
                f"(drive_id, ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start, data_source) "
                f"VALUES (?, ?, ?, ?, ?)",
                (
                    summary.driveId,
                    summary.ambientTempAtStartC,
                    summary.startingBatteryV,
                    summary.barometricKpaAtStart,
                    summary.dataSource,
                ),
            )
            conn.commit()

    def attemptBackfill(
        self,
        *,
        driveId: int,
        snapshot: dict[str, Any],
    ) -> None:
        """Sprint 18 unwired backfill -- deliberately a no-op.

        The Sprint-18 ship had a backfillFromSnapshot method but the
        DriveDetector never called it on subsequent ticks (the
        wiring was missing).  This stub method exists to make the
        production failure mode explicit: even if the test calls it
        repeatedly with sensor data, no UPDATE fires, and the row
        stays all-NULL.
        """
        # Intentionally empty: the bug class is "wiring missing".
        # See Spool's 4-drive consolidated note for the production
        # observation that drives 3/4/5 all had all-NULL rows.
        return


# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "us261_us228_retro.db"), walMode=False)
    db.initialize()
    return db


def _readSummaryRow(
    db: ObdDatabase, driveId: int,
) -> tuple[Any, ...] | None:
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT ambient_temp_at_start_c, starting_battery_v, "
            f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
            f"WHERE drive_id = ?",
            (driveId,),
        ).fetchone()
    return tuple(row) if row is not None else None


def _replayDriveTrajectory(
    *,
    recorder: SummaryRecorder,
    trajectory: _DriveTrajectory,
) -> None:
    """Replay a drive trajectory through the post-Sprint-19 defer-INSERT path.

    Step 1: drive_start with empty snapshot -> deferred no-op (no row).
    Steps 2..N: each sensor arrival adds to the cumulative snapshot and
    re-calls captureDriveStart.  The first call with a non-empty
    snapshot triggers the INSERT (or, for warm restarts, the first
    BATTERY_V / BAROMETRIC_KPA arrival triggers it -- IAT is filtered
    out by the warm-restart cold-start rule).  Subsequent calls UPDATE
    the row.

    This mirrors the real DriveDetector loop: empty-snapshot defer at
    drive_start, then per-tick re-calls as sensor cache fills.
    """
    # Step 1: drive_start with empty snapshot.
    recorder.captureDriveStart(
        driveId=trajectory.driveId,
        snapshot={},
        fromState=trajectory.fromState,
    )
    # Steps 2..N: cumulative sensor arrivals.
    cumulative: dict[str, float] = {}
    for arrival in trajectory.sensorArrivals:
        cumulative[arrival.paramName] = arrival.value
        # The detector also calls backfillFromSnapshot on later ticks;
        # captureDriveStart's UPSERT path covers the same DB write so
        # we use it here for simplicity.
        recorder.captureDriveStart(
            driveId=trajectory.driveId,
            snapshot=dict(cumulative),
            fromState=trajectory.fromState,
        )


def _replayPreSprint19DriveTrajectory(
    *,
    recorder: _PreSprint19InsertImmediatelyRecorder,
    trajectory: _DriveTrajectory,
) -> None:
    """Replay through the pre-Sprint-19 INSERT-immediately + unwired backfill.

    Step 1: drive_start with empty snapshot -> INSERT all-NULL row.
    Steps 2..N: sensor arrivals attempt backfill -- no-op stub.
    Final row is whatever was INSERTed at step 1: all-NULL.
    """
    recorder.captureDriveStart(
        driveId=trajectory.driveId,
        snapshot={},
        fromState=trajectory.fromState,
    )
    cumulative: dict[str, float] = {}
    for arrival in trajectory.sensorArrivals:
        cumulative[arrival.paramName] = arrival.value
        # The "backfill" tick fires but is unwired in production --
        # our stub matches that behavior.
        recorder.attemptBackfill(
            driveId=trajectory.driveId,
            snapshot=dict(cumulative),
        )


# ================================================================================
# Pre-Sprint-19 path: every drive ends with all-NULL metadata
# ================================================================================


class TestPreSprint19RecorderProducesAllNullRows:
    """The bug class proof: Sprint 18 INSERT-immediately + unwired backfill
    produces an all-NULL drive_summary row on every documented drive,
    regardless of how many sensor readings arrive afterward.  This is
    exactly the production observation Spool reported on 2026-04-29."""

    @pytest.mark.parametrize(
        "trajectory",
        _ALL_DRIVE_TRAJECTORIES,
        ids=["drive3_coldStart", "drive4_warmIdle", "drive5_fullColdCycle"],
    )
    def test_preSprint19_recorder_producesAllNullRow(
        self,
        trajectory: _DriveTrajectory,
        freshDb: ObdDatabase,
    ) -> None:
        """Pre-Sprint-19 path: drive_summary row is all-NULL post-drive.

        Discriminator: the INSERT fires at drive_start with empty
        snapshot, producing (NULL, NULL, NULL).  The unwired backfill
        never updates the row.  Final row state matches Spool's
        production observation across drives 3/4/5.
        """
        recorder = _PreSprint19InsertImmediatelyRecorder(database=freshDb)
        _replayPreSprint19DriveTrajectory(
            recorder=recorder, trajectory=trajectory,
        )

        row = _readSummaryRow(freshDb, driveId=trajectory.driveId)
        assert row is not None, (
            f"Drive {trajectory.driveId}: pre-Sprint-19 path should always "
            f"INSERT a row (the bug is that it INSERTs with all NULLs, not "
            f"that it skips the INSERT)."
        )
        assert row == (None, None, None), (
            f"Drive {trajectory.driveId}: expected pre-Sprint-19 path to "
            f"produce an all-NULL row matching the documented production "
            f"failure mode, got {row}.  The stub does not reproduce the "
            f"documented bug class if this assertion fails."
        )


# ================================================================================
# Post-Sprint-19 path: every drive ends with at least one non-NULL field
# ================================================================================


class TestPostSprint19DeferInsertProducesNonNullRow:
    """Sprint 19 US-236 defer-INSERT path: every drive ends with at least
    one non-NULL sensor field once the first sensor reading arrives.
    The bug class is eliminated by construction -- the row only appears
    when at least one column will be non-NULL."""

    @pytest.mark.parametrize(
        "trajectory",
        _ALL_DRIVE_TRAJECTORIES,
        ids=["drive3_coldStart", "drive4_warmIdle", "drive5_fullColdCycle"],
    )
    def test_postSprint19_deferInsert_producesNonNullRow(
        self,
        trajectory: _DriveTrajectory,
        freshDb: ObdDatabase,
    ) -> None:
        """Post-Sprint-19 path: drive_summary row has at least one non-
        NULL sensor field.  For cold-starts (drives 3 and 5) all 3
        fields populate.  For warm restarts (drive 4) ambient stays
        NULL by the cold-start rule but battery + baro populate.

        Discriminator: at least one non-NULL field is the eliminator
        for the bug class.  An all-NULL row would mean the defer-
        INSERT path failed to fire -- which would exactly reproduce
        the Sprint-18 production failure mode.
        """
        recorder = SummaryRecorder(database=freshDb)
        _replayDriveTrajectory(recorder=recorder, trajectory=trajectory)

        row = _readSummaryRow(freshDb, driveId=trajectory.driveId)
        assert row is not None, (
            f"Drive {trajectory.driveId}: post-Sprint-19 path should INSERT "
            f"a row by drive end (defer-INSERT triggers on first sensor "
            f"arrival)."
        )
        nonNullCount = sum(1 for v in row if v is not None)
        assert nonNullCount >= 1, (
            f"Drive {trajectory.driveId}: post-Sprint-19 path should "
            f"populate at least one sensor field by drive end, got "
            f"all-NULL row {row}.  This would exactly reproduce the "
            f"Sprint-18 bug class."
        )

    def test_postSprint19_drive3_coldStart_allThreeFieldsPopulated(
        self,
        freshDb: ObdDatabase,
    ) -> None:
        """Drive 3 cold-start: all 3 sensors arrive -> all 3 fields non-NULL."""
        recorder = SummaryRecorder(database=freshDb)
        _replayDriveTrajectory(recorder=recorder, trajectory=_DRIVE_3)
        row = _readSummaryRow(freshDb, driveId=_DRIVE_3.driveId)
        assert row == (19.0, 13.4, 100.2)

    def test_postSprint19_drive4_warmIdle_ambientNullBatteryNonNull(
        self,
        freshDb: ObdDatabase,
    ) -> None:
        """Drive 4 warm-idle: ambient stays NULL (warm-restart rule) but
        battery + baro populate.  This is the design-intent behavior
        per Invariant #2 (warm restart = ambient NULL forever)."""
        recorder = SummaryRecorder(database=freshDb)
        _replayDriveTrajectory(recorder=recorder, trajectory=_DRIVE_4)
        row = _readSummaryRow(freshDb, driveId=_DRIVE_4.driveId)
        assert row is not None
        assert row[0] is None       # ambient NULL by warm-restart rule
        assert row[1] == 14.2       # battery captured
        assert row[2] == 100.1      # baro captured

    def test_postSprint19_drive5_fullCycle_allThreeFieldsPopulated(
        self,
        freshDb: ObdDatabase,
    ) -> None:
        """Drive 5 cold-start full cycle: all 3 sensors arrive -> all 3
        fields non-NULL.  The cleanest dataset to date per Spool's
        drive-grade note."""
        recorder = SummaryRecorder(database=freshDb)
        _replayDriveTrajectory(recorder=recorder, trajectory=_DRIVE_5)
        row = _readSummaryRow(freshDb, driveId=_DRIVE_5.driveId)
        assert row == (19.0, 13.8, 100.2)


# ================================================================================
# Cross-discriminator combined assertion
# ================================================================================


class TestPreVsPostSprint19DriveSummaryDiscriminatorPair:
    """One unified test asserting BOTH directions of the discriminator on
    drive 5 (the most recent + cleanest production drive).  Same
    trajectory feeds both recorders; pre-Sprint-19 ends all-NULL,
    post-Sprint-19 ends with all 3 fields populated."""

    def test_drive5_preFix_allNull_postFix_allPopulated(
        self,
        tmp_path: Path,
    ) -> None:
        """Drive 5 trajectory drives both the pre-Sprint-19 stub and the
        post-Sprint-19 production recorder against fresh DBs.  Pre-fix
        ends (None, None, None).  Post-fix ends (19.0, 13.8, 100.2)."""
        # Pre-Sprint-19 path
        preDb = ObdDatabase(str(tmp_path / "pre.db"), walMode=False)
        preDb.initialize()
        preRecorder = _PreSprint19InsertImmediatelyRecorder(database=preDb)
        _replayPreSprint19DriveTrajectory(
            recorder=preRecorder, trajectory=_DRIVE_5,
        )
        preRow = _readSummaryRow(preDb, driveId=_DRIVE_5.driveId)
        assert preRow == (None, None, None)

        # Post-Sprint-19 path
        postDb = ObdDatabase(str(tmp_path / "post.db"), walMode=False)
        postDb.initialize()
        postRecorder = SummaryRecorder(database=postDb)
        _replayDriveTrajectory(recorder=postRecorder, trajectory=_DRIVE_5)
        postRow = _readSummaryRow(postDb, driveId=_DRIVE_5.driveId)
        assert postRow == (19.0, 13.8, 100.2)


# ================================================================================
# Sanity: SQLite raises on the discriminator only when the recorder is wrong
# ================================================================================


class TestStubFidelityToProductionFailureMode:
    """Validates the pre-Sprint-19 stub actually reproduces the failure
    mode it claims to.  If the stub silently fixed the bug (e.g. by
    INSERTing the cumulative snapshot rather than the empty
    drive_start snapshot) the discriminator pair above would still
    pass, masking a regression in this test file.  This test
    explicitly inspects the stub's INSERT timing."""

    def test_stub_insertsAtDriveStartNotOnSensorArrival(
        self,
        freshDb: ObdDatabase,
    ) -> None:
        """The stub INSERTs at the drive_start call, not on subsequent
        sensor-arrival ticks.  Verified by counting rows immediately
        after drive_start before any sensor arrivals replay."""
        recorder = _PreSprint19InsertImmediatelyRecorder(database=freshDb)
        # Drive_start only -- no sensor arrivals yet.
        recorder.captureDriveStart(
            driveId=99,
            snapshot={},
            fromState=EngineState.UNKNOWN,
        )
        # Row exists already with all-NULL metadata (the bug).
        row = _readSummaryRow(freshDb, driveId=99)
        assert row == (None, None, None)

    def test_stub_attemptBackfillIsNoOp(
        self,
        freshDb: ObdDatabase,
    ) -> None:
        """The stub's attemptBackfill is a no-op: subsequent calls with
        cumulative sensor data do NOT update the row."""
        recorder = _PreSprint19InsertImmediatelyRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=98,
            snapshot={},
            fromState=EngineState.UNKNOWN,
        )
        for _ in range(5):
            recorder.attemptBackfill(
                driveId=98,
                snapshot={
                    'INTAKE_TEMP': 20.0,
                    'BATTERY_V': 13.5,
                    'BAROMETRIC_KPA': 99.0,
                },
            )
        row = _readSummaryRow(freshDb, driveId=98)
        # The stub never updates -- row stays all-NULL despite repeated
        # backfill attempts with full sensor snapshot.
        assert row == (None, None, None)


# Sanity: imports referenced for type-checking compatibility.
# (sqlite3 is imported at module top; tests don't invoke it directly
# but the type hint on `_readSummaryRow` and the recorder interplay
# rely on it transitively.)
_ = sqlite3
