################################################################################
# File Name: v0015_us424_foreign_vehicle_data_quality.py
# Purpose/Description: US-424 registry migration -- widen the data_quality CHECK
#                      enums on drive_summary + drive_statistics to include the
#                      new 'foreign_vehicle' value (F-116 foreign-vehicle
#                      contamination marker, drive-level axis).  MariaDB cannot
#                      widen a CHECK in place, so each named constraint is dropped
#                      and re-added with the expanded enum -- the exact idiom
#                      v0010 used to add 'attribution_anomaly'.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-424) | Initial -- Sprint 51 US-424 (F-116).
# ================================================================================
################################################################################

"""Migration 0015: widen data_quality CHECK enums with 'foreign_vehicle' (US-424).

The ``foreign_vehicle`` marker identifies a drive captured from a vehicle that is
NOT the Eclipse (drive 33, the Ford Explorer).  Both
``drive_summary.data_quality`` and ``drive_statistics.data_quality`` must permit
the new value.  The column width (VARCHAR(20)) already fits 'foreign_vehicle'
(15 chars), so no ``MODIFY`` widen is needed -- only the CHECK enum grows.

Idempotency contract (mirrors v0010 ``_applyDriveStatisticsAnomalyCheck``): for
each table the migration probes ``INFORMATION_SCHEMA.CHECK_CONSTRAINTS`` for the
stored ``CHECK_CLAUSE``:

1. Fresh ``create_all`` DB (the ORM already declares the 5-value enum) ->
   the clause already contains 'foreign_vehicle' -> **no-op**.
2. Production DB with the stale 4-value CHECK -> DROP + re-ADD the named
   constraint with the expanded enum.
3. Already-migrated re-run -> no-op.

A post-condition probe re-reads the ``CHECK_CLAUSE`` and raises
:class:`SchemaProbeError` if 'foreign_vehicle' is still absent -- shielding the
operator from the silent-mysql-session-context class (wrong default DB, filtered
replica) exactly as v0010 / v0012 do.

The ADD DDLs are built from the ORM enum tuples
(``DRIVE_SUMMARY_DATA_QUALITY_VALUES`` / ``DRIVE_STATISTICS_DATA_QUALITY_VALUES``)
so a future enum change trips the DDL-parity tests rather than silently diverging
(A-4 define-once).

Reversibility: adding a value to a CHECK is non-destructive (existing rows are
unaffected).  No down-migration ships; rollback is "snapshot + redeploy prior
version" per the runner's documented design.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    serverTableExists,
)
from src.server.db.models import (
    DATA_QUALITY_FOREIGN_VEHICLE,
    DRIVE_STATISTICS_DATA_QUALITY_VALUES,
    DRIVE_SUMMARY_DATA_QUALITY_VALUES,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'DESCRIPTION',
    'DRIVE_STATISTICS_CHECK_NAME',
    'DRIVE_STATISTICS_TABLE',
    'DRIVE_SUMMARY_CHECK_NAME',
    'DRIVE_SUMMARY_TABLE',
    'MIGRATION',
    'VERSION',
    'apply',
]


VERSION: str = '0015'
DESCRIPTION: str = (
    "US-424 F-116 -- add 'foreign_vehicle' to drive_summary + drive_statistics "
    'data_quality CHECK enums (foreign-vehicle contamination marker)'
)


# Identifiers -- must match the v0010 migration + models.py CHECK names so
# SHOW CREATE TABLE is identical across environments.
DRIVE_SUMMARY_TABLE: str = 'drive_summary'
DRIVE_SUMMARY_CHECK_NAME: str = 'ck_drive_summary_data_quality'
DRIVE_STATISTICS_TABLE: str = 'drive_statistics'
DRIVE_STATISTICS_CHECK_NAME: str = 'ck_drive_statistics_data_quality'


# Build the CHECK enum lists from the ORM-exported tuples (A-4 define-once).
_DRIVE_SUMMARY_ALLOWED_VALUES_SQL: str = ','.join(
    f"'{v}'" for v in DRIVE_SUMMARY_DATA_QUALITY_VALUES
)
_DRIVE_STATISTICS_ALLOWED_VALUES_SQL: str = ','.join(
    f"'{v}'" for v in DRIVE_STATISTICS_DATA_QUALITY_VALUES
)

# MariaDB cannot widen a CHECK in place -- drop the named constraint and re-add
# it with the expanded enum.
DROP_DRIVE_SUMMARY_CHECK_DDL: str = (
    f"ALTER TABLE {DRIVE_SUMMARY_TABLE} "
    f"DROP CONSTRAINT {DRIVE_SUMMARY_CHECK_NAME};"
)
ADD_DRIVE_SUMMARY_CHECK_DDL: str = (
    f"ALTER TABLE {DRIVE_SUMMARY_TABLE} "
    f"ADD CONSTRAINT {DRIVE_SUMMARY_CHECK_NAME} "
    f"CHECK (data_quality IN ({_DRIVE_SUMMARY_ALLOWED_VALUES_SQL}));"
)
DROP_DRIVE_STATISTICS_CHECK_DDL: str = (
    f"ALTER TABLE {DRIVE_STATISTICS_TABLE} "
    f"DROP CONSTRAINT {DRIVE_STATISTICS_CHECK_NAME};"
)
ADD_DRIVE_STATISTICS_CHECK_DDL: str = (
    f"ALTER TABLE {DRIVE_STATISTICS_TABLE} "
    f"ADD CONSTRAINT {DRIVE_STATISTICS_CHECK_NAME} "
    f"CHECK (data_quality IN ({_DRIVE_STATISTICS_ALLOWED_VALUES_SQL}));"
)


# ---- INFORMATION_SCHEMA probe (mirrors v0010) -------------------------------


def _checkClause(ctx: RunnerContext, constraintName: str) -> str | None:
    """Return the stored ``CHECK_CLAUSE`` for a named CHECK, or ``None``.

    ``None`` means the constraint does not exist (no row).  MariaDB stores the
    clause text (e.g. ``data_quality in ('full','sparse',...)``) in
    ``information_schema.CHECK_CONSTRAINTS.CHECK_CLAUSE``.
    """
    sql = (
        "SELECT CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS "
        f"WHERE CONSTRAINT_SCHEMA='{ctx.creds.dbName}' "
        f"AND CONSTRAINT_NAME='{constraintName}';"
    )
    res = _runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'CHECK_CLAUSE probe failed for {constraintName!r}: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    clause = res.stdout.strip()
    return clause or None


# ---- Substep (mirrors v0010 _applyDriveStatisticsAnomalyCheck) --------------


def _widenDataQualityCheck(
    ctx: RunnerContext,
    tableName: str,
    checkName: str,
    dropDdl: str,
    addDdl: str,
) -> None:
    """Widen one ``data_quality`` CHECK to include ``foreign_vehicle``.

    Drops + re-adds the named constraint (MariaDB cannot widen in place).
    Idempotent: a stored clause that already contains 'foreign_vehicle' (fresh
    ``create_all`` DB or a prior run) is a no-op.
    """
    if not serverTableExists(ctx.addrs, ctx.creds, tableName, ctx.runner):
        raise MigrationError(
            f'{tableName!r} table missing; v0015 cannot rebuild its '
            f'data_quality CHECK.  Investigate why create_all + earlier '
            f'migrations did not land the table.',
        )

    clause = _checkClause(ctx, checkName)
    if clause is not None and DATA_QUALITY_FOREIGN_VEHICLE in clause:
        # Already widened (fresh create_all from the 5-value ORM enum, or a
        # prior successful run).  No-op.
        return

    # Drop the stale constraint when it exists; a fresh DB whose named CHECK is
    # absent (clause is None) skips straight to ADD.
    if clause is not None:
        res = _runServerSql(ctx.addrs, ctx.creds, dropDdl, ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'drop CHECK {checkName!r} on {tableName!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    res = _runServerSql(ctx.addrs, ctx.creds, addDdl, ctx.runner)
    if res.returncode != 0:
        err = (res.stderr.strip() or res.stdout.strip()).lower()
        if 'duplicate' not in err and 'already exists' not in err:
            raise MigrationError(
                f'add CHECK {checkName!r} on {tableName!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    # Post-condition probe: the widened clause MUST now carry 'foreign_vehicle'.
    clauseAfter = _checkClause(ctx, checkName)
    if clauseAfter is None or DATA_QUALITY_FOREIGN_VEHICLE not in clauseAfter:
        raise SchemaProbeError(
            f'{checkName!r} CHECK_CLAUSE does not contain '
            f'{DATA_QUALITY_FOREIGN_VEHICLE!r} after rebuild ran; investigate '
            f'the MariaDB session context.',
        )


def apply(ctx: RunnerContext) -> None:
    """Add 'foreign_vehicle' to both data_quality CHECK enums (US-424)."""
    _widenDataQualityCheck(
        ctx,
        DRIVE_SUMMARY_TABLE,
        DRIVE_SUMMARY_CHECK_NAME,
        DROP_DRIVE_SUMMARY_CHECK_DDL,
        ADD_DRIVE_SUMMARY_CHECK_DDL,
    )
    _widenDataQualityCheck(
        ctx,
        DRIVE_STATISTICS_TABLE,
        DRIVE_STATISTICS_CHECK_NAME,
        DROP_DRIVE_STATISTICS_CHECK_DDL,
        ADD_DRIVE_STATISTICS_CHECK_DDL,
    )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
