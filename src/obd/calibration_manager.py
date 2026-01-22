################################################################################
# File Name: calibration_manager.py
# Purpose/Description: Calibration mode management for OBD-II system
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-030
# ================================================================================
################################################################################

"""
Calibration mode management module.

Provides calibration mode for testing sensors, verifying OBD-II parameters,
and validating system accuracy. When enabled, logs ALL available parameters
regardless of config settings, using separate calibration session tracking.

Key features:
- Logs all OBD-II parameters when enabled (ignores logData settings)
- Creates calibration sessions with notes
- Stores calibration data linked to session_id (separate from normal data)
- Displays CALIBRATION MODE indicator prominently

Usage:
    from obd.calibration_manager import CalibrationManager

    manager = CalibrationManager(database=db, config=config)

    # Start a calibration session
    session = manager.startSession(notes="Sensor test run 1")

    # Log readings during calibration
    manager.logCalibrationReading(parameterName="RPM", value=2500, unit="rpm")

    # End the session
    manager.endSession()
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from obd.obd_parameters import (
    REALTIME_PARAMETERS,
    STATIC_PARAMETERS,
    getAllParameterNames,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Schema for calibration data table (separate from realtime_data)
SCHEMA_CALIBRATION_DATA = """
CREATE TABLE IF NOT EXISTS calibration_data (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Session association
    session_id INTEGER NOT NULL,

    -- Timestamp with millisecond precision
    timestamp DATETIME NOT NULL,

    -- Parameter data
    parameter_name TEXT NOT NULL,
    value REAL,
    unit TEXT,

    -- Raw string value for non-numeric data
    raw_value TEXT,

    -- Audit column
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT FK_calibration_data_session FOREIGN KEY (session_id)
        REFERENCES calibration_sessions(session_id)
        ON DELETE CASCADE
);
"""

# Index for efficient session queries
INDEX_CALIBRATION_DATA_SESSION = """
CREATE INDEX IF NOT EXISTS IX_calibration_data_session
    ON calibration_data(session_id);
"""

# Index for timestamp-based queries
INDEX_CALIBRATION_DATA_TIMESTAMP = """
CREATE INDEX IF NOT EXISTS IX_calibration_data_timestamp
    ON calibration_data(timestamp);
"""


# =============================================================================
# Enums and Dataclasses
# =============================================================================

class CalibrationState(Enum):
    """Calibration mode state."""

    DISABLED = "disabled"
    ENABLED = "enabled"
    SESSION_ACTIVE = "session_active"


@dataclass
class CalibrationSession:
    """Represents a calibration session."""

    sessionId: int
    startTime: datetime
    endTime: Optional[datetime] = None
    notes: Optional[str] = None
    profileId: Optional[str] = None
    readingCount: int = 0

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'sessionId': self.sessionId,
            'startTime': self.startTime.isoformat(),
            'endTime': self.endTime.isoformat() if self.endTime else None,
            'notes': self.notes,
            'profileId': self.profileId,
            'readingCount': self.readingCount,
            'durationSeconds': self.durationSeconds
        }

    @property
    def durationSeconds(self) -> Optional[float]:
        """Get session duration in seconds."""
        if self.endTime is None:
            # Session still active - calculate from now
            return (datetime.now() - self.startTime).total_seconds()
        return (self.endTime - self.startTime).total_seconds()

    @property
    def isActive(self) -> bool:
        """Check if session is still active (not ended)."""
        return self.endTime is None


@dataclass
class CalibrationReading:
    """A single calibration reading."""

    parameterName: str
    value: Optional[float]
    unit: Optional[str]
    timestamp: datetime
    sessionId: int
    rawValue: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'value': self.value,
            'unit': self.unit,
            'timestamp': self.timestamp.isoformat(),
            'sessionId': self.sessionId,
            'rawValue': self.rawValue
        }


@dataclass
class CalibrationStats:
    """Statistics for calibration manager."""

    totalSessions: int = 0
    activeSessions: int = 0
    totalReadings: int = 0
    state: CalibrationState = CalibrationState.DISABLED
    currentSessionId: Optional[int] = None


# =============================================================================
# Exceptions
# =============================================================================

class CalibrationError(Exception):
    """Base exception for calibration errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class CalibrationNotEnabledError(CalibrationError):
    """Raised when calibration operation attempted while mode disabled."""
    pass


