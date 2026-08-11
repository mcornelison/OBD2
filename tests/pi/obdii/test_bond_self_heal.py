################################################################################
# File Name: test_bond_self_heal.py
# Purpose/Description: US-545 (Atlas A-18) -- OBD BT bond self-heal + boot
#                      verify.  Drives the REAL healer over the shared CLI-level
#                      FakeBtStack so every decision, ordering rule and budget
#                      in bond_self_heal.py executes; only subprocess itself is
#                      faked.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-10    | Rex (US-545) | Initial -- A-18 bond self-heal + 3 Atlas
#               |              | refinements (serialise vs the port, bounded,
#               |              | loud-surface when not discoverable).
# ================================================================================
################################################################################

"""Coverage for the bounded, serialised BT bond self-heal.

WHY THE FAKE SITS AT THE SUBPROCESS SEAM
----------------------------------------
The lesson this story inherits (US-550): *a forced-override / mock-driven test
proves the mock works and says nothing about the path that runs on the Pi.*
Everything the healer does is a CLI invocation, so stubbing at the function
seam (``readBondState``, ``ensureTrusted``) would leave the entire body of the
story untested.  :class:`FakeBtStack` fakes ``subprocess`` and nothing else, so
the real ``bluetooth_helper`` parsing, the real verdict logic, the real
ordering and the real budget all run.

:class:`TestRealInvocationPath` closes the remaining gap deliberately: it
unsets every override and lets the GENUINE ``subprocess.run`` fail (there is no
``bluetoothctl`` on a Windows dev box), asserting the honest answer -- because
that is the production mode a forced runner can never reach.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pi.obdii import bond_self_heal
from src.pi.obdii.bluetooth_helper import BondState
from src.pi.obdii.bond_self_heal import (
    BOND_SELF_HEAL_LOG_PREFIX,
    OBD_SERVICE_UNIT,
    SELF_HEAL_MAX_ATTEMPTS_PER_BOOT,
    SELF_HEAL_UNIT,
    BondSelfHealer,
    BondVerdict,
    SelfHealOutcome,
    classifyBond,
    parseAdapterPowered,
    parseInRange,
    requestBondSelfHeal,
    resetSelfHealRequestBudget,
)

from .bt_stack_fake import DEFAULT_MAC, OBD_UNIT, FakeBtStack

# ================================================================================
# Helpers
# ================================================================================


def _healer(stack: FakeBtStack, **kwargs: object) -> BondSelfHealer:
    """Build a healer wired to ``stack`` with a no-op sleep."""
    kwargs.setdefault('maxAttempts', SELF_HEAL_MAX_ATTEMPTS_PER_BOOT)
    return BondSelfHealer(
        stack.mac,
        subprocessRunner=stack.runner,
        sleepFn=lambda _seconds: None,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.fixture
def lostBondStack() -> FakeBtStack:
    """The story's scenario: the bond has been cleared, the dongle is present."""
    stack = FakeBtStack()
    stack.clearBond()
    return stack


# ================================================================================
# Pure parsers -- the facts every decision is read from
# ================================================================================


class TestParsers:
    def test_parseAdapterPowered_poweredController_returnsTrue(self) -> None:
        """
        Given: `bluetoothctl show` output for a powered controller
        When: parsed
        Then: True
        """
        output = "Controller B8:27:EB:00:11:22 (public)\n\tPowered: yes\n"

        assert parseAdapterPowered(output) is True

    def test_parseAdapterPowered_unpoweredController_returnsFalse(self) -> None:
        """
        Given: a controller reporting Powered: no
        When: parsed
        Then: False -- present but dark, which is NOT the same as absent
        """
        output = "Controller B8:27:EB:00:11:22 (public)\n\tPowered: no\n"

        assert parseAdapterPowered(output) is False

    def test_parseAdapterPowered_noController_returnsNone(self) -> None:
        """
        Given: bluez reporting no default controller
        When: parsed
        Then: None -- "unreadable", never coerced to a confident False
        """
        assert parseAdapterPowered("No default controller available\n") is None
        assert parseAdapterPowered("") is None

    def test_parseInRange_rssiLine_returnsTrue(self) -> None:
        """
        Given: an `info` block carrying an RSSI reading
        When: parsed
        Then: True -- an RSSI can only come from a live advertisement
        """
        output = "Device 00:04:3E:85:0D:FB (public)\n\tPaired: no\n\tRSSI: -62\n"

        assert parseInRange(output) is True

    def test_parseInRange_rememberedButSilentDevice_returnsFalse(self) -> None:
        """
        Given: a fully-bonded device record with NO RSSI line
        When: parsed
        Then: False

        This is the whole point of using RSSI: a bonded record proves bluez
        REMEMBERS the dongle, not that the dongle is powered and in range.  An
        engine-off OBDLink LX looks exactly like this.
        """
        output = (
            "Device 00:04:3E:85:0D:FB (public)\n"
            "\tPaired: yes\n\tBonded: yes\n\tTrusted: yes\n"
        )

        assert parseInRange(output) is False

    def test_parseInRange_txPowerOnly_returnsTrue(self) -> None:
        """
        Given: an advertisement that carried TxPower but no RSSI
        When: parsed
        Then: True -- both fields are advertisement-derived
        """
        output = "Device 00:04:3E:85:0D:FB (public)\n\tTxPower: 4\n"

        assert parseInRange(output) is True


