################################################################################
# File Name: v0013_us412_power_log.py
# Purpose/Description: US-412 registry migration -- creates the power_log table
#                      on live MariaDB so :class:`src.server.db.models.PowerLog`
#                      has a matching physical table.  F-101 (one row per
#                      power-source / shutdown-stage transition), mirrored from
#                      the Pi so power/boot history is queryable server-side.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-412) | Initial -- Sprint 50 US-412 (F-101).
# ================================================================================
################################################################################

"""Migration 0013: power_log table (US-412 / F-101).

Idempotency contract: the migration probes ``INFORMATION_SCHEMA.TABLES``
first and short-circuits if the table already exists.  Safe to replay on
an already-migrated DB -- the MigrationRunner's schema_migrations
bookkeeping records the version on first success and skips subsequent
runs, but this extra guard covers the out-of-band-create case (mirrors
v0002_us217_battery_health_log).
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    serverTableExists,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = ['MIGRATION', 'VERSION', 'DESCRIPTION', 'apply']


VERSION: str = '0013'
DESCRIPTION: str = (
    'US-412 power_log -- Pi power-event log (one row per power-source / '
    'shutdown-stage transition), mirrored server-side (F-101)'
)


# Match the SQLAlchemy PowerLog model in src/server/db/models.py, which mirrors
# the Pi SCHEMA_POWER_LOG.  ``timestamp`` is backticked (it collides with the
# MariaDB TIMESTAMP type keyword otherwise).  MariaDB DATETIME for the timestamp
# column: server-side normalization already lands canonical ISO-8601 UTC on
# inbound Pi rows.  power_log carries no data_source column (Pi schema parity).
_CREATE_POWER_LOG: str = (
    'CREATE TABLE IF NOT EXISTS power_log ('
    '    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '    source_id       INT NOT NULL,'
    '    source_device   VARCHAR(64) NOT NULL,'
    '    synced_at       DATETIME DEFAULT CURRENT_TIMESTAMP,'
    '    sync_batch_id   INT,'
    '    `timestamp`     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,'
    '    event_type      VARCHAR(32) NOT NULL,'
    '    power_source    VARCHAR(32) NOT NULL,'
    '    on_ac_power     INT NOT NULL DEFAULT 1,'
    '    vcell           FLOAT,'
    '    UNIQUE KEY uq_power_log_source ('
    '        source_device, source_id'
    '    )'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    '  COLLATE=utf8mb4_unicode_ci;'
)


def apply(ctx: RunnerContext) -> None:
    """Create ``power_log`` if it does not already exist.

    No-op on a DB where the table is already present -- the
    ``CREATE TABLE IF NOT EXISTS`` guard is belt-and-suspenders with the
    INFORMATION_SCHEMA probe.
    """
    # INFORMATION_SCHEMA probe: cheap pre-check so the idempotent re-run
    # path doesn't even issue the CREATE statement on a migrated DB.
    if serverTableExists(ctx.addrs, ctx.creds, 'power_log', ctx.runner):
        return

    res = _runServerSql(
        ctx.addrs, ctx.creds, _CREATE_POWER_LOG, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'create power_log failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    # Post-condition probe: make sure the CREATE actually landed before the
    # runner records the version.  Shields future operators from silent mysql
    # no-op cases (wrong default DB, filtered replicas).
    if not serverTableExists(ctx.addrs, ctx.creds, 'power_log', ctx.runner):
        raise SchemaProbeError(
            'power_log missing after CREATE TABLE ran; '
            'investigate the MariaDB session context',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
