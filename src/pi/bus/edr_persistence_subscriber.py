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
#     ADR: $FLEET_SHARE/knowledge/superpowers/specs/
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
# 2026-09-18    | Rex          | US-767-b: optional logGate; every row is
#               |              | routed through EdrLogGate.admit() when wired.
# 2026-09-18    | Rex          | US-767-c: gate state published to
#               |              | states/edr-log-gate on every state change.
# 2026-09-18    | Rex          | US-768: purgeExpired() is sync-gated (id <=
#               |              | high-water mark); unreadable mark deletes
#               |              | nothing; below 15 GB free it only WARNS.
# 2026-09-22    | Rex (US-801) | IMU sample/persist defaults imported from the
#               |              | single definition in common.config.validator.
# ================================================================================
################################################################################

"""EDR sibling persistence subscriber -> edr_imu_sample / edr_light_sample."""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

# US-801: the IMU rate defaults are DEFINED once, in the validator.
from common.config.validator import DEFAULT_IMU_PERSIST_HZ as _DEFAULT_IMU_PERSIST_HZ
from common.config.validator import DEFAULT_IMU_SAMPLE_HZ as _DEFAULT_IMU_SAMPLE_HZ
from common.edr.sensor_schema import SCHEMA_VERSION
from common.time.helper import CANONICAL_ISO_FORMAT
from pi.obdii.drive_id import getCurrentDriveId
from src.pi.data import sync_log

from .edr_log_gate import EdrLogGate
from .sample import QoS, Sample

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_STATES_DIR",
    "EDR_LOG_GATE_STATE_FILENAME",
    "EdrPersistenceSubscriber",
    "buildEdrLogGateState",
    "createEdrPersistenceSubscriberFromConfig",
    "makeEdrLogGateStateEmitter",
]

# US-767-c: the state name the gate publishes to (GET /edr-log-gate).
EDR_LOG_GATE_STATE_FILENAME = "edr-log-gate"

# The tmpfs states dir every states/ writer defaults to (pi.splash.statesDir).
DEFAULT_STATES_DIR = "/run/eclipse-obd/states"

# Matches the other state emitters' `ts` format (second resolution, UTC).
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

# Additive channels this subscriber owns (never raw.obd.*).
_IMU_PREFIX = "raw.imu."
_LIGHT_PREFIX = "raw.light."

# ARCH-009. edr_light_sample.gain stores a LABEL ('low'|'med'|'high'|'max');
# the chip reports a register code. An unrecognised code maps to None -- it is
# not evidence of a gain setting, and inventing one would be a fabricated
# context, which is the defect class this story exists to close.
_GAIN_LABELS = {0x00: "low", 0x10: "med", 0x20: "high", 0x30: "max"}


def _gainLabel(code):
    """TSL2591 gain register code -> the schema's text label, or None."""
    if not isinstance(code, int) or isinstance(code, bool):
        return None
    return _GAIN_LABELS.get(code)

# The fields that make up one assembled row per seq. A burst is "complete" when
# all of a table's fields have arrived under the same seq (the reader publishes
# them atomically); an incomplete burst still flushes on the next-seq boundary.
_IMU_FIELDS = ("accel", "gyro", "mag", "temp")
_LIGHT_FIELDS = ("lux", "raw", "range")

# How long the drain loop blocks waiting for a sample before re-checking _stop.
_DRAIN_TIMEOUT_S = 0.5

# Default rolling-window purge cadence: the purge piggybacks on the drain thread
# (no new daemon, ADR 2.6). Deleting rows older than retentionDays at most hourly
# is ample -- retention is a coarse bound, not a real-time signal.
_DEFAULT_RETENTION_CHECK_S = 3600.0

# US-768: below this much free space the purge WARNS (and still deletes no
# unsynced row). 15 GB is the floor the story states; decimal GB.
_BYTES_PER_GB = 1000**3
_LOW_DISK_WARN_GB = 15
_LOW_DISK_WARN_BYTES = _LOW_DISK_WARN_GB * _BYTES_PER_GB

