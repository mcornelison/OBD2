################################################################################
# File Name: calibration_comparator.py
# Purpose/Description: Calibration session comparison tool for sensor validation
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-032
# ================================================================================
################################################################################

"""
Calibration session comparison module.

Provides tools for comparing 2+ calibration sessions to validate sensor accuracy
and identify parameter drift. Generates side-by-side statistics for each parameter
across sessions and highlights significant differences (>10% variance).

Key features:
- Compare 2 or more calibration sessions
- Generate side-by-side statistics (min, max, avg, stddev) for each parameter
- Highlight significant differences (>10% variance threshold)
- Export comparison reports to CSV and JSON formats

Usage:
    from obd.calibration_comparator import CalibrationComparator

    comparator = CalibrationComparator(database=db)

    # Compare sessions
    result = comparator.compareSessions([session1_id, session2_id, session3_id])

    # Check significant differences
    for paramName, paramResult in result.parameterResults.items():
        if paramResult.isSignificant:
            print(f"{paramName}: {paramResult.variancePercent:.1f}% variance")

    # Export comparison report
    exportResult = comparator.exportComparison(
        sessionIds=[session1_id, session2_id],
        format='json',
        exportDirectory='./exports/'
    )
"""

import csv
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Significance threshold for variance detection (10%)
SIGNIFICANCE_THRESHOLD = 10.0


# =============================================================================
# Exceptions
# =============================================================================

