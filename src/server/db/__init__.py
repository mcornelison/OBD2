################################################################################
# File Name: __init__.py
# Purpose/Description: Server database package — models and async connection.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | US-CMP-003 — public API exports for db package
# ================================================================================
################################################################################

"""
Server database package.

Re-exports key symbols from :mod:`models` and :mod:`connection` so consumers
can write::

    from src.server.db import Base, RealtimeData, createAsyncEngine
"""

from __future__ import annotations

from src.server.db.connection import createAsyncEngine, getAsyncSession
from src.server.db.models import (
    AiRecommendation,
    AlertLog,
    AnalysisHistory,
    AnalysisRecommendation,
    AnomalyLog,
    Base,
    Baseline,
    CalibrationSession,
    ConnectionLog,
    Device,
    DriveStatistic,
    DriveSummary,
    Profile,
    RealtimeData,
    Statistic,
    SyncHistory,
    TrendSnapshot,
    VehicleInfo,
)

__all__ = [
    # Base
    "Base",
    # Synced
    "RealtimeData",
    "Statistic",
    "Profile",
    "VehicleInfo",
    "AiRecommendation",
    "ConnectionLog",
    "AlertLog",
    "CalibrationSession",
    # Server-only
    "SyncHistory",
    "AnalysisHistory",
    "AnalysisRecommendation",
    "Device",
    # Analytics
    "DriveSummary",
    "DriveStatistic",
    "TrendSnapshot",
    "AnomalyLog",
    "Baseline",
    # Connection
    "createAsyncEngine",
    "getAsyncSession",
]
