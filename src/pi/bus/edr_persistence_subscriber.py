################################################################################
# File Name: edr_persistence_subscriber.py
# Purpose/Description: The EDR sibling persistence subscriber (US-410, F-114).
#     Drains the additive raw.imu.*/raw.light.* channels off the F-110 SampleBus
#     and writes edr_imu_sample / edr_light_sample -- a SEPARATE subscriber and
#     SEPARATE tables from the OBD PersistenceSubscriber, so the byte-identical
#     realtime_data golden master is untouched by construction. Each IMU burst
#     (accel+gyro+mag+temp, one shared seq) assembles into ONE edr_imu_sample
#     row; persistence is decimated to a baseline cadence (imu.persistHz);
#     always-on capture stamps drive_id from getCurrentDriveId() ONLY when a
#     drive is RUNNING, else explicit NULL (the A-9 / DTC-KOEO latch -- never
#     inherit a stale _currentDriveId). A rolling-window purge (retentionDays)
#     piggybacks on this subscriber's own drain thread (no new daemon).
#     ADR: docs/superpowers/specs/
#     2026-06-30-edr-sensor-reader-schema-bus-adr.md sections 2.3/2.4/2.6.
# Author: Rex (US-410)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Rex (US-410) | Initial -- EDR sibling subscriber: burst
#               |              | assembly, decimated persist, drive_id NULL-latch,
#               |              | rolling-window retention purge, ships dark.
# ================================================================================
################################################################################

