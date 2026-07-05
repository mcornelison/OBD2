################################################################################
# File Name: v0022_us451_drive_identity_collapse.py
# Purpose/Description: US-451 registry migration (F-104 / D-8 drive-identity
#                      collapse) -- the migration-order-LAST step of the
#                      server-analytics-authority spine.  Three forward-only,
#                      individually-idempotent substeps on live MariaDB:
#                        (1) widen the drives.data_quality CHECK to admit the
#                            new 'unmappable_legacy' marker (v0015 idiom);
#                        (2) flag unmappable legacy drives (source_drive_id IS
#                            NULL, still the default 'full') as
#                            'unmappable_legacy' -- one row per distinct legacy
#                            key, never dropped/merged, foreign_vehicle preserved;
#                        (3) re-point the drive_statistics.summary_id +
#                            drive_derived_signals.summary_id FKs from
#                            drive_summary.id to the canonical drives.drive_id
#                            (US-448 subsume already aligned the values, so this
#                            is 0-orphan for existing rows; it absorbs the
#                            US-460 harness-mint divergence for new drives).
#                      Deps US-460 (the harness mint must be live before the FK
#                      re-point, else new-drive stat writes orphan on deploy).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-05    | Rex (US-451) | Initial -- Sprint 55 US-451 (F-104 / D-8).
# ================================================================================
################################################################################

