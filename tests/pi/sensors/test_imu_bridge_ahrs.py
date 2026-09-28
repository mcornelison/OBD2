################################################################################
# File Name: test_imu_bridge_ahrs.py
# Purpose/Description: ARCH-064 Task 4 -- the states/imu bridge SELECTS its
#     fusion engine by config and, with the x-io Fusion AHRS (AhrsFusion), takes
#     the published heading from the ENGINE rather than from computeHeadingDeg.
#
#     Pinned here:
#       * pi.sensors.imu.fusionEngine selects "imufusion" (default) or "legacy";
#         an unknown value is legacy + WARNING; an engine that cannot be BUILT
#         (imufusion missing, bad calibration) is legacy + ERROR -- the IMU state
#         is never lost -- and the state file names the engine ACTUALLY running.
#       * magDeclinationDeg + magCalibration reach the engine.
#       * _handleAccel hands the engine the SAME fresh, body-frame mag the legacy
#         heading path pairs with the burst (or None when stale).
#       * headingDeg comes from engine.headingDeg; headingCalibrated is published;
#         during Fusion's ~3 s initialisation the fields are typed-null
#         (pitch_unseeded / heading_unseeded), never a stale or zero value; every
#         pre-existing null-reason path (no_mag_reading, mag_frozen, gated
#         channel, sensor_absent) still wins.
#       * derivedSnapshot()["fusionVersion"] is the RUNNING engine's version.
#       * Ruling 9 (clock): observeSpeed and update receive each sample's OWN
#         tsCapture, and both producers stamp it from time.monotonic().
# Author: Atlas (ARCH-064)
# Creation Date: 2026-09-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""ARCH-064 Task 4: engine selection and AHRS heading through the IMU bridge."""

from __future__ import annotations

import inspect
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

import pytest

from pi.bus.sample import Sample
from pi.sensors.ahrs_fusion import FUSION_VERSION_AHRS, AhrsFusion
from pi.sensors.imu_state_bridge import (
    CHANNEL_STATE_MAG,
    IMU_STATE_FILENAME,
    REASON_HEADING_UNSEEDED,
    REASON_MAG_FROZEN,
    REASON_NO_MAG,
    REASON_PITCH_UNSEEDED,
    REASON_SENSOR_ABSENT,
    STANDARD_GRAVITY_MS2,
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_GYRO,
    TOPIC_IMU_MAG,
    TOPIC_OBD_SPEED,
    ImuStateBridge,
    MagRotation,
    createImuStateBridgeFromConfig,
    resolveMountFrame,
)
from pi.sensors.pitch_fusion import FUSION_VERSION, PitchFusion

G = STANDARD_GRAVITY_MS2
HZ = 50.0
DT = 1.0 / HZ

# A level car pointing NORTH: the field's horizontal component lies along the
# nose, its vertical component points DOWN (northern hemisphere). Vehicle frame.
NORTH_FIELD_UT = (22.5, 0.0, -53.0)
LEVEL = (0.0, 0.0, G)


# ----------------------------------------------------------------------- helpers


