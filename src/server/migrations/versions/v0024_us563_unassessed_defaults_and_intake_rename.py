################################################################################
# File Name: v0024_us563_unassessed_defaults_and_intake_rename.py
# Purpose/Description: US-563 registry migration (F-134) -- three schema truths
#                      on the deployed obd2db:
#                        1. every data_quality column DEFAULTs to the NON-verdict
#                           'unassessed' instead of the BEST verdict 'full'
#                           (+ the CHECK enums widened to permit it);
#                        2. drive_summary.is_real DEFAULTs to NULL instead of 0;
#                        3. drive_summary.ambient_temp_at_start_c is RENAMED to
#                           intake_air_temp_at_start_c -- it is fed from IAT and
#                           was never ambient.
#                      Also the SSOT for the applied-schema DEFAULT probe that
#                      tests/server/test_applied_schema_column_defaults.py
#                      reuses (define-once: migration and guard share one
#                      definition of "the applied default").
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-563) | Initial -- Sprint 75 F-134.
# 2026-08-23    | Rex (US-568) | Add _requireColumn preconditions so a missing
#               |              | target column fails with a diagnosis instead of
#               |              | a bare MariaDB 1054 -- and so a missing is_real
#               |              | can no longer read as "already NULL-defaulted".
#               |              | No behaviour change on a correct schema.
# ================================================================================
################################################################################

