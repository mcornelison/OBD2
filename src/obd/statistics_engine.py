################################################################################
# File Name: statistics_engine.py
# Purpose/Description: Statistics calculation engine for OBD-II realtime data
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-014
# ================================================================================
################################################################################

"""
Statistics calculation engine for the Eclipse OBD-II Performance Monitoring System.

Provides:
- Statistical analysis of logged OBD-II parameters
- Threaded/scheduled analysis execution
- Calculation of max, min, avg, mode, std_1, std_2, outliers
- Storage of results in statistics table
- Profile-specific statistical analysis

Usage:
    from obd.statistics_engine import StatisticsEngine, ParameterStatistics

    # Create engine with database and config
    engine = StatisticsEngine(database, config)

    # Calculate statistics for all parameters
    results = engine.calculateStatistics(profileId='daily')

    # Schedule analysis to run after drive ends
    engine.scheduleAnalysis(delaySeconds=0)

    # Get statistics for a specific parameter
    stats = engine.getParameterStatistics('RPM', profileId='daily')
"""

import logging
import math
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ================================================================================
# Custom Exceptions
# ================================================================================

class StatisticsError(Exception):
    """Base exception for statistics-related errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class StatisticsCalculationError(StatisticsError):
    """Error during statistics calculation."""
    pass


class StatisticsStorageError(StatisticsError):
    """Error storing statistics in database."""
    pass


class InsufficientDataError(StatisticsError):
    """Not enough data points to calculate statistics."""
    pass


# ================================================================================
# Enums and Data Classes
# ================================================================================

class AnalysisState(Enum):
    """State of the analysis engine."""
    IDLE = 'idle'
    SCHEDULED = 'scheduled'
    RUNNING = 'running'
    COMPLETED = 'completed'
    ERROR = 'error'


@dataclass
class ParameterStatistics:
    """
    Statistical summary for a single OBD-II parameter.

    Attributes:
        parameterName: Name of the parameter (e.g., 'RPM')
        analysisDate: When the analysis was performed
        profileId: Profile ID the analysis is associated with
        maxValue: Maximum value observed
        minValue: Minimum value observed
        avgValue: Average (mean) value
        modeValue: Most common value
        std1: First standard deviation
        std2: Second standard deviation (std1 * 2)
        outlierMin: Lower outlier bound (avg - 2*std1)
        outlierMax: Upper outlier bound (avg + 2*std1)
        sampleCount: Number of data points used
    """
    parameterName: str
    analysisDate: datetime
    profileId: str
    maxValue: Optional[float] = None
    minValue: Optional[float] = None
    avgValue: Optional[float] = None
    modeValue: Optional[float] = None
    std1: Optional[float] = None
    std2: Optional[float] = None
    outlierMin: Optional[float] = None
    outlierMax: Optional[float] = None
    sampleCount: int = 0

    def toDict(self) -> Dict[str, Any]:
        """Convert statistics to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'analysisDate': self.analysisDate.isoformat() if self.analysisDate else None,
            'profileId': self.profileId,
            'maxValue': self.maxValue,
            'minValue': self.minValue,
            'avgValue': self.avgValue,
            'modeValue': self.modeValue,
            'std1': self.std1,
            'std2': self.std2,
            'outlierMin': self.outlierMin,
            'outlierMax': self.outlierMax,
            'sampleCount': self.sampleCount
        }


@dataclass
class AnalysisResult:
    """
    Result of a complete analysis run.

    Attributes:
        analysisDate: When the analysis was performed
        profileId: Profile ID the analysis is associated with
        parameterStats: Dictionary of parameter name to ParameterStatistics
        totalParameters: Number of parameters analyzed
        totalSamples: Total number of data points analyzed
        success: Whether the analysis completed successfully
        errorMessage: Error message if analysis failed
        durationMs: Duration of analysis in milliseconds
    """
    analysisDate: datetime
    profileId: str
    parameterStats: Dict[str, ParameterStatistics] = field(default_factory=dict)
    totalParameters: int = 0
    totalSamples: int = 0
    success: bool = True
    errorMessage: Optional[str] = None
    durationMs: float = 0.0

    def toDict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            'analysisDate': self.analysisDate.isoformat() if self.analysisDate else None,
            'profileId': self.profileId,
            'parameterStats': {
                name: stats.toDict()
                for name, stats in self.parameterStats.items()
            },
            'totalParameters': self.totalParameters,
            'totalSamples': self.totalSamples,
            'success': self.success,
            'errorMessage': self.errorMessage,
            'durationMs': self.durationMs
        }


