################################################################################
# File Name: test_drive_summary_decouple_from_ollama.py
# Purpose/Description: US-317 / I-021 -- decouple _ensureDriveSummary from the
#                      pingOllama health gate in enqueueAutoAnalysisForSync, and
#                      extend backfill_drive_summary_analytics_fields.py to
#                      handle (a) NULL-drive_id legacy rows + (b) drives in
#                      realtime_data that have no drive_summary row at all.
#                      Each TestX class would FAIL against the pre-V0.27.4
#                      implementation; together they pin the V0.27.4 fix.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex (US-317) | Initial -- TDD lock-in for I-021 (writer +
#               |              | backfill decoupling from Ollama health gate).
# 2026-05-21    | Rex (US-350) | Module-level skip: this test exercises the
#               |              | enqueueAutoAnalysisForSync trigger seam retired
#               |              | by US-350 / B-104 Step 1a (V0.27.17).  The
#               |              | seam is gone; equivalent regression coverage
#               |              | on the new server-side compute path is the
#               |              | responsibility of US-355 (deploy-context drive
#               |              | simulator test surface).  Leaving the file in
#               |              | the tree as a marker; skip prevents the suite
#               |              | from going red on the architectural shift.
# ================================================================================
################################################################################

"""US-317 / I-021 -- writer / backfill decoupled from Ollama trigger.

US-350 / B-104 Step 1a (V0.27.17): ``TestDriveSummaryDecoupleFromOllama``
exercises the retired ``enqueueAutoAnalysisForSync`` trigger seam and is
class-level-skipped.  The four backfill helper classes below remain in
play -- those tests cover ``scripts/backfill_drive_summary_analytics_fields.py``
which is independent of the retired trigger.


Two concerns
------------

1. **Decouple** (``src/server/services/analysis.py:enqueueAutoAnalysisForSync``)
   -- ``_ensureDriveSummary`` is purely a data-write step; ``pingOllama`` is
   the AI-service health gate. Pre-V0.27.4 the writer was bundled behind the
   ping so when Ollama was down at sync time, drive_summary rows for drives
   6-10 never landed on the server. Fix: writer runs unconditionally; only
   the AI ``_safeRunAnalysis`` task scheduling is gated on the ping.

2. **Backfill extension** (``scripts/backfill_drive_summary_analytics_fields.py``)
   -- pre-V0.27.4 the script filtered ``drive_id IS NOT NULL``, so it
   couldn't recover (a) the NULL-drive_id legacy rows for drives 3-5 nor
   (b) drives 6-10+ that had no drive_summary row at all. Fix: three paths
   (post-US-200 UPDATE, NULL-drive_id legacy UPDATE, missing-row INSERT)
   with idempotent + ``--dry-run`` semantics preserved.

Discriminators
--------------

* :meth:`TestDriveSummaryDecoupleFromOllama.test_ollamaDown_driveSummaryStillWritten_andNoTasksEnqueued`
  -- pre-fix returns False BEFORE the writer fires; drive_summary stays
  empty. Post-fix the row exists.
* :meth:`TestBackfillNullDriveIdPath.test_nullDriveIdRow_getsAnalyticsPopulated`
  -- pre-fix filters ``drive_id IS NOT NULL`` so legacy rows are skipped.
  Post-fix Path B fills row_count / is_real / data_source.
* :meth:`TestBackfillMissingRowPath.test_missingDriveId_insertsNewRow`
  -- pre-fix only iterates existing rows so no INSERTs ever happen.
  Post-fix Path C inserts a row when realtime_data has a drive_id without
  a drive_summary entry.

The remaining tests (Ollama-up happy path, no-boundaries path,
idempotency, dry-run) are regression pins that hold pre and post fix.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.db.models import Base, DriveSummary, RealtimeData  # noqa: E402

# ==============================================================================
# aiosqlite gating (mirrors test_sync_auto_analysis.py)
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


# b044-exempt: canonical Eclipse Pi hostname for US-317 fixtures
DEVICE = "chi-eclipse-01"
START_1 = datetime(2026, 5, 11, 8, 0, 0)
END_1 = datetime(2026, 5, 11, 8, 5, 0)


# ==============================================================================
# 1) Decouple tests -- writer fires regardless of Ollama health
# ==============================================================================


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


def _connectionLogRowsForDrive(driveId: int = 11) -> list[dict]:
    return [
        {
            "id": 1,
            "timestamp": START_1.isoformat(),
            "event_type": "drive_start",
            "success": 1,
            "drive_id": driveId,
        },
        {
            "id": 2,
            "timestamp": END_1.isoformat(),
            "event_type": "drive_end",
            "success": 1,
            "drive_id": driveId,
        },
    ]


@pytest.mark.skip(
    reason=(
        "Superseded by US-350 / B-104 Step 1a (V0.27.17) -- the "
        "enqueueAutoAnalysisForSync trigger seam these tests exercise is "
        "retired.  Replacement coverage on the server-side compute path "
        "belongs to US-355 (deploy-context drive simulator)."
    ),
)
@_skipNoAsyncDb
class TestDriveSummaryDecoupleFromOllama:
    """I-021: writer must run independently of pingOllama health gate."""

    @pytest.mark.asyncio
    async def test_ollamaDown_driveSummaryStillWritten_andNoTasksEnqueued(
        self, asyncEngine, monkeypatch,
    ):
        """Pre-fix: writer short-circuits with ping. Post-fix: writer fires; AI tasks don't."""
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        async def fakePingDown(*_args, **_kwargs):
            return False

        monkeypatch.setattr(analysisModule, "pingOllama", fakePingDown)

        # _safeRunAnalysis must NOT be scheduled when Ollama is down.
        scheduled: list[int] = []

        async def shouldNotRun(**kwargs):  # pragma: no cover -- discriminator
            scheduled.append(kwargs.get("driveId"))

        monkeypatch.setattr(analysisModule, "_safeRunAnalysis", shouldNotRun)

        result = await analysisModule.enqueueAutoAnalysisForSync(
            engine=asyncEngine,
            deviceId=DEVICE,
            connectionLogRows=_connectionLogRowsForDrive(driveId=11),
            ollamaBaseUrl="http://fake-ollama:11434",
            ollamaModel="llama3.1:8b-test",
            ollamaTimeoutSeconds=30,
        )

        # Return value semantics preserved: no AI tasks scheduled -> False.
        assert result is False
        assert scheduled == []

        # Discriminator: drive_summary row must exist post-call.
        async with AsyncSession(asyncEngine) as session:
            drives = (
                await session.execute(select(DriveSummary))
            ).scalars().all()

        assert len(drives) == 1
        assert drives[0].source_device == DEVICE
        assert drives[0].drive_id == 11

    @pytest.mark.asyncio
    async def test_ollamaUp_driveSummaryWritten_andAnalysisEnqueued(
        self, asyncEngine, monkeypatch,
    ):
        """Happy path preserved: writer fires AND AI analysis is scheduled."""
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

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
            connectionLogRows=_connectionLogRowsForDrive(driveId=12),
            ollamaBaseUrl="http://fake-ollama:11434",
            ollamaModel="llama3.1:8b-test",
            ollamaTimeoutSeconds=30,
        )

        # Drain background tasks the AI step scheduled.
        await asyncio.gather(
            *list(analysisModule._pendingAutoAnalysisTasks),
            return_exceptions=True,
        )

        assert result is True
        assert len(scheduled) == 1

        async with AsyncSession(asyncEngine) as session:
            drives = (
                await session.execute(select(DriveSummary))
            ).scalars().all()
        assert len(drives) == 1
        assert drives[0].drive_id == 12

    @pytest.mark.asyncio
    async def test_noBoundaries_returnsFalse_noWritesNoAnalysis(
        self, asyncEngine, monkeypatch,
    ):
        """Empty connection_log -> early-return path unchanged (regression pin)."""
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        # If we get past the boundaries==[] guard, this raises.
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
            drives = (
                await session.execute(select(DriveSummary))
            ).scalars().all()
        assert drives == []


