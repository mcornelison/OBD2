################################################################################
# File Name: __init__.py
# Purpose/Description: Public API for the server-side analytics package.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-158 — re-export
#               |              | basic analytics functions and result types
# ================================================================================
################################################################################

"""
Server-side analytics package.

Two layers:

* :mod:`src.server.analytics.basic` — per-drive statistics and
  new-vs-historical comparison. Implemented in US-158.
* :mod:`src.server.analytics.advanced` — trends, correlations, and anomaly
  detection. Deferred to US-159.

Shared pieces live in:

* :mod:`src.server.analytics.helpers` — pure-math helpers, no DB access.
* :mod:`src.server.analytics.types` — result dataclasses and enums.
"""

from __future__ import annotations

from src.server.analytics.basic import (
    compareDriveToHistory,
    computeDriveStatistics,
)
from src.server.analytics.helpers import (
    classifyDeviation,
    computeBasicStats,
)
from src.server.analytics.types import (
    BasicStats,
    ComparisonStatus,
    DriveStatistics,
    ParameterComparison,
)

__all__ = [
    "BasicStats",
    "ComparisonStatus",
    "DriveStatistics",
    "ParameterComparison",
    "classifyDeviation",
    "compareDriveToHistory",
    "computeBasicStats",
    "computeDriveStatistics",
]
