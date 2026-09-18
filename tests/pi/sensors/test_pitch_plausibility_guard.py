################################################################################
# File Name: test_pitch_plausibility_guard.py
# Purpose/Description: US-749 -- the fusion published a CONFIDENT 70 degree pitch
#     on a stationary car because the gyro carried a large standing offset and
#     nothing checked the answer against the accelerometer it already trusted.
#     These tests pin the plausibility guard (a sustained accel-vs-fusion
#     disagreement publishes the typed absence ``gyro_implausible``, never the
#     number), that it does NOT trip on a healthy gyro or on a real grade, that the
#     accelerometer term measurably contributes, and the stop-detector facts the
#     story asked to be stated rather than assumed.
# Author: Rex (US-749)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""US-749: the fusion's plausibility guard and the ZUPT stop-detector facts."""

from __future__ import annotations

import json
import math
from pathlib import Path

from pi.bus.sample import Sample
from pi.sensors.imu_state_bridge import (
    IMU_STATE_FILENAME,
    REASON_GYRO_IMPLAUSIBLE,
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_GYRO,
    ImuStateBridge,
)
from pi.sensors.pitch_fusion import (
    DEFAULT_ACCEL_TRUST_BAND,
    DEFAULT_PITCH_TAU_S,
    GYRO_IMPLAUSIBLE_SETTLE_TAUS,
    STANDARD_GRAVITY_MS2,
    PitchFusion,
    accelTrustContaminationRad,
)

G = STANDARD_GRAVITY_MS2

# MEASURED 2026-09-14 16Z -> now, raw edr_imu_sample on the stationary car (story
# acceptance, Atlas): the channel that drives pitch read 0.2457 rad/s standing.
FAULTY_RATE_RAD_S = 0.2457
# MEASURED 2026-09-13 18Z .. 2026-09-14 14Z, same car: the largest healthy
# standing offset on any gyro axis (gyro_y 0.015).
HEALTHY_RATE_RAD_S = 0.015

_CAROUSEL_JS = Path(__file__).resolve().parents[3] / "src" / "pi" / "ui" / "dashboard" / "carousel.js"


def _level() -> tuple[float, float, float]:
    """Vehicle-frame specific force of a level, stationary board."""
    return (0.0, 0.0, G)


def _tilted(deg: float) -> tuple[float, float, float]:
    """Vehicle-frame specific force of a stationary board pitched nose-up."""
    rad = math.radians(deg)
    return (G * math.sin(rad), 0.0, G * math.cos(rad))


def _noseUpRate(radPerS: float) -> tuple[float, float, float]:
    """Vehicle-frame gyro for a nose-up rate (a NEGATIVE left-axis rate)."""
    return (0.0, -radPerS, 0.0)


def _hold(
    fusion: PitchFusion,
    accel,
    gyro,
    *,
    seconds: float,
    startAt: float = 0.0,
    hz: float = 50.0,
    speed: float | None = None,
) -> float:
    """Feed constant accel/gyro (and optional 1 Hz speed); returns the next capture."""
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


# ------------------------------------------------------------- the bound itself


def test_contaminationBound_isDerivedFromTheTrustBand_notInvented():
    """
    Given: the accel trust band (|a| within 2% of 1 g)
    When:  the largest tilt error a TRUSTED reading can carry is derived
    Then:  it is atan(sqrt((1 + band)^2 - 1)) -- the tilt a longitudinal pull that
           still passes the band would fake -- about 11.4 degrees at the default.
           The guard's bound is that number, so it is a consequence of an existing
           constant rather than a new judgement.
    """
    band = DEFAULT_ACCEL_TRUST_BAND
    expected = math.atan(math.sqrt((1.0 + band) ** 2 - 1.0))
    assert math.isclose(accelTrustContaminationRad(band), expected)
    assert 11.0 < math.degrees(expected) < 11.5


# ---------------------------------------------------- VC6: the guard (the half that must ship)


