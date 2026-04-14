################################################################################
# File Name: summary.py
# Purpose/Description: Summary export implementation (statistics + recommendations + alerts)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent3  | Initial implementation for US-029
# 2026-04-14    | Sweep 5       | Extracted from data_exporter.py (task 4 split)
# ================================================================================
################################################################################

"""
Summary export implementation.

Provides module-level functions that export combined summary reports
(statistics + AI recommendations + alerts) to CSV and JSON. Called by
the DataExporter class facade.
"""

import csv
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from obd.export.realtime import ensureExportDirectory
from obd.export.summary_fetchers import (
    fetchAlerts,
    fetchRecommendations,
    fetchStatistics,
    generateSummaryFilename,
)
from obd.export.types import (
    SUMMARY_ALERTS_COLUMNS,
    SUMMARY_RECOMMENDATIONS_COLUMNS,
    SUMMARY_STATISTICS_COLUMNS,
    ExportDirectoryError,
    ExportFormat,
    SummaryExportResult,
)

logger = logging.getLogger(__name__)


def exportSummaryToCsv(
    db: Any,
    exportDirectory: str,
    exportDate: datetime | None = None,
    profileIds: list[str] | None = None,
    filename: str | None = None
) -> SummaryExportResult:
    """
    Export summary report to CSV file.

    Generates a CSV with three sections:
    - Statistics summary (all parameters)
    - AI recommendations with rankings
    - Alert history

    Each section is prefixed with a section header row.

    Args:
        db: Database instance for data retrieval
        exportDirectory: Target directory for the CSV file
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
        ensureExportDirectory(exportDirectory)

        # Generate filename if not provided
        if not filename:
            filename = generateSummaryFilename(exportDate, ExportFormat.CSV.value)

        filePath = os.path.join(exportDirectory, filename)

        # Fetch all data
        with db.connect() as conn:
            statistics = fetchStatistics(conn, profileIds)
            recommendations = fetchRecommendations(conn, profileIds)
            alerts = fetchAlerts(conn, profileIds)

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
    db: Any,
    exportDirectory: str,
    exportDate: datetime | None = None,
    profileIds: list[str] | None = None,
    filename: str | None = None
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
        db: Database instance for data retrieval
        exportDirectory: Target directory for the JSON file
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
        ensureExportDirectory(exportDirectory)

        # Generate filename if not provided
        if not filename:
            filename = generateSummaryFilename(exportDate, ExportFormat.JSON.value)

        filePath = os.path.join(exportDirectory, filename)

        # Fetch all data
        with db.connect() as conn:
            statistics = fetchStatistics(conn, profileIds)
            recommendations = fetchRecommendations(conn, profileIds)
            alerts = fetchAlerts(conn, profileIds)

        # Group by profile if multiple profiles selected
        statisticsByProfile: dict[str, list[dict[str, Any]]] = {}
        for stat in statistics:
            profileId = stat.get('profile_id') or 'unknown'
            if profileId not in statisticsByProfile:
                statisticsByProfile[profileId] = []
            statisticsByProfile[profileId].append(stat)

        recommendationsByProfile: dict[str, list[dict[str, Any]]] = {}
        for rec in recommendations:
            profileId = rec.get('profile_id') or 'unknown'
            if profileId not in recommendationsByProfile:
                recommendationsByProfile[profileId] = []
            recommendationsByProfile[profileId].append(rec)

        alertsByProfile: dict[str, list[dict[str, Any]]] = {}
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
