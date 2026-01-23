################################################################################
# File Name: recommendation_ranker.py
# Purpose/Description: Ranking and deduplication of AI recommendations
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-021
# 2026-01-22    | Ralph Agent   | US-016 - Re-export from ai subpackage
# ================================================================================
################################################################################

"""
AI recommendation ranking and deduplication module.

This module re-exports from the obd.ai subpackage for backward compatibility.
New code should import directly from obd.ai.

Provides priority ranking based on keywords and semantic similarity detection
to identify duplicate recommendations before storing them in the database.

Usage (backward compatible):
    from obd.recommendation_ranker import (
        RecommendationRanker,
        createRecommendationRankerFromConfig
    )

Recommended usage (new code):
    from obd.ai import (
        RecommendationRanker,
        createRecommendationRankerFromConfig
    )
"""

# Re-export from ai subpackage for backward compatibility
from obd.ai import (
    # Constants
    SIMILARITY_THRESHOLD,
    DUPLICATE_WINDOW_DAYS,
    PRIORITY_KEYWORDS,
    ALL_KEYWORDS,
    DOMAIN_KEYWORDS,

    # Enums
    PriorityRank,

    # Dataclasses
    RankedRecommendation,
    SimilarityResult,

    # Exceptions
    RecommendationRankerError,

    # Class
    RecommendationRanker,

    # Helper functions
    extractKeywords,
    calculateTextSimilarity,
    rankRecommendation,
    createRecommendationRankerFromConfig,
)


__all__ = [
    # Constants
    'SIMILARITY_THRESHOLD',
    'DUPLICATE_WINDOW_DAYS',
    'PRIORITY_KEYWORDS',
    'ALL_KEYWORDS',
    'DOMAIN_KEYWORDS',

    # Enums
    'PriorityRank',

    # Dataclasses
    'RankedRecommendation',
    'SimilarityResult',

    # Exceptions
    'RecommendationRankerError',

    # Class
    'RecommendationRanker',

    # Helper functions
    'extractKeywords',
    'calculateTextSimilarity',
    'rankRecommendation',
    'createRecommendationRankerFromConfig',
]