def test_largeStandingGyroOffset_levelTrustedAccel_publishesTypedAbsence():
    """
    Given: the 2026-09-14 failure -- a level, trusted accelerometer and a 0.2457
           rad/s standing offset on the pitch-rate channel
    When:  the fusion runs well past GYRO_IMPLAUSIBLE_SETTLE_TAUS time constants
    Then:  it declares the gyro implausible and pitchRad is None -- NOT the 70
           degrees it published live. The raw estimate stays readable for
           diagnostics, and it is NOT clamped: it still shows the runaway.
    """
    fusion = PitchFusion()
    _hold(fusion, _level(), _noseUpRate(FAULTY_RATE_RAD_S), seconds=60.0)

    assert fusion.gyroImplausible is True
    assert fusion.pitchRad is None
    raw = fusion.rawPitchRad
    assert raw is not None
    # The mechanism, proven: steady state = rate x tau = 70.4 degrees.
    assert abs(math.degrees(raw) - math.degrees(FAULTY_RATE_RAD_S * DEFAULT_PITCH_TAU_S)) < 1.0


def test_guard_waitsForTheSettleWindow_beforeDeclaring():
    """
    Given: the same faulty offset
    When:  less than the settle window has elapsed since the disagreement began
    Then:  the guard has NOT yet tripped -- a transient must be allowed to decay
           before it is called a fault.
    """
    fusion = PitchFusion()
    # Seed, then run the fault for well under one settle window.
    _hold(fusion, _level(), _noseUpRate(FAULTY_RATE_RAD_S), seconds=4.0)
    assert fusion.gyroImplausible is False


def test_healthyGyroOffset_fifteenMinutesStationary_staysBoundedAndPlausible():
    """
    Given: the largest healthy standing offset measured on this car (0.015 rad/s)
    When:  15 minutes of stationary samples are replayed (VC1's duration)
    Then:  the guard never trips, pitch is published, it stays within a few
           degrees of the true 0, and it does NOT trend (last minute == first
           settled minute).
    """
    fusion = PitchFusion()
    after = _hold(fusion, _level(), _noseUpRate(HEALTHY_RATE_RAD_S), seconds=60.0)
    settled = fusion.pitchRad
    _hold(fusion, _level(), _noseUpRate(HEALTHY_RATE_RAD_S), seconds=14 * 60.0, startAt=after)

    assert fusion.gyroImplausible is False
    assert fusion.pitchRad is not None and settled is not None
    assert abs(math.degrees(fusion.pitchRad)) < 5.0
    assert abs(fusion.pitchRad - settled) < 1e-6


def test_realClimbOntoAGrade_doesNotTripTheGuard():
    """
    Given: a car rolling from flat onto a 6% grade over 3 s, gyro seeing the real
           rotation, accel seeing the real tilt
    When:  it then holds the grade for a minute
    Then:  the guard stays quiet and pitch reports the grade -- a real road must
           never be suppressed as a gyro fault.
    """
    fusion = PitchFusion()
    at = _hold(fusion, _level(), (0.0, 0.0, 0.0), seconds=10.0)
    gradeDeg = math.degrees(math.atan(0.06))
    rampS = 3.0
    rate = math.radians(gradeDeg) / rampS
    steps = int(rampS * 50)
    for i in range(steps):
        deg = gradeDeg * (i + 1) / steps
        fusion.update(_tilted(deg), _noseUpRate(rate), at + i * 0.02)
    at += steps * 0.02
    _hold(fusion, _tilted(gradeDeg), (0.0, 0.0, 0.0), seconds=60.0, startAt=at)

    assert fusion.gyroImplausible is False
    assert fusion.pitchRad is not None
    assert abs(math.degrees(fusion.pitchRad) - gradeDeg) < 0.5


def test_trustedContaminationStep_decays_andDoesNotTripTheGuard():
    """
    Given: a zero-offset gyro and a trusted accel tilt that STEPS 5 degrees PAST
           the contamination bound, so the disagreement does open the window
    When:  the step persists for a minute
    Then:  the fusion follows the accel (the disagreement decays with tau, back
           under the bound within a second) and the guard does not trip. A step
           cannot hold a SUSTAINED disagreement; only a standing rate can, which
           is why the guard reads the gyro's health and not the accelerometer's.
    """
    fusion = PitchFusion()
    at = _hold(fusion, _level(), (0.0, 0.0, 0.0), seconds=10.0)
    stepDeg = math.degrees(accelTrustContaminationRad(DEFAULT_ACCEL_TRUST_BAND)) + 5.0
    _hold(fusion, _tilted(stepDeg), (0.0, 0.0, 0.0), seconds=60.0, startAt=at)
    assert fusion.gyroImplausible is False


