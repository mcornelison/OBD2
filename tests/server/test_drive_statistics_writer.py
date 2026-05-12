################################################################################
# File Name: test_drive_statistics_writer.py
# Purpose/Description: US-324 / I-024 -- production drive_statistics writer.  No
#                      production path wrote drive_statistics rows except
#                      runAnalysis -> _buildAnalyticsContext -> computeDriveStatistics,
#                      which only fired when pingOllama succeeded.  The fix adds
#                      _ensureDriveStatistics() to analysis.py, wired into
#                      enqueueAutoAnalysisForSync alongside _ensureDriveSummary
#                      and decoupled from the Ollama health gate (US-317 pattern),
#                      plus scripts/backfill_drive_statistics.py for drives 3-10.
#                      Each TestX class would FAIL against the pre-V0.27.6 code.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-11    | Rex (US-324) | Initial -- TDD lock-in for I-024 (drive_statistics
#               |              | writer + Ollama decouple + backfill).
# ================================================================================
################################################################################

"""US-324 / I-024 -- drive_statistics writer + backfill.

Concerns
--------

1. **Writer** (``src/server/services/analysis.py:_ensureDriveStatistics``)
   -- a data-write step that computes per-parameter aggregates
   (min/max/avg/std) from ``realtime_data`` and persists one
   ``drive_statistics`` row per parameter.  Delegates to
   :func:`src.server.analytics.basic.computeDriveStatistics` so the
   writer and the AI-analysis path share one source of truth.  Keyed on
   the *server-side* ``drive_summary.id`` -- the value
   ``proposeCalibration`` joins on (``DriveSummary.id == DriveStatistic.drive_id``).

2. **Decouple** (``enqueueAutoAnalysisForSync``) -- the writer runs
   unconditionally whenever a drive's boundaries are known, exactly like
   ``_ensureDriveSummary`` post-US-317.  Pre-V0.27.6 the only path that
   wrote drive_statistics was ``runAnalysis`` (gated on ``pingOllama``),
   so an Ollama-down sync left ``drive_statistics`` empty and calibration
   permanently returned "Need 5 more real drives".

3. **Backfill** (``scripts/backfill_drive_statistics.py``) -- one-shot
   computation for drives that have ``realtime_data`` + a ``drive_summary``
   row but no ``drive_statistics`` rows yet.  Idempotent (skips populated
   drives) + ``--dry-run`` preview.

Discriminators (would FAIL pre-fix)
-----------------------------------

* :meth:`TestEnsureDriveStatistics.*` -- ``_ensureDriveStatistics`` does
  not exist pre-fix (ImportError).
* :meth:`TestEnqueueAutoAnalysisWritesDriveStatistics.test_ollamaDown_driveStatisticsStillWritten`
  -- pre-fix the writer is bundled behind the Ollama gate, so an
  Ollama-down sync leaves ``drive_statistics`` empty.
* :meth:`TestEnqueueAutoAnalysisWritesDriveStatistics.test_ollamaUp_driveStatisticsWrittenWithoutRunningAnalysis`
  -- pre-fix the rows only land inside ``runAnalysis``; with the AI task
  mocked out they never appear.
* :meth:`TestBackfillDriveStatistics.*` -- ``scripts/backfill_drive_statistics``
  does not exist pre-fix.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

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

# b044-exempt: canonical Eclipse Pi hostname for US-324 fixtures
DEVICE = "chi-eclipse-01"
DRIVE_WINDOW_START = datetime(2026, 5, 12, 8, 0, 0)
DRIVE_WINDOW_END = datetime(2026, 5, 12, 8, 30, 0)

# Subset of the canonical PIDs the calibration pipeline cares about -- enough
# for the writer assertions without seeding all ten.
CANONICAL_PIDS_SAMPLE = ("RPM", "COOLANT_TEMP", "SPEED")


# ==============================================================================
# aiosqlite gating (mirrors test_drive_summary_decouple_from_ollama.py)
# ==============================================================================

try:
    import aiosqlite as _aiosqlite  # noqa: F401

    _HAS_AIOSQLITE = True
except ImportError:
    _HAS_AIOSQLITE = False

_skipNoAsyncDb = pytest.mark.skipif(
    not _HAS_AIOSQLITE,
    reason="aiosqlite not installed -- skipping async DB tests",
)

if _HAS_AIOSQLITE:
    import pytest_asyncio  # type: ignore[import-not-found]

    _asyncFixture = pytest_asyncio.fixture
else:
    _asyncFixture = pytest.fixture


# ==============================================================================
# Fixtures + seeding helpers
# ==============================================================================


@pytest.fixture
def syncSession() -> Session:
    """Sync SQLite session with the server schema (writer + backfill take sync)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
    Path(tmp.name).unlink(missing_ok=True)


