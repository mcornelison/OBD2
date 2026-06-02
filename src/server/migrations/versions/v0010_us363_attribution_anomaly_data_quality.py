################################################################################
# File Name: v0010_us363_attribution_anomaly_data_quality.py
# Purpose/Description: Sprint 43 V0.28.0 schema pass -- migration v0010.  This is
#                      the SINGLE v0010 migration the V0.28.0 sprint shares
#                      across its schema stories; each story appends its own
#                      substep function to apply().  US-363 (F-107) lands the
#                      first substep: the data_quality='attribution_anomaly'
#                      tripwire schema --
#                        (a) ADD COLUMN data_quality (+ CHECK + index) to
#                            drive_summary (the table had no data_quality column
#                            at all), and
#                        (b) extend the existing drive_statistics data_quality
#                            CHECK enum (full/sparse/below_threshold) with
#                            'attribution_anomaly' via DROP + re-ADD CONSTRAINT.
#                      Mirrors v0009's INFORMATION_SCHEMA-probe idempotency so a
#                      partial-success re-run, an already-migrated production DB,
#                      and a fresh ``Base.metadata.create_all`` DB all converge.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-363) | Initial -- F-107 attribution-anomaly tripwire
#               |              | schema substep.  drive_summary.data_quality
#               |              | ADD COLUMN + CHECK + index; drive_statistics
#               |              | CHECK enum extended with 'attribution_anomaly'.
# 2026-05-28    | Rex (US-371) | F-076 substep: rename the drive_statistics
#               |              | drive_id column -> summary_id (RENAME COLUMN;
#               |              | idempotent column probe; complete, no alias).
# 2026-05-28    | Rex (US-365) | F-108 substep: vehicle_info ECU-lineage columns
#               |              | (ecu_signature/cal_signature/install/removal/
#               |              | notes) + STORED ecu_active_marker generated
#               |              | column + UNIQUE index (single-active ECU);
#               |              | legacy backfill with PRE_TRACKING_UNKNOWN
#               |              | sentinel; runs before any US-370 FK substep.
# 2026-05-28    | Rex (US-368) | F-109 substep: CREATE dtc_freeze_frame capture
#               |              | table (Mode 02 freeze-frame; FK dtc_log.id +
#               |              | vehicle_info.id).  New table -> CREATE TABLE IF
#               |              | NOT EXISTS (v0005 pattern); runs after the
#               |              | vehicle_info substep (FK target).
# ================================================================================
################################################################################

