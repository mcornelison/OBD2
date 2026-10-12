################################################################################
# File Name: test_sync_residual_groups.py
# Purpose/Description: US-795(a) -- the residual carries a drive/sensor split,
#                      and it is stored with the same typed-absence discipline
#                      as the total: absent means unknown, never 0.
# Author: Atlas (Architect) -- US-795(a), CIO-directed build
# Creation Date: 2026-10-06
################################################################################
"""The residual's drive/sensor split (US-795(a), CIO ruling 2026-10-06).

The CIO ruled that the queue the server reports is EVERYTHING unsynced, stated
as a total plus a split: ``drive`` (the car's own records) and ``sensor`` (the
EDR archive, ``src/common/edr/sync_contract.EDR_SYNC_TABLES``). The split rides
inside the existing ``residual`` object as an OPTIONAL ``groups`` field, so a
Pi that predates it still syncs, and it lands in two nullable columns added by
v0036 -- for the same reason ``residual_rows`` has no default: a split nobody
measured must read back as unknown.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import create_engine, inspect, select, text  # noqa: E402

from src.server.api.sync import (  # noqa: E402
    ResidualGroups,
    ResidualReport,
    SyncRequest,
    _completeSyncHistoryRow,
    _createSyncHistoryRow,
    residualColumnValues,
)
from src.server.db.models import Base, SyncHistory  # noqa: E402

try:
    import aiosqlite as _aiosqlite  # noqa: F401

    _HAS_AIOSQLITE = True
except ImportError:  # pragma: no cover
    _HAS_AIOSQLITE = False

_skipNoAsyncDb = pytest.mark.skipif(not _HAS_AIOSQLITE, reason="aiosqlite not installed")


def _request(residual: dict | None) -> dict:
    body: dict = {
        "deviceId": "chi-eclipse-01",
        "batchId": "b1",
        "tables": {"realtime_data": {"lastSyncedId": 0, "rows": []}},
    }
    if residual is not None:
        body["residual"] = residual
    return body


class TestTheWireAcceptsTheSplit:

    def test_aResidualWithGroups_isAccepted(self) -> None:
        req = SyncRequest(**_request({
            "outstandingRows": 1200, "complete": True,
            "groups": {"drive": 200, "sensor": 1000},
        }))
        assert req.residual.groups == ResidualGroups(drive=200, sensor=1000)

    def test_aResidualWithoutGroups_isStillAccepted_soAnOlderPiKeepsSyncing(self) -> None:
        req = SyncRequest(**_request({"outstandingRows": 5, "complete": True}))
        assert req.residual.groups is None

    def test_anUnknownGroup_isRejected(self) -> None:
        """extra='forbid' like every other wire model: a typo is not silently dropped."""
        with pytest.raises(ValidationError):
            ResidualReport(outstandingRows=1, complete=True,
                           groups={"drive": 1, "sensor": 0, "other": 0})

    def test_aNegativeGroup_isRejected(self) -> None:
        with pytest.raises(ValidationError):
            ResidualGroups(drive=-1, sensor=0)


class TestTheSplitHasNoDefault:

    def test_bothColumnsAreNullableWithNoDefault(self) -> None:
        columns = {c.name: c for c in SyncHistory.__table__.columns}
        for name in ("residual_drive_rows", "residual_sensor_rows"):
            assert columns[name].nullable, name
            assert columns[name].default is None, name
            assert columns[name].server_default is None, name


class TestTheColumnValues:
    """The writer's mapping, tested without an async database (the venv has no
    aiosqlite, so the async writer tests below skip on a bench)."""

    def test_theSplitIsWrittenWhenMeasured(self) -> None:
        values = residualColumnValues(ResidualReport(
            outstandingRows=1200, complete=False,
            groups=ResidualGroups(drive=200, sensor=1000),
        ))
        assert values == {
            "residual_rows": 1200, "residual_complete": False,
            "residual_drive_rows": 200, "residual_sensor_rows": 1000,
        }

    def test_noGroups_writesNoSplit(self) -> None:
        assert residualColumnValues(ResidualReport(outstandingRows=7, complete=True)) == {
            "residual_rows": 7, "residual_complete": True,
        }

    def test_noResidual_writesNothing(self) -> None:
        assert residualColumnValues(None) == {}


async def _completed(residual: ResidualReport | None) -> SyncHistory:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    syncEng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(syncEng)
    syncEng.dispose()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.name}")
    try:
        historyId = await _createSyncHistoryRow(engine, "chi-eclipse-01")
        await _completeSyncHistoryRow(
            engine, historyId,
            {"realtime_data": {"inserted": 1, "updated": 0, "errors": 0}},
            datetime.now(UTC).replace(tzinfo=None),
            residual,
        )
        async with AsyncSession(engine) as session:
            return (await session.execute(
                select(SyncHistory).where(SyncHistory.id == historyId),
            )).scalar_one()
    finally:
        await engine.dispose()
        Path(tmp.name).unlink(missing_ok=True)


@_skipNoAsyncDb
@pytest.mark.asyncio
async def test_theWriterStoresTheSplit() -> None:
    row = await _completed(ResidualReport(
        outstandingRows=1200, complete=True,
        groups=ResidualGroups(drive=200, sensor=1000),
    ))
    assert (row.residual_rows, row.residual_drive_rows, row.residual_sensor_rows) == (1200, 200, 1000)


@_skipNoAsyncDb
@pytest.mark.asyncio
async def test_noGroups_leavesTheSplitUnknown_notZero() -> None:
    row = await _completed(ResidualReport(outstandingRows=7, complete=True))
    assert row.residual_rows == 7
    assert row.residual_drive_rows is None
    assert row.residual_sensor_rows is None


class TestV0036:

    def test_registeredAfterV0035_andAddsBothColumns(self) -> None:
        from src.server.migrations import ALL_MIGRATIONS
        from src.server.migrations.versions.v0036_us795a_sync_history_residual_groups import (
            ADD_RESIDUAL_DRIVE_ROWS_DDL,
            ADD_RESIDUAL_SENSOR_ROWS_DDL,
            MIGRATION,
        )

        versions = [m.version for m in ALL_MIGRATIONS]
        assert MIGRATION.version == "0036"
        # Placement, never the absolute tail (TD-062).
        assert versions.index("0036") == versions.index("0035") + 1

        eng = create_engine("sqlite://")
        with eng.begin() as conn:
            conn.execute(text(
                "CREATE TABLE sync_history (id INTEGER PRIMARY KEY, "
                "device_id VARCHAR(64) NOT NULL, residual_rows INTEGER)"
            ))
            conn.execute(text("INSERT INTO sync_history (device_id, residual_rows) VALUES ('old', 3)"))
            for ddl in (ADD_RESIDUAL_DRIVE_ROWS_DDL, ADD_RESIDUAL_SENSOR_ROWS_DDL):
                conn.execute(text(ddl.rstrip(";")))
            old = conn.execute(text(
                "SELECT residual_rows, residual_drive_rows, residual_sensor_rows FROM sync_history",
            )).one()

        names = {c["name"] for c in inspect(eng).get_columns("sync_history")}
        assert {"residual_drive_rows", "residual_sensor_rows"} <= names
        # Non-destructive: an existing row keeps its total and reads the split as unknown.
        assert tuple(old) == (3, None, None)


class TestThePiAndServerAgreeOnTheShape:
    """WIRING across the tiers: the exact dict the Pi builds must validate on
    the server. Both sides are extra='forbid', so one renamed key would make
    the server REJECT EVERY PUSH -- the failure mode that orders the deploy
    (server before Pi)."""

    def test_whatThePiBuilds_theServerAccepts(self) -> None:
        from src.common.edr.sync_contract import EDR_SYNC_TABLES
        from src.pi.sync.backlog import SyncBacklog, residualAfterBatch

        built = residualAfterBatch(
            SyncBacklog(perTable={"realtime_data": 900, EDR_SYNC_TABLES[0]: 300},
                        unreadableTables=("dtc_log",)),
            batchTable="realtime_data", batchNewRows=500, sensorTables=EDR_SYNC_TABLES,
        )
        report = ResidualReport.model_validate(built)

        assert report.outstandingRows == 700
        assert report.complete is False
        assert report.groups == ResidualGroups(drive=400, sensor=300)
        assert residualColumnValues(report) == {
            "residual_rows": 700, "residual_complete": False,
            "residual_drive_rows": 400, "residual_sensor_rows": 300,
        }
