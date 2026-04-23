################################################################################
# File Name: test_battery_health_log_sync.py
# Purpose/Description: Server-side sync tests for battery_health_log (US-217).
#                      Verifies the BatteryHealthLog SQLAlchemy model carries
#                      the right columns, that the Pi-side sync registration
#                      names drain_event_id as the PK, and that runSyncUpsert
#                      lands + upserts drain-event rows keyed on
#                      (source_device, source_id).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-217) | Initial -- BatteryHealthLog Pi-mirror + sync.
# ================================================================================
################################################################################

"""Server-side battery_health_log sync tests (US-217)."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.pi.data.sync_log import DELTA_SYNC_TABLES, PK_COLUMN
from src.server.api.sync import ACCEPTED_TABLES, runSyncUpsert
from src.server.db.models import Base, BatteryHealthLog

# ================================================================================
# Model contract
# ================================================================================


class TestBatteryHealthLogModelContract:
    """BatteryHealthLog mirrors the Pi schema + carries the sync columns."""

    def test_modelHasPiNativeColumns(self) -> None:
        cols = {c.name for c in BatteryHealthLog.__table__.columns}
        pi = {
            'start_timestamp', 'end_timestamp',
            'start_soc', 'end_soc',
            'runtime_seconds', 'ambient_temp_c',
            'load_class', 'notes', 'data_source',
        }
        assert pi.issubset(cols), f"missing Pi-native cols: {pi - cols}"

    def test_modelHasSyncColumns(self) -> None:
        cols = {c.name for c in BatteryHealthLog.__table__.columns}
        sync = {'id', 'source_id', 'source_device', 'synced_at',
                'sync_batch_id'}
        assert sync.issubset(cols), f"missing sync cols: {sync - cols}"

    def test_hasUniqueSourceDeviceSourceId(self) -> None:
        constraints = [
            c for c in BatteryHealthLog.__table__.constraints
            if 'source_device' in [
                col.name for col in getattr(c, 'columns', [])
            ]
        ]
        assert len(constraints) >= 1, (
            'expected UNIQUE(source_device, source_id) for Pi-sync path'
        )

    def test_startSocIsNotNull(self) -> None:
        col = BatteryHealthLog.__table__.columns['start_soc']
        assert col.nullable is False

    def test_endSocIsNullable(self) -> None:
        col = BatteryHealthLog.__table__.columns['end_soc']
        assert col.nullable is True

    def test_loadClassDefaultIsProduction(self) -> None:
        col = BatteryHealthLog.__table__.columns['load_class']
        default = col.server_default
        assert default is not None
        assert 'production' in str(default.arg)


# ================================================================================
# Sync registration
# ================================================================================


class TestSyncRegistration:
    """battery_health_log is wired into both Pi sync_log + server sync."""

    def test_batteryHealthLogInDeltaSyncTables(self) -> None:
        assert 'battery_health_log' in DELTA_SYNC_TABLES

    def test_batteryHealthLogPkIsDrainEventId(self) -> None:
        assert PK_COLUMN['battery_health_log'] == 'drain_event_id'

    def test_batteryHealthLogInAcceptedTables(self) -> None:
        assert 'battery_health_log' in ACCEPTED_TABLES


# ================================================================================
# Sync upsert behavior
# ================================================================================


def _newSession() -> Session:
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return Session(engine)


class TestRunSyncUpsertBatteryHealthLog:
    """Pi delta rows land as upserted server rows keyed on (device, source_id)."""

    def test_pushesNewRow(self) -> None:
        session = _newSession()
        # The Pi sync client's _renamePkToId renames drain_event_id -> id
        # on the wire for tables with a non-id PK, so runSyncUpsert
        # receives 'id' -> which it maps to source_id.
        rows = [
            {
                'id': 5,
                'start_timestamp': '2026-04-21T12:00:00Z',
                'end_timestamp': '2026-04-21T12:24:00Z',
                'start_soc': 100.0,
                'end_soc': 20.0,
                'runtime_seconds': 1440,
                'ambient_temp_c': 22.5,
                'load_class': 'test',
                'notes': 'April baseline drill',
                'data_source': 'real',
            },
        ]
        result = runSyncUpsert(
            session,
            deviceId='chi-eclipse-01',
            batchId='batch-1',
            tables={'battery_health_log': {'rows': rows}},
            syncHistoryId=99,
        )

        assert result['battery_health_log'] == {
            'inserted': 1, 'updated': 0, 'errors': 0,
        }

        serverRow = session.query(BatteryHealthLog).one()
        assert serverRow.source_id == 5
        assert serverRow.source_device == 'chi-eclipse-01'
        assert serverRow.start_soc == 100.0
        assert serverRow.end_soc == 20.0
        assert serverRow.runtime_seconds == 1440
        assert serverRow.ambient_temp_c == 22.5
        assert serverRow.load_class == 'test'
        assert serverRow.notes == 'April baseline drill'
        assert serverRow.data_source == 'real'
        assert serverRow.sync_batch_id == 99

    def test_secondPushUpdatesSameRow(self) -> None:
        """Same (device, source_id) on second push -> UPDATE, not INSERT."""
        session = _newSession()
        first = {
            'id': 6,
            'start_timestamp': '2026-04-21T12:00:00Z',
            'end_timestamp': '2026-04-21T12:24:00Z',
            'start_soc': 100.0,
            'end_soc': 20.0,
            'runtime_seconds': 1440,
            'load_class': 'test',
            'data_source': 'real',
        }
        runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b1',
            tables={'battery_health_log': {'rows': [first]}},
            syncHistoryId=1,
        )

        # Second push with updated end_soc + runtime on the same row.
        second = dict(first)
        second['end_soc'] = 18.5
        second['runtime_seconds'] = 1280
        result = runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b2',
            tables={'battery_health_log': {'rows': [second]}},
            syncHistoryId=2,
        )

        assert result['battery_health_log'] == {
            'inserted': 0, 'updated': 1, 'errors': 0,
        }
        serverRow = session.query(BatteryHealthLog).one()
        assert serverRow.end_soc == 18.5
        assert serverRow.runtime_seconds == 1280

    def test_pushPreClosedRowOmitsEndColumns(self) -> None:
        """Pi can push a still-open event with end_timestamp/end_soc NULL."""
        session = _newSession()
        rows = [
            {
                'id': 7,
                'start_timestamp': '2026-04-21T12:00:00Z',
                'start_soc': 100.0,
                'load_class': 'production',
                'data_source': 'real',
            },
        ]
        runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b1',
            tables={'battery_health_log': {'rows': rows}},
            syncHistoryId=1,
        )
        serverRow = session.query(BatteryHealthLog).one()
        assert serverRow.end_timestamp is None
        assert serverRow.end_soc is None
        assert serverRow.runtime_seconds is None

    def test_differentDevicesDoNotCollide(self) -> None:
        """Same source_id from two devices produces two rows."""
        session = _newSession()
        shared = {
            'id': 1,
            'start_timestamp': '2026-04-21T12:00:00Z',
            'start_soc': 100.0,
            'load_class': 'test',
            'data_source': 'real',
        }
        runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b1',
            tables={'battery_health_log': {'rows': [shared]}},
            syncHistoryId=1,
        )
        runSyncUpsert(
            session, deviceId='pi-dev-scratchpad', batchId='b2',
            tables={'battery_health_log': {'rows': [dict(shared)]}},
            syncHistoryId=2,
        )
        assert session.query(BatteryHealthLog).count() == 2
