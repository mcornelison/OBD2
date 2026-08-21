################################################################################
# File Name: sensor_reader.py
# Purpose/Description: EDR IMU + light sensor readers (US-409, F-113). Each reader
#                      probes its I2C device at init, and -- only if present --
#                      runs a poll loop publishing raw readings onto the F-110
#                      SampleBus as ADDITIVE LOSSY channels (never touching
#                      raw.obd.*). The IMU is read as one burst per poll
#                      (accel+gyro+mag+temp together) so all four topics carry the
#                      SAME seq (the persistence subscriber, US-410, assembles one
#                      edr_imu_sample row per seq). Graceful-absence: an unwired
#                      sensor produces SILENCE (a retained state.sensor.*=absent
#                      marker + zero samples), never a fabricated 0.0/null a
#                      consumer could mistake for a real zero-g / zero-lux reading.
#                      Light saturation publishes lux=None (never inf). Ships dark
#                      behind pi.sensors.{imu,light}.enabled under pi.bus.enabled.
#                      ADR: docs/superpowers/specs/
#                      2026-06-30-edr-sensor-reader-schema-bus-adr.md sections 1/3.
# Author: Rex (US-409)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Rex (US-409) | Initial -- IMU + light readers, additive bus
#               |              | topics, burst-poll shared seq, graceful-absence,
#               |              | presence STATE, saturation->None, config factory.
# 2026-08-21    | Rex (US-564) | Plausibility/invariance gate on the SUCCESS path:
#               |              | an implausible or bit-identical read is routed
#               |              | into the EXISTING failed-poll path (no new
#               |              | silence mechanism) + a retained per-channel gate
#               |              | STATE; failed-poll WARNING rate-limited.
# ================================================================================
################################################################################