@_asyncFixture
async def asyncEngine():
    """Real AsyncEngine on a file-backed aiosqlite DB."""
    from sqlalchemy.ext.asyncio import create_async_engine

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    syncEng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(syncEng)
    syncEng.dispose()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    try:
        yield engine
    finally:
        await engine.dispose()
        Path(tmp.name).unlink(missing_ok=True)


def _seedDriveSummary(
    session: Session,
    *,
    summaryId: int,
    device: str = DEVICE,
    start: datetime = DRIVE_WINDOW_START,
    end: datetime = DRIVE_WINDOW_END,
    driveId: int | None = None,
) -> None:
    """Insert a drive_summary row with analytics fields populated."""
    session.add(
        DriveSummary(
            id=summaryId,
            device_id=device,
            start_time=start,
            end_time=end,
            duration_seconds=int((end - start).total_seconds()),
            source_device=device if driveId is not None else None,
            source_id=driveId,
            drive_id=driveId,
        ),
    )


def _seedReadings(
    session: Session,
    *,
    device: str = DEVICE,
    readings: list[tuple[str, float, datetime]],
    sourceIdStart: int = 1,
    driveId: int | None = None,
) -> None:
    """Insert realtime_data rows; ``readings`` are (parameter_name, value, ts)."""
    for i, (param, value, ts) in enumerate(readings):
        session.add(
            RealtimeData(
                source_id=sourceIdStart + i,
                source_device=device,
                timestamp=ts,
                parameter_name=param,
                value=value,
                unit=None,
                profile_id="daily",
                data_source="real",
                drive_id=driveId,
            ),
        )


def _rpmSeries() -> list[float]:
    """Known series with easy-to-check aggregates: min 10, max 50, avg 30."""
    return [10.0, 20.0, 30.0, 40.0, 50.0]


def _seedDriveWithKnownStats(
    session: Session,
    *,
    summaryId: int,
    driveId: int | None = None,
    sourceIdStart: int = 1,
) -> None:
    """Seed a drive_summary + realtime_data for RPM/COOLANT_TEMP/SPEED.

    RPM follows :func:`_rpmSeries` (min 10, max 50, avg 30, sample std
    sqrt(250) ~ 15.811).  COOLANT_TEMP is constant 85.0 (std 0).  SPEED is
    a short ramp.  Five readings per parameter.
    """
    _seedDriveSummary(session, summaryId=summaryId, driveId=driveId)
    readings: list[tuple[str, float, datetime]] = []
    rpm = _rpmSeries()
    for i in range(5):
        ts = DRIVE_WINDOW_START + timedelta(seconds=i)
        readings.append(("RPM", rpm[i], ts))
        readings.append(("COOLANT_TEMP", 85.0, ts))
        readings.append(("SPEED", 30.0 + 2.0 * i, ts))
    _seedReadings(
        session,
        readings=readings,
        sourceIdStart=sourceIdStart,
        driveId=driveId,
    )


def _connectionLogRowsForDrive(driveId: int) -> list[dict]:
    return [
        {
            "id": 1,
            "timestamp": DRIVE_WINDOW_START.isoformat(),
            "event_type": "drive_start",
            "success": 1,
            "drive_id": driveId,
        },
        {
            "id": 2,
            "timestamp": DRIVE_WINDOW_END.isoformat(),
            "event_type": "drive_end",
            "success": 1,
            "drive_id": driveId,
        },
    ]


# ==============================================================================
# 1) Writer unit tests -- _ensureDriveStatistics
# ==============================================================================


