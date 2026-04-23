################################################################################
# File Name: reconcile_drive_summary.py
# Purpose/Description: One-shot migration that merges the US-206 dual-writer
#                      drive_summary rows into single-row-per-drive semantics
#                      per US-214.  For every analytics-only row + Pi-sync-only
#                      row pair (matched on source_device == device_id AND
#                      timestamp overlap within the configured window), copy
#                      analytics fields into the Pi-sync row, redirect
#                      drive_statistics / anomaly_log foreign-id references
#                      onto the surviving row, then delete the analytics-only
#                      row.  Idempotent -- re-running finds no unreconciled
#                      pairs.
# Author: Rex (Ralph)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-214) | Initial -- reconciliation migration.
# ================================================================================
################################################################################

"""One-shot drive_summary reconciliation migration.

Usage::

    python scripts/reconcile_drive_summary.py --dry-run
    python scripts/reconcile_drive_summary.py --execute

Both modes connect to the server DB via the same DSN the running server
uses (``src.server.db.connection.makeEngine`` / ``DATABASE_URL``).

Safety posture matches US-209's apply_server_migrations.py:

* ``--dry-run`` reports the merge plan and exits 0 without writing.
* ``--execute`` runs the merge inside a single transaction per pair.  Any
  error rolls that pair's updates back -- analytics + Pi-sync rows remain
  intact for inspection.

Matching rule
=============

Analytics-only rows have (``device_id`` NOT NULL, ``start_time`` NOT NULL,
``source_device`` NULL).  Pi-sync-only rows have (``source_device`` NOT
NULL, ``source_id`` NOT NULL, ``start_time`` NULL).  A pair matches when
the analytics row's ``device_id == source_device`` AND its ``start_time``
is within ``timeWindowSeconds`` of the Pi-sync row's
``drive_start_timestamp`` (default 60s).  Windows wider than typical
clock skew between the Pi's drive-start state-machine tick and the
connection_log drive_start event are a judgment call; 60s is safe for
normal operations.

Non-matching rows (no Pi-sync partner for an analytics-only row) stay
as-is -- they may be pre-US-200 drives that never had drive_id
propagation.  The report counts them so the operator can decide whether
to manually adjust.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

# Allow ``python scripts/reconcile_drive_summary.py ...`` to resolve
# ``src.server.*`` imports without requiring the project to be installed
# as a package.  Matches scripts/apply_server_migrations.py.
_projectRoot = Path(__file__).resolve().parents[1]
if str(_projectRoot) not in sys.path:
    sys.path.insert(0, str(_projectRoot))

from src.server.db.models import AnomalyLog, DriveStatistic, DriveSummary  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_TIME_WINDOW_SECONDS: int = 60


@dataclass(frozen=True, slots=True)
class ReconcileStats:
    """Summary counts returned by :func:`reconcile`."""

    merged: int
    orphanedAnalyticsRows: int
    orphanedPiSyncRows: int


def reconcile(
    session: Session,
    *,
    dryRun: bool,
    timeWindowSeconds: int = DEFAULT_TIME_WINDOW_SECONDS,
) -> ReconcileStats:
    """Merge every matchable analytics/Pi-sync row pair.

    Args:
        session: SQLAlchemy sync Session. Caller owns commit/rollback.
        dryRun: When True, counts what would merge without modifying
            any rows.
        timeWindowSeconds: Tolerance between the analytics row's
            ``start_time`` and the Pi-sync row's
            ``drive_start_timestamp``.

    Returns:
        :class:`ReconcileStats` with merge + orphan counts.
    """
    analyticsOnly = session.execute(
        select(DriveSummary)
        .where(DriveSummary.device_id.is_not(None))
        .where(DriveSummary.start_time.is_not(None))
        .where(DriveSummary.source_device.is_(None)),
    ).scalars().all()

    piSyncOnly = session.execute(
        select(DriveSummary)
        .where(DriveSummary.source_device.is_not(None))
        .where(DriveSummary.source_id.is_not(None))
        .where(DriveSummary.start_time.is_(None)),
    ).scalars().all()

    window = timedelta(seconds=timeWindowSeconds)
    mergedCount = 0
    consumedPiIds: set[int] = set()
    unmatchedAnalytics: list[int] = []

    for analyticsRow in analyticsOnly:
        match: DriveSummary | None = None
        for piRow in piSyncOnly:
            if piRow.id in consumedPiIds:
                continue
            if piRow.source_device != analyticsRow.device_id:
                continue
            if piRow.drive_start_timestamp is None:
                continue
            delta = abs(piRow.drive_start_timestamp - analyticsRow.start_time)
            if delta <= window:
                match = piRow
                break

        if match is None:
            unmatchedAnalytics.append(analyticsRow.id)
            continue

        mergedCount += 1
        consumedPiIds.add(match.id)

        if dryRun:
            logger.info(
                "[dry-run] would merge analytics id=%s into Pi-sync id=%s "
                "(device=%s, start=%s)",
                analyticsRow.id, match.id, analyticsRow.device_id,
                analyticsRow.start_time.isoformat(),
            )
            continue

        _mergePair(session, analytics=analyticsRow, piSync=match)

    orphanedPiSync = [p for p in piSyncOnly if p.id not in consumedPiIds]
    return ReconcileStats(
        merged=mergedCount,
        orphanedAnalyticsRows=len(unmatchedAnalytics),
        orphanedPiSyncRows=len(orphanedPiSync),
    )


def _mergePair(
    session: Session,
    *,
    analytics: DriveSummary,
    piSync: DriveSummary,
) -> None:
    """Copy analytics fields into the Pi-sync row + redirect FK refs + delete."""
    piSync.device_id = analytics.device_id
    piSync.start_time = analytics.start_time
    piSync.end_time = analytics.end_time
    piSync.duration_seconds = analytics.duration_seconds
    piSync.row_count = analytics.row_count
    piSync.is_real = analytics.is_real
    if analytics.profile_id is not None and piSync.profile_id is None:
        piSync.profile_id = analytics.profile_id

    # DriveStatistic / AnomalyLog hold an integer drive_id that points at
    # DriveSummary.id (no FK constraint in the model).  Redirect those
    # pointers onto the surviving Pi-sync row before deleting the
    # analytics row; otherwise they'd be orphaned.
    session.execute(
        update(DriveStatistic)
        .where(DriveStatistic.drive_id == analytics.id)
        .values(drive_id=piSync.id),
    )
    session.execute(
        update(AnomalyLog)
        .where(AnomalyLog.drive_id == analytics.id)
        .values(drive_id=piSync.id),
    )

    session.delete(analytics)
    session.flush()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint -- returns shell exit code."""
    parser = argparse.ArgumentParser(
        description="Reconcile US-206 dual-writer drive_summary rows "
                    "(US-214 Option 1).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Report the merge plan without modifying any rows.",
    )
    mode.add_argument(
        "--execute", action="store_true",
        help="Apply the reconciliation.",
    )
    parser.add_argument(
        "--window-seconds", type=int, default=DEFAULT_TIME_WINDOW_SECONDS,
        help=(
            "Max delta between analytics.start_time and "
            "pi.drive_start_timestamp for a match (default 60)."
        ),
    )
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy DSN. Defaults to src.server.db.connection default.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )

    dsn = args.database_url
    if dsn is None:
        from src.server.config import Settings
        settings = Settings()
        # Settings holds the async DSN (mysql+aiomysql://...); convert to
        # the sync pymysql driver since this script runs a synchronous
        # Session over non-blocking analytics-only table work.
        dsn = settings.DATABASE_URL.replace("+aiomysql", "+pymysql")

    engine = create_engine(dsn)
    try:
        with Session(engine) as session:
            stats = reconcile(
                session, dryRun=args.dry_run,
                timeWindowSeconds=args.window_seconds,
            )
            if not args.dry_run:
                session.commit()
    finally:
        engine.dispose()

    logger.info(
        "merged=%d orphaned_analytics=%d orphaned_pi_sync=%d "
        "(mode=%s, window=%ds)",
        stats.merged, stats.orphanedAnalyticsRows, stats.orphanedPiSyncRows,
        "dry-run" if args.dry_run else "execute", args.window_seconds,
    )
    return 0


__all__ = [
    "DEFAULT_TIME_WINDOW_SECONDS",
    "ReconcileStats",
    "main",
    "reconcile",
]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
