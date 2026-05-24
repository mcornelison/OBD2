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
# 2026-05-10    | Rex (US-317) | Extend per I-021 -- handle NULL-drive_id legacy
#               |              | rows (Path B) + INSERT new rows for drives in
#               |              | realtime_data without a drive_summary entry
#               |              | (Path C). BackfillStats gains `inserted` field.
# ================================================================================
################################################################################

"""Server-side drive_summary fields-3-8 backfill (US-310 / US-317 / I-021).

Usage::

    python scripts/backfill_drive_summary_analytics_fields.py --dry-run
    python scripts/backfill_drive_summary_analytics_fields.py --execute
    python scripts/backfill_drive_summary_analytics_fields.py \\
        --device-id chi-eclipse-01 --execute

What this script does
---------------------

Three paths cover every shape of orphaned / missing drive_summary state
seen on the production server post-V0.27.3 deploy:

* **Path A** -- post-US-200 rows where ``drive_id IS NOT NULL``. Recompute
  Spec 3 fields 3-8 from ``realtime_data`` filtered by ``drive_id``.
* **Path B** (US-317) -- NULL-drive_id legacy rows (drives 3-5 in
  production). Filter ``realtime_data`` by ``timestamp`` range using the
  row's existing ``start_time`` / ``end_time`` natural-key boundaries.
* **Path C** (US-317) -- drives that show up in ``realtime_data`` with a
  ``drive_id`` but have NO matching ``drive_summary`` row at all (drives
  6-10 in production -- pre-V0.27.4 the auto-analysis writer was
  short-circuited when Ollama was unreachable, so these never landed).
  INSERT a new row with key columns + analytics fields.

All three paths delegate to
:func:`src.server.services.analysis._computeDriveAnalytics` so the
backfill output and the live writer share one source of truth.

Outcome counts
--------------

* ``populated`` -- rows whose existing analytics fields were UPDATEd
  (Paths A + B). Idempotent: a second run that finds matching values
  reports populated=0.
* ``skipped`` -- rows whose recomputed values already matched (Paths A
  + B), or NULL-drive_id rows missing the boundary timestamps Path B
  needs.
* ``inserted`` -- new rows created via Path C.

Safety posture
--------------

* ``--dry-run`` (default) lists every row that WOULD change without
  committing.  ``populated`` / ``inserted`` report the counts that
  would be written.
* ``--execute`` writes inside a single transaction.  No partial
  commits -- any error rolls the whole batch back.
* Spec 3 race-handling rule: Pi-sync columns (9-12) are NEVER touched
  by Paths A + B.  Path C INSERTs leave 9-12 NULL so a later Pi-sync
  upsert lands on the same row via ``UNIQUE(source_device, source_id)``
  and only overwrites its own columns.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.server.db.models import DriveSummary, RealtimeData
from src.server.services.analysis import _computeDriveAnalytics

logger = logging.getLogger("backfill_drive_summary_analytics_fields")

DEFAULT_DEVICE_ID = "chi-eclipse-01"  # b044-exempt: canonical Eclipse Pi hostname for one-off backfill CLI; overridable via --device-id


@dataclass(frozen=True, slots=True)
class BackfillStats:
    """Outcome counts for a backfill run."""

    populated: int
    skipped: int
    inserted: int = 0


def backfill(
    session: Session,
    *,
    deviceId: str = DEFAULT_DEVICE_ID,
    dryRun: bool = False,
) -> BackfillStats:
    """Recompute / populate Spec 3 fields 3-8 across all three orphan paths.

    Three paths are evaluated in order so the membership sets they query
    against don't overlap:

    1. **Path A** -- post-US-200 ``source_device, drive_id`` rows. UPDATE
       analytics fields if they drifted from realtime_data.
    2. **Path B** -- NULL-drive_id legacy rows scoped by ``device_id``.
       UPDATE analytics fields using the row's existing ``start_time`` /
       ``end_time`` natural-key boundaries as the realtime_data filter.
    3. **Path C** -- drive_ids in realtime_data with no drive_summary
       row. INSERT a new row per missing drive.

    Args:
        session: Open SQLAlchemy session against the server DB.
        deviceId: ``source_device`` filter (also matched against
            legacy rows' ``device_id``). Defaults to ``chi-eclipse-01``.
        dryRun: When True, count rows that WOULD change but do not write.

    Returns:
        :class:`BackfillStats` with ``populated`` (rows touched -- Paths
        A + B), ``skipped`` (rows whose recomputed values matched, plus
        Path B rows missing boundary timestamps), and ``inserted`` (Path
        C new rows).
    """
    populated = 0
    skipped = 0
    inserted = 0

    # ----- Path A -- post-US-200 rows with drive_id ---------------------
    rowsWithDriveId = session.execute(
        select(DriveSummary)
        .where(DriveSummary.source_device == deviceId)
        .where(DriveSummary.drive_id.is_not(None))
        .order_by(DriveSummary.drive_id),
    ).scalars().all()

    knownDriveIds: set[int] = set()
    for row in rowsWithDriveId:
        knownDriveIds.add(row.drive_id)

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
                "[dry-run] (A) drive_id=%s would write start=%s end=%s "
                "rows=%s is_real=%s source=%s",
                row.drive_id, analytics.startTime, analytics.endTime,
                analytics.rowCount, analytics.isReal, analytics.dataSource,
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
            "(A) drive_id=%s populated start=%s end=%s rows=%s "
            "is_real=%s source=%s",
            row.drive_id, analytics.startTime, analytics.endTime,
            analytics.rowCount, analytics.isReal, analytics.dataSource,
        )

    # ----- Path B (US-317) -- NULL-drive_id legacy rows -----------------
    legacyRows = session.execute(
        select(DriveSummary)
        .where(DriveSummary.device_id == deviceId)
        .where(DriveSummary.drive_id.is_(None))
        .order_by(DriveSummary.id),
    ).scalars().all()

    for row in legacyRows:
        if row.start_time is None or row.end_time is None:
            # Without boundaries we can't filter realtime_data -- nothing
            # to compute. Count as skipped so a human can investigate.
            skipped += 1
            logger.info(
                "(B) drive_summary.id=%s skipped: no start_time/end_time",
                row.id,
            )
            continue

        analytics = _computeDriveAnalytics(
            session,
            deviceId,
            driveId=None,
            fallbackStartTime=row.start_time,
            fallbackEndTime=row.end_time,
        )

        # Preserve the legacy natural-key boundaries (start_time /
        # end_time) -- they're what defines the row's identity. Only
        # touch the derived analytics fields.
        currentTuple = (
            row.duration_seconds,
            row.row_count,
            row.is_real,
            row.data_source,
            row.profile_id,
        )
        targetTuple = (
            analytics.durationSeconds,
            analytics.rowCount,
            analytics.isReal,
            analytics.dataSource,
            analytics.profileId,
        )

        if currentTuple == targetTuple:
            skipped += 1
            continue

        populated += 1
        if dryRun:
            logger.info(
                "[dry-run] (B) drive_summary.id=%s (NULL drive_id) would write "
                "rows=%s is_real=%s source=%s",
                row.id, analytics.rowCount, analytics.isReal, analytics.dataSource,
            )
            continue

        row.duration_seconds = analytics.durationSeconds
        row.row_count = analytics.rowCount
        row.is_real = analytics.isReal
        row.data_source = analytics.dataSource
        row.profile_id = analytics.profileId
        logger.info(
            "(B) drive_summary.id=%s (NULL drive_id) populated rows=%s "
            "is_real=%s source=%s",
            row.id, analytics.rowCount, analytics.isReal, analytics.dataSource,
        )

    # ----- Path C (US-317) -- missing rows for drive_ids in realtime ----
    realtimeDriveIds = session.execute(
        select(RealtimeData.drive_id)
        .where(RealtimeData.source_device == deviceId)
        .where(RealtimeData.drive_id.is_not(None))
        .distinct(),
    ).scalars().all()

    missing = sorted(set(realtimeDriveIds) - knownDriveIds)
    for driveId in missing:
        analytics = _computeDriveAnalytics(
            session,
            deviceId,
            driveId=driveId,
            # Sentinel placeholders -- unused when driveId is set.
            fallbackStartTime=datetime.min,
            fallbackEndTime=datetime.min,
        )
        if analytics.startTime is None:
            # Drive_id present in realtime_data but no rows survived the
            # filter (would only happen on a corrupt seed). Skip.
            skipped += 1
            continue

        inserted += 1
        if dryRun:
            logger.info(
                "[dry-run] (C) drive_id=%s would INSERT start=%s end=%s "
                "rows=%s is_real=%s source=%s",
                driveId, analytics.startTime, analytics.endTime,
                analytics.rowCount, analytics.isReal, analytics.dataSource,
            )
            continue

        session.add(
            DriveSummary(
                device_id=deviceId,
                source_device=deviceId,
                source_id=driveId,
                drive_id=driveId,
                start_time=analytics.startTime,
                end_time=analytics.endTime,
                duration_seconds=analytics.durationSeconds,
                row_count=analytics.rowCount,
                profile_id=analytics.profileId,
                is_real=analytics.isReal,
                data_source=analytics.dataSource,
            ),
        )
        logger.info(
            "(C) drive_id=%s INSERTED start=%s end=%s rows=%s "
            "is_real=%s source=%s",
            driveId, analytics.startTime, analytics.endTime,
            analytics.rowCount, analytics.isReal, analytics.dataSource,
        )

    if not dryRun:
        session.flush()

    return BackfillStats(populated=populated, skipped=skipped, inserted=inserted)


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
        "[%s] device_id=%s populated=%d skipped=%d inserted=%d",
        mode, args.device_id, stats.populated, stats.skipped, stats.inserted,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
