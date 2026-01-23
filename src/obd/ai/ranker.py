################################################################################
# File Name: ranker.py
# Purpose/Description: Ranking and deduplication of AI recommendations
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-016 - Move from
#               |              | recommendation_ranker.py to ai subpackage
# ================================================================================
################################################################################

"""
AI recommendation ranking and deduplication module.

Provides priority ranking based on keywords and semantic similarity detection
to identify duplicate recommendations before storing them in the database.

Priority Ranking (1=highest, 5=lowest):
- 1 (SAFETY): Safety issues - warnings, critical conditions, danger
- 2 (PERFORMANCE): Performance gains - optimize, power, acceleration
- 3 (EFFICIENCY): Efficiency - fuel economy, mileage, consumption
- 4 (MINOR_TWEAK): Minor tweaks - slight adjustments, fine-tune
- 5 (INFORMATIONAL): Informational - notes, references, FYI

Deduplication:
- Checks last 30 days of recommendations for similarity
- Uses >70% text similarity threshold or same keywords
- Marks duplicates with is_duplicate_of foreign key

Usage:
    from obd.ai.ranker import (
        RecommendationRanker,
        createRecommendationRankerFromConfig,
        rankRecommendation,
        extractKeywords,
    )

    # Create ranker with database
    ranker = RecommendationRanker(database=db)

    # Rank and store a recommendation
    result = ranker.rankAndStore("Warning: Coolant temperature critical.")
    print(f"Priority: {result.priorityRank.value}")

    # Get display recommendations (non-duplicates, sorted by priority)
    recommendations = ranker.getDisplayRecommendations()
    for rec in recommendations:
        print(f"[{rec.priorityRank.name}] {rec.recommendation}")
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from .types import (
    PriorityRank,
    RankedRecommendation,
    SimilarityResult,
    SIMILARITY_THRESHOLD,
    DUPLICATE_WINDOW_DAYS,
)
from .exceptions import RecommendationRankerError

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Priority keyword mappings (priority level -> set of keywords)
PRIORITY_KEYWORDS: Dict[int, Set[str]] = {
    # Priority 1: Safety issues
    1: {
        "warning", "critical", "danger", "dangerous", "hazard", "hazardous",
        "safety", "emergency", "urgent", "immediately", "stop", "failure",
        "fail", "damage", "damaging", "overheating", "overheat", "leak",
        "leaking", "fire", "risk", "risky", "caution", "alert"
    },
    # Priority 2: Performance gains
    2: {
        "optimize", "optimization", "performance", "power", "horsepower",
        "torque", "acceleration", "boost", "turbo", "tune", "tuning",
        "upgrade", "improve", "improvement", "enhance", "enhancement",
        "gain", "gains", "increase", "maximize", "max"
    },
    # Priority 3: Efficiency
    3: {
        "efficiency", "efficient", "economy", "economical", "mileage",
        "mpg", "consumption", "fuel-efficient", "eco", "save", "saving",
        "savings", "reduce", "reduction", "lower", "decrease"
    },
    # Priority 4: Minor tweaks
    4: {
        "slight", "slightly", "minor", "small", "little", "fine-tune",
        "fine", "adjust", "adjustment", "tweak", "refine", "refinement",
        "subtle", "marginal", "incremental", "consider", "optional"
    },
    # Priority 5: Informational
    5: {
        "note", "notes", "fyi", "reference", "typical", "normal",
        "information", "informational", "background", "context", "general",
        "overview", "summary", "observe", "observation"
    }
}

# All keywords flattened for extraction
ALL_KEYWORDS: Set[str] = set()
for keywords in PRIORITY_KEYWORDS.values():
    ALL_KEYWORDS.update(keywords)

# Additional domain-specific keywords for extraction
DOMAIN_KEYWORDS: Set[str] = {
    "air/fuel", "fuel", "trim", "coolant", "temperature", "temp",
    "oil", "pressure", "rpm", "throttle", "maf", "o2", "sensor",
    "engine", "timing", "advance", "retard", "knock", "intake",
    "exhaust", "rich", "lean", "ratio", "mixture", "injector",
    "spark", "plug", "valve", "cam", "compression"
}


# =============================================================================
# Helper Functions
# =============================================================================

def extractKeywords(text: str) -> List[str]:
    """
    Extract keywords from recommendation text.

    Args:
        text: Recommendation text to analyze

    Returns:
        List of extracted keywords (lowercase)
    """
    if not text:
        return []

    keywords: List[str] = []
    textLower = text.lower()

    # Check for priority keywords
    for keyword in ALL_KEYWORDS:
        if keyword in textLower:
            keywords.append(keyword)

    # Check for domain keywords
    for keyword in DOMAIN_KEYWORDS:
        if keyword in textLower:
            keywords.append(keyword)

    # Remove duplicates while preserving order
    seen: Set[str] = set()
    unique: List[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)

    return unique


def calculateTextSimilarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two text strings using word overlap.

    Uses Jaccard similarity coefficient on word sets.

    Args:
        text1: First text string
        text2: Second text string

    Returns:
        Similarity score from 0.0 (no similarity) to 1.0 (identical)
    """
    if not text1 or not text2:
        return 0.0

    # Normalize and tokenize
    def tokenize(text: str) -> Set[str]:
        # Remove punctuation and convert to lowercase
        cleaned = re.sub(r'[^\w\s/]', '', text.lower())
        # Split on whitespace
        words = set(cleaned.split())
        # Remove very short words
        return {w for w in words if len(w) > 2}

    words1 = tokenize(text1)
    words2 = tokenize(text2)

    if not words1 or not words2:
        return 0.0

    # Jaccard similarity: intersection / union
    intersection = words1 & words2
    union = words1 | words2

    return len(intersection) / len(union)


