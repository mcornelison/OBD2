################################################################################
# File Name: speed_aligner.py
# Purpose/Description: Derive the per-ECU multiplicative SPEED-PID correction
#                      factor by pairing an OBD SPEED series (km/h) with a GPS
#                      "source of truth" track (FIT). Two independent estimators:
#                      (A) distance-ratio = GPS distance / OBD-integrated distance
#                      -- clock-skew immune, the robust primary; (B) speed-ratio =
#                      median GPS/OBD over a cross-correlation-aligned, speed-
#                      filtered grid -- the diagnostic that also drives the
#                      scalar-vs-curve gate (is one constant factor even valid?).
#                      true_speed = OBD_speed x factor. Pure stdlib (no numpy).
# Author: Atlas (Architect)
# Creation Date: 2026-06-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Align OBD SPEED with GPS truth and estimate the SPEED-PID correction factor.

The factor is multiplicative: ``true_speed = OBD_speed * factor``.  Two
estimators are computed and cross-checked:

* **Distance-ratio (primary):** ``GPS_distance / OBD_integrated_distance``.
  Needs no time alignment -- each side integrates its own clock -- so it is
  immune to in-car NTP skew.  FIT supplies GPS cumulative distance directly.
* **Speed-ratio (diagnostic):** cross-correlate the two speed traces to find the
  clock lag, resample to a 1 Hz grid, take the median of ``GPS/OBD`` where both
  exceed a floor (low speed is noisy).  Binned by speed, it answers the
  scalar-vs-curve question: if the ratio drifts with speed, a single factor is
  the wrong model and the single-scalar schema is a B-076 finding.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median, pstdev

from src.calibration.fit_reader import FitTrack

KMH_PER_MPS = 3.6
MIN_SPEED_KMH_FOR_RATIO = 10.0  # below this, GPS+OBD instantaneous ratio is noise
RESAMPLE_STEP_S = 1.0
MAX_LAG_SEARCH_S = 60
SCALAR_CONSTANT_TOL = 0.15  # max (bin spread / overall median) to call it constant

ObdSample = tuple[datetime, float]  # (utc timestamp, km/h)
GpsSample = tuple[datetime, float]  # (utc timestamp, m/s)


@dataclass(frozen=True)
class CalibrationEstimate:
    """Result of pairing OBD SPEED with GPS truth.

    Attributes:
        distanceRatioScale: Estimator A -- GPS dist / OBD-integrated dist (primary).
        speedRatioScale: Estimator B -- median GPS/OBD over aligned moving samples.
        lagSeconds: Clock offset (s) found by cross-correlation (GPS vs OBD).
        obdDistanceM: OBD-integrated distance over the drive (m).
        gpsDistanceM: GPS cumulative distance (m).
        pairedSampleCount: Number of speed-filtered aligned samples used for B.
        ratioSpread: Population stdev of the per-sample GPS/OBD ratio (confidence).
        scalarIsConstant: scalar-vs-curve verdict -- is one factor valid?
        ratioBySpeedBin: Median ratio per OBD-speed bin (the curve evidence).
    """

    distanceRatioScale: float
    speedRatioScale: float
    lagSeconds: float
    obdDistanceM: float
    gpsDistanceM: float
    pairedSampleCount: int
    ratioSpread: float
    scalarIsConstant: bool
    ratioBySpeedBin: dict[str, float]


def loadObdSpeedCsv(path: str | os.PathLike[str]) -> list[ObdSample]:
    """Load an OBD SPEED fixture CSV (``ts,speed_kmh``) as a UTC-aware series."""
    out: list[ObdSample] = []
    with open(os.fspath(path), newline="") as f:
        for row in csv.DictReader(f):
            ts = datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            out.append((ts, float(row["speed_kmh"])))
    out.sort(key=lambda r: r[0])
    return out


def gpsSpeedSeries(track: FitTrack) -> list[GpsSample]:
    """Extract the (timestamp, m/s) speed series from a FIT track's GPS points."""
    return [
        (p.timestamp, p.speedMps)
        for p in track.gpsPoints
        if p.timestamp is not None and p.speedMps is not None
    ]


def integrateDistanceKm(samples: list[ObdSample]) -> float:
    """Trapezoidal integral of a km/h series over time -> kilometres."""
    total = 0.0
    for (t0, v0), (t1, v1) in zip(samples, samples[1:], strict=False):
        dtHours = (t1 - t0).total_seconds() / 3600.0
        total += (v0 + v1) / 2.0 * dtHours
    return total


