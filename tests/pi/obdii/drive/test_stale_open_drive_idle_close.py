################################################################################
# File Name: test_stale_open_drive_idle_close.py
# Purpose/Description: US-625 (A-9 Root 2) -- a drive with no recent samples must
#                      CLOSE on a bounded idle rather than stay open and claim
#                      whatever arrives next.  Measured by Spool 2026-08-28:
#                      drive 51's real leg ran 22:09:43-22:49:48 UTC at
#                      438 rows/min, then 24 rows arrived ~52 minutes later still
#                      stamped drive_id=51, dragging the drive's apparent rate
#                      down to 189 rows/min.  US-388 fixed the close paths that
#                      run from RUNNING/STOPPING; these tests pin the states
#                      US-388 could NOT reach -- a live drive_id whose session or
#                      state leaves every existing close path early-returning.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-625) | Initial -- bounded-idle close for a stale-open
#                               drive; stop()/reset() context custody.
# ================================================================================
################################################################################

"""US-625 -- the stale-open drive leak that US-388 did not reach.

US-388 (F-107 Root-2) made the close deadline-anchored and added the off-tick
``evaluateTimeouts`` pass.  Both of its close paths are guarded:

* :meth:`DriveDetector._maybeCloseOnDeadline` no-ops unless the state is
  ``STOPPING``;
* :meth:`DriveDetector._checkEcuSilenceDriveEnd` no-ops unless the state is
  ``RUNNING`` or ``STOPPING``;
* :meth:`DriveDetector.evaluateTimeouts` itself no-ops when ``_currentSession``
  is ``None``.

MEASURED in this tree before the fix: a detector carrying a live ``drive_id``
in ANY other shape -- session lost, or state reset to ``STOPPED`` by a
``stop()``/``start()`` cycle -- is unclosable.  Every existing path
early-returns, so the id stays claimable for the life of the process.  That is
"an end signal that never fires" (US-625 AC-5), and it is the shape that
produced drive 51's 24 orphan rows.

AC-2 fence honoured throughout: the fix must NOT discard rows.  Late rows are
still written; they simply resolve to a NULL drive_id instead of a finished
drive's.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive.types import DriveSession, DriveState
from src.pi.obdii.drive_id import (
    clearCurrentDriveId,
    getCurrentDriveId,
    getRawCurrentDriveId,
    isDriveIdStale,
    setCurrentDriveId,
)

# Drive 51's real leg (Spool measurement, US-625 AC-1).
_LEG_START = datetime(2026, 8, 28, 22, 9, 43)
_LAST_SAMPLE = datetime(2026, 8, 28, 22, 49, 48)
# The orphan rows arrived ~52 minutes after the last real sample.
_ORPHAN_ARRIVAL = _LAST_SAMPLE + timedelta(minutes=52)
# Seconds of idle the orphan rows represent.  The context's bound runs on
# time.monotonic() (US-620: this Pi's wall clock steps hours when NTP
# lands), so tests arm it that far in the PAST rather than injecting a
# future wall-clock instant.
_ORPHAN_IDLE_SECONDS = 52 * 60

_DRIVE_51 = 51


def _baseConfig(driveEndDurationSeconds: float = 60) -> dict[str, Any]:
    """DB-less config pinned to the production 60 s end-debounce."""
    return {
        'pi': {
            'analysis': {
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 10,
                'driveEndRpmThreshold': 0,
                'driveEndDurationSeconds': driveEndDurationSeconds,
                'triggerAfterDrive': False,
                'driveSummaryBackfillSeconds': 0,
            },
        },
    }


def _detectorHoldingDrive51(
    state: DriveState,
    *,
    withSession: bool,
    lastEcuReadingTime: datetime | None = _LAST_SAMPLE,
    idleSeconds: float = _ORPHAN_IDLE_SECONDS,
) -> DriveDetector:
    """A monitoring detector holding drive 51 in an unclosable shape.

    ``state`` / ``withSession`` select the shape.  The drive_id context is armed
    at ``_LAST_SAMPLE`` so the idle bound is measured from the leg's real end,
    exactly as ``_startDrive`` arms it in production.
    """
    detector = DriveDetector(config=_baseConfig())
    detector.start()
    detector._driveState = state
    detector._currentSession = (
        DriveSession(startTime=_LEG_START) if withSession else None
    )
    detector._lastEcuReadingTime = lastEcuReadingTime
    setCurrentDriveId(_DRIVE_51)
    detector._armDriveIdleBound(time.monotonic() - idleSeconds)
    return detector


class TestStaleOpenDriveClosesOnBoundedIdle:
    """The states US-388's two close paths cannot reach."""

    def teardown_method(self) -> None:
        clearCurrentDriveId()

    def test_liveDriveIdWithNoSession_closesOnIdleBound(self) -> None:
        """
        Given: a live drive_id but no _currentSession -- evaluateTimeouts
            early-returned here before US-625, so NO close path could fire.
        When: the orchestrator's off-tick pass runs 52 minutes after the last
            sample.
        Then: the drive_id is released, so nothing further is attributed to
            the finished drive.
        """
        detector = _detectorHoldingDrive51(
            DriveState.STOPPED, withSession=False,
        )

        detector.evaluateTimeouts(now=_ORPHAN_ARRIVAL)

        assert getRawCurrentDriveId() is None

    def test_sessionAliveButStateStopped_closesOnIdleBound(self) -> None:
        """
        Given: a session still held while the state reads STOPPED (the shape a
            stop()/start() cycle leaves behind).  _maybeCloseOnDeadline needs
            STOPPING and _checkEcuSilenceDriveEnd needs RUNNING/STOPPING, so
            both early-return forever.
        When: the off-tick pass runs past the idle bound.
        Then: the drive closes and the context is released.
        """
        detector = _detectorHoldingDrive51(
            DriveState.STOPPED, withSession=True,
        )

        detector.evaluateTimeouts(now=_ORPHAN_ARRIVAL)

        assert detector._currentSession is None
        assert getRawCurrentDriveId() is None

    def test_staleCloseFiresEvenWhenEcuTimerWasNeverSeeded(self) -> None:
        """
        Given: a live drive_id whose _lastEcuReadingTime is None -- the
            ECU-silence path explicitly no-ops on that, by design (US-229).
        When: the off-tick pass runs past the idle bound.
        Then: the drive still closes.  The bounded-idle close must not depend
            on the very bookkeeping that can go missing.
        """
        detector = _detectorHoldingDrive51(
            DriveState.STOPPED, withSession=True, lastEcuReadingTime=None,
        )

        detector.evaluateTimeouts(now=_ORPHAN_ARRIVAL)

        assert getRawCurrentDriveId() is None

    def test_insideTheIdleBound_theDriveIsLeftAlone(self) -> None:
        """
        Given: the same stale-open shape, only 59 s after the last sample.
        When: the off-tick pass runs.
        Then: NOTHING is closed.  The bound is an idle bound, not a dropout
            bound -- US-388 constraint C-gamma, which this must not weaken.
        """
        detector = _detectorHoldingDrive51(
            DriveState.STOPPED, withSession=True, idleSeconds=59,
        )

        detector.evaluateTimeouts(now=_LAST_SAMPLE + timedelta(seconds=59))

        assert getRawCurrentDriveId() == _DRIVE_51
        assert detector._currentSession is not None


