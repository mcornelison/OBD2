################################################################################
# File Name: boot_ladder_report.py
# Purpose/Description: US-861 (F-157) -- the desk tool that reports the boot
#                      ladder from counted cold key-ons.  Reads FILES only (a
#                      copy of obd.db and per-boot journal exports), classifies
#                      each boot COUNTED or EXCLUDED(reasons), and prints
#                      per-milestone statistics before vs after a change, with
#                      a VERDICT only when both sides have n >= 5.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-861) | Initial.
# ================================================================================
################################################################################

"""Boot ladder report (US-861).

Every OS change is accepted only on n >= 5 counted cold key-ons before and
after it (CIO DoD, Atlas C5).  Counting by hand is error-prone, so this tool
counts from the boot record.  Inputs are FILES, never ssh (Atlas RULED S101):

- ``--db``: a copy of the Pi's obd.db (``boot_milestone`` + ``startup_log``),
  opened read-only.
- ``--journal-dir``: one ``journalctl -o short-monotonic`` export per boot,
  named ``<boot_id>.<anything>``.
- ``--deploy-at`` (repeatable), ``--change-at``, ``--min-off-s`` (default 60).

A boot is COUNTED only when no rule below fails; otherwise it is EXCLUDED with
every failing reason, in this fixed order (Atlas RULED US-861 + G1/G2):

1. ``no_startup_log``  -- no startup_log row for the boot_id.  The cold-key-on
   rules cannot be read without it, so they are not reported beside it.
2. ``warm_reboot``     -- prior_boot_loss_at NULL, or neither
   prior_boot_last_stage = CLEAN_COMPLETE nor prior_boot_clean = 0.
3. ``short_off``       -- kernel_start.ts_utc - prior_boot_loss_at < --min-off-s
   (kernel_start, never recorded_at: the row is often written pre-NTP).
4. ``no_obd``          -- obd_connected or first_sample_obd missing.  Car power
   is INFERRED from the OBD connect; the OBD rungs report only as this reason.
5. ``missing_milestone:<name>`` -- kernel_start or first_sample_imu/light/ups
   missing.  drive_start is not required.
6. ``first_after_deploy`` -- the first boot whose kernel_start follows a
   --deploy-at.
7. ``deploy_mid_boot`` -- a --deploy-at in [kernel_start.ts_utc, lastWall],
   where lastWall = kernel_start.ts_utc + the export's last monotonic seconds
   (both count from kernel start, so they share an axis).
8. ``obd_restarted``   -- the export's 'Started eclipse-obd.service' count is
   not exactly 1.  A boot with no export counts 0.

Usage::

    python scripts/boot_ladder_report.py --db obd.db --journal-dir journals \\
        --deploy-at 2026-10-14T15:55:30Z --change-at 2026-10-20T18:00:00Z
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import statistics
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Allow `python scripts/boot_ladder_report.py ...` to resolve src.* imports
# without requiring the project to be installed as a package.
_projectRoot = Path(__file__).resolve().parents[1]
if str(_projectRoot) not in sys.path:
    sys.path.insert(0, str(_projectRoot))

from src.common.time.helper import CANONICAL_ISO_FORMAT  # noqa: E402
from src.pi.diagnostics.boot_milestone import (  # noqa: E402
    DRIVE_START,
    FIRST_SAMPLE_IMU,
    FIRST_SAMPLE_LIGHT,
    FIRST_SAMPLE_OBD,
    FIRST_SAMPLE_UPS,
    KERNEL_START,
    OBD_CONNECTED,
)
from src.pi.diagnostics.boot_progress import CLEAN_COMPLETE_RUNG  # noqa: E402

#: Atlas RULED US-861: off-time below this is not a cold key-on.
DEFAULT_MIN_OFF_S = 60.0

#: CIO DoD / Atlas C5: a before/after verdict needs n >= 5 counted boots a side.
MIN_VERDICT_N = 5

CAR_POWER_HEADER = 'car power inferred from OBD connect; supply not instrumented'

REASON_NO_STARTUP_LOG = 'no_startup_log'
REASON_WARM_REBOOT = 'warm_reboot'
REASON_SHORT_OFF = 'short_off'
REASON_NO_OBD = 'no_obd'
REASON_MISSING_MILESTONE = 'missing_milestone'
REASON_FIRST_AFTER_DEPLOY = 'first_after_deploy'
REASON_DEPLOY_MID_BOOT = 'deploy_mid_boot'
REASON_OBD_RESTARTED = 'obd_restarted'

#: The rungs that prove car power; they report ONLY as no_obd (Atlas G1).
OBD_MILESTONES: tuple[str, ...] = (OBD_CONNECTED, FIRST_SAMPLE_OBD)

#: The rungs every counted boot must have, in reporting order.
REQUIRED_MILESTONES: tuple[str, ...] = (
    KERNEL_START, FIRST_SAMPLE_IMU, FIRST_SAMPLE_LIGHT, FIRST_SAMPLE_UPS,
)

#: Journal milestones (Atlas: boot_milestone has no kiosk rung).
GRAPHICAL_TARGET = 'graphical.target'
DASHBOARD_STARTED = 'eclipse-dashboard'

#: The statistics rows, in ladder order.  kernel_start is always 0.
REPORT_MILESTONES: tuple[str, ...] = (
    FIRST_SAMPLE_IMU,
    FIRST_SAMPLE_LIGHT,
    FIRST_SAMPLE_UPS,
    OBD_CONNECTED,
    FIRST_SAMPLE_OBD,
    DRIVE_START,
    GRAPHICAL_TARGET,
    DASHBOARD_STARTED,
)

#: startup_log columns the cold-key-on rules read; prior_boot_loss_at is ARCH-065.
STARTUP_LOG_COLUMNS: tuple[str, ...] = (
    'boot_id', 'prior_boot_clean', 'prior_boot_last_stage', 'prior_boot_loss_at',
)

BEFORE = 'BEFORE'
AFTER = 'AFTER'

_JOURNAL_LINE = re.compile(r'^\[\s*(\d+(?:\.\d+)?)\]\s?(.*)$')
_OBD_STARTED = re.compile(r'\bStarted eclipse-obd\.service\b')
_GRAPHICAL_REACHED = re.compile(r'\bReached target graphical\.target\b')
_DASHBOARD_STARTED = re.compile(r'\bStarted eclipse-dashboard\.service\b')


class ReportInputError(Exception):
    """An input file is missing or unreadable; the report cannot run."""


@dataclass
class JournalSummary:
    """What one boot's short-monotonic journal export says."""

    obdStarts: int = 0
    lastMonotonicS: float | None = None
    graphicalTargetS: float | None = None
    dashboardStartedS: float | None = None


