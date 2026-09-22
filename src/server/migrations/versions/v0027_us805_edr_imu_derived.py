################################################################################
# File Name: v0027_us805_edr_imu_derived.py
# Purpose/Description: US-805 (F-125) -- create edr_imu_derived, the server
#                      destination for the Pi's PitchFusion OUTPUTS. Generated
#                      from the US-764 contract, keyed and partitioned exactly
#                      as the raw EDR tables so retention stays a partition drop.
# Author: Atlas (ARCH-045, under the CIO build override -- board/wip/ARCH-045.md)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-22    | Atlas        | Initial -- edr_imu_derived (US-805 / ARCH-045).
# ================================================================================
################################################################################
"""Migration 0027: create ``edr_imu_derived`` (US-805).

The CIO ruled on 2026-09-22 that ``pitchDeg`` / ``stopCount`` / ``biasRad`` get
their own table rather than joining ``edr_imu_sample``: a raw reading never
changes, a computed value changes when the ALGORITHM changes, and mixing them
would leave early and late rows meaning subtly different things with nothing in
the table marking where the maths moved.

⚠️ **Why this is a separate migration rather than an edit to v0026.**  v0026
generates its DDL from ``EDR_SYNC_TABLES``, so adding a table to the contract
silently widens what v0026 *would* create on a fresh database -- but v0026 has
already run on the live server and will never run again there.  Without this
migration the table would exist on every fresh install and on no upgraded one.

🔴 **A latent defect this exposed, recorded rather than fixed here:** a migration
whose DDL is generated from a MUTABLE contract is not a historical record of
what it did.  v0026 today creates three tables; when it ran it created two.  The
existence probe below keeps that harmless (this migration is a no-op when the
table is already present), but the general problem belongs to its own ticket.
"""

from __future__ import annotations

from datetime import date

from src.common.edr.server_ddl import buildRawTableDdl
from src.server.migrations.runner import Migration, RunnerContext
from src.server.migrations.versions.v0026_us765_edr_raw_tables import (
    FIRST_PARTITION_MONTH,
    PARTITION_MONTHS,
    _createTable,
)

__all__ = [
    'DESCRIPTION',
    'MIGRATION',
    'TABLE_NAME',
    'VERSION',
    'apply',
    'edrDerivedTableDdl',
]


VERSION: str = '0027'
DESCRIPTION: str = (
    'US-805 (F-125) -- create edr_imu_derived: the server destination for the '
    "Pi's PitchFusion outputs (pitch_deg, stop_count, bias_rad), generated from "
    'the US-764 contract, keyed (source_device, source_id, ts_utc) and monthly '
    'RANGE-partitioned exactly as the raw EDR tables'
)

TABLE_NAME: str = 'edr_imu_derived'

# Deliberately the SAME window as v0026.  The derived rows are written beside
# their raw siblings from the same sample, so a different partition floor would
# mean a pair could straddle a partition that exists on one table and not the
# other -- and retention is a partition DROP.
_FIRST_PARTITION_MONTH: date = FIRST_PARTITION_MONTH
_PARTITION_MONTHS: int = PARTITION_MONTHS


def edrDerivedTableDdl() -> str:
    """Return the CREATE TABLE statement for ``edr_imu_derived``.

    Generated from ``src/common/edr/server_ddl.py`` so this migration cannot
    drift from the shared contract.  A function rather than a module constant so
    a test can compare it against the generator directly.

    Returns:
        The MariaDB DDL statement.
    """
    return buildRawTableDdl(
        TABLE_NAME,
        firstMonth=_FIRST_PARTITION_MONTH,
        months=_PARTITION_MONTHS,
    )


def apply(ctx: RunnerContext) -> None:
    """Create ``edr_imu_derived`` if it is not already present.

    Reuses v0026's ``_createTable``, which PROVES the table landed rather than
    trusting ``CREATE TABLE IF NOT EXISTS`` -- that statement reports success
    when it does nothing, so without the probe a session pointed at the wrong
    database would report a clean migration having created nothing.
    """
    _createTable(ctx, TABLE_NAME, edrDerivedTableDdl())


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
