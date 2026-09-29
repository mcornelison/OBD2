################################################################################
# File Name: test_ahrs_road_bias_and_gyro_latch.py
# Purpose/Description: ARCH-064 final review (Ruling 35) -- AhrsFusion on the
#     ROAD, with realistic gyro bias, sensor noise and OBD speed on its real
#     ~2.3 s grid. Pins three defects the whole-branch review MEASURED:
#
#       I1  the centripetal term v * omega_z used the RAW gyro, so the gyro bias
#           became a fake lateral acceleration (30 m/s, 0.747 dps bias: 5.77 deg
#           of heading error and 2.28 deg of roll on a STRAIGHT road);
#       I3  Fusion's Bias learner calls anything under 3 dps for 3 s
#           "stationary", so a gentle 1.5 dps highway curve held for 60 s was
#           learned as a -1.5 dps offset (2.97 deg of heading error);
#       I2  gyroImplausible was hard-wired False under the AHRS, so the A-34
#           latched gyro (14-30 dps on a motionless car) published pitch
#           -44..-90 deg with no reason code while PARKED.
#
#     Each test was shown RED against the pre-fix code (see final-fix-report.md).
# Author: Atlas (ARCH-064)
# Creation Date: 2026-09-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""AhrsFusion on the road: bias-corrected compensation, speed-gated bias
learning, and the A-34 parked-gyro latch (ARCH-064 Ruling 35)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from pi.sensors.ahrs_fusion import GYRO_FAULT_WINDOW_S, AhrsFusion
from pi.sensors.gyro_recovery import GYRO_FAULT_MIN_RAD_S

G = 9.80665
HZ = 50.0
DT = 1.0 / HZ
SPEED_PERIOD_S = 2.3  # MEASURED OBD SPEED cadence on the car
KMH_PER_MS = 3.6

# Earth field near the car (uT): horizontal H toward magnetic north, vertical V
# DOWN. Body frame x forward, y left, z up.
FIELD_H_UT = 19.4
FIELD_V_UT = 49.0

# Sensor noise, 1 sigma. Gyro: the healthy parked statistic on record is
# 0.013-0.015 rad/s (A-34 bimodal cut); per-axis white noise well inside it.
GYRO_NOISE_RAD_S = 0.004
ACCEL_NOISE_MS2 = 0.05
MAG_NOISE_UT = 0.3


def _bodyField(headingDeg: float) -> tuple[float, float, float]:
    """The field a LEVEL car pointing ``headingDeg`` (clockwise from north) sees."""
    p = math.radians(headingDeg)
    return (FIELD_H_UT * math.cos(p), FIELD_H_UT * math.sin(p), -FIELD_V_UT)


