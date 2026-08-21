################################################################################
# File Name: test_sensor_reader_plausibility_gate.py
# Purpose/Description: US-564 WIRING gate -- proves the plausibility gate is
#   actually reached from the reader's success path, that a refusal routes into
#   the EXISTING failed-poll path (no new silence mechanism), that a gated
#   channel does not take its healthy siblings with it, and that the absence +
#   error paths are behaviourally UNCHANGED (Atlas AC-4 regression clause).
#
#   The gate's own logic is pinned in test_plausibility_gate.py. THIS file is
#   about the seam: a gate nothing calls is a comment.
# Author: Rex (US-564)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-564) | Initial -- burst suppression, per-channel
#               |              | silence, retained gate STATE, rate-limited log,
#               |              | absence/error-path regression.
# ================================================================================
################################################################################

"""Tests for the US-564 gate as wired into the EDR sensor readers."""

from __future__ import annotations

import logging
import math

import pytest

from pi.sensors.plausibility_gate import (
    GATE_OK,
    REASON_SENSOR_MUTE,
    REASON_SENSOR_STALE,
    channelStateTopic,
)
from pi.sensors.sensor_reader import (
    ABSENT,
    PRESENT,
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_GYRO,
    TOPIC_IMU_MAG,
    TOPIC_IMU_TEMP,
    TOPIC_LIGHT_LUX,
    TOPIC_LIGHT_RAW,
    GatedReadingError,
    ImuReader,
    LightReader,
)


class _RecordingBus:
    """Minimal SampleBus double: records every publish, retained or not."""

    def __init__(self) -> None:
        self.published: list = []
        self.retained: list = []

    def publish(self, sample, retain: bool = False) -> None:
        self.published.append(sample)
        if retain:
            self.retained.append(sample)

    def topics(self) -> list[str]:
        return [s.topic for s in self.published]


class _FakeImu:
    """An ICM-20948 stand-in whose three channels are independently scriptable."""

    def __init__(self) -> None:
        self._i = 0
        self.latchMag = False
        self.zeroAccel = False
        self.magnetic = (-26.7, 11.4, -40.2)

    @property
    def acceleration(self):
        self._i += 1
        if self.zeroAccel:
            return (0.0, 0.0, 0.0)
        # Real +/-1 ULP dither, the behaviour the gate relies on.
        return (0.03, -0.01, math.nextafter(9.81, math.inf if self._i % 2 else -math.inf))

    @property
    def gyro(self):
        return (0.001 * self._i, 0.0, 0.0)

    @property
    def temperature(self):
        raise AttributeError("the genuine ICM20948 has no .temperature (US-500)")


def _imu(bus, **kw) -> ImuReader:
    """An armed IMU reader over the fake device (probe already succeeded)."""
    dev = kw.pop("device", None) or _FakeImu()
    reader = ImuReader(bus, sampleHz=kw.pop("sampleHz", 50), deviceFactory=lambda: dev, **kw)
    reader.probe()
    reader.device = dev  # convenience handle for the tests
    return reader


def _pump(reader, n: int) -> None:
    for _ in range(n):
        reader.pollOnce()


def _limit(reader) -> int:
    return reader._gate.invariantRunLimit


class TestGateIsReachedFromTheSuccessPath:
    """A gate the reader never calls would pass every test in the other file."""

    def test_pollOnce_allZeroAccelBurst_publishesNothingAtAll(self):
        """
        Given: the device returns a bit-exact all-zero acceleration vector
        When: one poll runs
        Then: NOT ONE topic is published -- not gyro, not mag, not temp. The
              burst is atomic, so no partial edr_imu_sample row can be
              assembled for this seq (Atlas AC-1: "no persisted row").
        """
        bus = _RecordingBus()
        dev = _FakeImu()
        dev.zeroAccel = True
        reader = _imu(bus, device=dev)
        bus.published.clear()

        reader.pollOnce()

        assert [t for t in bus.topics() if t.startswith("raw.")] == []

    def test_pollOnce_allZeroAccel_advancesSeqSoTheGapIsVisible(self):
        """
        Given: a refused burst
        When: the poll completes
        Then: seq still advanced -- a consumer sees an honest GAP, exactly as an
              I/O fault produces. A refusal that also hid the missing sample
              would make the data look continuous.
        """
        bus = _RecordingBus()
        dev = _FakeImu()
        dev.zeroAccel = True
        reader = _imu(bus, device=dev)
        before = reader._seq

        reader.pollOnce()

        assert reader._seq == before + 1

    def test_pollOnce_healthyBurst_stillPublishesAllFourTopics(self):
        """
        Given: a perfectly normal burst
        When: one poll runs
        Then: all four topics publish under one seq -- the gate must be
              invisible on the happy path or it is a regression, not a guard
        """
        bus = _RecordingBus()
        reader = _imu(bus)
        bus.published.clear()

        reader.pollOnce()

        raw = [s for s in bus.published if s.topic.startswith("raw.")]
        assert {s.topic for s in raw} == {
            TOPIC_IMU_ACCEL,
            TOPIC_IMU_GYRO,
            TOPIC_IMU_MAG,
            TOPIC_IMU_TEMP,
        }
        assert len({s.seq for s in raw}) == 1

    def test_gatedReadingError_isRaisedForACriticalChannelOnly(self):
        """
        Given: the burst publisher facing a refused CRITICAL channel
        When: it is called directly
        Then: it raises GatedReadingError carrying the topic + reason, which is
              what routes the poll into the existing failed-poll handler
        """
        bus = _RecordingBus()
        reader = _imu(bus)
        with pytest.raises(GatedReadingError) as exc:
            reader._publishBurst(((TOPIC_IMU_ACCEL, (0.0, 0.0, 0.0), "m/s^2"),), 1)
        assert exc.value.topic == TOPIC_IMU_ACCEL
        assert exc.value.reason == REASON_SENSOR_MUTE


