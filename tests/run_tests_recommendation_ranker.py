################################################################################
# File Name: run_tests_recommendation_ranker.py
# Purpose/Description: Test suite for RecommendationRanker - ranking and deduplication
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-021
# ================================================================================
################################################################################

"""
Test suite for RecommendationRanker class.

Tests cover:
- Priority ranking based on keywords (safety=1, performance=2, etc.)
- Text similarity detection (>70% threshold)
- Duplicate marking with is_duplicate_of foreign key
- Database integration for storing ranked recommendations
- 30-day window for duplicate detection
- Display filtering (non-duplicates sorted by priority)

Run with: python tests/run_tests_recommendation_ranker.py
"""

import json
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, Mock, patch, call

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.recommendation_ranker import (
    RecommendationRanker,
    RankedRecommendation,
    PriorityRank,
    SimilarityResult,
    RecommendationRankerError,
    calculateTextSimilarity,
    extractKeywords,
    rankRecommendation,
    createRecommendationRankerFromConfig,
    PRIORITY_KEYWORDS,
    SIMILARITY_THRESHOLD,
    DUPLICATE_WINDOW_DAYS,
)
from obd.database import ObdDatabase


# =============================================================================
# Test Configuration
# =============================================================================

def createTestConfig() -> Dict[str, Any]:
    """Create a test configuration dictionary."""
    return {
        "aiAnalysis": {
            "enabled": True,
            "model": "gemma2:2b",
            "ollamaBaseUrl": "http://localhost:11434",
            "maxAnalysesPerDrive": 1,
        },
        "database": {
            "path": ":memory:",
            "walMode": False
        }
    }


def createTestDatabase() -> ObdDatabase:
    """Create a test database with required tables."""
    # Use a temp file for tests that need persistence
    dbPath = tempfile.mktemp(suffix='.db')
    db = ObdDatabase(dbPath, walMode=False)
    db.initialize()
    return db


# =============================================================================
# Test Classes - PriorityRank Enum
# =============================================================================

class TestPriorityRankEnum(unittest.TestCase):
    """Tests for PriorityRank enum."""

    def test_values_exist(self):
        """Verify all expected priority values exist."""
        self.assertEqual(PriorityRank.SAFETY.value, 1)
        self.assertEqual(PriorityRank.PERFORMANCE.value, 2)
        self.assertEqual(PriorityRank.EFFICIENCY.value, 3)
        self.assertEqual(PriorityRank.MINOR_TWEAK.value, 4)
        self.assertEqual(PriorityRank.INFORMATIONAL.value, 5)

    def test_ordering(self):
        """Test that safety has highest priority (lowest value)."""
        self.assertTrue(PriorityRank.SAFETY.value < PriorityRank.PERFORMANCE.value)
        self.assertTrue(PriorityRank.PERFORMANCE.value < PriorityRank.EFFICIENCY.value)
        self.assertTrue(PriorityRank.EFFICIENCY.value < PriorityRank.MINOR_TWEAK.value)
        self.assertTrue(PriorityRank.MINOR_TWEAK.value < PriorityRank.INFORMATIONAL.value)

    def test_fromValue_valid(self):
        """Test conversion from integer value."""
        self.assertEqual(PriorityRank.fromValue(1), PriorityRank.SAFETY)
        self.assertEqual(PriorityRank.fromValue(2), PriorityRank.PERFORMANCE)
        self.assertEqual(PriorityRank.fromValue(3), PriorityRank.EFFICIENCY)
        self.assertEqual(PriorityRank.fromValue(4), PriorityRank.MINOR_TWEAK)
        self.assertEqual(PriorityRank.fromValue(5), PriorityRank.INFORMATIONAL)

    def test_fromValue_invalid_returnsDefault(self):
        """Test invalid value returns INFORMATIONAL as default."""
        self.assertEqual(PriorityRank.fromValue(0), PriorityRank.INFORMATIONAL)
        self.assertEqual(PriorityRank.fromValue(6), PriorityRank.INFORMATIONAL)
        self.assertEqual(PriorityRank.fromValue(-1), PriorityRank.INFORMATIONAL)


# =============================================================================
# Test Classes - RankedRecommendation Dataclass
# =============================================================================

