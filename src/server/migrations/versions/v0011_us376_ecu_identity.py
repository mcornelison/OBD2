################################################################################
# File Name: v0011_us376_ecu_identity.py
# Purpose/Description: Sprint 44 V0.28.1 (US-376 + US-374 / B-076 first slice) --
#                      migration v0011 (forward-only; v0010 untouched).  Substeps:
#                        (a) CREATE the normalized, immutable ``ecu`` identity
#                            dimension (id PK, ecu_signature/cal_signature
#                            VARCHAR(32) NOT NULL, UNIQUE pair) + seed the 3
#                            grounded identity rows idempotently (INSERT IGNORE).
#                        (b) ADD ``vehicle_info.ecu_id`` (FK -> ecu.id), backfill
#                            it by matching each row's (ecu_signature,
#                            cal_signature) text to its ecu row -- a legacy row
#                            whose cal_signature is NULL resolves via
#                            COALESCE(cal, sig) onto the PRE_TRACKING_UNKNOWN seed
#                            (whose cal == its sig) -- DERIVE the transitional
#                            text columns from the matched ecu row (coherence),
#                            FAIL LOUDLY on any unmatched row (never NULL ecu_id),
#                            MODIFY NOT NULL, ADD the FK, and extend the
#                            append-only table comment.
#                        (c) RE-KEY speed_pid_calibration (US-374) FORWARD from
#                            the v0010 option-(c) ecu_signature natural key to an
#                            ecu_id FK -> ecu.id + UNIQUE(ecu_id): ADD ecu_id,
#                            backfill by matching ecu_signature to its ecu row,
#                            re-point the 2 seed provenance strings, FAIL LOUDLY
#                            on any unmatched row, MODIFY NOT NULL, ADD UNIQUE+FK,
#                            then DROP the old ecu_signature UNIQUE key + column.
#                      Mirrors v0005/v0010's INFORMATION_SCHEMA-probe idempotency
#                      so a partial-success re-run, an already-migrated DB, and a
#                      fresh ``Base.metadata.create_all`` DB all converge.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-01    | Rex (US-376) | Initial -- B-076 first slice: ecu identity table
#               |              | + vehicle_info.ecu_id FK wiring.
# ================================================================================
################################################################################

