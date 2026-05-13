################################################################################
# File Name: backfill_server_battery_health_log_stranded.py
# Purpose/Description: US-323 / B-073 -- one-off backfill of the stranded
#                      server-side battery_health_log rows (drain_event_ids
#                      11-15).  V0.27.4 US-315 added the sync UPDATE-propagation
#                      path (modified_at cursor) and it works FORWARD
#                      (drain_event_id=16 closed cleanly on both Pi and server
#                      post-deploy) but it does NOT auto-replay missed historical
#                      UPDATEs -- so server rows 11-15 sit with end_timestamp
#                      NULL despite the Pi side carrying full close-event data.
#                      This script reads the Pi-side authoritative close-event
#                      values (READ-ONLY) and emits / applies the server-side
#                      MariaDB UPDATE statements.  --dry-run reports + writes a
#                      sentinel; --execute (requires a prior dry-run) takes a
#                      mysqldump backup of battery_health_log first, then issues
#                      the UPDATE batch in a single transaction.  Idempotent:
#                      already-populated server rows are skipped at plan time AND
#                      every emitted UPDATE keeps `AND end_timestamp IS NULL` so
#                      a re-apply is a no-op at the engine level.
#                      --count-stranded is a cheap server-only pre-check (no
#                      Pi SSH, no mutation, no sentinel) that prints the
#                      number of still-stranded rows and exits 0; deploy/
#                      deploy-server.sh Step 4.6 reads it to decide whether to
#                      run the full backfill (US-327 / I-027).
#
#                      Server-schema note (phantom-column drift): the sprint.json
#                      US-323 scope text + offices/pm/backlog/B-073 both name
#                      `end_vcell_v` as an UPDATE target, but the server-side
#                      battery_health_log table (v0002 migration +
#                      src/server/db/models.py BatteryHealthLog) has NO *_vcell_v
#                      columns -- only end_timestamp / end_soc / runtime_seconds.
#                      The US-289 *_vcell_v rename was Pi-side only.  This script
#                      backfills exactly the columns that exist server-side; the
#                      drift is documented here + in the US-323 completionNotes.
#                      Same drift family as US-322 (`timestamp_ms`).
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-11    | Rex (US-323) | Initial -- stranded battery_health_log
#                               server-side backfill (B-073 / Spool 2026-05-11
#                               audit Story D).  Mirrors the US-240
#                               backfill_server_premint_orphans SSH + sentinel +
#                               mysqldump-backup pattern; reuses US-209's
#                               address/credential plumbing.
# 2026-05-12    | Rex (US-327) | Add --count-stranded mode (cheap server-only
#                               pre-check: prints # of still-stranded rows,
#                               exits 0; no Pi SSH / no mutation / no sentinel)
#                               + countStrandedServerRows helper, for the new
#                               deploy/deploy-server.sh Step 4.6 idempotent
#                               invocation (I-027 -- the US-323 script shipped
#                               but nothing ever auto-ran it).
# 2026-05-13    | Agent2       | I-031 / US-331 -- no in-file change; the two
#                 (US-331)       deploy-context fixes ride through the sibling
#                                loader (`_us209`).  Specifically: the
#                                Pi-side `/home/...` sqlite3 path no longer
#                                MSYS-mangles under Git Bash because
#                                apply_server_migrations._defaultRunner now
#                                seeds `MSYS_NO_PATHCONV=1` +
#                                `MSYS2_ARG_CONV_EXCL='*'` on every subprocess
#                                env (Context 1); and loadServerCreds (also
#                                imported via `_us209`) short-circuits the
#                                self-SSH when the server address resolves to
#                                this host (Context 2).  This script reuses
#                                both seams via `loadServerCreds = _us209.
#                                loadServerCreds` + `_defaultRunner = _us209.
#                                _defaultRunner` -- no usage-site changes
#                                needed.  Regression coverage:
#                                tests/scripts/test_backfill_deploy_contexts.py.
# ================================================================================
################################################################################

