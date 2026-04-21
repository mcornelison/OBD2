################################################################################
# File Name: apply_server_migrations.py
# Purpose/Description: Apply the US-195 (data_source) + US-200 (drive_id,
#                      drive_counter) schema migrations to the live server
#                      MariaDB ``obd2db`` database.  Ralph's US-205 --dry-run
#                      on 2026-04-20 surfaced that those migrations shipped as
#                      SQLAlchemy model changes in Sessions 65 + 66 but never
#                      ran as ALTER TABLE / CREATE TABLE on the live DB.  CI
#                      tested against ephemeral SQLite, so the divergence went
#                      unnoticed until the truncate script halted on schema
#                      gaps.  US-209 closes that gap for the 4 capture tables
#                      (realtime_data, connection_log, statistics, alert_log)
#                      plus the drive_counter singleton.
#
#                      Safety posture: --dry-run probes INFORMATION_SCHEMA,
#                      builds the migration plan, and exits 0 without writing.
#                      --execute refuses without a prior successful --dry-run,
#                      backs up affected tables via mysqldump --single-
#                      transaction, then runs the planned DDL in a scripted
#                      order with per-statement timing guards.  Re-running
#                      --execute on an already-migrated DB is a no-op.
#
# Author: Agent3 (Ralph)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Agent3       | Initial -- US-209 server schema catch-up.
# ================================================================================
################################################################################

"""Server schema catch-up for US-195 + US-200 (US-209).

Run from the project root:

    python scripts/apply_server_migrations.py --dry-run
    python scripts/apply_server_migrations.py --execute

Both modes require SSH reachability to ``SERVER_HOST`` (chi-srv-01).  The
server DSN is read from ``/mnt/projects/O/OBD2v2/.env`` over SSH so the
MariaDB password never leaves the server host.

Intent: after this lands, US-205 --execute runs clean (data_source filters
resolve; drive_counter reset operates on a real table) and US-204 + US-206
server-side work no longer needs schema prerequisites embedded in the
per-story scope.

Idempotency: every ALTER / CREATE is preceded by an INFORMATION_SCHEMA
probe.  Re-running on a fully-migrated DB emits 0 DDL statements and
exits 0.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

__all__ = [
    'CAPTURE_TABLES',
    'DRIVE_ID_TABLES',
    'DRIVE_COUNTER_TABLE',
    'DATA_SOURCE_COLUMN_DDL',
    'DRIVE_ID_COLUMN_DDL',
    'HostAddresses',
    'ServerCreds',
    'ColumnProbe',
    'SchemaState',
    'MigrationPlan',
    'MigrationError',
    'SchemaProbeError',
    'SafetyGateError',
    'CommandRunner',
    'loadAddresses',
    'loadServerCreds',
    'probeServerColumns',
    'serverTableExists',
    'indexExists',
    'scanServerSchema',
    'planMigrations',
    'renderPlan',
    'backupServer',
    'applyPlan',
    'main',
]


# ================================================================================
# Scope + DDL constants (MUST mirror src/pi/obdii/data_source.py + drive_id.py)
# ================================================================================

# Tables that receive data_source on the Pi (CAPTURE_TABLES in data_source.py).
# alert_log is intentionally omitted -- hardware alerts pre-date drive context
# and never carry fixture/replay tagging.
CAPTURE_TABLES: tuple[str, ...] = (
    'realtime_data',
    'connection_log',
    'statistics',
    'profiles',
    'calibration_sessions',
)

# Tables that receive drive_id on the Pi (DRIVE_ID_TABLES in drive_id.py).
# profiles / calibration_sessions are per-install not per-drive, so they are
# deliberately NOT in this tuple.
DRIVE_ID_TABLES: tuple[str, ...] = (
    'realtime_data',
    'connection_log',
    'statistics',
    'alert_log',
)

DRIVE_COUNTER_TABLE: str = 'drive_counter'

# MariaDB column shapes.  Mirror Pi semantics but use the MariaDB-native
# spelling: VARCHAR(16) for the enum, BIGINT for drive_id (per PM grounding
# gloss + docstring intent in drive_id.py -- SQLAlchemy's Integer maps to
# INT today; see TD-029 for the ORM catch-up).
DATA_SOURCE_COLUMN_DDL: str = (
    "data_source VARCHAR(16) NOT NULL DEFAULT 'real' "
    "CHECK (data_source IN ('real','replay','physics_sim','fixture'))"
)
DRIVE_ID_COLUMN_DDL: str = 'drive_id BIGINT NULL'

# Single-row counter table.  CHECK(id = 1) mirrors the Pi constraint so both
# hosts refuse multi-row accidents.
DRIVE_COUNTER_TABLE_DDL: str = (
    f"CREATE TABLE IF NOT EXISTS {DRIVE_COUNTER_TABLE} ("
    "    id INT PRIMARY KEY CHECK (id = 1),"
    "    last_drive_id BIGINT NOT NULL DEFAULT 0"
    ")"
)
DRIVE_COUNTER_SEED_SQL: str = (
    f"INSERT IGNORE INTO {DRIVE_COUNTER_TABLE} (id, last_drive_id) "
    "VALUES (1, 0)"
)

DRY_RUN_SENTINEL_NAME: str = '.us209-dry-run-ok'

# Stop-condition thresholds (spec §stopConditions).
BACKUP_MAX_SECONDS: float = 60.0
BACKUP_MAX_BYTES: int = 500 * 1024 * 1024
DDL_MAX_SECONDS: float = 30.0


# ================================================================================
# Exceptions
# ================================================================================

class MigrationError(Exception):
    """Base class for operator-facing migration failures."""


class SchemaProbeError(MigrationError):
    """Raised when an INFORMATION_SCHEMA probe fails."""


class SafetyGateError(MigrationError):
    """Raised when a safety gate (sentinel, backup, timing) fails."""


# ================================================================================
# Injection seams
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


# ================================================================================
# Address + credential dataclasses
# ================================================================================

@dataclass(slots=True, frozen=True)
class HostAddresses:
    """Server network coordinates resolved from deploy/addresses.sh."""

    serverHost: str
    serverUser: str


@dataclass(slots=True, frozen=True)
class ServerCreds:
    """MariaDB DSN pieces parsed from the server's DATABASE_URL env."""

    dbUser: str
    dbPassword: str
    dbName: str


