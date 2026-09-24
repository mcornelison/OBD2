################################################################################
# File Name: v0029_us809b1_realtime_written_at.py
# Purpose/Description: US-809-b1 -- ADD COLUMN ``written_at`` to
#                      ``realtime_data`` so the Pi's WRITE instant crosses the
#                      tier boundary alongside the capture instant. Without it
#                      the server model lacks a column the Pi sends, and
#                      US-689's unknown-column guard STOPS realtime_data sync.
# Author: Ralph (US-809-b1)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-809-b1) | Initial -- one nullable column, no
#               |                   | backfill, no rewrite.
# ================================================================================
################################################################################
"""Add the Pi's write instant to ``realtime_data``.

``timestamp`` holds the EVENT instant -- when the reading was taken (US-809-a,
spec A-double-prime).  This column holds when the row reached storage on the
Pi.  Under normal load the two differ by milliseconds and nothing shows; the
difference appears exactly when a queue has backed up, which is the case the
record most needs to describe honestly.  A-double-prime ADDS this requirement
without removing anything: two honest columns beat one ambiguous one.

🔴 **THIS COLUMN IS NOT OPTIONAL ON THE SERVER.**  ``src/server/api/sync.py``
RAISES ValueError on any Pi column the server model lacks -- US-689 made it do
that on purpose, because the previous behaviour was a SILENT DROP (SQLAlchemy's
executemany ignores surplus keys, so the row inserted and the value vanished).
``realtime_data`` takes that delta path and is the highest-volume table on the
car, so landing the column on the Pi alone would stop its sync on the FIRST
batch.

⚠️ **NULLABLE, AND DELIBERATELY NOT BACKFILLED.**  Rows written before this
column read NULL -- a typed absence, the truth about them.  Backfilling from
``timestamp`` was the tempting option and is the worst available one: it would
assert that every historical row was written the instant it was captured,
which is precisely the false continuity A-double-prime exists to remove, and
once landed it would be indistinguishable from a genuinely prompt write.

⚠️ **On "reversible".**  As with v0028, this runner ships no down-migration
machinery by design.  What is offered instead is that the migration is
**NON-DESTRUCTIVE**: one nullable column, no backfill, no row rewritten, so
:data:`REVERT_DDL` restores the previous shape exactly.

⚠️ **Scheduling, per the story:** run this outside the 03:30 analytics batch,
and coordinate with the collector's DB lock on the Pi side.

US-809-b2 makes the column NOT NULL with the system-clock DEFAULT; this
migration deliberately stops short of that.
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
    'ADD_WRITTEN_AT_DDL',
    'DESCRIPTION',
    'MIGRATION',
    'WRITTEN_AT_COLUMN',
    'REVERT_DDL',
    'TABLE_NAME',
    'VERSION',
    'apply',
]

VERSION: str = '0029'

TABLE_NAME: str = 'realtime_data'

WRITTEN_AT_COLUMN: str = 'written_at'

DESCRIPTION: str = (
    'US-809-b1 realtime_data.written_at -- carry the Pi WRITE instant across '
    'the tier boundary beside the capture instant. Nullable, no backfill: NULL '
    'means the row predates the column, never that it was written at capture.'
)

# Mirrors the ``RealtimeData.written_at`` ORM declaration:
#  * DATETIME     -- matches DateTime on the model
#  * NULL allowed -- matches Mapped[datetime | None]
#  * NO DEFAULT   -- b2 adds the system-clock default; here absence is honest.
ADD_WRITTEN_AT_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} ADD COLUMN {WRITTEN_AT_COLUMN} DATETIME NULL;'
)

#: Not wired to any runner -- this framework applies forward only. Recorded so
#: the non-destructive claim in the docstring is checkable rather than asserted.
REVERT_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} DROP COLUMN {WRITTEN_AT_COLUMN};'
)


def apply(ctx: RunnerContext) -> None:
    """Add the write-time column to live ``realtime_data``.

    Guarded by a column probe, so re-applying is a no-op rather than an error.
    No row is read, written or backfilled: a row that predates the column has
    no known write time, and says so.

    Args:
        ctx: Runner context supplying addresses, credentials and the command
            runner.

    Raises:
        MigrationError: If ``realtime_data`` is absent, or the ADD COLUMN fails.
    """
    if not serverTableExists(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner):
        raise MigrationError(
            f'{TABLE_NAME!r} table missing; v0029 cannot add the write-time '
            'column to a non-existent table.',
        )

    columns = probeServerColumns(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner)

    if WRITTEN_AT_COLUMN in columns:
        return

    res = _runServerSql(ctx.addrs, ctx.creds, ADD_WRITTEN_AT_DDL, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'add {WRITTEN_AT_COLUMN!r} to {TABLE_NAME!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
