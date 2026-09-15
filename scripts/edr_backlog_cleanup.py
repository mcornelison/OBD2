################################################################################
# File Name: edr_backlog_cleanup.py
# Purpose/Description: US-769 -- one-time Pi cleanup run before the EDR tables
#                      enter sync scope: keep edr_imu_sample / edr_light_sample
#                      rows inside drive windows and delete the parked rest.
#                      DRY RUN by default; --apply takes a verified backup, then
#                      deletes. Windows come only from canonical drive events.
#                      Design: _shared/knowledge/superpowers/specs/
#                      2026-09-14-us734-edr-server-sync-schema-design.md section 4.
# Author: Rex (US-769)
# Creation Date: 2026-09-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-15    | Rex (US-769) | Initial -- keep-drive-window EDR backlog cleanup,
#                               per-day per-table counts, refusal on non-canonical
#                               drive events, verified backup before --apply.
# ================================================================================
################################################################################

"""One-time EDR backlog cleanup (US-769, design D7).

Run on the Pi from the project root::

    # Dry run (default): prints kept/deleted per day per table, writes nothing
    python scripts/edr_backlog_cleanup.py --db data/obd.db

    # After the CIO has reviewed the dry-run counts
    python scripts/edr_backlog_cleanup.py --db data/obd.db --apply

Keep windows
------------

Built ONLY from ``connection_log`` rows with ``event_type`` ``drive_start`` or
``drive_end``, as ``[drive_start - 60 s, drive_end + 300 s]``. Link events are
never read: they are stored in two timestamp formats. A ``drive_start`` with no
``drive_end`` before the next ``drive_start`` extends to ``min(next start,
start + 2 h)``, and every such extension is printed on the run.

Refusals (non-zero exit, nothing deleted)
-----------------------------------------

* A drive event whose timestamp is not canonical ``YYYY-MM-DDTHH:MM:SSZ``: a
  window inferred from it could delete real driving data, and there is no undo.
* An EDR row whose ``ts_utc`` is not canonical: the window test is a string
  comparison that is only chronological for the canonical format.
* A backup that cannot be re-read, or whose drive windows differ from the
  database's.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / 'src'
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from common.edr.sync_contract import EDR_SYNC_TABLES  # noqa: E402
from common.time.helper import CANONICAL_ISO_FORMAT, CANONICAL_ISO_REGEX  # noqa: E402

__all__ = [
    'BackupVerificationError',
    'DayCounts',
    'DriveEvent',
    'DriveWindow',
    'NonCanonicalDataError',
    'applyCleanup',
    'backupDatabase',
    'checkEdrTimestamps',
    'keepWindows',
    'main',
    'orphanDriveEnds',
    'planCleanup',
    'readDriveEvents',
    'verifyBackup',
]

# ================================================================================
# Constants (design section 4)
# ================================================================================

DEFAULT_DB_PATH = 'data/obd.db'
DRIVE_START = 'drive_start'
DRIVE_END = 'drive_end'
PRE_DRIVE_PAD = timedelta(seconds=60)
POST_DRIVE_PAD = timedelta(seconds=300)
UNMATCHED_START_CAP = timedelta(hours=2)

EXIT_OK = 0
EXIT_MISSING_INPUT = 2
EXIT_NON_CANONICAL = 3
EXIT_BACKUP_FAILED = 4

# SQLite GLOB equivalent of CANONICAL_ISO_REGEX, for a set-based check of ts_utc.
_CANONICAL_GLOB = (
    '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
)
_BACKUP_TAG = 'bak-us769'
_DAY_CHARS = 10  # 'YYYY-MM-DD' prefix of a canonical timestamp


class NonCanonicalDataError(ValueError):
    """An input the keep windows depend on is not in the canonical format."""


class BackupVerificationError(RuntimeError):
    """The backup taken before --apply could not be re-read as a faithful copy."""


@dataclass(frozen=True, slots=True)
class DriveEvent:
    """One canonical drive_start / drive_end row from connection_log."""

    eventId: int
    at: datetime
    eventType: str


@dataclass(frozen=True, slots=True)
class DriveWindow:
    """A padded keep window. ``unmatched`` marks an extended drive_start."""

    start: datetime
    end: datetime
    unmatched: bool
    startEventId: int


@dataclass(frozen=True, slots=True)
class DayCounts:
    """EDR rows kept and deleted for one table on one UTC day."""

    kept: int
    deleted: int


# ================================================================================
# Drive events -> keep windows
# ================================================================================

def _shape(value: object) -> str:
    """Describe a timestamp's format: digits become D, e.g. 'DDDD-DD-DD DD:DD:DD'."""
    if not isinstance(value, str):
        return f'<{type(value).__name__}>'
    return re.sub(r'\d', 'D', value)


