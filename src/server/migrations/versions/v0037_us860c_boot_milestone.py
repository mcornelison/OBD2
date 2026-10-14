################################################################################
# File Name: v0037_us860c_boot_milestone.py
# Purpose/Description: US-860-c (F-157) -- CREATE the ``boot_milestone`` table on
#                      the server so :class:`src.server.db.models.BootMilestone`
#                      has a physical table: each boot's milestone ladder, one
#                      row per (boot, milestone), delta-synced from the Pi on its
#                      integer id.
# Author: Rex (US-860-c)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-10-14    | Rex (US-860-c) | Initial -- probe-guarded CREATE TABLE IF NOT
#               |                | EXISTS, post-condition probe (v0033 pattern).
# ================================================================================
################################################################################
"""Create ``boot_milestone`` (US-860-c).

🔴 **DEPLOY BEFORE THE PI PUSHES IT.**  US-860-d registers the table in the Pi's
``sync_log.PK_COLUMN`` and in the server's ``/sync`` registry; a server without
the table would reject every batch that carries a milestone.  This migration
gives the rows a home first and accepts nothing on its own.

Delta path, not snapshot (Atlas RULED 2026-10-14): the Pi's ``id`` (US-860-b)
lands in ``source_id`` and rows dedup on ``UNIQUE(source_device, source_id)``,
exactly as ``drain_vcell_trajectory`` (v0033).

Idempotency: an ``INFORMATION_SCHEMA`` probe decides.  An existing table is
never touched and no ``CREATE`` is issued for it; otherwise a
``CREATE TABLE IF NOT EXISTS`` runs and the table is probed again, so a CREATE
that reported success without landing fails here rather than when the first
batch arrives.  The table is new, so :data:`REVERT_DDL` restores the previous
shape exactly.

Column shapes mirror the model: ``ts_utc`` DATETIME (the Pi's canonical
ISO-8601 event time, parsed by ``/sync``), ``uptime_s`` DOUBLE (the Pi's REAL is
8-byte; a 4-byte FLOAT drops sub-second digits after a long uptime).
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
    'CREATE_TABLE_DDL',
    'DESCRIPTION',
    'MIGRATION',
    'REVERT_DDL',
    'TABLE_NAME',
    'VERSION',
    'apply',
]

VERSION: str = '0037'

TABLE_NAME: str = 'boot_milestone'

DESCRIPTION: str = (
    'US-860-c boot_milestone -- each boot\'s milestone ladder (one row per boot '
    'and milestone), mirrored from the Pi on the id -> source_id delta path '
    '(F-157)'
)

CREATE_TABLE_DDL: str = (
    f'CREATE TABLE IF NOT EXISTS {TABLE_NAME} ('
    '    id             INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '    source_device  VARCHAR(64) NOT NULL,'
    '    source_id      INT NOT NULL,'
    '    synced_at      DATETIME DEFAULT CURRENT_TIMESTAMP,'
    '    sync_batch_id  INT,'
    '    boot_id        VARCHAR(64) NOT NULL,'
    '    milestone      VARCHAR(32) NOT NULL,'
    '    ts_utc         DATETIME NOT NULL,'
    '    uptime_s       DOUBLE NOT NULL,'
    f'    UNIQUE KEY uq_{TABLE_NAME}_source (source_device, source_id)'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    '  COLLATE=utf8mb4_unicode_ci;'
)

#: Not wired to any runner -- this framework applies forward only.  Recorded so
#: the non-destructive claim in the docstring is checkable rather than asserted.
REVERT_DDL: str = f'DROP TABLE {TABLE_NAME};'


def apply(ctx: RunnerContext) -> None:
    """Create ``boot_milestone`` unless it already exists.

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
