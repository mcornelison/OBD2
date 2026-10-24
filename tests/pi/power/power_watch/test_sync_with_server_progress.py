################################################################################
# File Name: test_sync_with_server_progress.py
# Purpose/Description: US-883-b -- the shutdown sync publishes its progress
#                      {waitingAtKeyOff, confirmed} into shutdown-state: the
#                      key-off snapshot at SyncWithServerTask.run start, one
#                      publish after each drain pass (_buildRunSync), written
#                      through the sequencer's one shutdown-state writer.
#                      Away from home (no drain) sync stays null.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-10-23    | Rex (US-883-b) | Initial.
# ================================================================================
################################################################################
"""US-883-b: shutdown sync progress, from the task and drain to shutdown-state."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.common.edr.sync_contract import SHUTDOWN_DRAIN_EXCLUDED_TABLES
from src.pi.data import sync_log
from src.pi.network.home_detector import HomeNetworkState
from src.pi.power.power_watch import __main__ as m
from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask
from src.pi.splash.shutdown_state_emitter import (
    SHUTDOWN_STATE_FILENAME,
    makeShutdownPhaseEmitter,
)
from src.pi.sync.backlog import countOutstandingRows
from src.pi.sync.shutdown_progress import ShutdownSyncProgress


@dataclass
class _Summary:
    """PushSummary stand-in (only the fields _buildRunSync reads)."""

    rowsPushed: int = 0
    tablesFailed: int = 0
    disabled: bool = False


class _AckingClient:
    """A sync client whose each pass acks the next scripted realtime_data mark."""

    def __init__(self, dbPath: str, marks: list[int], summaries: list[_Summary] | None = None):
        self._dbPath = dbPath
        self._marks = list(marks)
        self._summaries = list(summaries or [])
        self.calls = 0

    def forcePush(self, *, excludeTables=()) -> _Summary:
        self.calls += 1
        if self._marks:
            conn = sqlite3.connect(self._dbPath)
            sync_log.updateHighWaterMark(conn, "realtime_data", self._marks.pop(0), "b")
            conn.close()
        if self._summaries:
            return self._summaries.pop(0)
        return _Summary(rowsPushed=1)


def _db(tmp_path: Path, rows: int, mark: int) -> str:
    """A Pi database whose realtime_data holds ``rows`` rows, acked to ``mark``."""
    path = str(tmp_path / "obd.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE realtime_data (id INTEGER PRIMARY KEY AUTOINCREMENT, v REAL)")
    conn.executemany("INSERT INTO realtime_data (id, v) VALUES (?, 0.0)",
                     [(i,) for i in range(1, rows + 1)])
    sync_log.initDb(conn)
    sync_log.updateHighWaterMark(conn, "realtime_data", mark, "b0")
    conn.close()
    return path


def _backlog(dbPath: str):
    return countOutstandingRows(dbPath, excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES)


def _task(*, homeState, runSync, keyOffSnapshotFn=None, backlogReader=None):
    return SyncWithServerTask(
        homeState=lambda: homeState,
        runSync=runSync,
        writeRecord=lambda _r: None,
        joinWaitSec=0.0,
        stallSec=0.0,
        sleepFn=lambda _s: None,
        backlogReader=backlogReader,
        keyOffSnapshotFn=keyOffSnapshotFn,
    )


def _sequencer(statesDir: Path, runPipelineFn, isOnBattery=lambda: True, written=None):
    emit = makeShutdownPhaseEmitter(str(statesDir), nowIsoFn=lambda: "2026-10-23T20:00:00Z")
    target = statesDir / SHUTDOWN_STATE_FILENAME

    def recordingEmit(phase, **kw):
        emit(phase, **kw)
        if written is not None:
            written.append(json.loads(target.read_text(encoding="utf-8")))

    return ShutdownSequencer(
        isOnBattery=isOnBattery,
        vcell=lambda: 3.9,
        runPipelineFn=runPipelineFn,
        powerOffFn=lambda: None,
        vcellFloor=3.40,
        totalCapSec=60.0,
        smoothingSec=0.0,
        smoothingPollSec=0.0,
        sleepFn=lambda _s: None,
        nowIsoFn=lambda: "2026-10-23T20:00:00Z",
        phaseEmitFn=recordingEmit,
    )


# --------------------------------------------------------------------------- #
# The snapshot point: SyncWithServerTask.run start
# --------------------------------------------------------------------------- #


def test_run_snapshotsOnce_beforeAnyPass() -> None:
    """
    Given: a task at home with a snapshot hook
    When:  run() drains
    Then:  the snapshot is taken once, before the first runSync pass
    """
    calls: list[str] = []
    task = _task(
        homeState=HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        runSync=lambda: calls.append("pass"),
        keyOffSnapshotFn=lambda: calls.append("snapshot"),
    )

    task.run()

    assert calls == ["snapshot", "pass"]


def test_run_aRaisingSnapshot_neverStopsTheDrain() -> None:
    """A snapshot hook that raises is logged; the drain still runs."""
    passes: list[int] = []

    def _boom() -> None:
        raise RuntimeError("db locked")

    task = _task(
        homeState=HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        runSync=lambda: passes.append(1),
        keyOffSnapshotFn=_boom,
    )

    task.run()

    assert passes == [1]


# --------------------------------------------------------------------------- #
# The emit point: after each runSync pass
# --------------------------------------------------------------------------- #


def test_buildRunSync_callsThePassHookAfterEveryPass(tmp_path: Path) -> None:
    """Three passes -> three publishes, each after its pass's ack."""
    dbPath = _db(tmp_path, rows=30, mark=0)
    client = _AckingClient(dbPath, [10, 20, 30])
    seen: list[int] = []
    runSync = m._buildRunSync(  # noqa: SLF001
        client,
        backlogReader=lambda: _backlog(dbPath),
        passDoneFn=lambda: seen.append(_backlog(dbPath).total),
    )

    runSync()

    assert client.calls == 3
    assert seen == [20, 10, 0]


