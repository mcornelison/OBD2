################################################################################
# File Name: v0008_us312_create_baselines.py
# Purpose/Description: Sprint 29 US-312 (I-018 Layer 2 close) -- create the
#                      live MariaDB ``baselines`` table so
#                      :class:`src.server.db.models.Baseline` (declared in
#                      Sprint 9 US-162) has a matching physical table.  Spool's
#                      2026-05-09 housekeeping note Item 1 caught the gap:
#                      SHOW TABLES on chi-srv-01 obd2db does not include
#                      ``baselines``; calibration --apply path's INSERT would
#                      fail with ``Table 'obd2db.baselines' doesn't exist``.
#                      Mirrors the v0005 (dtc_log) CREATE-TABLE-IF-NOT-EXISTS
#                      pattern with a post-condition probe that surfaces silent
#                      mysql session-context bugs.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex          | Initial -- Sprint 29 US-312 (I-018 Layer 2
#               |              | close).
# ================================================================================
################################################################################

"""Migration 0008: baselines table (US-312 / I-018 Layer 2 close).

Context
-------
Sprint 9 US-162 added :func:`src.server.analytics.calibration.applyCalibration`
as the sole writer of the ``baselines`` table, plus the
:class:`src.server.db.models.Baseline` ORM model with the
``UniqueConstraint('device_id', 'parameter_name')`` upsert key.  US-162
predates the US-213 explicit migration registry (Sprint 16); the table
only ever existed in tests where SQLAlchemy ``Base.metadata.create_all()``
is the canonical writer.  Live MariaDB on chi-srv-01 has been running
since 2026-04-22 deploy without it.

I-018 surfaced the bug as a stacked failure: Layer 1 was the stdlib
``types`` shadow that crashed ``calibration.py`` at import time before
the SQL INSERT could even attempt; Layer 2 is this migration -- once
Layer 1 is fixed, the next ``--calibrate --apply`` invocation would fail
on the missing table.  Both layers ship together in V0.27.3.

Idempotency contract
--------------------
1. ``serverTableExists('baselines')`` short-circuits on a DB where the
   table already exists -- this covers both fresh-DB SQLAlchemy
   ``create_all()`` and idempotent migration re-runs.
2. ``CREATE TABLE IF NOT EXISTS`` is belt-and-suspenders with the probe.
3. The :class:`src.server.migrations.MigrationRunner` records this
   version after first success; future deploys skip the entire
   ``apply()`` call.

Post-condition probe
--------------------
* ``serverTableExists('baselines')`` MUST be True after the CREATE.
  Failure raises :class:`SchemaProbeError` -- shields operators from
  silent mysql no-op cases (wrong default DB, filtered replicas).

Schema
------
Mirrors :class:`src.server.db.models.Baseline`.  Nine columns total:
``id`` (auto-increment PK), ``device_id`` + ``parameter_name`` (the
upsert composite), ``avg_value`` (NOT NULL -- the calibrated value),
``min_value`` / ``max_value`` / ``std_dev`` / ``sample_count`` (nullable
context columns), and ``established_at`` (server-side timestamp default
NOW()).  The unique key on ``(device_id, parameter_name)`` is the
:func:`applyCalibration` upsert key -- rename or drift would break every
re-apply with ``Duplicate entry`` errors on the second run.
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
    'BASELINES_UNIQUE_NAME',
    'CREATE_BASELINES_DDL',
    'DESCRIPTION',
    'MIGRATION',
    'VERSION',
    'apply',
]


VERSION: str = '0008'
DESCRIPTION: str = (
    'US-312 baselines -- create live MariaDB calibration table mirroring '
    'Baseline ORM (I-018 Layer 2 close; calibration --apply unblocked)'
)


# Index/key names -- declared as constants so tests can assert on them
# and the upsert call site can rely on the spelling.
BASELINES_UNIQUE_NAME: str = 'uq_baselines_device_param'


# MariaDB DDL.  Column order mirrors the SQLAlchemy Baseline model so a
# stale vs migrated diff is visually obvious.  Every nullable / default
# decision matches the ORM:
#  * id, device_id, parameter_name, avg_value, established_at  NOT NULL
#  * min_value, max_value, std_dev, sample_count               NULL
#  * (device_id, parameter_name) UNIQUE -- applyCalibration upsert key
CREATE_BASELINES_DDL: str = (
    'CREATE TABLE IF NOT EXISTS baselines ('
    '    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,'
    '    device_id       VARCHAR(64) NOT NULL,'
    '    parameter_name  VARCHAR(128) NOT NULL,'
    '    avg_value       DOUBLE NOT NULL,'
    '    min_value       DOUBLE,'
    '    max_value       DOUBLE,'
    '    std_dev         DOUBLE,'
    '    sample_count    INT,'
    '    established_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,'
    f'    UNIQUE KEY {BASELINES_UNIQUE_NAME} (device_id, parameter_name)'
    ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
    '  COLLATE=utf8mb4_unicode_ci;'
)


def apply(ctx: RunnerContext) -> None:
    """Create ``baselines`` on live MariaDB if not already present.

    Idempotent via :func:`serverTableExists` short-circuit + CREATE TABLE
    IF NOT EXISTS guard.  Post-condition probe raises
    :class:`SchemaProbeError` if the table is still missing after the
    CREATE statement runs -- catches the silent-no-op class (wrong
    default DB, filtered replicas) that prompted the post-probe pattern
    in v0002 / v0004 / v0005.
    """
    # INFORMATION_SCHEMA short-circuit: cheap pre-check so the idempotent
    # re-run path doesn't even issue the CREATE statement when the table
    # is already present.
    if serverTableExists(ctx.addrs, ctx.creds, 'baselines', ctx.runner):
        return

    res = _runServerSql(ctx.addrs, ctx.creds, CREATE_BASELINES_DDL, ctx.runner)
    if res.returncode != 0:
        raise MigrationError(
            f'create baselines failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    # Post-condition probe: the CREATE returned 0 but the table must
    # actually exist before the runner records the version.  Loud failure
    # is preferable to silent no-op (e.g. mysql session pointing at the
    # wrong database).
    if not serverTableExists(ctx.addrs, ctx.creds, 'baselines', ctx.runner):
        raise SchemaProbeError(
            'baselines missing after CREATE TABLE ran; '
            'investigate the MariaDB session context',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
