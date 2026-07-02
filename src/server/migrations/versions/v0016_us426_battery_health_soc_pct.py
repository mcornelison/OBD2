################################################################################
# File Name: v0016_us426_battery_health_soc_pct.py
# Purpose/Description: US-426 registry migration (BL-015 / F-061) -- retire the
#                      misnamed legacy battery_health_log.start_soc / end_soc
#                      columns (they held VCELL volts, redundant with the Pi's
#                      *_vcell_v) and add the dedicated *_vcell_v + *_soc_pct
#                      columns so the server table is byte-for-byte identical to
#                      the Pi SQLite table (A-4).  *_soc_pct is the durable home
#                      for the MAX17048 register State-of-Charge percent.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-426) | Initial -- Sprint 52 US-426 (BL-015 / F-061).
# ================================================================================
################################################################################

"""Migration 0016: battery_health_log SoC% schema (US-426 / BL-015).

ONE forward-only both-tier migration (the Pi half is the CREATE-SELECT-DROP-
RENAME rebuild in ``src.pi.power.battery_health.ensureBatteryHealthLogSocPctColumns``;
this is the server MariaDB half).  It:

* DROPs the legacy ``start_soc`` / ``end_soc`` columns -- misnamed (they held
  VCELL volts, not SoC%%) and redundant with the vcell columns.  Merges old
  US-423.
* ADDs ``start_vcell_v`` / ``end_vcell_v`` (FLOAT NULL) -- the US-289 Pi rename
  mirrored to the server so the full sync payload the Pi already sends is
  consumed with no unmapped keys (closes the A-4 vcell divergence for this
  table).
* ADDs ``start_soc_pct`` / ``end_soc_pct`` (FLOAT NULL) -- the durable MAX17048
  register SoC%% home.  US-427 wires the real register read; here they land
  empty (NULL).

Idempotency contract (mirrors v0015): each column op probes
``INFORMATION_SCHEMA.COLUMNS`` first.

1. Fresh ``create_all`` DB (the ORM already declares the target shape) -> every
   ADD is a no-op and neither legacy column is present -> no-op.
2. Production DB with the legacy shape -> DROP the two legacy columns + ADD the
   four new ones.
3. Already-migrated re-run -> no-op.

A post-condition probe re-reads the column set and raises
:class:`SchemaProbeError` if the four new columns are not all present or either
legacy column survives -- shielding the operator from the silent-mysql-session-
context class (wrong default DB, filtered replica) exactly as v0010 / v0012 /
v0015 do.

Reversibility: DROP COLUMN is destructive of the legacy volts (which are
preserved on the Pi side via the COALESCE-into-vcell rebuild, and are redundant
per the BL-015 ruling).  No down-migration ships; rollback is "snapshot +
redeploy prior version" per the runner's documented design.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    probeServerColumns,
    serverTableExists,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'BATTERY_HEALTH_LOG_TABLE',
    'DESCRIPTION',
    'DROP_COLUMNS',
    'MIGRATION',
    'NEW_COLUMNS',
    'VERSION',
    'apply',
]


VERSION: str = '0016'
DESCRIPTION: str = (
    'US-426 BL-015/F-061 -- battery_health_log: drop legacy start_soc/end_soc '
    '(VCELL volts) + add start_vcell_v/end_vcell_v + start_soc_pct/end_soc_pct '
    '(durable MAX17048 SoC% home), both-tier-identical (A-4)'
)


BATTERY_HEALTH_LOG_TABLE: str = 'battery_health_log'

# Legacy columns to DROP (held VCELL volts despite the "soc" name).
DROP_COLUMNS: tuple[str, ...] = ('start_soc', 'end_soc')

# New columns to ADD -- FLOAT NULL, matching the BatteryHealthLog ORM model.
# Order matches the model so SHOW CREATE TABLE reads intuitively.
NEW_COLUMNS: tuple[str, ...] = (
    'start_vcell_v', 'end_vcell_v', 'start_soc_pct', 'end_soc_pct',
)


def _dropColumnDdl(column: str) -> str:
    return (
        f"ALTER TABLE {BATTERY_HEALTH_LOG_TABLE} DROP COLUMN {column};"
    )


def _addColumnDdl(column: str) -> str:
    return (
        f"ALTER TABLE {BATTERY_HEALTH_LOG_TABLE} ADD COLUMN {column} FLOAT NULL;"
    )


def apply(ctx: RunnerContext) -> None:
    """Retire legacy start_soc/end_soc + add the vcell/soc_pct columns (US-426)."""
    if not serverTableExists(
        ctx.addrs, ctx.creds, BATTERY_HEALTH_LOG_TABLE, ctx.runner,
    ):
        raise MigrationError(
            f'{BATTERY_HEALTH_LOG_TABLE!r} table missing; v0016 cannot migrate '
            f'its SoC% columns.  Investigate why create_all + earlier '
            f'migrations (v0002) did not land the table.',
        )

    existing = set(
        probeServerColumns(
            ctx.addrs, ctx.creds, BATTERY_HEALTH_LOG_TABLE, ctx.runner,
        )
    )

    # ADD the new columns first (idempotent: skip any already present) so the
    # table never sits in a state where the volts are gone but the new homes
    # are absent.
    for column in NEW_COLUMNS:
        if column in existing:
            continue
        res = _runServerSql(
            ctx.addrs, ctx.creds, _addColumnDdl(column), ctx.runner,
        )
        if res.returncode != 0:
            err = (res.stderr.strip() or res.stdout.strip()).lower()
            if 'duplicate' not in err and 'exists' not in err:
                raise MigrationError(
                    f'add column {column!r} on {BATTERY_HEALTH_LOG_TABLE!r} '
                    f'failed: {res.stderr.strip() or res.stdout.strip()}',
                )

    # DROP the legacy columns (idempotent: skip any already gone).
    for column in DROP_COLUMNS:
        if column not in existing:
            continue
        res = _runServerSql(
            ctx.addrs, ctx.creds, _dropColumnDdl(column), ctx.runner,
        )
        if res.returncode != 0:
            err = (res.stderr.strip() or res.stdout.strip()).lower()
            if "can't drop" not in err and 'check that' not in err:
                raise MigrationError(
                    f'drop column {column!r} on {BATTERY_HEALTH_LOG_TABLE!r} '
                    f'failed: {res.stderr.strip() or res.stdout.strip()}',
                )

    # Post-condition probe: all four new columns present, both legacy gone.
    after = set(
        probeServerColumns(
            ctx.addrs, ctx.creds, BATTERY_HEALTH_LOG_TABLE, ctx.runner,
        )
    )
    missing = [c for c in NEW_COLUMNS if c not in after]
    survived = [c for c in DROP_COLUMNS if c in after]
    if missing or survived:
        raise SchemaProbeError(
            f'{BATTERY_HEALTH_LOG_TABLE!r} column shape wrong after v0016: '
            f'missing new columns={missing}, surviving legacy columns='
            f'{survived}; investigate the MariaDB session context.',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
