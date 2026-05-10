################################################################################
# File Name: backfill_orphan_drive_id.py
# Purpose/Description: US-311 / I-019 -- one-shot backfill for the 1,078 NULL-
#                      drive_id rows in realtime_data captured during the
#                      2026-05-09 evening orphan window between Drive 8 (clean)
#                      and Drive 9 (compromised by USB-C brownout).  A 2-3 min
#                      around-the-block trip lived in that window but never
#                      fired drive_start because the orchestrator's one-shot
#                      _engineOnEscalated flag swallowed the warm-restart probe.
#                      US-311 fixes the live writer; this script repairs the
#                      historical rows.  --dry-run preview + idempotent.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex (US-311) | Initial -- orphan-drive-id backfill (option a):
#               |              | operator-provided timestamp window + target
#               |              | drive_id; optional RPM-filter narrows the
#               |              | window to RPM>500 segments only.
# ================================================================================
################################################################################

"""Pi obd.db orphan-drive-id backfill (US-311 / I-019).

Run from anywhere with read+write access to the Pi obd.db (typically over
SSH on chi-eclipse-01 against ``~/Projects/Eclipse-01/data/obd.db``)::

    # I-019 default window: Drive 8 -> Drive 9 orphan from 2026-05-09 evening
    python scripts/backfill_orphan_drive_id.py \\
        --db data/obd.db --target-drive-id 11 --dry-run

    python scripts/backfill_orphan_drive_id.py \\
        --db data/obd.db --target-drive-id 11 --execute

    # Custom window (any future I-019-class warm-restart orphan)
    python scripts/backfill_orphan_drive_id.py \\
        --db data/obd.db \\
        --start 2026-05-09T23:40:00Z \\
        --end 2026-05-10T00:16:00Z \\
        --target-drive-id 11 \\
        --rpm-filter \\
        --execute

Algorithm
---------

1. Scan ``realtime_data`` for rows in ``[start, end]`` with NULL drive_id.
2. If ``--rpm-filter`` is set, narrow the window to only the timestamps
   where an RPM reading > 500 was captured (the actual driving slice
   inside the broader orphan window) plus a small bracket around each
   reading so all parameters captured in that microsecond pack with it.
3. Assign ``--target-drive-id`` to every matching row.
4. Idempotent: a second run finds the rows already tagged and reports
   ``populated=0, skipped=N``.

Safety posture
--------------

* ``--dry-run`` (default) lists every row that WOULD change without
  committing.  Writes a sentinel that ``--execute`` requires.
* ``--execute`` backs up the DB to ``<db>.bak-us311-<ts>`` before any
  UPDATE and runs all UPDATEs in a single transaction.
* The target drive_id MUST already exist in ``drive_counter`` (or be
  injectable -- this script does NOT advance the counter).  Operator
  is responsible for picking an unused id; the recommended workflow is
  to mint the next id via the Pi service first, then pass it here.
* Touches only ``realtime_data``.  ``connection_log`` /
  ``drive_summary`` are NOT synthesized -- this script repairs the
  raw row tagging only.  Operator can hand-roll a drive_summary row
  via :class:`SummaryRecorder` after the fact if needed.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    'DEFAULT_RPM_THRESHOLD',
    'DEFAULT_RPM_BRACKET_SECONDS',
    'I019_DEFAULT_START',
    'I019_DEFAULT_END',
    'DRY_RUN_SENTINEL_NAME',
    'BackfillError',
    'OrphanRow',
    'BackfillPlan',
    'scanOrphansInWindow',
    'narrowToRpmWindows',
    'applyBackfill',
    'renderReport',
    'backupDatabase',
    'main',
]


# ================================================================================
# Configuration constants
# ================================================================================

# RPM threshold for the optional --rpm-filter narrowing.  Same constant
# DriveDetector uses for driveStartRpmThreshold (specs/standards.md +
# src/pi/obdii/drive/types.py:38).
DEFAULT_RPM_THRESHOLD: float = 500.0

# When --rpm-filter is on, each RPM > threshold reading anchors a small
# bracket so other parameters captured in the same poll cycle pack with
# it.  Production poll cycle is ~500ms so 2s comfortably covers a full
# multi-parameter cycle.
DEFAULT_RPM_BRACKET_SECONDS: float = 2.0

# I-019 default window: Drive 8 ended 2026-05-09T23:39, Drive 9 started
# 2026-05-10T00:16; orphan rows live in the 37-min span.  Use these
# defaults when the operator omits --start / --end (the scripted I-019
# repair path).
I019_DEFAULT_START: str = '2026-05-09T23:40:00Z'
I019_DEFAULT_END: str = '2026-05-10T00:16:00Z'

DRY_RUN_SENTINEL_NAME: str = '.us311-dry-run-ok'


# ================================================================================
# Exceptions
# ================================================================================

class BackfillError(Exception):
    """Base class for operator-facing backfill failures."""


# ================================================================================
# Data classes
# ================================================================================

@dataclass(slots=True, frozen=True)
class OrphanRow:
    """A NULL-drive_id row inside the operator-supplied window."""

    rowId: int
    timestamp: str  # ISO-8601 UTC string as stored in realtime_data
    parameterName: str | None
    value: float | None


@dataclass(slots=True, frozen=True)
class BackfillPlan:
    """The set of rows that would (or did) get tagged with the target id."""

    targetDriveId: int
    windowStart: str
    windowEnd: str
    rpmFilterUsed: bool
    rowsToTag: list[OrphanRow]


# ================================================================================
# Pure read helpers
# ================================================================================

def scanOrphansInWindow(
    conn: sqlite3.Connection, *, windowStart: str, windowEnd: str,
) -> list[OrphanRow]:
    """Return every NULL-drive_id row in ``[windowStart, windowEnd]``.

    ``data_source`` filter omitted intentionally: the I-019 orphans
    include rows with adapter heartbeats (BATTERY_V via ELM_VOLTAGE,
    ``data_source='real'``) AND any rows the realtime loop tagged
    differently.  Operator decides the scope via the timestamp window.
    """
    cursor = conn.execute(
        "SELECT id, timestamp, parameter_name, value FROM realtime_data "
        "WHERE drive_id IS NULL "
        "AND timestamp >= ? AND timestamp <= ? "
        "ORDER BY timestamp ASC, id ASC",
        (windowStart, windowEnd),
    )
    return [
        OrphanRow(
            rowId=int(rid),
            timestamp=str(ts),
            parameterName=str(pn) if pn is not None else None,
            value=float(val) if val is not None else None,
        )
        for rid, ts, pn, val in cursor
    ]


def narrowToRpmWindows(
    rows: list[OrphanRow],
    *,
    rpmThreshold: float = DEFAULT_RPM_THRESHOLD,
    bracketSeconds: float = DEFAULT_RPM_BRACKET_SECONDS,
) -> list[OrphanRow]:
    """Keep only rows within ``bracketSeconds`` of an RPM > threshold reading.

    The I-019 orphan window is 37 min wide but the actual around-the-
    block drive was only ~3 min in the middle.  Tagging the whole window
    with a synthetic drive_id would absorb 30+ min of engine-off baseline
    BATTERY_V heartbeats into the drive.  This filter narrows the tag
    target to the windows where RPM > threshold was actually observed,
    plus a small bracket around each so the other parameters captured in
    the same poll cycle pack with it.

    Args:
        rows: Output of :func:`scanOrphansInWindow` (must be sorted by
            timestamp ascending; the function relies on that ordering).
        rpmThreshold: Minimum RPM value to anchor a bracket.  Same as
            ``DriveDetector.driveStartRpmThreshold`` default.
        bracketSeconds: Half-width of the bracket around each RPM
            reading (rows within ``+/- bracketSeconds`` are kept).

    Returns:
        A subset of ``rows`` ordered the same way.  When the input has
        no RPM>threshold readings, returns ``[]`` (no driving in the
        window -- the script will report and exit cleanly).
    """
    rpmAnchors = [
        _parseIso(r.timestamp)
        for r in rows
        if r.parameterName == 'RPM' and r.value is not None
        and r.value > rpmThreshold
    ]
    if not rpmAnchors:
        return []

    kept: list[OrphanRow] = []
    for row in rows:
        rowTime = _parseIso(row.timestamp)
        for anchor in rpmAnchors:
            if abs((rowTime - anchor).total_seconds()) <= bracketSeconds:
                kept.append(row)
                break
    return kept


def _parseIso(iso: str) -> _dt.datetime:
    """Parse the canonical Pi ``YYYY-MM-DDTHH:MM:SSZ`` ISO format."""
    if iso.endswith('Z'):
        iso = iso[:-1] + '+00:00'
    return _dt.datetime.fromisoformat(iso)


# ================================================================================
# UPDATE applier
# ================================================================================

def applyBackfill(
    conn: sqlite3.Connection, plan: BackfillPlan,
) -> int:
    """Run UPDATE drive_id on every row in the plan (single transaction).

    Idempotent: an empty plan is a no-op returning 0.  Re-running after
    a successful pass returns 0 because the same rows no longer have
    NULL drive_id and :func:`scanOrphansInWindow` won't re-pick them.

    Returns:
        Number of rows updated.
    """
    if not plan.rowsToTag:
        return 0

    rowIds = [(plan.targetDriveId, r.rowId) for r in plan.rowsToTag]
    cursor = conn.executemany(
        "UPDATE realtime_data SET drive_id = ? WHERE id = ?",
        rowIds,
    )
    return cursor.rowcount


# ================================================================================
# Reporting
# ================================================================================

def renderReport(plan: BackfillPlan, *, dryRun: bool) -> str:
    """Format a human-readable summary for the CLI."""
    mode = 'DRY RUN' if dryRun else 'EXECUTE'
    rpm = 'RPM>500 narrowed' if plan.rpmFilterUsed else 'full window'
    headline = (
        f"[{mode}] window={plan.windowStart} -> {plan.windowEnd} "
        f"({rpm}) target_drive_id={plan.targetDriveId} "
        f"rows_to_tag={len(plan.rowsToTag)}"
    )
    if not plan.rowsToTag:
        return headline + "\n(no rows match -- nothing to do)"

    sample = plan.rowsToTag[:5]
    tail = plan.rowsToTag[-5:] if len(plan.rowsToTag) > 5 else []
    lines = [headline, "first rows:"]
    for r in sample:
        lines.append(
            f"  id={r.rowId} ts={r.timestamp} "
            f"param={r.parameterName} value={r.value}"
        )
    if tail and tail[0].rowId != sample[-1].rowId:
        lines.append("...")
        lines.append("last rows:")
        for r in tail:
            lines.append(
                f"  id={r.rowId} ts={r.timestamp} "
                f"param={r.parameterName} value={r.value}"
            )
    return "\n".join(lines)


# ================================================================================
# Backup
# ================================================================================

def backupDatabase(dbPath: Path) -> Path:
    """Copy the DB to ``<db>.bak-us311-<ts>`` before any UPDATE.

    Uses the same naming convention as :mod:`backfill_premint_orphans`
    (US-233) so the operator recognizes the safety pattern.
    """
    timestamp = _dt.datetime.now(_dt.UTC).strftime('%Y%m%dT%H%M%SZ')
    backupPath = dbPath.with_suffix(dbPath.suffix + f'.bak-us311-{timestamp}')
    shutil.copy2(dbPath, backupPath)
    return backupPath


# ================================================================================
# CLI entry point
# ================================================================================

def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog='backfill_orphan_drive_id',
        description=(
            'US-311 / I-019: tag NULL-drive_id rows in a timestamp window '
            'with a synthetic drive_id (operator-supplied).  Repairs '
            'historical orphans from warm-restart drive_start failures.'
        ),
    )
    parser.add_argument(
        '--db', type=Path, required=True,
        help='Path to the Pi obd.db SQLite file.',
    )
    parser.add_argument(
        '--target-drive-id', type=int, required=True,
        help=(
            'Synthetic drive_id to assign to matching rows.  Operator '
            'is responsible for picking an unused id (recommended: mint '
            'the next id via the Pi service before running this script).'
        ),
    )
    parser.add_argument(
        '--start', type=str, default=I019_DEFAULT_START,
        help=(
            f'Window start (inclusive) ISO-8601 UTC.  Default: '
            f'{I019_DEFAULT_START} (I-019 Drive 8 -> Drive 9 orphan).'
        ),
    )
    parser.add_argument(
        '--end', type=str, default=I019_DEFAULT_END,
        help=(
            f'Window end (inclusive) ISO-8601 UTC.  Default: '
            f'{I019_DEFAULT_END} (I-019 Drive 8 -> Drive 9 orphan).'
        ),
    )
    parser.add_argument(
        '--rpm-filter', action='store_true',
        help=(
            'Narrow the tagged set to only rows within +/- 2s of an RPM '
            '> 500 reading inside the window.  Recommended for I-019 '
            'where the orphan window includes 30+ min of engine-off '
            'baseline that should NOT be absorbed into the synthetic drive.'
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        '--dry-run', action='store_true', default=True,
        help='Preview the plan without modifying the DB (default).',
    )
    mode.add_argument(
        '--execute', action='store_true',
        help='Apply the plan (requires a prior --dry-run sentinel + backs up the DB).',
    )

    args = parser.parse_args(argv)

    dbPath: Path = args.db
    if not dbPath.exists():
        sys.stderr.write(f"error: db not found: {dbPath}\n")
        return 2

    # --execute overrides --dry-run default.
    isExecute = bool(args.execute)
    isDryRun = not isExecute

    sentinelPath = dbPath.with_name(DRY_RUN_SENTINEL_NAME)
    if isExecute and not sentinelPath.exists():
        sys.stderr.write(
            f"error: --execute requires a prior successful --dry-run "
            f"(sentinel {sentinelPath} not found).\n"
        )
        return 2

    conn = sqlite3.connect(str(dbPath))
    try:
        rowsAll = scanOrphansInWindow(
            conn, windowStart=args.start, windowEnd=args.end,
        )
        if args.rpm_filter:
            rowsToTag = narrowToRpmWindows(rowsAll)
        else:
            rowsToTag = rowsAll
        plan = BackfillPlan(
            targetDriveId=args.target_drive_id,
            windowStart=args.start,
            windowEnd=args.end,
            rpmFilterUsed=args.rpm_filter,
            rowsToTag=rowsToTag,
        )
        sys.stdout.write(renderReport(plan, dryRun=isDryRun) + "\n")

        if isDryRun:
            sentinelPath.write_text(_dt.datetime.now(_dt.UTC).isoformat() + "\n")
            return 0

        backupPath = backupDatabase(dbPath)
        sys.stdout.write(f"backup written to {backupPath}\n")
        with conn:
            updated = applyBackfill(conn, plan)
        sys.stdout.write(f"rows updated: {updated}\n")
        try:
            sentinelPath.unlink()
        except FileNotFoundError:
            pass
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
