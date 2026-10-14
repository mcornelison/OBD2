################################################################################
# File Name: test_sync_joining_wait.py
# Purpose/Description: US-776-e -- at home with the WiFi rejoin still pending
#                      (AT_HOME_JOINING), the shutdown sync polls for the
#                      association inside pi.homeNetwork.joinWaitSec, then
#                      drains. The join wait is bounded on its own (ARCH-065:
#                      the drain's stall clock starts at association); a
#                      rejoin that outlasts it records AT_HOME_JOINING_TIMEOUT.
#                      Away, nothing waits.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-01    | Rex          | Initial -- US-776-e JOINING wait.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T3: ceilingSec -> joinWaitSec + stallSec;
#               |              | the shared-ceiling tests became stall-clock-from-association.
# 2026-10-11    | Rex          | US-776-k2: an AWAY poll inside the wait no longer
#               |              | ends it; key-off rigs prove the three exits with
#               |              | custody (config.json waits).
# 2026-10-13    | Atlas (ARCH-068) | joinWaitSec 120 -> 30: the Sprint 97 "stays 120"
#               |              | pin becomes DEFAULTS == config.json, so the two
#               |              | copies cannot drift.
# ================================================================================
################################################################################
"""US-776-e: at home, the shutdown waits for the WiFi rejoin within the ceiling."""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import src.pi.power.power_watch.__main__ as m
from src.common.config.validator import DEFAULTS
from src.pi.network.home_detector import HomeNetworkDetector, HomeNetworkState, SweepResult
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.sync_custody import CUSTODY_RECORD_FILENAME, makeSyncCustodyHook
from src.pi.power.power_watch.tasks.sync_with_server import (
    JOIN_POLL_SEC,
    SyncOutcomeRecord,
    SyncWithServerTask,
)
from src.pi.sync.backlog import BACKLOG_DELIVERED, BACKLOG_OUTSTANDING, SyncBacklog

_JOIN_WAIT_SEC = 60.0
_STALL_SEC = 60.0
_HOME_SSID = "DeathStarWiFi"
_JOINED_AT_SEC = 20.0
_REPO_ROOT = Path(__file__).resolve().parents[4]
_VCELL_FLOOR = 3.30
_VCELL_OK = 3.90
_BACKLOG_ROWS = 412


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
        self.delivers = not fail  # a clean runSync empties the backlog
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
        joinWaitSec=_JOIN_WAIT_SEC,
        stallSec=_STALL_SEC,
        sleepFn=clock.sleep,
        monotonic=clock.monotonic,
        backlogReader=lambda: 0 if (sync.delivers and sync.starts) else backlog,
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
    ssid: Callable[[], str | None],
    scan: Callable[[], list[str] | None],
    *,
    serverUp: bool = True,
) -> HomeNetworkDetector:
    """The REAL detector with faked nmcli/hostname/HTTP readers."""

    def opener(_req: object, timeout: float) -> _Response:
        if not serverUp:
            raise urllib.error.URLError("connection refused")
        return _Response()

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
        httpOpener=opener,
        apiKey="test-key",
    )


# =============================================================================
# Associated mid-wait -> drain
# =============================================================================