# ==============================================================================
# 2) Backfill extension -- NULL-drive_id UPDATE + missing-row INSERT
# ==============================================================================


@pytest.fixture
def syncSession() -> Session:
    """Sync SQLite session for backfill tests (the script uses sync Session)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


def _seedRealtimeRowsForDrive(
    session: Session,
    *,
    driveId: int,
    sourceIdStart: int,
    rowCount: int,
    timestampStart: datetime,
    deviceId: str = DEVICE,
    dataSource: str = "real",
) -> None:
    """Seed N real readings inside a drive window with the given drive_id."""
    for i in range(rowCount):
        session.add(
            RealtimeData(
                source_id=sourceIdStart + i,
                source_device=deviceId,
                timestamp=timestampStart + timedelta(seconds=i),
                parameter_name="RPM",
                value=2500.0,
                unit="rpm",
                profile_id="daily",
                data_source=dataSource,
                drive_id=driveId,
            ),
        )
    session.flush()


def _seedRealtimeRowsLegacyTimeRange(
    session: Session,
    *,
    sourceIdStart: int,
    rowCount: int,
    timestampStart: datetime,
    deviceId: str = DEVICE,
    dataSource: str = "real",
) -> None:
    """Seed N readings with NO drive_id (legacy / pre-US-200 shape)."""
    for i in range(rowCount):
        session.add(
            RealtimeData(
                source_id=sourceIdStart + i,
                source_device=deviceId,
                timestamp=timestampStart + timedelta(seconds=i),
                parameter_name="RPM",
                value=2500.0,
                unit="rpm",
                profile_id="daily",
                data_source=dataSource,
                drive_id=None,
            ),
        )
    session.flush()


class TestBackfillNullDriveIdPath:
    """NULL-drive_id legacy rows (drives 3-5 in production) get analytics filled."""

    def test_nullDriveIdRow_getsAnalyticsPopulated(self, syncSession):
        from scripts.backfill_drive_summary_analytics_fields import backfill

        legacyStart = datetime(2026, 4, 29, 14, 0, 0)
        legacyEnd = legacyStart + timedelta(minutes=10)

        # Pre-existing legacy row: NULL drive_id, NULL analytics.
        legacy = DriveSummary(
            device_id=DEVICE,
            start_time=legacyStart,
            end_time=legacyEnd,
        )
        syncSession.add(legacy)
        syncSession.flush()

        # 150 real readings inside the legacy window so the legacy
        # time-range path in _computeDriveAnalytics catches them.
        _seedRealtimeRowsLegacyTimeRange(
            syncSession,
            sourceIdStart=10_000,
            rowCount=150,
            timestampStart=legacyStart,
        )

        stats = backfill(syncSession, deviceId=DEVICE, dryRun=False)
        syncSession.flush()

        refreshed = syncSession.execute(
            select(DriveSummary).where(DriveSummary.id == legacy.id),
        ).scalar_one()

        assert stats.populated >= 1
        assert refreshed.row_count == 150
        assert refreshed.is_real is True
        assert refreshed.data_source == "real"


class TestBackfillMissingRowPath:
    """Drives in realtime_data without any drive_summary row get one inserted."""

    def test_missingDriveId_insertsNewRow(self, syncSession):
        from scripts.backfill_drive_summary_analytics_fields import backfill

        _seedRealtimeRowsForDrive(
            syncSession,
            driveId=99,
            sourceIdStart=20_000,
            rowCount=120,
            timestampStart=datetime(2026, 5, 5, 9, 0, 0),
        )

        existingPre = syncSession.execute(
            select(DriveSummary),
        ).scalars().all()
        assert existingPre == []

        stats = backfill(syncSession, deviceId=DEVICE, dryRun=False)
        syncSession.flush()

        rows = syncSession.execute(select(DriveSummary)).scalars().all()
        assert len(rows) == 1
        assert rows[0].drive_id == 99
        assert rows[0].source_device == DEVICE
        assert rows[0].source_id == 99
        assert rows[0].row_count == 120
        assert stats.inserted == 1


class TestBackfillIdempotency:
    """Second run reports populated=0 inserted=0 (no duplicate rows)."""

    def test_secondRun_noChanges(self, syncSession):
        from scripts.backfill_drive_summary_analytics_fields import backfill

        _seedRealtimeRowsForDrive(
            syncSession,
            driveId=42,
            sourceIdStart=30_000,
            rowCount=110,
            timestampStart=datetime(2026, 5, 6, 10, 0, 0),
        )

        first = backfill(syncSession, deviceId=DEVICE, dryRun=False)
        syncSession.flush()
        assert first.inserted == 1

        second = backfill(syncSession, deviceId=DEVICE, dryRun=False)
        assert second.populated == 0
        assert second.inserted == 0

        rows = syncSession.execute(select(DriveSummary)).scalars().all()
        assert len(rows) == 1


class TestBackfillDryRun:
    """--dry-run reports counts but writes nothing."""

    def test_dryRun_doesNotInsert(self, syncSession):
        from scripts.backfill_drive_summary_analytics_fields import backfill

        _seedRealtimeRowsForDrive(
            syncSession,
            driveId=77,
            sourceIdStart=40_000,
            rowCount=130,
            timestampStart=datetime(2026, 5, 7, 11, 0, 0),
        )

        stats = backfill(syncSession, deviceId=DEVICE, dryRun=True)

        rows = syncSession.execute(select(DriveSummary)).scalars().all()
        assert rows == []
        assert stats.inserted == 1
