################################################################################
# File Name: v0019_us453_pi_state.py
# Purpose/Description: US-453 registry migration -- creates the pi_state table
#                      on live MariaDB so :class:`src.server.db.models.PiState`
#                      has a matching physical table.  D-7 / F-082 (the Pi
#                      operational-state singleton -- no_new_drives gate --
#                      mirrored from the Pi as irreproducible raw forensic state).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-453) | Initial -- Sprint 55 US-453 (D-7 / F-082).
# ================================================================================
################################################################################

"""Migration 0019: pi_state table (US-453 / D-7 / F-082).

Idempotency contract: the migration probes ``INFORMATION_SCHEMA.TABLES``
first and short-circuits if the table already exists.  Safe to replay on
an already-migrated DB (mirrors v0013_us412_power_log -- the same
raw-forensic-mirror shape).
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


VERSION: str = '0019'
DESCRIPTION: str = (
    'US-453 pi_state -- Pi operational-state singleton (no_new_drives gate), '
    'mirrored server-side as raw forensic state (D-7 / F-082)'
)


# Match the SQLAlchemy PiState model in src/server/db/models.py, which mirrors
# the Pi SCHEMA_PI_STATE.  The server ``id`` autoincrements its own PK; the Pi's
# ``id`` (pinned to 1) maps to source_id.  The (source_device, source_id) UNIQUE
# key is the delta-sync natural key + the ON DUPLICATE KEY upsert anchor, so the
# Pi's no_new_drives flips land as an UPDATE, not a duplicate row.  pi_state
# carries no data_source column (Pi schema parity).
_CREATE_PI_STATE: str = (
    'CREATE TABLE IF NOT EXISTS pi_state ('
    '    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '    source_id       INT NOT NULL,'
    '    source_device   VARCHAR(64) NOT NULL,'
    '    synced_at       DATETIME DEFAULT CURRENT_TIMESTAMP,'
    '    sync_batch_id   INT,'
    '    no_new_drives   INT NOT NULL DEFAULT 0,'
    '    UNIQUE KEY uq_pi_state_source ('
    '        source_device, source_id'
    '    )'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    '  COLLATE=utf8mb4_unicode_ci;'
)


def apply(ctx: RunnerContext) -> None:
    """Create ``pi_state`` if it does not already exist.

    No-op on a DB where the table is already present -- the
    ``CREATE TABLE IF NOT EXISTS`` guard is belt-and-suspenders with the
    INFORMATION_SCHEMA probe (mirrors v0013_us412_power_log).
    """
    # INFORMATION_SCHEMA probe: cheap pre-check so the idempotent re-run
    # path doesn't even issue the CREATE statement on a migrated DB.
    if serverTableExists(ctx.addrs, ctx.creds, 'pi_state', ctx.runner):
        return

    res = _runServerSql(
        ctx.addrs, ctx.creds, _CREATE_PI_STATE, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'create pi_state failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    # Post-condition probe: make sure the CREATE actually landed before the
    # runner records the version.  Shields future operators from silent mysql
    # no-op cases (wrong default DB, filtered replicas).
    if not serverTableExists(ctx.addrs, ctx.creds, 'pi_state', ctx.runner):
        raise SchemaProbeError(
            'pi_state missing after CREATE TABLE ran; '
            'investigate the MariaDB session context',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
