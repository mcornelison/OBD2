################################################################################
# File Name: test_load_shed.py
# Purpose/Description: ARCH-031 / US-748 -- shed load on power loss, BEFORE the
#     smoothing debounce decides whether to power off.
#
#     Measured 2026-09-16 across 9 live power cuts (CIO on the plug): with the
#     chromium dashboard running the Pi drew 4.35 W bursty and survived 0.678 s
#     on battery; with that ONE service stopped it drew 1.886 W and survived
#     ~7 s. Everything else the project runs adds ~0.1 W combined. Shedding the
#     dashboard is therefore a ~10x survival improvement for free.
#
#     The design separates the REVERSIBLE mitigation from the IRREVERSIBLE
#     decision: shed immediately on the first PLD edge (no debounce, nothing
#     committed), then let smoothing decide. If power returns, restore.
#
# 🔴 THE INVARIANT THESE TESTS EXIST TO PROTECT: neither shedding nor restoring
#     may EVER raise into the shutdown sequencer. Shedding is an optimisation;
#     losing the shutdown to it would be strictly worse than the defect it fixes.
#
# Author: Atlas (ARCH-031, CIO build override 2026-09-16)
# Creation Date: 2026-09-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""ARCH-031: reversible load shedding at power loss."""

from __future__ import annotations

import pytest

from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.load_shed import LoadShedder


class _Runner:
    """Records unit actions instead of invoking systemd. Fails on demand."""

    def __init__(self, failOn: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._failOn = failOn or set()

    def __call__(self, action: str, unit: str) -> None:
        self.calls.append((action, unit))
        if unit in self._failOn:
            raise OSError(f"systemctl {action} {unit} failed")


def test_shedStopsEveryConfiguredUnit():
    """The whole point: on power loss the configured load is dropped."""
    runner = _Runner()
    shedder = LoadShedder(("eclipse-dashboard",), runner=runner)

    shedder.shed()

    assert runner.calls == [("stop", "eclipse-dashboard")]


def test_restoreStartsExactlyWhatWasShed():
    """Power returned during smoothing -> put back what we took, nothing more."""
    runner = _Runner()
    shedder = LoadShedder(("eclipse-dashboard",), runner=runner)

    shedder.shed()
    runner.calls.clear()
    shedder.restore()

    assert runner.calls == [("start", "eclipse-dashboard")]


def test_restoreWithoutShedDoesNothing():
    """A cancel with no prior loss must not start services nobody stopped.

    The sequencer can emit `cancelled` on paths where shedding never ran; a
    restore that starts units unconditionally would turn a no-op into a change.
    """
    runner = _Runner()
    shedder = LoadShedder(("eclipse-dashboard",), runner=runner)

    shedder.restore()

    assert runner.calls == []


def test_aFailingShedNeverRaises():
    """🔴 The invariant. A failed shed must cost us the shed, never the shutdown."""
    runner = _Runner(failOn={"eclipse-dashboard"})
    shedder = LoadShedder(("eclipse-dashboard",), runner=runner)

    shedder.shed()  # must not raise

    assert runner.calls == [("stop", "eclipse-dashboard")]


def test_aFailingRestoreNeverRaises():
    """Same invariant on the way back: a cancel must still complete."""
    runner = _Runner(failOn={"eclipse-dashboard"})
    shedder = LoadShedder(("eclipse-dashboard",), runner=runner)
    shedder._shed = ["eclipse-dashboard"]  # noqa: SLF001 -- simulate a prior shed

    shedder.restore()  # must not raise


def test_oneUnitFailingDoesNotStopTheOthersBeingShed():
    """Shedding is best-effort PER UNIT.

    The dashboard is the one that matters; a failure on any other unit must not
    silently leave it running, which is what a bare try/except round the whole
    loop would do.
    """
    runner = _Runner(failOn={"first"})
    shedder = LoadShedder(("first", "eclipse-dashboard"), runner=runner)

    shedder.shed()

    assert runner.calls == [("stop", "first"), ("stop", "eclipse-dashboard")]


def test_restoreOnlyReturnsUnitsThatActuallyStopped():
    """A unit that failed to stop is still running -- starting it is a lie.

    Restoring it would make the log claim a state change that never happened.
    """
    runner = _Runner(failOn={"stuck"})
    shedder = LoadShedder(("stuck", "eclipse-dashboard"), runner=runner)

    shedder.shed()
    runner.calls.clear()
    shedder.restore()

    assert runner.calls == [("start", "eclipse-dashboard")]


def test_shedIsIdempotentWithinOneLoss():
    """A second PLD edge during the same loss must not re-stop or double-record."""
    runner = _Runner()
    shedder = LoadShedder(("eclipse-dashboard",), runner=runner)

    shedder.shed()
    shedder.shed()

    assert runner.calls == [("stop", "eclipse-dashboard")]


@pytest.mark.parametrize("units", [(), None])
def test_noUnitsConfiguredIsAWorkingNoOp(units):
    """Shedding must be opt-in. An empty list disables it without special-casing."""
    runner = _Runner()
    shedder = LoadShedder(units or (), runner=runner)

    shedder.shed()
    shedder.restore()

    assert runner.calls == []


# ---------------------------------------------------------------------------
# Sequencer wiring: EVERY path that abandons a shutdown must restore the shed.
#
# 🔴 There are THREE such paths, and the third is easy to miss:
#   1. smoothing not sustained                 (controller.py :286)
#   2. power returned during the window        (controller.py :340)
#   3. the phase-emit early return BEFORE smoothing (:276-277) -- which runs
#      AFTER _notifyPowerLossObserved() has already fired, so a shed has
#      already happened and nothing would ever put it back.
# A shed that is never restored leaves the dashboard dark until the next boot.
# ---------------------------------------------------------------------------


def _pw(**kw):
    """A sequencer with everything injected, mirroring test_controller.py."""
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
    )
    base.update(kw)
    return ShutdownSequencer(**base)


