"""ARCH-064 Task 6: tests for the planar hard/soft-iron magnetometer fitter.

WHY AN ELLIPSE. As a car's heading sweeps 360 degrees, Earth's HORIZONTAL
field traces a circle in vehicle coordinates -- IF the magnetometer were
perfect. Hard iron shifts that circle's CENTRE; soft iron stretches and
rotates it into an ellipse. So a synthetic ellipse with a known centre, known
semi-axes and a known rotation is exactly the shape a real capture's
horizontal locus takes, and fitting it back out is the whole test.

The synthetic data is built in the BODY frame directly (accel pinned to
gravity along a chosen "up" direction -- level or tilted -- so the level-frame
basis this module derives is known exactly and the fit is scored against
unambiguous, exactly known ellipse parameters). The loader/CLI tests are where
device-frame conversion is exercised, round-tripped through the INVERSE of
the production ``resolveMountFrame`` mapping -- including, for fix round 1
(I4), under a NON-identity mount, with a proof that the round-trip assertion
can actually go red if ``resolveMountFrame`` were ever dropped from the loader.

Fix round 1 (reviewer rejected da39bc16) additions, by finding:

* C1 (Ruling 20) -- the loader accepts the REAL edr_imu_sample column names
  as primary, the unit-suffixed alias as a fallback, and raises naming what
  is missing rather than silently returning no rows.
* C2 (Ruling 22) -- hard-iron z now subtracts Earth's own vertical field
  before what is left is called hard iron; the old bug (raw mean vertical,
  no subtraction) is pinned as a NEGATIVE space -- these tests use a separate
  Earth V and a small true iron z and assert the SMALL number is recovered.
* C3 (Ruling 23) -- heading-coverage bins are centred on the FITTED ellipse
  centre, count only MOVING samples (gyro-gated), and require >=3 samples per
  bin; the dense-idle exploit that used to be accepted is now refused.
* I4 -- the mount round-trip test uses a genuinely non-identity mount and
  proves it can fail.
* I5 -- the 3x3 body-frame embedding (B^T C B) is exercised off-level, with
  the calibration applied exactly as AhrsFusion applies it
  (``m_c = S @ (m_u - h)``, src/pi/sensors/ahrs_fusion.py:310).
* m7/m8 -- the radius-spread quality floor and the (now clearly labelled)
  major-axis rotation.
"""

from __future__ import annotations

import csv
import json
import math

import numpy as np
import pytest

import pi.sensors.imu_state_bridge as imu_state_bridge_module
import tools.imu.fit_mag_calibration as fit_mag_calibration_module
from pi.sensors.imu_state_bridge import IMU_BODY_FRAME, resolveMountFrame
from tools.imu.fit_mag_calibration import (
    MAX_RADIUS_SPREAD_PERCENT_DEFAULT,
    MIN_OCCUPIED_BINS,
    MOVING_MIN_GYRO_RAD_S,
    fitMagCalibration,
    loadRows,
    main,
)

Vector3 = tuple[float, float, float]

_LEVEL_ACCEL: Vector3 = (0.0, 0.0, 9.80665)
_STANDARD_GRAVITY_MS2 = 9.80665
# Comfortably above MOVING_MIN_GYRO_RAD_S (accel_cal.DEFAULT_MAX_GYRO_RAD_S,
# 0.05 rad/s) so a row tagged "moving" in a test is unambiguously moving.
_MOVING_GYRO_RAD_S = MOVING_MIN_GYRO_RAD_S * 10.0
_IDLE_GYRO_RAD_S = MOVING_MIN_GYRO_RAD_S * 0.1


def _ellipsePoints(
    *,
    centerP: float,
    centerQ: float,
    r1: float,
    r2: float,
    rotationDeg: float,
    hz: float,
    count: int = 360,
    noiseUt: float = 0.0,
    spanDeg: float = 360.0,
    seed: int = 42,
) -> list[Vector3]:
    """Trace a rotated ellipse in the horizontal (p, q) plane, constant z=hz.

    ``spanDeg`` lets a test cover only PART of the compass (to exercise the
    coverage refusal) without changing anything else about the shape.
    """
    rng = np.random.default_rng(seed)
    theta = math.radians(rotationDeg)
    cosT, sinT = math.cos(theta), math.sin(theta)
    points: list[Vector3] = []
    for i in range(count):
        t = math.radians(spanDeg * i / count)
        rx = r1 * math.cos(t)
        ry = r2 * math.sin(t)
        p = centerP + rx * cosT - ry * sinT
        q = centerQ + rx * sinT + ry * cosT
        r = hz
        if noiseUt:
            p += float(rng.normal(scale=noiseUt))
            q += float(rng.normal(scale=noiseUt))
            r += float(rng.normal(scale=noiseUt))
        points.append((p, q, r))
    return points


