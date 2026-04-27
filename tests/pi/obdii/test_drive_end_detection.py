################################################################################
# File Name: test_drive_end_detection.py
# Purpose/Description: Tests for ECU-silence-based drive_end detection
#                      (US-229 -- Drive 3 engine-off 2026-04-23 16:46:21 UTC
#                      but no drive_end event fired; ELM_VOLTAGE adapter
#                      heartbeat kept DriveDetector in RUNNING for 6+ min).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex (US-229) | Initial -- ECU-silence drive_end unit tests.
# ================================================================================
################################################################################

"""Tests for the US-229 ECU-silence drive_end signal in :class:`DriveDetector`.

Root cause of the Drive 3 bug: RPM-based drive_end via
``_processRpmValue`` only fires when RPM=0 readings KEEP arriving for
``driveEndDurationSeconds``.  When the ECU stops responding entirely
post-engine-off, no RPM=0 reading ever reaches ``processValue`` -- the
below-threshold timer is never started -- yet ``BATTERY_V`` (ELM_VOLTAGE,
adapter-level) keeps ticking and the drive stays open forever.

Fix shape: track ``_lastEcuReadingTime`` on every ECU-sourced
``processValue`` call; run a silence check each tick that fires
``drive_end`` once the last ECU reading is older than
``driveEndDurationSeconds``.  Adapter-level heartbeats (BATTERY_V) drive
the check forward but do NOT reset the timer.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive.types import DetectorState, DriveSession, DriveState

# ================================================================================
# Fixtures
# ================================================================================


def _baseConfig() -> dict[str, Any]:
    """Minimal config: no DB, debounce values short enough for unit speed."""
    return {
        'pi': {
            'analysis': {
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 0.01,
                'driveEndRpmThreshold': 0,
                # 60s default mirrors config.json -- tests parametrize
                # shorter windows where useful.
                'driveEndDurationSeconds': 60,
                'triggerAfterDrive': False,
                'driveSummaryBackfillSeconds': 0,
            },
        },
    }


@pytest.fixture()
def runningDetector() -> DriveDetector:
    """A DriveDetector already in DriveState.RUNNING with no DB attached."""
    detector = DriveDetector(config=_baseConfig())
    detector.start()
    # Drive into RUNNING without exercising the RPM state machine -- no
    # DB, no callbacks, no statistics engine needed for the silence tests.
    detector._driveState = DriveState.RUNNING
    detector._currentSession = DriveSession(startTime=datetime.now())
    # _lastEcuReadingTime is populated by _startDrive in prod; simulate
    # that bootstrap at construction time.
    detector._lastEcuReadingTime = datetime.now()
    return detector


# ================================================================================
# Acceptance #4: ELM_VOLTAGE-only heartbeat post-engine-off triggers drive_end
# ================================================================================


class TestEcuSilenceDriveEnd:
    """ECU-silence signal fires drive_end when only BATTERY_V keeps ticking."""

    def test_ecuSilence_onlyBatteryVArrives_firesDriveEnd(
        self, runningDetector: DriveDetector
    ) -> None:
        """Drive 3 bug repro: engine off, only ELM_VOLTAGE keeps ticking."""
        # Arrange: last ECU reading was 61s ago -- past the 60s debounce.
        runningDetector._lastEcuReadingTime = (
            datetime.now() - timedelta(seconds=61)
        )
        assert runningDetector._driveState == DriveState.RUNNING

        # Act: BATTERY_V (adapter-level heartbeat) arrives.
        runningDetector.processValue('BATTERY_V', 12.4)

        # Assert: silence check fired drive_end -> STOPPED.
        assert runningDetector._driveState == DriveState.STOPPED
        assert runningDetector._currentSession is None

    def test_ecuSilence_batteryVDoesNotResetTimer(
        self, runningDetector: DriveDetector
    ) -> None:
        """BATTERY_V is adapter-level; its arrival must not reset the silence clock."""
        oldTime = datetime.now() - timedelta(seconds=30)
        runningDetector._lastEcuReadingTime = oldTime

        runningDetector.processValue('BATTERY_V', 12.4)

        # _lastEcuReadingTime still 30s in the past -- BATTERY_V did NOT
        # touch it (the detector is still in RUNNING because the 30s
        # elapsed has not yet crossed the 60s debounce).
        assert runningDetector._lastEcuReadingTime == oldTime
        assert runningDetector._driveState == DriveState.RUNNING

    def test_ecuSilence_belowDebounce_doesNotFire(
        self, runningDetector: DriveDetector
    ) -> None:
        """Guard: silence for < 60s does NOT trigger drive_end."""
        runningDetector._lastEcuReadingTime = (
            datetime.now() - timedelta(seconds=45)
        )

        runningDetector.processValue('BATTERY_V', 12.4)

        assert runningDetector._driveState == DriveState.RUNNING
        assert runningDetector._currentSession is not None


# ================================================================================
# Acceptance #5: continued ECU polls prevent false drive_end
# ================================================================================


class TestEcuReadingResetsTimer:
    """Mode 01 PID arriving resets the silence clock -- drive continues."""

    @pytest.mark.parametrize(
        "ecuParameter",
        [
            'RPM',
            'SPEED',
            'COOLANT_TEMP',
            'ENGINE_LOAD',
            'FUEL_SYSTEM_STATUS',
            'MIL_ON',
            'RUNTIME_SEC',
            'BAROMETRIC_KPA',
        ],
    )
    def test_ecuReading_resetsLastEcuReadingTime(
        self, runningDetector: DriveDetector, ecuParameter: str
    ) -> None:
        """Each ECU-sourced parameter bumps the silence timer forward."""
        oldTime = datetime.now() - timedelta(seconds=45)
        runningDetector._lastEcuReadingTime = oldTime

        # Non-zero value avoids tripping the RPM-below-threshold branch
        # for RPM + SPEED; value shape is irrelevant for the other params.
        runningDetector.processValue(ecuParameter, 1500.0)

        # _lastEcuReadingTime advanced past oldTime.
        assert runningDetector._lastEcuReadingTime is not None
        assert runningDetector._lastEcuReadingTime > oldTime
        # Drive is still alive.
        assert runningDetector._driveState == DriveState.RUNNING
        assert runningDetector._currentSession is not None

    def test_ecuReading_pastDebounceWindow_doesNotFireIfTimerAlreadyReset(
        self, runningDetector: DriveDetector
    ) -> None:
        """Two-tick sequence: RPM bumps timer, then BATTERY_V inside window -- drive continues."""
        # Seed: silence elapsed just under 60s at start of sequence.
        runningDetector._lastEcuReadingTime = (
            datetime.now() - timedelta(seconds=50)
        )

        # Tick 1: RPM arrives and resets the timer.
        runningDetector.processValue('RPM', 2800.0)
        # Tick 2: BATTERY_V arrives immediately after -- timer is fresh.
        runningDetector.processValue('BATTERY_V', 12.4)

        assert runningDetector._driveState == DriveState.RUNNING


# ================================================================================
# Acceptance: no-fire when detector has no active drive
# ================================================================================


class TestEcuSilenceNoActiveDrive:
    """Silence check is a no-op in STOPPED / UNKNOWN / no-session states."""

    def test_stopped_noActiveDrive_noFire(self) -> None:
        detector = DriveDetector(config=_baseConfig())
        detector.start()
        # Fresh detector is STOPPED; _currentSession is None.
        detector._lastEcuReadingTime = (
            datetime.now() - timedelta(seconds=600)
        )

        # Act: BATTERY_V ticks; silence check sees no currentSession.
        detector.processValue('BATTERY_V', 12.4)

        # Still STOPPED; no drive_end side effect (no session to end).
        assert detector._driveState == DriveState.STOPPED
        assert detector._currentSession is None

    def test_monitoringNotStarted_doesNotAdvanceTimer(self) -> None:
        """processValue returns early when detector isn't MONITORING."""
        detector = DriveDetector(config=_baseConfig())
        # Not calling detector.start() -> _detectorState stays IDLE.
        assert detector._detectorState == DetectorState.IDLE
        # No assignment of _lastEcuReadingTime should occur.

        detector.processValue('RPM', 3000.0)

        assert detector._lastEcuReadingTime is None


