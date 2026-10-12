################################################################################
# File Name: test_obdctl.py
# Purpose/Description: US-492 [F-122] tests for `obdctl` -- the on-Pi operator
#   CLI that stops/starts/restarts/kills/statuses the OBD services.
#
#   The CLI is a MAINTENANCE tool run by a human on a car computer, so the tests
#   are weighted toward the ways it could hurt: it must never take the
#   safe-shutdown guard down without an explicit yes (D-7 / F-7), never turn a
#   `stop` into a `kill`, never claim a state it did not read back, and never
#   default a bare invocation to anything destructive. `systemctl` is injected,
#   so nothing here touches a real unit.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-27    | Ralph (Rex)  | Initial implementation (US-492 obdctl).
# ================================================================================
################################################################################

"""Tests for the US-492 obdctl operator CLI."""

from __future__ import annotations

import io
import subprocess

import pytest

from pi.ops import obdctl
from pi.ops import unit_manifest as manifest

GUARD = manifest.SAFE_SHUTDOWN_GUARD

# Verbs that CHANGE a unit. Used to assert a read-only path stayed read-only.
MUTATING = ("start", "stop", "restart", "kill")


class FakeSystemctl:
    """Records every argv it is handed and answers from a scripted state table.

    Attributes:
        states: unit -> (loadState, activeState). A unit absent from the table
            reads back as not-found, which is how a not-installed unit behaves.
        failing: units whose mutating actions exit non-zero.
    """

    def __init__(self, states=None, failing=(), afterStates=None):
        self.states = dict(states or {})
        self.failing = set(failing)
        self.afterStates = dict(afterStates or {})
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        bare = [a for a in argv if a != "sudo"]

        if bare[1] == "show":
            unit = bare[-1]
            load, active = self.states.get(unit, ("not-found", "inactive"))
            return subprocess.CompletedProcess(argv, 0, f"{load}\n{active}\n", "")

        unit = bare[-1]
        if unit in self.failing:
            return subprocess.CompletedProcess(argv, 1, "", "Job failed. See journalctl.")
        # A successful action moves the unit to its post-action state so the
        # after-read is genuinely a read, not an echo of what we asked for.
        if unit in self.afterStates:
            self.states[unit] = self.afterStates[unit]
        elif bare[1] in ("stop", "kill"):
            self.states[unit] = ("loaded", "inactive")
        elif bare[1] in ("start", "restart"):
            self.states[unit] = ("loaded", "active")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def mutatingCalls(self) -> list[list[str]]:
        return [c for c in self.calls if any(v in c for v in MUTATING)]

    def actedUnits(self) -> list[str]:
        return [c[-1] for c in self.mutatingCalls()]


def allActive() -> dict[str, tuple[str, str]]:
    """Every canonical unit loaded + active."""
    return {unit: ("loaded", "active") for unit in manifest.CANONICAL_UNITS}


def runCli(argv, *, runner=None, confirm=True, isRoot=False, sudo="/usr/bin/sudo"):
    # Default posture = how it actually runs on the Pi: the operator is
    # mcornelison, not root, and sudo is available.
    """Drive obdctl.main with everything injected. Returns (exitCode, output)."""
    runner = runner if runner is not None else FakeSystemctl(allActive())
    out = io.StringIO()
    code = obdctl.main(
        argv,
        runner=runner,
        confirmer=lambda prompt: confirm,
        stream=out,
        isRoot=isRoot,
        sudoPath=sudo,
    )
    return code, out.getvalue()


# ---------------------------------------------------------------------------
# Invocation surface (AC-1).
# ---------------------------------------------------------------------------


def test_main_bareInvocation_statusesEverythingAndChangesNothing():
    """
    Given: AC-1 -- a bare invocation must NEVER be a destructive default
    When: obdctl is run with no arguments
    Then: it reports all 8 units and issues no mutating systemctl call
    """
    fake = FakeSystemctl(allActive())

    code, out = runCli([], runner=fake)

    assert code == 0
    assert fake.mutatingCalls() == []
    for unit in manifest.CANONICAL_UNITS:
        assert unit in out


