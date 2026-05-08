################################################################################
# File Name: v0007_sync_history_retention.py
# Purpose/Description: Sprint 26 US-300 (B-053 Story 3) -- prune sync_history
#                      rows older than the 90-day retention horizon.  Captures
#                      the BL-010 audit finding (the bloating server-side table
#                      is sync_history, NOT the Pi-side sync_log cursor) and
#                      the CIO 2026-05-07 retention answer (90 days, matching
#                      Pi-side data retention).  Idempotent DELETE: re-running
#                      on a freshly-pruned DB is near-no-op (deletes 0 rows).
#                      Schema unchanged -- DELETE only, no ALTER.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex          | Initial -- Sprint 26 US-300 (B-053 Story 3,
#               |              | BL-010 close).
# ================================================================================
################################################################################

"""Migration 0007: sync_history retention pruning (US-300 / B-053 Story 3).

Context
-------
``sync_history`` accumulates one row per Pi sync attempt
(:func:`src.server.api.sync._createSyncHistoryRow` at
``src/server/api/sync.py:396-405``).  CIO observation 2026-05-05:
chi-srv-01 ``sync_history`` had grown past 100,000 rows at ~5 inserts/sec
with no retention policy in place.

BL-010 audit (Rex, 2026-05-08) established that the bloating table is
``sync_history`` (server-side per-attempt log, ``src/server/db/models.py:462``)
and NOT the Pi-side ``sync_log`` (a 10-row per-table cursor at
``src/pi/data/sync_log.py:152-161``).  The original B-053 PRD wording
conflated the names; Marcus retargeted the story 2026-05-08 and updated
the PRD banner.

This migration prunes rows whose ``started_at`` is older than the 90-day
retention horizon.  Future ongoing pruning is a separate concern (cron /
scheduled task -- not a migration).  This migration:

* Captures the retention rule as deploy-replayable artifact.
* Performs the initial cleanup on first run.
* Is safe to re-run -- subsequent runs delete 0 rows.

Idempotency contract
--------------------
1. Pre-condition probe verifies ``sync_history`` exists.  If the table is
   missing on the live DB, the migration HARD-fails rather than silently
   no-op'ing -- a missing ``sync_history`` table indicates either a fresh
   DB pre-``create_all`` or a wrong default DB context, both of which need
   operator attention.
2. ``DELETE FROM sync_history WHERE started_at < (NOW() - INTERVAL N DAY)``
   is naturally idempotent: rows already pruned cannot be re-deleted.
3. Post-condition probe asserts ``COUNT(*) FROM sync_history WHERE
   started_at < (NOW() - INTERVAL N DAY) = 0``.  Catches the silent-no-op
   class (wrong DB context, replication filter dropping the DELETE,
   etc.) -- v0005 / v0006 follow the same belt-and-suspenders pattern.
4. The :class:`src.server.migrations.MigrationRunner` records this version
   after first success; future deploys skip the ``apply()`` call entirely.

Configurability
---------------
The retention horizon defaults to 90 days
(:data:`RETENTION_DAYS_DEFAULT`).  Operators can override via the
``SYNC_HISTORY_RETENTION_DAYS`` environment variable -- useful for
disaster-recovery scenarios where a tighter or looser window is needed
without code change.  Garbage / negative values fall back to the default
rather than build a malformed clause (defensive: a misparsed env should
never delete more rows than intended).
"""

from __future__ import annotations

import os

from scripts.apply_server_migrations import (
    MigrationError,
    SchemaProbeError,
    _runServerSql,
    serverTableExists,
)
from src.server.migrations.runner import Migration, RunnerContext

__all__ = [
    'DESCRIPTION',
    'MIGRATION',
    'RETENTION_DAYS_DEFAULT',
    'RETENTION_ENV_VAR',
    'TARGET_TABLE',
    'VERSION',
    'apply',
    'buildDeleteSql',
]


VERSION: str = '0007'
DESCRIPTION: str = (
    'B-053 Story 3 (US-300, BL-010 close) -- prune sync_history rows older '
    'than 90 days; idempotent DELETE; schema unchanged'
)


# ================================================================================
# Constants
# ================================================================================

TARGET_TABLE: str = 'sync_history'

