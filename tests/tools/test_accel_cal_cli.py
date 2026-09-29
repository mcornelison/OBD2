"""ARCH-064 Task 6b: ``accel_cal_cli --ellipsoid`` on a tumble capture (Ruling 19:
EXTENDS the ARCH-027 tool; its default sphere+scalar mode is byte-identical).

The capture is a physical tumble in tumble_capture's own CSV format: six held
faces (gyro noise only) and a tumbling phase whose rows carry a real rotation
rate, so the quasi-static gate -- kept as the input gate -- must drop them.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from contextlib import redirect_stdout

import numpy as np
import pytest

import pi.sensors.imu_state_bridge as imu_state_bridge_module
from pi.sensors.accel_cal import STANDARD_GRAVITY_MS2
from tests.pi.sensors.test_ellipsoid_fit import (
    ACCEL_OFFSET,
    _randomUnitVectors,
    accelLikePoints,
    sixFaceDirections,
)
from tools.imu import accel_cal_cli
from tools.imu.cal_frames import mountMatrix
from tools.imu.tumble_capture import CSV_COLUMNS

NON_IDENTITY_MOUNT = {"forward": "+z", "left": "-x", "up": "-y"}


_CORNERS = np.array(
    [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=float
) / np.sqrt(3.0)


def _writeTumble(
    path,
    *,
    faces: int = 6,
    perFace: int = 500,
    tumbleRows: int = 3000,
    seed: int = 8,
    cornerHolds: int = 0,
) -> None:
    """``cornerHolds`` > 0 adds that many still samples at each of the 8 cube
    corners -- the oblique orientations that make cross-axis terms observable."""
    rng = np.random.default_rng(seed)
    directions = sixFaceDirections(perFace, faces=faces)
    if cornerHolds:
        directions = np.vstack([directions, np.repeat(_CORNERS, cornerHolds, axis=0)])
    still = accelLikePoints(directions, seed=seed)
    # Tumbling: gravity in random directions PLUS hand acceleration, turning at 0.3-1.5 rad/s.
    moving = accelLikePoints(_randomUnitVectors(tumbleRows, rng), seed=seed + 1)
    moving += rng.normal(scale=0.8, size=moving.shape)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        t = 0.0
        for i, a in enumerate(still):
            gyro = rng.normal(scale=0.005, size=3)
            writer.writerow([repr(t), f"face_{i // perFace}", *map(repr, map(float, a)), *map(repr, map(float, gyro)), "10.0", "20.0", "-40.0"])
            t += 0.02
        for a in moving:
            axis = rng.normal(size=3)
            gyro = axis / np.linalg.norm(axis) * rng.uniform(0.3, 1.5)
            writer.writerow([repr(t), "tumble", *map(repr, map(float, a)), *map(repr, map(float, gyro)), "", "", ""])
            t += 0.02


def _run(argv: list[str]) -> tuple[int, dict, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = accel_cal_cli.main(argv)
    text = buffer.getvalue()
    return code, json.loads(text), text


class TestEllipsoidMode:
    def test_recoversTheOffsetFromTheHeldFacesOnly(self, tmp_path) -> None:
        path = tmp_path / "tumble.csv"
        _writeTumble(path)
        code, out, _ = _run([str(path), "--ellipsoid"])
        assert code == 0
        assert out["quasiStaticRows"] == 3000  # the tumbling rows were gated out
        dev = out["overall"]["deviceFrame"]
        assert np.asarray(dev["offsetMs2"]) == pytest.approx(ACCEL_OFFSET, abs=0.02)
        assert out["overall"]["orientations"] == 6

    def test_correctedNormsAreGAfterCalibration(self, tmp_path) -> None:
        path = tmp_path / "tumble.csv"
        _writeTumble(path)
        _, out, _ = _run([str(path), "--ellipsoid"])
        overall = out["overall"]
        assert abs(overall["correctedMeanG"] - 1.0) < 0.001
        assert abs(overall["rawMeanG"] - 1.0) > 0.005  # guard: it was not already 1 g

    def test_bodyBlockIsConjugatedThroughANonIdentityMount(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(imu_state_bridge_module, "IMU_BODY_FRAME", NON_IDENTITY_MOUNT)
        r = mountMatrix()
        assert not np.allclose(r, np.eye(3))
        path = tmp_path / "tumble.csv"
        _writeTumble(path)
        _, out, _ = _run([str(path), "--ellipsoid"])
        dev = out["overall"]["deviceFrame"]
        body = out["accelCalibration"]
        b, a = np.asarray(dev["offsetMs2"]), np.asarray(dev["matrix"])
        assert np.asarray(body["offsetMs2"]) == pytest.approx(r @ b, abs=1e-5)
        assert np.asarray(body["matrix"]) == pytest.approx(r @ a @ r.T, abs=1e-5)
        assert not np.allclose(np.asarray(body["offsetMs2"]), b, atol=0.05)  # guard: it moved

    def test_bodyBlockCorrectsBodyFrameGravityTheWayAhrsFusionDoes(self, tmp_path, monkeypatch) -> None:
        """The emitted block, applied to resolveMountFrame(raw) as a_c = M (a - o),
        yields |a_c| = g -- the check AhrsFusion's input actually needs -- in
        EVERY orientation, when the capture held oblique orientations too."""
        monkeypatch.setattr(imu_state_bridge_module, "IMU_BODY_FRAME", NON_IDENTITY_MOUNT)
        path = tmp_path / "tumble.csv"
        _writeTumble(path, cornerHolds=200)
        _, out, _ = _run([str(path), "--ellipsoid"])
        o = np.asarray(out["accelCalibration"]["offsetMs2"])
        m = np.asarray(out["accelCalibration"]["matrix"])
        clean = accelLikePoints(_randomUnitVectors(500, np.random.default_rng(2)), seed=0, noise=0.0)
        errors = [
            abs(np.linalg.norm(m @ (np.asarray(imu_state_bridge_module.resolveMountFrame(tuple(raw))) - o))
                / STANDARD_GRAVITY_MS2 - 1.0)
            for raw in clean
        ]
        assert max(errors) < 0.003

    def test_sixFacesAloneCorrectTheFacesButNotTheCrossAxis(self, tmp_path) -> None:
        """MEASURED limitation, pinned: six axis-aligned faces do not observe
        cross-axis coupling. At the held faces the correction is exact; in an
        oblique orientation it is off by up to the (unobserved) coupling."""
        path = tmp_path / "tumble.csv"
        _writeTumble(path)
        _, out, _ = _run([str(path), "--ellipsoid"])
        o = np.asarray(out["accelCalibration"]["offsetMs2"])
        m = np.asarray(out["accelCalibration"]["matrix"])

        def worst(directions):
            clean = accelLikePoints(directions, seed=0, noise=0.0)
            return max(abs(np.linalg.norm(m @ (a - o)) / STANDARD_GRAVITY_MS2 - 1.0) for a in clean)

        assert worst(sixFaceDirections(1)) < 0.001
        assert worst(_CORNERS) > 0.003

    def test_interleavedSubsetsAgreeWhenObliqueOrientationsWereHeld(self, tmp_path) -> None:
        path = tmp_path / "tumble.csv"
        _writeTumble(path, cornerHolds=200)
        _, out, _ = _run([str(path), "--ellipsoid"])
        assert len(out["interleaved"]) == 4
        assert all("deviceFrame" in s for s in out["interleaved"])
        assert out["stability"]["verdict"] == "stable"
        assert out["stability"]["offsetSpreadMs2"] < 0.02

    def test_facesOnlyIsFlaggedCrossAxisUnobserved(self, tmp_path) -> None:
        """Six faces: offset and per-axis gain agree across subsets, the cross
        terms wander with the noise -- and the verdict SAYS which."""
        path = tmp_path / "tumble.csv"
        _writeTumble(path)
        _, out, _ = _run([str(path), "--ellipsoid"])
        stability = out["stability"]
        assert stability["offsetSpreadMs2"] < 0.02
        assert stability["diagonalSpread"] < 0.002
        assert stability["crossSpread"] >= 0.002
        assert stability["verdict"] == "crossAxisUnobserved"

    def test_fiveFacesIsARefusal(self, tmp_path) -> None:
        path = tmp_path / "tumble.csv"
        _writeTumble(path, faces=5)
        code, out, _ = _run([str(path), "--ellipsoid"])
        assert code == 1
        assert "distinct orientations" in out["overall"]["refused"]
        assert "accelCalibration" not in out


# --- the default (sphere + scalar) mode is byte-identical to a85d0f16 -----------

_GOLDEN_DEFAULT_SHA256 = "26938c51bfab39a3a5d4003dec90ef1b47c5fffcfbb37d25f83ab46f03463ac9"


def _writeAliasCsv(path) -> None:
    """The ARCH-027 export shape this tool has always read."""
    rng = np.random.default_rng(12)
    raw = accelLikePoints(_randomUnitVectors(400, rng), seed=13)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["accel_x_ms2", "accel_y_ms2", "accel_z_ms2", "gyro_x_rads", "gyro_y_rads", "gyro_z_rads"])
        for a in raw:
            writer.writerow([*map(repr, map(float, a)), *map(repr, map(float, rng.normal(scale=0.005, size=3)))])


def test_defaultModeIsByteIdenticalToTask6(tmp_path) -> None:
    path = tmp_path / "capture.csv"
    _writeAliasCsv(path)
    _, _, text = _run([str(path)])
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == _GOLDEN_DEFAULT_SHA256


def test_defaultModeNowReadsTheRealEdrColumnNames(tmp_path) -> None:
    """Ruling 20: the real edr_imu_sample names are accepted (the alias still is)."""
    path = tmp_path / "tumble.csv"
    _writeTumble(path)
    code, out, _ = _run([str(path)])
    assert code == 0
    assert out["totalRows"] == 6000
