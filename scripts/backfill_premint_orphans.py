################################################################################
# File Name: backfill_premint_orphans.py
# Purpose/Description: Backfill the drive_id column on realtime_data rows that
#                      were captured during the BT-connect-to-cranking window
#                      (US-233 -- Sprint 18). Pre-mint orphan rows are tagged
#                      data_source='real' but have NULL drive_id because the
#                      python-obd connection started writing rows before the
#                      EngineStateMachine fired CRANKING and minted the id.
#                      Reuses Sprint 15 truncate_session23.py safety patterns:
#                      --dry-run scans state without mutation, --execute
#                      requires a prior --dry-run sentinel + backs up the DB
#                      before any UPDATE.
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex (US-233) | Initial -- pre-mint orphan backfill (option a).
# ================================================================================
################################################################################

"""Pre-mint orphan-row backfill for the Pi obd.db (US-233).

Run from anywhere with read+write access to the Pi obd.db (typically over
SSH on chi-eclipse-01 against ``~/Projects/Eclipse-01/data/obd.db``)::

    python scripts/backfill_premint_orphans.py --db data/obd.db --dry-run
    python scripts/backfill_premint_orphans.py --db data/obd.db --execute

Algorithm: a row whose ``drive_id IS NULL AND data_source = 'real'`` is a
"pre-mint orphan" if its timestamp falls within ``--window-seconds`` BEFORE
the next real drive's start. We attach each orphan to the *nearest
subsequent* drive_id; orphans with no drive within the cap remain NULL.

Safety: dry-run is read-only and writes a sentinel; --execute refuses
without that sentinel, backs up the DB to ``<db>.bak-us233-<ts>`` before
any UPDATE, and runs the UPDATEs in a single transaction. Idempotent --
re-run after a clean execute returns 0 matches.

Scope (US-233 invariants):

* Touches only ``realtime_data``. ``drive_summary``, ``connection_log``,
  ``statistics``, ``alert_log`` are NOT modified -- those tables are
  US-200-aware on insert and don't have the same pre-mint orphan
  pattern.
* Per-drive cap (default 1000) prevents a runaway match if a divergent
  schema state lands a million orphans against a single drive_start.
* Tagged rows (``drive_id IS NOT NULL``) and non-real rows
  (``data_source != 'real'``) are NEVER modified.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    'DEFAULT_WINDOW_SECONDS',
    'DEFAULT_MAX_ORPHANS_PER_DRIVE',
    'DRY_RUN_SENTINEL_NAME',
    'BackfillError',
    'SafetyCapError',
    'OrphanRow',
    'DriveStart',
    'BackfillMatch',
    'scanOrphans',
    'scanDriveStarts',
    'findOrphanBackfillMatches',
    'applyBackfill',
    'renderReport',
    'backupDatabase',
    'main',
]


# ================================================================================
# Configuration constants
# ================================================================================

# 60s default covers the observed Drive 3 BT-connect window (39s) with
# headroom. Operator can pass --window-seconds for tighter / wider caps.
DEFAULT_WINDOW_SECONDS: float = 60.0

# Per-drive cap defends against a divergent schema state where a
# multi-million-row scan tries to attach to one drive_id. Real
# BT-connect-to-cranking windows produce at most a few hundred rows
# (~3 rows/sec * 60s = 180); 1000 leaves comfortable headroom.
DEFAULT_MAX_ORPHANS_PER_DRIVE: int = 1000

DRY_RUN_SENTINEL_NAME: str = '.us233-dry-run-ok'


# ================================================================================
# Exceptions
# ================================================================================

class BackfillError(Exception):
    """Base class for operator-facing backfill failures."""


class SafetyCapError(BackfillError):
    """A match would exceed the per-drive maxOrphansPerDrive cap."""


# ================================================================================
# Data classes
# ================================================================================

@dataclass(slots=True, frozen=True)
class OrphanRow:
    """A NULL-drive_id row tagged data_source='real'."""

    rowId: int
    timestamp: str  # ISO-8601 UTC string as stored in realtime_data


@dataclass(slots=True, frozen=True)
class DriveStart:
    """First-row timestamp of a real drive present in realtime_data."""

    driveId: int
    driveStartTimestamp: str  # ISO-8601 UTC string


@dataclass(slots=True, frozen=True)
class BackfillMatch:
    """A single orphan -> drive association produced by the matcher."""

    rowId: int
    toDriveId: int
    rowTimestamp: str
    driveStartTimestamp: str
    gapSeconds: float


# ================================================================================
# Pure read helpers
# ================================================================================

def scanOrphans(conn: sqlite3.Connection) -> list[OrphanRow]:
    """Return every row with NULL drive_id AND data_source='real'.

    Returned rows are sorted by timestamp ascending so matching against
    sorted drive starts is a single linear scan.
    """
    cursor = conn.execute(
        "SELECT id, timestamp FROM realtime_data "
        "WHERE drive_id IS NULL AND data_source = 'real' "
        "ORDER BY timestamp ASC, id ASC",
    )
    return [OrphanRow(rowId=int(rid), timestamp=str(ts)) for rid, ts in cursor]


def scanDriveStarts(conn: sqlite3.Connection) -> list[DriveStart]:
    """Return (drive_id, drive_start_timestamp) for each real drive.

    The drive_start is ``MIN(timestamp)`` over real-tagged rows for the
    drive_id; matches the same authoritative anchor that the engine state
    machine produces in production. Drives that exist only in sim/test
    data are skipped -- we never backfill real orphans against a sim
    drive_id.
    """
    cursor = conn.execute(
        "SELECT drive_id, MIN(timestamp) FROM realtime_data "
        "WHERE drive_id IS NOT NULL AND data_source = 'real' "
        "GROUP BY drive_id "
        "ORDER BY MIN(timestamp) ASC",
    )
    return [
        DriveStart(driveId=int(did), driveStartTimestamp=str(ts))
        for did, ts in cursor
    ]


# ================================================================================
# Matching algorithm
# ================================================================================

def findOrphanBackfillMatches(
    conn: sqlite3.Connection,
    *,
    windowSeconds: float = DEFAULT_WINDOW_SECONDS,
    maxOrphansPerDrive: int = DEFAULT_MAX_ORPHANS_PER_DRIVE,
) -> list[BackfillMatch]:
    """Match each pre-mint orphan to its nearest subsequent real drive.

    Args:
        conn: Open sqlite3 connection on the obd.db.
        windowSeconds: Maximum allowed gap (in seconds) between an
            orphan timestamp and the subsequent drive_start. Orphans
            with no drive_start within the cap stay NULL.
        maxOrphansPerDrive: Refusal cap. If any drive_id would receive
            more than this many orphans, raise SafetyCapError instead
            of silently truncating -- divergence likely means the schema
            or data is in an unexpected state.

    Returns:
        BackfillMatch entries sorted by row timestamp.

    Raises:
        ValueError: ``windowSeconds <= 0``.
        SafetyCapError: any drive_id would exceed the per-drive cap.
    """
    if windowSeconds <= 0:
        raise ValueError(
            f"windowSeconds must be > 0; got {windowSeconds}",
        )
    orphans = scanOrphans(conn)
    starts = scanDriveStarts(conn)
    if not orphans or not starts:
        return []
    matches: list[BackfillMatch] = []
    perDriveCount: dict[int, int] = {}
    for orphan in orphans:
        nearest = _nearestSubsequentDriveStart(orphan.timestamp, starts)
        if nearest is None:
            continue
        gap = _isoGapSeconds(orphan.timestamp, nearest.driveStartTimestamp)
        # gap must be strictly positive (orphan strictly before drive_start)
        # AND within the window cap.
        if gap <= 0 or gap > windowSeconds:
            continue
        perDriveCount[nearest.driveId] = (
            perDriveCount.get(nearest.driveId, 0) + 1
        )
        if perDriveCount[nearest.driveId] > maxOrphansPerDrive:
            raise SafetyCapError(
                f"drive_id={nearest.driveId} would receive "
                f"{perDriveCount[nearest.driveId]} orphans, exceeding "
                f"maxOrphansPerDrive={maxOrphansPerDrive}; refuse",
            )
        matches.append(
            BackfillMatch(
                rowId=orphan.rowId,
                toDriveId=nearest.driveId,
                rowTimestamp=orphan.timestamp,
                driveStartTimestamp=nearest.driveStartTimestamp,
                gapSeconds=gap,
            ),
        )
    return matches


def _nearestSubsequentDriveStart(
    orphanTimestamp: str, starts: Sequence[DriveStart],
) -> DriveStart | None:
    """Return the earliest drive_start strictly AFTER the orphan timestamp.

    ``starts`` is assumed sorted ascending by driveStartTimestamp.
    Linear scan is fine here -- the dataset is small (a handful of
    drives per Pi DB).
    """
    for start in starts:
        if start.driveStartTimestamp > orphanTimestamp:
            return start
    return None


def _isoGapSeconds(earlierIso: str, laterIso: str) -> float:
    """Seconds between two ISO-8601 UTC strings (later - earlier).

    Both inputs are expected in the canonical Pi format
    ``YYYY-MM-DDTHH:MM:SSZ`` (US-202). datetime.fromisoformat handles
    the trailing ``Z`` once we replace it with ``+00:00``.
    """
    earlier = _parseIso(earlierIso)
    later = _parseIso(laterIso)
    return (later - earlier).total_seconds()


def _parseIso(iso: str) -> _dt.datetime:
    if iso.endswith('Z'):
        iso = iso[:-1] + '+00:00'
    return _dt.datetime.fromisoformat(iso)


# ================================================================================
# UPDATE applier
# ================================================================================

def applyBackfill(
    conn: sqlite3.Connection, matches: Iterable[BackfillMatch],
) -> int:
    """Run UPDATE drive_id on every matched row in a single transaction.

    Idempotent: an empty ``matches`` is a no-op returning 0. Re-running
    after a successful pass returns 0 because the same rows no longer
    have NULL drive_id and the matcher won't re-pick them.

    The UPDATE is double-guarded: the WHERE clause requires
    ``drive_id IS NULL AND data_source = 'real'`` so a tagged row can
    never be silently clobbered even if a stale ``BackfillMatch`` is
    passed in.
    """
    matchList = list(matches)
    if not matchList:
        return 0
    updated = 0
    conn.execute('BEGIN IMMEDIATE')
    try:
        for match in matchList:
            cursor = conn.execute(
                "UPDATE realtime_data SET drive_id = ? "
                "WHERE id = ? AND drive_id IS NULL "
                "AND data_source = 'real'",
                (match.toDriveId, match.rowId),
            )
            updated += cursor.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return updated


# ================================================================================
# Reporting
# ================================================================================

def renderReport(
    matches: Sequence[BackfillMatch], *, dryRun: bool, dbPath: str,
) -> str:
    """Operator-facing summary of the proposed (or applied) backfill."""
    lines: list[str] = []
    lines.append('=' * 72)
    lines.append('US-233 pre-mint orphan backfill')
    lines.append('=' * 72)
    lines.append(f'  database: {dbPath}')
    lines.append(f'  mode:     {"dry-run" if dryRun else "execute"}')
    lines.append(f'  matches:  {len(matches)}')
    if not matches:
        lines.append('  -> nothing to do')
        lines.append('=' * 72)
        return '\n'.join(lines)
    perDrive: dict[int, int] = {}
    for match in matches:
        perDrive[match.toDriveId] = perDrive.get(match.toDriveId, 0) + 1
    lines.append('  per-drive:')
    for driveId in sorted(perDrive):
        lines.append(f'    drive_id={driveId}: {perDrive[driveId]} orphan(s)')
    earliest = min(m.rowTimestamp for m in matches)
    latest = max(m.rowTimestamp for m in matches)
    maxGap = max(m.gapSeconds for m in matches)
    lines.append(
        f'  span:     [{earliest} .. {latest}]  max gap={maxGap:.1f}s',
    )
    lines.append('=' * 72)
    return '\n'.join(lines)


# ================================================================================
# Backup
# ================================================================================

def backupDatabase(dbPath: Path, timestampTag: str) -> Path:
    """Copy the SQLite DB file to <db>.bak-us233-<ts> using shutil.copy2.

    shutil.copy2 preserves metadata + works cross-FS; the source DB is
    expected to be quiesced (eclipse-obd.service stopped) per the
    operator runbook in docs/testing.md. We do NOT use sqlite3 .backup
    here because the destination is a plain file and the source is
    expected to be at rest.
    """
    if not dbPath.exists():
        raise BackfillError(f'database not found: {dbPath}')
    backupPath = dbPath.with_name(
        f'{dbPath.name}.bak-us233-{timestampTag}',
    )
    shutil.copy2(dbPath, backupPath)
    return backupPath


# ================================================================================
# CLI
# ================================================================================

def _timestampTag() -> str:
    return _dt.datetime.now(_dt.UTC).strftime('%Y%m%d-%H%M%SZ')


def _writeSentinel(sentinelDir: Path, payload: str) -> Path:
    sentinelDir.mkdir(parents=True, exist_ok=True)
    path = sentinelDir / DRY_RUN_SENTINEL_NAME
    path.write_text(payload, encoding='utf-8')
    return path


def _readSentinel(sentinelDir: Path) -> str | None:
    path = sentinelDir / DRY_RUN_SENTINEL_NAME
    if not path.exists():
        return None
    return path.read_text(encoding='utf-8')


def _clearSentinel(sentinelDir: Path) -> None:
    path = sentinelDir / DRY_RUN_SENTINEL_NAME
    path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='backfill_premint_orphans.py',
        description=(
            'US-233 pre-mint orphan backfill: attach NULL-drive_id real '
            'rows to the nearest subsequent drive (within --window-seconds).'
        ),
    )
    parser.add_argument(
        '--db', required=True,
        help='Path to the Pi obd.db SQLite file',
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        '--dry-run', action='store_true',
        help='Scan + report; no mutation',
    )
    mode.add_argument(
        '--execute', action='store_true',
        help='Apply UPDATE after a prior --dry-run',
    )
    parser.add_argument(
        '--window-seconds', type=float,
        default=DEFAULT_WINDOW_SECONDS,
        help=(
            f'Maximum gap between orphan and subsequent drive_start '
            f'(default {DEFAULT_WINDOW_SECONDS}s)'
        ),
    )
    parser.add_argument(
        '--max-orphans-per-drive', type=int,
        default=DEFAULT_MAX_ORPHANS_PER_DRIVE,
        help=(
            f'Refuse if any drive would receive > N orphans '
            f'(default {DEFAULT_MAX_ORPHANS_PER_DRIVE})'
        ),
    )
    parser.add_argument(
        '--sentinel-dir', type=Path, default=None,
        help=(
            'Directory for the dry-run sentinel '
            '(defaults to the parent of --db)'
        ),
    )
    args = parser.parse_args(argv)

    dbPath = Path(args.db).resolve()
    sentinelDir = (args.sentinel_dir or dbPath.parent).resolve()

    if not dbPath.exists():
        print(f'ERROR: database not found: {dbPath}', file=sys.stderr)
        return 2

    try:
        with sqlite3.connect(str(dbPath)) as conn:
            try:
                matches = findOrphanBackfillMatches(
                    conn,
                    windowSeconds=args.window_seconds,
                    maxOrphansPerDrive=args.max_orphans_per_drive,
                )
            except (ValueError, SafetyCapError) as err:
                print(f'ERROR: {err}', file=sys.stderr)
                return 3
            print(renderReport(
                matches, dryRun=args.dry_run, dbPath=str(dbPath),
            ))
            if args.dry_run:
                _writeSentinel(
                    sentinelDir,
                    f'matches={len(matches)}\n'
                    f'window={args.window_seconds}\n'
                    f'writtenAt={_dt.datetime.now(_dt.UTC).isoformat()}\n',
                )
                print(
                    f'\n[dry-run] sentinel: {sentinelDir / DRY_RUN_SENTINEL_NAME}',
                )
                return 0
            # --execute path
            if _readSentinel(sentinelDir) is None:
                print(
                    'ERROR: --execute requires a prior --dry-run '
                    f'(missing {sentinelDir / DRY_RUN_SENTINEL_NAME})',
                    file=sys.stderr,
                )
                return 2
            if not matches:
                _clearSentinel(sentinelDir)
                return 0
            backupPath = backupDatabase(dbPath, _timestampTag())
            print(f'[backup] {backupPath}')
            updated = applyBackfill(conn, matches)
            print(f'[execute] UPDATE applied: {updated} row(s)')
            _clearSentinel(sentinelDir)
            return 0
    except BackfillError as err:
        print(f'ERROR: {err}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
