################################################################################
# File Name: test_imu_state_bridge.py
# Purpose/Description: Unit tests for the IMU -> states/imu bridge (US-478,
#     F-113). Drains raw.imu.accel / raw.imu.mag off the F-110 SampleBus and
#     mirrors the DERIVED display view into states/imu per Atlas's Q-A contract:
#     gLat / gLon (g), headingDeg, gradePct = tan(pitch)*100, altitude typed-NULL
#     + reason "no_source", available + ts. Raw stays on the bus (A-4) -- this is
#     the derived view only. Honest-availability: every field that has no readable
#     source is JSON null WITH a named reason, never a fabricated 0.0 (a zeroed
#     g-meter and a dead g-meter must not look alike).
# Author: Rex (US-478)
# Creation Date: 2026-07-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# 2026-09-22 Rex (US-801): the two US-508 default-rate pins now pin the shipped
#     1 Hz default and the CIO's 4 Hz hard cap (ARCH-036), per the CIO.
################################################################################
"""Unit tests for the IMU-state bridge (bus raw.imu.* -> states/imu)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from pi.bus.bus import SampleBus
from pi.bus.sample import QoS, Sample
from pi.sensors.imu_state_bridge import (
    DEFAULT_IMU_SAMPLE_HZ,
    DEFAULT_STATE_HZ,
    IMU_BODY_FRAME,
    IMU_STATE_FILENAME,
    MAX_GRADE_PITCH_DEG,
    REASON_NO_MAG,
    REASON_NO_SOURCE,
    REASON_PITCH_OUT_OF_RANGE,
    REASON_PITCH_UNSEEDED,
    REASON_SENSOR_ABSENT,
    REASON_TILT_UNRESOLVED,
    STANDARD_GRAVITY_MS2,
    TOPIC_IMU_GYRO,
    TOPIC_OBD_SPEED,
    ImuStateBridge,
    buildImuState,
    computeHeadingDeg,
    computeHorizontalG,
    createImuStateBridgeFromConfig,
    resolveMountFrame,
)
from pi.sensors.pitch_fusion import FUSION_VERSION, PitchFusion

G = STANDARD_GRAVITY_MS2

# The exact key set of the states/imu payload (Atlas Q-A contract + gMag from the
# US-478 AC, + the US-708 pitch-path diagnostics).  Pinned so a field can never be
# dropped or silently renamed.
_EXPECTED_KEYS = {
    "available",
    "ts",
    "gLat",
    "gLon",
    "gMag",
    "headingDeg",
    "pitchDeg",
    "gradePct",
    "altitude",
    # US-708. NOT derived fields and never gated: they describe the ESTIMATOR,
    # not a sensor reading, and they are wanted most when the instrument has gone
    # unavailable -- which is why they are outside _DERIVED_FIELDS.
    "stopCount",
    "biasRad",
    # ARCH-056. Outside _DERIVED_FIELDS and never gated, for the same reason: it
    # describes whether the mag channel was DEMONSTRATED to turn with the
    # vehicle, so it is wanted most precisely when headingDeg has gone null.
    # Three-valued -- "undetermined" is not "healthy".
    "magRotation",
    "reasons",
}


def _level() -> tuple[float, float, float]:
    """Gravity as read by a level board: +1 g on the UP axis, nothing else."""
    return (0.0, 0.0, G)


def _pitched(deg: float) -> tuple[float, float, float]:
    """Gravity as read by a board pitched nose-UP by ``deg`` degrees."""
    rad = math.radians(deg)
    return (G * math.sin(rad), 0.0, G * math.cos(rad))


def _rollAboutForward(
    vec: tuple[float, float, float], deg: float
) -> tuple[float, float, float]:
    """Re-express an earth-fixed vector after the BODY rolls ``deg`` about forward.

    Rolling about the forward axis leaves the forward direction unchanged in the
    earth frame, so any heading computed from the rotated pair must be identical
    -- that invariance is what "tilt-compensated" means.
    """
    f, lft, up = vec
    rad = math.radians(deg)
    return (f, lft * math.cos(rad) + up * math.sin(rad), -lft * math.sin(rad) + up * math.cos(rad))


def _asRawAxes(vehicle):
    """Express a VEHICLE-frame vector in the board's own axes (US-708).

    Every helper below states its reading in VEHICLE coordinates, because that is
    what the assertions in this file are about -- the derived logic, not the
    mounting. The bridge is fed RAW device axes, so the conversion happens here,
    once, and it is DERIVED from the shipped IMU_BODY_FRAME (a rotation, so its
    inverse is its transpose) rather than hand-written.

    That makes this file deliberately mount-AGNOSTIC: it stays green if the
    orientation constant is flipped between candidate (A) and (B). The mounting
    itself is pinned in test_imu_body_frame.py, which feeds LITERAL raw vectors
    -- a suite that passed under both candidates would pin neither.
    """
    cols = [
        resolveMountFrame(axis, IMU_BODY_FRAME)
        for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    ]
    return tuple(sum(cols[col][row] * vehicle[row] for row in range(3)) for col in range(3))


def _accel(value, seq: int = 1, *, capture: float = 0.0) -> Sample:
    """Build one raw.imu.accel burst sample from a VEHICLE-frame 3-tuple (m/s^2)."""
    return Sample(
        topic="raw.imu.accel",
        source="imu",
        value=_asRawAxes(value),
        unit="m/s^2",
        tsUtc="2026-07-31T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _mag(value, seq: int = 1, *, capture: float = 0.0) -> Sample:
    """Build one raw.imu.mag burst sample from a VEHICLE-frame 3-tuple (uT)."""
    return Sample(
        topic="raw.imu.mag",
        source="imu",
        value=_asRawAxes(value),
        unit="uT",
        tsUtc="2026-07-31T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _presence(present: bool, *, capture: float = 0.0) -> Sample:
    """Build the retained state.sensor.imu presence sample."""
    return Sample(
        topic="state.sensor.imu",
        source="imu",
        value=1.0 if present else 0.0,
        unit="present" if present else "absent",
        tsUtc="2026-07-31T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=0,
    )


def _readState(statesDir: Path) -> dict:
    """Load the written states/imu JSON."""
    return json.loads((statesDir / IMU_STATE_FILENAME).read_text(encoding="utf-8"))


def _settle(bridge: ImuStateBridge, gravity, *, seconds: float = 30.0, hz: float = 50.0):
    """Feed a constant accel reading long enough for the gravity filter to lock."""
    step = 1.0 / hz
    n = int(seconds * hz)
    for i in range(n):
        bridge.handleSample(_accel(gravity, seq=i + 1, capture=i * step))


# ------------------------------------------------------------ resolveMountFrame


def test_resolveMountFrame_identityMount_passesTheVectorThrough():
    """
    Given: an explicit identity map (+x forward, +y left, +z up)
    When: a raw device-frame vector is resolved
    Then: the components are returned unchanged, in (forward, left, up) order --
          the mapping PRIMITIVE, exercised on its own. US-708 note: the identity
          is no longer the shipped mounting; it is the frame the code wrongly
          assumed, kept here only to pin what the primitive does with it.
    """
    identity = {"forward": "+x", "left": "+y", "up": "+z"}
    assert resolveMountFrame((1.0, 2.0, 3.0), identity) == (1.0, 2.0, 3.0)


def test_resolveMountFrame_remountedBoard_remapsAndSignsAxes():
    """
    Given: a board mounted on its side (+y forward, -x left, +z up)
    When: a raw device-frame vector is resolved
    Then: the axes are remapped AND the sign is applied
    """
    mount = {"forward": "+y", "left": "-x", "up": "+z"}
    assert resolveMountFrame((1.0, 2.0, 3.0), mount) == (2.0, -1.0, 3.0)


def test_resolveMountFrame_noMountGiven_appliesTheShippedBodyFrame():
    """
    Given: no explicit map -- the production call shape
    When: a raw device-frame vector is resolved
    Then: the shipped IMU_BODY_FRAME is applied. There is no second place the
          mounting is declared and no identity fallback hiding behind a
          .get() default (US-708).
    """
    probe = (1.0, 2.0, 3.0)
    assert resolveMountFrame(probe) == resolveMountFrame(probe, IMU_BODY_FRAME)
    assert resolveMountFrame(probe, {}) == resolveMountFrame(probe, IMU_BODY_FRAME)


# NOTE (US-521): the pure grade math that used to be tested here as
# computeGradePct(gravity) MOVED to pi.sensors.pitch_fusion, because grade is no
# longer derived from the accel-only gravity vector -- it is derived from the
# GYRO-FUSED pitch.  Its five cases (level, nose-up, nose-down, past-range,
# degenerate) are covered one-for-one by tests/pi/sensors/test_pitch_fusion.py
# against pitchRadFromAccel + gradePctFromPitchRad.  Nothing was dropped; the
# fact simply has a different producer now.


# -------------------------------------------------------------- computeHeadingDeg


def test_computeHeadingDeg_northAlongForward_isZero():
    """
    Given: a level board with the magnetic field pointing along the vehicle nose
    When: the heading is computed
    Then: it is 0 degrees (pointing at magnetic north)
    """
    assert computeHeadingDeg(_level(), (20.0, 0.0, 0.0)) == 0.0


def test_computeHeadingDeg_northToTheLeft_isEast():
    """
    Given: a level board with magnetic north off the LEFT flank
    When: the heading is computed
    Then: it is 90 degrees -- the vehicle is pointing east
    """
    assert computeHeadingDeg(_level(), (0.0, 20.0, 0.0)) == 90.0


def test_computeHeadingDeg_northToTheRight_isWestNotNegative():
    """
    Given: a level board with magnetic north off the RIGHT flank
    When: the heading is computed
    Then: it is 270 degrees -- normalized into 0..359, never a negative bearing
    """
    assert computeHeadingDeg(_level(), (0.0, -20.0, 0.0)) == 270.0


def test_computeHeadingDeg_boardRolled_isUnchanged_tiltCompensated():
    """
    Given: the same physical heading, read by a board rolled 25 degrees about the
           forward axis (both gravity AND field rotate with the body)
    When: the heading is computed
    Then: it is the SAME bearing as level -- this invariance IS the tilt
          compensation; an uncompensated atan2(my, mx) would swing badly here
    """
    gravity, mag = _level(), (14.0, 8.0, -30.0)
    flat = computeHeadingDeg(gravity, mag)
    rolled = computeHeadingDeg(_rollAboutForward(gravity, 25.0), _rollAboutForward(mag, 25.0))
    assert flat is not None and rolled is not None
    assert abs(rolled - flat) < 0.2


def test_computeHeadingDeg_degenerateGravity_isNull():
    """
    Given: no usable gravity reference
    When: the heading is computed
    Then: it is None -- an untilt-compensatable bearing is not published
    """
    assert computeHeadingDeg((0.0, 0.0, 0.0), (20.0, 0.0, 0.0)) is None


def test_computeHeadingDeg_zeroField_isNull():
    """
    Given: a zero-magnitude magnetic reading (dead / shielded magnetometer)
    When: the heading is computed
    Then: it is None, never the 0.0 bearing that a zero vector would fall out as
    """
    assert computeHeadingDeg(_level(), (0.0, 0.0, 0.0)) is None


# ------------------------------------------------------------- computeHorizontalG


def test_computeHorizontalG_forwardAcceleration_isPositiveLongitudinal():
    """
    Given: a level board under 0.5 g of forward acceleration
    When: the horizontal g is computed
    Then: gLon = +0.5 and gLat = 0.0 (positive longitudinal = accelerating)
    """
    gLon, gLat = computeHorizontalG((0.5 * G, 0.0, 0.0), _level())
    assert gLon == 0.5
    assert gLat == 0.0


def test_computeHorizontalG_braking_isNegativeLongitudinal():
    """
    Given: a level board under 0.3 g of deceleration
    When: the horizontal g is computed
    Then: gLon is negative -- braking reads as braking
    """
    gLon, _ = computeHorizontalG((-0.3 * G, 0.0, 0.0), _level())
    assert gLon == -0.3


def test_computeHorizontalG_rightTurn_isPositiveLateral():
    """
    Given: a right turn (centripetal acceleration points to the RIGHT flank, i.e.
           NEGATIVE on the left-handed body axis)
    When: the horizontal g is computed
    Then: gLat is POSITIVE -- the published convention is lateral-positive-right
          (automotive convention; the card maps it, it never re-derives it)
    """
    _, gLat = computeHorizontalG((0.0, -0.4 * G, 0.0), _level())
    assert gLat == 0.4


def test_computeHorizontalG_degenerateGravity_isNull():
    """
    Given: no usable gravity reference (no level frame to project onto)
    When: the horizontal g is computed
    Then: it is None -- never a projection onto a guessed frame
    """
    assert computeHorizontalG((1.0, 1.0, 1.0), (0.0, 0.0, 0.0)) is None


# ------------------------------------------------------------------ buildImuState


def test_buildImuState_liveReading_carriesExactlyTheContractKeys():
    """
    Given: a live gravity + linear + mag reading
    When: the payload is assembled
    Then: it carries EXACTLY the Atlas Q-A contract keys -- no more, no fewer
    """
    state = buildImuState(
        tsUtc="2026-07-31T00:00:00Z",
        gravity=_level(),
        linear=(0.0, 0.0, 0.0),
        mag=(20.0, 0.0, 0.0),
    )
    assert set(state) == _EXPECTED_KEYS
    assert state["available"] is True


def test_buildImuState_altitude_isTypedNullWithNoSourceReason_never_zero():
    """
    Given: any live reading (the ICM-20948 has no barometer)
    When: the payload is assembled
    Then: altitude is JSON null with reason "no_source" -- NEVER 0, never omitted
          (a zeroed altitude would render as sea level, a confident lie)
    """
    state = buildImuState(
        tsUtc="2026-07-31T00:00:00Z",
        gravity=_level(),
        linear=(0.0, 0.0, 0.0),
        mag=(20.0, 0.0, 0.0),
    )
    assert state["altitude"] is None
    assert state["reasons"]["altitude"] == REASON_NO_SOURCE


def test_buildImuState_noMagReading_headingIsNullWithReason_othersStillLive():
    """
    Given: an accel reading but no usable magnetometer reading
    When: the payload is assembled
    Then: headingDeg alone grays (null + reason), while gLat/gLon/gradePct stay
          live -- honest-availability is PER FIELD, not per card
    """
    state = buildImuState(
        tsUtc="2026-07-31T00:00:00Z",
        gravity=_pitched(5.0),
        linear=(0.0, 0.0, 0.0),
        mag=None,
        pitchRad=math.radians(5.0),
    )
    assert state["headingDeg"] is None
    assert state["reasons"]["headingDeg"] == REASON_NO_MAG
    assert state["available"] is True
    assert state["gradePct"] is not None
    assert state["gLon"] is not None


def test_buildImuState_sensorAbsent_everyFieldNullWithOneNamedReason():
    """
    Given: the IMU is absent (never wired / unplugged mid-session)
    When: the payload is assembled with the absent reason
    Then: available is False and EVERY derived field is null with the reason
          named -- silence is reported as silence, not as a zeroed instrument
    """
    state = buildImuState(tsUtc="2026-07-31T00:00:00Z", unavailableReason=REASON_SENSOR_ABSENT)
    assert set(state) == _EXPECTED_KEYS
    assert state["available"] is False
    for field in ("gLat", "gLon", "gMag", "headingDeg", "gradePct", "altitude"):
        assert state[field] is None, field
        assert state["reasons"][field]
    assert state["reasons"]["gLat"] == REASON_SENSOR_ABSENT


def test_buildImuState_degenerateGravity_reportsTiltUnresolved():
    """
    Given: a gravity vector that yields no level frame
    When: the payload is assembled
    Then: the tilt-derived fields are null with the tilt_unresolved reason
    """
    state = buildImuState(
        tsUtc="2026-07-31T00:00:00Z",
        gravity=(0.0, 0.0, 0.0),
        linear=(0.0, 0.0, 0.0),
        mag=(20.0, 0.0, 0.0),
    )
    assert state["gLat"] is None
    assert state["reasons"]["gLat"] == REASON_TILT_UNRESOLVED
    assert state["gradePct"] is None


def test_buildImuState_isJsonSerializable_withNoNonFiniteValues():
    """
    Given: a live payload
    When: it is serialized the way the atomic writer serializes it
    Then: it round-trips through strict JSON -- no inf/nan can reach the file
          (json.dumps(allow_nan=False) is the guard the display relies on)
    """
    state = buildImuState(
        tsUtc="2026-07-31T00:00:00Z",
        gravity=_pitched(3.0),
        linear=(0.2 * G, -0.1 * G, 0.0),
        mag=(18.0, 4.0, -40.0),
        pitchRad=math.radians(3.0),
    )
    assert json.loads(json.dumps(state, allow_nan=False)) == state


# ---------------------------------------------- US-521 fused pitch in the payload


def test_buildImuState_pitchDeg_isPublishedFromTheFusedEstimate():
    """
    Given: a fused pitch of 4.5 degrees (Atlas DELTA-2: the reader computes)
    When: the payload is assembled
    Then: pitchDeg carries it, so US-519 can integrate the same fact the card
          renders rather than re-deriving its own
    """
    state = buildImuState(
        tsUtc="2026-07-31T00:00:00Z",
        gravity=_level(),
        linear=(0.0, 0.0, 0.0),
        mag=None,
        pitchRad=math.radians(4.5),
    )
    assert state["pitchDeg"] == 4.5


def test_buildImuState_unseededPitch_graysPitchAndGrade_notTheWholeCard():
    """
    Given: a live IMU whose fusion has NOT yet seeded (started mid-drive under
           power, so no uncontaminated reading has arrived)
    When: the payload is assembled
    Then: pitchDeg and gradePct are null with the pitch_unseeded reason while
          the g-meter and heading stay live -- and gradePct is NEVER 0.0, which
          would render as a confident "flat road" the estimator cannot support
    """
    state = buildImuState(
        tsUtc="2026-07-31T00:00:00Z",
        gravity=_level(),
        linear=(0.1 * G, 0.0, 0.0),
        mag=(20.0, 0.0, 0.0),
        pitchRad=None,
    )
    assert state["available"] is True
    assert state["pitchDeg"] is None
    assert state["gradePct"] is None
    assert state["reasons"]["pitchDeg"] == REASON_PITCH_UNSEEDED
    assert state["reasons"]["gradePct"] == REASON_PITCH_UNSEEDED
    assert state["gLon"] is not None
    assert state["headingDeg"] is not None


def test_buildImuState_gradeIsNeverDerivedFromGravityAsAFallback():
    """
    Given: a strongly pitched GRAVITY vector but no fused pitch
    When: the payload is assembled
    Then: gradePct stays null -- a gravity fallback would silently restore the
          accel-only tilt US-521 exists to delete, and give one published fact
          two producers that can disagree
    """
    state = buildImuState(
        tsUtc="2026-07-31T00:00:00Z",
        gravity=_pitched(12.0),
        linear=(0.0, 0.0, 0.0),
        mag=None,
        pitchRad=None,
    )
    assert state["gradePct"] is None
    assert state["pitchDeg"] is None


def test_buildImuState_pitchPastVertical_separatesOutOfRangeFromUnseeded():
    """
    Given: a fused pitch past MAX_GRADE_PITCH_DEG
    When: the payload is assembled
    Then: pitchDeg is still reported (the attitude IS known) but gradePct grays
          with pitch_out_of_range -- "we do not know" and "tan() is meaningless
          here" are different facts and must not share one reason
    """
    state = buildImuState(
        tsUtc="2026-07-31T00:00:00Z",
        gravity=_level(),
        linear=(0.0, 0.0, 0.0),
        mag=None,
        pitchRad=math.radians(MAX_GRADE_PITCH_DEG + 2.0),
    )
    assert state["pitchDeg"] is not None
    assert state["gradePct"] is None
    assert state["reasons"]["gradePct"] == REASON_PITCH_OUT_OF_RANGE


# ------------------------------------------------------------------ ImuStateBridge


def test_handleSample_firstAccel_writesStatesImuImmediately(tmp_path: Path):
    """
    Given: a started bridge with no prior samples
    When: the first raw.imu.accel sample arrives
    Then: states/imu is written at once (the card is never left with no file
          waiting for a decimation window to open)
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    assert bridge.handleSample(_accel(_level())) is True
    state = _readState(tmp_path)
    assert state["available"] is True
    assert state["gradePct"] == 0.0


