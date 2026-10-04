################################################################################
# File Name: test_sync_retry_ceiling.py
# Purpose/Description: US-776-g -- once the shutdown decides to drain, it
#                      retries a transient sync failure with increasing waits
#                      until delivered or the backlog has not fallen for
#                      pi.homeNetwork.stallSec (ARCH-065: the absolute ceiling
#                      is retired). run() never raises.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-01    | Rex          | Initial -- US-776-g retry-with-backoff ceiling.
# 2026-10-01    | Rex          | US-776-d: outcomes are DELIVERED / AWAY /
#               |              | AT_HOME_SERVER_DOWN; success writes a record too.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T3: ceilingSec retired -> joinWaitSec +
#               |              | stallSec; the ceiling tests are now stall tests.
# ================================================================================
################################################################################
"""US-776-g / ARCH-065: at home the drain retries with backoff until delivered or stalled."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from src.common.config.validator import ConfigValidator
from src.pi.network.home_detector import HomeNetworkState
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask

_REPO_ROOT = Path(__file__).resolve().parents[4]
_STALL_SEC = 60.0
_JOIN_WAIT_SEC = 120.0


class _FakeClock:
    """Monotonic fake that only moves when something sleeps or works on it."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _ScriptedSync:
    """runSync fake: raises each scripted exception in turn, then succeeds.

    Records the fake-clock time each attempt STARTS, and optionally spends
    ``attemptSec`` of fake time per attempt (a slow forcePush).
    """

    def __init__(
        self,
        clock: _FakeClock,
        failures: list[BaseException] | None = None,
        *,
        alwaysFail: Callable[[], BaseException] | None = None,
        attemptSec: float = 0.0,
    ) -> None:
        self._clock = clock
        self._failures = list(failures or [])
        self._alwaysFail = alwaysFail
        self._attemptSec = attemptSec
        self.starts: list[float] = []

    def __call__(self) -> None:
        self.starts.append(self._clock.now)
        self._clock.now += self._attemptSec
        if self._alwaysFail is not None:
            raise self._alwaysFail()
        if self._failures:
            raise self._failures.pop(0)


def _task(
    runSync: Callable[[], None],
    clock: _FakeClock,
    records: list[object],
    *,
    stallSec: float = _STALL_SEC,
) -> SyncWithServerTask:
    return SyncWithServerTask(
        homeState=lambda: HomeNetworkState.AT_HOME_SERVER_DOWN,
        runSync=runSync,
        writeRecord=records.append,
        joinWaitSec=_JOIN_WAIT_SEC,
        stallSec=stallSec,
        sleepFn=clock.sleep,
        monotonic=clock.monotonic,
    )


class TestRetryUntilDelivered:

    def test_failsTwiceThenSucceeds_threeAttemptsIncreasingGapsOk(self) -> None:
        """
        Given: a runSync that fails twice (transient), then succeeds
        When: run() drains
        Then: three attempts, each gap longer than the last, outcome DELIVERED,
            one record (US-776-d)
        """
        clock = _FakeClock()
        sync = _ScriptedSync(clock, [RuntimeError("net"), RuntimeError("net")])
        records: list[object] = []

        result = _task(sync, clock, records).run()

        assert result == OutcomeKind.DELIVERED
        assert len(sync.starts) == 3
        gaps = [b - a for a, b in zip(sync.starts, sync.starts[1:], strict=False)]
        assert gaps[0] > 0
        assert gaps[1] > gaps[0]
        assert [r[0] for r in records] == [OutcomeKind.DELIVERED]

    def test_firstAttemptSucceeds_noWaitAtAll(self) -> None:
        clock = _FakeClock()
        sync = _ScriptedSync(clock)
        records: list[object] = []

        result = _task(sync, clock, records).run()

        assert result == OutcomeKind.DELIVERED
        assert sync.starts == [0.0]
        assert clock.sleeps == []

    def test_stopsAtFirstSuccess(self) -> None:
        clock = _FakeClock()
        sync = _ScriptedSync(clock, [RuntimeError("net")])
        records: list[object] = []

        _task(sync, clock, records).run()

        assert len(sync.starts) == 2


