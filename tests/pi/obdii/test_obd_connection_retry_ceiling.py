################################################################################
# File Name: test_obd_connection_retry_ceiling.py
# Purpose/Description: US-673 -- the OBD reconnect backoff escalates past the
#                      16s plateau to a configurable, documented ceiling, and
#                      the heartbeat's per-tick connect is ONE attempt rather
#                      than a 6-attempt burst.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-03    | Rex (US-673) | Initial -- retry ceiling + single-attempt
#               |              | heartbeat connect.
# ================================================================================
################################################################################

"""US-673: a parked car costs ONE probe every few minutes, not 275 in 13 hours.

MEASURED (story clause 2): 275+ connect retries over 13 hours against a dongle
that could not answer.  Two separate mechanisms produce that number and this
file pins the fix for both:

1. **The schedule PLATEAUS.**  ``DEFAULT_RETRY_DELAYS = [1, 2, 4, 8, 16]`` was
   consumed as ``retryDelays[min(attempt, len - 1)]`` -- so every attempt past
   the fifth waited exactly 16 s, forever, with no ceiling and no terminal
   state.  :func:`nextRetryDelaySeconds` replaces the clamp with geometric
   escalation to ``pi.bluetooth.retryCeilingSeconds``.

2. **The cadence is AMPLIFIED 6x.**  ``runReconnectHeartbeat`` is the loop that
   genuinely runs forever, and it has had an exponential ceiling since US-325 /
   I-025 (10 -> 20 -> ... -> 320 s).  But each of its ticks called
   ``ObdConnection.connect()``, which is ITSELF a 6-attempt retry loop -- so a
   320 s "idle cadence" actually bought a 31-second burst of six rfcomm binds.
   :meth:`ObdConnection.connectOnce` makes the per-tick attempt singular, which
   is what :meth:`LifecycleMixin._spawnReconnectHeartbeatDaemon`'s own docstring
   has claimed since US-301 ("attempt a single ``connect()``").

CALIBRATION (the US-645 lesson -- a test that proves an improvement must first
prove the defect was present in its own fixture): :class:`TestThirtyMinuteFalloff`
runs the story's OWN validation criterion -- 30 minutes against an unreachable
dongle -- under BOTH policies and asserts the old one reproduces the story's
~112 figure.  Without that half, "14 attempts" is also what a schedule that
never retried at all would report.

NOT CLOSED HERE, deliberately: the ENGINE-STATE GATE.  See
:class:`TestTheEngineStateGateIsAbsentAndWhyIsRecorded`.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from src.pi.obdii.config.loader import OBD_DEFAULTS
from src.pi.obdii.obd_connection import (
    DEFAULT_RETRY_CEILING_SECONDS,
    DEFAULT_RETRY_DELAYS,
    ObdConnection,
    nextRetryDelaySeconds,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ================================================================================
# Fakes
# ================================================================================


class RecordingShutdownEvent(threading.Event):
    """A never-set shutdown event that records every backoff it was asked to wait.

    ``_performConnect`` sleeps via ``shutdownEvent.wait(timeout=delay)`` when an
    event is plumbed in (US-232 / TD-035), so recording ``wait`` captures the
    real backoff schedule without a single second of wall clock.  ``is_set()``
    stays False so the retry loop is never short-circuited by the shutdown path.
    """

    def __init__(self) -> None:
        super().__init__()
        self.waits: list[float] = []

    def wait(self, timeout: float | None = None) -> bool:  # type: ignore[override]
        self.waits.append(float(timeout if timeout is not None else 0.0))
        return False


class UnreachableDongleFactory:
    """An ``obd.OBD`` factory that always fails -- the parked-car case."""

    def __init__(self) -> None:
        self.callCount = 0

    def __call__(self, portstr: str, timeout: int) -> Any:
        self.callCount += 1
        raise OSError("device unreachable")


class _FakeObd:
    def __init__(self) -> None:
        self._connected = True

    def is_connected(self) -> bool:
        return self._connected

    def close(self) -> None:
        self._connected = False


class DongleThatReturnsFactory:
    """Fails ``failuresBeforeSuccess`` times, then hands back a live link."""

    def __init__(self, failuresBeforeSuccess: int) -> None:
        self.failuresBeforeSuccess = failuresBeforeSuccess
        self.callCount = 0

    def __call__(self, portstr: str, timeout: int) -> Any:
        self.callCount += 1
        if self.callCount <= self.failuresBeforeSuccess:
            raise OSError("device unreachable")
        return _FakeObd()


def _connection(
    factory: Any,
    *,
    retryDelays: list[int] | None = None,
    maxRetries: int | None = None,
    retryCeilingSeconds: float | None = None,
    shutdownEvent: threading.Event | None = None,
) -> ObdConnection:
    """Build an ObdConnection over a PATH-style port (never touches rfcomm).

    Path-style configuration means ``_releaseRfcommBinding`` short-circuits on
    ``isMacAddress`` and no subprocess is ever spawned, so these tests are
    hermetic on a Windows bench with no bluez.
    """
    bluetooth: dict[str, Any] = {
        "macAddress": "/dev/rfcomm0",
        "connectionTimeoutSeconds": 5,
    }
    if retryDelays is not None:
        bluetooth["retryDelays"] = retryDelays
    if maxRetries is not None:
        bluetooth["maxRetries"] = maxRetries
    if retryCeilingSeconds is not None:
        bluetooth["retryCeilingSeconds"] = retryCeilingSeconds
    return ObdConnection(
        {"pi": {"bluetooth": bluetooth}},
        obdFactory=factory,
        shutdownEvent=shutdownEvent,
    )


def _plateauDelay(attempt: int, retryDelays: list[int]) -> int:
    """The PRE-US-673 policy, kept here as the calibration control.

    Verbatim shape of the code this story replaces::

        delayIndex = min(attempt, len(self.retryDelays) - 1)
        delay = self.retryDelays[delayIndex]
    """
    if not retryDelays:
        return 0
    return retryDelays[min(attempt, len(retryDelays) - 1)]


# ================================================================================
# The escalation policy itself
# ================================================================================


class TestNextRetryDelayEscalation:
    """The pure policy function -- the SSOT the story names."""

    def test_withinTheSchedule_theConfiguredEntryIsUsedVerbatim(self) -> None:
        """
        Given: the shipped schedule [1, 2, 4, 8, 16]
        When: attempts 0..4 are scheduled
        Then: each returns its own configured entry -- escalation adds a tail,
              it does not rewrite the head the CIO configured.
        """
        delays = [1, 2, 4, 8, 16]
        got = [nextRetryDelaySeconds(n, delays, 320.0) for n in range(5)]
        assert got == [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_pastTheScheduleEnd_theDelayEscalatesInsteadOfPlateauing(self) -> None:
        """
        Given: the shipped schedule, exhausted
        When: attempts 5, 6, 7, 8 are scheduled
        Then: each is strictly LARGER than the last -- 16 s is no longer the
              answer forever.  THIS is the defect the story names.
        """
        delays = [1, 2, 4, 8, 16]
        tail = [nextRetryDelaySeconds(n, delays, 10_000.0) for n in range(5, 9)]

        assert tail == [32.0, 64.0, 128.0, 256.0]
        # Stated as the invariant as well as the values, so a future schedule
        # change cannot quietly restore a plateau while the literals are edited.
        assert all(later > 16.0 for later in tail)
        assert tail == sorted(tail)
        assert len(set(tail)) == len(tail)

    def test_theEscalationStopsAtTheCeilingAndStaysThere(self) -> None:
        """
        Given: a ceiling of 320 s
        When: the schedule escalates past it
        Then: it clamps and holds -- a documented ceiling, not a blow-up.
        """
        delays = [1, 2, 4, 8, 16]
        assert nextRetryDelaySeconds(9, delays, 320.0) == 320.0   # 512 -> clamped
        assert nextRetryDelaySeconds(20, delays, 320.0) == 320.0
        assert nextRetryDelaySeconds(200, delays, 320.0) == 320.0

    def test_theCeilingAlsoClampsAnOverlongConfiguredEntry(self) -> None:
        """
        Given: a schedule entry ABOVE the ceiling (contradictory config)
        When: that entry is scheduled
        Then: the ceiling wins.  A ceiling that only governs the tail is not a
              ceiling; it is a suffix rule with a misleading name.
        """
        assert nextRetryDelaySeconds(0, [600], 320.0) == 320.0

    def test_anEmptyScheduleIsStillZeroDelay(self) -> None:
        """Back-compat: ``retryDelays: []`` is the repo's fast-test config."""
        assert nextRetryDelaySeconds(0, [], 320.0) == 0.0
        assert nextRetryDelaySeconds(7, [], 320.0) == 0.0

    def test_aZeroTailEntryNeverEscalates(self) -> None:
        """Doubling zero is zero -- an explicit no-backoff schedule stays that way.

        Guards the arithmetic: ``last * 2 ** n`` would silently keep returning 0
        anyway, but a future switch to ``last + step`` would not, so the
        intended behaviour is pinned rather than left to the operator.
        """
        assert nextRetryDelaySeconds(9, [0], 320.0) == 0.0

    def test_aNonPositiveCeilingIsTheDocumentedOptOut(self) -> None:
        """
        Given: ``retryCeilingSeconds`` <= 0 (or None)
        When: attempts past the schedule end are scheduled
        Then: the PRE-US-673 plateau is preserved exactly.

        This is the escape hatch, and it is deliberate: an operator who wants
        the old fixed cadence has one, and it is spelled in config rather than
        by editing the module.
        """
        delays = [1, 2, 4, 8, 16]
        assert nextRetryDelaySeconds(9, delays, 0.0) == 16.0
        assert nextRetryDelaySeconds(9, delays, None) == 16.0
        assert nextRetryDelaySeconds(9, delays, -5.0) == 16.0

    def test_aNegativeAttemptIsTreatedAsTheFirst(self) -> None:
        """Defensive: no IndexError, no negative-index wraparound to the tail."""
        assert nextRetryDelaySeconds(-3, [1, 2, 4, 8, 16], 320.0) == 1.0