class CalibrationSessionError(CalibrationError):
    """Raised when session operation fails."""
    pass


# =============================================================================
# CalibrationManager Class
# =============================================================================

class CalibrationManager:
    """
    Manages calibration mode for the OBD-II monitoring system.

    When calibration mode is enabled, all available OBD-II parameters are
    logged regardless of individual config settings. Data is stored in
    separate calibration tables linked to session IDs, keeping it separate
    from normal operational data.

    Attributes:
        database: ObdDatabase instance for data storage
        config: Configuration dictionary
        state: Current calibration state

    Example:
        manager = CalibrationManager(database=db, config=config)

        # Enable calibration mode
        manager.enable()

        # Start a session
        session = manager.startSession(notes="Test run #1")

        # Log readings
        manager.logCalibrationReading("RPM", 2500, "rpm")

        # End session
        manager.endSession()

        # Disable calibration mode
        manager.disable()
    """

    def __init__(
        self,
        database: Any,
        config: Optional[Dict[str, Any]] = None,
        displayManager: Optional[Any] = None
    ):
        """
        Initialize CalibrationManager.

        Args:
            database: ObdDatabase instance for data storage
            config: Optional configuration dictionary
            displayManager: Optional DisplayManager for CALIBRATION MODE indicator
        """
        self._database = database
        self._config = config or {}
        self._displayManager = displayManager
        self._state = CalibrationState.DISABLED
        self._currentSession: Optional[CalibrationSession] = None
        self._callbacks: Dict[str, List[Callable]] = {
            'session_start': [],
            'session_end': [],
            'state_change': [],
        }

        # Load config settings
        calibConfig = self._config.get('calibration', {})
        self._enabled = calibConfig.get('mode', False)
        self._logAllParameters = calibConfig.get('logAllParameters', True)
        self._sessionNotesRequired = calibConfig.get('sessionNotesRequired', False)

        # Initialize schema
        self._ensureSchema()

        # Update state based on config
        if self._enabled:
            self._state = CalibrationState.ENABLED
            logger.info("Calibration mode enabled from config")

    def _ensureSchema(self) -> None:
        """Ensure calibration_data table exists."""
        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()

                # Create calibration_data table
                cursor.execute(SCHEMA_CALIBRATION_DATA)

                # Create indexes
                cursor.execute(INDEX_CALIBRATION_DATA_SESSION)
                cursor.execute(INDEX_CALIBRATION_DATA_TIMESTAMP)

                logger.debug("Calibration schema ensured")
        except Exception as e:
            logger.error(f"Failed to ensure calibration schema: {e}")
            raise CalibrationError(
                f"Schema initialization failed: {e}",
                details={'error': str(e)}
            )

    @property
    def isEnabled(self) -> bool:
        """Check if calibration mode is enabled."""
        return self._state in (CalibrationState.ENABLED, CalibrationState.SESSION_ACTIVE)

    @property
    def state(self) -> CalibrationState:
        """Get current calibration state."""
        return self._state

    @property
    def currentSession(self) -> Optional[CalibrationSession]:
        """Get the current active session, if any."""
        return self._currentSession

    @property
    def hasActiveSession(self) -> bool:
        """Check if there is an active calibration session."""
        return self._currentSession is not None and self._currentSession.isActive

    def enable(self) -> None:
        """
        Enable calibration mode.

        When enabled, the system will log all available OBD-II parameters
        regardless of individual config settings.
        """
        if self._state == CalibrationState.SESSION_ACTIVE:
            logger.warning("Cannot change enabled state during active session")
            return

        self._enabled = True
        self._state = CalibrationState.ENABLED
        logger.info("Calibration mode enabled")

        # Show indicator on display
        if self._displayManager:
            self._showCalibrationIndicator(True)

        self._triggerCallbacks('state_change', self._state)

    def disable(self) -> None:
        """
        Disable calibration mode.

        If a session is active, it will be ended first.
        """
        # End any active session first
        if self._currentSession and self._currentSession.isActive:
            self.endSession()

        self._enabled = False
        self._state = CalibrationState.DISABLED
        logger.info("Calibration mode disabled")

        # Hide indicator on display
        if self._displayManager:
            self._showCalibrationIndicator(False)

        self._triggerCallbacks('state_change', self._state)

    def _showCalibrationIndicator(self, show: bool) -> None:
        """
        Show or hide the CALIBRATION MODE indicator on display.

        Args:
            show: True to show, False to hide
        """
        if self._displayManager is None:
            return

        try:
            # The display manager's showAlert method can be used for prominent display
            if show:
                self._displayManager.showAlert(
                    message="CALIBRATION MODE",
                    priority=2,  # High priority for visibility
                    acknowledged=True  # Don't add to active alerts list
                )
        except Exception as e:
            logger.warning(f"Failed to update calibration display indicator: {e}")

    def startSession(
        self,
        notes: Optional[str] = None,
        profileId: Optional[str] = None
    ) -> CalibrationSession:
        """
        Start a new calibration session.

        Args:
            notes: Optional notes for this session
            profileId: Optional profile ID to associate with session

        Returns:
            CalibrationSession object

        Raises:
            CalibrationNotEnabledError: If calibration mode is not enabled
            CalibrationSessionError: If session start fails
        """
        if not self.isEnabled:
            raise CalibrationNotEnabledError(
                "Cannot start session - calibration mode not enabled"
            )

        if self._sessionNotesRequired and not notes:
            raise CalibrationSessionError(
                "Session notes are required by configuration"
            )

        if self._currentSession and self._currentSession.isActive:
            raise CalibrationSessionError(
                "Cannot start new session - a session is already active"
            )

        try:
            startTime = datetime.now()

            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO calibration_sessions
                    (start_time, notes, profile_id)
                    VALUES (?, ?, ?)
                    """,
                    (startTime, notes, profileId)
                )
                sessionId = cursor.lastrowid

            self._currentSession = CalibrationSession(
                sessionId=sessionId,
                startTime=startTime,
                notes=notes,
                profileId=profileId
            )
            self._state = CalibrationState.SESSION_ACTIVE

            logger.info(f"Calibration session {sessionId} started")
            self._triggerCallbacks('session_start', self._currentSession)

            return self._currentSession

        except Exception as e:
            raise CalibrationSessionError(
                f"Failed to start session: {e}",
                details={'error': str(e)}
            )

    def endSession(self) -> Optional[CalibrationSession]:
        """
        End the current calibration session.

        Returns:
            The ended CalibrationSession, or None if no active session

        Raises:
            CalibrationSessionError: If session end fails
        """
        if self._currentSession is None or not self._currentSession.isActive:
            logger.warning("No active session to end")
            return None

        try:
            endTime = datetime.now()
            sessionId = self._currentSession.sessionId

            # Update session in database
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE calibration_sessions
                    SET end_time = ?
                    WHERE session_id = ?
                    """,
                    (endTime, sessionId)
                )

                # Get reading count
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM calibration_data
                    WHERE session_id = ?
                    """,
                    (sessionId,)
                )
                readingCount = cursor.fetchone()[0]

            self._currentSession.endTime = endTime
            self._currentSession.readingCount = readingCount

            endedSession = self._currentSession
            self._currentSession = None
            self._state = CalibrationState.ENABLED

            logger.info(
                f"Calibration session {sessionId} ended "
                f"(duration={endedSession.durationSeconds:.1f}s, "
                f"readings={readingCount})"
            )

            self._triggerCallbacks('session_end', endedSession)
            return endedSession

        except Exception as e:
            raise CalibrationSessionError(
                f"Failed to end session: {e}",
                details={'error': str(e)}
            )

    def logCalibrationReading(
        self,
        parameterName: str,
        value: Optional[float],
        unit: Optional[str] = None,
        rawValue: Optional[str] = None,
        timestamp: Optional[datetime] = None
    ) -> CalibrationReading:
        """
        Log a calibration reading.

        Args:
            parameterName: Name of the OBD-II parameter
            value: Numeric value (may be None for non-numeric)
            unit: Unit of measurement
            rawValue: Raw string value for non-numeric data
            timestamp: Optional timestamp (defaults to now)

        Returns:
            CalibrationReading object

        Raises:
            CalibrationSessionError: If no active session
        """
        if self._currentSession is None or not self._currentSession.isActive:
            raise CalibrationSessionError(
                "Cannot log reading - no active calibration session"
            )

        readingTime = timestamp or datetime.now()

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO calibration_data
                    (session_id, timestamp, parameter_name, value, unit, raw_value)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._currentSession.sessionId,
                        readingTime,
                        parameterName,
                        value,
                        unit,
                        rawValue
                    )
                )

            reading = CalibrationReading(
                parameterName=parameterName,
                value=value,
                unit=unit,
                timestamp=readingTime,
                sessionId=self._currentSession.sessionId,
                rawValue=rawValue
            )

            logger.debug(
                f"Calibration reading: {parameterName}={value} {unit or ''}"
            )
            return reading

        except Exception as e:
            logger.error(f"Failed to log calibration reading: {e}")
            raise CalibrationSessionError(
                f"Failed to log reading: {e}",
                details={'parameter': parameterName, 'error': str(e)}
            )

    def getParametersToLog(self) -> List[str]:
        """
        Get list of parameters to log during calibration.

        When logAllParameters is True (default), returns ALL available
        OBD-II parameters. Otherwise returns only configured parameters.

        Returns:
            List of parameter names to log
        """
        if self._logAllParameters:
            return getAllParameterNames()

        # Use configured parameters
        realtimeConfig = self._config.get('realtimeData', {})
        params = realtimeConfig.get('parameters', [])
        return [
            p.get('name', p) if isinstance(p, dict) else p
            for p in params
        ]

    def getSession(self, sessionId: int) -> Optional[CalibrationSession]:
        """
        Get a calibration session by ID.

        Args:
            sessionId: Session ID to retrieve

        Returns:
            CalibrationSession or None if not found
        """
        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT session_id, start_time, end_time, notes, profile_id
                    FROM calibration_sessions
                    WHERE session_id = ?
                    """,
                    (sessionId,)
                )
                row = cursor.fetchone()

                if row is None:
                    return None

                # Get reading count
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM calibration_data
                    WHERE session_id = ?
                    """,
                    (sessionId,)
                )
                readingCount = cursor.fetchone()[0]

                return CalibrationSession(
                    sessionId=row['session_id'],
                    startTime=datetime.fromisoformat(row['start_time'])
                    if isinstance(row['start_time'], str)
                    else row['start_time'],
                    endTime=datetime.fromisoformat(row['end_time'])
                    if row['end_time'] and isinstance(row['end_time'], str)
                    else row['end_time'],
                    notes=row['notes'],
                    profileId=row['profile_id'],
                    readingCount=readingCount
                )
        except Exception as e:
            logger.error(f"Failed to get session {sessionId}: {e}")
            return None

    def listSessions(
        self,
        limit: int = 100,
        includeActive: bool = True
    ) -> List[CalibrationSession]:
        """
        List calibration sessions.

        Args:
            limit: Maximum number of sessions to return
            includeActive: Include sessions without end_time

        Returns:
            List of CalibrationSession objects, newest first
        """
        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()

                query = """
                    SELECT session_id, start_time, end_time, notes, profile_id
                    FROM calibration_sessions
                """
                if not includeActive:
                    query += " WHERE end_time IS NOT NULL"
                query += " ORDER BY start_time DESC LIMIT ?"

                cursor.execute(query, (limit,))
                rows = cursor.fetchall()

                sessions = []
                for row in rows:
                    # Get reading count for each session
                    cursor.execute(
                        "SELECT COUNT(*) FROM calibration_data WHERE session_id = ?",
                        (row['session_id'],)
                    )
                    readingCount = cursor.fetchone()[0]

                    sessions.append(CalibrationSession(
                        sessionId=row['session_id'],
                        startTime=datetime.fromisoformat(row['start_time'])
                        if isinstance(row['start_time'], str)
                        else row['start_time'],
                        endTime=datetime.fromisoformat(row['end_time'])
                        if row['end_time'] and isinstance(row['end_time'], str)
                        else row['end_time'],
                        notes=row['notes'],
                        profileId=row['profile_id'],
                        readingCount=readingCount
                    ))

                return sessions

        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            return []

    def getSessionReadings(
        self,
        sessionId: int,
        parameterName: Optional[str] = None,
        limit: int = 10000
    ) -> List[CalibrationReading]:
        """
        Get readings for a calibration session.

        Args:
            sessionId: Session ID to retrieve readings for
            parameterName: Optional filter by parameter name
            limit: Maximum number of readings to return

        Returns:
            List of CalibrationReading objects
        """
        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()

                query = """
                    SELECT parameter_name, value, unit, timestamp, raw_value
                    FROM calibration_data
                    WHERE session_id = ?
                """
                params: List[Any] = [sessionId]

                if parameterName:
                    query += " AND parameter_name = ?"
                    params.append(parameterName)

                query += " ORDER BY timestamp ASC LIMIT ?"
                params.append(limit)

                cursor.execute(query, params)
                rows = cursor.fetchall()

                return [
                    CalibrationReading(
                        parameterName=row['parameter_name'],
                        value=row['value'],
                        unit=row['unit'],
                        timestamp=datetime.fromisoformat(row['timestamp'])
                        if isinstance(row['timestamp'], str)
                        else row['timestamp'],
                        sessionId=sessionId,
                        rawValue=row['raw_value']
                    )
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"Failed to get readings for session {sessionId}: {e}")
            return []

    def getStats(self) -> CalibrationStats:
        """
        Get calibration statistics.

        Returns:
            CalibrationStats object
        """
        stats = CalibrationStats(
            state=self._state,
            currentSessionId=self._currentSession.sessionId
            if self._currentSession
            else None
        )

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()

                # Total sessions
                cursor.execute(
                    "SELECT COUNT(*) FROM calibration_sessions"
                )
                stats.totalSessions = cursor.fetchone()[0]

                # Active sessions
                cursor.execute(
                    "SELECT COUNT(*) FROM calibration_sessions WHERE end_time IS NULL"
                )
                stats.activeSessions = cursor.fetchone()[0]

                # Total readings
                cursor.execute(
                    "SELECT COUNT(*) FROM calibration_data"
                )
                stats.totalReadings = cursor.fetchone()[0]

        except Exception as e:
            logger.error(f"Failed to get calibration stats: {e}")

        return stats

    def onSessionStart(self, callback: Callable[[CalibrationSession], None]) -> None:
        """Register callback for session start events."""
        self._callbacks['session_start'].append(callback)

    def onSessionEnd(self, callback: Callable[[CalibrationSession], None]) -> None:
        """Register callback for session end events."""
        self._callbacks['session_end'].append(callback)

    def onStateChange(self, callback: Callable[[CalibrationState], None]) -> None:
        """Register callback for state change events."""
        self._callbacks['state_change'].append(callback)

    def _triggerCallbacks(self, eventType: str, data: Any) -> None:
        """Trigger callbacks for an event type."""
        for callback in self._callbacks.get(eventType, []):
            try:
                callback(data)
            except Exception as e:
                logger.error(f"Callback error for {eventType}: {e}")


# =============================================================================
# Helper Functions
# =============================================================================

def createCalibrationManagerFromConfig(
    database: Any,
    config: Dict[str, Any],
    displayManager: Optional[Any] = None
) -> CalibrationManager:
    """
    Create a CalibrationManager from configuration.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary
        displayManager: Optional DisplayManager for indicator

    Returns:
        Configured CalibrationManager instance
    """
    return CalibrationManager(
        database=database,
        config=config,
        displayManager=displayManager
    )


def isCalibrationModeEnabled(config: Dict[str, Any]) -> bool:
    """
    Check if calibration mode is enabled in config.

    Args:
        config: Configuration dictionary

    Returns:
        True if calibration mode is enabled
    """
    return config.get('calibration', {}).get('mode', False)


def getCalibrationConfig(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get calibration configuration section.

    Args:
        config: Configuration dictionary

    Returns:
        Calibration config section with defaults
    """
    calibConfig = config.get('calibration', {})
    return {
        'mode': calibConfig.get('mode', False),
        'logAllParameters': calibConfig.get('logAllParameters', True),
        'sessionNotesRequired': calibConfig.get('sessionNotesRequired', False)
    }