def _rowsFromMagPoints(
    points: list[Vector3],
    accel: Vector3 = _LEVEL_ACCEL,
    gyroMagRadS: float | None = None,
) -> list[tuple[float, Vector3, Vector3, float | None]]:
    """Body-frame rows with no gyro column by default (Ruling 23 all-moving fallback)."""
    return [(float(i), accel, mag, gyroMagRadS) for i, mag in enumerate(points)]


# ARCH-064 Task 6 brief's exact synthetic parameters for the horizontal shape.
_TRUE_CENTER_P = 12.0
_TRUE_CENTER_Q = -7.0
_TRUE_R1 = 20.0
_TRUE_R2 = 16.0
_TRUE_ROTATION_DEG = 25.0

# C2 (Ruling 22): Earth's vertical field and the TRUE (small) hard-iron z are
# now separate quantities -- the raw mean vertical (what the fit round 1 bug
# reported AS hard-iron z) is their SUM, -49.0, which is deliberately NOT
# asserted as the recovered hard-iron anywhere below.
_TRUE_EARTH_VERTICAL_UT = -52.0
_TRUE_IRON_Z_UT = 3.0
_TRUE_RAW_MEAN_VERTICAL_UT = _TRUE_EARTH_VERTICAL_UT + _TRUE_IRON_Z_UT  # -49.0