class TestStall:

    def test_alwaysFailing_endsOnceStallSecHasPassed(self) -> None:
        """
        Given: an always-failing runSync, a 60 s stall rule and a fake clock
        When: run() drains
        Then: it keeps retrying until 60 s without progress, then returns after
            recording the failure exactly once
        """
        clock = _FakeClock()
        sync = _ScriptedSync(clock, alwaysFail=lambda: RuntimeError("server down"))
        records: list[object] = []

        result = _task(sync, clock, records).run()

        assert result == OutcomeKind.AT_HOME_SERVER_DOWN
        assert len(sync.starts) >= 3
        assert _STALL_SEC <= clock.now < _STALL_SEC + 1.0
        assert len(records) == 1
        assert records[0][0] == OutcomeKind.AT_HOME_SERVER_DOWN

    def test_alwaysFailing_waitsStrictlyIncrease(self) -> None:
        clock = _FakeClock()
        sync = _ScriptedSync(clock, alwaysFail=lambda: RuntimeError("server down"))

        _task(sync, clock, []).run()

        assert clock.sleeps
        assert all(b > a for a, b in zip(clock.sleeps, clock.sleeps[1:], strict=False))

    def test_alwaysFailing_neverSleepsPastTheStallWindow(self) -> None:
        """No wait carries the clock beyond the stall window."""
        clock = _FakeClock()
        sync = _ScriptedSync(clock, alwaysFail=lambda: RuntimeError("server down"))

        _task(sync, clock, []).run()

        assert clock.now <= _STALL_SEC

    def test_slowAttempts_stallClockIncludesAttemptTime(self) -> None:
        """Each forcePush spends 25 s: the stall window counts real time, so the
        drain ends after the attempt that carries it past 60 s."""
        clock = _FakeClock()
        sync = _ScriptedSync(
            clock, alwaysFail=lambda: RuntimeError("timeout"), attemptSec=25.0
        )
        records: list[object] = []

        result = _task(sync, clock, records).run()

        assert result == OutcomeKind.AT_HOME_SERVER_DOWN
        assert len(sync.starts) == 3
        assert len(records) == 1

    @pytest.mark.parametrize("stallSec", [1.0, 5.0, 17.0, 60.0, 120.0])
    def test_anyStallSec_drainEndsAtIt(self, stallSec: float) -> None:
        clock = _FakeClock()
        sync = _ScriptedSync(clock, alwaysFail=lambda: RuntimeError("down"))

        _task(sync, clock, [], stallSec=stallSec).run()

        assert sync.starts[0] == 0.0
        assert clock.now == stallSec

    def test_stallClockStartsAtRun_notAtConstruction(self) -> None:
        clock = _FakeClock()
        sync = _ScriptedSync(clock, [RuntimeError("net")])
        task = _task(sync, clock, [])
        clock.now = 1000.0  # time passes between wiring and the power loss

        result = task.run()

        assert result == OutcomeKind.DELIVERED
        assert len(sync.starts) == 2