"""EDR sibling persistence subscriber -> edr_imu_sample / edr_light_sample."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from common.edr.sensor_schema import SCHEMA_VERSION
from common.time.helper import CANONICAL_ISO_FORMAT
from pi.obdii.drive_id import getCurrentDriveId

from .sample import QoS, Sample

logger = logging.getLogger(__name__)

__all__ = [
    "EdrPersistenceSubscriber",
    "createEdrPersistenceSubscriberFromConfig",
]

# Additive channels this subscriber owns (never raw.obd.*).
_IMU_PREFIX = "raw.imu."
_LIGHT_PREFIX = "raw.light."

# The fields that make up one assembled row per seq. A burst is "complete" when
# all of a table's fields have arrived under the same seq (the reader publishes
# them atomically); an incomplete burst still flushes on the next-seq boundary.
_IMU_FIELDS = ("accel", "gyro", "mag", "temp")
_LIGHT_FIELDS = ("lux", "raw")

# How long the drain loop blocks waiting for a sample before re-checking _stop.
_DRAIN_TIMEOUT_S = 0.5

# Default rolling-window purge cadence: the purge piggybacks on the drain thread
# (no new daemon, ADR 2.6). Deleting rows older than retentionDays at most hourly
# is ample -- retention is a coarse bound, not a real-time signal.
_DEFAULT_RETENTION_CHECK_S = 3600.0

# Config defaults (mirrored by the validator DEFAULTS registry -- these are the
# safety fallbacks for a caller that passes an unvalidated config).
_DEFAULT_IMU_SAMPLE_HZ = 50
_DEFAULT_IMU_PERSIST_HZ = 25
_DEFAULT_RETENTION_DAYS = 7


def _decimationFactor(sampleHz: Any, persistHz: Any) -> int:
    """Keep-1-of-N factor to decimate the bus rate down to the persist rate.

    50 Hz bus -> 25 Hz persist == keep every 2nd burst. A persistHz at or above
    sampleHz (or a bad value) means keep every burst (factor 1).
    """
    try:
        s = int(sampleHz)
        p = int(persistHz)
    except (TypeError, ValueError):
        return 1
    if s <= 0 or p <= 0:
        return 1
    return max(1, round(s / p))


def _xyz(value: Any) -> tuple[float | None, float | None, float | None]:
    """Split a 3-vector reading into floats; anything else -> (None, None, None)."""
    if isinstance(value, (tuple, list)) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    return (None, None, None)


def _xyzInt(value: Any) -> tuple[int | None, int | None, int | None]:
    """Split a 3-vector of counts into ints; anything else -> (None, None, None)."""
    if isinstance(value, (tuple, list)) and len(value) == 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    return (None, None, None)


def _scalar(value: Any) -> float | None:
    """Coerce a scalar reading to float; None / non-numeric -> None (honest NULL)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class EdrPersistenceSubscriber:
    """Drains raw.imu.*/raw.light.* and persists them to the EDR tables.

    Burst assembly: the IMU reader publishes accel+gyro+mag+temp under one shared
    ``seq``; this subscriber accumulates them and writes exactly one
    ``edr_imu_sample`` row per seq. Light publishes lux+raw under its own seq.
    Persistence is decimated to ``imuPersistHz`` (a subscriber-side concern -- the
    bus still carries full rate for a live display consumer). ``drive_id`` is
    stamped from ``driveIdFn`` ONLY when ``isDrivingFn`` reports a RUNNING drive,
    else explicit NULL (never inherit a stale ``_currentDriveId``). A rolling
    retention purge piggybacks on the drain thread.
    """

    def __init__(
        self,
        subscription: Any,
        database: Any,
        *,
        imuSampleHz: int = _DEFAULT_IMU_SAMPLE_HZ,
        imuPersistHz: int = _DEFAULT_IMU_PERSIST_HZ,
        retentionDays: int = _DEFAULT_RETENTION_DAYS,
        driveIdFn: Callable[[], int | None] = getCurrentDriveId,
        isDrivingFn: Callable[[], bool] | None = None,
        nowUtcFn: Callable[[], datetime] | None = None,
        monotonicFn: Callable[[], float] = time.monotonic,
        retentionCheckIntervalS: float = _DEFAULT_RETENTION_CHECK_S,
    ) -> None:
        """Bind the subscriber to its source subscription + write target.

        Args:
            subscription: The bus Subscription (LOSSY on raw.imu.*/raw.light.*)
                this consumer drains. May be None for direct-handleSample tests.
            database: ObdDatabase whose ``connect()`` yields the EDR write conn.
            imuSampleHz: The IMU bus publish rate (for the decimation ratio).
            imuPersistHz: The decimated IMU persist cadence (ADR 2.3).
            retentionDays: Rolling-window bound; rows older are purged (ADR 2.6).
            driveIdFn: Resolves the current drive_id (default getCurrentDriveId).
            isDrivingFn: Reports whether a drive is RUNNING; default -> always
                False (drive_id NULL -- the safe default that never fabricates a
                drive attribution).
            nowUtcFn: Clock for the retention cutoff (default datetime.now(UTC)).
            monotonicFn: Monotonic clock for the purge cadence gate.
            retentionCheckIntervalS: Minimum seconds between purge attempts.
        """
        self._sub = subscription
        self._database = database
        self._imuDecimateN = _decimationFactor(imuSampleHz, imuPersistHz)
        self._retentionDays = int(retentionDays)
        self._driveIdFn = driveIdFn
        self._isDrivingFn = isDrivingFn if isDrivingFn is not None else (lambda: False)
        self._nowUtcFn = nowUtcFn if nowUtcFn is not None else (lambda: datetime.now(UTC))
        self._monotonic = monotonicFn
        self._retentionCheckIntervalS = float(retentionCheckIntervalS)
        self._lastPurgeMono = self._monotonic()
        # Per-table burst buffers: {"seq", "fields": {name: value}, "tsUtc",
        # "tsCapture", "dataSource"}. None == no burst in progress.
        self._buffers: dict[str, dict[str, Any] | None] = {"imu": None, "light": None}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        """Start the background drain thread."""
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="EdrPersistenceSubscriber", daemon=True
        )
        self._thread.start()

    def stop(self, timeoutS: float = 5.0) -> None:
        """Stop the drain loop, join, and flush any pending partial burst.

        Args:
            timeoutS: Maximum seconds to wait for the drain thread to finish.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeoutS)
            self._thread = None
        # The thread is stopped -> flushing the buffers here cannot race it.
        self.flushPending()

    def _loop(self) -> None:
        """Drain samples until stopped; purge on cadence (subscriber isolation)."""
        if self._sub is None:
            return
        while not self._stop.is_set():
            sample = self._sub.get(timeoutS=_DRAIN_TIMEOUT_S)
            if sample is not None:
                try:
                    self.handleSample(sample)
                except Exception as e:  # noqa: BLE001 -- never crash the loop
                    logger.warning("EDR handleSample failed: %s", e)
            self.maybePurge()

    # -- ingest ----------------------------------------------------------------
    def handleSample(self, sample: Sample) -> bool:
        """Route one sample into its burst buffer.

        Returns True if the sample belongs to an EDR channel (raw.imu.* /
        raw.light.*) and was accumulated; False if it was ignored (an unknown
        field, a decimated-out IMU burst, or a non-EDR topic such as raw.obd.*).
        """
        topic = sample.topic
        if topic.startswith(_IMU_PREFIX):
            field = topic[len(_IMU_PREFIX):]
            if field not in _IMU_FIELDS:
                return False
            # Decimate whole bursts by seq (all 4 IMU topics share one seq, so
            # this keeps/drops the entire burst consistently).
            if sample.seq % self._imuDecimateN != 0:
                return False
            return self._accumulate("imu", field, sample, len(_IMU_FIELDS))
        if topic.startswith(_LIGHT_PREFIX):
            field = topic[len(_LIGHT_PREFIX):]
            if field not in _LIGHT_FIELDS:
                return False
            return self._accumulate("light", field, sample, len(_LIGHT_FIELDS))
        return False

    def _accumulate(
        self, table: str, field: str, sample: Sample, expectedCount: int
    ) -> bool:
        """Add ``field`` to the ``table`` burst; flush on completion or boundary."""
        buf = self._buffers[table]
        if buf is not None and buf["seq"] != sample.seq:
            # A new seq opened before the prior burst completed -> flush the
            # partial (missing fields persist as NULL -- honest gap).
            self._flush(table)
            buf = None
        if buf is None:
            buf = {
                "seq": sample.seq,
                "fields": {},
                "tsUtc": sample.tsUtc,
                "tsCapture": sample.tsCapture,
                "dataSource": sample.dataSource,
            }
            self._buffers[table] = buf
        buf["fields"][field] = sample.value
        if len(buf["fields"]) >= expectedCount:
            self._flush(table)
        return True

    def flushPending(self) -> None:
        """Write out any in-progress bursts (called on stop / after a drain)."""
        self._flush("imu")
        self._flush("light")

    def _flush(self, table: str) -> None:
        """Write the buffered burst for ``table`` as one row, then clear it."""
        buf = self._buffers.get(table)
        if buf is None:
            return
        self._buffers[table] = None
        driveId = self._resolveDriveId()
        try:
            if table == "imu":
                self._writeImuRow(buf, driveId)
            else:
                self._writeLightRow(buf, driveId)
        except Exception as e:  # noqa: BLE001 -- a bad write never crashes the drain
            logger.warning("EDR %s row write failed (seq=%s): %s", table, buf.get("seq"), e)

    def _resolveDriveId(self) -> int | None:
        """drive_id ONLY when a drive is RUNNING, else NULL (never stale-inherit).

        Mirrors the DTC-KOEO ruling (US-404) + the A-9 gap-fence: the fallback on
        any uncertainty is NULL, not a possibly-stale ``_currentDriveId``.
        """
        try:
            if self._isDrivingFn():
                return self._driveIdFn()
        except Exception as e:  # noqa: BLE001 -- fail closed to NULL attribution
            logger.debug("EDR drive_id latch uncertain -> NULL: %s", e)
        return None

    # -- writes ----------------------------------------------------------------
    def _writeImuRow(self, buf: dict[str, Any], driveId: int | None) -> None:
        fields = buf["fields"]
        ax, ay, az = _xyz(fields.get("accel"))
        gx, gy, gz = _xyz(fields.get("gyro"))
        mx, my, mz = _xyz(fields.get("mag"))
        tempC = _scalar(fields.get("temp"))
        with self._database.connect() as conn:
            conn.execute(
                "INSERT INTO edr_imu_sample "
                "(ts_utc, ts_capture, seq, accel_x, accel_y, accel_z, "
                "gyro_x, gyro_y, gyro_z, mag_x, mag_y, mag_z, temp_c, "
                "drive_id, data_source, schema_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    buf["tsUtc"], buf["tsCapture"], buf["seq"],
                    ax, ay, az, gx, gy, gz, mx, my, mz, tempC,
                    driveId, buf["dataSource"], SCHEMA_VERSION,
                ),
            )

    def _writeLightRow(self, buf: dict[str, Any], driveId: int | None) -> None:
        fields = buf["fields"]
        lux = _scalar(fields.get("lux"))  # None when saturated -> NULL, never inf
        visible, infrared, full = _xyzInt(fields.get("raw"))
        with self._database.connect() as conn:
            conn.execute(
                "INSERT INTO edr_light_sample "
                "(ts_utc, ts_capture, seq, lux, visible, infrared, full_spectrum, "
                "drive_id, data_source, schema_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    buf["tsUtc"], buf["tsCapture"], buf["seq"],
                    lux, visible, infrared, full,
                    driveId, buf["dataSource"], SCHEMA_VERSION,
                ),
            )

    # -- retention -------------------------------------------------------------
    def maybePurge(self) -> bool:
        """Run the rolling-window purge if the cadence interval has elapsed.

        Returns True iff a purge attempt ran this call (cadence due), else False.
        """
        now = self._monotonic()
        if now - self._lastPurgeMono < self._retentionCheckIntervalS:
            return False
        self._lastPurgeMono = now
        try:
            imuDeleted, lightDeleted = self.purgeExpired()
            if imuDeleted or lightDeleted:
                logger.info(
                    "EDR retention purge: deleted imu=%d light=%d (older than %d days)",
                    imuDeleted, lightDeleted, self._retentionDays,
                )
        except Exception as e:  # noqa: BLE001 -- purge failure is non-fatal
            logger.warning("EDR retention purge failed: %s", e)
        return True

    def purgeExpired(self) -> tuple[int, int]:
        """Delete rows older than ``retentionDays`` from both EDR tables.

        Returns:
            (imuRowsDeleted, lightRowsDeleted).
        """
        cutoff = (self._nowUtcFn() - timedelta(days=self._retentionDays)).strftime(
            CANONICAL_ISO_FORMAT
        )
        with self._database.connect() as conn:
            imuDeleted = conn.execute(
                "DELETE FROM edr_imu_sample WHERE ts_utc < ?", (cutoff,)
            ).rowcount
            lightDeleted = conn.execute(
                "DELETE FROM edr_light_sample WHERE ts_utc < ?", (cutoff,)
            ).rowcount
        return (imuDeleted, lightDeleted)

    # -- observability ---------------------------------------------------------
    def stats(self) -> Any:
        """Return the subscription's SubStats snapshot (None if no subscription)."""
        return self._sub.stats() if self._sub is not None else None


