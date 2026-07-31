################################################################################
# File Name: test_sensor_reader.py
# Purpose/Description: Tests for the EDR IMU + light sensor readers (US-409).
#     Covers the present (mock-sensor) burst-poll path, the graceful-absence
#     path, presence STATE topics, saturation->None light honesty, additive
#     isolation from raw.obd.*, and the config factory. All paths run with NO
#     hardware wired (device factories are dependency-injected fakes).
# Author: Rex (US-409)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Present + absent path tests for the EDR sensor readers (F-113)."""

from __future__ import annotations

import math

from pi.bus.bus import SampleBus
from pi.bus.sample import QoS
from pi.sensors.sensor_reader import (
    ABSENT,
    PRESENT,
    STATE_IMU,
    STATE_LIGHT,
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_GYRO,
    TOPIC_IMU_MAG,
    TOPIC_IMU_TEMP,
    TOPIC_LIGHT_LUX,
    TOPIC_LIGHT_RAW,
    ImuReader,
    LightReader,
    createSensorReadersFromConfig,
)


# --- Fakes (dependency-injected in place of the real I2C devices) ------------
class FakeImu:
    """Mimics adafruit_icm20x.ICM20948: vector properties + die temp."""

    def __init__(self) -> None:
        self.acceleration = (0.11, 0.22, 9.81)
        self.gyro = (0.01, -0.02, 0.03)
        self.magnetic = (12.0, -34.0, 56.0)
        self.temperature = 27.5


class FakeTsl:
    """Mimics adafruit_tsl2591.TSL2591: lux property + raw channel counts."""

    def __init__(self, *, luxValue: float | None = 123.4, raise_lux: bool = False) -> None:
        self._luxValue = luxValue
        self._raise_lux = raise_lux
        self.visible = 1000
        self.infrared = 250
        self.full_spectrum = 1250

    @property
    def lux(self) -> float:
        if self._raise_lux:
            raise RuntimeError("Overflow reading light channels. Try to reduce the gain.")
        return self._luxValue


def _raising_factory():
    """A device factory that fails to construct -- the absent path."""

    def _factory():
        raise RuntimeError("no sensor on the bus")

    return _factory


def _drain(sub) -> list:
    out = []
    while True:
        s = sub.poll()
        if s is None:
            return out
        out.append(s)


# --- IMU present burst poll --------------------------------------------------
def test_imu_burstPoll_publishesFourTopicsWithSharedSeq():
    """
    Given: an IMU reader with a mock device
    When: one burst poll runs
    Then: raw.imu.{accel,gyro,mag,temp} all publish carrying ONE shared seq
    """
    bus = SampleBus()
    sub = bus.subscribe(["raw.imu.*"], QoS.LOSSY, "t")
    reader = ImuReader(bus, sampleHz=50, deviceFactory=lambda: FakeImu())
    reader.probe()

    reader.pollOnce()

    samples = _drain(sub)
    byTopic = {s.topic: s for s in samples}
    assert set(byTopic) == {
        TOPIC_IMU_ACCEL,
        TOPIC_IMU_GYRO,
        TOPIC_IMU_MAG,
        TOPIC_IMU_TEMP,
    }
    seqs = {s.seq for s in samples}
    assert len(seqs) == 1  # one shared seq across the whole burst
    assert byTopic[TOPIC_IMU_ACCEL].value == (0.11, 0.22, 9.81)
    assert byTopic[TOPIC_IMU_GYRO].value == (0.01, -0.02, 0.03)
    assert byTopic[TOPIC_IMU_MAG].value == (12.0, -34.0, 56.0)
    assert byTopic[TOPIC_IMU_TEMP].value == 27.5
    assert byTopic[TOPIC_IMU_ACCEL].unit == "m/s^2"
    assert byTopic[TOPIC_IMU_TEMP].unit == "degC"
    assert all(s.source == "imu" for s in samples)


class FakeImuNoTemp:
    """Mimics the GENUINE adafruit_icm20x.ICM20948: vector properties present,
    but NO .temperature attribute -- the real chip class does not expose it
    (the live 'ICM20948 object has no attribute temperature' crash, US-500)."""

    def __init__(self) -> None:
        self.acceleration = (0.11, 0.22, 9.81)
        self.gyro = (0.01, -0.02, 0.03)
        self.magnetic = (12.0, -34.0, 56.0)
        # deliberately no .temperature -> float(dev.temperature) raises AttributeError


