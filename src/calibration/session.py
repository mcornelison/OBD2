################################################################################
# File Name: session.py
# Purpose/Description: Session lifecycle management for calibration
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
Calibration session lifecycle management.

Provides functions for creating, starting, ending, and managing calibration sessions.
"""

import logging
from datetime import datetime
from typing import Any, List, Optional

from .exceptions import CalibrationSessionError
from .types import CalibrationSession

logger = logging.getLogger(__name__)


def createSession(
    database: Any,
    notes: Optional[str] = None,
    profileId: Optional[str] = None
) -> CalibrationSession:
    """
    Create a new calibration session in the database.

    Args:
        database: ObdDatabase instance
        notes: Optional notes for this session
        profileId: Optional profile ID to associate with session

    Returns:
        CalibrationSession object

    Raises:
        CalibrationSessionError: If session creation fails
    """
    try:
        startTime = datetime.now()

        with database.connect() as conn:
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

        session = CalibrationSession(
            sessionId=sessionId,
            startTime=startTime,
            notes=notes,
            profileId=profileId
        )

        logger.info(f"Created calibration session {sessionId}")
        return session

    except Exception as e:
        raise CalibrationSessionError(
            f"Failed to create session: {e}",
            details={'error': str(e)}
        )


def endSession(
    database: Any,
    session: CalibrationSession
) -> CalibrationSession:
    """
    End a calibration session.

    Args:
        database: ObdDatabase instance
        session: Session to end

    Returns:
        Updated CalibrationSession with end time

    Raises:
        CalibrationSessionError: If session end fails
    """
    if not session.isActive:
        logger.warning(f"Session {session.sessionId} is not active")
        return session

    try:
        endTime = datetime.now()

        with database.connect() as conn:
            cursor = conn.cursor()

            # Update session end time
            cursor.execute(
                """
                UPDATE calibration_sessions
                SET end_time = ?
                WHERE session_id = ?
                """,
                (endTime, session.sessionId)
            )

            # Get reading count
            cursor.execute(
                """
                SELECT COUNT(*) FROM calibration_data
                WHERE session_id = ?
                """,
                (session.sessionId,)
            )
            readingCount = cursor.fetchone()[0]

        session.endTime = endTime
        session.readingCount = readingCount

        logger.info(
            f"Ended calibration session {session.sessionId} "
            f"(duration={session.durationSeconds:.1f}s, readings={readingCount})"
        )

        return session

    except Exception as e:
        raise CalibrationSessionError(
            f"Failed to end session: {e}",
            details={'error': str(e)}
        )


def getSession(
    database: Any,
    sessionId: int
) -> Optional[CalibrationSession]:
    """
    Get a calibration session by ID.

    Args:
        database: ObdDatabase instance
        sessionId: Session ID to retrieve

    Returns:
        CalibrationSession or None if not found
    """
    try:
        with database.connect() as conn:
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
    database: Any,
    limit: int = 100,
    includeActive: bool = True
) -> List[CalibrationSession]:
    """
    List calibration sessions.

    Args:
        database: ObdDatabase instance
        limit: Maximum number of sessions to return
        includeActive: Include sessions without end_time

    Returns:
        List of CalibrationSession objects, newest first
    """
    try:
        with database.connect() as conn:
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


def deleteSession(
    database: Any,
    sessionId: int,
    force: bool = False
) -> bool:
    """
    Delete a calibration session and all associated data.

    Args:
        database: ObdDatabase instance
        sessionId: ID of the session to delete
        force: If True, delete even if session is active

    Returns:
        True if session was deleted, False if not found

    Raises:
        CalibrationSessionError: If trying to delete active session without force
    """
    logger.info(f"Deleting calibration session {sessionId}")

    try:
        # Check if session exists and is active
        session = getSession(database, sessionId)
        if session is None:
            logger.warning(f"Session {sessionId} not found for deletion")
            return False

        if session.isActive and not force:
            raise CalibrationSessionError(
                f"Cannot delete active session {sessionId}. "
                "Use force=True to delete anyway."
            )

        with database.connect() as conn:
            cursor = conn.cursor()

            # Delete readings first (FK constraint)
            cursor.execute(
                "DELETE FROM calibration_data WHERE session_id = ?",
                (sessionId,)
            )
            readingsDeleted = cursor.rowcount

            # Delete session
            cursor.execute(
                "DELETE FROM calibration_sessions WHERE session_id = ?",
                (sessionId,)
            )
            sessionDeleted = cursor.rowcount > 0

        logger.info(
            f"Deleted session {sessionId} with {readingsDeleted} readings"
        )

        return sessionDeleted

    except CalibrationSessionError:
        raise
    except Exception as e:
        logger.error(f"Failed to delete session {sessionId}: {e}")
        raise CalibrationSessionError(
            f"Failed to delete session: {e}",
            details={'sessionId': sessionId, 'error': str(e)}
        )


def sessionExists(database: Any, sessionId: int) -> bool:
    """
    Check if a session exists.

    Args:
        database: ObdDatabase instance
        sessionId: Session ID to check

    Returns:
        True if session exists, False otherwise
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM calibration_sessions WHERE session_id = ?",
                (sessionId,)
            )
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Failed to check session existence: {e}")
        return False
