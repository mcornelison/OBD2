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
logger = logging.getLogger("pi.obd.orchestrator")


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

        # Log health check
        logger.info(
            f"HEALTH CHECK | "
            f"connection={self._healthCheckStats.connectionStatus} | "
            f"data_rate={self._healthCheckStats.dataRatePerMinute:.1f}/min | "
            f"readings={self._healthCheckStats.totalReadings} | "
            f"errors={self._healthCheckStats.totalErrors} | "
            f"drives={self._healthCheckStats.drivesDetected} | "
            f"alerts={self._healthCheckStats.alertsTriggered} | "
            f"uptime={self._healthCheckStats.uptimeSeconds:.0f}s"
        )

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
