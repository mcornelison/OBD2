################################################################################
# File Name: test_analytics_basic.py
# Purpose/Description: Tests for src/server/analytics/basic.py and helpers —
#                      per-drive statistics and historical comparison for US-158.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-158 — basic analytics
# ================================================================================
################################################################################

"""
Tests for the basic analytics engine.

Covers:
    - helpers.computeBasicStats: min/max/avg/std/outlier bounds/count
    - helpers.classifyDeviation: NORMAL/WATCH/INVESTIGATE boundaries
    - basic.computeDriveStatistics: queries realtime_data for a drive's window,
      writes per-parameter stats to drive_statistics, idempotent on re-run
    - basic.compareDriveToHistory: flags parameters whose avg or peak deviates
      from historical aggregates by > 2σ

Uses SQLite as a MariaDB stand-in (same pattern as test_load_data.py).
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics import basic, helpers  # noqa: E402
from src.server.analytics.types import (  # noqa: E402
    ComparisonStatus,
    DriveStatistics,
    ParameterComparison,
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
    """In-memory SQLite engine with server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _seedDrive(
    session: Session,
    driveId: int,
    device: str,
    start: datetime,
    end: datetime,
    readings: list[tuple[str, float, datetime]],
) -> None:
    """Insert a drive_summary row and associated realtime_data rows."""
    session.add(
        DriveSummary(
            id=driveId,
            device_id=device,
            start_time=start,
            end_time=end,
            duration_seconds=int((end - start).total_seconds()),
            row_count=len(readings),
        )
    )
    for i, (param, value, ts) in enumerate(readings):
        session.add(
            RealtimeData(
                source_id=driveId * 10_000 + i,
                source_device=device,
                timestamp=ts,
                parameter_name=param,
                value=value,
            )
        )
    session.commit()


# =========================================================================
# helpers.computeBasicStats
# =========================================================================


