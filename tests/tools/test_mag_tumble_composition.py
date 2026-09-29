"""ARCH-064 Task 6b / Ruling 27: stage 1 (hand tumble, sensor-intrinsic) composed
with stage 2 (in-car planar fit) into ONE body-frame ``magCalibration``.

The world is simulated end to end, physically:

* the SENSOR has its own offset ``b_s`` and symmetric soft iron ``D_s`` in its
  DEVICE frame (they rotate with it);
* it is mounted in the car through a NON-identity mount (monkeypatched
  ``IMU_BODY_FRAME``: body = R . device, moving the vertical axis too);
* the CAR has its own hard iron and horizontal soft iron in the BODY frame
  (they do not rotate with a hand-tumbled sensor);
* Earth's field is Chicago's (H 19.4 uT, vertical -49 uT body-up).

Stage 1 tumbles the sensor in place in a fixed local field. Stage 2 drives
circles (no gyro columns: the no-gyro path) at a 2.5 degree nose-up mount
tilt. Both go through the real CLIs, as CSV files. The composed block is then
applied EXACTLY as ``AhrsFusion`` applies it -- ``m_c = S . (m_u - h)`` on the
raw body reading ``m_u = resolveMountFrame(m)`` -- and the heading it yields
is compared with the true heading, at the capture tilt and at a different one.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from contextlib import redirect_stdout

import numpy as np
import pytest

import pi.sensors.imu_state_bridge as imu_state_bridge_module
import tools.imu.fit_mag_calibration as fit_mag_calibration_module
from tests.pi.sensors.test_ellipsoid_fit import MAG_OFFSET, magDistortion
from tests.tools.test_fit_mag_tumble import tumblePoints, writeTumbleCsv
from tools.imu import fit_mag_tumble

NON_IDENTITY_MOUNT = {"forward": "+z", "left": "-x", "up": "-y"}
G = 9.80665
EARTH_H_UT = 19.4
EARTH_V_UT = -49.0
CAR_HARD_IRON_BODY = np.array([8.0, -5.0, 3.0])
_CAR_ROT = math.radians(25.0)
_CAR_U = np.array([[math.cos(_CAR_ROT), -math.sin(_CAR_ROT)], [math.sin(_CAR_ROT), math.cos(_CAR_ROT)]])
# Horizontal-only, symmetric, det 1 (no horizontal:vertical gain change --
# that is Ruling 26's separate, warned problem).
CAR_SOFT_IRON_BODY = np.eye(3)
CAR_SOFT_IRON_BODY[:2, :2] = _CAR_U @ np.diag([1.15, 1.0 / 1.15]) @ _CAR_U.T
CAPTURE_TILT_DEG = 2.5
_NO_GYRO_DT_S = math.radians(1.0) / 0.3


def _bodyBasis(pitchDeg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Body forward/left/up axes in LEVEL (NWU) coordinates, nose-up pitch."""
    t = math.radians(pitchDeg)
    return (
        np.array([math.cos(t), 0.0, math.sin(t)]),
        np.array([0.0, 1.0, 0.0]),
        np.array([-math.sin(t), 0.0, math.cos(t)]),
    )


def _toBody(vLevel: np.ndarray, pitchDeg: float) -> np.ndarray:
    return np.array([vLevel @ axis for axis in _bodyBasis(pitchDeg)])


def _earthLevel(headingDeg: float) -> np.ndarray:
    """Earth's field in the LEVEL frame of a car heading ``headingDeg`` (clockwise from N)."""
    psi = math.radians(headingDeg)
    return np.array([EARTH_H_UT * math.cos(psi), -EARTH_H_UT * math.sin(psi), EARTH_V_UT])


def _bodyField(headingDeg: float, pitchDeg: float) -> np.ndarray:
    """The field AT THE SENSOR, body frame: car iron applied to Earth's field."""
    return CAR_SOFT_IRON_BODY @ _toBody(_earthLevel(headingDeg), pitchDeg) + CAR_HARD_IRON_BODY


def _mountR() -> np.ndarray:
    return fit_mag_tumble.conjugateToBody.__globals__["mountMatrix"]()


def _sensorReading(fieldBody: np.ndarray, r: np.ndarray, noise: np.ndarray) -> np.ndarray:
    """DEVICE-frame reading: m = D_s . (R^T B_body) + b_s + noise."""
    return magDistortion() @ (r.T @ fieldBody) + MAG_OFFSET + noise


