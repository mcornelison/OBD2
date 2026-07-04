################################################################################
# File Name: annotate_orphan_production_drain_events.py
# Purpose/Description: US-442 / F-062 -- one-off, idempotent tombstone
#                      annotation of the 4 historical orphan `production`
#                      drain_event rows in the Pi-side battery_health_log
#                      (drain_event_id 1, 9, 18, 21; end_timestamp IS NULL;
#                      load_class='production').  These rows were opened by the
#                      now-retired US-216 auto-write path (0 callers post
#                      TD-058 / US-427) and never closed on poweroff.  Per the
#                      US-434 disposition (issue Option C, PM-endorsed
#                      "annotate, never delete") this script writes a provenance
#                      `notes` string so the rows are self-documenting historical
#                      residue -- it does NOT fabricate an end_timestamp (there is
#                      no timing-truth source for a close; honest-instrument) and
#                      it does NOT delete any data.
#
#                      Scope: touches ONLY battery_health_log, ONLY the `notes`
#                      column, ONLY rows whose end_timestamp IS NULL AND
#                      load_class='production' AND whose note does not already
#                      carry the provenance tag, ONLY for the configured
#                      drain_event_ids.  A closed row, a non-production row, and
#                      an already-tagged row are each skipped with a reason.  An
#                      existing (non-tag) note is preserved -- the provenance is
#                      appended, never overwritten.  The live drain writer
#                      (src/pi/power/battery_health.py) is untouched; the
#                      auto-open path that produced these rows is already retired,
#                      so no new orphans can form (see that file's US-442 note).
#
#                      --execute requires a writable DB; without it the script is
#                      a read-only dry-run (mode=ro) that prints the plan.
#                      Idempotent: every UPDATE re-asserts the end_timestamp /
#                      load_class / not-already-tagged guards, so a re-run (or a
#                      stale plan) touches zero rows.  --drain-event-ids overrides
#                      the default {1, 9, 18, 21} set.  A `.bak` copy of the DB is
#                      taken before --execute unless --no-backup is given.
#
#                      Server reconciliation: the Pi-side `notes` change
#                      propagates to the already-synced server copy through the
#                      same sync UPDATE path that carries end_* changes
#                      (US-315 / US-326 / US-331) -- confirm the server row after
#                      the next sync (this script targets the Pi SQLite DB only).
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-03    | Rex (US-442) | Initial -- historical orphan-production-drain
#                               tombstone annotation.  Structure mirrors
#                               scripts/backfill_pi_battery_health_log_
#                               historical_drains.py (US-335): dry-run/execute +
#                               idempotency + backup + --drain-event-ids arg.
# ================================================================================
################################################################################