class TestClassifyBond:
    def test_classifyBond_allThreeFlags_isDurable(self) -> None:
        state = BondState(known=True, paired=True, bonded=True, trusted=True)

        assert classifyBond(state, adapterPresent=True) is BondVerdict.DURABLE

    def test_classifyBond_onlyTrustMissing_isTrustMissing(self) -> None:
        """
        Given: paired + bonded but not trusted
        When: classified
        Then: TRUST_MISSING -- the one case repairable WITHOUT the dongle
        """
        state = BondState(known=True, paired=True, bonded=True, trusted=False)

        assert classifyBond(state, adapterPresent=True) is BondVerdict.TRUST_MISSING

    def test_classifyBond_noBondRecordButAdapterUp_isLost(self) -> None:
        """
        Given: bluez answering normally with no record for the MAC
        When: classified
        Then: LOST -- this is a genuinely de-bonded dongle
        """
        assert classifyBond(BondState(), adapterPresent=True) is BondVerdict.LOST

    def test_classifyBond_bondedNo_isLost(self) -> None:
        """
        Given: paired but Bonded: no (link keys not persisted)
        When: classified
        Then: LOST -- the AC's literal trigger
        """
        state = BondState(known=True, paired=True, bonded=False, trusted=True)

        assert classifyBond(state, adapterPresent=True) is BondVerdict.LOST

    def test_classifyBond_noAdapter_isUnknownNotLost(self) -> None:
        """
        Given: bluez unreadable (missing bluetoothctl / no controller)
        When: classified
        Then: UNKNOWN, NOT lost

        LOAD-BEARING.  An absent bond record and an unreadable bluez produce
        the IDENTICAL BondState (every flag False).  Collapsing them would
        make the healer re-pair on every boot where bluez is merely slow to
        come up -- an auto-recovery that hammers the radio in response to its
        own blindness.  The adapter reading is what separates them.
        """
        assert classifyBond(BondState(), adapterPresent=False) is BondVerdict.UNKNOWN

    def test_classifyBond_noAdapter_neverReportsDurableEither(self) -> None:
        """
        Given: an unreadable adapter but a bond state that LOOKS durable
        When: classified
        Then: UNKNOWN -- unreadable is unreadable in both directions
        """
        state = BondState(known=True, paired=True, bonded=True, trusted=True)

        assert classifyBond(state, adapterPresent=False) is BondVerdict.UNKNOWN


# ================================================================================
# assess() -- detection over the real helper + fake CLI
# ================================================================================


class TestAssess:
    def test_assess_durableBond_reportsDurable(self) -> None:
        stack = FakeBtStack()

        verdict, state = _healer(stack).assess()

        assert verdict is BondVerdict.DURABLE
        assert state.bonded is True

    def test_assess_clearedBond_reportsLost(self, lostBondStack: FakeBtStack) -> None:
        """
        Given: the validation-criteria scenario (bond cleared on the Pi)
        When: assessed
        Then: LOST -- detection works off the real bluetoothctl parsing
        """
        verdict, _state = _healer(lostBondStack).assess()

        assert verdict is BondVerdict.LOST

    def test_assess_bluetoothctlMissing_reportsUnknownNotLost(self) -> None:
        """
        Given: no bluetoothctl at all (the runner raises FileNotFoundError)
        When: assessed
        Then: UNKNOWN -- and the healer did not crash on the missing binary
        """
        stack = FakeBtStack(bluetoothctlPresent=False)

        verdict, _state = _healer(stack).assess()

        assert verdict is BondVerdict.UNKNOWN


# ================================================================================
# selfHeal() -- the cheap paths, which must not touch the radio at all
# ================================================================================


