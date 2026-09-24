################################################################################
# File Name: v0028_us795a_sync_history_residual.py
# Purpose/Description: US-795-a -- ADD COLUMN ``residual_rows`` and
#                      ``residual_complete`` to ``sync_history`` so a completed
#                      sync session records what the car STILL held when it
#                      closed, together with the qualifier that says whether
#                      that number is exact or a lower bound.
# Author: Ralph (US-795-a)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-795-a) | Initial -- two nullable columns, no
#               |                  | backfill, no rewrite.
# ================================================================================
################################################################################
"""Add the sync residual and its completeness qualifier to ``sync_history``.

``sync_history`` recorded what MOVED (``rows_synced``) and never what REMAINED.
The residual is the only statement about the Pi that stays true after it goes
dark, so it belongs on the session row rather than being recomputed later from
a device that may never be reachable again.

🔴 **BOTH COLUMNS ARE NULLABLE AND NEITHER HAS A DEFAULT.**  Three states must
stay distinguishable::

    (0,    TRUE )   the car owed nothing, and every table could be read
    (12,   FALSE)   AT LEAST 12 -- some tables were unreadable
    (NULL, NULL )   we could not determine what the car owed

A ``NOT NULL DEFAULT 0`` would collapse the third into the first.  Every row
written before this migration, and every session that could not measure, would
then assert that the car owed nothing -- reporting a healthy car on the
evidence of a failed measurement.  That is why the migration deliberately
BACKFILLS NOTHING: an unmeasured past is unknown, and saying so is the point.

⚠️ **On "reversible".**  This runner ships no down-migration machinery, by
design -- ``src/server/migrations/runner.py`` says "No rollback machinery"
and seven prior versions record "rollback is snapshot + redeploy prior
version".  What this migration offers instead is that it is
**NON-DESTRUCTIVE**: it adds two nullable columns, backfills nothing and
rewrites no existing row, so :data:`REVERT_DDL` restores the previous shape
exactly.  Nothing else about the table changes.

Idempotent: each ADD COLUMN is guarded by its own INFORMATION_SCHEMA probe, so
a partial-success state from an interrupted run converges on re-apply.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    _runServerSql,
    probeServerColumns,
    serverTableExists,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'ADD_RESIDUAL_COMPLETE_DDL',
    'ADD_RESIDUAL_ROWS_DDL',
    'DESCRIPTION',
    'MIGRATION',
    'RESIDUAL_COLUMNS',
    'REVERT_DDL',
    'TABLE_NAME',
    'VERSION',
    'apply',
]

VERSION: str = '0028'

TABLE_NAME: str = 'sync_history'

RESIDUAL_ROWS_COLUMN: str = 'residual_rows'
RESIDUAL_COMPLETE_COLUMN: str = 'residual_complete'

#: Both new columns, in the order they are added.
RESIDUAL_COLUMNS: tuple[str, ...] = (
    RESIDUAL_ROWS_COLUMN,
    RESIDUAL_COMPLETE_COLUMN,
)

DESCRIPTION: str = (
    'US-795-a sync_history.residual_rows + residual_complete -- record what the '
    'car still held at session close, with the qualifier that says whether the '
    'count is exact or a lower bound. Nullable, no backfill: NULL means unknown.'
)

# DDLs mirror the ``SyncHistory`` ORM declarations. Column shape:
#  * INTEGER / BOOLEAN  -- matches Integer / Boolean on the model
#  * NULL allowed       -- matches Mapped[int | None] / Mapped[bool | None]
#  * NO DEFAULT         -- so an absent measurement stays absent. See the
#                          module docstring; this is the whole point.
ADD_RESIDUAL_ROWS_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} ADD COLUMN {RESIDUAL_ROWS_COLUMN} INTEGER NULL;'
)

ADD_RESIDUAL_COMPLETE_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} '
    f'ADD COLUMN {RESIDUAL_COMPLETE_COLUMN} BOOLEAN NULL;'
)

#: Not wired to any runner -- this framework applies forward only. Recorded so
#: the non-destructive claim in the docstring is checkable rather than asserted.
REVERT_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} '
    f'DROP COLUMN {RESIDUAL_COMPLETE_COLUMN}, '
    f'DROP COLUMN {RESIDUAL_ROWS_COLUMN};'
)

def apply(ctx: RunnerContext) -> None:
    """Add the two residual columns to live ``sync_history``.

    Each ADD COLUMN is guarded by a column probe, so re-applying after a
    partial run is a no-op rather than an error.  No row is read, written or
    backfilled: an unmeasured past stays unknown.

    Args:
        ctx: Runner context supplying addresses, credentials and the command
            runner.

    Raises:
        MigrationError: If ``sync_history`` is absent, or an ADD COLUMN fails.
    """
    if not serverTableExists(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner):
        raise MigrationError(
            f'{TABLE_NAME!r} table missing; v0028 cannot add the residual '
            'columns to a non-existent table.',
        )

    columns = probeServerColumns(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner)

    for columnName, ddl in (
        (RESIDUAL_ROWS_COLUMN, ADD_RESIDUAL_ROWS_DDL),
        (RESIDUAL_COMPLETE_COLUMN, ADD_RESIDUAL_COMPLETE_DDL),
    ):
        if columnName in columns:
            continue
        res = _runServerSql(ctx.addrs, ctx.creds, ddl, ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'add {columnName!r} to {TABLE_NAME!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
