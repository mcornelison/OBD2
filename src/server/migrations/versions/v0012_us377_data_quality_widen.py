################################################################################
# File Name: v0012_us377_data_quality_widen.py
# Purpose/Description: Sprint 45 V0.28.2 (US-377 / F-107) -- widen the
#                      ``data_quality`` columns on ``drive_summary`` and
#                      ``drive_statistics`` from VARCHAR(16) to VARCHAR(20).
#                      The V0.28.1 IRL drill (2026-06-01) hit MariaDB DataError
#                      1406 ("Data too long") recomputing the dual-attribution
#                      drives 23+24: both columns are VARCHAR(16) but their own
#                      CHECK enums permit 'attribution_anomaly' (19 chars).
#                      SQLite never enforces VARCHAR width, so the fresh-DB
#                      ``create_all`` tests passed while production failed (the
#                      same false-pass class as v0009 / I-041).  This migration
#                      MODIFYs each column to VARCHAR(20) -- preserving NOT NULL
#                      + DEFAULT 'full' -- so recompute_drive_analytics can stamp
#                      the anomaly value.  Idempotent via a
#                      CHARACTER_MAXIMUM_LENGTH probe: a fresh ``create_all`` DB
#                      (ORM already declares VARCHAR(20)) and a re-run are no-ops.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-01    | Rex (US-377) | Initial -- data_quality VARCHAR(16)->VARCHAR(20)
#               |              | width hotfix (drill-revealed regression).
# ================================================================================
################################################################################

