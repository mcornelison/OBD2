################################################################################
# File Name: test_drain_trajectory_rows.py
# Purpose/Description: US-790 -- ShutdownSequencer feeds the drain VCELL series:
#                      one row per drain poll (the start read included), NULL
#                      for a failed read, and exactly ONE terminal row per drain
#                      carrying the typed reason the drain ended -- on every one
#                      of its exits.  Unwired, the sequencer reads VCELL exactly
#                      as before (a row costs no extra I2C per poll).
# Author: Rex (US-790)
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-25    | Rex (US-790) | Initial.
# ================================================================================
################################################################################
"""The sequencer's drain poll produces the VCELL series (US-790)."""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator

from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.types import (
    DRAIN_TERMINATION_DRAIN_FLOOR,
    DRAIN_TERMINATION_POWER_RESTORED,
    DRAIN_TERMINATION_SHUTDOWN,
    DRAIN_TERMINATION_VCELL_FLOOR,
    DRAIN_TERMINATION_VCELL_UNREADABLE,
)

_VCELL_FLOOR = 3.50
_DRAIN_FLOOR = 3.60
_TOTAL_CAP_SEC = 45.0
_POLL_SEC = 0.005


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self.t

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.t += seconds


class _Rows:
    """Captures what the sequencer hands the trajectory writer."""

    def __init__(self) -> None:
        self.rows: list[tuple[float | None, str | None]] = []

    def __call__(self, vcellV: float | None, *, terminationReason: str | None = None) -> None:
        self.rows.append((vcellV, terminationReason))

    @property
    def terminal(self) -> list[tuple[float | None, str | None]]:
        return [row for row in self.rows if row[1] is not None]


def _script(values: list[float | Exception], *, then: float | Exception) -> Callable[[], float]:
    it: Iterator[float | Exception] = iter(values)
    lock = threading.Lock()

    def _read() -> float:
        with lock:
            value = next(it, then)
        if isinstance(value, Exception):
            raise value
        return value

    return _read


def _sequencer(
    *,
    rows: _Rows | None,
    vcell: Callable[[], float],
    runPipelineFn: Callable[[], None],
    events: list[str],
    isOnBattery: Callable[[], bool] = lambda: True,
    clock: _Clock | None = None,
) -> ShutdownSequencer:
    return ShutdownSequencer(
        isOnBattery=isOnBattery,
        vcell=vcell,
        runPipelineFn=runPipelineFn,
        powerOffFn=lambda: events.append("poweroff"),
        vcellFloor=_VCELL_FLOOR,
        drainFloor=_DRAIN_FLOOR,
        totalCapSec=_TOTAL_CAP_SEC,
        smoothingSec=0.0,
        smoothingPollSec=_POLL_SEC,
        sleepFn=lambda _s: None,
        monotonicFn=clock if clock is not None else _Clock(),
        drainSampleFn=rows,
    )


def _blockingPipeline(release: threading.Event) -> Callable[[], None]:
    def _pipe() -> None:
        release.wait(5.0)

    return _pipe


class TestOneRowPerPoll:
    def test_drainFloorExit_everyPollIsARow_andOnlyTheLastCarriesTheReason(self) -> None:
        rows, events, release = _Rows(), [], threading.Event()
        seq = _sequencer(
            rows=rows,
            vcell=_script([4.00, 3.90, 3.80, 3.55], then=3.55),
            runPipelineFn=_blockingPipeline(release),
            events=events,
        )

        try:
            seq.handleOnBattery()
        finally:
            release.set()

        assert rows.rows == [
            (4.00, None),
            (3.90, None),
            (3.80, None),
            (3.55, DRAIN_TERMINATION_DRAIN_FLOOR),
        ]
        assert events == ["poweroff"]

    def test_aFailedReadMidDrain_isNULL_neverASentinel(self) -> None:
        rows, events, release = _Rows(), [], threading.Event()
        seq = _sequencer(
            rows=rows,
            vcell=_script([4.00, OSError("i2c"), 3.55], then=3.55),
            runPipelineFn=_blockingPipeline(release),
            events=events,
        )

        try:
            seq.handleOnBattery()
        finally:
            release.set()

        assert rows.rows == [(4.00, None), (None, None), (3.55, DRAIN_TERMINATION_DRAIN_FLOOR)]


