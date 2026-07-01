################################################################################
# File Name: test_clock_sync.py
# Purpose/Description: Unit tests for the post-reboot clock-drift honest
#                      instrument (US-419 / F-080).  Covers the pure
#                      classifier, the NTP-sync probe (injected runner), and
#                      the wired assessor -- proving a pre-NTP-sync boot
#                      timestamp is flagged clock_unsynced and never crashes.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-07-01    | Rex     | Initial -- US-419 clock-drift guard tests.
# ================================================================================
################################################################################
"""Unit tests for :mod:`src.pi.diagnostics.clock_sync` (US-419)."""

from src.pi.diagnostics.clock_sync import (
    CLOCK_QUALITY_CLOCK_UNSYNCED,
    CLOCK_QUALITY_FULL,
    CLOCK_SANITY_FLOOR_ISO,
    assessClockQuality,
    classifyClockQuality,
    isNtpSynchronized,
)

# A timestamp definitively before the project could exist (dead-RTC epoch reset).
_PRE_FLOOR_ISO = "1970-01-01T00:00:00Z"
# A plausible, post-floor "now".
_POST_FLOOR_ISO = "2026-07-01T12:00:00Z"


# ================================================================================
# classifyClockQuality -- pure honest-instrument classifier
# ================================================================================


class TestClassifyClockQuality:
    """The floor is the always-available signal; ntpSynced is a refinement."""

    def test_belowFloorTimestamp_flagsClockUnsynced(self) -> None:
        """
        Given: a boot timestamp before the sanity floor (dead-RTC reset)
        When: classified with no NTP signal
        Then: it is flagged clock_unsynced (never written as truth)
        """
        assert (
            classifyClockQuality(_PRE_FLOOR_ISO, ntpSynced=None)
            == CLOCK_QUALITY_CLOCK_UNSYNCED
        )

    def test_aboveFloorNtpSynced_isFull(self) -> None:
        """A post-floor timestamp with confirmed NTP sync is trustworthy."""
        assert (
            classifyClockQuality(_POST_FLOOR_ISO, ntpSynced=True)
            == CLOCK_QUALITY_FULL
        )

    def test_aboveFloorNtpNotSynced_flagsClockUnsynced(self) -> None:
        """NTP explicitly not-synced flags even a plausible-looking timestamp."""
        assert (
            classifyClockQuality(_POST_FLOOR_ISO, ntpSynced=False)
            == CLOCK_QUALITY_CLOCK_UNSYNCED
        )

    def test_aboveFloorNtpUndeterminable_defaultsFull(self) -> None:
        """
        Given: a post-floor timestamp and an undeterminable NTP state (None)
        When: classified
        Then: it is FULL -- an unreachable probe must NOT paint every row
              suspect (no false-positive flood on non-systemd / dev boxes)
        """
        assert (
            classifyClockQuality(_POST_FLOOR_ISO, ntpSynced=None)
            == CLOCK_QUALITY_FULL
        )

    def test_belowFloorEvenWhenNtpSynced_flagsClockUnsynced(self) -> None:
        """The floor wins: a 'synced' clock reading 1970 is still definitively bad."""
        assert (
            classifyClockQuality(_PRE_FLOOR_ISO, ntpSynced=True)
            == CLOCK_QUALITY_CLOCK_UNSYNCED
        )

    def test_nonCanonicalGarbage_doesNotCrash(self) -> None:
        """A malformed timestamp must not raise (honest instrument, no crash)."""
        # Neither None nor a garbage string may crash the writer path.
        assert classifyClockQuality("not-a-timestamp", ntpSynced=None) in (
            CLOCK_QUALITY_FULL,
            CLOCK_QUALITY_CLOCK_UNSYNCED,
        )
        assert classifyClockQuality(None, ntpSynced=None) in (  # type: ignore[arg-type]
            CLOCK_QUALITY_FULL,
            CLOCK_QUALITY_CLOCK_UNSYNCED,
        )

    def test_defaultNtpSyncedIsNone(self) -> None:
        """Called with only a timestamp (the power_log floor-only seam)."""
        assert classifyClockQuality(_POST_FLOOR_ISO) == CLOCK_QUALITY_FULL
        assert (
            classifyClockQuality(_PRE_FLOOR_ISO) == CLOCK_QUALITY_CLOCK_UNSYNCED
        )

    def test_sanityFloorConstantIsCanonicalIso(self) -> None:
        """The floor is a canonical ISO string so the compare is lexical."""
        assert CLOCK_SANITY_FLOOR_ISO.endswith("Z")
        assert "T" in CLOCK_SANITY_FLOOR_ISO


# ================================================================================
# isNtpSynchronized -- injected-runner probe
# ================================================================================


class TestIsNtpSynchronized:
    """Best-effort timedatectl probe -- True / False / None, never raises."""

    def test_runnerYes_returnsTrue(self) -> None:
        assert isNtpSynchronized(runner=lambda: "yes\n") is True

    def test_runnerNo_returnsFalse(self) -> None:
        assert isNtpSynchronized(runner=lambda: "no\n") is False

    def test_runnerMissingBinary_returnsNone(self) -> None:
        """timedatectl absent (non-systemd / dev box) -> undeterminable."""

        def _boom() -> str:
            raise FileNotFoundError("timedatectl")

        assert isNtpSynchronized(runner=_boom) is None

    def test_runnerUnexpectedOutput_returnsNone(self) -> None:
        assert isNtpSynchronized(runner=lambda: "banana") is None

    def test_runnerEmpty_returnsNone(self) -> None:
        assert isNtpSynchronized(runner=lambda: "") is None


# ================================================================================
# assessClockQuality -- wired SSOT entry (probe + classify)
# ================================================================================


class TestAssessClockQuality:
    """The production single-call entry point used by the boot-log writer."""

    def test_aboveFloorNtpSynced_isFull(self) -> None:
        assert (
            assessClockQuality(_POST_FLOOR_ISO, runner=lambda: "yes")
            == CLOCK_QUALITY_FULL
        )

    def test_aboveFloorNtpNotSynced_flagsClockUnsynced(self) -> None:
        assert (
            assessClockQuality(_POST_FLOOR_ISO, runner=lambda: "no")
            == CLOCK_QUALITY_CLOCK_UNSYNCED
        )

    def test_belowFloorNtpSynced_floorWins(self) -> None:
        assert (
            assessClockQuality(_PRE_FLOOR_ISO, runner=lambda: "yes")
            == CLOCK_QUALITY_CLOCK_UNSYNCED
        )

    def test_probeUnavailableAboveFloor_isFull(self) -> None:
        """Non-systemd box (probe -> None) + sane clock -> FULL, no crash."""

        def _boom() -> str:
            raise FileNotFoundError("timedatectl")

        assert (
            assessClockQuality(_POST_FLOOR_ISO, runner=_boom)
            == CLOCK_QUALITY_FULL
        )
