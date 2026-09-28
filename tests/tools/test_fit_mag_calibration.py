"""ARCH-064 Task 6: tests for the planar hard/soft-iron magnetometer fitter.

WHY AN ELLIPSE. As a car's heading sweeps 360 degrees, Earth's HORIZONTAL
field traces a circle in vehicle coordinates -- IF the magnetometer were
perfect. Hard iron shifts that circle's CENTRE; soft iron stretches and
rotates it into an ellipse. So a synthetic ellipse with a known centre, known
semi-axes and a known rotation is exactly the shape a real capture's
horizontal locus takes, and fitting it back out is the whole test.

The synthetic data is built in the BODY frame directly (accel pinned to
``(0, 0, 9.80665)`` -- a level car, so the level-frame basis this module
derives is the identity and the fit is scored against unambiguous, exactly
known ellipse parameters). The loader/CLI test is the one place device-frame
conversion is exercised, round-tripped through the INVERSE of the production
``resolveMountFrame`` mapping so the assertion would fail if that call were
ever dropped from the loader.
"""

from __future__ import annotations

import csv
import json
import math

import numpy as np
import pytest

from pi.sensors.imu_state_bridge import IMU_BODY_FRAME, resolveMountFrame
from tools.imu.fit_mag_calibration import (
    MIN_OCCUPIED_BINS,
    fitMagCalibration,
    loadRows,
    main,
)

Vector3 = tuple[float, float, float]

_LEVEL_ACCEL: Vector3 = (0.0, 0.0, 9.80665)


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
    points: list[Vector3], accel: Vector3 = _LEVEL_ACCEL
) -> list[tuple[float, Vector3, Vector3]]:
    return [(float(i), accel, mag) for i, mag in enumerate(points)]


# ARCH-064 Task 6 brief's exact synthetic parameters.
_TRUE_CENTER_P = 12.0
_TRUE_CENTER_Q = -7.0
_TRUE_R1 = 20.0
_TRUE_R2 = 16.0
_TRUE_ROTATION_DEG = 25.0
_TRUE_HZ = 45.0


class TestFitMagCalibration:
    def test_recoversHardIronWithinPoint5UtOnACleanEllipse(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_HZ,
        )
        fit = fitMagCalibration(_rowsFromMagPoints(points))

        assert fit.hardIronUt[0] == pytest.approx(_TRUE_CENTER_P, abs=0.5)
        assert fit.hardIronUt[1] == pytest.approx(_TRUE_CENTER_Q, abs=0.5)
        assert fit.hardIronUt[2] == pytest.approx(_TRUE_HZ, abs=0.5)

    def test_recoversHardIronWithNoise(self) -> None:
        """Realistic sensor noise, still well inside the 0.5 uT bound."""
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_HZ,
            noiseUt=0.15,
        )
        fit = fitMagCalibration(_rowsFromMagPoints(points))

        assert fit.hardIronUt[0] == pytest.approx(_TRUE_CENTER_P, abs=0.5)
        assert fit.hardIronUt[1] == pytest.approx(_TRUE_CENTER_Q, abs=0.5)
        assert fit.hardIronUt[2] == pytest.approx(_TRUE_HZ, abs=0.5)

    def test_softIronCorrectsRadiiToWithin3Percent(self) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_HZ,
            noiseUt=0.15,
        )
        fit = fitMagCalibration(_rowsFromMagPoints(points))
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
            hz=_TRUE_HZ,
        )
        fit = fitMagCalibration(_rowsFromMagPoints(points))

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
            hz=_TRUE_HZ,
        )
        fit = fitMagCalibration(_rowsFromMagPoints(points))
        block = fit.toConfigBlock()

        assert set(block.keys()) == {"hardIronUt", "softIron"}
        assert len(block["hardIronUt"]) == 3
        assert len(block["softIron"]) == 3
        assert all(len(row) == 3 for row in block["softIron"])

    def test_refusesInsufficientHeadingCoverage(self) -> None:
        """Only a third of the compass driven -- fewer than 25/36 bins."""
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_HZ,
            count=200,
            spanDeg=120.0,
        )
        with pytest.raises(ValueError, match="coverage"):
            fitMagCalibration(_rowsFromMagPoints(points))

    def test_acceptsCoverageRightAtTheFloor(self) -> None:
        """25/36 bins (MIN_OCCUPIED_BINS) is accepted, not rejected."""
        assert MIN_OCCUPIED_BINS == 25
        # 250 degrees of span at 10 deg/bin occupies at least 25 distinct bins.
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_HZ,
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
            hz=_TRUE_HZ,
        )
        rows = _rowsFromMagPoints(points, accel=(0.0, 0.0, 0.0))
        with pytest.raises(ValueError, match="gravity"):
            fitMagCalibration(rows)


