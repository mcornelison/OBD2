################################################################################
# File Name: truncate_drive_id_1_pollution.py
# Purpose/Description: Sprint-18 operational truncate of the 2.9M pre-US-212
#                      pollution rows tagged real on drive_id=1 from Pi
#                      data/obd.db + server obd2db MariaDB. Implements US-227
#                      per Spool consolidated note 2026-04-23 Section 2.
#
#                      Differs from US-205 in scope: deletes only
#                      drive_id=1 AND data_source='real' rows (NOT every real
#                      row). Drive 3's 6,089 rows + Drive 2 sim rows + NULL
#                      drive_id orphans (US-233 territory) are preserved by
#                      the WHERE clause itself; the script does not need to
#                      enumerate them.
#
#                      Sync gate: --execute refuses unless the Pi sync_log
#                      cursor for realtime_data is >= MIN_REALTIME_SYNC_CURSOR
#                      (Drive 3 max id). This prevents truncating local rows
#                      that haven't propagated to the server.
#
#                      drive_counter target: 3 (post-Drive-3 high-water).
#                      Idempotent: never regresses a counter that is already
#                      ahead of the target.
#
#                      Reuses subprocess/SSH/backup helpers from
#                      truncate_session23.py to avoid duplicating ~400 lines
#                      of plumbing. Operational policy lives here.
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-27    | Rex (US-227) | Initial -- Sprint 18 drive_id=1 pollution truncate
# ================================================================================
################################################################################

