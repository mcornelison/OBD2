################################################################################
# File Name: detector.py
# Purpose/Description: DriveDetector class for drive start/end detection
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation (US-009)
# 2026-04-19    | Rex (US-202) | Route connection_log INSERT timestamp through
#                               src.common.time.helper.utcIsoNow (TD-027 fix)
# 2026-04-23    | Rex (US-225) | TD-034 close: forceKeyOff(reason) external
#                               termination API + no_new_drives gate on
#                               _openDriveId for the US-216 WARNING stage.
# 2026-04-23    | Rex (US-228) | drive_summary cold-start backfill: arm a
#                               bounded window at drive_start; each
#                               processValue tick fills still-NULL
#                               ambient/battery/baro columns via
#                               SummaryRecorder.backfillFromSnapshot.
# 2026-04-23    | Rex (US-229) | ECU-silence drive_end signal: track
#                               _lastEcuReadingTime on every ECU-sourced
#                               processValue call; fire drive_end when the
#                               ELM_VOLTAGE heartbeat keeps ticking but no
#                               Mode 01 PID has arrived in
#                               driveEndDurationSeconds.  Fixes Drive 3's
#                               never-closed drive bug.
# ================================================================================
################################################################################
"""
DriveDetector class for the Eclipse OBD-II Performance Monitoring System.

Provides:
- Detection of when the car is running vs idle
- Configurable thresholds for drive start/end detection
- Integration with StatisticsEngine for post-drive analysis triggers
- Drive session tracking and logging

Usage:
    from obd.drive import DriveDetector, DriveState

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
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from src.common.time.helper import utcIsoNow

from ..decoders import isEcuDependentParameter
from ..drive_id import getCurrentDriveId, nextDriveId, setCurrentDriveId
from ..engine_state import EngineState
from ..pi_state import getNoNewDrives
from .types import (
    DEFAULT_DRIVE_END_DURATION_SECONDS,
    DEFAULT_DRIVE_END_RPM_THRESHOLD,
    DEFAULT_DRIVE_START_DURATION_SECONDS,
    DEFAULT_DRIVE_START_RPM_THRESHOLD,
    DEFAULT_DRIVE_SUMMARY_BACKFILL_SECONDS,
    DRIVE_DETECTION_PARAMETERS,
    DetectorConfig,
    DetectorState,
    DetectorStats,
    DriveSession,
    DriveState,
)

logger = logging.getLogger(__name__)


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
        config: dict[str, Any],
        statisticsEngine: Any | None = None,
        database: Any | None = None,
        summaryRecorder: Any | None = None,
        readingSnapshotSource: Any | None = None,
    ):
        """
        Initialize the drive detector.

        Args:
            config: Configuration dictionary with 'analysis' section
            statisticsEngine: StatisticsEngine for triggering post-drive analysis
            database: ObdDatabase for logging drive events
            summaryRecorder: SummaryRecorder for US-206 drive-start
                metadata capture.  When provided, ``_startDrive``
                publishes ambient/battery/baro from the latest reading
                snapshot into the ``drive_summary`` table.  Pass
                ``None`` to skip (legacy tests that construct a
                detector with only config still work).
            readingSnapshotSource: Object exposing
                ``getLatestReadings() -> dict[str, float]``.
                Typically an :class:`ObdDataLogger` instance -- the
                detector pulls the cached snapshot here so the
                summary recorder never triggers new ECU polls
                (US-206 Invariant #1).
        """
        self._statisticsEngine = statisticsEngine
        self._database = database
        self._summaryRecorder = summaryRecorder
        self._readingSnapshotSource = readingSnapshotSource

        # Load configuration
        self._config = self._loadConfig(config)

        # State tracking
        self._driveState = DriveState.UNKNOWN
        self._detectorState = DetectorState.IDLE
        self._currentSession: DriveSession | None = None
        self._sessionHistory: list[DriveSession] = []

        # US-206: engine-state transition tracker used by the
        # drive-summary cold-start ambient rule.  Defaults to UNKNOWN
        # on boot (first drive since process start = cold).  Switched
        # to KEY_OFF by ``_endDrive`` after a clean debounce; stays
        # RUNNING only across a warm-restart gap where the engine
        # dropped but not long enough to hit the KEY_OFF window.  The
        # state is an attribute so tests can inject warm-restart
        # scenarios without hand-rolling an EngineStateMachine.
        self._lastEngineState: EngineState = EngineState.UNKNOWN

        # US-228: drive_summary backfill state.  _captureDriveStartSummary
        # runs an INSERT immediately at drive_start but may write NULL
        # ambient / battery / baro if the first Mode 01 tier-2 poll has
        # not returned yet.  During the backfill window, each
        # processValue tick calls _maybeBackfillDriveSummary to UPDATE
        # any still-NULL columns as readings arrive.  Complete=True +
        # deadline-expired both short-circuit the backfill early.
        self._driveSummaryBackfillDriveId: int | None = None
        self._driveSummaryBackfillDeadline: datetime | None = None
        self._driveSummaryBackfillComplete: bool = True
        self._driveSummaryBackfillFromState: EngineState | None = None

        # US-229: ECU-silence drive_end signal.  Timestamp of the most
        # recent ECU-sourced processValue call (isEcuDependentParameter
        # returns True).  Adapter-level heartbeats (BATTERY_V via
        # ELM_VOLTAGE) do NOT reset this -- they're the reason the
        # detector needs an orthogonal silence signal.  Initialized to
        # None; seeded in _startDrive to avoid firing immediately on the
        # first post-start tick.
        self._lastEcuReadingTime: datetime | None = None

        # Threshold timing
        self._aboveThresholdSince: datetime | None = None
        self._belowThresholdSince: datetime | None = None
        self._lastRpmValue: float = 0.0
        self._lastSpeedValue: float = 0.0
        self._lastValueTime: datetime | None = None

        # Statistics
        self._stats = DetectorStats()

        # Callbacks
        self._onDriveStart: Callable[[DriveSession], None] | None = None
        self._onDriveEnd: Callable[[DriveSession], None] | None = None
        self._onStateChange: Callable[[DriveState, DriveState], None] | None = None

        # Thread safety
        self._lock = threading.Lock()

    def _loadConfig(self, config: dict[str, Any]) -> DetectorConfig:
        """
        Load configuration from config dictionary.

        Args:
            config: Configuration dictionary

        Returns:
            DetectorConfig instance
        """
        analysisConfig = config.get('pi', {}).get('analysis', {})
        profilesConfig = config.get('pi', {}).get('profiles', {})

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
            driveSummaryBackfillSeconds=analysisConfig.get(
                'driveSummaryBackfillSeconds',
                DEFAULT_DRIVE_SUMMARY_BACKFILL_SECONDS,
            ),
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

    def setSummaryRecorder(self, recorder: Any) -> None:
        """Attach a SummaryRecorder for US-206 drive-start metadata capture."""
        self._summaryRecorder = recorder

    def setReadingSnapshotSource(self, source: Any) -> None:
        """Attach an object exposing ``getLatestReadings() -> dict``."""
        self._readingSnapshotSource = source

    def setThresholds(
        self,
        driveStartRpmThreshold: float | None = None,
        driveStartDurationSeconds: float | None = None,
        driveEndRpmThreshold: float | None = None,
        driveEndDurationSeconds: float | None = None
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
        onDriveStart: Callable[[DriveSession], None] | None = None,
        onDriveEnd: Callable[[DriveSession], None] | None = None,
        onStateChange: Callable[[DriveState, DriveState], None] | None = None
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

    def getCurrentSession(self) -> DriveSession | None:
        """
        Get current drive session if active.

        Returns:
            DriveSession if drive in progress, None otherwise
        """
        return self._currentSession

    def getSessionHistory(self, limit: int = 10) -> list[DriveSession]:
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

            # US-229: record ECU-sourced reading arrival so the silence
            # check below knows ECU polling is alive.  Adapter-level
            # parameters (BATTERY_V via ELM_VOLTAGE) keep ticking past
            # engine-off -- they MUST NOT reset this timer, otherwise
            # drive_end never fires.
            if isEcuDependentParameter(parameterName):
                self._lastEcuReadingTime = now

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

            # US-229: fire drive_end via ECU-silence path when the ECU
            # stops responding but an adapter heartbeat keeps this loop
            # alive.  Runs AFTER _processRpmValue so the RPM-below path
            # gets first swing at firing a clean debounced drive_end;
            # _endDrive is idempotent so a second attempt is a no-op.
            self._checkEcuSilenceDriveEnd(now)

            # US-228: while the drive is RUNNING and inside the
            # backfill window, each tick attempts to fill any
            # still-NULL drive_summary columns from the latest
            # reading snapshot.  Early-exits when complete or past
            # deadline.
            self._maybeBackfillDriveSummary(now)

            return self._driveState

    def processValues(self, values: dict[str, float]) -> DriveState:
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
        # US-200: mint a new drive_id via the Pi-local counter + publish
        # it on the process-wide context so writers tag every subsequent
        # row with this drive's id.  The mint happens BEFORE _logDriveEvent
        # so that the drive_start connection_log row already carries the id.
        self._openDriveId()

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
            f"RPM={self._lastRpmValue} | drive_id={getCurrentDriveId()}"
        )

        # Log to database
        self._logDriveEvent('drive_start', startTime)

        # US-206: drive-start metadata capture.  Runs AFTER the
        # drive_id is minted + published on the process context but
        # BEFORE the onDriveStart callback so that consumers observing
        # that callback can already find the drive_summary row if they
        # go looking.  Failure is logged but does NOT abort the drive
        # -- analytics filtering on is_real will ignore rows with no
        # drive_summary rather than crash, so the drive still records.
        self._captureDriveStartSummary()

        # US-228: arm the backfill window.  Subsequent processValue
        # ticks inside the window UPDATE any drive_summary columns
        # that the drive-start INSERT left NULL as readings arrive.
        self._armDriveSummaryBackfill(startTime)

        # US-229: seed the ECU-silence timer so the silence check
        # doesn't fire on the first tick after drive_start before the
        # first post-start Mode 01 poll arrives.
        self._lastEcuReadingTime = startTime

        # Trigger callback
        if self._onDriveStart and self._currentSession:
            try:
                self._onDriveStart(self._currentSession)
            except Exception as e:
                logger.error(f"onDriveStart callback error: {e}")

        # Mark the state as RUNNING AFTER the summary capture so the
        # cold-start rule sees the pre-drive state (UNKNOWN / KEY_OFF)
        # rather than RUNNING.  _endDrive flips back to KEY_OFF.
        self._lastEngineState = EngineState.RUNNING

    def _endDrive(self, reason: str | None = None) -> None:
        """End the current drive session.

        Args:
            reason: Optional external-termination reason.  When set,
                threaded through :meth:`_logDriveEvent` so the connection_log
                drive_end row carries the reason in ``error_message`` for
                operator traceability (US-225 / TD-034 -- US-216
                IMMINENT-stage force-KEY-off).  ``None`` preserves the
                legacy RPM-debounce-driven drive end.
        """
        if not self._currentSession:
            return

        endTime = datetime.now()
        self._currentSession.endTime = endTime
        self._currentSession.duration = self._currentSession.getDuration()

        self._stats.lastDriveEnd = endTime

        if reason is None:
            logger.info(
                f"DRIVE ENDED | duration={self._currentSession.duration:.1f}s | "
                f"peakRPM={self._currentSession.peakRpm} | "
                f"peakSpeed={self._currentSession.peakSpeed}"
            )
        else:
            logger.warning(
                f"DRIVE ENDED (forced) | reason={reason} | "
                f"duration={self._currentSession.duration:.1f}s | "
                f"peakRPM={self._currentSession.peakRpm} | "
                f"peakSpeed={self._currentSession.peakSpeed}"
            )

        # Log to database -- drive_end carries the SAME drive_id the
        # drive_start row did, so a server-side pair-up query groups them.
        # US-225: forceKeyOff callers thread a reason string into
        # connection_log.error_message for traceability.
        self._logDriveEvent('drive_end', endTime, reason=reason)

        # Trigger post-drive analysis.  drive_id remains set so
        # _storeStatistics stamps the analysis rows with the closing id
        # BEFORE we clear the context.
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

        # US-200: close the drive by clearing the process-wide context.
        # Subsequent writers (heartbeat, telemetry, shutdown events)
        # will see NULL drive_id until the next _startDrive.
        self._closeDriveId()

        # US-206: a clean drive-end with debounce satisfied is a
        # KEY_OFF transition.  The NEXT _startDrive sees fromState =
        # KEY_OFF and re-enables the cold-start ambient capture.
        self._lastEngineState = EngineState.KEY_OFF

        # US-228: disarm the backfill window.  Any ticks that arrive
        # after drive_end must NOT attempt to fill drive_summary for
        # the just-ended drive_id (e.g. a late telemetry callback).
        self._driveSummaryBackfillComplete = True
        self._driveSummaryBackfillDriveId = None
        self._driveSummaryBackfillDeadline = None
        self._driveSummaryBackfillFromState = None

        # US-229: clear the ECU-silence timer so a subsequent
        # _startDrive seeds it fresh -- otherwise a latent stale value
        # could fire silence immediately after the next drive_start.
        self._lastEcuReadingTime = None

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

    def _captureDriveStartSummary(self) -> None:
        """Publish drive-start metadata to the ``drive_summary`` table.

        US-206: invoked from ``_startDrive`` AFTER ``_openDriveId``
        publishes the drive_id and BEFORE the external onDriveStart
        callback fires.  Reads the latest-reading snapshot from the
        injected source (typically :class:`ObdDataLogger`) -- NO new
        ECU polls are issued.  Failure is logged and swallowed so a
        missing recorder / empty snapshot never aborts the drive.
        """
        if self._summaryRecorder is None:
            return
        driveId = getCurrentDriveId()
        if driveId is None:
            logger.debug(
                "drive_summary capture skipped: drive_id is None"
            )
            return
        snapshot: dict[str, Any] = {}
        if self._readingSnapshotSource is not None:
            try:
                raw = self._readingSnapshotSource.getLatestReadings()
                snapshot = dict(raw or {})
            except Exception as e:
                logger.warning(
                    "drive_summary snapshot read failed: %s", e
                )
                snapshot = {}
        try:
            self._summaryRecorder.captureDriveStart(
                driveId=driveId,
                snapshot=snapshot,
                fromState=self._lastEngineState,
            )
        except Exception as e:
            logger.error(
                "drive_summary capture failed | drive_id=%s | error=%s",
                driveId, e,
            )

    def _checkEcuSilenceDriveEnd(self, now: datetime) -> None:
        """Fire drive_end when ECU polling has gone silent too long.

        US-229: the RPM-based drive_end path in :meth:`_processRpmValue`
        only fires when RPM=0 readings keep arriving long enough to
        satisfy ``driveEndDurationSeconds``.  When the ECU stops
        responding entirely after engine-off, no RPM=0 reading ever
        reaches this detector -- the below-threshold timer never starts
        -- yet adapter-level heartbeats (``BATTERY_V`` via ``ELM_VOLTAGE``)
        keep ticking and the drive remained open (Drive 3 / 2026-04-23).

        This check runs on every processValue tick (including ticks
        triggered by adapter-level parameters) and closes the drive
        when ``now - _lastEcuReadingTime >= driveEndDurationSeconds``.
        Adapter-level parameters are exactly the wake-up signal we need:
        they let the check run even though the ECU is silent.

        No-op when:
            - ``driveEndDurationSeconds <= 0`` (silence check disabled
              sentinel: existing tests use 0.0 as a fast-debounce knob
              for the RPM path without wanting the silence path to
              interfere.  Production configs never set 0 -- that would
              fire drive_end on every tick),
            - no active session (drive already ended),
            - state not in {RUNNING, STOPPING} (not in an active drive),
            - ``_lastEcuReadingTime`` is None (never received an ECU
              reading for this drive -- e.g. session manually staged
              by a test without the seeded timer; safe to skip rather
              than fire spuriously).
        """
        if self._config.driveEndDurationSeconds <= 0:
            return
        if self._currentSession is None:
            return
        if self._driveState not in (DriveState.RUNNING, DriveState.STOPPING):
            return
        if self._lastEcuReadingTime is None:
            return
        elapsed = (now - self._lastEcuReadingTime).total_seconds()
        if elapsed < self._config.driveEndDurationSeconds:
            return
        logger.warning(
            "drive_end via ECU silence | "
            "elapsed=%.1fs >= driveEndDurationSeconds=%.1fs | "
            "drive_id=%s | lastRpm=%s",
            elapsed, self._config.driveEndDurationSeconds,
            getCurrentDriveId(), self._lastRpmValue,
        )
        self._endDrive()

    def _armDriveSummaryBackfill(self, startTime: datetime) -> None:
        """Arm the US-228 backfill window for the drive that just started.

        Stores the current drive_id + deadline so subsequent
        :meth:`processValue` ticks can call
        :meth:`_maybeBackfillDriveSummary` to fill still-NULL
        drive_summary columns as readings arrive.  Snapshot of
        ``_lastEngineState`` taken here (rather than re-read at each
        backfill tick) so the warm-restart rule sees the PRE-drive
        state consistently with the initial ``captureDriveStart`` call.
        """
        if self._summaryRecorder is None or self._readingSnapshotSource is None:
            # Nothing to backfill into -- flag complete so the tick
            # loop early-exits on first check.
            self._driveSummaryBackfillComplete = True
            self._driveSummaryBackfillDriveId = None
            self._driveSummaryBackfillDeadline = None
            self._driveSummaryBackfillFromState = None
            return

        driveId = getCurrentDriveId()
        if driveId is None:
            self._driveSummaryBackfillComplete = True
            self._driveSummaryBackfillDriveId = None
            self._driveSummaryBackfillDeadline = None
            self._driveSummaryBackfillFromState = None
            return

        windowSeconds = max(0.0, float(self._config.driveSummaryBackfillSeconds))
        self._driveSummaryBackfillDriveId = driveId
        self._driveSummaryBackfillDeadline = startTime + timedelta(
            seconds=windowSeconds
        )
        self._driveSummaryBackfillFromState = self._lastEngineState
        self._driveSummaryBackfillComplete = False

    def _maybeBackfillDriveSummary(self, now: datetime) -> None:
        """Fill still-NULL drive_summary columns from the latest snapshot.

        Called once per :meth:`processValue` tick.  O(1) early-exit
        when there is nothing to do (backfill disarmed, already
        complete, or past the deadline).  Any exception inside the
        backfill call is logged and swallowed -- the drive continues
        regardless.
        """
        if self._driveSummaryBackfillComplete:
            return
        if self._driveSummaryBackfillDriveId is None:
            return
        if self._driveSummaryBackfillDeadline is None:
            return
        if self._driveState != DriveState.RUNNING:
            return
        if now >= self._driveSummaryBackfillDeadline:
            # Window expired.  Flip complete so future ticks early-exit
            # and log once so operators see the window closed without
            # the row being fully populated (noisy but diagnosable).
            logger.info(
                "drive_summary backfill window expired | drive_id=%s",
                self._driveSummaryBackfillDriveId,
            )
            self._driveSummaryBackfillComplete = True
            return

        if self._summaryRecorder is None or self._readingSnapshotSource is None:
            self._driveSummaryBackfillComplete = True
            return

        try:
            raw = self._readingSnapshotSource.getLatestReadings()
            snapshot = dict(raw or {})
        except Exception as e:
            logger.warning(
                "drive_summary backfill snapshot read failed: %s", e
            )
            return

        if not snapshot:
            return

        try:
            result = self._summaryRecorder.backfillFromSnapshot(
                driveId=self._driveSummaryBackfillDriveId,
                snapshot=snapshot,
                fromState=self._driveSummaryBackfillFromState,
            )
        except Exception as e:
            logger.error(
                "drive_summary backfill failed | drive_id=%s | error=%s",
                self._driveSummaryBackfillDriveId, e,
            )
            return

        if result.complete:
            self._driveSummaryBackfillComplete = True

    def _openDriveId(self) -> int | None:
        """Mint a new drive_id and publish it to the process context.

        US-200: called on drive start.  Uses the ``drive_counter`` table
        (monotonic, persistent across restarts) for id assignment.
        Returns the new id, or None if no database is attached (unit
        tests construct a detector without DB).

        US-225 / TD-034: checks the ``pi_state.no_new_drives`` gate
        before minting.  When the gate is set (US-216 WARNING stage),
        this returns ``None`` and the drive proceeds id-less -- the
        drive-detection state machine still transitions but realtime
        rows are written without drive_id.  Invariant: the gate does
        NOT affect a currently-active drive, only new mints at
        cranking transitions.
        """
        if not self._database:
            return None
        try:
            with self._database.connect() as conn:
                # US-225 gate check.  Returning None before nextDriveId()
                # means the counter is not incremented -- the gated
                # attempt leaves no footprint in drive_counter.
                if getNoNewDrives(conn):
                    logger.warning(
                        "drive_id mint suppressed: "
                        "pi_state.no_new_drives is set (US-216 gate active)"
                    )
                    return None
                newId = nextDriveId(conn)
            setCurrentDriveId(newId)
            return newId
        except Exception as e:
            logger.error(f"Failed to mint drive_id: {e}")
            return None

    def forceKeyOff(self, reason: str) -> bool:
        """Externally terminate any active drive immediately.

        US-225 / TD-034: the US-216 PowerDownOrchestrator IMMINENT
        stage calls this to close a running drive before
        ``systemctl poweroff`` fires so downstream analytics see a
        first-class ``drive_end`` row (with a reason code) rather
        than a trailing-row gap where the drive never closes.

        Bypasses the normal RPM/speed-driven debounce -- this is an
        external signal, not a state-machine transition.  Safe to
        call when no drive is active (returns ``False`` without
        side effects).

        Args:
            reason: Short reason code persisted in
                ``connection_log.error_message`` on the drive_end
                row.  Expected values include ``'power_imminent'``
                (US-216) and ``'operator_forced'``.

        Returns:
            ``True`` when an active drive was actually terminated.
            ``False`` when no drive was active (no-op, safe).
        """
        with self._lock:
            if (
                self._driveState == DriveState.STOPPED
                or self._currentSession is None
            ):
                logger.info(
                    "forceKeyOff(%r): no active drive -- no-op", reason,
                )
                return False

            logger.warning(
                "forceKeyOff(%r): forcing drive termination "
                "(state=%s drive_id=%s)",
                reason, self._driveState.value, getCurrentDriveId(),
            )
            self._endDrive(reason=reason)
            return True

    def _closeDriveId(self) -> None:
        """Clear the process context so post-drive writers emit NULL.

        US-200: called on drive end AFTER post-drive analysis is queued.
        """
        setCurrentDriveId(None)

    def _logDriveEvent(
        self, eventType: str, timestamp: datetime, reason: str | None = None,
    ) -> None:
        """
        Log drive event to database.

        Args:
            eventType: Type of event ('drive_start' or 'drive_end')
            timestamp: Event timestamp
            reason: Optional termination reason (US-225 / TD-034).  When
                set on a drive_end event, persisted in the
                ``error_message`` column so server-side analytics can
                distinguish a debounced drive-end (``NULL``) from a
                forced drive-end (e.g. ``'power_imminent'``).
        """
        if not self._database:
            return

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                # TD-027 / US-202: canonical ISO-8601 UTC via the shared helper.
                # The `timestamp` parameter (naive datetime.now() at call site)
                # remains useful for in-memory session tracking but must not
                # land in connection_log -- Session 23 rows showed exactly this
                # drift (07:xx local vs 12:xx UTC).
                # US-200: stamp drive_id so connection_log drive_start /
                # drive_end rows group with the matching realtime rows.
                cursor.execute(
                    """
                    INSERT INTO connection_log
                    (timestamp, event_type, mac_address, success,
                     error_message, drive_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utcIsoNow(),
                        eventType,
                        f"profile:{self._config.profileId}",
                        True,
                        reason,
                        getCurrentDriveId(),
                    )
                )
                logger.debug(
                    f"Drive event logged: {eventType}"
                    + (f" reason={reason}" if reason else "")
                )
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

    def getTimingInfo(self) -> dict[str, Any]:
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