def test_imu_noTemperatureAttr_publishesAccelGyroMag_tempNone():
    """US-500: a genuine ICM-20948 has no .temperature. A missing temp must
    degrade to honest-null and MUST NOT drop the accel/gyro/mag burst the IMU
    card + EDR actually need -- pre-fix the AttributeError dropped the whole
    poll ('no sample this poll'), so states/imu was never written.
    """
    bus = SampleBus()
    sub = bus.subscribe(["raw.imu.*"], QoS.LOSSY, "t")
    reader = ImuReader(bus, deviceFactory=lambda: FakeImuNoTemp())
    reader.probe()

    reader.pollOnce()

    samples = _drain(sub)
    byTopic = {s.topic: s for s in samples}
    # the critical trio still publishes real values
    assert byTopic[TOPIC_IMU_ACCEL].value == (0.11, 0.22, 9.81)
    assert byTopic[TOPIC_IMU_GYRO].value == (0.01, -0.02, 0.03)
    assert byTopic[TOPIC_IMU_MAG].value == (12.0, -34.0, 56.0)
    # temp degrades to honest-null (never fabricated); the topic is still present
    assert TOPIC_IMU_TEMP in byTopic
    assert byTopic[TOPIC_IMU_TEMP].value is None
    # the whole burst still shares one seq
    assert len({s.seq for s in samples}) == 1


def test_imu_seqIncrementsPerBurstNotPerTopic():
    """Each burst shares one seq; the seq advances by one across bursts."""
    bus = SampleBus()
    sub = bus.subscribe(["raw.imu.*"], QoS.LOSSY, "t")
    reader = ImuReader(bus, deviceFactory=lambda: FakeImu())
    reader.probe()

    reader.pollOnce()
    reader.pollOnce()

    samples = _drain(sub)
    seqs = sorted({s.seq for s in samples})
    assert seqs == [1, 2]  # two bursts -> two distinct seqs, contiguous


# --- IMU absent (graceful-absence) -------------------------------------------
def test_imu_absent_publishesNoSamplesButStateAbsent():
    """
    Given: the IMU device factory fails (nothing wired), flag on
    When: the reader starts
    Then: state.sensor.imu=absent is retained, ZERO raw samples, no crash
    """
    bus = SampleBus()
    rawSub = bus.subscribe(["raw.imu.*"], QoS.LOSSY, "raw")
    reader = ImuReader(bus, deviceFactory=_raising_factory())

    reader.start()

    assert reader.isPresent is False
    # A late STATE subscriber sees the retained absent marker.
    stateSub = bus.subscribe(["state.sensor.*"], QoS.LOSSY, "state")
    state = stateSub.poll()
    assert state is not None
    assert state.topic == STATE_IMU
    assert state.value == ABSENT
    # Not a single raw sample was fabricated.
    assert _drain(rawSub) == []
    reader.stop()


def test_imu_absent_pollOnceFabricatesNothing():
    """Even if pollOnce is invoked on an absent reader, it stays silent."""
    bus = SampleBus()
    rawSub = bus.subscribe(["raw.imu.*"], QoS.LOSSY, "raw")
    reader = ImuReader(bus, deviceFactory=_raising_factory())
    reader.probe()

    reader.pollOnce()

    assert _drain(rawSub) == []


# --- IMU present STATE -------------------------------------------------------
def test_imu_present_publishesStatePresent():
    bus = SampleBus()
    reader = ImuReader(bus, deviceFactory=lambda: FakeImu())

    reader.start()

    stateSub = bus.subscribe(["state.sensor.imu"], QoS.LOSSY, "state")
    state = stateSub.poll()
    assert state is not None
    assert state.topic == STATE_IMU
    assert state.value == PRESENT
    reader.stop()


# --- Light present -----------------------------------------------------------
def test_light_present_publishesStatePresent():
    bus = SampleBus()
    reader = LightReader(bus, deviceFactory=lambda: FakeTsl())

    reader.start()

    stateSub = bus.subscribe([STATE_LIGHT], QoS.LOSSY, "state")
    state = stateSub.poll()
    assert state is not None
    assert state.topic == STATE_LIGHT
    assert state.value == PRESENT
    reader.stop()


