################################################################################
# File Name: test_imu_body_frame.py
# Purpose/Description: US-708 (F-135) -- pins the IMU BODY-FRAME MOUNTING, the
#     one fact three published readouts were reading wrong. The code shipped an
#     IDENTITY frame ("X = forward, Y = left, Z = up"); the board's X is LATERAL
#     and its Y is FORE-AFT, so heading was transposed (90 deg at N/E), gLat and
#     gLon were swapped, and -- the headline -- gradePct was computed from the
#     LATERAL axis, i.e. from the car's ROLL. Every corner and crowned road read
#     as a hill, which is the CIO's "gradients of 20% or more".
#
#     WHY THIS FILE IS SEPARATE FROM test_imu_state_bridge.py. That file feeds
#     VEHICLE-frame vectors and converts them to raw axes THROUGH the shipped
#     constant, so it stays green under either candidate mounting -- which is
#     correct: it tests the derived logic, not the mounting. This file feeds
#     LITERAL RAW SENSOR VECTORS, so it is the file that fails if the mounting
#     constant is wrong. A suite that passes under both candidates pins neither.
# Author: Rex (US-708)
# Creation Date: 2026-09-09
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Unit tests for the US-708 IMU body-frame transform (raw sensor -> vehicle)."""

from __future__ import annotations

import json
import math
from pathlib import Path

from pi.bus.sample import Sample
from pi.sensors.imu_state_bridge import (
    IMU_BODY_FRAME,
    IMU_BODY_FRAME_A,
    IMU_BODY_FRAME_B,
    IMU_STATE_FILENAME,
    STANDARD_GRAVITY_MS2,
    STATE_IMU_PRESENCE,
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_GYRO,
    TOPIC_IMU_MAG,
    TOPIC_OBD_SPEED,
    ImuStateBridge,
    computeHeadingDeg,
    computeHorizontalG,
    createImuStateBridgeFromConfig,
    resolveMountFrame,
)
from pi.sensors.pitch_fusion import PitchFusion, gradePctFromPitchRad, pitchRadFromAccel

G = STANDARD_GRAVITY_MS2

# The frame the code shipped with before US-708, kept ONLY so the defect can be
# demonstrated rather than asserted about. Every "before" number in this file is
# produced by running the same raw vector through this map.
_IDENTITY_FRAME = {"forward": "+x", "left": "+y", "up": "+z"}


# ------------------------------------------------------------------ raw samples
def _raw(topic: str, value, unit: str, seq: int = 1, *, capture: float = 0.0) -> Sample:
    """Build one bus sample carrying a RAW DEVICE-FRAME 3-vector."""
    return Sample(
        topic=topic,
        source="imu",
        value=value,
        unit=unit,
        tsUtc="2026-09-09T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _rawAccel(value, seq: int = 1, *, capture: float = 0.0) -> Sample:
    """One raw.imu.accel burst in the BOARD's own axes (m/s^2)."""
    return _raw(TOPIC_IMU_ACCEL, value, "m/s^2", seq, capture=capture)


def _rawMag(value, seq: int = 1, *, capture: float = 0.0) -> Sample:
    """One raw.imu.mag burst in the BOARD's own axes (uT)."""
    return _raw(TOPIC_IMU_MAG, value, "uT", seq, capture=capture)


def _rawGyro(value, seq: int = 1, *, capture: float = 0.0) -> Sample:
    """One raw.imu.gyro burst in the BOARD's own axes (rad/s)."""
    return _raw(TOPIC_IMU_GYRO, value, "rad/s", seq, capture=capture)


def _readState(statesDir: Path) -> dict:
    """Load the written states/imu JSON."""
    return json.loads((statesDir / IMU_STATE_FILENAME).read_text(encoding="utf-8"))


def _settle(bridge: ImuStateBridge, rawAccel, *, seconds: float = 30.0, hz: float = 50.0) -> float:
    """Feed one constant RAW accel reading until the gravity filter locks.

    Args:
        bridge: The bridge under test.
        rawAccel: The constant DEVICE-frame reading to hold.
        seconds: How long to hold it.
        hz: Burst rate.

    Returns:
        The capture time the caller's next sample should carry.
    """
    step = 1.0 / hz
    n = int(seconds * hz)
    for i in range(n):
        bridge.handleSample(_rawAccel(rawAccel, seq=i + 1, capture=i * step))
    return n * step


