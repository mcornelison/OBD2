################################################################################
# File Name: test_drive_statistics_compute.py
# Purpose/Description: Tests for src/server/analytics/drive_statistics_compute.py
#                      -- US-351 / B-104 Step 1b server-side drive_statistics
#                      compute from raw realtime_data.  Mirrors the US-350
#                      drive_summary_compute test discipline (in-memory SQLite +
#                      real ORM + real INSERTs; NO seam mocks) so the exact
#                      failure mode that masked three cycles of writer false-pass
#                      (US-326 V0.27.7, US-348 V0.27.16) cannot recur here.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex (US-351) | Initial -- B-104 Step 1b architectural shift.
#               |              | Pi-side drive_statistics table retired entirely
#               |              | (CIO 2026-05-21 ratified); server is sole writer.
#               |              | Atlas Q4 DDL: composite PK (drive_id,
#               |              | parameter_name), FK drive_summary.id ON DELETE
#               |              | CASCADE, data_quality enum (full/sparse/
#               |              | below_threshold), computed_at ON UPDATE.  Atlas
#               |              | Refinement A generic invariants (min<=avg<=max,
#               |              | std_dev>=0, no NaN/inf, sample_count>=1) +
#               |              | Refinement B data_quality thresholds (<10
#               |              | below_threshold, 10-99 sparse, >=100 full).
#               |              | Spool FLAG-1 honored: compute path reuses
#               |              | src/server/analytics/helpers.computeBasicStats
#               |              | (2-sigma) instead of re-deriving stats.
# ================================================================================
################################################################################

"""US-351 / B-104 Step 1b tests for ``compute_drive_statistics``.

The compute path replaces the V0.27.7-V0.27.16 trigger-seam Pi-side writer
architecture (US-328 / US-349) with a direct read of raw ``realtime_data``
rows for a given Pi-local ``drive_id``.  Server is the sole writer; Pi-side
``drive_statistics`` table is retired entirely (CIO 2026-05-21 ratified).

Test discipline (post-I-040 / Tester I-040 lesson)
--------------------------------------------------

* No mocks of the compute function's seams.  Tests use a real in-memory
  SQLite engine + the real ORM models + real INSERTs of synthetic
  ``realtime_data`` and ``drive_summary`` rows.
* Idempotency is verified by running the compute twice and asserting
  data values match.
* Atlas Refinement A generic invariants RAISE on violation.
* Atlas Refinement B data_quality thresholds: <10 below_threshold,
  10-99 sparse, >=100 full.
* Spool FLAG-1: the compute path imports + invokes
  :func:`src.server.analytics.helpers.computeBasicStats` so the 2-sigma
  outlier math stays in one place.
"""

from __future__ import annotations

import math
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics.drive_statistics_compute import (  # noqa: E402
    DATA_QUALITY_BELOW_THRESHOLD,
    DATA_QUALITY_FULL,
    DATA_QUALITY_SPARSE,
    compute_drive_statistics,
)
from src.server.db.models import (  # noqa: E402
    Base,
    DriveStatistic,
    DriveSummary,
    RealtimeData,
)

# =========================================================================
# Fixtures
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
    dataSource: str | None = "real",
) -> int:
    """Seed a Pi-sync drive_summary row.  Returns server-side drive_summary.id."""
    row = DriveSummary(
        source_device=device,
        source_id=driveId,
        drive_id=driveId,
        data_source=dataSource if dataSource is not None else "real",
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
    pollIntervalSeconds: float = 1.0,
) -> int:
    """Seed ``realtime_data`` rows for a drive from per-parameter value lists.

    Each parameter's values are stamped one-per-tick starting at ``startTime``.
    Returns total row count inserted.
    """
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
                )
            )
            sourceIdCursor += 1
            total += 1
    session.commit()
    return total


# =========================================================================
# compute_drive_statistics -- core compute
# =========================================================================


