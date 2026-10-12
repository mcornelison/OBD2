"""ARCH-027: pin the unit conversion and frame map used by the fusion comparison.

🔴 WHY THIS EXISTS. `imufusion` takes gyro in deg/s and accel in g; our data is
rad/s and m/s^2. A units error does not crash -- it produces a confident,
plausible, WRONG comparison, and a wrong comparison would be used to choose a
filter. This project has already paid for that shape of error more than once.

The frame map is tested here too because the comparison is meaningless if the
estimators are fed different axes than the shipped filter uses.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tools.imu.fusion_bench import Calibration, frameB, toImufusionUnits

STANDARD_GRAVITY_MS2 = 9.80665


class TestUnitConversion:
    def test_gyroRadiansPerSecondBecomeDegreesPerSecond(self) -> None:
        gyro = np.array([[math.pi, 0.0, 0.0]])
        converted, _ = toImufusionUnits(gyro, np.zeros((1, 3)))
        assert converted[0][0] == pytest.approx(180.0)

    def test_accelMetresPerSecondSquaredBecomeG(self) -> None:
        accel = np.array([[0.0, 0.0, STANDARD_GRAVITY_MS2]])
        _, converted = toImufusionUnits(np.zeros((1, 3)), accel)
        assert converted[0][2] == pytest.approx(1.0)

    def test_oneGIsNotNinePointEight(self) -> None:
        """The specific mistake: passing m/s^2 where g is expected."""
        _, converted = toImufusionUnits(np.zeros((1, 3)), np.array([[0.0, 0.0, 9.80665]]))
        assert converted[0][2] != pytest.approx(9.80665)

    def test_ourMeasuredRestBiasConvertsToTheFigureWeQuote(self) -> None:
        """0.01275 rad/s is the 0.730 deg/s quoted in the evidence files."""
        converted, _ = toImufusionUnits(np.array([[0.01275, 0.0, 0.0]]), np.zeros((1, 3)))
        assert converted[0][0] == pytest.approx(0.730, abs=0.001)

    def test_conversionIsElementwiseAcrossManySamples(self) -> None:
        gyro = np.full((50, 3), math.pi)
        accel = np.full((50, 3), STANDARD_GRAVITY_MS2)
        gyroOut, accelOut = toImufusionUnits(gyro, accel)
        assert gyroOut.shape == (50, 3)
        assert np.allclose(gyroOut, 180.0)
        assert np.allclose(accelOut, 1.0)


class TestFrameB:
    """(fwd, left, up) = (-y, +x, +z). Settled by direct tilt test 2026-09-16."""

    def test_forwardIsNegativeY(self) -> None:
        assert frameB(np.array([[0.0, -1.0, 0.0]]))[0][0] == pytest.approx(1.0)

    def test_leftIsPositiveX(self) -> None:
        assert frameB(np.array([[1.0, 0.0, 0.0]]))[0][1] == pytest.approx(1.0)

    def test_upIsUnchanged(self) -> None:
        assert frameB(np.array([[0.0, 0.0, 9.8]]))[0][2] == pytest.approx(9.8)

    def test_noseUpLiftReadsPositiveForward(self) -> None:
        """The measured tilt test: nose up gave accel_y = -5.19, and forward is
        -y, so the forward component must come out POSITIVE."""
        assert frameB(np.array([[0.95, -5.19, 8.54]]))[0][0] == pytest.approx(5.19)

    def test_frameIsRightHanded(self) -> None:
        fwd = frameB(np.array([[0.0, -1.0, 0.0]]))[0]
        left = frameB(np.array([[1.0, 0.0, 0.0]]))[0]
        up = frameB(np.array([[0.0, 0.0, 1.0]]))[0]
        assert np.allclose(np.cross(fwd, left), up)


class TestCalibrationIsIdentityByDefault:
    """An uncalibrated run must be the SAME code path with no corrections, not a
    different one -- otherwise the comparison confounds calibration with code."""

    def test_rawAccelIsUnchanged(self) -> None:
        cal = Calibration()
        accel = np.array([[0.3, -0.1, 9.98]])
        assert np.allclose(cal.applyAccel(accel), accel)

    def test_rawGyroIsUnchanged(self) -> None:
        cal = Calibration()
        gyro = np.array([[0.002, 0.013, 0.003]])
        assert np.allclose(cal.applyGyro(gyro), gyro)

    def test_rawMagIsUnchangedAndUnflipped(self) -> None:
        cal = Calibration()
        mag = np.array([[16.3, 16.0, 36.7]])
        assert np.allclose(cal.applyMag(mag), mag)

    def test_calibratedMagAppliesAxisFixThenOffset(self) -> None:
        cal = Calibration(magOffsetUt=(1.0, 2.0, 3.0), magAxisFix=True, label="cal")
        out = cal.applyMag(np.array([[10.0, 10.0, 10.0]]))
        assert out[0] == pytest.approx([9.0, -12.0, -13.0])

    def test_calibratedAccelScaleBringsOneGToUnity(self) -> None:
        cal = Calibration(accelScale=1.0 / 1.0185, label="cal")
        out = cal.applyAccel(np.array([[0.0, 0.0, STANDARD_GRAVITY_MS2 * 1.0185]]))
        assert out[0][2] == pytest.approx(STANDARD_GRAVITY_MS2, abs=0.001)
