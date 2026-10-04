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


def test_wallVcellCache_keepsLastGood_neverRaises() -> None:
    from src.pi.power.power_watch.__main__ import WallVcellCache

    cache = WallVcellCache()
    assert cache.last() is None
    cache.update(4.21)
    cache.update(None)
    assert cache.last() == 4.21


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


def test_pldLoop_feedsWallVcellOnlyWhilePowerPresent_andSurvivesRaise() -> None:
    import threading
    from unittest.mock import MagicMock

    from src.pi.power.power_watch.__main__ import _runPldWatchLoop

    lostSeq = iter([False, False, False, True])
    calls: list[int] = []
    stop = MagicMock()
    ticks = iter([False, False, False, True])
    stop.wait.side_effect = lambda timeout: next(ticks)

    def wall() -> None:
        calls.append(1)
        raise RuntimeError("i2c")

    seq = MagicMock()
    _runPldWatchLoop(
        isPowerLostFn=lambda: next(lostSeq, True), stop=stop, serviceStartMono=0.0,
        bootGraceSec=0.0, pldPollSec=1.0, pldGpioPin=6, handleLock=threading.Lock(),
        shutdownSequencer=seq, monotonicFn=lambda: 100.0, wallVcell=wall,
    )
    assert len(calls) == 2  # two present polls fed the cache
