################################################################################
# File Name: test_pitch_fusion.py
# Purpose/Description: Unit tests for the US-521 gyro-fused pitch estimator
#     (complementary filter + ZUPT). The headline case is Spool's: an
#     accelerometer cannot distinguish grade from acceleration, so a 0.3 g
#     longitudinal pull on FLAT ground reads as atan(0.3) = 16.7 degrees of
#     climb on any accel-derived tilt. These tests pin that it does not, that a
#     REAL grade still is reported, and that the ZUPT bias update converges the
#     mount tilt out over stops -- including the negative cases that matter most
#     (an absent or STALE OBD speed must never be read as "stopped", or the
#     estimator would hard-correct its pitch to a contaminated accel reading
#     while the car is moving).
# Author: Rex (US-521)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Unit tests for the gyro-fused pitch estimator + ZUPT bias update (US-521)."""

from __future__ import annotations

import math

from pi.sensors.pitch_fusion import (
    DEFAULT_ACCEL_TRUST_BAND,
    DEFAULT_PITCH_TAU_S,
    DEFAULT_ZUPT_MIN_STOPS,
    MAX_GRADE_PITCH_DEG,
    STANDARD_GRAVITY_MS2,
    ZUPT_MIN_STOP_S,
    PitchFusion,
    gradePctFromPitchRad,
    pitchRadFromAccel,
)

G = STANDARD_GRAVITY_MS2

# The failure mode the whole story exists to delete (Spool): atan(0.3) rad.
CONTAMINATION_DEG = math.degrees(math.atan(0.3))  # 16.699...


def _level() -> tuple[float, float, float]:
    """Specific force read by a level, stationary board: +1 g on UP."""
    return (0.0, 0.0, G)


def _tilted(deg: float) -> tuple[float, float, float]:
    """Specific force read by a stationary board pitched nose-UP by ``deg``."""
    rad = math.radians(deg)
    return (G * math.sin(rad), 0.0, G * math.cos(rad))


def _accelerating(gLon: float, tiltDeg: float = 0.0) -> tuple[float, float, float]:
    """Specific force on a board pitched ``tiltDeg`` while pulling ``gLon`` g forward.

    Specific force is ``a_vehicle - g_vector``; a forward pull therefore ADDS to
    the forward component, which is exactly why an accelerometer reads it as
    nose-up tilt. On flat ground gLon=0.3 yields the 16.7-degree phantom.
    """
    fwd, left, up = _tilted(tiltDeg)
    return (fwd + gLon * G, left, up)


def _gyro(pitchRateDegPerS: float) -> tuple[float, float, float]:
    """Vehicle-frame gyro for a nose-up rate of ``pitchRateDegPerS``.

    Right-handed (forward x left = up): a nose point at +forward moves as
    ``omega x r = omega_left * (left x forward) = -omega_left * up``, so a
    NOSE-UP rate is a NEGATIVE left-axis rate.
    """
    return (0.0, -math.radians(pitchRateDegPerS), 0.0)


def _drive(
    fusion: PitchFusion,
    accel,
    *,
    seconds: float,
    startAt: float = 0.0,
    hz: float = 50.0,
    gyro=(0.0, 0.0, 0.0),
    speed: float | None = 40.0,
    speedHz: float = 1.0,
) -> float:
    """Feed a constant accel/gyro (and optional speed) for ``seconds``.

    Returns the capture time just past the last sample, so callers can chain
    legs of a simulated drive without re-deriving the clock.
    """
    step = 1.0 / hz
    speedStep = 1.0 / speedHz if speedHz > 0 else None
    nextSpeedAt = startAt
    capture = startAt
    for i in range(int(round(seconds * hz))):
        capture = startAt + i * step
        if speed is not None and speedStep is not None and capture >= nextSpeedAt:
            fusion.observeSpeed(speed, capture)
            nextSpeedAt = capture + speedStep
        fusion.update(accel, gyro, capture)
    return capture + step


def _stopThenGo(fusion: PitchFusion, accel, *, startAt: float, stopSeconds: float = 6.0) -> float:
    """Simulate one confirmed stop (speed 0) followed by the car pulling away."""
    after = _drive(fusion, accel, seconds=stopSeconds, startAt=startAt, speed=0.0)
    # One moving sample ends the stop and commits the bias observation.
    fusion.observeSpeed(30.0, after)
    return after + 0.02


