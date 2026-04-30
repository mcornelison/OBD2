################################################################################
# File Name: v0004_us237_drive_summary_reconcile.py
# Purpose/Description: Sprint 19 US-237 -- reconcile the live MariaDB
#                      ``drive_summary`` table with the SQLAlchemy
#                      :class:`src.server.db.models.DriveSummary` model.  The
#                      Sprint 7-8 analytics-shape table never got the US-206
#                      Pi-sync columns, US-195 ``data_source`` tag, US-200
#                      ``drive_id`` column, or the ``UNIQUE(source_device,
#                      source_id)`` upsert key the sync handler queries on.
#                      Every Pi -> server drive_summary sync (148 attempts as
#                      of 2026-04-29) failed with ``Unknown column
#                      'drive_summary.source_id'``.  This migration ALTERs
#                      11 missing columns, adds the drive_id index +
#                      Pi-sync UNIQUE key, and truncates the 9 legacy sim
#                      drive_summary rows + their drive_statistics children.
#                      Idempotent via INFORMATION_SCHEMA probes.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex          | Initial -- Sprint 19 US-237 (V-1 + V-4 close).
# ================================================================================
################################################################################

"""Migration 0004: drive_summary 3-way schema reconciliation (US-237).

Context
-------
Three independent shapes diverged for ``drive_summary`` over Sprint 7-15:

* **Pi SQLite** (``src/pi/obdii/drive_summary.py``, US-206 / US-228 / US-236)
  -- ``drive_id`` PK, ``ambient_temp_at_start_c``, ``starting_battery_v``,
  ``barometric_kpa_at_start``, ``data_source``.
* **Server SQLAlchemy ORM** (``src/server/db/models.py``, US-206 dual-writer
  contract) -- ``id`` autoincrement PK, all analytics columns
  (``device_id``, ``start_time``, ``end_time``, ``duration_seconds``,
  ``profile_id``, ``row_count``, ``is_real``, ``data_source``, ``created_at``)
  PLUS Pi-sync columns (``source_id``, ``source_device``, ``synced_at``,
  ``sync_batch_id``, ``drive_start_timestamp``, ``ambient_temp_at_start_c``,
  ``starting_battery_v``, ``barometric_kpa_at_start``, ``drive_id``)
  PLUS ``UNIQUE(source_device, source_id)``.
* **Server actual MariaDB table** (Sprint 7-8 analytics era) -- ``id``,
  ``device_id``, ``start_time``, ``end_time``, ``duration_seconds``,
  ``profile_id``, ``row_count``, ``created_at``.  None of the US-195 /
  US-200 / US-206 columns ever ALTERed in.

Net effect: the Pi-sync upsert query (``SELECT drive_summary.source_id
FROM drive_summary WHERE drive_summary.source_device = %s AND ...``) hits
an ``Unknown column`` error from MariaDB on every batch.  Ralph's Drive 4
health check (2026-04-29) found 148 such failures vs 93 successes for
other tables.  Drive_summary metadata for drives 2, 3, 4, 5 is on Pi only
until this lands.

Why v0001 didn't catch this: ``CAPTURE_TABLES`` in
:mod:`scripts.apply_server_migrations` (the US-209 catch-up scope)
deliberately excluded ``drive_summary`` because the Sprint 14 grooming
pass treated it as an analytics table.  The US-206 dual-writer reframe
made it both, but the catch-up scope was never expanded.  US-237 is the
explicit reconciliation.

V-4 (drive_id namespace cleanup, CIO-approved 2026-04-29)
---------------------------------------------------------
Nine legacy rows from Sprint 7-8 sim era survive:

* ``device_id IN ('sim-eclipse-gst', 'sim-eclipse-gst-multi',
  'eclipse-gst-day1')``

Their auto-increment ``id`` values (1-10) collide with Pi-minted
``drive_id`` (3, 4, 5...).  drive_statistics rows from 2026-04-16
reference these legacy ids as ``drive_id`` FKs, so a Pi-side query for
"drive 3 statistics" returns the sim-era data, not real Drive 3.  The
CIO-approved fix is to truncate the 9 sim drive_summary rows + cascade
to their drive_statistics children -- matches the US-205 / US-227
"legacy ops cleanup" precedent.  No real-data is lost: real drive
realtime_data rows are tagged with the correct Pi-minted drive_ids and
unaffected.

Idempotency contract
--------------------
1. ``serverTableExists('drive_summary')`` short-circuits on a fresh DB
   where SQLAlchemy ``create_all()`` is the canonical writer (no ALTER
   needed -- the model already declares everything).
2. Each ``ALTER ... ADD COLUMN`` is gated by an
   ``INFORMATION_SCHEMA.COLUMNS`` probe -- skipped when present.
3. ``ALTER ... ADD INDEX`` / ``ADD UNIQUE KEY`` gated by an
   ``INFORMATION_SCHEMA.STATISTICS`` probe.
4. ``DELETE`` statements are unconditionally safe -- a re-run on an
   already-truncated DB simply matches 0 rows (returncode 0).
5. The :class:`src.server.migrations.MigrationRunner` records this
   version after first success, so future deploys skip the entire
   ``apply()`` call.  The probes are belt-and-suspenders for any
   out-of-band schema change between deploys.

Post-condition probes
---------------------
* Every column listed in :data:`_DRIVE_SUMMARY_NEW_COLUMNS` MUST be
  present on the live table.
* Zero rows MUST remain matching the sim-era ``device_id`` filter.

Failure modes (raise :class:`SchemaProbeError`):

* DDL ran but a column is still missing (mysql session-context bug).
* DELETE ran but sim rows survived (filter typo, replication lag).
"""

