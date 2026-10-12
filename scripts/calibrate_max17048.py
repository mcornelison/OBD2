################################################################################
# File Name: calibrate_max17048.py
# Purpose/Description: Bench calibration tool for the MAX17048 fuel gauge
#                      (US-431 / F-048).  Samples the register SoC% (with VCELL
#                      and CRATE) at a fixed cadence from a cold power-up, logs
#                      every sample to a schema-free CSV, and measures how long
#                      the ModelGauge algorithm takes to SETTLE -- i.e. how long
#                      its ~30-40 point cold-start error persists (F-048).  That
#                      measured settle time is the real-data value that feeds the
#                      US-234/US-427 cold-start guard threshold
#                      (record_drain_test.COLD_START_CALIBRATION_WINDOW_SECONDS /
#                      the pi.hardware.upsMonitor.socColdStartWindowSeconds config
#                      key), replacing the guessed 180s constant.  Run it on the
#                      UPS-drain rig immediately after a cold power-up; write the
#                      printed recommendation into config.json.  Schema-free by
#                      design (AC: no battery_health_log change) -- unlike the
#                      original F-048 load_class='calibration' sketch.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ==============================================================================
# Date          | Author       | Description
# ==============================================================================
# 2026-07-02    | Rex (US-431) | Initial -- settling analysis + injected-clock
#                                sampler + CSV sink + recommendation print.
# ==============================================================================
################################################################################