@dataclass
class EngineStats:
    """
    Statistics about the engine itself.

    Attributes:
        totalAnalysesRun: Number of analyses performed
        lastAnalysisDate: When the last analysis was performed
        lastAnalysisDurationMs: Duration of last analysis in ms
        totalParametersAnalyzed: Total parameters analyzed across all runs
        totalSamplesProcessed: Total data points processed
    """
    totalAnalysesRun: int = 0
    lastAnalysisDate: Optional[datetime] = None
    lastAnalysisDurationMs: float = 0.0
    totalParametersAnalyzed: int = 0
    totalSamplesProcessed: int = 0

    def toDict(self) -> Dict[str, Any]:
        """Convert stats to dictionary for serialization."""
        return {
            'totalAnalysesRun': self.totalAnalysesRun,
            'lastAnalysisDate': (
                self.lastAnalysisDate.isoformat() if self.lastAnalysisDate else None
            ),
            'lastAnalysisDurationMs': self.lastAnalysisDurationMs,
            'totalParametersAnalyzed': self.totalParametersAnalyzed,
            'totalSamplesProcessed': self.totalSamplesProcessed
        }


# ================================================================================
# Statistics Calculator Functions
# ================================================================================

def calculateMean(values: List[float]) -> float:
    """
    Calculate arithmetic mean of values.

    Args:
        values: List of numeric values

    Returns:
        Mean value

    Raises:
        InsufficientDataError: If values list is empty
    """
    if not values:
        raise InsufficientDataError("Cannot calculate mean of empty list")
    return sum(values) / len(values)


def calculateMode(values: List[float], precision: int = 2) -> Optional[float]:
    """
    Calculate mode (most common value) of values.

    Args:
        values: List of numeric values
        precision: Decimal places to round for mode calculation

    Returns:
        Mode value, or None if no clear mode exists
    """
    if not values:
        return None

    # Round values for mode calculation to group similar values
    roundedValues = [round(v, precision) for v in values]
    counter = Counter(roundedValues)

    if not counter:
        return None

    # Get most common value
    mostCommon = counter.most_common(1)
    if mostCommon:
        return mostCommon[0][0]

    return None


def calculateStandardDeviation(values: List[float], mean: Optional[float] = None) -> float:
    """
    Calculate sample standard deviation of values.

    Args:
        values: List of numeric values
        mean: Pre-calculated mean (optional, will calculate if not provided)

    Returns:
        Standard deviation

    Raises:
        InsufficientDataError: If fewer than 2 values provided
    """
    if len(values) < 2:
        raise InsufficientDataError(
            "Cannot calculate standard deviation with fewer than 2 values"
        )

    if mean is None:
        mean = calculateMean(values)

    # Calculate sum of squared differences from mean
    squaredDiffs = [(v - mean) ** 2 for v in values]

    # Use sample standard deviation (n-1)
    variance = sum(squaredDiffs) / (len(values) - 1)
    return math.sqrt(variance)


def calculateOutlierBounds(
    mean: float,
    stdDev: float,
    multiplier: float = 2.0
) -> Tuple[float, float]:
    """
    Calculate outlier bounds based on mean and standard deviation.

    Args:
        mean: Mean value
        stdDev: Standard deviation
        multiplier: Standard deviation multiplier (default: 2.0)

    Returns:
        Tuple of (outlier_min, outlier_max)
    """
    outlierMin = mean - (multiplier * stdDev)
    outlierMax = mean + (multiplier * stdDev)
    return (outlierMin, outlierMax)


