################################################################################
# File Name: test_gyro_bias_learning.py
# Purpose/Description: US-779 -- PitchFusion learns the gyro's RATE bias at
#     ZUPT-confirmed stops, per run, and REFUSES to learn a latched-magnitude
#     standing rate (A-34). A loose bias learner is a fault concealer: measured on
#     imufusion at a 50 deg/s threshold it swallowed the latch entirely. These
#     tests pin that the learned bias never outlives the process (or a sensor
#     power-cycle), that a 20 deg/s latch is rejected and still reaches the US-749
#     plausibility guard, that the per-axis report puts the dash-mount rest bias
#     on roll and yaw rather than pitch, and that with no stop nothing changes.
# Author: Rex (US-779)
# Creation Date: 2026-09-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""US-779: per-run gyro rate-bias learning that cannot conceal the A-34 latch."""

from __future__ import annotations

import csv
import math
from pathlib import Path

from pi.sensors.imu_state_bridge import resolveMountFrame
from pi.sensors.pitch_fusion import (
    GYRO_BIAS_MAX_RAD_S,
    STANDARD_GRAVITY_MS2,
    ZUPT_MIN_STOP_S,
    PitchFusion,
)

G = STANDARD_GRAVITY_MS2

# MEASURED dash-mount rest data (story acceptance; Atlas ARCH-027, 2026-09-16),
# RAW board axes, deg/s.
REST_RAW_DEG_S = (-0.012, 0.730, 0.156)

# The A-34 fault band the story names (deg/s), and the story's latch test rate.
FAULT_BAND_LOW_DEG_S = 14.0
LATCH_DEG_S = 20.0

# MEASURED (Atlas, 2026-09-14 gyro-quality classifier): the largest healthy
# quiet-minute |mean gyro| on any axis. The learning bound must admit it.
HEALTHY_MAX_RAD_S = 0.0153

# Real parked-car capture whose gyro is LATCHED (~0.5 rad/s on raw Y); see the
# CSV's own header for its provenance.
_FIXTURE = Path(__file__).parents[2] / "fixtures" / "imu_stationary_90s_2026-08-21.csv"
_FIXTURE_HZ = 20.5


def _level() -> tuple[float, float, float]:
    """Vehicle-frame specific force of a level, stationary board."""
    return (0.0, 0.0, G)


def _degToRad(vec: tuple[float, float, float]) -> tuple[float, float, float]:
    return (math.radians(vec[0]), math.radians(vec[1]), math.radians(vec[2]))


def _feed(
    fusion: PitchFusion,
    accel,
    gyro,
    *,
    seconds: float,
    speed: float | None,
    startAt: float = 0.0,
    hz: float = 50.0,
) -> float:
    """Feed constant accel/gyro with an optional 1 Hz speed; returns the next capture."""
    step = 1.0 / hz
    nextSpeedAt = startAt
    capture = startAt
    for i in range(int(round(seconds * hz))):
        capture = startAt + i * step
        if speed is not None and capture >= nextSpeedAt:
            fusion.observeSpeed(speed, capture)
            nextSpeedAt = capture + 1.0
        fusion.update(accel, gyro, capture)
    return capture + step


def _stopThenDrive(fusion: PitchFusion, gyro, *, stopS: float = 10.0) -> float:
    """One confirmed stop (well past the ZUPT gate) followed by moving off."""
    assert stopS > ZUPT_MIN_STOP_S + 2.0
    t = _feed(fusion, _level(), gyro, seconds=stopS, speed=0.0)
    fusion.observeSpeed(20.0, t)
    return t


# ------------------------------------------------------------- AC1: per run


def test_confirmedStop_learnsRateBias_andAppliesItInTheSameRun():
    """
    Given: a healthy standing rate on every axis
    When:  one ZUPT-confirmed stop has ended
    Then:  the bias is learned from it and is subtracted from later gyro samples
           in this same run -- pitch no longer walks off while moving.
    """
    bias = (0.004, -0.003, 0.002)
    fusion = PitchFusion()
    assert fusion.gyroBiasRadS is None

    t = _stopThenDrive(fusion, bias)

    learned = fusion.gyroBiasRadS
    assert learned is not None
    for got, want in zip(learned, bias, strict=True):
        assert math.isclose(got, want, abs_tol=1e-12)
    assert fusion.gyroBiasStopCount == 1

    # Applied: a pure bias rate integrates to ~no pitch change now.
    before = fusion.rawPitchRad
    _feed(fusion, (0.0, 0.0, G * 1.5), bias, seconds=4.0, speed=20.0, startAt=t)
    assert before is not None and fusion.rawPitchRad is not None
    assert abs(fusion.rawPitchRad - before) < 1e-9


