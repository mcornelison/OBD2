################################################################################
# File Name: test_arm_decision_logging.py
# Purpose/Description: US-566 gate -- eclipse-powerwatch must state its arm
#                      decision. Covers the three halves of the fix: the
#                      decision line itself (unconditional, both branches,
#                      above lastResort's WARNING floor, carrying its
#                      evidence), the disarmed hold that re-states its cause
#                      instead of falling silent, and the structural pins that
#                      main() configures logging BEFORE the decision and never
#                      re-opens a bare block-forever on the disarmed branch.
# Author: (Ralph / Agent 1)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-08-21    | US-566  | Initial -- Sprint 75 / V0.29.30 arm-decision
#                           observability gate.
# ================================================================================
################################################################################
"""US-566: the powerwatch arm decision must never be silent."""
from __future__ import annotations

import inspect
import logging

import pytest

from src.pi.power.power_watch import __main__ as m

LOGGER_NAME = m.logger.name

# The facts the pre-US-566 ERROR message carried. US-566 rewrites that message,
# so these are MOVED pins, not new ones: the rewrite must not quietly drop the
# remediation the only diagnostic line on this path used to carry.
PRE_US566_ERROR_FACTS = (
    "REFUSING to arm",
    "OBD collector",
    "NOTHING will be powered off",
    "pi.powerWatch.pldGpioPin",
    "pldPowerPresentHigh",
    "redeploy",
)


def _decisionRecords(caplog):
    return [r for r in caplog.records if r.name == LOGGER_NAME]


# --------------------------------------------------------------------------
# The decision line -- unconditional, both branches
# --------------------------------------------------------------------------
@pytest.mark.parametrize("armed", [True, False])
def test_emitArmDecision_isNeverSilentOnEitherBranch(caplog, armed):
    """
    Given: either disposition of the startup arm self-check
    When: the service reports its arm decision
    Then: exactly one record is emitted -- there is no input that logs nothing

    This is the story in one assertion. The defect was not a missing branch;
    it was that the taken branch produced nothing observable.
    """
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    m.emitArmDecision(
        armed=armed, pldGpioPin=6, pldAvailable=True, readsPowerPresent=armed
    )

    assert len(_decisionRecords(caplog)) == 1


@pytest.mark.parametrize("armed", [True, False])
def test_emitArmDecision_clearsTheLastResortWarningFloor(caplog, armed):
    """
    Given: a process with NO logging configuration installed
    When: the arm decision is emitted
    Then: its level is >= WARNING, so logging.lastResort still prints it

    The measured root cause: with no root handler Python falls back to
    logging.lastResort, whose level is WARNING. The arm-success line was INFO
    and was therefore discarded on every one of 8 observed service starts. A
    safety fact must not sit on a tier that a configuration change can silence,
    so this pins the FLOOR rather than the exact level -- defence in depth
    behind the setupLogging() call, not instead of it.
    """
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    m.emitArmDecision(
        armed=armed, pldGpioPin=6, pldAvailable=True, readsPowerPresent=armed
    )

    record = _decisionRecords(caplog)[0]
    assert record.levelno >= logging.WARNING, (
        f"arm decision emitted at {record.levelname}; lastResort drops "
        "anything below WARNING and that is exactly how this fact went missing"
    )


def test_emitArmDecision_armedIsWarning_notArmedIsError(caplog):
    """
    Given: each disposition in turn
    When: the arm decision is emitted
    Then: armed logs WARNING, not-armed logs ERROR

    Both directions pinned. A refusal is more severe than a routine start, and
    collapsing them to one level would cost the operator the distinction while
    still passing the floor test above.
    """
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    m.emitArmDecision(
        armed=True, pldGpioPin=6, pldAvailable=True, readsPowerPresent=True
    )
    m.emitArmDecision(
        armed=False, pldGpioPin=6, pldAvailable=False, readsPowerPresent=False
    )

    armedRec, notArmedRec = _decisionRecords(caplog)
    assert armedRec.levelno == logging.WARNING
    assert notArmedRec.levelno == logging.ERROR


@pytest.mark.parametrize("armed", [True, False])
def test_emitArmDecision_bothBranchesShareOneGreppablePrefix(caplog, armed):
    """
    Given: either disposition
    When: the arm decision is emitted
    Then: the line carries ARM_DECISION_PREFIX

    The deliverable is that ONE grep answers "did safety arm?":
      journalctl -u eclipse-powerwatch.service --grep='ARM DECISION'
    If only one branch carried the token, a silent journal would still be
    ambiguous -- which is the state this story exists to end.
    """
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    m.emitArmDecision(
        armed=armed, pldGpioPin=6, pldAvailable=True, readsPowerPresent=armed
    )

    assert m.ARM_DECISION_PREFIX in _decisionRecords(caplog)[0].getMessage()