# ------------------------------------------------------------- pure pitch math


def test_pitchRadFromAccel_levelBoard_isZeroNotNoise():
    """
    Given: a level, stationary board (+1 g straight up)
    When: the accel tilt is computed
    Then: it is exactly zero -- a level board must not read a phantom slope
    """
    assert pitchRadFromAccel(_level()) == 0.0


def test_pitchRadFromAccel_noseUpTenDegrees_isTenDegrees():
    """
    Given: a stationary board pitched nose-up by 10 degrees
    When: the accel tilt is computed
    Then: it reads +10 degrees (positive = climbing)
    """
    assert abs(math.degrees(pitchRadFromAccel(_tilted(10.0))) - 10.0) < 1e-9


def test_pitchRadFromAccel_noseDown_isNegative():
    """
    Given: a stationary board pitched nose-DOWN
    When: the accel tilt is computed
    Then: the sign is negative -- descending is not the same fact as climbing
    """
    assert pitchRadFromAccel(_tilted(-8.0)) < 0.0


def test_pitchRadFromAccel_degenerateVector_isNoneNotZero():
    """
    Given: a free-fall / unreadable specific-force vector (no level reference)
    When: the accel tilt is computed
    Then: it is None -- an absent reference is not a level board
    """
    assert pitchRadFromAccel((0.0, 0.0, 0.0)) is None


def test_pitchRadFromAccel_nonFiniteComponent_isNone():
    """
    Given: a burst carrying a NaN component
    When: the accel tilt is computed
    Then: it is None -- NaN propagates silently through every later sum and
          never compares unequal to itself, so it is rejected at the seam
    """
    assert pitchRadFromAccel((float("nan"), 0.0, G)) is None


def test_gradePctFromPitchRad_tenDegrees_isTanTimesOneHundred():
    """
    Given: a fused pitch of 10 degrees
    When: it is converted to road grade
    Then: grade = tan(pitch) * 100 (the Atlas contract), rounded for display
    """
    expected = round(math.tan(math.radians(10.0)) * 100.0, 1)
    assert gradePctFromPitchRad(math.radians(10.0)) == expected


def test_gradePctFromPitchRad_beyondRange_isNullNotAnAbsurdNumber():
    """
    Given: a pitch past MAX_GRADE_PITCH_DEG, where tan() runs away
    When: it is converted to road grade
    Then: it is None -- a four-digit percentage is not a road grade by any
          reading, and the card must not render it as fact
    """
    assert gradePctFromPitchRad(math.radians(MAX_GRADE_PITCH_DEG + 1.0)) is None


def test_gradePctFromPitchRad_unknownPitch_isNull():
    """
    Given: no fused pitch yet (the estimator has not seeded)
    When: grade is asked for
    Then: it is None -- never a fabricated 0.0 flat road
    """
    assert gradePctFromPitchRad(None) is None


# ----------------------------------------------------------- seeding / honesty


def test_pitchRad_beforeAnySample_isNoneNotZero():
    """
    Given: a freshly constructed estimator
    When: the pitch is read
    Then: it is None -- a zeroed attitude and an unknown attitude must not look
          alike (the same rule the g-meter and the altitude anchor follow)
    """
    assert PitchFusion().pitchRad is None


def test_update_firstTrustedSample_seedsFromTheAccelTilt():
    """
    Given: a stationary board sitting nose-up 3 degrees
    When: the first sample arrives
    Then: the estimator seeds AT that tilt rather than settling in from a
          fabricated origin of zero
    """
    fusion = PitchFusion()
    fusion.update(_tilted(3.0), (0.0, 0.0, 0.0), 0.0)
    assert abs(math.degrees(fusion.pitchRad) - 3.0) < 1e-6


def test_update_firstSampleWhileAccelerating_doesNotSeed():
    """
    Given: the process starts mid-drive, under a 0.3 g pull (accel contaminated)
    When: the first sample arrives
    Then: the pitch stays unknown -- seeding from a contaminated reading would
          bake the 16.7-degree phantom in as the origin the gyro integrates from
    """
    fusion = PitchFusion()
    fusion.update(_accelerating(0.3), (0.0, 0.0, 0.0), 0.0)
    assert fusion.pitchRad is None


