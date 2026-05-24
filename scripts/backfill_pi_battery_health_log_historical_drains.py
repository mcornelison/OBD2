################################################################################
# File Name: backfill_pi_battery_health_log_historical_drains.py
# Purpose/Description: US-335 / Spool 2026-05-12 Story E -- one-off, idempotent
#                      backfill of the two stranded Pi-side battery_health_log
#                      rows whose end_timestamp is NULL: drain_event_id=1
#                      (the V0.24.1-ladder predates the recorder close-write)
#                      and drain_event_id=9 (the Pi died mid-drain and the
#                      endDrainEvent UPDATE didn't flush before
#                      `systemctl poweroff` -- pre-V0.27.2 root cause).
#                      The contemporaneous power_log `stage_trigger` rows are
#                      the timing-truth source for the close-time: each drain
#                      event's close is the first stage_trigger row whose
#                      timestamp falls in [drain.start_timestamp,
#                      next_drain.start_timestamp).  This script reads those
#                      rows and replays them into the stranded battery_health_log
#                      rows -- end_timestamp / end_soc / end_vcell_v /
#                      runtime_seconds, exactly the shape `endDrainEvent`
#                      writes (sans ambient_temp_c, which has no source).  The
#                      now-working (V0.27.4 US-315 + V0.27.7 US-326 + V0.27.8
#                      US-331) sync UPDATE path then propagates these to the
#                      server-side rows for source_id IN (1, 9), which is also a
#                      third orthogonal validation of the drive-side sync UPDATE.
#
#                      --execute requires a writable DB; without it the script
#                      is a read-only dry-run (the DB is opened mode=ro) that
#                      prints the plan.  Idempotent: every UPDATE keeps
#                      `AND end_timestamp IS NULL`, and rows that are already
#                      closed are skipped at plan time -- a re-run is a no-op.
#                      --drain-event-ids overrides the default {1, 9} set.
#                      A `.bak` copy of the DB is taken before --execute unless
#                      --no-backup is given.
#
#                      Scope: touches ONLY battery_health_log, ONLY the
#                      end_* columns, ONLY rows whose end_timestamp is NULL,
#                      ONLY for the configured drain_event_ids.  power_log is
#                      read-only (the timing-truth source).  The live drain-close
#                      writer (src/pi/power/battery_health.py:endDrainEvent) is
#                      untouched -- V0.27.2 is what prevents recurrence; this is
#                      purely historical backfill.
#
# Author: Agent2 (Ralph agent)
# Creation Date: 2026-05-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-12    | Agent2       | Initial -- Pi-side historical-drain backfill
#                  (US-335)      (drain_event_id 1 + 9).  Structure mirrors
#                                scripts/backfill_server_battery_health_log_
#                                stranded.py (idempotency + dry-run/execute +
#                                arg pattern); the timing-truth source is the
#                                power_log stage_trigger rows.
# ================================================================================
################################################################################

