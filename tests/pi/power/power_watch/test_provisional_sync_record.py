################################################################################
# File Name: test_provisional_sync_record.py
# Purpose/Description: US-833 -- no poweroff leaves the shutdown-sync record
#                      silent. The sync task writes a PROVISIONAL `INTERRUPTED`
#                      record (backlog_start, then sync_started_at) through its
#                      own seam before it can be cut off; the final outcome
#                      overwrites it. A floor-ended drain's RESERVE_FLOOR carries
#                      the provisional's backlog_start / sync_started_at
#                      forward, and the backstop fast path (no pipeline at all)
#                      records INTERRUPTED with a backlog count.
# Author: Atlas (architect)
# Creation Date: 2026-10-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-05    | Atlas        | US-833 (CIO-directed build, charter override):
#                               Atlas ruling 2026-10-01 -- silence must not be
#                               the floor's signature.
# ================================================================================
################################################################################
"""US-833: every poweroff path leaves a shutdown-sync record that can testify."""

from __future__ import annotations

import ast
import inspect
import json
import threading
from pathlib import Path
from typing import Any

import src.pi.power.power_watch.__main__ as m
from src.pi.network.home_detector import HomeNetworkState
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.tasks.sync_with_server import (
    SyncOutcomeRecord,
    SyncWithServerTask,
)

_HOME = HomeNetworkState.AT_HOME_SERVER_REACHABLE


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _task(
    state: HomeNetworkState,
    records: list[SyncOutcomeRecord],
    provisional: list[SyncOutcomeRecord] | None,
    *,
    runSync: Any = None,
    backlog: list[int] | None = None,
) -> SyncWithServerTask:
    """A task whose drain succeeds on the first attempt unless runSync says otherwise.

    The default sync EMPTIES the backlog, as a real drain does: the task runs to
    completion, and with the fake clock frozen a backlog that never falls would
    never stall either -- the loop would not end.
    """
    if runSync is None:
        def runSync() -> None:
            if backlog is not None:
                backlog[0] = 0
    return SyncWithServerTask(
        homeState=lambda: state,
        runSync=runSync,
        writeRecord=records.append,
        writeProvisional=provisional.append if provisional is not None else None,
        joinWaitSec=120.0,
        stallSec=10.0,
        sleepFn=lambda _s: None,
        monotonic=lambda: 0.0,
        backlogReader=(lambda: backlog[0]) if backlog is not None else None,
        nowIsoFn=lambda: "2026-10-05T12:00:00Z",
    )


# =============================================================================
# The contract
# =============================================================================


def test_interruptedIsAnOutcomeKind() -> None:
    """INTERRUPTED: the shutdown sync did not reach its end."""
    assert OutcomeKind.INTERRUPTED.value == "interrupted"


# =============================================================================
# The sync task's provisional seam
# =============================================================================


class TestTaskWritesProvisionalBeforeItCanBeCut:

    def test_drain_provisionalAtRunStartThenAtDrainStart_thenOneFinal(self) -> None:
        """
        Given: at home, 412 rows owed, a drain that delivers
        When: run()
        Then: two provisional INTERRUPTED records (run start: backlog only;
              drain start: + sync_started_at), then exactly ONE final record
              (the US-776-d one-record-per-run contract is unchanged)
        """
        records: list[SyncOutcomeRecord] = []
        provisional: list[SyncOutcomeRecord] = []
        backlog = [412]

        def drain() -> None:
            backlog[0] = 0

        result = _task(_HOME, records, provisional, runSync=drain, backlog=backlog).run()

        assert result is OutcomeKind.DELIVERED
        assert [p.kind for p in provisional] == [OutcomeKind.INTERRUPTED] * 2
        assert (provisional[0].backlogStart, provisional[0].startedAt) == (412, None)
        assert (provisional[1].backlogStart, provisional[1].startedAt) == (
            412, "2026-10-05T12:00:00Z",
        )
        assert all(p.backlogEnd is None and p.endedAt is None for p in provisional)
        assert len(records) == 1 and records[0].kind is OutcomeKind.DELIVERED

    def test_away_oneProvisional_noDrainStartProvisional(self) -> None:
        """AWAY skips the drain, so only the run-start provisional is written."""
        records: list[SyncOutcomeRecord] = []
        provisional: list[SyncOutcomeRecord] = []

        _task(HomeNetworkState.AWAY, records, provisional, backlog=[7]).run()

        assert [p.startedAt for p in provisional] == [None]
        assert [r.kind for r in records] == [OutcomeKind.AWAY]

    def test_provisionalNeverSetsLastOutcome(self) -> None:
        """
        Given: a provisional writer that looks at the task while it is called
        When: run()
        Then: lastOutcome is still None at every provisional write -- the hold
              task reads lastOutcome and must never see INTERRUPTED
        """
        records: list[SyncOutcomeRecord] = []
        seen: list[object] = []
        task = _task(_HOME, records, None, backlog=[3])
        task._writeProvisional = lambda _rec: seen.append(task.lastOutcome)

        task.run()

        assert seen == [None, None]
        assert task.lastOutcome is OutcomeKind.DELIVERED

    def test_provisionalWriterRaises_runStillCompletesAndRecords(self) -> None:
        """A failing provisional write never stops the drain or the final record."""
        records: list[SyncOutcomeRecord] = []
        task = _task(_HOME, records, None, backlog=[3])

        def boom(_rec: SyncOutcomeRecord) -> None:
            raise OSError("disk full")

        task._writeProvisional = boom

        assert task.run() is OutcomeKind.DELIVERED
        assert [r.kind for r in records] == [OutcomeKind.DELIVERED]

    def test_noProvisionalWriter_isTodaysBehaviour(self) -> None:
        """writeProvisional is optional; without it run() is unchanged."""
        records: list[SyncOutcomeRecord] = []

        assert _task(_HOME, records, None, backlog=[3]).run() is OutcomeKind.DELIVERED
        assert len(records) == 1