def writeDriveCsv(path, r: np.ndarray, *, seed: int = 5) -> None:
    """Two full circles, 1 degree per row, real edr_imu_sample columns, DEVICE frame."""
    rng = np.random.default_rng(seed)
    gravityBody = _toBody(np.array([0.0, 0.0, G]), CAPTURE_TILT_DEG)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ts_capture", "accel_x", "accel_y", "accel_z", "mag_x", "mag_y", "mag_z"])
        for i in range(720):
            accel = r.T @ gravityBody + rng.normal(scale=0.02, size=3)
            mag = _sensorReading(_bodyField(float(i), CAPTURE_TILT_DEG), r, rng.normal(scale=0.3, size=3))
            writer.writerow([repr(i * _NO_GYRO_DT_S), *map(repr, map(float, accel)), *map(repr, map(float, mag))])


def _tumbleInTheCar(r: np.ndarray) -> np.ndarray:
    """Stage-1 tumble at the open door: the LOCAL field (car-bent, fixed in the
    world) seen through random rotations -- tumblePoints already models that."""
    return tumblePoints(field=_bodyField(90.0, 0.0))


def _runCli(module, argv: list[str]) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = module.main(argv)
    return code, buffer.getvalue()


def _headingErrorsDeg(h: np.ndarray, s: np.ndarray, r: np.ndarray, pitchDeg: float) -> np.ndarray:
    """Apply (h, S) as AhrsFusion does to noise-free readings at ``pitchDeg``;
    tilt-compensate with the TRUE attitude; return heading error per heading."""
    forward, left, up = _bodyBasis(pitchDeg)
    errors = []
    for headingDeg in range(0, 360, 5):
        m = _sensorReading(_bodyField(float(headingDeg), pitchDeg), r, np.zeros(3))
        mU = np.asarray(imu_state_bridge_module.resolveMountFrame(tuple(m)))
        mC = s @ (mU - h)
        level = mC[0] * forward + mC[1] * left + mC[2] * up
        got = math.degrees(math.atan2(-level[1], level[0]))
        errors.append((got - headingDeg + 180.0) % 360.0 - 180.0)
    return np.abs(np.asarray(errors))


@pytest.fixture
def mounted(monkeypatch):
    monkeypatch.setattr(imu_state_bridge_module, "IMU_BODY_FRAME", NON_IDENTITY_MOUNT)
    r = _mountR()
    assert not np.allclose(r, np.eye(3))
    return r


def _composed(tmp_path, r: np.ndarray, extraArgs: list[str] | None = None) -> dict:
    tumblePath = tmp_path / "tumble.csv"
    writeTumbleCsv(tumblePath, _tumbleInTheCar(r))
    code, out = _runCli(fit_mag_tumble, [str(tumblePath)])
    assert code == 0, out
    calPath = tmp_path / "sensor_cal.json"
    calPath.write_text(out, encoding="utf-8")

    drivePath = tmp_path / "drive.csv"
    writeDriveCsv(drivePath, r)
    code, out = _runCli(
        fit_mag_calibration_module, [str(drivePath), "--sensor-cal", str(calPath), *(extraArgs or [])]
    )
    assert code == 0, out
    return json.loads(out)