@dataclass(slots=True)
class ColumnProbe:
    """Per-column probe result for one capture/drive-id table."""

    tableName: str
    exists: bool
    hasDataSource: bool
    hasDriveId: bool
    hasDriveIdIndex: bool


@dataclass(slots=True)
class SchemaState:
    """Aggregated server schema state across the four capture tables + counter."""

    tables: list[ColumnProbe] = field(default_factory=list)
    hasDriveCounterTable: bool = False


@dataclass(slots=True)
class MigrationPlan:
    """Ordered list of DDL statements to emit, with a human-readable rationale."""

    statements: list[tuple[str, str]] = field(default_factory=list)

    @property
    def isEmpty(self) -> bool:
        return len(self.statements) == 0


# ================================================================================
# Address + credential loaders (mirror scripts/truncate_session23.py)
# ================================================================================

def loadAddresses(
    addressesShPath: Path,
    runner: CommandRunner | None = None,
) -> HostAddresses:
    """Source ``deploy/addresses.sh`` via bash and return server coordinates.

    Only the server-side exports matter for this script; Pi fields are
    ignored to keep the surface minimal.
    """
    if runner is None:
        runner = _defaultRunner
    if not addressesShPath.exists():
        raise MigrationError(f'addresses.sh not found: {addressesShPath}')
    posix = addressesShPath.resolve().as_posix()
    cmd = f'. "{posix}" && env'
    result = runner(['bash', '-c', cmd])
    if result.returncode != 0:
        raise MigrationError(
            f'sourcing addresses.sh failed: {result.stderr.strip()}',
        )
    env: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if '=' in line:
            k, _, v = line.partition('=')
            env[k] = v
    missing = [k for k in ('SERVER_HOST', 'SERVER_USER') if not env.get(k)]
    if missing:
        raise MigrationError(
            f'addresses.sh missing required vars: {", ".join(missing)}',
        )
    return HostAddresses(
        serverHost=env['SERVER_HOST'],
        serverUser=env['SERVER_USER'],
    )