# =============================================================================
# End to end: the durable file, through HomeStateAtLoss, a real sequencer
# =============================================================================


def _holder(path: Path, *, backlog: int | None = 55) -> m.HomeStateAtLoss:
    return m.HomeStateAtLoss(
        lambda: _HOME,
        outcomePath=str(path),
        startFn=lambda fn: fn(),
        vcellBeforeCut=lambda: 4.10,
        backlogReader=(lambda: backlog) if backlog is not None else None,
    )


def _wiredTask(holder: m.HomeStateAtLoss, path: Path, runSync: Any) -> SyncWithServerTask:
    """The sync task wired the way main() wires it: ONE serialised sink for both
    seams. ``runSync`` runs, then the backlog empties (a delivered drain)."""
    syncRecordSink = holder.wrapSink(m.makeOutcomeSink(
        str(path), homeState=holder.stateName, wallVcell=holder.vcellBeforeCut,
        lossAt=holder.lossIso,
    ))
    backlog = [412]

    def drain() -> None:
        runSync()
        backlog[0] = 0

    return SyncWithServerTask(
        homeState=holder.stateForSync,
        runSync=drain,
        writeRecord=syncRecordSink,
        writeProvisional=syncRecordSink,
        joinWaitSec=120.0,
        stallSec=60.0,
        sleepFn=lambda _s: None,
        monotonic=lambda: 0.0,
        backlogReader=lambda: backlog[0],
        nowIsoFn=lambda: "2026-10-05T12:00:00Z",
        lossGeneration=holder.lossGeneration,
    )


def test_cutMidDrain_theFileAlreadySaysInterrupted(tmp_path: Path) -> None:
    """
    Given: a drain in flight (the moment a hard cut would land)
    When: the durable file is read DURING the drain
    Then: it says INTERRUPTED with backlog_start and sync_started_at, and no
          sync_ended_at -- what the next boot lands if the power dies now.
          Afterwards the final outcome overwrites it.
    """
    path = tmp_path / "powerwatch_outcome.json"
    holder = _holder(path)
    duringDrain: list[dict[str, Any]] = []
    task = _wiredTask(holder, path, runSync=lambda: duringDrain.append(_read(path)))
    holder.observe()

    task.run()

    mid = duringDrain[0]
    assert mid["sync_outcome"] == "INTERRUPTED"
    assert mid["kind"] == "interrupted"
    assert mid["backlog_start"] == 412
    assert mid["sync_started_at"] == "2026-10-05T12:00:00Z"
    assert "sync_ended_at" not in mid
    assert mid["home_state"] == _HOME.name
    assert _read(path)["sync_outcome"] != "INTERRUPTED"  # the final overwrote it


def test_floorEndedDrain_reserveFloorCarriesTheProvisionalForward(tmp_path: Path) -> None:
    """
    Given: the provisional records were written, then the reserve floor ends the drain
    When: the floor-end hook records RESERVE_FLOOR
    Then: the record keeps backlog_start and sync_started_at (prior_boot_sync_*
          non-NULL), and the abandoned sync thread's late record is dropped
    """
    path = tmp_path / "powerwatch_outcome.json"
    holder = _holder(path)
    sink = holder.wrapSink(m.makeOutcomeSink(str(path), homeState=holder.stateName))
    holder.observe()
    gen = holder.lossGeneration()
    sink(SyncOutcomeRecord(OutcomeKind.INTERRUPTED, "provisional", 412, None,
                           "2026-10-05T12:00:00Z", None, gen))

    holder.recordFloorEnd()
    sink(SyncOutcomeRecord(OutcomeKind.STALLED, "late", 412, 300,
                           "2026-10-05T12:00:00Z", "2026-10-05T12:09:00Z", gen))

    rec = _read(path)
    assert rec["sync_outcome"] == "RESERVE_FLOOR"
    assert rec["backlog_start"] == 412
    assert rec["sync_started_at"] == "2026-10-05T12:00:00Z"
    assert "sync_ended_at" not in rec


def test_floorEndedBeforeAnySyncRecord_readsTheBacklogItself(tmp_path: Path) -> None:
    """A floor end with no provisional yet still records a backlog count."""
    path = tmp_path / "powerwatch_outcome.json"
    holder = _holder(path, backlog=55)
    holder.observe()

    holder.recordFloorEnd()

    rec = _read(path)
    assert rec["sync_outcome"] == "RESERVE_FLOOR"
    assert rec["backlog_start"] == 55
    assert "sync_started_at" not in rec


