################################################################################
# File Name: v0009_us351_drive_statistics_data_quality_column.py
# Purpose/Description: Sprint 41 V0.27.18 hotfix (US-357, I-041) -- ADD COLUMN
#                      ``data_quality`` to live MariaDB ``drive_statistics`` so
#                      the SQLAlchemy ``DriveStatistic`` model shipped by
#                      US-351 (Sprint 41 V0.27.17) can INSERT successfully in
#                      production.  US-351 added the column at
#                      ``src/server/db/models.py:711`` but no v0009 was filed;
#                      Step 4.9 backfill failed 10/10 with ``Unknown column
#                      'data_quality' in 'INSERT INTO'`` after the V0.27.17
#                      deploy.  Same false-pass class as US-326/US-328/US-348/
#                      US-349 (writer wired in code, fresh-DB tests via
#                      ``Base.metadata.create_all`` succeed, historical
#                      production schema diverges).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex          | Initial -- Sprint 41 V0.27.18 hotfix
#               |              | (US-357 / I-041 / B-104 Step 1b close).
# ================================================================================
################################################################################

"""Migration 0009: drive_statistics.data_quality column (US-357 / I-041 close).

Context
-------
Sprint 41 V0.27.17 US-351 ("B-104 Step 1b: server drive_statistics compute +
retire Pi table") reshaped the SQLAlchemy ``DriveStatistic`` model with Atlas
Refinement B's data-quality classification: ``below_threshold`` < 10 samples,
``sparse`` 10-99, ``full`` >= 100.  Atlas's Q4 DDL specified ``data_quality``
as a CheckConstraint-enforced enum with ``server_default='full'``.  The model
landed at ``src/server/db/models.py:711``; the compute writer at
``src/server/analytics/drive_statistics_compute.py:214`` populates the column
on every INSERT.

The gap (I-041)
---------------
US-351 shipped without a corresponding migration.  Fresh-DB unit tests pass
because ``Base.metadata.create_all(engine)`` builds the table from the live
ORM (column present).  Production MariaDB pre-dates the column; ``create_all``
is a no-op on existing tables (it never ALTERs).  US-352 Step 4.9 backfill
hit ``OperationalError (1054, "Unknown column 'data_quality' in 'INSERT INTO'")``
on every drive after V0.27.17 deploy.

This migration closes the gap with an additive ALTER TABLE that mirrors the
ORM's column shape exactly so the schema and ORM converge.

SSOT
----
``src/server/db/models.py`` is the sole SSOT for the column definition.  As
of US-351:

* ``data_quality: Mapped[str] = mapped_column(String(16), nullable=False,
  server_default='full')``
* ``CheckConstraint("data_quality IN ('full','sparse','below_threshold')",
  name='ck_drive_statistics_data_quality')``
* ``Index('idx_drive_statistics_quality', 'data_quality')``

The default ``'full'`` (not ``'unknown'`` -- the V0.27.18 dispatch note got
this wrong; ``'unknown'`` is not in the CHECK enum and would itself fail the
constraint on any row that hit the default path).  ``VARCHAR(16)`` (not
``VARCHAR(32)``).  ``ck_drive_statistics_data_quality`` constraint name +
``idx_drive_statistics_quality`` index name match the ORM verbatim so
``SHOW CREATE TABLE`` is identical across environments.

Idempotency contract
--------------------
1. :func:`probeServerColumns` short-circuits if ``data_quality`` already
   exists -- covers fresh-DB ``create_all`` (Atlas Q5 harness pattern), prior
   successful migration runs, and re-runs after manual intervention.
2. The CHECK constraint and INDEX are added only when missing -- each guarded
   by its own probe so a partial-success state from a prior run still
   converges.
3. The :class:`MigrationRunner` records version ``'0009'`` after success;
   future deploys skip the entire ``apply()`` call via the runner's tracking
   table.

Post-condition probe
--------------------
After all three DDLs run, the column MUST be present.  Failure raises
:class:`SchemaProbeError` -- shields operators from the silent mysql session-
context bug class (wrong default DB, filtered replicas) that prompted the
post-probe pattern in v0002 / v0004 / v0005 / v0008.

Reversibility
-------------
ALTER TABLE ADD COLUMN is non-destructive: existing rows get the
``server_default='full'`` value (acceptable: production has zero pre-V0.27.18
``drive_statistics`` rows -- backfill failed 10/10 per I-041, so the table
is empty).  No down-migration ships with this version; the rollback story is
"snapshot + redeploy prior version" per the runner's documented design
(``src/server/migrations/runner.py``: "No rollback machinery").
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
    DRIVE_STATISTICS_DATA_QUALITY_DEFAULT,
    DRIVE_STATISTICS_DATA_QUALITY_VALUES,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'ADD_DATA_QUALITY_COLUMN_DDL',
    'ADD_DATA_QUALITY_INDEX_DDL',
    'ADD_DATA_QUALITY_CHECK_DDL',
    'CHECK_CONSTRAINT_NAME',
    'COLUMN_NAME',
    'DESCRIPTION',
    'INDEX_NAME',
    'MIGRATION',
    'TABLE_NAME',
    'VERSION',
    'apply',
]


VERSION: str = '0009'
DESCRIPTION: str = (
    'US-357 drive_statistics.data_quality -- ADD COLUMN per US-351 ORM '
    '(I-041 close; backfill 0/10 unblocked)'
)


# Identifiers -- pinned as module constants so tests assert on them and
# the migration body uses the same names the ORM does.  Drift here breaks
# the "SHOW CREATE TABLE matches across environments" property.
TABLE_NAME: str = 'drive_statistics'
COLUMN_NAME: str = 'data_quality'
CHECK_CONSTRAINT_NAME: str = 'ck_drive_statistics_data_quality'
INDEX_NAME: str = 'idx_drive_statistics_quality'


# Build the CHECK enum list from the model's exported tuple so a future
# ORM-side addition (e.g., 'replay') trips the test_ddlAllowedValuesMatchOrm
# guard immediately rather than silently diverging in production.
_ALLOWED_VALUES_SQL: str = ','.join(
    f"'{v}'" for v in DRIVE_STATISTICS_DATA_QUALITY_VALUES
)


# DDLs mirror ``DriveStatistic`` ORM declarations.  Column shape:
#  * VARCHAR(16)    -- matches ``String(16)`` on the model
#  * NOT NULL       -- matches ``nullable=False``
#  * DEFAULT 'full' -- matches ``server_default=DRIVE_STATISTICS_DATA_QUALITY_DEFAULT``
ADD_DATA_QUALITY_COLUMN_DDL: str = (
    f"ALTER TABLE {TABLE_NAME} "
    f"ADD COLUMN {COLUMN_NAME} VARCHAR(16) NOT NULL "
    f"DEFAULT '{DRIVE_STATISTICS_DATA_QUALITY_DEFAULT}';"
)


# CHECK enforces the same enum set the ORM CheckConstraint uses.  MariaDB
# 10.2+ supports inline CHECKs added via ALTER TABLE ADD CONSTRAINT.
ADD_DATA_QUALITY_CHECK_DDL: str = (
    f"ALTER TABLE {TABLE_NAME} "
    f"ADD CONSTRAINT {CHECK_CONSTRAINT_NAME} "
    f"CHECK ({COLUMN_NAME} IN ({_ALLOWED_VALUES_SQL}));"
)


# Index on data_quality matches the ORM ``Index('idx_drive_statistics_quality',
# 'data_quality')`` declaration.  Lets analytics dashboards filter by quality
# bucket without a full table scan.
ADD_DATA_QUALITY_INDEX_DDL: str = (
    f"ALTER TABLE {TABLE_NAME} "
    f"ADD INDEX {INDEX_NAME} ({COLUMN_NAME});"
)


def apply(ctx: RunnerContext) -> None:
    """Add ``data_quality`` column + CHECK + index to live MariaDB drive_statistics.

    Each DDL is guarded by its own INFORMATION_SCHEMA probe so a partial-
    success state from a prior run converges on re-apply.  Pre-condition:
    the ``drive_statistics`` table must already exist (Sprint 41 V0.27.17
    deploy created it via :class:`Base.metadata.create_all`; v0001 catch-up
    would also have created it; we probe explicitly and raise if neither
    path landed it).
    """
    # Defensive: the table itself must exist before we can ALTER it.  In
    # production this is guaranteed (V0.27.17 deploy ran create_all
    # which built the table; that's also why the column gap was missed
    # -- create_all is a no-op on existing tables but creates fresh ones
    # with the current ORM shape).  A fresh DB through this migration
    # path also lands the table via create_all before runner invocation.
    if not serverTableExists(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner):
        raise MigrationError(
            f'{TABLE_NAME!r} table missing; v0009 cannot add column to a '
            f'non-existent table.  Investigate why create_all + earlier '
            f'migrations did not land the table.',
        )

    columns = probeServerColumns(ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner)

    # Step 1: column.  Short-circuit if already present (idempotent re-run
    # or fresh-DB create_all path).
    if COLUMN_NAME not in columns:
        res = _runServerSql(
            ctx.addrs, ctx.creds, ADD_DATA_QUALITY_COLUMN_DDL, ctx.runner,
        )
        if res.returncode != 0:
            raise MigrationError(
                f'add {COLUMN_NAME!r} to {TABLE_NAME!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    # Step 2: CHECK constraint.  Separate INFORMATION_SCHEMA probe because
    # adding the column does not add the CHECK (the ORM declares them
    # independently).  MariaDB 10.2+ stores CHECKs in
    # information_schema.CHECK_CONSTRAINTS.  We tolerate "constraint
    # already exists" on add since older MariaDB versions report this as
    # error 1826 instead of being addable IF NOT EXISTS.
    checkProbeSql = (
        "SELECT COUNT(*) FROM information_schema.CHECK_CONSTRAINTS "
        f"WHERE CONSTRAINT_SCHEMA='{ctx.creds.dbName}' "
        f"AND CONSTRAINT_NAME='{CHECK_CONSTRAINT_NAME}';"
    )
    res = _runServerSql(ctx.addrs, ctx.creds, checkProbeSql, ctx.runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'CHECK constraint probe failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    checkExists = False
    try:
        checkExists = int(res.stdout.strip().split()[0]) > 0
    except (ValueError, IndexError):
        checkExists = False
    if not checkExists:
        res = _runServerSql(
            ctx.addrs, ctx.creds, ADD_DATA_QUALITY_CHECK_DDL, ctx.runner,
        )
        if res.returncode != 0:
            # Treat duplicate-constraint as benign so a partial prior run
            # is recoverable.  Surface every other failure loud.
            err = (res.stderr.strip() or res.stdout.strip()).lower()
            if 'duplicate' not in err and 'already exists' not in err:
                raise MigrationError(
                    f'add CHECK {CHECK_CONSTRAINT_NAME!r} on '
                    f'{TABLE_NAME!r} failed: '
                    f'{res.stderr.strip() or res.stdout.strip()}',
                )

    # Step 3: index.  Reuses the existing ``indexExists`` probe from
    # apply_server_migrations.
    if not indexExists(
        ctx.addrs, ctx.creds, TABLE_NAME, INDEX_NAME, ctx.runner,
    ):
        res = _runServerSql(
            ctx.addrs, ctx.creds, ADD_DATA_QUALITY_INDEX_DDL, ctx.runner,
        )
        if res.returncode != 0:
            raise MigrationError(
                f'add INDEX {INDEX_NAME!r} on {TABLE_NAME!r} failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )

    # Post-condition probe: the column MUST be present now.  Re-probes
    # INFORMATION_SCHEMA rather than trusting the ADD-COLUMN exit code so
    # the silent mysql session-context class (wrong default DB, filtered
    # replicas) is caught loud before the runner records v0009 as applied.
    columnsAfter = probeServerColumns(
        ctx.addrs, ctx.creds, TABLE_NAME, ctx.runner,
    )
    if COLUMN_NAME not in columnsAfter:
        raise SchemaProbeError(
            f'{COLUMN_NAME!r} missing from {TABLE_NAME!r} after ADD COLUMN '
            f'ran; investigate the MariaDB session context (wrong DB? '
            f'filtered replica?).',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
