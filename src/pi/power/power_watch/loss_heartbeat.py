################################################################################
# File Name: loss_heartbeat.py
# Purpose/Description: US-748 -- the instrument that turns TIME-TO-DEATH after a
#   power loss into a NUMBER read from SQLite on the next boot.
#
#   WHY THIS EXISTS. On 2026-09-14 two deliberate cuts (16:04:44Z, 16:40:03Z)
#   left: power_log transition_to_battery WRITTEN, a drain row OPENED at 4.18 V /
#   3.95 V, that row REAPED before its first 30 s checkpoint, no CLEAN_COMPLETE,
#   and a journal whose last persisted line PREDATES the transition by 5-18 s.
#   The journal cannot see the last seconds (page-cache tail lost, A-22), so
#   "how long did the machine live after the loss" was an inference -- "under
#   30 s" -- bounded only by a checkpoint that did not land.
#
#   THE SHAPE (Atlas, Sprint 86 gate 2026-09-14 section 1; his 2026-09-06 A-22
#   recommendation): from the moment of PLD loss, write a DURABLE 1 Hz row
#   (VCELL + monotonic elapsed) for 60 s. The last row that survives IS the
#   floor on time-to-death, with no car and no human needed to read it.
#
#   DESIGN NOTES
#   - Owned by powerwatch: it owns GPIO6 (US-668), so it knows the loss instant
#     first, and it already holds the UpsMonitor.
#   - Runs on its OWN daemon thread. start() returns immediately; nothing here
#     may delay the shutdown sequence it is observing.
#   - Durable per row: PRAGMA synchronous = FULL + a commit per row (the US-267
#     logShutdownStage chain). A buffered row is exactly the row a hard cut loses.
#   - Elapsed time is MONOTONIC, never wall clock: US-620 measured this Pi
#     booting at 1970 and stepping hours forward when NTP lands.
#   - Honest-NA: an unreadable gauge writes NULL VCELL, an unreadable PLD writes
#     NULL power_lost. A row is still written -- the row's EXISTENCE is the
#     measurement; the gauge is secondary.
#   - Never creates the database. A missing db is not a deployed system.
#   - Pi-LOCAL, NOT synced: absent from sync_log.IN_SCOPE_TABLES, and
#     deliberately outside ALL_SCHEMAS so it adds no Pi-only drift to the
#     server-parity gate (TD-039). It is a forensic record for the next boot.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Rex (US-748) | Initial -- 1 Hz durable power-loss heartbeat +
#                                the next-boot time-to-death reader.
# ================================================================================
################################################################################

