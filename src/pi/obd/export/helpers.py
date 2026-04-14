################################################################################
# File Name: helpers.py
# Purpose/Description: Convenience module-level helpers for data export subpackage
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-027
# 2026-04-14    | Sweep 5       | Extracted from data_exporter.py (task 4 split)
# ================================================================================
################################################################################

"""
Convenience helper functions for common export scenarios.

These are thin wrappers over DataExporter that let callers trigger an export
without explicitly building the exporter + config plumbing.
"""

from datetime import datetime
from typing import Any

from obd.database import ObdDatabase
from obd.export.exporter import DataExporter
from obd.export.types import (
    DEFAULT_EXPORT_DIRECTORY,
    ExportFormat,
    ExportResult,
    SummaryExportResult,
)


def createExporterFromConfig(db: ObdDatabase, config: dict[str, Any]) -> DataExporter:
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
    profileId: str | None = None,
    parameters: list[str] | None = None,
    exportDirectory: str = DEFAULT_EXPORT_DIRECTORY,
    filename: str | None = None
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
    profileId: str | None = None,
    parameters: list[str] | None = None,
    exportDirectory: str = DEFAULT_EXPORT_DIRECTORY,
    filename: str | None = None
) -> ExportResult:
    """
    Export realtime data to JSON (convenience function).

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
    exportDate: datetime | None = None,
    profileIds: list[str] | None = None,
    format: ExportFormat = ExportFormat.JSON,
    exportDirectory: str = DEFAULT_EXPORT_DIRECTORY,
    filename: str | None = None
) -> SummaryExportResult:
    """
    Export summary report with statistics, AI recommendations, and alerts.

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
