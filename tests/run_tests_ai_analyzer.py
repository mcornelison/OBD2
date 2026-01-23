################################################################################
# File Name: run_tests_ai_analyzer.py
# Purpose/Description: Tests for AI-based post-drive analysis module
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-019
# ================================================================================
################################################################################

"""
Tests for the AI analyzer module.

Tests cover:
- AiAnalyzer initialization and configuration
- Post-drive analysis triggering
- Data window preparation
- Ollama integration (mocked)
- Recommendation storage and retrieval
- Analysis limiting (max per drive)
- Statistics tracking
- Helper functions

Run with: python tests/run_tests_ai_analyzer.py
Or via pytest: pytest tests/run_tests_ai_analyzer.py -v
"""

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.obd.ai_analyzer import (
    AiAnalyzer,
    AiRecommendation,
    AnalysisResult,
    AnalyzerState,
    AnalyzerStats,
    AiAnalyzerError,
    AiAnalyzerNotAvailableError,
    AiAnalyzerLimitExceededError,
    AiAnalyzerGenerationError,
    createAiAnalyzerFromConfig,
    isAiAnalysisEnabled,
    getAiAnalysisConfig,
    connectAnalyzerToStatisticsEngine,
    DEFAULT_MAX_ANALYSES_PER_DRIVE,
    OLLAMA_DEFAULT_BASE_URL,
)


# =============================================================================
# Test Fixtures and Helpers
# =============================================================================

def createTestConfig(
    enabled: bool = True,
    model: str = 'gemma2:2b',
    maxPerDrive: int = 1
) -> Dict[str, Any]:
    """Create a test configuration dictionary."""
    return {
        'aiAnalysis': {
            'enabled': enabled,
            'model': model,
            'ollamaBaseUrl': 'http://localhost:11434',
            'maxAnalysesPerDrive': maxPerDrive,
            'focusAreas': ['air_fuel_ratio'],
        },
        'profiles': {
            'activeProfile': 'daily'
        }
    }