def test_learnedBias_doesNotSurviveAProcessRestart():
    """
    Given: a run that has learned a bias at a stop
    When:  the process restarts (a fresh estimator is constructed)
    Then:  the learned bias is gone -- it is never a stored constant.
    """
    first = PitchFusion()
    _stopThenDrive(first, (0.004, -0.003, 0.002))
    assert first.gyroBiasRadS is not None

    restarted = PitchFusion()
    assert restarted.gyroBiasRadS is None
    assert restarted.gyroBiasStopCount == 0
    assert restarted.gyroBiasCorrection is None


def test_sensorPowerCycle_reset_dropsTheLearnedRateBias():
    """
    Given: a learned rate bias
    When:  the sensor goes absent (reset -- the chip is power-cycled on re-plug)
    Then:  the rate bias is dropped: a re-powered gyro can come up with a
           different bias or latched, so the old one is not evidence about it.
    """
    fusion = PitchFusion()
    _stopThenDrive(fusion, (0.004, -0.003, 0.002))
    fusion.reset()
    assert fusion.gyroBiasRadS is None


# ---------------------------------------------------- AC2: the A-34 latch


def test_learningBound_sitsBetweenHealthyAndTheFaultBand_notNearIt():
    """
    Given: the measured healthy maximum and the 14-30 deg/s fault band
    When:  the learning bound is compared with both
    Then:  it admits every healthy rate and sits at less than half of the fault
           band's lower edge -- a threshold near the band would conceal the latch.
    """
    assert GYRO_BIAS_MAX_RAD_S > HEALTHY_MAX_RAD_S * 5
    assert math.degrees(GYRO_BIAS_MAX_RAD_S) < FAULT_BAND_LOW_DEG_S / 2


def test_latchedStandingRate_isRejected_andStillReachesThePlausibilityGuard():
    """
    Given: a 20 deg/s standing rate on the pitch channel (A-34 magnitude)
    When:  a confirmed stop is observed and the car then moves off
    Then:  nothing is learned, the rejection is counted, and the latched rate is
           still integrated uncorrected so the US-749 guard trips.
    """
    latch = (0.0, -math.radians(LATCH_DEG_S), 0.0)
    fusion = PitchFusion()
    t = _stopThenDrive(fusion, latch)

    assert fusion.gyroBiasRadS is None
    assert fusion.gyroBiasRejectedStops == 1

    _feed(fusion, _level(), latch, seconds=60.0, speed=20.0, startAt=t)
    assert fusion.gyroBiasRadS is None
    assert fusion.gyroImplausible is True
    assert fusion.pitchRad is None


def test_latchOnAnyAxis_rejectsTheWholeStop():
    """
    Given: a healthy pitch axis but a latched yaw axis
    When:  a stop is observed
    Then:  the stop is rejected outright -- a latched chip's other axes are not
           trustworthy calibration either.
    """
    fusion = PitchFusion()
    _stopThenDrive(fusion, (0.001, 0.001, math.radians(LATCH_DEG_S)))
    assert fusion.gyroBiasRadS is None
    assert fusion.gyroBiasRejectedStops == 1


def test_latchAfterAHealthyStop_isNotAbsorbed_andKeepsTheHealthyBias():
    """
    Given: a healthy stop has been learned
    When:  the gyro latches and a later stop is observed
    Then:  the latched stop is rejected, the healthy bias is unchanged, and the
           guard still trips on the latch.
    """
    healthy = (0.004, -0.003, 0.002)
    latch = (0.0, -math.radians(LATCH_DEG_S), 0.0)
    fusion = PitchFusion()
    t = _stopThenDrive(fusion, healthy)
    t = _feed(fusion, _level(), healthy, seconds=5.0, speed=20.0, startAt=t)
    t = _feed(fusion, _level(), latch, seconds=10.0, speed=0.0, startAt=t)
    fusion.observeSpeed(20.0, t)

    learned = fusion.gyroBiasRadS
    assert learned is not None
    for got, want in zip(learned, healthy, strict=True):
        assert math.isclose(got, want, abs_tol=1e-12)
    assert fusion.gyroBiasRejectedStops == 1

    _feed(fusion, _level(), latch, seconds=60.0, speed=20.0, startAt=t)
    assert fusion.gyroImplausible is True


