################################################################################
# File Name: test_harness_idempotency.py
# Purpose/Description: US-449 / F-104 -- idempotency proof for the B-104
#                      server-analytics harness (compute_drive_summary +
#                      compute_drive_statistics + compute_drive_derived_signals).
#                      Re-runs the whole harness over the SAME raw realtime_data
#                      and asserts byte-identical owned-table rows (0 diffs),
#                      the AC2/AC4 "re-run = 0 row diffs" contract.  The only
#                      column allowed to advance is the intentionally-volatile
#                      ``computed_at`` observability timestamp.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-449) | Initial -- F-104 spine: prove the harness is
#               |              | idempotent (same raw -> byte-identical owned
#               |              | rows).  In-memory SQLite + real ORM + real
#               |              | INSERTs (no seam mocks), mirroring the US-350/
#               |              | US-351 compute-test discipline.  NOTE: the
#               |              | "sole writer / no dual-write" AC (US-449 AC2)
#               |              | is BLOCKED by BL-017 (a live /analyze writer of
#               |              | drive_statistics); this file proves only the
#               |              | idempotency half, which is ruling-independent.
# ================================================================================
################################################################################

"""US-449 / F-104 -- harness idempotency proof (re-run-and-diff = 0 diffs).

The B-104 server-analytics harness is the three per-drive compute functions
run in order over a Pi-local ``drive_id``:

1. :func:`src.server.analytics.drive_summary_compute.compute_drive_summary`
2. :func:`src.server.analytics.drive_statistics_compute.compute_drive_statistics`
3. :func:`src.server.analytics.derived_signals_compute.compute_drive_derived_signals`

The idempotency contract (US-449 AC2/AC4): re-running the whole harness over
the SAME raw ``realtime_data`` produces byte-identical owned-table rows.  The
only column permitted to advance across a re-run is the intentionally-volatile
``computed_at`` observability timestamp (``onupdate=func.now()`` on
``drive_statistics`` / ``drive_derived_signals``) -- so this proof snapshots
every data column EXCEPT ``computed_at`` and asserts a zero diff.

Test discipline (post-I-040 lesson): real in-memory SQLite engine + the real
ORM models + real INSERTs of synthetic ``realtime_data`` / ``drive_summary``
rows.  No mocks of the compute seams.

Scope note: US-449 AC2 also requires the harness be the SOLE writer of its
owned tables (no dual-write).  That half is BLOCKED -- ``drive_statistics`` has
a second live writer, ``src.server.analytics.basic.computeDriveStatistics``,
reached via ``POST /api/v1/analyze`` -> ``runAnalysis`` ->
``_buildAnalyticsContext``.  See ``offices/pm/blockers/
BL-017-us449-drive-statistics-dual-write-analyze.md``.  This file deliberately
proves only the ruling-independent idempotency contract.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics.derived_signals_compute import (  # noqa: E402
    compute_drive_derived_signals,
)
from src.server.analytics.drive_statistics_compute import (  # noqa: E402
    compute_drive_statistics,
)
from src.server.analytics.drive_summary_compute import (  # noqa: E402
    compute_drive_summary,
)
from src.server.db.models import (  # noqa: E402
    Base,
    DriveDerivedSignal,
    DriveStatistic,
    DriveSummary,
    RealtimeData,
)

# =========================================================================
# Fixtures + seeding (mirrors test_drive_statistics_compute discipline)
# =========================================================================


@pytest.fixture
def engine():
    """Temp-file SQLite engine carrying the full server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _seedPiSyncedDriveSummary(
    session: Session,
    *,
    driveId: int,
    device: str = "chi-eclipse-01",
    dataSource: str = "real",
) -> int:
    """Seed a Pi-sync ``drive_summary`` row; return server-side drive_summary.id."""
    row = DriveSummary(
        source_device=device,
        source_id=driveId,
        drive_id=driveId,
        data_source=dataSource,
        start_time=None,
        end_time=None,
        duration_seconds=None,
        row_count=None,
        is_real=None,
    )
    session.add(row)
    session.commit()
    return row.id


def _seedRealtimeRows(
    session: Session,
    *,
    driveId: int,
    device: str = "chi-eclipse-01",
    startTime: datetime,
    paramSeries: dict[str, list[float]],
    profileId: str | None = "pump-gas",
    pollIntervalSeconds: float = 1.0,
) -> int:
    """Seed ``realtime_data`` rows for a drive from per-parameter value lists."""
    total = 0
    sourceIdCursor = driveId * 1_000_000
    longest = max((len(series) for series in paramSeries.values()), default=0)
    for i in range(longest):
        ts = startTime + timedelta(seconds=i * pollIntervalSeconds)
        for param, series in paramSeries.items():
            if i >= len(series):
                continue
            session.add(
                RealtimeData(
                    source_id=sourceIdCursor,
                    source_device=device,
                    timestamp=ts,
                    parameter_name=param,
                    value=float(series[i]),
                    drive_id=driveId,
                    data_source="real",
                    profile_id=profileId,
                )
            )
            sourceIdCursor += 1
            total += 1
    session.commit()
    return total


# =========================================================================
# Harness runner + owned-table snapshotter
# =========================================================================


def _runHarness(session: Session, driveId: int) -> None:
    """Run the full B-104 analytics harness over one Pi-local ``drive_id``.

    The three computes in the canonical order the on-demand CLI + nightly
    timer fire them (see ``src.server.cli.recompute_drive_analytics``).
    """
    compute_drive_summary(session, driveId)
    compute_drive_statistics(session, driveId)
    compute_drive_derived_signals(session, driveId)
    session.commit()