def _toRaw(vehicle: tuple[float, float, float]) -> tuple[float, ...]:
    """Express a VEHICLE-frame vector in the board's raw axes.

    DERIVED from the shipped body frame (a signed permutation, so its inverse is
    its transpose) -- this file stays mount-agnostic, like test_imu_state_bridge.
    """
    cols = [resolveMountFrame(e) for e in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
    return tuple(sum(cols[c][r] * vehicle[r] for r in range(3)) for c in range(3))


def _sample(topic: str, value: Any, *, capture: float, seq: int = 1, unit: str = "") -> Sample:
    return Sample(
        topic=topic,
        source="imu",
        value=value,
        unit=unit,
        tsUtc="2026-09-28T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _accel(vehicle, *, capture: float, seq: int = 1) -> Sample:
    return _sample(TOPIC_IMU_ACCEL, _toRaw(vehicle), capture=capture, seq=seq, unit="m/s^2")


def _gyro(vehicle, *, capture: float, seq: int = 1) -> Sample:
    return _sample(TOPIC_IMU_GYRO, _toRaw(vehicle), capture=capture, seq=seq, unit="rad/s")


def _mag(vehicle, *, capture: float, seq: int = 1) -> Sample:
    return _sample(TOPIC_IMU_MAG, _toRaw(vehicle), capture=capture, seq=seq, unit="uT")


def _speed(kmh: float, *, capture: float) -> Sample:
    return _sample(TOPIC_OBD_SPEED, kmh, capture=capture, unit="kph")


def _readState(statesDir: Path) -> dict:
    return json.loads((statesDir / IMU_STATE_FILENAME).read_text(encoding="utf-8"))


def _config(statesDir: Path, **imu: Any) -> dict:
    """Validated-shape config; ``imu`` keys are merged into pi.sensors.imu."""
    section = {"enabled": True, "sampleHz": 50, "stateHz": 50}
    section.update(imu)
    return {
        "pi": {
            "bus": {"enabled": True},
            "sensors": {"imu": section},
            "splash": {"statesDir": str(statesDir)},
        }
    }


class _NullBus:
    """A bus that hands back no subscription -- handleSample is driven directly."""

    def subscribe(self, *_args, **_kwargs):
        return None


def _feed(bridge: ImuStateBridge, *, seconds: float, startAt: float = 0.0,
          mag=NORTH_FIELD_UT, accel=LEVEL) -> float:
    """Drive full bursts (gyro zero, mag, accel) at 50 Hz; return next capture."""
    capture = startAt
    for i in range(int(round(seconds * HZ))):
        capture = startAt + i * DT
        bridge.handleSample(_gyro((0.0, 0.0, 0.0), capture=capture, seq=i + 1))
        if mag is not None:
            bridge.handleSample(_mag(mag, capture=capture, seq=i + 1))
        bridge.handleSample(_accel(accel, capture=capture, seq=i + 1))
    return capture + DT


class _RecordingAhrs(AhrsFusion):
    """The REAL AhrsFusion, recording what the bridge hands it."""

    def __init__(self, *args, **kwargs) -> None:
        self.updates: list[dict] = []
        self.speeds: list[tuple[Any, float]] = []
        super().__init__(*args, **kwargs)

    def update(self, accel, gyro, capture, mag_ut=None):  # noqa: D102
        self.updates.append({"accel": accel, "gyro": gyro, "capture": capture, "mag_ut": mag_ut})
        super().update(accel, gyro, capture, mag_ut=mag_ut)

    def observeSpeed(self, speed, capture):  # noqa: D102
        self.speeds.append((speed, capture))
        super().observeSpeed(speed, capture)


class _FixedAhrs(AhrsFusion):
    """An initialised-looking engine whose heading is a KNOWN, distinctive value."""

    headingDeg = property(lambda self: 123.4)  # type: ignore[assignment]
    pitchRad = property(lambda self: 0.0)  # type: ignore[assignment]


# ---------------------------------------------------------------- engine selection


def test_factory_defaultEngine_isTheImufusionAhrs(tmp_path: Path):
    """
    Given: a config with NO fusionEngine key
    When: the factory builds the bridge
    Then: the engine is AhrsFusion and the state file says "imufusion"
    """
    bridge = createImuStateBridgeFromConfig(_config(tmp_path), _NullBus())
    assert bridge is not None
    assert isinstance(bridge._pitchFusion, AhrsFusion)  # noqa: SLF001
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    assert _readState(tmp_path)["fusionEngine"] == "imufusion"


def test_factory_legacyEngine_isPitchFusion_withVersionOne(tmp_path: Path):
    """
    Given: fusionEngine "legacy"
    When: the bridge is built and fed
    Then: PitchFusion runs, fusionVersion is the legacy stamp, the state file
          says "legacy" and carries no AHRS-only headingCalibrated field
    """
    bridge = createImuStateBridgeFromConfig(_config(tmp_path, fusionEngine="legacy"), _NullBus())
    assert bridge is not None
    assert isinstance(bridge._pitchFusion, PitchFusion)  # noqa: SLF001
    bridge.handleSample(_mag(NORTH_FIELD_UT, capture=0.0))
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    state = _readState(tmp_path)
    assert state["fusionEngine"] == "legacy"
    assert "headingCalibrated" not in state
    # Legacy heading is still the tilt-compensated computeHeadingDeg path.
    assert state["headingDeg"] == 0.0
    snap = bridge.derivedSnapshot()
    assert snap is not None and snap["fusionVersion"] == FUSION_VERSION


def test_factory_unknownEngine_fallsBackToLegacy_withAWarning(tmp_path: Path, caplog):
    """
    Given: fusionEngine "kalman" (not a known engine)
    When: the factory runs
    Then: legacy runs and a WARNING names the rejected value
    """
    with caplog.at_level(logging.WARNING, logger="pi.sensors.imu_state_bridge"):
        bridge = createImuStateBridgeFromConfig(
            _config(tmp_path, fusionEngine="kalman"), _NullBus()
        )
    assert bridge is not None
    assert isinstance(bridge._pitchFusion, PitchFusion)  # noqa: SLF001
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("kalman" in r.getMessage() for r in warnings)


def test_factory_imufusionMissing_fallsBackToLegacy_withAnError(
    tmp_path: Path, caplog, monkeypatch: pytest.MonkeyPatch
):
    """
    Given: the imufusion wheel cannot be imported
    When: the factory is asked for the AHRS engine
    Then: ONE ERROR is logged, legacy PitchFusion runs -- the IMU state is not
          lost -- and the state file reports the engine ACTUALLY running
    """
    monkeypatch.setitem(sys.modules, "imufusion", None)  # import -> ImportError
    monkeypatch.delitem(sys.modules, "pi.sensors.ahrs_fusion", raising=False)
    with caplog.at_level(logging.ERROR, logger="pi.sensors.imu_state_bridge"):
        bridge = createImuStateBridgeFromConfig(
            _config(tmp_path, fusionEngine="imufusion"), _NullBus()
        )
    assert bridge is not None
    assert isinstance(bridge._pitchFusion, PitchFusion)  # noqa: SLF001
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    state = _readState(tmp_path)
    assert state["fusionEngine"] == "legacy"
    assert state["available"] is True
    snap = bridge.derivedSnapshot()
    assert snap is not None and snap["fusionVersion"] == FUSION_VERSION


def test_factory_engineConstructionFails_fallsBackToLegacy(tmp_path: Path, caplog):
    """
    Given: a malformed magCalibration the AHRS constructor rejects
    When: the factory runs
    Then: ERROR + legacy fallback, never an exception out of the factory
    """
    bad = {"hardIronUt": [1.0, 2.0], "softIron": [[1.0, 0.0]]}
    with caplog.at_level(logging.ERROR, logger="pi.sensors.imu_state_bridge"):
        bridge = createImuStateBridgeFromConfig(
            _config(tmp_path, magCalibration=bad), _NullBus()
        )
    assert bridge is not None
    assert isinstance(bridge._pitchFusion, PitchFusion)  # noqa: SLF001
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_factory_passesDeclinationAndCalibrationToTheEngine(tmp_path: Path):
    """
    Given: magDeclinationDeg and a hard/soft-iron magCalibration in config
    When: the factory builds the AHRS
    Then: they reach the engine (otherwise the keys are decorative)
    """
    cal = {"hardIronUt": [1.5, -2.0, 3.0], "softIron": [[1.1, 0, 0], [0, 0.9, 0], [0, 0, 1.0]]}
    bridge = createImuStateBridgeFromConfig(
        _config(tmp_path, magDeclinationDeg=-3.5, magCalibration=cal), _NullBus()
    )
    assert bridge is not None
    engine = bridge._pitchFusion  # noqa: SLF001
    assert isinstance(engine, AhrsFusion)
    assert engine._declinationDeg == -3.5  # noqa: SLF001
    assert list(engine._hardIron) == [1.5, -2.0, 3.0]  # noqa: SLF001
    assert engine._softIron[0][0] == 1.1  # noqa: SLF001
    assert engine.headingCalibrated is True


# --------------------------------------------------------------- AHRS wiring


def test_ahrs_updateReceivesTheFreshBodyFrameMag(tmp_path: Path):
    """
    Given: an AHRS engine and a mag reading paired with the burst
    When: the accel arrives
    Then: update() gets mag_ut == the bridge's _freshMag (body frame, uT)
    """
    engine = _RecordingAhrs(HZ)
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=engine)
    bridge.handleSample(_mag(NORTH_FIELD_UT, capture=1.0))
    bridge.handleSample(_accel(LEVEL, capture=1.0))
    assert engine.updates[-1]["mag_ut"] == pytest.approx(NORTH_FIELD_UT)
    assert engine.updates[-1]["mag_ut"] == bridge._freshMag(1.0)  # noqa: SLF001


def test_ahrs_staleMag_isNotHandedToTheEngine(tmp_path: Path):
    """
    Given: a mag reading older than the pairing window
    When: the accel arrives
    Then: update() gets mag_ut=None -- an old bearing is not a measurement
    """
    engine = _RecordingAhrs(HZ)
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=engine)
    bridge.handleSample(_mag(NORTH_FIELD_UT, capture=0.0))
    bridge.handleSample(_accel(LEVEL, capture=5.0))
    assert engine.updates[-1]["mag_ut"] is None


