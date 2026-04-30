################################################################################
# File Name: test_dtc_log_sync_post_create.py
# Purpose/Description: Sprint 19 US-238 -- post-migration sync round-trip tests.
#                      Verifies the V-2 production failure mode (dtc_log table
#                      missing) is reproduced when the schema is stale, and
#                      that a Pi-shape DTC payload lands HTTP-200 against the
#                      v0005-created schema.  Strong-test discriminator
#                      ``test_missingTableFailsWithNoSuchTableError`` reproduces
#                      the exact bug class US-238 closes (next-DTC-drive silent
#                      data loss).  The pre-existing ``tests/server/test_dtc_sync.py``
#                      already covers ORM contract + happy-path round-trip on
#                      the always-create_all() path; this file adds the missing-
#                      table reproduction that the runtime-validation rule
#                      requires.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex          | Initial -- Sprint 19 US-238 round-trip TDD.
# ================================================================================
################################################################################

"""Sync round-trip tests verifying v0005 closes the V-2 missing-table bug.

Two perspectives:

* **Stale-shape discriminator** -- builds a SQLite engine and explicitly
  drops the ``dtc_log`` table to mirror the live MariaDB state captured
  in Drive 4 health check on 2026-04-29 (``Table 'obd2db.dtc_log' doesn't
  exist`` raw error from MariaDB).  Asserts the sync handler raises an
  ``OperationalError`` referencing ``dtc_log``.  This is the production
  bug class US-238 closes; if a future change drops the v0005 migration
  or removes the ORM table from ``Base.metadata``, this test fires.

* **Post-migration round-trip** -- builds the full ORM-shaped schema via
  ``Base.metadata.create_all()`` (post-US-238 invariant) and verifies a
  Pi-shape DTC payload (P0420 catalyst efficiency, the representative
  DSM DTC per groundingRef) lands HTTP-200.

Note: the always-create_all() happy-path round-trip is already covered
in ``tests/server/test_dtc_sync.py`` (US-204).  This file adds the
missing-table strong-test discriminator + payload variants that mirror
the V-2 evidence shape.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.server.api.sync import runSyncUpsert
from src.server.db.models import Base, DtcLog

# ================================================================================
# Helpers
# ================================================================================


def _newOrmEngine():
    """Engine + ORM-driven (post-migration) schema -- the US-238 invariant."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return engine


def _newMissingDtcLogEngine():
    """Engine where every ORM table EXCEPT dtc_log exists.

    Mirrors the live MariaDB state on 2026-04-29 per Ralph's V-2 finding:
    SHOW TABLES returns 16 tables (drive_summary, realtime_data,
    connection_log, etc.) but no dtc_log.  The next DTC drive would write
    to Pi only -- this is the silent-data-loss bug class US-238 closes.
    """
    engine = create_engine('sqlite:///:memory:')
    everythingExceptDtcLog = [
        t for t in Base.metadata.sorted_tables if t.name != 'dtc_log'
    ]
    Base.metadata.create_all(engine, tables=everythingExceptDtcLog)
    # Belt-and-suspenders: verify dtc_log really is absent.
    with engine.connect() as conn:
        present = conn.execute(text(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='dtc_log'"
        )).fetchone()
        assert present is None, (
            'test setup error: dtc_log should be missing'
        )
    return engine


def _piShapeDtcPayload(
    *,
    sourceId: int,
    code: str,
    status: str = 'stored',
    driveId: int | None = 7,
) -> dict:
    """Pi-shape DTC payload mirroring DtcLogger output (US-204)."""
    return {
        'id': sourceId,
        'dtc_code': code,
        'description': 'Catalyst System Efficiency Below Threshold (Bank 1)',
        'status': status,
        'first_seen_timestamp': '2026-04-29T13:39:18Z',
        'last_seen_timestamp': '2026-04-29T13:39:18Z',
        'drive_id': driveId,
        'data_source': 'real',
    }


# ================================================================================
# Strong-test discriminator -- V-2 production failure mode reproduction
# ================================================================================

