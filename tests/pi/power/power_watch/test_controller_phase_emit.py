################################################################################
# File Name: test_controller_phase_emit.py
# Purpose/Description: Tests for the ShutdownSequencer phase-emit hook [Atlas
#   A-2, US-394]. The sequencer emits a shutdown-state phase event at each
#   code-path transition (grace -> cancelled | flushing -> powering_off) via a
#   GENERIC injected callable -- the sequencer never imports the splash module
#   (spec §6 unidirectional dependency). When no emitter is wired the sequencer
#   behaves byte-identically to today (the older test_controller.py cases assert
#   that). Constraints under test: (a) grace fires at T=0 BEFORE smoothing
#   resolves; (b) emission happens AFTER each transition is decided; (c) an
#   emit-callable that raises NEVER blocks the shutdown progression.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Ralph (Rex)  | Initial implementation (US-394 F-103 shutdown splash)
# 2026-10-23    | Rex (US-883-a) | Step publish: a step transition re-writes the
#                               current phase, so the phase pins compare phase
#                               TRANSITIONS; new step {index, of, name} cases.
# ================================================================================
################################################################################

"""Tests for the ShutdownSequencer phase-emit hook (US-394)."""

import threading

import pytest

from src.pi.power.power_watch import __main__ as m
from src.pi.power.power_watch.ceremony import (
    CEREMONY_ORDER,
    STEP_CUSTODY,
    STEP_DRAIN_CLOSE,
    STEP_MONTHLY_TEST_HOLD,
    CeremonyProgress,
    ceremonySteps,
)
from src.pi.power.power_watch.controller import ShutdownSequencer


def _recordingEmitter():
    """Return (emitFn, events) where events captures (phase, kwargs) per call."""
    events: list[tuple] = []

    def emit(phase, **kw):
        events.append((phase, kw))

    return emit, events


def _seq(events_emit=None, **kw):
    base = dict(
        isOnBattery=lambda: True,
        vcell=lambda: 3.9,
        runPipelineFn=lambda: None,
        powerOffFn=lambda: None,
        vcellFloor=3.40,
        totalCapSec=2.0,
        smoothingSec=0.0,
        smoothingPollSec=0.0,
        sleepFn=lambda _s: None,
        nowIsoFn=lambda: "2026-06-29T19:50:00Z",
    )
    if events_emit is not None:
        base["phaseEmitFn"] = events_emit
    base.update(kw)
    return ShutdownSequencer(**base)


def _transitions(phases):
    """The phase sequence with repeats collapsed: a step write keeps its phase."""
    return [p for i, p in enumerate(phases) if i == 0 or phases[i - 1] != p]


def test_sustainedLoss_emitsGrace_thenFlushing_thenPoweringOff():
    """A real sustained loss walks grace -> flushing -> powering_off in order,
    and powers off."""
    emit, events = _recordingEmitter()
    calls = []
    seq = _seq(
        events_emit=emit,
        isOnBattery=lambda: True,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
    )
    seq.handleOnBattery()

    phases = [p for p, _ in events]
    assert _transitions(phases) == ["grace", "flushing", "powering_off"]
    assert calls == ["pipeline", "poweroff"]
    # powering_off is emitted BEFORE the actual poweroff call (constraint b).
    assert events[-1][0] == "powering_off"


def test_grace_emittedAtT0_beforeSmoothingResolves():
    """grace must be written the instant the power-LOST signal arrives, BEFORE
    the smoothing window confirms -- so the splash triggers at T=0 and the
    animation IS the grace countdown. The grace payload carries the full
    smoothing budget as tRemainingS."""
    emit, events = _recordingEmitter()
    # grace-start=0, grace-remaining=0, deadline base=0 (=>deadline 7), then the
    # smoothing while-check reads 100 (>=7) so smoothing confirms immediately;
    # exhaustion falls back to 100.0 (no StopIteration on later remaining reads).
    clock = iter([0.0, 0.0, 0.0, 100.0])
    seq = _seq(
        events_emit=emit,
        isOnBattery=lambda: True,
        smoothingSec=7.0,
        smoothingPollSec=0.0,
        monotonicFn=lambda: next(clock, 100.0),
    )
    seq.handleOnBattery()

    assert events[0][0] == "grace"
    graceKw = events[0][1]
    assert graceKw["tGraceTotalS"] == 7.0
    assert graceKw["tGraceStartedAtIso"] == "2026-06-29T19:50:00Z"
    # At grace-emit time, ~all of the window remains.
    assert graceKw["tRemainingS"] == 7.0
    assert graceKw["reason"] == "ignition_off"


