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
# 2026-07-13    | Rex (US-463) | BL-021 -- the 5 live CHECKs are INLINE (name==
#               |              | column); DROP CONSTRAINT can't drop an inline
#               |              | CHECK (1091) and DROP CHECK isn't MariaDB syntax
#               |              | (1064).  Branch inline->definition-preserving
#               |              | MODIFY COLUMN (strips the CHECK); table-level
#               |              | (ck_*)->DROP CONSTRAINT.  Introspect+preserve
#               |              | the full col def (a bare MODIFY resets collation).
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

**BL-021 (US-463): the live CHECKs are INLINE, so DROP CONSTRAINT cannot drop
them.**  The v0018-era rewrite dropped every discovered CHECK with ``ALTER TABLE
... DROP CONSTRAINT <name>``.  But Atlas's live-MariaDB introspection (ruling
2026-07-13) found all 5 ``data_source`` CHECKs are **column-level (inline)** --
defined as part of the ``data_source VARCHAR(16) ... CHECK (...)`` column, so
MariaDB names the constraint after the *column* (``CONSTRAINT_NAME ==
'data_source'``).  On such an inline CHECK, ``DROP CONSTRAINT`` fails with 1091
(can't drop; no matching table-level constraint) and ``DROP CHECK`` is not valid
MariaDB syntax (1064) -- both are why the V0.29.10 deploy stalled at v0023.
The only in-place strip is to **re-declare the column without the CHECK** via
``ALTER TABLE ... MODIFY COLUMN``.  A bare ``MODIFY ... VARCHAR(16)`` would
silently reset the column's charset/collation/default/nullability, so the fix
**introspects the live column definition** (``information_schema.COLUMNS``) and
rebuilds a MODIFY that preserves every attribute -- only the inline CHECK is
dropped.  The 5 tables are ``VARCHAR(16) CHARACTER SET utf8mb4 COLLATE
utf8mb4_unicode_ci NOT NULL DEFAULT 'real'``, but nothing is hard-coded: the
def is read per-table and preserved verbatim.

The discovery + post-probe are unchanged (Atlas: sound).  Each discovered CHECK
is branched: **inline** (``CONSTRAINT_NAME == 'data_source'``) -> definition-
preserving MODIFY COLUMN; **table-level** (a ``ck_*`` name) -> DROP CONSTRAINT
(the original path, still correct for a genuinely table-level constraint).
Today all 5 are inline; the branch keeps the migration correct if a future DB
carries a table-level one.

Idempotency contract: the change set is exactly what discovery returns.  On a
fresh ``create_all`` DB (the ORM declares no such CHECK) or on replay after a
prior successful run, discovery returns 0 rows -> no MODIFY / no drop -> the
post-probe finds 0 survivors -> returncode 0 (a MODIFY that stripped an inline
CHECK removes it from ``CHECK_CONSTRAINTS``, so the replay is a genuine no-op).
A post-condition probe re-runs discovery and raises :class:`SchemaProbeError` if
any ``data_source`` CHECK survives, so the runner never records success while
the drift persists (wrong default DB, filtered replica, silently-skipped strip).

Reversibility: dropping a CHECK is non-destructive to row data.  No
down-migration ships; rollback is "snapshot + redeploy prior version" per the
runner's documented design.  A hand-off follows on land: Spool re-tags drive
33 (both tiers; the Pi drive-33 rows must be re-tagged too) once the drop
lets ``data_source='foreign'`` insert on the server.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    'ColumnDef',
    'apply',
    'discoverDataSourceCheckSql',
    'dropConstraintSql',
    'introspectColumnDefSql',
    'modifyColumnStripCheckSql',
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
    """Return the DDL that drops one discovered *table-level* CHECK by its name.

    Only correct for a genuinely table-level (``ck_*``) constraint.  An inline
    (column-level) CHECK cannot be dropped this way (MariaDB 1091); those are
    stripped via :func:`modifyColumnStripCheckSql` instead (BL-021 / US-463).
    """
    return f'ALTER TABLE {tableName} DROP CONSTRAINT {constraintName};'


@dataclass(frozen=True)
class ColumnDef:
    """The live definition of a column, introspected for a preserving MODIFY.

    Mirrors the ``information_schema.COLUMNS`` fields that a ``MODIFY COLUMN``
    must re-state so re-declaring the column (to drop its inline CHECK) does not
    silently reset any attribute.  ``charset``/``collation``/``default`` are
    ``None`` when the live column has none (a non-string type, or no DEFAULT).
    """

    columnType: str
    charset: str | None
    collation: str | None
    notNull: bool
    default: str | None


def introspectColumnDefSql(dbName: str, tableName: str, columnName: str) -> str:
    """Return the query that reads one column's full live definition.

    Selects the attributes a preserving ``MODIFY COLUMN`` must re-state:
    ``COLUMN_TYPE`` (type + length), ``CHARACTER_SET_NAME``, ``COLLATION_NAME``,
    ``IS_NULLABLE`` and ``COLUMN_DEFAULT``.  Under ``mysql -B -N`` these come
    back as one tab-delimited, header-less row; a SQL ``NULL`` renders as the
    literal token ``NULL``.
    """
    return (
        'SELECT COLUMN_TYPE, CHARACTER_SET_NAME, COLLATION_NAME, IS_NULLABLE, '
        'COLUMN_DEFAULT FROM information_schema.COLUMNS '
        f"WHERE TABLE_SCHEMA='{dbName}' AND TABLE_NAME='{tableName}' "
        f"AND COLUMN_NAME='{columnName}';"
    )


def modifyColumnStripCheckSql(
    tableName: str, columnName: str, colDef: ColumnDef,
) -> str:
    """Return a ``MODIFY COLUMN`` that re-declares the column WITHOUT any CHECK.

    Every introspected attribute is re-stated so nothing is silently reset: the
    charset/collation are emitted explicitly (a bare ``MODIFY ... VARCHAR(16)``
    would reset them to the table/server default), nullability is explicit, and
    the DEFAULT is echoed verbatim from ``COLUMN_DEFAULT`` (already a valid SQL
    expression, e.g. ``'real'``).  No CHECK clause is emitted, so re-declaring
    the column drops the inline CHECK that was part of its old definition.
    """
    parts = [
        f'ALTER TABLE {tableName} MODIFY COLUMN {columnName} {colDef.columnType}',
    ]
    if colDef.charset:
        parts.append(f'CHARACTER SET {colDef.charset}')
    if colDef.collation:
        parts.append(f'COLLATE {colDef.collation}')
    parts.append('NOT NULL' if colDef.notNull else 'NULL')
    if colDef.default is not None:
        parts.append(f'DEFAULT {colDef.default}')
    return ' '.join(parts) + ';'


def _noneIfSqlNull(token: str) -> str | None:
    """Map a ``mysql -N`` field to ``None`` when it is SQL NULL / empty."""
    stripped = token.strip()
    if not stripped or stripped == 'NULL':
        return None
    return stripped


def _introspectColumnDef(
    ctx: RunnerContext, tableName: str, columnName: str,
) -> ColumnDef:
    """Read ``tableName.columnName``'s live definition (for a preserving MODIFY).

    Raises :class:`SchemaProbeError` if the probe fails or the column is absent
    -- never MODIFY a column whose real definition could not be read (that is
    the exact silent-reset the introspect-and-preserve contract guards against).
    """
    sql = introspectColumnDefSql(ctx.creds.dbName, tableName, columnName)
    res = _runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'column-def introspection failed for {tableName}.{columnName}: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    line = res.stdout.strip()
    if not line:
        raise SchemaProbeError(
            f'column {tableName}.{columnName} not found while introspecting its '
            'definition to strip the inline data_source CHECK; investigate the '
            'MariaDB session context.',
        )
    fields = line.split('\t')
    if len(fields) < 4:
        raise SchemaProbeError(
            f'malformed column-def row for {tableName}.{columnName}: {line!r}',
        )
    return ColumnDef(
        columnType=fields[0].strip(),
        charset=_noneIfSqlNull(fields[1]),
        collation=_noneIfSqlNull(fields[2]),
        notNull=fields[3].strip().upper() == 'NO',
        default=_noneIfSqlNull(fields[4]) if len(fields) > 4 else None,
    )


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


def _stripInlineDataSourceCheck(ctx: RunnerContext, tableName: str) -> None:
    """Strip an INLINE ``data_source`` CHECK via a definition-preserving MODIFY.

    Introspects the live column def first, then re-declares the column WITHOUT
    the CHECK (MODIFY COLUMN) -- preserving type/charset/collation/nullability/
    default.  DROP CONSTRAINT / DROP CHECK cannot remove an inline CHECK on
    MariaDB (1091 / 1064); this is the only in-place strip (BL-021).
    """
    colDef = _introspectColumnDef(ctx, tableName, DATA_SOURCE_COLUMN)
    ddl = modifyColumnStripCheckSql(tableName, DATA_SOURCE_COLUMN, colDef)
    res = _runServerSql(ctx.addrs, ctx.creds, ddl, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'strip inline data_source CHECK on {tableName!r} via MODIFY COLUMN '
            f'failed: {res.stderr.strip() or res.stdout.strip()}',
        )


def _dropTableLevelDataSourceCheck(
    ctx: RunnerContext, tableName: str, constraintName: str,
) -> None:
    """Drop a genuinely TABLE-LEVEL (``ck_*``) ``data_source`` CHECK by name."""
    res = _runServerSql(
        ctx.addrs, ctx.creds, dropConstraintSql(tableName, constraintName), ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'drop table-level data_source CHECK {constraintName!r} on '
            f'{tableName!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )


def apply(ctx: RunnerContext) -> None:
    """Strip every stale ``data_source`` CHECK on the live DB (US-458 / US-463).

    Forward-only + idempotent: the change set is exactly what discovery returns,
    so a fresh create_all DB (no such CHECK) or a replay after a prior run is a
    no-op.  Each discovered CHECK is branched on its shape (BL-021):

    * **inline** (``CONSTRAINT_NAME == 'data_source'``, i.e. name == column) ->
      definition-preserving MODIFY COLUMN (DROP CONSTRAINT would raise 1091);
    * **table-level** (a ``ck_*`` name) -> DROP CONSTRAINT (the original path).

    Raises :class:`MigrationError` on any DDL failure and
    :class:`SchemaProbeError` if a data_source CHECK survives the strip.
    """
    discovered = _discoverDataSourceChecks(ctx)
    for tableName, constraintName in discovered:
        if constraintName == DATA_SOURCE_COLUMN:
            # Inline CHECK (name == column): only MODIFY COLUMN can strip it.
            _stripInlineDataSourceCheck(ctx, tableName)
        else:
            # Table-level CHECK (ck_*): drop it by its discovered name.
            _dropTableLevelDataSourceCheck(ctx, tableName, constraintName)

    # Post-condition: no data_source CHECK may survive, or the runner would
    # record success while the drift persists (wrong DB context, filtered
    # replica).  Verified by re-running discovery so a silently-skipped strip is
    # loud.
    survivors = _discoverDataSourceChecks(ctx)
    if survivors:
        rendered = ', '.join(f'{t}.{c}' for t, c in survivors)
        raise SchemaProbeError(
            f'{len(survivors)} data_source CHECK(s) survive after the strip ran '
            f'({rendered}); investigate the MariaDB session context.',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
