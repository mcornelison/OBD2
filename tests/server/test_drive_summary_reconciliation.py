################################################################################
# File Name: test_drive_summary_reconciliation.py
# Purpose/Description: US-214 -- merge the US-206 dual-writer pattern into a
#                      single row per drive keyed by (source_device, drive_id).
#                      Covers _ensureDriveSummary find-or-create, the extended
#                      extractDriveBoundaries drive_id passthrough, the
#                      Pi-first / analytics-first / both-present flows, and
#                      the idempotent double-write path.
# Author: Rex (Ralph)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-214) | Initial TDD tests for drive_summary dual-writer
#               |              | reconciliation (Option 1: Pi writes first,
#               |              | analytics updates).
# ================================================================================
################################################################################

"""Tests for US-214 drive_summary reconciliation.

Reconciliation contract (Option 1 from the Ralph US-206 note):

* Pi-sync path writes the row first with ``source_device`` + ``source_id``
  (== drive_id) + ``drive_id`` + metadata.  Analytics fields stay NULL.
* Analytics path runs at drive-end, finds the existing Pi-sync row via
  ``(source_device, drive_id)`` and UPDATEs analytics fields
  (``device_id``, ``start_time``, ``end_time``, ``duration_seconds``,
  ``row_count``, ``is_real``, ``profile_id``) in place.
* If no Pi-sync row exists yet (e.g. pre-US-200 data, or analytics run
  in isolation), analytics falls back to the legacy
  ``(device_id, start_time)`` find-or-create path -- no behavior change
  for that historical code path.

The companion one-shot migration ``scripts/reconcile_drive_summary.py``
merges pre-existing dual rows in the live DB.  Migration-scope tests
live alongside here so the semantics stay unified.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import (  # noqa: E402
    Base,
    DriveStatistic,
    DriveSummary,
    RealtimeData,
)
from src.server.services.analysis import (  # noqa: E402
    _ensureDriveSummary,
    extractDriveBoundaries,
)

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def session() -> Session:
    """In-memory SQLite session with all server tables materialised."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


DEVICE = "chi-eclipse-01"
START = datetime(2026, 4, 21, 10, 0, 0)
END = datetime(2026, 4, 21, 10, 15, 0)
DRIVE_ID = 42


def _insertPiSyncRow(
    session: Session,
    *,
    driveId: int = DRIVE_ID,
    deviceId: str = DEVICE,
    driveStartTs: datetime | None = START,
    ambient: float | None = 18.5,
    battery: float | None = 12.6,
    baro: float | None = 98.2,
) -> int:
    """Mirror what the sync path writes: metadata present, analytics NULL."""
    row = DriveSummary(
        source_device=deviceId,
        source_id=driveId,
        drive_id=driveId,
        drive_start_timestamp=driveStartTs,
        ambient_temp_at_start_c=ambient,
        starting_battery_v=battery,
        barometric_kpa_at_start=baro,
        data_source="real",
    )
    session.add(row)
    session.flush()
    return row.id


# ==============================================================================
# extractDriveBoundaries -- drive_id passthrough
# ==============================================================================


class TestExtractDriveBoundariesWithDriveId:
    """``extractDriveBoundaries`` must carry drive_id per pair."""

    def test_pairedEventsWithDriveId_driveIdReturned(self):
        rows = [
            {
                "timestamp": "2026-04-21T10:00:00",
                "event_type": "drive_start",
                "drive_id": 7,
            },
            {
                "timestamp": "2026-04-21T10:15:00",
                "event_type": "drive_end",
                "drive_id": 7,
            },
        ]
        assert extractDriveBoundaries(rows) == [
            (datetime(2026, 4, 21, 10, 0, 0), datetime(2026, 4, 21, 10, 15, 0), 7),
        ]

    def test_missingDriveId_returnsNone(self):
        """Legacy rows with no drive_id must not crash the extractor."""
        rows = [
            {"timestamp": "2026-04-21T10:00:00", "event_type": "drive_start"},
            {"timestamp": "2026-04-21T10:15:00", "event_type": "drive_end"},
        ]
        assert extractDriveBoundaries(rows) == [
            (
                datetime(2026, 4, 21, 10, 0, 0),
                datetime(2026, 4, 21, 10, 15, 0),
                None,
            ),
        ]

    def test_driveEndDriveIdPreferred(self):
        """When start and end disagree, drive_end wins (authoritative)."""
        rows = [
            {
                "timestamp": "2026-04-21T10:00:00",
                "event_type": "drive_start",
                "drive_id": 99,
            },
            {
                "timestamp": "2026-04-21T10:15:00",
                "event_type": "drive_end",
                "drive_id": 7,
            },
        ]
        boundaries = extractDriveBoundaries(rows)
        assert boundaries[0][2] == 7

    def test_driveStartOnlyDriveId_usedWhenEndMissing(self):
        rows = [
            {
                "timestamp": "2026-04-21T10:00:00",
                "event_type": "drive_start",
                "drive_id": 11,
            },
            {
                "timestamp": "2026-04-21T10:15:00",
                "event_type": "drive_end",
            },
        ]
        assert extractDriveBoundaries(rows)[0][2] == 11


