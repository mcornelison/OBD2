################################################################################
# File Name: test_persistent_state_dir_install.py
# Purpose/Description: US-667 acceptance gate -- deploy-pi.sh must provision
#                      /var/lib/eclipse-obd, the PERSISTENT state directory,
#                      with ownership correct for BOTH of its consuming
#                      services.
#
#   THE DEFECT.  ARCH-019's PLD transition witness writes to
#   /var/lib/eclipse-obd/pld-transition-witness.json.  Nothing in the deploy
#   ever created that directory, and the witness deliberately does NOT create
#   it (Atlas's dev-box guard: "a missing parent means we are not on a deployed
#   system", which stops a test run inventing C:\var\lib\eclipse-obd on
#   Windows).  Correct in the direction tested, blind in the direction that
#   matters -- a DEPLOYED Pi with the directory absent is indistinguishable
#   from a dev box under that rule.
#
#   MEASURED 2026-08-31 18:51: a real power-loss transition fired, powerwatch
#   ran the full sequenced shutdown, and the arm line on the next boot STILL
#   read 'ARMED (UNPROVEN)'.  `ls -ld /var/lib/eclipse-obd` -> No such file or
#   directory.  The witness never wrote.
#
#   ⚠️ GAP 5 (Atlas, 2026-09-03) -- THE DIRECTORY HAS TWO CONSUMERS, NOT ONE.
#   `pi.update.markerFilePath` = /var/lib/eclipse-obd/update-pending.json is
#   read/written by the update checker + applier, which run inside a DIFFERENT
#   systemd unit from the witness.  "Correct ownership" is underspecified until
#   you say correct FOR WHOM.  A directory created correctly for one consumer
#   and wrongly for the other reproduces this exact defect in the update
#   subsystem, where nobody has looked.
#
#   HOW THIS FILE ANSWERS THAT.  Every path and every service account here is
#   DERIVED from its SSOT, never restated:
#     - the witness path from pld_witness.DEFAULT_WITNESS_PATH
#     - the marker path from validator.DEFAULTS['pi.update.markerFilePath']
#     - each service account from the User= line of its own .service unit
#   So if a consumer's path moves, or either unit changes User=, these tests
#   fail rather than certifying a stale literal.  A copied constant is the
#   drift, not a shortcut.
#
#   Offline-safe: static file reads plus deploy-pi.sh --dry-run, which never
#   touches the network.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-03    | Rex (US-667) | Initial -- Sprint 80 persistent-state-dir gate.
# ================================================================================
################################################################################

