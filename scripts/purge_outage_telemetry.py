################################################################################
# File Name: purge_outage_telemetry.py
# Purpose/Description: US-774 -- one-time delete of the April/May outage-era
#                      retry telemetry and the drive 2 simulator rows, on the Pi
#                      (obd.db) and the server (MariaDB). DRY RUN by default;
#                      --apply backs up and re-reads every tier before any
#                      delete, and rolls a tier back if a kept row moves.
# Author: Rex (US-774)
# Creation Date: 2026-09-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-15    | Rex (US-774) | Initial -- outage telemetry + drive 2 purge with
#                               verified per-tier backups and scope stops.
# ================================================================================
################################################################################

"""One-time purge of outage-era retry telemetry and drive 2 simulator rows (US-774).

Each tier is optional; name the ones this host can reach::

    # On the Pi, dry run (default): per-statement counts, writes nothing
    python scripts/purge_outage_telemetry.py --pi-db data/obd.db

    # On the server (DATABASE_URL from the environment), dry run
    python scripts/purge_outage_telemetry.py --server

    # After the CIO has reviewed the counts
    python scripts/purge_outage_telemetry.py --server --backup-dir ~/us774 --apply

Ruled scope
-----------

Pi (``pi``):
    * ``connection_log WHERE timestamp < '2026-06-01'`` -- EVERY event type,
      success rows and drive markers included.
    * ``realtime_data WHERE drive_id = 2`` (all ``physics_sim``).
    * ``drive_summary WHERE drive_id = 2``.

Server (``server``):
    * ``connection_log WHERE timestamp < '2026-06-01' AND event_type IN
      ('connect_attempt', 'connect_failure', 'disconnect')``. A server timestamp
      predicate cannot be built without its event_type filter.
    * ``connection_log WHERE drive_id = 2`` -- the two drive 2 markers. The one
      server statement with no event_type filter, by design.

Stops (non-zero exit, nothing deleted)
--------------------------------------

* A tier holds a ``drive_id = 2`` row that none of its statements delete, in any
  table: the scope was measured as clear, so a surprise means it is wrong.
* A Pi ``realtime_data`` drive 2 row that is not ``physics_sim``.
* A table's delete count is above its recorded scope. Retention only removes
  rows, so growth is never explained by it. Lower counts are printed for review.
* A backup that cannot be re-read (exit 4).
* A delete that changes any row outside the ruled scope, or deletes a count other
  than the one planned: that tier is rolled back (exit 5).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event, inspect, text
from sqlalchemy.exc import SQLAlchemyError

__all__ = [
    'BackupVerificationError',
    'InvariantBrokenError',
    'PurgeStatement',
    'RECORDED_SCOPE',
    'applyTier',
    'backupPiDatabase',
    'backupServerTables',
    'buildPiStatements',
    'buildServerStatements',
    'drivePredicate',
    'main',
    'makeEngine',
    'planCounts',
    'readServerBackup',
    'scopeSurprises',
    'serverKeptCounts',
    'timestampPredicate',
    'verifyPiBackup',
    'verifyServerBackup',
]

# ================================================================================
# Constants (US-774 examples)
# ================================================================================

PI = 'pi'
SERVER = 'server'
PURGE_CUTOFF = '2026-06-01'
SIM_DRIVE_ID = 2
SIM_DATA_SOURCE = 'physics_sim'
SERVER_RETRY_EVENT_TYPES = ('connect_attempt', 'connect_failure', 'disconnect')
SERVER_KEPT_EVENT_TYPES = ('connect_success', 'reconnect', 'drive_start', 'drive_end')
REALTIME_TABLE = 'realtime_data'

# Rows each (tier, table) was measured to delete on 2026-09-15.
RECORDED_SCOPE: dict[tuple[str, str], int] = {
    (PI, 'connection_log'): 44_704,
    (PI, REALTIME_TABLE): 1_853,
    (PI, 'drive_summary'): 1,
    (SERVER, 'connection_log'): 16_306 + 2,
}

EXIT_OK = 0
EXIT_MISSING_INPUT = 2
EXIT_SCOPE_SURPRISE = 3
EXIT_BACKUP_FAILED = 4
EXIT_INVARIANT_BROKEN = 5

_BACKUP_TAG = 'bak-us774'


class BackupVerificationError(RuntimeError):
    """A backup taken before --apply could not be re-read as a faithful copy."""


class InvariantBrokenError(RuntimeError):
    """A delete changed rows outside the ruled scope; the tier was rolled back."""


@dataclass(frozen=True, slots=True)
class PurgeStatement:
    """One ruled DELETE: a table on a tier and its WHERE predicate."""

    tier: str
    table: str
    where: str

    @property
    def deleteSql(self) -> str:
        """The DELETE statement this purge executes."""
        return f'DELETE FROM {self.table} WHERE {self.where}'  # noqa: S608


# ================================================================================
# Statement generation
# ================================================================================

def timestampPredicate(tier: str, eventTypes: Sequence[str]) -> str:
    """Build the pre-cutoff predicate, with an event_type filter when given.

    Args:
        tier: ``pi`` or ``server``.
        eventTypes: Event types to restrict to; empty means every type.

    Returns:
        The WHERE predicate text.

    Raises:
        ValueError: For a server predicate without event types -- a timestamp-only
            server delete would take the success rows the story keeps.
    """
    if tier == SERVER and not eventTypes:
        raise ValueError('a server timestamp delete must carry an event_type filter')
    predicate = f"timestamp < '{PURGE_CUTOFF}'"
    if eventTypes:
        predicate += ' AND event_type IN (' + ', '.join(f"'{t}'" for t in eventTypes) + ')'
    return predicate


def drivePredicate() -> str:
    """Return the predicate selecting the drive 2 simulator rows."""
    return f'drive_id = {SIM_DRIVE_ID}'


def buildPiStatements() -> tuple[PurgeStatement, ...]:
    """Return the Pi deletes, in execution order."""
    return (
        PurgeStatement(PI, 'connection_log', timestampPredicate(PI, ())),
        PurgeStatement(PI, REALTIME_TABLE, drivePredicate()),
        PurgeStatement(PI, 'drive_summary', drivePredicate()),
    )


def buildServerStatements() -> tuple[PurgeStatement, ...]:
    """Return the server deletes, in execution order."""
    return (
        PurgeStatement(SERVER, 'connection_log',
                       timestampPredicate(SERVER, SERVER_RETRY_EVENT_TYPES)),
        PurgeStatement(SERVER, 'connection_log', drivePredicate()),
    )


def _matchesAny(statements: Sequence[PurgeStatement], table: str) -> str:
    """SQL true (never NULL) when a row matches any statement on ``table``."""
    clauses = [f'COALESCE(({s.where}), 0) = 1' for s in statements if s.table == table]
    return '(' + ' OR '.join(clauses) + ')' if clauses else '(1 = 0)'


def _tables(statements: Sequence[PurgeStatement]) -> list[str]:
    return list(dict.fromkeys(s.table for s in statements))


# ================================================================================
# Read-only planning and scope checks
# ================================================================================

def makeEngine(url: str) -> Engine:
    """Create a synchronous engine; an async MariaDB URL is switched to pymysql."""
    return create_engine(url.replace('+aiomysql://', '+pymysql://', 1))


def _scalar(conn: Connection, sql: str) -> int:
    return int(conn.execute(text(sql)).scalar_one())


def planCounts(conn: Connection, statements: Sequence[PurgeStatement]) -> list[int]:
    """Count the rows each statement will delete, net of earlier statements.

    Args:
        conn: Connection on the tier.
        statements: The tier's statements, in execution order.

    Returns:
        One count per statement, equal to the rowcount its DELETE will report.
    """
    counts = []
    for index, statement in enumerate(statements):
        earlier = _matchesAny(statements[:index], statement.table)
        counts.append(_scalar(
            conn,
            f'SELECT COUNT(*) FROM {statement.table}'  # noqa: S608
            f' WHERE COALESCE(({statement.where}), 0) = 1 AND NOT {earlier}',
        ))
    return counts


def scopeSurprises(
    conn: Connection, statements: Sequence[PurgeStatement], counts: Sequence[int],
) -> list[str]:
    """Return every observation that says the ruled scope is wrong for this tier.

    Args:
        conn: Connection on the tier.
        statements: The tier's statements.
        counts: Their :func:`planCounts`.

    Returns:
        Human-readable stop reasons; empty when the tier matches its scope.
    """
    tier = statements[0].tier
    inspector = inspect(conn)
    surprises = []
    for table in inspector.get_table_names():
        if 'drive_id' not in {c['name'] for c in inspector.get_columns(table)}:
            continue
        residual = _scalar(
            conn,
            f'SELECT COUNT(*) FROM {table}'  # noqa: S608
            f' WHERE {drivePredicate()} AND NOT {_matchesAny(statements, table)}',
        )
        if residual:
            surprises.append(
                f'{tier} {table} holds {residual} drive {SIM_DRIVE_ID} row(s) '
                'that no ruled statement deletes',
            )

    realtimeDrive = [s for s in statements
                     if s.table == REALTIME_TABLE and s.where == drivePredicate()]
    if realtimeDrive:
        real = _scalar(
            conn,
            f'SELECT COUNT(*) FROM {REALTIME_TABLE} WHERE {drivePredicate()}'  # noqa: S608
            f" AND COALESCE(data_source, '') <> '{SIM_DATA_SOURCE}'",
        )
        if real:
            surprises.append(
                f'{tier} {REALTIME_TABLE} drive {SIM_DRIVE_ID} holds {real} row(s) '
                f'that are not {SIM_DATA_SOURCE}',
            )

    for table in _tables(statements):
        observed = sum(n for s, n in zip(statements, counts, strict=True) if s.table == table)
        recorded = RECORDED_SCOPE[(tier, table)]
        if observed > recorded:
            surprises.append(
                f'{tier} {table}: observed {observed} row(s) to delete, recorded {recorded}',
            )
    return surprises


def serverKeptCounts(conn: Connection) -> dict[str, int]:
    """Count the pre-cutoff server connection_log rows of each kept event type."""
    kept = ', '.join(f"'{t}'" for t in SERVER_KEPT_EVENT_TYPES)
    rows = conn.execute(text(
        'SELECT event_type, COUNT(*) FROM connection_log'  # noqa: S608
        f" WHERE timestamp < '{PURGE_CUTOFF}' AND event_type IN ({kept})"
        ' GROUP BY event_type',
    )).all()
    found = {str(r[0]): int(r[1]) for r in rows}
    return {t: found.get(t, 0) for t in SERVER_KEPT_EVENT_TYPES}


# ================================================================================
# Backups
# ================================================================================

def _stamp() -> str:
    return datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')


def backupPiDatabase(dbPath: Path, backupDir: Path) -> Path:
    """Copy the whole Pi database with SQLite's online backup API.

    Args:
        dbPath: The live obd.db.
        backupDir: Directory the copy is written to.

    Returns:
        Path of the backup file.
    """
    target = backupDir / f'{dbPath.name}.{_BACKUP_TAG}-{_stamp()}'
    src = sqlite3.connect(dbPath, timeout=30.0)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return target


def verifyPiBackup(
    backupPath: Path, statements: Sequence[PurgeStatement], expected: Sequence[int],
) -> None:
    """Re-read the Pi copy: it must pass quick_check and plan the same counts.

    Raises:
        BackupVerificationError: When the copy cannot be read or plans differently.
    """
    engine = makeEngine(f'sqlite:///file:{backupPath.as_posix()}?mode=ro&uri=true')
    try:
        with engine.connect() as conn:
            check = conn.exec_driver_sql('PRAGMA quick_check').scalar_one()
            if check != 'ok':
                raise BackupVerificationError(f'backup {backupPath} quick_check: {check}')
            counts = planCounts(conn, statements)
    except SQLAlchemyError as exc:
        raise BackupVerificationError(f'cannot re-read backup {backupPath}: {exc}') from exc
    finally:
        engine.dispose()
    if counts != list(expected):
        raise BackupVerificationError(
            f'backup {backupPath} plans {counts} row(s), the database {list(expected)}',
        )


def _backupLine(table: str, row: dict[str, Any]) -> str:
    return json.dumps({'table': table, 'row': row}, sort_keys=True, default=str)


def _digest(lines: Sequence[str]) -> str:
    return hashlib.sha256('\n'.join(lines).encode('utf-8')).hexdigest()


def backupServerTables(
    conn: Connection, statements: Sequence[PurgeStatement], backupDir: Path,
) -> tuple[Path, str]:
    """Export every server table the statements delete from, whole, as JSON lines.

    Args:
        conn: Connection on the server database.
        statements: The server statements.
        backupDir: Directory the export is written to.

    Returns:
        ``(path, sha256 of the exported lines)``.
    """
    tables = _tables(statements)
    lines = []
    for table in tables:
        result = conn.execute(text(f'SELECT * FROM {table} ORDER BY id'))  # noqa: S608
        lines.extend(_backupLine(table, dict(row._mapping)) for row in result)
    target = backupDir / f'{SERVER}-{"+".join(tables)}.{_BACKUP_TAG}-{_stamp()}.jsonl'
    target.write_text(''.join(line + '\n' for line in lines), encoding='utf-8')
    return target, _digest(lines)


def readServerBackup(backupPath: Path) -> list[dict[str, Any]]:
    """Read a server export back as ``[{'table': ..., 'row': {...}}, ...]``.

    Raises:
        BackupVerificationError: When the file cannot be read or parsed.
    """
    try:
        text_ = backupPath.read_text(encoding='utf-8')
        return [json.loads(line) for line in text_.splitlines() if line]
    except (OSError, ValueError) as exc:
        raise BackupVerificationError(f'cannot re-read backup {backupPath}: {exc}') from exc


def verifyServerBackup(
    conn: Connection, statements: Sequence[PurgeStatement], backupPath: Path, digest: str,
) -> None:
    """Re-read the server export: same content as written, holding every row to delete.

    Raises:
        BackupVerificationError: When the file differs from what was exported or
            lacks a row a statement would delete.
    """
    entries = readServerBackup(backupPath)
    if _digest([_backupLine(e['table'], e['row']) for e in entries]) != digest:
        raise BackupVerificationError(f'backup {backupPath} does not match what was exported')
    for statement in statements:
        backedUp = {e['row']['id'] for e in entries if e['table'] == statement.table}
        doomed = {int(r[0]) for r in conn.execute(text(
            f'SELECT id FROM {statement.table} WHERE {statement.where}',  # noqa: S608
        ))}
        missing = doomed - backedUp
        if missing:
            raise BackupVerificationError(
                f'backup {backupPath} lacks {len(missing)} {statement.table} row(s) to delete',
            )


# ================================================================================
# Apply
# ================================================================================

def _snapshot(conn: Connection, statements: Sequence[PurgeStatement]) -> dict[str, Any]:
    """Everything a correct delete leaves unchanged."""
    snapshot: dict[str, Any] = {
        f'{table} rows outside the ruled scope': _scalar(
            conn, f'SELECT COUNT(*) FROM {table} WHERE NOT {_matchesAny(statements, table)}',  # noqa: S608
        )
        for table in _tables(statements)
    }
    if inspect(conn).has_table(REALTIME_TABLE):
        snapshot[f'{REALTIME_TABLE} rows per drive other than {SIM_DRIVE_ID}'] = sorted(
            (-1 if r[0] is None else int(r[0]), int(r[1])) for r in conn.execute(text(
                f'SELECT drive_id, COUNT(*) FROM {REALTIME_TABLE}'  # noqa: S608
                f' WHERE drive_id IS NULL OR drive_id <> {SIM_DRIVE_ID} GROUP BY drive_id',
            ))
        )
    return snapshot


def _executeDeletes(conn: Connection, statements: Sequence[PurgeStatement]) -> list[int]:
    return [conn.execute(text(s.deleteSql)).rowcount for s in statements]


def applyTier(
    engine: Engine, statements: Sequence[PurgeStatement], expected: Sequence[int],
) -> tuple[list[int], dict[str, Any]]:
    """Run a tier's deletes in one transaction, rolling back on any surprise.

    Args:
        engine: Writable engine on the tier.
        statements: The tier's statements, in execution order.
        expected: Their :func:`planCounts`.

    Returns:
        ``(rows deleted per statement, the unchanged snapshot)``.

    Raises:
        InvariantBrokenError: When a count differs from the plan or a row outside
            the ruled scope changed. Nothing is committed.
    """
    with engine.begin() as conn:
        before = _snapshot(conn, statements)
        deleted = _executeDeletes(conn, statements)
        after = _snapshot(conn, statements)
        if deleted != list(expected):
            raise InvariantBrokenError(f'deleted {deleted} row(s), planned {list(expected)}')
        if after != before:
            changed = [k for k in before if before[k] != after.get(k)]
            raise InvariantBrokenError(f'rows outside the ruled scope changed: {changed}')
    return deleted, before


def _lockOnBegin(engine: Engine) -> None:
    """Make an SQLite transaction take its write lock before the first read.

    pysqlite otherwise opens the transaction only at the first DELETE, so the
    before-snapshot would race the running collector.
    """
    @event.listens_for(engine, 'connect')
    def _noAutoBegin(dbapiConnection: Any, _record: Any) -> None:
        dbapiConnection.isolation_level = None

    @event.listens_for(engine, 'begin')
    def _beginImmediate(conn: Connection) -> None:
        conn.exec_driver_sql('BEGIN IMMEDIATE')


# ================================================================================
# CLI
# ================================================================================

@dataclass(slots=True)
class _Tier:
    name: str
    url: str
    statements: tuple[PurgeStatement, ...]
    piPath: Path | None = None
    counts: list[int] | None = None


def _buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='US-774: purge April/May retry telemetry and drive 2 simulator rows.',
    )
    parser.add_argument('--pi-db', help='Pi obd.db to purge (the Pi tier).')
    parser.add_argument('--server', action='store_true',
                        help='Purge the server tier at the DATABASE_URL env var.')
    parser.add_argument('--server-url', help='Server SQLAlchemy URL (implies --server).')
    parser.add_argument('--backup-dir',
                        help='Backup directory (default: beside obd.db / current directory).')
    parser.add_argument('--apply', action='store_true',
                        help='Back up, re-read, then delete. Default is a dry run.')
    return parser


def _resolveTiers(args: argparse.Namespace, mode: str) -> list[_Tier] | None:
    tiers = []
    if args.pi_db:
        path = Path(args.pi_db)
        if not path.is_file():
            print(f'purge_outage_telemetry.py: error: Pi DB not found: {path}', file=sys.stderr)
            return None
        url = (f'sqlite:///{path.as_posix()}' if mode == 'APPLY'
               else f'sqlite:///file:{path.as_posix()}?mode=ro&uri=true')
        tiers.append(_Tier(PI, url, buildPiStatements(), piPath=path))
    serverUrl = args.server_url or (os.environ.get('DATABASE_URL') if args.server else None)
    if args.server and not serverUrl:
        print('purge_outage_telemetry.py: error: --server needs DATABASE_URL', file=sys.stderr)
        return None
    if serverUrl:
        tiers.append(_Tier(SERVER, serverUrl, buildServerStatements()))
    if not tiers:
        print('purge_outage_telemetry.py: error: name a tier (--pi-db and/or --server)',
              file=sys.stderr)
        return None
    return tiers


def _planTier(tier: _Tier, mode: str) -> list[str] | None:
    """Print the tier's counts; return its stop reasons, or None if tables are missing."""
    engine = makeEngine(tier.url)
    try:
        with engine.connect() as conn:
            present = set(inspect(conn).get_table_names())
            missing = [t for t in _tables(tier.statements) if t not in present]
            if missing:
                print(f'purge_outage_telemetry.py: error: {tier.name} lacks table(s) {missing}',
                      file=sys.stderr)
                return None
            tier.counts = planCounts(conn, tier.statements)
            for statement, count in zip(tier.statements, tier.counts, strict=True):
                print(f'[{mode}] {tier.name} {statement.table} WHERE {statement.where}'
                      f' -> {count} row(s)')
            for table in _tables(tier.statements):
                observed = sum(n for s, n in zip(tier.statements, tier.counts, strict=True)
                               if s.table == table)
                recorded = RECORDED_SCOPE[(tier.name, table)]
                if observed < recorded:
                    print(f'[{mode}] {tier.name} {table}: {observed} row(s) against a recorded'
                          f' {recorded} -- confirm retention explains the difference')
            if tier.name == SERVER:
                kept = serverKeptCounts(conn)
                print(f'[{mode}] server keep before {PURGE_CUTOFF}: '
                      + ', '.join(f'{t}={n}' for t, n in kept.items()))
            return scopeSurprises(conn, tier.statements, tier.counts)
    finally:
        engine.dispose()