def test_backstopFastPath_recordsInterrupted_withBacklogAndHomeState(tmp_path: Path) -> None:
    """
    Given: VCELL already at/below the backstop floor at confirmation, so the
           sequencer skips the pipeline (no sync ever runs)
    When: the loss powers off
    Then: the record says INTERRUPTED (the shutdown sync never reached its end)
          with the backlog it left behind and the home state -- not silence.
          It is NOT RESERVE_FLOOR: the finaliser would stamp an at-home
          RESERVE_FLOOR `replace`, and no drain was measured here.
    """
    path = tmp_path / "powerwatch_outcome.json"
    holder = _holder(path, backlog=55)
    offs: list[str] = []
    seq = ShutdownSequencer(
        isOnBattery=lambda: True, vcell=lambda: 3.00,
        runPipelineFn=lambda: offs.append("pipeline-ran"),
        powerOffFn=lambda: offs.append("poweroff"), vcellFloor=3.30, totalCapSec=45.0,
        smoothingSec=0.0, smoothingPollSec=0.0, sleepFn=lambda _s: None,
        prePowerOffFn=m.composePrePowerOffHooks(
            m.buildFloorEndHook(lambda: seq.lastDrainEndReason, holder),
            holder.ensureRecorded,
        ),
        powerLossObservedFn=holder.observe,
    )

    seq.handleOnBattery()

    rec = _read(path)
    assert offs == ["poweroff"]
    assert rec["sync_outcome"] == "INTERRUPTED"
    assert rec["backlog_start"] == 55
    assert rec["home_state"] == _HOME.name
    assert "sync_started_at" not in rec


def test_ensureRecorded_doesNotOverwriteASyncRecord(tmp_path: Path) -> None:
    """A loss whose sync already recorded (final or provisional) is left alone."""
    path = tmp_path / "powerwatch_outcome.json"
    holder = _holder(path)
    sink = holder.wrapSink(m.makeOutcomeSink(str(path), homeState=holder.stateName))
    holder.observe()
    sink(SyncOutcomeRecord(OutcomeKind.DELIVERED, "done", 412, 0,
                           "2026-10-05T12:00:00Z", "2026-10-05T12:00:09Z",
                           holder.lossGeneration()))

    holder.ensureRecorded()

    assert _read(path)["sync_outcome"] == "DELIVERED"


def test_backlogReaderRaises_stillRecordsInterrupted(tmp_path: Path) -> None:
    """An unreadable backlog lands NULL; the record and the poweroff still happen."""
    path = tmp_path / "powerwatch_outcome.json"

    def boom() -> int:
        raise OSError("database locked")

    holder = m.HomeStateAtLoss(
        lambda: _HOME, outcomePath=str(path), startFn=lambda fn: fn(), backlogReader=boom,
    )
    holder.observe()

    holder.ensureRecorded()

    rec = _read(path)
    assert rec["sync_outcome"] == "INTERRUPTED"
    assert "backlog_start" not in rec


def test_lateDetectorAnswer_doesNotOverwriteInterrupted(tmp_path: Path) -> None:
    """The fast path's INTERRUPTED stands even if the detector answers afterwards."""
    path = tmp_path / "powerwatch_outcome.json"
    release = threading.Event()
    threads: list[threading.Thread] = []

    def slow() -> HomeNetworkState:
        release.wait(timeout=10.0)
        return _HOME

    def startFn(target: Any) -> None:
        th = threading.Thread(target=target, daemon=True)
        threads.append(th)
        th.start()

    holder = m.HomeStateAtLoss(slow, outcomePath=str(path), startFn=startFn)
    holder.observe()
    holder.ensureRecorded()
    release.set()
    threads[0].join(timeout=5.0)

    rec = _read(path)
    assert rec["sync_outcome"] == "INTERRUPTED"
    assert rec["home_state"] == "UNKNOWN"


# =============================================================================
# Production wiring
# =============================================================================


def test_main_wiresTheProvisionalSeamAndTheBacklogReader() -> None:
    """main() hands the task a provisional seam through the holder, and the
    holder the same backlog reader the task uses."""
    tree = ast.parse(inspect.getsource(m.main))
    calls = {
        ast.unparse(node.func): {kw.arg: ast.unparse(kw.value) for kw in node.keywords}
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and ast.unparse(node.func) in ("SyncWithServerTask", "HomeStateAtLoss")
    }
    task = calls["SyncWithServerTask"]
    holder = calls["HomeStateAtLoss"]
    # One serialised sink for the final AND the provisional records (one file).
    assert task["writeProvisional"] == task["writeRecord"] == "syncRecordSink"
    sinkAssignments = [
        ast.unparse(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "syncRecordSink" for t in node.targets)
    ]
    assert len(sinkAssignments) == 1
    assert sinkAssignments[0].startswith("homeStateAtLoss.wrapSink(makeOutcomeSink(")
    assert holder["backlogReader"] == task["backlogReader"]
