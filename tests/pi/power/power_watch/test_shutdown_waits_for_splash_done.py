################################################################################
# File Name: test_shutdown_waits_for_splash_done.py
# Purpose/Description: US-870-d -- poweroff waits for the shutdown page's
#                      'splash done' record, bounded by totalCapSec measured from
#                      the start of the wait; skipped on the floor paths, when
#                      the grace splash is not active, and cancelled on power
#                      return. Also the real done-file reader (this boot only).
# Author: Rex (Ralph)
# Creation Date: 2026-10-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-27    | Rex (US-870-d) | Initial -- A1-A4, A6, A7 and the G2 call order.
# ================================================================================
################################################################################

"""The splash-done wait between the powering_off emit and the poweroff."""

from __future__ import annotations

import json
import logging
import subprocess
import threading

import pytest

from src.pi.ops import unit_manifest
from src.pi.power.power_watch import splash_done
from src.pi.power.power_watch.controller import (
    PHASE_CANCELLED,
    PHASE_POWERING_OFF,
    ShutdownSequencer,
)
from src.pi.power.types import DRAIN_TERMINATION_DRAIN_FLOOR

_CAP = 45.0  # pi.powerWatch.totalWindowCapSec default (validator.py)
_POLL = 1.0  # pi.powerWatch.smoothingPollSec default
_DRAIN_FLOOR = 3.55
_VCELL_FLOOR = 3.40
_HEALTHY = 3.90
_BOOT = "0123456789abcdef0123456789abcdef"


class _Clock:
    """A fake monotonic clock that only the injected sleep advances."""

    def __init__(self) -> None:
        self.now = 1000.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


class _Run:
    """One recorded shutdown: the ordered events and the wait's start time."""

    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.events: list[str] = []
        self.waitStart: float | None = None
        self.powerOffAt: float | None = None

    def emit(self, phase: str, **_fields: object) -> None:
        self.events.append(f"emit:{phase}")
        if phase == PHASE_POWERING_OFF and self.waitStart is None:
            self.waitStart = self.clock.now

    def powerOff(self) -> None:
        self.events.append("poweroff")
        self.powerOffAt = self.clock.now


def _sequencer(run: _Run, **kw) -> ShutdownSequencer:
    clock = run.clock
    base = dict(
        isOnBattery=lambda: True,
        vcell=lambda: _HEALTHY,
        runPipelineFn=lambda: None,
        powerOffFn=run.powerOff,
        vcellFloor=_VCELL_FLOOR,
        drainFloor=_DRAIN_FLOOR,
        totalCapSec=_CAP,
        smoothingSec=0.0,
        smoothingPollSec=_POLL,
        sleepFn=clock.sleep,
        monotonicFn=clock.monotonic,
        phaseEmitFn=run.emit,
        splashActiveFn=lambda: True,
        splashDoneFn=lambda: None,
    )
    base.update(kw)
    return ShutdownSequencer(**base)


def _doneAfter(run: _Run, seconds: float):
    """A done reader whose record appears ``seconds`` after the wait starts."""

    def _read() -> str | None:
        run.events.append("wait")
        if run.waitStart is not None and run.clock.now - run.waitStart >= seconds:
            return "2026-10-27T07:00:10Z"
        return None

    return _read


# ------------------------------------------------------------------ A1 / G2


def test_poweroff_waits_for_splash_done(caplog):
    """
    Given: a normal key-off with the grace splash active
    When: the page's done record appears 4 s after the wait starts
    Then: poweroff comes at t >= 4 s, not before, and the outcome is logged
    """
    run = _Run(_Clock())
    seq = _sequencer(run, splashDoneFn=_doneAfter(run, 4.0))

    with caplog.at_level(logging.INFO):
        seq.handleOnBattery()

    assert run.powerOffAt is not None and run.waitStart is not None
    assert run.powerOffAt - run.waitStart >= 4.0
    assert run.powerOffAt - run.waitStart < 4.0 + 2 * _POLL
    assert "splash done after 4.0 s" in caplog.text


