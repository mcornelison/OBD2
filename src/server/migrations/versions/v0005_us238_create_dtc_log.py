################################################################################
# File Name: v0005_us238_create_dtc_log.py
# Purpose/Description: Sprint 19 US-238 -- create the live MariaDB ``dtc_log``
#                      table so :class:`src.server.db.models.DtcLog` (declared
#                      in Sprint 15 US-204) has a matching physical table.
#                      Ralph's Drive 4 health check (2026-04-29) found
#                      ``Table 'obd2db.dtc_log' doesn't exist`` (V-2).  Drive 4
#                      had DTC_COUNT=0 so no rows were lost yet, but the next
#                      drive that hits a DTC will write to Pi only.  This
#                      migration mirrors the v0002 (battery_health_log)
#                      CREATE-TABLE-IF-NOT-EXISTS pattern with a
#                      post-condition probe that surfaces silent mysql
#                      session-context bugs.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex          | Initial -- Sprint 19 US-238 (V-2 close).
# ================================================================================
################################################################################

"""Migration 0005: dtc_log table (US-238 / V-2 close).

Context
-------
Sprint 15 US-204 added Mode 03 / Mode 07 DTC retrieval on the Pi and
created the SQLite ``dtc_log`` capture table (``src/pi/obdii/dtc_log_schema.py``).
The companion server-side artifacts shipped at the same time:

* :class:`src.server.db.models.DtcLog` ORM model (Pi-shape parity with
  ``source_id`` / ``source_device`` rename per the US-194 sync convention).
* ``"dtc_log"`` registered in :data:`src.server.api.sync._TABLE_REGISTRY`.
* ``dtc_log`` registered in :data:`src.pi.data.sync_log.PK_COLUMN`.

What never landed: the physical CREATE TABLE on live MariaDB.  Sprint 15
predates the US-213 explicit migration registry (which arrived in
Sprint 16), so the table only existed for tests where SQLAlchemy
``Base.metadata.create_all()`` is the canonical writer.  The live server
has run since 2026-04-22 deploy without the table.

Drive 4's DTC_COUNT was 0 so the gap stayed dormant.  Ralph's post-deploy
health check on 2026-04-29 caught it via direct ``SHOW TABLES`` + raw
``SELECT COUNT(*) FROM dtc_log;`` returning ``ERROR 1146 (42S02): Table
'obd2db.dtc_log' doesn't exist``.  Filed as V-2 (MAJOR -- silent data loss
on the next DTC drive).

Idempotency contract
--------------------
1. ``serverTableExists('dtc_log')`` short-circuits on a DB where the table
   already exists -- this covers both fresh-DB SQLAlchemy ``create_all()``
   and idempotent migration re-runs.
2. ``CREATE TABLE IF NOT EXISTS`` is belt-and-suspenders with the probe.
3. The :class:`src.server.migrations.MigrationRunner` records this version
   after first success; future deploys skip the entire ``apply()`` call.

Post-condition probe
--------------------
* ``serverTableExists('dtc_log')`` MUST be True after the CREATE.  Failure
  raises :class:`SchemaProbeError` -- shields operators from silent mysql
  no-op cases (wrong default DB, filtered replicas).

Schema
------
Mirrors :class:`src.server.db.models.DtcLog`.  Twelve columns total: the
four Pi-sync fields (``source_id``, ``source_device``, ``synced_at``,
``sync_batch_id``) plus eight Pi-native (``dtc_code``, ``description``,
``status``, ``first_seen_timestamp``, ``last_seen_timestamp``, ``drive_id``,
``data_source`` -- and ``id`` as the auto-increment PK).  Indexes:
``uq_dtc_log_source`` on ``(source_device, source_id)`` -- the upsert key
the sync handler uses; ``ix_dtc_log_drive_id`` on ``drive_id`` -- mirrors
the ORM ``index=True`` declaration so analytics joins land on a covered
index whether ``create_all()`` or this migration built the table.
"""

from __future__ import annotations

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    serverTableExists,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'CREATE_DTC_LOG_DDL',
    'DESCRIPTION',
    'DTC_LOG_DRIVE_ID_INDEX',
    'DTC_LOG_UNIQUE_NAME',
    'MIGRATION',
    'VERSION',
    'apply',
]


VERSION: str = '0005'
DESCRIPTION: str = (
    'US-238 dtc_log -- create live MariaDB DTC capture table mirroring '
    'DtcLog ORM (V-2 close; closes silent-data-loss risk on next DTC drive)'
)


# Index/key names -- declared as constants so tests can assert on them.
DTC_LOG_UNIQUE_NAME: str = 'uq_dtc_log_source'
DTC_LOG_DRIVE_ID_INDEX: str = 'ix_dtc_log_drive_id'


# MariaDB DDL.  Column order mirrors the SQLAlchemy DtcLog model so a stale
# vs migrated diff is visually obvious.  Every nullable / default decision
# matches the ORM:
#  * id, source_id, source_device, dtc_code, status, first/last_seen_*  NOT NULL
#  * synced_at, sync_batch_id, description, drive_id, data_source       NULL/DEFAULT
#  * (source_device, source_id) UNIQUE -- Pi-sync upsert key
#  * drive_id INDEX -- per-drive analytics joins
CREATE_DTC_LOG_DDL: str = (
    'CREATE TABLE IF NOT EXISTS dtc_log ('
    '    id                    INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '    source_id             INT NOT NULL,'
    '    source_device         VARCHAR(64) NOT NULL,'
    '    synced_at             DATETIME DEFAULT CURRENT_TIMESTAMP,'
    '    sync_batch_id         INT,'
    '    dtc_code              VARCHAR(16) NOT NULL,'
    '    description           TEXT,'
    '    status                VARCHAR(16) NOT NULL,'
    '    first_seen_timestamp  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,'
    '    last_seen_timestamp   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,'
    '    drive_id              INT,'
    '    data_source           VARCHAR(16) DEFAULT "real",'
    f'    UNIQUE KEY {DTC_LOG_UNIQUE_NAME} (source_device, source_id),'
    f'    KEY {DTC_LOG_DRIVE_ID_INDEX} (drive_id)'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    '  COLLATE=utf8mb4_unicode_ci;'
)


def apply(ctx: RunnerContext) -> None:
    """Create ``dtc_log`` on live MariaDB if not already present.

    Idempotent via :func:`serverTableExists` short-circuit + CREATE TABLE
    IF NOT EXISTS guard.  Post-condition probe raises :class:`SchemaProbeError`
    if the table is still missing after the CREATE statement runs -- catches
    the silent-no-op class (wrong default DB, filtered replicas) that
    prompted the post-probe pattern in v0002 / v0004.
    """
    # INFORMATION_SCHEMA short-circuit: cheap pre-check so the idempotent
    # re-run path doesn't even issue the CREATE statement when the table is
    # already present.  Same belt-and-suspenders pattern as v0002.
    if serverTableExists(ctx.addrs, ctx.creds, 'dtc_log', ctx.runner):
        return

    res = _runServerSql(ctx.addrs, ctx.creds, CREATE_DTC_LOG_DDL, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'create dtc_log failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    # Post-condition probe: the CREATE returned 0 but the table must
    # actually exist before the runner records the version.  Loud failure
    # is preferable to silent no-op (e.g. mysql session pointing at the
    # wrong database).
    if not serverTableExists(ctx.addrs, ctx.creds, 'dtc_log', ctx.runner):
        raise SchemaProbeError(
            'dtc_log missing after CREATE TABLE ran; '
            'investigate the MariaDB session context',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