def test_legacy_updateIsCalledWithoutMag(tmp_path: Path):
    """
    Given: the legacy PitchFusion (no heading surface)
    When: a burst with a fresh mag arrives
    Then: update() is called exactly as before -- (accel, gyro, capture)
    """
    calls: list[tuple] = []

    class _Spy(PitchFusion):
        def update(self, *args, **kwargs):  # noqa: D102
            calls.append((args, kwargs))
            return super().update(*args, **kwargs)

    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=_Spy())
    bridge.handleSample(_mag(NORTH_FIELD_UT, capture=0.0))
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    assert len(calls[-1][0]) == 3 and calls[-1][1] == {}


def test_ahrs_headingComesFromTheEngine_notComputeHeadingDeg(tmp_path: Path):
    """
    Given: an engine whose heading is 123.4 while the raw field points NORTH
          (computeHeadingDeg would say 0)
    When: the state is written
    Then: headingDeg is the engine's (rounded to whole degrees) and the
          engine's headingCalibrated is published
    """
    engine = _FixedAhrs(HZ)
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=engine)
    bridge.handleSample(_mag(NORTH_FIELD_UT, capture=0.0))
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    state = _readState(tmp_path)
    assert state["headingDeg"] == 123.0
    assert state["headingCalibrated"] is False
    assert state["fusionEngine"] == "imufusion"
    assert "headingDeg" not in state["reasons"]