def test_guard_clearsWhenTheOffsetGoesAway():
    """
    Given: a tripped guard
    When:  the gyro offset disappears and the fusion re-converges
    Then:  pitch is published again -- the absence is a verdict on the CURRENT
           evidence, not a permanent latch.
    """
    fusion = PitchFusion()
    at = _hold(fusion, _level(), _noseUpRate(FAULTY_RATE_RAD_S), seconds=60.0)
    assert fusion.gyroImplausible is True
    _hold(fusion, _level(), (0.0, 0.0, 0.0), seconds=60.0, startAt=at)
    assert fusion.gyroImplausible is False
    assert fusion.pitchRad is not None and abs(math.degrees(fusion.pitchRad)) < 1.0


def test_reset_clearsTheVerdict():
    """
    Given: a tripped guard
    When:  the estimator is reset (sensor went absent)
    Then:  the verdict is dropped with the attitude it was about.
    """
    fusion = PitchFusion()
    _hold(fusion, _level(), _noseUpRate(FAULTY_RATE_RAD_S), seconds=60.0)
    fusion.reset()
    assert fusion.gyroImplausible is False


# ------------------------------------------------- VC4: the accel term contributes


def test_accelTerm_contributesMeasurably_againstTheSameOffset():
    """
    Given: the faulty standing offset, once with a TRUSTED accel and once with an
           accel outside the trust band (so the correction term never runs)
    When:  both run for a minute
    Then:  the trusted run settles at rate x tau (~70 degrees) while the untrusted
           run integrates to the vertical clamp. The ~20 degree gap IS the accel
           term's contribution -- asserted, not merely reached.
    """
    trusted = PitchFusion()
    _hold(trusted, _level(), _noseUpRate(FAULTY_RATE_RAD_S), seconds=60.0)
    untrusted = PitchFusion()
    # Seed from a trusted reading, then 1.05 g: outside the 2% band.
    at = _hold(untrusted, _level(), (0.0, 0.0, 0.0), seconds=1.0)
    _hold(untrusted, (0.0, 0.0, 1.05 * G), _noseUpRate(FAULTY_RATE_RAD_S), seconds=60.0, startAt=at)

    assert trusted.rawPitchRad is not None and untrusted.rawPitchRad is not None
    contributionDeg = math.degrees(untrusted.rawPitchRad) - math.degrees(trusted.rawPitchRad)
    assert contributionDeg > 15.0


# ------------------------------------------ VC2 / VC3: the stop detector, stated


def test_parkedCarWithSpeedZeroStream_confirmsAStop_withoutAPriorMovingTransition():
    """
    Given: a car that starts PARKED -- SPEED=0 from the very first reading, never
           having moved -- and the faulty gyro offset
    When:  more than the 3 s ZUPT gate of zero speed has been observed
    Then:  the stop is confirmed (no moving->stopped transition is required:
           ``observeSpeed`` opens a stop on the first zero it sees), the ZUPT snap
           holds pitch at the accel's measurement, and the guard does not trip.
    """
    fusion = PitchFusion()
    _hold(fusion, _level(), _noseUpRate(FAULTY_RATE_RAD_S), seconds=120.0, speed=0.0)

    assert fusion.inConfirmedStop is True
    assert fusion.gyroImplausible is False
    assert fusion.pitchRad is not None and abs(math.degrees(fusion.pitchRad)) < 1.0


def test_oneLongStop_commitsNoBiasObservation_untilItEnds():
    """
    Given: one long stationary SPEED=0 period
    When:  it is read before and after the car moves off
    Then:  stopCount is 0 DURING the stop and 1 after it -- the observation is
           committed per STOP at its end (Spool's mean is over stops) -- and
           biasRad stays 0.0 until DEFAULT_ZUPT_MIN_STOPS stops. So a single
           stationary replay cannot make both non-zero under the shipped
           defaults; that is the ZUPT design, reported, not changed.
    """
    fusion = PitchFusion()
    at = _hold(fusion, _tilted(2.0), (0.0, 0.0, 0.0), seconds=60.0, speed=0.0)
    assert fusion.stopCount == 0
    fusion.observeSpeed(20.0, at)
    assert fusion.stopCount == 1
    assert fusion.biasRad == 0.0

    oneStop = PitchFusion(zuptMinStops=1)
    at = _hold(oneStop, _tilted(2.0), (0.0, 0.0, 0.0), seconds=60.0, speed=0.0)
    oneStop.observeSpeed(20.0, at)
    assert oneStop.stopCount == 1
    assert abs(math.degrees(oneStop.biasRad) - 2.0) < 0.05