from __future__ import annotations

from collections.abc import Iterable

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    indexExists,
    probeServerColumns,
    serverTableExists,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'DRIVE_SUMMARY_INDEX_NAME',
    'DRIVE_SUMMARY_NEW_COLUMNS',
    'DRIVE_SUMMARY_UNIQUE_NAME',
    'DESCRIPTION',
    'LEGACY_SIM_DEVICE_IDS',
    'MIGRATION',
    'VERSION',
    'apply',
]


VERSION: str = '0004'
DESCRIPTION: str = (
    'US-237 drive_summary reconcile -- ADD Pi-sync columns + UNIQUE + '
    'drive_id index (matches DriveSummary ORM, US-206/US-195/US-200 '
    'catch-up); DELETE 9 legacy sim rows + cascade drive_statistics '
    '(V-4 namespace cleanup, CIO 2026-04-29)'
)


# ================================================================================
# Schema constants -- mirror src.server.db.models.DriveSummary
# ================================================================================

# (column_name, MariaDB column-type fragment).  Order matches the order in
# the SQLAlchemy model so a stale -> migrated diff is visually obvious.
# NOTE: every type is NULLable (or has a DEFAULT) because pre-existing
# rows must accept the new columns without a backfill -- legacy rows just
# get NULLs and will be truncated by the V-4 cleanup phase.
DRIVE_SUMMARY_NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ('source_id', 'INT NULL'),
    ('source_device', 'VARCHAR(64) NULL'),
    ('synced_at', 'DATETIME DEFAULT CURRENT_TIMESTAMP'),
    ('sync_batch_id', 'INT NULL'),
    ('drive_id', 'INT NULL'),
    ('drive_start_timestamp', 'DATETIME NULL'),
    ('ambient_temp_at_start_c', 'FLOAT NULL'),
    ('starting_battery_v', 'FLOAT NULL'),
    ('barometric_kpa_at_start', 'FLOAT NULL'),
    ('is_real', 'TINYINT(1) DEFAULT 0'),
    ('data_source', "VARCHAR(16) DEFAULT 'real'"),
)

DRIVE_SUMMARY_INDEX_NAME: str = 'IX_drive_summary_drive_id'
DRIVE_SUMMARY_UNIQUE_NAME: str = 'uq_drive_summary_source'

# Sprint 7-8 sim era device_ids per Ralph V-4 / CIO directive 2026-04-29.
# These are the only rows whose drive_summary + drive_statistics children
# get truncated.  Real-data rows (any other device_id) are preserved.
LEGACY_SIM_DEVICE_IDS: tuple[str, ...] = (
    'sim-eclipse-gst',
    'sim-eclipse-gst-multi',
    'eclipse-gst-day1',
)


def _legacyDeviceFilter(deviceIds: Iterable[str] = LEGACY_SIM_DEVICE_IDS) -> str:
    """Return ``device_id IN ('a','b',...)`` SQL fragment for the sim filter."""
    quoted = ', '.join(f"'{d}'" for d in deviceIds)
    return f"device_id IN ({quoted})"


# ================================================================================
# apply
# ================================================================================

