################################################################################
# File Name: test_ahrs_fusion.py
# Purpose/Description: ARCH-064 Task 3 -- unit tests for AhrsFusion, the x-io
#     Fusion (imufusion) AHRS behind the PitchFusion surface. Runs the REAL
#     library (no fake): the point of the swap is to stop trusting our own
#     maths, so a fake would re-introduce exactly the thing being removed.
#
#     The two sign conversions out of Fusion's NWU Euler angles are PINNED here,
#     not asserted from memory: a static 2-degree nose-up board must read +2
#     (nose-UP positive), and a level board whose field points north-and-left
#     must read nose EAST = 90 degrees (clockwise from north).
#
#     The three review-focus cases are the failure modes the old filter showed on
#     a real drive: a gyro bias drifting the parked grade, a sustained cornering
#     load leaking into pitch, and a transient magnetic spike yanking heading.
# Author: Atlas (ARCH-064)
# Creation Date: 2026-09-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Unit tests for the imufusion-backed AHRS (ARCH-064 Task 3)."""

from __future__ import annotations

import math

import pytest

from pi.sensors.ahrs_fusion import FUSION_VERSION_AHRS, MAG_MAX_COAST_S, AhrsFusion

G = 9.80665
HZ = 50.0
DT = 1.0 / HZ

# A northern-hemisphere field seen by a LEVEL car pointing EAST: the horizontal
# (north) component lies to the car's LEFT, the vertical component points DOWN.
# Body frame is x = forward, y = left, z = up (MEASURED on the car).
EAST_FIELD_UT = (0.0, 22.5, -53.0)


def _tilted(deg: float) -> tuple[float, float, float]:
    """Specific force on a stationary board pitched nose-UP by ``deg``."""
    rad = math.radians(deg)
    return (G * math.sin(rad), 0.0, G * math.cos(rad))


LEVEL = _tilted(0.0)
NO_ROTATION = (0.0, 0.0, 0.0)


def _run(fusion: AhrsFusion, seconds: float, accel, gyro=NO_ROTATION, mag=None, start: float = 0.0) -> float:
    """Feed ``seconds`` of constant samples at HZ; return the next capture time."""
    n = int(round(seconds * HZ))
    t = start
    for _ in range(n):
        fusion.update(accel, gyro, t, mag_ut=mag)
        t += DT
    return t


