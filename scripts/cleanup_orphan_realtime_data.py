################################################################################
# File Name: cleanup_orphan_realtime_data.py
# Purpose/Description: US-322 / B-072 -- delete orphan NULL-drive_id rows from
#                      Pi-side realtime_data older than --age-hours (default
#                      24).  Sources of orphans: reconnect-loop polling, I-019
#                      DriveDetector warm-restart gap, pre-DriveDetector grace
#                      period.  Approach 1 (script + nightly systemd timer);
#                      Approach 2 (writer-side guard) deferred per Spool's
#                      grooming rec.  Idempotent; --dry-run default; --execute
#                      backs up the DB first and runs in a single transaction.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author          | Description
# ================================================================================
# 2026-05-11    | Rex (US-322)    | Initial -- orphan NULL-drive_id realtime_data
#                                   cleanup (B-072 / Spool 2026-05-11 audit Story C).
#                                   Filters on the actual realtime_data column
#                                   ``timestamp`` (ISO-8601 UTC string) -- the
#                                   sprint.json spec said ``timestamp_ms`` but no
#                                   such column exists per
#                                   src/pi/obdii/database_schema.py:180.  Documented
#                                   phantom-path drift in completionNotes.
# 2026-05-13    | Agent2 (US-336) | Add recent-orphan sweep pass (Spool 2026-05-12
#                                   Story F).  Steady-state ~199 NULL-drive_id
#                                   rows accumulate in the 24h window between
#                                   firings (8/hour rate from pre-engage /
#                                   reconnect-noise polls).  ``drive_id`` is set
#                                   at INSERT-time and never updated, so any NULL
#                                   row older than the DriveDetector engage lag
#                                   (~30s typically) is permanently orphaned.
#                                   New ``runRecentOrphanSweep`` runs after the
#                                   main pass with a tighter default cutoff (4h);
#                                   ``--no-recent-orphan-sweep`` opts out.  The
#                                   existing .service ExecStart picks up the
#                                   sweep automatically (defaults are ON), so
#                                   deploy/orphan-cleanup.service (US-334's lane)
#                                   stays untouched.
# ================================================================================
################################################################################

