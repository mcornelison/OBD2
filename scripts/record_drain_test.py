################################################################################
# File Name: record_drain_test.py
# Purpose/Description: CLI for CIO to record a UPS drain test into the Pi-side
#                      battery_health_log table (US-217).  Opens a drain event
#                      row with startDrainEvent, then immediately closes it
#                      with endDrainEvent so the row lands as a single unit.
#                      Intended for the monthly drain-test drill (CIO directive
#                      3 from Spool Session 6).  Follow this with
#                      ``python scripts/sync_now.py`` to push the row to the
#                      server.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-217) | Initial -- manual drain-event recorder.
# 2026-04-23    | Rex (US-224) | Flip --load-class default 'production' -> 'test'.
#                                Manual CLI invocation is typically a drill;
#                                orchestrator auto-writes real shutdowns as
#                                'production'.  Library LOAD_CLASS_DEFAULT stays
#                                'production' (US-216 auto-write path).
# ================================================================================
################################################################################

"""Manual drain-test recorder (US-217; US-224 default flip).

Usage::

    # Standard monthly drill -- load_class defaults to 'test'.
    python scripts/record_drain_test.py \\
        --start-soc 100 --end-soc 20 --runtime 1440

    # With ambient temperature + notes.
    python scripts/record_drain_test.py \\
        --start-soc 100 --end-soc 20 --runtime 1440 \\
        --ambient 22.5 --notes "April baseline drill"

    # Record a real production drain after the fact (opt-in to production).
    # This is rare -- US-216's Power-Down Orchestrator auto-writes real
    # shutdowns as load_class='production'.  Use this only when a real
    # drain event was NOT captured automatically.
    python scripts/record_drain_test.py \\
        --start-soc 95 --end-soc 18 --runtime 1320 --load-class production

    # Dry-run: prove the wiring without touching the DB.
    python scripts/record_drain_test.py --start-soc 100 --end-soc 20 \\
        --runtime 1440 --dry-run

Output (non-dry-run):

    Drain event recorded
    ---------------------
    drain_event_id: 3
    start_soc:      100.0
    end_soc:        20.0
    runtime_s:      1440 (24.0 min)
    load_class:     test
    ambient_c:      22.5
    notes:          April baseline drill

    Next step: run `python scripts/sync_now.py` to push to Chi-Srv-01.

Exit codes:
    * 0 -- success (event recorded or dry-run clean)
    * 1 -- config load failure OR DB error
    * 2 -- invalid CLI arguments (argparse-reported)

Invariant: this CLI is one-shot.  It opens AND closes the event on the
same invocation.  The async start/close path (open at wall-power-loss
warning, close at trigger poweroff) is US-216's scope.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common.config.secrets_loader import (  # noqa: E402
    loadConfigWithSecrets,
    loadEnvFile,
)
from src.common.config.validator import (  # noqa: E402
    ConfigValidationError,
    ConfigValidator,
)
from src.common.errors.handler import ConfigurationError  # noqa: E402
from src.pi.obdii.database import initializeDatabase  # noqa: E402
from src.pi.power.battery_health import (  # noqa: E402
    LOAD_CLASS_VALUES,
    BatteryHealthRecorder,
)

logger = logging.getLogger(__name__)

# US-224: CLI-specific default diverges from the library LOAD_CLASS_DEFAULT.
# Manual CLI invocation is almost always a CIO-driven drill, so 'test' is the
# safe default that keeps test rows out of the production baseline.  The
# library-level LOAD_CLASS_DEFAULT stays 'production' -- that feeds US-216's
# Power-Down Orchestrator auto-write path for real shutdowns.
CLI_DEFAULT_LOAD_CLASS: str = 'test'

__all__ = ['CLI_DEFAULT_LOAD_CLASS', 'main', 'parseArguments']


# ==============================================================================
# CLI parsing
# ==============================================================================


def parseArguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the drain-test recorder.

    Args:
        argv: Optional argv slice for testing; defaults to ``sys.argv[1:]``.

    Returns:
        Populated ``argparse.Namespace``.
    """
    parser = argparse.ArgumentParser(
        prog='record_drain_test.py',
        description=(
            'Record a UPS drain-test event in the Pi '  # b044-exempt: argparse help prose
            'battery_health_log table (US-217).'
        ),
    )
    parser.add_argument(
        '--start-soc', type=float, required=True,
        metavar='PCT',
        help='SOC %% at event start (e.g. 100 for a fully-charged drill).',
    )
    parser.add_argument(
        '--end-soc', type=float, required=True,
        metavar='PCT',
        help='SOC %% at event end (e.g. 20 for trigger threshold).',
    )
    parser.add_argument(
        '--runtime', type=int,
        default=None,
        metavar='SECONDS',
        help=(
            'Override computed runtime_seconds.  Normally the recorder '
            'uses wall-clock delta between start + end timestamps; since '
            'this CLI opens AND closes in the same invocation, wall-clock '
            'delta is near-zero.  Pass the observed drain duration here.'
        ),
    )
    parser.add_argument(
        '--load-class',
        choices=LOAD_CLASS_VALUES,
        default=CLI_DEFAULT_LOAD_CLASS,
        help=(
            f'Drain-event class (default: {CLI_DEFAULT_LOAD_CLASS}).  '
            "'test' is the default because manual CLI invocation is "
            'typically a drill; pass --load-class production only for '
            'rare manual recording of a real drain event not captured '
            "by US-216's Power-Down Orchestrator auto-write."
        ),
    )
    parser.add_argument(
        '--ambient', type=float,
        default=None,
        metavar='CELSIUS',
        help='Ambient temperature in Celsius (optional).',
    )
    parser.add_argument(
        '--notes',
        default=None,
        metavar='TEXT',
        help='Free-form notes (drill context, weather, hardware).',
    )
    parser.add_argument(
        '--config', '-c',
        default='config.json',
        metavar='PATH',
        help='Path to config.json (default: ./config.json).',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate args + load config but do NOT write to the DB.',
    )
    return parser.parse_args(argv)


