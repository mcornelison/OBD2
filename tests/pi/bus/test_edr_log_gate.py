################################################################################
# File Name: test_edr_log_gate.py
# Purpose/Description: US-767-b -- the EDR log gate state machine: a CLOSED gate
#                      buffers a monotonic pre-roll ring and writes nothing,
#                      opening flushes the ring in order, OPEN->HOLD keeps writing
#                      for holdSec and re-arms when the link returns. Two inputs
#                      US-793-b: the gate reads ECU reachability, not the
#                      Bluetooth link, and only a definite negative closes it.
# Author: Rex (US-767-b)
# Creation Date: 2026-09-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-18    | Rex (US-767-b) | Initial -- state machine, fail-OPEN, disabled.
# 2026-09-21    | Rex (US-793-b) | Driven by reachability (ANSWERED in place of
#               |                | connected=True, DID_NOT_ANSWER in place of
#               |                | False; Atlas option ii); one test per gate path.
# ================================================================================
################################################################################
"""Tests for EdrLogGate (US-767-b, US-793-b): pre-roll, hold, fail-OPEN, disabled."""

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
from pi.obdii.obd_connection import Reachability

ANSWERED = Reachability.ANSWERED
DID_NOT_ANSWER = Reachability.DID_NOT_ANSWER
NOT_YET_ATTEMPTED = Reachability.NOT_YET_ATTEMPTED
COULD_NOT_DETERMINE = Reachability.COULD_NOT_DETERMINE


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@dataclass
class _Status:
    """The producer fields (ConnectionStatus shape). Only reachability gates."""

    reachability: Reachability
    connected: bool = True
    signalReadable: bool = True


@dataclass
class _LegacyStatus:
    """A status WITHOUT reachability -- the pre-US-793-a producer shape."""

    connected: bool
    signalReadable: bool = True


class _Link:
    """A mutable signal; ``raises`` makes the read itself fail."""

    def __init__(self, reachability: Reachability, connected: bool = True) -> None:
        self.reachability = reachability
        self.connected = connected
        self.raises: BaseException | None = None
        self.reads = 0

    def __call__(self) -> _Status:
        self.reads += 1
        if self.raises is not None:
            raise self.raises
        return _Status(self.reachability, self.connected)


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
        clock, link = _Clock(), _Link(DID_NOT_ANSWER)
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
        clock, link = _Clock(), _Link(DID_NOT_ANSWER)
        gate = _gate(link, clock)
        for i in range(3):
            clock.t = float(i)
            gate.admit("imu", (i,))
        link.reachability = ANSWERED
        clock.t = 3.0
        out = gate.admit("light", ("L",))
        assert out == [("imu", (0,)), ("imu", (1,)), ("imu", (2,)), ("light", ("L",))]
        assert gate.state == GATE_OPEN
        assert gate.lastTransition == (GATE_CLOSED, GATE_OPEN, "ecu_answered")
        clock.t = 4.0
        assert gate.admit("imu", (4,)) == [("imu", (4,))]

    def test_fiveMinutesClosed_thenOpen_emitsExactlyLast60s(self) -> None:
        """
        Given: the gate held CLOSED for a simulated 5 minutes, one row a second
        When: it opens at t=300
        Then: nothing was written while closed; exactly rows t=240..299 (the
            last 60 s) come out, in order, followed by the live row
        """
        clock, link = _Clock(), _Link(DID_NOT_ANSWER)
        gate = _gate(link, clock)
        written = []
        for i in range(300):
            clock.t = float(i)
            written.extend(gate.admit("imu", (i,)))
        assert written == []

        link.reachability = ANSWERED
        clock.t = 300.0
        out = gate.admit("imu", (300,))

        assert out == [("imu", (i,)) for i in range(240, 301)]

    def test_ring_isBoundedByPreRoll_whileClosed(self) -> None:
        """
        Given: a long CLOSED stretch
        When: rows keep arriving
        Then: the ring never holds more than the pre-roll window
        """
        clock, link = _Clock(), _Link(DID_NOT_ANSWER)
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
        clock, link = _Clock(), _Link(ANSWERED)
        gate = _gate(link, clock)
        gate.admit("imu", (0,))
        link.reachability = DID_NOT_ANSWER
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
        clock, link = _Clock(), _Link(ANSWERED)
        gate = _gate(link, clock)
        written = []
        for i in range(100):
            clock.t = float(i)
            link.reachability = DID_NOT_ANSWER if 40 <= i < 70 else ANSWERED
            written.extend(gate.admit("imu", (i,)))
            if 40 <= i < 70:
                assert gate.state == GATE_HOLD
        assert written == [("imu", (i,)) for i in range(100)]
        assert gate.state == GATE_OPEN
        assert gate.lastTransition == (GATE_HOLD, GATE_OPEN, "ecu_answered")

    def test_hold_reArmsFromTheSecondDrop(self) -> None:
        """
        Given: a hold that re-armed when the link returned
        When: the link drops again
        Then: the hold window counts from the SECOND drop
        """
        clock, link = _Clock(), _Link(ANSWERED)
        gate = _gate(link, clock)
        gate.admit("imu", (0,))
        link.reachability = DID_NOT_ANSWER
        clock.t = 10.0
        gate.admit("imu", (1,))
        link.reachability = ANSWERED
        clock.t = 20.0
        gate.admit("imu", (2,))
        link.reachability = DID_NOT_ANSWER
        clock.t = 25.0
        gate.admit("imu", (3,))
        clock.t = 320.0  # 300 s after the first drop is 310; after the second, 325
        assert gate.admit("imu", (4,)) == [("imu", (4,))]


