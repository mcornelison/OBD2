################################################################################
# File Name: test_kiosk_watchdog.py
# Purpose/Description: US-523 (F-124) acceptance gate for the kiosk watchdog --
#                      the defense-in-depth recovery behind US-522's
#                      `--disable-gpu` fix.  Pins the DECISION table (when the
#                      watchdog restarts eclipse-dashboard and, far more
#                      importantly, when it REFUSES to) plus the journal
#                      counter, the persisted restart ledger and the CLI
#                      exit-code contract.
#
#                      The load-bearing negatives, each its own test:
#                        - a kiosk that is NOT active is never "restarted"
#                          (systemctl restart on an inactive unit would START
#                          it, breaking the splash OnSuccess hand-off);
#                        - an unreadable journal is UNCERTAIN, never a wedge;
#                        - the restart budget makes a recurring wedge LOUD
#                          instead of hiding it behind an endless restart loop
#                          (the AC's "must not mask a still-present freeze
#                          class");
#                        - the attempt is recorded BEFORE the restart fires, so
#                          an unwritable ledger disables the restart rather than
#                          silently disabling the cooldown that bounds it.
#
#                      US-561 ADDS the honesty gate for Atlas's four 08-17
#                      watchdog defects.  The load-bearing one: the verdict may
#                      NEVER be "healthy" while markers are present.  Healthy
#                      was MEASURED as exactly zero, so zero is the only count
#                      that earns the word -- 84 and 101 (the observed band that
#                      made the old absolute threshold a coin-flip) must produce
#                      the SAME verdict as each other, and neither is healthy.
#
#                      Offline-safe: no journalctl, no systemctl, no network --
#                      every external command is an injected fake.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Rex          | Initial implementation (Sprint 70 US-523)
# 2026-08-21    | Rex          | US-561: presence+dwell discriminator, journal
#               |              | readability probe, budget observability. Three
#               |              | pins MOVED (not deleted) -- see the repointed
#               |              | docstrings; each says what it used to assert.
# ================================================================================
################################################################################

"""Decision-table + effect-ordering tests for pi.display.kiosk_watchdog (US-523/US-561)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from pi.display import kiosk_watchdog as kw

# ----------------------------------------------------------------------------
# Fixtures / helpers
# ----------------------------------------------------------------------------

NOW = 1_800_000_000.0


def _policy(**overrides: int) -> kw.WatchdogPolicy:
    """A policy with the shipped defaults unless a test overrides one knob."""
    base = {
        "windowSeconds": 60,
        "markerReadCap": 100,
        "wedgeDwellSeconds": 60,
        "cooldownSeconds": 180,
        "maxRestartsPerHour": 5,
    }
    base.update(overrides)
    return kw.WatchdogPolicy(**base)  # type: ignore[arg-type]


class _FakeCommands:
    """Records the ordered effect trace so tests can assert SEQUENCE, not just calls."""

    def __init__(
        self,
        *,
        active: bool = True,
        errorCount: int | None = 0,
        restartOk: bool = True,
        writeOk: bool = True,
        markerPresentSince: float | None = None,
        journalTimedOut: bool = False,
    ) -> None:
        self.active = active
        self.errorCount = errorCount
        self.journalTimedOut = journalTimedOut
        self.restartOk = restartOk
        self.writeOk = writeOk
        self.trace: list[str] = []
        self.sinceEpochs: list[float] = []
        self.history: list[float] = []
        self.markerPresentSince = markerPresentSince
        self.written: list[kw.LedgerState] = []

    # --- injected seams -------------------------------------------------
    def isActiveFn(self, unitName: str) -> bool:
        self.trace.append(f"is-active:{unitName}")
        return self.active

    def errorCountFn(self, unitName: str, sinceEpoch: float) -> kw.JournalReading:
        self.trace.append("count")
        self.sinceEpochs.append(sinceEpoch)
        return kw.JournalReading(count=self.errorCount, timedOut=self.journalTimedOut)

    def restartFn(self, unitName: str) -> bool:
        self.trace.append(f"restart:{unitName}")
        return self.restartOk

    def readLedgerFn(self) -> kw.LedgerState:
        self.trace.append("read-ledger")
        return kw.LedgerState(
            restartAttempts=list(self.history), markerPresentSince=self.markerPresentSince
        )

    def writeLedgerFn(self, state: kw.LedgerState) -> bool:
        self.trace.append("write-ledger")
        self.written.append(state)
        if not self.writeOk:
            return False
        self.history = list(state.restartAttempts)
        self.markerPresentSince = state.markerPresentSince
        return True


def _runOnce(fake: _FakeCommands, *, policy: kw.WatchdogPolicy | None = None, now: float = NOW):
    return kw.runOnce(
        policy=policy or _policy(),
        unitName="eclipse-dashboard.service",
        isActiveFn=fake.isActiveFn,
        errorCountFn=fake.errorCountFn,
        restartFn=fake.restartFn,
        readLedgerFn=fake.readLedgerFn,
        writeLedgerFn=fake.writeLedgerFn,
        clockFn=lambda: now,
    )


#: A dwell long enough that decideAction sees the wedge as SUSTAINED.
_SUSTAINED = NOW - 600.0


# ----------------------------------------------------------------------------
# decideAction -- the pure decision table
# ----------------------------------------------------------------------------


def test_decideAction_kioskInactive_neverRestartsEvenWithFloodingErrors():
    """
    Given: the kiosk unit is NOT active but the journal is full of wedge markers
    When:  the watchdog decides
    Then:  it no-ops -- `systemctl restart` would START a unit the splash
           OnSuccess hand-off is supposed to own (dashboard.service.x11 A-1)
    """
    decision = kw.decideAction(
        unitActive=False,
        errorCount=999_999,
        now=NOW,
        restartHistory=[],
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_NOOP
    assert decision.reason == kw.REASON_KIOSK_INACTIVE


def test_decideAction_journalUnreadable_isUncertainNotWedge():
    """
    Given: the journal count is None (journalctl failed / unavailable)
    When:  the watchdog decides
    Then:  no restart -- a verification path that cannot read defaults to
           UNCERTAIN, never to "wedged" (I-037 lesson)
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=None,
        now=NOW,
        restartHistory=[],
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_NOOP
    assert decision.reason == kw.REASON_JOURNAL_UNREADABLE


def test_decideAction_measuredZero_isTheOnlyHealthyVerdict():
    """
    Given: the journal is READABLE and holds exactly ZERO wedge markers
    When:  the watchdog decides
    Then:  healthy -- and this is the ONLY input that earns the word.

    REPOINTED (US-561). This test used to run over [0, 1, 99] and call all
    three "healthy", because the verdict was `count < 100`. Atlas measured
    healthy as exactly zero post-restart, so 1 and 99 were never healthy; they
    were a live failure class below an arbitrary line. The other two counts now
    live in test_decideAction_anyMarkerAtAll_isNeverHealthy.
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=0,
        now=NOW,
        restartHistory=[],
        markerPresentSince=None,
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_NOOP
    assert decision.reason == kw.REASON_HEALTHY
    assert decision.wedged is False


@pytest.mark.parametrize("count", [1, 42, 84, 99, 100, 30_000])
def test_decideAction_anyMarkerAtAll_isNeverHealthy(count: int):
    """
    Given: ANY non-zero marker count, anywhere across four orders of magnitude
    When:  the watchdog decides
    Then:  the reason is NEVER "healthy" -- DEFECT 3a.

    `healthy; markers=84` was a false clean bill of health printed at the exact
    moment the CIO was looking at a frozen screen. Presence of the marker is
    the failure class being live; the count only says how fast it is spinning.
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=count,
        now=NOW,
        restartHistory=[],
        markerPresentSince=NOW - 1.0,
        policy=_policy(),
    )

    assert decision.reason != kw.REASON_HEALTHY