def test_transientBlip_emitsGrace_thenCancelled_noPoweroff():
    """A blip that fails smoothing emits grace (splash triggered) then cancelled
    (splash aborts) and NEVER powers off."""
    emit, events = _recordingEmitter()
    calls = []
    # entry isOnBattery=True (grace), then _smoothedPowerLost reads False (blip).
    seq = _seq(
        events_emit=emit,
        isOnBattery=iter([True, False]).__next__,
        smoothingSec=5.0,
        powerOffFn=lambda: calls.append("poweroff"),
    )
    seq.handleOnBattery()

    phases = [p for p, _ in events]
    assert phases == ["grace", "cancelled"]
    assert calls == []  # never powered off


def test_vcellFloor_fastPath_emitsGrace_thenPoweringOff_noFlushing():
    """The VCELL-floor backstop skips the pipeline, so it emits powering_off
    WITHOUT a flushing phase (honest instrument -- no flush happened)."""
    emit, events = _recordingEmitter()
    calls = []
    seq = _seq(
        events_emit=emit,
        isOnBattery=lambda: True,
        vcell=lambda: 3.30,  # successful low read -> floor short-circuit
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
    )
    seq.handleOnBattery()

    phases = [p for p, _ in events]
    assert _transitions(phases) == ["grace", "powering_off"]
    assert calls == ["poweroff"]  # pipeline skipped


def test_powerReturnsDuringWindow_emitsCancelled_noPoweroff():
    """Power returning during the bounded pipeline window aborts the poweroff;
    the splash is told via a late cancelled emit so it does not hang."""
    emit, events = _recordingEmitter()
    calls = []
    # entry True (grace), smoothing confirms (True), post-window False (returned).
    seq = _seq(
        events_emit=emit,
        isOnBattery=iter([True, True, False]).__next__,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
    )
    seq.handleOnBattery()

    phases = [p for p, _ in events]
    assert phases[0] == "grace"
    assert phases[-1] == "cancelled"
    assert "poweroff" not in calls


def test_emitFailure_neverBlocksShutdown():
    """Constraint (c): a phase-emit callable that raises must NOT stop the
    sequencer from completing the shutdown (poweroff still fires)."""
    calls = []

    def _raisingEmit(phase, **kw):
        raise RuntimeError("emit blew up")

    seq = _seq(
        events_emit=_raisingEmit,
        isOnBattery=lambda: True,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
    )
    seq.handleOnBattery()
    assert calls == ["pipeline", "poweroff"]  # shutdown completed despite emit error


def test_noEmitter_doesNotReadIsOnBattery_extraTimes():
    """Regression guard: when phaseEmitFn is None the sequencer takes the exact
    legacy path -- it must NOT add the entry isOnBattery() read that the emit
    path uses, so iterator-based legacy mocks keep their consumption pattern."""
    reads = {"n": 0}

    def _isOnBattery():
        reads["n"] += 1
        return True

    seq = _seq(
        events_emit=None,
        isOnBattery=_isOnBattery,
        smoothingSec=0.0,
    )
    seq.handleOnBattery()
    # Legacy path: one read inside _smoothedPowerLost + one post-window read = 2.
    # (The emit path would add a third entry read.)
    assert reads["n"] == 2


# ================================================================================
# US-883-a: step {index, of, name} from the one ceremony list
# ================================================================================


def _steps(events):
    """The distinct step values written, in order (a phase write repeats one)."""
    out = []
    for _phase, kw in events:
        step = kw.get("step")
        if step is not None and (not out or out[-1] != step):
            out.append(step)
    return out


def _named(steps):
    return [(s["name"], s["index"], s["of"]) for s in steps]


class _Hold:
    """Stands in for MonthlyTestHoldTask: a named task that returns at once."""

    name = STEP_MONTHLY_TEST_HOLD

    def run(self):
        return "ok"