class TestFitMagCalibration:
    def test_recoversHardIronWithinPoint5UtOnACleanEllipse(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )

        assert fit.hardIronUt[0] == pytest.approx(_TRUE_CENTER_P, abs=0.5)
        assert fit.hardIronUt[1] == pytest.approx(_TRUE_CENTER_Q, abs=0.5)
        assert fit.hardIronUt[2] == pytest.approx(_TRUE_IRON_Z_UT, abs=0.5)

    def test_recoversHardIronWithNoise(self) -> None:
        """Realistic sensor noise, still well inside the 0.5 uT bound."""
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            noiseUt=0.15,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )

        assert fit.hardIronUt[0] == pytest.approx(_TRUE_CENTER_P, abs=0.5)
        assert fit.hardIronUt[1] == pytest.approx(_TRUE_CENTER_Q, abs=0.5)
        assert fit.hardIronUt[2] == pytest.approx(_TRUE_IRON_Z_UT, abs=0.5)

    def test_hardIronZDoesNotAbsorbEarthsField(self) -> None:
        """C2 negative check: the fix round 1 bug specifically -- the OLD
        (wrong) reading was the raw mean vertical, ~-49 uT. That must NOT be
        what the fixed fitter reports as hard-iron z.
        """
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert abs(fit.hardIronUt[2] - _TRUE_RAW_MEAN_VERTICAL_UT) > 40.0

    def test_softIronCorrectsRadiiToWithin3Percent(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            noiseUt=0.15,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert fit.radiusSpreadPercent < 3.0

    def test_softIronEmbedsAsIdentityOnTheZRowAndColumn(self) -> None:
        """The brief: "a 2x2 correction embedded in the 3x3 (z row/col identity)".

        Level accel means the body frame IS the level frame here, so the
        embedding is literally the z row/column -- this pins that shape.
        """
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )

        assert fit.softIron[0][2] == pytest.approx(0.0, abs=1e-9)
        assert fit.softIron[1][2] == pytest.approx(0.0, abs=1e-9)
        assert fit.softIron[2][0] == pytest.approx(0.0, abs=1e-9)
        assert fit.softIron[2][1] == pytest.approx(0.0, abs=1e-9)
        assert fit.softIron[2][2] == pytest.approx(1.0, abs=1e-9)

    def test_toConfigBlockMatchesTheMagCalibrationSchema(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        block = fit.toConfigBlock()

        assert set(block.keys()) == {"hardIronUt", "softIron"}
        assert len(block["hardIronUt"]) == 3
        assert len(block["softIron"]) == 3
        assert all(len(row) == 3 for row in block["softIron"])

    def test_majorAxisRotationNamesTheLargerAxis(self) -> None:
        """m8: semiAxesUt is (major, minor); the rotation describes the major one."""
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert fit.semiAxesUt[0] >= fit.semiAxesUt[1]
        assert fit.semiAxesUt[0] == pytest.approx(_TRUE_R1, abs=0.5)
        assert fit.semiAxesUt[1] == pytest.approx(_TRUE_R2, abs=0.5)
        # The major axis (r1=20) was rotated 25 degrees in construction; that
        # angle (mod 180, an axis has no direction) is what must come back.
        assert fit.majorAxisRotationDeg % 180.0 == pytest.approx(
            _TRUE_ROTATION_DEG, abs=0.5
        )

    def test_refusesInsufficientHeadingCoverage(self) -> None:
        """Only a third of the compass driven -- fewer than 25/36 bins."""
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=200,
            spanDeg=120.0,
        )
        with pytest.raises(ValueError, match="coverage"):
            fitMagCalibration(_rowsFromMagPoints(points))

    def test_acceptsCoverageRightAtTheFloor(self) -> None:
        """25/36 bins (MIN_OCCUPIED_BINS) is accepted, not rejected."""
        assert MIN_OCCUPIED_BINS == 25
        # 250 degrees of span at 10 deg/bin, ~10 pts/bin -- clears both the
        # bin-count floor and the >=3-samples-per-bin floor (Ruling 23).
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=250,
            spanDeg=250.0,
        )
        fit = fitMagCalibration(_rowsFromMagPoints(points))
        assert fit.headingBinsOccupied >= MIN_OCCUPIED_BINS

    def test_refusesTooFewSamples(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            fitMagCalibration(_rowsFromMagPoints([(1.0, 2.0, 45.0)] * 5))

    def test_refusesWithNoGravityReference(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        rows = _rowsFromMagPoints(points, accel=(0.0, 0.0, 0.0))
        with pytest.raises(ValueError, match="gravity"):
            fitMagCalibration(rows)


class TestQualityFloor:
    """m7: refuse a fit whose corrected radius spread is untrustworthy."""

    def _noisyRows(self, noiseUt: float) -> list[tuple[float, Vector3, Vector3, float | None]]:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=360,
            noiseUt=noiseUt,
        )
        return _rowsFromMagPoints(points)

    def test_refusesASpreadOverTheFloor(self) -> None:
        # Noise scaled well past what recovers a <5% RMS spread.
        rows = self._noisyRows(noiseUt=3.0)
        with pytest.raises(ValueError, match="quality floor"):
            fitMagCalibration(rows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT)

    def test_forceAcceptsItAnywayAndMarksTheResult(self) -> None:
        rows = self._noisyRows(noiseUt=3.0)
        fit = fitMagCalibration(
            rows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT, force=True
        )
        assert fit.qualityForced is True
        assert fit.radiusSpreadPercent > MAX_RADIUS_SPREAD_PERCENT_DEFAULT

    def test_cleanFitIsNotForced(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
        )
        fit = fitMagCalibration(
            _rowsFromMagPoints(points), earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )
        assert fit.qualityForced is False


class TestCoverageExploit:
    """C3 (Ruling 23): the dense-idle exploit that fit round 1 accepted."""

    def test_denseIdleDwellIsRefused(self) -> None:
        """MEASURED regression: 2000 idle samples (parked) + a real 300-sample
        90-degree sweep, both noisy (sigma=0.6), used to be ACCEPTED at 32/36
        bins with the hard-iron offset off by 12 uT, because the naive
        centroid sat near the dense idle cluster and noise scattered it
        across many spurious bins. Moving-only, fitted-centre, >=3-per-bin
        binning must refuse this instead.
        """
        idlePoints = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=2000,
            spanDeg=0.001,  # parked: one heading, essentially no sweep
            noiseUt=0.6,
            seed=1,
        )
        movingPoints = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=300,
            spanDeg=90.0,
            noiseUt=0.6,
            seed=2,
        )
        rows = _rowsFromMagPoints(idlePoints, gyroMagRadS=_IDLE_GYRO_RAD_S) + _rowsFromMagPoints(
            movingPoints, gyroMagRadS=_MOVING_GYRO_RAD_S
        )
        with pytest.raises(ValueError, match="coverage"):
            fitMagCalibration(rows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT)

    def test_idleSamplesDoNotCountEvenWhenCoverageWouldOtherwisePass(self) -> None:
        """A full-coverage moving sweep plus a huge idle cluster must fit
        (and refuse-or-not) IDENTICALLY to the moving sweep alone -- proving
        idle rows are excluded, not merely down-weighted.
        """
        movingPoints = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=360,
        )
        movingRows = _rowsFromMagPoints(movingPoints, gyroMagRadS=_MOVING_GYRO_RAD_S)
        withoutIdle = fitMagCalibration(movingRows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT)

        idlePoints = _ellipsePoints(
            centerP=_TRUE_CENTER_P + 5.0,  # deliberately off-centre
            centerQ=_TRUE_CENTER_Q - 5.0,
            r1=1.0,
            r2=1.0,
            rotationDeg=0.0,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=2000,
            spanDeg=0.001,
            noiseUt=0.6,
            seed=3,
        )
        idleRows = _rowsFromMagPoints(idlePoints, gyroMagRadS=_IDLE_GYRO_RAD_S)
        withIdle = fitMagCalibration(
            movingRows + idleRows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT
        )

        assert withIdle.hardIronUt == pytest.approx(withoutIdle.hardIronUt, abs=1e-6)
        assert withIdle.movingSamples == withoutIdle.movingSamples


