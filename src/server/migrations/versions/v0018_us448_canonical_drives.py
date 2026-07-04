################################################################################
# File Name: v0018_us448_canonical_drives.py
# Purpose/Description: US-448 registry migration (F-104 server-analytics-authority
#                      spine) -- creates the canonical ``drives`` table on live
#                      MariaDB so :class:`src.server.db.models.Drive` has a
#                      matching physical table, then SUBSUMES the pre-existing
#                      de-facto identity ``drive_summary.id`` by inserting each
#                      existing ``drive_summary.id`` value in as the new
#                      ``drive_id`` (identity preserved -> existing
#                      drive_summary.id foreign keys stay numerically valid).
#                      Forward-only; ``drive_id`` is the single drive-identity
#                      SSOT, the Pi's drive_counter id demoted to the advisory
#                      nullable ``source_drive_id``.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-448) | Initial -- Sprint 55 US-448 (F-104 spine).
# ================================================================================
################################################################################

"""Migration 0018: canonical ``drives`` identity table (US-448 / F-104).

Two substeps, applied in order:

1. **CREATE ``drives``** (idempotent: INFORMATION_SCHEMA probe + ``IF NOT
   EXISTS``) with the server-minted ``drive_id`` PK anchored by a
   ``UNIQUE (source_device, source_drive_id)`` constraint (the natural-key
   mint anchor -- see :mod:`src.server.analytics.drive_identity`).

2. **SUBSUME ``drive_summary.id``** -- ``INSERT INTO drives (drive_id, ...)
   SELECT ds.id, ... FROM drive_summary`` so every existing drive keeps its
   identity value as ``drive_id``.  The Atlas ruling is explicit: do NOT mint
   a 5th orthogonal id (that worsens the D-8 id-family sprawl this spine
   exists to fix).  Because ``drives.drive_id`` == the old ``drive_summary.id``,
   the existing ``drive_statistics.summary_id -> drive_summary.id`` foreign key
   remains numerically valid; US-451 later re-points the FK constraints at
   ``drives.drive_id`` (no data change, values already match).

Idempotency contract (mirrors v0013/v0017): the CREATE is guarded by an
INFORMATION_SCHEMA probe + ``IF NOT EXISTS``; the subsume backfill is guarded
by ``WHERE ds.id NOT IN (SELECT drive_id FROM drives)`` so a replay inserts
nothing new.  The MigrationRunner also records the version on first success
and skips subsequent runs.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    serverTableExists,
)
from src.server.db.models import (
    DRIVES_DATA_QUALITY_DEFAULT,
    DRIVES_DATA_QUALITY_VALUES,
    DRIVES_SOURCE_UNIQUE_CONSTRAINT,
    DRIVES_TABLE,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = ['MIGRATION', 'VERSION', 'DESCRIPTION', 'apply']


VERSION: str = '0018'
DESCRIPTION: str = (
    'US-448 canonical drives identity table -- server-minted drive_id SSOT '
    'anchored by UNIQUE(source_device, source_drive_id); subsumes the '
    'existing drive_summary.id (F-104 spine)'
)


# The data_quality CHECK enum, rendered from the model SSOT so the physical
# constraint matches the ORM (a bad value can never be persisted on either
# SQLite or MariaDB).
_DATA_QUALITY_CHECK: str = (
    'data_quality IN '
    f"({','.join(repr(v) for v in DRIVES_DATA_QUALITY_VALUES)})"
)

# Match the SQLAlchemy Drive model in src/server/db/models.py.  drive_id is the
# server-minted autoincrement PK (the SSOT identity); source_device +
# source_drive_id are the advisory Pi ids (nullable), UNIQUE-anchored so the
# mint is an idempotent upsert-by-natural-key.  data_quality VARCHAR(20)
# matches DATA_QUALITY_COLUMN_LENGTH.
CREATE_DRIVES_DDL: str = (
    f'CREATE TABLE IF NOT EXISTS {DRIVES_TABLE} ('
    '    drive_id        INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '    source_device   VARCHAR(64),'
    '    source_drive_id INT NULL,'
    '    start_time      DATETIME,'
    '    end_time        DATETIME NULL,'
    "    data_source     VARCHAR(16) DEFAULT 'real',"
    '    data_quality    VARCHAR(20) NOT NULL '
    f"        DEFAULT '{DRIVES_DATA_QUALITY_DEFAULT}',"
    f'    CONSTRAINT {DRIVES_SOURCE_UNIQUE_CONSTRAINT}'
    '        UNIQUE (source_device, source_drive_id),'
    f'    CONSTRAINT ck_drives_data_quality CHECK ({_DATA_QUALITY_CHECK})'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    '  COLLATE=utf8mb4_unicode_ci;'
)


# SUBSUME drive_summary.id -> drives.drive_id.  The explicit ``ds.id`` insert
# preserves the identity value (do NOT let AUTO_INCREMENT renumber).  The Pi's
# drive id lands in the advisory source_drive_id (COALESCE picks source_id, or
# the mirrored drive_id -- they are equal by the drive_summary invariant, or
# one is NULL for legacy rows).  ``WHERE ds.id NOT IN (SELECT drive_id FROM
# drives)`` makes the backfill idempotent: a replay re-inserts nothing.
BACKFILL_DRIVES_FROM_SUMMARY_DDL: str = (
    f'INSERT INTO {DRIVES_TABLE} '
    '(drive_id, source_device, source_drive_id, start_time, end_time, '
    'data_source, data_quality) '
    'SELECT ds.id, ds.source_device, '
    'COALESCE(ds.source_id, ds.drive_id), '
    'COALESCE(ds.drive_start_timestamp, ds.start_time), '
    'ds.end_time, '
    "COALESCE(ds.data_source, 'real'), "
    'ds.data_quality '
    'FROM drive_summary ds '
    f'WHERE ds.id NOT IN (SELECT drive_id FROM {DRIVES_TABLE});'
)


def _applyCreateDrives(ctx: RunnerContext) -> None:
    """Create ``drives`` if absent, then post-probe it actually landed."""
    if serverTableExists(ctx.addrs, ctx.creds, DRIVES_TABLE, ctx.runner):
        return

    res = _runServerSql(ctx.addrs, ctx.creds, CREATE_DRIVES_DDL, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'create {DRIVES_TABLE} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    # Post-condition probe: guard against a silent mysql no-op (wrong default
    # DB, filtered replica) before the runner records the version.
    if not serverTableExists(ctx.addrs, ctx.creds, DRIVES_TABLE, ctx.runner):
        raise SchemaProbeError(
            f'{DRIVES_TABLE} missing after CREATE TABLE ran; investigate the '
            'MariaDB session context',
        )


def _applySubsumeDriveSummaryId(ctx: RunnerContext) -> None:
    """Insert every drive_summary.id as a drives.drive_id (idempotent)."""
    res = _runServerSql(
        ctx.addrs, ctx.creds, BACKFILL_DRIVES_FROM_SUMMARY_DDL, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'subsume drive_summary.id into {DRIVES_TABLE} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )


def apply(ctx: RunnerContext) -> None:
    """Create ``drives`` then subsume ``drive_summary.id`` into it.

    Ordering is load-bearing: the table must exist before the subsume INSERT
    can target it.  Both substeps are individually idempotent, so replaying
    the whole migration on an already-migrated DB is a safe no-op.
    """
    _applyCreateDrives(ctx)
    _applySubsumeDriveSummaryId(ctx)


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
