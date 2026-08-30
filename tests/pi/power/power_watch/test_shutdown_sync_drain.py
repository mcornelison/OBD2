################################################################################
# File Name: test_shutdown_sync_drain.py
# Purpose/Description: US-621 -- guards for the BOUNDED pre-shutdown drain and
#                      for the pre-poweroff hook composition that carries the
#                      custody record alongside the US-526 drain close.
#
#                      The premise correction this story turns on: a shutdown
#                      drain DOES exist (SyncWithServerTask -> forcePush), but
#                      forcePush moves at most batchSize (500) rows PER TABLE
#                      PER CALL, so one call against a ~15,000-row backlog
#                      returned OK with ~14,500 rows still local. The drain now
#                      makes repeated passes under a measured bound, and the
#                      custody record states what remains either way.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-621) | Initial -- bounded drain + hook composition.
# ================================================================================
################################################################################
"""US-621 guards for the bounded pre-shutdown drain."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from src.pi.power.power_watch import __main__ as m
from src.pi.sync.backlog import SyncBacklog


@dataclass
class _FakeSummary:
    """Minimal PushSummary stand-in (only the fields _buildRunSync reads)."""

    rowsPushed: int = 0
    tablesFailed: int = 0
    disabled: bool = False


class _FakeSyncClient:
    """Records forcePush calls and replays a scripted sequence of summaries."""

    def __init__(self, summaries: list[_FakeSummary]) -> None:
        self._summaries = list(summaries)
        self.calls = 0

    def forcePush(self) -> _FakeSummary:
        self.calls += 1
        if self._summaries:
            return self._summaries.pop(0)
        return _FakeSummary(rowsPushed=0)


def _backlogOf(*counts: int):
    """A backlog reader replaying one count per call, holding the last."""
    remaining = list(counts)

    def _read() -> SyncBacklog:
        value = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return SyncBacklog(perTable={"realtime_data": value})

    return _read


# --------------------------------------------------------------------------- #
# The drain makes MORE THAN ONE pass -- the actual 2026-08-28 defect
# --------------------------------------------------------------------------- #


class TestTheDrainKeepsGoingWhileRowsRemain:
    """One forcePush is one batch per table, not a drained queue."""

    def test_runSync_repeatsWhileTheBacklogIsNonEmpty(self) -> None:
        """
        Given: a backlog needing three batches to clear
        When: the pre-shutdown drain runs with budget to spare
        Then: forcePush is called until the queue is actually empty

        This is the whole observed defect: forcePush moves at most batchSize
        rows PER TABLE PER CALL, so a single call against ~15,000 rows returned
        OK while ~14,500 stayed on the Pi.
        """
        # Arrange
        client = _FakeSyncClient(
            [
                _FakeSummary(rowsPushed=500),
                _FakeSummary(rowsPushed=500),
                _FakeSummary(rowsPushed=300),
            ]
        )
        runSync = m._buildRunSync(
            client,
            backlogReader=_backlogOf(800, 300, 0),
            budgetSec=100.0,
            monotonicFn=_clock(),
        )

        # Act
        runSync()

        # Assert
        assert client.calls == 3

    def test_runSync_stopsImmediatelyWhenTheQueueIsAlreadyEmpty(self) -> None:
        """
        Given: nothing outstanding after the first pass
        When: the drain runs
        Then: exactly one forcePush -- no speculative extra round trips
        """
        # Arrange
        client = _FakeSyncClient([_FakeSummary(rowsPushed=4)])
        runSync = m._buildRunSync(
            client,
            backlogReader=_backlogOf(0),
            budgetSec=100.0,
            monotonicFn=_clock(),
        )

        # Act
        runSync()

        # Assert
        assert client.calls == 1


class TestTheDrainIsBounded:
    """An unbounded drain would fight the power budget the sequencer exists for."""

    def test_runSync_stopsWhenTheRemainingBudgetCannotFitAnotherPass(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: a large backlog and passes that each consume most of the budget
        When: the drain runs
        Then: it stops rather than starting a pass that cannot finish in budget

        US-621 VC-3 + conditionalOutcome 1: the bound is derived from MEASURED
        pass duration against the shutdown path's own perTaskTimeoutSec, so no
        new tunable is invented and a slow link self-limits.
        """
        # Arrange -- each pass takes 8s against a 20s budget: pass 3 would not fit
        caplog.set_level(logging.DEBUG)
        client = _FakeSyncClient([_FakeSummary(rowsPushed=500)] * 10)
        runSync = m._buildRunSync(
            client,
            backlogReader=_backlogOf(9000),
            budgetSec=20.0,
            monotonicFn=_clock(step=8.0),
        )

        # Act
        runSync()

        # Assert -- bounded well short of the 18 passes the backlog would need
        assert client.calls == 2

    def test_runSync_alwaysMakesAtLeastOnePass(self) -> None:
        """
        Given: a budget already exhausted
        When: the drain runs
        Then: one forcePush still happens

        Today's behaviour is exactly one pass; the bound must never regress
        below that or a shutdown would stop syncing altogether.
        """
        # Arrange
        client = _FakeSyncClient([_FakeSummary(rowsPushed=10)])
        runSync = m._buildRunSync(
            client,
            backlogReader=_backlogOf(5000),
            budgetSec=0.0,
            monotonicFn=_clock(step=100.0),
        )

        # Act
        runSync()

        # Assert
        assert client.calls == 1

    def test_runSync_stopsWhenAPassMakesNoProgress(self) -> None:
        """
        Given: rows outstanding but a pass that moves none of them
        When: the drain runs
        Then: it stops instead of spinning until the bound

        A backlog that will not shrink (a quarantined or skipped table) must
        not burn the entire shutdown window re-attempting the same no-op.
        """
        # Arrange
        client = _FakeSyncClient(
            [_FakeSummary(rowsPushed=100), _FakeSummary(rowsPushed=0)]
        )
        runSync = m._buildRunSync(
            client,
            backlogReader=_backlogOf(700, 700),
            budgetSec=1000.0,
            monotonicFn=_clock(),
        )

        # Act
        runSync()

        # Assert
        assert client.calls == 2


