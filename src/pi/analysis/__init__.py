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
    from pi.analysis import StatisticsEngine
    from common.analysis.types import ParameterStatistics

    # Create engine with database and config
    engine = StatisticsEngine(database, config)

    # Calculate statistics for all parameters
    results = engine.calculateStatistics(profileId='daily')

    # Or use helper functions
    from pi.analysis import createStatisticsEngineFromConfig, getStatisticsSummary
"""

# Pure calculation functions (shared, lives in common.analysis)
from common.analysis.calculations import (
    calculateMean,
    calculateMode,
    calculateOutlierBounds,
    calculateParameterStatistics,
    calculateStandardDeviation,
)

# Exceptions (shared, lives in common.analysis)
from common.analysis.exceptions import (
    InsufficientDataError,
    StatisticsCalculationError,
    StatisticsError,
    StatisticsStorageError,
)

# Types (shared, lives in common.analysis)
from common.analysis.types import (
    AnalysisResult,
    AnalysisState,
    EngineStats,
    ParameterStatistics,
)

# Engine class
from .engine import StatisticsEngine

# Helpers
from .helpers import (
    calculateStatisticsForDrive,
    clearStatisticsForProfile,
    createStatisticsEngineFromConfig,
    getAnalysisHistory,
    getAnalyzedParameterCount,
    getLatestAnalysisDate,
    getStatisticsSummary,
    isStatisticsAvailable,
)

# Profile statistics
from .profile_statistics import (
    SIGNIFICANCE_THRESHOLD,
    ParameterComparison,
    ProfileComparison,
    ProfileComparisonResult,
    ProfileStatisticsError,
    ProfileStatisticsManager,
    ProfileStatisticsReport,
    compareProfiles,
    createProfileStatisticsManager,
    generateProfileReport,
    getAllProfilesStatistics,
    getProfileStatisticsSummary,
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
