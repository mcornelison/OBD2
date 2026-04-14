################################################################################
# File Name: realtime.py
# Purpose/Description: Export OBD-II realtime data rows to CSV and JSON formats
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-027
# 2026-01-22    | Ralph Agent3  | Added JSON export for US-028
# 2026-04-14    | Sweep 5       | Extracted from data_exporter.py (task 4 split)
# ================================================================================
################################################################################

"""
Realtime data export implementation.

Provides module-level functions that export rows from the realtime_data table
to CSV or JSON with optional date/profile/parameter filtering. Called by
the DataExporter class facade.
"""

import csv
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from obd.export.types import (
    CSV_COLUMNS,
    ExportDirectoryError,
    ExportFormat,
    ExportResult,
    InvalidDateRangeError,
)

logger = logging.getLogger(__name__)


def ensureExportDirectory(exportDirectory: str) -> None:
    """
    Ensure export directory exists, creating it if necessary.

    Args:
        exportDirectory: Directory path to ensure

    Raises:
        ExportDirectoryError: If directory cannot be created
    """
    try:
        Path(exportDirectory).mkdir(parents=True, exist_ok=True)
        logger.debug(f"Export directory ensured: {exportDirectory}")
    except Exception as e:
        raise ExportDirectoryError(
            f"Failed to create export directory: {e}",
            details={'directory': exportDirectory, 'error': str(e)}
        ) from e


def validateDateRange(startDate: datetime, endDate: datetime) -> None:
    """
    Validate date range parameters.

    Args:
        startDate: Start of date range
        endDate: End of date range

    Raises:
        InvalidDateRangeError: If end date is before start date
    """
    if endDate < startDate:
        raise InvalidDateRangeError(
            "End date cannot be before start date",
            details={'startDate': startDate.isoformat(), 'endDate': endDate.isoformat()}
        )


def generateRealtimeFilename(
    startDate: datetime,
    endDate: datetime,
    format: ExportFormat = ExportFormat.CSV
) -> str:
    """
    Generate export filename with date range.

    Args:
        startDate: Start of date range
        endDate: End of date range
        format: Export format

    Returns:
        Filename string (e.g., 'obd_export_2026-01-15_to_2026-01-22.csv')
    """
    startStr = startDate.strftime('%Y-%m-%d')
    endStr = endDate.strftime('%Y-%m-%d')
    extension = format.value
    return f'obd_export_{startStr}_to_{endStr}.{extension}'


def buildRealtimeQuery(
    startDate: datetime,
    endDate: datetime,
    profileId: str | None = None,
    parameters: list[str] | None = None
) -> tuple:
    """
    Build SQL query for realtime data retrieval.

    Args:
        startDate: Start of date range
        endDate: End of date range
        profileId: Optional profile filter
        parameters: Optional parameter name filter

    Returns:
        Tuple of (query_string, parameters_list)
    """
    query = """
        SELECT timestamp, parameter_name, value, unit
        FROM realtime_data
        WHERE timestamp >= ? AND timestamp <= ?
    """
    params: list[Any] = [startDate, endDate]

    if profileId:
        query += " AND profile_id = ?"
        params.append(profileId)

    if parameters:
        placeholders = ', '.join('?' for _ in parameters)
        query += f" AND parameter_name IN ({placeholders})"
        params.extend(parameters)

    query += " ORDER BY timestamp ASC"

    return query, params


def exportRealtimeToCsv(
    db: Any,
    exportDirectory: str,
    startDate: datetime,
    endDate: datetime,
    profileId: str | None = None,
    parameters: list[str] | None = None,
    filename: str | None = None
) -> ExportResult:
    """
    Export realtime data to CSV file.

    Args:
        db: Database instance for data retrieval
        exportDirectory: Target directory for the CSV file
        startDate: Start of date range
        endDate: End of date range
        profileId: Optional profile ID filter
        parameters: Optional list of parameter names to include
        filename: Optional custom filename (auto-generated if not provided)

    Returns:
        ExportResult with export details

    Raises:
        InvalidDateRangeError: If end date is before start date
        ExportDirectoryError: If export directory cannot be created
    """
    startTimeMs = time.time() * 1000

    logger.info(
        f"Starting CSV export: {startDate.isoformat()} to {endDate.isoformat()}, "
        f"profile={profileId}, parameters={parameters}"
    )

    try:
        # Validate date range
        validateDateRange(startDate, endDate)

        # Ensure export directory exists
        ensureExportDirectory(exportDirectory)

        # Generate filename if not provided
        if not filename:
            filename = generateRealtimeFilename(startDate, endDate, ExportFormat.CSV)

        filePath = os.path.join(exportDirectory, filename)

        # Build and execute query
        query, queryParams = buildRealtimeQuery(startDate, endDate, profileId, parameters)

        recordCount = 0
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(query, queryParams)

            # Write to CSV - use newline='' for proper Windows handling
            with open(filePath, 'w', newline='', encoding='utf-8') as csvFile:
                writer = csv.writer(csvFile)

                # Write header
                writer.writerow(CSV_COLUMNS)

                # Write data rows
                for row in cursor:
                    # Format timestamp as ISO string
                    timestamp = row[0]
                    if isinstance(timestamp, datetime):
                        timestampStr = timestamp.isoformat()
                    else:
                        timestampStr = str(timestamp)

                    writer.writerow([
                        timestampStr,
                        row[1],  # parameter_name
                        row[2],  # value
                        row[3]   # unit
                    ])
                    recordCount += 1

        executionTimeMs = int(time.time() * 1000 - startTimeMs)

        logger.info(
            f"CSV export complete: {recordCount} records to {filePath} "
            f"in {executionTimeMs}ms"
        )

        return ExportResult(
            success=True,
            filePath=filePath,
            recordCount=recordCount,
            format=ExportFormat.CSV,
            startDate=startDate,
            endDate=endDate,
            profileId=profileId,
            parameters=parameters,
            executionTimeMs=executionTimeMs
        )

    except (InvalidDateRangeError, ExportDirectoryError):
        raise
    except Exception as e:
        executionTimeMs = int(time.time() * 1000 - startTimeMs)
        logger.error(f"CSV export failed: {e}")

        return ExportResult(
            success=False,
            recordCount=0,
            format=ExportFormat.CSV,
            startDate=startDate,
            endDate=endDate,
            profileId=profileId,
            parameters=parameters,
            executionTimeMs=executionTimeMs,
            errorMessage=str(e)
        )


