################################################################################
# File Name: v0036_us795a_sync_history_residual_groups.py
# Purpose/Description: US-795(a) -- ADD COLUMN ``residual_drive_rows`` and
#                      ``residual_sensor_rows`` to ``sync_history``: the
#                      drive/sensor split of the residual the CIO ruled the
#                      server must report (2026-10-06).
# Author: Atlas (Architect) -- US-795(a), CIO-directed build
# Creation Date: 2026-10-06
################################################################################
"""Add the residual's drive/sensor split to ``sync_history``.

Mirrors v0028 exactly in shape: two nullable INTEGER columns, no default, no
backfill. A row written before this migration -- or by a Pi that does not send
the split -- reads the split as unknown, never as 0.

NON-DESTRUCTIVE (no rollback machinery in this runner, by design):
:data:`REVERT_DDL` restores the previous shape. Idempotent: each ADD COLUMN is
guarded by its own column probe.
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
    'ADD_RESIDUAL_DRIVE_ROWS_DDL',
    'ADD_RESIDUAL_SENSOR_ROWS_DDL',
    'DESCRIPTION',
    'MIGRATION',
    'RESIDUAL_GROUP_COLUMNS',
    'REVERT_DDL',
    'TABLE_NAME',
    'VERSION',
    'apply',
]

VERSION: str = '0036'

TABLE_NAME: str = 'sync_history'

RESIDUAL_DRIVE_ROWS_COLUMN: str = 'residual_drive_rows'
RESIDUAL_SENSOR_ROWS_COLUMN: str = 'residual_sensor_rows'

#: Both new columns, in the order they are added.
RESIDUAL_GROUP_COLUMNS: tuple[str, ...] = (
    RESIDUAL_DRIVE_ROWS_COLUMN,
    RESIDUAL_SENSOR_ROWS_COLUMN,
)

DESCRIPTION: str = (
    'US-795(a) sync_history.residual_drive_rows + residual_sensor_rows -- the '
    'drive/sensor split of what the car still held. Nullable, no backfill: '
    'NULL means unknown.'
)

ADD_RESIDUAL_DRIVE_ROWS_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} ADD COLUMN {RESIDUAL_DRIVE_ROWS_COLUMN} INTEGER NULL;'
)

ADD_RESIDUAL_SENSOR_ROWS_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} ADD COLUMN {RESIDUAL_SENSOR_ROWS_COLUMN} INTEGER NULL;'
)

#: Not wired to any runner -- forward only. Recorded so the non-destructive
#: claim is checkable rather than asserted.
REVERT_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} '
    f'DROP COLUMN {RESIDUAL_SENSOR_ROWS_COLUMN}, '
    f'DROP COLUMN {RESIDUAL_DRIVE_ROWS_COLUMN};'
)


def apply(ctx: RunnerContext) -> None:
    """Add the two split columns to live ``sync_history``.

    Args:
        ctx: Runner context supplying addresses, credentials and the command
            runner.

    Raises:
        MigrationError: If ``sync_history`` is absent, or an ADD COLUMN fails.
    """
    if not serverTableExists(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner):
        raise MigrationError(
            f'{TABLE_NAME!r} table missing; v0036 cannot add the residual split '
            'columns to a non-existent table.',
        )

    columns = probeServerColumns(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner)

    for columnName, ddl in (
        (RESIDUAL_DRIVE_ROWS_COLUMN, ADD_RESIDUAL_DRIVE_ROWS_DDL),
        (RESIDUAL_SENSOR_ROWS_COLUMN, ADD_RESIDUAL_SENSOR_ROWS_DDL),
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