def _parseCanonical(value: object) -> datetime:
    """Parse a canonical ISO-8601 UTC string, or raise NonCanonicalDataError."""
    if not isinstance(value, str) or re.fullmatch(CANONICAL_ISO_REGEX, value) is None:
        raise NonCanonicalDataError(
            f'found format {_shape(value)!r}, expected YYYY-MM-DDTHH:MM:SSZ',
        )
    try:
        return datetime.strptime(value, CANONICAL_ISO_FORMAT).replace(tzinfo=UTC)
    except ValueError as exc:
        raise NonCanonicalDataError(f'canonical shape but not a valid time: {exc}') from exc


def readDriveEvents(conn: sqlite3.Connection) -> list[DriveEvent]:
    """Read every drive_start / drive_end event, refusing any non-canonical one.

    Args:
        conn: Open connection on obd.db.

    Returns:
        The drive events in ``id`` order.

    Raises:
        NonCanonicalDataError: When any drive event's timestamp is not canonical.
            The message names the row, the value and the format found.
    """
    events: list[DriveEvent] = []
    rows = conn.execute(
        'SELECT id, timestamp, event_type FROM connection_log '
        'WHERE event_type IN (?, ?) ORDER BY id',
        (DRIVE_START, DRIVE_END),
    )
    for eventId, timestamp, eventType in rows:
        try:
            at = _parseCanonical(timestamp)
        except NonCanonicalDataError as exc:
            raise NonCanonicalDataError(
                f'connection_log id={eventId} event_type={eventType} '
                f'timestamp={timestamp!r}: {exc}',
            ) from exc
        events.append(DriveEvent(eventId=int(eventId), at=at, eventType=eventType))
    return events


def _ordered(events: list[DriveEvent]) -> list[DriveEvent]:
    # Same-second events keep their insert order, so a start precedes its end.
    return sorted(events, key=lambda e: (e.at, e.eventId))


def keepWindows(events: list[DriveEvent]) -> list[DriveWindow]:
    """Build padded keep windows from drive events.

    A drive_start pairs with the next event when that event is a drive_end:
    ``[start - 60 s, end + 300 s]``. Otherwise the start is unmatched and its
    window ends at ``min(next drive_start, start + 2 h)``.

    Args:
        events: Drive events in any order.

    Returns:
        One window per drive_start, in chronological order.
    """
    ordered = _ordered(events)
    windows: list[DriveWindow] = []
    for i, event in enumerate(ordered):
        if event.eventType != DRIVE_START:
            continue
        following = ordered[i + 1] if i + 1 < len(ordered) else None
        start = event.at - PRE_DRIVE_PAD
        if following is not None and following.eventType == DRIVE_END:
            windows.append(
                DriveWindow(start, following.at + POST_DRIVE_PAD, False, event.eventId),
            )
            continue
        end = event.at + UNMATCHED_START_CAP
        if following is not None:
            end = min(end, following.at)
        windows.append(DriveWindow(start, end, True, event.eventId))
    return windows


def orphanDriveEnds(events: list[DriveEvent]) -> list[DriveEvent]:
    """Return drive_end events that no drive_start opens (no window is built)."""
    ordered = _ordered(events)
    return [
        event for i, event in enumerate(ordered)
        if event.eventType == DRIVE_END and (i == 0 or ordered[i - 1].eventType != DRIVE_START)
    ]


def _mergedRanges(windows: list[DriveWindow]) -> list[tuple[str, str]]:
    """Merge overlapping windows into disjoint canonical-string ranges."""
    merged: list[list[datetime]] = []
    for window in sorted(windows, key=lambda w: w.start):
        if merged and window.start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], window.end)
        else:
            merged.append([window.start, window.end])
    return [
        (s.strftime(CANONICAL_ISO_FORMAT), e.strftime(CANONICAL_ISO_FORMAT)) for s, e in merged
    ]


# ================================================================================
# Plan and apply
# ================================================================================

def checkEdrTimestamps(conn: sqlite3.Connection) -> None:
    """Refuse when any EDR row's ts_utc is not canonical.

    Raises:
        NonCanonicalDataError: Naming the table, the offending count and an example.
    """
    for table in EDR_SYNC_TABLES:
        count, example = conn.execute(
            f'SELECT COUNT(*), MIN(ts_utc) FROM {table} WHERE NOT (ts_utc GLOB ?)',  # noqa: S608
            (_CANONICAL_GLOB,),
        ).fetchone()
        if count:
            raise NonCanonicalDataError(
                f'{table}: {count} row(s) with a non-canonical ts_utc, e.g. {example!r} '
                f'(format {_shape(example)!r}, expected YYYY-MM-DDTHH:MM:SSZ)',
            )


