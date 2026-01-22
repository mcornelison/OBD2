################################################################################
# File Name: data_exporter.py
# Purpose/Description: Export OBD-II realtime data to various formats (CSV, JSON)
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
# 2026-01-22    | Ralph Agent3  | Added summary export for US-029 (statistics, AI recommendations, alerts)
# ================================================================================
################################################################################

"""
Data export module for the Eclipse OBD-II system.

Provides:
- CSV export of realtime data with configurable date ranges
- JSON export with metadata (export_date, profile, date_range, record_count)
- Summary export with statistics, AI recommendations, and alert history
- Filtering by profile ID and parameter names
- Automatic filename generation with date ranges
- Configurable export directory with auto-creation

Usage:
    from obd.data_exporter import DataExporter, exportRealtimeDataToCsv, exportRealtimeDataToJson

    exporter = DataExporter(db, config)

    # CSV export
    result = exporter.exportToCsv(
        startDate=datetime.now() - timedelta(days=7),
        endDate=datetime.now(),
        profileId='daily',
        parameters=['RPM', 'SPEED']
    )

    # JSON export
    result = exporter.exportToJson(
        startDate=datetime.now() - timedelta(days=7),
        endDate=datetime.now(),
        profileId='daily'
    )

    # Summary export (statistics + AI recommendations + alerts)
    result = exporter.exportSummary(
        exportDate=datetime.now(),
        profileIds=['daily', 'performance'],  # Optional, all profiles if None
        format=ExportFormat.JSON
    )

    # Or use helper functions:
    result = exportRealtimeDataToCsv(db, startDate, endDate, profileId='daily')
    result = exportRealtimeDataToJson(db, startDate, endDate, profileId='daily')
    result = exportSummaryReport(db, exportDate, profileIds=['daily'])
"""

import csv
import json
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

# Summary export CSV column headers
SUMMARY_STATISTICS_COLUMNS = [
    'profile_id', 'parameter_name', 'analysis_date', 'max_value', 'min_value',
    'avg_value', 'mode_value', 'std_1', 'std_2', 'outlier_min', 'outlier_max', 'sample_count'
]
SUMMARY_RECOMMENDATIONS_COLUMNS = [
    'id', 'profile_id', 'timestamp', 'recommendation', 'priority_rank', 'is_duplicate_of'
]
SUMMARY_ALERTS_COLUMNS = [
    'id', 'profile_id', 'timestamp', 'alert_type', 'parameter_name', 'value', 'threshold'
]


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
    JSON = 'json'

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


