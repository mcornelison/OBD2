################################################################################
# File Name: test_power_log_sync.py
# Purpose/Description: Server-side sync tests for power_log (US-412 / F-101).
#                      Verifies the PowerLog SQLAlchemy model carries the right
#                      columns, that the Pi-side sync registration names power_log
#                      as a delta table keyed on 'id', and that runSyncUpsert
#                      lands + upserts power-event rows keyed on
#                      (source_device, source_id).
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-412) | Initial -- PowerLog Pi-mirror + sync.  power_log
#               |              | was Pi-only until US-412 mirrored it to the
#               |              | server so power/boot history is queryable
#               |              | server-side alongside the rest of the telemetry.
# ================================================================================
################################################################################

"""Server-side power_log sync tests (US-412 / F-101).

power_log is an append-only event table (one row per power-source / shutdown
stage transition -- NOT per poll), so it delta-syncs on its integer ``id`` PK
exactly like every other capture table (the battery_health_log pattern).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.pi.data.sync_log import DELTA_SYNC_TABLES, PK_COLUMN
from src.server.api.sync import ACCEPTED_TABLES, runSyncUpsert
from src.server.db.models import Base, PowerLog

# ================================================================================
# Model contract
# ================================================================================


class TestPowerLogModelContract:
    """PowerLog mirrors the Pi schema + carries the sync columns."""

    def test_modelHasPiNativeColumns(self) -> None:
        cols = {c.name for c in PowerLog.__table__.columns}
        pi = {
            'timestamp', 'event_type', 'power_source',
            'on_ac_power', 'vcell',
        }
        assert pi.issubset(cols), f"missing Pi-native cols: {pi - cols}"

    def test_modelHasSyncColumns(self) -> None:
        cols = {c.name for c in PowerLog.__table__.columns}
        sync = {'id', 'source_id', 'source_device', 'synced_at',
                'sync_batch_id'}
        assert sync.issubset(cols), f"missing sync cols: {sync - cols}"

    def test_hasUniqueSourceDeviceSourceId(self) -> None:
        constraints = [
            c for c in PowerLog.__table__.constraints
            if 'source_device' in [
                col.name for col in getattr(c, 'columns', [])
            ]
        ]
        assert len(constraints) >= 1, (
            'expected UNIQUE(source_device, source_id) for Pi-sync path'
        )

    def test_eventTypeIsNotNull(self) -> None:
        col = PowerLog.__table__.columns['event_type']
        assert col.nullable is False

    def test_powerSourceIsNotNull(self) -> None:
        col = PowerLog.__table__.columns['power_source']
        assert col.nullable is False

    def test_vcellIsNullable(self) -> None:
        """vcell is NULL on legacy power-source-transition rows (US-252)."""
        col = PowerLog.__table__.columns['vcell']
        assert col.nullable is True


# ================================================================================
# Sync registration
# ================================================================================


class TestSyncRegistration:
    """power_log is wired into both Pi sync_log + server sync (US-412)."""

    def test_powerLogInDeltaSyncTables(self) -> None:
        assert 'power_log' in DELTA_SYNC_TABLES

    def test_powerLogPkIsId(self) -> None:
        assert PK_COLUMN['power_log'] == 'id'

    def test_powerLogInAcceptedTables(self) -> None:
        assert 'power_log' in ACCEPTED_TABLES


# ================================================================================
# Sync upsert behavior
# ================================================================================


def _newSession() -> Session:
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return Session(engine)


class TestRunSyncUpsertPowerLog:
    """Pi delta rows land as upserted server rows keyed on (device, source_id)."""

    def test_pushesNewRow(self) -> None:
        session = _newSession()
        # power_log's PK is already 'id' so the Pi client sends it verbatim;
        # runSyncUpsert maps 'id' -> source_id like every capture table.
        rows = [
            {
                'id': 5,
                'timestamp': '2026-07-01T12:00:00Z',
                'event_type': 'STAGE_SHUTDOWN',
                'power_source': 'BATTERY',
                'on_ac_power': 0,
                'vcell': 3.72,
            },
        ]
        result = runSyncUpsert(
            session,
            deviceId='chi-eclipse-01',
            batchId='batch-1',
            tables={'power_log': {'rows': rows}},
            syncHistoryId=99,
        )

        assert result['power_log'] == {
            'inserted': 1, 'updated': 0, 'errors': 0,
        }

        serverRow = session.query(PowerLog).one()
        assert serverRow.source_id == 5
        assert serverRow.source_device == 'chi-eclipse-01'
        assert serverRow.event_type == 'STAGE_SHUTDOWN'
        assert serverRow.power_source == 'BATTERY'
        assert serverRow.on_ac_power == 0
        assert serverRow.vcell == 3.72
        assert serverRow.sync_batch_id == 99

    def test_pushesRowWithNullVcell(self) -> None:
        """Legacy power-source-transition rows carry no voltage -> vcell NULL."""
        session = _newSession()
        rows = [
            {
                'id': 8,
                'timestamp': '2026-07-01T12:05:00Z',
                'event_type': 'AC_LOST',
                'power_source': 'BATTERY',
                'on_ac_power': 0,
            },
        ]
        runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b1',
            tables={'power_log': {'rows': rows}},
            syncHistoryId=1,
        )
        serverRow = session.query(PowerLog).one()
        assert serverRow.vcell is None

    def test_secondPushIsIdempotent(self) -> None:
        """Same (device, source_id) on re-sync -> UPDATE, not a duplicate row."""
        session = _newSession()
        row = {
            'id': 6,
            'timestamp': '2026-07-01T12:00:00Z',
            'event_type': 'AC_RESTORED',
            'power_source': 'AC',
            'on_ac_power': 1,
            'vcell': 4.05,
        }
        runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b1',
            tables={'power_log': {'rows': [row]}},
            syncHistoryId=1,
        )
        result = runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b2',
            tables={'power_log': {'rows': [dict(row)]}},
            syncHistoryId=2,
        )
        assert result['power_log'] == {
            'inserted': 0, 'updated': 1, 'errors': 0,
        }
        assert session.query(PowerLog).count() == 1

    def test_differentDevicesDoNotCollide(self) -> None:
        """Same source_id from two devices produces two rows."""
        session = _newSession()
        shared = {
            'id': 1,
            'timestamp': '2026-07-01T12:00:00Z',
            'event_type': 'STARTUP',
            'power_source': 'AC',
            'on_ac_power': 1,
        }
        runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b1',
            tables={'power_log': {'rows': [shared]}},
            syncHistoryId=1,
        )
        runSyncUpsert(
            session, deviceId='pi-dev-scratchpad', batchId='b2',
            tables={'power_log': {'rows': [dict(shared)]}},
            syncHistoryId=2,
        )
        assert session.query(PowerLog).count() == 2