def test_buildRunSync_aFailedPassStillPublishes_thenRaises(tmp_path: Path) -> None:
    """A pass with a failed table may have acked others: it publishes, then the
    transient failure is raised for the task's retry."""
    seen: list[str] = []
    client = _AckingClient(str(tmp_path / "x.db"), [], [_Summary(tablesFailed=1)])
    runSync = m._buildRunSync(client, passDoneFn=lambda: seen.append("pass"))  # noqa: SLF001

    try:
        runSync()
    except RuntimeError:
        pass

    assert seen == ["pass"]


def test_buildRunSync_disabledService_publishesNothing(tmp_path: Path) -> None:
    """A disabled companion service is no drain: no publish."""
    seen: list[str] = []
    client = _AckingClient(str(tmp_path / "x.db"), [], [_Summary(disabled=True)])
    runSync = m._buildRunSync(client, passDoneFn=lambda: seen.append("pass"))  # noqa: SLF001

    runSync()

    assert seen == []


def test_buildRunSync_aRaisingPassHook_neverEndsTheDrain(tmp_path: Path) -> None:
    """A pass hook that raises is ignored; the drain keeps passing."""
    dbPath = _db(tmp_path, rows=20, mark=0)
    client = _AckingClient(dbPath, [10, 20])

    def _boom() -> None:
        raise RuntimeError("writer down")

    runSync = m._buildRunSync(  # noqa: SLF001
        client, backlogReader=lambda: _backlog(dbPath), passDoneFn=_boom,
    )

    runSync()

    assert client.calls == 2


# --------------------------------------------------------------------------- #
# End to end into the shutdown-state file
# --------------------------------------------------------------------------- #


