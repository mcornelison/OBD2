################################################################################
# File Name: data_retention.py
# Purpose/Description: Data retention policy management for OBD-II database
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-016
# ================================================================================
################################################################################

"""
Data retention policy management for the Eclipse OBD-II Performance Monitoring System.

Provides:
- Scheduled automatic deletion of old realtime data
- Configurable retention periods from config
- Statistics table preservation (kept indefinitely)
- Database vacuum after cleanup to reclaim space
- Comprehensive deletion logging

Usage:
    from obd.data_retention import DataRetentionManager, CleanupResult

    # Create manager with database and config
    manager = DataRetentionManager(database, config)

    # Run immediate cleanup
    result = manager.runCleanup()
    print(f"Deleted {result.rowsDeleted} rows")

    # Schedule daily cleanup at specific hour
    manager.scheduleCleanup()

    # Stop scheduled cleanup
    manager.stop()
"""

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ================================================================================
# Custom Exceptions
# ================================================================================

class DataRetentionError(Exception):
    """Base exception for data retention-related errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class CleanupError(DataRetentionError):
    """Error during data cleanup operation."""
    pass


class SchedulerError(DataRetentionError):
    """Error with cleanup scheduler."""
    pass


# ================================================================================
# Enums and Data Classes
# ================================================================================

class CleanupState(Enum):
    """State of the cleanup manager."""
    IDLE = 'idle'
    SCHEDULED = 'scheduled'
    RUNNING = 'running'
    COMPLETED = 'completed'
    ERROR = 'error'


@dataclass
class CleanupResult:
    """
    Result of a cleanup operation.

    Attributes:
        success: Whether cleanup completed successfully
        rowsDeleted: Number of rows deleted from realtime_data
        oldestTimestamp: Timestamp of oldest data before cleanup
        newestTimestamp: Timestamp of newest data before cleanup
        retentionDays: Retention period used
        cutoffTimestamp: Timestamp cutoff for deletion
        executionTimeMs: Time taken to execute cleanup
        vacuumPerformed: Whether database vacuum was performed
        spaceReclaimedBytes: Estimated space reclaimed (if vacuum performed)
        errorMessage: Error message if cleanup failed
    """
    success: bool
    rowsDeleted: int = 0
    oldestTimestamp: Optional[datetime] = None
    newestTimestamp: Optional[datetime] = None
    retentionDays: int = 365
    cutoffTimestamp: Optional[datetime] = None
    executionTimeMs: int = 0
    vacuumPerformed: bool = False
    spaceReclaimedBytes: int = 0
    errorMessage: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            'success': self.success,
            'rowsDeleted': self.rowsDeleted,
            'oldestTimestamp': self.oldestTimestamp.isoformat() if self.oldestTimestamp else None,
            'newestTimestamp': self.newestTimestamp.isoformat() if self.newestTimestamp else None,
            'retentionDays': self.retentionDays,
            'cutoffTimestamp': self.cutoffTimestamp.isoformat() if self.cutoffTimestamp else None,
            'executionTimeMs': self.executionTimeMs,
            'vacuumPerformed': self.vacuumPerformed,
            'spaceReclaimedBytes': self.spaceReclaimedBytes,
            'errorMessage': self.errorMessage
        }


@dataclass
class RetentionStats:
    """
    Statistics about data retention manager state.

    Attributes:
        state: Current state of the manager
        lastCleanupTime: When the last cleanup was performed
        nextScheduledCleanup: When the next cleanup is scheduled
        totalCleanups: Total number of cleanups performed
        totalRowsDeleted: Total rows deleted across all cleanups
        lastResult: Result of the most recent cleanup
    """
    state: CleanupState = CleanupState.IDLE
    lastCleanupTime: Optional[datetime] = None
    nextScheduledCleanup: Optional[datetime] = None
    totalCleanups: int = 0
    totalRowsDeleted: int = 0
    lastResult: Optional[CleanupResult] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert stats to dictionary for serialization."""
        return {
            'state': self.state.value,
            'lastCleanupTime': self.lastCleanupTime.isoformat() if self.lastCleanupTime else None,
            'nextScheduledCleanup': (
                self.nextScheduledCleanup.isoformat() if self.nextScheduledCleanup else None
            ),
            'totalCleanups': self.totalCleanups,
            'totalRowsDeleted': self.totalRowsDeleted,
            'lastResult': self.lastResult.toDict() if self.lastResult else None
        }


# ================================================================================
# Data Retention Manager
# ================================================================================

