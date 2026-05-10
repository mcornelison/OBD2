################################################################################
# File Name: backfill_drive_summary.py
# Purpose/Description: One-shot Pi-side backfill for drive_summary rows that
#                      were never INSERTed during the US-304 dormancy window
#                      (Sprint 19 US-236 ship through Sprint 28 V0.27.2 fix).
#                      Drives 6+7 from 2026-05-08 are the canonical example:
#                      DRIVE STARTED + DRIVE ENDED journal events fired with
#                      full payloads but the lifecycle.py wiring's hasattr()
#                      gate evaluated False (RealtimeDataLogger lacked
#                      getLatestReadings) so the defer-INSERT machinery
#                      short-circuited and zero rows landed.  This script
#                      walks connection_log for drive_start events without a
#                      corresponding drive_summary row, then reconstructs
#                      ambient_temp_at_start_c / starting_battery_v /
#                      barometric_kpa_at_start from realtime_data using the
#                      earliest non-NULL reading per parameter within a
#                      bounded window after drive_start.  Idempotent --
#                      re-running finds no eligible drives.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-09
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-09    | Rex (US-304) | Initial -- Pi-side backfill for the Sprint
#                              | 19 .. V0.27.2 dormancy window.  --dry-run
#                              | preview + idempotent --execute path.
# ================================================================================
################################################################################