@dataclass
class Boot:
    """One boot_id's record and its classification."""

    bootId: str
    tsUtc: dict[str, datetime] = field(default_factory=dict)
    uptimeS: dict[str, float] = field(default_factory=dict)
    journal: JournalSummary | None = None
    reasons: list[str] = field(default_factory=list)
    side: str = BEFORE

    @property
    def kernelStart(self) -> datetime | None:
        return self.tsUtc.get(KERNEL_START)

    @property
    def sortKey(self) -> datetime:
        """kernel_start, else the boot's earliest rung."""
        return self.kernelStart or min(self.tsUtc.values())

    @property
    def counted(self) -> bool:
        return not self.reasons

    def milestoneS(self, name: str) -> float | None:
        """Seconds from kernel start to ``name``, from boot_milestone or the journal."""
        if name == GRAPHICAL_TARGET:
            return self.journal.graphicalTargetS if self.journal else None
        if name == DASHBOARD_STARTED:
            return self.journal.dashboardStartedS if self.journal else None
        return self.uptimeS.get(name)


# ================================================================================
# Inputs
# ================================================================================

def parseIso(text: str) -> datetime:
    """An ISO-8601 time as an aware UTC datetime; a naive time is taken as UTC.

    Raises:
        ValueError: ``text`` is not ISO-8601.
    """
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _isoArg(text: str) -> datetime:
    try:
        return parseIso(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f'not an ISO-8601 time: {text!r}') from exc


def formatIso(value: datetime) -> str:
    return value.strftime(CANONICAL_ISO_FORMAT)


def parseJournal(path: Path) -> JournalSummary:
    """Summarise one ``journalctl -o short-monotonic`` export.

    Lines without a ``[ seconds]`` prefix (the '-- Journal begins --' banner,
    '-- Boot ... --' separators) are skipped.
    """
    summary = JournalSummary()
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            match = _JOURNAL_LINE.match(line)
            if not match:
                continue
            seconds = float(match.group(1))
            message = match.group(2)
            if summary.lastMonotonicS is None or seconds > summary.lastMonotonicS:
                summary.lastMonotonicS = seconds
            if _OBD_STARTED.search(message):
                summary.obdStarts += 1
            if summary.graphicalTargetS is None and _GRAPHICAL_REACHED.search(message):
                summary.graphicalTargetS = seconds
            if summary.dashboardStartedS is None and _DASHBOARD_STARTED.search(message):
                summary.dashboardStartedS = seconds
    return summary


def _normalizeBootId(text: str) -> str:
    """As startup_log carries it: lowercase, dashes stripped."""
    return text.strip().lower().replace('-', '')


def loadJournals(journalDir: Path) -> dict[str, JournalSummary]:
    """boot_id -> summary for every export in ``journalDir`` (file stem = boot_id)."""
    if not journalDir.is_dir():
        raise ReportInputError(f'journal dir not found: {journalDir}')
    return {
        _normalizeBootId(path.stem): parseJournal(path)
        for path in sorted(journalDir.iterdir())
        if path.is_file()
    }


