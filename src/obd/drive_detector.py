################################################################################
# File Name: drive_detector.py
# Purpose/Description: Drive start/end detection for triggering post-drive analysis
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-015
# ================================================================================
################################################################################

"""
Drive start/end detection for the Eclipse OBD-II Performance Monitoring System.

Provides:
- Detection of when the car is running vs idle
- Configurable thresholds for drive start/end detection
- Integration with StatisticsEngine for post-drive analysis triggers
- Drive session tracking and logging

Usage:
    from obd.drive_detector import DriveDetector, DriveState

    # Create detector with config and statistics engine
    detector = DriveDetector(config, statisticsEngine, database)

    # Register callbacks for drive events
    detector.registerCallbacks(
        onDriveStart=lambda ds: print(f"Drive started: {ds}"),
        onDriveEnd=lambda ds: print(f"Drive ended: {ds}")
    )

    # In data acquisition loop, feed values to detector
    detector.processValue('RPM', 2500)
    detector.processValue('SPEED', 45)
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Default thresholds (from config analysis section)
DEFAULT_DRIVE_START_RPM_THRESHOLD = 500
DEFAULT_DRIVE_START_DURATION_SECONDS = 10
DEFAULT_DRIVE_END_RPM_THRESHOLD = 0
DEFAULT_DRIVE_END_DURATION_SECONDS = 60

# Parameters monitored for drive detection
DRIVE_DETECTION_PARAMETERS = ['RPM', 'SPEED']

# Minimum time between drive end and new drive start (debounce)
MIN_INTER_DRIVE_SECONDS = 5


# ================================================================================
# Enums
# ================================================================================

class DriveState(Enum):
    """State of the drive session."""
    UNKNOWN = "unknown"       # Initial state, no data yet
    STOPPED = "stopped"       # Engine off, vehicle stationary
    STARTING = "starting"     # RPM above threshold, waiting for duration
    RUNNING = "running"       # Drive confirmed in progress
    STOPPING = "stopping"     # RPM at/below threshold, waiting for duration
    ENDED = "ended"           # Drive ended (transitions to STOPPED)


class DetectorState(Enum):
    """State of the detector itself."""
    IDLE = "idle"
    MONITORING = "monitoring"
    ERROR = "error"


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class DriveSession:
    """
    Information about a drive session.

    Attributes:
        startTime: When the drive started
        endTime: When the drive ended (None if ongoing)
        profileId: Active profile during the drive
        peakRpm: Maximum RPM recorded during drive
        peakSpeed: Maximum speed recorded during drive
        duration: Duration of the drive in seconds
        analysisTriggered: Whether post-drive analysis was triggered
    """
    startTime: datetime
    endTime: Optional[datetime] = None
    profileId: Optional[str] = None
    peakRpm: float = 0.0
    peakSpeed: float = 0.0
    duration: float = 0.0
    analysisTriggered: bool = False

    def isActive(self) -> bool:
        """Check if this drive session is still active."""
        return self.endTime is None

    def getDuration(self) -> float:
        """Get duration in seconds."""
        if self.endTime:
            return (self.endTime - self.startTime).total_seconds()
        return (datetime.now() - self.startTime).total_seconds()

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'startTime': self.startTime.isoformat() if self.startTime else None,
            'endTime': self.endTime.isoformat() if self.endTime else None,
            'profileId': self.profileId,
            'peakRpm': self.peakRpm,
            'peakSpeed': self.peakSpeed,
            'duration': self.getDuration(),
            'analysisTriggered': self.analysisTriggered,
        }


@dataclass
class DetectorConfig:
    """
    Configuration for drive detection.

    Attributes:
        driveStartRpmThreshold: RPM threshold to consider engine running
        driveStartDurationSeconds: Duration RPM must exceed threshold
        driveEndRpmThreshold: RPM threshold to consider engine off
        driveEndDurationSeconds: Duration RPM must be at/below threshold
        triggerAnalysisAfterDrive: Whether to trigger analysis after drive
        profileId: Active profile ID
    """
    driveStartRpmThreshold: float = DEFAULT_DRIVE_START_RPM_THRESHOLD
    driveStartDurationSeconds: float = DEFAULT_DRIVE_START_DURATION_SECONDS
    driveEndRpmThreshold: float = DEFAULT_DRIVE_END_RPM_THRESHOLD
    driveEndDurationSeconds: float = DEFAULT_DRIVE_END_DURATION_SECONDS
    triggerAnalysisAfterDrive: bool = True
    profileId: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'driveStartRpmThreshold': self.driveStartRpmThreshold,
            'driveStartDurationSeconds': self.driveStartDurationSeconds,
            'driveEndRpmThreshold': self.driveEndRpmThreshold,
            'driveEndDurationSeconds': self.driveEndDurationSeconds,
            'triggerAnalysisAfterDrive': self.triggerAnalysisAfterDrive,
            'profileId': self.profileId,
        }


@dataclass
class DetectorStats:
    """
    Statistics about detector operation.

    Attributes:
        valuesProcessed: Total number of values processed
        drivesDetected: Total number of drives detected
        analysesTriggered: Number of analyses triggered
        lastDriveStart: Time of most recent drive start
        lastDriveEnd: Time of most recent drive end
        currentDriveDuration: Duration of current drive (if active)
    """
    valuesProcessed: int = 0
    drivesDetected: int = 0
    analysesTriggered: int = 0
    lastDriveStart: Optional[datetime] = None
    lastDriveEnd: Optional[datetime] = None
    currentDriveDuration: float = 0.0

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'valuesProcessed': self.valuesProcessed,
            'drivesDetected': self.drivesDetected,
            'analysesTriggered': self.analysesTriggered,
            'lastDriveStart': self.lastDriveStart.isoformat() if self.lastDriveStart else None,
            'lastDriveEnd': self.lastDriveEnd.isoformat() if self.lastDriveEnd else None,
            'currentDriveDuration': self.currentDriveDuration,
        }


# ================================================================================
# Exceptions
# ================================================================================

class DriveDetectorError(Exception):
    """Base exception for drive detector errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class DriveDetectorConfigError(DriveDetectorError):
    """Error in drive detector configuration."""
    pass


