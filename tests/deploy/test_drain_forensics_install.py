################################################################################
# File Name: test_drain_forensics_install.py
# Purpose/Description: US-277 acceptance gate.  Verifies that
#                      deploy/drain-forensics.service ships with the
#                      PYTHONPATH env (Spool's bonus fix; without it the
#                      `import src.pi.power.*` lines in scripts/drain_forensics.py
#                      fail silently and every fire is a no-op) and that
#                      deploy/deploy-pi.sh wires the systemd unit pair into
#                      the default-mode dispatch via a new
#                      step_install_drain_forensics_unit() function -- the
#                      Sprint-22 ship gap that forced Spool to run sudo cp
#                      + daemon-reload + enable mid-Drain-7.
#
#                      All assertions in this file would FAIL pre-US-277:
#                      drain-forensics.service did not contain PYTHONPATH,
#                      and deploy-pi.sh had no step_install_drain_forensics_unit
#                      function.  The dry-run integration test is the
#                      strongest end-to-end signal: it actually runs
#                      bash deploy/deploy-pi.sh --dry-run and asserts the
#                      new step's announcement lines appear, which would
#                      not be the case pre-fix because the function did
#                      not exist nor was it called from the dispatch body.
#
#                      Offline-safe: every test uses static file reads or
#                      the existing deploy-pi.sh --dry-run mode which
#                      never touches the network.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-03    | Rex          | Initial implementation (Sprint 23 US-277)
# ================================================================================
################################################################################

