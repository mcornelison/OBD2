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
# 2026-01-22    | Ralph Agent  | US-016 - Add core components exports
# ================================================================================
################################################################################
"""
AI Subpackage.

This subpackage contains AI analyzer and recommendation components:
- AI-powered data analysis (AiAnalyzer)
- Data window preparation for prompts (prepareDataWindow)
- Ollama integration for local LLM inference (OllamaManager)
- Prompt templates and generation (AiPromptTemplate)
- Recommendation ranking algorithms (RecommendationRanker)

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

Core Components (US-016):
- AiAnalyzer class for post-drive AI analysis
- AiPromptTemplate class for prompt generation
- OllamaManager class for ollama service management
- RecommendationRanker class for ranking and deduplication
- Data preparation functions for extracting metrics
- Factory functions for easy component creation

Usage:
    from ai import (
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

        # Classes
        AiAnalyzer,
        AiPromptTemplate,
        OllamaManager,
        RecommendationRanker,

        # Factory functions
        createAiAnalyzerFromConfig,
        createOllamaManagerFromConfig,
        createPromptTemplateFromConfig,
        createRecommendationRankerFromConfig,
        isAiAnalysisEnabled,
    )
"""

# Types - Enums
# Core Classes
from .analyzer import AiAnalyzer

# Data Preparation
from .data_preparation import (
    HIGH_RPM_THRESHOLD,
    O2_LEAN_THRESHOLD,
    O2_RICH_THRESHOLD,
    PARAMETER_MAPPINGS,
    calculateDerivedMetrics,
    extractStatisticsMetrics,
    getAvailableMetricKeys,
    getParameterMappings,
    prepareDataWindow,
)

# Exceptions - AI Analyzer
# Exceptions - Prompt Template
# Exceptions - Ollama
# Exceptions - Recommendation Ranker
from .exceptions import (
    AiAnalyzerError,
    AiAnalyzerGenerationError,
    AiAnalyzerLimitExceededError,
    AiAnalyzerNotAvailableError,
    InvalidTemplateError,
    MissingMetricsError,
    OllamaError,
    OllamaModelError,
    OllamaNotAvailableError,
    PromptTemplateError,
    RecommendationRankerError,
)

# Factory Functions and Helpers
from .helpers import (
    calculateRecommendationSimilarity,
    connectAnalyzerToStatisticsEngine,
    createAiAnalyzerFromConfig,
    createOllamaManagerFromConfig,
    createPromptTemplateFromConfig,
    createRecommendationRankerFromConfig,
    extractRecommendationKeywords,
    getAiAnalysisConfig,
    initializeAiComponents,
    isAiAnalysisEnabled,
    prepareAnalysisDataWindow,
    rankRecommendationText,
)
from .ollama import (
    OLLAMA_AVAILABLE,
    OllamaManager,
    getOllamaConfig,
    isOllamaAvailable,
)
from .prompt_template import (
    DEFAULT_PROMPT_TEMPLATE,
    FOCUS_AREA_TEMPLATES,
    AiPromptTemplate,
    buildPromptFromMetrics,
    extractMetricsFromStatistics,
    getDefaultPromptTemplate,
    getDefaultVehicleContext,
    getFocusAreaTemplates,
)
from .ranker import (
    ALL_KEYWORDS,
    DOMAIN_KEYWORDS,
    PRIORITY_KEYWORDS,
    RecommendationRanker,
    calculateTextSimilarity,
    extractKeywords,
    getDomainKeywords,
    getPriorityKeywords,
    rankRecommendation,
)

# Types - Dataclasses
# Types - Constants
from .types import (
    DEFAULT_MAX_ANALYSES_PER_DRIVE,
    DUPLICATE_WINDOW_DAYS,
    METRIC_PLACEHOLDERS,
    OLLAMA_API_TIMEOUT,
    OLLAMA_DEFAULT_BASE_URL,
    OLLAMA_DEFAULT_MODEL,
    OLLAMA_GENERATE_TIMEOUT,
    OLLAMA_HEALTH_TIMEOUT,
    OLLAMA_PULL_TIMEOUT,
    SIMILARITY_THRESHOLD,
    VEHICLE_CONTEXT,
    AiRecommendation,
    AnalysisResult,
    AnalyzerState,
    AnalyzerStats,
    FocusArea,
    GeneratedPrompt,
    ModelInfo,
    OllamaState,
    OllamaStatus,
    PriorityRank,
    PromptMetrics,
    RankedRecommendation,
    SimilarityResult,
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

    # Constants - Types
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

    # Core Classes
    'AiAnalyzer',
    'AiPromptTemplate',
    'OllamaManager',
    'RecommendationRanker',

    # Prompt Template Functions
    'DEFAULT_PROMPT_TEMPLATE',
    'FOCUS_AREA_TEMPLATES',
    'getDefaultPromptTemplate',
    'getDefaultVehicleContext',
    'getFocusAreaTemplates',
    'buildPromptFromMetrics',
    'extractMetricsFromStatistics',

    # Ollama Functions
    'OLLAMA_AVAILABLE',
    'isOllamaAvailable',
    'getOllamaConfig',

    # Ranker Functions and Constants
    'PRIORITY_KEYWORDS',
    'ALL_KEYWORDS',
    'DOMAIN_KEYWORDS',
    'extractKeywords',
    'calculateTextSimilarity',
    'rankRecommendation',
    'getPriorityKeywords',
    'getDomainKeywords',

    # Data Preparation Functions and Constants
    'prepareDataWindow',
    'extractStatisticsMetrics',
    'calculateDerivedMetrics',
    'getParameterMappings',
    'getAvailableMetricKeys',
    'PARAMETER_MAPPINGS',
    'HIGH_RPM_THRESHOLD',
    'O2_RICH_THRESHOLD',
    'O2_LEAN_THRESHOLD',

    # Factory Functions and Helpers
    'createAiAnalyzerFromConfig',
    'isAiAnalysisEnabled',
    'getAiAnalysisConfig',
    'connectAnalyzerToStatisticsEngine',
    'createOllamaManagerFromConfig',
    'createPromptTemplateFromConfig',
    'createRecommendationRankerFromConfig',
    'rankRecommendationText',
    'extractRecommendationKeywords',
    'calculateRecommendationSimilarity',
    'prepareAnalysisDataWindow',
    'initializeAiComponents',
]
