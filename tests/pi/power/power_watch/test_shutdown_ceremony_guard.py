################################################################################
# File Name: test_shutdown_ceremony_guard.py
# Purpose/Description: US-796-d -- an empty sync backlog shortens the DRAIN,
#     never the CEREMONY. A shutdown with nothing to send must still shed, make
#     its drain pass, close its drain, write custody, reach CLEAN_COMPLETE and
#     read prior_boot_clean = 1 on the next boot. The guard asserts no display:
#     the grace splash is shed (CIO 2026-09-20). It is proved able to FAIL on a
#     shutdown that reaches poweroff without CLEAN_COMPLETE, and on each other
#     step going missing, so it cannot pass as decoration.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""US-796-d: the shutdown ceremony guard, at an empty sync backlog."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.common.edr.sync_contract import SHUTDOWN_DRAIN_EXCLUDED_TABLES
from src.pi.data import sync_log
from src.pi.diagnostics import boot_progress
from src.pi.obdii.database import ObdDatabase
from src.pi.power.power_watch import __main__ as m
from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.load_shed import DEFAULT_SHED_UNITS, LoadShedder
from src.pi.power.power_watch.pipeline import runPipeline
from src.pi.power.power_watch.sync_custody import (
    OwnDrainCloseSlot,
    makeSyncCustodyHook,
)
from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask
from src.pi.splash.shutdown_state_emitter import makeShutdownPhaseEmitter
from src.pi.sync.backlog import BACKLOG_DELIVERED, countOutstandingRows

_SETTLED_UPTIME_S = 9999.0
_SHUTDOWN_BOOT = "boot-shutting-down"
_NEXT_BOOT = "boot-next"

#: The ceremony, in the order it must happen. Backlog depth changes how long
#: the drain takes and nothing else on this list.
CEREMONY_ORDER = ("shed", "drain", "drain close", "custody", "poweroff")


class _FakeUps:
    def getVcell(self) -> float:
        return 3.47

    def getBatteryPercentage(self) -> int:
        return 5


class _EmptyBacklogSyncClient:
    """forcePush against a backlog that holds nothing: succeeds, moves 0 rows."""

    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.passes = 0

    def forcePush(self, *, excludeTables=()) -> SimpleNamespace:
        self.passes += 1
        self._events.append("drain")
        return SimpleNamespace(disabled=False, tablesFailed=0, rowsPushed=0)


@dataclass
class Observed:
    """What one shutdown left behind, read from the artefacts it wrote."""

    events: list[str] = field(default_factory=list)
    backlogAtLoss: int = -1
    drainPasses: int = 0
    custody: dict[str, Any] | None = None
    trailStages: list[str] = field(default_factory=list)
    priorBootClean: int | None = None


def ceremonyGaps(obs: Observed) -> list[str]:
    """Every mandatory ceremony step the shutdown did not complete, in order.

    Nothing here reads the display: the grace splash is shed, so an animation
    is not part of the ceremony (CIO ruling 2026-09-20).
    """
    gaps: list[str] = []
    stopped = {e.removeprefix("stop:") for e in obs.events if e.startswith("stop:")}
    if not set(DEFAULT_SHED_UNITS) <= stopped:
        gaps.append("shed")
    if obs.drainPasses < 1:
        gaps.append("drain")
    if "drain close" not in obs.events:
        gaps.append("drain close")
    if obs.custody is None or obs.custody.get("verdict") != BACKLOG_DELIVERED:
        gaps.append("custody")
    if "poweroff" not in obs.events:
        gaps.append("poweroff")
    if boot_progress.Stage.CLEAN_COMPLETE.value not in obs.trailStages:
        gaps.append("CLEAN_COMPLETE")
    if obs.priorBootClean != 1:
        gaps.append("prior_boot_clean")
    steps = ["shed" if e.startswith("stop:") else e for e in obs.events]
    firstSeen = [s for i, s in enumerate(steps) if s in CEREMONY_ORDER and s not in steps[:i]]
    if not gaps and firstSeen != list(CEREMONY_ORDER):
        gaps.append(f"order {firstSeen}")
    return gaps


def assertCeremony(obs: Observed) -> None:
    """The guard. Fails naming every missing step."""
    gaps = ceremonyGaps(obs)
    assert not gaps, f"shutdown ceremony incomplete: missing {gaps} (events {obs.events})"