"""Pi obd.db orphan-realtime-data cleanup (US-322 / B-072).

Run from the Pi's project root (or anywhere with read+write access to
the SQLite file)::

    # Default: dry-run, 24h cutoff, $PWD/data/obd.db
    python scripts/cleanup_orphan_realtime_data.py

    # Apply against the canonical Pi DB
    python scripts/cleanup_orphan_realtime_data.py \\
        --db /home/mcornelison/Projects/Eclipse-01/data/obd.db \\
        --execute

    # Custom age threshold
    python scripts/cleanup_orphan_realtime_data.py \\
        --db data/obd.db --age-hours 48 --execute

WHERE clause
------------

The DELETE filter is::

    drive_id IS NULL AND timestamp < <cutoff>

where ``cutoff`` is ``utcnow() - age_hours`` formatted as canonical
``YYYY-MM-DDTHH:MM:SSZ``.  This is exactly the format
``src/pi/obdii/database_schema.py:180`` emits via
``strftime('%Y-%m-%dT%H:%M:%SZ', 'now')``, so SQLite's lexical
string comparison is correct against rows written by the live writer.

Note on the spec column name
----------------------------

``offices/ralph/sprint.json`` US-322 + ``offices/pm/backlog/B-072-...md``
both refer to ``timestamp_ms``.  No such column exists -- the
realtime_data schema (``src/pi/obdii/database_schema.py:180``) has
``timestamp DATETIME NOT NULL`` storing ISO-8601 UTC strings.  This
script filters on the real column.

Safety posture
--------------

* ``--dry-run`` (default) reports the eligible row count without
  writing.
* ``--execute`` backs up the DB to ``<db>.bak-us322-<ts>`` before
  running, then issues a single DELETE inside an implicit
  transaction.  Re-running on an already-clean DB is a no-op.
* Touches only ``realtime_data``.  drive_summary, statistics,
  connection_log, drive_counter etc. are untouched.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import shutil
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    'DEFAULT_AGE_HOURS',
    'DEFAULT_DB_PATH',
    'DEFAULT_RECENT_ORPHAN_AGE_HOURS',
    'CleanupSummary',
    'computeCutoff',
    'runCleanup',
    'runRecentOrphanSweep',
    'backupDatabase',
    'main',
]


# ================================================================================
# Configuration constants
# ================================================================================

DEFAULT_AGE_HOURS: float = 24.0
DEFAULT_DB_PATH: str = 'data/obd.db'

# US-336: cutoff for the recent-orphan sweep pass.  ``drive_id`` is set at
# INSERT time and never updated, so any NULL-drive_id row older than the
# maximum DriveDetector engage lag (~30s typically) is permanently orphaned.
# 4h gives diagnostic headroom while cutting the steady-state count well
# below the post-Drive-12 ``<= 50`` orphan target.
DEFAULT_RECENT_ORPHAN_AGE_HOURS: float = 4.0


logger = logging.getLogger('cleanup_orphan_realtime_data')


# ================================================================================
# Data classes
# ================================================================================

@dataclass(slots=True, frozen=True)
class CleanupSummary:
    """Outcome of a cleanup run (dry-run or executed).

    Attributes:
        eligibleRowCount: Number of rows matching the WHERE clause at scan
            time.  In a dry-run, this is what *would* have been deleted.
        rowsDeleted: Number of rows actually removed (always 0 for
            dry-runs; equals ``eligibleRowCount`` on a successful execute).
        executed: True if a DELETE actually ran; False for dry-run.
        cutoffTimestamp: The ISO-8601 UTC string used in the WHERE clause.
        nowTimestamp: The ``now`` value the cutoff was derived from.
    """

    eligibleRowCount: int
    rowsDeleted: int
    executed: bool
    cutoffTimestamp: str
    nowTimestamp: str


# ================================================================================
# Pure helpers
# ================================================================================

def computeCutoff(
    *, ageHours: float, nowFn: Callable[[], _dt.datetime] | None = None,
) -> str:
    """Return the ISO-8601 UTC string for ``now - ageHours``.

    Format mirrors the realtime_data schema's
    ``strftime('%Y-%m-%dT%H:%M:%SZ', 'now')`` DEFAULT so SQLite's lexical
    string compare is correct.

    Args:
        ageHours: Hours to subtract from ``now``.  Must be >= 0.
        nowFn: Optional clock injection (tests pin a fixed ``_NOW``).

    Returns:
        Canonical ``YYYY-MM-DDTHH:MM:SSZ`` string (note the literal
        trailing ``Z`` -- not ``+00:00``).

    Raises:
        ValueError: when ``ageHours`` is negative.
    """
    if ageHours < 0:
        raise ValueError(
            f'ageHours must be >= 0; got {ageHours}',
        )
    now = nowFn() if nowFn is not None else _dt.datetime.now(_dt.UTC)
    cutoff = now - _dt.timedelta(hours=ageHours)
    return cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')


# ================================================================================
# Cleanup engine
# ================================================================================

def runCleanup(
    conn: sqlite3.Connection,
    *,
    ageHours: float = DEFAULT_AGE_HOURS,
    execute: bool = False,
    nowFn: Callable[[], _dt.datetime] | None = None,
) -> CleanupSummary:
    """Scan + (optionally) delete NULL-drive_id rows older than the cutoff.

    The WHERE clause is ``drive_id IS NULL AND timestamp < ?``; ``timestamp``
    here is the realtime_data column (ISO-8601 UTC string), NOT the spec's
    phantom ``timestamp_ms``.

    Args:
        conn: Open sqlite3 connection on the obd.db file.
        ageHours: Rows with timestamp older than ``now - ageHours`` are
            eligible.  Defaults to 24h.
        execute: When False, scan only (idempotent dry-run).  When True,
            issues a single DELETE and commits.
        nowFn: Optional clock injection for tests.

    Returns:
        :class:`CleanupSummary` with eligible + deleted counts and the
        cutoff timestamp used for logging.
    """
    nowDt = nowFn() if nowFn is not None else _dt.datetime.now(_dt.UTC)
    cutoff = computeCutoff(ageHours=ageHours, nowFn=lambda: nowDt)
    nowStr = nowDt.strftime('%Y-%m-%dT%H:%M:%SZ')

    eligibleRowCount = int(
        conn.execute(
            'SELECT COUNT(*) FROM realtime_data '
            'WHERE drive_id IS NULL AND timestamp < ?',
            (cutoff,),
        ).fetchone()[0],
    )

    if not execute:
        return CleanupSummary(
            eligibleRowCount=eligibleRowCount,
            rowsDeleted=0,
            executed=False,
            cutoffTimestamp=cutoff,
            nowTimestamp=nowStr,
        )

    cursor = conn.execute(
        'DELETE FROM realtime_data '
        'WHERE drive_id IS NULL AND timestamp < ?',
        (cutoff,),
    )
    conn.commit()
    return CleanupSummary(
        eligibleRowCount=eligibleRowCount,
        rowsDeleted=cursor.rowcount,
        executed=True,
        cutoffTimestamp=cutoff,
        nowTimestamp=nowStr,
    )


def runRecentOrphanSweep(
    conn: sqlite3.Connection,
    *,
    recentOrphanAgeHours: float = DEFAULT_RECENT_ORPHAN_AGE_HOURS,
    execute: bool = False,
    nowFn: Callable[[], _dt.datetime] | None = None,
) -> CleanupSummary:
    """US-336 second-pass sweep for NULL-drive_id rows aged > sweep cutoff.

    The main :func:`runCleanup` pass only catches NULL-drive_id rows older
    than ``--age-hours`` (default 24h).  Steady-state on the Pi accumulates
    ~199 NULL rows in the 24h survivor window (~8/hour from pre-engage and
    reconnect-noise polls).  Since ``drive_id`` is set at INSERT-time and
    never updated, any NULL row older than the maximum DriveDetector engage
    lag is permanently orphaned -- this sweep clears them on the same
    firing as the main pass.

    Wire-up: ``main()`` calls this AFTER :func:`runCleanup` when sweep is
    enabled (default ON; opt-out via ``--no-recent-orphan-sweep``).  The
    existing ``deploy/orphan-cleanup.service`` ExecStart inherits the new
    behaviour automatically, so the unit file (US-334's lane) does not need
    to change.

    Args:
        conn: Open sqlite3 connection on the obd.db file.
        recentOrphanAgeHours: Sweep cutoff in hours.  Rows with
            ``timestamp < now - recentOrphanAgeHours`` AND
            ``drive_id IS NULL`` are eligible.  Defaults to 4h.
        execute: When False, scan only (idempotent dry-run).  When True,
            issues a single DELETE and commits.
        nowFn: Optional clock injection for tests.

    Returns:
        :class:`CleanupSummary` with the sweep's counts + cutoff string.
    """
    nowDt = nowFn() if nowFn is not None else _dt.datetime.now(_dt.UTC)
    cutoff = computeCutoff(ageHours=recentOrphanAgeHours, nowFn=lambda: nowDt)
    nowStr = nowDt.strftime('%Y-%m-%dT%H:%M:%SZ')

    eligibleRowCount = int(
        conn.execute(
            'SELECT COUNT(*) FROM realtime_data '
            'WHERE drive_id IS NULL AND timestamp < ?',
            (cutoff,),
        ).fetchone()[0],
    )

    if not execute:
        return CleanupSummary(
            eligibleRowCount=eligibleRowCount,
            rowsDeleted=0,
            executed=False,
            cutoffTimestamp=cutoff,
            nowTimestamp=nowStr,
        )

    cursor = conn.execute(
        'DELETE FROM realtime_data '
        'WHERE drive_id IS NULL AND timestamp < ?',
        (cutoff,),
    )
    conn.commit()
    return CleanupSummary(
        eligibleRowCount=eligibleRowCount,
        rowsDeleted=cursor.rowcount,
        executed=True,
        cutoffTimestamp=cutoff,
        nowTimestamp=nowStr,
    )


def backupDatabase(dbPath: Path) -> Path:
    """Copy ``dbPath`` to ``<dbPath>.bak-us322-<ts>`` and return the path.

    Best-effort safety net before --execute touches the DB.  No locking
    is needed -- shutil.copy2 reads the file directly.
    """
    ts = _dt.datetime.now(_dt.UTC).strftime('%Y%m%dT%H%M%SZ')
    backup = dbPath.with_name(f'{dbPath.name}.bak-us322-{ts}')
    shutil.copy2(dbPath, backup)
    return backup


# ================================================================================
# CLI
# ================================================================================

def _buildParser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='cleanup_orphan_realtime_data.py',
        description=(
            'Delete NULL-drive_id orphan rows from realtime_data older than '
            '--age-hours (default 24).  US-322 / B-072.'
        ),
    )
    p.add_argument(
        '--db',
        default=DEFAULT_DB_PATH,
        help=f'Path to obd.db (default: {DEFAULT_DB_PATH}).',
    )
    p.add_argument(
        '--age-hours',
        type=float,
        default=DEFAULT_AGE_HOURS,
        help=f'Age threshold in hours (default: {DEFAULT_AGE_HOURS}).',
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        '--dry-run',
        dest='execute',
        action='store_false',
        help='Scan only; report eligible row count without deleting (default).',
    )
    g.add_argument(
        '--execute',
        dest='execute',
        action='store_true',
        help='Actually delete eligible rows (backs up DB first).',
    )
    p.set_defaults(execute=False)

    # US-336: recent-orphan sweep -- a second pass that catches NULL-drive_id
    # rows aged > recent_orphan_age_hours (default 4h).  On by default;
    # --no-recent-orphan-sweep preserves the legacy 24h-only behaviour.
    p.add_argument(
        '--recent-orphan-age-hours',
        type=float,
        default=DEFAULT_RECENT_ORPHAN_AGE_HOURS,
        help=(
            'Age threshold in hours for the recent-orphan sweep pass '
            f'(default: {DEFAULT_RECENT_ORPHAN_AGE_HOURS}).  See '
            'runRecentOrphanSweep docstring for rationale.'
        ),
    )
    p.add_argument(
        '--no-recent-orphan-sweep',
        dest='recent_orphan_sweep',
        action='store_false',
        help=(
            'Disable the US-336 second-pass recent-orphan sweep; '
            'preserves the legacy 24h-only cleanup behaviour.'
        ),
    )
    p.set_defaults(recent_orphan_sweep=True)
    return p


def _configureLogging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'),
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns process exit code."""
    _configureLogging()
    parser = _buildParser()
    args = parser.parse_args(argv)

    dbPath = Path(args.db)
    if not dbPath.exists():
        logger.error('DB not found: %s', dbPath)
        print(f'cleanup_orphan_realtime_data.py: error: DB not found: {dbPath}',
              file=sys.stderr)
        return 2

    if args.execute:
        backup = backupDatabase(dbPath)
        logger.info('Backup written: %s', backup)
        print(f'Backup written: {backup}')

    with sqlite3.connect(dbPath) as conn:
        before = int(
            conn.execute(
                'SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL',
            ).fetchone()[0],
        )
        summary = runCleanup(
            conn,
            ageHours=args.age_hours,
            execute=args.execute,
        )
        sweepSummary: CleanupSummary | None = None
        if args.recent_orphan_sweep:
            sweepSummary = runRecentOrphanSweep(
                conn,
                recentOrphanAgeHours=args.recent_orphan_age_hours,
                execute=args.execute,
            )
        after = int(
            conn.execute(
                'SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL',
            ).fetchone()[0],
        )

    mode = 'EXECUTE' if summary.executed else 'DRY-RUN'
    line = (
        f'[{mode}] cutoff={summary.cutoffTimestamp} ageHours={args.age_hours} '
        f'nullBefore={before} eligible={summary.eligibleRowCount} '
        f'rowsDeleted={summary.rowsDeleted} nullAfter={after}'
    )
    logger.info(line)
    print(line)

    if sweepSummary is not None:
        sweepLine = (
            f'[{mode}] sweep recent-orphan cutoff={sweepSummary.cutoffTimestamp} '
            f'ageHours={args.recent_orphan_age_hours} '
            f'eligible={sweepSummary.eligibleRowCount} '
            f'rowsDeleted={sweepSummary.rowsDeleted} '
            f'nullAfter={after}'
        )
        logger.info(sweepLine)
        print(sweepLine)

    return 0


if __name__ == '__main__':
    sys.exit(main())