# ------------------------------------------------------------ frame linear algebra
def _frameMatrix(frame: dict[str, str]) -> list[list[float]]:
    """The 3x3 matrix an axis map applies, recovered by probing the basis."""
    cols = [
        resolveMountFrame(axis, frame)
        for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    ]
    return [[cols[col][row] for col in range(3)] for row in range(3)]


def _det3(m: list[list[float]]) -> float:
    """Determinant of a 3x3 matrix."""
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _toRawAxes(vehicle, frame: dict[str, str] = IMU_BODY_FRAME):
    """Express a VEHICLE-frame vector in the board's raw axes under ``frame``.

    The inverse of the axis map. The map is a rotation (pinned below), so the
    inverse is its transpose -- derived FROM the constant rather than
    hand-written, so it cannot drift away from it.
    """
    m = _frameMatrix(frame)
    return tuple(sum(m[row][col] * vehicle[row] for row in range(3)) for col in range(3))


# ------------------------------------------------- the constant itself (AC 1 + 5)
def test_imuBodyFrame_declaresTheMeasuredMounting_notTheIdentity():
    """
    Given: the measured mounting -- X lateral, Y fore-aft, Z up
    When:  the shipped body-frame constant is read
    Then:  it is candidate (A), (fwd, left, up) = (+y, -x, +z), and it is NOT the
           identity map the code shipped with. The identity IS the defect: it
           claims X is forward, and X is the lateral axis.

    US-745: the binding is now (B) -- see the dedicated guard below. (A) stays
    DEFINED because the source comment cites it as the rejected candidate.
    """
    assert IMU_BODY_FRAME_A == {"forward": "+y", "left": "-x", "up": "+z"}
    assert IMU_BODY_FRAME_B == {"forward": "-y", "left": "+x", "up": "+z"}
    assert IMU_BODY_FRAME != _IDENTITY_FRAME, (
        "the identity frame is the US-708 defect: it reads the LATERAL axis as "
        "forward, which is why gradePct was computed from roll"
    )


_MEASURED_BASIS_FOR_B = (
    "IMU_BODY_FRAME must be candidate (B) (+Y = tail, +X = driver). MEASURED on the "
    "NEW dash mount, drives 70/71, 23,770 IMU samples (Atlas ruling 2026-09-11, "
    "US-745): accel_Y vs d(SPEED)/dt = -0.906 over 235 accel/decel windows (US-708's "
    "gate: strongly NEGATIVE => (B)); grade vs GPS ground truth +0.411 for (B) vs "
    "-0.411 for (A) over 125 constant-speed windows. Binding (A) on this board "
    "publishes gLon, gLat and pitch INVERTED and heading rotated 180 degrees."
)


def test_imuBodyFrame_shippedBinding_isCandidateB_byMeasurement():
    """
    Given: the gate US-708 left pending, run on drives 70/71 (the NEW mount)
    When:  the shipped binding is read, and a raw +Y unit vector is resolved with
           NO mount argument (so the BOUND frame is exercised, not the primitive)
    Then:  the binding is (B) and the forward component is NEGATIVE. A correct
           ruling with no executable consumer is how (A) stayed shipped after the
           measurement; this is that consumer, so a revert to (A) fails loudly.
    """
    assert IMU_BODY_FRAME == IMU_BODY_FRAME_B, _MEASURED_BASIS_FOR_B
    forward, _, _ = resolveMountFrame((0.0, 1.0, 0.0))
    assert forward < 0.0, _MEASURED_BASIS_FOR_B


def test_imuBodyFrame_bothCandidates_areProperRotations():
    """
    Given: the two candidate mountings (A) and (B)
    When:  the matrix each one applies is recovered and its determinant taken
    Then:  both are +1. A determinant of -1 would MIRROR the board, which is not
           a mounting but a typo -- and pitch_fusion's gyro sign is DERIVED from
           the frame being right-handed (forward x left = up), so a mirror would
           silently invert the pitch rate rather than fail.
    """
    for name, frame in (("A", IMU_BODY_FRAME_A), ("B", IMU_BODY_FRAME_B)):
        assert abs(_det3(_frameMatrix(frame)) - 1.0) < 1e-12, f"candidate {name} is not a rotation"