def test_callOrder_emitPoweringOff_thenTheWait_thenPowerOff():
    """
    Given: a recorder on the phase emit, the done reader and the poweroff
    When: a normal key-off runs
    Then: emit(powering_off), then the wait, then poweroff -- never a read before the cue
    """
    run = _Run(_Clock())
    seq = _sequencer(run, splashDoneFn=_doneAfter(run, 2.0))

    seq.handleOnBattery()

    cue = run.events.index(f"emit:{PHASE_POWERING_OFF}")
    firstWait = run.events.index("wait")
    assert cue < firstWait < run.events.index("poweroff")
    assert run.events[-1] == "poweroff"


def test_aRecordAlreadyThereAtTheCue_doesNotEndTheWait():
    """
    Given: a done record already on disk when powering_off is emitted (an earlier
           shutdown of this boot that was cancelled)
    When: the wait runs and no NEW record appears
    Then: it does not end the wait -- poweroff only at the ceiling
    """
    run = _Run(_Clock())
    seq = _sequencer(run, splashDoneFn=lambda: "2026-10-27T06:00:00Z")

    seq.handleOnBattery()

    assert run.powerOffAt - run.waitStart >= _CAP


# ------------------------------------------------------------------------ A2


def test_noDoneFile_powerOffAtTheCeiling_measuredFromTheWaitStart(caplog):
    """
    Given: no done record ever (kiosk dead at key-off)
    When: the wait runs
    Then: poweroff at totalCapSec after the WAIT starts, with the cap-hit log
    """
    run = _Run(_Clock())
    seq = _sequencer(run)

    with caplog.at_level(logging.INFO):
        seq.handleOnBattery()

    elapsed = run.powerOffAt - run.waitStart
    assert _CAP <= elapsed < _CAP + 2 * _POLL
    assert "splash wait cap hit" in caplog.text


# ------------------------------------------------------------------------ A7


def test_vcellAtTheDrainFloorDuringTheWait_powersOffAtOnce(caplog):
    """
    Given: the pack reaches the drain floor once the wait has started
    When: the wait polls VCELL
    Then: poweroff at once (the dwell reads), long before the ceiling
    """
    run = _Run(_Clock())

    def _vcell() -> float:
        if run.waitStart is not None and run.clock.now - run.waitStart >= 3.0:
            return _DRAIN_FLOOR - 0.05
        return _HEALTHY

    seq = _sequencer(run, vcell=_vcell)

    with caplog.at_level(logging.INFO):
        seq.handleOnBattery()

    assert run.powerOffAt - run.waitStart < 3.0 + 2 * _POLL
    assert "splash wait ended on the drain floor" in caplog.text


def test_drainFloorDuringTheWait_honoursTheDwellReads():
    """
    Given: drainFloorDwellReads=3 and every read during the wait below the floor
    When: the wait polls
    Then: poweroff after the third consecutive low read, not the first
    """
    run = _Run(_Clock())

    def _vcell() -> float:
        return _DRAIN_FLOOR - 0.05 if run.waitStart is not None else _HEALTHY

    seq = _sequencer(run, vcell=_vcell, drainFloorDwellReads=3)

    seq.handleOnBattery()

    assert run.powerOffAt - run.waitStart == pytest.approx(3 * _POLL)


def test_floorBlindForTotalCap_endsTheWait(caplog):
    """
    Given: VCELL unreadable for the whole wait
    When: the wait polls
    Then: poweroff once the floor has been blind for totalCapSec
    """
    run = _Run(_Clock())

    def _vcell() -> float:
        if run.waitStart is not None:
            raise OSError("i2c")
        return _HEALTHY

    seq = _sequencer(run, vcell=_vcell)

    seq.handleOnBattery()

    assert _CAP <= run.powerOffAt - run.waitStart < _CAP + 2 * _POLL


