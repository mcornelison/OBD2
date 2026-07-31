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
################################################################################
"""Unit tests for the IMU-state bridge (bus raw.imu.* -> states/imu)."""

from __future__ import annotations

import json
import math
from pathlib import Path

from pi.bus.bus import SampleBus
from pi.bus.sample import QoS, Sample
from pi.sensors.imu_state_bridge import (
    DEFAULT_MOUNT,
    IMU_STATE_FILENAME,
    MAX_GRADE_PITCH_DEG,
    REASON_NO_MAG,
    REASON_NO_SOURCE,
    REASON_SENSOR_ABSENT,
    REASON_TILT_UNRESOLVED,
    STANDARD_GRAVITY_MS2,
    ImuStateBridge,
    buildImuState,
    computeGradePct,
    computeHeadingDeg,
    computeHorizontalG,
    createImuStateBridgeFromConfig,
    resolveMountFrame,
)

G = STANDARD_GRAVITY_MS2

# The exact key set of the states/imu payload (Atlas Q-A contract + gMag from the
# US-478 AC).  Pinned so a field can never be dropped or silently renamed.
_EXPECTED_KEYS = {
    "available",
    "ts",
    "gLat",
    "gLon",
    "gMag",
    "headingDeg",
    "gradePct",
    "altitude",
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


def _accel(value, seq: int = 1, *, capture: float = 0.0) -> Sample:
    """Build one raw.imu.accel burst sample (m/s^2 3-tuple)."""
    return Sample(
        topic="raw.imu.accel",
        source="imu",
        value=value,
        unit="m/s^2",
        tsUtc="2026-07-31T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _mag(value, seq: int = 1, *, capture: float = 0.0) -> Sample:
    """Build one raw.imu.mag burst sample (uT 3-tuple)."""
    return Sample(
        topic="raw.imu.mag",
        source="imu",
        value=value,
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
    Given: the default mount (+x forward, +y left, +z up)
    When: a raw device-frame vector is resolved
    Then: the components are returned unchanged, in (forward, left, up) order
    """
    assert resolveMountFrame((1.0, 2.0, 3.0), DEFAULT_MOUNT) == (1.0, 2.0, 3.0)


def test_resolveMountFrame_remountedBoard_remapsAndSignsAxes():
    """
    Given: a board mounted on its side (+y forward, -x left, +z up)
    When: a raw device-frame vector is resolved
    Then: the axes are remapped AND the sign is applied -- so a physical remount
          is a config change, never a code change
    """
    mount = {"forward": "+y", "left": "-x", "up": "+z"}
    assert resolveMountFrame((1.0, 2.0, 3.0), mount) == (2.0, -1.0, 3.0)


# --------------------------------------------------------------- computeGradePct


def test_computeGradePct_levelBoard_isZeroNotNoise():
    """
    Given: gravity read by a level board
    When: the grade is computed
    Then: it is exactly 0.0 percent
    """
    assert computeGradePct(_level()) == 0.0


def test_computeGradePct_noseUpTenDegrees_isTanPitchTimes100():
    """
    Given: the board pitched nose-up 10 degrees
    When: the grade is computed
    Then: it is tan(10 deg) * 100 = 17.6 percent, positive for a climb
    """
    assert computeGradePct(_pitched(10.0)) == round(math.tan(math.radians(10.0)) * 100, 1)


def test_computeGradePct_noseDown_isNegative():
    """
    Given: the board pitched nose-DOWN
    When: the grade is computed
    Then: it is negative (a descent reads as a descent)
    """
    assert computeGradePct(_pitched(-8.0)) < 0


def test_computeGradePct_pitchBeyondRange_isNullNotAnAbsurdNumber():
    """
    Given: a pitch past MAX_GRADE_PITCH_DEG (tan explodes toward infinity)
    When: the grade is computed
    Then: it is None -- an unreportable grade is NOT reported (never inf, never a
          four-digit percent the display would render as fact)
    """
    assert computeGradePct(_pitched(MAX_GRADE_PITCH_DEG + 1.0)) is None


def test_computeGradePct_degenerateGravity_isNull():
    """
    Given: a zero-magnitude gravity vector (unreadable / free-fall)
    When: the grade is computed
    Then: it is None, never 0.0 -- "no tilt reading" is not "level"
    """
    assert computeGradePct((0.0, 0.0, 0.0)) is None


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
    )
    assert json.loads(json.dumps(state, allow_nan=False)) == state


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
          is the DISPLAY's poll cadence (carousel.js POLL_MS = 250), not the
          sensor's; anything faster is pure wear with no consumer
    """
    writes = []
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=4)
    bridge._writeState = lambda payload: writes.append(payload)  # type: ignore[method-assign]
    for i in range(50):
        bridge.handleSample(_accel(_level(), seq=i + 1, capture=i * 0.02))
    assert 4 <= len(writes) <= 5


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


def test_bridge_mountConfig_isAppliedToTheReadings(tmp_path: Path):
    """
    Given: a board physically mounted on its side (+z forward, +y left, -x up)
    When: a device-frame gravity reading arrives
    Then: the derived grade is computed in the VEHICLE frame -- a remount is a
          config edit, not a code edit (CIO rule: calibration values live in
          config)
    """
    mount = {"forward": "+z", "left": "+y", "up": "-x"}
    bridge = ImuStateBridge(None, str(tmp_path), mount=mount)
    # Device frame reading whose UP axis (-x) carries the full 1 g -> level.
    bridge.handleSample(_accel((-G, 0.0, 0.0)))
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
    assert sensor_reader.TOPIC_IMU_MAG in patterns
    assert sensor_reader.STATE_IMU in patterns


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
