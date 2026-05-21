################################################################################
# File Name: test_drive_summary_writer_fires_on_pi_sync.py
# Purpose/Description: US-348 / I-040 -- drive_summary server analytics writer
#                      must fire when a Pi-sync drive_summary row arrives, even
#                      when the same sync payload's connection_log carries no
#                      drive_start / drive_end events.  Empirical from I-040:
#                      across drives 11-18 incl. fresh real drives 17+18 the
#                      analytics fields (start_time / end_time /
#                      duration_seconds / row_count / is_real) stay NULL forever
#                      because the trigger seam was hardcoded to connection_log
#                      drive_end events.  Real Pi syncs land drive_summary rows
#                      via the table-upsert path; connection_log drive_end
#                      events are not a reliable signal (different sync batches,
#                      or absent entirely on the Pi side).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex (US-348) | Initial -- IRL-discipline e2e regression gate
#               |              | for I-040 false-pass of US-326.  Per Tester
#               |              | I-040 + feedback-tester-validate-deploy-fixes-
#               |              | irl-not-just-code: this test exercises the real
#               |              | writer trigger via httpx + ASGI transport with
#               |              | a real aiosqlite engine and the live route --
#               |              | NOT a synthetic mock of the writer's trigger
#               |              | seam.  Pre-fix: RED on every assertion below
#               |              | because extractDriveBoundaries returns [] for
#               |              | the connection_log-empty case.  Post-fix:
#               |              | GREEN because drive_summary payload is the
#               |              | secondary trigger seam.
# ================================================================================
################################################################################