class CalibrationComparisonError(Exception):
    """Base exception for calibration comparison errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class ParameterSessionStats:
    """
    Statistics for a single parameter within a single session.

    Attributes:
        parameterName: Name of the OBD-II parameter
        sessionId: ID of the calibration session
        count: Number of readings
        min: Minimum value
        max: Maximum value
        avg: Average value
        stdDev: Standard deviation
    """
    parameterName: str
    sessionId: int
    count: int = 0
    min: Optional[float] = None
    max: Optional[float] = None
    avg: Optional[float] = None
    stdDev: Optional[float] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'sessionId': self.sessionId,
            'count': self.count,
            'min': self.min,
            'max': self.max,
            'avg': self.avg,
            'stdDev': self.stdDev,
        }


@dataclass
class SessionComparisonResult:
    """
    Comparison result for a single parameter across multiple sessions.

    Attributes:
        parameterName: Name of the compared parameter
        sessionStats: Dictionary mapping session ID to statistics
        variancePercent: Maximum variance percentage across sessions
        isSignificant: Whether variance exceeds significance threshold (>10%)
        description: Human-readable description of the difference
    """
    parameterName: str
    sessionStats: Dict[int, ParameterSessionStats] = field(default_factory=dict)
    variancePercent: float = 0.0
    isSignificant: bool = False
    description: str = ''

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'sessionStats': {
                str(sessionId): stats.toDict()
                for sessionId, stats in self.sessionStats.items()
            },
            'variancePercent': self.variancePercent,
            'isSignificant': self.isSignificant,
            'description': self.description,
        }


@dataclass
class CalibrationSessionComparison:
    """
    Complete comparison result for multiple calibration sessions.

    Attributes:
        sessionIds: List of compared session IDs
        comparisonDate: When the comparison was performed
        parameterResults: Dictionary of parameter name to comparison result
        significantCount: Number of parameters with significant variance
        totalParameters: Total number of parameters compared
        commonParameters: List of parameters common to all sessions
    """
    sessionIds: List[int]
    comparisonDate: datetime
    parameterResults: Dict[str, SessionComparisonResult] = field(default_factory=dict)
    significantCount: int = 0
    totalParameters: int = 0
    commonParameters: List[str] = field(default_factory=list)

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'sessionIds': self.sessionIds,
            'comparisonDate': self.comparisonDate.isoformat() if self.comparisonDate else None,
            'parameterResults': {
                name: result.toDict()
                for name, result in self.parameterResults.items()
            },
            'significantCount': self.significantCount,
            'totalParameters': self.totalParameters,
            'commonParameters': self.commonParameters,
        }


@dataclass
class ComparisonExportResult:
    """
    Result of a comparison export operation.

    Attributes:
        success: Whether export completed successfully
        filePath: Path to exported file (if successful)
        format: Export format used ('csv' or 'json')
        sessionIds: IDs of compared sessions
        executionTimeMs: Time taken in milliseconds
        errorMessage: Error message (if failed)
    """
    success: bool
    filePath: Optional[str] = None
    format: Optional[str] = None
    sessionIds: List[int] = field(default_factory=list)
    executionTimeMs: int = 0
    errorMessage: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'success': self.success,
            'filePath': self.filePath,
            'format': self.format,
            'sessionIds': self.sessionIds,
            'executionTimeMs': self.executionTimeMs,
            'errorMessage': self.errorMessage,
        }


# =============================================================================
# CalibrationComparator Class
# =============================================================================

class CalibrationComparator:
    """
    Compares calibration sessions to identify parameter drift and validate accuracy.

    Supports comparing 2 or more sessions, generating side-by-side statistics,
    highlighting significant differences (>10% variance), and exporting reports.

    Attributes:
        database: ObdDatabase instance for data access
        config: Optional configuration dictionary

    Example:
        comparator = CalibrationComparator(database=db)

        # Compare two sessions
        result = comparator.compareSessions([1, 2])

        # Export comparison
        exportResult = comparator.exportComparison(
            sessionIds=[1, 2],
            format='json',
            exportDirectory='./exports/'
        )
    """

    def __init__(
        self,
        database: Any,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize CalibrationComparator.

        Args:
            database: ObdDatabase instance for data access
            config: Optional configuration dictionary
        """
        self.database = database
        self.config = config or {}

        # Load significance threshold from config (default 10%)
        calibConfig = self.config.get('calibration', {})
        self._significanceThreshold = calibConfig.get(
            'significanceThreshold',
            SIGNIFICANCE_THRESHOLD
        )

    def compareSessions(
        self,
        sessionIds: List[int]
    ) -> CalibrationSessionComparison:
        """
        Compare multiple calibration sessions.

        Generates side-by-side statistics for each parameter that appears in
        all sessions, and identifies significant differences (>10% variance).

        Args:
            sessionIds: List of session IDs to compare (minimum 2)

        Returns:
            CalibrationSessionComparison with detailed comparison results

        Raises:
            CalibrationComparisonError: If fewer than 2 sessions or sessions not found
        """
        # Validate input
        if len(sessionIds) < 2:
            raise CalibrationComparisonError(
                "At least 2 session IDs required for comparison",
                details={'provided': len(sessionIds)}
            )

        comparisonDate = datetime.now()

        logger.info(f"Comparing {len(sessionIds)} calibration sessions: {sessionIds}")

        # Validate sessions exist
        self._validateSessionsExist(sessionIds)

        # Get statistics for each session
        allSessionStats: Dict[int, Dict[str, ParameterSessionStats]] = {}
        for sessionId in sessionIds:
            stats = self.getSessionStatistics(sessionId)
            if stats:
                allSessionStats[sessionId] = stats

        if len(allSessionStats) < 2:
            raise CalibrationComparisonError(
                "Could not retrieve statistics for at least 2 sessions",
                details={'sessionsWithStats': list(allSessionStats.keys())}
            )

        # Find common parameters across all sessions
        parameterSets = [set(stats.keys()) for stats in allSessionStats.values()]
        commonParameters = list(set.intersection(*parameterSets))
        commonParameters.sort()

        # Create comparison result
        comparison = CalibrationSessionComparison(
            sessionIds=sessionIds,
            comparisonDate=comparisonDate,
            commonParameters=commonParameters,
            totalParameters=len(commonParameters)
        )

        significantCount = 0

        # Compare each common parameter
        for paramName in commonParameters:
            sessionStatsForParam: Dict[int, ParameterSessionStats] = {}
            avgValues: List[float] = []

            for sessionId, sessionStats in allSessionStats.items():
                paramStats = sessionStats.get(paramName)
                if paramStats:
                    sessionStatsForParam[sessionId] = paramStats
                    if paramStats.avg is not None:
                        avgValues.append(paramStats.avg)

            # Calculate variance across sessions
            variancePercent = self._calculateMaxVariance(avgValues)
            isSignificant = abs(variancePercent) > self._significanceThreshold

            if isSignificant:
                significantCount += 1

            # Generate description
            description = self._generateDescription(
                paramName, avgValues, variancePercent, isSignificant
            )

            comparison.parameterResults[paramName] = SessionComparisonResult(
                parameterName=paramName,
                sessionStats=sessionStatsForParam,
                variancePercent=variancePercent,
                isSignificant=isSignificant,
                description=description
            )

        comparison.significantCount = significantCount

        logger.info(
            f"Comparison complete | sessions={len(sessionIds)} | "
            f"parameters={len(commonParameters)} | significant={significantCount}"
        )

        return comparison

    def getSessionStatistics(
        self,
        sessionId: int
    ) -> Dict[str, ParameterSessionStats]:
        """
        Get statistics for all parameters in a calibration session.

        Args:
            sessionId: Session ID to retrieve statistics for

        Returns:
            Dictionary mapping parameter names to their statistics
        """
        stats: Dict[str, ParameterSessionStats] = {}

        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()

                # Get statistics per parameter using SQL aggregates
                cursor.execute(
                    """
                    SELECT
                        parameter_name,
                        COUNT(*) as count,
                        MIN(value) as min_val,
                        MAX(value) as max_val,
                        AVG(value) as avg_val
                    FROM calibration_data
                    WHERE session_id = ?
                    AND value IS NOT NULL
                    GROUP BY parameter_name
                    """,
                    (sessionId,)
                )

                rows = cursor.fetchall()

                for row in rows:
                    paramName = row['parameter_name'] if hasattr(row, '__getitem__') else row[0]
                    count = row['count'] if hasattr(row, '__getitem__') else row[1]
                    minVal = row['min_val'] if hasattr(row, '__getitem__') else row[2]
                    maxVal = row['max_val'] if hasattr(row, '__getitem__') else row[3]
                    avgVal = row['avg_val'] if hasattr(row, '__getitem__') else row[4]

                    # Calculate standard deviation separately
                    stdDev = self._calculateStdDev(sessionId, paramName, avgVal)

                    stats[paramName] = ParameterSessionStats(
                        parameterName=paramName,
                        sessionId=sessionId,
                        count=count,
                        min=minVal,
                        max=maxVal,
                        avg=avgVal,
                        stdDev=stdDev
                    )

        except Exception as e:
            logger.error(f"Failed to get statistics for session {sessionId}: {e}")

        return stats

    def exportComparison(
        self,
        sessionIds: List[int],
        format: str = 'csv',
        exportDirectory: str = './exports/',
        filename: Optional[str] = None
    ) -> ComparisonExportResult:
        """
        Export a comparison report to CSV or JSON file.

        Args:
            sessionIds: List of session IDs to compare
            format: Export format ('csv' or 'json')
            exportDirectory: Directory to save export file
            filename: Optional custom filename

        Returns:
            ComparisonExportResult with export details
        """
        startTimeMs = time.time() * 1000
        formatLower = format.lower()

        logger.info(f"Starting {formatLower.upper()} export for comparison of sessions {sessionIds}")

        try:
            # Perform comparison
            comparison = self.compareSessions(sessionIds)

            # Ensure export directory exists
            Path(exportDirectory).mkdir(parents=True, exist_ok=True)

            # Generate filename if not provided
            if not filename:
                dateStr = datetime.now().strftime('%Y-%m-%d')
                sessionStr = '_'.join(str(s) for s in sessionIds)
                extension = formatLower
                filename = f'calibration_comparison_{sessionStr}_{dateStr}.{extension}'

            filePath = os.path.join(exportDirectory, filename)

            if formatLower == 'csv':
                self._exportComparisonToCsv(comparison, filePath)
            elif formatLower == 'json':
                self._exportComparisonToJson(comparison, filePath)
            else:
                return ComparisonExportResult(
                    success=False,
                    sessionIds=sessionIds,
                    format=formatLower,
                    errorMessage=f"Unsupported format: {format}"
                )

            executionTimeMs = int(time.time() * 1000 - startTimeMs)

            logger.info(
                f"Export complete: {len(comparison.parameterResults)} parameters "
                f"to {filePath} in {executionTimeMs}ms"
            )

            return ComparisonExportResult(
                success=True,
                filePath=filePath,
                format=formatLower,
                sessionIds=sessionIds,
                executionTimeMs=executionTimeMs
            )

        except CalibrationComparisonError as e:
            executionTimeMs = int(time.time() * 1000 - startTimeMs)
            return ComparisonExportResult(
                success=False,
                sessionIds=sessionIds,
                format=formatLower,
                executionTimeMs=executionTimeMs,
                errorMessage=e.message
            )
        except Exception as e:
            executionTimeMs = int(time.time() * 1000 - startTimeMs)
            logger.error(f"Export failed: {e}")

            return ComparisonExportResult(
                success=False,
                sessionIds=sessionIds,
                format=formatLower,
                executionTimeMs=executionTimeMs,
                errorMessage=str(e)
            )

    def _validateSessionsExist(self, sessionIds: List[int]) -> None:
        """
        Validate that all session IDs exist in the database.

        Args:
            sessionIds: List of session IDs to validate

        Raises:
            CalibrationComparisonError: If any session is not found
        """
        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()

                for sessionId in sessionIds:
                    cursor.execute(
                        "SELECT session_id FROM calibration_sessions WHERE session_id = ?",
                        (sessionId,)
                    )
                    if cursor.fetchone() is None:
                        raise CalibrationComparisonError(
                            f"Session {sessionId} not found",
                            details={'sessionId': sessionId}
                        )

        except CalibrationComparisonError:
            raise
        except Exception as e:
            raise CalibrationComparisonError(
                f"Failed to validate sessions: {e}",
                details={'sessionIds': sessionIds, 'error': str(e)}
            )

    def _calculateStdDev(
        self,
        sessionId: int,
        parameterName: str,
        avg: Optional[float]
    ) -> Optional[float]:
        """
        Calculate standard deviation for a parameter in a session.

        Args:
            sessionId: Session ID
            parameterName: Parameter name
            avg: Pre-calculated average value

        Returns:
            Standard deviation or None if cannot be calculated
        """
        if avg is None:
            return None

        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()

                # Get all values for variance calculation
                cursor.execute(
                    """
                    SELECT value FROM calibration_data
                    WHERE session_id = ? AND parameter_name = ? AND value IS NOT NULL
                    """,
                    (sessionId, parameterName)
                )

                values = [row[0] for row in cursor.fetchall()]

                if len(values) < 2:
                    return 0.0

                # Calculate variance
                variance = sum((v - avg) ** 2 for v in values) / len(values)
                return math.sqrt(variance)

        except Exception as e:
            logger.warning(f"Failed to calculate stddev for {parameterName}: {e}")
            return None

    def _calculateMaxVariance(self, values: List[float]) -> float:
        """
        Calculate the maximum variance percentage across a list of values.

        Uses min-max range comparison to determine variance. This approach
        calculates how much the maximum value differs from the minimum value
        as a percentage of the minimum, which is appropriate for detecting
        sensor drift across calibration sessions.

        Args:
            values: List of values to compare

        Returns:
            Maximum variance percentage
        """
        if not values or len(values) < 2:
            return 0.0

        minVal = min(values)
        maxVal = max(values)

        # All values are the same
        if minVal == maxVal:
            return 0.0

        # Handle zero minimum value
        if minVal == 0:
            # If min is 0, use max as base
            if maxVal == 0:
                return 0.0
            # Use small offset to avoid division by zero
            minVal = 0.0001

        # Calculate percentage difference from min to max
        variance = ((maxVal - minVal) / abs(minVal)) * 100
        return round(variance, 2)

    def _generateDescription(
        self,
        paramName: str,
        avgValues: List[float],
        variancePercent: float,
        isSignificant: bool
    ) -> str:
        """
        Generate a human-readable description of the comparison.

        Args:
            paramName: Parameter name
            avgValues: List of average values from each session
            variancePercent: Calculated variance percentage
            isSignificant: Whether variance is significant

        Returns:
            Human-readable description
        """
        if not avgValues:
            return f"{paramName}: No data available"

        if not isSignificant:
            return f"{paramName}: Within normal range ({variancePercent:.1f}% variance)"

        minAvg = min(avgValues)
        maxAvg = max(avgValues)

        return (
            f"{paramName}: Significant variance detected ({variancePercent:.1f}%) - "
            f"range {minAvg:.2f} to {maxAvg:.2f}"
        )

    def _exportComparisonToCsv(
        self,
        comparison: CalibrationSessionComparison,
        filePath: str
    ) -> None:
        """
        Export comparison results to CSV file.

        Args:
            comparison: CalibrationSessionComparison to export
            filePath: Path to output file
        """
        # Build headers dynamically based on sessions
        headers = ['parameter_name', 'variance_percent', 'is_significant']

        # Add columns for each session's stats
        for sessionId in comparison.sessionIds:
            headers.extend([
                f'session_{sessionId}_count',
                f'session_{sessionId}_min',
                f'session_{sessionId}_max',
                f'session_{sessionId}_avg',
                f'session_{sessionId}_stddev',
            ])

        # Write CSV with proper Windows handling
        with open(filePath, 'w', newline='', encoding='utf-8') as csvFile:
            writer = csv.writer(csvFile)
            writer.writerow(headers)

            # Sort parameters by significance (significant first)
            sortedParams = sorted(
                comparison.parameterResults.items(),
                key=lambda x: (not x[1].isSignificant, x[0])
            )

            for paramName, result in sortedParams:
                row = [
                    paramName,
                    f'{result.variancePercent:.2f}',
                    'Yes' if result.isSignificant else 'No'
                ]

                # Add stats for each session
                for sessionId in comparison.sessionIds:
                    stats = result.sessionStats.get(sessionId)
                    if stats:
                        row.extend([
                            stats.count,
                            f'{stats.min:.4f}' if stats.min is not None else '',
                            f'{stats.max:.4f}' if stats.max is not None else '',
                            f'{stats.avg:.4f}' if stats.avg is not None else '',
                            f'{stats.stdDev:.4f}' if stats.stdDev is not None else '',
                        ])
                    else:
                        row.extend(['', '', '', '', ''])

                writer.writerow(row)

    def _exportComparisonToJson(
        self,
        comparison: CalibrationSessionComparison,
        filePath: str
    ) -> None:
        """
        Export comparison results to JSON file.

        Args:
            comparison: CalibrationSessionComparison to export
            filePath: Path to output file
        """
        exportData = {
            'metadata': {
                'sessionIds': comparison.sessionIds,
                'comparisonDate': comparison.comparisonDate.isoformat(),
                'totalParameters': comparison.totalParameters,
                'significantCount': comparison.significantCount,
                'significanceThreshold': self._significanceThreshold,
            },
            'results': []
        }

        # Sort parameters by significance
        sortedParams = sorted(
            comparison.parameterResults.items(),
            key=lambda x: (not x[1].isSignificant, x[0])
        )

        for paramName, result in sortedParams:
            paramData = {
                'parameterName': paramName,
                'variancePercent': result.variancePercent,
                'isSignificant': result.isSignificant,
                'description': result.description,
                'sessionStats': {}
            }

            for sessionId, stats in result.sessionStats.items():
                paramData['sessionStats'][str(sessionId)] = {
                    'count': stats.count,
                    'min': stats.min,
                    'max': stats.max,
                    'avg': stats.avg,
                    'stdDev': stats.stdDev,
                }

            exportData['results'].append(paramData)

        with open(filePath, 'w', encoding='utf-8') as jsonFile:
            json.dump(exportData, jsonFile, indent=2)