"""Migration 0010: V0.28.0 schema pass (US-363 attribution-anomaly first).

Context (US-363 / F-107)
------------------------
The V0.27.18 IRL drill (2026-05-22) surfaced a Pi-side DriveDetector defect
that minted two ``drive_id``s for one physical leg (drives 23 + 24).  US-362
landed :func:`src.server.analytics.overlap.detect_overlapping_drives`, the
SSOT detector over raw ``realtime_data``.  US-363 wires that detector into
both server compute paths so an overlapping drive is stamped
``data_quality='attribution_anomaly'`` and the dual-emission pattern becomes
observable downstream as a per-row flag (observability, not refusal).

Two schema surfaces are needed:

* ``drive_summary`` had **no** ``data_quality`` column at all.  This migration
  ADDs it (``VARCHAR(16) NOT NULL DEFAULT 'full'``) with a CHECK enforcing the
  ``{full, attribution_anomaly}`` enum and an index, mirroring the v0009
  column shape exactly so SHOW CREATE TABLE is identical across environments.
* ``drive_statistics`` already had a ``data_quality`` CHECK enum
  (``full/sparse/below_threshold``, added by v0009).  MariaDB cannot widen a
  CHECK in place, so this migration DROPs and re-ADDs the named constraint with
  the extra ``'attribution_anomaly'`` value.

Shared-migration contract
--------------------------
v0010 is the ONE migration the V0.28.0 sprint shares.  Later schema stories
(US-365 vehicle_info, US-368 dtc_freeze_frame, US-370 speed_pid_calibration,
US-371 rename, US-372 drive_summary CHECK) append their own ``_applyUsNNN``
substep function and call it from :func:`apply` in story order.  Substep order
matters where FKs cross stories (e.g. US-370 FKs US-365's column); document any
such dependency in the substep docstring per Atlas Refinements row 16.

Idempotency contract
--------------------
Each substep probes INFORMATION_SCHEMA before issuing DDL:

1. The drive_summary column / CHECK / index are added only when missing --
   covers fresh-DB ``create_all`` (the ORM already declares all three), prior
   successful runs, and partial-success recovery.
2. The drive_statistics CHECK is rebuilt only when its stored ``CHECK_CLAUSE``
   does not already contain ``attribution_anomaly`` -- so a fresh ``create_all``
   DB (ORM CHECK already carries the 4-value enum) and a re-run are both no-ops.

Post-condition probes re-read INFORMATION_SCHEMA and raise
:class:`SchemaProbeError` if the expected shape is absent -- the silent mysql
session-context bug class (wrong default DB, filtered replica) that prompted
the post-probe pattern in v0002/v0004/v0005/v0008/v0009.

Reversibility
-------------
ADD COLUMN and ADD CONSTRAINT are non-destructive (existing drive_summary rows
take the ``'full'`` default; the drive_statistics CHECK widens, never narrows).
No down-migration ships; rollback is "snapshot + redeploy prior version" per
the runner's documented design.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    indexExists,
    probeServerColumns,
    serverTableExists,
)
from src.server.db.models import (
    DATA_QUALITY_ATTRIBUTION_ANOMALY,
    DRIVE_STATISTICS_DATA_QUALITY_VALUES,
    DRIVE_SUMMARY_DATA_QUALITY_DEFAULT,
    DRIVE_SUMMARY_DATA_QUALITY_VALUES,
    DRIVE_SUMMARY_DRIVE_ID_CHECK_CLAUSE,
    DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME,
    SPEED_PID_CALIBRATION_CAPTURE_METHOD_CHECK_NAME,
    SPEED_PID_CALIBRATION_CAPTURE_METHOD_VALUES,
    SPEED_PID_CALIBRATION_ECU_SIGNATURE_LENGTH,
    SPEED_PID_CALIBRATION_ECU_SIGNATURE_UNIQUE,
    SPEED_PID_CALIBRATION_TABLE,
    VEHICLE_INFO_ACTIVE_MARKER_COLUMN,
    VEHICLE_INFO_ACTIVE_MARKER_EXPR,
    VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN,
    VEHICLE_INFO_SINGLE_ACTIVE_INDEX,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'ADD_DRIVE_STATISTICS_CHECK_DDL',
    'ADD_DRIVE_SUMMARY_CHECK_DDL',
    'ADD_DRIVE_SUMMARY_COLUMN_DDL',
    'ADD_DRIVE_SUMMARY_DRIVE_ID_CHECK_DDL',
    'ADD_DRIVE_SUMMARY_INDEX_DDL',
    'BACKFILL_DRIVE_SUMMARY_DRIVE_ID_FROM_SOURCE_DDL',
    'BACKFILL_DRIVE_SUMMARY_SOURCE_ID_FROM_DRIVE_DDL',
    'DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME',
    'ADD_VEHICLE_INFO_ACTIVE_MARKER_DDL',
    'ADD_VEHICLE_INFO_CAL_SIGNATURE_DDL',
    'ADD_VEHICLE_INFO_ECU_INSTALL_DDL',
    'ADD_VEHICLE_INFO_ECU_REMOVAL_DDL',
    'ADD_VEHICLE_INFO_ECU_SIGNATURE_DDL',
    'ADD_VEHICLE_INFO_NOTES_DDL',
    'ADD_VEHICLE_INFO_SINGLE_ACTIVE_INDEX_DDL',
    'BACKFILL_VEHICLE_INFO_LEGACY_DDL',
    'CREATE_DTC_FREEZE_FRAME_DDL',
    'DTC_FREEZE_FRAME_TABLE',
    'DESCRIPTION',
    'DROP_DRIVE_STATISTICS_CHECK_DDL',
    'DRIVE_STATISTICS_CHECK_NAME',
    'DRIVE_STATISTICS_OLD_DRIVE_ID_COLUMN',
    'DRIVE_STATISTICS_SUMMARY_ID_COLUMN',
    'DRIVE_STATISTICS_TABLE',
    'DRIVE_SUMMARY_CHECK_NAME',
    'DRIVE_SUMMARY_COLUMN',
    'DRIVE_SUMMARY_INDEX_NAME',
    'DRIVE_SUMMARY_TABLE',
    'MIGRATION',
    'MODIFY_VEHICLE_INFO_ECU_INSTALL_NOT_NULL_DDL',
    'MODIFY_VEHICLE_INFO_ECU_SIGNATURE_NOT_NULL_DDL',
    'RENAME_DRIVE_STATISTICS_COLUMN_DDL',
    'CREATE_SPEED_PID_CALIBRATION_DDL',
    'SEED_NEW_ECU_SPEED_PID_CALIBRATION_DDL',
    'SEED_PRIOR_ECU_SPEED_PID_CALIBRATION_DDL',
    'SPEED_PID_CALIBRATION_TABLE',
    'VEHICLE_INFO_ACTIVE_MARKER_COLUMN',
    'VEHICLE_INFO_SINGLE_ACTIVE_INDEX',
    'VEHICLE_INFO_TABLE',
    'VERSION',
    'apply',
]


VERSION: str = '0010'
DESCRIPTION: str = (
    'US-363 F-107 attribution-anomaly tripwire -- drive_summary.data_quality '
    'ADD COLUMN + drive_statistics CHECK enum extended with '
    "'attribution_anomaly' (V0.28.0 schema pass)"
)


# ---- drive_summary identifiers + DDLs (mirror v0009 column shape) -----------

DRIVE_SUMMARY_TABLE: str = 'drive_summary'
DRIVE_SUMMARY_COLUMN: str = 'data_quality'
DRIVE_SUMMARY_CHECK_NAME: str = 'ck_drive_summary_data_quality'
DRIVE_SUMMARY_INDEX_NAME: str = 'idx_drive_summary_data_quality'

# Build the CHECK enum list from the model's exported tuple so a future
# ORM-side change trips the DDL-parity test rather than silently diverging.
_DRIVE_SUMMARY_ALLOWED_VALUES_SQL: str = ','.join(
    f"'{v}'" for v in DRIVE_SUMMARY_DATA_QUALITY_VALUES
)

ADD_DRIVE_SUMMARY_COLUMN_DDL: str = (
    f"ALTER TABLE {DRIVE_SUMMARY_TABLE} "
    f"ADD COLUMN {DRIVE_SUMMARY_COLUMN} VARCHAR(16) NOT NULL "
    f"DEFAULT '{DRIVE_SUMMARY_DATA_QUALITY_DEFAULT}';"
)
ADD_DRIVE_SUMMARY_CHECK_DDL: str = (
    f"ALTER TABLE {DRIVE_SUMMARY_TABLE} "
    f"ADD CONSTRAINT {DRIVE_SUMMARY_CHECK_NAME} "
    f"CHECK ({DRIVE_SUMMARY_COLUMN} IN ({_DRIVE_SUMMARY_ALLOWED_VALUES_SQL}));"
)
ADD_DRIVE_SUMMARY_INDEX_DDL: str = (
    f"ALTER TABLE {DRIVE_SUMMARY_TABLE} "
    f"ADD INDEX {DRIVE_SUMMARY_INDEX_NAME} ({DRIVE_SUMMARY_COLUMN});"
)


# ---- drive_statistics CHECK-rebuild identifiers + DDLs ----------------------

DRIVE_STATISTICS_TABLE: str = 'drive_statistics'
DRIVE_STATISTICS_CHECK_NAME: str = 'ck_drive_statistics_data_quality'

_DRIVE_STATISTICS_ALLOWED_VALUES_SQL: str = ','.join(
    f"'{v}'" for v in DRIVE_STATISTICS_DATA_QUALITY_VALUES
)

# MariaDB cannot widen a CHECK in place; drop the v0009-era 3-value constraint
# and re-add it with the 'attribution_anomaly' value included.
DROP_DRIVE_STATISTICS_CHECK_DDL: str = (
    f"ALTER TABLE {DRIVE_STATISTICS_TABLE} "
    f"DROP CONSTRAINT {DRIVE_STATISTICS_CHECK_NAME};"
)
ADD_DRIVE_STATISTICS_CHECK_DDL: str = (
    f"ALTER TABLE {DRIVE_STATISTICS_TABLE} "
    f"ADD CONSTRAINT {DRIVE_STATISTICS_CHECK_NAME} "
    f"CHECK (data_quality IN ({_DRIVE_STATISTICS_ALLOWED_VALUES_SQL}));"
)


# ---- US-371 drive_statistics column rename (drive_id -> summary_id) ----------
#
# The column has ALWAYS held a ``drive_summary.id`` FK (server-minted PK), never
# a Pi-assigned drive_id, so the old name lied to readers.  US-371 renames it
# (COMPLETE, no alias).  MariaDB 10.5.2+ supports ``RENAME COLUMN`` and carries
# the composite PK + the ``drive_summary.id`` FK over to the new name
# automatically.  Fallback if a target ever predates 10.5.2 (per
# conditionalOutcome 2): ``CHANGE drive_id summary_id INT NOT NULL`` (still no
# alias) -- not emitted here because chi-srv-01 runs MariaDB >= 10.5.

DRIVE_STATISTICS_OLD_DRIVE_ID_COLUMN: str = 'drive_id'
DRIVE_STATISTICS_SUMMARY_ID_COLUMN: str = 'summary_id'

RENAME_DRIVE_STATISTICS_COLUMN_DDL: str = (
    f"ALTER TABLE {DRIVE_STATISTICS_TABLE} "
    f"RENAME COLUMN {DRIVE_STATISTICS_OLD_DRIVE_ID_COLUMN} "
    f"TO {DRIVE_STATISTICS_SUMMARY_ID_COLUMN};"
)


# ---- US-365 vehicle_info ECU-lineage identifiers + DDLs (F-108) -------------
#
# Five new columns + a STORED generated marker enforcing "exactly one active
# ECU".  DATETIME (not TIMESTAMP) matches the rest of the schema's ``*_utc``
# columns (synced_at / created_at use DateTime) and dodges the TIMESTAMP epoch
# range; the AC's "TIMESTAMP" is the generic term.  The two required columns are
# added NULLable, the legacy rows are backfilled, then the columns are tightened
# to NOT NULL -- so a production table with pre-tracking rows survives the ADD
# (ORM declares them NOT NULL, so the final shape matches across environments).
#
# Legacy backfill (per US-365 conditionalOutcome + AC#3): a pre-tracking
# vehicle_info row gets the honest ``PRE_TRACKING_UNKNOWN`` sentinel signature
# (NOT a fabricated ECU id) and is CLOSED at its own ``created_at`` (install ==
# removal == created_at), so it is never "currently active" and never collides
# on the unique marker.  US-367's authoritative backfill (Spool-signed naming +
# real install/removal timestamps) overwrites these placeholder rows.

VEHICLE_INFO_TABLE: str = 'vehicle_info'
VEHICLE_INFO_ECU_SIGNATURE_COLUMN: str = 'ecu_signature'
VEHICLE_INFO_CAL_SIGNATURE_COLUMN: str = 'cal_signature'
VEHICLE_INFO_ECU_INSTALL_COLUMN: str = 'ecu_install_timestamp_utc'
VEHICLE_INFO_ECU_REMOVAL_COLUMN: str = 'ecu_removal_timestamp_utc'
VEHICLE_INFO_NOTES_COLUMN: str = 'notes'

ADD_VEHICLE_INFO_ECU_SIGNATURE_DDL: str = (
    f"ALTER TABLE {VEHICLE_INFO_TABLE} "
    f"ADD COLUMN {VEHICLE_INFO_ECU_SIGNATURE_COLUMN} TEXT NULL;"
)
ADD_VEHICLE_INFO_CAL_SIGNATURE_DDL: str = (
    f"ALTER TABLE {VEHICLE_INFO_TABLE} "
    f"ADD COLUMN {VEHICLE_INFO_CAL_SIGNATURE_COLUMN} TEXT NULL;"
)
ADD_VEHICLE_INFO_ECU_INSTALL_DDL: str = (
    f"ALTER TABLE {VEHICLE_INFO_TABLE} "
    f"ADD COLUMN {VEHICLE_INFO_ECU_INSTALL_COLUMN} DATETIME NULL;"
)
ADD_VEHICLE_INFO_ECU_REMOVAL_DDL: str = (
    f"ALTER TABLE {VEHICLE_INFO_TABLE} "
    f"ADD COLUMN {VEHICLE_INFO_ECU_REMOVAL_COLUMN} DATETIME NULL;"
)
ADD_VEHICLE_INFO_NOTES_DDL: str = (
    f"ALTER TABLE {VEHICLE_INFO_TABLE} "
    f"ADD COLUMN {VEHICLE_INFO_NOTES_COLUMN} TEXT NULL;"
)

# Close every pre-tracking legacy row with an honest sentinel signature + a
# zero-length window at its own created_at.  WHERE-guarded so it is a no-op once
# the rows are populated (idempotent) and matches nothing on a fresh create_all
# DB (no legacy rows).
BACKFILL_VEHICLE_INFO_LEGACY_DDL: str = (
    f"UPDATE {VEHICLE_INFO_TABLE} SET "
    f"{VEHICLE_INFO_ECU_SIGNATURE_COLUMN} = "
    f"COALESCE({VEHICLE_INFO_ECU_SIGNATURE_COLUMN}, "
    f"'{VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN}'), "
    f"{VEHICLE_INFO_ECU_INSTALL_COLUMN} = "
    f"COALESCE({VEHICLE_INFO_ECU_INSTALL_COLUMN}, created_at, NOW()), "
    f"{VEHICLE_INFO_ECU_REMOVAL_COLUMN} = "
    f"COALESCE({VEHICLE_INFO_ECU_REMOVAL_COLUMN}, created_at, NOW()) "
    f"WHERE {VEHICLE_INFO_ECU_SIGNATURE_COLUMN} IS NULL "
    f"OR {VEHICLE_INFO_ECU_INSTALL_COLUMN} IS NULL;"
)

MODIFY_VEHICLE_INFO_ECU_SIGNATURE_NOT_NULL_DDL: str = (
    f"ALTER TABLE {VEHICLE_INFO_TABLE} "
    f"MODIFY {VEHICLE_INFO_ECU_SIGNATURE_COLUMN} TEXT NOT NULL;"
)
MODIFY_VEHICLE_INFO_ECU_INSTALL_NOT_NULL_DDL: str = (
    f"ALTER TABLE {VEHICLE_INFO_TABLE} "
    f"MODIFY {VEHICLE_INFO_ECU_INSTALL_COLUMN} DATETIME NOT NULL;"
)

# STORED generated marker: the expression is the SSOT shared with the ORM
# (VEHICLE_INFO_ACTIVE_MARKER_EXPR) so SHOW CREATE TABLE is identical.
ADD_VEHICLE_INFO_ACTIVE_MARKER_DDL: str = (
    f"ALTER TABLE {VEHICLE_INFO_TABLE} "
    f"ADD COLUMN {VEHICLE_INFO_ACTIVE_MARKER_COLUMN} INT "
    f"AS ({VEHICLE_INFO_ACTIVE_MARKER_EXPR}) STORED;"
)
ADD_VEHICLE_INFO_SINGLE_ACTIVE_INDEX_DDL: str = (
    f"ALTER TABLE {VEHICLE_INFO_TABLE} "
    f"ADD UNIQUE INDEX {VEHICLE_INFO_SINGLE_ACTIVE_INDEX} "
    f"({VEHICLE_INFO_ACTIVE_MARKER_COLUMN});"
)


# ---- US-368 dtc_freeze_frame CREATE TABLE (F-109) ---------------------------
#
# A brand-new synced capture table (no prior version), so -- unlike the other
# v0010 substeps which ALTER existing tables -- this one CREATEs the whole
# table, mirroring v0005's CREATE-TABLE-IF-NOT-EXISTS + serverTableExists
# short-circuit + post-condition probe pattern.  Column order mirrors the
# DtcFreezeFrame ORM so a stale-vs-migrated diff is visually obvious.  FKs to
# dtc_log(id) + vehicle_info(id) per AC#1; the vehicle_info FK is the one the
# server writer-path's temporal invariant guards (insertDtcFreezeFrame).  Runs
# AFTER the vehicle_info substep (FK target must exist first).

DTC_FREEZE_FRAME_TABLE: str = 'dtc_freeze_frame'
DTC_FREEZE_FRAME_UNIQUE_NAME: str = 'uq_dtc_freeze_frame_source'
DTC_FREEZE_FRAME_DTC_LOG_INDEX: str = 'ix_dtc_freeze_frame_dtc_log_id'
DTC_FREEZE_FRAME_VEHICLE_INFO_INDEX: str = 'ix_dtc_freeze_frame_vehicle_info_id'
DTC_FREEZE_FRAME_DTC_LOG_FK: str = 'fk_dtc_freeze_frame_dtc_log'
DTC_FREEZE_FRAME_VEHICLE_INFO_FK: str = 'fk_dtc_freeze_frame_vehicle_info'

CREATE_DTC_FREEZE_FRAME_DDL: str = (
    f'CREATE TABLE IF NOT EXISTS {DTC_FREEZE_FRAME_TABLE} ('
    '    id                         INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '    source_id                  INT NOT NULL,'
    '    source_device              VARCHAR(64) NOT NULL,'
    '    synced_at                  DATETIME DEFAULT CURRENT_TIMESTAMP,'
    '    sync_batch_id              INT,'
    '    dtc_log_id                 INT,'
    '    captured_at_timestamp_utc  DATETIME NOT NULL,'
    '    pid_responses_json         JSON,'
    '    vehicle_info_id            INT,'
    '    notes                      TEXT,'
    f'    UNIQUE KEY {DTC_FREEZE_FRAME_UNIQUE_NAME} (source_device, source_id),'
    f'    KEY {DTC_FREEZE_FRAME_DTC_LOG_INDEX} (dtc_log_id),'
    f'    KEY {DTC_FREEZE_FRAME_VEHICLE_INFO_INDEX} (vehicle_info_id),'
    f'    CONSTRAINT {DTC_FREEZE_FRAME_DTC_LOG_FK} '
    '        FOREIGN KEY (dtc_log_id) REFERENCES dtc_log(id),'
    f'    CONSTRAINT {DTC_FREEZE_FRAME_VEHICLE_INFO_FK} '
    '        FOREIGN KEY (vehicle_info_id) REFERENCES vehicle_info(id)'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    '  COLLATE=utf8mb4_unicode_ci;'
)


# ---- US-370 speed_pid_calibration CREATE + 2-ECU seed (F-076) ---------------
#
# Per-ECU multiplicative SPEED-PID correction (new modified-EPROM ECU reads ~2x
# actual ground speed).  Brand-new table -> CREATE TABLE IF NOT EXISTS (US-368
# pattern).  Atlas option-(c) ruling 2026-05-29: ``ecu_signature`` is a UNIQUE
# natural key (VARCHAR(32)), NOT a foreign key to vehicle_info -- the correction
# is window-invariant, so it keys on the signature value, not a window-scoped
# row.  The capture_method ENUM is realized as VARCHAR + CHECK (cross-DB parity
# with SQLite, matching the data_quality enums); the value list is built from the
# ORM tuple so an ORM-side change trips the DDL-parity test.

_SPEED_PID_CAPTURE_METHOD_SQL: str = ','.join(
    f"'{v}'" for v in SPEED_PID_CALIBRATION_CAPTURE_METHOD_VALUES
)

CREATE_SPEED_PID_CALIBRATION_DDL: str = (
    f'CREATE TABLE IF NOT EXISTS {SPEED_PID_CALIBRATION_TABLE} ('
    'id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, '
    f'ecu_signature VARCHAR({SPEED_PID_CALIBRATION_ECU_SIGNATURE_LENGTH}) NOT NULL, '
    'correction_factor DOUBLE NOT NULL, '
    'capture_method VARCHAR(32), '
    'captured_at_timestamp_utc DATETIME, '
    'captured_by VARCHAR(128), '
    'provenance TEXT NOT NULL, '
    'notes TEXT, '
    f'UNIQUE KEY {SPEED_PID_CALIBRATION_ECU_SIGNATURE_UNIQUE} (ecu_signature), '
    f'CONSTRAINT {SPEED_PID_CALIBRATION_CAPTURE_METHOD_CHECK_NAME} '
    f'CHECK (capture_method IN ({_SPEED_PID_CAPTURE_METHOD_SQL}))'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;'
)

# Seed rows -- grounded, no fabrication (Spool-signed signatures, frozen
# provenance strings).  INSERT IGNORE keyed on the UNIQUE ecu_signature so a
# re-run / partial-success / create_all-then-migrate all converge.  US-367's
# authoritative backfill later overwrites these bootstrap seeds.
#   prior ECU (drives <=24): MD346675, factor 1.0 (Drive 18 3rd-gear math fit).
#   new ECU  (drives >=25):  MD326328, factor 0.5 (INITIAL ESTIMATE, Drive 26
#                            rough gear-math; pending Spool Q2 GPS-correlation).
SEED_PRIOR_ECU_SPEED_PID_CALIBRATION_DDL: str = (
    f'INSERT IGNORE INTO {SPEED_PID_CALIBRATION_TABLE} '
    '(ecu_signature, correction_factor, capture_method, provenance, notes) '
    "VALUES ('MD346675', 1.0, 'gear_math', 'gear-math-drive-18-3rd-gear-fit', "
    "'Prior ECU (drives <=24); SPEED reads correct -- Drive 18 RPM 3937 / "
    "SPEED 60 3rd-gear math fit.');"
)
SEED_NEW_ECU_SPEED_PID_CALIBRATION_DDL: str = (
    f'INSERT IGNORE INTO {SPEED_PID_CALIBRATION_TABLE} '
    '(ecu_signature, correction_factor, capture_method, provenance, notes) '
    "VALUES ('MD326328', 0.5, 'gear_math', 'rough-seed-drive-26-gear-math', "
    "'INITIAL ESTIMATE pending Spool Q2 GPS-correlation refinement; new "
    "modified-EPROM ECU SPEED reads ~2x actual (Drive 26 rough gear-math).');"
)


# ---- US-372 drive_summary.drive_id <-> source_id invariant (F-076) ----------
#
# Q1 ruling 2026-05-28: backfill + CHECK invariant.  The production smell is a
# Pi-sync drive_summary row whose Pi drive_counter id mapped to ``source_id``
# while the ``drive_id`` mirror was left NULL (per-drive joins keyed on drive_id
# were bitten by the NULL).  The substep backfills BOTH asymmetric directions --
# the forward case (AC#1 step i) and the reverse case (conditionalOutcome 1) --
# BEFORE the ADD CONSTRAINT, so the CHECK cannot fail on real data.  Runs LAST
# in apply(): it depends on no other v0010 substep and only touches columns that
# predate v0010.

BACKFILL_DRIVE_SUMMARY_DRIVE_ID_FROM_SOURCE_DDL: str = (
    f"UPDATE {DRIVE_SUMMARY_TABLE} SET drive_id = source_id "
    f"WHERE drive_id IS NULL AND source_id IS NOT NULL;"
)
BACKFILL_DRIVE_SUMMARY_SOURCE_ID_FROM_DRIVE_DDL: str = (
    f"UPDATE {DRIVE_SUMMARY_TABLE} SET source_id = drive_id "
    f"WHERE source_id IS NULL AND drive_id IS NOT NULL;"
)
ADD_DRIVE_SUMMARY_DRIVE_ID_CHECK_DDL: str = (
    f"ALTER TABLE {DRIVE_SUMMARY_TABLE} "
    f"ADD CONSTRAINT {DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME} "
    f"CHECK ({DRIVE_SUMMARY_DRIVE_ID_CHECK_CLAUSE});"
)


# ---- INFORMATION_SCHEMA probes ----------------------------------------------


def _checkConstraintCount(ctx: RunnerContext, constraintName: str) -> int:
    """Return how many CHECK constraints match ``constraintName`` (0 or 1)."""
    sql = (
        "SELECT COUNT(*) FROM information_schema.CHECK_CONSTRAINTS "
        f"WHERE CONSTRAINT_SCHEMA='{ctx.creds.dbName}' "
        f"AND CONSTRAINT_NAME='{constraintName}';"
    )
    res = _runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'CHECK constraint probe failed for {constraintName!r}: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    try:
        return int(res.stdout.strip().split()[0])
    except (ValueError, IndexError):
        return 0


def _checkClause(ctx: RunnerContext, constraintName: str) -> str | None:
    """Return the stored ``CHECK_CLAUSE`` for a named CHECK, or ``None``.

    ``None`` means the constraint does not exist (no row).  MariaDB stores the
    clause text (e.g. ``data_quality in ('full','sparse','below_threshold')``)
    in ``information_schema.CHECK_CONSTRAINTS.CHECK_CLAUSE``.
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