def _snapshotOwnedTables(session: Session, summaryId: int) -> dict[str, list]:
    """Read every owned-table data column for a drive (EXCLUDING computed_at).

    ``computed_at`` is the intentionally-volatile idempotency-observability
    timestamp (``onupdate=func.now()``); it is designed to advance on re-run
    and is therefore excluded from the byte-identical comparison.  Every other
    persisted column is captured, so any real data drift across a re-run is a
    hard failure.
    """
    summary = session.get(DriveSummary, summaryId)
    assert summary is not None
    summarySnap = (
        summary.start_time,
        summary.end_time,
        summary.duration_seconds,
        summary.row_count,
        summary.is_real,
        summary.data_quality,
        summary.profile_id,
    )

    statRows = session.execute(
        select(DriveStatistic)
        .where(DriveStatistic.summary_id == summaryId)
        .order_by(DriveStatistic.parameter_name)
    ).scalars().all()
    statSnap = [
        (
            r.summary_id,
            r.parameter_name,
            r.min_value,
            r.max_value,
            r.avg_value,
            r.std_dev,
            r.outlier_min,
            r.outlier_max,
            r.sample_count,
            r.data_quality,
        )
        for r in statRows
    ]

    derivedRows = session.execute(
        select(DriveDerivedSignal)
        .where(DriveDerivedSignal.summary_id == summaryId)
        .order_by(DriveDerivedSignal.summary_id)
    ).scalars().all()
    derivedSnap = [
        (
            r.summary_id,
            r.estimated_distance_km,
            r.peak_acceleration_ms2,
            r.peak_deceleration_ms2,
            r.sample_count,
            r.segment_count,
            r.gap_skipped_count,
            r.speed_unit,
            r.distance_unit,
            r.accel_unit,
        )
        for r in derivedRows
    ]

    return {
        "drive_summary": [summarySnap],
        "drive_statistics": statSnap,
        "drive_derived_signals": derivedSnap,
    }


# =========================================================================
# Idempotency proof
# =========================================================================


class TestHarnessIdempotency:
    """US-449 AC2/AC4: re-running the harness on the same raw = 0 row diffs."""

    def _seedDrive(self, session: Session, driveId: int) -> int:
        """Seed one realistic multi-PID drive; return drive_summary.id."""
        startTime = datetime(2026, 7, 4, 10, 0, 0)
        summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
        _seedRealtimeRows(
            session,
            driveId=driveId,
            startTime=startTime,
            paramSeries={
                "RPM": [800.0, 1500.0, 2400.0, 1800.0, 1000.0, 900.0],
                "SPEED": [0.0, 25.0, 60.0, 45.0, 30.0, 0.0],
                "COOLANT_TEMP": [85.0, 86.0, 87.0, 88.0, 87.0, 86.0],
            },
        )
        return summaryId

    def test_reRun_producesByteIdenticalOwnedRows(self, engine):
        """Second harness pass over identical raw = identical owned-table data."""
        driveId = 42
        with Session(engine) as session:
            summaryId = self._seedDrive(session, driveId)

            _runHarness(session, driveId)
            firstSnapshot = _snapshotOwnedTables(session, summaryId)

            _runHarness(session, driveId)
            secondSnapshot = _snapshotOwnedTables(session, summaryId)

            assert firstSnapshot == secondSnapshot, (
                "harness is NOT idempotent -- a re-run over identical raw "
                "realtime_data produced different owned-table rows"
            )

    def test_firstRun_actuallyPopulatedTheOwnedTables(self, engine):
        """Guard: the idempotency assertion is not vacuously comparing empties."""
        driveId = 43
        with Session(engine) as session:
            summaryId = self._seedDrive(session, driveId)
            _runHarness(session, driveId)
            snapshot = _snapshotOwnedTables(session, summaryId)

            # drive_summary analytics columns were written.
            summarySnap = snapshot["drive_summary"][0]
            assert summarySnap[3] == 18  # row_count = 6 ticks * 3 PIDs
            assert summarySnap[4] is True  # is_real (data_source='real')
            # One drive_statistics row per PID.
            assert {s[1] for s in snapshot["drive_statistics"]} == {
                "RPM", "SPEED", "COOLANT_TEMP",
            }
            # One derived-signals row.
            assert len(snapshot["drive_derived_signals"]) == 1

    def test_ownedTables_keyedOnSubsumedCanonicalDriveId(self, engine):
        """VC1: owned tables key on drive_summary.id (== drives.drive_id, US-448).

        US-448 subsumed ``drive_summary.id`` INTO ``drives.drive_id`` (the
        same integer value), so a key of ``summary_id`` IS the canonical
        drive identity.  The FK-constraint re-point is US-451; here we assert
        the harness already keys its owned rows on that subsumed identity.
        """
        driveId = 44
        with Session(engine) as session:
            summaryId = self._seedDrive(session, driveId)
            _runHarness(session, driveId)

            statKeys = session.execute(
                select(DriveStatistic.summary_id).distinct()
            ).scalars().all()
            derivedKeys = session.execute(
                select(DriveDerivedSignal.summary_id).distinct()
            ).scalars().all()

            assert statKeys == [summaryId]
            assert derivedKeys == [summaryId]