def test_decideAction_theObservedBand_84and101_agreeWithEachOther():
    """
    Given: the two counts Atlas actually observed one tick apart (101 then 84)
    When:  the watchdog decides on each, with everything else held identical
    Then:  the SAME verdict both times -- the coin-flip is gone (DEFECT 3a).

    This is the whole story in one assertion. 100 sat INSIDE the 84-101 band,
    so consecutive ticks of one continuous freeze produced WEDGED then healthy.
    A discriminator that lands differently on two samples of the same state is
    not a detector.
    """
    def decide(count: int):
        return kw.decideAction(
            unitActive=True,
            errorCount=count,
            now=NOW,
            restartHistory=[],
            markerPresentSince=_SUSTAINED,
            policy=_policy(),
        )

    assert decide(101).reason == decide(84).reason
    assert decide(101).action == decide(84).action
    assert decide(84).action == kw.ACTION_RESTART


def test_decideAction_markersPresentButNotYetSustained_isSuspectedNotHealthy():
    """
    Given: markers appeared 10s ago and the dwell is 60s
    When:  the watchdog decides
    Then:  wedge_suspected -- NOT healthy, and NOT yet a restart.

    Threshold+dwell, the shape Spool's coolant band arrived at independently.
    A lone startup GL complaint must not cost the panel a restart, but it must
    not be laundered into "healthy" either.
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=101,
        now=NOW,
        restartHistory=[],
        markerPresentSince=NOW - 10.0,
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_NOOP
    assert decision.reason == kw.REASON_WEDGE_SUSPECTED
    assert decision.reason != kw.REASON_HEALTHY
    assert decision.wedged is False


@pytest.mark.parametrize("count", [1, 84, 101, 30_000])
def test_decideAction_markersSustainedPastDwell_restartsRegardlessOfRate(count: int):
    """
    Given: markers present continuously for longer than the dwell
    When:  the watchdog decides, at a trickle AND at the catastrophic rate
    Then:  restart in every case -- the verdict is dwell-driven, so the slow
           regime that hid behind the old threshold now recovers too
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=count,
        now=NOW,
        restartHistory=[],
        markerPresentSince=NOW - 61.0,
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_RESTART
    assert decision.reason == kw.REASON_WEDGE_DETECTED
    assert decision.wedged is True


def test_decideAction_dwellBoundaryIsInclusive():
    """
    Given: markers present for EXACTLY the dwell
    When:  the watchdog decides
    Then:  restart -- the boundary is pinned so a future edit cannot silently
           move detection a whole tick later
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=5,
        now=NOW,
        restartHistory=[],
        markerPresentSince=NOW - 60.0,
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_RESTART


def test_decideAction_carriesTheDwellSoTheLogCanSayHowLong():
    """
    Given: a wedge sustained for 90s
    When:  it is decided
    Then:  the measured dwell rides along -- "wedged for 90s" is a fact a human
           can act on; "wedged" alone is not
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=101,
        now=NOW,
        restartHistory=[],
        markerPresentSince=NOW - 90.0,
        policy=_policy(),
    )

    assert decision.dwellSeconds == pytest.approx(90.0)


def test_decideAction_hasNoAbsoluteCountComparisonLeftInIt():
    """
    Given: the shipped decideAction source
    When:  it is read
    Then:  it compares errorCount only against ZERO -- never against a policy
           magnitude.

    STRUCTURAL, deliberately. Behaviour alone cannot pin this: a re-tuned
    constant (say 10 instead of 100) would pass every behavioural test above
    while re-creating the exact defect the moment the regime shifts again. The
    AC forbids a SHAPE, so the shape is what gets asserted.
    """
    import inspect

    body = inspect.getsource(kw.decideAction)

    assert "policy.errorThreshold" not in body
    assert "markerReadCap" not in body, (
        "the read cap is an I/O bound, not a verdict -- it must not re-enter the decision"
    )


def test_decideAction_wedgeWithinCooldown_holdsOff():
    """
    Given: a wedge is detected 10s after the previous restart attempt
    When:  the watchdog decides with a 180s cooldown
    Then:  no restart -- back-to-back restarts would flap and never let the
           fresh GPU context settle
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=30_000,
        now=NOW,
        restartHistory=[NOW - 10.0],
        markerPresentSince=_SUSTAINED,
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_NOOP
    assert decision.reason == kw.REASON_COOLDOWN
    assert decision.wedged is True, "holding off is not the same as being well"


def test_decideAction_wedgePastCooldown_restartsAgain():
    """
    Given: a wedge is detected well past the cooldown from the last attempt
    When:  the watchdog decides
    Then:  restart -- a genuine recurrence still recovers
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=30_000,
        now=NOW,
        restartHistory=[NOW - 1_000.0],
        markerPresentSince=_SUSTAINED,
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_RESTART
    assert decision.reason == kw.REASON_WEDGE_DETECTED