def test_main_help_documentsActionsTargetsAndUsage():
    """
    Given: AC-9 -- a one-line usage lives in --help
    When: --help is requested
    Then: every action, the `all` target and the safety note are printed, and
        nothing is executed
    """
    fake = FakeSystemctl(allActive())

    code, out = runCli(["--help"], runner=fake)

    assert code == 0
    assert fake.calls == []
    assert "obdctl" in out
    for action in ("status", "start", "stop", "restart", "kill"):
        assert action in out
    assert "all" in out
    assert "--dry-run" in out


def test_main_unknownTarget_exitsUsageErrorAndListsWhatIsAccepted():
    """
    Given: a typo'd target
    When: obdctl is run
    Then: it exits 1 (config/usage), names the bad token, prints the accepted
        tokens, and touches nothing
    """
    fake = FakeSystemctl(allActive())

    code, out = runCli(["restart", "dashbaord"], runner=fake)

    assert code == obdctl.EXIT_USAGE
    assert fake.calls == []
    assert "dashbaord" in out
    assert "dashboard" in out


def test_main_unknownAction_exitsUsageErrorAndTouchesNothing():
    """
    Given: an action word the tool does not implement
    When: obdctl is run
    Then: it exits 1 and runs nothing (never falls through to a default action)
    """
    fake = FakeSystemctl(allActive())

    code, out = runCli(["nuke", "all"], runner=fake)

    assert code == obdctl.EXIT_USAGE
    assert fake.calls == []
    assert "nuke" in out


def test_main_dryRun_readsStateButExecutesNoAction():
    """
    Given: AC-1 -- --dry-run
    When: a destructive action is dry-run
    Then: the intent is printed, state is still read (read-only is side-effect
        free and the operator wants to see what WOULD change), and no mutating
        call is issued
    """
    fake = FakeSystemctl(allActive())

    code, out = runCli(["--dry-run", "stop", "all", "--yes"], runner=fake)

    assert code == 0
    assert fake.mutatingCalls() == []
    assert "DRY-RUN" in out


# ---------------------------------------------------------------------------
# Dispatch + honest reporting (AC-1, AC-7).
# ---------------------------------------------------------------------------


def test_main_restartByAlias_actsOnTheResolvedUnitAndReportsBeforeAndAfter():
    """
    Given: AC-3 + AC-7 -- `obdctl restart obd`
    When: the alias is dispatched
    Then: systemctl restarts eclipse-obd.service, before->after states are both
        printed, and the exit code is 0
    """
    fake = FakeSystemctl({**allActive(), "eclipse-obd.service": ("loaded", "inactive")})

    code, out = runCli(["restart", "obd"], runner=fake)

    assert code == 0
    assert fake.actedUnits() == ["eclipse-obd.service"]
    assert ["sudo", "systemctl", "restart", "eclipse-obd.service"] in fake.calls
    assert "inactive" in out and "active" in out


def test_main_afterState_isReadBackNotAssumed():
    """
    Given: F-1 honest instrument -- the tool must not report the state it WANTED
    When: a restart succeeds but the unit reads back failed
    Then: the after-state shown is `failed` and the unit is reported FAIL
    """
    fake = FakeSystemctl(
        allActive(), afterStates={"eclipse-obd.service": ("loaded", "failed")}
    )

    code, out = runCli(["restart", "obd"], runner=fake)

    assert "failed" in out
    assert "FAIL" in out
    assert code == obdctl.EXIT_ACTION_FAILED


def test_main_failedAction_reportsFailAndExitsNonZero():
    """
    Given: AC-7 -- non-zero exit if any requested action failed
    When: systemctl exits non-zero
    Then: the unit line says FAIL, the stderr reason is surfaced, exit is 2
    """
    fake = FakeSystemctl(allActive(), failing={"eclipse-obd.service"})

    code, out = runCli(["restart", "obd"], runner=fake)

    assert code == obdctl.EXIT_ACTION_FAILED
    assert "FAIL" in out
    assert "journalctl" in out


