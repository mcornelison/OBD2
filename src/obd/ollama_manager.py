################################################################################
# File Name: ollama_manager.py
# Purpose/Description: Ollama installation and model management for AI analysis
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-018
# 2026-01-22    | Ralph Agent   | US-016 - Re-export from ai subpackage
# ================================================================================
################################################################################

"""
Ollama management module for AI-based analysis features.

This module re-exports from the ai subpackage for backward compatibility.
New code should import directly from ai.

Provides installation detection, model verification, and download functionality
for the ollama local LLM server. Gracefully disables AI features when ollama
is unavailable to ensure the system continues operating normally.

Usage (backward compatible):
    from obd.ollama_manager import OllamaManager

Recommended usage (new code):
    from ai import OllamaManager
"""

# Re-export from ai subpackage for backward compatibility
from ai import (
    # Constants
    OLLAMA_DEFAULT_BASE_URL,
    OLLAMA_DEFAULT_MODEL,
    OLLAMA_HEALTH_TIMEOUT,
    OLLAMA_API_TIMEOUT,
    OLLAMA_PULL_TIMEOUT,
    OLLAMA_AVAILABLE,

    # Enums
    OllamaState,

    # Dataclasses
    OllamaStatus,
    ModelInfo,

    # Exceptions
    OllamaError,
    OllamaNotAvailableError,
    OllamaModelError,

    # Class
    OllamaManager,

    # Helper functions
    createOllamaManagerFromConfig,
    isOllamaAvailable,
    getOllamaConfig,
)


__all__ = [
    # Constants
    'OLLAMA_DEFAULT_BASE_URL',
    'OLLAMA_DEFAULT_MODEL',
    'OLLAMA_HEALTH_TIMEOUT',
    'OLLAMA_API_TIMEOUT',
    'OLLAMA_PULL_TIMEOUT',
    'OLLAMA_AVAILABLE',

    # Enums
    'OllamaState',

    # Dataclasses
    'OllamaStatus',
    'ModelInfo',

    # Exceptions
    'OllamaError',
    'OllamaNotAvailableError',
    'OllamaModelError',

    # Class
    'OllamaManager',

    # Helper functions
    'createOllamaManagerFromConfig',
    'isOllamaAvailable',
    'getOllamaConfig',
]
