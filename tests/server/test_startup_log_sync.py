################################################################################
# File Name: test_startup_log_sync.py
# Purpose/Description: US-417 tests -- register startup_log onto the natural-key
#                      SNAPSHOT_SYNC path (closes BL-013). Verifies the shared
#                      registration (boot_id / recorded_at), the server StartupLog
#                      model shape (UNIQUE(source_device, boot_id), no source_id),
#                      that runSyncUpsert routes startup_log through the natural-key
#                      resolver with the REAL model, idempotency on re-sync, and
#                      that the v0014 server migration is registered + creates the
#                      table with the UNIQUE constraint.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-417) | Initial -- startup_log snapshot-sync registration.
# ================================================================================
################################################################################

"""US-417 startup_log snapshot-sync registration tests."""

from __future__ import annotations

from sqlalchemy import UniqueConstraint, create_engine
from sqlalchemy.orm import Session

from src.common.sync.snapshot_registry import (
    SNAPSHOT_SYNC,
    getSnapshotSpec,
    isSnapshotSyncTable,
)
from src.server.api.sync import (
    _SNAPSHOT_TABLE_REGISTRY,
    acceptedTables,
    runSyncUpsert,
)
from src.server.db.models import Base, StartupLog
from src.server.migrations import ALL_MIGRATIONS

_TABLE = "startup_log"


def _piBootRow(bootId: str, recordedAt: str) -> dict:
    """A Pi-native startup_log row as it lands in the sync payload."""
    return {
        "boot_id": bootId,
        "prior_boot_clean": 1,
        "prior_last_entry_ts": "2026-06-30T23:59:00Z",
        "current_boot_first_entry_ts": "2026-07-01T00:00:01Z",
        "prior_boot_last_stage": "shutdown_complete",
        "prior_boot_reason": "clean_shutdown",
        "recorded_at": recordedAt,
    }


def _newSession() -> Session:
    engine = create_engine("sqlite:///:memory:")
    StartupLog.__table__.create(engine)
    return Session(engine)


class TestStartupLogRegistration:
    """startup_log is a permanent registrant of the shared SNAPSHOT_SYNC (A-4)."""

    def test_registeredWithBootIdNaturalKey(self) -> None:
        assert isSnapshotSyncTable(_TABLE) is True
        spec = getSnapshotSpec(_TABLE)
        assert spec.naturalKeyCols == ("boot_id",)
        assert spec.cursorCol == "recorded_at"

    def test_liveInSharedRegistryDict(self) -> None:
        # The registration lives in the shared dict, not a per-tier copy.
        assert _TABLE in SNAPSHOT_SYNC


class TestStartupLogModel:
    """The server model carries the natural-key UNIQUE + no source_id."""

    def test_tableName(self) -> None:
        assert StartupLog.__tablename__ == "startup_log"

    def test_uniqueOnSourceDeviceAndBootId(self) -> None:
        uniques = [
            tuple(col.name for col in c.columns)
            for c in StartupLog.__table__.constraints
            if isinstance(c, UniqueConstraint)
        ]
        assert ("source_device", "boot_id") in uniques

    def test_hasNoSourceId(self) -> None:
        # Natural-key dedup -- there is no id->source_id mapping (distinct from
        # the generic delta registry path).
        cols = {c.name for c in StartupLog.__table__.columns}
        assert "source_id" not in cols

    def test_mirrorsPiColumns(self) -> None:
        cols = {c.name for c in StartupLog.__table__.columns}
        assert {
            "id",
            "source_device",
            "boot_id",
            "prior_boot_clean",
            "prior_last_entry_ts",
            "current_boot_first_entry_ts",
            "prior_boot_last_stage",
            "prior_boot_reason",
            "recorded_at",
            "sync_batch_id",
            "synced_at",
        } <= cols

    def test_registeredInServerSnapshotRegistry(self) -> None:
        assert _SNAPSHOT_TABLE_REGISTRY.get(_TABLE) is StartupLog

    def test_acceptedByPayloadWhitelist(self) -> None:
        assert _TABLE in acceptedTables()


class TestStartupLogUpsert:
    """runSyncUpsert routes startup_log through the natural-key resolver."""

    def test_insertsThenRowsMatchPi(self) -> None:
        session = _newSession()
        rows = [
            _piBootRow("boot-a", "2026-07-01T10:00:00Z"),
            _piBootRow("boot-b", "2026-07-01T11:00:00Z"),
        ]
        result = runSyncUpsert(
            session,
            deviceId="chi-eclipse-01",
            batchId="b1",
            tables={_TABLE: {"rows": rows}},
            syncHistoryId=5,
        )
        assert result[_TABLE] == {"inserted": 2, "updated": 0, "errors": 0}
        assert session.query(StartupLog).count() == 2
        landed = session.query(StartupLog).filter_by(boot_id="boot-a").one()
        assert landed.source_device == "chi-eclipse-01"
        assert landed.prior_boot_reason == "clean_shutdown"
        assert landed.sync_batch_id == 5

    def test_reSyncIsIdempotentOnNaturalKey(self) -> None:
        session = _newSession()
        rows = [_piBootRow("boot-a", "2026-07-01T10:00:00Z")]
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b1",
            tables={_TABLE: {"rows": rows}}, syncHistoryId=1,
        )
        # The Pi cursor over-reads and re-pushes the same boot row.
        second = runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b2",
            tables={_TABLE: {"rows": [dict(rows[0])]}}, syncHistoryId=2,
        )
        assert second[_TABLE] == {"inserted": 0, "updated": 1, "errors": 0}
        # No duplicate row on the natural key.
        assert session.query(StartupLog).count() == 1

    def test_sameBootIdDifferentDevicesCoexist(self) -> None:
        session = _newSession()
        row = _piBootRow("shared-boot", "2026-07-01T10:00:00Z")
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b1",
            tables={_TABLE: {"rows": [dict(row)]}}, syncHistoryId=1,
        )
        runSyncUpsert(
            session, deviceId="pi-scratch", batchId="b2",
            tables={_TABLE: {"rows": [dict(row)]}}, syncHistoryId=2,
        )
        assert session.query(StartupLog).count() == 2


class TestServerMigrationRegistered:
    """A v0014 migration creates startup_log with the UNIQUE constraint."""

    def test_v0014InRegistry(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert "0014" in versions

    def test_v0014CreatesStartupLogWithUniqueKey(self) -> None:
        from src.server.migrations.versions.v0014_us417_startup_log import (
            _CREATE_STARTUP_LOG,
        )

        ddl = _CREATE_STARTUP_LOG.lower()
        assert "startup_log" in ddl
        assert "boot_id" in ddl
        assert "source_device" in ddl
        # natural-key UNIQUE(source_device, boot_id) -- the dedup anchor.
        assert "unique" in ddl
        assert "source_id" not in ddl


def test_baseMetadataCarriesStartupLog() -> None:
    """The model is registered on the production Base metadata (create_all)."""
    assert "startup_log" in Base.metadata.tables
