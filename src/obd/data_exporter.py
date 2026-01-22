################################################################################
# File Name: data_exporter.py
# Purpose/Description: Export OBD-II realtime data to various formats (CSV)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-027
# ================================================================================
################################################################################

"""
Data export module for the Eclipse OBD-II system.

Provides:
- CSV export of realtime data with configurable date ranges
- Filtering by profile ID and parameter names
- Automatic filename generation with date ranges
- Configurable export directory with auto-creation

Usage:
    from obd.data_exporter import DataExporter, exportRealtimeDataToCsv

    exporter = DataExporter(db, config)
    result = exporter.exportToCsv(
        startDate=datetime.now() - timedelta(days=7),
        endDate=datetime.now(),
        profileId='daily',
        parameters=['RPM', 'SPEED']
    )

    # Or use helper function:
    result = exportRealtimeDataToCsv(
        db, startDate, endDate,
        profileId='daily',
        exportDirectory='./exports/'
    )
"""

import csv
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from obd.database import ObdDatabase

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

DEFAULT_EXPORT_DIRECTORY = './exports/'
CSV_COLUMNS = ['timestamp', 'parameter_name', 'value', 'unit']


# ================================================================================
# Custom Exceptions
# ================================================================================

class DataExportError(Exception):
    """Base exception for data export errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidDateRangeError(DataExportError):
    """Error when date range is invalid."""
    pass


class ExportDirectoryError(DataExportError):
    """Error creating or accessing export directory."""
    pass


# ================================================================================
# Enums and Dataclasses
# ================================================================================

class ExportFormat(Enum):
    """Supported export formats."""
    CSV = 'csv'

    @classmethod
    def fromString(cls, value: str) -> 'ExportFormat':
        """
        Convert string to ExportFormat.

        Args:
            value: Format string (case-insensitive)

        Returns:
            ExportFormat enum value

        Raises:
            ValueError: If format string not recognized
        """
        normalizedValue = value.lower()
        for fmt in cls:
            if fmt.value == normalizedValue:
                return fmt
        raise ValueError(f"Unknown export format: {value}")


@dataclass
class ExportResult:
    """
    Result of a data export operation.

    Attributes:
        success: Whether export completed successfully
        filePath: Path to exported file (if successful)
        recordCount: Number of records exported
        format: Export format used
        startDate: Start of date range
        endDate: End of date range
        profileId: Profile filter used (if any)
        parameters: Parameter filter used (if any)
        executionTimeMs: Time taken in milliseconds
        errorMessage: Error message (if failed)
    """
    success: bool
    recordCount: int = 0
    filePath: Optional[str] = None
    format: Optional[ExportFormat] = None
    startDate: Optional[datetime] = None
    endDate: Optional[datetime] = None
    profileId: Optional[str] = None
    parameters: Optional[List[str]] = None
    executionTimeMs: int = 0
    errorMessage: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns:
            Dictionary representation
        """
        return {
            'success': self.success,
            'filePath': self.filePath,
            'recordCount': self.recordCount,
            'format': self.format.value if self.format else None,
            'startDate': self.startDate.isoformat() if self.startDate else None,
            'endDate': self.endDate.isoformat() if self.endDate else None,
            'profileId': self.profileId,
            'parameters': self.parameters,
            'executionTimeMs': self.executionTimeMs,
            'errorMessage': self.errorMessage
        }


# ================================================================================
# DataExporter Class
# ================================================================================