def rankRecommendation(text: str) -> PriorityRank:
    """
    Determine priority rank for a recommendation based on keywords.

    Checks for keywords in priority order (safety first) and returns
    the highest matching priority.

    Args:
        text: Recommendation text to analyze

    Returns:
        PriorityRank based on keyword analysis
    """
    if not text:
        return PriorityRank.INFORMATIONAL

    textLower = text.lower()

    # Check in priority order (lowest value = highest priority)
    for priority in range(1, 6):
        keywords = PRIORITY_KEYWORDS.get(priority, set())
        for keyword in keywords:
            if keyword in textLower:
                return PriorityRank.fromValue(priority)

    # Default to informational if no keywords match
    return PriorityRank.INFORMATIONAL


def getPriorityKeywords() -> Dict[int, Set[str]]:
    """
    Get the priority keyword mappings.

    Returns:
        Dictionary mapping priority levels to keyword sets
    """
    return {k: v.copy() for k, v in PRIORITY_KEYWORDS.items()}


def getDomainKeywords() -> Set[str]:
    """
    Get the domain-specific keywords.

    Returns:
        Set of domain keywords
    """
    return DOMAIN_KEYWORDS.copy()


# =============================================================================
# RecommendationRanker Class
# =============================================================================

class RecommendationRanker:
    """
    Ranks and deduplicates AI-generated recommendations.

    Provides priority ranking based on keyword analysis and duplicate
    detection using text similarity. Stores recommendations in the database
    with appropriate priority_rank and is_duplicate_of values.

    Attributes:
        database: ObdDatabase instance for storage
        similarityThreshold: Threshold for duplicate detection (default 0.70)
        duplicateWindowDays: Days to look back for duplicates (default 30)

    Example:
        ranker = RecommendationRanker(database=db)

        # Store a new recommendation
        result = ranker.rankAndStore("Warning: Check coolant immediately.")
        print(f"Stored with priority {result.priorityRank.value}")

        # Get recommendations for display
        recs = ranker.getDisplayRecommendations()
    """

    def __init__(
        self,
        database: Any,
        config: Optional[Dict[str, Any]] = None,
        similarityThreshold: float = SIMILARITY_THRESHOLD,
        duplicateWindowDays: int = DUPLICATE_WINDOW_DAYS
    ):
        """
        Initialize RecommendationRanker.

        Args:
            database: ObdDatabase instance for storing recommendations
            config: Optional configuration dictionary
            similarityThreshold: Similarity threshold for duplicates (0.0-1.0)
            duplicateWindowDays: Days to look back for duplicate detection
        """
        self._database = database
        self._config = config or {}
        self._similarityThreshold = similarityThreshold
        self._duplicateWindowDays = duplicateWindowDays

        logger.debug(
            f"RecommendationRanker initialized with threshold={similarityThreshold}, "
            f"window={duplicateWindowDays} days"
        )

    @property
    def similarityThreshold(self) -> float:
        """Get the similarity threshold for duplicate detection."""
        return self._similarityThreshold

    @property
    def duplicateWindowDays(self) -> int:
        """Get the duplicate window in days."""
        return self._duplicateWindowDays

    def rankAndStore(
        self,
        recommendation: str,
        profileId: Optional[str] = None,
        timestamp: Optional[datetime] = None
    ) -> RankedRecommendation:
        """
        Rank a recommendation and store it in the database.

        Analyzes the recommendation text for priority keywords, checks for
        duplicates in the last 30 days, and stores with appropriate metadata.

        Args:
            recommendation: The AI-generated recommendation text
            profileId: Optional profile ID to associate with
            timestamp: Optional timestamp (defaults to now)

        Returns:
            RankedRecommendation with assigned priority and duplicate info
        """
        if timestamp is None:
            timestamp = datetime.now()

        # Determine priority rank
        priorityRank = rankRecommendation(recommendation)

        # Extract keywords
        keywords = extractKeywords(recommendation)

        # Check for duplicates
        similarityResult = self.checkSimilarity(recommendation)
        isDuplicateOf = None

        if similarityResult.isAboveThreshold(self._similarityThreshold):
            isDuplicateOf = similarityResult.matchedRecommendationId
            logger.info(
                f"Recommendation marked as duplicate of {isDuplicateOf} "
                f"(similarity={similarityResult.similarityScore:.2f})"
            )

        # Store in database
        with self._database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO ai_recommendations
                   (timestamp, recommendation, priority_rank, is_duplicate_of, profile_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    timestamp.isoformat(),
                    recommendation,
                    priorityRank.value,
                    isDuplicateOf,
                    profileId
                )
            )
            recId = cursor.lastrowid

        logger.info(
            f"Stored recommendation {recId} with priority {priorityRank.name}"
        )

        return RankedRecommendation(
            id=recId,
            recommendation=recommendation,
            priorityRank=priorityRank,
            isDuplicateOf=isDuplicateOf,
            profileId=profileId,
            timestamp=timestamp,
            keywords=keywords
        )

    def checkSimilarity(
        self,
        recommendation: str,
        profileId: Optional[str] = None
    ) -> SimilarityResult:
        """
        Check similarity against existing recommendations in the window.

        Args:
            recommendation: Text to check for similarity
            profileId: Optional profile ID to filter by

        Returns:
            SimilarityResult with highest similarity found
        """
        windowStart = datetime.now() - timedelta(days=self._duplicateWindowDays)

        # Get recent recommendations
        with self._database.connect() as conn:
            cursor = conn.cursor()

            if profileId:
                cursor.execute(
                    """SELECT id, recommendation FROM ai_recommendations
                       WHERE timestamp >= ?
                       AND (profile_id = ? OR profile_id IS NULL)
                       AND is_duplicate_of IS NULL""",
                    (windowStart.isoformat(), profileId)
                )
            else:
                cursor.execute(
                    """SELECT id, recommendation FROM ai_recommendations
                       WHERE timestamp >= ?
                       AND is_duplicate_of IS NULL""",
                    (windowStart.isoformat(),)
                )

            rows = cursor.fetchall()

        if not rows:
            return SimilarityResult()

        # Find highest similarity
        bestSimilarity = 0.0
        bestMatchId: Optional[int] = None
        bestSharedKeywords: List[str] = []

        inputKeywords = set(extractKeywords(recommendation))

        for row in rows:
            recId = row['id']
            existingText = row['recommendation']

            similarity = calculateTextSimilarity(recommendation, existingText)

            if similarity > bestSimilarity:
                bestSimilarity = similarity
                bestMatchId = recId

                # Find shared keywords
                existingKeywords = set(extractKeywords(existingText))
                bestSharedKeywords = list(inputKeywords & existingKeywords)

        return SimilarityResult(
            similarityScore=bestSimilarity,
            matchedRecommendationId=bestMatchId,
            sharedKeywords=bestSharedKeywords
        )

    def getDisplayRecommendations(
        self,
        limit: Optional[int] = None,
        profileId: Optional[str] = None
    ) -> List[RankedRecommendation]:
        """
        Get recommendations for display (non-duplicates, sorted by priority).

        Args:
            limit: Maximum number of recommendations to return
            profileId: Optional profile ID to filter by

        Returns:
            List of RankedRecommendation sorted by priority (highest first)
        """
        with self._database.connect() as conn:
            cursor = conn.cursor()

            query = """
                SELECT id, timestamp, recommendation, priority_rank,
                       is_duplicate_of, profile_id
                FROM ai_recommendations
                WHERE is_duplicate_of IS NULL
            """
            params: List[Any] = []

            if profileId:
                query += " AND profile_id = ?"
                params.append(profileId)

            query += " ORDER BY priority_rank ASC, timestamp DESC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

        recommendations: List[RankedRecommendation] = []
        for row in rows:
            # Parse timestamp
            ts = row['timestamp']
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)

            recommendations.append(RankedRecommendation(
                id=row['id'],
                recommendation=row['recommendation'],
                priorityRank=PriorityRank.fromValue(row['priority_rank']),
                isDuplicateOf=row['is_duplicate_of'],
                profileId=row['profile_id'],
                timestamp=ts,
                keywords=extractKeywords(row['recommendation'])
            ))

        return recommendations

    def getStatistics(self) -> Dict[str, Any]:
        """
        Get statistics about stored recommendations.

        Returns:
            Dictionary with statistics including:
            - totalRecommendations: Total count
            - uniqueRecommendations: Non-duplicate count
            - duplicateCount: Duplicate count
            - byPriority: Count by priority level
        """
        with self._database.connect() as conn:
            cursor = conn.cursor()

            # Total count
            cursor.execute("SELECT COUNT(*) FROM ai_recommendations")
            total = cursor.fetchone()[0]

            # Unique count (non-duplicates)
            cursor.execute(
                "SELECT COUNT(*) FROM ai_recommendations WHERE is_duplicate_of IS NULL"
            )
            unique = cursor.fetchone()[0]

            # Count by priority
            cursor.execute(
                """SELECT priority_rank, COUNT(*) as count
                   FROM ai_recommendations
                   WHERE is_duplicate_of IS NULL
                   GROUP BY priority_rank"""
            )
            byPriority: Dict[int, int] = {}
            for row in cursor.fetchall():
                byPriority[row['priority_rank']] = row['count']

        return {
            'totalRecommendations': total,
            'uniqueRecommendations': unique,
            'duplicateCount': total - unique,
            'byPriority': byPriority
        }

    def getById(self, recommendationId: int) -> Optional[RankedRecommendation]:
        """
        Get a recommendation by its ID.

        Args:
            recommendationId: Database ID of the recommendation

        Returns:
            RankedRecommendation or None if not found
        """
        with self._database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT id, timestamp, recommendation, priority_rank,
                          is_duplicate_of, profile_id
                   FROM ai_recommendations
                   WHERE id = ?""",
                (recommendationId,)
            )
            row = cursor.fetchone()

        if not row:
            return None

        ts = row['timestamp']
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        return RankedRecommendation(
            id=row['id'],
            recommendation=row['recommendation'],
            priorityRank=PriorityRank.fromValue(row['priority_rank']),
            isDuplicateOf=row['is_duplicate_of'],
            profileId=row['profile_id'],
            timestamp=ts,
            keywords=extractKeywords(row['recommendation'])
        )


# =============================================================================
# Factory Functions
# =============================================================================

def createRecommendationRankerFromConfig(
    config: Dict[str, Any],
    database: Any
) -> RecommendationRanker:
    """
    Create a RecommendationRanker from configuration.

    Args:
        config: Configuration dictionary
        database: Database instance

    Returns:
        Configured RecommendationRanker instance
    """
    aiConfig = config.get('aiAnalysis', {})
    similarityThreshold = aiConfig.get('similarityThreshold', SIMILARITY_THRESHOLD)
    duplicateWindowDays = aiConfig.get('duplicateWindowDays', DUPLICATE_WINDOW_DAYS)

    return RecommendationRanker(
        database=database,
        config=config,
        similarityThreshold=similarityThreshold,
        duplicateWindowDays=duplicateWindowDays
    )
