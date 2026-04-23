################################################################################
# File Name: test_force_key_off_api.py
# Purpose/Description: DriveDetector.forceKeyOff(reason) tests -- external
#                      termination API used by the US-216 PowerDownOrchestrator
#                      IMMINENT stage.  US-225 / TD-034 close.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Unit tests for :meth:`DriveDetector.forceKeyOff`.

Covers the four invariants pinned in US-225:

1. **No-op safety** -- calling forceKeyOff with no active drive returns
   False without any side effects (no DB write, no callback).
2. **Active-drive termination** -- during RUNNING, forceKeyOff closes
   the session, writes a drive_end row with the reason, clears the
   process drive_id, and transitions to STOPPED.
3. **Reason traceability** -- the reason string lands in
   ``connection_log.error_message`` so analytics can distinguish a
   debounced drive-end (NULL) from a forced drive-end.
4. **Bypasses debounce** -- does not require the normal RPM=0 +
   drive_end_duration window to fire.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive.types import DriveState
from src.pi.obdii.drive_id import getCurrentDriveId, setCurrentDriveId


@pytest.fixture
def freshDb(tmp_path) -> Generator[ObdDatabase, None, None]:
    dbPath = tmp_path / "obd.db"
    db = ObdDatabase(str(dbPath), walMode=False)
    db.initialize()
    setCurrentDriveId(None)
    yield db
    setCurrentDriveId(None)


@pytest.fixture
def config() -> dict:
    return {
        'pi': {
            'analysis': {
                'driveStartRpmThreshold': 500,
                'driveStartDurationSeconds': 0.01,
                'driveEndRpmThreshold': 200,
                'driveEndDurationSeconds': 30,  # long debounce -- tests prove bypass
                'triggerAfterDrive': False,
            },
            'profiles': {
                'activeProfile': 'daily',
            },
        },
    }


@pytest.fixture
def detector(config, freshDb) -> DriveDetector:
    d = DriveDetector(config, statisticsEngine=None, database=freshDb)
    d.start()
    return d


# ================================================================================
# No-op safety
# ================================================================================


class TestNoOpSafety:
    def test_forceKeyOff_whenStopped_returnsFalse(self, detector) -> None:
        # Fresh detector -- STOPPED, no session.
        assert detector.getDriveState() == DriveState.STOPPED

        result = detector.forceKeyOff(reason='power_imminent')

        assert result is False
        assert detector.getCurrentSession() is None
        assert detector.getDriveState() == DriveState.STOPPED

    def test_forceKeyOff_writesNoRowWhenNoActiveDrive(
        self, detector, freshDb
    ) -> None:
        detector.forceKeyOff(reason='power_imminent')

        with freshDb.connect() as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM connection_log WHERE event_type = 'drive_end'"
            ).fetchone()
            assert rows[0] == 0

    def test_forceKeyOff_fromStartingState_noSession_isNoOp(
        self, detector
    ) -> None:
        # Put the detector in STARTING -- RPM above threshold but
        # debounce not met.
        detector.processValue('RPM', 1000)
        assert detector.getDriveState() == DriveState.STARTING
        # Session is None at this stage (created by _startDrive only).
        assert detector.getCurrentSession() is None

        result = detector.forceKeyOff(reason='power_imminent')

        assert result is False


# ================================================================================
# Active-drive termination
# ================================================================================