class DataExporter:
    """
    Export OBD-II realtime data to various formats.

    Supports exporting data with filters for date range, profile,
    and specific parameters. Creates export directory if needed.

    Attributes:
        exportDirectory: Directory where exports are saved

    Example:
        exporter = DataExporter(db, config)
        result = exporter.exportToCsv(
            startDate=datetime.now() - timedelta(days=7),
            endDate=datetime.now(),
            profileId='daily'
        )
    """

    def __init__(self, db: ObdDatabase, config: Dict[str, Any]):
        """
        Initialize data exporter.

        Args:
            db: Database instance for data retrieval
            config: Configuration dictionary with optional 'export' section
        """
        self._db = db

        exportConfig = config.get('export', {})
        self.exportDirectory = exportConfig.get('directory', DEFAULT_EXPORT_DIRECTORY)

        logger.debug(f"DataExporter initialized with directory: {self.exportDirectory}")

    def ensureExportDirectory(self) -> None:
        """
        Ensure export directory exists, creating it if necessary.

        Raises:
            ExportDirectoryError: If directory cannot be created
        """
        try:
            Path(self.exportDirectory).mkdir(parents=True, exist_ok=True)
            logger.debug(f"Export directory ensured: {self.exportDirectory}")
        except Exception as e:
            raise ExportDirectoryError(
                f"Failed to create export directory: {e}",
                details={'directory': self.exportDirectory, 'error': str(e)}
            )

    def _validateDateRange(self, startDate: datetime, endDate: datetime) -> None:
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

    def _generateFilename(
        self,
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

    def _buildQuery(
        self,
        startDate: datetime,
        endDate: datetime,
        profileId: Optional[str] = None,
        parameters: Optional[List[str]] = None
    ) -> tuple:
        """
        Build SQL query for data retrieval.

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
        params: List[Any] = [startDate, endDate]

        if profileId:
            query += " AND profile_id = ?"
            params.append(profileId)

        if parameters:
            placeholders = ', '.join('?' for _ in parameters)
            query += f" AND parameter_name IN ({placeholders})"
            params.extend(parameters)

        query += " ORDER BY timestamp ASC"

        return query, params

    def exportToCsv(
        self,
        startDate: datetime,
        endDate: datetime,
        profileId: Optional[str] = None,
        parameters: Optional[List[str]] = None,
        filename: Optional[str] = None
    ) -> ExportResult:
        """
        Export realtime data to CSV file.

        Args:
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
            self._validateDateRange(startDate, endDate)

            # Ensure export directory exists
            self.ensureExportDirectory()

            # Generate filename if not provided
            if not filename:
                filename = self._generateFilename(startDate, endDate, ExportFormat.CSV)

            filePath = os.path.join(self.exportDirectory, filename)

            # Build and execute query
            query, queryParams = self._buildQuery(startDate, endDate, profileId, parameters)

            recordCount = 0
            with self._db.connect() as conn:
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


# ================================================================================
# Helper Functions
# ================================================================================

def createExporterFromConfig(db: ObdDatabase, config: Dict[str, Any]) -> DataExporter:
    """
    Create a DataExporter instance from configuration.

    Args:
        db: Database instance
        config: Configuration dictionary

    Returns:
        Configured DataExporter instance

    Example:
        config = {
            'export': {
                'directory': './exports/'
            }
        }
        exporter = createExporterFromConfig(db, config)
    """
    return DataExporter(db, config)


def exportRealtimeDataToCsv(
    db: ObdDatabase,
    startDate: datetime,
    endDate: datetime,
    profileId: Optional[str] = None,
    parameters: Optional[List[str]] = None,
    exportDirectory: str = DEFAULT_EXPORT_DIRECTORY,
    filename: Optional[str] = None
) -> ExportResult:
    """
    Export realtime data to CSV (convenience function).

    Args:
        db: Database instance
        startDate: Start of date range
        endDate: End of date range
        profileId: Optional profile ID filter
        parameters: Optional list of parameter names
        exportDirectory: Directory for export file
        filename: Optional custom filename

    Returns:
        ExportResult with export details

    Example:
        result = exportRealtimeDataToCsv(
            db,
            datetime.now() - timedelta(days=7),
            datetime.now(),
            profileId='daily'
        )
    """
    config = {'export': {'directory': exportDirectory}}
    exporter = DataExporter(db, config)
    return exporter.exportToCsv(
        startDate, endDate,
        profileId=profileId,
        parameters=parameters,
        filename=filename
    )
