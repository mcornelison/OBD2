#!/usr/bin/env python3
################################################################################
# File Name: pre_drive_greenlight.py
# Purpose/Description: US-479 (F-117) CIO-runnable pre-drive capture green-light
#                      probe. Opens ONE connection and runs the realtime logger
#                      concurrently with a KOEO/idle DTC read -- the exact A-17
#                      connect-edge -- then reports realtime_data row count +
#                      core-PID coverage and a final CAPTURE: PASS/FAIL + reason.
#                      Bench mode (SimulatedObdConnection) validates the logic
#                      off-Pi; a bench PASS is NOT a substitute for the live gate.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-20    | Rex (US-479) | Initial -- pre-drive green-light CLI over
#               |              | pi.obdii.pre_drive_gate.
# ================================================================================
################################################################################

"""Pre-drive OBD capture green-light probe (US-479 / F-117).

Thin CLI over :mod:`src.pi.obdii.pre_drive_gate`.  Composed by the CIO-runnable
``scripts/verify_pre_drive.sh`` wrapper as its live-window step, but also runnable
standalone:

    python3 scripts/pre_drive_greenlight.py --live --duration 30      # in-car
    python3 scripts/pre_drive_greenlight.py --live --koeo-only        # driveway
    python3 scripts/pre_drive_greenlight.py --bench                   # off-Pi

The probe writes to a DEDICATED database (``--db``, default a temp file), never
the production ``data/obd.db``, so a pre-drive check never contaminates real drive
data.  Exit 0 = CAPTURE PASS, 1 = CAPTURE FAIL, 2 = misuse.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# Resolve project paths relative to this script (mirror main.py / pi_smoke_test.py).
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
for _p in (str(SRC_DIR), str(PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_MISUSE = 2

DEFAULT_LIVE_DURATION = 30.0
DEFAULT_KOEO_DURATION = 5.0


def _parseArgs(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pre_drive_greenlight.py",
        description=(
            "Pre-drive OBD capture green-light: exercises the A-17 connect-edge "
            "(logger + KOEO DTC read on ONE connection) and reports CAPTURE: "
            "PASS/FAIL."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--live",
        action="store_true",
        help="Authoritative in-car mode: real ObdConnection (default).",
    )
    mode.add_argument(
        "--bench",
        action="store_true",
        help="Bench mode: SimulatedObdConnection. NOT a substitute for live.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help=f"Capture window seconds (default {DEFAULT_LIVE_DURATION:.0f} live, "
        f"{DEFAULT_KOEO_DURATION:.0f} koeo).",
    )
    parser.add_argument(
        "--koeo-only",
        action="store_true",
        help="Engine-off earliest signal: link + one read; skip row/coverage floors.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Dedicated SQLite path for the probe (default: a temp file). "
        "NEVER point this at production data/obd.db.",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=str(PROJECT_ROOT / "config.json"),
        help="Config path (live mode reads pi.bluetooth + pi.realtimeData).",
    )
    parser.add_argument(
        "--min-rows-per-sec",
        type=float,
        default=None,
        help="Override the rows/sec floor (default from pre_drive_gate).",
    )
    parser.add_argument(
        "--min-distinct-params",
        type=int,
        default=None,
        help="Override the core-PID coverage floor (default from pre_drive_gate).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan and exit without opening a connection.",
    )
    return parser.parse_args(argv)


def _benchConfig() -> dict:
    """A minimal config that logs the core PIDs (bench mode builds its own conn)."""
    from pi.obdii.pre_drive_gate import CORE_PIDS

    return {
        "pi": {
            "bluetooth": {},
            "realtimeData": {
                "pollingIntervalMs": 100,
                "parameters": [{"name": p, "logData": True} for p in CORE_PIDS],
            },
        }
    }


def _buildConnection(args: argparse.Namespace, config: dict):
    """Build the connection for the selected mode."""
    if args.bench:
        from pi.obdii.simulator.simulated_connection import SimulatedObdConnection

        return SimulatedObdConnection(connectionDelaySeconds=0.0, config=config)

    # Live: real ObdConnection from config.
    from pi.obdii.obd_connection import createConnectionFromConfig

    return createConnectionFromConfig(config, database=None, simulateFlag=False)


def main(argv: list[str] | None = None) -> int:
    args = _parseArgs(argv)

    from pi.obdii.pre_drive_gate import (
        DEFAULT_MIN_DISTINCT_PARAMS,
        DEFAULT_MIN_ROWS_PER_SEC,
        evaluateGate,
        requiredRows,
        runConnectEdgeCapture,
    )

    modeLabel = "bench" if args.bench else "live"
    duration = args.duration
    if duration is None:
        duration = DEFAULT_KOEO_DURATION if args.koeo_only else DEFAULT_LIVE_DURATION
    if duration < 1.0:
        print(f"ERROR: --duration must be >= 1 (got {duration})", file=sys.stderr)
        return EXIT_MISUSE

    minRowsPerSec = (
        args.min_rows_per_sec
        if args.min_rows_per_sec is not None
        else DEFAULT_MIN_ROWS_PER_SEC
    )
    minDistinctParams = (
        args.min_distinct_params
        if args.min_distinct_params is not None
        else DEFAULT_MIN_DISTINCT_PARAMS
    )
    minRows = 0 if args.koeo_only else requiredRows(duration, minRowsPerSec)

    dbPath = args.db or str(Path(tempfile.gettempdir()) / "pre_drive_greenlight.db")

    print("=" * 64)
    print(f" Pre-drive capture green-light ({modeLabel}"
          f"{', KOEO engine-off' if args.koeo_only else ''})")
    print("=" * 64)
    print(f"  duration           : {duration:.0f}s")
    print(f"  min rows           : {minRows}")
    print(f"  min core-PID cover : {'n/a (koeo)' if args.koeo_only else minDistinctParams}")
    print(f"  probe db           : {dbPath}")
    if args.bench:
        print("  NOTE: bench PASS is NOT a substitute for the live in-car gate.")

    if args.dry_run:
        print("\n[dry-run] no connection opened; plan only.")
        return EXIT_PASS

    config = _benchConfig() if args.bench else _loadLiveConfig(args.config)
    if config is None:
        return EXIT_MISUSE

    from pi.obdii.database import ObdDatabase

    database = ObdDatabase(dbPath)
    database.initialize()
    # Fresh window: clear any rows from a prior probe run in this temp db.
    _truncate(database)

    connection = _buildConnection(args, config)
    result = runConnectEdgeCapture(
        connection=connection,
        database=database,
        config=config,
        durationSec=duration,
        koeoOnly=args.koeo_only,
    )
    try:
        connection.disconnect()
    except Exception:  # noqa: BLE001 -- teardown best-effort
        pass

    verdict = evaluateGate(
        result,
        minRows=minRows,
        minDistinctParams=minDistinctParams,
        requireRows=not args.koeo_only,
    )

    print("")
    print(f"  rows written       : {result.rowsWritten}")
    print(f"  distinct core PIDs : {result.distinctParams}")
    print(f"  covered            : {', '.join(sorted(result.coveredParams)) or '(none)'}")
    print(f"  DTC reads          : {result.dtcReadCount}")
    print(f"  connect-edge       : {'exercised' if result.connectEdgeExercised else 'NOT exercised'}")
    interleave = (
        "yes (RACE)" if result.interleaveObserved is True
        else ("no" if result.interleaveObserved is False else "n/a (uninstrumented)")
    )
    print(f"  interleave         : {interleave}")
    if result.captureError:
        print(f"  capture error      : {result.captureError}")
    print("")
    print(f"CAPTURE: {verdict.reason}")

    return EXIT_PASS if verdict.passed else EXIT_FAIL


def _loadLiveConfig(configPath: str) -> dict | None:
    """Load + validate config.json for live mode."""
    from common.config.secrets_loader import loadConfigWithSecrets
    from common.config.validator import ConfigValidationError, ConfigValidator

    try:
        config = loadConfigWithSecrets(configPath)
        return ConfigValidator().validate(config)
    except FileNotFoundError:
        print(f"ERROR: config not found: {configPath}", file=sys.stderr)
        return None
    except ConfigValidationError as exc:
        print(f"ERROR: invalid config: {exc}", file=sys.stderr)
        return None


def _truncate(database) -> None:
    """Clear realtime_data in the dedicated probe db so each run is a fresh window."""
    try:
        with database.connect() as conn:
            conn.execute("DELETE FROM realtime_data")
    except Exception:  # noqa: BLE001 -- fresh db has nothing to clear
        pass


if __name__ == "__main__":
    sys.exit(main())
