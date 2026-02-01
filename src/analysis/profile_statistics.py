################################################################################
# File Name: profile_statistics.py
# Purpose/Description: Profile-specific statistics and cross-profile comparison
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Moved from obd/profile_statistics.py (US-010)
# ================================================================================
################################################################################

"""
Profile-specific statistics module for the Eclipse OBD-II Performance Monitoring System.

Provides:
- Profile-filtered statistics retrieval
- Cross-profile statistics comparison
- Variance detection and significance analysis (>10% threshold)
- Comprehensive profile statistics reporting
- Report generation in serializable format

This module builds on StatisticsEngine to provide profile-specific analysis
and comparison features, allowing users to compare driving behavior across
different profiles (e.g., daily driving vs track day).

Usage:
    from analysis import ProfileStatisticsManager, compareProfiles

    # Create manager
    manager = ProfileStatisticsManager(database, config)

    # Get statistics for a single profile
    stats = manager.getStatisticsForProfile('daily')

    # Compare two profiles
    comparison = manager.compareProfiles('daily', 'performance')

    # Generate comprehensive report
    report = manager.generateReport(profileIds=['daily', 'performance', 'economy'])
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from typing import Any

from .engine import StatisticsEngine
from .helpers import getStatisticsSummary

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Significance threshold for variance detection (10%)
SIGNIFICANCE_THRESHOLD = 10.0


# ================================================================================
# Custom Exceptions
# ================================================================================

class ProfileStatisticsError(Exception):
    """Base exception for profile statistics-related errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class ParameterComparison:
    """
    Comparison of a single parameter across two profiles.

    Attributes:
        parameterName: Name of the compared parameter
        profile1Value: Average value from profile 1
        profile2Value: Average value from profile 2
        profile1Max: Maximum value from profile 1
        profile2Max: Maximum value from profile 2
        profile1Min: Minimum value from profile 1
        profile2Min: Minimum value from profile 2
        avgVariancePercent: Percentage variance in average values
        maxVariancePercent: Percentage variance in maximum values
        isSignificant: Whether variance exceeds significance threshold (>10%)
    """
    parameterName: str
    profile1Value: float
    profile2Value: float
    profile1Max: float | None = None
    profile2Max: float | None = None
    profile1Min: float | None = None
    profile2Min: float | None = None
    avgVariancePercent: float = 0.0
    maxVariancePercent: float = 0.0
    isSignificant: bool = False

    def toDict(self) -> dict[str, Any]:
        """Convert comparison to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'profile1Value': self.profile1Value,
            'profile2Value': self.profile2Value,
            'profile1Max': self.profile1Max,
            'profile2Max': self.profile2Max,
            'profile1Min': self.profile1Min,
            'profile2Min': self.profile2Min,
            'avgVariancePercent': self.avgVariancePercent,
            'maxVariancePercent': self.maxVariancePercent,
            'isSignificant': self.isSignificant,
        }


@dataclass
class ProfileComparison:
    """
    Comparison result between two profiles.

    Attributes:
        profileId1: First profile ID
        profileId2: Second profile ID
        comparisonDate: When the comparison was performed
        parameterComparisons: Dictionary of parameter comparisons
        commonParameters: List of parameters common to both profiles
        significantCount: Number of parameters with significant variance
    """
    profileId1: str
    profileId2: str
    comparisonDate: datetime
    parameterComparisons: dict[str, ParameterComparison] = field(default_factory=dict)
    commonParameters: list[str] = field(default_factory=list)
    significantCount: int = 0

    def toDict(self) -> dict[str, Any]:
        """Convert comparison to dictionary for serialization."""
        return {
            'profileId1': self.profileId1,
            'profileId2': self.profileId2,
            'comparisonDate': self.comparisonDate.isoformat() if self.comparisonDate else None,
            'parameterComparisons': {
                name: comp.toDict()
                for name, comp in self.parameterComparisons.items()
            },
            'commonParameters': self.commonParameters,
            'significantCount': self.significantCount,
        }


@dataclass
class ProfileComparisonResult:
    """
    Summary of a comparison result for reporting.

    Attributes:
        parameterName: Name of the parameter
        profileId1: First profile ID
        profileId2: Second profile ID
        variancePercent: Percentage variance
        description: Human-readable description
    """
    parameterName: str
    profileId1: str
    profileId2: str
    variancePercent: float
    description: str = ''

    def toDict(self) -> dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'profileId1': self.profileId1,
            'profileId2': self.profileId2,
            'variancePercent': self.variancePercent,
            'description': self.description,
        }


@dataclass
class ProfileStatisticsReport:
    """
    Comprehensive statistics report for one or more profiles.

    Attributes:
        reportDate: When the report was generated
        profileIds: List of profiles included in the report
        profileStatistics: Dictionary of profile ID to parameter statistics
        comparisons: List of profile comparisons
        significantDifferences: List of significant differences found
        totalSamples: Total samples across all profiles
        totalParameters: Total unique parameters across all profiles
    """
    reportDate: datetime
    profileIds: list[str]
    profileStatistics: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    comparisons: list[ProfileComparison] = field(default_factory=list)
    significantDifferences: list[ProfileComparisonResult] = field(default_factory=list)
    totalSamples: int = 0
    totalParameters: int = 0

    def toDict(self) -> dict[str, Any]:
        """Convert report to dictionary for serialization."""
        return {
            'reportDate': self.reportDate.isoformat() if self.reportDate else None,
            'profileIds': self.profileIds,
            'profileStatistics': self.profileStatistics,
            'comparisons': [comp.toDict() for comp in self.comparisons],
            'significantDifferences': [diff.toDict() for diff in self.significantDifferences],
            'totalSamples': self.totalSamples,
            'totalParameters': self.totalParameters,
        }


# ================================================================================
# Profile Statistics Manager Class
# ================================================================================

class ProfileStatisticsManager:
    """
    Manages profile-specific statistics and comparisons.

    Provides methods for:
    - Retrieving statistics filtered by profile
    - Comparing statistics across profiles
    - Detecting significant variances (>10%)
    - Generating comprehensive reports

    Attributes:
        database: ObdDatabase instance for data access
        config: Configuration dictionary
        statisticsEngine: Optional StatisticsEngine for calculations

    Example:
        manager = ProfileStatisticsManager(database, config)

        # Get single profile stats
        dailyStats = manager.getStatisticsForProfile('daily')

        # Compare profiles
        comparison = manager.compareProfiles('daily', 'performance')

        # Generate report
        report = manager.generateReport(['daily', 'performance', 'economy'])
    """

    def __init__(
        self,
        database: Any,
        config: dict[str, Any],
        statisticsEngine: StatisticsEngine | None = None
    ):
        """
        Initialize the profile statistics manager.

        Args:
            database: ObdDatabase instance for data access
            config: Configuration dictionary
            statisticsEngine: Optional StatisticsEngine (created if not provided)
        """
        self.database = database
        self.config = config
        self.statisticsEngine = statisticsEngine or StatisticsEngine(database, config)

    # ================================================================================
    # Profile Statistics Retrieval
    # ================================================================================

    def getStatisticsForProfile(
        self,
        profileId: str,
        parameterNames: list[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        """
        Get statistics for a specific profile.

        Args:
            profileId: Profile ID to get statistics for
            parameterNames: Optional list of parameter names to filter

        Returns:
            Dictionary mapping parameter names to their statistics
        """
        return getStatisticsSummary(self.database, profileId, parameterNames)

    def getAllProfileStatistics(self) -> dict[str, dict[str, dict[str, Any]]]:
        """
        Get statistics for all profiles.

        Returns:
            Dictionary mapping profile IDs to their parameter statistics
        """
        allStats: dict[str, dict[str, dict[str, Any]]] = {}

        # Get all profile IDs
        profileIds = self._getProfileIds()

        for profileId in profileIds:
            stats = self.getStatisticsForProfile(profileId)
            if stats:
                allStats[profileId] = stats

        return allStats

    # ================================================================================
    # Profile Comparison
    # ================================================================================

    def compareProfiles(
        self,
        profileId1: str,
        profileId2: str
    ) -> ProfileComparison:
        """
        Compare statistics between two profiles.

        Calculates variance percentages for each common parameter and
        identifies significant differences (>10% variance).

        Args:
            profileId1: First profile ID
            profileId2: Second profile ID

        Returns:
            ProfileComparison with detailed comparison results
        """
        comparisonDate = datetime.now()

        # Get statistics for both profiles
        stats1 = self.getStatisticsForProfile(profileId1)
        stats2 = self.getStatisticsForProfile(profileId2)

        # Find common parameters
        params1 = set(stats1.keys())
        params2 = set(stats2.keys())
        commonParams = list(params1.intersection(params2))
        commonParams.sort()

        comparison = ProfileComparison(
            profileId1=profileId1,
            profileId2=profileId2,
            comparisonDate=comparisonDate,
            commonParameters=commonParams
        )

        significantCount = 0

        for paramName in commonParams:
            paramStats1 = stats1[paramName]
            paramStats2 = stats2[paramName]

            # Get average values
            avg1 = paramStats1.get('avg', 0.0) or 0.0
            avg2 = paramStats2.get('avg', 0.0) or 0.0

            # Get max values
            max1 = paramStats1.get('max')
            max2 = paramStats2.get('max')

            # Get min values
            min1 = paramStats1.get('min')
            paramStats1.get('min')

            # Calculate variance percentages
            avgVariance = self._calculateVariancePercent(avg1, avg2)
            maxVariance = self._calculateVariancePercent(max1, max2) if max1 and max2 else 0.0

            # Determine significance (>10% variance)
            isSignificant = abs(avgVariance) > SIGNIFICANCE_THRESHOLD

            if isSignificant:
                significantCount += 1

            paramComp = ParameterComparison(
                parameterName=paramName,
                profile1Value=avg1,
                profile2Value=avg2,
                profile1Max=max1,
                profile2Max=max2,
                profile1Min=min1,
                profile2Min=paramStats2.get('min'),
                avgVariancePercent=avgVariance,
                maxVariancePercent=maxVariance,
                isSignificant=isSignificant
            )

            comparison.parameterComparisons[paramName] = paramComp

        comparison.significantCount = significantCount

        logger.info(
            f"Profile comparison | {profileId1} vs {profileId2} | "
            f"common={len(commonParams)} | significant={significantCount}"
        )

        return comparison

    def compareMultipleProfiles(
        self,
        profileIds: list[str]
    ) -> list[ProfileComparison]:
        """
        Compare all pairs of profiles.

        Args:
            profileIds: List of profile IDs to compare

        Returns:
            List of ProfileComparison for each pair
        """
        comparisons: list[ProfileComparison] = []

        # Generate all pairs
        for profile1, profile2 in combinations(profileIds, 2):
            comparison = self.compareProfiles(profile1, profile2)
            comparisons.append(comparison)

        return comparisons

    # ================================================================================
    # Report Generation
    # ================================================================================

    def generateReport(
        self,
        profileIds: list[str] | None = None
    ) -> ProfileStatisticsReport:
        """
        Generate a comprehensive statistics report.

        Args:
            profileIds: List of profiles to include (None for all)

        Returns:
            ProfileStatisticsReport with statistics and comparisons
        """
        reportDate = datetime.now()

        # Get profile IDs
        if profileIds is None:
            profileIds = self._getProfileIds()

        if not profileIds:
            return ProfileStatisticsReport(
                reportDate=reportDate,
                profileIds=[]
            )

        report = ProfileStatisticsReport(
            reportDate=reportDate,
            profileIds=profileIds
        )

        totalSamples = 0
        allParameters: set = set()

        # Get statistics for each profile
        for profileId in profileIds:
            stats = self.getStatisticsForProfile(profileId)
            if stats:
                report.profileStatistics[profileId] = stats
                allParameters.update(stats.keys())

                # Sum up samples
                for paramStats in stats.values():
                    sampleCount = paramStats.get('sample_count', 0) or 0
                    totalSamples += sampleCount

        report.totalSamples = totalSamples
        report.totalParameters = len(allParameters)

        # Generate comparisons if multiple profiles
        if len(profileIds) > 1:
            report.comparisons = self.compareMultipleProfiles(profileIds)

            # Collect significant differences
            for comparison in report.comparisons:
                for paramName, paramComp in comparison.parameterComparisons.items():
                    if paramComp.isSignificant:
                        # Determine which profile has higher value
                        if paramComp.profile2Value > paramComp.profile1Value:
                            higherProfile = comparison.profileId2
                            lowerProfile = comparison.profileId1
                        else:
                            higherProfile = comparison.profileId1
                            lowerProfile = comparison.profileId2

                        description = (
                            f"{paramName} is {abs(paramComp.avgVariancePercent):.1f}% "
                            f"higher in {higherProfile} vs {lowerProfile}"
                        )

                        report.significantDifferences.append(
                            ProfileComparisonResult(
                                parameterName=paramName,
                                profileId1=comparison.profileId1,
                                profileId2=comparison.profileId2,
                                variancePercent=paramComp.avgVariancePercent,
                                description=description
                            )
                        )

        logger.info(
            f"Generated report | profiles={len(profileIds)} | "
            f"parameters={report.totalParameters} | samples={report.totalSamples}"
        )

        return report

    # ================================================================================
    # Private Methods
    # ================================================================================

    def _getProfileIds(self) -> list[str]:
        """Get all profile IDs from database."""
        profileIds: list[str] = []

        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT id FROM profiles ORDER BY name")
                for row in cursor.fetchall():
                    profileIds.append(row['id'] if hasattr(row, '__getitem__') else row[0])
        except Exception as e:
            logger.warning(f"Error getting profile IDs: {e}")

        return profileIds

    def _calculateVariancePercent(
        self,
        value1: float | None,
        value2: float | None
    ) -> float:
        """
        Calculate variance percentage between two values.

        Args:
            value1: First value (base)
            value2: Second value

        Returns:
            Percentage variance ((v2-v1)/v1 * 100)
        """
        if value1 is None or value2 is None:
            return 0.0

        # Avoid division by zero
        if value1 == 0:
            if value2 == 0:
                return 0.0
            # If base is 0 but second value isn't, use second value as base
            return abs(value2 / (value2 + 0.0001)) * 100

        variance = ((value2 - value1) / abs(value1)) * 100
        return round(variance, 2)


# ================================================================================
# Helper Functions (convenience functions for quick access)
# ================================================================================

def createProfileStatisticsManager(
    database: Any,
    config: dict[str, Any]
) -> ProfileStatisticsManager:
    """
    Create a ProfileStatisticsManager from configuration.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary

    Returns:
        Configured ProfileStatisticsManager instance
    """
    return ProfileStatisticsManager(database, config)


def compareProfiles(
    database: Any,
    config: dict[str, Any],
    profileId1: str,
    profileId2: str
) -> ProfileComparison:
    """
    Compare statistics between two profiles.

    Convenience function for quick profile comparison.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary
        profileId1: First profile ID
        profileId2: Second profile ID

    Returns:
        ProfileComparison with detailed comparison results
    """
    manager = ProfileStatisticsManager(database, config)
    return manager.compareProfiles(profileId1, profileId2)


def generateProfileReport(
    database: Any,
    config: dict[str, Any],
    profileIds: list[str] | None = None
) -> ProfileStatisticsReport:
    """
    Generate a comprehensive profile statistics report.

    Convenience function for quick report generation.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary
        profileIds: List of profiles to include (None for all)

    Returns:
        ProfileStatisticsReport with statistics and comparisons
    """
    manager = ProfileStatisticsManager(database, config)
    return manager.generateReport(profileIds)


def getProfileStatisticsSummary(
    database: Any,
    profileId: str,
    parameterNames: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    """
    Get statistics summary for a specific profile.

    Convenience function wrapping getStatisticsSummary.

    Args:
        database: ObdDatabase instance
        profileId: Profile ID to get statistics for
        parameterNames: Optional list of parameter names to filter

    Returns:
        Dictionary mapping parameter names to their statistics
    """
    return getStatisticsSummary(database, profileId, parameterNames)


def getAllProfilesStatistics(
    database: Any
) -> dict[str, dict[str, dict[str, Any]]]:
    """
    Get statistics for all profiles in the database.

    Args:
        database: ObdDatabase instance

    Returns:
        Dictionary mapping profile IDs to their parameter statistics
    """
    manager = ProfileStatisticsManager(database, {})
    return manager.getAllProfileStatistics()