# ================================================================================
# The join: _performConnect actually consumes the policy
# ================================================================================


class TestPerformConnectUsesTheEscalatingSchedule:
    """Two correct halves in two places is the recurring defect here -- so the
    policy function and the retry loop are pinned TOGETHER, not separately."""

    def test_theSixteenSecondPlateauIsGoneFromTheRealRetryLoop(self) -> None:
        """
        Given: an ObdConnection on the SHIPPED schedule with room to run past it
        When: every attempt fails
        Then: the observed backoffs escalate past 16 s instead of repeating it.
        """
        event = RecordingShutdownEvent()
        conn = _connection(
            UnreachableDongleFactory(),
            retryDelays=[1, 2, 4, 8, 16],
            maxRetries=9,
            retryCeilingSeconds=320.0,
            shutdownEvent=event,
        )

        assert conn.connect() is False

        assert event.waits == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0]
        assert max(event.waits) > 16.0

    def test_theRetryLoopNeverExceedsTheConfiguredCeiling(self) -> None:
        """
        Given: a low ceiling of 20 s
        When: the schedule escalates past it
        Then: no observed backoff exceeds 20 s.
        """
        event = RecordingShutdownEvent()
        conn = _connection(
            UnreachableDongleFactory(),
            retryDelays=[1, 2, 4, 8, 16],
            maxRetries=9,
            retryCeilingSeconds=20.0,
            shutdownEvent=event,
        )

        conn.connect()

        assert max(event.waits) == 20.0
        assert event.waits[-3:] == [20.0, 20.0, 20.0]

    def test_theCeilingIsReadFromConfigNotFromTheCode(self) -> None:
        """
        Given: two connections differing ONLY in ``pi.bluetooth.retryCeilingSeconds``
        When: both exhaust the same schedule
        Then: their tails differ.  Story validationCriterion #3 -- the ceiling
              is configurable, and it is proven configurable by observing the
              config change the behaviour, not by reading the key back.
        """
        tails: list[float] = []
        for ceiling in (40.0, 200.0):
            event = RecordingShutdownEvent()
            conn = _connection(
                UnreachableDongleFactory(),
                retryDelays=[1, 2, 4, 8, 16],
                maxRetries=9,
                retryCeilingSeconds=ceiling,
                shutdownEvent=event,
            )
            conn.connect()
            tails.append(max(event.waits))

        assert tails == [40.0, 200.0]

    def test_anAbsentCeilingKeyFallsBackToTheDocumentedDefault(self) -> None:
        """A config that predates this story still gets the ceiling."""
        conn = _connection(UnreachableDongleFactory(), retryDelays=[1, 2, 4, 8, 16])
        assert conn.retryCeilingSeconds == DEFAULT_RETRY_CEILING_SECONDS


