################################################################################
# File Name: v0033_us790_drain_vcell_trajectory.py
# Purpose/Description: US-790 (F-138) -- CREATE the ``drain_vcell_trajectory``
#                      table on the server so
#                      :class:`src.server.db.models.DrainVcellTrajectory` has a
#                      physical table: the shutdown drain's VCELL series, one row
#                      per drain poll, the termination reason on the last row.
# Author: Rex (US-790)
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-25    | Rex (US-790) | Initial -- probe-guarded CREATE, post-condition
#               |              | probe.
# ================================================================================
################################################################################
"""Create ``drain_vcell_trajectory`` (US-790).

🔴 **NOT OPTIONAL ON THE SERVER.**  The Pi registers the table in
``sync_log.PK_COLUMN`` and pushes it -- during the shutdown drain itself -- so a
server without it rejects every batch that carries the series.  Deploy this
before the Pi.

Idempotency: an ``INFORMATION_SCHEMA`` probe decides.  An existing table is
never touched and no ``CREATE`` is issued for it; a fresh one is created with a
plain ``CREATE TABLE`` and then probed again, so a CREATE that reported success
without landing fails here rather than when the first batch arrives
(v0013 / v0026 pattern).  The table is new, so :data:`REVERT_DDL` restores the
previous shape exactly.

Column shapes mirror the model: ``ts_utc`` DATETIME (the Pi's canonical
ISO-8601 event time), ``ts_capture`` DOUBLE (monotonic seconds carry more digits
than a 4-byte FLOAT holds), ``vcell_v`` FLOAT NULL (NULL = no reading), and the
named CHECK on ``termination_reason`` from
:data:`src.server.db.models.DRAIN_TERMINATION_REASON_VALUES`.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    serverTableExists,
)
from src.server.db.models import (
    CK_DRAIN_VCELL_TRAJECTORY_TERMINATION_REASON,
    DRAIN_TERMINATION_REASON_VALUES,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'CREATE_TABLE_DDL',
    'DESCRIPTION',
    'MIGRATION',
    'REVERT_DDL',
    'TABLE_NAME',
    'VERSION',
    'apply',
]

VERSION: str = '0033'

TABLE_NAME: str = 'drain_vcell_trajectory'

DESCRIPTION: str = (
    'US-790 drain_vcell_trajectory -- the shutdown drain VCELL series (one row '
    'per drain poll, typed termination_reason on the last row, cell_epoch on '
    'every row), mirrored from the Pi (F-138)'
)

CREATE_TABLE_DDL: str = (
    f'CREATE TABLE {TABLE_NAME} ('
    '    id                  INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '    source_id           INT NOT NULL,'
    '    source_device       VARCHAR(64) NOT NULL,'
    '    synced_at           DATETIME DEFAULT CURRENT_TIMESTAMP,'
    '    sync_batch_id       INT,'
    '    ts_utc              DATETIME NOT NULL,'
    '    ts_capture          DOUBLE NOT NULL,'
    '    seq                 INT NOT NULL,'
    '    vcell_v             FLOAT NULL,'
    '    termination_reason  VARCHAR(32) NULL,'
    '    cell_epoch          VARCHAR(32) NOT NULL,'
    f'    UNIQUE KEY uq_{TABLE_NAME}_source (source_device, source_id),'
    f'    CONSTRAINT {CK_DRAIN_VCELL_TRAJECTORY_TERMINATION_REASON} '
    '        CHECK (termination_reason IN ('
    + ','.join(f"'{value}'" for value in DRAIN_TERMINATION_REASON_VALUES)
    + '))'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    '  COLLATE=utf8mb4_unicode_ci;'
)

#: Not wired to any runner -- this framework applies forward only.  Recorded so
#: the non-destructive claim in the docstring is checkable rather than asserted.
REVERT_DDL: str = f'DROP TABLE {TABLE_NAME};'


def apply(ctx: RunnerContext) -> None:
    """Create ``drain_vcell_trajectory`` unless it already exists.

    Args:
        ctx: Runner context supplying addresses, credentials and the command
            runner.

    Raises:
        MigrationError: If the CREATE fails.
        SchemaProbeError: If the table is still absent after the CREATE
            reported success.
    """
    if serverTableExists(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner):
        return

    res = _runServerSql(ctx.addrs, ctx.creds, CREATE_TABLE_DDL, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'create {TABLE_NAME} failed: {res.stderr.strip() or res.stdout.strip()}',
        )
    if not serverTableExists(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner):
        raise SchemaProbeError(
            f'{TABLE_NAME} missing after CREATE TABLE ran; '
            'investigate the MariaDB session context',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