def test_restoreHookFiresWhenSmoothingSaysTransient():
    """Path 1: a blip. We shed on the edge; the blip must give it back."""
    calls = []
    pw = _pw(
        isOnBattery=iter([True, False]).__next__,
        smoothingSec=0.01,
        powerRestoredFn=lambda: calls.append("restored"),
    )
    pw.handleOnBattery()
    assert calls == ["restored"]


def test_restoreHookFiresWhenPowerReturnsDuringTheWindow():
    """Path 2: power came back WHILE the bounded pipeline was running.

    ⚠️ Expressed as state the pipeline mutates, NOT as a fixed sequence of
    isOnBattery() return values -- a canned sequence silently couples the test
    to how many times the sequencer happens to poll, which is an implementation
    detail it has no business asserting.
    """
    calls = []
    onBattery = {"value": True}

    def _pipelineDuringWhichPowerReturns():
        onBattery["value"] = False

    pw = _pw(
        isOnBattery=lambda: onBattery["value"],
        runPipelineFn=_pipelineDuringWhichPowerReturns,
        powerRestoredFn=lambda: calls.append("restored"),
        powerOffFn=lambda: calls.append("poweroff"),
    )
    pw.handleOnBattery()
    assert calls == ["restored"], "power returned mid-window: abort and restore"


def test_restoreHookFiresOnThePhaseEmitEarlyReturn():
    """🔴 Path 3. The loss-observed hook ALREADY ran, so a shed is outstanding."""
    calls = []
    pw = _pw(
        isOnBattery=lambda: False,
        phaseEmitFn=lambda _p: None,
        powerLossObservedFn=lambda: calls.append("shed"),
        powerRestoredFn=lambda: calls.append("restored"),
    )
    pw.handleOnBattery()
    assert calls == ["shed", "restored"]


def test_restoreHookDoesNotFireOnARealShutdown():
    """A sustained loss powers off. Restoring there would re-start the load we
    just shed, moments before cutting power -- the exact opposite of the point."""
    calls = []
    pw = _pw(
        isOnBattery=lambda: True,
        powerRestoredFn=lambda: calls.append("restored"),
        powerOffFn=lambda: calls.append("poweroff"),
    )
    pw.handleOnBattery()
    assert calls == ["poweroff"]


def test_theComposedLossHookRunsBothTheHeartbeatAndTheShed():
    """ARCH-031 shares the loss-observed slot with US-748's heartbeat.

    🔴 The slot takes ONE callable, so adding shedding meant composing. Both must
    run, and neither may suppress the other -- a failing shed must not cost us
    the time-to-death instrument, which is the only record of how long the Pi
    survived.
    """
    from src.pi.power.power_watch.__main__ import composePrePowerOffHooks

    calls = []

    def _heartbeat():
        calls.append("heartbeat")

    def _shedThatBlowsUp():
        calls.append("shed")
        raise RuntimeError("systemctl unavailable")

    composed = composePrePowerOffHooks(_heartbeat, _shedThatBlowsUp)
    composed()  # must not raise

    assert calls == ["heartbeat", "shed"]


def test_aRaisingRestoreHookNeverBreaksTheCancel():
    """🔴 The invariant, at the sequencer boundary."""
    def _boom():
        raise RuntimeError("restore exploded")

    pw = _pw(
        isOnBattery=iter([True, False]).__next__,
        smoothingSec=0.01,
        powerRestoredFn=_boom,
    )
    pw.handleOnBattery()  # must not raise