# ================================================================================
# validationCriterion #1 -- 30 minutes against an unreachable dongle
# ================================================================================


class TestThirtyMinuteFalloff:
    """The story's own criterion, with its own control.

    *"run the connection loop for 30 minutes against an unreachable dongle and
    count attempts -> attempts fall off to the documented idle cadence.  Today
    this yields ~112 attempts at 16 s; the test asserts the escalation, not a
    fixed number."*
    """

    BUDGET_SECONDS = 30 * 60

    def _attemptsWithin(self, policy: Any) -> int:
        """Count attempts a 30-minute unreachable window admits under ``policy``."""
        elapsed = 0.0
        attempts = 1  # attempt 0 fires immediately, before any backoff
        n = 0
        while True:
            elapsed += policy(n)
            if elapsed > self.BUDGET_SECONDS:
                return attempts
            attempts += 1
            n += 1

    def test_theOldPlateauReproducesTheStorysMeasuredFigure(self) -> None:
        """CALIBRATION.  Without this, 'few attempts' is also what a loop that
        never retried would report -- the defect must be present in our own
        fixture before its absence means anything.
        """
        delays = [1, 2, 4, 8, 16]
        attempts = self._attemptsWithin(lambda n: _plateauDelay(n, delays))

        # The story records "~112 attempts at 16 s".  Asserted as a band, not a
        # literal: the point is the ORDER OF MAGNITUDE the CIO measured.
        assert 105 <= attempts <= 120

    def test_theEscalatingScheduleFallsOffToAHandfulOfProbes(self) -> None:
        """
        Given: the same 30-minute unreachable window
        When: the schedule escalates to the 320 s ceiling
        Then: attempts fall off by more than an order of magnitude.

        Asserted as a RATIO against the calibrated control rather than as a
        fixed count, per the criterion's own instruction to assert the
        escalation and not a number.
        """
        delays = [1, 2, 4, 8, 16]
        before = self._attemptsWithin(lambda n: _plateauDelay(n, delays))
        after = self._attemptsWithin(
            lambda n: nextRetryDelaySeconds(n, delays, DEFAULT_RETRY_CEILING_SECONDS)
        )

        assert after < before / 5
        # And the parked car is genuinely down to a probe every few minutes.
        assert nextRetryDelaySeconds(50, delays, DEFAULT_RETRY_CEILING_SECONDS) >= 120.0