class TestDriveFiftyOneReplay:
    """VC-1: replay the drive-51 shape -- healthy leg, long gap, late rows."""

    def teardown_method(self) -> None:
        clearCurrentDriveId()

    def test_lateRowsAreNotAttributedToTheFinishedDrive(self) -> None:
        """
        Given: drive 51's healthy leg has ended and the process-wide context
            still holds 51 in an unclosable shape.
        When: the off-tick pass runs, then the 24 orphan rows are written.
        Then: they resolve to NULL, not to 51 -- the late rows are NOT
            attributed to the finished drive (US-625 VC-1).
        """
        detector = _detectorHoldingDrive51(
            DriveState.STOPPED, withSession=True,
        )

        detector.evaluateTimeouts(now=_ORPHAN_ARRIVAL)
        attributions = [getCurrentDriveId() for _ in range(24)]

        assert attributions == [None] * 24

    def test_lateRowsAreNullEvenIfTheCloseNeverRuns(self) -> None:
        """
        Given: the same stale-open drive, but the orchestrator loop is starved
            so evaluateTimeouts NEVER runs -- the condition that let drive 51
            keep claiming rows for 52 minutes in the first place.
        When: the orphan rows are written anyway.
        Then: they STILL resolve to NULL.  This is the load-bearing half: the
            close runs on a loop that can stall, but writes do not, so
            attribution has to be safe by construction rather than by the
            close being timely.
        """
        _detectorHoldingDrive51(DriveState.STOPPED, withSession=True)

        assert getCurrentDriveId() is None
        # ...and the row is still writable -- AC-2: mis-attribution is the
        # defect, data loss would be a worse one.
        assert getRawCurrentDriveId() == _DRIVE_51

    def test_theHealthyLegItselfIsNeverChopped(self) -> None:
        """
        Given: drive 51 mid-leg, samples arriving at 438 rows/min.
        When: rows are attributed 40 minutes into the drive.
        Then: every one carries 51.  A 40-minute leg must survive a 60 s IDLE
            bound -- the bound measures silence, never elapsed drive time.
        """
        detector = _detectorHoldingDrive51(
            DriveState.RUNNING, withSession=True, idleSeconds=0,
        )

        cursor = time.monotonic()
        attributions = []
        for _ in range(40):
            cursor += 60
            detector._noteDriveActivity(cursor)
            attributions.append(getCurrentDriveId(nowMono=cursor))

        assert attributions == [_DRIVE_51] * 40


