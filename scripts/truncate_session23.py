################################################################################
# File Name: truncate_session23.py
# Purpose/Description: Clean-slate truncate of Session 23 first-light operational
#                      rows from Pi data/obd.db + server obd2db MariaDB, plus
#                      drive_counter reset to 0.  Implements US-205 (Sprint 15)
#                      per CIO directive 2026-04-20.
#
#                      Script is defensive: --dry-run scans state + reports
#                      counts without mutating anything; --execute requires a
#                      prior successful --dry-run, backs up both DBs before
#                      any DELETE, runs DELETEs transactionally, and verifies
#                      the regression fixture (eclipse_idle.db) SHA-256 was
#                      not touched.
#
#                      When Pi/server schemas diverge (data_source, drive_id,
#                      or drive_counter missing on either host), the script
#                      refuses --execute per stopCondition #4 and prints a
#                      structured report so the operator can decide next
#                      steps.
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-205) | Initial -- Session 23 operational truncate
# ================================================================================
################################################################################

"""Session 23 operational truncate + drive_counter reset (US-205).

Run this script from the project root:

    python scripts/truncate_session23.py --dry-run
    python scripts/truncate_session23.py --execute

Both steps require SSH reachability to ``PI_HOST`` (chi-eclipse-01) and
``SERVER_HOST`` (chi-srv-01).  Addresses resolve via ``deploy/addresses.sh``
(B-044 canonical source) or environment overrides.

Intent: after this lands, the next REAL vehicle drive mints ``drive_id=1``
on both hosts against an otherwise empty set of tagged-real rows.  The
regression fixture ``data/regression/pi-inputs/eclipse_idle.db`` is NOT
touched -- SHA-256 is asserted before and after ``--execute``.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import shlex
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

__all__ = [
    'HostAddresses',
    'ServerCreds',
    'StateReport',
    'TableState',
    'CommandRunner',
    'loadAddresses',
    'loadServerCreds',
    'probePiColumns',
    'probeServerColumns',
    'scanPiState',
    'scanServerState',
    'scanOrphans',
    'verifyFixtureHash',
    'piServiceIsActive',
    'stopPiService',
    'startPiService',
    'backupPi',
    'backupServer',
    'executePiTruncate',
    'executeServerTruncate',
    'divergenceDetected',
    'renderReport',
    'main',
]


# ================================================================================
# Constants
# ================================================================================

PI_TABLES: tuple[str, ...] = (
    'realtime_data',
    'connection_log',
    'statistics',
    'alert_log',
)

SERVER_TABLES: tuple[str, ...] = (
    'realtime_data',
    'connection_log',
    'statistics',
    'alert_log',
)

FIXTURE_RELATIVE_PATH: str = 'data/regression/pi-inputs/eclipse_idle.db'
FIXTURE_EXPECTED_SHA256: str = (
    '0b90b188fa31f6285d8440ba1a251678a2ac652dd589314a50062fa06c5d38db'
)
FIXTURE_EXPECTED_BYTES: int = 188_416

DRY_RUN_SENTINEL_NAME: str = '.us205-dry-run-ok'
SESSION23_WINDOW_START: str = '2026-04-19 07:18:50'
SESSION23_WINDOW_END: str = '2026-04-19 07:20:41'


# ================================================================================
# Exceptions
# ================================================================================

class TruncateError(Exception):
    """Base class for operator-facing truncate failures."""


class SchemaDivergenceError(TruncateError):
    """Raised when Pi/server schemas diverge from spec expectations."""


class SafetyGateError(TruncateError):
    """Raised when a safety gate (dry-run sentinel, backup) fails."""


# ================================================================================
# Configuration / injection seams
# ================================================================================

class CommandRunner(Protocol):
    """Injectable subprocess runner for SSH/local commands (test seam)."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- matches subprocess API
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