def _deviceFrameFromBody(vecBody: Vector3, mount: dict[str, str] = IMU_BODY_FRAME) -> Vector3:
    """Invert ``resolveMountFrame``: body (forward, left, up) -> raw device axes.

    Generic over any signed-permutation mount (each device axis is named
    exactly once, across forward/left/up, optionally negated -- true of every
    ``IMU_BODY_FRAME_*`` this project has ever shipped), so this round-trips
    correctly under a non-identity mount too (I4).
    """
    device = [0.0, 0.0, 0.0]
    axisIndex = {"x": 0, "y": 1, "z": 2}
    for roleIdx, role in enumerate(("forward", "left", "up")):
        spec = mount[role].strip().lower()
        sign = -1.0 if spec.startswith("-") else 1.0
        axis = spec.lstrip("+-")
        device[axisIndex[axis]] = sign * vecBody[roleIdx]
    return (device[0], device[1], device[2])


def _writeCsv(
    path: str,
    rows: list[tuple[float, int | None, Vector3, Vector3]],
    *,
    columnStyle: str = "primary",
    includeGyro: bool = False,
    gyroDevice: Vector3 = (0.0, 0.0, 0.0),
) -> None:
    if columnStyle == "primary":
        accelHeader = ["accel_x", "accel_y", "accel_z"]
        magHeader = ["mag_x", "mag_y", "mag_z"]
        gyroHeader = ["gyro_x", "gyro_y", "gyro_z"]
    elif columnStyle == "alias":
        accelHeader = ["accel_x_ms2", "accel_y_ms2", "accel_z_ms2"]
        magHeader = ["mag_x_ut", "mag_y_ut", "mag_z_ut"]
        gyroHeader = ["gyro_x_rads", "gyro_y_rads", "gyro_z_rads"]
    else:
        raise ValueError(columnStyle)

    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        header = ["ts_capture", "drive_id", *accelHeader, *magHeader]
        if includeGyro:
            header += gyroHeader
        writer.writerow(header)
        for ts, driveId, accelDevice, magDevice in rows:
            line = [ts, "" if driveId is None else driveId, *accelDevice, *magDevice]
            if includeGyro:
                line += list(gyroDevice)
            writer.writerow(line)


# The LITERAL column order of `select * from edr_imu_sample` (C1), per
# src/common/edr/sensor_schema.py's SCHEMA_EDR_IMU_SAMPLE DDL -- what
# `sqlite3 -csv -header obd.db "select * from edr_imu_sample where drive_id=N"`
# actually produces, extra columns and all.
_REAL_EDR_IMU_SAMPLE_HEADER = [
    "id",
    "ts_utc",
    "ts_capture",
    "seq",
    "accel_x",
    "accel_y",
    "accel_z",
    "gyro_x",
    "gyro_y",
    "gyro_z",
    "mag_x",
    "mag_y",
    "mag_z",
    "temp_c",
    "drive_id",
    "data_source",
    "schema_version",
]