def calculateParameterStatistics(
    values: List[float],
    parameterName: str,
    profileId: str,
    analysisDate: Optional[datetime] = None,
    minSamples: int = 2
) -> ParameterStatistics:
    """
    Calculate all statistics for a parameter.

    Args:
        values: List of parameter values
        parameterName: Name of the parameter
        profileId: Profile ID for the analysis
        analysisDate: When the analysis was performed (default: now)
        minSamples: Minimum samples required for std calculation

    Returns:
        ParameterStatistics with all calculated values

    Raises:
        InsufficientDataError: If no values provided
    """
    if analysisDate is None:
        analysisDate = datetime.now()

    if not values:
        raise InsufficientDataError(
            f"No data for parameter '{parameterName}'",
            details={'parameter': parameterName, 'profileId': profileId}
        )

    # Basic statistics
    maxValue = max(values)
    minValue = min(values)
    avgValue = calculateMean(values)
    modeValue = calculateMode(values)
    sampleCount = len(values)

    # Standard deviation and outliers (requires at least minSamples points)
    std1 = None
    std2 = None
    outlierMin = None
    outlierMax = None

    if sampleCount >= minSamples:
        try:
            std1 = calculateStandardDeviation(values, avgValue)
            std2 = std1 * 2
            outlierMin, outlierMax = calculateOutlierBounds(avgValue, std1)
        except (InsufficientDataError, ZeroDivisionError):
            # Keep as None if calculation fails
            pass

    return ParameterStatistics(
        parameterName=parameterName,
        analysisDate=analysisDate,
        profileId=profileId,
        maxValue=maxValue,
        minValue=minValue,
        avgValue=avgValue,
        modeValue=modeValue,
        std1=std1,
        std2=std2,
        outlierMin=outlierMin,
        outlierMax=outlierMax,
        sampleCount=sampleCount
    )


# ================================================================================
# Statistics Engine Class
# ================================================================================