def _deviceFrameFromBody(vecBody: Vector3, mount: dict[str, str] = IMU_BODY_FRAME) -> Vector3:
    """Invert ``resolveMountFrame``: body (forward, left, up) -> raw device axes.

    Generic over any signed-permutation mount (each device axis is named
    exactly once, across forward/left/up, optionally negated -- true of every
    ``IMU_BODY_FRAME_*`` this project has ever shipped), so this round-trips
    correctly even if the shipped mount stops being the identity map. Proves
    the loader really calls ``resolveMountFrame`` rather than passing the
    columns through unchanged, which an identity-mount-only test could not.
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
    path: str, rows: list[tuple[float, int | None, Vector3, Vector3]]
) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ts_capture",
                "drive_id",
                "accel_x_ms2",
                "accel_y_ms2",
                "accel_z_ms2",
                "mag_x_ut",
                "mag_y_ut",
                "mag_z_ut",
            ]
        )
        for ts, driveId, accelDevice, magDevice in rows:
            writer.writerow(
                [ts, "" if driveId is None else driveId, *accelDevice, *magDevice]
            )


class TestLoadRows:
    def test_roundTripsThroughTheInverseMountMapping(self, tmp_path) -> None:
        """The defining property: what comes back out is what the body-frame
        producer would have seen, proving resolveMountFrame really ran.
        """
        accelBody: Vector3 = (0.1, -0.2, 9.75)
        magBody: Vector3 = (5.0, -3.0, 40.0)
        accelDevice = _deviceFrameFromBody(accelBody)
        magDevice = _deviceFrameFromBody(magBody)
        # Sanity: resolveMountFrame(deviceVec) recovers the body vec exactly --
        # if this failed the test below would be meaningless.
        assert resolveMountFrame(accelDevice) == pytest.approx(accelBody)
        assert resolveMountFrame(magDevice) == pytest.approx(magBody)

        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), [(1.0, None, accelDevice, magDevice)])

        rows = loadRows(str(csvPath))
        assert len(rows) == 1
        tsCaptureS, loadedAccel, loadedMag = rows[0]
        assert tsCaptureS == pytest.approx(1.0)
        assert loadedAccel == pytest.approx(accelBody)
        assert loadedMag == pytest.approx(magBody)

    def test_filtersByDriveId(self, tmp_path) -> None:
        rows = [
            (1.0, 7, _LEVEL_ACCEL, (1.0, 2.0, 3.0)),
            (2.0, 8, _LEVEL_ACCEL, (4.0, 5.0, 6.0)),
            (3.0, 7, _LEVEL_ACCEL, (7.0, 8.0, 9.0)),
        ]
        csvPath = tmp_path / "capture.csv"
        _writeCsv(
            str(csvPath),
            [(ts, drive, _deviceFrameFromBody(a), _deviceFrameFromBody(m)) for ts, drive, a, m in rows],
        )

        assert len(loadRows(str(csvPath))) == 3
        onlyDrive7 = loadRows(str(csvPath), driveId=7)
        assert len(onlyDrive7) == 2
        assert all(ts in (1.0, 3.0) for ts, _, _ in onlyDrive7)

    def test_skipsRowsMissingFields(self, tmp_path) -> None:
        csvPath = tmp_path / "capture.csv"
        with open(csvPath, "w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ts_capture", "accel_x_ms2", "accel_y_ms2", "accel_z_ms2"])
            writer.writerow([1.0, 0.0, 0.0, 9.8])  # no mag columns at all
        assert loadRows(str(csvPath)) == []


class TestMainCli:
    def test_printsMagCalibrationAndFitQuality(self, tmp_path, capsys) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_HZ,
            noiseUt=0.1,
        )
        rows = [
            (float(i), 42, _deviceFrameFromBody(_LEVEL_ACCEL), _deviceFrameFromBody(mag))
            for i, mag in enumerate(points)
        ]
        csvPath = tmp_path / "capture.csv"
        _writeCsv(str(csvPath), rows)

        exitCode = main([str(csvPath), "--drive-id", "42"])
        assert exitCode == 0

        output = json.loads(capsys.readouterr().out)
        assert "magCalibration" in output
        assert "fitQuality" in output
        hardIron = output["magCalibration"]["hardIronUt"]
        assert hardIron[0] == pytest.approx(_TRUE_CENTER_P, abs=0.5)
        assert hardIron[1] == pytest.approx(_TRUE_CENTER_Q, abs=0.5)
        assert output["fitQuality"]["headingBinsOccupied"] == 36
        assert output["fitQuality"]["radiusSpreadPercent"] < 3.0

    def test_reportsRefusalInsteadOfCrashing(self, tmp_path, capsys) -> None:
        points = _ellipsePoints(
            centerP=_TRUE_CENTER_P,
            centerQ=_TRUE_CENTER_Q,
            r1=_TRUE_R1,
            r2=_TRUE_R2,
            rotationDeg=_TRUE_ROTATION_DEG,
            hz=_TRUE_HZ,
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