def test_main_notInstalledUnit_isReportedHonestlyNotCrashed():
    """
    Given: AC-7 -- a not-installed unit is reported honestly, not an error-crash
    When: `status all` runs on a Pi missing one unit
    Then: that unit reads `not-installed`, the run still exits 0, and every
        other unit is still reported
    """
    states = allActive()
    del states["splash-grace.service"]
    fake = FakeSystemctl(states)

    code, out = runCli(["status", "all"], runner=fake)

    assert code == 0
    assert "not-installed" in out
    assert "eclipse-obd.service" in out


def test_main_statusAll_printsASummaryLineCoveringEveryUnit():
    """
    Given: AC-7 -- `all` prints a summary table
    When: status all runs
    Then: every canonical unit appears and the count line agrees with the
        manifest. Derived from the manifest rather than a literal: the contract
        is "the CLI counts what it printed", which a hardcoded number states
        only by coincidence and has to be re-edited every time a unit is added.
    """
    code, out = runCli(["status", "all"])

    assert code == 0
    for unit in manifest.CANONICAL_UNITS:
        assert unit in out
    assert f"{len(manifest.CANONICAL_UNITS)} unit" in out


def test_main_statusOfAnInactiveOneshot_saysInactiveIsNormal():
    """
    Given: rfcomm-bind is Type=oneshot -- `inactive` is its resting state
    When: status shows it inactive
    Then: the line is annotated, so a normal unit is not read as a broken one
        (F-1 honest instrument cuts both ways: no false alarms either)
    """
    states = allActive()
    states["rfcomm-bind.service"] = ("loaded", "inactive")
    fake = FakeSystemctl(states)

    code, out = runCli(["status", "rfcomm"], runner=fake)

    line = next(ln for ln in out.splitlines() if "rfcomm-bind.service" in ln)
    assert "normal" in line.lower()
    assert code == 0


def test_main_actionOnAnUninstalledUnitTargetedByName_failsHonestly():
    """
    Given: an operator explicitly names a unit this Pi does not have
    When: they try to restart it
    Then: nothing is executed and the run fails honestly -- the requested action
        did not happen, so it must not exit 0
    """
    states = allActive()
    del states["eclipse-dashboard.service"]
    fake = FakeSystemctl(states)

    code, out = runCli(["restart", "dashboard"], runner=fake)

    assert code == obdctl.EXIT_ACTION_FAILED
    assert fake.mutatingCalls() == []
    assert "not-installed" in out


def test_main_uninstalledUnitInsideAll_isSkippedWithoutFailingTheRun():
    """
    Given: AC-7 + conditionalOutcome 2 -- `all` on a Pi missing a unit
    When: stop all runs
    Then: the absent unit is reported and skipped, the rest still act, and the
        run does not fail on account of a unit that was never installed
    """
    states = allActive()
    del states["splash-grace.service"]
    fake = FakeSystemctl(states)

    code, out = runCli(["stop", "all", "--yes"], runner=fake)

    assert code == 0
    assert "splash-grace.service" not in fake.actedUnits()
    assert "eclipse-obd.service" in fake.actedUnits()


# ---------------------------------------------------------------------------
# Ordering (AC-6).
# ---------------------------------------------------------------------------


def test_main_stopAll_actsInReverseDependencyOrder():
    """
    Given: AC-6 -- stop kiosk/splash first, states-http next, core last
    When: stop all runs
    Then: the acted order is exactly the manifest's stop order
    """
    fake = FakeSystemctl(allActive())

    code, _ = runCli(["stop", "all", "--yes"], runner=fake)

    assert code == 0
    assert fake.actedUnits() == list(manifest.STOP_ORDER)


def test_main_startAll_actsInDependencyOrder():
    """
    Given: AC-6 -- start states-http before the surfaces that consume it
    When: start all runs
    Then: the acted order is exactly the manifest's start order
    """
    fake = FakeSystemctl(allActive())

    code, _ = runCli(["start", "all"], runner=fake)

    assert code == 0
    assert fake.actedUnits() == list(manifest.START_ORDER)


# ---------------------------------------------------------------------------
# SAFETY -- the safe-shutdown guard (AC-4).
# ---------------------------------------------------------------------------