class DataRetentionManager:
    """
    Manages data retention policy for OBD-II database.

    Automatically deletes old realtime data based on configured retention period
    while preserving statistics data indefinitely.

    Attributes:
        database: ObdDatabase instance for data access
        config: Configuration dictionary with dataRetention settings
        retentionDays: Number of days to retain realtime data
        vacuumAfterCleanup: Whether to vacuum database after deletion
        cleanupHour: Hour of day (0-23) to run scheduled cleanup

    Example:
        manager = DataRetentionManager(db, config)
        manager.scheduleCleanup()  # Start daily scheduled cleanup

        # Or run immediate cleanup
        result = manager.runCleanup()
        print(f"Deleted {result.rowsDeleted} rows")
    """

    def __init__(
        self,
        database: Any,
        config: Dict[str, Any],
        onCleanupComplete: Optional[Callable[[CleanupResult], None]] = None
    ):
        """
        Initialize the DataRetentionManager.

        Args:
            database: ObdDatabase instance
            config: Configuration dictionary with dataRetention section
            onCleanupComplete: Optional callback invoked after cleanup completes
        """
        self._database = database
        self._config = config
        self._onCleanupComplete = onCleanupComplete

        # Extract retention configuration
        retentionConfig = config.get('dataRetention', {})
        self._retentionDays = retentionConfig.get('realtimeDataDays', 365)
        self._statisticsRetentionDays = retentionConfig.get('statisticsRetentionDays', -1)
        self._vacuumAfterCleanup = retentionConfig.get('vacuumAfterCleanup', True)
        self._cleanupHour = retentionConfig.get('cleanupTimeHour', 3)

        # State tracking
        self._state = CleanupState.IDLE
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._stopRequested = False

        # Statistics
        self._stats = RetentionStats()

        logger.info(
            f"DataRetentionManager initialized: "
            f"retentionDays={self._retentionDays}, "
            f"vacuumAfterCleanup={self._vacuumAfterCleanup}, "
            f"cleanupHour={self._cleanupHour}"
        )

    @property
    def state(self) -> CleanupState:
        """Get current state of the manager."""
        with self._lock:
            return self._state

    @property
    def retentionDays(self) -> int:
        """Get configured retention period in days."""
        return self._retentionDays

    @property
    def cleanupHour(self) -> int:
        """Get configured cleanup hour."""
        return self._cleanupHour

    def getStats(self) -> RetentionStats:
        """Get retention manager statistics."""
        with self._lock:
            return self._stats

    def runCleanup(self, retentionDays: Optional[int] = None) -> CleanupResult:
        """
        Run data cleanup immediately.

        Deletes realtime_data rows older than the retention period and
        optionally vacuums the database to reclaim space.

        Args:
            retentionDays: Override retention period (uses config value if None)

        Returns:
            CleanupResult with details of the operation

        Raises:
            CleanupError: If cleanup fails
        """
        startTime = datetime.now()
        retentionDays = retentionDays if retentionDays is not None else self._retentionDays

        with self._lock:
            self._state = CleanupState.RUNNING

        logger.info(f"Starting data cleanup with {retentionDays} day retention period")

        try:
            # Calculate cutoff timestamp
            cutoffTimestamp = datetime.now() - timedelta(days=retentionDays)

            # Get current data range before deletion
            dataRange = self._getDataRange()
            oldestTimestamp = dataRange.get('oldest')
            newestTimestamp = dataRange.get('newest')
            totalRowsBefore = dataRange.get('count', 0)

            # Get database file size before cleanup (for space calculation)
            sizeBefore = self._getDatabaseSize()

            # Delete old data
            rowsDeleted = self._deleteOldData(cutoffTimestamp)

            # Log deletion to connection_log
            self._logCleanupEvent(rowsDeleted, retentionDays, cutoffTimestamp)

            # Vacuum database if configured and rows were deleted
            vacuumPerformed = False
            spaceReclaimed = 0
            if self._vacuumAfterCleanup and rowsDeleted > 0:
                try:
                    self._database.vacuum()
                    vacuumPerformed = True
                    sizeAfter = self._getDatabaseSize()
                    spaceReclaimed = max(0, sizeBefore - sizeAfter)
                    logger.info(f"Database vacuumed, reclaimed {spaceReclaimed} bytes")
                except Exception as e:
                    logger.warning(f"Vacuum failed (non-critical): {e}")

            # Calculate execution time
            executionTimeMs = int((datetime.now() - startTime).total_seconds() * 1000)

            result = CleanupResult(
                success=True,
                rowsDeleted=rowsDeleted,
                oldestTimestamp=oldestTimestamp,
                newestTimestamp=newestTimestamp,
                retentionDays=retentionDays,
                cutoffTimestamp=cutoffTimestamp,
                executionTimeMs=executionTimeMs,
                vacuumPerformed=vacuumPerformed,
                spaceReclaimedBytes=spaceReclaimed
            )

            logger.info(
                f"Data cleanup completed: deleted {rowsDeleted} rows, "
                f"execution time {executionTimeMs}ms"
            )

            # Update statistics
            with self._lock:
                self._state = CleanupState.COMPLETED
                self._stats.lastCleanupTime = datetime.now()
                self._stats.totalCleanups += 1
                self._stats.totalRowsDeleted += rowsDeleted
                self._stats.lastResult = result

            # Invoke callback if set
            if self._onCleanupComplete:
                try:
                    self._onCleanupComplete(result)
                except Exception as e:
                    logger.warning(f"Cleanup callback error (non-critical): {e}")

            return result

        except Exception as e:
            executionTimeMs = int((datetime.now() - startTime).total_seconds() * 1000)
            errorMsg = f"Cleanup failed: {e}"
            logger.error(errorMsg)

            with self._lock:
                self._state = CleanupState.ERROR
                self._stats.lastResult = CleanupResult(
                    success=False,
                    retentionDays=retentionDays,
                    executionTimeMs=executionTimeMs,
                    errorMessage=str(e)
                )

            raise CleanupError(errorMsg, details={'error': str(e)})

    def _getDataRange(self) -> Dict[str, Any]:
        """
        Get the timestamp range and count of realtime data.

        Returns:
            Dictionary with 'oldest', 'newest', and 'count' keys
        """
        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT
                        MIN(timestamp) as oldest,
                        MAX(timestamp) as newest,
                        COUNT(*) as count
                    FROM realtime_data
                """)
                row = cursor.fetchone()
                if row:
                    # Handle both tuple and Row access
                    if hasattr(row, 'keys'):
                        return {
                            'oldest': row['oldest'],
                            'newest': row['newest'],
                            'count': row['count'] or 0
                        }
                    else:
                        return {
                            'oldest': row[0],
                            'newest': row[1],
                            'count': row[2] or 0
                        }
                return {'oldest': None, 'newest': None, 'count': 0}
        except Exception as e:
            logger.warning(f"Error getting data range: {e}")
            return {'oldest': None, 'newest': None, 'count': 0}

    def _getDatabaseSize(self) -> int:
        """
        Get the current database file size in bytes.

        Returns:
            File size in bytes, or 0 if unable to determine
        """
        import os
        try:
            dbPath = self._database.dbPath
            if os.path.exists(dbPath):
                return os.path.getsize(dbPath)
        except Exception:
            pass
        return 0

    def _deleteOldData(self, cutoffTimestamp: datetime) -> int:
        """
        Delete realtime data older than cutoff timestamp.

        Args:
            cutoffTimestamp: Delete rows with timestamp before this

        Returns:
            Number of rows deleted
        """
        with self._database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM realtime_data WHERE timestamp < ?",
                (cutoffTimestamp,)
            )
            rowsDeleted = cursor.rowcount
            logger.debug(f"Deleted {rowsDeleted} rows from realtime_data")
            return rowsDeleted

    def _logCleanupEvent(
        self,
        rowsDeleted: int,
        retentionDays: int,
        cutoffTimestamp: datetime
    ) -> None:
        """
        Log cleanup event to connection_log table.

        Args:
            rowsDeleted: Number of rows deleted
            retentionDays: Retention period used
            cutoffTimestamp: Cutoff timestamp for deletion
        """
        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO connection_log
                    (timestamp, event_type, mac_address, success, error_message, retry_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now(),
                    'data_cleanup',
                    None,  # mac_address not applicable
                    1,  # success
                    f"Deleted {rowsDeleted} rows older than {retentionDays} days "
                    f"(cutoff: {cutoffTimestamp.isoformat()})",
                    0
                ))
        except Exception as e:
            logger.warning(f"Failed to log cleanup event: {e}")

    def scheduleCleanup(self) -> None:
        """
        Schedule daily cleanup at the configured hour.

        Cleanup runs once per day at cleanupHour (default 3 AM).
        Call stop() to cancel scheduled cleanup.

        Raises:
            SchedulerError: If scheduling fails
        """
        with self._lock:
            if self._timer is not None:
                logger.warning("Cleanup already scheduled, canceling existing timer")
                self._timer.cancel()

            self._stopRequested = False
            self._state = CleanupState.SCHEDULED

        self._scheduleNextRun()
        logger.info(f"Scheduled daily cleanup at {self._cleanupHour:02d}:00")

    def _scheduleNextRun(self) -> None:
        """Schedule the next cleanup run."""
        if self._stopRequested:
            return

        # Calculate time until next cleanup
        now = datetime.now()
        nextRun = now.replace(hour=self._cleanupHour, minute=0, second=0, microsecond=0)

        # If already past cleanup time today, schedule for tomorrow
        if nextRun <= now:
            nextRun += timedelta(days=1)

        delaySeconds = (nextRun - now).total_seconds()

        with self._lock:
            self._stats.nextScheduledCleanup = nextRun

        logger.debug(f"Next cleanup scheduled for {nextRun} (in {delaySeconds:.0f} seconds)")

        # Create timer
        self._timer = threading.Timer(delaySeconds, self._runScheduledCleanup)
        self._timer.daemon = True
        self._timer.start()

    def _runScheduledCleanup(self) -> None:
        """Execute scheduled cleanup and reschedule next run."""
        if self._stopRequested:
            return

        try:
            self.runCleanup()
        except Exception as e:
            logger.error(f"Scheduled cleanup failed: {e}")

        # Schedule next run
        if not self._stopRequested:
            self._scheduleNextRun()

    def stop(self) -> None:
        """
        Stop scheduled cleanup.

        Cancels any pending scheduled cleanup and resets state to IDLE.
        """
        with self._lock:
            self._stopRequested = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._state = CleanupState.IDLE
            self._stats.nextScheduledCleanup = None

        logger.info("Data retention scheduler stopped")

    def isRunning(self) -> bool:
        """Check if cleanup is currently running."""
        return self.state == CleanupState.RUNNING

    def isScheduled(self) -> bool:
        """Check if cleanup is scheduled."""
        return self.state == CleanupState.SCHEDULED


# ================================================================================
# Helper Functions
# ================================================================================

def createRetentionManagerFromConfig(
    database: Any,
    config: Dict[str, Any]
) -> DataRetentionManager:
    """
    Create a DataRetentionManager from configuration.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary with dataRetention section

    Returns:
        Configured DataRetentionManager instance

    Example:
        config = loadObdConfig('obd_config.json')
        manager = createRetentionManagerFromConfig(db, config)
    """
    return DataRetentionManager(database, config)


def runImmediateCleanup(
    database: Any,
    retentionDays: int = 365,
    vacuumAfterCleanup: bool = True
) -> CleanupResult:
    """
    Run immediate data cleanup with specified parameters.

    Convenience function for one-off cleanup without creating a manager.

    Args:
        database: ObdDatabase instance
        retentionDays: Number of days to retain data
        vacuumAfterCleanup: Whether to vacuum after deletion

    Returns:
        CleanupResult with operation details

    Example:
        result = runImmediateCleanup(db, retentionDays=365)
        print(f"Deleted {result.rowsDeleted} rows")
    """
    config = {
        'dataRetention': {
            'realtimeDataDays': retentionDays,
            'vacuumAfterCleanup': vacuumAfterCleanup,
            'cleanupTimeHour': 3
        }
    }
    manager = DataRetentionManager(database, config)
    return manager.runCleanup()


def getRetentionSummary(database: Any) -> Dict[str, Any]:
    """
    Get a summary of data retention status.

    Args:
        database: ObdDatabase instance

    Returns:
        Dictionary with summary info:
        - realtimeDataCount: Number of rows in realtime_data
        - oldestTimestamp: Timestamp of oldest data
        - newestTimestamp: Timestamp of newest data
        - dataAgeDays: Age of oldest data in days
        - statisticsCount: Number of rows in statistics table

    Example:
        summary = getRetentionSummary(db)
        print(f"Oldest data is {summary['dataAgeDays']} days old")
    """
    summary = {
        'realtimeDataCount': 0,
        'oldestTimestamp': None,
        'newestTimestamp': None,
        'dataAgeDays': 0,
        'statisticsCount': 0
    }

    try:
        with database.connect() as conn:
            cursor = conn.cursor()

            # Get realtime data info
            cursor.execute("""
                SELECT
                    COUNT(*) as count,
                    MIN(timestamp) as oldest,
                    MAX(timestamp) as newest
                FROM realtime_data
            """)
            row = cursor.fetchone()
            if row:
                if hasattr(row, 'keys'):
                    summary['realtimeDataCount'] = row['count'] or 0
                    summary['oldestTimestamp'] = row['oldest']
                    summary['newestTimestamp'] = row['newest']
                else:
                    summary['realtimeDataCount'] = row[0] or 0
                    summary['oldestTimestamp'] = row[1]
                    summary['newestTimestamp'] = row[2]

                if summary['oldestTimestamp']:
                    oldest = summary['oldestTimestamp']
                    if isinstance(oldest, str):
                        oldest = datetime.fromisoformat(oldest)
                    summary['dataAgeDays'] = (datetime.now() - oldest).days

            # Get statistics count
            cursor.execute("SELECT COUNT(*) FROM statistics")
            row = cursor.fetchone()
            if row:
                summary['statisticsCount'] = row[0] or 0

    except Exception as e:
        logger.warning(f"Error getting retention summary: {e}")

    return summary
