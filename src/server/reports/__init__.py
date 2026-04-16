################################################################################
# File Name: __init__.py
# Purpose/Description: Public API for the server-side reports package.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-160 — drive and
#               |              | trend report formatters + orchestrators
# ================================================================================
################################################################################

"""
Server-side report package.

Two layers:

* :mod:`src.server.reports.drive_report` — single-drive and all-drives
  reports (per-parameter stats table + historical comparison section).
* :mod:`src.server.reports.trend_report` — rolling trend report with
  direction arrows, delta over period, significance, and correlations.

Both modules expose *pure formatters* (take already-computed data, return a
string) and *orchestrators* (take a session + args, call analytics layer,
return a fully-assembled string).  Pure formatters are unit-tested without
any database dependency.
"""

from __future__ import annotations

from src.server.reports import drive_report, trend_report
from src.server.reports.drive_report import (
    buildAllDrivesReport,
    buildDriveReport,
    formatAllDrivesTable,
    formatDriveReport,
)
from src.server.reports.trend_report import (
    DEFAULT_TREND_PARAMETERS,
    buildTrendReport,
    classifyTrendSignificance,
    formatTrendReport,
    trendArrow,
)

__all__ = [
    "DEFAULT_TREND_PARAMETERS",
    "buildAllDrivesReport",
    "buildDriveReport",
    "buildTrendReport",
    "classifyTrendSignificance",
    "drive_report",
    "formatAllDrivesTable",
    "formatDriveReport",
    "formatTrendReport",
    "trend_report",
    "trendArrow",
]