# --------------------------------------------------------------- cancel (b)


def test_powerReturnsDuringTheWait_cancels_noPoweroff(caplog):
    """
    Given: power returns 3 s into the wait
    When: the wait polls isOnBattery
    Then: cancelled is emitted, the restore hook runs, and there is NO poweroff
    """
    run = _Run(_Clock())
    restored: list[str] = []

    def _onBattery() -> bool:
        return not (run.waitStart is not None and run.clock.now - run.waitStart >= 3.0)

    seq = _sequencer(
        run,
        isOnBattery=_onBattery,
        powerRestoredFn=lambda: restored.append("restore"),
        prePowerOffFn=lambda: run.events.append("prepoweroff"),
    )

    with caplog.at_level(logging.INFO):
        seq.handleOnBattery()

    assert "poweroff" not in run.events
    assert "prepoweroff" not in run.events
    assert run.events[-1] == f"emit:{PHASE_CANCELLED}"
    assert restored == ["restore"]
    assert "splash wait cancelled" in caplog.text


# --------------------------------------------------------------- A3 / A4 skips


def test_drainFloorPath_noWait():
    """
    Given: the drain itself ended on the drain floor
    When: the sequencer reaches poweroff
    Then: no wait -- neither the splash check nor the done reader is consulted
    """
    run = _Run(_Clock())
    consulted: list[str] = []
    blocker = threading.Event()  # the pipeline never finishes on its own
    seq = _sequencer(
        run,
        runPipelineFn=blocker.wait,
        # Above the backstop (the pipeline starts), at the drain floor (it ends).
        vcell=lambda: _DRAIN_FLOOR - 0.05,
        splashActiveFn=lambda: consulted.append("active") or True,
        splashDoneFn=lambda: consulted.append("done"),
    )

    try:
        seq.handleOnBattery()
    finally:
        blocker.set()

    assert seq.lastDrainEndReason == DRAIN_TERMINATION_DRAIN_FLOOR
    assert consulted == []
    assert run.events[-1] == "poweroff"


def test_vcellFloorFastPath_noWait():
    """
    Given: VCELL already at the backstop floor when smoothing confirms
    When: the fast path powers off
    Then: no wait
    """
    run = _Run(_Clock())
    consulted: list[str] = []
    seq = _sequencer(
        run,
        vcell=lambda: _VCELL_FLOOR - 0.1,
        splashActiveFn=lambda: consulted.append("active") or True,
        splashDoneFn=lambda: consulted.append("done"),
    )

    seq.handleOnBattery()

    assert consulted == []
    assert run.events[-1] == "poweroff"


def test_splashGraceInactive_noWait():
    """
    Given: the grace splash is not active
    When: the sequencer reaches poweroff
    Then: poweroff at once; the done reader is never read
    """
    run = _Run(_Clock())
    reads: list[str] = []
    seq = _sequencer(
        run, splashActiveFn=lambda: False, splashDoneFn=lambda: reads.append("x"),
    )

    seq.handleOnBattery()

    assert reads == []
    assert run.powerOffAt == run.waitStart


def test_splashCheckRaises_readsAsInactive_noWait():
    run = _Run(_Clock())

    def _boom() -> bool:
        raise RuntimeError("systemctl")

    seq = _sequencer(run, splashActiveFn=_boom)

    seq.handleOnBattery()

    assert run.powerOffAt == run.waitStart


def test_noPhaseEmitter_noWait_legacyPath():
    """
    Given: no phaseEmitFn wired (splash disabled: nothing tells a page to end)
    When: the sequencer reaches poweroff
    Then: no wait and no splash check
    """
    run = _Run(_Clock())
    consulted: list[str] = []
    seq = _sequencer(
        run,
        phaseEmitFn=None,
        splashActiveFn=lambda: consulted.append("active") or True,
    )

    seq.handleOnBattery()

    assert consulted == []
    assert run.events == ["poweroff"]


