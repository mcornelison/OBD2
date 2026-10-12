################################################################################
# File Name: v0030_us809b2_written_at_default.py
# Purpose/Description: US-809-b2 -- put the system-clock DEFAULT on
#                      ``realtime_data.written_at``. The schema fills the write
#                      instant, because at INSERT time now IS the write time.
#                      The column stays NULLABLE (CIO ruling 2026-09-24) so
#                      history keeps an honest absence rather than an invention.
# Author: Ralph (US-809-b2)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-809-b2) | Initial -- one nullable column, no
#               |                   | backfill, no rewrite.
# ================================================================================
################################################################################
"""Put the system-clock DEFAULT on ``realtime_data.written_at``.

**The default was never the problem -- its LOCATION was.**  On the WRITE
column a default of "now" is exactly right: at the instant of INSERT, now IS
the write time.  On the CAPTURE column the same default is a fabrication about
the past, which is why the sibling change removes it there.

🔴 **THE COLUMN STAYS NULLABLE, ruled by the CIO 2026-09-24.**  This story
originally asked for NOT NULL.  That is unsatisfiable on a database that
already holds rows: the Pi carries 405,536 realtime_data rows over five months
whose write time was never recorded and cannot be recovered, and NOT NULL could
only be met by INVENTING one -- the migration clock, or the capture time.  The
second is worse, because it asserts every historical row was written the
instant it was captured, which is the exact false continuity A-double-prime
exists to remove and is indistinguishable afterwards from a genuinely prompt
write.  Sprint 93 constraint 4 governs: a typed absence beats a fabricated
value, every time.

🟢 **Nothing observable is lost.**  The DEFAULT fills every new row and
nothing can write a blank one, because it fires on every INSERT that omits the
column.  What is given up is only the constraint's PROOF that no future row is
blank -- and giving it up is what lets this migration run at all without a
backfill.

⚠️ **Scheduling:** run outside the 03:30 analytics batch, as with v0029.
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
    'SET_WRITTEN_AT_DEFAULT_DDL',
    'DESCRIPTION',
    'MIGRATION',
    'WRITTEN_AT_COLUMN',
    'REVERT_DDL',
    'TABLE_NAME',
    'VERSION',
    'apply',
]

VERSION: str = '0030'

TABLE_NAME: str = 'realtime_data'

WRITTEN_AT_COLUMN: str = 'written_at'

DESCRIPTION: str = (
    'US-809-b2 realtime_data.written_at DEFAULT CURRENT_TIMESTAMP -- the schema '
    'supplies the write instant. Stays NULLABLE (CIO 2026-09-24): no backfill, '
    'so rows predating the column keep an honest absence.'
)

# Mirrors the ``RealtimeData.written_at`` ORM declaration:
#  * DATETIME     -- matches DateTime on the model
#  * NULL allowed -- matches Mapped[datetime | None]
#  * NO DEFAULT   -- b2 adds the system-clock default; here absence is honest.
SET_WRITTEN_AT_DEFAULT_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} MODIFY COLUMN {WRITTEN_AT_COLUMN} '
    'DATETIME NULL DEFAULT CURRENT_TIMESTAMP;'
)

#: Not wired to any runner -- this framework applies forward only. Recorded so
#: the non-destructive claim in the docstring is checkable rather than asserted.
REVERT_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} MODIFY COLUMN {WRITTEN_AT_COLUMN} DATETIME NULL;'
)


def apply(ctx: RunnerContext) -> None:
    """Put the system-clock default on live ``realtime_data.written_at``.

    MODIFY is idempotent in MariaDB -- re-applying sets the same default.
    No row is read, written or backfilled: a row that predates the column has
    no known write time, and keeps saying so.

    Args:
        ctx: Runner context supplying addresses, credentials and the command
            runner.

    Raises:
        MigrationError: If the table or column is absent, or the MODIFY fails.
    """
    if not serverTableExists(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner):
        raise MigrationError(
            f'{TABLE_NAME!r} table missing; v0030 cannot set a default on a '
            'column of a non-existent table.',
        )

    columns = probeServerColumns(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner)

    if WRITTEN_AT_COLUMN not in columns:
        raise MigrationError(
            f'{WRITTEN_AT_COLUMN!r} missing from {TABLE_NAME!r}; v0029 must '
            'run before v0030 can put a default on it.',
        )

    res = _runServerSql(
        ctx.addrs, ctx.creds, SET_WRITTEN_AT_DEFAULT_DDL, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'set default on {WRITTEN_AT_COLUMN!r} in {TABLE_NAME!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