class TestEnsureDriveStatistics:
    """The new server-side drive_statistics writer (US-324 / I-024)."""

    def test_ensureDriveStatistics_writesOneRowPerParameter(self, syncSession):
        from src.server.services.analysis import _ensureDriveStatistics

        _seedDriveWithKnownStats(syncSession, summaryId=1)
        syncSession.commit()

        written = _ensureDriveStatistics(syncSession, 1)

        rows = syncSession.execute(
            select(DriveStatistic).where(DriveStatistic.drive_id == 1),
        ).scalars().all()
        assert written == len(rows) == 3
        assert {r.parameter_name for r in rows} == set(CANONICAL_PIDS_SAMPLE)

    def test_ensureDriveStatistics_computesCorrectAggregates(self, syncSession):
        from src.server.services.analysis import _ensureDriveStatistics

        _seedDriveWithKnownStats(syncSession, summaryId=1)
        syncSession.commit()

        _ensureDriveStatistics(syncSession, 1)

        rows = {
            r.parameter_name: r
            for r in syncSession.execute(
                select(DriveStatistic).where(DriveStatistic.drive_id == 1),
            ).scalars().all()
        }
        rpm = rows["RPM"]
        assert rpm.min_value == 10.0
        assert rpm.max_value == 50.0
        assert rpm.avg_value == 30.0
        assert rpm.sample_count == 5
        # sample std of [10,20,30,40,50] = sqrt(250) ~ 15.811
        assert abs(rpm.std_dev - 15.811) < 0.01

        coolant = rows["COOLANT_TEMP"]
        assert coolant.min_value == coolant.max_value == coolant.avg_value == 85.0
        assert coolant.std_dev == 0.0

    def test_ensureDriveStatistics_isIdempotent(self, syncSession):
        from src.server.services.analysis import _ensureDriveStatistics

        _seedDriveWithKnownStats(syncSession, summaryId=1)
        syncSession.commit()

        _ensureDriveStatistics(syncSession, 1)
        secondCount = _ensureDriveStatistics(syncSession, 1)

        rows = syncSession.execute(
            select(DriveStatistic).where(DriveStatistic.drive_id == 1),
        ).scalars().all()
        assert secondCount == 3
        assert len(rows) == 3  # replaced, not duplicated

    def test_ensureDriveStatistics_driveWithNoReadings_writesNoRows(self, syncSession):
        from src.server.services.analysis import _ensureDriveStatistics

        _seedDriveSummary(syncSession, summaryId=7)
        syncSession.commit()

        written = _ensureDriveStatistics(syncSession, 7)

        rows = syncSession.execute(
            select(DriveStatistic).where(DriveStatistic.drive_id == 7),
        ).scalars().all()
        assert written == 0
        assert rows == []


# ==============================================================================
# 2) Decouple tests -- writer fires regardless of Ollama health
# ==============================================================================


@_skipNoAsyncDb
class TestEnqueueAutoAnalysisWritesDriveStatistics:
    """I-024: drive_statistics writer must be decoupled from the Ollama gate."""

    @staticmethod
    async def _seedRealtimeForDrive(asyncEngine, driveId: int) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(asyncEngine) as session:
            idx = 0
            for i in range(6):
                ts = DRIVE_WINDOW_START + timedelta(seconds=i)
                for param, value in (
                    ("RPM", 2000.0 + 50.0 * i),
                    ("COOLANT_TEMP", 85.0),
                    ("SPEED", 40.0 + float(i)),
                ):
                    session.add(
                        RealtimeData(
                            source_id=1000 + idx,
                            source_device=DEVICE,
                            timestamp=ts,
                            parameter_name=param,
                            value=value,
                            data_source="real",
                            drive_id=driveId,
                        ),
                    )
                    idx += 1
            await session.commit()

    @pytest.mark.asyncio
    async def test_ollamaDown_driveStatisticsStillWritten(
        self, asyncEngine, monkeypatch,
    ):
        """Pre-fix: drive_statistics never written when Ollama is down."""
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        await self._seedRealtimeForDrive(asyncEngine, driveId=11)

        async def fakePingDown(*_args, **_kwargs):
            return False

        monkeypatch.setattr(analysisModule, "pingOllama", fakePingDown)

        scheduled: list[int] = []

        async def shouldNotRun(**kwargs):  # pragma: no cover -- discriminator
            scheduled.append(kwargs.get("driveId"))

        monkeypatch.setattr(analysisModule, "_safeRunAnalysis", shouldNotRun)

        result = await analysisModule.enqueueAutoAnalysisForSync(
            engine=asyncEngine,
            deviceId=DEVICE,
            connectionLogRows=_connectionLogRowsForDrive(11),
            ollamaBaseUrl="http://fake-ollama:11434",
            ollamaModel="llama3.1:8b-test",
            ollamaTimeoutSeconds=30,
        )

        assert result is False
        assert scheduled == []

        async with AsyncSession(asyncEngine) as session:
            summaries = (
                await session.execute(select(DriveSummary))
            ).scalars().all()
            stats = (
                await session.execute(select(DriveStatistic))
            ).scalars().all()

        assert len(summaries) == 1
        assert {s.parameter_name for s in stats} == set(CANONICAL_PIDS_SAMPLE)
        # drive_statistics.drive_id is the SERVER-side drive_summary.id,
        # not the Pi-local drive_id (matches proposeCalibration's join).
        assert all(s.drive_id == summaries[0].id for s in stats)

    @pytest.mark.asyncio
    async def test_ollamaUp_driveStatisticsWrittenWithoutRunningAnalysis(
        self, asyncEngine, monkeypatch,
    ):
        """With the AI task mocked out, drive_statistics still land (pre-fix: not)."""
        import asyncio

        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        await self._seedRealtimeForDrive(asyncEngine, driveId=12)

        async def fakePingUp(*_args, **_kwargs):
            return True

        monkeypatch.setattr(analysisModule, "pingOllama", fakePingUp)

        scheduled: list[int] = []

        async def captureRun(**kwargs):
            scheduled.append(kwargs["driveId"])

        monkeypatch.setattr(analysisModule, "_safeRunAnalysis", captureRun)

        result = await analysisModule.enqueueAutoAnalysisForSync(
            engine=asyncEngine,
            deviceId=DEVICE,
            connectionLogRows=_connectionLogRowsForDrive(12),
            ollamaBaseUrl="http://fake-ollama:11434",
            ollamaModel="llama3.1:8b-test",
            ollamaTimeoutSeconds=30,
        )

        await asyncio.gather(
            *list(analysisModule._pendingAutoAnalysisTasks),
            return_exceptions=True,
        )

        assert result is True
        assert len(scheduled) == 1

        async with AsyncSession(asyncEngine) as session:
            stats = (
                await session.execute(select(DriveStatistic))
            ).scalars().all()
        assert {s.parameter_name for s in stats} == set(CANONICAL_PIDS_SAMPLE)

    @pytest.mark.asyncio
    async def test_noBoundaries_writesNothing(self, asyncEngine, monkeypatch):
        """Empty connection_log -> early return, no drive_statistics (regression pin)."""
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        async def explodingPing(*_args, **_kwargs):  # pragma: no cover
            raise AssertionError("pingOllama must not run when boundaries=[]")

        monkeypatch.setattr(analysisModule, "pingOllama", explodingPing)

        result = await analysisModule.enqueueAutoAnalysisForSync(
            engine=asyncEngine,
            deviceId=DEVICE,
            connectionLogRows=[],
            ollamaBaseUrl="http://fake-ollama:11434",
            ollamaModel="llama3.1:8b-test",
            ollamaTimeoutSeconds=30,
        )

        assert result is False
        async with AsyncSession(asyncEngine) as session:
            stats = (
                await session.execute(select(DriveStatistic))
            ).scalars().all()
        assert stats == []


