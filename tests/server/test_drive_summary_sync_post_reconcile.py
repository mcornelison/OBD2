################################################################################
# File Name: test_drive_summary_sync_post_reconcile.py
# Purpose/Description: Sprint 19 US-237 -- post-migration sync round-trip tests.
#                      Verifies that a Pi-shape drive_summary payload (drive_id +
#                      ambient/battery/baro fields, mirroring what the Pi
#                      actually sends today) lands HTTP 200 against the
#                      US-237-reconciled schema, AND that the production
#                      failure mode is reproduced when the schema is stale.
#                      The strong-test discriminator is
#                      ``test_staleShapeFailsWithUnknownColumnError`` --
#                      it asserts the exact bug class US-237 fixes (148 silent
#                      sync failures over multi-day window).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex          | Initial -- Sprint 19 US-237 round-trip TDD.
# ================================================================================
################################################################################

"""Sync round-trip tests verifying the US-237 reconciled schema accepts
Pi-shape drive_summary payloads.

Two perspectives:

* **Stale-shape discriminator** -- builds a SQLite drive_summary table
  with ONLY the Sprint 7-8 legacy columns (the exact production state
  on 2026-04-29).  Asserts the sync handler fails with the
  ``Unknown column 'drive_summary.source_id'`` error class.  This is
  the production bug class US-237 closes; if a future change reverses
  the migration the test fails loudly.
* **Post-migration round-trip** -- builds the full ORM-shaped schema
  via ``Base.metadata.create_all()`` (post-US-237 invariant) and
  verifies (a) Pi-shape payload lands HTTP-200, (b) all-NULL rows
  (drives 3/4/5 today) sync successfully, (c) existing analytics
  writer path is preserved (no regression).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.server.api.sync import runSyncUpsert
from src.server.db.models import Base, DriveSummary

# ================================================================================
# Helpers
# ================================================================================


def _newOrmEngine():
    """Engine + ORM-driven (post-migration) schema -- the US-237 invariant."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return engine


def _newStaleEngine():
    """Engine + Sprint-7-8-shape drive_summary (no source_id, source_device).

    Mirrors what the live MariaDB actually had on 2026-04-29 per Ralph's
    V-1 finding.  Other ORM tables still get created so referenced
    helper tables (drive_statistics, sync_history, etc.) exist.

    The legacy table is created via raw DDL because SQLAlchemy ``Table``
    + ``extend_existing=True`` keeps the full ORM column list in metadata
    and would create a fully-migrated physical table -- defeating the
    point of the test.
    """
    engine = create_engine('sqlite:///:memory:')
    # Create everything except drive_summary.
    everythingExceptDriveSummary = [
        t for t in Base.metadata.sorted_tables if t.name != 'drive_summary'
    ]
    Base.metadata.create_all(engine, tables=everythingExceptDriveSummary)
    # Build the Sprint 7-8 legacy shape via raw SQL: id PK + 7 analytics
    # columns, NO source_id / source_device / drive_id / data_source.
    with engine.begin() as conn:
        conn.execute(text(
            'CREATE TABLE drive_summary ('
            ' id INTEGER PRIMARY KEY AUTOINCREMENT,'
            ' device_id VARCHAR(64),'
            ' start_time DATETIME,'
            ' end_time DATETIME,'
            ' duration_seconds INTEGER,'
            ' profile_id VARCHAR(64),'
            ' row_count INTEGER DEFAULT 0,'
            ' created_at DATETIME'
            ')'
        ))
    return engine


# Pi-shape payload mirroring what
# ``src/pi/obdii/drive_summary.py::SummaryRecorder.captureDriveStart``
# emits, before US-236 defer-INSERT lands real metadata values.
def _piShapePayload(driveId: int, *, allNull: bool = False) -> dict:
    if allNull:
        return {
            'id': driveId,
            'drive_start_timestamp': '2026-04-29T13:39:18Z',
            'ambient_temp_at_start_c': None,
            'starting_battery_v': None,
            'barometric_kpa_at_start': None,
            'data_source': 'real',
        }
    return {
        'id': driveId,
        'drive_start_timestamp': '2026-04-29T13:39:18Z',
        'ambient_temp_at_start_c': 15.0,
        'starting_battery_v': 12.6,
        'barometric_kpa_at_start': 101.3,
        'data_source': 'real',
    }


