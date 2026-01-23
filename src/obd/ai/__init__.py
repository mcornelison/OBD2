################################################################################
# File Name: __init__.py
# Purpose/Description: AI subpackage for AI analyzer and recommendation components
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | US-015 - Add types and exceptions exports
# ================================================================================
################################################################################
"""
AI Subpackage.

This subpackage contains AI analyzer and recommendation components:
- AI-powered data analysis
- Ollama integration for local LLM inference
- Prompt templates and generation
- Recommendation ranking algorithms

Types Module (US-015):
- AnalyzerState enum for analyzer state tracking
- AiRecommendation, AnalysisResult, AnalyzerStats dataclasses
- FocusArea enum for analysis focus areas
- PromptMetrics, GeneratedPrompt dataclasses for prompt generation
- OllamaState enum, OllamaStatus, ModelInfo dataclasses for ollama management
- PriorityRank enum, RankedRecommendation, SimilarityResult dataclasses for ranking

Exceptions Module (US-015):
- AiAnalyzerError and subclasses for analyzer errors
- PromptTemplateError and subclasses for template errors
- OllamaError and subclasses for ollama errors
- RecommendationRankerError for ranker errors

Usage:
    from obd.ai import (
        # Types - Enums
        AnalyzerState,
        FocusArea,
        OllamaState,
        PriorityRank,

        # Types - Dataclasses
        AiRecommendation,
        AnalysisResult,
        AnalyzerStats,
        PromptMetrics,
        GeneratedPrompt,
        OllamaStatus,
        ModelInfo,
        RankedRecommendation,
        SimilarityResult,

        # Types - Constants
        DEFAULT_MAX_ANALYSES_PER_DRIVE,
        OLLAMA_DEFAULT_BASE_URL,
        SIMILARITY_THRESHOLD,

        # Exceptions
        AiAnalyzerError,
        AiAnalyzerNotAvailableError,
        PromptTemplateError,
        OllamaError,
    )
"""

# Types - Enums
from .types import (
    AnalyzerState,
    FocusArea,
    OllamaState,
    PriorityRank,
)

# Types - Dataclasses
from .types import (
    AiRecommendation,
    AnalysisResult,
    AnalyzerStats,
    PromptMetrics,
    GeneratedPrompt,
    OllamaStatus,
    ModelInfo,
    RankedRecommendation,
    SimilarityResult,
)

# Types - Constants
from .types import (
    DEFAULT_MAX_ANALYSES_PER_DRIVE,
    OLLAMA_GENERATE_TIMEOUT,
    OLLAMA_DEFAULT_BASE_URL,
    OLLAMA_DEFAULT_MODEL,
    OLLAMA_HEALTH_TIMEOUT,
    OLLAMA_API_TIMEOUT,
    OLLAMA_PULL_TIMEOUT,
    SIMILARITY_THRESHOLD,
    DUPLICATE_WINDOW_DAYS,
    VEHICLE_CONTEXT,
    METRIC_PLACEHOLDERS,
)

# Exceptions - AI Analyzer
from .exceptions import (
    AiAnalyzerError,
    AiAnalyzerNotAvailableError,
    AiAnalyzerLimitExceededError,
    AiAnalyzerGenerationError,
)

# Exceptions - Prompt Template
from .exceptions import (
    PromptTemplateError,
    InvalidTemplateError,
    MissingMetricsError,
)

# Exceptions - Ollama
from .exceptions import (
    OllamaError,
    OllamaNotAvailableError,
    OllamaModelError,
)

# Exceptions - Recommendation Ranker
from .exceptions import (
    RecommendationRankerError,
)


__all__ = [
    # Enums
    'AnalyzerState',
    'FocusArea',
    'OllamaState',
    'PriorityRank',

    # Dataclasses
    'AiRecommendation',
    'AnalysisResult',
    'AnalyzerStats',
    'PromptMetrics',
    'GeneratedPrompt',
    'OllamaStatus',
    'ModelInfo',
    'RankedRecommendation',
    'SimilarityResult',

    # Constants
    'DEFAULT_MAX_ANALYSES_PER_DRIVE',
    'OLLAMA_GENERATE_TIMEOUT',
    'OLLAMA_DEFAULT_BASE_URL',
    'OLLAMA_DEFAULT_MODEL',
    'OLLAMA_HEALTH_TIMEOUT',
    'OLLAMA_API_TIMEOUT',
    'OLLAMA_PULL_TIMEOUT',
    'SIMILARITY_THRESHOLD',
    'DUPLICATE_WINDOW_DAYS',
    'VEHICLE_CONTEXT',
    'METRIC_PLACEHOLDERS',

    # AI Analyzer Exceptions
    'AiAnalyzerError',
    'AiAnalyzerNotAvailableError',
    'AiAnalyzerLimitExceededError',
    'AiAnalyzerGenerationError',

    # Prompt Template Exceptions
    'PromptTemplateError',
    'InvalidTemplateError',
    'MissingMetricsError',

    # Ollama Exceptions
    'OllamaError',
    'OllamaNotAvailableError',
    'OllamaModelError',

    # Recommendation Ranker Exceptions
    'RecommendationRankerError',
]