# -------------------------------------------------------- the published payload


def _sample(topic: str, value, unit: str, capture: float, seq: int) -> Sample:
    return Sample(
        topic=topic,
        source="imu",
        value=value,
        unit=unit,
        tsUtc="2026-09-14T16:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _feedBridge(bridge: ImuStateBridge, rawAccel, rawGyro, *, seconds: float) -> None:
    """RAW gyro then accel bursts at 50 Hz, the order the reader publishes them."""
    for i in range(int(seconds * 50)):
        capture = i * 0.02
        bridge.handleSample(_sample(TOPIC_IMU_GYRO, rawGyro, "rad/s", capture, i + 1))
        bridge.handleSample(_sample(TOPIC_IMU_ACCEL, rawAccel, "m/s^2", capture, i + 1))


def _readState(statesDir: Path) -> dict:
    return json.loads((statesDir / IMU_STATE_FILENAME).read_text(encoding="utf-8"))


def test_bridge_faultyGyro_publishesNullPitchAndGrade_withTheTypedReason(tmp_path: Path):
    """
    Given: the bridge fed the 09-14 raw signature (level board, gravity on raw z,
           0.2457 rad/s on raw gyro_x -- the pitch channel under either mounting)
    When:  states/imu is read after a minute
    Then:  pitchDeg and gradePct are null with reason gyro_implausible, and the
           gravity-removed g-meter stays small (VC5: that path must not regress).
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    # ARCH-034: the 09-14 signature put the faulty rate on the PITCH channel.
    # Under (B) that was raw X; under (C) it is raw Y. The docstring's "under
    # either mounting" was true of the two mountings that existed then.
    _feedBridge(bridge, (0.0, 0.0, G), (0.0, FAULTY_RATE_RAD_S, 0.0), seconds=60.0)
    state = _readState(tmp_path)

    assert state["pitchDeg"] is None
    assert state["gradePct"] is None
    assert state["reasons"]["pitchDeg"] == REASON_GYRO_IMPLAUSIBLE
    assert state["reasons"]["gradePct"] == REASON_GYRO_IMPLAUSIBLE
    assert abs(state["gLat"]) < 0.02 and abs(state["gLon"]) < 0.02


def test_bridge_healthyGyro_stillPublishesPitch(tmp_path: Path):
    """
    Given: the same feed with the healthy 0.015 rad/s offset
    When:  states/imu is read
    Then:  pitchDeg is a number and carries no gyro_implausible reason.
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    _feedBridge(bridge, (0.0, 0.0, G), (HEALTHY_RATE_RAD_S, 0.0, 0.0), seconds=60.0)
    state = _readState(tmp_path)

    assert state["pitchDeg"] is not None
    assert REASON_GYRO_IMPLAUSIBLE not in state["reasons"].values()


def test_guardSettleWindow_isThreeTimeConstants():
    """
    Given: a first-order filter
    When:  the settle window is read
    Then:  it is 3 tau, the textbook ~95% settling time (1 - e^-3).
    """
    assert GYRO_IMPLAUSIBLE_SETTLE_TAUS == 3


def test_rendererCanSpellTheNewReason():
    """
    Given: the new producer reason
    When:  it is looked up in the vocabulary parsed OUT OF the shipped carousel.js
    Then:  it is present -- otherwise the tile paints the raw snake_case code.
    """
    import re

    js = _CAROUSEL_JS.read_text(encoding="utf-8")
    block = re.search(r"var IMU_REASON_TEXT = \{(.*?)\};", js, re.S)
    assert block, "IMU_REASON_TEXT is no longer declared in carousel.js"
    vocabulary = dict(re.findall(r"(\w+):\s*\"([^\"]*)\"", block.group(1)))
    assert REASON_GYRO_IMPLAUSIBLE in vocabulary