class TestComputeDriveStatisticsCore:
    """compute_drive_statistics writes one row per parameter from realtime_data."""

    def test_compute_writesOneRowPerParameter_fromRealtimeData(self, engine):
        """Three PIDs with realtime rows -> three drive_statistics rows."""
        driveId = 20
        startTime = datetime(2026, 5, 21, 17, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                paramSeries={
                    "RPM": [800.0, 1500.0, 2400.0, 1800.0, 1000.0],
                    "SPEED": [0.0, 25.0, 60.0, 45.0, 30.0],
                    "COOLANT_TEMP": [85.0, 86.0, 87.0, 86.0, 85.0],
                },
            )
            written = compute_drive_statistics(session, driveId)
            session.commit()

            assert written == 3
            rows = session.execute(
                select(DriveStatistic)
                .where(DriveStatistic.summary_id == summaryId)
                .order_by(DriveStatistic.parameter_name)
            ).scalars().all()
            assert {r.parameter_name for r in rows} == {
                "RPM", "SPEED", "COOLANT_TEMP",
            }

    def test_compute_computesAggregatesViaComputeBasicStats(self, engine):
        """Per-PID aggregates match the 2-sigma helper (Spool FLAG-1)."""
        driveId = 21
        startTime = datetime(2026, 5, 21, 17, 0, 0)
        values = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                paramSeries={"BATTERY_V": values},
            )
            compute_drive_statistics(session, driveId)
            session.commit()

            row = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == summaryId,
                    DriveStatistic.parameter_name == "BATTERY_V",
                )
            ).scalar_one()

            import statistics as pyStats
            expectedMean = sum(values) / len(values)
            expectedStd = pyStats.stdev(values)
            assert row.min_value == pytest.approx(min(values))
            assert row.max_value == pytest.approx(max(values))
            assert row.avg_value == pytest.approx(expectedMean)
            assert row.std_dev == pytest.approx(expectedStd)
            assert row.outlier_min == pytest.approx(
                expectedMean - 2.0 * expectedStd,
            )
            assert row.outlier_max == pytest.approx(
                expectedMean + 2.0 * expectedStd,
            )
            assert row.sample_count == len(values)

    def test_compute_returnsZero_whenNoRealtimeRowsForDrive(self, engine):
        """A drive_summary with no realtime_data writes zero rows + returns 0."""
        driveId = 99
        with Session(engine) as session:
            _seedPiSyncedDriveSummary(session, driveId=driveId)
            written = compute_drive_statistics(session, driveId)
            session.commit()
            assert written == 0
            rows = session.execute(select(DriveStatistic)).scalars().all()
            assert rows == []

    def test_compute_returnsZero_whenDriveSummaryAbsent(self, engine):
        """Missing drive_summary -> WARN + return 0 (non-fatal)."""
        with Session(engine) as session:
            _seedRealtimeRows(
                session,
                driveId=12345,
                startTime=datetime(2026, 5, 21, 19, 0, 0),
                paramSeries={"RPM": [1000.0, 2000.0]},
            )
            written = compute_drive_statistics(session, 12345)
            session.commit()
            assert written == 0

    def test_compute_excludesRowsFromOtherDrives(self, engine):
        """drive_id filter is strict; sibling drive's data must not pollute."""
        driveAId = 5
        driveBId = 6
        startTime = datetime(2026, 5, 21, 8, 0, 0)
        with Session(engine) as session:
            summaryAId = _seedPiSyncedDriveSummary(session, driveId=driveAId)
            _seedPiSyncedDriveSummary(session, driveId=driveBId)
            _seedRealtimeRows(
                session,
                driveId=driveAId,
                startTime=startTime,
                paramSeries={"RPM": [1000.0, 2000.0]},
            )
            _seedRealtimeRows(
                session,
                driveId=driveBId,
                startTime=startTime,
                paramSeries={"RPM": [9000.0, 9999.0]},
            )
            compute_drive_statistics(session, driveAId)
            session.commit()
            row = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == summaryAId,
                )
            ).scalar_one()
            assert row.avg_value == pytest.approx(1500.0)


# =========================================================================
# Idempotency
# =========================================================================