class StatisticsEngine:
    """
    Engine for calculating and storing OBD-II parameter statistics.

    Provides threaded/scheduled analysis execution with configurable triggers.
    Calculates max, min, avg, mode, std_1, std_2, and outlier bounds for
    each logged parameter, then stores results in the statistics table.

    Features:
    - Background thread execution for non-blocking analysis
    - Configurable analysis window (time range)
    - Profile-specific statistics
    - Callback support for analysis events
    - Minimum sample requirements

    Attributes:
        database: ObdDatabase instance for data access
        config: Configuration dictionary with 'analysis' section

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)

        engine = StatisticsEngine(db, config)

        # Calculate immediately
        result = engine.calculateStatistics(profileId='daily')

        # Or schedule for background execution
        engine.scheduleAnalysis(delaySeconds=5)

        # Get historical statistics
        stats = engine.getParameterStatistics('RPM', profileId='daily')
    """

    def __init__(
        self,
        database: Any,
        config: Dict[str, Any],
        minSamples: int = 2
    ):
        """
        Initialize the statistics engine.

        Args:
            database: ObdDatabase instance for data access
            config: Configuration dictionary with 'analysis' section
            minSamples: Minimum samples required for standard deviation
        """
        self.database = database
        self.config = config
        self.minSamples = minSamples

        # Extract analysis configuration
        analysisConfig = config.get('analysis', {})
        self._calculateStats = analysisConfig.get(
            'calculateStatistics',
            ['max', 'min', 'avg', 'mode', 'std_1', 'std_2', 'outlier_min', 'outlier_max']
        )

        # State management
        self._state = AnalysisState.IDLE
        self._lock = threading.Lock()
        self._scheduledTimer: Optional[threading.Timer] = None
        self._analysisThread: Optional[threading.Thread] = None

        # Statistics tracking
        self._engineStats = EngineStats()

        # Callbacks
        self._onAnalysisStart: Optional[Callable[[str], None]] = None
        self._onAnalysisComplete: Optional[Callable[[AnalysisResult], None]] = None
        self._onAnalysisError: Optional[Callable[[str, Exception], None]] = None

    @property
    def state(self) -> AnalysisState:
        """Get current analysis state."""
        return self._state

    @property
    def isRunning(self) -> bool:
        """Check if analysis is currently running."""
        return self._state == AnalysisState.RUNNING

    @property
    def isScheduled(self) -> bool:
        """Check if analysis is scheduled to run."""
        return self._state == AnalysisState.SCHEDULED

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

    def scheduleAnalysis(
        self,
        profileId: Optional[str] = None,
        delaySeconds: float = 0,
        analysisWindow: Optional[timedelta] = None
    ) -> bool:
        """
        Schedule analysis to run after a delay.

        Args:
            profileId: Profile to analyze (default: active profile from config)
            delaySeconds: Delay before running analysis
            analysisWindow: Time window of data to analyze (default: all available)

        Returns:
            True if scheduled successfully
        """
        with self._lock:
            if self._state == AnalysisState.RUNNING:
                logger.warning("Cannot schedule analysis while running")
                return False

            # Cancel any existing scheduled analysis
            if self._scheduledTimer is not None:
                self._scheduledTimer.cancel()
                self._scheduledTimer = None

            # Determine profile ID
            if profileId is None:
                profileId = self._getActiveProfileId()

            self._state = AnalysisState.SCHEDULED

            logger.info(
                f"Analysis scheduled | profile={profileId} | delay={delaySeconds}s"
            )

            if delaySeconds <= 0:
                # Run immediately in background thread
                self._startAnalysisThread(profileId, analysisWindow)
            else:
                # Schedule for later
                self._scheduledTimer = threading.Timer(
                    delaySeconds,
                    lambda: self._startAnalysisThread(profileId, analysisWindow)
                )
                self._scheduledTimer.daemon = True
                self._scheduledTimer.start()

            return True

    def cancelScheduledAnalysis(self) -> bool:
        """
        Cancel any scheduled analysis.

        Returns:
            True if cancelled, False if nothing was scheduled
        """
        with self._lock:
            if self._scheduledTimer is not None:
                self._scheduledTimer.cancel()
                self._scheduledTimer = None
                self._state = AnalysisState.IDLE
                logger.info("Scheduled analysis cancelled")
                return True
            return False

    def calculateStatistics(
        self,
        profileId: Optional[str] = None,
        analysisWindow: Optional[timedelta] = None,
        storeResults: bool = True
    ) -> AnalysisResult:
        """
        Calculate statistics for all logged parameters.

        This is a synchronous method that blocks until analysis is complete.
        For background execution, use scheduleAnalysis().

        Args:
            profileId: Profile to analyze (default: active profile from config)
            analysisWindow: Time window of data to analyze (default: all available)
            storeResults: Whether to store results in database

        Returns:
            AnalysisResult with all calculated statistics

        Raises:
            StatisticsCalculationError: If analysis fails
        """
        import time
        startTime = time.perf_counter()

        # Determine profile ID
        if profileId is None:
            profileId = self._getActiveProfileId()

        analysisDate = datetime.now()

        result = AnalysisResult(
            analysisDate=analysisDate,
            profileId=profileId
        )

        try:
            with self._lock:
                self._state = AnalysisState.RUNNING

            # Notify callback
            if self._onAnalysisStart:
                try:
                    self._onAnalysisStart(profileId)
                except Exception as e:
                    logger.warning(f"onAnalysisStart callback error: {e}")

            logger.info(f"Starting statistics analysis | profile={profileId}")

            # Get parameter data from database
            parameterData = self._fetchParameterData(profileId, analysisWindow)

            if not parameterData:
                logger.warning(f"No data found for profile '{profileId}'")
                result.success = True
                result.errorMessage = "No data available for analysis"
            else:
                # Calculate statistics for each parameter
                for paramName, values in parameterData.items():
                    try:
                        stats = calculateParameterStatistics(
                            values=values,
                            parameterName=paramName,
                            profileId=profileId,
                            analysisDate=analysisDate,
                            minSamples=self.minSamples
                        )
                        result.parameterStats[paramName] = stats
                        result.totalSamples += stats.sampleCount

                    except InsufficientDataError as e:
                        logger.debug(f"Skipping '{paramName}': {e}")
                    except Exception as e:
                        logger.warning(
                            f"Error calculating stats for '{paramName}': {e}"
                        )

                result.totalParameters = len(result.parameterStats)

                # Store results if requested
                if storeResults and result.parameterStats:
                    self._storeStatistics(result)

            # Calculate duration
            endTime = time.perf_counter()
            result.durationMs = (endTime - startTime) * 1000

            # Update engine stats
            self._engineStats.totalAnalysesRun += 1
            self._engineStats.lastAnalysisDate = analysisDate
            self._engineStats.lastAnalysisDurationMs = result.durationMs
            self._engineStats.totalParametersAnalyzed += result.totalParameters
            self._engineStats.totalSamplesProcessed += result.totalSamples

            logger.info(
                f"Analysis complete | profile={profileId} | "
                f"parameters={result.totalParameters} | "
                f"samples={result.totalSamples} | "
                f"duration={result.durationMs:.1f}ms"
            )

            # Notify callback
            if self._onAnalysisComplete:
                try:
                    self._onAnalysisComplete(result)
                except Exception as e:
                    logger.warning(f"onAnalysisComplete callback error: {e}")

            return result

        except Exception as e:
            result.success = False
            result.errorMessage = str(e)

            # Notify callback
            if self._onAnalysisError:
                try:
                    self._onAnalysisError(profileId, e)
                except Exception as callbackError:
                    logger.warning(f"onAnalysisError callback error: {callbackError}")

            logger.error(f"Analysis failed | profile={profileId} | error={e}")
            raise StatisticsCalculationError(
                f"Statistics calculation failed: {e}",
                details={'profileId': profileId, 'error': str(e)}
            )

        finally:
            with self._lock:
                self._state = AnalysisState.COMPLETED if result.success else AnalysisState.ERROR

    def getParameterStatistics(
        self,
        parameterName: str,
        profileId: Optional[str] = None,
        limit: int = 1
    ) -> List[ParameterStatistics]:
        """
        Retrieve stored statistics for a parameter.

        Args:
            parameterName: Name of the parameter
            profileId: Profile to filter by (None for all profiles)
            limit: Maximum number of results to return

        Returns:
            List of ParameterStatistics, ordered by analysis_date desc
        """
        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()

                if profileId:
                    cursor.execute(
                        """
                        SELECT parameter_name, analysis_date, profile_id,
                               max_value, min_value, avg_value, mode_value,
                               std_1, std_2, outlier_min, outlier_max,
                               sample_count
                        FROM statistics
                        WHERE parameter_name = ? AND profile_id = ?
                        ORDER BY analysis_date DESC
                        LIMIT ?
                        """,
                        (parameterName, profileId, limit)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT parameter_name, analysis_date, profile_id,
                               max_value, min_value, avg_value, mode_value,
                               std_1, std_2, outlier_min, outlier_max,
                               sample_count
                        FROM statistics
                        WHERE parameter_name = ?
                        ORDER BY analysis_date DESC
                        LIMIT ?
                        """,
                        (parameterName, limit)
                    )

                rows = cursor.fetchall()

                results = []
                for row in rows:
                    results.append(ParameterStatistics(
                        parameterName=row['parameter_name'],
                        analysisDate=row['analysis_date'],
                        profileId=row['profile_id'],
                        maxValue=row['max_value'],
                        minValue=row['min_value'],
                        avgValue=row['avg_value'],
                        modeValue=row['mode_value'],
                        std1=row['std_1'],
                        std2=row['std_2'],
                        outlierMin=row['outlier_min'],
                        outlierMax=row['outlier_max'],
                        sampleCount=row['sample_count'] or 0
                    ))

                return results

        except Exception as e:
            logger.error(f"Error retrieving statistics: {e}")
            return []

    def getLatestAnalysisResult(
        self,
        profileId: Optional[str] = None
    ) -> Optional[AnalysisResult]:
        """
        Get the most recent complete analysis result from database.

        Args:
            profileId: Profile to filter by (default: active profile)

        Returns:
            AnalysisResult if available, None otherwise
        """
        if profileId is None:
            profileId = self._getActiveProfileId()

        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()

                # Get latest analysis date for this profile
                cursor.execute(
                    """
                    SELECT MAX(analysis_date) as latest
                    FROM statistics
                    WHERE profile_id = ?
                    """,
                    (profileId,)
                )
                row = cursor.fetchone()

                if not row or row['latest'] is None:
                    return None

                latestDate = row['latest']

                # Get all stats from that analysis
                cursor.execute(
                    """
                    SELECT parameter_name, analysis_date, profile_id,
                           max_value, min_value, avg_value, mode_value,
                           std_1, std_2, outlier_min, outlier_max,
                           sample_count
                    FROM statistics
                    WHERE profile_id = ? AND analysis_date = ?
                    """,
                    (profileId, latestDate)
                )

                rows = cursor.fetchall()

                if not rows:
                    return None

                result = AnalysisResult(
                    analysisDate=latestDate,
                    profileId=profileId,
                    success=True
                )

                for row in rows:
                    stats = ParameterStatistics(
                        parameterName=row['parameter_name'],
                        analysisDate=row['analysis_date'],
                        profileId=row['profile_id'],
                        maxValue=row['max_value'],
                        minValue=row['min_value'],
                        avgValue=row['avg_value'],
                        modeValue=row['mode_value'],
                        std1=row['std_1'],
                        std2=row['std_2'],
                        outlierMin=row['outlier_min'],
                        outlierMax=row['outlier_max'],
                        sampleCount=row['sample_count'] or 0
                    )
                    result.parameterStats[stats.parameterName] = stats
                    result.totalSamples += stats.sampleCount

                result.totalParameters = len(result.parameterStats)
                return result

        except Exception as e:
            logger.error(f"Error retrieving latest analysis: {e}")
            return None

    def getEngineStats(self) -> EngineStats:
        """
        Get engine statistics.

        Returns:
            EngineStats with engine performance data
        """
        return self._engineStats

    def getAnalysisCount(self, profileId: Optional[str] = None) -> int:
        """
        Get the number of analyses stored for a profile.

        Args:
            profileId: Profile to count (None for all profiles)

        Returns:
            Number of distinct analyses
        """
        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()

                if profileId:
                    cursor.execute(
                        """
                        SELECT COUNT(DISTINCT analysis_date) as count
                        FROM statistics
                        WHERE profile_id = ?
                        """,
                        (profileId,)
                    )
                else:
                    cursor.execute(
                        "SELECT COUNT(DISTINCT analysis_date) as count FROM statistics"
                    )

                row = cursor.fetchone()
                return row['count'] if row else 0

        except Exception as e:
            logger.error(f"Error counting analyses: {e}")
            return 0

    def _getActiveProfileId(self) -> str:
        """Get active profile ID from config."""
        profiles = self.config.get('profiles', {})
        return profiles.get('activeProfile', 'daily')

    def _startAnalysisThread(
        self,
        profileId: str,
        analysisWindow: Optional[timedelta]
    ) -> None:
        """Start analysis in a background thread."""
        def runAnalysis():
            try:
                self.calculateStatistics(
                    profileId=profileId,
                    analysisWindow=analysisWindow,
                    storeResults=True
                )
            except Exception as e:
                logger.error(f"Background analysis failed: {e}")

        self._analysisThread = threading.Thread(
            target=runAnalysis,
            name='StatisticsAnalysis',
            daemon=True
        )
        self._analysisThread.start()

    def _fetchParameterData(
        self,
        profileId: str,
        analysisWindow: Optional[timedelta] = None
    ) -> Dict[str, List[float]]:
        """
        Fetch parameter data from database for analysis.

        Args:
            profileId: Profile to fetch data for
            analysisWindow: Time window to fetch (None for all data)

        Returns:
            Dictionary mapping parameter names to lists of values
        """
        parameterData: Dict[str, List[float]] = {}

        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()

                if analysisWindow:
                    startTime = datetime.now() - analysisWindow
                    cursor.execute(
                        """
                        SELECT parameter_name, value
                        FROM realtime_data
                        WHERE profile_id = ? AND timestamp >= ?
                        ORDER BY parameter_name, timestamp
                        """,
                        (profileId, startTime)
                    )
                else:
                    cursor.execute(
                        """
                        SELECT parameter_name, value
                        FROM realtime_data
                        WHERE profile_id = ?
                        ORDER BY parameter_name, timestamp
                        """,
                        (profileId,)
                    )

                for row in cursor.fetchall():
                    paramName = row['parameter_name']
                    value = row['value']

                    if paramName not in parameterData:
                        parameterData[paramName] = []
                    parameterData[paramName].append(value)

        except Exception as e:
            logger.error(f"Error fetching parameter data: {e}")
            raise StatisticsCalculationError(
                f"Failed to fetch parameter data: {e}",
                details={'profileId': profileId, 'error': str(e)}
            )

        return parameterData

    def _storeStatistics(self, result: AnalysisResult) -> None:
        """
        Store analysis results in the statistics table.

        Args:
            result: AnalysisResult to store
        """
        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()

                for paramName, stats in result.parameterStats.items():
                    cursor.execute(
                        """
                        INSERT INTO statistics
                        (parameter_name, analysis_date, profile_id,
                         max_value, min_value, avg_value, mode_value,
                         std_1, std_2, outlier_min, outlier_max,
                         sample_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            stats.parameterName,
                            stats.analysisDate,
                            stats.profileId,
                            stats.maxValue,
                            stats.minValue,
                            stats.avgValue,
                            stats.modeValue,
                            stats.std1,
                            stats.std2,
                            stats.outlierMin,
                            stats.outlierMax,
                            stats.sampleCount
                        )
                    )

                logger.debug(
                    f"Stored {len(result.parameterStats)} statistics records"
                )

        except Exception as e:
            logger.error(f"Error storing statistics: {e}")
            raise StatisticsStorageError(
                f"Failed to store statistics: {e}",
                details={'error': str(e)}
            )


