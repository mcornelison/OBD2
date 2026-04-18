################################################################################
# File Name: statistics_engine.py
# Purpose/Description: Statistics calculation engine for OBD-II realtime data
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-014
# 2026-01-22    | Ralph Agent  | Refactored to re-export from analysis subpackage (US-010)
# ================================================================================
################################################################################

"""
Statistics calculation engine for the Eclipse OBD-II Performance Monitoring System.

This module re-exports from analysis subpackages for backward compatibility.
New code should import directly from pi.analysis or common.analysis:

    from pi.analysis import StatisticsEngine
    from common.analysis.types import ParameterStatistics

Provides:
- Statistical analysis of logged OBD-II parameters
- Threaded/scheduled analysis execution
- Calculation of max, min, avg, mode, std_1, std_2, outliers
- Storage of results in statistics table
- Profile-specific statistical analysis

Usage:
    from obd.statistics_engine import StatisticsEngine, ParameterStatistics

    # Create engine with database and config
    engine = StatisticsEngine(database, config)

    # Calculate statistics for all parameters
    results = engine.calculateStatistics(profileId='daily')

    # Schedule analysis to run after drive ends
    engine.scheduleAnalysis(delaySeconds=0)

    # Get statistics for a specific parameter
    stats = engine.getParameterStatistics('RPM', profileId='daily')
"""

# Re-export all public symbols from the analysis subpackages
from common.analysis.calculations import (
    calculateMean,
    calculateMode,
    calculateOutlierBounds,
    calculateParameterStatistics,
    calculateStandardDeviation,
)
from common.analysis.exceptions import (
    InsufficientDataError,
    StatisticsCalculationError,
    StatisticsError,
    StatisticsStorageError,
)
from common.analysis.types import (
    AnalysisResult,
    AnalysisState,
    EngineStats,
    ParameterStatistics,
)
from pi.analysis import (
    # Engine class
    StatisticsEngine,
    calculateStatisticsForDrive,
    # Helpers
    createStatisticsEngineFromConfig,
    getStatisticsSummary,
)

__all__ = [
    # Types
    'AnalysisState',
    'ParameterStatistics',
    'AnalysisResult',
    'EngineStats',
    # Exceptions
    'StatisticsError',
    'StatisticsCalculationError',
    'StatisticsStorageError',
    'InsufficientDataError',
    # Calculation functions
    'calculateMean',
    'calculateMode',
    'calculateStandardDeviation',
    'calculateOutlierBounds',
    'calculateParameterStatistics',
    # Engine class
    'StatisticsEngine',
    # Helpers
    'createStatisticsEngineFromConfig',
    'calculateStatisticsForDrive',
    'getStatisticsSummary',
]
