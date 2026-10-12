################################################################################
# File Name: test_capture_health.py
# Purpose/Description: US-688 (F-138) -- the CONSUMER for the capture-health
#                      signal the Pi has been logging, and nothing has read,
#                      since US-302. `data_logger_last_row_seconds_ago` went out
#                      every 60 s reading `never_written` for TWO DAYS
#                      (2026-09-04 18:59:47Z onward) while a loose dongle
#                      produced 41 failed reconnects and zero rows. The outage
#                      lasting two days is a REPORTING defect, not a connector
#                      defect.
#
#                      🔴 THE TRAP, AND IT IS THIS STORY'S WHOLE DESIGN. The
#                      story asks for the alert to be gated on "the engine
#                      running". EVERY engine-running signal this system owns --
#                      RPM (PID 0x0C), the alternator-voltage escalation
#                      (BATTERY_V, PID 0x42), and drive detection, which is
#                      derived from both -- arrives over THE OBDLINK BLUETOOTH
#                      TRANSPORT. That is the same transport whose failure IS the
#                      incident. Gate the alert on any of them and it CANNOT FIRE
#                      in the one case it was written for: the dongle falls out,
#                      RPM stops, and the "engine running" precondition goes
#                      false at exactly the instant capture dies.
#
#                      So the gate is the POWER SOURCE, which is sensed on the
#                      X1209 GPIO6 PLD line -- a DIFFERENT transport, which
#                      survives the dongle. It is pinned below by name, in both
#                      directions, and the dead-branch case is asserted
#                      explicitly rather than left as prose.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-08    | Rex (US-688) | Initial -- the capture-health decision, its
#               |              | off-transport gate, and the four states.
# ================================================================================
################################################################################

"""US-688: capture can produce zero rows for a whole drive and say nothing.

WHAT THIS PRODUCER CLAIMS, precisely.  ``stalled`` says *the Pi is running on
the car's power and the data logger has written no row for longer than the
stall window*.  It does NOT claim the engine is turning -- nothing off the OBD
transport can tell us that, and everything ON the OBD transport is gone in the
failure this story exists to report.  The over-claim is in the SAFE direction
(key-on-engine-off is still a state in which rows ought to be landing) and it is
named here rather than hidden behind a parameter called ``engineRunning``.

THE NEGATIVE CASE IS LOAD-BEARING and it is what the power gate buys.  A parked
Pi with the key off has lost fuse-box power and is running down its UPS toward a
graceful poweroff -- ``powerSource == "battery"``.  Absence of data there is
expected, not a fault, and an alert that fired on every key-off would be ignored
inside a week.
"""

from __future__ import annotations

import pytest

from src.pi.obdii import capture_health as ch

# The stall window used throughout. A LITERAL here on purpose: these tests must
# fail if the shipped default moves without someone re-reading the grounding,
# so the value is never imported from the module under test.
_STALL_S = 60.0

_NOW = "2026-09-08T12:00:00Z"


def _build(**kw):
    """Build a payload with the healthy shape as the baseline.

    Every test below states ONLY the fact it is about. A helper that defaulted
    to the FAULT shape would let a test pass because the baseline was already
    broken, which is the shape of a fixture that has stopped discriminating.
    """
    args = {
        "lastRowSecondsAgo": 1.0,
        "freshnessReason": None,
        "powerSource": "external",
        "stallSeconds": _STALL_S,
        "nowIso": _NOW,
    }
    args.update(kw)
    return ch.buildCaptureHealthState(**args)


# ---------------------------------------------------------------- the incident