"""Migration 0011: normalized ecu identity dimension + vehicle_info.ecu_id FK.

Context (US-376 / F-076 / B-076 first slice)
--------------------------------------------
ECU identity was duplicated free text on ``vehicle_info`` (``ecu_signature`` +
``cal_signature``).  This migration normalizes it into an ``ecu`` dimension
keyed on the ``(ecu_signature, cal_signature)`` PAIR -- so a reflash is its own
identity row -- and references it from ``vehicle_info`` by ``ecu_id`` FK, making
ECU identity SSOT.  The transitional TEXT columns are KEPT this slice (a derived
snapshot, dropped in a later B-076 slice); a coherence guard
(:mod:`src.server.db.vehicle_info_coherence`) asserts they never drift from the
joined ecu row.

Forward-only
------------
v0011 is a NEW module; v0010 is byte-for-byte untouched (the dev-shipped v0010
build is already on dev).  v0011 runs after v0010 in registry order.

Backfill + FAIL LOUDLY
----------------------
The vehicle_info.ecu_id backfill JOINs ecu on ``ecu_signature`` AND
``COALESCE(vi.cal_signature, vi.ecu_signature) = e.cal_signature``.  The COALESCE
maps the v0010 legacy sentinel row (``ecu_signature='PRE_TRACKING_UNKNOWN'``,
``cal_signature=NULL``) onto the ``(PRE_TRACKING_UNKNOWN, PRE_TRACKING_UNKNOWN)``
seed (whose cal equals its sig) without special-casing, while a genuinely
unseeded identity matches nothing.  After the JOIN UPDATE, any row still holding
``ecu_id IS NULL`` FAILS LOUDLY (:class:`MigrationError`) -- bad data is surfaced
for disposition, never silently NULLed (US-376 conditionalOutcome 1).

Idempotency contract
--------------------
* ecu CREATE: ``serverTableExists`` short-circuit + ``CREATE TABLE IF NOT
  EXISTS`` + post-condition probe (covers fresh ``create_all`` -- the ORM owns
  the table -- and re-runs).  The 3 seeds are ``INSERT IGNORE`` on EVERY run.
* vehicle_info.ecu_id: a column probe gates the whole ADD/backfill/MODIFY/FK/
  COMMENT block -- a fresh ``create_all`` DB (ORM already owns ``ecu_id`` + the
  FK) and a prior successful run are pure no-ops.

Reversibility
-------------
ADD TABLE / ADD COLUMN / ADD CONSTRAINT are non-destructive; no down-migration
ships (snapshot + redeploy per the runner's documented design).
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    probeServerColumns,
    serverTableExists,
)
from src.server.db.models import (
    ECU_IMMUTABILITY_COMMENT,
    ECU_PAIR_UNIQUE,
    ECU_SEED_PAIRS,
    ECU_SIGNATURE_LENGTH,
    ECU_TABLE,
    SPEED_PID_CALIBRATION_ECU_FK_COLUMN,
    SPEED_PID_CALIBRATION_ECU_FK_NAME,
    SPEED_PID_CALIBRATION_ECU_ID_UNIQUE,
    SPEED_PID_CALIBRATION_ECU_SIGNATURE_UNIQUE,
    SPEED_PID_CALIBRATION_TABLE,
    VEHICLE_INFO_APPEND_ONLY_COMMENT,
    VEHICLE_INFO_ECU_FK_COLUMN,
    VEHICLE_INFO_ECU_FK_NAME,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'ADD_SPEED_PID_ECU_FK_DDL',
    'ADD_SPEED_PID_ECU_ID_DDL',
    'ADD_SPEED_PID_ECU_ID_UNIQUE_DDL',
    'ADD_VEHICLE_INFO_ECU_FK_DDL',
    'ADD_VEHICLE_INFO_ECU_ID_DDL',
    'ALTER_VEHICLE_INFO_COMMENT_DDL',
    'BACKFILL_SPEED_PID_ECU_ID_DDL',
    'BACKFILL_VEHICLE_INFO_ECU_ID_DDL',
    'CREATE_ECU_DDL',
    'DESCRIPTION',
    'DROP_SPEED_PID_ECU_SIGNATURE_COLUMN_DDL',
    'DROP_SPEED_PID_ECU_SIGNATURE_UNIQUE_DDL',
    'ECU_TABLE',
    'MIGRATION',
    'MODIFY_SPEED_PID_ECU_ID_NOT_NULL_DDL',
    'MODIFY_VEHICLE_INFO_ECU_ID_NOT_NULL_DDL',
    'REPOINT_NEW_ECU_PROVENANCE_DDL',
    'REPOINT_PRIOR_ECU_PROVENANCE_DDL',
    'SEED_ECU_DDLS',
    'SPEED_PID_CALIBRATION_TABLE',
    'SPEED_PID_NEW_ECU_PROVENANCE',
    'SPEED_PID_PRIOR_ECU_PROVENANCE',
    'VEHICLE_INFO_TABLE',
    'VERSION',
    'apply',
]


VERSION: str = '0011'
DESCRIPTION: str = (
    'US-376/US-374 F-076/B-076 first slice -- normalized ecu identity dimension '
    '(pair-keyed) + vehicle_info.ecu_id FK wiring + speed_pid_calibration re-key '
    'to ecu_id FK (V0.28.1 schema pass)'
)

VEHICLE_INFO_TABLE: str = 'vehicle_info'


# ---- ecu CREATE + seed DDLs --------------------------------------------------
#
# Identity dimension: no lineage/timestamp columns (the install/removal window
# stays on vehicle_info).  The immutability carve-out is surfaced as a table
# COMMENT (the constant carries no apostrophes, so it is safe to embed inline).

CREATE_ECU_DDL: str = (
    f'CREATE TABLE IF NOT EXISTS {ECU_TABLE} ('
    'id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, '
    f'ecu_signature VARCHAR({ECU_SIGNATURE_LENGTH}) NOT NULL, '
    f'cal_signature VARCHAR({ECU_SIGNATURE_LENGTH}) NOT NULL, '
    f'UNIQUE KEY {ECU_PAIR_UNIQUE} (ecu_signature, cal_signature)'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci '
    f"COMMENT='{ECU_IMMUTABILITY_COMMENT}';"
)

# Seed the 3 grounded identity rows (INSERT IGNORE on the pair UNIQUE so a
# re-run / partial-success / create_all-then-migrate all converge).  Built from
# the SSOT ECU_SEED_PAIRS tuple so an ORM-side change trips the DDL-parity test.
SEED_ECU_DDLS: tuple[str, ...] = tuple(
    f'INSERT IGNORE INTO {ECU_TABLE} (ecu_signature, cal_signature) '
    f"VALUES ('{sig}', '{cal}');"
    for sig, cal in ECU_SEED_PAIRS
)


# ---- vehicle_info.ecu_id DDLs ------------------------------------------------

ADD_VEHICLE_INFO_ECU_ID_DDL: str = (
    f'ALTER TABLE {VEHICLE_INFO_TABLE} '
    f'ADD COLUMN {VEHICLE_INFO_ECU_FK_COLUMN} INT NULL;'
)

# Resolve ecu_id by matching the transitional text pair to an ecu row, and
# DERIVE the (transitional) cal_signature from the matched ecu row so the
# coherence invariant holds.  COALESCE(cal, sig) maps the legacy NULL-cal
# sentinel onto the (PRE_TRACKING_UNKNOWN, PRE_TRACKING_UNKNOWN) seed.
BACKFILL_VEHICLE_INFO_ECU_ID_DDL: str = (
    f'UPDATE {VEHICLE_INFO_TABLE} vi JOIN {ECU_TABLE} e '
    'ON vi.ecu_signature = e.ecu_signature '
    'AND COALESCE(vi.cal_signature, vi.ecu_signature) = e.cal_signature '
    'SET vi.ecu_id = e.id, vi.cal_signature = e.cal_signature '
    'WHERE vi.ecu_id IS NULL;'
)

# FAIL-LOUDLY probe: any vehicle_info row the backfill could not resolve.
COUNT_UNRESOLVED_ECU_ID_SQL: str = (
    f'SELECT COUNT(*) FROM {VEHICLE_INFO_TABLE} WHERE ecu_id IS NULL;'
)

MODIFY_VEHICLE_INFO_ECU_ID_NOT_NULL_DDL: str = (
    f'ALTER TABLE {VEHICLE_INFO_TABLE} '
    f'MODIFY {VEHICLE_INFO_ECU_FK_COLUMN} INT NOT NULL;'
)

ADD_VEHICLE_INFO_ECU_FK_DDL: str = (
    f'ALTER TABLE {VEHICLE_INFO_TABLE} '
    f'ADD CONSTRAINT {VEHICLE_INFO_ECU_FK_NAME} '
    f'FOREIGN KEY ({VEHICLE_INFO_ECU_FK_COLUMN}) REFERENCES {ECU_TABLE}(id);'
)

# Bring the migrated table comment up to the ORM value (v0010 never set it, so a
# migrated production table has no comment; this lands the full append-only +
# ecu_id wording so SHOW CREATE TABLE matches create_all).
ALTER_VEHICLE_INFO_COMMENT_DDL: str = (
    f'ALTER TABLE {VEHICLE_INFO_TABLE} '
    f"COMMENT='{VEHICLE_INFO_APPEND_ONLY_COMMENT}';"
)


# ---- US-374 speed_pid_calibration re-key DDLs (forward from option-(c)) -------
#
# v0010 (untouched) created speed_pid_calibration keyed on its own
# ``ecu_signature`` natural key + ``uq_speed_pid_calibration_ecu_signature``.
# Now that the ecu identity dimension exists, US-374 re-keys it FORWARD to an
# ``ecu_id`` FK -> ecu.id with UNIQUE(ecu_id): the calibration references the
# SSOT identity, and because ecu is pair-keyed a reflash gets its own row.
# The 2 v0010 seed provenance strings are re-pointed to the Spool-signed
# 2026-06-01 values (the prior-ECU seed gains the ``empirical-`` prefix so the
# analytics gate includes it; the new-ECU rough seed stays excluded).

# Grounded, Spool-signed (2026-06-01) -- no fabrication.  The prior-ECU value is
# empirical-prefixed (gate INCLUDES it); the new-ECU value is a rough sanity-check
# seed (gate EXCLUDES it).  See US-374 AC#4 + VC#6.
SPEED_PID_PRIOR_ECU_PROVENANCE: str = 'empirical-Drive-18-gear-math-fit'
SPEED_PID_NEW_ECU_PROVENANCE: str = 'gear-math-sanity-check-Drive-26-CIO-corrected'

ADD_SPEED_PID_ECU_ID_DDL: str = (
    f'ALTER TABLE {SPEED_PID_CALIBRATION_TABLE} '
    f'ADD COLUMN {SPEED_PID_CALIBRATION_ECU_FK_COLUMN} INT NULL;'
)

# Resolve ecu_id by matching each calibration row's transitional ecu_signature
# to its ecu identity row.  Each seed signature maps to exactly one ecu row
# (1:1 today); a reflash would add its own ecu row + its own calibration row.
BACKFILL_SPEED_PID_ECU_ID_DDL: str = (
    f'UPDATE {SPEED_PID_CALIBRATION_TABLE} spc JOIN {ECU_TABLE} e '
    'ON spc.ecu_signature = e.ecu_signature '
    'SET spc.ecu_id = e.id '
    'WHERE spc.ecu_id IS NULL;'
)

# Re-point the 2 v0010 seed provenance strings (run while ecu_signature still
# exists, before the column is dropped).
REPOINT_PRIOR_ECU_PROVENANCE_DDL: str = (
    f'UPDATE {SPEED_PID_CALIBRATION_TABLE} '
    f"SET provenance = '{SPEED_PID_PRIOR_ECU_PROVENANCE}' "
    "WHERE ecu_signature = 'MD346675';"
)
REPOINT_NEW_ECU_PROVENANCE_DDL: str = (
    f'UPDATE {SPEED_PID_CALIBRATION_TABLE} '
    f"SET provenance = '{SPEED_PID_NEW_ECU_PROVENANCE}' "
    "WHERE ecu_signature = 'MD335287';"
)

# FAIL-LOUDLY probe: any calibration row the backfill could not resolve.
COUNT_UNRESOLVED_SPEED_PID_SQL: str = (
    f'SELECT COUNT(*) FROM {SPEED_PID_CALIBRATION_TABLE} WHERE ecu_id IS NULL;'
)

MODIFY_SPEED_PID_ECU_ID_NOT_NULL_DDL: str = (
    f'ALTER TABLE {SPEED_PID_CALIBRATION_TABLE} '
    f'MODIFY {SPEED_PID_CALIBRATION_ECU_FK_COLUMN} INT NOT NULL;'
)

ADD_SPEED_PID_ECU_ID_UNIQUE_DDL: str = (
    f'ALTER TABLE {SPEED_PID_CALIBRATION_TABLE} '
    f'ADD CONSTRAINT {SPEED_PID_CALIBRATION_ECU_ID_UNIQUE} '
    f'UNIQUE ({SPEED_PID_CALIBRATION_ECU_FK_COLUMN});'
)

ADD_SPEED_PID_ECU_FK_DDL: str = (
    f'ALTER TABLE {SPEED_PID_CALIBRATION_TABLE} '
    f'ADD CONSTRAINT {SPEED_PID_CALIBRATION_ECU_FK_NAME} '
    f'FOREIGN KEY ({SPEED_PID_CALIBRATION_ECU_FK_COLUMN}) REFERENCES {ECU_TABLE}(id);'
)

# Drop the transitional natural key + column.  The UNIQUE index must go first
# (the column is part of it).
DROP_SPEED_PID_ECU_SIGNATURE_UNIQUE_DDL: str = (
    f'ALTER TABLE {SPEED_PID_CALIBRATION_TABLE} '
    f'DROP INDEX {SPEED_PID_CALIBRATION_ECU_SIGNATURE_UNIQUE};'
)
DROP_SPEED_PID_ECU_SIGNATURE_COLUMN_DDL: str = (
    f'ALTER TABLE {SPEED_PID_CALIBRATION_TABLE} DROP COLUMN ecu_signature;'
)


# ---- Probes ------------------------------------------------------------------


def _countUnresolvedEcuId(ctx: RunnerContext) -> int:
    """Return how many vehicle_info rows still hold ``ecu_id IS NULL``."""
    res = _runServerSql(
        ctx.addrs, ctx.creds, COUNT_UNRESOLVED_ECU_ID_SQL, ctx.runner,
    )
    if res.returncode != 0:
        raise SchemaProbeError(
            'unresolved-ecu_id probe failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    try:
        return int(res.stdout.strip().split()[0])
    except (ValueError, IndexError):
        return 0


def _countUnresolvedSpeedPidEcuId(ctx: RunnerContext) -> int:
    """Return how many speed_pid_calibration rows still hold ``ecu_id IS NULL``."""
    res = _runServerSql(
        ctx.addrs, ctx.creds, COUNT_UNRESOLVED_SPEED_PID_SQL, ctx.runner,
    )
    if res.returncode != 0:
        raise SchemaProbeError(
            'unresolved speed_pid_calibration.ecu_id probe failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    try:
        return int(res.stdout.strip().split()[0])
    except (ValueError, IndexError):
        return 0


# ---- Substeps ----------------------------------------------------------------


def _applyEcuTable(ctx: RunnerContext) -> None:
    """Create the ecu identity dimension + seed the 3 grounded rows.

    Brand-new table, so this CREATEs (v0005 pattern): a ``serverTableExists``
    short-circuit + ``CREATE TABLE IF NOT EXISTS`` + post-condition probe.  The
    3 seeds are emitted via ``INSERT IGNORE`` on EVERY run -- not only on fresh
    create -- so a re-run, a partial-success recovery, and a
    create_all-then-migrate DB all converge to the seeded state idempotently.
    """
    freshCreate = not serverTableExists(ctx.addrs, ctx.creds, ECU_TABLE, ctx.runner)
    if freshCreate:
        res = _runServerSql(ctx.addrs, ctx.creds, CREATE_ECU_DDL, ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'create {ECU_TABLE!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )
        if not serverTableExists(ctx.addrs, ctx.creds, ECU_TABLE, ctx.runner):
            raise SchemaProbeError(
                f'{ECU_TABLE!r} missing after CREATE TABLE ran; investigate the '
                f'MariaDB session context (wrong DB? filtered replica?).',
            )

    for ddl in SEED_ECU_DDLS:
        res = _runServerSql(ctx.addrs, ctx.creds, ddl, ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f'seed {ECU_TABLE!r} failed on {ddl!r}: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )


def _applyVehicleInfoEcuIdFk(ctx: RunnerContext) -> None:
    """Add vehicle_info.ecu_id, backfill+derive, FAIL LOUDLY, NOT NULL, ADD FK.

    Runs AFTER ``_applyEcuTable`` (the FK target must exist + be seeded).  A
    column probe gates the whole block: a fresh ``create_all`` DB already owns
    ``ecu_id`` + the FK (no-op), and a prior successful run lands on the present
    column (no-op).  A genuinely unmatched row FAILS LOUDLY rather than taking a
    NULL ecu_id (US-376 conditionalOutcome 1).
    """
    if not serverTableExists(ctx.addrs, ctx.creds, VEHICLE_INFO_TABLE, ctx.runner):
        raise MigrationError(
            f'{VEHICLE_INFO_TABLE!r} table missing; v0011 cannot add ecu_id to '
            f'a non-existent table.  Investigate why create_all + v0010 did not '
            f'land the table.',
        )

    columns = probeServerColumns(ctx.addrs, ctx.creds, VEHICLE_INFO_TABLE, ctx.runner)
    if VEHICLE_INFO_ECU_FK_COLUMN in columns:
        # Already migrated (fresh create_all from the ORM, or a prior run).
        return

    # 1. ADD the column nullable so existing rows survive the ALTER.
    res = _runServerSql(ctx.addrs, ctx.creds, ADD_VEHICLE_INFO_ECU_ID_DDL, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'add {VEHICLE_INFO_ECU_FK_COLUMN!r} to {VEHICLE_INFO_TABLE!r} '
            f'failed: {res.stderr.strip() or res.stdout.strip()}',
        )

    # 2. Backfill ecu_id + derive the transitional cal_signature from the ecu row.
    res = _runServerSql(
        ctx.addrs, ctx.creds, BACKFILL_VEHICLE_INFO_ECU_ID_DDL, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'backfill {VEHICLE_INFO_TABLE!r}.ecu_id failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    # 3. FAIL LOUDLY on any unresolved row -- never NULL ecu_id (CO#1).
    unresolved = _countUnresolvedEcuId(ctx)
    if unresolved > 0:
        raise MigrationError(
            f'{unresolved} {VEHICLE_INFO_TABLE!r} row(s) have an '
            f'(ecu_signature, cal_signature) pair that matches no ecu identity '
            f'row; refusing to NULL ecu_id.  Seed the missing ecu identity '
            f'(stamp_ecu_swap / backfill) and re-run -- surface the bad data, '
            f'do not paper over it.',
        )

    # 4. Tighten to NOT NULL (all rows now resolved).
    res = _runServerSql(
        ctx.addrs, ctx.creds, MODIFY_VEHICLE_INFO_ECU_ID_NOT_NULL_DDL, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'modify {VEHICLE_INFO_ECU_FK_COLUMN!r} NOT NULL on '
            f'{VEHICLE_INFO_TABLE!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    # 5. ADD the FK (swallow duplicate on a partial-success replay).
    res = _runServerSql(ctx.addrs, ctx.creds, ADD_VEHICLE_INFO_ECU_FK_DDL, ctx.runner)
    if res.returncode != 0:
        err = (res.stderr.strip() or res.stdout.strip()).lower()
        if 'duplicate' not in err and 'already exists' not in err:
            raise MigrationError(
                f'add FK {VEHICLE_INFO_ECU_FK_NAME!r} on {VEHICLE_INFO_TABLE!r} '
                f'failed: {res.stderr.strip() or res.stdout.strip()}',
            )

    # 6. Land the append-only + ecu_id table comment (parity with create_all).
    res = _runServerSql(ctx.addrs, ctx.creds, ALTER_VEHICLE_INFO_COMMENT_DDL, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'set {VEHICLE_INFO_TABLE!r} table comment failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    # Post-condition probe: the FK column MUST be present now.
    columnsAfter = probeServerColumns(
        ctx.addrs, ctx.creds, VEHICLE_INFO_TABLE, ctx.runner,
    )
    if VEHICLE_INFO_ECU_FK_COLUMN not in columnsAfter:
        raise SchemaProbeError(
            f'{VEHICLE_INFO_ECU_FK_COLUMN!r} missing from {VEHICLE_INFO_TABLE!r} '
            f'after ADD COLUMN ran; investigate the MariaDB session context '
            f'(wrong DB? filtered replica?).',
        )


def _swallowMissingOnDrop(res, *, what: str) -> None:
    """Raise unless a DROP failed only because the target was already gone.

    Lets a partial-success replay re-enter the re-key block (gated on the
    ecu_signature column's presence) and harmlessly retry DROPs whose target a
    prior run already removed.
    """
    if res.returncode == 0:
        return
    err = (res.stderr.strip() or res.stdout.strip()).lower()
    if "can't drop" in err or 'check that' in err or "doesn't exist" in err:
        return
    raise MigrationError(
        f'{what} on {SPEED_PID_CALIBRATION_TABLE!r} failed: '
        f'{res.stderr.strip() or res.stdout.strip()}',
    )


def _applySpeedPidCalibrationRekey(ctx: RunnerContext) -> None:
    """US-374 substep: re-key speed_pid_calibration from ecu_signature to ecu_id.

    Runs AFTER ``_applyEcuTable`` (the FK target must exist + be seeded).  The
    transitional ``ecu_signature`` column's PRESENCE gates the whole block: its
    terminal absence means already re-keyed -- a fresh ``create_all`` DB (the ORM
    owns the ecu_id shape directly) and a prior successful run are both pure
    no-ops.  A calibration row whose ecu_signature matches no ecu identity row
    FAILS LOUDLY rather than taking a NULL ecu_id (US-374 conditionalOutcome 2).
    """
    if not serverTableExists(
        ctx.addrs, ctx.creds, SPEED_PID_CALIBRATION_TABLE, ctx.runner,
    ):
        raise MigrationError(
            f'{SPEED_PID_CALIBRATION_TABLE!r} table missing; v0011 cannot re-key '
            f'a non-existent table.  Investigate why v0010 did not create it.',
        )

    columns = probeServerColumns(
        ctx.addrs, ctx.creds, SPEED_PID_CALIBRATION_TABLE, ctx.runner,
    )
    if 'ecu_signature' not in columns:
        # Already re-keyed (fresh create_all from the ORM, or a prior run).
        return

    # 1. ADD the FK column nullable so existing rows survive the ALTER (swallow a
    #    duplicate-column on a partial-success replay).
    if SPEED_PID_CALIBRATION_ECU_FK_COLUMN not in columns:
        res = _runServerSql(ctx.addrs, ctx.creds, ADD_SPEED_PID_ECU_ID_DDL, ctx.runner)
        if res.returncode != 0:
            err = (res.stderr.strip() or res.stdout.strip()).lower()
            if 'duplicate' not in err and 'exists' not in err:
                raise MigrationError(
                    f'add {SPEED_PID_CALIBRATION_ECU_FK_COLUMN!r} to '
                    f'{SPEED_PID_CALIBRATION_TABLE!r} failed: '
                    f'{res.stderr.strip() or res.stdout.strip()}',
                )

    # 2. Backfill ecu_id by matching ecu_signature to the ecu identity row.
    res = _runServerSql(
        ctx.addrs, ctx.creds, BACKFILL_SPEED_PID_ECU_ID_DDL, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'backfill {SPEED_PID_CALIBRATION_TABLE!r}.ecu_id failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    # 3. Re-point the 2 seed provenance strings (Spool 2026-06-01) while the
    #    ecu_signature column still exists.
    for ddl in (REPOINT_PRIOR_ECU_PROVENANCE_DDL, REPOINT_NEW_ECU_PROVENANCE_DDL):
        res = _runServerSql(ctx.addrs, ctx.creds, ddl, ctx.runner)
        if res.returncode != 0:
            raise MigrationError(
                f're-point {SPEED_PID_CALIBRATION_TABLE!r} provenance failed on '
                f'{ddl!r}: {res.stderr.strip() or res.stdout.strip()}',
            )

    # 4. FAIL LOUDLY on any unresolved row -- never NULL ecu_id (CO#2).
    unresolved = _countUnresolvedSpeedPidEcuId(ctx)
    if unresolved > 0:
        raise MigrationError(
            f'{unresolved} {SPEED_PID_CALIBRATION_TABLE!r} row(s) have an '
            f'ecu_signature that matches no ecu identity row; refusing to NULL '
            f'ecu_id.  Seed the missing ecu identity and re-run -- surface the '
            f'bad data, do not paper over it.',
        )

    # 5. Tighten to NOT NULL (all rows now resolved).
    res = _runServerSql(
        ctx.addrs, ctx.creds, MODIFY_SPEED_PID_ECU_ID_NOT_NULL_DDL, ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'modify {SPEED_PID_CALIBRATION_ECU_FK_COLUMN!r} NOT NULL on '
            f'{SPEED_PID_CALIBRATION_TABLE!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    # 6. ADD UNIQUE(ecu_id) + the FK (swallow duplicates on a partial replay).
    for ddl in (ADD_SPEED_PID_ECU_ID_UNIQUE_DDL, ADD_SPEED_PID_ECU_FK_DDL):
        res = _runServerSql(ctx.addrs, ctx.creds, ddl, ctx.runner)
        if res.returncode != 0:
            err = (res.stderr.strip() or res.stdout.strip()).lower()
            if 'duplicate' not in err and 'exists' not in err:
                raise MigrationError(
                    f'add constraint on {SPEED_PID_CALIBRATION_TABLE!r} failed '
                    f'({ddl!r}): {res.stderr.strip() or res.stdout.strip()}',
                )

    # 7. Drop the transitional UNIQUE key, then the ecu_signature column.
    res = _runServerSql(
        ctx.addrs, ctx.creds, DROP_SPEED_PID_ECU_SIGNATURE_UNIQUE_DDL, ctx.runner,
    )
    _swallowMissingOnDrop(res, what='drop unique')
    res = _runServerSql(
        ctx.addrs, ctx.creds, DROP_SPEED_PID_ECU_SIGNATURE_COLUMN_DDL, ctx.runner,
    )
    _swallowMissingOnDrop(res, what='drop column')

    # Post-condition probe: ecu_id present, ecu_signature gone.
    columnsAfter = probeServerColumns(
        ctx.addrs, ctx.creds, SPEED_PID_CALIBRATION_TABLE, ctx.runner,
    )
    if (
        SPEED_PID_CALIBRATION_ECU_FK_COLUMN not in columnsAfter
        or 'ecu_signature' in columnsAfter
    ):
        raise SchemaProbeError(
            f'{SPEED_PID_CALIBRATION_TABLE!r} did not converge on the ecu_id '
            f'shape after re-key (cols={columnsAfter}); investigate the MariaDB '
            f'session context.',
        )


def apply(ctx: RunnerContext) -> None:
    """Apply the B-076 first-slice substeps in dependency order.

    The ecu table is created + seeded FIRST so the vehicle_info FK and the
    speed_pid_calibration re-key both have a target to reference and rows to
    resolve against.
    """
    _applyEcuTable(ctx)
    _applyVehicleInfoEcuIdFk(ctx)
    _applySpeedPidCalibrationRekey(ctx)


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