# Config defaults -- the safety fallbacks for a caller that passes an
# unvalidated config. The IMU sample/persist rates are imported above (US-801);
# retentionDays is mirrored by the validator DEFAULTS registry.
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
        logGate: EdrLogGate | None = None,
        gateStateEmitFn: Callable[[EdrLogGate], None] | None = None,
        freeDiskBytesFn: Callable[[], int] | None = None,
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
            logGate: The EDR log gate every row is routed through (US-767-b).
                None writes every row (the pre-gate behaviour).
            gateStateEmitFn: Called with the gate whenever its state differs
                from the last one published (US-767-c: states/edr-log-gate).
                None publishes nothing.
            freeDiskBytesFn: Free bytes on the database volume, read by the
                purge's low-disk warning (US-768). None measures the volume
                holding ``database.dbPath``.
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
        self._logGate = logGate
        self._gateStateEmitFn = gateStateEmitFn
        self._publishedGateState: str | None = None
        self._freeDiskBytesFn = (
            freeDiskBytesFn if freeDiskBytesFn is not None else self._freeDiskBytes
        )
        self._lastPurgeMono = self._monotonic()
        # Per-table burst buffers: {"seq", "fields": {name: value}, "tsUtc",
        # "tsCapture", "dataSource"}. None == no burst in progress.
        self._buffers: dict[str, dict[str, Any] | None] = {"imu": None, "light": None}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # ARCH-030: one REUSED write connection per writing thread.
        # See _writeConn() for why a fresh connection per row was catastrophic.
        self._tls = threading.local()

    # -- write connection ------------------------------------------------------
    def _writeConn(self) -> Any:
        """Return this thread's reusable write connection, opening it once.

        ARCH-030 (measured on chi-eclipse-01 2026-09-16, idle, no OBD link):
        this subscriber used to take a fresh ``ObdDatabase.connect()`` for every
        single row. Nothing else held a connection, so **every close was the
        LAST close** -- which makes SQLite checkpoint the entire database and
        unlink the WAL. Against a 2.9 GB file that turned ~3.7 KB/s of EDR rows
        into ~3.4 MB/s of physical SD writes (~900x, ~85 fdatasync/s, ~294
        GB/day). Holding one connection open cut total machine I/O 9x.

        The connection is thread-local because a ``sqlite3`` connection is bound
        to the thread that created it: the drain thread owns one, and a caller
        that writes directly (tests, or ``flushPending()`` after the join) owns
        its own. Each thread only ever touches its own.

        Rows are still committed one at a time -- see ``_writeImuRow``. The EDR
        is a black box, so buffering rows to batch them would trade away the
        durability this subsystem exists to provide.
        """
        conn = getattr(self._tls, "conn", None)
        if conn is None:
            cm = self._database.connect()
            conn = cm.__enter__()
            self._tls.cm = cm
            self._tls.conn = conn
        return conn

    def closeWriteConnection(self) -> None:
        """Commit and close this thread's write connection, if it opened one.

        Safe to call on a thread that never wrote, and safe to call twice.
        """
        cm = getattr(self._tls, "cm", None)
        self._tls.cm = None
        self._tls.conn = None
        if cm is None:
            return
        try:
            cm.__exit__(None, None, None)
        except Exception as e:  # noqa: BLE001 -- closing must never raise at shutdown
            logger.warning("EDR write connection close failed: %s", e)

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
        # ARCH-030: release THIS thread's write connection. The drain thread
        # closes its own in _loop's finally -- a sqlite3 connection may only be
        # closed by the thread that opened it.
        self.closeWriteConnection()

    def _loop(self) -> None:
        """Drain samples until stopped; purge on cadence (subscriber isolation)."""
        if self._sub is None:
            return
        try:
            while not self._stop.is_set():
                sample = self._sub.get(timeoutS=_DRAIN_TIMEOUT_S)
                if sample is not None:
                    try:
                        self.handleSample(sample)
                    except Exception as e:  # noqa: BLE001 -- never crash the loop
                        logger.warning("EDR handleSample failed: %s", e)
                self.maybePurge()
        finally:
            # ARCH-030: this thread owns its write connection and is the only
            # thread allowed to close it.
            self.closeWriteConnection()

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
        # US-767-b: every row goes through the log gate when one is wired. The
        # drive_id is resolved at CAPTURE, so a pre-roll row flushed later keeps
        # the attribution it had when it was read.
        row = (buf, driveId)
        if self._logGate is None:
            toWrite = [(table, row)]
        else:
            toWrite = self._logGate.admit(table, row)
            self._publishGateState(self._logGate)
        for rowTable, (rowBuf, rowDriveId) in toWrite:
            try:
                if rowTable == "imu":
                    self._writeImuRow(rowBuf, rowDriveId)
                else:
                    self._writeLightRow(rowBuf, rowDriveId)
            except Exception as e:  # noqa: BLE001 -- a bad write never crashes the drain
                logger.warning(
                    "EDR %s row write failed (seq=%s): %s", rowTable, rowBuf.get("seq"), e
                )

    def _publishGateState(self, gate: EdrLogGate) -> None:
        """Publish the gate's state when it differs from the last published one.

        US-767-c. The first admit always publishes, so a gate that never leaves
        CLOSED (parked, no link) is still visible. The emitter is best-effort
        and a failure here must never cost the row being written.
        """
        if self._gateStateEmitFn is None or gate.state == self._publishedGateState:
            return
        try:
            self._gateStateEmitFn(gate)
            self._publishedGateState = gate.state
        except Exception as e:  # noqa: BLE001 -- publishing never costs a row
            logger.warning("EDR log gate state publish failed: %s", e)

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
        # ARCH-030: reused connection, still committed per row (black-box durability).
        conn = self._writeConn()
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
        conn.commit()

    def _writeLightRow(self, buf: dict[str, Any], driveId: int | None) -> None:
        fields = buf["fields"]
        lux = _scalar(fields.get("lux"))  # None when saturated -> NULL, never inf
        visible, infrared, full = _xyzInt(fields.get("raw"))
        # ARCH-009: the range context this reading was taken under. Absent is
        # NULL -- an honest gap. The context is diagnostic and its absence must
        # never cost us the READING.
        rng = fields.get("range") or (None, None)
        gain = _gainLabel(rng[0] if len(rng) > 0 else None)
        integrationMs = rng[1] if len(rng) > 1 and isinstance(rng[1], int) else None
        # ARCH-030: reused connection, still committed per row (black-box durability).
        conn = self._writeConn()
        conn.execute(
            "INSERT INTO edr_light_sample "
            "(ts_utc, ts_capture, seq, lux, visible, infrared, full_spectrum, "
            "gain, integration_ms, drive_id, data_source, schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                buf["tsUtc"], buf["tsCapture"], buf["seq"],
                lux, visible, infrared, full,
                gain, integrationMs,
                driveId, buf["dataSource"], SCHEMA_VERSION,
            ),
        )
        conn.commit()

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
                    "EDR retention purge: deleted imu=%d light=%d (synced, older than %d days)",
                    imuDeleted, lightDeleted, self._retentionDays,
                )
        except Exception as e:  # noqa: BLE001 -- purge failure is non-fatal
            logger.warning("EDR retention purge failed: %s", e)
        return True

    def purgeExpired(self) -> tuple[int, int]:
        """Delete rows the server already has that are older than ``retentionDays``.

        US-768: this is the ONLY EDR delete. A row goes only when it is past the
        age cutoff AND its id is at or below its table's sync high-water mark --
        age alone never authorises a delete. Both marks are read before any
        delete; if either cannot be read, nothing is deleted. Below
        :data:`_LOW_DISK_WARN_BYTES` free the purge WARNS and deletes exactly
        what it would otherwise: a disk-space emergency never widens the delete
        to unsynced rows. (US-762's whole-disk guard is a separate mechanism.)

        Returns:
            (imuRowsDeleted, lightRowsDeleted).
        """
        cutoff = (self._nowUtcFn() - timedelta(days=self._retentionDays)).strftime(
            CANONICAL_ISO_FORMAT
        )
        self._warnIfLowDisk()
        with self._database.connect() as conn:
            try:
                imuMark = sync_log.getHighWaterMark(conn, "edr_imu_sample")[0]
                lightMark = sync_log.getHighWaterMark(conn, "edr_light_sample")[0]
            except Exception as e:  # noqa: BLE001 -- any unreadable mark deletes nothing
                logger.warning(
                    "EDR retention purge: sync high-water mark unreadable (%s) -- "
                    "deleting nothing", e,
                )
                return (0, 0)
            imuDeleted = conn.execute(
                "DELETE FROM edr_imu_sample WHERE ts_utc < ? AND id <= ?", (cutoff, imuMark)
            ).rowcount
            lightDeleted = conn.execute(
                "DELETE FROM edr_light_sample WHERE ts_utc < ? AND id <= ?", (cutoff, lightMark)
            ).rowcount
        return (imuDeleted, lightDeleted)

    def _freeDiskBytes(self) -> int:
        """Free bytes on the volume that holds the database file."""
        dbDir = os.path.dirname(os.path.abspath(self._database.dbPath))
        return shutil.disk_usage(dbDir).free

    def _warnIfLowDisk(self) -> None:
        """WARN when free space is below the floor. Never changes what is deleted."""
        try:
            freeBytes = self._freeDiskBytesFn()
        except Exception as e:  # noqa: BLE001 -- the warning is advisory only
            logger.warning("EDR retention purge: free disk space unreadable (%s)", e)
            return
        if freeBytes < _LOW_DISK_WARN_BYTES:
            logger.warning(
                "EDR retention purge: free disk %.2f GB is below the %d GB floor -- "
                "deleting only rows the server already has; unsynced EDR rows are kept",
                freeBytes / _BYTES_PER_GB, _LOW_DISK_WARN_GB,
            )

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
    logGate: EdrLogGate | None = None,
    gateStateEmitFn: Callable[[EdrLogGate], None] | None = None,
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
        logGate: Optional EdrLogGate handed to the subscriber (US-767-b).
            Absent -> every row is written.
        gateStateEmitFn: Optional gate-state publisher (US-767-c), e.g. from
            :func:`makeEdrLogGateStateEmitter`.

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
        logGate=logGate,
        gateStateEmitFn=gateStateEmitFn,
    )