def _backupTier(tier: _Tier, backupDir: Path | None) -> Path:
    assert tier.counts is not None
    if tier.piPath is not None:
        target = backupDir or tier.piPath.parent
        target.mkdir(parents=True, exist_ok=True)
        backup = backupPiDatabase(tier.piPath, target)
        verifyPiBackup(backup, tier.statements, tier.counts)
        return backup
    target = backupDir or Path.cwd()
    target.mkdir(parents=True, exist_ok=True)
    engine = makeEngine(tier.url)
    try:
        with engine.connect() as conn:
            backup, digest = backupServerTables(conn, tier.statements, target)
            verifyServerBackup(conn, tier.statements, backup, digest)
    finally:
        engine.dispose()
    return backup


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = _buildParser().parse_args(argv)
    mode = 'APPLY' if args.apply else 'DRY-RUN'
    tiers = _resolveTiers(args, mode)
    if tiers is None:
        return EXIT_MISSING_INPUT

    surprises: list[str] = []
    try:
        for tier in tiers:
            found = _planTier(tier, mode)
            if found is None:
                return EXIT_MISSING_INPUT
            surprises.extend(found)
    except SQLAlchemyError as exc:
        print(f'[{mode}] cannot read a tier, nothing deleted: {exc}', file=sys.stderr)
        return EXIT_MISSING_INPUT
    if surprises:
        for reason in surprises:
            print(f'[{mode}] STOP, nothing deleted: {reason}', file=sys.stderr)
        return EXIT_SCOPE_SURPRISE

    if not args.apply:
        print('[DRY-RUN] nothing deleted. Review these counts, then re-run with --apply.')
        return EXIT_OK

    backupDir = Path(args.backup_dir) if args.backup_dir else None
    try:
        for tier in tiers:
            print(f'[APPLY] {tier.name} backup verified: {_backupTier(tier, backupDir)}')
    except (BackupVerificationError, OSError, sqlite3.Error, SQLAlchemyError) as exc:
        print(f'[APPLY] REFUSED, nothing deleted: backup failed: {exc}', file=sys.stderr)
        return EXIT_BACKUP_FAILED

    for tier in tiers:
        assert tier.counts is not None
        engine = makeEngine(tier.url)
        if tier.piPath is not None:
            _lockOnBegin(engine)
        try:
            deleted, kept = applyTier(engine, tier.statements, tier.counts)
        except (InvariantBrokenError, SQLAlchemyError) as exc:
            print(f'[APPLY] {tier.name} ROLLED BACK, nothing deleted on this tier: {exc}',
                  file=sys.stderr)
            return EXIT_INVARIANT_BROKEN
        finally:
            engine.dispose()
        for statement, count in zip(tier.statements, deleted, strict=True):
            print(f'[APPLY] {tier.name} {statement.table} WHERE {statement.where}'
                  f' deleted {count} row(s)')
        for label, value in kept.items():
            shown = len(value) if isinstance(value, list) else value
            print(f'[APPLY] {tier.name} unchanged: {label} = {shown}')
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