"""MAX17048 SoC% cold-start calibration bench tool (US-431 / F-048).

The MAX17048 ModelGauge needs a few minutes of observation after a fresh
power-up before its SoC register is meaningful; Spool's drain tests
measured a 40-percentage-point gauge-vs-VCELL divergence during that
window (F-048).  US-234 moved the shutdown ladder off SoC onto VCELL, and
US-427 added an honest-instrument guard that records NULL for any register
read inside a ~180s cold-start window.  That 180s was a *guess*.

This tool measures the real settle time: sample the register from a cold
power-up, find the first moment the reading enters and holds a tolerance
band around its settled value, and print a margin-padded recommended
window.  The operator writes that number into
``pi.hardware.upsMonitor.socColdStartWindowSeconds`` (config.json), which
:mod:`scripts.record_drain_test` reads at runtime -- so the guard is fed
with data, not a guess.

Grounded defaults (all operator-overridable; see :func:`parseArguments`):

* ``--interval 5s`` -- matches ``UpsMonitor`` ``DEFAULT_POLL_INTERVAL`` and
  Spool's ``drain_log_simple.sh`` 5s cadence.
* ``--duration 600s`` (10 min) -- must run well past the current 180s guard
  (>=3x) to observe settling beyond it.
* ``--settle-tolerance 2pct`` -- the register reports integer percent
  (``getBatteryPercentage`` drops the fractional low byte), so +/-2% is
  "within 2 LSB" of the steady reading.
* ``--settle-window 30s`` -- "settled" means the reading holds in-band for
  at least 30s (>=6 samples at 5s), so one transient sample cannot declare
  a premature settle.
* margin 1.5 + round-up 10s -- pad the measured settle by 50% and round up
  to a 10s bucket for the recommended guard.

Usage::

    # On the rig, right after a cold power-up, with a known-full battery:
    python scripts/calibrate_max17048.py --reference-soc 100 \\
        --output calibrate_max17048.csv

    # Preview the run plan without touching the gauge:
    python scripts/calibrate_max17048.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Pi-tier entry-point path bootstrap (mirrors scripts/record_drain_test.py).
# src/ goes on sys.path so the `pi.*` imports resolve as the canonical form,
# and so a bare `python scripts/calibrate_max17048.py` does not die with
# `ModuleNotFoundError: No module named 'pi'` (US-397).  ROOT stays on the
# path too for the shared `common.*` modules.
# Convention: see [[feedback-path-convention-no-src-prefix]].
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pi.hardware.ups_monitor import UpsMonitor, UpsMonitorError  # noqa: E402

logger = logging.getLogger(__name__)

# Grounded defaults -- rationale in the module docstring.
DEFAULT_SAMPLE_INTERVAL_SECONDS: float = 5.0
DEFAULT_DURATION_SECONDS: float = 600.0
DEFAULT_SETTLE_TOLERANCE_PCT: float = 2.0
DEFAULT_SETTLE_WINDOW_SECONDS: float = 30.0
DEFAULT_MARGIN_FACTOR: float = 1.5
DEFAULT_ROUND_TO_SECONDS: float = 10.0
DEFAULT_OUTPUT_PATH: str = "calibrate_max17048.csv"

_CSV_HEADER: tuple[str, ...] = (
    "elapsed_seconds",
    "vcell_v",
    "soc_pct",
    "crate_pct_per_hr",
    "reference_soc_pct",
    "soc_error_pct",
)

__all__ = [
    "CalibrationSample",
    "SettlingResult",
    "analyzeSettling",
    "collectSamples",
    "main",
    "parseArguments",
    "recommendWindowSeconds",
    "run",
    "writeCsv",
]


# ==============================================================================
# Data model
# ==============================================================================


@dataclass
class CalibrationSample:
    """One timestamped gauge reading during a calibration run.

    A dropped read (gauge absent / I2C error) records ``None`` for the
    affected field rather than crashing the run -- the CSV keeps the row so
    the gap is visible.
    """

    elapsedSeconds: float
    vcellV: float | None
    socPct: int | None
    cratePctPerHr: float | None


@dataclass
class SettlingResult:
    """Outcome of the cold-start settling analysis.

    Attributes:
        settled: True only if the reading entered and held a tolerance band
            around its final value for at least the required dwell.
        settledAtSeconds: Elapsed seconds at which the sustained in-band run
            began, or ``None`` if it never settled confidently.
        finalSocPct: The settled (last valid) register reading, or ``None``.
        maxDeviationPct: Peak absolute divergence from ``finalSocPct`` across
            valid samples (the cold-start error magnitude), or ``None``.
        recommendedWindowSeconds: Margin-padded guard window derived from
            ``settledAtSeconds``, or ``None`` if it never settled.
        sampleCount: Number of valid (non-``None``) SoC samples analyzed.
    """

    settled: bool
    settledAtSeconds: float | None
    finalSocPct: int | None
    maxDeviationPct: float | None
    recommendedWindowSeconds: float | None
    sampleCount: int


# ==============================================================================
# Analysis (pure -- hardware-free, the value that feeds the guard)
# ==============================================================================


def recommendWindowSeconds(
    settledAtSeconds: float,
    *,
    marginFactor: float = DEFAULT_MARGIN_FACTOR,
    roundToSeconds: float = DEFAULT_ROUND_TO_SECONDS,
) -> float:
    """Pad a measured settle time and round it up to a guard-window bucket.

    Args:
        settledAtSeconds: The measured settle time in seconds.
        marginFactor: Multiplier applied for safety headroom (default 1.5).
        roundToSeconds: Bucket size the result is rounded up to (default 10).

    Returns:
        The recommended cold-start guard window in seconds.
    """
    padded = settledAtSeconds * marginFactor
    return float(math.ceil(padded / roundToSeconds) * roundToSeconds)


def analyzeSettling(
    samples: list[CalibrationSample],
    *,
    tolerancePct: float = DEFAULT_SETTLE_TOLERANCE_PCT,
    settleWindowSeconds: float = DEFAULT_SETTLE_WINDOW_SECONDS,
    marginFactor: float = DEFAULT_MARGIN_FACTOR,
    roundToSeconds: float = DEFAULT_ROUND_TO_SECONDS,
) -> SettlingResult:
    """Measure when the register SoC% settled during a calibration run.

    Settling is defined against the *final* valid reading: the earliest
    sample after which every subsequent valid reading stays within
    ``tolerancePct`` of that final value, provided the in-band tail lasts at
    least ``settleWindowSeconds``.  ``None`` (dropped) reads are skipped, not
    treated as excursions.

    Args:
        samples: The ordered calibration samples.
        tolerancePct: Half-width of the "settled" band around the final read.
        settleWindowSeconds: Minimum sustained in-band dwell to trust a settle.
        marginFactor: Safety multiplier for the recommendation.
        roundToSeconds: Rounding bucket for the recommendation.

    Returns:
        A :class:`SettlingResult` describing the settle point and the
        recommended guard window (both ``None`` if it never settled).
    """
    valid = [s for s in samples if s.socPct is not None]
    sampleCount = len(valid)
    if sampleCount < 2:
        finalSoc = valid[-1].socPct if valid else None
        return SettlingResult(
            settled=False,
            settledAtSeconds=None,
            finalSocPct=finalSoc,
            maxDeviationPct=None,
            recommendedWindowSeconds=None,
            sampleCount=sampleCount,
        )

    finalSoc = valid[-1].socPct
    assert finalSoc is not None  # narrowed by the filter above
    maxDeviation = max(abs(int(s.socPct) - finalSoc) for s in valid if s.socPct is not None)
    lastElapsed = valid[-1].elapsedSeconds

    # Walk back from the end while readings stay in-band; the earliest such
    # index is the start of the maximal in-band suffix ending at the last read.
    suffixStart = len(valid)
    for i in range(len(valid) - 1, -1, -1):
        soc = valid[i].socPct
        if soc is not None and abs(soc - finalSoc) <= tolerancePct:
            suffixStart = i
        else:
            break

    candidateElapsed = valid[suffixStart].elapsedSeconds
    dwell = lastElapsed - candidateElapsed
    if dwell >= settleWindowSeconds:
        return SettlingResult(
            settled=True,
            settledAtSeconds=candidateElapsed,
            finalSocPct=finalSoc,
            maxDeviationPct=float(maxDeviation),
            recommendedWindowSeconds=recommendWindowSeconds(
                candidateElapsed,
                marginFactor=marginFactor,
                roundToSeconds=roundToSeconds,
            ),
            sampleCount=sampleCount,
        )

    return SettlingResult(
        settled=False,
        settledAtSeconds=None,
        finalSocPct=finalSoc,
        maxDeviationPct=float(maxDeviation),
        recommendedWindowSeconds=None,
        sampleCount=sampleCount,
    )


# ==============================================================================
# Sampling (injected clock + sleep so the loop is testable off-Pi)
# ==============================================================================


def _safeRead(reader: Callable[[], Any]) -> Any:
    """Call a gauge reader, returning ``None`` on any UPS read failure.

    A calibration run on a dev box (no I2C) records ``None`` for that field
    instead of crashing -- the honest-instrument stance from US-234.
    """
    try:
        return reader()
    except UpsMonitorError as exc:
        logger.warning("gauge read failed -> None: %s", exc)
        return None


def _readSampleOnce(monitor: Any) -> tuple[float | None, int | None, float | None]:
    """Read (vcell, soc, crate) once, each guarded independently."""
    vcell = _safeRead(monitor.getBatteryVoltage)
    soc = _safeRead(monitor.getBatteryPercentage)
    crate = _safeRead(monitor.getChargeRatePercentPerHour)
    socInt = int(soc) if soc is not None else None
    return vcell, socInt, crate


def collectSamples(
    monitor: Any,
    *,
    durationSeconds: float,
    intervalSeconds: float,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> list[CalibrationSample]:
    """Sample the gauge at a fixed cadence for ``durationSeconds``.

    Args:
        monitor: A ``UpsMonitor``-like object.
        durationSeconds: Total run length; the last sample lands at ~duration.
        intervalSeconds: Cadence between samples.
        clock: Monotonic time source (injected for tests); default
            ``time.monotonic``.
        sleep: Sleep function (injected for tests); default ``time.sleep``.

    Returns:
        The ordered list of :class:`CalibrationSample`.
    """
    tick = clock or time.monotonic
    wait = sleep or time.sleep
    nSamples = max(1, int(round(durationSeconds / intervalSeconds)) + 1)

    start = tick()
    samples: list[CalibrationSample] = []
    for k in range(nSamples):
        vcell, soc, crate = _readSampleOnce(monitor)
        samples.append(
            CalibrationSample(
                elapsedSeconds=tick() - start,
                vcellV=vcell,
                socPct=soc,
                cratePctPerHr=crate,
            )
        )
        if k < nSamples - 1:
            wait(intervalSeconds)
    return samples


# ==============================================================================
# CSV sink (schema-free -- no battery_health_log change, AC)
# ==============================================================================


def _fmt(value: Any) -> str:
    """Render a value for CSV: empty string for ``None``, else ``str``."""
    return "" if value is None else str(value)


def writeCsv(
    samples: list[CalibrationSample],
    path: str,
    *,
    referenceSocPct: float | None = None,
) -> None:
    """Write calibration samples to CSV (Windows-safe ``newline=''``).

    Each row carries the raw reading plus, when ``referenceSocPct`` is given,
    the per-sample ``soc_error_pct`` (register minus reference) so the
    cold-start divergence is directly visible.
    """
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADER)
        for s in samples:
            if s.socPct is not None and referenceSocPct is not None:
                error = str(float(s.socPct) - float(referenceSocPct))
            else:
                error = ""
            writer.writerow(
                [
                    _fmt(s.elapsedSeconds),
                    _fmt(s.vcellV),
                    _fmt(s.socPct),
                    _fmt(s.cratePctPerHr),
                    _fmt(referenceSocPct),
                    error,
                ]
            )


# ==============================================================================
# CLI + orchestration
# ==============================================================================


def parseArguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the calibration tool.

    Args:
        argv: Optional argv slice for testing; defaults to ``sys.argv[1:]``.

    Returns:
        Populated ``argparse.Namespace``.
    """
    parser = argparse.ArgumentParser(
        prog="calibrate_max17048.py",
        description=(
            "Measure the MAX17048 cold-start settle time to feed the "  # b044-exempt: help prose
            "SoC%% guard window with real data (US-431 / F-048)."
        ),
    )
    parser.add_argument(
        "--duration", type=float, default=DEFAULT_DURATION_SECONDS,
        metavar="SECONDS",
        help=f"Total run length (default: {DEFAULT_DURATION_SECONDS:.0f}s).",
    )
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_SAMPLE_INTERVAL_SECONDS,
        metavar="SECONDS",
        help=f"Sample cadence (default: {DEFAULT_SAMPLE_INTERVAL_SECONDS:.0f}s).",
    )
    parser.add_argument(
        "--settle-tolerance", type=float, default=DEFAULT_SETTLE_TOLERANCE_PCT,
        metavar="PCT",
        help=(
            "Half-width of the settled band, in SoC%% points "
            f"(default: {DEFAULT_SETTLE_TOLERANCE_PCT:.0f})."
        ),
    )
    parser.add_argument(
        "--settle-window", type=float, default=DEFAULT_SETTLE_WINDOW_SECONDS,
        metavar="SECONDS",
        help=(
            "Minimum sustained in-band dwell to trust a settle "
            f"(default: {DEFAULT_SETTLE_WINDOW_SECONDS:.0f}s)."
        ),
    )
    parser.add_argument(
        "--reference-soc", type=float, default=None,
        metavar="PCT",
        help=(
            "Known reference SoC%% (e.g. 100 for a freshly-charged battery); "
            "logged per-sample as soc_error_pct."
        ),
    )
    parser.add_argument(
        "--output", "-o", default=DEFAULT_OUTPUT_PATH,
        metavar="PATH",
        help=f"CSV output path (default: {DEFAULT_OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the run plan and exit without touching the gauge.",
    )
    return parser.parse_args(argv)