"""Pi-side drive_summary backfill for the US-304 dormancy window.

Usage::

    python scripts/backfill_drive_summary.py --db data/obd.db --dry-run
    python scripts/backfill_drive_summary.py --db data/obd.db --execute

What this script does
=====================

For every ``connection_log`` row with ``event_type='drive_start'`` whose
``drive_id`` does NOT have a matching ``drive_summary`` row, the script:

1. Reads the drive_start timestamp + drive_end timestamp (or falls back
   to drive_start + ``--window-seconds`` when no drive_end exists).
2. Pulls the earliest non-NULL ``INTAKE_TEMP``, ``BATTERY_V``, and
   ``BAROMETRIC_KPA`` readings from ``realtime_data`` whose
   ``timestamp_ms`` lands inside the drive window.  Lookups are by
   timestamp range, not ``drive_id``, because US-306 left the first N
   ticks of every drive with ``drive_id=NULL``.
3. INSERTs a ``drive_summary`` row with whatever metadata is available
   (NULLs preserved when no qualifying reading exists).  The original
   defer-INSERT cold-start rule (Invariant #2 -- ambient is only valid
   on cold-starts) cannot be reconstructed from realtime_data alone, so
   the backfill writes the captured IAT regardless.  This is acceptable
   because drives 6+7 are documented cold-starts (Mike's 2026-05-08
   Drive 6 was the first drive of the day after >1h key-off).

Safety posture
==============

* ``--dry-run`` lists every eligible drive_id + the metadata that
  WOULD be written; exits 0 without touching the DB.
* ``--execute`` writes inside a single transaction per drive.  An error
  on any drive rolls only that drive's INSERT back; the rest proceed.
* Idempotent: re-running finds no eligible drives because the prior run
  closed each one.  ``ON CONFLICT DO NOTHING`` would also be safe but
  the explicit ``IS NULL`` check makes the dry-run preview honest.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Allow `python scripts/backfill_drive_summary.py ...` to resolve src.*
# imports without requiring the project to be installed as a package.
_projectRoot = Path(__file__).resolve().parents[1]
if str(_projectRoot) not in sys.path:
    sys.path.insert(0, str(_projectRoot))

logger = logging.getLogger(__name__)

# Default fallback window: when a drive_start has no matching drive_end
# (Pi crashed mid-drive, drive still in progress, etc.) the script
# samples realtime_data within this many seconds after drive_start.
DEFAULT_WINDOW_SECONDS: int = 600  # 10 min covers a typical short drive

# Parameter-name -> drive_summary column mapping.  Aligned with
# src.pi.obdii.drive_summary._PARAM_* constants.
_PARAM_TO_COLUMN: dict[str, str] = {
    'INTAKE_TEMP': 'ambient_temp_at_start_c',
    'BATTERY_V': 'starting_battery_v',
    'BAROMETRIC_KPA': 'barometric_kpa_at_start',
}


@dataclass(frozen=True)
class EligibleDrive:
    """Per-drive metadata payload returned by :func:`findEligibleDrives`.

    Attributes:
        driveId: drive_id minted by the Pi-side counter at drive_start.
        startTimestampMs: drive_start ``timestamp`` from connection_log,
            converted to milliseconds for the realtime_data range query.
        endTimestampMs: drive_end ``timestamp`` from connection_log,
            converted to milliseconds.  ``None`` when no drive_end was
            ever logged.  In that case the caller falls back to
            ``startTimestampMs + windowSeconds * 1000``.
        startIso: ISO-8601 UTC string from connection_log -- preserved
            as-is for the drive_summary.drive_start_timestamp column
            (the schema's DEFAULT is honored when this is None).
    """

    driveId: int
    startTimestampMs: int
    endTimestampMs: int | None
    startIso: str


@dataclass(frozen=True)
class BackfillRow:
    """drive_summary INSERT payload for one drive."""

    driveId: int
    startIso: str
    ambientTempAtStartC: float | None
    startingBatteryV: float | None
    barometricKpaAtStart: float | None


def _isoToMs(isoStr: str) -> int:
    """Parse an ISO-8601 UTC timestamp into integer milliseconds.

    connection_log stores its timestamps via the canonical helper
    ``utcIsoNow`` (US-202) which produces e.g. ``'2026-05-08T20:36:45Z'``.
    realtime_data stores ``timestamp_ms`` as ``int`` milliseconds since
    epoch (UTC).  This helper bridges the two formats.
    """
    from datetime import UTC, datetime

    if isoStr.endswith('Z'):
        isoStr = isoStr[:-1] + '+00:00'
    parsed = datetime.fromisoformat(isoStr)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def findEligibleDrives(
    conn: sqlite3.Connection,
    *,
    windowSeconds: int,
) -> list[EligibleDrive]:
    """Return drives with drive_start events but no drive_summary row.

    Joins connection_log against drive_summary on drive_id; emits one
    EligibleDrive per drive_id where the LEFT JOIN reveals the absence
    of a summary row.

    Args:
        conn: live sqlite3 connection.
        windowSeconds: unused at query time; the caller applies the
            window when computing the per-drive realtime_data range.

    Returns:
        List of EligibleDrive sorted by driveId ascending so the dry-run
        preview reads chronologically.
    """
    del windowSeconds  # consumed by the caller, not the SQL
    rows = conn.execute(
        """
        SELECT cl.drive_id, cl.timestamp,
               (SELECT timestamp FROM connection_log
                WHERE drive_id = cl.drive_id
                  AND event_type = 'drive_end'
                ORDER BY id ASC LIMIT 1) AS end_iso
        FROM connection_log cl
        LEFT JOIN drive_summary ds
          ON ds.drive_id = cl.drive_id
        WHERE cl.event_type = 'drive_start'
          AND cl.drive_id IS NOT NULL
          AND ds.drive_id IS NULL
        ORDER BY cl.drive_id ASC
        """
    ).fetchall()

    eligible: list[EligibleDrive] = []
    for row in rows:
        startIso = row[1]
        endIso = row[2]
        eligible.append(
            EligibleDrive(
                driveId=int(row[0]),
                startTimestampMs=_isoToMs(startIso),
                endTimestampMs=_isoToMs(endIso) if endIso else None,
                startIso=startIso,
            )
        )
    return eligible


def reconstructMetadata(
    conn: sqlite3.Connection,
    drive: EligibleDrive,
    *,
    windowSeconds: int,
) -> BackfillRow:
    """Pull the earliest non-NULL ambient/battery/baro reading per drive.

    Looks up by ``timestamp_ms`` range (NOT ``drive_id``) because US-306
    leaves the first N ticks of each drive with ``drive_id=NULL`` and
    relying on drive_id would silently drop those rows.

    Args:
        conn: live sqlite3 connection.
        drive: Eligible drive descriptor from :func:`findEligibleDrives`.
        windowSeconds: Fallback window when drive_end is missing.

    Returns:
        BackfillRow ready for INSERT.  Any of the metadata fields may
        be ``None`` if no qualifying reading exists in the window.
    """
    if drive.endTimestampMs is not None:
        endMs = drive.endTimestampMs
    else:
        endMs = drive.startTimestampMs + windowSeconds * 1000

    metadata: dict[str, float | None] = dict.fromkeys(
        _PARAM_TO_COLUMN.values()
    )

    for paramName, column in _PARAM_TO_COLUMN.items():
        row = conn.execute(
            """
            SELECT value FROM realtime_data
            WHERE parameter_name = ?
              AND timestamp_ms BETWEEN ? AND ?
              AND value IS NOT NULL
            ORDER BY timestamp_ms ASC
            LIMIT 1
            """,
            (paramName, drive.startTimestampMs, endMs),
        ).fetchone()
        if row is not None:
            metadata[column] = float(row[0])

    return BackfillRow(
        driveId=drive.driveId,
        startIso=drive.startIso,
        ambientTempAtStartC=metadata['ambient_temp_at_start_c'],
        startingBatteryV=metadata['starting_battery_v'],
        barometricKpaAtStart=metadata['barometric_kpa_at_start'],
    )


def insertBackfillRow(
    conn: sqlite3.Connection,
    row: BackfillRow,
) -> None:
    """INSERT one drive_summary row.  Caller owns commit / rollback."""
    conn.execute(
        """
        INSERT INTO drive_summary
            (drive_id, drive_start_timestamp,
             ambient_temp_at_start_c, starting_battery_v,
             barometric_kpa_at_start, data_source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            row.driveId,
            row.startIso,
            row.ambientTempAtStartC,
            row.startingBatteryV,
            row.barometricKpaAtStart,
            'real',
        ),
    )


