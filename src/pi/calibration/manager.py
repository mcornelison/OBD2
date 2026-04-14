################################################################################
# File Name: manager.py
# Purpose/Description: CalibrationManager class for calibration mode management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-014
# ================================================================================
################################################################################
"""
Calibration mode management module.

Provides CalibrationManager class for managing calibration mode, sessions,
and reading collection.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from obd.obd_parameters import getAllParameterNames

from .collector import getSessionReadings, logReading
from .exceptions import (
    CalibrationError,
    CalibrationNotEnabledError,
    CalibrationSessionError,
)
from .export import exportSession
from .session import (
    createSession,
    deleteSession,
    endSession,
    getSession,
    listSessions,
)
from .types import (
    INDEX_CALIBRATION_DATA_SESSION,
    INDEX_CALIBRATION_DATA_TIMESTAMP,
    SCHEMA_CALIBRATION_DATA,
    CalibrationExportResult,
    CalibrationReading,
    CalibrationSession,
    CalibrationState,
    CalibrationStats,
)

logger = logging.getLogger(__name__)


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
        config: dict[str, Any] | None = None,
        displayManager: Any | None = None
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
        self._currentSession: CalibrationSession | None = None
        self._callbacks: dict[str, list[Callable]] = {
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
            ) from e

    @property
    def isEnabled(self) -> bool:
        """Check if calibration mode is enabled."""
        return self._state in (CalibrationState.ENABLED, CalibrationState.SESSION_ACTIVE)

    @property
    def state(self) -> CalibrationState:
        """Get current calibration state."""
        return self._state

    @property
    def currentSession(self) -> CalibrationSession | None:
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
        notes: str | None = None,
        profileId: str | None = None
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

        self._currentSession = createSession(
            self._database,
            notes=notes,
            profileId=profileId
        )
        self._state = CalibrationState.SESSION_ACTIVE

        logger.info(f"Calibration session {self._currentSession.sessionId} started")
        self._triggerCallbacks('session_start', self._currentSession)

        return self._currentSession

    def endSession(self) -> CalibrationSession | None:
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

        endedSession = endSession(self._database, self._currentSession)
        self._currentSession = None
        self._state = CalibrationState.ENABLED

        logger.info(f"Calibration session {endedSession.sessionId} ended")
        self._triggerCallbacks('session_end', endedSession)

        return endedSession

    def logCalibrationReading(
        self,
        parameterName: str,
        value: float | None,
        unit: str | None = None,
        rawValue: str | None = None,
        timestamp: datetime | None = None
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

        return logReading(
            self._database,
            self._currentSession.sessionId,
            parameterName,
            value,
            unit=unit,
            rawValue=rawValue,
            timestamp=timestamp
        )

    def getParametersToLog(self) -> list[str]:
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

    def getSession(self, sessionId: int) -> CalibrationSession | None:
        """
        Get a calibration session by ID.

        Args:
            sessionId: Session ID to retrieve

        Returns:
            CalibrationSession or None if not found
        """
        return getSession(self._database, sessionId)

    def listSessions(
        self,
        limit: int = 100,
        includeActive: bool = True
    ) -> list[CalibrationSession]:
        """
        List calibration sessions.

        Args:
            limit: Maximum number of sessions to return
            includeActive: Include sessions without end_time

        Returns:
            List of CalibrationSession objects, newest first
        """
        return listSessions(self._database, limit, includeActive)

    def getSessionReadings(
        self,
        sessionId: int,
        parameterName: str | None = None,
        limit: int = 10000
    ) -> list[CalibrationReading]:
        """
        Get readings for a calibration session.

        Args:
            sessionId: Session ID to retrieve readings for
            parameterName: Optional filter by parameter name
            limit: Maximum number of readings to return

        Returns:
            List of CalibrationReading objects
        """
        return getSessionReadings(
            self._database,
            sessionId,
            parameterName=parameterName,
            limit=limit
        )

    def exportSession(
        self,
        sessionId: int,
        format: str = 'csv',
        exportDirectory: str = './exports/',
        filename: str | None = None
    ) -> CalibrationExportResult:
        """
        Export a calibration session to CSV or JSON file.

        Args:
            sessionId: ID of the session to export
            format: Export format ('csv' or 'json')
            exportDirectory: Directory to save export file
            filename: Optional custom filename

        Returns:
            CalibrationExportResult with export details
        """
        return exportSession(
            self._database,
            sessionId,
            format=format,
            exportDirectory=exportDirectory,
            filename=filename
        )

    def deleteSession(self, sessionId: int, force: bool = False) -> bool:
        """
        Delete a calibration session and all associated data.

        Args:
            sessionId: ID of the session to delete
            force: If True, delete even if session is active

        Returns:
            True if session was deleted, False if not found

        Raises:
            CalibrationSessionError: If trying to delete active session without force
        """
        # Check if this is the current session
        isCurrentSession = (
            self._currentSession is not None and
            self._currentSession.sessionId == sessionId
        )

        result = deleteSession(self._database, sessionId, force=force)

        # If this was the current session, clear it
        if isCurrentSession and result:
            self._currentSession = None
            self._state = CalibrationState.ENABLED if self._enabled else CalibrationState.DISABLED

        return result

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