class DriveDetectorStateError(DriveDetectorError):
    """Invalid state transition error."""
    pass


# ================================================================================
# Drive Detector Class
# ================================================================================

class DriveDetector:
    """
    Detects drive start/end for triggering post-drive analysis.

    Monitors RPM and vehicle speed to detect when the engine is running.
    Considers drive started when RPM > threshold for consecutive duration.
    Considers drive ended when RPM = 0 for consecutive duration.

    Features:
    - Configurable thresholds from config.json
    - Integration with StatisticsEngine for automatic analysis
    - Drive session tracking with peak values
    - Database logging of drive events
    - Callback support for custom event handling

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        engine = createStatisticsEngineFromConfig(db, config)

        detector = DriveDetector(config, engine, db)
        detector.start()

        # In data acquisition loop
        for reading in readings:
            detector.processValue(reading.parameterName, reading.value)

        # When done
        detector.stop()
    """

    def __init__(
        self,
        config: Dict[str, Any],
        statisticsEngine: Optional[Any] = None,
        database: Optional[Any] = None
    ):
        """
        Initialize the drive detector.

        Args:
            config: Configuration dictionary with 'analysis' section
            statisticsEngine: StatisticsEngine for triggering post-drive analysis
            database: ObdDatabase for logging drive events
        """
        self._statisticsEngine = statisticsEngine
        self._database = database

        # Load configuration
        self._config = self._loadConfig(config)

        # State tracking
        self._driveState = DriveState.UNKNOWN
        self._detectorState = DetectorState.IDLE
        self._currentSession: Optional[DriveSession] = None
        self._sessionHistory: List[DriveSession] = []

        # Threshold timing
        self._aboveThresholdSince: Optional[datetime] = None
        self._belowThresholdSince: Optional[datetime] = None
        self._lastRpmValue: float = 0.0
        self._lastSpeedValue: float = 0.0
        self._lastValueTime: Optional[datetime] = None

        # Statistics
        self._stats = DetectorStats()

        # Callbacks
        self._onDriveStart: Optional[Callable[[DriveSession], None]] = None
        self._onDriveEnd: Optional[Callable[[DriveSession], None]] = None
        self._onStateChange: Optional[Callable[[DriveState, DriveState], None]] = None

        # Thread safety
        self._lock = threading.Lock()

    def _loadConfig(self, config: Dict[str, Any]) -> DetectorConfig:
        """
        Load configuration from config dictionary.

        Args:
            config: Configuration dictionary

        Returns:
            DetectorConfig instance
        """
        analysisConfig = config.get('analysis', {})
        profilesConfig = config.get('profiles', {})

        return DetectorConfig(
            driveStartRpmThreshold=analysisConfig.get(
                'driveStartRpmThreshold',
                DEFAULT_DRIVE_START_RPM_THRESHOLD
            ),
            driveStartDurationSeconds=analysisConfig.get(
                'driveStartDurationSeconds',
                DEFAULT_DRIVE_START_DURATION_SECONDS
            ),
            driveEndRpmThreshold=analysisConfig.get(
                'driveEndRpmThreshold',
                DEFAULT_DRIVE_END_RPM_THRESHOLD
            ),
            driveEndDurationSeconds=analysisConfig.get(
                'driveEndDurationSeconds',
                DEFAULT_DRIVE_END_DURATION_SECONDS
            ),
            triggerAnalysisAfterDrive=analysisConfig.get(
                'triggerAfterDrive',
                True
            ),
            profileId=profilesConfig.get('activeProfile'),
        )

    # ================================================================================
    # Configuration
    # ================================================================================

    def setStatisticsEngine(self, engine: Any) -> None:
        """
        Set the statistics engine for post-drive analysis.

        Args:
            engine: StatisticsEngine instance
        """
        self._statisticsEngine = engine

    def setDatabase(self, database: Any) -> None:
        """
        Set the database for event logging.

        Args:
            database: ObdDatabase instance
        """
        self._database = database

    def setThresholds(
        self,
        driveStartRpmThreshold: Optional[float] = None,
        driveStartDurationSeconds: Optional[float] = None,
        driveEndRpmThreshold: Optional[float] = None,
        driveEndDurationSeconds: Optional[float] = None
    ) -> None:
        """
        Update detection thresholds.

        Args:
            driveStartRpmThreshold: RPM threshold for drive start
            driveStartDurationSeconds: Duration for drive start
            driveEndRpmThreshold: RPM threshold for drive end
            driveEndDurationSeconds: Duration for drive end
        """
        with self._lock:
            if driveStartRpmThreshold is not None:
                self._config.driveStartRpmThreshold = driveStartRpmThreshold
            if driveStartDurationSeconds is not None:
                self._config.driveStartDurationSeconds = driveStartDurationSeconds
            if driveEndRpmThreshold is not None:
                self._config.driveEndRpmThreshold = driveEndRpmThreshold
            if driveEndDurationSeconds is not None:
                self._config.driveEndDurationSeconds = driveEndDurationSeconds

        logger.info(f"Thresholds updated: {self._config.toDict()}")

    def setTriggerAnalysis(self, enabled: bool) -> None:
        """
        Enable or disable automatic analysis triggering.

        Args:
            enabled: True to enable, False to disable
        """
        self._config.triggerAnalysisAfterDrive = enabled

    def setProfileId(self, profileId: str) -> None:
        """
        Set the active profile ID.

        Args:
            profileId: Profile ID
        """
        self._config.profileId = profileId

    def getConfig(self) -> DetectorConfig:
        """
        Get current configuration.

        Returns:
            DetectorConfig instance
        """
        return self._config

    # ================================================================================
    # Callbacks
    # ================================================================================

    def registerCallbacks(
        self,
        onDriveStart: Optional[Callable[[DriveSession], None]] = None,
        onDriveEnd: Optional[Callable[[DriveSession], None]] = None,
        onStateChange: Optional[Callable[[DriveState, DriveState], None]] = None
    ) -> None:
        """
        Register callbacks for drive events.

        Args:
            onDriveStart: Called when drive starts (DriveSession)
            onDriveEnd: Called when drive ends (DriveSession)
            onStateChange: Called on state change (oldState, newState)
        """
        self._onDriveStart = onDriveStart
        self._onDriveEnd = onDriveEnd
        self._onStateChange = onStateChange

    # ================================================================================
    # Lifecycle
    # ================================================================================

    def start(self) -> bool:
        """
        Start the drive detector.

        Returns:
            True if started successfully
        """
        with self._lock:
            if self._detectorState == DetectorState.MONITORING:
                return True

            self._detectorState = DetectorState.MONITORING
            self._driveState = DriveState.STOPPED

            # Reset timing trackers
            self._aboveThresholdSince = None
            self._belowThresholdSince = None

            logger.info(
                f"Drive detector started | "
                f"startThreshold={self._config.driveStartRpmThreshold}RPM | "
                f"startDuration={self._config.driveStartDurationSeconds}s | "
                f"endDuration={self._config.driveEndDurationSeconds}s"
            )

            return True

    def stop(self) -> None:
        """Stop the drive detector."""
        with self._lock:
            # If drive is active, end it
            if self._driveState == DriveState.RUNNING and self._currentSession:
                self._endDrive()

            self._detectorState = DetectorState.IDLE
            logger.info("Drive detector stopped")

    def isMonitoring(self) -> bool:
        """Check if detector is monitoring."""
        return self._detectorState == DetectorState.MONITORING

    def getDetectorState(self) -> DetectorState:
        """Get detector state."""
        return self._detectorState

    # ================================================================================
    # Drive State
    # ================================================================================

    def getDriveState(self) -> DriveState:
        """Get current drive state."""
        return self._driveState

    def isDriving(self) -> bool:
        """Check if a drive is currently in progress."""
        return self._driveState == DriveState.RUNNING

    def getCurrentSession(self) -> Optional[DriveSession]:
        """
        Get current drive session if active.

        Returns:
            DriveSession if drive in progress, None otherwise
        """
        return self._currentSession

    def getSessionHistory(self, limit: int = 10) -> List[DriveSession]:
        """
        Get recent drive session history.

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of DriveSession objects (most recent first)
        """
        return list(reversed(self._sessionHistory[-limit:]))

    # ================================================================================
    # Value Processing
    # ================================================================================

    def processValue(self, parameterName: str, value: float) -> DriveState:
        """
        Process a parameter value and update drive state.

        Args:
            parameterName: Parameter name ('RPM' or 'SPEED')
            value: Current value

        Returns:
            Current drive state after processing
        """
        if self._detectorState != DetectorState.MONITORING:
            return self._driveState

        with self._lock:
            self._stats.valuesProcessed += 1
            now = datetime.now()
            self._lastValueTime = now

            # Update tracked values
            if parameterName == 'RPM':
                self._lastRpmValue = value
                self._processRpmValue(value, now)
            elif parameterName == 'SPEED':
                self._lastSpeedValue = value
                # Update peak speed if driving
                if self._currentSession and value > self._currentSession.peakSpeed:
                    self._currentSession.peakSpeed = value

            # Update current drive duration stat
            if self._currentSession and self._currentSession.isActive():
                self._stats.currentDriveDuration = self._currentSession.getDuration()
            else:
                self._stats.currentDriveDuration = 0.0

            return self._driveState

    def processValues(self, values: Dict[str, float]) -> DriveState:
        """
        Process multiple parameter values at once.

        Args:
            values: Dictionary of parameter names to values

        Returns:
            Current drive state after processing
        """
        for parameterName, value in values.items():
            if parameterName in DRIVE_DETECTION_PARAMETERS:
                self.processValue(parameterName, value)
        return self._driveState

    def _processRpmValue(self, rpm: float, now: datetime) -> None:
        """
        Process an RPM value and check for state transitions.

        Args:
            rpm: Current RPM value
            now: Current timestamp
        """
        # Check if RPM is above start threshold
        rpmAboveStart = rpm > self._config.driveStartRpmThreshold

        # Check if RPM is at or below end threshold
        rpmAtOrBelowEnd = rpm <= self._config.driveEndRpmThreshold

        # Update peak RPM if driving
        if self._currentSession and rpm > self._currentSession.peakRpm:
            self._currentSession.peakRpm = rpm

        # State machine transitions
        if self._driveState == DriveState.UNKNOWN:
            # Initial state - transition to STOPPED
            self._transitionState(DriveState.STOPPED)

        elif self._driveState == DriveState.STOPPED:
            if rpmAboveStart:
                # Start tracking above-threshold time
                if self._aboveThresholdSince is None:
                    self._aboveThresholdSince = now
                    self._transitionState(DriveState.STARTING)
                    logger.debug(f"RPM above threshold, starting timer | RPM={rpm}")
            else:
                self._aboveThresholdSince = None

        elif self._driveState == DriveState.STARTING:
            if rpmAboveStart:
                # Check if duration met
                if self._aboveThresholdSince:
                    elapsed = (now - self._aboveThresholdSince).total_seconds()
                    if elapsed >= self._config.driveStartDurationSeconds:
                        # Drive confirmed!
                        self._startDrive(now)
            else:
                # RPM dropped below threshold, reset
                self._aboveThresholdSince = None
                self._transitionState(DriveState.STOPPED)
                logger.debug("RPM dropped below threshold before duration met")

        elif self._driveState == DriveState.RUNNING:
            if rpmAtOrBelowEnd:
                # Start tracking below-threshold time
                if self._belowThresholdSince is None:
                    self._belowThresholdSince = now
                    self._transitionState(DriveState.STOPPING)
                    logger.debug(f"RPM at/below end threshold | RPM={rpm}")
            else:
                self._belowThresholdSince = None

        elif self._driveState == DriveState.STOPPING:
            if rpmAtOrBelowEnd:
                # Check if duration met
                if self._belowThresholdSince:
                    elapsed = (now - self._belowThresholdSince).total_seconds()
                    if elapsed >= self._config.driveEndDurationSeconds:
                        # Drive ended!
                        self._endDrive()
            else:
                # RPM went back up, drive continues
                self._belowThresholdSince = None
                self._transitionState(DriveState.RUNNING)
                logger.debug("RPM went above threshold, drive continues")

    def _transitionState(self, newState: DriveState) -> None:
        """
        Transition to a new drive state.

        Args:
            newState: The new state to transition to
        """
        oldState = self._driveState
        if oldState == newState:
            return

        self._driveState = newState
        logger.debug(f"Drive state: {oldState.value} -> {newState.value}")

        # Trigger callback
        if self._onStateChange:
            try:
                self._onStateChange(oldState, newState)
            except Exception as e:
                logger.error(f"onStateChange callback error: {e}")

    def _startDrive(self, startTime: datetime) -> None:
        """
        Start a new drive session.

        Args:
            startTime: When the drive started
        """
        self._currentSession = DriveSession(
            startTime=startTime,
            profileId=self._config.profileId,
            peakRpm=self._lastRpmValue,
            peakSpeed=self._lastSpeedValue,
        )

        self._stats.drivesDetected += 1
        self._stats.lastDriveStart = startTime

        self._transitionState(DriveState.RUNNING)
        self._aboveThresholdSince = None

        logger.info(
            f"DRIVE STARTED | profile={self._config.profileId} | "
            f"RPM={self._lastRpmValue}"
        )

        # Log to database
        self._logDriveEvent('drive_start', startTime)

        # Trigger callback
        if self._onDriveStart and self._currentSession:
            try:
                self._onDriveStart(self._currentSession)
            except Exception as e:
                logger.error(f"onDriveStart callback error: {e}")

    def _endDrive(self) -> None:
        """End the current drive session."""
        if not self._currentSession:
            return

        endTime = datetime.now()
        self._currentSession.endTime = endTime
        self._currentSession.duration = self._currentSession.getDuration()

        self._stats.lastDriveEnd = endTime

        logger.info(
            f"DRIVE ENDED | duration={self._currentSession.duration:.1f}s | "
            f"peakRPM={self._currentSession.peakRpm} | "
            f"peakSpeed={self._currentSession.peakSpeed}"
        )

        # Log to database
        self._logDriveEvent('drive_end', endTime)

        # Trigger post-drive analysis
        if self._config.triggerAnalysisAfterDrive:
            self._triggerAnalysis()
            self._currentSession.analysisTriggered = True
            self._stats.analysesTriggered += 1

        # Add to history
        self._sessionHistory.append(self._currentSession)

        # Trigger callback before clearing session
        if self._onDriveEnd:
            try:
                self._onDriveEnd(self._currentSession)
            except Exception as e:
                logger.error(f"onDriveEnd callback error: {e}")

        # Clear current session
        self._currentSession = None
        self._belowThresholdSince = None

        self._transitionState(DriveState.STOPPED)

    def _triggerAnalysis(self) -> None:
        """Trigger post-drive statistical analysis."""
        if not self._statisticsEngine:
            logger.debug("No statistics engine configured, skipping analysis")
            return

        try:
            logger.info("Triggering post-drive statistical analysis")

            # Schedule analysis to run immediately (0 delay)
            # This runs in a background thread to not block the detector
            self._statisticsEngine.scheduleAnalysis(
                profileId=self._config.profileId,
                delaySeconds=0
            )

        except Exception as e:
            logger.error(f"Failed to trigger post-drive analysis: {e}")

    def _logDriveEvent(self, eventType: str, timestamp: datetime) -> None:
        """
        Log drive event to database.

        Args:
            eventType: Type of event ('drive_start' or 'drive_end')
            timestamp: Event timestamp
        """
        if not self._database:
            return

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO connection_log
                    (timestamp, event_type, mac_address, success, error_message)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp,
                        eventType,
                        f"profile:{self._config.profileId}",
                        True,
                        None
                    )
                )
                logger.debug(f"Drive event logged: {eventType}")
        except Exception as e:
            logger.error(f"Failed to log drive event: {e}")

    # ================================================================================
    # Statistics
    # ================================================================================

    def getStats(self) -> DetectorStats:
        """
        Get detector statistics.

        Returns:
            DetectorStats with current statistics
        """
        with self._lock:
            return DetectorStats(
                valuesProcessed=self._stats.valuesProcessed,
                drivesDetected=self._stats.drivesDetected,
                analysesTriggered=self._stats.analysesTriggered,
                lastDriveStart=self._stats.lastDriveStart,
                lastDriveEnd=self._stats.lastDriveEnd,
                currentDriveDuration=self._stats.currentDriveDuration,
            )

    def resetStats(self) -> None:
        """Reset statistics."""
        with self._lock:
            self._stats = DetectorStats()

    # ================================================================================
    # Debugging / Testing Helpers
    # ================================================================================

    def getTimingInfo(self) -> Dict[str, Any]:
        """
        Get current timing information for debugging.

        Returns:
            Dictionary with timing details
        """
        now = datetime.now()

        aboveElapsed = None
        if self._aboveThresholdSince:
            aboveElapsed = (now - self._aboveThresholdSince).total_seconds()

        belowElapsed = None
        if self._belowThresholdSince:
            belowElapsed = (now - self._belowThresholdSince).total_seconds()

        return {
            'driveState': self._driveState.value,
            'lastRpm': self._lastRpmValue,
            'lastSpeed': self._lastSpeedValue,
            'aboveThresholdSince': (
                self._aboveThresholdSince.isoformat()
                if self._aboveThresholdSince else None
            ),
            'aboveThresholdElapsed': aboveElapsed,
            'belowThresholdSince': (
                self._belowThresholdSince.isoformat()
                if self._belowThresholdSince else None
            ),
            'belowThresholdElapsed': belowElapsed,
            'sessionActive': self._currentSession is not None,
        }

    def reset(self) -> None:
        """Reset detector to initial state."""
        with self._lock:
            self._driveState = DriveState.STOPPED
            self._currentSession = None
            self._aboveThresholdSince = None
            self._belowThresholdSince = None
            self._lastRpmValue = 0.0
            self._lastSpeedValue = 0.0
            self._lastValueTime = None
            logger.debug("Drive detector reset")