def _printDryRunPlan(args: argparse.Namespace) -> None:
    """Print what a real run would do, without touching hardware."""
    nSamples = max(1, int(round(args.duration / args.interval)) + 1)
    print("DRY RUN -- MAX17048 SoC% calibration (no gauge access)")
    print("------------------------------------------------------")
    print(f"duration:         {args.duration:.0f}s")
    print(f"interval:         {args.interval:.0f}s")
    print(f"samples:          {nSamples}")
    print(f"settle tolerance: +/-{args.settle_tolerance:.0f} pct")
    print(f"settle window:    {args.settle_window:.0f}s")
    print(
        "reference soc:    "
        + (f"{args.reference_soc:.0f} pct" if args.reference_soc is not None else "(none)")
    )
    print(f"output csv:       {args.output}")


def _printSummary(result: SettlingResult, args: argparse.Namespace) -> None:
    """Print the calibration outcome + the value to write into config."""
    print()
    print("Calibration result")
    print("------------------")
    print(f"valid samples:    {result.sampleCount}")
    print(
        "final soc:        "
        + (f"{result.finalSocPct} pct" if result.finalSocPct is not None else "(no reads)")
    )
    print(
        "peak deviation:   "
        + (f"{result.maxDeviationPct:.0f} pct" if result.maxDeviationPct is not None else "n/a")
    )
    if result.settled:
        print(f"settled at:       {result.settledAtSeconds:.0f}s")
        print(f"Recommended cold-start window: {result.recommendedWindowSeconds:.0f}s")
        print(
            "  -> set pi.hardware.upsMonitor.socColdStartWindowSeconds "
            f"= {result.recommendedWindowSeconds:.0f} in config.json"
        )
    else:
        print("settled at:       DID NOT SETTLE")
        print(
            "Recommended cold-start window: (did not settle -- extend "
            "--duration or check the rig, then re-run)"
        )
    print()
    print(f"Samples logged to {args.output}.")


def run(
    args: argparse.Namespace,
    *,
    monitor: Any | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """Execute a calibration run end to end and return an exit code.

    Args:
        args: Parsed CLI namespace.
        monitor: Optional ``UpsMonitor``-like double (tests inject a fake);
            defaults to a real ``UpsMonitor``.
        clock: Optional monotonic clock (tests inject); default
            ``time.monotonic``.
        sleep: Optional sleep function (tests inject a no-op); default
            ``time.sleep``.

    Returns:
        ``0`` on success.
    """
    ups = monitor if monitor is not None else UpsMonitor()
    samples = collectSamples(
        ups,
        durationSeconds=args.duration,
        intervalSeconds=args.interval,
        clock=clock,
        sleep=sleep,
    )
    writeCsv(samples, args.output, referenceSocPct=args.reference_soc)
    result = analyzeSettling(
        samples,
        tolerancePct=args.settle_tolerance,
        settleWindowSeconds=args.settle_window,
    )
    _printSummary(result, args)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Optional argv slice for testing; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code (``0`` success).
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parseArguments(argv)
    if args.dry_run:
        _printDryRunPlan(args)
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