def test_candidateB_isTheHalfTurnOfCandidateA():
    """
    Given: candidate (B) -- the mounting the OLD under-seat board measured as
    When:  the same raw vector is resolved through (A) and through (B)
    Then:  (B) is (A) yawed 180 degrees: forward and left both invert, up does
           not. That is exactly what remounting the board the other way round
           produces, and it is why picking wrong INVERTS grade rather than
           fixing it -- worse than shipping the identity.
    """
    probe = (1.0, 2.0, 3.0)
    fwdA, leftA, upA = resolveMountFrame(probe, IMU_BODY_FRAME_A)
    assert resolveMountFrame(probe, IMU_BODY_FRAME_B) == (-fwdA, -leftA, upA)


def test_candidateB_reproducesTheSignsMeasuredOnTheOldMount():
    """
    Given: Atlas's two correlations from the OLD under-seat mount --
           accel_Y vs d(SPEED)/dt = -0.945 over 829 windows, and
           accel_X vs gyro_Z = +0.712 over 26,208 turning samples
    When:  those two physical events are expressed in raw axes under (B)
    Then:  the signs come out as measured. This is the derivation that produced
           the shipped constant, made falsifiable rather than quoted: (A) is
           claimed because the board was remounted 180 degrees from (B), so if
           (B) is not the old mount, the reasoning for (A) collapses with it.
    """
    # Accelerating forward: proper acceleration along the nose, plus gravity.
    _, rawY, _ = _toRawAxes((1.0, 0.0, G), IMU_BODY_FRAME_B)
    assert rawY < 0.0, "accel_Y must oppose d(SPEED)/dt on the old mount (r = -0.945)"

    # A right-hand turn: centripetal acceleration points RIGHT (= -left), and
    # turning right is a NEGATIVE yaw rate in a right-handed, z-up frame.
    rawX, _, _ = _toRawAxes((0.0, -1.0, G), IMU_BODY_FRAME_B)
    _, _, rawZ = _toRawAxes((0.0, 0.0, -1.0), IMU_BODY_FRAME_B)
    assert rawX < 0.0 and rawZ < 0.0, (
        "accel_X and gyro_Z must share a sign in a turn on the old mount (r = +0.712)"
    )


# ------------------------------------------------------- the g-meter (AC 3, VC 3)
def test_lateralAcceleration_landsOnGLat_notGLon(tmp_path: Path):
    """
    Given: a settled level board that then takes a 0.4 g shove on its X axis
    When:  the state is written
    Then:  it renders as LATERAL g, positive = right. X is the lateral axis, so a
           shove on X is a corner -- not an acceleration.
    """
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=4, gravityTauSec=5.0)
    _settle(bridge, (0.0, 0.0, G))
    bridge.handleSample(_rawAccel((-0.4 * G, 0.0, G), seq=9000, capture=30.5))
    state = _readState(tmp_path)
    assert 0.35 <= state["gLat"] <= 0.45, "X must land on gLat (right positive)"
    assert abs(state["gLon"]) <= 0.02, "a corner is not an acceleration"


def test_foreAftAcceleration_landsOnGLon_notGLat(tmp_path: Path):
    """
    Given: a settled level board that then takes a 0.4 g shove on its Y axis
    When:  the state is written
    Then:  it renders as LONGITUDINAL g, positive = accelerating. Y is the
           fore-aft axis.
    """
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=4, gravityTauSec=5.0)
    _settle(bridge, (0.0, 0.0, G))
    # US-745: -Y is the nose under the shipped (B) mounting.
    bridge.handleSample(_rawAccel((0.0, -0.4 * G, G), seq=9000, capture=30.5))
    state = _readState(tmp_path)
    assert 0.35 <= state["gLon"] <= 0.45, "Y must land on gLon (accelerating positive)"
    assert abs(state["gLat"]) <= 0.02, "an acceleration is not a corner"


