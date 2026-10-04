################################################################################
# File Name: test_load_shed_splash.py
# Purpose/Description: US-796 -- the power-loss shed leaves the grace splash
#     alone. US-796-a put splash-grace.path and splash-grace.service on the shed
#     list; the stop failed on every cut ("could not stop splash-grace.service")
#     and, had it succeeded, would have removed the shutdown animation the CIO
#     ruled to keep. The dashboard is still shed (ARCH-031), and still before
#     the sequencer writes shutdown-state.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-21    | Rex          | US-796-a: shed stops both splash units.
# 2026-09-30    | Rex          | US-796: inverted -- no splash unit is shed or
#                                treated as triggered; the dashboard still is.
# ================================================================================
################################################################################
"""US-796: the grace splash is not part of the power-loss shed."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

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

DASHBOARD = "eclipse-dashboard"
SPLASH_PATTERN = re.compile(r"splash-grace")
_POWER_WATCH = Path(__file__).resolve().parents[4] / "src" / "pi" / "power" / "power_watch"
CONTROLLER_SOURCE = _POWER_WATCH / "controller.py"
LOAD_SHED_SOURCE = _POWER_WATCH / "load_shed.py"


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


def _splashUnits(units) -> list[str]:
    return [unit for unit in units if SPLASH_PATTERN.search(unit)]


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


def test_shedLists_holdNoSplashUnit_andStillHoldTheDashboard():
    """
    Given: the default shed set and the triggered set
    When: inspected
    Then: neither names a splash-grace unit, and the dashboard is still shed
          (ARCH-031)
    """
    assert _splashUnits(DEFAULT_SHED_UNITS) == []
    assert _splashUnits(TRIGGERED_UNITS) == []
    assert DASHBOARD in DEFAULT_SHED_UNITS


@pytest.mark.parametrize("splashUnit", ["splash-grace.path", "splash-grace.service"])
def test_splashCheck_catchesASplashUnitAddedBack(splashUnit):
    """
    Given: a shed set with a splash-grace unit added back
    When: the same check the list test uses reads it
    Then: it reports the unit, so the list test cannot pass vacuously
    """
    assert _splashUnits((*DEFAULT_SHED_UNITS, splashUnit)) == [splashUnit]
    assert _splashUnits(frozenset({splashUnit})) == [splashUnit]


def test_loadShedSource_namesSplashOnlyInProse():
    """
    Given: load_shed.py
    When: its code (docstrings and comments stripped) is searched
    Then: no string literal names a splash-grace unit -- any mention left is
          the prose explaining why it is excluded
    """
    tree = ast.parse(LOAD_SHED_SOURCE.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]

    assert _splashUnits(literals) == []


def test_loadShedDocstring_noLongerClaimsTheShedSuppressesTheSplash():
    """
    Given: the load_shed module docstring
    When: read
    Then: it does not claim the shed stops / suppresses the grace splash
    """
    # Collapse the docstring's line wrapping, or a phrase split across two
    # lines slips past every check below.
    doc = " ".join((load_shed.__doc__ or "").split())

    assert "the shed stops both" not in doc
    assert "Suppression lives here" not in doc
    assert not re.search(r"suppress\w*\s+(the\s+)?(grace\s+)?splash", doc, re.IGNORECASE)


def test_powerLoss_shedsOnlyTheDashboard_beforeTheStateWrite(tmp_path):
    """
    Given: a sustained power loss through the real phase emitter
    When: the sequencer handles it
    Then: the dashboard is stopped before the first shutdown-state write, no
          splash unit is touched, and the shutdown still reaches poweroff
    """
    recorder = _Recorder(tmp_path)
    calls: list[str] = []
    shedder = LoadShedder(runner=recorder.runner)

    _sequencer(recorder, shedder, calls).handleOnBattery()

    stops = [unit for kind, unit in recorder.events if kind == "stop"]
    assert stops == list(DEFAULT_SHED_UNITS)
    assert _splashUnits(unit for _, unit in recorder.events) == []
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


def test_blipDuringSmoothing_restoresTheDashboardAndNeverPowersOff(tmp_path):
    """
    Given: power lost, then back before smoothing resolves
    When: the sequencer handles it
    Then: it cancels, restores the dashboard (and nothing else), and commands
          no poweroff
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
    assert starts == [DASHBOARD]
    assert phases == [PHASE_GRACE, PHASE_CANCELLED]
    assert "poweroff" not in calls


def test_restore_neverStartsATriggeredUnit():
    """
    Given: a shedder told one of its units is started by a trigger
    When: it sheds, then power returns
    Then: that unit is stopped but not started -- its trigger owns its start
    """
    events: list[tuple[str, str]] = []
    shedder = LoadShedder(
        units=(DASHBOARD, "triggered.service"),
        runner=lambda action, unit: events.append((action, unit)),
        triggeredUnits={"triggered.service"},
    )

    shedder.shed()
    events.clear()
    shedder.restore()

    assert events == [("start", DASHBOARD)]


def test_systemctlRunner_waitsForAPathStopButNotForAService(monkeypatch):
    """
    Given: the production runner
    When: it stops a path unit and a service
    Then: the path stop blocks; the service stop keeps --no-block
    """
    argvs: list[list[str]] = []
    monkeypatch.setattr(
        load_shed.subprocess, "run", lambda argv, **_kw: argvs.append(list(argv))
    )

    load_shed.systemctlRunner("stop", "some.path")
    load_shed.systemctlRunner("stop", DASHBOARD)

    assert argvs == [
        ["systemctl", "stop", "some.path"],
        ["systemctl", "--no-block", "stop", DASHBOARD],
    ]


def test_sequencerNamesNoSplashUnit():
    """
    Given: the sequencer source
    When: searched for splash unit names
    Then: none -- the sequencer never learns a splash unit (F-103 decoupling)
    """
    source = CONTROLLER_SOURCE.read_text(encoding="utf-8")

    assert "splash-grace" not in source
    assert not re.search(r"splash[\w-]*\.(path|service)", source)
