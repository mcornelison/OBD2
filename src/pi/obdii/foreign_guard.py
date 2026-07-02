################################################################################
# File Name: foreign_guard.py
# Purpose/Description: US-424 (F-116) Pi-side foreign-vehicle ingest guard.  A
#                      sustained-bus-rate check that concludes a NON-Eclipse
#                      vehicle is connected when the realtime_data row-write rate
#                      (== OBD PID query-response rate) stays above the Eclipse
#                      K-line ceiling, then retro-tags the open drive's rows
#                      data_source='foreign' so analytics auto-exclude them.
#                      SSOT for the "is this drive foreign?" fact -- the writer
#                      (ObdDataLogger.logReading) and the poll loop consult it;
#                      neither classifies on its own.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-424) | Initial -- F-116 sustained bus-rate ingest guard.
# ================================================================================
################################################################################

"""US-424 / F-116 -- Pi-side foreign-vehicle contamination ingest guard.

The OBDLink dongle is used on more than one vehicle (the Eclipse and, on drive
33, a Ford Explorer).  When it is plugged into a *different* car, that car's
telemetry lands in ``realtime_data`` tagged ``'real'`` and silently pollutes
every ``WHERE data_source='real'`` tuning query.  A dongle-MAC allowlist can't
tell the two apart (same dongle), and Mode-09 VIN is silent on the Eclipse's
ECU, so identity can't be read directly.

**The discriminator is protocol speed.**  Every poll cycle queries the same set
of ~21 PIDs and writes one ``realtime_data`` row per response, so the sustained
row-write rate equals the OBD query-response rate.  The 1998 Eclipse GST speaks
ISO 9141-2 over the K-line, whose sustained PID throughput ceiling is ~6.3
responses/sec.  A modern vehicle on CAN / ISO 15765 sustains far higher.  So a
**sustained** row rate above ~7/s (just over the Eclipse ceiling) means the
connected vehicle is not the Eclipse.

"Sustained" is structural, not a knob: the rate is the sample count over a full
rolling ``windowSeconds`` window divided by ``windowSeconds`` (NOT by the elapsed
span), so a momentary burst reads low until the window fills -- only a rate held
for ~a window trips the guard.  A legit Eclipse burst therefore never
false-flags.

On a trip the guard (a) retro-tags the open drive's already-written rows
``data_source='foreign'`` via the injected retag function, and (b) latches the
drive_id so the writer stamps every *subsequent* row ``'foreign'`` too
(``isDriveForeign``).  Rows are re-tagged, NEVER deleted -- evidence is
preserved.  Tagging IS the exclusion: the Pi sync pushes the rows, but the
server filters ``WHERE data_source='real'`` so they never enter a real-data
query (zero consumer changes).

Design: this module is the single authoritative provider (SSOT) of the "drive is
foreign" fact.  Consumers apply the verdict; they do not each measure the bus
rate.  Ships DARK -- ``pi.foreignGuard.enabled`` defaults ``False`` so the CIO
flips it on after the bench drill confirms the Eclipse never false-trips.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("eclipse-obd")

__all__ = [
    "DEFAULT_BUS_RATE_THRESHOLD_HZ",
    "DEFAULT_MEASUREMENT_WINDOW_SECONDS",
    "DEFAULT_SUSTAINED_SECONDS",
    "ForeignVehicleGuard",
    "getForeignGuard",
    "installForeignVehicleGuardFromConfig",
    "isDriveForeign",
    "makeForeignVehicleGuard",
    "makeRealtimeDataForeignRetagger",
    "observeSample",
    "resetForeignGuard",
    "setForeignGuard",
]


# Grounded defaults (US-424 AC + specs/grounded-knowledge.md OBD-II protocol
# facts).  The 1998 Eclipse GST ISO 9141-2 K-line sustained PID-response ceiling
# is ~6.3/s; 7.0 Hz sits just above it (~11% margin).
DEFAULT_BUS_RATE_THRESHOLD_HZ: float = 7.0
# The rate is estimated over a short measurement window (a stable per-second
# rate) and must stay above the threshold CONTINUOUSLY for the sustained window
# to trip.  Two timescales are what make "sustained, not instantaneous"
# structural: a burst spikes the short-window rate but decays back below the
# bar well before the sustained window elapses, so it resets the timer and never
# trips; only a genuinely sustained high rate holds the bar for the full window.
DEFAULT_SUSTAINED_SECONDS: float = 10.0
DEFAULT_MEASUREMENT_WINDOW_SECONDS: float = 3.0

# retag(driveId) -> number of rows re-tagged 'foreign'.
RetagFn = Callable[[int], int]
ClockFn = Callable[[], float]


class ForeignVehicleGuard:
    """Sustained-bus-rate foreign-vehicle detector for one Pi collector.

    Thread-safe: ``observe`` (poll-loop thread) and ``isDriveForeign`` (writer
    thread) share a lock over the rolling window + the foreign-drive latch.
    """

    def __init__(
        self,
        thresholdHz: float = DEFAULT_BUS_RATE_THRESHOLD_HZ,
        sustainedSeconds: float = DEFAULT_SUSTAINED_SECONDS,
        measurementWindowSeconds: float = DEFAULT_MEASUREMENT_WINDOW_SECONDS,
        retagFn: RetagFn | None = None,
        clock: ClockFn = time.monotonic,
    ) -> None:
        if thresholdHz <= 0:
            raise ValueError("thresholdHz must be > 0")
        if sustainedSeconds <= 0:
            raise ValueError("sustainedSeconds must be > 0")
        if measurementWindowSeconds <= 0:
            raise ValueError("measurementWindowSeconds must be > 0")
        self._thresholdHz = float(thresholdHz)
        self._sustainedSeconds = float(sustainedSeconds)
        self._measurementWindowSeconds = float(measurementWindowSeconds)
        self._retagFn = retagFn
        self._clock = clock
        self._lock = threading.Lock()
        self._activeDriveId: int | None = None
        self._aboveSince: float | None = None
        self._window: deque[float] = deque()
        self._foreignDrives: set[int] = set()

    def observe(self, driveId: int | None, now: float | None = None) -> None:
        """Record one captured sample (one realtime_data row) for ``driveId``.

        No-op when there is no open drive (``driveId is None``).  Trips the
        guard the moment the sustained windowed rate exceeds the threshold.
        """
        if driveId is None:
            return
        if now is None:
            now = self._clock()

        with self._lock:
            if driveId in self._foreignDrives:
                # Already latched foreign -- the writer tags new rows; nothing
                # more to measure for this drive.
                return
            if driveId != self._activeDriveId:
                # New drive -> its window + timer start clean (drive boundaries
                # reset the count so a prior drive's burst can't leak across).
                self._activeDriveId = driveId
                self._aboveSince = None
                self._window.clear()

            window = self._window
            window.append(now)
            cutoff = now - self._measurementWindowSeconds
            while window and window[0] < cutoff:
                window.popleft()

            # Instantaneous-ish rate over the short measurement window.
            rate = len(window) / self._measurementWindowSeconds
            if rate <= self._thresholdHz:
                # Below the bar -> reset the sustained-duration timer.  A burst
                # that decays here can never accumulate the sustained window.
                self._aboveSince = None
                return
            if self._aboveSince is None:
                self._aboveSince = now
                return
            if (now - self._aboveSince) < self._sustainedSeconds:
                # Above the bar, but not yet for long enough to call it foreign.
                return
            self._foreignDrives.add(driveId)

        # Trip actions run outside the lock (DB retag may block).
        self._onTrip(driveId, rate)

    def _onTrip(self, driveId: int, rate: float) -> None:
        logger.warning(
            "eclipse-obd | FOREIGN-VEHICLE guard TRIPPED | drive_id=%s | "
            "sustained bus rate %.1f/s > %.1f/s threshold "
            "(Eclipse K-line ceiling ~6.3/s) -- retro-tagging the drive's "
            "rows data_source='foreign' (NOT deleting; evidence preserved)",
            driveId, rate, self._thresholdHz,
        )
        if self._retagFn is None:
            return
        try:
            retagged = self._retagFn(driveId)
            logger.warning(
                "eclipse-obd | foreign retro-tag | drive_id=%s | rows=%s",
                driveId, retagged,
            )
        except Exception as exc:  # never let a retag failure kill the poll loop
            logger.error(
                "eclipse-obd | foreign retro-tag FAILED | drive_id=%s | %s",
                driveId, exc,
            )

    def isDriveForeign(self, driveId: int | None) -> bool:
        """Return True once ``driveId`` has been latched as a foreign vehicle."""
        if driveId is None:
            return False
        with self._lock:
            return driveId in self._foreignDrives


# ================================================================================
# Process-wide singleton (mirrors src/pi/obdii/drive_id.py's context pattern)
# ================================================================================

_guard: ForeignVehicleGuard | None = None
_guardLock = threading.Lock()


def setForeignGuard(guard: ForeignVehicleGuard | None) -> None:
    """Install (or clear) the process-wide foreign-vehicle guard."""
    global _guard
    with _guardLock:
        _guard = guard


def getForeignGuard() -> ForeignVehicleGuard | None:
    """Return the installed guard, or ``None`` when the guard is dark."""
    with _guardLock:
        return _guard


def resetForeignGuard() -> None:
    """Clear the installed guard (test isolation + the disabled-config path)."""
    setForeignGuard(None)


def observeSample(driveId: int | None, now: float | None = None) -> None:
    """Feed one captured sample to the guard.  No-op when the guard is dark."""
    guard = getForeignGuard()
    if guard is not None:
        guard.observe(driveId, now)


def isDriveForeign(driveId: int | None) -> bool:
    """Consult the guard for ``driveId``.  Returns False when the guard is dark."""
    guard = getForeignGuard()
    return guard.isDriveForeign(driveId) if guard is not None else False


# ================================================================================
# Factory + config install
# ================================================================================


def makeRealtimeDataForeignRetagger(database: Any) -> RetagFn:
    """Build a retag function that flips an open drive's rows to 'foreign'.

    Re-tags only rows still tagged ``'real'`` (leaves any sim/replay/fixture
    rows untouched) and NEVER deletes.  Requires the realtime_data CHECK to
    already accept ``'foreign'`` (``ensureDataSourceCheckWidened`` runs at
    :meth:`ObdDatabase.initialize`).
    """

    def retag(driveId: int) -> int:
        with database.connect() as conn:
            cursor = conn.execute(
                "UPDATE realtime_data SET data_source = 'foreign' "
                "WHERE drive_id = ? AND data_source = 'real'",
                (driveId,),
            )
            return cursor.rowcount

    return retag


def makeForeignVehicleGuard(
    config: dict[str, Any], database: Any,
) -> ForeignVehicleGuard:
    """Build a guard from the ``pi.foreignGuard.*`` config block + a DB retagger."""
    guardConfig = config.get("pi", {}).get("foreignGuard", {})
    thresholdHz = float(
        guardConfig.get("busRateThresholdHz", DEFAULT_BUS_RATE_THRESHOLD_HZ)
    )
    sustainedSeconds = float(
        guardConfig.get("sustainedSeconds", DEFAULT_SUSTAINED_SECONDS)
    )
    measurementWindowSeconds = float(
        guardConfig.get(
            "measurementWindowSeconds", DEFAULT_MEASUREMENT_WINDOW_SECONDS
        )
    )
    retagFn = (
        makeRealtimeDataForeignRetagger(database) if database is not None else None
    )
    return ForeignVehicleGuard(
        thresholdHz=thresholdHz,
        sustainedSeconds=sustainedSeconds,
        measurementWindowSeconds=measurementWindowSeconds,
        retagFn=retagFn,
    )


def installForeignVehicleGuardFromConfig(
    config: dict[str, Any], database: Any,
) -> bool:
    """Install the singleton guard iff ``pi.foreignGuard.enabled`` is true.

    Ships DARK: when disabled (the default) the guard is cleared so
    :func:`observeSample` / :func:`isDriveForeign` are cheap no-ops and the live
    write path is unchanged.

    Returns:
        ``True`` iff the guard was installed (config enabled), else ``False``.
    """
    guardConfig = config.get("pi", {}).get("foreignGuard", {})
    if not guardConfig.get("enabled", False):
        resetForeignGuard()
        return False
    setForeignGuard(makeForeignVehicleGuard(config, database))
    logger.info(
        "eclipse-obd | foreign-vehicle guard ARMED (pi.foreignGuard.enabled) "
        "| threshold=%.1f/s sustained=%.0fs",
        float(guardConfig.get("busRateThresholdHz", DEFAULT_BUS_RATE_THRESHOLD_HZ)),
        float(guardConfig.get("sustainedSeconds", DEFAULT_SUSTAINED_SECONDS)),
    )
    return True
