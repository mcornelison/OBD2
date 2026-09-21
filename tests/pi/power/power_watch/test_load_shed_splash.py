################################################################################
# File Name: test_load_shed_splash.py
# Purpose/Description: US-796-a -- the power-loss shed stops the grace splash
#     (splash-grace.path AND splash-grace.service), and it runs BEFORE the
#     sequencer writes shutdown-state. splash-grace.path is always armed on that
#     file and cold-starts a second chromium the instant it appears; a .path
#     unit that has already fired cannot be un-fired, so the reverse order is a
#     no-op that looks like a fix in the diff. Correctness, not a survival claim.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""US-796-a: consumer-side suppression of the grace splash at power loss."""

from __future__ import annotations

import re
from pathlib import Path

from src.pi.power.power_watch import load_shed
from src.pi.power.power_watch.__main__ import composePrePowerOffHooks
from src.pi.power.power_watch.controller import (
    PHASE_CANCELLED,
    PHASE_GRACE,
    ShutdownSequencer,
)
from src.pi.power.power_watch.load_shed import (
    DEFAULT_SHED_UNITS,
    TRIGGERED_UNITS,
    LoadShedder,
)
from src.pi.splash.shutdown_state_emitter import (
    SHUTDOWN_STATE_FILENAME,
    makeShutdownPhaseEmitter,
)

SPLASH_PATH = "splash-grace.path"
SPLASH_SERVICE = "splash-grace.service"
CONTROLLER_SOURCE = (
    Path(__file__).resolve().parents[4] / "src" / "pi" / "power" / "power_watch" / "controller.py"
)


class _Recorder:
    """One ordered event log shared by the shed runner and the state writer."""

    def __init__(self, statesDir: Path) -> None:
        self.events: list[tuple[str, str]] = []
        self._emit = makeShutdownPhaseEmitter(str(statesDir))
        self._stateFile = statesDir / SHUTDOWN_STATE_FILENAME

    def runner(self, action: str, unit: str) -> None:
        self.events.append((action, unit))

    def phaseEmit(self, phase: str, **fields: object) -> None:
        # The REAL emitter writes the file splash-grace.path watches; the event
        # is recorded only once the file is actually on disk.
        self._emit(phase, **fields)
        assert self._stateFile.exists()
        self.events.append(("write", phase))


def _shedPrecedesWrite(events: list[tuple[str, str]]) -> bool:
    """True when every shed stop comes before the first shutdown-state write."""
    writes = [i for i, (kind, _) in enumerate(events) if kind == "write"]
    stops = [i for i, (kind, _) in enumerate(events) if kind == "stop"]
    return bool(writes) and bool(stops) and max(stops) < min(writes)


def _sequencer(recorder: _Recorder, shedder: LoadShedder, calls: list[str], **kw):
    """Wired the way __main__.main() wires it: heartbeat + shed composed."""
    base = dict(
        isOnBattery=lambda: True,
        vcell=lambda: 3.9,
        runPipelineFn=lambda: None,
        powerOffFn=lambda: calls.append("poweroff"),
        vcellFloor=3.40,
        totalCapSec=2.0,
        smoothingSec=0.0,
        smoothingPollSec=0.0,
        sleepFn=lambda _s: None,
        phaseEmitFn=recorder.phaseEmit,
        powerLossObservedFn=composePrePowerOffHooks(
            lambda: calls.append("heartbeat"), shedder.shed
        ),
        powerRestoredFn=shedder.restore,
    )
    base.update(kw)
    return ShutdownSequencer(**base)


def test_defaultShedSet_containsBothSplashUnits():
    """
    Given: the default shed set
    When: inspected
    Then: both the path and the service are in it -- stopping only the service
          leaves the path armed to re-launch it
    """
    assert SPLASH_PATH in DEFAULT_SHED_UNITS
    assert SPLASH_SERVICE in DEFAULT_SHED_UNITS
    assert "eclipse-dashboard" in DEFAULT_SHED_UNITS


def test_defaultShedSet_disarmsThePathBeforeStoppingItsService():
    """
    Given: the default shed set
    When: its order is read
    Then: the path is stopped first, so nothing can re-launch the service
    """
    assert DEFAULT_SHED_UNITS.index(SPLASH_PATH) < DEFAULT_SHED_UNITS.index(SPLASH_SERVICE)