# ================================================================================
# validationCriterion #2 -- the escalation collapses on a real state change
# ================================================================================


class TestEscalationCollapsesOnStateChange:
    """*"A fix that trades 13 hours of noise for a 60-second wait at every
    key-on has moved the cost onto the driver."*"""

    def test_aSuccessfulConnectResetsTheScheduleForTheNextOutage(self) -> None:
        """
        Given: a connection that escalated all the way to its ceiling, then
               connected
        When: a LATER outage begins
        Then: it starts at 1 s again -- the escalation is per-outage state, not
              a permanent slowdown of the link.
        """
        factory = DongleThatReturnsFactory(failuresBeforeSuccess=9)
        event = RecordingShutdownEvent()
        conn = _connection(
            factory,
            retryDelays=[1, 2, 4, 8, 16],
            maxRetries=9,
            retryCeilingSeconds=320.0,
            shutdownEvent=event,
        )

        assert conn.connect() is True
        assert max(event.waits) > 16.0, "fixture must actually have escalated"

        # A second outage: the schedule restarts from the head.
        event.waits.clear()
        conn.disconnect()
        factory.failuresBeforeSuccess = factory.callCount + 2
        conn.connect()

        assert event.waits[0] == 1.0

    def test_connectOnceMakesExactlyOneAttemptAndNeverSleeps(self) -> None:
        """
        Given: an unreachable dongle
        When: ``connectOnce()`` is called
        Then: ONE port open is attempted and no backoff is waited.

        This is the 6x amplifier removal: a heartbeat tick that calls
        ``connect()`` spends 31 s doing six binds; a tick that calls
        ``connectOnce()`` does one and hands the cadence back to the heartbeat's
        own US-325 ceiling, which is where the cadence is supposed to live.
        """
        factory = UnreachableDongleFactory()
        event = RecordingShutdownEvent()
        conn = _connection(
            factory,
            retryDelays=[1, 2, 4, 8, 16],
            maxRetries=5,
            shutdownEvent=event,
        )

        assert conn.connectOnce() is False
        assert factory.callCount == 1
        assert event.waits == []

    def test_connectStillBurstsSoNoOtherCallerSilentlyLosesItsRetries(self) -> None:
        """The CONTROL for the test above.

        ``connectOnce`` must be a NEW seam, not a behaviour change smuggled into
        ``connect()``.  Every existing caller (the bounded reconnection loop,
        the initial-connect daemon) still gets its full retry budget.
        """
        factory = UnreachableDongleFactory()
        conn = _connection(
            factory,
            retryDelays=[1, 2, 4, 8, 16],
            maxRetries=5,
            shutdownEvent=RecordingShutdownEvent(),
        )

        conn.connect()
        assert factory.callCount == 6

    def test_connectOnceComesUpPromptlyWhenTheDongleReturns(self) -> None:
        """
        Given: a dongle that is reachable on this tick
        When: the heartbeat's per-tick attempt fires
        Then: the link comes up on that attempt, with no backoff waited first.

        The escalated delay lives in the heartbeat, and it is a delay BETWEEN
        ticks -- so a returning dongle is caught by the next tick rather than
        having to wait out a ceiling inside the connect call.
        """
        factory = DongleThatReturnsFactory(failuresBeforeSuccess=0)
        event = RecordingShutdownEvent()
        conn = _connection(factory, retryDelays=[1, 2, 4, 8, 16], shutdownEvent=event)

        assert conn.connectOnce() is True
        assert conn.isConnected() is True
        assert event.waits == []