def _wiredSeq(emit, *, holdDue=False, **kw):
    """A sequencer whose pre-poweroff hooks announce their step as main() wires them."""
    box = {}

    def enterStep(step):
        box["seq"].enterStep(step)

    kw.setdefault(
        "prePowerOffFn",
        m.composePrePowerOffHooks(
            m.announceStep(STEP_DRAIN_CLOSE, lambda: None, enterStep),
            m.announceStep(STEP_CUSTODY, lambda: None, enterStep),
        ),
    )
    pipeline = kw.pop("pipeline", None)
    if pipeline is not None:
        kw["runPipelineFn"] = lambda: pipeline(enterStep)
    seq = _seq(events_emit=emit, holdDueFn=lambda: holdDue, **kw)
    box["seq"] = seq
    return seq


def test_ceremonySteps_eachPath():
    """
    Given: the one ceremony list
    When:  each path's plan is asked for
    Then:  normal 5 in CEREMONY_ORDER, 6 with the hold after the drain, fast path 3
    """
    assert CEREMONY_ORDER == ("shed", "drain", "drain close", "custody", "poweroff")
    assert ceremonySteps(fastPath=False, holdDue=False) == CEREMONY_ORDER
    assert ceremonySteps(fastPath=False, holdDue=True) == (
        "shed", "drain", "monthly_test_hold", "drain close", "custody", "poweroff",
    )
    assert ceremonySteps(fastPath=True, holdDue=False) == ("shed", "custody", "poweroff")
    assert ceremonySteps(fastPath=True, holdDue=True) == ("shed", "custody", "poweroff")


def test_holdStepName_isTheHoldTasksName():
    """The step word for the hold is the task's own name (one string)."""
    from src.pi.power.power_watch.tasks.monthly_test_hold import MonthlyTestHoldTask

    assert STEP_MONTHLY_TEST_HOLD == MonthlyTestHoldTask.name


def test_normalHomePath_holdNotDue_stepsOneToFiveOfFive():
    """
    Given: a sustained loss above the floor, hold not due, hooks wired as main() wires them
    When:  the shutdown runs to poweroff
    Then:  shed..poweroff are published in order, index 1..5, of 5
    """
    emit, events = _recordingEmitter()
    _wiredSeq(emit).handleOnBattery()

    assert _named(_steps(events)) == [
        ("shed", 1, 5), ("drain", 2, 5), ("drain close", 3, 5),
        ("custody", 4, 5), ("poweroff", 5, 5),
    ]


def test_example_drainStepIsWrittenWithFlushing():
    """The story's example: {phase: flushing, step: {index: 2, of: 5, name: 'drain'}}."""
    emit, events = _recordingEmitter()
    _wiredSeq(emit).handleOnBattery()

    assert ("flushing", {"index": 2, "of": 5, "name": "drain"}) in [
        (p, kw["step"]) for p, kw in events
    ]


def test_holdDue_ofSix_holdInOrder():
    """
    Given: the monthly hold due, and the hold task announcing itself in the pipeline
    When:  the shutdown runs
    Then:  of = 6 and the hold is step 3, between the drain and the drain close
    """
    emit, events = _recordingEmitter()
    seen = {}

    def pipeline(enterStep):
        task = m.StepAnnouncedTask(_Hold(), STEP_MONTHLY_TEST_HOLD, enterStep)
        seen["name"] = task.name
        seen["result"] = task.run()

    _wiredSeq(emit, holdDue=True, pipeline=pipeline).handleOnBattery()

    assert seen == {"name": STEP_MONTHLY_TEST_HOLD, "result": "ok"}
    assert _named(_steps(events)) == [
        ("shed", 1, 6), ("drain", 2, 6), ("monthly_test_hold", 3, 6),
        ("drain close", 4, 6), ("custody", 5, 6), ("poweroff", 6, 6),
    ]


def test_holdAnnounced_butNotPlanned_publishesNothing():
    """A hold that was not due at the plan is off the path: no step, of stays 5."""
    emit, events = _recordingEmitter()
    _wiredSeq(
        emit, holdDue=False, pipeline=lambda enterStep: enterStep(STEP_MONTHLY_TEST_HOLD),
    ).handleOnBattery()

    steps = _steps(events)
    assert STEP_MONTHLY_TEST_HOLD not in [s["name"] for s in steps]
    assert {s["of"] for s in steps} == {5}