class TestEveryExitWritesExactlyOneTerminalRow:
    def test_vcellFloorFastPath_isAOneRowDrain(self) -> None:
        rows, events = _Rows(), []
        seq = _sequencer(
            rows=rows, vcell=lambda: 3.40, runPipelineFn=lambda: None, events=events,
        )

        seq.handleOnBattery()

        assert rows.rows == [(3.40, DRAIN_TERMINATION_VCELL_FLOOR)]
        assert events == ["poweroff"]

    def test_pipelineComplete_endsWithOneShutdownRow_readAtTermination(self) -> None:
        rows, events, release = _Rows(), [], threading.Event()
        reads = {"n": 0}

        def _vcell() -> float:
            reads["n"] += 1
            if reads["n"] >= 3:
                release.set()  # the drain's own work finishes
            return 3.90

        seq = _sequencer(
            rows=rows, vcell=_vcell, runPipelineFn=_blockingPipeline(release), events=events,
        )

        seq.handleOnBattery()

        assert rows.terminal == [(3.90, DRAIN_TERMINATION_SHUTDOWN)]
        assert rows.rows[-1] == (3.90, DRAIN_TERMINATION_SHUTDOWN)
        assert all(row == (3.90, None) for row in rows.rows[:-1])
        assert len(rows.rows) >= 2  # the start read, then the terminal read
        assert events == ["poweroff"]

    def test_powerRestored_endsWithOnePowerRestoredRow_andNoPoweroff(self) -> None:
        rows, events, release = _Rows(), [], threading.Event()
        onBattery = _script([True, True, True], then=False)

        seq = _sequencer(
            rows=rows,
            vcell=lambda: 3.95,
            runPipelineFn=_blockingPipeline(release),
            events=events,
            isOnBattery=onBattery,  # type: ignore[arg-type]
        )

        try:
            seq.handleOnBattery()
        finally:
            release.set()

        assert rows.terminal == [(3.95, DRAIN_TERMINATION_POWER_RESTORED)]
        assert rows.rows[-1][1] == DRAIN_TERMINATION_POWER_RESTORED
        assert events == []

    def test_floorBlindForTheCap_endsWithOneUnreadableRow(self) -> None:
        rows, events, release = _Rows(), [], threading.Event()
        clock = _Clock()

        def _vcell() -> float:
            clock.advance(10.0)
            raise OSError("gauge gone")

        seq = _sequencer(
            rows=rows, vcell=_vcell, runPipelineFn=_blockingPipeline(release),
            events=events, clock=clock,
        )

        try:
            seq.handleOnBattery()
        finally:
            release.set()

        assert rows.terminal == [(None, DRAIN_TERMINATION_VCELL_UNREADABLE)]
        assert rows.rows[-1] == (None, DRAIN_TERMINATION_VCELL_UNREADABLE)
        assert all(vcell is None for vcell, _ in rows.rows)
        assert events == ["poweroff"]

    def test_bootGraceDrain_readsNoVcell_evenWithTheSeriesWired(self) -> None:
        """US-788's suppression holds: rows record NULL, the gauge is never read."""
        rows, events, release = _Rows(), [], threading.Event()
        clock = _Clock()
        reads: list[int] = []

        def _vcell() -> float:
            reads.append(1)
            return 3.30

        def _pipe() -> None:
            while not release.wait(_POLL_SEC):
                clock.advance(10.0)

        seq = _sequencer(
            rows=rows, vcell=_vcell, runPipelineFn=_pipe, events=events, clock=clock,
        )

        try:
            seq.handleOnBattery(suppressFloorFastPath=True)
        finally:
            release.set()

        assert reads == []
        assert rows.terminal == [(None, DRAIN_TERMINATION_VCELL_UNREADABLE)]
        assert events == ["poweroff"]


class TestTheSeriesNeverCostsTheShutdown:
    def test_aWriterThatRaises_neverBlocksPoweroff(self) -> None:
        events: list[str] = []
        release = threading.Event()

        def _explode(_v, *, terminationReason=None) -> None:
            raise RuntimeError("disk full")

        seq = ShutdownSequencer(
            isOnBattery=lambda: True,
            vcell=_script([4.0, 3.55], then=3.55),
            runPipelineFn=_blockingPipeline(release),
            powerOffFn=lambda: events.append("poweroff"),
            vcellFloor=_VCELL_FLOOR,
            drainFloor=_DRAIN_FLOOR,
            totalCapSec=_TOTAL_CAP_SEC,
            smoothingSec=0.0,
            smoothingPollSec=_POLL_SEC,
            sleepFn=lambda _s: None,
            monotonicFn=_Clock(),
            drainSampleFn=_explode,
        )

        try:
            seq.handleOnBattery()
        finally:
            release.set()

        assert events == ["poweroff"]

    def test_aRowCostsNoExtraRead_perPoll(self) -> None:
        """Wired or not, a drain-floor drain reads the gauge the same four times."""
        counts: dict[bool, int] = {}
        for wired in (False, True):
            events: list[str] = []
            release = threading.Event()
            reads = {"n": 0}
            script = _script([4.00, 3.90, 3.80, 3.55], then=3.55)

            def _vcell(reads=reads, script=script) -> float:
                reads["n"] += 1
                return script()

            try:
                _sequencer(
                    rows=_Rows() if wired else None, vcell=_vcell,
                    runPipelineFn=_blockingPipeline(release), events=events,
                ).handleOnBattery()
            finally:
                release.set()
            counts[wired] = reads["n"]

        assert counts == {False: 4, True: 4}

    def test_everyReadIsExactlyOneRow(self) -> None:
        rows, events, release = _Rows(), [], threading.Event()
        reads = {"n": 0}

        def _vcell() -> float:
            reads["n"] += 1
            if reads["n"] >= 3:
                release.set()
            return 3.90

        _sequencer(
            rows=rows, vcell=_vcell, runPipelineFn=_blockingPipeline(release), events=events,
        ).handleOnBattery()

        assert len(rows.rows) == reads["n"]