"""Pi-side stranded ``battery_health_log`` historical-drain backfill (US-335).

Run from the project root, against the Pi-side SQLite DB (default
``./data/obd.db``)::

    python scripts/backfill_pi_battery_health_log_historical_drains.py            # dry-run
    python scripts/backfill_pi_battery_health_log_historical_drains.py --execute
    python scripts/backfill_pi_battery_health_log_historical_drains.py --execute --drain-event-ids 1,9

On the Pi this is typically invoked as
``ssh chi-eclipse-01 'cd ~/Projects/Eclipse-01 && python3 scripts/backfill_pi_battery_health_log_historical_drains.py --execute'``.

Algorithm
---------

For each configured ``drain_event_id`` (default ``1`` and ``9``):

1. No ``battery_health_log`` row with that id            -> skip.
2. The row's ``end_timestamp`` is already populated       -> skip (idempotent).
3. The row's ``start_timestamp`` is missing/unparseable   -> skip (no anchor).
4. No ``power_log`` row with ``event_type='stage_trigger'`` whose timestamp is
   in ``[start_timestamp, next_drain.start_timestamp)``    -> skip (no
   timing-truth source; stopCondition -- never fabricate close-event values).
5. Otherwise emit ``UPDATE battery_health_log SET end_timestamp = <trigger.ts>,
   end_soc = <trigger.vcell>, end_vcell_v = <trigger.vcell>,
   runtime_seconds = <trigger.ts - start_timestamp> WHERE drain_event_id = N
   AND end_timestamp IS NULL;``.

``end_soc`` and ``end_vcell_v`` both receive the ``power_log.vcell`` value --
this mirrors the US-289 dual-write contract that
:meth:`src.pi.power.battery_health.BatteryHealthRecorder.endDrainEvent`
follows, so a backfilled row is shaped exactly like a recorder-closed one.  If
the ``stage_trigger`` row predates the US-252 ``vcell`` column (NULL), both
``end_soc`` and ``end_vcell_v`` stay NULL but ``end_timestamp`` /
``runtime_seconds`` are still written.

Safety
------

* Without ``--execute`` the DB is opened ``mode=ro`` -- the dry-run cannot
  mutate anything.
* With ``--execute`` a ``<db>.us335-backup-<tag>.bak`` copy is taken first
  (unless ``--no-backup``), then the UPDATE batch runs in one transaction.
  Every statement carries ``AND end_timestamp IS NULL`` so a re-run, or a
  stale plan, touches zero rows.
* If the DB carries *more* NULL-``end_timestamp`` rows than the configured
  set, the report prints a WARNING naming them (re-run with
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

from src.common.time.helper import CANONICAL_ISO_FORMAT
from src.pi.power.types import POWER_LOG_EVENT_STAGE_TRIGGER

__all__ = [
    'BATTERY_HEALTH_LOG_TABLE',
    'POWER_LOG_TABLE',
    'HISTORICAL_DRAIN_EVENT_IDS',
    'BACKFILL_COLUMNS',
    'BACKUP_SUFFIX_TEMPLATE',
    'BackfillError',
    'DrainRow',
    'StageTriggerRow',
    'BackfillRow',
    'SkippedRow',
    'BackfillPlan',
    'readDrainRows',
    'readStageTriggerRows',
    'matchStageTrigger',
    'planBackfill',
    'applyBackfill',
    'backupDb',
    'renderReport',
    'main',
]


# ================================================================================
# Configuration constants
# ================================================================================

BATTERY_HEALTH_LOG_TABLE: str = 'battery_health_log'
POWER_LOG_TABLE: str = 'power_log'

# Spool 2026-05-12 Story E: the two Pi-side rows with NULL end_timestamp.
HISTORICAL_DRAIN_EVENT_IDS: tuple[int, ...] = (1, 9)

# battery_health_log columns this script writes.  end_soc + end_vcell_v both
# get the power_log.vcell value (US-289 dual-write parity with endDrainEvent);
# ambient_temp_c is left NULL -- there is no source for it.
BACKFILL_COLUMNS: tuple[str, ...] = (
    'end_timestamp', 'end_soc', 'end_vcell_v', 'runtime_seconds',
)

# Default DB path: ./data/obd.db relative to the repo root (mirrors
# src/pi/obdii/database.py's default).  Overridable via --db-path.
DEFAULT_DB_PATH: Path = Path(__file__).resolve().parents[1] / 'data' / 'obd.db'

# Backup filename: <db name>.us335-backup-<UTC tag>.bak alongside the DB.
BACKUP_SUFFIX_TEMPLATE: str = '{name}.us335-backup-{tag}.bak'


# ================================================================================
# Exceptions
# ================================================================================

class BackfillError(Exception):
    """Operator-facing failure during the backfill (DB open / read / write)."""


# ================================================================================
# Data classes
# ================================================================================

@dataclass(slots=True, frozen=True)
class DrainRow:
    """The bits of a ``battery_health_log`` row the planner needs."""

    drainEventId: int
    startTimestamp: str | None
    endTimestamp: str | None  # None == stranded (the rows we backfill)


@dataclass(slots=True, frozen=True)
class StageTriggerRow:
    """A ``power_log`` row with ``event_type='stage_trigger'`` (timing truth)."""

    timestamp: str
    vcell: float | None


@dataclass(slots=True, frozen=True)
class BackfillRow:
    """A single ``battery_health_log`` UPDATE to apply, derived from a trigger."""

    drainEventId: int
    endTimestamp: str
    endSoc: float | None
    runtimeSeconds: int | None


@dataclass(slots=True, frozen=True)
class SkippedRow:
    """A configured drain id we did NOT backfill, with the operator-facing reason."""

    drainEventId: int
    reason: str


@dataclass(slots=True)
class BackfillPlan:
    """The planned backfill: rows to UPDATE + rows skipped (with reasons)."""

    toUpdate: list[BackfillRow] = field(default_factory=list)
    skipped: list[SkippedRow] = field(default_factory=list)


# ================================================================================
# Timestamp helpers (pure)
# ================================================================================

def _parseTimestamp(ts: str | None) -> datetime | None:
    """Parse a capture-table timestamp string to a tz-aware UTC datetime.

    Accepts the canonical ``YYYY-MM-DDTHH:MM:SSZ`` form first (every
    capture-table writer emits this); falls back to :func:`datetime.fromisoformat`
    for any legacy/offset form.  Returns ``None`` for empty/unparseable input
    so a corrupted row degrades to a skip rather than a crash.
    """
    if not ts:
        return None
    try:
        return datetime.strptime(ts, CANONICAL_ISO_FORMAT).replace(tzinfo=UTC)
    except (TypeError, ValueError):
        pass
    try:
        normalized = ts[:-1] + '+00:00' if ts.endswith('Z') else ts
        parsed = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _computeRuntimeSeconds(startTs: str | None, endTs: str | None) -> int | None:
    """Integer seconds between two timestamp strings, or ``None`` if either is bad.

    Matches :func:`src.pi.power.battery_health._computeRuntimeSeconds` so a
    backfilled ``runtime_seconds`` is computed the same way the live close
    path computes it.
    """
    start = _parseTimestamp(startTs)
    end = _parseTimestamp(endTs)
    if start is None or end is None:
        return None
    return int((end - start).total_seconds())


# ================================================================================
# Pure planning
# ================================================================================

def _nextDrainStart(allDrainRows: Sequence[DrainRow], row: DrainRow) -> str | None:
    """The earliest ``start_timestamp`` of any drain that started after ``row``.

    Used as the exclusive upper bound when matching ``row``'s close-trigger so
    a ``stage_trigger`` belonging to a later drain can't be mis-attributed.
    Returns ``None`` when ``row`` is the latest drain (no upper bound).
    """
    rowStart = _parseTimestamp(row.startTimestamp)
    if rowStart is None:
        return None
    candidates: list[tuple[datetime, str]] = []
    for other in allDrainRows:
        if other.drainEventId == row.drainEventId:
            continue
        otherStart = _parseTimestamp(other.startTimestamp)
        if otherStart is not None and otherStart > rowStart and other.startTimestamp:
            candidates.append((otherStart, other.startTimestamp))
    if not candidates:
        return None
    return min(candidates, key=lambda pair: pair[0])[1]


def matchStageTrigger(
    startTs: str | None,
    triggers: Sequence[StageTriggerRow],
    *,
    upperBoundTs: str | None,
) -> StageTriggerRow | None:
    """Return the first ``stage_trigger`` row in ``[startTs, upperBoundTs)``.

    "First" == earliest timestamp.  ``upperBoundTs=None`` means unbounded
    above.  Triggers with an unparseable timestamp, or one before ``startTs``,
    are ignored.  Returns ``None`` when no trigger qualifies.
    """
    start = _parseTimestamp(startTs)
    if start is None:
        return None
    upper = _parseTimestamp(upperBoundTs) if upperBoundTs else None
    best: StageTriggerRow | None = None
    bestDt: datetime | None = None
    for trig in triggers:
        when = _parseTimestamp(trig.timestamp)
        if when is None or when < start:
            continue
        if upper is not None and when >= upper:
            continue
        if bestDt is None or when < bestDt:
            best, bestDt = trig, when
    return best


def planBackfill(
    drainRows: Sequence[DrainRow],
    allDrainRows: Sequence[DrainRow],
    triggers: Sequence[StageTriggerRow],
    *,
    drainEventIds: Sequence[int],
) -> BackfillPlan:
    """Decide which configured drain ids to backfill, and which to skip (why).

    ``drainRows`` is the subset of ``allDrainRows`` matching ``drainEventIds``;
    ``allDrainRows`` is the full table (needed to bound each drain's
    close-trigger by the next drain's start).
    """
    byId = {row.drainEventId: row for row in drainRows}
    plan = BackfillPlan()
    for rawId in drainEventIds:
        eventId = int(rawId)
        row = byId.get(eventId)
        if row is None:
            plan.skipped.append(SkippedRow(
                eventId,
                f'no {BATTERY_HEALTH_LOG_TABLE} row with drain_event_id={eventId} '
                '(nothing to update)',
            ))
            continue
        if row.endTimestamp is not None:
            plan.skipped.append(SkippedRow(
                eventId,
                f'drain_event_id={eventId} already closed '
                f'(end_timestamp={row.endTimestamp}); idempotent skip',
            ))
            continue
        if _parseTimestamp(row.startTimestamp) is None:
            plan.skipped.append(SkippedRow(
                eventId,
                f'drain_event_id={eventId} has no parseable start_timestamp '
                f'(value={row.startTimestamp!r}); cannot anchor runtime',
            ))
            continue
        upperBoundTs = _nextDrainStart(allDrainRows, row)
        matched = matchStageTrigger(
            row.startTimestamp, triggers, upperBoundTs=upperBoundTs,
        )
        if matched is None:
            plan.skipped.append(SkippedRow(
                eventId,
                f'no {POWER_LOG_TABLE} stage_trigger row in '
                f'[{row.startTimestamp}, {upperBoundTs or "end"}) for '
                f'drain_event_id={eventId} -- no timing-truth source '
                '(stopCondition: do not fabricate close-event values)',
            ))
            continue
        plan.toUpdate.append(BackfillRow(
            drainEventId=eventId,
            endTimestamp=matched.timestamp,
            endSoc=matched.vcell,
            runtimeSeconds=_computeRuntimeSeconds(
                row.startTimestamp, matched.timestamp,
            ),
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


def readDrainRows(
    conn: sqlite3.Connection,
    *,
    drainEventIds: Sequence[int] | None = None,
) -> list[DrainRow]:
    """Read ``(drain_event_id, start_timestamp, end_timestamp)`` rows.

    ``drainEventIds=None`` reads the whole table (the planner needs it for the
    next-drain upper bound); otherwise only the listed ids.
    """
    try:
        if drainEventIds is None:
            cursor = conn.execute(
                f'SELECT drain_event_id, start_timestamp, end_timestamp '
                f'FROM {BATTERY_HEALTH_LOG_TABLE} ORDER BY drain_event_id',
            )
        else:
            ids = tuple(int(i) for i in drainEventIds)
            if not ids:
                return []
            placeholders = ','.join('?' for _ in ids)
            cursor = conn.execute(
                f'SELECT drain_event_id, start_timestamp, end_timestamp '
                f'FROM {BATTERY_HEALTH_LOG_TABLE} '
                f'WHERE drain_event_id IN ({placeholders}) ORDER BY drain_event_id',
                ids,
            )
        rows = cursor.fetchall()
    except sqlite3.Error as err:
        raise BackfillError(
            f'reading {BATTERY_HEALTH_LOG_TABLE} failed: {err}',
        ) from err
    return [
        DrainRow(
            drainEventId=int(rowId),
            startTimestamp=startTs,
            endTimestamp=endTs,
        )
        for rowId, startTs, endTs in rows
    ]


def readStageTriggerRows(conn: sqlite3.Connection) -> list[StageTriggerRow]:
    """Read all ``power_log`` rows with ``event_type='stage_trigger'`` (timing truth)."""
    try:
        rows = conn.execute(
            f'SELECT timestamp, vcell FROM {POWER_LOG_TABLE} '
            'WHERE event_type = ? ORDER BY timestamp',
            (POWER_LOG_EVENT_STAGE_TRIGGER,),
        ).fetchall()
    except sqlite3.Error as err:
        raise BackfillError(f'reading {POWER_LOG_TABLE} failed: {err}') from err
    return [
        StageTriggerRow(
            timestamp=str(ts),
            vcell=(float(vcell) if vcell is not None else None),
        )
        for ts, vcell in rows
    ]


def applyBackfill(conn: sqlite3.Connection, rows: Iterable[BackfillRow]) -> int:
    """Apply the UPDATE batch in one transaction; return rows actually changed.

    Every statement carries ``AND end_timestamp IS NULL`` so a re-run, or a
    stale plan against a since-closed row, changes nothing.  An empty batch is
    a no-op.
    """
    rowList = list(rows)
    if not rowList:
        return 0
    changed = 0
    try:
        for row in rowList:
            cursor = conn.execute(
                f'UPDATE {BATTERY_HEALTH_LOG_TABLE} SET '
                'end_timestamp = ?, end_soc = ?, end_vcell_v = ?, '
                'runtime_seconds = ? '
                'WHERE drain_event_id = ? AND end_timestamp IS NULL',
                (
                    row.endTimestamp, row.endSoc, row.endSoc,
                    row.runtimeSeconds, int(row.drainEventId),
                ),
            )
            changed += cursor.rowcount
        conn.commit()
    except sqlite3.Error as err:
        conn.rollback()
        raise BackfillError(f'UPDATE batch failed: {err}') from err
    return changed


def backupDb(dbPath: Path, *, tag: str) -> Path:
    """Copy ``dbPath`` to ``<name>.us335-backup-<tag>.bak`` alongside it."""
    backupPath = dbPath.with_name(
        BACKUP_SUFFIX_TEMPLATE.format(name=dbPath.name, tag=tag),
    )
    shutil.copy2(dbPath, backupPath)
    return backupPath


# ================================================================================
# Reporting
# ================================================================================

def renderReport(
    plan: BackfillPlan,
    *,
    dryRun: bool,
    extras: Sequence[int] = (),
) -> str:
    """Operator-facing summary of the proposed (dry-run) or applied backfill."""
    verb = 'would update' if dryRun else 'updated'
    lines: list[str] = []
    lines.append('=' * 72)
    lines.append(
        'US-335 Pi-side battery_health_log historical-drain backfill',
    )
    lines.append('=' * 72)
    lines.append(f'  mode:          {"dry-run" if dryRun else "execute"}')
    lines.append(f'  to backfill:   {len(plan.toUpdate)}')
    for row in plan.toUpdate:
        lines.append(
            f'    {verb} drain_event_id={row.drainEventId}: '
            f'end_timestamp={row.endTimestamp} end_soc={row.endSoc} '
            f'end_vcell_v={row.endSoc} runtime_seconds={row.runtimeSeconds}',
        )
    if plan.skipped:
        lines.append(f'  skipped:       {len(plan.skipped)}')
        for skip in plan.skipped:
            lines.append(f'    drain_event_id={skip.drainEventId}: {skip.reason}')
    if extras:
        idList = ', '.join(str(i) for i in extras)
        lines.append(
            f'  WARNING: {len(extras)} other {BATTERY_HEALTH_LOG_TABLE} row(s) '
            f'have a NULL end_timestamp outside the configured set '
            f'(drain_event_id {idList}); re-run with --drain-event-ids to '
            'backfill those too',
        )
    if not plan.toUpdate:
        lines.append('  -> nothing to backfill')
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
        prog='backfill_pi_battery_health_log_historical_drains.py',
        description=(
            'US-335 / Spool Story E -- backfill the stranded Pi-side '
            'battery_health_log rows (default drain_event_ids 1 and 9) from '
            'the contemporaneous power_log stage_trigger rows. Dry-run by '
            'default; pass --execute to apply.'
        ),
    )
    parser.add_argument(
        '--db-path', type=Path, default=DEFAULT_DB_PATH,
        help=f'Pi-side SQLite DB path (default: {DEFAULT_DB_PATH})',
    )
    parser.add_argument(
        '--execute', action='store_true',
        help='Apply the backfill (default is a read-only dry-run)',
    )
    parser.add_argument(
        '--no-backup', action='store_true',
        help='Skip the .bak DB copy taken before --execute',
    )
    parser.add_argument(
        '--drain-event-ids', type=str, default=None,
        help=(
            'Comma-separated drain_event_ids to backfill '
            f'(default: {",".join(str(i) for i in HISTORICAL_DRAIN_EVENT_IDS)})'
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
        drainEventIds = HISTORICAL_DRAIN_EVENT_IDS

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
            allDrainRows = readDrainRows(conn)
            triggers = readStageTriggerRows(conn)
        except BackfillError as err:
            print(f'ERROR: {err}', file=sys.stderr)
            return 2

        wantedIds = {int(i) for i in drainEventIds}
        targetRows = [r for r in allDrainRows if r.drainEventId in wantedIds]
        plan = planBackfill(
            targetRows, allDrainRows, triggers, drainEventIds=drainEventIds,
        )
        nullEndIds = {r.drainEventId for r in allDrainRows if r.endTimestamp is None}
        extras = sorted(nullEndIds - wantedIds)

        print(renderReport(plan, dryRun=not args.execute, extras=extras))

        if not args.execute:
            print('\n[dry-run] no changes made; re-run with --execute to apply')
            return 0

        if not plan.toUpdate:
            print('\n[execute] nothing to backfill')
            return 0

        if not args.no_backup:
            backupPath = backupDb(dbPath, tag=_timestampTag())
            print(f'[backup] {dbPath} -> {backupPath}')

        try:
            changed = applyBackfill(conn, plan.toUpdate)
        except BackfillError as err:
            print(f'ERROR: {err}', file=sys.stderr)
            return 2
        print(f'[execute] updated {changed} row(s)')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