"""Migration 0024: unassessed defaults + the intake-air rename (US-563 / F-134).

What shipped the defect
-----------------------

``drive_summary.data_quality`` was ``varchar(20) NOT NULL DEFAULT 'full'`` on
prod -- a quality VERDICT column whose default is the BEST verdict -- and
``is_real`` was ``tinyint(1) NULL DEFAULT 0``.  A drive that had ended but had
not yet reached the nightly 03:30 analytics batch therefore read back as
"full quality, not real": a confident verdict on a drive nobody had assessed.
On 2026-08-20 that read misled BOTH Spool and Atlas into filing a phantom
roll-up regression story.  There is NO roll-up regression -- the batch is a
nightly job and it runs correctly -- and there is NO compute defect;
``_deriveIsReal`` works as designed and the observed ``is_real=0`` was this
schema default (Atlas, confirmed).

No code review would have caught it.  The code is innocent; the schema lied.

Three substeps, each idempotent with a post-condition probe
----------------------------------------------------------

1. **Widen the data_quality CHECK enums** with ``'unassessed'`` on
   ``drive_summary`` / ``drive_statistics`` / ``drives``.  MariaDB cannot widen
   a CHECK in place, so each named constraint is dropped and re-added -- the
   exact idiom v0010 / v0015 / v0022 use.  This MUST precede substep 2: setting
   a default the CHECK forbids would make every subsequent INSERT fail.
2. **Re-default the three data_quality columns** to ``'unassessed'`` and
   ``drive_summary.is_real`` to NULL.  ``MODIFY`` re-states the full column
   definition (MariaDB requires it) so NOT NULL / width survive -- v0012's
   lesson: a bare ``MODIFY ... VARCHAR(20)`` silently drops both.
   No carve-outs.  ``drives`` and ``drive_statistics`` rows are only ever
   written with an explicit data_quality today, so re-defaulting them changes
   no behaviour -- but "the writer always sets it" is a claim about intent,
   never about enforcement, and a guard with exemptions is the inert-guard
   anti-pattern.
3. **Rename** ``ambient_temp_at_start_c`` -> ``intake_air_temp_at_start_c``.
   The column is fed from IAT (PID 0x0F) at drive-start.  Drive 41 logged
   47 C / 117 F into it while real ambient was 24-27 C, and IAT ran
   48.1 -> 40.6 C by speed band -- it cools with airflow and never nears
   ambient.  The 2G 4G63 does not support PID 0x46, so NO ambient source exists
   on this vehicle and inventing one would be fabrication.  Rename, don't
   re-derive.  Spelled as ``CHANGE COLUMN`` (not ``RENAME COLUMN``) for
   compatibility with MariaDB below 10.5.2.

Existing rows are NOT rewritten
-------------------------------

A DEFAULT applies to future INSERTs only.  Rows already carrying ``'full'`` /
``is_real=0`` keep those values: some are genuine batch results and the
migration cannot tell them apart from pre-computed defaults without re-running
analytics, which is a different job with a different owner.  Back-filling
"probably unassessed" over them would MANUFACTURE a reading -- the corollary to
SSOT rule A (land what you read; landing must not manufacture).  The nightly
batch overwrites each row the next time it assesses it.

Reversibility: forward-only, as every migration in this registry.  Widening a
CHECK and relaxing a DEFAULT are both non-destructive; the rename is the only
lossy-looking step and it preserves every value.  Rollback is
"snapshot + redeploy prior version" per the runner's documented design.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    serverTableExists,
)
from src.server.db.models import (
    DATA_QUALITY_COLUMN_LENGTH,
    DATA_QUALITY_UNASSESSED,
    DRIVE_STATISTICS_ASSESSED_DATA_QUALITY_VALUES,
    DRIVE_STATISTICS_DATA_QUALITY_VALUES,
    DRIVE_SUMMARY_ASSESSED_DATA_QUALITY_VALUES,
    DRIVE_SUMMARY_DATA_QUALITY_VALUES,
    DRIVES_ASSESSED_DATA_QUALITY_VALUES,
    DRIVES_DATA_QUALITY_VALUES,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'ASSESSED_DATA_QUALITY_VALUES',
    'DATA_QUALITY_COLUMN',
    'DESCRIPTION',
    'DRIVE_SUMMARY_TABLE',
    'MIGRATION',
    'NEW_INTAKE_COLUMN',
    'NULL_DEFAULT_COLUMNS',
    'OLD_AMBIENT_COLUMN',
    'RENAME_INTAKE_COLUMN_DDL',
    'UNASSESSED_VALUE',
    'VERSION',
    'apply',
    'columnExistsSql',
    'discoverColumnDefaultSql',
    'discoverDataQualityDefaultsSql',
    'normalizeAppliedDefault',
]


VERSION: str = '0024'
DESCRIPTION: str = (
    'US-563 F-134 -- data_quality columns DEFAULT to the non-verdict '
    "'unassessed' (CHECK enums widened), drive_summary.is_real DEFAULTs NULL, "
    'and ambient_temp_at_start_c renames to intake_air_temp_at_start_c '
    '(the column is fed from IAT and was never ambient)'
)


# ================================================================================
# Identifiers -- names match models.py + the earlier migrations' ADD CONSTRAINT
# so SHOW CREATE TABLE is identical across SQLite (tests) and MariaDB (prod).
# ================================================================================

DATA_QUALITY_COLUMN: str = 'data_quality'
UNASSESSED_VALUE: str = DATA_QUALITY_UNASSESSED

DRIVE_SUMMARY_TABLE: str = 'drive_summary'
DRIVE_STATISTICS_TABLE: str = 'drive_statistics'
DRIVES_TABLE: str = 'drives'

OLD_AMBIENT_COLUMN: str = 'ambient_temp_at_start_c'
NEW_INTAKE_COLUMN: str = 'intake_air_temp_at_start_c'

IS_REAL_COLUMN: str = 'is_real'


# Every value that means "an assessment RAN and reached a conclusion", across
# every table that carries a data_quality column.  Built from the ORM's own
# *_ASSESSED_* tuples (A-4 define-once) so a verdict added to any enum tomorrow
# is automatically forbidden as a DEFAULT without editing this file.
ASSESSED_DATA_QUALITY_VALUES: frozenset[str] = frozenset(
    (
        *DRIVE_SUMMARY_ASSESSED_DATA_QUALITY_VALUES,
        *DRIVE_STATISTICS_ASSESSED_DATA_QUALITY_VALUES,
        *DRIVES_ASSESSED_DATA_QUALITY_VALUES,
    ),
)

# Columns whose applied DEFAULT must be NULL.  ``is_real`` is a COMPUTED verdict
# (TRUE/FALSE = "analytics looked"); NULL is "nobody has looked".  A non-NULL
# default on a computed column reads as a computed result on a row nobody
# computed -- the same defect as a verdict-shaped data_quality default, arriving
# by a different road.
NULL_DEFAULT_COLUMNS: tuple[tuple[str, str], ...] = (
    (DRIVE_SUMMARY_TABLE, IS_REAL_COLUMN),
)


# The per-table CHECK constraint names + the enum each one must carry.
_CHECK_TARGETS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (DRIVE_SUMMARY_TABLE, 'ck_drive_summary_data_quality',
     DRIVE_SUMMARY_DATA_QUALITY_VALUES),
    (DRIVE_STATISTICS_TABLE, 'ck_drive_statistics_data_quality',
     DRIVE_STATISTICS_DATA_QUALITY_VALUES),
    (DRIVES_TABLE, 'ck_drives_data_quality', DRIVES_DATA_QUALITY_VALUES),
)

# The data_quality columns to re-default.  All three; see module docstring for
# why there are no carve-outs.
_DATA_QUALITY_TABLES: tuple[str, ...] = (
    DRIVE_SUMMARY_TABLE, DRIVE_STATISTICS_TABLE, DRIVES_TABLE,
)


def _modifyDataQualityDefaultDdl(tableName: str) -> str:
    """MODIFY re-stating the whole column definition (MariaDB requires it).

    A bare ``MODIFY data_quality VARCHAR(20)`` would silently drop NOT NULL and
    the DEFAULT -- v0012's lesson, kept.
    """
    return (
        f'ALTER TABLE {tableName} '
        f'MODIFY {DATA_QUALITY_COLUMN} VARCHAR({DATA_QUALITY_COLUMN_LENGTH}) '
        f"NOT NULL DEFAULT '{UNASSESSED_VALUE}';"
    )


MODIFY_IS_REAL_DEFAULT_NULL_DDL: str = (
    f'ALTER TABLE {DRIVE_SUMMARY_TABLE} '
    f'MODIFY {IS_REAL_COLUMN} TINYINT(1) NULL DEFAULT NULL;'
)

# CHANGE COLUMN, not RENAME COLUMN: RENAME COLUMN needs MariaDB >= 10.5.2 and
# CHANGE works on every version this project has ever deployed against.  The
# type is re-stated because CHANGE requires it.
RENAME_INTAKE_COLUMN_DDL: str = (
    f'ALTER TABLE {DRIVE_SUMMARY_TABLE} '
    f'CHANGE COLUMN {OLD_AMBIENT_COLUMN} {NEW_INTAKE_COLUMN} FLOAT NULL;'
)


# ================================================================================
# INFORMATION_SCHEMA probes -- SHARED with the applied-schema guard (A-4)
# ================================================================================


def discoverDataQualityDefaultsSql(dbName: str) -> str:
    """SQL listing ``(table, column, default)`` for EVERY data_quality column.

    Discovery-driven, in the shape v0023/US-458 established: the query asks the
    deployed schema which tables carry the column rather than hard-coding a
    list, so a table added tomorrow is covered without editing anything.  This
    is the durable half of the F-134 fix -- it is what stops the NEXT column
    defaulting to a verdict.
    """
    return (
        'SELECT TABLE_NAME, COLUMN_NAME, COLUMN_DEFAULT '
        'FROM information_schema.COLUMNS '
        f"WHERE TABLE_SCHEMA='{dbName}' "
        f"AND COLUMN_NAME='{DATA_QUALITY_COLUMN}' "
        'ORDER BY TABLE_NAME;'
    )


def discoverColumnDefaultSql(dbName: str, tableName: str, columnName: str) -> str:
    """SQL returning one column's ``COLUMN_DEFAULT`` (empty result = no column)."""
    return (
        'SELECT COLUMN_DEFAULT FROM information_schema.COLUMNS '
        f"WHERE TABLE_SCHEMA='{dbName}' "
        f"AND TABLE_NAME='{tableName}' "
        f"AND COLUMN_NAME='{columnName}';"
    )