def test_doneReaderRaises_isNotDone():
    run = _Run(_Clock())

    def _boom() -> str | None:
        raise OSError("tmpfs")

    seq = _sequencer(run, splashDoneFn=_boom)

    seq.handleOnBattery()

    assert run.powerOffAt - run.waitStart >= _CAP


# ------------------------------------------------- A6: the real done reader


def _writeDone(statesDir, bootId: str | None, ts: str = "2026-10-27T07:00:10Z") -> None:
    (statesDir / splash_done.SHUTDOWN_SPLASH_DONE_FILENAME).write_text(
        json.dumps({"bootId": bootId, "ts": ts}), encoding="utf-8"
    )


def test_reader_thisBootsRecord_returnsItsTs(tmp_path):
    _writeDone(tmp_path, _BOOT)
    read = splash_done.makeSplashDoneReader(str(tmp_path), currentBootIdFn=lambda: _BOOT)

    assert read() == "2026-10-27T07:00:10Z"


def test_reader_anotherBootsRecord_isIgnored(tmp_path):
    _writeDone(tmp_path, "f" * 32)
    read = splash_done.makeSplashDoneReader(str(tmp_path), currentBootIdFn=lambda: _BOOT)

    assert read() is None


@pytest.mark.parametrize(
    "content",
    ["", "not json", "[]", '{"ts": "x"}', '{"bootId": null, "ts": "x"}'],
)
def test_reader_malformedOrUnstampedRecord_isNotDone(tmp_path, content):
    (tmp_path / splash_done.SHUTDOWN_SPLASH_DONE_FILENAME).write_text(content, encoding="utf-8")
    read = splash_done.makeSplashDoneReader(str(tmp_path), currentBootIdFn=lambda: _BOOT)

    assert read() is None


def test_reader_currentBootUnreadable_neverMatches(tmp_path):
    _writeDone(tmp_path, None)
    read = splash_done.makeSplashDoneReader(str(tmp_path), currentBootIdFn=lambda: None)

    assert read() is None


def test_reader_noFile_isNotDone(tmp_path):
    read = splash_done.makeSplashDoneReader(str(tmp_path), currentBootIdFn=lambda: _BOOT)

    assert read() is None


def test_anotherBootsRecord_throughTheSequencer_powersOffAtTheCeiling(tmp_path):
    """A6 end to end: a done file with another boot's bootId never ends the wait."""
    run = _Run(_Clock())
    reader = splash_done.makeSplashDoneReader(str(tmp_path), currentBootIdFn=lambda: _BOOT)

    def _postLate() -> str | None:
        if run.waitStart is not None and run.clock.now - run.waitStart >= 2.0:
            _writeDone(tmp_path, "f" * 32)
        return reader()

    seq = _sequencer(run, splashDoneFn=_postLate)

    seq.handleOnBattery()

    assert run.powerOffAt - run.waitStart >= _CAP


# ------------------------------------------------- the real unit check


def test_splashGraceUnit_isTheManifestsUnit():
    assert unit_manifest.lookup(splash_done.SPLASH_GRACE_UNIT) is not None


def test_splashGraceActive_trueOnlyWhenSystemctlSaysActive():
    calls: list[tuple[str, str]] = []

    def _active(action: str, unit: str) -> None:
        calls.append((action, unit))

    def _inactive(action: str, unit: str) -> None:
        raise subprocess.CalledProcessError(3, ["systemctl", action, unit])

    def _missing(action: str, unit: str) -> None:
        raise FileNotFoundError("systemctl")

    assert splash_done.splashGraceActive(runner=_active) is True
    assert calls == [("is-active", splash_done.SPLASH_GRACE_UNIT)]
    assert splash_done.splashGraceActive(runner=_inactive) is False
    assert splash_done.splashGraceActive(runner=_missing) is False