"""Durable 1 Hz heartbeat after a PLD power loss, and its next-boot reader."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.common.time.helper import utcIsoNow

logger = logging.getLogger(__name__)

__all__ = [
    'HEARTBEAT_DURATION_SEC',
    'HEARTBEAT_INTERVAL_SEC',
    'LOSS_HEARTBEAT_TABLE',
    'SCHEMA_POWER_LOSS_HEARTBEAT',
    'LossHeartbeatSummary',
    'PowerLossHeartbeat',
    'ensureLossHeartbeatTable',
    'readLatestLossHeartbeat',
]

# ================================================================================
# Constants
# ================================================================================

LOSS_HEARTBEAT_TABLE: str = 'power_loss_heartbeat'

#: Seconds between heartbeat rows.
#:
#: GROUNDING: Atlas, Sprint 86 design gate (pm/inbox 2026-09-14 "GATE sprint86",
#: section 1): "a durable 1 Hz heartbeat row (VCELL + monotonic time)". It is the
#: resolution of the answer: time-to-death is known to within one interval.
#: Deliberately NOT a config key -- same reasoning as the US-605 checkpoint
#: cadence: a grounded number that is somebody else's to set.
HEARTBEAT_INTERVAL_SEC: float = 1.0

#: How long the heartbeat runs after the loss.
#:
#: GROUNDING: the same Atlas gate, "into SQLite for 60 s". It comfortably
#: covers the designed time-to-poweroff (smoothingSec 7 + perTaskTimeoutSec 20,
#: capped by totalWindowCapSec 45) and the observed < 30 s death, while
#: bounding the rows a single event can add.
HEARTBEAT_DURATION_SEC: float = 60.0

SCHEMA_POWER_LOSS_HEARTBEAT: str = f"""
CREATE TABLE IF NOT EXISTS {LOSS_HEARTBEAT_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- The loss EVENT key: UTC instant the PLD loss was observed.  Every row of
    -- one event carries the same value; the next boot groups on it.
    loss_started_utc TEXT NOT NULL,

    -- 0-based row number within the event.
    seq INTEGER NOT NULL,

    -- MONOTONIC seconds since the loss was observed.  The last surviving row's
    -- value is the floor on time-to-death.  Never derived from wall clock.
    elapsed_s REAL NOT NULL,

    -- MAX17048 VCELL volts at this row; NULL when the gauge could not be read.
    vcell_v REAL,

    -- PLD read at this row: 1 lost, 0 present (power returned), NULL unknown.
    power_lost INTEGER,

    -- Wall-clock write time (canonical ISO-8601 UTC).  Context only.
    recorded_at TEXT NOT NULL
);
"""

_INSERT_SQL: str = (
    f"INSERT INTO {LOSS_HEARTBEAT_TABLE} "
    "(loss_started_utc, seq, elapsed_s, vcell_v, power_lost, recorded_at) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)

_SELECT_LATEST_SQL: str = (
    f"SELECT loss_started_utc, COUNT(*), MAX(elapsed_s), "
    f"MIN(vcell_v), SUM(CASE WHEN power_lost = 0 THEN 1 ELSE 0 END) "
    f"FROM {LOSS_HEARTBEAT_TABLE} "
    f"WHERE loss_started_utc = ("
    f"SELECT loss_started_utc FROM {LOSS_HEARTBEAT_TABLE} ORDER BY id DESC LIMIT 1"
    f") GROUP BY loss_started_utc"
)


def ensureLossHeartbeatTable(conn: sqlite3.Connection) -> None:
    """Create the heartbeat table if absent (idempotent).

    Args:
        conn: Open sqlite3 connection; the caller owns commit semantics.
    """
    conn.execute(SCHEMA_POWER_LOSS_HEARTBEAT)


# ================================================================================
# Writer
# ================================================================================


class PowerLossHeartbeat:
    """Write one durable row per interval for a bounded window after a loss.

    Every public method is total: it logs and returns rather than raising,
    because it is called from the power-loss path of a machine that may be dying.
    """

    def __init__(
        self,
        *,
        dbPath: str,
        vcellFn: Callable[[], float],
        isPowerLostFn: Callable[[], bool],
        intervalSec: float = HEARTBEAT_INTERVAL_SEC,
        durationSec: float = HEARTBEAT_DURATION_SEC,
        busyTimeoutSec: float = HEARTBEAT_INTERVAL_SEC,
        monotonicFn: Callable[[], float] | None = None,
        nowIsoFn: Callable[[], str] | None = None,
    ) -> None:
        """Args:
            dbPath: ``pi.database.path`` -- the SQLite file the rows go into.
            vcellFn: Zero-arg VCELL reader in volts (``UpsMonitor.getVcell``).
            isPowerLostFn: Zero-arg PLD reader (``PowerSourceProvider.isPowerLost``).
            intervalSec: Seconds between rows.  Default grounded, see
                :data:`HEARTBEAT_INTERVAL_SEC`; tests override.
            durationSec: Seconds the heartbeat runs.  Default grounded, see
                :data:`HEARTBEAT_DURATION_SEC`; tests override.
            busyTimeoutSec: sqlite busy timeout.  One interval: a lock held by the
                collector may cost this row its slot, never the next one.
            monotonicFn: DI monotonic clock (default :func:`time.monotonic`).
            nowIsoFn: DI canonical UTC stamp (default :func:`utcIsoNow`).
        """
        self._dbPath = dbPath
        self._vcellFn = vcellFn
        self._isPowerLostFn = isPowerLostFn
        self._intervalSec = float(intervalSec)
        self._durationSec = float(durationSec)
        self._busyTimeoutSec = float(busyTimeoutSec)
        self._monotonic = monotonicFn or time.monotonic
        self._nowIso = nowIsoFn or utcIsoNow
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def isRunning(self) -> bool:
        """Whether a heartbeat window is currently being written."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> bool:
        """Begin a heartbeat window NOW, on a daemon thread.  Never blocks.

        A second call while a window is running is ignored: one loss event, one
        series of rows.

        Returns:
            True if a new window was started.
        """
        try:
            with self._lock:
                if self.isRunning:
                    return False
                lossStartedUtc = self._nowIso()
                startMono = self._monotonic()
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._run,
                    args=(lossStartedUtc, startMono),
                    name='pw-loss-heartbeat',
                    daemon=True,
                )
                self._thread.start()
            return True
        except Exception as exc:  # noqa: BLE001 -- the loss path must not break
            logger.error("loss-heartbeat: could not start (%s) -- no rows this loss", exc)
            return False

    def stop(self, timeoutSec: float | None = None) -> None:
        """Stop the window early and wait for the thread (tests / teardown).

        Args:
            timeoutSec: Longest to wait for the writer thread.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeoutSec)

    def _run(self, lossStartedUtc: str, startMono: float) -> None:
        """Writer thread body: one committed row per interval until the window ends."""
        conn = self._openConnection()
        if conn is None:
            return
        written = 0
        seq = 0
        try:
            while True:
                elapsed = self._monotonic() - startMono
                if elapsed > self._durationSec:
                    break
                if self._writeRow(conn, lossStartedUtc, seq, elapsed):
                    written += 1
                seq += 1
                # Schedule on the loss instant, not on the previous write, so a
                # slow commit shifts one row rather than every row after it.
                nextDue = startMono + seq * self._intervalSec
                if self._stop.wait(timeout=max(0.0, nextDue - self._monotonic())):
                    break
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 -- closing is best-effort
                pass
        logger.info(
            "loss-heartbeat: window for loss at %s ended -- %d row(s) written "
            "(a machine that died mid-window never logs this line)",
            lossStartedUtc, written,
        )

    def _openConnection(self) -> sqlite3.Connection | None:
        """Open the durable write connection, or None (logged) if impossible."""
        if not Path(self._dbPath).exists():
            logger.error(
                "loss-heartbeat: database %s not found -- NOT creating one; "
                "time-to-death will not be measured for this loss", self._dbPath,
            )
            return None
        try:
            conn = sqlite3.connect(
                self._dbPath, timeout=self._busyTimeoutSec, check_same_thread=False,
            )
            # US-267 durability chain: in WAL mode FULL fsyncs the WAL on every
            # commit -- a row that is merely buffered dies with the machine.
            conn.execute("PRAGMA synchronous = FULL")
            ensureLossHeartbeatTable(conn)
            conn.commit()
            return conn
        except Exception as exc:  # noqa: BLE001 -- the loss path must not break
            logger.error(
                "loss-heartbeat: could not open %s (%s) -- time-to-death will "
                "not be measured for this loss", self._dbPath, exc,
            )
            return None

    def _writeRow(
        self, conn: sqlite3.Connection, lossStartedUtc: str, seq: int, elapsed: float,
    ) -> bool:
        """Write and commit one row.  Returns whether it landed (never raises)."""
        vcell = _readOrNone(self._vcellFn, 'VCELL')
        lost = _readOrNone(self._isPowerLostFn, 'PLD')
        try:
            conn.execute(
                _INSERT_SQL,
                (
                    lossStartedUtc,
                    int(seq),
                    round(float(elapsed), 3),
                    float(vcell) if vcell is not None else None,
                    (1 if lost else 0) if lost is not None else None,
                    self._nowIso(),
                ),
            )
            conn.commit()
            return True
        except Exception as exc:  # noqa: BLE001 -- one lost row, not a lost window
            logger.warning("loss-heartbeat: row %d not written (%s)", seq, exc)
            return False


def _readOrNone(reader: Callable[[], object], label: str) -> object | None:
    """Call a zero-arg reader, returning None if it raises."""
    try:
        return reader()
    except Exception as exc:  # noqa: BLE001 -- unreadable -> NULL, never a guess
        logger.debug("loss-heartbeat: %s read failed -> NULL (%s)", label, exc)
        return None


# ================================================================================
# Next-boot reader
# ================================================================================


@dataclass(frozen=True)
class LossHeartbeatSummary:
    """What the most recent loss event's surviving rows say.

    Attributes:
        lossStartedUtc: The event key (UTC instant the loss was observed).
        rowCount: Rows that survived.
        lastElapsedS: Elapsed seconds of the last surviving row -- the FLOOR on
            how long the machine lived after the loss.  It may understate by up
            to one interval, never overstate.
        minVcellV: Lowest VCELL any surviving row recorded, or None.
        powerReturnedRows: Rows whose PLD read said power was PRESENT again.
        windowCompleted: True when the rows reach the end of the window, i.e.
            the machine outlived the instrument and this is NOT a death time.
    """

    lossStartedUtc: str
    rowCount: int
    lastElapsedS: float
    minVcellV: float | None
    powerReturnedRows: int
    windowCompleted: bool


def readLatestLossHeartbeat(
    dbPath: str,
    *,
    intervalSec: float = HEARTBEAT_INTERVAL_SEC,
    durationSec: float = HEARTBEAT_DURATION_SEC,
) -> LossHeartbeatSummary | None:
    """Summarise the most recent loss event's heartbeat rows.  Never raises.

    Args:
        dbPath: ``pi.database.path``.
        intervalSec: The window's row interval (for ``windowCompleted``).
        durationSec: The window's duration (for ``windowCompleted``).

    Returns:
        The summary, or None when there is no database, no table, no rows, or
        the read failed (logged).
    """
    if not Path(dbPath).exists():
        return None
    try:
        conn = sqlite3.connect(dbPath, timeout=HEARTBEAT_INTERVAL_SEC)
        try:
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (LOSS_HEARTBEAT_TABLE,),
            ).fetchone()
            if exists is None:
                return None
            row = conn.execute(_SELECT_LATEST_SQL).fetchone()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 -- a boot report must not break boot
        logger.warning("loss-heartbeat: could not read %s (%s)", dbPath, exc)
        return None
    if row is None:
        return None
    lastElapsed = float(row[2])
    return LossHeartbeatSummary(
        lossStartedUtc=str(row[0]),
        rowCount=int(row[1]),
        lastElapsedS=lastElapsed,
        minVcellV=float(row[3]) if row[3] is not None else None,
        powerReturnedRows=int(row[4] or 0),
        windowCompleted=lastElapsed >= durationSec - intervalSec,
    )