# ---- Substeps ---------------------------------------------------------------


def _applyDriveSummaryDataQualityColumn(ctx: RunnerContext) -> None:
    """US-363 substep (a): ADD drive_summary.data_quality + CHECK + index.

    Mirrors v0009's per-piece idempotency: each DDL is guarded by its own
    INFORMATION_SCHEMA probe so a partial-success state converges on re-apply.
    """
    if not serverTableExists(
        ctx.addrs, ctx.creds, DRIVE_SUMMARY_TABLE, ctx.runner,
    ):
        raise MigrationError(
            f'{DRIVE_SUMMARY_TABLE!r} table missing; v0010 cannot add a '
            f'column to a non-existent table.  Investigate why create_all + '
            f'earlier migrations did not land the table.',
        )

    columns = probeServerColumns(
        ctx.addrs, ctx.creds, DRIVE_SUMMARY_TABLE, ctx.runner,
    )

    # Step 1: column.  Short-circuit if already present (fresh-DB create_all
    # owns the column from the ORM, or a prior run added it).
    if DRIVE_SUMMARY_COLUMN not in columns:
        res = _runServerSql(
            ctx.addrs, ctx.creds, ADD_DRIVE_SUMMARY_COLUMN_DDL, ctx.runner,
        )
        if res.returncode != 0:
            raise MigrationError(
                f'add {DRIVE_SUMMARY_COLUMN!r} to {DRIVE_SUMMARY_TABLE!r} '
                f'failed: {res.stderr.strip() or res.stdout.strip()}',
            )

    # Step 2: CHECK constraint (added independently of the column).
    if _checkConstraintCount(ctx, DRIVE_SUMMARY_CHECK_NAME) == 0:
        res = _runServerSql(
            ctx.addrs, ctx.creds, ADD_DRIVE_SUMMARY_CHECK_DDL, ctx.runner,
        )
        if res.returncode != 0:
            err = (res.stderr.strip() or res.stdout.strip()).lower()
            if 'duplicate' not in err and 'already exists' not in err:
                raise MigrationError(
                    f'add CHECK {DRIVE_SUMMARY_CHECK_NAME!r} on '
                    f'{DRIVE_SUMMARY_TABLE!r} failed: '
                    f'{res.stderr.strip() or res.stdout.strip()}',
                )

    # Step 3: index.
    if not indexExists(
        ctx.addrs, ctx.creds, DRIVE_SUMMARY_TABLE,
        DRIVE_SUMMARY_INDEX_NAME, ctx.runner,
    ):
        res = _runServerSql(
            ctx.addrs, ctx.creds, ADD_DRIVE_SUMMARY_INDEX_DDL, ctx.runner,
        )
        if res.returncode != 0:
            raise MigrationError(
                f'add INDEX {DRIVE_SUMMARY_INDEX_NAME!r} on '
                f'{DRIVE_SUMMARY_TABLE!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    # Post-condition probe: the column MUST be present now.
    columnsAfter = probeServerColumns(
        ctx.addrs, ctx.creds, DRIVE_SUMMARY_TABLE, ctx.runner,
    )
    if DRIVE_SUMMARY_COLUMN not in columnsAfter:
        raise SchemaProbeError(
            f'{DRIVE_SUMMARY_COLUMN!r} missing from {DRIVE_SUMMARY_TABLE!r} '
            f'after ADD COLUMN ran; investigate the MariaDB session context '
            f'(wrong DB? filtered replica?).',
        )


def _applyDriveStatisticsAnomalyCheck(ctx: RunnerContext) -> None:
    """US-363 substep (b): extend drive_statistics CHECK with anomaly value.

    MariaDB cannot widen a CHECK in place, so the named constraint is dropped
    and re-added.  Idempotent: if the stored CHECK_CLAUSE already contains
    ``attribution_anomaly`` (fresh ``create_all`` DB or a prior run), this is a
    no-op.
    """
    if not serverTableExists(
        ctx.addrs, ctx.creds, DRIVE_STATISTICS_TABLE, ctx.runner,
    ):
        raise MigrationError(
            f'{DRIVE_STATISTICS_TABLE!r} table missing; v0010 cannot rebuild '
            f'its CHECK constraint.  Investigate why v0009 + create_all did '
            f'not land the table.',
        )

    clause = _checkClause(ctx, DRIVE_STATISTICS_CHECK_NAME)
    if clause is not None and DATA_QUALITY_ATTRIBUTION_ANOMALY in clause:
        # Already widened (fresh create_all from the 4-value ORM enum, or a
        # prior successful run).  No-op.
        return

    # Drop the stale 3-value constraint when it exists; a fresh DB whose
    # named CHECK is absent (clause is None) skips straight to ADD.
    if clause is not None:
        res = _runServerSql(
            ctx.addrs, ctx.creds, DROP_DRIVE_STATISTICS_CHECK_DDL, ctx.runner,
        )
        if res.returncode != 0:
            raise MigrationError(
                f'drop CHECK {DRIVE_STATISTICS_CHECK_NAME!r} on '
                f'{DRIVE_STATISTICS_TABLE!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    res = _runServerSql(
        ctx.addrs, ctx.creds, ADD_DRIVE_STATISTICS_CHECK_DDL, ctx.runner,
    )
    if res.returncode != 0:
        err = (res.stderr.strip() or res.stdout.strip()).lower()
        if 'duplicate' not in err and 'already exists' not in err:
            raise MigrationError(
                f'add CHECK {DRIVE_STATISTICS_CHECK_NAME!r} on '
                f'{DRIVE_STATISTICS_TABLE!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    # Post-condition probe: the widened clause MUST now carry the anomaly value.
    clauseAfter = _checkClause(ctx, DRIVE_STATISTICS_CHECK_NAME)
    if clauseAfter is None or DATA_QUALITY_ATTRIBUTION_ANOMALY not in clauseAfter:
        raise SchemaProbeError(
            f'{DRIVE_STATISTICS_CHECK_NAME!r} CHECK_CLAUSE does not contain '
            f'{DATA_QUALITY_ATTRIBUTION_ANOMALY!r} after rebuild ran; '
            f'investigate the MariaDB session context.',
        )


def _applyDriveStatisticsSummaryIdRename(ctx: RunnerContext) -> None:
    """US-371 substep: rename the drive_statistics drive_id column -> summary_id.

    Idempotent via a column probe: a fresh ``create_all`` DB already owns
    ``summary_id`` from the renamed ORM column (no-op), a v0009/US-363-era
    production DB still has ``drive_id`` (emit the RENAME), and a prior
    successful run lands on ``summary_id`` (no-op).  The rename is independent
    of the US-363 substeps (different column) and of the FK-cross-story ordering
    that binds US-365 before US-370, so it may run in any position.
    """
    if not serverTableExists(
        ctx.addrs, ctx.creds, DRIVE_STATISTICS_TABLE, ctx.runner,
    ):
        raise MigrationError(
            f'{DRIVE_STATISTICS_TABLE!r} table missing; v0010 cannot rename '
            f'its drive_id column.  Investigate why v0009 + create_all did not '
            f'land the table.',
        )

    columns = probeServerColumns(
        ctx.addrs, ctx.creds, DRIVE_STATISTICS_TABLE, ctx.runner,
    )

    # Already renamed (fresh create_all from the renamed ORM, or a prior run).
    if DRIVE_STATISTICS_SUMMARY_ID_COLUMN in columns:
        return

    if DRIVE_STATISTICS_OLD_DRIVE_ID_COLUMN not in columns:
        raise MigrationError(
            f'{DRIVE_STATISTICS_TABLE!r} has neither '
            f'{DRIVE_STATISTICS_SUMMARY_ID_COLUMN!r} nor '
            f'{DRIVE_STATISTICS_OLD_DRIVE_ID_COLUMN!r}; refusing to rename a '
            f'column that is not there.  Investigate the table shape.',
        )

    res = _runServerSql(
        ctx.addrs, ctx.creds, RENAME_DRIVE_STATISTICS_COLUMN_DDL, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'rename {DRIVE_STATISTICS_OLD_DRIVE_ID_COLUMN!r} -> '
            f'{DRIVE_STATISTICS_SUMMARY_ID_COLUMN!r} on '
            f'{DRIVE_STATISTICS_TABLE!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    # Post-condition probe: the new column MUST be present now.
    columnsAfter = probeServerColumns(
        ctx.addrs, ctx.creds, DRIVE_STATISTICS_TABLE, ctx.runner,
    )
    if DRIVE_STATISTICS_SUMMARY_ID_COLUMN not in columnsAfter:
        raise SchemaProbeError(
            f'{DRIVE_STATISTICS_SUMMARY_ID_COLUMN!r} missing from '
            f'{DRIVE_STATISTICS_TABLE!r} after RENAME ran; investigate the '
            f'MariaDB session context (wrong DB? filtered replica?).',
        )


def _applyVehicleInfoEcuColumns(ctx: RunnerContext) -> None:
    """US-365 substep (F-108): add vehicle_info ECU-lineage columns + the
    single-active-ECU unique marker.

    Per-piece idempotency mirrors the v0009 / US-363 pattern: each ADD COLUMN is
    guarded by a column probe; the unique index by an index probe.  The legacy
    backfill + NOT NULL tightening run ONLY when ``ecu_signature`` was absent at
    entry (a fresh add this run), so a fully-migrated DB is a pure no-op.  This
    substep runs AFTER the US-371 rename and BEFORE any US-370 substep, since
    speed_pid_calibration FKs ``vehicle_info.ecu_signature``.
    """
    if not serverTableExists(
        ctx.addrs, ctx.creds, VEHICLE_INFO_TABLE, ctx.runner,
    ):
        raise MigrationError(
            f'{VEHICLE_INFO_TABLE!r} table missing; v0010 cannot add ECU '
            f'columns to a non-existent table.  Investigate why create_all + '
            f'earlier migrations did not land the table.',
        )

    columns = probeServerColumns(
        ctx.addrs, ctx.creds, VEHICLE_INFO_TABLE, ctx.runner,
    )
    # True when we are adding the ECU columns fresh this run; gates the legacy
    # backfill + NOT NULL tighten so a migrated DB stays a no-op.
    freshAdd = VEHICLE_INFO_ECU_SIGNATURE_COLUMN not in columns

    addByColumn = (
        (VEHICLE_INFO_ECU_SIGNATURE_COLUMN, ADD_VEHICLE_INFO_ECU_SIGNATURE_DDL),
        (VEHICLE_INFO_CAL_SIGNATURE_COLUMN, ADD_VEHICLE_INFO_CAL_SIGNATURE_DDL),
        (VEHICLE_INFO_ECU_INSTALL_COLUMN, ADD_VEHICLE_INFO_ECU_INSTALL_DDL),
        (VEHICLE_INFO_ECU_REMOVAL_COLUMN, ADD_VEHICLE_INFO_ECU_REMOVAL_DDL),
        (VEHICLE_INFO_NOTES_COLUMN, ADD_VEHICLE_INFO_NOTES_DDL),
    )
    for columnName, ddl in addByColumn:
        if columnName not in columns:
            res = _runServerSql(ctx.addrs, ctx.creds, ddl, ctx.runner)
            if res.returncode != 0:
                raise MigrationError(
                    f'add {columnName!r} to {VEHICLE_INFO_TABLE!r} failed: '
                    f'{res.stderr.strip() or res.stdout.strip()}',
                )

    if freshAdd:
        # Backfill legacy rows, then tighten the two required columns.  Order
        # matters: the rows must be non-NULL before MODIFY ... NOT NULL.
        for ddl in (
            BACKFILL_VEHICLE_INFO_LEGACY_DDL,
            MODIFY_VEHICLE_INFO_ECU_SIGNATURE_NOT_NULL_DDL,
            MODIFY_VEHICLE_INFO_ECU_INSTALL_NOT_NULL_DDL,
        ):
            res = _runServerSql(ctx.addrs, ctx.creds, ddl, ctx.runner)
            if res.returncode != 0:
                raise MigrationError(
                    f'vehicle_info ECU backfill/tighten failed on '
                    f'{ddl!r}: {res.stderr.strip() or res.stdout.strip()}',
                )

    # Generated single-active marker column (re-probe in case it was just
    # added alongside the others above is unnecessary -- it is never in the
    # base set; guard on the entry probe instead).
    if VEHICLE_INFO_ACTIVE_MARKER_COLUMN not in columns:
        res = _runServerSql(
            ctx.addrs, ctx.creds, ADD_VEHICLE_INFO_ACTIVE_MARKER_DDL, ctx.runner,
        )
        if res.returncode != 0:
            raise MigrationError(
                f'add {VEHICLE_INFO_ACTIVE_MARKER_COLUMN!r} to '
                f'{VEHICLE_INFO_TABLE!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    if not indexExists(
        ctx.addrs, ctx.creds, VEHICLE_INFO_TABLE,
        VEHICLE_INFO_SINGLE_ACTIVE_INDEX, ctx.runner,
    ):
        res = _runServerSql(
            ctx.addrs, ctx.creds,
            ADD_VEHICLE_INFO_SINGLE_ACTIVE_INDEX_DDL, ctx.runner,
        )
        if res.returncode != 0:
            err = (res.stderr.strip() or res.stdout.strip()).lower()
            if 'duplicate' not in err and 'already exists' not in err:
                raise MigrationError(
                    f'add UNIQUE INDEX {VEHICLE_INFO_SINGLE_ACTIVE_INDEX!r} on '
                    f'{VEHICLE_INFO_TABLE!r} failed: '
                    f'{res.stderr.strip() or res.stdout.strip()}',
                )

    # Post-condition probe: the identity column MUST be present now.
    columnsAfter = probeServerColumns(
        ctx.addrs, ctx.creds, VEHICLE_INFO_TABLE, ctx.runner,
    )
    if VEHICLE_INFO_ECU_SIGNATURE_COLUMN not in columnsAfter:
        raise SchemaProbeError(
            f'{VEHICLE_INFO_ECU_SIGNATURE_COLUMN!r} missing from '
            f'{VEHICLE_INFO_TABLE!r} after ADD COLUMN ran; investigate the '
            f'MariaDB session context (wrong DB? filtered replica?).',
        )


def _applyDtcFreezeFrameTable(ctx: RunnerContext) -> None:
    """US-368 substep (F-109): create the dtc_freeze_frame capture table.

    Brand-new table, so this CREATEs rather than ALTERs.  Idempotent via the
    v0005 pattern: a ``serverTableExists`` short-circuit (covers fresh-DB
    ``create_all`` -- the ORM owns the table -- and idempotent re-runs) plus
    ``CREATE TABLE IF NOT EXISTS`` belt-and-suspenders, with a post-condition
    probe that raises :class:`SchemaProbeError` on the silent-no-op class.

    Runs AFTER ``_applyVehicleInfoEcuColumns`` because the freeze-frame FK
    references ``vehicle_info(id)`` (the dtc_log FK target predates v0010).
    """
    if serverTableExists(
        ctx.addrs, ctx.creds, DTC_FREEZE_FRAME_TABLE, ctx.runner,
    ):
        return

    res = _runServerSql(
        ctx.addrs, ctx.creds, CREATE_DTC_FREEZE_FRAME_DDL, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'create {DTC_FREEZE_FRAME_TABLE!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    if not serverTableExists(
        ctx.addrs, ctx.creds, DTC_FREEZE_FRAME_TABLE, ctx.runner,
    ):
        raise SchemaProbeError(
            f'{DTC_FREEZE_FRAME_TABLE!r} missing after CREATE TABLE ran; '
            f'investigate the MariaDB session context (wrong DB? '
            f'filtered replica?).',
        )


def _applySpeedPidCalibrationTable(ctx: RunnerContext) -> None:
    """US-370 substep (F-076): create speed_pid_calibration + seed 2 ECU rows.

    Runs AFTER ``_applyVehicleInfoEcuColumns`` (US-365).  Atlas option-(c)
    (2026-05-29) made ``ecu_signature`` a UNIQUE natural key with NO FK to
    vehicle_info, but the US-365-before-US-370 ordering is preserved per Atlas
    Refinements row 16: the two tables share the ``ecu_signature`` value, and
    US-367's authoritative vehicle_info backfill is that value's source.

    Brand-new table, so this CREATEs rather than ALTERs, mirroring the
    ``_applyDtcFreezeFrameTable`` (v0005) pattern: a ``serverTableExists``
    short-circuit + ``CREATE TABLE IF NOT EXISTS`` + post-condition probe.

    The two seed rows are emitted via ``INSERT IGNORE`` (keyed on the UNIQUE
    ``ecu_signature``) on EVERY run -- not only on fresh create -- so a re-run,
    a partial-success recovery (table created but seed failed), and a
    create_all-then-migrate DB all converge to the seeded state idempotently.
    """
    freshCreate = not serverTableExists(
        ctx.addrs, ctx.creds, SPEED_PID_CALIBRATION_TABLE, ctx.runner,
    )
    if freshCreate:
        res = _runServerSql(
            ctx.addrs, ctx.creds, CREATE_SPEED_PID_CALIBRATION_DDL, ctx.runner,
        )
        if res.returncode != 0:
            raise MigrationError(
                f'create {SPEED_PID_CALIBRATION_TABLE!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

        if not serverTableExists(
            ctx.addrs, ctx.creds, SPEED_PID_CALIBRATION_TABLE, ctx.runner,
        ):
            raise SchemaProbeError(
                f'{SPEED_PID_CALIBRATION_TABLE!r} missing after CREATE TABLE ran; '
                f'investigate the MariaDB session context (wrong DB? '
                f'filtered replica?).',
            )

    for ddl in (
        SEED_PRIOR_ECU_SPEED_PID_CALIBRATION_DDL,
        SEED_NEW_ECU_SPEED_PID_CALIBRATION_DDL,
    ):
        res = _runServerSql(ctx.addrs, ctx.creds, ddl, ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'seed {SPEED_PID_CALIBRATION_TABLE!r} failed on '
                f'{ddl!r}: {res.stderr.strip() or res.stdout.strip()}',
            )


def _applyDriveSummaryDriveIdSourceIdInvariant(ctx: RunnerContext) -> None:
    """US-372 substep (F-076): backfill drive_summary.drive_id <-> source_id,
    then ADD the CHECK invariant.

    ORDER -- UPDATE BEFORE ALTER (Atlas Refinements row 16): both asymmetric
    directions are backfilled before the constraint lands, so ADD CONSTRAINT
    cannot fail on pre-migration rows.

    * Forward (AC#1 step i): ``drive_id <- source_id`` where the mirror is NULL
      but the Pi origin is known (the actual V0.27.x smell -- Pi-sync rows whose
      mirror was never populated).
    * Reverse (conditionalOutcome 1): ``source_id <- drive_id`` where an
      analytics-only row somehow set the mirror but not the source id.

    Idempotent: when the named CHECK already exists (a fresh ``create_all`` DB --
    the ORM owns the constraint -- or a prior successful run), this is a pure
    no-op (no backfill UPDATEs, no ALTER).  A row that has BOTH columns set to
    DIFFERENT values is deliberately NOT silently rewritten; the ADD CONSTRAINT
    will fail loudly on it, surfacing genuinely corrupt data for disposition.
    """
    if not serverTableExists(
        ctx.addrs, ctx.creds, DRIVE_SUMMARY_TABLE, ctx.runner,
    ):
        raise MigrationError(
            f'{DRIVE_SUMMARY_TABLE!r} table missing; v0010 cannot add the '
            f'drive_id/source_id invariant.  Investigate why create_all + '
            f'earlier migrations did not land the table.',
        )

    # Already enforced (fresh create_all from the ORM CHECK, or a prior run).
    if _checkConstraintCount(ctx, DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME) >= 1:
        return

    for ddl in (
        BACKFILL_DRIVE_SUMMARY_DRIVE_ID_FROM_SOURCE_DDL,
        BACKFILL_DRIVE_SUMMARY_SOURCE_ID_FROM_DRIVE_DDL,
    ):
        res = _runServerSql(ctx.addrs, ctx.creds, ddl, ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'drive_summary drive_id/source_id backfill failed on '
                f'{ddl!r}: {res.stderr.strip() or res.stdout.strip()}',
            )

    res = _runServerSql(
        ctx.addrs, ctx.creds, ADD_DRIVE_SUMMARY_DRIVE_ID_CHECK_DDL, ctx.runner,
    )
    if res.returncode != 0:
        err = (res.stderr.strip() or res.stdout.strip()).lower()
        if 'duplicate' not in err and 'already exists' not in err:
            raise MigrationError(
                f'add CHECK {DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME!r} on '
                f'{DRIVE_SUMMARY_TABLE!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    # Post-condition probe: the invariant CHECK MUST be present now.
    if _checkConstraintCount(ctx, DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME) < 1:
        raise SchemaProbeError(
            f'{DRIVE_SUMMARY_DRIVE_ID_CHECK_NAME!r} CHECK missing from '
            f'{DRIVE_SUMMARY_TABLE!r} after ADD CONSTRAINT ran; investigate '
            f'the MariaDB session context (wrong DB? filtered replica?).',
        )


def apply(ctx: RunnerContext) -> None:
    """Apply the V0.28.0 schema pass substeps in story order.

    US-363 (F-107) substeps land first.  Later V0.28.0 schema stories append
    their ``_applyUsNNN`` substep call below, preserving FK-cross-story order.
    """
    # ---- US-363 (F-107) -- attribution-anomaly tripwire schema ----
    _applyDriveSummaryDataQualityColumn(ctx)
    _applyDriveStatisticsAnomalyCheck(ctx)

    # ---- US-371 (F-076) -- drive_statistics drive_id -> summary_id rename ----
    # Independent of the US-363 substeps (different column) and order-insensitive
    # vs the US-365-before-US-370 FK ordering.
    _applyDriveStatisticsSummaryIdRename(ctx)

    # ---- US-365 (F-108) -- vehicle_info ECU lineage --------------------------
    # MUST precede any US-370 substep: speed_pid_calibration FKs
    # vehicle_info.ecu_signature (Atlas Refinements row 16 ordering).
    _applyVehicleInfoEcuColumns(ctx)

    # ---- US-368 (F-109) -- dtc_freeze_frame capture table --------------------
    # CREATE (new table).  Runs after the vehicle_info substep: the freeze-frame
    # FK references vehicle_info(id).
    _applyDtcFreezeFrameTable(ctx)

    # ---- US-370 (F-076) -- speed_pid_calibration table + 2-ECU seed ----------
    # MUST follow the US-365 vehicle_info substep (ecu_signature value source);
    # ecu_signature is a UNIQUE natural key (option-(c) -- no FK).
    _applySpeedPidCalibrationTable(ctx)

    # ---- US-372 (F-076) -- drive_summary.drive_id <-> source_id invariant ----
    # Runs LAST: depends on no other v0010 substep; only touches columns that
    # predate v0010.  UPDATE-before-ALTER backfill is internal to the substep.
    _applyDriveSummaryDriveIdSourceIdInvariant(ctx)


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
