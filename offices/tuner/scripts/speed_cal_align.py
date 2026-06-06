################################################################################
# File Name: speed_cal_align.py
# Purpose/Description: SPEED-PID calibration aligner ("tool 2" per Atlas's GPS
#                      calibration procedure). Pairs the GPS source-of-truth (a
#                      FIT track, read via src/calibration/fit_reader.py) with the
#                      drive's OBD SPEED series and emits the multiplicative
#                      correction_factor (true = OBD x factor) via TWO estimators:
#                        A) distance-ratio  (primary; clock-skew immune)
#                        B) speed-ratio + scalar-vs-curve gate (diagnostic)
#                      Spool ratifies the final value before it is written.
# Author: Spool (Tuning SME)
# Creation Date: 2026-06-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-05    | Spool        | Initial -- operationalizes Atlas's procedure
#               |              | (offices/architect/findings/2026-06-01-speed-pid-
#               |              | gps-calibration-procedure.md) for drive 27.
# ================================================================================
################################################################################
"""Pure-python SPEED-PID aligner. No numpy. fitparse via Atlas's reader."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from statistics import median

sys.path.insert(0, 'src')
from calibration.fit_reader import readFit  # noqa: E402

FIT_PATH = 'data/calibration/strava-drive-27c.fit'
OBD_TSV = 'data/calibration/drive27_obd_speed.tsv'
LOW_SPEED_FLOOR_KMH = 20.0  # down-weight noisy/laggy low-speed GPS (Atlas Sec.3)
MS_TO_KMH = 3.6


def loadObd(path: str) -> list[tuple[datetime, float]]:
    """Parse the OBD SPEED TSV (timestamp<TAB>value_kmh) into UTC pairs."""
    out: list[tuple[datetime, float]] = []
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


def integrateDistanceM(series: list[tuple[datetime, float]]) -> float:
    """Trapezoidal integral of a (time, speed_kmh) series -> metres."""
    total = 0.0
    for (t0, v0), (t1, v1) in zip(series, series[1:]):
        dtH = (t1 - t0).total_seconds() / 3600.0
        total += ((v0 + v1) / 2.0) * dtH  # km
    return total * 1000.0


def resample1Hz(series: list[tuple[datetime, float]], t0: datetime, n: int) -> list[float]:
    """Nearest-hold resample to a 1 Hz grid of n samples starting at t0."""
    grid: list[float] = []
    j = 0
    for k in range(n):
        target = t0.timestamp() + k
        while j + 1 < len(series) and series[j + 1][0].timestamp() <= target:
            j += 1
        grid.append(series[j][1])
    return grid


def pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 3:
        return -2.0
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return num / (da * db) if da and db else -2.0


def main() -> None:
    track = readFit(FIT_PATH)
    gps = [(p.timestamp, (p.speedMps or 0.0) * MS_TO_KMH)
           for p in track.points if p.timestamp is not None and p.speedMps is not None]
    gps.sort(key=lambda r: r[0])
    obd = loadObd(OBD_TSV)

    print('=' * 70)
    print('SPEED-PID CALIBRATION ALIGNER  --  drive 27  (ECU MD326328)')
    print('=' * 70)
    print(f'GPS  : {len(track.points)} pts ({len(track.gpsPoints)} fixes), '
          f'{track.startTime} -> {track.endTime}, dur {track.durationS:.0f}s')
    print(f'       embedded totalDistance = {track.totalDistanceM:.1f} m '
          f'({track.totalDistanceM / 1000:.3f} km)')
    print(f'OBD  : {len(obd)} SPEED samples, {obd[0][0]} -> {obd[-1][0]}, '
          f'dur {(obd[-1][0]-obd[0][0]).total_seconds():.0f}s')

    # ---- Estimator A: distance-ratio (PRIMARY) ----
    gpsDistEmbedded = track.totalDistanceM
    gpsDistIntegrated = integrateDistanceM(gps) if gps else 0.0
    obdDist = integrateDistanceM(obd)
    print('\n--- Estimator A: DISTANCE-RATIO (primary, clock-skew immune) ---')
    print(f'GPS distance (embedded cumulative): {gpsDistEmbedded:8.1f} m')
    print(f'GPS distance (integrated speed)   : {gpsDistIntegrated:8.1f} m  (self-check)')
    print(f'OBD distance (integrated SPEED)   : {obdDist:8.1f} m')
    scaleA = gpsDistEmbedded / obdDist if obdDist else float('nan')
    scaleA_alt = gpsDistIntegrated / obdDist if obdDist else float('nan')
    print(f'>> scale_A (embedded GPS / OBD)    = {scaleA:.4f}')
    print(f'   scale_A (integrated GPS / OBD)  = {scaleA_alt:.4f}')

    # ---- Estimator B: speed-ratio + scalar-vs-curve gate ----
    print('\n--- Estimator B: SPEED-RATIO + scalar-vs-curve gate ---')
    # cross-correlate on 1 Hz grid to recover clock offset (lag in seconds).
    if gps and obd:
        t0 = max(gps[0][0], obd[0][0])
        t1 = min(gps[-1][0], obd[-1][0])
        span = int((t1 - t0).total_seconds())
        if span > 10:
            gGrid = resample1Hz(gps, t0, span)
            oGrid = resample1Hz(obd, t0, span)
            best = (-2.0, 0)
            for lag in range(-30, 31):
                if lag >= 0:
                    a, b = oGrid[lag:], gGrid[:span - lag]
                else:
                    a, b = oGrid[:span + lag], gGrid[-lag:]
                r = pearson(a, b)
                if r > best[0]:
                    best = (r, lag)
            corr, lag = best
            print(f'overlap span {span}s; best lag {lag:+d}s (corr {corr:.3f}) '
                  f'[+lag => GPS clock ahead of Pi clock]')
            # pair on aligned grid, ratio GPS/OBD where OBD above floor
            ratios: list[tuple[float, float]] = []  # (obd_kmh, ratio)
            for k in range(span):
                ko = k + lag if 0 <= k + lag < span else None
                if ko is None:
                    continue
                vo, vg = oGrid[ko], gGrid[k]
                if vo >= LOW_SPEED_FLOOR_KMH:
                    ratios.append((vo, vg / vo))
            if ratios:
                rs = [r for _, r in ratios]
                scaleB = median(rs)
                print(f'paired samples >= {LOW_SPEED_FLOOR_KMH:.0f} km/h OBD: {len(ratios)}')
                print(f'>> scale_B (median GPS/OBD)       = {scaleB:.4f}  '
                      f'(spread {min(rs):.3f}..{max(rs):.3f})')
                # scalar-vs-curve gate: median ratio per OBD-speed bin
                print('   scalar-vs-curve gate (median ratio by OBD speed bin):')
                bins = [(20, 40), (40, 60), (60, 80), (80, 200)]
                for lo, hi in bins:
                    br = [r for vo, r in ratios if lo <= vo < hi]
                    if br:
                        print(f'     OBD {lo:3d}-{hi:<3d} km/h: n={len(br):3d}  '
                              f'median ratio={median(br):.3f}')
                    else:
                        print(f'     OBD {lo:3d}-{hi:<3d} km/h: (no samples)')
            else:
                scaleB = float('nan')
                print('   no paired samples above low-speed floor (city loop too slow)')
        else:
            scaleB = float('nan')
            print('   overlap too short to cross-correlate')
    else:
        scaleB = float('nan')

    print('\n' + '=' * 70)
    print('SUMMARY')
    print(f'  Estimator A (distance-ratio, PRIMARY) : {scaleA:.4f}')
    print(f'  Estimator B (speed-ratio, diagnostic) : {scaleB:.4f}')
    print(f'  prior seed (gear-math estimate)       : 0.5000')
    print('=' * 70)


if __name__ == '__main__':
    main()