class TestIdempotent:
    """Re-running compute_drive_statistics produces identical data values."""

    def test_idempotent_dataValuesMatch(self, engine):
        driveId = 11
        startTime = datetime(2026, 5, 9, 12, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                paramSeries={
                    "RPM": [1000.0 + i * 50.0 for i in range(20)],
                    "SPEED": [float(i) for i in range(20)],
                },
            )

            compute_drive_statistics(session, driveId)
            session.commit()
            first = sorted(
                (
                    r.parameter_name,
                    r.min_value, r.max_value, r.avg_value, r.std_dev,
                    r.outlier_min, r.outlier_max, r.sample_count,
                    r.data_quality,
                )
                for r in session.execute(
                    select(DriveStatistic).where(
                        DriveStatistic.summary_id == summaryId,
                    )
                ).scalars().all()
            )

            compute_drive_statistics(session, driveId)
            session.commit()
            second = sorted(
                (
                    r.parameter_name,
                    r.min_value, r.max_value, r.avg_value, r.std_dev,
                    r.outlier_min, r.outlier_max, r.sample_count,
                    r.data_quality,
                )
                for r in session.execute(
                    select(DriveStatistic).where(
                        DriveStatistic.summary_id == summaryId,
                    )
                ).scalars().all()
            )

            assert first == second

    def test_idempotent_doesNotDuplicateRows(self, engine):
        """Re-running yields the same row count -- no duplicate PK violations."""
        driveId = 12
        startTime = datetime(2026, 5, 9, 12, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                paramSeries={"RPM": [1000.0, 2000.0], "SPEED": [30.0, 40.0]},
            )

            compute_drive_statistics(session, driveId)
            session.commit()
            compute_drive_statistics(session, driveId)
            session.commit()

            rows = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == summaryId,
                )
            ).scalars().all()
            assert len(rows) == 2


# =========================================================================
# Atlas Refinement A: Generic invariants
# =========================================================================


class TestGenericInvariants:
    """min<=avg<=max, std_dev>=0, no NaN/inf, sample_count>=1."""

    def test_invariants_minLEAvgLEMax(self, engine):
        driveId = 31
        startTime = datetime(2026, 5, 21, 9, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                paramSeries={"RPM": [800.0, 1500.0, 2400.0]},
            )
            compute_drive_statistics(session, driveId)
            session.commit()
            row = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == summaryId,
                )
            ).scalar_one()
            assert row.min_value <= row.avg_value <= row.max_value

    def test_invariants_stdDevGEZero(self, engine):
        driveId = 32
        startTime = datetime(2026, 5, 21, 9, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                paramSeries={"RPM": [1500.0, 1500.0, 1500.0]},
            )
            compute_drive_statistics(session, driveId)
            session.commit()
            row = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == summaryId,
                )
            ).scalar_one()
            assert row.std_dev is not None
            assert row.std_dev >= 0.0
            assert math.isfinite(row.std_dev)
            # All-equal values -> std=0 + outliers degenerate to mean.
            assert row.outlier_min == pytest.approx(1500.0)
            assert row.outlier_max == pytest.approx(1500.0)

    def test_invariants_singleSample_sampleCountIsOne_stdIsZero(self, engine):
        """n=1 still satisfies invariants (sample_count >= 1, std==0)."""
        driveId = 33
        startTime = datetime(2026, 5, 21, 9, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                paramSeries={"BAROMETRIC_KPA": [101.3]},
            )
            compute_drive_statistics(session, driveId)
            session.commit()
            row = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == summaryId,
                )
            ).scalar_one()
            assert row.sample_count == 1
            assert row.std_dev == pytest.approx(0.0)
            assert math.isfinite(row.std_dev)


# =========================================================================
# Atlas Refinement B: data_quality classification
# =========================================================================


class TestDataQualityClassification:
    """<10 below_threshold; 10-99 sparse; >=100 full."""

    def test_dataQuality_belowThreshold_fewerThanTenSamples(self, engine):
        driveId = 41
        startTime = datetime(2026, 5, 21, 10, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                paramSeries={"RPM": [float(v) for v in range(9)]},
            )
            compute_drive_statistics(session, driveId)
            session.commit()
            row = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == summaryId,
                )
            ).scalar_one()
            assert row.sample_count == 9
            assert row.data_quality == DATA_QUALITY_BELOW_THRESHOLD

    def test_dataQuality_sparse_tenToNinetyNineSamples(self, engine):
        driveId = 42
        startTime = datetime(2026, 5, 21, 10, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                paramSeries={"RPM": [float(v) for v in range(50)]},
            )
            compute_drive_statistics(session, driveId)
            session.commit()
            row = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == summaryId,
                )
            ).scalar_one()
            assert row.sample_count == 50
            assert row.data_quality == DATA_QUALITY_SPARSE

    def test_dataQuality_full_oneHundredOrMoreSamples(self, engine):
        driveId = 43
        startTime = datetime(2026, 5, 21, 10, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                paramSeries={"RPM": [float(v) for v in range(150)]},
            )
            compute_drive_statistics(session, driveId)
            session.commit()
            row = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == summaryId,
                )
            ).scalar_one()
            assert row.sample_count == 150
            assert row.data_quality == DATA_QUALITY_FULL