"""EDR IMU + light sensor readers that publish onto the F-110 SampleBus."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from typing import Any

from common.time.helper import utcIsoNow
from pi.bus.bus import SampleBus
from pi.bus.sample import Sample
from pi.obdii.drive_id import getCurrentDriveId

# The accel floor is the SAME constant the tilt maths already refuses to work
# below -- imported, never retyped, so the gate and the level frame cannot drift
# into disagreeing about what counts as a usable specific-force vector.
from pi.sensors.pitch_fusion import MIN_GRAVITY_MS2

# US-564: the gate owns the MECHANISM (bit-identity + magnitude); this module
# owns the PHYSICS (which channel gets which check, and what the floor is).
from pi.sensors.plausibility_gate import (
    DEFAULT_INVARIANT_DWELL_S,
    GATE_OK,
    ChannelPolicy,
    PlausibilityGate,
    channelStateTopic,
    magnitudeAtLeast,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ImuReader",
    "LightReader",
    "createSensorReadersFromConfig",
    "PRESENT",
    "ABSENT",
    "STATE_IMU",
    "STATE_LIGHT",
    "TOPIC_IMU_ACCEL",
    "TOPIC_IMU_GYRO",
    "TOPIC_IMU_MAG",
    "TOPIC_IMU_TEMP",
    "TOPIC_LIGHT_LUX",
    "TOPIC_LIGHT_RAW",
]

# --- Bus topics (additive -- never touch raw.obd.*) -- ADR section 1.1 --------
TOPIC_IMU_ACCEL = "raw.imu.accel"
TOPIC_IMU_GYRO = "raw.imu.gyro"
TOPIC_IMU_MAG = "raw.imu.mag"
TOPIC_IMU_TEMP = "raw.imu.temp"
TOPIC_LIGHT_LUX = "raw.light.lux"
TOPIC_LIGHT_RAW = "raw.light.raw"

# Retained presence STATE topics (ADR section 3). STATE = last-value cache.
STATE_IMU = "state.sensor.imu"
STATE_LIGHT = "state.sensor.light"

# Presence encoded as a float on the STATE topic (the bus Sample.value envelope
# is numeric); the human-readable label rides in the unit field.
PRESENT = 1.0
ABSENT = 0.0
_LABEL_PRESENT = "present"
_LABEL_ABSENT = "absent"

# Units (ADR section 1.1).
UNIT_ACCEL = "m/s^2"
UNIT_GYRO = "rad/s"
UNIT_MAG = "uT"
UNIT_TEMP = "degC"
UNIT_LUX = "lux"
UNIT_COUNT = "count"

# I2C addresses (ADR: ICM-20948 @0x69, TSL2591 @0x29).
ADDR_IMU = 0x69
ADDR_TSL = 0x29

# Default bus publish rates (ADR section 1.2 / 4). Mirrored by the validator
# DEFAULTS registry (pi.sensors.{imu,light}.sampleHz) -- these are the safety
# fallbacks used when a caller passes an unvalidated config.
DEFAULT_IMU_SAMPLE_HZ = 50
DEFAULT_LIGHT_SAMPLE_HZ = 1

# Fallback poll interval when a non-positive sampleHz slips through (defensive;
# the validated config always carries a positive rate).
_FALLBACK_INTERVAL_S = 1.0

# TSL2591 raises on a saturated/overflow lux read; treat these as "unreadable"
# (publish None) rather than a fabricated value.
_SATURATION_ERRORS = (RuntimeError, OverflowError, ValueError, ZeroDivisionError)

# US-564 / Atlas AC-7: how often an ONGOING poll fault re-states itself. The
# TRANSITION always logs immediately; only the repetition is rate-limited. The
# failed-poll WARNING previously fired once per poll, i.e. 50 times a second on
# the IMU (seq reached 128,422 in minutes) -- which is how a real fault hides in
# its own noise. Do NOT silence it: a fault nobody can find in the journal and a
# fault nobody logged are the same fault operationally.
DEFAULT_POLL_FAULT_SUMMARY_S = 60.0


class GatedReadingError(Exception):
    """A successful read that the plausibility gate refused as a non-measurement.

    Raised for a CRITICAL channel only, so it lands in the reader's existing
    ``pollOnce`` failure handler: the poll publishes nothing, the seq still
    advances, and the consumer sees the same honest gap an I/O fault produces.
    Reusing that path is deliberate -- a second silence mechanism would be a
    second thing to keep honest.
    """

    def __init__(self, topic: str, reason: str) -> None:
        """Bind the refusal to the channel and reason that caused it."""
        super().__init__(f"{reason} on {topic}")
        self.topic = topic
        self.reason = reason


class _PollFaultLog:
    """Transition-plus-summary logger for a repeating poll fault.

    Logs the moment a fault STARTS, stays quiet while it persists, re-states it
    with a suppressed-count every ``summaryEveryS``, and logs the recovery. The
    count is part of the message because "still failing" and "failed 3,000 more
    times" are different operational facts.
    """

    def __init__(
        self,
        summaryEveryS: float = DEFAULT_POLL_FAULT_SUMMARY_S,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """Bind the summary interval and (injectable) monotonic clock."""
        self._summaryEveryS = summaryEveryS
        self._clock = clock if clock is not None else time.monotonic
        self._since: dict[str, float] = {}
        self._suppressed: dict[str, int] = {}

    def note(self, key: str, message: str, *args: Any) -> None:
        """Record one occurrence of ``key``, logging on start or on summary."""
        now = self._clock()
        last = self._since.get(key)
        if last is None:
            self._since[key] = now
            self._suppressed[key] = 0
            logger.warning(message, *args)
            return
        self._suppressed[key] = self._suppressed.get(key, 0) + 1
        if (now - last) >= self._summaryEveryS:
            logger.warning(
                "%s -- still failing: %d further occurrences in the last %.0fs",
                message % args if args else message,
                self._suppressed[key],
                now - last,
            )
            self._since[key] = now
            self._suppressed[key] = 0

    def clear(self, key: str, message: str, *args: Any) -> None:
        """Log a recovery iff ``key`` was actually in a fault state."""
        if key not in self._since:
            return
        suppressed = self._suppressed.pop(key, 0)
        self._since.pop(key, None)
        logger.warning("%s (%d occurrences suppressed)", message % args if args else message, suppressed)


class _BaseSensorReader:
    """Shared scaffold for a single-sensor reader (probe + poll loop + STATE).

    Subclasses declare ``source`` / ``stateTopic`` and implement
    :meth:`_defaultDeviceFactory` (the real hardware handle) and
    :meth:`_readAndPublish` (one poll's reads + publishes). The scaffold owns the
    probe/graceful-absence discipline, the per-producer ``seq`` counter, the
    retained presence STATE topic, and the daemon poll thread.
    """

    source: str = ""
    stateTopic: str = ""

    # US-564: the per-channel physics this reader is willing to assert. A topic
    # absent from this map is published unchecked -- enrolling a channel is an
    # evidence decision, never a default (see plausibility_gate's header).
    channelPolicies: dict[str, ChannelPolicy] = {}

    # Channels whose refusal invalidates the WHOLE burst. A gated critical
    # channel routes the poll into the failed-poll path, so no partial row is
    # persisted for that seq; a gated NON-critical channel is silenced alone and
    # its healthy siblings still publish.
    criticalTopics: tuple[str, ...] = ()

    def __init__(
        self,
        bus: SampleBus,
        *,
        sampleHz: int = 1,
        deviceFactory: Callable[[], Any] | None = None,
        dataSource: str = "real",
        invariantDwellSeconds: float = DEFAULT_INVARIANT_DWELL_S,
    ) -> None:
        """Bind a reader to the bus.

        Args:
            bus: The SampleBus this reader publishes onto (producer role).
            sampleHz: Bus publish rate in Hz (poll interval = 1 / sampleHz).
            deviceFactory: callable() -> device handle; DI'd for tests/non-Pi.
                Defaults to the subclass's real-hardware factory, which raises
                on a non-Pi host or an absent sensor (the graceful-absent path).
            dataSource: Origin tag stamped on every sample (US-195 contract).
            invariantDwellSeconds: US-564 check-2 dwell -- how long a channel
                must stay BIT-IDENTICAL before it is reported ``sensor_stale``.
        """
        self._bus = bus
        self._sampleHz = sampleHz
        self._intervalS = 1.0 / sampleHz if sampleHz and sampleHz > 0 else _FALLBACK_INTERVAL_S
        self._deviceFactory = deviceFactory if deviceFactory is not None else self._defaultDeviceFactory
        self._dataSource = dataSource
        self._device: Any | None = None
        self._present = False
        self._probed = False
        self._seq = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._gate = PlausibilityGate(
            sampleHz=sampleHz,
            policies=self.channelPolicies,
            invariantDwellSeconds=invariantDwellSeconds,
        )
        self._faultLog = _PollFaultLog()

    # -- subclass hooks --------------------------------------------------------
    def _defaultDeviceFactory(self) -> Any:
        """Construct the real I2C device handle (raises when absent/non-Pi)."""
        raise NotImplementedError

    def _readAndPublish(self, seq: int) -> None:
        """Read one poll's worth of data and publish it under ``seq``."""
        raise NotImplementedError

    # -- lifecycle -------------------------------------------------------------
    @property
    def isPresent(self) -> bool:
        """True iff the sensor was detected at probe time."""
        return self._present

    def probe(self) -> bool:
        """Detect the sensor once. Absent -> log once at WARN, stay silent.

        Constructing the device performs the I2C handshake (a test read); a
        failure means the sensor is not wired (or we are off-Pi). Absent is
        SAFE, never fatal -- a flag flipped on before the sensor is physically
        present takes this path, not a crash.

        Returns:
            True if the sensor is present, else False.
        """
        self._probed = True
        # A re-probe is a discontinuity: a value read before it must not pair
        # with one read after it to manufacture an invariant run across a gap
        # when the channel was not reading at all.
        self._gate.reset()
        try:
            self._device = self._deviceFactory()
            self._present = True
            logger.info("%s sensor present -- reader armed", self.source)
        except Exception as exc:  # noqa: BLE001 -- absent must be safe, never fatal
            self._device = None
            self._present = False
            logger.warning(
                "%s sensor absent (%s) -- publishing silence (state=absent), "
                "no fabricated samples",
                self.source,
                exc,
            )
        return self._present

    def start(self) -> None:
        """Probe (if not yet), publish the retained STATE, and -- if present --
        start the poll thread. Absent -> STATE=absent + no thread (silence)."""
        if not self._probed:
            self.probe()
        self._publishState()
        if self._present:
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name=f"SensorReader-{self.source}", daemon=True
            )
            self._thread.start()

    def stop(self, timeoutS: float = 5.0) -> None:
        """Signal the poll loop to exit, join the thread, and release the device.

        Args:
            timeoutS: Maximum seconds to wait for the poll thread to finish.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeoutS)
            self._thread = None
        self._closeDevice()

    def pollOnce(self) -> None:
        """Run exactly one poll: bump seq, read, publish. Absent -> no-op.

        A read fault is isolated (logged, no sample) -- reader isolation, the
        producer-side analogue of the PersistenceSubscriber's per-write guard.
        The seq still advances so a downstream consumer sees an honest gap.

        US-564: a read that SUCCEEDS but returns a non-measurement on a critical
        channel lands here too, via GatedReadingError. That is the point -- the
        outcome an operator sees is the same honest gap, produced by the same
        code, and there is exactly one path that means "no sample this poll".
        """
        if self._device is None:
            return
        self._seq += 1
        try:
            self._readAndPublish(self._seq)
        except GatedReadingError as gated:
            self._faultLog.note(
                f"gate:{gated.topic}",
                "%s burst REFUSED by the plausibility gate (seq=%d, %s on %s) "
                "-- no sample this poll; the device answered, the answer was not a reading",
                self.source,
                self._seq,
                gated.reason,
                gated.topic,
            )
        except Exception as exc:  # noqa: BLE001 -- one bad read never crashes the loop
            self._faultLog.note(
                "read",
                "%s read failed (seq=%d, %s) -- no sample this poll",
                self.source,
                self._seq,
                exc,
            )
        else:
            self._faultLog.clear("read", "%s read recovered (seq=%d)", self.source, self._seq)

    def _loop(self) -> None:
        """Poll at the configured rate until stopped."""
        while not self._stop.is_set():
            self.pollOnce()
            self._stop.wait(self._intervalS)

    # -- publishing ------------------------------------------------------------
    def _publishBurst(
        self, readings: tuple[tuple[str, Any, str], ...], seq: int
    ) -> None:
        """Gate one poll's readings, then publish the survivors under ``seq``.

        Every reading is gated BEFORE any of them is published, so the atomic
        burst contract (one edr_imu_sample row per seq, or none) holds regardless
        of the order a subclass lists its channels in. Ordering the checks after
        the publishes would make the guarantee depend on which topic happened to
        be written first -- a correctness property resting on a list's order.

        Args:
            readings: ``(topic, value, unit)`` triples read this poll.
            seq: The shared sequence number for the burst.

        Raises:
            GatedReadingError: When a CRITICAL channel is refused -- nothing has
                been published at that point, so the poll produces the same
                honest silence an I/O fault would.
        """
        verdicts = {topic: self._gate.check(topic, value) for topic, value, _ in readings}
        for topic, verdict in verdicts.items():
            if verdict.changed:
                self._publishChannelState(topic, verdict.reason)
        for topic in self.criticalTopics:
            verdict = verdicts.get(topic)
            if verdict is not None and not verdict.ok:
                raise GatedReadingError(topic, verdict.reason or "")
        for topic, value, unit in readings:
            verdict = verdicts[topic]
            if verdict.ok:
                self._faultLog.clear(
                    f"gate:{topic}", "%s %s channel reading again", self.source, topic
                )
                self._publish(topic, value, unit, seq)
            else:
                self._faultLog.note(
                    f"gate:{topic}",
                    "%s %s REFUSED by the plausibility gate (seq=%d, %s) -- channel "
                    "silenced; derived fields go typed-NA rather than carry it forward",
                    self.source,
                    topic,
                    seq,
                    verdict.reason,
                )

    def _publishChannelState(self, topic: str, reason: str | None) -> None:
        """Publish the retained per-channel gate STATE on a transition.

        Retained + transition-only: a consumer that starts late still learns the
        channel is gated (last-value cache), and a channel gated at 50 Hz costs
        one marker, not fifty a second. The reason rides in the unit field
        exactly as the presence STATE's present/absent label does -- one existing
        mechanism, extended, rather than a second vocabulary to keep honest.
        """
        sample = Sample(
            topic=channelStateTopic(topic),
            source=self.source,
            value=ABSENT if reason else PRESENT,
            unit=reason or GATE_OK,
            tsUtc=utcIsoNow(),
            tsCapture=time.monotonic(),
            driveId=None,
            dataSource=self._dataSource,
            seq=0,
        )
        self._bus.publish(sample, retain=True)

    def _publish(
        self, topic: str, value: float | tuple[float, ...] | None, unit: str, seq: int
    ) -> None:
        """Fan one reading out on the bus (never blocks -- LOSSY drop-oldest)."""
        sample = Sample(
            topic=topic,
            source=self.source,
            value=value,
            unit=unit,
            tsUtc=utcIsoNow(),
            tsCapture=time.monotonic(),
            driveId=getCurrentDriveId(),
            dataSource=self._dataSource,
            seq=seq,
        )
        self._bus.publish(sample)

    def _publishState(self) -> None:
        """Publish the retained presence STATE (present|absent) once."""
        sample = Sample(
            topic=self.stateTopic,
            source=self.source,
            value=PRESENT if self._present else ABSENT,
            unit=_LABEL_PRESENT if self._present else _LABEL_ABSENT,
            tsUtc=utcIsoNow(),
            tsCapture=time.monotonic(),
            driveId=None,
            dataSource=self._dataSource,
            seq=0,
        )
        self._bus.publish(sample, retain=True)

    def _closeDevice(self) -> None:
        """Release the device handle if it exposes ``close`` (best-effort)."""
        dev = self._device
        self._device = None
        close = getattr(dev, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:  # noqa: BLE001 -- close error is non-fatal
                logger.debug("%s device close error (ignored): %s", self.source, exc)


class ImuReader(_BaseSensorReader):
    """ICM-20948 9-DoF IMU reader. One burst poll -> accel+gyro+mag+temp, all
    published under a SINGLE shared seq (ADR section 1.1)."""

    source = "imu"
    stateTopic = STATE_IMU

    # US-564 physics for this chip, and every entry is grounded in a measurement:
    #  - accel carries a MAGNITUDE floor because a stationary sensor must read
    #    ~9.81 m/s^2 and a moving one reads more -- never ~0 (the 43,203 all-zero
    #    rows of 08-17). MIN_GRAVITY_MS2 is the same floor the level frame uses.
    #  - accel/gyro/mag are all enrolled in the BIT-IDENTITY check because this
    #    die was measured dithering: 743 distinct accel values in 90 s stationary
    #    while the magnetometer served 1.
    #  - temp is deliberately NOT enrolled. It is a coarse, slowly-varying
    #    housekeeping channel that is already best-effort/honest-null, nobody has
    #    measured its dither, and it feeds no displayed or derived field.
    channelPolicies = {
        TOPIC_IMU_ACCEL: ChannelPolicy(
            plausible=magnitudeAtLeast(MIN_GRAVITY_MS2), invariance=True
        ),
        TOPIC_IMU_GYRO: ChannelPolicy(invariance=True),
        TOPIC_IMU_MAG: ChannelPolicy(invariance=True),
    }

    # Accel is the burst's load-bearing channel: without it there is no gravity
    # reference, no level frame and no usable edr_imu_sample row, so its refusal
    # takes the whole poll. A refused MAG must NOT -- the 08-20 measurement is
    # that accel and gyro are HEALTHY while the magnetometer is latched, and
    # discarding the burst would throw away valid g-force, pitch and grade data.
    criticalTopics = (TOPIC_IMU_ACCEL,)

    def __init__(
        self,
        bus: SampleBus,
        *,
        sampleHz: int = DEFAULT_IMU_SAMPLE_HZ,
        deviceFactory: Callable[[], Any] | None = None,
        dataSource: str = "real",
        invariantDwellSeconds: float = DEFAULT_INVARIANT_DWELL_S,
    ) -> None:
        super().__init__(
            bus,
            sampleHz=sampleHz,
            deviceFactory=deviceFactory,
            dataSource=dataSource,
            invariantDwellSeconds=invariantDwellSeconds,
        )

    def _defaultDeviceFactory(self) -> Any:
        return _makeIcm20948()

    def _readAndPublish(self, seq: int) -> None:
        dev = self._device
        # Read the whole burst FIRST so a mid-read fault publishes nothing for
        # this seq (atomic burst -> one edr_imu_sample row per seq).
        accel = _vec3(dev.acceleration)
        gyro = _vec3(dev.gyro)
        mag = _vec3(dev.magnetic)
        # US-500: the genuine adafruit_icm20x.ICM20948 does NOT expose
        # .temperature (the clone/FakeImu assumption did). temp is NOT in the
        # states/imu display contract and edr_imu_sample.temp_c is nullable, so a
        # missing/bad temp degrades to honest-null (never fabricated) and must
        # NOT drop the accel/gyro/mag burst the card + EDR need. Best-effort,
        # decoupled from the atomic critical trio above.
        try:
            temp = float(dev.temperature)
        except (AttributeError, TypeError, ValueError):
            temp = None
        self._publishBurst(
            (
                (TOPIC_IMU_ACCEL, accel, UNIT_ACCEL),
                (TOPIC_IMU_GYRO, gyro, UNIT_GYRO),
                (TOPIC_IMU_MAG, mag, UNIT_MAG),
                (TOPIC_IMU_TEMP, temp, UNIT_TEMP),
            ),
            seq,
        )


class LightReader(_BaseSensorReader):
    """TSL2591 light reader. Publishes lux (None when saturated -- never inf) and
    the raw channel counts, both under one shared seq (ADR sections 1.1/3)."""

    source = "light"
    stateTopic = STATE_LIGHT

    # US-564: DELIBERATELY EMPTY, and that is a finding rather than an omission.
    # A photon-counting sensor in real darkness can legitimately return a
    # bit-exact zero indefinitely, so enrolling it in the invariance check would
    # gate a working sensor at night -- and enrolling it WITHOUT first measuring
    # its dither would repeat the unmeasured-assumption defect this whole story
    # exists to delete. Enrol it when a dark-garage capture says what it does.
    channelPolicies: dict[str, ChannelPolicy] = {}
    criticalTopics: tuple[str, ...] = ()

    def __init__(
        self,
        bus: SampleBus,
        *,
        sampleHz: int = DEFAULT_LIGHT_SAMPLE_HZ,
        deviceFactory: Callable[[], Any] | None = None,
        dataSource: str = "real",
    ) -> None:
        super().__init__(
            bus, sampleHz=sampleHz, deviceFactory=deviceFactory, dataSource=dataSource
        )

    def _defaultDeviceFactory(self) -> Any:
        return _makeTsl2591()

    def _readAndPublish(self, seq: int) -> None:
        dev = self._device
        lux = _readLux(dev)
        visible = int(dev.visible)
        infrared = int(dev.infrared)
        full = int(dev.full_spectrum)
        # Honest instrument: lux may be None (saturation), raw counts always go.
        self._publishBurst(
            (
                (TOPIC_LIGHT_LUX, lux, UNIT_LUX),
                (TOPIC_LIGHT_RAW, (visible, infrared, full), UNIT_COUNT),
            ),
            seq,
        )


def _vec3(v: Any) -> tuple[float, float, float]:
    """Coerce a 3-vector reading into a plain float 3-tuple."""
    x, y, z = v
    return (float(x), float(y), float(z))


def _readLux(dev: Any) -> float | None:
    """Read TSL2591 lux, returning None on saturation or a non-finite value.

    The TSL2591 driver raises on an overflow (saturated) read; we translate that
    to None (persist NULL) rather than publish a fabricated or ``inf`` value.
    """
    try:
        lux = dev.lux
    except _SATURATION_ERRORS:
        return None
    if lux is None:
        return None
    try:
        luxF = float(lux)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(luxF):  # never inf/nan
        return None
    return luxF


def _makeI2c() -> Any:  # pragma: no cover -- real-hardware glue (Pi only)
    """Open the primary I2C bus (Pi only; raises on a non-Pi host)."""
    import board  # local import: optional on dev hosts
    import busio

    return busio.I2C(board.SCL, board.SDA)


def _makeIcm20948() -> Any:  # pragma: no cover -- real-hardware glue (Pi only)
    """Construct the ICM-20948 IMU handle (@0x69). Raises when absent/non-Pi."""
    import adafruit_icm20x  # local import: optional on dev hosts

    return adafruit_icm20x.ICM20948(_makeI2c(), address=ADDR_IMU)


def _makeTsl2591() -> Any:  # pragma: no cover -- real-hardware glue (Pi only)
    """Construct the TSL2591 light handle (@0x29). Raises when absent/non-Pi."""
    import adafruit_tsl2591  # local import: optional on dev hosts

    return adafruit_tsl2591.TSL2591(_makeI2c(), address=ADDR_TSL)


def createSensorReadersFromConfig(
    config: dict[str, Any], bus: SampleBus
) -> list[_BaseSensorReader]:
    """Build the enabled sensor readers from validated config.

    Each per-sensor flag REQUIRES ``pi.bus.enabled`` (the master bus gate): with
    the bus off, no reader is built regardless of the per-sensor flags. Ships
    dark -- every flag defaults false, so the returned list is empty until the
    CIO flips a sensor on as he wires it (connect-when-wired).

    Args:
        config: The validated tier-aware config (reads the ``pi`` section).
        bus: The SampleBus the readers publish onto.

    Returns:
        The list of enabled readers (empty when the bus or both sensors are off).
    """
    pi = config.get("pi", {})
    if not pi.get("bus", {}).get("enabled", False):
        return []
    sensors = pi.get("sensors", {})
    readers: list[_BaseSensorReader] = []
    imu = sensors.get("imu", {})
    if imu.get("enabled", False):
        readers.append(
            ImuReader(
                bus,
                sampleHz=imu.get("sampleHz", DEFAULT_IMU_SAMPLE_HZ),
                # US-564: the gate's dwell is a filter constant, not a tuning
                # value, but it is still a NUMBER -- so it lives in config where
                # it can be changed without a code edit.
                invariantDwellSeconds=imu.get(
                    "invariantDwellSeconds", DEFAULT_INVARIANT_DWELL_S
                ),
            )
        )
    light = sensors.get("light", {})
    if light.get("enabled", False):
        readers.append(
            LightReader(bus, sampleHz=light.get("sampleHz", DEFAULT_LIGHT_SAMPLE_HZ))
        )
    return readers