"""US-227 truncate of drive_id=1 / data_source='real' pollution rows.

Run from the project root::

    python scripts/truncate_drive_id_1_pollution.py --dry-run
    python scripts/truncate_drive_id_1_pollution.py --execute

Both modes require SSH reachability to ``PI_HOST`` and ``SERVER_HOST`` (resolved
via ``deploy/addresses.sh``). Use ``--local --db PATH`` to operate on a local
SQLite file only -- intended for tests and CI.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import sqlite3
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# ================================================================================
# Reuse SSH/backup/fixture helpers from US-205 (no duplication of plumbing)
# ================================================================================

_THIS_DIR = Path(__file__).resolve().parent


def _loadSibling(name: str):  # noqa: ANN202 -- module loader helper
    spec = importlib.util.spec_from_file_location(
        name, _THIS_DIR / f'{name}.py',
    )
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot locate sibling script: {name}')
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


_us205 = _loadSibling('truncate_session23')

# Re-exports for convenience.
HostAddresses = _us205.HostAddresses
ServerCreds = _us205.ServerCreds
CommandRunner = _us205.CommandRunner
TruncateError = _us205.TruncateError
SafetyGateError = _us205.SafetyGateError
loadAddresses = _us205.loadAddresses
loadServerCreds = _us205.loadServerCreds
verifyFixtureHash = _us205.verifyFixtureHash
piServiceIsActive = _us205.piServiceIsActive
stopPiService = _us205.stopPiService
startPiService = _us205.startPiService
backupPi = _us205.backupPi
backupServer = _us205.backupServer
_defaultRunner = _us205._defaultRunner
_runPiSql = _us205._runPiSql
_runServerSql = _us205._runServerSql
_scalarIntPi = _us205._scalarIntPi
_scalarIntServer = _us205._scalarIntServer
_sshPi = _us205._sshPi
_sshServer = _us205._sshServer
_parseColumnsSqlite = _us205._parseColumnsSqlite
FIXTURE_RELATIVE_PATH = _us205.FIXTURE_RELATIVE_PATH
FIXTURE_EXPECTED_SHA256 = _us205.FIXTURE_EXPECTED_SHA256
FIXTURE_EXPECTED_BYTES = _us205.FIXTURE_EXPECTED_BYTES


__all__ = [
    'DRIVE_ID_TARGET',
    'DRIVE_COUNTER_TARGET',
    'DATA_SOURCE_TARGET',
    'MIN_REALTIME_SYNC_CURSOR',
    'POLLUTION_WINDOW_START',
    'POLLUTION_WINDOW_END',
    'DRY_RUN_SENTINEL_NAME',
    'TableTarget',
    'StateReport',
    'enumerateTargetTables',
    'readRealtimeSyncCursor',
    'scanOrphans',
    'divergenceDetected',
    'executeLocalTruncate',
    'renderReport',
    'main',
]


# ================================================================================
# Policy constants (Sprint 18 targets)
# ================================================================================

# Story scope: DELETE WHERE drive_id=1 AND data_source='real'.
DRIVE_ID_TARGET: int = 1
DATA_SOURCE_TARGET: str = 'real'

# drive_counter target = post-Drive-3 high-water. Idempotent: never regress.
DRIVE_COUNTER_TARGET: int = 3

# Pre-flight gate: sync_log.realtime_data.last_synced_id must be >= the
# largest Drive 3 row id (3,439,960) so we know Drive 3 landed on the server
# before we delete anything locally. Pinned from the 2026-04-27 pre-flight.
MIN_REALTIME_SYNC_CURSOR: int = 3_439_960

# Spool consolidated note Section 1: pollution rows span this window.
# Used as the orphan-scan window on ai_recommendations + calibration_sessions.
POLLUTION_WINDOW_START: str = '2026-04-21 02:27'
POLLUTION_WINDOW_END: str = '2026-04-23 03:12'

# Sentinel filename -- distinct from US-205's '.us205-dry-run-ok'.
DRY_RUN_SENTINEL_NAME: str = '.us227-dry-run-ok'

# Tables that are excluded from the truncate even if they have both
# (drive_id, data_source) columns. drive_summary is per-drive metadata
# (one row per drive) -- per US-227 doNotTouch.
_EXCLUDED_TABLES: frozenset[str] = frozenset({'drive_summary'})


# ================================================================================
# Data classes
# ================================================================================


@dataclass(slots=True)
class TableTarget:
    """A table eligible for the drive_id=1 / real DELETE."""

    name: str
    drive1RealRows: int
    hasDataSourceColumn: bool
    hasDriveIdColumn: bool


@dataclass(slots=True)
class StateReport:
    """Consolidated dry-run report across Pi + server."""

    piTargets: list[TableTarget] = field(default_factory=list)
    serverTargets: list[TableTarget] = field(default_factory=list)
    piRealtimeSyncCursor: int | None = None
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
# Local SQLite helpers (used for --local mode + tests)
# ================================================================================


def _localTablesWithBothColumns(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name",
    ).fetchall()
    out: list[str] = []
    for (name,) in rows:
        if name in _EXCLUDED_TABLES:
            continue
        cols = {row[1] for row in conn.execute(f'PRAGMA table_info({name})')}
        if 'drive_id' in cols and 'data_source' in cols:
            out.append(name)
    return out


def _localCount(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row else 0


def enumerateTargetTables(dbPath: Path) -> list[TableTarget]:
    """Local-DB table enumeration: tables with both drive_id + data_source.

    For each candidate, count drive_id=1 / data_source='real' rows so the
    operator's report shows the deletion impact per table.
    """
    if not dbPath.exists():
        return []
    conn = sqlite3.connect(dbPath)
    try:
        names = _localTablesWithBothColumns(conn)
        targets: list[TableTarget] = []
        for name in names:
            n = _localCount(
                conn,
                f"SELECT COUNT(*) FROM {name} "
                f"WHERE drive_id={DRIVE_ID_TARGET} "
                f"AND data_source='{DATA_SOURCE_TARGET}'",
            )
            targets.append(
                TableTarget(
                    name=name,
                    drive1RealRows=n,
                    hasDataSourceColumn=True,
                    hasDriveIdColumn=True,
                ),
            )
        return targets
    finally:
        conn.close()


def readRealtimeSyncCursor(dbPath: Path) -> int | None:
    """Return sync_log.last_synced_id for table_name='realtime_data'."""
    if not dbPath.exists():
        return None
    conn = sqlite3.connect(dbPath)
    try:
        row = conn.execute(
            "SELECT last_synced_id FROM sync_log "
            "WHERE table_name='realtime_data'",
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return int(row[0])


def _readDriveCounter(dbPath: Path) -> int | None:
    if not dbPath.exists():
        return None
    conn = sqlite3.connect(dbPath)
    try:
        row = conn.execute(
            'SELECT last_drive_id FROM drive_counter WHERE id=1',
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return int(row[0])


def executeLocalTruncate(
    dbPath: Path,
    targets: Iterable[TableTarget],
    *,
    driveCounterTarget: int = DRIVE_COUNTER_TARGET,
) -> None:
    """Run the DELETE + counter-advance against a local SQLite DB.

    Wraps every DELETE plus the counter UPDATE in a single transaction so
    a mid-run failure rolls back. Used by --local mode and the test suite;
    the live Pi path goes through SSH -> sqlite3 in :func:`_runExecute`.
    """
    conn = sqlite3.connect(dbPath)
    try:
        conn.execute('BEGIN IMMEDIATE')
        for t in targets:
            if not (t.hasDriveIdColumn and t.hasDataSourceColumn):
                continue
            conn.execute(
                f"DELETE FROM {t.name} "
                f"WHERE drive_id={DRIVE_ID_TARGET} "
                f"AND data_source='{DATA_SOURCE_TARGET}'",
            )
        # Idempotent counter advance: never regress.
        conn.execute(
            'UPDATE drive_counter SET last_drive_id = ? '
            'WHERE id=1 AND last_drive_id < ?',
            (driveCounterTarget, driveCounterTarget),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ================================================================================
# Remote (SSH-based) probes -- thin wrappers over US-205's helpers
# ================================================================================


def _enumerateRemoteTablesPi(
    addrs: HostAddresses, runner: CommandRunner,
) -> list[TableTarget]:
    """Enumerate Pi tables with both columns via SSH."""
    res = _runPiSql(
        addrs,
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name;",
        runner,
    )
    if res.returncode != 0:
        return []
    targets: list[TableTarget] = []
    for line in res.stdout.splitlines():
        name = line.strip()
        if not name or name in _EXCLUDED_TABLES:
            continue
        colRes = _runPiSql(addrs, f'PRAGMA table_info({name});', runner)
        cols = set(_parseColumnsSqlite(colRes.stdout)) if colRes.returncode == 0 else set()
        hasDs = 'data_source' in cols
        hasDid = 'drive_id' in cols
        if not (hasDs and hasDid):
            continue
        n = _scalarIntPi(
            addrs, runner,
            f"SELECT COUNT(*) FROM {name} "
            f"WHERE drive_id={DRIVE_ID_TARGET} "
            f"AND data_source='{DATA_SOURCE_TARGET}';",
        ) or 0
        targets.append(
            TableTarget(
                name=name, drive1RealRows=n,
                hasDataSourceColumn=True, hasDriveIdColumn=True,
            ),
        )
    return targets


def _enumerateRemoteTablesServer(
    addrs: HostAddresses, creds: ServerCreds, runner: CommandRunner,
) -> list[TableTarget]:
    """Enumerate server tables with both columns via SSH/MySQL."""
    sql = (
        "SELECT TABLE_NAME FROM information_schema.TABLES "
        f"WHERE TABLE_SCHEMA='{creds.dbName}' AND TABLE_TYPE='BASE TABLE';"
    )
    res = _runServerSql(addrs, creds, sql, runner)
    if res.returncode != 0:
        return []
    targets: list[TableTarget] = []
    for line in res.stdout.splitlines():
        name = line.strip()
        if not name or name in _EXCLUDED_TABLES:
            continue
        colSql = (
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            f"WHERE TABLE_SCHEMA='{creds.dbName}' AND TABLE_NAME='{name}';"
        )
        colRes = _runServerSql(addrs, creds, colSql, runner)
        cols = {ln.strip() for ln in colRes.stdout.splitlines() if ln.strip()}
        if not ({'drive_id', 'data_source'} <= cols):
            continue
        n = _scalarIntServer(
            addrs, creds, runner,
            f"SELECT COUNT(*) FROM {name} "
            f"WHERE drive_id={DRIVE_ID_TARGET} "
            f"AND data_source='{DATA_SOURCE_TARGET}';",
        ) or 0
        targets.append(
            TableTarget(
                name=name, drive1RealRows=n,
                hasDataSourceColumn=True, hasDriveIdColumn=True,
            ),
        )
    return targets


def _readRemoteRealtimeSyncCursor(
    addrs: HostAddresses, runner: CommandRunner,
) -> int | None:
    return _scalarIntPi(
        addrs, runner,
        "SELECT last_synced_id FROM sync_log "
        "WHERE table_name='realtime_data';",
    )


def _readRemoteDriveCounterPi(
    addrs: HostAddresses, runner: CommandRunner,
) -> int | None:
    return _scalarIntPi(
        addrs, runner,
        'SELECT last_drive_id FROM drive_counter WHERE id=1;',
    )


def _readRemoteDriveCounterServer(
    addrs: HostAddresses, creds: ServerCreds, runner: CommandRunner,
) -> tuple[bool, int | None]:
    presence = _runServerSql(
        addrs, creds, "SHOW TABLES LIKE 'drive_counter';", runner,
    )
    has = presence.returncode == 0 and bool(presence.stdout.strip())
    if not has:
        return False, None
    return True, _scalarIntServer(
        addrs, creds, runner,
        'SELECT last_drive_id FROM drive_counter WHERE id=1;',
    )


# ================================================================================
# Orphan scan (server only -- ai_recs + calib_sessions don't exist on Pi)
# ================================================================================


def scanOrphans(
    addrs: HostAddresses, creds: ServerCreds, runner: CommandRunner,
) -> tuple[int, int]:
    """Count ai_recommendations + calibration_sessions in the pollution window."""
    ai = _scalarIntServer(
        addrs, creds, runner,
        f"SELECT COUNT(*) FROM ai_recommendations "
        f"WHERE created_at BETWEEN '{POLLUTION_WINDOW_START}' "
        f"AND '{POLLUTION_WINDOW_END}';",
    ) or 0
    calib = _scalarIntServer(
        addrs, creds, runner,
        f"SELECT COUNT(*) FROM calibration_sessions "
        f"WHERE start_time BETWEEN '{POLLUTION_WINDOW_START}' "
        f"AND '{POLLUTION_WINDOW_END}';",
    ) or 0
    return ai, calib


# ================================================================================
# Divergence detection
# ================================================================================


def divergenceDetected(report: StateReport) -> list[str]:
    """Reasons --execute should be refused. Empty list = safe to run."""
    reasons: list[str] = []
    if report.piRealtimeSyncCursor is None:
        reasons.append(
            'sync_log.realtime_data cursor missing -- cannot prove Drive 3 '
            'landed on the server. Refusing --execute.',
        )
    elif report.piRealtimeSyncCursor < MIN_REALTIME_SYNC_CURSOR:
        reasons.append(
            'sync_log.realtime_data cursor '
            f'{report.piRealtimeSyncCursor} < required '
            f'{MIN_REALTIME_SYNC_CURSOR} (Drive 3 max id). '
            'Drive 3 has not propagated to the server; refusing --execute.',
        )
    if not report.fixtureShaMatches:
        reasons.append(
            f'Regression fixture SHA-256 mismatch '
            f'(got {report.fixtureSha[:16]}..., '
            f'expected {FIXTURE_EXPECTED_SHA256[:16]}...). Refusing --execute.',
        )
    if (
        report.piDriveCounterLast is not None
        and report.piDriveCounterLast < DRIVE_COUNTER_TARGET
    ):
        reasons.append(
            'Pi drive_counter.last_drive_id '
            f'{report.piDriveCounterLast} < target {DRIVE_COUNTER_TARGET} '
            '-- counter regressed; Drive 3 metadata may be inconsistent. '
            'Surface to Marcus before --execute.',
        )
    if report.aiRecsWindowCount > 0:
        reasons.append(
            f'Orphan scan found {report.aiRecsWindowCount} '
            'ai_recommendations row(s) in the pollution window. '
            'Surface to Marcus + Spool before --execute (stopCondition #2).',
        )
    if report.calibSessionsWindowCount > 0:
        reasons.append(
            f'Orphan scan found {report.calibSessionsWindowCount} '
            'calibration_sessions row(s) in the pollution window. '
            'Surface to Marcus + Spool before --execute (stopCondition #2).',
        )
    return reasons


# ================================================================================
# Report rendering
# ================================================================================


def renderReport(report: StateReport) -> str:
    lines: list[str] = []
    lines.append('=' * 76)
    lines.append('US-227 truncate_drive_id_1_pollution dry-run state report')
    lines.append('=' * 76)
    lines.append('')
    lines.append(f'Target: drive_id={DRIVE_ID_TARGET} '
                 f"AND data_source='{DATA_SOURCE_TARGET}'")
    lines.append(f'drive_counter target: last_drive_id >= {DRIVE_COUNTER_TARGET} '
                 '(idempotent; never regress)')
    lines.append(
        f'Sync gate: sync_log.realtime_data.last_synced_id >= '
        f'{MIN_REALTIME_SYNC_CURSOR}',
    )
    lines.append('')
    lines.append('Pi targets:')
    if not report.piTargets:
        lines.append('  (none discovered)')
    for t in report.piTargets:
        lines.append(
            f"  {t.name:20s} drive_id=1/real rows={t.drive1RealRows}",
        )
    lines.append(
        f'  drive_counter.last_drive_id = {report.piDriveCounterLast}',
    )
    lines.append(
        f'  sync_log.realtime_data cursor = {report.piRealtimeSyncCursor}',
    )
    lines.append('')
    lines.append('Server targets:')
    if not report.serverTargets:
        lines.append('  (none discovered)')
    for t in report.serverTargets:
        lines.append(
            f"  {t.name:20s} drive_id=1/real rows={t.drive1RealRows}",
        )
    lines.append(
        f'  drive_counter present={report.serverHasDriveCounter} '
        f'last_drive_id={report.serverDriveCounterLast}',
    )
    lines.append('')
    lines.append('Orphan scan (pollution window on server):')
    lines.append(
        f'  ai_recommendations: {report.aiRecsWindowCount} rows '
        f'(window {POLLUTION_WINDOW_START} .. {POLLUTION_WINDOW_END})',
    )
    lines.append(
        f'  calibration_sessions: {report.calibSessionsWindowCount} rows',
    )
    lines.append('')
    lines.append('Regression fixture:')
    lines.append(f'  path: {FIXTURE_RELATIVE_PATH}')
    lines.append(
        f'  bytes={report.fixtureBytes} sha256={report.fixtureSha[:16]}... '
        f'matches-expected={report.fixtureShaMatches}',
    )
    lines.append('')
    if report.divergenceReasons:
        lines.append('DIVERGENCE DETECTED -- --execute will be refused:')
        for reason in report.divergenceReasons:
            lines.append(f'  * {reason}')
    else:
        lines.append('Schema + state match expectations. --execute safe.')
    lines.append('=' * 76)
    return '\n'.join(lines)


# ================================================================================
# Orchestration
# ================================================================================


def _timestampTag() -> str:
    return _dt.datetime.now(_dt.UTC).strftime('%Y%m%d-%H%M%SZ')


def _writeSentinel(sentinelDir: Path, report: StateReport) -> Path:
    sentinel = sentinelDir / DRY_RUN_SENTINEL_NAME
    payload = {
        'writtenAt': _dt.datetime.now(_dt.UTC).isoformat(),
        'piRealtimeSyncCursor': report.piRealtimeSyncCursor,
        'piDriveCounterLast': report.piDriveCounterLast,
        'fixtureSha': report.fixtureSha,
        'divergenceReasons': len(report.divergenceReasons),
    }
    sentinel.write_text(
        '\n'.join(f'{k}={v}' for k, v in payload.items()) + '\n',
        encoding='utf-8',
    )
    return sentinel


def _readSentinel(sentinelDir: Path) -> dict[str, str] | None:
    sentinel = sentinelDir / DRY_RUN_SENTINEL_NAME
    if not sentinel.exists():
        return None
    out: dict[str, str] = {}
    for line in sentinel.read_text(encoding='utf-8').splitlines():
        if '=' in line:
            k, _, v = line.partition('=')
            out[k] = v
    return out


def _buildLocalReport(dbPath: Path, projectRoot: Path) -> StateReport:
    targets = enumerateTargetTables(dbPath)
    cursor = readRealtimeSyncCursor(dbPath)
    counter = _readDriveCounter(dbPath)
    matches, sha, nbytes = verifyFixtureHash(projectRoot)
    report = StateReport(
        piTargets=targets,
        serverTargets=[],  # local mode: server not probed
        piRealtimeSyncCursor=cursor,
        piDriveCounterLast=counter,
        serverHasDriveCounter=False,
        serverDriveCounterLast=None,
        fixtureShaMatches=matches,
        fixtureSha=sha,
        fixtureBytes=nbytes,
        aiRecsWindowCount=0,
        calibSessionsWindowCount=0,
    )
    report.divergenceReasons = divergenceDetected(report)
    return report


def _buildRemoteReport(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    projectRoot: Path,
) -> StateReport:
    piTargets = _enumerateRemoteTablesPi(addrs, runner)
    serverTargets = _enumerateRemoteTablesServer(addrs, creds, runner)
    piCursor = _readRemoteRealtimeSyncCursor(addrs, runner)
    piCounter = _readRemoteDriveCounterPi(addrs, runner)
    hasCounter, serverCounter = _readRemoteDriveCounterServer(
        addrs, creds, runner,
    )
    aiCount, calibCount = scanOrphans(addrs, creds, runner)
    matches, sha, nbytes = verifyFixtureHash(projectRoot)
    report = StateReport(
        piTargets=piTargets,
        serverTargets=serverTargets,
        piRealtimeSyncCursor=piCursor,
        piDriveCounterLast=piCounter,
        serverHasDriveCounter=hasCounter,
        serverDriveCounterLast=serverCounter,
        fixtureShaMatches=matches,
        fixtureSha=sha,
        fixtureBytes=nbytes,
        aiRecsWindowCount=aiCount,
        calibSessionsWindowCount=calibCount,
    )
    report.divergenceReasons = divergenceDetected(report)
    return report


def _executeRemote(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    projectRoot: Path,
    report: StateReport,
    *,
    skipBackup: bool = False,
) -> int:
    tag = _timestampTag()
    priorActive = piServiceIsActive(addrs, runner)
    if priorActive:
        stopPiService(addrs, runner)
    try:
        if not skipBackup:
            piBackup = backupPi(addrs, runner, tag)
            print(f'[backup] Pi -> {piBackup}')
            try:
                serverBackup = backupServer(addrs, creds, runner, tag)
                print(f'[backup] Server -> {serverBackup}')
            except SafetyGateError as err:
                # Server backup failure is fail-open per invariant #5
                # (backup lands BEFORE any DELETE; no backup -> no DELETE).
                raise SafetyGateError(
                    'Server backup failed; refusing to proceed: '
                    f'{err}',
                ) from err
        # Pi DELETE
        statements = ['BEGIN IMMEDIATE;']
        for t in report.piTargets:
            statements.append(
                f"DELETE FROM {t.name} WHERE drive_id={DRIVE_ID_TARGET} "
                f"AND data_source='{DATA_SOURCE_TARGET}';",
            )
        statements.append(
            f'UPDATE drive_counter SET last_drive_id={DRIVE_COUNTER_TARGET} '
            f'WHERE id=1 AND last_drive_id<{DRIVE_COUNTER_TARGET};',
        )
        statements.append('COMMIT;')
        res = _runPiSql(addrs, '\n'.join(statements), runner)
        if res.returncode != 0:
            raise TruncateError(
                f'Pi DELETE failed: {res.stderr.strip() or res.stdout.strip()}',
            )
        # Server DELETE
        srvStatements = ['START TRANSACTION;']
        for t in report.serverTargets:
            srvStatements.append(
                f"DELETE FROM {t.name} WHERE drive_id={DRIVE_ID_TARGET} "
                f"AND data_source='{DATA_SOURCE_TARGET}';",
            )
        if report.serverHasDriveCounter:
            srvStatements.append(
                f'UPDATE drive_counter SET last_drive_id={DRIVE_COUNTER_TARGET} '
                f'WHERE id=1 AND last_drive_id<{DRIVE_COUNTER_TARGET};',
            )
        srvStatements.append('COMMIT;')
        res = _runServerSql(addrs, creds, '\n'.join(srvStatements), runner)
        if res.returncode != 0:
            raise TruncateError(
                f'Server DELETE failed: '
                f'{res.stderr.strip() or res.stdout.strip()}',
            )
        # Post-execute fixture hash check.
        post, postSha, _ = verifyFixtureHash(projectRoot)
        if not post:
            raise TruncateError(
                f'POST-EXECUTE fixture hash diverged: {postSha}',
            )
        # Remove sentinel so the next run dry-runs again.
        (projectRoot / DRY_RUN_SENTINEL_NAME).unlink(missing_ok=True)
    finally:
        if priorActive:
            startPiService(addrs, runner)
    return 0


def _executeLocalCli(
    dbPath: Path,
    projectRoot: Path,
    report: StateReport,
) -> int:
    executeLocalTruncate(
        dbPath, report.piTargets,
        driveCounterTarget=DRIVE_COUNTER_TARGET,
    )
    post, postSha, _ = verifyFixtureHash(projectRoot)
    if not post:
        raise TruncateError(
            f'POST-EXECUTE fixture hash diverged: {postSha}',
        )
    return 0


# ================================================================================
# CLI
# ================================================================================


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='truncate_drive_id_1_pollution.py',
        description='US-227 drive_id=1 pollution truncate (Pi + server)',
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        '--dry-run', action='store_true',
        help='Scan state + orphans + fixture hash; no mutations',
    )
    mode.add_argument(
        '--execute', action='store_true',
        help='Back up + DELETE + counter advance (requires prior --dry-run)',
    )
    parser.add_argument(
        '--local', action='store_true',
        help='Operate on a local SQLite DB only (test/CI mode)',
    )
    parser.add_argument(
        '--db', type=Path, default=None,
        help='Local DB path (required with --local)',
    )
    parser.add_argument(
        '--no-backup', action='store_true',
        help='Skip backup step (DANGEROUS; only for tests)',
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
    parser.add_argument(
        '--sentinel-dir', type=Path, default=None,
        help='Override sentinel directory (defaults to project root)',
    )
    args = parser.parse_args(argv)

    projectRoot: Path = args.project_root.resolve()
    sentinelDir: Path = (args.sentinel_dir or projectRoot).resolve()

    if args.local:
        if args.db is None:
            print(
                'ERROR: --local requires --db PATH',
                file=sys.stderr,
            )
            return 2
        try:
            report = _buildLocalReport(args.db, projectRoot)
        except TruncateError as err:
            print(f'ERROR: {err}', file=sys.stderr)
            return 2
    else:
        addressesPath = args.addresses or (
            projectRoot / 'deploy' / 'addresses.sh'
        )
        try:
            addrs = loadAddresses(addressesPath)
            creds = loadServerCreds(addrs)
            report = _buildRemoteReport(
                addrs, creds, _defaultRunner, projectRoot,
            )
        except TruncateError as err:
            print(f'ERROR: {err}', file=sys.stderr)
            return 2

    print(renderReport(report))

    if args.dry_run:
        _writeSentinel(sentinelDir, report)
        print(
            f'\n[dry-run] sentinel written: {sentinelDir / DRY_RUN_SENTINEL_NAME}',
        )
        if report.divergenceReasons:
            print(
                '[dry-run] divergence detected -- --execute would refuse.',
            )
        return 0

    # --execute path
    if _readSentinel(sentinelDir) is None:
        print(
            f'ERROR: --execute requires a prior --dry-run '
            f'(missing {sentinelDir / DRY_RUN_SENTINEL_NAME})',
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

    try:
        if args.local:
            rc = _executeLocalCli(args.db, projectRoot, report)
        else:
            rc = _executeRemote(
                addrs, creds, _defaultRunner, projectRoot, report,
                skipBackup=args.no_backup,
            )
    except TruncateError as err:
        print(f'ERROR: {err}', file=sys.stderr)
        return 2
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
