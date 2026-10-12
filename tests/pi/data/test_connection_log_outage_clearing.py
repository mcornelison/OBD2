################################################################################
# File Name: test_connection_log_outage_clearing.py
# Purpose/Description: F-077 / ARCH-047 -- the per-mac outage tracker's CLEARING
#                      set. Pins the three disjoint categories and the defect
#                      that connect_failure used to clear the tracker every cycle.
# Author: Atlas (ARCH-047)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""F-077: the outage tracker must be cleared only by a real state change."""

from __future__ import annotations

import pytest

from pi.data.connection_logger import (
    _OUTAGE_CLEARING_EVENTS,
    _REPEAT_SUPPRESSED_EVENTS,
    EVENT_BT_DISCONNECT,
    EVENT_CONNECT_ATTEMPT,
    EVENT_CONNECT_FAILURE,
    EVENT_CONNECT_SUCCESS,
    EVENT_DATA_CLEANUP,
    EVENT_DISCONNECT,
    EVENT_DRIVE_END,
    EVENT_DRIVE_START,
    EVENT_RECONNECT,
    EVENT_RECONNECT_SUCCESS,
    resetDedupStateForTests,
    shouldSuppressAsRepeat,
)

# --- F-077 / ARCH-047: the outage tracker's CLEARING set ----------------------
# Ruled by Atlas 2026-09-22. The defect: "state change" was defined as the
# COMPLEMENT of the suppressed set, so `connect_failure` -- a repeat symptom of
# an ONGOING outage -- cleared the tracker on every cycle. A parked car emits
# alternating connect_attempt/connect_failure, so suppression never fired and
# the table took ~500 rows/day, 24/7, engine off.


class TestOutageClearingSet:
    """Three categories, not two. The inversion alone would have been a bug."""

    def setup_method(self) -> None:
        resetDedupStateForTests()

    def _log(self, eventType: str, mac: str = "AA:BB:CC:DD:EE:FF") -> bool:
        """True when the event is SUPPRESSED (a repeat), False when it logs."""
        return shouldSuppressAsRepeat(mac, eventType)

    # -- category 1: CLEARING (a real state change) ---------------------------

    @pytest.mark.parametrize("event", sorted(_OUTAGE_CLEARING_EVENTS))
    def test_clearingEvent_logsAndResetsTheOutage(self, event: str) -> None:
        assert self._log(EVENT_CONNECT_ATTEMPT) is False   # first, logs
        assert self._log(EVENT_CONNECT_ATTEMPT) is True    # repeat, suppressed
        assert self._log(event) is False                   # state change, logs
        assert self._log(EVENT_CONNECT_ATTEMPT) is False   # NEW outage, logs again

    def test_theClearingSetIsExactlyTheRuledFive(self) -> None:
        """Pinned as a LITERAL: a set derived from the code under test cannot fail."""
        assert _OUTAGE_CLEARING_EVENTS == frozenset({
            EVENT_CONNECT_SUCCESS,
            EVENT_RECONNECT_SUCCESS,
            EVENT_DISCONNECT,
            EVENT_BT_DISCONNECT,
            EVENT_RECONNECT,
        })

    # -- category 2: SUPPRESSED (repeat symptoms of one outage) ---------------

    def test_connectFailure_doesNOTclear_THE_DEFECT(self) -> None:
        """🔴 THE F-077 DEFECT ITSELF.

        The live parked pattern alternates attempt/failure. While `connect_failure`
        cleared the tracker, the attempt logged EVERY cycle forever -- ~500 rows a
        day with the engine off, which is exactly what the feature forbids.
        """
        assert self._log(EVENT_CONNECT_ATTEMPT) is False   # first attempt logs
        assert self._log(EVENT_CONNECT_FAILURE) is False   # first failure logs
        assert self._log(EVENT_CONNECT_ATTEMPT) is True    # 🔴 was False before the fix
        assert self._log(EVENT_CONNECT_FAILURE) is True    # 🔴 was False before the fix

    def test_theFIRSTattemptAndFIRSTfailureOfEachOutageSTILLlog(self) -> None:
        """Suppression must not erase the signal it exists to compress."""
        assert self._log(EVENT_CONNECT_ATTEMPT) is False
        assert self._log(EVENT_CONNECT_FAILURE) is False
        for _ in range(50):
            self._log(EVENT_CONNECT_ATTEMPT)
            self._log(EVENT_CONNECT_FAILURE)
        self._log(EVENT_CONNECT_SUCCESS)                   # outage ends
        assert self._log(EVENT_CONNECT_ATTEMPT) is False   # next outage logs its first
        assert self._log(EVENT_CONNECT_FAILURE) is False

    def test_aLongParkedRun_collapsesToTwoRows(self) -> None:
        """The measured defect was ~500 rows/day. One outage is now 2 rows."""
        logged = 0
        for _ in range(500):
            logged += 0 if self._log(EVENT_CONNECT_ATTEMPT) else 1
            logged += 0 if self._log(EVENT_CONNECT_FAILURE) else 1
        assert logged == 2

    # -- category 3: ALWAYS-LOG (neither clearing nor suppressed) -------------

    @pytest.mark.parametrize("event", [EVENT_DRIVE_START, EVENT_DRIVE_END, EVENT_DATA_CLEANUP])
    def test_realEvents_ALWAYSlog_andNeverClear(self, event: str) -> None:
        """🔴 THE FLAW IN MY OWN RULING, caught while implementing it.

        A straight inversion -- "clearing := not suppressed" -> "clearing := in the
        allowlist" -- would have dropped these into the SUPPRESSED bucket, so a
        SECOND drive_start would have been silently swallowed. Losing a drive
        boundary to fix a chattiness defect is a far worse trade. They are their
        own category: log every time, touch the tracker never.
        """
        assert self._log(event) is False
        assert self._log(event) is False
        assert self._log(event) is False

    def test_anAlwaysLogEvent_doesNotEndAnOutage(self) -> None:
        """It logs, but it is not evidence the link recovered."""
        assert self._log(EVENT_CONNECT_ATTEMPT) is False
        assert self._log(EVENT_DATA_CLEANUP) is False
        assert self._log(EVENT_CONNECT_ATTEMPT) is True    # outage still open

    def test_theThreeCategoriesAreDISJOINT(self) -> None:
        assert not (_OUTAGE_CLEARING_EVENTS & _REPEAT_SUPPRESSED_EVENTS)

    def test_aNEWeventTypeDefaultsToALWAYSLOG_theSafeDirection(self) -> None:
        """design-patterns.md SS7: pin the DIRECTION, not the MEMBERSHIP.

        An unknown event must not silently become a state change (which would
        reopen this defect) nor silently become suppressed (which would lose it).
        Logging every time is the only default whose failure mode is NOISE.
        """
        novel = "some_future_event_nobody_has_written_yet"
        assert novel not in _OUTAGE_CLEARING_EVENTS
        assert novel not in _REPEAT_SUPPRESSED_EVENTS
        assert self._log(EVENT_CONNECT_ATTEMPT) is False
        assert self._log(novel) is False
        assert self._log(novel) is False                   # not suppressed
        assert self._log(EVENT_CONNECT_ATTEMPT) is True    # and it did not clear

    # -- per-mac isolation, unchanged -----------------------------------------

    def test_outagesAreTrackedPerMac(self) -> None:
        assert self._log(EVENT_CONNECT_ATTEMPT, "AA:11") is False
        assert self._log(EVENT_CONNECT_ATTEMPT, "BB:22") is False
        assert self._log(EVENT_CONNECT_ATTEMPT, "AA:11") is True
