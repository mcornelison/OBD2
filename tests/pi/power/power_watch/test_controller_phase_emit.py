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
# ================================================================================
################################################################################

"""Tests for the ShutdownSequencer phase-emit hook (US-394)."""

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
    assert phases == ["grace", "flushing", "powering_off"]
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
    assert phases == ["grace", "powering_off"]
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