# ================================================================================
# Acceptance: _startDrive seeds timer + _endDrive clears it
# ================================================================================


class TestSilenceTimerLifecycle:
    """_startDrive + _endDrive correctly manage _lastEcuReadingTime."""

    def test_endDrive_clearsLastEcuReadingTime(
        self, runningDetector: DriveDetector
    ) -> None:
        """After clean drive_end, silence timer is None (so next drive starts fresh)."""
        assert runningDetector._lastEcuReadingTime is not None

        # End the drive via the public API path (bypasses RPM state machine).
        runningDetector._endDrive()

        assert runningDetector._driveState == DriveState.STOPPED
        assert runningDetector._lastEcuReadingTime is None

    def test_startDrive_seedsLastEcuReadingTime(self) -> None:
        """_startDrive initializes the silence timer so we don't fire immediately."""
        detector = DriveDetector(config=_baseConfig())
        detector.start()
        assert detector._lastEcuReadingTime is None

        # Force the detector through a drive-start.  Monkey-patch the
        # DB-touching helpers (_openDriveId, _logDriveEvent,
        # _captureDriveStartSummary) since we don't have a DB attached.
        detector._openDriveId = lambda: None  # type: ignore[method-assign]
        detector._logDriveEvent = lambda *a, **kw: None  # type: ignore[method-assign]
        detector._captureDriveStartSummary = lambda: None  # type: ignore[method-assign]
        detector._armDriveSummaryBackfill = lambda _t: None  # type: ignore[method-assign]
        detector._triggerAnalysis = lambda: None  # type: ignore[method-assign]

        startTime = datetime.now()
        detector._startDrive(startTime)

        assert detector._driveState == DriveState.RUNNING
        assert detector._lastEcuReadingTime == startTime