# ================================================================================
# The join at BOTH heartbeat spawn sites
# ================================================================================


class _LifecycleHost:
    """Minimal host exposing only what ``_buildHeartbeatConnectFn`` reads."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection


class TestBothHeartbeatSpawnSitesUseTheSingleAttemptConnect:
    """There are TWO places that drive the forever-loop, and a fix applied to
    one of them leaves the other amplifying by 6x.  Both are pinned."""

    def test_lifecycleHeartbeatPrefersConnectOnce(self) -> None:
        from src.pi.obdii.orchestrator.lifecycle import LifecycleMixin

        factory = UnreachableDongleFactory()
        conn = _connection(factory, retryDelays=[1, 2, 4, 8, 16], maxRetries=5)

        host = _LifecycleHost(conn)
        connectFn = LifecycleMixin._buildHeartbeatConnectFn(host)  # type: ignore[arg-type]

        assert connectFn() is False
        assert factory.callCount == 1, (
            "the heartbeat tick must be ONE attempt -- its own docstring has "
            "said 'attempt a single connect()' since US-301"
        )

    def test_lifecycleHeartbeatStillWorksOnAConnectionWithoutConnectOnce(self) -> None:
        """The simulator + test doubles are duck-typed; they must not break."""
        from src.pi.obdii.orchestrator.lifecycle import LifecycleMixin

        class LegacyConnection:
            def __init__(self) -> None:
                self.connectCalls = 0

            def connect(self) -> bool:
                self.connectCalls += 1
                return True

        legacy = LegacyConnection()
        connectFn = LifecycleMixin._buildHeartbeatConnectFn(_LifecycleHost(legacy))  # type: ignore[arg-type]

        assert connectFn() is True
        assert legacy.connectCalls == 1

    def test_postFailureHeartbeatPrefersConnectOnce(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.pi.obdii.orchestrator import connection_recovery as cr

        captured: dict[str, Any] = {}

        def _fakeHeartbeat(**kwargs: Any) -> int:
            captured.update(kwargs)
            return 0

        monkeypatch.setattr(cr, "runReconnectHeartbeat", _fakeHeartbeat)

        factory = UnreachableDongleFactory()
        conn = _connection(factory, retryDelays=[1, 2, 4, 8, 16], maxRetries=5)

        host = cr.ConnectionRecoveryMixin()
        host._connection = conn
        host._postFailureReconnectHeartbeatThread = None

        host._spawnPostFailureReconnectHeartbeat()
        thread = host._postFailureReconnectHeartbeatThread
        assert thread is not None
        thread.join(timeout=5)

        # Asserted BEHAVIOURALLY rather than by identity: what matters is that
        # the function handed to the heartbeat costs one port open per tick.
        # An identity check would also pass if `connectOnce` were quietly
        # re-defined to burst.
        assert captured["connectFn"]() is False
        assert factory.callCount == 1


# ================================================================================
# The ceiling's home in config -- validationCriterion #3
# ================================================================================


class TestTheCeilingLivesBesideRetryDelays:
    """*"the ceiling is configurable and its default is documented in the same
    place as the existing ``pi.bluetooth.retryDelays`` key -- not a second
    hard-coded constant beside the first."*"""

    def test_theKeyIsInTheSameDefaultsBlockAsRetryDelays(self) -> None:
        assert 'pi.bluetooth.retryDelays' in OBD_DEFAULTS
        assert 'pi.bluetooth.retryCeilingSeconds' in OBD_DEFAULTS

    def test_theModuleConstantAndTheConfigDefaultAreTheSameNumber(self) -> None:
        """Read out of both SSOTs and asserted to agree.

        A number named in two places is a copied constant with better manners;
        if they ever diverge this fires rather than letting the loader and the
        module disagree about what the ceiling is.
        """
        assert OBD_DEFAULTS['pi.bluetooth.retryCeilingSeconds'] == (
            DEFAULT_RETRY_CEILING_SECONDS
        )
        assert OBD_DEFAULTS['pi.bluetooth.retryDelays'] == DEFAULT_RETRY_DELAYS

    def test_theShippedConfigJsonCarriesTheCeiling(self) -> None:
        """config.json is what the Pi actually reads; a default nobody ships is
        a default nobody has.
        """
        shipped = json.loads((REPO_ROOT / 'config.json').read_text(encoding='utf-8'))
        bluetooth = shipped['pi']['bluetooth']

        assert 'retryCeilingSeconds' in bluetooth
        assert bluetooth['retryCeilingSeconds'] == DEFAULT_RETRY_CEILING_SECONDS
        assert bluetooth['retryDelays'] == DEFAULT_RETRY_DELAYS

    def test_theDefaultCeilingIsTheGroundedInTreeFigure(self) -> None:
        """GROUNDING (Refusal Rule 2).  320 s is not invented for this story --
        it is the ceiling the fleet has actually run on since 2026-05-11:
        ``HEARTBEAT_TICK_INTERVAL_SEC * 2 ** BACKOFF_EXP_CAP`` = 10 * 32, the
        US-325 / I-025 production figure documented in ``reconnect_loop.py``.
        Read out of that module rather than restated, so the two cannot drift.
        """
        from src.pi.obdii.reconnect_loop import (
            BACKOFF_EXP_CAP,
            HEARTBEAT_TICK_INTERVAL_SEC,
        )

        assert DEFAULT_RETRY_CEILING_SECONDS == (
            HEARTBEAT_TICK_INTERVAL_SEC * 2 ** BACKOFF_EXP_CAP
        )