def columnExistsSql(dbName: str, tableName: str, columnName: str) -> str:
    """SQL returning ``1`` when the column exists on the deployed schema."""
    return (
        'SELECT COUNT(*) FROM information_schema.COLUMNS '
        f"WHERE TABLE_SCHEMA='{dbName}' "
        f"AND TABLE_NAME='{tableName}' "
        f"AND COLUMN_NAME='{columnName}';"
    )


def normalizeAppliedDefault(raw: str) -> str | None:
    """Normalize a raw ``COLUMN_DEFAULT`` cell into the bare default value.

    MariaDB 10.2+ stores the default as an EXPRESSION, so a string default reads
    back quoted (``'full'``) while an absent / NULL default reads back as the
    literal ``NULL``.  ``mysql -B -N`` also renders a SQL NULL as ``NULL``, and
    the two are indistinguishable in that output -- which is fine here, because
    both mean the same thing to the caller: no default value was handed out.

    Returns ``None`` for "no default", else the unquoted default.  ``DEFAULT
    'NULL'`` (a four-character string) is deliberately NOT collapsed to
    ``None``: that is a column whose default is the word NULL, which is a value.
    """
    text = (raw or '').strip()
    if not text:
        return None
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1]
    if text.upper() == 'NULL':
        return None
    return text