def _makeDb(tmp_path: Path) -> str:
    """A real Pi database with every delta-table cursor past its seed rows."""
    db = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    db.initialize()
    conn = sqlite3.connect(db.dbPath)
    try:
        sync_log.initDb(conn)
        sync_log.ensureSyncModifiedAtSchema(conn)
        existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in sync_log.DELTA_SYNC_TABLES:
            if table not in existing:
                continue
            pk = sync_log.PK_COLUMN[table]
            maxPk = conn.execute(f"SELECT MAX({pk}) FROM {table}").fetchone()[0]
            if maxPk is not None:
                sync_log.updateHighWaterMark(
                    conn, table, int(maxPk), "seed", "ok",
                    lastModifiedAt="9999-12-31T23:59:59Z",
                )
        conn.commit()
    finally:
        conn.close()
    return db.dbPath


def _recorded(name: str, events: list[str], hook):
    def _run() -> None:
        events.append(name)
        hook()

    return _run


def runShutdown(
    tmp_path: Path,
    *,
    finalizerRuns: bool = True,
    wireShed: bool = True,
    drainSkipsOnEmpty: bool = False,
    wirePrePowerOff: bool = True,
) -> Observed:
    """Drive one sustained power loss end to end, wired the way main() wires it.

    Real pieces: ShutdownSequencer, runPipeline, SyncWithServerTask with the
    production multi-pass drain, the production drain-close and custody hooks
    composed by composePrePowerOffHooks, LoadShedder, the shutdown-state
    emitter, and boot_progress --finalize / arm. Faked: systemctl, the network,
    and the UPS gauge. ``powerOffFn`` stands in for ``systemctl poweroff``,
    whose shutdown transaction runs boot-progress-finalize.service's ExecStop.

    The keyword arguments reproduce the defects the guard exists to catch.
    """
    obs = Observed()
    events = obs.events
    dbPath = _makeDb(tmp_path)
    trailPath = str(tmp_path / "boot_progress")
    custodyPath = tmp_path / "sync_custody.json"

    def readSyncBacklog(excludeRows=()):
        return countOutstandingRows(
            dbPath,
            busyTimeoutSec=5.0,
            excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES,
            excludeRows=excludeRows,
        )

    # This boot was armed at startup, exactly as boot-progress-arm.service does.
    boot_progress.arm(
        filePath=trailPath, dbPath=dbPath, bootId=_SHUTDOWN_BOOT,
        nasArchiveDir=str(tmp_path / "nas"), nasArchiveEnabled=False,
        clockQualityProvider=lambda _ts: "ok",
    )
    obs.backlogAtLoss = readSyncBacklog().total

    client = _EmptyBacklogSyncClient(events)
    drain = m._buildRunSync(
        client, backlogReader=readSyncBacklog, excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES,
    )

    def runSync() -> None:
        # The defect variant: "nothing to send" returns before the drain pass.
        if drainSkipsOnEmpty and readSyncBacklog().total <= 0:
            return
        drain()

    syncTask = SyncWithServerTask(
        serverReachable=lambda: True, runSync=runSync, writeRecord=lambda _kd: None,
    )

    slot = OwnDrainCloseSlot()
    drainCloseFn = m.buildDrainCloseHook(
        config={
            "pi": {
                "database": {"path": dbPath},
                "powerWatch": {"perTaskTimeoutSec": 5.0},
                "hardware": {"upsMonitor": {"socColdStartWindowSeconds": 1.0}},
            },
        },
        upsResolver=_FakeUps,
        uptimeReader=lambda: _SETTLED_UPTIME_S,
        ownDrainCloseSlot=slot,
    )
    custodyFn = makeSyncCustodyHook(
        recordPath=str(custodyPath), backlogReader=readSyncBacklog, ownDrainCloseSlot=slot,
    )
    prePowerOffFn = (
        m.composePrePowerOffHooks(
            _recorded("drain close", events, drainCloseFn),
            _recorded("custody", events, custodyFn),
        )
        if wirePrePowerOff
        else None
    )

    shedder = LoadShedder(runner=lambda action, unit: events.append(f"{action}:{unit}"))

    def powerOff() -> None:
        events.append("poweroff")
        if finalizerRuns:
            boot_progress.main(["--finalize", "--file", trailPath, "--boot-id", _SHUTDOWN_BOOT])

    ShutdownSequencer(
        isOnBattery=lambda: True,
        vcell=lambda: 3.9,
        runPipelineFn=lambda: runPipeline(
            m.buildV1Tasks(syncTask),
            perTaskTimeoutSec=5.0,
            sequencerBoundedTasks=(syncTask.name,),
        ),
        powerOffFn=powerOff,
        vcellFloor=3.40,
        drainFloor=3.50,
        totalCapSec=5.0,
        smoothingSec=0.0,
        smoothingPollSec=0.01,
        sleepFn=lambda _s: None,
        phaseEmitFn=makeShutdownPhaseEmitter(str(tmp_path / "states")),
        prePowerOffFn=prePowerOffFn,
        powerLossObservedFn=shedder.shed if wireShed else None,
        powerRestoredFn=shedder.restore,
    ).handleOnBattery()

    obs.drainPasses = client.passes
    if custodyPath.exists():
        obs.custody = json.loads(custodyPath.read_text(encoding="utf-8"))
    obs.trailStages = [r["stage"] for r in boot_progress.readPriorTrail(trailPath)]

    # The next boot classifies this one.
    boot_progress.arm(
        filePath=trailPath, dbPath=dbPath, bootId=_NEXT_BOOT,
        nasArchiveDir=str(tmp_path / "nas"), nasArchiveEnabled=False,
        clockQualityProvider=lambda _ts: "ok",
    )
    conn = sqlite3.connect(dbPath)
    try:
        row = conn.execute(
            "SELECT prior_boot_clean FROM startup_log WHERE boot_id = ?", (_NEXT_BOOT,)
        ).fetchone()
    finally:
        conn.close()
    obs.priorBootClean = None if row is None else row[0]
    return obs


