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

    def __init__(
        self,
        bus: SampleBus,
        *,
        sampleHz: int = 1,
        deviceFactory: Callable[[], Any] | None = None,
        dataSource: str = "real",
    ) -> None:
        """Bind a reader to the bus.

        Args:
            bus: The SampleBus this reader publishes onto (producer role).
            sampleHz: Bus publish rate in Hz (poll interval = 1 / sampleHz).
            deviceFactory: callable() -> device handle; DI'd for tests/non-Pi.
                Defaults to the subclass's real-hardware factory, which raises
                on a non-Pi host or an absent sensor (the graceful-absent path).
            dataSource: Origin tag stamped on every sample (US-195 contract).
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
        """
        if self._device is None:
            return
        self._seq += 1
        try:
            self._readAndPublish(self._seq)
        except Exception as exc:  # noqa: BLE001 -- one bad read never crashes the loop
            logger.warning(
                "%s read failed (seq=%d, %s) -- no sample this poll",
                self.source,
                self._seq,
                exc,
            )

    def _loop(self) -> None:
        """Poll at the configured rate until stopped."""
        while not self._stop.is_set():
            self.pollOnce()
            self._stop.wait(self._intervalS)

    # -- publishing ------------------------------------------------------------
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

    def __init__(
        self,
        bus: SampleBus,
        *,
        sampleHz: int = DEFAULT_IMU_SAMPLE_HZ,
        deviceFactory: Callable[[], Any] | None = None,
        dataSource: str = "real",
    ) -> None:
        super().__init__(
            bus, sampleHz=sampleHz, deviceFactory=deviceFactory, dataSource=dataSource
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
        temp = float(dev.temperature)
        self._publish(TOPIC_IMU_ACCEL, accel, UNIT_ACCEL, seq)
        self._publish(TOPIC_IMU_GYRO, gyro, UNIT_GYRO, seq)
        self._publish(TOPIC_IMU_MAG, mag, UNIT_MAG, seq)
        self._publish(TOPIC_IMU_TEMP, temp, UNIT_TEMP, seq)


class LightReader(_BaseSensorReader):
    """TSL2591 light reader. Publishes lux (None when saturated -- never inf) and
    the raw channel counts, both under one shared seq (ADR sections 1.1/3)."""

    source = "light"
    stateTopic = STATE_LIGHT

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
        self._publish(TOPIC_LIGHT_LUX, lux, UNIT_LUX, seq)
        self._publish(TOPIC_LIGHT_RAW, (visible, infrared, full), UNIT_COUNT, seq)


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
            ImuReader(bus, sampleHz=imu.get("sampleHz", DEFAULT_IMU_SAMPLE_HZ))
        )
    light = sensors.get("light", {})
    if light.get("enabled", False):
        readers.append(
            LightReader(bus, sampleHz=light.get("sampleHz", DEFAULT_LIGHT_SAMPLE_HZ))
        )
    return readers