def _checkClause(ctx: RunnerContext, constraintName: str) -> str | None:
    """Return the stored ``CHECK_CLAUSE`` for a named CHECK, or ``None``."""
    sql = (
        'SELECT CHECK_CLAUSE FROM information_schema.CHECK_CONSTRAINTS '
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


def _appliedDefault(
    ctx: RunnerContext, tableName: str, columnName: str,
) -> str | None:
    """Return one column's normalized applied DEFAULT."""
    sql = discoverColumnDefaultSql(ctx.creds.dbName, tableName, columnName)
    res = _runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'DEFAULT probe failed for {tableName}.{columnName}: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    return normalizeAppliedDefault(res.stdout)


def _columnExists(ctx: RunnerContext, tableName: str, columnName: str) -> bool:
    """Return True when the deployed schema carries the column."""
    sql = columnExistsSql(ctx.creds.dbName, tableName, columnName)
    res = _runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'column-existence probe failed for {tableName}.{columnName}: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    txt = res.stdout.strip()
    return bool(txt) and txt.split()[0] not in ('0', 'NULL')


def _requireTable(ctx: RunnerContext, tableName: str) -> None:
    if not serverTableExists(ctx.addrs, ctx.creds, tableName, ctx.runner):
        raise MigrationError(
            f'{tableName!r} table missing; v0024 cannot re-default its '
            f'{DATA_QUALITY_COLUMN!r} column.  Investigate why create_all + '
            f'earlier migrations did not land the table.',
        )


def _requireColumn(
    ctx: RunnerContext, tableName: str, columnName: str, substep: str,
) -> None:
    """Fail LOUDLY, with a diagnosis, when a table lacks a column v0024 needs.

    US-568.  Every table in :data:`_CHECK_TARGETS` / :data:`_DATA_QUALITY_TABLES`
    MUST carry the column -- that is an explicit, tested, table-by-table
    decision, not a caught exception.  There are NO carve-outs: the deployed
    obd2db carries ``data_quality`` on all three tables and ``is_real`` on
    ``drive_summary`` (measured 2026-08-23 via information_schema), so a missing
    column is never "this table legitimately opts out" -- it is always a broken
    schema, and the migration must stop.

    Why this exists rather than the raw engine error: without it MariaDB reports
    ``(1054, "Unknown column 'data_quality' in 'CHECK'")`` from inside the
    ADD CONSTRAINT, which names the symptom and hides the cause.  The cause is
    always the same -- the schema does not match the ledger that claims which
    migrations have been applied -- and that is what an operator needs told.

    It also closes a genuine silent-success hole in substep 2: ``_appliedDefault``
    returns ``None`` both for "column has no default" AND for "column does not
    exist", so ``_redefaultIsRealToNull`` would have read a MISSING ``is_real``
    as "already defaulting to NULL" and returned success having changed nothing.
    A non-measurement wearing the appearance of a measurement is the exact class
    F-135 / US-563 exist to eliminate.
    """
    if not _columnExists(ctx, tableName, columnName):
        raise MigrationError(
            f'{tableName}.{columnName} does not exist, so v0024 cannot '
            f'{substep}.  v0024 has no carve-out for a missing column: the '
            f'deployed schema carries it on every target table, so this is a '
            f'BROKEN SCHEMA, not an opt-out.  Almost always this means the '
            f'schema_migrations ledger claims an earlier migration ran when it '
            f'did not -- {tableName}.{columnName} is created by an earlier '
            f'migration in this registry.  Reconcile the ledger against the '
            f'actual schema before re-running; do NOT skip the table.',
        )


# ================================================================================
# Substep 1 -- widen the CHECK enums so 'unassessed' is a legal value
# ================================================================================


def _widenCheckWithUnassessed(
    ctx: RunnerContext,
    tableName: str,
    checkName: str,
    allowedValues: tuple[str, ...],
) -> None:
    """Add ``'unassessed'`` to one data_quality CHECK enum.

    Drops + re-adds the named constraint (MariaDB cannot widen in place).
    Idempotent: a stored clause that already contains the value -- a fresh
    ``create_all`` from the current ORM enum, or a prior run -- is a no-op.

    This MUST run before the DEFAULT is changed.  Setting a DEFAULT the CHECK
    forbids does not fail at ALTER time; it fails on the next INSERT that omits
    the column, i.e. on the next Pi sync, in the car.
    """
    _requireTable(ctx, tableName)
    _requireColumn(
        ctx, tableName, DATA_QUALITY_COLUMN,
        f'widen the {checkName!r} CHECK enum with {UNASSESSED_VALUE!r}',
    )

    clause = _checkClause(ctx, checkName)
    if clause is not None and UNASSESSED_VALUE in clause:
        return

    if clause is not None:
        res = _runServerSql(
            ctx.addrs, ctx.creds,
            f'ALTER TABLE {tableName} DROP CONSTRAINT {checkName};',
            ctx.runner,
        )
        if res.returncode != 0:
            raise MigrationError(
                f'drop CHECK {checkName!r} on {tableName!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    valuesSql = ','.join(f"'{v}'" for v in allowedValues)
    res = _runServerSql(
        ctx.addrs, ctx.creds,
        f'ALTER TABLE {tableName} ADD CONSTRAINT {checkName} '
        f'CHECK ({DATA_QUALITY_COLUMN} IN ({valuesSql}));',
        ctx.runner,
    )
    if res.returncode != 0:
        err = (res.stderr.strip() or res.stdout.strip()).lower()
        if 'duplicate' not in err and 'already exists' not in err:
            raise MigrationError(
                f'add CHECK {checkName!r} on {tableName!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    clauseAfter = _checkClause(ctx, checkName)
    if clauseAfter is None or UNASSESSED_VALUE not in clauseAfter:
        raise SchemaProbeError(
            f'{checkName!r} CHECK_CLAUSE does not contain '
            f'{UNASSESSED_VALUE!r} after rebuild ran; investigate the MariaDB '
            f'session context (wrong default DB / filtered replica).',
        )


# ================================================================================
# Substep 2 -- re-default the verdict columns
# ================================================================================


def _redefaultDataQuality(ctx: RunnerContext, tableName: str) -> None:
    """Re-default one ``data_quality`` column to the non-verdict.

    Idempotent: a column already defaulting to ``'unassessed'`` is a no-op.
    """
    _requireTable(ctx, tableName)
    _requireColumn(
        ctx, tableName, DATA_QUALITY_COLUMN,
        f're-default it to {UNASSESSED_VALUE!r}',
    )

    if _appliedDefault(ctx, tableName, DATA_QUALITY_COLUMN) == UNASSESSED_VALUE:
        return

    res = _runServerSql(
        ctx.addrs, ctx.creds, _modifyDataQualityDefaultDdl(tableName), ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f're-default {tableName}.{DATA_QUALITY_COLUMN} to '
            f'{UNASSESSED_VALUE!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    after = _appliedDefault(ctx, tableName, DATA_QUALITY_COLUMN)
    if after != UNASSESSED_VALUE:
        raise SchemaProbeError(
            f'{tableName}.{DATA_QUALITY_COLUMN} DEFAULT is {after!r} after '
            f'MODIFY ran (expected {UNASSESSED_VALUE!r}); investigate the '
            f'MariaDB session context.',
        )


def _redefaultIsRealToNull(ctx: RunnerContext) -> None:
    """Drop ``drive_summary.is_real``'s DEFAULT 0 so it defaults to NULL."""
    _requireTable(ctx, DRIVE_SUMMARY_TABLE)
    # MUST precede the _appliedDefault read: that probe cannot tell "no default"
    # from "no column", so without this a missing is_real would report success.
    _requireColumn(
        ctx, DRIVE_SUMMARY_TABLE, IS_REAL_COLUMN, 'drop its DEFAULT 0',
    )

    if _appliedDefault(ctx, DRIVE_SUMMARY_TABLE, IS_REAL_COLUMN) is None:
        return

    res = _runServerSql(
        ctx.addrs, ctx.creds, MODIFY_IS_REAL_DEFAULT_NULL_DDL, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f're-default {DRIVE_SUMMARY_TABLE}.{IS_REAL_COLUMN} to NULL '
            f'failed: {res.stderr.strip() or res.stdout.strip()}',
        )

    after = _appliedDefault(ctx, DRIVE_SUMMARY_TABLE, IS_REAL_COLUMN)
    if after is not None:
        raise SchemaProbeError(
            f'{DRIVE_SUMMARY_TABLE}.{IS_REAL_COLUMN} DEFAULT is {after!r} '
            f'after MODIFY ran (expected NULL); investigate the MariaDB '
            f'session context.',
        )


# ================================================================================
# Substep 3 -- the rename
# ================================================================================


def _renameAmbientToIntakeAir(ctx: RunnerContext) -> None:
    """Rename ``ambient_temp_at_start_c`` -> ``intake_air_temp_at_start_c``.

    Three states, all handled:

    * new column present, old absent -> already renamed (fresh ``create_all``
      from the current ORM, or a prior run).  No-op.
    * old present -> CHANGE COLUMN, then verify.
    * NEITHER present -> hard error.  A drive_summary with no drive-start IAT
      column at all is a shape nobody expects, and silently continuing would
      leave the operator believing the rename landed.
    """
    _requireTable(ctx, DRIVE_SUMMARY_TABLE)

    hasNew = _columnExists(ctx, DRIVE_SUMMARY_TABLE, NEW_INTAKE_COLUMN)
    hasOld = _columnExists(ctx, DRIVE_SUMMARY_TABLE, OLD_AMBIENT_COLUMN)

    if hasNew and not hasOld:
        return
    if hasNew and hasOld:
        raise MigrationError(
            f'{DRIVE_SUMMARY_TABLE} carries BOTH {OLD_AMBIENT_COLUMN!r} and '
            f'{NEW_INTAKE_COLUMN!r}.  Two live spellings of one reading is the '
            f'state this rename exists to prevent; v0024 will not guess which '
            f'holds the real values.  Investigate by hand.',
        )
    if not hasOld:
        raise MigrationError(
            f'{DRIVE_SUMMARY_TABLE} carries neither {OLD_AMBIENT_COLUMN!r} nor '
            f'{NEW_INTAKE_COLUMN!r}; v0024 cannot rename a column that is not '
            f'there.  Investigate the table shape (v0004 should have added it).',
        )

    res = _runServerSql(ctx.addrs, ctx.creds, RENAME_INTAKE_COLUMN_DDL, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'rename {DRIVE_SUMMARY_TABLE}.{OLD_AMBIENT_COLUMN} -> '
            f'{NEW_INTAKE_COLUMN} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    if not _columnExists(ctx, DRIVE_SUMMARY_TABLE, NEW_INTAKE_COLUMN):
        raise SchemaProbeError(
            f'{DRIVE_SUMMARY_TABLE}.{NEW_INTAKE_COLUMN} absent after CHANGE '
            f'COLUMN ran; investigate the MariaDB session context.',
        )
    if _columnExists(ctx, DRIVE_SUMMARY_TABLE, OLD_AMBIENT_COLUMN):
        raise SchemaProbeError(
            f'{DRIVE_SUMMARY_TABLE}.{OLD_AMBIENT_COLUMN} still present after '
            f'CHANGE COLUMN ran -- the mislabeled name survives alongside the '
            f'honest one.  Investigate before any consumer re-points.',
        )


# ================================================================================
# Entry point
# ================================================================================


def apply(ctx: RunnerContext) -> None:
    """Apply the three F-134 schema truths (US-563).

    Ordering is load-bearing: every CHECK is widened BEFORE any DEFAULT moves,
    so there is no window in which the column's own default would be rejected
    by its own constraint.
    """
    for tableName, checkName, allowedValues in _CHECK_TARGETS:
        _widenCheckWithUnassessed(ctx, tableName, checkName, allowedValues)

    for tableName in _DATA_QUALITY_TABLES:
        _redefaultDataQuality(ctx, tableName)

    _redefaultIsRealToNull(ctx)
    _renameAmbientToIntakeAir(ctx)


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
