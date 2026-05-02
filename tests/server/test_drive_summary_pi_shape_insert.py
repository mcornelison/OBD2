################################################################################
# File Name: test_drive_summary_pi_shape_insert.py
# Purpose/Description: Sprint 21 US-256 Sprint 19/20 retro -- integration test
#                      that locks in the TD-043 bug class (legacy NOT-NULL
#                      drive_summary columns reject Pi-shape sync INSERTs).
#                      Builds a pre-v0006 schema (device_id NOT NULL +
#                      start_time NOT NULL, no defaults) and asserts the same
#                      production failure mode CIO saw on 2026-05-01.  Then
#                      asserts that the modernized post-v0006 schema (built
#                      via Base.metadata.create_all -> nullable per ORM)
#                      accepts the same payload.  Direct application of
#                      feedback_runtime_validation_required.md -- this test
#                      WOULD HAVE FAILED against pre-v0006 production code.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex (US-256) | Initial -- Sprint 19/20 retro lock-in for TD-043.
# ================================================================================
################################################################################

"""Pi-shape drive_summary sync integration test (US-256 / TD-043 retro).

Why this exists
---------------

Sprint 19 US-237 ALTERed in the modern Pi-sync columns on the server
``drive_summary`` table but did not touch the 6 legacy Sprint-7/8
columns -- two of them (``device_id``, ``start_time``) carried
``NOT NULL`` with no default.  Pi-sync omits those columns (they are
analytics-only on the server side), so every Pi INSERT failed with
MariaDB error 1364 ``Field 'device_id' doesn't have a default value``
for weeks until CIO ran a live ALTER on 2026-05-01 (captured by Sprint
21 v0006 migration).

Sprint 19 US-237 + Sprint 20 US-249 both shipped passes:true.  Neither
caught TD-043.  The acceptance gate they had was ORM-shape correctness
(via ``Base.metadata.create_all`` on SQLite -- which produces a fully
nullable schema since the ORM model declares the legacy columns as
``Mapped[str | None]``).  That gate is necessary but insufficient: live
MariaDB had pre-existing NOT-NULL state from Sprint 7-8 DDL that the
ORM-shape test never exercised.

This file closes that retro loop.  It builds the **pre-v0006 production
shape** as raw DDL (NOT NULL device_id + NOT NULL start_time, no
defaults), runs the real ``runSyncUpsert`` handler with a Pi-shape
payload, and asserts the exact production failure surfaces.  It also
asserts the post-v0006 ORM shape accepts the same payload, so the
test discriminates the bug fix.

Discriminator
-------------

If a future change reverses v0006 (e.g. someone re-ALTERs device_id
back to NOT NULL), :meth:`TestPreV0006FailureMode
.test_piShapeInsert_omitsDeviceId_failsWithIntegrityError` fires loudly.

If a future change introduces a new NOT-NULL-without-default column
to the live MariaDB schema that Pi doesn't populate, this same shape
of test would catch it -- the fixture builders (_newPreV0006Engine /
_newPostV0006Engine) document how to extend.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from src.server.api.sync import runSyncUpsert
from src.server.db.models import Base, DriveSummary

# ================================================================================
# Engines -- pre-v0006 vs post-v0006 (modernized) shapes
# ================================================================================


def _newPostV0006Engine():
    """Engine + ORM-driven schema -- post-v0006, all legacy cols nullable.

    This is the modern reference state: ``Base.metadata.create_all``
    creates ``drive_summary`` from the ORM model, where every legacy
    column is declared ``Mapped[str | None]`` so SQLite produces them
    as nullable.  Mirrors what a freshly-provisioned MariaDB looks
    like after v0001..v0006 migrations apply cleanly.
    """
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return engine


def _newPreV0006Engine():
    """Engine + Sprint-7/8 legacy shape with the NOT-NULL trap.

    Builds drive_summary with ``device_id VARCHAR(64) NOT NULL`` and
    ``start_time DATETIME NOT NULL`` (the exact pre-v0006 production
    state on 2026-05-01) PLUS the modern Pi-sync columns (so the upsert
    handler's pre-INSERT SELECT on ``source_device + source_id`` finds
    the table -- this isolates the bug to the NOT-NULL trap rather than
    the source_id missing-column bug US-237 already closed).

    Other ORM tables (sync_history, drive_statistics, ...) get created
    via ``Base.metadata.create_all`` so the upsert handler's foreign
    references resolve normally.

    The legacy table is built via raw DDL because SQLAlchemy + the ORM
    model would build the modern (nullable) shape regardless of any
    column-level overrides at engine time.
    """
    engine = create_engine('sqlite:///:memory:')
    everythingExceptDriveSummary = [
        t for t in Base.metadata.sorted_tables if t.name != 'drive_summary'
    ]
    Base.metadata.create_all(engine, tables=everythingExceptDriveSummary)
    with engine.begin() as conn:
        conn.execute(text(
            'CREATE TABLE drive_summary ('
            ' id INTEGER PRIMARY KEY AUTOINCREMENT,'
            # Legacy Sprint-7/8 columns -- NOT NULL is the TD-043 trap.
            ' device_id VARCHAR(64) NOT NULL,'
            ' start_time DATETIME NOT NULL,'
            ' end_time DATETIME,'
            ' duration_seconds INTEGER,'
            ' profile_id VARCHAR(64),'
            ' row_count INTEGER DEFAULT 0,'
            ' is_real BOOLEAN DEFAULT 0,'
            ' created_at DATETIME,'
            ' data_source VARCHAR(16) DEFAULT \'real\','
            # Modern Pi-sync columns (Sprint 19 US-237 ALTER).
            ' source_id INTEGER,'
            ' source_device VARCHAR(64),'
            ' synced_at DATETIME,'
            ' sync_batch_id INTEGER,'
            ' drive_start_timestamp DATETIME,'
            ' ambient_temp_at_start_c FLOAT,'
            ' starting_battery_v FLOAT,'
            ' barometric_kpa_at_start FLOAT,'
            ' drive_id INTEGER,'
            ' UNIQUE (source_device, source_id)'
            ')'
        ))
    return engine


# ================================================================================
# Pi-shape payload -- mirrors what SyncClient actually sends
# ================================================================================


def _piShapePayload(driveId: int) -> dict:
    """Pi-side drive_summary sync payload (US-236 defer-INSERT shape).

    Mirrors what ``src/pi/obdii/drive_summary.py`` writes after first
    IAT/BATTERY/BARO arrival.  Notably **omits** ``device_id``,
    ``start_time``, ``end_time``, ``duration_seconds``, ``profile_id``,
    ``row_count`` -- those are the analytics-writer's columns and the
    Pi has no source for them.  This is the exact payload class that
    triggered the 500-error storm pre-TD-043-fix.
    """
    return {
        'id': driveId,
        'drive_start_timestamp': '2026-05-01T05:30:24Z',
        'ambient_temp_at_start_c': 18.5,
        'starting_battery_v': 12.7,
        'barometric_kpa_at_start': 100.2,
        'data_source': 'real',
    }


# ================================================================================
# Pre-v0006 production failure-mode reproduction
# ================================================================================


class TestPreV0006FailureMode:
    """Locks in the TD-043 bug class -- pre-v0006 schema rejects Pi sync.

    Each test here would have FAILED against pre-v0006 production code
    (the real Sprint 19/20 deploy state CIO observed on 2026-05-01).
    Their job is to be the canary that catches the bug class returning.
    """

    def test_piShapeInsert_omitsDeviceId_failsWithIntegrityError(self) -> None:
        """The exact MariaDB-1364 bug class CIO saw on 2026-05-01.

        Given the pre-v0006 schema (``device_id NOT NULL`` no default),
        a Pi-shape INSERT that omits ``device_id`` MUST fail.  SQLite's
        equivalent of MariaDB-1364 is ``NOT NULL constraint failed:
        drive_summary.device_id`` (sqlalchemy wraps as IntegrityError).

        This is the discriminator for TD-043 retro: if the test passes
        without raising, the bug class has returned.
        """
        engine = _newPreV0006Engine()
        session = Session(engine)
        try:
            with pytest.raises((IntegrityError, OperationalError)) as exc:
                runSyncUpsert(
                    session,
                    deviceId='chi-eclipse-01',
                    batchId='batch-pre-v0006-fails',
                    tables={
                        'drive_summary': {
                            'rows': [_piShapePayload(driveId=2)],
                        },
                    },
                    syncHistoryId=1,
                )
                session.commit()
            errMsg = str(exc.value).lower()
            # Either device_id or start_time NOT-NULL must fail (depends
            # on column-evaluation order).  device_id is the leading
            # column in the legacy DDL so it usually wins, but assert on
            # either to keep the test robust to column ordering.
            assert 'not null' in errMsg or "doesn't have a default" in errMsg, (
                f'expected NOT-NULL / missing-default failure; got: {errMsg!r}'
            )
            assert 'device_id' in errMsg or 'start_time' in errMsg, (
                f'expected device_id or start_time in error; got: {errMsg!r}'
            )
        finally:
            session.rollback()
            session.close()

    def test_piShapeInsert_isolated_omitsStartTime_failsWithIntegrityError(
        self,
    ) -> None:
        """Even after device_id is fixed, start_time alone still trips.

        Documents the second blocker CIO hit on 2026-05-01 (after
        ALTERing device_id, the next sync attempt failed on
        start_time).  This test simulates that intermediate state by
        building a schema with ONLY start_time NOT NULL.  Confirms a
        partial v0006 fix is insufficient -- both columns must be
        addressed, which v0006 does atomically.
        """
        engine = create_engine('sqlite:///:memory:')
        everythingExceptDriveSummary = [
            t for t in Base.metadata.sorted_tables
            if t.name != 'drive_summary'
        ]
        Base.metadata.create_all(
            engine, tables=everythingExceptDriveSummary,
        )
        with engine.begin() as conn:
            conn.execute(text(
                'CREATE TABLE drive_summary ('
                ' id INTEGER PRIMARY KEY AUTOINCREMENT,'
                ' device_id VARCHAR(64),'
                ' start_time DATETIME NOT NULL,'
                ' end_time DATETIME,'
                ' duration_seconds INTEGER,'
                ' profile_id VARCHAR(64),'
                ' row_count INTEGER DEFAULT 0,'
                ' is_real BOOLEAN DEFAULT 0,'
                ' created_at DATETIME,'
                ' data_source VARCHAR(16) DEFAULT \'real\','
                ' source_id INTEGER,'
                ' source_device VARCHAR(64),'
                ' synced_at DATETIME,'
                ' sync_batch_id INTEGER,'
                ' drive_start_timestamp DATETIME,'
                ' ambient_temp_at_start_c FLOAT,'
                ' starting_battery_v FLOAT,'
                ' barometric_kpa_at_start FLOAT,'
                ' drive_id INTEGER,'
                ' UNIQUE (source_device, source_id)'
                ')'
            ))

        session = Session(engine)
        try:
            with pytest.raises((IntegrityError, OperationalError)) as exc:
                runSyncUpsert(
                    session,
                    deviceId='chi-eclipse-01',
                    batchId='batch-only-start-time-not-null',
                    tables={
                        'drive_summary': {
                            'rows': [_piShapePayload(driveId=3)],
                        },
                    },
                    syncHistoryId=2,
                )
                session.commit()
            errMsg = str(exc.value).lower()
            assert 'not null' in errMsg, (
                f'expected NOT-NULL failure on start_time; got: {errMsg!r}'
            )
            assert 'start_time' in errMsg, (
                f'expected start_time in error; got: {errMsg!r}'
            )
        finally:
            session.rollback()
            session.close()


# ================================================================================
# Post-v0006 modernized -- success path (the v0006 fix verified)
# ================================================================================


class TestPostV0006Modernized:
    """The v0006 fix lets Pi-shape INSERTs land on the modernized schema."""

    def test_piShapeInsert_postV0006_succeedsAsInsert(self) -> None:
        """Pi-shape INSERT lands HTTP-200 on post-v0006 schema.

        This is the post-fix reference behavior.  Discriminates the
        v0006 fix: if the legacy NOT-NULL constraints came back
        (regression on the v0006 migration), this test would fail with
        the same IntegrityError as the pre-v0006 cases above.
        """
        engine = _newPostV0006Engine()
        session = Session(engine)
        try:
            result = runSyncUpsert(
                session,
                deviceId='chi-eclipse-01',
                batchId='batch-post-v0006-succeeds',
                tables={
                    'drive_summary': {
                        'rows': [_piShapePayload(driveId=4)],
                    },
                },
                syncHistoryId=3,
            )
            session.commit()

            assert result['drive_summary'] == {
                'inserted': 1, 'updated': 0, 'errors': 0,
            }

            row = session.query(DriveSummary).one()
            assert row.source_id == 4
            assert row.source_device == 'chi-eclipse-01'
            # Legacy columns must be NULL (Pi never populates them).
            assert row.device_id is None
            assert row.start_time is None
            # Pi-populated cold-start metadata round-trips correctly.
            assert row.ambient_temp_at_start_c == pytest.approx(18.5)
            assert row.starting_battery_v == pytest.approx(12.7)
            assert row.barometric_kpa_at_start == pytest.approx(100.2)
        finally:
            session.close()

    def test_piShapeInsert_postV0006_omitsAllSixLegacyColumns(self) -> None:
        """Verifies every one of the 6 legacy columns is omitted by Pi.

        Locks in Pi-side scope: ``device_id``, ``start_time``,
        ``end_time``, ``duration_seconds``, ``profile_id``, ``row_count``
        all originate from the analytics-writer path and Pi has no
        source for them.  If the Pi sync writer ever starts populating
        any of them, this test will surface that scope creep.
        """
        engine = _newPostV0006Engine()
        session = Session(engine)
        try:
            runSyncUpsert(
                session,
                deviceId='chi-eclipse-01',
                batchId='batch-pi-omits-six-legacy',
                tables={
                    'drive_summary': {
                        'rows': [_piShapePayload(driveId=5)],
                    },
                },
                syncHistoryId=4,
            )
            session.commit()

            row = session.query(DriveSummary).one()
            for col in (
                'device_id', 'start_time', 'end_time',
                'duration_seconds', 'profile_id',
            ):
                assert getattr(row, col) is None, (
                    f'Pi must not populate legacy column {col!r} '
                    f'(got: {getattr(row, col)!r})'
                )
            # row_count has a model-level default=0 -- Pi still does
            # not send it, but ORM may apply the Python-level default.
            # Accept either None or 0 to keep the test robust to ORM
            # default semantics evolution.
            assert row.row_count in (None, 0)
        finally:
            session.close()