def test_emitArmDecision_returnsTheExactLineItLogged(caplog):
    """
    Given: the not-armed branch
    When: the decision is emitted
    Then: the returned string is byte-identical to the record logged

    The disarmed hold re-states this string verbatim. Returning it is what
    keeps ONE formatting site -- the alternative is recomposing the message at
    the hold, which also means re-reading the hardware to do it.
    """
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    returned = m.emitArmDecision(
        armed=False, pldGpioPin=6, pldAvailable=False, readsPowerPresent=False
    )

    assert returned == _decisionRecords(caplog)[0].getMessage()


# --------------------------------------------------------------------------
# The message -- a verdict without its evidence cannot be diagnosed
# --------------------------------------------------------------------------
@pytest.mark.parametrize("armed", [True, False])
def test_buildArmDecisionMessage_carriesEvidenceNotJustAVerdict(armed):
    """
    Given: either disposition, with distinctive evidence values
    When: the message is composed
    Then: the pin, the line readability and the actual reading all appear

    "NOT-ARMED" alone routes nobody anywhere. The CIO's X1209 diagnosis needs
    to separate "wrong pin/polarity" from "line unreadable", and that is only
    possible if the line reports what was measured.
    """
    message = m.buildArmDecisionMessage(
        armed=armed,
        pldGpioPin=17,
        pldAvailable=False,
        readsPowerPresent=False,
    )

    assert "gpio=17" in message
    assert "pld.available=False" in message
    assert "reads-power-present=False" in message


def test_buildArmDecisionMessage_statesTheProtectionStateInPlainWords():
    """
    Given: each disposition
    When: the message is composed
    Then: it says whether safe-shutdown protection is ON or OFF

    The operator's question is not "did a self-check pass", it is "am I
    protected". Both must be answerable from the one line.
    """
    assert "protection is ON" in m.buildArmDecisionMessage(
        armed=True, pldGpioPin=6, pldAvailable=True, readsPowerPresent=True
    )
    assert "protection is OFF" in m.buildArmDecisionMessage(
        armed=False, pldGpioPin=6, pldAvailable=True, readsPowerPresent=False
    )


@pytest.mark.parametrize("fact", PRE_US566_ERROR_FACTS)
def test_buildArmDecisionMessage_notArmedKeepsEveryPreUs566Fact(fact):
    """
    Given: the not-armed branch
    When: the message is composed
    Then: every fact the pre-US-566 ERROR carried is still present

    A MOVED pin. US-566 rewrites the only diagnostic line on this path; the
    rewrite must be additive. Losing the remediation while adding a prefix
    would be a net regression that every other test here would still pass.
    """
    message = m.buildArmDecisionMessage(
        armed=False, pldGpioPin=6, pldAvailable=False, readsPowerPresent=False
    )

    assert fact in message


def test_buildArmDecisionMessage_armedDoesNotCarryRemediationText():
    """
    Given: the armed branch
    When: the message is composed
    Then: it does NOT tell the operator to fix the pin and redeploy

    The two branches share a formatting site, not their content. An ARMED line
    carrying "REFUSING to arm ... redeploy" would read as a failure on the
    happy path -- the inverse of the honest-instrument goal.
    """
    message = m.buildArmDecisionMessage(
        armed=True, pldGpioPin=6, pldAvailable=True, readsPowerPresent=True
    )

    assert "REFUSING to arm" not in message
    assert m.ARM_DECISION_NOT_ARMED not in message


# --------------------------------------------------------------------------
# The disarmed hold -- declining to arm is not a claim of wellness
# --------------------------------------------------------------------------
def test_runDisarmedHold_reStatesTheCauseUntilTheWaitEnds(caplog):
    """
    Given: a wait that times out three times, then returns True
    When: the disarmed hold runs
    Then: the cause is re-stated exactly three times, each at ERROR

    Pre-US-566 this branch was `threading.Event().wait()` -- one announcement,
    then permanent silence behind a unit that `systemctl is-active` still
    reports as active. A disarmed service must keep declaring itself.
    """
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    calls = []

    def waitFn(timeoutSec):
        calls.append(timeoutSec)
        return len(calls) > 3

    m.runDisarmedHold(message="NOT-ARMED because reasons", waitFn=waitFn)

    records = _decisionRecords(caplog)
    assert len(records) == 3
    assert all(r.levelno == logging.ERROR for r in records)
    assert all("STILL NOT-ARMED" in r.getMessage() for r in records)


