################################################################################
# File Name: test_deploy_pi.py
# Purpose/Description: pytest wrapper for deploy/deploy-pi.sh smoke test.
#                      Drives the bash test_deploy_pi.sh via subprocess so the
#                      flag-parsing + dry-run safety checks run automatically
#                      inside the existing test suite. The bash script remains
#                      the canonical, runnable-by-hand smoke test (per
#                      Sprint 10 US-176 acceptance criterion).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Rex          | Initial implementation (Sprint 10 US-176)
# 2026-05-21    | Rex (US-354) | Add static-content assertions for the
#               |              | restart-decoupled-from-unit-file-diff fix and
#               |              | the new PID-start-time verification step.
#               |              | Pins the V0.27.16 deploy bug shape (long-running
#               |              | service restart gated on $changed) so a future
#               |              | regression to the narrow-guard pattern trips
#               |              | RED here.
# ================================================================================
################################################################################

"""pytest wrapper around tests/deploy/test_deploy_pi.sh + static assertions.

The .sh script is the source of truth for flag-parsing / --dry-run safety — see
that file for the assertion catalog. The pytest cases below cover both:

* The .sh wrapper (smoke + --help + unknown-flag).
* Static-content assertions on deploy-pi.sh for US-354 (V0.27.16 dead-code-in-
  memory bug: long-running service restart was gated on unit-file diff, so
  Python-source-only deploys silently shipped dead code).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SMOKE_TEST = REPO_ROOT / "tests" / "deploy" / "test_deploy_pi.sh"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"


def _scriptText() -> str:
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _stepBody(text: str, stepName: str) -> str:
    """Return the body of a bash function `step_<stepName>() { ... }`.

    Used by the US-354 static assertions to scope a check to one routine —
    a global grep can't distinguish 'restart inside step_install_power_watch_unit'
    from 'restart inside step_restart_service'.
    """
    needle = f"{stepName}() {{"
    start = text.find(needle)
    assert start > -1, f"function {stepName} not found in deploy-pi.sh"
    # Match the closing brace at column 0 (matches the project's style of
    # one-line `}` at end of each step_ function).
    rest = text[start:]
    closeIdx = rest.find("\n}\n")
    assert closeIdx > -1, f"could not find closing brace for {stepName}"
    return rest[: closeIdx + 2]


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_smokeTestPasses():
    """The bash smoke test (test_deploy_pi.sh) must exit 0 on a clean tree.

    Forwards stdout to the pytest captured output so any assertion failure
    inside the .sh test is visible from `pytest -v`.
    """
    assert SMOKE_TEST.is_file(), f"Missing smoke test at {SMOKE_TEST}"
    assert DEPLOY_SCRIPT.is_file(), f"Missing script under test at {DEPLOY_SCRIPT}"
    result = subprocess.run(
        ["bash", str(SMOKE_TEST)],
        capture_output=True,
        text=True,
        # Generous timeout: the .sh test forks ~10 sub-bash invocations of
        # deploy-pi.sh, and a NAS-mounted repo (chi-nas-01 SMB) makes each
        # invocation noticeably slower than local-disk. 90s is comfortable
        # headroom for both local-disk runs (~5s) and NAS runs (~35-50s).
        timeout=90,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
    assert result.returncode == 0, (
        f"deploy-pi.sh smoke test failed (exit={result.returncode})"
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_helpFlagExitsCleanly():
    """`deploy-pi.sh --help` must exit 0 and print usage."""
    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "Usage: bash deploy/deploy-pi.sh" in result.stdout
    assert "--init" in result.stdout
    assert "--restart" in result.stdout
    assert "--dry-run" in result.stdout


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_unknownFlagRejected():
    """Unknown flags must exit 2 and name the offending arg."""
    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--nope"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "--nope" in result.stderr or "--nope" in result.stdout


# ----------------------------------------------------------------------------
# US-354: V0.27.16 dead-code-in-memory bug -- static-content assertions
#
# Argus's 2026-05-21 finding: V0.27.16 deploy wrote new files to disk and
# bumped .deploy-version but did NOT restart eclipse-powerwatch.service and
# did NOT run daemon-reload. The Pi ran V0.27.15 code in memory for 15 hours
# despite .deploy-version reporting V0.27.16. Atlas's diagnosis: the existing
# restart logic in step_install_power_watch_unit was gated by `$changed`,
# which is TRUE only when the unit FILE differs (cmp -s). The common deploy
# case -- only Python source changes -- left $changed=false and silently
# skipped the restart.
#
# The fix decouples the two concerns: daemon-reload remains gated on $changed
# (unit-file metadata reload is only useful when unit files change), but the
# restart of long-running services becomes UNCONDITIONAL on every default
# deploy. A PID-start-time verification step asserts both services actually
# restarted (ExecMainStartTimestamp after deploy start) before .deploy-version
# is bumped.
#
# These assertions pin the fix shape so a future refactor cannot re-gate the
# restart on a narrow predicate.
# ----------------------------------------------------------------------------


def test_us354_citedInScript():
    """The fix must cite US-354 in deploy-pi.sh so archaeology can trace it
    back to its acceptance criteria.
    """
    text = _scriptText()
    assert "US-354" in text, (
        "deploy-pi.sh must cite US-354 on the restart-decoupling fix "
        "(per Sprint 41 V0.27.17 provenance discipline)"
    )


def test_deployStartEpoch_capturedBeforeStepsRun():
    """The verification step needs a deploy-start timestamp to compare each
    service's ExecMainStartTimestamp against. Capture it BEFORE any step
    runs (so the comparison is unambiguous: any restart fired during the
    deploy yields a service-start later than deploy-start).
    """
    text = _scriptText()
    assert "DEPLOY_START_EPOCH" in text, (
        "deploy-pi.sh must capture DEPLOY_START_EPOCH (used by the PID "
        "verification step to detect services that never restarted)"
    )
    # The capture must precede the mode-dispatch block; we use the
    # `=== OBD2v2 Pi Deployment ===` banner as the boundary marker because
    # it's the first observable line at the start of the dispatch flow.
    captureIdx = text.find("DEPLOY_START_EPOCH=")
    dispatchIdx = text.find("=== OBD2v2 Pi Deployment ===")
    assert captureIdx > -1, "DEPLOY_START_EPOCH must be assigned somewhere"
    assert dispatchIdx > -1, "mode-dispatch banner anchor missing"
    assert captureIdx < dispatchIdx, (
        "DEPLOY_START_EPOCH must be captured BEFORE the dispatch banner -- "
        "if it's captured after a step runs, that step's restart timestamp "
        "would (correctly) be before DEPLOY_START_EPOCH, false-failing the "
        "verification"
    )


def test_powerWatchRestart_isUnconditional_notGatedByChangedFlag():
    """The core fix: `systemctl restart eclipse-powerwatch.service` inside
    step_install_power_watch_unit must NOT be inside the `if [ "$changed" =
    true ]` block. The whole point of US-354 is to fire the restart even
    when the unit file is byte-identical (Python-source-only deploys).
    """
    text = _scriptText()
    body = _stepBody(text, "step_install_power_watch_unit")
    lines = body.splitlines()
    restartLineIdxs = [
        i for i, line in enumerate(lines)
        if "systemctl restart" in line and "eclipse-powerwatch" in line
    ]
    assert restartLineIdxs, (
        "step_install_power_watch_unit must contain a "
        "`systemctl restart eclipse-powerwatch.service` line"
    )
    for idx in restartLineIdxs:
        nested_in_changed = False
        depth = 0
        for j in range(idx - 1, -1, -1):
            stripped = lines[j].strip()
            if stripped.startswith("fi"):
                depth += 1
            elif stripped.startswith("if "):
                if depth > 0:
                    depth -= 1
                    continue
                # The `step_install_*_unit` bodies live inside `remote "..."`
                # double-quoted heredocs, so `$changed` references appear
                # with backslashes in the .sh source (e.g. `\"\$changed\"`).
                # Match by substrings instead of a literal pattern.
                if "changed" in stripped and "= true" in stripped and " if " in (" " + stripped):
                    nested_in_changed = True
                break
        assert not nested_in_changed, (
            f"systemctl restart eclipse-powerwatch on line {idx + 1} of "
            f"step_install_power_watch_unit is gated by `$changed` -- per "
            f"US-354 the restart must fire UNCONDITIONALLY on every default "
            f"deploy (long-running service; Python-source rsync needs the "
            f"running process replaced even when the unit file is unchanged)"
        )


def test_powerWatchDaemonReload_remainsGatedByChanged():
    """daemon-reload SHOULD still be gated on $changed -- it's a no-op when
    the unit file hasn't changed (daemon-reload reloads systemd's in-memory
    unit metadata; if the file is byte-identical there's nothing new to
    load). The fix decouples the TWO concerns; this test pins that
    daemon-reload didn't accidentally get decoupled too.
    """
    text = _scriptText()
    body = _stepBody(text, "step_install_power_watch_unit")
    lines = body.splitlines()
    reloadLineIdxs = [
        i for i, line in enumerate(lines)
        if "systemctl daemon-reload" in line
    ]
    assert reloadLineIdxs, (
        "step_install_power_watch_unit must contain a daemon-reload line"
    )
    for idx in reloadLineIdxs:
        nested_in_changed = False
        depth = 0
        for j in range(idx - 1, -1, -1):
            stripped = lines[j].strip()
            if stripped.startswith("fi"):
                depth += 1
            elif stripped.startswith("if "):
                if depth > 0:
                    depth -= 1
                    continue
                # The `step_install_*_unit` bodies live inside `remote "..."`
                # double-quoted heredocs, so `$changed` references appear
                # with backslashes in the .sh source (e.g. `\"\$changed\"`).
                # Match by substrings instead of a literal pattern.
                if "changed" in stripped and "= true" in stripped and " if " in (" " + stripped):
                    nested_in_changed = True
                break
        assert nested_in_changed, (
            f"systemctl daemon-reload on line {idx + 1} of "
            f"step_install_power_watch_unit is NOT gated by `$changed` -- "
            f"daemon-reload is unit-file metadata reload (different signal "
            f"from process restart); ungating it would churn systemd on "
            f"every no-op deploy"
        )


def test_verifyServiceRestarts_stepExists():
    """A dedicated verification step must exist so its presence is
    observable in the deploy log and its absence trips RED here.
    """
    text = _scriptText()
    assert "step_verify_service_restarts" in text, (
        "deploy-pi.sh must define a step_verify_service_restarts function "
        "that asserts both eclipse-powerwatch + eclipse-obd PIDs started "
        "later than DEPLOY_START_EPOCH (US-354 acceptance criterion 2)"
    )


def test_verifyServiceRestarts_checksBothPowerwatchAndObd():
    """The verification must cover BOTH long-running services -- not just
    eclipse-powerwatch (the one Argus caught) but also eclipse-obd, so a
    future eclipse-obd regression to the same bug class is caught too.
    """
    text = _scriptText()
    body = _stepBody(text, "step_verify_service_restarts")
    assert "eclipse-powerwatch" in body, (
        "step_verify_service_restarts must verify eclipse-powerwatch.service"
    )
    assert "eclipse-obd" in body, (
        "step_verify_service_restarts must also verify eclipse-obd.service "
        "(same long-running shape -- same potential bug class)"
    )


def test_verifyServiceRestarts_comparesAgainstDeployStartEpoch():
    """The verification compares each service's start time against
    DEPLOY_START_EPOCH; if the start time is earlier (i.e. the service
    didn't restart during this deploy), the verification fails.
    """
    text = _scriptText()
    body = _stepBody(text, "step_verify_service_restarts")
    assert "DEPLOY_START_EPOCH" in body, (
        "step_verify_service_restarts must compare against DEPLOY_START_EPOCH"
    )
    # The systemd-side timestamp source. ExecMainStartTimestamp or
    # ActiveEnterTimestamp are both acceptable -- both reflect the post-
    # restart start time, and either parses with `date -d`.
    assert (
        "ExecMainStartTimestamp" in body
        or "ActiveEnterTimestamp" in body
    ), (
        "step_verify_service_restarts must query a systemd-side start "
        "timestamp (ExecMainStartTimestamp or ActiveEnterTimestamp)"
    )


def test_verifyServiceRestarts_failsDeployOnStaleStart():
    """If either service's start time is before DEPLOY_START_EPOCH, the
    deploy must abort (exit non-zero) -- not silently continue and bump
    .deploy-version on top of a dead-code-in-memory Pi.
    """
    text = _scriptText()
    body = _stepBody(text, "step_verify_service_restarts")
    # The simplest signal that the step aborts on failure: an `exit` with
    # a non-zero code somewhere in the body. Mirroring the existing
    # require_ssh / step_install_journald_persistent pattern (exit 4 / 7).
    hasExit = any(
        f"exit {n}" in body for n in range(1, 256)
    )
    assert hasExit, (
        "step_verify_service_restarts must `exit <non-zero>` when a "
        "service's start time is before DEPLOY_START_EPOCH -- "
        "silently continuing would bump .deploy-version on a Pi running "
        "dead code in memory (the very bug US-354 fixes)"
    )


def test_deployVersion_writtenAfterRestartVerification():
    """.deploy-version must be the LAST thing written -- if any of the
    restart / verification steps fail, .deploy-version stays at the prior
    version so subsequent inspection of the Pi correctly reports the OLD
    deploy. Writing it before verification would lie about what's running.
    """
    text = _scriptText()
    # Anchor on the executable body (post `set -e`) -- header comments
    # mention step names in plain text which would skew text.find().
    setEOffset = text.find("\nset -e")
    assert setEOffset > -1
    body = text[setEOffset:]
    verifyIdx = body.find("step_verify_service_restarts")
    writeIdx = body.find("step_write_deploy_version")
    assert verifyIdx > -1, "step_verify_service_restarts not called in body"
    assert writeIdx > -1, "step_write_deploy_version not called in body"
    # There may be the function definition AND a call site. Use the LAST
    # occurrence (the call) for both.
    verifyCallIdx = body.rfind("step_verify_service_restarts")
    writeCallIdx = body.rfind("step_write_deploy_version")
    assert writeCallIdx > verifyCallIdx, (
        ".deploy-version bump (step_write_deploy_version) must run AFTER "
        "the restart verification (step_verify_service_restarts) so a "
        "failed restart leaves the OLD .deploy-version in place "
        "(US-354 acceptance criterion 5)"
    )


def test_restartVerification_runsAfterPowerWatchAndObdRestarts():
    """The verification step must run after BOTH:
    - step_install_power_watch_unit (which restarts eclipse-powerwatch)
    - step_restart_service (which restarts eclipse-obd)
    Otherwise the verification queries a service that hasn't been
    restarted yet, false-failing on a healthy deploy.
    """
    text = _scriptText()
    setEOffset = text.find("\nset -e")
    body = text[setEOffset:]
    pwIdx = body.rfind("step_install_power_watch_unit")
    restartIdx = body.rfind("step_restart_service")
    verifyIdx = body.rfind("step_verify_service_restarts")
    assert pwIdx > -1, "step_install_power_watch_unit not called in body"
    assert restartIdx > -1, "step_restart_service not called in body"
    assert verifyIdx > -1, "step_verify_service_restarts not called in body"
    assert verifyIdx > pwIdx, (
        "step_verify_service_restarts must run AFTER step_install_power_watch_unit"
    )
    assert verifyIdx > restartIdx, (
        "step_verify_service_restarts must run AFTER step_restart_service"
    )


def test_dryRunMode_doesNotInvokeRealVerification():
    """The new verification step must be a no-op under --dry-run (the
    existing smoke test runs --dry-run from a workstation without SSH
    access to a real Pi; the step would hang or fail otherwise).
    """
    text = _scriptText()
    body = _stepBody(text, "step_verify_service_restarts")
    # Match the existing dry-run shape: every other step does an early
    # `if $DRY_RUN; then ... return 0; fi`.
    assert "$DRY_RUN" in body, (
        "step_verify_service_restarts must short-circuit under --dry-run "
        "(matches the existing dry-run idiom across every other step)"
    )


def test_dryRunSmokeTestStillPasses():
    """End-to-end sanity: the existing bash smoke test still passes after
    the US-354 edits (--dry-run, --help, flag parsing all stay offline-
    safe). Same harness as test_deployPiSh_smokeTestPasses above but
    grouped with the US-354 assertions so an inadvertent shell-syntax
    break trips RED in this section too.
    """
    if not _bashAvailable():
        pytest.skip("bash not available on PATH")
    assert SMOKE_TEST.is_file()
    result = subprocess.run(
        ["bash", str(SMOKE_TEST)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
    assert result.returncode == 0, (
        f"deploy-pi.sh smoke test failed post-US-354 edits (exit={result.returncode})"
    )


# ----------------------------------------------------------------------------
# US-389: single-instance matched-pair deploy invariant + stop-before-start
#
# F-107 Root 1 closure (Atlas C-5): the guard config flag
# (pi.runtime.singleInstanceGuard.enabled) and the systemd
# RuntimeDirectory=eclipse-obd are a MATCHED PAIR. The deploy gate must:
#   1. assert both halves are present BEFORE syncing/restarting (fail loudly
#      on the workstation, never reach the Pi with a broken pair); and
#   2. stop-before-start the orchestrator so the outgoing process releases the
#      single-instance pidfile before the incoming process acquires it
#      (release-then-acquire ordering -- the deploy-hygiene check architecture.md
#      §10.7.1 gates the guard's production-enable on).
# These static assertions pin the fix shape so a future refactor cannot silently
# drop the gate or revert to a bare `systemctl restart`.
# ----------------------------------------------------------------------------


def test_us389_citedInScript():
    """The matched-pair gate + stop-before-start must cite US-389 so archaeology
    can trace them back to their acceptance criteria.
    """
    text = _scriptText()
    assert "US-389" in text, "deploy-pi.sh must cite US-389 on the matched-pair gate"


def test_us389_matchedPairStep_exists():
    """A dedicated matched-pair assertion step must exist so its presence is
    observable in the deploy log and its absence trips RED here.
    """
    text = _scriptText()
    assert "step_assert_single_instance_matched_pair" in text, (
        "deploy-pi.sh must define a step_assert_single_instance_matched_pair "
        "function (US-389 AC#1 -- the deploy fails if the guard flag or "
        "RuntimeDirectory is missing)"
    )


def test_us389_matchedPairStep_checksBothHalves():
    """The gate must shell out to the deploy_invariants helper with BOTH the
    config (guard flag half) and the unit (RuntimeDirectory half).
    """
    text = _scriptText()
    body = _stepBody(text, "step_assert_single_instance_matched_pair")
    assert "deploy_invariants.py" in body, (
        "the gate must invoke scripts/deploy_invariants.py (the testable "
        "assertion logic)"
    )
    assert "check-pair" in body, "the gate must call the check-pair subcommand"
    assert "config.json" in body, "the gate must pass config.json (guard-flag half)"
    assert ".service" in body, "the gate must pass the unit (RuntimeDirectory half)"


def test_us389_matchedPairStep_failsDeployOnViolation():
    """A broken pair must abort the deploy (exit non-zero), not warn-and-continue.
    The presence of a real file is the only warn-and-skip path; an actual
    violation from a present pair must `exit`.
    """
    text = _scriptText()
    body = _stepBody(text, "step_assert_single_instance_matched_pair")
    hasExit = any(f"exit {n}" in body for n in range(1, 256))
    assert hasExit, (
        "step_assert_single_instance_matched_pair must `exit <non-zero>` when "
        "the matched-pair check fails -- a broken pair reaching the Pi "
        "crash-loops the non-root orchestrator (US-389 AC#1)"
    )


def test_us389_matchedPairStep_runsBeforeSyncTree():
    """The gate must run BEFORE sync_tree so a broken pair aborts on the
    workstation and never ships to the Pi.
    """
    text = _scriptText()
    setEOffset = text.find("\nset -e")
    body = text[setEOffset:]
    gateCallIdx = body.rfind("step_assert_single_instance_matched_pair")
    syncCallIdx = body.rfind("sync_tree")
    assert gateCallIdx > -1, "matched-pair gate not called in body"
    assert syncCallIdx > -1, "sync_tree not called in body"
    assert gateCallIdx < syncCallIdx, (
        "step_assert_single_instance_matched_pair must run BEFORE sync_tree "
        "(abort on the workstation, never ship a broken pair to the Pi)"
    )


def test_us389_restartService_stopsBeforeStart():
    """step_restart_service must stop-then-start (release-then-acquire), NOT a
    bare `systemctl restart` -- so the outgoing orchestrator releases the
    single-instance pidfile before the incoming one acquires it.
    """
    text = _scriptText()
    body = _stepBody(text, "step_restart_service")
    stopIdx = body.find("systemctl stop ${SERVICE_NAME}")
    startIdx = body.find("systemctl start ${SERVICE_NAME}")
    assert stopIdx > -1, (
        "step_restart_service must `systemctl stop ${SERVICE_NAME}` (US-389 "
        "release-then-acquire ordering)"
    )
    assert startIdx > -1, (
        "step_restart_service must `systemctl start ${SERVICE_NAME}` after the stop"
    )
    assert stopIdx < startIdx, (
        "the stop must precede the start (the guard refuses a double-start; a "
        "bare restart can race the still-dying old pid)"
    )


def test_us389_deployVersion_recordsSingleInstanceState():
    """step_write_deploy_version must thread the single-instance summary into
    the release record so .deploy-version is no longer silent on the
    matched-pair guard state (US-389 AC#4).
    """
    text = _scriptText()
    body = _stepBody(text, "step_write_deploy_version")
    assert "deploy_invariants.py" in body and "summarize" in body, (
        "step_write_deploy_version must summarize the single-instance state"
    )
    assert "--single-instance" in body, (
        "step_write_deploy_version must pass --single-instance to compose-record "
        "so the .deploy-version stamp records guardEnabled + runtimeDirectory"
    )


# -----------------------------------------------------------------------------
# US-395: F-103 deploy integration -- fold the splash state-server units +
# states-dir provisioning + splash assets/version.txt into deploy-pi.sh.
# -----------------------------------------------------------------------------


def test_us395_citedInScript():
    """The F-103 deploy integration must cite US-395 so archaeology can trace it."""
    text = _scriptText()
    assert "US-395" in text, "deploy-pi.sh must cite US-395 on the F-103 splash steps"


def test_us395_stateServerUnits_stepExists_installsBothUnits():
    """deploy-pi.sh must define a step that installs BOTH F-103 state-server
    units (eclipse-boot-state.service + eclipse-states-http.service) -- AC#1.
    """
    text = _scriptText()
    body = _stepBody(text, "step_install_state_server_units")
    assert "eclipse-boot-state.service" in body, (
        "step_install_state_server_units must install eclipse-boot-state.service"
    )
    assert "eclipse-states-http.service" in body, (
        "step_install_state_server_units must install eclipse-states-http.service"
    )


def test_us395_stateServerUnits_syncIfChangedAndEnabled():
    """The state-server units install must mirror the existing unit-install
    steps: cmp -s sync-if-changed, daemon-reload, enable --now (AC#1).
    """
    body = _stepBody(_scriptText(), "step_install_state_server_units")
    assert "cmp -s" in body, "must be sync-if-changed (cmp -s) like the sibling unit installers"
    assert "daemon-reload" in body, "must daemon-reload when a unit file changed"
    assert "enable --now" in body, "must enable --now both state-server units"


def test_us395_stateServerUnits_restartLongRunningServices():
    """The two state-server units are long-running Type=simple services -- they
    must restart on EVERY deploy so rsynced source changes actually run (US-354
    dead-code-in-memory lesson), not just on a unit-file diff.
    """
    body = _stepBody(_scriptText(), "step_install_state_server_units")
    assert "systemctl restart eclipse-states-http.service" in body, (
        "step_install_state_server_units must restart eclipse-states-http.service "
        "unconditionally (US-354 long-running-service restart class)"
    )
    assert "systemctl restart" in body and "eclipse-boot-state.service" in body, (
        "step_install_state_server_units must restart eclipse-boot-state.service too"
    )


def test_us395_statesTmpfiles_stepProvisionsRunDir():
    """AC#4 (Atlas C-5): deploy installs the tmpfiles.d provisioning mechanism
    that makes /run/eclipse-obd/states/ exist at EVERY boot -- NOT the
    deploy-time `install -d` alone (which tmpfs wipes on reboot).
    """
    body = _stepBody(_scriptText(), "step_install_states_tmpfiles")
    assert "eclipse-obd-states.conf" in body, (
        "must install deploy/eclipse-obd-states.conf"
    )
    assert "/etc/tmpfiles.d" in body, "must target /etc/tmpfiles.d"
    assert "systemd-tmpfiles --create" in body, (
        "must apply the tmpfiles entry immediately (systemd-tmpfiles --create) so "
        "/run/eclipse-obd/states exists without waiting for the next boot"
    )


def test_us395_splashAssets_writesVersionTxt():
    """AC#2: a version.txt must be written into the splash assets dir
    (/opt/splash) -- the kiosk version chip consumes it.
    """
    body = _stepBody(_scriptText(), "step_install_splash_assets")
    assert "version.txt" in body, "step_install_splash_assets must write version.txt"
    assert "/opt/splash" in body, "version.txt + assets land in /opt/splash"


def test_us395_splashAssets_warnsNotBlocksOnMissing():
    """AC#3 / A-9: missing splash assets must WARN and let the deploy CONTINUE,
    never BLOCK. The local-source guard must `return 0` (not exit non-zero) so a
    deploy without the splash kit still completes.
    """
    body = _stepBody(_scriptText(), "step_install_splash_assets")
    assert "specs/UI/dist/splash-pi" in body, (
        "step_install_splash_assets must source the splash kit from "
        "specs/UI/dist/splash-pi"
    )
    assert "WARN" in body, "missing assets must emit a WARN"
    # The whole point of A-9: the step must not contain a hard non-zero exit for
    # the missing-assets path. (`exit 0` / `return 0` are fine.)
    assert "exit 1" not in body, (
        "step_install_splash_assets must not BLOCK (exit non-zero) on missing assets (A-9)"
    )


def test_us395_splashSteps_wiredIntoMainFlow():
    """All three US-395 steps must be CALLED from the default-mode body, not just
    defined. A `step_*` name appearing only once = defined-but-never-invoked.
    """
    text = _scriptText()
    for step in (
        "step_install_states_tmpfiles",
        "step_install_splash_assets",
        "step_install_state_server_units",
    ):
        assert text.count(step) >= 2, (
            f"{step} must be both defined AND called in the main deploy flow"
        )
