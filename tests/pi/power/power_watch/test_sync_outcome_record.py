################################################################################
# File Name: test_sync_outcome_record.py
# Purpose/Description: US-776-d -- every SyncWithServerTask.run() writes
#                      exactly one outcome record (DELIVERED, AWAY,
#                      UNKNOWN_NETWORK, AT_HOME_SERVER_DOWN, PROBE_MISCONFIGURED,
#                      or REAL_ERROR for a genuine fault), carrying backlog_start
#                      (before the first attempt) and backlog_end (after the
#                      last), and that record reaches the durable shutdown file
#                      US-776-f lands into startup_log.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-01    | Rex          | Initial -- US-776-d one record per shutdown
# ================================================================================
################################################################################
"""Every shutdown sync records why it ended, with the backlog at both ends."""

from __future__ import annotations

import io
import json
import logging
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import src.pi.power.power_watch.__main__ as m
from src.pi.network.home_detector import HomeNetworkDetector, HomeNetworkState, ProbeResult
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.tasks.sync_with_server import (
    SyncOutcomeRecord,
    SyncWithServerTask,
)
from src.pi.sync.backlog import SyncBacklog

_LOGGER = "src.pi.power.power_watch.tasks.sync_with_server"


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Sync:
    """runSync fake: pops one item per call; an Exception item is raised.

    A successful call empties the shared backlog, as a real drain would.
    """

    def __init__(self, items: list[Exception | None], backlog: list[int]) -> None:
        self._items = list(items)
        self._backlog = backlog
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1
        item = self._items.pop(0) if self._items else RuntimeError("net")
        if isinstance(item, Exception):
            raise item
        self._backlog[0] = 0


def _task(
    state: HomeNetworkState,
    sync: Callable[[], None],
    records: list[SyncOutcomeRecord],
    *,
    backlog: list[int] | None = None,
    probe: ProbeResult | None = None,
    ceilingSec: float = 10.0,
) -> SyncWithServerTask:
    clock = _Clock()
    return SyncWithServerTask(
        homeState=lambda: state,
        runSync=sync,
        writeRecord=records.append,
        ceilingSec=ceilingSec,
        sleepFn=clock.sleep,
        monotonic=clock.monotonic,
        backlogReader=(lambda: backlog[0]) if backlog is not None else None,
        lastProbe=lambda: probe,
    )


# =============================================================================
# Exactly one record per run, one per outcome
# =============================================================================


