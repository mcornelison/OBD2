################################################################################
# File Name: test_drive_summary_sync.py
# Purpose/Description: Server-side sync tests for drive_summary (US-206).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-206) | Initial -- DriveSummary Pi-mirror + sync upsert.
# ================================================================================
################################################################################

"""Server-side drive_summary sync tests (US-206).

Verifies the DriveSummary model carries the US-206 metadata columns,
preserves the pre-US-206 analytics columns (nullable), and that the
Pi-sync upsert-by-(source_device, source_id) path lands Pi rows
correctly.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.pi.data.sync_log import DELTA_SYNC_TABLES, PK_COLUMN
from src.server.api.sync import ACCEPTED_TABLES, runSyncUpsert
from src.server.db.models import Base, DriveSummary

# ================================================================================
# DriveSummary model contract
# ================================================================================


class TestDriveSummaryModelContract:
    """DriveSummary carries both analytics and Pi-sync columns."""

    def test_modelHasAnalyticsColumns(self) -> None:
        cols = {c.name for c in DriveSummary.__table__.columns}
        analytics = {
            'id', 'device_id', 'start_time', 'end_time', 'duration_seconds',
            'profile_id', 'row_count', 'is_real', 'created_at', 'data_source',
        }
        assert analytics.issubset(cols), f"missing analytics cols: {analytics - cols}"

    def test_modelHasUs206MetadataColumns(self) -> None:
        cols = {c.name for c in DriveSummary.__table__.columns}
        us206 = {
            'source_id', 'source_device', 'synced_at', 'sync_batch_id',
            'drive_start_timestamp', 'ambient_temp_at_start_c',
            'starting_battery_v', 'barometric_kpa_at_start', 'drive_id',
        }
        assert us206.issubset(cols), f"missing US-206 cols: {us206 - cols}"

    def test_hasUniqueSourceDeviceSourceId(self) -> None:
        constraints = [
            c for c in DriveSummary.__table__.constraints
            if 'source_device' in [col.name for col in getattr(c, 'columns', [])]
        ]
        assert len(constraints) >= 1, (
            "expected UNIQUE(source_device, source_id) for Pi-sync path"
        )

    def test_startTimeIsNullable(self) -> None:
        """Pi-sync path needs to leave start_time NULL until analytics fills it."""
        col = DriveSummary.__table__.columns['start_time']
        assert col.nullable is True


# ================================================================================
# Sync registration
# ================================================================================


class TestSyncRegistration:
    """drive_summary is wired into both Pi sync_log and server sync.py."""

    def test_driveSummaryInDeltaSyncTables(self) -> None:
        assert 'drive_summary' in DELTA_SYNC_TABLES

    def test_driveSummaryPkIsDriveId(self) -> None:
        assert PK_COLUMN['drive_summary'] == 'drive_id'

    def test_driveSummaryInAcceptedTables(self) -> None:
        assert 'drive_summary' in ACCEPTED_TABLES


# ================================================================================
# Server upsert behavior
# ================================================================================


def _newSession() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


class TestRunSyncUpsertDriveSummary:
    """Pi delta payload lands as upserted server rows."""

    def test_pushesNewRow(self) -> None:
        session = _newSession()
        # The Pi sync client's _renamePkToId renames drive_id -> id on
        # the wire for tables with a non-id PK, so the runSyncUpsert
        # input arrives with "id" -- the server maps it to source_id.
        rows = [
            {
                "id": 7,
                "drive_start_timestamp": "2026-04-20T12:00:00Z",
                "ambient_temp_at_start_c": 18.5,
                "starting_battery_v": 12.4,
                "barometric_kpa_at_start": 101.2,
                "data_source": "real",
            },
        ]
        result = runSyncUpsert(
            session,
            deviceId="chi-eclipse-01",
            batchId="batch-1",
            tables={"drive_summary": {"rows": rows}},
            syncHistoryId=99,
        )

        assert result["drive_summary"] == {"inserted": 1, "updated": 0, "errors": 0}

        serverRow = session.query(DriveSummary).one()
        assert serverRow.source_id == 7
        assert serverRow.source_device == "chi-eclipse-01"
        assert serverRow.ambient_temp_at_start_c == 18.5
        assert serverRow.starting_battery_v == 12.4
        assert serverRow.barometric_kpa_at_start == 101.2
        assert serverRow.data_source == "real"
        assert serverRow.sync_batch_id == 99

    def test_secondPushUpdatesSameRow(self) -> None:
        """Same (device, source_id) on second push -> UPDATE, not INSERT."""
        session = _newSession()
        first = {
            "id": 8,
            "drive_start_timestamp": "2026-04-20T12:00:00Z",
            "ambient_temp_at_start_c": 18.5,
            "starting_battery_v": 12.4,
            "barometric_kpa_at_start": 101.2,
            "data_source": "real",
        }
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b1",
            tables={"drive_summary": {"rows": [first]}}, syncHistoryId=1,
        )

        second = dict(first)
        second["starting_battery_v"] = 12.9
        result = runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b2",
            tables={"drive_summary": {"rows": [second]}}, syncHistoryId=2,
        )
        assert result["drive_summary"] == {"inserted": 0, "updated": 1, "errors": 0}

        rows = session.query(DriveSummary).all()
        assert len(rows) == 1
        assert rows[0].starting_battery_v == 12.9

    def test_warmRestartRowHasNullAmbient(self) -> None:
        """Pi-sent warm-restart row preserves NULL ambient server-side."""
        session = _newSession()
        rows = [
            {
                "id": 9,
                "drive_start_timestamp": "2026-04-20T13:00:00Z",
                "ambient_temp_at_start_c": None,  # Pi wrote NULL (warm restart)
                "starting_battery_v": 13.6,
                "barometric_kpa_at_start": 100.9,
                "data_source": "real",
            },
        ]
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="b",
            tables={"drive_summary": {"rows": rows}}, syncHistoryId=1,
        )

        row = session.query(DriveSummary).one()
        assert row.ambient_temp_at_start_c is None
        assert row.starting_battery_v == 13.6

    def test_separateDevicesGetSeparateRows(self) -> None:
        """Same drive_id from two devices -> two distinct server rows."""
        session = _newSession()
        row = {
            "id": 1,
            "drive_start_timestamp": "2026-04-20T12:00:00Z",
            "ambient_temp_at_start_c": 20.0,
            "starting_battery_v": 12.5,
            "barometric_kpa_at_start": 101.0,
            "data_source": "real",
        }
        runSyncUpsert(
            session, deviceId="chi-eclipse-01", batchId="a",
            tables={"drive_summary": {"rows": [row]}}, syncHistoryId=1,
        )
        runSyncUpsert(
            session, deviceId="chi-eclipse-02", batchId="b",
            tables={"drive_summary": {"rows": [row]}}, syncHistoryId=2,
        )

        rows = session.query(DriveSummary).order_by(
            DriveSummary.source_device
        ).all()
        assert len(rows) == 2
        assert {r.source_device for r in rows} == {
            "chi-eclipse-01", "chi-eclipse-02",
        }
