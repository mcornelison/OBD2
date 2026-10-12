################################################################################
# File Name: bond_self_heal.py
# Purpose/Description: US-545 (Atlas A-18) -- detect a lost / de-bonded OBDLink
#                      BT bond and either auto-run the re-pair path or surface
#                      it loudly.  Bounded (once per boot), serialised against
#                      eclipse-obd (never pair while the logger holds the port)
#                      and honest when the dongle simply is not there.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-10    | Rex (US-545) | Initial -- A-18 follow-on.  The bond outage of
#               |              | 2026-07-03..08-07 killed capture for a month and
#               |              | nothing in the stack ever said "the bond is
#               |              | gone"; US-512 added the RUNTIME bond READ but
#               |              | could only repair the Trusted flag.  This is the
#               |              | recovery half.
# ================================================================================
################################################################################

"""Bounded, serialised self-heal for a lost Bluetooth bond.

THE DEFECT
----------
``scripts/pair_obdlink.sh`` writes Paired+Bonded+Trusted at pair time; US-512
added :func:`~src.pi.obdii.bluetooth_helper.readBondState` so the connect path
could READ them back, and :func:`~src.pi.obdii.bluetooth_helper.ensureTrusted`
so it could repair the one flag that is repairable locally.  Everything else --
a bond bluez has actually dropped -- produced a warning and then capture died
quietly for as long as nobody read the journal.  That is the month-long outage
this module exists to make impossible.

WHY THIS IS A SEPARATE PROCESS AND NOT A METHOD ON THE CONNECTION
-----------------------------------------------------------------
The Atlas refinement is explicit: the re-pair MUST stop ``eclipse-obd`` first,
because pairing while the logger contends on the port is the "multiple access
on port?" hazard hit by hand on 2026-08-07.  A heal running INSIDE eclipse-obd
would therefore have to ask systemd to kill its own caller mid-call.  So the
heal is a standalone unit (``deploy/eclipse-bond-selfheal.service``) and the
logger only ever *requests* it, via :func:`requestBondSelfHeal`.  Two entry
points, one implementation:

* **boot** -- the unit is ordered ``Before=eclipse-obd.service`` and runs
  :func:`main`.  Nothing is running yet, so nothing is stopped.
* **repeated connect-fail** -- ``ObdConnection._assureDurableBond`` observes a
  non-durable bond and calls :func:`requestBondSelfHeal`, which starts the unit
  ``--no-block`` and returns.  systemd owns the stop/pair/start from there.

THE FOUR HONEST ANSWERS
-----------------------
``bonded=no`` is not one situation.  Reporting a single generic failure would
satisfy every "did it report?" check while leaving the operator exactly as
blind as before, so the outcomes stay distinct -- they have different remedies:

* :attr:`SelfHealOutcome.NOT_DISCOVERABLE` -- power-cycle the dongle / engine on
* :attr:`SelfHealOutcome.ABORTED_PORT_BUSY` -- service control was refused
* :attr:`SelfHealOutcome.SKIPPED_BUDGET`    -- already tried this boot
* :attr:`SelfHealOutcome.REPAIR_FAILED`     -- pair ran and the bond is still bad

and :attr:`SelfHealOutcome.SKIPPED_UNKNOWN` for the case that must never be
mistaken for any of them: bluez itself was unreadable.

TWO INVARIANTS THAT ARE EASY TO BREAK LATER
-------------------------------------------
1. **Never rfkill.**  The wedge reset cycles the adapter with ``bluetoothctl
   power off/on`` -- a runtime D-Bus property.  ``rfkill`` soft-blocks are
   PERSISTED by systemd-rfkill across reboots, which is how the 07-03 outage
   became sticky and why ``eclipse-rfkill-unblock.service`` exists.  A recovery
   path that reaches for rfkill can re-arm the very failure it is recovering
   from, on the next boot, invisibly.
2. **Never return with the radio down or capture stopped.**  Both restorations
   live in a ``finally``.  Every early return between the power-off and the
   power-on would otherwise convert a recoverable outage into a hard one.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from . import bluetooth_helper
from .bluetooth_helper import BondState, SubprocessRunner

logger = logging.getLogger(__name__)

__all__ = [
    'BOND_SELF_HEAL_LOG_PREFIX',
    'DISCOVERY_SCAN_SECONDS',
    'OBD_SERVICE_UNIT',
    'SELF_HEAL_MAX_ATTEMPTS_PER_BOOT',
    'SELF_HEAL_UNIT',
    'STACK_RESET_SETTLE_SECONDS',
    'BondSelfHealer',
    'BondVerdict',
    'SelfHealOutcome',
    'SelfHealReport',
    'classifyBond',
    'main',
    'parseAdapterPowered',
    'parseInRange',
    'requestBondSelfHeal',
    'resetSelfHealRequestBudget',
]


# ================================================================================
# Constants
# ================================================================================

#: Pinned journal token.  The operator's only cheap check is
#: ``journalctl -u eclipse-bond-selfheal -u eclipse-obd | grep 'BOND SELF-HEAL'``,
#: so the grep, the code and the tests all read this one constant.
BOND_SELF_HEAL_LOG_PREFIX: str = "BOND SELF-HEAL"

#: The capture unit this module serialises against (Atlas refinement 2).
OBD_SERVICE_UNIT: str = "eclipse-obd.service"

#: The unit that RUNS the heal.  Started ``--no-block`` by the logger; ordered
#: ``Before=eclipse-obd.service`` at boot.
SELF_HEAL_UNIT: str = "eclipse-bond-selfheal.service"

#: Atlas refinement 3 -- bounded, not a loop.  ONE unattended re-pair per boot.
#: The reconnect path retries forever by design, so an uncapped heal would
#: re-pair on every connect-fail and hammer the radio (US-325's I-025 lesson,
#: where a fixed-cadence retry starved the Pi 5's shared WiFi+BT chip).
SELF_HEAL_MAX_ATTEMPTS_PER_BOOT: int = 1

#: Same cap on the REQUEST side: the logger asks at most once per process.
SELF_HEAL_MAX_REQUESTS_PER_BOOT: int = 1

#: The "longer scan" of AC1.  ``pair_obdlink_driver.DEFAULT_SCAN_SECONDS`` is
#: 7s, which is the scan that was not enough when the stack was wedged on
#: 2026-08-07 -- the fix needed a power cycle AND more discovery time.  This is
#: the discovery gate only; the pair script still runs its own scan afterwards.
DISCOVERY_SCAN_SECONDS: int = 20

#: Settle time either side of the adapter power cycle.  bluez tears down and
#: re-registers the controller on the D-Bus; scanning into that window returns
#: "No default controller available" and reads as "dongle absent".
STACK_RESET_SETTLE_SECONDS: float = 2.0

SYSTEMCTL_CMD: str = "systemctl"

#: Path of the re-pair path AC1 says to run, relative to the repo root.
PAIR_SCRIPT_RELPATH: str = "scripts/pair_obdlink.sh"

#: The US-196 status snapshot AC1 names ("verify_bt_pair.sh exists -- wire it
#: into the reconnect path").  Run for its OUTPUT, never for its verdict: it
#: reports an unset ``Bonded`` flag as ``[INFO]`` rather than ``[FAIL]``, so it
#: exits 0 over precisely the not-bonded state this module exists to fix.  What
#: it is genuinely good at is the WIDER surface -- the rfcomm bind and
#: rfcomm-bind.service -- which the bond flags say nothing about, and which an
#: operator would otherwise have to SSH in and check by hand.
VERIFY_SCRIPT_RELPATH: str = "scripts/verify_bt_pair.sh"

#: The verify snapshot shells out to bluetoothctl/rfcomm/systemctl; capped so a
#: wedged one cannot outlive the heal that is holding capture down.
VERIFY_SCRIPT_TIMEOUT_SECONDS: float = 30.0

#: Wall-clock cap on the pair invocation.  The driver's own PAIR_TIMEOUT is 60s
#: plus its scan; this is the outer guard so a wedged bluez can never park the
#: heal -- and therefore capture -- indefinitely.
PAIR_SCRIPT_TIMEOUT_SECONDS: float = 180.0

_POWERED_RE = re.compile(r'^\s*Powered:\s*(yes|no)\s*$', re.MULTILINE)

#: RSSI and TxPower are both read off a live advertisement.  Their PRESENCE is
#: the signal, not their value -- see :func:`parseInRange`.
_IN_RANGE_RE = re.compile(r'^\s*(?:RSSI|TxPower):\s*-?\d+\s*$', re.MULTILINE)

_ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')


# ================================================================================
# Types
# ================================================================================


class BondVerdict(Enum):
    """What the bond flags mean, once the adapter reading is taken into account."""

    #: Paired + Bonded + Trusted -- nothing to do.
    DURABLE = 'durable'
    #: Paired + Bonded but not Trusted.  Repairable locally, dongle not needed.
    TRUST_MISSING = 'trust-missing'
    #: bluez is answering and the bond is genuinely gone or not persisted.
    LOST = 'lost'
    #: bluez could not be read at all.  NEVER acted on -- see :func:`classifyBond`.
    UNKNOWN = 'unknown'


class SelfHealOutcome(Enum):
    """What the heal actually did.  Distinct per remedy, never collapsed."""

    HEALTHY = 'healthy'
    TRUST_RESTORED = 'trust-restored'
    REPAIRED = 'repaired'
    REPAIR_FAILED = 'repair-failed'
    NOT_DISCOVERABLE = 'not-discoverable'
    SKIPPED_BUDGET = 'skipped-budget'
    SKIPPED_UNKNOWN = 'skipped-unknown'
    ABORTED_PORT_BUSY = 'aborted-port-busy'


#: Outcomes that leave the bond usable.  Everything else owes the operator
#: something, which is why :class:`SelfHealReport` carries ``operatorAction``.
_GOOD_OUTCOMES: frozenset[SelfHealOutcome] = frozenset({
    SelfHealOutcome.HEALTHY,
    SelfHealOutcome.TRUST_RESTORED,
    SelfHealOutcome.REPAIRED,
})


@dataclass(frozen=True)
class SelfHealReport:
    """One heal attempt, rendered for both the journal and a caller.

    Attributes:
        outcome: What happened.
        verdict: The bond reading the decision was made from.
        macAddress: The dongle this is about.
        bondState: The final bond flags actually read back (never assumed).
        attemptsUsed: Re-pairs spent this boot, against the cap.
        detail: One human-readable sentence.
        operatorAction: The remedy a human owes, or None when nothing is owed.
    """

    outcome: SelfHealOutcome
    verdict: BondVerdict
    macAddress: str
    bondState: BondState
    attemptsUsed: int
    detail: str
    operatorAction: str | None = None

    @property
    def ok(self) -> bool:
        """True when the bond is usable after this attempt."""
        return self.outcome in _GOOD_OUTCOMES


# ================================================================================
# Pure readings
# ================================================================================


def parseAdapterPowered(showOutput: str) -> bool | None:
    """Read the controller's ``Powered`` flag out of ``bluetoothctl show``.

    Args:
        showOutput: Raw (possibly ANSI-coloured) output.

    Returns:
        True/False when a controller answered, ``None`` when there was no
        controller block at all.

    ``None`` is a third answer on purpose.  "No default controller available",
    a missing ``bluetoothctl`` and a controller that is merely switched off are
    three different facts, and only the first two mean *we cannot see*.
    Folding them into False would make every unreadable stack look like a
    powered-down one.
    """
    match = _POWERED_RE.search(_ANSI_RE.sub('', showOutput or ''))
    if match is None:
        return None
    return match.group(1) == 'yes'


def parseInRange(infoOutput: str) -> bool:
    """True when ``bluetoothctl info`` shows the device is advertising NOW.

    Args:
        infoOutput: Raw output of ``info <MAC>``.

    Returns:
        True if an ``RSSI:`` or ``TxPower:`` line is present.

    THE DISCRIMINATOR, and the reason this is not just "did info return a
    block".  A fully-bonded record proves bluez REMEMBERS the dongle; it says
    nothing about whether the dongle is powered.  The OBDLink LX is bus-powered
    off the OBD port, so engine-off it is simply absent while its record sits
    there looking healthy.  RSSI/TxPower can only come from an advertisement
    received during discovery, so they cannot be satisfied by a stale record.

    Errs toward False: if bluez ever stops emitting either field, the heal
    reports NOT_DISCOVERABLE and asks the operator, rather than pairing at
    something it never saw.  That is the safe direction for an unattended
    action on a car-mounted radio.
    """
    return _IN_RANGE_RE.search(_ANSI_RE.sub('', infoOutput or '')) is not None


def classifyBond(state: BondState, adapterPresent: bool) -> BondVerdict:
    """Turn bond flags + an adapter reading into an actionable verdict.

    Args:
        state: Flags from :func:`~src.pi.obdii.bluetooth_helper.readBondState`.
        adapterPresent: Whether ``bluetoothctl show`` answered at all.

    Returns:
        The :class:`BondVerdict`.

    LOAD-BEARING: ``adapterPresent`` is what separates LOST from UNKNOWN.  A
    de-bonded device and an unreadable bluez produce the IDENTICAL
    ``BondState`` -- every flag False -- because ``bluetoothctl remove`` deletes
    the record outright.  Without the adapter reading, a Pi whose bluez is
    merely slow to come up on boot would be diagnosed as de-bonded and would
    auto-re-pair in response to its own blindness.  So: no adapter reading, no
    action, in EITHER direction (a "durable" reading is equally untrustworthy
    when the source could not be reached).
    """
    if not adapterPresent:
        return BondVerdict.UNKNOWN
    if bluetooth_helper.isDurableBond(state):
        return BondVerdict.DURABLE
    if state.known and state.paired and state.bonded and not state.trusted:
        return BondVerdict.TRUST_MISSING
    return BondVerdict.LOST


# ================================================================================
# The healer
# ================================================================================


class BondSelfHealer:
    """Detect a lost bond and run the bounded, serialised recovery.

    Args:
        macAddress: The dongle MAC.
        subprocessRunner: CLI seam.  Defaults to the SAME runner
            ``bluetooth_helper`` uses, so a test that injects one fake sees
            every command this class issues, including the ones it delegates.
        sleepFn: Injected sleep (the settle waits).
        serviceUnit: Capture unit to serialise against.
        pairScriptPath: Override for the re-pair path.
        maxAttempts: Re-pair cap for this process (Atlas refinement 3).
        scanSeconds: Discovery-gate scan length.
        settleSeconds: Wait either side of the adapter power cycle.
    """

    def __init__(
        self,
        macAddress: str,
        *,
        subprocessRunner: SubprocessRunner | None = None,
        sleepFn: Callable[[float], None] | None = None,
        serviceUnit: str = OBD_SERVICE_UNIT,
        pairScriptPath: str | os.PathLike[str] | None = None,
        verifyScriptPath: str | os.PathLike[str] | None = None,
        maxAttempts: int = SELF_HEAL_MAX_ATTEMPTS_PER_BOOT,
        scanSeconds: int = DISCOVERY_SCAN_SECONDS,
        settleSeconds: float = STACK_RESET_SETTLE_SECONDS,
    ) -> None:
        self.macAddress = macAddress
        self._runner: SubprocessRunner = (
            subprocessRunner or bluetooth_helper.defaultSubprocessRunner
        )
        self._sleep = sleepFn if sleepFn is not None else time.sleep
        self._serviceUnit = serviceUnit
        self.pairScriptPath = str(
            pairScriptPath if pairScriptPath is not None
            else _repoScript(PAIR_SCRIPT_RELPATH)
        )
        self.verifyScriptPath = str(
            verifyScriptPath if verifyScriptPath is not None
            else _repoScript(VERIFY_SCRIPT_RELPATH)
        )
        self._maxAttempts = maxAttempts
        self._scanSeconds = scanSeconds
        self._settleSeconds = settleSeconds
        self._attemptsUsed = 0

    @property
    def attemptsUsed(self) -> int:
        """Re-pairs spent this process, against :attr:`_maxAttempts`."""
        return self._attemptsUsed

    # --------------------------------------------------------------------------
    # Detection
    # --------------------------------------------------------------------------

    def assess(self) -> tuple[BondVerdict, BondState]:
        """Read the adapter + the bond and classify.

        Returns:
            ``(verdict, state)``.  Never raises: every reading is best-effort
            and an unreadable one resolves to :attr:`BondVerdict.UNKNOWN`.
        """
        adapterPowered = self.readAdapterPowered()
        state = bluetooth_helper.readBondState(
            self.macAddress, subprocessRunner=self._runner
        )
        return classifyBond(state, adapterPresent=adapterPowered is not None), state

    def readAdapterPowered(self) -> bool | None:
        """``bluetoothctl show`` -> Powered flag, or None when unreadable."""
        result = self._run([
            bluetooth_helper.BLUETOOTHCTL_CMD,
            '--timeout', str(bluetooth_helper.BLUETOOTHCTL_TIMEOUT_S),
            'show',
        ])
        if result is None or result.returncode != 0:
            return None
        return parseAdapterPowered(result.stdout or '')

    # --------------------------------------------------------------------------
    # The heal
    # --------------------------------------------------------------------------

    def selfHeal(self) -> SelfHealReport:
        """Assess the bond and act, within the cap.  Never raises.

        Returns:
            The :class:`SelfHealReport`, which is also emitted to the journal
            under :data:`BOND_SELF_HEAL_LOG_PREFIX`.
        """
        verdict, state = self.assess()

        if verdict is BondVerdict.UNKNOWN:
            return self._finish(
                SelfHealOutcome.SKIPPED_UNKNOWN, verdict, state,
                "bluez could not be read (no controller / no bluetoothctl) -- "
                "refusing to act on a blind reading",
                "check `systemctl status bluetooth` and `bluetoothctl show` on the Pi",
            )

        if verdict is BondVerdict.DURABLE:
            return self._finish(
                SelfHealOutcome.HEALTHY, verdict, state,
                "bond is Paired+Bonded+Trusted",
            )

        if verdict is BondVerdict.TRUST_MISSING:
            # The cheap path first: Trusted is a local bluez flag, so this
            # needs neither the dongle powered nor capture stopped.  Escalating
            # it to a full re-pair would take capture down for a fault that
            # costs one command.
            repaired = bluetooth_helper.ensureTrusted(
                self.macAddress, subprocessRunner=self._runner
            )
            if bluetooth_helper.isDurableBond(repaired):
                return self._finish(
                    SelfHealOutcome.TRUST_RESTORED, verdict, repaired,
                    "Trusted flag restored locally -- no re-pair, no capture "
                    "interruption",
                )
            logger.warning(
                "%s | trust restore did not produce a durable bond -- escalating "
                "to the re-pair path", BOND_SELF_HEAL_LOG_PREFIX,
            )
            state = repaired
            verdict = BondVerdict.LOST

        return self._runBoundedRePair(verdict, state)

    def _runBoundedRePair(
        self, verdict: BondVerdict, state: BondState
    ) -> SelfHealReport:
        """Stop capture, reset the stack, gate on discovery, pair, verify."""
        if self._attemptsUsed >= self._maxAttempts:
            return self._finish(
                SelfHealOutcome.SKIPPED_BUDGET, verdict, state,
                f"auto-re-pair already used {self._attemptsUsed}/"
                f"{self._maxAttempts} attempt(s) this boot -- not hammering the "
                "radio",
                f"re-pair by hand: scripts/pair_obdlink.sh {self.macAddress} "
                "(dongle powered, engine on), or reboot to reset the cap",
            )

        # Consumed BEFORE the work, not after: a heal that dies mid-way must
        # not leave a budget that lets the next connect-fail start another one.
        self._attemptsUsed += 1

        # At boot the healer is ordered Before=eclipse-obd, so there is nothing
        # to serialise against.  Issuing a stop into a boot transaction already
        # queued to START the unit -- and then starting it early ourselves --
        # would have us fighting systemd's own ordering.
        captureWasRunning = self._isUnitActive(self._serviceUnit)
        if captureWasRunning and not self._controlUnit('stop', self._serviceUnit):
            return self._finish(
                SelfHealOutcome.ABORTED_PORT_BUSY, verdict, state,
                f"could not stop {self._serviceUnit} -- refusing to pair while "
                "the logger may still hold the port",
                "grant service control (polkit rule 51-eclipse-service-control) "
                f"or stop {self._serviceUnit} by hand before re-pairing",
            )

        try:
            # Stopping the process does NOT free the rfcomm binding: a bind is
            # a kernel table entry that outlives its creator (US-512).  A
            # surviving /dev/rfcommN is literally the contention we just
            # stopped the logger to avoid.
            self._releaseBinding()
            self._resetBtStack()

            if not self._isDiscoverable():
                return self._finish(
                    SelfHealOutcome.NOT_DISCOVERABLE, verdict, state,
                    f"{self.macAddress} did not answer a {self._scanSeconds}s "
                    "scan after a full adapter reset -- not pairing at a dongle "
                    "that is not there, and NOT retrying",
                    "power-cycle the OBDLink LX (engine on / re-seat it) so it "
                    "advertises, then re-run the self-heal",
                )

            paired = self._runPairScript()
            self._runVerifySnapshot()
            finalState = bluetooth_helper.readBondState(
                self.macAddress, subprocessRunner=self._runner
            )
            if bluetooth_helper.isDurableBond(finalState):
                return self._finish(
                    SelfHealOutcome.REPAIRED, verdict, finalState,
                    "re-paired and verified Paired+Bonded+Trusted",
                )
            return self._finish(
                SelfHealOutcome.REPAIR_FAILED, verdict, finalState,
                "the re-pair path "
                + ("exited non-zero" if not paired else "reported success")
                + " but the bond read back is still not durable",
                f"run scripts/pair_obdlink.sh {self.macAddress} interactively "
                "with the dongle in pair mode and read its output",
            )
        finally:
            # Both restorations are unconditional.  Every early return above
            # sits between the power-off and here.
            self._ensureRadioPowered()
            if captureWasRunning:
                self._controlUnit('start', self._serviceUnit)

    # --------------------------------------------------------------------------
    # Steps
    # --------------------------------------------------------------------------

    def _releaseBinding(self) -> None:
        """Drop any surviving /dev/rfcommN so nothing holds the dongle."""
        try:
            bluetooth_helper.releaseRfcomm(subprocessRunner=self._runner)
        except Exception as exc:  # noqa: BLE001 -- recovery must not raise
            logger.debug("rfcomm release during self-heal failed: %s", exc)

    def _resetBtStack(self) -> None:
        """The 2026-08-07 wedge reset: cycle the adapter, settle either side.

        ``bluetoothctl power off/on`` ONLY.  Never ``rfkill`` -- see the module
        docstring; systemd-rfkill persists soft-blocks across reboots.

        WHY THE ``radio-guard-exempt`` MARKER BELOW IS THERE, AND WHY IT IS NOT
        A LOOSENING OF THAT GUARD.  ``tests/deploy/test_no_radio_disable_in_project.py``
        (BL-025, the 07-03 dead-capture outage) refuses any shipped radio
        disable, and it is right to: a radio left dark IS that outage.  This is
        the one case AC1 explicitly requires -- "the BT-stack-wedge reset (power
        off/on + longer scan) that was needed 2026-08-07" -- and it differs from
        the failure the guard was written for on both axes that matter:

        * **Not persistent.**  This is a runtime D-Bus property, not an rfkill
          soft-block, so it cannot survive into the next boot the way BL-025's
          did.  A reboot clears it even if this code is wrong.
        * **Not one-way.**  The off is paired with an on two lines down AND with
          :meth:`_ensureRadioPowered` in the caller's ``finally``, which VERIFIES
          the adapter came back rather than assuming it.  Every early return in
          :meth:`_runBoundedRePair` sits between the two.

        That second claim is the load-bearing one, so it is asserted rather than
        promised: ``test_selfHeal_notDiscoverable_stillRestoresRadioAndCapture``
        and ``test_selfHeal_pairScriptFails_radioIsPoweredBackOn`` drive the two
        early-return paths and assert the adapter ends POWERED.  If a future
        edit strands the radio, those go red -- the exemption silences the
        static guard, not the behaviour it protects.
        """
        logger.info(
            "%s | cycling the adapter (power off -> on) to clear a wedged stack",
            BOND_SELF_HEAL_LOG_PREFIX,
        )
        self._bluetoothctl(['power', 'off'])  # radio-guard-exempt: AC1 reset, restored in finally
        self._sleep(self._settleSeconds)
        self._bluetoothctl(['power', 'on'])
        # bluez re-registers the controller on the D-Bus after a power-on;
        # scanning into that window returns "No default controller available",
        # which reads as "dongle absent" and would bail at the discovery gate.
        self._sleep(self._settleSeconds)

    def _isDiscoverable(self) -> bool:
        """One scan, then ask whether the dongle actually advertised.

        Atlas refinement 4: exactly one scan.  A retry loop against a dongle
        that is not powered is the radio-hammering the refinement forbids, and
        it converts a two-second "it isn't there" into minutes of silence.
        """
        self._bluetoothctl(['scan', 'on'], timeoutSeconds=self._scanSeconds)
        result = self._bluetoothctl(['info', self.macAddress])
        if result is None:
            return False
        return parseInRange(result.stdout or '')

    def _runPairScript(self) -> bool:
        """Run the existing re-pair path.  Returns its success, not the bond's.

        The caller re-reads the bond afterwards regardless: an exit code
        describes the COMMAND, the flags describe the RESULT.
        """
        logger.info(
            "%s | running %s for %s",
            BOND_SELF_HEAL_LOG_PREFIX, self.pairScriptPath, self.macAddress,
        )
        result = self._run(
            [self.pairScriptPath, self.macAddress],
            timeout=PAIR_SCRIPT_TIMEOUT_SECONDS,
        )
        return result is not None and result.returncode == 0

    def _runVerifySnapshot(self) -> None:
        """Put ``verify_bt_pair.sh``'s snapshot in the journal (AC1).

        SNAPSHOT, NOT VERDICT -- and the distinction is load-bearing.  That
        script reports an unset ``Bonded`` flag as ``[INFO]`` rather than
        ``[FAIL]`` ("some BT stacks only set Bonded on first connection"), so
        it exits 0 over exactly the not-bonded state this module exists to fix.
        Using its exit code as the gate would let the healer declare success on
        a bond that cannot survive a reboot -- the original defect, wearing a
        green check mark.  The caller re-reads the bond flags for the verdict.

        What the script gives that the flags cannot: the rfcomm bind and
        rfcomm-bind.service state.  A durable bond with no binding is still a
        dead capture path, and that is worth having in the same journal entry.
        """
        result = self._run(
            [self.verifyScriptPath, self.macAddress],
            timeout=VERIFY_SCRIPT_TIMEOUT_SECONDS,
        )
        if result is None:
            logger.info(
                "%s | %s could not be run -- snapshot unavailable (the bond "
                "verdict below does not depend on it)",
                BOND_SELF_HEAL_LOG_PREFIX, self.verifyScriptPath,
            )
            return
        logger.info(
            "%s | verify_bt_pair snapshot (rc=%d, ADVISORY -- not the verdict):\n%s",
            BOND_SELF_HEAL_LOG_PREFIX,
            result.returncode,
            (result.stdout or result.stderr or '').strip(),
        )

    def _ensureRadioPowered(self) -> None:
        """Never leave the adapter dark.  Verified, not assumed."""
        if self.readAdapterPowered() is True:
            return
        self._bluetoothctl(['power', 'on'])
        if self.readAdapterPowered() is True:
            return
        logger.error(
            "%s | the adapter is NOT powered after the self-heal -- capture "
            "cannot work until it is. Try: bluetoothctl power on; "
            "systemctl restart bluetooth",
            BOND_SELF_HEAL_LOG_PREFIX,
        )

    # --------------------------------------------------------------------------
    # CLI plumbing
    # --------------------------------------------------------------------------

    def _isUnitActive(self, unit: str) -> bool:
        result = self._run([SYSTEMCTL_CMD, 'is-active', unit])
        return result is not None and result.returncode == 0

    def _controlUnit(self, verb: str, unit: str) -> bool:
        result = self._run([SYSTEMCTL_CMD, verb, unit])
        ok = result is not None and result.returncode == 0
        logger.info(
            "%s | systemctl %s %s -> %s",
            BOND_SELF_HEAL_LOG_PREFIX, verb, unit, 'ok' if ok else 'FAILED',
        )
        return ok

    def _bluetoothctl(
        self, args: list[str], timeoutSeconds: int | None = None
    ) -> subprocess.CompletedProcess[str] | None:
        timeout = (
            timeoutSeconds if timeoutSeconds is not None
            else bluetooth_helper.BLUETOOTHCTL_TIMEOUT_S
        )
        return self._run(
            [bluetooth_helper.BLUETOOTHCTL_CMD, '--timeout', str(timeout), *args]
        )

    def _run(
        self, cmd: list[str], timeout: float | None = None
    ) -> subprocess.CompletedProcess[str] | None:
        """Run one command; None on any transport failure.

        A missing binary, a wedged D-Bus and a killed child all surface as
        None so the decision logic above has exactly one "could not read"
        value to reason about instead of three exception types.
        """
        try:
            if timeout is not None:
                return self._runner(cmd, timeout=timeout)
            return self._runner(cmd)
        except Exception as exc:  # noqa: BLE001 -- self-heal must never raise
            logger.debug("%s | %s failed: %s", BOND_SELF_HEAL_LOG_PREFIX, cmd[0], exc)
            return None

    def _finish(
        self,
        outcome: SelfHealOutcome,
        verdict: BondVerdict,
        state: BondState,
        detail: str,
        operatorAction: str | None = None,
    ) -> SelfHealReport:
        """Build, log and return the report."""
        report = SelfHealReport(
            outcome=outcome,
            verdict=verdict,
            macAddress=self.macAddress,
            bondState=state,
            attemptsUsed=self._attemptsUsed,
            detail=detail,
            operatorAction=operatorAction,
        )
        line = (
            f"{BOND_SELF_HEAL_LOG_PREFIX} | outcome={outcome.value} "
            f"| verdict={verdict.value} | mac={self.macAddress} "
            f"| attempts={self._attemptsUsed}/{self._maxAttempts} "
            f"| paired={state.paired} bonded={state.bonded} trusted={state.trusted} "
            f"| {detail}"
        )
        if report.ok:
            logger.info(line)
        else:
            logger.warning("%s | ACTION: %s", line, operatorAction)
        return report


def _repoScript(relPath: str) -> Path:
    """Absolute path of a repo-root-relative script in this checkout."""
    return Path(__file__).resolve().parents[3] / relPath


# ================================================================================
# The request seam -- used by the RUNNING logger, which cannot heal itself
# ================================================================================


class _RequestBudget:
    """Process-lifetime cap on self-heal requests (Atlas refinement 3)."""

    def __init__(self) -> None:
        self._used = 0

    def allow(self) -> bool:
        return self._used < SELF_HEAL_MAX_REQUESTS_PER_BOOT

    def consume(self) -> None:
        self._used += 1

    def reset(self) -> None:
        self._used = 0


_requestBudget = _RequestBudget()


def resetSelfHealRequestBudget() -> None:
    """Reset the once-per-process request cap (tests only)."""
    _requestBudget.reset()


def requestBondSelfHeal(
    macAddress: str,
    *,
    subprocessRunner: SubprocessRunner | None = None,
    unit: str = SELF_HEAL_UNIT,
) -> bool:
    """Ask systemd to run the self-heal.  Bounded, non-raising.

    Args:
        macAddress: The dongle MAC (for the journal line only -- the unit reads
            the canonical ``$OBD_BT_MAC`` itself).
        subprocessRunner: CLI seam.
        unit: The self-heal unit.

    Returns:
        True when the unit was actually started, False otherwise.

    ``--no-block`` is load-bearing.  The unit's first act is to STOP
    ``eclipse-obd`` -- i.e. this caller.  Blocking on a job that kills the
    blocker is a deadlock; ``--no-block`` queues the job and returns, and
    systemd restarts capture when the heal finishes.

    The budget is consumed only on an actual start, so one transient systemctl
    failure cannot disable self-heal for the rest of the boot.
    """
    if not _requestBudget.allow():
        logger.debug(
            "%s | request suppressed -- already requested this boot",
            BOND_SELF_HEAL_LOG_PREFIX,
        )
        return False

    runner = subprocessRunner or bluetooth_helper.defaultSubprocessRunner
    cmd = [SYSTEMCTL_CMD, 'start', '--no-block', unit]
    try:
        result = runner(cmd)
    except Exception as exc:  # noqa: BLE001 -- runs inside the capture path
        logger.warning(
            "%s | could not request %s (%s) -- the bond for %s is still broken",
            BOND_SELF_HEAL_LOG_PREFIX, unit, exc, macAddress,
        )
        return False

    if result.returncode != 0:
        logger.warning(
            "%s | %s refused to start (rc=%d): %s",
            BOND_SELF_HEAL_LOG_PREFIX, unit, result.returncode,
            (result.stderr or result.stdout or '').strip(),
        )
        return False

    _requestBudget.consume()
    logger.warning(
        "%s | bond for %s is not durable -- requested %s. Capture will be "
        "STOPPED for the re-pair and restarted by systemd; this is deliberate "
        "(never pair while the logger holds the port).",
        BOND_SELF_HEAL_LOG_PREFIX, macAddress, unit,
    )
    return True


# ================================================================================
# CLI entry point (ExecStart of eclipse-bond-selfheal.service)
# ================================================================================


def main(argv: list[str] | None = None) -> int:
    """Run one self-heal.

    MAC resolution order: argv[0], then ``$OBD_BT_MAC`` (the repo-canonical
    SSOT written to ``/etc/default/obdlink`` by ``deploy/reassert-obd-mac.sh``).

    Returns:
        0 when the bond is usable, 1 when a human owes something, 2 on usage
        error -- the same contract as ``scripts/verify_bt_pair.sh``.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    mac = args[0] if args else os.environ.get('OBD_BT_MAC', '').strip()

    if not mac or not bluetooth_helper.isMacAddress(mac):
        sys.stderr.write(
            "bond_self_heal: a Bluetooth MAC is required "
            "(argv[1] or $OBD_BT_MAC); got: "
            f"{mac!r}\n"
        )
        return 2

    logging.basicConfig(
        level=logging.INFO, format='%(levelname)s %(message)s', stream=sys.stdout
    )
    report = BondSelfHealer(mac).selfHeal()

    sys.stdout.write(f"{BOND_SELF_HEAL_LOG_PREFIX}: {report.outcome.value}\n")
    sys.stdout.write(f"  {report.detail}\n")
    if report.operatorAction:
        sys.stdout.write(f"  ACTION: {report.operatorAction}\n")
    return 0 if report.ok else 1


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
