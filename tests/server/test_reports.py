################################################################################
# File Name: test_reports.py
# Purpose/Description: Tests for src/server/reports/ and scripts/report.py —
#                      drive and trend report formatters, orchestrators, and
#                      CLI dispatch for US-160.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-160 — CLI reports
# ================================================================================
################################################################################

"""
Tests for the CLI report tool.

Coverage:
    * Pure formatters (no DB): formatDriveReport, formatAllDrivesTable,
      formatTrendReport, trendArrow, classifyTrendSignificance.
    * Orchestrators (SQLite as MariaDB stand-in): buildDriveReport,
      buildAllDrivesReport, buildTrendReport.
    * CLI: parseArguments, renderReport, main().
"""

from __future__ import annotations

import io
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scripts import report as report_cli  # noqa: E402
from src.server.analytics import basic  # noqa: E402
from src.server.analytics.types import (  # noqa: E402
    ComparisonStatus,
    CorrelationResult,
    DriveStatistics,
    ParameterComparison,
    TrendDirection,
    TrendResult,
)
from src.server.db.models import (  # noqa: E402
    Base,
    DriveStatistic,
    DriveSummary,
    RealtimeData,
)
from src.server.reports import (  # noqa: E402
    buildAllDrivesReport,
    buildDriveReport,
    buildTrendReport,
    classifyTrendSignificance,
    drive_report,
    formatAllDrivesTable,
    formatDriveReport,
    formatTrendReport,
    trend_report,
    trendArrow,
)

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def engine():
    """File-backed SQLite engine with the full server schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    Path(tmp.name).unlink(missing_ok=True)


def _makeDriveSummary(
    driveId: int,
    device: str = "sim-eclipse-gst",
    start: datetime | None = None,
    durationMinutes: int = 17,
    profile: str | None = "Daily",
    rowCount: int = 2500,
) -> DriveSummary:
    """Build a detached ``DriveSummary`` fixture for pure-formatter tests."""
    startTime = start or datetime(2026, 4, 15, 14, 30, 0)
    return DriveSummary(
        id=driveId,
        device_id=device,
        start_time=startTime,
        end_time=startTime + timedelta(minutes=durationMinutes),
        duration_seconds=durationMinutes * 60,
        profile_id=profile,
        row_count=rowCount,
    )


def _makeStats(
    paramName: str,
    minV: float,
    maxV: float,
    avg: float,
    std: float,
    driveId: int = 1,
) -> DriveStatistics:
    return DriveStatistics(
        drive_id=driveId,
        parameter_name=paramName,
        min_value=minV,
        max_value=maxV,
        avg_value=avg,
        std_dev=std,
        outlier_min=avg - 2 * std,
        outlier_max=avg + 2 * std,
        sample_count=200,
    )


def _makeComparison(
    paramName: str,
    sigma: float,
    status: ComparisonStatus,
    currentAvg: float = 100.0,
    historicalMean: float = 90.0,
) -> ParameterComparison:
    return ParameterComparison(
        parameter_name=paramName,
        current_avg=currentAvg,
        current_max=currentAvg + 20,
        historical_mean_avg=historicalMean,
        historical_std_avg=4.0,
        deviation_sigma=sigma,
        status=status,
    )


def _seedDriveWithStats(
    session: Session,
    driveId: int,
    startTime: datetime,
    device: str,
    stats: dict[str, tuple[float, float, float, float]],
    profile: str | None = "Daily",
) -> None:
    """Seed a DriveSummary + DriveStatistic rows.

    stats dict: ``{param: (min, max, avg, std)}``.
    """
    session.add(
        DriveSummary(
            id=driveId,
            device_id=device,
            start_time=startTime,
            end_time=startTime + timedelta(minutes=15),
            duration_seconds=15 * 60,
            profile_id=profile,
            row_count=1000,
        ),
    )
    for name, (minV, maxV, avg, std) in stats.items():
        session.add(
            DriveStatistic(
                drive_id=driveId,
                parameter_name=name,
                min_value=minV,
                max_value=maxV,
                avg_value=avg,
                std_dev=std,
                outlier_min=avg - 2 * std,
                outlier_max=avg + 2 * std,
                sample_count=100,
            ),
        )


def _seedDriveForAnalytics(
    session: Session,
    driveId: int,
    startTime: datetime,
    device: str,
    readings: list[tuple[str, float]],
    profile: str | None = "Daily",
) -> None:
    """Seed a DriveSummary + realtime_data rows so basic.computeDriveStatistics can be run."""
    endTime = startTime + timedelta(minutes=10)
    session.add(
        DriveSummary(
            id=driveId,
            device_id=device,
            start_time=startTime,
            end_time=endTime,
            duration_seconds=600,
            profile_id=profile,
            row_count=len(readings),
        ),
    )
    for i, (param, value) in enumerate(readings):
        ts = startTime + timedelta(seconds=i)
        session.add(
            RealtimeData(
                source_id=driveId * 10_000 + i,
                source_device=device,
                timestamp=ts,
                parameter_name=param,
                value=value,
            ),
        )


# =========================================================================
# Pure formatter: formatDriveReport
# =========================================================================


class TestFormatDriveReport:
    """Pure formatter — no DB involvement."""

    def test_containsHeaderBorderAndDateTime(self):
        drive = _makeDriveSummary(1)
        report = formatDriveReport(drive, stats=[], comparisons=[], historicalDriveCount=0)

        assert "═" * 10 in report  # double-border present
        assert "Drive Report" in report
        assert "2026-04-15 14:30" in report
        assert "17 min" in report
        assert "Device: sim-eclipse-gst" in report
        assert "Profile: Daily" in report

    def test_rendersParameterRowsInOrder(self):
        drive = _makeDriveSummary(1)
        stats = [
            _makeStats("RPM", 850, 5200, 2340, 680.2),
            _makeStats("Coolant", 145, 198, 187, 8.1),
            _makeStats("IAT", 72, 118, 94, 12.3),
        ]
        report = formatDriveReport(drive, stats, comparisons=[], historicalDriveCount=0)

        rpmIdx = report.index("RPM")
        coolantIdx = report.index("Coolant")
        iatIdx = report.index("IAT")
        assert rpmIdx < coolantIdx < iatIdx
        # Sanity: values show up somewhere in the row.
        assert "5200" in report
        assert "187" in report

    def test_statusColumnReflectsComparison(self):
        drive = _makeDriveSummary(1)
        stats = [
            _makeStats("RPM", 850, 5200, 2340, 680.2),
            _makeStats("IAT", 72, 118, 94, 12.3),
        ]
        comparisons = [
            _makeComparison("RPM", sigma=0.5, status=ComparisonStatus.NORMAL),
            _makeComparison("IAT", sigma=2.4, status=ComparisonStatus.WATCH),
        ]
        report = formatDriveReport(drive, stats, comparisons, historicalDriveCount=12)

        assert "NORMAL" in report
        assert "WATCH" in report

    def test_historicalComparisonShowsDriveCount(self):
        drive = _makeDriveSummary(1)
        report = formatDriveReport(
            drive,
            stats=[_makeStats("RPM", 850, 5200, 2340, 680.2)],
            comparisons=[
                _makeComparison("RPM", sigma=0.5, status=ComparisonStatus.NORMAL),
            ],
            historicalDriveCount=12,
        )
        assert "Comparison to Historical (12 prior drives)" in report
        assert "within normal envelope" in report

    def test_flaggedParameterIncludesSigmaAndDirection(self):
        drive = _makeDriveSummary(1)
        comparisons = [
            _makeComparison(
                "IAT",
                sigma=2.4,
                status=ComparisonStatus.WATCH,
                currentAvg=118.0,
                historicalMean=98.0,
            ),
        ]
        report = formatDriveReport(
            drive,
            stats=[_makeStats("IAT", 72, 118, 118, 12.3)],
            comparisons=comparisons,
            historicalDriveCount=12,
        )
        assert "2.4σ" in report
        assert "above" in report
        assert "[⚠ WATCH]" in report

    def test_belowHistoricalShownAsBelow(self):
        drive = _makeDriveSummary(1)
        comparisons = [
            _makeComparison(
                "Coolant",
                sigma=-2.5,
                status=ComparisonStatus.WATCH,
                currentAvg=80.0,
                historicalMean=100.0,
            ),
        ]
        report = formatDriveReport(
            drive,
            stats=[_makeStats("Coolant", 70, 90, 80, 5.0)],
            comparisons=comparisons,
            historicalDriveCount=5,
        )
        assert "below" in report
        assert "2.5σ" in report

    def test_emptyHistoryDegradesGracefully(self):
        drive = _makeDriveSummary(1)
        report = formatDriveReport(
            drive,
            stats=[_makeStats("RPM", 850, 5200, 2340, 680.2)],
            comparisons=[],
            historicalDriveCount=0,
        )
        assert "Comparison to Historical (0 prior drives)" in report
        assert "No prior drives" in report


# =========================================================================
# Pure formatter: formatAllDrivesTable
# =========================================================================


class TestFormatAllDrivesTable:
    def test_emptyListShowsFriendlyMessage(self):
        text = formatAllDrivesTable([])
        assert "No drives found" in text

    def test_rendersOneRowPerDrive(self):
        drives = [
            _makeDriveSummary(1, start=datetime(2026, 4, 10, 8, 0)),
            _makeDriveSummary(2, start=datetime(2026, 4, 12, 10, 0)),
            _makeDriveSummary(3, start=datetime(2026, 4, 14, 12, 0)),
        ]
        text = formatAllDrivesTable(drives)
        assert "2026-04-10 08:00" in text
        assert "2026-04-12 10:00" in text
        assert "2026-04-14 12:00" in text
        # Duration shown
        assert "17 min" in text
        # Header present
        assert "Date" in text
        assert "Duration" in text
        assert "Device" in text
        assert "Profile" in text
        assert "Rows" in text

    def test_missingProfileRendersPlaceholder(self):
        drives = [_makeDriveSummary(1, profile=None)]
        text = formatAllDrivesTable(drives)
        assert "—" in text


# =========================================================================
# Pure formatter: formatTrendReport + helpers
# =========================================================================


class TestTrendArrow:
    def test_risingArrow(self):
        result = TrendResult(
            parameter_name="Coolant Peak",
            window_size=10,
            direction=TrendDirection.RISING,
            slope=0.8,
            avg_peak=198.0,
            avg_mean=180.0,
            drift_pct=6.0,
        )
        arrow, label = trendArrow(result)
        assert arrow == "↑"
        assert label == "Rising"

    def test_fallingArrow(self):
        result = TrendResult(
            parameter_name="RPM",
            window_size=10,
            direction=TrendDirection.FALLING,
            slope=-0.8,
            avg_peak=5000.0,
            avg_mean=2340.0,
            drift_pct=-6.0,
        )
        arrow, label = trendArrow(result)
        assert arrow == "↓"
        assert label == "Falling"

    def test_stableFlatArrow(self):
        result = TrendResult(
            parameter_name="Knock Count",
            window_size=10,
            direction=TrendDirection.STABLE,
            slope=0.0,
            avg_peak=0.0,
            avg_mean=0.0,
            drift_pct=0.0,
        )
        arrow, label = trendArrow(result)
        assert arrow == "→"
        assert label == "Stable"

    def test_stablePositiveSlopeShowsSlightRise(self):
        result = TrendResult(
            parameter_name="IAT Peak",
            window_size=10,
            direction=TrendDirection.STABLE,
            slope=0.3,
            avg_peak=98.0,
            avg_mean=90.0,
            drift_pct=3.0,  # under 5% → STABLE
        )
        arrow, label = trendArrow(result)
        assert arrow == "↗"
        assert label == "Slight"

    def test_stableNegativeSlopeShowsSlightFall(self):
        result = TrendResult(
            parameter_name="RPM Max",
            window_size=10,
            direction=TrendDirection.STABLE,
            slope=-0.2,
            avg_peak=5100.0,
            avg_mean=2300.0,
            drift_pct=-2.0,
        )
        arrow, label = trendArrow(result)
        assert arrow == "↘"


class TestClassifyTrendSignificance:
    @pytest.mark.parametrize(
        ("drift", "expected"),
        [
            (0.0, ComparisonStatus.NORMAL),
            (2.5, ComparisonStatus.NORMAL),
            (-4.9, ComparisonStatus.NORMAL),
            (5.0, ComparisonStatus.WATCH),
            (10.0, ComparisonStatus.WATCH),
            (-14.9, ComparisonStatus.WATCH),
            (15.0, ComparisonStatus.INVESTIGATE),
            (-25.0, ComparisonStatus.INVESTIGATE),
        ],
    )
    def test_thresholds(self, drift, expected):
        result = TrendResult(
            parameter_name="X",
            window_size=10,
            direction=TrendDirection.STABLE,
            slope=0.0,
            avg_peak=1.0,
            avg_mean=1.0,
            drift_pct=drift,
        )
        assert classifyTrendSignificance(result) is expected


class TestFormatTrendReport:
    def test_headerShowsWindowSize(self):
        text = formatTrendReport([], [], windowSize=10)
        assert "Trend Report — Last 10 Drives" in text

    def test_customWindowSizeInHeader(self):
        text = formatTrendReport([], [], windowSize=20)
        assert "Last 20 Drives" in text

    def test_rendersTrendRows(self):
        trends = [
            TrendResult(
                parameter_name="Coolant Peak",
                window_size=10,
                direction=TrendDirection.RISING,
                slope=0.8,
                avg_peak=198.0,
                avg_mean=180.0,
                drift_pct=6.0,
            ),
            TrendResult(
                parameter_name="RPM Max",
                window_size=10,
                direction=TrendDirection.STABLE,
                slope=0.0,
                avg_peak=5000.0,
                avg_mean=2340.0,
                drift_pct=-1.0,
            ),
        ]
        text = formatTrendReport(trends, [], windowSize=10)
        assert "Coolant Peak" in text
        assert "↑ Rising" in text
        assert "+6.0%" in text
        assert "WATCH" in text  # 6% drift → WATCH
        assert "→ Stable" in text
        assert "OK" in text

    def test_significantCorrelationsListed(self):
        correlations = [
            CorrelationResult(
                parameter_a="IAT",
                parameter_b="STFT",
                pearson_r=0.78,
                is_significant=True,
                sample_count=12,
            ),
            CorrelationResult(
                parameter_a="RPM",
                parameter_b="CoolantTemp",
                pearson_r=0.15,
                is_significant=False,
                sample_count=12,
            ),
        ]
        text = formatTrendReport([], correlations, windowSize=10)
        assert "IAT" in text
        assert "STFT" in text
        # r=+0.78 shown, not the insignificant 0.15
        assert "+0.78" in text
        assert "0.15" not in text

    def test_noCorrelationsFriendlyMessage(self):
        text = formatTrendReport([], [], windowSize=10)
        assert "No significant correlations" in text


# =========================================================================
# Orchestrator: buildDriveReport / buildAllDrivesReport
# =========================================================================


class TestBuildDriveReport:
    def test_latestPicksMostRecentDrive(self, engine):
        with Session(engine) as session:
            _seedDriveWithStats(
                session, 1, datetime(2026, 4, 10, 8, 0),
                "sim", {"RPM": (800, 4000, 2000.0, 200.0)},
            )
            _seedDriveWithStats(
                session, 2, datetime(2026, 4, 14, 10, 0),
                "sim", {"RPM": (900, 5000, 2400.0, 250.0)},
            )
            session.commit()

            report = buildDriveReport(session, "latest")
            assert "2026-04-14 10:00" in report
            assert "2026-04-10 08:00" not in report

    def test_dateRefPicksDriveOnThatDay(self, engine):
        with Session(engine) as session:
            _seedDriveWithStats(
                session, 1, datetime(2026, 4, 10, 8, 0),
                "sim", {"RPM": (800, 4000, 2000.0, 200.0)},
            )
            _seedDriveWithStats(
                session, 2, datetime(2026, 4, 14, 10, 0),
                "sim", {"RPM": (900, 5000, 2400.0, 250.0)},
            )
            session.commit()

            report = buildDriveReport(session, "2026-04-10")
            assert "2026-04-10 08:00" in report
            assert "2026-04-14" not in report

    def test_numericIdPicksDrive(self, engine):
        with Session(engine) as session:
            _seedDriveWithStats(
                session, 7, datetime(2026, 4, 15, 12, 30),
                "sim", {"RPM": (800, 4000, 2000.0, 200.0)},
            )
            session.commit()
            report = buildDriveReport(session, "7")
            assert "2026-04-15 12:30" in report

    def test_unknownRefReturnsNotFoundMessage(self, engine):
        with Session(engine) as session:
            report = buildDriveReport(session, "9999")
            assert "No drive found" in report

    def test_invalidDateStringReturnsNotFound(self, engine):
        with Session(engine) as session:
            report = buildDriveReport(session, "not-a-date")
            assert "No drive found" in report

    def test_driveReportIncludesComputedStats(self, engine):
        """End-to-end: compute basic stats, then build report, assert values."""
        with Session(engine) as session:
            # Need at least 2 drives for history to be non-empty.
            _seedDriveForAnalytics(
                session, 1, datetime(2026, 4, 10, 8, 0), "sim",
                [("RPM", 2000.0), ("RPM", 2200.0), ("RPM", 1900.0)],
            )
            _seedDriveForAnalytics(
                session, 2, datetime(2026, 4, 14, 10, 0), "sim",
                [("RPM", 2400.0), ("RPM", 2600.0), ("RPM", 2300.0)],
            )
            session.commit()
            basic.computeDriveStatistics(session, 1)
            basic.computeDriveStatistics(session, 2)

            report = buildDriveReport(session, "latest")
            assert "RPM" in report
            # Latest drive avg around 2433 — format round-trips the value.
            assert "2400" in report or "2433" in report


class TestBuildAllDrivesReport:
    def test_emptyDatabaseShowsNoDrives(self, engine):
        with Session(engine) as session:
            text = buildAllDrivesReport(session)
        assert "No drives found" in text

    def test_listsAllDrivesChronologically(self, engine):
        with Session(engine) as session:
            _seedDriveWithStats(
                session, 1, datetime(2026, 4, 12, 8, 0),
                "sim", {"RPM": (800, 4000, 2000.0, 200.0)},
            )
            _seedDriveWithStats(
                session, 2, datetime(2026, 4, 10, 8, 0),
                "sim", {"RPM": (800, 4000, 2000.0, 200.0)},
            )
            session.commit()

            text = buildAllDrivesReport(session)
            # Chronological — 10th before 12th regardless of insertion order.
            apr10 = text.index("2026-04-10")
            apr12 = text.index("2026-04-12")
            assert apr10 < apr12


# =========================================================================
# Orchestrator: buildTrendReport
# =========================================================================


class TestBuildTrendReport:
    def test_trendReportAssemblesForSeededDrives(self, engine):
        """Seed 12 drives w/ rising RPM, assert RPM shows up with rising arrow."""
        with Session(engine) as session:
            baseTime = datetime(2026, 4, 1, 8, 0)
            for i in range(1, 13):
                startTime = baseTime + timedelta(days=i)
                avg = 2000.0 + i * 60  # rising → ≥ 5% drift over 12 drives
                session.add(
                    DriveSummary(
                        id=i,
                        device_id="sim",
                        start_time=startTime,
                        end_time=startTime + timedelta(minutes=15),
                        duration_seconds=900,
                        row_count=100,
                    ),
                )
                session.add(
                    DriveStatistic(
                        drive_id=i,
                        parameter_name="RPM",
                        min_value=avg - 500,
                        max_value=avg + 500,
                        avg_value=avg,
                        std_dev=100.0,
                        outlier_min=avg - 200,
                        outlier_max=avg + 200,
                        sample_count=100,
                    ),
                )
            session.commit()

            text = buildTrendReport(session, windowSize=10)
            assert "Trend Report — Last 10 Drives" in text
            assert "RPM" in text
            # RPM rose from 2120 (drive 2) to 2720 (drive 12) — well over 5%.
            assert "↑ Rising" in text

    def test_trendWindowSizeOverride(self, engine):
        with Session(engine) as session:
            text = buildTrendReport(session, windowSize=20)
        assert "Last 20 Drives" in text

    def test_trendReportHandlesEmptyDatabase(self, engine):
        with Session(engine) as session:
            text = buildTrendReport(session)
        assert "Trend Report" in text
        assert "No significant correlations" in text


# =========================================================================
# CLI: argument parsing + dispatch
# =========================================================================


class TestParseArguments:
    def test_driveModeLatest(self):
        args = report_cli.parseArguments(["--drive", "latest"])
        assert args.drive == "latest"
        assert args.trends is False

    def test_driveModeAll(self):
        args = report_cli.parseArguments(["--drive", "all"])
        assert args.drive == "all"

    def test_trendsMode(self):
        args = report_cli.parseArguments(["--trends"])
        assert args.trends is True
        assert args.drive is None
        assert args.last is None

    def test_trendsWithLast(self):
        args = report_cli.parseArguments(["--trends", "--last", "20"])
        assert args.trends is True
        assert args.last == 20

    def test_driveAndTrendsMutuallyExclusive(self):
        with pytest.raises(SystemExit):
            report_cli.parseArguments(["--drive", "latest", "--trends"])

    def test_requiresMode(self):
        with pytest.raises(SystemExit):
            report_cli.parseArguments([])

    def test_dbUrlOverride(self):
        args = report_cli.parseArguments(
            ["--trends", "--db-url", "sqlite:///custom.db"],
        )
        assert args.db_url == "sqlite:///custom.db"


class TestRenderReport:
    def test_renderDriveLatest(self, engine):
        with Session(engine) as session:
            _seedDriveWithStats(
                session, 1, datetime(2026, 4, 10, 8, 0),
                "sim", {"RPM": (800, 4000, 2000.0, 200.0)},
            )
            session.commit()

        args = report_cli.parseArguments(["--drive", "latest"])
        text = report_cli.renderReport(args, engine)
        assert "Drive Report" in text
        assert "2026-04-10" in text

    def test_renderAll(self, engine):
        with Session(engine) as session:
            _seedDriveWithStats(
                session, 1, datetime(2026, 4, 10, 8, 0),
                "sim", {"RPM": (800, 4000, 2000.0, 200.0)},
            )
            session.commit()

        args = report_cli.parseArguments(["--drive", "all"])
        text = report_cli.renderReport(args, engine)
        assert "All Drives Summary" in text
        assert "2026-04-10" in text

    def test_renderTrends(self, engine):
        args = report_cli.parseArguments(["--trends", "--last", "20"])
        text = report_cli.renderReport(args, engine)
        assert "Last 20 Drives" in text

    def test_renderTrendsDefaultWindow(self, engine):
        args = report_cli.parseArguments(["--trends"])
        text = report_cli.renderReport(args, engine)
        assert "Last 10 Drives" in text


class TestMainCli:
    def test_mainWithSqliteDbUrlPrintsOutput(self, engine, capsys):
        # Use the fixture engine's URL so the SQLite file already has schema.
        dbUrl = str(engine.url)
        exitCode = report_cli.main(["--trends", "--db-url", dbUrl])
        assert exitCode == 0
        captured = capsys.readouterr()
        assert "Trend Report" in captured.out

    def test_mainBadArgsExits(self):
        # argparse exits with code 2 on bad args.
        with pytest.raises(SystemExit):
            report_cli.main([])

    def test_mainEmitsDriveReportToStdout(self, engine, capsys):
        with Session(engine) as session:
            _seedDriveWithStats(
                session, 1, datetime(2026, 4, 10, 8, 0),
                "sim", {"RPM": (800, 4000, 2000.0, 200.0)},
            )
            session.commit()

        dbUrl = str(engine.url)
        exitCode = report_cli.main(["--drive", "latest", "--db-url", dbUrl])
        assert exitCode == 0
        captured = capsys.readouterr()
        assert "Drive Report" in captured.out

    def test_mainResolvesEnvDbUrl(self, engine, monkeypatch, capsys):
        monkeypatch.setenv("DATABASE_URL", str(engine.url))
        exitCode = report_cli.main(["--trends"])
        assert exitCode == 0
        captured = capsys.readouterr()
        assert "Trend Report" in captured.out


class TestToSyncDriverUrl:
    """I-011: CLI must rewrite async drivers to sync before create_engine()."""

    def test_aiomysqlRewrittenToPymysql(self):
        url = "mysql+aiomysql://obd2:pw@localhost/obd2db"
        assert report_cli._toSyncDriverUrl(url) == (
            "mysql+pymysql://obd2:pw@localhost/obd2db"
        )

    def test_pymysqlPassthrough(self):
        url = "mysql+pymysql://obd2:pw@localhost/obd2db"
        assert report_cli._toSyncDriverUrl(url) == url

    def test_sqlitePassthrough(self):
        url = "sqlite:///data/server_crawl.db"
        assert report_cli._toSyncDriverUrl(url) == url


# =========================================================================
# Sanity: module re-exports
# =========================================================================


class TestPublicApi:
    def test_drive_report_and_trend_report_modules_reexported(self):
        # The package __init__ exposes submodules for programmatic access.
        assert drive_report.formatDriveReport is formatDriveReport
        assert trend_report.formatTrendReport is formatTrendReport

    def test_redirect_stdout_smoke(self):
        """Smoke-test: renderReport output can be captured with redirect_stdout."""
        # Unrelated regression guard — pure string returned, safe to re-emit.
        buf = io.StringIO()
        with redirect_stdout(buf):
            print(formatTrendReport([], [], windowSize=10))
        assert "Trend Report" in buf.getvalue()