class TestOneRecordPerOutcome:

    def test_away_oneAwayRecord_backlogBothEnds_noSync(self) -> None:
        records: list[SyncOutcomeRecord] = []
        backlog = [412]
        sync = _Sync([], backlog)

        result = _task(HomeNetworkState.AWAY, sync, records, backlog=backlog).run()

        assert result is OutcomeKind.AWAY
        assert sync.calls == 0
        assert len(records) == 1
        assert records[0].kind is OutcomeKind.AWAY
        assert (records[0].backlogStart, records[0].backlogEnd) == (412, 412)

    def test_delivered_oneRecord_backlogStartAndEnd(self) -> None:
        records: list[SyncOutcomeRecord] = []
        backlog = [412]
        sync = _Sync([None], backlog)

        result = _task(
            HomeNetworkState.AT_HOME_SERVER_REACHABLE, sync, records, backlog=backlog
        ).run()

        assert result is OutcomeKind.DELIVERED
        assert len(records) == 1
        assert records[0].kind is OutcomeKind.DELIVERED
        assert (records[0].backlogStart, records[0].backlogEnd) == (412, 0)

    def test_deliveredEmptyBacklog_distinguishableFromDeliveredNonEmpty(self) -> None:
        """
        Given: two drains that both deliver, one starting with nothing owed
        When: each runs
        Then: both read DELIVERED, and backlog_start tells them apart (the
            09-27 case: DELIVERED with the drain never having moved a row)
        """
        emptyRecs: list[SyncOutcomeRecord] = []
        fullRecs: list[SyncOutcomeRecord] = []
        empty, full = [0], [412]

        _task(HomeNetworkState.AT_HOME_SERVER_REACHABLE, _Sync([None], empty), emptyRecs,
              backlog=empty).run()
        _task(HomeNetworkState.AT_HOME_SERVER_REACHABLE, _Sync([None], full), fullRecs,
              backlog=full).run()

        assert emptyRecs[0].kind is fullRecs[0].kind is OutcomeKind.DELIVERED
        assert emptyRecs[0].backlogStart == 0
        assert fullRecs[0].backlogStart == 412
        assert emptyRecs[0] != fullRecs[0]

    def test_deliveredAfterRetries_stillOneRecord(self) -> None:
        records: list[SyncOutcomeRecord] = []
        backlog = [7]
        sync = _Sync([RuntimeError("net"), RuntimeError("net"), None], backlog)

        result = _task(
            HomeNetworkState.AT_HOME_SERVER_REACHABLE, sync, records, backlog=backlog
        ).run()

        assert result is OutcomeKind.DELIVERED
        assert sync.calls == 3
        assert len(records) == 1

    def test_unknownNetwork_failedDrain_unknownNetworkRecord(self) -> None:
        records: list[SyncOutcomeRecord] = []
        backlog = [9]

        result = _task(HomeNetworkState.UNKNOWN, _Sync([], backlog), records,
                       backlog=backlog).run()

        assert result is OutcomeKind.UNKNOWN_NETWORK
        assert len(records) == 1
        assert (records[0].backlogStart, records[0].backlogEnd) == (9, 9)

    def test_unknownNetwork_deliveredDrain_isDelivered(self) -> None:
        """A drain that delivered says DELIVERED whatever the network read said."""
        records: list[SyncOutcomeRecord] = []
        backlog = [9]

        result = _task(HomeNetworkState.UNKNOWN, _Sync([None], backlog), records,
                       backlog=backlog).run()

        assert result is OutcomeKind.DELIVERED
        assert len(records) == 1

    def test_serverDown_connectionError_atHomeServerDown(self) -> None:
        records: list[SyncOutcomeRecord] = []
        probe = ProbeResult(status=None, error="connection refused")

        result = _task(HomeNetworkState.AT_HOME_SERVER_DOWN, _Sync([], [5]), records,
                       backlog=[5], probe=probe).run()

        assert result is OutcomeKind.AT_HOME_SERVER_DOWN
        assert len(records) == 1

    def test_serverDown_5xx_atHomeServerDown(self) -> None:
        records: list[SyncOutcomeRecord] = []

        result = _task(HomeNetworkState.AT_HOME_SERVER_DOWN, _Sync([], [5]), records,
                       probe=ProbeResult(status=503, error="HTTP 503")).run()

        assert result is OutcomeKind.AT_HOME_SERVER_DOWN

    @pytest.mark.parametrize("status", [404, 405, 401, 403])
    def test_misconfiguredProbe_failedDrain_probeMisconfigured(self, status: int) -> None:
        records: list[SyncOutcomeRecord] = []

        result = _task(
            HomeNetworkState.AT_HOME_SERVER_DOWN, _Sync([], [5]), records,
            backlog=[5], probe=ProbeResult(status=status, error=f"HTTP {status}"),
        ).run()

        assert result is OutcomeKind.PROBE_MISCONFIGURED
        assert len(records) == 1
        assert str(status) in records[0].detail

    def test_reachableProbe_failedDrain_atHomeServerDown(self) -> None:
        records: list[SyncOutcomeRecord] = []

        result = _task(
            HomeNetworkState.AT_HOME_SERVER_REACHABLE, _Sync([], [5]), records,
            probe=ProbeResult(status=200, error=None),
        ).run()

        assert result is OutcomeKind.AT_HOME_SERVER_DOWN

    def test_genuineFault_oneRealErrorRecord(self) -> None:
        records: list[SyncOutcomeRecord] = []
        backlog = [3]

        result = _task(HomeNetworkState.AT_HOME_SERVER_REACHABLE,
                       _Sync([ValueError("corrupt db")], backlog), records,
                       backlog=backlog).run()

        assert result is OutcomeKind.REAL_ERROR
        assert len(records) == 1
        assert (records[0].backlogStart, records[0].backlogEnd) == (3, 3)


# =============================================================================
# The backlog reader never makes the record lie, and never raises out
# =============================================================================