"""US-348 / I-040: drive_summary writer fires on the Pi-sync drive_summary row.

The bug (I-040 evidence 2026-05-20)
-----------------------------------

Tester ran the production query::

    SELECT id, source_id, drive_id, start_time, end_time, duration_seconds,
           row_count, is_real, drive_start_timestamp
    FROM drive_summary WHERE drive_id >= 16 OR id >= 14 ORDER BY id DESC LIMIT 8;

and got: every row of 8 has ``start_time`` / ``end_time`` / ``duration_seconds``
/ ``row_count`` / ``is_real`` ALL NULL.  Pi-synced fields
(``drive_start_timestamp``, ``ambient_temp_at_start_c``, ``starting_battery_v``,
``source_id``) arrive correctly.  Includes today's fresh real drives 17+18 --
proving the analytics writer doesn't fire on a real Pi-sync round-trip.

US-326 (Sprint 33, V0.27.7) shipped ``passes:true`` with a synthetic test that
seeded both a Pi-sync row AND a paired ``drive_start`` / ``drive_end`` pair in
``connection_log`` in the same sync payload, then called the writer directly.
13 days of real drives later, the bug is empirically visible: the trigger seam
``extractDriveBoundaries(connection_log)`` returns ``[]`` for real Pi syncs
because the real Pi flow doesn't put paired drive_start/drive_end events into
the same sync batch's connection_log (or doesn't write those events at all).
Result: ``_writeDriveAnalytics`` never runs and analytics fields stay NULL.

Test discipline (Tester I-040 lesson)
-------------------------------------

Per ``offices/tester/knowledge/feedback-tester-validate-deploy-fixes-irl-not-
just-code.md``: this test exercises the **real** writer trigger via the live
``/api/v1/sync`` route against an aiosqlite engine.  No mock of
``extractDriveBoundaries``, no mock of ``_ensureDriveSummary``, no mock of
``enqueueAutoAnalysisForSync`` -- only the Ollama transport adapter is mocked
(via the same ``pingOllama`` / ``_invokeOllama`` monkeypatch the existing
auto-analysis happy-path test uses).  The test fails pre-fix because the
analytics writer literally never runs; passes post-fix because the
drive_summary payload becomes a trigger seam alongside connection_log.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("jinja2")

from sqlalchemy import create_engine, select  # noqa: E402

from src.server.db.models import (  # noqa: E402
    Base,
    DriveSummary,
)

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
    reason="aiosqlite not installed -- skipping async DB route tests",
)

if _HAS_AIOSQLITE:
    import pytest_asyncio  # type: ignore[import-not-found]

    _asyncFixture = pytest_asyncio.fixture
else:
    _asyncFixture = pytest.fixture


# ==============================================================================
# Fixtures
# ==============================================================================


DEVICE_ID = "chi-eclipse-01"
DRIVE_ID = 17  # Mirror the fresh-real-drive id from I-040 evidence.
DRIVE_START_TS = datetime(2026, 5, 20, 18, 30, 0)


def _makeSettings(apiKey: str = "valid-key", maxMb: int = 10):
    from src.server.config import Settings

    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        API_KEY=apiKey,
        MAX_SYNC_PAYLOAD_MB=maxMb,
        OLLAMA_BASE_URL="http://fake-ollama:11434",
        OLLAMA_MODEL="llama3.1:8b-test",
    )


def _buildRealisticPiSyncPayload(
    *,
    driveId: int = DRIVE_ID,
    deviceId: str = DEVICE_ID,
    realtimeRowCount: int = 120,
    includeConnectionLogDriveEvents: bool = False,
) -> dict:
    """Build a sync payload that mirrors what the Pi actually sends post-drive.

    Shape:

    * ``drive_summary`` payload carries one row per completed drive with
      Pi-sync columns (id == drive_id, drive_start_timestamp, ambient_temp,
      starting_battery_v, barometric).  Analytics columns (3-8) are absent
      (Pi doesn't compute them).
    * ``realtime_data`` payload carries the per-PID readings with
      ``drive_id`` set -- this is the post-US-200 wire shape.
    * ``connection_log`` payload carries non-drive events ONLY by default
      (the empirical I-040 scenario).  When ``includeConnectionLogDriveEvents``
      is True, additionally carries paired ``drive_start``/``drive_end``
      events -- mirrors the existing
      ``test_sync_auto_analysis.TestAutoAnalysisHappyPath`` scenario, which
      passed pre-fix BECAUSE the connection_log events were synthetic.
    """
    realtimeStartTs = DRIVE_START_TS + timedelta(seconds=5)
    realtimeRows = []
    for i in range(realtimeRowCount):
        realtimeRows.append({
            "id": i + 1,
            "timestamp": (realtimeStartTs + timedelta(seconds=i)).isoformat(),
            "parameter_name": "RPM",
            "value": 2500.0 + (i % 50),
            "unit": "rpm",
            "profile_id": "daily",
            "data_source": "real",
            "drive_id": driveId,
        })

    driveSummaryRow = {
        # Pi PK 'drive_id' -> renamed to 'id' on the wire -> mapped to
        # source_id on the server (see src/pi/data/sync_log.py + sync.py
        # rename machinery).
        "id": driveId,
        "drive_start_timestamp": DRIVE_START_TS.isoformat(),
        "ambient_temp_at_start_c": 18.5,
        "starting_battery_v": 12.7,
        "barometric_kpa_at_start": 100.2,
        "data_source": "real",
    }

    connectionLogRows = [
        # A non-drive event always rides on connection_log (heartbeat,
        # OBD-connect noise, etc.).  Important to keep one so connection_log
        # isn't EMPTY -- the pre-fix early-return path was "connLog is None"
        # not "connLog has no drive events".  The empirical I-040 scenario
        # is connection_log present but no drive_start/drive_end rows.
        {
            "id": 1,
            "timestamp": DRIVE_START_TS.isoformat(),
            "event_type": "obd_connected",
            "success": 1,
        },
    ]
    if includeConnectionLogDriveEvents:
        connectionLogRows.extend([
            {
                "id": 2,
                "timestamp": DRIVE_START_TS.isoformat(),
                "event_type": "drive_start",
                "success": 1,
                "drive_id": driveId,
            },
            {
                "id": 3,
                "timestamp": (
                    realtimeStartTs + timedelta(seconds=realtimeRowCount)
                ).isoformat(),
                "event_type": "drive_end",
                "success": 1,
                "drive_id": driveId,
            },
        ])

    return {
        "deviceId": deviceId,
        "batchId": f"batch-us348-drive-{driveId}",
        "tables": {
            "realtime_data": {
                "lastSyncedId": 0,
                "rows": realtimeRows,
            },
            "connection_log": {
                "lastSyncedId": 0,
                "rows": connectionLogRows,
            },
            "drive_summary": {
                "lastSyncedId": 0,
                "rows": [driveSummaryRow],
            },
        },
    }


@_asyncFixture
async def asyncAppAndEngine():
    """App + real AsyncEngine backed by a file-based aiosqlite DB."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.server.api.app import createApp

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    syncEng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(syncEng)
    syncEng.dispose()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    settings = _makeSettings()
    app = createApp(settings=settings)
    app.state.engine = engine

    try:
        yield app, engine
    finally:
        await engine.dispose()
        Path(tmp.name).unlink(missing_ok=True)


async def _drainPendingAutoAnalysis(analysisModule) -> None:
    """Await any background tasks the auto-analysis path spawned."""
    pending = list(analysisModule._pendingAutoAnalysisTasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


# ==============================================================================
# US-348 / I-040 -- the new acceptance test
# ==============================================================================


@_skipNoAsyncDb
class TestDriveSummaryWriterFiresOnPiSyncRow:
    """drive_summary payload row triggers analytics writer fan-out.

    I-040 false-pass redo discriminator: the writer must run for every
    drive_summary row in the sync payload, even when the corresponding
    connection_log rows in the same sync batch carry no
    drive_start / drive_end events.
    """

    @pytest.mark.asyncio
    async def test_piSyncRowWithoutConnectionLogDriveEvents_writerFires(
        self, asyncAppAndEngine, monkeypatch,
    ):
        """The empirical I-040 scenario: Pi sends drive_summary row, but the
        same sync batch's connection_log has no drive_start / drive_end events
        (only e.g. obd_connected noise).  Pre-fix the writer never fired.
        Post-fix the drive_summary payload itself is a trigger seam."""
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        app, engine = asyncAppAndEngine

        async def fakePing(*_args, **_kwargs):
            return True  # Ollama "reachable" so AI fan-out is exercised.

        monkeypatch.setattr(analysisModule, "pingOllama", fakePing)

        fakeResponse = json.dumps([])  # Empty rec list -- writer runs anyway.
        monkeypatch.setattr(
            analysisModule, "_invokeOllama", lambda **_kw: fakeResponse,
        )

        payload = _buildRealisticPiSyncPayload(
            includeConnectionLogDriveEvents=False,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/sync",
                json=payload,
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 200
        body = response.json()
        # autoAnalysisTriggered=True because the drive_summary payload row
        # now drives the writer.
        assert body["autoAnalysisTriggered"] is True, (
            "Pi-sync drive_summary row must trigger the analytics writer "
            "even when connection_log has no drive_start/drive_end events."
        )

        await _drainPendingAutoAnalysis(analysisModule)

        async with AsyncSession(engine) as session:
            row = (
                await session.execute(
                    select(DriveSummary).where(
                        DriveSummary.source_id == DRIVE_ID,
                    ),
                )
            ).scalar_one()

        # The bug: pre-fix all five fields below were NULL forever.  Post-fix
        # they are populated by the analytics writer, per Spec 3 fields 3-8.
        assert row.start_time is not None, (
            "I-040 regression: start_time stayed NULL on a real Pi-sync round-trip"
        )
        assert row.end_time is not None, (
            "I-040 regression: end_time stayed NULL on a real Pi-sync round-trip"
        )
        assert row.duration_seconds is not None, (
            "I-040 regression: duration_seconds stayed NULL on a "
            "real Pi-sync round-trip"
        )
        assert row.row_count is not None and row.row_count > 0, (
            "I-040 regression: row_count stayed NULL on a real Pi-sync round-trip"
        )
        assert row.is_real is not None, (
            "I-040 regression: is_real stayed NULL on a real Pi-sync round-trip"
        )

        # Sanity: analytics fields are arithmetically consistent with the
        # realtime_data we seeded (120 rows, 1 second stride starting at
        # DRIVE_START_TS+5s).
        assert row.row_count == 120
        assert row.is_real is True  # 120 >= 100 AND all 'real' -> TRUE.
        assert row.duration_seconds == 119  # 120 rows, 1-sec stride.
        # Pi-sync fields preserved -- analytics UPDATE must not clobber 9-12.
        assert row.drive_start_timestamp == DRIVE_START_TS
        assert row.ambient_temp_at_start_c == pytest.approx(18.5)
        assert row.starting_battery_v == pytest.approx(12.7)

    @pytest.mark.asyncio
    async def test_pairedConnectionLogEvents_stillWorkPostFix(
        self, asyncAppAndEngine, monkeypatch,
    ):
        """Regression guard: the existing connection_log trigger seam still
        works when Pi DOES send paired drive_start/drive_end events.  Post-fix
        the two trigger sources are deduped by drive_id, so the writer fires
        exactly once per drive."""
        import httpx
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.server.services import analysis as analysisModule

        app, engine = asyncAppAndEngine

        async def fakePing(*_args, **_kwargs):
            return True

        monkeypatch.setattr(analysisModule, "pingOllama", fakePing)
        monkeypatch.setattr(
            analysisModule, "_invokeOllama", lambda **_kw: json.dumps([]),
        )

        payload = _buildRealisticPiSyncPayload(
            includeConnectionLogDriveEvents=True,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/sync",
                json=payload,
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 200
        await _drainPendingAutoAnalysis(analysisModule)

        async with AsyncSession(engine) as session:
            rows = (
                await session.execute(
                    select(DriveSummary).where(
                        DriveSummary.source_id == DRIVE_ID,
                    ),
                )
            ).scalars().all()

        # Exactly one drive_summary row -- the connection_log trigger seam
        # and the drive_summary-payload trigger seam dedupe by drive_id.
        assert len(rows) == 1, (
            f"Expected 1 drive_summary row, got {len(rows)} "
            f"(dedupe between connection_log + drive_summary trigger seams "
            f"is broken)"
        )
        row = rows[0]
        assert row.row_count == 120
        assert row.is_real is True

    @pytest.mark.asyncio
    async def test_noDriveSummaryRow_noConnectionLogEvents_writerSkips(
        self, asyncAppAndEngine, monkeypatch,
    ):
        """Control: a sync with no drive_summary rows AND no drive_start/
        drive_end events triggers no writer call.  This is the pre-fix
        ``not boundaries`` early-return path, preserved post-fix when both
        trigger seams are empty."""
        import httpx

        from src.server.services import analysis as analysisModule

        app, _engine = asyncAppAndEngine

        async def fakePing(*_args, **_kwargs):
            return True

        monkeypatch.setattr(analysisModule, "pingOllama", fakePing)

        payload = _buildRealisticPiSyncPayload()
        # Strip both trigger seams.
        del payload["tables"]["drive_summary"]
        payload["tables"]["connection_log"]["rows"] = [
            {
                "id": 1,
                "timestamp": DRIVE_START_TS.isoformat(),
                "event_type": "obd_connected",
                "success": 1,
            },
        ]

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/sync",
                json=payload,
                headers={"X-API-Key": "valid-key"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["autoAnalysisTriggered"] is False, (
            "With neither trigger seam carrying drive data, no writer call "
            "should be enqueued."
        )


# ==============================================================================
# Pure-helper test for the new extractor (TDD discriminator for the fix)
# ==============================================================================


class TestExtractDriveIdsFromDriveSummaryPayload:
    """``extractDriveIdsFromDriveSummaryPayload`` collects Pi-side drive_ids."""

    def test_singleRow_returnsSingletonSet(self):
        from src.server.services.analysis import (
            extractDriveIdsFromDriveSummaryPayload,
        )

        rows = [
            {
                "id": 17,
                "drive_start_timestamp": "2026-05-20T18:30:00",
                "ambient_temp_at_start_c": 18.5,
            },
        ]
        assert extractDriveIdsFromDriveSummaryPayload(rows) == {17}

    def test_multipleRows_returnsAllIds(self):
        from src.server.services.analysis import (
            extractDriveIdsFromDriveSummaryPayload,
        )

        rows = [
            {"id": 17},
            {"id": 18},
            {"id": 19},
        ]
        assert extractDriveIdsFromDriveSummaryPayload(rows) == {17, 18, 19}

    def test_emptyList_returnsEmptySet(self):
        from src.server.services.analysis import (
            extractDriveIdsFromDriveSummaryPayload,
        )

        assert extractDriveIdsFromDriveSummaryPayload([]) == set()

    def test_noneRows_treatedAsEmpty(self):
        from src.server.services.analysis import (
            extractDriveIdsFromDriveSummaryPayload,
        )

        assert extractDriveIdsFromDriveSummaryPayload(None) == set()

    def test_nonIntegerIdSkipped(self):
        """Defensive: Pi-side id must be int.  Strings / None get dropped."""
        from src.server.services.analysis import (
            extractDriveIdsFromDriveSummaryPayload,
        )

        rows = [
            {"id": 17},
            {"id": "18"},  # string id -- skipped
            {"id": None},  # null id -- skipped
            {},            # missing id -- skipped
        ]
        assert extractDriveIdsFromDriveSummaryPayload(rows) == {17}
