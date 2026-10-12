"""ARCH-027: tests for the accelerometer scale/bias calibration.

WHY THIS IS CALIBRATABLE FROM A HAND ROTATION. Gravity's MAGNITUDE is 9.80665
m/s^2 whatever direction the sensor faces. So at rest, in any orientation, the
acceleration vector must land on a sphere of radius g centred on the sensor's
bias. Rotate through many orientations and that sphere is measurable -- the
centre is the per-axis bias, the radius is the scale error.

THE DEFECT THIS MEASURES. |a| reads 1.0184 g at rest (four independent readings
on 2026-09-15) against `DEFAULT_ACCEL_TRUST_BAND = 0.02`. Gravity correction is
therefore admitted with 0.002 of margin, and in-car readings of 1.020-1.021 g
fall outside it entirely -- so `pitch_fusion` stops trusting the accelerometer
exactly when it is most needed. 🔴 The fix is calibrating the scale, NEVER
widening the band: a wider band admits real acceleration as if it were gravity.

THE PRECONDITION. Only samples taken while the sensor is NOT being accelerated
are usable; during a hand rotation that means the pauses. Gyro magnitude is the
available proxy for "not being moved right now", so the filter gates on it.
"""

from __future__ import annotations

import math

import pytest

from pi.sensors.accel_cal import (
    STANDARD_GRAVITY_MS2,
    calibrateAccel,
    quasiStaticSamples,
)


def _spherePoints(
    center: tuple[float, float, float], radius: float, count: int = 300
) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    goldenAngle = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(count):
        z = 1.0 - (2.0 * i + 1.0) / count
        r = math.sqrt(max(0.0, 1.0 - z * z))
        theta = goldenAngle * i
        points.append(
            (
                center[0] + radius * r * math.cos(theta),
                center[1] + radius * r * math.sin(theta),
                center[2] + radius * z,
            )
        )
    return points


class TestQuasiStaticSamples:
    """A sample taken mid-swing measures motion, not gravity."""

    def test_keepsStillSamples(self) -> None:
        rows = [((0.0, 0.0, 9.8), (0.001, 0.002, 0.001))] * 10
        assert len(quasiStaticSamples(rows, maxGyroRadS=0.05)) == 10

    def test_dropsSamplesTakenWhileRotating(self) -> None:
        rows = [((0.0, 0.0, 9.8), (0.9, 0.1, 0.2))] * 10
        assert quasiStaticSamples(rows, maxGyroRadS=0.05) == []

    def test_keepsOnlyThePauses(self) -> None:
        still = ((0.1, 0.2, 9.8), (0.001, 0.001, 0.001))
        moving = ((3.0, 1.0, 9.0), (0.8, 0.4, 0.2))
        kept = quasiStaticSamples([still, moving, still, moving, still], maxGyroRadS=0.05)
        assert len(kept) == 3
        assert all(sample == still[0] for sample in kept)

    def test_returnsAccelVectorsOnly(self) -> None:
        kept = quasiStaticSamples([((1.0, 2.0, 3.0), (0.0, 0.0, 0.0))], maxGyroRadS=0.05)
        assert kept == [(1.0, 2.0, 3.0)]


class TestCalibrateAccel:
    def test_recoversBiasAndScaleFromACleanSphere(self) -> None:
        """A sensor reading 1.8 % high with a small bias."""
        measuredG = STANDARD_GRAVITY_MS2 * 1.018
        cal = calibrateAccel(_spherePoints((0.12, -0.08, 0.05), measuredG))

        assert cal.biasMs2[0] == pytest.approx(0.12, abs=0.01)
        assert cal.biasMs2[1] == pytest.approx(-0.08, abs=0.01)
        assert cal.biasMs2[2] == pytest.approx(0.05, abs=0.01)
        assert cal.measuredGMs2 == pytest.approx(measuredG, abs=0.01)

    def test_scaleFactorCorrectsTheMagnitude(self) -> None:
        """Applying the scale must bring |a| to 1.000 g, which is the point."""
        measuredG = STANDARD_GRAVITY_MS2 * 1.018
        cal = calibrateAccel(_spherePoints((0.0, 0.0, 0.0), measuredG))

        assert cal.scaleFactor == pytest.approx(1.0 / 1.018, abs=0.001)
        assert measuredG * cal.scaleFactor == pytest.approx(STANDARD_GRAVITY_MS2, abs=0.01)

    def test_aPerfectSensorNeedsNoCorrection(self) -> None:
        cal = calibrateAccel(_spherePoints((0.0, 0.0, 0.0), STANDARD_GRAVITY_MS2))
        assert cal.scaleFactor == pytest.approx(1.0, abs=0.001)
        assert cal.errorPercent == pytest.approx(0.0, abs=0.1)

    def test_reportsErrorAsAPercentage(self) -> None:
        cal = calibrateAccel(_spherePoints((0.0, 0.0, 0.0), STANDARD_GRAVITY_MS2 * 1.018))
        assert cal.errorPercent == pytest.approx(1.8, abs=0.1)

    def test_refusesDataThatDoesNotSpan3D(self) -> None:
        """A sensor sitting still samples ONE orientation. That is not a sphere,
        and a scale derived from it would be a guess dressed as a measurement.
        """
        oneOrientation = [(0.1, 0.2, 9.98)] * 200
        with pytest.raises(ValueError, match="span"):
            calibrateAccel(oneOrientation)

    def test_refusesTooFewSamples(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            calibrateAccel([(0.0, 0.0, 9.8), (0.0, 9.8, 0.0)])

    def test_reportsResidualSoTheFitCanBeJudged(self) -> None:
        cal = calibrateAccel(_spherePoints((0.0, 0.0, 0.0), STANDARD_GRAVITY_MS2))
        assert cal.residualRmsMs2 < 0.01

    def test_survivesRealisticNoise(self) -> None:
        points = _spherePoints((0.1, -0.05, 0.02), STANDARD_GRAVITY_MS2 * 1.018, count=600)
        noisy = [
            (x + 0.02 * math.sin(i), y + 0.02 * math.cos(i), z + 0.02 * math.sin(3 * i))
            for i, (x, y, z) in enumerate(points)
        ]
        cal = calibrateAccel(noisy)
        assert cal.errorPercent == pytest.approx(1.8, abs=0.3)


class TestTrustBandConsequence:
    """The calibration exists to move |a| back inside the fusion's trust band."""

    def test_uncorrectedReadingSitsAtTheBandEdge(self) -> None:
        """1.0184 g against a 0.02 band: inside by 0.0016, which is no margin."""
        measured = 1.0184
        assert abs(measured - 1.0) < 0.02
        assert abs(measured - 1.0) > 0.015

    def test_correctedReadingIsComfortablyInsideTheBand(self) -> None:
        cal = calibrateAccel(_spherePoints((0.0, 0.0, 0.0), STANDARD_GRAVITY_MS2 * 1.0184))
        correctedG = (STANDARD_GRAVITY_MS2 * 1.0184 * cal.scaleFactor) / STANDARD_GRAVITY_MS2
        assert abs(correctedG - 1.0) < 0.002