class TestDetectorCustodyOfTheContext:
    """Every exit from an active drive must release the drive_id."""

    def teardown_method(self) -> None:
        clearCurrentDriveId()

    def test_stopWhileStopping_closesTheDrive(self) -> None:
        """
        Given: a detector in STOPPING -- the state engine-off leaves behind,
            and therefore the state a shutdown almost always finds.
        When: the detector is stopped.
        Then: the drive is closed.  stop() previously closed only a RUNNING
            drive, so the overwhelmingly common shutdown shape left the drive
            open with no drive_end row ever written.
        """
        detector = _detectorHoldingDrive51(
            DriveState.STOPPING, withSession=True,
        )
        detector._belowThresholdSince = _LAST_SAMPLE

        detector.stop()

        assert detector._currentSession is None
        assert getRawCurrentDriveId() is None

    def test_stopWhileRunning_stillClosesTheDrive(self) -> None:
        """
        Given: a RUNNING drive.
        When: the detector is stopped.
        Then: it closes -- the pre-existing behaviour is preserved exactly
            (US-625 VC-3: no regression).
        """
        detector = _detectorHoldingDrive51(
            DriveState.RUNNING, withSession=True,
        )

        detector.stop()

        assert detector._currentSession is None
        assert getRawCurrentDriveId() is None

    def test_stopWithOrphanedContext_releasesTheDriveId(self) -> None:
        """
        Given: a live drive_id with no session at all.
        When: the detector stops.
        Then: the id is released.  stop() is the LAST moment a close can ever
            fire -- afterwards the detector is IDLE and evaluateTimeouts
            early-returns forever, so anything left live here is leaked for
            the remaining life of the process.
        """
        detector = _detectorHoldingDrive51(
            DriveState.STOPPED, withSession=False,
        )

        detector.stop()

        assert getRawCurrentDriveId() is None

    def test_resetReleasesTheDriveId(self) -> None:
        """
        Given: a detector holding a live drive_id.
        When: reset() returns it to its initial state.
        Then: the context is released too.  reset() cleared _currentSession
            but not the process-wide id, leaving an id no code path could
            ever close.
        """
        detector = _detectorHoldingDrive51(
            DriveState.RUNNING, withSession=True,
        )

        detector.reset()

        assert getRawCurrentDriveId() is None