class TestGatedChannelDoesNotTakeItsSiblings:
    """The 08-20 measurement: mag latched, accel + gyro HEALTHY."""

    def test_pollOnce_latchedMag_silencesMagButKeepsAccelAndGyro(self):
        """
        Given: the magnetometer serving one value forever while accel dithers
        When: the run passes the invariance limit
        Then: mag stops publishing and accel/gyro keep going. Dropping the whole
              burst would discard the valid g-force / pitch / grade data Atlas
              confirmed is healthy -- the guard must not cost more than the fault.
        """
        bus = _RecordingBus()
        reader = _imu(bus)
        _pump(reader, _limit(reader) + 5)
        recent = [s.topic for s in bus.published[-12:]]

        assert TOPIC_IMU_MAG not in recent
        assert TOPIC_IMU_ACCEL in recent
        assert TOPIC_IMU_GYRO in recent

    def test_pollOnce_latchedMag_publishesNoMagSampleAfterTheLimit(self):
        """
        Given: a channel proven latched
        When: polling continues indefinitely
        Then: the mag topic never publishes again -- so the assembled EDR row
              carries NULL mag columns rather than a value nobody measured
        """
        bus = _RecordingBus()
        reader = _imu(bus)
        _pump(reader, _limit(reader))
        bus.published.clear()
        _pump(reader, 20)

        assert TOPIC_IMU_MAG not in bus.topics()

    def test_pollOnce_magRecovers_resumesPublishing(self):
        """
        Given: a gated magnetometer that starts reading again (US-565's fix)
        When: a genuinely new value arrives
        Then: the channel publishes again with no restart -- the gate is a
              latch on EVIDENCE, not a latch on the channel
        """
        bus = _RecordingBus()
        reader = _imu(bus)
        _pump(reader, _limit(reader) + 2)
        bus.published.clear()
        reader.device.magnetic = (-25.1, 11.4, -40.2)
        reader.pollOnce()

        assert TOPIC_IMU_MAG in bus.topics()


class TestRetainedChannelGateState:
    """The marker that lets a LATE consumer learn the channel is gated."""

    def test_gateState_isPublishedRetainedOnTheRefusalTransition(self):
        """
        Given: a channel crossing into stale
        When: the transition happens
        Then: a RETAINED marker goes out carrying the reason, so a subscriber
              that starts afterwards still learns the channel is not measuring
        """
        bus = _RecordingBus()
        reader = _imu(bus)
        _pump(reader, _limit(reader))
        markers = [s for s in bus.retained if s.topic == channelStateTopic(TOPIC_IMU_MAG)]

        assert len(markers) == 1
        assert markers[0].unit == REASON_SENSOR_STALE
        assert markers[0].value == ABSENT

    def test_gateState_isNotRepublishedPerPoll(self):
        """
        Given: a channel that stays gated for hundreds of polls at 50 Hz
        When: polling continues
        Then: exactly ONE marker exists. A per-poll retained publish would be
              the same 50 Hz flood AC-7 exists to stop, wearing a state topic.
        """
        bus = _RecordingBus()
        reader = _imu(bus)
        _pump(reader, _limit(reader) + 200)
        markers = [s for s in bus.retained if s.topic == channelStateTopic(TOPIC_IMU_MAG)]

        assert len(markers) == 1

    def test_gateState_recoveryMarkerIsPublished(self):
        """
        Given: a gated channel that recovers
        When: the transition back happens
        Then: an OK marker goes out -- otherwise the retained cache would hold
              `sensor_stale` forever and a healed sensor would stay greyed out
        """
        bus = _RecordingBus()
        reader = _imu(bus)
        _pump(reader, _limit(reader))
        reader.device.magnetic = (-25.1, 11.4, -40.2)
        reader.pollOnce()
        markers = [s for s in bus.retained if s.topic == channelStateTopic(TOPIC_IMU_MAG)]

        assert [m.unit for m in markers] == [REASON_SENSOR_STALE, GATE_OK]
        assert markers[-1].value == PRESENT

    def test_gateState_topicIsDistinctFromThePresenceState(self):
        """
        Given: the gate marker and the presence marker
        When: their topics are compared
        Then: they differ -- "wired but not measuring" must not overwrite
              "not wired", they are different facts about different things
        """
        from pi.sensors.sensor_reader import STATE_IMU

        assert channelStateTopic(TOPIC_IMU_MAG) != STATE_IMU