class TestCheapPaths:
    def test_selfHeal_durableBond_isHealthyAndTouchesNothing(self) -> None:
        """
        Given: a healthy bond
        When: self-heal runs
        Then: HEALTHY, and neither the radio nor the logger was disturbed
        """
        stack = FakeBtStack()

        report = _healer(stack).selfHeal()

        assert report.outcome is SelfHealOutcome.HEALTHY
        assert stack.countMatching("power") == 0
        assert stack.countMatching("stop") == 0
        assert stack.pairScriptRuns() == 0
        assert report.operatorAction is None

    def test_selfHeal_trustMissing_restoresTrustWithoutStoppingCapture(self) -> None:
        """
        Given: a bond that lost only its Trusted flag
        When: self-heal runs
        Then: TRUST_RESTORED via the local flag -- no radio cycle, no re-pair,
              and capture is never interrupted

        Trust is a local bluez flag, so repairing it needs neither the dongle
        powered nor the logger stopped.  Escalating this case to a full
        re-pair would take capture down for a fault that costs one command.
        """
        stack = FakeBtStack(trusted=False)

        report = _healer(stack).selfHeal()

        assert report.outcome is SelfHealOutcome.TRUST_RESTORED
        assert stack.trusted is True
        assert stack.pairScriptRuns() == 0
        assert stack.countMatching("power", "off") == 0
        assert stack.countMatching("stop", OBD_UNIT) == 0

    def test_selfHeal_unreadableBluez_skipsAndNeverRePairs(self) -> None:
        """
        Given: bluez unreadable
        When: self-heal runs
        Then: SKIPPED_UNKNOWN -- no re-pair is attempted off a blind reading,
              and the attempt budget is NOT spent on it
        """
        stack = FakeBtStack(bluetoothctlPresent=False)
        healer = _healer(stack)

        report = healer.selfHeal()

        assert report.outcome is SelfHealOutcome.SKIPPED_UNKNOWN
        assert stack.pairScriptRuns() == 0
        assert healer.attemptsUsed == 0


# ================================================================================
# selfHeal() -- the re-pair path (AC1) and its serialisation (AC2)
# ================================================================================