RETENTION_DAYS_DEFAULT: int = 90

RETENTION_ENV_VAR: str = 'SYNC_HISTORY_RETENTION_DAYS'


# ================================================================================
# SQL builders
# ================================================================================

def buildDeleteSql(retentionDays: int) -> str:
    """Build the parameterized DELETE statement for the retention horizon.

    MariaDB-native ``INTERVAL N DAY`` arithmetic against ``NOW()`` matches
    the ``started_at DATETIME NOT NULL DEFAULT NOW()`` column type
    (:class:`src.server.db.models.SyncHistory`).
    """
    return (
        f'DELETE FROM {TARGET_TABLE} '
        f'WHERE started_at < (NOW() - INTERVAL {retentionDays} DAY);'
    )


def _buildPostProbeSql(retentionDays: int) -> str:
    """Post-condition probe -- count any rows the DELETE should have caught."""
    return (
        f'SELECT COUNT(*) FROM {TARGET_TABLE} '
        f'WHERE started_at < (NOW() - INTERVAL {retentionDays} DAY);'
    )


# ================================================================================
# Configuration resolution
# ================================================================================

def _resolveRetentionDays() -> int:
    """Return the active retention horizon in days.

    Precedence: ``SYNC_HISTORY_RETENTION_DAYS`` env var (if a positive
    integer) -> :data:`RETENTION_DAYS_DEFAULT`.  Garbage / non-positive
    values fall back to default rather than build a malformed clause -- a
    misparsed env should never widen the deletion window beyond what an
    operator intended.
    """
    raw = os.environ.get(RETENTION_ENV_VAR)
    if raw is None:
        return RETENTION_DAYS_DEFAULT
    try:
        parsed = int(raw)
    except ValueError:
        return RETENTION_DAYS_DEFAULT
    if parsed <= 0:
        return RETENTION_DAYS_DEFAULT
    return parsed


# ================================================================================
# apply
# ================================================================================

def apply(ctx: RunnerContext) -> None:
    """Prune ``sync_history`` rows older than the retention horizon.

    Hard-fails when ``sync_history`` is missing -- a missing table on a
    deploy-time migration indicates operator error (wrong default DB,
    missing ``create_all`` run, etc.) and silently no-op'ing would mask
    a deeper problem.
    """
    if not serverTableExists(ctx.addrs, ctx.creds, TARGET_TABLE, ctx.runner):
        raise MigrationError(
            f'{TARGET_TABLE} table missing on server; cannot prune '
            f'(verify SQLAlchemy create_all has run + correct default DB)',
        )

    retentionDays = _resolveRetentionDays()

    res = _runServerSql(
        ctx.addrs, ctx.creds,
        buildDeleteSql(retentionDays),
        ctx.runner,
    )
    if res.returncode != 0:
        raise MigrationError(
            f'delete from {TARGET_TABLE} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )

    # Post-condition probe: any rows older than the horizon means the
    # DELETE silently no-op'd (wrong DB, replication filter, etc.) -- the
    # runner must NOT record this version against an unchanged retention
    # state.  Mirrors v0005 / v0006 silent-no-op guards.
    probe = _runServerSql(
        ctx.addrs, ctx.creds,
        _buildPostProbeSql(retentionDays),
        ctx.runner,
    )
    if probe.returncode != 0:
        raise SchemaProbeError(
            f'post-DELETE row-count probe on {TARGET_TABLE} failed: '
            f'{probe.stderr.strip() or probe.stdout.strip()}',
        )
    txt = probe.stdout.strip()
    try:
        staleCount = int(txt.split()[0])
    except (ValueError, IndexError):
        # Empty/malformed probe output -- treat as probe failure rather
        # than silent success.
        raise SchemaProbeError(
            f'post-DELETE row-count probe on {TARGET_TABLE} returned '
            f'unparseable output: {txt!r}',
        ) from None
    if staleCount > 0:
        raise SchemaProbeError(
            f'{TARGET_TABLE} still has {staleCount} row(s) older than '
            f'{retentionDays} days after DELETE ran; investigate the '
            f'MariaDB session context (wrong DB? replication filter?)',
        )


MIGRATION: Migration = Migration(
    version=VERSION,
    description=DESCRIPTION,
    applyFn=apply,
)
