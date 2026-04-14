################################################################################
# File Name: analyzer_db.py
# Purpose/Description: Database helpers for the AI analyzer (save/fetch recommendations)
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-016
# 2026-04-14    | Sweep 5      | Extracted from analyzer.py (task 4 split)
# ================================================================================
################################################################################

"""
Database helpers for the AI analyzer.

Module-level functions for inserting and retrieving AiRecommendation rows.
The AiAnalyzer class keeps the Database reference and delegates row-level
IO to these stateless helpers.
"""

import logging
from typing import Any

from .types import AiRecommendation

logger = logging.getLogger(__name__)


def saveRecommendationToDb(
    database: Any,
    recommendation: AiRecommendation,
) -> int:
    """
    Save a recommendation row to the database.

    Args:
        database: ObdDatabase instance
        recommendation: AiRecommendation to persist

    Returns:
        Database ID of the inserted row
    """
    with database.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ai_recommendations
            (timestamp, recommendation, priority_rank, is_duplicate_of, profile_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                recommendation.timestamp,
                recommendation.recommendation,
                recommendation.priorityRank,
                recommendation.isDuplicateOf,
                recommendation.profileId,
            )
        )
        return cursor.lastrowid


def fetchRecommendations(
    database: Any | None,
    profileId: str | None = None,
    limit: int = 10,
    excludeDuplicates: bool = True,
) -> list[AiRecommendation]:
    """
    Get recent AI recommendations from the database.

    Args:
        database: ObdDatabase instance (or None)
        profileId: Profile to filter by (None for all)
        limit: Maximum number of recommendations to return
        excludeDuplicates: Whether to exclude duplicate recommendations

    Returns:
        List of AiRecommendation objects (empty on error or no database)
    """
    if not database:
        return []

    try:
        with database.connect() as conn:
            cursor = conn.cursor()

            if excludeDuplicates:
                if profileId:
                    cursor.execute(
                        """
                        SELECT id, timestamp, recommendation, priority_rank,
                               is_duplicate_of, profile_id
                        FROM ai_recommendations
                        WHERE profile_id = ? AND is_duplicate_of IS NULL
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (profileId, limit)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, timestamp, recommendation, priority_rank,
                               is_duplicate_of, profile_id
                        FROM ai_recommendations
                        WHERE is_duplicate_of IS NULL
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (limit,)
                    )
            else:
                if profileId:
                    cursor.execute(
                        """
                        SELECT id, timestamp, recommendation, priority_rank,
                               is_duplicate_of, profile_id
                        FROM ai_recommendations
                        WHERE profile_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (profileId, limit)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, timestamp, recommendation, priority_rank,
                               is_duplicate_of, profile_id
                        FROM ai_recommendations
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (limit,)
                    )

            recommendations = []
            for row in cursor.fetchall():
                recommendations.append(AiRecommendation(
                    id=row['id'],
                    timestamp=row['timestamp'],
                    recommendation=row['recommendation'],
                    priorityRank=row['priority_rank'],
                    isDuplicateOf=row['is_duplicate_of'],
                    profileId=row['profile_id'],
                ))

            return recommendations

    except Exception as e:
        logger.error(f"Error retrieving recommendations: {e}")
        return []


def fetchRecommendationById(
    database: Any | None,
    recommendationId: int,
) -> AiRecommendation | None:
    """
    Get a specific recommendation by ID.

    Args:
        database: ObdDatabase instance (or None)
        recommendationId: Database ID of the recommendation

    Returns:
        AiRecommendation or None if not found or on error
    """
    if not database:
        return None

    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, recommendation, priority_rank,
                       is_duplicate_of, profile_id
                FROM ai_recommendations
                WHERE id = ?
                """,
                (recommendationId,)
            )

            row = cursor.fetchone()
            if row:
                return AiRecommendation(
                    id=row['id'],
                    timestamp=row['timestamp'],
                    recommendation=row['recommendation'],
                    priorityRank=row['priority_rank'],
                    isDuplicateOf=row['is_duplicate_of'],
                    profileId=row['profile_id'],
                )
            return None

    except Exception as e:
        logger.error(f"Error retrieving recommendation {recommendationId}: {e}")
        return None


def fetchRecommendationCount(
    database: Any | None,
    profileId: str | None = None,
    excludeDuplicates: bool = True,
) -> int:
    """
    Get count of recommendations.

    Args:
        database: ObdDatabase instance (or None)
        profileId: Profile to filter by (None for all)
        excludeDuplicates: Whether to exclude duplicates

    Returns:
        Count of recommendations (0 on error or no database)
    """
    if not database:
        return 0

    try:
        with database.connect() as conn:
            cursor = conn.cursor()

            whereClause = []
            params = []

            if profileId:
                whereClause.append("profile_id = ?")
                params.append(profileId)
            if excludeDuplicates:
                whereClause.append("is_duplicate_of IS NULL")

            query = "SELECT COUNT(*) as count FROM ai_recommendations"
            if whereClause:
                query += " WHERE " + " AND ".join(whereClause)

            cursor.execute(query, params)
            row = cursor.fetchone()
            return row['count'] if row else 0

    except Exception as e:
        logger.error(f"Error counting recommendations: {e}")
        return 0
