################################################################################
# File Name: v0021_us455_unit_string_canonicalization.py
# Purpose/Description: US-455 unit-string canonicalization (D-4 / F-082) --
#                      forward-only DATA migration that re-maps the divergent
#                      abbreviated unit strings on ``realtime_data.unit`` to the
#                      python-obd NATIVE canonical form: 'V' -> 'volt',
#                      'kPa' -> 'kilopascal', 's' -> 'second'.  The Pi decoder
#                      source is renamed in lockstep (decoders.py) so no new row
#                      re-introduces an abbreviation; this migration cleans
#                      history so a physical unit carries ONE canonical label
#                      across the legacy (native) and decoder paths.  Forward-only;
#                      v0020 untouched.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-455) | Initial -- Sprint 55 US-455 (D-4 / F-082).
# ================================================================================
################################################################################

"""Migration 0021: canonical unit strings (US-455 / D-4 / F-082).

The ``unit`` column is populated by two paths in the Pi logger:

* the **legacy** path stores ``str(response.unit)`` -- the python-obd
  NATIVE pint string (``'volt'``, ``'kilopascal'``, ``'second'``);
* the **decoder** path stored a hand-written abbreviation
  (``'V'``, ``'kPa'``, ``'s'``).

So the same physical unit fragmented across two strings: voltage as
``'V'`` (BATTERY_V / O2_B1S2 decoders) *and* ``'volt'`` (legacy O2_B1S1),
pressure as ``'kPa'`` (BAROMETRIC_KPA) *and* ``'kilopascal'`` (legacy
INTAKE_PRESSURE).  US-455 renames the decoder source to emit the native
form; this migration re-maps the historical abbreviation rows so
``SELECT DISTINCT unit`` collapses each physical unit to one canonical
label.

Only :data:`UNIT_TABLE` (``realtime_data``) carries the Pi-emitted
physical-unit string.  ``drive_derived_signals`` has its own
server-computed ``*_unit`` label columns (``km/h`` / ``km`` / ``m/s^2``)
that are NOT part of this Pi unit path and are untouched.

Idempotency contract: each re-map is a bare
``UPDATE ... WHERE unit = '<abbrev>'``.  On replay no row matches
(already canonical) -> 0 rows affected, returncode 0.  A post-condition
probe counts any surviving abbreviation row and raises
:class:`SchemaProbeError` if a re-map silently no-op'd, so the runner
never records success on a partial migration.

The DTC ``'count'`` label is deliberately NOT re-mapped: python-obd's
STATUS command carries no pint unit, so ``'count'`` has no native form
and no colliding twin.  The enum ``textLabel`` overload (``'CL'`` / ``'ON'``
in the unit column for FUEL_SYSTEM_STATUS / MIL_ON) is likewise left
intact -- the AC keeps the native enum overload.
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
    'UNIT_TABLE',
    'UNIT_REMAP',
    'remapSql',
    'remainingVariantSql',
    'apply',
]


VERSION: str = '0021'
DESCRIPTION: str = (
    'US-455 unit-string canonicalization -- re-map realtime_data.unit '
    "abbreviations ('V'->'volt', 'kPa'->'kilopascal', 's'->'second') to "
    'the python-obd native canonical form (D-4 / F-082)'
)

# The only table carrying the Pi-emitted physical-unit string.  Confirmed
# against src/server/db/models.py: RealtimeData.unit (String(32)) is the sole
# bare ``unit`` column; drive_derived_signals' speed_unit/distance_unit/
# accel_unit are server-computed labels on a different path.
UNIT_TABLE: str = 'realtime_data'

# Abbreviation -> python-obd native canonical form.  Grounded in the decoder
# test fixtures, which feed the NATIVE unit as the decoder input:
# 'volt' (test_decoders_v2.py, decodeBatteryVoltage input),
# 'kilopascal' (decodeBarometricKpa input), 'second' (decodeRuntimeSec input).
# The decoder previously overrode these with the abbreviation; US-455 keeps the
# native form on both the decoder and legacy paths.
UNIT_REMAP: dict[str, str] = {
    'V': 'volt',
    'kPa': 'kilopascal',
    's': 'second',
}


def remapSql(oldUnit: str, newUnit: str) -> str:
    """Return the idempotent re-map UPDATE for one unit abbreviation."""
    return (
        f"UPDATE {UNIT_TABLE} SET unit = '{newUnit}' "
        f"WHERE unit = '{oldUnit}';"
    )


def remainingVariantSql(oldUnit: str) -> str:
    """Return the post-condition count of rows still carrying the abbreviation."""
    return (
        f"SELECT COUNT(*) FROM {UNIT_TABLE} "
        f"WHERE unit = '{oldUnit}';"
    )


def _remainingVariantCount(ctx: RunnerContext, oldUnit: str) -> int:
    """Count rows in :data:`UNIT_TABLE` still carrying the abbreviation.

    Uses ``mysql -B -N`` bare-numeric output (mirrors
    :func:`scripts.apply_server_migrations.serverTableExists` and v0020).
    """
    res = _runServerSql(ctx.addrs, ctx.creds, remainingVariantSql(oldUnit), ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'unit canonicalization post-probe for {oldUnit!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    txt = res.stdout.strip()
    try:
        return int(txt.split()[0])
    except (ValueError, IndexError):
        # No parseable count -> treat as an unverifiable probe, fail loud.
        raise SchemaProbeError(
            f'unit canonicalization post-probe for {oldUnit!r} returned '
            f'unparseable output: {txt!r}',
        ) from None


def apply(ctx: RunnerContext) -> None:
    """Re-map abbreviated ``realtime_data.unit`` values to their native canonical form.

    Forward-only + idempotent: a replay re-runs the same WHERE-guarded
    UPDATEs (0 rows on a migrated DB) and re-verifies zero surviving
    abbreviation rows.  Raises :class:`MigrationError` on any UPDATE
    failure and :class:`SchemaProbeError` if an abbreviation row survives
    the re-map.
    """
    for oldUnit, newUnit in UNIT_REMAP.items():
        res = _runServerSql(ctx.addrs, ctx.creds, remapSql(oldUnit, newUnit), ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'unit canonicalization re-map {oldUnit!r} -> {newUnit!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    # Post-condition: no abbreviation may survive, or the runner would record
    # success on a silent no-op (wrong DB, filtered replica).  Verified
    # separately from the UPDATE so a partial re-map is loud.
    for oldUnit in UNIT_REMAP:
        remaining = _remainingVariantCount(ctx, oldUnit)
        if remaining != 0:
            raise SchemaProbeError(
                f'{remaining} row(s) still carry unit {oldUnit!r} in {UNIT_TABLE} '
                f'after canonicalization; investigate the MariaDB session context',
            )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