class TestTheIncident:
    """The 2026-09-04 outage, reproduced as the fixture that motivated the story."""

    def test_buildCaptureHealthState_neverWrittenOnCarPower_isStalled(self) -> None:
        """
        Given: the Pi is on car power and the logger has NEVER written a row
        When: capture health is evaluated
        Then: the state is `stalled` -- the alert the operator never got

        This is `data_logger_last_row_seconds_ago=never_written`, the literal
        line the Pi logged every 60 s for two days.
        """
        state = _build(
            lastRowSecondsAgo=None,
            freshnessReason=ch.REASON_NEVER_WRITTEN,
        )

        assert state["state"] == ch.STATE_STALLED
        assert state["reason"] == ch.REASON_NEVER_WRITTEN

    def test_buildCaptureHealthState_stallsWithNoObdDataAtAll_stillFires(self) -> None:
        """
        Given: the dongle is out -- no RPM, no speed, no link, nothing on OBD
        When: capture health is evaluated on car power
        Then: `stalled` STILL fires

        🔴 THE DEAD-BRANCH GUARD. This producer takes NO OBD-derived argument at
        all -- no rpm, no linkState, no driveState. That is deliberate and this
        test is what holds it: the incident removed every one of those signals,
        so an implementation that consulted any of them would go quiet at exactly
        the moment it was needed. If someone later adds an `engineRunning`
        parameter sourced from RPM, this test keeps passing but the SIGNATURE
        test below fails -- they are a pair.
        """
        state = _build(
            lastRowSecondsAgo=None,
            freshnessReason=ch.REASON_NEVER_WRITTEN,
        )

        assert state["state"] == ch.STATE_STALLED

    def test_buildCaptureHealthState_takesNoObdDerivedInput(self) -> None:
        """
        Given: the producer's signature
        When: its parameters are inspected
        Then: none of them is an OBD-derived engine/link/drive signal

        The companion to the test above, and the one that actually FAILS if a
        future edit reaches for RPM. Asserting on the signature is the only way
        to pin "this decision must not depend on the dead transport" -- a
        behavioural test cannot see an argument that is merely available.
        """
        import inspect

        params = set(inspect.signature(ch.buildCaptureHealthState).parameters)

        forbidden = {
            "rpm", "speed", "engineRunning", "linkState", "linkHealthy",
            "obdAvailable", "driveState", "batteryVoltage",
        }
        assert params & forbidden == set(), (
            "capture health must not depend on the OBD transport -- that is the "
            "transport whose failure this alert reports"
        )


# ------------------------------------------------------------- the negative case


class TestTheNegativeCase:
    """A parked Pi with the key off must never alert. Expected absence is not a fault."""

    def test_buildCaptureHealthState_neverWrittenOnBattery_isIdleNotStalled(self) -> None:
        """
        Given: the key is off, so the Pi has lost fuse-box power and is on the UPS
        When: capture health is evaluated with no rows ever written
        Then: `idle` -- NOT `stalled`, and no alert

        The story's stated negative case. `battery` is the sensed fact that the
        car's power is gone; it is the same input in the opposite direction from
        the incident test, so a producer that ignored `powerSource` would fail
        exactly one of the two.
        """
        state = _build(
            lastRowSecondsAgo=None,
            freshnessReason=ch.REASON_NEVER_WRITTEN,
            powerSource="battery",
        )

        assert state["state"] == ch.STATE_IDLE
        assert state["state"] != ch.STATE_STALLED

    def test_buildCaptureHealthState_longStaleOnBattery_isStillIdle(self) -> None:
        """
        Given: the key is off and the last row is far older than the stall window
        When: capture health is evaluated
        Then: still `idle`

        Paired with the test above so `idle` is not satisfied only by the
        never-written shape. A Pi that has just been switched off has a REAL,
        AGEING last-row time -- that is the ordinary key-off state, and it is
        the one that would nuisance-fire on every single drive.
        """
        state = _build(
            lastRowSecondsAgo=_STALL_S * 10,
            powerSource="battery",
        )

        assert state["state"] == ch.STATE_IDLE

    def test_buildCaptureHealthState_powerUnknown_isUnknownNeverStalled(self) -> None:
        """
        Given: the power line cannot be read at all
        When: capture health is evaluated with no rows ever written
        Then: `unknown` -- neither a confident alert nor a confident all-clear

        An unreadable gate must not manufacture an alert (crying wolf) OR an
        all-clear (green-when-broken). `unknown` blocks green without alarming,
        which is this dashboard's existing word for a known-unknown.
        """
        state = _build(
            lastRowSecondsAgo=None,
            freshnessReason=ch.REASON_NEVER_WRITTEN,
            powerSource="unknown",
        )

        assert state["state"] == ch.STATE_UNKNOWN
        assert state["state"] != ch.STATE_STALLED