class TestRankedRecommendationDataclass(unittest.TestCase):
    """Tests for RankedRecommendation dataclass."""

    def test_creation_minimal(self):
        """Test minimal RankedRecommendation creation."""
        rec = RankedRecommendation(
            recommendation="Check engine coolant level",
            priorityRank=PriorityRank.SAFETY
        )
        self.assertEqual(rec.recommendation, "Check engine coolant level")
        self.assertEqual(rec.priorityRank, PriorityRank.SAFETY)
        self.assertIsNone(rec.id)
        self.assertIsNone(rec.isDuplicateOf)
        self.assertIsNone(rec.profileId)
        self.assertIsNotNone(rec.timestamp)

    def test_creation_full(self):
        """Test RankedRecommendation with all fields."""
        now = datetime.now()
        rec = RankedRecommendation(
            id=1,
            recommendation="Optimize air/fuel ratio",
            priorityRank=PriorityRank.PERFORMANCE,
            isDuplicateOf=None,
            profileId="daily",
            timestamp=now,
            keywords=["air/fuel", "optimize", "performance"]
        )
        self.assertEqual(rec.id, 1)
        self.assertEqual(rec.priorityRank, PriorityRank.PERFORMANCE)
        self.assertEqual(rec.profileId, "daily")
        self.assertEqual(rec.timestamp, now)
        self.assertEqual(len(rec.keywords), 3)

    def test_toDict(self):
        """Test serialization to dictionary."""
        rec = RankedRecommendation(
            id=1,
            recommendation="Safety check required",
            priorityRank=PriorityRank.SAFETY,
            profileId="track"
        )
        result = rec.toDict()

        self.assertEqual(result['id'], 1)
        self.assertEqual(result['recommendation'], "Safety check required")
        self.assertEqual(result['priorityRank'], 1)
        self.assertEqual(result['priorityName'], "SAFETY")
        self.assertEqual(result['profileId'], "track")
        self.assertIsNone(result['isDuplicateOf'])

    def test_isDuplicate_property(self):
        """Test isDuplicate property."""
        rec1 = RankedRecommendation(
            recommendation="Test",
            priorityRank=PriorityRank.INFORMATIONAL
        )
        self.assertFalse(rec1.isDuplicate)

        rec2 = RankedRecommendation(
            recommendation="Test",
            priorityRank=PriorityRank.INFORMATIONAL,
            isDuplicateOf=5
        )
        self.assertTrue(rec2.isDuplicate)


# =============================================================================
# Test Classes - SimilarityResult Dataclass
# =============================================================================

class TestSimilarityResultDataclass(unittest.TestCase):
    """Tests for SimilarityResult dataclass."""

    def test_creation(self):
        """Test SimilarityResult creation."""
        result = SimilarityResult(
            similarityScore=0.85,
            matchedRecommendationId=5,
            sharedKeywords=["safety", "coolant"]
        )
        self.assertEqual(result.similarityScore, 0.85)
        self.assertEqual(result.matchedRecommendationId, 5)
        self.assertEqual(result.sharedKeywords, ["safety", "coolant"])

    def test_isAboveThreshold(self):
        """Test threshold comparison."""
        # Above threshold
        result1 = SimilarityResult(similarityScore=0.75)
        self.assertTrue(result1.isAboveThreshold())

        # Below threshold
        result2 = SimilarityResult(similarityScore=0.65)
        self.assertFalse(result2.isAboveThreshold())

        # At threshold
        result3 = SimilarityResult(similarityScore=0.70)
        self.assertTrue(result3.isAboveThreshold())

    def test_toDict(self):
        """Test serialization to dictionary."""
        result = SimilarityResult(
            similarityScore=0.82,
            matchedRecommendationId=10,
            sharedKeywords=["performance"]
        )
        d = result.toDict()

        self.assertEqual(d['similarityScore'], 0.82)
        self.assertEqual(d['matchedRecommendationId'], 10)
        self.assertEqual(d['sharedKeywords'], ["performance"])
        self.assertTrue(d['isAboveThreshold'])


# =============================================================================
# Test Classes - Keyword Extraction
# =============================================================================