# ================================================================================
# Strong-test discriminator -- production failure mode reproduction
# ================================================================================

class TestStaleShapeReproducesProductionBug:
    """Pre-US-237 schema must fail with the exact 148-failure error class."""

    def test_staleShapeFailsWithUnknownColumnError(self) -> None:
        """A Sprint-7-8-shape drive_summary CANNOT accept Pi-shape sync.

        This locks in the bug class.  If a future refactor ships a
        DriveSummary ORM that doesn't need source_id/source_device
        (or makes them nullable in a way the sync handler tolerates
        even on stale schemas), this assertion will fire.  The error
        message must mention either ``source_id`` or ``source_device``
        because those are the columns the upsert handler queries on
        BEFORE INSERT -- the same query that produced 148 production
        failures on 2026-04-29.
        """
        engine = _newStaleEngine()
        session = Session(engine)
        try:
            with pytest.raises(OperationalError) as exc:
                runSyncUpsert(
                    session,
                    deviceId='chi-eclipse-01',
                    batchId='batch-stale-reproduces-bug',
                    tables={
                        'drive_summary': {
                            'rows': [_piShapePayload(driveId=4)],
                        },
                    },
                    syncHistoryId=1,
                )
            errMsg = str(exc.value)
            assert (
                'source_id' in errMsg or 'source_device' in errMsg
            ), (
                f'expected Unknown-column error on source_id|source_device; '
                f'got: {errMsg!r}'
            )
        finally:
            session.close()


# ================================================================================
# Post-migration round-trip -- US-237 contract
# ================================================================================

class TestPostReconcilePiShapeSync:
    """Pi-shape payload lands HTTP 200 + correct row contents post-migration."""

    def test_drive4WarmIdlePayloadSyncs(self) -> None:
        """The Drive-4 production shape (warm idle, all metadata set) lands."""
        engine = _newOrmEngine()
        session = Session(engine)
        try:
            result = runSyncUpsert(
                session,
                deviceId='chi-eclipse-01',
                batchId='batch-drive4',
                tables={'drive_summary': {'rows': [_piShapePayload(driveId=4)]}},
                syncHistoryId=42,
            )
            session.commit()
            assert result['drive_summary'] == {
                'inserted': 1, 'updated': 0, 'errors': 0,
            }

            row = session.query(DriveSummary).one()
            assert row.source_id == 4
            assert row.source_device == 'chi-eclipse-01'
            assert row.ambient_temp_at_start_c == pytest.approx(15.0)
            assert row.starting_battery_v == pytest.approx(12.6)
            assert row.barometric_kpa_at_start == pytest.approx(101.3)
            assert row.sync_batch_id == 42
        finally:
            session.close()

    def test_drives345AllNullPayloadsSyncSuccessfully(self) -> None:
        """All-NULL Pi-shape rows (the US-228 broken-backfill production state).

        Until US-236 ships defer-INSERT, drives 3/4/5 produced rows with
        NULL ambient/battery/baro.  US-237's job is schema-only: the row
        MUST land regardless of data values.  Data-value population is
        US-236's territory.
        """
        engine = _newOrmEngine()
        session = Session(engine)
        try:
            rows = [_piShapePayload(driveId=did, allNull=True)
                    for did in (3, 4, 5)]
            result = runSyncUpsert(
                session,
                deviceId='chi-eclipse-01',
                batchId='batch-345-all-null',
                tables={'drive_summary': {'rows': rows}},
                syncHistoryId=99,
            )
            session.commit()
            assert result['drive_summary'] == {
                'inserted': 3, 'updated': 0, 'errors': 0,
            }

            landedIds = {r.source_id for r in session.query(DriveSummary).all()}
            assert landedIds == {3, 4, 5}
            allNullsPreserved = session.query(DriveSummary).filter(
                DriveSummary.ambient_temp_at_start_c.is_(None),
                DriveSummary.starting_battery_v.is_(None),
                DriveSummary.barometric_kpa_at_start.is_(None),
            ).count()
            assert allNullsPreserved == 3, (
                'all three rows should have NULL data values (US-228 production state)'
            )
        finally:
            session.close()

    def test_secondPushOfSameDriveIdUpdatesNotInserts(self) -> None:
        """UNIQUE(source_device, source_id) drives upsert semantics."""
        engine = _newOrmEngine()
        session = Session(engine)
        try:
            first = _piShapePayload(driveId=7)
            runSyncUpsert(
                session, deviceId='chi-eclipse-01', batchId='b1',
                tables={'drive_summary': {'rows': [first]}}, syncHistoryId=1,
            )
            session.commit()

            updated = dict(first)
            updated['starting_battery_v'] = 13.2
            result = runSyncUpsert(
                session, deviceId='chi-eclipse-01', batchId='b2',
                tables={'drive_summary': {'rows': [updated]}}, syncHistoryId=2,
            )
            session.commit()
            assert result['drive_summary'] == {
                'inserted': 0, 'updated': 1, 'errors': 0,
            }

            rows = session.query(DriveSummary).all()
            assert len(rows) == 1
            assert rows[0].starting_battery_v == pytest.approx(13.2)
        finally:
            session.close()


