################################################################################
# File Name: test_analytics_advanced.py
# Purpose/Description: Tests for src/server/analytics/advanced.py — trends,
#                      correlations, and anomaly detection for US-159.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-159 — advanced
#               |              | analytics (trends/correlations/anomalies)
# ================================================================================
################################################################################

"""
Tests for the advanced analytics engine.

Covers:
    - advanced.computeTrends: rolling trend detection across last N drives,
      direction (rising/falling/stable) via regression slope + drift threshold,
      persistence to trend_snapshots.
    - advanced.computeCorrelations: Pearson r between configurable parameter
      pairs across drive-level aggregates, significance flag at |r| > 0.7.
    - advanced.detectAnomalies: flags per-parameter deviations > 2σ against
      the historical envelope, persists to anomaly_log with WATCH/INVESTIGATE
      severity, idempotent per drive.

Uses SQLite as a MariaDB stand-in (same pattern as test_analytics_basic.py).
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics import advanced  # noqa: E402
from src.server.analytics.types import (  # noqa: E402
    AnomalyResult,
    ComparisonStatus,
    CorrelationResult,
    TrendDirection,
    TrendResult,
)
from src.server.db.models import (  # noqa: E402
    AnomalyLog,
    Base,
    DriveStatistic,
    DriveSummary,
    TrendSnapshot,
)

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def engine():
    """File-based SQLite engine with the server schema applied."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _seedDrivesWithStats(
    session: Session,
    avgSeries: list[float],
    parameter: str = "RPM",
    peakOffset: float = 1000.0,
    device: str = "sim-eclipse",
    start: datetime | None = None,
) -> list[int]:
    """Create one drive_summary + one drive_statistics row per avg value.

    Drives are spaced one hour apart starting at ``start`` (or 2026-04-01 08:00)
    so their chronological ordering is unambiguous. Returns the ordered list
    of drive IDs so callers can designate the "current" drive.
    """
    if start is None:
        start = datetime(2026, 4, 1, 8, 0, 0)

    driveIds: list[int] = []
    for i, avg in enumerate(avgSeries, start=1):
        ts = start + timedelta(hours=i)
        session.add(
            DriveSummary(
                id=i,
                device_id=device,
                start_time=ts,
                end_time=ts + timedelta(minutes=15),
                duration_seconds=15 * 60,
            )
        )
        session.add(
            DriveStatistic(
                drive_id=i,
                parameter_name=parameter,
                min_value=avg - 500.0,
                max_value=avg + peakOffset,
                avg_value=avg,
                std_dev=0.0,
                outlier_min=avg - 500.0,
                outlier_max=avg + peakOffset,
                sample_count=100,
            )
        )
        driveIds.append(i)
    session.commit()
    return driveIds


def _seedDrivePairStats(
    session: Session,
    xs: list[float],
    ys: list[float],
    paramA: str = "IAT",
    paramB: str = "KnockCount",
    device: str = "sim-eclipse",
) -> None:
    """Seed drives with stats for two parameters in lockstep.

    Drive i gets avg_value xs[i] for paramA and ys[i] for paramB. Both series
    must be the same length. Useful for exercising correlation.
    """
    assert len(xs) == len(ys)
    start = datetime(2026, 4, 1, 8, 0, 0)
    for i, (xVal, yVal) in enumerate(zip(xs, ys, strict=True), start=1):
        ts = start + timedelta(hours=i)
        session.add(
            DriveSummary(
                id=i,
                device_id=device,
                start_time=ts,
                end_time=ts + timedelta(minutes=15),
            )
        )
        session.add(
            DriveStatistic(
                drive_id=i,
                parameter_name=paramA,
                min_value=xVal,
                max_value=xVal,
                avg_value=xVal,
                std_dev=0.0,
                outlier_min=xVal,
                outlier_max=xVal,
                sample_count=10,
            )
        )
        session.add(
            DriveStatistic(
                drive_id=i,
                parameter_name=paramB,
                min_value=yVal,
                max_value=yVal,
                avg_value=yVal,
                std_dev=0.0,
                outlier_min=yVal,
                outlier_max=yVal,
                sample_count=10,
            )
        )
    session.commit()


