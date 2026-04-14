################################################################################
# File Name: export.py
# Purpose/Description: Export calibration sessions to CSV/JSON formats
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
Calibration session export functionality.

Provides functions for exporting calibration sessions to CSV and JSON formats.
"""

import csv
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .collector import getSessionReadings
from .session import getSession
from .types import (
    CalibrationExportResult,
    CalibrationReading,
    CalibrationSession,
)

logger = logging.getLogger(__name__)


def exportSession(
    database: Any,
    sessionId: int,
    format: str = 'csv',
    exportDirectory: str = './exports/',
    filename: str | None = None
) -> CalibrationExportResult:
    """
    Export a calibration session to CSV or JSON file.

    Args:
        database: ObdDatabase instance
        sessionId: ID of the session to export
        format: Export format ('csv' or 'json')
        exportDirectory: Directory to save export file
        filename: Optional custom filename

    Returns:
        CalibrationExportResult with export details

    Example:
        result = exportSession(
            database=db,
            sessionId=1,
            format='csv',
            exportDirectory='./exports/'
        )
    """
    startTimeMs = time.time() * 1000
    formatLower = format.lower()

    logger.info(f"Starting {formatLower.upper()} export for session {sessionId}")

    try:
        # Get session to verify it exists
        session = getSession(database, sessionId)
        if session is None:
            return CalibrationExportResult(
                success=False,
                sessionId=sessionId,
                format=formatLower,
                errorMessage=f"Session {sessionId} not found"
            )

        # Ensure export directory exists
        Path(exportDirectory).mkdir(parents=True, exist_ok=True)

        # Generate filename if not provided
        if not filename:
            dateStr = session.startTime.strftime('%Y-%m-%d')
            extension = formatLower
            filename = f'calibration_session_{sessionId}_{dateStr}.{extension}'

        filePath = os.path.join(exportDirectory, filename)

        # Get readings for export
        readings = getSessionReadings(database, sessionId)

        if formatLower == 'csv':
            recordCount = _exportSessionToCsv(session, readings, filePath)
        elif formatLower == 'json':
            recordCount = _exportSessionToJson(session, readings, filePath)
        else:
            return CalibrationExportResult(
                success=False,
                sessionId=sessionId,
                format=formatLower,
                errorMessage=f"Unsupported format: {format}"
            )

        executionTimeMs = int(time.time() * 1000 - startTimeMs)

        logger.info(
            f"Export complete: {recordCount} readings to {filePath} "
            f"in {executionTimeMs}ms"
        )

        return CalibrationExportResult(
            success=True,
            filePath=filePath,
            recordCount=recordCount,
            format=formatLower,
            sessionId=sessionId,
            executionTimeMs=executionTimeMs
        )

    except Exception as e:
        executionTimeMs = int(time.time() * 1000 - startTimeMs)
        logger.error(f"Export failed for session {sessionId}: {e}")

        return CalibrationExportResult(
            success=False,
            sessionId=sessionId,
            format=formatLower,
            executionTimeMs=executionTimeMs,
            errorMessage=str(e)
        )


def _exportSessionToCsv(
    session: CalibrationSession,
    readings: list[CalibrationReading],
    filePath: str
) -> int:
    """
    Export session readings to CSV file.

    Args:
        session: CalibrationSession to export
        readings: List of readings to export
        filePath: Path to output file

    Returns:
        Number of records written
    """
    # Use newline='' for proper Windows handling
    with open(filePath, 'w', newline='', encoding='utf-8') as csvFile:
        writer = csv.writer(csvFile)

        # Write header
        writer.writerow(['timestamp', 'parameter_name', 'value', 'unit'])

        # Write data rows
        for reading in readings:
            timestampStr = (
                reading.timestamp.isoformat()
                if isinstance(reading.timestamp, datetime)
                else str(reading.timestamp)
            )
            writer.writerow([
                timestampStr,
                reading.parameterName,
                reading.value,
                reading.unit
            ])

    return len(readings)


def _exportSessionToJson(
    session: CalibrationSession,
    readings: list[CalibrationReading],
    filePath: str
) -> int:
    """
    Export session readings to JSON file.

    Args:
        session: CalibrationSession to export
        readings: List of readings to export
        filePath: Path to output file

    Returns:
        Number of records written
    """
    dataRows = []
    for reading in readings:
        timestampStr = (
            reading.timestamp.isoformat()
            if isinstance(reading.timestamp, datetime)
            else str(reading.timestamp)
        )
        dataRows.append({
            'timestamp': timestampStr,
            'parameter': reading.parameterName,
            'value': reading.value,
            'unit': reading.unit
        })

    exportData = {
        'metadata': {
            'session_id': session.sessionId,
            'export_date': datetime.now().isoformat(),
            'start_time': session.startTime.isoformat(),
            'end_time': session.endTime.isoformat() if session.endTime else None,
            'notes': session.notes,
            'profile_id': session.profileId,
            'duration_seconds': session.durationSeconds,
            'record_count': len(readings)
        },
        'data': dataRows
    }

    with open(filePath, 'w', encoding='utf-8') as jsonFile:
        json.dump(exportData, jsonFile, indent=2)

    return len(readings)
