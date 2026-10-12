################################################################################
# File Name: v0014_us417_startup_log.py
# Purpose/Description: US-417 registry migration -- creates the startup_log table
#                      on live MariaDB so :class:`src.server.db.models.StartupLog`
#                      has a matching physical table.  F-101 (one row per boot,
#                      mirrored from the Pi so boot history is queryable
#                      server-side).  startup_log syncs via the natural-key
#                      SNAPSHOT path (US-416), so its dedup anchor is
#                      UNIQUE(source_device, boot_id) -- NOT the integer
#                      (source_device, source_id) key the delta tables use (there
#                      is no source_id column; boot_id is a natural TEXT key).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-417) | Initial -- Sprint 51 US-417 (F-101, closes
#                               BL-013).
# ================================================================================
################################################################################

"""Migration 0014: startup_log table (US-417 / F-101, closes BL-013).

Idempotency contract: the migration probes ``INFORMATION_SCHEMA.TABLES``
first and short-circuits if the table already exists.  Safe to replay on
an already-migrated DB -- the MigrationRunner's schema_migrations
bookkeeping records the version on first success and skips subsequent
runs, but this extra guard covers the out-of-band-create case (mirrors
v0013_us412_power_log).

Post-deploy verification (the US-417 acceptance step, run by the deployer):
``INFORMATION_SCHEMA`` confirms the table + the UNIQUE(source_device, boot_id)
key exist on the live MariaDB before boot history is expected to sync.
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


VERSION: str = '0014'
DESCRIPTION: str = (
    'US-417 startup_log -- Pi boot log (one row per boot), mirrored server-side '
    'via the natural-key snapshot path with UNIQUE(source_device, boot_id) '
    '(F-101, closes BL-013)'
)


# Match the SQLAlchemy StartupLog model in src/server/db/models.py, which mirrors
# the Pi SCHEMA_STARTUP_LOG.  No source_id column -- startup_log dedups on the
# NATURAL key (source_device, boot_id), not the integer id->source_id mapping the
# delta tables use.  Timestamp-ish columns are VARCHAR (canonical ISO-8601 TEXT,
# matching the Pi's storage) so journal timestamps that may be NULL / non-DATETIME
# land verbatim.
_CREATE_STARTUP_LOG: str = (
    'CREATE TABLE IF NOT EXISTS startup_log ('
    '    id                          INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '    source_device               VARCHAR(64) NOT NULL,'
    '    synced_at                   DATETIME DEFAULT CURRENT_TIMESTAMP,'
    '    sync_batch_id               INT,'
    '    boot_id                     VARCHAR(64) NOT NULL,'
    '    prior_boot_clean            INT,'
    '    prior_last_entry_ts         VARCHAR(40),'
    '    current_boot_first_entry_ts VARCHAR(40),'
    '    prior_boot_last_stage       VARCHAR(64),'
    '    prior_boot_reason           VARCHAR(64),'
    '    recorded_at                 VARCHAR(40),'
    '    UNIQUE KEY uq_startup_log_boot ('
    '        source_device, boot_id'
    '    )'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    '  COLLATE=utf8mb4_unicode_ci;'
)


def apply(ctx: RunnerContext) -> None:
    """Create ``startup_log`` if it does not already exist.

    No-op on a DB where the table is already present -- the
    ``CREATE TABLE IF NOT EXISTS`` guard is belt-and-suspenders with the
    INFORMATION_SCHEMA probe.
    """
    # INFORMATION_SCHEMA probe: cheap pre-check so the idempotent re-run
    # path doesn't even issue the CREATE statement on a migrated DB.
    if serverTableExists(ctx.addrs, ctx.creds, 'startup_log', ctx.runner):
        return

    res = _runServerSql(
        ctx.addrs, ctx.creds, _CREATE_STARTUP_LOG, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'create startup_log failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    # Post-condition probe: make sure the CREATE actually landed before the
    # runner records the version.  Shields future operators from silent mysql
    # no-op cases (wrong default DB, filtered replicas).
    if not serverTableExists(ctx.addrs, ctx.creds, 'startup_log', ctx.runner):
        raise SchemaProbeError(
            'startup_log missing after CREATE TABLE ran; '
            'investigate the MariaDB session context',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
