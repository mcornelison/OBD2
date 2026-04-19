################################################################################
# File Name: summary_fetchers.py
# Purpose/Description: Database fetchers for summary export sections (statistics, recommendations, alerts)
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
Database fetchers for the summary export subpackage.

Module-level functions that fetch pre-aggregated summary data from the DB:
- statistics: long-running stats from the statistics table
- recommendations: AI recommendations from ai_recommendations
- alerts: alert history from alert_log

Each function supports filtering by profile IDs and returns list[dict] rows
ready for serialization.
"""

from datetime import datetime
from typing import Any


def fetchStatistics(
    conn: Any,
    profileIds: list[str] | None = None
) -> list[dict[str, Any]]:
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
    params: list[Any] = []

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


def fetchRecommendations(
    conn: Any,
    profileIds: list[str] | None = None,
    includeAllOrNonDuplicatesOnly: bool = False
) -> list[dict[str, Any]]:
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
    params: list[Any] = []
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


def fetchAlerts(
    conn: Any,
    profileIds: list[str] | None = None
) -> list[dict[str, Any]]:
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
    params: list[Any] = []

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


def generateSummaryFilename(
    exportDate: datetime,
    extension: str = 'csv'
) -> str:
    """
    Generate summary export filename with date.

    Args:
        exportDate: Date for the summary
        extension: File extension ('csv' or 'json')

    Returns:
        Filename string (e.g., 'obd_summary_2026-01-22.csv')
    """
    dateStr = exportDate.strftime('%Y-%m-%d')
    return f'obd_summary_{dateStr}.{extension}'
