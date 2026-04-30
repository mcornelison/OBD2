################################################################################
# File Name: backfill_server_premint_orphans.py
# Purpose/Description: Backfill the drive_id column on realtime_data rows on
#                      the server's MariaDB obd2db that were captured during
#                      the Pi's BT-connect-to-cranking window (US-240 --
#                      Sprint 19). Server-side mirror of US-233's Pi-side
#                      script: same matching algorithm (orphan -> nearest
#                      subsequent drive_start within --window-seconds), but
#                      operating against MariaDB via SSH using the address
#                      and credential loaders from US-209's
#                      apply_server_migrations.py. Adds an explicit
#                      post-engine-off exclusion (orphans whose timestamp
#                      is past the latest drive's MAX timestamp stay NULL
#                      by design -- US-229 adapter polls continued after
#                      engine_state went KEY_OFF).
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex (US-240) | Initial -- server-side mirror of US-233 with
#                               explicit post-engine-off exclusion.
# ================================================================================
################################################################################

"""Server-side pre-mint orphan-row backfill (US-240).

Run from the project root with SSH reachability to ``SERVER_HOST``:

    python scripts/backfill_server_premint_orphans.py --dry-run
    python scripts/backfill_server_premint_orphans.py --execute

Algorithm: a server ``realtime_data`` row whose ``drive_id IS NULL AND
data_source = 'real'`` is a "pre-mint orphan" if its timestamp falls within
``--window-seconds`` BEFORE a real drive's start. We attach each orphan to
its nearest subsequent drive_id; orphans with no drive within the cap stay
NULL. **Post-engine-off rows** (timestamp strictly after the LATEST known
drive's MAX timestamp) are excluded explicitly per US-240 design --
adapter-level polls continue after engine_state goes KEY_OFF (US-229) and
are not part of any drive.

Safety: dry-run is read-only and writes a sentinel file; --execute refuses
without that sentinel, runs ``mysqldump --single-transaction`` of
``realtime_data`` first, then issues the UPDATE statements in a single
mysql transaction. Idempotent: re-running after a clean execute matches
zero rows because the same rows no longer have NULL drive_id.

Scope (US-240 invariants, mirrored from US-233):

* Touches only ``realtime_data``. ``drive_summary``, ``connection_log``,
  ``statistics``, ``alert_log``, ``dtc_log``, ``battery_health_log`` are
  NOT modified.
* Per-drive cap (default 1000) defends against runaway match.
* Tagged rows (``drive_id IS NOT NULL``) and non-real rows
  (``data_source != 'real'``) are NEVER modified -- the UPDATE WHERE
  clause keeps the same guard as the SELECT.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import shlex
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    'DEFAULT_WINDOW_SECONDS',
    'DEFAULT_MAX_ORPHANS_PER_DRIVE',
    'DRY_RUN_SENTINEL_NAME',
    'BACKUP_MAX_SECONDS',
    'BACKUP_MAX_BYTES',
    'BackfillError',
    'SafetyCapError',
    'SafetyGateError',
    'OrphanRow',
    'DriveAnchor',
    'BackfillMatch',
    'HostAddresses',
    'ServerCreds',
    'CommandRunner',
    'findOrphanBackfillMatches',
    'scanOrphans',
    'scanDriveAnchors',
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
    """Load a sibling script from scripts/ (which is not a package)."""
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

# Re-export the address + cred plumbing -- identical needs across server scripts.
HostAddresses = _us209.HostAddresses
ServerCreds = _us209.ServerCreds
CommandRunner = _us209.CommandRunner
loadAddresses = _us209.loadAddresses
loadServerCreds = _us209.loadServerCreds
_runServerSql = _us209._runServerSql
_defaultRunner = _us209._defaultRunner


# ================================================================================
# Configuration constants (mirror US-233)
# ================================================================================

DEFAULT_WINDOW_SECONDS: float = 60.0
DEFAULT_MAX_ORPHANS_PER_DRIVE: int = 1000

# Sentinel filename -- distinct from US-233's '.us233-dry-run-ok' so a
# Pi-side dry-run does NOT silently authorize a server execute.
DRY_RUN_SENTINEL_NAME: str = '.us240-dry-run-ok'

# mysqldump safety thresholds -- realtime_data is the only table dumped;
# 500MB and 60s leave plenty of headroom for the current scale (~22k rows
# at story start) plus future growth.
BACKUP_MAX_SECONDS: float = 60.0
BACKUP_MAX_BYTES: int = 500 * 1024 * 1024


# ================================================================================
# Exceptions
# ================================================================================

class BackfillError(Exception):
    """Base class for operator-facing backfill failures."""


class SafetyCapError(BackfillError):
    """A match would exceed the per-drive maxOrphansPerDrive cap."""


class SafetyGateError(BackfillError):
    """A safety gate (sentinel, backup timing/size) failed."""


# ================================================================================
# Data classes
# ================================================================================

@dataclass(slots=True, frozen=True)
class OrphanRow:
    """A NULL-drive_id row tagged data_source='real' on the server."""

    serverRowId: int  # server's auto-increment id (the UPDATE target)
    timestamp: str  # canonical ISO-8601 OR MariaDB DATETIME string


@dataclass(slots=True, frozen=True)
class DriveAnchor:
    """First and last real-data timestamps observed for a drive_id."""

    driveId: int
    driveStartTimestamp: str  # MIN(timestamp) for the drive
    driveEndTimestamp: str  # MAX(timestamp) for the drive


@dataclass(slots=True, frozen=True)
class BackfillMatch:
    """A single orphan -> drive association produced by the matcher."""

    serverRowId: int
    toDriveId: int
    rowTimestamp: str
    driveStartTimestamp: str
    gapSeconds: float


# ================================================================================
# Pure matching algorithm (no I/O)
# ================================================================================

def findOrphanBackfillMatches(
    orphans: Sequence[OrphanRow],
    anchors: Sequence[DriveAnchor],
    *,
    windowSeconds: float = DEFAULT_WINDOW_SECONDS,
    maxOrphansPerDrive: int = DEFAULT_MAX_ORPHANS_PER_DRIVE,
) -> list[BackfillMatch]:
    """Match each pre-mint orphan to its nearest subsequent real drive.

    Args:
        orphans: NULL-drive_id real rows from the server (any order; this
            function sorts internally).
        anchors: Per-drive (start, end) timestamps. ``driveStartTimestamp``
            is the drive's MIN(timestamp) and ``driveEndTimestamp`` is the
            MAX(timestamp); together they bracket the drive's data.
        windowSeconds: Maximum allowed gap between orphan timestamp and
            the subsequent drive_start. Orphans with no drive_start within
            the cap stay NULL.
        maxOrphansPerDrive: Refusal cap. If any drive_id would receive more
            than this many orphans, raise :class:`SafetyCapError` instead
            of silently truncating.

    Returns:
        :class:`BackfillMatch` entries ordered by orphan timestamp.

    Raises:
        ValueError: ``windowSeconds <= 0``.
        SafetyCapError: any drive_id would exceed the per-drive cap.

    US-240 explicit post-engine-off exclusion:
        An orphan whose timestamp is strictly past **every** known drive's
        ``driveEndTimestamp`` is treated as post-engine-off and stays NULL.
        This catches the US-229 scenario where the Pi's adapter-level
        polls (BATTERY_V via ELM_VOLTAGE) continued after engine_state
        went KEY_OFF -- those rows are not part of any drive. Even with
        an absurdly wide window the rule wins, providing defense-in-depth
        beyond what the natural "nearest subsequent drive_start within
        window" check would catch.
    """
    if windowSeconds <= 0:
        raise ValueError(
            f"windowSeconds must be > 0; got {windowSeconds}",
        )
    if not orphans or not anchors:
        return []

    sortedOrphans = sorted(orphans, key=lambda o: (o.timestamp, o.serverRowId))
    sortedAnchors = sorted(anchors, key=lambda a: a.driveStartTimestamp)

    # US-240 post-engine-off floor: max end timestamp across all drives.
    # An orphan past this floor is post-engine-off (no future drive
    # known); it stays NULL even if a far-future drive is later observed
    # because the natural window check would still reject it -- but we
    # encode the rule explicitly to make the intent visible + robust to
    # window widening.
    maxKnownDriveEnd = max(a.driveEndTimestamp for a in sortedAnchors)

    matches: list[BackfillMatch] = []
    perDriveCount: dict[int, int] = {}

    for orphan in sortedOrphans:
        # US-240 explicit branch: post-engine-off exclusion.
        if orphan.timestamp > maxKnownDriveEnd:
            continue

        nearest = _nearestSubsequentDriveStart(orphan.timestamp, sortedAnchors)
        if nearest is None:
            continue

        # Defense-in-depth: orphan must not fall in the post-engine-off
        # zone of an *earlier* drive. Specifically, if there is some
        # drive whose end is strictly before the orphan's timestamp AND
        # the orphan is closer to that drive's end than to the nearest
        # subsequent drive's start, treat it as post-engine-off and skip.
        if _isInPostEngineOffZoneBetweenDrives(
            orphan, sortedAnchors, nearest,
        ):
            continue

        gap = _isoGapSeconds(orphan.timestamp, nearest.driveStartTimestamp)
        # gap must be strictly positive (orphan strictly before drive_start)
        # AND within the window cap.
        if gap <= 0 or gap > windowSeconds:
            continue

        perDriveCount[nearest.driveId] = (
            perDriveCount.get(nearest.driveId, 0) + 1
        )
        if perDriveCount[nearest.driveId] > maxOrphansPerDrive:
            raise SafetyCapError(
                f"drive_id={nearest.driveId} would receive "
                f"{perDriveCount[nearest.driveId]} orphans, exceeding "
                f"maxOrphansPerDrive={maxOrphansPerDrive}; refuse",
            )
        matches.append(
            BackfillMatch(
                serverRowId=orphan.serverRowId,
                toDriveId=nearest.driveId,
                rowTimestamp=orphan.timestamp,
                driveStartTimestamp=nearest.driveStartTimestamp,
                gapSeconds=gap,
            ),
        )
    return matches


def _nearestSubsequentDriveStart(
    orphanTimestamp: str, anchors: Sequence[DriveAnchor],
) -> DriveAnchor | None:
    """Return the earliest drive whose start is strictly AFTER orphanTimestamp.

    ``anchors`` is assumed sorted ascending by driveStartTimestamp.
    """
    for anchor in anchors:
        if anchor.driveStartTimestamp > orphanTimestamp:
            return anchor
    return None


def _isInPostEngineOffZoneBetweenDrives(
    orphan: OrphanRow,
    anchors: Sequence[DriveAnchor],
    nextAnchor: DriveAnchor,
) -> bool:
    """Return True if orphan is post-engine-off of an earlier drive.

    The orphan's nearest-subsequent-drive is ``nextAnchor``. If there
    is any earlier drive whose end is < orphan.timestamp AND the orphan
    is closer to that earlier drive's end than to ``nextAnchor``'s start,
    the orphan belongs to the "post-engine-off" zone of the earlier drive
    rather than the "pre-mint" zone of ``nextAnchor``. Stay NULL.
    """
    for anchor in anchors:
        if anchor.driveStartTimestamp >= nextAnchor.driveStartTimestamp:
            # We only consider drives strictly earlier than nextAnchor.
            continue
        if anchor.driveEndTimestamp >= orphan.timestamp:
            # Orphan is within or before this drive's data window -- not a
            # post-engine-off candidate for it.
            continue
        # anchor ended before the orphan timestamp. Compare distances.
        gapSinceEnd = _isoGapSeconds(
            anchor.driveEndTimestamp, orphan.timestamp,
        )
        gapToNext = _isoGapSeconds(
            orphan.timestamp, nextAnchor.driveStartTimestamp,
        )
        if gapSinceEnd < gapToNext:
            return True
    return False


def _isoGapSeconds(earlier: str, later: str) -> float:
    """Seconds between two timestamp strings (later - earlier).

    Accepts both Pi-canonical ``YYYY-MM-DDTHH:MM:SSZ`` and MariaDB-default
    ``YYYY-MM-DD HH:MM:SS`` shapes; the matcher receives whatever the
    backing store produced, and lexicographic ordering on either format
    matches chronological ordering.
    """
    return (_parseIso(later) - _parseIso(earlier)).total_seconds()


def _parseIso(ts: str) -> _dt.datetime:
    """Parse a timestamp string in either ISO-8601 ``Z`` or MariaDB shape."""
    raw = ts.strip()
    if raw.endswith('Z'):
        raw = raw[:-1] + '+00:00'
    if 'T' not in raw and ' ' in raw:
        raw = raw.replace(' ', 'T', 1)
    parsed = _dt.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.UTC)
    return parsed


# ================================================================================
# I/O wrappers (SSH + MariaDB via mysql -B -N)
# ================================================================================

def scanOrphans(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
) -> list[OrphanRow]:
    """Return every server row with NULL drive_id AND data_source='real'.

    Output is sorted by timestamp ascending. Includes post-engine-off rows
    (the matcher applies the explicit US-240 exclusion); the SQL filter
    is intentionally narrow so an operator running ``--dry-run`` sees the
    full orphan population in the report.
    """
    sql = (
        "SELECT id, timestamp FROM realtime_data "
        "WHERE drive_id IS NULL AND data_source = 'real' "
        "ORDER BY timestamp ASC, id ASC;"
    )
    res = _runServerSql(addrs, creds, sql, runner)
    if res.returncode != 0:
        raise BackfillError(
            f'scan orphan rows failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    rows: list[OrphanRow] = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        rows.append(OrphanRow(
            serverRowId=int(parts[0]),
            timestamp=parts[1],
        ))
    return rows


def scanDriveAnchors(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
) -> list[DriveAnchor]:
    """Return one anchor (drive_id, MIN ts, MAX ts) per real drive.

    Sim/test drives (``data_source != 'real'``) are skipped -- we never
    backfill real orphans against a sim drive. Drives appear in
    chronological start order.
    """
    sql = (
        "SELECT drive_id, MIN(timestamp), MAX(timestamp) FROM realtime_data "
        "WHERE drive_id IS NOT NULL AND data_source = 'real' "
        "GROUP BY drive_id "
        "ORDER BY MIN(timestamp) ASC;"
    )
    res = _runServerSql(addrs, creds, sql, runner)
    if res.returncode != 0:
        raise BackfillError(
            f'scan drive anchor rows failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    anchors: list[DriveAnchor] = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        anchors.append(DriveAnchor(
            driveId=int(parts[0]),
            driveStartTimestamp=parts[1],
            driveEndTimestamp=parts[2],
        ))
    return anchors


def applyBackfill(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    matches: Iterable[BackfillMatch],
) -> int:
    """Issue a single mysql transaction with one UPDATE per matched row.

    The transaction wraps every UPDATE so a mid-batch failure rolls back
    the entire change set (MariaDB DDL would be implicit-commit but UPDATE
    is fully transactional). The WHERE clause keeps the
    ``drive_id IS NULL AND data_source='real'`` guard so a stale match
    cannot clobber a tagged row, mirroring US-233's safety property.
    """
    matchList = list(matches)
    if not matchList:
        return 0
    statements: list[str] = ['START TRANSACTION;']
    for match in matchList:
        statements.append(
            f'UPDATE realtime_data SET drive_id = {match.toDriveId} '
            f"WHERE id = {match.serverRowId} "
            f"AND drive_id IS NULL "
            f"AND data_source = 'real';"
        )
    statements.append('COMMIT;')
    sqlBlob = '\n'.join(statements) + '\n'
    res = _runServerSql(addrs, creds, sqlBlob, runner)
    if res.returncode != 0:
        raise BackfillError(
            f'UPDATE batch failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    # mysql with -B -N has no per-statement output for UPDATEs; we trust the
    # transaction-level success.
    return len(matchList)


def backupServer(
    addrs: HostAddresses,
    creds: ServerCreds,
    runner: CommandRunner,
    timestampTag: str,
) -> str:
    """Dump realtime_data to /tmp/obd2-us240-backup-<ts>.sql on the server.

    Uses ``mysqldump --single-transaction`` so the dump is consistent
    without locking writers. Stop-condition guards:

    * Dump must finish within :data:`BACKUP_MAX_SECONDS`.
    * Resulting file must be smaller than :data:`BACKUP_MAX_BYTES`.

    Returns the server-side path to the backup file.
    """
    dumpPath = f'/tmp/obd2-us240-backup-{timestampTag}.sql'
    envPrefix = f'MYSQL_PWD={shlex.quote(creds.dbPassword)}'
    cmd = (
        f'{envPrefix} mysqldump --single-transaction --skip-lock-tables '
        f'-u {shlex.quote(creds.dbUser)} '
        f'{shlex.quote(creds.dbName)} realtime_data '
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
            f'server backup failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    if elapsed > BACKUP_MAX_SECONDS:
        raise SafetyGateError(
            f'server backup exceeded {BACKUP_MAX_SECONDS:.0f}s '
            f'(took {elapsed:.1f}s)',
        )
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
                f'> {BACKUP_MAX_BYTES}',
            )
    return dumpPath


# ================================================================================
# Reporting
# ================================================================================

def renderReport(
    orphans: Sequence[OrphanRow],
    anchors: Sequence[DriveAnchor],
    matches: Sequence[BackfillMatch],
    *,
    dryRun: bool,
) -> str:
    """Operator-facing summary of the proposed (or applied) backfill."""
    lines: list[str] = []
    lines.append('=' * 72)
    lines.append('US-240 server-side pre-mint orphan backfill')
    lines.append('=' * 72)
    lines.append(f'  mode:           {"dry-run" if dryRun else "execute"}')
    lines.append(f'  orphans found:  {len(orphans)}')
    lines.append(f'  drives known:   {len(anchors)}')
    if anchors:
        ids = ','.join(str(a.driveId) for a in anchors)
        lines.append(f'    drive_ids:    {ids}')
        maxEnd = max(a.driveEndTimestamp for a in anchors)
        lines.append(f'    max end ts:   {maxEnd}')
    lines.append(f'  matches:        {len(matches)}')
    if not matches:
        if orphans and anchors:
            lines.append(
                '  -> all orphans stay NULL '
                '(pre-pollution, between drives, or post-engine-off)',
            )
        else:
            lines.append('  -> nothing to do')
        lines.append('=' * 72)
        return '\n'.join(lines)
    perDrive: dict[int, int] = {}
    for match in matches:
        perDrive[match.toDriveId] = perDrive.get(match.toDriveId, 0) + 1
    lines.append('  per-drive matches:')
    for driveId in sorted(perDrive):
        lines.append(f'    drive_id={driveId}: {perDrive[driveId]} orphan(s)')
    earliest = min(m.rowTimestamp for m in matches)
    latest = max(m.rowTimestamp for m in matches)
    maxGap = max(m.gapSeconds for m in matches)
    stayNull = len(orphans) - len(matches)
    lines.append(
        f'  span:           [{earliest} .. {latest}]  max gap={maxGap:.1f}s',
    )
    lines.append(
        f'  stay NULL:      {stayNull} '
        '(pre-pollution / between drives / post-engine-off)',
    )
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='backfill_server_premint_orphans.py',
        description=(
            'US-240 server-side pre-mint orphan backfill: attach NULL-'
            'drive_id real rows on the server to the nearest subsequent '
            'drive (within --window-seconds). Mirror of US-233.'
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        '--dry-run', action='store_true',
        help='Scan + report; no mutation',
    )
    mode.add_argument(
        '--execute', action='store_true',
        help='Apply UPDATE after a prior --dry-run',
    )
    parser.add_argument(
        '--window-seconds', type=float,
        default=DEFAULT_WINDOW_SECONDS,
        help=(
            f'Maximum gap between orphan and subsequent drive_start '
            f'(default {DEFAULT_WINDOW_SECONDS}s)'
        ),
    )
    parser.add_argument(
        '--max-orphans-per-drive', type=int,
        default=DEFAULT_MAX_ORPHANS_PER_DRIVE,
        help=(
            f'Refuse if any drive would receive > N orphans '
            f'(default {DEFAULT_MAX_ORPHANS_PER_DRIVE})'
        ),
    )
    parser.add_argument(
        '--addresses', type=Path, default=None,
        help='Override path to deploy/addresses.sh',
    )
    parser.add_argument(
        '--sentinel-dir', type=Path, default=None,
        help=(
            'Directory for the dry-run sentinel '
            '(defaults to the repo root)'
        ),
    )
    args = parser.parse_args(argv)

    projectRoot = Path(__file__).resolve().parents[1]
    addressesPath = args.addresses or (projectRoot / 'deploy' / 'addresses.sh')
    sentinelDir = (args.sentinel_dir or projectRoot).resolve()

    runner: CommandRunner = _defaultRunner

    try:
        addrs = loadAddresses(addressesPath, runner=runner)
        creds = loadServerCreds(addrs, runner=runner)
        orphans = scanOrphans(addrs, creds, runner)
        anchors = scanDriveAnchors(addrs, creds, runner)
        try:
            matches = findOrphanBackfillMatches(
                orphans, anchors,
                windowSeconds=args.window_seconds,
                maxOrphansPerDrive=args.max_orphans_per_drive,
            )
        except (ValueError, SafetyCapError) as err:
            print(f'ERROR: {err}', file=sys.stderr)
            return 3
        print(renderReport(orphans, anchors, matches, dryRun=args.dry_run))
    except BackfillError as err:
        print(f'ERROR: {err}', file=sys.stderr)
        return 2

    if args.dry_run:
        _writeSentinel(
            sentinelDir,
            f'orphans={len(orphans)}\n'
            f'anchors={len(anchors)}\n'
            f'matches={len(matches)}\n'
            f'window={args.window_seconds}\n'
            f'writtenAt={_dt.datetime.now(_dt.UTC).isoformat()}\n',
        )
        print(
            f'\n[dry-run] sentinel: {sentinelDir / DRY_RUN_SENTINEL_NAME}',
        )
        return 0

    # --execute path
    if _readSentinel(sentinelDir) is None:
        print(
            'ERROR: --execute requires a prior --dry-run '
            f'(missing {sentinelDir / DRY_RUN_SENTINEL_NAME})',
            file=sys.stderr,
        )
        return 2
    if not matches:
        print('[execute] zero matches; clearing sentinel and exiting')
        _clearSentinel(sentinelDir)
        return 0
    try:
        backupPath = backupServer(addrs, creds, runner, _timestampTag())
        print(f'[backup] server -> {backupPath}')
        applied = applyBackfill(addrs, creds, runner, matches)
        print(f'[execute] UPDATE applied: {applied} row(s)')
    except BackfillError as err:
        print(f'ERROR: {err}', file=sys.stderr)
        return 2
    _clearSentinel(sentinelDir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
