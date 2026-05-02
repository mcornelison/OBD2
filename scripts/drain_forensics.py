################################################################################
# File Name: drain_forensics.py
# Purpose/Description: US-262 drain forensics logger.  Activates when the UPS
#                      is on BATTERY; writes one 14-column CSV row every 5s
#                      to /var/log/eclipse-obd/drain-forensics-<TS>.csv with
#                      append-mode + os.fsync(); rotates by timestamp suffix
#                      on AC->BATTERY transition.  Captures the two diagnostic
#                      crown jewels for Drain Test 7: pd_tick_count (proves
#                      whether PowerDownOrchestrator.tick() is running) and
#                      throttled_hex (proves whether the Pi 5 SoC browns out
#                      before VCELL crosses thresholds, per CIO hypothesis).
#                      Stateless across systemd-timer fires: the timer runs a
#                      fresh Python process every 5s; rotation detection uses
#                      the latest CSV's mtime so no state file is required.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex (US-262) | Initial -- 14-column CSV writer + DI providers
#                                + os.fsync after every row + AC-transition
#                                rotation by mtime gap.  Companion to
#                                deploy/drain-forensics.service + .timer.
# ================================================================================
################################################################################

"""US-262 drain forensics logger.

Run-mode
--------
Driven by ``deploy/drain-forensics.timer`` which fires every 5s.  Each
firing instantiates a fresh Python process, calls :func:`main`, exits.
There is no daemon mode; the script is intentionally stateless across
fires so a runtime crash inside the logger cannot corrupt persistent
in-memory state.

Lifecycle per fire
------------------
1. Read the current power source.  If not BATTERY, return immediately
   (logger is a no-op while wall power feeds the UPS).
2. Resolve the active CSV file: glob ``drain-forensics-*.csv`` in the
   log directory.  If the newest file's mtime is within
   ``rotationGapSeconds`` (default 30s) of "now", append to it
   (continuation).  Otherwise, open a brand-new file with the current
   timestamp encoded in the suffix (this is the AC->BATTERY transition
   case; rotation by mtime gap is more robust than a state file because
   the CSV itself is the source of truth).
3. Compose a 14-column row from injected providers (UPS telemetry,
   vcgencmd, /proc/loadavg, orchestrator state, wall-clock + epoch).
4. Append the row in text mode, ``flush()`` the file object, then call
   ``os.fsync(fileno())`` so a hard-crash within the next 5s cannot
   strand buffered data in pagecache.

CSV columns (14, in order)
--------------------------
| # | Column              | Source                                  |
|---|---------------------|-----------------------------------------|
| 1 | timestamp_utc       | utcIsoNow                               |
| 2 | seconds_on_battery  | now - first row's timestamp_utc         |
| 3 | vcell_v             | MAX17048 reg 0x02 (78.125 uV/LSB)       |
| 4 | soc_pct             | MAX17048 reg 0x04 (high byte)           |
| 5 | crate_pct_per_hr    | MAX17048 reg 0x16 (signed, 0.208 %/hr)  |
| 6 | cpu_temp_c          | vcgencmd measure_temp                   |
| 7 | core_v              | vcgencmd measure_volts core             |
| 8 | sdram_c_v           | vcgencmd measure_volts sdram_c          |
| 9 | sdram_i_v           | vcgencmd measure_volts sdram_i          |
| 10| sdram_p_v           | vcgencmd measure_volts sdram_p          |
| 11| throttled_hex       | vcgencmd get_throttled (bit 0 = NOW)    |
| 12| load_1min           | /proc/loadavg first field                |
| 13| pd_stage            | PowerDownOrchestrator.currentStage      |
| 14| pd_tick_count       | PowerDownOrchestrator.tickCount         |

Cross-process gap (orchestrator state)
--------------------------------------
The PowerDownOrchestrator instance lives in the eclipse-obd.service
process.  This logger is its own systemd-timer-driven process and
cannot read the live orchestrator's :attr:`tickCount` /
:attr:`currentStage` directly.  The production
``orchestratorStateProvider`` reads from a small JSON state file at
``/var/run/eclipse-obd/orchestrator-state.json`` (atomic rename writer
on the orchestrator side; best-effort read on this side).  If the
file is absent or malformed the columns emit ``-1`` / ``unknown`` --
itself a diagnostic signal ("orchestrator never wrote state").
Wiring the orchestrator to write the state file is a known gap; see
the story handoff notes for the follow-up TD-pointer.

Invariants
----------
* fsync after every CSV row -- the spec mandates buffered data MUST
  NOT be lost on hard-crash.
* Logger no-ops on AC -- zero overhead during normal operation.
* No raise-out-of-runOnce in the no-op or successful-write paths.  The
  logger is a forensic side-channel; failures of forensics MUST NOT
  affect the eclipse-obd capture loop running in a sibling process.
* Stateless across timer fires -- rotation is mtime-based on the CSV
  artifact, not a persistent state file.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    'CSV_COLUMNS',
    'DEFAULT_LOG_DIR',
    'DEFAULT_ORCHESTRATOR_STATE_FILE',
    'DEFAULT_ROTATION_GAP_SECONDS',
    'FILENAME_PREFIX',
    'FILENAME_SUFFIX',
    'ForensicsContext',
    'RunResult',
    'buildProductionContext',
    'composeFilename',
    'main',
    'runOnce',
]


# ================================================================================
# Constants
# ================================================================================


# 14-column header in canonical write order. Tests pin this tuple identically.
CSV_COLUMNS: tuple[str, ...] = (
    'timestamp_utc',
    'seconds_on_battery',
    'vcell_v',
    'soc_pct',
    'crate_pct_per_hr',
    'cpu_temp_c',
    'core_v',
    'sdram_c_v',
    'sdram_i_v',
    'sdram_p_v',
    'throttled_hex',
    'load_1min',
    'pd_stage',
    'pd_tick_count',
)

# Production log directory (the systemd unit creates the parent dir on install).
DEFAULT_LOG_DIR: Path = Path('/var/log/eclipse-obd')

# State-file path that the production orchestratorStateProvider reads.
# Wired by a later story; absent until then.
DEFAULT_ORCHESTRATOR_STATE_FILE: Path = Path(
    '/var/run/eclipse-obd/orchestrator-state.json',
)

# Rotation invariant: if newest CSV's mtime is older than this many
# seconds, the next BATTERY tick treats this as a fresh AC->BATTERY
# transition and opens a new file.  30s comfortably exceeds the 5s
# timer cadence + ~1s timer jitter; less than the typical operator
# AC-restoration -> AC-removal cycle so genuine drain runs do not
# rotate mid-stream.
DEFAULT_ROTATION_GAP_SECONDS: float = 30.0

FILENAME_PREFIX: str = 'drain-forensics-'
FILENAME_SUFFIX: str = '.csv'

# vcgencmd output parsing (shared by core/sdram_c/sdram_i/sdram_p reads).
_VCGENCMD_VOLTS_RE = re.compile(r'volt=([\d.]+)V')
_VCGENCMD_TEMP_RE = re.compile(r"temp=([\d.]+)'C")
_VCGENCMD_THROTTLED_RE = re.compile(r'throttled=(0x[0-9a-fA-F]+)')

_FILENAME_TS_FORMAT = '%Y%m%dT%H%M%SZ'
_ROW_TS_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


# ================================================================================
# Dependency-injection container
# ================================================================================


@dataclass
class ForensicsContext:
    """Container for the dependency-injected provider callables.

    Tests construct this with mocks; production main() wires the real
    I2C / vcgencmd / file readers via :func:`buildProductionContext`.
    Each provider is invoked at most once per :func:`runOnce` call.
    """

    logDir: Path
    powerSourceProvider: Callable[[], str]
    upsTelemetryProvider: Callable[[], dict]
    vcgencmdProvider: Callable[[], dict]
    loadAvgProvider: Callable[[], float]
    orchestratorStateProvider: Callable[[], dict]
    nowUtcIso: Callable[[], str]
    nowEpoch: Callable[[], float]
    rotationGapSeconds: float = DEFAULT_ROTATION_GAP_SECONDS


@dataclass
class RunResult:
    """Outcome of a single :func:`runOnce` invocation."""

    action: str  # 'no_op_external' | 'wrote_row'
    path: Path | None = None
    isNewFile: bool = False


# ================================================================================
# Entry point: runOnce
# ================================================================================


def runOnce(ctx: ForensicsContext) -> RunResult:
    """Single forensics tick.

    Returns immediately if the UPS is not on BATTERY.  Otherwise resolves
    the active CSV file (continuation vs rotation), composes a 14-column
    row from the injected providers, appends + fsyncs, and returns the
    write outcome.

    Args:
        ctx: Provider container.  See :class:`ForensicsContext`.

    Returns:
        :class:`RunResult` describing the action taken.  ``action`` is
        ``'no_op_external'`` when not on BATTERY, ``'wrote_row'`` after
        a successful append.
    """
    source = ctx.powerSourceProvider()
    if source != 'battery':
        return RunResult(action='no_op_external')

    activePath, isNewFile = _resolveActivePath(ctx)

    secondsOnBattery = _computeSecondsOnBattery(
        activePath=activePath,
        isNewFile=isNewFile,
        nowUtcIso=ctx.nowUtcIso(),
    )

    row = _composeRow(
        ctx=ctx,
        secondsOnBattery=secondsOnBattery,
    )

    _appendAndFsync(activePath, row, isNewFile=isNewFile)

    return RunResult(action='wrote_row', path=activePath, isNewFile=isNewFile)


# ================================================================================
# File lifecycle
# ================================================================================


def composeFilename(nowUtcIso: str) -> str:
    """Return the rotation-suffixed filename for a fresh AC->BATTERY transition.

    Args:
        nowUtcIso: Canonical wall-clock string ``YYYY-MM-DDTHH:MM:SSZ``.
            Stripped of separators and lowered to a filename-safe suffix.

    Returns:
        ``drain-forensics-YYYYMMDDTHHMMSSZ.csv``.
    """
    # Translate ``2026-05-02T03:14:00Z`` -> ``20260502T031400Z`` for the
    # filename suffix.  Re-parsing/re-formatting is overkill; a simple
    # regex strip on the canonical ISO string suffices.
    suffix = re.sub(r'[-:]', '', nowUtcIso)
    return f'{FILENAME_PREFIX}{suffix}{FILENAME_SUFFIX}'


def _resolveActivePath(
    ctx: ForensicsContext,
) -> tuple[Path, bool]:
    """Return ``(path, isNewFile)`` for the CSV to write to this tick.

    Continuation: if the newest existing ``drain-forensics-*.csv`` has
    an mtime within ``rotationGapSeconds`` of the current epoch, append
    to it.

    Rotation: otherwise (no existing file, or newest is stale), open a
    brand-new file named after the current ISO timestamp.
    """
    ctx.logDir.mkdir(parents=True, exist_ok=True)

    candidates = sorted(ctx.logDir.glob(f'{FILENAME_PREFIX}*{FILENAME_SUFFIX}'))
    nowEpoch = ctx.nowEpoch()

    if candidates:
        latest = candidates[-1]
        try:
            latestMtime = latest.stat().st_mtime
        except OSError as e:
            logger.warning(
                "Could not stat latest forensics CSV %s: %s -- rotating",
                latest, e,
            )
            latestMtime = None

        if latestMtime is not None:
            ageSeconds = nowEpoch - latestMtime
            if ageSeconds <= ctx.rotationGapSeconds:
                return latest, False

    freshName = composeFilename(ctx.nowUtcIso())
    return ctx.logDir / freshName, True


def _computeSecondsOnBattery(
    *,
    activePath: Path,
    isNewFile: bool,
    nowUtcIso: str,
) -> int:
    """Return ``now_utc - first_row_utc`` in whole seconds.

    For a brand-new file this is 0.  For a continuation, parse the first
    row's ``timestamp_utc`` and subtract from now.  Wall-clock based
    (canonical ISO) so the metric survives the systemd-timer fresh
    interpreter (no monotonic continuity).
    """
    if isNewFile:
        return 0

    try:
        firstTs = _readFirstRowTimestamp(activePath)
    except (OSError, ValueError, StopIteration) as e:
        logger.warning(
            "Could not parse first row of %s: %s -- emitting 0",
            activePath, e,
        )
        return 0

    try:
        first = datetime.strptime(firstTs, _ROW_TS_FORMAT).replace(tzinfo=UTC)
        now = datetime.strptime(nowUtcIso, _ROW_TS_FORMAT).replace(tzinfo=UTC)
    except ValueError as e:
        logger.warning(
            "ISO timestamp parse failed (first=%r now=%r): %s",
            firstTs, nowUtcIso, e,
        )
        return 0

    return max(0, int((now - first).total_seconds()))


def _readFirstRowTimestamp(path: Path) -> str:
    """Return the ``timestamp_utc`` of the first DATA row in a CSV file."""
    with path.open(newline='') as fp:
        reader = csv.DictReader(fp)
        first = next(reader)
    return first['timestamp_utc']


# ================================================================================
# Row composition + write
# ================================================================================


def _composeRow(
    *,
    ctx: ForensicsContext,
    secondsOnBattery: int,
) -> dict[str, str]:
    """Build the 14-column row dict from the injected providers."""
    ups = ctx.upsTelemetryProvider()
    vc = ctx.vcgencmdProvider()
    pd = ctx.orchestratorStateProvider()
    loadAvg = ctx.loadAvgProvider()
    nowIso = ctx.nowUtcIso()

    return {
        'timestamp_utc':       nowIso,
        'seconds_on_battery':  str(secondsOnBattery),
        'vcell_v':             _formatFloat(ups.get('vcell_v')),
        'soc_pct':             _formatInt(ups.get('soc_pct')),
        'crate_pct_per_hr':    _formatFloat(ups.get('crate_pct_per_hr')),
        'cpu_temp_c':          _formatFloat(vc.get('cpu_temp_c')),
        'core_v':              _formatFloat(vc.get('core_v')),
        'sdram_c_v':           _formatFloat(vc.get('sdram_c_v')),
        'sdram_i_v':           _formatFloat(vc.get('sdram_i_v')),
        'sdram_p_v':           _formatFloat(vc.get('sdram_p_v')),
        'throttled_hex':       str(vc.get('throttled_hex') or 'unknown'),
        'load_1min':           _formatFloat(loadAvg),
        'pd_stage':            str(pd.get('pd_stage') or 'unknown'),
        'pd_tick_count':       _formatInt(pd.get('pd_tick_count'), default='-1'),
    }


def _formatFloat(value: float | None, default: str = 'nan') -> str:
    """Format a numeric provider reading; fall back to a sentinel string.

    Empty cells are forbidden by the test contract (every column must be
    populated so a post-mortem reader can mechanically distinguish
    "missing reading" from "logger never wrote this column").
    """
    if value is None:
        return default
    try:
        return f'{float(value):.6g}'
    except (TypeError, ValueError):
        return default


def _formatInt(value: int | None, default: str = 'nan') -> str:
    if value is None:
        return default
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return default


def _appendAndFsync(
    path: Path,
    row: dict[str, str],
    *,
    isNewFile: bool,
) -> None:
    """Append a row to the CSV file, flush, and ``os.fsync`` the fd.

    The fsync is the load-bearing invariant of US-262: a hard-crash
    inside the 5s window between writes MUST NOT lose buffered rows.
    """
    mode = 'w' if isNewFile else 'a'
    with path.open(mode, newline='') as fp:
        writer = csv.DictWriter(fp, fieldnames=CSV_COLUMNS)
        if isNewFile:
            writer.writeheader()
        writer.writerow(row)
        fp.flush()
        os.fsync(fp.fileno())


# ================================================================================
# Production providers (wired into :func:`main`)
# ================================================================================


def _readPowerSourceFromVcell(vcell: float | None) -> str:
    """Decide BATTERY vs EXTERNAL from a single VCELL reading.

    drain_forensics is a fresh-interpreter-per-fire script -- no rolling
    history is available like UpsMonitor's full BATTERY-detection rule
    set.  The single-reading rule below is a *forensic-grade* proxy: a
    LiPo cell sustained <3.95V is overwhelmingly on battery (the X1209
    HAT's wall-fed float is ~4.10V).  False-BATTERY-during-AC writes
    near the boundary are negligible noise; the worst case is one
    extra row in the CSV during the AC-restoration grace window.
    """
    if vcell is None:
        return 'unknown'
    if vcell < 3.95:
        return 'battery'
    return 'external'


def _readUpsTelemetry() -> dict:
    """Read MAX17048 VCELL/SOC/CRATE on the deployed Pi.

    Imports lazily so non-Pi test hosts (Windows dev) can collect the
    test module without pulling smbus2.  Errors return ``None`` for the
    affected field rather than raising, so a flaky I2C read doesn't
    poison the whole row.
    """
    try:
        from src.pi.hardware.ups_monitor import UpsMonitor
    except Exception as e:  # noqa: BLE001
        logger.warning("UpsMonitor import failed: %s", e)
        return {'vcell_v': None, 'soc_pct': None, 'crate_pct_per_hr': None}

    monitor = UpsMonitor()
    try:
        try:
            vcell = monitor.getBatteryVoltage()
        except Exception as e:  # noqa: BLE001
            logger.warning("VCELL read failed: %s", e)
            vcell = None
        try:
            soc = monitor.getBatteryPercentage()
        except Exception as e:  # noqa: BLE001
            logger.warning("SOC read failed: %s", e)
            soc = None
        try:
            crate = monitor.getChargeRatePercentPerHour()
        except Exception as e:  # noqa: BLE001
            logger.warning("CRATE read failed: %s", e)
            crate = None
        return {
            'vcell_v': vcell,
            'soc_pct': soc,
            'crate_pct_per_hr': crate,
        }
    finally:
        monitor.close()


def _readVcgencmd() -> dict:
    """Read CPU temp + core/sdram volts + throttled_hex via vcgencmd."""
    return {
        'cpu_temp_c':    _vcgencmdNumeric(['measure_temp'], _VCGENCMD_TEMP_RE),
        'core_v':        _vcgencmdNumeric(
            ['measure_volts', 'core'], _VCGENCMD_VOLTS_RE,
        ),
        'sdram_c_v':     _vcgencmdNumeric(
            ['measure_volts', 'sdram_c'], _VCGENCMD_VOLTS_RE,
        ),
        'sdram_i_v':     _vcgencmdNumeric(
            ['measure_volts', 'sdram_i'], _VCGENCMD_VOLTS_RE,
        ),
        'sdram_p_v':     _vcgencmdNumeric(
            ['measure_volts', 'sdram_p'], _VCGENCMD_VOLTS_RE,
        ),
        'throttled_hex': _vcgencmdString(
            ['get_throttled'], _VCGENCMD_THROTTLED_RE,
        ),
    }


def _vcgencmdNumeric(args: list[str], pattern: re.Pattern) -> float | None:
    out = _runVcgencmd(args)
    if out is None:
        return None
    match = pattern.search(out)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _vcgencmdString(args: list[str], pattern: re.Pattern) -> str | None:
    out = _runVcgencmd(args)
    if out is None:
        return None
    match = pattern.search(out)
    return match.group(1) if match else None


def _runVcgencmd(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ['vcgencmd', *args],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.debug("vcgencmd %s unavailable: %s", args, e)
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _readLoadAvg() -> float:
    """Read /proc/loadavg first field (1-minute load).  0.0 on any error."""
    try:
        text = Path('/proc/loadavg').read_text(encoding='ascii')
    except OSError as e:
        logger.debug("/proc/loadavg unreadable: %s", e)
        return 0.0
    try:
        return float(text.split()[0])
    except (IndexError, ValueError):
        return 0.0


def _readOrchestratorState(statePath: Path) -> dict:
    """Best-effort read of the cross-process orchestrator state file.

    Future story will wire the orchestrator to write this file
    atomically on each tick.  Until then, the file is absent and we
    emit ``unknown`` / ``-1`` for the columns -- itself a diagnostic
    signal ("nobody wrote the orchestrator state").
    """
    if not statePath.exists():
        return {'pd_stage': 'unknown', 'pd_tick_count': -1}

    try:
        import json
        data = json.loads(statePath.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        logger.warning("Could not read orchestrator state %s: %s", statePath, e)
        return {'pd_stage': 'unknown', 'pd_tick_count': -1}

    return {
        'pd_stage': str(data.get('pd_stage', 'unknown')),
        'pd_tick_count': int(data.get('pd_tick_count', -1)),
    }


def _utcIsoNow() -> str:
    return datetime.now(UTC).strftime(_ROW_TS_FORMAT)


def _epochNow() -> float:
    # Wall-clock epoch -- matches mtime semantics so rotation comparisons
    # are consistent.
    import time as _time
    return _time.time()


def buildProductionContext(
    logDir: Path = DEFAULT_LOG_DIR,
    rotationGapSeconds: float = DEFAULT_ROTATION_GAP_SECONDS,
    orchestratorStateFile: Path = DEFAULT_ORCHESTRATOR_STATE_FILE,
) -> ForensicsContext:
    """Wire the production providers (real I2C / vcgencmd / files)."""

    def _powerSourceProvider() -> str:
        ups = _readUpsTelemetry()
        return _readPowerSourceFromVcell(ups['vcell_v'])

    def _orchestratorStateProvider() -> dict:
        return _readOrchestratorState(orchestratorStateFile)

    return ForensicsContext(
        logDir=logDir,
        powerSourceProvider=_powerSourceProvider,
        upsTelemetryProvider=_readUpsTelemetry,
        vcgencmdProvider=_readVcgencmd,
        loadAvgProvider=_readLoadAvg,
        orchestratorStateProvider=_orchestratorStateProvider,
        nowUtcIso=_utcIsoNow,
        nowEpoch=_epochNow,
        rotationGapSeconds=rotationGapSeconds,
    )


# ================================================================================
# CLI
# ================================================================================


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point invoked once per systemd-timer fire."""
    parser = argparse.ArgumentParser(
        description=(
            "Drain forensics logger -- writes one CSV row to "
            f"{DEFAULT_LOG_DIR}/drain-forensics-<TS>.csv when the UPS is "
            "on BATTERY.  Runs once per invocation; intended to be driven "
            "by a 5s systemd timer."
        ),
    )
    parser.add_argument(
        '--log-dir',
        type=Path,
        default=DEFAULT_LOG_DIR,
        help='Directory for drain-forensics-*.csv files.',
    )
    parser.add_argument(
        '--rotation-gap-seconds',
        type=float,
        default=DEFAULT_ROTATION_GAP_SECONDS,
        help=(
            'If the newest CSV mtime is older than this, rotate to a new '
            'file (treats the gap as an AC->BATTERY transition).'
        ),
    )
    parser.add_argument(
        '--orchestrator-state-file',
        type=Path,
        default=DEFAULT_ORCHESTRATOR_STATE_FILE,
        help='Path the production orchestratorStateProvider reads from.',
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable debug logging to stderr.',
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        stream=sys.stderr,
    )

    ctx = buildProductionContext(
        logDir=args.log_dir,
        rotationGapSeconds=args.rotation_gap_seconds,
        orchestratorStateFile=args.orchestrator_state_file,
    )

    try:
        result = runOnce(ctx)
    except Exception as e:  # noqa: BLE001
        logger.exception("drain_forensics runOnce raised: %s", e)
        return 1

    logger.info(
        "drain_forensics: %s%s%s",
        result.action,
        f' path={result.path}' if result.path else '',
        ' (new_file)' if result.isNewFile else '',
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