class TestNeverRaises:

    @pytest.mark.parametrize(
        "exc",
        [RuntimeError("net"), ConnectionError("refused"), TimeoutError("slow"), OSError("io")],
    )
    def test_transientFamily_retriedThenRecorded(self, exc: Exception) -> None:
        clock = _FakeClock()
        sync = _ScriptedSync(clock, alwaysFail=lambda: exc)
        records: list[object] = []

        result = _task(sync, clock, records).run()

        assert result in (OutcomeKind.AT_HOME_SERVER_DOWN, OutcomeKind.REAL_ERROR)
        assert len(records) == 1

    @pytest.mark.parametrize(
        "exc", [ValueError("corrupt db"), KeyError("x"), TypeError("bug"), Exception("any")]
    )
    def test_genuineFault_recordedOnceNoRetry(self, exc: Exception) -> None:
        clock = _FakeClock()
        sync = _ScriptedSync(clock, alwaysFail=lambda: exc)
        records: list[object] = []

        result = _task(sync, clock, records).run()

        assert result == OutcomeKind.REAL_ERROR
        assert len(sync.starts) == 1
        assert clock.sleeps == []
        assert records[0][0] == OutcomeKind.REAL_ERROR

    def test_genuineFaultAfterTransient_recordedNoFurtherRetry(self) -> None:
        clock = _FakeClock()
        sync = _ScriptedSync(clock, [RuntimeError("net"), ValueError("corrupt")])
        records: list[object] = []

        result = _task(sync, clock, records).run()

        assert result == OutcomeKind.REAL_ERROR
        assert len(sync.starts) == 2
        assert len(records) == 1

    def test_writeRecordRaising_runStillReturns(self) -> None:
        clock = _FakeClock()
        sync = _ScriptedSync(clock, alwaysFail=lambda: RuntimeError("down"))

        def brokenSink(_kd: object) -> None:
            raise OSError("disk full")

        task = SyncWithServerTask(
            homeState=lambda: HomeNetworkState.AT_HOME_SERVER_DOWN,
            runSync=sync,
            writeRecord=brokenSink,
            joinWaitSec=_JOIN_WAIT_SEC,
            stallSec=_STALL_SEC,
            sleepFn=clock.sleep,
            monotonic=clock.monotonic,
        )

        assert task.run() == OutcomeKind.AT_HOME_SERVER_DOWN

    def test_sleepRaising_runStillReturns(self) -> None:
        clock = _FakeClock()
        sync = _ScriptedSync(clock, alwaysFail=lambda: RuntimeError("down"))

        def brokenSleep(_s: float) -> None:
            raise OSError("interrupted")

        task = SyncWithServerTask(
            homeState=lambda: HomeNetworkState.AT_HOME_SERVER_DOWN,
            runSync=sync,
            writeRecord=lambda _kd: None,
            joinWaitSec=_JOIN_WAIT_SEC,
            stallSec=_STALL_SEC,
            sleepFn=brokenSleep,
            monotonic=clock.monotonic,
        )

        assert task.run() in (OutcomeKind.AT_HOME_SERVER_DOWN, OutcomeKind.REAL_ERROR)


class TestAwayUnchanged:

    def test_away_noAttemptNoWait(self) -> None:
        clock = _FakeClock()
        sync = _ScriptedSync(clock)
        task = SyncWithServerTask(
            homeState=lambda: HomeNetworkState.AWAY,
            runSync=sync,
            writeRecord=lambda _kd: None,
            joinWaitSec=_JOIN_WAIT_SEC,
            stallSec=_STALL_SEC,
            sleepFn=clock.sleep,
            monotonic=clock.monotonic,
        )

        assert task.run() == OutcomeKind.AWAY
        assert sync.starts == []
        assert clock.sleeps == []


class TestStallConfig:

    def test_shippedConfig_joinWait120_stall60(self) -> None:
        """CIO ruling 2026-10-02: join wait 120 s, stall 60 s, no ceiling."""
        config = json.loads((_REPO_ROOT / "config.json").read_text(encoding="utf-8"))

        assert config["pi"]["homeNetwork"]["joinWaitSec"] == 120
        assert config["pi"]["homeNetwork"]["stallSec"] == 60
        assert "shutdownSyncCeilingSec" not in config["pi"]["homeNetwork"]

    def test_shippedConfig_validatesWithStallKeys(self) -> None:
        config = json.loads((_REPO_ROOT / "config.json").read_text(encoding="utf-8"))

        result = ConfigValidator(requiredKeys=[]).validate(config)

        assert result["pi"]["homeNetwork"]["joinWaitSec"] == 120
        assert result["pi"]["homeNetwork"]["stallSec"] == 60
