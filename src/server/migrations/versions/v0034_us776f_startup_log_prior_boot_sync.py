################################################################################
# File Name: v0034_us776f_startup_log_prior_boot_sync.py
# Purpose/Description: US-776-f (F-138) -- ADD the four prior-boot shutdown-sync
#                      columns to ``startup_log``: prior_boot_home_state,
#                      prior_boot_sync_outcome, prior_boot_backlog_start and
#                      prior_boot_backlog_end.  The Pi lands them at boot from
#                      powerwatch's shutdown record; the existing startup_log
#                      snapshot sync carries them here.
# Author: Rex (US-776-f)
# Creation Date: 2026-09-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-30    | Rex (US-776-f) | Initial -- four nullable columns, each added
#               |                | only when the column probe says it is missing.
# ================================================================================
################################################################################
"""Add the ``startup_log`` prior-boot shutdown-sync columns (US-776-f).

Why the server needs this: ``runSnapshotUpsert`` copies only the columns the
``StartupLog`` model declares, so without the model columns AND this migration
the Pi's values would be dropped on the floor at ingest -- the analysis the
sprint exists for (``prior_boot_sync_outcome = DELIVERED`` with
``prior_boot_backlog_start > 0``) could never be run server-side.

Replay-safe (specs/design-patterns.md #10): one column probe decides, each
column is added only when absent, and a re-run issues no ALTER.  A partially
applied earlier run is finished, not repeated.  All four columns are nullable
with no default (NULL = not recorded), so :data:`REVERT_DDL` restores the
previous shape exactly.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    probeServerColumns,
    serverTableExists,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'ADD_COLUMN_DDL',
    'COLUMN_TYPES',
    'DESCRIPTION',
    'MIGRATION',
    'REVERT_DDL',
    'TABLE_NAME',
    'VERSION',
    'apply',
]

VERSION: str = '0034'

TABLE_NAME: str = 'startup_log'

DESCRIPTION: str = (
    'US-776-f startup_log prior_boot_home_state / prior_boot_sync_outcome / '
    'prior_boot_backlog_start / prior_boot_backlog_end -- the prior boot\'s '
    'shutdown-sync record, landed by the Pi at boot. Nullable: NULL = not recorded.'
)

#: Column -> MariaDB type, in model order.  VARCHAR(64) mirrors ``String(64)``
#: on the model (the width of the existing prior_boot_last_stage/_reason).
COLUMN_TYPES: dict[str, str] = {
    'prior_boot_home_state': 'VARCHAR(64)',
    'prior_boot_sync_outcome': 'VARCHAR(64)',
    'prior_boot_backlog_start': 'INT',
    'prior_boot_backlog_end': 'INT',
}

ADD_COLUMN_DDL: dict[str, str] = {
    column: f'ALTER TABLE {TABLE_NAME} ADD COLUMN {column} {sqlType} NULL;'
    for column, sqlType in COLUMN_TYPES.items()
}

#: Not wired to any runner -- this framework applies forward only.  Recorded so
#: the non-destructive claim in the docstring is checkable rather than asserted.
REVERT_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} '
    + ', '.join(f'DROP COLUMN {column}' for column in COLUMN_TYPES)
    + ';'
)


def apply(ctx: RunnerContext) -> None:
    """Add each missing prior-boot sync column to ``startup_log``.

    Args:
        ctx: Runner context supplying addresses, credentials and the command
            runner.

    Raises:
        MigrationError: If the table is absent or any ALTER fails.
        SchemaProbeError: If a column is still missing after ADD COLUMN
            reported success.
    """
    if not serverTableExists(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner):
        raise MigrationError(
            f'{TABLE_NAME!r} table missing; v0034 cannot add its prior-boot sync '
            'columns to a non-existent table (v0014 creates it).',
        )

    existing = probeServerColumns(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner)
    missing = [column for column in COLUMN_TYPES if column not in existing]
    if not missing:
        return

    for column in missing:
        res = _runServerSql(ctx.addrs, ctx.creds, ADD_COLUMN_DDL[column], ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'add {column!r} to {TABLE_NAME!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    after = probeServerColumns(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner)
    stillMissing = [column for column in missing if column not in after]
    if stillMissing:
        raise SchemaProbeError(
            f'{TABLE_NAME!r} still lacks {", ".join(stillMissing)} after ADD '
            'COLUMN reported success.',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
