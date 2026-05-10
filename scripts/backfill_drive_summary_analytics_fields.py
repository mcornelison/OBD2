################################################################################
# File Name: backfill_drive_summary_analytics_fields.py
# Purpose/Description: US-310 / B-059 -- one-shot SERVER-SIDE backfill for the
#                      Spec 3 12-field drive_summary contract.  Pi-sync rows for
#                      drives 3-10 currently have NULL on every analytics
#                      column (start_time / end_time / duration_seconds /
#                      row_count / is_real / data_source) because the
#                      _ensureDriveSummary writer pre-V0.27.3 either never fired
#                      OR populated them with the wrong semantics.  Post-V0.27.3
#                      the writer is fixed; this script repopulates the
#                      historical drives in-place from the existing
#                      realtime_data.  Idempotent + --dry-run preview.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex (US-310) | Initial -- server-side backfill for Spec 3
#               |              | fields 3-8 across drives 3-10.
# ================================================================================
################################################################################

"""Server-side drive_summary fields-3-8 backfill (US-310 / B-059).

Usage::

    python scripts/backfill_drive_summary_analytics_fields.py --dry-run
    python scripts/backfill_drive_summary_analytics_fields.py --execute
    python scripts/backfill_drive_summary_analytics_fields.py \\
        --device-id chi-eclipse-01 --execute

What this script does
---------------------

For every ``drive_summary`` row matching ``source_device = device_id`` AND
``drive_id IS NOT NULL`` (i.e. a post-US-200 Pi-sync row) the script
recomputes Spec 3 fields 3-8 from ``realtime_data`` filtered by
``drive_id`` -- delegating to
:func:`src.server.services.analysis._computeDriveAnalytics` so the
backfill output and the live writer share one source of truth.

If the recomputed values match what's already on the row (or the row
otherwise has nothing to backfill), the row is counted as ``skipped``.
Otherwise the analytics columns are updated in place and the row is
counted as ``populated``.

This makes the backfill idempotent: a second run finds the first run's
output already in place and reports ``populated=0, skipped=N``.

Safety posture
--------------

* ``--dry-run`` (default) lists every row that WOULD change without
  committing.  ``populated`` reports the count that would be written.
* ``--execute`` writes inside a single transaction.  No partial
  commits -- any error rolls the whole batch back.
* Spec 3 race-handling rule: Pi-sync columns (9-12) are NEVER touched
  by the backfill.  Only fields 3-8 + ``device_id`` are written.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.server.db.models import DriveSummary
from src.server.services.analysis import _computeDriveAnalytics

logger = logging.getLogger("backfill_drive_summary_analytics_fields")

DEFAULT_DEVICE_ID = "chi-eclipse-01"  # b044-exempt: canonical Eclipse Pi hostname for one-off backfill CLI; overridable via --device-id


@dataclass(frozen=True, slots=True)
class BackfillStats:
    """Outcome counts for a backfill run."""

    populated: int
    skipped: int


def backfill(
    session: Session,
    *,
    deviceId: str = DEFAULT_DEVICE_ID,
    dryRun: bool = False,
) -> BackfillStats:
    """Recompute Spec 3 fields 3-8 for every Pi-sync drive_summary row.

    Args:
        session: Open SQLAlchemy session against the server DB.
        deviceId: ``source_device`` filter.  Defaults to ``chi-eclipse-01``.
        dryRun: When True, count rows that WOULD change but do not write.

    Returns:
        :class:`BackfillStats` with ``populated`` (rows touched / would
        touch) and ``skipped`` (rows whose recomputed values matched).
    """
    rows = session.execute(
        select(DriveSummary)
        .where(DriveSummary.source_device == deviceId)
        .where(DriveSummary.drive_id.is_not(None))
        .order_by(DriveSummary.drive_id),
    ).scalars().all()

    populated = 0
    skipped = 0

    for row in rows:
        # _computeDriveAnalytics filters realtime_data by drive_id when
        # given so the fallback boundaries are unused for post-US-200
        # rows.  Pass placeholders to satisfy the signature.
        analytics = _computeDriveAnalytics(
            session,
            deviceId,
            driveId=row.drive_id,
            fallbackStartTime=row.drive_start_timestamp or row.start_time,
            fallbackEndTime=row.drive_start_timestamp or row.end_time,
        )

        currentTuple = (
            row.start_time,
            row.end_time,
            row.duration_seconds,
            row.row_count,
            row.is_real,
            row.data_source,
            row.profile_id,
            row.device_id,
        )
        targetTuple = (
            analytics.startTime,
            analytics.endTime,
            analytics.durationSeconds,
            analytics.rowCount,
            analytics.isReal,
            analytics.dataSource,
            analytics.profileId,
            deviceId,
        )

        if currentTuple == targetTuple:
            skipped += 1
            continue

        populated += 1
        if dryRun:
            logger.info(
                "[dry-run] drive_id=%s would write start=%s end=%s "
                "rows=%s is_real=%s source=%s",
                row.drive_id,
                analytics.startTime,
                analytics.endTime,
                analytics.rowCount,
                analytics.isReal,
                analytics.dataSource,
            )
            continue

        row.start_time = analytics.startTime
        row.end_time = analytics.endTime
        row.duration_seconds = analytics.durationSeconds
        row.row_count = analytics.rowCount
        row.is_real = analytics.isReal
        row.data_source = analytics.dataSource
        row.profile_id = analytics.profileId
        row.device_id = deviceId
        logger.info(
            "drive_id=%s populated start=%s end=%s rows=%s is_real=%s source=%s",
            row.drive_id,
            analytics.startTime,
            analytics.endTime,
            analytics.rowCount,
            analytics.isReal,
            analytics.dataSource,
        )

    if not dryRun:
        session.flush()

    return BackfillStats(populated=populated, skipped=skipped)


def _parseArgs(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Spec 3 drive_summary fields 3-8 from realtime_data.",
    )
    parser.add_argument(
        "--device-id",
        default=DEFAULT_DEVICE_ID,
        help=f"source_device to scope the backfill (default: {DEFAULT_DEVICE_ID}).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview rows that would be touched (default).",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Commit the backfill writes.",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config.json for the server DB URL.",
    )
    return parser.parse_args(argv)


def _buildEngine(configPath: str) -> Engine:
    """Resolve the server DB URL from config.json and build a sync engine.

    Imports are lazy so the test suite can import :func:`backfill` without
    pulling in the secrets-loader dependency chain.
    """
    from src.common.config.secrets_loader import loadConfigWithSecrets

    config = loadConfigWithSecrets(configPath)
    dbConfig = config.get("server", {}).get("database", {})
    url = dbConfig.get("url")
    if not url:
        raise RuntimeError(
            "config.json missing server.database.url -- cannot resolve "
            "server DB connection.",
        )
    return create_engine(url)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args = _parseArgs(argv)
    dryRun = not args.execute

    engine = _buildEngine(args.config)
    with Session(engine) as session:
        stats = backfill(session, deviceId=args.device_id, dryRun=dryRun)
        if not dryRun:
            session.commit()

    mode = "dry-run" if dryRun else "execute"
    logger.info(
        "[%s] device_id=%s populated=%d skipped=%d",
        mode, args.device_id, stats.populated, stats.skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