class TestExtractKeywords(unittest.TestCase):
    """Tests for extractKeywords function."""

    def test_extractKeywords_safetyTerms(self):
        """Test extraction of safety-related keywords."""
        text = "Warning: coolant temperature is critical. Check immediately for safety."
        keywords = extractKeywords(text)

        self.assertIn("warning", keywords)
        self.assertIn("critical", keywords)
        self.assertIn("safety", keywords)
        self.assertIn("coolant", keywords)

    def test_extractKeywords_performanceTerms(self):
        """Test extraction of performance-related keywords."""
        text = "Optimize air/fuel ratio to improve power and acceleration."
        keywords = extractKeywords(text)

        self.assertIn("optimize", keywords)
        self.assertIn("air/fuel", keywords)
        self.assertIn("power", keywords)

    def test_extractKeywords_caseInsensitive(self):
        """Test that extraction is case insensitive."""
        text = "SAFETY CRITICAL WARNING"
        keywords = extractKeywords(text)

        self.assertIn("safety", keywords)
        self.assertIn("critical", keywords)
        self.assertIn("warning", keywords)

    def test_extractKeywords_emptyText(self):
        """Test extraction from empty text."""
        keywords = extractKeywords("")
        self.assertEqual(keywords, [])

    def test_extractKeywords_noKeywords(self):
        """Test text with no recognized keywords."""
        text = "The vehicle is operating within normal parameters."
        keywords = extractKeywords(text)
        # Should still find some common words
        self.assertIsInstance(keywords, list)


# =============================================================================
# Test Classes - Text Similarity
# =============================================================================

class TestCalculateTextSimilarity(unittest.TestCase):
    """Tests for calculateTextSimilarity function."""

    def test_identicalText_returns1(self):
        """Test that identical texts return 1.0 similarity."""
        text = "Check coolant temperature immediately"
        similarity = calculateTextSimilarity(text, text)
        self.assertEqual(similarity, 1.0)

    def test_completelyDifferent_returnsLow(self):
        """Test completely different texts return low similarity."""
        text1 = "Check coolant temperature"
        text2 = "xyz abc 123 qrs"
        similarity = calculateTextSimilarity(text1, text2)
        self.assertLess(similarity, 0.3)

    def test_partialMatch_returnsModerate(self):
        """Test partially matching texts."""
        text1 = "Check coolant temperature for overheating"
        text2 = "Monitor coolant temperature regularly"
        similarity = calculateTextSimilarity(text1, text2)
        # Should have moderate similarity due to shared words
        self.assertGreater(similarity, 0.2)
        self.assertLess(similarity, 0.9)

    def test_emptyText_returns0(self):
        """Test empty text comparison."""
        similarity1 = calculateTextSimilarity("", "some text")
        self.assertEqual(similarity1, 0.0)

        similarity2 = calculateTextSimilarity("some text", "")
        self.assertEqual(similarity2, 0.0)

        similarity3 = calculateTextSimilarity("", "")
        self.assertEqual(similarity3, 0.0)

    def test_caseInsensitive(self):
        """Test similarity is case insensitive."""
        text1 = "Check COOLANT Temperature"
        text2 = "check coolant temperature"
        similarity = calculateTextSimilarity(text1, text2)
        self.assertEqual(similarity, 1.0)

    def test_similarRecommendations(self):
        """Test similarity between similar AI recommendations."""
        text1 = "The air/fuel ratio is running slightly rich. Consider adjusting fuel trim."
        text2 = "Air/fuel mixture appears rich. Fuel trim adjustments recommended."
        similarity = calculateTextSimilarity(text1, text2)
        # Should have some similarity due to shared words
        self.assertGreater(similarity, 0.2)


# =============================================================================
# Test Classes - Priority Ranking
# =============================================================================