# ================================================================================
# VC-1: an empty backlog still runs the whole ceremony
# ================================================================================


def test_emptyBacklog_reachesCleanComplete_throughTheFullCeremony(tmp_path):
    """
    Given: a sustained power loss with NOTHING outstanding to sync
    When:  the shutdown runs end to end and the next boot classifies it
    Then:  shed -> drain -> drain close -> custody DELIVERED -> poweroff ->
           CLEAN_COMPLETE, and the next boot reads prior_boot_clean = 1
    """
    obs = runShutdown(tmp_path)

    assert obs.backlogAtLoss == 0
    assertCeremony(obs)
    assert obs.custody["outstandingRows"] == 0
    assert obs.trailStages[-1] == boot_progress.Stage.CLEAN_COMPLETE.value


def test_emptyBacklog_isAShorterDrain_notASkippedOne(tmp_path):
    """
    Given: an empty backlog
    When:  the drain runs
    Then:  it makes exactly one pass -- it finds nothing and stops, it is not
           skipped and it does not spin
    """
    obs = runShutdown(tmp_path)

    assert obs.drainPasses == 1


# ================================================================================
# VC-2: the guard FAILS on the defect it exists for
# ================================================================================


def test_guard_failsOnAShutdownThatReachesPoweroffWithoutCleanComplete(tmp_path):
    """
    Given: the same shutdown, except the finalizer never writes CLEAN_COMPLETE
    When:  the guard reads it
    Then:  it fails, naming CLEAN_COMPLETE and prior_boot_clean -- even though
           poweroff was commanded and every earlier step looks done
    """
    obs = runShutdown(tmp_path, finalizerRuns=False)

    assert "poweroff" in obs.events
    assert obs.priorBootClean == 0
    assert ceremonyGaps(obs) == ["CLEAN_COMPLETE", "prior_boot_clean"]
    with pytest.raises(AssertionError, match="CLEAN_COMPLETE"):
        assertCeremony(obs)


@pytest.mark.parametrize(
    ("defect", "missing"),
    [
        ({"drainSkipsOnEmpty": True}, ["drain"]),
        ({"wirePrePowerOff": False}, ["drain close", "custody"]),
        ({"wireShed": False}, ["shed"]),
    ],
    ids=["drain-skipped-on-empty", "hooks-unwired", "no-shed"],
)
def test_guard_failsWhenAnEmptyBacklogSkipsACeremonyStep(tmp_path, defect, missing):
    """
    Given: an empty-backlog shutdown that still reaches poweroff and
           CLEAN_COMPLETE, but skips one mandatory step
    When:  the guard reads it
    Then:  it fails naming exactly that step
    """
    obs = runShutdown(tmp_path, **defect)

    assert "poweroff" in obs.events
    assert ceremonyGaps(obs) == missing
    with pytest.raises(AssertionError):
        assertCeremony(obs)


def test_guard_failsWhenTheShedFollowsTheDrain():
    """
    Given: every step present, but the shed after the drain
    When:  the guard reads it
    Then:  it fails on the order
    """
    obs = Observed(
        events=["drain", *[f"stop:{u}" for u in DEFAULT_SHED_UNITS],
                "drain close", "custody", "poweroff"],
        drainPasses=1,
        custody={"verdict": BACKLOG_DELIVERED},
        trailStages=[boot_progress.Stage.CLEAN_COMPLETE.value],
        priorBootClean=1,
    )

    assert ceremonyGaps(obs) == [f"order {['drain', 'shed', 'drain close', 'custody', 'poweroff']}"]