# ================================================================================
# Helper Functions
# ================================================================================

def createDriveDetectorFromConfig(
    config: Dict[str, Any],
    statisticsEngine: Optional[Any] = None,
    database: Optional[Any] = None
) -> DriveDetector:
    """
    Create a DriveDetector from configuration.

    Args:
        config: Configuration dictionary
        statisticsEngine: StatisticsEngine instance (optional)
        database: ObdDatabase instance (optional)

    Returns:
        Configured DriveDetector instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        engine = createStatisticsEngineFromConfig(db, config)
        detector = createDriveDetectorFromConfig(config, engine, db)
    """
    return DriveDetector(config, statisticsEngine, database)


def isDriveDetectionEnabled(config: Dict[str, Any]) -> bool:
    """
    Check if drive detection is enabled in config.

    Args:
        config: Configuration dictionary

    Returns:
        True if drive detection/analysis trigger is enabled
    """
    return config.get('analysis', {}).get('triggerAfterDrive', True)


def getDriveDetectionConfig(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract drive detection configuration from config.

    Args:
        config: Configuration dictionary

    Returns:
        Dictionary with drive detection settings
    """
    analysisConfig = config.get('analysis', {})
    return {
        'driveStartRpmThreshold': analysisConfig.get(
            'driveStartRpmThreshold',
            DEFAULT_DRIVE_START_RPM_THRESHOLD
        ),
        'driveStartDurationSeconds': analysisConfig.get(
            'driveStartDurationSeconds',
            DEFAULT_DRIVE_START_DURATION_SECONDS
        ),
        'driveEndRpmThreshold': analysisConfig.get(
            'driveEndRpmThreshold',
            DEFAULT_DRIVE_END_RPM_THRESHOLD
        ),
        'driveEndDurationSeconds': analysisConfig.get(
            'driveEndDurationSeconds',
            DEFAULT_DRIVE_END_DURATION_SECONDS
        ),
        'triggerAfterDrive': analysisConfig.get('triggerAfterDrive', True),
    }


def getDefaultDriveDetectionConfig() -> Dict[str, float]:
    """
    Get default drive detection configuration values.

    Returns:
        Dictionary with default thresholds
    """
    return {
        'driveStartRpmThreshold': DEFAULT_DRIVE_START_RPM_THRESHOLD,
        'driveStartDurationSeconds': DEFAULT_DRIVE_START_DURATION_SECONDS,
        'driveEndRpmThreshold': DEFAULT_DRIVE_END_RPM_THRESHOLD,
        'driveEndDurationSeconds': DEFAULT_DRIVE_END_DURATION_SECONDS,
    }
