################################################################################
# File Name: helpers.py
# Purpose/Description: Factory and helper functions for AI analysis components
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-016 - Consolidate
#               |              | factory functions from AI modules
# ================================================================================
################################################################################

"""
Factory and helper functions for AI analysis components.

This module provides convenient factory functions for creating AI analysis
components from configuration, as well as utility functions for common
operations across the AI subpackage.

Usage:
    from obd.ai.helpers import (
        createAiAnalyzerFromConfig,
        createOllamaManagerFromConfig,
        createPromptTemplateFromConfig,
        createRecommendationRankerFromConfig,
        isAiAnalysisEnabled,
        connectAnalyzerToStatisticsEngine,
    )

    # Create all AI components from config
    ollama = createOllamaManagerFromConfig(config)
    template = createPromptTemplateFromConfig(config)
    analyzer = createAiAnalyzerFromConfig(config, database, ollama, template)
    ranker = createRecommendationRankerFromConfig(config, database)

    # Connect analyzer to statistics engine for automatic triggering
    connectAnalyzerToStatisticsEngine(analyzer, statisticsEngine)
"""

import logging
from typing import Any, Dict, Optional

from .types import (
    DEFAULT_MAX_ANALYSES_PER_DRIVE,
    OLLAMA_DEFAULT_BASE_URL,
    OLLAMA_DEFAULT_MODEL,
    SIMILARITY_THRESHOLD,
    DUPLICATE_WINDOW_DAYS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# AI Analyzer Helpers
# =============================================================================

def createAiAnalyzerFromConfig(
    config: Dict[str, Any],
    database: Optional[Any] = None,
    ollamaManager: Optional[Any] = None,
    promptTemplate: Optional[Any] = None
) -> 'AiAnalyzer':  # type: ignore
    """
    Create an AiAnalyzer from configuration.

    Args:
        config: Configuration dictionary with aiAnalysis section
        database: ObdDatabase instance
        ollamaManager: OllamaManager instance
        promptTemplate: Optional AiPromptTemplate instance

    Returns:
        Configured AiAnalyzer instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        ollama = createOllamaManagerFromConfig(config)
        analyzer = createAiAnalyzerFromConfig(config, db, ollama)
    """
    from .analyzer import AiAnalyzer
    return AiAnalyzer(
        config=config,
        database=database,
        ollamaManager=ollamaManager,
        promptTemplate=promptTemplate
    )


def isAiAnalysisEnabled(config: Dict[str, Any]) -> bool:
    """
    Check if AI analysis is enabled in configuration.

    Args:
        config: Configuration dictionary

    Returns:
        True if AI analysis is enabled
    """
    return config.get('aiAnalysis', {}).get('enabled', False)


def getAiAnalysisConfig(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract AI analysis configuration with defaults.

    Args:
        config: Configuration dictionary

    Returns:
        AI analysis config section with defaults applied
    """
    aiConfig = config.get('aiAnalysis', {})
    return {
        'enabled': aiConfig.get('enabled', False),
        'model': aiConfig.get('model', OLLAMA_DEFAULT_MODEL),
        'ollamaBaseUrl': aiConfig.get('ollamaBaseUrl', OLLAMA_DEFAULT_BASE_URL),
        'maxAnalysesPerDrive': aiConfig.get(
            'maxAnalysesPerDrive',
            DEFAULT_MAX_ANALYSES_PER_DRIVE
        ),
        'focusAreas': aiConfig.get('focusAreas', ['air_fuel_ratio']),
        'promptTemplate': aiConfig.get('promptTemplate', ''),
        'similarityThreshold': aiConfig.get('similarityThreshold', SIMILARITY_THRESHOLD),
        'duplicateWindowDays': aiConfig.get('duplicateWindowDays', DUPLICATE_WINDOW_DAYS),
    }


def connectAnalyzerToStatisticsEngine(
    analyzer: Any,
    statisticsEngine: Any
) -> None:
    """
    Connect AI analyzer to statistics engine for automatic triggering.

    Registers a callback on the statistics engine so that AI analysis
    is automatically triggered after each statistical analysis completes.

    Args:
        analyzer: AiAnalyzer instance
        statisticsEngine: StatisticsEngine instance

    Example:
        analyzer = createAiAnalyzerFromConfig(config, db, ollama)
        engine = createStatisticsEngineFromConfig(db, config)
        connectAnalyzerToStatisticsEngine(analyzer, engine)
    """
    def onAnalysisComplete(result: Any) -> None:
        """Callback for statistics engine completion."""
        if analyzer.isReady():
            logger.info("Statistics analysis complete, triggering AI analysis")
            analyzer.analyzePostDriveAsync(result)
        else:
            logger.debug("AI analyzer not ready, skipping post-drive analysis")

    statisticsEngine.registerCallbacks(
        onAnalysisComplete=onAnalysisComplete
    )
    logger.info("AI analyzer connected to statistics engine")


# =============================================================================
# Ollama Manager Helpers
# =============================================================================

def createOllamaManagerFromConfig(config: Dict[str, Any]) -> 'OllamaManager':  # type: ignore
    """
    Create an OllamaManager from configuration.

    Args:
        config: Configuration dictionary with aiAnalysis section

    Returns:
        Configured OllamaManager instance
    """
    from .ollama import OllamaManager
    return OllamaManager(config=config)


def isOllamaAvailable(config: Dict[str, Any]) -> bool:
    """
    Quick check if ollama is available and enabled.

    Args:
        config: Configuration dictionary

    Returns:
        True if AI analysis is enabled AND ollama is available
    """
    from .ollama import isOllamaAvailable as checkOllama
    return checkOllama(config)


def getOllamaConfig(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract ollama configuration with defaults.

    Args:
        config: Configuration dictionary

    Returns:
        Ollama config section with defaults applied
    """
    from .ollama import getOllamaConfig as getConfig
    return getConfig(config)


# =============================================================================
# Prompt Template Helpers
# =============================================================================

def createPromptTemplateFromConfig(config: Dict[str, Any]) -> 'AiPromptTemplate':  # type: ignore
    """
    Create an AiPromptTemplate from configuration.

    Args:
        config: Configuration dictionary with aiAnalysis section

    Returns:
        Configured AiPromptTemplate instance
    """
    from .prompt_template import AiPromptTemplate
    return AiPromptTemplate(config=config)


def getDefaultPromptTemplate() -> str:
    """
    Get the default prompt template.

    Returns:
        Default prompt template string
    """
    from .prompt_template import getDefaultPromptTemplate as getTemplate
    return getTemplate()


def getDefaultVehicleContext() -> Dict[str, Any]:
    """
    Get the default vehicle context.

    Returns:
        Default vehicle context dictionary
    """
    from .prompt_template import getDefaultVehicleContext as getContext
    return getContext()


def getFocusAreaTemplates() -> Dict[str, str]:
    """
    Get all available focus area templates.

    Returns:
        Dictionary of focus area name to template string
    """
    from .prompt_template import getFocusAreaTemplates as getTemplates
    return getTemplates()


def buildPromptFromMetrics(
    metrics: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
    vehicleContext: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Convenience function to build a prompt from metrics.

    Args:
        metrics: Dictionary of metric values
        config: Optional configuration dictionary
        vehicleContext: Optional vehicle context override

    Returns:
        Generated prompt string
    """
    from .prompt_template import buildPromptFromMetrics as buildPrompt
    return buildPrompt(metrics, config, vehicleContext)


# =============================================================================
# Recommendation Ranker Helpers
# =============================================================================

def createRecommendationRankerFromConfig(
    config: Dict[str, Any],
    database: Any
) -> 'RecommendationRanker':  # type: ignore
    """
    Create a RecommendationRanker from configuration.

    Args:
        config: Configuration dictionary
        database: Database instance

    Returns:
        Configured RecommendationRanker instance
    """
    from .ranker import RecommendationRanker
    aiConfig = config.get('aiAnalysis', {})
    similarityThreshold = aiConfig.get('similarityThreshold', SIMILARITY_THRESHOLD)
    duplicateWindowDays = aiConfig.get('duplicateWindowDays', DUPLICATE_WINDOW_DAYS)

    return RecommendationRanker(
        database=database,
        config=config,
        similarityThreshold=similarityThreshold,
        duplicateWindowDays=duplicateWindowDays
    )


def rankRecommendationText(text: str) -> 'PriorityRank':  # type: ignore
    """
    Determine priority rank for a recommendation based on keywords.

    Args:
        text: Recommendation text to analyze

    Returns:
        PriorityRank based on keyword analysis
    """
    from .ranker import rankRecommendation
    return rankRecommendation(text)


def extractRecommendationKeywords(text: str) -> list:
    """
    Extract keywords from recommendation text.

    Args:
        text: Recommendation text to analyze

    Returns:
        List of extracted keywords (lowercase)
    """
    from .ranker import extractKeywords
    return extractKeywords(text)


def calculateRecommendationSimilarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two recommendation texts.

    Args:
        text1: First text string
        text2: Second text string

    Returns:
        Similarity score from 0.0 to 1.0
    """
    from .ranker import calculateTextSimilarity
    return calculateTextSimilarity(text1, text2)


# =============================================================================
# Data Preparation Helpers
# =============================================================================

def prepareAnalysisDataWindow(
    statisticsResult: Any,
    rawData: Optional[Dict[str, list]] = None
) -> Dict[str, Any]:
    """
    Prepare data window from statistics result for AI analysis.

    Args:
        statisticsResult: AnalysisResult from StatisticsEngine
        rawData: Optional raw parameter data for derived calculations

    Returns:
        Dictionary of metrics for prompt template
    """
    from .data_preparation import prepareDataWindow
    return prepareDataWindow(statisticsResult, rawData)


def extractMetricsFromStatistics(statisticsResult: Any) -> Dict[str, Any]:
    """
    Extract metrics from a statistics result.

    Args:
        statisticsResult: AnalysisResult from StatisticsEngine

    Returns:
        Dictionary of metrics
    """
    from .data_preparation import extractStatisticsMetrics
    return extractStatisticsMetrics(statisticsResult)


def getAvailableMetricKeys() -> list:
    """
    Get all available metric keys that can be extracted.

    Returns:
        List of metric key names
    """
    from .data_preparation import getAvailableMetricKeys
    return getAvailableMetricKeys()


# =============================================================================
# Convenience Initialization
# =============================================================================

def initializeAiComponents(
    config: Dict[str, Any],
    database: Optional[Any] = None,
    statisticsEngine: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Initialize all AI components from configuration.

    Convenience function that creates all AI-related components and
    optionally connects them to the statistics engine.

    Args:
        config: Configuration dictionary with aiAnalysis section
        database: Optional ObdDatabase instance
        statisticsEngine: Optional StatisticsEngine to connect to

    Returns:
        Dictionary with initialized components:
        - 'ollamaManager': OllamaManager instance
        - 'promptTemplate': AiPromptTemplate instance
        - 'analyzer': AiAnalyzer instance (if database provided)
        - 'ranker': RecommendationRanker instance (if database provided)
        - 'enabled': Whether AI analysis is enabled

    Example:
        components = initializeAiComponents(config, database, statsEngine)
        if components['enabled']:
            analyzer = components['analyzer']
            # Use analyzer...
    """
    enabled = isAiAnalysisEnabled(config)

    # Create ollama manager
    ollamaManager = createOllamaManagerFromConfig(config)

    # Create prompt template
    promptTemplate = createPromptTemplateFromConfig(config)

    result: Dict[str, Any] = {
        'ollamaManager': ollamaManager,
        'promptTemplate': promptTemplate,
        'analyzer': None,
        'ranker': None,
        'enabled': enabled,
    }

    # Create analyzer and ranker if database is provided
    if database is not None:
        result['analyzer'] = createAiAnalyzerFromConfig(
            config, database, ollamaManager, promptTemplate
        )
        result['ranker'] = createRecommendationRankerFromConfig(config, database)

        # Connect to statistics engine if provided
        if statisticsEngine is not None and result['analyzer'] is not None:
            connectAnalyzerToStatisticsEngine(result['analyzer'], statisticsEngine)

    return result
