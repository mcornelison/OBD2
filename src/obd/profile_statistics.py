################################################################################
# File Name: profile_statistics.py
# Purpose/Description: Profile-specific statistics and cross-profile comparison
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-026
# 2026-01-22    | Ralph Agent  | Refactored to re-export from analysis subpackage (US-010)
# ================================================================================
################################################################################

"""
Profile-specific statistics module for the Eclipse OBD-II Performance Monitoring System.

This module re-exports from obd.analysis subpackage for backward compatibility.
New code should import directly from obd.analysis:

    from obd.analysis import ProfileStatisticsManager, compareProfiles

Provides:
- Profile-filtered statistics retrieval
- Cross-profile statistics comparison
- Variance detection and significance analysis (>10% threshold)
- Comprehensive profile statistics reporting
- Report generation in serializable format

Usage:
    from obd.profile_statistics import ProfileStatisticsManager, compareProfiles

    # Create manager
    manager = ProfileStatisticsManager(database, config)

    # Get statistics for a single profile
    stats = manager.getStatisticsForProfile('daily')

    # Compare two profiles
    comparison = manager.compareProfiles('daily', 'performance')

    # Generate comprehensive report
    report = manager.generateReport(profileIds=['daily', 'performance', 'economy'])
"""

# Re-export all public symbols from the analysis subpackage
from obd.analysis import (
    # Types (from statistics engine)
    ParameterStatistics,
    AnalysisResult,
    # Engine (for backward compatibility)
    StatisticsEngine,
    # Helpers
    getStatisticsSummary,
    # Profile statistics types
    ProfileStatisticsError,
    ParameterComparison,
    ProfileComparison,
    ProfileComparisonResult,
    ProfileStatisticsReport,
    # Profile statistics manager
    ProfileStatisticsManager,
    # Profile statistics helpers
    createProfileStatisticsManager,
    compareProfiles,
    generateProfileReport,
    getProfileStatisticsSummary,
    getAllProfilesStatistics,
    # Constants
    SIGNIFICANCE_THRESHOLD,
)

__all__ = [
    # Types (from statistics engine)
    'ParameterStatistics',
    'AnalysisResult',
    # Engine (for backward compatibility)
    'StatisticsEngine',
    # Helpers
    'getStatisticsSummary',
    # Profile statistics types
    'ProfileStatisticsError',
    'ParameterComparison',
    'ProfileComparison',
    'ProfileComparisonResult',
    'ProfileStatisticsReport',
    # Profile statistics manager
    'ProfileStatisticsManager',
    # Profile statistics helpers
    'createProfileStatisticsManager',
    'compareProfiles',
    'generateProfileReport',
    'getProfileStatisticsSummary',
    'getAllProfilesStatistics',
    # Constants
    'SIGNIFICANCE_THRESHOLD',
]