# ================================================================================
# Helper Functions
# ================================================================================

def createStatisticsEngineFromConfig(
    database: Any,
    config: Dict[str, Any]
) -> StatisticsEngine:
    """
    Create a StatisticsEngine from configuration.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary

    Returns:
        Configured StatisticsEngine instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        engine = createStatisticsEngineFromConfig(db, config)
    """
    return StatisticsEngine(database, config)


def calculateStatisticsForDrive(
    database: Any,
    config: Dict[str, Any],
    profileId: Optional[str] = None,
    startTime: Optional[datetime] = None,
    endTime: Optional[datetime] = None
) -> AnalysisResult:
    """
    Calculate statistics for a specific drive session.

    Convenience function for calculating statistics for data within a time range.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary
        profileId: Profile to analyze
        startTime: Start of time range
        endTime: End of time range

    Returns:
        AnalysisResult with calculated statistics
    """
    engine = StatisticsEngine(database, config)

    # Calculate analysis window if times provided
    analysisWindow = None
    if startTime and endTime:
        analysisWindow = endTime - startTime
    elif endTime:
        analysisWindow = datetime.now() - startTime if startTime else None

    return engine.calculateStatistics(
        profileId=profileId,
        analysisWindow=analysisWindow,
        storeResults=True
    )