def createTestDatabase() -> Any:
    """Create a test database with ai_recommendations table."""
    dbPath = tempfile.mktemp(suffix='.db')
    conn = sqlite3.connect(dbPath)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            recommendation TEXT NOT NULL,
            priority_rank INTEGER DEFAULT 3
                CHECK (priority_rank >= 1 AND priority_rank <= 5),
            is_duplicate_of INTEGER,
            profile_id TEXT,
            FOREIGN KEY (is_duplicate_of)
                REFERENCES ai_recommendations(id)
                ON DELETE SET NULL
        )
    """)
    conn.commit()
    conn.close()

    # Create database wrapper
    class MockDatabase:
        def __init__(self, path):
            self.path = path

        def connect(self):
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            return conn

    return MockDatabase(dbPath)


def createMockOllamaManager(ready: bool = True) -> MagicMock:
    """Create a mock OllamaManager."""
    manager = MagicMock()
    manager.isReady.return_value = ready
    manager.isEnabled = True
    return manager


def createMockStatisticsResult(
    profileId: str = 'daily',
    includeStats: bool = True
) -> Any:
    """Create a mock statistics result."""
    @dataclass
    class MockParameterStats:
        parameterName: str
        avgValue: Optional[float] = None
        maxValue: Optional[float] = None
        minValue: Optional[float] = None

    @dataclass
    class MockStatisticsResult:
        profileId: str
        parameterStats: Dict[str, MockParameterStats] = field(default_factory=dict)

    result = MockStatisticsResult(profileId=profileId)

    if includeStats:
        result.parameterStats = {
            'RPM': MockParameterStats('RPM', avgValue=2500.0, maxValue=6200.0, minValue=800.0),
            'SHORT_FUEL_TRIM_1': MockParameterStats('SHORT_FUEL_TRIM_1', avgValue=2.5),
            'LONG_FUEL_TRIM_1': MockParameterStats('LONG_FUEL_TRIM_1', avgValue=-1.8),
            'ENGINE_LOAD': MockParameterStats('ENGINE_LOAD', avgValue=45.0, maxValue=85.0),
            'THROTTLE_POS': MockParameterStats('THROTTLE_POS', avgValue=35.0, maxValue=95.0),
            'MAF': MockParameterStats('MAF', avgValue=12.5, maxValue=35.0),
            'COOLANT_TEMP': MockParameterStats('COOLANT_TEMP', avgValue=92.0),
        }

    return result


# =============================================================================
# Test Classes
# =============================================================================

class TestAiRecommendation(unittest.TestCase):
    """Tests for AiRecommendation dataclass."""

    def test_defaultValues(self):
        """
        Given: Default AiRecommendation
        When: Created with no arguments
        Then: Should have default values
        """
        rec = AiRecommendation()
        self.assertIsNone(rec.id)
        self.assertIsNotNone(rec.timestamp)
        self.assertEqual(rec.recommendation, "")
        self.assertEqual(rec.priorityRank, 3)
        self.assertIsNone(rec.isDuplicateOf)
        self.assertIsNone(rec.profileId)

    def test_toDict(self):
        """
        Given: AiRecommendation with values
        When: toDict called
        Then: Should return correct dictionary
        """
        timestamp = datetime(2026, 1, 22, 10, 30, 0)
        rec = AiRecommendation(
            id=1,
            timestamp=timestamp,
            recommendation="Test recommendation",
            priorityRank=2,
            isDuplicateOf=None,
            profileId='daily'
        )
        result = rec.toDict()
        self.assertEqual(result['id'], 1)
        self.assertEqual(result['timestamp'], '2026-01-22T10:30:00')
        self.assertEqual(result['recommendation'], "Test recommendation")
        self.assertEqual(result['priorityRank'], 2)
        self.assertIsNone(result['isDuplicateOf'])
        self.assertEqual(result['profileId'], 'daily')


class TestAnalysisResult(unittest.TestCase):
    """Tests for AnalysisResult dataclass."""

    def test_defaultValues(self):
        """
        Given: Default AnalysisResult
        When: Created with no arguments
        Then: Should have default values
        """
        result = AnalysisResult()
        self.assertFalse(result.success)
        self.assertIsNone(result.recommendation)
        self.assertEqual(result.promptUsed, "")
        self.assertEqual(result.responseRaw, "")
        self.assertEqual(result.analysisTime, 0.0)
        self.assertIsNone(result.errorMessage)

    def test_toDict_truncatesLongContent(self):
        """
        Given: AnalysisResult with very long prompt/response
        When: toDict called
        Then: Should truncate long content
        """
        result = AnalysisResult(
            success=True,
            promptUsed="x" * 600,
            responseRaw="y" * 600
        )
        d = result.toDict()
        self.assertTrue(d['promptUsed'].endswith('...'))
        self.assertTrue(d['responseRaw'].endswith('...'))
        self.assertLessEqual(len(d['promptUsed']), 510)


class TestAnalyzerStats(unittest.TestCase):
    """Tests for AnalyzerStats dataclass."""

    def test_defaultValues(self):
        """
        Given: Default AnalyzerStats
        When: Created with no arguments
        Then: Should have default values
        """
        stats = AnalyzerStats()
        self.assertEqual(stats.totalAnalyses, 0)
        self.assertEqual(stats.successfulAnalyses, 0)
        self.assertEqual(stats.failedAnalyses, 0)
        self.assertEqual(stats.averageAnalysisTime, 0.0)

    def test_toDict(self):
        """
        Given: AnalyzerStats with values
        When: toDict called
        Then: Should return correct dictionary
        """
        stats = AnalyzerStats(
            totalAnalyses=10,
            successfulAnalyses=8,
            failedAnalyses=2,
            averageAnalysisTime=1500.0
        )
        result = stats.toDict()
        self.assertEqual(result['totalAnalyses'], 10)
        self.assertEqual(result['successfulAnalyses'], 8)
        self.assertEqual(result['failedAnalyses'], 2)


class TestAiAnalyzerInit(unittest.TestCase):
    """Tests for AiAnalyzer initialization."""

    def test_init_defaultConfig(self):
        """
        Given: No config provided
        When: AiAnalyzer created
        Then: Should use defaults and be disabled
        """
        analyzer = AiAnalyzer()
        self.assertFalse(analyzer.isEnabled)
        self.assertEqual(analyzer.state, AnalyzerState.DISABLED)

    def test_init_enabledConfig(self):
        """
        Given: Config with enabled=True
        When: AiAnalyzer created
        Then: Should be enabled with IDLE state
        """
        config = createTestConfig(enabled=True)
        analyzer = AiAnalyzer(config=config)
        self.assertTrue(analyzer.isEnabled)
        self.assertEqual(analyzer.state, AnalyzerState.IDLE)

    def test_init_customModel(self):
        """
        Given: Config with custom model
        When: AiAnalyzer created
        Then: Should use specified model
        """
        config = createTestConfig(model='qwen2.5:3b')
        analyzer = AiAnalyzer(config=config)
        self.assertEqual(analyzer._model, 'qwen2.5:3b')

    def test_init_customMaxPerDrive(self):
        """
        Given: Config with custom maxAnalysesPerDrive
        When: AiAnalyzer created
        Then: Should use specified limit
        """
        config = createTestConfig(maxPerDrive=3)
        analyzer = AiAnalyzer(config=config)
        self.assertEqual(analyzer._maxAnalysesPerDrive, 3)


class TestAiAnalyzerIsReady(unittest.TestCase):
    """Tests for AiAnalyzer.isReady()."""

    def test_isReady_disabled(self):
        """
        Given: AI analysis disabled
        When: isReady called
        Then: Should return False
        """
        config = createTestConfig(enabled=False)
        analyzer = AiAnalyzer(config=config)
        self.assertFalse(analyzer.isReady())

    def test_isReady_noOllama(self):
        """
        Given: Enabled but no ollama manager
        When: isReady called
        Then: Should return False
        """
        config = createTestConfig(enabled=True)
        analyzer = AiAnalyzer(config=config)
        self.assertFalse(analyzer.isReady())

    def test_isReady_ollamaNotReady(self):
        """
        Given: Enabled but ollama not ready
        When: isReady called
        Then: Should return False
        """
        config = createTestConfig(enabled=True)
        mockOllama = createMockOllamaManager(ready=False)
        analyzer = AiAnalyzer(config=config, ollamaManager=mockOllama)
        self.assertFalse(analyzer.isReady())

    def test_isReady_allConditionsMet(self):
        """
        Given: Enabled and ollama ready
        When: isReady called
        Then: Should return True
        """
        config = createTestConfig(enabled=True)
        mockOllama = createMockOllamaManager(ready=True)
        analyzer = AiAnalyzer(config=config, ollamaManager=mockOllama)
        self.assertTrue(analyzer.isReady())


class TestAiAnalyzerDataPreparation(unittest.TestCase):
    """Tests for data window preparation."""

    def setUp(self):
        self.config = createTestConfig(enabled=True)
        self.analyzer = AiAnalyzer(config=self.config)

    def test_prepareDataWindow_withStats(self):
        """
        Given: Statistics result with parameter data
        When: _prepareDataWindow called
        Then: Should extract metrics correctly
        """
        statsResult = createMockStatisticsResult()
        metrics = self.analyzer._prepareDataWindow(statsResult)

        self.assertEqual(metrics.get('rpm_avg'), 2500.0)
        self.assertEqual(metrics.get('rpm_max'), 6200.0)
        self.assertEqual(metrics.get('short_fuel_trim_avg'), 2.5)
        self.assertEqual(metrics.get('engine_load_avg'), 45.0)

    def test_prepareDataWindow_emptyStats(self):
        """
        Given: Statistics result with no parameters
        When: _prepareDataWindow called
        Then: Should return empty metrics
        """
        statsResult = createMockStatisticsResult(includeStats=False)
        metrics = self.analyzer._prepareDataWindow(statsResult)
        self.assertEqual(len(metrics), 0)

    def test_prepareDataWindow_withRawData(self):
        """
        Given: Statistics result and raw RPM data
        When: _prepareDataWindow called
        Then: Should calculate high RPM percentage
        """
        statsResult = createMockStatisticsResult()
        rawData = {
            'RPM': [3000, 3500, 4500, 5000, 5500, 3000, 2500, 4200]
        }
        metrics = self.analyzer._prepareDataWindow(statsResult, rawData)

        # 4 out of 8 values are > 4000
        self.assertEqual(metrics.get('rpm_high_time_pct'), 50.0)

    def test_prepareDataWindow_withO2Data(self):
        """
        Given: Statistics result and raw O2 sensor data
        When: _prepareDataWindow called
        Then: Should calculate rich/lean counts
        """
        statsResult = createMockStatisticsResult()
        rawData = {
            'O2_B1S1': [0.2, 0.3, 0.6, 0.7, 0.45, 0.55, 0.35]
        }
        metrics = self.analyzer._prepareDataWindow(statsResult, rawData)

        # Rich (>0.5): 0.6, 0.7, 0.55 = 3
        # Lean (<0.4): 0.2, 0.3, 0.35 = 3
        self.assertEqual(metrics.get('o2_rich_count'), 3)
        self.assertEqual(metrics.get('o2_lean_count'), 3)

    def test_prepareDataWindow_dictFormat(self):
        """
        Given: Statistics result in dictionary format
        When: _prepareDataWindow called
        Then: Should extract metrics correctly
        """
        statsResult = {
            'profileId': 'daily',
            'parameterStats': {
                'RPM': {'avgValue': 2500.0, 'maxValue': 6200.0},
                'ENGINE_LOAD': {'avgValue': 45.0}
            }
        }
        metrics = self.analyzer._prepareDataWindow(statsResult)
        self.assertEqual(metrics.get('rpm_avg'), 2500.0)
        self.assertEqual(metrics.get('engine_load_avg'), 45.0)


class TestAiAnalyzerPromptBuilding(unittest.TestCase):
    """Tests for prompt building."""

    def setUp(self):
        self.config = createTestConfig(enabled=True)
        self.analyzer = AiAnalyzer(config=self.config)

    def test_buildBasicPrompt(self):
        """
        Given: Metrics dictionary
        When: _buildBasicPrompt called
        Then: Should return formatted prompt
        """
        metrics = {
            'rpm_avg': 2500,
            'rpm_max': 6200,
            'short_fuel_trim_avg': 2.5,
            'long_fuel_trim_avg': -1.8,
            'engine_load_avg': 45.0,
            'engine_load_max': 85.0,
            'throttle_pos_avg': 35.0,
            'maf_avg': 12.5
        }
        prompt = self.analyzer._buildBasicPrompt(metrics)

        self.assertIn('2500', prompt)
        self.assertIn('6200', prompt)
        self.assertIn('2.5', prompt)
        self.assertIn('automotive performance', prompt.lower())

    def test_buildBasicPrompt_missingMetrics(self):
        """
        Given: Partial metrics
        When: _buildBasicPrompt called
        Then: Should use N/A for missing values
        """
        metrics = {'rpm_avg': 2500}
        prompt = self.analyzer._buildBasicPrompt(metrics)

        self.assertIn('2500', prompt)
        self.assertIn('N/A', prompt)


class TestAiAnalyzerAnalyzePostDrive(unittest.TestCase):
    """Tests for analyzePostDrive method."""

    def setUp(self):
        self.config = createTestConfig(enabled=True)
        self.db = createTestDatabase()
        self.mockOllama = createMockOllamaManager(ready=True)
        self.analyzer = AiAnalyzer(
            config=self.config,
            database=self.db,
            ollamaManager=self.mockOllama
        )

    def test_analyzePostDrive_disabled(self):
        """
        Given: AI analysis disabled
        When: analyzePostDrive called
        Then: Should return result with error message
        """
        config = createTestConfig(enabled=False)
        analyzer = AiAnalyzer(config=config)
        statsResult = createMockStatisticsResult()

        result = analyzer.analyzePostDrive(statsResult)

        self.assertFalse(result.success)
        self.assertIn('disabled', result.errorMessage.lower())

    def test_analyzePostDrive_notReady(self):
        """
        Given: Ollama not ready
        When: analyzePostDrive called
        Then: Should raise AiAnalyzerNotAvailableError
        """
        config = createTestConfig(enabled=True)
        mockOllama = createMockOllamaManager(ready=False)
        analyzer = AiAnalyzer(config=config, ollamaManager=mockOllama)
        statsResult = createMockStatisticsResult()

        result = analyzer.analyzePostDrive(statsResult)

        self.assertFalse(result.success)
        self.assertIn('not ready', result.errorMessage.lower())

    @patch('src.obd.ai.analyzer.urllib.request.urlopen')
    def test_analyzePostDrive_success(self, mockUrlopen):
        """
        Given: Valid setup and ollama response
        When: analyzePostDrive called
        Then: Should return successful result with recommendation
        """
        # Mock ollama response
        mockResponse = MagicMock()
        mockResponse.read.return_value = json.dumps({
            'response': 'Test recommendation from AI model'
        }).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        statsResult = createMockStatisticsResult()
        result = self.analyzer.analyzePostDrive(statsResult)

        self.assertTrue(result.success)
        self.assertIsNotNone(result.recommendation)
        self.assertEqual(
            result.recommendation.recommendation,
            'Test recommendation from AI model'
        )
        self.assertEqual(result.profileId, 'daily')

    @patch('src.obd.ai.analyzer.urllib.request.urlopen')
    def test_analyzePostDrive_savesToDatabase(self, mockUrlopen):
        """
        Given: Valid setup
        When: analyzePostDrive succeeds
        Then: Should save recommendation to database
        """
        mockResponse = MagicMock()
        mockResponse.read.return_value = json.dumps({
            'response': 'Saved recommendation'
        }).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        statsResult = createMockStatisticsResult()
        result = self.analyzer.analyzePostDrive(statsResult)

        # Verify saved to database
        with self.db.connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM ai_recommendations')
            rows = cursor.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['recommendation'], 'Saved recommendation')
            self.assertEqual(rows[0]['profile_id'], 'daily')

    @patch('src.obd.ai.analyzer.urllib.request.urlopen')
    def test_analyzePostDrive_limitExceeded(self, mockUrlopen):
        """
        Given: Max analyses per drive exceeded
        When: analyzePostDrive called again
        Then: Should return limit exceeded error
        """
        mockResponse = MagicMock()
        mockResponse.read.return_value = json.dumps({
            'response': 'First recommendation'
        }).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        statsResult = createMockStatisticsResult()
        driveId = 'test_drive_001'

        # First analysis should succeed
        result1 = self.analyzer.analyzePostDrive(
            statsResult, driveId=driveId
        )
        self.assertTrue(result1.success)

        # Second analysis should be limited
        result2 = self.analyzer.analyzePostDrive(
            statsResult, driveId=driveId
        )
        self.assertFalse(result2.success)
        self.assertIn('exceeded', result2.errorMessage.lower())

    @patch('src.obd.ai.analyzer.urllib.request.urlopen')
    def test_analyzePostDrive_multipleAllowed(self, mockUrlopen):
        """
        Given: Config allows 2 analyses per drive
        When: analyzePostDrive called twice
        Then: Should succeed both times
        """
        config = createTestConfig(enabled=True, maxPerDrive=2)
        analyzer = AiAnalyzer(
            config=config,
            database=self.db,
            ollamaManager=self.mockOllama
        )

        mockResponse = MagicMock()
        mockResponse.read.return_value = json.dumps({
            'response': 'Recommendation'
        }).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        statsResult = createMockStatisticsResult()
        driveId = 'test_drive_002'

        result1 = analyzer.analyzePostDrive(statsResult, driveId=driveId)
        result2 = analyzer.analyzePostDrive(statsResult, driveId=driveId)

        self.assertTrue(result1.success)
        self.assertTrue(result2.success)


class TestAiAnalyzerOllamaIntegration(unittest.TestCase):
    """Tests for ollama API integration."""

    def setUp(self):
        self.config = createTestConfig(enabled=True)
        self.analyzer = AiAnalyzer(config=self.config)

    @patch('src.obd.ai.analyzer.urllib.request.urlopen')
    def test_callOllama_success(self, mockUrlopen):
        """
        Given: Valid ollama response
        When: _callOllama called
        Then: Should return response text
        """
        mockResponse = MagicMock()
        mockResponse.read.return_value = json.dumps({
            'response': 'AI generated text'
        }).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        result = self.analyzer._callOllama("Test prompt")

        self.assertEqual(result, 'AI generated text')

    @patch('src.obd.ai.analyzer.urllib.request.urlopen')
    def test_callOllama_emptyResponse(self, mockUrlopen):
        """
        Given: Empty response from ollama
        When: _callOllama called
        Then: Should raise AiAnalyzerGenerationError
        """
        mockResponse = MagicMock()
        mockResponse.read.return_value = json.dumps({
            'response': ''
        }).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        with self.assertRaises(AiAnalyzerGenerationError):
            self.analyzer._callOllama("Test prompt")

    @patch('src.obd.ai.analyzer.urllib.request.urlopen')
    def test_callOllama_connectionError(self, mockUrlopen):
        """
        Given: Connection error to ollama
        When: _callOllama called
        Then: Should raise AiAnalyzerGenerationError
        """
        import urllib.error
        mockUrlopen.side_effect = urllib.error.URLError("Connection refused")

        with self.assertRaises(AiAnalyzerGenerationError) as ctx:
            self.analyzer._callOllama("Test prompt")

        self.assertIn('connect', ctx.exception.message.lower())


class TestAiAnalyzerRetrievalMethods(unittest.TestCase):
    """Tests for recommendation retrieval methods."""

    def setUp(self):
        self.config = createTestConfig(enabled=True)
        self.db = createTestDatabase()
        self.analyzer = AiAnalyzer(
            config=self.config,
            database=self.db
        )
        # Insert test data
        with self.db.connect() as conn:
            conn.execute("""
                INSERT INTO ai_recommendations
                (recommendation, priority_rank, profile_id, is_duplicate_of)
                VALUES
                ('Rec 1', 1, 'daily', NULL),
                ('Rec 2', 2, 'daily', NULL),
                ('Rec 3 (dup)', 3, 'daily', 1),
                ('Rec 4', 4, 'performance', NULL)
            """)

    def test_getRecommendations_all(self):
        """
        Given: Recommendations in database
        When: getRecommendations called with no filter
        Then: Should return all non-duplicate recommendations
        """
        recs = self.analyzer.getRecommendations(excludeDuplicates=True)
        self.assertEqual(len(recs), 3)

    def test_getRecommendations_byProfile(self):
        """
        Given: Recommendations for different profiles
        When: getRecommendations called with profileId
        Then: Should return only matching profile's recommendations
        """
        recs = self.analyzer.getRecommendations(
            profileId='daily',
            excludeDuplicates=True
        )
        self.assertEqual(len(recs), 2)
        for rec in recs:
            self.assertEqual(rec.profileId, 'daily')

    def test_getRecommendations_includeDuplicates(self):
        """
        Given: Recommendations including duplicates
        When: getRecommendations called with excludeDuplicates=False
        Then: Should include duplicate recommendations
        """
        recs = self.analyzer.getRecommendations(
            profileId='daily',
            excludeDuplicates=False
        )
        self.assertEqual(len(recs), 3)

    def test_getRecommendations_limit(self):
        """
        Given: Multiple recommendations
        When: getRecommendations called with limit
        Then: Should return limited number
        """
        recs = self.analyzer.getRecommendations(limit=2)
        self.assertEqual(len(recs), 2)

    def test_getRecommendationById(self):
        """
        Given: Recommendation in database
        When: getRecommendationById called
        Then: Should return correct recommendation
        """
        rec = self.analyzer.getRecommendationById(1)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.recommendation, 'Rec 1')
        self.assertEqual(rec.priorityRank, 1)

    def test_getRecommendationById_notFound(self):
        """
        Given: Non-existent ID
        When: getRecommendationById called
        Then: Should return None
        """
        rec = self.analyzer.getRecommendationById(999)
        self.assertIsNone(rec)

    def test_getRecommendationCount(self):
        """
        Given: Recommendations in database
        When: getRecommendationCount called
        Then: Should return correct count
        """
        count = self.analyzer.getRecommendationCount()
        self.assertEqual(count, 3)  # Excludes duplicates by default

    def test_getRecommendationCount_byProfile(self):
        """
        Given: Recommendations for different profiles
        When: getRecommendationCount called with profileId
        Then: Should return profile-specific count
        """
        count = self.analyzer.getRecommendationCount(profileId='performance')
        self.assertEqual(count, 1)


class TestAiAnalyzerStatistics(unittest.TestCase):
    """Tests for statistics tracking."""

    def setUp(self):
        self.config = createTestConfig(enabled=True)
        self.db = createTestDatabase()
        self.mockOllama = createMockOllamaManager(ready=True)
        self.analyzer = AiAnalyzer(
            config=self.config,
            database=self.db,
            ollamaManager=self.mockOllama
        )

    @patch('src.obd.ai.analyzer.urllib.request.urlopen')
    def test_stats_updatedOnSuccess(self, mockUrlopen):
        """
        Given: Successful analysis
        When: analyzePostDrive completes
        Then: Should update statistics
        """
        mockResponse = MagicMock()
        mockResponse.read.return_value = json.dumps({
            'response': 'Test'
        }).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        statsResult = createMockStatisticsResult()
        self.analyzer.analyzePostDrive(statsResult, driveId='d1')

        stats = self.analyzer.stats
        self.assertEqual(stats.totalAnalyses, 1)
        self.assertEqual(stats.successfulAnalyses, 1)
        self.assertEqual(stats.failedAnalyses, 0)
        self.assertEqual(stats.totalRecommendations, 1)
        self.assertIsNotNone(stats.lastAnalysisTime)

    @patch('src.obd.ai.analyzer.urllib.request.urlopen')
    def test_stats_updatedOnFailure(self, mockUrlopen):
        """
        Given: Failed analysis (ollama error)
        When: analyzePostDrive fails
        Then: Should update failure count
        """
        # Make ollama throw an error during generation
        import urllib.error
        mockUrlopen.side_effect = urllib.error.URLError("Connection failed")

        statsResult = createMockStatisticsResult()
        result = self.analyzer.analyzePostDrive(statsResult)

        stats = self.analyzer.stats
        self.assertFalse(result.success)
        self.assertEqual(stats.failedAnalyses, 1)

    def test_resetStats(self):
        """
        Given: Analyzer with statistics
        When: resetStats called
        Then: Should reset all stats
        """
        self.analyzer._stats.totalAnalyses = 10
        self.analyzer._stats.successfulAnalyses = 8

        self.analyzer.resetStats()

        stats = self.analyzer.stats
        self.assertEqual(stats.totalAnalyses, 0)
        self.assertEqual(stats.successfulAnalyses, 0)

    def test_resetDriveAnalysisCounts(self):
        """
        Given: Analyzer with drive counts
        When: resetDriveAnalysisCounts called
        Then: Should clear all counts
        """
        self.analyzer._analysisCountByDrive['d1'] = 1
        self.analyzer._analysisCountByDrive['d2'] = 2

        self.analyzer.resetDriveAnalysisCounts()

        self.assertEqual(len(self.analyzer._analysisCountByDrive), 0)


class TestAiAnalyzerCallbacks(unittest.TestCase):
    """Tests for callback functionality."""

    def setUp(self):
        self.config = createTestConfig(enabled=True)
        self.db = createTestDatabase()
        self.mockOllama = createMockOllamaManager(ready=True)
        self.analyzer = AiAnalyzer(
            config=self.config,
            database=self.db,
            ollamaManager=self.mockOllama
        )

    @patch('src.obd.ai.analyzer.urllib.request.urlopen')
    def test_onAnalysisStart_called(self, mockUrlopen):
        """
        Given: Callback registered for analysis start
        When: Analysis starts
        Then: Should call callback
        """
        mockResponse = MagicMock()
        mockResponse.read.return_value = json.dumps({
            'response': 'Test'
        }).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        startCallback = MagicMock()
        self.analyzer.registerCallbacks(onAnalysisStart=startCallback)

        statsResult = createMockStatisticsResult()
        self.analyzer.analyzePostDrive(statsResult)

        startCallback.assert_called_once_with('daily')

    @patch('src.obd.ai.analyzer.urllib.request.urlopen')
    def test_onAnalysisComplete_called(self, mockUrlopen):
        """
        Given: Callback registered for analysis complete
        When: Analysis completes
        Then: Should call callback with result
        """
        mockResponse = MagicMock()
        mockResponse.read.return_value = json.dumps({
            'response': 'Test'
        }).encode('utf-8')
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        completeCallback = MagicMock()
        self.analyzer.registerCallbacks(onAnalysisComplete=completeCallback)

        statsResult = createMockStatisticsResult()
        self.analyzer.analyzePostDrive(statsResult)

        completeCallback.assert_called_once()
        callArg = completeCallback.call_args[0][0]
        self.assertIsInstance(callArg, AnalysisResult)
        self.assertTrue(callArg.success)


class TestHelperFunctions(unittest.TestCase):
    """Tests for helper functions."""

    def test_createAiAnalyzerFromConfig(self):
        """
        Given: Config dictionary
        When: createAiAnalyzerFromConfig called
        Then: Should return configured analyzer
        """
        config = createTestConfig(enabled=True, model='qwen2.5:3b')
        db = createTestDatabase()
        ollama = createMockOllamaManager()

        analyzer = createAiAnalyzerFromConfig(config, db, ollama)

        self.assertIsInstance(analyzer, AiAnalyzer)
        self.assertTrue(analyzer.isEnabled)
        self.assertEqual(analyzer._model, 'qwen2.5:3b')

    def test_isAiAnalysisEnabled_true(self):
        """
        Given: Config with enabled=True
        When: isAiAnalysisEnabled called
        Then: Should return True
        """
        config = createTestConfig(enabled=True)
        self.assertTrue(isAiAnalysisEnabled(config))

    def test_isAiAnalysisEnabled_false(self):
        """
        Given: Config with enabled=False
        When: isAiAnalysisEnabled called
        Then: Should return False
        """
        config = createTestConfig(enabled=False)
        self.assertFalse(isAiAnalysisEnabled(config))

    def test_isAiAnalysisEnabled_missing(self):
        """
        Given: Config without aiAnalysis section
        When: isAiAnalysisEnabled called
        Then: Should return False (default)
        """
        config = {}
        self.assertFalse(isAiAnalysisEnabled(config))

    def test_getAiAnalysisConfig(self):
        """
        Given: Config dictionary
        When: getAiAnalysisConfig called
        Then: Should return config with defaults
        """
        config = createTestConfig(enabled=True, model='gemma2:2b')
        result = getAiAnalysisConfig(config)

        self.assertTrue(result['enabled'])
        self.assertEqual(result['model'], 'gemma2:2b')
        self.assertEqual(result['ollamaBaseUrl'], 'http://localhost:11434')
        self.assertEqual(result['maxAnalysesPerDrive'], 1)

    def test_getAiAnalysisConfig_defaults(self):
        """
        Given: Empty config
        When: getAiAnalysisConfig called
        Then: Should return all defaults
        """
        config = {}
        result = getAiAnalysisConfig(config)

        self.assertFalse(result['enabled'])
        self.assertEqual(result['model'], 'gemma2:2b')
        self.assertEqual(result['maxAnalysesPerDrive'], DEFAULT_MAX_ANALYSES_PER_DRIVE)

    def test_connectAnalyzerToStatisticsEngine(self):
        """
        Given: Analyzer and statistics engine
        When: connectAnalyzerToStatisticsEngine called
        Then: Should register callback on engine
        """
        config = createTestConfig(enabled=True)
        analyzer = AiAnalyzer(config=config)
        mockEngine = MagicMock()

        connectAnalyzerToStatisticsEngine(analyzer, mockEngine)

        mockEngine.registerCallbacks.assert_called_once()


class TestAiAnalyzerGetStatus(unittest.TestCase):
    """Tests for getStatus method."""

    def test_getStatus_disabled(self):
        """
        Given: Disabled analyzer
        When: getStatus called
        Then: Should return disabled status
        """
        config = createTestConfig(enabled=False)
        analyzer = AiAnalyzer(config=config)

        status = analyzer.getStatus()

        self.assertFalse(status['enabled'])
        self.assertEqual(status['state'], 'disabled')
        self.assertFalse(status['ready'])

    def test_getStatus_enabled(self):
        """
        Given: Enabled analyzer with ollama
        When: getStatus called
        Then: Should return full status
        """
        config = createTestConfig(enabled=True)
        mockOllama = createMockOllamaManager(ready=True)
        analyzer = AiAnalyzer(config=config, ollamaManager=mockOllama)

        status = analyzer.getStatus()

        self.assertTrue(status['enabled'])
        self.assertEqual(status['state'], 'idle')
        self.assertTrue(status['ready'])
        self.assertEqual(status['model'], 'gemma2:2b')
        self.assertEqual(status['maxAnalysesPerDrive'], 1)


class TestAiAnalyzerExceptions(unittest.TestCase):
    """Tests for exception classes."""

    def test_AiAnalyzerError(self):
        """Test base AiAnalyzerError."""
        error = AiAnalyzerError("Test error", details={'key': 'value'})
        self.assertEqual(error.message, "Test error")
        self.assertEqual(error.details, {'key': 'value'})

    def test_AiAnalyzerNotAvailableError(self):
        """Test AiAnalyzerNotAvailableError."""
        error = AiAnalyzerNotAvailableError("Not available")
        self.assertIsInstance(error, AiAnalyzerError)

    def test_AiAnalyzerLimitExceededError(self):
        """Test AiAnalyzerLimitExceededError."""
        error = AiAnalyzerLimitExceededError("Limit exceeded")
        self.assertIsInstance(error, AiAnalyzerError)

    def test_AiAnalyzerGenerationError(self):
        """Test AiAnalyzerGenerationError."""
        error = AiAnalyzerGenerationError("Generation failed")
        self.assertIsInstance(error, AiAnalyzerError)


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)