class TestFailedPollLoggingIsRateLimited:
    """AC-7 -- log the transition + a periodic summary; do NOT silence it."""

    def test_gatedChannel_logsOnceNotPerPoll(self, caplog):
        """
        Given: a latched channel polled 200 times past the limit
        When: the WARNINGs are counted
        Then: one line, not two hundred. The pre-US-564 failed-poll WARNING
              fired per poll (seq reached 128,422 in minutes), which is how a
              real fault hides inside its own noise.
        """
        bus = _RecordingBus()
        reader = _imu(bus)
        _pump(reader, _limit(reader) - 1)
        with caplog.at_level(logging.WARNING):
            _pump(reader, 200)
        gateLines = [r for r in caplog.records if "plausibility gate" in r.getMessage()]

        assert len(gateLines) == 1

    def test_gatedChannel_theOneLineNamesTheChannelAndTheReason(self, caplog):
        """
        Given: the single WARNING a gated channel produces
        When: it is read
        Then: it says WHICH channel and WHY -- a rate-limited log that drops the
              diagnosis has traded one unusable extreme for the other
        """
        bus = _RecordingBus()
        reader = _imu(bus)
        with caplog.at_level(logging.WARNING):
            _pump(reader, _limit(reader) + 1)
        line = next(r.getMessage() for r in caplog.records if "plausibility gate" in r.getMessage())

        assert TOPIC_IMU_MAG in line
        assert REASON_SENSOR_STALE in line

    def test_readFailure_stillLogsOnTheFirstOccurrence(self, caplog):
        """
        Given: a genuine I/O fault (the pre-existing error path)
        When: a poll runs
        Then: the WARNING still appears immediately. Rate-limiting must delay
              REPETITION, never the first report of a new fault.
        """

        class _Broken:
            @property
            def acceleration(self):
                raise OSError("[Errno 121] Remote I/O error")

        bus = _RecordingBus()
        reader = _imu(bus, device=_Broken())
        with caplog.at_level(logging.WARNING):
            reader.pollOnce()

        assert any("read failed" in r.getMessage() for r in caplog.records)

    def test_readFailure_isNotRepeatedEveryPoll(self, caplog):
        """
        Given: a permanently broken device
        When: it is polled 100 times
        Then: one line -- the same flood applies to the I/O path, and AC-7's
              complaint was about the failed-poll WARNING generally
        """

        class _Broken:
            @property
            def acceleration(self):
                raise OSError("[Errno 121] Remote I/O error")

        bus = _RecordingBus()
        reader = _imu(bus, device=_Broken())
        with caplog.at_level(logging.WARNING):
            _pump(reader, 100)

        assert len([r for r in caplog.records if "read failed" in r.getMessage()]) == 1


