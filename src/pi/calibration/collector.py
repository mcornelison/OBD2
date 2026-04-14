################################################################################
# File Name: collector.py
# Purpose/Description: Reading collection and storage for calibration sessions
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
Calibration reading collection and storage.

Provides functions for logging calibration readings to the database
and retrieving readings for a session.
"""

import logging
from datetime import datetime
from typing import Any

from .exceptions import CalibrationSessionError
from .types import CalibrationReading

logger = logging.getLogger(__name__)


def logReading(
    database: Any,
    sessionId: int,
    parameterName: str,
    value: float | None,
    unit: str | None = None,
    rawValue: str | None = None,
    timestamp: datetime | None = None
) -> CalibrationReading:
    """
    Log a calibration reading to the database.

    Args:
        database: ObdDatabase instance
        sessionId: ID of the active session
        parameterName: Name of the OBD-II parameter
        value: Numeric value (may be None for non-numeric)
        unit: Unit of measurement
        rawValue: Raw string value for non-numeric data
        timestamp: Optional timestamp (defaults to now)

    Returns:
        CalibrationReading object

    Raises:
        CalibrationSessionError: If logging fails
    """
    readingTime = timestamp or datetime.now()

    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO calibration_data
                (session_id, timestamp, parameter_name, value, unit, raw_value)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (sessionId, readingTime, parameterName, value, unit, rawValue)
            )

        reading = CalibrationReading(
            parameterName=parameterName,
            value=value,
            unit=unit,
            timestamp=readingTime,
            sessionId=sessionId,
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
        ) from e


def getSessionReadings(
    database: Any,
    sessionId: int,
    parameterName: str | None = None,
    limit: int = 10000
) -> list[CalibrationReading]:
    """
    Get readings for a calibration session.

    Args:
        database: ObdDatabase instance
        sessionId: Session ID to retrieve readings for
        parameterName: Optional filter by parameter name
        limit: Maximum number of readings to return

    Returns:
        List of CalibrationReading objects
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()

            query = """
                SELECT parameter_name, value, unit, timestamp, raw_value
                FROM calibration_data
                WHERE session_id = ?
            """
            params: list[Any] = [sessionId]

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


def getReadingCount(database: Any, sessionId: int) -> int:
    """
    Get the number of readings in a session.

    Args:
        database: ObdDatabase instance
        sessionId: Session ID to count readings for

    Returns:
        Number of readings in the session
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM calibration_data WHERE session_id = ?",
                (sessionId,)
            )
            return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Failed to get reading count for session {sessionId}: {e}")
        return 0


def getParameterNames(database: Any, sessionId: int) -> list[str]:
    """
    Get list of parameter names logged in a session.

    Args:
        database: ObdDatabase instance
        sessionId: Session ID to get parameters for

    Returns:
        List of unique parameter names
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT parameter_name
                FROM calibration_data
                WHERE session_id = ?
                ORDER BY parameter_name
                """,
                (sessionId,)
            )
            return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get parameter names for session {sessionId}: {e}")
        return []


def logMultipleReadings(
    database: Any,
    sessionId: int,
    readings: list[dict],
    timestamp: datetime | None = None
) -> int:
    """
    Log multiple calibration readings in a single transaction.

    Args:
        database: ObdDatabase instance
        sessionId: ID of the active session
        readings: List of reading dicts with keys: parameterName, value, unit, rawValue
        timestamp: Optional timestamp to use for all readings (defaults to now)

    Returns:
        Number of readings logged

    Raises:
        CalibrationSessionError: If logging fails

    Example:
        readings = [
            {'parameterName': 'RPM', 'value': 2500, 'unit': 'rpm'},
            {'parameterName': 'SPEED', 'value': 65, 'unit': 'mph'},
        ]
        count = logMultipleReadings(database, sessionId, readings)
    """
    readingTime = timestamp or datetime.now()
    count = 0

    try:
        with database.connect() as conn:
            cursor = conn.cursor()

            for reading in readings:
                cursor.execute(
                    """
                    INSERT INTO calibration_data
                    (session_id, timestamp, parameter_name, value, unit, raw_value)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sessionId,
                        readingTime,
                        reading.get('parameterName'),
                        reading.get('value'),
                        reading.get('unit'),
                        reading.get('rawValue')
                    )
                )
                count += 1

        logger.debug(f"Logged {count} calibration readings")
        return count

    except Exception as e:
        logger.error(f"Failed to log multiple calibration readings: {e}")
        raise CalibrationSessionError(
            f"Failed to log readings: {e}",
            details={'count': len(readings), 'error': str(e)}
        ) from e