"""Historical orphan-``production``-drain tombstone annotation (US-442 / F-062).

Run from the project root, against the Pi-side SQLite DB (default
``./data/obd.db``)::

    python scripts/annotate_orphan_production_drain_events.py            # dry-run
    python scripts/annotate_orphan_production_drain_events.py --execute
    python scripts/annotate_orphan_production_drain_events.py --execute --drain-event-ids 1,9,18,21

On the Pi this is typically invoked as
``ssh chi-eclipse-01 'cd ~/Projects/Eclipse-01 && python3 scripts/annotate_orphan_production_drain_events.py --execute'``.

Algorithm
---------

For each configured ``drain_event_id`` (default ``1, 9, 18, 21``):

1. No ``battery_health_log`` row with that id            -> skip.
2. The row's ``end_timestamp`` is populated (closed)      -> skip (not an
   orphan; never annotate a completed drain).
3. The row's ``load_class`` is not ``'production'``        -> skip (the US-434
   residue is production-only; leave test/sim rows alone).
4. The row already carries the provenance tag             -> skip (idempotent).
5. Otherwise annotate: set ``notes`` to the provenance string
   (:data:`PROVENANCE_NOTE`), preserving any pre-existing non-tag note by
   appending after :data:`NOTE_SEPARATOR`.

The row's ``end_timestamp`` is left NULL -- there is no timing-truth source for
a close, and inventing one would violate honest-instrument.  Analytics
runtime-trend baselines already require a non-NULL ``runtime_seconds``, so these
rows stay correctly excluded; the tombstone just makes them self-documenting.

Safety
------

* Without ``--execute`` the DB is opened ``mode=ro`` -- the dry-run cannot
  mutate anything.
* With ``--execute`` a ``<db>.us442-backup-<tag>.bak`` copy is taken first
  (unless ``--no-backup``), then the UPDATE batch runs in one transaction.
  Every statement re-asserts ``end_timestamp IS NULL`` + ``load_class =
  'production'`` + not-already-tagged, so a re-run, or a stale plan, touches
  zero rows.
* No row is ever deleted; ``notes`` is the only column written.
* If the DB carries *more* NULL-``end_timestamp`` ``production`` rows than the
  configured set, the report prints a WARNING naming them (re-run with
  ``--drain-event-ids`` to include them) -- it does not silently widen scope.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.pi.power.battery_health import (
    BATTERY_HEALTH_LOG_TABLE,
    LOAD_CLASS_DEFAULT,
)

__all__ = [
    'BATTERY_HEALTH_LOG_TABLE',
    'ORPHAN_DRAIN_EVENT_IDS',
    'PRODUCTION_LOAD_CLASS',
    'PROVENANCE_TAG',
    'PROVENANCE_NOTE',
    'NOTE_SEPARATOR',
    'BACKUP_SUFFIX_TEMPLATE',
    'AnnotateError',
    'OrphanRow',
    'AnnotateRow',
    'SkippedRow',
    'AnnotatePlan',
    'readOrphanRows',
    'planAnnotate',
    'applyAnnotate',
    'backupDb',
    'renderReport',
    'main',
]


# ================================================================================
# Configuration constants
# ================================================================================

# The 4 historical orphan rows flagged in US-434 (issue
# I-orphaned-production-drain-event-rows.md): NULL end_timestamp, production.
ORPHAN_DRAIN_EVENT_IDS: tuple[int, ...] = (1, 9, 18, 21)

# Only production orphans are in scope (LOAD_CLASS_DEFAULT == 'production').
PRODUCTION_LOAD_CLASS: str = LOAD_CLASS_DEFAULT

# Stable substring used for idempotency (LIKE match) + self-documentation.  The
# provenance note embeds it so a re-run recognizes an already-annotated row.
PROVENANCE_TAG: str = 'orphaned-US216-autowrite-residue'

# The full tombstone note written to `notes`.
PROVENANCE_NOTE: str = (
    f'{PROVENANCE_TAG} (US-442): production drain opened by the retired US-216 '
    'auto-write path and never closed on poweroff; retained as historical '
    'residue, NOT a real completed drain (no end_timestamp -- no timing-truth '
    'source for a close). Excluded from runtime-trend baselines.'
)

# Separator used when a pre-existing (non-tag) note must be preserved.
NOTE_SEPARATOR: str = ' | '

# Default DB path: ./data/obd.db relative to the repo root (mirrors
# src/pi/obdii/database.py's default).  Overridable via --db-path.
DEFAULT_DB_PATH: Path = Path(__file__).resolve().parents[1] / 'data' / 'obd.db'

# Backup filename: <db name>.us442-backup-<UTC tag>.bak alongside the DB.
BACKUP_SUFFIX_TEMPLATE: str = '{name}.us442-backup-{tag}.bak'


# ================================================================================
# Exceptions
# ================================================================================

class AnnotateError(Exception):
    """Operator-facing failure during the annotation (DB open / read / write)."""


# ================================================================================
# Data classes
# ================================================================================

@dataclass(slots=True, frozen=True)
class OrphanRow:
    """The bits of a ``battery_health_log`` row the planner needs."""

    drainEventId: int
    endTimestamp: str | None  # None == still open (the orphans we annotate)
    loadClass: str | None
    notes: str | None


@dataclass(slots=True, frozen=True)
class AnnotateRow:
    """A single ``battery_health_log`` ``notes`` UPDATE to apply."""

    drainEventId: int
    newNotes: str


@dataclass(slots=True, frozen=True)
class SkippedRow:
    """A configured drain id we did NOT annotate, with the operator-facing reason."""

    drainEventId: int
    reason: str


@dataclass(slots=True)
class AnnotatePlan:
    """The planned annotation: rows to UPDATE + rows skipped (with reasons)."""

    toAnnotate: list[AnnotateRow] = field(default_factory=list)
    skipped: list[SkippedRow] = field(default_factory=list)


# ================================================================================
# Pure planning
# ================================================================================

def _composeNote(existing: str | None) -> str:
    """Return the note to store: the provenance string, preserving any prior note.

    A NULL/empty prior note becomes just :data:`PROVENANCE_NOTE`.  A non-empty
    prior note is preserved verbatim with the provenance appended after
    :data:`NOTE_SEPARATOR` -- US-442 never overwrites operator context.
    """
    if not existing:
        return PROVENANCE_NOTE
    return f'{existing}{NOTE_SEPARATOR}{PROVENANCE_NOTE}'


def planAnnotate(
    rows: Sequence[OrphanRow],
    *,
    drainEventIds: Sequence[int],
) -> AnnotatePlan:
    """Decide which configured drain ids to annotate, and which to skip (why).

    ``rows`` is the full ``battery_health_log`` row set (id/end/load_class/notes).
    Each configured id is resolved against it and classified per the module
    algorithm.  Pure: no DB access, so it is trivially unit-testable.
    """
    byId = {row.drainEventId: row for row in rows}
    plan = AnnotatePlan()
    for rawId in drainEventIds:
        eventId = int(rawId)
        row = byId.get(eventId)
        if row is None:
            plan.skipped.append(SkippedRow(
                eventId,
                f'no {BATTERY_HEALTH_LOG_TABLE} row with drain_event_id={eventId} '
                '(nothing to annotate)',
            ))
            continue
        if row.endTimestamp is not None:
            plan.skipped.append(SkippedRow(
                eventId,
                f'drain_event_id={eventId} is already closed '
                f'(end_timestamp={row.endTimestamp}); not an orphan -- never '
                'annotate a completed drain',
            ))
            continue
        if row.loadClass != PRODUCTION_LOAD_CLASS:
            plan.skipped.append(SkippedRow(
                eventId,
                f'drain_event_id={eventId} is load_class={row.loadClass!r}, '
                f'not {PRODUCTION_LOAD_CLASS!r}; out of scope (US-434 residue is '
                'production-only)',
            ))
            continue
        if row.notes is not None and PROVENANCE_TAG in row.notes:
            plan.skipped.append(SkippedRow(
                eventId,
                f'drain_event_id={eventId} already carries the provenance tag; '
                'idempotent skip',
            ))
            continue
        plan.toAnnotate.append(AnnotateRow(
            drainEventId=eventId,
            newNotes=_composeNote(row.notes),
        ))
    return plan


# ================================================================================
# Database I/O
# ================================================================================

def _connect(dbPath: Path, *, readOnly: bool) -> sqlite3.Connection:
    """Open ``dbPath`` -- read-only (``mode=ro`` URI) unless ``readOnly`` is False.

    Read-only is the dry-run default so the script structurally cannot mutate
    the DB without ``--execute``.
    """
    if readOnly:
        uri = f'{dbPath.resolve().as_uri()}?mode=ro'
        return sqlite3.connect(uri, uri=True)
    return sqlite3.connect(str(dbPath))


def readOrphanRows(conn: sqlite3.Connection) -> list[OrphanRow]:
    """Read ``(drain_event_id, end_timestamp, load_class, notes)`` for every row.

    The whole table is read so the planner can (a) resolve each configured id
    and (b) report extra NULL-end production rows outside the configured set.
    """
    try:
        rows = conn.execute(
            f'SELECT drain_event_id, end_timestamp, load_class, notes '
            f'FROM {BATTERY_HEALTH_LOG_TABLE} ORDER BY drain_event_id',
        ).fetchall()
    except sqlite3.Error as err:
        raise AnnotateError(
            f'reading {BATTERY_HEALTH_LOG_TABLE} failed: {err}',
        ) from err
    return [
        OrphanRow(
            drainEventId=int(rowId),
            endTimestamp=endTs,
            loadClass=loadClass,
            notes=notes,
        )
        for rowId, endTs, loadClass, notes in rows
    ]


def applyAnnotate(conn: sqlite3.Connection, rows: Iterable[AnnotateRow]) -> int:
    """Apply the ``notes`` UPDATE batch in one transaction; return rows changed.

    Every statement re-asserts ``end_timestamp IS NULL`` + ``load_class =
    'production'`` + not-already-tagged, so a re-run, or a stale plan against a
    since-closed/since-tagged row, changes nothing.  An empty batch is a no-op.
    """
    rowList = list(rows)
    if not rowList:
        return 0
    likePattern = f'%{PROVENANCE_TAG}%'
    changed = 0
    try:
        for row in rowList:
            cursor = conn.execute(
                f'UPDATE {BATTERY_HEALTH_LOG_TABLE} SET notes = ? '
                'WHERE drain_event_id = ? '
                'AND end_timestamp IS NULL '
                'AND load_class = ? '
                'AND (notes IS NULL OR notes NOT LIKE ?)',
                (
                    row.newNotes, int(row.drainEventId),
                    PRODUCTION_LOAD_CLASS, likePattern,
                ),
            )
            changed += cursor.rowcount
        conn.commit()
    except sqlite3.Error as err:
        conn.rollback()
        raise AnnotateError(f'UPDATE batch failed: {err}') from err
    return changed


def backupDb(dbPath: Path, *, tag: str) -> Path:
    """Copy ``dbPath`` to ``<name>.us442-backup-<tag>.bak`` alongside it."""
    backupPath = dbPath.with_name(
        BACKUP_SUFFIX_TEMPLATE.format(name=dbPath.name, tag=tag),
    )
    shutil.copy2(dbPath, backupPath)
    return backupPath


# ================================================================================
# Reporting
# ================================================================================

def _extraOrphanIds(
    rows: Sequence[OrphanRow], configured: Sequence[int],
) -> list[int]:
    """NULL-end ``production`` ids present in the DB but outside ``configured``."""
    wanted = {int(i) for i in configured}
    return sorted(
        row.drainEventId
        for row in rows
        if row.endTimestamp is None
        and row.loadClass == PRODUCTION_LOAD_CLASS
        and row.drainEventId not in wanted
    )


def renderReport(
    plan: AnnotatePlan,
    *,
    dryRun: bool,
    extras: Sequence[int] = (),
) -> str:
    """Operator-facing summary of the proposed (dry-run) or applied annotation."""
    verb = 'would annotate' if dryRun else 'annotated'
    lines: list[str] = []
    lines.append('=' * 72)
    lines.append(
        'US-442 orphan-production-drain tombstone annotation',
    )
    lines.append('=' * 72)
    lines.append(f'  mode:          {"dry-run" if dryRun else "execute"}')
    lines.append(f'  to annotate:   {len(plan.toAnnotate)}')
    for row in plan.toAnnotate:
        lines.append(
            f'    {verb} drain_event_id={row.drainEventId}: '
            f'notes <- {row.newNotes!r}',
        )
    if plan.skipped:
        lines.append(f'  skipped:       {len(plan.skipped)}')
        for skip in plan.skipped:
            lines.append(f'    drain_event_id={skip.drainEventId}: {skip.reason}')
    if extras:
        idList = ', '.join(str(i) for i in extras)
        lines.append(
            f'  WARNING: {len(extras)} other NULL-end production '
            f'{BATTERY_HEALTH_LOG_TABLE} row(s) outside the configured set '
            f'(drain_event_id {idList}); re-run with --drain-event-ids to '
            'annotate those too',
        )
    if not plan.toAnnotate:
        lines.append('  -> nothing to annotate')
    lines.append('=' * 72)
    return '\n'.join(lines)


# ================================================================================
# CLI
# ================================================================================

def _timestampTag() -> str:
    return datetime.now(UTC).strftime('%Y%m%d-%H%M%SZ')


def _parseDrainEventIds(raw: str) -> tuple[int, ...]:
    parts = [chunk.strip() for chunk in raw.split(',') if chunk.strip()]
    if not parts:
        raise ValueError('--drain-event-ids must list at least one integer')
    return tuple(int(chunk) for chunk in parts)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='annotate_orphan_production_drain_events.py',
        description=(
            'US-442 / F-062 -- tombstone-annotate the 4 historical orphan '
            'production battery_health_log rows (default drain_event_ids '
            '1, 9, 18, 21) with a provenance note. Never closes (no fabricated '
            'end_timestamp) and never deletes. Dry-run by default; pass '
            '--execute to apply.'
        ),
    )
    parser.add_argument(
        '--db-path', type=Path, default=DEFAULT_DB_PATH,
        help=f'Pi-side SQLite DB path (default: {DEFAULT_DB_PATH})',
    )
    parser.add_argument(
        '--execute', action='store_true',
        help='Apply the annotation (default is a read-only dry-run)',
    )
    parser.add_argument(
        '--no-backup', action='store_true',
        help='Skip the .bak DB copy taken before --execute',
    )
    parser.add_argument(
        '--drain-event-ids', type=str, default=None,
        help=(
            'Comma-separated drain_event_ids to annotate '
            f'(default: {",".join(str(i) for i in ORPHAN_DRAIN_EVENT_IDS)})'
        ),
    )
    args = parser.parse_args(argv)

    if args.drain_event_ids:
        try:
            drainEventIds: tuple[int, ...] = _parseDrainEventIds(args.drain_event_ids)
        except ValueError as err:
            print(f'ERROR: {err}', file=sys.stderr)
            return 2
    else:
        drainEventIds = ORPHAN_DRAIN_EVENT_IDS

    dbPath: Path = args.db_path
    if not dbPath.exists():
        print(f'ERROR: database not found: {dbPath}', file=sys.stderr)
        return 2

    try:
        conn = _connect(dbPath, readOnly=not args.execute)
    except sqlite3.Error as err:
        print(f'ERROR: cannot open database {dbPath}: {err}', file=sys.stderr)
        return 2

    try:
        try:
            allRows = readOrphanRows(conn)
        except AnnotateError as err:
            print(f'ERROR: {err}', file=sys.stderr)
            return 2

        plan = planAnnotate(allRows, drainEventIds=drainEventIds)
        extras = _extraOrphanIds(allRows, drainEventIds)

        print(renderReport(plan, dryRun=not args.execute, extras=extras))

        if not args.execute:
            print('\n[dry-run] no changes made; re-run with --execute to apply')
            return 0

        if not plan.toAnnotate:
            print('\n[execute] nothing to annotate')
            return 0

        if not args.no_backup:
            backupPath = backupDb(dbPath, tag=_timestampTag())
            print(f'[backup] {dbPath} -> {backupPath}')

        try:
            changed = applyAnnotate(conn, plan.toAnnotate)
        except AnnotateError as err:
            print(f'ERROR: {err}', file=sys.stderr)
            return 2
        print(f'[execute] annotated {changed} row(s)')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