class TestComposition:
    def test_composedBlockRecoversTheTrueHeadingAtTheCaptureTilt(self, tmp_path, mounted) -> None:
        out = _composed(tmp_path, mounted)
        block = out["magCalibration"]
        errors = _headingErrorsDeg(np.asarray(block["hardIronUt"]), np.asarray(block["softIron"]), mounted, CAPTURE_TILT_DEG)
        assert float(errors.max()) < 0.2  # MEASURED 0.07 deg

    def test_composedBlockHoldsAtADifferentTilt(self, tmp_path, mounted) -> None:
        """8 degrees nose-up (a hill) -- the sensor's cross-axis terms would
        leak vertical into horizontal here if stage 1 were not composed in."""
        out = _composed(tmp_path, mounted)
        block = out["magCalibration"]
        errors = _headingErrorsDeg(np.asarray(block["hardIronUt"]), np.asarray(block["softIron"]), mounted, 8.0)
        assert float(errors.max()) < 0.35  # MEASURED 0.18 deg

    def test_composedBeatsThePlanarFitAloneOffLevel(self, tmp_path, mounted) -> None:
        """What stage 1 buys: the same drive fitted WITHOUT --sensor-cal leaves
        the sensor's own cross-axis terms in, and they leak at 8 degrees of
        pitch (MEASURED 0.53 deg vs 0.18 composed)."""
        out = _composed(tmp_path, mounted)
        code, planarOut = _runCli(fit_mag_calibration_module, [str(tmp_path / "drive.csv")])
        assert code == 0
        composed = out["magCalibration"]
        planar = json.loads(planarOut)["magCalibration"]
        eComposed = _headingErrorsDeg(np.asarray(composed["hardIronUt"]), np.asarray(composed["softIron"]), mounted, 8.0)
        ePlanar = _headingErrorsDeg(np.asarray(planar["hardIronUt"]), np.asarray(planar["softIron"]), mounted, 8.0)
        assert float(eComposed.max()) < 0.5 * float(ePlanar.max())

    def test_theStageTwoBlockAloneIsWrongOnRawReadings(self, tmp_path, mounted) -> None:
        """Guard: the car-only block (fitted on stage-1-corrected data) applied
        to RAW readings is wrong -- so the composition is doing real work."""
        out = _composed(tmp_path, mounted)
        car = out["composition"]["carStageMagCalibration"]
        errors = _headingErrorsDeg(np.asarray(car["hardIronUt"]), np.asarray(car["softIron"]), mounted, CAPTURE_TILT_DEG)
        assert float(errors.max()) > 5.0

    def test_outputRecordsBothStagesAndTheFormula(self, tmp_path, mounted) -> None:
        out = _composed(tmp_path, mounted)
        comp = out["composition"]
        assert comp["sensorMagCalibration"]["frame"] == "device"
        assert "carStageMagCalibration" in comp
        assert "R" in comp["formula"]
        assert comp["mount"] == NON_IDENTITY_MOUNT

    def test_aBadSensorCalIsARefusalNotATraceback(self, tmp_path) -> None:
        calPath = tmp_path / "bad.json"
        calPath.write_text(json.dumps({"sensorMagCalibration": {"frame": "body"}}), encoding="utf-8")
        drivePath = tmp_path / "drive.csv"
        writeDriveCsv(drivePath, np.eye(3))
        code, out = _runCli(fit_mag_calibration_module, [str(drivePath), "--sensor-cal", str(calPath)])
        assert code == 1
        assert "device" in json.loads(out)["refused"]


@pytest.mark.parametrize("content", [None, "{not json", b"\xff\xfe\x00garbage"])
def test_aMissingOrUnreadableSensorCalIsARefusalNotATraceback(tmp_path, content) -> None:
    """m2 (fix round 1): a path that does not exist, is not JSON, or is not
    text comes out as the CLI's {"refused": ...} JSON with exit 1."""
    calPath = tmp_path / "sensor_cal.json"
    if isinstance(content, str):
        calPath.write_text(content, encoding="utf-8")
    elif isinstance(content, bytes):
        calPath.write_bytes(content)
    drivePath = tmp_path / "drive.csv"
    writeDriveCsv(drivePath, np.eye(3))
    code, out = _runCli(fit_mag_calibration_module, [str(drivePath), "--sensor-cal", str(calPath)])
    assert code == 1
    assert "sensor_cal.json" in json.loads(out)["refused"]


# --- without --sensor-cal the output is byte-identical to Task 6 (a85d0f16) ----

# sha256 of main([drive.csv])'s stdout, captured from a85d0f16 BEFORE this task
# touched fit_mag_calibration.py, on writeDriveCsv(..., np.eye(3)).
_GOLDEN_STDOUT_SHA256 = "eb37929a84000059774712bf5bb906ed26daf516aa5a527ed433a95028ceb769"


def test_withoutSensorCalTheOutputIsByteIdenticalToTask6(tmp_path) -> None:
    drivePath = tmp_path / "drive.csv"
    writeDriveCsv(drivePath, np.eye(3))
    code, out = _runCli(fit_mag_calibration_module, [str(drivePath)])
    assert code == 0
    assert hashlib.sha256(out.encode("utf-8")).hexdigest() == _GOLDEN_STDOUT_SHA256
    assert "composition" not in json.loads(out)