def test_main_stopPowerwatchWithoutForce_requiresConfirmAndWarnsLoudly():
    """
    Given: AC-4 / D-7 -- powerwatch is the safe-shutdown guard
    When: it is stopped with no --force
    Then: the operator is asked, the warning names the consequence, and the
        recovery command is printed
    """
    prompts: list[str] = []
    fake = FakeSystemctl(allActive())
    out = io.StringIO()

    def confirmer(prompt):
        prompts.append(prompt)
        return True

    code = obdctl.main(
        ["stop", "powerwatch"],
        runner=fake,
        confirmer=confirmer,
        stream=out,
        isRoot=True,
        sudoPath="/usr/bin/sudo",
    )

    assert prompts, "stopping the safe-shutdown guard must ask"
    assert code == 0
    text = out.getvalue()
    assert "SAFE-SHUTDOWN GUARD" in text
    assert "obdctl start powerwatch" in text


def test_main_stopPowerwatchDeclined_leavesTheGuardRunning():
    """
    Given: the operator answers no to the guard prompt
    When: the run finishes
    Then: NO stop was issued, the unit is reported SKIPPED, and the exit is
        non-zero because the requested action did not happen
    """
    fake = FakeSystemctl(allActive())
    out = io.StringIO()

    code = obdctl.main(
        ["stop", "powerwatch"],
        runner=fake,
        confirmer=lambda prompt: False,
        stream=out,
        isRoot=True,
        sudoPath="/usr/bin/sudo",
    )

    assert fake.mutatingCalls() == []
    assert code == obdctl.EXIT_ACTION_FAILED
    assert "SKIPPED" in out.getvalue()


def test_main_stopAllDeclined_stopsEverythingExceptTheGuard():
    """
    Given: AC-4 -- declining the guard prompt during `all`
    When: stop all runs and the confirm is refused
    Then: every other unit is still stopped (the operator asked for
        maintenance) but the guard stays up -- the cardinal rule wins over
        completeness, and the exit code says not everything happened
    """
    fake = FakeSystemctl(allActive())
    out = io.StringIO()

    code = obdctl.main(
        ["stop", "all"],
        runner=fake,
        confirmer=lambda prompt: False,
        stream=out,
        isRoot=True,
        sudoPath="/usr/bin/sudo",
    )

    acted = fake.actedUnits()
    assert GUARD not in acted
    assert "eclipse-obd.service" in acted
    assert len(acted) == len(manifest.CANONICAL_UNITS) - 1
    assert code == obdctl.EXIT_ACTION_FAILED


def test_main_stopPowerwatchWithForce_skipsThePromptAndStops():
    """
    Given: AC-4 -- --force/--yes is the scriptable escape hatch
    When: the guard is stopped with --yes
    Then: no prompt is raised and the stop is executed
    """
    prompts: list[str] = []
    fake = FakeSystemctl(allActive())
    out = io.StringIO()

    code = obdctl.main(
        ["stop", "powerwatch", "--yes"],
        runner=fake,
        confirmer=lambda prompt: prompts.append(prompt) or True,
        stream=out,
        isRoot=True,
        sudoPath="/usr/bin/sudo",
    )

    assert prompts == []
    assert fake.actedUnits() == [GUARD]
    assert code == 0


def test_main_restartPowerwatch_isUnrestricted():
    """
    Given: AC-4 -- restart/status of powerwatch is unrestricted (a restart ends
        with the guard RUNNING, so it does not disable shutdown protection)
    When: powerwatch is restarted
    Then: no prompt, and it runs
    """
    prompts: list[str] = []
    fake = FakeSystemctl(allActive())
    out = io.StringIO()

    code = obdctl.main(
        ["restart", "powerwatch"],
        runner=fake,
        confirmer=lambda prompt: prompts.append(prompt) or True,
        stream=out,
        isRoot=True,
        sudoPath="/usr/bin/sudo",
    )

    assert prompts == []
    assert code == 0
    assert fake.actedUnits() == [GUARD]