"""Acceptance tests for US-667: deploy-pi.sh provisions /var/lib/eclipse-obd."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from src.common.config.validator import DEFAULTS
from src.pi.power.power_watch.pld_witness import DEFAULT_WITNESS_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"

#: The two consuming units.  Named here because the UNIT is what the deploy
#: provisions for; the ACCOUNT is read out of each unit file below rather than
#: restated, so a User= change breaks the test instead of slipping through.
WITNESS_UNIT = REPO_ROOT / "deploy" / "eclipse-powerwatch.service"
UPDATE_MARKER_UNIT = REPO_ROOT / "deploy" / "eclipse-obd.service"

#: Consumer paths, DERIVED from their SSOTs.  ``as_posix()`` because
#: DEFAULT_WITNESS_PATH is a pathlib.Path and str() yields backslashes on the
#: Windows bench -- which would never match a shell script.
WITNESS_PATH = PurePosixPath(DEFAULT_WITNESS_PATH.as_posix())
MARKER_PATH = PurePosixPath(DEFAULTS["pi.update.markerFilePath"])

STATE_DIR = WITNESS_PATH.parent

STEP_NAME = "step_install_persistent_state_dir"


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


def _serviceUser(unitPath: Path) -> str:
    """The ``User=`` a systemd unit runs as.

    Read from the unit rather than restated, so this file cannot drift away
    from the account the service actually uses.
    """
    body = unitPath.read_text(encoding="utf-8")
    match = re.search(r"^User=(.+)$", body, re.MULTILINE)
    assert match is not None, f"{unitPath.name} has no User= line"
    return match.group(1).strip()


def _extractFunctionBody(scriptText: str) -> str:
    """Return the body of the provisioning step, sliced to the next function."""
    startMatch = re.search(rf"^{STEP_NAME}\(\) \{{", scriptText, re.MULTILINE)
    if not startMatch:
        return ""
    body = scriptText[startMatch.end():]
    endMatch = re.search(r"^[a-z_]+\(\) \{", body, re.MULTILINE)
    if endMatch:
        body = body[:endMatch.start()]
    return body


def _extractRemoteBlock(scriptText: str) -> str:
    """The step body from ``remote "`` onwards, with comment lines dropped.

    Use this for any assertion about what the deploy DOES on the Pi.  The raw
    body also carries prose comments and ``DRY-RUN would: <the same command>``
    echoes, and both read exactly like performing the action -- measured on
    this script before (US-646), where it let a deleted ``rm -f`` pass.
    """
    body = _extractFunctionBody(scriptText)
    remoteMatch = re.search(r"^\s*remote \"", body, re.MULTILINE)
    assert remoteMatch, f"{STEP_NAME} has no `remote \"` block"
    return "\n".join(
        line
        for line in body[remoteMatch.end():].splitlines()
        if not line.strip().startswith("#")
    )


# ----------------------------------------------------------------------------
# The two consumers agree on a directory -- the premise the whole story rests
# on.  If these ever diverge, ONE provisioning step can no longer serve both
# and the rest of this file is asserting the wrong thing.
# ----------------------------------------------------------------------------

class TestTheDirectoryHasExactlyTwoKnownConsumers:
    """Gap 5: name both consumers, and prove they share one directory."""

    def test_witnessAndUpdateMarker_shareOneParentDirectory(self):
        """Both SSOT paths resolve under the SAME directory.

        Derived, not restated.  A future story that moves either consumer
        elsewhere must confront this test rather than silently leave the
        deploy provisioning a directory only one of them uses.
        """
        assert MARKER_PATH.parent == STATE_DIR, (
            f"the update marker ({MARKER_PATH}) and the PLD witness "
            f"({WITNESS_PATH}) no longer share a parent directory. One "
            f"`install -d` can no longer serve both consumers -- US-667's "
            f"single-step fix is invalid and the deploy needs revisiting."
        )

    def test_theSharedDirectoryIsUnderVarLib_notATmpfs(self):
        """/run and /var/run are wiped on reboot; the witness must survive one.

        The witness answers 'has the pin EVER been seen to move'. A record
        forgotten at poweroff is no better than never recording it -- and the
        boot AFTER the event is exactly when it is read.
        """
        assert str(STATE_DIR).startswith("/var/lib/"), (
            f"persistent state moved to {STATE_DIR}, which is not under "
            f"/var/lib. If this is now a tmpfs the witness cannot survive the "
            f"reboot it exists to be read on."
        )


# ----------------------------------------------------------------------------
# Static content tests -- offline-safe; ALL would FAIL pre-US-667, because
# deploy-pi.sh had no persistent-state-dir step at all.
# ----------------------------------------------------------------------------

class TestDeployPiShProvisionsThePersistentStateDir:
    """deploy-pi.sh must define + call the provisioning step."""

    @pytest.fixture
    def deployScriptText(self) -> str:
        return DEPLOY_SCRIPT.read_text(encoding="utf-8")

    def test_functionDefined(self, deployScriptText: str):
        """The step exists at all. Pre-fix: it did not."""
        assert f"{STEP_NAME}() {{" in deployScriptText, (
            f"deploy-pi.sh is missing the {STEP_NAME} function -- "
            f"{STATE_DIR} is never created and the PLD witness silently "
            f"never writes, leaving the arm line permanently UNPROVEN."
        )

    def test_functionCalledFromDispatchBody(self, deployScriptText: str):
        """Declared AND invoked. A defined-but-uncalled step is dead code."""
        occurrences = [
            m.start()
            for m in re.finditer(rf"^{STEP_NAME}\b", deployScriptText, re.MULTILINE)
        ]
        assert len(occurrences) >= 2, (
            f"{STEP_NAME} appears {len(occurrences)} time(s) in deploy-pi.sh; "
            f"expected 2+ (declaration + at least one call site). Without a "
            f"call site the function is dead code and the directory is still "
            f"never created."
        )

    def test_provisioningRunsBeforeBothConsumingUnitsAreInstalled(
        self, deployScriptText: str,
    ):
        """Order matters, and it matters for BOTH consumers.

        The directory has to exist before either service is installed and
        started, or the first power-loss / update check after a fresh deploy
        races the provisioning it depends on.
        """
        callPositions = [
            m.start()
            for m in re.finditer(rf"^{STEP_NAME}\b", deployScriptText, re.MULTILINE)
        ]
        assert len(callPositions) >= 2, "no dispatch call site to order against"
        provisionCall = callPositions[-1]

        for consumerStep in (
            "step_install_eclipse_obd_unit",
            "step_install_power_watch_unit",
        ):
            consumerCalls = [
                m.start()
                for m in re.finditer(
                    rf"^{consumerStep}\b", deployScriptText, re.MULTILINE,
                )
            ]
            assert consumerCalls, f"{consumerStep} dispatch call missing"
            assert provisionCall < consumerCalls[-1], (
                f"{STEP_NAME} is dispatched AFTER {consumerStep}. "
                f"{STATE_DIR} must exist before its consuming service is "
                f"installed and started."
            )

    def test_functionCreatesTheDirectoryDerivedFromTheSsot(
        self, deployScriptText: str,
    ):
        """`install -d` targets exactly the directory the SSOTs point at.

        The path is interpolated from DEFAULT_WITNESS_PATH, so moving the
        witness without moving the deploy fails here.
        """
        body = _extractRemoteBlock(deployScriptText)
        assert re.search(rf"install -d[^\n]*{re.escape(str(STATE_DIR))}", body), (
            f"the step's remote block never runs `install -d` against "
            f"{STATE_DIR} (the parent of both {WITNESS_PATH.name} and "
            f"{MARKER_PATH.name}). Found body:\n{body}"
        )

    def test_ownershipMatchesTheServiceAccountOfBothConsumers(
        self, deployScriptText: str,
    ):
        """⚠️ GAP 5: correct ownership -- correct FOR WHOM?

        Both consuming units are read for their User=. This test states the
        answer as a DERIVED fact: whatever account those units run as is the
        account the directory must be owned by. Today both are the same
        account, so one `install -d` serves both; if a future change splits
        them, the assertion below fires and forces the group/mode question to
        be answered rather than assumed.
        """
        witnessUser = _serviceUser(WITNESS_UNIT)
        markerUser = _serviceUser(UPDATE_MARKER_UNIT)

        assert witnessUser == markerUser, (
            f"the two consumers of {STATE_DIR} now run as DIFFERENT accounts "
            f"({WITNESS_UNIT.name}={witnessUser}, "
            f"{UPDATE_MARKER_UNIT.name}={markerUser}). A single owner can no "
            f"longer satisfy both -- the directory needs a shared group and a "
            f"group-writable mode, and US-667's single `install -d -o/-g` is "
            f"no longer sufficient. This is the exact latent failure Gap 5 "
            f"named; do not 'fix' it by picking one account."
        )

        body = _extractRemoteBlock(deployScriptText)
        pattern = (
            r"install -d[^\n]*-o\s+" + re.escape(witnessUser)
            + r"[^\n]*-g\s+" + re.escape(witnessUser)
            + r"[^\n]*" + re.escape(str(STATE_DIR))
        )
        assert re.search(pattern, body), (
            f"`install -d` for {STATE_DIR} must specify "
            f"-o {witnessUser} -g {witnessUser} -- the account BOTH "
            f"{WITNESS_UNIT.name} and {UPDATE_MARKER_UNIT.name} run as. "
            f"root:root with default 0755 would block both writers. Found "
            f"body:\n{body}"
        )

    def test_provisioningIsNotGatedOnAnyServiceFileBeingPresent(
        self, deployScriptText: str,
    ):
        """The directory is created UNCONDITIONALLY.

        The neighbouring drain-forensics step puts its `install -d` calls
        AFTER an `exit 0` guard on its own unit file being present -- so a
        deploy missing that one unit silently skips provisioning unrelated
        directories. Persistent state must not inherit that coupling: this
        step owns a directory two OTHER services depend on.
        """
        body = _extractRemoteBlock(deployScriptText)
        installPos = body.find("install -d")
        assert installPos != -1, "no `install -d` in the remote block"
        preamble = body[:installPos]
        assert "exit 0" not in preamble, (
            f"the remote block can `exit 0` BEFORE creating {STATE_DIR}, so "
            f"some unrelated precondition can silently skip provisioning. "
            f"Preamble:\n{preamble}"
        )

    def test_deployVerifiesBothConsumerPathsAreWritable(
        self, deployScriptText: str,
    ):
        """⚠️ GAP 5: assert the UPDATE MARKER path, not only the witness path.

        Creating the directory is not the same as proving either service can
        write into it -- an existing root-owned directory from an earlier
        hand-creation survives `install -d` with its ownership intact. The
        deploy must CHECK, and it must check both consumers, because a
        directory correct for one and wrong for the other reproduces this
        defect in the update subsystem where nobody has looked.
        """
        body = _extractRemoteBlock(deployScriptText)
        for consumerPath in (WITNESS_PATH, MARKER_PATH):
            assert str(consumerPath) in body, (
                f"the deploy step never mentions {consumerPath} in what it "
                f"actually RUNS on the Pi. Both consumer paths must be "
                f"verified writable after provisioning, not just the "
                f"directory created."
            )

    def test_provisioningFailureIsLoudNotSilent(self, deployScriptText: str):
        """A provisioning step that cannot provision must SAY SO.

        The whole story is a silent failure. A fix whose own failure mode is
        also silent has moved the problem rather than removed it.
        """
        body = _extractRemoteBlock(deployScriptText)
        assert "WARN" in body or ">&2" in body, (
            f"the step emits no warning on any failure path. If "
            f"{STATE_DIR} cannot be created or is not writable, the deploy "
            f"log must say so -- otherwise the next UNPROVEN arm line is "
            f"again unexplainable."
        )


# ----------------------------------------------------------------------------
# Dry-run integration -- offline-safe; would FAIL pre-fix because the step
# did not exist to announce anything.
# ----------------------------------------------------------------------------

@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
class TestDeployPiShDryRunAnnouncesTheProvisioning:
    """`bash deploy-pi.sh --dry-run` must announce the new step."""

    @pytest.fixture
    def dryRunOutput(self) -> str:
        result = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), "--dry-run"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"--dry-run exited {result.returncode} (stderr: {result.stderr})"
        )
        return result.stdout + result.stderr

    def test_dryRunAnnouncesTheDirectoryCreation(self, dryRunOutput: str):
        """The operator can see the provisioning coming before it happens."""
        witnessUser = _serviceUser(WITNESS_UNIT)
        expected = (
            f"install -d -o {witnessUser} -g {witnessUser} {STATE_DIR}"
        )
        assert expected in dryRunOutput, (
            f"Dry-run does not announce {STATE_DIR} provisioning "
            f"(expected the line '{expected}')"
        )

    def test_dryRunNamesUs667(self, dryRunOutput: str):
        """Step header names the story so the deploy log is grep-able."""
        assert "US-667" in dryRunOutput, (
            "Dry-run output does not mention US-667; the step's header is "
            "missing or the function never runs."
        )

    def test_dryRunNamesBothConsumers(self, dryRunOutput: str):
        """Gap 5, visible to the operator reading the deploy log.

        Both consumers are named in the announcement, so nobody reading the
        log concludes this directory belongs to the witness alone.
        """
        for consumerPath in (WITNESS_PATH, MARKER_PATH):
            assert str(consumerPath) in dryRunOutput, (
                f"Dry-run never names {consumerPath}. The operator cannot "
                f"tell that this directory has two consumers."
            )

    def test_dryRunDoesNotCallRealSsh(self, dryRunOutput: str):
        """No real SSH attempts during dry-run (offline-safe contract)."""
        for forbidden in (
            "Permission denied", "Connection refused", "No route to host",
        ):
            assert forbidden not in dryRunOutput, (
                f"Dry-run output contains '{forbidden}'; the dry-run guard "
                f"failed and the script attempted a real SSH connection."
            )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_bashSyntaxValid():
    """`bash -n deploy-pi.sh` must succeed -- catches typos in the new body.

    A syntax error in the new function would otherwise only surface at deploy
    time, on the Pi, in the car.
    """
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"bash -n failed (exit={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