class TestAssociatedMidWait:

    def test_associatedAt20s_drainStartsAbout20s_delivered_underJoinWait(self) -> None:
        """
        Given: the home SSID is visible but unassociated until t=20 s
        When: run() is called at key-off
        Then: it waits, the drain starts at about 20 s (within one poll),
            delivers, and the whole run stays under the join wait
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
        assert clock.now < _JOIN_WAIT_SEC
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

    def test_joinedButServerDown_stallClockStartsAtAssociation(self) -> None:
        """
        Given: the rejoin lands at 50 s and every sync attempt then fails
        When: run() is called
        Then: the drain starts at the association and ends 60 s later
            (ARCH-065): the 50 s of joining did NOT count against the stall
            window, and no attempt starts before the association
        """
        clock = _FakeClock()
        sync = _Sync(clock, fail=True)
        records: list[SyncOutcomeRecord] = []
        homeState = _joiningUntil(clock, 50.0, HomeNetworkState.AT_HOME_SERVER_DOWN)

        result = _task(homeState, sync, clock, records).run()

        assert result == OutcomeKind.AT_HOME_SERVER_DOWN
        assert sync.starts
        assert all(s >= 50.0 for s in sync.starts)
        assert 50.0 + _STALL_SEC <= clock.now <= 50.0 + JOIN_POLL_SEC + _STALL_SEC

    def test_joinedButHomeUnconfirmed_drainsAsUnknownNetwork(self) -> None:
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []
        homeState = _joiningUntil(clock, _JOINED_AT_SEC, HomeNetworkState.UNKNOWN)

        result = _task(homeState, sync, clock, records).run()

        assert result == OutcomeKind.DELIVERED
        assert len(sync.starts) == 1


# =============================================================================
# Still joining at the join-wait bound -> AT_HOME_JOINING_TIMEOUT
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
        assert clock.now <= _JOIN_WAIT_SEC
        # Polled right up to the ceiling: no room left for one more poll.
        assert clock.now + JOIN_POLL_SEC >= _JOIN_WAIT_SEC
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
        assert clock.now <= _JOIN_WAIT_SEC
        assert [r.kind for r in records] == [OutcomeKind.AT_HOME_JOINING_TIMEOUT]

    def test_associationLandingLate_stillDrains_stallClockFromThen(self) -> None:
        """A state read that itself runs past the join wait still ended in an
        association: the drain runs (ARCH-065 retired the shared ceiling)."""
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []
        reads = {"n": 0}

        def homeState() -> HomeNetworkState:
            reads["n"] += 1
            if reads["n"] == 1:
                return HomeNetworkState.AT_HOME_JOINING
            # The association landed, but this read (nmcli + probe) took the
            # clock past the join wait.
            clock.now = _JOIN_WAIT_SEC + 1.0
            return HomeNetworkState.AT_HOME_SERVER_REACHABLE

        result = _task(homeState, sync, clock, records).run()

        assert result == OutcomeKind.DELIVERED
        assert len(sync.starts) == 1

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
            joinWaitSec=_JOIN_WAIT_SEC,
            stallSec=_STALL_SEC,
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

    def test_ssidLeavesTheCacheMidWait_keepsWaiting_joinTimeout_noSync(self) -> None:
        """
        US-776-k2 deliberately CHANGES this case. Until k2 an AWAY poll inside
        the wait was the key-off gate again and skipped the drain; but each poll
        re-reads NetworkManager's cached list, so one poll that missed home
        abandoned a sync at home (2026-10-11 13:14:47, moved inside the wait).
        Once home has been seen only association or joinWaitSec ends the wait.

        Given: JOINING, then AWAY from t=10 s for the rest of the wait
        When: run() is called
        Then: the wait is NOT ended by the AWAY reads; it runs to joinWaitSec
            and records AT_HOME_JOINING_TIMEOUT, never AWAY, with no sync
        """
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []
        homeState = _joiningUntil(clock, 10.0, HomeNetworkState.AWAY)

        result = _task(homeState, sync, clock, records).run()

        assert result == OutcomeKind.AT_HOME_JOINING_TIMEOUT
        assert clock.now + JOIN_POLL_SEC >= _JOIN_WAIT_SEC
        assert sync.starts == []
        assert [r.kind for r in records] == [OutcomeKind.AT_HOME_JOINING_TIMEOUT]


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


# =============================================================================
# US-776-k2: once home is seen, only association or joinWaitSec ends the wait
# =============================================================================


def _homeNetworkConfig() -> dict[str, Any]:
    """The repo's ``pi.homeNetwork`` -- the section main() reads the waits from."""
    with open(_REPO_ROOT / "config.json", encoding="utf-8") as fh:
        return json.load(fh)["pi"]["homeNetwork"]


class _RecordingDetector:
    """The REAL detector's live read, recording every state it answered."""

    def __init__(self, detector: HomeNetworkDetector) -> None:
        self.detector = detector
        self.states: list[HomeNetworkState] = []

    def __call__(self) -> HomeNetworkState:
        state = self.detector.getHomeNetworkState()
        self.states.append(state)
        return state


class _KeyOffResult:
    """What a key-off at home left behind."""

    def __init__(self, tmp_path: Path) -> None:
        self.outcomePath = tmp_path / "powerwatch_outcome.json"
        self.custodyPath = tmp_path / CUSTODY_RECORD_FILENAME
        self.powerOffAt: list[float] = []

    def outcome(self) -> dict[str, Any]:
        return json.loads(self.outcomePath.read_text(encoding="utf-8"))

    def custody(self) -> dict[str, Any]:
        return json.loads(self.custodyPath.read_text(encoding="utf-8"))


