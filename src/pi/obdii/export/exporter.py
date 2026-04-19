################################################################################
# File Name: exporter.py
# Purpose/Description: DataExporter class facade for OBD-II data export
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-027
# 2026-01-22    | Ralph Agent3  | Added JSON + summary export for US-028/029
# 2026-04-14    | Sweep 5       | Extracted from data_exporter.py (task 4 split)
# ================================================================================
################################################################################

"""
DataExporter class — stateful facade over the export module functions.

Holds DB reference and export directory from config, then delegates
realtime and summary export methods to the implementation modules.
"""

import logging
from datetime import datetime
from typing import Any

from obd.database import ObdDatabase
from obd.export.realtime import (
    buildRealtimeQuery,
    ensureExportDirectory,
    exportRealtimeToCsv,
    exportRealtimeToJson,
    generateRealtimeFilename,
    validateDateRange,
)
from obd.export.summary import exportSummaryToCsv, exportSummaryToJson
from obd.export.summary_fetchers import (
    fetchAlerts,
    fetchRecommendations,
    fetchStatistics,
    generateSummaryFilename,
)
from obd.export.types import (
    DEFAULT_EXPORT_DIRECTORY,
    ExportFormat,
    ExportResult,
    SummaryExportResult,
)

logger = logging.getLogger(__name__)


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

    def __init__(self, db: ObdDatabase, config: dict[str, Any]):
        """
        Initialize data exporter.

        Args:
            db: Database instance for data retrieval
            config: Configuration dictionary with optional 'export' section
        """
        self._db = db

        exportConfig = config.get('pi', {}).get('export', {})
        self.exportDirectory = exportConfig.get('directory', DEFAULT_EXPORT_DIRECTORY)

        logger.debug(f"DataExporter initialized with directory: {self.exportDirectory}")

    def ensureExportDirectory(self) -> None:
        """
        Ensure export directory exists, creating it if necessary.

        Raises:
            ExportDirectoryError: If directory cannot be created
        """
        ensureExportDirectory(self.exportDirectory)

    def _validateDateRange(self, startDate: datetime, endDate: datetime) -> None:
        """
        Validate date range parameters.

        Args:
            startDate: Start of date range
            endDate: End of date range

        Raises:
            InvalidDateRangeError: If end date is before start date
        """
        validateDateRange(startDate, endDate)

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
        return generateRealtimeFilename(startDate, endDate, format)

    def _buildQuery(
        self,
        startDate: datetime,
        endDate: datetime,
        profileId: str | None = None,
        parameters: list[str] | None = None
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
        return buildRealtimeQuery(startDate, endDate, profileId, parameters)

    def exportToCsv(
        self,
        startDate: datetime,
        endDate: datetime,
        profileId: str | None = None,
        parameters: list[str] | None = None,
        filename: str | None = None
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
        return exportRealtimeToCsv(
            self._db,
            self.exportDirectory,
            startDate,
            endDate,
            profileId=profileId,
            parameters=parameters,
            filename=filename,
        )

    def exportToJson(
        self,
        startDate: datetime,
        endDate: datetime,
        profileId: str | None = None,
        parameters: list[str] | None = None,
        filename: str | None = None
    ) -> ExportResult:
        """
        Export realtime data to JSON file.

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
        return exportRealtimeToJson(
            self._db,
            self.exportDirectory,
            startDate,
            endDate,
            profileId=profileId,
            parameters=parameters,
            filename=filename,
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
        return generateSummaryFilename(exportDate, format.value)

    def _fetchStatistics(
        self,
        conn: Any,
        profileIds: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Fetch statistics rows (see summary_fetchers.fetchStatistics)."""
        return fetchStatistics(conn, profileIds)

    def _fetchRecommendations(
        self,
        conn: Any,
        profileIds: list[str] | None = None,
        includeAllOrNonDuplicatesOnly: bool = False
    ) -> list[dict[str, Any]]:
        """Fetch recommendation rows (see summary_fetchers.fetchRecommendations)."""
        return fetchRecommendations(conn, profileIds, includeAllOrNonDuplicatesOnly)

    def _fetchAlerts(
        self,
        conn: Any,
        profileIds: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Fetch alert rows (see summary_fetchers.fetchAlerts)."""
        return fetchAlerts(conn, profileIds)

    def exportSummaryToCsv(
        self,
        exportDate: datetime | None = None,
        profileIds: list[str] | None = None,
        filename: str | None = None
    ) -> SummaryExportResult:
        """
        Export summary report to CSV file.

        Args:
            exportDate: Date for the summary (defaults to today)
            profileIds: Optional list of profile IDs to include (all if None)
            filename: Optional custom filename (auto-generated if not provided)

        Returns:
            SummaryExportResult with export details

        Raises:
            ExportDirectoryError: If export directory cannot be created
        """
        return exportSummaryToCsv(
            self._db,
            self.exportDirectory,
            exportDate=exportDate,
            profileIds=profileIds,
            filename=filename,
        )

    def exportSummaryToJson(
        self,
        exportDate: datetime | None = None,
        profileIds: list[str] | None = None,
        filename: str | None = None
    ) -> SummaryExportResult:
        """
        Export summary report to JSON file.

        Args:
            exportDate: Date for the summary (defaults to today)
            profileIds: Optional list of profile IDs to include (all if None)
            filename: Optional custom filename (auto-generated if not provided)

        Returns:
            SummaryExportResult with export details

        Raises:
            ExportDirectoryError: If export directory cannot be created
        """
        return exportSummaryToJson(
            self._db,
            self.exportDirectory,
            exportDate=exportDate,
            profileIds=profileIds,
            filename=filename,
        )

    def exportSummary(
        self,
        exportDate: datetime | None = None,
        profileIds: list[str] | None = None,
        format: ExportFormat = ExportFormat.JSON,
        filename: str | None = None
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
