################################################################################
# File Name: types.py
# Purpose/Description: Shared types for data export subpackage (exceptions, enums, result dataclasses)
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
Shared types for the data export subpackage.

Provides:
- DataExportError, InvalidDateRangeError, ExportDirectoryError exceptions
- ExportFormat enum (CSV, JSON)
- ExportResult dataclass for realtime exports
- SummaryExportResult dataclass for summary exports
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

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

    def __init__(self, message: str, details: dict[str, Any] | None = None):
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
    filePath: str | None = None
    format: ExportFormat | None = None
    startDate: datetime | None = None
    endDate: datetime | None = None
    profileId: str | None = None
    parameters: list[str] | None = None
    executionTimeMs: int = 0
    errorMessage: str | None = None

    def toDict(self) -> dict[str, Any]:
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
    filePath: str | None = None
    format: ExportFormat | None = None
    exportDate: datetime | None = None
    profileIds: list[str] | None = None
    statisticsCount: int = 0
    recommendationsCount: int = 0
    alertsCount: int = 0
    executionTimeMs: int = 0
    errorMessage: str | None = None

    def toDict(self) -> dict[str, Any]:
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