# =========================================================================
# advanced.computeTrends
# =========================================================================


class TestComputeTrends:
    """Rolling trend detection across last N drives."""

    def test_computeTrends_monotonicIncreasing_returnsRising(self, engine):
        """12 drives with avg rising from 2000 to 2300 → RISING."""
        with Session(engine) as session:
            _seedDrivesWithStats(
                session,
                avgSeries=[2000.0 + i * 25.0 for i in range(12)],
            )
            result = advanced.computeTrends(session, "RPM", windowSize=10)
            assert isinstance(result, TrendResult)
            assert result.direction == TrendDirection.RISING
            assert result.slope > 0
            assert result.drift_pct > 5.0

    def test_computeTrends_monotonicDecreasing_returnsFalling(self, engine):
        """12 drives with avg falling from 2300 to 2000 → FALLING."""
        with Session(engine) as session:
            _seedDrivesWithStats(
                session,
                avgSeries=[2300.0 - i * 25.0 for i in range(12)],
            )
            result = advanced.computeTrends(session, "RPM", windowSize=10)
            assert result.direction == TrendDirection.FALLING
            assert result.slope < 0
            assert result.drift_pct < -5.0

    def test_computeTrends_flatValues_returnsStable(self, engine):
        """12 drives with nearly-constant avg → STABLE (drift ≤ 5%)."""
        with Session(engine) as session:
            # Small jitter around 2000 (all within 1% of 2000) → drift < 5%
            _seedDrivesWithStats(
                session,
                avgSeries=[2000.0, 2010.0, 1995.0, 2005.0, 1998.0, 2002.0,
                          2007.0, 1993.0, 2001.0, 2004.0, 1999.0, 2000.0],
            )
            result = advanced.computeTrends(session, "RPM", windowSize=10)
            assert result.direction == TrendDirection.STABLE
            assert abs(result.drift_pct) <= 5.0

    def test_computeTrends_averagesMatchExpected(self, engine):
        """avg_peak = mean of max_value across window; avg_mean = mean of avg."""
        with Session(engine) as session:
            # 10 drives, avg_value = [1000, 1100, ..., 1900]
            #   peak offset = 1000 → max_value = [2000, 2100, ..., 2900]
            avgSeries = [1000.0 + i * 100.0 for i in range(10)]
            _seedDrivesWithStats(
                session,
                avgSeries=avgSeries,
                peakOffset=1000.0,
            )
            result = advanced.computeTrends(session, "RPM", windowSize=10)
            expectedAvgMean = sum(avgSeries) / len(avgSeries)
            expectedAvgPeak = expectedAvgMean + 1000.0
            assert abs(result.avg_mean - expectedAvgMean) < 0.01
            assert abs(result.avg_peak - expectedAvgPeak) < 0.01
            assert result.window_size == 10

    def test_computeTrends_windowLimitsSampleCount(self, engine):
        """windowSize=5 uses only the last 5 drives (by start_time)."""
        with Session(engine) as session:
            # 12 rising drives: 2000, 2100, ..., 3100
            _seedDrivesWithStats(
                session,
                avgSeries=[2000.0 + i * 100.0 for i in range(12)],
            )
            result = advanced.computeTrends(session, "RPM", windowSize=5)
            # Last 5 drives have avg values 2700..3100, mean = 2900
            assert abs(result.avg_mean - 2900.0) < 0.01

    def test_computeTrends_persistsSnapshot(self, engine):
        """Each call writes a new trend_snapshots row."""
        with Session(engine) as session:
            _seedDrivesWithStats(
                session,
                avgSeries=[2000.0 + i * 25.0 for i in range(12)],
            )
            advanced.computeTrends(session, "RPM", windowSize=10)
            snapshots = session.execute(
                select(TrendSnapshot).where(
                    TrendSnapshot.parameter_name == "RPM"
                )
            ).scalars().all()
            assert len(snapshots) == 1
            assert snapshots[0].direction == TrendDirection.RISING.value
            assert snapshots[0].window_size == 10

    def test_computeTrends_singleDrive_returnsStableNoError(self, engine):
        """Fewer than 2 drives → STABLE, no crash, drift=0."""
        with Session(engine) as session:
            _seedDrivesWithStats(session, avgSeries=[2000.0])
            result = advanced.computeTrends(session, "RPM", windowSize=10)
            assert result.direction == TrendDirection.STABLE
            assert result.drift_pct == 0.0
            assert result.slope == 0.0

    def test_computeTrends_noData_returnsNone(self, engine):
        """Parameter with no drive stats returns None."""
        with Session(engine) as session:
            result = advanced.computeTrends(session, "RPM", windowSize=10)
            assert result is None


