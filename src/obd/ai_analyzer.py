################################################################################
# File Name: ai_analyzer.py
# Purpose/Description: AI-based post-drive analysis for OBD-II performance data
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-019
# 2026-01-22    | Ralph Agent   | US-016 - Re-export from ai subpackage
# ================================================================================
################################################################################

"""
AI-based post-drive analysis module for the Eclipse OBD-II Performance Monitoring System.

This module re-exports from the ai subpackage for backward compatibility.
New code should import directly from ai.

Provides AI-powered performance optimization recommendations by analyzing drive data
through a local ollama model. Integrates with the statistics engine to trigger
analysis after each drive ends.

Usage (backward compatible):
    from obd.ai_analyzer import (
        AiAnalyzer,
        createAiAnalyzerFromConfig,
        isAiAnalysisEnabled,
    )

Recommended usage (new code):
    from ai import (
        AiAnalyzer,
        createAiAnalyzerFromConfig,
        isAiAnalysisEnabled,
    )
"""

# Re-export from ai subpackage for backward compatibility
from ai import (
    # Constants
    DEFAULT_MAX_ANALYSES_PER_DRIVE,
    OLLAMA_DEFAULT_BASE_URL,
    OLLAMA_GENERATE_TIMEOUT,
    # Class
    AiAnalyzer,
    # Exceptions
    AiAnalyzerError,
    AiAnalyzerGenerationError,
    AiAnalyzerLimitExceededError,
    AiAnalyzerNotAvailableError,
    # Dataclasses
    AiRecommendation,
    AnalysisResult,
    # Enums
    AnalyzerState,
    AnalyzerStats,
    connectAnalyzerToStatisticsEngine,
    # Helper functions
    createAiAnalyzerFromConfig,
    getAiAnalysisConfig,
    isAiAnalysisEnabled,
)

__all__ = [
    # Enums
    'AnalyzerState',

    # Dataclasses
    'AiRecommendation',
    'AnalysisResult',
    'AnalyzerStats',

    # Constants
    'DEFAULT_MAX_ANALYSES_PER_DRIVE',
    'OLLAMA_GENERATE_TIMEOUT',
    'OLLAMA_DEFAULT_BASE_URL',

    # Exceptions
    'AiAnalyzerError',
    'AiAnalyzerNotAvailableError',
    'AiAnalyzerLimitExceededError',
    'AiAnalyzerGenerationError',

    # Class
    'AiAnalyzer',

    # Helper functions
    'createAiAnalyzerFromConfig',
    'isAiAnalysisEnabled',
    'getAiAnalysisConfig',
    'connectAnalyzerToStatisticsEngine',
]
