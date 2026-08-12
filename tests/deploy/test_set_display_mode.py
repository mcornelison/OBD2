################################################################################
# File Name: test_set_display_mode.py
# Purpose/Description: pytest wrapper + deploy-wiring guards for the US-552
#                      HDMI/KMS output-mode pin. Drives
#                      tests/deploy/test_set_display_mode.sh via subprocess so
#                      the bash scenarios (synthetic /sys/class/drm and
#                      cmdline.txt fixtures behind the $PI_DRM_DIR /
#                      $PI_CMDLINE_TXT seams) run in the fast suite, and pins
#                      that deploy-pi.sh actually DEFINES and CALLS the step
#                      after sync_tree.
#
#                      Mirrors test_set_gpu_cma.py: the bash script is the
#                      source of truth for behavioural assertions; this file is
#                      the pytest entry point and adds the static guards bash
#                      cannot express -- including the one that grounds the
#                      target resolution against the hardware reference instead
#                      of against another copy of the same literal.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-11    | Rex          | Initial implementation (Sprint 74 US-552)
# ================================================================================
################################################################################

"""pytest wrapper around tests/deploy/test_set_display_mode.sh + wiring guards.

The .sh script is the canonical assertion catalog (14 scenarios over synthetic
sysfs / cmdline.txt fixtures: the live shape, idempotent re-run, a foreign
video= token, the three safety interlocks that write nothing, a malformed boot
cmdline, connector discovery, pristine-backup semantics, mode parameterisation).

The Python guards here cover the other half, which the bash catalog structurally
cannot: a byte-perfect set-display-mode.sh that deploy-pi.sh never invokes ships
nothing. That is the recurring "two correct halves, never connected" defect
class (US-494/499/502/503/505/513/524).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_SCRIPT = REPO_ROOT / "tests" / "deploy" / "test_set_display_mode.sh"
MODE_SCRIPT = REPO_ROOT / "deploy" / "set-display-mode.sh"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"
HARDWARE_REF = REPO_ROOT / "docs" / "hardware-reference.md"

STEP_NAME = "step_set_display_mode"


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


def _readDeployScript() -> str:
    """Return deploy-pi.sh text."""
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _codeLines(text: str) -> list[str]:
    """Return only executable-looking lines: comments and blanks stripped.

    US-501/US-513/US-522 lesson: a guard that greps raw file text is satisfied
    by the explanatory COMMENT that documents the thing it is checking for.
    This script's header talks at length about connectors and cmdline.txt, so
    every assertion below runs against the stripped view.
    """
    out = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


# --------------------------------------------------------------------------
# Behavioural catalog (the real gate)
# --------------------------------------------------------------------------


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_setDisplayMode_allScenariosPass():
    """The bash test (test_set_display_mode.sh) must exit 0.

    Given: 14 synthetic sysfs + cmdline.txt fixtures behind the env seams
    When: deploy/set-display-mode.sh is run against each
    Then: every scenario's exit code, file mutation and message assertion holds
    """
    assert TEST_SCRIPT.exists(), f"missing bash catalog: {TEST_SCRIPT}"
    result = subprocess.run(
        ["bash", str(TEST_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"set-display-mode bash catalog failed (exit {result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert re.search(r"===\s*Results:\s*\d+\s*passed,\s*0\s*failed", result.stdout), (
        f"expected a zero-failure summary, got:\n{result.stdout[-600:]}"
    )


# --------------------------------------------------------------------------
# Wiring guards -- the half the bash catalog cannot see
# --------------------------------------------------------------------------


def test_setDisplayMode_scriptExistsAndIsExecutableBash():
    """The production script exists and is a bash script."""
    assert MODE_SCRIPT.exists(), f"missing production script: {MODE_SCRIPT}"
    firstLine = MODE_SCRIPT.read_text(encoding="utf-8").splitlines()[0]
    assert firstLine.startswith("#!"), "set-display-mode.sh needs a shebang"
    assert "bash" in firstLine, f"expected a bash shebang, got: {firstLine}"


def test_deployPi_definesAndCallsTheDisplayModeStep():
    """deploy-pi.sh must both DEFINE and CALL step_set_display_mode.

    A definition with no call site is the exact shape of a fix that passes
    every test and ships nothing.
    """
    lines = _codeLines(_readDeployScript())
    definitions = [ln for ln in lines if ln.startswith(f"{STEP_NAME}()")]
    calls = [ln for ln in lines if ln == STEP_NAME]
    assert len(definitions) == 1, f"expected exactly 1 definition of {STEP_NAME}, got {definitions}"
    assert len(calls) == 1, f"expected exactly 1 call to {STEP_NAME}, got {calls}"


def test_deployPi_callsDisplayModeStepAfterSyncTree():
    """The call site must come AFTER sync_tree.

    set-display-mode.sh is executed ON THE PI from ${PI_PATH}/deploy/. If the
    step ran before the tree was rsynced, a first-ever deploy would invoke a
    file that is not there yet. Asserted against deploy-pi.sh's own call order
    -- the artifact that ENFORCES the ordering, not a manifest describing it.
    """
    lines = _codeLines(_readDeployScript())
    callIdx = [i for i, ln in enumerate(lines) if ln == STEP_NAME]
    syncIdx = [i for i, ln in enumerate(lines) if ln == "sync_tree"]
    assert callIdx, f"{STEP_NAME} is never called"
    assert syncIdx, "sync_tree is never called -- ordering guard cannot be evaluated"
    assert min(syncIdx) < callIdx[0], (
        f"{STEP_NAME} (line index {callIdx[0]}) must run after sync_tree "
        f"(line index {min(syncIdx)})"
    )


def test_deployPi_displayModeStepHonoursDryRun():
    """The step must have a DRY_RUN branch that returns before touching the Pi.

    A deploy --dry-run that rewrites the boot cmdline would be a genuinely
    destructive surprise -- more so here than for the CMA step, since this file
    is the one whose corruption costs a bootable Pi.
    """
    text = _readDeployScript()
    start = text.index(f"{STEP_NAME}()")
    end = text.index("\nstep_", start + 1)
    body = text[start:end]
    assert "$DRY_RUN" in body, f"{STEP_NAME} has no DRY_RUN branch"
    dryIdx = body.index("$DRY_RUN")
    remoteIdx = body.index("remote ")
    assert dryIdx < remoteIdx, "the DRY_RUN guard must precede the remote invocation"
    assert "return 0" in body[dryIdx:remoteIdx], "the DRY_RUN branch must return before remote"
    assert "set-display-mode.sh" in body, f"{STEP_NAME} must invoke deploy/set-display-mode.sh"


def test_setDisplayMode_defaultTargetMatchesTheDocumentedPanelResolution():
    """The default target mode is the panel's DOCUMENTED native resolution.

    Grounded against docs/hardware-reference.md (the OSOYOO 3.5" HDMI panel
    spec table), not against a second copy of the same literal in this test.
    US-552's whole premise is that the output should match the PANEL -- so if
    the panel on record ever changes, this guard goes red and the default has
    to be re-derived rather than silently continuing to pin 480x320 at a screen
    that is no longer 480x320.
    """
    doc = HARDWARE_REF.read_text(encoding="utf-8")
    match = re.search(r"\|\s*Resolution\s*\|\s*(\d+)\s*x\s*(\d+)\s*pixels\s*\|", doc)
    assert match, "could not find the panel resolution row in docs/hardware-reference.md"
    documented = f"{match.group(1)}x{match.group(2)}"

    text = MODE_SCRIPT.read_text(encoding="utf-8")
    default = re.search(r"ECLIPSE_DISPLAY_MODE:-([0-9]+x[0-9]+)", text)
    assert default, "set-display-mode.sh must declare an ECLIPSE_DISPLAY_MODE default"
    assert default.group(1) == documented, (
        f"default target {default.group(1)} does not match the documented panel "
        f"resolution {documented}"
    )


def test_setDisplayMode_neverHardCodesAConnectorName():
    """The connector must be DISCOVERED from sysfs, never assumed.

    A Pi 5 has two micro-HDMI ports. Pinning `video=HDMI-A-1:...` when the panel
    is on the other one is a silent no-op that still prints "applied" -- the
    failure mode this story's whole point (render 1:1) would quietly not get.
    Comments are stripped first, since the header explains the ports at length.
    """
    lines = _codeLines(MODE_SCRIPT.read_text(encoding="utf-8"))
    offenders = [ln for ln in lines if re.search(r"HDMI-A-[0-9]", ln)]
    assert not offenders, f"set-display-mode.sh must not hard-code a connector: {offenders}"


def test_setDisplayMode_guardsRootArgumentInExecutableCode():
    """`root=` preservation must be enforced in code, not just promised in prose.

    This is the token whose loss leaves a headless Pi unbootable, and it is the
    reason US-524 refused this file outright. The guard exists so a later
    simplification cannot drop the check while leaving the reassuring header
    comment in place.
    """
    lines = _codeLines(MODE_SCRIPT.read_text(encoding="utf-8"))
    rootChecks = [ln for ln in lines if "root=" in ln]
    assert rootChecks, "set-display-mode.sh must check for root= in executable code"


def test_setDisplayMode_neverExitsNonZeroOnADeliberateNoOp():
    """Every "did not pin" path must exit 0 so a bench deploy cannot be halted.

    deploy-pi.sh runs under `set -e`, so a non-zero exit stops the whole deploy.
    A Pi on the bench with no panel attached, or one whose operator pinned their
    own mode, is not a deploy failure. Non-zero is reserved for a malformed boot
    cmdline (1) and a failed write (2) -- both of which MUST stop the deploy
    before anyone reboots the Pi. Asserted structurally: the exit codes the
    script declares are exactly {0, 1, 2}.
    """
    lines = _codeLines(MODE_SCRIPT.read_text(encoding="utf-8"))
    codes = set()
    for line in lines:
        match = re.match(r"exit\s+([0-9]+)$", line)
        if match:
            codes.add(int(match.group(1)))
    assert codes == {0, 1, 2}, (
        f"expected exit codes {{0, 1, 2}}, found {sorted(codes)} -- a third failure "
        "code would halt a deploy on a path the story says is a no-op"
    )
