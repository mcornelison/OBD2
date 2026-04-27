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
# ================================================================================
################################################################################

"""Integration tests: DriveDetector + SummaryRecorder backfill loop (US-228)."""

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


def _readSummaryRow(db: ObdDatabase, driveId: int) -> tuple[object, ...]:
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT ambient_temp_at_start_c, starting_battery_v, "
            f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
            f"WHERE drive_id = ?",
            (driveId,),
        ).fetchone()
    assert row is not None, f"drive_summary row missing for drive_id={driveId}"
    return tuple(row)


class TestEndToEndBackfillOnEmptyStart:
    """Drive-start with empty snapshot -> later ticks backfill the row."""

    def test_emptyAtStartBackfilledOnSubsequentTicks(
        self, freshDb: ObdDatabase
    ) -> None:
        """Drive 3 scenario: empty snapshot at start; backfill as readings arrive."""
        snapshot = _MutableSnapshotSource()
        detector = _buildDetector(freshDb, snapshot=snapshot)

        # Drive start with empty snapshot.
        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row == (None, None, None)  # bug state at t=0

        # First backfill tick: only BATTERY_V arrived so far.
        snapshot.set(BATTERY_V=13.4)
        detector.processValue('RPM', 2500.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row[1] == 13.4
        assert row[0] is None
        assert row[2] is None

        # Second tick: IAT + BARO arrive.
        snapshot.set(INTAKE_TEMP=19.0, BAROMETRIC_KPA=100.2)
        detector.processValue('RPM', 2500.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row[0] == 19.0
        assert row[1] == 13.4
        assert row[2] == 100.2

    def test_backfillStopsOnceComplete(
        self, freshDb: ObdDatabase
    ) -> None:
        """Once all three fields are filled, backfill ticks are early-exit."""
        snapshot = _MutableSnapshotSource()
        detector = _buildDetector(freshDb, snapshot=snapshot)

        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        snapshot.set(
            INTAKE_TEMP=20.0, BATTERY_V=12.6, BAROMETRIC_KPA=101.0
        )
        detector.processValue('RPM', 2500.0)  # backfill completes

        # Now mutate the snapshot to "bad" values -- should NOT be written
        # because backfill has already flagged complete.
        snapshot.set(
            INTAKE_TEMP=99.0, BATTERY_V=99.9, BAROMETRIC_KPA=999.0
        )
        detector.processValue('RPM', 2500.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row == (20.0, 12.6, 101.0)


class TestBackfillWindowTimeout:
    """Backfill respects the configured window; after timeout, no more writes."""

    def test_backfillStopsAfterWindowExpires(
        self, freshDb: ObdDatabase
    ) -> None:
        """IAT arrives after the 0-second window expires -> no backfill write."""
        snapshot = _MutableSnapshotSource()
        detector = _buildDetector(
            freshDb, snapshot=snapshot, backfillSeconds=0.05
        )

        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        # Wait past the backfill window (50ms -> sleep 100ms).
        time.sleep(0.1)

        # IAT arrives too late -- row must stay NULL.
        snapshot.set(
            INTAKE_TEMP=19.0, BATTERY_V=13.4, BAROMETRIC_KPA=100.2
        )
        detector.processValue('RPM', 2500.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row == (None, None, None)


class TestBackfillWarmRestart:
    """Warm-restart ambient stays NULL even during the backfill window."""

    def test_warmRestartBackfillSkipsAmbient(
        self, freshDb: ObdDatabase
    ) -> None:
        """IAT arriving during warm-restart backfill MUST NOT fill ambient."""
        snapshot = _MutableSnapshotSource()
        detector = _buildDetector(freshDb, snapshot=snapshot)

        # Monkey-patch _lastEngineState to simulate warm restart before start.
        from src.pi.obdii.engine_state import EngineState
        detector._lastEngineState = EngineState.RUNNING  # type: ignore[attr-defined]

        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        # Drive-start row exists, all NULL.
        row = _readSummaryRow(freshDb, driveId=1)
        assert row == (None, None, None)

        # Readings arrive -- ambient MUST stay NULL; battery + baro fill.
        snapshot.set(
            INTAKE_TEMP=85.0, BATTERY_V=13.7, BAROMETRIC_KPA=100.4
        )
        detector.processValue('RPM', 2500.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row[0] is None
        assert row[1] == 13.7
        assert row[2] == 100.4


class TestBackfillDuringDriveEndInterrupt:
    """If drive ends during the backfill window, subsequent ticks don't write."""

    def test_backfillStopsOnDriveEnd(
        self, freshDb: ObdDatabase
    ) -> None:
        snapshot = _MutableSnapshotSource()
        detector = _buildDetector(freshDb, snapshot=snapshot)

        detector.processValue('RPM', 2500.0)
        detector.processValue('RPM', 2500.0)

        # Drive ends immediately (duration=0 config).
        detector.processValue('RPM', 0.0)
        detector.processValue('RPM', 0.0)

        # Readings arrive after drive_end -- detector no longer RUNNING,
        # so no backfill should happen.  Row stays NULL for drive_id=1.
        snapshot.set(
            INTAKE_TEMP=19.0, BATTERY_V=13.4, BAROMETRIC_KPA=100.2
        )
        # Re-processing after drive_end should NOT backfill drive_id=1.
        detector.processValue('RPM', 0.0)

        row = _readSummaryRow(freshDb, driveId=1)
        assert row == (None, None, None)
