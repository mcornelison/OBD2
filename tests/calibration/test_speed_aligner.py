################################################################################
# File Name: test_speed_aligner.py
# Purpose/Description: TDD tests for the SPEED-PID calibration aligner -- pairs an
#                      OBD SPEED series with a GPS (FIT) track and derives the
#                      multiplicative correction factor via two independent
#                      estimators (distance-ratio + speed-ratio) plus a
#                      scalar-vs-curve gate. Synthetic known-answer math tests +
#                      real drive-27 / strava-27c fixture tests (no mocks).
# Author: Atlas (Architect)
# Creation Date: 2026-06-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""TDD tests for ``src.calibration.speed_aligner``.

Real-fixture ground truth (drive-27 OBD ↔ strava-drive-27c GPS, spiked):
OBD avg 30.3 km/h, GPS avg 31.9 km/h, GPS distance 6421 m -> the correction
factor is ~1.0 (the new ECU reads ~true on this tune), NOT the ~0.5 that the
prior tune-state showed.  The real-data tests assert ~1.0 and explicitly NOT 0.5.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.calibration.fit_reader import readFit
from src.calibration.speed_aligner import (
    estimateCalibration,
    gpsSpeedSeries,
    integrateDistanceKm,
    loadObdSpeedCsv,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OBD_CSV = REPO_ROOT / "data" / "calibration" / "obd-drive-27-speed.csv"
GPS_FIT = REPO_ROOT / "data" / "calibration" / "strava-drive-27c.fit"


# ---- synthetic, known-answer math ----

def test_integrateDistanceKm_constantSpeed_exactDistance() -> None:
    """60 km/h held for exactly 1 hour integrates to 60 km."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    samples = [(t0 + timedelta(seconds=s), 60.0) for s in range(0, 3601, 10)]
    assert integrateDistanceKm(samples) == pytest.approx(60.0, abs=1e-6)


def test_estimateCalibration_obdReadsDouble_scaleIsHalf() -> None:
    """
    Given: a synthetic drive where OBD reads exactly 2x the GPS truth
    When:  estimateCalibration runs
    Then:  both estimators return ~0.5 (true = OBD x 0.5)
    """
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    obd, gps = [], []
    distM = 0.0
    prevKmh = None
    for s in range(0, 600):
        trueKmh = 40.0 + 20.0 * (1 if (s // 60) % 2 else -1) * (s % 60) / 60.0
        ts = t0 + timedelta(seconds=s)
        gps.append((ts, trueKmh / 3.6))          # m/s
        obd.append((ts, 2.0 * trueKmh))           # OBD reads double
        if prevKmh is not None:
            distM += (prevKmh + trueKmh) / 2.0 / 3.6  # trapezoid, 1s steps
        prevKmh = trueKmh
    est = estimateCalibration(obd, gps, distM)
    assert est.distanceRatioScale == pytest.approx(0.5, abs=0.02)
    assert est.speedRatioScale == pytest.approx(0.5, abs=0.02)


# ---- real fixtures: drive-27 OBD <-> strava-27c GPS ----

@pytest.fixture(scope="module")
def realEstimate():
    obd = loadObdSpeedCsv(OBD_CSV)
    track = readFit(GPS_FIT)
    return estimateCalibration(obd, gpsSpeedSeries(track), track.totalDistanceM)


def test_loadObdSpeedCsv_realFixture_parsesUtcAwareSeries() -> None:
    obd = loadObdSpeedCsv(OBD_CSV)
    assert len(obd) == 298
    assert all(ts.tzinfo == UTC for ts, _ in obd)
    assert obd == sorted(obd, key=lambda r: r[0])


def test_estimateCalibration_realDrive27_scaleNearOne_notHalf(realEstimate) -> None:
    """The headline finding: drive-27 reads ~true (~1.0), NOT the 0.5 seed."""
    assert 0.9 <= realEstimate.distanceRatioScale <= 1.15
    assert not (realEstimate.distanceRatioScale < 0.7)  # explicitly not ~0.5


def test_estimateCalibration_realDrive27_estimatorsAgree(realEstimate) -> None:
    """Distance-ratio and speed-ratio corroborate (within 0.15)."""
    assert abs(realEstimate.distanceRatioScale - realEstimate.speedRatioScale) < 0.15


def test_estimateCalibration_realDrive27_clockLagSmall(realEstimate) -> None:
    """Pi clock was NTP-synced in-car -> small alignment lag."""
    assert abs(realEstimate.lagSeconds) <= 60


def test_estimateCalibration_realDrive27_scalarIsConstant(realEstimate) -> None:
    """Ratio is ~flat across the speed range -> single-scalar model is valid."""
    assert realEstimate.scalarIsConstant is True