class TestUs388CloseGuaranteeStillHolds:
    """VC-3: the existing close guarantees must survive this change."""

    def teardown_method(self) -> None:
        clearCurrentDriveId()

    def test_stoppingPastDeadline_stillClosesOffTick(self) -> None:
        """
        Given: US-388's canonical shape -- STOPPING, debounce armed, readings
            stopped.
        When: evaluateTimeouts runs 61 s later.
        Then: it closes via the RPM-debounce deadline, as US-388 pinned.
        """
        detector = DriveDetector(config=_baseConfig())
        detector.start()
        detector._driveState = DriveState.STOPPING
        detector._currentSession = DriveSession(startTime=_LEG_START)
        detector._belowThresholdSince = _LAST_SAMPLE
        detector._lastEcuReadingTime = None

        detector.evaluateTimeouts(now=_LAST_SAMPLE + timedelta(seconds=61))

        assert detector._driveState == DriveState.STOPPED
        assert detector._currentSession is None

    def test_stoppingBeforeDeadline_staysOpen(self) -> None:
        """
        Given: a STOPPING drive 30 s into its 60 s debounce.
        When: evaluateTimeouts runs.
        Then: it stays open -- C-gamma deadline-anchoring is intact and the
            new idle bound has not made the close trigger-happy.
        """
        detector = DriveDetector(config=_baseConfig())
        detector.start()
        detector._driveState = DriveState.STOPPING
        detector._currentSession = DriveSession(startTime=_LEG_START)
        detector._belowThresholdSince = _LAST_SAMPLE
        detector._lastEcuReadingTime = None

        detector.evaluateTimeouts(now=_LAST_SAMPLE + timedelta(seconds=30))

        assert detector._driveState == DriveState.STOPPING
        assert detector._currentSession is not None

    def test_noDriveAtAll_isANoOp(self) -> None:
        """
        Given: a detector with no drive and no context.
        When: the off-tick pass runs.
        Then: nothing happens and nothing is fabricated.
        """
        detector = DriveDetector(config=_baseConfig())
        detector.start()

        detector.evaluateTimeouts(now=_ORPHAN_ARRIVAL)

        assert getRawCurrentDriveId() is None
        assert detector._currentSession is None


class TestOnlyEcuDataCountsAsActivity:
    """The idle window tracks ECU data, never mere adapter liveness."""

    def teardown_method(self) -> None:
        clearCurrentDriveId()

    @staticmethod
    def _liveDriveOneTickFromStale() -> DriveDetector:
        """A RUNNING drive armed 59 s ago, with the ECU timer deliberately
        FRESH so the US-229 silence close cannot fire and mask the result.
        Anything that changes here is the idle window, nothing else.
        """
        return _detectorHoldingDrive51(
            DriveState.RUNNING,
            withSession=True,
            idleSeconds=59,
            lastEcuReadingTime=datetime.now(),
        )

    def test_ecuReadingRefreshesTheIdleWindow(self) -> None:
        """
        Given: a RUNNING drive whose idle window expires in 1 s.
        When: an ECU-sourced reading (RPM) arrives.
        Then: 2 s later it is still NOT stale -- the window was refreshed.
            This is the live half of the rule and the control for the test
            below: both start identically and differ only in the parameter.
        """
        detector = self._liveDriveOneTickFromStale()

        detector.processValue('RPM', 2500)

        assert isDriveIdStale(nowMono=time.monotonic() + 2) is False
        assert getCurrentDriveId() == _DRIVE_51

    def test_adapterHeartbeatDoesNotRefreshTheIdleWindow(self) -> None:
        """
        Given: the SAME drive, 1 s from a stale window.
        When: the adapter-level BATTERY_V heartbeat arrives instead of an ECU
            reading.
        Then: 2 s later it IS stale -- the window was not extended.  BATTERY_V
            comes from the ELM adapter via ELM_VOLTAGE, not the ECU, and keeps
            ticking long past engine-off (US-229).  If it counted as drive
            activity it would hold a finished drive open for as long as the Pi
            had power -- exactly the defect this story exists to end.
        """
        detector = self._liveDriveOneTickFromStale()

        detector.processValue('BATTERY_V', 12.4)

        assert isDriveIdStale(nowMono=time.monotonic() + 2) is True