def _keyOffAtHome(
    tmp_path: Path,
    clock: _FakeClock,
    detector: HomeNetworkDetector,
    runSync: Callable[[], None],
    backlog: dict[str, int],
) -> tuple[_KeyOffResult, _RecordingDetector]:
    """Run one key-off wired the way main() wires powerwatch.

    The US-776-k1 sweep answers VISIBLE (home in range, wlan0 not associated),
    so the sync task's FIRST read is AT_HOME_JOINING; every later poll is a
    live read of the REAL detector over its faked cached nmcli list. The
    sequencer runs the sync task, then the custody hook, then the poweroff.
    The waits are config.json's pi.homeNetwork values, as in main().
    """
    homeNetwork = _homeNetworkConfig()
    result = _KeyOffResult(tmp_path)
    live = _RecordingDetector(detector)
    holder = m.HomeStateAtLoss(
        live, outcomePath=str(result.outcomePath), startFn=lambda target: target(),
        sweep=lambda: SweepResult.VISIBLE,
        observationTimeoutSec=detector.observationBoundSec,
    )
    syncTask = SyncWithServerTask(
        homeState=holder.stateForSync,
        runSync=runSync,
        writeRecord=holder.wrapSink(
            m.makeOutcomeSink(str(result.outcomePath), homeState=holder.stateName)
        ),
        joinWaitSec=float(homeNetwork["joinWaitSec"]),
        stallSec=float(homeNetwork["stallSec"]),
        sleepFn=clock.sleep,
        monotonic=clock.monotonic,
        backlogReader=lambda: sum(backlog.values()),
        lastProbe=lambda: detector.lastProbe,
    )
    custodyFn = makeSyncCustodyHook(
        recordPath=str(result.custodyPath),
        backlogReader=lambda **_kw: SyncBacklog(perTable=dict(backlog)),
    )
    ShutdownSequencer(
        isOnBattery=lambda: True,
        vcell=lambda: _VCELL_OK,
        runPipelineFn=syncTask.run,
        powerOffFn=lambda: result.powerOffAt.append(clock.now),
        vcellFloor=_VCELL_FLOOR,
        totalCapSec=45.0,
        smoothingSec=0.0,
        smoothingPollSec=0.0,
        sleepFn=lambda _s: None,
        prePowerOffFn=m.composePrePowerOffHooks(custodyFn, holder.ensureRecorded),
        powerLossObservedFn=holder.observe,
    ).handleOnBattery()
    return result, live


class TestUS776k2AwayPollInsideTheWait:

    def test_weakDrivewaySignal_awayPollKeepsWaiting_drainsOnAssociation(self) -> None:
        """
        Given: polls read JOINING, AWAY, JOINING, then associated at 9 s (the
            story's weak-driveway example)
        When: run() is called
        Then: the AWAY read does not end the wait; the sync runs once the
            association is reported and delivers
        """
        clock = _FakeClock()
        sync = _Sync(clock)
        records: list[SyncOutcomeRecord] = []
        script = [HomeNetworkState.AT_HOME_JOINING, HomeNetworkState.AWAY]

        def homeState() -> HomeNetworkState:
            if script:
                return script.pop(0)
            if clock.now < 9.0:
                return HomeNetworkState.AT_HOME_JOINING
            return HomeNetworkState.AT_HOME_SERVER_REACHABLE

        result = _task(homeState, sync, clock, records).run()

        assert result == OutcomeKind.DELIVERED
        assert len(sync.starts) == 1
        assert 9.0 <= sync.starts[0] < 9.0 + JOIN_POLL_SEC
        assert [r.kind for r in records] == [OutcomeKind.DELIVERED]

    def test_keyOff_cacheMissesHomeOnePoll_stillDelivers(self, tmp_path: Path) -> None:
        """
        Given: a key-off at home whose sweep saw home (AT_HOME_JOINING), and a
            cached scan list that drops home on the t=4 s poll (the REAL
            detector reads AWAY there), with wlan0 associating at t=9 s
        When: the sequencer runs the key-off
        Then: the AWAY poll keeps the wait going; the drain runs after the
            association, the outcome is DELIVERED and custody is DELIVERED
        """
        clock = _FakeClock()
        sync = _Sync(clock)
        backlog = {"realtime_data": _BACKLOG_ROWS}

        def runSync() -> None:
            sync()
            backlog["realtime_data"] = 0

        detector = _realDetector(
            ssid=lambda: _HOME_SSID if clock.now >= 9.0 else "",
            scan=lambda: ["Neighbour"] if clock.now == 4.0 else ["Neighbour", _HOME_SSID],
        )

        result, live = _keyOffAtHome(tmp_path, clock, detector, runSync, backlog)

        assert HomeNetworkState.AWAY in live.states  # the cache really did miss home
        assert live.states[-1] is HomeNetworkState.AT_HOME_SERVER_REACHABLE
        assert len(sync.starts) == 1 and sync.starts[0] >= 9.0
        assert result.powerOffAt and len(result.powerOffAt) == 1
        outcome = result.outcome()
        assert outcome["home_state"] == HomeNetworkState.AT_HOME_JOINING.name
        assert outcome["sync_outcome"] == OutcomeKind.DELIVERED.name
        assert result.custody()["verdict"] == BACKLOG_DELIVERED


