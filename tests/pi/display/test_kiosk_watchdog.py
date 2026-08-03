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
# ================================================================================
################################################################################

"""Decision-table + effect-ordering tests for pi.display.kiosk_watchdog (US-523)."""

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
        "errorThreshold": 100,
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
    ) -> None:
        self.active = active
        self.errorCount = errorCount
        self.restartOk = restartOk
        self.writeOk = writeOk
        self.trace: list[str] = []
        self.sinceEpochs: list[float] = []
        self.history: list[float] = []

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

    def readHistoryFn(self) -> list[float]:
        self.trace.append("read-history")
        return list(self.history)

    def writeHistoryFn(self, history: list[float]) -> bool:
        self.trace.append("write-history")
        if not self.writeOk:
            return False
        self.history = list(history)
        return True


def _runOnce(fake: _FakeCommands, *, policy: kw.WatchdogPolicy | None = None, now: float = NOW):
    return kw.runOnce(
        policy=policy or _policy(),
        unitName="eclipse-dashboard.service",
        isActiveFn=fake.isActiveFn,
        errorCountFn=fake.errorCountFn,
        restartFn=fake.restartFn,
        readHistoryFn=fake.readHistoryFn,
        writeHistoryFn=fake.writeHistoryFn,
        clockFn=lambda: now,
    )


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


@pytest.mark.parametrize("count", [0, 1, 99])
def test_decideAction_belowThreshold_isHealthy(count: int):
    """
    Given: a wedge-marker count below the threshold
    When:  the watchdog decides
    Then:  healthy no-op -- an isolated GL hiccup is not a wedge
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=count,
        now=NOW,
        restartHistory=[],
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_NOOP
    assert decision.reason == kw.REASON_HEALTHY


@pytest.mark.parametrize("count", [100, 30_000])
def test_decideAction_atOrAboveThreshold_restarts(count: int):
    """
    Given: the wedge-marker rate reaches the threshold (boundary included)
    When:  the watchdog decides with no prior restarts
    Then:  restart -- this is the Atlas-RCA hot-loop signature
    """
    decision = kw.decideAction(
        unitActive=True,
        errorCount=count,
        now=NOW,
        restartHistory=[],
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_RESTART
    assert decision.reason == kw.REASON_WEDGE_DETECTED


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
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_NOOP
    assert decision.reason == kw.REASON_COOLDOWN


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
        policy=_policy(),
    )

    assert decision.action == kw.ACTION_NOOP
    assert decision.reason == kw.REASON_BUDGET_EXHAUSTED
    assert decision.restartsInWindow == 5


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
        policy=_policy(),
    )

    assert decision.errorCount == 1_234


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
    assert "write-history" not in fake.trace


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
    fake = _FakeCommands(errorCount=30_000)

    outcome = _runOnce(fake)

    assert outcome.restarted is True
    assert outcome.reason == kw.REASON_WEDGE_RESTARTED
    assert fake.trace.index("write-history") < fake.trace.index(
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
    fake = _FakeCommands(errorCount=30_000, writeOk=False)

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
    fake = _FakeCommands(errorCount=30_000, restartOk=False)

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
    fake = _FakeCommands(errorCount=30_000)
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
    fake = _FakeCommands(errorCount=30_000)

    with caplog.at_level("INFO"):
        _runOnce(fake)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, "a self-healing restart must not be silent"
    assert any("30000" in r.getMessage() for r in warnings)


# ----------------------------------------------------------------------------
# countWedgeMarkers -- the journalctl seam
# ----------------------------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


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


def test_countWedgeMarkers_nonZeroExit_isUnreadable():
    """
    Given: journalctl exits non-zero (no permission on the journal, bad flag)
    When:  counted
    Then:  None -- honest "I could not tell", which decideAction turns into a
           no-op instead of a restart
    """
    def runFn(argv, **kwargs):
        return _FakeCompleted(returncode=1, stdout="")

    assert kw.countWedgeMarkers("u", sinceEpoch=0.0, cap=10, runFn=runFn) is None


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


def test_ledger_roundTrips(tmp_path: Path):
    """
    Given: a written ledger
    When:  read back
    Then:  the attempt timestamps survive
    """
    path = tmp_path / "kiosk-watchdog.json"

    assert kw.writeRestartHistory(path, [1.0, 2.5]) is True
    assert kw.readRestartHistory(path) == [1.0, 2.5]


def test_ledger_missingFile_isEmptyHistory(tmp_path: Path):
    """
    Given: no ledger yet (fresh boot -- /run is tmpfs)
    When:  read
    Then:  empty history, not an error
    """
    assert kw.readRestartHistory(tmp_path / "absent.json") == []


def test_ledger_corruptJson_isEmptyHistory(tmp_path: Path):
    """
    Given: a truncated/corrupt ledger (power-cut mid-write)
    When:  read
    Then:  empty history -- degrade to "no known restarts", never crash the tick
    """
    path = tmp_path / "kiosk-watchdog.json"
    path.write_text("{not json", encoding="utf-8")

    assert kw.readRestartHistory(path) == []


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

    assert kw.readRestartHistory(path) == [1.0, 3.0]


def test_ledger_wrongShape_isEmptyHistory(tmp_path: Path):
    """
    Given: a ledger holding a list instead of the expected object
    When:  read
    Then:  empty history
    """
    path = tmp_path / "kiosk-watchdog.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    assert kw.readRestartHistory(path) == []


def test_ledger_unwritablePath_returnsFalseNotRaises(tmp_path: Path):
    """
    Given: a ledger path whose parent does not exist and cannot be made
    When:  written
    Then:  False -- runOnce turns that into "refuse to restart", so the failure
           must be a value, not an exception
    """
    path = tmp_path / "missing-dir" / "sub" / "x.json"
    (tmp_path / "missing-dir").write_text("i am a file, not a dir", encoding="utf-8")

    assert kw.writeRestartHistory(path, [1.0]) is False


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
        errorThreshold=kw.DEFAULT_ERROR_THRESHOLD,
        cooldownSeconds=kw.DEFAULT_COOLDOWN_SECONDS,
        maxRestartsPerHour=kw.DEFAULT_MAX_RESTARTS_PER_HOUR,
    )
    assert captured["unitName"] == kw.DEFAULT_UNIT


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
            "--error-threshold",
            "7",
            "--cooldown-seconds",
            "300",
            "--max-restarts-per-hour",
            "2",
        ],
        runOnceFn=fakeRunOnce,
    )

    assert captured["unitName"] == "other.service"
    assert captured["policy"] == kw.WatchdogPolicy(
        windowSeconds=30, errorThreshold=7, cooldownSeconds=300, maxRestartsPerHour=2
    )


@pytest.mark.parametrize(
    "reason,expected",
    [
        (kw.REASON_HEALTHY, 0),
        (kw.REASON_KIOSK_INACTIVE, 0),
        (kw.REASON_JOURNAL_UNREADABLE, 0),
        (kw.REASON_COOLDOWN, 0),
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
