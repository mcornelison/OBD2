################################################################################
# File Name: v0031_us810_edr_gyro_rate_bias.py
# Purpose/Description: US-810 (F-135) -- ADD the five gyro RATE bias columns to
#                      ``edr_imu_derived`` so the Pi's learned bias crosses the
#                      tier boundary. Without them the server model lacks
#                      columns the Pi sends, and US-689's unknown-column guard
#                      STOPS edr_imu_derived sync.
# Author: Rex (US-810)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-24    | Rex (US-810) | Initial -- five nullable columns, probe-guarded,
#               |              | no backfill, no rewrite.
# ================================================================================
################################################################################
"""Add PitchFusion's gyro RATE bias to ``edr_imu_derived`` (US-810).

The columns carry the gyro RATE bias (rad/s, roll/pitch/yaw) that PitchFusion
learns at ZUPT stops and subtracts before integrating -- NOT ``bias_rad``, which
is the mount-tilt ANGLE.  The rate columns are NULL until a stop is accepted in
a run; ``gyro_bias_rejected_stops`` distinguishes "never learned" from "every
stop rejected as an A-34 latch", which both leave the rates NULL.

🔴 **NOT OPTIONAL ON THE SERVER.**  ``src/server/api/sync.py`` RAISES on any Pi
column the server model lacks (US-689), so the Pi-side ADD COLUMN
(``ensureEdrImuDerivedGyroRateBiasColumns``) without this migration would stop
``edr_imu_derived`` sync on the first batch.

⚠️ **Why a probe per column rather than trusting the fresh path.**  v0027
generates ``edr_imu_derived`` from the MUTABLE ``EDR_COLUMNS`` contract, so on a
fresh database it already creates these five columns and this migration must be
a no-op there; on the live server (v0027 applied before US-810) it adds them.
Each column is probed, so a partial earlier run is also completed rather than
failing on a duplicate.

Each ADD carries ``AFTER`` so an upgraded table has the same column order as a
fresh one (contract columns, then ``synced_at`` / ``sync_batch_id``).

NON-DESTRUCTIVE: five nullable columns, no backfill, no row rewritten, so
:data:`REVERT_DDL` restores the previous shape exactly.  Existing rows read NULL
-- their bias was never recorded, and that is the truth about them.
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
    'ADD_COLUMN_DDL',
    'DESCRIPTION',
    'GYRO_RATE_BIAS_COLUMNS',
    'MIGRATION',
    'REVERT_DDL',
    'TABLE_NAME',
    'VERSION',
    'apply',
]

VERSION: str = '0031'

TABLE_NAME: str = 'edr_imu_derived'

DESCRIPTION: str = (
    'US-810 edr_imu_derived gyro RATE bias -- add gyro_bias_roll/pitch/yaw_rad_s, '
    'gyro_bias_stops and gyro_bias_rejected_stops. Nullable, no backfill: NULL '
    'rates mean the bias was not learned, never a measured zero.'
)

#: (column, MariaDB type, the column it follows).  Types mirror the
#: ``EdrImuDerived`` ORM and the server_ddl KIND_TYPES map (float -> FLOAT,
#: int -> INT).  Written as literals, not generated from EDR_COLUMNS, so this
#: migration records what it does even if the contract later changes.
GYRO_RATE_BIAS_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ('gyro_bias_roll_rad_s', 'FLOAT', 'schema_version'),
    ('gyro_bias_pitch_rad_s', 'FLOAT', 'gyro_bias_roll_rad_s'),
    ('gyro_bias_yaw_rad_s', 'FLOAT', 'gyro_bias_pitch_rad_s'),
    ('gyro_bias_stops', 'INT', 'gyro_bias_yaw_rad_s'),
    ('gyro_bias_rejected_stops', 'INT', 'gyro_bias_stops'),
)

#: One statement per column, keyed by column name.
ADD_COLUMN_DDL: dict[str, str] = {
    name: f'ALTER TABLE {TABLE_NAME} ADD COLUMN {name} {sqlType} NULL AFTER {after};'
    for name, sqlType, after in GYRO_RATE_BIAS_COLUMNS
}

#: Not wired to any runner -- this framework applies forward only. Recorded so
#: the non-destructive claim in the docstring is checkable rather than asserted.
REVERT_DDL: str = (
    f'ALTER TABLE {TABLE_NAME} '
    + ', '.join(f'DROP COLUMN {name}' for name, _, _ in GYRO_RATE_BIAS_COLUMNS)
    + ';'
)


def apply(ctx: RunnerContext) -> None:
    """Add every missing gyro RATE bias column to live ``edr_imu_derived``.

    Guarded by a column probe, so re-applying is a no-op.  After adding, the
    columns are probed again: an ALTER that reported success without the column
    appearing is a failure, not a clean migration.

    Args:
        ctx: Runner context supplying addresses, credentials and the command
            runner.

    Raises:
        MigrationError: If ``edr_imu_derived`` is absent, an ADD COLUMN fails, or
            a column is still missing afterwards.
    """
    if not serverTableExists(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner):
        raise MigrationError(
            f'{TABLE_NAME!r} table missing; v0031 cannot add the gyro rate bias '
            'columns to a non-existent table (v0027 creates it).',
        )

    columns = probeServerColumns(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner)
    missing = [name for name, _, _ in GYRO_RATE_BIAS_COLUMNS if name not in columns]
    if not missing:
        return

    for name in missing:
        res = _runServerSql(ctx.addrs, ctx.creds, ADD_COLUMN_DDL[name], ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'add {name!r} to {TABLE_NAME!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    after = probeServerColumns(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner)
    stillMissing = [name for name in missing if name not in after]
    if stillMissing:
        raise MigrationError(
            f'{TABLE_NAME!r} still lacks {stillMissing} after ADD COLUMN reported '
            'success.',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