class TestMissingTableReproducesProductionBug:
    """Pre-US-238 schema (no dtc_log table) must fail with ``no such table``.

    Locks the bug class.  If a future refactor drops the v0005 migration
    or yanks the ORM table from Base.metadata, this test fires.  The
    error message must mention ``dtc_log`` because that's the table the
    upsert handler queries -- the same query that would produce silent
    data loss on the next DTC drive.
    """

    def test_missingTableFailsWithNoSuchTableError(self) -> None:
        engine = _newMissingDtcLogEngine()
        session = Session(engine)
        try:
            with pytest.raises(OperationalError) as exc:
                runSyncUpsert(
                    session,
                    deviceId='chi-eclipse-01',
                    batchId='batch-missing-reproduces-v2',
                    tables={
                        'dtc_log': {
                            'rows': [_piShapeDtcPayload(
                                sourceId=1, code='P0420',
                            )],
                        },
                    },
                    syncHistoryId=1,
                )
            errMsg = str(exc.value)
            # SQLite phrasing is "no such table: dtc_log"; MariaDB phrasing
            # would be "Table 'obd2db.dtc_log' doesn't exist" (V-2 evidence
            # at offices/pm/inbox/2026-04-29-from-ralph-post-deploy-...md
            # line 437-438).  Either way the table name surfaces.
            assert 'dtc_log' in errMsg, (
                f'expected error referencing dtc_log; got: {errMsg!r}'
            )
        finally:
            session.close()


# ================================================================================
# Post-migration round-trip -- US-238 contract
# ================================================================================