# ---------------------------------------------------- AC5: the 0.3 g phantom


def test_update_longitudinalPointThreeG_onFlatGround_isNotReadAsASixteenDegreeClimb():
    """
    Given: a level, seeded estimator on FLAT ground
    When: the car pulls a sustained 0.3 g for 10 s (an on-ramp), gyro reads zero
          because the chassis is not actually rotating
    Then: the pitch stays ~0 -- the accel correction is gated off because
          |accel| = 1.044 g is not near 1 g, so the 16.7-degree phantom that an
          accel-derived tilt would integrate never enters the estimate
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    _drive(fusion, _accelerating(0.3), seconds=10.0, startAt=0.02, speed=None)

    pitchDeg = math.degrees(fusion.pitchRad)
    assert abs(pitchDeg) < 1.0, f"0.3 g read as {pitchDeg:.1f} deg of pitch"
    assert abs(pitchDeg - CONTAMINATION_DEG) > 10.0


def test_update_longitudinalBraking_isNotReadAsADescent():
    """
    Given: a level, seeded estimator
    When: the car brakes hard (-0.4 g) for 5 s
    Then: the pitch stays ~0 -- the gate is on |accel| magnitude, so it rejects
          contamination in BOTH directions, not just under power
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    _drive(fusion, _accelerating(-0.4), seconds=5.0, startAt=0.02, speed=None)

    assert abs(math.degrees(fusion.pitchRad)) < 1.0


def test_update_realGradeAtSteadySpeed_isStillReported():
    """
    Given: a level, seeded estimator
    When: the car climbs a genuine 10-degree grade at STEADY speed, so |accel|
          is exactly 1 g and the reading is uncontaminated
    Then: the pitch converges on the real 10 degrees -- the gate must reject
          acceleration without also refusing to ever see a hill
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    _drive(
        fusion,
        _tilted(10.0),
        seconds=DEFAULT_PITCH_TAU_S * 6,
        startAt=0.02,
        speed=None,
    )

    assert abs(math.degrees(fusion.pitchRad) - 10.0) < 0.5


# -------------------------------------------------------------- gyro fusion


def test_update_gyroRate_isIntegratedWhileTheAccelIsUntrusted():
    """
    Given: a seeded estimator whose accel is contaminated (0.5 g pull) so the
           accel correction is gated OFF for the whole leg
    When: the gyro reports a real 2 deg/s nose-up rate for 3 s
    Then: the pitch tracks ~6 degrees -- gyro-alone is exactly what carries the
          short term, and without it the estimate would be frozen
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    _drive(
        fusion,
        _accelerating(0.5),
        seconds=3.0,
        startAt=0.02,
        gyro=_gyro(2.0),
        speed=None,
    )

    assert abs(math.degrees(fusion.pitchRad) - 6.0) < 0.5