def test_decideAction_budgetExhausted_stopsRestartingAndStaysLoud():
    """
    Given: the hourly restart budget is already spent (5 attempts this hour)
    When:  a wedge is detected past the cooldown
    Then:  NO restart, reason=restart_budget_exhausted -- a recurring wedge must
           surface as a persistent fault, not be masked by an endless restart
           loop (US-523 AC: defense-in-depth must not hide a live freeze class)
    """
    history = [NOW - 900.0, NOW - 800.0, NOW - 700.0, NOW - 600.0, NOW - 500.0]

    decision = kw.decideAction(
        unitActive=True,
        errorCount=30_000,
        now=NOW,
        restartHistory=history,
        markerPresentSince=_SUSTAINED,
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_NOOP
    assert decision.reason == kw.REASON_BUDGET_EXHAUSTED
    assert decision.restartsInWindow == 5
    assert decision.wedged is True, "giving up is not the same as being well"


def test_decideAction_budgetExhaustedOutranksCooldown():
    """
    Given: budget spent AND the last attempt is inside the cooldown
    When:  a wedge is detected
    Then:  the reason reported is the LOUDER one (budget exhausted), so the
           journal shows "this keeps wedging", not a bland "cooling down"
    """
    history = [NOW - 400.0, NOW - 300.0, NOW - 200.0, NOW - 100.0, NOW - 5.0]

    decision = kw.decideAction(
        unitActive=True,
        errorCount=30_000,
        now=NOW,
        restartHistory=history,
        markerPresentSince=_SUSTAINED,
        policy=_policy(),
    )

    assert decision.reason == kw.REASON_BUDGET_EXHAUSTED


def test_decideAction_attemptsOlderThanBudgetWindow_arePruned():
    """
    Given: 5 restart attempts, all older than the 1h budget window
    When:  a wedge is detected now
    Then:  restart -- yesterday's wedge does not spend today's budget
    """
    stale = [NOW - 7_200.0 - (i * 60.0) for i in range(5)]

    decision = kw.decideAction(
        unitActive=True,
        errorCount=30_000,
        now=NOW,
        restartHistory=stale,
        markerPresentSince=_SUSTAINED,
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_RESTART
    assert decision.restartsInWindow == 0


def test_decideAction_carriesErrorCountForLogging():
    """
    Given: any decision
    When:  it is returned
    Then:  the observed count rides along so the log line can be specific
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=1_234,
        now=NOW,
        restartHistory=[],
        markerPresentSince=_SUSTAINED,
        policy=_policy(),
    )

    assert decision.errorCount == 1_234


def test_decideAction_inactiveKioskOutranksASustainedWedge():
    """
    Given: a long-sustained wedge on a kiosk that is NOT active
    When:  decided
    Then:  still kiosk_inactive -- the never-flap rules keep their precedence
           over the new discriminator (restart would START the unit)
    """
    decision = kw.decideAction(
        unitActive=False,
        errorCount=30_000,
        now=NOW,
        restartHistory=[],
        markerPresentSince=_SUSTAINED,
        policy=_policy(),
    )

    assert decision.reason == kw.REASON_KIOSK_INACTIVE


# ----------------------------------------------------------------------------
# runOnce -- effects + ordering
# ----------------------------------------------------------------------------


def test_runOnce_healthy_doesNotRestartOrWriteState():
    """
    Given: a healthy kiosk (0 wedge markers)
    When:  one watchdog tick runs
    Then:  no restart, no ledger write -- a quiet tick leaves no footprint
    """
    fake = _FakeCommands(errorCount=0)

    outcome = _runOnce(fake)

    assert outcome.restarted is False
    assert outcome.reason == kw.REASON_HEALTHY
    assert "restart:eclipse-dashboard.service" not in fake.trace
    assert "write-ledger" not in fake.trace


def test_runOnce_inactiveKiosk_skipsTheJournalQuery():
    """
    Given: the kiosk is not active
    When:  one tick runs
    Then:  journalctl is never invoked -- no pointless work every 30s while the
           dashboard is deliberately stopped
    """
    fake = _FakeCommands(active=False, errorCount=30_000)

    outcome = _runOnce(fake)

    assert outcome.reason == kw.REASON_KIOSK_INACTIVE
    assert "count" not in fake.trace


def test_runOnce_wedge_recordsAttemptBeforeRestarting():
    """
    Given: a wedge is detected
    When:  the tick recovers
    Then:  the ledger write happens BEFORE the restart -- the cooldown/budget
           that bounds restarts is only real if no restart can outrun its own
           bookkeeping
    """
    fake = _FakeCommands(errorCount=30_000, markerPresentSince=_SUSTAINED)

    outcome = _runOnce(fake)

    assert outcome.restarted is True
    assert outcome.reason == kw.REASON_WEDGE_RESTARTED
    assert fake.trace.index("write-ledger") < fake.trace.index(
        "restart:eclipse-dashboard.service"
    )
    assert fake.history == [NOW]


def test_runOnce_unwritableLedger_refusesToRestart():
    """
    Given: the restart ledger cannot be persisted
    When:  a wedge is detected
    Then:  NO restart happens -- an unbounded restart loop (cooldown silently
           dead because history is always empty) is worse than a frozen panel,
           and the failure is reported rather than swallowed
    """
    fake = _FakeCommands(errorCount=30_000, writeOk=False, markerPresentSince=_SUSTAINED)

    outcome = _runOnce(fake)

    assert outcome.restarted is False
    assert outcome.reason == kw.REASON_LEDGER_UNWRITABLE
    assert "restart:eclipse-dashboard.service" not in fake.trace


def test_runOnce_restartCommandFails_reportsItAndStillSpendsBudget():
    """
    Given: systemctl restart fails (e.g. polkit revoked)
    When:  a wedge is detected
    Then:  reason=restart_failed AND the attempt still counts against the
           budget, so a broken recovery path cannot retry every tick forever
    """
    fake = _FakeCommands(errorCount=30_000, restartOk=False, markerPresentSince=_SUSTAINED)

    outcome = _runOnce(fake)

    assert outcome.restarted is False
    assert outcome.reason == kw.REASON_RESTART_FAILED
    assert fake.history == [NOW]


def test_runOnce_journalWindowStartsAfterTheLastRestart():
    """
    Given: a restart attempt 20s ago and a 60s window
    When:  the tick queries the journal
    Then:  it counts only from the restart instant -- pre-restart errors are
           still inside the raw 60s window and would re-trigger on the very
           next tick (double-counting the wedge we already acted on)
    """
    fake = _FakeCommands(errorCount=0)
    fake.history = [NOW - 20.0]

    _runOnce(fake)

    assert fake.sinceEpochs == [NOW - 20.0]


def test_runOnce_noPriorRestart_usesTheFullWindow():
    """
    Given: no restart history
    When:  the tick queries the journal
    Then:  the window is the full policy window
    """
    fake = _FakeCommands(errorCount=0)

    _runOnce(fake)

    assert fake.sinceEpochs == [NOW - 60.0]


def test_runOnce_budgetExhausted_logsAtErrorLevel(caplog: pytest.LogCaptureFixture):
    """
    Given: the restart budget is spent and the kiosk is still wedging
    When:  a tick runs
    Then:  it logs at ERROR -- the AC requires recurring wedges stay VISIBLE
    """
    fake = _FakeCommands(errorCount=30_000, markerPresentSince=_SUSTAINED)
    fake.history = [NOW - (i + 1) * 100.0 for i in range(5)]

    with caplog.at_level("INFO"):
        outcome = _runOnce(fake)

    assert outcome.reason == kw.REASON_BUDGET_EXHAUSTED
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_runOnce_restart_isLoggedAtWarningWithTheCount(caplog: pytest.LogCaptureFixture):
    """
    Given: a wedge restart
    When:  it happens
    Then:  it is logged at WARNING and names the observed marker count, so
           "the display recovered by itself" is never silent
    """
    fake = _FakeCommands(errorCount=30_000, markerPresentSince=_SUSTAINED)

    with caplog.at_level("INFO"):
        _runOnce(fake)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, "a self-healing restart must not be silent"
    assert any("30000" in r.getMessage() for r in warnings)


# ----------------------------------------------------------------------------
# DEFECT 3a (cont.) -- the marker-presence clock, the state the dwell rests on
# ----------------------------------------------------------------------------


def test_runOnce_firstSightingOfMarkers_startsTheClockAndDoesNotRestart():
    """
    Given: a clean ledger and markers appearing for the first time this tick
    When:  the tick runs
    Then:  the presence clock is STAMPED at now, and nothing is restarted --
           one tick can observe presence but cannot observe persistence
    """
    fake = _FakeCommands(errorCount=101, markerPresentSince=None)

    outcome = _runOnce(fake)

    assert outcome.reason == kw.REASON_WEDGE_SUSPECTED
    assert outcome.restarted is False
    assert fake.markerPresentSince == NOW


def test_runOnce_markersStillPresent_doesNotRestampTheClock():
    """
    Given: the clock was stamped 45s ago and markers are still present
    When:  another tick runs
    Then:  the original stamp SURVIVES -- re-stamping every tick would reset the
           dwell forever and the watchdog could never conclude anything
    """
    fake = _FakeCommands(errorCount=101, markerPresentSince=NOW - 45.0)

    _runOnce(fake)

    assert fake.markerPresentSince == NOW - 45.0


def test_runOnce_aSingleCleanTick_resetsTheClock():
    """
    Given: markers were present, then one tick reads a measured ZERO
    When:  that tick runs
    Then:  the clock clears -- dwell means CONTINUOUS presence, so an isolated
           GL complaint 5 minutes ago can never combine with one now to fake a
           sustained wedge
    """
    fake = _FakeCommands(errorCount=0, markerPresentSince=NOW - 45.0)

    outcome = _runOnce(fake)

    assert outcome.reason == kw.REASON_HEALTHY
    assert fake.markerPresentSince is None


def test_runOnce_unreadableJournal_leavesTheClockUntouched():
    """
    Given: a wedge has been accruing dwell and this tick cannot read the journal
    When:  the tick runs
    Then:  the clock is NOT cleared -- absence of evidence would otherwise
           silently forgive a wedge every time journalctl hiccups, and the
           watchdog would restart the dwell from scratch each time
    """
    fake = _FakeCommands(errorCount=None, markerPresentSince=NOW - 45.0)

    outcome = _runOnce(fake)

    assert outcome.reason == kw.REASON_JOURNAL_UNREADABLE
    assert fake.markerPresentSince == NOW - 45.0
    assert "write-ledger" not in fake.trace


def test_runOnce_restart_clearsTheClockSoTheNewGenerationEarnsItsOwnDwell():
    """
    Given: a sustained wedge that gets restarted
    When:  the ledger is written
    Then:  markerPresentSince is cleared -- otherwise the fresh chromium
           generation inherits the dead one's dwell and gets restarted again on
           its very first marker, which is exactly the flap the cooldown exists
           to prevent
    """
    fake = _FakeCommands(errorCount=30_000, markerPresentSince=_SUSTAINED)

    _runOnce(fake)

    assert fake.markerPresentSince is None
    assert fake.history == [NOW]


def test_runOnce_markersPresentButLedgerUnwritable_isAFaultNotHealthy():
    """
    Given: markers are present and the ledger cannot be persisted
    When:  the tick runs
    Then:  ledger_unwritable -- NEVER healthy.

    The dwell lives in the ledger, so an unwritable ledger means the watchdog
    can no longer accumulate a verdict. Reporting "healthy" from a detector
    that has lost its own memory is the same false clean bill of health this
    story exists to remove, just arriving by a different road.
    """
    fake = _FakeCommands(errorCount=5, markerPresentSince=None, writeOk=False)

    outcome = _runOnce(fake)

    assert outcome.reason == kw.REASON_LEDGER_UNWRITABLE
    assert outcome.reason != kw.REASON_HEALTHY
    assert outcome.restarted is False


def test_runOnce_wedgedTicksNeverReportHealthyAcrossAWholeFreeze():
    """
    Given: five consecutive ticks of one continuous freeze, at the real observed
           counts (the 84-101 band Atlas logged)
    When:  they run in sequence against a shared ledger
    Then:  not ONE of them reports healthy.

    This is validationCriteria #1 in test form: "reports WEDGED every tick while
    wedged; never healthy". The old code produced WEDGED, healthy, WEDGED,
    healthy... on this exact input.
    """
    fake = _FakeCommands(errorCount=101)
    reasons = []

    for tick in range(5):
        fake.errorCount = [101, 84, 97, 88, 100][tick]
        reasons.append(_runOnce(fake, now=NOW + tick * 30.0).reason)

    assert kw.REASON_HEALTHY not in reasons
    # ...and it must eventually ACT, not just worry. `wedge_detected` is the
    # DECISION; runOnce reports the OUTCOME, which on a successful self-heal is
    # `wedge_restarted`. Asserting the decision reason here would have gone
    # green only if the restart had failed.
    assert kw.REASON_WEDGE_RESTARTED in reasons


# ----------------------------------------------------------------------------
# DEFECT 3d -- the restart budget must be observable
# ----------------------------------------------------------------------------


def test_runOnce_consumedBudget_isSurfacedOnEveryTickNotOnlyAtRestart(
    caplog: pytest.LogCaptureFixture,
):
    """
    Given: 2 restarts already consumed this hour and a currently-healthy kiosk
    When:  a routine tick runs
    Then:  the tick logs the budget at WARNING -- DEFECT 3d.

    On 2026-08-20 two of five restarts were spent mid-drive and nothing
    surfaced it; the only trace was two WARNING lines minutes apart in a
    journal nobody was reading. A spent budget is a standing fact about the
    display's health, so every tick states it until it ages out.
    """
    fake = _FakeCommands(errorCount=0)
    fake.history = [NOW - 400.0, NOW - 200.0]

    with caplog.at_level("INFO"):
        outcome = _runOnce(fake)

    assert outcome.restartsInWindow == 2
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, "a partially spent restart budget is not a routine INFO tick"
    assert any("2" in m and "5" in m for m in warnings), "say N of M, not just 'restarts'"


def test_runOnce_untouchedBudget_staysQuietAtInfo(caplog: pytest.LogCaptureFixture):
    """
    Given: a healthy kiosk with no restarts this hour
    When:  a tick runs
    Then:  INFO only -- if every 30s tick warned, the WARNING above would carry
           no information at all
    """
    fake = _FakeCommands(errorCount=0)

    with caplog.at_level("INFO"):
        _runOnce(fake)

    assert not [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]


def test_runOnce_outcomeCarriesTheBudgetCeilingNotJustTheCount():
    """
    Given: any tick
    When:  the outcome is returned
    Then:  it carries both the spend and the ceiling -- "2 restarts" is not
           observable, "2 of 5" is
    """
    fake = _FakeCommands(errorCount=0)
    fake.history = [NOW - 400.0, NOW - 200.0]

    outcome = _runOnce(fake)

    assert outcome.restartsInWindow == 2
    assert outcome.maxRestartsPerHour == 5


# ----------------------------------------------------------------------------
# countWedgeMarkers -- the journalctl seam
# ----------------------------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _isProbe(argv: list[str]) -> bool:
    """True for the readability probe -- it carries no --grep and no -u."""
    return not any(a.startswith("--grep=") for a in argv)


def test_countWedgeMarkers_buildsABoundedGrepQuery():
    """
    Given: a unit + an epoch cutoff + a cap
    When:  the journal is counted
    Then:  the argv filters by unit, epoch (`@<ts>`, locale-proof), the marker
           and caps the returned lines -- a wedge emits ~500 errors/sec, so an
           uncapped read pulls megabytes per tick off an already-pegged Pi
    """
    seen: list[list[str]] = []

    def runFn(argv, **kwargs):
        seen.append(argv)
        return _FakeCompleted(stdout="")

    kw.countWedgeMarkers(
        "eclipse-dashboard.service", sinceEpoch=1_800_000_000.0, cap=101, runFn=runFn
    )

    argv = seen[0]
    assert argv[0] == "journalctl"
    assert "-u" in argv and "eclipse-dashboard.service" in argv
    assert "--since=@1800000000" in argv
    assert f"--grep={kw.WEDGE_MARKER}" in argv
    assert "--lines=101" in argv
    assert "--no-pager" in argv


def test_countWedgeMarkers_countsMatchingLines():
    """
    Given: journalctl returns 3 matching lines
    When:  counted
    Then:  3 (blank trailing lines ignored)
    """
    def runFn(argv, **kwargs):
        return _FakeCompleted(stdout="err\nerr\nerr\n")

    assert kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn).count == 3


def test_countWedgeMarkers_noMatches_isZeroNotNone():
    """
    Given: journalctl succeeds with empty output
    When:  counted
    Then:  0 -- a readable-and-clean journal is a POSITIVE health fact and must
           be distinguishable from an unreadable one
    """
    def runFn(argv, **kwargs):
        return _FakeCompleted(stdout="")

    assert kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn).count == 0


def test_countWedgeMarkers_grepExit1WithAReadableJournal_isACleanZero(tmp_path: Path):
    """
    Given: `--grep` exits 1 (its documented ZERO-MATCHES code) and a probe shows
           the journal reads fine
    When:  counted
    Then:  0 -- DEFECT 3b.

    REPOINTED (US-561). This test used to assert None for exactly this input,
    which is the defect: `journalctl --grep=` exits 1 when there is nothing to
    match, so every healthy tick was reported as an honest-unknown. The
    docstring promised "0 == readable and clean, None if it could not be read"
    and delivered the inverse -- the instrument could not report its own good
    news, and a genuinely broken journal was indistinguishable from a clean one.
    The refusal-on-a-real-error half is MOVED to the next test, not dropped.
    """
    pattern = _journalTree(tmp_path)

    def runFn(argv, **kwargs):
        if _isProbe(argv):
            return _FakeCompleted(returncode=0, stdout="some unrelated log line\n")
        return _FakeCompleted(returncode=1, stdout="")

    reading = kw.countWedgeMarkers(
        "u", sinceEpoch=0.0, cap=10, runFn=runFn, journalGlobs=(pattern,)
    )
    assert reading.count == 0
    assert reading.timedOut is False


def test_countWedgeMarkers_nonZeroExitWithAnUnreadableJournal_isStillUnreadable(
    tmp_path: Path,
):
    """
    Given: `--grep` exits non-zero AND the readability probe also fails
    When:  counted
    Then:  no count -- honest "I could not tell", which decideAction turns into
           a no-op instead of a restart. The 3b fix must not swallow a REAL
           journal failure into a comfortable zero.

    US-644-a: ``timedOut`` is asserted FALSE here on purpose. This is the
    partner of the timeout tests -- without it, a change that reported every
    failure as a timeout would look just as green.
    """
    pattern = _journalTree(tmp_path)

    def runFn(argv, **kwargs):
        return _FakeCompleted(returncode=1, stderr="Failed to open journal: Permission denied")

    reading = kw.countWedgeMarkers(
        "u", sinceEpoch=0.0, cap=10, runFn=runFn, journalGlobs=(pattern,)
    )
    assert reading.count is None
    assert reading.timedOut is False


def test_countWedgeMarkers_nonZeroExitButOutputPresent_isUnreadable(tmp_path: Path):
    """
    Given: journalctl exits non-zero yet printed something to stdout
    When:  counted
    Then:  None -- a partial/aborted read is not a measured zero, so the
           zero-matches shortcut is gated on EMPTY output as well as the probe
    """
    pattern = _journalTree(tmp_path)

    def runFn(argv, **kwargs):
        if _isProbe(argv):
            return _FakeCompleted(returncode=0, stdout="ok\n")
        return _FakeCompleted(returncode=1, stdout="AllocateRingBuffer\n")

    reading = kw.countWedgeMarkers(
        "u", sinceEpoch=0.0, cap=10, runFn=runFn, journalGlobs=(pattern,)
    )
    assert reading.count is None


def test_countWedgeMarkers_doesNotProbeWhenTheGrepSucceeded(tmp_path: Path):
    """
    Given: a normal successful grep
    When:  counted
    Then:  the probe is NEVER run -- the extra command is a diagnostic for the
           failure path only, not a second journalctl on every 30s tick
    """
    pattern = _journalTree(tmp_path)
    argvs: list[list[str]] = []

    def runFn(argv, **kwargs):
        argvs.append(argv)
        return _FakeCompleted(returncode=0, stdout="err\n")

    kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn, journalGlobs=(pattern,))

    assert len(argvs) == 1
    assert not _isProbe(argvs[0])


def test_countWedgeMarkers_subprocessRaises_isUnreadable():
    """
    Given: journalctl is missing entirely (OSError)
    When:  counted
    Then:  no count, no exception escapes into the tick

    REPOINTED (US-644-a). This test's docstring used to read "OSError OR TIMES
    OUT" and treat the two as one case -- which is the defect in miniature: the
    test itself recorded the collapse as intended behaviour. The timeout half
    is MOVED to test_countWedgeMarkers_mainQueryTimesOut_theReadingCarriesTheTimeout,
    where it now asserts the OPPOSITE outcome. Not dropped -- split, because
    they were never the same fact.
    """
    def runFn(argv, **kwargs):
        raise OSError("no journalctl")

    assert kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn).count is None


# ----------------------------------------------------------------------------
# restart ledger persistence
# ----------------------------------------------------------------------------


def test_ledger_roundTripsBothFields(tmp_path: Path):
    """
    Given: a written ledger
    When:  read back
    Then:  the attempt timestamps AND the presence clock survive
    """
    path = tmp_path / "kiosk-watchdog.json"
    state = kw.LedgerState(restartAttempts=[1.0, 2.5], markerPresentSince=9.0)

    assert kw.writeLedger(path, state) is True
    assert kw.readLedger(path) == state


def test_ledger_missingFile_isTheEmptyState(tmp_path: Path):
    """
    Given: no ledger yet (fresh boot -- /run is tmpfs)
    When:  read
    Then:  empty state, not an error
    """
    assert kw.readLedger(tmp_path / "absent.json") == kw.LedgerState.empty()


def test_ledger_corruptJson_isTheEmptyState(tmp_path: Path):
    """
    Given: a truncated/corrupt ledger (power-cut mid-write)
    When:  read
    Then:  empty state -- degrade to "no known restarts", never crash the tick
    """
    path = tmp_path / "kiosk-watchdog.json"
    path.write_text("{not json", encoding="utf-8")

    assert kw.readLedger(path) == kw.LedgerState.empty()


def test_ledger_dropsNonNumericEntries(tmp_path: Path):
    """
    Given: a ledger with junk mixed into the attempt list
    When:  read
    Then:  only real timestamps survive (a str would explode the arithmetic in
           decideAction and take the whole watchdog down)
    """
    path = tmp_path / "kiosk-watchdog.json"
    path.write_text(
        json.dumps({"restartAttempts": [1.0, "nope", None, 3.0, True]}), encoding="utf-8"
    )

    assert kw.readLedger(path).restartAttempts == [1.0, 3.0]


def test_ledger_wrongShape_isTheEmptyState(tmp_path: Path):
    """
    Given: a ledger holding a list instead of the expected object
    When:  read
    Then:  empty state
    """
    path = tmp_path / "kiosk-watchdog.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    assert kw.readLedger(path) == kw.LedgerState.empty()


def test_ledger_preUs561File_readsAsNoPresenceClock(tmp_path: Path):
    """
    Given: a ledger written by the US-523 build, with no markerPresentSince key
    When:  read after the upgrade
    Then:  the attempts survive and the clock is simply unset.

    The ledger lives on tmpfs and clears at boot, so this only matters for the
    single tick that straddles a deploy -- but "the budget silently resets
    because the file shape changed" is exactly the kind of quiet loss that is
    cheaper to pin than to notice later.
    """
    path = tmp_path / "kiosk-watchdog.json"
    path.write_text(json.dumps({"restartAttempts": [7.0]}), encoding="utf-8")

    state = kw.readLedger(path)

    assert state.restartAttempts == [7.0]
    assert state.markerPresentSince is None


@pytest.mark.parametrize("junk", ["nope", True, [], {}])
def test_ledger_nonNumericPresenceClock_isDiscarded(tmp_path: Path, junk: object):
    """
    Given: a corrupt presence clock (incl. JSON `true`, which float()s to 1.0
           and would read as a plausible 1970 stamp -- the US-517 trap)
    When:  read
    Then:  None. A junk clock is worse than no clock: `now - 1.0` is a 56-year
           dwell, so the very next tick with one marker would restart the panel.
    """
    path = tmp_path / "kiosk-watchdog.json"
    path.write_text(
        json.dumps({"restartAttempts": [], "markerPresentSince": junk}), encoding="utf-8"
    )

    assert kw.readLedger(path).markerPresentSince is None


def test_ledger_unwritablePath_returnsFalseNotRaises(tmp_path: Path):
    """
    Given: a ledger path whose parent does not exist and cannot be made
    When:  written
    Then:  False -- runOnce turns that into "refuse to restart", so the failure
           must be a value, not an exception
    """
    path = tmp_path / "missing-dir" / "sub" / "x.json"
    (tmp_path / "missing-dir").write_text("i am a file, not a dir", encoding="utf-8")

    state = kw.LedgerState(restartAttempts=[1.0], markerPresentSince=None)

    assert kw.writeLedger(path, state) is False


# ----------------------------------------------------------------------------
# CLI contract
# ----------------------------------------------------------------------------


def test_main_defaultsMatchTheDocumentedPolicy():
    """
    Given: no CLI overrides
    When:  main runs
    Then:  the policy handed to runOnce is the documented default set
    """
    captured: dict[str, object] = {}

    def fakeRunOnce(**kwargs):
        captured.update(kwargs)
        return kw.WatchdogOutcome(
            reason=kw.REASON_HEALTHY, restarted=False, errorCount=0, restartsInWindow=0
        )

    exitCode = kw.main([], runOnceFn=fakeRunOnce)

    assert exitCode == 0
    policy = captured["policy"]
    assert policy == kw.WatchdogPolicy(
        windowSeconds=kw.DEFAULT_WINDOW_SECONDS,
        markerReadCap=kw.DEFAULT_MARKER_READ_CAP,
        wedgeDwellSeconds=kw.DEFAULT_WEDGE_DWELL_SECONDS,
        cooldownSeconds=kw.DEFAULT_COOLDOWN_SECONDS,
        maxRestartsPerHour=kw.DEFAULT_MAX_RESTARTS_PER_HOUR,
    )
    assert captured["unitName"] == kw.DEFAULT_UNIT


def test_main_dwellIsShorterThanTheCooldown():
    """
    Given: the shipped defaults
    When:  compared
    Then:  dwell < cooldown. If the dwell ever exceeded the cooldown, a wedge
           could never accumulate enough uninterrupted presence to fire twice,
           and the budget/escalation path would be unreachable -- the watchdog
           would look calm precisely because it had gone deaf.
    """
    assert kw.DEFAULT_WEDGE_DWELL_SECONDS < kw.DEFAULT_COOLDOWN_SECONDS


def test_main_dwellSpansAtLeastTwoTimerTicks():
    """
    Given: the 30s timer cadence declared in eclipse-kiosk-watchdog.timer
    When:  compared against the dwell
    Then:  the dwell covers >= 2 ticks -- "sustained" has to mean more than one
           observation, or dwell degenerates back into a single-sample verdict
    """
    assert kw.DEFAULT_WEDGE_DWELL_SECONDS >= 2 * kw.TIMER_CADENCE_SECONDS


def test_main_flagsOverrideThePolicy():
    """
    Given: CLI overrides for every knob
    When:  main runs
    Then:  they reach the policy -- the unit file can retune without a code
           change (no magic numbers baked past the parameter boundary)
    """
    captured: dict[str, object] = {}

    def fakeRunOnce(**kwargs):
        captured.update(kwargs)
        return kw.WatchdogOutcome(
            reason=kw.REASON_HEALTHY, restarted=False, errorCount=0, restartsInWindow=0
        )

    kw.main(
        [
            "--unit",
            "other.service",
            "--window-seconds",
            "30",
            "--marker-read-cap",
            "7",
            "--wedge-dwell-seconds",
            "45",
            "--cooldown-seconds",
            "300",
            "--max-restarts-per-hour",
            "2",
        ],
        runOnceFn=fakeRunOnce,
    )

    assert captured["unitName"] == "other.service"
    assert captured["policy"] == kw.WatchdogPolicy(
        windowSeconds=30,
        markerReadCap=7,
        wedgeDwellSeconds=45,
        cooldownSeconds=300,
        maxRestartsPerHour=2,
    )


#: Every outcome the watchdog can report, paired with the exit code main owes
#: it. Named rather than inlined so the census guard below can read it.
_EXIT_CODE_TABLE = [
    (kw.REASON_HEALTHY, 0),
    (kw.REASON_KIOSK_INACTIVE, 0),
    (kw.REASON_JOURNAL_UNREADABLE, 0),
    (kw.REASON_COOLDOWN, 0),
    (kw.REASON_WEDGE_SUSPECTED, 0),
    (kw.REASON_WEDGE_RESTARTED, 0),
    (kw.REASON_BUDGET_EXHAUSTED, 2),
    (kw.REASON_RESTART_FAILED, 2),
    (kw.REASON_LEDGER_UNWRITABLE, 2),
    # US-644-a. 2, and it sits beside REASON_JOURNAL_UNREADABLE's 0 on purpose:
    # same no-action, opposite exit code. A journal that will not READ leaves
    # the watchdog uncertain; a journal read that will not FINISH leaves it
    # BLIND, which is a broken recovery path and belongs with the other three.
    (kw.REASON_JOURNAL_TIMEOUT, 2),
]


@pytest.mark.parametrize("reason,expected", _EXIT_CODE_TABLE)
def test_main_exitCodeSurfacesABrokenRecoveryPath(reason: str, expected: int):
    """
    Given: each possible outcome
    When:  main maps it to an exit code
    Then:  routine outcomes (incl. a successful self-heal) exit 0, but a
           recovery path that is BROKEN or exhausted exits 2 (runtime) so the
           oneshot shows as failed in `systemctl status` instead of looking fine
    """

    def fakeRunOnce(**kwargs):
        return kw.WatchdogOutcome(
            reason=reason, restarted=(reason == kw.REASON_WEDGE_RESTARTED),
            errorCount=0, restartsInWindow=0,
        )

    assert kw.main([], runOnceFn=fakeRunOnce) == expected


# ----------------------------------------------------------------------------
# US-644-a: the readability probe is BOUNDED, and "timed out" is its OWN fact
#
# MEASURED (Atlas, at a real freeze 2026-08-30): the probe ran
# `journalctl --lines=1` with no file scoping across a 6M-entry journal, blew
# the 20s command budget, raised TimeoutExpired -- and every failure path
# collapsed into "unreadable -> take no action", logged at INFO as
# "no action (journal_unreadable; markers=None)".  PM then saw the SAME probe
# work ~90 minutes later on the same boot.  An INTERMITTENT detector is worse
# than a dead one because its successes make it look trustworthy.
#
# Two independent properties are pinned below, and BOTH are load-bearing:
#   1. the probe's work is scoped to ONE journal file whose size journald caps,
#      so its runtime no longer scales with the journal;
#   2. a timeout is reported as a FAULT and is distinguishable from both
#      "unreadable" and "no markers found".
# ----------------------------------------------------------------------------


def _journalTree(root: Path, *, volatile: bool = False) -> str:
    """Build a journald-shaped storage root and return its glob pattern."""
    branch = "run" if volatile else "var"
    machine = root / branch / "log" / "journal" / "0123456789abcdef0123456789abcdef"
    machine.mkdir(parents=True)
    (machine / "system.journal").write_bytes(b"LPKSHHRH")
    return str(root / branch / "log" / "journal" / "*" / "system.journal")


def test_activeJournalFile_findsTheActiveSystemJournal(tmp_path: Path):
    """
    Given: a journald storage root holding an active system.journal
    When:  the probe resolves the file to scope itself to
    Then:  that file is returned -- the scoping target is DISCOVERED, not
           hardcoded to one machine-id
    """
    pattern = _journalTree(tmp_path)

    found = kw.activeJournalFile(journalGlobs=(pattern,))

    assert found is not None
    assert found.endswith("system.journal")


def test_activeJournalFile_prefersTheVolatileRootOverThePersistentOne(tmp_path: Path):
    """
    Given: BOTH journald storage roots exist
    When:  the active file is resolved
    Then:  /run wins -- journald writes to the volatile root when it is present,
           so the persistent tree would be a STALE file and a stale file answers
           "can I read the journal" about the wrong journal
    """
    volatile = _journalTree(tmp_path, volatile=True)
    persistent = _journalTree(tmp_path)

    found = kw.activeJournalFile(journalGlobs=(volatile, persistent))

    assert found is not None
    assert "run" in Path(found).parts


def test_activeJournalFile_twoMachineIds_takesTheOneStillBeingWritten(tmp_path: Path):
    """
    Given: two machine-id directories under one storage root -- what a reimage
           that regenerated /etc/machine-id while /var survived leaves behind
    When:  the active file is resolved
    Then:  the MOST RECENTLY WRITTEN one wins, not the alphabetically first.

    This is the dangerous direction, which is why it gets its own test: a probe
    pointed at an abandoned journal would answer "readable" on a box whose live
    journal is broken, countWedgeMarkers would turn that into a clean ZERO, and
    the tick would report a wedged panel as HEALTHY.
    """
    root = tmp_path / "var" / "log" / "journal"
    stale = root / "00000000000000000000000000000000"
    live = root / "ffffffffffffffffffffffffffffffff"
    for machine in (stale, live):
        machine.mkdir(parents=True)
        (machine / "system.journal").write_bytes(b"LPKSHHRH")
    os.utime(stale / "system.journal", (1_000_000, 1_000_000))
    os.utime(live / "system.journal", (2_000_000, 2_000_000))

    found = kw.activeJournalFile(journalGlobs=(str(root / "*" / "system.journal"),))

    assert found is not None
    assert Path(found).parent.name == live.name


def test_activeJournalFile_nothingMatches_isNone(tmp_path: Path):
    """
    Given: neither storage root exists
    When:  the active file is resolved
    Then:  None -- an honest "I cannot scope", never a fabricated path
    """
    assert kw.activeJournalFile(journalGlobs=(str(tmp_path / "nope" / "*.journal"),)) is None


def test_probeJournal_scopesTheReadToTheSingleActiveJournalFile(tmp_path: Path):
    """
    Given: an active system.journal exists
    When:  the readability probe runs
    Then:  the argv carries `--file=<that one file>` -- THE FIX.  An unscoped
           journalctl opens and merges EVERY archived boot's file, so its
           runtime grows with the journal; one active file is size-capped by
           journald itself, so the probe's cost stops depending on how long the
           Pi has been up.  It stays unit-unfiltered and one line long, because
           the question is still "can I read the journal AT ALL".
    """
    pattern = _journalTree(tmp_path)
    seen: list[list[str]] = []

    def runFn(argv, **kwargs):
        seen.append(argv)
        return _FakeCompleted(returncode=0, stdout="x\n")

    assert kw.probeJournal(runFn=runFn, journalGlobs=(pattern,)) == kw.PROBE_READABLE

    argv = seen[0]
    assert argv[0] == "journalctl"
    assert any(a.startswith("--file=") and a.endswith("system.journal") for a in argv)
    assert "--lines=1" in argv
    assert "-u" not in argv
    assert not any(a.startswith("--grep=") for a in argv)


def test_probeJournal_runsUnderItsOwnShortTimeout(tmp_path: Path):
    """
    Given: the readability probe
    When:  it shells out
    Then:  it uses the SHORT probe budget, not the full command budget.  This
           is a NARROWING, and it is not the fix -- the scoping above is.  It
           exists so a probe that hangs anyway cannot eat the whole tick.
    """
    pattern = _journalTree(tmp_path)
    seen: list[float] = []

    def runFn(argv, **kwargs):
        seen.append(kwargs["timeout"])
        return _FakeCompleted(returncode=0, stdout="x\n")

    kw.probeJournal(runFn=runFn, journalGlobs=(pattern,))

    assert seen == [kw._PROBE_TIMEOUT_SECONDS]
    assert kw._PROBE_TIMEOUT_SECONDS < kw._COMMAND_TIMEOUT_SECONDS


def test_theWholeTickBudgetFitsInsideOneTimerInterval():
    """
    Given: a tick may spend the marker query AND the readability probe
    When:  their budgets are added up
    Then:  the total fits inside the declared timer cadence -- that is where
           the probe budget's number COMES FROM.  Overrunning the cadence means
           overlapping ticks, which is how a detector starts lying about time.
    """
    assert kw._COMMAND_TIMEOUT_SECONDS + kw._PROBE_TIMEOUT_SECONDS <= kw.TIMER_CADENCE_SECONDS


def test_probeJournal_timesOut_isTimedOutAndNotUnreadable(tmp_path: Path):
    """
    Given: the probe exceeds its budget
    When:  it is asked for a verdict
    Then:  PROBE_TIMED_OUT -- a THIRD state.  Collapsing it into "unreadable"
           is the defect: it made a broken instrument indistinguishable from a
           quiet one, and the tick then logged a healthy-looking no-op.
    """
    pattern = _journalTree(tmp_path)

    def runFn(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kw._PROBE_TIMEOUT_SECONDS)

    assert kw.probeJournal(runFn=runFn, journalGlobs=(pattern,)) == kw.PROBE_TIMED_OUT


def test_probeJournal_journalctlMissing_isUnreadableAndNotTimedOut(tmp_path: Path):
    """
    Given: journalctl cannot be executed at all
    When:  probed
    Then:  PROBE_UNREADABLE -- the DISCRIMINATING PARTNER of the test above.
           Without this pair, "everything is a timeout" would pass just as well
           as the real behaviour.
    """
    pattern = _journalTree(tmp_path)

    def runFn(argv, **kwargs):
        raise OSError("no journalctl")

    assert kw.probeJournal(runFn=runFn, journalGlobs=(pattern,)) == kw.PROBE_UNREADABLE


def test_probeJournal_noActiveJournalFile_isUnreadableWithoutAnUnscopedScan(tmp_path: Path):
    """
    Given: journald has no readable storage root at either location
    When:  probed
    Then:  PROBE_UNREADABLE, and journalctl is NEVER RUN.  Falling back to the
           unscoped `--lines=1` here would reinstate exactly the unbounded scan
           this story removes; and if neither storage root exists there is
           genuinely nothing to read, so "unreadable" is the honest answer --
           reached immediately instead of after a 20s hang.
    """
    calls: list[list[str]] = []

    def runFn(argv, **kwargs):
        calls.append(argv)
        return _FakeCompleted(returncode=0, stdout="x\n")

    verdict = kw.probeJournal(runFn=runFn, journalGlobs=(str(tmp_path / "none" / "*.j"),))

    assert verdict == kw.PROBE_UNREADABLE
    assert calls == []


def test_probeJournal_smallJournalReadsFine_isReadable(tmp_path: Path):
    """
    Given: a small journal that answers immediately (VC-3, the no-regression case)
    When:  probed
    Then:  PROBE_READABLE -- unchanged behaviour for the case that always worked
    """
    pattern = _journalTree(tmp_path)

    def runFn(argv, **kwargs):
        return _FakeCompleted(returncode=0, stdout="a log line\n")

    assert kw.probeJournal(runFn=runFn, journalGlobs=(pattern,)) == kw.PROBE_READABLE


def test_countWedgeMarkers_probeTimesOut_theReadingCarriesTheTimeout(tmp_path: Path):
    """
    Given: the grep exits 1 with empty output and the readability probe TIMES OUT
    When:  the journal is counted
    Then:  no count, and the reading says it TIMED OUT -- so the tick can report
           a fault instead of the routine "journal_unreadable" no-op that hid a
           dead panel for 7h27m
    """
    pattern = _journalTree(tmp_path)

    def runFn(argv, **kwargs):
        if _isProbe(argv):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kw._PROBE_TIMEOUT_SECONDS)
        return _FakeCompleted(returncode=1, stdout="")

    reading = kw.countWedgeMarkers(
        "u", sinceEpoch=0.0, cap=10, runFn=runFn, journalGlobs=(pattern,)
    )

    assert reading.count is None
    assert reading.timedOut is True


def test_countWedgeMarkers_mainQueryTimesOut_theReadingCarriesTheTimeout():
    """
    Given: the MARKER QUERY itself times out (not the probe)
    When:  counted
    Then:  the same distinct timeout fact.  The collapse being removed is not
           specific to the probe -- `except SubprocessError` swallowed
           TimeoutExpired here too and logged it as a routine unreadable.
    """
    def runFn(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kw._COMMAND_TIMEOUT_SECONDS)

    reading = kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn)

    assert reading.count is None
    assert reading.timedOut is True


def test_countWedgeMarkers_mainQueryOsError_isUnreadableAndNotTimedOut():
    """
    Given: journalctl is missing entirely
    When:  counted
    Then:  unreadable, timedOut FALSE -- the discriminating partner again, so
           the new flag cannot pass by being permanently true
    """
    def runFn(argv, **kwargs):
        raise OSError("no journalctl")

    reading = kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn)

    assert reading.count is None
    assert reading.timedOut is False


def test_decideAction_journalTimedOut_isADistinctReasonFromUnreadable():
    """
    Given: two ticks with NO count -- one unreadable, one timed out
    When:  each is decided
    Then:  both refuse to act, but they carry DIFFERENT reasons.  Same action,
           different fact: a watchdog that cannot read the journal is uncertain;
           a watchdog whose probe keeps timing out is BROKEN.
    """
    unreadable = kw.decideAction(
        unitActive=True, errorCount=None, now=NOW, restartHistory=[], policy=_policy()
    )
    timedOut = kw.decideAction(
        unitActive=True,
        errorCount=None,
        now=NOW,
        restartHistory=[],
        policy=_policy(),
        journalTimedOut=True,
    )

    assert unreadable.reason == kw.REASON_JOURNAL_UNREADABLE
    assert timedOut.reason == kw.REASON_JOURNAL_TIMEOUT
    assert unreadable.action == timedOut.action == kw.ACTION_NOOP


def test_runOnce_journalReadTimesOut_isLoggedAsAFaultNotARoutineNoop(
    caplog: pytest.LogCaptureFixture,
):
    """
    Given: a tick whose journal read timed out
    When:  it runs
    Then:  the outcome reason is the timeout, and it is logged at ERROR.  The
           shipped line was `INFO kiosk-watchdog: no action (journal_unreadable;
           markers=None)` -- indistinguishable, to a human scanning the journal,
           from a healthy tick.
    """
    fake = _FakeCommands(errorCount=None, journalTimedOut=True)

    with caplog.at_level("INFO"):
        outcome = _runOnce(fake)

    assert outcome.reason == kw.REASON_JOURNAL_TIMEOUT
    assert outcome.restarted is False
    assert [r for r in caplog.records if r.levelname == "ERROR"]


def test_runOnce_journalUnreadable_staysTheQuieterUncertainTick(
    caplog: pytest.LogCaptureFixture,
):
    """
    Given: a genuinely unreadable journal that did NOT time out
    When:  the tick runs
    Then:  the pre-existing reason and behaviour are unchanged -- the new fault
           must not swallow the old state the way the old state swallowed it
    """
    fake = _FakeCommands(errorCount=None)

    with caplog.at_level("INFO"):
        outcome = _runOnce(fake)

    assert outcome.reason == kw.REASON_JOURNAL_UNREADABLE
    assert not [r for r in caplog.records if r.levelname == "ERROR"]


def test_exitCodeTableCoversEveryReasonTheWatchdogCanReport():
    """
    Given: the exit-code parametrize table above
    When:  it is compared against every REASON_* the module defines
    Then:  none is missing -- the table is a CENSUS, and a census that has to
           be remembered is one that drifts.  US-644-a added a reason and this
           guard is what makes the next addition go red instead of quietly
           inheriting whichever exit code its outcome happens to fall through
           to.
    """
    declared = {
        value
        for name, value in vars(kw).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    covered = {reason for reason, _ in _EXIT_CODE_TABLE}

    assert declared, "premise check: the module must declare REASON_* constants"
    # ONE legitimate exclusion, and it is NAMED rather than the guard being
    # widened to swallow it: WEDGE_DETECTED is a DECISION reason only. runOnce
    # always converts it into WEDGE_RESTARTED, RESTART_FAILED or
    # LEDGER_UNWRITABLE, so it can never reach main as an outcome. An unnamed
    # exclusion is how the next genuinely-missing reason would slip through.
    assert declared - covered == {kw.REASON_WEDGE_DETECTED}
