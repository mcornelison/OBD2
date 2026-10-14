################################################################################
# File Name: replay_source.py
# Purpose/Description: Replay value source -- answers getValue from a recorded
#                      drive's realtime_data rows on the drive's own timing
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-857) | Initial implementation (F-162 replay)
# ================================================================================
################################################################################

"""
Replay value source for the ``--simulate`` seam (US-857 / F-162).

UI work should not need the car running.  :class:`ReplayValueSource` stands in
for :class:`SensorSimulator` inside :class:`SimulatedObdConnection`: it reads a
recorded drive's ``realtime_data`` rows from a SOURCE database and answers
``getValue(name)`` with the value that PID had at the same point of the
recorded drive.  Everything downstream (orchestrator, logger, gear, card
emitters, state files) runs for real on those values.

Timing:
    The replay clock starts at :meth:`startEngine`.  At wall-clock offset
    ``now - start`` the source serves, per PID, the most recent row at or
    before ``firstTimestamp + offset``.  Before a PID's first row it returns
    ``None`` -- never 0 (``None`` means "not read").  Timing comes from the
    clock alone: nothing in the orchestrator calls ``update()``, so it is a
    no-op here.

End:
    The replay ends once the drive's last row (``ORDER BY timestamp, id``) has
    been served; ``getValue`` then returns ``None`` for every PID.

Usage:
    source = ReplayValueSource('/tmp/obd-copy.db', driveId=117)
    conn = SimulatedObdConnection(simulator=source)
"""

import bisect
import logging
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .vehicle_profile import VehicleProfile, getDefaultProfile

logger = logging.getLogger(__name__)

# The source database is opened through a read-only URI so the replay can
# never write the recorded drive.
_READ_ONLY_URI = "file:{path}?mode=ro"

_DRIVE_ROWS_SQL = (
    "SELECT timestamp, parameter_name, value FROM realtime_data "
    "WHERE drive_id = ? ORDER BY timestamp, id"
)


class ReplaySourceError(ValueError):
    """A replay cannot run: its source is missing, empty, or is the run's own database."""


def _toEpochSeconds(timestamp: str) -> float:
    """Parse a realtime_data timestamp (canonical ISO UTC; naive read as UTC)."""
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


class ReplayValueSource:
    """Serves a recorded drive's OBD values on the drive's original timing.

    Provides the five members :class:`SimulatedObdConnection` uses:
    ``profile``, ``startEngine``, ``stopEngine``, ``update`` and ``getValue``.

    Attributes:
        profile: Vehicle profile answering VIN queries (the default profile;
            a recorded drive carries no profile of its own).
        sourcePath: The database the drive is read from.
        driveId: The replayed drive.
    """

    def __init__(
        self,
        sourcePath: str,
        driveId: int,
        clock: Callable[[], float] = time.monotonic,
        profile: VehicleProfile | None = None,
    ) -> None:
        """
        Load the drive's rows from the source database.

        Args:
            sourcePath: Path of the database holding the recorded drive.
            driveId: drive_id of the drive to replay.
            clock: Monotonic seconds source; injectable for tests.
            profile: Vehicle profile for VIN queries (default profile if None).

        Raises:
            ReplaySourceError: If the source file is missing or unreadable, or
                holds no realtime_data rows for ``driveId``.
        """
        self.profile = profile or getDefaultProfile()
        self.sourcePath = sourcePath
        self.driveId = driveId
        self._clock = clock
        self._startedAt: float | None = None
        self._running = False
        self._finished = False

        rows = self._loadRows(sourcePath, driveId)
        self._firstTs = _toEpochSeconds(rows[0][0])

        # Per PID: offsets (seconds into the drive) and values, both in row order.
        self._offsets: dict[str, list[float]] = {}
        self._values: dict[str, list[float]] = {}
        for timestamp, name, value in rows:
            key = name.upper()
            self._offsets.setdefault(key, []).append(
                _toEpochSeconds(timestamp) - self._firstTs
            )
            self._values.setdefault(key, []).append(float(value))

        lastName = rows[-1][1].upper()
        self._lastRow = (lastName, len(self._offsets[lastName]) - 1)

        logger.info(
            "Replay source loaded | sourcePath=%s | drive_id=%s | rows=%d | "
            "pids=%d | duration=%.1fs",
            sourcePath, driveId, len(rows), len(self._offsets),
            self._offsets[lastName][-1],
        )

    @staticmethod
    def _loadRows(sourcePath: str, driveId: int) -> list[tuple[str, str, float]]:
        if not Path(sourcePath).is_file():
            raise ReplaySourceError(
                f"pi.replay.sourcePath {sourcePath!r} is not a file"
            )
        uri = _READ_ONLY_URI.format(path=Path(sourcePath).resolve().as_posix())
        try:
            conn = sqlite3.connect(uri, uri=True)
            try:
                rows = conn.execute(_DRIVE_ROWS_SQL, (driveId,)).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as e:
            raise ReplaySourceError(
                f"pi.replay.sourcePath {sourcePath!r} cannot be read: {e}"
            ) from e
        if not rows:
            raise ReplaySourceError(
                f"pi.replay.sourcePath {sourcePath!r} holds no realtime_data "
                f"rows for drive_id {driveId}"
            )
        return rows

    def startEngine(self) -> bool:
        """Start (or resume) the replay.

        The first start fixes the replay's time zero.  A later start after
        :meth:`stopEngine` (a reconnect) resumes on the same wall-clock
        timeline rather than rewinding the drive.

        Returns:
            True (a loaded replay always starts).
        """
        if self._startedAt is None:
            self._startedAt = self._clock()
        self._running = True
        return True

    def stopEngine(self) -> None:
        """Pause serving: getValue returns None until the next startEngine."""
        self._running = False

    def update(self, deltaSeconds: float) -> None:
        """No-op: replay timing comes from the clock, not from update calls.

        Args:
            deltaSeconds: Ignored.
        """
        return None

    def isFinished(self) -> bool:
        """True once the drive's last row has been served."""
        return self._finished

    def getValue(self, parameterName: str) -> float | None:
        """Return the PID's recorded value at the current replay offset.

        Args:
            parameterName: OBD parameter name (case-insensitive).

        Returns:
            The value of the PID's most recent row at or before the offset;
            None before the replay starts, while stopped, before the PID's
            first row, for a PID the drive never recorded, and after the end.
        """
        if not self._running or self._finished or self._startedAt is None:
            return None
        key = parameterName.upper()
        offsets = self._offsets.get(key)
        if offsets is None:
            return None
        offset = self._clock() - self._startedAt
        index = bisect.bisect_right(offsets, offset) - 1
        if index < 0:
            return None
        if (key, index) == self._lastRow:
            self._finished = True
            logger.info(
                "Replay finished | drive_id=%s | last row served", self.driveId
            )
        return self._values[key][index]