def test_handleSample_nonImuTopic_ignoredNoWrite(tmp_path: Path):
    """
    Given: a bridge subscribed for IMU topics
    When: an unrelated sample arrives (raw.obd.RPM)
    Then: it is ignored and no state file is written
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    other = Sample(
        topic="raw.obd.RPM",
        source="obd",
        value=2500.0,
        unit="rpm",
        tsUtc="2026-07-31T00:00:00Z",
        tsCapture=0.0,
        driveId=None,
        dataSource="real",
        seq=1,
    )
    assert bridge.handleSample(other) is False
    assert not (tmp_path / IMU_STATE_FILENAME).exists()


def test_bridge_decimatesTheFiftyHzBurstToTheStateRate(tmp_path: Path):
    """
    Given: the IMU publishing at its 50 Hz sampleHz and a 4 Hz state rate
    When: one second of samples is drained
    Then: the file is written about stateHz times, not 50 -- the tmpfs write rate
          is the DISPLAY's poll cadence, not the sensor's; anything faster is
          pure wear with no consumer.

          This test pins the DECIMATION at whatever rate it is handed, which is
          why it still passes 4 explicitly. What that cadence should DEFAULT to
          is a separate fact with its own test below -- US-801 moved it to 1 Hz
          and this docstring used to assert the old grounding as if it were the
          rule.
    """
    writes = []
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=4)
    bridge._writeState = lambda payload: writes.append(payload)  # type: ignore[method-assign]
    for i in range(50):
        bridge.handleSample(_accel(_level(), seq=i + 1, capture=i * 0.02))
    assert 4 <= len(writes) <= 5


def test_bridge_defaultStateRate_isTheShippedOneHz(tmp_path: Path):
    """
    Given: a bridge built WITHOUT an explicit stateHz -- the way production wires
           it whenever pi.sensors.imu.stateHz is absent from config
    When: eight seconds of the default 4 Hz burst are drained
    Then: it writes about DEFAULT_STATE_HZ times a second -- one per second.

          THE GAP THIS CLOSES: every other rate test in this file passes stateHz
          explicitly, so not one of them exercises the default. US-801 moved the
          default from US-508's 10 Hz to the shipped 1 Hz (US-796-b, the CIO's
          4 Hz hard cap, ARCH-036). A silent revert to 10 -- or to 4 -- writes on
          every burst (32 writes here) and fails this band.
    """
    writes = []
    bridge = ImuStateBridge(None, str(tmp_path))
    bridge._writeState = lambda payload: writes.append(payload)  # type: ignore[method-assign]
    for i in range(32):
        bridge.handleSample(_accel(_level(), seq=i + 1, capture=i * 0.25))
    assert DEFAULT_STATE_HZ == 1
    # One write per 1 s interval over 8 s, quantised by the 0.25 s burst grid.
    assert 7 <= len(writes) <= 9, len(writes)


def test_defaultRates_sitUnderTheCioHardCap():
    """
    Given: the CIO's acquisition ceiling, read from its ratified source
           (specs/data-acquisition-architecture.md §4.2, ARCH-036: "4 Hz HARD
           CAP", tightened from 5 Hz on 2026-09-21)
    When: the shipped IMU defaults are compared against it
    Then: the state write rate never exceeds its source burst rate, and the burst
          rate never exceeds the cap.

          This REPLACES the US-508 transport-band pin (10-15 Hz, grounded to the
          card's 100 ms poll), which the CIO's ruling superseded: the card now
          re-reads an unchanged file between 1 Hz writes, by design. It stays a
          CROSS-ARTIFACT pin -- the cap is parsed from the ruling, not retyped, so
          a comment claiming agreement is never the only check.
    """
    doc = Path(__file__).resolve().parents[3] / "specs/data-acquisition-architecture.md"
    m = re.search(r"(\d+)\s*Hz\s+HARD\s+CAP", doc.read_text(encoding="utf-8"))
    assert m, "ARCH-036 no longer states an 'N Hz HARD CAP' -- re-ground this pin"
    capHz = int(m.group(1))
    assert DEFAULT_STATE_HZ <= DEFAULT_IMU_SAMPLE_HZ, "state writes faster than its source"
    assert DEFAULT_IMU_SAMPLE_HZ <= capHz, "the IMU default exceeds the CIO's hard cap"


def test_bridge_settledOnATiltedMount_readsZeroGButNonZeroGrade(tmp_path: Path):
    """
    Given: a board bolted in at a permanent 10-degree nose-up tilt, sitting still
    When: the gravity filter has settled
    Then: gLon reads ~0 (the car is NOT accelerating) while gradePct reads ~17.6
          -- the whole point of a gravity reference: static tilt is a GRADE, not
          a phantom 0.17 g of forward acceleration pinned on the g-meter
    """
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=4, gravityTauSec=5.0)
    _settle(bridge, _pitched(10.0))
    state = _readState(tmp_path)
    assert abs(state["gLon"]) <= 0.01
    assert abs(state["gradePct"] - math.tan(math.radians(10.0)) * 100) < 0.5


def test_bridge_realAccelerationEvent_showsOnTheGMeter(tmp_path: Path):
    """
    Given: a settled level board that then takes a 0.4 g forward shove
    When: the event sample is drained
    Then: gLon reports the acceleration -- the low-pass rejects static tilt
          WITHOUT swallowing the transient the g-meter exists to show
    """
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=4, gravityTauSec=5.0)
    _settle(bridge, _level())
    bridge.handleSample(_accel((0.4 * G, 0.0, G), seq=9000, capture=30.5))
    state = _readState(tmp_path)
    assert 0.35 <= state["gLon"] <= 0.4


def test_bridge_magFromTheSameBurst_feedsTheHeading(tmp_path: Path):
    """
    Given: a mag sample followed by the next accel sample of the burst
    When: the state is written
    Then: headingDeg is live (the reader bursts accel+gyro+mag under one seq, so
          the freshest mag belongs to this reading)
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    bridge.handleSample(_mag((0.0, 20.0, 0.0), seq=1, capture=0.0))
    bridge.handleSample(_accel(_level(), seq=2, capture=0.02))
    assert _readState(tmp_path)["headingDeg"] == 90.0


def test_bridge_staleMag_graysTheHeadingOnly(tmp_path: Path):
    """
    Given: a magnetometer reading far older than the burst cadence allows
    When: a fresh accel sample arrives
    Then: headingDeg grays with the no-mag reason while the g fields stay live --
          a frozen compass needle is worse than an absent one
    """
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50)
    bridge.handleSample(_mag((0.0, 20.0, 0.0), seq=1, capture=0.0))
    bridge.handleSample(_accel(_level(), seq=500, capture=10.0))
    state = _readState(tmp_path)
    assert state["headingDeg"] is None
    assert state["reasons"]["headingDeg"] == REASON_NO_MAG
    assert state["gLon"] is not None


def test_bridge_absentPresenceState_writesAnExplicitUnavailableState(tmp_path: Path):
    """
    Given: the retained state.sensor.imu = absent (unwired sensor)
    When: the bridge drains it
    Then: it writes an explicit available:false state -- "no file at all" is
          indistinguishable from "the emitter died", so absence is STATED
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    assert bridge.handleSample(_presence(False)) is True
    state = _readState(tmp_path)
    assert state["available"] is False
    assert state["reasons"]["gLat"] == REASON_SENSOR_ABSENT


def test_bridge_unpluggedMidSession_flipsBackToUnavailable(tmp_path: Path):
    """
    Given: a bridge that has been publishing live readings
    When: the sensor goes absent (US-478 AC-3: unplug -> silent)
    Then: the last live values are REPLACED by an honest unavailable state, never
          left frozen on the card as though they were current
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    bridge.handleSample(_accel(_level()))
    assert _readState(tmp_path)["available"] is True
    bridge.handleSample(_presence(False, capture=1.0))
    assert _readState(tmp_path)["available"] is False


def test_bridge_presenceAbsent_bypassesTheDecimationWindow(tmp_path: Path):
    """
    Given: a bridge that has just written a live state (decimation window open)
    When: the sensor goes absent immediately afterwards
    Then: the unavailable state is written anyway -- a state CHANGE is never
          rate-limited behind a display-cadence budget
    """
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=1)
    bridge.handleSample(_accel(_level(), seq=1, capture=0.0))
    bridge.handleSample(_presence(False, capture=0.01))
    assert _readState(tmp_path)["available"] is False