def test_identityFrame_transposesTheGAxes_theDefectThisStoryRemoves():
    """
    Given: the SAME lateral shove, resolved through the frame the code shipped
    When:  the horizontal g is computed
    Then:  it comes out on gLon -- a corner reported as an acceleration. Recorded
           so the fix is measured against the defect rather than asserted about.
    """
    old = resolveMountFrame((0.4 * G, 0.0, G), _IDENTITY_FRAME)
    gravity = resolveMountFrame((0.0, 0.0, G), _IDENTITY_FRAME)
    linear = tuple(old[i] - gravity[i] for i in range(3))
    gLon, gLat = computeHorizontalG(linear, gravity)
    assert 0.35 <= gLon <= 0.45 and abs(gLat) <= 0.02, "the pre-US-708 transposition"


# ------------------------------------------------------------ grade (the headline)
def test_crownedRoadRoll_doesNotRenderAsAGrade(tmp_path: Path):
    """
    Given: a level road with an 11.3 degree ROLL -- a crowned road, or a corner
    When:  the state is written
    Then:  gradePct is ~0. Roll is not grade. Under the shipped identity frame
           this same reading rendered as a 20% hill, which is exactly the CIO's
           "gradients of 20% or more".
    """
    rad = math.radians(11.3)
    # RAW axes, written out rather than derived from the constant: rolling the
    # car tilts gravity onto the board's X axis, and X is the LATERAL one.
    raw = (-G * math.sin(rad), 0.0, G * math.cos(rad))
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=4, gravityTauSec=5.0)
    _settle(bridge, raw)
    assert abs(_readState(tmp_path)["gradePct"]) < 0.5

    # And the defect it replaces, measured on the identical reading.
    oldGrade = gradePctFromPitchRad(pitchRadFromAccel(resolveMountFrame(raw, _IDENTITY_FRAME)))
    assert abs(oldGrade) > 19.0, f"the pre-US-708 phantom hill was {oldGrade}%"


def test_realClimb_rendersAsTheGrade(tmp_path: Path):
    """
    Given: a genuine 4% climb (2.29 degrees nose-up), plausible for Chicagoland
    When:  the state is written
    Then:  gradePct reports it, WITH ITS SIGN -- a climb, not a descent. Under
           the identity frame it read FLAT: the defect hid real hills as
           thoroughly as it invented fake ones. Under the rejected candidate (A)
           it would read -4%, which is the "picking wrong inverts grade rather
           than fixing it" case, and asserting the signed value is what catches it.
    """
    rad = math.atan(0.04)
    # RAW axes, written out: pitching the nose up tilts gravity onto the board's
    # Y axis -- Y is the FORE-AFT one, and -Y points at the nose under (B) (US-745).
    raw = (0.0, -G * math.sin(rad), G * math.cos(rad))
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=4, gravityTauSec=5.0)
    _settle(bridge, raw)
    assert abs(_readState(tmp_path)["gradePct"] - 4.0) < 0.3

    oldGrade = gradePctFromPitchRad(pitchRadFromAccel(resolveMountFrame(raw, _IDENTITY_FRAME)))
    assert abs(oldGrade) < 0.5, f"the pre-US-708 code read this climb as {oldGrade}%"


