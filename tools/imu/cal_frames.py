"""ARCH-064 Task 6b: frame conversion and composition for tumble calibrations.

Ruling 30 (binding): a tumble calibration is FITTED in the DEVICE frame (the
frame the sensor reports, and the frame its own iron and gain errors live in)
and EMITTED in the BODY frame, because ``AhrsFusion`` receives body-frame
vectors: the bridge maps every device reading through
``imu_state_bridge.resolveMountFrame`` before the engine sees it.

With ``R`` the matrix of ``resolveMountFrame`` (body = R . device), a
device-frame correction ``c_dev = A . (x_dev - b)`` becomes, in the body frame,

    c_body = R . A . (x_dev - b) = (R A R^T) . (x_body - R b)

so the body-frame block is ``offset = R . b`` and ``matrix = R . A . R^T``.

Ruling 27, stage 1 -> stage 2 (magnetometer only). The in-car planar fit
(``fit_mag_calibration``, stage 2) runs on data ALREADY corrected by the
tumble's device-frame ``A_s . (m - b_s)`` (stage 1) and returns
``(h_car, S_car)`` for ``S_car . (x - h_car)`` applied to those corrected body
vectors. The ONE block ``AhrsFusion`` applies, ``m_c = S . (m_u - h)`` on the
RAW body reading ``m_u = R m``, must equal stage 2 after stage 1:

    S_car . (R A_s (m - b_s) - h_car)
      = S_car . (A_b (m_u - R b_s) - h_car)                with A_b = R A_s R^T
      = S_car A_b . (m_u - R b_s - A_b^-1 h_car)

so ``S = S_car . A_b`` and ``h = R b_s + A_b^-1 . h_car``.

``R`` is re-derived from ``resolveMountFrame`` on every call -- never cached,
never hard-coded -- so a change to ``IMU_BODY_FRAME`` (A-42: the mount CAN
change) reaches every emitted block, and a test can monkeypatch it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import numpy as np

from pi.sensors import imu_state_bridge

Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]

# The stage-1 sensor-cal document (written by fit_mag_tumble, read by
# fit_mag_calibration --sensor-cal). Kept here so neither tool imports the other.
SENSOR_CAL_KEY = "sensorMagCalibration"
SENSOR_CAL_FRAME = "device"


def mountMatrix() -> np.ndarray:
    """``R`` such that ``resolveMountFrame(v) == R @ v``, from the live mount.

    Column j is ``resolveMountFrame(e_j)``. The mount is a signed axis
    permutation, so ``R`` must be orthonormal; anything else is refused rather
    than conjugated through (``R^T`` would not be its inverse).
    """
    columns = [
        imu_state_bridge.resolveMountFrame(tuple(1.0 if i == j else 0.0 for i in range(3)))
        for j in range(3)
    ]
    r = np.column_stack([np.asarray(c, dtype=float) for c in columns])
    if not np.allclose(r @ r.T, np.eye(3)):
        raise ValueError(f"mount matrix is not orthonormal: {r.tolist()}")
    return r


def _vec(value: Sequence[float], label: str) -> np.ndarray:
    arr = np.asarray(value, dtype=float).reshape(3)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{label} must be finite, got {arr.tolist()}")
    return arr


def _mat(value: Sequence[Sequence[float]], label: str) -> np.ndarray:
    arr = np.asarray(value, dtype=float).reshape(3, 3)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{label} must be finite, got {arr.tolist()}")
    return arr


def conjugateToBody(
    offsetDevice: Sequence[float], matrixDevice: Sequence[Sequence[float]]
) -> tuple[np.ndarray, np.ndarray]:
    """Device-frame ``A . (x - b)`` -> body-frame ``(R b, R A R^T)``."""
    r = mountMatrix()
    b = _vec(offsetDevice, "offset")
    a = _mat(matrixDevice, "matrix")
    return r @ b, r @ a @ r.T


def applyDeviceCorrection(
    vec: Sequence[float], offsetDevice: Sequence[float], matrixDevice: Sequence[Sequence[float]]
) -> Vector3:
    """``A . (v - b)`` on one DEVICE-frame vector (stage 1, before the mount)."""
    out = _mat(matrixDevice, "matrix") @ (np.asarray(vec, dtype=float) - _vec(offsetDevice, "offset"))
    return (float(out[0]), float(out[1]), float(out[2]))


def composeMagCalibration(
    sensorOffsetDevice: Sequence[float],
    sensorMatrixDevice: Sequence[Sequence[float]],
    carHardIronBody: Sequence[float],
    carSoftIronBody: Sequence[Sequence[float]],
) -> tuple[np.ndarray, np.ndarray]:
    """Ruling 27: one body-frame ``(h, S)`` for ``m_c = S . (m_u - h)``.

    ``S = S_car . R A_s R^T`` and ``h = R b_s + (R A_s R^T)^-1 . h_car`` --
    derivation in the module docstring.
    """
    bBody, aBody = conjugateToBody(sensorOffsetDevice, sensorMatrixDevice)
    hCar = _vec(carHardIronBody, "car hard iron")
    sCar = _mat(carSoftIronBody, "car soft iron")
    return bBody + np.linalg.solve(aBody, hCar), sCar @ aBody


def toVector(arr: np.ndarray, digits: int) -> list[float]:
    """Round a 3-vector for a JSON config block."""
    return [round(float(v), digits) for v in arr]


def toMatrix(arr: np.ndarray, digits: int) -> list[list[float]]:
    """Round a 3x3 for a JSON config block."""
    return [[round(float(v), digits) for v in row] for row in arr]


def loadSensorCal(path: str) -> tuple[Vector3, Matrix3]:
    """Read the stage-1 DEVICE-frame ``(offsetUt, matrix)`` this tool emits.

    Raises:
        ValueError: an unreadable or non-JSON file, a missing block, a frame
            other than ``device``, a malformed
            or non-finite offset/matrix, or a matrix determinant <= 0.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # Fix round 1 (m2): a missing, unreadable or non-JSON file is a
        # REFUSAL the CLI reports as JSON, never a traceback.
        raise ValueError(f"{path}: cannot read the sensor cal ({type(exc).__name__}: {exc})") from exc
    block = document.get(SENSOR_CAL_KEY) if isinstance(document, dict) else None
    if not isinstance(block, dict):
        raise ValueError(f"{path}: no '{SENSOR_CAL_KEY}' block (is this fit_mag_tumble output?)")
    if block.get("frame") != SENSOR_CAL_FRAME:
        raise ValueError(
            f"{path}: sensor cal frame is {block.get('frame')!r}; stage 2 applies it "
            f"before the mount mapping, so it must be {SENSOR_CAL_FRAME!r}"
        )
    try:
        offset = np.asarray(block["offsetUt"], dtype=float).reshape(3)
        matrix = np.asarray(block["matrix"], dtype=float).reshape(3, 3)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{path}: malformed sensor cal ({exc})") from exc
    if not (np.all(np.isfinite(offset)) and np.all(np.isfinite(matrix))):
        raise ValueError(f"{path}: sensor cal must be finite")
    if not np.linalg.det(matrix) > 0.0:
        raise ValueError(f"{path}: sensor cal matrix determinant must be > 0")
    rows = [(float(r[0]), float(r[1]), float(r[2])) for r in matrix]
    return (float(offset[0]), float(offset[1]), float(offset[2])), (rows[0], rows[1], rows[2])