# =============================================================================
# Helper Functions
# =============================================================================

def createCalibrationComparatorFromConfig(
    database: Any,
    config: Dict[str, Any]
) -> CalibrationComparator:
    """
    Create a CalibrationComparator from configuration.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary

    Returns:
        Configured CalibrationComparator instance
    """
    return CalibrationComparator(database=database, config=config)


def compareCalibrationSessions(
    database: Any,
    sessionIds: List[int],
    config: Optional[Dict[str, Any]] = None
) -> CalibrationSessionComparison:
    """
    Compare calibration sessions (convenience function).

    Creates a temporary CalibrationComparator to perform the comparison.

    Args:
        database: ObdDatabase instance
        sessionIds: List of session IDs to compare
        config: Optional configuration dictionary

    Returns:
        CalibrationSessionComparison with detailed comparison results
    """
    comparator = CalibrationComparator(database=database, config=config)
    return comparator.compareSessions(sessionIds)


def exportComparisonReport(
    database: Any,
    sessionIds: List[int],
    format: str = 'csv',
    exportDirectory: str = './exports/',
    filename: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None
) -> ComparisonExportResult:
    """
    Export a calibration session comparison report (convenience function).

    Args:
        database: ObdDatabase instance
        sessionIds: List of session IDs to compare
        format: Export format ('csv' or 'json')
        exportDirectory: Directory to save export file
        filename: Optional custom filename
        config: Optional configuration dictionary

    Returns:
        ComparisonExportResult with export details
    """
    comparator = CalibrationComparator(database=database, config=config)
    return comparator.exportComparison(
        sessionIds=sessionIds,
        format=format,
        exportDirectory=exportDirectory,
        filename=filename
    )