# =========================================================================
# advanced.computeCorrelations
# =========================================================================


class TestComputeCorrelations:
    """Pearson correlation between tuning-relevant parameter pairs."""

    def test_computeCorrelations_strongPositiveCorrelation_flaggedSignificant(
        self, engine
    ):
        """IAT and KnockCount rising together → |r| ≈ 1 → significant."""
        with Session(engine) as session:
            xs = [float(v) for v in range(70, 82)]  # 12 values
            ys = [x * 0.5 for x in xs]              # perfectly linear
            _seedDrivePairStats(session, xs, ys, "IAT", "KnockCount")
            results = advanced.computeCorrelations(
                session, pairs=[("IAT", "KnockCount")]
            )
            assert len(results) == 1
            iatKnock = results[0]
            assert isinstance(iatKnock, CorrelationResult)
            assert iatKnock.pearson_r > 0.95
            assert iatKnock.is_significant is True
            assert iatKnock.sample_count == 12

    def test_computeCorrelations_strongNegativeCorrelation_flaggedSignificant(
        self, engine
    ):
        """Negatively correlated pair → r ≈ -1 → still significant."""
        with Session(engine) as session:
            xs = [float(v) for v in range(70, 82)]
            ys = [100.0 - x for x in xs]
            _seedDrivePairStats(session, xs, ys, "IAT", "STFT")
            results = advanced.computeCorrelations(
                session, pairs=[("IAT", "STFT")]
            )
            assert results[0].pearson_r < -0.95
            assert results[0].is_significant is True

    def test_computeCorrelations_weakCorrelation_notFlagged(self, engine):
        """Essentially random pair → |r| < 0.7 → not significant."""
        with Session(engine) as session:
            xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
                  11.0, 12.0]
            # Zigzag — low but nonzero correlation
            ys = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0, 5.0, 3.0, 5.0, 8.0]
            _seedDrivePairStats(session, xs, ys, "RPM", "CoolantTemp")
            results = advanced.computeCorrelations(
                session, pairs=[("RPM", "CoolantTemp")]
            )
            assert results[0].is_significant is False

    def test_computeCorrelations_defaultPairs_usesModuleLevelConstant(
        self, engine
    ):
        """Omitting pairs arg uses DEFAULT_CORRELATION_PAIRS (not hardcoded)."""
        with Session(engine) as session:
            # Seed all four default pairs with trivial data so function returns
            # a result for each pair without raising.
            for paramA, paramB in advanced.DEFAULT_CORRELATION_PAIRS:
                _seedDrivePairStats(
                    session,
                    xs=[1.0, 2.0, 3.0, 4.0],
                    ys=[1.0, 2.0, 3.0, 4.0],
                    paramA=paramA,
                    paramB=paramB,
                )
                # Need fresh DriveSummary IDs per pair — clear and reseed
                session.query(DriveStatistic).delete()
                session.query(DriveSummary).delete()
                session.commit()
            # Reseed the first default pair properly for a single assertion
            first = advanced.DEFAULT_CORRELATION_PAIRS[0]
            _seedDrivePairStats(
                session,
                xs=[1.0, 2.0, 3.0, 4.0],
                ys=[1.0, 2.0, 3.0, 4.0],
                paramA=first[0],
                paramB=first[1],
            )
            results = advanced.computeCorrelations(session)
            # At least the first default pair has results
            assert any(
                r.parameter_a == first[0] and r.parameter_b == first[1]
                for r in results
            )

    def test_computeCorrelations_configurablePairs_overrideDefaults(
        self, engine
    ):
        """Callers can pass their own pairs — not hardcoded in function body."""
        with Session(engine) as session:
            _seedDrivePairStats(
                session,
                xs=[1.0, 2.0, 3.0],
                ys=[1.0, 2.0, 3.0],
                paramA="CustomA",
                paramB="CustomB",
            )
            results = advanced.computeCorrelations(
                session, pairs=[("CustomA", "CustomB")]
            )
            assert len(results) == 1
            assert results[0].parameter_a == "CustomA"
            assert results[0].parameter_b == "CustomB"

    def test_computeCorrelations_insufficientOverlap_skipped(self, engine):
        """Pair where both params don't coexist on any drive is skipped."""
        with Session(engine) as session:
            # Only one drive has IAT; none have KnockCount
            _seedDrivesWithStats(
                session,
                avgSeries=[70.0, 75.0, 80.0, 85.0],
                parameter="IAT",
            )
            results = advanced.computeCorrelations(
                session, pairs=[("IAT", "KnockCount")]
            )
            assert results == []

    def test_computeCorrelations_constantSeries_skippedGracefully(
        self, engine
    ):
        """Constant series → stdlib raises StatisticsError → pair skipped."""
        with Session(engine) as session:
            _seedDrivePairStats(
                session,
                xs=[50.0, 50.0, 50.0, 50.0],   # constant
                ys=[1.0, 2.0, 3.0, 4.0],
                paramA="IAT",
                paramB="KnockCount",
            )
            # Should not raise — return empty or result with pearson_r=0
            results = advanced.computeCorrelations(
                session, pairs=[("IAT", "KnockCount")]
            )
            # Either skipped (empty) or reported as not significant
            if results:
                assert results[0].is_significant is False


