################################################################################
# File Name: exceptions.py
# Purpose/Description: Exception definitions for AI analyzer and recommendation system
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-015 - Extract
#               |              | exceptions from ai_analyzer.py, ai_prompt_template.py,
#               |              | ollama_manager.py, and recommendation_ranker.py
# ================================================================================
################################################################################

"""
Exception definitions for the AI analysis and recommendation system.

This module contains all exception classes used throughout the AI subpackage,
including exceptions for:
- AI analyzer operations (AiAnalyzerError and subclasses)
- Prompt template operations (PromptTemplateError and subclasses)
- Ollama service operations (OllamaError and subclasses)
- Recommendation ranking operations (RecommendationRankerError)

All exceptions follow a consistent pattern with message and details dict attributes.

Usage:
    from ai.exceptions import (
        AiAnalyzerError,
        AiAnalyzerNotAvailableError,
        OllamaError,
        PromptTemplateError,
    )

    try:
        result = analyzer.analyzePostDrive(data)
    except AiAnalyzerNotAvailableError as e:
        print(f"AI not available: {e.message}")
        print(f"Details: {e.details}")
"""

from typing import Any, Dict, Optional


# =============================================================================
# AI Analyzer Exceptions
# =============================================================================

class AiAnalyzerError(Exception):
    """
    Base exception for AI analyzer errors.

    Attributes:
        message: Error message
        details: Additional context as a dictionary
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AiAnalyzerNotAvailableError(AiAnalyzerError):
    """
    Raised when AI analyzer is not available.

    This typically occurs when ollama is not running or the configured
    model is not installed.
    """
    pass


class AiAnalyzerLimitExceededError(AiAnalyzerError):
    """
    Raised when analysis limit per drive is exceeded.

    The AI analyzer has a configurable maximum number of analyses
    per drive session to prevent excessive API calls. This exception
    is raised when that limit is reached.
    """
    pass


class AiAnalyzerGenerationError(AiAnalyzerError):
    """
    Raised when AI model generation fails.

    This can occur due to ollama API errors, network issues,
    or model inference failures.
    """
    pass


# =============================================================================
# Prompt Template Exceptions
# =============================================================================

class PromptTemplateError(Exception):
    """
    Base exception for prompt template errors.

    Attributes:
        message: Error message
        details: Additional context as a dictionary
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidTemplateError(PromptTemplateError):
    """
    Raised when template is invalid or malformed.

    This can occur when:
    - Template has unbalanced braces
    - Template is missing required placeholders
    - Template is too short
    """
    pass


class MissingMetricsError(PromptTemplateError):
    """
    Raised when required metrics are missing for prompt generation.

    While most missing metrics are handled gracefully with defaults,
    this exception may be raised for critical missing data.
    """
    pass


# =============================================================================
# Ollama Manager Exceptions
# =============================================================================

class OllamaError(Exception):
    """
    Base exception for ollama-related errors.

    Attributes:
        message: Error message
        details: Additional context as a dictionary
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class OllamaNotAvailableError(OllamaError):
    """
    Raised when ollama is not installed or not running.

    This exception is raised when the ollama service cannot be reached
    at the configured base URL (default: http://localhost:11434).
    """
    pass


class OllamaModelError(OllamaError):
    """
    Raised when model operations fail.

    This can occur when:
    - Requested model is not installed
    - Model pull/download fails
    - Model verification fails
    """
    pass


# =============================================================================
# Recommendation Ranker Exceptions
# =============================================================================

class RecommendationRankerError(Exception):
    """
    Base exception for recommendation ranker errors.

    Attributes:
        message: Error message
        details: Additional context as a dictionary
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