# ==============================================================================
# 3) Backfill tests -- scripts/backfill_drive_statistics.py
# ==============================================================================


class TestBackfillDriveStatistics:
    """One-shot backfill for drives that lack drive_statistics rows."""

    def test_backfill_writesForDrivesLackingStats(self, syncSession):
        from scripts.backfill_drive_statistics import backfill

        _seedDriveWithKnownStats(syncSession, summaryId=3)
        syncSession.commit()

        stats = backfill(syncSession, deviceId=DEVICE, dryRun=False)

        assert stats.drivesWritten == 1
        assert stats.rowsWritten == 3
        rows = syncSession.execute(
            select(DriveStatistic).where(DriveStatistic.drive_id == 3),
        ).scalars().all()
        assert {r.parameter_name for r in rows} == set(CANONICAL_PIDS_SAMPLE)

    def test_backfill_isIdempotent_secondRunSkipsPopulated(self, syncSession):
        from scripts.backfill_drive_statistics import backfill

        _seedDriveWithKnownStats(syncSession, summaryId=3)
        syncSession.commit()

        first = backfill(syncSession, deviceId=DEVICE, dryRun=False)
        assert first.drivesWritten == 1

        second = backfill(syncSession, deviceId=DEVICE, dryRun=False)
        assert second.drivesWritten == 0
        assert second.drivesSkipped == 1

        rows = syncSession.execute(select(DriveStatistic)).scalars().all()
        assert len(rows) == 3  # not duplicated

    def test_backfill_dryRun_writesNothing(self, syncSession):
        from scripts.backfill_drive_statistics import backfill

        _seedDriveWithKnownStats(syncSession, summaryId=3)
        syncSession.commit()

        stats = backfill(syncSession, deviceId=DEVICE, dryRun=True)

        assert stats.drivesWritten == 1
        assert stats.rowsWritten == 3
        rows = syncSession.execute(select(DriveStatistic)).scalars().all()
        assert rows == []

    def test_backfill_driveWithNoReadings_isSkipped(self, syncSession):
        from scripts.backfill_drive_statistics import backfill

        _seedDriveSummary(syncSession, summaryId=9)
        syncSession.commit()

        stats = backfill(syncSession, deviceId=DEVICE, dryRun=False)

        assert stats.drivesWritten == 0
        assert stats.drivesSkipped == 1
        rows = syncSession.execute(select(DriveStatistic)).scalars().all()
        assert rows == []