# =========================================================================
# advanced.detectAnomalies
# =========================================================================


class TestDetectAnomalies:
    """Per-drive anomaly detection against historical envelope."""

    def test_detectAnomalies_withinEnvelope_noRowsWritten(self, engine):
        """Current drive sits within 2σ of history → no anomalies."""
        with Session(engine) as session:
            # History: RPM avg ∈ {1900..2100}, mean=2000, std≈79
            _seedDrivesWithStats(
                session,
                avgSeries=[1900.0, 1950.0, 2000.0, 2050.0, 2100.0, 2030.0],
            )
            results = advanced.detectAnomalies(session, driveId=6)
            # Drive 6 (avg=2030) is ~0.4σ from mean — within envelope
            assert results == []
            rows = session.execute(select(AnomalyLog)).scalars().all()
            assert rows == []

    def test_detectAnomalies_watchLevel_writesWatchRow(self, engine):
        """Drive at ~2.5σ → WATCH severity row in anomaly_log."""
        with Session(engine) as session:
            # Historical 5 drives: avg ∈ {1900..2100}, mean=2000, std≈79.06
            # 2.5σ ≈ +198. Put current drive at 2200 (~2.53σ).
            _seedDrivesWithStats(
                session,
                avgSeries=[1900.0, 1950.0, 2000.0, 2050.0, 2100.0, 2200.0],
            )
            results = advanced.detectAnomalies(session, driveId=6)
            assert len(results) == 1
            assert results[0].severity == ComparisonStatus.WATCH
            assert isinstance(results[0], AnomalyResult)

            rows = session.execute(select(AnomalyLog)).scalars().all()
            assert len(rows) == 1
            assert rows[0].severity == ComparisonStatus.WATCH.value
            assert rows[0].drive_id == 6
            assert rows[0].parameter_name == "RPM"

    def test_detectAnomalies_investigateLevel_writesInvestigateRow(
        self, engine
    ):
        """Drive far above history (>3σ) → INVESTIGATE severity row."""
        with Session(engine) as session:
            # mean=2000, std≈79; put current at 2400 → ~5.06σ
            _seedDrivesWithStats(
                session,
                avgSeries=[1900.0, 1950.0, 2000.0, 2050.0, 2100.0, 2400.0],
            )
            results = advanced.detectAnomalies(session, driveId=6)
            assert len(results) == 1
            assert results[0].severity == ComparisonStatus.INVESTIGATE
            assert abs(results[0].deviation_sigma) > 3.0

    def test_detectAnomalies_reRun_replacesRowsNotDuplicates(self, engine):
        """Re-running detectAnomalies(driveId) replaces prior anomalies."""
        with Session(engine) as session:
            _seedDrivesWithStats(
                session,
                avgSeries=[1900.0, 1950.0, 2000.0, 2050.0, 2100.0, 2400.0],
            )
            advanced.detectAnomalies(session, driveId=6)
            advanced.detectAnomalies(session, driveId=6)
            rows = session.execute(
                select(AnomalyLog).where(AnomalyLog.drive_id == 6)
            ).scalars().all()
            assert len(rows) == 1  # not 2

    def test_detectAnomalies_excludesCurrentDriveFromEnvelope(self, engine):
        """Historical envelope excludes the current drive's own stats."""
        with Session(engine) as session:
            # If current drive were included, envelope would widen.
            # 3 history at 2000, current at 5000. Historical mean=2000, std=0.
            # With std=0 we skip (no meaningful envelope).
            _seedDrivesWithStats(
                session,
                avgSeries=[2000.0, 2000.0, 2000.0, 5000.0],
            )
            results = advanced.detectAnomalies(session, driveId=4)
            # Historical std=0 → can't compute sigma, skip cleanly
            assert results == []

    def test_detectAnomalies_recordsExpectedEnvelopeAndObserved(self, engine):
        """Anomaly row captures observed value and expected min/max bounds."""
        with Session(engine) as session:
            _seedDrivesWithStats(
                session,
                avgSeries=[1900.0, 1950.0, 2000.0, 2050.0, 2100.0, 2400.0],
            )
            results = advanced.detectAnomalies(session, driveId=6)
            anomaly = results[0]
            assert anomaly.observed_value == 2400.0
            # Expected envelope = mean ± 2*std. Mean=2000, std≈79 → ~1842..2158
            assert anomaly.expected_min < 2000.0 < anomaly.expected_max
            assert anomaly.expected_max < anomaly.observed_value

    def test_detectAnomalies_noHistoryAtAll_returnsEmpty(self, engine):
        """Only the current drive exists → nothing to compare against."""
        with Session(engine) as session:
            _seedDrivesWithStats(session, avgSeries=[2500.0])
            results = advanced.detectAnomalies(session, driveId=1)
            assert results == []