def _defaultRunner(
    argv: Sequence[str],
    *,
    input: str | None = None,  # noqa: A002
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Default subprocess-based runner used in production."""
    return subprocess.run(  # noqa: S603 -- argv is explicit list
        list(argv),
        input=input,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@dataclass(slots=True, frozen=True)
class HostAddresses:
    """Pi + server network coordinates resolved from deploy/addresses.sh."""

    piHost: str
    piUser: str
    piPath: str
    piPort: str
    serverHost: str
    serverUser: str


@dataclass(slots=True, frozen=True)
class ServerCreds:
    """MariaDB DSN pieces parsed from the server's DATABASE_URL env."""

    dbUser: str
    dbPassword: str
    dbName: str


@dataclass(slots=True)
class TableState:
    """Per-table row counts and column-presence flags."""

    name: str
    rows: int
    dataSourceRows: int | None  # None -> column missing on host
    hasDataSourceColumn: bool
    hasDriveIdColumn: bool
    earliestTs: str | None = None
    latestTs: str | None = None


@dataclass(slots=True)
class StateReport:
    """Consolidated dry-run state report across Pi + server."""

    piTables: list[TableState] = field(default_factory=list)
    serverTables: list[TableState] = field(default_factory=list)
    piDriveCounterLast: int | None = None
    serverHasDriveCounter: bool = False
    serverDriveCounterLast: int | None = None
    fixtureShaMatches: bool = False
    fixtureSha: str = ''
    fixtureBytes: int = 0
    aiRecsWindowCount: int = 0
    calibSessionsWindowCount: int = 0
    divergenceReasons: list[str] = field(default_factory=list)


# ================================================================================
# Address + credential loaders
# ================================================================================

def loadAddresses(
    addressesShPath: Path,
    runner: CommandRunner = _defaultRunner,
) -> HostAddresses:
    """Source ``deploy/addresses.sh`` via bash and return exported values.

    Bash execution is the authoritative resolver (the file uses the
    ``${VAR:-default}`` pattern).  We avoid re-parsing the shell syntax
    in Python because that invites drift.
    """
    if not addressesShPath.exists():
        raise TruncateError(f'addresses.sh not found: {addressesShPath}')
    # Use POSIX form so git-bash on Windows accepts the path (backslash
    # escaping otherwise corrupts drive-letter paths like "Z:\").
    posix = addressesShPath.resolve().as_posix()
    cmd = f'. "{posix}" && env'
    result = runner(['bash', '-c', cmd])
    if result.returncode != 0:
        raise TruncateError(
            f'sourcing addresses.sh failed: {result.stderr.strip()}'
        )
    env: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if '=' in line:
            k, _, v = line.partition('=')
            env[k] = v
    missing = [
        k
        for k in (
            'PI_HOST', 'PI_USER', 'PI_PATH', 'PI_PORT',
            'SERVER_HOST', 'SERVER_USER',
        )
        if not env.get(k)
    ]
    if missing:
        raise TruncateError(
            f'addresses.sh missing required vars: {", ".join(missing)}'
        )
    return HostAddresses(
        piHost=env['PI_HOST'],
        piUser=env['PI_USER'],
        piPath=env['PI_PATH'],
        piPort=env['PI_PORT'],
        serverHost=env['SERVER_HOST'],
        serverUser=env['SERVER_USER'],
    )


def loadServerCreds(
    addrs: HostAddresses,
    runner: CommandRunner = _defaultRunner,
) -> ServerCreds:
    """Fetch server ``.env`` DATABASE_URL via SSH and parse DSN pieces."""
    remote = f'{addrs.serverUser}@{addrs.serverHost}'
    # Read the project .env on the server; DATABASE_URL follows the
    # SQLAlchemy aiomysql form: mysql+aiomysql://USER:PASS@HOST/DB.
    script = (
        "grep '^DATABASE_URL=' /mnt/projects/O/OBD2v2/.env | "
        "head -1 | cut -d= -f2-"
    )
    result = runner(['ssh', remote, script])
    if result.returncode != 0 or not result.stdout.strip():
        raise TruncateError(
            f'could not read DATABASE_URL on {remote}: {result.stderr.strip()}'
        )
    dsn = result.stdout.strip()
    # Expected: mysql+aiomysql://USER:PASSWORD@HOST/DBNAME
    try:
        _, rest = dsn.split('://', 1)
        userpass, hostdb = rest.rsplit('@', 1)
        dbUser, dbPassword = userpass.split(':', 1)
        _, dbName = hostdb.split('/', 1)
    except ValueError as err:
        raise TruncateError(f'malformed DATABASE_URL: {dsn!r}') from err
    return ServerCreds(
        dbUser=dbUser, dbPassword=dbPassword, dbName=dbName,
    )


# ================================================================================
# SSH command helpers
# ================================================================================

def _sshPi(
    addrs: HostAddresses,
    remoteCmd: str,
    runner: CommandRunner,
    *,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    remote = f'{addrs.piUser}@{addrs.piHost}'
    return runner(['ssh', '-p', addrs.piPort, remote, remoteCmd], input=stdin)


def _sshServer(
    addrs: HostAddresses,
    remoteCmd: str,
    runner: CommandRunner,
    *,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    remote = f'{addrs.serverUser}@{addrs.serverHost}'
    return runner(['ssh', remote, remoteCmd], input=stdin)


def _runPiSql(
    addrs: HostAddresses,
    sql: str,
    runner: CommandRunner,
) -> subprocess.CompletedProcess[str]:
    dbPath = f'{addrs.piPath}/data/obd.db'
    cmd = f'sqlite3 {shlex.quote(dbPath)}'
    return _sshPi(addrs, cmd, runner, stdin=sql)


def _runServerSql(
    addrs: HostAddresses,
    creds: ServerCreds,
    sql: str,
    runner: CommandRunner,
) -> subprocess.CompletedProcess[str]:
    # -B => tab-delimited, -N => no headers, -u/-p => auth, -D => database.
    # Password passed via MYSQL_PWD env to keep it out of `ps`.
    remote = f'{addrs.serverUser}@{addrs.serverHost}'
    envPrefix = f'MYSQL_PWD={shlex.quote(creds.dbPassword)}'
    cmd = (
        f'{envPrefix} mysql -u {shlex.quote(creds.dbUser)} '
        f'-B -N -D {shlex.quote(creds.dbName)}'
    )
    return runner(['ssh', remote, cmd], input=sql)


# ================================================================================
# Schema probes
# ================================================================================

def _parseColumnsSqlite(output: str) -> list[str]:
    cols: list[str] = []
    for line in output.splitlines():
        parts = line.split('|')
        if len(parts) >= 2:
            cols.append(parts[1])
    return cols


def probePiColumns(
    addrs: HostAddresses,
    tableName: str,
    runner: CommandRunner,
) -> list[str]:
    """Return the list of column names for ``tableName`` on the Pi SQLite DB."""
    res = _runPiSql(addrs, f'PRAGMA table_info({tableName});', runner)
    if res.returncode != 0:
        return []
    return _parseColumnsSqlite(res.stdout)


def probeServerColumns(
    addrs: HostAddresses,
    creds: ServerCreds,
    tableName: str,
    runner: CommandRunner,
) -> list[str]:
    """Return column names for ``tableName`` on the server MariaDB."""
    sql = (
        f"SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        f"WHERE TABLE_SCHEMA='{creds.dbName}' "
        f"AND TABLE_NAME='{tableName}';"
    )
    res = _runServerSql(addrs, creds, sql, runner)
    if res.returncode != 0:
        return []
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


# ================================================================================
# State scan
# ================================================================================

def _scanOneTable(
    tableName: str,
    columns: Iterable[str],
    countAll: int,
    countReal: int | None,
    earliest: str | None,
    latest: str | None,
) -> TableState:
    colSet = set(columns)
    return TableState(
        name=tableName,
        rows=countAll,
        dataSourceRows=countReal,
        hasDataSourceColumn='data_source' in colSet,
        hasDriveIdColumn='drive_id' in colSet,
        earliestTs=earliest,
        latestTs=latest,
    )


def _timestampColumnForPi(tableName: str) -> str | None:
    # statistics uses analysis_date, connection_log + realtime_data +
    # alert_log use timestamp.  Return None to skip the range query if
    # the table has no conventional time column.
    return {
        'realtime_data': 'timestamp',
        'connection_log': 'timestamp',
        'statistics': 'analysis_date',
        'alert_log': 'timestamp',
    }.get(tableName)


def scanPiState(
    addrs: HostAddresses,
    runner: CommandRunner,
) -> tuple[list[TableState], int | None]:
    """Scan Pi per-table row counts + drive_counter last_id."""
    tables: list[TableState] = []
    for tableName in PI_TABLES:
        cols = probePiColumns(addrs, tableName, runner)
        if not cols:
            tables.append(
                TableState(
                    name=tableName,
                    rows=0,
                    dataSourceRows=None,
                    hasDataSourceColumn=False,
                    hasDriveIdColumn=False,
                ),
            )
            continue
        hasDs = 'data_source' in cols
        tsCol = _timestampColumnForPi(tableName)
        if hasDs:
            countReal: int | None = _scalarIntPi(
                addrs, runner,
                f"SELECT COUNT(*) FROM {tableName} "
                f"WHERE data_source='real';",
            )
        else:
            countReal = None
        countAll = _scalarIntPi(
            addrs, runner, f'SELECT COUNT(*) FROM {tableName};',
        ) or 0
        earliest: str | None = None
        latest: str | None = None
        if tsCol and countAll > 0:
            rangeRes = _runPiSql(
                addrs,
                f'SELECT MIN({tsCol}), MAX({tsCol}) FROM {tableName};',
                runner,
            )
            if rangeRes.returncode == 0 and rangeRes.stdout.strip():
                row = rangeRes.stdout.strip().split('|', 1)
                if len(row) == 2:
                    earliest, latest = row[0] or None, row[1] or None
        tables.append(
            _scanOneTable(tableName, cols, countAll, countReal, earliest, latest),
        )
    counterLast = _scalarIntPi(
        addrs, runner,
        'SELECT last_drive_id FROM drive_counter WHERE id=1;',
    )
    return tables, counterLast


def scanServerState(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
) -> tuple[list[TableState], bool, int | None]:
    """Scan server per-table row counts + drive_counter presence/value."""
    tables: list[TableState] = []
    for tableName in SERVER_TABLES:
        cols = probeServerColumns(addrs, creds, tableName, runner)
        if not cols:
            tables.append(
                TableState(
                    name=tableName,
                    rows=0,
                    dataSourceRows=None,
                    hasDataSourceColumn=False,
                    hasDriveIdColumn=False,
                ),
            )
            continue
        hasDs = 'data_source' in cols
        if hasDs:
            countReal: int | None = _scalarIntServer(
                addrs, creds, runner,
                f"SELECT COUNT(*) FROM {tableName} "
                f"WHERE data_source='real';",
            )
        else:
            countReal = None
        countAll = _scalarIntServer(
            addrs, creds, runner,
            f'SELECT COUNT(*) FROM {tableName};',
        ) or 0
        tables.append(
            _scanOneTable(tableName, cols, countAll, countReal, None, None),
        )
    # drive_counter presence check + value if present
    tablesPresent = _runServerSql(
        addrs, creds,
        "SHOW TABLES LIKE 'drive_counter';",
        runner,
    )
    hasCounter = (
        tablesPresent.returncode == 0 and bool(tablesPresent.stdout.strip())
    )
    counterLast: int | None = None
    if hasCounter:
        counterLast = _scalarIntServer(
            addrs, creds, runner,
            'SELECT last_drive_id FROM drive_counter WHERE id=1;',
        )
    return tables, hasCounter, counterLast


def _scalarIntPi(
    addrs: HostAddresses, runner: CommandRunner, sql: str,
) -> int | None:
    res = _runPiSql(addrs, sql, runner)
    if res.returncode != 0:
        return None
    txt = res.stdout.strip()
    if not txt:
        return None
    try:
        return int(txt.split()[0].split('|')[0])
    except ValueError:
        return None


def _scalarIntServer(
    addrs: HostAddresses, creds: ServerCreds, runner: CommandRunner, sql: str,
) -> int | None:
    res = _runServerSql(addrs, creds, sql, runner)
    if res.returncode != 0:
        return None
    txt = res.stdout.strip()
    if not txt:
        return None
    try:
        return int(txt.split()[0])
    except ValueError:
        return None


# ================================================================================
# Orphan scan (ai_recommendations + calibration_sessions)
# ================================================================================

def scanOrphans(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
) -> tuple[int, int]:
    """Scan server for Session 23-window rows in derived tables."""
    ai = _scalarIntServer(
        addrs, creds, runner,
        f"SELECT COUNT(*) FROM ai_recommendations "
        f"WHERE drive_start BETWEEN '{SESSION23_WINDOW_START}' "
        f"AND '{SESSION23_WINDOW_END}';",
    ) or 0
    calib = _scalarIntServer(
        addrs, creds, runner,
        f"SELECT COUNT(*) FROM calibration_sessions "
        f"WHERE session_start BETWEEN '{SESSION23_WINDOW_START}' "
        f"AND '{SESSION23_WINDOW_END}';",
    ) or 0
    return ai, calib


# ================================================================================
# Fixture hash guard
# ================================================================================

def verifyFixtureHash(projectRoot: Path) -> tuple[bool, str, int]:
    """Compute the current SHA-256 + byte size of the regression fixture."""
    path = projectRoot / FIXTURE_RELATIVE_PATH
    if not path.exists():
        return False, '', 0
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    matches = sha == FIXTURE_EXPECTED_SHA256 and len(data) == FIXTURE_EXPECTED_BYTES
    return matches, sha, len(data)


# ================================================================================
# Pi service control (automatic stop/start around DELETEs)
# ================================================================================

def piServiceIsActive(
    addrs: HostAddresses, runner: CommandRunner,
) -> bool:
    res = _sshPi(addrs, 'systemctl is-active eclipse-obd.service', runner)
    return res.stdout.strip() == 'active'


def stopPiService(
    addrs: HostAddresses, runner: CommandRunner,
) -> None:
    res = _sshPi(
        addrs, 'sudo systemctl stop eclipse-obd.service', runner,
    )
    if res.returncode != 0:
        # sudo may require a password; report cleanly.
        raise TruncateError(
            'could not stop eclipse-obd.service on Pi '
            f'(rc={res.returncode}): {res.stderr.strip()}',
        )


def startPiService(
    addrs: HostAddresses, runner: CommandRunner,
) -> None:
    _sshPi(addrs, 'sudo systemctl start eclipse-obd.service', runner)


# ================================================================================
# Backups (Pi SQLite + server mysqldump)
# ================================================================================

def backupPi(
    addrs: HostAddresses, runner: CommandRunner, timestampTag: str,
) -> str:
    srcDb = f'{addrs.piPath}/data/obd.db'
    dstDb = f'{addrs.piPath}/data/obd.db.bak-truncate-{timestampTag}'
    cmd = f'sqlite3 {shlex.quote(srcDb)} ".backup {shlex.quote(dstDb)}"'
    res = _sshPi(addrs, cmd, runner)
    if res.returncode != 0:
        raise SafetyGateError(
            f'Pi backup failed: {res.stderr.strip() or res.stdout.strip()}',
        )
    return dstDb


def backupServer(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    timestampTag: str,
) -> str:
    dumpPath = f'/tmp/obd2-truncate-backup-{timestampTag}.sql'
    envPrefix = f'MYSQL_PWD={shlex.quote(creds.dbPassword)}'
    tableList = ' '.join(SERVER_TABLES + ('ai_recommendations', 'calibration_sessions'))
    cmd = (
        f'{envPrefix} mysqldump --single-transaction '
        f'-u {shlex.quote(creds.dbUser)} '
        f'{shlex.quote(creds.dbName)} {tableList} '
        f'> {shlex.quote(dumpPath)}'
    )
    res = _sshServer(addrs, cmd, runner)
    if res.returncode != 0:
        raise SafetyGateError(
            f'Server backup failed: {res.stderr.strip() or res.stdout.strip()}',
        )
    return dumpPath


# ================================================================================
# DELETE executors (transactional)
# ================================================================================

def executePiTruncate(
    addrs: HostAddresses,
    runner: CommandRunner,
    tables: Iterable[TableState],
) -> None:
    statements = ['BEGIN IMMEDIATE;']
    for ts in tables:
        if ts.hasDataSourceColumn:
            statements.append(
                f"DELETE FROM {ts.name} WHERE data_source='real';",
            )
    statements.append(
        'UPDATE drive_counter SET last_drive_id=0 WHERE id=1;',
    )
    statements.append('COMMIT;')
    sql = '\n'.join(statements)
    res = _runPiSql(addrs, sql, runner)
    if res.returncode != 0:
        raise TruncateError(
            f'Pi DELETE failed: {res.stderr.strip() or res.stdout.strip()}',
        )


def executeServerTruncate(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    tables: Iterable[TableState],
) -> None:
    statements = ['START TRANSACTION;']
    for ts in tables:
        if ts.hasDataSourceColumn:
            statements.append(
                f"DELETE FROM {ts.name} WHERE data_source='real';",
            )
    # drive_counter reset only if the table exists on server.
    statements.append(
        "UPDATE drive_counter SET last_drive_id=0 WHERE id=1;",
    )
    statements.append('COMMIT;')
    sql = '\n'.join(statements)
    res = _runServerSql(addrs, creds, sql, runner)
    if res.returncode != 0:
        raise TruncateError(
            'Server DELETE failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )


# ================================================================================
# Divergence detection
# ================================================================================

def divergenceDetected(report: StateReport) -> list[str]:
    """Return a list of reasons why --execute should be refused.

    Empty list means the schema + state match spec expectations closely
    enough that --execute is safe.  Any non-empty return blocks --execute
    per stopCondition #4.
    """
    reasons: list[str] = []
    for ts in report.piTables:
        if ts.name == 'alert_log':
            # alert_log is intentionally excluded from data_source per
            # CAPTURE_TABLES in data_source.py.  Record for the report
            # but do NOT list as divergence.
            continue
        if not ts.hasDataSourceColumn:
            reasons.append(
                f'Pi {ts.name} missing data_source column '
                '(US-195 migration did not apply)',
            )
    for ts in report.serverTables:
        if not ts.hasDataSourceColumn and ts.name != 'alert_log':
            # alert_log intentionally omits data_source per Pi CAPTURE_TABLES
            # carve-out (data_source.py) -- server mirror honors the same shape
            # (US-209 kept alert_log data_source-less).  Spool amendment 2
            # confirms: bare DELETE / timestamp filter on alert_log, not
            # data_source.  Carve-out mirrors the Pi loop above.
            reasons.append(
                f'Server {ts.name} missing data_source column '
                '(US-195 never ran on live MariaDB)',
            )
        if ts.name in {'realtime_data', 'connection_log', 'statistics', 'alert_log'} \
                and not ts.hasDriveIdColumn:
            reasons.append(
                f'Server {ts.name} missing drive_id column '
                '(US-200 never ran on live MariaDB)',
            )
    if not report.serverHasDriveCounter:
        reasons.append(
            'Server missing drive_counter table '
            '(US-200 migration was Pi-only)',
        )
    if not report.fixtureShaMatches:
        reasons.append(
            f'Regression fixture SHA-256 mismatch '
            f'(got {report.fixtureSha[:16]}..., '
            f'expected {FIXTURE_EXPECTED_SHA256[:16]}...)',
        )
    return reasons


# ================================================================================
# Report rendering
# ================================================================================

def renderReport(report: StateReport) -> str:
    lines: list[str] = []
    lines.append('=' * 76)
    lines.append('US-205 truncate_session23 dry-run state report')
    lines.append('=' * 76)
    lines.append('')
    lines.append('Pi tables (chi-eclipse-01:~/Projects/Eclipse-01/data/obd.db):')  # b044-exempt: operator-facing display label, not a functional address
    for ts in report.piTables:
        dsNote = (
            f"real={ts.dataSourceRows}"
            if ts.hasDataSourceColumn
            else 'data_source column ABSENT'
        )
        rangeNote = (
            f" [{ts.earliestTs} .. {ts.latestTs}]"
            if ts.earliestTs and ts.latestTs
            else ''
        )
        lines.append(
            f"  {ts.name:15s} total={ts.rows:>8} {dsNote}{rangeNote}",
        )
    lines.append(
        f'  drive_counter.last_drive_id = {report.piDriveCounterLast}',
    )
    lines.append('')
    lines.append('Server tables (chi-srv-01 MariaDB obd2db):')  # b044-exempt: operator-facing display label, not a functional address
    for ts in report.serverTables:
        dsNote = (
            f"real={ts.dataSourceRows}"
            if ts.hasDataSourceColumn
            else 'data_source column ABSENT'
        )
        didNote = (
            ' drive_id=present' if ts.hasDriveIdColumn else ' drive_id=ABSENT'
        )
        lines.append(
            f"  {ts.name:15s} total={ts.rows:>8} {dsNote}{didNote}",
        )
    lines.append(
        f'  drive_counter present={report.serverHasDriveCounter} '
        f'last_drive_id={report.serverDriveCounterLast}',
    )
    lines.append('')
    lines.append('Orphan scan (Session 23 window on server):')
    lines.append(
        f'  ai_recommendations: {report.aiRecsWindowCount} rows',
    )
    lines.append(
        f'  calibration_sessions: {report.calibSessionsWindowCount} rows',
    )
    lines.append('')
    lines.append('Regression fixture (read-only; DELETE must not touch):')
    lines.append(
        f'  path: {FIXTURE_RELATIVE_PATH}',
    )
    lines.append(
        f'  bytes={report.fixtureBytes} sha256={report.fixtureSha[:16]}...',
    )
    lines.append(
        f'  matches-expected={report.fixtureShaMatches}',
    )
    lines.append('')
    if report.divergenceReasons:
        lines.append('DIVERGENCE DETECTED -- --execute will be refused:')
        for reason in report.divergenceReasons:
            lines.append(f'  * {reason}')
    else:
        lines.append('Schema + state match spec expectations. --execute safe.')
    lines.append('=' * 76)
    return '\n'.join(lines)


# ================================================================================
# Orchestration + CLI
# ================================================================================

def _timestampTag() -> str:
    return _dt.datetime.now(_dt.UTC).strftime('%Y%m%d-%H%M%SZ')


def _buildReport(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    projectRoot: Path,
) -> StateReport:
    piTables, piCounter = scanPiState(addrs, runner)
    serverTables, hasCounter, serverCounter = scanServerState(
        addrs, creds, runner,
    )
    aiWindow, calibWindow = scanOrphans(addrs, creds, runner)
    shaMatches, sha, nbytes = verifyFixtureHash(projectRoot)
    report = StateReport(
        piTables=piTables,
        serverTables=serverTables,
        piDriveCounterLast=piCounter,
        serverHasDriveCounter=hasCounter,
        serverDriveCounterLast=serverCounter,
        fixtureShaMatches=shaMatches,
        fixtureSha=sha,
        fixtureBytes=nbytes,
        aiRecsWindowCount=aiWindow,
        calibSessionsWindowCount=calibWindow,
    )
    report.divergenceReasons = divergenceDetected(report)
    return report


def _writeSentinel(projectRoot: Path, report: StateReport) -> Path:
    sentinel = projectRoot / DRY_RUN_SENTINEL_NAME
    payload = {
        'writtenAt': _dt.datetime.now(_dt.UTC).isoformat(),
        'piDriveCounterLast': report.piDriveCounterLast,
        'fixtureSha': report.fixtureSha,
        'divergenceReasons': report.divergenceReasons,
    }
    sentinel.write_text(
        '\n'.join(f'{k}={v}' for k, v in payload.items()) + '\n',
        encoding='utf-8',
    )
    return sentinel


def _readSentinel(projectRoot: Path) -> dict[str, str] | None:
    sentinel = projectRoot / DRY_RUN_SENTINEL_NAME
    if not sentinel.exists():
        return None
    out: dict[str, str] = {}
    for line in sentinel.read_text(encoding='utf-8').splitlines():
        if '=' in line:
            k, _, v = line.partition('=')
            out[k] = v
    return out


def _runExecute(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    projectRoot: Path,
    report: StateReport,
) -> int:
    tag = _timestampTag()
    # Stop Pi service so SQLite gives us a write lock.  Capture the
    # prior state so the finally block restores -- not force-starts --
    # the service.  Otherwise a fresh-truncate run immediately
    # repopulates with benchtest rows (Spool amendment 3 hygiene bug).
    priorServiceActive = piServiceIsActive(addrs, runner)
    if priorServiceActive:
        stopPiService(addrs, runner)
    try:
        piBackup = backupPi(addrs, runner, tag)
        serverBackup = backupServer(addrs, creds, runner, tag)
        print(f'[backup] Pi -> {piBackup}')
        print(f'[backup] Server -> {serverBackup}')
        executePiTruncate(addrs, runner, report.piTables)
        executeServerTruncate(addrs, creds, runner, report.serverTables)
        # Post-execute hash check.
        post, postSha, _ = verifyFixtureHash(projectRoot)
        if not post:
            raise TruncateError(
                f'POST-EXECUTE fixture hash diverged: {postSha}',
            )
        # Remove sentinel on success so the next run must dry-run again.
        (projectRoot / DRY_RUN_SENTINEL_NAME).unlink(missing_ok=True)
    finally:
        if priorServiceActive:
            startPiService(addrs, runner)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='truncate_session23.py',
        description=(
            'US-205 Session 23 operational truncate + drive_counter reset'
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        '--dry-run', action='store_true',
        help='Scan state + orphans + fixture hash; no mutations',
    )
    mode.add_argument(
        '--execute', action='store_true',
        help='Back up + DELETE + reset counter (requires prior --dry-run)',
    )
    parser.add_argument(
        '--project-root', type=Path,
        default=Path(__file__).resolve().parents[1],
        help='Project root (defaults to the repo root)',
    )
    parser.add_argument(
        '--addresses', type=Path, default=None,
        help='Override path to deploy/addresses.sh',
    )
    args = parser.parse_args(argv)

    projectRoot: Path = args.project_root.resolve()
    addressesPath = args.addresses or (projectRoot / 'deploy' / 'addresses.sh')

    try:
        addrs = loadAddresses(addressesPath)
        creds = loadServerCreds(addrs)
        report = _buildReport(addrs, creds, _defaultRunner, projectRoot)
    except TruncateError as err:
        print(f'ERROR: {err}', file=sys.stderr)
        return 2

    print(renderReport(report))

    if args.dry_run:
        _writeSentinel(projectRoot, report)
        print(
            f'\n[dry-run] sentinel written: {projectRoot / DRY_RUN_SENTINEL_NAME}',
        )
        if report.divergenceReasons:
            print(
                '[dry-run] divergence detected -- '
                '--execute would refuse.  File an inbox note.',
            )
        return 0

    # --execute path
    sentinel = _readSentinel(projectRoot)
    if sentinel is None:
        print(
            'ERROR: --execute requires a prior successful --dry-run '
            f'(missing {DRY_RUN_SENTINEL_NAME})',
            file=sys.stderr,
        )
        return 2
    if report.divergenceReasons:
        print(
            'ERROR: refusing --execute -- divergence reasons:\n  '
            + '\n  '.join(report.divergenceReasons),
            file=sys.stderr,
        )
        return 3
    return _runExecute(addrs, creds, _defaultRunner, projectRoot, report)


if __name__ == '__main__':
    raise SystemExit(main())