class TestPostCreatePiShapeSync:
    """Pi-shape DTC payload lands HTTP 200 + correct row contents post-migration."""

    def test_p0420PayloadSyncs(self) -> None:
        """Representative DSM DTC (P0420 catalyst efficiency) lands."""
        engine = _newOrmEngine()
        session = Session(engine)
        try:
            result = runSyncUpsert(
                session,
                deviceId='chi-eclipse-01',
                batchId='batch-p0420',
                tables={
                    'dtc_log': {
                        'rows': [_piShapeDtcPayload(sourceId=1, code='P0420')],
                    },
                },
                syncHistoryId=42,
            )
            session.commit()
            assert result['dtc_log'] == {
                'inserted': 1, 'updated': 0, 'errors': 0,
            }

            row = session.query(DtcLog).one()
            assert row.source_id == 1
            assert row.source_device == 'chi-eclipse-01'
            assert row.dtc_code == 'P0420'
            assert row.status == 'stored'
            assert row.drive_id == 7
            assert row.data_source == 'real'
            assert row.sync_batch_id == 42
        finally:
            session.close()

    def test_storedAndPendingDtcsCoexist(self) -> None:
        """Mode 03 (stored) + Mode 07 (pending) DTCs from the same drive
        land as separate rows -- ``status`` differentiates them.
        """
        engine = _newOrmEngine()
        session = Session(engine)
        try:
            rows = [
                _piShapeDtcPayload(sourceId=1, code='P0420', status='stored'),
                _piShapeDtcPayload(sourceId=2, code='P0171', status='pending'),
            ]
            result = runSyncUpsert(
                session,
                deviceId='chi-eclipse-01',
                batchId='batch-mixed-status',
                tables={'dtc_log': {'rows': rows}},
                syncHistoryId=43,
            )
            session.commit()
            assert result['dtc_log'] == {
                'inserted': 2, 'updated': 0, 'errors': 0,
            }
            statuses = {r.status for r in session.query(DtcLog).all()}
            assert statuses == {'stored', 'pending'}
        finally:
            session.close()

    def test_unknownDtcWithEmptyDescriptionStillLands(self) -> None:
        """Mitsubishi P1XXX codes return empty description from python-obd
        DTC_MAP (US-204 invariant -- never fabricate).  Empty string MUST
        sync without error.
        """
        engine = _newOrmEngine()
        session = Session(engine)
        try:
            payload = _piShapeDtcPayload(sourceId=1, code='P1500')
            payload['description'] = ''  # python-obd returns empty for unknown
            result = runSyncUpsert(
                session,
                deviceId='chi-eclipse-01',
                batchId='batch-p1500',
                tables={'dtc_log': {'rows': [payload]}},
                syncHistoryId=44,
            )
            session.commit()
            assert result['dtc_log']['inserted'] == 1
            row = session.query(DtcLog).one()
            assert row.dtc_code == 'P1500'
            assert row.description == ''
        finally:
            session.close()

    def test_secondPushOfSameDtcIdUpdatesNotInserts(self) -> None:
        """UNIQUE(source_device, source_id) drives upsert semantics.

        DtcLogger reissues the same row with a bumped ``last_seen_timestamp``
        when a code reappears in the same drive.
        """
        engine = _newOrmEngine()
        session = Session(engine)
        try:
            first = _piShapeDtcPayload(sourceId=1, code='P0420')
            runSyncUpsert(
                session, deviceId='chi-eclipse-01', batchId='b1',
                tables={'dtc_log': {'rows': [first]}}, syncHistoryId=1,
            )
            session.commit()

            bumped = dict(first)
            bumped['last_seen_timestamp'] = '2026-04-29T13:45:00Z'
            result = runSyncUpsert(
                session, deviceId='chi-eclipse-01', batchId='b2',
                tables={'dtc_log': {'rows': [bumped]}}, syncHistoryId=2,
            )
            session.commit()

            assert result['dtc_log'] == {
                'inserted': 0, 'updated': 1, 'errors': 0,
            }
            assert session.query(DtcLog).count() == 1
        finally:
            session.close()

    def test_separateDevicesGetSeparateRows(self) -> None:
        """Same source_id, different device -> two distinct server rows.

        Future-proofs against multi-Pi setups (test rigs sharing a server).
        """
        engine = _newOrmEngine()
        session = Session(engine)
        try:
            payload = _piShapeDtcPayload(sourceId=1, code='P0420')
            runSyncUpsert(
                session, deviceId='chi-eclipse-01', batchId='a',
                tables={'dtc_log': {'rows': [payload]}}, syncHistoryId=1,
            )
            runSyncUpsert(
                session, deviceId='chi-eclipse-02', batchId='b',
                tables={'dtc_log': {'rows': [payload]}}, syncHistoryId=2,
            )
            session.commit()
            rows = session.query(DtcLog).order_by(DtcLog.source_device).all()
            assert len(rows) == 2
            assert {r.source_device for r in rows} == {
                'chi-eclipse-01', 'chi-eclipse-02',
            }
        finally:
            session.close()

    def test_nullDriveIdAccepted(self) -> None:
        """Pi-side schema allows NULL drive_id for Mode 03 probes that
        precede _startDrive (rare edge case per dtc_log_schema docstring).
        Server must accept the same.
        """
        engine = _newOrmEngine()
        session = Session(engine)
        try:
            payload = _piShapeDtcPayload(sourceId=1, code='P0420', driveId=None)
            result = runSyncUpsert(
                session, deviceId='chi-eclipse-01', batchId='b-null-drive',
                tables={'dtc_log': {'rows': [payload]}}, syncHistoryId=1,
            )
            session.commit()
            assert result['dtc_log']['inserted'] == 1
            row = session.query(DtcLog).one()
            assert row.drive_id is None
        finally:
            session.close()


# ================================================================================
# ORM <-> migration column parity
# ================================================================================

class TestOrmMigrationParity:
    """Schema declared by SQLAlchemy DtcLog must match what v0005 creates.

    If the ORM ever adds a column that the migration doesn't, fresh DBs
    (where create_all() runs) and migrated DBs (where v0005 ran) will
    diverge -- the exact migration drift class US-213 was designed to
    prevent.  This is the same parity guard US-237 used.
    """

    def test_everyOrmColumnIsInMigrationDdl(self) -> None:
        from src.server.migrations.versions import (
            v0005_us238_create_dtc_log as m0005,
        )
        ddl = m0005.CREATE_DTC_LOG_DDL
        for col in DtcLog.__table__.columns:
            assert col.name in ddl, (
                f'ORM column {col.name!r} not declared in v0005 DDL'
            )