def test_ahrs_duringInitialisation_headingAndPitchAreTypedNull(tmp_path: Path):
    """
    Given: a fresh AHRS (Fusion's ~3 s startup has not completed)
    When: the first burst -- mag fresh -- is written
    Then: headingDeg null/heading_unseeded, pitchDeg + gradePct null/
          pitch_unseeded -- never a zero that reads as "level, north"
    """
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=AhrsFusion(HZ))
    bridge.handleSample(_mag(NORTH_FIELD_UT, capture=0.0))
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    state = _readState(tmp_path)
    assert state["available"] is True
    assert state["headingDeg"] is None
    assert state["reasons"]["headingDeg"] == REASON_HEADING_UNSEEDED
    assert state["pitchDeg"] is None and state["gradePct"] is None
    assert state["reasons"]["pitchDeg"] == REASON_PITCH_UNSEEDED
    assert state["reasons"]["gradePct"] == REASON_PITCH_UNSEEDED


def test_ahrs_afterInitialisation_publishesHeadingAndPitch(tmp_path: Path):
    """
    Given: the factory-built AHRS with a 10-degree EAST declination
    When: 5 s of a level, north-pointing car are fed
    Then: heading = 10 (true north + declination), pitch ~0, uncalibrated
    """
    bridge = createImuStateBridgeFromConfig(
        _config(tmp_path, magDeclinationDeg=10.0), _NullBus()
    )
    assert bridge is not None
    _feed(bridge, seconds=5.0)
    state = _readState(tmp_path)
    assert state["headingDeg"] == pytest.approx(10.0, abs=1.0)
    assert abs(state["pitchDeg"]) < 0.5
    assert state["headingCalibrated"] is False
    assert state["fusionEngine"] == "imufusion"