"""Server-side stranded ``battery_health_log`` backfill (US-323 / B-073).

Run from the project root with SSH reachability to both ``PI_HOST`` and
``SERVER_HOST`` (resolved from ``deploy/addresses.sh``)::

    python scripts/backfill_server_battery_health_log_stranded.py --count-stranded
    python scripts/backfill_server_battery_health_log_stranded.py --dry-run
    python scripts/backfill_server_battery_health_log_stranded.py --execute

``--count-stranded`` is the cheap server-only pre-check (no Pi SSH, no
mutation, no sentinel): it prints the number of configured ``drain_event_id``
rows whose server-side ``end_timestamp`` is still NULL and exits 0.
``deploy/deploy-server.sh`` Step 4.6 reads it to decide whether to run the
full ``--dry-run`` + ``--execute`` backfill (US-327 / I-027) -- so the first
deploy after V0.27.7 heals rows 11-15 and every later deploy is a no-op.

Algorithm
---------

For each stranded ``drain_event_id`` (default 11-15):

1. If the server has no row with ``id = N`` -> skip.
2. If the server row's ``end_timestamp`` is already populated -> skip
   (idempotency: the row was either backfilled already or US-315 forward
   propagation caught it).
3. If the Pi side has no authoritative row for ``drain_event_id = N``
   (e.g. the Pi DB was reset) -> skip; the row stays *permanently
   stranded* (stopCondition).  We never fabricate close-event values.
4. If the Pi row exists but ``end_timestamp`` is still NULL (never
   closed) -> skip; there is nothing to replay.
5. Otherwise emit ``UPDATE battery_health_log SET end_timestamp = ...,
   end_soc = ..., runtime_seconds = ... WHERE id = N AND end_timestamp
   IS NULL;`` using the Pi-side values verbatim.

Safety
------

* ``--dry-run`` is read-only: it scans both sides, prints the plan, and
  writes a sentinel file.
* ``--execute`` refuses without that sentinel; it then runs
  ``mysqldump --single-transaction`` of ``battery_health_log``
  (size/time-guarded) and issues the UPDATE batch in a single MariaDB
  transaction.  The ``AND end_timestamp IS NULL`` guard on every
  statement means a stale plan cannot clobber a populated row, and a
  full re-apply matches zero rows.
* The Pi side is queried with ``sqlite3 -readonly`` -- the script never
  modifies Pi data (invariant).

Scope
-----

* Touches only the ``battery_health_log`` table, only the
  ``end_timestamp`` / ``end_soc`` / ``runtime_seconds`` columns, only
  on rows whose ``end_timestamp`` is NULL.  No PKs, no ``source_id``,
  no ``synced_at`` (US-315 keeps ``synced_at`` at INSERT time).
* The Pi-side authoritative data is read but never written.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import shlex
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    'STRANDED_DRAIN_EVENT_IDS',
    'BACKFILL_COLUMNS',
    'DRY_RUN_SENTINEL_NAME',
    'BACKUP_MAX_SECONDS',
    'BACKUP_MAX_BYTES',
    'BackfillError',
    'SafetyGateError',
    'HostAddresses',
    'ServerCreds',
    'CommandRunner',
    'PiCoordinates',
    'PiDrainRow',
    'ServerDrainRow',
    'BackfillRow',
    'SkippedRow',
    'BackfillPlan',
    'loadAddresses',
    'loadServerCreds',
    'loadPiCoordinates',
    'scanPiRows',
    'scanServerRows',
    'countStrandedServerRows',
    'planBackfill',
    'renderUpdateSql',
    'applyBackfill',
    'backupServer',
    'renderReport',
    'main',
]


# ================================================================================
# Reuse address + credential loaders from US-209 (no plumbing duplication)
# ================================================================================

_THIS_DIR = Path(__file__).resolve().parent


def _loadSibling(name: str):  # noqa: ANN202 -- module loader helper
    """Load a sibling script from scripts/ (mirrors US-240's loader)."""
    spec = importlib.util.spec_from_file_location(
        name, _THIS_DIR / f'{name}.py',
    )
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot locate sibling script: {name}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


_us209 = _loadSibling('apply_server_migrations')

HostAddresses = _us209.HostAddresses
ServerCreds = _us209.ServerCreds
CommandRunner = _us209.CommandRunner
loadAddresses = _us209.loadAddresses
loadServerCreds = _us209.loadServerCreds
_runServerSql = _us209._runServerSql
_defaultRunner = _us209._defaultRunner


# ================================================================================
# Configuration constants
# ================================================================================

# The stranded rows from Spool's 2026-05-11 audit (B-073).  Server-side
# end_timestamp = NULL for these despite Pi-side carrying close-event data.
STRANDED_DRAIN_EVENT_IDS: tuple[int, ...] = (11, 12, 13, 14, 15)

# Server-side battery_health_log columns this script writes.  Deliberately
# NOT including end_vcell_v / start_vcell_v -- those columns exist only on
# the Pi-side schema (US-289 rename); the server table never grew them.
# See the module docstring's phantom-column-drift note.
BACKFILL_COLUMNS: tuple[str, ...] = ('end_timestamp', 'end_soc', 'runtime_seconds')

# Distinct from US-240's '.us240-dry-run-ok' so a pre-mint-orphan dry-run
# does NOT silently authorize this backfill's execute.
DRY_RUN_SENTINEL_NAME: str = '.us323-dry-run-ok'

# mysqldump safety thresholds.  battery_health_log is tiny (one row per
# drain event; ~20 rows total at story time) so these are generous.
BACKUP_MAX_SECONDS: float = 30.0
BACKUP_MAX_BYTES: int = 50 * 1024 * 1024


# Canonical Pi DB path tail under PI_PATH (mirrors src/pi/obdii data dir).
_PI_DB_TAIL: str = 'data/obd.db'


# ================================================================================
# Exceptions
# ================================================================================

class BackfillError(Exception):
    """Operator-facing failure during the backfill (SSH / SQL / parse)."""


class SafetyGateError(BackfillError):
    """A safety gate (sentinel, backup timing/size) failed."""


# ================================================================================
# Data classes
# ================================================================================

@dataclass(slots=True, frozen=True)
class PiCoordinates:
    """Pi network coordinates + the SQLite DB path, from deploy/addresses.sh."""

    piHost: str
    piUser: str
    piDbPath: str


@dataclass(slots=True, frozen=True)
class PiDrainRow:
    """Authoritative close-event data for one drain event, read from the Pi."""

    drainEventId: int
    endTimestamp: str | None  # canonical ISO-8601 UTC; None if never closed
    endSoc: float | None
    runtimeSeconds: int | None


@dataclass(slots=True, frozen=True)
class ServerDrainRow:
    """Server-side row state for one drain event (only what idempotency needs)."""

    rowId: int  # server-side battery_health_log.id (== Pi's drain_event_id)
    endTimestamp: str | None  # None when stranded (the rows we backfill)


@dataclass(slots=True, frozen=True)
class BackfillRow:
    """A single server-side UPDATE to apply, sourced from the Pi side."""

    rowId: int
    endTimestamp: str
    endSoc: float | None
    runtimeSeconds: int | None


@dataclass(slots=True, frozen=True)
class SkippedRow:
    """A stranded id we did NOT backfill, with the operator-facing reason."""

    rowId: int
    reason: str


@dataclass(slots=True)
class BackfillPlan:
    """The planned backfill: rows to UPDATE + rows skipped (with reasons)."""

    toUpdate: list[BackfillRow] = field(default_factory=list)
    skipped: list[SkippedRow] = field(default_factory=list)


# ================================================================================
# Pi coordinate loader (parallel to US-209's loadAddresses, for the PI_* vars)
# ================================================================================

def loadPiCoordinates(
    addressesShPath: Path,
    runner: CommandRunner | None = None,
    *,
    piDbOverride: str | None = None,
) -> PiCoordinates:
    """Source ``deploy/addresses.sh`` and return Pi host/user + DB path.

    Mirrors :func:`scripts.apply_server_migrations.loadAddresses` but reads
    the ``PI_*`` exports.  The DB path defaults to ``$PI_PATH/data/obd.db``
    unless ``piDbOverride`` is given (CLI ``--pi-db``).
    """
    if runner is None:
        runner = _defaultRunner
    if not addressesShPath.exists():
        raise BackfillError(f'addresses.sh not found: {addressesShPath}')
    posix = addressesShPath.resolve().as_posix()
    result = runner(['bash', '-c', f'. "{posix}" && env'])
    if result.returncode != 0:
        raise BackfillError(
            f'sourcing addresses.sh failed: {result.stderr.strip()}',
        )
    env: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if '=' in line:
            k, _, v = line.partition('=')
            env[k] = v
    missing = [k for k in ('PI_HOST', 'PI_USER', 'PI_PATH') if not env.get(k)]
    if missing:
        raise BackfillError(
            f'addresses.sh missing required vars: {", ".join(missing)}',
        )
    piDbPath = piDbOverride or f'{env["PI_PATH"].rstrip("/")}/{_PI_DB_TAIL}'
    return PiCoordinates(
        piHost=env['PI_HOST'], piUser=env['PI_USER'], piDbPath=piDbPath,
    )


# ================================================================================
# Pure planning + rendering (no I/O)
# ================================================================================

def countStrandedServerRows(serverRows: Sequence[ServerDrainRow]) -> int:
    """Count server rows that are *stranded* (present but ``end_timestamp`` NULL).

    This is the cheap server-only signal :data:`deploy/deploy-server.sh`'s
    Step 4.6 reads via ``--count-stranded`` before deciding whether to run
    the full Pi-coupled backfill: zero means the deploy skips straight past
    (idempotency for re-deploys after the first successful backfill).
    """
    return sum(1 for row in serverRows if row.endTimestamp is None)


def planBackfill(
    piRows: Sequence[PiDrainRow],
    serverRows: Sequence[ServerDrainRow],
    *,
    drainEventIds: Sequence[int],
) -> BackfillPlan:
    """Decide which stranded ids to backfill and which to skip (with reasons).

    Idempotency + safety are encoded here:

    * server row missing            -> skip
    * server row already populated  -> skip (idempotent)
    * Pi row missing                -> skip (stays permanently stranded)
    * Pi row never closed           -> skip (nothing to replay)
    * otherwise                     -> :class:`BackfillRow` with Pi values
    """
    piById = {r.drainEventId: r for r in piRows}
    srvById = {r.rowId: r for r in serverRows}
    plan = BackfillPlan()
    for eventId in drainEventIds:
        srv = srvById.get(eventId)
        if srv is None:
            plan.skipped.append(SkippedRow(
                eventId,
                f'no server row id={eventId} in battery_health_log '
                '(nothing to update)',
            ))
            continue
        if srv.endTimestamp is not None:
            plan.skipped.append(SkippedRow(
                eventId,
                f'server row id={eventId} already populated '
                f'(end_timestamp={srv.endTimestamp}); idempotent skip',
            ))
            continue
        pi = piById.get(eventId)
        if pi is None:
            plan.skipped.append(SkippedRow(
                eventId,
                f'Pi-side authoritative data for drain_event_id={eventId} '
                'unavailable -- row stays permanently stranded '
                '(stopCondition: do not fabricate close-event values)',
            ))
            continue
        if pi.endTimestamp is None:
            plan.skipped.append(SkippedRow(
                eventId,
                f'Pi-side row drain_event_id={eventId} not closed '
                '(end_timestamp NULL); nothing to replay',
            ))
            continue
        plan.toUpdate.append(BackfillRow(
            rowId=eventId,
            endTimestamp=pi.endTimestamp,
            endSoc=pi.endSoc,
            runtimeSeconds=pi.runtimeSeconds,
        ))
    return plan


def _sqlNumber(value: float | int | None) -> str:
    """Render a numeric value as a SQL literal (``NULL`` when ``None``)."""
    if value is None:
        return 'NULL'
    return repr(float(value))


def _sqlInt(value: int | None) -> str:
    """Render an integer value as a SQL literal (``NULL`` when ``None``)."""
    if value is None:
        return 'NULL'
    return str(int(value))


def renderUpdateSql(rows: Sequence[BackfillRow]) -> str:
    """Render a single MariaDB transaction with one UPDATE per backfill row.

    Every UPDATE keeps ``AND end_timestamp IS NULL`` so the batch is
    idempotent at the engine level (a re-apply touches zero rows) and a
    stale plan cannot clobber a populated row.  Returns ``''`` for an
    empty row list.
    """
    rowList = list(rows)
    if not rowList:
        return ''
    lines: list[str] = ['START TRANSACTION;']
    for row in rowList:
        lines.append(
            'UPDATE battery_health_log SET '
            f"end_timestamp = '{row.endTimestamp}', "
            f'end_soc = {_sqlNumber(row.endSoc)}, '
            f'runtime_seconds = {_sqlInt(row.runtimeSeconds)} '
            f'WHERE id = {int(row.rowId)} AND end_timestamp IS NULL;'
        )
    lines.append('COMMIT;')
    return '\n'.join(lines) + '\n'


# ================================================================================
# I/O wrappers -- SSH to the Pi (sqlite3) + SSH to the server (mysql/mysqldump)
# ================================================================================

def scanPiRows(
    piCoords: PiCoordinates,
    runner: CommandRunner,
    *,
    drainEventIds: Sequence[int],
) -> list[PiDrainRow]:
    """Read the Pi-side ``battery_health_log`` close-event data (READ-ONLY).

    Uses ``sqlite3 -readonly`` over SSH so the Pi DB is never modified.
    sqlite3's list mode renders SQL NULL as an empty field; those map to
    ``None`` on the returned :class:`PiDrainRow`.
    """
    if not drainEventIds:
        return []
    idsCsv = ','.join(str(int(i)) for i in drainEventIds)
    sql = (
        'SELECT drain_event_id, end_timestamp, end_soc, runtime_seconds '
        'FROM battery_health_log '
        f'WHERE drain_event_id IN ({idsCsv}) ORDER BY drain_event_id'
    )
    remoteCmd = f'sqlite3 -readonly {shlex.quote(piCoords.piDbPath)} {shlex.quote(sql)}'
    res = runner(['ssh', f'{piCoords.piUser}@{piCoords.piHost}', remoteCmd])
    if res.returncode != 0:
        raise BackfillError(
            'reading Pi-side battery_health_log failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    rows: list[PiDrainRow] = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split('|')
        if len(parts) < 4:
            continue
        eventId, endTs, endSoc, runtimeSec = parts[:4]
        rows.append(PiDrainRow(
            drainEventId=int(eventId),
            endTimestamp=endTs or None,
            endSoc=float(endSoc) if endSoc else None,
            runtimeSeconds=int(float(runtimeSec)) if runtimeSec else None,
        ))
    return rows


def scanServerRows(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    *,
    drainEventIds: Sequence[int],
) -> list[ServerDrainRow]:
    """Read the server-side ``battery_health_log`` ``(id, end_timestamp)`` rows.

    mysql ``-B -N`` renders SQL NULL as the literal string ``NULL``; that
    (and the empty string) map to ``None``.
    """
    if not drainEventIds:
        return []
    idsCsv = ','.join(str(int(i)) for i in drainEventIds)
    sql = (
        'SELECT id, end_timestamp FROM battery_health_log '
        f'WHERE id IN ({idsCsv}) ORDER BY id;'
    )
    res = _runServerSql(addrs, creds, sql, runner)
    if res.returncode != 0:
        raise BackfillError(
            'reading server-side battery_health_log rows failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    rows: list[ServerDrainRow] = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        rowId, endTs = parts[0], parts[1]
        rows.append(ServerDrainRow(
            rowId=int(rowId),
            endTimestamp=None if endTs in ('', 'NULL') else endTs,
        ))
    return rows


def applyBackfill(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    rows: Iterable[BackfillRow],
) -> int:
    """Issue the UPDATE batch (single transaction) on the server.

    Returns the number of UPDATE statements sent.  An empty row list is a
    no-op (no subprocess call).  A non-zero mysql exit raises
    :class:`BackfillError`.
    """
    rowList = list(rows)
    if not rowList:
        return 0
    sql = renderUpdateSql(rowList)
    res = _runServerSql(addrs, creds, sql, runner)
    if res.returncode != 0:
        raise BackfillError(
            'UPDATE batch failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    return len(rowList)


def backupServer(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    timestampTag: str,
) -> str:
    """Dump ``battery_health_log`` to ``/tmp/obd2-us323-backup-<tag>.sql``.

    Uses ``mysqldump --single-transaction`` so the dump is consistent
    without locking writers.  Stop-condition guards: the dump must finish
    within :data:`BACKUP_MAX_SECONDS` and the file must be smaller than
    :data:`BACKUP_MAX_BYTES`.  Returns the server-side path.
    """
    dumpPath = f'/tmp/obd2-us323-backup-{timestampTag}.sql'
    envPrefix = f'MYSQL_PWD={shlex.quote(creds.dbPassword)}'
    cmd = (
        f'{envPrefix} mysqldump --single-transaction --skip-lock-tables '
        f'-u {shlex.quote(creds.dbUser)} '
        f'{shlex.quote(creds.dbName)} battery_health_log '
        f'> {shlex.quote(dumpPath)}'
    )
    start = time.monotonic()
    res = runner(
        ['ssh', f'{addrs.serverUser}@{addrs.serverHost}', cmd],
        timeout=BACKUP_MAX_SECONDS + 10,
    )
    elapsed = time.monotonic() - start
    if res.returncode != 0:
        raise SafetyGateError(
            'server backup failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    if elapsed > BACKUP_MAX_SECONDS:
        raise SafetyGateError(
            f'server backup exceeded {BACKUP_MAX_SECONDS:.0f}s '
            f'(took {elapsed:.1f}s)',
        )
    statRes = runner(
        ['ssh', f'{addrs.serverUser}@{addrs.serverHost}',
         f'stat -c %s {shlex.quote(dumpPath)}'],
    )
    if statRes.returncode == 0 and statRes.stdout.strip():
        try:
            nbytes = int(statRes.stdout.strip())
        except ValueError:
            nbytes = 0
        if nbytes > BACKUP_MAX_BYTES:
            raise SafetyGateError(
                f'server backup too large: {nbytes} bytes '
                f'> {BACKUP_MAX_BYTES}',
            )
    return dumpPath


# ================================================================================
# Reporting
# ================================================================================

def renderReport(
    piRows: Sequence[PiDrainRow],
    serverRows: Sequence[ServerDrainRow],
    plan: BackfillPlan,
    *,
    dryRun: bool,
) -> str:
    """Operator-facing summary of the proposed (or applied) backfill."""
    lines: list[str] = []
    lines.append('=' * 72)
    lines.append('US-323 server-side battery_health_log stranded-row backfill')
    lines.append('=' * 72)
    lines.append(f'  mode:              {"dry-run" if dryRun else "execute"}')
    lines.append(f'  Pi rows read:      {len(piRows)}')
    lines.append(f'  server rows read:  {len(serverRows)}')
    lines.append(f'  to backfill:       {len(plan.toUpdate)}')
    for row in plan.toUpdate:
        lines.append(
            f'    id={row.rowId}: end_timestamp={row.endTimestamp} '
            f'end_soc={row.endSoc} runtime_seconds={row.runtimeSeconds}',
        )
    if plan.skipped:
        lines.append(f'  skipped:           {len(plan.skipped)}')
        for skip in plan.skipped:
            lines.append(f'    id={skip.rowId}: {skip.reason}')
    if not plan.toUpdate:
        lines.append('  -> nothing to backfill')
    lines.append('=' * 72)
    return '\n'.join(lines)


# ================================================================================
# CLI -- sentinel + dry-run/execute orchestration
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


def _parseDrainEventIds(raw: str) -> tuple[int, ...]:
    parts = [chunk.strip() for chunk in raw.split(',') if chunk.strip()]
    if not parts:
        raise ValueError('--drain-event-ids must list at least one integer')
    return tuple(int(chunk) for chunk in parts)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='backfill_server_battery_health_log_stranded.py',
        description=(
            'US-323 / B-073 -- backfill the stranded server-side '
            'battery_health_log rows (default drain_event_ids 11-15) from '
            'the Pi-side authoritative close-event data. Mirror of US-240.'
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        '--dry-run', action='store_true',
        help='Scan both sides + report the plan; write a sentinel; no mutation',
    )
    mode.add_argument(
        '--execute', action='store_true',
        help='Apply the backfill after a prior --dry-run (backs up first)',
    )
    mode.add_argument(
        '--count-stranded', action='store_true',
        help=(
            'Print the number of stranded server-side rows (configured '
            'drain_event_ids whose end_timestamp is NULL) to stdout and '
            'exit 0. Cheap server-only pre-check for deploy-server.sh '
            'Step 4.6 -- no Pi SSH, no mutation, no sentinel'
        ),
    )
    parser.add_argument(
        '--addresses', type=Path, default=None,
        help='Override path to deploy/addresses.sh',
    )
    parser.add_argument(
        '--sentinel-dir', type=Path, default=None,
        help='Directory for the dry-run sentinel (defaults to the repo root)',
    )
    parser.add_argument(
        '--pi-db', type=str, default=None,
        help='Override the Pi-side SQLite path (default: $PI_PATH/data/obd.db)',
    )
    parser.add_argument(
        '--drain-event-ids', type=str, default=None,
        help=(
            'Comma-separated drain_event_ids to backfill '
            f'(default: {",".join(str(i) for i in STRANDED_DRAIN_EVENT_IDS)})'
        ),
    )
    args = parser.parse_args(argv)

    projectRoot = Path(__file__).resolve().parents[1]
    addressesPath = args.addresses or (projectRoot / 'deploy' / 'addresses.sh')
    sentinelDir = (args.sentinel_dir or projectRoot).resolve()
    if args.drain_event_ids:
        try:
            drainEventIds: tuple[int, ...] = _parseDrainEventIds(
                args.drain_event_ids,
            )
        except ValueError as err:
            print(f'ERROR: {err}', file=sys.stderr)
            return 2
    else:
        drainEventIds = STRANDED_DRAIN_EVENT_IDS

    runner: CommandRunner = _defaultRunner

    # --count-stranded: cheap server-only pre-check for deploy-server.sh Step
    # 4.6.  No Pi SSH, no mutation, no sentinel -- just SELECT id, end_timestamp
    # for the configured drain_event_ids and print how many are still NULL.
    if args.count_stranded:
        try:
            addrs = loadAddresses(addressesPath, runner=runner)
            creds = loadServerCreds(addrs, runner=runner)
            serverRows = scanServerRows(
                addrs, creds, runner, drainEventIds=drainEventIds,
            )
        except (BackfillError, _us209.MigrationError) as err:
            # loadAddresses / loadServerCreds raise the US-209 MigrationError;
            # scanServerRows raises BackfillError -- both mean "couldn't reach
            # the server cheaply", so deploy-server.sh treats rc 2 as "skip".
            print(f'ERROR: {err}', file=sys.stderr)
            return 2
        print(countStrandedServerRows(serverRows))
        return 0

    try:
        addrs = loadAddresses(addressesPath, runner=runner)
        piCoords = loadPiCoordinates(
            addressesPath, runner=runner, piDbOverride=args.pi_db,
        )
        creds = loadServerCreds(addrs, runner=runner)
        piRows = scanPiRows(piCoords, runner, drainEventIds=drainEventIds)
        serverRows = scanServerRows(
            addrs, creds, runner, drainEventIds=drainEventIds,
        )
        plan = planBackfill(piRows, serverRows, drainEventIds=drainEventIds)
        print(renderReport(piRows, serverRows, plan, dryRun=args.dry_run))
    except BackfillError as err:
        print(f'ERROR: {err}', file=sys.stderr)
        return 2

    if args.dry_run:
        _writeSentinel(
            sentinelDir,
            f'piRows={len(piRows)}\n'
            f'serverRows={len(serverRows)}\n'
            f'toUpdate={len(plan.toUpdate)}\n'
            f'skipped={len(plan.skipped)}\n'
            f'drainEventIds={",".join(str(i) for i in drainEventIds)}\n'
            f'writtenAt={_dt.datetime.now(_dt.UTC).isoformat()}\n',
        )
        print(f'\n[dry-run] sentinel: {sentinelDir / DRY_RUN_SENTINEL_NAME}')
        return 0

    # --execute path
    if _readSentinel(sentinelDir) is None:
        print(
            'ERROR: --execute requires a prior --dry-run '
            f'(missing {sentinelDir / DRY_RUN_SENTINEL_NAME})',
            file=sys.stderr,
        )
        return 2
    if not plan.toUpdate:
        print('[execute] zero rows to backfill; clearing sentinel and exiting')
        _clearSentinel(sentinelDir)
        return 0
    try:
        backupPath = backupServer(addrs, creds, runner, _timestampTag())
        print(f'[backup] server -> {backupPath}')
        applied = applyBackfill(addrs, creds, runner, plan.toUpdate)
        print(f'[execute] UPDATE applied: {applied} row(s)')
    except BackfillError as err:
        print(f'ERROR: {err}', file=sys.stderr)
        return 2
    _clearSentinel(sentinelDir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