def test_main_statusWithGuardDown_shoutsAboutItAndSaysHowToFixIt():
    """
    Given: AC-4 -- "make it easy to SEE powerwatch is down + to bring it back"
    When: status runs while the guard is inactive
    Then: a loud line flags it and prints the exact recovery command
    """
    states = allActive()
    states[GUARD] = ("loaded", "inactive")
    fake = FakeSystemctl(states)

    code, out = runCli(["status", "all"], runner=fake)

    assert "SAFE-SHUTDOWN GUARD" in out
    assert "obdctl start powerwatch" in out
    assert code == 0


def test_main_statusWithUnreadableGuardState_doesNotClaimItIsDown():
    """
    Given: systemctl cannot be read at all, so the guard's state is `unknown`
    When: status runs
    Then: the banner does NOT assert the guard is down. `unknown` means "I could
        not read it", and announcing a confident DOWN on a guard that may be
        running perfectly is the same class of lie as announcing a confident UP
        on one that is dead (F-1). It says it could not read it instead.
    """

    def broken(argv, **kwargs):
        raise OSError("systemctl missing")

    out = io.StringIO()
    code = obdctl.main(
        ["status", "all"],
        runner=broken,
        confirmer=lambda prompt: True,
        stream=out,
        isRoot=False,
        sudoPath=None,
    )

    text = out.getvalue()
    assert "GUARD IS DOWN" not in text
    assert "could not" in text.lower()
    assert code == 0


def test_main_statusWithGuardUp_doesNotCryWolf():
    """
    Given: a healthy Pi
    When: status runs with the guard active
    Then: no guard-down alarm is printed (an alarm that is always on is noise)
    """
    code, out = runCli(["status", "all"])

    assert "GUARD IS DOWN" not in out
    assert code == 0


# ---------------------------------------------------------------------------
# SAFETY -- kill is forceful (AC-5).
# ---------------------------------------------------------------------------


def test_main_kill_sendsSigkillAndRequiresExplicitConfirm():
    """
    Given: AC-5 -- kill requires explicit intent
    When: `kill dashboard` runs without --yes
    Then: the operator is asked, the warning explains uncleaned resources and
        points at `stop` first, and SIGKILL is what actually gets sent
    """
    prompts: list[str] = []
    fake = FakeSystemctl(allActive())
    out = io.StringIO()

    code = obdctl.main(
        ["kill", "dashboard"],
        runner=fake,
        confirmer=lambda prompt: prompts.append(prompt) or True,
        stream=out,
        isRoot=False,
        sudoPath="/usr/bin/sudo",
    )

    assert prompts, "SIGKILL must be confirmed"
    assert code == 0
    assert [
        "sudo",
        "systemctl",
        "kill",
        "-s",
        "SIGKILL",
        "eclipse-dashboard.service",
    ] in fake.calls
    text = out.getvalue()
    assert "SIGKILL" in text
    assert "stop" in text.lower()
    assert "inactive" in text


def test_main_stopThatFails_neverEscalatesToKill():
    """
    Given: AC-5 -- kill is "never a fallback of stop"
    When: a stop fails
    Then: the tool reports the failure and issues NO kill; escalating for the
        operator would silently destroy the state they were trying to preserve
    """
    fake = FakeSystemctl(allActive(), failing={"eclipse-obd.service"})

    code, out = runCli(["stop", "obd"], runner=fake)

    assert code == obdctl.EXIT_ACTION_FAILED
    assert not any("kill" in call for call in fake.calls)
    assert "FAIL" in out


def test_main_killDeclined_doesNotKill():
    """
    Given: the operator answers no to the SIGKILL prompt
    When: the run finishes
    Then: nothing was killed and the exit says so
    """
    fake = FakeSystemctl(allActive())
    out = io.StringIO()

    code = obdctl.main(
        ["kill", "dashboard"],
        runner=fake,
        confirmer=lambda prompt: False,
        stream=out,
        isRoot=True,
        sudoPath="/usr/bin/sudo",
    )

    assert fake.mutatingCalls() == []
    assert code == obdctl.EXIT_ACTION_FAILED


# ---------------------------------------------------------------------------
# Privilege (AC-8).
# ---------------------------------------------------------------------------


