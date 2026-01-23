################################################################################
# File Name: data_preparation.py
# Purpose/Description: Data window preparation for AI analysis prompts
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-016 - Extract
#               |              | data preparation logic from ai_analyzer.py
# ================================================================================
################################################################################

"""
Data window preparation for AI analysis prompts.

This module provides functions for extracting and formatting OBD-II metrics
from statistics results into a format suitable for AI prompt generation.

Key features:
- Extract parameter statistics into prompt-ready metrics
- Calculate derived metrics from raw data (high RPM time, O2 rich/lean counts)
- Round values to appropriate precision

Usage:
    from obd.ai.data_preparation import (
        prepareDataWindow,
        extractStatisticsMetrics,
        calculateDerivedMetrics,
    )

    # From statistics result
    metrics = prepareDataWindow(statisticsResult, rawData)

    # Use with prompt template
    prompt = template.buildPrompt(metrics)
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Parameter Mappings
# =============================================================================

# Mapping from OBD parameter names to prompt metric keys
PARAMETER_MAPPINGS: Dict[str, Dict[str, str]] = {
    'RPM': {
        'avg': 'rpm_avg',
        'max': 'rpm_max',
        'min': 'rpm_min',
    },
    'SHORT_FUEL_TRIM_1': {
        'avg': 'short_fuel_trim_avg',
    },
    'LONG_FUEL_TRIM_1': {
        'avg': 'long_fuel_trim_avg',
    },
    'O2_B1S1': {
        'avg': 'o2_voltage_avg',
    },
    'ENGINE_LOAD': {
        'avg': 'engine_load_avg',
        'max': 'engine_load_max',
    },
    'THROTTLE_POS': {
        'avg': 'throttle_pos_avg',
        'max': 'throttle_pos_max',
    },
    'MAF': {
        'avg': 'maf_avg',
        'max': 'maf_max',
    },
    'INTAKE_TEMP': {
        'avg': 'intake_temp_avg',
    },
    'COOLANT_TEMP': {
        'avg': 'coolant_temp_avg',
    },
    'TIMING_ADVANCE': {
        'avg': 'timing_advance_avg',
    },
    'INTAKE_PRESSURE': {
        'avg': 'intake_pressure_avg',
    },
    'FUEL_PRESSURE': {
        'avg': 'fuel_pressure_avg',
    },
}

# Thresholds for derived metrics
HIGH_RPM_THRESHOLD = 4000  # RPM threshold for "high RPM" percentage
O2_RICH_THRESHOLD = 0.5  # Voltage above which O2 indicates rich
O2_LEAN_THRESHOLD = 0.4  # Voltage below which O2 indicates lean


# =============================================================================
# Data Extraction Functions
# =============================================================================

def extractStatValue(
    paramStats: Any,
    statKey: str
) -> Optional[Any]:
    """
    Extract a statistic value from either dict or object format.

    Args:
        paramStats: Parameter statistics (dict or object)
        statKey: Statistic key ('avg', 'max', 'min')

    Returns:
        Extracted value or None if not found
    """
    # Handle dict format
    if isinstance(paramStats, dict):
        if statKey == 'avg':
            return paramStats.get('avgValue')
        elif statKey == 'max':
            return paramStats.get('maxValue')
        elif statKey == 'min':
            return paramStats.get('minValue')
        else:
            return paramStats.get(statKey)

    # Handle object format with attributes
    if statKey == 'avg':
        return getattr(paramStats, 'avgValue', None)
    elif statKey == 'max':
        return getattr(paramStats, 'maxValue', None)
    elif statKey == 'min':
        return getattr(paramStats, 'minValue', None)
    else:
        return getattr(paramStats, statKey, None)


def extractStatisticsMetrics(
    statisticsResult: Any
) -> Dict[str, Any]:
    """
    Extract metrics from a statistics result.

    Converts StatisticsEngine analysis result into a flat dictionary
    of metrics suitable for prompt template substitution.

    Args:
        statisticsResult: AnalysisResult from StatisticsEngine
                         (can be object or dict with parameterStats)

    Returns:
        Dictionary of metrics with keys like 'rpm_avg', 'maf_max', etc.
    """
    metrics: Dict[str, Any] = {}

    if statisticsResult is None:
        return metrics

    # Extract parameter stats from result
    if isinstance(statisticsResult, dict):
        parameterStats = statisticsResult.get('parameterStats', {})
    else:
        parameterStats = getattr(statisticsResult, 'parameterStats', {})

    # Map parameter statistics to prompt metrics
    for paramName, mappings in PARAMETER_MAPPINGS.items():
        if paramName in parameterStats:
            paramStats = parameterStats[paramName]

            for statKey, metricKey in mappings.items():
                value = extractStatValue(paramStats, statKey)

                if value is not None:
                    # Round to reasonable precision
                    if isinstance(value, float):
                        metrics[metricKey] = round(value, 2)
                    else:
                        metrics[metricKey] = value

    logger.debug(f"Extracted {len(metrics)} metrics from statistics")
    return metrics


def calculateDerivedMetrics(
    rawData: Dict[str, List[float]]
) -> Dict[str, Any]:
    """
    Calculate derived metrics from raw parameter data.

    Computes additional metrics that require access to raw values
    rather than just aggregated statistics.

    Args:
        rawData: Dictionary mapping parameter names to lists of values

    Returns:
        Dictionary of derived metrics
    """
    metrics: Dict[str, Any] = {}

    if not rawData:
        return metrics

    # High RPM time percentage
    if 'RPM' in rawData and rawData['RPM']:
        rpmValues = rawData['RPM']
        highRpmCount = sum(1 for r in rpmValues if r > HIGH_RPM_THRESHOLD)
        metrics['rpm_high_time_pct'] = round(
            (highRpmCount / len(rpmValues)) * 100, 1
        )

    # O2 rich/lean counts
    if 'O2_B1S1' in rawData and rawData['O2_B1S1']:
        o2Values = rawData['O2_B1S1']
        metrics['o2_rich_count'] = sum(1 for v in o2Values if v > O2_RICH_THRESHOLD)
        metrics['o2_lean_count'] = sum(1 for v in o2Values if v < O2_LEAN_THRESHOLD)

    logger.debug(f"Calculated {len(metrics)} derived metrics")
    return metrics


def prepareDataWindow(
    statisticsResult: Any,
    rawData: Optional[Dict[str, List[float]]] = None
) -> Dict[str, Any]:
    """
    Prepare data window from statistics result for AI analysis.

    This is the main entry point for data preparation. It extracts
    metrics from the statistics result and calculates derived metrics
    from raw data if available.

    Args:
        statisticsResult: AnalysisResult from StatisticsEngine
        rawData: Optional raw parameter data for derived calculations

    Returns:
        Dictionary of all metrics for prompt template
    """
    # Extract metrics from statistics
    metrics = extractStatisticsMetrics(statisticsResult)

    # Calculate derived metrics from raw data
    if rawData:
        derivedMetrics = calculateDerivedMetrics(rawData)
        metrics.update(derivedMetrics)

    logger.debug(f"Prepared data window with {len(metrics)} total metrics")
    return metrics


def getParameterMappings() -> Dict[str, Dict[str, str]]:
    """
    Get the parameter to metric key mappings.

    Returns:
        Dictionary of parameter mappings
    """
    return PARAMETER_MAPPINGS.copy()


def getAvailableMetricKeys() -> List[str]:
    """
    Get all available metric keys that can be extracted.

    Returns:
        List of metric key names
    """
    keys: List[str] = []

    for mappings in PARAMETER_MAPPINGS.values():
        keys.extend(mappings.values())

    # Add derived metric keys
    keys.extend(['rpm_high_time_pct', 'o2_rich_count', 'o2_lean_count'])

    return keys
