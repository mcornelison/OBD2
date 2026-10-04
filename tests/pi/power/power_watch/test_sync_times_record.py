from src.pi.network.home_detector import HomeNetworkState
from src.pi.power.power_watch.tasks.sync_with_server import SyncOutcomeRecord, SyncWithServerTask


def test_deliveredRecord_carriesStartAndEndTimes() -> None:
    records: list[SyncOutcomeRecord] = []
    stamps = iter(["2026-10-02T16:53:40Z", "2026-10-02T16:58:12Z"])
    task = SyncWithServerTask(
        homeState=lambda: HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        runSync=lambda: None, writeRecord=records.append,
        joinWaitSec=120.0, stallSec=60.0, sleepFn=lambda s: None,
        monotonic=lambda: 0.0, backlogReader=lambda: 0, nowIsoFn=lambda: next(stamps),
    )
    task.run()
    assert (records[0].startedAt, records[0].endedAt) == ("2026-10-02T16:53:40Z", "2026-10-02T16:58:12Z")


def test_awaySkip_hasNoTimes() -> None:
    records: list[SyncOutcomeRecord] = []
    task = SyncWithServerTask(
        homeState=lambda: HomeNetworkState.AWAY, runSync=lambda: None, writeRecord=records.append,
        joinWaitSec=120.0, stallSec=60.0, sleepFn=lambda s: None, monotonic=lambda: 0.0,
        backlogReader=lambda: 5, nowIsoFn=lambda: "2026-10-02T16:53:40Z",
    )
    task.run()
    assert (records[0].startedAt, records[0].endedAt) == (None, None)


def test_wallVcellCache_freshReturned_staleIsNone_noneKeepsPrevious() -> None:
    from src.pi.power.power_watch.__main__ import WALL_VCELL_MAX_AGE_S, WallVcellCache

    now = [100.0]
    cache = WallVcellCache(monotonicFn=lambda: now[0])
    assert cache.last() is None
    cache.update(4.21)
    now[0] += WALL_VCELL_MAX_AGE_S - 1
    assert cache.last() == 4.21
    cache.update(None)  # keeps the previous value (and its age)
    assert cache.last() == 4.21
    now[0] += 2.0  # now older than 15 s
    assert cache.last() is None


def test_outcomeSink_carriesTimesAndWallVcell(tmp_path) -> None:
    import json

    from src.pi.power.power_watch.__main__ import makeOutcomeSink
    from src.pi.power.power_watch.contract import OutcomeKind

    path = tmp_path / "o.json"
    sink = makeOutcomeSink(str(path), wallVcell=lambda: 4.2)
    sink(SyncOutcomeRecord(OutcomeKind.DELIVERED, "ok", 3, 0, "2026-10-02T16:53:40Z", "2026-10-02T16:58:12Z"))
    rec = json.loads(path.read_text(encoding="utf-8"))
    assert rec["sync_started_at"] == "2026-10-02T16:53:40Z"
    assert rec["sync_ended_at"] == "2026-10-02T16:58:12Z"
    assert rec["vcell_before_cut_v"] == 4.2


def test_pldLoop_makesNoVcellCall_andStillFiresOnLoss() -> None:
    import inspect
    import threading
    from unittest.mock import MagicMock

    from src.pi.power.power_watch.__main__ import _runPldWatchLoop

    assert "wallVcell" not in inspect.signature(_runPldWatchLoop).parameters
    lostSeq = iter([False, False, True])
    stop = MagicMock()
    ticks = iter([False, False, True])
    stop.wait.side_effect = lambda timeout: next(ticks)
    seq = MagicMock()
    _runPldWatchLoop(
        isPowerLostFn=lambda: next(lostSeq, True), stop=stop, serviceStartMono=0.0,
        bootGraceSec=0.0, pldPollSec=1.0, pldGpioPin=6, handleLock=threading.Lock(),
        shutdownSequencer=seq, monotonicFn=lambda: 100.0,
    )
    seq.handleOnBattery.assert_called_once()


def test_wallVcellFeed_updatesWhenPresentAfterRead_notWhenLost() -> None:
    from src.pi.power.power_watch.__main__ import WallVcellCache, makeWallVcellFeed

    cache = WallVcellCache(monotonicFn=lambda: 0.0)
    recorded: list[tuple] = []
    lost = [False]
    feed = makeWallVcellFeed(cache, lambda: lost[0], lambda *a: recorded.append(a))
    feed(1.0, 4.2, 90)
    assert cache.last() == 4.2
    lost[0] = True
    feed(2.0, 3.9, 80)
    assert cache.last() == 4.2  # post-cut value never cached as on-wall
    assert len(recorded) == 2  # the monitor's own recording is untouched


def test_wallVcellFeed_neverRaisesIntoThePoll() -> None:
    from src.pi.power.power_watch.__main__ import WallVcellCache, makeWallVcellFeed

    def boom() -> bool:
        raise OSError("gpio")

    feed = makeWallVcellFeed(WallVcellCache(), boom, lambda *a: None)
    feed(1.0, 4.2, 90)


def test_homeStateAtLossRecord_carriesVcellBeforeCut(tmp_path) -> None:
    import json

    from src.pi.power.power_watch.__main__ import HomeStateAtLoss

    path = tmp_path / "o.json"
    h = HomeStateAtLoss(
        lambda: None, outcomePath=str(path), startFn=lambda fn: None, vcellBeforeCut=lambda: 4.19
    )
    h.observe()
    h.ensureRecorded()
    assert json.loads(path.read_text(encoding="utf-8"))["vcell_before_cut_v"] == 4.19
