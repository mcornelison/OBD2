################################################################################
# File Name: test_edr_log_gate.py
# Purpose/Description: US-767-b -- the EDR log gate state machine: a CLOSED gate
#                      buffers a monotonic pre-roll ring and writes nothing,
#                      opening flushes the ring in order, OPEN->HOLD keeps writing
#                      for holdSec and re-arms when the link returns. Two inputs
#                      (connected, signalReadable) follow Atlas's fail-OPEN table.
# Author: Rex (US-767-b)
# Creation Date: 2026-09-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-18    | Rex (US-767-b) | Initial -- state machine, fail-OPEN, disabled.
# ================================================================================
################################################################################
"""Tests for EdrLogGate (US-767-b): pre-roll, hold, fail-OPEN, disabled."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from pi.bus.edr_log_gate import (
    DEFAULT_HOLD_SEC,
    DEFAULT_PRE_ROLL_SEC,
    GATE_CLOSED,
    GATE_HOLD,
    GATE_OPEN,
    EdrLogGate,
)


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@dataclass
class _Status:
    """The two producer fields the gate reads (ConnectionStatus shape)."""

    connected: bool
    signalReadable: bool = True


class _Link:
    """A mutable link signal; ``raises`` makes the read itself fail."""

    def __init__(self, connected: bool, signalReadable: bool = True) -> None:
        self.connected = connected
        self.signalReadable = signalReadable
        self.raises = False
        self.reads = 0

    def __call__(self) -> _Status:
        self.reads += 1
        if self.raises:
            raise RuntimeError("no connection")
        return _Status(self.connected, self.signalReadable)


def _gate(link: _Link, clock: _Clock) -> EdrLogGate:
    return EdrLogGate(
        link, enabled=True, preRollSec=60.0, holdSec=300.0, monotonicFn=clock
    )


class TestDefaults:
    def test_defaults_are_atlasPlanValues(self) -> None:
        """
        Given: the module constants
        When: read
        Then: 60 s pre-roll and 300 s hold (Atlas's US-734 plan, Tasks 7-8)
        """
        assert DEFAULT_PRE_ROLL_SEC == 60.0
        assert DEFAULT_HOLD_SEC == 300.0

    @pytest.mark.parametrize("bad", [0, -1.0])
    def test_nonPositiveWindow_rejected(self, bad: float) -> None:
        """
        Given: a zero or negative pre-roll or hold
        When: the gate is built
        Then: ValueError -- a zero window is a permanently shut gate, not a knob
        """
        with pytest.raises(ValueError):
            EdrLogGate(None, preRollSec=bad)
        with pytest.raises(ValueError):
            EdrLogGate(None, holdSec=bad)


class TestClosedAndPreRoll:
    def test_closed_writesNothing(self) -> None:
        """
        Given: an enabled gate, link genuinely down (readable)
        When: rows are admitted
        Then: nothing is returned for writing and the gate is CLOSED
        """
        clock, link = _Clock(), _Link(connected=False)
        gate = _gate(link, clock)
        for i in range(5):
            clock.t = float(i)
            assert gate.admit("imu", (i,)) == []
        assert gate.state == GATE_CLOSED

    def test_open_flushesPreRollInOrder_thenWritesLive(self) -> None:
        """
        Given: three rows buffered while CLOSED
        When: the link opens and a row of another table arrives
        Then: the ring is flushed oldest first, then the live row
        """
        clock, link = _Clock(), _Link(connected=False)
        gate = _gate(link, clock)
        for i in range(3):
            clock.t = float(i)
            gate.admit("imu", (i,))
        link.connected = True
        clock.t = 3.0
        out = gate.admit("light", ("L",))
        assert out == [("imu", (0,)), ("imu", (1,)), ("imu", (2,)), ("light", ("L",))]
        assert gate.state == GATE_OPEN
        assert gate.lastTransition == (GATE_CLOSED, GATE_OPEN, "link_linked")
        clock.t = 4.0
        assert gate.admit("imu", (4,)) == [("imu", (4,))]

    def test_fiveMinutesClosed_thenOpen_emitsExactlyLast60s(self) -> None:
        """
        Given: the gate held CLOSED for a simulated 5 minutes, one row a second
        When: it opens at t=300
        Then: nothing was written while closed; exactly rows t=240..299 (the
            last 60 s) come out, in order, followed by the live row
        """
        clock, link = _Clock(), _Link(connected=False)
        gate = _gate(link, clock)
        written = []
        for i in range(300):
            clock.t = float(i)
            written.extend(gate.admit("imu", (i,)))
        assert written == []

        link.connected = True
        clock.t = 300.0
        out = gate.admit("imu", (300,))

        assert out == [("imu", (i,)) for i in range(240, 301)]

    def test_ring_isBoundedByPreRoll_whileClosed(self) -> None:
        """
        Given: a long CLOSED stretch
        When: rows keep arriving
        Then: the ring never holds more than the pre-roll window
        """
        clock, link = _Clock(), _Link(connected=False)
        gate = _gate(link, clock)
        for i in range(1000):
            clock.t = float(i)
            gate.admit("imu", (i,))
        assert gate.bufferedRows == 61  # t=939..999 inclusive


class TestHold:
    def test_hold_keepsWriting_thenCloses(self) -> None:
        """
        Given: an OPEN gate
        When: the link drops
        Then: rows keep landing for holdSec, then the gate CLOSES
        """
        clock, link = _Clock(), _Link(connected=True)
        gate = _gate(link, clock)
        gate.admit("imu", (0,))
        link.connected = False
        clock.t = 10.0
        assert gate.admit("imu", (1,)) == [("imu", (1,))]
        assert gate.state == GATE_HOLD
        clock.t = 309.0
        assert gate.admit("imu", (2,)) == [("imu", (2,))]
        clock.t = 311.0
        assert gate.admit("imu", (3,)) == []
        assert gate.state == GATE_CLOSED
        assert gate.lastTransition == (GATE_HOLD, GATE_CLOSED, "hold_expired")

    def test_linkDrop30s_writingNeverStops_andReArms(self) -> None:
        """
        Given: an OPEN gate with a row a second
        When: the link drops for 30 s, then returns
        Then: every row is written (inside the 300 s hold) and the gate re-arms
            to OPEN
        """
        clock, link = _Clock(), _Link(connected=True)
        gate = _gate(link, clock)
        written = []
        for i in range(100):
            clock.t = float(i)
            link.connected = not (40 <= i < 70)
            written.extend(gate.admit("imu", (i,)))
            if 40 <= i < 70:
                assert gate.state == GATE_HOLD
        assert written == [("imu", (i,)) for i in range(100)]
        assert gate.state == GATE_OPEN
        assert gate.lastTransition == (GATE_HOLD, GATE_OPEN, "link_linked")

    def test_hold_reArmsFromTheSecondDrop(self) -> None:
        """
        Given: a hold that re-armed when the link returned
        When: the link drops again
        Then: the hold window counts from the SECOND drop
        """
        clock, link = _Clock(), _Link(connected=True)
        gate = _gate(link, clock)
        gate.admit("imu", (0,))
        link.connected = False
        clock.t = 10.0
        gate.admit("imu", (1,))
        link.connected = True
        clock.t = 20.0
        gate.admit("imu", (2,))
        link.connected = False
        clock.t = 25.0
        gate.admit("imu", (3,))
        clock.t = 320.0  # 300 s after the first drop is 310; after the second, 325
        assert gate.admit("imu", (4,)) == [("imu", (4,))]


class TestFailOpenTable:
    def test_disconnected_readable_isClosed(self) -> None:
        """connected False + signalReadable True -> CLOSED (buffer)."""
        gate = _gate(_Link(connected=False, signalReadable=True), _Clock())
        assert gate.admit("imu", (0,)) == []
        assert gate.state == GATE_CLOSED

    def test_unreadable_isOpen_withOneRateLimitedWarning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: signalReadable False (connected False with it)
        When: rows arrive over 30 s
        Then: every row is written (OPEN) and exactly one WARNING is logged
        """
        clock, link = _Clock(), _Link(connected=False, signalReadable=False)
        gate = _gate(link, clock)
        with caplog.at_level(logging.WARNING, logger="pi.bus.edr_log_gate"):
            for i in range(30):
                clock.t = float(i)
                assert gate.admit("imu", (i,)) == [("imu", (i,))]
        assert gate.state == GATE_OPEN
        assert gate.lastTransition == (GATE_CLOSED, GATE_OPEN, "signal_unreadable")
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "unreadable" in warnings[0].getMessage()

    def test_unreadable_warnsAgain_afterTheInterval(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: a persistently unreadable signal
        When: more than the warning interval passes
        Then: a second WARNING -- rate-limited, not silenced
        """
        clock, link = _Clock(), _Link(connected=False, signalReadable=False)
        gate = _gate(link, clock)
        with caplog.at_level(logging.WARNING, logger="pi.bus.edr_log_gate"):
            gate.admit("imu", (0,))
            clock.t = 61.0
            gate.admit("imu", (1,))
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2

    def test_connected_isOpen(self) -> None:
        """connected True -> OPEN."""
        gate = _gate(_Link(connected=True), _Clock())
        assert gate.admit("imu", (0,)) == [("imu", (0,))]
        assert gate.state == GATE_OPEN

    def test_raisingInput_isUnreadable_isOpen(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: an input callable that RAISES
        When: a row is admitted
        Then: it is treated as signalReadable False -- OPEN, row written, WARNING
        """
        link = _Link(connected=False)
        link.raises = True
        gate = _gate(link, _Clock())
        with caplog.at_level(logging.WARNING, logger="pi.bus.edr_log_gate"):
            assert gate.admit("imu", (0,)) == [("imu", (0,))]
        assert link.reads == 1
        assert gate.state == GATE_OPEN
        assert gate.lastTransition == (GATE_CLOSED, GATE_OPEN, "signal_unreadable")
        assert any("no connection" in r.getMessage() for r in caplog.records)

    def test_unreadableWhileBuffering_flushesTheRing(self) -> None:
        """
        Given: rows buffered while genuinely down
        When: the signal becomes unreadable
        Then: the gate fails OPEN and the buffered pre-roll is written too
        """
        clock, link = _Clock(), _Link(connected=False)
        gate = _gate(link, clock)
        gate.admit("imu", (0,))
        link.signalReadable = False
        clock.t = 1.0
        assert gate.admit("imu", (1,)) == [("imu", (0,)), ("imu", (1,))]

    def test_noSignalSource_isUnreadable_isOpen(self) -> None:
        """An enabled gate with no signal wired cannot read it -> OPEN."""
        gate = EdrLogGate(None, enabled=True, monotonicFn=_Clock())
        assert gate.admit("imu", (0,)) == [("imu", (0,))]
        assert gate.state == GATE_OPEN


class TestDisabled:
    def test_disabled_isAlwaysOpen_andNeverReadsTheSignal(self) -> None:
        """
        Given: enabled False and a link that is genuinely down
        When: rows are admitted over a long stretch
        Then: every row is written as-is, the signal is never read, state OPEN
        """
        clock, link = _Clock(), _Link(connected=False)
        gate = EdrLogGate(link, enabled=False, monotonicFn=clock)
        for i in range(1000):
            clock.t = float(i)
            assert gate.admit("imu", (i,)) == [("imu", (i,))]
        assert link.reads == 0
        assert gate.state == GATE_OPEN
        assert gate.enabled is False
        assert gate.bufferedRows == 0

    def test_enabledDefaultsFalse(self) -> None:
        """A gate built without ``enabled`` is pass-through (never loses a row)."""
        gate = EdrLogGate(_Link(connected=False))
        assert gate.enabled is False
        assert gate.admit("imu", (0,)) == [("imu", (0,))]