class TestAbsenceAndErrorPathsAreUnchanged:
    """Atlas AC-4 regression clause -- the proven-honest paths must not move."""

    def test_probe_absentSensor_publishesAbsentStateAndNoSamples(self):
        """
        Given: a sensor that is not wired (the device factory raises)
        When: the reader starts
        Then: retained state=absent and ZERO raw samples -- behaviourally
              identical to before the gate existed
        """

        def _missing():
            raise OSError("no device at 0x69")

        bus = _RecordingBus()
        reader = ImuReader(bus, sampleHz=50, deviceFactory=_missing)
        reader.start()

        assert reader.isPresent is False
        assert [s for s in bus.published if s.topic.startswith("raw.")] == []
        assert bus.retained[-1].unit == "absent"

    def test_pollOnce_absentSensor_isANoOp(self):
        """
        Given: an absent sensor
        When: pollOnce is called
        Then: nothing is published and seq does not advance (unchanged)
        """

        def _missing():
            raise OSError("no device")

        bus = _RecordingBus()
        reader = ImuReader(bus, sampleHz=50, deviceFactory=_missing)
        reader.probe()
        bus.published.clear()
        reader.pollOnce()

        assert bus.published == []
        assert reader._seq == 0

    def test_pollOnce_readRaises_publishesNothingAndNeverCrashes(self):
        """
        Given: a mid-burst I/O fault
        When: the poll runs
        Then: no samples, no exception escapes -- reader isolation, unchanged
        """

        class _Broken:
            @property
            def acceleration(self):
                raise OSError("bus error")

        bus = _RecordingBus()
        reader = _imu(bus, device=_Broken())
        bus.published.clear()
        reader.pollOnce()

        assert [s for s in bus.published if s.topic.startswith("raw.")] == []

    def test_probe_resetsTheGateAcrossAReplug(self):
        """
        Given: an in-progress invariant run interrupted by a re-probe
        When: the sensor comes back serving the same value
        Then: a FULL fresh run is required. Pairing a pre-unplug reading with a
              post-replug one would manufacture a stale verdict over a window
              in which the channel was not reading at all.
        """
        bus = _RecordingBus()
        reader = _imu(bus)
        _pump(reader, _limit(reader) - 1)
        reader.probe()
        bus.published.clear()
        _pump(reader, _limit(reader) - 1)

        assert TOPIC_IMU_MAG in bus.topics()


class TestLightReaderIsDeliberatelyUnenrolled:
    """A channel whose dither nobody measured must not be gated on a guess."""

    def test_lightReader_repeatedIdenticalReads_areNeverGated(self):
        """
        Given: a TSL2591 in real darkness returning a bit-exact zero forever
        When: it is polled far past any run limit
        Then: it keeps publishing. Enrolling it without measuring its dither
              would gate a WORKING sensor at night -- the same
              unmeasured-assumption defect this story exists to delete.
        """

        class _DarkTsl:
            lux = 0.0
            visible = 0
            infrared = 0
            full_spectrum = 0

        bus = _RecordingBus()
        reader = LightReader(bus, sampleHz=1, deviceFactory=_DarkTsl)
        reader.probe()
        bus.published.clear()
        _pump(reader, 50)

        assert bus.topics().count(TOPIC_LIGHT_LUX) == 50
        assert bus.topics().count(TOPIC_LIGHT_RAW) == 50

    def test_lightReader_declaresNoPolicyAndNoCriticalTopic(self):
        """
        Given: the LightReader class
        When: its gate declarations are read
        Then: both are empty. Pinned STRUCTURALLY because the behavioural test
              above passes just as well if someone enrols the channel with a
              predicate that happens to accept zero -- and that would be a
              latent gate on a working sensor waiting for a darker night.
        """
        assert LightReader.channelPolicies == {}
        assert LightReader.criticalTopics == ()


class TestChannelEnrolmentIsPinned:
    """What IS enrolled is a claim about hardware -- pin it, don't assume it."""

    def test_imuReader_enrolsAccelGyroMagButNotTemp(self):
        """
        Given: the IMU's declared policies
        When: they are read
        Then: accel/gyro/mag are enrolled in invariance and temp is not. temp is
              a coarse housekeeping channel whose dither nobody measured, and it
              feeds no displayed or derived field.
        """
        policies = ImuReader.channelPolicies

        assert set(policies) == {TOPIC_IMU_ACCEL, TOPIC_IMU_GYRO, TOPIC_IMU_MAG}
        assert all(p.invariance for p in policies.values())
        assert TOPIC_IMU_TEMP not in policies

    def test_imuReader_onlyAccelCarriesAMagnitudeFloor(self):
        """
        Given: the IMU's declared policies
        When: the check-1 predicates are read
        Then: only accel has one. A magnetometer field floor and a gyro rate
              floor would both be invented physics -- a stationary gyro really
              does read ~0 rad/s, so a floor there would gate a parked car.
        """
        policies = ImuReader.channelPolicies

        assert policies[TOPIC_IMU_ACCEL].plausible is not None
        assert policies[TOPIC_IMU_GYRO].plausible is None
        assert policies[TOPIC_IMU_MAG].plausible is None

    def test_imuReader_onlyAccelIsBurstCritical(self):
        """
        Given: the IMU's critical-channel declaration
        When: it is read
        Then: it is accel alone. Adding mag would discard every healthy accel
              and gyro row for the duration of the latch -- the fault would cost
              more through the guard than it does through the defect.
        """
        assert ImuReader.criticalTopics == (TOPIC_IMU_ACCEL,)
