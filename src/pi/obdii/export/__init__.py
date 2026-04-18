################################################################################
# File Name: __init__.py
# Purpose/Description: Export subpackage for data export functionality
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-04-14    | Sweep 5      | Populated with data_exporter.py split (task 4)
# ================================================================================
################################################################################
"""
Export Subpackage.

This subpackage contains data export components:
- types: exceptions, ExportFormat, ExportResult, SummaryExportResult
- realtime: realtime data CSV/JSON exporters
- summary_fetchers: DB readers for statistics/recommendations/alerts
- summary: summary CSV/JSON exporters
- exporter: DataExporter class facade
- helpers: convenience module-level functions
"""

from obd.export.exporter import DataExporter
from obd.export.helpers import (
    createExporterFromConfig,
    exportRealtimeDataToCsv,
    exportRealtimeDataToJson,
    exportSummaryReport,
)
from obd.export.types import (
    CSV_COLUMNS,
    DEFAULT_EXPORT_DIRECTORY,
    SUMMARY_ALERTS_COLUMNS,
    SUMMARY_RECOMMENDATIONS_COLUMNS,
    SUMMARY_STATISTICS_COLUMNS,
    DataExportError,
    ExportDirectoryError,
    ExportFormat,
    ExportResult,
    InvalidDateRangeError,
    SummaryExportResult,
)

__all__ = [
    'CSV_COLUMNS',
    'DEFAULT_EXPORT_DIRECTORY',
    'SUMMARY_ALERTS_COLUMNS',
    'SUMMARY_RECOMMENDATIONS_COLUMNS',
    'SUMMARY_STATISTICS_COLUMNS',
    'DataExportError',
    'DataExporter',
    'ExportDirectoryError',
    'ExportFormat',
    'ExportResult',
    'InvalidDateRangeError',
    'SummaryExportResult',
    'createExporterFromConfig',
    'exportRealtimeDataToCsv',
    'exportRealtimeDataToJson',
    'exportSummaryReport',
]
