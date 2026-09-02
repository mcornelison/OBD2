################################################################################
# File Name: v0025_arch020_maintenance_record.py
# Purpose/Description: ARCH-020 -- create maintenance_log and
#                      maintenance_schedule on obd2db. The vehicle's service
#                      history is the last load-bearing project fact with no
#                      home in the database.
# Author: Atlas (Architect)
# Creation Date: 2026-09-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-01    | Atlas        | Initial -- CIO-directed build (charter s2
#               |              | override recorded in board/wip/ARCH-020.md).
# ================================================================================
################################################################################

"""Migration 0025: the vehicle maintenance record (ARCH-020).

Why this table exists at all
----------------------------

``SHOW TABLES`` on ``obd2db`` carried **no** maintenance, service or odometer
surface -- 30 tables, and the nearest was ``vehicle_info`` holding two ECU-epoch
rows.  Meanwhile 47 dated events and 26 odometer readings, assembled from five
independent sources, lived **only** as Markdown on the fleet share.

On 2026-09-01 that share was confirmed to have **no snapshots and no undo of any
kind**: the volume is ext4 on RAID 5 and Synology Snapshot Replication requires
Btrfs, so none were ever taken and none can be until the volume is rebuilt.  RAID
5 is redundancy, not backup -- it survives a disk failing, not a truncating
script, because the corruption mirrors faithfully across the array.

That is not hypothetical here.  In S41 a script opened a 22,588-byte knowledge
file with mode ``"w"`` -- which truncates immediately -- then raised before
writing a byte.  The content survived **only** because a copy also lived in
``obd2db.drive_annotations``.  The maintenance record had no such copy.  This
migration gives it one.

Why the columns are shaped the way they are
-------------------------------------------

This is the first table in the project fed entirely by humans and paper, so the
failure modes are provenance failure modes rather than sensor ones.

**Date precision is stated, never implied.**  The record holds exact days
(``2008-05-08``), a bare month (``May 2025``) and an owner-estimated four-year
window (spark plugs).  A plain ``DATE NOT NULL`` forces a loader to write
``2025-05-01`` for "May 2025", manufacturing a day no source recorded.  That is
SSOT rule A's corollary -- *landing must not manufacture a reading* -- applied to
a date.  ``event_date_precision`` therefore has **no default**: a precision
acquired by omission is exactly the silent lie the column exists to prevent.

**An odometer and its source are ONE fact**, enforced by
``ck_maintenance_log_odometer_paired``.  There is no odometer PID on a 1998 4G63;
every figure is operator- or shop-supplied, so an unattributed mileage cannot be
distinguished from a guess.  The tiers matter concretely: every Illinois
emissions odometer in this history is a round thousand while shop records are
exact, which **manufactures an apparent rollback** -- 77,000 on 2022-04-12, then
76,961 on 2022-10-11, six months later and lower.  A schema without source tiers
cannot resolve that pair, and a naive integrity check would flag a healthy car as
tampered.

**The verbatim source wording is kept beside the normalised category.**  Carfax
rendered the repair order's *"Reset PCM memory"* as *"Computer reprogrammed"*,
which manufactured a conflict with the prior ECU's never-flashed status that
stood as unresolvable until the primary document was read.  A normalised summary
is a lossy view of a record and the loss is not random: it flattens distinctions
exactly where they matter.

**``last_done_confidence`` has no default, and it is the most load-bearing
column in either table.**  The timing belt's only candidate in 28 years is a 2008
*"60,000 MILE SERVICE"* that never names a belt; no timing-belt line item appears
in any of four independent sources.  If this column defaulted to ``confirmed``,
the single most dangerous row in the record would acquire the safest value by
omission, and the first query anyone ran would report the belt as serviced in
2008.  The 4G63 is an **interference engine**; the interval is 60,000 miles OR
5 years; the car is ~10k miles into it and 18.3 years into it.

**Three interval columns, any of which can fire.**  Usage measured across three
independent segments of this car's history runs ~460-500 mi/yr, so a 60,000-mile
interval would take 120 years.  On this vehicle only calendar intervals can ever
fire, and a mileage-only schema would report that belt as healthy.

Forward-only and idempotent
---------------------------

``CREATE TABLE IF NOT EXISTS`` with an existence probe before and a post-condition
probe after, matching v0013 / v0017.  Re-running is a no-op.

⚠️ **The A-10 trap does not apply here and the reason is worth stating**, because
five occurrences of it are catalogued in this project: ``CREATE TABLE IF NOT
EXISTS`` is a **silent no-op on an existing table**, so it can never be used to
ALTER one.  These are new tables that exist nowhere, which is the only situation
in which that idiom is safe.  A future column added to either table needs its own
migration with its own ``information_schema`` probe -- never an edit to this file.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    _runServerSql,
    serverTableExists,
)
from src.server.db.models import (
    CK_MAINTENANCE_DATE_PRECISION,
    CK_MAINTENANCE_ODOMETER_PAIRED,
    CK_MAINTENANCE_ODOMETER_SOURCE,
    CK_MAINTENANCE_RANGE_END,
    CK_SCHEDULE_CONFIDENCE,
    CK_SCHEDULE_SOME_INTERVAL,
    EVENT_DATE_PRECISION_VALUES,
    LAST_DONE_CONFIDENCE_VALUES,
    MAINTENANCE_LOG_TABLE,
    MAINTENANCE_SCHEDULE_TABLE,
    ODOMETER_SOURCE_VALUES,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'CREATE_MAINTENANCE_LOG_DDL',
    'CREATE_MAINTENANCE_SCHEDULE_DDL',
    'DESCRIPTION',
    'MIGRATION',
    'VERSION',
    'apply',
]


VERSION: str = '0025'
DESCRIPTION: str = (
    'ARCH-020 -- maintenance_log + maintenance_schedule: the vehicle service '
    'record gets a durable home in obd2db, with per-field provenance, stated '
    'date precision, odometer source tiers, and a last-done confidence that '
    'keeps an inferred timing-belt service from reading as a confirmed one'
)


def _sqlEnum(values: tuple[str, ...]) -> str:
    """Render a value tuple for a CHECK ... IN (...) clause."""
    return ','.join(f"'{v}'" for v in values)


# Constraint names + enum contents come from models.py so create_all and this
# migration produce an IDENTICAL SHOW CREATE TABLE.  Define-once: a tier added to
# the ORM tomorrow is carried here without editing this file (A-4 discipline).
CREATE_MAINTENANCE_LOG_DDL: str = (
    f'CREATE TABLE IF NOT EXISTS {MAINTENANCE_LOG_TABLE} ('
    '  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '  event_date DATE NOT NULL,'
    '  event_date_precision VARCHAR(8) NOT NULL,'
    '  event_date_end DATE NULL,'
    '  odometer_mi INT NULL,'
    '  odometer_source VARCHAR(32) NULL,'
    '  work_performed TEXT NOT NULL,'
    '  source_verbatim TEXT NULL,'
    '  dtc_code VARCHAR(16) NULL,'
    '  venue VARCHAR(128) NULL,'
    '  document_ref VARCHAR(64) NULL,'
    '  source_document_path TEXT NULL,'
    '  parts TEXT NULL,'
    '  part_customer_supplied TINYINT(1) NULL,'
    '  cost_usd FLOAT NULL,'
    '  is_epoch_boundary TINYINT(1) NOT NULL DEFAULT 0,'
    '  provenance TEXT NOT NULL,'
    '  notes TEXT NULL,'
    '  recorded_by VARCHAR(64) NOT NULL,'
    '  recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,'
    f'  CONSTRAINT {CK_MAINTENANCE_ODOMETER_PAIRED} CHECK ('
    '    (odometer_mi IS NULL AND odometer_source IS NULL)'
    '    OR (odometer_mi IS NOT NULL AND odometer_source IS NOT NULL)),'
    f'  CONSTRAINT {CK_MAINTENANCE_DATE_PRECISION} CHECK ('
    f'    event_date_precision IN ({_sqlEnum(EVENT_DATE_PRECISION_VALUES)})),'
    f'  CONSTRAINT {CK_MAINTENANCE_ODOMETER_SOURCE} CHECK ('
    '    odometer_source IS NULL OR odometer_source IN '
    f'    ({_sqlEnum(ODOMETER_SOURCE_VALUES)})),'
    f'  CONSTRAINT {CK_MAINTENANCE_RANGE_END} CHECK ('
    "    (event_date_precision = 'range' AND event_date_end IS NOT NULL)"
    "    OR (event_date_precision <> 'range' AND event_date_end IS NULL)),"
    '  INDEX ix_maintenance_log_event_date (event_date)'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 '
    "COLLATE=utf8mb4_unicode_ci COMMENT='ARCH-020: what was DONE to the "
    "vehicle. Provenance is PER FIELD in the provenance column, never per row.';"
)

CREATE_MAINTENANCE_SCHEDULE_DDL: str = (
    f'CREATE TABLE IF NOT EXISTS {MAINTENANCE_SCHEDULE_TABLE} ('
    '  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '  item VARCHAR(128) NOT NULL,'
    '  interval_miles INT NULL,'
    '  interval_months INT NULL,'
    '  interval_engine_hours INT NULL,'
    '  last_done_log_id INT NULL,'
    '  last_done_confidence VARCHAR(16) NOT NULL,'
    '  notes TEXT NULL,'
    '  recorded_by VARCHAR(64) NOT NULL,'
    '  recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,'
    '  CONSTRAINT uq_maintenance_schedule_item UNIQUE (item),'
    f'  CONSTRAINT {CK_SCHEDULE_SOME_INTERVAL} CHECK ('
    '    interval_miles IS NOT NULL OR interval_months IS NOT NULL'
    '    OR interval_engine_hours IS NOT NULL),'
    f'  CONSTRAINT {CK_SCHEDULE_CONFIDENCE} CHECK ('
    f'    last_done_confidence IN ({_sqlEnum(LAST_DONE_CONFIDENCE_VALUES)})),'
    '  CONSTRAINT fk_schedule_last_done_log FOREIGN KEY (last_done_log_id)'
    f'    REFERENCES {MAINTENANCE_LOG_TABLE} (id)'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 '
    "COLLATE=utf8mb4_unicode_ci COMMENT='ARCH-020: what is DUE. Three interval "
    "columns because at ~500 mi/yr only calendar intervals can ever fire.';"
)


def _createTable(ctx: RunnerContext, tableName: str, ddl: str) -> None:
    """Create one table if absent, then PROVE it landed.

    The post-condition probe is not ceremony.  ``CREATE TABLE IF NOT EXISTS``
    reports success when it does nothing, so without a probe a wrong-database
    session context (a filtered replica, a wrong default DB) would report a clean
    migration having created no table at all.
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
    """Create both maintenance tables.

    Ordering is load-bearing: ``maintenance_schedule.last_done_log_id`` carries a
    FOREIGN KEY to ``maintenance_log.id``, so the log must exist first or the
    schedule's CREATE fails with a bare errno 150 that names neither table.
    """
    _createTable(ctx, MAINTENANCE_LOG_TABLE, CREATE_MAINTENANCE_LOG_DDL)
    _createTable(ctx, MAINTENANCE_SCHEDULE_TABLE, CREATE_MAINTENANCE_SCHEDULE_DDL)


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
