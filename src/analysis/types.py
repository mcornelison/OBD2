################################################################################
# File Name: types.py
# Purpose/Description: Type definitions for the analysis subpackage
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
Type definitions for the analysis subpackage.

Provides:
- AnalysisState enum for analysis engine state
- ParameterStatistics dataclass for parameter statistical summary
- AnalysisResult dataclass for complete analysis run result
- EngineStats dataclass for engine performance tracking

These types have no dependencies on other project modules (only stdlib).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# ================================================================================
# Enums
# ================================================================================

class AnalysisState(Enum):
    """State of the analysis engine."""
    IDLE = 'idle'
    SCHEDULED = 'scheduled'
    RUNNING = 'running'
    COMPLETED = 'completed'
    ERROR = 'error'


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class ParameterStatistics:
    """
    Statistical summary for a single OBD-II parameter.

    Attributes:
        parameterName: Name of the parameter (e.g., 'RPM')
        analysisDate: When the analysis was performed
        profileId: Profile ID the analysis is associated with
        maxValue: Maximum value observed
        minValue: Minimum value observed
        avgValue: Average (mean) value
        modeValue: Most common value
        std1: First standard deviation
        std2: Second standard deviation (std1 * 2)
        outlierMin: Lower outlier bound (avg - 2*std1)
        outlierMax: Upper outlier bound (avg + 2*std1)
        sampleCount: Number of data points used
    """
    parameterName: str
    analysisDate: datetime
    profileId: str
    maxValue: float | None = None
    minValue: float | None = None
    avgValue: float | None = None
    modeValue: float | None = None
    std1: float | None = None
    std2: float | None = None
    outlierMin: float | None = None
    outlierMax: float | None = None
    sampleCount: int = 0

    def toDict(self) -> dict[str, Any]:
        """Convert statistics to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'analysisDate': self.analysisDate.isoformat() if self.analysisDate else None,
            'profileId': self.profileId,
            'maxValue': self.maxValue,
            'minValue': self.minValue,
            'avgValue': self.avgValue,
            'modeValue': self.modeValue,
            'std1': self.std1,
            'std2': self.std2,
            'outlierMin': self.outlierMin,
            'outlierMax': self.outlierMax,
            'sampleCount': self.sampleCount
        }


@dataclass
class AnalysisResult:
    """
    Result of a complete analysis run.

    Attributes:
        analysisDate: When the analysis was performed
        profileId: Profile ID the analysis is associated with
        parameterStats: Dictionary of parameter name to ParameterStatistics
        totalParameters: Number of parameters analyzed
        totalSamples: Total number of data points analyzed
        success: Whether the analysis completed successfully
        errorMessage: Error message if analysis failed
        durationMs: Duration of analysis in milliseconds
    """
    analysisDate: datetime
    profileId: str
    parameterStats: dict[str, ParameterStatistics] = field(default_factory=dict)
    totalParameters: int = 0
    totalSamples: int = 0
    success: bool = True
    errorMessage: str | None = None
    durationMs: float = 0.0

    def toDict(self) -> dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            'analysisDate': self.analysisDate.isoformat() if self.analysisDate else None,
            'profileId': self.profileId,
            'parameterStats': {
                name: stats.toDict()
                for name, stats in self.parameterStats.items()
            },
            'totalParameters': self.totalParameters,
            'totalSamples': self.totalSamples,
            'success': self.success,
            'errorMessage': self.errorMessage,
            'durationMs': self.durationMs
        }


@dataclass
class EngineStats:
    """
    Statistics about the engine itself.

    Attributes:
        totalAnalysesRun: Number of analyses performed
        lastAnalysisDate: When the last analysis was performed
        lastAnalysisDurationMs: Duration of last analysis in ms
        totalParametersAnalyzed: Total parameters analyzed across all runs
        totalSamplesProcessed: Total data points processed
    """
    totalAnalysesRun: int = 0
    lastAnalysisDate: datetime | None = None
    lastAnalysisDurationMs: float = 0.0
    totalParametersAnalyzed: int = 0
    totalSamplesProcessed: int = 0

    def toDict(self) -> dict[str, Any]:
        """Convert stats to dictionary for serialization."""
        return {
            'totalAnalysesRun': self.totalAnalysesRun,
            'lastAnalysisDate': (
                self.lastAnalysisDate.isoformat() if self.lastAnalysisDate else None
            ),
            'lastAnalysisDurationMs': self.lastAnalysisDurationMs,
            'totalParametersAnalyzed': self.totalParametersAnalyzed,
            'totalSamplesProcessed': self.totalSamplesProcessed
        }
