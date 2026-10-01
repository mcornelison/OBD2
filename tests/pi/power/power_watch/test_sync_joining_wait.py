################################################################################
# File Name: test_sync_joining_wait.py
# Purpose/Description: US-776-e -- at home with the WiFi rejoin still pending
#                      (AT_HOME_JOINING), the shutdown sync polls for the
#                      association inside pi.homeNetwork.shutdownSyncCeilingSec,
#                      then drains. JOINING wait + drain share that one
#                      ceiling; a rejoin that outlasts it records
#                      AT_HOME_JOINING_TIMEOUT. Away, nothing waits.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-01    | Rex          | Initial -- US-776-e JOINING wait.
# ================================================================================
################################################################################
"""US-776-e: at home, the shutdown waits for the WiFi rejoin within the ceiling."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from src.pi.network.home_detector import HomeNetworkDetector, HomeNetworkState
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.tasks.sync_with_server import (
    JOIN_POLL_SEC,
    SyncOutcomeRecord,
    SyncWithServerTask,
)

_CIO_CEILING_SEC = 60.0
_HOME_SSID = "DeathStarWiFi"
_JOINED_AT_SEC = 20.0


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


class _Sync:
    """runSync fake recording when each attempt starts; optionally always fails."""

    def __init__(self, clock: _FakeClock, *, fail: bool = False) -> None:
        self._clock = clock
        self._fail = fail
        self.starts: list[float] = []

    def __call__(self) -> None:
        self.starts.append(self._clock.now)
        if self._fail:
            raise RuntimeError("connection refused")


def _task(
    homeState: Callable[[], HomeNetworkState],
    sync: _Sync,
    clock: _FakeClock,
    records: list[SyncOutcomeRecord],
    *,
    backlog: int | None = 412,
) -> SyncWithServerTask:
    return SyncWithServerTask(
        homeState=homeState,
        runSync=sync,
        writeRecord=records.append,
        ceilingSec=_CIO_CEILING_SEC,
        sleepFn=clock.sleep,
        monotonic=clock.monotonic,
        backlogReader=lambda: backlog,
    )


def _joiningUntil(
    clock: _FakeClock, at: float, then: HomeNetworkState,
) -> Callable[[], HomeNetworkState]:
    """JOINING before ``at`` seconds on the fake clock, ``then`` from it on."""
    return lambda: HomeNetworkState.AT_HOME_JOINING if clock.now < at else then


class _Response:
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _realDetector(
    ssid: Callable[[], str | None], scan: Callable[[], list[str] | None],
) -> HomeNetworkDetector:
    """The REAL detector with faked nmcli/hostname/HTTP readers."""
    config: dict[str, Any] = {
        "pi": {
            "homeNetwork": {
                "ssid": _HOME_SSID,
                "subnet": "10.27.27.0/24",
                "pingTimeoutSeconds": 3,
                "serverPingPath": "/api/v1/health",
            },
            "companionService": {"baseUrl": "http://10.27.27.10:8000"},
        },
    }
    return HomeNetworkDetector(
        config,
        ssidReader=ssid,
        scanReader=scan,
        ipReader=lambda: ["10.27.27.28"],
        httpOpener=lambda _req, timeout: _Response(),
        apiKey="test-key",
    )


# =============================================================================
# Associated mid-wait -> drain
# =============================================================================


class TestAssociatedMidWait:

    def test_associatedAt20s_drainStartsAbout20s_delivered_underCeiling(self) -> None:
        """
        Given: the home SSID is visible but unassociated until t=20 s
        When: run() is called at key-off
        Then: it waits, the drain starts at about 20 s (within one poll),
            delivers, and the whole run stays under the ceiling
        """
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []
        homeState = _joiningUntil(
            clock, _JOINED_AT_SEC, HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        )

        result = _task(homeState, sync, clock, records).run()

        assert result == OutcomeKind.DELIVERED
        assert len(sync.starts) == 1
        assert _JOINED_AT_SEC <= sync.starts[0] < _JOINED_AT_SEC + JOIN_POLL_SEC
        assert clock.now < _CIO_CEILING_SEC
        assert [r.kind for r in records] == [OutcomeKind.DELIVERED]

    def test_realDetector_ssidAssociatesAt20s_drains(self) -> None:
        """Faked nmcli: visible + unassociated, then associated at t=20 s."""
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []
        detector = _realDetector(
            ssid=lambda: _HOME_SSID if clock.now >= _JOINED_AT_SEC else "",
            scan=lambda: ["Neighbour", _HOME_SSID],
        )

        result = _task(detector.getHomeNetworkState, sync, clock, records).run()

        assert result == OutcomeKind.DELIVERED
        assert _JOINED_AT_SEC <= sync.starts[0] < _JOINED_AT_SEC + JOIN_POLL_SEC

    def test_pollsAtAFixedCadence(self) -> None:
        clock = _FakeClock()
        homeState = _joiningUntil(
            clock, _JOINED_AT_SEC, HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        )

        _task(homeState, _Sync(clock), clock, []).run()

        assert clock.sleeps
        assert set(clock.sleeps) == {JOIN_POLL_SEC}

    def test_joinedButServerDown_drainUsesWhatIsLeftOfTheSameCeiling(self) -> None:
        """
        Given: the rejoin lands at 50 s and every sync attempt then fails
        When: run() is called
        Then: no attempt starts at or after 60 s from run() start, and no wait
            runs past it -- the JOINING wait and the drain share ONE ceiling
        """
        clock = _FakeClock()
        sync = _Sync(clock, fail=True)
        records: list[SyncOutcomeRecord] = []
        homeState = _joiningUntil(clock, 50.0, HomeNetworkState.AT_HOME_SERVER_DOWN)

        result = _task(homeState, sync, clock, records).run()

        assert result == OutcomeKind.AT_HOME_SERVER_DOWN
        assert sync.starts
        assert all(50.0 <= s < _CIO_CEILING_SEC for s in sync.starts)
        assert clock.now <= _CIO_CEILING_SEC

    def test_joinedButHomeUnconfirmed_drainsAsUnknownNetwork(self) -> None:
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []
        homeState = _joiningUntil(clock, _JOINED_AT_SEC, HomeNetworkState.UNKNOWN)

        result = _task(homeState, sync, clock, records).run()

        assert result == OutcomeKind.DELIVERED
        assert len(sync.starts) == 1


# =============================================================================
# Still joining at the ceiling -> AT_HOME_JOINING_TIMEOUT
# =============================================================================


class TestJoiningTimeout:

    def test_neverAssociates_polledUntilTheCeiling_timeoutRecorded(self) -> None:
        """
        Given: the home SSID stays visible and unassociated
        When: run() is called
        Then: runSync is never called, the wait ends within the ceiling, and
            exactly one AT_HOME_JOINING_TIMEOUT record carries the backlog
        """
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []

        result = _task(
            lambda: HomeNetworkState.AT_HOME_JOINING, sync, clock, records,
        ).run()

        assert result == OutcomeKind.AT_HOME_JOINING_TIMEOUT
        assert sync.starts == []
        assert clock.now <= _CIO_CEILING_SEC
        # Polled right up to the ceiling: no room left for one more poll.
        assert clock.now + JOIN_POLL_SEC >= _CIO_CEILING_SEC
        assert len(clock.sleeps) > 1
        assert len(records) == 1
        assert records[0].kind == OutcomeKind.AT_HOME_JOINING_TIMEOUT
        assert records[0].backlogStart == 412
        assert records[0].backlogEnd == 412

    def test_realDetector_visibleNeverAssociated_polledToCeiling_timeout(self) -> None:
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []
        detector = _realDetector(ssid=lambda: "", scan=lambda: [_HOME_SSID])

        result = _task(detector.getHomeNetworkState, sync, clock, records).run()

        assert result == OutcomeKind.AT_HOME_JOINING_TIMEOUT
        assert sync.starts == []
        assert len(clock.sleeps) > 1
        assert clock.now <= _CIO_CEILING_SEC
        assert [r.kind for r in records] == [OutcomeKind.AT_HOME_JOINING_TIMEOUT]

    def test_associatedOnlyAfterTheCeilingIsSpent_timeoutNoAttempt(self) -> None:
        """A state read that itself runs past the ceiling leaves no time to drain."""
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []
        reads = {"n": 0}

        def homeState() -> HomeNetworkState:
            reads["n"] += 1
            if reads["n"] == 1:
                return HomeNetworkState.AT_HOME_JOINING
            # The association landed, but this read (nmcli + probe) took the
            # clock past the ceiling.
            clock.now = _CIO_CEILING_SEC + 1.0
            return HomeNetworkState.AT_HOME_SERVER_REACHABLE

        result = _task(homeState, sync, clock, records).run()

        assert result == OutcomeKind.AT_HOME_JOINING_TIMEOUT
        assert sync.starts == []

    def test_brokenWait_endsTheWait_neverRaises(self) -> None:
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []

        def brokenSleep(_seconds: float) -> None:
            raise OSError("interrupted")

        task = SyncWithServerTask(
            homeState=lambda: HomeNetworkState.AT_HOME_JOINING,
            runSync=sync,
            writeRecord=records.append,
            ceilingSec=_CIO_CEILING_SEC,
            sleepFn=brokenSleep,
            monotonic=clock.monotonic,
        )

        assert task.run() == OutcomeKind.AT_HOME_JOINING_TIMEOUT
        assert sync.starts == []
        assert len(records) == 1

    def test_detectorRaisesMidWait_unknown_drains(self) -> None:
        """A dead detector is UNKNOWN (US-776-c), which drains; never raises."""
        clock = _FakeClock()
        sync = _Sync(clock)
        reads = {"n": 0}

        def homeState() -> HomeNetworkState:
            reads["n"] += 1
            if reads["n"] == 1:
                return HomeNetworkState.AT_HOME_JOINING
            raise RuntimeError("nmcli exploded")

        result = _task(homeState, sync, clock, []).run()

        assert result == OutcomeKind.DELIVERED
        assert len(sync.starts) == 1


# =============================================================================
# Not visible -> AWAY, zero waits
# =============================================================================


class TestNotVisibleIsAway:

    def test_realDetector_homeSsidNotVisible_awayZeroWaitsNoSync(self) -> None:
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []
        detector = _realDetector(ssid=lambda: "", scan=lambda: ["Neighbour"])

        result = _task(detector.getHomeNetworkState, sync, clock, records).run()

        assert result == OutcomeKind.AWAY
        assert clock.sleeps == []
        assert clock.now == 0.0
        assert sync.starts == []
        assert [r.kind for r in records] == [OutcomeKind.AWAY]

    def test_ssidLeavesTheCacheMidWait_away_noSync(self) -> None:
        """The same gate as at key-off: a positive AWAY skips the drain."""
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []
        homeState = _joiningUntil(clock, 10.0, HomeNetworkState.AWAY)

        result = _task(homeState, sync, clock, records).run()

        assert result == OutcomeKind.AWAY
        assert sync.starts == []
        assert [r.kind for r in records] == [OutcomeKind.AWAY]


@pytest.mark.parametrize(
    "state",
    [
        HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        HomeNetworkState.AT_HOME_SERVER_DOWN,
        HomeNetworkState.UNKNOWN,
    ],
)
def test_notJoining_noJoinWait_drainStartsAtOnce(state: HomeNetworkState) -> None:
    clock = _FakeClock()
    sync = _Sync(clock)

    _task(lambda: state, sync, clock, []).run()

    assert sync.starts == [0.0]