def test_vcellFastPathFromTheStart_ofThree_noDrainNoDrainClose():
    """
    Given: the first VCELL read at the floor (fast path), the drain close still wired
    When:  the shutdown runs
    Then:  of = 3: shed, custody, poweroff -- no drain and no drain close step
    """
    emit, events = _recordingEmitter()
    _wiredSeq(emit, vcell=lambda: 3.30).handleOnBattery()

    assert _named(_steps(events)) == [("shed", 1, 3), ("custody", 2, 3), ("poweroff", 3, 3)]
    assert {p for p, kw in events if kw["step"] is not None} == {"powering_off"}


def test_vcellForcesFastPathAfterDrainStarted_ofFiveThenFour():
    """
    Given: the drain running when a VCELL read reaches the drain floor
    When:  the floor ends the drain
    Then:  shed 1/5, drain 2/5, custody 3/4, poweroff 4/4; index never exceeds of
    """
    emit, events = _recordingEmitter()
    release = threading.Event()
    reads = iter([3.90, 3.45])
    try:
        _wiredSeq(
            emit,
            vcell=lambda: next(reads, 3.45),
            drainFloor=3.50,
            smoothingPollSec=0.001,
            runPipelineFn=release.wait,
        ).handleOnBattery()
    finally:
        release.set()

    steps = _steps(events)
    assert _named(steps) == [
        ("shed", 1, 5), ("drain", 2, 5), ("custody", 3, 4), ("poweroff", 4, 4),
    ]
    assert all(s["index"] <= s["of"] for s in steps)
    assert [s["index"] for s in steps] == sorted(s["index"] for s in steps)


def test_graceThenCancelled_stepNullThroughout():
    """
    Given: a blip that fails smoothing
    When:  grace then cancelled are written
    Then:  step is null on both
    """
    emit, events = _recordingEmitter()
    _wiredSeq(emit, isOnBattery=iter([True, False]).__next__, smoothingSec=5.0).handleOnBattery()

    assert [p for p, _ in events] == ["grace", "cancelled"]
    assert [kw["step"] for _, kw in events] == [None, None]


def test_powerReturnsMidDrain_cancelledCarriesNoStep_andALateAnnounceIsDropped():
    """A cancel mid-drain writes step null and ends the plan: a late hook publishes nothing."""
    emit, events = _recordingEmitter()
    seq = _wiredSeq(emit, isOnBattery=iter([True, True, False]).__next__)
    seq.handleOnBattery()
    count = len(events)
    seq.enterStep(STEP_CUSTODY)

    assert events[-1][0] == "cancelled"
    assert events[-1][1]["step"] is None
    assert len(events) == count


def test_holdDueRaises_plannedWithoutTheHold():
    """A hold-due read that raises never stalls the shutdown: of stays 5."""
    emit, events = _recordingEmitter()

    def _boom():
        raise RuntimeError("db locked")

    _seq(events_emit=emit, holdDueFn=_boom).handleOnBattery()

    assert {s["of"] for s in _steps(events)} == {5}


def test_noEmitter_neverReadsHoldDue():
    """With no phaseEmitFn nothing publishes, so the hold-due read is not made."""
    calls = []
    _seq(events_emit=None, holdDueFn=lambda: calls.append("read") or True).handleOnBattery()

    assert calls == []


@pytest.mark.parametrize(
    ("plan", "enters", "expected"),
    [
        (CEREMONY_ORDER, ["shed", "drain"], {"index": 2, "of": 4, "name": "drain"}),
        (
            ceremonySteps(fastPath=False, holdDue=True),
            ["shed", "drain", "monthly_test_hold"],
            {"index": 3, "of": 5, "name": "monthly_test_hold"},
        ),
    ],
    ids=["after-drain", "during-hold"],
)
def test_ceremonyProgress_rerouteKeepsEnteredAndAppendsRemaining(plan, enters, expected):
    """of = steps entered + steps remaining on the new path (Atlas Rule 13 gap 1)."""
    progress = CeremonyProgress()
    progress.begin(plan)
    for name in enters:
        assert progress.enter(name)
    progress.reroute(ceremonySteps(fastPath=True, holdDue=False))

    assert progress.step() == expected


def test_ceremonyProgress_neverGoesBackwards():
    """A step already behind the current one, or off the plan, is not entered."""
    progress = CeremonyProgress()
    progress.begin(CEREMONY_ORDER)
    assert progress.step() is None
    assert progress.enter("custody")
    assert not progress.enter("drain")
    assert not progress.enter("not-a-step")

    assert progress.step() == {"index": 4, "of": 5, "name": "custody"}
