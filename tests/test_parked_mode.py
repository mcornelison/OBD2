################################################################################
# File Name: test_parked_mode.py
# Purpose/Description: Tests for Parked Mode Display (US-128)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-12    | Ralph Agent  | Initial implementation for US-128
# ================================================================================
################################################################################
"""
Tests for the Parked Mode Display (US-128).

Validates:
- EngineMode enum values
- DriveSummary formatting and placeholder behavior
- AdvisoryMessage dataclass
- ParkedModeState construction with various states
- ParkedModeTracker mode transitions (running → parked, parked → running)
- Configurable RPM=0 sustain threshold
- Display content with sync states (no sync, in progress, complete)
- Advisory message presence/absence
- Battery display with/without UPS
- Graceful degradation when sync not configured
"""

from pi.display.screens.parked_mode import (
    DEFAULT_PARKED_THRESHOLD_SECONDS,
    DEFAULT_RUNNING_THRESHOLD_SECONDS,
    AdvisoryMessage,
    EngineMode,
    ParkedModeState,
    ParkedModeTracker,
    buildDriveSummary,
    buildParkedModeState,
    formatDistance,
)
from pi.display.screens.system_detail import (
    SyncStatus,
    buildBatteryInfo,
    buildSyncInfo,
)

# ================================================================================
# EngineMode Enum Tests
# ================================================================================


class TestEngineMode:
    """Tests for EngineMode enum values."""

    def test_engineMode_hasTwoValues(self):
        """
        Given: EngineMode enum
        When: checking values
        Then: contains RUNNING and PARKED
        """
        assert EngineMode.RUNNING.value == "running"
        assert EngineMode.PARKED.value == "parked"

    def test_engineMode_displayLabel(self):
        """
        Given: each EngineMode value
        When: getting display label
        Then: returns human-readable string
        """
        assert EngineMode.RUNNING.displayLabel == "Running"
        assert EngineMode.PARKED.displayLabel == "Parked"


# ================================================================================
# DriveSummary Tests
# ================================================================================


class TestDriveSummary:
    """Tests for DriveSummary dataclass and builder."""

    def test_buildDriveSummary_withAllData(self):
        """
        Given: complete drive data
        When: building summary
        Then: formats duration, distance, and alert count
        """
        summary = buildDriveSummary(
            durationSeconds=5400.0,
            distanceMiles=45.2,
            alertCount=2,
        )

        assert summary.durationSeconds == 5400.0
        assert summary.distanceMiles == 45.2
        assert summary.alertCount == 2
        assert summary.formattedDuration == "1h 30m"
        assert summary.formattedDistance == "45.2 mi"

    def test_buildDriveSummary_shortDrive(self):
        """
        Given: a short drive under one hour
        When: building summary
        Then: formats without hours
        """
        summary = buildDriveSummary(
            durationSeconds=1200.0,
            distanceMiles=8.7,
            alertCount=0,
        )

        assert summary.formattedDuration == "20m"
        assert summary.formattedDistance == "8.7 mi"
        assert summary.alertCount == 0

    def test_buildDriveSummary_zeroDuration(self):
        """
        Given: zero duration drive
        When: building summary
        Then: shows 0m and 0.0 mi
        """
        summary = buildDriveSummary(
            durationSeconds=0.0,
            distanceMiles=0.0,
            alertCount=0,
        )

        assert summary.formattedDuration == "0m"
        assert summary.formattedDistance == "0.0 mi"

    def test_buildDriveSummary_placeholder(self):
        """
        Given: None values (no drive data available)
        When: building summary
        Then: returns placeholder summary with dashes
        """
        summary = buildDriveSummary(
            durationSeconds=None,
            distanceMiles=None,
            alertCount=None,
        )

        assert summary.durationSeconds == 0.0
        assert summary.distanceMiles == 0.0
        assert summary.alertCount == 0
        assert summary.formattedDuration == "--"
        assert summary.formattedDistance == "--"
        assert summary.isPlaceholder is True

    def test_driveSummary_isPlaceholder_false(self):
        """
        Given: valid drive data
        When: checking isPlaceholder
        Then: returns False
        """
        summary = buildDriveSummary(
            durationSeconds=600.0,
            distanceMiles=5.0,
            alertCount=0,
        )

        assert summary.isPlaceholder is False


