################################################################################
# File Name: ai_prompt_template.py
# Purpose/Description: AI recommendation prompt templates for OBD-II analysis
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-020
# 2026-01-22    | Ralph Agent   | US-016 - Re-export from ai subpackage
# ================================================================================
################################################################################

"""
AI prompt template module for the Eclipse OBD-II Performance Monitoring System.

This module re-exports from the ai subpackage for backward compatibility.
New code should import directly from ai.

Provides prompt templates for generating AI-based performance recommendations.
Templates include vehicle context, relevant OBD-II metrics, and specific
questions about air/fuel tuning opportunities.

Usage (backward compatible):
    from obd.ai_prompt_template import (
        AiPromptTemplate,
        buildPromptFromMetrics,
        getDefaultPromptTemplate
    )

Recommended usage (new code):
    from ai import (
        AiPromptTemplate,
        buildPromptFromMetrics,
        getDefaultPromptTemplate
    )
"""

# Re-export from ai subpackage for backward compatibility
from ai import (
    # Constants
    VEHICLE_CONTEXT,
    DEFAULT_PROMPT_TEMPLATE,
    METRIC_PLACEHOLDERS,
    FOCUS_AREA_TEMPLATES,

    # Enums
    FocusArea,

    # Dataclasses
    PromptMetrics,
    GeneratedPrompt,

    # Exceptions
    PromptTemplateError,
    InvalidTemplateError,
    MissingMetricsError,

    # Class
    AiPromptTemplate,

    # Helper functions
    getDefaultPromptTemplate,
    getDefaultVehicleContext,
    getFocusAreaTemplates,
    buildPromptFromMetrics,
    createPromptTemplateFromConfig,
    extractMetricsFromStatistics,
)


__all__ = [
    # Constants
    'VEHICLE_CONTEXT',
    'DEFAULT_PROMPT_TEMPLATE',
    'METRIC_PLACEHOLDERS',
    'FOCUS_AREA_TEMPLATES',

    # Enums
    'FocusArea',

    # Dataclasses
    'PromptMetrics',
    'GeneratedPrompt',

    # Exceptions
    'PromptTemplateError',
    'InvalidTemplateError',
    'MissingMetricsError',

    # Class
    'AiPromptTemplate',

    # Helper functions
    'getDefaultPromptTemplate',
    'getDefaultVehicleContext',
    'getFocusAreaTemplates',
    'buildPromptFromMetrics',
    'createPromptTemplateFromConfig',
    'extractMetricsFromStatistics',
]