"""Migration 0012: widen data_quality to VARCHAR(20) (US-377 / F-107).

Context
-------
The V0.27.18 dual-attribution tripwire (US-363) stamps
``data_quality='attribution_anomaly'`` (19 chars) on overlapping drives.  Both
``drive_summary.data_quality`` and ``drive_statistics.data_quality`` were
created VARCHAR(16):

* v0009 created ``drive_statistics.data_quality`` VARCHAR(16) (then a 3-value
  enum whose longest value, ``below_threshold``, is 15 chars -- it fit).
* v0010 (US-363) widened the *CHECK* on both columns to include
  ``attribution_anomaly`` and created ``drive_summary.data_quality`` VARCHAR(16),
  but neither widened the *column*.

The CHECK now permits a 19-char value the column cannot hold.  MariaDB raises
``DataError 1406`` on write; SQLite (no width enforcement) silently accepts it,
so every unit test passed.  This migration converges the column width with its
CHECK.

SSOT
----
``src.server.db.models.DATA_QUALITY_COLUMN_LENGTH`` (20) is the sole source of
truth for the width; the ORM columns and this migration both read it, so a
future widen is a one-line change that the width-invariant test
(``test_migration_0012_data_quality_widen``) keeps honest.

Idempotency contract
--------------------
For each table the migration probes ``CHARACTER_MAXIMUM_LENGTH`` and MODIFYs the
column only when it is narrower than the target:

1. Production (VARCHAR(16)) -> emit the MODIFY.
2. Already-migrated re-run / fresh ``create_all`` DB (VARCHAR(20)) -> no-op.
3. Any wider width -> no-op (never narrows).

A post-condition probe re-reads the width and raises :class:`SchemaProbeError`
if it is still below target -- shielding operators from the silent mysql
session-context class (wrong default DB, filtered replica) per the v0002 /
v0009 / v0010 post-probe pattern.

Reversibility
-------------
Widening a VARCHAR is non-destructive (existing values are preserved; no value
is truncated going wider).  No down-migration ships; rollback is "snapshot +
redeploy prior version" per the runner's documented design.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    serverTableExists,
)
from src.server.db.models import (
    DATA_QUALITY_COLUMN_LENGTH,
    DRIVE_STATISTICS_DATA_QUALITY_DEFAULT,
    DRIVE_SUMMARY_DATA_QUALITY_DEFAULT,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'COLUMN_NAME',
    'DESCRIPTION',
    'DRIVE_STATISTICS_TABLE',
    'DRIVE_SUMMARY_TABLE',
    'MIGRATION',
    'MODIFY_DRIVE_STATISTICS_DATA_QUALITY_DDL',
    'MODIFY_DRIVE_SUMMARY_DATA_QUALITY_DDL',
    'TARGET_WIDTH',
    'VERSION',
    'apply',
]


VERSION: str = '0012'
DESCRIPTION: str = (
    'US-377 F-107 -- widen drive_summary + drive_statistics data_quality '
    "VARCHAR(16)->VARCHAR(20) so 'attribution_anomaly' (19 chars) fits "
    '(drill-revealed DataError 1406 regression)'
)


# Identifiers + target width are pinned as module constants so tests assert on
# them and the DDL reads the same SSOT width the ORM does.
TARGET_WIDTH: int = DATA_QUALITY_COLUMN_LENGTH
COLUMN_NAME: str = 'data_quality'
DRIVE_SUMMARY_TABLE: str = 'drive_summary'
DRIVE_STATISTICS_TABLE: str = 'drive_statistics'


# MODIFY re-states the full column definition (MariaDB requires it) so the widen
# preserves NOT NULL + DEFAULT 'full' -- a bare ``MODIFY ... VARCHAR(20)`` would
# silently drop both.  Both columns default to 'full'.
MODIFY_DRIVE_SUMMARY_DATA_QUALITY_DDL: str = (
    f"ALTER TABLE {DRIVE_SUMMARY_TABLE} "
    f"MODIFY {COLUMN_NAME} VARCHAR({TARGET_WIDTH}) NOT NULL "
    f"DEFAULT '{DRIVE_SUMMARY_DATA_QUALITY_DEFAULT}';"
)
MODIFY_DRIVE_STATISTICS_DATA_QUALITY_DDL: str = (
    f"ALTER TABLE {DRIVE_STATISTICS_TABLE} "
    f"MODIFY {COLUMN_NAME} VARCHAR({TARGET_WIDTH}) NOT NULL "
    f"DEFAULT '{DRIVE_STATISTICS_DATA_QUALITY_DEFAULT}';"
)


def _columnCharLength(
    ctx: RunnerContext, tableName: str, columnName: str,
) -> int | None:
    """Return the ``CHARACTER_MAXIMUM_LENGTH`` of a column, or ``None``.

    ``None`` means the column does not exist (no row) -- the caller treats that
    as a hard error (the column predates v0012 and must be present).
    """
    sql = (
        "SELECT CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
        f"WHERE TABLE_SCHEMA='{ctx.creds.dbName}' "
        f"AND TABLE_NAME='{tableName}' "
        f"AND COLUMN_NAME='{columnName}';"
    )
    res = _runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'{columnName!r} width probe on {tableName!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    txt = res.stdout.strip()
    if not txt:
        return None
    try:
        return int(txt.split()[0])
    except (ValueError, IndexError):
        return None


def _widenDataQualityColumn(
    ctx: RunnerContext, tableName: str, modifyDdl: str,
) -> None:
    """Widen one ``data_quality`` column to ``TARGET_WIDTH`` if it is narrower.

    Idempotent: a column already at or above the target width is a no-op.  A
    post-condition probe re-reads the width and raises on the silent-no-op class.
    """
    if not serverTableExists(ctx.addrs, ctx.creds, tableName, ctx.runner):
        raise MigrationError(
            f'{tableName!r} table missing; v0012 cannot widen its '
            f'{COLUMN_NAME!r} column.  Investigate why create_all + earlier '
            f'migrations did not land the table.',
        )

    width = _columnCharLength(ctx, tableName, COLUMN_NAME)
    if width is None:
        raise MigrationError(
            f'{COLUMN_NAME!r} column missing from {tableName!r}; v0012 cannot '
            f'widen a column that is not there.  Investigate the table shape '
            f'(v0009/v0010 should have created it).',
        )

    # Already wide enough (fresh create_all from the VARCHAR(20) ORM, a prior
    # run, or a hand-widened column).  No-op.
    if width >= TARGET_WIDTH:
        return

    res = _runServerSql(ctx.addrs, ctx.creds, modifyDdl, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'widen {tableName}.{COLUMN_NAME} to VARCHAR({TARGET_WIDTH}) '
            f'failed: {res.stderr.strip() or res.stdout.strip()}',
        )

    # Post-condition probe: the column MUST now be at least the target width.
    widthAfter = _columnCharLength(ctx, tableName, COLUMN_NAME)
    if widthAfter is None or widthAfter < TARGET_WIDTH:
        raise SchemaProbeError(
            f'{tableName}.{COLUMN_NAME} is VARCHAR({widthAfter}) after MODIFY '
            f'ran (expected >= {TARGET_WIDTH}); investigate the MariaDB session '
            f'context (wrong DB? filtered replica?).',
        )


def apply(ctx: RunnerContext) -> None:
    """Widen both ``data_quality`` columns to VARCHAR(20) (US-377 / F-107)."""
    _widenDataQualityColumn(
        ctx, DRIVE_SUMMARY_TABLE, MODIFY_DRIVE_SUMMARY_DATA_QUALITY_DDL,
    )
    _widenDataQualityColumn(
        ctx, DRIVE_STATISTICS_TABLE, MODIFY_DRIVE_STATISTICS_DATA_QUALITY_DDL,
    )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
