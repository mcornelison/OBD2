################################################################################
# File Name: v0006_td043_drive_summary_legacy_nullable.py
# Purpose/Description: TD-043 close -- ALTER 6 legacy drive_summary columns to
#                      NULL DEFAULT NULL so Pi-sync INSERTs (which omit them)
#                      no longer fail with "Field doesn't have a default value"
#                      (MariaDB error 1364). Captures the post-Sprint-20 manual
#                      production hotfix that CIO ran live on chi-srv-01 on
#                      2026-05-01 -- making it reproducible across server
#                      reinstalls / disaster recovery.
# Author: Marcus (PM)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Marcus       | Initial -- TD-043 close (post-Sprint-20 hotfix capture).
# ================================================================================
################################################################################

"""Migration 0006: drive_summary legacy columns -> nullable (TD-043 close).

Context
-------
Sprint 19 US-237 v0004 migration (``v0004_us237_drive_summary_reconcile.py``)
ALTERed in 11 new Pi-sync columns + the ``UNIQUE(source_device, source_id)``
upsert key, but did NOT touch the 6 pre-existing Sprint-7/8 legacy columns:

* ``device_id`` VARCHAR(64) NOT NULL -- legacy device attribution
* ``start_time`` DATETIME NOT NULL -- legacy drive-window start
* ``end_time`` DATETIME -- already nullable
* ``duration_seconds`` INT -- already nullable
* ``profile_id`` VARCHAR(64) -- already nullable
* ``row_count`` INT -- already nullable

Pi-sync INSERTs use the modern columns (``source_device`` + ``source_id`` +
``drive_start_timestamp``) and OMIT the legacy ones.  Two of the legacy
columns (``device_id``, ``start_time``) carry NOT NULL with no default ->
MariaDB rejects every Pi INSERT with error 1364 ("Field doesn't have a
default value").

Symptom: post-Sprint-20 deploy 2026-05-01, every Pi ``drive_summary`` sync
attempt returned 500.  Pi ``sync_log.drive_summary`` stuck at
``last_synced_id=0 status=failed``.  CIO ran two live ALTERs to make
``device_id`` and ``start_time`` nullable; sync flipped to ``status=ok``
within 30 seconds.

This migration captures those manual ALTERs as schema_migrations history
so a fresh ``apply_server_migrations.py --execute`` run reproduces the
correct schema.  Without this capture, disaster recovery from migrations
alone would land the server back in the broken state.

We pre-emptively MODIFY all 6 legacy columns -- the 4 already-nullable ones
are no-ops at the MariaDB level (MODIFY to identical state); the 2
broken-NOT-NULL ones get fixed.  This makes the migration robust against
any future drift on the still-NOT-NULL columns.

Idempotency contract
--------------------
1. ``serverTableExists('drive_summary')`` short-circuits if table missing
   (would indicate v0004 hadn't run; this migration is a follow-up).
2. ALTER TABLE ... MODIFY is idempotent at MariaDB-DDL level -- modifying
   a column to its existing definition is a no-op.
3. The :class:`src.server.migrations.MigrationRunner` records this version
   after first success; future deploys skip the ``apply()`` call entirely.

Sprint 21 follow-up (NOT in this migration)
-------------------------------------------
Spool flagged in 2026-05-01 inbox note: should the legacy columns be DROPPED
entirely once data has been migrated to the new columns?  Audit pending --
need to verify no analytics queries still reference ``device_id`` /
``start_time`` / etc.  Defer to Sprint 21 ``v0007`` migration.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    serverTableExists,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'ALTER_DRIVE_SUMMARY_LEGACY_NULLABLE_DDL',
    'DESCRIPTION',
    'MIGRATION',
    'VERSION',
    'apply',
]


VERSION: str = '0006'
DESCRIPTION: str = (
    'TD-043 drive_summary legacy columns -> NULL DEFAULT NULL '
    '(captures post-Sprint-20 manual hotfix as reproducible migration)'
)


# Single ALTER with multiple MODIFY clauses -- atomic on MariaDB.  Each MODIFY
# explicitly sets NULL DEFAULT NULL; the 4 already-nullable columns are no-ops
# at the MariaDB level (MODIFY to identical state has no effect).  The 2
# previously-NOT-NULL columns (device_id, start_time) get fixed.
ALTER_DRIVE_SUMMARY_LEGACY_NULLABLE_DDL: str = (
    'ALTER TABLE drive_summary '
    '  MODIFY device_id VARCHAR(64) NULL DEFAULT NULL, '
    '  MODIFY start_time DATETIME NULL DEFAULT NULL, '
    '  MODIFY end_time DATETIME NULL DEFAULT NULL, '
    '  MODIFY duration_seconds INT NULL DEFAULT NULL, '
    '  MODIFY profile_id VARCHAR(64) NULL DEFAULT NULL, '
    '  MODIFY row_count INT NULL DEFAULT NULL;'
)


def apply(ctx: RunnerContext) -> None:
    """ALTER drive_summary legacy columns to NULL DEFAULT NULL (TD-043).

    Idempotent: ALTER MODIFY to identical state is a no-op at MariaDB level,
    so re-running this migration after CIO's manual hotfix already landed
    is safe.  The post-condition probe verifies device_id is nullable
    (the marker column) -- catches the silent-no-op class.
    """
    # Short-circuit if drive_summary doesn't exist (would indicate v0004
    # never ran; this is a follow-up to v0004 + can't run standalone).
    if not serverTableExists(ctx.addrs, ctx.creds, 'drive_summary', ctx.runner):
        raise MigrationError(
            'drive_summary table missing; v0006 requires v0004 to have run first',
        )

    res = _runServerSql(
        ctx.addrs, ctx.creds,
        ALTER_DRIVE_SUMMARY_LEGACY_NULLABLE_DDL,
        ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'alter drive_summary legacy columns failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    # Post-condition probe: device_id MUST be nullable post-migration.
    # If MariaDB silently no-op'd the ALTER (wrong DB context, replication
    # filter, etc.), this probe surfaces it loudly rather than letting
    # the runner record the version against an unchanged schema.
    probe_sql = (
        "SELECT IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = 'drive_summary' "
        "AND COLUMN_NAME = 'device_id';"
    )
    probe = _runServerSql(ctx.addrs, ctx.creds, probe_sql, ctx.runner)
    if probe.returncode != 0:
        raise SchemaProbeError(
            f'post-ALTER probe of device_id failed: '
            f'{probe.stderr.strip() or probe.stdout.strip()}',
        )
    if 'YES' not in probe.stdout:
        raise SchemaProbeError(
            'drive_summary.device_id still NOT NULL after ALTER ran; '
            'investigate the MariaDB session context (TD-043 capture)',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