class TestRePairPath:
    def test_selfHeal_lostBondInRange_rePairsAndVerifies(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: a cleared bond with the dongle powered + in range
        When: self-heal runs
        Then: REPAIRED, and the bond really is durable afterwards
        """
        report = _healer(lostBondStack).selfHeal()

        assert report.outcome is SelfHealOutcome.REPAIRED
        assert lostBondStack.bonded is True
        assert lostBondStack.trusted is True

    def test_selfHeal_stopsCaptureBeforePairingAndRestartsAfter(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: eclipse-obd is running and holding the port
        When: a re-pair runs
        Then: the stop precedes the pair and the start follows it

        AC2 verbatim: never pair while the logger contends on the port (the
        'multiple access' hazard of 2026-08-07).  Both commands being PRESENT
        is satisfied by an implementation that runs them in the wrong order,
        so the assertion is on the ORDER.
        """
        _healer(lostBondStack).selfHeal()

        stopAt = lostBondStack.indexOf("stop", OBD_UNIT)
        pairAt = lostBondStack.indexOf("pair_obdlink.sh")
        startAt = lostBondStack.indexOf("start", OBD_UNIT)

        assert stopAt >= 0, "capture was never stopped"
        assert pairAt >= 0, "the pair path never ran"
        assert startAt >= 0, "capture was never restarted"
        assert stopAt < pairAt < startAt
        assert lostBondStack.services[OBD_UNIT] is True

    def test_selfHeal_releasesRfcommBindingBeforePairing(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: a binding inherited from the stopped logger
        When: a re-pair runs
        Then: the rfcomm binding is released before pairing

        Stopping the process does NOT free the binding -- an rfcomm bind is a
        kernel table entry that outlives its creator (US-512's core fact).  A
        surviving /dev/rfcomm0 is literally the port contention AC2 forbids.
        """
        lostBondStack.seedInheritedBinding()

        _healer(lostBondStack).selfHeal()

        releaseAt = lostBondStack.indexOf("rfcomm", "release")
        pairAt = lostBondStack.indexOf("pair_obdlink.sh")
        assert releaseAt >= 0
        assert releaseAt < pairAt
        assert lostBondStack.isBound() is False

    def test_selfHeal_cannotStopCapture_abortsWithoutPairing(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: `systemctl stop eclipse-obd` fails
        When: self-heal runs
        Then: ABORTED_PORT_BUSY and the pair path NEVER runs

        Pairing anyway would be the exact hazard AC2 exists to prevent.  A
        failure to serialise must abort, not proceed hopefully.
        """
        lostBondStack.serviceControlFails.add((OBD_UNIT, "stop"))

        report = _healer(lostBondStack).selfHeal()

        assert report.outcome is SelfHealOutcome.ABORTED_PORT_BUSY
        assert lostBondStack.pairScriptRuns() == 0
        assert lostBondStack.countMatching("power", "off") == 0
        assert report.operatorAction is not None

    def test_selfHeal_atBootWithCaptureInactive_neitherStopsNorStarts(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: eclipse-obd is not running (the boot ordering case)
        When: self-heal runs
        Then: it pairs without issuing stop or start

        The healer is ordered Before=eclipse-obd, so at boot there is nothing
        to serialise against.  Issuing a stop into a boot transaction that is
        already queued to start the unit -- and then starting it early --
        would have the healer fighting systemd's own ordering.
        """
        lostBondStack.services[OBD_UNIT] = False

        report = _healer(lostBondStack).selfHeal()

        assert report.outcome is SelfHealOutcome.REPAIRED
        assert lostBondStack.countMatching("stop", OBD_UNIT) == 0
        assert lostBondStack.countMatching("start", OBD_UNIT) == 0

    def test_selfHeal_runsTheWedgeResetBeforeScanning(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: a lost bond
        When: self-heal runs
        Then: the adapter is cycled off->on and only THEN scanned

        AC1 names the BT-stack-wedge reset that was needed by hand on
        2026-08-07.  Scanning before the cycle would be scanning the wedged
        stack -- the state the reset exists to clear.
        """
        _healer(lostBondStack).selfHeal()

        offAt = lostBondStack.indexOf("power", "off")
        onAt = lostBondStack.indexOf("power", "on")
        scanAt = lostBondStack.indexOf("scan", "on")

        assert 0 <= offAt < onAt < scanAt

    def test_selfHeal_scansLongerThanThePairScriptsOwnScan(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: the healer's discovery scan
        When: compared with the pair driver's default
        Then: it is strictly longer

        AC1 says "longer scan".  A number is only longer than something --
        the thing it must beat is the pair driver's own DEFAULT_SCAN_SECONDS,
        which is the scan that was not enough on 2026-08-07.  Read from the
        driver rather than restated, so the two cannot drift apart silently.
        """
        import importlib.util

        driverPath = (
            Path(__file__).resolve().parents[3] / 'scripts' / 'pair_obdlink_driver.py'
        )
        spec = importlib.util.spec_from_file_location('_pairDriver', driverPath)
        assert spec is not None and spec.loader is not None
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)

        assert bond_self_heal.DISCOVERY_SCAN_SECONDS > driver.DEFAULT_SCAN_SECONDS

    def test_selfHeal_neverTouchesRfkill(self, lostBondStack: FakeBtStack) -> None:
        """
        Given: a full re-pair including the wedge reset
        When: every command issued is inspected
        Then: none of them is rfkill

        systemd-rfkill PERSISTS a soft-block across reboots -- that is how the
        07-03 outage became sticky (BL-025 P0, eclipse-rfkill-unblock.service).
        A recovery path that reaches for rfkill can re-arm exactly the failure
        it is recovering from, on the next boot, invisibly.  `bluetoothctl
        power` is a runtime D-Bus property and is not persisted.
        """
        _healer(lostBondStack).selfHeal()

        assert lostBondStack.countMatching("rfkill") == 0
        assert all(cmd[0] != "rfkill" for cmd in lostBondStack.commands)


# ================================================================================
# AC4 -- loud-surface when the dongle is not discoverable
# ================================================================================


class TestNotDiscoverable:
    def test_selfHeal_dongleOutOfRange_surfacesAndDoesNotPair(self) -> None:
        """
        Given: a lost bond and a dongle that discovery cannot see
        When: self-heal runs
        Then: NOT_DISCOVERABLE, the pair path never runs, and an operator
              action is named

        AC4: unattended re-pair only works against a discoverable+unbonded
        dongle.  Running `pair` at a dongle that is not there just burns the
        radio and produces a timeout that reads like a software fault.
        """
        stack = FakeBtStack(inRange=False)
        stack.clearBond()

        report = _healer(stack).selfHeal()

        assert report.outcome is SelfHealOutcome.NOT_DISCOVERABLE
        assert stack.pairScriptRuns() == 0
        assert report.operatorAction is not None
        assert "power" in report.operatorAction.lower()

    def test_selfHeal_notDiscoverable_scansOnceNotInALoop(self) -> None:
        """
        Given: a dongle discovery cannot find
        When: self-heal runs
        Then: exactly one scan was issued

        AC4 verbatim: "do NOT silently retry".  A retry loop against an absent
        dongle is the radio-hammering this refinement forbids.
        """
        stack = FakeBtStack(inRange=False)
        stack.clearBond()

        _healer(stack).selfHeal()

        assert stack.countMatching("scan", "on") == 1

    def test_selfHeal_notDiscoverable_stillRestoresRadioAndCapture(self) -> None:
        """
        Given: a heal that bails at the discovery gate
        When: it returns
        Then: the adapter is powered back on and capture is running again

        Never silent capture-death: the failure path must leave the box in a
        state where the NEXT connect can still work.  Bailing out with the
        radio off would convert a recoverable outage into a hard one.
        """
        stack = FakeBtStack(inRange=False)
        stack.clearBond()

        _healer(stack).selfHeal()

        assert stack.radioPowered is True
        assert stack.services[OBD_UNIT] is True


# ================================================================================
# AC3 -- bounded
# ================================================================================


class TestBounded:
    def test_selfHeal_secondCallInSameProcess_isSkippedByBudget(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: one heal has already run this boot
        When: a second is requested against a still-broken bond
        Then: SKIPPED_BUDGET and the pair path runs exactly once in total

        AC3: cap auto-re-pair -- never re-pair on EVERY connect-fail.
        """
        lostBondStack.pairScriptSucceeds = False
        healer = _healer(lostBondStack)

        first = healer.selfHeal()
        second = healer.selfHeal()

        assert first.outcome is SelfHealOutcome.REPAIR_FAILED
        assert second.outcome is SelfHealOutcome.SKIPPED_BUDGET
        assert lostBondStack.pairScriptRuns() == 1
        assert healer.attemptsUsed == 1

    def test_selfHeal_budgetExhausted_stillNamesTheOperatorRemedy(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: the budget is spent
        When: another heal is requested
        Then: the report still tells the operator what to do

        A cap that goes quiet is indistinguishable from a healer that is not
        running at all.  Bounded means "stop acting", not "stop reporting".
        """
        lostBondStack.pairScriptSucceeds = False
        healer = _healer(lostBondStack)
        healer.selfHeal()

        report = healer.selfHeal()

        assert report.operatorAction is not None
        assert SELF_HEAL_MAX_ATTEMPTS_PER_BOOT == 1

    def test_selfHeal_healthyBondAfterBudgetSpent_stillReportsHealthy(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: the budget is spent and the bond has since become durable
        When: self-heal runs
        Then: HEALTHY -- the cap gates ACTING, never OBSERVING
        """
        healer = _healer(lostBondStack)
        healer.selfHeal()

        report = healer.selfHeal()

        assert report.outcome is SelfHealOutcome.HEALTHY


# ================================================================================
# Verification + restoration invariants
# ================================================================================


class TestVerificationAndRestoration:
    def test_selfHeal_pairScriptExitsZeroButBondNotDurable_isRepairFailed(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: the pair script exits 0 while the bond is still not durable
        When: self-heal runs
        Then: REPAIR_FAILED

        The exit code describes the COMMAND; the bond flags describe the
        RESULT.  pair_obdlink_driver itself re-reads `info` for exactly this
        reason -- a caller that trusts rc==0 reports a fixed bond that is
        still broken, which is worse than reporting the failure.
        """
        lostBondStack.pairScriptLies = True

        report = _healer(lostBondStack).selfHeal()

        assert report.outcome is SelfHealOutcome.REPAIR_FAILED
        assert report.operatorAction is not None

    def test_selfHeal_pairScriptFails_radioIsPoweredBackOn(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: the pair path fails after the adapter was cycled off
        When: self-heal returns
        Then: the adapter is powered again

        The wedge reset powers the adapter DOWN.  Any early return between
        that and the power-on would strand the radio dark -- a self-heal that
        causes the outage it is named for.
        """
        lostBondStack.pairScriptSucceeds = False

        _healer(lostBondStack).selfHeal()

        assert lostBondStack.radioPowered is True

    def test_selfHeal_pairScriptRaises_captureIsStillRestarted(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: the pair invocation raises rather than returning a code
        When: self-heal returns
        Then: capture was restarted anyway and nothing propagated

        'Never silent capture-death' has to hold on the exception path too --
        that is the path nobody tests and the one that leaves the car mute.
        """
        realRunner = lostBondStack.runner

        def explodingRunner(cmd: list[str], **kwargs: object):  # type: ignore[no-untyped-def]
            if cmd[0].replace("\\", "/").endswith("pair_obdlink.sh"):
                lostBondStack.commands.append(list(cmd))
                raise OSError("boom")
            return realRunner(cmd, **kwargs)

        healer = BondSelfHealer(
            lostBondStack.mac,
            subprocessRunner=explodingRunner,
            sleepFn=lambda _seconds: None,
        )

        report = healer.selfHeal()

        assert report.outcome is SelfHealOutcome.REPAIR_FAILED
        assert lostBondStack.services[OBD_UNIT] is True
        assert lostBondStack.radioPowered is True

    def test_selfHeal_everyOutcomeIsReportedOnTheGreppableLogLine(
        self, lostBondStack: FakeBtStack, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Given: a heal that ends in a non-healthy outcome
        When: the journal is read
        Then: one line carries the pinned prefix AND the outcome

        The operator's only cheap check is the journal.  Pinning the prefix as
        a constant keeps the grep, the code and this test on one token.
        """
        caplog.set_level("INFO")

        report = _healer(lostBondStack).selfHeal()

        lines = [
            record.getMessage()
            for record in caplog.records
            if BOND_SELF_HEAL_LOG_PREFIX in record.getMessage()
        ]
        assert lines, "no self-heal line reached the journal"
        assert any(report.outcome.value in line for line in lines)

    def test_selfHeal_distinguishesItsFailureModesFromEachOther(self) -> None:
        """
        Given: the four distinct ways a heal can fail to fix the bond
        When: each is run
        Then: all four report a DIFFERENT outcome

        The defect this story closes is 'capture died and nothing said why'.
        A single generic failure outcome would pass every did-it-report test
        while leaving the operator exactly as blind as before -- the four
        cases have four different remedies (power-cycle the dongle / grant
        service control / wait for the next boot / re-pair by hand).
        """
        def _run(**stackKwargs: object) -> SelfHealOutcome:
            stack = FakeBtStack(**stackKwargs)  # type: ignore[arg-type]
            stack.clearBond()
            return _healer(stack).selfHeal().outcome

        outOfRange = _run(inRange=False)
        pairFailed = _run(pairScriptSucceeds=False)
        blindStack = FakeBtStack(bluetoothctlPresent=False)
        unreadable = _healer(blindStack).selfHeal().outcome

        busyStack = FakeBtStack()
        busyStack.clearBond()
        busyStack.serviceControlFails.add((OBD_UNIT, "stop"))
        portBusy = _healer(busyStack).selfHeal().outcome

        outcomes = {outOfRange, pairFailed, unreadable, portBusy}
        assert len(outcomes) == 4, f"failure modes collapsed: {outcomes}"


# ================================================================================
# The request seam -- how the running logger asks for a heal (AC1 "reconnect path")
# ================================================================================


class TestRequestSeam:
    def setup_method(self) -> None:
        resetSelfHealRequestBudget()

    def teardown_method(self) -> None:
        resetSelfHealRequestBudget()

    def test_requestBondSelfHeal_startsTheUnitWithoutBlocking(self) -> None:
        """
        Given: a running logger that has detected a lost bond
        When: it requests a heal
        Then: the self-heal unit is started with --no-block

        The logger cannot run the heal itself: the heal must STOP the logger
        (AC2), so an in-process heal would be a process asking to be killed
        mid-call.  It delegates to the unit and returns immediately; systemd
        owns the stop/pair/start from there.
        """
        stack = FakeBtStack()

        assert requestBondSelfHeal(DEFAULT_MAC, subprocessRunner=stack.runner) is True
        assert stack.indexOf("systemctl", "start", "--no-block", SELF_HEAL_UNIT) >= 0

    def test_requestBondSelfHeal_secondRequest_isSuppressed(self) -> None:
        """
        Given: a heal has already been requested this process
        When: another connect-fail requests one
        Then: it is suppressed

        AC3 again, at the other end: the reconnect path retries forever by
        design, so an unbounded request would restart the unit on every cycle.
        """
        stack = FakeBtStack()

        first = requestBondSelfHeal(DEFAULT_MAC, subprocessRunner=stack.runner)
        second = requestBondSelfHeal(DEFAULT_MAC, subprocessRunner=stack.runner)

        assert (first, second) == (True, False)
        assert stack.countMatching("start", SELF_HEAL_UNIT) == 1

    def test_requestBondSelfHeal_systemctlMissing_returnsFalseAndDoesNotRaise(
        self,
    ) -> None:
        """
        Given: systemctl is absent (dev box)
        When: a heal is requested
        Then: False, no exception

        This runs inside the capture path.  A request that raises would turn
        a bond warning into a capture crash.
        """
        def missingRunner(cmd: list[str], **kwargs: object):  # type: ignore[no-untyped-def]
            raise FileNotFoundError("systemctl")

        assert requestBondSelfHeal(DEFAULT_MAC, subprocessRunner=missingRunner) is False

    def test_requestBondSelfHeal_failedStart_doesNotConsumeTheBudget(self) -> None:
        """
        Given: the first request could not start the unit
        When: a later connect-fail requests again
        Then: it is allowed through

        A budget that counts ATTEMPTS rather than actual starts would let one
        transient systemctl failure disable self-heal for the whole boot.
        """
        stack = FakeBtStack()
        stack.serviceControlFails.add((SELF_HEAL_UNIT, "start"))

        assert requestBondSelfHeal(DEFAULT_MAC, subprocessRunner=stack.runner) is False

        stack.serviceControlFails.clear()
        assert requestBondSelfHeal(DEFAULT_MAC, subprocessRunner=stack.runner) is True


# ================================================================================
# AC1 -- "verify_bt_pair.sh exists -- wire it into the reconnect path"
# ================================================================================


class TestVerifyScriptWiring:
    def test_selfHeal_runsTheExistingVerifyScriptAfterRePairing(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: a re-pair has run
        When: the heal finishes
        Then: scripts/verify_bt_pair.sh ran, after the pair

        AC1 names the script by name.  It checks a WIDER surface than the bond
        flags -- the rfcomm bind and rfcomm-bind.service too -- so its output
        in the journal is the snapshot an operator would otherwise have to SSH
        in and produce by hand.
        """
        _healer(lostBondStack).selfHeal()

        verifyAt = lostBondStack.indexOf("verify_bt_pair.sh")
        pairAt = lostBondStack.indexOf("pair_obdlink.sh")

        assert verifyAt > pairAt >= 0

    def test_selfHeal_doesNotUseTheVerifyScriptsExitCodeAsTheVerdict(
        self, lostBondStack: FakeBtStack
    ) -> None:
        """
        Given: a bond that is Paired + Trusted but NOT Bonded
        When: the heal verifies
        Then: REPAIR_FAILED, even though verify_bt_pair.sh exits 0

        THE REASON THE SNAPSHOT IS NOT THE GATE.  verify_bt_pair.sh reports an
        unset `Bonded` as [INFO], not [FAIL] -- so it returns 0 over exactly
        the state this story is named for.  Wiring it in as the verdict would
        have made the healer declare success on a bond that cannot survive a
        reboot.  The gate stays on the bond flags read back from bluez.
        """
        lostBondStack.pairScriptLies = True
        lostBondStack.known = True
        lostBondStack.paired = True
        lostBondStack.trusted = True
        lostBondStack.bonded = False

        report = _healer(lostBondStack).selfHeal()

        verify = lostBondStack.runner(
            [str(_healer(lostBondStack).verifyScriptPath), lostBondStack.mac]
        )
        assert verify.returncode == 0, "fixture no longer reproduces the blind spot"
        assert report.outcome is SelfHealOutcome.REPAIR_FAILED

    def test_defaultVerifyScriptPath_pointsAtAScriptThatExists(self) -> None:
        """
        Given: the healer's default verify-script path
        When: the filesystem is checked
        Then: the script is there

        Same trap as the pair script: the fake matches on a FILENAME, so a
        path typo stays green here and exits 127 on the Pi.
        """
        assert Path(BondSelfHealer(DEFAULT_MAC).verifyScriptPath).is_file()


# ================================================================================
# The reconnect path -- ObdConnection detects and delegates (AC1)
# ================================================================================


class TestConnectPathWiring:
    """`_assureDurableBond` runs on EVERY connect, so it is the reconnect path.

    Patching is at the ``bluetooth_helper`` runner attributes -- the one seam
    the whole chain reads the world through -- so the real ``ensureTrusted``,
    the real bond parsing and the real verdict logic all execute.
    """

    def setup_method(self) -> None:
        resetSelfHealRequestBudget()

    def teardown_method(self) -> None:
        resetSelfHealRequestBudget()

    @staticmethod
    def _connection(stack: FakeBtStack, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
        from src.pi.obdii import bluetooth_helper as helper
        from src.pi.obdii.obd_connection import ObdConnection

        monkeypatch.setattr(helper, '_defaultRunner', stack.runner)
        monkeypatch.setattr(helper, 'defaultSubprocessRunner', stack.runner)
        return ObdConnection(
            config={'pi': {'bluetooth': {'macAddress': stack.mac}}},
        )

    def test_assureDurableBond_lostBond_requestsTheSelfHeal(
        self, lostBondStack: FakeBtStack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: a connect attempt against a de-bonded dongle
        When: the connect path assures the bond
        Then: the self-heal unit is requested

        This is the "repeated connect-fail" trigger.  It fires on the FIRST
        observation deliberately: unlike a connect failure, `bonded=no` is a
        durable fact read straight out of bluez, so waiting for it to repeat
        only delays recovery without adding information.  The cap is what
        keeps it from becoming a loop.
        """
        conn = self._connection(lostBondStack, monkeypatch)

        conn._assureDurableBond(lostBondStack.mac)

        assert lostBondStack.countMatching("start", SELF_HEAL_UNIT) == 1

    def test_assureDurableBond_healthyBond_requestsNothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: a durable bond
        When: the connect path assures it
        Then: no heal is requested -- the normal case stays silent and free
        """
        stack = FakeBtStack()
        conn = self._connection(stack, monkeypatch)

        conn._assureDurableBond(stack.mac)

        assert stack.countMatching("start", SELF_HEAL_UNIT) == 0

    def test_assureDurableBond_unreadableBluez_requestsNothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: bluez unreadable (no controller answering)
        When: the connect path assures the bond
        Then: NO heal is requested

        THE FALSE-TRIGGER GUARD.  An unreadable bluez yields the same all-False
        BondState as a genuinely cleared bond.  Without the adapter reading,
        every boot where bluetooth.service is a little slow would stop capture
        and re-pair the dongle -- an "auto-recovery" that manufactures the
        outage it is supposed to fix.
        """
        stack = FakeBtStack(adapterPresent=False)
        stack.clearBond()
        conn = self._connection(stack, monkeypatch)

        conn._assureDurableBond(stack.mac)

        assert stack.countMatching("start", SELF_HEAL_UNIT) == 0

    def test_assureDurableBond_requestFailure_doesNotBreakTheConnect(
        self, lostBondStack: FakeBtStack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: systemctl refuses to start the self-heal unit
        When: the connect path assures the bond
        Then: nothing propagates

        Bond assurance is advisory.  A heal that cannot be requested must not
        fail a connect attempt that would otherwise have worked.
        """
        lostBondStack.serviceControlFails.add((SELF_HEAL_UNIT, "start"))
        conn = self._connection(lostBondStack, monkeypatch)

        conn._assureDurableBond(lostBondStack.mac)  # must not raise


# ================================================================================
# The real invocation -- no overrides, genuine subprocess
# ================================================================================


class TestRealInvocationPath:
    def test_healer_withNoInjectedRunner_usesTheRealSubprocess(self) -> None:
        """
        Given: a healer built with NO runner override at all
        When: it assesses the bond on this box
        Then: UNKNOWN -- the genuine subprocess ran and genuinely failed

        US-550's mutation C in one test: a suite whose every case forces a
        runner proves the fake works and never once executes the default.
        On a Windows dev box there is no bluetoothctl, so the real call
        raises FileNotFoundError and the honest answer is UNKNOWN.  If the
        default were ever swapped for a stub, or the missing-binary path made
        to fabricate a bond, this goes red.
        """
        healer = BondSelfHealer(DEFAULT_MAC)

        verdict, state = healer.assess()

        assert verdict is BondVerdict.UNKNOWN
        assert state.known is False

    def test_defaultPairScriptPath_pointsAtAScriptThatExists(self) -> None:
        """
        Given: the healer's default pair-script path
        When: the filesystem is checked
        Then: the script is there

        The re-pair path is 'run scripts/pair_obdlink.sh'.  A path typo turns
        the entire story into a unit that exits non-zero on the Pi and nowhere
        else -- the tests would stay green because the fake matches on the
        filename, not on the file existing.
        """
        healer = BondSelfHealer(DEFAULT_MAC)

        assert Path(healer.pairScriptPath).is_file()

    def test_serviceUnitDefault_matchesTheShippedUnitName(self) -> None:
        """
        Given: the unit name the healer serialises against
        When: compared with the shipped unit file
        Then: they agree

        `systemctl stop <typo>` exits non-zero and the healer would abort --
        but only on the Pi.  Pin the name against the artifact on disk.
        """
        repoRoot = Path(__file__).resolve().parents[3]

        assert (repoRoot / 'deploy' / OBD_SERVICE_UNIT).is_file()
