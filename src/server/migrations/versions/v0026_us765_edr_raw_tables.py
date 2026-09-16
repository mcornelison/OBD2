################################################################################
# File Name: v0026_us765_edr_raw_tables.py
# Purpose/Description: US-765 (F-142) -- create edr_imu_sample and
#                      edr_light_sample on obd2db. The Pi has recorded EDR
#                      samples since V0.29.4 and none of them have ever left the
#                      device, because there was no table to receive them.
# Author: Atlas (Architect)
# Creation Date: 2026-09-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-16    | Atlas        | Initial -- CIO-directed build (charter s2
#               |              | override recorded in board/wip/ARCH-029.md).
# ================================================================================
################################################################################

"""Migration 0026: the server EDR raw tables (US-765 / F-142).

Why this migration exists
-------------------------

Measured on 2026-09-16: ``SHOW TABLES LIKE 'edr%'`` on ``obd2db`` returned
**zero rows**, while the Pi held 14,461,121 ``edr_imu_sample`` rows and 701,609
``edr_light_sample`` rows.  The Pi's journal shows an hourly purge --
``deleted imu=73798 light=3575 (older than 7 days)`` -- running since the
feature shipped on 2026-07-01 (US-410).

So the black box recorded faithfully for six to ten weeks and deleted itself on
a rolling window, because the destination did not exist.  ``b25acc7d``
(2026-09-14) raised retention 7 -> 45 days, which pauses the deletion and puts a
date on it: **it resumes about 2026-10-22**.  This migration is the destination.

Why the DDL is GENERATED and not written here
---------------------------------------------

``src/common/edr/server_ddl.py`` (US-764) builds the MariaDB DDL from
``sensor_schema.EDR_COLUMNS`` -- the same contract the Pi tables and the
SQLAlchemy models mirror.  Restating the shape in this file would create a
SECOND copy of the contract, which is precisely the Pi<->server divergence A-4
tracks.  This module therefore supplies only the *partition window* and calls
the generator; ``tests/server/test_edr_raw_tables.py`` compares the two rather
than pinning a literal.

Why the primary key has three columns
-------------------------------------

``(source_device, source_id, ts_utc)``.  MariaDB requires the **partition
column** in every unique key, and these tables are RANGE-partitioned monthly on
``ts_utc``.  ``(source_device, source_id)`` is still unique on its own --
``source_id`` is the Pi rowid -- so the third column changes the DDL, not the
identity.

There is deliberately **no surrogate id**.  ``drives.PRIMARY KEY`` is
``drive_id`` alone, with no device dimension, and will collide the moment a
second vehicle reports.  These tables are keyed the way that one should have
been.

Forward-only and idempotent
---------------------------

``CREATE TABLE IF NOT EXISTS`` with an existence probe before and a
post-condition probe after, matching v0013 / v0017 / v0025.  Re-running is a
no-op.

WARNING **The A-10 trap does not apply here, and the reason is worth stating**:
``CREATE TABLE IF NOT EXISTS`` is a **silent no-op on an existing table**, so it
can never be used to ALTER one.  These are new tables that exist nowhere, which
is the only situation in which that idiom is safe.  A future column -- or a new
monthly partition -- needs its own migration with its own probe, never an edit
to this file.  ``server_ddl.buildAddPartitionSql`` exists for exactly that.
"""

from __future__ import annotations

from datetime import date

from scripts.apply_server_migrations import (
    MigrationError,
    _runServerSql,
    serverTableExists,
)
from src.common.edr.server_ddl import buildAllRawTableDdl
from src.common.edr.sync_contract import EDR_SYNC_TABLES
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'DESCRIPTION',
    'FIRST_PARTITION_MONTH',
    'MIGRATION',
    'PARTITION_MONTHS',
    'VERSION',
    'apply',
    'edrRawTableDdl',
]


VERSION: str = '0026'
DESCRIPTION: str = (
    'US-765 (F-142) -- create edr_imu_sample + edr_light_sample: the server '
    'destination for EDR raw samples, generated from the US-764 contract, '
    'keyed (source_device, source_id, ts_utc) and RANGE-partitioned monthly '
    'on ts_utc so retention is a partition drop rather than a row scan'
)

# The first month that can still hold a row.  The Pi floor is 2026-09-07 -- the
# residue of the last 7-day purge before US-761 raised retention to 45 days --
# so nothing older than September 2026 can arrive.
FIRST_PARTITION_MONTH: date = date(2026, 9, 1)

# How many NAMED monthly partitions precede pmax.  This is not a correctness
# bound: ``pmax`` (VALUES LESS THAN MAXVALUE) catches everything past the
# window, so a row from 2029 still lands.  The count only decides how many
# months can be dropped INDIVIDUALLY before someone has to reorganise pmax, and
# a year of headroom keeps that off the critical path.
PARTITION_MONTHS: int = 12


def edrRawTableDdl() -> list[str]:
    """Return the CREATE TABLE statements, one per EDR sync table.

    Generated from ``src/common/edr/server_ddl.py`` so this migration cannot
    drift from the shared contract.  Exposed as a function (rather than a
    module constant) so a test can compare it against the generator directly.

    Returns:
        One DDL statement per ``EDR_SYNC_TABLES`` entry, in scope order.
    """
    return buildAllRawTableDdl(
        firstMonth=FIRST_PARTITION_MONTH,
        months=PARTITION_MONTHS,
    )


def _createTable(ctx: RunnerContext, tableName: str, ddl: str) -> None:
    """Create one table if absent, then PROVE it landed.

    The post-condition probe is not ceremony.  ``CREATE TABLE IF NOT EXISTS``
    reports success when it does nothing, so without a probe a wrong-database
    session context (a filtered replica, a wrong default DB) would report a
    clean migration having created no table at all.
    """
    if serverTableExists(ctx.addrs, ctx.creds, tableName, ctx.runner):
        return

    res = _runServerSql(ctx.addrs, ctx.creds, ddl, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'CREATE TABLE {tableName} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    if not serverTableExists(ctx.addrs, ctx.creds, tableName, ctx.runner):
        raise MigrationError(
            f'{tableName} absent after CREATE TABLE reported success.  '
            f'CREATE TABLE IF NOT EXISTS succeeds when it does nothing, so this '
            f'almost always means the session landed in the wrong database.  '
            f'Investigate the MariaDB session context before re-running.',
        )


def apply(ctx: RunnerContext) -> None:
    """Create both EDR raw tables.

    Order is not load-bearing here -- unlike v0025 these carry no foreign key
    to one another -- but the pairing of table name to generated DDL is, so it
    is zipped strictly rather than indexed.
    """
    for tableName, ddl in zip(EDR_SYNC_TABLES, edrRawTableDdl(), strict=True):
        _createTable(ctx, tableName, ddl)


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
