"""ARCH-064 Task 6b: stage-1 sensor-intrinsic magnetometer fit from a hand tumble.

Synthetic tumbles are PHYSICAL: a fixed field (the car-bent local field at the
open door) seen through random rotations of the sensor, distorted by the
sensor's own symmetric soft iron and offset, with 0.3 uT noise on every axis of
every row.
"""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest

import pi.sensors.imu_state_bridge as imu_state_bridge_module
from tests.pi.sensors.test_ellipsoid_fit import MAG_OFFSET, magDistortion
from tools.imu.cal_frames import SENSOR_CAL_KEY, loadSensorCal, mountMatrix
from tools.imu.fit_mag_tumble import fitSensorMag, loadMagPoints, main
from tools.imu.tumble_capture import CSV_COLUMNS

NON_IDENTITY_MOUNT = {"forward": "+z", "left": "-x", "up": "-y"}
LOCAL_FIELD_UT = np.array([14.0, -9.0, -48.0])  # |F| ~ 50.8 uT


def _randomRotations(count: int, rng: np.random.Generator) -> np.ndarray:
    """Uniform random rotations (QR of Gaussian matrices, sign-fixed to det +1)."""
    out = np.empty((count, 3, 3))
    for i in range(count):
        q, r = np.linalg.qr(rng.normal(size=(3, 3)))
        q = q @ np.diag(np.sign(np.diag(r)))
        if np.linalg.det(q) < 0:
            q[:, 0] = -q[:, 0]
        out[i] = q
    return out


def tumblePoints(
    count: int = 3000,
    *,
    seed: int = 21,
    field: np.ndarray = LOCAL_FIELD_UT,
    noise: float = 0.3,
    keep=None,
) -> np.ndarray:
    """DEVICE-frame readings of a sensor tumbled in place: m = D_s . (Q F) + b_s + noise.

    ``keep`` optionally filters the true device-frame field directions (to
    model a tumble that missed part of the sphere).
    """
    rng = np.random.default_rng(seed)
    fieldDevice = np.einsum("nij,j->ni", _randomRotations(count, rng), field)
    if keep is not None:
        fieldDevice = fieldDevice[keep(fieldDevice / np.linalg.norm(fieldDevice, axis=1, keepdims=True))]
    raw = fieldDevice @ magDistortion().T + MAG_OFFSET
    return raw + rng.normal(scale=noise, size=raw.shape)


def _pts(raw: np.ndarray) -> list[tuple[float, float, float]]:
    return [tuple(float(c) for c in p) for p in raw]