# ------------------------------------------------------------------ the window


class TestTheStallWindow:
    """The threshold is a boundary, and both sides of it are asserted."""

    def test_buildCaptureHealthState_rowsArrivingNormally_isOk(self) -> None:
        """
        Given: a row landed one second ago on car power
        When: capture health is evaluated
        Then: `ok` -- no alert
        """
        assert _build(lastRowSecondsAgo=1.0)["state"] == ch.STATE_OK

    def test_buildCaptureHealthState_justInsideTheWindow_isOk(self) -> None:
        """
        Given: the last row is one second short of the stall window
        When: capture health is evaluated
        Then: `ok`

        Straddles the boundary with the test below. A producer with an
        off-by-one or an inverted comparison splits this pair.
        """
        assert _build(lastRowSecondsAgo=_STALL_S - 1.0)["state"] == ch.STATE_OK

    def test_buildCaptureHealthState_justOutsideTheWindow_isStalled(self) -> None:
        """
        Given: the last row is one second past the stall window
        When: capture health is evaluated
        Then: `stalled`
        """
        state = _build(lastRowSecondsAgo=_STALL_S + 1.0)

        assert state["state"] == ch.STATE_STALLED
        assert state["reason"] == ch.REASON_STALLED

    def test_buildCaptureHealthState_theWindowIsTheParameterNotAConstant(self) -> None:
        """
        Given: an age that stalls at a 60 s window
        When: the SAME age is evaluated against a 600 s window
        Then: `ok`

        Pins the threshold as a real input rather than decoration. A producer
        that ignored `stallSeconds` and hardcoded its own would pass every other
        test in this file -- they all use the default value.
        """
        aged = _STALL_S + 1.0

        assert _build(lastRowSecondsAgo=aged)["state"] == ch.STATE_STALLED
        assert _build(lastRowSecondsAgo=aged, stallSeconds=600.0)["state"] == ch.STATE_OK


# ------------------------------------------------------------------ recovery


class TestRecovery:
    """The alert must CLEAR, not latch. A stuck alarm is its own dishonesty."""

    def test_buildCaptureHealthState_rowResumesAfterAStall_returnsToOk(self) -> None:
        """
        Given: capture stalled, then a row lands
        When: capture health is re-evaluated
        Then: `ok` -- the alert clears

        The producer is stateless by construction, so this cannot latch. Pinned
        anyway: the story asks for it by name, and a future edit that adds
        hysteresis (a reasonable thing to want) must not make it permanent.
        """
        stalled = _build(lastRowSecondsAgo=_STALL_S + 1.0)
        assert stalled["state"] == ch.STATE_STALLED

        recovered = _build(lastRowSecondsAgo=0.5)
        assert recovered["state"] == ch.STATE_OK
        assert recovered["reason"] is None


# -------------------------------------------------------- absent / unreadable


