################################################################################
# File Name: __init__.py
# Purpose/Description: Analysis subpackage for statistics and data analysis
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | Added all exports for US-010 refactoring
# ================================================================================
################################################################################
"""
Analysis Subpackage.

This subpackage contains data analysis components:
- Statistics engine for parameter calculations
- Profile statistics comparison
- Pure calculation functions (mean, mode, std, outliers)

Usage:
    from analysis import StatisticsEngine, ParameterStatistics

    # Create engine with database and config
    engine = StatisticsEngine(database, config)

    # Calculate statistics for all parameters
    results = engine.calculateStatistics(profileId='daily')

    # Or use helper functions
    from analysis import createStatisticsEngineFromConfig, getStatisticsSummary
"""

# Types
from .types import (
    AnalysisState,
    ParameterStatistics,
    AnalysisResult,
    EngineStats,
)

# Exceptions
from .exceptions import (
    StatisticsError,
    StatisticsCalculationError,
    StatisticsStorageError,
    InsufficientDataError,
)

# Pure calculation functions
from .calculations import (
    calculateMean,
    calculateMode,
    calculateStandardDeviation,
    calculateOutlierBounds,
    calculateParameterStatistics,
)

# Engine class
from .engine import StatisticsEngine

# Helpers
from .helpers import (
    createStatisticsEngineFromConfig,
    calculateStatisticsForDrive,
    getStatisticsSummary,
    isStatisticsAvailable,
    getLatestAnalysisDate,
    getAnalyzedParameterCount,
    clearStatisticsForProfile,
    getAnalysisHistory,
)

# Profile statistics
from .profile_statistics import (
    ProfileStatisticsError,
    ParameterComparison,
    ProfileComparison,
    ProfileComparisonResult,
    ProfileStatisticsReport,
    ProfileStatisticsManager,
    createProfileStatisticsManager,
    compareProfiles,
    generateProfileReport,
    getProfileStatisticsSummary,
    getAllProfilesStatistics,
    SIGNIFICANCE_THRESHOLD,
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
    'isStatisticsAvailable',
    'getLatestAnalysisDate',
    'getAnalyzedParameterCount',
    'clearStatisticsForProfile',
    'getAnalysisHistory',
    # Profile statistics
    'ProfileStatisticsError',
    'ParameterComparison',
    'ProfileComparison',
    'ProfileComparisonResult',
    'ProfileStatisticsReport',
    'ProfileStatisticsManager',
    'createProfileStatisticsManager',
    'compareProfiles',
    'generateProfileReport',
    'getProfileStatisticsSummary',
    'getAllProfilesStatistics',
    'SIGNIFICANCE_THRESHOLD',
]
