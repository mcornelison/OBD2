"""ARCH-027: tests for GPS truth scoring.

🔴 These exist because the metric they replace had NO test and produced numbers
that looked like results. The first fusion bench regressed estimated pitch
against the accelerometer's own forward axis -- which on a tilted sensor IS
pitch -- and returned slopes of tens of degrees per g with signs that flipped
between estimators. Nothing caught it but eyeballing the output.

Truth must come from outside the system under test. Every function here takes
its truth from GPS or from OBD SPEED, neither of which any estimator consumes.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tools.imu.gps_truth import (
    GpsTrack,
    circularErrorDeg,
    distanceAndBearing,
    findClockOffset,
    gradeWindows,
    longitudinalAccelFromSpeed,
    scoreGrade,
    scoreHeading,
)


class TestDistanceAndBearing:
    def test_oneDegreeOfLatitudeIsAboutOneHundredAndElevenKm(self) -> None:
        distance, _ = distanceAndBearing(
            np.array([41.0]), np.array([-87.0]), np.array([42.0]), np.array([-87.0])
        )
        assert distance[0] == pytest.approx(111195.0, rel=0.01)

    def test_dueNorthIsZeroDegrees(self) -> None:
        _, bearing = distanceAndBearing(
            np.array([41.0]), np.array([-87.0]), np.array([41.1]), np.array([-87.0])
        )
        assert bearing[0] == pytest.approx(0.0, abs=0.1)

    def test_dueEastIsNinetyDegrees(self) -> None:
        _, bearing = distanceAndBearing(
            np.array([41.0]), np.array([-87.0]), np.array([41.0]), np.array([-86.9])
        )
        assert bearing[0] == pytest.approx(90.0, abs=0.1)

    def test_dueWestIsTwoSeventy(self) -> None:
        _, bearing = distanceAndBearing(
            np.array([41.0]), np.array([-87.0]), np.array([41.0]), np.array([-87.1])
        )
        assert bearing[0] == pytest.approx(270.0, abs=0.1)

    def test_zeroDistanceForIdenticalPoints(self) -> None:
        distance, _ = distanceAndBearing(
            np.array([41.0]), np.array([-87.0]), np.array([41.0]), np.array([-87.0])
        )
        assert distance[0] == pytest.approx(0.0, abs=1e-6)


class TestCircularErrorDeg:
    def test_smallDifference(self) -> None:
        assert circularErrorDeg(np.array([10.0]), np.array([5.0]))[0] == pytest.approx(5.0)

    def test_wrapsAcrossNorth(self) -> None:
        """359 vs 1 is 2 degrees apart, not 358."""
        assert circularErrorDeg(np.array([359.0]), np.array([1.0]))[0] == pytest.approx(-2.0)

    def test_oppositeIsOneEighty(self) -> None:
        assert abs(circularErrorDeg(np.array([0.0]), np.array([180.0]))[0]) == pytest.approx(180.0)

    def test_mirroredHeadingIsLargeError(self) -> None:
        """The A-30 signature: reading S while heading N."""
        assert abs(circularErrorDeg(np.array([184.0]), np.array([2.0]))[0]) == pytest.approx(178.0)


def _syntheticTrack(
    seconds: int = 120, speedMs: float = 15.0, climbPerSecond: float = 0.15
) -> GpsTrack:
    """A straight northward drive at constant speed and constant climb."""
    time = np.arange(seconds, dtype=float) + 1_700_000_000.0
    metresPerDegLat = 111195.0
    lat = 41.0 + (np.arange(seconds) * speedMs) / metresPerDegLat
    lon = np.full(seconds, -87.0)
    elevation = 200.0 + np.arange(seconds) * climbPerSecond

    span, bearing = distanceAndBearing(lat[:-2], lon[:-2], lat[2:], lon[2:])
    interval = time[2:] - time[:-2]
    stepDistance = distanceAndBearing(lat[:-1], lon[:-1], lat[1:], lon[1:])[0]
    return GpsTrack(
        time=time,
        lat=lat,
        lon=lon,
        elevation=elevation,
        courseTime=time[1:-1],
        speedMs=span / interval,
        courseDeg=bearing,
        cumulativeM=np.concatenate([[0.0], np.cumsum(stepDistance)]),
    )


class TestFindClockOffset:
    def test_recoversAKnownLag(self) -> None:
        track = _syntheticTrack()
        # OBD sees the same speed profile but its clock runs 3 s behind GPS.
        obdTime = track.courseTime - 3.0
        obdSpeed = track.speedMs * 3.6
        assert findClockOffset(track, obdTime, obdSpeed) == pytest.approx(3.0, abs=0.3)

    def test_zeroLagWhenAlreadyAligned(self) -> None:
        track = _syntheticTrack()
        assert findClockOffset(
            track, track.courseTime, track.speedMs * 3.6
        ) == pytest.approx(0.0, abs=0.3)


class TestGradeWindows:
    def test_recoversAKnownGrade(self) -> None:
        """15 m/s with 0.15 m/s of climb is a 1 % grade."""
        track = _syntheticTrack(seconds=180, speedMs=15.0, climbPerSecond=0.15)
        sampleTime = np.arange(track.time[0], track.time[-1], 0.05)
        estimated = np.full(len(sampleTime), 1.0)
        pairs = gradeWindows(track, sampleTime, estimated, clockOffsetS=0.0)
        assert len(pairs) >= 3
        assert pairs[0][0] == pytest.approx(1.0, abs=0.1)

    def test_discardsWindowsWithTooLittleTravel(self) -> None:
        """A parked car has no run, so rise/run is not a grade at any value."""
        track = _syntheticTrack(seconds=180, speedMs=0.2, climbPerSecond=0.15)
        sampleTime = np.arange(track.time[0], track.time[-1], 0.05)
        estimated = np.full(len(sampleTime), 1.0)
        assert gradeWindows(track, sampleTime, estimated, clockOffsetS=0.0) == []

    def test_skipsWindowsWhereTheEstimateIsAllNan(self) -> None:
        """A withheld pitch (gyro_implausible) must not score as zero grade."""
        track = _syntheticTrack(seconds=180)
        sampleTime = np.arange(track.time[0], track.time[-1], 0.05)
        estimated = np.full(len(sampleTime), np.nan)
        assert gradeWindows(track, sampleTime, estimated, clockOffsetS=0.0) == []


class TestScoreGrade:
    def test_perfectEstimatorScoresZeroError(self) -> None:
        pairs = [(1.0, 1.0), (2.0, 2.0), (-1.0, -1.0), (0.5, 0.5)]
        assert scoreGrade(pairs)["medianAbsErrorPoints"] == pytest.approx(0.0)

    def test_reportsErrorInGradePoints(self) -> None:
        pairs = [(1.0, 7.0), (2.0, 8.0), (0.0, 6.0), (1.0, 7.0)]
        assert scoreGrade(pairs)["medianAbsErrorPoints"] == pytest.approx(6.0)

    def test_tooFewWindowsReportsNan(self) -> None:
        assert math.isnan(scoreGrade([(1.0, 1.0)])["medianAbsErrorPoints"])


class TestScoreHeading:
    def test_perfectHeadingScoresNearZero(self) -> None:
        track = _syntheticTrack(seconds=120, speedMs=15.0)
        sampleTime = np.arange(track.courseTime[0], track.courseTime[-1], 0.05)
        truth = np.interp(sampleTime, track.courseTime, track.courseDeg)
        # Declination shifts magnetic from true; feed the magnetic equivalent.
        estimate = (truth - (-3.5)) % 360.0
        result = scoreHeading(track, sampleTime, estimate, clockOffsetS=0.0)
        assert result["medianAbsErrorDeg"] < 1.0
        assert result["within30DegPct"] == pytest.approx(100.0)

    def test_mirroredHeadingIsCaught(self) -> None:
        track = _syntheticTrack(seconds=120, speedMs=15.0)
        sampleTime = np.arange(track.courseTime[0], track.courseTime[-1], 0.05)
        truth = np.interp(sampleTime, track.courseTime, track.courseDeg)
        result = scoreHeading(track, sampleTime, (truth + 180.0) % 360.0, clockOffsetS=0.0)
        assert result["medianAbsErrorDeg"] > 90.0

    def test_stationaryDataIsExcludedByTheSpeedFloor(self) -> None:
        """Course over ground is noise at a standstill; scoring it is meaningless."""
        track = _syntheticTrack(seconds=120, speedMs=0.5)
        sampleTime = np.arange(track.courseTime[0], track.courseTime[-1], 0.05)
        result = scoreHeading(
            track, sampleTime, np.zeros(len(sampleTime)), clockOffsetS=0.0
        )
        assert math.isnan(result["medianAbsErrorDeg"])


class TestLongitudinalAccelFromSpeed:
    def test_constantSpeedGivesZeroAcceleration(self) -> None:
        speedTime = np.arange(60, dtype=float)
        speedKph = np.full(60, 50.0)
        out = longitudinalAccelFromSpeed(speedTime, speedKph, np.arange(10, 50, dtype=float))
        assert np.allclose(out, 0.0, atol=1e-9)

    def test_steadyAccelerationRecoversTheRate(self) -> None:
        """0 to 36 km/h (10 m/s) over 10 s is 1 m/s^2 = 0.102 g."""
        speedTime = np.arange(11, dtype=float)
        speedKph = np.arange(11, dtype=float) * 3.6
        out = longitudinalAccelFromSpeed(speedTime, speedKph, np.array([5.0]))
        assert out[0] == pytest.approx(1.0 / 9.80665, rel=0.01)

    def test_tooFewSpeedRowsReturnsNan(self) -> None:
        out = longitudinalAccelFromSpeed(
            np.array([0.0]), np.array([10.0]), np.array([0.0, 1.0])
        )
        assert np.all(np.isnan(out))

    def test_isIndependentOfAnyEstimator(self) -> None:
        """Contract note: this derives from OBD SPEED only. If it ever takes an
        accelerometer argument, the coupling metric becomes self-referential
        again -- which is the defect this module was written to fix."""
        import inspect

        params = set(inspect.signature(longitudinalAccelFromSpeed).parameters)
        assert params == {"speedTime", "speedKph", "sampleTime"}