"""Migration 0022: collapse the drive-identity id-families (US-451 / F-104 D-8).

The F-104 spine ends here: every table carrying a drive-identity reference now
points at the single canonical identity ``drives.drive_id`` (US-448), the Pi's
own id survives only as advisory ``drives.source_drive_id``, and unmappable
legacy drives are honestly typed rather than dropped.

Three substeps, each individually idempotent (safe to replay on an
already-migrated DB; the MigrationRunner also records the version on first
success and skips subsequent runs):

1. **Widen the ``ck_drives_data_quality`` CHECK** with ``'unmappable_legacy'``.
   MariaDB cannot widen a CHECK in place, so the named constraint is dropped and
   re-added from the ORM enum tuple (``DRIVES_DATA_QUALITY_VALUES``, A-4
   define-once).  Idempotent via an ``INFORMATION_SCHEMA.CHECK_CONSTRAINTS``
   probe: a fresh ``create_all`` DB (whose ORM already declares the widened
   enum) or a prior run is a no-op.

2. **Flag unmappable legacy drives.**  ``UPDATE drives SET
   data_quality='unmappable_legacy' WHERE source_drive_id IS NULL AND
   data_quality='full'``.  A ``drives`` row has ``source_drive_id IS NULL`` only
   when its advisory Pi natural key is absent (pre-``connection_log`` drives
   1-12, NULL-``drive_id`` raw) -- exactly the rows that cannot be re-keyed to a
   Pi identity.  The ``data_quality='full'`` guard PRESERVES a more-specific
   existing marker (a NULL-key foreign_vehicle or attribution_anomaly row keeps
   its flag -- precedence: specific-fact over unmappable).  The v0018 subsume
   already created one ``drives`` row per legacy drive (NULLs are distinct under
   the UNIQUE natural key), so nothing is merged: this only re-labels.
   Idempotent -- a replay matches 0 rows (already-flagged rows are no longer
   ``'full'``); a zero-survivor post-probe guards against a silent no-op.

3. **Re-point the summary_id FKs -> ``drives.drive_id``.**  For
   ``drive_statistics`` and ``drive_derived_signals`` the current FK on
   ``summary_id`` (auto-named by ``create_all`` on ``drive_statistics``;
   ``fk_drive_derived_signals_summary`` on ``drive_derived_signals`` from v0017)
   is discovered by name via ``INFORMATION_SCHEMA.KEY_COLUMN_USAGE``, dropped,
   and re-added as a named FK referencing ``drives(drive_id)`` ON DELETE
   CASCADE.  Because v0018 subsumed ``drive_summary.id`` INTO ``drives.drive_id``
   (identical values), every existing ``summary_id`` value already exists in
   ``drives`` -- the ADD validates 0 orphans.  Idempotent: if the FK already
   references ``drives`` the substep is a no-op.

**Not done here (scope + safety, documented for PM/Atlas):**

* ``drive_annotations`` -- the AC names it, but no such table/ORM model exists
  in ``src/server``; it is a no-op (nothing to re-point).
* A hard ``drive_summary.id -> drives.drive_id`` FK is deliberately NOT added.
  ``drive_summary`` links to ``drives`` by the *natural key*
  (``source_device``, ``source_id``) <-> (``source_device``, ``source_drive_id``),
  NOT by its PK: (a) the US-214 contract inserts the ``drive_summary`` row FIRST,
  before the harness mints ``drives`` (models.py DriveSummary docstring), so a
  hard FK would fail the sync insert; (b) for a NEW harness-derived drive the
  minted ``drives.drive_id`` is an INDEPENDENT autoincrement, divergent from
  ``drive_summary.id`` (US-460) -- a ``drive_summary.id -> drives.drive_id`` FK
  would point the new row at an unrelated OLD subsumed drive.  The identity
  collapse for ``drive_summary`` is realized by the v0018 subsume (its id IS the
  canonical id for historical rows) + the child re-points above.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    serverTableExists,
)
from src.server.db.models import (
    DRIVES_DATA_QUALITY_UNMAPPABLE_LEGACY,
    DRIVES_DATA_QUALITY_VALUES,
    DRIVES_TABLE,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'ADD_DRIVE_DERIVED_SIGNALS_FK_DDL',
    'ADD_DRIVE_STATISTICS_FK_DDL',
    'ADD_DRIVES_CHECK_DDL',
    'DESCRIPTION',
    'DRIVES_CHECK_NAME',
    'DRIVE_DERIVED_SIGNALS_FK_NAME',
    'DRIVE_DERIVED_SIGNALS_TABLE',
    'DRIVE_STATISTICS_FK_NAME',
    'DRIVE_STATISTICS_TABLE',
    'DROP_DRIVES_CHECK_DDL',
    'FLAG_UNMAPPABLE_LEGACY_DDL',
    'MIGRATION',
    'VERSION',
    'apply',
]


VERSION: str = '0022'
DESCRIPTION: str = (
    'US-451 F-104/D-8 drive-identity collapse -- widen drives.data_quality CHECK '
    "with 'unmappable_legacy' + flag NULL-natural-key legacy drives + re-point "
    'drive_statistics/drive_derived_signals summary_id FKs to drives.drive_id'
)


# ---- Identifiers (match models.py + v0018 so SHOW CREATE TABLE is portable) --

DRIVE_STATISTICS_TABLE: str = 'drive_statistics'
DRIVE_DERIVED_SIGNALS_TABLE: str = 'drive_derived_signals'
DRIVES_CHECK_NAME: str = 'ck_drives_data_quality'
# New FK constraint names -- must match the models.py ForeignKey(name=...) so the
# ORM (SQLite create_all) and this ALTER (MariaDB) converge on one schema.
DRIVE_STATISTICS_FK_NAME: str = 'fk_drive_statistics_drives'
DRIVE_DERIVED_SIGNALS_FK_NAME: str = 'fk_drive_derived_signals_drives'
_SUMMARY_FK_COLUMN: str = 'summary_id'
_LEGACY_REFERENCED_TABLE: str = 'drive_summary'


# ---- Substep 1: widen the drives.data_quality CHECK -------------------------

# Build the CHECK enum list from the ORM tuple (A-4 define-once): a future enum
# change trips the DDL-parity tests instead of silently diverging.
_DRIVES_ALLOWED_VALUES_SQL: str = ','.join(
    f"'{v}'" for v in DRIVES_DATA_QUALITY_VALUES
)
DROP_DRIVES_CHECK_DDL: str = (
    f'ALTER TABLE {DRIVES_TABLE} DROP CONSTRAINT {DRIVES_CHECK_NAME};'
)
ADD_DRIVES_CHECK_DDL: str = (
    f'ALTER TABLE {DRIVES_TABLE} ADD CONSTRAINT {DRIVES_CHECK_NAME} '
    f'CHECK (data_quality IN ({_DRIVES_ALLOWED_VALUES_SQL}));'
)


# ---- Substep 2: flag unmappable legacy drives -------------------------------

FLAG_UNMAPPABLE_LEGACY_DDL: str = (
    f"UPDATE {DRIVES_TABLE} SET data_quality="
    f"'{DRIVES_DATA_QUALITY_UNMAPPABLE_LEGACY}' "
    "WHERE source_drive_id IS NULL AND data_quality='full';"
)


# ---- Substep 3: FK re-point DDLs (ADD; the DROP name is discovered) ----------

ADD_DRIVE_STATISTICS_FK_DDL: str = (
    f'ALTER TABLE {DRIVE_STATISTICS_TABLE} '
    f'ADD CONSTRAINT {DRIVE_STATISTICS_FK_NAME} '
    f'FOREIGN KEY ({_SUMMARY_FK_COLUMN}) REFERENCES {DRIVES_TABLE}(drive_id) '
    'ON DELETE CASCADE;'
)
ADD_DRIVE_DERIVED_SIGNALS_FK_DDL: str = (
    f'ALTER TABLE {DRIVE_DERIVED_SIGNALS_TABLE} '
    f'ADD CONSTRAINT {DRIVE_DERIVED_SIGNALS_FK_NAME} '
    f'FOREIGN KEY ({_SUMMARY_FK_COLUMN}) REFERENCES {DRIVES_TABLE}(drive_id) '
    'ON DELETE CASCADE;'
)


# ---- INFORMATION_SCHEMA probes ----------------------------------------------


def _checkClause(ctx: RunnerContext, constraintName: str) -> str | None:
    """Return the stored ``CHECK_CLAUSE`` for a named CHECK, or ``None``.

    ``None`` means the constraint does not exist (no row).  Mirrors v0015.
    """
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


def _fkNameReferencing(
    ctx: RunnerContext, tableName: str, referencedTable: str,
) -> str | None:
    """Return the FK constraint name on ``tableName.summary_id`` referencing
    ``referencedTable``, or ``None`` when no such FK exists.

    Discovering the name (rather than hard-coding it) handles both the
    ``create_all`` auto-named FK on ``drive_statistics`` and the explicitly
    named FK on ``drive_derived_signals`` (v0017), and makes the re-point
    idempotent: after the re-point the drive_summary-referencing FK is gone and
    the drives-referencing FK is present.
    """
    sql = (
        'SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE '
        f"WHERE TABLE_SCHEMA='{ctx.creds.dbName}' "
        f"AND TABLE_NAME='{tableName}' "
        f"AND COLUMN_NAME='{_SUMMARY_FK_COLUMN}' "
        f"AND REFERENCED_TABLE_NAME='{referencedTable}';"
    )
    res = _runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'FK-name probe failed for {tableName}.{_SUMMARY_FK_COLUMN} -> '
            f'{referencedTable}: {res.stderr.strip() or res.stdout.strip()}',
        )
    name = res.stdout.strip()
    # Guard against a multi-row / malformed result: take the first token only.
    return name.split()[0] if name else None


# ---- Substeps ---------------------------------------------------------------


def _widenDrivesDataQualityCheck(ctx: RunnerContext) -> None:
    """Widen ``ck_drives_data_quality`` with 'unmappable_legacy' (v0015 idiom)."""
    if not serverTableExists(ctx.addrs, ctx.creds, DRIVES_TABLE, ctx.runner):
        raise MigrationError(
            f'{DRIVES_TABLE!r} table missing; v0022 cannot widen its '
            'data_quality CHECK.  Investigate why v0018 (create drives) did '
            'not land.',
        )

    clause = _checkClause(ctx, DRIVES_CHECK_NAME)
    if clause is not None and DRIVES_DATA_QUALITY_UNMAPPABLE_LEGACY in clause:
        # Already widened (fresh create_all from the widened ORM enum, or a
        # prior run).  No-op.
        return

    if clause is not None:
        res = _runServerSql(ctx.addrs, ctx.creds, DROP_DRIVES_CHECK_DDL, ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'drop CHECK {DRIVES_CHECK_NAME!r} on {DRIVES_TABLE!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    res = _runServerSql(ctx.addrs, ctx.creds, ADD_DRIVES_CHECK_DDL, ctx.runner)
    if res.returncode != 0:
        err = (res.stderr.strip() or res.stdout.strip()).lower()
        if 'duplicate' not in err and 'already exists' not in err:
            raise MigrationError(
                f'add CHECK {DRIVES_CHECK_NAME!r} on {DRIVES_TABLE!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    clauseAfter = _checkClause(ctx, DRIVES_CHECK_NAME)
    if (
        clauseAfter is None
        or DRIVES_DATA_QUALITY_UNMAPPABLE_LEGACY not in clauseAfter
    ):
        raise SchemaProbeError(
            f'{DRIVES_CHECK_NAME!r} CHECK_CLAUSE does not contain '
            f'{DRIVES_DATA_QUALITY_UNMAPPABLE_LEGACY!r} after rebuild ran; '
            'investigate the MariaDB session context.',
        )


def _flagUnmappableLegacy(ctx: RunnerContext) -> None:
    """Re-label NULL-natural-key default drives as 'unmappable_legacy'.

    Idempotent: a replay updates 0 rows (already-flagged rows are no longer
    ``'full'``).  A zero-survivor post-probe raises if the UPDATE silently
    no-op'd on a still-populated set (wrong DB context).
    """
    res = _runServerSql(
        ctx.addrs, ctx.creds, FLAG_UNMAPPABLE_LEGACY_DDL, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'flag unmappable-legacy drives on {DRIVES_TABLE!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    probe = (
        f'SELECT COUNT(*) FROM {DRIVES_TABLE} '
        "WHERE source_drive_id IS NULL AND data_quality='full';"
    )
    res = _runServerSql(ctx.addrs, ctx.creds, probe, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'unmappable-legacy post-probe failed on {DRIVES_TABLE!r}: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    survivors = res.stdout.strip()
    if survivors and survivors.split()[0] != '0':
        raise SchemaProbeError(
            f'{survivors.split()[0]} NULL-natural-key drives still carry '
            "data_quality='full' after the flag UPDATE ran; investigate the "
            'MariaDB session context.',
        )


def _repointSummaryFk(
    ctx: RunnerContext, tableName: str, newFkName: str, addDdl: str,
) -> None:
    """Re-point ``tableName.summary_id`` FK from drive_summary -> drives.

    Idempotent + name-discovering: if the FK already references ``drives`` the
    substep is a no-op; if it still references ``drive_summary`` the stale FK is
    dropped by its discovered name and the drives-referencing FK re-added.
    """
    if not serverTableExists(ctx.addrs, ctx.creds, tableName, ctx.runner):
        raise MigrationError(
            f'{tableName!r} table missing; v0022 cannot re-point its '
            f'{_SUMMARY_FK_COLUMN} FK.  Investigate why create_all + earlier '
            'migrations did not land the table.',
        )

    staleName = _fkNameReferencing(ctx, tableName, _LEGACY_REFERENCED_TABLE)
    if staleName is None:
        # No drive_summary-referencing FK -> either already re-pointed, or the
        # FK is missing entirely.  The drives-referencing FK MUST exist.
        if _fkNameReferencing(ctx, tableName, DRIVES_TABLE) is None:
            raise SchemaProbeError(
                f'{tableName}.{_SUMMARY_FK_COLUMN} references neither '
                f'{_LEGACY_REFERENCED_TABLE} nor {DRIVES_TABLE}; the expected '
                'FK is missing.  Investigate the MariaDB session context.',
            )
        return  # already re-pointed -- no-op

    dropDdl = (
        f'ALTER TABLE {tableName} DROP FOREIGN KEY {staleName};'
    )
    res = _runServerSql(ctx.addrs, ctx.creds, dropDdl, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'drop stale FK {staleName!r} on {tableName!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    res = _runServerSql(ctx.addrs, ctx.creds, addDdl, ctx.runner)
    if res.returncode != 0:
        err = (res.stderr.strip() or res.stdout.strip()).lower()
        if 'duplicate' not in err and 'already exists' not in err:
            raise MigrationError(
                f'add FK {newFkName!r} on {tableName!r} -> {DRIVES_TABLE} '
                f'failed: {res.stderr.strip() or res.stdout.strip()}',
            )

    # Post-condition probe: the FK must now reference drives.
    if _fkNameReferencing(ctx, tableName, DRIVES_TABLE) is None:
        raise SchemaProbeError(
            f'{tableName}.{_SUMMARY_FK_COLUMN} does not reference '
            f'{DRIVES_TABLE} after the re-point ran; investigate the MariaDB '
            'session context.',
        )


def apply(ctx: RunnerContext) -> None:
    """Collapse the drive-identity id-families onto ``drives.drive_id``.

    Ordering is load-bearing: the CHECK widen (1) must precede the legacy flag
    (2) so the new value is permitted; the FK re-points (3) are independent.
    Each substep is individually idempotent, so replaying the whole migration on
    an already-migrated DB is a safe no-op.
    """
    _widenDrivesDataQualityCheck(ctx)
    _flagUnmappableLegacy(ctx)
    _repointSummaryFk(
        ctx,
        DRIVE_STATISTICS_TABLE,
        DRIVE_STATISTICS_FK_NAME,
        ADD_DRIVE_STATISTICS_FK_DDL,
    )
    _repointSummaryFk(
        ctx,
        DRIVE_DERIVED_SIGNALS_TABLE,
        DRIVE_DERIVED_SIGNALS_FK_NAME,
        ADD_DRIVE_DERIVED_SIGNALS_FK_DDL,
    )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
