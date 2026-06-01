################################################################################
# File Name: recompute_drive_analytics.py
# Purpose/Description: On-demand CLI for B-104 Step 1 server-side analytics
#                      recompute.  Iterates over drive_ids (single, range, or
#                      all-stale) and runs compute_drive_summary against each.
#                      Used by deploy-time backfill (US-352), nightly systemd
#                      batch, and operator-driven recomputes.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex (US-350) | Initial -- B-104 Step 1a on-demand recompute
#               |              | CLI.  --drive-id N | --drive-id-range A-B |
#               |              | --all-stale | --dry-run.  Same compute path
#               |              | the nightly batch fires (one timer fires both
#               |              | per Atlas Q1).
# 2026-05-21    | Rex (US-351) | B-104 Step 1b: invoke compute_drive_statistics
#               |              | alongside compute_drive_summary per drive_id so
#               |              | a single CLI invocation / nightly timer tick
#               |              | refreshes BOTH analytics tables (Atlas Q1
#               |              | single-timer-fires-both-paths honored).
# 2026-05-28    | Rex (US-363) | F-107: surface the data_quality tripwire flag
#               |              | per drive (OK log + a WARNING line on
#               |              | attribution_anomaly) and a run-level anomaly
#               |              | tally.  Anomaly rows are rendered, never
#               |              | dropped (downstream graceful-degradation DoD).
# ================================================================================
################################################################################