# ================================================================================
# FormatDistance Tests
# ================================================================================


class TestFormatDistance:
    """Tests for formatDistance function."""

    def test_formatDistance_normal(self):
        """
        Given: a distance value
        When: formatting
        Then: returns value with 'mi' suffix
        """
        assert formatDistance(45.2) == "45.2 mi"

    def test_formatDistance_zero(self):
        """
        Given: zero distance
        When: formatting
        Then: returns '0.0 mi'
        """
        assert formatDistance(0.0) == "0.0 mi"

    def test_formatDistance_wholeMiles(self):
        """
        Given: whole number distance
        When: formatting
        Then: shows one decimal place
        """
        assert formatDistance(10.0) == "10.0 mi"

    def test_formatDistance_longDistance(self):
        """
        Given: a long distance
        When: formatting
        Then: shows one decimal place
        """
        assert formatDistance(123.456) == "123.5 mi"


# ================================================================================
# AdvisoryMessage Tests
# ================================================================================


class TestAdvisoryMessage:
    """Tests for AdvisoryMessage dataclass."""

    def test_advisoryMessage_creation(self):
        """
        Given: message text and priority
        When: creating advisory
        Then: stores values correctly
        """
        msg = AdvisoryMessage(message="Oil change due at 80k miles", priority="info")
        assert msg.message == "Oil change due at 80k miles"
        assert msg.priority == "info"

    def test_advisoryMessage_warningPriority(self):
        """
        Given: a warning priority advisory
        When: creating advisory
        Then: stores warning priority
        """
        msg = AdvisoryMessage(message="Check engine light history", priority="warning")
        assert msg.priority == "warning"


# ================================================================================
# ParkedModeState Tests
# ================================================================================


class TestParkedModeState:
    """Tests for ParkedModeState dataclass."""

    def test_parkedModeState_creation(self):
        """
        Given: all required state components
        When: creating ParkedModeState
        Then: stores all values correctly
        """
        syncInfo = buildSyncInfo(lastSyncTimestamp="2026-04-12T10:00:00Z")
        batteryInfo = buildBatteryInfo(True, 78.0, 1.5)
        summary = buildDriveSummary(3600.0, 25.0, 1)

        state = ParkedModeState(
            syncInfo=syncInfo,
            driveSummary=summary,
            advisoryMessages=[],
            batteryInfo=batteryInfo,
        )

        assert state.syncInfo.status == SyncStatus.COMPLETE
        assert state.driveSummary.formattedDuration == "1h 0m"
        assert state.advisoryMessages == []
        assert state.batteryInfo.displayText == "78% (~1.5 hrs)"

    def test_parkedModeState_withAdvisories(self):
        """
        Given: advisory messages from server
        When: creating state
        Then: advisory list populated
        """
        syncInfo = buildSyncInfo(lastSyncTimestamp="2026-04-12T10:00:00Z")
        batteryInfo = buildBatteryInfo(True, 50.0, 0.8)
        summary = buildDriveSummary(1800.0, 12.0, 0)

        advisories = [
            AdvisoryMessage(message="Tune revision 4.2 available", priority="info"),
            AdvisoryMessage(message="Check boost logs from last drive", priority="warning"),
        ]

        state = ParkedModeState(
            syncInfo=syncInfo,
            driveSummary=summary,
            advisoryMessages=advisories,
            batteryInfo=batteryInfo,
        )

        assert len(state.advisoryMessages) == 2
        assert state.advisoryMessages[0].message == "Tune revision 4.2 available"

    def test_parkedModeState_noSync(self):
        """
        Given: sync never configured
        When: creating state
        Then: sync shows 'Never'
        """
        syncInfo = buildSyncInfo(lastSyncTimestamp=None)
        batteryInfo = buildBatteryInfo(False)
        summary = buildDriveSummary(None, None, None)

        state = ParkedModeState(
            syncInfo=syncInfo,
            driveSummary=summary,
            advisoryMessages=[],
            batteryInfo=batteryInfo,
        )

        assert state.syncInfo.status == SyncStatus.NEVER
        assert state.syncInfo.displayText == "Never"
        assert state.batteryInfo.displayText == "--"
        assert state.driveSummary.isPlaceholder is True

    def test_parkedModeState_syncInProgress(self):
        """
        Given: sync currently running
        When: creating state
        Then: shows sync progress
        """
        syncInfo = buildSyncInfo(syncInProgress=True, progressPercent=45.0)
        batteryInfo = buildBatteryInfo(True, 85.0, 2.0)
        summary = buildDriveSummary(2700.0, 18.5, 0)

        state = ParkedModeState(
            syncInfo=syncInfo,
            driveSummary=summary,
            advisoryMessages=[],
            batteryInfo=batteryInfo,
        )

        assert state.syncInfo.status == SyncStatus.IN_PROGRESS
        assert state.syncInfo.displayText == "Syncing to server... 45%"


