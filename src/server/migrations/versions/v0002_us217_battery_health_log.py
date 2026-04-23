################################################################################
# File Name: v0002_us217_battery_health_log.py
# Purpose/Description: US-213 registry migration -- creates the
#                      battery_health_log table on live MariaDB so
#                      :class:`src.server.db.models.BatteryHealthLog` has a
#                      matching physical table.  Spool Session 6 Story 3
#                      design (US-217) -- one row per UPS drain event.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex          | Initial -- Sprint 16 US-217.
# ================================================================================
################################################################################

"""Migration 0002: battery_health_log table (US-217).

Idempotency contract: the migration probes ``INFORMATION_SCHEMA.TABLES``
first and short-circuits if the table already exists.  Safe to replay
on an already-migrated DB -- the MigrationRunner's schema_migrations
bookkeeping records the version on first success and skips subsequent
runs, but this extra guard covers the case where the table was created
out-of-band before the registry row landed (e.g. the catch-up path the
v0001 wrapper uses for US-209).
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


VERSION: str = '0002'
DESCRIPTION: str = (
    'US-217 battery_health_log -- per-drain-event UPS health table '
    '(Spool Session 6 Story 3)'
)


# Match the SQLAlchemy BatteryHealthLog model in src/server/db/models.py.
# MariaDB DDL: DATETIME for timestamps (server-side normalization handles
# the canonical ISO-8601 UTC shape on inbound Pi rows).
_CREATE_BATTERY_HEALTH_LOG: str = (
    'CREATE TABLE IF NOT EXISTS battery_health_log ('
    '    id                INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '    source_id         INT NOT NULL,'
    '    source_device     VARCHAR(64) NOT NULL,'
    '    synced_at         DATETIME DEFAULT CURRENT_TIMESTAMP,'
    '    sync_batch_id     INT,'
    '    start_timestamp   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,'
    '    end_timestamp     DATETIME,'
    '    start_soc         FLOAT NOT NULL,'
    '    end_soc           FLOAT,'
    '    runtime_seconds   INT,'
    '    ambient_temp_c    FLOAT,'
    '    load_class        VARCHAR(16) NOT NULL DEFAULT "production",'
    '    notes             TEXT,'
    '    data_source       VARCHAR(16) DEFAULT "real",'
    '    UNIQUE KEY uq_battery_health_log_source ('
    '        source_device, source_id'
    '    )'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    '  COLLATE=utf8mb4_unicode_ci;'
)


def apply(ctx: RunnerContext) -> None:
    """Create ``battery_health_log`` if it does not already exist.

    No-op on a DB where the table is already present -- the
    ``CREATE TABLE IF NOT EXISTS`` guard is belt-and-suspenders with
    the INFORMATION_SCHEMA probe.
    """
    # INFORMATION_SCHEMA probe: cheap pre-check so the idempotent re-run
    # path doesn't even issue the CREATE statement on a migrated DB.
    if serverTableExists(ctx.addrs, ctx.creds, 'battery_health_log', ctx.runner):
        return

    res = _runServerSql(
        ctx.addrs, ctx.creds, _CREATE_BATTERY_HEALTH_LOG, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'create battery_health_log failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    # Post-condition probe: make sure the CREATE actually landed before
    # the runner records the version.  Shields future operators from
    # silent mysql no-op cases (wrong default DB, filtered replicas).
    if not serverTableExists(
        ctx.addrs, ctx.creds, 'battery_health_log', ctx.runner,
    ):
        raise SchemaProbeError(
            'battery_health_log missing after CREATE TABLE ran; '
            'investigate the MariaDB session context',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