def buildEdrLogGateState(gate: EdrLogGate, *, nowIso: str) -> dict[str, Any]:
    """Build the states/edr-log-gate payload (pure, US-767-c).

    States are written upper-case (``CLOSED`` / ``OPEN`` / ``HOLD``), the same
    words the gate's transition log line uses.

    Args:
        gate: The gate whose current state is published.
        nowIso: ISO-8601 emission timestamp (the freshness marker).

    Returns:
        ``{"state", "enabled", "from", "reason", "bufferedRows", "ts"}``;
        ``from`` / ``reason`` are None before the gate's first transition.
    """
    last = gate.lastTransition
    return {
        "state": gate.state.upper(),
        "enabled": gate.enabled,
        "from": last[0].upper() if last is not None else None,
        "reason": last[2] if last is not None else None,
        "bufferedRows": gate.bufferedRows,
        "ts": nowIso,
    }


def makeEdrLogGateStateEmitter(
    statesDir: str,
    *,
    nowIsoFn: Callable[[], str] | None = None,
) -> Callable[[EdrLogGate], None]:
    """Build the states/edr-log-gate emit callable (US-767-c).

    Args:
        statesDir: tmpfs states directory (e.g. ``/run/eclipse-obd/states``).
        nowIsoFn: Injected clock for ``ts`` (default UTC now, second resolution).

    Returns:
        A callable taking the gate and writing its state atomically.
        Best-effort by contract: write failures are logged, never raised, so
        publishing can never cost an EDR row.
    """
    from pi.splash.boot_state_emitter import ensureStatesDir, writeStateAtomic

    nowFn = nowIsoFn or (lambda: datetime.now(UTC).strftime(_ISO_FMT))
    target = os.path.join(statesDir, EDR_LOG_GATE_STATE_FILENAME)

    def emit(gate: EdrLogGate) -> None:
        try:
            ensureStatesDir(statesDir)
            writeStateAtomic(target, buildEdrLogGateState(gate, nowIso=nowFn()))
        except Exception as e:  # noqa: BLE001 -- never cost an EDR row
            logger.error("states/edr-log-gate write failed (%s) -- ignored", e)

    return emit