# ==============================================================================
# _ensureDriveSummary -- Pi-first flow (normal US-214 path)
# ==============================================================================


class TestEnsureDriveSummaryPiFirst:
    """Pi-sync row exists first; analytics must UPDATE in place, not INSERT."""

    def test_piRowExists_analyticsUpdatesInPlace(self, session):
        preexistingId = _insertPiSyncRow(session)
        session.commit()

        returnedId = _ensureDriveSummary(
            session, DEVICE, START, END, driveId=DRIVE_ID,
        )
        session.commit()

        assert returnedId == preexistingId
        rows = session.execute(select(DriveSummary)).scalars().all()
        assert len(rows) == 1
        merged = rows[0]
        # Analytics fields now populated
        assert merged.device_id == DEVICE
        assert merged.start_time == START
        assert merged.end_time == END
        assert merged.duration_seconds == 900
        assert merged.is_real is True
        # Pi-sync metadata still intact
        assert merged.ambient_temp_at_start_c == 18.5
        assert merged.starting_battery_v == 12.6
        assert merged.barometric_kpa_at_start == 98.2
        assert merged.drive_id == DRIVE_ID
        assert merged.source_device == DEVICE
        assert merged.source_id == DRIVE_ID

    def test_piRowExists_doubleWriteIdempotent(self, session):
        """Analytics re-running on the same drive must not insert a dup."""
        _insertPiSyncRow(session)
        session.commit()

        firstId = _ensureDriveSummary(
            session, DEVICE, START, END, driveId=DRIVE_ID,
        )
        session.commit()
        secondId = _ensureDriveSummary(
            session, DEVICE, START, END, driveId=DRIVE_ID,
        )
        session.commit()

        assert firstId == secondId
        total = session.execute(select(DriveSummary)).scalars().all()
        assert len(total) == 1


# ==============================================================================
# _ensureDriveSummary -- analytics-first (Pi-sync missing/deferred)
# ==============================================================================


class TestEnsureDriveSummaryAnalyticsFirst:
    """No Pi-sync row yet (e.g. pre-US-200 or sync delay) -- must INSERT."""

    def test_noPreexistingRow_insertsBothHalves(self, session):
        returnedId = _ensureDriveSummary(
            session, DEVICE, START, END, driveId=DRIVE_ID,
        )
        session.commit()

        row = session.get(DriveSummary, returnedId)
        assert row is not None
        assert row.device_id == DEVICE
        assert row.start_time == START
        assert row.end_time == END
        # Pi-side columns populated on analytics-first insert so later
        # Pi-sync of the same (source_device, source_id) upserts in place
        # rather than creating a second row.
        assert row.source_device == DEVICE
        assert row.source_id == DRIVE_ID
        assert row.drive_id == DRIVE_ID
        assert row.is_real is True

    def test_driveIdNone_legacyPathNoSourceDevicePopulation(self, session):
        """Pre-US-200 flow (no drive_id in connection_log) -- legacy behavior."""
        returnedId = _ensureDriveSummary(
            session, DEVICE, START, END, driveId=None,
        )
        session.commit()

        row = session.get(DriveSummary, returnedId)
        assert row is not None
        assert row.device_id == DEVICE
        assert row.start_time == START
        # Legacy rows leave the Pi-sync columns untouched (source_device
        # NULL keeps the UNIQUE constraint clear of collisions).
        assert row.source_device is None
        assert row.drive_id is None

    def test_legacyRerunReturnsSameId(self, session):
        """Legacy path remains idempotent on re-run (matches pre-US-214 behavior)."""
        firstId = _ensureDriveSummary(
            session, DEVICE, START, END, driveId=None,
        )
        session.commit()
        secondId = _ensureDriveSummary(
            session, DEVICE, START, END, driveId=None,
        )
        session.commit()

        assert firstId == secondId


# ==============================================================================
# Pre-existing row_count is computed from realtime_data window
# ==============================================================================


class TestEnsureDriveSummaryRowCount:
    """Analytics-run must populate row_count from realtime_data in-window."""

    def test_realtimeDataInWindow_rowCountPopulated(self, session):
        preexistingId = _insertPiSyncRow(session)
        for i in range(5):
            session.add(
                RealtimeData(
                    source_id=i + 1,
                    source_device=DEVICE,
                    timestamp=datetime(2026, 4, 21, 10, 5, i),
                    parameter_name="RPM",
                    value=2200.0 + i,
                )
            )
        session.commit()

        _ensureDriveSummary(session, DEVICE, START, END, driveId=DRIVE_ID)
        session.commit()

        row = session.get(DriveSummary, preexistingId)
        assert row.row_count == 5


# ==============================================================================
# Reconciliation migration script -- merging existing dual rows
# ==============================================================================


