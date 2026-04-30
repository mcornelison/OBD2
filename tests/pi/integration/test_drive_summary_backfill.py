################################################################################
# File Name: test_drive_summary_backfill.py
# Purpose/Description: Integration tests for the DriveDetector drive-start -> tick
#                      -> drive_summary backfill path (US-228).  Covers the
#                      end-to-end scenario: empty snapshot at drive_start ->
#                      subsequent processValue ticks with partial then full
#                      snapshot -> drive_summary row has non-null values.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex (US-228) | Initial.
# 2026-04-29    | Rex (US-236) | Sprint 19: tests rewritten for defer-INSERT
#                               semantics.  Sprint 18 INSERTed an all-NULL row
#                               at drive_start; the new flow defers until
#                               first IAT/BATTERY_V/BARO arrives, then
#                               backfills as more readings come in, OR
#                               force-INSERTs at the deadline tagged with
#                               reason='no_readings_within_timeout'.
# ================================================================================
################################################################################

"""Integration tests: DriveDetector + SummaryRecorder defer-INSERT loop (US-236)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive_id import clearCurrentDriveId
from src.pi.obdii.drive_summary import DRIVE_SUMMARY_TABLE, SummaryRecorder


class _MutableSnapshotSource:
    """Mutable stand-in for :class:`ObdDataLogger`.

    Tests mutate the backing dict to simulate readings arriving tick-
    by-tick (IAT comes in first, then BATTERY_V, then BAROMETRIC_KPA --
    whatever order Spool's Data v2 tiered poll produces).
    """

    def __init__(self) -> None:
        self._snapshot: dict[str, float] = {}

    def getLatestReadings(self) -> dict[str, float]:
        return dict(self._snapshot)

    def set(self, **values: float) -> None:
        for key, value in values.items():
            self._snapshot[key] = value


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "integ.db"), walMode=False)
    db.initialize()
    yield db
    clearCurrentDriveId()


def _makeConfig(
    *, backfillSeconds: float = 60.0
) -> dict[str, object]:
    return {
        'pi': {
            'analysis': {
                'driveStartRpmThreshold': 500.0,
                'driveStartDurationSeconds': 0.0,
                'driveEndRpmThreshold': 0.0,
                'driveEndDurationSeconds': 0.0,
                'triggerAfterDrive': False,
                'driveSummaryBackfillSeconds': backfillSeconds,
            },
            'profiles': {'activeProfile': 'daily'},
        },
    }


def _buildDetector(
    db: ObdDatabase,
    *,
    snapshot: _MutableSnapshotSource,
    backfillSeconds: float = 60.0,
) -> DriveDetector:
    detector = DriveDetector(
        _makeConfig(backfillSeconds=backfillSeconds),
        statisticsEngine=None,
        database=db,
        summaryRecorder=SummaryRecorder(database=db),
        readingSnapshotSource=snapshot,
    )
    detector.start()
    return detector


def _readSummaryRow(
    db: ObdDatabase, driveId: int
) -> tuple[object, ...] | None:
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT ambient_temp_at_start_c, starting_battery_v, "
            f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
            f"WHERE drive_id = ?",
            (driveId,),
        ).fetchone()
    return tuple(row) if row is not None else None


def _summaryRowExists(db: ObdDatabase, driveId: int) -> bool:
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT 1 FROM {DRIVE_SUMMARY_TABLE} WHERE drive_id = ?",
            (driveId,),
        ).fetchone()
    return row is not None


class TestEndToEndDeferInsertOnEmptyStart:
    """Drive-start with empty snapshot -> NO row until first reading arrives."""

    def test_emptyAtStartProducesNoRowUntilFirstReading(
        self, freshDb: ObdDatabase
    ) -> None:
        """US-236 (Drive 3 scenario): empty snapshot at start; row appears on first reading."""
        snapshot = _MutableSnapshotSource()
        detector = _buildDetector(freshDb, snapshot=snapshot)

        # Drive start with empty snapshot -- defer-INSERT, no row yet.
        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        assert not _summaryRowExists(freshDb, driveId=1), (
            "drive_summary row should NOT exist after empty-snapshot "
            "drive_start (US-236 Option a discriminator)."
        )

        # First tick with BATTERY_V -> row appears with battery only.
        snapshot.set(BATTERY_V=13.4)
        detector.processValue('RPM', 2500.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row is not None
        assert row[0] is None      # ambient still missing
        assert row[1] == 13.4      # battery captured
        assert row[2] is None      # baro still missing

        # Second tick: IAT + BARO arrive -> backfill phase fills them.
        snapshot.set(INTAKE_TEMP=19.0, BAROMETRIC_KPA=100.2)
        detector.processValue('RPM', 2500.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row == (19.0, 13.4, 100.2)

    def test_progressStopsOnceComplete(
        self, freshDb: ObdDatabase
    ) -> None:
        """Once all three fields are filled, subsequent ticks are early-exit."""
        snapshot = _MutableSnapshotSource()
        detector = _buildDetector(freshDb, snapshot=snapshot)

        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        # Snapshot has all 3; first tick post-drive-start INSERTs full row.
        snapshot.set(
            INTAKE_TEMP=20.0, BATTERY_V=12.6, BAROMETRIC_KPA=101.0
        )
        detector.processValue('RPM', 2500.0)

        # Mutate the snapshot to "bad" values -- complete flag prevents
        # further writes (backfill never clobbers anyway, but the loop
        # doesn't even run).
        snapshot.set(
            INTAKE_TEMP=99.0, BATTERY_V=99.9, BAROMETRIC_KPA=999.0
        )
        detector.processValue('RPM', 2500.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row == (20.0, 12.6, 101.0)


class TestDeferInsertWindowTimeoutForcesInsert:
    """Backfill window expires with no readings -> force-INSERT explicit-NULL row.

    US-236 acceptance #3: 60s timeout INSERTs a row tagged
    reason='no_readings_within_timeout' so analytics see the drive
    even when the ECU stayed silent the entire window.
    """

    def test_forceInsertOnDeadlineEvenWithEmptySnapshot(
        self, freshDb: ObdDatabase
    ) -> None:
        snapshot = _MutableSnapshotSource()
        detector = _buildDetector(
            freshDb, snapshot=snapshot, backfillSeconds=0.05
        )

        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        # Pre-deadline: no row yet.
        assert not _summaryRowExists(freshDb, driveId=1)

        # Wait past the deadline (50ms -> sleep 100ms).
        time.sleep(0.1)

        # Tick with still-empty snapshot -- forceInsert path fires.
        detector.processValue('RPM', 2500.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row == (None, None, None), (
            "60s deadline must force an explicit-NULL INSERT so analytics "
            "see the drive even when the ECU stays silent."
        )


class TestDeferInsertWarmRestart:
    """Warm-restart -> ambient stays NULL across both phases."""

    def test_warmRestartProgressFillsBatteryAndBaroOnly(
        self, freshDb: ObdDatabase
    ) -> None:
        """Warm restart + IAT -> defer; +BATTERY_V -> INSERT (ambient NULL)."""
        snapshot = _MutableSnapshotSource()
        detector = _buildDetector(freshDb, snapshot=snapshot)

        # Monkey-patch _lastEngineState to simulate warm restart before start.
        from src.pi.obdii.engine_state import EngineState
        detector._lastEngineState = EngineState.RUNNING  # type: ignore[attr-defined]

        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        # No row yet (defer phase).
        assert not _summaryRowExists(freshDb, driveId=1)

        # IAT arrives -- on warm restart this is filtered out, so the
        # post-cold-start payload is still all-NULL -> still deferred.
        snapshot.set(INTAKE_TEMP=85.0)
        detector.processValue('RPM', 2500.0)
        assert not _summaryRowExists(freshDb, driveId=1)

        # BATTERY_V + BARO join -> INSERT fires.  Ambient remains NULL.
        snapshot.set(BATTERY_V=13.7, BAROMETRIC_KPA=100.4)
        detector.processValue('RPM', 2500.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row[0] is None
        assert row[1] == 13.7
        assert row[2] == 100.4


class TestDeferInsertDuringDriveEndInterrupt:
    """If drive ends before any reading arrives, no row is created (defer canceled)."""

    def test_driveEndBeforeAnyReadingLeavesNoRow(
        self, freshDb: ObdDatabase
    ) -> None:
        snapshot = _MutableSnapshotSource()
        detector = _buildDetector(freshDb, snapshot=snapshot)

        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        # Drive ends immediately (duration=0 config).  No reading
        # arrived, so the row was never INSERTed and the deferred
        # state is cleared in _endDrive.
        detector.processValue('RPM', 0.0)
        detector.processValue('RPM', 0.0)

        # Readings arrive after drive_end -- detector no longer RUNNING,
        # so progress loop is a no-op.
        snapshot.set(
            INTAKE_TEMP=19.0, BATTERY_V=13.4, BAROMETRIC_KPA=100.2
        )
        detector.processValue('RPM', 0.0)

        # Drive 1 had no row INSERTed (deferred state canceled clean).
        assert not _summaryRowExists(freshDb, driveId=1)
