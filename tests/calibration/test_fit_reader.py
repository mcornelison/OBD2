################################################################################
# File Name: test_fit_reader.py
# Purpose/Description: Tests for the Strava/Garmin FIT reader (offline SPEED-PID
#                      GPS-calibration tooling). Verifies extraction of the
#                      alignment-ready data (UTC timestamps, lat/lon degrees,
#                      ground speed m/s, cumulative distance, gps accuracy) from
#                      the REAL drive-27 Strava FIT files -- no synthetic
#                      fixtures (the FIT dialect's heterogeneous record shape is
#                      exactly what must be read correctly).
# Author: Atlas (Architect)
# Creation Date: 2026-06-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""TDD tests for ``src.calibration.fit_reader``.

Ground truth was established by spiking the real files:

* ``strava-drive-27a.fit`` -- 5722 records, 2861 GPS-position points,
  total distance 17378.5 m, span 21:18:37 -> 22:06:26 UTC (47:49 = 2869 s),
  lat 41.785..41.850, lon -87.882..-87.829 (Chicago), speed 0..23.110 m/s.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import pytest

from src.calibration.fit_reader import FitPoint, FitTrack, readFit

REPO_ROOT = Path(__file__).resolve().parents[2]
LEG_A = REPO_ROOT / "data" / "calibration" / "strava-drive-27a.fit"


@pytest.fixture(scope="module")
def trackA() -> FitTrack:
    """The parsed leg-A track (read once per module)."""
    return readFit(LEG_A)


def test_readFit_legA_returnsEveryRecordTimeOrdered(trackA: FitTrack) -> None:
    """
    Given: the real leg-A FIT file (5722 records)
    When:  readFit parses it
    Then:  every record is returned, in non-decreasing timestamp order
    """
    assert len(trackA.points) == 5722
    timestamps = [p.timestamp for p in trackA.points]
    assert timestamps == sorted(timestamps)


def test_readFit_legA_timestampsAreUtcAware(trackA: FitTrack) -> None:
    """
    Given: FIT timestamps are stored naive-UTC by the device
    When:  readFit parses them
    Then:  each point's timestamp is timezone-aware UTC (honest for alignment)
    """
    assert all(p.timestamp.tzinfo == UTC for p in trackA.points)


def test_readFit_legA_gpsPointsExcludeDistanceOnlyRecords(trackA: FitTrack) -> None:
    """
    Given: the FIT interleaves GPS-position records with distance-only records
    When:  gpsPoints filters to records carrying a fix
    Then:  exactly the 2861 position-bearing records remain, each with lat+lon
    """
    gps = trackA.gpsPoints
    assert len(gps) == 2861
    assert all(p.latDeg is not None and p.lonDeg is not None for p in gps)


def test_readFit_legA_semicirclesConvertedToChicagoDegrees(trackA: FitTrack) -> None:
    """
    Given: FIT stores position in int32 semicircles
    When:  readFit converts to degrees (value * 180 / 2**31)
    Then:  the first fix lands in the real Chicago bounding box, not raw ints
    """
    first = trackA.gpsPoints[0]
    assert 41.78 <= first.latDeg <= 41.85
    assert -87.89 <= first.lonDeg <= -87.82


def test_readFit_legA_totalDistanceMeters(trackA: FitTrack) -> None:
    """
    Given: cumulative distance is recorded in metres
    When:  totalDistanceM = last - first cumulative distance
    Then:  it matches the spiked ground truth (~17378.5 m)
    """
    assert trackA.totalDistanceM == pytest.approx(17378.5, abs=1.0)


def test_readFit_legA_speedIsMetersPerSecondNonNegative(trackA: FitTrack) -> None:
    """
    Given: FIT speed is m/s
    When:  readFit extracts speedMps on GPS points
    Then:  speeds are >= 0 and the max matches ground truth (~23.11 m/s)
    """
    speeds = [p.speedMps for p in trackA.gpsPoints if p.speedMps is not None]
    assert min(speeds) >= 0.0
    assert max(speeds) == pytest.approx(23.110, abs=0.01)


def test_readFit_legA_durationSeconds(trackA: FitTrack) -> None:
    """
    Given: leg A spans 21:18:37 -> 22:06:26 UTC
    When:  durationS = end - start
    Then:  it is 2869 seconds (47:49)
    """
    assert trackA.durationS == pytest.approx(2869, abs=1)


def test_FitTrack_emptyTrack_accessorsAreSafe() -> None:
    """
    Given: a degenerate (empty) track -- e.g. a truncated FIT
    When:  the convenience accessors are read
    Then:  they return neutral values instead of raising IndexError
    """
    empty = FitTrack(points=(), sourcePath="none.fit")
    assert empty.gpsPoints == []
    assert empty.startTime is None
    assert empty.endTime is None
    assert empty.durationS == 0.0
    assert empty.totalDistanceM == 0.0


def test_FitPoint_isImmutable() -> None:
    """A FitPoint is a frozen value object (safe to share across estimators)."""
    p = FitPoint(
        timestamp=None, latDeg=1.0, lonDeg=2.0, speedMps=3.0, distanceM=4.0, gpsAccuracyM=5.0
    )
    with pytest.raises(Exception):
        p.latDeg = 9.0  # type: ignore[misc]
