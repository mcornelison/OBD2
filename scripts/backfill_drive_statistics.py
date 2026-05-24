################################################################################
# File Name: backfill_drive_statistics.py
# Purpose/Description: US-324 / I-024 -- one-shot SERVER-SIDE backfill that
#                      computes drive_statistics rows for drives that have a
#                      drive_summary row + realtime_data but no drive_statistics
#                      rows yet (drives 3-10 in production -- pre-V0.27.6 the only
#                      writer was runAnalysis, gated on Ollama health, so most
#                      historical drives never got stats).  Idempotent (skips
#                      already-populated drives) + --dry-run preview.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-11    | Rex (US-324) | Initial -- backfill drive_statistics for drives
#               |              | that lack them; reuses computeDriveStatistics so
#               |              | the backfill and the live writer share one
#               |              | source of truth.
# ================================================================================
################################################################################

"""Server-side ``drive_statistics`` backfill (US-324 / I-024).

Usage::

    python scripts/backfill_drive_statistics.py --dry-run
    python scripts/backfill_drive_statistics.py --execute
    python scripts/backfill_drive_statistics.py --device-id chi-eclipse-01 --execute
    python scripts/backfill_drive_statistics.py --execute --force   # recompute all

What this script does
---------------------

For every ``drive_summary`` row owned by ``--device-id`` (matched on
``device_id`` *or* ``source_device``), if the drive has no
``drive_statistics`` rows yet (and ``--force`` was not given), compute the
per-parameter aggregates from ``realtime_data`` via
:func:`src.server.analytics.basic.computeDriveStatistics` and persist one
``drive_statistics`` row per parameter.  Drives that already have stats are
skipped, so a second run is a no-op.  ``--force`` recomputes every drive
(``computeDriveStatistics`` DELETEs prior rows before re-inserting, so the
result is identical -- the flag just bypasses the skip).

Outcome counts (:class:`BackfillStats`)
---------------------------------------

* ``drivesWritten`` -- drives that got (or, in ``--dry-run``, would get)
  ``drive_statistics`` rows this run.
* ``rowsWritten`` -- total ``drive_statistics`` rows written across those
  drives.  In ``--dry-run`` this is the count of distinct
  ``parameter_name`` values found in each candidate drive's window
  (equals the rows that would be written).
* ``drivesSkipped`` -- drives already having stats (no ``--force``), or
  drives whose window contains no usable ``realtime_data``.

Safety posture
--------------

* ``--dry-run`` (default) lists every drive that WOULD change without
  committing.
* ``--execute`` delegates each drive to ``computeDriveStatistics``, which
  commits per drive (so a failure on drive N does not roll back drives
  1..N-1 -- mirrors the live writer's per-drive commit semantics).
* This script only ever writes ``drive_statistics`` rows.  It never
  touches ``drive_summary``, ``realtime_data``, or any synced table.
"""

from __future__ import annotations

# ---- sys.path bootstrap (mirrors src/server/analytics/calibration.py) --------
# Direct script invocation (``python scripts/backfill_drive_statistics.py``)
# puts the script's own directory at ``sys.path[0]`` and does NOT include the
# repo root, so ``from src.server... import ...`` below crashes with
# ``ModuleNotFoundError: No module named 'src'``.  Inserting the repo root
# resolves that without requiring callers to set PYTHONPATH.  Idempotent for
# library importers (pytest already has ``src`` resolvable), so the duplicate
# entry is benign.
import sys as _bootstrapSys
from pathlib import Path as _BootstrapPath

_bootstrapSys.path.insert(
    0, str(_BootstrapPath(__file__).resolve().parent.parent),
)

import argparse
import logging
from dataclasses import dataclass

from sqlalchemy import and_, create_engine, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.server.analytics.basic import computeDriveStatistics
from src.server.db.models import DriveStatistic, DriveSummary, RealtimeData

logger = logging.getLogger("backfill_drive_statistics")

DEFAULT_DEVICE_ID = "chi-eclipse-01"  # b044-exempt: canonical Eclipse Pi hostname for one-off backfill CLI; overridable via --device-id


@dataclass(frozen=True, slots=True)
class BackfillStats:
    """Outcome counts for a drive_statistics backfill run."""

    drivesWritten: int
    rowsWritten: int
    drivesSkipped: int


def _existingStatsCount(session: Session, driveSummaryId: int) -> int:
    """Return the number of ``drive_statistics`` rows already keyed on a drive."""
    return int(
        session.execute(
            select(func.count())
            .select_from(DriveStatistic)
            .where(DriveStatistic.drive_id == driveSummaryId),
        ).scalar_one(),
    )