class TestTheDrainKeepsItsExistingContract:
    """SyncWithServerTask's classification depends on these exact signals."""

    def test_runSync_tablesFailed_raisesRuntimeErrorForTheRetryPath(self) -> None:
        """
        Given: a transport failure after retries
        When: the drain runs
        Then: RuntimeError -- the transient class SyncWithServerTask retries

        The T6 wiring contract: RuntimeError-family means retry-eligible; any
        other exception is classified REAL_ERROR with no retry.
        """
        # Arrange
        client = _FakeSyncClient([_FakeSummary(tablesFailed=2)])
        runSync = m._buildRunSync(
            client,
            backlogReader=_backlogOf(10),
            budgetSec=100.0,
            monotonicFn=_clock(),
        )

        # Act / Assert
        with pytest.raises(RuntimeError):
            runSync()

    def test_runSync_disabledCompanion_isABenignNoOp(self) -> None:
        """
        Given: the companion service disabled by config
        When: the drain runs
        Then: it returns without raising and without further passes
        """
        # Arrange
        client = _FakeSyncClient([_FakeSummary(disabled=True)])
        runSync = m._buildRunSync(
            client,
            backlogReader=_backlogOf(999),
            budgetSec=100.0,
            monotonicFn=_clock(),
        )

        # Act
        runSync()

        # Assert
        assert client.calls == 1

    def test_runSync_unreadableBacklog_doesNotLoopForever(self) -> None:
        """
        Given: a backlog that cannot be read (UNKNOWN)
        When: the drain runs
        Then: it still terminates

        UNKNOWN is not "empty", so the loop must not treat it as a reason to
        continue indefinitely either.
        """
        # Arrange
        client = _FakeSyncClient([_FakeSummary(rowsPushed=0)])

        def _unknown() -> SyncBacklog:
            return SyncBacklog(perTable={}, unreadableTables=("realtime_data",))

        runSync = m._buildRunSync(
            client,
            backlogReader=_unknown,
            budgetSec=100.0,
            monotonicFn=_clock(),
        )

        # Act
        runSync()

        # Assert
        assert client.calls == 1


# --------------------------------------------------------------------------- #
# Hook composition: custody must not displace the US-526 drain close
# --------------------------------------------------------------------------- #


class TestPrePowerOffHookComposition:
    """Two facts must be recorded before poweroff, and neither may eat the other."""

    def test_composePrePowerOffHooks_runsEveryHookInOrder(self) -> None:
        """
        Given: the US-526 drain close and the US-621 custody record
        When: the composed hook fires
        Then: both run, in the order given
        """
        # Arrange
        calls: list[str] = []
        composed = m.composePrePowerOffHooks(
            lambda: calls.append("drain-close"),
            lambda: calls.append("custody"),
        )

        # Act
        composed()

        # Assert
        assert calls == ["drain-close", "custody"]

    def test_composePrePowerOffHooks_oneHookRaising_doesNotStopTheOthers(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: an earlier hook that raises
        When: the composed hook fires
        Then: the later hook STILL runs

        The sequencer guards prePowerOffFn as a single unit, so naive
        composition would let a failing drain close silently delete the custody
        record -- one shutdown bug quietly disabling another's fix.
        """
        # Arrange
        caplog.set_level(logging.DEBUG)
        calls: list[str] = []

        def _boom() -> None:
            raise RuntimeError("drain close failed")

        composed = m.composePrePowerOffHooks(
            _boom, lambda: calls.append("custody")
        )

        # Act
        composed()

        # Assert
        assert calls == ["custody"]

    def test_composePrePowerOffHooks_ignoresUnwiredHooks(self) -> None:
        """
        Given: an absent (None) hook, e.g. no pi.database.path configured
        When: the composed hook fires
        Then: the wired hooks still run and nothing raises
        """
        # Arrange
        calls: list[str] = []

        # Act
        m.composePrePowerOffHooks(None, lambda: calls.append("custody"))()

        # Assert
        assert calls == ["custody"]

    def test_composePrePowerOffHooks_allUnwired_returnsNone(self) -> None:
        """
        Given: no hooks at all
        When: composition runs
        Then: None, so the sequencer takes its exact legacy path
        """
        assert m.composePrePowerOffHooks(None, None) is None


def _clock(step: float = 0.0):
    """A monotonic stub advancing by ``step`` seconds on every read."""
    state = {"t": 0.0}

    def _now() -> float:
        value = state["t"]
        state["t"] += step
        return value

    return _now
