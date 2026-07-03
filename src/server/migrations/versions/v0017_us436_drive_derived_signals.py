################################################################################
# File Name: v0017_us436_drive_derived_signals.py
# Purpose/Description: US-436 registry migration -- creates the
#                      drive_derived_signals table on live MariaDB so
#                      :class:`src.server.db.models.DriveDerivedSignal` has a
#                      matching physical table.  F-106 per-drive derived motion
#                      signals (acceleration + estimated distance), one row per
#                      drive keyed on drive_summary.id (ON DELETE CASCADE).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-02    | Rex (US-436) | Initial -- Sprint 53 US-436 (F-106).
# ================================================================================
################################################################################

"""Migration 0017: drive_derived_signals table (US-436 / F-106).

Idempotency contract (mirrors v0013_us412_power_log): the migration probes
``INFORMATION_SCHEMA.TABLES`` first and short-circuits if the table already
exists.  Safe to replay on an already-migrated DB -- the MigrationRunner's
schema_migrations bookkeeping records the version on first success and skips
subsequent runs; this INFORMATION_SCHEMA guard plus the ``IF NOT EXISTS``
clause cover the out-of-band-create case.

The FK to ``drive_summary(id)`` with ``ON DELETE CASCADE`` means deleting a
drive_summary row tears down its derived-signals child automatically (same
lifecycle as drive_statistics).
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


VERSION: str = '0017'
DESCRIPTION: str = (
    'US-436 drive_derived_signals -- per-drive derived motion signals '
    '(acceleration + estimated distance) from the SPEED stream, one row per '
    'drive keyed on drive_summary.id ON DELETE CASCADE (F-106)'
)


DRIVE_DERIVED_SIGNALS_TABLE: str = 'drive_derived_signals'

# Match the SQLAlchemy DriveDerivedSignal model in src/server/db/models.py.
# FLOAT for the derived magnitudes (distance km, accel m/s^2); peak_* are NULL
# when a drive had no valid segment.  Unit columns default to the stored units
# (honest-instrument).  computed_at defaults to CURRENT_TIMESTAMP; the ORM's
# onupdate=func.now() advances it on idempotent re-write.
_CREATE_DRIVE_DERIVED_SIGNALS: str = (
    f'CREATE TABLE IF NOT EXISTS {DRIVE_DERIVED_SIGNALS_TABLE} ('
    '    summary_id            INT NOT NULL PRIMARY KEY,'
    '    estimated_distance_km FLOAT,'
    '    peak_acceleration_ms2 FLOAT,'
    '    peak_deceleration_ms2 FLOAT,'
    '    sample_count          INT NOT NULL,'
    '    segment_count         INT NOT NULL,'
    '    gap_skipped_count     INT NOT NULL,'
    "    speed_unit            VARCHAR(16) NOT NULL DEFAULT 'km/h',"
    "    distance_unit         VARCHAR(16) NOT NULL DEFAULT 'km',"
    "    accel_unit            VARCHAR(16) NOT NULL DEFAULT 'm/s^2',"
    '    computed_at           DATETIME DEFAULT CURRENT_TIMESTAMP,'
    '    CONSTRAINT fk_drive_derived_signals_summary'
    '        FOREIGN KEY (summary_id) REFERENCES drive_summary(id)'
    '        ON DELETE CASCADE'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    '  COLLATE=utf8mb4_unicode_ci;'
)


def apply(ctx: RunnerContext) -> None:
    """Create ``drive_derived_signals`` if it does not already exist.

    No-op on a DB where the table is already present -- the
    ``CREATE TABLE IF NOT EXISTS`` guard is belt-and-suspenders with the
    INFORMATION_SCHEMA probe.
    """
    if serverTableExists(
        ctx.addrs, ctx.creds, DRIVE_DERIVED_SIGNALS_TABLE, ctx.runner,
    ):
        return

    res = _runServerSql(
        ctx.addrs, ctx.creds, _CREATE_DRIVE_DERIVED_SIGNALS, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'create {DRIVE_DERIVED_SIGNALS_TABLE} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    # Post-condition probe: make sure the CREATE actually landed before the
    # runner records the version (shields against silent mysql no-op cases:
    # wrong default DB, filtered replicas).
    if not serverTableExists(
        ctx.addrs, ctx.creds, DRIVE_DERIVED_SIGNALS_TABLE, ctx.runner,
    ):
        raise SchemaProbeError(
            f'{DRIVE_DERIVED_SIGNALS_TABLE} missing after CREATE TABLE ran; '
            'investigate the MariaDB session context',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