def _distinctParameterCount(session: Session, drive: DriveSummary) -> int:
    """Count distinct ``realtime_data`` parameters in a drive's window.

    Mirrors the filter :func:`src.server.analytics.basic.computeDriveStatistics`
    applies (``_collectReadings``): same ``source_device`` as the drive's
    ``device_id``, ``timestamp`` within ``[start_time, end_time]``, and a
    ``data_source`` of ``'real'`` or ``NULL`` (pre-US-195 BC).  Each
    parameter that survives the filter has at least one reading, so this
    equals the number of ``drive_statistics`` rows
    ``computeDriveStatistics`` would write -- which is what ``--dry-run``
    reports.
    """
    if drive.device_id is None or drive.start_time is None:
        return 0
    filters = [
        RealtimeData.source_device == drive.device_id,
        RealtimeData.timestamp >= drive.start_time,
        or_(
            RealtimeData.data_source == "real",
            RealtimeData.data_source.is_(None),
        ),
    ]
    if drive.end_time is not None:
        filters.append(RealtimeData.timestamp <= drive.end_time)
    return int(
        session.execute(
            select(func.count(func.distinct(RealtimeData.parameter_name)))
            .where(and_(*filters)),
        ).scalar_one(),
    )


def backfill(
    session: Session,
    *,
    deviceId: str = DEFAULT_DEVICE_ID,
    dryRun: bool = False,
    force: bool = False,
) -> BackfillStats:
    """Compute ``drive_statistics`` for drives that don't have any yet.

    Args:
        session: Open SQLAlchemy session against the server DB.
        deviceId: Device filter -- a ``drive_summary`` row matches if its
            ``device_id`` *or* ``source_device`` equals this value.
        dryRun: When True, report the drives / rows that WOULD be written
            without writing anything.
        force: When True, recompute every matched drive even if it already
            has ``drive_statistics`` rows (``computeDriveStatistics``
            DELETEs prior rows first, so the end state is identical).

    Returns:
        :class:`BackfillStats`.
    """
    summaryRows = session.execute(
        select(DriveSummary)
        .where(
            or_(
                DriveSummary.device_id == deviceId,
                DriveSummary.source_device == deviceId,
            ),
        )
        .order_by(DriveSummary.id),
    ).scalars().all()

    drivesWritten = 0
    rowsWritten = 0
    drivesSkipped = 0

    prefix = "[dry-run] " if dryRun else ""
    for row in summaryRows:
        if not force and _existingStatsCount(session, row.id) > 0:
            drivesSkipped += 1
            logger.info(
                "drive_summary.id=%s skipped: already has drive_statistics rows",
                row.id,
            )
            continue

        # Count distinct parameters in the drive's window first.  This both
        # gives the dry-run row estimate AND guards the execute path:
        # computeDriveStatistics' time-window filter does
        # ``timestamp >= drive.start_time``, which SQLAlchemy refuses when
        # start_time is None (a Pi-sync-only stub row).
        paramCount = _distinctParameterCount(session, row)
        if paramCount == 0:
            drivesSkipped += 1
            logger.info(
                "%sdrive_summary.id=%s skipped: no usable realtime_data",
                prefix, row.id,
            )
            continue

        if dryRun:
            drivesWritten += 1
            rowsWritten += paramCount
            logger.info(
                "[dry-run] drive_summary.id=%s would write %d drive_statistics rows",
                row.id, paramCount,
            )
            continue

        stats = computeDriveStatistics(session, row.id)
        drivesWritten += 1
        rowsWritten += len(stats)
        logger.info(
            "drive_summary.id=%s wrote %d drive_statistics rows",
            row.id, len(stats),
        )

    return BackfillStats(
        drivesWritten=drivesWritten,
        rowsWritten=rowsWritten,
        drivesSkipped=drivesSkipped,
    )


def _parseArgs(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill drive_statistics rows from realtime_data.",
    )
    parser.add_argument(
        "--device-id",
        default=DEFAULT_DEVICE_ID,
        help=f"device filter (device_id or source_device; default: {DEFAULT_DEVICE_ID}).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview drives that would be touched (default).",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Commit the backfill writes.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute drives that already have drive_statistics rows.",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config.json for the server DB URL.",
    )
    return parser.parse_args(argv)


def _buildEngine(configPath: str) -> Engine:
    """Resolve the server DB URL from config.json and build a sync engine.

    Lazy imports so the test suite can import :func:`backfill` without
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
        stats = backfill(
            session, deviceId=args.device_id, dryRun=dryRun, force=args.force,
        )
        if not dryRun:
            session.commit()

    mode = "dry-run" if dryRun else "execute"
    logger.info(
        "[%s] device_id=%s drives_written=%d rows_written=%d drives_skipped=%d",
        mode, args.device_id, stats.drivesWritten, stats.rowsWritten,
        stats.drivesSkipped,
    )
    return 0


if __name__ == "__main__":
    _bootstrapSys.exit(main())
