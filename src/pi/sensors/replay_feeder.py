################################################################################
# File Name: replay_feeder.py
# Purpose/Description: Replay feeder -- publishes a recorded drive's IMU and
#                      light rows onto the SampleBus in place of the hardware
#                      readers, on the drive's own timing, tagged 'replay'
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-900) | Initial implementation (F-162 sensor replay)
# ================================================================================
################################################################################

"""
Sensor replay feeder for ``pi.replay.active`` (US-900 / F-162).

US-857 replays a recorded drive's OBD rows through the real capture path. This
module does the same for the two EDR sensors: :class:`SensorReplayFeeder` reads
the drive's ``edr_imu_sample`` and ``edr_light_sample`` rows from the replay
SOURCE database and publishes them as the live readers would --
``raw.imu.accel`` / ``raw.imu.gyro`` / ``raw.imu.mag`` under one seq per burst,
``raw.light.lux`` / ``raw.light.raw`` under one seq per poll -- each stamped
``dataSource='replay'``. The real light and IMU bridges and the EDR subscriber
consume them unchanged.

UPS is NOT replayed (CIO R36, 2026-10-13): no drive window holds a recorded UPS
reading, so the battery card keeps reading the live gauge.

Window:
    The drive's window is its first to last ``realtime_data`` row -- the same
    rows US-857 replays, so offset 0 is the same instant on both feeds. Sensor
    rows outside it are not replayed. A drive with no realtime_data rows has no
    window, and a source without the EDR tables has no sensor rows: either way
    nothing is published and the bridges keep their no-data state.

Timing:
    ``ts_utc`` is whole seconds while the IMU runs at tens of Hz, so a row's
    offset is taken from the FIRST in-window row's ``ts_utc`` plus its
    ``ts_capture`` (monotonic) distance from that row. A ``ts_capture`` that
    goes backwards (a reboot inside the window) re-anchors on that row's
    ``ts_utc``. The replay clock starts at :meth:`SensorReplayFeeder.begin`.

Published samples are stamped as the live readers stamp theirs: ``tsUtc`` is
the wall clock at publish and ``tsCapture`` the monotonic clock, so the bridges'
freshness checks see a live feed. The OBD replay stamps its rows the same way.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.time.helper import toCanonicalIso, utcIsoNow
from pi.bus.sample import Sample
from pi.obdii.drive_id import getCurrentDriveId
from pi.sensors.sensor_reader import (
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_GYRO,
    TOPIC_IMU_MAG,
    TOPIC_LIGHT_LUX,
    TOPIC_LIGHT_RAW,
    UNIT_ACCEL,
    UNIT_COUNT,
    UNIT_GYRO,
    UNIT_LUX,
    UNIT_MAG,
)

logger = logging.getLogger(__name__)

__all__ = [
    "REPLAY_DATA_SOURCE",
    "SensorReplayFeeder",
    "createSensorReplayFeederFromConfig",
]

# The origin tag every replayed sample carries (data_source.DATA_SOURCE_VALUES).
REPLAY_DATA_SOURCE = "replay"

# The source database is opened read-only so the replay can never write the
# recorded drive (as US-857's ReplayValueSource does).
_READ_ONLY_URI = "file:{path}?mode=ro"

# Producer ids, matching the live readers' ``source``.
_SOURCE_IMU = "imu"
_SOURCE_LIGHT = "light"

# Upper bound on one wait between rows, so stop() is honoured promptly even
# when the next recorded row is minutes away.
_MAX_WAIT_S = 0.5

_WINDOW_SQL = (
    "SELECT MIN(timestamp), MAX(timestamp) FROM realtime_data WHERE drive_id = ?"
)

_IMU_SQL = (
    "SELECT ts_utc, ts_capture, accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z,"
    " mag_x, mag_y, mag_z FROM edr_imu_sample"
    " WHERE ts_utc >= ? AND ts_utc <= ? ORDER BY ts_utc, ts_capture, id"
)

_LIGHT_SQL = (
    "SELECT ts_utc, ts_capture, lux, visible, infrared, full_spectrum"
    " FROM edr_light_sample"
    " WHERE ts_utc >= ? AND ts_utc <= ? ORDER BY ts_utc, ts_capture, id"
)


def _toEpochSeconds(timestamp: str) -> float:
    """Parse a stored timestamp (canonical ISO UTC; naive read as UTC)."""
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _vector(values: tuple[Any, ...]) -> tuple[float, ...] | None:
    """A stored 3-vector as floats, or None when any axis was not read."""
    if any(v is None for v in values):
        return None
    return tuple(float(v) for v in values)


@dataclass(frozen=True)
class _Burst:
    """One recorded row, ready to publish at ``offset`` seconds into the drive."""

    offset: float
    source: str
    readings: tuple[tuple[str, Any, str], ...]


def _offsets(rows: list[tuple[Any, ...]], windowStart: float) -> list[float]:
    """Offsets into the drive for rows ordered by time (see module Timing)."""
    offsets: list[float] = []
    anchorUtc = anchorCapture = 0.0
    for index, row in enumerate(rows):
        tsUtc, tsCapture = _toEpochSeconds(row[0]), float(row[1])
        if index == 0 or tsCapture < anchorCapture:
            anchorUtc, anchorCapture = tsUtc - windowStart, tsCapture
        offsets.append(anchorUtc + (tsCapture - anchorCapture))
    return offsets


class SensorReplayFeeder:
    """Publishes a recorded drive's IMU and light rows in place of the readers.

    Has the readers' ``start()`` / ``stop()`` lifecycle, so the orchestrator
    starts and stops it where it would the readers.

    Attributes:
        sourcePath: The database the drive is read from.
        driveId: The replayed drive.
        replaysImu: Whether IMU rows are replayed (``pi.sensors.imu.enabled``).
        replaysLight: Whether light rows are replayed (``pi.sensors.light.enabled``).
    """

    def __init__(
        self,
        bus: Any,
        sourcePath: str,
        driveId: int,
        *,
        imu: bool = True,
        light: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        Load the drive window's sensor rows from the source database.

        Args:
            bus: The SampleBus to publish onto (producer role).
            sourcePath: Path of the database holding the recorded drive.
            driveId: drive_id of the drive to replay.
            imu: Replay edr_imu_sample rows.
            light: Replay edr_light_sample rows.
            clock: Monotonic seconds source; injectable for tests.

        Raises:
            sqlite3.Error: If the source database cannot be opened or read.
        """
        self._bus = bus
        self.sourcePath = sourcePath
        self.driveId = driveId
        self.replaysImu = imu
        self.replaysLight = light
        self._clock = clock
        self._startedAt: float | None = None
        self._next = 0
        self._seq = {_SOURCE_IMU: 0, _SOURCE_LIGHT: 0}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._bursts = self._loadBursts()
        logger.info(
            "Sensor replay loaded | sourcePath=%s | drive_id=%s | bursts=%d "
            "(imu=%s light=%s)",
            sourcePath, driveId, len(self._bursts), imu, light,
        )

    def _loadBursts(self) -> list[_Burst]:
        uri = _READ_ONLY_URI.format(path=Path(self.sourcePath).resolve().as_posix())
        conn = sqlite3.connect(uri, uri=True)
        try:
            first, last = conn.execute(_WINDOW_SQL, (self.driveId,)).fetchone()
            if first is None:
                logger.warning(
                    "Sensor replay: drive_id %s has no realtime_data rows -- "
                    "no window, nothing to replay", self.driveId,
                )
                return []
            windowStart = _toEpochSeconds(first)
            bounds = (
                toCanonicalIso(datetime.fromtimestamp(windowStart, UTC)),
                toCanonicalIso(datetime.fromtimestamp(_toEpochSeconds(last), UTC)),
            )
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            bursts: list[_Burst] = []
            if self.replaysImu and "edr_imu_sample" in tables:
                rows = conn.execute(_IMU_SQL, bounds).fetchall()
                for offset, row in zip(_offsets(rows, windowStart), rows, strict=True):
                    readings = (
                        (TOPIC_IMU_ACCEL, _vector(row[2:5]), UNIT_ACCEL),
                        (TOPIC_IMU_GYRO, _vector(row[5:8]), UNIT_GYRO),
                        (TOPIC_IMU_MAG, _vector(row[8:11]), UNIT_MAG),
                    )
                    bursts.append(_Burst(offset, _SOURCE_IMU, tuple(
                        r for r in readings if r[1] is not None
                    )))
            if self.replaysLight and "edr_light_sample" in tables:
                rows = conn.execute(_LIGHT_SQL, bounds).fetchall()
                for offset, row in zip(_offsets(rows, windowStart), rows, strict=True):
                    lux = None if row[2] is None else float(row[2])
                    rawCounts = row[3:6]
                    readings = ((TOPIC_LIGHT_LUX, lux, UNIT_LUX),) + (
                        ()
                        if any(v is None for v in rawCounts)
                        else ((TOPIC_LIGHT_RAW, tuple(int(v) for v in rawCounts), UNIT_COUNT),)
                    )
                    bursts.append(_Burst(offset, _SOURCE_LIGHT, readings))
        finally:
            conn.close()
        # Stable: IMU before light at an equal offset, each table in row order.
        bursts.sort(key=lambda b: b.offset)
        return bursts

    # -- replay ----------------------------------------------------------------
    def begin(self) -> None:
        """Fix the replay's time zero (idempotent: a second call keeps the first)."""
        if self._startedAt is None:
            self._startedAt = self._clock()

    def isFinished(self) -> bool:
        """True once every loaded row has been published (at once when none)."""
        return self._next >= len(self._bursts)

    def publishDue(self) -> int:
        """Publish every row whose offset has been reached.

        Returns:
            The number of rows (bursts) published by this call.
        """
        if self._startedAt is None:
            return 0
        elapsed = self._clock() - self._startedAt
        published = 0
        while self._next < len(self._bursts) and self._bursts[self._next].offset <= elapsed:
            self._publishBurst(self._bursts[self._next])
            self._next += 1
            published += 1
        return published

    def _publishBurst(self, burst: _Burst) -> None:
        self._seq[burst.source] += 1
        seq = self._seq[burst.source]
        for topic, value, unit in burst.readings:
            self._bus.publish(Sample(
                topic=topic,
                source=burst.source,
                value=value,
                unit=unit,
                tsUtc=utcIsoNow(),
                tsCapture=self._clock(),
                driveId=getCurrentDriveId(),
                dataSource=REPLAY_DATA_SOURCE,
                seq=seq,
            ))

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        """Begin the replay and publish on a daemon thread until the last row."""
        self.begin()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="SensorReplayFeeder", daemon=True
        )
        self._thread.start()

    def stop(self, timeoutS: float = 5.0) -> None:
        """Signal the replay thread to exit and join it.

        Args:
            timeoutS: Maximum seconds to wait for the thread to finish.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeoutS)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.publishDue()
            except Exception as e:  # noqa: BLE001 -- a replay fault never crashes boot
                logger.error("Sensor replay publish failed -- replay stopped: %s", e)
                return
            if self.isFinished():
                logger.info("Sensor replay finished | drive_id=%s", self.driveId)
                return
            assert self._startedAt is not None
            due = self._bursts[self._next].offset - (self._clock() - self._startedAt)
            self._stop.wait(min(max(due, 0.0), _MAX_WAIT_S))


def createSensorReplayFeederFromConfig(
    config: dict[str, Any], bus: Any
) -> SensorReplayFeeder | None:
    """Build the sensor replay feeder from validated config, or None.

    Returns None unless ``pi.replay.active``, ``pi.bus.enabled`` and at least
    one of ``pi.sensors.{imu,light}.enabled`` are set -- a disabled sensor is
    not replayed, exactly as a disabled reader is not built.

    Args:
        config: Validated tier-aware config (reads the ``pi`` section).
        bus: The SampleBus the feeder publishes onto.

    Returns:
        A ready-to-start SensorReplayFeeder, or None when there is nothing to replay.

    Raises:
        ValueError: If replay is active without sourcePath or driveId.
    """
    pi = config.get("pi", {}) or {}
    replay = pi.get("replay", {}) or {}
    if not replay.get("active", False) or not pi.get("bus", {}).get("enabled", False):
        return None
    sensors = pi.get("sensors", {}) or {}
    imu = bool(sensors.get("imu", {}).get("enabled", False))
    light = bool(sensors.get("light", {}).get("enabled", False))
    if not (imu or light):
        return None
    sourcePath = replay.get("sourcePath")
    driveId = replay.get("driveId")
    if not sourcePath or driveId is None:
        raise ValueError("pi.replay.active needs pi.replay.sourcePath and pi.replay.driveId")
    return SensorReplayFeeder(bus, sourcePath, int(driveId), imu=imu, light=light)