@dataclass
class SummaryExportResult:
    """
    Result of a summary export operation.

    Attributes:
        success: Whether export completed successfully
        filePath: Path to exported file (if successful)
        format: Export format used
        exportDate: Date for this summary report
        profileIds: Profile IDs included in export
        statisticsCount: Number of statistics records exported
        recommendationsCount: Number of AI recommendations exported
        alertsCount: Number of alert records exported
        executionTimeMs: Time taken in milliseconds
        errorMessage: Error message (if failed)
    """
    success: bool
    filePath: Optional[str] = None
    format: Optional[ExportFormat] = None
    exportDate: Optional[datetime] = None
    profileIds: Optional[List[str]] = None
    statisticsCount: int = 0
    recommendationsCount: int = 0
    alertsCount: int = 0
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
            'format': self.format.value if self.format else None,
            'exportDate': self.exportDate.isoformat() if self.exportDate else None,
            'profileIds': self.profileIds,
            'statisticsCount': self.statisticsCount,
            'recommendationsCount': self.recommendationsCount,
            'alertsCount': self.alertsCount,
            'executionTimeMs': self.executionTimeMs,
            'errorMessage': self.errorMessage
        }

    @property
    def totalRecordCount(self) -> int:
        """Total number of records exported across all sections."""
        return self.statisticsCount + self.recommendationsCount + self.alertsCount


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

    def exportToJson(
        self,
        startDate: datetime,
        endDate: datetime,
        profileId: Optional[str] = None,
        parameters: Optional[List[str]] = None,
        filename: Optional[str] = None
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
            self._validateDateRange(startDate, endDate)

            # Ensure export directory exists
            self.ensureExportDirectory()

            # Generate filename if not provided
            if not filename:
                filename = self._generateFilename(startDate, endDate, ExportFormat.JSON)

            filePath = os.path.join(self.exportDirectory, filename)

            # Build and execute query
            query, queryParams = self._buildQuery(startDate, endDate, profileId, parameters)

            dataRows: List[Dict[str, Any]] = []
            with self._db.connect() as conn:
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

    def _generateSummaryFilename(
        self,
        exportDate: datetime,
        format: ExportFormat = ExportFormat.CSV
    ) -> str:
        """
        Generate summary export filename with date.

        Args:
            exportDate: Date for the summary
            format: Export format

        Returns:
            Filename string (e.g., 'obd_summary_2026-01-22.csv')
        """
        dateStr = exportDate.strftime('%Y-%m-%d')
        extension = format.value
        return f'obd_summary_{dateStr}.{extension}'

    def _fetchStatistics(
        self,
        conn: Any,
        profileIds: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch statistics from database.

        Args:
            conn: Database connection
            profileIds: Optional list of profile IDs to filter

        Returns:
            List of statistics dictionaries
        """
        query = """
            SELECT profile_id, parameter_name, analysis_date, max_value, min_value,
                   avg_value, mode_value, std_1, std_2, outlier_min, outlier_max, sample_count
            FROM statistics
        """
        params: List[Any] = []

        if profileIds:
            placeholders = ', '.join('?' for _ in profileIds)
            query += f" WHERE profile_id IN ({placeholders})"
            params.extend(profileIds)

        query += " ORDER BY profile_id, parameter_name, analysis_date DESC"

        cursor = conn.cursor()
        cursor.execute(query, params)

        results = []
        for row in cursor:
            analysisDate = row[2]
            if isinstance(analysisDate, datetime):
                analysisDateStr = analysisDate.isoformat()
            else:
                analysisDateStr = str(analysisDate) if analysisDate else None

            results.append({
                'profile_id': row[0],
                'parameter_name': row[1],
                'analysis_date': analysisDateStr,
                'max_value': row[3],
                'min_value': row[4],
                'avg_value': row[5],
                'mode_value': row[6],
                'std_1': row[7],
                'std_2': row[8],
                'outlier_min': row[9],
                'outlier_max': row[10],
                'sample_count': row[11]
            })

        return results

    def _fetchRecommendations(
        self,
        conn: Any,
        profileIds: Optional[List[str]] = None,
        includeAllOrNonDuplicatesOnly: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Fetch AI recommendations from database.

        Args:
            conn: Database connection
            profileIds: Optional list of profile IDs to filter
            includeAllOrNonDuplicatesOnly: If False, only non-duplicates; if True, all

        Returns:
            List of recommendation dictionaries
        """
        query = """
            SELECT id, profile_id, timestamp, recommendation, priority_rank, is_duplicate_of
            FROM ai_recommendations
        """
        params: List[Any] = []
        conditions = []

        if profileIds:
            placeholders = ', '.join('?' for _ in profileIds)
            conditions.append(f"profile_id IN ({placeholders})")
            params.extend(profileIds)

        if not includeAllOrNonDuplicatesOnly:
            conditions.append("is_duplicate_of IS NULL")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY priority_rank ASC, timestamp DESC"

        cursor = conn.cursor()
        cursor.execute(query, params)

        results = []
        for row in cursor:
            timestamp = row[2]
            if isinstance(timestamp, datetime):
                timestampStr = timestamp.isoformat()
            else:
                timestampStr = str(timestamp) if timestamp else None

            results.append({
                'id': row[0],
                'profile_id': row[1],
                'timestamp': timestampStr,
                'recommendation': row[3],
                'priority_rank': row[4],
                'is_duplicate_of': row[5]
            })

        return results

    def _fetchAlerts(
        self,
        conn: Any,
        profileIds: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch alert history from database.

        Args:
            conn: Database connection
            profileIds: Optional list of profile IDs to filter

        Returns:
            List of alert dictionaries
        """
        query = """
            SELECT id, profile_id, timestamp, alert_type, parameter_name, value, threshold
            FROM alert_log
        """
        params: List[Any] = []

        if profileIds:
            placeholders = ', '.join('?' for _ in profileIds)
            query += f" WHERE profile_id IN ({placeholders})"
            params.extend(profileIds)

        query += " ORDER BY timestamp DESC"

        cursor = conn.cursor()
        cursor.execute(query, params)

        results = []
        for row in cursor:
            timestamp = row[2]
            if isinstance(timestamp, datetime):
                timestampStr = timestamp.isoformat()
            else:
                timestampStr = str(timestamp) if timestamp else None

            results.append({
                'id': row[0],
                'profile_id': row[1],
                'timestamp': timestampStr,
                'alert_type': row[3],
                'parameter_name': row[4],
                'value': row[5],
                'threshold': row[6]
            })

        return results

    def exportSummaryToCsv(
        self,
        exportDate: Optional[datetime] = None,
        profileIds: Optional[List[str]] = None,
        filename: Optional[str] = None
    ) -> SummaryExportResult:
        """
        Export summary report to CSV file.

        Generates a CSV with three sections:
        - Statistics summary (all parameters)
        - AI recommendations with rankings
        - Alert history

        Each section is prefixed with a section header row.

        Args:
            exportDate: Date for the summary (defaults to today)
            profileIds: Optional list of profile IDs to include (all if None)
            filename: Optional custom filename (auto-generated if not provided)

        Returns:
            SummaryExportResult with export details

        Raises:
            ExportDirectoryError: If export directory cannot be created
        """
        startTimeMs = time.time() * 1000

        if exportDate is None:
            exportDate = datetime.now()

        logger.info(
            f"Starting CSV summary export: date={exportDate.isoformat()}, "
            f"profiles={profileIds}"
        )

        try:
            # Ensure export directory exists
            self.ensureExportDirectory()

            # Generate filename if not provided
            if not filename:
                filename = self._generateSummaryFilename(exportDate, ExportFormat.CSV)

            filePath = os.path.join(self.exportDirectory, filename)

            # Fetch all data
            with self._db.connect() as conn:
                statistics = self._fetchStatistics(conn, profileIds)
                recommendations = self._fetchRecommendations(conn, profileIds)
                alerts = self._fetchAlerts(conn, profileIds)

            # Write to CSV - use newline='' for proper Windows handling
            with open(filePath, 'w', newline='', encoding='utf-8') as csvFile:
                writer = csv.writer(csvFile)

                # Section 1: Statistics
                writer.writerow(['# STATISTICS SUMMARY'])
                writer.writerow(SUMMARY_STATISTICS_COLUMNS)
                for stat in statistics:
                    writer.writerow([
                        stat['profile_id'],
                        stat['parameter_name'],
                        stat['analysis_date'],
                        stat['max_value'],
                        stat['min_value'],
                        stat['avg_value'],
                        stat['mode_value'],
                        stat['std_1'],
                        stat['std_2'],
                        stat['outlier_min'],
                        stat['outlier_max'],
                        stat['sample_count']
                    ])

                # Blank line separator
                writer.writerow([])

                # Section 2: AI Recommendations
                writer.writerow(['# AI RECOMMENDATIONS'])
                writer.writerow(SUMMARY_RECOMMENDATIONS_COLUMNS)
                for rec in recommendations:
                    writer.writerow([
                        rec['id'],
                        rec['profile_id'],
                        rec['timestamp'],
                        rec['recommendation'],
                        rec['priority_rank'],
                        rec['is_duplicate_of']
                    ])

                # Blank line separator
                writer.writerow([])

                # Section 3: Alert History
                writer.writerow(['# ALERT HISTORY'])
                writer.writerow(SUMMARY_ALERTS_COLUMNS)
                for alert in alerts:
                    writer.writerow([
                        alert['id'],
                        alert['profile_id'],
                        alert['timestamp'],
                        alert['alert_type'],
                        alert['parameter_name'],
                        alert['value'],
                        alert['threshold']
                    ])

            executionTimeMs = int(time.time() * 1000 - startTimeMs)

            logger.info(
                f"CSV summary export complete: {len(statistics)} statistics, "
                f"{len(recommendations)} recommendations, {len(alerts)} alerts "
                f"to {filePath} in {executionTimeMs}ms"
            )

            return SummaryExportResult(
                success=True,
                filePath=filePath,
                format=ExportFormat.CSV,
                exportDate=exportDate,
                profileIds=profileIds,
                statisticsCount=len(statistics),
                recommendationsCount=len(recommendations),
                alertsCount=len(alerts),
                executionTimeMs=executionTimeMs
            )

        except ExportDirectoryError:
            raise
        except Exception as e:
            executionTimeMs = int(time.time() * 1000 - startTimeMs)
            logger.error(f"CSV summary export failed: {e}")

            return SummaryExportResult(
                success=False,
                format=ExportFormat.CSV,
                exportDate=exportDate,
                profileIds=profileIds,
                executionTimeMs=executionTimeMs,
                errorMessage=str(e)
            )

    def exportSummaryToJson(
        self,
        exportDate: Optional[datetime] = None,
        profileIds: Optional[List[str]] = None,
        filename: Optional[str] = None
    ) -> SummaryExportResult:
        """
        Export summary report to JSON file.

        Generates JSON with structure:
        {
            "metadata": {
                "export_date": "ISO timestamp",
                "profiles": ["profile_id", ...] or null,
                "counts": {
                    "statistics": N,
                    "recommendations": N,
                    "alerts": N
                }
            },
            "statistics": [{...}, ...],
            "recommendations": [{...}, ...],
            "alerts": [{...}, ...]
        }

        Args:
            exportDate: Date for the summary (defaults to today)
            profileIds: Optional list of profile IDs to include (all if None)
            filename: Optional custom filename (auto-generated if not provided)

        Returns:
            SummaryExportResult with export details

        Raises:
            ExportDirectoryError: If export directory cannot be created
        """
        startTimeMs = time.time() * 1000

        if exportDate is None:
            exportDate = datetime.now()

        logger.info(
            f"Starting JSON summary export: date={exportDate.isoformat()}, "
            f"profiles={profileIds}"
        )

        try:
            # Ensure export directory exists
            self.ensureExportDirectory()

            # Generate filename if not provided
            if not filename:
                filename = self._generateSummaryFilename(exportDate, ExportFormat.JSON)

            filePath = os.path.join(self.exportDirectory, filename)

            # Fetch all data
            with self._db.connect() as conn:
                statistics = self._fetchStatistics(conn, profileIds)
                recommendations = self._fetchRecommendations(conn, profileIds)
                alerts = self._fetchAlerts(conn, profileIds)

            # Group by profile if multiple profiles selected
            statisticsByProfile: Dict[str, List[Dict[str, Any]]] = {}
            for stat in statistics:
                profileId = stat.get('profile_id') or 'unknown'
                if profileId not in statisticsByProfile:
                    statisticsByProfile[profileId] = []
                statisticsByProfile[profileId].append(stat)

            recommendationsByProfile: Dict[str, List[Dict[str, Any]]] = {}
            for rec in recommendations:
                profileId = rec.get('profile_id') or 'unknown'
                if profileId not in recommendationsByProfile:
                    recommendationsByProfile[profileId] = []
                recommendationsByProfile[profileId].append(rec)

            alertsByProfile: Dict[str, List[Dict[str, Any]]] = {}
            for alert in alerts:
                profileId = alert.get('profile_id') or 'unknown'
                if profileId not in alertsByProfile:
                    alertsByProfile[profileId] = []
                alertsByProfile[profileId].append(alert)

            # Build JSON structure
            exportData = {
                'metadata': {
                    'export_date': datetime.now().isoformat(),
                    'summary_date': exportDate.isoformat(),
                    'profiles': profileIds,
                    'counts': {
                        'statistics': len(statistics),
                        'recommendations': len(recommendations),
                        'alerts': len(alerts)
                    }
                },
                'statistics': statisticsByProfile if profileIds and len(profileIds) > 1 else statistics,
                'recommendations': recommendationsByProfile if profileIds and len(profileIds) > 1 else recommendations,
                'alerts': alertsByProfile if profileIds and len(profileIds) > 1 else alerts
            }

            # Write to JSON file
            with open(filePath, 'w', encoding='utf-8') as jsonFile:
                json.dump(exportData, jsonFile, indent=2)

            executionTimeMs = int(time.time() * 1000 - startTimeMs)

            logger.info(
                f"JSON summary export complete: {len(statistics)} statistics, "
                f"{len(recommendations)} recommendations, {len(alerts)} alerts "
                f"to {filePath} in {executionTimeMs}ms"
            )

            return SummaryExportResult(
                success=True,
                filePath=filePath,
                format=ExportFormat.JSON,
                exportDate=exportDate,
                profileIds=profileIds,
                statisticsCount=len(statistics),
                recommendationsCount=len(recommendations),
                alertsCount=len(alerts),
                executionTimeMs=executionTimeMs
            )

        except ExportDirectoryError:
            raise
        except Exception as e:
            executionTimeMs = int(time.time() * 1000 - startTimeMs)
            logger.error(f"JSON summary export failed: {e}")

            return SummaryExportResult(
                success=False,
                format=ExportFormat.JSON,
                exportDate=exportDate,
                profileIds=profileIds,
                executionTimeMs=executionTimeMs,
                errorMessage=str(e)
            )

    def exportSummary(
        self,
        exportDate: Optional[datetime] = None,
        profileIds: Optional[List[str]] = None,
        format: ExportFormat = ExportFormat.JSON,
        filename: Optional[str] = None
    ) -> SummaryExportResult:
        """
        Export summary report in specified format.

        Convenience method that delegates to exportSummaryToCsv or exportSummaryToJson.

        Args:
            exportDate: Date for the summary (defaults to today)
            profileIds: Optional list of profile IDs to include (all if None)
            format: Export format (CSV or JSON)
            filename: Optional custom filename (auto-generated if not provided)

        Returns:
            SummaryExportResult with export details
        """
        if format == ExportFormat.CSV:
            return self.exportSummaryToCsv(exportDate, profileIds, filename)
        else:
            return self.exportSummaryToJson(exportDate, profileIds, filename)


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


def exportRealtimeDataToJson(
    db: ObdDatabase,
    startDate: datetime,
    endDate: datetime,
    profileId: Optional[str] = None,
    parameters: Optional[List[str]] = None,
    exportDirectory: str = DEFAULT_EXPORT_DIRECTORY,
    filename: Optional[str] = None
) -> ExportResult:
    """
    Export realtime data to JSON (convenience function).

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
        result = exportRealtimeDataToJson(
            db,
            datetime.now() - timedelta(days=7),
            datetime.now(),
            profileId='daily'
        )
    """
    config = {'export': {'directory': exportDirectory}}
    exporter = DataExporter(db, config)
    return exporter.exportToJson(
        startDate, endDate,
        profileId=profileId,
        parameters=parameters,
        filename=filename
    )


def exportSummaryReport(
    db: ObdDatabase,
    exportDate: Optional[datetime] = None,
    profileIds: Optional[List[str]] = None,
    format: ExportFormat = ExportFormat.JSON,
    exportDirectory: str = DEFAULT_EXPORT_DIRECTORY,
    filename: Optional[str] = None
) -> SummaryExportResult:
    """
    Export summary report with statistics, AI recommendations, and alerts (convenience function).

    Generates a combined report containing:
    - Statistics summary (all parameters)
    - AI recommendations with priority rankings
    - Alert history

    CSV format uses section headers (# STATISTICS SUMMARY, # AI RECOMMENDATIONS, # ALERT HISTORY).
    JSON format groups data by profile when multiple profiles are selected.

    Args:
        db: Database instance
        exportDate: Date for the summary (defaults to today)
        profileIds: Optional list of profile IDs to include (all if None)
        format: Export format (CSV or JSON, defaults to JSON)
        exportDirectory: Directory for export file
        filename: Optional custom filename

    Returns:
        SummaryExportResult with export details

    Example:
        # Export all profiles to JSON
        result = exportSummaryReport(db)

        # Export specific profiles to CSV
        result = exportSummaryReport(
            db,
            exportDate=datetime.now(),
            profileIds=['daily', 'performance'],
            format=ExportFormat.CSV
        )
    """
    config = {'export': {'directory': exportDirectory}}
    exporter = DataExporter(db, config)
    return exporter.exportSummary(
        exportDate=exportDate,
        profileIds=profileIds,
        format=format,
        filename=filename
    )
