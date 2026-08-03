################################################################################
# File Name: test_set_gpu_cma.py
# Purpose/Description: pytest wrapper + deploy-wiring guards for the US-524
#                      GPU CMA boot-config step. Drives
#                      tests/deploy/test_set_gpu_cma.sh via subprocess so the
#                      bash scenarios (fixture config.txt files behind the
#                      $PI_CONFIG_TXT seam) run in the fast suite, and pins
#                      that deploy-pi.sh actually DEFINES and CALLS the step
#                      after sync_tree.
#
#                      Mirrors the test_deploy_pi_eeprom_config.py pattern: the
#                      bash script is the source of truth for behavioural
#                      assertions; this file is the pytest entry point and adds
#                      the static wiring guards bash cannot express cleanly.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Rex          | Initial implementation (Sprint 70 US-524)
# ================================================================================
################################################################################

"""pytest wrapper around tests/deploy/test_set_gpu_cma.sh + deploy wiring guards.

The .sh script is the canonical assertion catalog (12 scenarios over synthetic
/boot/firmware/config.txt fixtures: the live Pi's shape, idempotent re-run,
foreign cma- param, the -pi5 overlay variant, commented-out and wrong-section
lines, missing file, unsupported size, pristine-backup semantics).

The Python guards here cover the OTHER half of the story, which the bash
catalog structurally cannot: a byte-perfect set-gpu-cma.sh that deploy-pi.sh
never invokes ships nothing. That is the recurring "two correct halves, never
connected" defect class (US-494/499/502/503/505/513).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_SCRIPT = REPO_ROOT / "tests" / "deploy" / "test_set_gpu_cma.sh"
CMA_SCRIPT = REPO_ROOT / "deploy" / "set-gpu-cma.sh"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"

STEP_NAME = "step_set_gpu_cma"


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


def _readDeployScript() -> str:
    """Return deploy-pi.sh text."""
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _codeLines(text: str) -> list[str]:
    """Return only executable-looking lines: comments and blanks stripped.

    US-501/US-513/US-522 lesson: a guard that greps raw file text is satisfied
    by the explanatory COMMENT that documents the thing it is checking for. All
    wiring assertions below run against this stripped view so a comment
    mentioning `step_set_gpu_cma` can never make them pass.
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
def test_setGpuCma_allScenariosPass():
    """The bash test (test_set_gpu_cma.sh) must exit 0.

    Given: 12 synthetic config.txt fixtures behind the $PI_CONFIG_TXT seam
    When: deploy/set-gpu-cma.sh is run against each
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
        f"set-gpu-cma bash catalog failed (exit {result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "failed" in result.stdout, "expected a results summary line"
    assert re.search(r"===\s*Results:\s*\d+\s*passed,\s*0\s*failed", result.stdout), (
        f"expected a zero-failure summary, got:\n{result.stdout[-600:]}"
    )


# --------------------------------------------------------------------------
# Wiring guards -- the half the bash catalog cannot see
# --------------------------------------------------------------------------


def test_setGpuCma_scriptExistsAndIsExecutableBash():
    """The production script exists and is a bash script."""
    assert CMA_SCRIPT.exists(), f"missing production script: {CMA_SCRIPT}"
    firstLine = CMA_SCRIPT.read_text(encoding="utf-8").splitlines()[0]
    assert firstLine.startswith("#!"), "set-gpu-cma.sh needs a shebang"
    assert "bash" in firstLine, f"expected a bash shebang, got: {firstLine}"


def test_deployPi_definesAndCallsTheCmaStep():
    """deploy-pi.sh must both DEFINE and CALL step_set_gpu_cma.

    A definition with no call site is the exact shape of a fix that passes
    every test and ships nothing.
    """
    lines = _codeLines(_readDeployScript())
    definitions = [ln for ln in lines if ln.startswith(f"{STEP_NAME}()")]
    calls = [ln for ln in lines if ln == STEP_NAME]
    assert len(definitions) == 1, f"expected exactly 1 definition of {STEP_NAME}, got {definitions}"
    assert len(calls) == 1, f"expected exactly 1 call to {STEP_NAME}, got {calls}"


def test_deployPi_callsCmaStepAfterSyncTree():
    """The call site must come AFTER sync_tree.

    set-gpu-cma.sh is executed ON THE PI from ${PI_PATH}/deploy/. If the step
    ran before the tree was rsynced, a first-ever deploy would invoke a file
    that is not there yet. Asserted against deploy-pi.sh's own call order --
    the artifact that ENFORCES the ordering, not a manifest that describes it
    (US-513 lesson).
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


def test_deployPi_cmaStepHonoursDryRun():
    """The step must have a DRY_RUN branch that returns before touching the Pi.

    A deploy --dry-run that rewrites the boot partition would be a genuinely
    destructive surprise.
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
    assert "set-gpu-cma.sh" in body, f"{STEP_NAME} must invoke deploy/set-gpu-cma.sh"


def test_setGpuCma_defaultsTo256M():
    """The default CMA size is 256 MB (US-524 AC1)."""
    text = CMA_SCRIPT.read_text(encoding="utf-8")
    assert re.search(r'ECLIPSE_CMA_MB:-256', text), (
        "set-gpu-cma.sh must default to 256 MB"
    )


def test_setGpuCma_neverWritesCmdlineTxt():
    """The script must not touch cmdline.txt.

    US-524 AC1 lists both mechanisms; config.txt was chosen because a bad
    overlay param is recoverable (dark display, SSH alive) while a corrupted
    cmdline.txt can break root= on a headless Pi. Pin the choice so a later
    edit cannot quietly move to the unrecoverable surface. Comments are
    stripped first so the rationale text above does not satisfy the guard.
    """
    lines = _codeLines(CMA_SCRIPT.read_text(encoding="utf-8"))
    offenders = [ln for ln in lines if "cmdline.txt" in ln]
    assert not offenders, f"set-gpu-cma.sh must not reference cmdline.txt: {offenders}"


def test_setGpuCma_refusesUnsupportedSizesBeforeWriting():
    """The supported-size allowlist matches the Pi's overlay README.

    Grounded on /boot/firmware/overlays/README from the live Pi 2026-08-03:
    vc4-kms-v3d accepts cma-64/96/128/192/256/320/384/448/512. An unsupported
    value makes the firmware reject the overlay -> no KMS driver -> dark
    display, so it must be refused before anything is written.
    """
    text = CMA_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r'SUPPORTED_CMA_SIZES="([^"]+)"', text)
    assert match, "set-gpu-cma.sh must declare SUPPORTED_CMA_SIZES"
    sizes = set(match.group(1).split())
    assert sizes == {"64", "96", "128", "192", "256", "320", "384", "448", "512"}, (
        f"allowlist drifted from the overlay README: {sorted(sizes, key=int)}"
    )