def getStatisticsSummary(
    database: Any,
    profileId: str,
    parameterNames: Optional[List[str]] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Get a summary of latest statistics for multiple parameters.

    Args:
        database: ObdDatabase instance
        profileId: Profile to get statistics for
        parameterNames: List of parameters (None for all)

    Returns:
        Dictionary mapping parameter names to their latest statistics
    """
    summary: Dict[str, Dict[str, Any]] = {}

    try:
        with database.connect() as conn:
            cursor = conn.cursor()

            if parameterNames:
                placeholders = ','.join('?' * len(parameterNames))
                cursor.execute(
                    f"""
                    SELECT s.*
                    FROM statistics s
                    INNER JOIN (
                        SELECT parameter_name, MAX(analysis_date) as max_date
                        FROM statistics
                        WHERE profile_id = ? AND parameter_name IN ({placeholders})
                        GROUP BY parameter_name
                    ) latest ON s.parameter_name = latest.parameter_name
                        AND s.analysis_date = latest.max_date
                    WHERE s.profile_id = ?
                    """,
                    [profileId] + parameterNames + [profileId]
                )
            else:
                cursor.execute(
                    """
                    SELECT s.*
                    FROM statistics s
                    INNER JOIN (
                        SELECT parameter_name, MAX(analysis_date) as max_date
                        FROM statistics
                        WHERE profile_id = ?
                        GROUP BY parameter_name
                    ) latest ON s.parameter_name = latest.parameter_name
                        AND s.analysis_date = latest.max_date
                    WHERE s.profile_id = ?
                    """,
                    (profileId, profileId)
                )

            for row in cursor.fetchall():
                summary[row['parameter_name']] = {
                    'max': row['max_value'],
                    'min': row['min_value'],
                    'avg': row['avg_value'],
                    'mode': row['mode_value'],
                    'std_1': row['std_1'],
                    'std_2': row['std_2'],
                    'outlier_min': row['outlier_min'],
                    'outlier_max': row['outlier_max'],
                    'sample_count': row['sample_count'],
                    'analysis_date': row['analysis_date']
                }

    except Exception as e:
        logger.error(f"Error getting statistics summary: {e}")

    return summary