def apply(ctx: RunnerContext) -> None:
    """Reconcile drive_summary columns + truncate Sprint 7-8 sim rows.

    See module docstring for the design rationale and idempotency contract.
    """
    # Fresh-DB short-circuit.  SQLAlchemy ``Base.metadata.create_all()`` is
    # the canonical writer for tests and brand-new server installs; the
    # ORM already declares every column in DRIVE_SUMMARY_NEW_COLUMNS so
    # no ALTER is required there.  The migration is purely catch-up DDL.
    if not serverTableExists(ctx.addrs, ctx.creds, 'drive_summary', ctx.runner):
        return

    cols = set(probeServerColumns(
        ctx.addrs, ctx.creds, 'drive_summary', ctx.runner,
    ))

    # Phase 1: ADD COLUMN per missing US-206/US-195/US-200 column.
    for colName, colType in DRIVE_SUMMARY_NEW_COLUMNS:
        if colName in cols:
            continue
        sql = f'ALTER TABLE drive_summary ADD COLUMN {colName} {colType};'
        _emit(ctx, sql, f'add drive_summary.{colName}')

    # Phase 2: drive_id index for per-drive analytics joins.
    if not indexExists(
        ctx.addrs, ctx.creds, 'drive_summary',
        DRIVE_SUMMARY_INDEX_NAME, ctx.runner,
    ):
        _emit(
            ctx,
            (
                f'ALTER TABLE drive_summary ADD INDEX '
                f'{DRIVE_SUMMARY_INDEX_NAME} (drive_id);'
            ),
            'add drive_summary.drive_id index',
        )

    # Phase 3: UNIQUE(source_device, source_id) -- the natural key the Pi-sync
    # upsert handler queries.  Without this, every Pi sync of drive_summary
    # fails with "Unknown column 'drive_summary.source_id'".
    if not indexExists(
        ctx.addrs, ctx.creds, 'drive_summary',
        DRIVE_SUMMARY_UNIQUE_NAME, ctx.runner,
    ):
        _emit(
            ctx,
            (
                f'ALTER TABLE drive_summary ADD UNIQUE KEY '
                f'{DRIVE_SUMMARY_UNIQUE_NAME} (source_device, source_id);'
            ),
            'add drive_summary Pi-sync unique key',
        )

    # Phase 4: cascade-delete drive_statistics children of legacy sim rows.
    # MariaDB allows the cross-table sub-select.  drive_statistics is
    # different from drive_summary so the "can't-modify-and-select-same-
    # table" restriction does not apply.
    cascadeSql = (
        'DELETE FROM drive_statistics WHERE drive_id IN '
        f'(SELECT id FROM drive_summary WHERE {_legacyDeviceFilter()});'
    )
    _emit(ctx, cascadeSql, 'cascade-delete legacy drive_statistics rows')

    # Phase 5: delete legacy sim drive_summary rows.
    _emit(
        ctx,
        f'DELETE FROM drive_summary WHERE {_legacyDeviceFilter()};',
        'delete legacy sim drive_summary rows',
    )

    # ---- Post-condition probes ------------------------------------------
    # Verify every new column actually landed (mysql session-context bug
    # would silently no-op without raising).
    postCols = set(probeServerColumns(
        ctx.addrs, ctx.creds, 'drive_summary', ctx.runner,
    ))
    missing = [c for c, _t in DRIVE_SUMMARY_NEW_COLUMNS if c not in postCols]
    if missing:
        raise SchemaProbeError(
            f'drive_summary columns missing post-migration: {missing}',
        )

    # Verify zero sim rows remain.
    countSql = (
        f'SELECT COUNT(*) FROM drive_summary WHERE {_legacyDeviceFilter()};'
    )
    res = _runServerSql(ctx.addrs, ctx.creds, countSql, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'post-delete count probe failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    txt = res.stdout.strip()
    try:
        remaining = int(txt.split()[0]) if txt else 0
    except (ValueError, IndexError) as err:
        raise SchemaProbeError(
            f'post-delete count probe returned non-integer: {txt!r}',
        ) from err
    if remaining != 0:
        raise SchemaProbeError(
            f'expected 0 legacy sim drive_summary rows post-delete, '
            f'found {remaining}',
        )


def _emit(ctx: RunnerContext, sql: str, reason: str) -> None:
    """Run one DDL/DML statement and raise MigrationError on failure."""
    res = _runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'{reason} failed: {res.stderr.strip() or res.stdout.strip()}',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