def createEdrPersistenceSubscriberFromConfig(
    config: dict[str, Any],
    bus: Any,
    database: Any,
    *,
    driveDetector: Any = None,
) -> EdrPersistenceSubscriber | None:
    """Build the EDR subscriber from validated config, or None when it ships dark.

    Returns None unless ``pi.bus.enabled`` AND at least one of
    ``pi.sensors.{imu,light}.enabled`` is set -- so with the default flags off,
    nothing is built and there are zero EDR writes (the OBD path is untouched).

    Args:
        config: Validated tier-aware config (reads the ``pi`` section).
        bus: The SampleBus to subscribe to (LOSSY on raw.imu.*/raw.light.*).
        database: ObdDatabase for the EDR row writes.
        driveDetector: Optional DriveDetector; its ``isDriving()`` gates the
            drive_id latch. Absent -> drive_id is always NULL (safe default).

    Returns:
        A started-ready EdrPersistenceSubscriber, or None when disabled.
    """
    pi = config.get("pi", {})
    if not pi.get("bus", {}).get("enabled", False):
        return None
    sensors = pi.get("sensors", {})
    imu = sensors.get("imu", {})
    light = sensors.get("light", {})
    if not (imu.get("enabled", False) or light.get("enabled", False)):
        return None

    subscription = bus.subscribe(
        [_IMU_PREFIX + "*", _LIGHT_PREFIX + "*"], QoS.LOSSY, "edr-persistence"
    )

    isDrivingFn: Callable[[], bool] | None = None
    if driveDetector is not None:
        def isDrivingFn() -> bool:
            try:
                return bool(driveDetector.isDriving())
            except Exception:  # noqa: BLE001 -- fail closed: no RUNNING drive
                return False

    return EdrPersistenceSubscriber(
        subscription,
        database,
        imuSampleHz=imu.get("sampleHz", _DEFAULT_IMU_SAMPLE_HZ),
        imuPersistHz=imu.get("persistHz", _DEFAULT_IMU_PERSIST_HZ),
        retentionDays=sensors.get("retentionDays", _DEFAULT_RETENTION_DAYS),
        driveIdFn=getCurrentDriveId,
        isDrivingFn=isDrivingFn,
    )