# ================================================================================
# buildParkedModeState Tests
# ================================================================================


class TestBuildParkedModeState:
    """Tests for buildParkedModeState builder function."""

    def test_buildParkedModeState_fullData(self):
        """
        Given: all subsystem data available
        When: building parked mode state
        Then: assembles all components correctly
        """
        advisories = [AdvisoryMessage(message="Firmware update ready", priority="info")]

        state = buildParkedModeState(
            upsAvailable=True,
            batteryLevelPercent=78.0,
            batteryEstimatedHours=1.5,
            lastSyncTimestamp="2026-04-12T10:00:00Z",
            syncInProgress=False,
            syncProgressPercent=0.0,
            driveDurationSeconds=3600.0,
            driveDistanceMiles=25.0,
            driveAlertCount=1,
            advisoryMessages=advisories,
        )

        assert state.batteryInfo.displayText == "78% (~1.5 hrs)"
        assert state.syncInfo.status == SyncStatus.COMPLETE
        assert state.driveSummary.formattedDuration == "1h 0m"
        assert len(state.advisoryMessages) == 1

    def test_buildParkedModeState_noUps(self):
        """
        Given: UPS not available
        When: building state
        Then: battery shows placeholder
        """
        state = buildParkedModeState(
            upsAvailable=False,
            batteryLevelPercent=None,
            batteryEstimatedHours=None,
            lastSyncTimestamp=None,
            syncInProgress=False,
            syncProgressPercent=0.0,
            driveDurationSeconds=0.0,
            driveDistanceMiles=0.0,
            driveAlertCount=0,
            advisoryMessages=[],
        )

        assert state.batteryInfo.displayText == "--"
        assert state.batteryInfo.available is False

    def test_buildParkedModeState_syncInProgress(self):
        """
        Given: active sync
        When: building state
        Then: shows sync progress percentage
        """
        state = buildParkedModeState(
            upsAvailable=True,
            batteryLevelPercent=60.0,
            batteryEstimatedHours=1.0,
            lastSyncTimestamp="2026-04-12T09:00:00Z",
            syncInProgress=True,
            syncProgressPercent=72.0,
            driveDurationSeconds=1800.0,
            driveDistanceMiles=12.0,
            driveAlertCount=0,
            advisoryMessages=[],
        )

        assert state.syncInfo.status == SyncStatus.IN_PROGRESS
        assert state.syncInfo.displayText == "Syncing to server... 72%"

    def test_buildParkedModeState_noDriveData(self):
        """
        Given: no drive data (first power on)
        When: building state
        Then: drive summary shows placeholders
        """
        state = buildParkedModeState(
            upsAvailable=True,
            batteryLevelPercent=100.0,
            batteryEstimatedHours=3.0,
            lastSyncTimestamp=None,
            syncInProgress=False,
            syncProgressPercent=0.0,
            driveDurationSeconds=None,
            driveDistanceMiles=None,
            driveAlertCount=None,
            advisoryMessages=[],
        )

        assert state.driveSummary.isPlaceholder is True
        assert state.driveSummary.formattedDuration == "--"
        assert state.driveSummary.formattedDistance == "--"

    def test_buildParkedModeState_emptyAdvisories(self):
        """
        Given: no advisory messages
        When: building state
        Then: advisory list is empty
        """
        state = buildParkedModeState(
            upsAvailable=True,
            batteryLevelPercent=90.0,
            batteryEstimatedHours=2.5,
            lastSyncTimestamp="2026-04-12T10:00:00Z",
            syncInProgress=False,
            syncProgressPercent=0.0,
            driveDurationSeconds=600.0,
            driveDistanceMiles=3.0,
            driveAlertCount=0,
            advisoryMessages=[],
        )

        assert state.advisoryMessages == []


