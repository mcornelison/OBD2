################################################################################
# File Name: test_drive_id_idle_bound.py
# Purpose/Description: US-625 (A-9 Root 2) -- the drive_id context must not hand
#                      out a STALE drive_id.  Drive 51 (Spool, 2026-08-28) ran a
#                      healthy leg 22:09:43-22:49:48 UTC at 438 rows/min, then
#                      took 24 more rows ~52 minutes later STILL stamped
#                      drive_id=51.  The process-wide context had no idle bound,
#                      so a drive that was over kept claiming whatever arrived
#                      next.  These tests pin the bounded-idle NULL-latch on the
#                      context itself: past the bound the id resolves to NULL
#                      (non-attribution), never to the stale id (mis-attribution).
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-625) | Initial -- bounded-idle NULL-latch on the
#                               process-wide current-drive context.
# ================================================================================
################################################################################

"""US-625 -- bounded-idle NULL-latch on the current-drive context.

The A-9 Root 2 defect is MIS-ATTRIBUTION, not data loss (US-625 AC-2): late rows
must still be written, they must simply stop carrying a finished drive's id.  So
the latch resolves a stale context to ``None`` -- the same "no active drive"
sentinel a pre-crank row already uses -- and never discards anything.

Ownership rule pinned here: :func:`getCurrentDriveId` is the ATTRIBUTION view
(latched, used by writers) and :func:`getRawCurrentDriveId` is the OWNER view
(unlatched, used by the DriveDetector for its own bookkeeping).  The detector
must keep seeing the raw id or its own ``drive_end`` row -- which fires exactly
at the idle bound -- would be stamped NULL and break the drive_start/drive_end
pair-up.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from src.pi.obdii.drive_id import (
    armDriveIdleBound,
    clearCurrentDriveId,
    getCurrentDriveId,
    getRawCurrentDriveId,
    isDriveIdStale,
    noteDriveActivity,
    setCurrentDriveId,
)

# Monotonic anchor for drive 51's last real sample (22:49:48 UTC, Spool
# measurement, US-625 AC-1).  The bound is monotonic, never wall-clock:
# US-620 measured this Pi stepping its clock hours forward when NTP lands,
# and a wall-clock delta would read that step as hours of sample silence.
_T0 = 10_000.0

# The production ECU-silence bound; US-625 reuses it rather than inventing a
# second idle number (see DEFAULT_DRIVE_END_DURATION_SECONDS).
_BOUND = 60.0


@pytest.fixture(autouse=True)
def resetContext() -> Generator[None, None, None]:
    """The context is process-wide module state; isolate every test."""
    clearCurrentDriveId()
    yield
    clearCurrentDriveId()


class TestUnarmedContextIsUnchanged:
    """Back-compat: a context nobody armed behaves exactly as it did pre-US-625."""

    def test_setAndGetRoundTrip_withNoBound_returnsId(self) -> None:
        """
        Given: a drive_id set with no idle bound armed (the legacy call shape).
        When: the id is read back an arbitrarily long time later.
        Then: it is returned unchanged -- arming is opt-in, so no existing
            caller changes behaviour.
        """
        setCurrentDriveId(51)

        assert getCurrentDriveId(nowMono=_T0 + 9 * 3600) == 51

    def test_defaultsToNone(self) -> None:
        """
        Given: a freshly cleared context.
        When: the id is read.
        Then: None -- the latch never fabricates an attribution.
        """
        assert getCurrentDriveId() is None
        assert getRawCurrentDriveId() is None

    def test_unarmedContextIsNeverStale(self) -> None:
        """
        Given: an unarmed context holding a live id.
        When: staleness is evaluated far past any plausible bound.
        Then: not stale -- absence of a bound must not be read as "expired".
        """
        setCurrentDriveId(51)

        assert isDriveIdStale(nowMono=_T0 + 86_400) is False


class TestArmedContextLatchesOnIdle:
    """The drive-51 shape: inside the bound attribute, past it latch to NULL."""

    def test_insideBound_stillAttributes(self) -> None:
        """
        Given: drive 51 armed with the 60 s idle bound at its last sample.
        When: a row is written 59 s later (a normal inter-sample gap).
        Then: it still carries drive_id=51 -- the latch must not chop a live
            drive (US-625 AC-2: this is mis-attribution, not over-eagerness).
        """
        setCurrentDriveId(51)
        armDriveIdleBound(_BOUND, nowMono=_T0)

        assert getCurrentDriveId(nowMono=_T0 + 59) == 51

    def test_pastBound_resolvesToNullNotTheStaleId(self) -> None:
        """
        Given: drive 51 armed at its last real sample, 22:49:48.
        When: the 24 orphan rows arrive ~52 minutes later.
        Then: they resolve to NULL, NOT to 51 -- the exact mis-attribution
            US-625 exists to end.
        """
        setCurrentDriveId(51)
        armDriveIdleBound(_BOUND, nowMono=_T0)

        assert getCurrentDriveId(nowMono=_T0 + 52 * 60) is None

    def test_atExactlyTheBound_isStale(self) -> None:
        """
        Given: a context armed with a 60 s bound.
        When: exactly 60 s have elapsed.
        Then: stale -- the SAME >= comparison the detector's ECU-silence close
            uses, so "the drive is over" and "stop attributing" can never
            disagree about the same instant.
        """
        setCurrentDriveId(51)
        armDriveIdleBound(_BOUND, nowMono=_T0)

        assert isDriveIdStale(nowMono=_T0 + 60) is True

    def test_rawViewStillReportsTheStaleId(self) -> None:
        """
        Given: a context that has gone stale.
        When: the OWNER view is read.
        Then: it still reports 51 -- the detector needs the truth to close the
            drive and to stamp its own drive_end row; only writers are latched.
        """
        setCurrentDriveId(51)
        armDriveIdleBound(_BOUND, nowMono=_T0)

        assert getRawCurrentDriveId() == 51
        assert getCurrentDriveId(nowMono=_T0 + 52 * 60) is None

    def test_activityRefreshKeepsALiveDriveAttributed(self) -> None:
        """
        Given: a drive armed at T0 whose samples keep arriving.
        When: activity is noted at T0+50 s and a row is written at T0+100 s.
        Then: still attributed -- the bound measures IDLE, not drive length.
            A two-hour drive must never be chopped at 60 s.
        """
        setCurrentDriveId(51)
        armDriveIdleBound(_BOUND, nowMono=_T0)

        noteDriveActivity(nowMono=_T0 + 50)

        assert getCurrentDriveId(nowMono=_T0 + 100) == 51

    def test_activityOnAClearedContextDoesNotResurrectAnId(self) -> None:
        """
        Given: a closed drive (context cleared).
        When: a late writer notes activity anyway.
        Then: the id stays None -- noting activity must never MINT an
            attribution, only extend a live one.
        """
        setCurrentDriveId(51)
        armDriveIdleBound(_BOUND, nowMono=_T0)
        clearCurrentDriveId()

        noteDriveActivity(nowMono=_T0 + 1)

        assert getCurrentDriveId(nowMono=_T0 + 2) is None
        assert getRawCurrentDriveId() is None


class TestArmingIsScopedToOneDrive:
    """A new drive must not inherit the previous drive's bound or activity."""

    def test_settingANewIdDisarmsThePriorBound(self) -> None:
        """
        Given: drive 51 armed and long since stale.
        When: drive 52 is set without arming.
        Then: 52 is attributed -- a stale predecessor must never make a fresh
            drive read as expired the instant it starts.
        """
        setCurrentDriveId(51)
        armDriveIdleBound(_BOUND, nowMono=_T0)

        setCurrentDriveId(52)

        assert getCurrentDriveId(nowMono=_T0 + 52 * 60) == 52

    def test_armingWithNoLiveIdIsANoOp(self) -> None:
        """
        Given: no live drive.
        When: a bound is armed anyway.
        Then: nothing is attributed -- arming cannot conjure a drive_id.
        """
        armDriveIdleBound(_BOUND, nowMono=_T0)

        assert getCurrentDriveId(nowMono=_T0) is None

    def test_clearDisarmsTheBound(self) -> None:
        """
        Given: an armed, stale context.
        When: it is cleared and a new id is set with no bound.
        Then: the new id is attributed -- clear resets bound AND activity, so
            no residue of the old drive survives into the next one.
        """
        setCurrentDriveId(51)
        armDriveIdleBound(_BOUND, nowMono=_T0)
        clearCurrentDriveId()

        setCurrentDriveId(52)

        assert isDriveIdStale(nowMono=_T0 + 52 * 60) is False
        assert getCurrentDriveId(nowMono=_T0 + 52 * 60) == 52