def _openReadOnly(dbPath: Path) -> sqlite3.Connection:
    if not dbPath.is_file():
        raise ReportInputError(f'database copy not found: {dbPath}')
    conn = sqlite3.connect(f'{dbPath.resolve().as_uri()}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}


def loadBoots(conn: sqlite3.Connection) -> dict[str, Boot]:
    """Every boot in boot_milestone, read by column NAME (S98 and id-keyed shapes)."""
    if not {'boot_id', 'milestone', 'ts_utc', 'uptime_s'} <= _columns(conn, 'boot_milestone'):
        raise ReportInputError('boot_milestone table (boot_id, milestone, ts_utc, uptime_s) '
                               'not found in the database copy')
    boots: dict[str, Boot] = {}
    for row in conn.execute('SELECT boot_id, milestone, ts_utc, uptime_s FROM boot_milestone'):
        boot = boots.setdefault(row['boot_id'], Boot(bootId=row['boot_id']))
        boot.tsUtc[row['milestone']] = parseIso(row['ts_utc'])
        boot.uptimeS[row['milestone']] = float(row['uptime_s'])
    return boots


def loadStartupLog(conn: sqlite3.Connection) -> tuple[dict[str, sqlite3.Row], str | None]:
    """boot_id -> startup_log row, plus a WARN when the copy cannot answer.

    A copy without the cold-key-on columns (a pre-ARCH-065 copy has no
    prior_boot_loss_at) yields no rows, so every boot is no_startup_log.
    """
    missing = [c for c in STARTUP_LOG_COLUMNS if c not in _columns(conn, 'startup_log')]
    if missing:
        return {}, (f"WARN: startup_log has no {', '.join(missing)} column; "
                    'every boot is EXCLUDED(no_startup_log)')
    rows = conn.execute(f"SELECT {', '.join(STARTUP_LOG_COLUMNS)} FROM startup_log")
    return {row['boot_id']: row for row in rows}, None


# ================================================================================
# Classification
# ================================================================================

def _lossAt(row: sqlite3.Row) -> datetime | None:
    try:
        return parseIso(row['prior_boot_loss_at']) if row['prior_boot_loss_at'] else None
    except ValueError:
        return None


def _coldReasons(boot: Boot, row: sqlite3.Row | None, minOffS: float) -> list[str]:
    if row is None:
        return [REASON_NO_STARTUP_LOG]
    reasons = []
    lossAt = _lossAt(row)
    priorOff = (row['prior_boot_last_stage'] == CLEAN_COMPLETE_RUNG.value
                or row['prior_boot_clean'] == 0)
    if lossAt is None or not priorOff:
        reasons.append(REASON_WARM_REBOOT)
    if lossAt is not None and boot.kernelStart is not None:
        if (boot.kernelStart - lossAt).total_seconds() < minOffS:
            reasons.append(REASON_SHORT_OFF)
    return reasons


def _lastWall(boot: Boot) -> datetime | None:
    if boot.kernelStart is None or boot.journal is None or boot.journal.lastMonotonicS is None:
        return None
    return boot.kernelStart + timedelta(seconds=boot.journal.lastMonotonicS)


def classifyBoots(
    boots: Sequence[Boot],
    startupLog: dict[str, sqlite3.Row],
    deployAts: Sequence[datetime],
    changeAt: datetime | None,
    minOffS: float,
) -> None:
    """Set each boot's reasons (fixed order) and side, in place.

    ``boots`` must be in boot order (:attr:`Boot.sortKey`).
    """
    withKernel = [b for b in boots if b.kernelStart is not None]
    firstAfterDeploy = set()
    for deployAt in deployAts:
        following = [b for b in withKernel if b.kernelStart > deployAt]  # type: ignore[operator]
        if following:
            firstAfterDeploy.add(following[0].bootId)

    for boot in boots:
        reasons = _coldReasons(boot, startupLog.get(boot.bootId), minOffS)
        if any(name not in boot.tsUtc for name in OBD_MILESTONES):
            reasons.append(REASON_NO_OBD)
        reasons += [f'{REASON_MISSING_MILESTONE}:{name}'
                    for name in REQUIRED_MILESTONES if name not in boot.tsUtc]
        if boot.bootId in firstAfterDeploy:
            reasons.append(REASON_FIRST_AFTER_DEPLOY)
        lastWall = _lastWall(boot)
        if lastWall is not None and any(
            boot.kernelStart <= d <= lastWall for d in deployAts  # type: ignore[operator]
        ):
            reasons.append(REASON_DEPLOY_MID_BOOT)
        if (boot.journal.obdStarts if boot.journal else 0) != 1:
            reasons.append(REASON_OBD_RESTARTED)
        boot.reasons = reasons
        boot.side = AFTER if changeAt is not None and boot.sortKey > changeAt else BEFORE


# ================================================================================
# Output
# ================================================================================

def _status(boot: Boot) -> str:
    return 'COUNTED' if boot.counted else f"EXCLUDED({', '.join(boot.reasons)})"


def _sideStats(values: list[float]) -> str:
    if not values:
        return 'n=0'
    low, high = min(values), max(values)
    return (f'n={len(values)} median {statistics.median(values):.1f} s '
            f'min {low:.1f} max {high:.1f} spread {high - low:.1f}')


def buildReport(
    boots: Sequence[Boot],
    deployAts: Sequence[datetime],
    changeAt: datetime | None,
    minOffS: float,
) -> list[str]:
    """The report's lines: header, one line per boot, statistics, verdict."""
    lines = [
        CAR_POWER_HEADER,
        (f"deploys: {', '.join(formatIso(d) for d in deployAts) or 'none'}; "
         f"change-at: {formatIso(changeAt) if changeAt else 'none'}; min-off-s: {minOffS:g}"),
        '',
    ]
    for boot in boots:
        kernel = formatIso(boot.kernelStart) if boot.kernelStart else '-'
        lines.append(f'{boot.bootId}  {kernel}  {boot.side}  {_status(boot)}')

    counted = {side: [b for b in boots if b.counted and b.side == side] for side in (BEFORE, AFTER)}
    lines += ['', 'milestone (seconds from kernel start), COUNTED boots only:']
    medians: dict[str, dict[str, float]] = {BEFORE: {}, AFTER: {}}
    for name in REPORT_MILESTONES:
        parts = []
        for side in (BEFORE, AFTER):
            values = [v for v in (b.milestoneS(name) for b in counted[side]) if v is not None]
            if values:
                medians[side][name] = statistics.median(values)
            parts.append(f'{side} {_sideStats(values)}')
        lines.append(f'{name:<20}{parts[0]}  |  {parts[1]}')

    nBefore, nAfter = len(counted[BEFORE]), len(counted[AFTER])
    lines.append('')
    if nBefore >= MIN_VERDICT_N and nAfter >= MIN_VERDICT_N:
        deltas = [f'{name} {medians[AFTER][name] - medians[BEFORE][name]:+.1f} s'
                  for name in REPORT_MILESTONES
                  if name in medians[BEFORE] and name in medians[AFTER]]
        lines.append(f"VERDICT (median AFTER - BEFORE): {', '.join(deltas)}")
    else:
        lines.append(f'NO VERDICT: n before {nBefore}, after {nAfter}')
    return lines


# ================================================================================
# CLI
# ================================================================================

def _parseArgs(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Report the boot ladder from counted cold key-ons (US-861). FILES only.',
    )
    parser.add_argument('--db', required=True, type=Path,
                        help='a COPY of the Pi obd.db (boot_milestone + startup_log)')
    parser.add_argument('--journal-dir', required=True, type=Path,
                        help='one `journalctl -o short-monotonic` export per boot, '
                             'named <boot_id>.<ext>')
    parser.add_argument('--deploy-at', action='append', default=[], type=_isoArg,
                        help='ISO time of a deploy (repeatable)')
    parser.add_argument('--change-at', type=_isoArg, default=None,
                        help='ISO time of the change deploy; boots after it are AFTER')
    parser.add_argument('--min-off-s', type=float, default=DEFAULT_MIN_OFF_S,
                        help=f'shortest off-time of a cold key-on (default {DEFAULT_MIN_OFF_S:g})')
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the report.  Returns 0, or 1 when an input file is missing."""
    args = _parseArgs(argv)
    deployAts: list[datetime] = list(args.deploy_at)
    if args.change_at is not None and args.change_at not in deployAts:
        print(f'WARN: --change-at {formatIso(args.change_at)} is not a --deploy-at; '
              'added as a deploy (its first boot after is excluded)', file=sys.stderr)
        deployAts.append(args.change_at)
    deployAts.sort()

    try:
        journals = loadJournals(args.journal_dir)
        conn = _openReadOnly(args.db)
        try:
            bootsById = loadBoots(conn)
            startupLog, warning = loadStartupLog(conn)
        finally:
            conn.close()
    except ReportInputError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f'ERROR: cannot read {args.db}: {exc}', file=sys.stderr)
        return 1
    if warning:
        print(warning, file=sys.stderr)

    boots = sorted(bootsById.values(), key=lambda b: b.sortKey)
    for boot in boots:
        boot.journal = journals.get(_normalizeBootId(boot.bootId))
    classifyBoots(boots, startupLog, deployAts, args.change_at, args.min_off_s)
    print('\n'.join(buildReport(boots, deployAts, args.change_at, args.min_off_s)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