class TestFailOpenTable:
    def test_didNotAnswer_isClosed(self) -> None:
        """DID_NOT_ANSWER -> CLOSED (buffer)."""
        gate = _gate(_Link(DID_NOT_ANSWER), _Clock())
        assert gate.admit("imu", (0,)) == []
        assert gate.state == GATE_CLOSED

    def test_couldNotDetermine_isOpen_withOneRateLimitedWarning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: reachability COULD_NOT_DETERMINE
        When: rows arrive over 30 s
        Then: every row is written (OPEN) and exactly one WARNING is logged
        """
        clock, link = _Clock(), _Link(COULD_NOT_DETERMINE)
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

    def test_couldNotDetermine_warnsAgain_afterTheInterval(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: a persistently undeterminable signal
        When: more than the warning interval passes
        Then: a second WARNING -- rate-limited, not silenced
        """
        clock, link = _Clock(), _Link(COULD_NOT_DETERMINE)
        gate = _gate(link, clock)
        with caplog.at_level(logging.WARNING, logger="pi.bus.edr_log_gate"):
            gate.admit("imu", (0,))
            clock.t = 61.0
            gate.admit("imu", (1,))
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2

    def test_answered_isOpen(self) -> None:
        """ANSWERED -> OPEN."""
        gate = _gate(_Link(ANSWERED), _Clock())
        assert gate.admit("imu", (0,)) == [("imu", (0,))]
        assert gate.state == GATE_OPEN

    def test_raisingInput_isUnreadable_isOpen(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: an input callable that RAISES
        When: a row is admitted
        Then: OPEN, row written, WARNING naming the failure
        """
        link = _Link(DID_NOT_ANSWER)
        link.raises = RuntimeError("no connection")
        gate = _gate(link, _Clock())
        with caplog.at_level(logging.WARNING, logger="pi.bus.edr_log_gate"):
            assert gate.admit("imu", (0,)) == [("imu", (0,))]
        assert link.reads == 1
        assert gate.state == GATE_OPEN
        assert gate.lastTransition == (GATE_CLOSED, GATE_OPEN, "signal_unreadable")
        assert any("no connection" in r.getMessage() for r in caplog.records)

    def test_undeterminableWhileBuffering_flushesTheRing(self) -> None:
        """
        Given: rows buffered while the ECU did not answer
        When: reachability becomes COULD_NOT_DETERMINE
        Then: the gate fails OPEN and the buffered pre-roll is written too
        """
        clock, link = _Clock(), _Link(DID_NOT_ANSWER)
        gate = _gate(link, clock)
        gate.admit("imu", (0,))
        link.reachability = COULD_NOT_DETERMINE
        clock.t = 1.0
        assert gate.admit("imu", (1,)) == [("imu", (0,)), ("imu", (1,))]

    def test_noSignalSource_isUnreadable_isOpen(self) -> None:
        """An enabled gate with no signal wired cannot read it -> OPEN."""
        gate = EdrLogGate(None, enabled=True, monotonicFn=_Clock())
        assert gate.admit("imu", (0,)) == [("imu", (0,))]
        assert gate.state == GATE_OPEN


class TestReachabilityGatesCapture:
    """US-793-b: the ECU gates capture, not the Bluetooth link.

    Only a definite negative closes the gate; every "we do not know" is OPEN
    and loud (Atlas 2026-09-21: closing wrongly loses rows for good, opening
    wrongly costs disk).
    """

    def test_linkedButEcuSilent_isClosed(self) -> None:
        """
        Given: connected=True (dongle linked) and DID_NOT_ANSWER (no ECU)
        When: a row is admitted
        Then: CLOSED and buffering -- the pre-fix gate, reading ``connected``,
            is OPEN here, which is the parked-car defect
        """
        gate = _gate(_Link(DID_NOT_ANSWER, connected=True), _Clock())
        assert gate.admit("imu", (0,)) == []
        assert gate.state == GATE_CLOSED
        assert gate.bufferedRows == 1

    def test_notYetAttempted_isClosed_evenWhenLinked(self) -> None:
        """
        Given: a cold boot on a parked car -- linked, no ECU read yet
        When: a row is admitted
        Then: CLOSED; NOT_YET_ATTEMPTED is a known state, not "cannot tell"
        """
        gate = _gate(_Link(NOT_YET_ATTEMPTED, connected=True), _Clock())
        assert gate.admit("imu", (0,)) == []
        assert gate.state == GATE_CLOSED

    def test_answered_isOpen_evenWhenLinkReadsDown(self) -> None:
        """
        Given: ANSWERED with connected=False
        When: a row is admitted
        Then: OPEN -- the link field is not read at all
        """
        gate = _gate(_Link(ANSWERED, connected=False), _Clock())
        assert gate.admit("imu", (0,)) == [("imu", (0,))]
        assert gate.state == GATE_OPEN
        assert gate.lastTransition == (GATE_CLOSED, GATE_OPEN, "ecu_answered")

    @pytest.mark.parametrize(
        "exc",
        [
            RuntimeError("no OBD connection object"),
            ValueError("bad status"),
            AttributeError("half-built connection"),
            OSError("port gone"),
            KeyError("config"),
        ],
        ids=lambda e: type(e).__name__,
    )
    def test_everyRaise_isOpen_andWarns(
        self, exc: Exception, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: a signal callable raising any exception, not only no-connection
        When: a row is admitted
        Then: OPEN and the rate-limited WARNING
        """
        link = _Link(DID_NOT_ANSWER)
        link.raises = exc
        gate = _gate(link, _Clock())
        with caplog.at_level(logging.WARNING, logger="pi.bus.edr_log_gate"):
            assert gate.admit("imu", (0,)) == [("imu", (0,))]
        assert gate.state == GATE_OPEN
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    @pytest.mark.parametrize("connected", [False, True])
    def test_statusWithoutReachability_isOpen_neverFallsBackToConnected(
        self, connected: bool, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: a producer whose status has NO reachability field, including a
            readable connected=False (which the legacy table closed on)
        When: a row is admitted
        Then: COULD_NOT_DETERMINE semantics -- OPEN + WARNING. A silent
            fallback to ``connected`` would keep the Bluetooth-link defect for
            any producer lacking the field, with nothing reporting it
        """
        gate = _gate(lambda: _LegacyStatus(connected=connected), _Clock())
        with caplog.at_level(logging.WARNING, logger="pi.bus.edr_log_gate"):
            assert gate.admit("imu", (0,)) == [("imu", (0,))]
        assert gate.state == GATE_OPEN
        assert gate.lastTransition == (GATE_CLOSED, GATE_OPEN, "signal_unreadable")
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "reachability" in warnings[0].getMessage()

    @pytest.mark.parametrize("value", ["garbage", None, "", 3])
    def test_valueOutsideTheVocabulary_isOpen_andWarns(
        self, value: object, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: a reachability value that is none of the four states
        When: a row is admitted
        Then: OPEN + WARNING -- only a DEFINITE negative closes the gate
        """
        gate = _gate(lambda: _Status(value), _Clock())  # type: ignore[arg-type]
        with caplog.at_level(logging.WARNING, logger="pi.bus.edr_log_gate"):
            assert gate.admit("imu", (0,)) == [("imu", (0,))]
        assert gate.state == GATE_OPEN
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    @pytest.mark.parametrize(
        ("state", "isOpen"),
        [
            (ANSWERED, True),
            (DID_NOT_ANSWER, False),
            (NOT_YET_ATTEMPTED, False),
            (COULD_NOT_DETERMINE, True),
        ],
    )
    def test_everyProducerState_hasAnExplicitMapping(
        self, state: Reachability, isOpen: bool
    ) -> None:
        """
        Given: each of the producer's reachability states, by its real enum
        When: a row is admitted to a fresh gate
        Then: the ruled mapping
        """
        gate = _gate(_Link(state), _Clock())
        written = gate.admit("imu", (0,))
        assert (written == [("imu", (0,))]) is isOpen
        assert gate.state == (GATE_OPEN if isOpen else GATE_CLOSED)

    def test_mappingCoversEveryProducerState(self) -> None:
        """The four-state table above is the producer's whole vocabulary --
        a fifth state fails here until the gate maps it explicitly."""
        assert set(Reachability) == {
            ANSWERED, DID_NOT_ANSWER, NOT_YET_ATTEMPTED, COULD_NOT_DETERMINE,
        }

    def test_didNotAnswerThenAnswered_releasesPreRollUnchanged(self) -> None:
        """
        Given: rows buffered on DID_NOT_ANSWER
        When: reachability becomes ANSWERED
        Then: the pre-roll is released in order, exactly as US-767-b specified
        """
        clock, link = _Clock(), _Link(DID_NOT_ANSWER, connected=True)
        gate = _gate(link, clock)
        for i in range(3):
            clock.t = float(i)
            assert gate.admit("imu", (i,)) == []
        link.reachability = ANSWERED
        clock.t = 3.0
        assert gate.admit("imu", (3,)) == [("imu", (i,)) for i in range(4)]


class TestDisabled:
    def test_disabled_isAlwaysOpen_andNeverReadsTheSignal(self) -> None:
        """
        Given: enabled False and a link that is genuinely down
        When: rows are admitted over a long stretch
        Then: every row is written as-is, the signal is never read, state OPEN
        """
        clock, link = _Clock(), _Link(DID_NOT_ANSWER)
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
        gate = EdrLogGate(_Link(DID_NOT_ANSWER))
        assert gate.enabled is False
        assert gate.admit("imu", (0,)) == [("imu", (0,))]