def test_ahrs_noFreshMag_stillReportsNoMagReading(tmp_path: Path):
    """
    Given: an initialised AHRS and then the mag stops arriving
    When: a burst past the pairing window is written
    Then: headingDeg is null with the EXISTING no_mag_reading reason
    """
    engine = _FixedAhrs(HZ)
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=engine)
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    state = _readState(tmp_path)
    assert state["headingDeg"] is None
    assert state["reasons"]["headingDeg"] == REASON_NO_MAG


def test_ahrs_frozenMagVerdict_stillNullsTheHeading(tmp_path: Path):
    """
    Given: the ARCH-056 rotation gate has returned FROZEN
    When: the engine still holds a heading
    Then: headingDeg is null with mag_frozen -- the gate beats the engine
    """
    engine = _FixedAhrs(HZ)
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=engine)
    bridge._magRotation = MagRotation.FROZEN  # noqa: SLF001 -- the verdict under test
    bridge.handleSample(_mag(NORTH_FIELD_UT, capture=0.0))
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    state = _readState(tmp_path)
    assert state["headingDeg"] is None
    assert state["reasons"]["headingDeg"] == REASON_MAG_FROZEN


def test_ahrs_gatedMagChannel_stillNullsTheHeading(tmp_path: Path):
    """
    Given: the reader has gated the mag channel (sensor_stale)
    When: the engine still holds a heading
    Then: headingDeg is null with the gate's own reason
    """
    engine = _FixedAhrs(HZ)
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=engine)
    bridge.handleSample(_sample(CHANNEL_STATE_MAG, 0.0, capture=0.0, unit="sensor_stale"))
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    state = _readState(tmp_path)
    assert state["headingDeg"] is None
    assert state["reasons"]["headingDeg"] == "sensor_stale"


def test_ahrs_sensorAbsent_blanksEverything_andNamesTheEngine(tmp_path: Path):
    """
    Given: an AHRS bridge
    When: the presence STATE says absent
    Then: sensor_absent on every derived field, and the diagnostic still names
          the running engine
    """
    engine = _FixedAhrs(HZ)
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=engine)
    bridge.handleSample(_sample("state.sensor.imu", 0.0, capture=0.0, unit="absent"))
    state = _readState(tmp_path)
    assert state["available"] is False
    assert state["headingDeg"] is None
    assert state["reasons"]["headingDeg"] == REASON_SENSOR_ABSENT
    assert state["fusionEngine"] == "imufusion"


def test_ahrs_derivedSnapshot_carriesFusionVersionTwo(tmp_path: Path):
    """
    Given: the AHRS engine
    When: a burst is folded in
    Then: the EDR snapshot is stamped with the AHRS version, not PitchFusion's
    """
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=AhrsFusion(HZ))
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    snap = bridge.derivedSnapshot()
    assert snap is not None
    assert snap["fusionVersion"] == FUSION_VERSION_AHRS == 2


# ------------------------------------------------------------ Ruling 9: one clock


def test_clock_speedAndImuReachTheEngineOnEachSamplesOwnTsCapture(tmp_path: Path):
    """
    Given: a SPEED sample and an IMU burst with distinctive tsCapture values
    When: the bridge drains them
    Then: observeSpeed gets the SPEED sample's tsCapture and update gets the
          accel sample's tsCapture -- unmodified, no clock read in between, so
          the engine's dv/dt and staleness arithmetic compare like with like
    """
    engine = _RecordingAhrs(HZ)
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=engine)
    bridge.handleSample(_speed(36.0, capture=1234.5678))
    bridge.handleSample(_gyro((0.0, 0.0, 0.0), capture=1235.0001))
    bridge.handleSample(_accel(LEVEL, capture=1235.0001))
    assert engine.speeds == [(36.0, 1234.5678)]
    assert engine.updates[-1]["capture"] == 1235.0001


