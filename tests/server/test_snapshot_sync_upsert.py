################################################################################
# File Name: test_snapshot_sync_upsert.py
# Purpose/Description: Server-side tests for the natural-key SNAPSHOT upsert path
#                      (US-416 / F-101). Verifies runSnapshotUpsert dedups on
#                      (source_device, *naturalKeyCols), two sync cycles are
#                      idempotent (no duplicates), different devices don't collide,
#                      runSyncUpsert routes registered snapshot tables, and the
#                      payload whitelist (acceptedTables) honours registrations.
#                      Uses a throwaway test model on a private Base so production
#                      metadata stays clean.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-416) | Initial -- natural-key snapshot upsert tests.
# ================================================================================
################################################################################

"""Server natural-key snapshot-upsert tests (US-416)."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import (
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

import src.server.api.sync as server_sync
from src.common.sync.snapshot_registry import SNAPSHOT_SYNC, SnapshotSyncSpec
from src.server.api.sync import (
    SyncRequest,
    acceptedTables,
    runSnapshotUpsert,
    runSyncUpsert,
)

_TABLE = "test_startup_log"


class _TestBase(DeclarativeBase):
    """Private declarative base so the test model never touches production metadata."""


class _StartupLogTest(_TestBase):
    """Mirror of the shape US-417 will build for startup_log (TEXT boot_id key)."""

    __tablename__ = _TABLE
    __table_args__ = (UniqueConstraint("source_device", "boot_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_device: Mapped[str] = mapped_column(String(64), nullable=False)
    boot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[str | None] = mapped_column(String(40))
    boot_reason: Mapped[str | None] = mapped_column(String(64))
    sync_batch_id: Mapped[int | None] = mapped_column(Integer)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)


@pytest.fixture
def registerSnapshot() -> object:
    """Register the test table in BOTH the shared spec registry + server models."""
    SNAPSHOT_SYNC[_TABLE] = SnapshotSyncSpec(
        naturalKeyCols=("boot_id",), cursorCol="recorded_at",
    )
    server_sync._SNAPSHOT_TABLE_REGISTRY[_TABLE] = _StartupLogTest
    try:
        yield
    finally:
        SNAPSHOT_SYNC.pop(_TABLE, None)
        server_sync._SNAPSHOT_TABLE_REGISTRY.pop(_TABLE, None)


def _newSession() -> Session:
    engine = create_engine("sqlite:///:memory:")
    _TestBase.metadata.create_all(engine)
    return Session(engine)


def _piRow(bootId: str, recordedAt: str) -> dict:
    return {
        "boot_id": bootId,
        "recorded_at": recordedAt,
        "boot_reason": "power_on",
    }


class TestRunSnapshotUpsert:
    """Natural-key dedup + idempotent re-sync (the acceptance heart of US-416)."""

    def test_insertsNewRows(self, registerSnapshot: object) -> None:
        session = _newSession()
        rows = [
            _piRow("boot-a", "2026-07-01T10:00:00Z"),
            _piRow("boot-b", "2026-07-01T11:00:00Z"),
        ]
        result = runSnapshotUpsert(
            session, "chi-eclipse-01", _TABLE, _StartupLogTest, rows, 7,
        )
        assert result == {"inserted": 2, "updated": 0, "errors": 0}
        assert session.query(_StartupLogTest).count() == 2
        landed = session.query(_StartupLogTest).filter_by(boot_id="boot-a").one()
        assert landed.source_device == "chi-eclipse-01"
        assert landed.boot_reason == "power_on"
        assert landed.sync_batch_id == 7

    def test_twoSyncCyclesAreIdempotent(self, registerSnapshot: object) -> None:
        """Re-pushing the same natural keys UPDATEs -- never a duplicate row."""
        session = _newSession()
        rows = [
            _piRow("boot-a", "2026-07-01T10:00:00Z"),
            _piRow("boot-b", "2026-07-01T11:00:00Z"),
        ]
        # Cycle 1: both insert.
        first = runSnapshotUpsert(
            session, "chi-eclipse-01", _TABLE, _StartupLogTest, rows, 1,
        )
        assert first == {"inserted": 2, "updated": 0, "errors": 0}
        # Cycle 2: the Pi cursor over-reads and re-pushes the same rows.
        second = runSnapshotUpsert(
            session, "chi-eclipse-01", _TABLE, _StartupLogTest,
            [dict(r) for r in rows], 2,
        )
        assert second == {"inserted": 0, "updated": 2, "errors": 0}
        # No duplicates: still exactly 2 rows.
        assert session.query(_StartupLogTest).count() == 2

    def test_partialOverlapCountsCorrectly(self, registerSnapshot: object) -> None:
        session = _newSession()
        runSnapshotUpsert(
            session, "chi-eclipse-01", _TABLE, _StartupLogTest,
            [_piRow("boot-a", "2026-07-01T10:00:00Z")], 1,
        )
        result = runSnapshotUpsert(
            session, "chi-eclipse-01", _TABLE, _StartupLogTest,
            [
                _piRow("boot-a", "2026-07-01T10:00:00Z"),  # existing -> update
                _piRow("boot-c", "2026-07-01T12:00:00Z"),  # new -> insert
            ],
            2,
        )
        assert result == {"inserted": 1, "updated": 1, "errors": 0}
        assert session.query(_StartupLogTest).count() == 2

    def test_differentDevicesDoNotCollide(self, registerSnapshot: object) -> None:
        """Same boot_id from two devices -> two rows (device is half the key)."""
        session = _newSession()
        row = _piRow("shared-boot", "2026-07-01T10:00:00Z")
        runSnapshotUpsert(
            session, "chi-eclipse-01", _TABLE, _StartupLogTest, [dict(row)], 1,
        )
        runSnapshotUpsert(
            session, "pi-dev-scratchpad", _TABLE, _StartupLogTest, [dict(row)], 2,
        )
        assert session.query(_StartupLogTest).count() == 2

    def test_dropsPiIdColumn(self, registerSnapshot: object) -> None:
        """A stray Pi 'id' must not overwrite the server autoincrement PK."""
        session = _newSession()
        row = _piRow("boot-a", "2026-07-01T10:00:00Z")
        row["id"] = 999  # should be dropped, not written as server id
        runSnapshotUpsert(
            session, "chi-eclipse-01", _TABLE, _StartupLogTest, [row], 1,
        )
        landed = session.query(_StartupLogTest).one()
        assert landed.id != 999
        assert landed.boot_id == "boot-a"

    def test_emptyRowsIsNoOp(self, registerSnapshot: object) -> None:
        session = _newSession()
        result = runSnapshotUpsert(
            session, "chi-eclipse-01", _TABLE, _StartupLogTest, [], 1,
        )
        assert result == {"inserted": 0, "updated": 0, "errors": 0}


class TestRunSyncUpsertRouting:
    """runSyncUpsert dispatches registered snapshot tables to the natural-key path."""

    def test_routesSnapshotTable(self, registerSnapshot: object) -> None:
        session = _newSession()
        result = runSyncUpsert(
            session,
            deviceId="chi-eclipse-01",
            batchId="b1",
            tables={_TABLE: {"rows": [_piRow("boot-a", "2026-07-01T10:00:00Z")]}},
            syncHistoryId=1,
        )
        assert result[_TABLE] == {"inserted": 1, "updated": 0, "errors": 0}
        assert session.query(_StartupLogTest).count() == 1

    def test_missingModelRaises(self) -> None:
        """A spec registered without a server model must fail loudly."""
        SNAPSHOT_SYNC[_TABLE] = SnapshotSyncSpec(("boot_id",), "recorded_at")
        try:
            session = _newSession()
            with pytest.raises(ValueError, match="no server model registered"):
                runSyncUpsert(
                    session,
                    deviceId="chi-eclipse-01",
                    batchId="b1",
                    tables={_TABLE: {"rows": [_piRow("b", "2026-07-01T10:00:00Z")]}},
                    syncHistoryId=1,
                )
        finally:
            SNAPSHOT_SYNC.pop(_TABLE, None)


class TestAcceptedTables:
    """The payload whitelist honours snapshot-sync registrations dynamically."""

    def test_registeredTableIsAccepted(self, registerSnapshot: object) -> None:
        assert _TABLE in acceptedTables()

    def test_syncRequestAcceptsRegisteredTable(
        self, registerSnapshot: object,
    ) -> None:
        req = SyncRequest.model_validate({
            "deviceId": "chi-eclipse-01",
            "batchId": "b1",
            "tables": {_TABLE: {"rows": [_piRow("b", "2026-07-01T10:00:00Z")]}},
        })
        assert _TABLE in req.tables

    def test_syncRequestRejectsUnregisteredTable(self) -> None:
        with pytest.raises(ValueError, match="Unknown table name"):
            SyncRequest.model_validate({
                "deviceId": "chi-eclipse-01",
                "batchId": "b1",
                "tables": {"totally_unknown": {"rows": []}},
            })