# ================================================================================
# Acceptance: RPM-based drive_end path still works (no regression)
# ================================================================================


class TestSilenceCheckDisabledSentinel:
    """driveEndDurationSeconds <= 0 disables the silence check entirely."""

    def test_durationZero_silenceCheckDoesNotFire(self) -> None:
        """Fast-debounce tests (duration=0) must NOT trip silence on first tick.

        Existing tests in test_drive_summary_backfill.py +
        test_drive_summary_integration.py use duration=0 to make the
        RPM debounce fire immediately without caring about the silence
        path.  The silence check must treat 0 as opt-out.
        """
        config = _baseConfig()
        config['pi']['analysis']['driveEndDurationSeconds'] = 0.0
        detector = DriveDetector(config=config)
        detector.start()
        detector._driveState = DriveState.RUNNING
        detector._currentSession = DriveSession(startTime=datetime.now())
        detector._lastEcuReadingTime = datetime.now()

        # Act: BATTERY_V tick would fire silence in a duration>0 config.
        detector.processValue('BATTERY_V', 12.4)

        # Silence did NOT fire because the sentinel is respected.
        assert detector._driveState == DriveState.RUNNING
        assert detector._currentSession is not None

    def test_durationNegative_silenceCheckDoesNotFire(self) -> None:
        """Defensive: any <=0 value is treated as disabled."""
        config = _baseConfig()
        config['pi']['analysis']['driveEndDurationSeconds'] = -5.0
        detector = DriveDetector(config=config)
        detector.start()
        detector._driveState = DriveState.RUNNING
        detector._currentSession = DriveSession(startTime=datetime.now())
        detector._lastEcuReadingTime = (
            datetime.now() - timedelta(seconds=3600)
        )

        detector.processValue('BATTERY_V', 12.4)

        assert detector._driveState == DriveState.RUNNING


class TestRpmBasedDriveEndStillWorks:
    """The existing RPM-below-threshold debounce path is unchanged by US-229."""

    def test_rpmDebounce_firesDriveEnd_whenReadingsContinue(self) -> None:
        """RPM=0 readings arriving continuously for the debounce window still fire."""
        config = _baseConfig()
        # Short debounce so the test runs fast.
        config['pi']['analysis']['driveEndDurationSeconds'] = 0.05
        detector = DriveDetector(config=config)
        detector.start()

        # Place detector in RUNNING via manual state (same seam used
        # above; no DB -> skip full _startDrive).
        detector._driveState = DriveState.RUNNING
        detector._currentSession = DriveSession(startTime=datetime.now())
        detector._lastEcuReadingTime = datetime.now()

        # First RPM=0 starts the below-threshold timer (STOPPING).
        detector.processValue('RPM', 0.0)
        assert detector._driveState == DriveState.STOPPING

        # Wait past the 50 ms debounce window using elapsed wall-clock --
        # sleep is deterministic at this scale.
        import time
        time.sleep(0.08)
        detector.processValue('RPM', 0.0)

        assert detector._driveState == DriveState.STOPPED
        assert detector._currentSession is None