class TestBacklogReads:

    def test_startReadBeforeFirstAttempt_endReadAfterLast(self) -> None:
        events: list[str] = []
        backlog = [10]

        def reader() -> int:
            events.append(f"read:{backlog[0]}")
            return backlog[0]

        def sync() -> None:
            events.append("sync")
            backlog[0] = 0

        records: list[SyncOutcomeRecord] = []
        SyncWithServerTask(
            homeState=lambda: HomeNetworkState.AT_HOME_SERVER_REACHABLE,
            runSync=sync,
            writeRecord=records.append,
            ceilingSec=10.0,
            backlogReader=reader,
        ).run()

        assert events == ["read:10", "sync", "read:0"]
        assert (records[0].backlogStart, records[0].backlogEnd) == (10, 0)

    def test_noReader_backlogIsNone(self) -> None:
        records: list[SyncOutcomeRecord] = []

        _task(HomeNetworkState.AT_HOME_SERVER_REACHABLE, _Sync([None], [1]), records).run()

        assert (records[0].backlogStart, records[0].backlogEnd) == (None, None)

    def test_readerRaises_backlogNone_runStillRecords(self) -> None:
        def reader() -> int:
            raise OSError("database is locked")

        records: list[SyncOutcomeRecord] = []
        result = SyncWithServerTask(
            homeState=lambda: HomeNetworkState.AT_HOME_SERVER_REACHABLE,
            runSync=lambda: None,
            writeRecord=records.append,
            ceilingSec=10.0,
            backlogReader=reader,
        ).run()

        assert result is OutcomeKind.DELIVERED
        assert (records[0].backlogStart, records[0].backlogEnd) == (None, None)

    def test_lastProbeRaises_failedDrain_atHomeServerDown(self) -> None:
        def probe() -> ProbeResult:
            raise RuntimeError("detector gone")

        clock = _Clock()
        records: list[SyncOutcomeRecord] = []
        result = SyncWithServerTask(
            homeState=lambda: HomeNetworkState.AT_HOME_SERVER_DOWN,
            runSync=_Sync([], [1]),
            writeRecord=records.append,
            ceilingSec=5.0,
            sleepFn=clock.sleep,
            monotonic=clock.monotonic,
            lastProbe=probe,
        ).run()

        assert result is OutcomeKind.AT_HOME_SERVER_DOWN
        assert len(records) == 1


class TestCountFromSyncBacklog:
    """The production adapter: a lower-bound or failed count is NULL, never a guess."""

    def test_completeCount_isTotal(self) -> None:
        assert m.backlogCount(SyncBacklog(perTable={"a": 3, "b": 4})) == 7

    def test_emptyComplete_isZero(self) -> None:
        assert m.backlogCount(SyncBacklog()) == 0

    def test_unreadableTable_isNone(self) -> None:
        assert m.backlogCount(SyncBacklog(perTable={"a": 3}, unreadableTables=("b",))) is None

    def test_databaseError_isNone(self) -> None:
        assert m.backlogCount(SyncBacklog(error="unable to open database")) is None


# =============================================================================
# Through the real detector: a 404 probe reads PROBE_MISCONFIGURED
# =============================================================================


def _httpError(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://10.27.27.10:8000/api/v1/ping", code=code, msg="err",
        hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
    )


def _realDetector(opener: Callable[..., Any]) -> HomeNetworkDetector:
    config = {
        "pi": {
            "homeNetwork": {
                "ssid": "DeathStarWiFi",
                "subnet": "10.27.27.0/24",
                "pingTimeoutSeconds": 3,
                "serverPingPath": "/api/v1/ping",
            },
            "companionService": {"baseUrl": "http://10.27.27.10:8000"},
        },
    }
    return HomeNetworkDetector(
        config,
        ssidReader=lambda: "DeathStarWiFi",
        ipReader=lambda: ["10.27.27.28"],
        httpOpener=opener,
        apiKey="k",
    )


