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
    ) -> None:
        self.active = active
        self.errorCount = errorCount
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

    def errorCountFn(self, unitName: str, sinceEpoch: float) -> int | None:
        self.trace.append("count")
        self.sinceEpochs.append(sinceEpoch)
        return self.errorCount

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

    assert (
        kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn) == 3
    )


def test_countWedgeMarkers_noMatches_isZeroNotNone():
    """
    Given: journalctl succeeds with empty output
    When:  counted
    Then:  0 -- a readable-and-clean journal is a POSITIVE health fact and must
           be distinguishable from an unreadable one
    """
    def runFn(argv, **kwargs):
        return _FakeCompleted(stdout="")

    assert kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn) == 0


def test_countWedgeMarkers_grepExit1WithAReadableJournal_isACleanZero():
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
    def runFn(argv, **kwargs):
        if _isProbe(argv):
            return _FakeCompleted(returncode=0, stdout="some unrelated log line\n")
        return _FakeCompleted(returncode=1, stdout="")

    assert kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn) == 0


def test_countWedgeMarkers_nonZeroExitWithAnUnreadableJournal_isStillUnreadable():
    """
    Given: `--grep` exits non-zero AND the readability probe also fails
    When:  counted
    Then:  None -- honest "I could not tell", which decideAction turns into a
           no-op instead of a restart. The 3b fix must not swallow a REAL
           journal failure into a comfortable zero.
    """
    def runFn(argv, **kwargs):
        return _FakeCompleted(returncode=1, stderr="Failed to open journal: Permission denied")

    assert kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn) is None


def test_countWedgeMarkers_nonZeroExitButOutputPresent_isUnreadable():
    """
    Given: journalctl exits non-zero yet printed something to stdout
    When:  counted
    Then:  None -- a partial/aborted read is not a measured zero, so the
           zero-matches shortcut is gated on EMPTY output as well as the probe
    """
    def runFn(argv, **kwargs):
        if _isProbe(argv):
            return _FakeCompleted(returncode=0, stdout="ok\n")
        return _FakeCompleted(returncode=1, stdout="AllocateRingBuffer\n")

    assert kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn) is None


def test_countWedgeMarkers_doesNotProbeWhenTheGrepSucceeded():
    """
    Given: a normal successful grep
    When:  counted
    Then:  the probe is NEVER run -- the extra command is a diagnostic for the
           failure path only, not a second journalctl on every 30s tick
    """
    argvs: list[list[str]] = []

    def runFn(argv, **kwargs):
        argvs.append(argv)
        return _FakeCompleted(returncode=0, stdout="err\n")

    kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn)

    assert len(argvs) == 1
    assert not _isProbe(argvs[0])


def test_journalIsReadable_probeIsCheapAndUnfiltered():
    """
    Given: the readability probe
    When:  it runs
    Then:  it asks for ONE line with no unit filter -- it must answer "can I
           read the journal at all", which a unit with zero entries would
           otherwise answer wrongly
    """
    seen: list[list[str]] = []

    def runFn(argv, **kwargs):
        seen.append(argv)
        return _FakeCompleted(returncode=0, stdout="x\n")

    assert kw.journalIsReadable(runFn=runFn) is True

    argv = seen[0]
    assert argv[0] == "journalctl"
    assert "--lines=1" in argv
    assert "-u" not in argv
    assert not any(a.startswith("--grep=") for a in argv)


def test_journalIsReadable_subprocessRaises_isFalse():
    """
    Given: journalctl is missing entirely
    When:  probed
    Then:  False, no exception -- the caller then reports unreadable
    """
    def runFn(argv, **kwargs):
        raise OSError("no journalctl")

    assert kw.journalIsReadable(runFn=runFn) is False


def test_countWedgeMarkers_subprocessRaises_isUnreadable():
    """
    Given: journalctl is missing entirely (OSError) or times out
    When:  counted
    Then:  None, no exception escapes into the tick
    """
    def runFn(argv, **kwargs):
        raise OSError("no journalctl")

    assert kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn) is None


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


@pytest.mark.parametrize(
    "reason,expected",
    [
        (kw.REASON_HEALTHY, 0),
        (kw.REASON_KIOSK_INACTIVE, 0),
        (kw.REASON_JOURNAL_UNREADABLE, 0),
        (kw.REASON_COOLDOWN, 0),
        (kw.REASON_WEDGE_SUSPECTED, 0),
        (kw.REASON_WEDGE_RESTARTED, 0),
        (kw.REASON_BUDGET_EXHAUSTED, 2),
        (kw.REASON_RESTART_FAILED, 2),
        (kw.REASON_LEDGER_UNWRITABLE, 2),
    ],
)
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