class TestComputeBasicStats:
    """Pure-math helper that computes min/max/avg/std/outlier bounds."""

    def test_computeBasicStats_fiveValues_returnsCorrectStats(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        stats = helpers.computeBasicStats(values)
        assert stats.min_value == 10.0
        assert stats.max_value == 50.0
        assert stats.avg_value == 30.0
        assert stats.sample_count == 5
        # Sample std of [10,20,30,40,50] = sqrt(250) ≈ 15.811
        assert abs(stats.std_dev - 15.811) < 0.01

    def test_computeBasicStats_fiveValues_outlierBoundsAreMeanPlusMinus2Std(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        stats = helpers.computeBasicStats(values)
        assert abs(stats.outlier_min - (30.0 - 2 * 15.811)) < 0.01
        assert abs(stats.outlier_max - (30.0 + 2 * 15.811)) < 0.01

    def test_computeBasicStats_singleValue_stdDevIsZero(self):
        stats = helpers.computeBasicStats([42.0])
        assert stats.min_value == 42.0
        assert stats.max_value == 42.0
        assert stats.avg_value == 42.0
        assert stats.std_dev == 0.0
        assert stats.outlier_min == 42.0
        assert stats.outlier_max == 42.0
        assert stats.sample_count == 1

    def test_computeBasicStats_emptyValues_returnsNone(self):
        assert helpers.computeBasicStats([]) is None


# =========================================================================
# helpers.classifyDeviation
# =========================================================================


class TestClassifyDeviation:
    """Map sigma magnitude to ComparisonStatus per spec §1.7/§1.8."""

    @pytest.mark.parametrize(
        "sigma, expected",
        [
            (0.0, ComparisonStatus.NORMAL),
            (1.5, ComparisonStatus.NORMAL),
            (-1.5, ComparisonStatus.NORMAL),
            (2.0, ComparisonStatus.NORMAL),       # boundary: ≤ 2 is NORMAL
            (2.01, ComparisonStatus.WATCH),       # just over 2
            (2.5, ComparisonStatus.WATCH),
            (-2.5, ComparisonStatus.WATCH),
            (3.0, ComparisonStatus.WATCH),        # boundary: ≤ 3 is WATCH
            (3.01, ComparisonStatus.INVESTIGATE),  # just over 3
            (5.0, ComparisonStatus.INVESTIGATE),
            (-5.0, ComparisonStatus.INVESTIGATE),
        ],
    )
    def test_classifyDeviation_sigmaBoundaries_returnsExpectedStatus(
        self, sigma, expected
    ):
        assert helpers.classifyDeviation(sigma) == expected


# =========================================================================
# basic.computeDriveStatistics
# =========================================================================


class TestComputeDriveStatistics:
    """Compute per-parameter stats for a drive and persist to drive_statistics."""

    def test_computeDriveStatistics_singleDriveTwoParameters_createsOneRowPerParameter(
        self, engine
    ):
        with Session(engine) as session:
            _seedDrive(
                session,
                driveId=1,
                device="sim-eclipse",
                start=datetime(2026, 4, 16, 8, 0, 0),
                end=datetime(2026, 4, 16, 8, 10, 0),
                readings=[
                    ("RPM", 1000.0, datetime(2026, 4, 16, 8, 1, 0)),
                    ("RPM", 2000.0, datetime(2026, 4, 16, 8, 2, 0)),
                    ("RPM", 3000.0, datetime(2026, 4, 16, 8, 3, 0)),
                    ("SPEED", 30.0, datetime(2026, 4, 16, 8, 4, 0)),
                    ("SPEED", 60.0, datetime(2026, 4, 16, 8, 5, 0)),
                ],
            )
            stats = basic.computeDriveStatistics(session, 1)
            assert len(stats) == 2
            names = sorted(s.parameter_name for s in stats)
            assert names == ["RPM", "SPEED"]

            # Verify persistence
            rows = session.execute(
                select(DriveStatistic).where(DriveStatistic.drive_id == 1)
            ).scalars().all()
            assert len(rows) == 2

    def test_computeDriveStatistics_rpmValues_avgMatchesInput(self, engine):
        with Session(engine) as session:
            _seedDrive(
                session,
                driveId=1,
                device="sim-eclipse",
                start=datetime(2026, 4, 16, 8, 0, 0),
                end=datetime(2026, 4, 16, 8, 10, 0),
                readings=[
                    ("RPM", 1000.0, datetime(2026, 4, 16, 8, 1, 0)),
                    ("RPM", 2000.0, datetime(2026, 4, 16, 8, 2, 0)),
                    ("RPM", 3000.0, datetime(2026, 4, 16, 8, 3, 0)),
                ],
            )
            stats = basic.computeDriveStatistics(session, 1)
            rpm = next(s for s in stats if s.parameter_name == "RPM")
            assert rpm.min_value == 1000.0
            assert rpm.max_value == 3000.0
            assert rpm.avg_value == 2000.0
            assert rpm.sample_count == 3

    def test_computeDriveStatistics_reRunSameDrive_replacesRowsNotDuplicates(
        self, engine
    ):
        with Session(engine) as session:
            _seedDrive(
                session,
                driveId=1,
                device="sim-eclipse",
                start=datetime(2026, 4, 16, 8, 0, 0),
                end=datetime(2026, 4, 16, 8, 10, 0),
                readings=[
                    ("RPM", 1000.0, datetime(2026, 4, 16, 8, 1, 0)),
                    ("RPM", 2000.0, datetime(2026, 4, 16, 8, 2, 0)),
                ],
            )
            basic.computeDriveStatistics(session, 1)
            basic.computeDriveStatistics(session, 1)
            rows = session.execute(
                select(DriveStatistic).where(DriveStatistic.drive_id == 1)
            ).scalars().all()
            assert len(rows) == 1  # RPM only — no duplicates

    def test_computeDriveStatistics_filtersByDriveTimeWindow(self, engine):
        """Readings outside [start_time, end_time] must be excluded."""
        with Session(engine) as session:
            session.add(
                DriveSummary(
                    id=1,
                    device_id="sim-eclipse",
                    start_time=datetime(2026, 4, 16, 8, 0, 0),
                    end_time=datetime(2026, 4, 16, 8, 10, 0),
                )
            )
            # In-window readings
            session.add_all([
                RealtimeData(
                    source_id=1,
                    source_device="sim-eclipse",
                    timestamp=datetime(2026, 4, 16, 8, 1, 0),
                    parameter_name="RPM",
                    value=1000.0,
                ),
                RealtimeData(
                    source_id=2,
                    source_device="sim-eclipse",
                    timestamp=datetime(2026, 4, 16, 8, 5, 0),
                    parameter_name="RPM",
                    value=2000.0,
                ),
            ])
            # Out-of-window reading — must be excluded
            session.add(
                RealtimeData(
                    source_id=3,
                    source_device="sim-eclipse",
                    timestamp=datetime(2026, 4, 16, 9, 0, 0),  # after end
                    parameter_name="RPM",
                    value=9999.0,
                )
            )
            session.commit()

            stats = basic.computeDriveStatistics(session, 1)
            rpm = next(s for s in stats if s.parameter_name == "RPM")
            assert rpm.max_value == 2000.0  # 9999.0 excluded

    def test_computeDriveStatistics_filtersByDeviceId(self, engine):
        """Readings from other devices must not be included."""
        with Session(engine) as session:
            session.add(
                DriveSummary(
                    id=1,
                    device_id="sim-eclipse",
                    start_time=datetime(2026, 4, 16, 8, 0, 0),
                    end_time=datetime(2026, 4, 16, 8, 10, 0),
                )
            )
            session.add_all([
                RealtimeData(
                    source_id=1,
                    source_device="sim-eclipse",
                    timestamp=datetime(2026, 4, 16, 8, 1, 0),
                    parameter_name="RPM",
                    value=1000.0,
                ),
                # Same time window, different device
                RealtimeData(
                    source_id=2,
                    source_device="other-device",
                    timestamp=datetime(2026, 4, 16, 8, 2, 0),
                    parameter_name="RPM",
                    value=9999.0,
                ),
            ])
            session.commit()

            stats = basic.computeDriveStatistics(session, 1)
            rpm = next(s for s in stats if s.parameter_name == "RPM")
            assert rpm.max_value == 1000.0  # other-device excluded

    def test_computeDriveStatistics_unknownDrive_raisesValueError(self, engine):
        with Session(engine) as session:
            with pytest.raises(ValueError, match="no drive_summary"):
                basic.computeDriveStatistics(session, 999)


# =========================================================================
# basic.compareDriveToHistory
# =========================================================================


def _insertDriveStat(
    session: Session,
    driveId: int,
    param: str,
    avg: float,
    peak: float,
    sampleCount: int = 100,
) -> None:
    session.add(
        DriveStatistic(
            drive_id=driveId,
            parameter_name=param,
            min_value=0.0,
            max_value=peak,
            avg_value=avg,
            std_dev=0.0,
            outlier_min=0.0,
            outlier_max=peak,
            sample_count=sampleCount,
        )
    )


class TestCompareDriveToHistory:
    """Compare a drive's stats to historical aggregates across prior drives."""

    def test_compareDriveToHistory_noPriorDrives_returnsEmptyList(self, engine):
        with Session(engine) as session:
            _insertDriveStat(session, 1, "RPM", avg=2000.0, peak=3000.0)
            session.commit()
            comparisons = basic.compareDriveToHistory(session, 1)
            assert comparisons == []

    def test_compareDriveToHistory_withinTwoSigma_returnsNormal(self, engine):
        """Current avg close to historical mean → NORMAL status."""
        with Session(engine) as session:
            # Historical: 5 drives, avg RPM ∈ {1900, 1950, 2000, 2050, 2100}
            # mean=2000, std ≈ 79.06
            for i, avg in enumerate([1900.0, 1950.0, 2000.0, 2050.0, 2100.0], start=1):
                _insertDriveStat(session, i, "RPM", avg=avg, peak=avg + 1000)
            # Current drive: within 1σ of mean
            _insertDriveStat(session, 100, "RPM", avg=2050.0, peak=3050.0)
            session.commit()

            comparisons = basic.compareDriveToHistory(session, 100)
            rpm = next(c for c in comparisons if c.parameter_name == "RPM")
            assert rpm.status == ComparisonStatus.NORMAL

    def test_compareDriveToHistory_outsideTwoSigma_returnsWatch(self, engine):
        """Current avg ~2.5σ from historical → WATCH status."""
        with Session(engine) as session:
            # Historical: 5 drives, avg RPM ∈ {1900, 1950, 2000, 2050, 2100}
            # mean=2000, sample std ≈ 79.06; 2.5σ ≈ 197.6; put current at mean+200
            for i, avg in enumerate([1900.0, 1950.0, 2000.0, 2050.0, 2100.0], start=1):
                _insertDriveStat(session, i, "RPM", avg=avg, peak=avg + 1000)
            _insertDriveStat(session, 100, "RPM", avg=2200.0, peak=3200.0)
            session.commit()

            comparisons = basic.compareDriveToHistory(session, 100)
            rpm = next(c for c in comparisons if c.parameter_name == "RPM")
            assert rpm.status == ComparisonStatus.WATCH

    def test_compareDriveToHistory_outsideThreeSigma_returnsInvestigate(self, engine):
        """Current avg > 3σ from historical → INVESTIGATE status."""
        with Session(engine) as session:
            for i, avg in enumerate([1900.0, 1950.0, 2000.0, 2050.0, 2100.0], start=1):
                _insertDriveStat(session, i, "RPM", avg=avg, peak=avg + 1000)
            # Put current far above: mean=2000, std≈79, 3σ≈237; use +400 → ~5σ
            _insertDriveStat(session, 100, "RPM", avg=2400.0, peak=3400.0)
            session.commit()

            comparisons = basic.compareDriveToHistory(session, 100)
            rpm = next(c for c in comparisons if c.parameter_name == "RPM")
            assert rpm.status == ComparisonStatus.INVESTIGATE
            assert abs(rpm.deviation_sigma) > 3.0

    def test_compareDriveToHistory_excludesCurrentDriveFromHistorical(self, engine):
        """Historical aggregates must exclude the current drive's own stats."""
        with Session(engine) as session:
            _insertDriveStat(session, 1, "RPM", avg=2000.0, peak=3000.0)
            _insertDriveStat(session, 2, "RPM", avg=2000.0, peak=3000.0)
            # Current drive has wildly different value but is excluded from history
            _insertDriveStat(session, 3, "RPM", avg=5000.0, peak=6000.0)
            session.commit()

            comparisons = basic.compareDriveToHistory(session, 3)
            rpm = next(c for c in comparisons if c.parameter_name == "RPM")
            assert rpm.historical_mean_avg == 2000.0

    def test_compareDriveToHistory_singleHistoricalDrive_returnsNormalForZeroStd(
        self, engine
    ):
        """One historical drive → std is 0; differing current drive handled gracefully."""
        with Session(engine) as session:
            _insertDriveStat(session, 1, "RPM", avg=2000.0, peak=3000.0)
            _insertDriveStat(session, 2, "RPM", avg=2500.0, peak=3500.0)
            session.commit()
            # With only 1 historical drive, std is undefined → deviation_sigma=0, NORMAL
            comparisons = basic.compareDriveToHistory(session, 2)
            rpm = next(c for c in comparisons if c.parameter_name == "RPM")
            assert rpm.status == ComparisonStatus.NORMAL


# =========================================================================
# types
# =========================================================================


class TestTypes:
    """Sanity checks for the dataclasses declared in types.py."""

    def test_driveStatistics_isFrozen(self):
        stats = DriveStatistics(
            drive_id=1,
            parameter_name="RPM",
            min_value=0.0,
            max_value=0.0,
            avg_value=0.0,
            std_dev=0.0,
            outlier_min=0.0,
            outlier_max=0.0,
            sample_count=0,
        )
        with pytest.raises(Exception):
            stats.drive_id = 2  # type: ignore[misc]

    def test_parameterComparison_statusIsEnum(self):
        comparison = ParameterComparison(
            parameter_name="RPM",
            current_avg=2000.0,
            current_max=3000.0,
            historical_mean_avg=1950.0,
            historical_std_avg=50.0,
            deviation_sigma=1.0,
            status=ComparisonStatus.NORMAL,
        )
        assert comparison.status is ComparisonStatus.NORMAL
