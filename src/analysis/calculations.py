################################################################################
# File Name: calculations.py
# Purpose/Description: Pure calculation functions for statistics analysis
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-010 refactoring
# ================================================================================
################################################################################

"""
Pure calculation functions for statistics analysis.

Provides:
- calculateMean: Calculate arithmetic mean of values
- calculateMode: Calculate mode (most common value) of values
- calculateStandardDeviation: Calculate sample standard deviation
- calculateOutlierBounds: Calculate outlier bounds based on mean and std dev
- calculateParameterStatistics: Calculate all statistics for a parameter

These are pure functions with no side effects.
"""

import math
from collections import Counter
from datetime import datetime
from typing import List, Optional, Tuple

from .exceptions import InsufficientDataError
from .types import ParameterStatistics


# ================================================================================
# Statistics Calculator Functions
# ================================================================================

def calculateMean(values: List[float]) -> float:
    """
    Calculate arithmetic mean of values.

    Args:
        values: List of numeric values

    Returns:
        Mean value

    Raises:
        InsufficientDataError: If values list is empty
    """
    if not values:
        raise InsufficientDataError("Cannot calculate mean of empty list")
    return sum(values) / len(values)


def calculateMode(values: List[float], precision: int = 2) -> Optional[float]:
    """
    Calculate mode (most common value) of values.

    Args:
        values: List of numeric values
        precision: Decimal places to round for mode calculation

    Returns:
        Mode value, or None if no clear mode exists
    """
    if not values:
        return None

    # Round values for mode calculation to group similar values
    roundedValues = [round(v, precision) for v in values]
    counter = Counter(roundedValues)

    if not counter:
        return None

    # Get most common value
    mostCommon = counter.most_common(1)
    if mostCommon:
        return mostCommon[0][0]

    return None


def calculateStandardDeviation(values: List[float], mean: Optional[float] = None) -> float:
    """
    Calculate sample standard deviation of values.

    Args:
        values: List of numeric values
        mean: Pre-calculated mean (optional, will calculate if not provided)

    Returns:
        Standard deviation

    Raises:
        InsufficientDataError: If fewer than 2 values provided
    """
    if len(values) < 2:
        raise InsufficientDataError(
            "Cannot calculate standard deviation with fewer than 2 values"
        )

    if mean is None:
        mean = calculateMean(values)

    # Calculate sum of squared differences from mean
    squaredDiffs = [(v - mean) ** 2 for v in values]

    # Use sample standard deviation (n-1)
    variance = sum(squaredDiffs) / (len(values) - 1)
    return math.sqrt(variance)


def calculateOutlierBounds(
    mean: float,
    stdDev: float,
    multiplier: float = 2.0
) -> Tuple[float, float]:
    """
    Calculate outlier bounds based on mean and standard deviation.

    Args:
        mean: Mean value
        stdDev: Standard deviation
        multiplier: Standard deviation multiplier (default: 2.0)

    Returns:
        Tuple of (outlier_min, outlier_max)
    """
    outlierMin = mean - (multiplier * stdDev)
    outlierMax = mean + (multiplier * stdDev)
    return (outlierMin, outlierMax)


def calculateParameterStatistics(
    values: List[float],
    parameterName: str,
    profileId: str,
    analysisDate: Optional[datetime] = None,
    minSamples: int = 2
) -> ParameterStatistics:
    """
    Calculate all statistics for a parameter.

    Args:
        values: List of parameter values
        parameterName: Name of the parameter
        profileId: Profile ID for the analysis
        analysisDate: When the analysis was performed (default: now)
        minSamples: Minimum samples required for std calculation

    Returns:
        ParameterStatistics with all calculated values

    Raises:
        InsufficientDataError: If no values provided
    """
    if analysisDate is None:
        analysisDate = datetime.now()

    if not values:
        raise InsufficientDataError(
            f"No data for parameter '{parameterName}'",
            details={'parameter': parameterName, 'profileId': profileId}
        )

    # Basic statistics
    maxValue = max(values)
    minValue = min(values)
    avgValue = calculateMean(values)
    modeValue = calculateMode(values)
    sampleCount = len(values)

    # Standard deviation and outliers (requires at least minSamples points)
    std1 = None
    std2 = None
    outlierMin = None
    outlierMax = None

    if sampleCount >= minSamples:
        try:
            std1 = calculateStandardDeviation(values, avgValue)
            std2 = std1 * 2
            outlierMin, outlierMax = calculateOutlierBounds(avgValue, std1)
        except (InsufficientDataError, ZeroDivisionError):
            # Keep as None if calculation fails
            pass

    return ParameterStatistics(
        parameterName=parameterName,
        analysisDate=analysisDate,
        profileId=profileId,
        maxValue=maxValue,
        minValue=minValue,
        avgValue=avgValue,
        modeValue=modeValue,
        std1=std1,
        std2=std2,
        outlierMin=outlierMin,
        outlierMax=outlierMax,
        sampleCount=sampleCount
    )