def exportRealtimeToJson(
    db: Any,
    exportDirectory: str,
    startDate: datetime,
    endDate: datetime,
    profileId: str | None = None,
    parameters: list[str] | None = None,
    filename: str | None = None
) -> ExportResult:
    """
    Export realtime data to JSON file.

    Generates JSON with structure:
    {
        "metadata": {
            "export_date": "ISO timestamp",
            "profile": "profile_id or null",
            "date_range": {"start": "ISO", "end": "ISO"},
            "record_count": N
        },
        "data": [
            {"timestamp": "ISO", "parameter": "name", "value": N, "unit": "str"},
            ...
        ]
    }

    Args:
        db: Database instance for data retrieval
        exportDirectory: Target directory for the JSON file
        startDate: Start of date range
        endDate: End of date range
        profileId: Optional profile ID filter
        parameters: Optional list of parameter names to include
        filename: Optional custom filename (auto-generated if not provided)

    Returns:
        ExportResult with export details

    Raises:
        InvalidDateRangeError: If end date is before start date
        ExportDirectoryError: If export directory cannot be created
    """
    startTimeMs = time.time() * 1000

    logger.info(
        f"Starting JSON export: {startDate.isoformat()} to {endDate.isoformat()}, "
        f"profile={profileId}, parameters={parameters}"
    )

    try:
        # Validate date range
        validateDateRange(startDate, endDate)

        # Ensure export directory exists
        ensureExportDirectory(exportDirectory)

        # Generate filename if not provided
        if not filename:
            filename = generateRealtimeFilename(startDate, endDate, ExportFormat.JSON)

        filePath = os.path.join(exportDirectory, filename)

        # Build and execute query
        query, queryParams = buildRealtimeQuery(startDate, endDate, profileId, parameters)

        dataRows: list[dict[str, Any]] = []
        with db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(query, queryParams)

            for row in cursor:
                # Format timestamp as ISO string
                timestamp = row[0]
                if isinstance(timestamp, datetime):
                    timestampStr = timestamp.isoformat()
                else:
                    timestampStr = str(timestamp)

                dataRows.append({
                    'timestamp': timestampStr,
                    'parameter': row[1],  # parameter_name
                    'value': row[2],       # value
                    'unit': row[3]         # unit
                })

        recordCount = len(dataRows)

        # Build JSON structure
        exportData = {
            'metadata': {
                'export_date': datetime.now().isoformat(),
                'profile': profileId,
                'date_range': {
                    'start': startDate.isoformat(),
                    'end': endDate.isoformat()
                },
                'record_count': recordCount
            },
            'data': dataRows
        }

        # Write to JSON file
        with open(filePath, 'w', encoding='utf-8') as jsonFile:
            json.dump(exportData, jsonFile, indent=2)

        executionTimeMs = int(time.time() * 1000 - startTimeMs)

        logger.info(
            f"JSON export complete: {recordCount} records to {filePath} "
            f"in {executionTimeMs}ms"
        )

        return ExportResult(
            success=True,
            filePath=filePath,
            recordCount=recordCount,
            format=ExportFormat.JSON,
            startDate=startDate,
            endDate=endDate,
            profileId=profileId,
            parameters=parameters,
            executionTimeMs=executionTimeMs
        )

    except (InvalidDateRangeError, ExportDirectoryError):
        raise
    except Exception as e:
        executionTimeMs = int(time.time() * 1000 - startTimeMs)
        logger.error(f"JSON export failed: {e}")

        return ExportResult(
            success=False,
            recordCount=0,
            format=ExportFormat.JSON,
            startDate=startDate,
            endDate=endDate,
            profileId=profileId,
            parameters=parameters,
            executionTimeMs=executionTimeMs,
            errorMessage=str(e)
        )