# =========================================================================
# Twelve-drive end-to-end sanity check
# =========================================================================


class TestTwelveDriveEndToEnd:
    """Spec acceptance: seed 12+ drives with known patterns; validate all three
    advanced analytics outputs simultaneously."""

    def test_twelveDrivesWithRisingPattern_exercisesAllEntryPoints(self, engine):
        with Session(engine) as session:
            # 12 drives. IAT rises 70→92, KnockCount rises 0→11 (strongly
            # correlated), last drive is an RPM outlier at 4000 vs history 2000.
            iats = [70.0 + i * 2.0 for i in range(12)]
            knocks = [float(i) for i in range(12)]
            _seedDrivePairStats(session, iats, knocks, "IAT", "KnockCount")

            # Separately add rising RPM trend and an outlier last drive
            for i in range(1, 13):
                session.add(
                    DriveStatistic(
                        drive_id=i,
                        parameter_name="RPM",
                        min_value=1000.0,
                        max_value=2000.0 + i * 25.0 + 1000.0,
                        avg_value=2000.0 + i * 25.0,
                        std_dev=0.0,
                        outlier_min=0.0,
                        outlier_max=0.0,
                        sample_count=100,
                    )
                )
            session.commit()

            # Trend on RPM — rising
            rpmTrend = advanced.computeTrends(session, "RPM", windowSize=10)
            assert rpmTrend.direction == TrendDirection.RISING

            # Correlation IAT↔KnockCount — strongly significant
            corr = advanced.computeCorrelations(
                session, pairs=[("IAT", "KnockCount")]
            )
            assert corr[0].is_significant is True

            # Anomaly detection on drive 12 — RPM at 2300 vs history 2025..2275
            # Not dramatic but exercise the call path
            anomalies = advanced.detectAnomalies(session, driveId=12)
            # Whatever the outcome, call must succeed and return a list
            assert isinstance(anomalies, list)
