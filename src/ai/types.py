################################################################################
# File Name: types.py
# Purpose/Description: Type definitions for AI analyzer and recommendation system
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-015 - Extract types
#               |              | from ai_analyzer.py, ai_prompt_template.py,
#               |              | ollama_manager.py, and recommendation_ranker.py
# ================================================================================
################################################################################

"""
Type definitions for the AI analysis and recommendation system.

This module contains enums and dataclasses used throughout the AI subpackage,
including types for:
- Analyzer state tracking (AnalyzerState)
- AI recommendations (AiRecommendation, AnalysisResult, AnalyzerStats)
- Focus areas for analysis (FocusArea)
- Prompt generation (PromptMetrics, GeneratedPrompt)
- Ollama service management (OllamaState, OllamaStatus, ModelInfo)
- Recommendation ranking (PriorityRank, RankedRecommendation, SimilarityResult)

All types have zero project dependencies (only stdlib) to prevent circular imports.

Usage:
    from obd.ai.types import (
        AnalyzerState,
        AiRecommendation,
        AnalysisResult,
        FocusArea,
        PriorityRank,
        RankedRecommendation,
    )
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# =============================================================================
# Constants
# =============================================================================

# AI Analyzer Constants
DEFAULT_MAX_ANALYSES_PER_DRIVE = 1
OLLAMA_GENERATE_TIMEOUT = 120  # 2 minutes for model generation
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "gemma2:2b"
OLLAMA_HEALTH_TIMEOUT = 5  # seconds
OLLAMA_API_TIMEOUT = 30  # seconds
OLLAMA_PULL_TIMEOUT = 600  # 10 minutes for model download

# Recommendation Ranker Constants
SIMILARITY_THRESHOLD = 0.70  # 70% similarity threshold for duplicates
DUPLICATE_WINDOW_DAYS = 30  # Check last 30 days for duplicates

# Default vehicle context for prompt templates (1998 Mitsubishi Eclipse)
VEHICLE_CONTEXT = {
    'year': 1998,
    'make': 'Mitsubishi',
    'model': 'Eclipse',
    'engine': '2.0L 4-cylinder turbocharged (4G63)',
    'goal': 'performance optimization'
}

# Metric placeholder mappings for prompt templates
METRIC_PLACEHOLDERS = {
    'rpm_avg': ('RPM', 'avg', 0),
    'rpm_max': ('RPM', 'max', 0),
    'rpm_min': ('RPM', 'min', 0),
    'rpm_high_time_pct': ('RPM', 'high_time_pct', 0),
    'short_fuel_trim_avg': ('SHORT_FUEL_TRIM_1', 'avg', 0.0),
    'long_fuel_trim_avg': ('LONG_FUEL_TRIM_1', 'avg', 0.0),
    'o2_voltage_avg': ('O2_B1S1', 'avg', 0.0),
    'o2_rich_count': ('O2_B1S1', 'rich_count', 0),
    'o2_lean_count': ('O2_B1S1', 'lean_count', 0),
    'engine_load_avg': ('ENGINE_LOAD', 'avg', 0.0),
    'engine_load_max': ('ENGINE_LOAD', 'max', 0.0),
    'throttle_pos_avg': ('THROTTLE_POS', 'avg', 0.0),
    'throttle_pos_max': ('THROTTLE_POS', 'max', 0.0),
    'maf_avg': ('MAF', 'avg', 0.0),
    'maf_max': ('MAF', 'max', 0.0),
    'intake_temp_avg': ('INTAKE_TEMP', 'avg', 0.0),
    'coolant_temp_avg': ('COOLANT_TEMP', 'avg', 0.0),
    'timing_advance_avg': ('TIMING_ADVANCE', 'avg', 0.0),
    'intake_pressure_avg': ('INTAKE_PRESSURE', 'avg', 0.0),
    'fuel_pressure_avg': ('FUEL_PRESSURE', 'avg', 0.0),
}


# =============================================================================
# AI Analyzer Enums
# =============================================================================

class AnalyzerState(Enum):
    """State of the AI analyzer."""

    IDLE = "idle"
    PREPARING = "preparing"
    ANALYZING = "analyzing"
    SAVING = "saving"
    COMPLETED = "completed"
    ERROR = "error"
    DISABLED = "disabled"


# =============================================================================
# AI Analyzer Dataclasses
# =============================================================================

@dataclass
class AiRecommendation:
    """
    AI-generated recommendation.

    Attributes:
        id: Database ID (None if not saved)
        timestamp: When the recommendation was generated
        recommendation: The recommendation text from the AI
        priorityRank: Priority ranking (1=highest, 5=lowest)
        isDuplicateOf: ID of original recommendation if this is a duplicate
        profileId: Profile ID the recommendation is associated with
    """

    id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)
    recommendation: str = ""
    priorityRank: int = 3
    isDuplicateOf: Optional[int] = None
    profileId: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'recommendation': self.recommendation,
            'priorityRank': self.priorityRank,
            'isDuplicateOf': self.isDuplicateOf,
            'profileId': self.profileId
        }


@dataclass
class AnalysisResult:
    """
    Result of AI analysis.

    Attributes:
        success: Whether analysis completed successfully
        recommendation: The generated recommendation
        promptUsed: The prompt sent to the AI
        responseRaw: Raw response from ollama
        analysisTime: Time taken for analysis in milliseconds
        errorMessage: Error message if analysis failed
        profileId: Profile ID used for analysis
        driveId: Optional identifier for the drive session
    """

    success: bool = False
    recommendation: Optional[AiRecommendation] = None
    promptUsed: str = ""
    responseRaw: str = ""
    analysisTime: float = 0.0
    errorMessage: Optional[str] = None
    profileId: Optional[str] = None
    driveId: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'success': self.success,
            'recommendation': self.recommendation.toDict() if self.recommendation else None,
            'promptUsed': self.promptUsed[:500] + "..." if len(self.promptUsed) > 500 else self.promptUsed,
            'responseRaw': self.responseRaw[:500] + "..." if len(self.responseRaw) > 500 else self.responseRaw,
            'analysisTime': self.analysisTime,
            'errorMessage': self.errorMessage,
            'profileId': self.profileId,
            'driveId': self.driveId
        }


@dataclass
class AnalyzerStats:
    """
    Statistics about analyzer operation.

    Attributes:
        totalAnalyses: Total analyses performed
        successfulAnalyses: Number of successful analyses
        failedAnalyses: Number of failed analyses
        totalRecommendations: Total recommendations saved
        averageAnalysisTime: Average analysis time in ms
        lastAnalysisTime: Time of last analysis
    """

    totalAnalyses: int = 0
    successfulAnalyses: int = 0
    failedAnalyses: int = 0
    totalRecommendations: int = 0
    averageAnalysisTime: float = 0.0
    lastAnalysisTime: Optional[datetime] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'totalAnalyses': self.totalAnalyses,
            'successfulAnalyses': self.successfulAnalyses,
            'failedAnalyses': self.failedAnalyses,
            'totalRecommendations': self.totalRecommendations,
            'averageAnalysisTime': self.averageAnalysisTime,
            'lastAnalysisTime': (
                self.lastAnalysisTime.isoformat() if self.lastAnalysisTime else None
            )
        }


# =============================================================================
# Prompt Template Enums
# =============================================================================

class FocusArea(Enum):
    """Focus areas for AI analysis."""

    AIR_FUEL_RATIO = "air_fuel_ratio"
    TIMING = "timing"
    THROTTLE_RESPONSE = "throttle_response"

    @classmethod
    def fromString(cls, value: str) -> Optional['FocusArea']:
        """
        Convert string to FocusArea enum.

        Args:
            value: String value to convert

        Returns:
            FocusArea enum or None if not found
        """
        normalized = value.lower().replace(' ', '_').replace('-', '_')
        for area in cls:
            if area.value == normalized:
                return area
        return None


# =============================================================================
# Prompt Template Dataclasses
# =============================================================================

@dataclass
class PromptMetrics:
    """
    Container for OBD-II metrics used in prompt generation.

    Attributes:
        rpmStats: RPM statistics dictionary
        fuelTrimStats: Fuel trim statistics dictionary
        engineLoadStats: Engine load statistics dictionary
        throttleStats: Throttle position statistics dictionary
        airflowStats: MAF and airflow statistics dictionary
        temperatureStats: Temperature statistics dictionary
        timingStats: Timing and pressure statistics dictionary
        customMetrics: Additional custom metrics
    """

    rpmStats: Dict[str, Any] = field(default_factory=dict)
    fuelTrimStats: Dict[str, Any] = field(default_factory=dict)
    engineLoadStats: Dict[str, Any] = field(default_factory=dict)
    throttleStats: Dict[str, Any] = field(default_factory=dict)
    airflowStats: Dict[str, Any] = field(default_factory=dict)
    temperatureStats: Dict[str, Any] = field(default_factory=dict)
    timingStats: Dict[str, Any] = field(default_factory=dict)
    customMetrics: Dict[str, Any] = field(default_factory=dict)

    def toFlatDict(self) -> Dict[str, Any]:
        """
        Convert all stats to a flat dictionary for template substitution.

        Returns:
            Flat dictionary with all metrics
        """
        result: Dict[str, Any] = {}

        # Flatten each stats category
        for prefix, stats in [
            ('rpm', self.rpmStats),
            ('fuel_trim', self.fuelTrimStats),
            ('engine_load', self.engineLoadStats),
            ('throttle', self.throttleStats),
            ('airflow', self.airflowStats),
            ('temperature', self.temperatureStats),
            ('timing', self.timingStats),
        ]:
            for key, value in stats.items():
                result[f"{prefix}_{key}"] = value

        # Add custom metrics directly
        result.update(self.customMetrics)

        return result

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'rpmStats': self.rpmStats,
            'fuelTrimStats': self.fuelTrimStats,
            'engineLoadStats': self.engineLoadStats,
            'throttleStats': self.throttleStats,
            'airflowStats': self.airflowStats,
            'temperatureStats': self.temperatureStats,
            'timingStats': self.timingStats,
            'customMetrics': self.customMetrics,
        }


@dataclass
class GeneratedPrompt:
    """
    Result of prompt generation.

    Attributes:
        prompt: The generated prompt text
        template: Template name or identifier used
        timestamp: When the prompt was generated
        vehicleContext: Vehicle context used
        metricsIncluded: List of metrics that were included
        focusAreas: Focus areas that were added
        warnings: Any warnings during generation (e.g., missing metrics)
    """

    prompt: str
    template: str = "default"
    timestamp: datetime = field(default_factory=datetime.now)
    vehicleContext: Dict[str, Any] = field(default_factory=dict)
    metricsIncluded: List[str] = field(default_factory=list)
    focusAreas: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'prompt': self.prompt,
            'template': self.template,
            'timestamp': self.timestamp.isoformat(),
            'vehicleContext': self.vehicleContext,
            'metricsIncluded': self.metricsIncluded,
            'focusAreas': self.focusAreas,
            'warnings': self.warnings,
        }


# =============================================================================
# Ollama Manager Enums
# =============================================================================

class OllamaState(Enum):
    """Ollama service state."""

    UNAVAILABLE = "unavailable"
    AVAILABLE = "available"
    MODEL_READY = "model_ready"
    MODEL_DOWNLOADING = "model_downloading"
    ERROR = "error"


# =============================================================================
# Ollama Manager Dataclasses
# =============================================================================

@dataclass
class OllamaStatus:
    """Status information for ollama service."""

    state: OllamaState = OllamaState.UNAVAILABLE
    version: Optional[str] = None
    model: Optional[str] = None
    modelReady: bool = False
    availableModels: List[str] = field(default_factory=list)
    errorMessage: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'state': self.state.value,
            'version': self.version,
            'model': self.model,
            'modelReady': self.modelReady,
            'availableModels': self.availableModels,
            'errorMessage': self.errorMessage
        }


@dataclass
class ModelInfo:
    """Information about an installed model."""

    name: str
    size: int  # bytes
    digest: str
    modifiedAt: Optional[datetime] = None

    @property
    def sizeGb(self) -> float:
        """Get size in gigabytes."""
        return self.size / (1024 * 1024 * 1024)

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'size': self.size,
            'sizeGb': round(self.sizeGb, 2),
            'digest': self.digest,
            'modifiedAt': self.modifiedAt.isoformat() if self.modifiedAt else None
        }


# =============================================================================
# Recommendation Ranker Enums
# =============================================================================

class PriorityRank(Enum):
    """Priority ranking for AI recommendations."""

    SAFETY = 1
    PERFORMANCE = 2
    EFFICIENCY = 3
    MINOR_TWEAK = 4
    INFORMATIONAL = 5

    @classmethod
    def fromValue(cls, value: int) -> 'PriorityRank':
        """
        Convert integer value to PriorityRank.

        Args:
            value: Integer priority value (1-5)

        Returns:
            PriorityRank enum, defaults to INFORMATIONAL for invalid values
        """
        for rank in cls:
            if rank.value == value:
                return rank
        return cls.INFORMATIONAL


# =============================================================================
# Recommendation Ranker Dataclasses
# =============================================================================

@dataclass
class RankedRecommendation:
    """
    A ranked AI recommendation.

    Attributes:
        recommendation: The AI-generated recommendation text
        priorityRank: Priority ranking (1-5)
        id: Database ID (None until stored)
        isDuplicateOf: ID of original if this is a duplicate
        profileId: Associated profile ID
        timestamp: When the recommendation was generated
        keywords: Extracted keywords from the recommendation
    """

    recommendation: str
    priorityRank: PriorityRank
    id: Optional[int] = None
    isDuplicateOf: Optional[int] = None
    profileId: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    keywords: List[str] = field(default_factory=list)

    @property
    def isDuplicate(self) -> bool:
        """Check if this recommendation is marked as a duplicate."""
        return self.isDuplicateOf is not None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'recommendation': self.recommendation,
            'priorityRank': self.priorityRank.value,
            'priorityName': self.priorityRank.name,
            'isDuplicateOf': self.isDuplicateOf,
            'isDuplicate': self.isDuplicate,
            'profileId': self.profileId,
            'timestamp': self.timestamp.isoformat(),
            'keywords': self.keywords
        }


@dataclass
class SimilarityResult:
    """
    Result of similarity check against existing recommendations.

    Attributes:
        similarityScore: Similarity score (0.0 to 1.0)
        matchedRecommendationId: ID of the most similar recommendation
        sharedKeywords: Keywords shared between recommendations
    """

    similarityScore: float = 0.0
    matchedRecommendationId: Optional[int] = None
    sharedKeywords: List[str] = field(default_factory=list)

    def isAboveThreshold(self, threshold: float = SIMILARITY_THRESHOLD) -> bool:
        """Check if similarity is above the duplicate threshold."""
        return self.similarityScore >= threshold

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'similarityScore': self.similarityScore,
            'matchedRecommendationId': self.matchedRecommendationId,
            'sharedKeywords': self.sharedKeywords,
            'isAboveThreshold': self.isAboveThreshold()
        }