def test_light_present_publishesLuxAndRawWithSharedSeq():
    bus = SampleBus()
    sub = bus.subscribe(["raw.light.*"], QoS.LOSSY, "t")
    reader = LightReader(bus, sampleHz=1, deviceFactory=lambda: FakeTsl(luxValue=123.4))
    reader.probe()

    reader.pollOnce()

    samples = _drain(sub)
    byTopic = {s.topic: s for s in samples}
    assert set(byTopic) == {TOPIC_LIGHT_LUX, TOPIC_LIGHT_RAW}
    assert len({s.seq for s in samples}) == 1  # shared seq for the light poll
    assert byTopic[TOPIC_LIGHT_LUX].value == 123.4
    assert byTopic[TOPIC_LIGHT_LUX].unit == "lux"
    assert byTopic[TOPIC_LIGHT_RAW].value == (1000, 250, 1250)
    assert byTopic[TOPIC_LIGHT_RAW].unit == "count"
    assert all(s.source == "light" for s in samples)


# --- Light saturation honesty ------------------------------------------------
def test_light_saturated_publishesLuxNoneButKeepsRawCounts():
    """
    Given: a saturating TSL2591 read (.lux raises)
    When: the reader polls
    Then: raw.light.lux publishes None (never inf), raw counts still published
    """
    bus = SampleBus()
    sub = bus.subscribe(["raw.light.*"], QoS.LOSSY, "t")
    reader = LightReader(bus, deviceFactory=lambda: FakeTsl(raise_lux=True))
    reader.probe()

    reader.pollOnce()

    byTopic = {s.topic: s for s in _drain(sub)}
    assert byTopic[TOPIC_LIGHT_LUX].value is None
    # raw counts survive saturation
    assert byTopic[TOPIC_LIGHT_RAW].value == (1000, 250, 1250)


def test_light_infiniteLux_publishedAsNoneNotInf():
    """A non-finite lux (inf/nan) is published as None, never inf."""
    bus = SampleBus()
    sub = bus.subscribe(["raw.light.lux"], QoS.LOSSY, "t")
    reader = LightReader(bus, deviceFactory=lambda: FakeTsl(luxValue=math.inf))
    reader.probe()

    reader.pollOnce()

    lux = _drain(sub)[0]
    assert lux.value is None


# --- Additive isolation ------------------------------------------------------
def test_sensorReader_neverTouchesRawObd():
    """Sensor channels are additive: they publish nothing on raw.obd.*."""
    bus = SampleBus()
    obdSub = bus.subscribe(["raw.obd.*"], QoS.LOSSLESS, "obd")
    imuSub = bus.subscribe(["raw.imu.*"], QoS.LOSSY, "imu")
    reader = ImuReader(bus, deviceFactory=lambda: FakeImu())
    reader.probe()

    reader.pollOnce()

    assert _drain(obdSub) == []  # OBD lane untouched
    assert len(_drain(imuSub)) == 4  # sensor lane carries the burst


# --- Default (real) factory graceful-absence on a non-Pi host ----------------
def test_imu_defaultFactory_absentOnNonPi():
    """No injected factory: the hardware import fails on this dev box -> the
    reader takes the absent path (never crashes) -- the flag-on-but-absent case."""
    bus = SampleBus()
    reader = ImuReader(bus)  # real default factory
    reader.start()
    assert reader.isPresent is False
    reader.stop()


def test_light_defaultFactory_absentOnNonPi():
    bus = SampleBus()
    reader = LightReader(bus)  # real default factory
    reader.start()
    assert reader.isPresent is False
    reader.stop()


# --- Config factory ----------------------------------------------------------
def test_factory_busDisabled_buildsNothing():
    """Per-sensor flags require pi.bus.enabled; bus off -> no readers."""
    bus = SampleBus()
    config = {
        "pi": {
            "bus": {"enabled": False},
            "sensors": {"imu": {"enabled": True}, "light": {"enabled": True}},
        }
    }
    assert createSensorReadersFromConfig(config, bus) == []


def test_factory_perSensorFlags_buildOnlyEnabled():
    """Each sensor is built only when its own flag AND the bus flag are on."""
    bus = SampleBus()
    config = {
        "pi": {
            "bus": {"enabled": True},
            "sensors": {
                "imu": {"enabled": True, "sampleHz": 50},
                "light": {"enabled": False, "sampleHz": 1},
            },
        }
    }
    readers = createSensorReadersFromConfig(config, bus)
    assert [r.source for r in readers] == ["imu"]


def test_factory_defaultsOff_buildsNothing():
    """Empty/absent sensors config -> dark (default false)."""
    bus = SampleBus()
    assert createSensorReadersFromConfig({"pi": {"bus": {"enabled": True}}}, bus) == []