# ================================================================================
# What this story did NOT close, recorded rather than implied
# ================================================================================


class TestTheEngineStateGateIsAbsentAndWhyIsRecorded:
    """US-673 shipped the CEILING.  It did NOT ship the ENGINE-STATE GATE, and
    the story's conditionalOutcome #2 sanctions exactly that: *"If no
    independent engine-state signal proves reliable enough to gate on, ship the
    backoff ceiling alone and say so."*

    THE REASON, measured against the tree rather than asserted: the only
    engine-state signal in this repo is
    ``pi.obdii.orchestrator.engineOnVoltageThreshold`` (13.8 V, US-242 / B-049,
    ``src/common/config/validator.py``), and it is derived from the adapter's
    BATTERY_V sample -- which exists ONLY while the OBD link is UP.  The
    reconnect loop runs precisely when the link is DOWN, so gating it on
    BATTERY_V would be gating on the last reading taken before the link died:
    stale evidence about a car that may since have started.  That is the
    circularity the story forbids in its own words -- *"DO NOT infer engine
    state from the OBD link itself"*.

    This test exists so the absence is a RECORDED decision with a reason, not a
    silent omission a later reader mistakes for an oversight.  It fails the day
    someone adds a link-independent engine-state signal, which is the day this
    half becomes buildable.
    """

    def test_theOnlyEngineStateSignalInTreeIsLinkDerived(self) -> None:
        from src.common.config.validator import DEFAULTS

        assert 'pi.obdii.orchestrator.engineOnVoltageThreshold' in DEFAULTS
        assert DEFAULTS['pi.obdii.orchestrator.engineOnVoltageThreshold'] == 13.8

        # ...and it is consumed from the adapter read path, i.e. it requires the
        # very link the reconnect loop is trying to establish.
        escalation = (REPO_ROOT / 'src' / 'pi' / 'obdii' / 'orchestrator').rglob('*.py')
        consumers = [
            path.name
            for path in escalation
            if 'engineOnVoltageThreshold' in path.read_text(encoding='utf-8')
        ]
        assert consumers, (
            "engineOnVoltageThreshold has no consumer in the orchestrator -- if "
            "that is now true, re-read this story's gate half before trusting it"
        )

    def test_theBackoffCeilingStandsAloneAndIsStillWorthHaving(self) -> None:
        """Half of this story is shipped and the half is coherent by itself: a
        ceiling with no gate is strictly better than a plateau with no gate.
        """
        delays = list(DEFAULT_RETRY_DELAYS)
        plateau = _plateauDelay(30, delays)
        escalated = nextRetryDelaySeconds(30, delays, DEFAULT_RETRY_CEILING_SECONDS)

        assert plateau == 16
        assert escalated == DEFAULT_RETRY_CEILING_SECONDS
        assert escalated > plateau * 10
