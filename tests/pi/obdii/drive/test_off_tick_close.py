################################################################################
# File Name: test_off_tick_close.py
# Purpose/Description: US-388 (F-107 Root-2, Atlas C-alpha) -- unit tests for the
#                      DriveDetector OFF-TICK close path.  The drive-close state
#                      machine is otherwise tick-driven only (every close decision
#                      is evaluated inside processValue), so when readings STOP
#                      (engine off, data-acquisition loop quiesces) a STOPPING or
#                      RUNNING-dropout drive never closes and a later key-on is
#                      absorbed (drives 28/29).  evaluateTimeouts() lets an external
#                      periodic caller (the orchestrator main loop) fire the close
#                      when the deadline elapses even if NO further reading arrives.
# Author: Rex (Ralph agent)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Rex (US-388) | Initial -- off-tick close (evaluateTimeouts).
# ================================================================================
################################################################################

"""US-388 -- off-tick close path (:meth:`DriveDetector.evaluateTimeouts`).

Atlas's 2026-06-29 US-388 shape ruling, constraint C-alpha: the close decision
must NOT depend on a future ``processValue`` call.  A close fires when the
deadline elapses even if no further reading ever arrives.  The orchestrator's
main loop (``core.runLoop``) calls this on every pass (every
``_loopSleepInterval``) so the close is reliable when the data-acquisition loop
goes quiet.

C-beta: ``evaluateTimeouts`` acquires the EXISTING ``self._lock`` before
reading/mutating drive state (the re-entrancy guard against an in-flight tick).

C-gamma: deadline-anchored -- it closes only after ``driveEndDurationSeconds``
of genuine RPM-below (STOPPING) or ECU-silence has elapsed, never on a bare
connection-lost event.  A healthy RUNNING drive, or a STOPPING drive whose
deadline has not yet elapsed, is left untouched.

These tests pin the off-tick method in isolation, with no DB attached (the
DB-touching helpers ``_logDriveEvent``/``_openDriveId`` no-op without a
database, and ``triggerAfterDrive`` is False so no analysis is scheduled).  The
in-process reproducer ``test_drive2829_close_signal_reproducer.py`` is the
oracle for the tick-driven gap-resume half; the live IRL re-gate is the final
word on the off-tick close (Atlas oracle).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive.types import DriveSession, DriveState

_BASE_TS = datetime(2026, 6, 6, 8, 0, 0)


def _baseConfig(driveEndDurationSeconds: float = 60) -> dict[str, Any]:
    """Minimal DB-less config pinned to the production 60 s end-debounce."""
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


def _stoppingDetector() -> DriveDetector:
    """A detector parked in STOPPING with belowThresholdSince at ``_BASE_TS``.

    Models the drives-28/29 missed-close: RPM=0 was seen (STOPPING armed) and
    then the readings stopped before the 60 s debounce completed.
    ``_lastEcuReadingTime`` is deliberately None so the ECU-silence path cannot
    fire -- this isolates the RPM-debounce deadline close (``_maybeCloseOnDeadline``).
    """
    detector = DriveDetector(config=_baseConfig())
    detector.start()
    detector._driveState = DriveState.STOPPING
    detector._currentSession = DriveSession(startTime=_BASE_TS)
    detector._belowThresholdSince = _BASE_TS
    detector._lastEcuReadingTime = None
    return detector


class TestOffTickDeadlineClose:
    """evaluateTimeouts closes a stale STOPPING drive with no further reading."""

    def test_stoppingPastDeadline_closesWithoutFurtherTick(self) -> None:
        """
        Given: a drive in STOPPING whose RPM-below debounce armed at T0 and
            whose readings then stopped (no further processValue tick).
        When: the periodic loop calls evaluateTimeouts 61 s later.
        Then: the drive closes (STOPPED, session cleared) even though no
            reading arrived -- Atlas C-alpha off-tick close.
        """
        detector = _stoppingDetector()

        detector.evaluateTimeouts(now=_BASE_TS + timedelta(seconds=61))

        assert detector._driveState == DriveState.STOPPED
        assert detector._currentSession is None

    def test_stoppingBeforeDeadline_staysOpen(self) -> None:
        """
        Given: a STOPPING drive whose below-threshold timer armed at T0.
        When: evaluateTimeouts is called only 30 s later (< 60 s debounce).
        Then: the drive stays open (C-gamma: deadline-anchored, not
            dropout-anchored -- a brief quiet does not chop the drive).
        """
        detector = _stoppingDetector()

        detector.evaluateTimeouts(now=_BASE_TS + timedelta(seconds=30))

        assert detector._driveState == DriveState.STOPPING
        assert detector._currentSession is not None

    def test_runningHealthy_isNotClosed(self) -> None:
        """
        Given: a healthy RUNNING drive (RPM above end, recent ECU reading).
        When: evaluateTimeouts is called shortly after.
        Then: the drive is left RUNNING -- the off-tick path never closes a
            drive that has not entered the close debounce / gone ECU-silent.
        """
        detector = DriveDetector(config=_baseConfig())
        detector.start()
        detector._driveState = DriveState.RUNNING
        detector._currentSession = DriveSession(startTime=_BASE_TS)
        detector._belowThresholdSince = None
        detector._lastEcuReadingTime = _BASE_TS

        detector.evaluateTimeouts(now=_BASE_TS + timedelta(seconds=5))

        assert detector._driveState == DriveState.RUNNING
        assert detector._currentSession is not None

    def test_noActiveSession_isNoOp(self) -> None:
        """
        Given: a STOPPED detector with no active session.
        When: evaluateTimeouts is called.
        Then: it is a safe no-op (no exception, stays STOPPED).
        """
        detector = DriveDetector(config=_baseConfig())
        detector.start()

        detector.evaluateTimeouts(now=_BASE_TS + timedelta(seconds=3600))

        assert detector._driveState == DriveState.STOPPED
        assert detector._currentSession is None

    def test_ecuSilenceClosesOffTick_whenReadingsStop(self) -> None:
        """
        Given: a RUNNING drive whose last ECU reading was the only signal and
            then the OBD link went silent (no RPM=0 ever seen, so STOPPING was
            never entered).
        When: evaluateTimeouts is called past driveEndDurationSeconds with no
            further reading.
        Then: the ECU-silence path closes the drive off-tick too (the missed
            close is reachable without the data loop ticking).
        """
        detector = DriveDetector(config=_baseConfig())
        detector.start()
        detector._driveState = DriveState.RUNNING
        detector._currentSession = DriveSession(startTime=_BASE_TS)
        detector._belowThresholdSince = None
        detector._lastEcuReadingTime = _BASE_TS

        detector.evaluateTimeouts(now=_BASE_TS + timedelta(seconds=61))

        assert detector._driveState == DriveState.STOPPED
        assert detector._currentSession is None