def test_update_positiveLeftAxisRate_isNoseDown():
    """
    Given: a seeded estimator with a contaminated accel (gyro-only leg)
    When: the raw gyro reports a POSITIVE left-axis rate
    Then: the pitch goes NEGATIVE -- the right-hand-rule sign must match the
          accel tilt convention, or fusion fights itself instead of agreeing
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    _drive(
        fusion,
        _accelerating(0.5),
        seconds=2.0,
        startAt=0.02,
        gyro=(0.0, math.radians(3.0), 0.0),
        speed=None,
    )

    assert fusion.pitchRad < 0.0


def test_update_gyroAbsent_stillCorrectsFromATrustedAccel():
    """
    Given: a partially unreadable burst (no gyro vector paired with the accel)
    When: a trusted, stationary 6-degree tilt is fed for several time constants
    Then: the pitch still converges -- a missing gyro degrades to the previous
          accel-led behaviour rather than freezing the instrument
    """
    fusion = PitchFusion()
    fusion.update(_level(), None, 0.0)
    _drive(
        fusion,
        _tilted(6.0),
        seconds=DEFAULT_PITCH_TAU_S * 6,
        startAt=0.02,
        gyro=None,
        speed=None,
    )

    assert abs(math.degrees(fusion.pitchRad) - 6.0) < 0.5


def test_update_captureGapLongerThanTau_reseedsRatherThanIntegratingAcrossIt():
    """
    Given: a seeded estimator and then a long gap in the sample stream
    When: the next sample arrives past the time constant, on a 12-degree tilt
    Then: the estimate SEEDS at the new tilt instead of blending across a gap
          whose gyro history it never saw (the filter's memory is worthless)
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    fusion.update(_tilted(12.0), (0.0, 0.0, 0.0), DEFAULT_PITCH_TAU_S * 3)

    assert abs(math.degrees(fusion.pitchRad) - 12.0) < 1e-6


def test_update_runawayGyro_isClampedToVertical():
    """
    Given: a seeded estimator fed a stuck/garbage gyro rate for a long time
    When: the integration would otherwise wind past vertical without bound
    Then: the pitch is clamped at +/-90 degrees -- an unbounded attitude makes
          every downstream tan() nonsense rather than merely wrong
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    _drive(
        fusion,
        _accelerating(0.9),
        seconds=30.0,
        startAt=0.02,
        gyro=_gyro(45.0),
        speed=None,
    )

    assert abs(fusion.pitchRad) <= math.pi / 2 + 1e-9


def test_update_nonFiniteAccel_isIgnoredNotFolded():
    """
    Given: a seeded, level estimator
    When: a burst arrives with an infinite component
    Then: the pitch is unchanged -- a malformed sample must never be able to
          poison the running estimate (the writer would blow up on it anyway)
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    before = fusion.pitchRad
    fusion.update((float("inf"), 0.0, G), (0.0, 0.0, 0.0), 0.02)

    assert fusion.pitchRad == before


# --------------------------------------------------------------------- ZUPT


def test_zupt_speedZeroForLessThanTheGate_isNotAConfirmedStop():
    """
    Given: the car is stopped for less than the [EXACT:3] s ZUPT gate
    When: samples are fed for that window
    Then: no bias observation is recorded -- a rolling pause at a stop sign is
          not the pure-gravity window the correction depends on
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    after = _drive(
        fusion, _level(), seconds=ZUPT_MIN_STOP_S - 1.0, startAt=0.02, speed=0.0
    )
    fusion.observeSpeed(25.0, after)

    assert fusion.stopCount == 0


def test_zupt_speedZeroPastTheGate_isAConfirmedStop():
    """
    Given: the car is stopped well past the [EXACT:3] s gate
    When: it then pulls away
    Then: exactly one bias observation is recorded for that stop
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    _stopThenGo(fusion, _level(), startAt=0.02, stopSeconds=ZUPT_MIN_STOP_S + 3.0)

    assert fusion.stopCount == 1


def test_zupt_oneLongStop_countsOnceNotOncePerSample():
    """
    Given: a single 60 s stop sampled at 50 Hz (3000 samples)
    When: the car pulls away
    Then: it counts as ONE observation -- Spool's mean is over STOPS, and
          per-sample accumulation would let one long red light outvote a
          whole drive's worth of stoplights
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    _stopThenGo(fusion, _level(), startAt=0.02, stopSeconds=60.0)

    assert fusion.stopCount == 1


def test_zupt_convergesTheMountTiltBiasOverManyStops():
    """
    Given: the board is bolted in 4 degrees nose-up, so EVERY reading carries a
           constant +4-degree offset that is mount tilt, not road grade
    When: the car makes enough city stops for the mean to converge
    Then: the reported pitch at rest on flat ground is ~0 -- which is the whole
          point of ZUPT: stoplights are the free calibration signal
    """
    mountTilt = 4.0
    fusion = PitchFusion()
    fusion.update(_tilted(mountTilt), (0.0, 0.0, 0.0), 0.0)

    at = 0.02
    for _ in range(DEFAULT_ZUPT_MIN_STOPS):
        at = _drive(fusion, _tilted(mountTilt), seconds=20.0, startAt=at, speed=35.0)
        at = _stopThenGo(fusion, _tilted(mountTilt), startAt=at)

    assert abs(math.degrees(fusion.biasRad) - mountTilt) < 0.1
    assert abs(math.degrees(fusion.pitchRad)) < 0.1


def test_zupt_belowTheMinimumStopCount_appliesNoBias():
    """
    Given: only ONE stop has been observed, and it happened on a real hill
    When: the pitch is read
    Then: no bias is subtracted -- a single stop cannot separate mount tilt
          from the slope you are parked on, so claiming a bias from it would
          be inventing a calibration we have not measured
    """
    fusion = PitchFusion()
    fusion.update(_tilted(7.0), (0.0, 0.0, 0.0), 0.0)
    _stopThenGo(fusion, _tilted(7.0), startAt=0.02)

    assert fusion.stopCount == 1
    assert fusion.biasRad == 0.0
    assert abs(math.degrees(fusion.pitchRad) - 7.0) < 0.1


def test_zupt_hardCorrectsTheGyroDriftAtAConfirmedStop():
    """
    Given: an estimator whose pitch has been dragged 8 degrees off by a stuck
           gyro during a leg where the accel was contaminated
    When: the car reaches a confirmed stop on level ground
    Then: the pitch snaps back to the measured tilt -- at zero velocity the
          accel IS pure gravity, so this is the one uncontaminated fix the
          estimator ever gets, and it must not be a slow blend
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    at = _drive(
        fusion, _accelerating(0.6), seconds=4.0, startAt=0.02, gyro=_gyro(2.0), speed=None
    )
    assert math.degrees(fusion.pitchRad) > 5.0  # drifted, as set up

    _drive(fusion, _level(), seconds=ZUPT_MIN_STOP_S + 2.0, startAt=at, speed=0.0)

    assert abs(math.degrees(fusion.pitchRad)) < 0.5


def test_zupt_staleSpeedReading_doesNotHoldAConfirmedStop():
    """
    Given: the car sits at a light long enough to confirm a stop on LEVEL
           ground, and the OBD link then DROPS mid-stop -- so the last thing
           the estimator ever heard was "speed 0"
    When: the car pulls away and climbs a REAL 10-degree grade at steady speed,
          which is a TRUSTED accel reading (the magnitude gate cannot help here)
    Then: the stop is retired once the speed evidence goes stale, so the pitch
          is only slow-blended toward the hill rather than SNAPPED to it, and
          the one committed bias observation is the level stop -- not the hill.
          A stale speed is not evidence of a stop; honouring it would keep
          hard-correcting the attitude for the rest of the drive, with more
          confidence than the drift it was fixing.
    """
    fusion = PitchFusion(zuptSpeedMaxAgeSec=1.0, zuptMinStops=1)
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    at = _drive(fusion, _level(), seconds=ZUPT_MIN_STOP_S + 3.0, startAt=0.02, speed=0.0)

    # Link is gone. Nothing but IMU bursts from here -- first level, so the
    # freshness window expires, then a genuine hill.
    at = _drive(fusion, _level(), seconds=1.5, startAt=at, speed=None)
    _drive(fusion, _tilted(10.0), seconds=2.0, startAt=at, speed=None)

    pitchDeg = math.degrees(fusion.pitchRad)
    assert pitchDeg < 5.0, f"stale-speed ZUPT snapped pitch to {pitchDeg:.1f} deg"
    assert fusion.stopCount == 1
    assert abs(math.degrees(fusion.biasRad)) < 0.5


def test_zupt_oneZeroReadingThenSilence_neverConfirmsAStop():
    """
    Given: exactly ONE "speed 0" reading arrives and the link then goes silent.
           The freshness window is set WIDE on purpose, so that guard cannot be
           what saves us -- this test is about the gate itself.
    When: samples keep flowing for far longer than the [EXACT:3] s gate
    Then: no stop is ever confirmed -- the gate needs zero speed OBSERVED
          across the window, not merely the window's worth of time ELAPSED
          since one reading. Elapsed time after a single sample is evidence
          only that we stopped being told, not that the car stayed still.
    """
    fusion = PitchFusion(zuptSpeedMaxAgeSec=120.0, zuptMinStops=1)
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    fusion.observeSpeed(0.0, 0.0)
    _drive(fusion, _level(), seconds=60.0, startAt=0.02, speed=None)
    fusion.observeSpeed(40.0, 61.0)

    assert fusion.stopCount == 0


def test_zupt_gateNeedsThreeSecondsOfOBSERVEDzero_notThreeSinceTheFirstOne():
    """
    Given: a SLOW speed poll -- only two zero readings, 2 s apart, so there is
           two seconds of evidence that the car was stopped
    When: the car pulls away shortly after the second reading
    Then: no stop is confirmed. Spool's gate is 3 s of zero SPEED, and 2 s of
          evidence plus 1 s of hope is not that. Sampling the gate against
          wall-clock rather than against observed readings would let a slow or
          jittery SPEED poll manufacture stops that never happened.
    """
    fusion = PitchFusion(zuptSpeedMaxAgeSec=4.0, zuptMinStops=1)
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    fusion.observeSpeed(0.0, 0.0)
    _drive(fusion, _level(), seconds=2.0, startAt=0.02, speed=None)
    fusion.observeSpeed(0.0, 2.0)
    at = _drive(fusion, _level(), seconds=1.9, startAt=2.02, speed=None)
    fusion.observeSpeed(40.0, at)

    assert fusion.stopCount == 0


def test_zupt_noSpeedSourceAtAll_neverConfirmsAStop():
    """
    Given: a bench/no-OBD Pi where raw.obd.SPEED never publishes
    When: a long run of samples is fed
    Then: no stop is ever confirmed -- an ABSENT speed must never resolve as
          "speed 0", which is the same absence-is-not-zero rule the rest of
          the instrument follows
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    _drive(fusion, _level(), seconds=60.0, startAt=0.02, speed=None)

    assert fusion.stopCount == 0
    assert fusion.biasRad == 0.0


def test_zupt_unreadableSpeedSample_neitherStartsAStopNorRefreshesFreshness():
    """
    Given: the OBD layer publishes a null/garbage SPEED value
    When: it is observed
    Then: it starts no stop -- an unreadable speed is silence, not zero
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    at = 0.02
    for _ in range(10):
        fusion.observeSpeed(None, at)
        at = _drive(fusion, _level(), seconds=1.0, startAt=at, speed=None)

    assert fusion.stopCount == 0


def test_zupt_speedResumes_endsTheStopImmediately():
    """
    Given: a confirmed stop in progress
    When: the car starts moving again and then stops only briefly
    Then: the second, too-short pause is NOT folded into the first stop --
          the gate restarts from the moment speed returns to zero
    """
    fusion = PitchFusion()
    fusion.update(_level(), (0.0, 0.0, 0.0), 0.0)
    at = _stopThenGo(fusion, _level(), startAt=0.02, stopSeconds=ZUPT_MIN_STOP_S + 2.0)
    at = _drive(fusion, _level(), seconds=5.0, startAt=at, speed=30.0)
    at = _drive(fusion, _level(), seconds=ZUPT_MIN_STOP_S - 1.0, startAt=at, speed=0.0)
    fusion.observeSpeed(30.0, at)

    assert fusion.stopCount == 1


def test_zupt_windowIsRolling_soAnOldMountTiltAgesOut():
    """
    Given: the board is physically remounted (tilt changes 4 -> -3 degrees)
    When: enough new stops accumulate to fill the rolling window
    Then: the bias follows the new mount -- a cumulative mean over all history
          would freeze on the old calibration and never recover
    """
    fusion = PitchFusion(zuptWindowStops=4, zuptMinStops=2)
    fusion.update(_tilted(4.0), (0.0, 0.0, 0.0), 0.0)
    at = 0.02
    for _ in range(4):
        at = _stopThenGo(fusion, _tilted(4.0), startAt=at)
    assert abs(math.degrees(fusion.biasRad) - 4.0) < 0.1

    fusion.update(_tilted(-3.0), (0.0, 0.0, 0.0), at)
    for _ in range(4):
        at = _stopThenGo(fusion, _tilted(-3.0), startAt=at)

    assert abs(math.degrees(fusion.biasRad) + 3.0) < 0.1


# ------------------------------------------------------------- configuration


def test_accelTrustBand_rejectsTheAccelerationItWasSizedFor():
    """
    Given: the default trust band
    When: it is compared against the specific force under a 0.3 g pull
    Then: the band is TIGHTER than that reading's 4.4% magnitude excess -- the
          AC5 guarantee is a property of the constant, not an accident of the
          simulation, so it is asserted directly
    """
    excess = math.hypot(0.3, 1.0) - 1.0
    assert DEFAULT_ACCEL_TRUST_BAND < excess


def test_zuptMinStopSeconds_isSpoolsExactThreeSecondGate():
    """
    Given: Spool's [EXACT:3] s zero-velocity gate
    When: the shipped constant is read
    Then: it is 3.0 -- a load-bearing SME value, flagged before any drift
    """
    assert ZUPT_MIN_STOP_S == 3.0