# ================================================================================
# ParkedModeTracker - Mode Detection Tests
# ================================================================================


class TestParkedModeTrackerModeDetection:
    """Tests for ParkedModeTracker engine mode detection."""

    def test_tracker_initialMode_isRunning(self):
        """
        Given: a new tracker
        When: checking initial mode
        Then: starts in RUNNING mode
        """
        tracker = ParkedModeTracker()
        assert tracker.currentMode == EngineMode.RUNNING

    def test_tracker_singleZeroRpm_staysRunning(self):
        """
        Given: tracker in RUNNING mode
        When: one RPM=0 reading arrives
        Then: stays RUNNING (not sustained long enough)
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.RUNNING

    def test_tracker_sustainedZeroRpm_transitionsToParked(self):
        """
        Given: tracker in RUNNING mode
        When: RPM=0 sustained for longer than threshold
        Then: transitions to PARKED mode
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=3.0, rpm=0.0)
        tracker.addRpmReading(timestamp=6.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.PARKED

    def test_tracker_rpmFlicker_staysRunning(self):
        """
        Given: tracker in RUNNING mode
        When: RPM drops to 0 but comes back before threshold
        Then: stays RUNNING (flicker protection)
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=0.0, rpm=800.0)
        tracker.addRpmReading(timestamp=1.0, rpm=0.0)
        tracker.addRpmReading(timestamp=2.0, rpm=0.0)
        tracker.addRpmReading(timestamp=3.0, rpm=750.0)
        assert tracker.currentMode == EngineMode.RUNNING

    def test_tracker_parkedToRunning_sustainedRpm(self):
        """
        Given: tracker in PARKED mode
        When: RPM > 0 sustained for longer than threshold
        Then: transitions back to RUNNING
        """
        tracker = ParkedModeTracker(
            parkedThresholdSeconds=5.0,
            runningThresholdSeconds=3.0,
        )
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=6.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.PARKED

        tracker.addRpmReading(timestamp=7.0, rpm=800.0)
        tracker.addRpmReading(timestamp=11.0, rpm=850.0)
        assert tracker.currentMode == EngineMode.RUNNING

    def test_tracker_parkedToRunning_rpmFlicker_staysParked(self):
        """
        Given: tracker in PARKED mode
        When: RPM blips > 0 but drops back before threshold
        Then: stays PARKED (starter crank without catch)
        """
        tracker = ParkedModeTracker(
            parkedThresholdSeconds=5.0,
            runningThresholdSeconds=3.0,
        )
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=6.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.PARKED

        tracker.addRpmReading(timestamp=7.0, rpm=200.0)
        tracker.addRpmReading(timestamp=8.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.PARKED

    def test_tracker_defaultThresholds(self):
        """
        Given: tracker with default thresholds
        When: checking defaults
        Then: uses module-level constants
        """
        tracker = ParkedModeTracker()
        assert tracker.parkedThresholdSeconds == DEFAULT_PARKED_THRESHOLD_SECONDS
        assert tracker.runningThresholdSeconds == DEFAULT_RUNNING_THRESHOLD_SECONDS


# ================================================================================
# ParkedModeTracker - Transition Callback Tests
# ================================================================================


class TestParkedModeTrackerCallbacks:
    """Tests for ParkedModeTracker transition tracking."""

    def test_tracker_transitionToParked_recordsTransitionTime(self):
        """
        Given: tracker transitioning to PARKED
        When: checking last transition
        Then: records the transition timestamp
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=10.0, rpm=0.0)
        tracker.addRpmReading(timestamp=16.0, rpm=0.0)

        assert tracker.currentMode == EngineMode.PARKED
        assert tracker.lastTransitionTimestamp == 16.0

    def test_tracker_transitionToRunning_recordsTransitionTime(self):
        """
        Given: tracker in PARKED transitioning to RUNNING
        When: checking last transition
        Then: records the transition timestamp
        """
        tracker = ParkedModeTracker(
            parkedThresholdSeconds=5.0,
            runningThresholdSeconds=3.0,
        )
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=6.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.PARKED

        tracker.addRpmReading(timestamp=7.0, rpm=800.0)
        tracker.addRpmReading(timestamp=11.0, rpm=800.0)
        assert tracker.currentMode == EngineMode.RUNNING
        assert tracker.lastTransitionTimestamp == 11.0

    def test_tracker_noTransition_timestampIsNone(self):
        """
        Given: new tracker with no transitions
        When: checking last transition
        Then: returns None
        """
        tracker = ParkedModeTracker()
        assert tracker.lastTransitionTimestamp is None