class TestLoadRows:
    def test_roundTripsThroughTheInverseMountMapping(self, tmp_path) -> None:
        """The defining property: what comes back out is what the body-frame
        producer would have seen, proving resolveMountFrame really ran.
        """
        accelBody: Vector3 = (0.1, -0.2, 9.75)
        magBody: Vector3 = (5.0, -3.0, 40.0)
        accelDevice = _deviceFrameFromBody(accelBody)
        magDevice = _deviceFrameFromBody(magBody)
        assert resolveMountFrame(accelDevice) == pytest.approx(accelBody)
        assert resolveMountFrame(magDevice) == pytest.approx(magBody)

        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), [(1.0, None, accelDevice, magDevice)])

        rows = loadRows(str(csvPath))
        assert len(rows) == 1
        tsCaptureS, loadedAccel, loadedMag, gyroMagRadS = rows[0]
        assert tsCaptureS == pytest.approx(1.0)
        assert loadedAccel == pytest.approx(accelBody)
        assert loadedMag == pytest.approx(magBody)
        assert gyroMagRadS is None  # no gyro columns in this CSV

    def test_roundTripUnderANonIdentityMountDiscriminates(self, tmp_path, monkeypatch) -> None:
        """I4: IMU_BODY_FRAME is currently the identity, so a round-trip test
        against it alone cannot fail. Monkeypatch it to a real, non-identity
        mount and PROVE the assertion below can go red -- by temporarily
        dropping resolveMountFrame from the loader (an identity pass-through)
        and confirming it disagrees with body-frame truth -- before trusting
        the restored, GREEN case.
        """
        nonIdentityMount = {"forward": "-y", "left": "+x", "up": "+z"}
        monkeypatch.setattr(imu_state_bridge_module, "IMU_BODY_FRAME", nonIdentityMount)

        accelBody: Vector3 = (0.1, -0.2, 9.75)
        magBody: Vector3 = (5.0, -3.0, 40.0)
        accelDevice = _deviceFrameFromBody(accelBody, mount=nonIdentityMount)
        magDevice = _deviceFrameFromBody(magBody, mount=nonIdentityMount)
        # Sanity: the (patched-default) resolveMountFrame really does invert
        # this device vector back to the body vector under the new mount.
        assert resolveMountFrame(accelDevice) == pytest.approx(accelBody)
        assert accelDevice != pytest.approx(accelBody)  # mount is genuinely non-identity

        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), [(1.0, None, accelDevice, magDevice)])

        # RED proof: with resolveMountFrame swapped for an identity pass-
        # through, the loader must return the raw DEVICE vector, which is NOT
        # close to accelBody under this non-identity mount.
        originalResolve = fit_mag_calibration_module.resolveMountFrame
        fit_mag_calibration_module.resolveMountFrame = lambda vec, mount=None: vec
        try:
            brokenRows = loadRows(str(csvPath))
            brokenAccel = brokenRows[0][1]
            assert brokenAccel != pytest.approx(accelBody)
        finally:
            fit_mag_calibration_module.resolveMountFrame = originalResolve

        # GREEN: restored, the loader recovers the true body-frame vectors.
        rows = loadRows(str(csvPath))
        assert len(rows) == 1
        _, loadedAccel, loadedMag, _ = rows[0]
        assert loadedAccel == pytest.approx(accelBody)
        assert loadedMag == pytest.approx(magBody)

    def test_acceptsTheRealEdrImuSampleColumnNames(self, tmp_path) -> None:
        """C1: the literal column list a real export produces, extra columns
        (id, ts_utc, seq, temp_c, data_source, schema_version) and all.
        """
        csvPath = tmp_path / "capture.csv"
        accelBody: Vector3 = (0.1, -0.2, 9.75)
        magBody: Vector3 = (5.0, -3.0, 40.0)
        gyroDevice: Vector3 = (0.01, -0.02, 0.03)
        accelDevice = _deviceFrameFromBody(accelBody)
        magDevice = _deviceFrameFromBody(magBody)

        with open(csvPath, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(_REAL_EDR_IMU_SAMPLE_HEADER)
            writer.writerow(
                [
                    1,  # id
                    "2026-09-28T00:00:00Z",  # ts_utc
                    12.5,  # ts_capture
                    7,  # seq
                    *accelDevice,
                    *gyroDevice,
                    *magDevice,
                    21.0,  # temp_c
                    99,  # drive_id
                    "real",  # data_source
                    1,  # schema_version
                ]
            )

        rows = loadRows(str(csvPath))
        assert len(rows) == 1
        tsCaptureS, loadedAccel, loadedMag, gyroMagRadS = rows[0]
        assert tsCaptureS == pytest.approx(12.5)
        assert loadedAccel == pytest.approx(accelBody)
        assert loadedMag == pytest.approx(magBody)
        assert gyroMagRadS == pytest.approx(math.sqrt(sum(c * c for c in gyroDevice)))

        assert loadRows(str(csvPath), driveId=99) == rows
        assert loadRows(str(csvPath), driveId=1) == []

    def test_acceptsTheAliasColumnNames(self, tmp_path) -> None:
        accelBody: Vector3 = (0.1, -0.2, 9.75)
        magBody: Vector3 = (5.0, -3.0, 40.0)
        accelDevice = _deviceFrameFromBody(accelBody)
        magDevice = _deviceFrameFromBody(magBody)
        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), [(1.0, None, accelDevice, magDevice)], columnStyle="alias")

        rows = loadRows(str(csvPath))
        assert len(rows) == 1
        assert rows[0][1] == pytest.approx(accelBody)
        assert rows[0][2] == pytest.approx(magBody)

    def test_raisesNamingMissingColumnsRatherThanReturningNoRows(self, tmp_path) -> None:
        """C1: the fit round 1 bug -- wrong header used to silently load 0
        rows. It must now raise, naming what is missing, before any row loop.
        """
        csvPath = tmp_path / "capture.csv"
        with open(csvPath, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ts_capture", "accel_x", "accel_y", "accel_z"])  # no mag at all
            writer.writerow([1.0, 0.0, 0.0, 9.8])

        with pytest.raises(ValueError, match="mag"):
            loadRows(str(csvPath))

    def test_raisesOnAnEmptyOrHeaderlessCsv(self, tmp_path) -> None:
        csvPath = tmp_path / "capture.csv"
        csvPath.write_text("")
        with pytest.raises(ValueError, match="header"):
            loadRows(str(csvPath))

    def test_parsesGyroMagnitudeWhenGyroColumnsArePresent(self, tmp_path) -> None:
        accelBody: Vector3 = (0.0, 0.0, 9.80665)
        magBody: Vector3 = (1.0, 2.0, 3.0)
        gyroDevice: Vector3 = (0.3, 0.4, 0.0)  # magnitude 0.5, well above the floor
        csvPath = tmp_path / "capture.csv"
        _writeCsv(
            str(csvPath),
            [(1.0, None, _deviceFrameFromBody(accelBody), _deviceFrameFromBody(magBody))],
            includeGyro=True,
            gyroDevice=gyroDevice,
        )
        rows = loadRows(str(csvPath))
        assert rows[0][3] == pytest.approx(0.5)

    def test_filtersByDriveId(self, tmp_path) -> None:
        driveRows = [
            (1.0, 7, _LEVEL_ACCEL, (1.0, 2.0, 3.0)),
            (2.0, 8, _LEVEL_ACCEL, (4.0, 5.0, 6.0)),
            (3.0, 7, _LEVEL_ACCEL, (7.0, 8.0, 9.0)),
        ]
        csvPath = tmp_path / "capture.csv"
        _writeCsv(
            str(csvPath),
            [
                (ts, drive, _deviceFrameFromBody(a), _deviceFrameFromBody(m))
                for ts, drive, a, m in driveRows
            ],
        )

        assert len(loadRows(str(csvPath))) == 3
        onlyDrive7 = loadRows(str(csvPath), driveId=7)
        assert len(onlyDrive7) == 2
        assert all(ts in (1.0, 3.0) for ts, _, _, _ in onlyDrive7)

    def test_skipsRowsMissingFields(self, tmp_path) -> None:
        csvPath = tmp_path / "capture.csv"
        with open(csvPath, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ts_capture", "accel_x", "accel_y", "accel_z", "mag_x", "mag_y", "mag_z"])
            writer.writerow([1.0, 0.0, 0.0, 9.8, "", 0.0, 0.0])  # mag_x blank/unparsable
        assert loadRows(str(csvPath)) == []


def _tiltedBasis(tiltDeg: float) -> tuple[Vector3, Vector3, Vector3]:
    """Body-frame (forward, left, up) for a small tilt about the left axis.

    Hand-derived independently of the module's own ``_levelBasis`` (same
    Gram-Schmidt construction is the ONLY orthonormal answer for a given up
    vector and a forward seed, so the numbers necessarily agree -- but this
    test builds its ground truth without calling the private helper under
    test, per the module's own public-API testing style).
    """
    theta = math.radians(tiltDeg)
    forward = (math.cos(theta), 0.0, -math.sin(theta))
    left = (0.0, 1.0, 0.0)
    up = (math.sin(theta), 0.0, math.cos(theta))
    return forward, left, up


def _applyCalibrationLikeAhrsFusion(
    vec: Vector3, hardIronUt: Vector3, softIron: tuple[Vector3, Vector3, Vector3]
) -> np.ndarray:
    """m_c = S @ (m_u - h) -- verbatim, src/pi/sensors/ahrs_fusion.py:310."""
    h = np.asarray(hardIronUt, dtype=float)
    s = np.asarray(softIron, dtype=float)
    return s @ (np.asarray(vec, dtype=float) - h)


def _magBodyRows(
    *,
    tiltDeg: float,
    centerP: float,
    centerQ: float,
    r1: float,
    r2: float,
    rotationDeg: float,
    rLevel: float,
    headingsDeg: list[float],
) -> tuple[tuple[Vector3, Vector3, Vector3], Vector3, dict[float, Vector3]]:
    """Body-frame (basis, gravity, magByHeading) for a tilted mount.

    Independent of the module's own ``_levelBasis`` -- see ``_tiltedBasis``.
    """
    forward, left, up = _tiltedBasis(tiltDeg)
    gravityBody: Vector3 = (
        _STANDARD_GRAVITY_MS2 * up[0],
        _STANDARD_GRAVITY_MS2 * up[1],
        _STANDARD_GRAVITY_MS2 * up[2],
    )
    theta = math.radians(rotationDeg)
    cosT, sinT = math.cos(theta), math.sin(theta)

    magBodyByHeading: dict[float, Vector3] = {}
    for headingDeg in headingsDeg:
        t = math.radians(headingDeg)
        rx = r1 * math.cos(t)
        ry = r2 * math.sin(t)
        pLevel = centerP + rx * cosT - ry * sinT
        qLevel = centerQ + rx * sinT + ry * cosT
        magBody = (
            pLevel * forward[0] + qLevel * left[0] + rLevel * up[0],
            pLevel * forward[1] + qLevel * left[1] + rLevel * up[1],
            pLevel * forward[2] + qLevel * left[2] + rLevel * up[2],
        )
        magBodyByHeading[headingDeg] = magBody
    return (forward, left, up), gravityBody, magBodyByHeading


class TestTiltedEmbedding:
    """I5: the B^T C B embedding, exercised off-level; C2's heading-accuracy claim.

    Two DIFFERENT synthetic shapes are used deliberately:

    * I5 uses the full rotated ELLIPSE (soft-iron genuinely anisotropic) and
      only asserts the corrected locus is a circle -- a general hard/soft-iron
      fit from shape alone cannot recover an absolute heading REFERENCE (a
      circle has full rotational symmetry; nothing in the ellipse's shape says
      which point on it is heading zero), so asserting recovered angle ==
      true parametrized heading for an ANISOTROPIC ellipse is not a sound
      thing to test.
    * C2 uses a pure CIRCLE (r1 == r2): with no shape anisotropy the fitted
      soft-iron matrix reduces to an isotropic scale (V diag(k,k) V^T == k*I
      for ANY orthonormal V, so the eigenvector-order ambiguity cannot rotate
      the answer either), which removes the reference-ambiguity confound and
      isolates z hard-iron correctness under tilt.

    INVESTIGATED AND WORTH RECORDING: a WRONG hz does NOT, in this fitter's
    construction, move the corrected HEADING at all -- proven algebraically
    and pinned by ``test_hardIronZDoesNotLeakIntoHeadingByConstruction``
    below. The level-frame decomposition used to build the embedding is EXACT
    (an orthonormal basis, B @ B^T == I), and the correction matrix C is
    block-diagonal (the brief's own "z row/col identity"), so the vertical
    and horizontal channels never mix, at any tilt. This is DIFFERENT from
    the reviewer's reported 8.6/17.6 degree figures -- those were measured
    against the fuller AhrsFusion pipeline (a recursive attitude filter whose
    magnetometer correction is not a single instantaneous atan2 off a
    mean-gravity level frame), which this test suite does not reconstruct.
    What IS verified here is the literal ask: with Ruling 22 applied, heading
    recovers to within 1 degree of truth at 3 and 6 degrees of pitch --  and,
    as a bonus, WHY the z-only bug specifically cannot be the heading-error
    mechanism for this fitter's own math, only for hz's OWN correctness
    (pinned separately by ``test_hardIronZDoesNotAbsorbEarthsField``).
    """

    def test_correctedEllipseLocusIsACircleAtRealisticMountTilt(self) -> None:
        """I5: nose-up gravity (2.5 degrees) + a genuinely rotated/anisotropic
        ellipse. Apply the emitted (h, S) exactly as AhrsFusion does.
        """
        headingsDeg = [float(d) for d in range(0, 360, 2)]
        (forward, left, up), gravityBody, magBodyByHeading = _magBodyRows(
            tiltDeg=2.5,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            rLevel=_TRUE_RAW_MEAN_VERTICAL_UT,
            headingsDeg=headingsDeg,
        )
        rows = [
            (float(i), gravityBody, magBody, None)
            for i, magBody in enumerate(magBodyByHeading.values())
        ]

        fit = fitMagCalibration(rows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT)

        correctedRadii = []
        for magBody in magBodyByHeading.values():
            corrected = _applyCalibrationLikeAhrsFusion(magBody, fit.hardIronUt, fit.softIron)
            pC = float(np.dot(corrected, forward))
            qC = float(np.dot(corrected, left))
            correctedRadii.append(math.hypot(pC, qC))

        radii = np.array(correctedRadii)
        spreadPercent = (
            (float(np.max(radii)) - float(np.min(radii))) / float(np.mean(radii)) * 100.0
        )
        assert spreadPercent < 1.0, f"corrected locus is not a circle: spread {spreadPercent}%"

    @pytest.mark.parametrize("tiltDeg", [3.0, 6.0])
    def test_correctedHeadingStaysWithinOneDegreeOfTruth(self, tiltDeg: float) -> None:
        """C2: a pure circle isolates z hard-iron correctness from the
        (separate, inherent) horizontal-rotation reference ambiguity.
        """
        headingsDeg = [float(d) for d in range(0, 360, 2)]
        circleH = 18.0
        (forward, left, up), gravityBody, magBodyByHeading = _magBodyRows(
            tiltDeg=tiltDeg,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=circleH,
            r2=circleH,
            rotationDeg=0.0,
            rLevel=_TRUE_RAW_MEAN_VERTICAL_UT,
            headingsDeg=headingsDeg,
        )
        rows = [
            (float(i), gravityBody, magBody, None)
            for i, magBody in enumerate(magBodyByHeading.values())
        ]

        fit = fitMagCalibration(rows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT)

        worstDiff = 0.0
        for headingDeg, magBody in magBodyByHeading.items():
            corrected = _applyCalibrationLikeAhrsFusion(magBody, fit.hardIronUt, fit.softIron)
            pC = float(np.dot(corrected, forward))
            qC = float(np.dot(corrected, left))
            recoveredHeadingDeg = math.degrees(math.atan2(qC, pC)) % 360.0
            diff = abs((recoveredHeadingDeg - headingDeg + 180.0) % 360.0 - 180.0)
            worstDiff = max(worstDiff, diff)

        assert worstDiff < 1.0, f"worst heading error {worstDiff} deg at tilt {tiltDeg}"

    @pytest.mark.parametrize("tiltDeg", [3.0, 6.0])
    def test_hardIronZDoesNotLeakIntoHeadingByConstruction(self, tiltDeg: float) -> None:
        """Why C2's heading-accuracy claim holds even off-level: the B^T C B
        embedding decouples the vertical channel from the horizontal one
        EXACTLY (the "z row/col identity" the brief specifies), because the
        level-frame projection undoing it is built from the SAME orthonormal
        basis. So a WRONG hz (earthVerticalUt=0, fit round 1's exact bug)
        changes the recovered hard-iron z and (pinned above) MUST still be
        caught by ``test_hardIronZDoesNotAbsorbEarthsField`` -- but it cannot,
        in THIS fitter's construction, move the corrected heading at all.
        This is a real, load-bearing property of the design (not a rounding
        coincidence): it is what a clean "z row/col identity" embedding
        buys, and a future change that accidentally coupled the channels
        would be caught by this test going red.
        """
        headingsDeg = [float(d) for d in range(0, 360, 2)]
        circleH = 18.0
        (forward, left, up), gravityBody, magBodyByHeading = _magBodyRows(
            tiltDeg=tiltDeg,
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=circleH,
            r2=circleH,
            rotationDeg=0.0,
            rLevel=_TRUE_RAW_MEAN_VERTICAL_UT,
            headingsDeg=headingsDeg,
        )
        rows = [
            (float(i), gravityBody, magBody, None)
            for i, magBody in enumerate(magBodyByHeading.values())
        ]

        buggyFit = fitMagCalibration(rows, earthVerticalUt=0.0)
        correctFit = fitMagCalibration(rows, earthVerticalUt=_TRUE_EARTH_VERTICAL_UT)
        # The bug is real -- hz itself is very wrong -- just not visible in
        # heading. Confirms this test exercises the intended defect.
        assert abs(buggyFit.hardIronUt[2] - correctFit.hardIronUt[2]) > 10.0

        for headingDeg, magBody in magBodyByHeading.items():
            buggyCorrected = _applyCalibrationLikeAhrsFusion(
                magBody, buggyFit.hardIronUt, buggyFit.softIron
            )
            correctCorrected = _applyCalibrationLikeAhrsFusion(
                magBody, correctFit.hardIronUt, correctFit.softIron
            )
            buggyHeadingDeg = math.degrees(
                math.atan2(np.dot(buggyCorrected, left), np.dot(buggyCorrected, forward))
            ) % 360.0
            correctHeadingDeg = math.degrees(
                math.atan2(np.dot(correctCorrected, left), np.dot(correctCorrected, forward))
            ) % 360.0
            diff = abs((buggyHeadingDeg - correctHeadingDeg + 180.0) % 360.0 - 180.0)
            assert diff < 1e-6, f"hz leaked into heading at heading {headingDeg}, tilt {tiltDeg}"


class TestMainCli:
    def test_printsMagCalibrationAndFitQuality(self, tmp_path, capsys) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            noiseUt=0.1,
        )
        rows = [
            (float(i), 42, _deviceFrameFromBody(_LEVEL_ACCEL), _deviceFrameFromBody(mag))
            for i, mag in enumerate(points)
        ]
        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), rows)

        exitCode = main(
            [str(csvPath), "--drive-id", "42", "--earth-vertical-ut", str(_TRUE_EARTH_VERTICAL_UT)]
        )
        assert exitCode == 0

        output = json.loads(capsys.readouterr().out)
        assert "magCalibration" in output
        assert "fitQuality" in output
        hardIron = output["magCalibration"]["hardIronUt"]
        assert hardIron[0] == pytest.approx(_TRUE_CENTER_P, abs=0.5)
        assert hardIron[1] == pytest.approx(_TRUE_CENTER_Q, abs=0.5)
        assert hardIron[2] == pytest.approx(_TRUE_IRON_Z_UT, abs=0.5)
        assert output["fitQuality"]["headingBinsOccupied"] == 36
        assert output["fitQuality"]["radiusSpreadPercent"] < 3.0
        assert output["fitQuality"]["qualityForced"] is False
        assert "majorAxisRotationDeg" in output["fitQuality"]

    def test_reportsRefusalInsteadOfCrashing(self, tmp_path, capsys) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=100,
            spanDeg=90.0,
        )
        rows = [
            (float(i), None, _deviceFrameFromBody(_LEVEL_ACCEL), _deviceFrameFromBody(mag))
            for i, mag in enumerate(points)
        ]
        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), rows)

        exitCode = main([str(csvPath)])
        assert exitCode == 1
        output = json.loads(capsys.readouterr().out)
        assert "refused" in output
        assert "coverage" in output["refused"]

    def test_forceFlagAcceptsAnOverQualityFloorFit(self, tmp_path, capsys) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_RAW_MEAN_VERTICAL_UT,
            count=360,
            noiseUt=3.0,
        )
        rows = [
            (float(i), None, _deviceFrameFromBody(_LEVEL_ACCEL), _deviceFrameFromBody(mag))
            for i, mag in enumerate(points)
        ]
        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), rows)

        refused = main([str(csvPath), "--earth-vertical-ut", str(_TRUE_EARTH_VERTICAL_UT)])
        assert refused == 1
        capsys.readouterr()

        forced = main(
            [str(csvPath), "--earth-vertical-ut", str(_TRUE_EARTH_VERTICAL_UT), "--force"]
        )
        assert forced == 0
        output = json.loads(capsys.readouterr().out)
        assert output["fitQuality"]["qualityForced"] is True