def writeTumbleCsv(path, raw: np.ndarray, *, blankEvery: int = 0) -> None:
    """In tumble_capture's own format (its CSV_COLUMNS), blank mag every Nth row."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for i, m in enumerate(raw):
            mag = ["", "", ""] if blankEvery and i % blankEvery == 0 else [repr(float(v)) for v in m]
            writer.writerow([repr(float(i) * 0.02), "tumble", "0.0", "0.0", "9.8", "0.0", "0.0", "0.0", *mag])


class TestFitSensorMag:
    def test_recoversTheSensorsOwnOffsetAndSoftIron(self) -> None:
        fit = fitSensorMag(_pts(tumblePoints()))
        assert np.asarray(fit.offsetUt) == pytest.approx(MAG_OFFSET, abs=0.3)
        product = np.asarray(fit.matrix) @ magDistortion()
        assert product / (np.trace(product) / 3.0) == pytest.approx(np.eye(3), abs=0.01)

    def test_correctedLocusIsASphereAndScaleIsPreserved(self) -> None:
        raw = tumblePoints()
        fit = fitSensorMag(_pts(raw))
        norms = np.linalg.norm((raw - np.asarray(fit.offsetUt)) @ np.asarray(fit.matrix).T, axis=1)
        assert float(np.std(norms) / np.mean(norms)) < 0.01
        assert float(np.linalg.det(np.asarray(fit.matrix))) == pytest.approx(1.0, abs=1e-9)
        assert fit.coverageFraction > 0.95
        assert fit.fieldStrengthWarning is None
        assert fit.forced is False

    def test_aTumbleThatMissedHalfTheSphereIsRefused(self) -> None:
        raw = tumblePoints(keep=lambda u: u[:, 2] > 0.2)
        with pytest.raises(ValueError, match="coverage"):
            fitSensorMag(_pts(raw))

    def test_forceAcceptsLowCoverageAndSaysSo(self) -> None:
        fit = fitSensorMag(_pts(tumblePoints(keep=lambda u: u[:, 2] > 0.2)), force=True)
        assert fit.forced is True
        assert fit.coverageFraction < 0.6

    def test_aSensorCarriedThroughAGradientIsRefused(self) -> None:
        """Rotation in place is the precondition: a field whose MAGNITUDE
        changes +/-20 % across the capture is not an ellipsoid."""
        rng = np.random.default_rng(4)
        raw = tumblePoints()
        scale = 1.0 + 0.2 * np.sin(np.linspace(0.0, 6.0 * np.pi, len(raw)))
        centred = (raw - MAG_OFFSET) * scale[:, None] + MAG_OFFSET
        centred += rng.normal(scale=0.3, size=centred.shape)
        with pytest.raises(ValueError, match="ROTATED IN PLACE"):
            fitSensorMag(_pts(centred))

    def test_aWeakFieldWarnsButFits(self) -> None:
        fit = fitSensorMag(_pts(tumblePoints(field=LOCAL_FIELD_UT * 0.3, noise=0.1)))
        assert fit.fieldStrengthWarning is not None
        assert "outside" in fit.fieldStrengthWarning


class TestCli:
    def test_emitsTheDeviceFrameSensorCalAndSkipsBlankMagRows(self, tmp_path, capsys) -> None:
        raw = tumblePoints()
        path = tmp_path / "tumble.csv"
        writeTumbleCsv(path, raw, blankEvery=10)
        assert len(loadMagPoints(str(path))) == len(raw) - len(raw[::10])

        assert main([str(path)]) == 0
        out = json.loads(capsys.readouterr().out)
        block = out[SENSOR_CAL_KEY]
        assert block["frame"] == "device"
        assert np.asarray(block["offsetUt"]) == pytest.approx(MAG_OFFSET, abs=0.3)

    def test_outputRoundTripsThroughLoadSensorCal(self, tmp_path, capsys) -> None:
        path = tmp_path / "tumble.csv"
        writeTumbleCsv(path, tumblePoints())
        main([str(path)])
        calPath = tmp_path / "cal.json"
        calPath.write_text(capsys.readouterr().out, encoding="utf-8")
        offset, matrix = loadSensorCal(str(calPath))
        fit = fitSensorMag(loadMagPoints(str(path)))
        assert offset == pytest.approx(fit.offsetUt, abs=1e-4)
        assert np.asarray(matrix) == pytest.approx(np.asarray(fit.matrix), abs=1e-6)

    def test_bodyFrameEquivalentIsConjugatedThroughTheLiveMount(self, tmp_path, capsys, monkeypatch) -> None:
        """Ruling 30: body offset = R b, body matrix = R A R^T, under a
        NON-identity mount (under the identity a skipped conversion passes)."""
        monkeypatch.setattr(imu_state_bridge_module, "IMU_BODY_FRAME", NON_IDENTITY_MOUNT)
        r = mountMatrix()
        assert not np.allclose(r, np.eye(3))
        path = tmp_path / "tumble.csv"
        writeTumbleCsv(path, tumblePoints())
        main([str(path)])
        out = json.loads(capsys.readouterr().out)
        b = np.asarray(out[SENSOR_CAL_KEY]["offsetUt"])
        a = np.asarray(out[SENSOR_CAL_KEY]["matrix"])
        body = out["bodyFrameEquivalent"]
        assert np.asarray(body["hardIronUt"]) == pytest.approx(r @ b, abs=1e-3)
        assert np.asarray(body["softIron"]) == pytest.approx(r @ a @ r.T, abs=1e-5)
        assert not np.allclose(np.asarray(body["hardIronUt"]), b, atol=1.0)  # guard: it moved

    def test_refusalIsJsonNotATraceback(self, tmp_path, capsys) -> None:
        path = tmp_path / "tumble.csv"
        writeTumbleCsv(path, tumblePoints(keep=lambda u: u[:, 2] > 0.2))
        assert main([str(path)]) == 1
        assert "coverage" in json.loads(capsys.readouterr().out)["refused"]


class TestLoadSensorCal:
    def _write(self, tmp_path, block) -> str:
        path = tmp_path / "cal.json"
        path.write_text(json.dumps({SENSOR_CAL_KEY: block}), encoding="utf-8")
        return str(path)

    def test_refusesABodyFrameBlock(self, tmp_path) -> None:
        path = self._write(tmp_path, {"frame": "body", "offsetUt": [0, 0, 0], "matrix": np.eye(3).tolist()})
        with pytest.raises(ValueError, match="device"):
            loadSensorCal(path)

    def test_refusesANegativeDeterminant(self, tmp_path) -> None:
        path = self._write(tmp_path, {"frame": "device", "offsetUt": [0, 0, 0], "matrix": (-np.eye(3)).tolist()})
        with pytest.raises(ValueError, match="determinant"):
            loadSensorCal(path)

    def test_refusesAMalformedMatrix(self, tmp_path) -> None:
        path = self._write(tmp_path, {"frame": "device", "offsetUt": [0, 0, 0], "matrix": [[1, 0], [0, 1]]})
        with pytest.raises(ValueError, match="malformed"):
            loadSensorCal(path)

    def test_refusesADocumentWithoutTheBlock(self, tmp_path) -> None:
        path = tmp_path / "cal.json"
        path.write_text(json.dumps({"magCalibration": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match=SENSOR_CAL_KEY):
            loadSensorCal(str(path))