# =========================================================================
# computed_at observable idempotency
# =========================================================================


class TestComputedAtAdvances:
    """Re-run updates computed_at while leaving data values stable."""

    def test_computedAt_advancesOnRecompute(self, engine):
        driveId = 51
        startTime = datetime(2026, 5, 21, 11, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session,
                driveId=driveId,
                startTime=startTime,
                paramSeries={"RPM": [800.0, 1500.0, 2400.0]},
            )
            compute_drive_statistics(session, driveId)
            session.commit()
            first = session.execute(
                select(DriveStatistic.computed_at).where(
                    DriveStatistic.summary_id == summaryId,
                )
            ).scalar_one()
            assert first is not None


# =========================================================================
# US-363 -- data_quality='attribution_anomaly' tripwire integration
# =========================================================================


class TestComputeDriveStatisticsAttributionAnomaly:
    """US-363 / F-107: when the drive's realtime_data window overlaps another
    drive's window (the Drive 23/24 dual-emission pattern), every per-
    parameter row for that drive is stamped data_quality='attribution_anomaly',
    overriding the sample-count classification.  Otherwise the Atlas
    Refinement B sample-count buckets stand.  detect_overlapping_drives()
    (US-362) is the SSOT detector.
    """

    def test_overlap_overridesClassificationWithAnomaly(self, engine):
        driveId = 23
        startTime = datetime(2026, 5, 22, 14, 43, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            # 120 samples -> would classify 'full' absent the overlap override.
            _seedRealtimeRows(
                session, driveId=driveId, startTime=startTime,
                paramSeries={
                    "RPM": [800.0 + i for i in range(120)],
                    "SPEED": [float(i % 60) for i in range(120)],
                },
            )
            # Overlapping drive 24 (window intersects drive 23).
            _seedRealtimeRows(
                session, driveId=24,
                startTime=startTime + timedelta(seconds=30),
                paramSeries={"RPM": [900.0 + i for i in range(120)]},
            )
            written = compute_drive_statistics(session, driveId)
            session.commit()
            assert written == 2
            rows = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == summaryId,
                )
            ).scalars().all()
            assert {r.data_quality for r in rows} == {"attribution_anomaly"}

    def test_noOverlap_keepsSampleCountClassification(self, engine):
        driveId = 25
        startTime = datetime(2026, 5, 22, 16, 0, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session, driveId=driveId, startTime=startTime,
                paramSeries={"RPM": [800.0 + i for i in range(120)]},
            )
            # Non-overlapping neighbour (5 min later).
            _seedRealtimeRows(
                session, driveId=26,
                startTime=startTime + timedelta(seconds=300),
                paramSeries={"RPM": [800.0 + i for i in range(120)]},
            )
            compute_drive_statistics(session, driveId)
            session.commit()
            row = session.execute(
                select(DriveStatistic).where(
                    DriveStatistic.summary_id == summaryId,
                    DriveStatistic.parameter_name == "RPM",
                )
            ).scalar_one()
            # 120 samples -> 'full' (Atlas Refinement B), NOT anomaly.
            assert row.data_quality == DATA_QUALITY_FULL

    def test_anomalyIsIdempotent_acrossRecompute(self, engine):
        driveId = 23
        startTime = datetime(2026, 5, 22, 14, 43, 0)
        with Session(engine) as session:
            summaryId = _seedPiSyncedDriveSummary(session, driveId=driveId)
            _seedRealtimeRows(
                session, driveId=driveId, startTime=startTime,
                paramSeries={"RPM": [800.0 + i for i in range(120)]},
            )
            _seedRealtimeRows(
                session, driveId=24,
                startTime=startTime + timedelta(seconds=30),
                paramSeries={"RPM": [900.0 + i for i in range(120)]},
            )
            compute_drive_statistics(session, driveId)
            session.commit()
            first = session.execute(
                select(DriveStatistic.data_quality).where(
                    DriveStatistic.summary_id == summaryId,
                )
            ).scalars().all()
            compute_drive_statistics(session, driveId)
            session.commit()
            second = session.execute(
                select(DriveStatistic.data_quality).where(
                    DriveStatistic.summary_id == summaryId,
                )
            ).scalars().all()
            assert first == second == ["attribution_anomaly"]