class TestRankRecommendation(unittest.TestCase):
    """Tests for rankRecommendation function."""

    def test_safetyKeywords_returnsPriority1(self):
        """Test safety keywords result in priority 1."""
        # Safety-related recommendations
        text1 = "Warning: Coolant temperature critical. Check immediately."
        rank1 = rankRecommendation(text1)
        self.assertEqual(rank1, PriorityRank.SAFETY)

        text2 = "Danger: Oil pressure low. Stop engine to prevent damage."
        rank2 = rankRecommendation(text2)
        self.assertEqual(rank2, PriorityRank.SAFETY)

        text3 = "Safety concern: Check brake fluid levels."
        rank3 = rankRecommendation(text3)
        self.assertEqual(rank3, PriorityRank.SAFETY)

    def test_performanceKeywords_returnsPriority2(self):
        """Test performance keywords result in priority 2."""
        text1 = "Optimize air/fuel ratio for better power output."
        rank1 = rankRecommendation(text1)
        self.assertEqual(rank1, PriorityRank.PERFORMANCE)

        text2 = "Adjust timing advance for improved acceleration."
        rank2 = rankRecommendation(text2)
        self.assertEqual(rank2, PriorityRank.PERFORMANCE)

        text3 = "Boost pressure can be increased for more horsepower."
        rank3 = rankRecommendation(text3)
        self.assertEqual(rank3, PriorityRank.PERFORMANCE)

    def test_efficiencyKeywords_returnsPriority3(self):
        """Test efficiency keywords result in priority 3."""
        text1 = "Fuel efficiency is lower than expected."
        rank1 = rankRecommendation(text1)
        self.assertEqual(rank1, PriorityRank.EFFICIENCY)

        text2 = "Better gas mileage achievable with ECO mode."
        rank2 = rankRecommendation(text2)
        self.assertEqual(rank2, PriorityRank.EFFICIENCY)

        text3 = "Economy driving reduces fuel consumption."
        rank3 = rankRecommendation(text3)
        self.assertEqual(rank3, PriorityRank.EFFICIENCY)

    def test_minorTweakKeywords_returnsPriority4(self):
        """Test minor tweak keywords result in priority 4."""
        text1 = "Consider a slight adjustment to idle speed."
        rank1 = rankRecommendation(text1)
        self.assertEqual(rank1, PriorityRank.MINOR_TWEAK)

        text2 = "A minor tweak to the settings could help."
        rank2 = rankRecommendation(text2)
        self.assertEqual(rank2, PriorityRank.MINOR_TWEAK)

    def test_informationalKeywords_returnsPriority5(self):
        """Test informational content results in priority 5."""
        text1 = "Note: Engine parameters are within normal range."
        rank1 = rankRecommendation(text1)
        self.assertEqual(rank1, PriorityRank.INFORMATIONAL)

        text2 = "For reference, typical values for this sensor are 0.4-0.6V."
        rank2 = rankRecommendation(text2)
        self.assertEqual(rank2, PriorityRank.INFORMATIONAL)

    def test_noKeywords_returnsInformational(self):
        """Test text with no keywords defaults to informational."""
        text = "The vehicle was driven for 30 minutes today."
        rank = rankRecommendation(text)
        self.assertEqual(rank, PriorityRank.INFORMATIONAL)

    def test_multipleCategories_returnsHighestPriority(self):
        """Test that highest priority wins when multiple categories match."""
        # Has both safety and performance keywords - safety should win
        text = "Warning: Optimize cooling system to prevent critical failure."
        rank = rankRecommendation(text)
        self.assertEqual(rank, PriorityRank.SAFETY)


# =============================================================================
# Test Classes - RecommendationRanker Initialization
# =============================================================================