class TestActiveDriveTermination:
    def _driveUp(self, detector: DriveDetector) -> None:
        """Drive the detector into the RUNNING state with a live session."""
        # driveStartDurationSeconds = 0.01 -- two quick RPM ticks cross it.
        detector.processValue('RPM', 1000)
        import time as _t
        _t.sleep(0.05)
        detector.processValue('RPM', 1200)
        assert detector.getDriveState() == DriveState.RUNNING
        assert detector.getCurrentSession() is not None

    def test_forceKeyOff_onRunningDrive_returnsTrueAndClosesSession(
        self, detector
    ) -> None:
        self._driveUp(detector)

        result = detector.forceKeyOff(reason='power_imminent')

        assert result is True
        # After _endDrive, session is cleared + state is STOPPED.
        assert detector.getCurrentSession() is None
        assert detector.getDriveState() == DriveState.STOPPED

    def test_forceKeyOff_writesDriveEndRowWithReason(
        self, detector, freshDb
    ) -> None:
        self._driveUp(detector)
        mintedId = getCurrentDriveId()

        detector.forceKeyOff(reason='power_imminent')

        with freshDb.connect() as conn:
            row = conn.execute(
                "SELECT event_type, error_message, drive_id "
                "FROM connection_log "
                "WHERE event_type = 'drive_end'"
            ).fetchone()
            assert row is not None
            assert row[0] == 'drive_end'
            assert row[1] == 'power_imminent'
            assert row[2] == mintedId

    def test_forceKeyOff_clearsProcessDriveIdContext(
        self, detector
    ) -> None:
        self._driveUp(detector)
        assert getCurrentDriveId() is not None

        detector.forceKeyOff(reason='power_imminent')

        assert getCurrentDriveId() is None

    def test_forceKeyOff_bypassesDebounceWindow(
        self, detector
    ) -> None:
        # driveEndDurationSeconds = 30 -- normal path would require
        # 30s of RPM=0 before _endDrive fires.  forceKeyOff must NOT
        # wait.
        self._driveUp(detector)

        # Feed an RPM=0 reading but do NOT wait 30s.
        detector.processValue('RPM', 0)
        assert detector.getDriveState() == DriveState.STOPPING
        # Session still active at this point (debounce running).
        assert detector.getCurrentSession() is not None

        detector.forceKeyOff(reason='power_imminent')

        assert detector.getCurrentSession() is None
        assert detector.getDriveState() == DriveState.STOPPED

    def test_forceKeyOff_invokesOnDriveEndCallback(
        self, detector
    ) -> None:
        callback = MagicMock()
        detector.registerCallbacks(onDriveEnd=callback)

        self._driveUp(detector)
        detector.forceKeyOff(reason='power_imminent')

        callback.assert_called_once()
        # The callback receives the DriveSession.
        session = callback.call_args[0][0]
        assert session.endTime is not None

    def test_forceKeyOff_withDifferentReason_persistsIt(
        self, detector, freshDb
    ) -> None:
        self._driveUp(detector)

        detector.forceKeyOff(reason='operator_manual')

        with freshDb.connect() as conn:
            row = conn.execute(
                "SELECT error_message FROM connection_log "
                "WHERE event_type = 'drive_end'"
            ).fetchone()
            assert row[0] == 'operator_manual'


# ================================================================================
# Debounce-driven drive_end stays clean (regression guard)
# ================================================================================


class TestDebouncedDriveEndStillEmitsNullReason:
    """Regression guard: the normal (debounce) drive-end MUST NOT
    stamp a reason on connection_log.error_message -- that column is
    reserved for forced terminations so analytics can tell them
    apart.
    """

    def test_normalDriveEnd_writesNullErrorMessage(
        self, config, freshDb
    ) -> None:
        # Tight debounce so the test runs fast.
        config['pi']['analysis']['driveEndDurationSeconds'] = 0.01
        d = DriveDetector(config, statisticsEngine=None, database=freshDb)
        d.start()

        d.processValue('RPM', 1000)
        import time as _t
        _t.sleep(0.02)
        d.processValue('RPM', 1200)
        assert d.getDriveState() == DriveState.RUNNING

        d.processValue('RPM', 0)
        _t.sleep(0.02)
        d.processValue('RPM', 0)
        assert d.getDriveState() == DriveState.STOPPED

        with freshDb.connect() as conn:
            row = conn.execute(
                "SELECT error_message FROM connection_log "
                "WHERE event_type = 'drive_end'"
            ).fetchone()
            assert row[0] is None