def test_gyroPitchRate_isIntegratedFromTheLateralAxis(tmp_path: Path):
    """
    Given: a level board reporting a steady nose-UP rotation on the gyro
    When:  one second of bursts is drained
    Then:  the fused pitch climbs, and a ROLL rate of the same magnitude leaves
           it flat. Both halves of the complementary filter must sit on the same
           axis or they fight each other -- so the transform has to reach the
           GYRO, not just the accelerometer.
    """
    # RAW axes, written out. Nose-up is a NEGATIVE left-axis rate (right-handed:
    # forward x left = up), and left is +X under (B) (US-745), so a nose-up
    # rotation reads NEGATIVE on the board's X. A roll about the nose reads on Y.
    # The identity frame has these the other way round, which is why the gyro
    # half of the filter was integrating ROLL RATE as pitch (Atlas, spec s7).
    noseUp = (-0.1, 0.0, 0.0)
    rollRight = (0.0, 0.1, 0.0)

    def _pitchAfterOneSecond(rawGyro, statesDir: Path) -> float:
        bridge = ImuStateBridge(None, str(statesDir), stateHz=50, gravityTauSec=5.0)
        at = _settle(bridge, (0.0, 0.0, G), seconds=5.0)
        for i in range(50):
            capture = at + i * 0.02
            bridge.handleSample(_rawGyro(rawGyro, seq=10_000 + i, capture=capture))
            bridge.handleSample(_rawAccel((0.0, 0.0, G), seq=10_000 + i, capture=capture))
        return _readState(statesDir)["pitchDeg"]

    up = tmp_path / "up"
    roll = tmp_path / "roll"
    assert _pitchAfterOneSecond(noseUp, up) > 3.0, "a nose-up gyro rate must raise the pitch"
    assert abs(_pitchAfterOneSecond(rollRight, roll)) < 0.5, "a roll rate must not become pitch"


# ---------------------------------------------------------------- heading (AC 1)
def test_heading_noseAtMagneticNorth_readsZero(tmp_path: Path):
    """
    Given: a level board whose FORE-AFT axis (Y) is aligned with the field
    When:  the heading is computed
    Then:  it reads 0 -- the nose is at magnetic north. The identity frame put
           the same field on the left axis and answered 90 degrees, which is
           Atlas's "90 deg error at N/E, 180 deg at S/W".

    NOTE, and closing this story must not overstate it: this fixes the AXES. It
    does NOT fix the compass. The magnetometer carries a second, INDEPENDENT
    defect (A-30) -- the rotating field sits at ~28% of Earth's, roughly 5 uT of
    signal on a ~4 uT noise floor, and heading measured UNCORRELATED with
    rotation over 668 turns (slope -0.002, 53.7% same-sign: a coin flip). An
    axis fix cannot rescue a signal at the noise floor; that waits on the
    relocation gate (US-695).
    """
    rawNorth = (0.0, -20.0, 0.0)  # US-745: -Y is the nose under (B)
    bridge = ImuStateBridge(None, str(tmp_path))
    bridge.handleSample(_rawMag(rawNorth, seq=1, capture=0.0))
    bridge.handleSample(_rawAccel((0.0, 0.0, G), seq=2, capture=0.02))
    assert _readState(tmp_path)["headingDeg"] == 0.0

    oldHeading = computeHeadingDeg(
        resolveMountFrame((0.0, 0.0, G), _IDENTITY_FRAME),
        resolveMountFrame(rawNorth, _IDENTITY_FRAME),
    )
    # 270 rather than 90 only because the (B) raw vector points along -Y; the
    # error is the same 90 degree transposition either way.
    assert oldHeading == 270.0, "the pre-US-708 transposition, measured"


# ------------------------------------------------- the diagnostics (AC 5 / VC 2)
def _speedSample(value, *, capture: float) -> Sample:
    """One raw.obd.SPEED sample -- the ZUPT gate's only input."""
    return _raw(TOPIC_OBD_SPEED, value, "kph", seq=1, capture=capture)


def _feedRaw(bridge: ImuStateBridge, rawAccel, *, seconds: float, startAt: float) -> float:
    """Drive the bridge with RAW accel bursts at 50 Hz; returns the next capture."""
    capture = startAt
    for i in range(int(round(seconds * 50.0))):
        capture = startAt + i * 0.02
        bridge.handleSample(_rawAccel(rawAccel, seq=i + 1, capture=capture))
    return capture + 0.02


def _convergeOneStop(bridge: ImuStateBridge, rawTilt) -> float:
    """Take the bridge through ONE confirmed ZUPT stop; returns the next capture."""
    for sec in range(6):  # six 1 Hz zero readings = a 5 s OBSERVED zero span
        bridge.handleSample(_speedSample(0.0, capture=float(sec)))
    at = _feedRaw(bridge, rawTilt, seconds=6.0, startAt=0.0)
    bridge.handleSample(_speedSample(40.0, capture=at))  # moving again -> commit
    # The commit happens on the SPEED sample, and speed writes no state (it is a
    # gate, not a display field). One more burst so the published payload is
    # taken after the observation landed rather than before it.
    return _feedRaw(bridge, rawTilt, seconds=0.5, startAt=at)