"""Acceptance tests for US-277: auto-wire drain-forensics systemd into deploy-pi.sh."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"
DRAIN_SERVICE = REPO_ROOT / "deploy" / "drain-forensics.service"
DRAIN_TIMER = REPO_ROOT / "deploy" / "drain-forensics.timer"

PI_PATH_LITERAL = "/home/mcornelison/Projects/Eclipse-01"


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


# ----------------------------------------------------------------------------
# Static content tests -- offline-safe; would FAIL pre-fix.
# ----------------------------------------------------------------------------

class TestDrainForensicsServicePythonPath:
    """drain-forensics.service must export PYTHONPATH so imports resolve."""

    def test_serviceFile_definesPythonpathEnvironment(self):
        """`Environment=PYTHONPATH=...` line is present in [Service] block."""
        body = DRAIN_SERVICE.read_text(encoding="utf-8")
        assert f"Environment=PYTHONPATH={PI_PATH_LITERAL}" in body, (
            f"drain-forensics.service is missing the PYTHONPATH env line; "
            f"systemd will launch the script without {PI_PATH_LITERAL} on "
            f"sys.path and `import src.pi.power.*` will silently fail."
        )

    def test_pythonpathEnv_matchesWorkingDirectory(self):
        """PYTHONPATH path must match WorkingDirectory (no path drift)."""
        body = DRAIN_SERVICE.read_text(encoding="utf-8")
        workingMatch = re.search(r"^WorkingDirectory=(.+)$", body, re.MULTILINE)
        pythonPathMatch = re.search(
            r"^Environment=PYTHONPATH=(.+)$", body, re.MULTILINE,
        )
        assert workingMatch is not None, "WorkingDirectory not found in service file"
        assert pythonPathMatch is not None, "PYTHONPATH env not found in service file"
        assert workingMatch.group(1).strip() == pythonPathMatch.group(1).strip(), (
            "PYTHONPATH must equal WorkingDirectory; otherwise running the "
            "script with `cd $WorkingDirectory && python scripts/...` would "
            "find different modules from launching it via `python /abs/scripts/...`."
        )


class TestDeployPiShDrainForensicsStep:
    """deploy-pi.sh must define + call step_install_drain_forensics_unit."""

    @pytest.fixture
    def deployScriptText(self) -> str:
        return DEPLOY_SCRIPT.read_text(encoding="utf-8")

    def test_functionDefined(self, deployScriptText: str):
        """`step_install_drain_forensics_unit() {` declaration present."""
        assert "step_install_drain_forensics_unit() {" in deployScriptText, (
            "deploy-pi.sh is missing the step_install_drain_forensics_unit "
            "function declaration -- the systemd unit pair will not be "
            "installed and Spool's mid-Drain-7 manual sudo dance will be "
            "needed again on the next deploy."
        )

    def test_functionCalledFromDispatchBody(self, deployScriptText: str):
        """The function must be invoked from the default-mode dispatch."""
        # Find the dispatch body (everything after the `### Mode dispatch`
        # comment + everything not inside a function definition is hard to
        # parse from bash without a real parser; instead assert the call
        # appears OUTSIDE of the function declaration line + appears AFTER
        # step_install_eclipse_obd_unit so the unit pair lands alongside
        # the main eclipse-obd unit).
        callOccurrences = [
            m.start() for m in re.finditer(
                r"^step_install_drain_forensics_unit\b",
                deployScriptText,
                re.MULTILINE,
            )
        ]
        # Expected: 1 declaration + 1 invocation = 2 occurrences.  If only
        # 1 the function is defined but never called.
        assert len(callOccurrences) >= 2, (
            f"step_install_drain_forensics_unit appears {len(callOccurrences)} time(s) "
            f"in deploy-pi.sh; expected 2+ (declaration + at least one call site). "
            f"Without a call site the function is dead code."
        )
        # Order check: the call site must be AFTER step_install_eclipse_obd_unit
        # in the dispatch body so the drain-forensics unit installs alongside
        # the main eclipse-obd unit (consistent ordering, easier to reason about).
        eclipseUnitMatches = [
            m.start() for m in re.finditer(
                r"^step_install_eclipse_obd_unit\b",
                deployScriptText,
                re.MULTILINE,
            )
        ]
        assert eclipseUnitMatches, "step_install_eclipse_obd_unit dispatch missing"
        eclipseUnitCallPos = eclipseUnitMatches[-1]
        drainCallPos = callOccurrences[-1]
        assert drainCallPos > eclipseUnitCallPos, (
            "step_install_drain_forensics_unit call must come AFTER "
            "step_install_eclipse_obd_unit in the dispatch body."
        )

    def test_functionInstallsBothUnitFiles(self, deployScriptText: str):
        """Function body references both .service AND .timer source paths."""
        # Slice the function body: from the declaration to the next top-level
        # function or section break.
        body = self._extractFunctionBody(deployScriptText)
        assert "drain-forensics.service" in body, (
            "Function does not reference drain-forensics.service"
        )
        assert "drain-forensics.timer" in body, (
            "Function does not reference drain-forensics.timer"
        )

    def test_functionProvisionsBothRuntimeDirs(self, deployScriptText: str):
        """Both /var/log/eclipse-obd and /var/run/eclipse-obd are created."""
        body = self._extractFunctionBody(deployScriptText)
        assert "/var/log/eclipse-obd" in body, (
            "Function does not provision /var/log/eclipse-obd (CSV target)"
        )
        assert "/var/run/eclipse-obd" in body, (
            "Function does not provision /var/run/eclipse-obd "
            "(orchestrator-state.json target; without this US-276's "
            "writer logs+skips on every tick)"
        )
        # Both `install -d` calls must be present.
        installDirCount = body.count("install -d")
        assert installDirCount >= 2, (
            f"Expected at least 2 `install -d` calls (one per dir); "
            f"got {installDirCount}"
        )

    def test_functionUsesIdempotentCmpPattern(self, deployScriptText: str):
        """`cmp -s` no-op-when-identical pattern present (mocks unit current)."""
        body = self._extractFunctionBody(deployScriptText)
        # The cmp -s short-circuit is the same pattern step_install_journald_persistent
        # and step_install_eclipse_obd_unit use; without it, every deploy
        # would re-install + daemon-reload even on no-change runs.
        assert "cmp -s" in body, (
            "Function lacks the `cmp -s` idempotency pattern; every deploy "
            "would trigger systemd churn even when the unit files have not "
            "changed."
        )

    def test_functionSyncsOnChange(self, deployScriptText: str):
        """`install -m 644` writes the unit when source != installed copy."""
        body = self._extractFunctionBody(deployScriptText)
        assert "install -m 644" in body, (
            "Function does not use `install -m 644` to write unit files "
            "(mocks unit absent: function should install)"
        )

    def test_functionRunsDaemonReloadAndEnable(self, deployScriptText: str):
        """daemon-reload + enable --now drain-forensics.timer present."""
        body = self._extractFunctionBody(deployScriptText)
        assert "daemon-reload" in body, (
            "Function does not call systemctl daemon-reload"
        )
        assert "enable --now drain-forensics.timer" in body, (
            "Function does not call `systemctl enable --now drain-forensics.timer` "
            "(without this the timer is installed but inactive)"
        )

    def test_runtimeDirsOwnedByMcornelison(self, deployScriptText: str):
        """Both runtime dirs are mcornelison-owned (US-276 writer requirement).

        Spool's spec said /var/run/eclipse-obd should be root:root, but the
        PowerDownOrchestrator writer in US-276 runs inside eclipse-obd.service
        as User=mcornelison, so root:root with default 0755 would block the
        write and silently break the whole purpose of US-276 + US-277.  This
        test pins the functionally-correct ownership.
        """
        body = self._extractFunctionBody(deployScriptText)
        # Both install -d calls must specify -o mcornelison -g mcornelison.
        # Use a regex so we tolerate flag-order variation (e.g., -g first).
        for runtimeDir in ("/var/log/eclipse-obd", "/var/run/eclipse-obd"):
            pattern = (
                r"install -d[^\n]*-o\s+mcornelison[^\n]*-g\s+mcornelison[^\n]*"
                + re.escape(runtimeDir)
            )
            assert re.search(pattern, body), (
                f"install -d for {runtimeDir} must specify "
                f"`-o mcornelison -g mcornelison` (found body):\n{body}"
            )

    @staticmethod
    def _extractFunctionBody(scriptText: str) -> str:
        """Return the body of step_install_drain_forensics_unit (without the
        following functions).  Bash function definitions in this file follow
        the ``name() {`` convention and end at a closing brace at column 0,
        followed by a blank line; slice from the declaration to the next
        ``^[a-z_]+\\(\\) \\{`` line.
        """
        startMatch = re.search(
            r"^step_install_drain_forensics_unit\(\) \{",
            scriptText,
            re.MULTILINE,
        )
        if not startMatch:
            return ""
        body = scriptText[startMatch.end():]
        endMatch = re.search(r"^[a-z_]+\(\) \{", body, re.MULTILINE)
        if endMatch:
            body = body[:endMatch.start()]
        return body


# ----------------------------------------------------------------------------
# Dry-run integration test -- offline-safe; would FAIL pre-fix because the
# new step's announcement lines did not exist.
# ----------------------------------------------------------------------------

@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
class TestDeployPiShDryRunAnnouncesNewStep:
    """`bash deploy-pi.sh --dry-run` must announce the drain-forensics step."""

    @pytest.fixture
    def dryRunOutput(self) -> str:
        result = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), "--dry-run"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Dry-run is offline-safe and must always exit 0.
        assert result.returncode == 0, (
            f"--dry-run exited {result.returncode} (stderr: {result.stderr})"
        )
        return result.stdout + result.stderr

    def test_dryRunHeaderMentionsUs277(self, dryRunOutput: str):
        """Step header line names US-277 so the deploy log is grep-able."""
        assert "US-277" in dryRunOutput, (
            "Dry-run output does not mention US-277; the new step's header "
            "is missing or the function never runs."
        )

    def test_dryRunAnnouncesVarLogDirCreation(self, dryRunOutput: str):
        assert (
            "install -d -o mcornelison -g mcornelison /var/log/eclipse-obd"
            in dryRunOutput
        ), "Dry-run does not announce /var/log/eclipse-obd provisioning"

    def test_dryRunAnnouncesVarRunDirCreation(self, dryRunOutput: str):
        assert (
            "install -d -o mcornelison -g mcornelison /var/run/eclipse-obd"
            in dryRunOutput
        ), "Dry-run does not announce /var/run/eclipse-obd provisioning"

    def test_dryRunAnnouncesServiceInstall(self, dryRunOutput: str):
        assert (
            "/etc/systemd/system/drain-forensics.service" in dryRunOutput
        ), "Dry-run does not announce drain-forensics.service install target"

    def test_dryRunAnnouncesTimerInstall(self, dryRunOutput: str):
        assert (
            "/etc/systemd/system/drain-forensics.timer" in dryRunOutput
        ), "Dry-run does not announce drain-forensics.timer install target"

    def test_dryRunAnnouncesTimerEnable(self, dryRunOutput: str):
        assert (
            "systemctl enable --now drain-forensics.timer" in dryRunOutput
        ), "Dry-run does not announce timer enable --now"

    def test_dryRunDoesNotCallRealSsh(self, dryRunOutput: str):
        """No real SSH attempts during dry-run (offline-safe contract)."""
        for forbidden in ("Permission denied", "Connection refused", "No route to host"):
            assert forbidden not in dryRunOutput, (
                f"Dry-run output contains '{forbidden}'; the dry-run guard "
                f"failed and the script attempted a real SSH connection."
            )


# ----------------------------------------------------------------------------
# Bash syntax check -- catches typos in the new function body that would
# only surface at deploy time.
# ----------------------------------------------------------------------------

@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_bashSyntaxValid():
    """`bash -n deploy-pi.sh` must succeed (parses cleanly)."""
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"bash -n failed (exit={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
