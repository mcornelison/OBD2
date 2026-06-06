################################################################################
# File Name: speed_aligner-spool.py
# Purpose/Description: SPEED-PID calibration aligner -- SPOOL CROSS-CHECK VARIANT,
#                      independent of Atlas's speed_aligner.py. Same two estimators
#                      (A distance-ratio primary, B speed-ratio + scalar-vs-curve
#                      gate) but a different resampling method (nearest-hold vs
#                      Atlas's linear-interp), kept deliberately so the two
#                      implementations validate each other. On drive 27 both agree:
#                      A=1.0037 (both), B=0.9875 (Spool) / 0.9889 (Atlas), scalar
#                      gate flat -> ratified correction_factor = 1.00.
#                      true_speed = OBD_speed x factor. Pure stdlib (no numpy).
# Author: Spool (Tuning SME)   [method/data-flow: Atlas; ratified value: Spool]
# Creation Date: 2026-06-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-05    | Spool        | Initial -- operationalizes Atlas's GPS-cal
#               |              | procedure as an independent cross-check aligner.
#               |              | Promoted from offices/tuner/scripts/ per CIO.
# ================================================================================
################################################################################
"""Spool cross-check SPEED-PID aligner (nearest-hold resampling, no numpy).

Run as a script (hyphenated filename is intentionally not import-safe -- this is
a standalone cross-check tool, not a library; Atlas's speed_aligner.py is the
importable production module):

    python src/calibration/speed_aligner-spool.py <fit_path> <obd_speed_tsv>
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median

sys.path.insert(0, os.path.dirname(__file__))
from fit_reader import FitTrack, readFit  # type: ignore[import-not-found]  # noqa: E402

MS_TO_KMH = 3.6
DEFAULT_LOW_SPEED_FLOOR_KMH = 20.0   # GPS instantaneous speed is noisy at crawl
SCALAR_FLAT_TOLERANCE = 0.10         # per-bin median spread to call the scalar valid
MAX_LAG_SECONDS = 30                 # cross-correlation clock-offset search window

ObdSeries = list[tuple[datetime, float]]  # (utc_time, speed_kmh)


@dataclass(frozen=True)
class SpeedCalibrationEstimate:
    """Result of pairing a GPS track with an OBD SPEED series.

    Attributes:
        scaleDistanceRatio: Estimator A -- GPS dist / OBD-integrated dist (primary,
            clock-skew immune; this is the value to ratify).
        scaleSpeedRatioMedian: Estimator B -- median per-sample GPS/OBD ratio.
        lagSeconds: Recovered clock offset (+ve => GPS clock ahead of Pi).
        correlation: Peak cross-correlation of the speed traces at lagSeconds.
        binRatios: Median GPS/OBD ratio per OBD-speed bin (scalar-vs-curve gate).
        scalarIsFlat: True if bins agree within SCALAR_FLAT_TOLERANCE.
        gpsDistanceM / obdDistanceM: Window distances behind Estimator A.
        pairedSampleCount: Samples above the low-speed floor used for Estimator B.
    """

    scaleDistanceRatio: float
    scaleSpeedRatioMedian: float
    lagSeconds: int
    correlation: float
    binRatios: dict[str, float]
    scalarIsFlat: bool
    gpsDistanceM: float
    obdDistanceM: float
    pairedSampleCount: int


def loadObdSpeedTsv(path: str) -> ObdSeries:
    """Load an OBD SPEED export (``timestamp<TAB>value_kmh`` + header) as UTC pairs."""
    out: ObdSeries = []
    with open(path, encoding='utf-8') as fh:
        next(fh)  # header
        for line in fh:
            line = line.strip()
            if not line:
                continue
            ts, val = line.split('\t')
            dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            out.append((dt, float(val)))
    out.sort(key=lambda r: r[0])
    return out


def integrateDistanceMeters(series: ObdSeries) -> float:
    """Trapezoidal integral of a (time, speed_kmh) series -> metres."""
    total = 0.0
    for (t0, v0), (t1, v1) in zip(series, series[1:]):
        deltaHours = (t1 - t0).total_seconds() / 3600.0
        total += ((v0 + v1) / 2.0) * deltaHours  # km
    return total * 1000.0


def _resample1Hz(series: ObdSeries, t0: datetime, n: int) -> list[float]:
    """Nearest-hold resample to an n-sample 1 Hz grid starting at t0."""
    grid: list[float] = []
    j = 0
    for k in range(n):
        target = t0.timestamp() + k
        while j + 1 < len(series) and series[j + 1][0].timestamp() <= target:
            j += 1
        grid.append(series[j][1])
    return grid


def _pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 3:
        return -2.0
    meanA, meanB = sum(a) / n, sum(b) / n
    num = sum((x - meanA) * (y - meanB) for x, y in zip(a, b))
    denomA = sum((x - meanA) ** 2 for x in a) ** 0.5
    denomB = sum((y - meanB) ** 2 for y in b) ** 0.5
    return num / (denomA * denomB) if denomA and denomB else -2.0


def estimateCorrectionFactor(
    track: FitTrack,
    obd: ObdSeries,
    *,
    lowSpeedFloorKmh: float = DEFAULT_LOW_SPEED_FLOOR_KMH,
) -> SpeedCalibrationEstimate:
    """Estimate the SPEED correction_factor from a GPS track + OBD SPEED series."""
    gps = [(p.timestamp, (p.speedMps or 0.0) * MS_TO_KMH)
           for p in track.points if p.timestamp is not None and p.speedMps is not None]
    gps.sort(key=lambda r: r[0])

    gpsDistance = track.totalDistanceM
    obdDistance = integrateDistanceMeters(obd)
    scaleA = gpsDistance / obdDistance if obdDistance else float('nan')

    scaleB = float('nan')
    lag, corr, paired = 0, -2.0, 0
    binRatios: dict[str, float] = {}
    if gps and obd:
        t0 = max(gps[0][0], obd[0][0])
        t1 = min(gps[-1][0], obd[-1][0])
        span = int((t1 - t0).total_seconds())
        if span > 10:
            gGrid = _resample1Hz(gps, t0, span)
            oGrid = _resample1Hz(obd, t0, span)
            for trialLag in range(-MAX_LAG_SECONDS, MAX_LAG_SECONDS + 1):
                if trialLag >= 0:
                    a, b = oGrid[trialLag:], gGrid[:span - trialLag]
                else:
                    a, b = oGrid[:span + trialLag], gGrid[-trialLag:]
                r = _pearson(a, b)
                if r > corr:
                    corr, lag = r, trialLag
            ratios: list[tuple[float, float]] = []
            for k in range(span):
                ko = k + lag
                if 0 <= ko < span and oGrid[ko] >= lowSpeedFloorKmh:
                    ratios.append((oGrid[ko], gGrid[k] / oGrid[ko]))
            paired = len(ratios)
            if ratios:
                scaleB = median(r for _, r in ratios)
                for lo, hi in ((20, 40), (40, 60), (60, 80), (80, 200)):
                    chunk = [r for vo, r in ratios if lo <= vo < hi]
                    if chunk:
                        binRatios[f'{lo}-{hi}'] = median(chunk)

    flat = (max(binRatios.values()) - min(binRatios.values()) < SCALAR_FLAT_TOLERANCE
            if len(binRatios) >= 2 else True)

    return SpeedCalibrationEstimate(
        scaleDistanceRatio=scaleA,
        scaleSpeedRatioMedian=scaleB,
        lagSeconds=lag,
        correlation=corr,
        binRatios=binRatios,
        scalarIsFlat=flat,
        gpsDistanceM=gpsDistance,
        obdDistanceM=obdDistance,
        pairedSampleCount=paired,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: ``speed_aligner-spool.py <fit_path> <obd_speed_tsv>`` -> prints the estimate."""
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        print('usage: speed_aligner-spool.py <fit_path> <obd_speed_tsv>')
        return 2
    track = readFit(args[0])
    obd = loadObdSpeedTsv(args[1])
    est = estimateCorrectionFactor(track, obd)
    print(f'GPS distance      : {est.gpsDistanceM:8.1f} m')
    print(f'OBD distance      : {est.obdDistanceM:8.1f} m')
    print(f'Estimator A (dist): {est.scaleDistanceRatio:.4f}   <- ratify this')
    print(f'Estimator B (spd) : {est.scaleSpeedRatioMedian:.4f}  '
          f'(lag {est.lagSeconds:+d}s, corr {est.correlation:.3f}, n={est.pairedSampleCount})')
    print(f'scalar-vs-curve   : {"FLAT (single scalar valid)" if est.scalarIsFlat else "VARIES -> B-076"}')
    for label, ratio in est.binRatios.items():
        print(f'  OBD {label} km/h: median ratio {ratio:.3f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
