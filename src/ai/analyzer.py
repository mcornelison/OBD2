################################################################################
# File Name: analyzer.py
# Purpose/Description: AI-based post-drive analyzer for OBD-II performance data
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-016 - Extract
#               |              | AiAnalyzer class from ai_analyzer.py
# ================================================================================
################################################################################

"""
AI-based post-drive analyzer for OBD-II performance data.

Provides AI-powered performance optimization recommendations by analyzing drive data
through a local ollama model. Integrates with the statistics engine to trigger
analysis after each drive ends.

Key features:
- Triggers after post-drive statistical analysis completes
- Prepares data window with air/fuel ratio, RPM, throttle position, MAF, etc.
- Formats data as prompt for ollama model using AiPromptTemplate
- Saves recommendations to ai_recommendations table with timestamp and profile_id
- Limits analysis to max once per drive to prevent excessive processing

Usage:
    from ai.analyzer import AiAnalyzer

    # Create analyzer from config
    analyzer = AiAnalyzer(config, database, ollamaManager)

    # Analyze after statistics are ready
    result = analyzer.analyzePostDrive(analysisResult, profileId='daily')

    # Get recent recommendations
    recommendations = analyzer.getRecommendations(profileId='daily', limit=5)
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .types import (
    AnalyzerState,
    AiRecommendation,
    AnalysisResult,
    AnalyzerStats,
    DEFAULT_MAX_ANALYSES_PER_DRIVE,
    OLLAMA_GENERATE_TIMEOUT,
    OLLAMA_DEFAULT_BASE_URL,
)
from .exceptions import (
    AiAnalyzerError,
    AiAnalyzerNotAvailableError,
    AiAnalyzerLimitExceededError,
    AiAnalyzerGenerationError,
)
from .data_preparation import prepareDataWindow

logger = logging.getLogger(__name__)


class AiAnalyzer:
    """
    AI-based post-drive analyzer for OBD-II performance data.

    Analyzes drive data using a local ollama model to generate performance
    optimization recommendations. Integrates with StatisticsEngine for
    automatic triggering after drives end.

    Features:
    - Automatic triggering after post-drive statistical analysis
    - Data window preparation for AI prompt
    - ollama model integration for analysis
    - Recommendation storage in database
    - Analysis limiting (max once per drive)

    Attributes:
        config: Configuration dictionary with aiAnalysis settings
        database: ObdDatabase instance for data access and storage
        ollamaManager: OllamaManager instance for model interaction

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        ollama = createOllamaManagerFromConfig(config)

        analyzer = AiAnalyzer(config, db, ollama)

        # After drive ends and statistics are calculated
        result = analyzer.analyzePostDrive(statisticsResult)
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        database: Optional[Any] = None,
        ollamaManager: Optional[Any] = None,
        promptTemplate: Optional[Any] = None
    ):
        """
        Initialize the AI analyzer.

        Args:
            config: Configuration dictionary with aiAnalysis section
            database: ObdDatabase instance for data access
            ollamaManager: OllamaManager instance for model interaction
            promptTemplate: Optional AiPromptTemplate instance
        """
        self._config = config or {}
        self._database = database
        self._ollamaManager = ollamaManager
        self._promptTemplate = promptTemplate

        # Extract AI analysis config
        aiConfig = self._config.get('aiAnalysis', {})
        self._enabled = aiConfig.get('enabled', False)
        self._model = aiConfig.get('model', 'gemma2:2b')
        self._baseUrl = aiConfig.get('ollamaBaseUrl', OLLAMA_DEFAULT_BASE_URL)
        self._maxAnalysesPerDrive = aiConfig.get(
            'maxAnalysesPerDrive',
            DEFAULT_MAX_ANALYSES_PER_DRIVE
        )

        # State tracking
        self._state = AnalyzerState.IDLE if self._enabled else AnalyzerState.DISABLED
        self._analysisCountByDrive: Dict[str, int] = {}  # drive_id -> count
        self._lock = threading.Lock()

        # Statistics
        self._stats = AnalyzerStats()

        # Callbacks
        self._onAnalysisStart: Optional[Callable[[str], None]] = None
        self._onAnalysisComplete: Optional[Callable[[AnalysisResult], None]] = None
        self._onAnalysisError: Optional[Callable[[str, Exception], None]] = None

        if self._enabled:
            logger.info(
                f"AI Analyzer initialized | model={self._model} | "
                f"maxPerDrive={self._maxAnalysesPerDrive}"
            )
        else:
            logger.info("AI Analyzer disabled in configuration")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def isEnabled(self) -> bool:
        """Check if AI analysis is enabled in config."""
        return self._enabled

    @property
    def state(self) -> AnalyzerState:
        """Get current analyzer state."""
        return self._state

    @property
    def stats(self) -> AnalyzerStats:
        """Get analyzer statistics."""
        return self._stats

    def isReady(self) -> bool:
        """
        Check if analyzer is ready for analysis.

        Returns:
            True if enabled, ollama is available, and model is ready
        """
        if not self._enabled:
            return False
        if self._ollamaManager is None:
            return False
        return self._ollamaManager.isReady()

    # =========================================================================
    # Configuration
    # =========================================================================

    def setDatabase(self, database: Any) -> None:
        """Set the database for data access and storage."""
        self._database = database

    def setOllamaManager(self, manager: Any) -> None:
        """Set the ollama manager for model interaction."""
        self._ollamaManager = manager

    def setPromptTemplate(self, template: Any) -> None:
        """Set the prompt template for generating prompts."""
        self._promptTemplate = template

    def registerCallbacks(
        self,
        onAnalysisStart: Optional[Callable[[str], None]] = None,
        onAnalysisComplete: Optional[Callable[[AnalysisResult], None]] = None,
        onAnalysisError: Optional[Callable[[str, Exception], None]] = None
    ) -> None:
        """
        Register callbacks for analysis events.

        Args:
            onAnalysisStart: Called when analysis begins (profileId)
            onAnalysisComplete: Called when analysis completes (AnalysisResult)
            onAnalysisError: Called when analysis fails (profileId, exception)
        """
        self._onAnalysisStart = onAnalysisStart
        self._onAnalysisComplete = onAnalysisComplete
        self._onAnalysisError = onAnalysisError

    # =========================================================================
    # Analysis Methods
    # =========================================================================

    def analyzePostDrive(
        self,
        statisticsResult: Any,
        profileId: Optional[str] = None,
        driveId: Optional[str] = None,
        rawData: Optional[Dict[str, List[float]]] = None
    ) -> AnalysisResult:
        """
        Perform AI analysis on post-drive data.

        This is the main entry point for post-drive analysis. Call this
        after statistical analysis completes for a drive.

        Args:
            statisticsResult: AnalysisResult from StatisticsEngine
            profileId: Profile ID (uses statisticsResult.profileId if not provided)
            driveId: Optional drive identifier for tracking analysis count
            rawData: Optional raw parameter data for additional metrics

        Returns:
            AnalysisResult with recommendation or error

        Raises:
            AiAnalyzerNotAvailableError: If AI analysis is not available
            AiAnalyzerLimitExceededError: If max analyses per drive exceeded
        """
        startTime = time.perf_counter()

        # Use profile ID from statistics if not provided
        if profileId is None and statisticsResult:
            profileId = getattr(statisticsResult, 'profileId', None)
        if profileId is None:
            profileId = self._getActiveProfileId()

        # Generate drive ID if not provided
        if driveId is None:
            driveId = f"{profileId}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        result = AnalysisResult(
            profileId=profileId,
            driveId=driveId
        )

        try:
            # Check if enabled
            if not self._enabled:
                result.errorMessage = "AI analysis is disabled"
                logger.debug("AI analysis disabled, skipping")
                return result

            # Check analysis limit
            with self._lock:
                currentCount = self._analysisCountByDrive.get(driveId, 0)
                if currentCount >= self._maxAnalysesPerDrive:
                    raise AiAnalyzerLimitExceededError(
                        f"Max analyses per drive exceeded ({self._maxAnalysesPerDrive})",
                        details={'driveId': driveId, 'count': currentCount}
                    )

            # Check ollama availability
            if not self.isReady():
                raise AiAnalyzerNotAvailableError(
                    "AI analyzer not ready - ollama not available or model not loaded"
                )

            # Update state
            self._state = AnalyzerState.PREPARING

            # Trigger start callback
            if self._onAnalysisStart:
                try:
                    self._onAnalysisStart(profileId)
                except Exception as e:
                    logger.warning(f"onAnalysisStart callback error: {e}")

            logger.info(f"Starting AI analysis | profile={profileId} | drive={driveId}")

            # Prepare data window
            self._state = AnalyzerState.PREPARING
            metrics = prepareDataWindow(statisticsResult, rawData)

            # Build prompt
            prompt = self._buildPrompt(metrics)
            result.promptUsed = prompt

            # Call ollama for analysis
            self._state = AnalyzerState.ANALYZING
            response = self._callOllama(prompt)
            result.responseRaw = response

            # Parse and save recommendation
            self._state = AnalyzerState.SAVING
            recommendation = self._parseAndSaveRecommendation(
                response, profileId
            )
            result.recommendation = recommendation
            result.success = True

            # Update analysis count
            with self._lock:
                self._analysisCountByDrive[driveId] = currentCount + 1

            # Update stats
            endTime = time.perf_counter()
            result.analysisTime = (endTime - startTime) * 1000
            self._updateStats(result)

            logger.info(
                f"AI analysis complete | profile={profileId} | "
                f"time={result.analysisTime:.1f}ms"
            )

            # Trigger complete callback
            if self._onAnalysisComplete:
                try:
                    self._onAnalysisComplete(result)
                except Exception as e:
                    logger.warning(f"onAnalysisComplete callback error: {e}")

            return result

        except AiAnalyzerLimitExceededError as e:
            result.errorMessage = str(e)
            logger.info(f"Analysis limit exceeded for drive {driveId}")
            return result

        except AiAnalyzerNotAvailableError as e:
            result.errorMessage = str(e)
            logger.warning(f"AI analyzer not available: {e}")
            return result

        except Exception as e:
            result.success = False
            result.errorMessage = str(e)
            self._state = AnalyzerState.ERROR
            self._stats.failedAnalyses += 1

            logger.error(f"AI analysis failed: {e}")

            # Trigger error callback
            if self._onAnalysisError:
                try:
                    self._onAnalysisError(profileId, e)
                except Exception as callbackError:
                    logger.warning(f"onAnalysisError callback error: {callbackError}")

            return result

        finally:
            self._state = AnalyzerState.COMPLETED if result.success else AnalyzerState.ERROR

    def analyzePostDriveAsync(
        self,
        statisticsResult: Any,
        profileId: Optional[str] = None,
        driveId: Optional[str] = None,
        rawData: Optional[Dict[str, List[float]]] = None
    ) -> None:
        """
        Perform AI analysis asynchronously in a background thread.

        Same as analyzePostDrive but runs in background. Results are
        delivered through callbacks.

        Args:
            statisticsResult: AnalysisResult from StatisticsEngine
            profileId: Profile ID
            driveId: Optional drive identifier
            rawData: Optional raw parameter data
        """
        def runAnalysis():
            try:
                self.analyzePostDrive(
                    statisticsResult=statisticsResult,
                    profileId=profileId,
                    driveId=driveId,
                    rawData=rawData
                )
            except Exception as e:
                logger.error(f"Async AI analysis failed: {e}")

        thread = threading.Thread(
            target=runAnalysis,
            name='AiAnalysis',
            daemon=True
        )
        thread.start()

    # =========================================================================
    # Prompt Building
    # =========================================================================

    def _buildPrompt(self, metrics: Dict[str, Any]) -> str:
        """
        Build prompt for ollama from metrics.

        Args:
            metrics: Dictionary of metric values

        Returns:
            Formatted prompt string
        """
        # Use prompt template if available
        if self._promptTemplate is not None:
            result = self._promptTemplate.buildPrompt(metrics)
            return result.prompt

        # Import template module lazily to avoid circular imports
        try:
            from .prompt_template import AiPromptTemplate
            template = AiPromptTemplate(config=self._config)
            result = template.buildPrompt(metrics)
            return result.prompt
        except ImportError:
            logger.warning("AiPromptTemplate not available, using basic prompt")
            return self._buildBasicPrompt(metrics)

    def _buildBasicPrompt(self, metrics: Dict[str, Any]) -> str:
        """
        Build a basic prompt without the template module.

        Args:
            metrics: Dictionary of metric values

        Returns:
            Basic prompt string
        """
        prompt = """You are an automotive performance tuning expert. Based on this drive data:

RPM: avg={rpm_avg}, max={rpm_max}
Fuel Trim: short={short_fuel_trim_avg}%, long={long_fuel_trim_avg}%
Engine Load: avg={engine_load_avg}%, max={engine_load_max}%
Throttle: avg={throttle_pos_avg}%
MAF: avg={maf_avg} g/s

Please provide:
1. Air/fuel ratio assessment
2. Performance optimization recommendations
3. Potential issues to investigate
4. 3-5 actionable recommendations
"""
        # Define all expected placeholders
        allPlaceholders = [
            'rpm_avg', 'rpm_max', 'short_fuel_trim_avg', 'long_fuel_trim_avg',
            'engine_load_avg', 'engine_load_max', 'throttle_pos_avg', 'maf_avg'
        ]

        # Substitute metrics, using N/A for missing ones
        for placeholder in allPlaceholders:
            value = metrics.get(placeholder)
            fullPlaceholder = '{' + placeholder + '}'
            prompt = prompt.replace(
                fullPlaceholder,
                str(value) if value is not None else 'N/A'
            )

        return prompt

    def _prepareDataWindow(
        self,
        statisticsResult: Any,
        rawData: Optional[Dict[str, List[float]]] = None
    ) -> Dict[str, Any]:
        """
        Prepare data window from statistics result for AI analysis.

        This is a wrapper for backward compatibility. New code should use
        prepareDataWindow from ai.data_preparation directly.

        Args:
            statisticsResult: AnalysisResult from StatisticsEngine
            rawData: Optional raw parameter data for derived calculations

        Returns:
            Dictionary of metrics for prompt template
        """
        return prepareDataWindow(statisticsResult, rawData)

    # =========================================================================
    # Ollama Integration
    # =========================================================================

    def _callOllama(self, prompt: str) -> str:
        """
        Call ollama API to generate analysis.

        Args:
            prompt: The prompt to send to the model

        Returns:
            Generated response text

        Raises:
            AiAnalyzerGenerationError: If generation fails
        """
        try:
            url = f"{self._baseUrl}/api/generate"
            payload = json.dumps({
                'model': self._model,
                'prompt': prompt,
                'stream': False
            }).encode('utf-8')

            request = urllib.request.Request(
                url,
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )

            logger.debug(f"Calling ollama API | model={self._model}")

            with urllib.request.urlopen(
                request, timeout=OLLAMA_GENERATE_TIMEOUT
            ) as response:
                data = json.loads(response.read().decode('utf-8'))
                generatedText = data.get('response', '')

                if not generatedText:
                    raise AiAnalyzerGenerationError(
                        "Empty response from ollama",
                        details={'response': data}
                    )

                logger.debug(
                    f"Ollama response received | "
                    f"length={len(generatedText)} chars"
                )
                return generatedText

        except urllib.error.URLError as e:
            raise AiAnalyzerGenerationError(
                f"Failed to connect to ollama: {e.reason}",
                details={'url': url, 'error': str(e)}
            )
        except urllib.error.HTTPError as e:
            raise AiAnalyzerGenerationError(
                f"Ollama API error: HTTP {e.code}",
                details={'url': url, 'code': e.code}
            )
        except json.JSONDecodeError as e:
            raise AiAnalyzerGenerationError(
                f"Invalid JSON response from ollama: {e}",
                details={'error': str(e)}
            )
        except Exception as e:
            raise AiAnalyzerGenerationError(
                f"Ollama generation failed: {e}",
                details={'error': str(e)}
            )

    # =========================================================================
    # Recommendation Storage
    # =========================================================================

    def _parseAndSaveRecommendation(
        self,
        response: str,
        profileId: Optional[str]
    ) -> AiRecommendation:
        """
        Parse response and save as recommendation.

        Args:
            response: Raw response from ollama
            profileId: Profile ID to associate with recommendation

        Returns:
            Saved AiRecommendation
        """
        # Create recommendation object
        recommendation = AiRecommendation(
            timestamp=datetime.now(),
            recommendation=response.strip(),
            priorityRank=3,  # Default priority, will be ranked by ranker
            profileId=profileId
        )

        # Save to database if available
        if self._database:
            try:
                recommendationId = self._saveRecommendationToDb(recommendation)
                recommendation.id = recommendationId
                logger.debug(f"Recommendation saved | id={recommendationId}")
            except Exception as e:
                logger.error(f"Failed to save recommendation: {e}")

        return recommendation

    def _saveRecommendationToDb(self, recommendation: AiRecommendation) -> int:
        """
        Save recommendation to database.

        Args:
            recommendation: AiRecommendation to save

        Returns:
            Database ID of saved recommendation
        """
        with self._database.connect() as conn:
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
                    recommendation.profileId
                )
            )
            return cursor.lastrowid

    # =========================================================================
    # Retrieval Methods
    # =========================================================================

    def getRecommendations(
        self,
        profileId: Optional[str] = None,
        limit: int = 10,
        excludeDuplicates: bool = True
    ) -> List[AiRecommendation]:
        """
        Get recent AI recommendations from database.

        Args:
            profileId: Profile to filter by (None for all)
            limit: Maximum number of recommendations to return
            excludeDuplicates: Whether to exclude duplicate recommendations

        Returns:
            List of AiRecommendation objects
        """
        if not self._database:
            return []

        try:
            with self._database.connect() as conn:
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
                        profileId=row['profile_id']
                    ))

                return recommendations

        except Exception as e:
            logger.error(f"Error retrieving recommendations: {e}")
            return []

    def getRecommendationById(self, recommendationId: int) -> Optional[AiRecommendation]:
        """
        Get a specific recommendation by ID.

        Args:
            recommendationId: Database ID of the recommendation

        Returns:
            AiRecommendation or None if not found
        """
        if not self._database:
            return None

        try:
            with self._database.connect() as conn:
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
                        profileId=row['profile_id']
                    )
                return None

        except Exception as e:
            logger.error(f"Error retrieving recommendation {recommendationId}: {e}")
            return None

    def getRecommendationCount(
        self,
        profileId: Optional[str] = None,
        excludeDuplicates: bool = True
    ) -> int:
        """
        Get count of recommendations.

        Args:
            profileId: Profile to filter by (None for all)
            excludeDuplicates: Whether to exclude duplicates

        Returns:
            Count of recommendations
        """
        if not self._database:
            return 0

        try:
            with self._database.connect() as conn:
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

    # =========================================================================
    # Statistics and Utilities
    # =========================================================================

    def _updateStats(self, result: AnalysisResult) -> None:
        """Update analyzer statistics after analysis."""
        self._stats.totalAnalyses += 1
        self._stats.lastAnalysisTime = datetime.now()

        if result.success:
            self._stats.successfulAnalyses += 1
            self._stats.totalRecommendations += 1

            # Update average analysis time
            totalTime = (
                self._stats.averageAnalysisTime *
                (self._stats.successfulAnalyses - 1) +
                result.analysisTime
            )
            self._stats.averageAnalysisTime = (
                totalTime / self._stats.successfulAnalyses
            )
        else:
            self._stats.failedAnalyses += 1

    def _getActiveProfileId(self) -> str:
        """Get active profile ID from config."""
        profiles = self._config.get('profiles', {})
        return profiles.get('activeProfile', 'daily')

    def resetDriveAnalysisCounts(self) -> None:
        """Reset the per-drive analysis counts."""
        with self._lock:
            self._analysisCountByDrive.clear()
            logger.debug("Drive analysis counts reset")

    def resetStats(self) -> None:
        """Reset analyzer statistics."""
        self._stats = AnalyzerStats()
        logger.debug("Analyzer statistics reset")

    def getStatus(self) -> Dict[str, Any]:
        """
        Get comprehensive status information.

        Returns:
            Dictionary with analyzer status
        """
        return {
            'enabled': self._enabled,
            'state': self._state.value,
            'ready': self.isReady(),
            'model': self._model,
            'maxAnalysesPerDrive': self._maxAnalysesPerDrive,
            'ollamaAvailable': (
                self._ollamaManager.isReady()
                if self._ollamaManager else False
            ),
            'stats': self._stats.toDict()
        }
