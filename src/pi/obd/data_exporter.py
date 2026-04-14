################################################################################
# File Name: data_exporter.py
# Purpose/Description: Backwards-compatible facade re-exporting the export subpackage API
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
# 2026-01-22    | Ralph Agent3  | Added summary export for US-029
# 2026-04-14    | Sweep 5       | Split into obd/export/ subpackage; file now a facade
# ================================================================================
################################################################################

"""
Data export module facade (legacy import path).

The implementation now lives in the `obd.export` subpackage:
- obd.export.types: exceptions, ExportFormat, ExportResult, SummaryExportResult
- obd.export.realtime: realtime data CSV/JSON exporters
- obd.export.summary_fetchers: DB readers for summary sections
- obd.export.summary: summary report CSV/JSON exporters
- obd.export.exporter: DataExporter class (the main facade)
- obd.export.helpers: convenience module-level functions

This file remains as a compatibility shim so existing imports continue to work:

    from obd.data_exporter import DataExporter, exportRealtimeDataToCsv

Prefer importing directly from `obd.export` in new code.
"""

from obd.export import (
    CSV_COLUMNS,
    DEFAULT_EXPORT_DIRECTORY,
    SUMMARY_ALERTS_COLUMNS,
    SUMMARY_RECOMMENDATIONS_COLUMNS,
    SUMMARY_STATISTICS_COLUMNS,
    DataExportError,
    DataExporter,
    ExportDirectoryError,
    ExportFormat,
    ExportResult,
    InvalidDateRangeError,
    SummaryExportResult,
    createExporterFromConfig,
    exportRealtimeDataToCsv,
    exportRealtimeDataToJson,
    exportSummaryReport,
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