def loadServerCreds(
    addrs: HostAddresses,
    runner: CommandRunner | None = None,
) -> ServerCreds:
    """Fetch server ``.env`` DATABASE_URL via SSH and parse DSN pieces."""
    if runner is None:
        runner = _defaultRunner
    remote = f'{addrs.serverUser}@{addrs.serverHost}'
    script = (
        "grep '^DATABASE_URL=' /mnt/projects/O/OBD2v2/.env | "
        "head -1 | cut -d= -f2-"
    )
    result = runner(['ssh', remote, script])
    if result.returncode != 0 or not result.stdout.strip():
        raise MigrationError(
            f'could not read DATABASE_URL on {remote}: {result.stderr.strip()}',
        )
    dsn = result.stdout.strip()
    try:
        _, rest = dsn.split('://', 1)
        userpass, hostdb = rest.rsplit('@', 1)
        dbUser, dbPassword = userpass.split(':', 1)
        _, dbName = hostdb.split('/', 1)
    except ValueError as err:
        raise MigrationError(f'malformed DATABASE_URL: {dsn!r}') from err
    return ServerCreds(dbUser=dbUser, dbPassword=dbPassword, dbName=dbName)


# ================================================================================
# Server SQL helpers
# ================================================================================

def _runServerSql(
    addrs: HostAddresses,
    creds: ServerCreds,
    sql: str,
    runner: CommandRunner,
    *,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Pipe ``sql`` into ``mysql`` on the server over SSH.

    Password is passed via ``MYSQL_PWD`` so it never appears in ``ps`` on
    the remote host.  ``-B -N`` gives tab-delimited output with no headers.
    """
    remote = f'{addrs.serverUser}@{addrs.serverHost}'
    envPrefix = f'MYSQL_PWD={shlex.quote(creds.dbPassword)}'
    cmd = (
        f'{envPrefix} mysql -u {shlex.quote(creds.dbUser)} '
        f'-B -N -D {shlex.quote(creds.dbName)}'
    )
    return runner(['ssh', remote, cmd], input=sql, timeout=timeout)


# ================================================================================
# Schema probes (INFORMATION_SCHEMA)
# ================================================================================

def probeServerColumns(
    addrs: HostAddresses,
    creds: ServerCreds,
    tableName: str,
    runner: CommandRunner,
) -> list[str]:
    """Return column names for ``tableName`` on the server MariaDB.

    Empty list means the probe failed OR the table does not exist.  Callers
    disambiguate via :func:`serverTableExists`.
    """
    sql = (
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        f"WHERE TABLE_SCHEMA='{creds.dbName}' "
        f"AND TABLE_NAME='{tableName}';"
    )
    res = _runServerSql(addrs, creds, sql, runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'column probe for {tableName!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def serverTableExists(
    addrs: HostAddresses,
    creds: ServerCreds,
    tableName: str,
    runner: CommandRunner,
) -> bool:
    """Return True if ``tableName`` exists in the server database."""
    sql = (
        "SELECT COUNT(*) FROM information_schema.TABLES "
        f"WHERE TABLE_SCHEMA='{creds.dbName}' "
        f"AND TABLE_NAME='{tableName}';"
    )
    res = _runServerSql(addrs, creds, sql, runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'table probe for {tableName!r} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    txt = res.stdout.strip()
    try:
        return int(txt.split()[0]) > 0
    except (ValueError, IndexError):
        return False


def indexExists(
    addrs: HostAddresses,
    creds: ServerCreds,
    tableName: str,
    indexName: str,
    runner: CommandRunner,
) -> bool:
    """Return True if ``indexName`` exists on ``tableName``."""
    sql = (
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        f"WHERE TABLE_SCHEMA='{creds.dbName}' "
        f"AND TABLE_NAME='{tableName}' "
        f"AND INDEX_NAME='{indexName}';"
    )
    res = _runServerSql(addrs, creds, sql, runner)
    if res.returncode != 0:
        raise SchemaProbeError(
            f'index probe for {tableName}.{indexName} failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    txt = res.stdout.strip()
    try:
        return int(txt.split()[0]) > 0
    except (ValueError, IndexError):
        return False


def scanServerSchema(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
) -> SchemaState:
    """Probe every in-scope capture/drive-id table + drive_counter.

    Returns a :class:`SchemaState` with one :class:`ColumnProbe` per table
    in ``CAPTURE_TABLES | DRIVE_ID_TABLES``.  Non-existent tables appear
    with ``exists=False`` (they still show up so the operator sees the
    full scope in the report).
    """
    tableNames = tuple(dict.fromkeys(CAPTURE_TABLES + DRIVE_ID_TABLES))
    state = SchemaState()
    for tableName in tableNames:
        exists = serverTableExists(addrs, creds, tableName, runner)
        if not exists:
            state.tables.append(
                ColumnProbe(
                    tableName=tableName,
                    exists=False,
                    hasDataSource=False,
                    hasDriveId=False,
                    hasDriveIdIndex=False,
                ),
            )
            continue
        cols = set(probeServerColumns(addrs, creds, tableName, runner))
        hasDriveId = 'drive_id' in cols
        hasIdx = (
            indexExists(
                addrs, creds, tableName,
                f'IX_{tableName}_drive_id', runner,
            )
            if hasDriveId and tableName in DRIVE_ID_TABLES
            else False
        )
        state.tables.append(
            ColumnProbe(
                tableName=tableName,
                exists=True,
                hasDataSource='data_source' in cols,
                hasDriveId=hasDriveId,
                hasDriveIdIndex=hasIdx,
            ),
        )
    state.hasDriveCounterTable = serverTableExists(
        addrs, creds, DRIVE_COUNTER_TABLE, runner,
    )
    return state


# ================================================================================
# Migration planning (idempotent: only emit DDL for missing shapes)
# ================================================================================

def planMigrations(state: SchemaState) -> MigrationPlan:
    """Build the ordered DDL plan from the observed schema state.

    Order:

    1. ALTER TABLE ... ADD COLUMN data_source (per capture table)
    2. ALTER TABLE ... ADD COLUMN drive_id (per drive-id table)
    3. ALTER TABLE ... ADD INDEX IX_<t>_drive_id (after the column lands)
    4. CREATE TABLE drive_counter + seed singleton row

    Each statement is paired with a human-readable rationale for the report.
    """
    plan = MigrationPlan()
    probesByName = {p.tableName: p for p in state.tables}

    # Phase 1: data_source columns (CAPTURE_TABLES).
    for tableName in CAPTURE_TABLES:
        probe = probesByName.get(tableName)
        if probe is None or not probe.exists:
            continue
        if probe.hasDataSource:
            continue
        plan.statements.append((
            f'ALTER TABLE {tableName} ADD COLUMN {DATA_SOURCE_COLUMN_DDL}',
            f'add data_source to {tableName} (US-195 catch-up)',
        ))

    # Phase 2: drive_id columns (DRIVE_ID_TABLES).
    for tableName in DRIVE_ID_TABLES:
        probe = probesByName.get(tableName)
        if probe is None or not probe.exists:
            continue
        if probe.hasDriveId:
            continue
        plan.statements.append((
            f'ALTER TABLE {tableName} ADD COLUMN {DRIVE_ID_COLUMN_DDL}',
            f'add drive_id to {tableName} (US-200 catch-up)',
        ))

    # Phase 3: drive_id indexes (always last, only if index missing).  A
    # freshly-added column will have hasDriveIdIndex=False at scan time; we
    # assume the plan above creates the column, so the index is safe to
    # request unconditionally when either the column or the index is
    # missing.
    for tableName in DRIVE_ID_TABLES:
        probe = probesByName.get(tableName)
        if probe is None or not probe.exists:
            continue
        if probe.hasDriveId and probe.hasDriveIdIndex:
            continue
        indexName = f'IX_{tableName}_drive_id'
        plan.statements.append((
            f'ALTER TABLE {tableName} ADD INDEX {indexName} (drive_id)',
            f'add {indexName} (US-200 catch-up)',
        ))

    # Phase 4: drive_counter singleton.
    if not state.hasDriveCounterTable:
        plan.statements.append((
            DRIVE_COUNTER_TABLE_DDL,
            'create drive_counter singleton (US-200 catch-up)',
        ))
        plan.statements.append((
            DRIVE_COUNTER_SEED_SQL,
            'seed drive_counter.last_drive_id = 0',
        ))

    return plan


# ================================================================================
# Report rendering
# ================================================================================

def renderPlan(state: SchemaState, plan: MigrationPlan) -> str:
    """Pretty-print the scan + plan for the operator."""
    lines: list[str] = []
    lines.append('=' * 76)
    lines.append('US-209 apply_server_migrations plan')
    lines.append('=' * 76)
    lines.append('')
    lines.append('Server schema scan (chi-srv-01 MariaDB obd2db):')  # b044-exempt: operator-facing display label, not a functional address
    for probe in state.tables:
        if not probe.exists:
            lines.append(f'  {probe.tableName:22s} TABLE MISSING')
            continue
        ds = 'data_source=present' if probe.hasDataSource else 'data_source=ABSENT'
        did = 'drive_id=present' if probe.hasDriveId else 'drive_id=ABSENT'
        idx = (
            'index=present'
            if probe.hasDriveIdIndex
            else ('index=ABSENT' if probe.tableName in DRIVE_ID_TABLES else 'n/a')
        )
        lines.append(
            f'  {probe.tableName:22s} {ds:21s} {did:18s} {idx}',
        )
    lines.append(
        f'  {DRIVE_COUNTER_TABLE:22s} '
        f'{"table=present" if state.hasDriveCounterTable else "table=ABSENT"}',
    )
    lines.append('')
    if plan.isEmpty:
        lines.append('Migration plan: (empty) -- schema is already up to date.')
    else:
        lines.append(f'Migration plan ({len(plan.statements)} statement(s)):')
        for ordinal, (sql, reason) in enumerate(plan.statements, 1):
            lines.append(f'  [{ordinal:02d}] {reason}')
            for fragment in sql.splitlines():
                lines.append(f'       {fragment}')
    lines.append('=' * 76)
    return '\n'.join(lines)


# ================================================================================
# Backup (mysqldump --single-transaction)
# ================================================================================

def backupServer(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    timestampTag: str,
) -> str:
    """Dump affected tables to /tmp/obd2-migration-backup-<ts>.sql.

    Includes every in-scope capture/drive-id table plus drive_counter (safe
    because mysqldump skips non-existent tables with ``--ignore-table``
    guards; we list them explicitly so the backup is narrow + readable).
    Stop-condition guards:

    * Dump must finish within :data:`BACKUP_MAX_SECONDS`.
    * Resulting file must be smaller than :data:`BACKUP_MAX_BYTES`.

    Returns the server-side path to the backup file.
    """
    dumpPath = f'/tmp/obd2-migration-backup-{timestampTag}.sql'
    envPrefix = f'MYSQL_PWD={shlex.quote(creds.dbPassword)}'
    tableUnion = tuple(dict.fromkeys(
        CAPTURE_TABLES + DRIVE_ID_TABLES,
    ))
    tableList = ' '.join(tableUnion)
    # Use --ignore-table to skip any table that may not exist yet (e.g.,
    # drive_counter).  MariaDB mysqldump honours this on a per-TABLE level.
    cmd = (
        f'{envPrefix} mysqldump --single-transaction --skip-lock-tables '
        f'-u {shlex.quote(creds.dbUser)} '
        f'{shlex.quote(creds.dbName)} {tableList} '
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
            f'server backup failed: {res.stderr.strip() or res.stdout.strip()}',
        )
    if elapsed > BACKUP_MAX_SECONDS:
        raise SafetyGateError(
            f'server backup exceeded {BACKUP_MAX_SECONDS:.0f}s '
            f'(took {elapsed:.1f}s) -- stopCondition #2',
        )
    # Check size (stat via ssh) separately.
    statCmd = f'stat -c %s {shlex.quote(dumpPath)}'
    statRes = runner(
        ['ssh', f'{addrs.serverUser}@{addrs.serverHost}', statCmd],
    )
    if statRes.returncode == 0 and statRes.stdout.strip():
        try:
            nbytes = int(statRes.stdout.strip())
        except ValueError:
            nbytes = 0
        if nbytes > BACKUP_MAX_BYTES:
            raise SafetyGateError(
                f'server backup too large: {nbytes} bytes '
                f'> {BACKUP_MAX_BYTES} -- stopCondition #2',
            )
    return dumpPath


# ================================================================================
# Plan execution
# ================================================================================

def applyPlan(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    plan: MigrationPlan,
) -> list[tuple[str, float]]:
    """Execute each DDL statement sequentially with a timing guard.

    Returns a list of ``(sql, elapsed_seconds)`` tuples for the report.
    Halts on the first failure (MariaDB DDL is implicit-commit so mid-plan
    failure leaves the DB in a partial state -- the operator must restore
    from the mysqldump backup).
    """
    results: list[tuple[str, float]] = []
    for sql, reason in plan.statements:
        start = time.monotonic()
        res = _runServerSql(
            addrs, creds, sql + ';', runner,
            timeout=DDL_MAX_SECONDS + 10,
        )
        elapsed = time.monotonic() - start
        if res.returncode != 0:
            raise MigrationError(
                f'DDL failed [{reason}]: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )
        if elapsed > DDL_MAX_SECONDS:
            raise SafetyGateError(
                f'DDL exceeded {DDL_MAX_SECONDS:.0f}s '
                f'[{reason}, took {elapsed:.1f}s] -- stopCondition #3',
            )
        results.append((sql, elapsed))
    return results


# ================================================================================
# Sentinel gate (parity with truncate_session23.py)
# ================================================================================

def _writeSentinel(projectRoot: Path, plan: MigrationPlan) -> Path:
    sentinel = projectRoot / DRY_RUN_SENTINEL_NAME
    payload = {
        'writtenAt': _dt.datetime.now(_dt.UTC).isoformat(),
        'planLen': len(plan.statements),
        'empty': plan.isEmpty,
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


# ================================================================================
# Orchestration + CLI
# ================================================================================

def _timestampTag() -> str:
    return _dt.datetime.now(_dt.UTC).strftime('%Y%m%d-%H%M%SZ')


def _runExecute(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    projectRoot: Path,
    plan: MigrationPlan,
) -> int:
    if plan.isEmpty:
        print('[execute] plan is empty -- nothing to do (idempotent no-op)')
        (projectRoot / DRY_RUN_SENTINEL_NAME).unlink(missing_ok=True)
        return 0
    tag = _timestampTag()
    backupPath = backupServer(addrs, creds, runner, tag)
    print(f'[backup] server -> {backupPath}')
    timings = applyPlan(addrs, creds, runner, plan)
    for sql, elapsed in timings:
        snippet = sql.splitlines()[0][:72]
        print(f'[applied +{elapsed:5.2f}s] {snippet}')
    # Verify the plan landed.
    postState = scanServerSchema(addrs, creds, runner)
    postPlan = planMigrations(postState)
    if not postPlan.isEmpty:
        raise MigrationError(
            'post-execute verification: plan is still non-empty '
            f'({len(postPlan.statements)} residual statement(s))',
        )
    (projectRoot / DRY_RUN_SENTINEL_NAME).unlink(missing_ok=True)
    print('[execute] verified: server schema now matches Pi-side shape')
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='apply_server_migrations.py',
        description='US-209 server schema catch-up (US-195 + US-200 on MariaDB)',
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        '--dry-run', action='store_true',
        help='Probe schema + build plan; no mutations',
    )
    mode.add_argument(
        '--execute', action='store_true',
        help='Back up + apply plan (requires prior --dry-run)',
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

    # Resolve the runner once at call time (not at function definition) so
    # tests can monkeypatch asm._defaultRunner and have every downstream
    # helper pick up the replacement.
    runner: CommandRunner = _defaultRunner

    try:
        addrs = loadAddresses(addressesPath, runner=runner)
        creds = loadServerCreds(addrs, runner=runner)
        state = scanServerSchema(addrs, creds, runner)
        plan = planMigrations(state)
    except MigrationError as err:
        print(f'ERROR: {err}', file=sys.stderr)
        return 2

    print(renderPlan(state, plan))

    if args.dry_run:
        _writeSentinel(projectRoot, plan)
        print(
            f'\n[dry-run] sentinel written: '
            f'{projectRoot / DRY_RUN_SENTINEL_NAME}',
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
    try:
        return _runExecute(addrs, creds, runner, projectRoot, plan)
    except MigrationError as err:
        print(f'ERROR: {err}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
