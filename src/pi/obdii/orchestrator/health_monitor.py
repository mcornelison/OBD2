################################################################################
# File Name: health_monitor.py
# Purpose/Description: Health check and data rate tracking mixin for orchestrator
# Author: Ralph Agent
# Creation Date: 2026-04-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-14    | Ralph Agent  | Sweep 5 Task 2: extracted from orchestrator.py
# 2026-05-08    | Rex (US-302) | _performHealthCheck now renders
#               |              | data_logger_last_row_seconds_ago (Spool
#               |              | BUG-2 post-mortem signal).  Sentinel is
#               |              | the literal ``never_written`` -- explicit,
#               |              | greppable, no NULL or magic numbers.
# ================================================================================
################################################################################

"""
Health monitoring mixin for ApplicationOrchestrator.

Periodic health checks, data rate tracking, and stats collection. The main
application loop drives the schedule; this mixin supplies the behavior.
"""

import logging
from datetime import datetime
from typing import Any

from .types import HealthCheckStats

# Unified logger name matches the original monolith module so existing tests
# that filter caplog by logger name continue to work unchanged.
logger = logging.getLogger("pi.obdii.orchestrator")


class HealthMonitorMixin:
    """
    Mixin providing health check and data rate tracking.

    Assumes the composing class has:
        _healthCheckStats: HealthCheckStats
        _healthCheckInterval: float
        _startTime, _lastHealthCheckTime, _lastDataRateCheckTime,
        _lastDataRateLogTime: datetime | None
        _lastDataRateReadingCount, _lastDataRateLogCount: int
        _dataLogger, _driveDetector: components
        _checkConnectionStatus() method (from ConnectionRecoveryMixin)
    """

    _healthCheckStats: HealthCheckStats
    _healthCheckInterval: float
    _startTime: datetime | None
    _lastHealthCheckTime: datetime | None
    _lastDataRateCheckTime: datetime | None
    _lastDataRateReadingCount: int
    _lastDataRateLogTime: datetime | None
    _lastDataRateLogCount: int
    _dataLogger: Any | None
    _driveDetector: Any | None

    def _performHealthCheck(self) -> None:
        """
        Perform periodic health check and log status.

        Logs:
        - Connection status
        - Data rate (readings per minute)
        - Error count
        - Uptime
        """
        now = datetime.now()

        # Calculate data rate (readings per minute)
        if self._lastDataRateCheckTime is not None:
            elapsedMinutes = (now - self._lastDataRateCheckTime).total_seconds() / 60.0
            if elapsedMinutes > 0:
                readingsDelta = (
                    self._healthCheckStats.totalReadings - self._lastDataRateReadingCount
                )
                self._healthCheckStats.dataRatePerMinute = readingsDelta / elapsedMinutes

        # Update tracking for next calculation
        self._lastDataRateCheckTime = now
        self._lastDataRateReadingCount = self._healthCheckStats.totalReadings

        # Update connection status
        # Cross-mixin method call (ConnectionRecoveryMixin provides the method);
        # matches the type: ignore pattern used in lifecycle.py and event_router.py.
        self._healthCheckStats.connectionConnected = self._checkConnectionStatus()  # type: ignore[attr-defined]
        self._healthCheckStats.connectionStatus = (
            "connected" if self._healthCheckStats.connectionConnected else "disconnected"
        )

        # Calculate uptime
        if self._startTime is not None:
            self._healthCheckStats.uptimeSeconds = (now - self._startTime).total_seconds()

        self._healthCheckStats.lastHealthCheck = now

        # Get additional stats from components
        self._collectComponentStats()

        # US-302: pull lastRowWrittenSecondsAgo into the stats payload
        # so the toDict export and the log line below stay coherent.
        # ``never_written`` is the explicit sentinel rendered when the
        # logger has never produced a row -- preferred over None/NaN/-1
        # per the no-magic-numbers invariant.
        lastRow = self._readDataLoggerLastRowSecondsAgo()
        self._healthCheckStats.dataLoggerLastRowSecondsAgo = lastRow
        lastRowRender = (
            "never_written" if lastRow is None else f"{lastRow:.1f}"
        )

        # Log health check
        logger.info(
            f"HEALTH CHECK | "
            f"connection={self._healthCheckStats.connectionStatus} | "
            f"data_rate={self._healthCheckStats.dataRatePerMinute:.1f}/min | "
            f"readings={self._healthCheckStats.totalReadings} | "
            f"errors={self._healthCheckStats.totalErrors} | "
            f"drives={self._healthCheckStats.drivesDetected} | "
            f"alerts={self._healthCheckStats.alertsTriggered} | "
            f"uptime={self._healthCheckStats.uptimeSeconds:.0f}s | "
            f"data_logger_last_row_seconds_ago={lastRowRender}"
        )

    def _readDataLoggerLastRowSecondsAgo(self) -> float | None:
        """Read ``RealtimeDataLogger.lastRowWrittenSecondsAgo`` defensively.

        US-302: the property may not exist on older logger shapes
        (legacy mocks, future replacement) -- return ``None`` (==
        ``never_written``) on a missing attribute so the health check
        never crashes.

        US-688: the body MOVED to :meth:`_readDataLoggerRowFreshness`, which
        returns the same value plus the REASON it is None.  This wrapper is
        unchanged in behaviour and keeps the US-302 log line's contract; it
        delegates rather than re-reading so there stays exactly ONE acquisition
        of this fact (ssot-design-pattern rule B).
        """
        value, _reason = self._readDataLoggerRowFreshness()
        return value

    def _readDataLoggerRowFreshness(self) -> tuple[float | None, str | None]:
        """Read the logger's row freshness AND why it is absent (US-688).

        🔴 THE DISTINCTION THIS EXISTS TO MAKE.  US-302 collapsed three very
        different facts into one ``None``: the logger has written nothing (a
        MEASUREMENT, and the 2026-09-04 incident), there is no logger at all (an
        ABSENCE, the ordinary bench shape), and the read failed (a fault in the
        Pi).  Only the first is a capture fault.  The health-check LOG could
        blur them because a human reads it in context; an ALERT cannot, because
        alerting on the other two is how an alert gets ignored.

        Must coerce to ``float`` and validate the type because pytest MagicMock
        auto-creates attributes that lure the ``:.1f`` formatter into a
        TypeError; only a real numeric value survives the ``int|float`` filter.

        Returns:
            ``(secondsAgo, reason)``.  ``reason`` is None exactly when
            ``secondsAgo`` is a real reading, and otherwise one of
            ``capture_health``'s three read reasons.
        """
        from pi.obdii.capture_health import (
            REASON_LOGGER_ABSENT,
            REASON_UNREADABLE,
        )

        if self._dataLogger is None:
            return (None, REASON_LOGGER_ABSENT)
        try:
            value = getattr(self._dataLogger, 'lastRowWrittenSecondsAgo', None)
        except Exception as e:  # noqa: BLE001 -- defensive
            logger.debug(f"lastRowWrittenSecondsAgo read failed: {e}")
            return (None, REASON_UNREADABLE)
        if value is None:
            # US-727: the logger is there and THIS PROCESS has written nothing,
            # which is NOT the same fact as "nothing was ever written".
            # ``lastRowWrittenSecondsAgo`` is a time.monotonic() marker on the
            # logger INSTANCE, so every restart clears it -- and a Pi dead since
            # yesterday then read identically to one that booted forty seconds
            # ago. Ask the DURABLE record before concluding "never".
            return self._readDurableRowFreshness()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            # MagicMock or non-numeric stand-in -- we could not read a number.
            # NOT `never_written`: this is an unreadable instrument, and calling
            # it a capture stall would alarm on every legacy mock in the suite.
            return (None, REASON_UNREADABLE)
        return (float(value), None)

    def _readDurableRowFreshness(self) -> tuple[float | None, str | None]:
        """Age of the newest ``realtime_data`` row, or a typed absence (US-727).

        The fallback for a RESTART: the in-process marker is per-process by
        construction, the table is not. Consulted ONLY when that marker is
        absent, so a capturing process still reports its own reading and this
        never runs on the hot path.

        CHEAP AND NON-BLOCKING, which the emitter's contract requires:
        ``MAX(timestamp)`` is served by ``IX_realtime_data_timestamp`` --
        measured at 32 ms against the car's 400,755-row table (2026-09-22).

        Three outcomes, and they stay distinct:

        * a real age -> ``(seconds, None)``;
        * the table is present and EMPTY -> ``never_written``, the honest
          answer for a Pi that genuinely has not captured;
        * no database, a raising query, an uncoercible value, or a NEGATIVE age
          -> ``unreadable``. An instrument fault is never reported as a
          measurement of capture, and the age is NEVER clamped to zero: this Pi
          boots at 1970 and steps forward when NTP lands, so a row stamped in
          the future is a broken clock, not a fresh capture.

        Returns:
            ``(secondsAgo, reason)``, with ``reason`` None exactly when the
            value is a real reading.
        """
        from pi.obdii.capture_health import (
            REASON_NEVER_WRITTEN,
            REASON_UNREADABLE,
        )

        database = getattr(self, '_database', None)
        if database is None:
            return (None, REASON_UNREADABLE)
        try:
            with database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT "
                    "  CAST((julianday('now') - "
                    "        julianday(MAX(timestamp))) * 86400 AS REAL) "
                    "FROM realtime_data"
                )
                row = cursor.fetchone()
        except Exception as e:  # noqa: BLE001 -- the health check never raises
            logger.debug(f"durable row-freshness read failed: {e}")
            return (None, REASON_UNREADABLE)
        if not row or row[0] is None:
            # MAX over an empty table is NULL: nothing was ever captured.
            return (None, REASON_NEVER_WRITTEN)
        try:
            ageS = float(row[0])
        except (TypeError, ValueError):
            return (None, REASON_UNREADABLE)
        if ageS < 0:
            logger.debug(
                "durable row-freshness is negative (%.1fs): the clock is behind "
                "the newest row -- reporting unreadable", ageS,
            )
            return (None, REASON_UNREADABLE)
        return (ageS, None)

    def _collectComponentStats(self) -> None:
        """Collect additional statistics from components for health check."""
        # Get data logger stats if available
        if self._dataLogger is not None and hasattr(self._dataLogger, 'getStats'):
            try:
                loggerStats = self._dataLogger.getStats()
                if hasattr(loggerStats, 'totalLogged'):
                    self._healthCheckStats.totalReadings = loggerStats.totalLogged
                if hasattr(loggerStats, 'totalErrors'):
                    self._healthCheckStats.totalErrors = loggerStats.totalErrors
            except Exception as e:
                logger.debug(f"Could not get data logger stats: {e}")

        # Get drive detector stats if available
        if self._driveDetector is not None and hasattr(self._driveDetector, 'getStats'):
            try:
                detectorStats = self._driveDetector.getStats()
                if hasattr(detectorStats, 'drivesDetected'):
                    self._healthCheckStats.drivesDetected = detectorStats.drivesDetected
            except Exception as e:
                logger.debug(f"Could not get drive detector stats: {e}")

    def _logDataLoggingRate(self) -> None:
        """
        Log the data logging rate (records per minute).

        Called every 5 minutes (configurable) to track logging performance.
        Logs the average records/minute since last log.
        """
        now = datetime.now()

        # Calculate records per minute since last log
        if self._lastDataRateLogTime is not None:
            elapsedMinutes = (now - self._lastDataRateLogTime).total_seconds() / 60.0
            if elapsedMinutes > 0:
                readingsDelta = (
                    self._healthCheckStats.totalReadings - self._lastDataRateLogCount
                )
                recordsPerMinute = readingsDelta / elapsedMinutes

                logger.info(
                    f"DATA LOGGING RATE | "
                    f"records/min={recordsPerMinute:.1f} | "
                    f"total_logged={self._healthCheckStats.totalReadings} | "
                    f"period_minutes={elapsedMinutes:.1f}"
                )

        # Update tracking for next calculation
        self._lastDataRateLogCount = self._healthCheckStats.totalReadings

    def getHealthCheckStats(self) -> HealthCheckStats:
        """
        Get current health check statistics.

        Returns:
            HealthCheckStats with current statistics
        """
        return self._healthCheckStats

    def setHealthCheckInterval(self, intervalSeconds: float) -> None:
        """
        Update the health check interval.

        Args:
            intervalSeconds: New interval in seconds (minimum 10 seconds)

        Raises:
            ValueError: If interval is less than 10 seconds
        """
        if intervalSeconds < 10:
            raise ValueError("Health check interval must be at least 10 seconds")

        self._healthCheckInterval = intervalSeconds
        logger.info(f"Health check interval updated to {intervalSeconds}s")


__all__ = ['HealthMonitorMixin']
