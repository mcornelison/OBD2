################################################################################
# File Name: v0035_arch065_battery_capacity_columns.py
# Purpose/Description: ARCH-065 -- ADD the ten battery-capacity columns to
#                      ``battery_health_log`` (drain_trigger, cell_epoch,
#                      cut_step_mv, window_start_s, window_end_s,
#                      drain_rate_mv_s, verdict, t_floor_s, floor_vcell_v,
#                      cutoff_vcell_v) and the four prior-boot columns to
#                      ``startup_log`` (prior_boot_sync_started_at,
#                      prior_boot_sync_ended_at, prior_boot_vcell_before_cut_v,
#                      prior_boot_loss_at).
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author            | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a) | Initial -- two tables, each column added
#               |                   | only when the column probe says it is missing.
# ================================================================================
################################################################################
"""Add the ARCH-065 battery-capacity columns (battery_health_log, startup_log).

Why the server needs this: ``runSnapshotUpsert`` / the delta upsert copy only
the columns the model declares, so without the model columns AND this migration
the Pi's capacity values would be dropped at ingest.

Replay-safe (specs/design-patterns.md #10): one column probe per table decides,
each column is added only when absent, and a re-run issues no ALTER.  A
partially applied earlier run is finished, not repeated.  Every column is
nullable with no default (NULL = not recorded) except ``drain_trigger``, which
is ``NOT NULL DEFAULT 'keyoff'`` so legacy rows read as key-off drains exactly
as the Pi's own ADD COLUMN does.  :data:`REVERT_DDL` restores the previous shape.
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
    'COLUMNS',
    'DESCRIPTION',
    'MIGRATION',
    'REVERT_DDL',
    'VERSION',
    'apply',
]

VERSION: str = '0035'

DESCRIPTION: str = (
    'ARCH-065 battery capacity: battery_health_log drain_trigger / cell_epoch / '
    'cut_step_mv / window_start_s / window_end_s / drain_rate_mv_s / verdict / '
    't_floor_s / floor_vcell_v / cutoff_vcell_v, and startup_log '
    'prior_boot_sync_started_at / prior_boot_sync_ended_at / '
    'prior_boot_vcell_before_cut_v / prior_boot_loss_at.'
)

#: Table -> column -> MariaDB type (without the NULL / NOT NULL tail), in model
#: order.  Widths mirror the ``String(n)`` columns on the models.
COLUMNS: dict[str, dict[str, str]] = {
    'battery_health_log': {
        'drain_trigger': "VARCHAR(16) NOT NULL DEFAULT 'keyoff'",
        'cell_epoch': 'VARCHAR(32)',
        'cut_step_mv': 'FLOAT',
        'window_start_s': 'INT',
        'window_end_s': 'INT',
        'drain_rate_mv_s': 'FLOAT',
        'verdict': 'VARCHAR(16)',
        't_floor_s': 'INT',
        'floor_vcell_v': 'FLOAT',
        'cutoff_vcell_v': 'FLOAT',
    },
    'startup_log': {
        'prior_boot_sync_started_at': 'VARCHAR(40)',
        'prior_boot_sync_ended_at': 'VARCHAR(40)',
        'prior_boot_vcell_before_cut_v': 'FLOAT',
        'prior_boot_loss_at': 'VARCHAR(40)',
    },
}


def _columnDefinition(sqlType: str) -> str:
    """Nullable columns get an explicit ``NULL``; the NOT NULL one is left as is."""
    return sqlType if 'NOT NULL' in sqlType else f'{sqlType} NULL'


#: Table -> column -> the full ALTER statement.
ADD_COLUMN_DDL: dict[str, dict[str, str]] = {
    table: {
        column: f'ALTER TABLE {table} ADD COLUMN {column} {_columnDefinition(sqlType)};'
        for column, sqlType in columns.items()
    }
    for table, columns in COLUMNS.items()
}

#: Not wired to any runner -- this framework applies forward only.  Recorded so
#: the non-destructive claim in the docstring is checkable rather than asserted.
REVERT_DDL: dict[str, str] = {
    table: (
        f'ALTER TABLE {table} '
        + ', '.join(f'DROP COLUMN {column}' for column in columns)
        + ';'
    )
    for table, columns in COLUMNS.items()
}


def apply(ctx: RunnerContext) -> None:
    """Add each missing capacity column to ``battery_health_log`` / ``startup_log``.

    Args:
        ctx: Runner context supplying addresses, credentials and the command
            runner.

    Raises:
        MigrationError: If a table is absent or any ALTER fails.
        SchemaProbeError: If a column is still missing after ADD COLUMN
            reported success.
    """
    for table, columns in COLUMNS.items():
        if not serverTableExists(ctx.addrs, ctx.creds, table, ctx.runner):
            raise MigrationError(
                f'{table!r} table missing; v0035 cannot add its ARCH-065 '
                'columns to a non-existent table.',
            )

        existing = probeServerColumns(ctx.addrs, ctx.creds, table, ctx.runner)
        missing = [column for column in columns if column not in existing]
        if not missing:
            continue

        for column in missing:
            res = _runServerSql(
                ctx.addrs, ctx.creds, ADD_COLUMN_DDL[table][column], ctx.runner,
            )
            if res.returncode != 0:
                raise MigrationError(
                    f'add {column!r} to {table!r} failed: '
                    f'{res.stderr.strip() or res.stdout.strip()}',
                )

        after = probeServerColumns(ctx.addrs, ctx.creds, table, ctx.runner)
        stillMissing = [column for column in missing if column not in after]
        if stillMissing:
            raise SchemaProbeError(
                f'{table!r} still lacks {", ".join(stillMissing)} after ADD '
                'COLUMN reported success.',
            )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