def test_powerLoss_everyShedCallPrecedesTheStateWrite(tmp_path):
    """
    Given: a sustained power loss through the real phase emitter
    When: the sequencer handles it
    Then: every shed stop precedes the first shutdown-state write, and the
          shutdown still reaches poweroff
    """
    recorder = _Recorder(tmp_path)
    calls: list[str] = []
    shedder = LoadShedder(runner=recorder.runner)

    _sequencer(recorder, shedder, calls).handleOnBattery()

    stops = [unit for kind, unit in recorder.events if kind == "stop"]
    assert stops == list(DEFAULT_SHED_UNITS)
    assert recorder.events[len(stops)] == ("write", PHASE_GRACE)
    assert _shedPrecedesWrite(recorder.events)
    assert calls == ["heartbeat", "poweroff"]


def test_orderingCheck_rejectsAShedThatFollowsTheWrite():
    """
    Given: the recorded order reversed -- the write first, then the shed
    When: the ordering check reads it
    Then: it fails, so the ordering test above cannot pass vacuously
    """
    reversedEvents = [("write", PHASE_GRACE)] + [("stop", u) for u in DEFAULT_SHED_UNITS]

    assert not _shedPrecedesWrite(reversedEvents)


def test_blipDuringSmoothing_restoresTheShedUnitsAndNeverPowersOff(tmp_path):
    """
    Given: power lost, then back before smoothing resolves
    When: the sequencer handles it
    Then: it cancels, restores the dashboard and re-arms the splash path, and
          commands no poweroff
    """
    recorder = _Recorder(tmp_path)
    calls: list[str] = []
    shedder = LoadShedder(runner=recorder.runner)
    sequencer = _sequencer(
        recorder,
        shedder,
        calls,
        # phase-emit guard read, smoothing entry read, then power is back
        isOnBattery=iter([True, True, False]).__next__,
        smoothingSec=60.0,
    )

    sequencer.handleOnBattery()

    starts = [unit for kind, unit in recorder.events if kind == "start"]
    phases = [unit for kind, unit in recorder.events if kind == "write"]
    assert starts == ["eclipse-dashboard", SPLASH_PATH]
    assert phases == [PHASE_GRACE, PHASE_CANCELLED]
    assert "poweroff" not in calls


def test_restore_neverStartsTheTriggeredSplashService():
    """
    Given: a shed that stopped the splash service (a stop succeeds on an
           inactive unit, so "stopped" does not mean "was running")
    When: power returns
    Then: the service is not started -- its path unit owns its start
    """
    events: list[tuple[str, str]] = []
    shedder = LoadShedder(runner=lambda action, unit: events.append((action, unit)))

    shedder.shed()
    events.clear()
    shedder.restore()

    assert SPLASH_SERVICE in TRIGGERED_UNITS
    assert ("start", SPLASH_SERVICE) not in events
    assert ("start", SPLASH_PATH) in events


def test_systemctlRunner_waitsForAPathStopButNotForAService(monkeypatch):
    """
    Given: the production runner
    When: it stops the splash path and the splash service
    Then: the path stop blocks (a queued stop could lose the race to the state
          write); the service stop keeps --no-block
    """
    argvs: list[list[str]] = []
    monkeypatch.setattr(
        load_shed.subprocess, "run", lambda argv, **_kw: argvs.append(list(argv))
    )

    load_shed.systemctlRunner("stop", SPLASH_PATH)
    load_shed.systemctlRunner("stop", SPLASH_SERVICE)

    assert argvs == [
        ["systemctl", "stop", SPLASH_PATH],
        ["systemctl", "--no-block", "stop", SPLASH_SERVICE],
    ]


def test_sequencerNamesNoSplashUnit():
    """
    Given: the sequencer source
    When: searched for splash unit names
    Then: none -- suppression belongs to the shedder (F-103 decoupling)
    """
    source = CONTROLLER_SOURCE.read_text(encoding="utf-8")

    assert "splash-grace" not in source
    assert not re.search(r"splash[\w-]*\.(path|service)", source)