def test_publishedState_carriesPitchStopCountAndBias(tmp_path: Path):
    """
    Given: a board bolted in 3 degrees nose-up that makes one confirmed stop
    When:  the state file is read
    Then:  pitchDeg, stopCount and biasRad are all published, and biasRad carries
           the MEASURED mount tilt rather than a placeholder zero.

    None of the three were observable before US-708, which is why the axis defect
    survived so long: a wrong body frame and a merely unconverged bias produce
    the same suspicious grade, and nothing on screen told them apart. biasRad
    without stopCount is the trap in the other direction -- a 0.0 bias means "no
    bias measured yet" until you can see how many stops are behind it.
    """
    rad = math.radians(3.0)
    tilt = (0.0, -G * math.sin(rad), G * math.cos(rad))  # RAW: Y is fore-aft
    bridge = ImuStateBridge(None, str(tmp_path), pitchFusion=PitchFusion(zuptMinStops=1))
    _convergeOneStop(bridge, tilt)

    state = _readState(tmp_path)
    assert state["pitchDeg"] is not None
    assert state["stopCount"] == 1
    assert abs(state["biasRad"] - rad) < 0.01, "the published bias must be the measured one"


def test_absentSensor_stillReportsTheCalibrationState(tmp_path: Path):
    """
    Given: a bridge with a converged ZUPT bias whose sensor then goes absent
    When:  the unavailable state is written
    Then:  stopCount and biasRad SURVIVE in it. The bias is a property of how the
           board is BOLTED IN, which an unplug does not change -- PitchFusion
           deliberately keeps it across reset -- and a diagnostics field that
           vanishes exactly when you are diagnosing something is not one.
    """
    rad = math.radians(3.0)
    tilt = (0.0, -G * math.sin(rad), G * math.cos(rad))
    bridge = ImuStateBridge(None, str(tmp_path), pitchFusion=PitchFusion(zuptMinStops=1))
    at = _convergeOneStop(bridge, tilt)

    bridge.handleSample(_raw(STATE_IMU_PRESENCE, 0.0, "absent", seq=0, capture=at + 1.0))

    state = _readState(tmp_path)
    assert state["available"] is False
    assert state["pitchDeg"] is None, "a frozen attitude would render as a live grade"
    assert state["stopCount"] == 1
    assert abs(state["biasRad"] - rad) < 0.01


# ------------------------------------------ the mounting is not config (Atlas s7)
def test_theMounting_isNotReadFromConfig(tmp_path: Path):
    """
    Given: a config that still carries the stale pi.sensors.imu.mount block
    When:  the bridge is built from it and fed a lateral shove
    Then:  the shipped constant wins -- the reading lands on gLat. The mounting
           is a fact about how the board is bolted to the dash, established by
           measurement and settled by a drive, not a knob. Leaving it in
           config.json left the identity map sitting there looking adjustable,
           and it OVERRODE the code default -- so correcting the constant alone
           would have shipped a no-op onto the Pi.
    """
    config = {
        "pi": {
            "bus": {"enabled": True},
            "splash": {"statesDir": str(tmp_path)},
            "sensors": {
                "imu": {
                    "enabled": True,
                    "stateHz": 4,
                    "mount": {"forward": "+x", "left": "+y", "up": "+z"},
                }
            },
        }
    }

    class _NullBus:
        """A bus that hands back no subscription -- handleSample is driven directly."""

        def subscribe(self, *_args, **_kwargs):
            return None

    bridge = createImuStateBridgeFromConfig(config, _NullBus())
    assert bridge is not None
    _settle(bridge, (0.0, 0.0, G))
    bridge.handleSample(_rawAccel((-0.4 * G, 0.0, G), seq=9000, capture=30.5))
    state = _readState(tmp_path)
    assert 0.35 <= state["gLat"] <= 0.45, "the stale config mount must not be honoured"