def planCleanup(
    conn: sqlite3.Connection, windows: list[DriveWindow],
) -> dict[str, dict[str, DayCounts]]:
    """Count kept and deleted EDR rows per table per UTC day. Writes nothing.

    Args:
        conn: Open connection on obd.db.
        windows: Keep windows from :func:`keepWindows`.

    Returns:
        ``{table: {'YYYY-MM-DD': DayCounts}}`` with days in order.
    """
    ranges = _mergedRanges(windows)
    plan: dict[str, dict[str, DayCounts]] = {}
    for table in EDR_SYNC_TABLES:
        totals = dict(conn.execute(
            f'SELECT substr(ts_utc, 1, {_DAY_CHARS}), COUNT(*) FROM {table} '  # noqa: S608
            'GROUP BY 1',
        ).fetchall())
        kept: dict[str, int] = defaultdict(int)
        for start, end in ranges:
            for day, n in conn.execute(
                f'SELECT substr(ts_utc, 1, {_DAY_CHARS}), COUNT(*) FROM {table} '  # noqa: S608
                'WHERE ts_utc >= ? AND ts_utc <= ? GROUP BY 1',
                (start, end),
            ):
                kept[day] += n
        plan[table] = {
            day: DayCounts(kept=kept[day], deleted=totals[day] - kept[day])
            for day in sorted(totals)
        }
    return plan


def _outsideClauses(ranges: list[tuple[str, str]]) -> list[tuple[str, tuple[str, ...]]]:
    """WHERE clauses covering exactly the time outside every keep range."""
    if not ranges:
        return [('1', ())]
    clauses: list[tuple[str, tuple[str, ...]]] = [('ts_utc < ?', (ranges[0][0],))]
    for (_, prevEnd), (nextStart, _) in zip(ranges, ranges[1:], strict=False):
        clauses.append(('ts_utc > ? AND ts_utc < ?', (prevEnd, nextStart)))
    clauses.append(('ts_utc > ?', (ranges[-1][1],)))
    return clauses


def applyCleanup(conn: sqlite3.Connection, windows: list[DriveWindow]) -> dict[str, int]:
    """Delete every EDR row outside all keep windows, in one transaction.

    Args:
        conn: Writable connection on obd.db.
        windows: Keep windows from :func:`keepWindows`.

    Returns:
        ``{table: rowsDeleted}``.
    """
    clauses = _outsideClauses(_mergedRanges(windows))
    deleted: dict[str, int] = {}
    conn.execute('BEGIN IMMEDIATE')
    try:
        for table in EDR_SYNC_TABLES:
            deleted[table] = sum(
                conn.execute(f'DELETE FROM {table} WHERE {clause}', params).rowcount  # noqa: S608
                for clause, params in clauses
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return deleted


# ================================================================================
# Backup
# ================================================================================

def backupDatabase(conn: sqlite3.Connection, dbPath: Path, backupDir: Path) -> Path:
    """Copy the live database with SQLite's online backup API.

    Args:
        conn: Open connection on the database to copy.
        dbPath: Its path (names the backup).
        backupDir: Directory the backup is written to.

    Returns:
        Path of the backup file.
    """
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    target = backupDir / f'{dbPath.name}.{_BACKUP_TAG}-{stamp}'
    dst = sqlite3.connect(target)
    try:
        conn.backup(dst)
    finally:
        dst.close()
    return target


def verifyBackup(backupPath: Path, expected: list[DriveWindow]) -> None:
    """Re-read the backup: it must pass quick_check and yield the same windows.

    Args:
        backupPath: The backup to re-read.
        expected: The keep windows computed from the live database.

    Raises:
        BackupVerificationError: When the copy cannot be opened or read, fails
            quick_check, lacks an EDR table, or yields different keep windows.
    """
    try:
        conn = sqlite3.connect(f'file:{backupPath.as_posix()}?mode=ro', uri=True)
    except sqlite3.Error as exc:
        raise BackupVerificationError(f'cannot open backup {backupPath}: {exc}') from exc
    try:
        check = conn.execute('PRAGMA quick_check').fetchone()[0]
        if check != 'ok':
            raise BackupVerificationError(f'backup {backupPath} quick_check: {check}')
        for table in EDR_SYNC_TABLES:
            conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()  # noqa: S608
        windows = keepWindows(readDriveEvents(conn))
    except (sqlite3.Error, NonCanonicalDataError) as exc:
        raise BackupVerificationError(f'cannot re-read backup {backupPath}: {exc}') from exc
    finally:
        conn.close()
    if windows != expected:
        raise BackupVerificationError(
            f'backup {backupPath} yields {len(windows)} keep window(s), '
            f'the database {len(expected)}; they differ',
        )


# ================================================================================
# CLI
# ================================================================================

def _fmt(ts: datetime) -> str:
    return ts.strftime(CANONICAL_ISO_FORMAT)


def _buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='edr_backlog_cleanup.py',
        description=(
            'US-769 one-time EDR backlog cleanup: keep rows inside drive windows. '
            'Dry run unless --apply.'
        ),
    )
    parser.add_argument('--db', default=DEFAULT_DB_PATH, help=f'obd.db (default {DEFAULT_DB_PATH})')
    parser.add_argument(
        '--apply', action='store_true',
        help='Delete rows outside every keep window, after a verified backup.',
    )
    parser.add_argument(
        '--backup-dir', default=None,
        help='Where --apply writes the backup (default: the database directory).',
    )
    return parser