def _resampleToGrid(
    samples: list[tuple[datetime, float]], t0: datetime, t1: datetime, step: float
) -> list[float]:
    """Linear-interpolate a (ts, value) series onto a uniform grid [t0, t1]."""
    times = [s[0] for s in samples]
    vals = [s[1] for s in samples]
    grid: list[float] = []
    j = 0
    steps = int((t1 - t0).total_seconds() // step)
    for k in range(steps + 1):
        gt = t0 + timedelta(seconds=k * step)
        while j + 1 < len(times) and times[j + 1] <= gt:
            j += 1
        if gt <= times[0]:
            grid.append(vals[0])
        elif gt >= times[-1]:
            grid.append(vals[-1])
        else:
            tA, tB = times[j], times[j + 1]
            frac = (gt - tA).total_seconds() / (tB - tA).total_seconds()
            grid.append(vals[j] + (vals[j + 1] - vals[j]) * frac)
    return grid


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation of two equal-length series (0 if degenerate)."""
    n = len(xs)
    if n == 0:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _bestLagSeconds(obdGrid: list[float], gpsGrid: list[float], maxLag: int) -> int:
    """Discrete cross-correlation: the GPS-vs-OBD lag (s) maximizing correlation."""
    bestLag, bestCorr = 0, -2.0
    n = len(obdGrid)
    for lag in range(-maxLag, maxLag + 1):
        xs, ys = [], []
        for i in range(n):
            j = i - lag
            if 0 <= j < n:
                xs.append(obdGrid[i])
                ys.append(gpsGrid[j])
        if len(xs) < n // 2:
            continue
        corr = _pearson(xs, ys)
        if corr > bestCorr:
            bestCorr, bestLag = corr, lag
    return bestLag


def estimateCalibration(
    obdSamples: list[ObdSample], gpsSamples: list[GpsSample], gpsDistanceM: float
) -> CalibrationEstimate:
    """Pair an OBD SPEED series with GPS truth and estimate the correction factor.

    Args:
        obdSamples: (utc, km/h) OBD SPEED series for the drive.
        gpsSamples: (utc, m/s) GPS speed series (e.g. from ``gpsSpeedSeries``).
        gpsDistanceM: GPS cumulative distance for the drive (m).

    Returns:
        A :class:`CalibrationEstimate` with both estimators + the curve gate.
    """
    # Estimator A -- distance-ratio (clock-skew immune).
    obdDistanceM = integrateDistanceKm(obdSamples) * 1000.0
    distanceRatioScale = gpsDistanceM / obdDistanceM if obdDistanceM else float("nan")

    # Resample both onto a 1 Hz grid over the overlap window (GPS in km/h).
    t0 = max(obdSamples[0][0], gpsSamples[0][0])
    t1 = min(obdSamples[-1][0], gpsSamples[-1][0])
    gpsKmh = [(ts, v * KMH_PER_MPS) for ts, v in gpsSamples]
    obdGrid = _resampleToGrid(obdSamples, t0, t1, RESAMPLE_STEP_S)
    gpsGrid = _resampleToGrid(gpsKmh, t0, t1, RESAMPLE_STEP_S)
    lag = _bestLagSeconds(obdGrid, gpsGrid, MAX_LAG_SEARCH_S)

    # Estimator B -- speed-ratio on the lag-aligned, speed-filtered grid.
    ratios, speeds = [], []
    n = len(obdGrid)
    for i in range(n):
        j = i - lag
        if 0 <= j < n:
            obd, gps = obdGrid[i], gpsGrid[j]
            if obd >= MIN_SPEED_KMH_FOR_RATIO and gps >= MIN_SPEED_KMH_FOR_RATIO:
                ratios.append(gps / obd)
                speeds.append(obd)
    speedRatioScale = median(ratios) if ratios else float("nan")
    ratioSpread = pstdev(ratios) if len(ratios) > 1 else 0.0

    # scalar-vs-curve: median ratio per OBD-speed bin.
    edges = [(10, 25), (25, 45), (45, 65), (65, 200)]
    labels = ["10-25", "25-45", "45-65", "65+"]
    binned: dict[str, list[float]] = {lbl: [] for lbl in labels}
    for r, s in zip(ratios, speeds, strict=True):
        for (lo, hi), lbl in zip(edges, labels, strict=True):
            if lo <= s < hi:
                binned[lbl].append(r)
                break
    ratioBySpeedBin = {lbl: median(v) for lbl, v in binned.items() if v}
    if len(ratioBySpeedBin) >= 2 and ratios:
        vals = list(ratioBySpeedBin.values())
        scalarIsConstant = (max(vals) - min(vals)) / median(ratios) <= SCALAR_CONSTANT_TOL
    else:
        scalarIsConstant = True  # insufficient speed range to refute a constant

    return CalibrationEstimate(
        distanceRatioScale=distanceRatioScale,
        speedRatioScale=speedRatioScale,
        lagSeconds=float(lag),
        obdDistanceM=obdDistanceM,
        gpsDistanceM=gpsDistanceM,
        pairedSampleCount=len(ratios),
        ratioSpread=ratioSpread,
        scalarIsConstant=scalarIsConstant,
        ratioBySpeedBin=ratioBySpeedBin,
    )