class TestThroughRealDetector:

    def test_404Probe_failedDrain_probeMisconfigured(self) -> None:
        def opener(_req: Any, timeout: float) -> Any:
            raise _httpError(404)

        detector = _realDetector(opener)
        records: list[SyncOutcomeRecord] = []
        clock = _Clock()

        result = SyncWithServerTask(
            homeState=detector.getHomeNetworkState,
            runSync=_Sync([], [1]),
            writeRecord=records.append,
            ceilingSec=5.0,
            sleepFn=clock.sleep,
            monotonic=clock.monotonic,
            lastProbe=lambda: detector.lastProbe,
        ).run()

        assert result is OutcomeKind.PROBE_MISCONFIGURED
        assert [r.kind for r in records] == [OutcomeKind.PROBE_MISCONFIGURED]

    def test_refusedProbe_failedDrain_atHomeServerDown(self) -> None:
        def opener(_req: Any, timeout: float) -> Any:
            raise urllib.error.URLError("connection refused")

        detector = _realDetector(opener)
        records: list[SyncOutcomeRecord] = []
        clock = _Clock()

        result = SyncWithServerTask(
            homeState=detector.getHomeNetworkState,
            runSync=_Sync([], [1]),
            writeRecord=records.append,
            ceilingSec=5.0,
            sleepFn=clock.sleep,
            monotonic=clock.monotonic,
            lastProbe=lambda: detector.lastProbe,
        ).run()

        assert result is OutcomeKind.AT_HOME_SERVER_DOWN


# =============================================================================
# The record reaches the durable shutdown file US-776-f lands
# =============================================================================


class TestDurableRecord:

    @pytest.mark.parametrize(
        ("state", "items", "expected"),
        [
            (HomeNetworkState.AWAY, [], "AWAY"),
            (HomeNetworkState.AT_HOME_SERVER_REACHABLE, [None], "DELIVERED"),
            (HomeNetworkState.UNKNOWN, [], "UNKNOWN_NETWORK"),
            (HomeNetworkState.AT_HOME_SERVER_DOWN, [], "AT_HOME_SERVER_DOWN"),
        ],
    )
    def test_productionSink_writesSyncOutcomeAndBacklog(
        self, tmp_path: Path, state: HomeNetworkState, items: list, expected: str
    ) -> None:
        """
        Given: the production outcome sink pointed at a temp file
        When: run() ends on each outcome
        Then: the file holds sync_outcome = the outcome NAME and both backlog
            counts -- the keys boot_progress lands as prior_boot_*
        """
        path = tmp_path / "powerwatch_outcome.json"
        backlog = [12]
        clock = _Clock()

        SyncWithServerTask(
            homeState=lambda: state,
            runSync=_Sync(items, backlog),
            writeRecord=m.makeOutcomeSink(str(path)),
            ceilingSec=5.0,
            sleepFn=clock.sleep,
            monotonic=clock.monotonic,
            backlogReader=lambda: backlog[0],
        ).run()

        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["sync_outcome"] == expected
        assert record["kind"] == OutcomeKind[expected].value
        assert record["task"] == "sync_with_server"
        assert record["backlog_start"] == 12
        assert record["backlog_end"] == (0 if expected == "DELIVERED" else 12)

    def test_productionSink_unknownBacklog_keysAbsent(self, tmp_path: Path) -> None:
        """An unknown count is left out of the record, so it lands NULL."""
        path = tmp_path / "powerwatch_outcome.json"

        SyncWithServerTask(
            homeState=lambda: HomeNetworkState.AWAY,
            runSync=lambda: None,
            writeRecord=m.makeOutcomeSink(str(path)),
            ceilingSec=5.0,
        ).run()

        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["sync_outcome"] == "AWAY"
        assert "backlog_start" not in record
        assert "backlog_end" not in record


# =============================================================================
# One summary line per run, at the outcome's level
# =============================================================================


class TestSummaryLine:

    @pytest.mark.parametrize(
        ("state", "items", "level"),
        [
            (HomeNetworkState.AWAY, [], logging.INFO),
            (HomeNetworkState.AT_HOME_SERVER_REACHABLE, [None], logging.INFO),
            (HomeNetworkState.UNKNOWN, [], logging.WARNING),
            (HomeNetworkState.AT_HOME_SERVER_DOWN, [], logging.ERROR),
        ],
    )
    def test_oneOutcomeLine(
        self, caplog: pytest.LogCaptureFixture, state: HomeNetworkState, items: list,
        level: int,
    ) -> None:
        caplog.set_level(logging.DEBUG, logger=_LOGGER)

        _task(state, _Sync(items, [4]), [], backlog=[4]).run()

        lines = [r for r in caplog.records if "outcome=" in r.getMessage()]
        assert len(lines) == 1
        assert lines[0].levelno == level
        assert "backlog_start=4" in lines[0].getMessage()