class TestTheLoggerItself:
    """`never written` and `no logger at all` are DIFFERENT facts."""

    def test_buildCaptureHealthState_loggerAbsent_isUnknownNotStalled(self) -> None:
        """
        Given: no data logger is wired into this orchestrator at all
        When: capture health is evaluated on car power
        Then: `unknown` -- NOT `stalled`

        🔴 THE DISTINCTION THE UPSTREAM READER LOSES. US-302's
        `_readDataLoggerLastRowSecondsAgo` returns None for BOTH "the logger
        exists and has written nothing" (a MEASUREMENT, and the incident) and
        "there is no logger" (an ABSENCE). Alerting on the second would fire on
        every bench run that omits the logger, which is how an alert gets
        ignored. The typed reason is what separates them.
        """
        state = _build(
            lastRowSecondsAgo=None,
            freshnessReason=ch.REASON_LOGGER_ABSENT,
        )

        assert state["state"] == ch.STATE_UNKNOWN
        assert state["reason"] == ch.REASON_LOGGER_ABSENT

    def test_buildCaptureHealthState_loggerUnreadable_isUnknownNotStalled(self) -> None:
        """
        Given: the logger's freshness property could not be read
        When: capture health is evaluated on car power
        Then: `unknown` -- a fault in the Pi is not a claim about capture
        """
        state = _build(
            lastRowSecondsAgo=None,
            freshnessReason=ch.REASON_UNREADABLE,
        )

        assert state["state"] == ch.STATE_UNKNOWN

    def test_buildCaptureHealthState_neverWrittenIsNotTheSameStateAsAbsent(self) -> None:
        """
        Given: the two None-valued freshness shapes
        When: both are evaluated on car power
        Then: they reach DIFFERENT states

        The non-vacuity check for the pair above. Both tests pass for a producer
        that returns `unknown` for every None, so the discrimination has to be
        asserted directly.
        """
        neverWritten = _build(
            lastRowSecondsAgo=None, freshnessReason=ch.REASON_NEVER_WRITTEN
        )
        absent = _build(
            lastRowSecondsAgo=None, freshnessReason=ch.REASON_LOGGER_ABSENT
        )

        assert neverWritten["state"] != absent["state"]


# ------------------------------------------------------------------- payload


class TestThePayload:
    """The state file's shape is a contract the renderer is tested against."""

    def test_buildCaptureHealthState_carriesTheAgeAndTheWindowItWasJudgedAgainst(
        self,
    ) -> None:
        """
        Given: a stalled capture
        When: the payload is built
        Then: it carries BOTH the age and the window

        A bare `stalled` cannot be checked by anyone reading the state file. The
        window travels with it because "no rows for 90 s" means nothing without
        "and we alert past 60".
        """
        state = _build(lastRowSecondsAgo=90.0)

        assert state["lastRowSecondsAgo"] == 90.0
        assert state["stallSeconds"] == _STALL_S
        assert state["ts"] == _NOW

    def test_buildCaptureHealthState_neverWrittenPublishesNullAgeNeverZero(self) -> None:
        """
        Given: the logger has never written a row
        When: the payload is built
        Then: `lastRowSecondsAgo` is null, NEVER 0

        Zero is the single most reassuring value this field can take -- "a row
        landed just now" -- and it is the exact opposite of the truth. Same
        fabrication the project has already caught on altitude and on sync
        `pending`.
        """
        state = _build(
            lastRowSecondsAgo=None, freshnessReason=ch.REASON_NEVER_WRITTEN
        )

        assert state["lastRowSecondsAgo"] is None

    @pytest.mark.parametrize(
        "powerSource,freshnessReason,expected",
        [
            ("external", None, ch.STATE_OK),
            ("battery", None, ch.STATE_IDLE),
            ("unknown", None, ch.STATE_UNKNOWN),
        ],
    )
    def test_buildCaptureHealthState_everyPowerSourceResolves(
        self, powerSource: str, freshnessReason: str | None, expected: str
    ) -> None:
        """
        Given: each value `_gatherPowerSource` can return
        When: capture health is evaluated with rows landing normally
        Then: every one resolves to a defined state

        Swept over the producer's whole input vocabulary rather than the two
        interesting values, so an unhandled source cannot fall through to a
        default nobody chose.
        """
        state = _build(powerSource=powerSource, freshnessReason=freshnessReason)

        assert state["state"] == expected

    def test_buildCaptureHealthState_unrecognisedPowerSourceIsUnknownNotOk(self) -> None:
        """
        Given: a power source token this producer has never been taught
        When: capture health is evaluated
        Then: `unknown` -- never `ok`

        A future power vocabulary must not be able to paint capture healthy by
        default. Same rule `sysLevelRank` applies in the renderer.
        """
        assert _build(powerSource="solar")["state"] == ch.STATE_UNKNOWN