def _printReport(
    mode: str,
    windows: list[DriveWindow],
    orphans: list[DriveEvent],
    plan: dict[str, dict[str, DayCounts]],
) -> None:
    print(f'[{mode}] keep windows: {len(windows)}')
    for w in windows:
        if not w.unmatched:
            continue
        reason = (
            'next drive_start'
            if w.end < w.start + PRE_DRIVE_PAD + UNMATCHED_START_CAP else '2 h cap'
        )
        print(
            f'[{mode}] UNMATCHED drive_start id={w.startEventId} at '
            f'{_fmt(w.start + PRE_DRIVE_PAD)}: window {_fmt(w.start)} .. {_fmt(w.end)} '
            f'(extended to {reason})',
        )
    for event in orphans:
        print(
            f'[{mode}] ORPHAN drive_end id={event.eventId} at {_fmt(event.at)}: '
            'no drive_start opens it, so no window is built',
        )
    for table, days in plan.items():
        for day, counts in days.items():
            print(f'[{mode}] {table} {day} kept={counts.kept} deleted={counts.deleted}')
        kept = sum(c.kept for c in days.values())
        deleted = sum(c.deleted for c in days.values())
        print(f'[{mode}] total {table} kept={kept} deleted={deleted}')


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = _buildParser().parse_args(argv)
    dbPath = Path(args.db)
    if not dbPath.is_file():
        print(f'edr_backlog_cleanup.py: error: DB not found: {dbPath}', file=sys.stderr)
        return EXIT_MISSING_INPUT

    mode = 'APPLY' if args.apply else 'DRY-RUN'
    if args.apply:
        conn = sqlite3.connect(dbPath, timeout=30.0)
    else:
        # Read-only: a dry run cannot write the database, not even a journal.
        conn = sqlite3.connect(f'file:{dbPath.as_posix()}?mode=ro', uri=True, timeout=30.0)
    try:
        present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in ('connection_log', *EDR_SYNC_TABLES) if t not in present]
        if missing:
            print(f'edr_backlog_cleanup.py: error: {dbPath} lacks table(s) {missing}',
                  file=sys.stderr)
            return EXIT_MISSING_INPUT

        try:
            events = readDriveEvents(conn)
            checkEdrTimestamps(conn)
        except NonCanonicalDataError as exc:
            print(f'[{mode}] REFUSED, nothing deleted: {exc}', file=sys.stderr)
            return EXIT_NON_CANONICAL

        windows = keepWindows(events)
        _printReport(mode, windows, orphanDriveEnds(events), planCleanup(conn, windows))

        if not args.apply:
            print('[DRY-RUN] nothing deleted. Review these counts, then re-run with --apply.')
            return EXIT_OK

        backupDir = Path(args.backup_dir) if args.backup_dir else dbPath.parent
        try:
            backup = backupDatabase(conn, dbPath, backupDir)
            verifyBackup(backup, windows)
        except (BackupVerificationError, sqlite3.Error, OSError) as exc:
            print(f'[APPLY] REFUSED, nothing deleted: backup not verified: {exc}',
                  file=sys.stderr)
            return EXIT_BACKUP_FAILED
        print(f'[APPLY] backup written and re-read: {backup}')

        for table, n in applyCleanup(conn, windows).items():
            print(f'[APPLY] deleted {table} rows={n}')
        return EXIT_OK
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