class TestPostReconcileAnalyticsPreservation:
    """Analytics-writer path on the same table stays untouched (no regression)."""

    def test_analyticsRowDifferentDeviceIdCoexistsWithPiSyncRow(self) -> None:
        """A pre-existing analytics-writer row + Pi-sync row -- both survive."""
        engine = _newOrmEngine()
        session = Session(engine)
        try:
            # Simulate the analytics writer (per US-214 Option 1: NULL
            # source_device + populated device_id + start_time + row_count).
            analyticsRow = DriveSummary(
                device_id='chi-eclipse-01',
                start_time=None,  # would be a datetime in prod; nullable column
                end_time=None,
                duration_seconds=600,
                profile_id='default',
                row_count=4487,
                is_real=True,
                data_source='real',
            )
            session.add(analyticsRow)
            session.commit()

            # Pi-sync writer lands a separate row keyed on source_device+source_id.
            runSyncUpsert(
                session, deviceId='chi-eclipse-01', batchId='b1',
                tables={'drive_summary': {'rows': [_piShapePayload(driveId=99)]}},
                syncHistoryId=1,
            )
            session.commit()

            allRows = session.query(DriveSummary).all()
            # Analytics row + Pi-sync row -- two distinct rows.
            assert len(allRows) == 2
            piSync = next(r for r in allRows if r.source_id == 99)
            analytics = next(r for r in allRows if r.source_id is None)
            assert piSync.source_device == 'chi-eclipse-01'
            assert analytics.row_count == 4487
            assert analytics.is_real is True
        finally:
            session.close()


class TestPostReconcileColumnContract:
    """The reconciled schema declares every column the migration adds."""

    def test_allMigrationColumnsExistInOrm(self) -> None:
        from src.server.migrations.versions import (
            v0004_us237_drive_summary_reconcile as m0004,
        )

        ormCols = {c.name for c in DriveSummary.__table__.columns}
        for colName, _ddl in m0004.DRIVE_SUMMARY_NEW_COLUMNS:
            assert colName in ormCols, (
                f'ORM missing migration column {colName!r}; sync would fail '
                'against post-migrated DB if production matched'
            )

    def test_freshOrmDbAcceptsSourceIdQueryDirectly(self) -> None:
        """Confirms the bug fixed by US-237.

        On a fresh ORM-created schema (post-US-237 invariant), the query
        the sync handler runs (SELECT source_id FROM drive_summary ...)
        succeeds.  On the stale shape it would fail with Unknown column.
        Side-by-side with the stale-shape test above, this proves the
        migration closes the bug class.
        """
        engine = _newOrmEngine()
        session = Session(engine)
        try:
            sql = text(
                "SELECT source_id FROM drive_summary "
                "WHERE source_device='chi-eclipse-01' AND source_id=42"
            )
            # Should execute without error and return zero rows.
            result = session.execute(sql).fetchall()
            assert result == []
        finally:
            session.close()
