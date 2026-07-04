################################################################################
# File Name: v0020_us454_o2_name_normalization.py
# Purpose/Description: US-454 O2 sensor name normalization (D-3 / F-082) --
#                      forward-only DATA migration that re-maps the one divergent
#                      O2 parameter_name label ``O2_BANK1_SENSOR2_V`` to the
#                      canonical ``O2_B1S2`` (the decoder registry's own
#                      obdCommand + the O2_B{bank}S{sensor} convention already
#                      used by O2_B1S1) across every server table that carries a
#                      ``parameter_name`` string.  The Pi source is renamed in
#                      lockstep (config.json + decoders.py) so no new row
#                      re-introduces the variant; this migration cleans history.
#                      Forward-only; v0019 untouched.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-454) | Initial -- Sprint 55 US-454 (D-3 / F-082).
# ================================================================================
################################################################################

"""Migration 0020: canonical O2 sensor name (US-454 / D-3 / F-082).

Only one stored O2 label diverges from the ``O2_B{bank}S{sensor}``
convention: the post-catalyst sensor was logged as
``O2_BANK1_SENSOR2_V`` while its sibling (pre-cat) is ``O2_B1S1``.  The
decoder registry itself already declares the canonical short form
(``PARAMETER_DECODERS[...].obdCommand == "O2_B1S2"``), so the canonical
target is :data:`NEW_O2_NAME` ``= 'O2_B1S2'``.

Idempotency contract: the re-map is a bare
``UPDATE ... WHERE parameter_name = 'O2_BANK1_SENSOR2_V'``.  On replay no
row matches (already renamed) -> 0 rows affected, returncode 0.  A
post-condition probe counts any surviving variant rows across every
target table and raises :class:`SchemaProbeError` if the re-map silently
no-op'd, so the runner never records success on a partial migration.

drive_statistics carries ``parameter_name`` in its composite PK
``(summary_id, parameter_name)``.  A plain UPDATE would collide only if a
row already held the canonical ``O2_B1S2`` for the SAME ``summary_id`` --
impossible here because ``O2_B1S2`` was never a stored label before this
migration (the Pi only ever logged ``O2_BANK1_SENSOR2_V`` / ``O2_B1S1``),
and a given drive is either wholly pre- or wholly post-rename.  So the
plain UPDATE is safe; the post-probe still guards against surprises.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'MIGRATION',
    'VERSION',
    'DESCRIPTION',
    'OLD_O2_NAME',
    'NEW_O2_NAME',
    'PARAMETER_NAME_TABLES',
    'remapSql',
    'remainingVariantSql',
    'apply',
]


VERSION: str = '0020'
DESCRIPTION: str = (
    'US-454 O2 name normalization -- re-map parameter_name '
    "'O2_BANK1_SENSOR2_V' -> canonical 'O2_B1S2' across all "
    'parameter_name tables (D-3 / F-082)'
)

# The one divergent stored label and its canonical target.  Grounded in
# src/pi/obdii/decoders.py:290-297 (obdCommand='O2_B1S2') + the
# O2_B{bank}S{sensor} convention shared with O2_B1S1.
OLD_O2_NAME: str = 'O2_BANK1_SENSOR2_V'
NEW_O2_NAME: str = 'O2_B1S2'

# Every server table with a ``parameter_name`` VARCHAR that can hold an O2
# label (src/server/db/models.py): RealtimeData(realtime_data),
# Statistic(statistics), AlertLog(alert_log), DriveStatistic(drive_statistics),
# TrendSnapshot(trend_snapshots), AnomalyLog(anomaly_log).  Covering all of
# them keeps the "SELECT DISTINCT parameter_name -> only canonical" invariant
# honest regardless of which table an O2 row landed in.  Tables that never
# held the variant simply match 0 rows (harmless no-op).
PARAMETER_NAME_TABLES: tuple[str, ...] = (
    'realtime_data',
    'statistics',
    'alert_log',
    'drive_statistics',
    'trend_snapshots',
    'anomaly_log',
)


def remapSql(table: str) -> str:
    """Return the idempotent re-map UPDATE for one table."""
    return (
        f"UPDATE {table} SET parameter_name = '{NEW_O2_NAME}' "
        f"WHERE parameter_name = '{OLD_O2_NAME}';"
    )


def remainingVariantSql(table: str) -> str:
    """Return the post-condition count of surviving variant rows in one table."""
    return (
        f"SELECT COUNT(*) FROM {table} "
        f"WHERE parameter_name = '{OLD_O2_NAME}';"
    )


def _remainingVariantCount(ctx: RunnerContext, table: str) -> int:
    """Count rows in ``table`` still carrying the pre-canonical O2 label.

    Uses ``mysql -B -N`` bare-numeric output (mirrors
    :func:`scripts.apply_server_migrations.serverTableExists`).
    """
    res = _runServerSql(ctx.addrs, ctx.creds, remainingVariantSql(table), ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'O2 name post-probe on {table} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    txt = res.stdout.strip()
    try:
        return int(txt.split()[0])
    except (ValueError, IndexError):
        # No parseable count -> treat as an unverifiable probe, fail loud.
        raise SchemaProbeError(
            f'O2 name post-probe on {table} returned unparseable output: {txt!r}',
        ) from None


def apply(ctx: RunnerContext) -> None:
    """Re-map ``O2_BANK1_SENSOR2_V`` -> ``O2_B1S2`` across every parameter_name table.

    Forward-only + idempotent: a replay re-runs the same WHERE-guarded
    UPDATEs (0 rows on a migrated DB) and re-verifies zero surviving
    variant rows.  Raises :class:`MigrationError` on any UPDATE failure
    and :class:`SchemaProbeError` if a variant row survives the re-map.
    """
    for table in PARAMETER_NAME_TABLES:
        res = _runServerSql(ctx.addrs, ctx.creds, remapSql(table), ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'O2 name remap on {table} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    # Post-condition: no table may still carry the pre-canonical label, or the
    # runner would record success on a silent no-op (wrong DB, filtered
    # replica).  Verified separately from the UPDATE so a partial re-map is loud.
    for table in PARAMETER_NAME_TABLES:
        remaining = _remainingVariantCount(ctx, table)
        if remaining != 0:
            raise SchemaProbeError(
                f'{remaining} row(s) still carry {OLD_O2_NAME!r} in {table} '
                f'after the O2 name re-map; investigate the MariaDB session context',
            )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