# ================================================================================
# ParkedModeTracker - Edge Cases
# ================================================================================


class TestParkedModeTrackerEdgeCases:
    """Tests for ParkedModeTracker edge cases."""

    def test_tracker_exactThreshold_transitions(self):
        """
        Given: RPM=0 for exactly the threshold duration
        When: the threshold reading arrives
        Then: transitions to PARKED
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=5.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.PARKED

    def test_tracker_justUnderThreshold_staysRunning(self):
        """
        Given: RPM=0 for just under the threshold duration
        When: reading arrives just before threshold
        Then: stays RUNNING
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=4.9, rpm=0.0)
        assert tracker.currentMode == EngineMode.RUNNING

    def test_tracker_resetDrive_clearsState(self):
        """
        Given: tracker in PARKED mode
        When: resetDrive called
        Then: returns to RUNNING with cleared state
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=6.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.PARKED

        tracker.resetDrive()
        assert tracker.currentMode == EngineMode.RUNNING
        assert tracker.lastTransitionTimestamp is None

    def test_tracker_multipleTransitions(self):
        """
        Given: tracker cycling through multiple mode changes
        When: engine starts and stops multiple times
        Then: correctly tracks each transition
        """
        tracker = ParkedModeTracker(
            parkedThresholdSeconds=5.0,
            runningThresholdSeconds=3.0,
        )

        tracker.addRpmReading(timestamp=0.0, rpm=800.0)
        assert tracker.currentMode == EngineMode.RUNNING

        tracker.addRpmReading(timestamp=10.0, rpm=0.0)
        tracker.addRpmReading(timestamp=16.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.PARKED

        tracker.addRpmReading(timestamp=20.0, rpm=750.0)
        tracker.addRpmReading(timestamp=24.0, rpm=800.0)
        assert tracker.currentMode == EngineMode.RUNNING

        tracker.addRpmReading(timestamp=30.0, rpm=0.0)
        tracker.addRpmReading(timestamp=36.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.PARKED

    def test_tracker_customThresholds(self):
        """
        Given: tracker with custom thresholds
        When: RPM=0 for less than custom parked threshold
        Then: respects custom threshold value
        """
        tracker = ParkedModeTracker(
            parkedThresholdSeconds=30.0,
            runningThresholdSeconds=10.0,
        )

        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=20.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.RUNNING

        tracker.addRpmReading(timestamp=31.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.PARKED

    def test_tracker_zeroThenNonZero_immediateRestart(self):
        """
        Given: engine just turned off
        When: RPM goes to 0 then immediately back to positive
        Then: never transitions to PARKED
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=0.5, rpm=600.0)
        assert tracker.currentMode == EngineMode.RUNNING

    def test_tracker_negativeTimeDelta_ignored(self):
        """
        Given: timestamps arrive out of order
        When: a reading with earlier timestamp arrives
        Then: does not corrupt state (stays in current mode)
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=10.0, rpm=0.0)
        tracker.addRpmReading(timestamp=5.0, rpm=0.0)
        assert tracker.currentMode == EngineMode.RUNNING


# ================================================================================
# ParkedModeTracker - getState Tests
# ================================================================================


class TestParkedModeTrackerGetState:
    """Tests for ParkedModeTracker.getState() display state building."""

    def test_getState_whileParked_syncComplete(self):
        """
        Given: tracker in PARKED mode with sync complete
        When: getting display state
        Then: returns ParkedModeState with sync complete info
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=6.0, rpm=0.0)

        state = tracker.getState(
            upsAvailable=True,
            batteryLevelPercent=78.0,
            batteryEstimatedHours=1.5,
            lastSyncTimestamp="2026-04-12T10:00:00Z",
            syncInProgress=False,
            syncProgressPercent=0.0,
            driveDurationSeconds=3600.0,
            driveDistanceMiles=25.0,
            driveAlertCount=1,
            advisoryMessages=[],
        )

        assert state.syncInfo.status == SyncStatus.COMPLETE
        assert state.batteryInfo.displayText == "78% (~1.5 hrs)"
        assert state.driveSummary.formattedDuration == "1h 0m"

    def test_getState_whileParked_noSync(self):
        """
        Given: tracker in PARKED mode with no sync configured
        When: getting display state
        Then: shows 'Never' for sync and placeholders
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=6.0, rpm=0.0)

        state = tracker.getState(
            upsAvailable=False,
            batteryLevelPercent=None,
            batteryEstimatedHours=None,
            lastSyncTimestamp=None,
            syncInProgress=False,
            syncProgressPercent=0.0,
            driveDurationSeconds=None,
            driveDistanceMiles=None,
            driveAlertCount=None,
            advisoryMessages=[],
        )

        assert state.syncInfo.status == SyncStatus.NEVER
        assert state.syncInfo.displayText == "Never"
        assert state.batteryInfo.displayText == "--"
        assert state.driveSummary.isPlaceholder is True

    def test_getState_whileParked_withAdvisories(self):
        """
        Given: tracker in PARKED mode with advisory messages
        When: getting display state
        Then: passes advisory messages through
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=0.0, rpm=0.0)
        tracker.addRpmReading(timestamp=6.0, rpm=0.0)

        advisories = [
            AdvisoryMessage(message="New tune available", priority="info"),
        ]

        state = tracker.getState(
            upsAvailable=True,
            batteryLevelPercent=90.0,
            batteryEstimatedHours=2.5,
            lastSyncTimestamp="2026-04-12T10:00:00Z",
            syncInProgress=False,
            syncProgressPercent=0.0,
            driveDurationSeconds=1800.0,
            driveDistanceMiles=10.0,
            driveAlertCount=0,
            advisoryMessages=advisories,
        )

        assert len(state.advisoryMessages) == 1
        assert state.advisoryMessages[0].message == "New tune available"

    def test_getState_whileRunning_stillBuildsState(self):
        """
        Given: tracker in RUNNING mode
        When: getting display state
        Then: still returns valid ParkedModeState (caller decides visibility)
        """
        tracker = ParkedModeTracker(parkedThresholdSeconds=5.0)
        tracker.addRpmReading(timestamp=0.0, rpm=800.0)

        state = tracker.getState(
            upsAvailable=True,
            batteryLevelPercent=95.0,
            batteryEstimatedHours=3.0,
            lastSyncTimestamp=None,
            syncInProgress=False,
            syncProgressPercent=0.0,
            driveDurationSeconds=600.0,
            driveDistanceMiles=5.0,
            driveAlertCount=0,
            advisoryMessages=[],
        )

        assert isinstance(state, ParkedModeState)
        assert state.driveSummary.formattedDuration == "10m"