def test_homeDrain_publishesConfirmedFromTheAckedMarks(tmp_path: Path) -> None:
    """
    Given: key-off at home, realtime_data mark 5000, max 5400 (the story example)
    When:  pass 1 acks to 5250, pass 2 re-sends 5201-5250 then acks to 5400
    Then:  shutdown-state carries sync 400/250 then 400/400, through the one
           writer, in phase flushing with the step unchanged
    """
    dbPath = _db(tmp_path, rows=5400, mark=5000)
    statesDir = tmp_path / "states"
    written: list[dict] = []
    progress = ShutdownSyncProgress(
        dbPath, busyTimeoutSec=1.0, publishFn=lambda s: seq.publishSync(s),
    )
    client = _AckingClient(dbPath, [5250, 5400])
    task = _task(
        homeState=HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        runSync=m._buildRunSync(  # noqa: SLF001
            client, backlogReader=lambda: _backlog(dbPath), passDoneFn=progress.publish,
        ),
        keyOffSnapshotFn=progress.snapshot,
        backlogReader=lambda: _backlog(dbPath).total,
    )
    seq = _sequencer(statesDir, runPipelineFn=task.run, written=written)

    seq.handleOnBattery()

    syncs = [w["sync"] for w in written if w["sync"] is not None]
    assert syncs[:2] == [
        {"waitingAtKeyOff": 400, "confirmed": 250},
        {"waitingAtKeyOff": 400, "confirmed": 400},
    ]
    progressWrites = [w for w in written if w["sync"] is not None and w["phase"] == "flushing"]
    assert len(progressWrites) == 2
    assert all(w["step"] == {"index": 2, "of": 5, "name": "drain"} for w in progressWrites)
    assert written[0]["phase"] == "grace" and written[0]["sync"] is None


def test_awayPath_keepsSyncNull(tmp_path: Path) -> None:
    """Away from home no drain pass runs: sync is null in every write."""
    dbPath = _db(tmp_path, rows=50, mark=0)
    statesDir = tmp_path / "states"
    written: list[dict] = []
    progress = ShutdownSyncProgress(
        dbPath, busyTimeoutSec=1.0, publishFn=lambda s: seq.publishSync(s),
    )
    client = _AckingClient(dbPath, [50])
    task = _task(
        homeState=HomeNetworkState.AWAY,
        runSync=m._buildRunSync(client, passDoneFn=progress.publish),  # noqa: SLF001
        keyOffSnapshotFn=progress.snapshot,
    )
    seq = _sequencer(statesDir, runPipelineFn=task.run, written=written)

    seq.handleOnBattery()

    assert client.calls == 0
    assert written and all(w["sync"] is None for w in written)
    assert written[-1]["phase"] == "powering_off"


# --------------------------------------------------------------------------- #
# The sequencer seam
# --------------------------------------------------------------------------- #


def test_publishSync_outsideFlushingOrPoweringOff_writesNothing(tmp_path: Path) -> None:
    """Before any phase, or after a cancel, a late pass publishes nothing."""
    written: list[dict] = []
    seq = _sequencer(tmp_path / "states", runPipelineFn=lambda: None, written=written)

    seq.publishSync({"waitingAtKeyOff": 3, "confirmed": 1})
    assert written == []

    seq._emitPhase("cancelled")  # noqa: SLF001 -- the cancel write
    seq.publishSync({"waitingAtKeyOff": 3, "confirmed": 2})

    assert [w["phase"] for w in written] == ["cancelled"]
    assert written[0]["sync"] is None


def test_cancelAfterAPass_clearsSync(tmp_path: Path) -> None:
    """Power returning mid-drain writes cancelled with sync null, and a new loss
    starts with sync null at grace."""
    dbPath = _db(tmp_path, rows=10, mark=0)
    written: list[dict] = []
    published: list[dict] = []

    def _publish(sync: dict) -> None:
        seq.publishSync(sync)
        published.append(sync)

    progress = ShutdownSyncProgress(dbPath, busyTimeoutSec=1.0, publishFn=_publish)
    client = _AckingClient(dbPath, [5], [_Summary(rowsPushed=5), _Summary(rowsPushed=0)])
    task = _task(
        homeState=HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        runSync=m._buildRunSync(  # noqa: SLF001
            client, backlogReader=lambda: _backlog(dbPath), passDoneFn=progress.publish,
        ),
        keyOffSnapshotFn=progress.snapshot,
    )
    seq = _sequencer(
        tmp_path / "states",
        runPipelineFn=task.run,
        # Power returns once the first pass has published -- never before it.
        isOnBattery=lambda: not published,
        written=written,
    )

    seq.handleOnBattery()

    assert {"waitingAtKeyOff": 10, "confirmed": 5} in [w["sync"] for w in written]
    assert written[-1]["phase"] == "cancelled"
    assert written[-1]["sync"] is None