class TestRecommendationRankerInit(unittest.TestCase):
    """Tests for RecommendationRanker initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.db = createTestDatabase()
        self.config = createTestConfig()

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temp database file if it exists
        if hasattr(self.db, 'dbPath') and os.path.exists(self.db.dbPath):
            try:
                os.remove(self.db.dbPath)
            except OSError:
                pass

    def test_initialization_withDatabase(self):
        """Test initialization with database."""
        ranker = RecommendationRanker(database=self.db)
        self.assertIsNotNone(ranker)
        self.assertEqual(ranker.duplicateWindowDays, DUPLICATE_WINDOW_DAYS)
        self.assertEqual(ranker.similarityThreshold, SIMILARITY_THRESHOLD)

    def test_initialization_withConfig(self):
        """Test initialization with config."""
        ranker = RecommendationRanker(database=self.db, config=self.config)
        self.assertIsNotNone(ranker)

    def test_initialization_customThresholds(self):
        """Test initialization with custom thresholds."""
        ranker = RecommendationRanker(
            database=self.db,
            similarityThreshold=0.80,
            duplicateWindowDays=60
        )
        self.assertEqual(ranker.similarityThreshold, 0.80)
        self.assertEqual(ranker.duplicateWindowDays, 60)


# =============================================================================
# Test Classes - RecommendationRanker Ranking
# =============================================================================

class TestRecommendationRankerRanking(unittest.TestCase):
    """Tests for RecommendationRanker ranking functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.db = createTestDatabase()
        self.ranker = RecommendationRanker(database=self.db)

    def tearDown(self):
        """Clean up test fixtures."""
        if hasattr(self.db, 'dbPath') and os.path.exists(self.db.dbPath):
            try:
                os.remove(self.db.dbPath)
            except OSError:
                pass

    def test_rankAndStore_safetyRecommendation(self):
        """Test ranking and storing a safety recommendation."""
        text = "Warning: Critical coolant temperature detected."
        result = self.ranker.rankAndStore(text)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, RankedRecommendation)
        self.assertEqual(result.priorityRank, PriorityRank.SAFETY)
        self.assertIsNotNone(result.id)  # Should have been saved

    def test_rankAndStore_performanceRecommendation(self):
        """Test ranking and storing a performance recommendation."""
        text = "Optimize air/fuel ratio for better power output."
        result = self.ranker.rankAndStore(text)

        self.assertEqual(result.priorityRank, PriorityRank.PERFORMANCE)

    def test_rankAndStore_withProfileId(self):
        """Test ranking with profile association."""
        # First create a profile
        with self.db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO profiles (id, name) VALUES (?, ?)",
                ("track", "Track Day")
            )

        text = "Boost pressure optimization recommended."
        result = self.ranker.rankAndStore(text, profileId="track")

        self.assertEqual(result.profileId, "track")


# =============================================================================
# Test Classes - RecommendationRanker Deduplication
# =============================================================================