def test_bridge_writeFailureIsIsolated_neverRaises(tmp_path: Path):
    """
    Given: a states dir that cannot be written (permission / missing mount)
    When: a sample is handled
    Then: the bridge logs and continues -- a dashboard hook must never crash the
          bus drain (mirrors the emitters' contract)
    """
    bridge = ImuStateBridge(None, str(tmp_path / "nope"))

    def boom(*_a, **_k):
        raise OSError("read-only file system")

    bridge._ensureDir = boom  # type: ignore[method-assign]
    assert bridge.handleSample(_accel(_level())) is True


def _rawSample(topic: str, rawValue, seq: int = 1, *, capture: float = 0.0) -> Sample:
    """Build a bus sample carrying an already-RAW device-frame 3-vector."""
    return Sample(
        topic=topic,
        source="imu",
        value=rawValue,
        unit="m/s^2",
        tsUtc="2026-07-31T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def test_bridge_bodyFrame_isAppliedToTheReadings(tmp_path: Path):
    """
    Given: a RAW device reading whose UP axis carries the full 1 g
    When: it is drained
    Then: the derived grade is computed in the VEHICLE frame -- the boundary
          transform ran, and it ran on the raw vector rather than on something a
          caller had pre-mapped.

    US-708 replaced this test's subject. It used to pass a custom ``mount=`` to
    the constructor and assert that a remount was a CONFIG edit. It is not: the
    mounting is a fact about how the board is bolted to the dash, established by
    measurement -- and living in config.json is what let the identity map sit
    there looking adjustable while silently overriding the code default.
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    bridge.handleSample(_rawSample("raw.imu.accel", _asRawAxes((0.0, 0.0, G))))
    assert _readState(tmp_path)["gradePct"] == 0.0


def test_bridge_endToEnd_busPublishWritesStatesImu(tmp_path: Path):
    """
    Given: a real SampleBus + a subscribed, started bridge
    When: an IMU burst is published on the bus
    Then: states/imu appears with the derived fields -- proving the subscription
          topics and the drain loop line up with the real producer's topics
    """
    bus = SampleBus()
    sub = bus.subscribe(["raw.imu.accel", "raw.imu.mag", "state.sensor.imu"], QoS.LOSSY, "imu-state")
    bridge = ImuStateBridge(sub, str(tmp_path))
    bridge.start()
    try:
        bus.publish(_mag((20.0, 0.0, 0.0)))
        bus.publish(_accel(_level(), seq=1, capture=0.0))
        deadline = __import__("time").time() + 5.0
        target = tmp_path / IMU_STATE_FILENAME
        while __import__("time").time() < deadline and not target.exists():
            __import__("time").sleep(0.02)
    finally:
        bridge.stop(timeoutS=2.0)
    state = _readState(tmp_path)
    assert state["available"] is True
    assert state["headingDeg"] == 0.0


# ------------------------------------------- US-521 fused pitch through the bridge


def _gyroSample(value, seq: int = 1, *, capture: float = 0.0) -> Sample:
    """Build one raw.imu.gyro burst sample from a VEHICLE-frame 3-tuple (rad/s)."""
    return Sample(
        topic=TOPIC_IMU_GYRO,
        source="imu",
        value=_asRawAxes(value),
        unit="rad/s",
        tsUtc="2026-07-31T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _speedSample(value, seq: int = 1, *, capture: float = 0.0) -> Sample:
    """Build one raw.obd.SPEED sample (the ZUPT gate's only input)."""
    return Sample(
        topic=TOPIC_OBD_SPEED,
        source="obd",
        value=value,
        unit="kph",
        tsUtc="2026-07-31T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _feedBursts(bridge, accel, *, seconds: float, startAt: float, hz: float = 50.0) -> float:
    """Drive the bridge with accel bursts (gyro zero) for ``seconds``."""
    step = 1.0 / hz
    capture = startAt
    for i in range(int(round(seconds * hz))):
        capture = startAt + i * step
        bridge.handleSample(_gyroSample((0.0, 0.0, 0.0), seq=i + 1, capture=capture))
        bridge.handleSample(_accel(accel, seq=i + 1, capture=capture))
    return capture + step


def test_handleSample_gyroTopic_isConsumedNotIgnored(tmp_path: Path):
    """
    Given: a bridge (US-521 subscribes to the gyro the reader has always published)
    When: a raw.imu.gyro sample arrives
    Then: it is claimed -- returning False here would mean the fusion never sees
          a rate and silently degrades to the accel-only tilt it replaced
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    assert bridge.handleSample(_gyroSample((0.0, 0.0, 0.0))) is True


def test_handleSample_speedTopic_isConsumedNotIgnored(tmp_path: Path):
    """
    Given: a bridge
    When: a raw.obd.SPEED sample arrives (the ZUPT gate's only input)
    Then: it is claimed, and claiming it writes NO state -- speed is not a
          display field, it is a gate
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    assert bridge.handleSample(_speedSample(0.0)) is True
    assert not (tmp_path / IMU_STATE_FILENAME).exists()


def test_bridge_realChain_sustainedPointThreeG_doesNotRenderAsASeventeenPercentGrade(
    tmp_path: Path,
):
    """
    Given: a level, settled bridge -- the REAL bridge, REAL fusion, REAL payload
    When: the car pulls a sustained 0.3 g on flat ground for 12 s (an on-ramp),
          longer than the US-478 gravity filter's 5 s time constant so the
          accel-only path would have fully absorbed it
    Then: the published gradePct stays ~0, not the ~17.6% that atan(0.3) = 16.7
          degrees produces. This is Spool's failure mode asserted end-to-end
          through the file the card actually reads, not just on the estimator.
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    at = _feedBursts(bridge, _level(), seconds=1.0, startAt=0.0)
    _feedBursts(bridge, (0.3 * G, 0.0, G), seconds=12.0, startAt=at)

    state = _readState(tmp_path)
    assert abs(state["gradePct"]) < 2.0, f"0.3 g rendered as {state['gradePct']}% grade"
    assert abs(state["pitchDeg"]) < 1.0


def test_bridge_realChain_zuptAtAConfirmedStop_correctsTheMountTilt(tmp_path: Path):
    """
    Given: the board bolted in 4 degrees nose-up, so every raw reading carries a
           constant offset that is mount tilt and not road grade
    When: the car makes enough confirmed stops (raw.obd.SPEED at 0 across
          Spool's [EXACT:3] s gate) for the bias mean to converge
    Then: the published grade at rest reads ~0 -- the whole point of ZUPT, wired
          through the REAL bus topics rather than called on the estimator
    """
    bridge = ImuStateBridge(None, str(tmp_path), pitchFusion=PitchFusion(zuptMinStops=3))
    tilt = _pitched(4.0)
    at = 0.0
    for stop in range(3):
        bridge.handleSample(_speedSample(40.0, seq=stop, capture=at))
        at = _feedBursts(bridge, tilt, seconds=2.0, startAt=at)
        for sec in range(6):  # six 1 Hz zero readings = a 5 s observed span
            bridge.handleSample(_speedSample(0.0, seq=stop, capture=at + sec))
        at = _feedBursts(bridge, tilt, seconds=6.0, startAt=at)
        bridge.handleSample(_speedSample(40.0, seq=stop, capture=at))

    at = _feedBursts(bridge, tilt, seconds=0.1, startAt=at)
    state = _readState(tmp_path)
    assert abs(state["pitchDeg"]) < 0.2, f"mount tilt survived ZUPT: {state['pitchDeg']} deg"
    assert abs(state["gradePct"]) < 0.5


def test_bridge_unplugged_dropsTheAttitude_butKeepsTheZuptCalibration(tmp_path: Path):
    """
    Given: a bridge with a live fused pitch and a converged ZUPT bias
    When: the sensor goes absent mid-session
    Then: the attitude is dropped (a frozen pitch would render as a live grade)
          while the bias survives -- how the board is BOLTED IN did not change
          when the cable did, and re-converging costs another five stoplights
    """
    fusion = PitchFusion(zuptMinStops=1)
    bridge = ImuStateBridge(None, str(tmp_path), pitchFusion=fusion)
    tilt = _pitched(3.0)
    at = 0.0
    for sec in range(6):
        bridge.handleSample(_speedSample(0.0, capture=at + sec))
    at = _feedBursts(bridge, tilt, seconds=6.0, startAt=at)
    bridge.handleSample(_speedSample(40.0, capture=at))
    assert fusion.stopCount == 1

    bridge.handleSample(_presence(False, capture=at + 1.0))

    assert fusion.pitchRad is None
    assert fusion.stopCount == 1
    assert _readState(tmp_path)["pitchDeg"] is None


def test_bridge_staleGyro_isNotIntegrated(tmp_path: Path):
    """
    Given: a gyro reading far older than the burst pairing window
    When: accel bursts keep arriving on level ground
    Then: the stale rate is NOT integrated -- a frozen gyro would manufacture
          attitude out of an old reading, exactly the way a frozen compass
          needle is worse than an absent one (the US-478 mag rule, carried over)
    """
    bridge = ImuStateBridge(None, str(tmp_path))
    bridge.handleSample(_gyroSample((0.0, math.radians(30.0), 0.0), capture=0.0))
    _feedBursts(bridge, _level(), seconds=0.02, startAt=0.0)
    # Now let the gyro go stale, and feed a contaminated accel so nothing else
    # can move the pitch. A live-but-stale rate would wind it up.
    step = 1.0 / 50.0
    for i in range(500):
        bridge.handleSample(_accel((0.5 * G, 0.0, G), seq=i, capture=10.0 + i * step))

    assert abs(_readState(tmp_path)["pitchDeg"]) < 1.0


# ------------------------------------------------------------------------ factory


def _config(*, bus: bool = True, imu: bool = True, statesDir: str = "/run/eclipse-obd/states"):
    """Minimal validated-shape config for the factory."""
    return {
        "pi": {
            "bus": {"enabled": bus},
            "sensors": {"imu": {"enabled": imu, "sampleHz": 50, "stateHz": 4}},
            "splash": {"statesDir": statesDir},
        }
    }


def test_factory_busOff_returnsNone():
    """
    Given: pi.bus.enabled false (master gate)
    When: the factory runs
    Then: nothing is built -- the per-sensor flag can never bypass the bus gate
    """
    assert createImuStateBridgeFromConfig(_config(bus=False), SampleBus()) is None


def test_factory_imuOff_returnsNone():
    """
    Given: pi.sensors.imu.enabled false (ships dark until wired)
    When: the factory runs
    Then: nothing is built
    """
    assert createImuStateBridgeFromConfig(_config(imu=False), SampleBus()) is None


def test_factory_bothOn_buildsBridgeSubscribedToTheRealProducerTopics(tmp_path: Path):
    """
    Given: both gates on
    When: the factory runs
    Then: a bridge is built subscribed to the EXACT topics sensor_reader
          publishes -- asserted against the producer's own constants, so a topic
          rename on either side breaks the test instead of silencing the card
    """
    from pi.sensors import sensor_reader

    bus = SampleBus()
    bridge = createImuStateBridgeFromConfig(_config(statesDir=str(tmp_path)), bus)
    assert bridge is not None
    patterns = bridge._sub.topics  # noqa: SLF001 -- pinning the wiring
    assert sensor_reader.TOPIC_IMU_ACCEL in patterns
    assert sensor_reader.TOPIC_IMU_GYRO in patterns
    assert sensor_reader.TOPIC_IMU_MAG in patterns
    assert sensor_reader.STATE_IMU in patterns
    # US-521: the OBD speed the ZUPT gate needs is published onto this SAME bus
    # by the capture loop, so the subscription is the whole acquisition path.
    assert TOPIC_OBD_SPEED in patterns


def test_factory_zuptSpeedTopic_matchesWhatTheCaptureLoopActuallyPublishes():
    """
    Given: realtime._publishReading emits f"raw.obd.{reading.parameterName}"
    When: the bridge's ZUPT topic is compared against the configured PID name
    Then: they are the same string -- a rename on either side would leave the
          ZUPT gate subscribed to a topic nobody publishes, which fails SILENTLY
          (the fusion simply never confirms a stop and never converges a bias)
    """
    assert TOPIC_OBD_SPEED == "raw.obd.SPEED"


def test_factory_passesTheConfiguredPitchAndZuptSettingsThrough():
    """
    Given: a config carrying non-default pitch/ZUPT knobs
    When: the factory builds the bridge
    Then: they reach the estimator -- otherwise the config keys are decorative
          and the shipped constants are unreachable magic numbers
    """
    config = _config()
    config["pi"]["sensors"]["imu"].update(
        {"pitchTauSec": 2.5, "accelTrustBand": 0.01, "zuptMinStops": 2}
    )
    bridge = createImuStateBridgeFromConfig(config, SampleBus())
    assert bridge is not None
    fusion = bridge._pitchFusion  # noqa: SLF001 -- pinning the wiring
    assert fusion._tauS == 2.5  # noqa: SLF001
    assert fusion._trustBand == 0.01  # noqa: SLF001
    assert fusion._minStops == 2  # noqa: SLF001


def test_bridgeTopics_matchTheProducerConstants():
    """
    Given: the producer (sensor_reader) owns the topic SSOT
    When: the bridge's topic constants are compared to it
    Then: they are identical strings -- the seam cannot drift silently
    """
    from pi.sensors import imu_state_bridge, sensor_reader

    assert imu_state_bridge.TOPIC_IMU_ACCEL == sensor_reader.TOPIC_IMU_ACCEL
    assert imu_state_bridge.TOPIC_IMU_MAG == sensor_reader.TOPIC_IMU_MAG
    assert imu_state_bridge.STATE_IMU_PRESENCE == sensor_reader.STATE_IMU
    assert imu_state_bridge.STANDARD_GRAVITY_MS2 == 9.80665


# ------------------------------------------------------------------------- wiring


def test_orchestrator_startsTheImuBridge_notJustDefinesIt():
    """
    Given: the orchestrator's EDR sensor path (the production entry point)
    When: its source is inspected
    Then: it builds AND starts the IMU bridge -- US-494's lesson: a correct
          routine nobody calls is worth nothing, and no test of the routine can
          tell you it is not called.  (Source-text pin: stated as such, it is
          evidence of the call site, not of a running Pi.)
    """
    import inspect

    from pi.obdii.orchestrator.lifecycle import LifecycleMixin

    src = inspect.getsource(LifecycleMixin._startEdrSensorPath)
    assert "createImuStateBridgeFromConfig" in src
    assert "imuBridge.start()" in src


def test_orchestrator_stopsTheImuBridge_onShutdown():
    """
    Given: the orchestrator's sensor-path shutdown
    When: its source is inspected
    Then: the IMU bridge is stopped alongside the light bridge -- an orphaned
          daemon thread writing tmpfs through a shutdown is how a stale state
          file outlives the process that owned it
    """
    import inspect

    from pi.obdii.orchestrator import lifecycle

    src = inspect.getsource(lifecycle)
    assert "_imuStateBridge" in src


# --- US-805 / ARCH-045b: the fusion snapshot the EDR writer persists ----------


class TestDerivedSnapshot:
    """The bridge exposes what it believes, so the EDR writer can record it.

    The bridge computes these values and cannot write them (it holds no database
    handle); the EDR subscriber writes rows and cannot compute them. This
    accessor is the seam, and it is READ-ONLY by design.
    """

    def _bridge(self, tmp_path: Any) -> ImuStateBridge:
        return ImuStateBridge(None, str(tmp_path))

    def test_noEstimateYet_returnsNone(self, tmp_path: Any) -> None:
        """Before the fusion has seen a sample there is no belief to record.

        None -- never a zero-filled row. A fabricated 'pitch 0.0, no stops' row
        is indistinguishable from a genuine level reading with a converged bias.
        """
        assert self._bridge(tmp_path).derivedSnapshot() is None

    def test_afterASample_carriesTheFusionsOwnStampAndValues(self, tmp_path: Any) -> None:
        bridge = self._bridge(tmp_path)
        bridge._lastDerived = {  # noqa: SLF001 -- the recorded snapshot
            "tsUtc": "2026-09-22T12:00:00Z",
            "tsCapture": 123.5,
            "seq": 7,
            "pitchDeg": 3.74,
            "stopCount": 5,
            "biasRad": 0.01304,
            "fusionVersion": FUSION_VERSION,
        }
        snap = bridge.derivedSnapshot()
        assert snap is not None
        assert snap["tsCapture"] == 123.5
        assert snap["seq"] == 7
        assert snap["pitchDeg"] == 3.74
        assert snap["fusionVersion"] == FUSION_VERSION

    def test_snapshotIsACopy_aConsumerCannotMutateTheBridgesState(
        self, tmp_path: Any
    ) -> None:
        """The EDR writer must not be able to corrupt the estimator's record."""
        bridge = self._bridge(tmp_path)
        bridge._lastDerived = {  # noqa: SLF001
            "tsUtc": "2026-09-22T12:00:00Z", "tsCapture": 1.0, "seq": 1,
            "pitchDeg": 1.0, "stopCount": 0, "biasRad": 0.0,
            "fusionVersion": FUSION_VERSION,
        }
        snap = bridge.derivedSnapshot()
        assert snap is not None
        snap["pitchDeg"] = 999.0
        assert bridge.derivedSnapshot()["pitchDeg"] == 1.0  # type: ignore[index]

    def test_fusionVersionIsAPositiveInt_andIsStamped(self, tmp_path: Any) -> None:
        """A row that cannot say WHICH algorithm produced it defeats the split."""
        assert isinstance(FUSION_VERSION, int)
        assert FUSION_VERSION >= 1
