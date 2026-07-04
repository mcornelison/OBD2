################################################################################
# File Name: test_pi_state_sync.py
# Purpose/Description: Server-side sync tests for pi_state (US-453 / D-7 / F-082).
#                      Verifies the PiState SQLAlchemy model carries the right
#                      columns, that the Pi-side sync registration names pi_state
#                      as a delta table keyed on 'id' AND opts it into the
#                      modified_at update-propagation cursor (it is a mutable
#                      singleton), that v0019 is wired into the migration
#                      registry, and that runSyncUpsert lands + upserts the
#                      operational-state row keyed on (source_device, source_id)
#                      -- including propagating a no_new_drives flip.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-453) | Initial -- PiState Pi-mirror + sync.  pi_state
#               |              | was Pi-only until US-453 mirrored it as raw
#               |              | forensic state (D-7 / F-082); the server does
#               |              | not recompute it.
# ================================================================================
################################################################################

"""Server-side pi_state sync tests (US-453 / D-7 / F-082).

pi_state is the Pi operational-state singleton (id pinned to 1; carries the
US-225 no_new_drives gate flag).  It is irreproducible Pi-only forensic state,
so it syncs Pi->server as raw.  Its PK is integer ``id``, so it rides the delta
path exactly like every other capture table -- but unlike the append-only
tables it is a MUTABLE singleton, so it also opts into the modified_at
update-propagation cursor (SYNC_UPDATE_TABLES_PK) so a no_new_drives flip
re-syncs and the server mirror stays current (proved here via the
runSyncUpsert UPDATE path).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.pi.data.sync_log import (
    DELTA_SYNC_TABLES,
    PK_COLUMN,
    SYNC_UPDATE_TABLES_PK,
)
from src.server.api.sync import ACCEPTED_TABLES, runSyncUpsert
from src.server.db.models import Base, PiState
from src.server.migrations import ALL_MIGRATIONS

# ================================================================================
# Model contract
# ================================================================================


class TestPiStateModelContract:
    """PiState mirrors the Pi schema + carries the sync columns."""

    def test_modelHasPiNativeColumn(self) -> None:
        cols = {c.name for c in PiState.__table__.columns}
        assert 'no_new_drives' in cols

    def test_modelHasSyncColumns(self) -> None:
        cols = {c.name for c in PiState.__table__.columns}
        sync = {'id', 'source_id', 'source_device', 'synced_at',
                'sync_batch_id'}
        assert sync.issubset(cols), f"missing sync cols: {sync - cols}"

    def test_hasUniqueSourceDeviceSourceId(self) -> None:
        constraints = [
            c for c in PiState.__table__.constraints
            if 'source_device' in [
                col.name for col in getattr(c, 'columns', [])
            ]
        ]
        assert len(constraints) >= 1, (
            'expected UNIQUE(source_device, source_id) for Pi-sync path'
        )

    def test_noNewDrivesIsNotNull(self) -> None:
        col = PiState.__table__.columns['no_new_drives']
        assert col.nullable is False


# ================================================================================
# Sync registration (Pi + server)
# ================================================================================


class TestSyncRegistration:
    """pi_state is wired into both Pi sync_log + server sync (US-453)."""

    def test_piStateInDeltaSyncTables(self) -> None:
        assert 'pi_state' in DELTA_SYNC_TABLES

    def test_piStatePkIsId(self) -> None:
        assert PK_COLUMN['pi_state'] == 'id'

    def test_piStateOptsIntoModifiedAtCursor(self) -> None:
        """Mutable singleton -> must re-sync on UPDATE, not just first INSERT."""
        assert SYNC_UPDATE_TABLES_PK.get('pi_state') == 'id'

    def test_piStateInAcceptedTables(self) -> None:
        assert 'pi_state' in ACCEPTED_TABLES


class TestMigrationWiring:
    """v0019 creates the server pi_state table + is in the registry."""

    def test_v0019Registered(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert '0019' in versions

    def test_v0019IsLastInAscendingOrder(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert versions[-1] == '0019'


# ================================================================================
# Sync upsert behavior
# ================================================================================


def _newSession() -> Session:
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return Session(engine)


class TestRunSyncUpsertPiState:
    """Pi delta rows land as upserted server rows keyed on (device, source_id)."""

    def test_pushesNewRow(self) -> None:
        session = _newSession()
        # pi_state's PK is already 'id' so the Pi client sends it verbatim
        # (always 1 -- singleton); runSyncUpsert maps 'id' -> source_id.
        rows = [{'id': 1, 'no_new_drives': 1}]
        result = runSyncUpsert(
            session,
            deviceId='chi-eclipse-01',
            batchId='batch-1',
            tables={'pi_state': {'rows': rows}},
            syncHistoryId=99,
        )

        assert result['pi_state'] == {'inserted': 1, 'updated': 0, 'errors': 0}

        serverRow = session.query(PiState).one()
        assert serverRow.source_id == 1
        assert serverRow.source_device == 'chi-eclipse-01'
        assert serverRow.no_new_drives == 1
        assert serverRow.sync_batch_id == 99

    def test_secondPushIsIdempotent(self) -> None:
        """Same (device, source_id) on re-sync -> UPDATE, not a duplicate row."""
        session = _newSession()
        row = {'id': 1, 'no_new_drives': 0}
        runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b1',
            tables={'pi_state': {'rows': [row]}},
            syncHistoryId=1,
        )
        result = runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b2',
            tables={'pi_state': {'rows': [dict(row)]}},
            syncHistoryId=2,
        )
        assert result['pi_state'] == {'inserted': 0, 'updated': 1, 'errors': 0}
        assert session.query(PiState).count() == 1

    def test_flagFlipPropagatesToServerMirror(self) -> None:
        """A no_new_drives flip re-syncs and updates the SAME server row.

        This is the mutable-singleton guarantee: after the WARNING-stage flip
        (0 -> 1) the Pi re-sends id=1 (via the modified_at cursor on the Pi),
        and the server upsert on (source_device, source_id=1) must UPDATE the
        existing row -- so the server mirror matches the Pi, not a stale value.
        """
        session = _newSession()
        runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b1',
            tables={'pi_state': {'rows': [{'id': 1, 'no_new_drives': 0}]}},
            syncHistoryId=1,
        )
        # WARNING stage flips the gate on the Pi; the flipped row re-syncs.
        runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b2',
            tables={'pi_state': {'rows': [{'id': 1, 'no_new_drives': 1}]}},
            syncHistoryId=2,
        )
        serverRow = session.query(PiState).one()
        assert serverRow.no_new_drives == 1
        assert session.query(PiState).count() == 1

    def test_differentDevicesDoNotCollide(self) -> None:
        """Same source_id (1) from two devices produces two rows."""
        session = _newSession()
        shared = {'id': 1, 'no_new_drives': 0}
        runSyncUpsert(
            session, deviceId='chi-eclipse-01', batchId='b1',
            tables={'pi_state': {'rows': [dict(shared)]}},
            syncHistoryId=1,
        )
        runSyncUpsert(
            session, deviceId='pi-dev-scratchpad', batchId='b2',
            tables={'pi_state': {'rows': [dict(shared)]}},
            syncHistoryId=2,
        )
        assert session.query(PiState).count() == 2