def test_clock_bothProducersStampTsCaptureFromTimeMonotonic():
    """
    Given: the two producers feeding this bridge -- the OBD capture loop
          (raw.obd.SPEED) and the IMU reader (raw.imu.*)
    When: their publish paths are inspected
    Then: both stamp tsCapture from time.monotonic(), onto one in-process bus.
          SOURCE-TEXT PIN, stated as such: evidence of the call site, not a
          runtime measurement.
    """
    from pi.obdii.data import realtime
    from pi.sensors import sensor_reader

    obdSrc = inspect.getsource(realtime.RealtimeDataLogger._publishReading)
    imuSrc = inspect.getsource(sensor_reader.ImuReader._publish)
    assert "tsCapture=time.monotonic()" in obdSrc
    assert "tsCapture=time.monotonic()" in imuSrc


# ------------------------------------------- Ruling 13: a FROZEN mag is withheld


def _turningBursts(bridge: ImuStateBridge, *, seconds: float, yawRateRadS: float,
                   startAt: float = 0.0) -> float:
    """A level car yawing LEFT at a constant rate, with a mag that TURNS with it.

    Earth field fixed; the body rotates by +psi, so in the body frame the
    horizontal field rotates by -psi. Returns the next capture time.
    """
    capture = startAt
    for i in range(int(round(seconds * HZ))):
        capture = startAt + i * DT
        psi = yawRateRadS * (capture - startAt)
        field = (22.5 * math.cos(-psi), 22.5 * math.sin(-psi), -53.0)
        bridge.handleSample(_gyro((0.0, 0.0, yawRateRadS), capture=capture, seq=i + 1))
        bridge.handleSample(_mag(field, capture=capture, seq=i + 1))
        bridge.handleSample(_accel(LEVEL, capture=capture, seq=i + 1))
    return capture + DT


def test_ruling13_frozenVerdict_withholdsTheMagFromTheAhrs(tmp_path: Path):
    """
    Given: the AHRS engine, a fresh mag reading, and a FROZEN rotation verdict
    When: the burst's accel arrives
    Then: update() receives mag_ut=None -- a frozen vector must not anchor the
          engine's yaw (rejection + recovery would SNAP heading onto it)
    """
    engine = _RecordingAhrs(HZ)
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=engine)
    bridge._magRotation = MagRotation.FROZEN  # noqa: SLF001 -- the verdict under test
    bridge.handleSample(_mag(NORTH_FIELD_UT, capture=0.0))
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    assert bridge._freshMag(0.0) is not None  # noqa: SLF001 -- mag IS fresh
    assert engine.updates[-1]["mag_ut"] is None


def test_ruling13_verdictStillClears_whenTheMagTurnsWithTheGyro(tmp_path: Path):
    """
    Given: the AHRS engine and a FROZEN verdict
    When: the car yaws ~69 deg and the real mag turns with it
    Then: the verdict clears to HEALTHY (the bridge's own _freshMag path kept
          feeding the rotation gate), and only THEN does the engine get the mag
    """
    engine = _RecordingAhrs(HZ)
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=engine)
    bridge._magRotation = MagRotation.FROZEN  # noqa: SLF001
    _turningBursts(bridge, seconds=2.4, yawRateRadS=0.5)
    assert bridge._magRotation is MagRotation.HEALTHY  # noqa: SLF001
    fed = [u["mag_ut"] is not None for u in engine.updates]
    firstFed = fed.index(True)
    assert firstFed > 0 and not any(fed[:firstFed]) and all(fed[firstFed:])


def test_ruling13_legacyEngine_isUnchangedUnderAFrozenVerdict(tmp_path: Path):
    """
    Given: the legacy PitchFusion and a FROZEN verdict
    When: a burst with a fresh mag arrives
    Then: update() is called exactly as before -- (accel, gyro, capture)
    """
    calls: list[tuple] = []

    class _Spy(PitchFusion):
        def update(self, *args, **kwargs):  # noqa: D102
            calls.append((args, kwargs))
            return super().update(*args, **kwargs)

    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, pitchFusion=_Spy())
    bridge._magRotation = MagRotation.FROZEN  # noqa: SLF001
    bridge.handleSample(_mag(NORTH_FIELD_UT, capture=0.0))
    bridge.handleSample(_accel(LEVEL, capture=0.0))
    assert len(calls[-1][0]) == 3 and calls[-1][1] == {}
