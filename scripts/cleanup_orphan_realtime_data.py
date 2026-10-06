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
# 2026-10-05    | Atlas (US-838)  | Retention gates on DELIVERY, never on age
#                                   alone (CIO-directed build). Both passes add
#                                   `AND id <= <realtime_data sync high-water>`
#                                   (the EDR retention purge's rule); an
#                                   unreadable or implausible mark deletes
#                                   NOTHING; every run reports deliveryMark and
#                                   heldUndelivered. 2026-10-03 03:00 deleted
#                                   263 crank lead-in rows that survived only
#                                   because the sync had happened to run first.
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

    drive_id IS NULL AND timestamp < <cutoff> AND id <= <delivery mark>

US-838: ``<delivery mark>`` is ``realtime_data``'s sync high-water mark
(``sync_log.getHighWaterMark``) -- the last id the server has. Age says a row
is OLD; only the mark says the server HAS it. A mark that cannot be read, or
that sits above every id the table ever issued (``sqlite_sequence``: the
US-809 rebuild shape), deletes NOTHING. Same rule as the EDR retention purge.

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

from src.pi.data import sync_log

__all__ = [
    'DEFAULT_AGE_HOURS',
    'DEFAULT_DB_PATH',
    'DEFAULT_RECENT_ORPHAN_AGE_HOURS',
    'CleanupSummary',
    'computeCutoff',
    'readDeliveryBound',
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
        heldUndelivered: US-838 -- rows old enough to delete but NOT yet on
            the server (above the mark, or every age-eligible row when the
            mark is unusable). Kept; they go once delivered.
        deliveryMark: US-838 -- the realtime_data sync high-water mark the
            delete was bounded by, or ``None`` when unusable (nothing deleted).
        markNote: US-838 -- why the mark was unusable (``''`` when usable).
    """

    eligibleRowCount: int
    rowsDeleted: int
    executed: bool
    cutoffTimestamp: str
    nowTimestamp: str
    heldUndelivered: int = 0
    deliveryMark: int | None = None
    markNote: str = ''


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
    return _purge(conn, cutoff, nowDt.strftime('%Y-%m-%dT%H:%M:%SZ'), execute)


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
    return _purge(conn, cutoff, nowDt.strftime('%Y-%m-%dT%H:%M:%SZ'), execute)


def readDeliveryBound(conn: sqlite3.Connection) -> tuple[int | None, str]:
    """US-838: the last realtime_data id the server has, or why it cannot be used.

    The mark is ``sync_log.getHighWaterMark`` (the one owner of that fact; the
    EDR retention purge reads the same function). ``0`` (never synced) is a
    usable mark that delivers nothing. Unusable -- and therefore delete
    NOTHING -- when it cannot be read, or when it exceeds every id the table
    ever issued (``sqlite_sequence``, else ``MAX(id)``): that is the US-809
    rebuild shape, where ``id <= mark`` would pass UNDELIVERED rows.

    Returns:
        ``(mark, '')`` when usable; ``(None, reason)`` when not. Never raises.
    """
    try:
        mark = int(sync_log.getHighWaterMark(conn, 'realtime_data')[0])
        seqRow = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'realtime_data'"
        ).fetchone()
        maxRow = conn.execute('SELECT MAX(id) FROM realtime_data').fetchone()
    except Exception as exc:  # noqa: BLE001 -- any unreadable mark deletes nothing
        return None, f'unreadable ({exc})'
    issued = max(
        int(seqRow[0]) if seqRow and seqRow[0] is not None else 0,
        int(maxRow[0]) if maxRow and maxRow[0] is not None else 0,
    )
    if mark > issued:
        return None, f'implausible (mark {mark} > highest issued id {issued})'
    return mark, ''


def _purge(
    conn: sqlite3.Connection, cutoff: str, nowStr: str, execute: bool,
) -> CleanupSummary:
    """The one predicate both passes use: old, NULL-drive, AND delivered (US-838).

    Rows that are old enough but above the mark are counted as
    ``heldUndelivered`` and kept. An unusable mark deletes nothing and holds
    every age-eligible row.
    """
    mark, note = readDeliveryBound(conn)
    ageEligible = (
        'FROM realtime_data WHERE drive_id IS NULL AND timestamp < ?'
    )
    if mark is None:
        held = int(conn.execute(f'SELECT COUNT(*) {ageEligible}', (cutoff,)).fetchone()[0])
        return CleanupSummary(
            eligibleRowCount=0, rowsDeleted=0, executed=execute,
            cutoffTimestamp=cutoff, nowTimestamp=nowStr,
            heldUndelivered=held, deliveryMark=None, markNote=note,
        )
    eligible = int(conn.execute(
        f'SELECT COUNT(*) {ageEligible} AND id <= ?', (cutoff, mark),
    ).fetchone()[0])
    held = int(conn.execute(
        f'SELECT COUNT(*) {ageEligible} AND id > ?', (cutoff, mark),
    ).fetchone()[0])
    deleted = 0
    if execute:
        deleted = conn.execute(
            f'DELETE {ageEligible} AND id <= ?', (cutoff, mark),
        ).rowcount
        conn.commit()
    return CleanupSummary(
        eligibleRowCount=eligible, rowsDeleted=deleted, executed=execute,
        cutoffTimestamp=cutoff, nowTimestamp=nowStr,
        heldUndelivered=held, deliveryMark=mark,
    )


#: How many ``.bak-us322-*`` copies to retain, newest first. orphan-cleanup.timer
#: fires NIGHTLY with Persistent=true, so an unbounded backup is 2.2 GB per night
#: on the car -- 5 copies and 11 GB had accumulated before anyone looked, with
#: roughly five weeks of SD card left. Two is enough to survive a bad run plus
#: the run before it; the DB itself is synced to the server.
DEFAULT_BACKUP_KEEP = 2


def backupDatabase(dbPath: Path, keep: int = DEFAULT_BACKUP_KEEP) -> Path:
    """Copy ``dbPath`` to ``<dbPath>.bak-us322-<ts>``, prune old copies, return it.

    Best-effort safety net before --execute touches the DB.  No locking
    is needed -- shutil.copy2 reads the file directly.

    Args:
        dbPath: The database to back up.
        keep: How many backups to retain including the one just made.

    Returns:
        Path to the backup that was created.

    Raises:
        ValueError: If ``keep`` is below 1. keep=0 would perform an expensive
            full-file copy and then delete it -- nonsense that reads as valid
            config, so it is refused rather than honoured.
    """
    if keep < 1:
        raise ValueError(
            f'keep must be >= 1 (got {keep}); keep=0 would delete the backup '
            f'it just made, leaving the copy cost with none of the safety',
        )

    ts = _dt.datetime.now(_dt.UTC).strftime('%Y%m%dT%H%M%SZ')
    backup = dbPath.with_name(f'{dbPath.name}.bak-us322-{ts}')
    shutil.copy2(dbPath, backup)

    # Prune by the TIMESTAMP IN THE NAME, not by mtime. A restore or a bulk file
    # copy rewrites mtimes -- the 2026-08-25 share migration did exactly that to
    # 79 files -- which would make mtime ordering silently select the wrong
    # victims. The name is immutable; the stamp is sortable as a string.
    # The glob is anchored to THIS db's name: data/ holds more than one database
    # and a greedy pattern would delete another one's safety net.
    pattern = f'{dbPath.name}.bak-us322-*'
    existing = sorted(dbPath.parent.glob(pattern), key=lambda p: p.name)
    for stale in existing[:-keep] if keep < len(existing) else []:
        try:
            stale.unlink()
            logger.info('pruned old DB backup: %s', stale.name)
        except OSError as exc:  # noqa: PERF203 -- one failure must not abort the rest
            logger.warning('could not prune %s: %s', stale.name, exc)

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


def _boundFields(s: CleanupSummary) -> str:
    """US-838: the delivery-bound fields every log line carries."""
    mark = 'UNREADABLE' if s.deliveryMark is None else str(s.deliveryMark)
    return f'deliveryMark={mark} heldUndelivered={s.heldUndelivered}'


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
    # US-838: every line names the delivery bound and what it held back -- a
    # run that deleted nothing must still say why (ARCH-060: silence is not a record).
    for s in (summary, sweepSummary):
        if s is not None and s.deliveryMark is None:
            warn = (
                f'[{mode}] deliveryMark=UNREADABLE ({s.markNote}) -- deleting nothing; '
                f'heldUndelivered={s.heldUndelivered}'
            )
            logger.warning(warn)
            print(warn)
            break
    line = (
        f'[{mode}] cutoff={summary.cutoffTimestamp} ageHours={args.age_hours} '
        f'nullBefore={before} eligible={summary.eligibleRowCount} '
        f'rowsDeleted={summary.rowsDeleted} nullAfter={after} '
        f'{_boundFields(summary)}'
    )
    logger.info(line)
    print(line)

    if sweepSummary is not None:
        sweepLine = (
            f'[{mode}] sweep recent-orphan cutoff={sweepSummary.cutoffTimestamp} '
            f'ageHours={args.recent_orphan_age_hours} '
            f'eligible={sweepSummary.eligibleRowCount} '
            f'rowsDeleted={sweepSummary.rowsDeleted} '
            f'nullAfter={after} '
            f'{_boundFields(sweepSummary)}'
        )
        logger.info(sweepLine)
        print(sweepLine)

    return 0


if __name__ == '__main__':
    sys.exit(main())
