################################################################################
# File Name: v0023_us458_drop_stale_data_source_check.py
# Purpose/Description: US-458 registry migration (F-116 / BL-019 ruling A' /
#                      A-10 / TD-055 ORM-vs-live-DB drift) -- forward-only
#                      migration that DROPS the stale ``data_source`` CHECK
#                      constraint from the live obd2db.  US-424 widened the Pi
#                      + server Python enum tuples to include 'foreign' but
#                      NEVER ALTERed the live DB, so the deployed MariaDB still
#                      carries a stale 4-value
#                      ``data_source in ('real','replay','physics_sim','fixture')``
#                      CHECK (no 'foreign') on realtime_data/statistics/
#                      connection_log/profiles/calibration_sessions -- which
#                      rejects a synced data_source='foreign' row (drive 33) even
#                      though the ORM/code declares NO such CHECK.  This aligns
#                      the live DB DOWN to the code's documented permissive-mirror
#                      stance (models.py:130-131) by dropping the drifted CHECK.
#                      Drop-only = low-risk (no full-table validation scan).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-05    | Rex (US-458) | Initial -- Sprint 55 US-458 (F-116 / BL-019 A').
# ================================================================================
################################################################################

"""Migration 0023: drop the stale live ``data_source`` CHECK (US-458 / F-116).

**The drift (A-10 / TD-055).**  US-424 added ``'foreign'`` to the Pi + server
``DATA_SOURCE_VALUES`` Python tuples and deliberately made the *server* a
permissive mirror -- ``models.py:130-131`` documents that the server
``data_source`` column carries **no DB-level CHECK** (application-enforced
only).  But the live obd2db was provisioned before that decision with a stale
4-value ``data_source in ('real','replay','physics_sim','fixture')`` CHECK
(no ``'foreign'``) that no migration file ever captured.  So the ORM says
"no CHECK" while the deployed DB rejects a ``data_source='foreign'`` row --
the F-116 drive-33 re-tag / sync landmine (BL-019, Atlas ruling A').

**Why DROP, not widen (Atlas ruling A').**  Widening the CHECK to 5 values
would reverse US-424's documented permissive-mirror design *and* force MariaDB
to full-table-validate ``realtime_data`` (the largest table), failing the
deploy on any out-of-enum historical row.  Dropping the stale CHECK is
low-risk (no validation scan) and restores the code's documented state: the
enum is enforced in the Python layer (A-4 tuple-mirror,
``tests/pi/data/test_data_source_foreign_marker.py``), not the DB.

**Discovery, not a fixed name.**  Because the stale CHECK was created ad-hoc on
the live DB and never lived in a migration, its constraint *name* is unknown
(auto-generated, environment-dependent).  Unlike v0015 / v0022 (which drop a
CHECK by a known ``ck_*`` name), this migration DISCOVERS every CHECK whose
``CHECK_CLAUSE`` references ``data_source`` via
``INFORMATION_SCHEMA.CHECK_CONSTRAINTS`` and drops each by its discovered name.
This is schema-wide, so it satisfies the AC's "the 5 tables + probe for any
other" clause for free -- a stale ``data_source`` CHECK on any table is caught.

Idempotency contract: the drop set is exactly what discovery returns.  On a
fresh ``create_all`` DB (the ORM declares no such CHECK) or on replay after a
prior successful run, discovery returns 0 rows -> no drops -> the post-probe
finds 0 survivors -> returncode 0.  A post-condition probe re-runs discovery
and raises :class:`SchemaProbeError` if any ``data_source`` CHECK survives, so
the runner never records success while the drift persists (wrong default DB,
filtered replica, silently-skipped drop).

Reversibility: dropping a CHECK is non-destructive to row data.  No
down-migration ships; rollback is "snapshot + redeploy prior version" per the
runner's documented design.  A hand-off follows on land: Spool re-tags drive
33 (both tiers; the Pi drive-33 rows must be re-tagged too) once the drop
lets ``data_source='foreign'`` insert on the server.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'DATA_SOURCE_COLUMN',
    'DESCRIPTION',
    'EXPECTED_STALE_CHECK_TABLES',
    'MIGRATION',
    'VERSION',
    'apply',
    'discoverDataSourceCheckSql',
    'dropConstraintSql',
]


VERSION: str = '0023'
DESCRIPTION: str = (
    'US-458 F-116 / A-10 -- drop the stale live data_source CHECK '
    "(4-value, no 'foreign') that US-424 never ALTERed away, aligning the live "
    "DB to the code's documented permissive-mirror (drive-33 re-tag unblocked)"
)


# The column whose stale CHECK is being dropped.
DATA_SOURCE_COLUMN: str = 'data_source'

# The tables Atlas (BL-019 ruling A', live-DB verified) identified as carrying
# the stale data_source CHECK.  This is documentation / coverage-intent only --
# the actual drop is DISCOVERY-driven (schema-wide), so a stale data_source
# CHECK on any other table is dropped too (the AC's "probe for any other").
EXPECTED_STALE_CHECK_TABLES: tuple[str, ...] = (
    'realtime_data',
    'statistics',
    'connection_log',
    'profiles',
    'calibration_sessions',
)


def discoverDataSourceCheckSql(dbName: str) -> str:
    """Return the INFORMATION_SCHEMA query that finds every data_source CHECK.

    Selects ``(TABLE_NAME, CONSTRAINT_NAME)`` for every CHECK constraint in the
    schema whose stored ``CHECK_CLAUSE`` references the ``data_source`` column.
    ``data_quality`` CHECK clauses never contain the substring ``data_source``,
    so the ``LIKE`` cleanly isolates the drifted constraint(s).
    """
    return (
        'SELECT TABLE_NAME, CONSTRAINT_NAME FROM information_schema.CHECK_CONSTRAINTS '
        f"WHERE CONSTRAINT_SCHEMA='{dbName}' "
        f"AND CHECK_CLAUSE LIKE '%{DATA_SOURCE_COLUMN}%';"
    )


def dropConstraintSql(tableName: str, constraintName: str) -> str:
    """Return the DDL that drops one discovered CHECK by its name."""
    return f'ALTER TABLE {tableName} DROP CONSTRAINT {constraintName};'


def _discoverDataSourceChecks(ctx: RunnerContext) -> list[tuple[str, str]]:
    """Return ``[(table, constraint), ...]`` for every live data_source CHECK.

    Empty list means no drifted CHECK exists (fresh create_all DB, or a prior
    successful run).  ``mysql -B -N`` yields tab-delimited, header-less rows.
    """
    sql = discoverDataSourceCheckSql(ctx.creds.dbName)
    res = _runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            'data_source CHECK discovery probe failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    checks: list[tuple[str, str]] = []
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            checks.append((parts[0], parts[1]))
    return checks


def apply(ctx: RunnerContext) -> None:
    """Drop every stale ``data_source`` CHECK on the live DB (US-458).

    Forward-only + idempotent: the drop set is exactly what discovery returns,
    so a fresh create_all DB (no such CHECK) or a replay after a prior run is a
    no-op.  Raises :class:`MigrationError` on any DROP failure and
    :class:`SchemaProbeError` if a data_source CHECK survives the drop.
    """
    discovered = _discoverDataSourceChecks(ctx)
    for tableName, constraintName in discovered:
        res = _runServerSql(
            ctx.addrs, ctx.creds, dropConstraintSql(tableName, constraintName), ctx.runner,
        )
        if res.returncode != 0:
            raise MigrationError(
                f'drop stale data_source CHECK {constraintName!r} on '
                f'{tableName!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    # Post-condition: no data_source CHECK may survive, or the runner would
    # record success while the drift persists (wrong DB context, filtered
    # replica).  Verified by re-running discovery so a silently-skipped drop is
    # loud.
    survivors = _discoverDataSourceChecks(ctx)
    if survivors:
        rendered = ', '.join(f'{t}.{c}' for t, c in survivors)
        raise SchemaProbeError(
            f'{len(survivors)} data_source CHECK(s) survive after the drop ran '
            f'({rendered}); investigate the MariaDB session context.',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