class TestUS776k2JoinWaitFromConfig:

    def test_configJoinWait_matchesValidatorDefault(self) -> None:
        """The validator default and config.json carry ONE joinWaitSec (ARCH-068)."""
        assert _homeNetworkConfig()["joinWaitSec"] == DEFAULTS["pi.homeNetwork.joinWaitSec"]

    def test_keyOff_neverAssociates_endsAtJoinWaitSec_custodyOutstanding(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: a key-off at home whose sweep saw home, then a cached list that
            flickers home in and out (some polls read AWAY) and wlan0 that
            never associates
        When: the sequencer runs the key-off
        Then: the wait ends at config.json's joinWaitSec with
            AT_HOME_JOINING_TIMEOUT, no sync attempt, and the Pi powers down
            once with custody OUTSTANDING (every row still owed)
        """
        clock = _FakeClock()
        sync = _Sync(clock)
        backlog = {"realtime_data": _BACKLOG_ROWS}
        joinWaitSec = float(_homeNetworkConfig()["joinWaitSec"])
        detector = _realDetector(
            ssid=lambda: "",
            scan=lambda: [_HOME_SSID] if int(clock.now) % 4 == 0 else ["Neighbour"],
        )

        result, live = _keyOffAtHome(tmp_path, clock, detector, sync, backlog)

        assert HomeNetworkState.AWAY in live.states  # the AWAY reads happened
        assert sync.starts == []
        assert len(result.powerOffAt) == 1
        assert result.powerOffAt[0] <= joinWaitSec
        assert result.powerOffAt[0] + JOIN_POLL_SEC >= joinWaitSec
        assert result.outcome()["sync_outcome"] == OutcomeKind.AT_HOME_JOINING_TIMEOUT.name
        custody = result.custody()
        assert custody["verdict"] == BACKLOG_OUTSTANDING
        assert custody["outstandingRows"] == _BACKLOG_ROWS


class TestUS776k2AssociatedServerDown:

    def test_keyOff_associatedProbeFails_serverDown_withinStallSec_custodyOutstanding(
        self, tmp_path: Path,
    ) -> None:
        """
        CIO Q25 A.

        Given: a key-off at home whose sweep saw home, wlan0 associating at
            t=10 s, the server health probe failing, and every sync attempt
            failing
        When: the sequencer runs the key-off
        Then: the outcome is AT_HOME_SERVER_DOWN, the drain ends within
            config.json's stallSec (60 s) of the drain start plus at most one
            retry wait, and custody is OUTSTANDING
        """
        clock = _FakeClock()
        sync = _Sync(clock, fail=True)
        backlog = {"realtime_data": _BACKLOG_ROWS}
        stallSec = float(_homeNetworkConfig()["stallSec"])
        detector = _realDetector(
            ssid=lambda: _HOME_SSID if clock.now >= 10.0 else "",
            scan=lambda: [_HOME_SSID],
            serverUp=False,
        )

        result, live = _keyOffAtHome(tmp_path, clock, detector, sync, backlog)

        assert live.states[-1] is HomeNetworkState.AT_HOME_SERVER_DOWN
        assert result.outcome()["sync_outcome"] == OutcomeKind.AT_HOME_SERVER_DOWN.name
        drainStart = sync.starts[0]
        assert drainStart >= 10.0
        retryWaits = [b - a for a, b in zip(sync.starts, sync.starts[1:], strict=False)]
        assert retryWaits
        drainSpan = result.powerOffAt[0] - drainStart
        assert stallSec <= drainSpan <= stallSec + max(retryWaits)
        custody = result.custody()
        assert custody["verdict"] == BACKLOG_OUTSTANDING
        assert custody["outstandingRows"] == _BACKLOG_ROWS