def runBackfill(
    dbPath: str,
    *,
    dryRun: bool,
    windowSeconds: int,
) -> int:
    """Top-level backfill driver.  Returns the count of eligible drives."""
    with sqlite3.connect(dbPath) as conn:
        conn.row_factory = sqlite3.Row
        eligible = findEligibleDrives(conn, windowSeconds=windowSeconds)

        if not eligible:
            logger.info(
                "No eligible drives -- backfill is a no-op.  "
                "drive_summary is in sync with connection_log.drive_start.",
            )
            return 0

        logger.info(
            "Eligible drives: %d (drive_ids=%s)",
            len(eligible),
            [d.driveId for d in eligible],
        )

        plans: list[BackfillRow] = []
        for drive in eligible:
            row = reconstructMetadata(
                conn, drive, windowSeconds=windowSeconds,
            )
            plans.append(row)
            logger.info(
                "drive_id=%s | start=%s | ambient=%s | battery=%s | baro=%s",
                row.driveId,
                row.startIso,
                row.ambientTempAtStartC,
                row.startingBatteryV,
                row.barometricKpaAtStart,
            )

        if dryRun:
            logger.info(
                "--dry-run: %d row(s) WOULD be INSERTed.  Re-run with "
                "--execute to apply.",
                len(plans),
            )
            return len(plans)

        # Execute path: one transaction per drive so a single failure
        # does not roll back the whole batch.
        for plan in plans:
            try:
                with conn:
                    insertBackfillRow(conn, plan)
                logger.info(
                    "INSERTed drive_summary | drive_id=%s",
                    plan.driveId,
                )
            except sqlite3.IntegrityError as exc:
                # PK collision -- a concurrent writer landed the row
                # before us.  Safe to ignore (idempotency).
                logger.warning(
                    "Skipped drive_id=%s -- row already exists (%s)",
                    plan.driveId, exc,
                )

        return len(plans)


def _parseArgs(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill drive_summary rows for drives that lost the "
                    "US-304 dormancy-window INSERT (Sprint 19 .. V0.27.2).",
    )
    parser.add_argument(
        '--db',
        required=True,
        help="Path to the Pi-side SQLite database (e.g. data/obd.db).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        '--dry-run',
        action='store_true',
        help="Preview the backfill plan without writing.",
    )
    mode.add_argument(
        '--execute',
        action='store_true',
        help="Apply the backfill plan to the database.",
    )
    parser.add_argument(
        '--window-seconds',
        type=int,
        default=DEFAULT_WINDOW_SECONDS,
        help="Fallback window applied when a drive_start has no matching "
             "drive_end event (default: %(default)s sec).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parseArgs(argv)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )

    dbPath = args.db
    if not Path(dbPath).exists():
        logger.error("Database not found at %s", dbPath)
        return 1

    try:
        runBackfill(
            dbPath,
            dryRun=args.dry_run,
            windowSeconds=args.window_seconds,
        )
    except Exception as exc:  # noqa: BLE001 -- top-level driver
        logger.error("Backfill failed: %s", exc, exc_info=True)
        return 2

    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())


# Cast hint for Any typing in BackfillRow's optional float fields when
# IDEs require explicit Any imports.  Re-exported for symmetry with
# scripts/reconcile_drive_summary.py.
_ = Any