class TestRecommendationRankerDeduplication(unittest.TestCase):
    """Tests for RecommendationRanker deduplication functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.db = createTestDatabase()
        self.ranker = RecommendationRanker(database=self.db)

    def tearDown(self):
        """Clean up test fixtures."""
        if hasattr(self.db, 'dbPath') and os.path.exists(self.db.dbPath):
            try:
                os.remove(self.db.dbPath)
            except OSError:
                pass

    def test_detectDuplicate_identicalText(self):
        """Test duplicate detection with identical text."""
        text = "Optimize air/fuel ratio for performance."

        # Store original
        original = self.ranker.rankAndStore(text)
        self.assertIsNone(original.isDuplicateOf)

        # Store duplicate
        duplicate = self.ranker.rankAndStore(text)
        self.assertEqual(duplicate.isDuplicateOf, original.id)

    def test_detectDuplicate_similarText(self):
        """Test duplicate detection with similar text (>70% similarity)."""
        # Using very similar texts that will exceed 70% Jaccard similarity
        text1 = "Check the coolant temperature sensor for overheating issues"
        text2 = "Check the coolant temperature sensor for overheating problems"

        original = self.ranker.rankAndStore(text1)
        similar = self.ranker.rankAndStore(text2)

        # Should be marked as duplicate due to high similarity
        self.assertEqual(similar.isDuplicateOf, original.id)

    def test_noDuplicate_differentText(self):
        """Test no duplicate marking for different text."""
        text1 = "Check coolant temperature for overheating."
        text2 = "Optimize throttle response for acceleration."

        rec1 = self.ranker.rankAndStore(text1)
        rec2 = self.ranker.rankAndStore(text2)

        self.assertIsNone(rec1.isDuplicateOf)
        self.assertIsNone(rec2.isDuplicateOf)

    def test_duplicateWindow_respectsTimeLimit(self):
        """Test that duplicate detection respects the 30-day window."""
        text = "Optimize air/fuel ratio."

        # Store original with old timestamp
        with self.db.connect() as conn:
            cursor = conn.cursor()
            oldDate = datetime.now() - timedelta(days=35)
            cursor.execute(
                """INSERT INTO ai_recommendations
                   (timestamp, recommendation, priority_rank)
                   VALUES (?, ?, ?)""",
                (oldDate.isoformat(), text, 2)
            )

        # Store new recommendation with same text
        new = self.ranker.rankAndStore(text)

        # Should NOT be marked as duplicate (original is > 30 days old)
        self.assertIsNone(new.isDuplicateOf)

    def test_checkSimilarity_returnsResult(self):
        """Test checkSimilarity method returns proper result."""
        text1 = "Check coolant temperature."
        original = self.ranker.rankAndStore(text1)

        text2 = "Check coolant temperature now."
        result = self.ranker.checkSimilarity(text2)

        self.assertIsInstance(result, SimilarityResult)
        self.assertGreater(result.similarityScore, 0.5)
        self.assertEqual(result.matchedRecommendationId, original.id)


# =============================================================================
# Test Classes - RecommendationRanker Display Filtering
# =============================================================================

class TestRecommendationRankerDisplay(unittest.TestCase):
    """Tests for RecommendationRanker display filtering."""

    def setUp(self):
        """Set up test fixtures."""
        self.db = createTestDatabase()
        self.ranker = RecommendationRanker(database=self.db)

    def tearDown(self):
        """Clean up test fixtures."""
        if hasattr(self.db, 'dbPath') and os.path.exists(self.db.dbPath):
            try:
                os.remove(self.db.dbPath)
            except OSError:
                pass

    def test_getDisplayRecommendations_excludesDuplicates(self):
        """Test that display method excludes duplicates."""
        # Add recommendations including duplicates
        rec1 = self.ranker.rankAndStore("Warning: Check coolant level.")
        rec2 = self.ranker.rankAndStore("Optimize throttle response.")
        rec3 = self.ranker.rankAndStore("Warning: Check coolant level.")  # Duplicate

        results = self.ranker.getDisplayRecommendations()

        # Should only show 2 (non-duplicates)
        self.assertEqual(len(results), 2)
        ids = [r.id for r in results]
        self.assertIn(rec1.id, ids)
        self.assertIn(rec2.id, ids)
        self.assertNotIn(rec3.id, ids)

    def test_getDisplayRecommendations_sortedByPriority(self):
        """Test that display results are sorted by priority."""
        # Add in non-priority order
        self.ranker.rankAndStore("Note: Engine running normally.")  # Info (5)
        self.ranker.rankAndStore("Optimize power output.")  # Performance (2)
        self.ranker.rankAndStore("Warning: Critical issue.")  # Safety (1)
        self.ranker.rankAndStore("Improve fuel economy.")  # Efficiency (3)

        results = self.ranker.getDisplayRecommendations()

        # Should be sorted: Safety(1), Performance(2), Efficiency(3), Info(5)
        priorities = [r.priorityRank.value for r in results]
        self.assertEqual(priorities, sorted(priorities))

    def test_getDisplayRecommendations_withLimit(self):
        """Test limiting display results."""
        # Use completely unique recommendations to avoid duplicate detection
        uniqueTexts = [
            "Warning: Engine temperature too high",
            "Optimize fuel mixture for track use",
            "Efficiency could be improved slightly",
            "Note: Sensor readings normal",
            "Consider checking oil level",
            "Power output below expected",
            "Safety check passed successfully",
            "Timing advance within limits",
            "Throttle response acceptable",
            "Economy mode recommended"
        ]
        for text in uniqueTexts:
            self.ranker.rankAndStore(text)

        results = self.ranker.getDisplayRecommendations(limit=5)
        self.assertEqual(len(results), 5)

    def test_getDisplayRecommendations_filterByProfile(self):
        """Test filtering by profile."""
        # Create profiles
        with self.db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO profiles (id, name) VALUES (?, ?)",
                ("daily", "Daily Driver")
            )
            cursor.execute(
                "INSERT INTO profiles (id, name) VALUES (?, ?)",
                ("track", "Track Day")
            )

        # Use unique texts to avoid duplicate detection
        self.ranker.rankAndStore("Warning: Check engine oil for daily driving", profileId="daily")
        self.ranker.rankAndStore("Optimize boost pressure for track racing", profileId="track")
        self.ranker.rankAndStore("Note: Fuel economy normal for commuting", profileId="daily")

        dailyResults = self.ranker.getDisplayRecommendations(profileId="daily")
        trackResults = self.ranker.getDisplayRecommendations(profileId="track")

        self.assertEqual(len(dailyResults), 2)
        self.assertEqual(len(trackResults), 1)


# =============================================================================
# Test Classes - RecommendationRanker Statistics
# =============================================================================

class TestRecommendationRankerStatistics(unittest.TestCase):
    """Tests for RecommendationRanker statistics."""

    def setUp(self):
        """Set up test fixtures."""
        self.db = createTestDatabase()
        self.ranker = RecommendationRanker(database=self.db)

    def tearDown(self):
        """Clean up test fixtures."""
        if hasattr(self.db, 'dbPath') and os.path.exists(self.db.dbPath):
            try:
                os.remove(self.db.dbPath)
            except OSError:
                pass

    def test_getStatistics(self):
        """Test getting statistics about recommendations."""
        self.ranker.rankAndStore("Warning: Critical issue.")
        self.ranker.rankAndStore("Optimize performance.")
        self.ranker.rankAndStore("Warning: Critical issue.")  # Duplicate

        stats = self.ranker.getStatistics()

        self.assertEqual(stats['totalRecommendations'], 3)
        self.assertEqual(stats['uniqueRecommendations'], 2)
        self.assertEqual(stats['duplicateCount'], 1)
        self.assertIn('byPriority', stats)

    def test_getStatistics_byPriority(self):
        """Test statistics breakdown by priority."""
        self.ranker.rankAndStore("Warning: Safety concern.")
        self.ranker.rankAndStore("Optimize power.")
        self.ranker.rankAndStore("Danger: Check now.")

        stats = self.ranker.getStatistics()

        self.assertEqual(stats['byPriority'][1], 2)  # Safety
        self.assertEqual(stats['byPriority'][2], 1)  # Performance


# =============================================================================
# Test Classes - Helper Functions
# =============================================================================

class TestCreateRecommendationRankerFromConfig(unittest.TestCase):
    """Tests for createRecommendationRankerFromConfig helper."""

    def test_createsRankerFromConfig(self):
        """Test creating ranker from configuration."""
        db = createTestDatabase()
        config = createTestConfig()

        ranker = createRecommendationRankerFromConfig(config, db)

        self.assertIsNotNone(ranker)
        self.assertIsInstance(ranker, RecommendationRanker)

        # Cleanup
        if os.path.exists(db.dbPath):
            os.remove(db.dbPath)


# =============================================================================
# Test Classes - Constants
# =============================================================================

class TestConstants(unittest.TestCase):
    """Tests for module constants."""

    def test_similarityThreshold(self):
        """Test default similarity threshold is 0.70."""
        self.assertEqual(SIMILARITY_THRESHOLD, 0.70)

    def test_duplicateWindowDays(self):
        """Test default duplicate window is 30 days."""
        self.assertEqual(DUPLICATE_WINDOW_DAYS, 30)

    def test_priorityKeywords_exist(self):
        """Test priority keywords dictionary exists with all categories."""
        self.assertIn(1, PRIORITY_KEYWORDS)  # Safety
        self.assertIn(2, PRIORITY_KEYWORDS)  # Performance
        self.assertIn(3, PRIORITY_KEYWORDS)  # Efficiency
        self.assertIn(4, PRIORITY_KEYWORDS)  # Minor tweaks
        self.assertIn(5, PRIORITY_KEYWORDS)  # Informational

    def test_safetyKeywords_include(self):
        """Test safety keywords include expected terms."""
        safetyWords = PRIORITY_KEYWORDS[1]
        self.assertIn("warning", safetyWords)
        self.assertIn("critical", safetyWords)
        self.assertIn("danger", safetyWords)
        self.assertIn("safety", safetyWords)

    def test_performanceKeywords_include(self):
        """Test performance keywords include expected terms."""
        perfWords = PRIORITY_KEYWORDS[2]
        self.assertIn("optimize", perfWords)
        self.assertIn("performance", perfWords)
        self.assertIn("power", perfWords)


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    # Configure logging for tests
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run tests
    unittest.main(verbosity=2)