class TestReconcileDualRowsMigration:
    """``scripts.reconcile_drive_summary.reconcile`` merges legacy dual rows."""

    def test_matchingPair_mergesIntoPiSyncRowAndDeletesAnalyticsRow(self, session):
        from scripts.reconcile_drive_summary import reconcile

        analyticsRow = DriveSummary(
            device_id=DEVICE,
            start_time=START,
            end_time=END,
            duration_seconds=900,
            row_count=42,
            is_real=True,
        )
        session.add(analyticsRow)
        session.flush()
        analyticsId = analyticsRow.id

        piRowId = _insertPiSyncRow(session, driveStartTs=START)
        session.commit()

        stats = reconcile(session, dryRun=False, timeWindowSeconds=60)
        session.commit()

        assert stats.merged == 1
        remaining = session.execute(select(DriveSummary)).scalars().all()
        assert len(remaining) == 1
        merged = remaining[0]
        # Pi-sync row survives (so source_device / drive_id stay stable
        # as the authoritative natural key).
        assert merged.id == piRowId
        assert merged.device_id == DEVICE
        assert merged.start_time == START
        assert merged.ambient_temp_at_start_c == 18.5
        # Analytics row is gone.
        assert session.get(DriveSummary, analyticsId) is None

    def test_driveStatisticsRefsRewritten(self, session):
        from scripts.reconcile_drive_summary import reconcile

        analyticsRow = DriveSummary(
            device_id=DEVICE,
            start_time=START,
            end_time=END,
            duration_seconds=900,
            row_count=3,
            is_real=True,
        )
        session.add(analyticsRow)
        session.flush()
        stat = DriveStatistic(
            drive_id=analyticsRow.id,
            parameter_name="RPM",
            avg_value=2500.0,
            sample_count=3,
        )
        session.add(stat)

        piRowId = _insertPiSyncRow(session, driveStartTs=START)
        session.commit()

        reconcile(session, dryRun=False, timeWindowSeconds=60)
        session.commit()

        # The drive_statistics row must now point at the surviving Pi-sync row.
        updated = session.execute(select(DriveStatistic)).scalars().all()
        assert len(updated) == 1
        assert updated[0].drive_id == piRowId

    def test_dryRun_makesNoChanges(self, session):
        from scripts.reconcile_drive_summary import reconcile

        analyticsRow = DriveSummary(
            device_id=DEVICE,
            start_time=START,
            end_time=END,
            duration_seconds=900,
            row_count=42,
            is_real=True,
        )
        session.add(analyticsRow)
        _insertPiSyncRow(session, driveStartTs=START)
        session.commit()
        beforeCount = len(session.execute(select(DriveSummary)).scalars().all())

        stats = reconcile(session, dryRun=True, timeWindowSeconds=60)

        assert stats.merged == 1  # Count what WOULD merge
        after = session.execute(select(DriveSummary)).scalars().all()
        assert len(after) == beforeCount  # But nothing actually changed

    def test_idempotent_secondRunMergesNothing(self, session):
        from scripts.reconcile_drive_summary import reconcile

        analyticsRow = DriveSummary(
            device_id=DEVICE,
            start_time=START,
            end_time=END,
            duration_seconds=900,
            row_count=42,
            is_real=True,
        )
        session.add(analyticsRow)
        _insertPiSyncRow(session, driveStartTs=START)
        session.commit()

        first = reconcile(session, dryRun=False, timeWindowSeconds=60)
        session.commit()
        second = reconcile(session, dryRun=False, timeWindowSeconds=60)
        session.commit()

        assert first.merged == 1
        assert second.merged == 0

    def test_noMatchingPiSyncRow_analyticsRowPreservedAsOrphan(self, session):
        """Analytics rows that pre-date US-200 (no drive_id on Pi) stay as-is."""
        from scripts.reconcile_drive_summary import reconcile

        analyticsRow = DriveSummary(
            device_id=DEVICE,
            start_time=START,
            end_time=END,
            duration_seconds=900,
            row_count=42,
            is_real=True,
        )
        session.add(analyticsRow)
        session.commit()

        stats = reconcile(session, dryRun=False, timeWindowSeconds=60)
        session.commit()

        assert stats.merged == 0
        assert stats.orphanedAnalyticsRows == 1
        assert session.get(DriveSummary, analyticsRow.id) is not None

    def test_timestampOutsideWindow_noMatch(self, session):
        """Pi-sync row whose drive_start_timestamp differs by > window is not merged."""
        from scripts.reconcile_drive_summary import reconcile

        analyticsRow = DriveSummary(
            device_id=DEVICE,
            start_time=START,
            end_time=END,
            duration_seconds=900,
            row_count=42,
            is_real=True,
        )
        session.add(analyticsRow)
        # Pi row claims drive started 5 minutes later -- outside the default
        # 60-second window.  Do NOT auto-merge; caller decides.
        _insertPiSyncRow(
            session, driveStartTs=datetime(2026, 4, 21, 10, 5, 0),
        )
        session.commit()

        stats = reconcile(session, dryRun=False, timeWindowSeconds=60)
        session.commit()

        assert stats.merged == 0
        remaining = session.execute(select(DriveSummary)).scalars().all()
        assert len(remaining) == 2