"""B-104 Step 1 -- on-demand drive analytics recompute CLI.

Usage::

    python -m server.cli.recompute_drive_analytics --drive-id 20
    python -m server.cli.recompute_drive_analytics --drive-id-range 11-20
    python -m server.cli.recompute_drive_analytics --all-stale
    python -m server.cli.recompute_drive_analytics --drive-id-range 11-20 --dry-run

The CLI is intentionally narrow: it pulls a list of Pi-local drive_ids
from one of three flags, then loops invoking ``compute_drive_summary``.
Errors on individual drives are logged but do not abort the run -- a
backfill over 10 drives where one is genuinely empty must still process
the other 9.

Idempotency comes from the compute path: re-running the CLI over a
drive that already has analytics fields produces the same output (data
values converge; modification metadata may differ).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.server.analytics.drive_statistics_compute import (
    compute_drive_statistics,
)
from src.server.analytics.drive_summary_compute import compute_drive_summary
from src.server.db.models import DATA_QUALITY_ATTRIBUTION_ANOMALY, DriveSummary

logger = logging.getLogger(__name__)


def _resolveSyncDatabaseUrl() -> str:
    """Resolve a SYNC SQLAlchemy URL from the server config.

    The production server uses an async URL (``mysql+aiomysql://``).
    This CLI runs synchronously, so we strip the async driver and use
    the matching sync one (``mysql+pymysql://``).  When ``DATABASE_URL``
    is already sync we pass it through.
    """
    from src.server.config import Settings

    settings = Settings()
    url = settings.DATABASE_URL
    if "+aiomysql" in url:
        return url.replace("+aiomysql", "+pymysql")
    if "+aiosqlite" in url:
        return url.replace("+aiosqlite", "")
    return url


def _resolveDriveIds(
    args: argparse.Namespace, session: Session,
) -> list[int]:
    """Materialize the requested drive_id list from CLI args."""
    if args.drive_id is not None:
        return [int(args.drive_id)]

    if args.drive_id_range is not None:
        return list(_parseRange(args.drive_id_range))

    if args.all_stale:
        return _findStaleDriveIds(session)

    raise SystemExit(
        "ERROR: exactly one of --drive-id, --drive-id-range, --all-stale "
        "must be provided.  See --help."
    )


def _parseRange(spec: str) -> Sequence[int]:
    """Parse ``--drive-id-range A-B`` (inclusive of both endpoints)."""
    try:
        loStr, hiStr = spec.split("-", 1)
        lo, hi = int(loStr), int(hiStr)
    except (ValueError, AttributeError) as exc:
        raise SystemExit(
            f"ERROR: --drive-id-range expects 'A-B' format, got: {spec!r}",
        ) from exc

    if lo > hi:
        raise SystemExit(
            f"ERROR: --drive-id-range low ({lo}) > high ({hi})",
        )
    return range(lo, hi + 1)


def _findStaleDriveIds(session: Session) -> list[int]:
    """Return the Pi-local drive_ids of every drive_summary with NULL analytics.

    Stale = ``start_time IS NULL`` OR ``row_count IS NULL`` -- either
    is sufficient to trigger a recompute.  Returns the union, sorted
    ascending.
    """
    rows = session.execute(
        select(DriveSummary.source_id, DriveSummary.drive_id)
        .where(
            (DriveSummary.start_time.is_(None))
            | (DriveSummary.row_count.is_(None))
        )
    ).all()

    ids: set[int] = set()
    for sourceId, driveId in rows:
        if sourceId is not None:
            ids.add(int(sourceId))
        elif driveId is not None:
            ids.add(int(driveId))
    return sorted(ids)


def _buildArgParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m server.cli.recompute_drive_analytics",
        description=(
            "B-104 Step 1: recompute drive_summary + drive_statistics "
            "from raw realtime_data."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--drive-id",
        type=int,
        metavar="N",
        help="Recompute a single Pi-local drive_id.",
    )
    group.add_argument(
        "--drive-id-range",
        type=str,
        metavar="A-B",
        help="Recompute an inclusive range, e.g. 11-20.",
    )
    group.add_argument(
        "--all-stale",
        action="store_true",
        help=(
            "Recompute every drive_summary row whose start_time or "
            "row_count is NULL."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned operations without writing.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m server.cli.recompute_drive_analytics``."""
    parser = _buildArgParser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    databaseUrl = _resolveSyncDatabaseUrl()
    engine = create_engine(databaseUrl, future=True)
    try:
        with Session(engine) as session:
            driveIds = _resolveDriveIds(args, session)
            if not driveIds:
                logger.info(
                    "recompute_drive_analytics | no drive_ids to process",
                )
                return 0

            logger.info(
                "recompute_drive_analytics | begin | count=%d | dry_run=%s",
                len(driveIds), args.dry_run,
            )

            successes = 0
            failures = 0
            skipped = 0
            anomalies = 0
            for driveId in driveIds:
                if args.dry_run:
                    logger.info(
                        "DRY-RUN | drive_id=%s | would call "
                        "compute_drive_summary + compute_drive_statistics",
                        driveId,
                    )
                    successes += 1
                    continue

                try:
                    summaryId = compute_drive_summary(session, driveId)
                    if summaryId is None:
                        # No drive_summary row OR no realtime_data: skip the
                        # statistics compute too -- it would WARN+return 0 on
                        # the same precondition.
                        skipped += 1
                        continue
                    statsWritten = compute_drive_statistics(session, driveId)
                    # US-363: surface the data_quality tripwire flag visibly.
                    # The row is written and fully readable -- the CLI never
                    # drops or refuses an anomaly row; it renders it with a
                    # marker so an operator sees the dual-attribution signal.
                    summaryRow = session.get(DriveSummary, summaryId)
                    dataQuality = (
                        summaryRow.data_quality if summaryRow is not None
                        else "?"
                    )
                    session.commit()
                    successes += 1
                    if dataQuality == DATA_QUALITY_ATTRIBUTION_ANOMALY:
                        anomalies += 1
                        logger.warning(
                            "recompute_drive_analytics | drive_id=%s | "
                            "[ATTRIBUTION_ANOMALY] | summary_id=%s | "
                            "data_quality=%s | row written + readable "
                            "(rendered, not dropped)",
                            driveId, summaryId, dataQuality,
                        )
                    logger.info(
                        "recompute_drive_analytics | drive_id=%s | OK | "
                        "summary_id=%s | drive_statistics_rows=%d | "
                        "data_quality=%s",
                        driveId, summaryId, statsWritten, dataQuality,
                    )
                except Exception as exc:  # noqa: BLE001 - CLI fault tolerance
                    session.rollback()
                    failures += 1
                    logger.error(
                        "recompute_drive_analytics | drive_id=%s | "
                        "FAILED | %s", driveId, exc, exc_info=True,
                    )

            logger.info(
                "recompute_drive_analytics | done | success=%d | "
                "skipped=%d | failed=%d | attribution_anomalies=%d",
                successes, skipped, failures, anomalies,
            )
    finally:
        engine.dispose()

    return 0


if __name__ == "__main__":
    sys.exit(main())