class TestStartDriveActuallyArmsTheBound:
    """The wiring guard: without this the whole fix is inert in production."""

    def teardown_method(self) -> None:
        clearCurrentDriveId()

    def test_startDriveArmsTheIdleBoundOnTheLiveContext(self) -> None:
        """
        Given: a detector about to open a drive.
        When: _startDrive runs.
        Then: the live context is ARMED -- stale past driveEndDurationSeconds
            and fresh before it.

        This is the load-bearing wiring assertion.  Every other test in this
        file arms the bound by hand, so all of them stay green if _startDrive
        silently stops arming -- and the fix would then be perfectly inert on
        the car while the suite reported success.  A mutation removing the
        arming call was MISSED until this test existed.
        """
        detector = DriveDetector(config=_baseConfig())
        detector.start()
        # No database attached, so _openDriveId leaves the pre-set id in place;
        # the arming call under test is what must still fire.
        setCurrentDriveId(_DRIVE_51)

        detector._startDrive(datetime.now())
        anchor = time.monotonic()

        assert getRawCurrentDriveId() == _DRIVE_51
        assert isDriveIdStale(nowMono=anchor + 59) is False
        assert isDriveIdStale(nowMono=anchor + 61) is True

    def test_startDriveArmsWithTheConfiguredBoundNotAConstant(self) -> None:
        """
        Given: a detector configured with a 90 s end-debounce.
        When: _startDrive arms the context.
        Then: the armed bound is 90 s, not the 60 s default -- the arming must
            read config, not a hardcoded number (Rule 2 again, at the wiring
            level rather than the value level).
        """
        detector = DriveDetector(config=_baseConfig(driveEndDurationSeconds=90))
        detector.start()
        setCurrentDriveId(_DRIVE_51)

        detector._startDrive(datetime.now())
        anchor = time.monotonic()

        assert isDriveIdStale(nowMono=anchor + 61) is False
        assert isDriveIdStale(nowMono=anchor + 91) is True


class TestIdleBoundIsGrounded:
    """Rule 2: the bound is an existing measured value, not a new invention."""

    def teardown_method(self) -> None:
        clearCurrentDriveId()

    def test_boundIsTheConfiguredDriveEndDuration(self) -> None:
        """
        Given: a detector configured with a non-default 90 s end-debounce.
        When: a drive is armed.
        Then: the idle bound follows driveEndDurationSeconds -- US-625
            introduces NO new tunable.  The value that already decides "this
            drive is over" is the same one that decides "stop attributing to
            it", so the two can never disagree.
        """
        detector = DriveDetector(config=_baseConfig(driveEndDurationSeconds=90))
        detector.start()
        detector._currentSession = DriveSession(startTime=_LEG_START)
        setCurrentDriveId(_DRIVE_51)
        anchor = time.monotonic()
        detector._armDriveIdleBound(anchor)

        assert getCurrentDriveId(nowMono=anchor + 89) == 51
        assert getCurrentDriveId(nowMono=anchor + 91) is None