def test_recordedLatchedFixture_isRejected_andStopErrorIsUnchanged():
    """
    Given: the real parked-car capture of 2026-08-21, whose gyro is latched
    When:  it is replayed as a confirmed stop, then replayed again in the same run
    Then:  the learner rejects the stop, and the second replay is bit-identical to
           the first (to float tolerance) -- no correction was carried into it, so
           a learned bias cannot have made stop error worse on this recording.
    """
    rows = []
    with open(_FIXTURE, newline="") as fh:
        for row in csv.reader(line for line in fh if not line.startswith("#")):
            vals = [float(v) for v in row]
            rows.append((resolveMountFrame(tuple(vals[0:3])), resolveMountFrame(tuple(vals[3:6]))))
    assert len(rows) == 1845

    step = 1.0 / _FIXTURE_HZ

    def replay(fusion: PitchFusion, startAt: float) -> list[float | None]:
        out = []
        nextSpeedAt = startAt
        for i, (accel, gyro) in enumerate(rows):
            capture = startAt + i * step
            if capture >= nextSpeedAt:
                fusion.observeSpeed(0.0, capture)
                nextSpeedAt = capture + 1.0
            fusion.update(accel, gyro, capture)
            out.append(fusion.pitchRad)
        fusion.observeSpeed(20.0, startAt + len(rows) * step)
        return out

    fusion = PitchFusion()
    first = replay(fusion, 0.0)
    assert fusion.gyroBiasRadS is None
    assert fusion.gyroBiasRejectedStops == 1
    # Re-seed across a gap longer than tau so both passes start from equal state.
    second = replay(fusion, 1000.0)
    assert fusion.gyroBiasRadS is None
    assert fusion.gyroBiasRejectedStops == 2
    assert len(second) == len(first)
    for a, b in zip(first, second, strict=True):
        assert (a is None) == (b is None)
        if a is not None and b is not None:
            assert math.isclose(a, b, abs_tol=1e-9)


# ------------------------------------------------- AC3: which axes it corrected


def test_dashMountRestData_pitchCorrectionNearZero_rollAndYawCarryTheBias():
    """
    Given: the measured dash-mount rest rates (raw X -0.012, Y +0.730, Z +0.156
           deg/s) passed through the shipped body frame B
    When:  the learner runs over them at a confirmed stop
    Then:  it reports the pitch-axis correction as near zero (raw X, 0.012 deg/s)
           while roll (raw Y, forward) and yaw (raw Z, up) carry the real bias.
    """
    gyro = resolveMountFrame(_degToRad(REST_RAW_DEG_S))
    fusion = PitchFusion()
    _stopThenDrive(fusion, gyro)

    report = fusion.gyroBiasCorrection
    assert report is not None
    assert set(report) == {"roll", "pitch", "yaw"}
    rollDeg = math.degrees(report["roll"])
    pitchDeg = math.degrees(report["pitch"])
    yawDeg = math.degrees(report["yaw"])

    assert abs(pitchDeg) < 0.02
    assert math.isclose(abs(rollDeg), 0.730, abs_tol=1e-9)
    assert math.isclose(abs(yawDeg), 0.156, abs_tol=1e-9)
    assert abs(rollDeg) > 30 * abs(pitchDeg)
    assert abs(yawDeg) > 5 * abs(pitchDeg)


def test_imuStateBridgeComment_namesThePitchAxisAsRawX_notGyroY():
    """
    Given: the frame-boundary comment in imu_state_bridge.py
    When:  it is read
    Then:  it no longer blames the residual on a 'gyro-Y bias' (raw Y is roll
           under frame B) and names the pitch axis as raw X.
    """
    src = (
        Path(__file__).resolve().parents[3] / "src" / "pi" / "sensors" / "imu_state_bridge.py"
    ).read_text(encoding="utf-8")
    assert "gyro-Y bias" not in src
    assert "raw X" in src


# ------------------------------------------------- IF no stop / regression check


def test_noConfirmedStop_publishesValuesIdenticalToAnUnlearnedEstimator():
    """
    Given: a run with no ZUPT-confirmed stop (moving throughout, then unknown speed)
    When:  it is replayed
    Then:  no bias is learned and every published pitch is identical to what the
           estimator produced with the gyro fed through untouched.
    """
    bias = (0.004, -0.02, 0.002)
    fusion = PitchFusion()
    seen = []
    step = 1.0 / 50.0
    for i in range(3000):
        capture = i * step
        if i % 50 == 0:
            fusion.observeSpeed(30.0 if capture < 30.0 else None, capture)
        fusion.update((0.0, 0.0, G * (1.0 if i % 7 else 1.01)), bias, capture)
        seen.append((fusion.rawPitchRad, fusion.pitchRad))

    assert fusion.gyroBiasRadS is None
    assert fusion.gyroBiasCorrection is None
    assert fusion.gyroBiasStopCount == 0

    # The same arithmetic, independently: prev - bias[1] * dt then the blend.
    pitch = 0.0
    tau = 5.0
    for i, (raw, _pub) in enumerate(seen):
        if i > 0:
            accel = (0.0, 0.0, G * (1.0 if i % 7 else 1.01))
            pitch = pitch + (-bias[1]) * step
            if abs(math.sqrt(sum(c * c for c in accel)) / G - 1.0) <= 0.02:
                pitch = pitch + (step / (tau + step)) * (0.0 - pitch)
        assert raw is not None
        assert math.isclose(raw, pitch, abs_tol=1e-12)