def test_main_asRoot_doesNotPrefixSudo():
    """
    Given: obdctl already running as root
    When: a unit is restarted
    Then: systemctl is invoked directly
    """
    fake = FakeSystemctl(allActive())

    runCli(["restart", "obd"], runner=fake, isRoot=True, sudo=None)

    assert ["systemctl", "restart", "eclipse-obd.service"] in fake.calls


def test_main_unprivilegedWithoutSudo_saysSoInsteadOfFailingCryptically():
    """
    Given: AC-8 -- the tool must TELL the operator it lacks privilege
    When: it runs unprivileged on a box with no sudo
    Then: no systemctl mutation is attempted, the message names the problem,
        and the exit is non-zero
    """
    fake = FakeSystemctl(allActive())

    code, out = runCli(["restart", "obd"], runner=fake, isRoot=False, sudo=None)

    assert fake.mutatingCalls() == []
    assert "root" in out.lower() or "privilege" in out.lower()
    assert code != 0


def test_main_statusUnprivileged_stillWorks():
    """
    Given: reading state needs no privilege
    When: status runs unprivileged with no sudo
    Then: it reports normally and never mentions a privilege problem
    """
    fake = FakeSystemctl(allActive())

    code, out = runCli(["status", "all"], runner=fake, isRoot=False, sudo=None)

    assert code == 0
    assert "eclipse-obd.service" in out
    assert not any("sudo" in call for call in fake.calls)


def test_main_polkitDenial_isTranslatedIntoAPrivilegeMessage():
    """
    Given: AC-8 -- systemctl's auth failure is cryptic
    When: systemctl fails with an authentication error
    Then: the reported reason names privilege, not just the raw exit code
    """

    def denying(argv, **kwargs):
        if "show" in argv:
            return subprocess.CompletedProcess(argv, 0, "loaded\nactive\n", "")
        return subprocess.CompletedProcess(
            argv, 1, "", "Failed to restart: Access denied\nAuthentication is required"
        )

    out = io.StringIO()
    code = obdctl.main(
        ["restart", "obd"],
        runner=denying,
        confirmer=lambda prompt: True,
        stream=out,
        isRoot=False,
        sudoPath="/usr/bin/sudo",
    )

    assert code != 0
    assert "privilege" in out.getvalue().lower()


# ---------------------------------------------------------------------------
# Robustness.
# ---------------------------------------------------------------------------


def test_main_systemctlTimeout_isAnHonestFailureNotATraceback():
    """
    Given: a hung systemctl
    When: the runner raises
    Then: obdctl reports a failure and returns an exit code -- an operator tool
        that tracebacks on a stuck unit is useless at the exact moment it is
        needed
    """

    def hanging(argv, **kwargs):
        if "show" in argv:
            return subprocess.CompletedProcess(argv, 0, "loaded\nactive\n", "")
        raise subprocess.TimeoutExpired(argv, 15)

    out = io.StringIO()
    code = obdctl.main(
        ["restart", "obd"],
        runner=hanging,
        confirmer=lambda prompt: True,
        stream=out,
        isRoot=True,
        sudoPath=None,
    )

    assert code == obdctl.EXIT_ACTION_FAILED
    assert "FAIL" in out.getvalue()


def test_main_unreadableState_reportsUnknownRatherThanGuessing():
    """
    Given: `systemctl show` itself fails
    When: status runs
    Then: the state reads `unknown` -- never a confident wrong answer
    """

    def broken(argv, **kwargs):
        raise OSError("systemctl missing")

    out = io.StringIO()
    code = obdctl.main(
        ["status", "obd"],
        runner=broken,
        confirmer=lambda prompt: True,
        stream=out,
        isRoot=True,
        sudoPath=None,
    )

    assert "unknown" in out.getvalue()
    assert code == 0


@pytest.mark.parametrize("action", ["status", "start", "stop", "restart", "kill"])
def test_main_everyDocumentedAction_isDispatchable(action):
    """
    Given: AC-1 -- the five actions
    When: each is run against one unit with --yes
    Then: none is rejected as unknown
    """
    fake = FakeSystemctl(allActive())

    code, out = runCli([action, "obd", "--yes"], runner=fake)

    assert code == 0, out
