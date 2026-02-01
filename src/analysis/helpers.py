################################################################################
# File Name: helpers.py
# Purpose/Description: Factory and helper functions for the analysis subpackage
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-010 refactoring
# ================================================================================
################################################################################

"""
Factory and helper functions for the analysis subpackage.

Provides:
- createStatisticsEngineFromConfig: Factory function for StatisticsEngine
- calculateStatisticsForDrive: Calculate statistics for a specific drive session
- getStatisticsSummary: Get a summary of latest statistics for multiple parameters
- createProfileStatisticsManagerFromConfig: Factory for ProfileStatisticsManager

These helpers provide convenient factory patterns for class instantiation.
"""

import logging
from datetime import datetime
from typing import Any

from .engine import StatisticsEngine
from .types import AnalysisResult

logger = logging.getLogger(__name__)


# ================================================================================
# Factory Functions
# ================================================================================

def createStatisticsEngineFromConfig(
    database: Any,
    config: dict[str, Any]
) -> StatisticsEngine:
    """
    Create a StatisticsEngine from configuration.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary

    Returns:
        Configured StatisticsEngine instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        engine = createStatisticsEngineFromConfig(db, config)
    """
    return StatisticsEngine(database, config)


def calculateStatisticsForDrive(
    database: Any,
    config: dict[str, Any],
    profileId: str | None = None,
    startTime: datetime | None = None,
    endTime: datetime | None = None
) -> AnalysisResult:
    """
    Calculate statistics for a specific drive session.

    Convenience function for calculating statistics for data within a time range.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary
        profileId: Profile to analyze
        startTime: Start of time range
        endTime: End of time range

    Returns:
        AnalysisResult with calculated statistics
    """
    engine = StatisticsEngine(database, config)

    # Calculate analysis window if times provided
    analysisWindow = None
    if startTime and endTime:
        analysisWindow = endTime - startTime
    elif endTime:
        analysisWindow = datetime.now() - startTime if startTime else None

    return engine.calculateStatistics(
        profileId=profileId,
        analysisWindow=analysisWindow,
        storeResults=True
    )


def getStatisticsSummary(
    database: Any,
    profileId: str,
    parameterNames: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    """
    Get a summary of latest statistics for multiple parameters.

    Args:
        database: ObdDatabase instance
        profileId: Profile to get statistics for
        parameterNames: List of parameters (None for all)

    Returns:
        Dictionary mapping parameter names to their latest statistics
    """
    summary: dict[str, dict[str, Any]] = {}

    try:
        with database.connect() as conn:
            cursor = conn.cursor()

            if parameterNames:
                placeholders = ','.join('?' * len(parameterNames))
                cursor.execute(
                    f"""
                    SELECT s.*
                    FROM statistics s
                    INNER JOIN (
                        SELECT parameter_name, MAX(analysis_date) as max_date
                        FROM statistics
                        WHERE profile_id = ? AND parameter_name IN ({placeholders})
                        GROUP BY parameter_name
                    ) latest ON s.parameter_name = latest.parameter_name
                        AND s.analysis_date = latest.max_date
                    WHERE s.profile_id = ?
                    """,
                    [profileId] + parameterNames + [profileId]
                )
            else:
                cursor.execute(
                    """
                    SELECT s.*
                    FROM statistics s
                    INNER JOIN (
                        SELECT parameter_name, MAX(analysis_date) as max_date
                        FROM statistics
                        WHERE profile_id = ?
                        GROUP BY parameter_name
                    ) latest ON s.parameter_name = latest.parameter_name
                        AND s.analysis_date = latest.max_date
                    WHERE s.profile_id = ?
                    """,
                    (profileId, profileId)
                )

            for row in cursor.fetchall():
                summary[row['parameter_name']] = {
                    'max': row['max_value'],
                    'min': row['min_value'],
                    'avg': row['avg_value'],
                    'mode': row['mode_value'],
                    'std_1': row['std_1'],
                    'std_2': row['std_2'],
                    'outlier_min': row['outlier_min'],
                    'outlier_max': row['outlier_max'],
                    'sample_count': row['sample_count'],
                    'analysis_date': row['analysis_date']
                }

    except Exception as e:
        logger.error(f"Error getting statistics summary: {e}")

    return summary


def isStatisticsAvailable(database: Any, profileId: str) -> bool:
    """
    Check if statistics are available for a profile.

    Args:
        database: ObdDatabase instance
        profileId: Profile to check

    Returns:
        True if statistics exist for the profile
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as count FROM statistics WHERE profile_id = ?",
                (profileId,)
            )
            row = cursor.fetchone()
            return (row['count'] if row else 0) > 0
    except Exception as e:
        logger.warning(f"Error checking statistics availability: {e}")
        return False


def getLatestAnalysisDate(database: Any, profileId: str) -> datetime | None:
    """
    Get the date of the most recent analysis for a profile.

    Args:
        database: ObdDatabase instance
        profileId: Profile to check

    Returns:
        Datetime of latest analysis, or None if no analysis exists
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT MAX(analysis_date) as latest
                FROM statistics
                WHERE profile_id = ?
                """,
                (profileId,)
            )
            row = cursor.fetchone()
            return row['latest'] if row and row['latest'] else None
    except Exception as e:
        logger.warning(f"Error getting latest analysis date: {e}")
        return None


def getAnalyzedParameterCount(database: Any, profileId: str) -> int:
    """
    Get the count of distinct parameters that have been analyzed.

    Args:
        database: ObdDatabase instance
        profileId: Profile to check

    Returns:
        Number of distinct parameters with statistics
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(DISTINCT parameter_name) as count
                FROM statistics
                WHERE profile_id = ?
                """,
                (profileId,)
            )
            row = cursor.fetchone()
            return row['count'] if row else 0
    except Exception as e:
        logger.warning(f"Error counting analyzed parameters: {e}")
        return 0


def clearStatisticsForProfile(database: Any, profileId: str) -> int:
    """
    Clear all statistics for a profile.

    Args:
        database: ObdDatabase instance
        profileId: Profile to clear statistics for

    Returns:
        Number of records deleted
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM statistics WHERE profile_id = ?",
                (profileId,)
            )
            deleted = cursor.rowcount
            logger.info(f"Cleared {deleted} statistics records for profile '{profileId}'")
            return deleted
    except Exception as e:
        logger.error(f"Error clearing statistics: {e}")
        return 0


def getAnalysisHistory(
    database: Any,
    profileId: str,
    limit: int = 10
) -> list[dict[str, Any]]:
    """
    Get analysis history for a profile.

    Args:
        database: ObdDatabase instance
        profileId: Profile to get history for
        limit: Maximum number of analyses to return

    Returns:
        List of analysis summaries (date, parameter count, sample count)
    """
    history: list[dict[str, Any]] = []

    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT analysis_date,
                       COUNT(DISTINCT parameter_name) as parameter_count,
                       SUM(sample_count) as total_samples
                FROM statistics
                WHERE profile_id = ?
                GROUP BY analysis_date
                ORDER BY analysis_date DESC
                LIMIT ?
                """,
                (profileId, limit)
            )

            for row in cursor.fetchall():
                history.append({
                    'analysisDate': row['analysis_date'],
                    'parameterCount': row['parameter_count'],
                    'totalSamples': row['total_samples']
                })

    except Exception as e:
        logger.warning(f"Error getting analysis history: {e}")

    return history