def test_runDisarmedHold_reStatesTheOriginalCauseVerbatim(caplog):
    """
    Given: a decision line carrying its evidence
    When: the hold re-states it
    Then: the full original cause rides along, not a bare "still disarmed"

    A re-statement that drops the cause is a heartbeat, not an instrument --
    the operator reading the journal a week later would see that something is
    wrong and still not know what.
    """
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    original = m.buildArmDecisionMessage(
        armed=False, pldGpioPin=6, pldAvailable=False, readsPowerPresent=False
    )

    m.runDisarmedHold(
        message=original, waitFn=lambda _s: len(_decisionRecords(caplog)) >= 1
    )

    assert original in _decisionRecords(caplog)[0].getMessage()


def test_runDisarmedHold_usesTheDeclaredRestateInterval():
    """
    Given: no explicit interval
    When: the disarmed hold runs
    Then: it waits DISARMED_RESTATE_SEC between re-statements

    Pins the constant to the call site. A default that drifted to 0 would spin
    the CPU on a shutdown-critical box; one that drifted large would restore
    the silence.
    """
    seen = []

    m.runDisarmedHold(
        message="x", waitFn=lambda s: (seen.append(s), True)[1]
    )

    assert seen == [m.DISARMED_RESTATE_SEC]
    assert m.DISARMED_RESTATE_SEC > 0


def test_runDisarmedHold_returnsZeroSoTheServiceExitsCleanly():
    """
    Given: a wait that ends immediately
    When: the disarmed hold returns
    Then: the exit code is 0

    Refusing to arm is a deliberate safe state, not a crash. A non-zero exit
    under Restart=always would put the unit into a restart loop.
    """
    assert m.runDisarmedHold(message="x", waitFn=lambda _s: True) == 0


# --------------------------------------------------------------------------
# Structural pins -- shape that behaviour alone cannot hold
# --------------------------------------------------------------------------
def test_main_configuresLoggingBeforeTheArmDecision():
    """
    Given: main()'s source
    When: the order of setupLogging and the arm self-check is compared
    Then: logging is configured first

    THE root cause, and behaviour cannot pin it here: main() does real
    hardware wiring, and a run that configured logging afterwards would still
    emit the decision (it is above the lastResort floor) while silently
    dropping every INFO line before that point -- including "powerwatch
    service up". Ordering is the deliverable, so ordering is what is asserted.
    """
    source = inspect.getsource(m.main)

    setupAt = source.find("setupLogging(")
    armCheckAt = source.find("startupArmCheck()")

    assert setupAt != -1, "main() no longer configures logging at all"
    assert armCheckAt != -1
    assert setupAt < armCheckAt


def test_main_doesNotPassALogFileToSetupLogging():
    """
    Given: main()'s source
    When: the setupLogging call is inspected
    Then: no logFile argument is passed

    Deliberate: this shutdown-critical service must not open a second writer
    on the OBD app's log file. Its stdout is already the journal.
    """
    source = inspect.getsource(m.main)
    call = source[source.find("setupLogging(") :]
    call = call[: call.find(")") + 1]

    assert "logFile" not in call


def test_main_holdsDisarmedViaTheReStatingHoldNotABareWait():
    """
    Given: main()'s source
    When: the disarmed branch is inspected
    Then: it delegates to runDisarmedHold

    Guards the regression that reads as a simplification: swapping the hold
    back for `threading.Event().wait()` restores the silent-but-active service
    and every behavioural test above still passes, because none of them call
    main().
    """
    source = inspect.getsource(m.main)

    assert "runDisarmedHold(" in source


def test_armDecisionIsEmittedUnconditionally_notOnlyOnFailure():
    """
    Given: main()'s source
    When: the arm-decision emit is located
    Then: it sits OUTSIDE the `if not armed:` block

    The pre-US-566 shape logged only inside the failure branch, so a healthy
    start said nothing and silence was ambiguous. Asserting the emit precedes
    the branch is what makes "unconditional" checkable.
    """
    source = inspect.getsource(m.main)

    emitAt = source.find("emitArmDecision(")
    branchAt = source.find("if not armed:")

    assert emitAt != -1 and branchAt != -1
    assert emitAt < branchAt
