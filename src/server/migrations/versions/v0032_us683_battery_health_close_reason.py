################################################################################
# File Name: v0032_us683_battery_health_close_reason.py
# Purpose/Description: US-683 (F-138) -- ADD the typed ``close_reason`` column to
#                      ``battery_health_log`` with its CHECK, and BACKFILL it on
#                      the server's existing closed rows.  The column says how a
#                      drain row was closed (clean / reaped_uncheckpointed /
#                      reaped_checkpointed) so a checkpointed reap's
#                      understatement is read from a type, not from prose.
# Author: Rex (US-683)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-24    | Rex (US-683) | Initial -- nullable column, named CHECK, backfill,
#               |              | every step probe-guarded or self-limiting.
# ================================================================================
################################################################################
"""Add and backfill ``battery_health_log.close_reason`` (US-683).

🔴 **NOT OPTIONAL ON THE SERVER.**  ``src/server/api/sync.py`` RAISES on any Pi
column the server model lacks (US-689), so the Pi-side ADD COLUMN
(``ensureBatteryHealthLogCloseReasonColumn``) without this migration would stop
``battery_health_log`` sync on the first batch.

⚠️ **Why the backfill lives HERE and is not synced up.**  ``sync.py``'s
``_PRESERVE_ON_UPDATE`` holds ``notes`` for every table, so a Pi-side ``notes``
update never reaches the server: a row the server first received OPEN keeps its
open-time ``notes`` and may lack the reap suffix the backfill looks for.  This
migration therefore classifies the server's rows from what the server holds.
It is a floor, not the last word: the Pi's own backfill fires the US-315
modified_at trigger, and ``close_reason`` is NOT in the preserve set, so each
backfilled Pi row re-syncs and overwrites the server value with the Pi's.

The derivation is the Pi's, verbatim (``src/pi/power/battery_health.py``
``_BACKFILL_CLOSE_REASON_SQL``): the reap suffix in ``notes`` means
``reaped_checkpointed``; a close with ``runtime_seconds`` AND ``end_vcell_v``
both NULL means ``reaped_uncheckpointed``; any other closed row is ``clean``.
Open rows (``end_timestamp IS NULL``) are never touched.  The suffix is written
here as a literal -- the server does not import Pi modules -- and a test pins it
to the Pi constant.

Idempotency: the column and the CHECK are each added only when their probe
says they are missing; the backfill only fills ``close_reason IS NULL`` on
closed rows, so a re-run changes nothing.  The column is nullable and no other
column is written, so :data:`REVERT_DDL` restores the previous shape exactly.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    probeServerColumns,
    serverTableExists,
)
from src.server.db.models import (
    BATTERY_HEALTH_CLOSE_REASON_VALUES,
    CK_BATTERY_HEALTH_LOG_CLOSE_REASON,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'ADD_CHECK_DDL',
    'ADD_COLUMN_DDL',
    'BACKFILL_SQL',
    'CHECK_CONSTRAINT_NAME',
    'COLUMN_NAME',
    'DESCRIPTION',
    'MIGRATION',
    'REAP_CHECKPOINTED_NOTE_SUFFIX',
    'REVERT_DDL',
    'TABLE_NAME',
    'VERSION',
    'apply',
]

VERSION: str = '0032'

TABLE_NAME: str = 'battery_health_log'
COLUMN_NAME: str = 'close_reason'
CHECK_CONSTRAINT_NAME: str = CK_BATTERY_HEALTH_LOG_CLOSE_REASON

DESCRIPTION: str = (
    'US-683 battery_health_log.close_reason -- typed close discriminator '
    '(clean / reaped_uncheckpointed / reaped_checkpointed), CHECK-constrained, '
    'backfilled on closed rows. NULL exactly while a row is open.'
)

#: The Pi's reap suffix (src/pi/power/battery_health.py
#: REAP_CHECKPOINTED_NOTE_SUFFIX), copied as a literal.  Contains no quote.
REAP_CHECKPOINTED_NOTE_SUFFIX: str = (
    ' | INTERRUPTED (US-605): closed by the boot reaper at the last 30 s '
    'checkpoint -- depth and runtime are CHECKPOINTED values and both '
    'UNDERSTATE the real drain by up to one checkpoint interval'
)

_CLEAN, _REAPED_UNCHECKPOINTED, _REAPED_CHECKPOINTED = BATTERY_HEALTH_CLOSE_REASON_VALUES

#: VARCHAR(32) mirrors ``String(32)`` on the model.  AFTER data_source keeps an
#: upgraded table in the model's column order.
ADD_COLUMN_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} ADD COLUMN {COLUMN_NAME} VARCHAR(32) NULL '
    'AFTER data_source;'
)

ADD_CHECK_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} ADD CONSTRAINT {CHECK_CONSTRAINT_NAME} '
    f'CHECK ({COLUMN_NAME} IN ('
    + ','.join(f"'{value}'" for value in BATTERY_HEALTH_CLOSE_REASON_VALUES)
    + '));'
)

#: Portable across MariaDB and SQLite (INSTR / COALESCE / CASE), so the tests
#: run the exact statement the server runs.
BACKFILL_SQL: str = (
    f'UPDATE {TABLE_NAME} SET {COLUMN_NAME} = CASE '
    f"WHEN INSTR(COALESCE(notes, ''), '{REAP_CHECKPOINTED_NOTE_SUFFIX}') > 0 "
    f"THEN '{_REAPED_CHECKPOINTED}' "
    'WHEN runtime_seconds IS NULL AND end_vcell_v IS NULL '
    f"THEN '{_REAPED_UNCHECKPOINTED}' "
    f"ELSE '{_CLEAN}' END "
    f'WHERE end_timestamp IS NOT NULL AND {COLUMN_NAME} IS NULL;'
)

#: Not wired to any runner -- this framework applies forward only.  Recorded so
#: the non-destructive claim in the docstring is checkable rather than asserted.
REVERT_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} DROP CONSTRAINT {CHECK_CONSTRAINT_NAME}, '
    f'DROP COLUMN {COLUMN_NAME};'
)


def _checkExists(ctx: RunnerContext) -> bool:
    """Return True when the named CHECK is already on the server."""
    probeSql = (
        'SELECT COUNT(*) FROM information_schema.CHECK_CONSTRAINTS '
        f"WHERE CONSTRAINT_SCHEMA='{ctx.creds.dbName}' "
        f"AND CONSTRAINT_NAME='{CHECK_CONSTRAINT_NAME}';"
    )
    res = _runServerSql(ctx.addrs, ctx.creds, probeSql, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'CHECK constraint probe failed: {res.stderr.strip() or res.stdout.strip()}',
        )
    try:
        return int(res.stdout.strip().split()[0]) > 0
    except (ValueError, IndexError) as exc:
        raise SchemaProbeError(
            f'CHECK constraint probe returned {res.stdout!r}, not a count',
        ) from exc


def apply(ctx: RunnerContext) -> None:
    """Add, constrain and backfill ``battery_health_log.close_reason``.

    Args:
        ctx: Runner context supplying addresses, credentials and the command
            runner.

    Raises:
        MigrationError: If the table is absent, or any ALTER or the backfill
            fails.
        SchemaProbeError: If a probe cannot be read, or the column is still
            missing after ADD COLUMN reported success.
    """
    if not serverTableExists(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner):
        raise MigrationError(
            f'{TABLE_NAME!r} table missing; v0032 cannot add {COLUMN_NAME!r} to a '
            'non-existent table (v0002 creates it).',
        )

    columns = probeServerColumns(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner)
    if COLUMN_NAME not in columns:
        res = _runServerSql(ctx.addrs, ctx.creds, ADD_COLUMN_DDL, ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'add {COLUMN_NAME!r} to {TABLE_NAME!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )
        after = probeServerColumns(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner)
        if COLUMN_NAME not in after:
            raise SchemaProbeError(
                f'{TABLE_NAME!r} still lacks {COLUMN_NAME!r} after ADD COLUMN '
                'reported success.',
            )

    if not _checkExists(ctx):
        res = _runServerSql(ctx.addrs, ctx.creds, ADD_CHECK_DDL, ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'add CHECK {CHECK_CONSTRAINT_NAME!r} on {TABLE_NAME!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    res = _runServerSql(ctx.addrs, ctx.creds, BACKFILL_SQL, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'backfill of {TABLE_NAME}.{COLUMN_NAME} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