def _angleDiffDeg(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


class _Road:
    """Drives an AhrsFusion through (seconds, speedStartMs, speedEndMs, yawRateDps)
    segments. ``yawRateDps`` is CLOCKWISE (heading increasing). Speed ramps are
    real longitudinal accelerations and are felt by the accelerometer; the OBD
    speed is integer km/h on a 2.3 s grid, as on the car."""

    def __init__(self, fusion: AhrsFusion, *, gyroBiasRad=(0.0, 0.0, 0.0), seed: int = 64) -> None:
        self.fusion = fusion
        self.bias = np.asarray(gyroBiasRad, dtype=float)
        self.rng = np.random.default_rng(seed)
        self.t = 0.0
        self.psi = 0.0
        self.nextSpeed = 0.0
        self.trace: list[dict] = []

    def run(self, segments, *, feedSpeed: bool = True, latchedGyroRad=None) -> None:
        for seconds, v0, v1, rateDps in segments:
            n = int(round(seconds * HZ))
            aLong = (v1 - v0) / seconds
            for i in range(n):
                v = v0 + aLong * (i / n) * seconds
                if feedSpeed and self.t >= self.nextSpeed - 1e-9:
                    self.fusion.observeSpeed(float(round(v * KMH_PER_MS)), self.t)
                    self.nextSpeed += SPEED_PERIOD_S
                wz = -math.radians(rateDps)  # CCW positive in the body frame
                self.psi = (self.psi + rateDps * DT) % 360.0
                accel = np.array([aLong, v * wz, G]) + self.rng.normal(0.0, ACCEL_NOISE_MS2, 3)
                gyro = np.array([0.0, 0.0, wz]) + self.bias + self.rng.normal(0.0, GYRO_NOISE_RAD_S, 3)
                if latchedGyroRad is not None:
                    gyro = gyro + np.asarray(latchedGyroRad, dtype=float)
                mag = np.array(_bodyField(self.psi)) + self.rng.normal(0.0, MAG_NOISE_UT, 3)
                self.fusion.update(tuple(accel), tuple(gyro), self.t, mag_ut=tuple(mag))
                f = self.fusion
                self.trace.append(
                    {
                        "t": self.t,
                        "v": v,
                        "headErr": None if f.headingDeg is None else _angleDiffDeg(f.headingDeg, self.psi),
                        "roll": None if f.rollRad is None else math.degrees(f.rollRad),
                        "pitch": None if f.pitchRad is None else math.degrees(f.pitchRad),
                        "implausible": f.gyroImplausible,
                    }
                )
                self.t += DT

    def worst(self, key: str, since: float) -> float:
        vals = [abs(r[key]) for r in self.trace if r["t"] >= since and r[key] is not None]
        assert vals, f"no {key} values after t={since}"
        return max(vals)


# ---------------------------------------------------------------------------
# I1 -- the centripetal term must use the BIAS-CORRECTED yaw rate
# ---------------------------------------------------------------------------

# Park long enough for the learner to converge (key-on idle), pull away at a
# realistic 0.15 g, then hold a dead-straight road at 30 m/s (108 km/h).
_PARK_S = 40.0
_RAMP_S = 30.0 / (0.15 * G)


@pytest.mark.parametrize("biasDps", [0.75, 1.0])
def test_straightRoad30ms_realisticZBias_headingAndRollUnderOneDegree(biasDps):
    """A 0.75-1 dps residual z bias at 30 m/s is 0.39-0.52 m/s^2 of FAKE
    lateral force if the raw rate feeds v * omega_z. Bias-corrected, it is
    nothing: the road is straight and level, so heading and roll must stay
    within 1 deg of the truth all the way down it."""
    fusion = AhrsFusion(HZ)
    road = _Road(fusion, gyroBiasRad=(0.0, 0.0, math.radians(biasDps)))
    road.run([(_PARK_S, 0.0, 0.0, 0.0), (_RAMP_S, 0.0, 30.0, 0.0), (120.0, 30.0, 30.0, 0.0)])
    cruiseStart = _PARK_S + _RAMP_S + 10.0
    assert road.worst("headErr", cruiseStart) < 1.0
    assert road.worst("roll", cruiseStart) < 1.0


# ---------------------------------------------------------------------------
# I3 -- a gentle curve at speed must not be learned as gyro bias
# ---------------------------------------------------------------------------


def test_gentleHighwayCurve_isNotLearnedAsBias():
    """1.5 dps held for 60 s at 25 m/s is under Fusion's 3 dps 'stationary'
    threshold. With fresh OBD speed saying the car is moving, the learner must
    not touch the offset -- a real turn is not a bias."""
    fusion = AhrsFusion(HZ)
    road = _Road(fusion, gyroBiasRad=(0.0, 0.0, math.radians(0.3)))
    road.run([(_PARK_S, 0.0, 0.0, 0.0), (25.0 / (0.15 * G), 0.0, 25.0, 0.0), (10.0, 25.0, 25.0, 0.0)])
    before = fusion.gyroOffsetDps
    curveStart = road.t
    road.run([(60.0, 25.0, 25.0, 1.5)])
    after = fusion.gyroOffsetDps
    assert after[2] == pytest.approx(before[2], abs=0.05)
    assert road.worst("headErr", curveStart) < 1.0


def test_parked_stillLearnsTheBias():
    """The speed gate must not switch learning OFF altogether: parked with
    fresh speed 0, a 0.75 dps bias is learned."""
    fusion = AhrsFusion(HZ)
    road = _Road(fusion, gyroBiasRad=(0.0, 0.0, math.radians(0.75)))
    road.run([(_PARK_S, 0.0, 0.0, 0.0)])
    assert fusion.gyroOffsetDps[2] == pytest.approx(0.75, abs=0.1)


def test_noSpeedEverSeen_stillLearnsTheBias():
    """Bench / no OBD: Fusion's own stationary detector is the only evidence."""
    fusion = AhrsFusion(HZ)
    road = _Road(fusion, gyroBiasRad=(0.0, 0.0, math.radians(0.75)))
    road.run([(_PARK_S, 0.0, 0.0, 0.0)], feedSpeed=False)
    assert fusion.gyroOffsetDps[2] == pytest.approx(0.75, abs=0.1)


def test_speedLostWhileMoving_doesNotLearnTheCurve():
    """OBD drops out mid-curve: the last thing known is that the car was
    moving, so the learner stays OFF (documented stale-speed rule)."""
    fusion = AhrsFusion(HZ)
    road = _Road(fusion)
    road.run([(_PARK_S, 0.0, 0.0, 0.0), (25.0 / (0.15 * G), 0.0, 25.0, 0.0), (10.0, 25.0, 25.0, 0.0)])
    before = fusion.gyroOffsetDps
    road.run([(60.0, 25.0, 25.0, 1.5)], feedSpeed=False)
    assert fusion.gyroOffsetDps[2] == pytest.approx(before[2], abs=0.05)


# ---------------------------------------------------------------------------
# I2 -- the A-34 latched gyro must withhold the attitude under the AHRS
# ---------------------------------------------------------------------------

# The recorded fault: a motionless car reporting a constant 14-30 dps.
_LATCHED_Y_RAD = (0.0, math.radians(20.0), 0.0)


def _firstLatch(road: _Road) -> float | None:
    for r in road.trace:
        if r["implausible"]:
            return r["t"]
    return None


def test_latchedGyro_parked_isImplausibleWithinFiveSeconds_andWithholdsAttitude():
    fusion = AhrsFusion(HZ)
    road = _Road(fusion, gyroBiasRad=(0.0, 0.0, math.radians(0.75)))
    road.run([(10.0, 0.0, 0.0, 0.0)], latchedGyroRad=_LATCHED_Y_RAD)
    first = _firstLatch(road)
    assert first is not None and first <= 5.0
    # Once latched it STAYS latched while the fault persists.
    assert all(r["implausible"] for r in road.trace if r["t"] >= first)
    assert fusion.gyroImplausible is True
    assert fusion.pitchRad is None
    assert fusion.rollRad is None
    assert fusion.headingDeg is None
    # The raw attitude is still there for the diagnostic log.
    assert fusion.rawPitchRad is not None


def test_healthyGyro_parkedThenDriving_neverLatches():
    """A healthy gyro with a real 0.75 dps bias, parked for two minutes, then a
    20 dps turn at speed: the turn is REAL rotation and speed says so."""
    fusion = AhrsFusion(HZ)
    road = _Road(fusion, gyroBiasRad=(math.radians(0.3), math.radians(-0.4), math.radians(0.75)))
    road.run(
        [
            (120.0, 0.0, 0.0, 0.0),
            (15.0 / (0.15 * G), 0.0, 15.0, 0.0),
            (9.0, 15.0, 15.0, 20.0),
            (5.0, 15.0, 0.0, 0.0),
            (10.0, 0.0, 0.0, 0.0),
        ]
    )
    assert _firstLatch(road) is None


def test_turnWithStaleSpeed_neverLatches():
    """No speed evidence is not evidence the car is parked."""
    fusion = AhrsFusion(HZ)
    road = _Road(fusion)
    road.run([(10.0, 0.0, 0.0, 0.0), (9.0, 0.0, 0.0, 20.0)], feedSpeed=False)
    assert _firstLatch(road) is None


def test_latch_clearsOnRecovery_andReattitudes():
    """A successful A-34 power cycle is seen by the engine as a parked gyro that
    reads quiet again: the latch clears and the attitude re-converges from the
    accelerometer rather than from the integrated fault."""
    fusion = AhrsFusion(HZ)
    road = _Road(fusion, gyroBiasRad=(0.0, 0.0, math.radians(0.75)))
    road.run([(10.0, 0.0, 0.0, 0.0)], latchedGyroRad=_LATCHED_Y_RAD)
    assert fusion.gyroImplausible is True
    recoveredAt = road.t
    road.run([(15.0, 0.0, 0.0, 0.0)])
    cleared = [r["t"] for r in road.trace if r["t"] >= recoveredAt and not r["implausible"]]
    # The window open at the moment of recovery still holds faulted samples, so
    # clearing takes at most that window plus one full quiet one.
    assert cleared and cleared[0] - recoveredAt <= 2 * GYRO_FAULT_WINDOW_S + 0.5
    assert fusion.gyroImplausible is False
    # Never publish the attitude integrated from the fault: every pitch/roll
    # released after the latch clears is the re-converged one.
    released = [r for r in road.trace if r["t"] >= recoveredAt and r["pitch"] is not None]
    assert released
    assert max(abs(r["pitch"]) for r in released) < 2.0
    assert max(abs(r["roll"]) for r in released) < 2.0
    assert abs(math.degrees(fusion.pitchRad)) < 1.0
    assert abs(math.degrees(fusion.rollRad)) < 1.0


def test_latch_clearsOnReset():
    fusion = AhrsFusion(HZ)
    road = _Road(fusion)
    road.run([(10.0, 0.0, 0.0, 0.0)], latchedGyroRad=_LATCHED_Y_RAD)
    assert fusion.gyroImplausible is True
    fusion.reset()
    assert fusion.gyroImplausible is False


def test_latchThreshold_isTheA34BimodalCut():
    """Reuses the ONE definition -- no second copy of 0.10 rad/s to drift."""
    import pi.sensors.ahrs_fusion as ahrs

    assert ahrs.GYRO_FAULT_MIN_RAD_S is GYRO_FAULT_MIN_RAD_S
