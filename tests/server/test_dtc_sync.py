################################################################################
# File Name: test_dtc_sync.py
# Purpose/Description: Server-side sync tests for the dtc_log table -- mirrors
#                      Pi schema with source_id rename and (source_device,
#                      source_id) UNIQUE constraint per US-194 pattern (US-204).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-204) | Initial -- DtcLog server model + sync upsert.
# ================================================================================
################################################################################

"""Server-side dtc_log sync tests (US-204).

Covers:
* DtcLog model exists with the right column shape.
* Server sync API accepts dtc_log payload and upserts by
  (source_device, source_id).
* Pi-native ``id`` maps to ``source_id``; ``drive_id`` and
  ``data_source`` are preserved verbatim.
* dtc_log appears in ``ACCEPTED_TABLES`` so the request validator
  doesn't reject it.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.pi.data.sync_log import DELTA_SYNC_TABLES, PK_COLUMN
from src.server.api.sync import ACCEPTED_TABLES, runSyncUpsert
from src.server.db.models import Base, DtcLog

# ================================================================================
# DtcLog model contract
# ================================================================================


class TestDtcLogModelContract:
    """SQLAlchemy DtcLog model mirrors Pi dtc_log schema."""

    def test_modelHasExpectedColumns(self) -> None:
        cols = {c.name for c in DtcLog.__table__.columns}
        expected = {
            'id',
            'source_id',
            'source_device',
            'synced_at',
            'sync_batch_id',
            'dtc_code',
            'description',
            'status',
            'first_seen_timestamp',
            'last_seen_timestamp',
            'drive_id',
            'data_source',
        }
        assert expected.issubset(cols), f"missing columns: {expected - cols}"

    def test_uniqueOnSourceDeviceAndId(self) -> None:
        constraints = [
            c for c in DtcLog.__table__.constraints
            if 'source_device' in [col.name for col in getattr(c, 'columns', [])]
        ]
        assert len(constraints) >= 1, "expected (source_device, source_id) UNIQUE"

    def test_dtcCodeIsRequired(self) -> None:
        col = DtcLog.__table__.columns['dtc_code']
        assert col.nullable is False


# ================================================================================
# Sync registration
# ================================================================================


class TestSyncRegistration:
    """dtc_log is wired into both Pi sync_log and server sync.py."""

    def test_dtcLogInDeltaSyncTables(self) -> None:
        assert 'dtc_log' in DELTA_SYNC_TABLES

    def test_dtcLogPkIsId(self) -> None:
        assert PK_COLUMN['dtc_log'] == 'id'

    def test_dtcLogInAcceptedTables(self) -> None:
        assert 'dtc_log' in ACCEPTED_TABLES


# ================================================================================
# Server upsert behavior
# ================================================================================


def _newSession() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


class TestRunSyncUpsertDtcLog:
    """Pi delta payload lands as upserted server rows."""

    def test_pushesNewRows(self) -> None:
        session = _newSession()
        rows = [
            {
                "id": 1,
                "dtc_code": "P0171",
                "description": "System Too Lean (Bank 1)",
                "status": "stored",
                "first_seen_timestamp": "2026-04-20T12:00:00Z",
                "last_seen_timestamp": "2026-04-20T12:00:00Z",
                "drive_id": 7,
                "data_source": "real",
            },
            {
                "id": 2,
                "dtc_code": "P0420",
                "description": "Cat Efficiency",
                "status": "pending",
                "first_seen_timestamp": "2026-04-20T12:00:00Z",
                "last_seen_timestamp": "2026-04-20T12:00:00Z",
                "drive_id": 7,
                "data_source": "real",
            },
        ]
        result = runSyncUpsert(
            session,
            deviceId="chi-eclipse-01",
            batchId="batch-1",
            tables={"dtc_log": {"rows": rows}},
            syncHistoryId=99,
        )

        assert result["dtc_log"] == {"inserted": 2, "updated": 0, "errors": 0}

        serverRows = session.query(DtcLog).order_by(DtcLog.source_id).all()
        assert len(serverRows) == 2
        assert [r.source_id for r in serverRows] == [1, 2]
        assert [r.dtc_code for r in serverRows] == ["P0171", "P0420"]
        assert serverRows[0].drive_id == 7
        assert serverRows[0].data_source == "real"
        assert serverRows[0].source_device == "chi-eclipse-01"
        assert serverRows[0].sync_batch_id == 99

    def test_secondPushUpdatesExistingRow(self) -> None:
        """Same (device, source_id) on second push -> UPDATE, not INSERT."""
        session = _newSession()
        firstRow = {
            "id": 1, "dtc_code": "P0171", "description": "lean", "status": "stored",
            "first_seen_timestamp": "2026-04-20T12:00:00Z",
            "last_seen_timestamp": "2026-04-20T12:00:00Z",
            "drive_id": 7, "data_source": "real",
        }
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b1",
            tables={"dtc_log": {"rows": [firstRow]}}, syncHistoryId=1,
        )

        # Second push with same id but bumped last_seen_timestamp.
        bumped = dict(firstRow)
        bumped["last_seen_timestamp"] = "2026-04-20T12:05:00Z"
        result = runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b2",
            tables={"dtc_log": {"rows": [bumped]}}, syncHistoryId=2,
        )

        assert result["dtc_log"] == {"inserted": 0, "updated": 1, "errors": 0}

        rows = session.query(DtcLog).all()
        assert len(rows) == 1
        # SQLAlchemy DateTime parsed back as datetime; assert string round-trip
        # via isoformat for cross-portability.
        assert rows[0].last_seen_timestamp.isoformat().endswith("12:05:00")

    def test_separateDevicesGetSeparateRows(self) -> None:
        """Same source_id, different device -> two distinct server rows."""
        session = _newSession()
        row = {
            "id": 1, "dtc_code": "P0171", "description": "lean", "status": "stored",
            "first_seen_timestamp": "2026-04-20T12:00:00Z",
            "last_seen_timestamp": "2026-04-20T12:00:00Z",
            "drive_id": 7, "data_source": "real",
        }
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="a",
            tables={"dtc_log": {"rows": [row]}}, syncHistoryId=1,
        )
        runSyncUpsert(
            session, deviceId="chi-eclipse-02", batchId="b",
            tables={"dtc_log": {"rows": [row]}}, syncHistoryId=2,
        )

        rows = session.query(DtcLog).order_by(DtcLog.source_device).all()
        assert len(rows) == 2
        assert {r.source_device for r in rows} == {"chi-eclipse-01", "chi-eclipse-02"}
