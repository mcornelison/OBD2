"""ARCH-064 Task 6b / Ruling 30: device -> body conjugation and the Ruling 27
stage-1 -> stage-2 composition, tested under a NON-identity mount.

``IMU_BODY_FRAME`` is the identity today, and under the identity every one of
these formulas collapses to "do nothing" -- a skipped conversion would pass.
So every property below is checked with ``IMU_BODY_FRAME`` monkeypatched to a
mount that moves the vertical axis too, and a guard asserts that mount really
is not the identity.
"""

from __future__ import annotations

import numpy as np
import pytest

import pi.sensors.imu_state_bridge as imu_state_bridge_module
from pi.sensors.imu_state_bridge import resolveMountFrame
from tools.imu.cal_frames import (
    applyDeviceCorrection,
    composeMagCalibration,
    conjugateToBody,
    mountMatrix,
)

# forward = device +z, left = device -x, up = device -y: a proper rotation
# (det +1) that moves ALL three axes, including the vertical.
NON_IDENTITY_MOUNT = {"forward": "+z", "left": "-x", "up": "-y"}

_OFFSET = (12.0, -7.0, 20.0)
_MATRIX = (
    (1.04, 0.03, -0.02),
    (0.03, 0.95, 0.015),
    (-0.02, 0.015, 1.01),
)


@pytest.fixture
def nonIdentityMount(monkeypatch):
    monkeypatch.setattr(imu_state_bridge_module, "IMU_BODY_FRAME", NON_IDENTITY_MOUNT)
    r = mountMatrix()
    assert not np.allclose(r, np.eye(3))  # guard: the mount is genuinely not the identity
    assert np.linalg.det(r) == pytest.approx(1.0)
    return r


def _points(count: int = 50, seed: int = 3) -> np.ndarray:
    return np.random.default_rng(seed).normal(scale=40.0, size=(count, 3))


def test_mountMatrixReproducesResolveMountFrame(nonIdentityMount):
    for v in _points():
        assert nonIdentityMount @ v == pytest.approx(np.asarray(resolveMountFrame(tuple(v))))


def test_mountMatrixIsTheIdentityUnderTheShippedMount():
    assert mountMatrix() == pytest.approx(np.eye(3))


def test_conjugationCommutesWithTheMountUnderANonIdentityMount(nonIdentityMount):
    """The defining property: correcting in the device frame and then mapping
    to the body equals mapping to the body and then applying the body block."""
    bBody, aBody = conjugateToBody(_OFFSET, _MATRIX)
    for x in _points():
        viaDevice = np.asarray(resolveMountFrame(applyDeviceCorrection(tuple(x), _OFFSET, _MATRIX)))
        viaBody = aBody @ (np.asarray(resolveMountFrame(tuple(x))) - bBody)
        assert viaBody == pytest.approx(viaDevice, abs=1e-9)


def test_compositionEqualsStageTwoAfterStageOneUnderANonIdentityMount(nonIdentityMount):
    """Ruling 27: S . (m_u - h) on the RAW body reading == S_car . (x - h_car)
    on the stage-1-corrected body reading, for every m."""
    hCar = np.array([8.0, -5.0, 3.0])
    sCar = np.array([[1.1, 0.07, 0.0], [0.07, 0.92, 0.0], [0.0, 0.0, 1.0]])
    h, s = composeMagCalibration(_OFFSET, _MATRIX, hCar, sCar)
    for m in _points():
        stage1Body = np.asarray(resolveMountFrame(applyDeviceCorrection(tuple(m), _OFFSET, _MATRIX)))
        expected = sCar @ (stage1Body - hCar)
        mU = np.asarray(resolveMountFrame(tuple(m)))
        assert s @ (mU - h) == pytest.approx(expected, abs=1e-9)


def test_compositionWithAnIdentitySensorCalIsTheCarFitAlone(nonIdentityMount):
    hCar = (8.0, -5.0, 3.0)
    sCar = ((1.1, 0.07, 0.0), (0.07, 0.92, 0.0), (0.0, 0.0, 1.0))
    h, s = composeMagCalibration((0.0, 0.0, 0.0), np.eye(3), hCar, sCar)
    assert h == pytest.approx(np.asarray(hCar))
    assert s == pytest.approx(np.asarray(sCar))


def test_nonFiniteInputIsRefused():
    with pytest.raises(ValueError, match="finite"):
        conjugateToBody((float("nan"), 0.0, 0.0), np.eye(3))