def _angleDiffDeg(a: float, b: float) -> float:
    """Smallest signed difference a - b on a 360-degree circle."""
    return (a - b + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------
# Surface parity with PitchFusion
# ---------------------------------------------------------------------------


def test_fusionVersionAhrs_isTwo():
    assert FUSION_VERSION_AHRS == 2


def test_pitchRad_isNoneBeforeAnyUpdate():
    fusion = AhrsFusion(sampleHz=HZ)
    assert fusion.pitchRad is None
    assert fusion.rawPitchRad is None
    assert fusion.rollRad is None
    assert fusion.headingDeg is None


def test_parityProperties_haveInertValues():
    fusion = AhrsFusion(sampleHz=HZ)
    _run(fusion, 5.0, LEVEL)
    assert fusion.stopCount == 0
    assert fusion.biasRad == 0.0
    assert fusion.gyroImplausible is False
    fusion.observeSpeed(0.0, 5.0)  # accepted no-op
    fusion.observeSpeed(None, 5.1)
    assert isinstance(fusion.flags, dict)
    assert set(fusion.flags) >= {"startup", "accelerationRecovery", "magneticRecovery", "overrangeRecovery"}


def test_reset_dropsTheAttitude():
    fusion = AhrsFusion(sampleHz=HZ)
    _run(fusion, 5.0, LEVEL, mag=EAST_FIELD_UT)
    assert fusion.pitchRad is not None
    fusion.reset()
    assert fusion.pitchRad is None
    assert fusion.headingDeg is None


def test_malformedAccel_isIgnored():
    fusion = AhrsFusion(sampleHz=HZ)
    t = _run(fusion, 5.0, LEVEL)
    before = fusion.pitchRad
    fusion.update((float("nan"), 0.0, G), NO_ROTATION, t)
    fusion.update(None, NO_ROTATION, t + DT)
    assert fusion.pitchRad == pytest.approx(before)


def test_gyroNone_isAcceptedAndHoldsAttitude():
    fusion = AhrsFusion(sampleHz=HZ)
    _run(fusion, 5.0, _tilted(2.0), gyro=None)
    assert math.degrees(fusion.pitchRad) == pytest.approx(2.0, abs=0.3)


# ---------------------------------------------------------------------------
# Sign conventions (pinned, not recalled)
# ---------------------------------------------------------------------------


def test_staticNoseUp2Deg_readsPlus2():
    fusion = AhrsFusion(sampleHz=HZ)
    _run(fusion, 5.0, _tilted(2.0), gyro=None)
    assert math.degrees(fusion.pitchRad) == pytest.approx(2.0, abs=0.3)
    assert math.degrees(fusion.rawPitchRad) == pytest.approx(2.0, abs=0.3)


def test_roll_leftSideUp_isPositive():
    """Documented NWU roll sign: rotation about +x (forward), left side UP positive."""
    rad = math.radians(5.0)
    # Left side up: the left (+y) axis now points partly UP, so the specific
    # force (gravity's reaction, world up) projects POSITIVELY onto it.
    accel = (0.0, G * math.sin(rad), G * math.cos(rad))
    fusion = AhrsFusion(sampleHz=HZ)
    _run(fusion, 5.0, accel)
    assert math.degrees(fusion.rollRad) == pytest.approx(5.0, abs=0.3)


def test_heading_levelEastField_readsNinety():
    fusion = AhrsFusion(sampleHz=HZ)
    _run(fusion, 5.0, LEVEL, mag=EAST_FIELD_UT)
    assert _angleDiffDeg(fusion.headingDeg, 90.0) == pytest.approx(0.0, abs=2.0)


def test_heading_isNoneWithoutMagnetometer():
    fusion = AhrsFusion(sampleHz=HZ)
    _run(fusion, 5.0, LEVEL)
    assert fusion.pitchRad is not None
    assert fusion.headingDeg is None


def test_declination_shiftsHeadingExactly():
    plain = AhrsFusion(sampleHz=HZ)
    shifted = AhrsFusion(sampleHz=HZ, declinationDeg=-3.5)
    _run(plain, 5.0, LEVEL, mag=EAST_FIELD_UT)
    _run(shifted, 5.0, LEVEL, mag=EAST_FIELD_UT)
    assert _angleDiffDeg(shifted.headingDeg, plain.headingDeg) == pytest.approx(-3.5, abs=1e-6)


# ---------------------------------------------------------------------------
# Magnetometer calibration: m_c = S . (m_u - h)
# ---------------------------------------------------------------------------


def test_hardIron_calibratedMatchesCleanField():
    hard = (10.0, -5.0, 0.0)
    dirty = tuple(f + h for f, h in zip(EAST_FIELD_UT, hard, strict=True))
    clean = AhrsFusion(sampleHz=HZ)
    calibrated = AhrsFusion(sampleHz=HZ, hardIronUt=hard)
    _run(clean, 5.0, LEVEL, mag=EAST_FIELD_UT)
    _run(calibrated, 5.0, LEVEL, mag=dirty)
    assert _angleDiffDeg(calibrated.headingDeg, clean.headingDeg) == pytest.approx(0.0, abs=0.1)


def test_hardIron_uncalibratedDirtyField_isWrong():
    """Negative control: the hard-iron offset DOES move heading when not removed."""
    hard = (10.0, -5.0, 0.0)
    dirty = tuple(f + h for f, h in zip(EAST_FIELD_UT, hard, strict=True))
    clean = AhrsFusion(sampleHz=HZ)
    uncal = AhrsFusion(sampleHz=HZ)
    _run(clean, 5.0, LEVEL, mag=EAST_FIELD_UT)
    _run(uncal, 5.0, LEVEL, mag=dirty)
    assert abs(_angleDiffDeg(uncal.headingDeg, clean.headingDeg)) > 5.0


def test_softIron_isAppliedAfterHardIron():
    hard = (4.0, 2.0, -1.0)
    soft = ((1.0, 0.0, 0.0), (0.0, 0.5, 0.0), (0.0, 0.0, 1.0))
    # Sensor reads y at double scale, plus the hard-iron offset: S.(m_u - h) undoes it.
    raw = (EAST_FIELD_UT[0] + hard[0], 2.0 * EAST_FIELD_UT[1] + hard[1], EAST_FIELD_UT[2] + hard[2])
    clean = AhrsFusion(sampleHz=HZ)
    calibrated = AhrsFusion(sampleHz=HZ, hardIronUt=hard, softIron=soft)
    _run(clean, 5.0, LEVEL, mag=EAST_FIELD_UT)
    _run(calibrated, 5.0, LEVEL, mag=raw)
    assert _angleDiffDeg(calibrated.headingDeg, clean.headingDeg) == pytest.approx(0.0, abs=0.1)


def test_headingCalibrated_onlyForNonDefaultCalibration():
    assert AhrsFusion(sampleHz=HZ).headingCalibrated is False
    assert AhrsFusion(sampleHz=HZ, hardIronUt=(0.0, 0.0, 0.0)).headingCalibrated is False
    assert AhrsFusion(sampleHz=HZ, hardIronUt=(10.0, -5.0, 0.0)).headingCalibrated is True
    assert AhrsFusion(sampleHz=HZ, softIron=((1.1, 0, 0), (0, 1, 0), (0, 0, 1))).headingCalibrated is True


# ---------------------------------------------------------------------------
# Review focus: the failure modes seen on a real drive
# ---------------------------------------------------------------------------


def test_reviewFocus3_gyroBiasOnPitchAxis_stationary120s_staysUnderOneDegree():
    fusion = AhrsFusion(sampleHz=HZ)
    _run(fusion, 120.0, LEVEL, gyro=(0.0, 0.0146, 0.0))
    assert abs(math.degrees(fusion.pitchRad)) < 1.0


def test_reviewFocus2_sustainedLateral03g_20s_pitchUnderTwoDegrees():
    fusion = AhrsFusion(sampleHz=HZ)
    t = _run(fusion, 5.0, LEVEL)
    cornering = (0.0, 0.3 * G, G)
    worst = 0.0
    for _ in range(int(20.0 * HZ)):
        fusion.update(cornering, NO_ROTATION, t)
        t += DT
        worst = max(worst, abs(math.degrees(fusion.pitchRad)))
    assert worst < 2.0


def test_reviewFocus5_halfSecond200uTSpike_headingMovesUnderFiveDegrees():
    fusion = AhrsFusion(sampleHz=HZ)
    t = _run(fusion, 10.0, LEVEL, mag=EAST_FIELD_UT)
    before = fusion.headingDeg
    spike = (EAST_FIELD_UT[0] + 200.0, EAST_FIELD_UT[1], EAST_FIELD_UT[2])
    worst = 0.0
    for _ in range(int(0.5 * HZ)):
        fusion.update(LEVEL, NO_ROTATION, t, mag_ut=spike)
        t += DT
        worst = max(worst, abs(_angleDiffDeg(fusion.headingDeg, before)))
    for _ in range(int(2.0 * HZ)):
        fusion.update(LEVEL, NO_ROTATION, t, mag_ut=EAST_FIELD_UT)
        t += DT
        worst = max(worst, abs(_angleDiffDeg(fusion.headingDeg, before)))
    assert worst < 5.0


def test_realElapsedTime_drivesGyroIntegration():
    """A 20 Hz caller integrates the same rotation as a 50 Hz one: dt is measured."""
    fusion = AhrsFusion(sampleHz=HZ)
    t = _run(fusion, 5.0, LEVEL, mag=EAST_FIELD_UT)
    before = fusion.headingDeg
    # 10 deg/s yaw LEFT (+z, counter-clockwise from above) for 1 s at 20 Hz;
    # the field rotates with the car so the magnetometer agrees.
    rate = math.radians(10.0)
    for i in range(1, 21):
        t += 0.05
        yaw = math.radians(0.5 * i)  # body rotated CCW by yaw -> field appears rotated CW
        c, s = math.cos(yaw), math.sin(yaw)
        mag = (c * EAST_FIELD_UT[0] + s * EAST_FIELD_UT[1], -s * EAST_FIELD_UT[0] + c * EAST_FIELD_UT[1], EAST_FIELD_UT[2])
        fusion.update(LEVEL, (0.0, 0.0, rate), t, mag_ut=mag)
    # Turning left from east heads toward north: heading DECREASES by ~10 deg.
    assert _angleDiffDeg(fusion.headingDeg, before) == pytest.approx(-10.0, abs=1.0)


# ---------------------------------------------------------------------------
# Speed-aided acceleration compensation (ARCH-064 Task 3, C2/C3)
#
# An accelerometer cannot tell gravity from the car's own acceleration. OBD
# SPEED (km/h, ~every 2.3 s) supplies the car's own specific force: forward
# a_long = dv/dt, lateral v * omega_z. Both are subtracted before the AHRS sees
# the accel. Signs are pinned here: each test fails if its sign is flipped.
# ---------------------------------------------------------------------------

SPEED_PERIOD_S = 2.3
KMH_PER_MS = 3.6


def _driveScenario(fusion: AhrsFusion, aLongG: float, seconds: float, *, feedSpeed: bool = True) -> list[tuple[float, float]]:
    """5 s level at rest, then ``seconds`` of forward acceleration ``aLongG`` on flat ground.

    OBD speed is sampled on a fixed 2.3 s grid from t=0 (not phase-aligned with
    the onset, as on the car). Returns (secondsSinceOnset, pitchDeg) per sample
    during the acceleration.
    """
    onset = 5.0
    aMs2 = aLongG * G
    nextSpeed = 0.0
    trace = []
    t = 0.0
    end = onset + seconds
    while t < end - 1e-9:
        if feedSpeed and t >= nextSpeed - 1e-9:
            v = max(0.0, aMs2 * (t - onset))
            fusion.observeSpeed(v * KMH_PER_MS, t)
            nextSpeed += SPEED_PERIOD_S
        accelerating = t >= onset
        accel = (aMs2 if accelerating else 0.0, 0.0, G)
        fusion.update(accel, NO_ROTATION, t)
        if accelerating:
            trace.append((t - onset, math.degrees(fusion.pitchRad)))
        t += DT
    return trace


def test_speedAided_longitudinal015g_8s_pitchUnderTwoDegreesInLast4s():
    trace = _driveScenario(AhrsFusion(sampleHz=HZ), 0.15, 8.0)
    worst = max(abs(p) for s, p in trace if s >= 4.0)
    assert worst < 2.0


def test_speedAided_longitudinal03g_10s_pitchUnderThreeDegreesInLast4s():
    trace = _driveScenario(AhrsFusion(sampleHz=HZ), 0.3, 10.0)
    worst = max(abs(p) for s, p in trace if s >= 6.0)
    assert worst < 3.0


def test_speedAided_longitudinal_uncompensatedControl_isContaminated():
    """Negative control: without speed the same drive DOES read a phantom grade."""
    trace = _driveScenario(AhrsFusion(sampleHz=HZ), 0.15, 8.0, feedSpeed=False)
    worst = max(abs(p) for s, p in trace if s >= 4.0)
    assert worst > 5.0


def test_speedAided_longitudinalAccel_isDerivedFromSpeedAndClamped():
    fusion = AhrsFusion(sampleHz=HZ)
    assert fusion.longitudinalAccelMs2 is None
    fusion.observeSpeed(0.0, 0.0)
    assert fusion.longitudinalAccelMs2 is None  # one sample is not a derivative
    fusion.observeSpeed(36.0, 2.0)  # 0 -> 10 m/s in 2 s
    assert fusion.longitudinalAccelMs2 == pytest.approx(5.0)
    fusion.observeSpeed(None, 3.0)  # ignored
    assert fusion.longitudinalAccelMs2 == pytest.approx(5.0)
    fusion.observeSpeed(0.0, 3.0)  # 10 -> 0 m/s in 1 s = -1.02 g: clamp to 0.6 g
    assert fusion.longitudinalAccelMs2 == pytest.approx(-0.6 * G)


def test_speedAided_lateral_leftTurn_rollAndPitchUnderTwoDegrees():
    """Level car, 15 m/s, left turn omega_z=+0.2 rad/s: accel y = +v*omega_z for 20 s."""
    fusion = AhrsFusion(sampleHz=HZ)
    speed, omega = 15.0, 0.2
    t = 0.0
    nextSpeed = 0.0
    for _ in range(int(5.0 * HZ)):  # settle at speed, straight
        if t >= nextSpeed - 1e-9:
            fusion.observeSpeed(speed * KMH_PER_MS, t)
            nextSpeed += SPEED_PERIOD_S
        fusion.update(LEVEL, NO_ROTATION, t)
        t += DT
    worstRoll = worstPitch = 0.0
    for _ in range(int(20.0 * HZ)):
        if t >= nextSpeed - 1e-9:
            fusion.observeSpeed(speed * KMH_PER_MS, t)
            nextSpeed += SPEED_PERIOD_S
        fusion.update((0.0, speed * omega, G), (0.0, 0.0, omega), t)
        t += DT
        worstRoll = max(worstRoll, abs(math.degrees(fusion.rollRad)))
        worstPitch = max(worstPitch, abs(math.degrees(fusion.pitchRad)))
    assert worstRoll < 2.0
    assert worstPitch < 2.0


def test_speedAided_staleSpeed_equalsUncompensatedFilter():
    """> 3 s without a speed sample: compensation OFF -- it cannot act on old data."""
    aided = AhrsFusion(sampleHz=HZ)
    plain = AhrsFusion(sampleHz=HZ)
    aided.observeSpeed(0.0, 0.0)
    aided.observeSpeed(36.0, 2.0)  # a_long = 5 m/s^2, held
    assert aided.longitudinalAccelMs2 == pytest.approx(5.0)
    t = 5.1  # > 3.0 s after the last speed sample
    for _ in range(int(6.0 * HZ)):
        accel = (0.15 * G, 0.05 * G, G)
        gyro = (0.0, 0.0, 0.1)
        aided.update(accel, gyro, t)
        plain.update(accel, gyro, t)
        t += DT
        if plain.pitchRad is not None:
            assert aided.pitchRad == plain.pitchRad
            assert aided.rollRad == plain.rollRad
    assert aided.flags["speedCompensated"] is False


def test_speedAided_freshSpeed_changesTheOutput():
    """Positive control for the stale test: a FRESH speed does change the output."""
    aided = AhrsFusion(sampleHz=HZ)
    plain = AhrsFusion(sampleHz=HZ)
    aided.observeSpeed(0.0, 0.0)
    aided.observeSpeed(36.0, 2.0)
    t = 2.0
    for _ in range(int(0.9 * HZ)):  # stays within 3 s of the last sample
        accel = (0.15 * G, 0.0, G)
        aided.update(accel, NO_ROTATION, t)
        plain.update(accel, NO_ROTATION, t)
        t += DT
    assert aided.flags["speedCompensated"] is True
    assert aided._ahrs.get_quaternion().tolist() != plain._ahrs.get_quaternion().tolist()


def test_speedAided_gyroNone_skipsCompensation():
    fusion = AhrsFusion(sampleHz=HZ)
    fusion.observeSpeed(0.0, 0.0)
    fusion.observeSpeed(36.0, 2.0)
    fusion.update(LEVEL, None, 2.1)
    assert fusion.flags["speedCompensated"] is False


def test_speedAided_reset_dropsSpeedHistory():
    fusion = AhrsFusion(sampleHz=HZ)
    fusion.observeSpeed(0.0, 0.0)
    fusion.observeSpeed(36.0, 2.0)
    fusion.reset()
    assert fusion.longitudinalAccelMs2 is None


# ---------------------------------------------------------------------------
# Heading coast bound (review fix round 1): between mag readings the heading
# coasts on the gyro -- intended AHRS behaviour -- but for at most
# MAG_MAX_COAST_S; after that an unaided yaw is not a heading and reads None.
# ---------------------------------------------------------------------------


def _coast(fusion: AhrsFusion, seconds: float, start: float) -> float:
    """Feed ``seconds`` of level samples turning at 0.05 rad/s with NO magnetometer."""
    return _run(fusion, seconds, LEVEL, gyro=(0.0, 0.0, 0.05), mag=None, start=start)


def test_magCoastConstant_isFiveSeconds():
    assert MAG_MAX_COAST_S == 5.0


def test_heading_coastsOnGyroWithinBound():
    fusion = AhrsFusion(sampleHz=HZ)
    t = _run(fusion, 5.0, LEVEL, mag=EAST_FIELD_UT)
    lastMag = t - DT
    t = _coast(fusion, 4.9, t)
    assert (t - DT) - lastMag <= 4.9 + 1e-6
    assert fusion.headingDeg is not None


def test_heading_isNonePastCoastBound_andAFreshMagRestoresIt():
    fusion = AhrsFusion(sampleHz=HZ)
    t = _run(fusion, 5.0, LEVEL, mag=EAST_FIELD_UT)
    t = _coast(fusion, 5.1, t)
    assert fusion.headingDeg is None
    assert fusion.pitchRad is not None  # only heading is withheld
    fusion.update(LEVEL, NO_ROTATION, t, mag_ut=EAST_FIELD_UT)
    assert fusion.headingDeg is not None


def test_heading_afterResetWithoutMag_isNone():
    fusion = AhrsFusion(sampleHz=HZ)
    t = _run(fusion, 5.0, LEVEL, mag=EAST_FIELD_UT)
    fusion.reset()
    _run(fusion, 5.0, LEVEL, start=t)
    assert fusion.pitchRad is not None
    assert fusion.headingDeg is None
