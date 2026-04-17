################################################################################
# File Name: test_report_ai.py
# Purpose/Description: Tests for the AI Analysis and Baseline Status sections
#                      of scripts/report.py --drive (US-163). Covers pure
#                      formatter path, orchestrator DB integration, and the
#                      regression-invariant that drives without AI data render
#                      identically to the pre-US-163 layout.
# Author: Ralph Agent
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Ralph Agent  | Initial TDD tests for US-163 — AI-enhanced CLI
#               |              | drive reports (new sections when analysis_history
#               |              | + analysis_recommendations exist).
# ================================================================================
################################################################################

"""
Tests for the AI-enhanced drive report (US-163).

Three layers of coverage:

1. Pure formatter — pass ``AnalysisHistory`` + recommendations + baseline info
   into :func:`formatDriveReport` and assert the rendered text contains the
   AI Analysis section, the Baseline Status sub-section, the rank + category +
   confidence per recommendation, and the model/processing-time header.

2. Orchestrator DB integration — seed a drive with completed ``AnalysisHistory``
   rows + linked ``AnalysisRecommendation`` rows + ``Baseline`` rows, call
   :func:`buildDriveReport`, assert the composed sections appear.

3. Regression invariant — a drive with NO analysis_history rows must render
   with no AI section, no Baseline Status section, and no new header lines
   (the pre-US-163 layout is preserved).
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import (  # noqa: E402
    AnalysisHistory,
    AnalysisRecommendation,
    Base,
    Baseline,
    DriveSummary,
)
from src.server.reports import (  # noqa: E402
    buildDriveReport,
    formatDriveReport,
)

# =========================================================================
# Fixtures / helpers
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


def _makeDrive(
    driveId: int = 1,
    device: str = "eclipse-gst",
    start: datetime | None = None,
    durationMinutes: int = 42,
    profile: str | None = "Daily",
    isReal: bool = True,
) -> DriveSummary:
    startTime = start or datetime(2026, 7, 15, 14, 30, 0)
    return DriveSummary(
        id=driveId,
        device_id=device,
        start_time=startTime,
        end_time=startTime + timedelta(minutes=durationMinutes),
        duration_seconds=durationMinutes * 60,
        profile_id=profile,
        row_count=2500,
        is_real=isReal,
    )


def _makeAnalysis(
    driveId: int = 1,
    modelName: str = "llama3.1:8b",
    startedAt: datetime | None = None,
    processingSeconds: float = 4.2,
) -> AnalysisHistory:
    started = startedAt or datetime(2026, 7, 15, 15, 2, 0)
    completed = started + timedelta(seconds=processingSeconds)
    return AnalysisHistory(
        id=driveId,  # 1:1 with drive for fixture simplicity
        drive_id=driveId,
        model_name=modelName,
        started_at=started,
        completed_at=completed,
        status="completed",
        result_summary="{}",
    )


def _makeRec(
    analysisId: int,
    rank: int,
    category: str,
    text: str,
    confidence: float,
) -> AnalysisRecommendation:
    return AnalysisRecommendation(
        analysis_id=analysisId,
        rank=rank,
        category=category,
        recommendation=text,
        confidence=confidence,
    )


def _seedBaselines(
    session: Session,
    deviceId: str,
    parameters: list[str],
    establishedAt: datetime,
) -> None:
    """Seed one Baseline row per parameter with the same established_at."""
    for name in parameters:
        session.add(
            Baseline(
                device_id=deviceId,
                parameter_name=name,
                avg_value=100.0,
                min_value=80.0,
                max_value=120.0,
                std_dev=10.0,
                sample_count=5,
                established_at=establishedAt,
            ),
        )


def _seedRealDrives(
    session: Session,
    deviceId: str,
    count: int,
    baseStart: datetime,
) -> None:
    """Seed ``count`` is_real=True drives for ``countRealDrives`` to pick up."""
    for i in range(count):
        session.add(
            DriveSummary(
                id=100 + i,
                device_id=deviceId,
                start_time=baseStart + timedelta(days=i),
                end_time=baseStart + timedelta(days=i, minutes=15),
                duration_seconds=900,
                profile_id="Daily",
                row_count=500,
                is_real=True,
            ),
        )


# =========================================================================
# Pure formatter — AI Analysis section
# =========================================================================


class TestFormatDriveReportAiSection:
    """Pure formatter with AI data passed in — no DB involvement."""

    def test_aiSectionOmittedWhenNoAnalysisPassed(self):
        """Regression invariant: calling formatDriveReport without AI kwargs
        produces the pre-US-163 output."""
        drive = _makeDrive()
        report = formatDriveReport(
            drive,
            stats=[],
            comparisons=[],
            historicalDriveCount=0,
        )
        assert "AI Analysis" not in report
        assert "Baseline Status" not in report
        assert "Data Source" not in report

    def test_aiSectionAppearsWhenAnalysisPassed(self):
        drive = _makeDrive()
        analysis = _makeAnalysis()
        recs = [
            _makeRec(1, 1, "[AFR]", "Wideband AFR trending lean at high load.", 0.82),
            _makeRec(1, 2, "[TIMING]", "Timing advance stable.", 0.95),
        ]
        report = formatDriveReport(
            drive,
            stats=[],
            comparisons=[],
            historicalDriveCount=0,
            analysis=analysis,
            recommendations=recs,
        )
        assert "AI Analysis" in report
        assert "llama3.1:8b" in report
        # Processing time computed from completed_at - started_at = 4.2s
        assert "4.2s" in report

    def test_recommendationsRenderedRankedWithCategoryAndConfidence(self):
        drive = _makeDrive()
        analysis = _makeAnalysis()
        recs = [
            _makeRec(1, 1, "[AFR]", "Enrich high-load fuel map cells by 1-2%.", 0.82),
            _makeRec(1, 2, "[TIMING]", "Timing advance stable. No knock.", 0.95),
        ]
        report = formatDriveReport(
            drive,
            stats=[],
            comparisons=[],
            historicalDriveCount=0,
            analysis=analysis,
            recommendations=recs,
        )
        # Rank, category, text all visible
        assert "1. [AFR]" in report
        assert "Enrich high-load" in report
        assert "2. [TIMING]" in report
        # Confidence formatted to 2 decimals
        assert "0.82" in report
        assert "0.95" in report
        # Rank order: 1 before 2
        assert report.index("[AFR]") < report.index("[TIMING]")

    def test_dataSourceHeaderLineAddedWhenAnalysisPresent(self):
        drive = _makeDrive(isReal=True)
        analysis = _makeAnalysis(
            startedAt=datetime(2026, 7, 15, 15, 2, 0),
            processingSeconds=4.2,
        )
        report = formatDriveReport(
            drive,
            stats=[],
            comparisons=[],
            historicalDriveCount=0,
            analysis=analysis,
            recommendations=[],
        )
        # New conditional header line per spec §3.6
        assert "Data Source" in report
        assert "OBD-II (real)" in report
        assert "Sync: 2026-07-15 15:02" in report

    def test_dataSourceHeaderShowsSimulatorWhenNotReal(self):
        drive = _makeDrive(isReal=False)
        analysis = _makeAnalysis()
        report = formatDriveReport(
            drive,
            stats=[],
            comparisons=[],
            historicalDriveCount=0,
            analysis=analysis,
            recommendations=[],
        )
        assert "Simulator" in report

    def test_emptyRecommendationsShowsFriendlyNote(self):
        """Spool's prompt may produce zero recommendations — Spec says we do
        not synthesize; show a clear note so the section doesn't look broken.
        """
        drive = _makeDrive()
        analysis = _makeAnalysis()
        report = formatDriveReport(
            drive,
            stats=[],
            comparisons=[],
            historicalDriveCount=0,
            analysis=analysis,
            recommendations=[],
        )
        assert "AI Analysis" in report
        assert "No recommendations" in report


# =========================================================================
# Pure formatter — Baseline Status sub-section
# =========================================================================


class TestFormatDriveReportBaselineStatus:
    def test_baselineStatusShowsCalibratedWhenBaselinesExist(self):
        drive = _makeDrive()
        analysis = _makeAnalysis()
        report = formatDriveReport(
            drive,
            stats=[],
            comparisons=[],
            historicalDriveCount=0,
            analysis=analysis,
            recommendations=[],
            baselineCount=8,
            baselineEstablishedAt=datetime(2026, 7, 10, 9, 15),
        )
        assert "Baseline Status" in report
        assert "Calibrated on 8 real drives" in report
        assert "2026-07-10" in report

    def test_baselineStatusShowsSimulatedWhenNoBaselines(self):
        drive = _makeDrive()
        analysis = _makeAnalysis()
        report = formatDriveReport(
            drive,
            stats=[],
            comparisons=[],
            historicalDriveCount=0,
            analysis=analysis,
            recommendations=[],
            baselineCount=0,
            baselineEstablishedAt=None,
        )
        assert "Baseline Status" in report
        assert "Using simulated baselines" in report

    def test_baselineStatusOmittedWhenNoAnalysis(self):
        """Baseline Status rides with the AI section — if no AI analysis
        exists for the drive, the Baseline Status sub-section is also
        omitted. Prevents clutter on crawl/walk drives that never saw AI."""
        drive = _makeDrive()
        report = formatDriveReport(
            drive,
            stats=[],
            comparisons=[],
            historicalDriveCount=0,
            baselineCount=5,
            baselineEstablishedAt=datetime(2026, 7, 10),
        )
        assert "Baseline Status" not in report


# =========================================================================
# Orchestrator — DB integration
# =========================================================================


class TestBuildDriveReportAiIntegration:
    def test_driveWithoutAnalysisRendersOriginalLayout(self, engine):
        """Regression: a drive with no analysis_history rows renders exactly
        the pre-US-163 layout — no AI section, no Baseline Status, no new
        header lines.  Guards the 'No regressions in expected/*.txt'
        invariant from sprint.json."""
        with Session(engine) as session:
            session.add(
                DriveSummary(
                    id=1,
                    device_id="eclipse-gst",
                    start_time=datetime(2026, 4, 10, 8, 0),
                    end_time=datetime(2026, 4, 10, 8, 15),
                    duration_seconds=900,
                    profile_id="Daily",
                    row_count=500,
                    is_real=False,
                ),
            )
            session.commit()
            report = buildDriveReport(session, "1")

        assert "Drive Report" in report
        assert "AI Analysis" not in report
        assert "Baseline Status" not in report
        assert "Data Source" not in report

    def test_driveWithAnalysisAndRecommendationsRendersAiSection(self, engine):
        with Session(engine) as session:
            session.add(_makeDrive(driveId=1, device="eclipse-gst", isReal=True))
            session.flush()
            analysis = _makeAnalysis(driveId=1)
            session.add(analysis)
            session.flush()
            session.add(_makeRec(analysis.id, 1, "[AFR]", "Lean at 4000 RPM.", 0.82))
            session.add(_makeRec(analysis.id, 2, "[TIMING]", "Stable.", 0.95))
            session.commit()

            report = buildDriveReport(session, "1")

        assert "AI Analysis" in report
        assert "llama3.1:8b" in report
        assert "[AFR]" in report
        assert "0.82" in report
        assert "[TIMING]" in report
        assert "0.95" in report

    def test_driveWithBaselinesShowsCalibratedCount(self, engine):
        with Session(engine) as session:
            session.add(_makeDrive(driveId=1, device="eclipse-gst", isReal=True))
            session.flush()
            analysis = _makeAnalysis(driveId=1)
            session.add(analysis)
            # Seed baselines for this device
            _seedBaselines(
                session,
                deviceId="eclipse-gst",
                parameters=["RPM", "Coolant", "IAT"],
                establishedAt=datetime(2026, 7, 10, 9, 15),
            )
            # Seed 8 real drives so countRealDrives returns 8
            _seedRealDrives(
                session,
                deviceId="eclipse-gst",
                count=7,  # + the drive under test = 8
                baseStart=datetime(2026, 7, 1),
            )
            session.commit()

            report = buildDriveReport(session, "1")

        assert "Baseline Status" in report
        assert "Calibrated on 8 real drives" in report
        assert "2026-07-10" in report

    def test_driveWithAnalysisButNoBaselinesShowsSimulated(self, engine):
        with Session(engine) as session:
            session.add(_makeDrive(driveId=1, device="eclipse-gst", isReal=False))
            session.flush()
            session.add(_makeAnalysis(driveId=1))
            session.commit()

            report = buildDriveReport(session, "1")

        assert "Baseline Status" in report
        assert "Using simulated baselines" in report

    def test_mostRecentCompletedAnalysisWinsWhenMultipleExist(self, engine):
        """If multiple analysis_history rows exist for the drive, the latest
        completed one is rendered. Older or still-running rows are ignored."""
        with Session(engine) as session:
            session.add(_makeDrive(driveId=1))
            session.flush()
            older = AnalysisHistory(
                drive_id=1,
                model_name="llama3.1:8b",
                started_at=datetime(2026, 7, 15, 14, 0, 0),
                completed_at=datetime(2026, 7, 15, 14, 0, 3),
                status="completed",
            )
            newer = AnalysisHistory(
                drive_id=1,
                model_name="llama3.1:70b",
                started_at=datetime(2026, 7, 15, 15, 0, 0),
                completed_at=datetime(2026, 7, 15, 15, 0, 5),
                status="completed",
            )
            inProgress = AnalysisHistory(
                drive_id=1,
                model_name="llama3.1:405b",
                started_at=datetime(2026, 7, 15, 16, 0, 0),
                completed_at=None,
                status="in_progress",
            )
            session.add_all([older, newer, inProgress])
            session.flush()
            session.add(
                _makeRec(newer.id, 1, "[AFR]", "From newer analysis.", 0.88),
            )
            session.add(
                _makeRec(older.id, 1, "[OLD]", "From older analysis.", 0.50),
            )
            session.commit()

            report = buildDriveReport(session, "1")

        # Newer completed analysis wins
        assert "llama3.1:70b" in report
        assert "From newer analysis." in report
        # Older and in-progress ignored
        assert "llama3.1:8b" not in report
        assert "llama3.1:405b" not in report
        assert "From older analysis." not in report

    def test_failedAnalysisNotRendered(self, engine):
        """Failed analyses (status='failed') don't produce a section — the
        drive renders as if no analysis existed.  Prevents a 503 or parse
        failure from showing 'AI Analysis: (empty)' to the CIO."""
        with Session(engine) as session:
            session.add(_makeDrive(driveId=1))
            session.flush()
            session.add(
                AnalysisHistory(
                    drive_id=1,
                    model_name="llama3.1:8b",
                    started_at=datetime(2026, 7, 15, 14, 0, 0),
                    completed_at=datetime(2026, 7, 15, 14, 0, 3),
                    status="failed",
                    error_message="Ollama unavailable",
                ),
            )
            session.commit()
            report = buildDriveReport(session, "1")

        assert "AI Analysis" not in report
        assert "Baseline Status" not in report