# ==============================================================================
# Config loading (mirrors scripts/sync_now.py)
# ==============================================================================


def _loadConfig(configPath: str) -> dict[str, Any]:
    """Load + validate a Pi config, raising with a clear operator message."""
    loadEnvFile('.env')

    if not Path(configPath).exists():
        raise ConfigurationError(
            f'config file not found: {configPath}',
            {'configPath': configPath},
        )

    try:
        raw = loadConfigWithSecrets(configPath)
        validated: dict[str, Any] = ConfigValidator().validate(raw)
    except ConfigValidationError as exc:
        raise ConfigurationError(
            f'config validation failed: {exc}',
            {'configPath': configPath},
        ) from exc
    return validated


# ==============================================================================
# Core flow
# ==============================================================================


def _printResult(
    *,
    drainEventId: int,
    startSoc: float,
    endSoc: float,
    runtimeSeconds: int | None,
    loadClass: str,
    ambientC: float | None,
    notes: str | None,
) -> None:
    """Pretty-print the recorded event to stdout."""
    runtimeMin = (
        f'{runtimeSeconds} ({runtimeSeconds / 60.0:.1f} min)'
        if runtimeSeconds is not None else 'n/a'
    )
    print('Drain event recorded')
    print('---------------------')
    print(f'drain_event_id: {drainEventId}')
    print(f'start_soc:      {startSoc}')
    print(f'end_soc:        {endSoc}')
    print(f'runtime_s:      {runtimeMin}')
    print(f'load_class:     {loadClass}')
    print(f'ambient_c:      {ambientC if ambientC is not None else "n/a"}')
    print(f'notes:          {notes if notes is not None else "(none)"}')
    print()
    print('Next step: run `python scripts/sync_now.py` to push to Chi-Srv-01.')  # b044-exempt: operator-facing display name


def _overrideRuntimeSeconds(
    database: Any,
    drainEventId: int,
    runtimeSeconds: int,
) -> None:
    """Replace the auto-computed runtime_seconds with an operator-supplied value.

    The recorder's :meth:`endDrainEvent` computes runtime from the
    wall-clock delta between start + end timestamps.  In this CLI both
    endpoints happen in the same invocation so the computed delta is
    ~0s.  The CIO supplies the real observed drain duration via
    ``--runtime``; we UPDATE the row directly with that value.
    """
    with database.connect() as conn:
        conn.execute(
            'UPDATE battery_health_log SET runtime_seconds = ? '
            'WHERE drain_event_id = ?',
            (int(runtimeSeconds), int(drainEventId)),
        )


def _recordEvent(
    config: dict[str, Any],
    args: argparse.Namespace,
) -> int:
    """Open + close a drain event and return its ``drain_event_id``."""
    database = initializeDatabase(config)
    recorder = BatteryHealthRecorder(database=database)

    drainEventId = recorder.startDrainEvent(
        startSoc=args.start_soc,
        loadClass=args.load_class,
        notes=args.notes,
        dataSource='real',
    )
    closeResult = recorder.endDrainEvent(
        drainEventId=drainEventId,
        endSoc=args.end_soc,
        ambientTempC=args.ambient,
    )

    runtimeSeconds = closeResult.runtimeSeconds
    if args.runtime is not None:
        _overrideRuntimeSeconds(database, drainEventId, args.runtime)
        runtimeSeconds = args.runtime

    _printResult(
        drainEventId=drainEventId,
        startSoc=args.start_soc,
        endSoc=args.end_soc,
        runtimeSeconds=runtimeSeconds,
        loadClass=args.load_class,
        ambientC=args.ambient,
        notes=args.notes,
    )
    return drainEventId


# ==============================================================================
# Main entry point
# ==============================================================================


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argv slice for testing; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code (0 on success, 1 on operator-visible error).
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    args = parseArguments(argv)

    try:
        config = _loadConfig(args.config)
    except ConfigurationError as exc:
        logger.error('config load failed: %s', exc)
        return 1

    if args.dry_run:
        print('DRY RUN -- no DB write')
        print(f'  start_soc:   {args.start_soc}')
        print(f'  end_soc:     {args.end_soc}')
        print(f'  runtime:     {args.runtime}')
        print(f'  load_class:  {args.load_class}')
        print(f'  ambient:     {args.ambient}')
        print(f'  notes:       {args.notes}')
        return 0

    try:
        _recordEvent(config, args)
    except Exception as exc:  # noqa: BLE001 -- CLI surface
        logger.exception('record_drain_test failed: %s', exc)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
